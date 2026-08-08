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

// ────────────────────────────────────────────────────────────────
// 基建：内核 API 直连（复制自 e2e-writing.spec.ts，spec 自包含不 import）
// ────────────────────────────────────────────────────────────────

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

/** 从内核项目列表按书名查 id（断言存在） */
async function findProjectId(kernel: KernelInfo, name: string): Promise<string> {
  const res = await kernelFetch(kernel, '/api/v1/projects');
  expect(res.ok).toBe(true);
  const data = (await res.json()) as { items: Array<{ id: string; name: string }> };
  const project = data.items.find((p) => p.name === name);
  expect(project, `项目「${name}」应已创建并持久化`).toBeTruthy();
  return project!.id;
}

// ────────────────────────────────────────────────────────────────
// 设定库页 E2E（Issue #140：空态 / 项目选择器 / 分类 tab / 列表 / 空态 CTA / 失败重试）
// ────────────────────────────────────────────────────────────────

test('设定库：无当前项目 → 空态 + 「前往项目页」CTA → 跳转 /projects', async () => {
  const { app, window } = await launchApp();
  try {
    // 新启动 app 无当前项目（project store 不持久化）→ 直接进设定库即为空态
    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('library-empty')).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('library-empty')).toContainText('选择或新建项目开始构建设定');
    await expect(window.getByTestId('library-go-projects')).toBeVisible();
    await window.getByTestId('library-go-projects').click();
    await expect
      .poll(async () => window.evaluate(() => location.hash), { timeout: 15_000 })
      .toContain('/projects');
  } finally {
    await app.close();
  }
});

test('设定库：项目选择器 → 面包屑显示「设定库 · 项目名 / 分类」', async () => {
  const { app, window } = await launchApp();
  try {
    const name = `E2E-选择器-${Date.now()}`;
    await createProjectViaUi(window, name);
    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });

    // Radix Select：点击 trigger → 选项渲染于 portal（role=option 仅展开时存在）
    const trigger = window.getByTestId('library-project-select');
    await expect(trigger).toBeVisible();
    await trigger.click();
    await window.getByRole('option', { name }).click();

    const crumb = window.getByTestId('library-breadcrumb');
    await expect(crumb).toContainText('设定库', { timeout: 15_000 });
    await expect(crumb).toContainText(name);
  } finally {
    await app.close();
  }
});

test('设定库：六分类 tab 切换 → URL cat 参数 + aria-selected + 面包屑分类名', async () => {
  const { app, window } = await launchApp();
  try {
    const name = `E2E-Tabs-${Date.now()}`;
    await createProjectViaUi(window, name);
    await gotoNav(window, '设定库');

    const tabs = window.getByTestId('library-tabs');
    await expect(tabs).toBeVisible({ timeout: 15_000 });
    await expect(tabs.getByRole('tab')).toHaveCount(6);
    // 默认激活「角色」
    await expect(tabs.getByRole('tab', { name: '角色' })).toHaveAttribute('aria-selected', 'true');

    for (const [tabName, catKey] of [
      ['世界观', 'world'],
      ['时间线', 'timeline'],
      ['伏笔', 'foreshadow'],
    ] as const) {
      await tabs.getByRole('tab', { name: tabName }).click();
      await expect
        .poll(async () => window.evaluate(() => location.hash), { timeout: 15_000 })
        .toContain(`cat=${catKey}`);
      await expect(tabs.getByRole('tab', { name: tabName })).toHaveAttribute('aria-selected', 'true');
      await expect(window.getByTestId('library-breadcrumb')).toContainText(tabName);
    }
  } finally {
    await app.close();
  }
});

test('设定库：内核预置角色 → 角色分类列表渲染条目', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-列表-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 内核 API 预置 1 个角色（POST /characters；body 契约见 CharacterCreateBody）
    const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/characters`, {
      method: 'POST',
      body: { name: '角色甲', personality: 'E2E 测试' },
    });
    expect(res.status).toBe(201);

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
    // 默认角色 tab → 列表渲染角色名（列表项显示 title ?? name）
    await expect(window.getByTestId('library-list')).toContainText('角色甲', { timeout: 15_000 });
  } finally {
    await app.close();
  }
});

test('设定库：大纲分类无数据 → 空态引导 + 「去创建」→ 打开创建对话框（#196，不跳 /writing）', async () => {
  const { app, window } = await launchApp();
  try {
    const name = `E2E-空态-${Date.now()}`;
    await createProjectViaUi(window, name);
    await gotoNav(window, '设定库');

    const tabs = window.getByTestId('library-tabs');
    await expect(tabs).toBeVisible({ timeout: 15_000 });
    // 大纲分类无预置数据 → 分类空态
    // ⚠️ 不用「知识库 RAG」分类：RAG 未配置 embedding 模型时 get_vector_store() 抛
    //    RAGUnavailableError → 500 → 页面显示加载失败（正确产品行为），非空态
    await tabs.getByRole('tab', { name: '大纲' }).click();
    await expect(window.getByTestId('library-tab-empty')).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('library-tab-empty-cta')).toBeVisible();
    await window.getByTestId('library-tab-empty-cta').click();
    // #196（2026-08-09）：非 RAG 分类空态 CTA 打开分类创建对话框，不跳 /writing
    await expect(window.getByTestId('library-create-dialog')).toBeVisible({ timeout: 15_000 });
    // 大纲分类对话框字段：名称（必填）+ 描述
    await expect(window.getByLabel('名称')).toBeVisible();
    await expect(window.getByLabel('描述')).toBeVisible();
    // 取消关闭（关闭路径仅取消/Esc/成功，#195）
    await window.getByRole('button', { name: '取消' }).click();
    await expect(window.getByTestId('library-create-dialog')).toBeHidden();
  } finally {
    await app.close();
  }
});

test('设定库：分类加载失败 → error + 重试 → 列表恢复', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-重试-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/characters`, {
      method: 'POST',
      body: { name: '角色甲', personality: 'E2E 测试' },
    });
    expect(res.status).toBe(201);

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-list')).toContainText('角色甲', { timeout: 15_000 });

    // 拦截角色端点使其失败（渲染进程 window.fetch 可被 page.route 拦截）
    await window.route('**/api/v1/projects/*/characters', (route) => route.abort());
    const tabs = window.getByTestId('library-tabs');
    // 切换 tab 再切回角色 → 重新拉取角色端点 → 失败 → error 态
    await tabs.getByRole('tab', { name: '世界观' }).click();
    await tabs.getByRole('tab', { name: '角色' }).click();
    await expect(window.getByTestId('library-error')).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('library-retry')).toBeVisible();

    // 取消拦截 → 点重试 → 列表恢复
    await window.unroute('**/api/v1/projects/*/characters');
    await window.getByTestId('library-retry').click();
    await expect(window.getByTestId('library-error')).not.toBeVisible();
    await expect(window.getByTestId('library-list')).toContainText('角色甲', { timeout: 15_000 });
  } finally {
    await app.close();
  }
});
