/**
 * 写作页 × #1377 草稿审批弹层「驳回」入口（页面级契约，兄弟文件，镜像 #988 的 harness 最小子集）。
 *
 * ⚠️ 本文件 = 契约（页面装配面）：
 * - 工具栏 `drafts-approval-button` → 弹层 `drafts-drawer` → 行内 `drafts-drawer-reject-{id}`
 * - 点击 → 真实 api/drafts.rejectDraft 经 apiFetch 发
 *   POST /api/v1/agent/drafts/{id}/reject（**无 body**）
 * - 成功 → 关框（drafts-drawer 离开文档）+ 树轨重拉（GET /projects/p1/volumes 再次发出）
 * - 失败 → 框内 `drafts-drawer-error` 透传错误文案，框**不关**
 *
 * api/drafts 不 mock（真实模块经 apiFetch 分发，锁整链装配，同 #988 兄弟文件先例）；
 * 仅 mock api/client + api/pipeline + api/chat。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
vi.mock('../api/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/chat')>();
  return { ...actual, createChatConversation: vi.fn(), saveChatMessage: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

function renderWritingPage() {
  return render(
    <MemoryRouter initialEntries={['/writing']}>
      <WritingPage />
    </MemoryRouter>,
  );
}

const seedVolumes = [{ id: 'v1', title: '第一卷 风起', order_index: 0 }];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
];

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

/** #1377 种子：单条未审批草稿（chapter_id null，镜像 pending 草稿 DTO 形态） */
const draftItems = [
  {
    id: 'd1',
    project_id: 'p1',
    chapter_id: null,
    agent_run_id: 'r1',
    content: 'AI 生成的章节草稿正文',
    status: 'draft',
    summary: '第3章 渡口夜雾',
    created_at: '2026-08-25T10:00:00Z',
    confirmed_at: null,
    volume_id: 'v1',
  },
];

/** apiFetch 分发器：rejectFails=true 时驳回端点抛错（错误面用例复用同一路由表） */
function mockRoutes({ rejectFails = false }: { rejectFails?: boolean } = {}) {
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 } as never;
    }
    if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes } as never;
    if (path === '/api/v1/projects/p1/chapters') {
      return { items: seedChapters, total: 1, offset: 0, limit: 50 } as never;
    }
    if (path === '/api/v1/agent/drafts/d1/reject' && init?.method === 'POST') {
      if (rejectFails) throw new Error('草稿已被处理');
      return { draft_id: 'd1', status: 'rejected' } as never;
    }
    if (path.startsWith('/api/v1/agent/drafts')) {
      return { items: draftItems, total: draftItems.length } as never;
    }
    return { items: [], total: 0, offset: 0, limit: 50 } as never;
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  window.INKFLOW_API = { baseURL: 'http://test.local', token: 'tok-1' };
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: seedVolumes,
    chapters: seedChapters,
    treeProjectId: 'p1',
    currentChapterId: 'c1',
    content: '已有正文第一段。',
    loading: false,
    error: null,
  });
  useProjectStore.setState({
    projects: [
      { id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' },
    ],
    currentProjectId: 'p1',
    loading: false,
    error: null,
  });
});

afterEach(() => {
  delete window.INKFLOW_API;
});

describe('写作页 — #1377 草稿驳回链路（页面级）', () => {
  it('【R】弹层点驳回 → POST /agent/drafts/d1/reject（无 body）→ 关框 + 树轨重拉', async () => {
    mockRoutes();
    renderWritingPage();
    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1/volumes'),
    );
    fireEvent.click(screen.getByTestId('drafts-approval-button'));
    const rejectBtn = await screen.findByTestId('drafts-drawer-reject-d1');
    apiFetchMock.mockClear();
    fireEvent.click(rejectBtn);
    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => String(c[0]) === '/api/v1/agent/drafts/d1/reject',
      );
      expect(call).toBeDefined();
      expect((call?.[1] as { method?: string } | undefined)?.method).toBe('POST');
      // 无 body（issue 契约：rejectDraft 不传 body）
      expect((call?.[1] as { body?: unknown } | undefined)?.body).toBeUndefined();
    });
    // 关框（成功收束）
    await waitFor(() => expect(screen.queryByTestId('drafts-drawer')).not.toBeInTheDocument());
    // 树轨重拉（loadChapterTree → volumes 再次发出）
    expect(
      apiFetchMock.mock.calls.some((c) => String(c[0]) === '/api/v1/projects/p1/volumes'),
    ).toBe(true);
  }, 15000);

  it('【R】驳回失败 → 框内 drafts-drawer-error 透传且不关框', async () => {
    mockRoutes({ rejectFails: true });
    renderWritingPage();
    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1/volumes'),
    );
    fireEvent.click(screen.getByTestId('drafts-approval-button'));
    fireEvent.click(await screen.findByTestId('drafts-drawer-reject-d1'));
    expect(await screen.findByTestId('drafts-drawer-error')).toHaveTextContent('草稿已被处理');
    expect(screen.getByTestId('drafts-drawer')).toBeInTheDocument();
  }, 15000);
});
