/**
 * #1002：大纲树排序 toggle + 顶层分页 —— GUI 契约测试（RED）
 * specs/f19-gui/outline.md §2 新两行（排序切换 / 顶层分页）+ §3 N6 + specs/f11-outline/spec.md §6.3 #1002。
 *
 * 消费模型（library.tsx outline tab 三路拉取）：
 *   GET /api/v1/projects/{pid}/outlines?level=overall&sort_by=sort_order&sort_desc=<asc?false:true>
 *       &offset=<page*10>&limit=10           （顶层页，pageSize=10）
 *   GET ?level=volume&limit=100 与 ?level=chapter&limit=100 循环拉全（offset 递增 100 直到 total）。
 *   合并 items = overall 当前页 ∪ 全部 volume ∪ 全部 chapter 喂 OutlineTree；非 outline tab 零改动。
 *
 * 排序 state 在 library.tsx（outlineSortDesc 默认 false），受控 props 传 OutlineTree：
 *   sortDesc + onSortChange(desc)；buildOutlineTree 兄弟排序 sort_order asc（Number 兜底 ?? 0）
 *   → tie created_at 倒序（新在前，保 AI 插树顶）→ 再 tie id 字符串升序；sortDesc=true 整体镜像。
 *
 * 卡片工具栏分段控件（恒在）：data-testid outline-sort-asc / outline-sort-desc，当前态 aria-pressed=true。
 * 点击 desc → onSortChange(true) → library.tsx 仅重拉 overall（卷/章不重拉）+ 树本地重排。
 *
 * 顶层分页条（树下方、故事弧区上方；仅 props total > pageSize 时渲染，pageSize=10）：
 *   outline-page-prev / outline-page-info / outline-page-next；首页 prev disabled、末页 next disabled；
 *   info 文本 `第 {page} / {pages} 页 · 共 {total} 条`（i18n key lib.page.info，zh/en 双份；
 *   lib.page.prev/next 复用 logs.prev/logs.next 已有键）。新 props：total、page（0 基）、onPageChange(page)。
 *   点 next → library.tsx 仅重拉 overall（offset+10）。
 *
 * AI 生成共存：onOutlineGenerated 插树顶语义不变（本地 prepend + 顶层 total 计数 +1 由父级维护）。
 *
 * ==================== RED 预期（当前组件实现状态） ====================
 * 新 testid 清单：outline-sort-asc / outline-sort-desc / outline-page-prev / outline-page-info / outline-page-next
 * 目前 components/OutlineTree.tsx（buildOutlineTree:82-99、工具栏:686-714、树渲染:715-739、props:59-74）
 *   与 pages/library.tsx（拉取 effect:289-352、OutlineTree 挂载:697-709、handleOutlineGenerated:528-531）
 *   均无排序 toggle / 顶层分页 / sortDesc·total·page 受控 props → 上述 testid 全部 element-missing → FAIL。
 * P6（非 outline tab 回归护栏）与 P7（overall 拉取失败 toast 的既有面）预计 PASS（属预期，交付标注）。
 * 整文件 collection 通过（组件已存在，import 无 undefined）。
 * 本文件不改任何组件实现 / 不改既有断言 / 不 commit。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { LibraryPage } from './library';
import { OutlineTree, type OutlineItemDTO, type OutlineTreeProps } from '../components/OutlineTree';
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
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

/** 大纲 fixture：OutlineItemDTO + 排序契约字段（sort_order 比较、created_at 倒序 tie） */
type OutlineFixture = OutlineItemDTO & { sort_order: number; created_at: string; updated_at?: string };

/** 默认 fixtures：3 overall（sort_order=3/1/2，各带 created_at 差异）+ 每 overall 下 1 volume + volume 下 2 chapters */
const o1: OutlineFixture = { id: 'o1', name: '主线规划 v1', level: 'overall', parent_id: null, chapter_id: null, point_count: 0, sort_order: 3, created_at: '2026-03-01T00:00:00Z' };
const o2: OutlineFixture = { id: 'o2', name: '主线规划 v2', level: 'overall', parent_id: null, chapter_id: null, point_count: 0, sort_order: 1, created_at: '2026-01-01T00:00:00Z' };
const o3: OutlineFixture = { id: 'o3', name: '主线规划 v3', level: 'overall', parent_id: null, chapter_id: null, point_count: 0, sort_order: 2, created_at: '2026-02-01T00:00:00Z' };
const v1: OutlineFixture = { id: 'v1', name: '卷一·宗门', level: 'volume', parent_id: 'o1', chapter_id: null, point_count: 0, sort_order: 1, created_at: '2026-03-02T00:00:00Z' };
const v2: OutlineFixture = { id: 'v2', name: '卷二·试炼', level: 'volume', parent_id: 'o2', chapter_id: null, point_count: 0, sort_order: 1, created_at: '2026-01-02T00:00:00Z' };
const v3: OutlineFixture = { id: 'v3', name: '卷三·初露', level: 'volume', parent_id: 'o3', chapter_id: null, point_count: 0, sort_order: 1, created_at: '2026-02-02T00:00:00Z' };
// v1 下两章 tie sort_order=1 → created_at 倒序（c1a 新在前）
const c1a: OutlineFixture = { id: 'c1a', name: '第一章·入门', level: 'chapter', parent_id: 'v1', chapter_id: 'ch1', point_count: 0, sort_order: 1, created_at: '2026-01-15T00:00:00Z' };
const c1b: OutlineFixture = { id: 'c1b', name: '第二章·练功', level: 'chapter', parent_id: 'v1', chapter_id: 'ch2', point_count: 0, sort_order: 1, created_at: '2026-01-14T00:00:00Z' };
const c2a: OutlineFixture = { id: 'c2a', name: '第一章·觉醒', level: 'chapter', parent_id: 'v2', chapter_id: 'ch3', point_count: 0, sort_order: 2, created_at: '2026-01-16T00:00:00Z' };
const c2b: OutlineFixture = { id: 'c2b', name: '第二章·金手指', level: 'chapter', parent_id: 'v2', chapter_id: 'ch4', point_count: 0, sort_order: 1, created_at: '2026-01-17T00:00:00Z' };
const c3a: OutlineFixture = { id: 'c3a', name: '第一章·下山', level: 'chapter', parent_id: 'v3', chapter_id: 'ch5', point_count: 0, sort_order: 1, created_at: '2026-02-15T00:00:00Z' };
const c3b: OutlineFixture = { id: 'c3b', name: '第二章·天骄', level: 'chapter', parent_id: 'v3', chapter_id: 'ch6', point_count: 0, sort_order: 2, created_at: '2026-02-16T00:00:00Z' };

const emptyRes = { items: [], total: 0, offset: 0, limit: 50 };

interface State {
  outlines: OutlineFixture[];
}

function makeState(): State {
  return {
    outlines: [o1, o2, o3, v1, v2, v3, c1a, c1b, c2a, c2b, c3a, c3b],
  };
}

/** 造 n 个 overall（sort_order=1..n，created_at 递增），无子节点 */
function makePagingState(n = 12): State {
  const overalls: OutlineFixture[] = [];
  for (let i = 1; i <= n; i += 1) {
    const id = `o${i.toString().padStart(2, '0')}`;
    overalls.push({
      id, name: `卷规划 ${id}`, level: 'overall', parent_id: null, chapter_id: null, point_count: 0,
      sort_order: i, created_at: `2026-01-${i.toString().padStart(2, '0')}T00:00:00Z`,
    });
  }
  return { outlines: overalls };
}

/** 排序：sort_order asc（Number 兜底 ?? 0）；tie → created_at 倒序（新在前）；sortDesc=true 整体镜像（tie 也镜像） */
function sortByOrder(items: OutlineFixture[], sortDesc: boolean): OutlineFixture[] {
  const arr = [...items];
  const bySort = (a: OutlineFixture, b: OutlineFixture) => (Number(a.sort_order) || 0) - (Number(b.sort_order) || 0);
  const createdNewerFirst = (a: OutlineFixture, b: OutlineFixture) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? ''));
  return arr.sort((a, b) => {
    const p = bySort(a, b);
    if (p !== 0) return sortDesc ? -p : p;
    const c = createdNewerFirst(a, b);
    return sortDesc ? -c : c;
  });
}

function renderLibrary() {
  return render(
    <MemoryRouter initialEntries={['/library']}>
      <LibraryPage />
      <Routes>
        <Route path="/projects" element={<div />} />
        <Route path="/writing" element={<div />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** 进入大纲 tab 并等待树渲染 */
async function enterOutlineTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('tab', { name: '大纲' }));
  await screen.findByTestId('outline-tree');
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useToastStore.setState({ toasts: [] });
});

/** 状态化 mock：outlines 三路拉取（解析 querystring）+ 兜底空；generate 可注入 deferred */
function mockOutlineApi(state: State, opts?: { generate?: () => Promise<unknown> }) {
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    if (path === '/api/v1/projects') {
      return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    }
    // 大纲：带 level 参数 → 按 sort_desc 排后 offset/limit 切片；无 level 参数 → 全量（旧行为，兼容未知 mock 面）
    const isOutlinesGet =
      path === '/api/v1/projects/p1/outlines' ||
      path.startsWith('/api/v1/projects/p1/outlines?');
    if (isOutlinesGet && (!init?.method || init.method === 'GET')) {
      const url = new URL(path, 'http://x');
      const level = url.searchParams.get('level');
      const sortDesc = url.searchParams.get('sort_desc') === 'true';
      const offset = Number(url.searchParams.get('offset') ?? '0');
      const limit = Number(url.searchParams.get('limit') ?? '50');
      if (!level) {
        return { items: state.outlines, total: state.outlines.length, offset: 0, limit: 50 };
      }
      const layer = state.outlines.filter((o) => o.level === level);
      const sorted = sortByOrder(layer, sortDesc);
      return { items: sorted.slice(offset, offset + limit), total: layer.length, offset, limit };
    }
    if (path === '/api/v1/projects/p1/chapters') return emptyRes;
    if (path === '/api/v1/projects/p1/maps') return emptyRes;
    if (path === '/api/v1/projects/p1/story-arcs') return emptyRes;
    if (path === '/api/v1/projects/p1/characters') return { items: [{ id: 'x1', name: '林晚' }], total: 1, offset: 0, limit: 50 };
    const pts = path.match(/^\/api\/v1\/outlines\/([^/]+)\/plot-points$/);
    if (pts) return emptyRes;
    // AI 生成（POST /api/v1/outlines/generate）→ 注入式或默认回造一个 overall
    if (path === '/api/v1/outlines/generate' && init?.method === 'POST') {
      if (opts?.generate) return opts.generate();
      const created: OutlineFixture = { id: 'o4', name: 'AI 规划卷', level: 'overall', parent_id: null, chapter_id: null, point_count: 0, sort_order: 0, created_at: '2026-09-01T00:00:00Z' };
      state.outlines.unshift(created);
      return { saved: true, outline: created, plot_points: [], arcs: [], warnings: [], model: 'test' };
    }
    return emptyRes;
  });
  act(() => {
    useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
  });
}

/** 统计 level=volume 请求次数（不因切序重拉的护栏） */
function countLevelCalls(level: string): number {
  return apiFetchMock.mock.calls.filter(
    (c) => typeof c[0] === 'string' && (c[0] as string).includes(`level=${level}`),
  ).length;
}

/** 最后一次 level=overall 请求 path */
function lastOverallCall(): string | null {
  const calls = apiFetchMock.mock.calls.filter(
    (c) => typeof c[0] === 'string' && (c[0] as string).includes('level=overall'),
  );
  return calls.length ? String(calls[calls.length - 1][0]) : null;
}

describe('#1002 大纲树排序 toggle + 顶层分页（LibraryPage 装配）', () => {
  it('P1 默认正序：工具栏 outline-sort-asc 存在且 aria-pressed=true；树根 DOM 序 = O2,O3,O1；章 tie created_at 新在前', async () => {
    mockOutlineApi(makeState());
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    // 默认正序 toggle（新元素，RED element-missing）
    expect(screen.getByTestId('outline-sort-asc')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('outline-sort-desc')).toHaveAttribute('aria-pressed', 'false');
    // 树根按 sort_order asc → O2,O3,O1
    const roots = screen.getAllByTestId(/^outline-overall-/).map((el) => el.getAttribute('data-testid'));
    expect(roots).toEqual(['outline-overall-o2', 'outline-overall-o3', 'outline-overall-o1']);
    // v1 下两章 tie sort_order=1 → created_at 倒序 → c1a（新）在前
    const v1Node = screen.getByTestId('outline-volume-v1');
    // 精确匹配章行（排除 📎 徽标 outline-chapter-ref-*，父侧契约修正 2026-09-09）
    const chapters = within(v1Node)
      .getAllByTestId(/^outline-chapter-c\d[a-b]$/)
      .map((el) => el.getAttribute('data-testid'));
    expect(chapters).toEqual(['outline-chapter-c1a', 'outline-chapter-c1b']);
  });

  it('P2 点击 outline-sort-desc → asc=false/desc=true；树根镜像 O1,O3,O2；overall 请求 sort_desc=true；volume/chapter 不重拉', async () => {
    mockOutlineApi(makeState());
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    const volumeBefore = countLevelCalls('volume');
    // RED：toggle 不存在 → click element-missing FAIL
    await user.click(screen.getByTestId('outline-sort-desc'));
    expect(screen.getByTestId('outline-sort-asc')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('outline-sort-desc')).toHaveAttribute('aria-pressed', 'true');
    // 镜像序：sort_order desc → O1(3),O3(2),O2(1)
    const roots = screen.getAllByTestId(/^outline-overall-/).map((el) => el.getAttribute('data-testid'));
    expect(roots).toEqual(['outline-overall-o1', 'outline-overall-o3', 'outline-overall-o2']);
    // 最后一次 overall 拉取 query：sort_by=sort_order&sort_desc=true&level=overall
    const last = lastOverallCall();
    expect(last).toBeTruthy();
    expect(last).toContain('level=overall');
    expect(last).toContain('sort_by=sort_order');
    expect(last).toContain('sort_desc=true');
    // volume/chapter 不因切序重拉（请求数不增）
    expect(countLevelCalls('volume')).toBe(volumeBefore);
    expect(countLevelCalls('chapter')).toBe(0);
  });

  it('P3 顶层分页（pageSize=10, 12 条）：info 可见；next → offset=10 重拉；根 = O11,O12；next disabled；prev 回页 1；prev disabled', async () => {
    mockOutlineApi(makePagingState(12));
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    // info 文本（新元素，RED element-missing）
    const info = await screen.findByTestId('outline-page-info');
    expect(info.textContent).toContain('第 1 / 2 页 · 共 12 条');
    // 首页 prev disabled
    expect(screen.getByTestId('outline-page-prev')).toBeDisabled();
    // 点 next → 仅一次 level=overall&offset=10 重拉
    const overallBefore = countLevelCalls('overall');
    await user.click(screen.getByTestId('outline-page-next'));
    await waitFor(() => {
      const last = lastOverallCall();
      expect(last).toBeTruthy();
      expect(last).toContain('offset=10');
    });
    // 第 2 页 info
    await waitFor(() => expect(screen.getByTestId('outline-page-info').textContent).toContain('第 2 / 2 页 · 共 12 条'));
    // 树内根 = O11,O12（asc 第 11,12）
    const roots = screen.getAllByTestId(/^outline-overall-/).map((el) => el.getAttribute('data-testid'));
    expect(roots).toEqual(['outline-overall-o11', 'outline-overall-o12']);
    // 末页 next disabled
    expect(screen.getByTestId('outline-page-next')).toBeDisabled();
    // prev 回页 1（offset=0 重拉）→ prev disabled（首页）
    await user.click(screen.getByTestId('outline-page-prev'));
    await waitFor(() => {
      const last = lastOverallCall();
      expect(last).toBeTruthy();
      expect(last).toContain('offset=0');
    });
    expect(screen.getByTestId('outline-page-prev')).toBeDisabled();
    expect(overallBefore).toBeGreaterThanOrEqual(1);
  });

  it('P4 默认 fixtures（3 项 ≤10）不渲染分页条：outline-page-prev 不存在', async () => {
    mockOutlineApi(makeState());
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    // 3 项 ≤10 → 无分页条（守卫生效；RED 下组件本就无分页 → 通过）
    expect(screen.queryByTestId('outline-page-prev')).not.toBeInTheDocument();
    expect(screen.queryByTestId('outline-page-info')).not.toBeInTheDocument();
  });

  it('P5 共存：AI 生成 O4（sort_order=0）→ 树顶 = O4；排序 toggle 仍在（RED element-missing）', async () => {
    const state = makeState();
    let resolveGenerate!: (v: unknown) => void;
    const genPromise = new Promise<unknown>((res) => { resolveGenerate = res; });
    mockOutlineApi(state, { generate: () => genPromise });
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    await user.click(screen.getByTestId('library-ai-generate'));
    const dialog = await screen.findByTestId('outline-generate-dialog');
    await user.type(within(dialog).getByTestId('outline-generate-name'), '插树顶卷');
    await user.click(within(dialog).getByTestId('outline-generate-submit'));
    await act(async () => {
      resolveGenerate({
        saved: true,
        outline: { ...o1, id: 'o4', name: '插树顶卷', sort_order: 0 },
        plot_points: [], arcs: [], warnings: [], model: 'test',
      });
      await genPromise;
    });
    // 树顶 = O4（asc 下 sort_order 0 最小 / 本地 prepend）
    await waitFor(() => {
      const roots = screen.getAllByTestId(/^outline-overall-/).map((el) => el.getAttribute('data-testid'));
      expect(roots[0]).toBe('outline-overall-o4');
    });
    // 共存：排序 toggle 不因生成移除（RED element-missing）
    expect(screen.getByTestId('outline-sort-asc')).toBeInTheDocument();
  });

  it('P6 非 outline tab 回归护栏：切「角色」tab → 拉取 characters（无 level query），无 /outlines? 调用', async () => {
    mockOutlineApi(makeState());
    renderLibrary();
    const user = userEvent.setup();
    // 默认角色 tab（不进大纲）→ 只拉 characters
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/projects/p1/characters')).toBe(true);
    });
    // 明确切到角色 tab（从大纲场景外回归）
    await user.click(screen.getByRole('tab', { name: '角色' }));
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/projects/p1/characters')).toBe(true);
    });
    // 无任何 `/outlines?` 调用（三路拉取仅在 outline tab）
    expect(apiFetchMock.mock.calls.some((c) => typeof c[0] === 'string' && (c[0] as string).includes('/api/v1/projects/p1/outlines?'))).toBe(false);
  });

  it('P7 失败兜底：overall 拉取 reject → err toast，不白屏', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/characters') return { items: [{ id: 'x1', name: '林晚' }], total: 1, offset: 0, limit: 50 };
      // overall 拉取失败（覆盖 no-query（RED 旧行为）与 level=overall query（GREEN 新消费））
      if (typeof path === 'string' && path.startsWith('/api/v1/projects/p1/outlines')) {
        throw new Error('大纲加载失败');
      }
      return emptyRes;
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '大纲' }));
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
    });
    // 不白屏：页面根仍渲染
    expect(screen.getByTestId('library-page')).toBeInTheDocument();
  });
});

describe('OutlineTree 纯组件契约（#1002 排序/分页受控 props）', () => {
  /** 最小 harness：必传既有 props + 新受控 props（sortDesc/onSortChange/total/page/onPageChange），
   *  cast 到 OutlineTreeProps 绕过当前接口未含新 props 的类型检查（实现期自会加入）。 */
  function renderTree(overrides: Record<string, unknown> & { outlines: OutlineItemDTO[] }) {
    const base: OutlineTreeProps = {
      outlines: overrides.outlines,
      chapterTitles: {},
      onEdit: () => {},
      onDelete: () => {},
      onAdd: () => {},
      onOutlineGenerated: () => {},
      projectId: 'p1',
    };
    const props = { ...base, ...overrides } as unknown as OutlineTreeProps;
    return render(<OutlineTree {...props} />);
  }

  const onSortChange = vi.fn();

  beforeEach(() => {
    onSortChange.mockClear();
    mockOutlineApi(makeState());
  });

  it('C1 无分页 props（total<=10）不渲染分页条；排序 toggle 恒渲染（两 testid）', async () => {
    renderTree({ outlines: [o1, o2, o3] });
    // 分页条不渲染（守卫生效；RED 下本就无分页 → 通过）
    expect(screen.queryByTestId('outline-page-prev')).not.toBeInTheDocument();
    // 排序 toggle 恒渲染（RED element-missing）
    expect(screen.getByTestId('outline-sort-asc')).toBeInTheDocument();
    expect(screen.getByTestId('outline-sort-desc')).toBeInTheDocument();
  });

  it('C2 受控：sortDesc=true → desc aria-pressed=true；点 asc → onSortChange(false) 恰一次', async () => {
    renderTree({ outlines: [o1, o2, o3], sortDesc: true, onSortChange });
    // RED：toggle 不存在 → element-missing FAIL
    expect(screen.getByTestId('outline-sort-desc')).toHaveAttribute('aria-pressed', 'true');
    const user = userEvent.setup();
    await user.click(screen.getByTestId('outline-sort-asc'));
    expect(onSortChange).toHaveBeenCalledTimes(1);
    expect(onSortChange).toHaveBeenCalledWith(false);
  });

  it('C3 buildOutlineTree 兄弟序 = sort_order asc + tie created_at desc（乱序喂 → 渲染断言）', async () => {
    // 乱序喂：O1,O3,O2（含 tie 章乱序），断言树根按 sort_order asc 排序 & v1 章 tie created_at desc
    renderTree({ outlines: [o1, o3, o2, v1, v2, v3, c1b, c1a] });
    const roots = screen.getAllByTestId(/^outline-overall-/).map((el) => el.getAttribute('data-testid'));
    expect(roots).toEqual(['outline-overall-o2', 'outline-overall-o3', 'outline-overall-o1']);
    const v1Node = screen.getByTestId('outline-volume-v1');
    // 精确匹配章行（排除 📎 徽标 outline-chapter-ref-*，父侧契约修正 2026-09-09）
    const chapters = within(v1Node)
      .getAllByTestId(/^outline-chapter-c\d[a-b]$/)
      .map((el) => el.getAttribute('data-testid'));
    expect(chapters).toEqual(['outline-chapter-c1a', 'outline-chapter-c1b']);
  });

  it('C4 total=11/page=0 → info 第 1 / 2 页 · 共 11 条（zh）；prev disabled', async () => {
    renderTree({ outlines: [o1, o2, o3], total: 11, page: 0, onPageChange: () => {} });
    // RED：分页条不存在 → element-missing FAIL
    const info = screen.getByTestId('outline-page-info');
    expect(info.textContent).toBe('第 1 / 2 页 · 共 11 条');
    expect(screen.getByTestId('outline-page-prev')).toBeDisabled();
  });
});
