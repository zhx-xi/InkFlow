/**
 * 模型管理页域 E2E（ADR-028 E1 拆分自 electron-pages.spec.ts）
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-models
 *
 * 基建（复用 electron-pages.spec.ts 模式）：
 * - _electron.launch + waitKernelInfo（__kernelInfo 注入轮询，窗口交互前必须先等内核就绪，否则 401）
 * - 真实内核 + 真实渲染；用例清空持久化 UI 偏好（inkflow.ui）保证中文文案确定性
 * - 每个用例独立 launch app（workers=1，串行）
 */
import path from 'node:path';
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

/** 读主进程测试钩子（dev 模式暴露 globalThis.__kernelInfo，spec §3.6） */
async function readKernelInfo(
  app: ElectronApplication
): Promise<KernelInfo | undefined> {
  return app.evaluate(() => (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo);
}

/** 等待内核就绪（轮询 __kernelInfo 注入；CI 冷启动 chromadb+内核 >20s，默认 30s） */
async function waitKernelInfo(app: ElectronApplication, timeoutMs = 30_000): Promise<KernelInfo> {
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

/** 启动应用（Electron + 真实内核），等待窗口与内核就绪 */
async function launchApp(): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

test.describe.configure({ timeout: 120_000 });

// ────────────────────────────────────────────────────────────────
// 9. 模型管理页：侧边栏入口可达 + 页面渲染（#106 F5，spec §8.5 L968）
// ────────────────────────────────────────────────────────────────
test('模型管理页：侧边栏「模型管理」→ /models 渲染（标题 + Provider 列表）', async () => {
  const { app, window } = await launchApp();
  try {
    // 同用例 8：清空持久化 UI 偏好保证中文文案确定性（zh）
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible();

    // 侧边栏入口：nav-item-models（#106 已转正为 /models NavLink，spec §8.5 F5）
    const navModels = window.getByTestId('nav-item-models');
    await expect(navModels).toBeVisible();
    await expect(navModels).toContainText('模型管理');
    await navModels.click();

    // 路由 + 页面骨架渲染（页标题 h1 = m.title）
    expect(await window.evaluate(() => location.hash)).toContain('/models');
    const page = window.getByTestId('models-page');
    await expect(page).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('heading', { level: 1 })).toContainText('模型管理');

    // Provider 列表区：lifespan seed 内置 4 provider（openai/deepseek/zhipu/ollama）
    const list = window.getByTestId('provider-list');
    await expect(list).toBeVisible();
    await expect(window.locator('[data-testid^="provider-card-"]')).toHaveCount(4);
    // 全新库 seed 按序插入 → openai 自增 id=1
    await expect(window.getByTestId('provider-card-1')).toContainText('openai');
  } finally {
    await app.close();
  }
});
