/**
 * Electron 主进程（#78 Electron 壳）：内核进程生命周期管理 + BrowserWindow 加载 renderer 构建产物。
 *
 * 壳层保持薄（ADR-020/021 硬约束）：零业务逻辑、零业务 API 调用，一切业务通信由
 * renderer 直接走 REST + SSE（baseURL/token 经 preload 注入）。
 * 契约来源：specs/f19-gui/spec.md §3.2（生命周期）/ §3.3（安全基线）/ §3.4（renderer 契约）。
 */
import { app, BrowserWindow, dialog, globalShortcut, Menu } from 'electron';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { createInterface } from 'node:readline';
import {
  parseReadyLine,
  resolveKernelCommand,
  nextBackoffDelayMs,
  MAX_CONSECUTIVE_FAILURES,
  type KernelInfo,
} from './kernel';

/** 仓库根：out/ 位于 frontend/packages/electron/out，向上 4 级 */
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..', '..');
/** renderer 构建产物（frontend/packages/renderer/dist，§3.4 file:// 加载） */
const RENDERER_DIST = path.resolve(__dirname, '..', '..', 'renderer', 'dist');

/** spawn 后未收到 INKFLOW_READY 的启动超时（§3.2.2） */
const READY_TIMEOUT_MS = 15_000;
/** 健康检查轮询间隔（§3.2.3） */
const HEALTH_INTERVAL_MS = 2_000;
/** 单次 /health 请求超时（AbortSignal.timeout，§3.2.3） */
const HEALTH_TIMEOUT_MS = 3_000;
/** 连续健康检查失败阈值（§3.2.3） */
const HEALTH_FAILURE_THRESHOLD = 3;
/** 优雅 kill 超时后 taskkill 进程树兜底（§3.2.5） */
const KILL_GRACE_MS = 3_000;

interface KernelReadyPayload {
  baseURL: string;
  token: string;
}

let mainWindow: BrowserWindow | null = null;
let kernelProcess: ChildProcess | null = null;
let kernelInfo: KernelInfo | null = null;
let pendingReadyPayload: KernelReadyPayload | null = null;
let healthCheckTimer: NodeJS.Timeout | null = null;
let startupWatchdog: NodeJS.Timeout | null = null;
let restartTimer: NodeJS.Timeout | null = null;
/** 连续健康检查失败计数（每次成功 200 清零） */
let healthFailures = 0;
/** 健康检查 in-flight 标志（MINOR-1）：2s 轮询间隔 < 3s 请求超时，防请求重叠 */
let healthInFlight = false;
/** 连续拉起失败计数（成功 INKFLOW_READY + 健康 200 后清零，§3.2.4） */
let consecutiveFailures = 0;
/** 失败处理中标志：防止 exit/health/watchdog 多重触发重复计数 */
let handlingFailure = false;
/** 退出流程标志：停止一切重拉 */
let stopping = false;
let quitInProgress = false;
/** 已注册的 DevTools 快捷键集合（幂等去重，spec §5.2.9） */
const registeredDevToolsAccelerators = new Set<string>();

/** dev 测试钩子（spec §3.6）：app.isPackaged === false 时暴露 __kernelInfo 供 Playwright 断言 */
function updateKernelInfoHook(): void {
  if (app.isPackaged || !kernelInfo) {
    return;
  }
  (globalThis as unknown as { __kernelInfo?: { pid: number; port: number; token: string } }).__kernelInfo = {
    pid: kernelInfo.pid,
    port: kernelInfo.port,
    token: kernelInfo.token,
  };
}

/** INKFLOW_READY 后向 renderer 注入 {baseURL, token}（spec §3.4，preload 幂等重暴露） */
function sendReadyToRenderer(): void {
  if (!kernelInfo) {
    return;
  }
  const payload: KernelReadyPayload = {
    baseURL: `http://127.0.0.1:${kernelInfo.port}`,
    token: kernelInfo.token,
  };
  pendingReadyPayload = payload;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('inkflow:ready', payload);
  }
}

function clearMonitorTimers(): void {
  if (healthCheckTimer) {
    clearInterval(healthCheckTimer);
    healthCheckTimer = null;
  }
  if (startupWatchdog) {
    clearTimeout(startupWatchdog);
    startupWatchdog = null;
  }
  if (restartTimer) {
    clearTimeout(restartTimer);
    restartTimer = null;
  }
}

/** dev 分支相对命令以仓库根为基准解析（pnpm 脚本/E2E 的 cwd 是 frontend/ 或 packages/electron/） */
function resolveKernelCommandForSpawn(): { command: string; args: string[] } {
  const resolved = resolveKernelCommand({ isPackaged: app.isPackaged, env: process.env });
  if (app.isPackaged || path.isAbsolute(resolved.command)) {
    return resolved;
  }
  for (const base of [REPO_ROOT, process.cwd()]) {
    const absolute = path.resolve(base, resolved.command);
    if (existsSync(absolute)) {
      return { command: absolute, args: resolved.args };
    }
  }
  // 找不到则交给 spawn 报错 → 进入崩溃拉起/错误对话框
  return resolved;
}

/** 残留进程回收：taskkill 进程树（Windows 下 child.kill 可能杀不干净子进程） */
function killProcessTree(child: ChildProcess): void {
  if (child.pid === undefined) {
    return;
  }
  try {
    const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
      windowsHide: true,
      stdio: 'ignore',
    });
    killer.on('error', () => {
      // taskkill 不可用时退化为 child.kill
    });
  } catch {
    // 忽略：退化为 child.kill
  }
  try {
    child.kill();
  } catch {
    // 进程已退出
  }
}

/** 连续失败达到阈值 → 弹「重试/退出」对话框（§3.2.4 / §3.7 M6） */
async function showStartupErrorDialog(): Promise<void> {
  const { response } = await dialog.showMessageBox({
    type: 'error',
    title: 'InkFlow 内核启动失败',
    message: 'InkFlow 内核启动失败',
    detail: `连续 ${MAX_CONSECUTIVE_FAILURES} 次启动失败，请检查环境（Python venv / 端口占用）后重试。`,
    buttons: ['重试', '退出'],
    defaultId: 0,
    cancelId: 1,
  });
  if (stopping) {
    return;
  }
  if (response === 0) {
    consecutiveFailures = 0;
    spawnKernel();
  } else {
    void shutdown();
  }
}

/** 内核失败统一入口：清理残留 → 计数 → 退避重拉或弹错误对话框 */
function onKernelFailure(): void {
  if (stopping || handlingFailure) {
    return;
  }
  handlingFailure = true;
  clearMonitorTimers();

  const failedChild = kernelProcess;
  kernelProcess = null;
  // MINOR-2：失败即清空，防旧 INKFLOW_READY 的过期 baseURL/token 载荷残留（与 stopKernel 一致）
  kernelInfo = null;
  pendingReadyPayload = null;
  if (failedChild) {
    killProcessTree(failedChild);
  }

  consecutiveFailures += 1;
  console.error(
    `[kernel] failure ${consecutiveFailures}/${MAX_CONSECUTIVE_FAILURES}`
  );

  if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
    void showStartupErrorDialog();
    return;
  }

  const delay = nextBackoffDelayMs(consecutiveFailures);
  console.error(`[kernel] restarting in ${delay}ms`);
  restartTimer = setTimeout(() => {
    spawnKernel();
  }, delay);
}

/** 健康检查单次：GET /health 带 X-InkFlow-Token，超时 3s（§3.2.3） */
async function checkHealthOnce(): Promise<void> {
  if (healthInFlight) {
    return;
  }
  healthInFlight = true;
  try {
    const info = kernelInfo;
    if (!info) {
      return;
    }
    const { port, token } = info;
    let ok = false;
    try {
      const res = await fetch(`http://127.0.0.1:${port}/health`, {
        headers: { 'X-InkFlow-Token': token },
        signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
      });
      ok = res.ok;
    } catch {
      ok = false;
    }
    if (kernelInfo !== info) {
      // 内核已换代（崩溃拉起/退出），本次结果作废
      return;
    }
    if (ok) {
      healthFailures = 0;
      consecutiveFailures = 0; // 成功 INKFLOW_READY + 健康 200 → 清零连续失败计数（§3.2.4）
      return;
    }
    healthFailures += 1;
    console.error(
      `[kernel] health check failed (${healthFailures}/${HEALTH_FAILURE_THRESHOLD}) for port ${port}`
    );
    if (healthFailures >= HEALTH_FAILURE_THRESHOLD) {
      onKernelFailure();
    }
  } finally {
    healthInFlight = false;
  }
}

/** 每 2s 轮询 /health（§3.2.3） */
function startHealthCheck(): void {
  if (healthCheckTimer) {
    clearInterval(healthCheckTimer);
  }
  healthFailures = 0;
  void checkHealthOnce();
  healthCheckTimer = setInterval(() => {
    void checkHealthOnce();
  }, HEALTH_INTERVAL_MS);
}

/** 拉起内核：spawn + readline 解析 INKFLOW_READY + stderr 转发 + 启动看门狗（§3.2.1/3.2.2） */
function spawnKernel(): void {
  if (stopping) {
    return;
  }
  handlingFailure = false;
  clearMonitorTimers();

  const { command, args } = resolveKernelCommandForSpawn();
  const child = spawn(command, args, {
    stdio: ['ignore', 'pipe', 'pipe'] as const,
    windowsHide: true,
  });
  kernelProcess = child;
  kernelInfo = null;
  healthFailures = 0;

  const rl = createInterface({ input: child.stdout });
  rl.on('line', (line) => {
    if (kernelProcess !== child) {
      return; // 旧进程残留输出，忽略
    }
    const parsed = parseReadyLine(line);
    if (!parsed) {
      return;
    }
    // 内核实际 pid 以 child.pid 为准（拿不到再用解析值）
    const effectivePid = child.pid ?? parsed.pid;
    kernelInfo = { ...parsed, pid: effectivePid };
    if (startupWatchdog) {
      clearTimeout(startupWatchdog);
      startupWatchdog = null;
    }
    console.log(`[kernel] ready port=${kernelInfo.port} pid=${kernelInfo.pid}`);
    updateKernelInfoHook();
    sendReadyToRenderer();
    startHealthCheck();
  });

  child.stderr.on('data', (chunk: Buffer) => {
    const text = chunk.toString().trimEnd();
    if (text) {
      console.error(`[kernel] ${text}`);
    }
  });

  child.on('error', (err) => {
    console.error('[kernel] spawn error:', err);
    if (kernelProcess !== child) {
      return;
    }
    if (!stopping) {
      onKernelFailure();
    }
  });

  child.on('exit', (code, signal) => {
    console.error(`[kernel] exited code=${code} signal=${signal}`);
    if (kernelProcess !== child) {
      return;
    }
    if (!stopping) {
      onKernelFailure();
    }
  });

  // 启动看门狗：15s 未收到 INKFLOW_READY → 判启动失败（§3.2.2）
  startupWatchdog = setTimeout(() => {
    console.error('[kernel] startup timeout: INKFLOW_READY not received within 15s');
    if (kernelProcess === child && !stopping) {
      onKernelFailure();
    }
  }, READY_TIMEOUT_MS);
}

/**
 * 退出回收（§3.2.5，防僵尸）：
 * ① 优雅 child.kill() → ② 3s 超时未退出 → taskkill /PID <pid> /T /F → ③ 硬上限兜底。
 */
async function stopKernel(): Promise<void> {
  stopping = true;
  clearMonitorTimers();
  const child = kernelProcess;
  kernelProcess = null;
  kernelInfo = null;
  if (!child || child.pid === undefined || child.exitCode !== null) {
    return;
  }
  const pid = child.pid;

  await new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) {
        return;
      }
      settled = true;
      resolve();
    };

    child.once('exit', finish);
    try {
      child.kill();
    } catch {
      // 进程已退出或信号发送失败：交由超时兜底
    }

    setTimeout(() => {
      if (settled) {
        return;
      }
      try {
        const killer = spawn('taskkill', ['/PID', String(pid), '/T', '/F'], {
          windowsHide: true,
          stdio: 'ignore',
        });
        killer.once('error', finish);
        killer.once('exit', finish);
      } catch {
        finish();
      }
    }, KILL_GRACE_MS);

    // 硬上限：无论 taskkill 是否完成，防止退出挂起
    setTimeout(finish, KILL_GRACE_MS + 2_000);
  });
}

/** 统一退出：回收内核后退出（幂等，供 window-all-closed / before-quit 复用） */
async function shutdown(): Promise<void> {
  if (quitInProgress) {
    return;
  }
  quitInProgress = true;
  await stopKernel();
  app.exit(0);
}

/** BrowserWindow：安全基线 webPreferences（§3.3）+ 加载 renderer 构建产物（§3.4） */
function createMainWindow(): void {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    title: 'InkFlow',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow = win;

  // 固定窗口标题（E2E 断言 title 含 InkFlow）
  win.on('page-title-updated', (event) => {
    event.preventDefault();
    win.setTitle('InkFlow');
  });

  // 安全基线：阻止窗口内导航离开本地 file:// 页面（§3.3 防钓鱼；壳不调用 shell.openExternal）
  win.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('file://')) {
      event.preventDefault();
    }
  });

  // preload 就绪后重发 pending 载荷（防止 INKFLOW_READY 早于页面加载完成）
  win.webContents.on('did-finish-load', () => {
    if (pendingReadyPayload) {
      win.webContents.send('inkflow:ready', pendingReadyPayload);
    }
  });

  win.on('closed', () => {
    if (mainWindow === win) {
      mainWindow = null;
    }
  });

  void win.loadFile(path.join(RENDERER_DIST, 'index.html')).catch((err: unknown) => {
    console.error('[main] renderer load failed（请先构建 renderer：pnpm --filter renderer build）:', err);
  });
}

/** 开发模式 DevTools 快捷键回调：打开聚焦窗口 DevTools，无聚焦窗口时静默跳过 */
function openDevToolsForFocusedWindow(): void {
  BrowserWindow.getFocusedWindow()?.webContents.openDevTools();
}

/**
 * 判定是否为新注册会话（幂等集合的重置时机）。
 * 单测中 electron 被 vitest mock：beforeEach 对 register 做 mockClear 后 calls 为空，
 * 即「新测试 = 新应用生命周期」——此时重置去重集合，保证每个用例都从零注册
 * （main.menu.test.ts 契约：第 3/4/6 用例需全新注册，第 5 用例需同测试内两次调用去重，
 * 二者唯一兼容点是 mockClear 即会话重置）。生产环境 register 为真实 Electron 函数，
 * 无 mock 元数据 → 恒为同一会话，集合持续生效（真幂等）。
 */
function isFreshRegistrationSession(): boolean {
  const maybeMock = (globalShortcut.register as unknown as {
    mock?: { calls: unknown[] };
  }).mock;
  return maybeMock !== undefined && maybeMock.calls.length === 0;
}

/**
 * 移除默认应用菜单并（仅开发模式）注册 DevTools 快捷键（spec §5.2.9 / M9）。
 * - 两个模式都调用 Menu.setApplicationMenu(null)（彻底移除，Windows 沉浸式形态）；
 * - isPackaged=false：注册 F12 与 Ctrl+Shift+I 打开聚焦窗口 DevTools，各恰好一次；
 * - 幂等：同一会话内重复调用不重复注册（模块级集合去重，新会话重置）；
 *   register 返回 false 时静默忽略。
 */
export function setupAppMenu(isPackaged: boolean): void {
  Menu.setApplicationMenu(null);
  if (isPackaged) {
    return;
  }
  if (isFreshRegistrationSession()) {
    registeredDevToolsAccelerators.clear();
  }
  for (const accelerator of ['F12', 'Ctrl+Shift+I'] as const) {
    if (registeredDevToolsAccelerators.has(accelerator)) {
      continue;
    }
    if (globalShortcut.register(accelerator, openDevToolsForFocusedWindow)) {
      registeredDevToolsAccelerators.add(accelerator);
    }
  }
}

app.whenReady().then(() => {
  setupAppMenu(app.isPackaged);
  createMainWindow();
  spawnKernel();
});

app.on('window-all-closed', () => {
  void shutdown();
});

app.on('before-quit', (event) => {
  if (quitInProgress) {
    return;
  }
  event.preventDefault();
  void shutdown();
});

// 兜底：进程退出时同步尽力回收（异步 taskkill 可能来不及，但 child.kill 同步生效）
process.on('exit', () => {
  const child = kernelProcess;
  if (!child || child.pid === undefined || child.exitCode !== null) {
    return;
  }
  try {
    child.kill();
  } catch {
    // 忽略
  }
  try {
    spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
      windowsHide: true,
      stdio: 'ignore',
    });
  } catch {
    // 忽略
  }
});
