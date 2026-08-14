/**
});
  }
// 0.8.0 编排完全体 E2E 补测（#268 三态模型选择 / #269 执行顺序编辑 / #295-296 自定义角色）
// 契约源：components/AgentChainCard.tsx（data-testid 即契约）+ AgentChainCard.test.tsx（RTL）
// 三态 Select：角色行模型下拉（agent-model-select-<field>，开关开时条件渲染）——
//   null=关闭（Switch off）/ "__default__"=跟随默认 sentinel（Switch on 默认 / 下拉「跟随默认」）/
//   "<provider>/<model>"=指定模型（下拉选项）
// 执行顺序：agent-order-slot-<field> 槽位号 + agent-order-move-up/down-<field> 移动按钮
//   （首层上移/末层下移禁用）；移动写 config.agent_order 分层数组（[["a"],["b"]]），空层压缩
// 自定义角色：模板 roles 非四键 → 行 field=agent_<bareName>，显示名 role.name ?? 裸名，Sparkles 图标；
//   开关/下拉写 config.agent_roles（dict 浅合并，防丢其他自定义角色）
// 数据隔离：每用例独立 launchApp + 唯一项目名（E2E-<场景>-<ts>）；落库断言锚点 = 变更必变字段
//   （agent_* 三态值本身有区分度，直接轮询 GET /api/v1/projects/{id} 的 config 值，比 updated_at 强）
// ─────────────────────────────────────────────────────────────────────────────

/** 幂等确保 deepseek 配置含 deepseek-chat chat 模型（持久 DB 去重自愈，E3-2 模式）；须在进入 Agent 分类前调用 */
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


async function ensureDeepseekChatModel(kernel: KernelInfo): Promise<void> {
  const providers = await fetchKernel(kernel, '/api/v1/provider-configs');
  const deepseek = providers.items.find((p: { name: string }) => p.name === 'deepseek');
  expect(deepseek).toBeTruthy();
  const deduped = deepseek.models.filter(
    (m: { id: string }, i: number, arr: Array<{ id: string }>) =>
      m.id !== 'deepseek-chat' || arr.findIndex((x) => x.id === m.id) === i,
  );
  if (
    deduped.length !== deepseek.models.length ||
    !deepseek.models.some((m: { id: string }) => m.id === 'deepseek-chat')
  ) {
    await fetchKernel(kernel, `/api/v1/provider-configs/${deepseek.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        models: [...deduped, { id: 'deepseek-chat', type: 'chat', roles: [] }],
      }),
    });
  }
}

/** 预置含自定义角色的模板（#295/#296：roles 非四键 → 自定义行；researcher 带 name / editor 裸名回退） */
async function createCustomRoleTemplate(kernel: KernelInfo): Promise<{ id: string; name: string }> {
  const name = `E2E-CustomRole-${Date.now()}`;
  const tpl = await fetchKernel(kernel, '/api/v1/agent-templates', {
    method: 'POST',
    body: JSON.stringify({
      name,
      roles: {
        architect: { enabled: true },
        writer: { enabled: true },
        auditor: { enabled: true },
        reviser: { enabled: true },
        researcher: { enabled: true, name: '资料研究员', prompt: '你负责搜集资料' },
        editor: { enabled: true, name: null, prompt: '你负责润色' },
      },
    }),
  });
  return { id: String(tpl.id), name };
}

/** 经新建项目对话框选择 Agent 模板创建项目（e2e-projects 模板创建用例模式） */
async function createProjectWithTemplateViaUi(window: Page, name: string, tplName: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  await dlg.getByLabel('Agent 模板').click();
  await window.getByRole('option', { name: tplName, exact: true }).click();
  await window.getByLabel('书名').fill(name);
  await dlg.getByRole('button', { name: '创建', exact: true }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

// ─────────────────────────────────────────────────────────────────────────────
// A5-1 #268 三态模型选择：角色行模型下拉三值（跟随默认 / 指定模型 / 禁用）→ 内核落库
// ─────────────────────────────────────────────────────────────────────────────
});
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
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

test.describe.configure({ timeout: 120_000 });


// ────────────────────────────────────────────────────────────────
// F42 Agent 链 E2E（#268/#269/#295-296，2026-08-14）——从 e2e-settings.spec.ts 拆分（900 行护栏）
// #268 角色模型三态+重启保持 / #269 执行顺序+边界 / #295-296 自定义角色渲染+落库
// ────────────────────────────────────────────────────────────────
// ────────────────────────────────────────────────────────────────
// 5. 设置页：Agent 分类渲染（迁移自 Agent 页；agents 路由已删，spec §7.10 Q1=A）
// ────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────────────────
test('设置页：#268 角色模型三态 Select（跟随默认/指定模型/禁用）→ 内核 config.agent_writer 三值落库', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible();

    // 前置：UI 创建唯一项目 + deepseek-chat chat 模型（下拉选项数据源；幂等自愈）
    const name = `E2E-AgentTriState-${Date.now()}`;
    await createProjectViaUi(window, name);
    const list = await fetchKernel(kernel, '/api/v1/projects');
    const project = list.items.find((p: { name: string }) => p.name === name);
    expect(project).toBeTruthy();
    const projectId = project.id as string;
    await ensureDeepseekChatModel(kernel);

    // 设置页 → Agent 分类（首次挂载 loadProviders 拉最新模型列表）
    await gotoNav(window, '设置');
    await window.getByTestId('settings-cat-agent').click();
    const chain = window.getByTestId('agent-chain-card');
    await expect(chain).toBeVisible();
    const writer = chain.getByRole('switch', { name: 'Writer 执笔' });
    await expect(writer).not.toBeChecked(); // 新项目默认 agent_writer=null=关闭

    // 三态 1：Switch 开 → 默认「跟随默认」→ 落库 sentinel __default__
    await writer.click();
    await expect(writer).toBeChecked();
    const roleSelect = chain.getByTestId('agent-model-select-agent_writer');
    await expect(roleSelect).toBeVisible(); // 开关开 → 行内模型 Select 条件渲染
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_writer;
        },
        { timeout: 10_000 }
      )
      .toBe('__default__');

    // 三态 2：下拉选指定模型 → 落库 provider/model（option 为 Radix portal；first() 防持久 DB 重复选项）
    await roleSelect.click();
    await window.getByRole('option', { name: 'deepseek/deepseek-chat', exact: true }).first().click();
    await expect(roleSelect).toContainText('deepseek/deepseek-chat');
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_writer;
        },
        { timeout: 10_000 }
      )
      .toBe('deepseek/deepseek-chat');

    // 三态 2b：下拉切回「跟随默认」→ 落库回到 sentinel（Select 可逆）
    await roleSelect.click();
    await window.getByRole('option', { name: '跟随默认', exact: true }).click();
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_writer;
        },
        { timeout: 10_000 }
      )
      .toBe('__default__');

    // 三态 3：Switch 关（禁用）→ 落库显式 null + Select 卸载
    await writer.click();
    await expect(writer).not.toBeChecked();
    await expect(roleSelect).toHaveCount(0);
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

// ─────────────────────────────────────────────────────────────────────────────
// A5-2 #268 三态重启持久化（二次 launch 同 userData：后端权威 + UI 回显双断言）
// ─────────────────────────────────────────────────────────────────────────────
test('#268 三态指定模型 → 重启（二次 launch 同数据目录）→ 内核 config.agent_writer 保持 + UI 开关/下拉回显', async () => {
  test.setTimeout(240_000);
  const userDataDir = mkdtempSync(path.join(tmpdir(), 'inkflow-e2e-268-agent-'));
  const name = `E2E-AgentTriPersist-${Date.now()}`;
  let projectId: string;

  // ── 第一程：创建项目 → Writer 开 → 选 deepseek/deepseek-chat（落库 provider/model）──
  const first = await launchAppWithUserData(userDataDir);
  try {
    await first.window.evaluate(() => localStorage.clear());
    await first.window.reload();
    await expect(first.window.getByTestId('app-nav')).toBeVisible();
    await createProjectViaUi(first.window, name);
    const list = await fetchKernel(first.kernel, '/api/v1/projects');
    const project = list.items.find((p: { name: string }) => p.name === name);
    expect(project).toBeTruthy();
    projectId = project.id as string;
    await ensureDeepseekChatModel(first.kernel);

    await gotoNav(first.window, '设置');
    await first.window.getByTestId('settings-cat-agent').click();
    const chain = first.window.getByTestId('agent-chain-card');
    const writer = chain.getByRole('switch', { name: 'Writer 执笔' });
    await writer.click();
    await chain.getByTestId('agent-model-select-agent_writer').click();
    await first.window.getByRole('option', { name: 'deepseek/deepseek-chat', exact: true }).first().click();
    // 关闭前闸门：轮询内核确认落库（防 app.close() 与 fire-and-forget PATCH 竞态）
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(first.kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_writer;
        },
        { timeout: 10_000 }
      )
      .toBe('deepseek/deepseek-chat');
  } finally {
    await first.app.close();
  }

  // ── 第二程：复用同一数据目录重启 → 后端权威 + UI 状态双断言 ──
  const second = await launchAppWithUserData(userDataDir);
  try {
    // ① 后端权威（不依赖 UI 导航）：内核读同一 DB → agent_writer 仍为指定模型
    const r = await fetchKernel(second.kernel, `/api/v1/projects/${projectId}`);
    expect(r.config?.agent_writer).toBe('deepseek/deepseek-chat');

    // ② UI 回显：currentProjectId 为内存态 → 项目页卡片重选本项目 → Agent 分类
    await gotoNav(second.window, '项目');
    await second.window.getByTestId('project-card').filter({ hasText: name }).click();
    await expect(second.window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
    await gotoNav(second.window, '设置');
    await second.window.getByTestId('settings-cat-agent').click();
    const chain = second.window.getByTestId('agent-chain-card');
    await expect(chain.getByRole('switch', { name: 'Writer 执笔' })).toBeChecked();
    await expect(chain.getByTestId('agent-model-select-agent_writer')).toContainText('deepseek/deepseek-chat');
  } finally {
    await second.app.close();
  }

  try {
    rmSync(userDataDir, { recursive: true, force: true });
  } catch {
    // 临时目录清理失败（Windows 文件锁）不阻塞用例
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// A6-1 #269 执行顺序编辑：上移/下移 → 内核 config.agent_order 分层数组（移动后空层压缩）
// ─────────────────────────────────────────────────────────────────────────────
test('设置页：#269 执行顺序上移/下移 → 内核 config.agent_order 分层数组变化（空层压缩）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible();

    const name = `E2E-AgentOrder-${Date.now()}`;
    await createProjectViaUi(window, name);
    const list = await fetchKernel(kernel, '/api/v1/projects');
    const project = list.items.find((p: { name: string }) => p.name === name);
    expect(project).toBeTruthy();
    const projectId = project.id as string;

    await gotoNav(window, '设置');
    await window.getByTestId('settings-cat-agent').click();
    const chain = window.getByTestId('agent-chain-card');
    await expect(chain).toBeVisible();

    // 多角色开启（默认模板模式：config.agent_order 空，开关不写 order，B1 语义）
    await chain.getByRole('switch', { name: 'Writer 执笔' }).click();
    await chain.getByRole('switch', { name: 'Auditor 审校' }).click();

    // Writer 下移：并入 auditor 层（并行组）；writer 原层变空 → 压缩删除
    await chain.getByTestId('agent-order-move-down-agent_writer').click();
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_order;
        },
        { timeout: 10_000 }
      )
      .toEqual([
        ['agent_architect'],
        ['agent_auditor', 'agent_writer'],
        ['agent_reviser'],
      ]);

    // Writer 上移：并入 architect 层（并行组）→ UI 槽位号跟随更新
    await chain.getByTestId('agent-order-move-up-agent_writer').click();
    await expect(chain.getByTestId('agent-order-slot-agent_writer')).toHaveText('0');
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_order;
        },
        { timeout: 10_000 }
      )
      .toEqual([
        ['agent_architect', 'agent_writer'],
        ['agent_auditor'],
        ['agent_reviser'],
      ]);
  } finally {
    await app.close();
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// A6-2 #269 执行顺序边界：首层上移禁用 / 末层下移禁用（默认拓扑 0-3 槽位）
// ─────────────────────────────────────────────────────────────────────────────
test('设置页：#269 执行顺序边界（首层上移按钮禁用 / 末层下移按钮禁用）', async () => {
  const { app, window } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible();

    await createProjectViaUi(window, `E2E-AgentOrderBound-${Date.now()}`);
    await gotoNav(window, '设置');
    await window.getByTestId('settings-cat-agent').click();
    const chain = window.getByTestId('agent-chain-card');
    await expect(chain).toBeVisible();

    // 边界：architect=首层（上移禁用）/ reviser=末层（下移禁用）；中间层双向可用
    await expect(chain.getByTestId('agent-order-move-up-agent_architect')).toBeDisabled();
    await expect(chain.getByTestId('agent-order-move-down-agent_reviser')).toBeDisabled();
    await expect(chain.getByTestId('agent-order-move-up-agent_writer')).toBeEnabled();
    await expect(chain.getByTestId('agent-order-move-down-agent_writer')).toBeEnabled();

    // 槽位号显示（空 agent_order → 默认模板拓扑 0-3）
    await expect(chain.getByTestId('agent-order-slot-agent_architect')).toHaveText('0');
    await expect(chain.getByTestId('agent-order-slot-agent_reviser')).toHaveText('3');
  } finally {
    await app.close();
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// A7-1 #295/#296 自定义角色：模板 roles 非四键 → 自定义行（显示名 + Sparkles + 默认槽位 4+）
// ─────────────────────────────────────────────────────────────────────────────
test('设置页：#295/#296 自定义角色行渲染（显示名/裸名回退 + Sparkles 图标 + 4 内置后追加）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible();

    // 前置：内核 API 预置含自定义角色的模板（researcher 带 name / editor 无 name 回退裸名）
    const tpl = await createCustomRoleTemplate(kernel);
    // 经新建项目对话框选该模板创建（config.template_id 落库 → AgentChainCard 匹配模板渲染自定义行）
    const name = `E2E-AgentCustom-${Date.now()}`;
    await createProjectWithTemplateViaUi(window, name, tpl.name);

    await gotoNav(window, '设置');
    await window.getByTestId('settings-cat-agent').click();
    const chain = window.getByTestId('agent-chain-card');
    await expect(chain).toBeVisible();

    // 自定义行渲染：显示名 = role.name ?? 裸名；4 内置 + 2 自定义 = 6 开关
    await expect(chain.getByRole('switch', { name: '资料研究员' })).toBeVisible();
    await expect(chain.getByRole('switch', { name: 'editor' })).toBeVisible();
    await expect(chain.getByRole('switch')).toHaveCount(6);

    // Sparkles 图标（自定义行 icon 渲染；行内唯一 svg——Switch/移动按钮均无 svg）
    const researcherRow = chain.getByRole('switch', { name: '资料研究员' }).locator('xpath=..');
    await expect(researcherRow.locator('svg')).toHaveCount(1);

    // 默认槽位：自定义角色 = 4 + roles 顺序索引（researcher=4 / editor=5）
    await expect(chain.getByTestId('agent-order-slot-agent_researcher')).toHaveText('4');
    await expect(chain.getByTestId('agent-order-slot-agent_editor')).toHaveText('5');
  } finally {
    await app.close();
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// A7-2 #295/#296 自定义角色三态 + agent_roles 浅合并落库（开/选模型/关 → 内核 config.agent_roles）
// ─────────────────────────────────────────────────────────────────────────────
test('设置页：#295/#296 自定义角色三态（开/选模型/关）→ 内核 config.agent_roles 落库（dict 浅合并）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    await window.evaluate(() => localStorage.clear());
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible();

    const tpl = await createCustomRoleTemplate(kernel);
    const name = `E2E-AgentCustomTri-${Date.now()}`;
    await createProjectWithTemplateViaUi(window, name, tpl.name);
    const list = await fetchKernel(kernel, '/api/v1/projects');
    const project = list.items.find((p: { name: string }) => p.name === name);
    expect(project).toBeTruthy();
    const projectId = project.id as string;
    await ensureDeepseekChatModel(kernel);

    await gotoNav(window, '设置');
    await window.getByTestId('settings-cat-agent').click();
    const chain = window.getByTestId('agent-chain-card');
    await expect(chain).toBeVisible();
    const researcher = chain.getByRole('switch', { name: '资料研究员' });
    await expect(researcher).not.toBeChecked(); // 新项目 agent_roles 缺省 → 自定义角色关闭

    // 三态 1：自定义开关开 → agent_roles[agent_researcher] = sentinel __default__（写 dict 非顶层）
    await researcher.click();
    await expect(researcher).toBeChecked();
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_roles?.agent_researcher;
        },
        { timeout: 10_000 }
      )
      .toBe('__default__');

    // 三态 2：下拉选指定模型 → agent_roles[agent_researcher] = provider/model
    await chain.getByTestId('agent-model-select-agent_researcher').click();
    await window.getByRole('option', { name: 'deepseek/deepseek-chat', exact: true }).first().click();
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_roles?.agent_researcher;
        },
        { timeout: 10_000 }
      )
      .toBe('deepseek/deepseek-chat');

    // 浅合并：第二个自定义角色（editor）开启 → researcher 值保留（agent_roles 非整体覆盖）
    await chain.getByRole('switch', { name: 'editor' }).click();
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_roles;
        },
        { timeout: 10_000 }
      )
      .toEqual({
        agent_researcher: 'deepseek/deepseek-chat',
        agent_editor: '__default__',
      });

    // 三态 3：自定义开关关 → agent_roles[agent_researcher] = 显式 null（editor 值保留）
    await researcher.click();
    await expect(researcher).not.toBeChecked();
    await expect
      .poll(
        async () => {
          const r = await fetchKernel(kernel, `/api/v1/projects/${projectId}`);
          return r.config?.agent_roles;
        },
        { timeout: 10_000 }
      )
      .toEqual({
        agent_researcher: null,
        agent_editor: '__default__',
      });
  } finally {
    await app.close();
  }
});
