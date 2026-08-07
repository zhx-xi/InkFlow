/**
 * 设定库域 E2E（当前为导航流中的设定库断言，ADR-028 E2 将补用例）
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-library
 *
 * 基建（复用 electron-pages.spec.ts 模式）：
 * - _electron.launch + waitKernelInfo（__kernelInfo 注入轮询，窗口交互前必须先等内核就绪，否则 401）
 * - 真实内核 + 真实渲染：创建项目 = 真实 POST 落库；用例间用唯一书名 `E2E-<场景>-<ts>` 隔离数据
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

/** 启动应用（Electron + 真实内核），等待窗口与内核就绪 */
async function launchApp(): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置；NavLink 与 Agent 快捷 Link 均为 role=link） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

/**
 * 通过 UI 创建项目：new-project-btn → 对话框填书名 → 「创建」。
 * 契约：创建成功 → navigate('/writing')，等待写作页 project-tree 出现。
 */
async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  // getByLabel 通过关联 label / aria-label 查找（dialog 内唯一）
  await window.getByLabel('书名').fill(name);
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ timeout: 120_000 });

// ────────────────────────────────────────────────────────────────
// 7. 导航流闭环：写作 → 项目 → 设定库 → 设置（spec §7.7 E2E）
// ────────────────────────────────────────────────────────────────
test('导航流：创建项目 → 写作 → 项目 → 设定库 → 设置 侧边栏闭环', async () => {
  const { app, window } = await launchApp();
  try {
    const name = `E2E-导航流-${Date.now()}`;
    await createProjectViaUi(window, name);
    expect(await window.evaluate(() => location.hash)).toContain('/writing');
    await expect(window.getByTestId('project-tree')).toBeVisible();

    // 侧边「项目」→ 项目页
    await gotoNav(window, '项目');
    expect(await window.evaluate(() => location.hash)).toContain('/projects');
    await expect(window.getByTestId('new-project-btn')).toBeVisible();

    // 侧边「设定库」→ 设定库页（有当前项目 → 项目选择器与分类 tab 存在）
    await gotoNav(window, '设定库');
    expect(await window.evaluate(() => location.hash)).toContain('/library');
    await expect(window.getByTestId('library-page')).toBeVisible();
    await expect(window.getByTestId('library-project-select')).toBeVisible();
    await expect(window.getByTestId('library-tabs')).toBeVisible();

    // 侧边「设置」→ 设置页
    await gotoNav(window, '设置');
    expect(await window.evaluate(() => location.hash)).toContain('/settings');
    await expect(window.getByTestId('settings-page')).toBeVisible();
    await expect(window.getByTestId('settings-nav')).toBeVisible();
  } finally {
    await app.close();
  }
});
