/**
 * F23 数据面变更推送 —— 跨界面可见性 E2E（spec §15.12.1 M8，issue #1089 批 A4）
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build           # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build   # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-push-visibility
 *
 * 覆盖场景：
 * - S1（主场景 / #973 爆点复刻，spec §15.7.3 判据 2）：GUI 停留地图视图 → 外部（内核 HTTP
 *   API，**不是**页面按钮）建图 → 不切页/不刷新 → 地图自动出现。GUI 侧零交互，故出现只能
 *   来自推送流（事件 → debounce 300ms → reloadKey bump → 既有 effect 全量 refetch）。
 * - S2（断连兜底，spec §15.5.4 / §15.7.3 判据 3）：SSE 首连失败（route abort）→ 断连窗口内
 *   外部建图（事件无接收者，且无 Last-Event-ID 补发，D15-7）→ 放行重连 → 兜底全量 refetch
 *   使新图出现。
 * - S3（#989 复刻，spec §15.7.1）：GUI 停留模板页 → 外部经内核 HTTP API 挂引用 → 点删除 →
 *   风险确认读到最新 used_by（非空），不因陈旧快照漏列引用项目。
 *
 * 基建（照抄 e2e-library.spec.ts / e2e-settings-templates.spec.ts 模式，本文件自包含不 import
 * 其他 spec）：
 * - _electron.launch + waitKernelInfo（__kernelInfo 注入轮询，窗口交互前必须先等内核就绪，否则 401）
 * - 真实内核 + 真实渲染；用例间用唯一名（时间戳）隔离数据（内核 DB 为持久文件，跨用例残留）
 * - 每个用例独立 launch app（workers=1，串行）+ try/finally app.close()
 * - 外部写入一律直连内核 REST API 且只带 X-InkFlow-Token（不携带 X-Inkflow-Source）→
 *   后端 source=unknown（非 gui）→ 不会被前端 self-originated 过滤丢掉（spec §15.2.4）
 *
 * 确定性约定：断言一律用 Playwright 自动重试的 expect / expect.poll（禁裸 sleep 碰运气）；
 * 推送链路（事件 + debounce 300ms + refetch）给 20-30s 宽时限。
 */
import path from 'node:path';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Locator,
  type Page,
} from '@playwright/test';
import { ensureModelConfigured } from './e2e-model-ready';

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
async function readKernelInfo(app: ElectronApplication): Promise<KernelInfo | undefined> {
  // 根治（#1041）：evaluate 返回 JSON 字符串快照——序列化在主进程内同步完成，
  // 跨边界只传原始 string，消除 object round-trip 的 GC 竞态（#451/#455 签名族）。
  try {
    const raw = await app.evaluate(() => {
      const info = (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo;
      return info ? JSON.stringify(info) : null;
    });
    return raw ? (JSON.parse(raw) as KernelInfo) : undefined;
  } catch {
    return undefined;
  }
}

/** 等待内核就绪（轮询 __kernelInfo 注入；CI 冷启动 chromadb+内核 >20s；#1077 对齐主进程 90s×2 重启预算，默认 240s） */
async function waitKernelInfo(app: ElectronApplication, timeoutMs = 240_000): Promise<KernelInfo> {
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
  // F60 #934：隔离数据目录 = 全新安装态 → 预置「已配置模型」则门控放行
  await ensureModelConfigured(kernel);
  return { app, window, kernel };
}

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置；NavLink 与 Agent 快捷 Link 均为 role=link） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

/** 通过 UI 创建项目（new-project-btn → 对话框填书名/标签 → 创建 → 跳写作页） */
async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  await window.getByLabel('书名').fill(name);
  // #595 契约：创建须 ≥1 个题材/标签（Radix option 渲染于 portal，用 window 级查询）
  await window.getByTestId('tags-select').click();
  await window.getByRole('option', { name: '玄幻' }).click();
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

/** 带 token 的内核 API 请求（JSON body 自动序列化） */
async function kernelFetch(
  kernel: KernelInfo,
  pathname: string,
  init?: { method?: string; body?: unknown },
): Promise<Response> {
  return fetch(`http://127.0.0.1:${kernel.port}${pathname}`, {
    method: init?.method ?? 'GET',
    headers: {
      'X-InkFlow-Token': kernel.token,
      'Content-Type': 'application/json',
    },
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
}

/** 内核 API JSON 请求 + 状态码硬校验（status 不符即抛，防「构造失败静默」） */
async function kernelJson<T>(
  kernel: KernelInfo,
  pathname: string,
  init?: { method?: string; body?: unknown },
): Promise<T> {
  const res = await kernelFetch(kernel, pathname, init);
  expect(res.status, `内核 API ${init?.method ?? 'GET'} ${pathname}`).toBeLessThan(300);
  return (await res.json()) as T;
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

/** 外部写入：内核 API 建世界观根节点（category='' → 地理类，工作台可挂图），返回节点 id */
async function createWorldNode(kernel: KernelInfo, pid: string, name: string): Promise<string> {
  const node = await kernelJson<{ id: string }>(kernel, `/api/v1/projects/${pid}/world-settings`, {
    method: 'POST',
    body: { name, category: '' },
  });
  return node.id;
}

/**
 * 外部写入：内核 API 建地图（⚠️ multipart Form，kernelFetch 是 JSON-only，单独 fetch + FormData），
 * 返回地图 id。请求不带 X-Inkflow-Source → 后端 source=unknown（外部发起方）。
 */
async function createMapExternal(
  kernel: KernelInfo,
  pid: string,
  name: string,
  rootLocationId: string,
): Promise<string> {
  const form = new FormData();
  form.append('name', name);
  form.append('bg_source', 'shape'); // shape 无图也可建（对齐既有 presetMapWithPin）
  form.append('root_location_id', rootLocationId);
  const res = await fetch(`http://127.0.0.1:${kernel.port}/api/v1/projects/${pid}/maps`, {
    method: 'POST',
    headers: { 'X-InkFlow-Token': kernel.token },
    body: form,
  });
  expect(res.status, `外部建图 POST /projects/${pid}/maps`).toBe(201);
  const data = (await res.json()) as { id: string };
  return data.id;
}

/** 设定库 → 世界观 tab（含预置世界观节点）→ 点「地图视图」进工作台左栏地图目录树（不选具体图） */
async function enterMapWorkbench(window: Page): Promise<void> {
  await gotoNav(window, '设定库');
  await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
  await window.getByRole('tab', { name: '世界观' }).click();
  await expect(window.getByTestId('library-list')).toBeVisible({ timeout: 15_000 });
  await window.getByTestId('map-view-entry').click();
  await expect(window.getByTestId('map-workbench')).toBeVisible({ timeout: 15_000 });
}

/** 进入设置页模板分类（侧边栏「设置」→ 设置导航「模板」→ URL cat=templates） */
async function gotoTemplatesCat(window: Page): Promise<void> {
  await gotoNav(window, '设置');
  await window.getByTestId('settings-cat-templates').click();
  expect(await window.evaluate(() => location.hash)).toContain('cat=templates');
}

/** 通过 UI 新建模板（add-btn → 对话框填名 → 保存），返回新卡片定位器（已可见） */
async function createTemplateViaUi(window: Page, name: string): Promise<Locator> {
  await window.getByTestId('template-add-btn').click();
  const dialog = window.getByTestId('template-dialog');
  await expect(dialog).toBeVisible();
  await window.getByTestId('template-name-input').fill(name);
  await window.getByTestId('template-save').click();
  await expect(dialog).not.toBeVisible({ timeout: 15_000 });
  const card = window.locator('[data-testid^="template-card-"]').filter({ hasText: name });
  await expect(card).toBeVisible({ timeout: 15_000 });
  return card;
}

/** 从模板卡片 data-testid 提取模板 id（剥离 template-card- 前缀） */
async function extractTemplateId(card: Locator): Promise<string> {
  const testid = await card.getAttribute('data-testid');
  if (!testid) {
    throw new Error('模板卡片缺少 data-testid');
  }
  return testid.replace('template-card-', '');
}

/**
 * 外部写入：内核 API 建项目 + 挂模板引用（PATCH project.config.template_id）。
 * 走 API（而非 UI）是为了让 GUI **停留**在模板页不重挂载——UI 建项目会跳走 /writing。
 * 返回被引用项目名（供风险确认文案断言）。
 */
async function referenceNewProjectToTemplate(
  kernel: KernelInfo,
  projectName: string,
  templateId: string,
): Promise<void> {
  const created = await kernelJson<{ id: string }>(kernel, '/api/v1/projects', {
    method: 'POST',
    body: { name: projectName, tags: ['玄幻'] },
  });
  // config 整体替换语义 → 显式构造仅含 template_id 的 config（新项目无其他配置面）
  await kernelJson<{ id: string }>(kernel, `/api/v1/projects/${created.id}`, {
    method: 'PATCH',
    body: { config: { template_id: String(templateId) } },
  });
  // 内核数据面确认：模板详情 used_by 已含该项目（引用确实落库，对齐 #985 诊断约定）
  const detail = await kernelJson<{ used_by?: Array<{ name: string }> }>(
    kernel,
    `/api/v1/agent-templates/${templateId}`,
  );
  expect((detail.used_by ?? []).map((u) => u.name)).toContain(projectName);
}

test.describe.configure({ timeout: 360_000 });

// ────────────────────────────────────────────────────────────────
// S1（主场景）：推送可见性——GUI 停留不切页，外部建图自动出现（#973 复刻）
// ────────────────────────────────────────────────────────────────

test('推送可见性 S1：GUI 停留地图视图 → 外部 HTTP 建图 → 不切页/不刷新自动出现（#973 复刻）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-PUSH-Map-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    const rootLocationId = await createWorldNode(kernel, pid, `${name}-根`);

    // 进入并停留「地图视图」：此后 GUI 不再有任何交互
    await enterMapWorkbench(window);

    // 基线：外部建图前该世界观节点无挂图徽标（目录树无图）
    await expect(window.getByTestId(`world-map-badge-${rootLocationId}`)).toHaveCount(0);

    // 外部写入：内核 HTTP API 建图（不经页面按钮 → 不产生 self-originated 事件）
    const mapName = `${name}-外部图`;
    const mapId = await createMapExternal(kernel, pid, mapName, rootLocationId);

    // 关键断言：GUI 零交互（不点 / 不切页 / 不刷新）——纯等待
    // 推送链路：事件 → debounce 300ms → reloadKey bump → maps effect 全量 refetch
    await expect(window.getByTestId(`world-map-badge-${rootLocationId}`)).toHaveCount(1, {
      timeout: 20_000,
    });
    await expect(window.getByTestId(`map-tree-node-${mapId}`)).toContainText(mapName, {
      timeout: 20_000,
    });
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// S2（断连兜底）：SSE 断连 → 重连 → 兜底全量 refetch 使新图出现（spec §15.5.4）
// ────────────────────────────────────────────────────────────────

test('推送可见性 S2：SSE 断连重连 → 兜底全量 refetch 使外部新图出现（§15.5.4）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-PUSH-Reconnect-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    const rootLocationId = await createWorldNode(kernel, pid, `${name}-根`);

    // 构造断连：拦截长驻订阅请求并 abort（首连失败 → 客户端进入指数退避重试循环）。
    // 本构造不碰内核，只断前端订阅流——等价「SSE 断连」对 GUI 的可观测效果。
    let blockSse = true;
    await window.route('**/api/v1/events/stream', async (route) => {
      if (blockSse) {
        await route.abort();
      } else {
        await route.continue();
      }
    });

    // 进地图视图 → 页面挂载 → 发起 SSE 订阅 → 被 abort（无订阅者接收事件）
    await enterMapWorkbench(window);

    // 断连窗口内外部建图：事件无接收者，且客户端无 Last-Event-ID 补发（D15-7）→ 永久丢失
    const mapName = `${name}-断连图`;
    const mapId = await createMapExternal(kernel, pid, mapName, rootLocationId);

    // 断连期间 GUI 零交互 → 新图不可见（证明后续出现只可能来自重连兜底，而非事件投递）
    await expect(window.getByTestId(`map-tree-node-${mapId}`)).toHaveCount(0);

    // 放行订阅流 → 客户端退避重试成功（第 2 次及以后尝试 = 重连）→ onReconnect → 兜底全量 refetch
    blockSse = false;
    await expect(window.getByTestId(`map-tree-node-${mapId}`)).toContainText(mapName, {
      timeout: 30_000,
    });
    await expect(window.getByTestId(`world-map-badge-${rootLocationId}`)).toHaveCount(1);
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// S3（#989 复刻）：GUI 停留模板页，外部挂引用 → 删除风险确认读到最新 used_by
// ────────────────────────────────────────────────────────────────

test('推送可见性 S3：GUI 停留模板页 → 外部挂引用 → 删除风险确认读到最新 used_by（#989 复刻）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    // 清空持久化 UI 偏好（inkflow.ui）并重载：保证中文文案确定性（对齐既有模板 spec）
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    // UI 建唯一模板 → 定位卡片提取 id
    await gotoTemplatesCat(window);
    const tplName = `E2E-PUSH-Tpl-${Date.now()}`;
    const tplCard = await createTemplateViaUi(window, tplName);
    const tplId = await extractTemplateId(tplCard);

    // 全程停留模板页：外部（内核 HTTP API）建项目并挂上该模板引用
    const projectName = `E2E-PUSH-Ref-${Date.now()}`;
    await referenceNewProjectToTemplate(kernel, projectName, tplId);

    // 点删除 → 风险确认必须读到最新 used_by（非空）——即 #989「最后一道防线」
    await window.getByTestId(`template-delete-${tplId}`).click();
    const confirm = window.getByTestId('template-confirm-dialog');
    await expect(confirm).toBeVisible({ timeout: 15_000 });
    await expect(confirm).toContainText('正在被 1 个项目使用');
    await expect(confirm).toContainText(projectName);

    // 取消收尾（不真删，保持用例无副作用）
    await window.getByTestId('template-confirm-cancel').click();
    await expect(confirm).not.toBeVisible();
    await expect(tplCard).toBeVisible();
  } finally {
    await app.close();
  }
});
