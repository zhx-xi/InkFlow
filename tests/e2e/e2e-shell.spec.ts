/**
 * Electron 壳 E2E 冒烟契约（#78；ADR-028 E1 拆分：壳契约专用 spec，CI 第一批恒跑 required）
 */
import path from 'node:path';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
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

/** 读主进程测试钩子（dev 模式暴露 globalThis.__kernelInfo = {pid, port, token}，spec §3.6） */
async function readKernelInfo(
  app: ElectronApplication
): Promise<KernelInfo | undefined> {
  return app.evaluate(() => (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo);
}

/**
 * 等待内核就绪（spec §3.2.1/3.2.3）：内核拉起需 python + uvicorn 启动时间，
 * INKFLOW_READY 到达前 __kernelInfo 尚未注入。轮询至多 20s（健康检查 2s 间隔 × 余量）。
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

// Electron 启动 + 内核拉起较慢，放宽整文件超时（崩溃拉起用例含 40s 轮询）
test.describe.configure({ timeout: 120_000 });

test('启动闭环：窗口出现（title 含 InkFlow）+ 内核进程存在 + /health 200 + M5 安全基线', async () => {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  try {
    const window = await app.firstWindow();
    await expect(window).toHaveTitle(/InkFlow/);

    // 品牌 logo 真实加载断言（#98 修复回归：CSP default-src 'self' 阻止 data: 内联 svg →
    // 破图（naturalWidth=0）。这是**真实 Chromium 渲染**验证——jsdom 单元测试无法覆盖。
    // #106 用户反馈：品牌 logo 已从顶栏移入侧边栏 AppNav 品牌区（d372c13）——契约位置同步。
    await expect
      .poll(
        () =>
          window.evaluate(() => {
            const img = document.querySelector<HTMLImageElement>('[data-testid="app-nav"] img');
            return img
              ? { w: img.naturalWidth, src: img.getAttribute('src') ?? '' }
              : null;
          }),
        { timeout: 10_000 }
      )
      .toMatchObject({
        w: expect.any(Number),
        src: expect.any(String),
      });
    const logo = await window.evaluate(() => {
      const img = document.querySelector<HTMLImageElement>('[data-testid="app-nav"] img');
      return img
        ? { w: img.naturalWidth, src: img.getAttribute('src') ?? '' }
        : null;
    });
    expect(logo).not.toBeNull();
    expect(logo!.w, '品牌 logo 必须真实解码（naturalWidth>0，破图=0）').toBeGreaterThan(0);
    expect(logo!.src, 'CSP \'self\' 下 logo 必须为独立文件路径（data: 内联会被阻止）').not.toContain('data:');
    expect(logo!.src).toMatch(/inkflow-icon-plain/);

    // 窗口加载完成 ≠ 内核就绪：INKFLOW_READY 需 python + uvicorn 启动时间，轮询等待注入
    const kernel = await waitKernelInfo(app);
    expect(kernel.pid).toBeGreaterThan(0);
    expect(kernel.port).toBeGreaterThan(0);
    expect(kernel.token).toBeTruthy();

    expect(await healthCheck(kernel)).toBe(200);

    // ── M5 安全基线（spec §3.3 / §3.7 M5）──
    // ① webPreferences：contextIsolation=true / nodeIntegration=false / sandbox=true。
    //    app.evaluate 传参（require('electron')）→ 主进程上下文；getLastWebPreferences
    //    取创建窗口时的实际配置。注：electron.d.ts 缺该方法类型（运行时 API 存在）→
    //    webContents 类型断言兜底；运行时无此 API 时回落 null 显式失败。
    const prefs = await app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows()[0];
      const wc = win?.webContents as unknown as {
        getLastWebPreferences?: () => {
          contextIsolation?: boolean;
          nodeIntegration?: boolean;
          sandbox?: boolean;
        };
      };
      return (
        wc?.getLastWebPreferences?.() ?? {
          contextIsolation: null,
          nodeIntegration: null,
          sandbox: null,
        }
      );
    });
    expect(prefs.contextIsolation).toBe(true);
    expect(prefs.nodeIntegration).toBe(false);
    expect(prefs.sandbox).toBe(true);

    // ② INKFLOW_API 注入（renderer 上下文：window.evaluate 在页面主 world 执行，可读
    //    contextBridge 暴露）。preload 先暴露 {baseURL: null, token: null} 占位，
    //    inkflow:ready 后整体重暴露实际值 → 轮询等待就绪，再断言键集精确为 {baseURL, token}。
    await expect
      .poll(
        () =>
          window.evaluate(() => {
            const w = window as unknown as {
              INKFLOW_API?: { baseURL: string | null; token: string | null };
            };
            return w.INKFLOW_API;
          }),
        { timeout: 10_000 }
      )
      .toMatchObject({ baseURL: expect.stringMatching(/^http:\/\/127\.0\.0\.1:\d+$/) });

    const api = await window.evaluate(() => {
      const w = window as unknown as { INKFLOW_API?: { baseURL: string; token: string } };
      return w.INKFLOW_API;
    });
    expect(api).toBeTruthy();
    // #106 自绘窗口按钮后 INKFLOW_API 含 windowControls 第 3 键；#167 F31 含 settings 第 4 键（preload 契约升级）
    expect(Object.keys(api!).sort()).toEqual(['baseURL', 'settings', 'token', 'windowControls']);
    expect(api!.baseURL).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
    expect(api!.token).toBeTruthy();

    // ③ 错误 token → 401（随机 token 校验生效，spec §3.7 M5）
    const badRes = await fetch(`http://127.0.0.1:${kernel.port}/health`, {
      headers: { 'X-InkFlow-Token': 'wrong-token' },
    });
    expect(badRes.status).toBe(401);
  } finally {
    await app.close();
  }
});

test('崩溃拉起：强杀内核 pid → 壳自动重拉（≤40s 覆盖退避上限）→ 新 pid 健康 200', async () => {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  try {
    const first = await waitKernelInfo(app);
    const oldPid = first.pid;

    // 强杀内核子进程（Windows：SIGTERM → TerminateProcess 语义；若已自行退出则忽略）
    try {
      process.kill(oldPid);
    } catch {
      // 进程已退出，同样落入崩溃拉起场景
    }

    // 轮询新 __kernelInfo：pid 必须变化（新内核）；指数退避上限 30s + 余量 → 40s
    let revived: KernelInfo | undefined;
    const deadline = Date.now() + 40_000;
    while (Date.now() < deadline) {
      const info = await readKernelInfo(app);
      if (info && info.pid !== oldPid) {
        revived = info;
        break;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }

    expect(revived, '崩溃后壳应在退避上限内拉起新内核').toBeDefined();
    expect(revived!.pid).not.toBe(oldPid);
    expect(await healthCheck(revived!)).toBe(200);
  } finally {
    await app.close();
  }
});

test('退出回收：app.close() → 内核 pid 不再存活（无僵尸）', async () => {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  const kernel = await waitKernelInfo(app);
  const pid = kernel.pid;

  await app.close();

  // spec §3.2.5 / §3.7 M4：关闭后内核必须被回收（优雅 kill → 3s 超时 → taskkill 兜底）
  expect(isAlive(pid), `内核 pid=${pid} 应已退出`).toBe(false);
});

// ────────────────────────────────────────────────────────────────
// 4. #143 壳 chrome：窗口控制按钮（自绘 header-wc-*；#106 拍板）
//    断言走主进程 BrowserWindow 状态（Playwright 无头启动异步延迟 → 轮询）
// ────────────────────────────────────────────────────────────────
test('窗口控制：最小化按钮 → isMinimized 轮询 true → restore 恢复', async () => {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  try {
    const window = await app.firstWindow();
    await waitKernelInfo(app);

    await window.getByTestId('header-wc-min').click();
    await expect
      .poll(
        () =>
          app.evaluate(({ BrowserWindow }) => {
            const win = BrowserWindow.getAllWindows()[0];
            return win ? win.isMinimized() : false;
          }),
        { timeout: 10_000 }
      )
      .toBe(true);

    // 还原（最小化后窗口不可交互，主进程 restore）
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.restore());
    await expect
      .poll(
        () =>
          app.evaluate(({ BrowserWindow }) => {
            const win = BrowserWindow.getAllWindows()[0];
            return win ? win.isMinimized() : true;
          }),
        { timeout: 10_000 }
      )
      .toBe(false);
  } finally {
    await app.close();
  }
});

test('窗口控制：最大化 ↔ 还原（aria-label Maximize↔Restore 跟随 IPC push）', async () => {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  try {
    const window = await app.firstWindow();
    await waitKernelInfo(app);

    const maxBtn = window.getByTestId('header-wc-max');
    await expect(maxBtn).toHaveAttribute('aria-label', 'Maximize');

    await maxBtn.click();
    await expect
      .poll(
        () =>
          app.evaluate(({ BrowserWindow }) => {
            const win = BrowserWindow.getAllWindows()[0];
            return win ? win.isMaximized() : false;
          }),
        { timeout: 10_000 }
      )
      .toBe(true);
    // IPC push window:maximized-changed → 按钮 aria-label 切换 Restore
    await expect(maxBtn).toHaveAttribute('aria-label', 'Restore');

    // 还原
    await maxBtn.click();
    await expect
      .poll(
        () =>
          app.evaluate(({ BrowserWindow }) => {
            const win = BrowserWindow.getAllWindows()[0];
            return win ? win.isMaximized() : true;
          }),
        { timeout: 10_000 }
      )
      .toBe(false);
    await expect(maxBtn).toHaveAttribute('aria-label', 'Maximize');
  } finally {
    await app.close();
  }
});

test('窗口控制：关闭按钮（tray 语义）→ 窗口隐藏 + 内核存活', async () => {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  try {
    const window = await app.firstWindow();
    const kernel = await waitKernelInfo(app);
    const pid = kernel.pid;

    // 防 DB 残留 close_behavior='quit'（F32 M6 用例）破坏 tray 语义：显式复位
    await app.evaluate(
      (_electronModule: unknown, v: string) => {
        (globalThis as unknown as { __trayActions?: { setCloseBehavior(x: 'tray' | 'quit'): void } })
          .__trayActions?.setCloseBehavior(v as 'tray' | 'quit');
      },
      'tray'
    );

    // 自绘关闭按钮 UI 路径（renderer → window:close IPC → mainWindow.close() → 拦截隐藏）
    await window.getByTestId('header-wc-close').click();

    // 窗口隐藏 + 内核保持（tray 语义：preventDefault + hide）
    await expect
      .poll(
        () =>
          app.evaluate(() => {
            const info = (globalThis as unknown as {
              __trayInfo?: { windowVisible: boolean };
            }).__trayInfo;
            return info ? info.windowVisible : true;
          }),
        { timeout: 15_000 }
      )
      .toBe(false);
    expect(isAlive(pid), 'tray 关闭后内核必须存活').toBe(true);
    expect(await healthCheck(kernel)).toBe(200);
  } finally {
    await app.close();
  }
});
