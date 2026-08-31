/**
 * #744 conversation 多线程（归档后开新线程）专属契约测试 —— 自 ChatPanel.test.tsx 拆出，
 * 使其 ≤900 行护栏。用例：
 * - 挂载即解析活动线程（fetchChatConversations({projectId, includeDeleted:false})，无 →
 *   createChatConversation 建新）→ fetchChatMessages(conversationId) 加载历史。
 * - projectId 变化 → 重新走 conversation 解析。
 * - 整轮归档 → archiveChatConversation(conversationId) 后 createChatConversation 开新线程。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel, type ChatPanelProps } from './ChatPanel';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';
import { useThemeStore } from '../stores/theme';
import { useChapterStore } from '../stores/chapter';

// #744 新文件：chat api mock 聚合（vi.hoisted 供 vi.mock 工厂引用，镜像 ChatPanel.test.tsx 模式）
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
}));
vi.mock('../api/chat', () => chatApiMocks);
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock('../api/pipeline', () => ({
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));
const streamChatMock = chatApiMocks.streamChat;

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

function driveConversationReply(index: number, text: string) {
  act(() => {
    capturedStreams[index].callbacks.onDelta(text);
    capturedStreams[index].callbacks.onDone({ done: true });
  });
}

beforeEach(() => {
  streamChatMock.mockReset();
  capturedStreams = [];
  chatApiMocks.fetchChatMessages.mockReset();
  chatApiMocks.saveChatMessage.mockReset();
  chatApiMocks.fetchChatConversations.mockReset();
  chatApiMocks.archiveChatConversation.mockReset();
  chatApiMocks.deleteChatConversation.mockReset();
  chatApiMocks.createChatConversation.mockReset();
  chatApiMocks.fetchChatMessages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  chatApiMocks.archiveChatConversation.mockResolvedValue(undefined);
  chatApiMocks.deleteChatConversation.mockResolvedValue(undefined);
  chatApiMocks.saveChatMessage.mockResolvedValue({
    id: 'm-new',
    conversation_id: 'conv-p1',
    project_id: 'p1',
    role: 'user',
    content: '',
    intent: null,
    created_at: '2026-08-21T10:00:00Z',
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
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: [],
    chapters: [],
    treeProjectId: 'p1',
    currentChapterId: 'c1',
    content: '已有正文第一段。',
    loading: false,
    error: null,
  });
});

describe('ChatPanel — #744 conversation 多线程（归档后开新线程）', () => {
  it('挂载即解析活动线程：fetchChatConversations({projectId, includeDeleted:false})（空 → createChatConversation 建新）→ fetchChatMessages(conversationId) 载历史', async () => {
    chatApiMocks.fetchChatMessages.mockResolvedValue({
      items: [
        {
          id: 'm1',
          conversation_id: 'conv-p1',
          project_id: 'p1',
          role: 'user',
          content: '之前的提问',
          intent: null,
          created_at: '2026-08-20T08:00:00Z',
        },
      ],
      total: 1,
      offset: 0,
      limit: 50,
    });
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatConversations).toHaveBeenCalledWith({ projectId: 'p1', includeDeleted: false });
    });
    await waitFor(() => {
      expect(chatApiMocks.createChatConversation).toHaveBeenCalledWith('p1');
    });
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-p1');
    });
    await user.click(screen.getByTestId('chat-expand'));
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('之前的提问');
  });

  it('projectId 变化 → 重新走 conversation 解析（fetchChatConversations({projectId:p2}) → createChatConversation(p2) → fetchChatMessages(conv-p2)）', async () => {
    const { rerender } = render(<ChatPanel projectId="p1" />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-p1');
    });
    rerender(<ChatPanel projectId="p2" />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatConversations).toHaveBeenCalledWith({ projectId: 'p2', includeDeleted: false });
    });
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-p2');
    });
  });

  it('#744 核心：整轮归档 → archiveChatConversation(conversationId) 后 createChatConversation 开新线程（新 conversation_id）', async () => {
    chatApiMocks.createChatConversation
      .mockResolvedValueOnce({
        conversation_id: 'conv-p1',
        project_id: 'p1',
        project_name: null,
        last_message: '',
        message_count: 0,
        is_deleted: false,
        updated_at: '2026-08-21T10:00:00Z',
      })
      .mockResolvedValueOnce({
        conversation_id: 'conv-p1-new',
        project_id: 'p1',
        project_name: null,
        last_message: '',
        message_count: 0,
        is_deleted: false,
        updated_at: '2026-08-21T10:01:00Z',
      });
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '问一句');
    driveConversationReply(0, '答一句');
    await user.click(screen.getByTestId('chat-round-archive'));
    expect(chatApiMocks.archiveChatConversation).toHaveBeenCalledWith('conv-p1');
    expect(chatApiMocks.createChatConversation).toHaveBeenCalledTimes(2);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-p1-new');
    });
    await waitFor(() => {
      expect(screen.queryByTestId('chat-msg-user-0')).not.toBeInTheDocument();
    });
    expect(useToastStore.getState().toasts.some((t) => t.type === 'ok' && /归档/.test(t.message))).toBe(true);
  });

  it('#744 回归：挂载时 fetchChatConversations 返回其它项目活动线程 → 不选中（按 project_id 过滤）→ 为本项目 createChatConversation 建新', async () => {
    // 后端 GET /conversations 忽略 project_id 返回全部，含其它项目（p9）活动线程
    chatApiMocks.fetchChatMessages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
    chatApiMocks.fetchChatConversations.mockResolvedValue({
      items: [
        {
          conversation_id: 'conv-other',
          project_id: 'p9',
          project_name: '另一项目',
          last_message: '别的项目消息',
          message_count: 1,
          is_deleted: false,
          updated_at: '2026-08-21T10:00:00Z',
        },
      ],
      total: 1,
    });
    render(<ChatPanel {...OPTS} />);
    // 不应加载其它项目线程
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).not.toHaveBeenCalledWith('conv-other');
    });
    // 应为当前项目 p1 建新线程并加载其空历史
    await waitFor(() => {
      expect(chatApiMocks.createChatConversation).toHaveBeenCalledWith('p1');
    });
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-p1');
    });
  });
});

/* ============================== #770 ChatPanel variant 契约（full / inline） ============================== */

describe('ChatPanel — #770 variant 契约（full 无 resize handle / inline 可调）', () => {
  it('variant="full" → 不渲染 chat-resize-handle；容器 chat-panel 含 flex-1 占满', async () => {
    // RED：ChatPanelProps 尚无 variant（#770 增量，f47 §17.4.1）。契约先行：扩展类型携带 variant 渲染；
    // GREEN 将 variant?: 'inline' | 'full' 并入 ChatPanelProps 后可直接 <ChatPanel variant="full" />。
    type FullVariantProps = ChatPanelProps & { variant: 'full' };
    render(<ChatPanel {...({ ...OPTS, variant: 'full' } as FullVariantProps)} />);
    await screen.findByTestId('chat-panel');
    // RED：当前恒渲染 resize handle + 无 flex-1 → FAIL
    expect(screen.queryByTestId('chat-resize-handle')).not.toBeInTheDocument();
    expect(screen.getByTestId('chat-panel')).toHaveClass('flex-1');
  });

  it('默认 inline → 渲染 chat-resize-handle（回归守护，当前实现通过）', async () => {
    render(<ChatPanel {...OPTS} />);
    await screen.findByTestId('chat-panel');
    expect(screen.getByTestId('chat-resize-handle')).toBeInTheDocument();
  });
});

/* ============================== #840 conversationId prop 加载指定会话 ============================== */

describe('ChatPanel — #840 conversationId prop 加载指定会话（点击会话贯通）', () => {
  it('#840：传 conversationId prop → 直接加载该指定会话历史（不解析最新活跃线程、不新建线程）', async () => {
    chatApiMocks.fetchChatMessages.mockResolvedValue({
      items: [
        {
          id: 'rm1',
          conversation_id: 'conv-restored',
          project_id: 'p1',
          role: 'user',
          content: '恢复后的会话历史',
          intent: null,
          created_at: '2026-08-30T09:00:00Z',
        },
      ],
      total: 1,
      offset: 0,
      limit: 50,
    });
    // 即便 GET /conversations 返回空（无活动线程），conversationId 指定后也应直接加载该会话
    chatApiMocks.fetchChatConversations.mockResolvedValue({ items: [], total: 0 });
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} conversationId="conv-restored" />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-restored');
    });
    // 指定会话后不应走 createChatConversation 建新线程
    expect(chatApiMocks.createChatConversation).not.toHaveBeenCalled();
    await user.click(screen.getByTestId('chat-expand'));
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('恢复后的会话历史');
  });

  it('#840：conversationId prop 变化 → 重新加载对应会话（切换会话）', async () => {
    chatApiMocks.fetchChatMessages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
    const { rerender } = render(<ChatPanel {...OPTS} conversationId="conv-A" />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-A');
    });
    rerender(<ChatPanel {...OPTS} conversationId="conv-B" />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-B');
    });
  });
});
