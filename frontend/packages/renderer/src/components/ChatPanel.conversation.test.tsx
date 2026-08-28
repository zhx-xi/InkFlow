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
import { ChatPanel } from './ChatPanel';
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
