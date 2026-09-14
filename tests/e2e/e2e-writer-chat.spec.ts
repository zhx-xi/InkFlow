/**
 * 写作页 AI 聊天框 + 视图切换 E2E（#379 F47，spec §6.3；#477 契约升级 2026-08-19）
 *
 * #477 契约（意图分离 + 单选插入）：
 * - AI 回复解析标记：`<<<CONTENT>>>` ... `<<<END>>>` 包裹 = 产出正文（content 意图，可插入）；
 *   无 start 标记 = 对话（conversation，无插入控件）。
 * - content 消息显示解析后 body（不含标记/前言）；每条渲染选择控件 chat-select-<seq>
 *   （data-selected="true"|"false"），新 content 消息到达自动选中最新一条。
 * - per-message 插入按钮 chat-insert-<seq> 仅当该条 content 意图时渲染，点击 → setContent(该条 body)
 *   （#642-2 布局）；每条 AI 回复渲染 chat-copy-<seq>（复制对话）。全局 chat-insert-selected 已移除。
 * - conversation 消息无任何选择/插入控件（仅 chat-copy-<seq>）。
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
 * 4. 流式新消息落库回填 id（#1161）：发送 → 删除按钮切换 chat-msg-delete-<uuid>
 *    → 点击删除 → 消息消失 + 服务端无孤儿 + 重挂载不复活
 *
 * 基建复用 e2e-writing.spec.ts 模式（launchApp/waitKernelInfo/createProjectViaUi/findProjectId）。
 */
import path from 'node:path';
import { readFileSync } from 'node:fs';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';
import { createIsolatedEnv, type IsolatedEnv } from './e2e-isolation';
import { ensureModelConfigured } from './e2e-model-ready';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');
const MAIN_JS = 'packages/electron/out/main.js';

interface KernelInfo {
  pid: number;
  port: number;
  token: string;
}

async function readKernelInfo(app: ElectronApplication): Promise<KernelInfo | undefined> {
  // 根治（#1041）：evaluate 返回 JSON 字符串快照——序列化在主进程内同步完成，
  // 跨边界只传原始 string，消除 object round-trip 的 GC 竞态（#451/#455 签名族）；
  // 瞬态异常（GC / Target closed）等价「__kernelInfo 尚未注入」→ undefined，
  // 轮询继续——waitKernelInfo 超时耗尽仍响亮抛错（对齐 readTrayInfo 防御先例）。
  try {
    const raw = await app.evaluate(() => {
      const info = (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo;
      return info ? JSON.stringify(info) : null;
    });
    return raw ? (JSON.parse(raw) as KernelInfo) : undefined;
  } catch {
    return undefined;
  }
}

async function waitKernelInfo(app: ElectronApplication, timeoutMs = 240_000): Promise<KernelInfo> {
  const deadline = Date.now() + timeoutMs;
  let info: KernelInfo | undefined;
  while (Date.now() < deadline) {
    info = await readKernelInfo(app);
    if (info) return info;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`__kernelInfo 未在 ${timeoutMs}ms 内注入（内核未就绪）`);
}

/**
 * #1159 隔离数据目录的内核 pid：读 <dataDir>/kernel.json 的 pid（#1040：cleanup 先等内核退出再删目录）。
 * 就绪钩子 __kernelInfo 注入先于 kernel.json 落盘（main.ts updateKernelInfoHook → writeKernelStateFile）
 * → 短暂轮询；超时仍读不到返回 undefined（cleanupIsolatedEnv 内部过滤 undefined）。
 */
async function readKernelPid(dataDir: string, timeoutMs = 10_000): Promise<number | undefined> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const parsed = JSON.parse(readFileSync(path.join(dataDir, 'kernel.json'), 'utf8')) as {
        pid?: unknown;
      };
      if (typeof parsed.pid === 'number') {
        return parsed.pid;
      }
    } catch {
      // kernel.json 尚未落盘 / 半截写入 → 继续轮询
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  return undefined;
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

async function launchApp(): Promise<{
  app: ElectronApplication;
  window: Page;
  kernel: KernelInfo;
  iso: IsolatedEnv;
  kernelPid: number | undefined;
}> {
  // #1159 数据目录隔离：独立 dataDir（内核数据）+ 独立 --user-data-dir（渲染层）→ 与他例零共享
  const iso = createIsolatedEnv('writer-chat');
  const app = await electron.launch({
    args: [MAIN_JS, `--user-data-dir=${iso.userDataDir}`],
    cwd: FRONTEND_DIR,
    env: iso.env as Record<string, string>,
  });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  // F60 #934：隔离数据目录 = 全新安装态 → 预置「已配置模型」则门控放行
  await ensureModelConfigured(kernel);
  // #1040：cleanup 需先等内核退出再删目录 → 从隔离 dataDir 的 kernel.json 取内核 pid
  return { app, window, kernel, iso, kernelPid: await readKernelPid(iso.dataDir) };
}

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
  // #936 C：PATCH 补 chat 模型会触发保存前探测门禁；本预置阶段无真实凭据
  // （或 key 尚未就绪）→ 显式 force=true 跳过门禁（预置语义 = 只落数据）
  const patchRes = await kernelFetch(
    kernel,
    `/api/v1/provider-configs/${provider!.id}?force=true`,
    {
      method: 'PATCH',
      body: { models },
    }
  );
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

/**
 * #1161 契约（spec §18.2）：ChatPanel 挂载期历史加载不再覆盖本地新状态
 * （C1/C2 陈旧快照守卫）→ 「等历史落地再发送」的 #1155 绕过删除；
 * 用户消息落库回填 id 后删除真落服务端（C3），删除按钮 testid 由
 * chat-msg-delete-user-<seq> 切换为 chat-msg-delete-<uuid>。
 */

/** 拦截 chat 流式端点：POST /api/v1/chat/agent/stream → SSE 帧（确定性，零真实 LLM）.
 * #541：ChatPanel 已从 executePipeline+轮询 改为 streamChat SSE 消费；
 * 帧协议 = data: {json}\n\n（帧带 type 键：delta 帧 {type:'delta',delta,done:false} × N → {type:'done',done:true} 终帧）。
 */
function interceptChatStream(window: Page, finalOutput: string): void {
  // 拆两段 delta 模拟流式渐进（E2E 断言终态；流式渐进细节由单测覆盖）
  const mid = Math.ceil(finalOutput.length / 2);
  const frame = (payload: Record<string, unknown>): string =>
    `data: ${JSON.stringify(payload)}\n\n`;
  const body =
    frame({ type: 'delta', delta: finalOutput.slice(0, mid), done: false }) +
    frame({ type: 'delta', delta: finalOutput.slice(mid), done: false }) +
    frame({ type: 'done', done: true });
  void window.route('**/api/v1/chat/agent/stream', (route) => {
    void route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body,
    });
  });
}

test.describe.configure({ timeout: 360_000 });

test('聊天框：输入 → 发送 → assistant 消息 → 插入正文 → 编辑器 value 更新', async () => {
  const { app, window, kernel, iso, kernelPid } = await launchApp();
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
    interceptChatStream(window, finalOutput);

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

    // per-message 插入按钮 chat-insert-0（content 意图渲染，点它直接插入该条 body，#642-2）
    await expect(window.getByTestId('chat-insert-0')).toHaveCount(1);

    // 点 per-message 插入按钮 → setContent(该条 body) → 编辑器 value 更新
    await window.getByTestId('chat-insert-0').click();
    await expect(window.getByTestId('chapter-editor')).toHaveValue('E2E 续写正文内容', { timeout: 15_000 });
  } finally {
    await app.close();
    await iso.cleanup({ pids: [kernelPid], timeoutMs: 10_000 });
  }
});

test('对话类回复（无 content 标记）不渲染选择/插入控件', async () => {
  const { app, window, kernel, iso, kernelPid } = await launchApp();
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
    interceptChatStream(window, finalOutput);

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
    await iso.cleanup({ pids: [kernelPid], timeoutMs: 10_000 });
  }
});

test('视图切换：view-toggle → 详情页空态 → 切回 editor', async () => {
  const { app, window, kernel, iso, kernelPid } = await launchApp();
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
    await iso.cleanup({ pids: [kernelPid], timeoutMs: 10_000 });
  }
});

test('流式新消息落库回填 id → 删除真落服务端 → 重挂载不复活（#581-1 / #1161）', async () => {
  const { app, window, kernel, iso, kernelPid } = await launchApp();
  try {
    const name = `E2E-删除-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 预置 1 卷 + 1 章（正文空）
    const volRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/volumes`, { method: 'POST', body: { title: '第一卷 风起' } });
    expect(volRes.status).toBe(201);
    const volData = (await volRes.json()) as { id: string };
    const chRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '第1章 初见', volume_id: volData.id, content: '' },
    });
    expect(chRes.status).toBe(201);

    // #474 前置校验预置：注册 openai key + 补 chat 模型
    await presetChatModel(kernel);

    // 重挂载写作页触发 loadChapterTree
    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('tree-volume')).toBeVisible({ timeout: 15_000 });
    // #1161：陈旧快照落地已被 C1/C2 守卫丢弃 → 无需等历史加载即可点章节并发送
    await window.getByRole('button', { name: /第1章 初见/ }).click();
    await expect(window.getByTestId('tree-chapter')).toBeVisible({ timeout: 15_000 });

    // 树就绪后再注册流式拦截（对话类回复，无 content 标记）
    interceptChatStream(window, '这是一段纯对话回复。');

    // 发送 → user 消息渲染且不被在途加载抹掉（C1 修复的 E2E 面）
    const chatInput = window.getByTestId('chat-input');
    await expect(chatInput).toBeVisible({ timeout: 15_000 });
    await chatInput.fill('帮我写一段打斗场景');
    await window.getByTestId('chat-send').click();
    await expect(window.getByTestId('chat-msg-user-0')).toBeVisible({ timeout: 15_000 });

    // #1161 C3 契约：落库回填 id → 删除按钮 testid 切换为 chat-msg-delete-<uuid>
    const uuidDelete = window.locator('[data-testid^="chat-msg-delete-"]');
    await expect(async () => {
      const first = await uuidDelete.first().getAttribute('data-testid');
      expect(first).toMatch(/^chat-msg-delete-[0-9a-f-]{36}$/);
    }).toPass({ timeout: 15_000 });
    const delTestId = (await uuidDelete.first().getAttribute('data-testid'))!;

    // 点击删除 → 该消息消失
    await window.getByTestId(delTestId).click();
    await expect(window.getByTestId('chat-msg-user-0')).toHaveCount(0);

    // 服务端真相断言：被删消息无孤儿副本（C3：删除真落服务端）
    const convRes = await kernelFetch(kernel, '/api/v1/chat/conversations');
    expect(convRes.ok).toBe(true);
    const convs = (await convRes.json()) as { items: Array<{ conversation_id: string; project_id: string }> };
    const conv = convs.items.find((c) => c.project_id === pid);
    expect(conv, '章节会话应存在').toBeTruthy();
    const after = await kernelFetch(kernel, `/api/v1/chat/messages?conversation_id=${conv!.conversation_id}`);
    expect(after.ok).toBe(true);
    const afterData = (await after.json()) as { items: Array<{ content: string }> };
    expect(
      afterData.items.filter((m) => m.content === '帮我写一段打斗场景'),
      '被删消息不得留服务端孤儿',
    ).toHaveLength(0);

    // 重挂载不复活：切走再回 → 历史重新加载 → 消息仍不存在
    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await window.getByRole('button', { name: /第1章 初见/ }).click();
    await expect(window.getByTestId('tree-chapter')).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('chat-msg-user-0')).toHaveCount(0, { timeout: 15_000 });
  } finally {
    await app.close();
    await iso.cleanup({ pids: [kernelPid], timeoutMs: 10_000 });
  }
});
