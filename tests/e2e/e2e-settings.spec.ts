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
  // #595 契约：创建须 ≥1 个题材/标签（tags 多选勾选预设标签；Radix option 渲染于 portal，用 window 级查询）
  await window.getByTestId('tags-select').click();
  await window.getByRole('option', { name: '玄幻' }).click();
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
    await expect(chain).toContainText('架构师');
    await expect(chain).toContainText('写手');
    await expect(chain).toContainText('审校员');
    await expect(chain).toContainText('修订师');

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

    // 主题三选 radio（素笺/夜航/墨韵）——#479 后常规分类新增知识图谱提取卡片的
    // method radio（仅规则/仅 AI/规则+AI），故收窄到主题预览卡 testid，避免把
    // 提取方式 radio 计入「主题 radio=3」的断言
    const radios = window.getByTestId(/^theme-preview-/);
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
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

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
    // 选 EN → 界面语言切换（侧边栏 nav 文案变英文；#481：nav-item-models 已删 → 用设置项断言）
    await window.getByRole('option', { name: 'EN', exact: true }).click();
    await expect(window.getByTestId('nav-item-settings')).toContainText('Settings');
    await expect(window.getByTestId('nav-item-projects')).toContainText('Projects');

    // 切回中文（zh），避免持久化语言影响后续用例（既有用例断言中文文案）
    await langSelect.click();
    await window.getByRole('option', { name: /中文|Chinese/ }).click();
    await expect(window.getByTestId('nav-item-settings')).toContainText('设置');
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

// ────────────────────────────────────────────────────────────────
// E3 设置页 Agent 链/快捷键 E2E 补测（#105 合入后：#105 🔴-2 即改即存 + 快捷键面板）
// 新增用例：Agent 四角色开关（无项目纯 UI）/ 默认模型下拉落库 / 开关即改即存 / 快捷键面板渲染
// ────────────────────────────────────────────────────────────────

/** 直调内核 API（X-InkFlow-Token 认证；204 无 body 返回 undefined，否则解析 JSON） */
async function fetchKernel(kernel: KernelInfo, path: string, init?: RequestInit): Promise<any> {
  const res = await fetch(`http://127.0.0.1:${kernel.port}${path}`, {
    ...init,
    headers: {
      'X-InkFlow-Token': kernel.token,
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 204) return undefined;
  return res.json();
}

// ────────────────────────────────────────────────────────────────
// E3-1 Agent 链四角色开关（无项目纯 UI 状态；store 纯内存无持久化）
// ────────────────────────────────────────────────────────────────
test('设置页：Agent 链四角色开关逐个切换（无项目纯 UI 状态）', async () => {
  const { app, window } = await launchApp();
  try {
    // 清空持久化 UI 偏好（inkflow.ui）并重载：保证语言/主题初始确定性（zh）
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    // 设置页 → Agent 分类 → AgentChainCard
    await gotoNav(window, '设置');
    await window.getByTestId('settings-cat-agent').click();
    const chain = window.getByTestId('agent-chain-card');
    await expect(chain).toBeVisible();

    // 无当前项目：agent store 纯内存 config={} → 初始全 off 可稳定断言；
    // 逐个角色：初始 off → 点开 on → 再点回 off（getByRole name 子串匹配在 card 内唯一）
    const roles = ['架构师', '写手', '审校员', '修订师'];
    for (const name of roles) {
      const sw = chain.getByRole('switch', { name });
      await expect(sw).not.toBeChecked();
      await sw.click();
      await expect(sw).toBeChecked();
      await sw.click();
      await expect(sw).not.toBeChecked();
    }
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// E3-2 默认模型下拉（有项目：PATCH 落库确认）
// ────────────────────────────────────────────────────────────────
test('设置页：默认模型下拉选 deepseek/deepseek-v4-flash → 直调内核确认 PATCH 落库（F42 #268 R1：provider/model 选项）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    // 前置：UI 创建唯一项目（persist 契约「无当前项目不保存」）
    const name = `E2E-AgentModel-${Date.now()}`;
    await createProjectViaUi(window, name);
    expect(await window.evaluate(() => location.hash)).toContain('/writing');

    // 直调内核 GET /projects 按唯一名找项目 id（不硬编码 DB 持久 id）
    const list = await fetchKernel(kernel, '/api/v1/projects');
    const project = list.items.find((p: { name: string }) => p.name === name);
    expect(project).toBeTruthy();
    const projectId = project.id as string;

    // F42 #268 R1：默认模型下拉选项 = provider-configs chat 模型列表（spec §5.2 Q3）——
    // seed provider models 初始为空，先直调内核给 deepseek 添加 chat 模型；
    // 幂等：始终 PATCH 为「去重后 models + deepseek-v4-flash」（默认 userData 持久 DB，
    // 重跑残留的重复模型一并自愈，避免下拉出现重复 option）
    const providers = await fetchKernel(kernel, '/api/v1/provider-configs');
    const deepseek = providers.items.find((p: { name: string }) => p.name === 'deepseek');
    expect(deepseek).toBeTruthy();
    const deduped = deepseek.models.filter(
      (m: { id: string }, i: number, arr: Array<{ id: string }>) =>
        m.id !== 'deepseek-v4-flash' || arr.findIndex((x) => x.id === m.id) === i,
    );
    if (
      deduped.length !== deepseek.models.length ||
      !deepseek.models.some((m: { id: string }) => m.id === 'deepseek-v4-flash')
    ) {
      await fetchKernel(kernel, `/api/v1/provider-configs/${deepseek.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          models: [...deduped, { id: 'deepseek-v4-flash', type: 'chat', roles: [] }],
        }),
      });
    }
    // 数据源变更 → 切「常规」再切回「Agent」分类（AgentChainCard 条件渲染卸载→重挂载，
    // 挂载 loadProviders 拉取最新列表；不可 window.reload——project store currentProjectId
    // 非持久化，reload 后 persist 早退不发 PATCH）
    await gotoNav(window, '设置');
    await window.getByTestId('settings-cat-general').click();
    await window.getByTestId('settings-cat-agent').click();

    // 设置页 → Agent 分类 → 默认模型下拉选 deepseek/deepseek-v4-flash（option 为 Radix portal，展开后才存在；
    // first() 防持久 DB 残留重复模型导致的 strict mode violation——点击任一重复项语义等价）
    const combo = window.getByRole('combobox', { name: '默认模型' });
    await expect(combo).toBeVisible();
    await combo.click();
    await window.getByRole('option', { name: 'deepseek/deepseek-v4-flash', exact: true }).first().click();
    await expect(combo).toContainText('deepseek/deepseek-v4-flash');

    // saveConfig 为 fire-and-forget → 轮询后端 GET /projects/{id} 确认 config.model 落库
    // （R1：完整 provider/model 值，非裸 provider 名）
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.model;
        },
        { timeout: 10_000 }
      )
      .toBe('deepseek/deepseek-v4-flash');
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// E3-3 Agent 链开关即改即存（有项目：PATCH 落库确认；#225 语义升级 2026-08-10）
// ────────────────────────────────────────────────────────────────
test('设置页：Agent 链开关即改即存（#225 三态语义：null=关闭 / 字符串=开启 / __default__=跟随默认）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    // 前置：UI 创建唯一项目
    const name = `E2E-AgentSwitch-${Date.now()}`;
    await createProjectViaUi(window, name);
    const list = await fetchKernel(kernel, '/api/v1/projects');
    const project = list.items.find((p: { name: string }) => p.name === name);
    expect(project).toBeTruthy();
    const projectId = project.id as string;

    // 设置页 → Agent 分类 → Writer 开关
    await gotoNav(window, '设置');
    await window.getByTestId('settings-cat-agent').click();
    const chain = window.getByTestId('agent-chain-card');
    await expect(chain).toBeVisible();
    const writer = chain.getByRole('switch', { name: '写手' });

    // #225 语义：新项目默认 config.agent_* = null = 关闭 → 初始 off
    // （旧实现 checked = value !== undefined → null 误显示 on，#225 根因）
    await expect(writer).not.toBeChecked();

    // 点开 → sentinel "__default__"（跟随默认，前端不暴露中间态 UI）
    await writer.click();
    await expect(writer).toBeChecked();
    // 开态落库断言（#225：字符串值落库 roundtrip；旧实现开 = null → 本断言 RED）
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_writer;
        },
        { timeout: 10_000 }
      )
      .toBe('__default__');

    // 点关 → 显式 null（禁用角色）→ 开关 off
    await writer.click();
    await expect(writer).not.toBeChecked();
    // 关态落库断言（#225 核心：显式 null 落库，替代旧 updated_at 锚点——
    // 旧实现关闭发 undefined 被省略 → 后端缺失不改 → 此处恒非 null 或保持旧值）
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_writer;
        },
        { timeout: 10_000 }
      )
      .toBeNull();
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// #225 M2：Agent 链开关「关闭」重启持久化（二次 launch 同数据目录，F32 M3 模式）
// ────────────────────────────────────────────────────────────────
test('#225 M2：Agent 链开关关闭 → 重启（二次 launch 同数据目录）→ 开关仍关闭', async () => {
  test.setTimeout(240_000);
  const userDataDir = mkdtempSync(path.join(tmpdir(), 'inkflow-e2e-225-agent-'));

  // ── 第一程：创建项目 → Writer 点开（落库 __default__）→ 点关（落库 null）──
  const first = await launchAppWithUserData(userDataDir);
  let projectId: string;
  try {
    await first.window.evaluate(() => localStorage.clear());
    await first.window.reload();
    await expect(first.window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    const name = `E2E-225-Persist-${Date.now()}`;
    await createProjectViaUi(first.window, name);
    const list = await fetchKernel(first.kernel, '/api/v1/projects');
    const project = list.items.find((p: { name: string }) => p.name === name);
    expect(project).toBeTruthy();
    projectId = project.id as string;

    await gotoNav(first.window, '设置');
    await first.window.getByTestId('settings-cat-agent').click();
    const writer = first.window.getByTestId('agent-chain-card').getByRole('switch', { name: '写手' });
    await expect(writer).not.toBeChecked(); // 新项目默认 null = 关闭

    // 开 → 关（关闭 = 显式 null 落库）
    await writer.click();
    await expect(writer).toBeChecked();
    await writer.click();
    await expect(writer).not.toBeChecked();
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(first.kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_writer;
        },
        { timeout: 10_000 }
      )
      .toBeNull(); // 关闭态显式 null 已落库（非缺键/非旧值）
  } finally {
    await first.app.close();
  }

  // ── 第二程：复用同一数据目录重启 → 后端权威 + UI 开关状态双断言 ──
  const second = await launchAppWithUserData(userDataDir);
  try {
    await second.window.evaluate(() => localStorage.clear());
    await second.window.reload();
    await expect(second.window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    // ① 后端权威（不依赖 UI 导航，#232 未合时 currentProjectId 无法经卡片设置）：
    //    重启后内核读同一 DB → config.agent_writer 仍为 null（关闭）
    const r = await fetchKernel(second.kernel, `/api/v1/projects/${projectId}`);
    expect(r.config?.agent_writer).toBeNull();

    // ② UI 状态：设置页 Agent 分类 → Writer 开关显示关闭（重启后不误恢复开启）
    await gotoNav(second.window, '设置');
    await second.window.getByTestId('settings-cat-agent').click();
    await expect(
      second.window.getByTestId('agent-chain-card').getByRole('switch', { name: '写手' })
    ).not.toBeChecked();
  } finally {
    await second.app.close();
  }

  try {
    rmSync(userDataDir, { recursive: true, force: true });
  } catch {
    // 临时目录清理失败（Windows 文件锁）不阻塞用例
  }
});

// ────────────────────────────────────────────────────────────────
// E3-4 快捷键面板渲染（常规分类：五组标签 + 组合键）
// ────────────────────────────────────────────────────────────────
test('设置页：快捷键面板渲染（五组快捷键标签与组合键）', async () => {
  const { app, window } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    await gotoNav(window, '设置');
    await expect(window.getByTestId('settings-panel')).toBeVisible();
    const shortcuts = window.getByTestId('settings-shortcuts');
    await expect(shortcuts).toBeVisible();
    await expect(shortcuts).toContainText('快捷键一览');

    // 五组断言：标签与组合键均 exact 匹配（Ctrl+Enter 是 Ctrl+Shift+Enter 子串，必须 exact）
    const pairs: Array<[string, string]> = [
      ['撤销', 'Ctrl+Z'],
      ['重做', 'Ctrl+Y'],
      ['保存', 'Ctrl+S'],
      ['续写', 'Ctrl+Enter'],
      ['生成', 'Ctrl+Shift+Enter'],
    ];
    for (const [label, combo] of pairs) {
      await expect(shortcuts.getByText(label, { exact: true })).toBeVisible();
      await expect(shortcuts.getByText(combo, { exact: true })).toBeVisible();
    }
  } finally {
    await app.close();
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// #276 E2E 契约（G7，范围 5）：设置页 RAG 向量状态 UI 状态流。
// 父侧范围裁定（2026-08-12）：E2E 环境无真实 embedding API 端点，reindex 成功闭环
// （fresh 持久化/日志断言）由真实模型冒烟（M3-M7 门禁）覆盖；此处只做 UI 状态流断言
// （横幅/按钮/对话框/负例），全部无需真实 embedding 调用——不点击 reindex 确认。
// 依赖：G1-G5 后端 vector status 端点、G6 设置页 RAG 区块 testid。
// ⚠️ 内核数据目录为共享持久库（dev 侧 instance.env → %APPDATA%\InkFlow；Electron
// --user-data-dir 只隔离渲染层 profile，不隔离 provider 注册表）→ 用例 setup 先清理
// 此前 E2E 遗留的 e2e-rag* 测试 provider（绝不触碰 seed 4 个），保证注册表确定性。
// ─────────────────────────────────────────────────────────────────────────────

/** 直调内核 API（X-InkFlow-Token 认证 + JSON body）：非 2xx 抛错；204 → data undefined。 */
async function apiJson(
  kernel: KernelInfo,
  method: string,
  path: string,
  body?: unknown,
): Promise<{ status: number; data: unknown }> {
  const res = await fetch(`http://127.0.0.1:${kernel.port}${path}`, {
    method,
    headers: {
      'X-InkFlow-Token': kernel.token,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`kernel API ${method} ${path} -> ${res.status}: ${detail}`);
  }
  const data = res.status === 204 ? undefined : await res.json();
  return { status: res.status, data };
}

/** 清理此前 E2E 运行遗留的 e2e-rag* 测试 provider（共享持久注册表；seed/用户 provider 不动）。 */
async function cleanupRagTestProviders(kernel: KernelInfo): Promise<void> {
  const { data } = await apiJson(kernel, 'GET', '/api/v1/provider-configs');
  const items = (data as { items: Array<{ id: number; name: string }> }).items ?? [];
  for (const p of items) {
    if (p.name.startsWith('e2e-rag')) {
      await apiJson(kernel, 'DELETE', `/api/v1/provider-configs/${p.id}`);
    }
  }
}

/**
 * 配置 embedding provider（e2e-rag + 落盘 mock key）→ 201。
 * 另需 POST /api/v1/settings/llm-keys：G1-G5 _build_store 对非本地 embedding provider
 * 强制 key 存在（APIKeyManager.load 抛错 → RAGUnavailableError → status no_embedding）。
 */
async function ensureEmbeddingProvider(
  kernel: KernelInfo,
  modelId: string,
): Promise<{ status: number }> {
  await cleanupRagTestProviders(kernel);
  let created: { status: number; data: unknown };
  try {
    created = await apiJson(kernel, 'POST', '/api/v1/provider-configs', {
      name: 'e2e-rag',
      base_url: 'https://api.test.example/v1',
      models: [{ id: modelId, type: 'embedding' }],
    });
  } catch (err) {
    // 同名残留（422）→ 幂等复用：PATCH 刷新 models（正常已被 cleanup 清掉，仅兜底）
    if (!(err instanceof Error) || !/422/.test(err.message)) throw err;
    const { data } = await apiJson(kernel, 'GET', '/api/v1/provider-configs');
    const existing = ((data as { items: Array<{ id: number; name: string }> }).items ?? []).find(
      (p) => p.name === 'e2e-rag',
    );
    if (!existing) throw err;
    created = await apiJson(kernel, 'PATCH', `/api/v1/provider-configs/${existing.id}`, {
      base_url: 'https://api.test.example/v1',
      models: [{ id: modelId, type: 'embedding' }],
    });
  }
  await apiJson(kernel, 'POST', '/api/v1/settings/llm-keys', {
    provider: 'e2e-rag',
    api_key: 'e2e-mock-key',
  });
  return created;
}

/** 设置页 → 模型分类：ModelsPanel 挂载 → fetchVectorStatus → RAG 状态卡片出现。 */
async function openRagStatus(window: Page): Promise<void> {
  await gotoNav(window, '设置');
  await window.getByTestId('settings-cat-models').click();
  await expect(window.getByTestId('rag-status-card')).toBeVisible({ timeout: 15_000 });
}

// ─────────────────────────────────────────────────────────────────────────────
// RAG 向量状态区块（#276）——4 个 UI 状态流用例（无真实 embedding 调用）。
// ─────────────────────────────────────────────────────────────────────────────
test.describe('RAG 向量状态区块（#276）', () => {
  /** 独立 userData 临时目录（渲染层隔离；内核 DB 共享，provider 由 cleanup 保证确定性）。 */
  const mkUserData = (): string => mkdtempSync(path.join(tmpdir(), 'inkflow-e2e-rag-'));

  test('rag_unknown_shows_stale_banner：无指纹 → unknown 视同 stale（模型名/横幅/按钮）', async () => {
    const userDataDir = mkUserData();
    const { app, window, kernel } = await launchAppWithUserData(userDataDir);
    try {
      await window.evaluate(() => localStorage.clear());
      await window.reload();
      await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

      await createProjectViaUi(window, 'RAG 测试项目');

      // Node fetch 直调内核配置 embedding provider（201）；注册表首个 embedding 模型 = configured_fp.model_id
      const created = await ensureEmbeddingProvider(kernel, 'text-embedding-test');
      expect(created.status).toBe(201);

      await openRagStatus(window);
      await expect(window.getByTestId('rag-model-name')).toContainText('text-embedding-test');
      const banner = window.getByTestId('rag-stale-banner');
      await expect(banner).toBeVisible();
      await expect(banner).toContainText('无索引指纹');
      await expect(window.getByTestId('rag-reindex-btn')).toBeVisible();
    } finally {
      await app.close();
      try {
        rmSync(userDataDir, { recursive: true, force: true });
      } catch {
        // Windows 文件锁：临时目录清理失败不阻塞用例
      }
    }
  });

  test('rag_reindex_button_opens_confirm_dialog：点重新向量化 → 确认对话框出现（不点确认）', async () => {
    const userDataDir = mkUserData();
    const { app, window, kernel } = await launchAppWithUserData(userDataDir);
    try {
      await window.evaluate(() => localStorage.clear());
      await window.reload();
      await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

      await createProjectViaUi(window, 'RAG 测试项目');
      await ensureEmbeddingProvider(kernel, 'text-embedding-test');

      await openRagStatus(window);
      await window.getByTestId('rag-reindex-btn').click();
      const dlg = window.getByTestId('rag-confirm-dialog');
      await expect(dlg).toBeVisible();
      await expect(dlg).toContainText('将用当前模型全量重建向量索引');
      await expect(window.getByTestId('rag-confirm-ok')).toBeVisible();
      // 不点击确认：真实 reindex 会调 embedding API 失败（E2E 无真实端点）——本用例只锁 UI 链路
    } finally {
      await app.close();
      try {
        rmSync(userDataDir, { recursive: true, force: true });
      } catch {
        // Windows 文件锁：临时目录清理失败不阻塞用例
      }
    }
  });

  test('rag_no_embedding_shows_hint：无 embedding 可用（无 provider + 无本地 BGE 模型）→ 提示态', async () => {
    const userDataDir = mkUserData();
    const { app, window, kernel } = await launchAppWithUserData(userDataDir);
    try {
      await window.evaluate(() => localStorage.clear());
      await window.reload();
      await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

      await createProjectViaUi(window, 'RAG 测试项目');
      // 不配置任何 provider——清理遗留 e2e-rag* 保证「注册表无 embedding」成立（seed 4 个均无 embedding 模型）
      await cleanupRagTestProviders(kernel);

      await openRagStatus(window);
      // ⚠️ 父侧裁定（2026-08-12 E2E 实测）：本地 E2E 环境无 BGE 模型文件
      // （HuggingFaceBgeEmbeddings 构造失败）→ fallback 走 no_embedding 态——
      // 断言「未配置 embedding 模型」提示 + 无横幅无按钮（真实环境语义；
      // BGE fallback 两态需真实模型文件，由打包版/真机冒烟覆盖）
      await expect(window.getByTestId('rag-no-embedding')).toBeVisible();
      await expect(window.getByTestId('rag-model-name')).toHaveText('—');
      await expect(window.getByTestId('rag-stale-banner')).not.toBeVisible();
      await expect(window.getByTestId('rag-reindex-btn')).not.toBeVisible();
    } finally {
      await app.close();
      try {
        rmSync(userDataDir, { recursive: true, force: true });
      } catch {
        // Windows 文件锁：临时目录清理失败不阻塞用例
      }
    }
  });

  test('rag_stale_persists_across_restart：stale（unknown）跨重启保留', async () => {
    // 重启用例 = 二次 launch + 二次内核冷启动，放宽单用例超时（F32 M3 模式）
    test.setTimeout(240_000);
    const userDataDir = mkUserData();
    const name = `RAG 重启项目-${Date.now()}`;

    // ── 第一程：创建项目 → 配置 embedding provider → 设置页确认横幅（unknown 态）──
    const first = await launchAppWithUserData(userDataDir);
    try {
      await first.window.evaluate(() => localStorage.clear());
      await first.window.reload();
      await expect(first.window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

      await createProjectViaUi(first.window, name);
      await ensureEmbeddingProvider(first.kernel, 'text-embedding-test');

      await openRagStatus(first.window);
      await expect(first.window.getByTestId('rag-stale-banner')).toBeVisible();
    } finally {
      await first.app.close();
    }

    // ── 第二程：同 userData 重启 → 设置页横幅仍出现（unknown 态持久——未 reindex 过）──
    const second = await launchAppWithUserData(userDataDir);
    try {
      // currentProjectId 为内存态（无 persist）→ 项目页卡片重新选中本项目（#232）
      await gotoNav(second.window, '项目');
      await second.window.getByTestId('project-card').filter({ hasText: name }).click();
      await expect(second.window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });

      await openRagStatus(second.window);
      const banner = second.window.getByTestId('rag-stale-banner');
      await expect(banner).toBeVisible();
      // 后端权威（只读）：指纹缺失跨重启稳定 = stale true / reason unknown（UI 横幅同源）
      const list = await apiJson(second.kernel, 'GET', '/api/v1/projects');
      const project = ((list.data as { items: Array<{ id: string; name: string }> }).items ?? []).find(
        (p) => p.name === name,
      );
      expect(project).toBeTruthy();
      await expect
        .poll(
          async () => {
            const r = await apiJson(
              second.kernel,
              'GET',
              `/api/v1/projects/${(project as { id: string }).id}/vector/status`,
            );
            const status = r.data as { stale?: boolean; reason?: string | null };
            return { stale: status.stale, reason: status.reason };
          },
          { timeout: 10_000 },
        )
        .toEqual({ stale: true, reason: 'unknown' });
    } finally {
      await second.app.close();
    }

    try {
      rmSync(userDataDir, { recursive: true, force: true });
    } catch {
      // Windows 文件锁：临时目录清理失败不阻塞用例
    }
  });
});
// ─────────────────────────────────────────────────────────────────────────────
