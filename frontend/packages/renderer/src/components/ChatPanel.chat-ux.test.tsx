/**
 * ChatPanel chat-UX 契约测试（#719 中断按钮 + #726 自动滚动 + #727 思考/工具折叠块）。
 * 独立文件承载，避免与 ChatPanel.test.tsx（既有 44 用例）同文件双向矛盾 + 各守 900 行护栏。
 * 契约：#719 流式运行中 chat-send ↔ chat-interrupt 互斥切换，点中断调 abortChatRun；
 * #726 新消息到底部才滚动（用户上滑不拉底）；#727 reasoning/tool 独立折叠块（默认折叠、> 展开）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import { apiFetch } from '../api/client';
import { executePipeline, getExecutionStatus } from '../api/pipeline';
import { useChapterStore } from '../stores/chapter';
import { useThemeStore } from '../stores/theme';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock('../api/pipeline', () => ({
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

const chatApiMocks = vi.hoisted(() => ({
  streamChat: vi.fn(),
  fetchChatMessages: vi.fn(),
  saveChatMessage: vi.fn(),
  fetchChatConversations: vi.fn(),
  archiveChatMessage: vi.fn(),
  deleteChatMessage: vi.fn(),
  restoreChatMessage: vi.fn(),
  archiveChatConversation: vi.fn(),
  deleteChatConversation: vi.fn(),
  // #744：新线程创建（GREEN api/chat.ts 新增 createChatConversation）
  createChatConversation: vi.fn(),
  // #719：后端 abort 端点（api/chat.ts GREEN 新增 abortChatRun）
  abortChatRun: vi.fn(),
}));
vi.mock('../api/chat', () => chatApiMocks);

const streamChatMock = chatApiMocks.streamChat;
const abortChatRunMock = chatApiMocks.abortChatRun as ReturnType<typeof vi.fn>;
const apiFetchMock = vi.mocked(apiFetch);
const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);

interface ChatStreamBody {
  project_id: string;
  prompt: string;
  chapter_id?: string;
  chapter_context?: string;
}
interface ChatStreamFrame {
  done: boolean;
  delta?: string;
  error?: string;
}
interface ChatStreamCallbacks {
  onDelta: (delta: string) => void;
  onDone: (frame: ChatStreamFrame) => void;
  onError: (message: string) => void;
  onToolCall?: (call: { id: string; name: string; args: unknown }) => void;
  onToolResult?: (result: { id: string; name: string; result: string }) => void;
  /** #719：run_started 帧 → 携带 run_id（前端据此调后端 abort） */
  onRunStart?: (runId: string) => void;
  /** #727：reasoning 帧 → 思考过程块 */
  onReasoning?: (text: string) => void;
}
interface CapturedChatStream {
  body: ChatStreamBody;
  callbacks: ChatStreamCallbacks;
}

const OPTS = { projectId: 'p1', chapterId: 'c1', chapterContent: '已有正文第一段。' };

const READY_PROVIDER: ProviderConfig = {
  id: 1,
  name: 'openai',
  base_url: 'https://api.openai.com/v1',
  default_model: 'gpt-4o',
  models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }],
  key_saved: true,
  max_retries: 3,
  timeout: 60,
  created_at: '2026-08-01T10:00:00Z',
  updated_at: '2026-08-05T10:00:00Z',
};

let capturedStreams: CapturedChatStream[] = [];

async function sendAndAwaitStream(user: ReturnType<typeof userEvent.setup>, text: string, index = 0) {
  await user.type(screen.getByTestId('chat-input'), text);
  await user.click(screen.getByTestId('chat-send'));
  await waitFor(() => {
    expect(streamChatMock).toHaveBeenCalledTimes(index + 1);
  });
}
function emitDelta(index: number, delta: string) {
  act(() => capturedStreams[index].callbacks.onDelta(delta));
}
function emitRunStart(index: number, runId: string) {
  act(() => capturedStreams[index].callbacks.onRunStart?.(runId));
}
function emitReasoning(index: number, text: string) {
  act(() => capturedStreams[index].callbacks.onReasoning?.(text));
}
function emitDone(index: number) {
  act(() => capturedStreams[index].callbacks.onDone?.({ done: true }));
}

beforeEach(() => {
  streamChatMock.mockReset();
  abortChatRunMock.mockReset();
  capturedStreams = [];
  chatApiMocks.fetchChatMessages.mockReset();
  chatApiMocks.saveChatMessage.mockReset();
  chatApiMocks.fetchChatConversations.mockReset();
  chatApiMocks.archiveChatMessage.mockReset();
  chatApiMocks.deleteChatMessage.mockReset();
  chatApiMocks.restoreChatMessage.mockReset();
  chatApiMocks.archiveChatConversation.mockReset();
  chatApiMocks.deleteChatConversation.mockReset();
  chatApiMocks.createChatConversation.mockReset();
  chatApiMocks.fetchChatMessages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  chatApiMocks.deleteChatMessage.mockResolvedValue(undefined);
  chatApiMocks.archiveChatConversation.mockResolvedValue(undefined);
  chatApiMocks.deleteChatConversation.mockResolvedValue(undefined);
  chatApiMocks.saveChatMessage.mockResolvedValue({
    id: 'm-new', project_id: 'p1', role: 'user', content: '', intent: null, created_at: '2026-08-21T10:00:00Z',
  });
  chatApiMocks.fetchChatConversations.mockResolvedValue({ items: [], total: 0 });
  // #744：无活动线程时 createChatConversation 建新（mock 返回 conv-<projectId> 线程）
  chatApiMocks.createChatConversation.mockImplementation(async (projectId: string) => ({
    conversation_id: `conv-${projectId}`,
    project_id: projectId,
    project_name: null,
    last_message: '',
    message_count: 0,
    is_deleted: false,
    updated_at: '2026-08-21T10:00:00Z',
  }));
  streamChatMock.mockImplementation((body: ChatStreamBody, callbacks: ChatStreamCallbacks) => {
    capturedStreams.push({ body, callbacks });
    return Promise.resolve(() => {});
  });
  executeMock.mockReset();
  statusMock.mockReset();
  apiFetchMock.mockReset();
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    }
    return { ok: true };
  });
  executeMock.mockResolvedValue({
    execution_id: 'e-chat-1', pipeline: 'builtin:chat', project_id: 'p1', status: 'pending', created_at: '',
  });
  statusMock.mockResolvedValue({
    execution_id: 'e-chat-1', pipeline: 'builtin:chat', project_id: 'p1', status: 'pending',
    stages: [], trace: [], final_output: '', total_duration_ms: 0, error: '',
  });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: [], chapters: [], treeProjectId: 'p1', currentChapterId: 'c1',
    content: '已有正文第一段。', loading: false, error: null,
  });
});

describe('ChatPanel chat-UX — 发送/中断按钮切换（#719）', () => {
  it('流式运行中渲染 chat-interrupt，非运行中渲染 chat-send', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    expect(screen.getByTestId('chat-send')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-interrupt')).not.toBeInTheDocument();
    await sendAndAwaitStream(user, '运行中测试');
    expect(screen.getByTestId('chat-interrupt')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-send')).not.toBeInTheDocument();
  });

  it('流式运行中点击中断 → 调 abortChatRun(run_id) + 恢复发送态', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '中断测试');
    emitRunStart(0, 'run-abc-123');
    await user.click(screen.getByTestId('chat-interrupt'));
    expect(abortChatRunMock).toHaveBeenCalledWith('run-abc-123');
    expect(screen.getByTestId('chat-send')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-interrupt')).not.toBeInTheDocument();
  });
});

describe('ChatPanel chat-UX — 卸载中止后端 run（#842）', () => {
  it('流式运行中卸载 → 调后端 abortChatRun(runIdRef)（不只调本地 abort）', async () => {
    const user = userEvent.setup();
    const { unmount } = render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '切页测试');
    emitRunStart(0, 'run-unmount-001');
    abortChatRunMock.mockClear();
    unmount();
    expect(abortChatRunMock).toHaveBeenCalledWith('run-unmount-001');
  });
});

describe('ChatPanel chat-UX — 发送后自动滚动到底部（#726）', () => {
  it('新消息到达（处于底部）→ 滚动容器滚动到底部（scrollIntoView 被调用）', async () => {
    const scrollSpy = vi.fn();
    Element.prototype.scrollIntoView = scrollSpy as unknown as typeof Element.prototype.scrollIntoView;
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '滚动测试');
    const container = screen.getByTestId('chat-messages');
    Object.defineProperty(container, 'scrollHeight', { value: 100, configurable: true });
    Object.defineProperty(container, 'clientHeight', { value: 100, configurable: true });
    Object.defineProperty(container, 'scrollTop', { value: 50, configurable: true });
    scrollSpy.mockClear();
    emitDelta(0, '新内容');
    await waitFor(() => expect(scrollSpy).toHaveBeenCalled());
  });

  it('用户手动上滑（非底部）→ 新消息到达不强制拉底（scrollIntoView 不被调用）', async () => {
    const scrollSpy = vi.fn();
    Element.prototype.scrollIntoView = scrollSpy as unknown as typeof Element.prototype.scrollIntoView;
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '滚动测试');
    const container = screen.getByTestId('chat-messages');
    Object.defineProperty(container, 'scrollHeight', { value: 1000, configurable: true });
    Object.defineProperty(container, 'clientHeight', { value: 100, configurable: true });
    Object.defineProperty(container, 'scrollTop', { value: 0, configurable: true });
    scrollSpy.mockClear();
    emitDelta(0, '新内容');
    await new Promise((r) => setTimeout(r, 50));
    expect(scrollSpy).not.toHaveBeenCalled();
  });
});

describe('ChatPanel chat-UX — 思考过程与工具调用折叠块（#727）', () => {
  it('reasoning / tool_call 帧渲染为独立折叠块，默认折叠（aria-expanded=false）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '思考测试');
    const { callbacks } = capturedStreams[0];
    act(() => callbacks.onToolCall?.({ id: 't1', name: 'search_characters', args: {} }));
    act(() => callbacks.onToolResult?.({ id: 't1', name: 'search_characters', result: '{"ok":true}' }));
    emitReasoning(0, '让我想想…');
    expect(screen.getByTestId('chat-reasoning-0')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByTestId('chat-tool-0')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('让我想想…')).not.toBeInTheDocument();
  });

  it('点击 > 展开折叠块 → 思考/工具结果可见', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '展开测试');
    const { callbacks } = capturedStreams[0];
    act(() => callbacks.onToolCall?.({ id: 't1', name: 'search_characters', args: { project_id: 'p1' } }));
    act(() => callbacks.onToolResult?.({ id: 't1', name: 'search_characters', result: '{"ok":true,"data":[]}' }));
    emitReasoning(0, '让我想想…');
    await user.click(screen.getByTestId('chat-reasoning-0'));
    expect(screen.getByTestId('chat-reasoning-0')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('让我想想…')).toBeInTheDocument();
    await user.click(screen.getByTestId('chat-tool-0'));
    expect(screen.getByTestId('chat-tool-0')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('{"ok":true,"data":[]}')).toBeInTheDocument();
  });
});

describe('ChatPanel chat-UX — 每次提交+页面跳转自动滚到底（#745）', () => {
  it('每次提交消息后即使未处于底部 → 仍自动滚动到底部（scrollIntoView 被调用）', async () => {
    const scrollSpy = vi.fn();
    Element.prototype.scrollIntoView = scrollSpy as unknown as typeof Element.prototype.scrollIntoView;
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    // 首次提交（自动展开消息区）
    await sendAndAwaitStream(user, '第一次提交');
    expect(screen.getByTestId('chat-messages')).toBeInTheDocument();
    // 结束本轮流式，回到可发送态（chat-send）
    emitDone(0);
    await waitFor(() => expect(screen.getByTestId('chat-send')).toBeInTheDocument());
    const container = screen.getByTestId('chat-messages');
    // 模拟容器未处于底部（用户上滑阅读长回复）
    Object.defineProperty(container, 'scrollHeight', { value: 1000, configurable: true });
    Object.defineProperty(container, 'clientHeight', { value: 100, configurable: true });
    Object.defineProperty(container, 'scrollTop', { value: 0, configurable: true });
    scrollSpy.mockClear();
    // 第二次提交 → 应无条件滚到底
    await sendAndAwaitStream(user, '第二次提交', 1);
    await waitFor(() => expect(scrollSpy).toHaveBeenCalled());
  });

  it('页面跳转（项目切换重新加载历史）→ 自动滚动到底部', async () => {
    const scrollSpy = vi.fn();
    Element.prototype.scrollIntoView = scrollSpy as unknown as typeof Element.prototype.scrollIntoView;
    const user = userEvent.setup();
    // 首次挂载：空历史
    chatApiMocks.fetchChatMessages.mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 50 });
    const { rerender } = render(<ChatPanel {...OPTS} />);
    // 展开消息区（首次提交触发）
    await sendAndAwaitStream(user, '导航前');
    const container = screen.getByTestId('chat-messages');
    Object.defineProperty(container, 'scrollHeight', { value: 1000, configurable: true });
    Object.defineProperty(container, 'clientHeight', { value: 100, configurable: true });
    Object.defineProperty(container, 'scrollTop', { value: 0, configurable: true });
    // 导航：切换到新项目（重新加载历史）
    chatApiMocks.fetchChatMessages.mockResolvedValue({
      items: [
        { id: 'h1', project_id: 'p2', role: 'user', content: '历史问题', intent: null, created_at: '2026-08-21T10:00:00Z' },
        { id: 'h2', project_id: 'p2', role: 'ai', content: '历史回答', intent: 'content', created_at: '2026-08-21T10:00:01Z' },
      ],
      total: 2,
      offset: 0,
      limit: 50,
    });
    scrollSpy.mockClear();
    rerender(<ChatPanel {...OPTS} projectId="p2" />);
    await screen.findByTestId('chat-msg-ai-0');
    await waitFor(() => expect(scrollSpy).toHaveBeenCalled());
  });
});
