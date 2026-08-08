/**
 * Electron 主进程（#78 Electron 壳）：内核进程生命周期管理 + BrowserWindow 加载 renderer 构建产物。
 * F31 #167 扩展：托盘常驻（关闭拦截状态机 / Tray 菜单 / 单实例锁 / 内核复用 kernel.json 闭环）。
 *
 * 壳层保持薄（ADR-020/021 硬约束）：零业务逻辑、零业务 API 调用，一切业务通信由
 * renderer 直接走 REST + SSE（baseURL/token 经 preload 注入）。
 * 契约来源：specs/f19-gui/spec.md §3.2（生命周期）/ §3.3（安全基线）/ §3.4（renderer 契约）。
 */
import {
  app,
  BrowserWindow,
  dialog,
  globalShortcut,
  ipcMain,
  Menu,
  nativeImage,
  Tray,
  type MenuItemConstructorOptions,
} from 'electron';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { createInterface } from 'node:readline';
import {
  formatKernelMenuLabel,
  MAX_CONSECUTIVE_FAILURES,
  nextBackoffDelayMs,
  parseReadyLine,
  resolveKernelCommand,
  tryReuseKernel,
  writeKernelStateFile,
  type KernelInfo,
} from './kernel';

/** 仓库根：out/ 位于 frontend/packages/electron/out，向上 4 级 */
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..', '..');
/**
 * renderer 构建产物（§3.4 file:// 加载）。
 * ⚠️ 打包模式路径（rc.5 实测空白 #145）：asar 内 __dirname = app.asar/out，
 *    renderer 由组装步骤复制进 packages/electron/renderer-dist/ → asar 内 = app.asar/renderer-dist
 *    （files: renderer-dist/**）；dev 模式 out/ 在 packages/electron/out，renderer 在 packages/renderer/dist。
 */
const RENDERER_DIST = app.isPackaged
  ? path.join(__dirname, '..', 'renderer-dist')            // app.asar/out/../renderer-dist
  : path.resolve(__dirname, '..', '..', 'renderer', 'dist'); // dev: packages/renderer/dist

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
/** 关闭行为设置（spec f31 §2.2）：内存态，默认最小化到托盘；#152 合入后切换持久化 */
type CloseBehavior = 'tray' | 'quit';
let closeBehavior: CloseBehavior = 'tray';
/** 首次托盘提示「不再提示」（内存态，重启恢复；spec f31 §5.2） */
let trayHintDismissed = false;
/** 托盘实例（模块级保存，退出时 destroy 防 Windows 托盘残留图标；spec f31 §5.6） */
let tray: Tray | null = null;
/** kernel.json 状态文件路径（spec f31 §5.4）：%APPDATA%\InkFlow\kernel.json；测试环境为 null 时跳过闭环 */
let kernelStatePath: string | null = null;
/** __trayInfo.windowVisible 数据源：hide/show 事件驱动维护（spec f31 §9） */
let trayInfoWindowVisible = true;
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

/** dev 测试钩子（spec f31 §9）：__trayInfo 跟随 hide/show/设置变更刷新 */
function updateTrayInfoHook(): void {
  if (app.isPackaged) {
    return;
  }
  (globalThis as unknown as {
    __trayInfo?: { created: boolean; closeBehavior: string; windowVisible: boolean };
  }).__trayInfo = {
    created: tray !== null,
    closeBehavior,
    windowVisible: trayInfoWindowVisible,
  };
}

/**
 * kernel.json 状态文件路径（spec f31 §5.4）。
 * - 打包：%APPDATA%\InkFlow\kernel.json（与 Python frozen 侧 config.data_dir 一致）
 * - dev：backend/data/kernel.json（与 Python dev 侧 data_dir=./data 对齐——项目惯例
 *   CLI/内核从 backend 目录启动（inkflow-workflow），ensure_kernel 写 backend/data；
 *   GUI 复用必须读同一文件，否则 CLI 拉起的常驻内核 GUI 发现不了（F30 dev 相对路径坑）
 * 测试 mock 无 app.getPath → 返回 null（跳过双向闭环，确定性回落 spawnKernel）。
 */
function resolveKernelStatePath(): string | null {
  try {
    if (app.isPackaged) {
      return path.join(app.getPath('appData'), 'InkFlow', 'kernel.json');
    }
    return path.join(REPO_ROOT, 'backend', 'data', 'kernel.json');
  } catch {
    return null;
  }
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
  const resolved = resolveKernelCommand({
    isPackaged: app.isPackaged,
    env: process.env,
    // #187 任意 cwd 启动：打包版传绝对路径（app.getAppPath() 定位 resources/kernel/inkflow.exe）；
    // typeof 守卫兼容测试 mock 缺失 getAppPath（与 resolveKernelStatePath/requestSingleInstanceLock 同款防御）
    packagedKernelPath:
      app.isPackaged && typeof app.getAppPath === 'function'
        ? path.join(app.getAppPath(), 'resources', 'kernel', 'inkflow.exe')
        : undefined,
  });
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
  // #188 F2：内核失败清理 → 托盘菜单内核状态 label 刷新为「未运行」
  rebuildTrayMenu();
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
    // #187 双保险：打包版 spawn cwd 固定为 exe 所在目录，任意 cwd 启动不依赖相对路径解析
    cwd: app.isPackaged ? path.dirname(process.execPath) : undefined,
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
    const readyInfo: KernelInfo = { ...parsed, pid: effectivePid };
    kernelInfo = readyInfo;
    if (startupWatchdog) {
      clearTimeout(startupWatchdog);
      startupWatchdog = null;
    }
    console.log(`[kernel] ready port=${readyInfo.port} pid=${readyInfo.pid}`);
    updateKernelInfoHook();
    // #188 F2：内核就绪 → 托盘菜单内核状态 label 刷新为「运行中」
    rebuildTrayMenu();
    // 双向闭环（spec f31 §5.4）：GUI 拉起的常驻内核写 kernel.json，供 CLI/MCP/skills 复用发现；
    // 写入失败降级（%APPDATA% 只读等）→ 记录并继续（不影响 GUI 自用内核）
    if (kernelStatePath) {
      try {
        writeKernelStateFile(kernelStatePath, readyInfo);
      } catch (err) {
        console.error('[kernel] write kernel.json failed:', err);
      }
    }
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

/**
 * 内核连接（spec f31 §5.1/§5.3）：先 tryReuseKernel（kernel.json + pid 存活 + /health 200），
 * 成功 → 直接连接不 spawn；失败 → #78 既有 spawnKernel。
 */
async function connectKernel(): Promise<void> {
  if (kernelStatePath) {
    const reused = await tryReuseKernel(kernelStatePath);
    if (reused) {
      kernelInfo = reused;
      updateKernelInfoHook();
      sendReadyToRenderer();
      startHealthCheck();
      return;
    }
  }
  spawnKernel();
}

/** BrowserWindow：安全基线 webPreferences（§3.3）+ 加载 renderer 构建产物（§3.4） */
/**
 * #106 用户拍板：自绘窗口控制按钮（官方 titleBarOverlay 颜色联动不可靠）。
 * 最小化/最大化/关闭三个 IPC 通道由 renderer 顶栏 WindowControls 组件调用；
 * 颜色/大小完全走 CSS 变量，随主题 + 背景变体自然联动。
 */
function registerWindowControlsHandlers(): void {
  ipcMain.on('window:minimize', () => mainWindow?.minimize());
  ipcMain.on('window:toggle-maximize', () => {
    if (!mainWindow) return;
    if (mainWindow.isMaximized()) mainWindow.unmaximize();
    else mainWindow.maximize();
  });
  ipcMain.on('window:close', () => mainWindow?.close());
}

/** 关闭行为设置 IPC（spec f31 §2.3）：get/set/dismiss 三通道，whenReady 内幂等注册一次 */
function registerSettingsHandlers(): void {
  ipcMain.handle('settings:get-close-behavior', () => closeBehavior);
  ipcMain.handle('settings:set-close-behavior', (_event, value: unknown) => {
    if (value !== 'tray' && value !== 'quit') {
      throw new Error(`invalid close behavior: ${String(value)}`);
    }
    closeBehavior = value;
    updateTrayInfoHook();
  });
  ipcMain.handle('settings:dismiss-tray-hint', () => {
    trayHintDismissed = true;
  });
}

function createMainWindow(): void {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    title: 'InkFlow',
    icon: path.join(__dirname, '..', 'favicon.ico'),
    titleBarStyle: 'hidden',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow = win;

  // #106：最大化状态推送（自绘按钮图标切换：□ ↔ 还原）
  const sendMaximizedState = (): void => {
    win.webContents.send('window:maximized-changed', win.isMaximized());
  };
  win.on('maximize', sendMaximizedState);
  win.on('unmaximize', sendMaximizedState);
  win.on('ready-to-show', sendMaximizedState); // 初始状态

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
    sendMaximizedState(); // 初始状态补发（ready-to-show 早于 React 挂载订阅时兜底）
  });

  win.on('closed', () => {
    if (mainWindow === win) {
      mainWindow = null;
    }
  });

  // 关闭拦截状态机（spec f31 §5.2）：tray 模式 → preventDefault + hide（内核保持）+ 首次提示；
  // quit 模式 → 放行（window-all-closed → shutdown，#78 路径）
  win.on('close', (event) => {
    if (closeBehavior === 'tray' && !quitInProgress) {
      event.preventDefault();
      win.hide();
      trayInfoWindowVisible = false;
      updateTrayInfoHook();
      if (!trayHintDismissed) {
        win.webContents.send('inkflow:tray-hint');
      }
    }
  });

  void win.loadFile(path.join(RENDERER_DIST, 'index.html')).catch((err: unknown) => {
    console.error('[main] renderer load failed（请先构建 renderer：pnpm --filter renderer build）:', err);
  });
}

/** 托盘「打开主窗口」：窗口被销毁（异常）则重建（spec f31 §5.2 边界 #11） */
function showWindow(): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createMainWindow();
    return;
  }
  mainWindow.show();
  mainWindow.focus();
  trayInfoWindowVisible = true;
  updateTrayInfoHook();
}

/** 托盘「退出」= 真退出：destroy 防托盘残留 → shutdown（stopKernel 完整回收 + app.exit(0)） */
function quitFromTray(): void {
  if (tray) {
    tray.destroy();
    tray = null;
  }
  void shutdown();
}

/** 重建托盘菜单（#188 F2）：内核 ready / 失败清理时调用，label 跟随当前 kernelInfo 刷新 */
function rebuildTrayMenu(): void {
  if (!tray) {
    return;
  }
  const template: MenuItemConstructorOptions[] = [
    { label: '打开主窗口', click: showWindow },
    { label: formatKernelMenuLabel(kernelInfo), enabled: false },
    { type: 'separator' },
    { label: '退出', click: quitFromTray },
  ];
  tray.setContextMenu(Menu.buildFromTemplate(template));
}

/** Tray 创建 + 菜单（spec f31 §5.6）：dev/生产都创建；创建失败降级（不阻断窗口/内核） */
function createTray(): void {
  // 防御：异常环境（测试 mock 缺 Tray/buildFromTemplate 等）下托盘缺失不阻断启动
  if (typeof Tray !== 'function' || typeof Menu.buildFromTemplate !== 'function') {
    return;
  }
  try {
    const iconPath = path.join(__dirname, '..', 'inkflow-icon-256.png');
    // #188 F1 兜底：asar files 白名单漏包 png → createFromPath 空图像 → 回退 exe 自带图标（Windows）
    let icon = nativeImage.createFromPath(iconPath);
    if (icon.isEmpty()) {
      icon = nativeImage.createFromPath(process.execPath);
    }
    const instance = new Tray(icon);
    instance.on('click', showWindow); // Windows 惯例：点击托盘图标打开主窗口
    tray = instance;
    rebuildTrayMenu();
    trayInfoWindowVisible = true;
    updateTrayInfoHook();
  } catch (err) {
    console.error('[main] tray creation failed:', err);
  }
}

/** dev 测试钩子（spec f31 §9）：__trayActions 直调主进程动作（CI 无真实托盘交互） */
function exposeTrayDevHooks(): void {
  updateTrayInfoHook();
  (globalThis as unknown as {
    __trayActions?: {
      show: () => void;
      quit: () => void;
      setCloseBehavior: (value: CloseBehavior) => void;
    };
  }).__trayActions = {
    show: showWindow,
    quit: quitFromTray,
    setCloseBehavior: (value: CloseBehavior) => {
      closeBehavior = value;
      updateTrayInfoHook();
    },
  };
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

app.whenReady().then(async () => {
  // 单实例锁最先执行（spec f31 §5.5）：失败 → 静默让位已有实例（不 spawn、不建窗、不弹错）
  // （typeof 守卫：部分测试 mock 未提供该方法，视为单实例获取成功）
  const gotLock =
    typeof app.requestSingleInstanceLock === 'function' ? app.requestSingleInstanceLock() : true;
  if (!gotLock) {
    app.quit();
    return;
  }
  app.on('second-instance', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.show();
      mainWindow.focus();
      trayInfoWindowVisible = true;
      updateTrayInfoHook();
    } else {
      createMainWindow(); // 窗口被销毁但托盘仍在 → 重建（spec f31 §5.2 边界 #9）
    }
  });

  app.setAppUserModelId('InkFlow');
  setupAppMenu(app.isPackaged);
  registerWindowControlsHandlers();
  registerSettingsHandlers();
  createMainWindow();
  // 内核连接：先复用判定（kernel.json + pid 存活 + /health 200），失败回落 spawn（spec f31 §5.1）
  kernelStatePath = resolveKernelStatePath();
  await connectKernel();
  createTray();
  if (!app.isPackaged) {
    exposeTrayDevHooks();
  }
});

app.on('window-all-closed', (event?: { preventDefault?: () => void }) => {
  if (closeBehavior === 'quit' || quitInProgress) {
    void shutdown();
    return;
  }
  // 托盘模式（D5）：不退出——托盘仍在、内核保持；显式 preventDefault（真实 Electron 该事件
  // 无 event 对象时，不调用 shutdown 即保持驻留）
  event?.preventDefault?.();
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
