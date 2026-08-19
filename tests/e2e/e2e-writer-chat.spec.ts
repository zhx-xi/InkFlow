/**
 * 写作页 AI 聊天框 + 视图切换 E2E（#379 F47，spec §6.3；#477 契约升级 2026-08-19）
 *
 * #477 契约（意图分离 + 单选插入）：
 * - AI 回复解析标记：`<<<CONTENT>>>` ... `<<<END>>>` 包裹 = 产出正文（content 意图，可插入）；
 *   无 start 标记 = 对话（conversation，无插入控件）。
 * - content 消息显示解析后 body（不含标记/前言）；每条渲染选择控件 chat-select-<seq>
 *   （data-selected="true"|"false"），新 content 消息到达自动选中最新一条。
 * - 共享插入按钮 chat-insert-selected 仅当存在 ≥1 条 content 消息时渲染，点击 → setContent(选中条 body)。
 * - conversation 消息无任何选择/插入控件；旧 per-message 按钮 chat-insert-<seq> 已删除，任何场景不再渲染。
 *
 * 确定性方案（D5=A）：page.route 拦截管线 API，零真实 LLM 调用。
 * - POST /api/v1/agent/pipelines/execute → 202 + execution_id（拦截）
 * - GET /api/v1/agent/pipelines/executions/{id} → completed + final_output（拦截）
 * 其余（项目创建/章节树）走真实内核。
 *
 * 用例：
 * 1. 聊天框：输入 → 发送 → content 意图回复（标记包裹）→ 自动选中 → 插入选中正文 → 编辑器 value 更新
 * 2. 对话类回复（无标记）→ 不渲染选择/插入控件
 * 3. 视图切换：view-toggle → 详情页空态（exec-detail-empty）→ 切回 editor
 *
 * 基建复用 e2e-writing.spec.ts 模式（launchApp/waitKernelInfo/createProjectViaUi/findProjectId）。
 */
import path from 'node:path';
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

interface KernelInfo {
  pid: number;
  port: number;
  token: string;
}

async function readKernelInfo(app: ElectronApplication): Promise<KernelInfo | undefined> {
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

async function launchApp(): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  await window.getByLabel('书名').fill(name);
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

/**
 * #474 前置校验预置：注册 openai key + 补 chat 模型。
 * 前端在点发送前校验「存在 key_saved=true 的 chat provider」，seed provider 默认
 * key_saved=false 且 models 初始为空 → 不预置则点发送被前端拦截（零请求）。
 * 管线本身被 page.route 拦截（零真实 LLM），key 用假值即可（APIKeyManager 只存不验）。
 */
async function presetChatModel(kernel: KernelInfo): Promise<void> {
  const keyRes = await kernelFetch(kernel, '/api/v1/settings/llm-keys', {
    method: 'POST',
    body: { provider: 'openai', api_key: 'sk-e2e-chat-dummy' },
  });
  expect(keyRes.ok, 'openai key 注册（POST /settings/llm-keys）应成功').toBe(true);

  const pcRes = await kernelFetch(kernel, '/api/v1/provider-configs');
  expect(pcRes.ok).toBe(true);
  const pcs = (await pcRes.json()) as {
    items: Array<{ id: number; name: string; models: Array<{ id: string; type: string }> }>;
  };
  const provider = pcs.items.find((p) => p.name === 'openai');
  expect(provider, 'seed provider openai 应存在').toBeTruthy();
  const models = provider!.models.some((m) => m.id === 'gpt-4o' && m.type === 'chat')
    ? provider!.models
    : [...(provider!.models ?? []), { id: 'gpt-4o', type: 'chat' }];
  const patchRes = await kernelFetch(kernel, `/api/v1/provider-configs/${provider!.id}`, {
    method: 'PATCH',
    body: { models },
  });
  expect(patchRes.ok, 'provider-configs PATCH（补 chat 模型）应成功').toBe(true);
}

async function findProjectId(kernel: KernelInfo, name: string): Promise<string> {
  const res = await kernelFetch(kernel, '/api/v1/projects');
  expect(res.ok).toBe(true);
  const data = (await res.json()) as { items: Array<{ id: string; name: string }> };
  const project = data.items.find((p) => p.name === name);
  expect(project, `项目「${name}」应已创建并持久化`).toBeTruthy();
  return project!.id;
}

async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

/** 拦截管线 API：execute → 202；executions/{id} → completed + final_output（确定性，零真实 LLM） */
function interceptPipeline(window: Page, executionId: string, finalOutput: string, projectId: string): void {
  void window.route('**/api/v1/agent/pipelines/execute', (route) => {
    void route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        execution_id: executionId,
        pipeline: 'builtin:chat',
        project_id: projectId,
        status: 'pending',
        created_at: '',
      }),
    });
  });
  void window.route(`**/api/v1/agent/pipelines/executions/${executionId}`, (route) => {
    void route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        execution_id: executionId,
        pipeline: 'builtin:chat',
        project_id: projectId,
        status: 'completed',
        stages: [
          { stage_id: 'chat', status: 'completed', output: finalOutput, error: '', retry_count: 0, duration_ms: 300 },
        ],
        trace: [
          { node: 'chat', type: 'stage', reasoning: '回答用户提问', tool_calls: [], output: finalOutput, duration_ms: 300, ts: '2026-08-16T10:00:00Z' },
        ],
        relations: [],
        final_output: finalOutput,
        total_duration_ms: 300,
        error: '',
      }),
    });
  });
}

test.describe.configure({ timeout: 120_000 });

test('聊天框：输入 → 发送 → assistant 消息 → 插入正文 → 编辑器 value 更新', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-聊天-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 预置 1 卷 + 1 章（正文空）——项目树有章节可点（对齐 e2e-writing 预置写法）
    const volumes = await kernelFetch(kernel, `/api/v1/projects/${pid}/volumes`, { method: 'POST', body: { title: '第一卷 风起' } });
    expect(volumes.status).toBe(201);
    const volData = (await volumes.json()) as { id: string };
    const chapters = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '第1章 初见', volume_id: volData.id, content: '' },
    });
    expect(chapters.status).toBe(201);

    // #474 前置校验预置：注册 openai key + 补 chat 模型（不预置则点发送被前端拦截）
    await presetChatModel(kernel);

    // 重挂载写作页触发 loadChapterTree（加载 API 预置的卷/章）
    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('tree-volume')).toBeVisible({ timeout: 15_000 });
    // 点章节 → 成为当前章（tree-chapter 仅当前章渲染）
    await window.getByRole('button', { name: /第1章 初见/ }).click();
    await expect(window.getByTestId('tree-chapter')).toBeVisible({ timeout: 15_000 });

    // 树就绪后再注册管线拦截（避免影响树加载）
    // #477：<<<CONTENT>>>...<<<END>>> 包裹 = content 意图（产出正文，可插入）
    const finalOutput = '<<<CONTENT>>>\nE2E 续写正文内容\n<<<END>>>';
    interceptPipeline(window, 'e-chat-e2e', finalOutput, pid);

    // 聊天框发送
    const chatInput = window.getByTestId('chat-input');
    await expect(chatInput).toBeVisible({ timeout: 15_000 });
    await chatInput.fill('帮我写一段打斗场景');
    await window.getByTestId('chat-send').click();

    // #477：assistant 消息显示解析后 body（不含标记/前言）
    const aiMsg = window.getByTestId('chat-msg-ai-0');
    await expect(aiMsg).toContainText('E2E 续写正文内容', { timeout: 15_000 });
    await expect(aiMsg).not.toContainText('<<<CONTENT>>>');
    await expect(aiMsg).not.toContainText('<<<END>>>');

    // 选择控件：content 消息渲染 chat-select-0 且自动选中（data-selected="true"）
    const select0 = window.getByTestId('chat-select-0');
    await expect(select0).toBeVisible({ timeout: 15_000 });
    await expect(select0).toHaveAttribute('data-selected', 'true');

    // 旧 per-message 按钮 chat-insert-0 已删除（#477：任何场景不再渲染）
    await expect(window.getByTestId('chat-insert-0')).toHaveCount(0);

    // 共享「插入选中正文」按钮 → setContent(选中条 body) → 编辑器 value 更新
    await window.getByTestId('chat-insert-selected').click();
    await expect(window.getByTestId('chapter-editor')).toHaveValue('E2E 续写正文内容', { timeout: 15_000 });
  } finally {
    await app.close();
  }
});

test('对话类回复（无 content 标记）不渲染选择/插入控件', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-聊天-对话-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 预置 1 卷 + 1 章（正文空）——项目树有章节可点（对齐用例 1 预置写法）
    const volumes = await kernelFetch(kernel, `/api/v1/projects/${pid}/volumes`, { method: 'POST', body: { title: '第一卷 风起' } });
    expect(volumes.status).toBe(201);
    const volData = (await volumes.json()) as { id: string };
    const chapters = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '第1章 初见', volume_id: volData.id, content: '' },
    });
    expect(chapters.status).toBe(201);

    // #474 前置校验预置：注册 openai key + 补 chat 模型
    await presetChatModel(kernel);

    // 重挂载写作页触发 loadChapterTree（加载 API 预置的卷/章）
    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('tree-volume')).toBeVisible({ timeout: 15_000 });
    // 点章节 → 成为当前章（tree-chapter 仅当前章渲染）
    await window.getByRole('button', { name: /第1章 初见/ }).click();
    await expect(window.getByTestId('tree-chapter')).toBeVisible({ timeout: 15_000 });

    // 树就绪后再注册管线拦截（避免影响树加载）
    // #477：无 start 标记 = conversation 意图（纯对话，无插入控件）
    const finalOutput = '这是一段纯对话回复，不包含正文。';
    interceptPipeline(window, 'e-chat-e2e-conv', finalOutput, pid);

    // 聊天框发送
    const chatInput = window.getByTestId('chat-input');
    await expect(chatInput).toBeVisible({ timeout: 15_000 });
    await chatInput.fill('这本书怎么样？');
    await window.getByTestId('chat-send').click();

    // conversation：assistant 消息显示原文（无解析/无标记）
    await expect(window.getByTestId('chat-msg-ai-0')).toContainText(finalOutput, { timeout: 15_000 });

    // 无任何选择/插入控件（新契约 chat-select-*/chat-insert-selected + 旧 chat-insert-<seq> 均不渲染）
    await expect(window.getByTestId('chat-select-0')).toHaveCount(0);
    await expect(window.getByTestId('chat-insert-selected')).toHaveCount(0);
    await expect(window.getByTestId('chat-insert-0')).toHaveCount(0);
  } finally {
    await app.close();
  }
});

test('视图切换：view-toggle → 详情页空态 → 切回 editor', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-切换-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    const volumes = await kernelFetch(kernel, `/api/v1/projects/${pid}/volumes`, { method: 'POST', body: { title: '第一卷 风起' } });
    expect(volumes.status).toBe(201);
    const volData = (await volumes.json()) as { id: string };
    const chapters = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '第1章 初见', volume_id: volData.id, content: '正文内容' },
    });
    expect(chapters.status).toBe(201);

    // 重挂载写作页触发 loadChapterTree
    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('tree-volume')).toBeVisible({ timeout: 15_000 });
    await window.getByRole('button', { name: /第1章 初见/ }).click();
    await expect(window.getByTestId('tree-chapter')).toBeVisible({ timeout: 15_000 });

    // 默认 editor 视图
    await expect(window.getByTestId('chapter-editor')).toBeVisible({ timeout: 15_000 });

    // 切到详情视图（未执行过管线 → 空态）
    await window.getByTestId('view-toggle').click();
    await expect(window.getByTestId('exec-detail-empty')).toBeVisible({ timeout: 15_000 });

    // 切回 editor 视图
    await window.getByTestId('view-toggle').click();
    await expect(window.getByTestId('chapter-editor')).toBeVisible({ timeout: 15_000 });
  } finally {
    await app.close();
  }
});
