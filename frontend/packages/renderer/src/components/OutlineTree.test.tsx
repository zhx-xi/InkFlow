/**
 * #675/#676/#677 大纲三段（分级创建 / 关联章节选择器 / 生成刷新+进度）—— GUI 接线契约
 * 覆盖 #675（level/parent 分级创建 + ＋整本/＋卷/＋章细纲 预填）、
 *        #676（handleLinkChapter 打开章节选择弹层 + PATCH chapter_id + 📎 徽标）、
 *        #677（handleGenerate 回填 plot_points/arcs 立即可见 + 生成进度展示）。
 *
 * RED 预期（重写前实现缺失）：
 *   #675 outline-add-overall 不存在、＋卷/＋章细纲 不预填 level/parent → FAIL
 *   #676 点关联章节仅 toast，无 chapter-link-dialog → FAIL
 *   #677 generate 后情节点不入树（pointsByChapter 未回填），生成对话框无 outline-generate-progress → FAIL
 *
 * NOTE：#676 是 F43 §5.15 D9 拍板「后置」的占位——本次解除 D9，实现真实章节选择器。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { LibraryPage } from '../pages/library';
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

const outlineRoot = { id: 'o1', name: '主线规划 v1', level: 'overall', parent_id: null, chapter_id: null, point_count: 0 };
const outlineVol = { id: 'v1', name: '第一卷·宗门试炼', level: 'volume', parent_id: 'o1', chapter_id: null, point_count: 0 };
const outlineChap = { id: 'c1', name: '第一章·废柴觉醒', level: 'chapter', parent_id: 'v1', chapter_id: null, point_count: 2 };

const chapters = [
  { id: 'ch1', title: '第一章 废柴觉醒' },
  { id: 'ch2', title: '第二章 拜师学艺' },
];

const pointA = { id: 'p1', outline_id: 'c1', project_id: 'p1', name: '主角登场', type: '开篇', description: '', position: 1, arc_id: null };
const pointB = { id: 'p2', outline_id: 'c1', project_id: 'p1', name: '金手指觉醒', type: '转折', description: '', position: 2, arc_id: null };

interface State {
  outlines: Array<Record<string, unknown>>;
  points: Array<Record<string, unknown>>;
}

function makeState(): State {
  return { outlines: [outlineRoot, outlineVol, outlineChap], points: [pointA, pointB] };
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

/** 状态化 mock：读端点 + 创建/关联章节/生成；opts.generate 可注入 deferred 控制进行中态 */
function mockOutlineApi(state: State, opts?: { generate?: () => Promise<unknown> }) {
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/outlines' && (!init?.method || init.method === 'GET')) {
      return { items: state.outlines, total: state.outlines.length, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/projects/p1/chapters') return { items: chapters, total: chapters.length, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/maps') return { items: [], total: 0, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/story-arcs') return { items: [], total: 0, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/outlines' && init?.method === 'POST') {
      const body = init.body as Record<string, unknown>;
      const created = { id: `o${state.outlines.length + 1}`, name: body.name, project_id: 'p1', description: body.description ?? '', level: body.level ?? 'overall', parent_id: body.parent_id ?? null, chapter_id: null, point_count: 0 };
      state.outlines = [created, ...state.outlines];
      return created;
    }
    // 情节点列表
    const pointsPath = path.match(/^\/api\/v1\/outlines\/([^/]+)\/plot-points$/);
    if (pointsPath && (!init?.method || init.method === 'GET')) {
      const pts = state.points.filter((p) => String(p.outline_id) === pointsPath[1]);
      return { items: pts, total: pts.length, offset: 0, limit: 50 };
    }
    // 关联章节 PATCH
    const patched = path.match(/^\/api\/v1\/outlines\/([^/]+)$/);
    if (patched && init?.method === 'PATCH') {
      const body = init.body as Record<string, unknown>;
      const idx = state.outlines.findIndex((o) => String(o.id) === patched[1]);
      if (idx >= 0) { state.outlines[idx] = { ...state.outlines[idx], ...body }; return state.outlines[idx]; }
    }
    // AI 生成
    if (path === '/api/v1/outlines/generate' && init?.method === 'POST') {
      if (opts?.generate) return opts.generate();
      const body = init.body as Record<string, unknown>;
      const name = typeof body.name === 'string' ? body.name : '未命名大纲';
      const created = { id: 'o2', name, project_id: 'p1', description: '', level: 'chapter', parent_id: 'o1', chapter_id: null, point_count: 2 };
      state.outlines.unshift(created);
      return { saved: true, outline: created, plot_points: [{ id: 'g1', name: '生成点一', outline_id: 'o2', project_id: 'p1', position: 1, arc_id: null }, { id: 'g2', name: '生成点二', outline_id: 'o2', project_id: 'p1', position: 2, arc_id: null }], arcs: [], warnings: [], model: 'test' };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
  act(() => {
    useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
  });
}

describe('#675 大纲分级创建（＋整本/＋卷/＋章细纲 预填 level+parent）', () => {
  it('T675-1「＋整本」→ 对话框预填 level=overall → POST body {level,parent_id:null}', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    await user.click(screen.getByTestId('outline-add-overall'));
    const dialog = await screen.findByTestId('library-create-dialog');
    expect((within(dialog).getByTestId('library-create-level') as HTMLSelectElement).value).toBe('overall');
    await user.type(within(dialog).getByTestId('library-create-name'), '主线规划');
    await user.click(within(dialog).getByTestId('library-create-save'));
    await waitFor(() => {
      const post = apiFetchMock.mock.calls.find((c) => c[0] === '/api/v1/projects/p1/outlines' && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      const body = post![1]!.body as Record<string, unknown>;
      expect(body.level).toBe('overall');
      expect(body.parent_id).toBeNull();
    });
  });

  it('T675-2「＋卷」→ 对话框预填 level=volume+parent=o1 → POST body {level,parent_id}', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    await user.click(screen.getByTestId('outline-add-volume-o1'));
    const dialog = await screen.findByTestId('library-create-dialog');
    expect((within(dialog).getByTestId('library-create-level') as HTMLSelectElement).value).toBe('volume');
    expect(within(dialog).getByTestId('library-create-name')).toBeInTheDocument();
    await user.type(within(dialog).getByTestId('library-create-name'), '第二卷');
    await user.click(within(dialog).getByTestId('library-create-save'));
    await waitFor(() => {
      const post = apiFetchMock.mock.calls.find((c) => c[0] === '/api/v1/projects/p1/outlines' && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      const body = post![1]!.body as Record<string, unknown>;
      expect(body.level).toBe('volume');
      expect(body.parent_id).toBe('o1');
    });
  });

  it('T675-3「＋章细纲」→ 对话框预填 level=chapter+parent=v1 → POST body {level,parent_id}', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    await user.click(screen.getByTestId('outline-add-chapter-v1'));
    const dialog = await screen.findByTestId('library-create-dialog');
    expect((within(dialog).getByTestId('library-create-level') as HTMLSelectElement).value).toBe('chapter');
    await user.type(within(dialog).getByTestId('library-create-name'), '第二章');
    await user.click(within(dialog).getByTestId('library-create-save'));
    await waitFor(() => {
      const post = apiFetchMock.mock.calls.find((c) => c[0] === '/api/v1/projects/p1/outlines' && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      const body = post![1]!.body as Record<string, unknown>;
      expect(body.level).toBe('chapter');
      expect(body.parent_id).toBe('v1');
    });
  });
});

describe('#676 大纲关联章节选择器（解除 D9 占位）', () => {
  it('T676-1 点「关联章节」→ 打开章节选择弹层 → 选中 → PATCH /outlines/c1 {chapter_id} → 树内显示 📎 徽标', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    // 未关联时显示「关联章节」按钮
    await user.click(screen.getByTestId('outline-chapter-link-c1'));
    const dialog = await screen.findByTestId('chapter-link-dialog');
    // 弹层列出章节（数据源 chapterTitles：ch1/ch2）
    expect(within(dialog).getByTestId('chapter-link-option-ch1')).toBeInTheDocument();
    expect(within(dialog).getByTestId('chapter-link-option-ch2')).toBeInTheDocument();
    await user.click(within(dialog).getByTestId('chapter-link-option-ch1'));
    await waitFor(() => {
      const patch = apiFetchMock.mock.calls.find((c) => c[0] === '/api/v1/outlines/c1' && c[1]?.method === 'PATCH');
      expect(patch).toBeTruthy();
      expect((patch![1]!.body as Record<string, unknown>).chapter_id).toBe('ch1');
    });
    // 树内显示 📎 徽标（含章节标题），不再显示「关联章节」按钮
    await waitFor(() => {
      const badge = screen.getByTestId('outline-chapter-ref-c1');
      expect(within(badge).getByText('第一章 废柴觉醒')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('outline-chapter-link-c1')).not.toBeInTheDocument();
  });
});

describe('#677 大纲生成刷新 + 进度', () => {
  it('T677-1 生成后新大纲+情节点立即可见（回填 pointsByChapter，不需切 tab）', async () => {
    const state = makeState();
    let resolveGenerate!: (v: unknown) => void;
    const genPromise = new Promise<unknown>((res) => { resolveGenerate = res; });
    mockOutlineApi(state, { generate: () => genPromise });
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    await user.click(screen.getByTestId('library-ai-generate'));
    const dialog = await screen.findByTestId('outline-generate-dialog');
    await user.type(within(dialog).getByTestId('outline-generate-name'), '第二卷规划');
    await user.click(within(dialog).getByTestId('outline-generate-submit'));
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/outlines/generate' && c[1]?.method === 'POST')).toBe(true);
    });
    await act(async () => {
      resolveGenerate({
        saved: true,
        outline: { id: 'o2', name: '第二卷规划', project_id: 'p1', description: '', level: 'chapter', parent_id: 'o1', chapter_id: null, point_count: 2 },
        plot_points: [
          { id: 'g1', name: '生成点一', outline_id: 'o2', project_id: 'p1', position: 1, arc_id: null },
          { id: 'g2', name: '生成点二', outline_id: 'o2', project_id: 'p1', position: 2, arc_id: null },
        ],
        arcs: [], warnings: [], model: 'test',
      });
      await genPromise;
    });
    // 新大纲出现在树内（无需切 tab）
    await waitFor(() => {
      const tree = screen.getByTestId('outline-tree');
      expect(within(tree).getByText('第二卷规划')).toBeInTheDocument();
    });
    // 情节点立即可见（回填，不需再展开/拉取）
    await waitFor(() => {
      const tree = screen.getByTestId('outline-tree');
      expect(within(tree).getByText('生成点一')).toBeInTheDocument();
      expect(within(tree).getByText('生成点二')).toBeInTheDocument();
    });
  });

  it('T677-2 生成对话框有进度展示（阶段 + 已生成条目数）', async () => {
    const state = makeState();
    let resolveGenerate!: (v: unknown) => void;
    const genPromise = new Promise<unknown>((res) => { resolveGenerate = res; });
    mockOutlineApi(state, { generate: () => genPromise });
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    await user.click(screen.getByTestId('library-ai-generate'));
    const dialog = await screen.findByTestId('outline-generate-dialog');
    await user.click(within(dialog).getByTestId('outline-generate-submit'));
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/outlines/generate' && c[1]?.method === 'POST')).toBe(true);
    });
    // 生成中：对话框展示进度（阶段 + 已生成条目数）
    const progress = await screen.findByTestId('outline-generate-progress');
    expect(within(progress).getByTestId('outline-generate-stage')).toBeInTheDocument();
    expect(within(progress).getByTestId('outline-generate-count')).toBeInTheDocument();
    // 完成关闭
    await act(async () => {
      resolveGenerate({
        saved: true,
        outline: { id: 'o2', name: '第二卷', project_id: 'p1', description: '', level: 'chapter', parent_id: 'o1', chapter_id: null, point_count: 1 },
        plot_points: [{ id: 'g1', name: '生成点一', outline_id: 'o2', project_id: 'p1', position: 1, arc_id: null }],
        arcs: [], warnings: [], model: 'test',
      });
      await genPromise;
    });
    await waitFor(() => {
      expect(screen.queryByTestId('outline-generate-dialog')).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'ok')).toBe(true);
    });
  });
});
