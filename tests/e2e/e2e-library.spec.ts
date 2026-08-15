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
// ────────────────────────────────────────────────────────────────
// F43 P1（#284）：P0 遗留 E2E 契约补全（spec §5.7/§9.3 E2E-E1/E2/E3）——
// 编辑保存闭环 / 删除确认闭环 / 删除取消零请求
// ────────────────────────────────────────────────────────────────

test('设定库：编辑保存闭环（E2E-E1）——预填 → 改名称 → 保存 → PATCH 生效 + 已保存指示', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-编辑-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 预置 1 个角色（带 extra.role_rank='major' → 编辑对话框等级预填 → 保存按钮 enabled；
    // P1 等级必填 gate：无等级预置时编辑保存会被 disabled）
    const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/characters`, {
      method: 'POST',
      body: { name: '角色甲', personality: 'E2E 测试', extra: { role_rank: 'major', groups: [] } },
    });
    expect(res.status).toBe(201);
    const created = (await res.json()) as { id: string };
    const cid = created.id;

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-list')).toContainText('角色甲', { timeout: 15_000 });

    // 行编辑 → 对话框预填（名称 + 等级）
    await window.getByTestId(`lib-edit-${cid}`).click();
    const dialog = window.getByTestId('library-create-dialog');
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('library-create-name')).toHaveValue('角色甲');
    await expect(window.getByTestId('library-create-rank')).toContainText('重要配角');

    // 只改名称（不动等级）→ 保存
    const newName = '角色甲·改';
    await window.getByTestId('library-create-name').fill(newName);
    await window.getByTestId('library-create-save').click();

    // 保存指示「已保存」（2s 自动隐藏 → 时间敏感项先断言）
    await expect(window.getByTestId('lib-save-indicator')).toHaveText('已保存', { timeout: 15_000 });
    await expect(dialog).toBeHidden();
    // PATCH 生效：列表显示新名（reloadKey 重新拉取）
    await expect(window.getByTestId('library-list')).toContainText(newName, { timeout: 15_000 });
    // 内核落库：角色名已更新（PATCH 真实生效证据）
    await expect
      .poll(
        async () => {
          const r = await kernelFetch(kernel, `/api/v1/projects/${pid}/characters`);
          const data = (await r.json()) as { items: Array<{ id: string; name: string }> };
          return data.items.find((c) => c.id === cid)?.name;
        },
        { timeout: 15_000 },
      )
      .toBe(newName);
  } finally {
    await app.close();
  }
});

test('设定库：删除确认闭环（E2E-E2）——确认框 D11 文案 → 确认 → DELETE → 条目消失 + ok toast', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-删除-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/characters`, {
      method: 'POST',
      body: { name: '角色甲', personality: 'E2E 测试' },
    });
    expect(res.status).toBe(201);
    const created = (await res.json()) as { id: string };
    const cid = created.id;

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-list')).toContainText('角色甲', { timeout: 15_000 });

    // 行删除 → 二次确认框（D11 统一文案 + 标题含角色名）
    await window.getByTestId(`lib-delete-${cid}`).click();
    const confirm = window.getByTestId('lib-confirm-dialog');
    await expect(confirm).toBeVisible({ timeout: 15_000 });
    await expect(confirm).toContainText('删除角色甲？');
    await expect(confirm).toContainText('点击确认后立即移除，不可恢复');

    // 确认 → DELETE → ok toast（2s 自动消失 → 时间敏感项先断言）
    await window.getByTestId('lib-confirm-ok').click();
    await expect(window.getByRole('status')).toContainText('已保存', { timeout: 15_000 });
    await expect(confirm).toBeHidden();
    // 条目消失 → 角色列表空态
    await expect(window.getByTestId('library-tab-empty')).toBeVisible({ timeout: 15_000 });
    // 内核落库：DELETE 后列表不再返回该角色（软删过滤）
    await expect
      .poll(
        async () => {
          const r = await kernelFetch(kernel, `/api/v1/projects/${pid}/characters`);
          const data = (await r.json()) as { total: number };
          return data.total;
        },
        { timeout: 15_000 },
      )
      .toBe(0);
  } finally {
    await app.close();
  }
});

test('设定库：删除取消零请求（E2E-E3）——取消 → 关闭 + 条目仍在 + 内核无删除', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-取消-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/characters`, {
      method: 'POST',
      body: { name: '角色甲', personality: 'E2E 测试' },
    });
    expect(res.status).toBe(201);
    const created = (await res.json()) as { id: string };
    const cid = created.id;

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-list')).toContainText('角色甲', { timeout: 15_000 });

    // 行删除 → 确认框出现
    await window.getByTestId(`lib-delete-${cid}`).click();
    const confirm = window.getByTestId('lib-confirm-dialog');
    await expect(confirm).toBeVisible({ timeout: 15_000 });

    // 取消 → 对话框关闭
    await window.getByTestId('lib-confirm-cancel').click();
    await expect(confirm).toBeHidden();
    // 条目仍在（列表未变化，无刷新）
    await expect(window.getByTestId('library-list')).toContainText('角色甲');
    // 无 ok toast（取消不发任何请求）
    await expect(window.getByRole('status')).toHaveCount(0);
    // 内核零请求：角色仍存在
    const r = await kernelFetch(kernel, `/api/v1/projects/${pid}/characters`);
    const data = (await r.json()) as { items: Array<{ name: string }>; total: number };
    expect(data.total).toBe(1);
    expect(data.items[0].name).toBe('角色甲');
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// F43 P2（#284）：P2 遗留地图 E2E 契约补全（spec §9.8 E2E-M1/M2/M3）——
// 地图工作台入口+面包屑 / 一图多标记 / 三底图切换 pin 保留
// testid 契约以 P2 已交付源码为准（MapWorkbench.tsx / MapCanvas.tsx / PinDialog.tsx）
// ────────────────────────────────────────────────────────────────

/**
 * F43 P2 预置：唯一项目 → 世界观节点（JSON）→ 简图地图（⚠️ multipart Form，
 * kernelFetch 是 JSON-only，单独 fetch + FormData）→ 可选预置 pin（JSON）。
 * 返回 pid / rootLocationId（世界观节点 id）/ mapId / mapName 供断言使用。
 */
async function presetMapWithPin(
  window: Page,
  kernel: KernelInfo,
  name: string,
  opts: { withPin?: boolean } = {},
): Promise<{ pid: string; rootLocationId: string; mapId: string; mapName: string }> {
  await createProjectViaUi(window, name);
  const pid = await findProjectId(kernel, name);

  // 世界观节点（category='地图'）→ 返回 id 作 rootLocationId（地图挂载根地点）
  const wsRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/world-settings`, {
    method: 'POST',
    body: { name: `${name}-节点甲`, category: '地图' },
  });
  expect(wsRes.status).toBe(201);
  const ws = (await wsRes.json()) as { id: string };
  const rootLocationId = ws.id;

  // 地图（multipart：name + bg_source + root_location_id；bg_source=shape 无图也可建）
  const mapName = `${name}-地图`;
  const form = new FormData();
  form.append('name', mapName);
  form.append('bg_source', 'shape');
  form.append('root_location_id', rootLocationId);
  const mapRes = await fetch(`http://127.0.0.1:${kernel.port}/api/v1/projects/${pid}/maps`, {
    method: 'POST',
    headers: { 'X-InkFlow-Token': kernel.token },
    body: form,
  });
  expect(mapRes.status).toBe(201);
  const mapData = (await mapRes.json()) as { id: string };
  const mapId = mapData.id;

  if (opts.withPin) {
    const pinRes = await kernelFetch(kernel, `/api/v1/maps/${mapId}/pins`, {
      method: 'POST',
      body: { location_id: rootLocationId, x: 30, y: 40, label: '地点甲' },
    });
    expect(pinRes.status).toBe(201);
  }

  return { pid, rootLocationId, mapId, mapName };
}

/** F43 P2 进入地图工作台：设定库 → 世界观 tab（#389 停列表页）→ 点「地图视图」按钮 → 点地图节点徽标 → 画布出现 */
async function openMapWorkbench(window: Page, rootLocationId: string): Promise<void> {
  await gotoNav(window, '设定库');
  await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
  await window.getByRole('tab', { name: '世界观' }).click();
  await expect(window.getByTestId('library-list')).toBeVisible({ timeout: 15_000 });
  await window.getByTestId('map-view-entry').click();
  const badge = window.getByTestId(`world-map-badge-${rootLocationId}`);
  await expect(badge).toBeVisible({ timeout: 15_000 });
  await badge.click();
  await expect(window.getByTestId('map-canvas')).toBeVisible({ timeout: 15_000 });
}

/** 画布内 pin 计数（scope 到 map-canvas：页面级 map-pin-list / map-pin-edit-* 同前缀，不可整页计数） */
function canvasPins(window: Page) {
  return window.getByTestId('map-canvas').locator('[data-testid^="map-pin-"]');
}

test('设定库：地图工作台入口 + 面包屑（E2E-M1）——世界观 tab → 地图节点徽标 → 画布 + 面包屑含地图名', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-地图-M1-${Date.now()}`;
    const { rootLocationId, mapName } = await presetMapWithPin(window, kernel, name);

    await openMapWorkbench(window, rootLocationId);

    // 画布 + 底图工具栏（三态 chips：简图/图片/AI）
    await expect(window.getByTestId('map-bg-tools')).toBeVisible({ timeout: 15_000 });
    // 四级面包屑：设定库 / 世界观 / 地图视图 / {地图名}——当前级显示地图名
    await expect(window.getByTestId('map-breadcrumb')).toBeVisible();
    await expect(window.getByTestId('map-bc-current')).toContainText(mapName);
    // 无 pin → 空画布点击提示（预置无 pin）
    await expect(window.getByTestId('map-pin-add-hint')).toBeVisible();
  } finally {
    await app.close();
  }
});

test('设定库：一图多标记（E2E-M2）——点击画布 → pin-dialog → 保存 → 新 pin 出现 + 列表刷新', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-地图-M2-${Date.now()}`;
    const { rootLocationId, mapId } = await presetMapWithPin(window, kernel, name, { withPin: true });

    await openMapWorkbench(window, rootLocationId);

    // 预置 1 个 pin（画布叠加层渲染 map-pin-<id>）
    await expect(canvasPins(window)).toHaveCount(1, { timeout: 15_000 });

    // 点击画布任意位置 → PinDialog（名称/类型/保存五元素齐全）
    await window.getByTestId('map-canvas').click({ position: { x: 150, y: 120 } });
    const dialog = window.getByTestId('pin-dialog');
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(dialog.getByTestId('pin-name')).toBeVisible();

    // 填名称 → 保存（label 必填 1-50 gate；默认 type=location 不选关联 → 纯注释 pin）
    const newLabel = '新标记乙';
    await dialog.getByTestId('pin-name').fill(newLabel);
    await dialog.getByTestId('pin-save').click();

    // 时间敏感项最先断言：ok toast（~2s 自动消失）
    await expect(window.getByRole('status')).toContainText('已保存', { timeout: 15_000 });
    await expect(dialog).toBeHidden();
    // 新 pin 出现（画布计数 1→2）+ pin 列表刷新含新 label
    await expect(canvasPins(window)).toHaveCount(2, { timeout: 15_000 });
    await expect(window.getByTestId('map-pin-list')).toContainText(newLabel);
    // 内核落库：pin 列表 total=2（POST 真实发生证据）
    await expect
      .poll(
        async () => {
          const r = await kernelFetch(kernel, `/api/v1/maps/${mapId}/pins`);
          const data = (await r.json()) as { total: number };
          return data.total;
        },
        { timeout: 15_000 },
      )
      .toBe(2);
  } finally {
    await app.close();
  }
});

test('设定库：三底图切换 pin 保留（E2E-M3）——shape→image 切换 PATCH bg_source，pin 独立叠加层不消失', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-地图-M3-${Date.now()}`;
    const { rootLocationId, mapId } = await presetMapWithPin(window, kernel, name, { withPin: true });

    await openMapWorkbench(window, rootLocationId);

    // 预置 1 个 pin
    await expect(canvasPins(window)).toHaveCount(1, { timeout: 15_000 });

    // 简图（创建即 bg_source=shape）→ 画布仍显示 pin（数量不变）
    await window.getByTestId('map-bg-shape').click();
    await expect(canvasPins(window)).toHaveCount(1);

    // 切图片底图（无图 → 画布「无图片」占位；pin 独立叠加层仍保留）
    await window.getByTestId('map-bg-image').click();
    await expect(window.getByTestId('map-bg-image')).toHaveAttribute('aria-pressed', 'true', {
      timeout: 15_000,
    });
    await expect(canvasPins(window)).toHaveCount(1);

    // 内核落库：bg_source 已 PATCH 为 image（切换真实发生，非仅 UI 态）
    await expect
      .poll(
        async () => {
          const r = await kernelFetch(kernel, `/api/v1/maps/${mapId}`);
          const data = (await r.json()) as { bg_source: string };
          return data.bg_source;
        },
        { timeout: 15_000 },
      )
      .toBe('image');
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// F43 P1/P3/P4（#284）：0.8.0 设定库 P 块功能 E2E 补测（E2E-A1..A9）——
// 角色等级/标签创建与编辑 / 世界观树/分类筛选/跨项目复制 /
// 大纲三级树/章关联 / 时间线双序/一致性检查
// testid 契约以已交付源码为准（library.tsx + OutlineTree/TimelineView/CopyDialog/TagEditor），
// 参考 library-p1/p3/p4.test.tsx（R/O/T 序号契约）
