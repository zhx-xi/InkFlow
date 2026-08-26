/**
 * #681 管线帧与 chat 帧区分渲染契约（独立文件——原 ChatPanel.test.tsx 已 943 行超 900 护栏）
 *
 * 数据流：useExecutionPoll 把 streamPipeline 的帧透传给 streamSinkRef → ChatPanel streamSink prop。
 * RED 锁定两处真实 bug（GREEN 前）：
 * 1. 管线 delta 命中 sink.onDelta → 当前实现把它当 chat AI 消息（chat-msg-ai-0）渲染 → 断言
 *    应出现「管线输出」标签（pipeline-output-0）而非 AI 消息 → FAIL。
 * 2. 管线 delta + onDone → 当前实现复用 chat onDone → saveChatMessage 被调用 → 断言管线产物
 *    不落 chat 历史（saveChatMessage 不被调）→ FAIL。
 * GREEN 方向：ChatPanel 内部维护管线输出区（pipelineOutputEntries，data-testid=pipeline-output-<n>，
 *   带「管线输出」标签），与 chat messages 区分离；管线 sink 的 onDone 只落管线输出，不调 saveChatMessage。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import { apiFetch } from '../api/client';
import { executePipeline, getExecutionStatus } from '../api/pipeline';
import type { PipelineStreamFrame, PipelineStreamSink } from '../hooks/useExecutionPoll';
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
}));
vi.mock('../api/chat', () => chatApiMocks);

const apiFetchMock = vi.mocked(apiFetch);
const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);

const OPTS = { projectId: 'p1', chapterId: 'c1', chapterContent: '已有正文第一段。' };

const READY_PROVIDER: ProviderConfig = {
  id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
  models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }], key_saved: true,
  max_retries: 3, timeout: 60, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

beforeEach(() => {
  chatApiMocks.streamChat.mockReset();
  chatApiMocks.fetchChatMessages.mockReset();
  chatApiMocks.saveChatMessage.mockReset();
  chatApiMocks.fetchChatConversations.mockReset();
  chatApiMocks.archiveChatMessage.mockReset();
  chatApiMocks.deleteChatMessage.mockReset();
  chatApiMocks.restoreChatMessage.mockReset();
  chatApiMocks.archiveChatConversation.mockReset();
  chatApiMocks.deleteChatConversation.mockReset();
  chatApiMocks.fetchChatMessages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  chatApiMocks.deleteChatMessage.mockResolvedValue(undefined);
  chatApiMocks.archiveChatConversation.mockResolvedValue(undefined);
  chatApiMocks.deleteChatConversation.mockResolvedValue(undefined);
  chatApiMocks.saveChatMessage.mockResolvedValue({
    id: 'm-new', project_id: 'p1', role: 'user', content: '', intent: null, created_at: '2026-08-21T10:00:00Z',
  });
  chatApiMocks.fetchChatConversations.mockResolvedValue({ items: [], total: 0 });
  chatApiMocks.streamChat.mockImplementation(() => Promise.resolve(() => {}));
  executeMock.mockReset();
  statusMock.mockReset();
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    return { ok: true };
  });
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: [], chapters: [], treeProjectId: 'p1', currentChapterId: 'c1',
    content: '已有正文第一段。', loading: false, error: null,
  });
});

describe('ChatPanel — 管线帧与 chat 帧区分渲染（#681）', () => {
  let sinkRef: { current: PipelineStreamSink };
  beforeEach(() => {
    sinkRef = { current: {} as PipelineStreamSink };
  });

  it('管线 delta 命中 sink.onDelta → 以「管线输出」标签渲染，非普通 AI 消息（不污染 chat 历史）', async () => {
    render(<ChatPanel {...OPTS} streamSink={sinkRef} />);
    act(() => { sinkRef.current.onDelta?.('管线输出文本'); });
    // RED：当前实现把管线 delta 当 AI 消息（chat-msg-ai-0）渲染、无 pipeline-output 区 → 失败
    expect(screen.getByTestId('pipeline-output-0')).toHaveTextContent('管线输出文本');
  });

  it('管线 delta + onDone → 不调 saveChatMessage（管线产物不落 chat 历史）', async () => {
    render(<ChatPanel {...OPTS} streamSink={sinkRef} />);
    act(() => { sinkRef.current.onDelta?.('管线成品'); });
    act(() => {
      sinkRef.current.onDone?.({ type: 'done', done: true, final_output: '管线成品' } as PipelineStreamFrame);
    });
    expect(chatApiMocks.saveChatMessage).not.toHaveBeenCalled();
  });

  it('chat 帧（streamChat 路径）仍正常渲染 AI 消息并落库（#681 回归不破 chat 基线）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} streamSink={sinkRef} />);
    await user.type(screen.getByTestId('chat-input'), '正常对话');
    await user.click(screen.getByTestId('chat-send'));
    const captured = chatApiMocks.streamChat.mock.calls[0];
    await act(async () => { captured[1].onDelta('聊天回复'); });
    await act(async () => { captured[1].onDone({ done: true }); });
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('聊天回复');
    expect(chatApiMocks.saveChatMessage).toHaveBeenCalled();
  });
});
