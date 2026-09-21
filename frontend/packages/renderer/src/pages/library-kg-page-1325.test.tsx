/**
 * #1325 知识图谱关系列表分页 RED 契约（父侧作者；Codex 侧禁改）
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【本次要证明的命题（一句话）】
 * 知识图谱「关系列表」视图不再一次吞下全部关系：请求带 `?limit=&offset=`，
 * 列表下方渲染分页条（复用 #1300 的 Pagination，testIdPrefix='library-kg-page'），
 * 翻页/改页大小会以新的 offset 重拉。
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * 【契约（父侧定稿，2026-09-21）】
 *
 * 1. 首屏请求 `GET /api/v1/projects/{pid}/knowledge-relations?limit=50&offset=0`
 *    （响应 `{items,total,offset,limit}` 已有；page 为 0 基）
 * 2. 关系列表视图（`library-kg-relation-list`）**之下**渲染分页条
 *    `data-testid="library-kg-page-prev"` / `library-kg-page-next` / `library-kg-page-info`
 *    （来自 `<Pagination testIdPrefix="library-kg-page" />`）
 * 3. total 跨页（如 total=120, limit=50）→ next 可点；点 next → 请求 offset=50
 * 4. 首页 prev 禁用；末页 next 禁用（Pagination 既有语义，此处只验证接线）
 *
 * 【为何需要】旧实现 `listKnowledgeRelations(currentProjectId)` 不带任何分页参数，
 * 后端默认 `limit=50` → 第 51 条起的关系在列表视图永久不可见（静默截断）。
 *
 * 【RED 预期】实现前真跑并 FAIL：断言 1/2/3 均失败（无分页参数、无分页条 testid）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LibraryPage } from './library';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

const TOTAL_RELATIONS = 120;

/** 造 120 条关系（够跨 3 页 @limit=50） */
function makeRelations(): Array<Record<string, unknown>> {
  return Array.from({ length: TOTAL_RELATIONS }, (_, i) => ({
    id: String(i + 1), project_id: 'p1',
    source_type: 'character', source_id: 'c1',
    target_type: 'world', target_id: 'w1',
    relation_type: `关系${i + 1}`, description: '',
    source: 'manual', created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z',
  }));
}

const ALL_RELATIONS = makeRelations();

/** 抽出某次关系列表请求的 (offset, limit)（缺参 → null） */
function listPageArgs(): { offset: number | null; limit: number | null } {
  const call = apiFetchMock.mock.calls.find(
    (c) => typeof c[0] === 'string' && (c[0] as string).startsWith('/api/v1/projects/p1/knowledge-relations'),
  );
  if (!call) return { offset: null, limit: null };
  const url = new URL(call[0] as string, 'http://localhost');
  const offsetRaw = url.searchParams.get('offset');
  const limitRaw = url.searchParams.get('limit');
  return {
    offset: offsetRaw === null ? null : Number(offsetRaw),
    limit: limitRaw === null ? null : Number(limitRaw),
  };
}

function renderLibrary() {
  return render(
    <MemoryRouter initialEntries={['/library']}>
      <LibraryPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  // 服务端分页语义：按 offset/limit 切片（与后端一致）
  apiFetchMock.mockImplementation(
    async (path: string, init?: { method?: string; body?: unknown }) => {
      const method = init?.method ?? 'GET';
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/maps') return { items: [] };
      if (path.startsWith('/api/v1/projects/p1/knowledge-graph')) {
        return {
          nodes: [
            { id: 'character:c1', type: 'character', entity_id: 'c1', name: '林尘' },
            { id: 'world:w1', type: 'world', entity_id: 'w1', name: '清河县' },
          ],
          edges: [],
        };
      }
      if (path.startsWith('/api/v1/projects/p1/knowledge-relations')) {
        if (method === 'POST') return { id: '999' };
        const url = new URL(path, 'http://localhost');
        // 缺省 = 后端默认分页（limit=50, offset=0）——故意复刻真实后端语义，
        // 让「不传分页参数」的情况仍能出首屏数据（否则旧实现连列表都空，红得不是同一件事）
        const limit = Number(url.searchParams.get('limit') ?? 50);
        const offset = Number(url.searchParams.get('offset') ?? 0);
        return {
          items: ALL_RELATIONS.slice(offset, offset + limit).map((r) => ({ ...r })),
          total: TOTAL_RELATIONS,
          offset,
          limit,
        };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    },
  );
});

async function openRelationList(user: ReturnType<typeof userEvent.setup>) {
  act(() => {
    useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
  });
  renderLibrary();
  await user.click(screen.getByRole('tab', { name: '知识图谱' }));
  await user.click(await screen.findByTestId('library-kg-view-list'));
  await screen.findByTestId('library-kg-relation-list');
  await waitFor(() => {
    expect(screen.getByTestId('library-kg-relation-list')).toHaveTextContent('关系1');
  });
}

describe('#1325 知识图谱关系列表分页', () => {
  it('1 首屏请求带 limit=50&offset=0（不再吞全量）', async () => {
    const user = userEvent.setup();
    await openRelationList(user);

    await waitFor(() => {
      const { offset, limit } = listPageArgs();
      expect({ offset, limit }).toEqual({ offset: 0, limit: 50 });
    });
  });

  it('2 列表下方渲染分页条（library-kg-page-* 三件套）', async () => {
    const user = userEvent.setup();
    await openRelationList(user);

    expect(screen.getByTestId('library-kg-page-prev')).toBeInTheDocument();
    expect(screen.getByTestId('library-kg-page-next')).toBeInTheDocument();
    expect(screen.getByTestId('library-kg-page-info')).toBeInTheDocument();
  });

  it('3 首页 prev 禁用 / 有下一页时 next 可点', async () => {
    const user = userEvent.setup();
    await openRelationList(user);

    expect(screen.getByTestId('library-kg-page-prev')).toBeDisabled();
    expect(screen.getByTestId('library-kg-page-next')).not.toBeDisabled();
  });

  it('4 点 next → 以 offset=50 重拉（跨页可达，第 51 条起不再静默截断）', async () => {
    const user = userEvent.setup();
    await openRelationList(user);

    await user.click(screen.getByTestId('library-kg-page-next'));

    await waitFor(() => {
      const offsets = apiFetchMock.mock.calls
        .filter(
          (c) =>
            typeof c[0] === 'string' &&
            (c[0] as string).startsWith('/api/v1/projects/p1/knowledge-relations'),
        )
        .map((c) => new URL(c[0] as string, 'http://localhost').searchParams.get('offset'));
      expect(offsets).toContain('50');
    });
    // 反向断言：第 51 条真的出现在列表里（旧实现永远看不到）
    await waitFor(() => {
      expect(screen.getByTestId('library-kg-relation-list')).toHaveTextContent('关系51');
    });
  });

  it('5 末页 next 禁用（total=120 / limit=50 → 第 3 页）', async () => {
    const user = userEvent.setup();
    await openRelationList(user);

    await user.click(screen.getByTestId('library-kg-page-next'));
    await waitFor(() => expect(screen.getByTestId('library-kg-relation-list')).toHaveTextContent('关系51'));
    await user.click(screen.getByTestId('library-kg-page-next'));
    await waitFor(() => expect(screen.getByTestId('library-kg-relation-list')).toHaveTextContent('关系101'));

    expect(screen.getByTestId('library-kg-page-next')).toBeDisabled();
    expect(screen.getByTestId('library-kg-page-prev')).not.toBeDisabled();
  });

  it('6 分页条与列表同容器：不因视图切换残留（切回图谱视图后消失）', async () => {
    const user = userEvent.setup();
    await openRelationList(user);
    expect(within(screen.getByTestId('library-kg-relation-list')).queryByTestId('library-kg-page-next')).toBeNull();

    await user.click(screen.getByTestId('library-kg-view-graph'));
    await screen.findByTestId('library-kg-canvas');
    expect(screen.queryByTestId('library-kg-page-next')).toBeNull();
  });
});
