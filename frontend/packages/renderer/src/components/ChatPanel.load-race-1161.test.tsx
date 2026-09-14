/**
 * #1161 挂载期历史加载竞态 + 用户消息 id 回填 —— 前端 RED 契约（specs/f47-chat-exec-detail/spec.md §18）。
 *
 * 真相源：ChatPanel.tsx 加载 effect（:163-241）+ handleSend（:400-457）+ handleDeleteMessage（:553-567）。
 *
 * 契约（§18.1 / §18.2）：
 *  - C1 陈旧快照：加载在途期间用户已发送（userSeqRef.current > 0 或 streamingRef.current）→
 *     落地段（conversationIdRef 回写 / seq ref 覆盖 / setMessages(history) / setToolEntries([]) /
 *     setSelectedSeq）整体丢弃 —— 不回写 ref、不覆盖消息、不归零 seq。无新消息时逐字不变。
 *  - C2 conversationId 被覆盖 = C1 同一守卫（:203 写入前判据）。
 *  - C3 用户消息 id 回填：saveChatMessage resolve 且返回 id → 函数式 setMessages 按
 *     kind==='user' && seq===该条seq 回填；删除按钮 testid 由 chat-msg-delete-user-<seq>
 *     切换为 chat-msg-delete-<id>，点击 → deleteChatMessage(id)。save 失败/无 id → 维持无 id
 *     形态（#581 兜底：仅本地移除）。
 *
 * RED 预期（当前实现）：C1/C2/C3 用例 FAIL（加载 effect 无守卫 + handleSend 丢弃 saved.id）；
 * 反例守护用例 PASS（锁既有行为不回归）。GREEN = 本文件全绿且既有 ChatPanel*.test.tsx 无回归。
 *
 * mock 形态逐字镜像 ChatPanel.conversation.test.tsx（vi.hoisted 聚合 + vi.mock('../api/chat')、
 * streamChat 捕获 callbacks 由用例手动驱动、每例前重置 store/provider）。
 * 可控时序：fetchChatMessages / fetchChatConversations 用 deferred promise 手动 resolve
 * （不用 fake timers —— 与既有测试同款真实定时器 + userEvent）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';
import { useThemeStore } from '../stores/theme';
import { useChapterStore } from '../stores/chapter';
import type { ChatConversationDto, ChatMessageDto } from '../api/chat';

// #1161 新文件：chat api mock 聚合（vi.hoisted 供 vi.mock 工厂引用，镜像 ChatPanel.conversation.test.tsx）
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

type MsgPage = { items: ChatMessageDto[]; total: number; offset: number; limit: number };
type ConvPage = { items: ChatConversationDto[]; total: number };

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

/** #1161：手动可控 promise（延迟 resolve 模拟慢加载） */
function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function msgPage(items: ChatMessageDto[]): MsgPage {
  return { items, total: items.length, offset: 0, limit: 50 };
}

function msg(
  id: string,
  role: 'user' | 'ai',
  content: string,
  intent: 'content' | 'conversation' | null = null,
): ChatMessageDto {
  return {
    id,
    conversation_id: 'conv-p1',
    project_id: 'p1',
    role,
    content,
    intent,
    created_at: '2026-09-14T09:00:00Z',
  };
}

function conv(conversationId: string, isDeleted = false): ChatConversationDto {
  return {
    conversation_id: conversationId,
    project_id: 'p1',
    project_name: null,
    last_message: '',
    message_count: 0,
    is_deleted: isDeleted,
    updated_at: '2026-09-14T09:00:00Z',
  };
}

async function sendAndAwaitStream(user: ReturnType<typeof userEvent.setup>, text: string, index = 0) {
  await user.type(screen.getByTestId('chat-input'), text);
  await user.click(screen.getByTestId('chat-send'));
  await waitFor(() => {
    expect(streamChatMock).toHaveBeenCalledTimes(index + 1);
  });
}

/** 驱动第 index 次流的 delta 帧（不驱动 done → streamingRef 保持 true） */
function emitDelta(index: number, text: string) {
  act(() => {
    capturedStreams[index].callbacks.onDelta(text);
  });
}

/** delta + done（done 后 streamingRef 复位，可再次发送） */
function driveConversationReply(index: number, text: string) {
  act(() => {
    capturedStreams[index].callbacks.onDelta(text);
    capturedStreams[index].callbacks.onDone({ done: true });
  });
}

/** 仅取 role==='user' 的 saveChatMessage body —— AI done 同样落库，按下标盲取会错位 */
function userSaves(): { role: string; conversation_id: string }[] {
  return chatApiMocks.saveChatMessage.mock.calls
    .map((c) => c[0] as { role: string; conversation_id: string })
    .filter((b) => b.role === 'user');
}

beforeEach(() => {
  streamChatMock.mockReset();
  capturedStreams = [];
  chatApiMocks.fetchChatMessages.mockReset();
  chatApiMocks.saveChatMessage.mockReset();
  chatApiMocks.fetchChatConversations.mockReset();
  chatApiMocks.deleteChatMessage.mockReset();
  chatApiMocks.archiveChatConversation.mockReset();
  chatApiMocks.deleteChatConversation.mockReset();
  chatApiMocks.createChatConversation.mockReset();
  chatApiMocks.fetchChatMessages.mockResolvedValue(msgPage([]));
  chatApiMocks.deleteChatMessage.mockResolvedValue(undefined);
  chatApiMocks.saveChatMessage.mockResolvedValue(msg('m-new', 'user', ''));
  chatApiMocks.fetchChatConversations.mockResolvedValue({ items: [], total: 0 });
  // 无活动线程 → 挂载期建新线程 conv-<projectId>（镜像既有 conversation 契约）
  chatApiMocks.createChatConversation.mockImplementation(async (projectId: string) => conv(`conv-${projectId}`));
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

/* ============================ #1161 C1 / C2 加载竞态（陈旧快照整体丢弃） ============================ */

describe('ChatPanel — #1161 C1 陈旧快照丢弃（加载在途发送）', () => {
  it('C1：加载在途期间发送 → 陈旧空快照落地被丢弃（用户消息不被抹）+ 后续发送不重号', async () => {
    const load = deferred<MsgPage>();
    chatApiMocks.fetchChatMessages.mockReturnValue(load.promise);

    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-p1');
    });

    // ① 加载在途（未 resolve）→ 用户发送
    await sendAndAwaitStream(user, '竞态提问');
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('竞态提问');

    // ② 陈旧快照此刻才落地（空历史）——必须整体丢弃，不回写 seq / 不覆盖消息
    await act(async () => {
      load.resolve(msgPage([]));
    });
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('竞态提问');

    // ③ seq 计数器未被归零 → 第二条编号 1（不重号）
    driveConversationReply(0, '竞态回答');
    await sendAndAwaitStream(user, '第二条', 1);
    expect(screen.getByTestId('chat-msg-user-1')).toHaveTextContent('第二条');
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('竞态提问');
  });

  it('C1：流式在途（done 帧未到）时陈旧快照落地 → 流式消息与用户消息均不被抹', async () => {
    const load = deferred<MsgPage>();
    chatApiMocks.fetchChatMessages.mockReturnValue(load.promise);

    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-p1');
    });

    await sendAndAwaitStream(user, '流式提问');
    emitDelta(0, '流式回答片段'); // ✓ 流式中：streamingRef.current === true，done 未到
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('流式回答片段');

    await act(async () => {
      load.resolve(msgPage([]));
    });
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('流式回答片段');
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('流式提问');
  });
});

describe('ChatPanel — #1161 C2 conversationId 不被慢加载回写', () => {
  it('C2：慢加载解析出的旧会话不得覆盖 handleSend 新建的 conversationId', async () => {
    // 加载卡在 fetchChatConversations（:203 之前）→ handleSend 期间 conversationIdRef 仍为 null
    const convs = deferred<ConvPage>();
    chatApiMocks.fetchChatConversations.mockReturnValue(convs.promise);
    chatApiMocks.createChatConversation.mockResolvedValue(conv('conv-new'));

    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatConversations).toHaveBeenCalledWith({
        projectId: 'p1',
        includeDeleted: false,
      });
    });

    // ① 发送 → 本地新建会话 conv-new（ref 指向新值）
    await sendAndAwaitStream(user, '先把消息发出去');
    expect(chatApiMocks.createChatConversation).toHaveBeenCalledWith('p1');
    expect(userSaves()[0].conversation_id).toBe('conv-new');
    driveConversationReply(0, '回答');

    // ② 慢加载此刻才落地：解析到旧活动线程 conv-old → 不得回写 ref、不得覆盖消息
    await act(async () => {
      convs.resolve({ items: [conv('conv-old')], total: 1 });
    });
    await sendAndAwaitStream(user, '第二条', 1);
    expect(userSaves()[1].conversation_id).toBe('conv-new');
    // C1 同源：陈旧快照里的历史（空）不得抹掉本地消息
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('先把消息发出去');
  });
});

/* ============================ #1161 C3 用户消息 id 回填 → 真删服务端 ============================ */

describe('ChatPanel — #1161 C3 用户消息 id 回填', () => {
  it('C3：save 返回 id → 删除按钮 testid 切换 chat-msg-delete-<id>；点击 → deleteChatMessage(id) + 本地移除', async () => {
    // 历史已落地（空）后再发送 → 隔离 C3，不掺 C1 竞态
    const load = deferred<MsgPage>();
    chatApiMocks.fetchChatMessages.mockReturnValue(load.promise);
    chatApiMocks.saveChatMessage.mockResolvedValue(msg('m-9', 'user', '待删消息'));

    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-p1');
    });
    await act(async () => {
      load.resolve(msgPage([]));
    });

    await sendAndAwaitStream(user, '待删消息');
    // 流式新发（尚无 id）→ 无 id 形态 testid
    expect(screen.getByTestId('chat-msg-delete-user-0')).toBeInTheDocument();
    // save resolve 后回填 id → testid 切换为 id 形态
    await waitFor(() => {
      expect(screen.getByTestId('chat-msg-delete-m-9')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('chat-msg-delete-user-0')).not.toBeInTheDocument();

    // 点击 → 真删（服务端）+ 本地移除
    await user.click(screen.getByTestId('chat-msg-delete-m-9'));
    expect(chatApiMocks.deleteChatMessage).toHaveBeenCalledWith('m-9');
    expect(screen.queryByTestId('chat-msg-user-0')).not.toBeInTheDocument();
  });

  it('C3 兜底：save 失败 → 维持无 id 形态；点击仅本地移除（deleteChatMessage 不被调）', async () => {
    const load = deferred<MsgPage>();
    chatApiMocks.fetchChatMessages.mockReturnValue(load.promise);
    chatApiMocks.saveChatMessage.mockRejectedValue(new Error('落库失败'));

    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-p1');
    });

    await sendAndAwaitStream(user, '落库会失败的消息');
    driveConversationReply(0, '回答');
    // 陈旧快照（空历史）落地不得抹掉本地消息（C1 同源），兜底分支才有意义
    await act(async () => {
      load.resolve(msgPage([]));
    });
    expect(screen.getByTestId('chat-msg-delete-user-0')).toBeInTheDocument();

    await user.click(screen.getByTestId('chat-msg-delete-user-0'));
    expect(chatApiMocks.deleteChatMessage).not.toHaveBeenCalled();
    expect(screen.queryByTestId('chat-msg-user-0')).not.toBeInTheDocument();
  });
});

/* ============================ #1161 反例守护：无新消息时加载行为逐字不变 ============================ */

describe('ChatPanel — #1161 反例守护（正常加载历史不回归）', () => {
  it('反例：无新消息时历史逐条渲染（seq 基）+ 历史 id 透传删除按钮 + seq 计数对齐服务端', async () => {
    chatApiMocks.fetchChatMessages.mockResolvedValue(
      msgPage([msg('h-user', 'user', '历史提问'), msg('h-ai', 'ai', '历史回答', 'conversation')]),
    );

    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-p1');
    });
    await user.click(screen.getByTestId('chat-expand'));
    await waitFor(() => {
      expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('历史提问');
    });

    // 消息体 testid 不变（seq 基，role 独立计数）
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('历史回答');
    // 历史 id 透传 → 删除按钮 id 形态（#566 兼容）
    expect(screen.getByTestId('chat-msg-delete-h-user')).toBeInTheDocument();
    expect(screen.getByTestId('chat-msg-delete-h-ai')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-msg-delete-user-0')).not.toBeInTheDocument();

    // seq 计数对齐服务端：历史 1 条 user → 下一轮发送编号 1（加载未被误丢弃）
    await sendAndAwaitStream(user, '加载后的新提问');
    expect(screen.getByTestId('chat-msg-user-1')).toHaveTextContent('加载后的新提问');
  });
});
