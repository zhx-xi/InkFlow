/**
 * 设置页「Agent 管理」域 E2E（#260 F41 自定义 Agent 编辑，spec §5.5 / §13 M9）
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-settings-agents
 *
 * 基建（复制自 e2e-settings-templates.spec.ts，本文件自包含不 import 其他 spec）：
 * - _electron.launch + waitKernelInfo（__kernelInfo 注入轮询，窗口交互前必须先等内核就绪，否则 401）
 * - 真实内核 + 真实渲染；用例开头清空持久化 UI 偏好（inkflow.ui）并重载，保证中文文案确定性
 * - 每个用例独立 launch app（workers=1，串行）+ try/finally app.close()
 *
 * 数据隔离约定（内核 DB 为持久文件 frontend/inkflow.db，跨用例残留）：
 * - 内置 6 Agent（架构师/执笔/审校/修订/世界观/润色）+ 6 Skill 由 lifespan seed（#403，幂等；
 *   #522 后 Skill 目录名 = 英文 slug）
 * - 自定义 Agent 名唯一（E2E-AG-<场景>-${Date.now()}）；定位卡片一律
 *   locator('[data-testid^="agent-card-"]').filter({ hasText: 名称 })（禁硬编码 id，DB 自增持久累积），
 *   卡片 id 从 data-testid 提取（剥离 agent-card- 前缀）
 * - skill 勾选定位用 'writing-methodology'（内置 seed 目录名 = 英文 slug，#522，
 *   label 容器含 name 文本）：
 *   dialog.locator('[data-testid^="agent-skill-"]').filter({ hasText: 'writing-methodology' })
 *
 * testid 契约（#260 F41）：agent-list / agent-new-btn / agent-card-<id> /
 * agent-builtin-badge-<id> / agent-edit-<id>（仅自定义）/ agent-del-<id>（仅自定义）/
 * agent-tool-chip-<toolName> / agent-skill-chip-<skillName>（#522 skill_ids = 目录名）；
 * agent-dialog（role=dialog）/
 * agent-name-input / agent-desc-input / agent-icon-input / agent-prompt-input /
 * agent-tool-group-<group> / agent-tool-<toolName> / agent-skill-search /
 * agent-skill-<skillName> / agent-model-input / agent-temp-input /
 * agent-dialog-save / agent-dialog-cancel；agent-delete-dialog / agent-delete-ok /
 * agent-delete-cancel
 *
 * 门控适配（#384/#399）：localStorage.clear + window.reload 后 app-nav 断言升 60s
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

test.describe.configure({ timeout: 120_000 });

// ────────────────────────────────────────────────────────────────
// #260 F41 Agent 管理域 E2E：列表只读 / 创建 / 编辑 / 删除确认
// ────────────────────────────────────────────────────────────────

test('Agent 管理：内置 Agent 只读展示（builtin 徽标 + 无编辑/删除按钮）+ 新建按钮存在', async () => {
  const { app, window } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    await gotoAgentsCat(window);

    // 内置「架构师」卡片（seed 恒有）：builtin 徽标 + 无编辑/删除按钮（只读）
    const builtinCard = window.locator('[data-testid^="agent-card-"]').filter({ hasText: '架构师' });
    await expect(builtinCard).toBeVisible();
    await expect(builtinCard.getByTestId('agent-builtin-badge-1')).toBeVisible();
    await expect(builtinCard.getByTestId(/^agent-edit-/)).toHaveCount(0);
    await expect(builtinCard.getByTestId(/^agent-del-/)).toHaveCount(0);

    // 新建按钮存在
    await expect(window.getByTestId('agent-new-btn')).toBeVisible();
  } finally {
    await app.close();
  }
});

test('Agent 管理：创建自定义 Agent 全流程（新建 → 填表 + 勾函数组 + 绑 skill + 模型/温度 → 保存 → 卡片 + 白名单明细）', async () => {
  test.setTimeout(180_000);
  const { app, window } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    await gotoAgentsCat(window);

    // 新建对话框：role=dialog + 名称输入初始为空
    await window.getByTestId('agent-new-btn').click();
    const dialog = window.getByTestId('agent-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAttribute('role', 'dialog');

    // 基本信息
    const name = `E2E-AG-Create-${Date.now()}`;
    await window.getByTestId('agent-name-input').fill(name);
    await window.getByTestId('agent-desc-input').fill('E2E 创建描述');
    await window.getByTestId('agent-icon-input').fill('✨');
    await window.getByTestId('agent-prompt-input').fill('你是 E2E 润色师。');

    // 函数分组（D2）：写作组存在 + 勾选 save_draft；检索组存在不勾选
    await expect(dialog.getByTestId('agent-tool-group-writing')).toBeVisible();
    await dialog.getByTestId('agent-tool-save_draft').click();
    await dialog.getByTestId('agent-tool-group-retrieval').click(); // 展开无副作用，仅确认组存在

    // skill 绑定：搜索 writing-methodology（#522 内置目录名）→ 过滤 → 勾选 label 容器
    await dialog.getByTestId('agent-skill-search').fill('writing-methodology');
    const skillLabel = dialog.locator('[data-testid^="agent-skill-"]').filter({ hasText: 'writing-methodology' });
    await expect(skillLabel).toBeVisible();
    await skillLabel.click();

    // 模型/温度覆盖
    await window.getByTestId('agent-model-input').fill('openai/gpt-4o');
    await window.getByTestId('agent-temp-input').fill('0.6');

    // 保存 → 对话框关闭 → 新卡片出现
    await dialog.getByTestId('agent-dialog-save').click();
    await expect(dialog).not.toBeVisible();

    const card = window.locator('[data-testid^="agent-card-"]').filter({ hasText: name });
    await expect(card).toBeVisible();
    await expect(card).toContainText('E2E 创建描述');
    // 函数/skill 白名单展示（双向视图）：save_draft 工具 chip + writing-methodology skill chip
    await expect(card.getByTestId('agent-tool-chip-save_draft')).toBeVisible();
    await expect(
      card.locator('[data-testid^="agent-skill-chip-"]').filter({ hasText: 'writing-methodology' })
    ).toBeVisible();
    // 自定义可编辑：编辑/删除按钮存在 + 无 builtin 徽标
    await expect(card.getByTestId(/^agent-edit-/)).toHaveCount(1);
    await expect(card.getByTestId(/^agent-del-/)).toHaveCount(1);
  } finally {
    await app.close();
  }
});

test('Agent 管理：编辑自定义 Agent（名称回显 → 改名 + 取消一个函数 → 保存 → 卡片更新）', async () => {
  const { app, window } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    await gotoAgentsCat(window);

    // 前置：通过 UI 创建（与上一用例隔离的唯一名）
    const name = `E2E-AG-Edit-${Date.now()}`;
    await window.getByTestId('agent-new-btn').click();
    const createDialog = window.getByTestId('agent-dialog');
    await expect(createDialog).toBeVisible();
    await window.getByTestId('agent-name-input').fill(name);
    await createDialog.getByTestId('agent-tool-save_draft').click();
    await createDialog.getByTestId('agent-dialog-save').click();
    await expect(createDialog).not.toBeVisible();

    const card = window.locator('[data-testid^="agent-card-"]').filter({ hasText: name });
    await expect(card).toBeVisible();
    const agentId = await extractAgentId(card);

    // 点编辑 → 对话框预填名称
    await window.getByTestId(`agent-edit-${agentId}`).click();
    const editDialog = window.getByTestId('agent-dialog');
    await expect(editDialog).toBeVisible();
    await expect(window.getByTestId('agent-name-input')).toHaveValue(name);

    // 改名 + 取消 save_draft 函数
    const newName = `${name}-改`;
    await window.getByTestId('agent-name-input').fill(newName);
    await editDialog.getByTestId('agent-tool-save_draft').click();
    await editDialog.getByTestId('agent-dialog-save').click();
    await expect(editDialog).not.toBeVisible();

    // 卡片更新：新名可见 + save_draft chip 消失
    const updatedCard = window.locator('[data-testid^="agent-card-"]').filter({ hasText: newName });
    await expect(updatedCard).toBeVisible();
    await expect(updatedCard.getByTestId('agent-tool-chip-save_draft')).toHaveCount(0);
  } finally {
    await app.close();
  }
});

test('Agent 管理：删除自定义 Agent（确认框 → 确认 → 卡片消失）；内置无删除入口', async () => {
  const { app, window } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    await gotoAgentsCat(window);

    // 前置：创建唯一名 Agent
    const name = `E2E-AG-Del-${Date.now()}`;
    await window.getByTestId('agent-new-btn').click();
    const createDialog = window.getByTestId('agent-dialog');
    await expect(createDialog).toBeVisible();
    await window.getByTestId('agent-name-input').fill(name);
    await createDialog.getByTestId('agent-dialog-save').click();
    await expect(createDialog).not.toBeVisible();

    const card = window.locator('[data-testid^="agent-card-"]').filter({ hasText: name });
    await expect(card).toBeVisible();
    const agentId = await extractAgentId(card);

    // 删除：确认框出现（含 Agent 名）→ 确认 → 卡片消失
    await window.getByTestId(`agent-del-${agentId}`).click();
    const confirmDialog = window.getByTestId('agent-delete-dialog');
    await expect(confirmDialog).toBeVisible();
    await expect(confirmDialog).toContainText(name);
    await window.getByTestId('agent-delete-ok').click();
    await expect(card).not.toBeVisible();
  } finally {
    await app.close();
  }
});
