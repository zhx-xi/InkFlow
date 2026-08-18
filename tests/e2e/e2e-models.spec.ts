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

test.describe.configure({ timeout: 120_000 });

// ────────────────────────────────────────────────────────────────
// 9. 模型管理（#481 合并入设置页模型分类）：设置 → 模型分类 → 完整模型管理渲染
// ────────────────────────────────────────────────────────────────
test('模型管理：设置 → 模型分类 → 模型管理渲染（面板 + Provider 列表）', async () => {
  const { app, window } = await launchApp();
  try {
    // 同用例 8：清空持久化 UI 偏好保证中文文案确定性（zh）
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    // #481：模型管理无独立导航项（nav-item-models 已删除）→ 经「设置」→ 模型分类进入
    await expect(window.getByTestId('nav-item-models')).toHaveCount(0);
    await gotoNav(window, '设置');
    await expect(window.getByTestId('settings-page')).toBeVisible({ timeout: 15_000 });
    await window.getByTestId('settings-cat-models').click();

    // 路由 + 面板骨架渲染（设置页 h1 = set.title；模型管理面板 h2 = m.title）
    expect(await window.evaluate(() => location.hash)).toContain('/settings');
    expect(await window.evaluate(() => location.hash)).toContain('cat=models');
    const panel = window.getByTestId('models-panel');
    await expect(panel).toBeVisible({ timeout: 15_000 });
    await expect(panel.getByRole('heading', { level: 2 })).toContainText('模型管理');

    // Provider 列表区：lifespan seed 内置 4 provider（openai/deepseek/zhipu/ollama）
    // ⚠️ 不断言总数（frontend/data/inkflow.db 为持久文件，跨轮次累积 e2e-* provider）：
    //    断言 4 个 seed 名称都存在即可（CI 全新 runner 与本地持久库均稳定）
    const list = window.getByTestId('provider-list');
    await expect(list).toBeVisible();
    for (const seedName of ['openai', 'deepseek', 'zhipu', 'ollama']) {
      await expect(list).toContainText(seedName);
    }
    // 全新库 seed 按序插入 → openai 自增 id=1（持久库下 seed 首插 id 固定）
    await expect(window.getByTestId('provider-card-1')).toContainText('openai');
  } finally {
    await app.close();
  }
});


// ────────────────────────────────────────────────────────────────
// #140 E2：模型管理页交互用例（添加/编辑/删除 Provider、Key 徽标、添加模型）
// 每个用例独立 launch app；数据用唯一名 `e2e-<场景>-${Date.now()}` 隔离
// （满足后端名称校验 ^[a-z0-9_-]{1,32}$）；只操作本用例新建的 provider，
// 绝不触碰 seed 4 个（openai/deepseek/zhipu/ollama，DB 为持久文件）。
// ────────────────────────────────────────────────────────────────

/** 侧边栏导航（AppNav 链接文本子串匹配：项目 / 写作 / 设定库 / 设置 / 模型管理） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

/** 进入模型管理（设置页模型分类）：清空持久化 UI 偏好（中文确定性）→ 设置 → 模型分类 → 等面板骨架 */
async function gotoModels(window: Page): Promise<void> {
  await window.evaluate(() => localStorage.clear());
  await window.reload();
  await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });
  await gotoNav(window, '设置');
  await expect(window.getByTestId('settings-page')).toBeVisible({ timeout: 15_000 });
  await window.getByTestId('settings-cat-models').click();
  await expect(window.getByTestId('models-panel')).toBeVisible({ timeout: 15_000 });
}

/**
 * 通过 UI 添加 Provider：add-provider-btn → 填名称/Base URL/可选 API Key → 保存。
 * 返回新卡片的 testid（provider-card-<id>；id 为后端自增，不硬编码）。
 */
async function addProviderViaUi(
  window: Page,
  name: string,
  baseUrl = 'https://example.com/v1',
  apiKey?: string,
): Promise<string> {
  await window.getByTestId('add-provider-btn').click();
  const dialog = window.getByTestId('provider-dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('名称').fill(name);
  await dialog.getByLabel('Base URL').fill(baseUrl);
  if (apiKey) {
    await dialog.getByLabel('API Key').fill(apiKey);
  }
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  // 保存后 handleSaved → loadProviders 重新拉取 → 新卡片出现
  const card = window
    .locator('[data-testid^="provider-card-"]')
    .filter({ hasText: name })
    .first();
  await expect(card).toBeVisible({ timeout: 15_000 });
  const testid = await card.getAttribute('data-testid');
  if (!testid) {
    throw new Error(`provider-card testid 缺失（name=${name}）`);
  }
  return testid;
}

/** 从 provider-card testid 提取数字 id（'provider-card-7' → '7'） */
function cardId(testid: string): string {
  return testid.replace('provider-card-', '');
}

// ────────────────────────────────────────────────────────────────
// 用例 1：添加 Provider（名称校验 + 保存）
// ────────────────────────────────────────────────────────────────
test('模型管理：添加 Provider（名称校验拦截非法名 + 保存后新卡片出现）', async () => {
  const { app, window } = await launchApp();
  try {
    await gotoModels(window);

    await window.getByTestId('add-provider-btn').click();
    const dialog = window.getByTestId('provider-dialog');
    await expect(dialog).toBeVisible();

    // 非法名称（含空格大写）：校验文案出现 + 保存 disabled
    await dialog.getByLabel('名称').fill('Bad Name');
    await expect(
      dialog.getByText('仅允许小写字母 / 数字 / 下划线 / 连字符，1-32 字符'),
    ).toBeVisible();
    await expect(dialog.getByRole('button', { name: '保存', exact: true })).toBeDisabled();

    // 改填合法名 + Base URL → 保存 → 弹窗关闭
    const name = `e2e-${Date.now()}`;
    await dialog.getByLabel('名称').fill(name);
    await dialog.getByLabel('Base URL').fill('https://example.com/v1');
    await dialog.getByRole('button', { name: '保存', exact: true }).click();
    await expect(dialog).toHaveCount(0);

    // 新卡片出现（按名称匹配，不硬编码自增 id）
    const card = window
      .locator('[data-testid^="provider-card-"]')
      .filter({ hasText: name })
      .first();
    await expect(card).toBeVisible({ timeout: 15_000 });
    await expect(card).toContainText(name);
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 用例 2：Provider 编辑（dialog 预填 + 改名后卡片更新）
// ────────────────────────────────────────────────────────────────
test('模型管理：编辑 Provider（弹窗预填原名称 + 改名后卡片更新）', async () => {
  const { app, window } = await launchApp();
  try {
    await gotoModels(window);
    const original = `e2e-${Date.now()}`;
    const testid = await addProviderViaUi(window, original);
    const id = cardId(testid);

    await window.getByTestId(`provider-edit-${id}`).click();
    const dialog = window.getByTestId('provider-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute('aria-label', '编辑 Provider');
    // 名称预填原值；编辑模式无预置模板 Select
    await expect(dialog.getByLabel('名称')).toHaveValue(original);
    await expect(dialog.getByLabel('预置模板')).toHaveCount(0);

    const renamed = `e2e-edit-${Date.now()}`;
    await dialog.getByLabel('名称').fill(renamed);
    await dialog.getByRole('button', { name: '保存', exact: true }).click();
    await expect(dialog).toHaveCount(0);

    // 卡片 id 不变，文本更新为新名称（loadProviders 重新拉取后）
    await expect(window.getByTestId(`provider-card-${id}`)).toContainText(renamed);
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 用例 3：Provider 删除（确认框「取消」保留 + 「删除」后卡片消失）
// ────────────────────────────────────────────────────────────────
test('模型管理：删除 Provider（确认框取消保留 + 确认后卡片消失）', async () => {
  const { app, window } = await launchApp();
  try {
    await gotoModels(window);
    const name = `e2e-del-${Date.now()}`;
    const testid = await addProviderViaUi(window, name);
    const id = cardId(testid);
    const card = window.getByTestId(`provider-card-${id}`);

    // 第一次点删除：确认框可见（文案含名称与模型数）→ 取消 → 卡片保留
    await window.getByTestId(`provider-delete-${id}`).click();
    const confirmDlg = window.getByRole('dialog', { name: '删除 Provider' });
    await expect(confirmDlg).toBeVisible();
    await expect(confirmDlg).toContainText(`删除 Provider「${name}」？该 Provider 有 0 个模型`);
    await confirmDlg.getByRole('button', { name: '取消', exact: true }).click();
    await expect(confirmDlg).toHaveCount(0);
    await expect(card).toBeVisible();

    // 第二次点删除：确认 → 卡片消失（不硬编码 id，只查本用例新建的）
    await window.getByTestId(`provider-delete-${id}`).click();
    await expect(confirmDlg).toBeVisible();
    await confirmDlg.getByRole('button', { name: '删除', exact: true }).click();
    await expect(card).toHaveCount(0);
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 用例 4：保存 API Key → 徽标「Key 已存」
// ────────────────────────────────────────────────────────────────
test('模型管理：保存 API Key 后徽标显示「Key 已存」', async () => {
  const { app, window } = await launchApp();
  try {
    await gotoModels(window);
    const name = `e2e-key-${Date.now()}`;
    const testid = await addProviderViaUi(window, name, 'https://example.com/v1', 'sk-test-123');
    const id = cardId(testid);

    // 只断言新建 provider 的徽标（seed 4 个保持「未存 Key」，不动它们）
    await expect(window.getByTestId(`provider-key-badge-${id}`)).toContainText('Key 已存');
    await expect(window.getByTestId(`provider-card-${id}`)).toContainText(name);
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 用例 5：添加模型（AddModelDialog：选 Provider → 模型行 + 计数更新）
// ────────────────────────────────────────────────────────────────
test('模型管理：添加模型（选 Provider + 模型行出现 + 计数更新）', async () => {
  const { app, window } = await launchApp();
  try {
    await gotoModels(window);
    const providerName = `e2e-${Date.now()}`;
    const testid = await addProviderViaUi(window, providerName);
    const id = cardId(testid);

    await window.getByTestId('add-model-btn').click();
    const dialog = window.getByTestId('add-model-dialog');
    await expect(dialog).toBeVisible();

    // 选择新建的 Provider（Radix Select：click trigger → portal 选项）
    await dialog.getByLabel('选择 Provider').click();
    await window.getByRole('option', { name: providerName }).click();

    const modelId = `e2e-model-${Date.now()}`;
    await dialog.getByLabel('模型 ID 1').fill(modelId);
    // 类型默认 chat（不改动）；「添加一行」按钮存在
    await expect(dialog.getByLabel('类型 1')).toContainText('chat');
    await expect(dialog.getByRole('button', { name: '添加一行' })).toBeVisible();

    await dialog.getByRole('button', { name: '保存', exact: true }).click();
    await expect(dialog).toHaveCount(0);

    // 模型表出现该行（含模型 ID）+ provider 计数更新为「1 个模型」
    const row = window.getByTestId(`model-row-${modelId}`);
    await expect(row).toBeVisible({ timeout: 15_000 });
    await expect(row).toContainText(modelId);
    await expect(window.getByTestId(`provider-model-count-${id}`)).toContainText('1 个模型');
  } finally {
    await app.close();
  }
});
