/**
 * 写作页 × #988 草稿来源锚定页面级契约（兄弟文件，镜像 writing.test.tsx harness 最小子集）。
 *
 * ⚠️ 本文件 = 契约。writing.test.tsx 基线 895 行贴线（900 护栏），#988 页面级用例
 * 按先例独立成文件（#930 logs-card-readable-930 兄弟文件模式）：
 * - 草稿带 source_outline_id（后端 #988 创建点记录/D4 自取链路的 DTO 暴露）→
 *   审批弹层点确认 → POST /api/v1/agent/drafts/{id}/confirm body 含
 *   source_outline_id（DraftDto → confirmDraft options → apiFetch 全链路）。
 * - mock 仅 api/client + api/pipeline + api/chat（同 writing.test.tsx），api/drafts
 *   不 mock（真实模块经 apiFetch 分发，锁整链装配）。
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

/** #988 种子：d1 记录来源锚 o1（chat/book 轨创建点回填后 DTO 形态） */
const recordedDrafts = [
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
    source_outline_id: 'o1',
  },
];

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
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 } as never;
    }
    if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes } as never;
    if (path === '/api/v1/projects/p1/chapters') {
      return { items: seedChapters, total: 1, offset: 0, limit: 50 } as never;
    }
    if (path === '/api/v1/agent/drafts/d1/confirm' && init?.method === 'POST') {
      return { draft_id: 'd1', status: 'confirmed', chapter_id: 'c1' } as never;
    }
    if (path.startsWith('/api/v1/agent/drafts')) {
      return { items: recordedDrafts, total: recordedDrafts.length } as never;
    }
    return { items: [], total: 0, offset: 0, limit: 50 } as never;
  });
});

afterEach(() => {
  delete window.INKFLOW_API;
});

describe('写作页 — #988 来源锚定确认链路（页面级）', () => {
  it('【R】草稿带记录来源 → 弹层确认 POST body 含 source_outline_id', async () => {
    renderWritingPage();
    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1/volumes'),
    );
    fireEvent.click(screen.getByTestId('drafts-approval-button'));
    const btn = await screen.findByTestId('drafts-drawer-confirm-d1');
    apiFetchMock.mockClear();
    fireEvent.click(btn);
    await waitFor(() => {
      const confirmCall = apiFetchMock.mock.calls.find(
        (c) => String(c[0]) === '/api/v1/agent/drafts/d1/confirm',
      );
      expect(confirmCall).toBeDefined();
      expect((confirmCall?.[1] as { body: Record<string, unknown> }).body).toEqual({
        source_outline_id: 'o1',
      });
    });
  }, 15000);
});
