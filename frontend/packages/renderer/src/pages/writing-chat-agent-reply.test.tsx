/**
 * #642-1 契约（前端组件测试）：写作页「AI 写作/生成」后，管线 delta 应**流式**进入 chat 区。
 *
 * ⚠️ #681 契约翻转（2026-08-26）：管线产物**不再**以 chat-msg-ai-<seq> 渲染、**不再** saveChatMessage
 * 落库——改为独立「管线输出」区（pipeline-output-<seq>，带「管线输出」标签），符合 #681
 * 「管线阶段输出不污染 chat 历史」。编辑器仍落章（final_output = 编辑器内容）。
 * ⚠️ #763（2026-08-29）语义反转（用户拍板 P3-A）：生成/续写 → createChatConversation 建新会话，
 *   onDone(final_output) **再次** saveChatMessage 落成会话 ai 消息——本文件「不 saveChatMessage」断言已迁移为「saveChatMessage 被调」。
 *
 * GREEN 目标（本文件 = #681 新契约）:
 * - 生成触点 → 调 streamPipeline（SSE 流式），onDelta 渐进取「管线输出」区（pipeline-output-<seq>）
 * - onDone → **saveChatMessage** 落管线产物到新会话（#763 覆盖 #681 的「不落 chat」）；仅落章（编辑器 = final_output）
 * - 管线产物不持久化到 chat 历史（切 view 重挂后 chat 区无管线产物，符合「不污染 chat」语义）
 */
import { describe, it, expect, beforeEach, afterEach, vi, type MockInstance } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { WritingPage } from './writing';
import { MemoryRouter } from 'react-router-dom';
import { createChatConversation, type ChatConversationDto } from '../api/chat';
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
vi.mock('../api/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/chat')>();
  return { ...actual, createChatConversation: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);
const streamPipelineMock = vi.mocked(streamPipeline);
const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);
const confirmMock = vi.mocked(confirmExecution);

/** #770 契约签名（当前 src 仅 1 参 → RED）：createChatConversation(projectId, { title?: string }) */
const createChatCovMock = vi.mocked(createChatConversation) as unknown as MockInstance<
  (projectId: string, opts?: { title?: string }) => Promise<ChatConversationDto>
>;

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
  // #770：createChatConversation 直接 mock（返回 conv-<projectId> 线程，保持既有测试流）
  createChatCovMock.mockReset();
  createChatCovMock.mockImplementation(async (projectId: string) => ({
    conversation_id: `conv-${projectId}`,
    project_id: projectId,
    project_name: '青云志',
    last_message: '',
    message_count: 0,
    is_deleted: false,
    updated_at: '2026-08-25T00:00:00Z',
  }));
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
    // #744：conversation 多线程（ChatPanel 挂载解析活动线程 / 归档后建新线程）
    if (path.startsWith('/api/v1/chat/conversations')) {
      if (init?.method === 'POST') {
        const b = init.body as { project_id: string };
        return {
          conversation_id: `conv-${b.project_id}`,
          project_id: b.project_id,
          project_name: '青云志',
          last_message: '',
          message_count: 0,
          is_deleted: false,
          updated_at: '2026-08-25T00:00:00Z',
        };
      }
      return { items: [], total: 0 };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  vi.useRealTimers();
  delete window.INKFLOW_API;
  capturedPipelineStream = null;
});

/** #840：WritingPage 需要 Router 上下文（useSearchParams）；统一用 MemoryRouter 包裹渲染 */
function renderWritingPage(initialEntries: string[] = ['/writing']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <WritingPage />
    </MemoryRouter>
  );
}

describe('写作页 — AI 生成后管线输出与 chat 区分渲染（#681 翻转 #642-1）', () => {
  it('「生成」→ 调 streamPipeline → onDelta 渐进显示在「管线输出」区（非 chat-msg-ai）', async () => {
    renderWritingPage();
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    // streamPipeline 被调用（体含 pipeline=builtin:write_auto）
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    expect(capturedPipelineStream?.body.pipeline).toBe('builtin:write_auto');
    // 驱动 SSE delta：渐进取「管线输出」区（每条管线 delta 独立一条，seq 递增）
    act(() => { capturedPipelineStream?.callbacks.onDelta('管线成品'); });
    act(() => { capturedPipelineStream?.callbacks.onDelta('章节内容'); });
    // #681：管线产物以 pipeline-output-<seq> 逐条渲染（带「管线输出」标签），非 chat-msg-ai
    const outMsg = await screen.findByTestId('pipeline-output-0');
    expect(outMsg).toHaveTextContent('管线输出');
    expect(outMsg).toHaveTextContent('管线成品');
    // 第二条管线 delta 独立条目
    expect(screen.getByTestId('pipeline-output-1')).toHaveTextContent('章节内容');
    // 管线产物不应以 AI 消息出现（不污染 chat）
    expect(screen.queryByTestId('chat-msg-ai-0')).not.toBeInTheDocument();
  });

  it('done → saveChatMessage 落管线产物到会话（#763 覆盖 #681）；仅落章时编辑器 = final_output', async () => {
    renderWritingPage();
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    act(() => { capturedPipelineStream?.callbacks.onDelta('\n<<<CONTENT>>>\n他握紧了剑。\n<<<END>>>'); });
    act(() => { capturedPipelineStream?.callbacks.onDone({ done: true, final_output: '他握紧了剑。' }); });
    // #763：生成产物落成新会话的 ai 消息（saveChatMessage → POST /api/v1/chat/messages）。
    //   ⚠️ 此为 #681「管线产物不落 chat 历史」契约的语义反转（用户拍板 P3-A：#763 覆盖 #681）。
    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/chat/messages',
        expect.objectContaining({
          method: 'POST',
          body: expect.objectContaining({ project_id: 'p1', role: 'ai', content: '他握紧了剑。', intent: 'content', conversation_id: 'conv-p1' }),
        }),
      ),
    );
    // 落章：编辑器内容 = final_output
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toBe('他握紧了剑。'));
  });

  it('切 view（editor→detail→editor）后 chat 区无管线产物（管线输出不持久化到 chat 历史）', async () => {
    renderWritingPage();
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    act(() => { capturedPipelineStream?.callbacks.onDelta('<<<CONTENT>>>\n他握紧了剑。\n<<<END>>>'); });
    act(() => { capturedPipelineStream?.callbacks.onDone({ done: true, final_output: '他握紧了剑。' }); });
    // 切到详情页 view（ChatPanel 卸载重挂）
    fireEvent.click(screen.getByRole('button', { name: /详情/ }));
    // 切回编辑视图 → ChatPanel 重挂
    fireEvent.click(screen.getByTestId('view-toggle'));
    // #681：管线产物不落 chat 历史 → 重挂后 chat-msg-ai-0 不应出现（若出现则污染了 chat 历史）
    await waitFor(() => {
      expect(screen.queryByTestId('chat-msg-ai-0')).not.toBeInTheDocument();
    });
  });
});

/**
 * #770 会话跟随章节 + 命名（spec §17.4.3 / writing.md §4.2）：
 * - 章节内对话（ChatPanel 挂载建会话）/生成/续写 → createChatConversation(projectId, { title: 章节名 })
 * - 全局 chat 页（无章节）→ createChatConversation(projectId)（无 title；首条消息前 30 字命名在 ChatPanel 层落库）
 */
describe('写作页 — 会话跟随章节 + 命名（#770 §17.4.3）', () => {
  it('章节内对话（ChatPanel 挂载建会话）→ createChatConversation 传 {project_id, title=章节名}', async () => {
    renderWritingPage();
    // ChatPanel 挂载即解析活动线程：fetchChatConversations 空 → createChatConversation 建新
    await waitFor(() => expect(createChatCovMock).toHaveBeenCalled());
    // #770：章节内建会话 title=章节名（当前实现只传 projectId → RED）
    expect(createChatCovMock).toHaveBeenCalledWith('p1', expect.objectContaining({ title: '第1章 初见' }));
  });

  it('章节内点「生成」→ startWithCheck 建会话同样传 title=章节名（#763 保持 + #770 补 title）', async () => {
    renderWritingPage();
    await waitFor(() => expect(createChatCovMock).toHaveBeenCalled());
    createChatCovMock.mockClear();
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => expect(createChatCovMock).toHaveBeenCalled());
    expect(createChatCovMock).toHaveBeenLastCalledWith('p1', expect.objectContaining({ title: '第1章 初见' }));
  });

  it('全局 chat（无章节）→ 建会话不传 title（首条消息前 30 字命名在 ChatPanel 层）', async () => {
    useChapterStore.setState({ currentChapterId: null, content: '' });
    renderWritingPage();
    // 全局 chat 页挂载即建会话（当前实现无全局分支 → ChatPanel 不挂载 → 永不调用 → RED）
    await waitFor(() => expect(createChatCovMock).toHaveBeenCalled());
    const [pid, opts] = createChatCovMock.mock.calls[0];
    expect(pid).toBe('p1');
    expect(opts === undefined || !opts.title).toBe(true);
  });
});
