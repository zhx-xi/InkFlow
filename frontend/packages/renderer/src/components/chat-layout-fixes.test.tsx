/**
 * #642-2 契约（前端组件测试，TDD RED→GREEN）：chat 面板 DOM 布局顺序修正。
 * 现状（BUG）：chat 输入框渲染在消息区之上（[toggle|input|send] → messages → controls），
 * 与「输入框在消息区下方、控制块在输入框下方」的设计布局相反（rc4 报告「位置反了」）。
 * 目标布局（自上而下，满足 #542「按钮应在对话区顶部」不回归）：
 *   [chat-expand/chat-collapse toggle] → [chat-messages] → [chat-input|chat-send] → [round-actions] → [chat-resize-handle]
 *
 * ⚠️ 本文件 = #642-2 契约。当前实现 FAIL（输入框在消息区之前），GREEN 实现必须匹配。
 * compareDocumentPosition 语义：A.compareDocumentPosition(B) & FOLLOWING = B 在 A 之后（A 在 B 之前）。
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
  chatApiMocks.fetchChatMessages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  // #547：ChatPanel 发送时 fire-and-forget 调 saveChatMessage(...).catch(noop)；mock 必须 resolve 不然 unhandled rejection
  chatApiMocks.saveChatMessage.mockResolvedValue({ id: 'm-new', project_id: 'p1', role: 'ai', content: '', intent: null, created_at: '' });
  chatApiMocks.streamChat.mockImplementation((
    _body: { project_id: string; prompt: string; chapter_id?: string; chapter_context?: string },
    callbacks: { onDelta: (delta: string) => void; onDone: (frame: { done: boolean }) => void },
  ) => {
    callbacks.onDelta('AI 回复');
    callbacks.onDone({ done: true });
    return Promise.resolve(() => {});
  });
});

describe('ChatPanel — 布局顺序修正（#642-2）', () => {
  it('输入框位于消息区下方；控制块（round-actions/resize）位于输入框下方；按钮开关在顶部', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    // 发送一条消息，展开消息区
    await user.type(screen.getByTestId('chat-input'), '你好');
    await user.click(screen.getByTestId('chat-send'));
    await screen.findByTestId('chat-messages');

    const input = screen.getByTestId('chat-input');
    const messages = screen.getByTestId('chat-messages');
    const roundArchive = screen.getByTestId('chat-round-archive');
    const roundDelete = screen.getByTestId('chat-round-delete');
    const resize = screen.getByTestId('chat-resize-handle');
    const toggle = screen.getByTestId('chat-collapse');

    // RED：当前输入框在消息区之前（row1）→ messages.compareDocumentPosition(input) & FOLLOWING 为 0 → FAIL
    //      （messages 在 input 之后，input 前置 messages）
    expect(messages.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // 控制块在输入框下方（round-actions / resize 在 input 之后）
    expect(input.compareDocumentPosition(roundArchive) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(input.compareDocumentPosition(roundDelete) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(input.compareDocumentPosition(resize) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // 回归守护（#542）：展开/收缩控制按钮在输入框之前（对话区顶部）
    expect(toggle.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
