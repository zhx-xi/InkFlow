import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
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

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}{location.search}</div>;
}

function renderLibrary(initialPath = '/library') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LibraryPage />
      <Routes>
        <Route path="/projects" element={<LocationProbe />} />
        <Route path="/writing" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
});

/**
 * #568 世界观默认视图 UI 完整重设计——信息层级（名称/描述/子条目数）+ 入口交互（根态隐藏创建按钮、
 * 选中分类才显示 + 预填类别）+ 视图切换语义。spec: specs/f43-setting-library-crud/world-default-view-ui-568.md
 * @see 旧 #588 行为（已有根条目恒显示 world-cat-add）在 #568 反转：根态（未选分类）隐藏创建按钮。
 */
describe('设定库页 — 世界观默认视图重设计（#568）', () => {
  /** #568 契约数据：根条目（parent_id=null）+ 子条目（parent_id=根）+ 分类实体（world-categories）；
   * content 跟随 withChildren——true 时根条目带非空 content（供描述预览断言），false 时 content=''（供空 content 行收敛断言）。
   * 类型用宽 Record（后端 WorldSetting 响应含 created_at/updated_at，LibraryItemDTO 不含——mock 运行时宽松）。 */
  function seedWorld(withChildren: boolean, withCategory: boolean) {
    const items: Array<Record<string, unknown>> = [
      {
        id: 'w1', name: '世界观', parent_id: null,
        category: withCategory ? '秘境' : '', content: withChildren ? '公元 2048 年灵气复苏。' : '',
        created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z',
      },
    ];
    if (withChildren) {
      items.push({
        id: 'w2', name: '秘境', parent_id: 'w1',
        category: '秘境', content: '秘境小世界探索。',
        created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-02T10:00:00Z',
      });
    }
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/world-settings') return { items, total: items.length, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/world-categories') {
        return { items: [{ id: 'wc1', name: '秘境', count: 1 }], total: 1, offset: 0, limit: 50 };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
  }

  it('信息层级：树行渲染描述预览（content 单行）与子条目数徽标', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    seedWorld(true, false); // 根条目带 content + 一个子条目
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());
    // 描述预览：根条目 content 出现在各行（world-node-desc-<id>）
    expect(screen.getByTestId('world-node-desc-w1')).toBeInTheDocument();
    expect(screen.getByTestId('world-node-desc-w1')).toHaveTextContent('公元 2048 年灵气复苏');
    // 子条目数徽标：根条目有 children → world-node-childcount-w1 = '1 子条目'
    expect(screen.getByTestId('world-node-childcount-w1')).toBeInTheDocument();
    expect(screen.getByTestId('world-node-childcount-w1')).toHaveTextContent('1 子条目');
    // 叶子（w2 无子条目）不渲染子条目数徽标
    expect(screen.queryByTestId('world-node-childcount-w2')).not.toBeInTheDocument();
  });

  it('信息层级：空 content 的条目不渲染描述预览（行高收敛）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    seedWorld(false, false);
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());
    expect(screen.queryByTestId('world-node-desc-w1')).not.toBeInTheDocument();
  });

  it('入口反转：有根条目 + 未选分类（根态）→ 隐藏「去创建」（创建子条目入口，根单例）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    seedWorld(true, false);
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());
    // 未选任何分类 chip（activeWorldCat=null → 根态）→ 「去创建」library-create-btn 隐藏（根单例不能建根）
    expect(screen.queryByTestId('library-create-btn')).not.toBeInTheDocument();
    // 新建分类实体（world-cat-add）恒显示（分类树可扩展，非根条目）；地图视图入口保留
    expect(screen.getByTestId('world-cat-add')).toBeInTheDocument();
    expect(screen.getByTestId('map-view-entry')).toBeInTheDocument();
  });

  it('入口：选中分类 chip → 显示「去创建」；点击打开对话框且类别预填选中分类名', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    seedWorld(false, true); // 根条目 + 分类实体「秘境」
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());
    // 点击「秘境」分类 chip → 选中态
    await user.click(screen.getByTestId('world-cat-filter-秘境'));
    // 选中分类 → 工具栏「去创建」library-create-btn 显示（创建子条目入口）
    expect(screen.getByTestId('library-create-btn')).toBeInTheDocument();
    // 新建分类实体（world-cat-add）恒显示
    expect(screen.getByTestId('world-cat-add')).toBeInTheDocument();
    // 点击「去创建」→ 创建对话框打开，类别输入预填「秘境」，标题用 worldCategory
    await user.click(screen.getByTestId('library-create-btn'));
    await waitFor(() => expect(screen.getByTestId('library-create-dialog')).toBeInTheDocument());
    expect(screen.getByLabelText('类别')).toHaveValue('秘境');
    expect(screen.getByTestId('library-create-dialog')).toHaveTextContent('创建分类');
  });

  it('分类 chips：不渲染「全部」选项', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    seedWorld(false, true);
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());
    expect(screen.queryByTestId('world-cat-filter-全部')).not.toBeInTheDocument();
    expect(screen.getByTestId('world-cat-filter-秘境')).toBeInTheDocument();
  });
});
