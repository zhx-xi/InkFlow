/**
 * #1320 world tab 静默截断契约（RED 优先）。
 *
 * 【缺陷】世界观树构建只用**第 1 页 50 条**（buildWorldTree(listItems) 吃服务端分页首页），
 * 且 world（树分支）/ 工作台分支**不渲染分页条** → 51+ 条世界条目**完全不可达**（静默截断）；
 * 父条目不在本页的子条目还会被孤儿降级为顶层。
 *
 * 【修复契约（用户已拍板）】world tab **不分页、取全量**（整树语义需要全量数据；
 * limit/offset 分批拉全），分页条对 world 无意义 → 不渲染。
 *
 * RED 预期：现首拉 limit=50 且只渲染 50 条 → 用例 1/2 FAIL。
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

/** 世界观种子：52 条顶层（第 51 条 = 「第52界」，超出第 1 页 → 修复前不可达） */
function seedWorldApi() {
  const all = Array.from({ length: 52 }, (_, i) => ({
    id: `w${i}`, name: i === 51 ? '第52界' : `世界${i}`, content: '', category: '地理', parent_id: null,
  }));
  apiFetchMock.mockImplementation(async (url: string) => {
    const u = String(url);
    if (/\/maps$/.test(u)) return { items: [] };
    if (/\/world-categories$/.test(u)) return { items: [] };
    if (/\/world-settings/.test(u)) {
      const params = new URL(u, 'http://x').searchParams;
      const offset = Number(params.get('offset') ?? '0');
      const limit = Number(params.get('limit') ?? '50');
      return { items: all.slice(offset, offset + limit), total: all.length, offset, limit };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
  return { all };
}

function renderWorld() {
  return render(
    <MemoryRouter initialEntries={['/library?cat=world']}>
      <LibraryPage />
    </MemoryRouter>,
  );
}

describe('#1320 world tab 全量取数（清静默截断）', () => {
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

  it('world 取全量：51+ 条时第 52 条可达（首拉不再被 limit=50 截断）', async () => {
    seedWorldApi();
    renderWorld();
    await waitFor(() => {
      expect(screen.getByText('第52界')).toBeInTheDocument();
    });
  });

  it('world 全量后不再有静默截断：单次请求即达 total 上限，全部条目入树', async () => {
    const { all } = seedWorldApi();
    renderWorld();
    await waitFor(() => {
      expect(screen.getByTestId('library-list')).toHaveTextContent('世界0');
    });
    await waitFor(() => {
      const list = screen.getByTestId('library-list');
      expect(list).toHaveTextContent('第52界');
      expect(list).toHaveTextContent('世界0');
    });
    // 关键判据（有判别力）：请求的 limit 必须 ≥ total 才能一次拉全；
    // 旧实现写死 limit=50 → 52 条必被截断（第 52 条不可达，上面断言已捕获）
    const requested = apiFetchMock.mock.calls
      .map(([u]) => String(u))
      .filter((u) => u.includes('/world-settings'));
    const limits = requested.map((u) => Number(new URL(u, 'http://x').searchParams.get('limit') ?? '0'));
    expect(Math.max(...limits)).toBeGreaterThanOrEqual(all.length);
  });
});
