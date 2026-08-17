/**
 * 设置页「模板」分类域 E2E（#107 模板管理，spec §9.2.5 / §9.3 / §9.5）
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-settings-templates
 *
 * 基建（复制自 e2e-settings.spec.ts，本文件自包含不 import 其他 spec）：
 * - _electron.launch + waitKernelInfo（__kernelInfo 注入轮询，窗口交互前必须先等内核就绪，否则 401）
 * - 真实内核 + 真实渲染；用例开头清空持久化 UI 偏好（inkflow.ui）并重载，保证中文文案确定性
 * - 每个用例独立 launch app（workers=1，串行）+ try/finally app.close()
 *
 * 数据隔离约定（内核 DB 为持久文件 frontend/inkflow.db，跨用例残留）：
 * - 后端无模板 seed（新库空列表），但 DB 持久 → 每个用例自建唯一名模板
 *   （E2E-TPL-<场景>-${Date.now()}）；定位卡片一律
 *   locator('[data-testid^="template-card-"]').filter({ hasText: 名称 })（禁硬编码 id），
 *   卡片 id 从 data-testid 提取（剥离 template-card- 前缀）
 * - 项目名同样唯一（E2E-TPL-Ref-${Date.now()}）；「被引用」关系经内核 API 构造：
 *   PATCH /api/v1/projects/{id} body {config: {...原config, template_id: String(模板id)}}
 *   （config 整体替换，须先 GET 原 config 合并）
 *
 * testid 契约（#107 实测）：template-add-btn / template-list / template-card-<id> /
 * template-usedby-<id> / template-default-badge-<id> / template-edit-<id> /
 * template-set-default-<id> / template-delete-<id>；template-dialog（role=dialog，
 * aria-label=新建模板|编辑模板）/ template-name-input / template-description-input /
 * template-save / template-cancel；template-confirm-dialog / template-confirm-ok /
 * template-confirm-cancel
 *
 * ⚠️ 被引用删除的风险确认文案（tpl.confirm.deleteReferenced）依赖模板列表项 used_by
 * （前端契约：列表即完整实体，见 stores/templates.ts）；当前后端列表端点不含 used_by、
 * 仅详情端点含——若用例 4/5 的「正在被 1 个项目使用」断言失败，根因在此（后端列表补
 * used_by 或前端补拉详情），非测试写法问题。
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

/** 等待内核就绪（轮询 __kernelInfo 注入；CI 冷启动 chromadb+内核 >20s，默认 60s） */
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

/** 通过 UI 创建项目（复制自 e2e-settings.spec.ts：new-project-btn → 对话框填书名 → 创建 → 自动跳写作页） */
async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  // getByLabel 通过关联 label / aria-label 查找（dialog 内唯一）
  await window.getByLabel('书名').fill(name);
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

/** 直连内核 REST API（数据准备用；204 空响应返回 undefined，否则解析 JSON） */
async function fetchKernel(
  kernel: KernelInfo,
  path: string,
  init?: { method?: string; body?: unknown }
): Promise<unknown> {
  const res = await fetch(`http://127.0.0.1:${kernel.port}${path}`, {
    method: init?.method ?? 'GET',
    headers: {
      'X-InkFlow-Token': kernel.token,
      'Content-Type': 'application/json',
    },
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  if (res.status === 204) {
    return undefined;
  }
  return (await res.json()) as unknown;
}

/** 进入设置页模板分类（侧边栏「设置」→ 设置导航「模板」→ URL cat=templates） */
async function gotoTemplatesCat(window: Page): Promise<void> {
  await gotoNav(window, '设置');
  await window.getByTestId('settings-cat-templates').click();
  expect(await window.evaluate(() => location.hash)).toContain('cat=templates');
}

/** 通过 UI 新建模板（add-btn → 对话框填名/描述 → 保存），返回新卡片定位器（已可见） */
async function createTemplateViaUi(window: Page, name: string, description = ''): Promise<Locator> {
  await window.getByTestId('template-add-btn').click();
  const dialog = window.getByTestId('template-dialog');
  await expect(dialog).toBeVisible();
  await window.getByTestId('template-name-input').fill(name);
  if (description) {
    await window.getByTestId('template-description-input').fill(description);
  }
  await window.getByTestId('template-save').click();
  await expect(dialog).not.toBeVisible();
  const card = window.locator('[data-testid^="template-card-"]').filter({ hasText: name });
  await expect(card).toBeVisible();
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

/** 内核 API 构造「项目引用模板」：GET /api/v1/projects 按名找项目 → PATCH config.template_id */
async function referenceProjectToTemplate(
  kernel: KernelInfo,
  projectName: string,
  templateId: string
): Promise<void> {
  const projects = (await fetchKernel(kernel, '/api/v1/projects')) as {
    items: Array<{ id: string; name: string; config: Record<string, unknown> }>;
  };
  const project = projects.items.find((p) => p.name === projectName);
  expect(project).toBeTruthy();
  await fetchKernel(kernel, `/api/v1/projects/${project!.id}`, {
    method: 'PATCH',
    body: { config: { ...project!.config, template_id: String(templateId) } },
  });
}

test.describe.configure({ timeout: 120_000 });

// ────────────────────────────────────────────────────────────────
// #107 模板管理域 E2E：新建 / 编辑 / 设为默认 / 删除（被引用确认 / 取消）
// ────────────────────────────────────────────────────────────────

test('模板分类：新建模板全流程（对话框 → 保存 → 新卡片含描述且无默认徽标）', async () => {
  const { app, window } = await launchApp();
  try {
    // 清空持久化 UI 偏好（inkflow.ui）并重载：保证中文文案确定性
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    await gotoTemplatesCat(window);

    // 列表容器 + 新建按钮可见（无 seed 时列表可能为空，容器恒渲染）
    // 空列表（CI 全新 DB）时容器高度 0 → toBeVisible 误判 hidden；attached 表达「列表容器已渲染」，内容由后续 add-btn 交互与卡片断言覆盖
    await expect(window.getByTestId('template-list')).toBeAttached();
    await expect(window.getByTestId('template-add-btn')).toBeVisible();

    // 新建对话框：role=dialog + aria-label=新建模板 + 名称输入框初始为空
    await window.getByTestId('template-add-btn').click();
    const dialog = window.getByTestId('template-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute('role', 'dialog');
    await expect(dialog).toHaveAttribute('aria-label', '新建模板');
    await expect(window.getByTestId('template-name-input')).toHaveValue('');

    // 填写唯一名 + 描述 → 保存 → 对话框关闭
    const name = `E2E-TPL-Create-${Date.now()}`;
    await window.getByTestId('template-name-input').fill(name);
    await window.getByTestId('template-description-input').fill('E2E 描述');
    await window.getByTestId('template-save').click();
    await expect(dialog).not.toBeVisible();

    // 新卡片可见 + 含描述 + 卡内无默认徽标（新模板 is_default=false）
    const card = window.locator('[data-testid^="template-card-"]').filter({ hasText: name });
    await expect(card).toBeVisible();
    await expect(card).toContainText('E2E 描述');
    await expect(card.locator('[data-testid^="template-default-badge-"]')).toHaveCount(0);
  } finally {
    await app.close();
  }
});

test('模板分类：编辑无引用模板直接保存（名称回显 + 不弹风险确认 + 改名生效）', async () => {
  const { app, window } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    await gotoTemplatesCat(window);

    // UI 建唯一模板 → 定位卡片提取 id（禁硬编码 id）
    const name = `E2E-TPL-Edit-${Date.now()}`;
    const card = await createTemplateViaUi(window, name);
    const cardId = await extractTemplateId(card);

    // 编辑对话框：aria-label=编辑模板 + 名称回显原名
    await window.getByTestId(`template-edit-${cardId}`).click();
    const dialog = window.getByTestId('template-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute('aria-label', '编辑模板');
    await expect(window.getByTestId('template-name-input')).toHaveValue(name);

    // 改名（原名+'改'）→ 保存：无引用 → 直接保存，不弹风险确认框
    const renamed = `${name}改`;
    await window.getByTestId('template-name-input').fill(renamed);
    await window.getByTestId('template-save').click();
    await expect(window.getByTestId('template-confirm-dialog')).not.toBeVisible();
    await expect(dialog).not.toBeVisible();

    // 新名卡片可见
    const newCard = window.locator('[data-testid^="template-card-"]').filter({ hasText: renamed });
    await expect(newCard).toBeVisible();
  } finally {
    await app.close();
  }
});

test('模板分类：设为默认 → 默认徽标迁移（A→B）', async () => {
  const { app, window } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    await gotoTemplatesCat(window);

    // UI 建模板 A、B（唯一名）
    const nameA = `E2E-TPL-DefA-${Date.now()}`;
    const nameB = `E2E-TPL-DefB-${Date.now()}`;
    const cardA = await createTemplateViaUi(window, nameA);
    const cardB = await createTemplateViaUi(window, nameB);
    const idA = await extractTemplateId(cardA);
    const idB = await extractTemplateId(cardB);

    // A 设为默认 → A 卡片出现「默认」徽标
    await window.getByTestId(`template-set-default-${idA}`).click();
    await expect(window.getByTestId(`template-default-badge-${idA}`)).toBeVisible();

    // B 设为默认 → 徽标迁移：B 出现 + A 消失
    await window.getByTestId(`template-set-default-${idB}`).click();
    await expect(window.getByTestId(`template-default-badge-${idB}`)).toBeVisible();
    await expect(window.getByTestId(`template-default-badge-${idA}`)).not.toBeVisible();
  } finally {
    await app.close();
  }
});

test('模板分类：删除被引用模板 → 风险确认（列出项目）→ 确认后卡片移除', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    // UI 建模板 T（唯一名）
    await gotoTemplatesCat(window);
    const tplName = `E2E-TPL-Delete-${Date.now()}`;
    const tplCard = await createTemplateViaUi(window, tplName);
    const tplId = await extractTemplateId(tplCard);

    // UI 建项目 P（唯一名；new-project-btn 在项目页，先导航过去）
    await gotoNav(window, '项目');
    const projectName = `E2E-TPL-Ref-${Date.now()}`;
    await createProjectViaUi(window, projectName);

    // 内核 API 构造引用：PATCH /api/v1/projects/{id} config.template_id
    await referenceProjectToTemplate(kernel, projectName, tplId);

    // 回设置模板分类 → 卡片 T 点删除 → 风险确认框可见，文案含引用数与项目名
    await gotoTemplatesCat(window);
    await window.getByTestId(`template-delete-${tplId}`).click();
    const confirm = window.getByTestId('template-confirm-dialog');
    await expect(confirm).toBeVisible();
    await expect(confirm).toContainText('正在被 1 个项目使用');
    await expect(confirm).toContainText(projectName);

    // 确认 → DELETE 204 → 卡片 T 消失
    await window.getByTestId('template-confirm-ok').click();
    await expect(tplCard).not.toBeVisible();
  } finally {
    await app.close();
  }
});

test('模板分类：删除被引用模板 → 风险确认 → 取消（确认框关闭 + 卡片保留）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    // 同用例 4 构造：UI 建模板 T + 项目 P，内核 API 挂引用
    await gotoTemplatesCat(window);
    const tplName = `E2E-TPL-Cancel-${Date.now()}`;
    const tplCard = await createTemplateViaUi(window, tplName);
    const tplId = await extractTemplateId(tplCard);

    await gotoNav(window, '项目');
    const projectName = `E2E-TPL-Ref-${Date.now()}`;
    await createProjectViaUi(window, projectName);

    await referenceProjectToTemplate(kernel, projectName, tplId);

    // 点删除 → 确认框可见 → 取消 → 确认框关闭 + 卡片 T 仍可见
    await gotoTemplatesCat(window);
    await window.getByTestId(`template-delete-${tplId}`).click();
    const confirm = window.getByTestId('template-confirm-dialog');
    await expect(confirm).toBeVisible();
    await window.getByTestId('template-confirm-cancel').click();
    await expect(confirm).not.toBeVisible();
    await expect(tplCard).toBeVisible();
  } finally {
    await app.close();
  }
});
