/**
 * 写作页 AI 聊天框 + 视图切换 E2E（#379 F47，spec §6.3）
 *
 * 确定性方案（D5=A）：page.route 拦截管线 API，零真实 LLM 调用。
 * - POST /api/v1/agent/pipelines/execute → 202 + execution_id（拦截）
 * - GET /api/v1/agent/pipelines/executions/{id} → completed + final_output（拦截）
 * 其余（项目创建/章节树）走真实内核。
 *
 * 用例：
 * 1. 聊天框：输入 → 发送 → assistant 消息（轮询 completed）→ 插入正文 → 编辑器 value 更新
 * 2. 视图切换：view-toggle → 详情页空态（exec-detail-empty）→ 切回 editor
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

    // 预置 1 卷 + 1 章（正文空）——项目树有章节可点
    const volumes = await kernelFetch(kernel, `/api/v1/projects/${pid}/volumes`, { method: 'POST', body: { title: '第一卷 风起', order_index: 0 } });
    expect(volumes.ok).toBe(true);
    const volData = (await volumes.json()) as { id: string };
    const chapters = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '第1章 初见', volume_id: volData.id, order_index: 0, content: '' },
    });
    expect(chapters.ok).toBe(true);

    // 拦截管线 API（确定性）
    const finalOutput = 'E2E 对话回复内容';
    interceptPipeline(window, 'e-chat-e2e', finalOutput, pid);

    // 进入写作页并选择章节
    await gotoNav(window, '写作');
    await expect(window.getByTestId('tree-chapter')).toBeVisible({ timeout: 15_000 });
    await window.getByTestId('tree-chapter').click();

    // 聊天框发送
    const chatInput = window.getByTestId('chat-input');
    await expect(chatInput).toBeVisible({ timeout: 15_000 });
    await chatInput.fill('帮我写一段打斗场景');
    await window.getByTestId('chat-send').click();

    // assistant 消息 + 插入正文按钮
    await expect(window.getByTestId('chat-msg-ai-0')).toContainText(finalOutput, { timeout: 15_000 });
    await window.getByTestId('chat-insert-0').click();

    // 插入正文 → 编辑器 value 更新（setContent）
    await expect(window.getByTestId('chapter-editor')).toHaveValue(finalOutput, { timeout: 15_000 });
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

    const volumes = await kernelFetch(kernel, `/api/v1/projects/${pid}/volumes`, { method: 'POST', body: { title: '第一卷 风起', order_index: 0 } });
    expect(volumes.ok).toBe(true);
    const volData = (await volumes.json()) as { id: string };
    const chapters = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '第1章 初见', volume_id: volData.id, order_index: 0, content: '正文内容' },
    });
    expect(chapters.ok).toBe(true);

    await gotoNav(window, '写作');
    await expect(window.getByTestId('tree-chapter')).toBeVisible({ timeout: 15_000 });
    await window.getByTestId('tree-chapter').click();

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
