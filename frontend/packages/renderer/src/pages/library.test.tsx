/**
 * ⚠️ 契约文件（Issue #105 导航重构 RED 阶段，spec §7.3 设定库项目上下文）
 *
 * GREEN 新建 src/pages/library.tsx（命名导出 LibraryPage），必须匹配：
 *
 * 结构（data-testid 即契约）：
 * - library-page：页面根容器
 * - library-project-select：当前项目选择器（Radix Select，trigger aria-label=t('lib.projectSelect')）
 * - library-breadcrumb：面包屑「设定库 · 项目名 / 分类」（文本包含项目名与当前分类）
 * - library-tabs：六 tab 容器；tab 元素 role="tab"（shadcn Tabs 或 button+role=tab），
 *   标签文案用 nav.lib.* key：角色/世界观/大纲/时间线/伏笔/知识库 RAG
 * - library-list：当前分类列表（列表项渲染分类 DTO 的 name 字段）
 * - library-empty：未选择项目空态（文案 + 「前往项目页」按钮）
 * - library-tab-empty：分类空态引导（「还没有{name}，去创建」+ CTA library-tab-empty-cta）
 *
 * 行为：
 * - 项目列表来自 useProjectStore（挂载时 loadProjects；测试播种 store + mock apiFetch 双保险）
 * - 分类数据按当前项目拉取（端点已核实 backend/api/routers，响应统一 {items,total,offset,limit}）：
 *   角色 → GET /api/v1/projects/{id}/characters
 *   世界观 → GET /api/v1/projects/{id}/world-settings
 *   大纲 → GET /api/v1/projects/{id}/outlines
 *   时间线 → GET /api/v1/projects/{id}/timeline
 *   伏笔 → GET /api/v1/projects/{id}/foreshadowings
 *   知识库 RAG → GET /api/v1/projects/{id}/extractions/runs（索引状态列表，渲染细节 #106 细化）
 * - 未选择项目（currentProjectId=null，无论 projects 是否有数据）→ library-empty
 *   「选择或新建项目开始构建设定」+ 前往项目页按钮 → 路由 /projects
 * - 切换项目（选择器）→ useProjectStore.selectProject + 内容重载（重新拉取新项目分类端点）
 * - 读取 URL cat 查询参数作为初始 tab（侧边导航 nav-item-<key> 直达联动，spec §7.2）
 *
 * 新增 i18n key（GREEN 补 zh.ts/en.ts；tab 标签复用 nav.lib.*）：
 * lib.title='设定库' lib.projectSelect='当前项目' lib.empty.noProject='选择或新建项目开始构建设定'
 * lib.empty.goProjects='前往项目页' lib.empty.tab='还没有{name}，去创建'（name=分类名参数）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
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
  id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};
const projectP2 = {
  id: 'p2', name: '归墟记', genre: '仙侠', language: 'zh-CN', target_words: 500000, config: {},
  created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

const TABS = ['角色', '世界观', '大纲', '时间线', '伏笔', '知识库 RAG'];

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
      </Routes>
    </MemoryRouter>,
  );
}

/** 端点命中断言（宽容单参/双参：契约 = 拉取了该端点，不约束 init 形状） */
function fetchCalled(path: string): boolean {
  return apiFetchMock.mock.calls.some((c) => c[0] === path);
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1, projectP2], total: 2, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/characters') return { items: [{ id: 'c1', name: '林晚' }], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p2/characters') return { items: [{ id: 'c2', name: '沈砚' }], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/outlines') return { items: [{ id: 'o1', name: '卷一 风起' }], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/extractions/runs') return { items: [{ id: 1, status: 'success' }], total: 1, offset: 0, limit: 50 };
    // 时间线 = TimelineView 形状（backend timeline.py L365-377：event_timeline/narrative_order，无 items）
    if (path === '/api/v1/projects/p1/timeline')
      return { project_id: 'p1', total: 1, event_timeline: [{ id: 't1', title: '决战昆仑' }], narrative_order: [] };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('设定库页 — 未选择项目空态（spec §7.3）', () => {
  it('无项目：空态文案 + 前往项目页按钮 → 路由 /projects', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [], total: 0, offset: 0, limit: 50 };
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderLibrary();

    const empty = await screen.findByTestId('library-empty');
    expect(empty).toHaveTextContent('选择或新建项目开始构建设定');
    await user.click(within(empty).getByRole('button', { name: '前往项目页' }));
    expect(await screen.findByTestId('location-probe')).toHaveTextContent('/projects');
  });

  it('有项目但未选择（currentProjectId=null）：同样空态（入口语义 = 当前项目的设定库）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1, projectP2], currentProjectId: null });
    });
    renderLibrary();
    expect(await screen.findByTestId('library-empty')).toHaveTextContent('选择或新建项目开始构建设定');
  });
});

describe('设定库页 — 项目上下文（spec §7.3）', () => {
  it('选择项目后：项目选择器 + 面包屑 + 六 tab 渲染，默认角色 tab 拉取角色列表', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1, projectP2], currentProjectId: 'p1' });
    });
    renderLibrary();

    // 项目选择器：Radix Select trigger（aria-label「当前项目」）显示当前项目名
    expect(screen.getByTestId('library-project-select')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: '当前项目' })).toHaveTextContent('青云志');

    // 面包屑「设定库 · 青云志 / 角色」
    const crumb = screen.getByTestId('library-breadcrumb');
    expect(crumb).toHaveTextContent('青云志');
    expect(crumb).toHaveTextContent('角色');

    // 六 tab
    const tabs = screen.getByTestId('library-tabs');
    expect(within(tabs).getAllByRole('tab')).toHaveLength(6);
    for (const name of TABS) {
      expect(within(tabs).getByRole('tab', { name })).toBeInTheDocument();
    }

    // 默认角色 tab：拉取 /characters + 列表渲染 name
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/characters')).toBe(true);
      expect(screen.getByTestId('library-list')).toHaveTextContent('林晚');
    });
  });

  it('tab 切换：点击大纲 → 面包屑更新 + 拉取 /outlines + 列表渲染', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '大纲' }));
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/outlines')).toBe(true);
      expect(screen.getByTestId('library-breadcrumb')).toHaveTextContent('大纲');
      expect(screen.getByTestId('library-list')).toHaveTextContent('卷一 风起');
    });
  });

  it('知识库 RAG tab：拉取索引状态端点 /extractions/runs', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '知识库 RAG' }));
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/extractions/runs')).toBe(true);
    });
  });

  it('时间线 tab：TimelineView 形状（event_timeline 列表渲染 title，无 items）——评审 🔴 修复契约', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '时间线' }));
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/timeline')).toBe(true);
      // TimelineView 无 items：列表从 event_timeline 取，渲染事件 title
      expect(screen.getByTestId('library-list')).toHaveTextContent('决战昆仑');
    });
  });

  it('项目切换：选择器切换 → selectProject + 内容重载（新项目端点 + 新列表）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1, projectP2], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('combobox', { name: '当前项目' }));
    await user.click(await screen.findByRole('option', { name: '归墟记' }));

    await waitFor(() => {
      expect(useProjectStore.getState().currentProjectId).toBe('p2');
      expect(fetchCalled('/api/v1/projects/p2/characters')).toBe(true);
      expect(screen.getByTestId('library-breadcrumb')).toHaveTextContent('归墟记');
      expect(screen.getByTestId('library-list')).toHaveTextContent('沈砚');
    });
  });

  it('分类空态引导：无数据分类 → 「还没有{name}，去创建」+ CTA', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    // 世界观分类 mock 返回空列表（beforeEach 默认分支）
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    const empty = await screen.findByTestId('library-tab-empty');
    expect(empty).toHaveTextContent('还没有世界观，去创建');
    expect(within(empty).getByTestId('library-tab-empty-cta')).toBeInTheDocument();
  });

  it('深链直达：/library?cat=outline → 初始 tab 大纲（侧边导航联动）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    renderLibrary('/library?cat=outline');

    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/outlines')).toBe(true);
      expect(screen.getByTestId('library-breadcrumb')).toHaveTextContent('大纲');
    });
  });
});

/**
 * #105 Coverage-Gap 补测（非 RED）：六分类 endpoint 函数全覆盖
 * （时间线 L25 / 伏笔 L26）+ 分类端点失败 catch 兜底分支（L86-88）。
 */
describe('设定库页 — 分类端点全覆盖与失败兜底（#105 补测）', () => {
  it('时间线/伏笔 tab：拉取对应端点（endpoint 分支全覆盖）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '时间线' }));
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/timeline')).toBe(true);
    });

    await user.click(screen.getByRole('tab', { name: '伏笔' }));
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/foreshadowings')).toBe(true);
    });
  });

  it('分类端点失败：items 清空 + 加载复位 → 分类空态引导（catch 兜底）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      throw new Error('分类数据获取失败');
    });
    renderLibrary();

    await waitFor(() => {
      expect(screen.getByTestId('library-tab-empty')).toBeInTheDocument();
      expect(screen.queryByTestId('library-list')).not.toBeInTheDocument();
    });
  });
});
