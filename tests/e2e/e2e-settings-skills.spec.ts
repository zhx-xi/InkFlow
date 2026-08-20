/**
 * 设置页 — Skill 管理域 E2E（F40 #259，spec §5.4 上传绑定 / §5.6 删除保护 / §13 M7）
 *
 * 运行方式（同 e2e-settings.spec.ts 基建）：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-settings-skills
 *
 * 契约锚点（M7）：上传→绑定→引用视图→删除确认 全流程
 * - 上传：粘贴 SKILL.md → frontmatter 解析预览（name/description）
 * - 绑定：**默认不勾选**（D1 铁律）+ 可搜索 + 应用到全部 + 内置禁用
 * - 管理列表：来源 badge（内置/用户上传）+ 被引用 Agent 反查
 * - 删除保护：内置只读无删除按钮；被引用 → 确认框列影响面
 *
 * 数据准备：内核内置 seed 6 Agent（全部 builtin）+ 6 Skill。绑定目标须为**自定义 Agent**
 * （后端 PATCH 内置 → 409），F40 无 Agent 创建 UI → 内核 API 预建自定义 Agent（e2e-settings-
 * templates.spec.ts fetchKernel 先例）。每个用例独立 launch（workers=1，串行）。
 */
import path from 'node:path';
import { rmSync } from 'node:fs';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');
const MAIN_JS = 'packages/electron/out/main.js';

// 隔离数据目录清理：本地跑（INKFLOW_DATA_DIR 已注入）时清空残留——E2E 重跑/前次失败
// 会留下同名 skill/agent 导致 422 污染断言（2026-08-16 首跑实测）；CI 无此 env 不删
if (process.env.INKFLOW_DATA_DIR) {
  rmSync(process.env.INKFLOW_DATA_DIR, { recursive: true, force: true });
}

/** 卡片容器定位器：data-testid 前缀匹配容器 skill-card-<id> 与子元素 skill-card-name/desc/refs，
 * 用 has:skill-card-name 只留容器（strict mode 防 2 元素歧义，2026-08-16 E2E 首跑实测） */
function skillCard(window: Page, name: string) {
  return window
    .locator('[data-testid^="skill-card-"]')
    .filter({ has: window.getByTestId('skill-card-name') })
    .filter({ hasText: name });
}

interface KernelInfo {
  pid: number;
  port: number;
  token: string;
}

async function readKernelInfo(
  app: ElectronApplication
): Promise<KernelInfo | undefined> {
  return app.evaluate(() => (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo);
}

async function waitKernelInfo(app: ElectronApplication, timeoutMs = 60_000): Promise<KernelInfo> {
  const deadline = Date.now() + timeoutMs;
  let info: KernelInfo | undefined;
  while (Date.now() < deadline) {
    info = await readKernelInfo(app);
    if (info) return info;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`__kernelInfo 未在 ${timeoutMs}ms 内注入（内核未就绪）`);
}

async function launchApp(): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

/** 直连内核 REST API（数据准备用；204 空响应返回 undefined） */
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
  if (res.status === 204) return undefined;
  return (await res.json()) as unknown;
}

/** 内核 API 预建自定义 Agent（F40 无 Agent 创建 UI；builtin=false 才能被绑定）。
 * 名称带随机后缀——E2E 重跑/CI retry 时同名 422 会污染断言（2026-08-16 首跑实测数据残留） */
async function seedCustomAgent(kernel: KernelInfo, baseName: string): Promise<{ id: number; name: string }> {
  const name = `${baseName}${Math.floor(Math.random() * 100000)}`;
  const created = (await fetchKernel(kernel, '/api/v1/agents', {
    method: 'POST',
    body: {
      name,
      description: 'E2E 预建自定义 Agent',
      icon: '🤖',
      system_prompt: '你是测试 Agent',
      tool_ids: [],
      skill_ids: [],
    },
  })) as { id: number; builtin: boolean };
  expect(created.id).toBeGreaterThan(0);
  expect(created.builtin).toBe(false);
  return { id: created.id, name };
}

/** 进入设置页 Skill 分类（侧边栏「设置」→ 设置导航「Skill 管理」） */
async function gotoSkillCat(window: Page): Promise<void> {
  await gotoNav(window, '设置');
  await window.getByTestId('settings-cat-skills').click();
  await expect(window.getByTestId('skill-list')).toBeVisible();
}

/** 生成唯一 skill 名 + 合法 SKILL.md 内容（用例间/重跑不撞名 422，2026-08-16 首跑实测） */
function makeSkillMd(): { name: string; content: string } {
  const name = `e2e-research-${Math.floor(Math.random() * 100000)}`;
  return {
    name,
    content: `---
name: ${name}
description: E2E 调研方法论
tags: research
---
# 调研流程
1. 明确问题
2. 检索资料
`,
  };
}

test.describe.configure({ timeout: 120_000 });

// ────────────────────────────────────────────────────────────────
// #259 Skill 管理域 E2E：上传→绑定→引用视图→删除确认（M7）
// ────────────────────────────────────────────────────────────────

test('Skill 管理：上传（frontmatter 预览）→ 绑定默认不勾选 → 上传成功出现在列表', async () => {
  const { app, window } = await launchApp();
  try {
    const skill = makeSkillMd();
    await gotoSkillCat(window);

    // 打开上传对话框
    await window.getByTestId('skill-add-btn').click();
    const dialog = window.getByTestId('skill-upload-dialog');
    await expect(dialog).toBeVisible();

    // 粘贴内容 → frontmatter 预览出现 name/description
    await window.getByTestId('skill-upload-content').fill(skill.content);
    await expect(window.getByTestId('skill-upload-preview-name')).toHaveText(skill.name);
    await expect(window.getByTestId('skill-upload-preview-desc')).toHaveText('E2E 调研方法论');

    // 🔴 D1：绑定 checkbox 默认不勾选
    await expect(window.getByTestId('skill-bind-agent-1')).toBeVisible();
    const checkedCount = await window
      .locator('[data-testid^="skill-bind-agent-"] input[type="checkbox"]:checked')
      .count();
    expect(checkedCount).toBe(0);

    // 不勾选任何 Agent → 上传
    await window.getByTestId('skill-upload-submit').click();
    await expect(dialog).not.toBeVisible();

    // 列表出现新 skill（用户上传 badge）
    const card = skillCard(window, skill.name);
    await expect(card).toBeVisible();
    await expect(card.locator('[data-testid^="skill-source-user-"]')).toBeVisible();
  } finally {
    await app.close();
  }
});

test('Skill 管理：上传时绑定自定义 Agent → 引用视图显示被引用 → 删除确认列影响面', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const skill = makeSkillMd();
    // 预建自定义 Agent（绑定目标；内置 Agent 绑定 → 409）
    const custom = await seedCustomAgent(kernel, 'E2E 绑定测试员');
    const customName = custom.name;

    await gotoSkillCat(window);
    await window.getByTestId('skill-add-btn').click();
    const dialog = window.getByTestId('skill-upload-dialog');
    await expect(dialog).toBeVisible();

    await window.getByTestId('skill-upload-content').fill(skill.content);
    await expect(window.getByTestId('skill-upload-preview-name')).toHaveText(skill.name);

    // 绑定区：内置 Agent 禁用（写手 = 内置 seed），自定义 Agent 可勾选
    const builtinAgent = window.getByTestId('skill-bind-agent-1');
    await expect(builtinAgent.locator('input')).toBeDisabled();

    // 搜索自定义 Agent 并勾选（D1：显式指定，非默认）
    await window.getByTestId('skill-bind-search').fill(customName);
    const customRow = window.locator('[data-testid^="skill-bind-agent-"]').filter({ hasText: customName });
    await expect(customRow).toBeVisible();
    await customRow.locator('input').check();

    await window.getByTestId('skill-upload-submit').click();
    await expect(dialog).not.toBeVisible();

    // 引用视图：新 skill 卡片显示「被 1 个 Agent 引用：<customName>」
    const card = skillCard(window, skill.name);
    await expect(card).toBeVisible();
    const refs = card.locator('[data-testid^="skill-refs-"]');
    await expect(refs).toBeVisible();
    await expect(refs).toContainText(customName);

    // 删除保护：被引用 → 删除按钮存在 → 确认框列影响面 → 确认删除 → 卡片消失
    const deleteBtn = card.locator('[data-testid^="skill-delete-"]');
    await expect(deleteBtn).toBeVisible();
    await deleteBtn.click();
    const confirm = window.getByTestId('skill-confirm-dialog');
    await expect(confirm).toBeVisible();
    await expect(confirm.getByTestId('skill-confirm-message')).toContainText(customName);
    await confirm.getByTestId('skill-confirm-ok').click();
    await expect(card).not.toBeVisible();
  } finally {
    await app.close();
  }
});

test('Skill 管理：内置 Skill 只读（无删除按钮）+ 内置 Agent 绑定禁用', async () => {
  const { app, window } = await launchApp();
  try {
    await gotoSkillCat(window);

    // 内置 seed Skill（architecture-methodology，#522 目录名 = 英文 slug）卡片存在，但无删除按钮（只读）
    const builtinCard = skillCard(window, 'architecture-methodology');
    await expect(builtinCard).toBeVisible();
    await expect(builtinCard.locator('[data-testid^="skill-source-builtin-"]')).toBeVisible();
    await expect(builtinCard.locator('[data-testid^="skill-delete-"]')).toHaveCount(0);

    // 上传对话框内：内置 Agent（写手）checkbox 禁用
    await window.getByTestId('skill-add-btn').click();
    const dialog = window.getByTestId('skill-upload-dialog');
    await expect(dialog).toBeVisible();
    const builtinAgent = window.getByTestId('skill-bind-agent-1');
    await expect(builtinAgent.locator('input')).toBeDisabled();
    await expect(builtinAgent).toContainText('内置只读');

    // 应用到全部：只勾非内置（内置仍禁用）——断言「全部非禁用 checkbox 被勾选」
    // （共享数据目录可能残留用例 2 的自定义 Agent，不断言绝对数量）
    const bindableCount = await window
      .locator('[data-testid^="skill-bind-agent-"] input[type="checkbox"]:not(:disabled)')
      .count();
    await window.getByTestId('skill-bind-all').click();
    const checked = await window
      .locator('[data-testid^="skill-bind-agent-"] input[type="checkbox"]:checked')
      .count();
    expect(checked).toBe(bindableCount);
  } finally {
    await app.close();
  }
});
