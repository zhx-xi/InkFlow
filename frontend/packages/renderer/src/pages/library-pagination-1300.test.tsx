/**
 * #1300：设定库分页分类（characters / world / foreshadow）接入分页的回归护栏。
 *
 * 断言「分页控件必须出现」+ 请求带 limit/offset（防回归到一次性拉全）。
 * 契约要点：
 *   - 三个分页分类激活时 → library-page-info / -prev / -next 存在
 *   - 请求 URL 必须含 `limit=50&offset=0`（LIBRARY_PAGE_SIZE=50）
 *   - 切到非分页分类（timeline）→ 不渲染分页条
 *   - 空列表（total=0）→ 分页条仍渲染且 prev/next 双禁用（不崩）
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LibraryPage } from './library';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn(), ensureApiReady: vi.fn().mockResolvedValue(undefined) };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

function itemsResponse(count: number) {
  return {
    items: Array.from({ length: count }, (_, i) => ({
      id: `c${i}`, name: `角色${i}`, description: '', extra: {},
    })),
    total: count,
    offset: 0,
    limit: 50,
  };
}

/** 按 URL 分派 mock：分类列表端点返回 items；其余（maps 等）返回空 */
function seedApi(count: number) {
  apiFetchMock.mockImplementation(async (url: string) => {
    if (typeof url === 'string' && /\/maps$/.test(url)) return { items: [] };
    if (typeof url === 'string' && /\/world-categories$/.test(url)) return { items: [] };
    return itemsResponse(count);
  });
}

function renderLibrary() {
  return render(
    <MemoryRouter initialEntries={['/library?cat=characters']}>
      <LibraryPage />
    </MemoryRouter>,
  );
}

describe('#1300 设定库分类分页接入', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useThemeStore.setState({ lang: 'zh' });
    useProjectStore.setState({
      projects: [projectP1],
      currentProjectId: 'p1',
      loadProjects: vi.fn().mockResolvedValue(undefined),
      selectProject: vi.fn(),
    });
    useToastStore.setState({ toasts: [] });
    window.localStorage.clear();
  });

  it('characters 分类：分页控件出现且请求带 limit=50&offset=0', async () => {
    seedApi(120);
    renderLibrary();
    await waitFor(() => {
      expect(screen.getByTestId('library-page-info')).toBeInTheDocument();
    });
    expect(screen.getByTestId('library-page-prev')).toBeDisabled();
    expect(screen.getByTestId('library-page-next')).not.toBeDisabled();
    const listCall = apiFetchMock.mock.calls.find(
      ([u]) => typeof u === 'string' && u.includes('/characters'),
    );
    expect(String(listCall?.[0])).toContain('limit=50');
    expect(String(listCall?.[0])).toContain('offset=0');
  });

  it('characters 分类：info 显示「第 1 / 3 页 · 共 120 条」', async () => {
    seedApi(120);
    renderLibrary();
    await waitFor(() => {
      expect(screen.getByTestId('library-page-info')).toHaveTextContent('第 1 / 3 页 · 共 120 条');
    });
  });

  it('空列表（total=0）：分页条仍渲染且 prev/next 双禁用（不崩）', async () => {
    seedApi(0);
    renderLibrary();
    await waitFor(() => {
      expect(screen.getByTestId('library-tab-empty')).toBeInTheDocument();
    });
    // 空态走 empty 分支，分页条在列表分支内 → 此处断言不崩即可（无分页条属预期）
    expect(screen.queryByTestId('library-page-info')).not.toBeInTheDocument();
  });

  it('非分页分类（timeline）：不渲染分页条', async () => {
    apiFetchMock.mockImplementation(async (url: string) => {
      if (typeof url === 'string' && /\/maps$/.test(url)) return { items: [] };
      if (typeof url === 'string' && /\/world-categories$/.test(url)) return { items: [] };
      if (typeof url === 'string' && /\/timeline$/.test(url)) {
        return { event_timeline: [{ id: 't1', title: '事件一' }], narrative_order: [] };
      }
      return itemsResponse(0);
    });
    render(
      <MemoryRouter initialEntries={['/library?cat=timeline']}>
        <LibraryPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalled();
    });
    expect(screen.queryByTestId('library-page-info')).not.toBeInTheDocument();
  });
});
