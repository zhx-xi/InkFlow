/**
 * #642-1 契约（前端组件测试，TDD RED→GREEN）：写作页「AI 写作/生成」后，chat 页应
 * **流式**显示 Agent 回复（与详情页 AgentRun 的 final_output 一致），而非等 completed 后一次性注入。
 *
 * 现状（BUG）：writing.tsx 以 `agentOutput={pipeline.status==='success'?finalOutput:null}` 一次性注入；
 * 且用户「看详情页 completed → 切回编辑视图」时 ChatPanel 重挂，注入消息被历史加载覆盖丢失
 * （injectedAgentOutputsRef 使注入永不再触发）。本契约锁 GREEN 流式行为。
 *
 * GREEN 目标（本文件 = #642-1 契约，当前实现 FAIL，GREEN 实现必须匹配）:
 * - 生成触点 → 调 streamPipeline（SSE 流式），onDelta 渐进累积到 chat-msg-ai-<seq>
 * - onDone → parseChatReply 落定 + saveChatMessage 持久化 + 落章（编辑器 = final_output）
 * - 切 view（editor→detail→editor）后 chat 仍显示该 AI 回复（历史持久化，不因重挂丢失）
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { WritingPage } from './writing';
import { apiFetch } from '../api/client';
import { streamPipeline, executePipeline, getExecutionStatus, confirmExecution } from '../api/pipeline';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock('../api/pipeline', () => ({
  streamPipeline: vi.fn(),
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);
const streamPipelineMock = vi.mocked(streamPipeline);
const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);
const confirmMock = vi.mocked(confirmExecution);

const seedVolumes = [{ id: 'v1', title: '第一卷 风起', order_index: 0 }];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
];

const READY_PROVIDER: ProviderConfig = {
  id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
  models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }], key_saved: true,
  max_retries: 3, timeout: 60, created_at: '', updated_at: '',
};

/** 每次 streamPipeline 调用的 callbacks 捕获（用例手动驱动 SSE 帧） */
interface CapturedPipelineStream {
  body: { project_id: string; pipeline: string; chapter_id?: string; variables?: Record<string, string> };
  callbacks: {
    onDelta: (delta: string) => void;
    onDone: (frame: { done: boolean; final_output?: string }) => void;
    onError: (message: string) => void;
    onToolCall?: (call: { id: string; name: string; args: Record<string, unknown> }) => void;
    onToolResult?: (res: { id: string; name: string; result: string }) => void;
  };
}
let capturedPipelineStream: CapturedPipelineStream | null = null;

beforeEach(() => {
  vi.useRealTimers();
  apiFetchMock.mockReset();
  streamPipelineMock.mockReset();
  executeMock.mockReset();
  statusMock.mockReset();
  confirmMock.mockReset();
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  // 默认 streamPipeline 捕获 callbacks，不自动 emit（用例手动驱动帧）
  streamPipelineMock.mockImplementation((_body, callbacks) => {
    capturedPipelineStream = { body: _body as CapturedPipelineStream['body'], callbacks: callbacks as CapturedPipelineStream['callbacks'] };
    return Promise.resolve(() => {});
  });
  window.INKFLOW_API = { baseURL: 'http://test.local', token: 'tok-1' };
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: seedVolumes, chapters: seedChapters, treeProjectId: 'p1', currentChapterId: 'c1', content: '已有正文第一段。', loading: false, error: null,
  });
  useProjectStore.setState({
    projects: [{ id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {}, created_at: '', updated_at: '' }],
    currentProjectId: 'p1', loading: false, error: null,
  });
  // chat 消息历史（saveChatMessage 落库后重挂拉取）——记录 POST，GET 返回已存
  const savedChatMessages: Array<{ id: string; project_id: string; role: 'user' | 'ai'; content: string; intent: 'content' | 'conversation' | null; created_at: string }> = [];
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    if (path === '/api/v1/provider-configs') return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes, total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/chapters') return { items: seedChapters, total: 1, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/chapters/') && init?.method === 'PATCH') return { ok: true };
    if (path === '/api/v1/chat/messages' && init?.method === 'POST') {
      const b = init.body as { project_id: string; role: 'user' | 'ai'; content: string; intent?: 'content' | 'conversation' | null };
      const created = { id: `cm-${savedChatMessages.length + 1}`, project_id: b.project_id, role: b.role, content: b.content, intent: b.intent ?? null, created_at: '2026-08-25T00:00:00Z' };
      savedChatMessages.push(created);
      return created;
    }
    if (path.startsWith('/api/v1/chat/messages')) return { items: savedChatMessages, total: savedChatMessages.length, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  vi.useRealTimers();
  delete window.INKFLOW_API;
  capturedPipelineStream = null;
});

describe('写作页 — AI 生成后 chat 流式显示 Agent 回复（#642-1）', () => {
  it('「生成」→ 调 streamPipeline → onDelta 渐进显示 Agent 回复（流式，非 completed 后注入）', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    // streamPipeline 被调用（体含 pipeline=builtin:write_auto）
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    expect(capturedPipelineStream?.body.pipeline).toBe('builtin:write_auto');
    // 驱动 SSE delta：渐进累积到 chat-msg-ai-0
    // RED：当前实现不调 streamPipeline（走 executePipeline 轮询 + agentOutput 注入）→ 失败
    act(() => { capturedPipelineStream?.callbacks.onDelta('管线成品'); });
    act(() => { capturedPipelineStream?.callbacks.onDelta('章节内容'); });
    const aiMsg = await screen.findByTestId('chat-msg-ai-0');
    expect(aiMsg).toHaveTextContent('管线成品章节内容');
  });

  it('done → parseChatReply 落定 + saveChatMessage 持久化 + 落章（编辑器 = final_output）', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    act(() => { capturedPipelineStream?.callbacks.onDelta('\n<<<CONTENT>>>\n他握紧了剑。\n<<<END>>>'); });
    act(() => { capturedPipelineStream?.callbacks.onDone({ done: true, final_output: '他握紧了剑。' }); });
    // saveChatMessage 落库 AI 回复（intent=content）
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/chat/messages',
        expect.objectContaining({
          method: 'POST',
          body: expect.objectContaining({ project_id: 'p1', role: 'ai', content: '他握紧了剑。', intent: 'content' }),
        }),
      );
    });
    // 落章：编辑器内容 = final_output
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toBe('他握紧了剑。'));
  });

  it('切 view（editor→detail→editor）后 chat 仍显示该 AI 回复（历史持久化，不因重挂丢失）', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    act(() => { capturedPipelineStream?.callbacks.onDelta('<<<CONTENT>>>\n他握紧了剑。\n<<<END>>>'); });
    act(() => { capturedPipelineStream?.callbacks.onDone({ done: true, final_output: '他握紧了剑。' }); });
    // 切到详情页 view（ChatPanel 卸载重挂）
    fireEvent.click(screen.getByRole('button', { name: /详情/ }));
    // 切回编辑视图 → ChatPanel 重挂 → 从历史拉取已持久化 AI 回复
    fireEvent.click(screen.getByTestId('view-toggle'));
    const aiMsg = await screen.findByTestId('chat-msg-ai-0');
    expect(aiMsg).toHaveTextContent('他握紧了剑。');
  });
});
