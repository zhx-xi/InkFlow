/**
 * F43 P3（specs/f43-setting-library-crud/spec.md v1.3 §5.14/§5.15/§9.6 O1-O8）：
 * 设定库大纲 tab 三级树（整体→卷→章→情节点）+ 章关联徽标（D8/D9）。
 *
 * ⚠️ 本批契约拆分至独立文件 library-p3.test.tsx（对齐 library-p1/library-p2 先例：
 * library.test.tsx 超 900 行护栏，批次契约兄弟文件拆分）。
 *
 * ==================== GREEN 契约（library.tsx 大纲 tab 挂接 OutlineTree + i18n zh/en §6 P3 表） ====================
 *
 * 【testid 清单】
 * 树容器：outline-tree
 * 节点：outline-overall-<id> / outline-volume-<id> / outline-chapter-<id> / outline-point-<id>
 * 展开收起：outline-toggle-<id>（overall/volume/chapter 三级均支持；有子节点才渲染，叶子不渲染）
 * 各层新增：outline-add-volume-<parentId>（overall 节点，文案 lib.addVolume「＋卷」）/
 *   outline-add-chapter-<parentId>（volume 节点，lib.addChapter「＋章」）/
 *   outline-add-point-<chapterId>（chapter 节点，lib.addPoint「＋情节点」）
 * 章关联：outline-chapter-ref-<id>（chapter_id 非空 → 📎 徽标 + 章节标题，title=lib.chapterRefTip）/
 *   outline-chapter-link-<id>（未关联 → lib.chapterLink「关联章节」按钮）
 * 行内操作（沿用 P0 testid）：lib-edit-<id> / lib-delete-<id>；
 *   情节点行内：outline-point-edit-<id> / outline-point-del-<id>
 *
 * 【端点 + 响应形状】
 * GET /api/v1/projects/{pid}/outlines → {items:[Outline],total,offset,limit}
 *   Outline: {id,name,description,sort_order,level('overall'|'volume'|'chapter'),
 *             parent_id,chapter_id,point_count}
 *   （建树：overall 顶层；volume 挂 parent_id=overall.id；chapter 挂 parent_id=volume.id；
 *     孤立章 level=chapter 且 parent_id 空 → 降级为顶层）
 * GET /api/v1/outlines/{id}/plot-points → {items:[PlotPoint],total}
 *   PlotPoint: {id,name,type,description,position}（chapter 首次展开按需拉取，前端本地缓存）
 * GET /api/v1/projects/{pid}/chapters → {items:[{id,title,...}],total,offset,limit}
 *   （chapter_id → title 映射，章关联徽标标题来源）
 *
 * 【i18n key（zh/en §6 P3 表，GREEN 补）】
 *   lib.level.overall|volume|chapter（整体/卷/章）/ lib.volumes（卷）/ lib.chapters（章）/
 *   lib.outlinePoints（情节点）/ lib.empty.points（暂无情节点）/
 *   lib.chapterRefTip（已关联写作章节，点击可在写作页打开）/ lib.chapterLink（关联章节）/
 *   lib.chapterLinkPick（请选择要关联的写作章节）/ lib.addVolume（＋卷）/
 *   lib.addChapter（＋章）/ lib.addPoint（＋情节点）
 *
 * 【交互契约（GREEN 必守）】
 * - 树默认展开（加载即显示全部层级；toggle 收起/展开子节点；toggle 仅在有子节点时渲染）
 * - 层级标签：overall/volume/chapter 节点渲染 lib.level.* 文案（整体/卷/章）
 * - 「关联章节」按钮点击 → 仅 toast「请选择要关联的写作章节」（lib.chapterLinkPick，
 *   选择器后置 D9 拍板），不打开章节选择器
 * - 情节点首次展开拉取 + 前端本地缓存（收起再展开不重拉）
 *
 * RED 预期：以上 testid 全部不存在（大纲 tab 仍为 P0 平铺列表）→ element-missing 断言 FAIL
 * （类 3 契约缺口）；零 SyntaxError / ReferenceError / TypeError。O1-O8 共 8 it。
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

/** Outline seed 工厂（数据契约 §2.8：id/name/description/sort_order/level/parent_id/chapter_id/point_count） */
function outlineItem(over: Record<string, unknown>): Record<string, unknown> {
  return {
    id: 'x', name: 'x', description: '', sort_order: 1,
    level: 'chapter', parent_id: null, chapter_id: null, point_count: 0,
    ...over,
  };
}

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
  useToastStore.setState({ toasts: [] }); // 防跨用例 toast 残留误判
  // 默认兜底 URL 分发：projects 双项目；其余端点空列表（用例内 mockOutlineTree 覆盖）
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1, projectP2], total: 2, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('设定库页 — F43 P3 大纲三级树 + 章关联（大纲 tab，spec §5.14-5.15/§9.6 O1-O8）', () => {
  /**
   * 播种 p1 + 大纲三级树端点 mock（状态化：GET outlines 返回浅拷贝数组，
   * GET /outlines/{id}/plot-points 按 chapterId 分发，GET /chapters 供 chapter_id→title 映射）。
   */
  function mockOutlineTree(
    outlines: Array<Record<string, unknown>>,
    opts: {
      chapters?: Array<Record<string, unknown>>;
      pointsByChapter?: Record<string, Array<Record<string, unknown>>>;
    } = {},
  ) {
    // 浅拷贝（跨用例隔离；用例内同一数组可状态化）
    const outlineList = outlines.map((o) => ({ ...o }));
    const chapterList = (opts.chapters ?? []).map((c) => ({ ...c }));
    const points: Record<string, Array<Record<string, unknown>>> = {};
    for (const [cid, list] of Object.entries(opts.pointsByChapter ?? {})) {
      points[cid] = list.map((p) => ({ ...p }));
    }

    apiFetchMock.mockImplementation(async (path: string, _init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') {
        return { items: [projectP1, projectP2], total: 2, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/outlines') {
        return { items: outlineList, total: outlineList.length, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/chapters') {
        return { items: chapterList, total: chapterList.length, offset: 0, limit: 50 };
      }
      const pointsMatch = path.match(/^\/api\/v1\/outlines\/([^/]+)\/plot-points$/);
      if (pointsMatch) {
        const list = points[pointsMatch[1]] ?? [];
        return { items: list, total: list.length };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1, projectP2], currentProjectId: 'p1' });
    });
  }

  /** 切到大纲 tab（当前 RED 仍为平铺 library-list；GREEN 后为 outline-tree） */
  async function openOutlineTab(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('tab', { name: '大纲' }));
    await screen.findByTestId('library-list');
  }

  it('O1 大纲三级树渲染：overall/volume/chapter 三级节点层级嵌套 + 层级标签（整体/卷/章）', async () => {
    mockOutlineTree([
      outlineItem({ id: 'o1', name: '大纲整体', level: 'overall' }),
      outlineItem({ id: 'v1', name: '第一卷', level: 'volume', parent_id: 'o1' }),
      outlineItem({ id: 'c1', name: '第一章 初入江湖', level: 'chapter', parent_id: 'v1' }),
    ]);
    renderLibrary();
    const user = userEvent.setup();
    await openOutlineTab(user);
    // 树容器 + 三级节点（默认展开；GREEN 子节点 DOM 嵌套于父节点内）
    const tree = screen.getByTestId('outline-tree');
    const overall = within(tree).getByTestId('outline-overall-o1');
    const volume = within(overall).getByTestId('outline-volume-v1');
    const chapter = within(volume).getByTestId('outline-chapter-c1');
    // 层级标签（lib.level.overall|volume|chapter）
    expect(within(overall).getByText('整体')).toBeInTheDocument();
    expect(within(volume).getByText('卷')).toBeInTheDocument();
    expect(within(chapter).getByText('章')).toBeInTheDocument();
    // 行内编辑/删除沿用 P0 testid（lib-edit-<id> / lib-delete-<id>）
    expect(within(overall).getByTestId('lib-edit-o1')).toBeInTheDocument();
  });

  it('O2 孤立章降级顶层：level=chapter 且 parent 空 → outline-chapter-c2 渲染为顶层节点', async () => {
    mockOutlineTree([
      outlineItem({ id: 'o1', name: '大纲整体', level: 'overall' }),
      outlineItem({ id: 'c2', name: '第二章 孤岛', level: 'chapter', parent_id: null }),
    ]);
    renderLibrary();
    const user = userEvent.setup();
    await openOutlineTab(user);
    const tree = screen.getByTestId('outline-tree');
    // 孤立章渲染为顶层节点（在树中，但不在任何 overall 节点内）
    expect(within(tree).getByTestId('outline-chapter-c2')).toBeInTheDocument();
    const overall = screen.getByTestId('outline-overall-o1');
    expect(within(overall).queryByTestId('outline-chapter-c2')).not.toBeInTheDocument();
    // 孤立章无子节点 → 不渲染 toggle（有子节点才渲染）
    expect(screen.queryByTestId('outline-toggle-c2')).not.toBeInTheDocument();
  });

  it('O3 三级展开/收起：点 outline-toggle-o1 → 子节点显隐；叶子章无 toggle', async () => {
    mockOutlineTree([
      outlineItem({ id: 'o1', name: '大纲整体', level: 'overall' }),
      outlineItem({ id: 'v1', name: '第一卷', level: 'volume', parent_id: 'o1' }),
      outlineItem({ id: 'c1', name: '第一章', level: 'chapter', parent_id: 'v1' }),
    ]);
    renderLibrary();
    const user = userEvent.setup();
    await openOutlineTab(user);
    // 默认展开：三级可见
    expect(screen.getByTestId('outline-volume-v1')).toBeInTheDocument();
    expect(screen.getByTestId('outline-chapter-c1')).toBeInTheDocument();
    // 收起 o1 → 子卷隐藏（toggle 本身仍在）
    await user.click(screen.getByTestId('outline-toggle-o1'));
    await waitFor(() => expect(screen.queryByTestId('outline-volume-v1')).not.toBeInTheDocument());
    expect(screen.getByTestId('outline-toggle-o1')).toBeInTheDocument();
    // 再展开 → 卷回来
    await user.click(screen.getByTestId('outline-toggle-o1'));
    await waitFor(() => expect(screen.getByTestId('outline-volume-v1')).toBeInTheDocument());
    // 卷级收起 → 章隐藏
    await user.click(screen.getByTestId('outline-toggle-v1'));
    await waitFor(() => expect(screen.queryByTestId('outline-chapter-c1')).not.toBeInTheDocument());
    await user.click(screen.getByTestId('outline-toggle-v1'));
    await waitFor(() => expect(screen.getByTestId('outline-chapter-c1')).toBeInTheDocument());
    // 叶子（无子节点）不渲染 toggle
    expect(screen.queryByTestId('outline-toggle-c1')).not.toBeInTheDocument();
  });

  it('O4 各层新增按钮：overall 有 outline-add-volume-o1；volume 有 outline-add-chapter-v1；chapter 有 outline-add-point-c1', async () => {
    mockOutlineTree([
      outlineItem({ id: 'o1', name: '大纲整体', level: 'overall' }),
      outlineItem({ id: 'v1', name: '第一卷', level: 'volume', parent_id: 'o1' }),
      outlineItem({ id: 'c1', name: '第一章', level: 'chapter', parent_id: 'v1' }),
    ]);
    renderLibrary();
    const user = userEvent.setup();
    await openOutlineTab(user);
    const overall = screen.getByTestId('outline-overall-o1');
    const volume = screen.getByTestId('outline-volume-v1');
    const chapter = screen.getByTestId('outline-chapter-c1');
    // overall 节点「＋卷」（lib.addVolume）
    const addVolume = within(overall).getByTestId('outline-add-volume-o1');
    expect(addVolume).toHaveTextContent('＋卷');
    // volume 节点「＋章」（lib.addChapter）
    const addChapter = within(volume).getByTestId('outline-add-chapter-v1');
    expect(addChapter).toHaveTextContent('＋章');
    // chapter 节点「＋情节点」（lib.addPoint）
    const addPoint = within(chapter).getByTestId('outline-add-point-c1');
    expect(addPoint).toHaveTextContent('＋情节点');
    // 层级专属：volume 无「＋卷」、chapter 无「＋章」
    expect(within(volume).queryByTestId('outline-add-volume-v1')).not.toBeInTheDocument();
    expect(within(chapter).queryByTestId('outline-add-chapter-c1')).not.toBeInTheDocument();
  });

  it('O5 章关联徽标：chapter c1 带 chapter_id=ch3 → outline-chapter-ref-c1 显示 📎 + 「第3章」', async () => {
    mockOutlineTree(
      [
        outlineItem({ id: 'c1', name: '第一章', level: 'chapter', parent_id: null, chapter_id: 'ch3' }),
      ],
      { chapters: [{ id: 'ch3', title: '第3章' }] },
    );
    renderLibrary();
    const user = userEvent.setup();
    await openOutlineTab(user);
    // 已关联 → 📎 徽标 + 章节标题（chapter_id → title 映射自 GET /chapters）
    const badge = screen.getByTestId('outline-chapter-ref-c1');
    expect(badge).toHaveTextContent('📎');
    expect(badge).toHaveTextContent('第3章');
    expect(badge).toHaveAttribute('title', '已关联写作章节，点击可在写作页打开'); // lib.chapterRefTip
    // 已关联章不渲染「关联章节」按钮
    expect(screen.queryByTestId('outline-chapter-link-c1')).not.toBeInTheDocument();
  });

  it('O6 章关联按钮：chapter c2 无 chapter_id → outline-chapter-link-c2 「关联章节」按钮', async () => {
    mockOutlineTree([
      outlineItem({ id: 'c2', name: '第二章', level: 'chapter', parent_id: null, chapter_id: null }),
    ]);
    renderLibrary();
    const user = userEvent.setup();
    await openOutlineTab(user);
    // 未关联 → 「关联章节」按钮（lib.chapterLink）
    const linkBtn = screen.getByTestId('outline-chapter-link-c2');
    expect(linkBtn).toHaveTextContent('关联章节');
    // 未关联章不渲染 📎 徽标
    expect(screen.queryByTestId('outline-chapter-ref-c2')).not.toBeInTheDocument();
  });

  it('O7 关联章节按钮点击：点 outline-chapter-link-c2 → toast「请选择要关联的写作章节」（选择器后置）', async () => {
    mockOutlineTree([
      outlineItem({ id: 'c2', name: '第二章', level: 'chapter', parent_id: null, chapter_id: null }),
    ]);
    renderLibrary();
    const user = userEvent.setup();
    await openOutlineTab(user);
    await user.click(screen.getByTestId('outline-chapter-link-c2'));
    // 选择器后置（D9）：仅 toast 提示（lib.chapterLinkPick），不打开章节选择器
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.message === '请选择要关联的写作章节')).toBe(true);
    });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('O8 情节点拉取渲染：chapter 展开 → GET /outlines/c1/plot-points → outline-point-x 渲染 + 本地缓存 + 空态', async () => {
    mockOutlineTree(
      [
        outlineItem({ id: 'c1', name: '第一章', level: 'chapter', parent_id: null, point_count: 2 }),
        outlineItem({ id: 'c2', name: '第二章', level: 'chapter', parent_id: null, point_count: 0 }),
      ],
      {
        pointsByChapter: {
          c1: [
            { id: 'pt1', name: '情节点一', type: 'beat', description: '', position: 1 },
            { id: 'pt2', name: '情节点二', type: 'turning', description: '', position: 2 },
          ],
        },
      },
    );
    renderLibrary();
    const user = userEvent.setup();
    await openOutlineTab(user);
    // chapter 展开（默认展开）→ 按需拉取 plot-points → 情节点渲染（outline-point-<id>）
    const chapter = await screen.findByTestId('outline-chapter-c1');
    await waitFor(() => expect(within(chapter).getByTestId('outline-point-pt1')).toBeInTheDocument());
    expect(within(chapter).getByTestId('outline-point-pt2')).toBeInTheDocument();
    expect(within(chapter).getByText('情节点一')).toBeInTheDocument();
    expect(
      apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/outlines/c1/plot-points'),
    ).toBe(true);
    // 前端本地缓存：收起再展开不重拉（GET 计数不变）
    const plotPointsGetCalls = () =>
      apiFetchMock.mock.calls.filter(
        (c) => c[0] === '/api/v1/outlines/c1/plot-points' && (c[1]?.method ?? 'GET') === 'GET',
      ).length;
    const callsBefore = plotPointsGetCalls();
    await user.click(screen.getByTestId('outline-toggle-c1'));
    await waitFor(() => expect(screen.queryByTestId('outline-point-pt1')).not.toBeInTheDocument());
    await user.click(screen.getByTestId('outline-toggle-c1'));
    await waitFor(() => expect(screen.getByTestId('outline-point-pt1')).toBeInTheDocument());
    expect(plotPointsGetCalls()).toBe(callsBefore);
    // 无点章 → 情节点空态（lib.empty.points 暂无情节点）
    expect(within(screen.getByTestId('outline-chapter-c2')).getByText('暂无情节点')).toBeInTheDocument();
  });
});
