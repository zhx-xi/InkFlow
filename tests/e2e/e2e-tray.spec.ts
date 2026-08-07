/**
 * 托盘常驻 E2E 契约（F31 #167：GUI 托盘常驻 + 关闭行为设置）。
 * 契约来源：specs/f31-gui-tray/spec.md §9 测试策略（__trayInfo/__trayActions dev 钩子约定）、
 *           §13 验收标准 M1-M5：
 *           M1 关闭→窗口隐藏+内核存活+托盘已创建 / M2 托盘「打开」→恢复 +「退出」→内核回收+应用退出 /
 *           M3 设置「直接退出」→关闭=完整退出 / M4 单实例聚焦（无第二窗口/内核）/ M5 复用 CLI 预拉起内核。
 * 钩子契约（spec §9，dev 模式 app.isPackaged===false 时主进程 globalThis 暴露）：
 *   __trayInfo    = { created: boolean, closeBehavior: 'tray'|'quit', windowVisible: boolean }
 *   __trayActions = { show(): void, quit(): void, setCloseBehavior(v): void }
 * CI 无系统托盘交互能力 → 托盘菜单动作经 app.evaluate 直调主进程钩子（spec §12 D6）。
 * helper 复制自 e2e-shell.spec.ts（#78 同款 launch/waitKernelInfo/healthCheck/isAlive；Playwright
 * 单文件限制，不跨文件 import）。本文件只读，不修改 e2e-shell.spec.ts。
 *
 * F32 E2E 契约（#152，spec §9.1/§9.4）：关闭行为持久化重启保留（M6）——设置页 Select 切「直接退出」
 * → 重启 → 关闭窗口仍完整退出。重启用例独立 userData 临时目录（spec §9.1 隔离策略）。
 */
import path from 'node:path';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';

// 本文件位于 <repoRoot>/tests/e2e/ → 仓库根 → frontend 目录
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');
const MAIN_JS = 'packages/electron/out/main.js';

interface KernelInfo {
  pid: number;
  port: number;
  token: string;
}

/** 托盘测试钩子（spec §9）：主进程 dev 模式暴露，hide/show/setCloseBehavior 时刷新 */
interface TrayInfo {
  created: boolean;
  closeBehavior: 'tray' | 'quit';
  windowVisible: boolean;
}

/** 托盘动作钩子（spec §9）：CI 无真实托盘，Playwright 经 app.evaluate 直调 */
interface TrayActions {
  show(): void;
  quit(): void;
  setCloseBehavior(value: 'tray' | 'quit'): void;
}

/** 读主进程测试钩子（dev 模式暴露 globalThis.__kernelInfo = {pid, port, token}，spec §3.6） */
async function readKernelInfo(
  app: ElectronApplication
): Promise<KernelInfo | undefined> {
  return app.evaluate(() => (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo);
}

/**
 * 等待内核就绪（spec §3.2.1/3.2.3）：内核拉起需 python + uvicorn 启动时间，
 * INKFLOW_READY 到达前 __kernelInfo 尚未注入。轮询至多 60s（CI 冷启动窗口，inkflow-e2e-testing）。
 */
async function waitKernelInfo(app: ElectronApplication, timeoutMs = 60_000): Promise<KernelInfo> {
  const deadline = Date.now() + timeoutMs;
  let info: KernelInfo | undefined;
  while (Date.now() < deadline) {
    info = await readKernelInfo(app);
    if (info) {
      return info;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`__kernelInfo 未在 ${timeoutMs}ms 内注入（内核未就绪）`);
}

/** GET /health 带 token（spec §3.7 M2：200 = 内核健康） */
async function healthCheck(info: KernelInfo): Promise<number> {
  const res = await fetch(`http://127.0.0.1:${info.port}/health`, {
    headers: { 'X-InkFlow-Token': info.token },
  });
  return res.status;
}

/** 进程存活探测（Windows：kill(pid, 0) 对不存在的进程抛 ESRCH） */
function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/** 读托盘钩子（spec §9）。实现未就绪（RED）或应用已退出时返回 undefined → 轮询超时给出失败信息 */
async function readTrayInfo(app: ElectronApplication): Promise<TrayInfo | undefined> {
  try {
    return await app.evaluate(() => (globalThis as { __trayInfo?: TrayInfo }).__trayInfo);
  } catch {
    return undefined;
  }
}

/** 等待托盘创建（spec §5.6：whenReady 内创建，dev 也创建） */
async function waitForTrayCreated(app: ElectronApplication, timeoutMs = 15_000): Promise<TrayInfo> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const info = await readTrayInfo(app);
    if (info && info.created) {
      return info;
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`__trayInfo.created 未在 ${timeoutMs}ms 内变为 true（托盘未创建）`);
}

/** 轮询 __trayInfo.windowVisible 直到等于期望值（hide/show 事件驱动刷新，spec §5.2） */
async function waitForWindowVisible(
  app: ElectronApplication,
  visible: boolean,
  timeoutMs = 15_000
): Promise<TrayInfo> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const info = await readTrayInfo(app);
    if (info && info.windowVisible === visible) {
      return info;
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`__trayInfo.windowVisible 未在 ${timeoutMs}ms 内变为 ${visible}`);
}

/** 轮询应用进程退出（app.evaluate 连接断开 = 主进程已退出；规避 close 事件竞态） */
async function waitForAppExit(app: ElectronApplication, timeoutMs = 20_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await app.evaluate(() => 1);
    } catch {
      return;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`应用进程未在 ${timeoutMs}ms 内退出`);
}

/** 主进程直调 __trayActions.show()（spec §9：托盘「打开主窗口」） */
async function trayShow(app: ElectronApplication): Promise<void> {
  await app.evaluate(() => {
    (globalThis as unknown as { __trayActions?: TrayActions }).__trayActions?.show();
  });
}

/** 主进程直调 __trayActions.quit()（spec §9：托盘「退出」→ shutdown） */
async function trayQuit(app: ElectronApplication): Promise<void> {
  await app.evaluate(() => {
    (globalThis as unknown as { __trayActions?: TrayActions }).__trayActions?.quit();
  });
}

/** 主进程直调 __trayActions.setCloseBehavior(v)（spec §9：设置页「关闭窗口时」IPC 的落点） */
async function traySetCloseBehavior(app: ElectronApplication, value: 'tray' | 'quit'): Promise<void> {
  await app.evaluate(
    (_electronModule: unknown, v: 'tray' | 'quit') => {
      (globalThis as unknown as { __trayActions?: TrayActions }).__trayActions?.setCloseBehavior(v);
    },
    value
  );
}

/** 启动应用（独立 userData 临时目录——F32 重启用例隔离策略，spec §9.1：launch 传 --user-data-dir） */
async function launchAppWithUserData(userDataDir: string): Promise<ElectronApplication> {
  return electron.launch({
    args: [MAIN_JS, `--user-data-dir=${userDataDir}`],
    cwd: FRONTEND_DIR,
  });
}

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

/** 轮询 __trayInfo.closeBehavior 直到等于期望值（IPC 推送后事件驱动刷新，spec f31 §9；应用退出时读钩子返回 undefined 继续轮询） */
async function waitForCloseBehavior(
  app: ElectronApplication,
  expected: 'tray' | 'quit',
  timeoutMs = 20_000
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const info = await readTrayInfo(app);
    if (info && info.closeBehavior === expected) {
      return;
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`__trayInfo.closeBehavior 未在 ${timeoutMs}ms 内变为 ${expected}`);
}

// Electron 启动 + 内核拉起较慢，放宽整文件超时（M5 另设 300s：ensure_kernel 冷启动 + 复用等待）
test.describe.configure({ timeout: 180_000 });

test('托盘 M1（spec §13 M1）：关闭 → 窗口隐藏 + 内核存活 + 托盘已创建', async () => {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  try {
    const win = await app.firstWindow();
    await expect(win).toHaveTitle(/InkFlow/);
    const kernel = await waitKernelInfo(app);

    // 前置契约：托盘已创建（M1「托盘图标出现」的钩子面）+ 默认关闭行为 'tray'（spec §2.2）
    const tray = await waitForTrayCreated(app);
    expect(tray.closeBehavior).toBe('tray');

    // 触发关闭：走自绘关闭按钮的真实路径（renderer → window:close IPC → mainWindow.close() →
    // win.on('close') 拦截）。⚠️ 不可用 window.close()：sandbox renderer 下它直接销毁窗口、
    // 不触发主进程 close 事件（2026-08-08 E2E 实测），拦截不生效。
    await win.evaluate(() => window.INKFLOW_API.windowControls.close());

    // 窗口隐藏（spec §5.2 tray 行：preventDefault + hide，内核保持运行）
    await waitForWindowVisible(app, false);

    // 内核存活：pid 存活 + /health 200 + __kernelInfo 未清空
    expect(isAlive(kernel.pid), `内核 pid=${kernel.pid} 应保持存活`).toBe(true);
    expect(await healthCheck(kernel)).toBe(200);
    const still = await readKernelInfo(app);
    expect(still?.pid).toBe(kernel.pid);
  } finally {
    await app.close().catch(() => {});
  }
});

test('托盘 M2a（spec §13 M2 前半）：托盘「打开」→ 窗口恢复可见', async () => {
  // 独立 launch（项目惯例：每个用例独立 app，workers=1），先构造隐藏态再验证恢复
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  try {
    const win = await app.firstWindow();
    const kernel = await waitKernelInfo(app);

    // 先关闭 → 隐藏（默认 tray 行为；自绘按钮真实路径，见 M1 注释）
    await win.evaluate(() => window.INKFLOW_API.windowControls.close());
    await waitForWindowVisible(app, false);

    // 托盘「打开主窗口」→ __trayActions.show()（spec §9：CI 无真实托盘，钩子直调）
    await trayShow(app);
    await waitForWindowVisible(app, true);

    // 恢复不重建内核（pid 不变）
    const after = await readKernelInfo(app);
    expect(after?.pid).toBe(kernel.pid);
  } finally {
    await app.close().catch(() => {});
  }
});

test('托盘 M2b（spec §13 M2 后半）：托盘「退出」→ 内核回收 + 应用退出', async () => {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  let appExited = false;
  try {
    const kernel = await waitKernelInfo(app);
    await waitForTrayCreated(app);

    // 托盘「退出」→ shutdown()（spec §5.2：stopKernel 完整回收 → app.exit(0)）
    await trayQuit(app);

    // 应用退出（shutdown 先回收内核再 exit → 退出完成即内核必死）
    await waitForAppExit(app, 20_000);
    appExited = true;
    expect(isAlive(kernel.pid), `内核 pid=${kernel.pid} 应在托盘退出后回收`).toBe(false);
  } finally {
    if (!appExited) {
      await app.close().catch(() => {});
    }
  }
});

test('托盘 M3（spec §13 M3）：设置「直接退出」→ 关闭 = 完整退出（内核回收）', async () => {
  // 注：当前 #78 行为（关闭 → 无条件 shutdown）恰为 quit 语义 → RED 阶段本用例可能已绿，
  // 属回归保护（F31 改造 window-all-closed 条件退出后必须保持 quit 模式仍完整退出）
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  let appExited = false;
  try {
    const win = await app.firstWindow();
    const kernel = await waitKernelInfo(app);
    await waitForTrayCreated(app);

    // 设置页「关闭窗口时=直接退出」的 IPC 落点 = 主进程 setCloseBehavior（spec §2.3/§6.2）
    await traySetCloseBehavior(app, 'quit');
    const tray = await readTrayInfo(app);
    expect(tray?.closeBehavior, '__trayInfo.closeBehavior 应在 setCloseBehavior 后生效').toBe('quit');

    // 触发窗口关闭 → 不拦截（spec §5.2 quit 行）→ window-all-closed → shutdown()
    // （自绘按钮真实路径，见 M1 注释）
    await win.evaluate(() => window.INKFLOW_API.windowControls.close());

    await waitForAppExit(app, 20_000);
    appExited = true;
    expect(isAlive(kernel.pid), `内核 pid=${kernel.pid} 应在完整退出后回收`).toBe(false);
  } finally {
    if (!appExited) {
      await app.close().catch(() => {});
    }
  }
});

test('托盘 M4（spec §13 M4）：单实例——二次启动 → 聚焦已有窗口（无第二窗口/内核）', async () => {
  const appA = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  let appB: ElectronApplication | null = null;
  try {
    const winA = await appA.firstWindow();
    await expect(winA).toHaveTitle(/InkFlow/);
    const kernelA = await waitKernelInfo(appA);

    // 先隐藏 A（默认 tray 行为）→ second-instance 的「聚焦恢复」才可观测（spec §5.5 #8；
    // 自绘按钮真实路径，见 M1 注释）
    await winA.evaluate(() => window.INKFLOW_API.windowControls.close());
    await waitForWindowVisible(appA, false);

    // 第二次启动同 MAIN_JS：单实例锁获取失败（spec §5.5）→ 快速退出，不 spawn 不建窗
    try {
      appB = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
    } catch (err) {
      // B 在 Playwright 连接建立前即退出（锁失败 → app.quit）——本身即「第二进程快速退出」证据，
      // 继续断言 A 侧状态（RED 阶段无锁实现 → B 正常启动 → 下方 waitForAppExit 超时失败）
      console.warn('[e2e-tray M4] 第二实例未及连接即退出（预期内）：', err);
    }
    if (appB) {
      await waitForAppExit(appB, 30_000);
    }

    // A 被 second-instance 聚焦 → 窗口恢复可见（spec §5.5）
    await waitForWindowVisible(appA, true);
    // 无第二内核：__kernelInfo.pid 不变
    const kernelA2 = await readKernelInfo(appA);
    expect(kernelA2?.pid).toBe(kernelA.pid);
    // 窗口唯一
    const winCount = await appA.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length);
    expect(winCount).toBe(1);
  } finally {
    if (appB) {
      await appB.close().catch(() => {});
    }
    await appA.close().catch(() => {});
  }
});

test('托盘 M5（spec §13 M5）：GUI 复用 CLI 预拉起内核（pid 不变）', async () => {
  const backendDir = path.join(REPO_ROOT, 'backend');
  const pythonExe = path.join(backendDir, '.venv', 'Scripts', 'python.exe');
  test.skip(
    !existsSync(pythonExe),
    `backend venv 未就绪（${pythonExe}），跳过内核复用用例（父 agent 需先 uv sync）`
  );
  // ensure_kernel 冷启动（chromadb 初始化 + uvicorn + seed）可能 >60s → 本用例独立放宽
  test.setTimeout(300_000);

  // 1. Python 侧 ensure_kernel 预拉起常驻内核（F30：写 %APPDATA%\\InkFlow\\kernel.json，spec §5.4）
  const script =
    'import asyncio; from inkflow.infrastructure.kernel.bootstrap import ensure_kernel; ' +
    'h = asyncio.run(ensure_kernel()); print(h.pid)';
  const launched = spawnSync(pythonExe, ['-c', script], {
    cwd: backendDir,
    encoding: 'utf8',
    timeout: 120_000,
  });
  expect(launched.status, `ensure_kernel 失败：${launched.stderr ?? ''}`).toBe(0);
  const pidLine = (launched.stdout ?? '')
    .trim()
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .pop();
  const prePid = Number(pidLine);
  expect(
    Number.isInteger(prePid) && prePid > 0,
    `未从 ensure_kernel 输出解析出 pid：${launched.stdout ?? ''}`
  ).toBe(true);
  expect(isAlive(prePid), `预拉起内核 pid=${prePid} 应存活`).toBe(true);

  // 2. GUI 启动 → 复用判定（spec §5.3：读 kernel.json → pid 存活 + /health 200 → 不 spawn）
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  try {
    const kernel = await waitKernelInfo(app);
    expect(kernel.pid, 'GUI 必须复用 CLI 预拉起的内核（不 spawn 新内核）').toBe(prePid);
    expect(await healthCheck(kernel)).toBe(200);
  } finally {
    await app.close().catch(() => {});
    // GUI 复用路径不持有内核（kernelProcess=null → stopKernel 直接返回）→ 预拉起内核成为孤儿，
    // 必须显式回收，避免残留进程 + kernel.json 指向活内核污染后续用例
    try {
      process.kill(prePid);
    } catch {
      // 已退出
    }
  }
});

// ────────────────────────────────────────────────────────────────
// F32 设置持久化（#152，spec §9.1/§9.4 E2E 行；M6 验收）：关闭行为持久化重启保留
// ────────────────────────────────────────────────────────────────
test.describe('F32 关闭行为持久化（#152）', () => {
  test('F32 M6（spec §9.4/M6）：关闭行为「直接退出」→ 重启 → 关闭窗口仍完整退出（持久化生效）', async () => {
    // 重启用例 = 二次 launch + 二次内核冷启动，放宽单用例超时（文件级 180s 不足）
    test.setTimeout(300_000);
    // 设计假设（spec §5.3/§9.1）：close_behavior 持久化权威 = 后端 app_settings；
    // 设置页 Select → setCloseBehavior = PATCH 成功 → IPC 推送主进程 → store 更新（D9）；
    // 重启后 renderer initFromBackend GET → close_behavior != 'tray' → IPC 推送主进程（启动初始化⑤）。
    // __trayInfo.closeBehavior 变 quit = 「PATCH 已落库 + 主进程内存已对齐」的确定性闸门。
    const userDataDir = mkdtempSync(path.join(tmpdir(), 'inkflow-e2e-f32-tray-'));
    let app1Exited = false;
    let app2Exited = false;
    try {
      // ── 第一程：设置页切「直接退出」→ 关闭窗口 = 完整退出（内核回收 + 进程退出）──
      const app1 = await launchAppWithUserData(userDataDir);
      try {
        const win1 = await app1.firstWindow();
        const kernel1 = await waitKernelInfo(app1);
        await waitForTrayCreated(app1);

        // 设置页 → 常规分类 → 关闭窗口时 Select → 「直接退出」（真实 UI 路径，非 __trayActions 钩子）
        await gotoNav(win1, '设置');
        await expect(win1.getByTestId('settings-panel')).toBeVisible();
        await win1.getByRole('combobox', { name: '关闭窗口时' }).click();
        await win1.getByRole('option', { name: '直接退出', exact: true }).click();
        await expect(win1.getByRole('combobox', { name: '关闭窗口时' })).toContainText('直接退出');

        // 确定性闸门：PATCH 落库 + IPC 推送生效（spec §5.3：IPC 只在 PATCH 成功后推送）
        await waitForCloseBehavior(app1, 'quit');

        // 关闭窗口（自绘按钮真实路径，见 M1 注释：window.close() 不触发主进程 close 拦截）→
        // quit 语义 → window-all-closed → shutdown() → 完整退出
        await win1.evaluate(() => window.INKFLOW_API.windowControls.close());
        await waitForAppExit(app1, 20_000);
        app1Exited = true;
        expect(isAlive(kernel1.pid), `第一程内核 pid=${kernel1.pid} 应回收`).toBe(false);
      } finally {
        if (!app1Exited) {
          await app1.close().catch(() => {});
        }
      }

      // ── 第二程：复用同一数据目录重启 → 持久化生效 → 关闭窗口仍完整退出 ──
      const app2 = await launchAppWithUserData(userDataDir);
      try {
        const win2 = await app2.firstWindow();
        const kernel2 = await waitKernelInfo(app2);
        await waitForTrayCreated(app2);

        // 持久化生效断言：initFromBackend 启动初始化⑤ 已把 quit 推回主进程（未回退默认 tray）
        await waitForCloseBehavior(app2, 'quit');

        // UI 层确认：设置页 Select 显示「直接退出」（store 值来自后端 GET）
        await gotoNav(win2, '设置');
        await expect(win2.getByTestId('settings-panel')).toBeVisible();
        await expect(win2.getByRole('combobox', { name: '关闭窗口时' })).toContainText('直接退出');

        // 清理（内核仍存活时执行）：恢复共享内核 DB close_behavior='tray'（spec §2.2 默认值），
        // 避免持久化残留污染后续托盘用例（M1 断言默认 'tray'）。主进程内存仍为 quit，
        // 不影响本程「关闭 → 完整退出」断言；直接 fetch 绕过 renderer，UI 无感知
        const restore = await fetch(`http://127.0.0.1:${kernel2.port}/api/v1/settings`, {
          method: 'PATCH',
          headers: {
            'X-InkFlow-Token': kernel2.token,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ close_behavior: 'tray' }),
        });
        expect(restore.status, '恢复 close_behavior=tray 应 200').toBe(200);

        // 关闭窗口 → 仍完整退出（重启后行为未回退默认）
        await win2.evaluate(() => window.INKFLOW_API.windowControls.close());
        await waitForAppExit(app2, 20_000);
        app2Exited = true;
        expect(isAlive(kernel2.pid), `第二程内核 pid=${kernel2.pid} 应回收`).toBe(false);
      } finally {
        if (!app2Exited) {
          await app2.close().catch(() => {});
        }
      }
    } finally {
      try {
        rmSync(userDataDir, { recursive: true, force: true });
      } catch {
        // 临时目录清理失败（Windows 文件锁）不阻塞用例
      }
    }
  });
});
