/**
 * 0.8.0 #298 写作页管线化 E2E（全自动/续写 → PipelineStatus 状态流转 → 成品落章）
 *
 * 覆盖 spec §5.6「GUI 写作入口管线化」（usePipeline.ts 契约）：
 * - 全自动 = 工具栏「生成」按钮（aria-label=write.toolbar.generate='生成'）→ start('write_auto')
 * - 续写   = 工具栏「续写」按钮（aria-label=write.toolbar.continue='续写'）→ start('write_continue')
 * - 状态机 idle → running → success | failed 经 pipeline-status（data-testid）四态文案：
 *   running='执行中' / success='生成完成' / failed='生成失败: {message}' / idle（i18n zh.ts 契约）
 * - 成品落章：getExecutionStatus completed → chapterStore.setContent(final_output)
 *   → 编辑器（chapter-editor textarea）内容 = final_output
 *
 * ⚠️ 真实 LLM 依赖（GUI 经真实内核 HTTP：POST /api/v1/agent/pipelines/execute → 202 +
 *    execution_id → 1s 间隔轮询 GET /api/v1/agent/pipelines/executions/{id}）：
 * 每个用例开头 `test.skip(!process.env.INKFLOW_LLM_KEY, ...)` —— CI 默认（无 key）skip 不 fail，
 * label 触发时 secrets 注入后真实跑（ADR-026「缺 key 永远 skip 不 fail」哲学，e2e-ai-backend 同源）。
 * LLM 断言宽松（final_output 非空 + 编辑器落章 = final_output），不断言质量/字数
 * （test_writing_generate.py `assert result.content.strip()` 哲学）。
 *
 * LLM key 注入（真实内核 API，Node fetch + X-InkFlow-Token 头；与 e2e-writing 的 kernelFetch 同构）：
 * provider/model 由 tests/e2e/e2e-llm.config.ts 默认（deepseek/deepseek-v4-flash），
 * INKFLOW_E2E_LLM_PROVIDER / INKFLOW_E2E_LLM_MODEL env 优先覆盖（缺省读配置）：
 * 1. POST /api/v1/settings/llm-keys {provider: cfg.provider, api_key}
 *    —— settings.py LLMKeyStoreRequest（provider/api_key 必填非空），201 {provider, status:'saved'}
 * 2. GET /api/v1/provider-configs → 按 name=cfg.provider 找 seed provider（id 勿硬编码）→
 *    PATCH /api/v1/provider-configs/{id} {models: 去重后 chat 模型列表}
 *    —— ProviderConfigUpdate.models 整体替换语义（先读后合并）；补配置模型 chat 条目
 * 3. GET /api/v1/projects/{id} 合并 config → PATCH {config:{model, agent_*: cfg.model}}
 *    —— ⚠️ 后端实证（agent_service._merge_role_configs）：管线角色模型链 =
 *       模板 role model（builtin write_auto/continue 引用 config.llm_default_model）→ 项目 agent_* 覆盖；
 *       config.model 不参与管线路由 → 只 PATCH config.model 会拿默认模型打无 key 的
 *       provider 必然失败。必须 agent_architect/writer/auditor/reviser 全部覆盖为 cfg.model。
 *       config 整体替换语义（ProjectUpdate.config 为完整 ProjectConfig）→ 先 GET 合并再 PATCH。
 *
 * 运行方式（只 tsc 类型检查见 inkflow-e2e-testing skill；真跑需 build + key）：
 *   cd frontend
 *   pnpm --filter renderer build && pnpm --filter inkflow-electron build
 *   $env:INKFLOW_LLM_KEY = '<deepseek key>'   # 应为 deepseek 平台 key（deepseek-v4-flash）
 *   pnpm --filter inkflow-electron test:e2e e2e-pipeline-ai.spec.ts
 *
 * 基建：launchApp/waitKernelInfo/readKernelInfo/kernelFetch/createProjectViaUi/gotoNav/findProjectId
 * 复制自 e2e-writing.spec.ts（spec 自包含，不跨文件 import）。
 */
import path from 'node:path';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';
import { resolveE2eLlmConfig } from './e2e-llm.config';

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

/**
 * 通过 UI 创建项目：new-project-btn → 对话框填书名 → 「创建」。
 * 契约：创建成功 → navigate('/writing')，等待写作页 project-tree 出现。
 */
async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  // getByLabel 通过关联 label / aria-label 查找（dialog 内唯一）
  await window.getByLabel('书名').fill(name);
  // #595 契约：创建须 ≥1 个题材/标签（tags 多选勾选预设标签；Radix option 渲染于 portal，用 window 级查询）
  await window.getByTestId('tags-select').click();
  await window.getByRole('option', { name: '玄幻' }).click();
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

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置；NavLink 与 Agent 快捷 Link 均为 role=link） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

// ────────────────────────────────────────────────────────────────
// LLM 预置 helper（真实内核 API；宽松断言哲学：只验状态码，不验响应细节）
// ────────────────────────────────────────────────────────────────

/**
 * 预置 LLM 环境：provider/model 由 e2e-llm.config.ts 默认 + INKFLOW_E2E_LLM_* env 覆盖，
 * 注册 provider key + 补配置 chat 模型 + 项目模型路由。
 *
 * 项目路由必须是 agent_* 四角色全覆盖为配置模型（后端实证见文件头注释）：
 * builtin write_auto/continue 模板角色模型引用 config.llm_default_model，仅项目 agent_*
 * 非空（且含 '/'）时覆盖；config.model 不参与管线模型解析。
 */
async function setupLlmForProject(kernel: KernelInfo, projectId: string): Promise<void> {
  const cfg = resolveE2eLlmConfig();
  // 1. 注册 provider key（APIKeyManager AES-256-GCM 加密存储；201 {provider, status:'saved'}）
  const key = process.env.INKFLOW_LLM_KEY as string;
  const keyRes = await kernelFetch(kernel, '/api/v1/settings/llm-keys', {
    method: 'POST',
    body: { provider: cfg.provider, api_key: key },
  });
  expect(keyRes.ok, `${cfg.provider} key 注册（POST /settings/llm-keys）应成功`).toBe(true);

  // 2. provider seed 补 chat 模型（id 从 GET 列表取，勿硬编码；models 整体替换 → 先读后合并去重）
  const pcRes = await kernelFetch(kernel, '/api/v1/provider-configs');
  expect(pcRes.ok).toBe(true);
  const pcs = (await pcRes.json()) as {
    items: Array<{
      id: number;
      name: string;
      models: Array<{ id: string; type: string }>;
    }>;
  };
  const provider = pcs.items.find((p) => p.name === cfg.provider);
  expect(provider, `seed provider ${cfg.provider} 应存在（全新库 seed 4 provider）`).toBeTruthy();
  const modelId = cfg.model.split('/')[1];
  const existing = provider!.models ?? [];
  const models = existing.some((m) => m.id === modelId && m.type === 'chat')
    ? existing
    : [...existing, { id: modelId, type: 'chat' }];
  const modelRes = await kernelFetch(kernel, `/api/v1/provider-configs/${provider!.id}`, {
    method: 'PATCH',
    body: { models },
  });
  expect(modelRes.ok, `${cfg.provider} provider-configs PATCH（补 chat 模型）应成功`).toBe(true);

  // 3. 项目 config：model + 四角色 agent_* → 配置模型（config 整体替换 → 先 GET 合并）
  await setProjectRoleModels(kernel, projectId, cfg.model, { model: cfg.model });
}

/**
 * PATCH 项目 config 角色模型（config 整体替换语义 → 先 GET 合并）。
 * extra 可附带 config.model 等其它字段（整体替换时一起写入）。
 */
async function setProjectRoleModels(
  kernel: KernelInfo,
  projectId: string,
  roleModel: string,
  extra?: Record<string, unknown>
): Promise<void> {
  const getRes = await kernelFetch(kernel, `/api/v1/projects/${projectId}`);
  expect(getRes.ok).toBe(true);
  const project = (await getRes.json()) as { config: Record<string, unknown> };
  const config: Record<string, unknown> = {
    ...(project.config ?? {}),
    agent_architect: roleModel,
    agent_writer: roleModel,
    agent_auditor: roleModel,
    agent_reviser: roleModel,
    ...extra,
  };
  const patchRes = await kernelFetch(kernel, `/api/v1/projects/${projectId}`, {
    method: 'PATCH',
    body: { config },
  });
  expect(patchRes.ok, '项目 config PATCH（agent_* 角色模型）应成功').toBe(true);
}

/** 轮询项目执行列表取最新 execution_id（execute 202 返回前同步落库，宽松：仅取第一条） */
async function waitExecutionId(
  kernel: KernelInfo,
  projectId: string,
  timeoutMs = 30_000
): Promise<string> {
  let executionId = '';
  await expect
    .poll(
      async () => {
        const res = await kernelFetch(
          kernel,
          `/api/v1/agent/pipelines/executions?project_id=${projectId}&limit=5`
        );
        if (!res.ok) return null;
        const data = (await res.json()) as { items: Array<{ execution_id: string }> };
        if (data.items.length === 0) return null;
        executionId = data.items[0].execution_id;
        return executionId;
      },
      { timeout: timeoutMs, message: '管线执行记录应已创建（POST /pipelines/execute 202）' }
    )
    .toBeTruthy();
  return executionId;
}

/** 轮询执行终态：completed 且 final_output 非空 → 返回 final_output（宽松断言哲学） */
async function pollExecutionResult(
  kernel: KernelInfo,
  executionId: string,
  timeoutMs = 60_000
): Promise<string> {
  let finalOutput = '';
  await expect
    .poll(
      async () => {
        const res = await kernelFetch(
          kernel,
          `/api/v1/agent/pipelines/executions/${executionId}`
        );
        if (!res.ok) return null;
        const data = (await res.json()) as { status: string; final_output: string };
        if (data.status !== 'completed' || data.final_output.trim() === '') return null;
        finalOutput = data.final_output;
        return finalOutput;
      },
      { timeout: timeoutMs, message: `执行 ${executionId} 应 completed 且 final_output 非空` }
    )
    .toBeTruthy();
  return finalOutput;
}

// 真实 LLM 管线 4 阶段（architect→writer→auditor→reviser）串行调用，慢环境单条可能数分钟
test.describe.configure({ timeout: 3_600_000 });

// ────────────────────────────────────────────────────────────────
// B1-1 全自动管线：点「生成」→ running → success → 成品落章
// ────────────────────────────────────────────────────────────────
test('B1-1 全自动管线：点「生成」→ pipeline-status 执行中→生成完成 → 成品落章', async () => {
  test.skip(!process.env.INKFLOW_LLM_KEY, '需要真实 LLM key（INKFLOW_LLM_KEY 环境变量）');
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-管线-自动-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 预置空章节（全自动不依赖前文）+ LLM key 注入 + 模型路由
    const chRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: 'AI 管线测试章', content: '' },
    });
    expect(chRes.status).toBe(201);
    await setupLlmForProject(kernel, pid);

    // 重挂载写作页触发 loadChapterTree → 选中章节（编辑器空正文）
    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible();
    const tree = window.getByTestId('project-tree');
    await tree.getByRole('button', { name: /AI 管线测试章/ }).click();
    const editor = window.getByTestId('chapter-editor');
    await expect(editor).toHaveValue('');

    // 点「全自动」（工具栏「生成」按钮 aria-label=write.toolbar.generate）→ 状态机 running → success
    const toolbar = window.getByTestId('editor-toolbar');
    await toolbar.getByRole('button', { name: '生成', exact: true }).click();
    const status = window.getByTestId('pipeline-status');
    await expect(status).toContainText('执行中', { timeout: 15_000 });
    await expect(status).toContainText('生成完成', { timeout: 900_000 });

    // 成品落章（宽松断言：final_output 非空 + 编辑器 = final_output，不断言质量/字数）
    const executionId = await waitExecutionId(kernel, pid);
    const finalOutput = await pollExecutionResult(kernel, executionId, 60_000);
    expect(finalOutput.trim().length).toBeGreaterThan(0);
    await expect(editor).toHaveValue(finalOutput, { timeout: 15_000 });
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// B1-2 续写管线：点「续写」→ success → 成品落章（final_output 非空 + 内容已变更）
// ────────────────────────────────────────────────────────────────
test('B1-2 续写管线：点「续写」→ pipeline-status 生成完成 → 成品落章', async () => {
  test.skip(!process.env.INKFLOW_LLM_KEY, '需要真实 LLM key（INKFLOW_LLM_KEY 环境变量）');
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-管线-续写-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 预置带前文的章节（续写 variables.context = chapterStore.content）+ LLM 注入
    const seedContent = `前文：主角踏入试炼场，第一次面对魔兽。${Date.now() % 100000}`;
    const chRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '续写测试章', content: seedContent },
    });
    expect(chRes.status).toBe(201);
    await setupLlmForProject(kernel, pid);

    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible();
    await window
      .getByTestId('project-tree')
      .getByRole('button', { name: /续写测试章/ })
      .click();
    const editor = window.getByTestId('chapter-editor');
    await expect(editor).toHaveValue(seedContent);

    // 点「续写」→ 状态机 running → success
    const toolbar = window.getByTestId('editor-toolbar');
    await toolbar.getByRole('button', { name: '续写', exact: true }).click();
    const status = window.getByTestId('pipeline-status');
    await expect(status).toContainText('执行中', { timeout: 15_000 });
    await expect(status).toContainText('生成完成', { timeout: 900_000 });

    // 成品落章（宽松断言：final_output 非空 + 编辑器 = final_output + 内容已变更）
    const executionId = await waitExecutionId(kernel, pid);
    const finalOutput = await pollExecutionResult(kernel, executionId, 60_000);
    expect(finalOutput.trim().length).toBeGreaterThan(0);
    expect(finalOutput).not.toBe(seedContent);
    await expect(editor).toHaveValue(finalOutput, { timeout: 15_000 });
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// B1-3 并发保护：running 中再触发 → AI 按钮 disabled + 内核仅 1 条执行记录
// ────────────────────────────────────────────────────────────────
test('B1-3 并发保护：running 中再触发 → AI 按钮 disabled + 内核仅 1 条执行记录', async () => {
  test.skip(!process.env.INKFLOW_LLM_KEY, '需要真实 LLM key（INKFLOW_LLM_KEY 环境变量）');
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-管线-并发-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    const chRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '并发保护测试章', content: '' },
    });
    expect(chRes.status).toBe(201);
    await setupLlmForProject(kernel, pid);

    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible();
    await window
      .getByTestId('project-tree')
      .getByRole('button', { name: /并发保护测试章/ })
      .click();
    await expect(window.getByTestId('chapter-editor')).toHaveValue('');

    const toolbar = window.getByTestId('editor-toolbar');
    const generateBtn = toolbar.getByRole('button', { name: '生成', exact: true });
    const continueBtn = toolbar.getByRole('button', { name: '续写', exact: true });

    // 第一次触发：全自动 → running
    await generateBtn.click();
    const status = window.getByTestId('pipeline-status');
    await expect(status).toContainText('执行中', { timeout: 15_000 });

    // UI 闸门：running 中 AI 按钮 disabled（EditorToolbar disabled={generating}，writing.tsx 实证）
    await expect(generateBtn).toBeDisabled();
    await expect(continueBtn).toBeDisabled();

    // 键盘路径绕过 disabled 按钮直调 start('write_auto')（Ctrl+Shift+Enter）→ inFlightRef 守卫应无操作
    await window.getByTestId('chapter-editor').focus();
    await window.keyboard.press('Control+Shift+Enter');

    // 内核实证：仅 1 条执行记录（二次触发未创建第二条执行）
    await expect
      .poll(
        async () => {
          const res = await kernelFetch(
            kernel,
            `/api/v1/agent/pipelines/executions?project_id=${pid}&limit=20`
          );
          if (!res.ok) return -1;
          const data = (await res.json()) as { total: number };
          return data.total;
        },
        { timeout: 30_000, message: '并发保护：重复触发不应产生第二条执行记录' }
      )
      .toBe(1);

    // 首条执行正常完成 → 成品落章
    await expect(status).toContainText('生成完成', { timeout: 900_000 });
    const executionId = await waitExecutionId(kernel, pid);
    const finalOutput = await pollExecutionResult(kernel, executionId, 60_000);
    expect(finalOutput.trim().length).toBeGreaterThan(0);
    await expect(window.getByTestId('chapter-editor')).toHaveValue(finalOutput, {
      timeout: 15_000,
    });
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// B1-4 失败态：角色模型指向无 key 的 provider → 全自动 → pipeline-status 生成失败（不落章）
// ────────────────────────────────────────────────────────────────
test('B1-4 失败态：模型指向无 key provider → 点「生成」→ pipeline-status 生成失败', async () => {
  test.skip(!process.env.INKFLOW_LLM_KEY, '需要真实 LLM key（INKFLOW_LLM_KEY 环境变量）');
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-管线-失败-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    const chRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '失败态测试章', content: '' },
    });
    expect(chRes.status).toBe(201);

    // 角色模型指向「无任何 key 的 provider」→ get_provider_config 全 key 源缺失 → ValueError
    // → 阶段重试耗尽 → PipelineError → 执行 failed（provider_config.py 契约；env 名含唯一后缀
    // 天然规避本地 INKFLOW_*_API_KEY 残留，确定性失败；不注册 key，不消耗真实调用）
    const noKeyModel = `e2e-nokey-${Date.now() % 100000}/no-such-model`;
    await setProjectRoleModels(kernel, pid, noKeyModel);

    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible();
    await window
      .getByTestId('project-tree')
      .getByRole('button', { name: /失败态测试章/ })
      .click();
    await expect(window.getByTestId('chapter-editor')).toHaveValue('');

    // 点「全自动」→ failed 态（write.pipeline.failed='生成失败: {message}' 前缀，宽松断言前缀）
    const toolbar = window.getByTestId('editor-toolbar');
    await toolbar.getByRole('button', { name: '生成', exact: true }).click();
    const status = window.getByTestId('pipeline-status');
    await expect(status).toContainText('生成失败', { timeout: 900_000 });

    // 失败不落章：编辑器保持原内容（空）
    await expect(window.getByTestId('chapter-editor')).toHaveValue('');
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// B1-5 HITL 确认流（#343）：项目 config.supervisor.hitl_roles=['reviser']
//   → 点「生成」→ supervisor 管线 → 执行到 reviser 前 interrupt → 内联确认卡片
//   → 点「继续执行」→ resume → 成品落章
// ────────────────────────────────────────────────────────────────
test('B1-5 HITL 确认流：supervisor 管线 → 确认卡片 → 继续执行 → 成品落章', async () => {
  test.skip(!process.env.INKFLOW_LLM_KEY, '需要真实 LLM key（INKFLOW_LLM_KEY 环境变量）');
  test.skip(!process.env.INKFLOW_LLM_DEFAULT_MODEL, '需要 INKFLOW_LLM_DEFAULT_MODEL（supervisor 决策模型）');
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-管线-HITL-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    const chRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: 'HITL 测试章', content: '' },
    });
    expect(chRes.status).toBe(201);

    // LLM 预置：zhipu key + 角色模型全覆盖 + 项目 config.supervisor（#343 拍板 2A）
    await setupLlmForProject(kernel, pid);
    const getRes = await kernelFetch(kernel, `/api/v1/projects/${pid}`);
    expect(getRes.ok).toBe(true);
    const project = (await getRes.json()) as { config: Record<string, unknown> };
    const patchRes = await kernelFetch(kernel, `/api/v1/projects/${pid}`, {
      method: 'PATCH',
      body: {
        config: {
          ...(project.config ?? {}),
          supervisor: { hitl_roles: ['reviser'] },
        },
      },
    });
    expect(patchRes.ok, '项目 config PATCH（supervisor.hitl_roles）应成功').toBe(true);

    // 前端 project store 是启动时快照 → reload 让 usePipeline 读到 supervisor 配置
    await window.reload();
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });
    await gotoNav(window, '项目');
    // 等待项目列表加载完成（loadProjects 异步——projects 页挂载才触发；确保 config.supervisor 进入 store）
    await expect(window.getByTestId('project-card').first()).toBeVisible({ timeout: 15_000 });
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible();
    await window
      .getByTestId('project-tree')
      .getByRole('button', { name: /HITL 测试章/ })
      .click();
    await expect(window.getByTestId('chapter-editor')).toHaveValue('');

    // 点「生成」→ supervisor 管线 → 执行到 reviser 前 interrupt → 内联确认卡片
    const toolbar = window.getByTestId('editor-toolbar');
    await toolbar.getByRole('button', { name: '生成', exact: true }).click();
    const confirmCard = window.getByTestId('hitl-confirm-card');
    await expect(confirmCard).toBeVisible({ timeout: 900_000 });
    await expect(confirmCard).toContainText('确认执行下一角色');

    // 点「继续执行」→ resume → 完成 → 成品落章
    await window.getByTestId('hitl-confirm-approve').click();
    const status = window.getByTestId('pipeline-status');
    await expect(status).toContainText('生成完成', { timeout: 900_000 });

    // 成品落章（宽松断言：final_output 非空 + 编辑器 = final_output）
    const executionId = await waitExecutionId(kernel, pid);
    const finalOutput = await pollExecutionResult(kernel, executionId, 60_000);
    expect(finalOutput.trim().length).toBeGreaterThan(0);
    await expect(window.getByTestId('chapter-editor')).toHaveValue(finalOutput, {
      timeout: 15_000,
    });
  } finally {
    await app.close();
  }
});
