/**
 * ChatPanel 错误路径契约（#487 写入页聊天框回车偶发关闭 GUI + 内核）
 *
 * 独立文件（镜像 ChatPanel.test.tsx / ChatPanel.chat-ux.test.tsx 命名风格），
 * 不与既有 ChatPanel.test.tsx（44 用例）同文件互相干扰。
 *
 * 契约（#487，设计来驱动 GREEN）：handleSend 对 `await ensureModelReady()` 的拒绝必须被
 * 显式捕获（pushToast('err'...) + 不 rethrow），绝不允许经由 `void handleSend()`（L525）
 * 产生 unhandled promise rejection；且该路径绝不触发 window.close。
 *
 * 现状（RED）：ensureModelReady → loadProviders 拒绝时 handleSend 无 try/catch →
 * unhandled rejection（vitest 以 unhandledRejection 上报）+ 无 err toast。修复后 GREEN。
 *
 * 守卫（当前已通过）：正常路径回车后 streamChat 被调用、window.close 未被调用。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import { apiFetch } from '../api/client';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

/** 复用 ChatPanel.test.tsx 的 chat api 聚合 mock 形态（独立文件，避免跨文件 mock 状态污染） */
const chatApiMocks = vi.hoisted(() => ({
  streamChat: vi.fn(),
  fetchChatMessages: vi.fn(),
  saveChatMessage: vi.fn(),
  fetchChatConversations: vi.fn(),
  createChatConversation: vi.fn(),
}));
vi.mock('../api/chat', () => chatApiMocks);

const streamChatMock = chatApiMocks.streamChat;
const apiFetchMock = vi.mocked(apiFetch);

const OPTS = { projectId: 'p1' };

/** 已配置模型（key_saved=true + chat 模型）——确保 ensureModelReady 正常路径通过 */
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

/** 采原始 loadProviders（ensureModelReady 经 getState().loadProviders 调用）——beforeEach 复位用 */
const originalLoadProviders = useModelsStore.getState().loadProviders;

beforeEach(() => {
  streamChatMock.mockReset();
  chatApiMocks.fetchChatMessages.mockReset();
  chatApiMocks.saveChatMessage.mockReset();
  chatApiMocks.fetchChatConversations.mockReset();
  chatApiMocks.createChatConversation.mockReset();
  chatApiMocks.fetchChatMessages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
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
  chatApiMocks.createChatConversation.mockImplementation(async (projectId: string) => ({
    conversation_id: `conv-${projectId}`,
    project_id: projectId,
    project_name: null,
    last_message: '',
    message_count: 0,
    is_deleted: false,
    updated_at: '2026-08-21T10:00:00Z',
  }));
  streamChatMock.mockImplementation(() => Promise.resolve(() => {}));
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    }
    return { ok: true };
  });
  useModelsStore.setState({
    providers: [READY_PROVIDER],
    loading: false,
    error: null,
    loadProviders: originalLoadProviders,
  });
  useToastStore.setState({ toasts: [] });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ChatPanel — #487 发送错误（ensureModelReady 拒绝）不得关闭窗口 / 无 unhandled rejection', () => {
  it('守卫：正常路径回车 → streamChat 被调用 + window.close 未被调用（当前已通过）', async () => {
    const windowCloseSpy = vi.spyOn(window, 'close');
    try {
      const user = userEvent.setup();
      render(<ChatPanel {...OPTS} />);
      await user.type(screen.getByTestId('chat-input'), 'hello');
      await user.keyboard('{Enter}');
      await waitFor(() => expect(streamChatMock).toHaveBeenCalledTimes(1));
      expect(windowCloseSpy).not.toHaveBeenCalled();
    } finally {
      windowCloseSpy.mockRestore();
    }
  });

  it('RED：ensureModelReady 拒绝 → 推 err/warn toast（当前无 toast → 失败）', async () => {
    useModelsStore.setState({
      providers: [],
      loading: false,
      error: null,
      loadProviders: vi.fn().mockRejectedValue(new Error('KernelOfflineError')),
    });
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), 'hello');
    await user.keyboard('{Enter}');
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(useToastStore.getState().toasts.some((t) => t.type === 'err' || t.type === 'warn')).toBe(true);
  });

  it('RED：ensureModelReady 拒绝 → window.close 未被调用 + streamChat 未被调用 + 无 unhandled rejection', async () => {
    useModelsStore.setState({
      providers: [],
      loading: false,
      error: null,
      loadProviders: vi.fn().mockRejectedValue(new Error('KernelOfflineError')),
    });
    const windowCloseSpy = vi.spyOn(window, 'close');
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown): void => {
      unhandled.push(reason);
    };
    process.on('unhandledRejection', onUnhandled);
    try {
      const user = userEvent.setup();
      render(<ChatPanel {...OPTS} />);
      await user.type(screen.getByTestId('chat-input'), 'hello');
      await user.keyboard('{Enter}');
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(windowCloseSpy).not.toHaveBeenCalled();
      expect(streamChatMock).not.toHaveBeenCalled();
      // 契约：handleSend 必须捕获 ensureModelReady 拒绝 → 无 unhandled rejection
      expect(unhandled).toHaveLength(0);
    } finally {
      process.off('unhandledRejection', onUnhandled);
      windowCloseSpy.mockRestore();
    }
  });
});