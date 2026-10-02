/**
 * #1334 ①C（已拍板 2026-10-02）：abstract 分类条目【移出列表页主树】，
 * 仅在该分类被选中（分类筛选视图）时可见。后端零改动（#641 自动挂根语义不变）。
 *
 * 判据（specs/f10-world-settings/spec.md §16.4 / §16.8，与 #721 地图树同源）：
 * - 条目的**分类的 kind** 决定可见性；`category=""` 或分类未注册 → 按 geo 处理（可见）
 * - abstract 分类条目：主树不可见；选中该分类 → 可见
 *
 * 实施归属：前端渲染层（library.tsx 树数据源过滤），无 DB / 契约 / 迁移变更。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
  id: 'p1', name: '项目甲', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

/** 分类表：地理=geo / 势力=abstract / 「文化」刻意不注册（存量未注册类别） */
const cats = [
  { id: 'g1', name: '地理', kind: 'geo', count: 0 },
  { id: 'a1', name: '势力', kind: 'abstract', count: 0 },
];

/** 条目：根（未分类）+ geo + abstract + 未分类子条目 + 未注册分类条目 */
const items = [
  { id: 'w1', name: '世界观根', category: '', content: '', parent_id: null },
  { id: 'w2', name: '地点甲', category: '地理', content: '', parent_id: 'w1' },
  { id: 'w3', name: '组织乙', category: '势力', content: '', parent_id: 'w1' },
  { id: 'w4', name: '无名设定丙', category: '', content: '', parent_id: 'w1' },
  { id: 'w5', name: '习俗丁', category: '文化', content: '', parent_id: 'w1' },
];

function seedApi() {
  apiFetchMock.mockImplementation(async (url: string) => {
    const u = String(url);
    if (/\/maps$/.test(u)) return { items: [] };
    if (/\/world-categories$/.test(u)) return { items: cats, total: cats.length, offset: 0, limit: 50 };
    if (/\/world-settings/.test(u)) {
      const params = new URL(u, 'http://x').searchParams;
      const offset = Number(params.get('offset') ?? '0');
      const limit = Number(params.get('limit') ?? '50');
      return { items: items.slice(offset, offset + limit), total: items.length, offset, limit };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
}

function renderWorld() {
  return render(
    <MemoryRouter initialEntries={['/library?cat=world']}>
      <LibraryPage />
    </MemoryRouter>,
  );
}

/** 等主树就绪（根条目渲染）后返回 library-list 容器 */
async function readyTree() {
  await waitFor(() => {
    expect(screen.getByTestId('library-list')).toHaveTextContent('世界观根');
  });
  return screen.getByTestId('library-list');
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  act(() => {
    useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
  });
});

describe('#1334 ①C — abstract 分类条目移出列表页主树', () => {
  it('主树（未筛选）：abstract 分类条目（组织乙）不渲染；geo 条目照常显示', async () => {
    seedApi();
    renderWorld();
    const list = await readyTree();
    expect(within(list).getByText('地点甲')).toBeInTheDocument();
    expect(within(list).queryByText('组织乙')).not.toBeInTheDocument();
  });

  it('反例守护：`category=""`（未分类）条目按 geo 处理 → 主树可见', async () => {
    seedApi();
    renderWorld();
    const list = await readyTree();
    expect(within(list).getByText('无名设定丙')).toBeInTheDocument();
  });

  it('反例守护：分类未注册（「文化」不在分类表）按 geo 处理 → 主树可见', async () => {
    seedApi();
    renderWorld();
    const list = await readyTree();
    expect(within(list).getByText('习俗丁')).toBeInTheDocument();
  });

  it('选中 abstract 分类（势力）→ 该分类条目在筛选视图可见', async () => {
    seedApi();
    const user = userEvent.setup();
    renderWorld();
    await readyTree();
    await user.click(screen.getByTestId('world-cat-filter-势力'));
    await waitFor(() => {
      expect(within(screen.getByTestId('library-list')).getByText('组织乙')).toBeInTheDocument();
    });
  });

  it('选中 geo 分类（地理）→ abstract 条目仍不在树中', async () => {
    seedApi();
    const user = userEvent.setup();
    renderWorld();
    await readyTree();
    await user.click(screen.getByTestId('world-cat-filter-地理'));
    await waitFor(() => {
      expect(within(screen.getByTestId('library-list')).getByText('地点甲')).toBeInTheDocument();
    });
    expect(within(screen.getByTestId('library-list')).queryByText('组织乙')).not.toBeInTheDocument();
  });

  it('取消选中 abstract 分类（再点同 chip）→ abstract 条目重新移出主树', async () => {
    seedApi();
    const user = userEvent.setup();
    renderWorld();
    await readyTree();
    const chip = screen.getByTestId('world-cat-filter-势力');
    await user.click(chip);
    await waitFor(() => {
      expect(within(screen.getByTestId('library-list')).getByText('组织乙')).toBeInTheDocument();
    });
    await user.click(chip);
    await waitFor(() => {
      expect(within(screen.getByTestId('library-list')).queryByText('组织乙')).not.toBeInTheDocument();
    });
  });
});
