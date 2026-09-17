/**
 * #1248 ChatPanel 泄漏 setTimeout 致 unmount 后 setState —— 前端 RED 契约。
 *
 * 真相源：ChatPanel.tsx handleSend 的 saveChatMessage().then 段（:447-458，#1161 C3 id 回填
 * 100ms 延迟定时器，从未 clearTimeout）+ unmount 清理 effect（:517-522）。
 *
 * 缺陷链（issue #1248 栈帧）：save resolve → setTimeout(100ms) 无清理 → 测试在 100ms 内
 * 结束 → 组件 unmount / jsdom 环境拆除 → 定时器仍触发 → setMessages → React
 * dispatchSetState → resolveUpdatePriority 访问 window → Node 上下文无 window →
 * ReferenceError: window is not defined → Vitest Unhandled Error → unit-frontend 退出码 1。
 *
 * 契约：
 *  - 1248-1（清理）：存在在途回填定时器时 unmount → 该定时器句柄被 clearTimeout。
 *  - 1248-2（行为，复现栈帧形态）：unmount 后模拟 window 不可用（stubGlobal undefined，
 *    与 CI「jsdom 已拆除」等价根因；异常为 TypeError 而非 ReferenceError，同源）→
 *    推进 timer 越过 100ms 不得抛异常（泄漏形态下 React 访问 window.event 必抛）。
 *  - 1248-3（不劣化守护）：不 unmount → 推进 100ms → id 回填正常生效
 *    （chat-msg-delete-user-<seq> → chat-msg-delete-<id>，#1161 C3 契约零回归）。
 *
 * RED 预期（当前实现）：1248-1 / 1248-2 FAIL（无 clearTimeout → 定时器 unmount 后仍触发）；
 * 1248-3 PASS（锁既有回填行为）。GREEN = 本文件全绿且既有 ChatPanel*.test.tsx 零回归。
 *
 * mock 形态逐字镜像 ChatPanel.load-race-1161.test.tsx（vi.hoisted 聚合 + vi.mock('../api/chat')、
 * streamChat 捕获 callbacks、deferred 手动控制 save resolve 时机、每例前重置 store/provider）。
 * 定时器控制：fake timers（setup.ts 兜底 shouldAdvanceTime=true → userEvent 正常；save 的
 * deferred 在交互完成后才 resolve → 100ms 回填定时器不会在断言窗口前自动触发）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';
import { useThemeStore } from '../stores/theme';
import { useChapterStore } from '../stores/chapter';
import type { ChatConversationDto, ChatMessageDto } from '../api/chat';

// #1248 新文件：chat api mock 聚合（vi.hoisted 供 vi.mock 工厂引用，镜像 load-race-1161）
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

/** #1248：手动可控 promise（精确控制 saveChatMessage resolve 时机） */
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
    created_at: '2026-09-17T09:00:00Z',
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
    updated_at: '2026-09-17T09:00:00Z',
  };
}

async function sendAndAwaitStream(user: ReturnType<typeof userEvent.setup>, text: string, index = 0) {
  await user.type(screen.getByTestId('chat-input'), text);
  await user.click(screen.getByTestId('chat-send'));
  await waitFor(() => {
    expect(streamChatMock).toHaveBeenCalledTimes(index + 1);
  });
}

/**
 * #1248 公共前置：render → 历史加载落地（空）→ 发送一条消息 → save 处于 deferred pending。
 * 返回 { view, save }：save.resolve 后 #1161 C3 的 100ms 回填定时器才被排入时钟，
 * 由用例精确控制「resolve → unmount → 推进 timer」的时序窗口。
 */
async function renderSendWithPendingSave(user: ReturnType<typeof userEvent.setup>) {
  const save = deferred<ChatMessageDto>();
  chatApiMocks.saveChatMessage.mockReturnValue(save.promise);
  chatApiMocks.fetchChatMessages.mockResolvedValue(msgPage([]));

  const view = render(<ChatPanel {...OPTS} />);
  await waitFor(() => {
    expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('conv-p1');
  });
  await sendAndAwaitStream(user, '泄漏探针消息');
  return { view, save };
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

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/* ============================ #1248 泄漏定时器清理契约 ============================ */

describe('ChatPanel — #1248 泄漏 setTimeout 清理（unmount 后不 setState）', () => {
  it('1248-1：存在在途回填定时器时 unmount → 该定时器句柄被 clearTimeout', async () => {
    vi.useFakeTimers();
    const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout');
    const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout');

    const user = userEvent.setup();
    const { view, save } = await renderSendWithPendingSave(user);

    // save resolve → .then 排入 100ms 回填定时器（#1161 C3）
    await act(async () => {
      save.resolve(msg('m-9', 'user', '泄漏探针消息'));
    });
    const idx = setTimeoutSpy.mock.calls.findIndex((c) => c[1] === 100);
    expect(idx).toBeGreaterThanOrEqual(0); // 回填定时器确已排入时钟
    const handle = setTimeoutSpy.mock.results[idx]?.value;
    expect(handle).toBeDefined();

    // 定时器未到期即 unmount → 清理必须清掉在途回填定时器
    view.unmount();
    expect(clearTimeoutSpy).toHaveBeenCalledWith(handle);
  });

  it('1248-2：unmount 后模拟 window 不可用 → 推进 timer 越过 100ms 不得抛异常（复现 #1248 栈帧根因）', async () => {
    vi.useFakeTimers();

    const user = userEvent.setup();
    const { view, save } = await renderSendWithPendingSave(user);
    await act(async () => {
      save.resolve(msg('m-9', 'user', '泄漏探针消息'));
    });

    view.unmount();
    // 模拟 CI 失败形态：测试结束后 jsdom 环境已拆除 → window 不可用。
    // stubGlobal(undefined) 下 React resolveUpdatePriority 访问 window.event 抛
    // TypeError（CI 中为 ReferenceError: window is not defined，同一根因）。
    vi.stubGlobal('window', undefined);
    try {
      // RED（泄漏）：定时器仍触发 → setMessages → dispatchSetState → 访问 window → 抛。
      // GREEN（清理）：unmount 已 clearTimeout → 无回调 → 不抛。
      expect(() => vi.advanceTimersByTime(200)).not.toThrow();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('1248-3：不 unmount → 推进 100ms → id 回填正常生效（#1161 C3 契约不劣化）', async () => {
    vi.useFakeTimers();

    const user = userEvent.setup();
    const { save } = await renderSendWithPendingSave(user);

    // 回填定时器到期前：仍是无 id 形态 testid（seq 基）
    await act(async () => {
      save.resolve(msg('m-9', 'user', '泄漏探针消息'));
    });
    expect(screen.getByTestId('chat-msg-delete-user-0')).toBeInTheDocument();

    // 推进越过 100ms → setMessages 回填 id → testid 切换（既有 C3 语义不变）
    await act(async () => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.getByTestId('chat-msg-delete-m-9')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-msg-delete-user-0')).not.toBeInTheDocument();
  });
});
