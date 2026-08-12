/**
 * 项目页测试契约（Issue #79 RED 阶段，spec §4.2.2）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 ProjectsPage 必须匹配（行为断言，不测样式）：
 *
 * - 挂载 → projectStore.loadProjects()（GET /api/v1/projects）→ 卡片网格
 * - 卡片（data-testid="project-card"）：
 *   书名 / 题材 / 目标字数 / 章节进度「第 n 章 / m 章」（n = word_count>0 章节数，m = 总数）
 *   / 更新时间相对时间 / 进度条（role="progressbar"，aria-valuenow = round(n/m*100)）
 *   / 写作中标记（data-testid="writing-badge"，文案「写作中」；依据 currentProjectId === project.id）
 * - 双入口：主按钮 data-testid="new-project-btn" + 网格末位虚线卡片 data-testid="new-project-card"（均打开新建对话框）
 * - 新建对话框（role="dialog"）：书名必填 1-100（空 → 「书名不能为空」，不发 POST）
 *   / 题材 11 枚举（Genre） / 语言（含 zh-CN） / 目标字数默认 800000
 * - 「创建」→ POST /api/v1/projects → 201 → navigate('/writing')（渲染于 MemoryRouter 下断言）
 * - #232 点击项目卡片 → selectProject(p.id)（store currentProjectId 切换）+ navigate('/writing')：
 *   ① ProjectCard 根元素可点击——GREEN 必须：onClick prop（ProjectsPage 传入）+ role="button" +
 *      tabIndex={0} + Enter/Space 键盘触发（cursor-pointer 为样式，不测）
 *   ② ProjectsPage 卡片 onClick = useProjectStore.selectProject(p.id) + useNavigate()('/writing')
 *      （复用 NewProjectDialog 创建成功后的既有跳转模式）
 *   ③ 多项目切换：点击不同卡片 → currentProjectId 分别切换（p1 / p2）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ProjectsPage } from './projects';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';
import type { Project } from '../stores/project';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const GENRES = ['玄幻', '科幻', '言情', '仙侠', '武侠', '都市', '历史', '游戏', '悬疑', '奇幻', '其他'];

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'p1',
    name: '青云志',
    genre: '玄幻',
    language: 'zh-CN',
    target_words: 800000,
    config: {},
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
    ...overrides,
  };
}

/** 12 章中 3 章有正文（word_count>0）→ written=3, total=12 */
function chapterPage(total: number, written: number) {
  return {
    items: Array.from({ length: total }, (_, i) => ({
      id: `c${i}`, project_id: 'p1', volume_id: null, title: `第${i + 1}章`, content: '',
      word_count: i < written ? 500 : 0, order_index: i,
    })),
    total,
    offset: 0,
    limit: 50,
  };
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects' && (!init?.method || init.method === 'GET')) {
      return {
        items: [makeProject({ id: 'p1', name: '青云志', updated_at: new Date(Date.now() - 30_000).toISOString() }),
          makeProject({ id: 'p2', name: '山海经', genre: '神话', updated_at: new Date(Date.now() - 5 * 86_400_000).toISOString() })],
        total: 2, offset: 0, limit: 50,
      };
    }
    if (path === '/api/v1/projects/p1/chapters') return chapterPage(12, 3);
    if (path === '/api/v1/projects/p2/chapters') return chapterPage(0, 0);
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

function renderProjectsPage(initialEntry = '/projects') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/writing" element={<div data-testid="writing-probe">写作页探针</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('项目页 — 卡片网格（spec §4.2.2）', () => {
  it('挂载加载项目列表并渲染卡片：书名/题材/目标字数/进度/更新时间/进度条', async () => {
    useProjectStore.setState({ currentProjectId: 'p1' }); // 写作中标记依据
    renderProjectsPage();

    // 卡片出现（loadProjects 异步完成；mock 2 个项目 → 用 findAll 取第一张）
    const card1 = (await screen.findAllByTestId('project-card'))[0];
    expect(card1).toHaveTextContent('青云志');
    expect(card1).toHaveTextContent('玄幻');
    expect(card1).toHaveTextContent(/800,?000/); // 目标字数
    // 章节进度：第 3 章 / 12 章（written=3, total=12）
    expect(card1).toHaveTextContent('第 3 章 / 12 章');
    // 更新时间相对时间：p1 刚刚更新
    expect(card1).toHaveTextContent('刚刚');
    // 进度条：3/12 → 25
    const bar = within(card1).getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '25');

    const cards = screen.getAllByTestId('project-card');
    expect(cards).toHaveLength(2);
    expect(cards[1]).toHaveTextContent('山海经');
    expect(cards[1]).toHaveTextContent('5 天前');
  });

  it('写作中标记：仅 currentProjectId 对应卡片显示', async () => {
    useProjectStore.setState({ currentProjectId: 'p1' });
    renderProjectsPage();
    const card1 = (await screen.findAllByTestId('project-card'))[0];
    expect(within(card1).getByTestId('writing-badge')).toHaveTextContent('写作中');
    const cards = screen.getAllByTestId('project-card');
    expect(within(cards[1]).queryByTestId('writing-badge')).not.toBeInTheDocument();
  });

  it('加载失败：错误态展示（不渲染卡片）', async () => {
    apiFetchMock.mockRejectedValue(new Error('内核未就绪'));
    renderProjectsPage();
    await screen.findByText(/内核未就绪/);
    expect(screen.queryByTestId('project-card')).not.toBeInTheDocument();
  });
});

describe('项目页 — 双入口（主按钮 + 末位虚线卡片）', () => {
  it('主按钮与虚线卡片均可打开新建对话框', async () => {
    const user = userEvent.setup();
    renderProjectsPage();

    await user.click(screen.getByTestId('new-project-btn'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('new-project-card'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});

describe('项目页 — 新建对话框', () => {
  it('字段：书名必填 / 题材 11 枚举 / 语言含 zh-CN / 目标字数默认 800000', async () => {
    const user = userEvent.setup();
    renderProjectsPage();
    await user.click(screen.getByTestId('new-project-btn'));

    const dlg = screen.getByRole('dialog');
    expect(within(dlg).getByLabelText('书名')).toBeInTheDocument();
    // Radix Select（#98 Q1=A 契约升级）：trigger 是 combobox，选项打开面板后 portal 渲染
    const genre = within(dlg).getByRole('combobox', { name: '题材' });
    expect(genre).toBeInTheDocument();
    await user.click(genre);
    // 11 种 Genre 枚举全量存在（打开的面板只渲染当前 select 的 option）
    for (const g of GENRES) {
      expect(await screen.findByRole('option', { name: g })).toBeInTheDocument();
    }
    await user.keyboard('{Escape}');
    expect(within(dlg).getByLabelText('语言')).toBeInTheDocument();
    await user.click(within(dlg).getByRole('combobox', { name: '语言' }));
    expect(await screen.findByRole('option', { name: 'zh-CN' })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(within(dlg).getByLabelText('目标字数')).toHaveValue(800000);
  });

  it('书名空校验：显示「书名不能为空」，不发 POST', async () => {
    const user = userEvent.setup();
    renderProjectsPage();
    await user.click(screen.getByTestId('new-project-btn'));
    await user.click(screen.getByRole('button', { name: '创建' }));

    expect(screen.getByText('书名不能为空')).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalledWith('/api/v1/projects', expect.objectContaining({ method: 'POST' }));
  });

  it('创建成功：POST /api/v1/projects → 201 → 跳转写作页', async () => {
    const user = userEvent.setup();
    const created = makeProject({ id: 'p9', name: '青山入我怀', genre: '言情' });
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/projects' && init?.method === 'POST') return created;
      if (path === '/api/v1/projects' && (!init?.method || init.method === 'GET')) {
        // 初始列表为空——避免 POST 创建（p9）与 GET 列表（p9）重复导致 React key 冲突
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      if (path.startsWith('/api/v1/projects/p9/chapters')) return chapterPage(0, 0);
      return { items: [], total: 0, offset: 0, limit: 50 };
    });

    renderProjectsPage();
    await user.click(screen.getByTestId('new-project-btn'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');
    await user.click(within(screen.getByRole('dialog')).getByRole('combobox', { name: '题材' }));
    await user.click(await screen.findByRole('option', { name: '言情' }));
    await user.click(screen.getByRole('button', { name: '创建' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects', {
        method: 'POST',
        body: { name: '青山入我怀', genre: '言情', language: 'zh-CN', target_words: 800000 },
      });
    });
    // 201 后跳转写作页
    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
    expect(useProjectStore.getState().currentProjectId).toBe('p9');
  });
});

/**
 * #98 §5.2.6 空态设计：空列表引导化分支（本 describe 为增量契约，未改动上述既有断言）
 *
 * ⚠️ 契约：GREEN 实现 ProjectsPage 空列表分支（projects.length===0 且 error===null 且加载完成）必须匹配：
 * - 引导化空态容器 data-testid="projects-empty"（居中：图标 + 主文案 + 次文案 + CTA 按钮）
 * - 主文案「还没有项目」、次文案「创建你的第一个故事，从书名开始」（i18n 新 key，GREEN 补）
 * - 空态 CTA 按钮（名称「新建项目」，可复用 pj.new）点击 → 打开新建对话框（role=dialog）
 * - 网格末位虚线卡片 data-testid="new-project-card" 保留条件 = 有项目时（空列表不渲染）
 * - 与「加载失败」态区分：空态仅在 error===null 时出现（失败态渲染错误框，既有契约）
 */
describe('项目页 — 空列表引导化空态（#98 §5.2.6）', () => {
  /** 空列表 mock：GET /projects 返回空 items（区别于加载失败态） */
  function mockEmptyProjects() {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [], total: 0, offset: 0, limit: 50 };
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
  }

  it('空列表（无项目、无错误）→ 引导化空态：主文案 + 次文案', async () => {
    mockEmptyProjects();
    renderProjectsPage();
    const empty = await screen.findByTestId('projects-empty');
    expect(empty).toHaveTextContent('还没有项目');
    expect(empty).toHaveTextContent('创建你的第一个故事，从书名开始');
  });

  it('空态 CTA「新建项目」→ 打开新建对话框（role=dialog）', async () => {
    const user = userEvent.setup();
    mockEmptyProjects();
    renderProjectsPage();
    const empty = await screen.findByTestId('projects-empty');
    await user.click(within(empty).getByRole('button', { name: '新建项目' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('空态下不渲染「+ 新建项目」虚线卡片（保留条件 = 有项目）', async () => {
    mockEmptyProjects();
    renderProjectsPage();
    // 等 loadProjects 完成（loading 先 true 后 false）
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));
    expect(screen.queryByTestId('new-project-card')).not.toBeInTheDocument();
  });

  it('回归：有项目时虚线卡片保留，空态不出现', async () => {
    renderProjectsPage();
    await screen.findAllByTestId('project-card');
    expect(screen.getByTestId('new-project-card')).toBeInTheDocument();
    expect(screen.queryByTestId('projects-empty')).not.toBeInTheDocument();
  });
});

/**
 * #232 点击项目卡片跳转写作页（2026-08-10 增量契约，Issue #232）
 *
 * ⚠️ 契约：GREEN 实现必须匹配（RED 阶段本 describe 全部 FAIL——卡片无 onClick）：
 * - ProjectCard 根元素可点击：role="button"（可访问名 = 卡片文本）+ tabIndex={0}（React 渲染 tabindex="0"）
 * - 点击卡片 → useProjectStore.selectProject(id)（currentProjectId 切换为被点项目）
 *   + navigate('/writing')（writing-probe 出现；复用 NewProjectDialog 创建成功跳转模式）
 * - 多项目切换：p1 / p2 卡片分别点击 → currentProjectId 对应切换
 * - 键盘可达：卡片 focus 后 Enter 触发同样跳转（Space 可选，契约不钉）
 * - 既有用例零回归：cards 数组顺序 = mock 返回顺序（p1 青云志 / p2 山海经）
 */
describe('项目页 — 点击卡片跳转写作页（#232）', () => {
  it('点击第一张卡片（p1 青云志）→ currentProjectId 切换 + 跳转写作页', async () => {
    const user = userEvent.setup();
    renderProjectsPage();
    const cards = await screen.findAllByTestId('project-card');

    await user.click(cards[0]);

    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
    expect(useProjectStore.getState().currentProjectId).toBe('p1');
  });

  it('点击第二张卡片（p2 山海经）→ 项目上下文切换为 p2（多项目切换）', async () => {
    const user = userEvent.setup();
    renderProjectsPage();
    const cards = await screen.findAllByTestId('project-card');

    await user.click(cards[1]);

    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
    expect(useProjectStore.getState().currentProjectId).toBe('p2');
  });

  it('键盘可达：卡片 role=button + tabindex=0，Enter 触发跳转', async () => {
    const user = userEvent.setup();
    renderProjectsPage();
    const card = (await screen.findAllByTestId('project-card'))[0];

    expect(card).toHaveAttribute('role', 'button');
    expect(card).toHaveAttribute('tabindex', '0');

    card.focus();
    await user.keyboard('{Enter}');

    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
    expect(useProjectStore.getState().currentProjectId).toBe('p1');
  });
});

/**
 * F43（2026-08-12，specs/f43-setting-library-crud/spec.md §5.5/§5.6/§9.2）：
 * 项目卡片菜单（重命名/删除，US-3）。
 *
 * GREEN 契约（ProjectCard.tsx + projects.tsx + stores/project.ts + i18n zh/en）：
 * - 卡片菜单按钮 data-testid=project-card-menu-<id>（点击 stopPropagation，不触发卡片跳转 #232）
 * - 菜单项：project-rename-<id>（重命名）/ project-delete-<id>（删除）
 * - 重命名对话框（轻量单字段）：project-rename-dialog / project-rename-input（预填现名）/
 *   project-rename-save / project-rename-cancel → 保存 → store.renameProject(id, name)
 *   → PATCH /api/v1/projects/{id} body {name} → 关框 + 卡片显示新名 + ok toast
 * - 删除确认 ConfirmDialog（testidPrefix='project-delete'）：project-delete-dialog / -cancel / -ok；
 *   文案 = pj.delete.range「其章节、设定、大纲、时间线数据将全部删除」+ D11 统一行；
 *   确认 → store.deleteProject(id) → DELETE → 卡片消失；删除当前项目 → currentProjectId 置 null
 * - #195：遮罩点击不关闭；失败 → err toast
 *
 * RED 预期：project-card-menu-* 不存在 → element-missing（类 3 契约缺口）。
 */
describe('项目页 — F43 卡片菜单重命名/删除（P0）', () => {
  it('P1 卡片菜单按钮 → 菜单项（重命名/删除）可见', async () => {
    const user = userEvent.setup();
    renderProjectsPage();
    await screen.findAllByTestId('project-card');

    await user.click(screen.getByTestId('project-card-menu-p1'));

    expect(screen.getByTestId('project-rename-p1')).toBeInTheDocument();
    expect(screen.getByTestId('project-delete-p1')).toBeInTheDocument();
  });

  it('P2 菜单按钮点击不触发卡片跳转（stopPropagation，#232 回归）', async () => {
    const user = userEvent.setup();
    renderProjectsPage();
    await screen.findAllByTestId('project-card');
    useProjectStore.setState({ currentProjectId: null });

    await user.click(screen.getByTestId('project-card-menu-p1'));

    expect(screen.queryByTestId('writing-probe')).not.toBeInTheDocument();
    expect(useProjectStore.getState().currentProjectId).toBeNull();
  });

  it('P3 重命名：输入新名 → PATCH {name} → 关框 + 卡片显示新名 + ok toast', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects' && !init?.method) {
        return {
          items: [makeProject({ id: 'p1', name: '青云志' })],
          total: 1, offset: 0, limit: 50,
        };
      }
      if (path === '/api/v1/projects/p1/chapters') return chapterPage(0, 0);
      if (path === '/api/v1/projects/p1' && init?.method === 'PATCH') {
        return makeProject({ id: 'p1', name: (init.body as { name: string }).name });
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderProjectsPage();
    await screen.findAllByTestId('project-card');

    await user.click(screen.getByTestId('project-card-menu-p1'));
    await user.click(screen.getByTestId('project-rename-p1'));

    const dialog = await screen.findByTestId('project-rename-dialog');
    const input = within(dialog).getByTestId('project-rename-input');
    expect(input).toHaveValue('青云志'); // 预填现名
    await user.clear(input);
    await user.type(input, '青云志·改');
    await user.click(within(dialog).getByTestId('project-rename-save'));

    await waitFor(() => {
      const patchCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1' && c[1]?.method === 'PATCH',
      );
      expect(patchCall).toBeTruthy();
      expect(patchCall![1]!.body).toEqual({ name: '青云志·改' });
    });
    await waitFor(() => {
      expect(screen.queryByTestId('project-rename-dialog')).not.toBeInTheDocument();
      expect(screen.getByText('青云志·改')).toBeInTheDocument();
      expect(useToastStore.getState().toasts.some((t) => t.type === 'ok')).toBe(true);
    });
  });

  it('P4 重命名失败：PATCH reject → err toast + 对话框保持', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/projects' && !init?.method) {
        return {
          items: [makeProject({ id: 'p1', name: '青云志' })],
          total: 1, offset: 0, limit: 50,
        };
      }
      if (path === '/api/v1/projects/p1/chapters') return chapterPage(0, 0);
      if (path === '/api/v1/projects/p1' && init?.method === 'PATCH') throw new Error('改名失败');
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderProjectsPage();
    await screen.findAllByTestId('project-card');

    await user.click(screen.getByTestId('project-card-menu-p1'));
    await user.click(screen.getByTestId('project-rename-p1'));
    const dialog = await screen.findByTestId('project-rename-dialog');
    const input = within(dialog).getByTestId('project-rename-input');
    await user.clear(input);
    await user.type(input, '新名');
    await user.click(within(dialog).getByTestId('project-rename-save'));

    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
      expect(screen.getByTestId('project-rename-dialog')).toBeInTheDocument();
    });
  });

  it('P5 删除：确认框含数据范围文案 + D11 行 → 确认 → DELETE → 卡片消失', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/projects' && !init?.method) {
        return {
          items: [makeProject({ id: 'p1', name: '青云志' })],
          total: 1, offset: 0, limit: 50,
        };
      }
      if (path === '/api/v1/projects/p1/chapters') return chapterPage(0, 0);
      if (path === '/api/v1/projects/p1' && init?.method === 'DELETE') return undefined;
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderProjectsPage();
    await screen.findAllByTestId('project-card');

    await user.click(screen.getByTestId('project-card-menu-p1'));
    await user.click(screen.getByTestId('project-delete-p1'));

    const confirm = await screen.findByTestId('project-delete-dialog');
    expect(confirm).toHaveTextContent('青云志');
    expect(confirm).toHaveTextContent('其章节、设定、大纲、时间线数据将全部删除');
    expect(confirm).toHaveTextContent('点击确认后立即移除（后台逻辑删除，30 天后彻底清除）');
    await user.click(within(confirm).getByTestId('project-delete-ok'));

    await waitFor(() => {
      expect(
        apiFetchMock.mock.calls.some(
          (c) => c[0] === '/api/v1/projects/p1' && c[1]?.method === 'DELETE',
        ),
      ).toBe(true);
      expect(screen.queryByTestId('project-delete-dialog')).not.toBeInTheDocument();
      expect(screen.queryByText('青云志')).not.toBeInTheDocument();
    });
  });

  it('P6 删除当前项目 → currentProjectId 置 null（spec E7）', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/projects' && !init?.method) {
        return {
          items: [makeProject({ id: 'p1', name: '青云志' })],
          total: 1, offset: 0, limit: 50,
        };
      }
      if (path === '/api/v1/projects/p1/chapters') return chapterPage(0, 0);
      if (path === '/api/v1/projects/p1' && init?.method === 'DELETE') return undefined;
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderProjectsPage();
    await screen.findAllByTestId('project-card');
    useProjectStore.setState({ currentProjectId: 'p1' });

    await user.click(screen.getByTestId('project-card-menu-p1'));
    await user.click(screen.getByTestId('project-delete-p1'));
    await user.click(await screen.findByTestId('project-delete-ok'));

    await waitFor(() => {
      expect(useProjectStore.getState().currentProjectId).toBeNull();
    });
  });

  it('P7 删除取消：cancel → 零 DELETE 调用，卡片仍在', async () => {
    const user = userEvent.setup();
    renderProjectsPage();
    await screen.findAllByTestId('project-card');

    await user.click(screen.getByTestId('project-card-menu-p1'));
    await user.click(screen.getByTestId('project-delete-p1'));
    await user.click(await screen.findByTestId('project-delete-cancel'));

    expect(screen.queryByTestId('project-delete-dialog')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('project-card')).toHaveLength(2);
    expect(apiFetchMock.mock.calls.some((c) => c[1]?.method === 'DELETE')).toBe(false);
  });
});
