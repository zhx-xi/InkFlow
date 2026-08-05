/**
 * Electron 壳 E2E 冒烟契约（#78，spec §3.6/§3.7：启动闭环 / 崩溃拉起 / 退出回收）
 *
 * 【待 GREEN】RED 阶段仅编写：out/main.js 由 Codex 实现 src/main.ts 后产出，
 * 在此之前运行必然失败（electron 无法加载不存在的入口）。
 * 运行方式：pnpm --filter electron test:e2e（本地手动，不进常规 CI，spec §3.6）
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
async function waitKernelInfo(app: ElectronApplication, timeoutMs = 20_000): Promise<KernelInfo> {
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
    // 契约：header 内 img 解码成功（naturalWidth > 0）且 src 为独立文件路径（非 data:）。
    await expect
      .poll(
        () =>
          window.evaluate(() => {
            const img = document.querySelector('header img');
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
      const img = document.querySelector('header img');
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
    expect(Object.keys(api!).sort()).toEqual(['baseURL', 'token']);
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
