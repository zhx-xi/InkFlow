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
 *   标签文案用 nav.lib.* key：角色/世界观/大纲/时间线/伏笔/知识图谱
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
 *   知识图谱 → GET /api/v1/projects/{id}/knowledge-graph（图谱画布 nodes+edges，F48 §5.4；原 rag tab 改造）
 * - 未选择项目（currentProjectId=null，无论 projects 是否有数据）→ library-empty
 *   「选择或新建项目开始构建设定」+ 前往项目页按钮 → 路由 /projects
 * - 切换项目（选择器）→ useProjectStore.selectProject + 内容重载（重新拉取新项目分类端点）
 * - 读取 URL cat 查询参数作为初始 tab（侧边导航 nav-item-<key> 直达联动，spec §7.2）
 *
 * 新增 i18n key（GREEN 补 zh.ts/en.ts；tab 标签复用 nav.lib.*）：
 * lib.title='设定库' lib.projectSelect='当前项目' lib.empty.noProject='选择或新建项目开始构建设定'
 * lib.empty.goProjects='前往项目页' lib.empty.tab='还没有{name}，去创建'（name=分类名参数）
 *
 * ⚠️ #105 修复批契约（评审 findings 驱动，2026-08-06）：
 * - 分类端点失败 → error 态（不再误显示空态）：i18n 新 key lib.loadFailed='加载失败，请重试'
 *   （Loading failed, please retry）+ 重试按钮 data-testid="library-retry" → 点击重新拉取当前分类端点
 * - 空态 CTA（library-tab-empty-cta）可点：点击 → navigate('/writing')（空态引导去写作页创建）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { LibraryPage } from './library';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

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

const TABS = ['角色', '世界观', '大纲', '时间线', '伏笔', '知识图谱'];

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
    if (path === '/api/v1/projects/p1/knowledge-graph') return { nodes: [], edges: [] };
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

  it('列表非空时仍有「新建」按钮（#545：创建实体后无常态创建入口）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();
    // 角色 tab 已有 1 条（林晚）——非空态
    await waitFor(() => {
      expect(screen.getByTestId('library-list')).toHaveTextContent('林晚');
    });
    // 列表态必须存在「新建」按钮（非空态 CTA 之外的第二入口）
    const createBtn = screen.getByTestId('library-create-btn');
    expect(createBtn).toBeInTheDocument();
    // 点击 → 打开创建对话框
    await user.click(createBtn);
    expect(screen.getByTestId('library-create-dialog')).toBeInTheDocument();
  });

  it('知识图谱 tab：拉取图谱端点 /knowledge-graph（F48：原 rag tab 改造）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '知识图谱' }));
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/knowledge-graph')).toBe(true);
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

  it('#196 空态 CTA 打开创建对话框：世界观分类空态「去创建」→ 对话框出现，不跳转 /writing（替代 #105 占位跳转）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '世界观' }));
    const empty = await screen.findByTestId('library-tab-empty');
    // RED：现状 CTA navigate('/writing') → 无对话框 → element-missing FAIL
    await user.click(within(empty).getByTestId('library-tab-empty-cta'));
    await waitFor(() => {
      expect(screen.getByTestId('library-create-dialog')).toBeInTheDocument();
    });
    // 不跳转
    expect(screen.queryByTestId('location-probe')).not.toBeInTheDocument();
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
 * （时间线 L25 / 伏笔 L26）+ #105 修复批 error 态契约（失败不再落空态，改错误文案 + 重试）。
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

  it('分类端点失败 → error 态：不显示空态，展示 lib.loadFailed 文案 + library-retry 重试按钮', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      throw new Error('分类数据获取失败');
    });
    renderLibrary();

    // #105 修复批契约：失败 ≠ 真空态——library-tab-empty 不得出现，改显示错误文案 + 重试按钮
    await waitFor(() => {
      expect(screen.queryByTestId('library-tab-empty')).not.toBeInTheDocument();
      expect(screen.getByText('加载失败，请重试')).toBeInTheDocument();
      expect(screen.getByTestId('library-retry')).toBeInTheDocument();
    });
  });

  it('点击 library-retry 重新拉取分类：失败一次后重试成功 → 列表恢复', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    let shouldFail = true;
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/characters') {
        if (shouldFail) {
          shouldFail = false;
          throw new Error('分类数据获取失败');
        }
        return { items: [{ id: 'c1', name: '林晚' }], total: 1, offset: 0, limit: 50 };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderLibrary();

    const retry = await screen.findByTestId('library-retry');
    await user.click(retry);

    // 重试 = 再次请求同一分类端点（初始失败 1 次 + 重试 1 次 = 2 次）→ 成功后列表恢复
    await waitFor(() => {
      const charCalls = apiFetchMock.mock.calls.filter((c) => c[0] === '/api/v1/projects/p1/characters');
      expect(charCalls.length).toBe(2);
      expect(screen.getByTestId('library-list')).toHaveTextContent('林晚');
    });
  });
});

/**
 * #196（2026-08-09，rc3 复验缺陷）：设定库分类实体手动创建（specs/f36-library-manual-create/spec.md）。
 * - 五个可创建分类（角色/世界观/大纲/时间线/伏笔）空态 CTA → 打开 LibraryCreateDialog（不跳 /writing）
 * - 对话框字段按分类渲染（后端 DTO 已核实，见 spec §2.1 表）；名称/标题必填
 * - 保存成功 → POST 对应分类端点 → 对话框关闭 + 列表实时刷新（重新拉取当前分类端点）
 * - 保存失败 → err toast（errorMessage）+ 对话框保持打开
 * - 知识图谱分类无创建端点（图谱关系编辑走画布/列表内交互）→ 空态 CTA 改图谱空态引导（F48 §5.4，不跳 /writing）
 * GREEN 契约：library.tsx 渲染 <LibraryCreateDialog>（新组件 components/LibraryCreateDialog.tsx）；
 * data-testid=library-create-dialog；字段经 label/aria-label 关联（i18n lib.create.* 由 GREEN 补 zh/en）；
 * 创建按钮 data-testid=library-create-save。
 * RED 预期：现状 CTA navigate('/writing') → 无对话框 → element-missing FAIL；
 * 知识图谱 tab 空态用例改 F48 语义（图谱空态引导，不跳 /writing）。
 */
describe('设定库页 — #196 分类实体手动创建', () => {
  /** 播种 p1 + 切到指定 tab + 点击空态 CTA 打开对话框 */
  async function openCreateDialog(tabName: string) {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    // 空态前提：当前分类端点 mock 为空（beforeEach 默认对角色/大纲/时间线/知识图谱有数据 → 无空态）
    const emptyByTab: Record<string, string | null> = {
      '角色': '/api/v1/projects/p1/characters',
      '世界观': '/api/v1/projects/p1/world-settings',
      '大纲': '/api/v1/projects/p1/outlines',
      '时间线': null, // TimelineView 特例（event_timeline）
      '伏笔': '/api/v1/projects/p1/foreshadowings',
    };
    const emptyTarget = emptyByTab[tabName];
    if (emptyTarget !== undefined) {
      // 一次性 seed 语义（#196 实现期父侧裁定）：仅首次 GET 返回空（空态前提），
      // 此后委托 prev——POST 与刷新 GET 必须走用例自身 mock（reject/回显），
      // 无条件拦截会把 POST 也 resolve，保存流用例永远无法通过
      const prev = apiFetchMock.getMockImplementation();
      let seeded = false;
      apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
        if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
        if (
          !seeded &&
          (path === emptyTarget || (emptyTarget === null && path === '/api/v1/projects/p1/timeline'))
        ) {
          seeded = true;
          return emptyTarget === null
            ? { project_id: 'p1', total: 0, event_timeline: [], narrative_order: [] }
            : { items: [], total: 0, offset: 0, limit: 50 };
        }
        return prev ? prev(path, init) : { items: [], total: 0, offset: 0, limit: 50 };
      });
    }
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: tabName }));
    const empty = await screen.findByTestId('library-tab-empty');
    await user.click(within(empty).getByTestId('library-tab-empty-cta'));
    const dialog = await screen.findByTestId('library-create-dialog');
    return { user, dialog };
  }

  it('角色分类对话框：字段齐全（名称/性格/背景/目标）', async () => {
    const { dialog } = await openCreateDialog('角色');
    expect(within(dialog).getByLabelText('名称')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('性格')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('背景')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('目标')).toBeInTheDocument();
    expect(within(dialog).getByTestId('library-create-save')).toBeInTheDocument();
  });

  it('世界观分类对话框：字段（名称/类别/内容）', async () => {
    const { dialog } = await openCreateDialog('世界观');
    expect(within(dialog).getByLabelText('名称')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('类别')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('内容')).toBeInTheDocument();
  });

  it('大纲分类对话框：字段（名称/描述）', async () => {
    const { dialog } = await openCreateDialog('大纲');
    expect(within(dialog).getByLabelText('名称')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('描述')).toBeInTheDocument();
  });

  it('时间线分类对话框：字段（标题/时间显示/描述）', async () => {
    const { dialog } = await openCreateDialog('时间线');
    expect(within(dialog).getByLabelText('标题')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('时间显示')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('描述')).toBeInTheDocument();
  });

  it('伏笔分类对话框：字段（标题/优先级/位置/描述）', async () => {
    const { dialog } = await openCreateDialog('伏笔');
    expect(within(dialog).getByLabelText('标题')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('优先级')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('位置')).toBeInTheDocument();
    expect(within(dialog).getByLabelText('描述')).toBeInTheDocument();
  });

  it('角色创建保存：填写 → POST /characters body 对齐 DTO → 对话框关闭 + 列表刷新出现新角色', async () => {
    // 后端语义 mock：POST 入数组，GET 返回数组（回显式模拟真实落库）
    const chars: Array<{ id: string; name: string }> = [{ id: 'c1', name: '林晚' }];
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/characters') {
        if (init?.method === 'POST') {
          const body = init.body as { name: string };
          const created = { id: 'c9', name: body.name };
          chars.push(created);
          return created;
        }
        return { items: chars, total: chars.length, offset: 0, limit: 50 };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const { user, dialog } = await openCreateDialog('角色');
    await user.type(within(dialog).getByLabelText('名称'), '叶孤城');
    await user.type(within(dialog).getByLabelText('性格'), '孤傲');
    await user.type(within(dialog).getByLabelText('背景'), '剑客');
    await user.type(within(dialog).getByLabelText('目标'), '决战');
    // P1 D1 契约升级（2026-08-13）：角色创建必填等级——未选保存 disabled，显式选择「重要配角」后保存
    await user.click(within(dialog).getByTestId('library-create-rank'));
    await user.click(await screen.findByRole('option', { name: '重要配角' }));
    await user.click(within(dialog).getByTestId('library-create-save'));

    // POST body 对齐后端 CharacterCreateBody（name/personality/background/goals + P1 extra 透传）
    await waitFor(() => {
      const postCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/characters' && c[1]?.method === 'POST',
      );
      expect(postCall).toBeTruthy();
      const body = postCall![1]!.body as {
        name: string;
        personality: string;
        background: string;
        goals: string;
        extra: { role_rank: string; groups: string[] };
      };
      expect(body).toEqual({
        name: '叶孤城',
        personality: '孤傲',
        background: '剑客',
        goals: '决战',
        extra: { role_rank: 'major', groups: [] },
      });
    });
    // 对话框关闭 + 列表刷新（重新 GET 出现新角色）
    await waitFor(() => {
      expect(screen.queryByTestId('library-create-dialog')).not.toBeInTheDocument();
      expect(screen.getByTestId('library-list')).toHaveTextContent('叶孤城');
    });
  });

  it('创建保存失败：POST reject → err toast + 对话框保持打开（可修改重试）', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/outlines') {
        // GET 空列表（空态）；POST 失败（reject）——区分 method，否则 POST 也命中空列表分支 resolve
        if (init?.method === 'POST') throw new Error('创建失败');
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      throw new Error('创建失败');
    });
    const { user, dialog } = await openCreateDialog('大纲');
    await user.type(within(dialog).getByLabelText('名称'), '卷一 风起');
    await user.click(within(dialog).getByTestId('library-create-save'));
    // err toast（errorMessage）
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
    });
    // 对话框保持
    expect(screen.getByTestId('library-create-dialog')).toBeInTheDocument();
  });

  it('知识图谱 tab 空态 → 图谱空态引导（F48：不再跳 /writing，改图谱空态 library-kg-empty）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    // 图谱默认 mock 有数据（nodes 非空）→ 先 mock 空（空态前提：graph 返回 nodes=[] edges=[]）
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/knowledge-graph') return { nodes: [], edges: [] };
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '知识图谱' }));
    const empty = await screen.findByTestId('library-kg-empty');
    // F48 §5.4：空态 CTA 不再跳 /writing（图谱空态引导去实体页/建关系）。
    // LocationProbe 只在 /projects 或 /writing 路由渲染——probe 不存在 = 未发生跳转。
    expect(empty).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByTestId('location-probe')).toBeNull();
    });
  });
});

/**
 * F43（2026-08-12，specs/f43-setting-library-crud/spec.md §5.1-5.4/§9.2）：
 * 六分类列表项编辑/删除（P0 批次）。
 *
 * GREEN 契约（library.tsx + LibraryCreateDialog.tsx + ConfirmDialog.tsx + i18n zh/en）：
 * - 列表行（非知识图谱）操作按钮：lib-edit-<id>（编辑）/ lib-delete-<id>（删除）
 * - 行编辑 → LibraryCreateDialog 双模式（editing prop 预填现值，data-testid=library-create-dialog 不变；
 *   保存按钮 library-create-save 不变）→ 保存 → PATCH 扁平端点（§3.1 表）→ 关框 + 刷新 + lib-save-indicator「已保存」
 * - 行删除 → ConfirmDialog（testidPrefix='lib-confirm'）：lib-confirm-dialog / lib-confirm-cancel / lib-confirm-ok；
 *   文案 = lib.delete.confirm「点击确认后立即移除（后台逻辑删除，30 天后彻底清除）」；
 *   世界观追加 lib.delete.worldCascade「该条目及其全部子条目将级联删除，不可恢复」+ DELETE ?cascade=true
 * - #195：遮罩点击不关闭；关闭仅 取消/Esc/确认成功
 * - 删除成功 → reloadKey 刷新 + ok toast（toast.saved）；失败 → err toast + 列表不变
 * - 知识图谱 tab 无列表行操作按钮（图谱画布视图，F48 改造——L10 用例改断言 library-kg-canvas）
 *
 * RED 预期：lib-edit-x / lib-delete-x / lib-confirm-dialog / lib-save-indicator 均不存在 →
 * element-missing（类 3 契约缺口）；L10 改断言 library-kg-canvas（F48 图谱视图，非确认型）。
 */
describe('设定库页 — F43 列表项编辑/删除（P0）', () => {
  /** 角色列表完整 DTO（编辑预填需要全字段，spec §2.1；P1 契约升级 2026-08-13：含等级/标签 extra——编辑保存 enabled 前提） */
  const fullChar = {
    id: 'c1', name: '林晚', personality: '孤傲', background: '剑客', goals: '决战',
    extra: { role_rank: 'major', groups: [] },
  };

  /** 播种 p1 + 角色列表 mock（回显式：PATCH 合并更新，GET 返回最新） */
  function mockCharacters() {
    const chars: Array<Record<string, unknown>> = [{ ...fullChar }];
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/characters') {
        return { items: chars, total: chars.length, offset: 0, limit: 50 };
      }
      // 编辑保存 PATCH 打扁平端点（spec §3.1：PATCH /api/v1/characters/{id}），合并更新回显
      if (path === '/api/v1/characters/c1' && init?.method === 'PATCH') {
        const body = init.body as Record<string, string>;
        chars[0] = { ...chars[0], ...body };
        return chars[0];
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
  }

  it('L1 行编辑按钮点击 → 对话框打开且预填现值（getByDisplayValue）', async () => {
    mockCharacters();
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-edit-c1'));

    const dialog = await screen.findByTestId('library-create-dialog');
    expect(within(dialog).getByLabelText('名称')).toHaveValue('林晚');
    expect(within(dialog).getByLabelText('性格')).toHaveValue('孤傲');
    expect(within(dialog).getByLabelText('背景')).toHaveValue('剑客');
    expect(within(dialog).getByLabelText('目标')).toHaveValue('决战');
  });

  it('L2 编辑保存：PATCH /api/v1/characters/c1 → 关框 + 列表刷新显示新名 + 顶部「已保存」指示', async () => {
    mockCharacters();
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-edit-c1'));
    const dialog = await screen.findByTestId('library-create-dialog');
    const nameInput = within(dialog).getByLabelText('名称');
    await user.clear(nameInput);
    await user.type(nameInput, '叶孤城');
    await user.click(within(dialog).getByTestId('library-create-save'));

    await waitFor(() => {
      const patchCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/characters/c1' && c[1]?.method === 'PATCH',
      );
      expect(patchCall).toBeTruthy();
      expect(patchCall![1]!.body).toEqual(expect.objectContaining({ name: '叶孤城' }));
    });
    // 关框 + 列表刷新（GET 回显新名）+ 顶部「已保存」指示（#189 模式，lib-save-indicator）
    await waitFor(() => {
      expect(screen.queryByTestId('library-create-dialog')).not.toBeInTheDocument();
      expect(screen.getByTestId('library-list')).toHaveTextContent('叶孤城');
      expect(screen.getByTestId('lib-save-indicator').textContent).toBe('已保存');
    });
  });

  it('L3 编辑保存失败：PATCH reject → err toast + 对话框保持打开', async () => {
    mockCharacters();
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/characters') {
        return { items: [{ ...fullChar }], total: 1, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/characters/c1' && init?.method === 'PATCH') throw new Error('保存失败');
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-edit-c1'));
    const dialog = await screen.findByTestId('library-create-dialog');
    const nameInput = within(dialog).getByLabelText('名称');
    await user.clear(nameInput);
    await user.type(nameInput, '叶孤城');
    await user.click(within(dialog).getByTestId('library-create-save'));

    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
    });
    expect(screen.getByTestId('library-create-dialog')).toBeInTheDocument();
  });

  it('L4 行删除按钮 → 确认框：标题含名称 + D11 统一文案', async () => {
    mockCharacters();
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-delete-c1'));

    const confirm = await screen.findByTestId('lib-confirm-dialog');
    expect(confirm).toHaveTextContent('林晚');
    expect(confirm).toHaveTextContent('点击确认后立即移除，不可恢复');
  });

  it('L5 确认删除：DELETE /api/v1/characters/c1 → 关框 + 列表刷新（条目消失）+ ok toast', async () => {
    // 状态化 mock：初始含 c1（渲染删除按钮），DELETE 后清空（列表刷新条目消失）
    const chars = [{ ...fullChar }];
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/characters') {
        return { items: chars, total: chars.length, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/characters/c1' && init?.method === 'DELETE') {
        chars.length = 0;
        return undefined;
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-delete-c1'));
    await user.click(await screen.findByTestId('lib-confirm-ok'));

    await waitFor(() => {
      expect(
        apiFetchMock.mock.calls.some(
          (c) => c[0] === '/api/v1/characters/c1' && c[1]?.method === 'DELETE',
        ),
      ).toBe(true);
      expect(screen.queryByTestId('lib-confirm-dialog')).not.toBeInTheDocument();
      expect(screen.queryByText('林晚')).not.toBeInTheDocument();
      expect(useToastStore.getState().toasts.some((t) => t.type === 'ok')).toBe(true);
    });
  });

  it('L6 世界观删除：确认框含级联警告 + DELETE 带 ?cascade=true', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/world-settings') {
        return { items: [{ id: 'w1', name: '九州', category: '地理', content: '天下地理' }], total: 1, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/world-settings/w1?cascade=true' && init?.method === 'DELETE') return undefined;
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-delete-w1'));

    const confirm = await screen.findByTestId('lib-confirm-dialog');
    expect(confirm).toHaveTextContent('该条目及其全部子条目将级联删除，不可恢复');
    await user.click(within(confirm).getByTestId('lib-confirm-ok'));

    await waitFor(() => {
      expect(
        apiFetchMock.mock.calls.some(
          (c) => c[0] === '/api/v1/world-settings/w1?cascade=true' && c[1]?.method === 'DELETE',
        ),
      ).toBe(true);
    });
  });

  it('L7 取消按钮关闭且零请求；遮罩点击不关闭（#195）', async () => {
    mockCharacters();
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    // 取消路径
    await user.click(screen.getByTestId('lib-delete-c1'));
    await user.click(await screen.findByTestId('lib-confirm-cancel'));
    expect(screen.queryByTestId('lib-confirm-dialog')).not.toBeInTheDocument();

    // 遮罩点击不关闭（#195：遮罩是 dialog 的父层 role=presentation）
    await user.click(screen.getByTestId('lib-delete-c1'));
    const confirm = await screen.findByTestId('lib-confirm-dialog');
    const overlay = confirm.parentElement;
    expect(overlay).not.toBeNull();
    await user.click(overlay!);
    expect(screen.getByTestId('lib-confirm-dialog')).toBeInTheDocument();

    // 全程零 DELETE 调用
    expect(apiFetchMock.mock.calls.some((c) => c[1]?.method === 'DELETE')).toBe(false);
  });

  it('L8 Esc 关闭确认框且零请求', async () => {
    mockCharacters();
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-delete-c1'));
    await screen.findByTestId('lib-confirm-dialog');
    await user.keyboard('{Escape}');

    expect(screen.queryByTestId('lib-confirm-dialog')).not.toBeInTheDocument();
    expect(apiFetchMock.mock.calls.some((c) => c[1]?.method === 'DELETE')).toBe(false);
  });

  it('L9 删除失败：DELETE reject → err toast + 列表不变（条目仍在）', async () => {
    mockCharacters();
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/characters') {
        return { items: [{ ...fullChar }], total: 1, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/characters/c1' && init?.method === 'DELETE') throw new Error('删除失败');
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-delete-c1'));
    await user.click(await screen.findByTestId('lib-confirm-ok'));

    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
      expect(screen.getByTestId('library-list')).toHaveTextContent('林晚');
    });
  });

  it('L10 知识图谱 tab 无列表行操作按钮（图谱画布视图 library-kg-canvas，F48 改造）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/knowledge-graph') {
        return { nodes: [], edges: [] };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '知识图谱' }));
    const canvas = await screen.findByTestId('library-kg-canvas');
    expect(canvas).toBeInTheDocument();
    // 图谱视图非列表：F43 列表行编辑/删除按钮不存在（F48 关系编辑走画布/关系列表内交互）
    expect(within(canvas).queryAllByTestId(/^lib-edit-/)).toHaveLength(0);
    expect(within(canvas).queryAllByTestId(/^lib-delete-/)).toHaveLength(0);
  });
});
