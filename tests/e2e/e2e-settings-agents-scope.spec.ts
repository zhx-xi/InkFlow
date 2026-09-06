/**
 * 设置页「Agent 管理 → scope 授权矩阵」域 E2E（#957 F58 GUI scope 勾选矩阵，contract-957 §5-T2）
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-settings-agents-scope
 *
 * 基建（自包含复制自 e2e-settings-agents.spec.ts，本文件不 import 其他 spec）：
 * - _electron.launch + waitKernelInfo（__kernelInfo 注入轮询，窗口交互前必须先等内核就绪，否则 401）
 * - 真实内核 + 真实渲染；用例开头清空持久化 UI 偏好（inkflow.ui）并重载，保证中文文案确定性
 * - 每个用例独立 launch app（workers=1，串行）+ try/finally app.close()
 * - apiJson 为直调内核 HTTP 的硬断言工具（复制自 e2e-rag-fake.spec.ts，含 X-InkFlow-Token）
 * - ❗ 本文件依赖 GREEN 后才存在的 scope 矩阵 UI（AgentEditDialog/AgentList 重写，contract-957 §2/§3）；
 *   本批为 RED 契约文件，不要求本地跑通 —— CI e2e-frontend-settings 是最终裁判。
 *
 * 数据隔离约定（内核 DB 为持久文件 frontend/inkflow.db，跨用例残留）：
 * - 内置 6 Agent（架构师/写手/审校/修订/世界观/润色）由 lifespan seed（#403，幂等）
 * - 自定义 Agent 名唯一（E2E-SCOPE-<场景>-${Date.now()}）；定位卡片一律
 *   locator('[data-testid^="agent-card-"]').filter({ hasText: 名称 })（禁硬编码 id，DB 自增持久累积），
 *   卡片 id 从 data-testid 提取（剥离 agent-card- 前缀）
 * - Agent 列表页不依赖当前项目（#595 建项目须选 ≥1 题材仅影响项目创建流），本文件不建项目（同 e2e-settings-agents.spec.ts）
 *
 * testid 契约（#957 F58，contract-957 §2/§3）：新增
 *   agent-scope-matrix / agent-scope-row-<domain>（8 域行）/
 *   agent-scope-cell-<domain>-<op>（24 格，内含 checkbox，点击容器切换）/
 *   agent-scope-head-read / agent-scope-head-write / agent-scope-head-delete /
 *   agent-scope-delete-help（删除列头说明 tooltip）/
 *   详情：agent-scope-detail / agent-detail-scope-<domain>-<op>（data-checked="true|false"）/
 *   agent-detail-resolved-count / agent-detail-resolved-toggle（默认折叠）/
 *   agent-detail-resolved-tool-<name> / agent-scope-empty
 *   复用（沿用 e2e-settings-agents.spec.ts）：agent-list / settings-cat-agent / agent-new-btn /
 *   agent-card-<id> / agent-edit-<id>（仅自定义）/ agent-detail-<id>（仅内置）/ agent-dialog /
 *   agent-name-input / agent-dialog-save / agent-builtin-badge-<id>
 *
 * 门控适配（#384/#399）：localStorage.clear + window.reload 后 app-nav 断言升 60s
 *
 * 范围裁定（contract-957 §5-T2 最后一段，逐字）：
 * fake-LLM 驱动真实对话工具循环的 E2E 不在本批——chat 主面板无「按自定义 Agent 开会话」入口
 * （agent 链工具 agent_call 路径），F58 Phase 2 范畴；本批 E2E 证 scope 保存→grants→resolved
 * 全链路真实内核数据面。
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

/** 进入设置页 Agent 分类（侧边栏「设置」→ 设置导航「Agent」→ agent-list 可见） */
async function gotoAgentsCat(window: Page): Promise<void> {
  await gotoNav(window, '设置');
  await window.getByTestId('settings-cat-agent').click();
  await expect(window.getByTestId('agent-list')).toBeVisible({ timeout: 15_000 });
}

/** 从 Agent 卡片 data-testid 提取 id（剥离 agent-card- 前缀） */
async function extractAgentId(card: Locator): Promise<string> {
  const testid = await card.getAttribute('data-testid');
  if (!testid) {
    throw new Error('Agent 卡片缺少 data-testid');
  }
  return testid.replace('agent-card-', '');
}

/** 直调内核 API：非 2xx 抛错；204 → data undefined（复制 e2e-rag-fake.spec.ts / e2e-settings apiJson） */
async function apiJson(
  kernel: KernelInfo,
  method: string,
  pathname: string,
  body?: unknown
): Promise<{ status: number; data: unknown }> {
  const res = await fetch(`http://127.0.0.1:${kernel.port}${pathname}`, {
    method,
    headers: {
      'X-InkFlow-Token': kernel.token,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`kernel API ${method} ${pathname} -> ${res.status}: ${detail}`);
  }
  const data = res.status === 204 ? undefined : await res.json();
  return { status: res.status, data };
}

/** 从内核 GET /api/v1/agents 中按 name 精确查一条 Agent 记录（无则 undefined） */
async function getAgentByName(
  kernel: KernelInfo,
  name: string
): Promise<Record<string, unknown> | undefined> {
  const { data } = await apiJson(kernel, 'GET', '/api/v1/agents');
  const items = (data as { items?: Record<string, unknown>[] }).items ?? [];
  return items.find((a) => a.name === name);
}

/**
 * 归一化一条 Agent 的授权断言面：
 * 返回 { grants: { <domain>: sorted ops[] }, resolved: sorted tool name[] }。
 * 供 expect.poll 到做到 deep-equal（复制 e2e-rag-fake.spec.ts ⑦ 的 poll 形态）。
 */
async function scopeSnapshotOf(
  kernel: KernelInfo,
  name: string
): Promise<Record<string, unknown> | null> {
  const rec = await getAgentByName(kernel, name);
  if (!rec) {
    return null;
  }
  const grants: Array<{ domain: string; ops: string[] }> =
    (rec.grants as Array<{ domain: string; ops: string[] }>) ?? [];
  const grantsByDomain: Record<string, string[]> = {};
  for (const g of grants) {
    grantsByDomain[g.domain] = [...g.ops].sort();
  }
  const resolved: string[] = (rec.resolved_tool_names as string[]) ?? [];
  return { grants: grantsByDomain, resolved: [...new Set(resolved)].sort() };
}

/** 断言 edit 矩阵某格内 checkbox 的勾选态（格子为 label 容器，内含 input[type=checkbox]，contract-957 §2） */
async function expectCell(dialog: Locator, cellTestid: string, checked: boolean): Promise<void> {
  const cell = dialog.getByTestId(cellTestid);
  await expect(cell).toBeVisible();
  const box = cell.locator('input[type="checkbox"]');
  if (checked) {
    await expect(box).toBeChecked();
  } else {
    await expect(box).not.toBeChecked();
  }
}

test.describe.configure({ timeout: 240_000 });

// ────────────────────────────────────────────────────────────────
// #957 F58 GUI scope 勾选矩阵 E2E：创建带 scope 的 Agent / 编辑回显 + 增量授权 / 内置详情矩阵回显
// 全部关键断言为真实内核 HTTP 硬断言（GET /api/v1/agents），锁 scope→grants→resolved 全链路数据面。
// ────────────────────────────────────────────────────────────────

test('设置→Agent：创建自定义 Agent 勾选 scope 矩阵（角色·读/写 + 记忆·读）→ 保存 → 卡片 + 内核 grants/resolved 硬断言', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    await gotoAgentsCat(window);

    // 新建对话框
    await window.getByTestId('agent-new-btn').click();
    const dialog = window.getByTestId('agent-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute('role', 'dialog');

    const name = `E2E-SCOPE-${Date.now()}`;
    await dialog.getByTestId('agent-name-input').fill(name);

    // scope 矩阵：容器 + 行 + 三列头可见（契约 §2）
    const matrix = dialog.getByTestId('agent-scope-matrix');
    await expect(matrix).toBeVisible();
    await expect(dialog.getByTestId('agent-scope-row-character')).toBeVisible();
    await expect(dialog.getByTestId('agent-scope-row-memory')).toBeVisible();
    await expect(dialog.getByTestId('agent-scope-head-read')).toBeVisible();
    await expect(dialog.getByTestId('agent-scope-head-write')).toBeVisible();
    await expect(dialog.getByTestId('agent-scope-head-delete')).toBeVisible();

    // 勾 角色·读 + 角色·写 + 记忆·读（点击格子容器切换）
    await dialog.getByTestId('agent-scope-cell-character-read').click();
    await dialog.getByTestId('agent-scope-cell-character-write').click();
    await dialog.getByTestId('agent-scope-cell-memory-read').click();

    // 保存 → 对话框关闭 → 卡片出现（locator 按名称过滤，禁硬编码 id）
    await dialog.getByTestId('agent-dialog-save').click();
    await expect(dialog).not.toBeVisible();

    const card = window.locator('[data-testid^="agent-card-"]').filter({ hasText: name });
    await expect(card).toBeVisible();

    // 内核硬断言（保存异步落库 → poll，timeout 30s）：grants + resolved 集合 == 契约 §5-T2
    // resolved 集合：search_characters(character·read) + create/update_character(character·write) + memory_list(memory·read)
    // 真实映射源：backend/.../agent/tools/registry.py GRANT_TOOL_MAP
    await expect
      .poll(async () => scopeSnapshotOf(kernel, name), { timeout: 30_000 })
      .toEqual({
        grants: { character: ['read', 'write'], memory: ['read'] },
        resolved: ['create_character', 'memory_list', 'search_characters', 'update_character'],
      });
  } finally {
    await app.close();
  }
});

test('设置→Agent：编辑重开 scope 矩阵回显（三格 checked）→ 加勾 世界观·写 → 保存 → 内核 grants 更新', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    await gotoAgentsCat(window);

    // 前置：通过 UI 创建带 scope 的唯一名 Agent（与其它用例隔离）
    const name = `E2E-SCOPE-Edit-${Date.now()}`;
    await window.getByTestId('agent-new-btn').click();
    const createDialog = window.getByTestId('agent-dialog');
    await expect(createDialog).toBeVisible();
    await createDialog.getByTestId('agent-name-input').fill(name);
    await createDialog.getByTestId('agent-scope-cell-character-read').click();
    await createDialog.getByTestId('agent-scope-cell-character-write').click();
    await createDialog.getByTestId('agent-scope-cell-memory-read').click();
    await createDialog.getByTestId('agent-dialog-save').click();
    await expect(createDialog).not.toBeVisible();

    const card = window.locator('[data-testid^="agent-card-"]').filter({ hasText: name });
    await expect(card).toBeVisible();
    const agentId = await extractAgentId(card);

    // 编辑重开：名称回显 + 矩阵三格 checked（编辑回显 = editing.grants，初始勾选，§2）
    await window.getByTestId(`agent-edit-${agentId}`).click();
    const editDialog = window.getByTestId('agent-dialog');
    await expect(editDialog).toBeVisible();
    await expect(editDialog.getByTestId('agent-name-input')).toHaveValue(name);

    await expectCell(editDialog, 'agent-scope-cell-character-read', true);
    await expectCell(editDialog, 'agent-scope-cell-character-write', true);
    await expectCell(editDialog, 'agent-scope-cell-memory-read', true);
    await expectCell(editDialog, 'agent-scope-cell-world-write', false); // 初始未勾

    // 加勾 世界观·写 → 保存
    await editDialog.getByTestId('agent-scope-cell-world-write').click();
    await expectCell(editDialog, 'agent-scope-cell-world-write', true);
    await editDialog.getByTestId('agent-dialog-save').click();
    await expect(editDialog).not.toBeVisible();

    // 内核硬断言：grants 更新（新增 world·write）+ resolved 集合扩至 8 工具
    // （world·write → create_world_setting/update_world_setting/create_map/update_map，registry GRANT_TOOL_MAP）
    await expect
      .poll(async () => scopeSnapshotOf(kernel, name), { timeout: 30_000 })
      .toEqual({
        grants: { character: ['read', 'write'], memory: ['read'], world: ['write'] },
        resolved: [
          'create_character',
          'create_map',
          'create_world_setting',
          'memory_list',
          'search_characters',
          'update_character',
          'update_map',
          'update_world_setting',
        ],
      });
  } finally {
    await app.close();
  }
});

test('设置→Agent：内置「架构师」详情弹窗 scope 矩阵回显（角色·读 checked）+ resolved 计数 + 默认折叠 + 展开显工具行', async () => {
  const { app, window } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    await gotoAgentsCat(window);

    // 内置「架构师」卡（seed 恒有，builtin 徽标 + 详情按钮 agent-detail-<id>，无编辑/删除）
    const builtinCard = window.locator('[data-testid^="agent-card-"]').filter({ hasText: '架构师' });
    await expect(builtinCard).toBeVisible();
    await expect(builtinCard.getByTestId(/^agent-builtin-badge-/)).toBeVisible();
    await builtinCard.getByTestId(/^agent-detail-/).click();

    const detail = window.getByTestId('agent-detail-dialog');
    await expect(detail).toBeVisible();

    // 详情 scope 矩阵（§3）：容器 + 角色·读 checked
    await expect(detail.getByTestId('agent-scope-detail')).toBeVisible();
    await expect(detail.getByTestId('agent-detail-scope-character-read')).toHaveAttribute('data-checked', 'true');

    // resolved 计数可见（数量不加锁，见文件头范围裁定）
    await expect(detail.getByTestId('agent-detail-resolved-count')).toBeVisible();

    // 默认折叠：无 agent-detail-resolved-tool-*（Playwright 无 queryByTestId，RTL「不存在」语义 → toHaveCount(0)）
    await expect(detail.getByTestId(/^agent-detail-resolved-tool-/)).toHaveCount(0);

    // 展开 toggle → 工具行
    await detail.getByTestId('agent-detail-resolved-toggle').click();
    await expect(detail.getByTestId(/^agent-detail-resolved-tool-/).first()).toBeVisible();
  } finally {
    await app.close();
  }
});
