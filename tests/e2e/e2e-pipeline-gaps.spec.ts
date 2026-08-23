/**
 * 0.9.0 #366 writing pipeline e2e gaps（G1-G4）——设定驱动写作 + 多章串行 + 续写连贯 + 大纲驱动
 *
 * 覆盖 issue #366 四个产品旅程缺口：
 * - G1 设定驱动写作（P0）：管线 prompt 注入设定库摘要（角色/世界观/大纲）→
 *   预置设定 → 点「生成」→ final_output 含设定要素（后端 _assemble_setting_context
 *   variables["setting"] + 模板 {setting} 占位符，G1 能力 + E2E 双验证）
 * - G2 多章串行（P1）：连续生成第 1→2 章（2 章上限控时长）——章节树新章 +
 *   每章落库 + 前文传递（第 2 章续写 context 由后端从第 1 章生成摘要，#318）
 * - G3 续写连贯（P2）：前文含独特主角名 → 续写 → final_output 含该主角名
 * - G4 大纲驱动（P2）：先建大纲（level=chapter + chapter_id 关联写作章节）→
 *   AI 按大纲写指定章 → final_output 含大纲要素
 *
 * ⚠️ 真实 LLM 依赖（同 e2e-pipeline-ai.spec.ts 哲学）：每个用例开头
 * `test.skip(!process.env.INKFLOW_LLM_KEY, ...)`——CI 默认（无 key）skip 不 fail；
 * 真实跑时轮询 900s / describe 3600s（实测：write_auto 4 阶段 ~7.5m、
 * write_continue 3 阶段 ~4.5m，见 e2e-pipeline-ai-contract.md 时间预算节）。
 *
 * LLM 断言宽松（概率性）：G1 断言「角色名或世界观名之一出现在 final_output」
 * （二选一提高稳定性）；G3 断言前文主角名出现；G4 断言大纲名或描述关键词出现。
 *
 * 运行方式（真实跑需 build + key）：
 *   cd frontend
 *   pnpm --filter renderer build && pnpm --filter inkflow-electron build
 *   $env:INKFLOW_LLM_KEY = '<deepseek key>'   # 应为 deepseek 平台 key（deepseek-v4-flash）
 *   pnpm --filter inkflow-electron test:e2e e2e-pipeline-gaps
 *   或隔离数据目录：workspace\scripts\run-e2e-isolated.ps1 -Spec e2e-pipeline-gaps.spec.ts
 *
 * 基建：launchApp/waitKernelInfo/readKernelInfo/kernelFetch/createProjectViaUi/
 * findProjectId/gotoNav/setupLlmForProject/setProjectRoleModels/waitExecutionId/
 * pollExecutionResult 复制自 e2e-pipeline-ai.spec.ts（spec 自包含，不跨文件 import）。
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

/** 通过 UI 创建项目：new-project-btn → 对话框填书名 → 「创建」。 */
async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
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

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

// ────────────────────────────────────────────────────────────────
// LLM 预置 helper（真实内核 API；宽松断言哲学：只验状态码）
// ────────────────────────────────────────────────────────────────

/**
 * 预置 LLM 环境：provider/model 由 e2e-llm.config.ts 默认 + INKFLOW_E2E_LLM_* env 覆盖，
 * 注册 provider key + 补配置 chat 模型 + 项目模型路由。
 * 项目路由必须是 agent_* 四角色全覆盖为配置模型（后端实证见 e2e-pipeline-ai.spec.ts
 * 文件头：builtin write_auto/continue 模板角色模型引用 config.llm_default_model，仅项目
 * agent_* 非空（且含 '/'）时覆盖；config.model 不参与管线模型解析）。
 */
async function setupLlmForProject(kernel: KernelInfo, projectId: string): Promise<void> {
  const cfg = resolveE2eLlmConfig();
  const key = process.env.INKFLOW_LLM_KEY as string;
  const keyRes = await kernelFetch(kernel, '/api/v1/settings/llm-keys', {
    method: 'POST',
    body: { provider: cfg.provider, api_key: key },
  });
  expect(keyRes.ok, `${cfg.provider} key 注册（POST /settings/llm-keys）应成功`).toBe(true);

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

// ────────────────────────────────────────────────────────────────
// 设定库预置 helper（G1/G4：角色/世界观/大纲 经内核 API）
// ────────────────────────────────────────────────────────────────

/** 预置角色（CharacterCreate: name/personality/background/goals） */
async function presetCharacter(
  kernel: KernelInfo,
  projectId: string,
  name: string,
  personality: string
): Promise<void> {
  const res = await kernelFetch(kernel, `/api/v1/projects/${projectId}/characters`, {
    method: 'POST',
    body: { name, personality },
  });
  expect(res.status, `角色「${name}」创建应 201`).toBe(201);
}

/** 预置世界观条目（WorldSettingCreate: name/category/content） */
async function presetWorldSetting(
  kernel: KernelInfo,
  projectId: string,
  name: string,
  content: string
): Promise<void> {
  const res = await kernelFetch(kernel, `/api/v1/projects/${projectId}/world-settings`, {
    method: 'POST',
    body: { name, content },
  });
  expect(res.status, `世界观「${name}」创建应 201`).toBe(201);
}

/** 预置大纲（OutlineCreate: name/description/level/chapter_id）——G4 大纲驱动 */
async function presetOutline(
  kernel: KernelInfo,
  projectId: string,
  name: string,
  description: string,
  chapterId?: string
): Promise<void> {
  const res = await kernelFetch(kernel, `/api/v1/projects/${projectId}/outlines`, {
    method: 'POST',
    body: {
      name,
      description,
      level: chapterId ? 'chapter' : 'overall',
      ...(chapterId ? { chapter_id: chapterId } : {}),
    },
  });
  expect(res.status, `大纲「${name}」创建应 201`).toBe(201);
}

/** UI 新建章节：树底部「+ 新建章节」→ 输入标题 → Enter */
async function createChapterViaUi(window: Page, title: string): Promise<void> {
  await window.getByRole('button', { name: /新建章节/ }).click();
  const titleInput = window.getByPlaceholder('新建章节', { exact: true });
  await titleInput.fill(title);
  await titleInput.press('Enter');
}

/** 点击「生成」→ 等待管线 completed → 返回 final_output（轮询 900s 预算） */
async function runWriteAuto(
  window: Page,
  kernel: KernelInfo,
  projectId: string
): Promise<string> {
  const toolbar = window.getByTestId('editor-toolbar');
  await toolbar.getByRole('button', { name: '生成', exact: true }).click();
  const status = window.getByTestId('pipeline-status');
  await expect(status).toContainText('执行中', { timeout: 15_000 });
  await expect(status).toContainText('生成完成', { timeout: 900_000 });
  const executionId = await waitExecutionId(kernel, projectId);
  const finalOutput = await pollExecutionResult(kernel, executionId, 60_000);
  expect(finalOutput.trim().length).toBeGreaterThan(0);
  return finalOutput;
}

/** 点击「续写」→ 等待管线 completed → 返回 final_output（轮询 900s 预算） */
async function runWriteContinue(
  window: Page,
  kernel: KernelInfo,
  projectId: string
): Promise<string> {
  const toolbar = window.getByTestId('editor-toolbar');
  await toolbar.getByRole('button', { name: '续写', exact: true }).click();
  const status = window.getByTestId('pipeline-status');
  await expect(status).toContainText('执行中', { timeout: 15_000 });
  await expect(status).toContainText('生成完成', { timeout: 900_000 });
  const executionId = await waitExecutionId(kernel, projectId);
  const finalOutput = await pollExecutionResult(kernel, executionId, 60_000);
  expect(finalOutput.trim().length).toBeGreaterThan(0);
  return finalOutput;
}

// 真实 LLM 管线串行调用：G1 ~7.5m + G2 双段 ~12m + G3 ~4.5m + G4 ~7.5m ≈ 32m
test.describe.configure({ timeout: 3_600_000 });

// ────────────────────────────────────────────────────────────────
// G1 设定驱动写作：预置设定（角色/世界观）→ 生成 → 输出含设定要素
// ────────────────────────────────────────────────────────────────
test('G1 设定驱动：预置角色+世界观 → 点「生成」→ final_output 含设定要素', async () => {
  test.skip(!process.env.INKFLOW_LLM_KEY, '需要真实 LLM key（INKFLOW_LLM_KEY 环境变量）');
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-管线-G1-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 预置空章节 + 设定库（角色名/世界观名唯一化，断言宽松二选一）
    const chRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '设定驱动测试章', content: '' },
    });
    expect(chRes.status).toBe(201);
    const charName = `林晚${Date.now() % 100000}`;
    const worldName = `天玄大陆${Date.now() % 100000}`;
    await presetCharacter(kernel, pid, charName, '性格冷静，擅长谋略，是故事的绝对主角');
    await presetWorldSetting(kernel, pid, worldName, '灵气复苏的修真世界，宗门林立，以剑修为主流');
    await setupLlmForProject(kernel, pid);

    // 重挂载写作页选中章节（编辑器空正文）
    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible();
    await window
      .getByTestId('project-tree')
      .getByRole('button', { name: /设定驱动测试章/ })
      .click();
    await expect(window.getByTestId('chapter-editor')).toHaveValue('');

    // 生成 → completed → 断言设定要素出现在成品（宽松：角色名或世界观名之一）
    const finalOutput = await runWriteAuto(window, kernel, pid);
    const hitChar = finalOutput.includes(charName);
    const hitWorld = finalOutput.includes(worldName);
    expect(
      hitChar || hitWorld,
      `设定驱动：final_output 应含设定要素（角色「${charName}」或世界观「${worldName}」之一）`
    ).toBe(true);

    // 成品落章（编辑器 = final_output）
    await expect(window.getByTestId('chapter-editor')).toHaveValue(finalOutput, {
      timeout: 15_000,
    });
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// G2 多章串行：第 1 章生成 → UI 新建第 2 章 → 续写（前文传递）→ 章节树 2 章 + 落库
// ────────────────────────────────────────────────────────────────
test('G2 多章串行：生成第 1 章 → 新建第 2 章 → 续写 → 章节树 2 章 + 每章落库', async () => {
  test.skip(!process.env.INKFLOW_LLM_KEY, '需要真实 LLM key（INKFLOW_LLM_KEY 环境变量）');
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-管线-G2-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 第 1 章：空章 → 生成（write_auto 4 阶段）
    const ch1Title = `第一章${Date.now() % 100000}`;
    const ch1Res = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: ch1Title, content: '' },
    });
    expect(ch1Res.status).toBe(201);
    await setupLlmForProject(kernel, pid);

    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible();
    await window
      .getByTestId('project-tree')
      .getByRole('button', { name: new RegExp(ch1Title) })
      .click();
    await expect(window.getByTestId('chapter-editor')).toHaveValue('');

    // 第 1 章生成完成 → 落章
    const ch1Output = await runWriteAuto(window, kernel, pid);
    await expect(window.getByTestId('chapter-editor')).toHaveValue(ch1Output, {
      timeout: 15_000,
    });

    // UI 新建第 2 章（树联动：新节点 data-current）
    const ch2Title = `第二章${Date.now() % 100000}`;
    await createChapterViaUi(window, ch2Title);
    const tree = window.getByTestId('project-tree');
    const current = tree.getByTestId('tree-chapter');
    await expect(current).toContainText(ch2Title);
    await expect(current).toHaveAttribute('data-current', 'true');

    // 第 2 章续写（write_continue 3 阶段；前文 = 第 1 章 → 后端摘要注入 context，#318）
    const ch2Output = await runWriteContinue(window, kernel, pid);
    await expect(window.getByTestId('chapter-editor')).toHaveValue(ch2Output, {
      timeout: 15_000,
    });

    // 章节树 2 章 + 每章落库（内核 chapters 列表含 2 章且均非空）
    await expect(tree.getByTestId('tree-chapter')).toHaveCount(2);
    await expect
      .poll(
        async () => {
          const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`);
          if (!res.ok) return null;
          const data = (await res.json()) as {
            items: Array<{ title: string; word_count: number }>;
          };
          const found = data.items.filter(
            (c) => c.title === ch1Title || c.title === ch2Title
          );
          return found.length === 2 && found.every((c) => c.word_count > 0)
            ? found.length
            : null;
        },
        { timeout: 30_000, message: '两章应落库且均有正字数（第 1 章生成 + 第 2 章续写）' }
      )
      .toBe(2);
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// G3 续写连贯：前文含独特主角名 → 续写 → final_output 含主角名
// ────────────────────────────────────────────────────────────────
test('G3 续写连贯：前文主角名 → 点「续写」→ final_output 含主角名', async () => {
  test.skip(!process.env.INKFLOW_LLM_KEY, '需要真实 LLM key（INKFLOW_LLM_KEY 环境变量）');
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-管线-G3-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 前文含独特主角名（时间戳唯一化，避免旧文本干扰）
    const hero = `沈孤鸿${Date.now() % 100000}`;
    const seedContent = `前文：${hero}踏入试炼场，第一次面对魔兽，握紧长剑迎战。`;
    const chRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '续写连贯测试章', content: seedContent },
    });
    expect(chRes.status).toBe(201);
    await setupLlmForProject(kernel, pid);

    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible();
    await window
      .getByTestId('project-tree')
      .getByRole('button', { name: /续写连贯测试章/ })
      .click();
    await expect(window.getByTestId('chapter-editor')).toHaveValue(seedContent);

    // 续写 → completed → 断言前文主角名出现在续写（连贯性：#318 前文摘要注入）
    const finalOutput = await runWriteContinue(window, kernel, pid);
    expect(
      finalOutput.includes(hero),
      `续写连贯：final_output 应含前文主角「${hero}」（前文摘要注入 context 后 LLM 应延续人物）`
    ).toBe(true);
    expect(finalOutput).not.toBe(seedContent);
    await expect(window.getByTestId('chapter-editor')).toHaveValue(finalOutput, {
      timeout: 15_000,
    });
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// G4 大纲驱动：先建大纲（关联章节）→ AI 按大纲写指定章 → 输出含大纲要素
// ────────────────────────────────────────────────────────────────
test('G4 大纲驱动：预置大纲（关联章节）→ 点「生成」→ final_output 含大纲要素', async () => {
  test.skip(!process.env.INKFLOW_LLM_KEY, '需要真实 LLM key（INKFLOW_LLM_KEY 环境变量）');
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-管线-G4-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 预置空章节 → 关联大纲（level=chapter + chapter_id；description 含独特要素词）
    const chRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '大纲驱动测试章', content: '' },
    });
    expect(chRes.status).toBe(201);
    const chapter = (await chRes.json()) as { id: string };
    const outlineName = `青云宗试炼${Date.now() % 100000}`;
    const outlineKeyword = `剑意觉醒`;
    await presetOutline(
      kernel,
      pid,
      outlineName,
      `主角在${outlineKeyword}中获得传承，修为突破`,
      chapter.id
    );
    await setupLlmForProject(kernel, pid);

    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible();
    await window
      .getByTestId('project-tree')
      .getByRole('button', { name: /大纲驱动测试章/ })
      .click();
    await expect(window.getByTestId('chapter-editor')).toHaveValue('');

    // 生成指定章 → completed → 断言大纲要素出现在成品（宽松：大纲名或关键词之一）
    const finalOutput = await runWriteAuto(window, kernel, pid);
    const hitName = finalOutput.includes(outlineName);
    const hitKeyword = finalOutput.includes(outlineKeyword);
    expect(
      hitName || hitKeyword,
      `大纲驱动：final_output 应含大纲要素（「${outlineName}」或「${outlineKeyword}」之一）`
    ).toBe(true);
    await expect(window.getByTestId('chapter-editor')).toHaveValue(finalOutput, {
      timeout: 15_000,
    });
  } finally {
    await app.close();
  }
});
