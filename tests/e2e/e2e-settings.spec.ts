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
 *
 * F32 E2E 契约（#152，spec §9.1/§9.4）：default_words 跳页保留（M1）+ 主题后端持久化重启保留（M3）。
 * 重启用例隔离策略（spec §9.1 评审 🟡 修订）：独立 userData 临时目录（launch 传 --user-data-dir），
 * 二次 launch 显式复用同一目录；普通用例沿用既有模式。
 */
import path from 'node:path';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
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

/** 启动应用（独立 userData 临时目录——F32 重启用例隔离策略，spec §9.1：launch 传 --user-data-dir） */
async function launchAppWithUserData(
  userDataDir: string
): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({
    args: [MAIN_JS, `--user-data-dir=${userDataDir}`],
    cwd: FRONTEND_DIR,
  });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

/** 通过 UI 创建项目（复制自 e2e-projects.spec.ts：new-project-btn → 对话框填书名 → 创建 → 自动跳写作页） */
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

// ────────────────────────────────────────────────────────────────
// F32 设置持久化（#152，spec §9.1/§9.4 E2E 行；M1/M3 验收）
// ────────────────────────────────────────────────────────────────
test.describe('F32 设置持久化（#152）', () => {
  test('F32 M1（spec §9.4/M1）：default_words 输入后直接切导航 → 返回设置页值保留（跳页不丢）', async () => {
    const { app, window } = await launchApp();
    try {
      // 前置：创建当前项目（flush 契约「无当前项目不保存」，spec §5.4）——UI 创建唯一项目，
      // 创建成功自动进入写作页（project-tree 出现即 currentProjectId 已就位）
      const name = `E2E-F32-M1-${Date.now()}`;
      await createProjectViaUi(window, name);
      expect(await window.evaluate(() => location.hash)).toContain('/writing');

      // 设置页 → 常规分类 → 新章节默认字数输入 5000
      await gotoNav(window, '设置');
      await expect(window.getByTestId('settings-panel')).toBeVisible();
      const input = window.getByLabel('新章节默认字数');
      await input.fill('5000');

      // 输入后不手动 blur：直接点侧边栏「写作」导航——真实浏览器点击会先 blur（onBlur 保存），
      // 随后组件卸载 cleanup 兜底 flush（spec §5.4 双路径）；任一路径成功即满足「返回后值保留」
      await gotoNav(window, '写作');
      expect(await window.evaluate(() => location.hash)).toContain('/writing');
      await expect(window.getByTestId('project-tree')).toBeVisible();

      // 返回设置页：PATCH 落库 + project store 本地合并（updateConfig）→ remount 懒初始化读新值；
      // PATCH 在途窗口输入框可能短暂为旧值 → toHaveValue 自动重试兜底
      await gotoNav(window, '设置');
      await expect(window.getByTestId('settings-panel')).toBeVisible();
      await expect(window.getByLabel('新章节默认字数')).toHaveValue('5000');
    } finally {
      await app.close();
    }
  });

  test('F32 M3（spec §9.4/M3）：主题切 night → 重启（二次 launch 同数据目录）→ data-theme=night', async () => {
    // 重启用例 = 二次 launch + 二次内核冷启动，放宽单用例超时（文件级 120s 不足）
    test.setTimeout(240_000);
    // 设计假设（spec §5.2/§9.1）：主题持久化权威 = 后端 app_settings（PATCH 落库）+ localStorage
    // 快照兜底；重启 = 二次 _electron.launch 复用同一 userData 目录（独立临时目录，不碰默认 profile）
    const userDataDir = mkdtempSync(path.join(tmpdir(), 'inkflow-e2e-f32-settings-'));
    try {
      // ── 第一程：设置页切 night（乐观生效 + PATCH 落库）──
      const first = await launchAppWithUserData(userDataDir);
      try {
        await gotoNav(first.window, '设置');
        await expect(first.window.getByTestId('settings-panel')).toBeVisible();
        await first.window.getByTestId('theme-preview-night').click();
        await expect
          .poll(() => first.window.evaluate(() => document.documentElement.dataset.theme))
          .toBe('night');
        // PATCH 落库确认（setter 为 fire-and-forget，spec §5.2）：轮询后端 GET /settings，
        // 避免 app.close() 与 PATCH 竞态导致「重启保留」测不到后端权威路径
        await expect
          .poll(
            () =>
              fetch(`http://127.0.0.1:${first.kernel.port}/api/v1/settings`, {
                headers: { 'X-InkFlow-Token': first.kernel.token },
              })
                .then((r) => r.json())
                .then((s: { theme?: string }) => s.theme),
            { timeout: 10_000 }
          )
          .toBe('night');
      } finally {
        await first.app.close();
      }

      // ── 第二程：复用同一数据目录重启 → 主题仍为 night（后端权威 + 快照兜底）──
      const second = await launchAppWithUserData(userDataDir);
      try {
        await expect
          .poll(() => second.window.evaluate(() => document.documentElement.dataset.theme))
          .toBe('night');
        // store 层确认：设置页「夜航」radio 选中（既有断言方式：radio 反映 store.theme）
        await gotoNav(second.window, '设置');
        await expect(second.window.getByTestId('settings-panel')).toBeVisible();
        await expect(second.window.getByRole('radio', { name: /夜航/ })).toBeChecked();
      } finally {
        await second.app.close();
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
