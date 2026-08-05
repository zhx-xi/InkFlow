/**
 * Electron 渲染层页面流程 E2E（#105 导航重构后契约：项目页 / 写作页 / 设定库 / 设置四页 + 侧边栏导航）
 *
 * 运行方式（与 electron-smoke.spec.ts 相同）：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e electron-pages
 *
 * 基建（复用 electron-smoke.spec.ts 模式）：
 * - _electron.launch + waitKernelInfo（__kernelInfo 注入轮询，窗口交互前必须先等内核就绪，否则 401）
 * - 真实内核 + 真实渲染：创建项目 = 真实 POST 落库；用例间用唯一书名 `E2E-<场景>-<ts>` 隔离数据
 * - 每个用例独立 launch app（workers=1，串行）
 *
 * #105 导航重构契约（spec §7.2/§7.4，Q1=A）：
 * - 顶栏三页导航 → 左侧可折叠侧边栏 AppNav（nav-item-<key> testid；写作/项目/设定库/设置 +
 *   Agent 快捷入口 Link 直达 /settings?cat=agent）；agents 页面已删除
 * - AgentChainCard 迁移至设置页 Agent 分类（settings-cat-agent）；AppearanceCard 行为并入
 *   设置页常规分类（主题 radio 三选）；AgentLlmCard 待 #106 挂载，本期不断言
 *
 * 元素契约来源：renderer 源码 testid（AppNav / projects.tsx / writing.tsx / library.tsx /
 * settings.tsx / NewProjectDialog / ProjectTree / EditorToolbar / ChapterEditor /
 * AgentChainCard）与 i18n/zh.ts 文案。
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

/** 等待内核就绪（轮询 __kernelInfo 注入，至多 20s） */
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

/** 带 token 的内核 API 请求（JSON body 自动序列化） */
async function kernelFetch(
  info: KernelInfo,
  pathname: string,
  init?: { method?: string; body?: unknown }
): Promise<Response> {
  return fetch(`http://127.0.0.1:${info.port}${pathname}`, {
    method: init?.method ?? 'GET',
    headers: {
      'X-InkFlow-Token': info.token,
      'Content-Type': 'application/json',
    },
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
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

/** 从内核项目列表按书名查 id（断言存在） */
async function findProjectId(kernel: KernelInfo, name: string): Promise<string> {
  const res = await kernelFetch(kernel, '/api/v1/projects');
  expect(res.ok).toBe(true);
  const data = (await res.json()) as { items: Array<{ id: string; name: string }> };
  const project = data.items.find((p) => p.name === name);
  expect(project, `项目「${name}」应已创建并持久化`).toBeTruthy();
  return project!.id;
}

test.describe.configure({ timeout: 120_000 });

// ────────────────────────────────────────────────────────────────
// 1. 项目页：新建对话框 → 创建项目 → 项目卡片出现（含书名）
// ────────────────────────────────────────────────────────────────
test('项目页：创建项目 → 项目卡片出现（含书名，真实落库）', async () => {
  const { app, window } = await launchApp();
  try {
    const name = `E2E-项目-${Date.now()}`;
    await createProjectViaUi(window, name);

    // 回项目页断言卡片（filter 精确匹配书名，避免历史数据干扰）
    await gotoNav(window, '项目');
    const card = window.getByTestId('project-card').filter({ hasText: name });
    await expect(card).toHaveCount(1);
    await expect(card).toContainText('玄幻'); // 默认题材
    await expect(card).toContainText(/800,?000/); // 默认目标字数
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 2. 项目页 → 写作页导航：创建自动跳转 + 侧边栏往返闭环
// ────────────────────────────────────────────────────────────────
test('项目→写作页导航：创建后自动跳转 + 侧边栏「项目/写作」往返', async () => {
  const { app, window } = await launchApp();
  try {
    const name = `E2E-导航-${Date.now()}`;
    await createProjectViaUi(window, name);

    // 创建成功 → 自动进入写作页（契约：navigate('/writing')）
    expect(await window.evaluate(() => location.hash)).toContain('/writing');
    await expect(window.getByTestId('project-tree')).toBeVisible();

    // 侧边栏「项目」→ 回项目页
    await gotoNav(window, '项目');
    expect(await window.evaluate(() => location.hash)).toContain('/projects');
    await expect(window.getByTestId('new-project-btn')).toBeVisible();

    // 侧边栏「写作」→ 再进写作页（回退首个项目，树正常渲染）
    await gotoNav(window, '写作');
    expect(await window.evaluate(() => location.hash)).toContain('/writing');
    await expect(window.getByTestId('project-tree')).toBeVisible();
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 3. 写作页：卷/章树渲染 + 点章节 → 编辑器显示正文
// ────────────────────────────────────────────────────────────────
test('写作页：卷/章树渲染（tree-volume/tree-chapter）→ 选章节 → 编辑器正文', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-树-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 内核 API 预置：1 卷 + 2 章（带正文）——模拟已有内容的项目
    const volRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/volumes`, {
      method: 'POST',
      body: { title: '第一卷 风起' },
    });
    expect(volRes.status).toBe(201);
    const vol = (await volRes.json()) as { id: string };
    const seedChapters: Array<{ title: string; content: string }> = [
      { title: '第一章 初见', content: '第一章正文内容。' },
      { title: '第二章 夜谈', content: '第二章正文内容。' },
    ];
    for (const ch of seedChapters) {
      const r = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
        method: 'POST',
        body: { title: ch.title, volume_id: vol.id, content: ch.content },
      });
      expect(r.status).toBe(201);
    }

    // 重挂载写作页触发 loadChapterTree（加载 API 预置的卷/章）
    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible();

    // 卷节点渲染
    const tree = window.getByTestId('project-tree');
    await expect(tree.getByTestId('tree-volume')).toHaveCount(1);
    await expect(tree.getByTestId('tree-volume')).toContainText('第一卷 风起');

    // 点章节 → 成为当前章（data-testid=tree-chapter + data-current=true）
    await tree.getByRole('button', { name: /第一章 初见/ }).click();
    const current = tree.getByTestId('tree-chapter');
    await expect(current).toHaveCount(1);
    await expect(current).toHaveAttribute('data-current', 'true');
    await expect(current).toContainText('第一章 初见');

    // 编辑器显示选中章节正文（selectChapter 拉取 GET /chapters/{id}）
    await expect(window.getByTestId('chapter-editor')).toHaveValue('第一章正文内容。');
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 4. 写作页：工具栏保存 → 正文持久化到内核
// ────────────────────────────────────────────────────────────────
test('写作页：新建章节 → 输入正文 → 工具栏保存 → 内核持久化', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-保存-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // UI 新建章节（底部「+ 新建章节」→ 输入标题 → Enter；创建后自动成为当前章）
    await window.getByRole('button', { name: /新建章节/ }).click();
    // exact: 编辑器 textarea 的 placeholder 也含「新建章节」子串，必须精确匹配树底部输入框
    const titleInput = window.getByPlaceholder('新建章节', { exact: true });
    await titleInput.fill('保存测试章节');
    await titleInput.press('Enter');
    await expect(window.getByTestId('tree-chapter')).toContainText('保存测试章节');

    // 编辑器输入正文
    const editor = window.getByTestId('chapter-editor');
    const text = `E2E 保存正文 ${Date.now()}`;
    await editor.fill(text);

    // 工具栏保存
    await window.getByTestId('toolbar-save').click();

    // 轮询内核：正文已持久化（PATCH /chapters/{id} 异步完成）
    await expect
      .poll(
        async () => {
          const listRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`);
          const list = (await listRes.json()) as {
            items: Array<{ id: string; title: string }>;
          };
          const ch = list.items.find((c) => c.title === '保存测试章节');
          if (!ch) return null;
          const detailRes = await kernelFetch(kernel, `/api/v1/chapters/${ch.id}`);
          return ((await detailRes.json()) as { content: string }).content;
        },
        { timeout: 10_000 }
      )
      .toBe(text);
  } finally {
    await app.close();
  }
});

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
