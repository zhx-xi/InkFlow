/**
 * #770 前端 RED 契约 A：写作页「无章节 → 全局 chat 页」+「章节内 ChatPanel」布局分支。
 *
 * 契约源：specs/f47-chat-exec-detail/spec.md §17.4.1/§17.4.2 + specs/f19-gui/writing.md §4.1/§4.3（N9/N10）。
 * - 场景 A（currentChapterId === null 且有项目）：中栏渲染全局 chat 页（data-testid="global-chat"，
 *   ChatPanel variant="full"）——无 resize handle、不渲染 EditorToolbar / ChapterEditor；
 *   左栏项目树、右栏 right-rail 保持。
 * - 场景 B（章节选中）：现有章节内 ChatPanel（inline，chat-resize-handle 80~480px）完整保留，不改。
 * - 空态守卫：无章节时不应渲染「生成/续写」触发点（EditorToolbar）——全局 chat 页只对话，不触发管线生成流。
 *
 * TDD RED：全局 chat 页未实现（writing.tsx 无 currentChapterId===null 分支，ChatPanel 仅章节内渲染）→
 * 场景 A 用例 FAIL；场景 B 用例为守护用例（当前实现已满足，PASS）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { WritingPage } from './writing';
import { apiFetch } from '../api/client';
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

const apiFetchMock = vi.mocked(apiFetch);

const seedVolumes = [{ id: 'v1', title: '第一卷 风起', order_index: 0 }];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
];

const READY_PROVIDER: ProviderConfig = {
  id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
  models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }], key_saved: true,
  max_retries: 3, timeout: 60, created_at: '', updated_at: '',
};

beforeEach(() => {
  vi.useRealTimers();
  apiFetchMock.mockReset();
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
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
  // ChatPanel（章节内）挂载即解析活动线程：GET 空 → createChatConversation 建新 → GET 消息
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    if (path === '/api/v1/provider-configs') return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes, total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/chapters') return { items: seedChapters, total: 1, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/chapters/') && init?.method === 'PATCH') return { ok: true };
    if (path === '/api/v1/chat/messages' && init?.method === 'POST') {
      const b = init.body as { project_id: string; role: 'user' | 'ai'; content: string };
      return { id: 'cm-1', project_id: b.project_id, role: b.role, content: b.content, intent: null, created_at: '2026-08-25T00:00:00Z' };
    }
    if (path.startsWith('/api/v1/chat/messages')) return { items: [], total: 0, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/chat/conversations')) {
      if (init?.method === 'POST') {
        const b = init.body as { project_id: string; title?: string };
        // #770 契约：POST /chat/conversations 返回含 title（章节名 / 全局首条消息前 30 字）
        return {
          conversation_id: `conv-${b.project_id}`,
          project_id: b.project_id,
          project_name: '青云志',
          title: b.title ?? '',
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
});

describe('写作页 — 无章节 → 全局 chat 页 / 章节内 ChatPanel（#770 §17.4.1/§17.4.2）', () => {
  it('场景 A：无章节（有项目）→ 渲染全局 chat 页：global-chat 存在、无 resize handle、无 EditorToolbar/ChapterEditor、右栏保持', () => {
    useChapterStore.setState({ currentChapterId: null, content: '' });
    render(
      <MemoryRouter initialEntries={['/writing']}>
        <WritingPage />
      </MemoryRouter>
    );
    // 全局 chat 容器（#770 新增；当前实现无此分支 → RED 首锚点）
    expect(screen.getByTestId('global-chat')).toBeInTheDocument();
    // full 变体不可调：无 resize handle（inline 章节内 ChatPanel 才渲染）
    expect(screen.queryByTestId('chat-resize-handle')).not.toBeInTheDocument();
    // 无章节不渲染编辑工具栏 / 章节编辑器
    expect(screen.queryByTestId('editor-toolbar')).not.toBeInTheDocument();
    expect(screen.queryByTestId('chapter-editor')).not.toBeInTheDocument();
    // 右栏保持（上下文注入仍有用）
    expect(screen.getByTestId('right-rail')).toBeInTheDocument();
  });

  it('场景 A 空态守卫：无章节 → 不渲染「生成/续写」触发点（不误触发 ChatPanel 生成流）', () => {
    useChapterStore.setState({ currentChapterId: null, content: '' });
    render(
      <MemoryRouter initialEntries={['/writing']}>
        <WritingPage />
      </MemoryRouter>
    );
    expect(screen.queryByRole('button', { name: '生成' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /续写/ })).not.toBeInTheDocument();
  });

  it('场景 B 回归守卫：选中章节 → 章节内 ChatPanel（chat-panel + resize handle + EditorToolbar）完整保留', () => {
    render(
      <MemoryRouter initialEntries={['/writing']}>
        <WritingPage />
      </MemoryRouter>
    );
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
    expect(screen.getByTestId('chat-resize-handle')).toBeInTheDocument();
    expect(screen.getByTestId('editor-toolbar')).toBeInTheDocument();
  });
});

describe('写作页 — #840 URL conversation_id 参数消费（会话点击贯通）', () => {
  it('场景 C：/writing?conversation_id=conv-restored → WritingPage 透传 conversationId 给 ChatPanel 加载该指定会话（不再解析最新活跃线程/不再新建）', async () => {
    useChapterStore.setState({ currentChapterId: null, content: '' });
    render(
      <MemoryRouter initialEntries={['/writing?conversation_id=conv-restored']}>
        <WritingPage />
      </MemoryRouter>
    );
    // #840：conversation_id 参数被 writing.tsx 消费并传给 ChatPanel，ChatPanel 直接加载该会话消息
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/chat/messages?conversation_id=conv-restored&offset=0&limit=50',
        expect.anything(),
      );
    });
    // 指定会话后不应再走 createChatConversation 建新线程
    expect(apiFetchMock).not.toHaveBeenCalledWith(
      '/api/v1/chat/conversations',
      expect.anything(),
    );
  });
});
