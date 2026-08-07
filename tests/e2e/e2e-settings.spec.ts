/**
 * 设置页域 E2E（ADR-028 E1 拆分自 electron-pages.spec.ts）
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-settings
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

test.describe.configure({ timeout: 120_000 });

// ────────────────────────────────────────────────────────────────
// 5. 设置页：Agent 分类渲染（迁移自 Agent 页；agents 路由已删，spec §7.10 Q1=A）
// ────────────────────────────────────────────────────────────────
test('设置页：Agent 分类 → AgentChainCard（四角色+四开关）与默认模型下拉渲染', async () => {
  const { app, window } = await launchApp();
  try {
    // 侧边栏「设置」→ 默认落在常规分类（无 cat 参数）
    await gotoNav(window, '设置');
    expect(await window.evaluate(() => location.hash)).toContain('/settings');
    await expect(window.getByTestId('settings-cat-general')).toHaveAttribute('aria-current', 'page');

    // 点设置导航「Agent」分类 → 面板切换（URL cat=agent）
    await window.getByTestId('settings-cat-agent').click();
    expect(await window.evaluate(() => location.hash)).toContain('cat=agent');
    await expect(window.getByTestId('settings-agent-panel')).toBeVisible();

    // AgentChainCard（迁移自旧 agents 页，testid 不变）
    const chain = window.getByTestId('agent-chain-card');
    await expect(chain).toBeVisible();
    await expect(chain.getByRole('switch')).toHaveCount(4);
    await expect(chain).toContainText('Architect 大纲架构师');
    await expect(chain).toContainText('Writer 执笔');
    await expect(chain).toContainText('Auditor 审校');
    await expect(chain).toContainText('Reviser 修订');

    // 默认模型下拉（#106 前 AgentLlmCard 不挂载，不做断言）
    await expect(window.getByRole('combobox', { name: '默认模型' })).toBeVisible();

    // 链开关交互：config 为空 → 初始全 off；点 Architect 开关 → on；再点 → off
    const firstSwitch = chain.getByRole('switch').nth(0);
    await expect(firstSwitch).not.toBeChecked();
    await firstSwitch.click();
    await expect(firstSwitch).toBeChecked();
    await firstSwitch.click();
    await expect(firstSwitch).not.toBeChecked();
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 6. 设置页：常规分类主题切换（AppearanceCard 行为并入常规，spec §7.4）
// ────────────────────────────────────────────────────────────────
test('设置页：常规分类主题 radio 切换生效（html data-theme）', async () => {
  const { app, window } = await launchApp();
  try {
    // 侧边栏「设置」→ 默认常规分类（主题三选 radio 即在此面板）
    await gotoNav(window, '设置');
    expect(await window.evaluate(() => location.hash)).toContain('/settings');
    await expect(window.getByTestId('settings-panel')).toBeVisible();

    // 主题三选 radio（素笺/夜航/墨韵）
    const radios = window.getByRole('radio');
    await expect(radios).toHaveCount(3);
    await expect(window.getByRole('radio', { name: /素笺/ })).toBeVisible();
    await expect(window.getByRole('radio', { name: /夜航/ })).toBeVisible();
    await expect(window.getByRole('radio', { name: /墨韵/ })).toBeVisible();
    // 初始主题受系统深色偏好 + localStorage（inkflow.ui）持久化影响，不硬编码也不断言初始值

    // 点「夜航 · 深色」→ html data-theme=night + radio checked
    await window.getByRole('radio', { name: /夜航/ }).click();
    await expect
      .poll(() => window.evaluate(() => document.documentElement.dataset.theme))
      .toBe('night');
    await expect(window.getByRole('radio', { name: /夜航/ })).toBeChecked();

    // 点「墨韵 · 东方」→ data-theme=ink
    await window.getByRole('radio', { name: /墨韵/ }).click();
    await expect
      .poll(() => window.evaluate(() => document.documentElement.dataset.theme))
      .toBe('ink');
    await expect(window.getByRole('radio', { name: /墨韵/ })).toBeChecked();
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 8. 顶栏：主题/语言 Select 选择直达生效（#106 F5，spec §8.4 L958）
// ────────────────────────────────────────────────────────────────
test('顶栏：主题/语言 Select 展开全选项可见 + 选择直达生效（data-theme / 界面语言）', async () => {
  const { app, window } = await launchApp();
  try {
    // 清空持久化 UI 偏好（inkflow.ui）并重载：保证语言/主题初始确定性（zh / 默认），
    // 避免上次运行残留影响断言（Radix 选项文案按当前语言渲染）
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible();

    // ── 主题 Select（Radix combobox，testid=header-theme-select，aria-label=主题）──
    const themeSelect = window.getByTestId('header-theme-select');
    await expect(themeSelect).toBeVisible();
    await expect(themeSelect).toHaveAttribute('role', 'combobox');
    await themeSelect.click();
    // 展开后三选项全可见（素笺 · 纸张 / 夜航 · 深色 / 墨韵 · 东方）
    await expect(window.getByRole('option', { name: '素笺 · 纸张' })).toBeVisible();
    await expect(window.getByRole('option', { name: '夜航 · 深色' })).toBeVisible();
    await expect(window.getByRole('option', { name: '墨韵 · 东方' })).toBeVisible();
    // 选「夜航 · 深色」→ html data-theme=night（主题直达生效）+ trigger 显示当前值
    await window.getByRole('option', { name: '夜航 · 深色' }).click();
    await expect
      .poll(() => window.evaluate(() => document.documentElement.dataset.theme))
      .toBe('night');
    await expect(themeSelect).toContainText('夜航 · 深色');

    // ── 语言 Select（testid=header-lang-select，aria-label=语言）──
    const langSelect = window.getByTestId('header-lang-select');
    await expect(langSelect).toHaveAttribute('role', 'combobox');
    await langSelect.click();
    // 选 EN → 界面语言切换（侧边栏 nav 文案变英文）
    await window.getByRole('option', { name: 'EN', exact: true }).click();
    await expect(window.getByTestId('nav-item-models')).toContainText('Model Manager');
    await expect(window.getByTestId('nav-item-projects')).toContainText('Projects');

    // 切回中文（zh），避免持久化语言影响后续用例（既有用例断言中文文案）
    await langSelect.click();
    await window.getByRole('option', { name: /中文|Chinese/ }).click();
    await expect(window.getByTestId('nav-item-models')).toContainText('模型管理');
  } finally {
    await app.close();
  }
});
