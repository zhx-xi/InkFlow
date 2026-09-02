/**
 * F5 打包冻结黑盒 E2E 契约（S3f-T2，contract-s3f-t2 §1 R2）：真实冻结产物黑盒。
 * launch win-unpacked/InkFlow.exe（或 NSIS 安装目录，INKFLOW_PACKAGED_DIR 注入）；打包版
 * __kernelInfo/__trayInfo 钩子被 isPackaged 门控（非 debug 不暴露）→ kernel.json = 唯一契约
 * 通道（spec f31 §5.4 双向闭环：GUI 拉起内核后原子写 %APPDATA%/InkFlow/kernel.json）。
 * 用例 2 负向断言在 dev 模式恒不成立（钩子暴露）——双守卫 skip 天然保证只跑打包 exe：
 * INKFLOW_PACKAGED_DIR 未设或无 InkFlow.exe → 各 test 首行执行期干净 skip（--list 仍收集
 * 4 tests，CI 不失败）。运行：INKFLOW_PACKAGED_DIR=<win-unpacked> && cd frontend/packages/
 * electron && playwright test e2e-packaged.spec.ts。用例 4 另需调用方复制 win-unpacked 到
 * 含中文/空格目录并设 INKFLOW_PACKAGED_CJK=1（spec 不复制目录，env 注入即参数化）。
 */
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { test, expect, _electron as electron, type ElectronApplication, type Page } from '@playwright/test';

const PACKAGED_DIR = process.env.INKFLOW_PACKAGED_DIR;
const PACKAGED_EXE = PACKAGED_DIR ? path.join(PACKAGED_DIR, 'InkFlow.exe') : '';
const HAS_PACKAGED = !!PACKAGED_DIR && fs.existsSync(PACKAGED_EXE);

/** kernel.json 五字段（spec f31 §2.1：port/token/pid/version/started_at） */
interface KernelState {
  port: number;
  token: string;
  pid: number;
  version: string;
  started_at: string;
}

/** 各 test 首行调用：无打包产物 → 执行期 skip（收集期不受影响） */
function skipUnlessPackaged(): void {
  test.skip(!HAS_PACKAGED, '需本地/CI 打包产物：INKFLOW_PACKAGED_DIR 指向含 InkFlow.exe 的 win-unpacked/安装目录');
}

/** mkdtemp 隔离根（APPDATA + 内核数据目录双隔离 → 每次 launch 独立内核实例） */
function makeIsolation(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'inkflow-e2e-packaged-'));
}

/** 解析 kernel.json 五字段（类型校验缺/错即抛——镜像 kernel.state.test.ts 判定） */
function parseKernelState(raw: string): KernelState {
  const d = JSON.parse(raw) as Record<string, unknown>;
  const ok =
    typeof d.port === 'number' &&
    typeof d.token === 'string' &&
    d.token !== '' &&
    typeof d.pid === 'number' &&
    d.pid > 0 &&
    typeof d.version === 'string' &&
    d.version !== '' &&
    typeof d.started_at === 'string' &&
    !Number.isNaN(Date.parse(d.started_at));
  if (!ok) throw new Error(`kernel.json 五字段非法: ${raw}`);
  return d as unknown as KernelState;
}

/**
 * 打包版 kernel.json 真实落点（S3f-T2 黑盒实证修正，release-verification「APPDATA 双轨」契约）：
 * Electron app.getPath('appData') 走 Windows Known Folder API，**不随 APPDATA env 注入漂移**；
 * 故 spec 必须读 Playwright runner 进程的真实 %APPDATA%\InkFlow\kernel.json（launch 前删残留
 * 保证读到的是本次 launch 新写）。内核 DB/日志仍经 INKFLOW_DATA_DIR env 隔离（pydantic env 最高）。
 */
const KERNEL_STATE_FILE = path.join(process.env.APPDATA ?? '', 'InkFlow', 'kernel.json');

/** 轮询真实 %APPDATA%/InkFlow/kernel.json（打包冷启动 chromadb 可 >60s，90s 上限） */
async function waitForKernelFile(timeoutMs = 90_000): Promise<KernelState> {
  const file = KERNEL_STATE_FILE;
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown;
  while (Date.now() < deadline) {
    if (fs.existsSync(file)) {
      try {
        return parseKernelState(fs.readFileSync(file, 'utf8'));
      } catch (err) {
        lastError = err; // 半写/畸形：继续轮询等原子 rename 完成
      }
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  const why = lastError ? `（最后解析错误: ${String(lastError)}）` : '';
  throw new Error(`kernel.json 未在 ${timeoutMs}ms 内就绪（${file}）${why}`);
}

/** 打包 launch：APPDATA/INKFLOW_DATA_DIR 双隔离（frozen data_dir + GUI kernel.json 落点） */
async function launchPackaged(appDataDir: string, extraEnv: Record<string, string> = {}): Promise<ElectronApplication> {
  // 剥 debug 判定干扰键（INKFLOW_DEBUG/TOKEN 由用例注入；与 e2e-debug-triad baseEnv 同规）
  // 陈旧 kernel.json 先删：waitForKernelFile 读到必是本次 launch 新写（原子 rename 契约）
  try { fs.rmSync(KERNEL_STATE_FILE, { force: true }); } catch { /* 不存在=常态 */ }
  const env = Object.fromEntries(
    Object.entries(process.env).filter(([k, v]) => v !== undefined && k !== 'INKFLOW_DEBUG' && k !== 'INKFLOW_DEBUG_TOKEN')
  ) as Record<string, string>;
  return electron.launch({
    executablePath: PACKAGED_EXE,
    env: { ...env, APPDATA: appDataDir, INKFLOW_DATA_DIR: path.join(appDataDir, 'data'), ...extraEnv },
  });
}

/** pid 存活探活（tasklist/wmic 过重不用；信号 0 = 存在性检查；EPERM = 存在但无权限） */
function isPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return (err as NodeJS.ErrnoException).code === 'EPERM';
  }
}

/** GET /health（带 token 200 = READY 契约） */
async function healthStatus(port: number, token: string): Promise<number> {
  return (await fetch(`http://127.0.0.1:${port}/health`, { headers: { 'X-InkFlow-Token': token } })).status;
}

/** GET /docs（G1 docs 门控：debug 放行 200 / 非 debug 404） */
async function docsStatus(port: number): Promise<number> {
  return (await fetch(`http://127.0.0.1:${port}/docs`)).status;
}

/** 读主进程 __kernelInfo 钩子（打包 + debug 门控放行才暴露） */
async function readKernelInfoHook(app: ElectronApplication): Promise<KernelState | undefined> {
  return app.evaluate(() => (globalThis as { __kernelInfo?: KernelState }).__kernelInfo);
}

/** 主窗口 DevTools 是否打开（无窗口视为 false） */
async function isDevToolsOpened(app: ElectronApplication): Promise<boolean> {
  return app.evaluate(({ BrowserWindow }) => {
    const win = BrowserWindow.getAllWindows()[0];
    return win ? win.webContents.isDevToolsOpened() : false;
  });
}

// 真实 exe 启动 + 内核冷启动慢（每用例独立 launch + 独立数据目录），放宽整文件超时
test.describe.configure({ timeout: 240_000 });

let currentApp: ElectronApplication | undefined;
let currentIsolation: string | undefined;

test.afterEach(async () => {
  if (currentApp) {
    try { await currentApp.close(); } catch { /* close 幂等兜底（进程已自行退出） */ }
    currentApp = undefined;
  }
  try { fs.rmSync(KERNEL_STATE_FILE, { force: true }); } catch { /* 清理瞬态文件 */ }
  if (currentIsolation) {
    try { fs.rmSync(currentIsolation, { recursive: true, force: true }); } catch { /* 句柄占用：清理失败不阻塞结论 */ }
    currentIsolation = undefined;
  }
});

test('打包启动闭环：title /InkFlow/ + app-nav 渲染 + kernel.json 五字段 + /health 200 + 内核进程存活（M2 核心）', async () => {
  skipUnlessPackaged();
  const iso = makeIsolation();
  currentIsolation = iso;
  const app = await launchPackaged(iso);
  currentApp = app;
  const window: Page = await app.firstWindow();
  await expect.poll(() => window.title(), { timeout: 30_000 }).toMatch(/InkFlow/);
  await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });
  const state = await waitForKernelFile();
  // 五字段合法由 parseKernelState 保证（version 非空）；pid 探活实证 resources/kernel 拉起
  expect(await healthStatus(state.port, state.token)).toBe(200);
  expect(isPidAlive(state.pid)).toBe(true);
});

test('DevTools/钩子负向门控（打包非 debug）：__kernelInfo/__trayInfo 不暴露 + DevTools 不开（R-语义：dev 模式此面恒假，打包黑盒独有）', async () => {
  skipUnlessPackaged();
  const iso = makeIsolation();
  currentIsolation = iso;
  const app = await launchPackaged(iso);
  currentApp = app;
  const window: Page = await app.firstWindow();
  await waitForKernelFile(); // 内核就绪 = 钩子更新时机已过，负向断言有效
  await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });
  expect(await readKernelInfoHook(app)).toBeUndefined();
  expect(await app.evaluate(() => (globalThis as { __trayInfo?: unknown }).__trayInfo)).toBeUndefined();
  expect(await isDevToolsOpened(app)).toBe(false);
});

test('打包 + INKFLOW_DEBUG=1 三层联动：__kernelInfo 暴露 + debug token + /docs 200 + /health 200（T1 e2e-debug-triad 打包面对偶）', async () => {
  skipUnlessPackaged();
  const iso = makeIsolation();
  currentIsolation = iso;
  const app = await launchPackaged(iso, { INKFLOW_DEBUG: '1' });
  currentApp = app;
  await app.firstWindow();
  const state = await waitForKernelFile();
  // 打包 + debug 门控放行 → __kernelInfo 暴露（G2 env 回写联动）
  const deadline = Date.now() + 30_000;
  let hook: KernelState | undefined;
  while (Date.now() < deadline && !hook) {
    hook = await readKernelInfoHook(app);
    if (!hook) await new Promise((r) => setTimeout(r, 500));
  }
  expect(hook?.token).toBe('inkflow-debug-token');
  expect(state.token).toBe('inkflow-debug-token'); // kernel.json 同值（双向闭环）
  expect(await docsStatus(state.port)).toBe(200); // G1 docs 门控 debug 放行
  expect(await healthStatus(state.port, state.token)).toBe(200);
});

test('中文/空格安装目录变体（INKFLOW_PACKAGED_CJK=1 条件用例：调用方复制 win-unpacked 后复用本 spec，用例 1 简化版）', async () => {
  skipUnlessPackaged();
  test.skip(process.env.INKFLOW_PACKAGED_CJK !== '1', '调用方编排脚本负责复制到含中文/空格目录并设 INKFLOW_PACKAGED_CJK=1');
  // 前置断言：PACKAGED_DIR 确含非 ASCII 或空格（复制是调用方职责）
  expect(PACKAGED_DIR!.includes(' ') || /[^\x00-\x7F]/.test(PACKAGED_DIR!), `PACKAGED_DIR 应含非 ASCII/空格: ${PACKAGED_DIR}`).toBe(true);
  const iso = makeIsolation();
  currentIsolation = iso;
  const app = await launchPackaged(iso);
  currentApp = app;
  const window: Page = await app.firstWindow();
  await expect.poll(() => window.title(), { timeout: 30_000 }).toMatch(/InkFlow/);
  const state = await waitForKernelFile();
  expect(await healthStatus(state.port, state.token)).toBe(200);
});
