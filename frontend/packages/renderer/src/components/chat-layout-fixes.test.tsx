/**
 * #642-2 契约（前端组件测试，TDD RED→GREEN）：chat 面板 DOM 布局顺序修正。
 * 用户确认布局（自上而下）:
 *   ① 顶部行: [chat-collapse/chat-expand toggle] + [chat-resize-handle]
 *   ② 消息区: [chat-messages]（每条 AI 回复后跟 [复制对话][插入到正文] per-message）
 *   ③ 输入行: [chat-input][chat-send]
 *   ④ 底部: [chat-round-archive][chat-round-delete]
 * 现状（BUG）：resize 在底部（输入框下方），insert 是底部全局 chat-insert-selected，
 *   与「resize 在顶部、插入 per-message、底部仅整轮操作」的布局相反。
 * compareDocumentPosition 语义：A.compareDocumentPosition(B) & FOLLOWING = B 在 A 之后。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import { useThemeStore } from '../stores/theme';
import { useChapterStore } from '../stores/chapter';
import { useToastStore } from '../stores/toast';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

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

const apiFetchMock = vi.mocked(apiFetch);

const READY_PROVIDER: ProviderConfig = {
  id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
  models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }], key_saved: true,
  max_retries: 3, timeout: 60, created_at: '', updated_at: '',
};

const OPTS = { projectId: 'p1', chapterId: 'c1', chapterContent: '已有正文第一段。' };

beforeEach(() => {
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({ volumes: [], chapters: [], treeProjectId: 'p1', currentChapterId: 'c1', content: '正文', loading: false, error: null });
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
  chatApiMocks.fetchChatMessages.mockReset();
  chatApiMocks.streamChat.mockReset();
  chatApiMocks.saveChatMessage.mockReset();
  chatApiMocks.fetchChatConversations.mockReset();
  chatApiMocks.createChatConversation.mockReset();
  chatApiMocks.fetchChatMessages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  chatApiMocks.saveChatMessage.mockResolvedValue({ id: 'm-new', conversation_id: 'conv-p1', project_id: 'p1', role: 'ai', content: '', intent: null, created_at: '' });
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
  // #642-2：流式产出 content 意图消息（含 >>>CONTENT>>> 标记），使 per-message 复制/插入按钮都渲染
  chatApiMocks.streamChat.mockImplementation(
    (_body: { project_id: string; prompt: string; chapter_id?: string; chapter_context?: string },
     callbacks: { onDelta: (delta: string) => void; onDone: (frame: { done: boolean }) => void; onError: (message: string) => void },
    ) => {
      callbacks.onDelta('\n<<<CONTENT>>>\n他握紧了剑。\n<<<END>>>');
      callbacks.onDone({ done: true });
      return Promise.resolve(() => {});
    },
  );
});

describe('ChatPanel — 布局顺序修正（#642-2）', () => {
  it('①顶部行=toggle+resize / ②输入框在消息区下方 / ③底部=整轮操作 / 每条 AI 回复后跟复制+插入', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    // 发送一条消息（content 意图），展开消息区 + 渲染 per-message 复制/插入
    await user.type(screen.getByTestId('chat-input'), '写一段正文');
    await user.click(screen.getByTestId('chat-send'));
    await screen.findByTestId('chat-messages');

    const input = screen.getByTestId('chat-input');
    const messages = screen.getByTestId('chat-messages');
    const roundArchive = screen.getByTestId('chat-round-archive');
    const roundDelete = screen.getByTestId('chat-round-delete');
    const resize = screen.getByTestId('chat-resize-handle');
    const toggle = screen.getByTestId('chat-collapse');
    const copy0 = screen.getByTestId('chat-copy-0');
    const insert0 = screen.getByTestId('chat-insert-0');

    // RED：① resize 当前在 input 之后（底部）→ resize 在 messages 之前断言 FAIL；
    //      toggle 在 messages 之前（#542 回归，保持）
    expect(toggle.compareDocumentPosition(messages) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(resize.compareDocumentPosition(messages) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // ② 消息区在 input 之前（输入框在消息区下方）
    expect(messages.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // ③ 底部整轮操作在 input 之后
    expect(input.compareDocumentPosition(roundArchive) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(input.compareDocumentPosition(roundDelete) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // per-message：每条 AI 回复后跟复制 + 插入按钮（现状无 per-message 按钮 → getByTestId FAIL）
    expect(copy0).toBeInTheDocument();
    expect(insert0).toBeInTheDocument();
  });
});
