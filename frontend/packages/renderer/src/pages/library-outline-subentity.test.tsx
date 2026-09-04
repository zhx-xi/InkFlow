/**
 * #649：大纲子项写操作（情节节点 / 故事弧 CRUD + AI 生成）—— GUI 接线契约
 * specs/f11-outline/spec.md §3（18 端点）+ #649 拍板：
 *   - 情节节点/故事弧 = 编辑类子实体（真删，删除弹确认框）
 *   - AI 生成 = A 方案（生成到新大纲，仅新建，无合并语义）+ 手动触发 + 进行中/完成/失败反馈
 *   - 本轨不触碰「卷纲」(level=volume 是卷纲展示，仍只读)；「＋情节点」在章行、故事弧区/生成按钮在库顶工具栏
 *
 * ⚠️ 本批契约独立文件 library-outline-subentity.test.tsx（library.test.tsx 已近 900 行护栏）。
 *
 * ==================== GREEN 契约（mock apiFetch） ====================
 *
 * 【testid 清单】
 * 工具栏：library-ai-generate（AI 生成大纲按钮）/ outline-generate-loading（进行中反馈元素）
 * AI 生成对话框：outline-generate-dialog / outline-generate-name / outline-generate-prompt / outline-generate-submit / outline-generate-cancel
 * 情节节点对话框：outline-point-dialog / outline-point-name / outline-point-type / outline-point-desc / outline-point-arc / outline-point-save / outline-point-cancel
 * 情节节点删除确认：outline-point-confirm-dialog / outline-point-confirm-ok / outline-point-confirm-cancel
 * 故事弧区：outline-arcs / outline-arc-create
 * 故事弧行：outline-arc-<arcId>（含名称文本）/ outline-arc-count-<arcId> / outline-arc-edit-<arcId> / outline-arc-del-<arcId>
 * 故事弧对话框：outline-arc-dialog / outline-arc-name / outline-arc-desc / outline-arc-save / outline-arc-cancel
 * 故事弧删除确认：outline-arc-confirm-dialog / outline-arc-confirm-ok / outline-arc-confirm-cancel
 * 树既有：outline-tree / outline-add-point-<outlineId> / outline-point-edit-<pointId> / outline-point-del-<pointId> / outline-point-<pointId>
 *
 * 【端点 + body 形状】
 * POST   /api/v1/outlines/{outline_id}/plot-points   → body { name, type?, description?, position?, arc_id? }
 * PATCH  /api/v1/plot-points/{point_id}              → body 部分更新（仅变化字段，如 { name }）
 * DELETE /api/v1/plot-points/{point_id}              → 204（真删）
 * POST   /api/v1/projects/{project_id}/story-arcs    → body { name, description? }
 * PATCH  /api/v1/story-arcs/{arc_id}                 → body 部分更新（如 { name }）
 * DELETE /api/v1/story-arcs/{arc_id}                 → 204（真删，成员 arc_id 置 NULL）
 * POST   /api/v1/outlines/generate                   → body { project_id, name?, prompt?, num_chapters?, save: true }
 *   → 响应 OutlineGenerationResult { saved, outline, plot_points, arcs, warnings, model }
 * GET    /api/v1/projects/{pid}/story-arcs           → { items: [StoryArc], total }
 *
 * 【交互契约（GREEN 必守）】
 * - 情节节点创建：章行「＋情节点」→ 打开情节节点对话框（名称必填 gate）→ 保存 → POST 到该章 outline_id → 成功刷新该章情节点（新点出现在树内）
 * - 情节节点编辑：行内「✎」→ 对话框预填现值 → 改字段 → 保存 → PATCH /plot-points/{id} → 行内文本更新
 * - 情节节点删除：行内「🗑」→ 确认框（消息含情节点名）→ 确认(ok) → DELETE /plot-points/{id} → 行消失（刷新闭环）
 * - 故事弧创建：故事弧区「＋新建故事弧」→ 对话框（名称必填）→ 保存 → POST /projects/{pid}/story-arcs → 新弧出现在区列表
 * - 故事弧编辑：弧行「✎」→ 预填 → 改 → 保存 → PATCH /story-arcs/{id} → 行文本更新
 * - 故事弧删除：弧行「🗑」→ 确认框 → DELETE /story-arcs/{id} → 行消失
 * - AI 生成：工具栏「AI 生成大纲」→ 对话框（名称/prompt 可选）→ 保存 → POST /outlines/generate body {project_id, name?, save:true}
 *   → 生成中：outline-generate-loading 出现（按钮禁用/转圈反馈）
 *   → 完成：toast ok「大纲已生成」+ 新大纲出现在树顶部（生成后刷新 outlines）
 *   → 失败：toast err（展示后端 detail）
 *
 * RED 预期：outline-point-dialog / outline-arcs / outline-arc-&lt;id&gt; / library-ai-generate / outline-generate-&lt;field&gt; 全部不存在 →
 * element-missing 断言 FAIL；POST/PATCH/DELETE body 断言因无调用 FAIL；整个文件 collection 通过（组件已存在）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
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
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

// 大纲三级（overall → volume → chapter）；情节点挂在 chapter（c1）
const outlineRoot = { id: 'o1', name: '主线规划 v1', level: 'overall', parent_id: null, chapter_id: null, point_count: 0 };
const outlineVol = { id: 'v1', name: '第一卷·宗门试炼', level: 'volume', parent_id: 'o1', chapter_id: null, point_count: 2 };
const outlineChap = { id: 'c1', name: '第一章·废柴觉醒', level: 'chapter', parent_id: 'v1', chapter_id: null, point_count: 2 };
const outlineChap2 = { id: 'c2', name: '第二章·宗门大比', level: 'chapter', parent_id: 'v1', chapter_id: null, point_count: 1 };

function makePoint(id: string, name: string, type = '', position = 1, arc_id: string | null = null, outline_id = 'c1') {
  return { id, outline_id, project_id: 'p1', name, type, description: '', position, arc_id };
}
const pointA = makePoint('p1', '主角登场', '开篇', 1);
const pointB = makePoint('p2', '金手指觉醒', '转折', 2, 'a1'); // #928：弧 a1 的真实成员（outline_id 默认 c1）
const pointC = makePoint('p3', '一鸣惊人', '高潮', 1, null, 'c2'); // #928：挂 c2 章的独立情节点

const arc1 = { id: 'a1', project_id: 'p1', name: '主角成长线', description: '', point_count: 3 };
const arc2 = { id: 'a2', project_id: 'p1', name: '反派线', description: '', point_count: 1 };

/** 可变状态（新增/编辑/删除后回写，模拟后端持久化） */
interface State {
  outlines: Array<Record<string, unknown>>;
  points: Array<Record<string, unknown>>;
  arcs: Array<Record<string, unknown>>;
}

function makeState(): State {
  return {
    outlines: [outlineRoot, outlineVol, outlineChap, outlineChap2],
    points: [pointA, pointB, pointC],
    arcs: [arc1, arc2],
  };
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

/** 状态化 mock：读端点 + CRUD 写入 state；生成端点可注入 deferred 控制进行中态 */
function mockOutlineApi(state: State, opts?: { generate?: () => Promise<unknown> }) {
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    if (path === '/api/v1/projects') {
      return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/projects/p1/outlines' && (!init?.method || init.method === 'GET')) {
      return { items: state.outlines, total: state.outlines.length, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/projects/p1/chapters') return { items: [], total: 0, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/maps') return { items: [], total: 0, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/story-arcs' && (!init?.method || init.method === 'GET')) {
      return { items: state.arcs, total: state.arcs.length, offset: 0, limit: 50 };
    }
    // 情节点列表
    const pointsPath = path.match(/^\/api\/v1\/outlines\/([^/]+)\/plot-points$/);
    if (pointsPath && (!init?.method || init.method === 'GET')) {
      const pts = state.points.filter((p) => String(p.outline_id) === pointsPath[1]);
      return { items: pts, total: pts.length, offset: 0, limit: 50 };
    }
    const pointPost = path.match(/^\/api\/v1\/outlines\/([^/]+)\/plot-points$/);
    if (pointPost && init?.method === 'POST') {
      const body = init.body as Record<string, unknown>;
      const created = { id: `p${state.points.length + 1}`, outline_id: pointPost[1], project_id: 'p1', type: '', description: '', position: state.points.length + 1, arc_id: null, ...body };
      state.points.push(created);
      return created;
    }
    const pointPatched = path.match(/^\/api\/v1\/plot-points\/([^/]+)$/);
    if (pointPatched && init?.method === 'PATCH') {
      const idx = state.points.findIndex((p) => String(p.id) === pointPatched[1]);
      if (idx >= 0) { state.points[idx] = { ...state.points[idx], ...(init.body as Record<string, unknown>) }; return state.points[idx]; }
    }
    if (pointPatched && init?.method === 'DELETE') {
      state.points = state.points.filter((p) => String(p.id) !== pointPatched[1]);
      return undefined;
    }
    // 故事弧 CRUD
    const arcPost = /^\/api\/v1\/projects\/p1\/story-arcs$/.test(path);
    if (arcPost && init?.method === 'POST') {
      const body = init.body as Record<string, unknown>;
      const created = { id: `a${state.arcs.length + 1}`, project_id: 'p1', description: '', point_count: 0, ...body };
      state.arcs.push(created);
      return created;
    }
    const arcPatched = path.match(/^\/api\/v1\/story-arcs\/([^/]+)$/);
    // #928：GET 弧详情 → { ...arc, points: [...] }（按 arc_id 过滤 + 映射 outline_name），
    //   与下方 PATCH/DELETE 分支互不冲突（此分支只响应 GET/无 method）
    if (arcPatched && (!init?.method || init.method === 'GET')) {
      const idx = state.arcs.findIndex((a) => String(a.id) === arcPatched[1]);
      if (idx >= 0) {
        const arc = state.arcs[idx];
        const points = state.points
          .filter((p) => String(p.arc_id) === arcPatched[1])
          .map((p) => {
            const outline = state.outlines.find((o) => String(o.id) === String(p.outline_id));
            return { ...p, outline_name: outline ? String(outline.name) : '' };
          });
        return { ...arc, points };
      }
    }
    if (arcPatched && init?.method === 'PATCH') {
      const idx = state.arcs.findIndex((a) => String(a.id) === arcPatched[1]);
      if (idx >= 0) { state.arcs[idx] = { ...state.arcs[idx], ...(init.body as Record<string, unknown>) }; return state.arcs[idx]; }
    }
    if (arcPatched && init?.method === 'DELETE') {
      state.arcs = state.arcs.filter((a) => String(a.id) !== arcPatched[1]);
      return undefined;
    }
    // AI 生成
    if (path === '/api/v1/outlines/generate' && init?.method === 'POST') {
      if (opts?.generate) return opts.generate();
      const body = init.body as Record<string, unknown>;
      const name = typeof body.name === 'string' ? body.name : '未命名大纲';
      const created = { id: 'o2', name, project_id: 'p1', description: '', level: 'overall', parent_id: null, chapter_id: null, point_count: 0 };
      state.outlines.unshift(created);
      return { saved: true, outline: created, plot_points: [], arcs: [], warnings: [], model: 'test' };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
  act(() => {
    useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
  });
}

describe('#649 大纲子项写操作（情节节点/故事弧 CRUD + AI 生成）', () => {

  it('T1 情节节点创建：章行「＋情节点」→ 对话框 → 保存 → POST /outlines/c1/plot-points → 新点出现', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    // 锚定既有按钮（章行「＋情节点」）
    await user.click(screen.getByTestId('outline-add-point-c1'));
    // 对话框（当前实现不存在 → RED 在 findByTestId 失败）
    const dialog = await screen.findByTestId('outline-point-dialog');
    await user.type(within(dialog).getByTestId('outline-point-name'), '拜师立誓');
    await user.click(within(dialog).getByTestId('outline-point-save'));
    await waitFor(() => {
      const post = apiFetchMock.mock.calls.find((c) => c[0] === '/api/v1/outlines/c1/plot-points' && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      const body = post![1]!.body as Record<string, unknown>;
      expect(body.name).toBe('拜师立誓');
    });
    // 成功刷新：新点出现在树内
    await waitFor(() => {
      const tree = screen.getByTestId('outline-tree');
      expect(within(tree).getByText('拜师立誓')).toBeInTheDocument();
    });
  });

  it('T2 情节节点编辑：行内「✎」→ 预填 → 改名称 → 保存 → PATCH /plot-points/p1 → 行更新', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    await user.click(screen.getByTestId('outline-point-edit-p1'));
    const dialog = await screen.findByTestId('outline-point-dialog');
    const nameInput = within(dialog).getByTestId('outline-point-name');
    // 编辑模式预填现值
    expect((nameInput as HTMLInputElement).value).toBe('主角登场');
    await user.clear(nameInput);
    await user.type(nameInput, '主角入场');
    await user.click(within(dialog).getByTestId('outline-point-save'));
    await waitFor(() => {
      const patch = apiFetchMock.mock.calls.find((c) => c[0] === '/api/v1/plot-points/p1' && c[1]?.method === 'PATCH');
      expect(patch).toBeTruthy();
      // #649 保存契约：PATCH body 只含变化字段（只改了名称；type/description/arc_id 未变不进 body）
      const body = patch![1]!.body as Record<string, unknown>;
      expect(body.name).toBe('主角入场');
      expect(Object.keys(body)).toEqual(['name']);
    });
    await waitFor(() => {
      const tree = screen.getByTestId('outline-tree');
      expect(within(tree).getByText('主角入场')).toBeInTheDocument();
    });
  });

  it('T2b 全字段未变直接保存 → 零 PATCH 请求（仅变化字段才发 PATCH，空 body 不发）', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    await user.click(screen.getByTestId('outline-point-edit-p1'));
    const dialog = await screen.findByTestId('outline-point-dialog');
    // 不改任何字段直接保存（名称预填非空 → 保存按钮可用）
    await user.click(within(dialog).getByTestId('outline-point-save'));
    // 保存流程走完（对话框关闭 + 刷新）
    await waitFor(() => {
      expect(screen.queryByTestId('outline-point-dialog')).not.toBeInTheDocument();
    });
    // 全字段未变 → 零 PATCH 请求（OutlineTree handlePointSave 空 body 不发）
    expect(apiFetchMock.mock.calls.some((c) => c[1]?.method === 'PATCH')).toBe(false);
  });

  it('T3 情节节点删除：行内「🗑」→ 确认框（含名称）→ 确认 → DELETE /plot-points/p1 → 行消失', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    await user.click(screen.getByTestId('outline-point-del-p1'));
    const confirm = await screen.findByTestId('outline-point-confirm-dialog');
    // 确认框消息含情节点名
    expect(within(confirm).getByText(/主角登场/)).toBeInTheDocument();
    await user.click(within(confirm).getByTestId('outline-point-confirm-ok'));
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/plot-points/p1' && c[1]?.method === 'DELETE')).toBe(true);
    });
    // 刷新闭环：行消失
    await waitFor(() => {
      const tree = screen.getByTestId('outline-tree');
      expect(within(tree).queryByText('主角登场')).not.toBeInTheDocument();
    });
  });

  it('T4 故事弧创建：故事弧区「＋新建故事弧」→ 对话框 → 保存 → POST /projects/p1/story-arcs → 新弧出现', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    const arcs = await screen.findByTestId('outline-arcs');
    await user.click(within(arcs).getByTestId('outline-arc-create'));
    const dialog = await screen.findByTestId('outline-arc-dialog');
    await user.type(within(dialog).getByTestId('outline-arc-name'), '权谋线');
    await user.click(within(dialog).getByTestId('outline-arc-save'));
    await waitFor(() => {
      const post = apiFetchMock.mock.calls.find((c) => c[0] === '/api/v1/projects/p1/story-arcs' && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect((post![1]!.body as Record<string, unknown>).name).toBe('权谋线');
    });
    await waitFor(() => {
      expect(screen.getByText('权谋线')).toBeInTheDocument();
    });
  });

  it('T5 故事弧编辑：弧行「✎」→ 预填 → 改 → 保存 → PATCH /story-arcs/a1 → 更新', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    const arcs = await screen.findByTestId('outline-arcs');
    await user.click(within(arcs).getByTestId('outline-arc-edit-a1'));
    const dialog = await screen.findByTestId('outline-arc-dialog');
    const nameInput = within(dialog).getByTestId('outline-arc-name');
    expect((nameInput as HTMLInputElement).value).toBe('主角成长线');
    await user.clear(nameInput);
    await user.type(nameInput, '主角蜕变线');
    await user.click(within(dialog).getByTestId('outline-arc-save'));
    await waitFor(() => {
      const patch = apiFetchMock.mock.calls.find((c) => c[0] === '/api/v1/story-arcs/a1' && c[1]?.method === 'PATCH');
      expect(patch).toBeTruthy();
      // #649 保存契约：PATCH body 只含变化字段（description 未变不进 body）
      const body = patch![1]!.body as Record<string, unknown>;
      expect(body.name).toBe('主角蜕变线');
      expect(Object.keys(body)).toEqual(['name']);
    });
    await waitFor(() => {
      expect(screen.getByText('主角蜕变线')).toBeInTheDocument();
    });
  });

  it('T6 故事弧删除：弧行「🗑」→ 确认 → DELETE /story-arcs/a1 → 行消失', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    const arcs = await screen.findByTestId('outline-arcs');
    await user.click(within(arcs).getByTestId('outline-arc-del-a1'));
    const confirm = await screen.findByTestId('outline-arc-confirm-dialog');
    expect(within(confirm).getByText(/主角成长线/)).toBeInTheDocument();
    await user.click(within(confirm).getByTestId('outline-arc-confirm-ok'));
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/story-arcs/a1' && c[1]?.method === 'DELETE')).toBe(true);
    });
    await waitFor(() => {
      expect(screen.queryByText('主角成长线')).not.toBeInTheDocument();
    });
  });

  it('T7 AI 生成：工具栏按钮 → 对话框 → 保存 → POST /outlines/generate {project_id,save:true} → 进行中 → 完成 toast + 新大纲出现', async () => {
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
    // 进行中反馈（POST pending）
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/outlines/generate' && c[1]?.method === 'POST')).toBe(true);
    });
    expect(await screen.findByTestId('outline-generate-loading')).toBeInTheDocument();
    // 完成：resolve → toast ok + 新大纲出现在树顶部
    await act(async () => {
      resolveGenerate({
        saved: true,
        outline: { ...outlineRoot, id: 'o2', name: '第二卷规划' },
        plot_points: [], arcs: [], warnings: [], model: 'test',
      });
      await genPromise;
    });
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/outlines/generate' && c[1]?.method === 'POST')).toBe(true);
      const gen = apiFetchMock.mock.calls.find((c) => c[0] === '/api/v1/outlines/generate');
      const body = gen![1]!.body as Record<string, unknown>;
      expect(body.project_id).toBe('p1');
      expect(body.save).toBe(true);
      expect(body.name).toBe('第二卷规划');
    });
    // 完成 toast
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'ok')).toBe(true);
    });
    // 新大纲出现在树顶部（generate 后 reload outlines）
    await waitFor(() => {
      const tree = screen.getByTestId('outline-tree');
      expect(within(tree).getByText('第二卷规划')).toBeInTheDocument();
    });
  });

  it('T8 AI 生成失败：genPromise reject → toast err（展示 detail）', async () => {
    const state = makeState();
    mockOutlineApi(state, {
      generate: () => Promise.reject(new Error('大纲生成失败: LLM 输出无法解析，请重试')),
    });
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    await user.click(screen.getByTestId('library-ai-generate'));
    const dialog = await screen.findByTestId('outline-generate-dialog');
    await user.click(within(dialog).getByTestId('outline-generate-submit'));
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
    });
  });
});

describe('#928 ArcDialog 章节关联（多选+标签）', () => {
  it('N1 打开既有弧展示关联标签：outline-arc-chapters + chip-p2 + GET /story-arcs/a1', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    // 锚定既有对话框（当前实现存在 → 通过；RED 锚点在下方新元素）
    const arcs = await screen.findByTestId('outline-arcs');
    await user.click(within(arcs).getByTestId('outline-arc-edit-a1'));
    const dialog = await screen.findByTestId('outline-arc-dialog');
    // RED：outline-arc-chapters 缺失 → element-missing（GREEN 后展示弧成员 chips）
    const chapters = within(dialog).getByTestId('outline-arc-chapters');
    // i18n：关联区标题文案含「章节」（t('lib.arcs.chapters') 新 key 中文值）
    expect(chapters.textContent).toMatch(/章节/);
    // a1 的真实成员 p2「金手指觉醒」以 chip 呈现
    const chipP2 = within(chapters).getByTestId('outline-arc-chip-p2');
    expect(chipP2.textContent).toContain('金手指觉醒');
    // 打开弧详情须以 GET（无 PATCH/DELETE）拉取 /api/v1/story-arcs/a1
    await waitFor(() => {
      const getArc = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/story-arcs/a1' && (!c[1]?.method || c[1].method === 'GET'),
      );
      expect(getArc).toBeTruthy();
    });
  });

  it('N2 移除标签保存 → PATCH /plot-points/p2 {arc_id:""} 清除归属，且不发 /story-arcs/a1 PATCH', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    const arcs = await screen.findByTestId('outline-arcs');
    await user.click(within(arcs).getByTestId('outline-arc-edit-a1'));
    const dialog = await screen.findByTestId('outline-arc-dialog');
    // RED：chip 移除按钮不存在 → element-missing（GREEN 后点它移除标签）
    await user.click(within(dialog).getByTestId('outline-arc-chip-remove-p2'));
    // 保存前本地态：chip p2 消失
    expect(within(dialog).queryByTestId('outline-arc-chip-p2')).not.toBeInTheDocument();
    await user.click(within(dialog).getByTestId('outline-arc-save'));
    // 批量契约：PATCH /plot-points/p2 严格 body { arc_id: '' }（#862 清除归属）
    await waitFor(() => {
      const patchPoint = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/plot-points/p2' && c[1]?.method === 'PATCH',
      );
      expect(patchPoint).toBeTruthy();
      expect(patchPoint![1]!.body).toEqual({ arc_id: '' });
    });
    // name/description 未变 → 不发 /api/v1/story-arcs/a1 的 PATCH
    expect(
      apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/story-arcs/a1' && c[1]?.method === 'PATCH'),
    ).toBe(false);
    await waitFor(() => {
      expect(screen.queryByTestId('outline-arc-dialog')).not.toBeInTheDocument();
    });
  });

  it('N3 空弧多选添加两个点保存 → 两条 PATCH 批量挂弧（p1/p3 → {arc_id:"a2"}）', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    const arcs = await screen.findByTestId('outline-arcs');
    await user.click(within(arcs).getByTestId('outline-arc-edit-a2'));
    const dialog = await screen.findByTestId('outline-arc-dialog');
    // RED：空弧关联区为空态 → outline-arc-chapters-empty 缺失 → element-missing
    expect(within(dialog).getByTestId('outline-arc-chapters-empty')).toBeInTheDocument();
    // 展开多选（GREEN 后 outline-arc-add-chapter 存在）
    await user.click(within(dialog).getByTestId('outline-arc-add-chapter'));
    // 勾选 p1 与 p3（GREEN：option testid 挂可点击 checkbox 上，checked 可断言）
    await user.click(within(dialog).getByTestId('outline-arc-option-p1'));
    await user.click(within(dialog).getByTestId('outline-arc-option-p3'));
    // 勾选后 p1 以 chip 呈现
    expect(within(dialog).getByTestId('outline-arc-chip-p1')).toBeInTheDocument();
    await user.click(within(dialog).getByTestId('outline-arc-save'));
    await waitFor(() => {
      const patchP1 = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/plot-points/p1' && c[1]?.method === 'PATCH',
      );
      expect(patchP1).toBeTruthy();
      expect(patchP1![1]!.body).toEqual({ arc_id: 'a2' });
    });
    await waitFor(() => {
      const patchP3 = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/plot-points/p3' && c[1]?.method === 'PATCH',
      );
      expect(patchP3).toBeTruthy();
      expect(patchP3![1]!.body).toEqual({ arc_id: 'a2' });
    });
    await waitFor(() => {
      expect(screen.queryByTestId('outline-arc-dialog')).not.toBeInTheDocument();
    });
  });

  it('N4 新建弧多选保存 → 先 POST /projects/p1/story-arcs 再 PATCH /plot-points/p1 {arc_id:"a3"}', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    const arcs = await screen.findByTestId('outline-arcs');
    await user.click(within(arcs).getByTestId('outline-arc-create'));
    const dialog = await screen.findByTestId('outline-arc-dialog');
    await user.type(within(dialog).getByTestId('outline-arc-name'), '权谋线B');
    // RED：新建弧对话框亦无多选 → outline-arc-add-chapter 缺失 → element-missing
    await user.click(within(dialog).getByTestId('outline-arc-add-chapter'));
    await user.click(within(dialog).getByTestId('outline-arc-option-p1'));
    await user.click(within(dialog).getByTestId('outline-arc-save'));
    // 先建弧再挂点：POST 索引 < PATCH 索引；新弧 created id = a{arcs.length+1} = a3
    await waitFor(() => {
      const postIdx = apiFetchMock.mock.calls.findIndex(
        (c) => c[0] === '/api/v1/projects/p1/story-arcs' && c[1]?.method === 'POST',
      );
      expect(postIdx).toBeGreaterThanOrEqual(0);
      const patchIdx = apiFetchMock.mock.calls.findIndex(
        (c) => c[0] === '/api/v1/plot-points/p1' && c[1]?.method === 'PATCH',
      );
      expect(patchIdx).toBeGreaterThanOrEqual(0);
      expect(postIdx).toBeLessThan(patchIdx);
      const body = apiFetchMock.mock.calls[patchIdx][1]!.body as Record<string, unknown>;
      expect(body).toEqual({ arc_id: 'a3' });
    });
    await waitFor(() => {
      expect(screen.queryByTestId('outline-arc-dialog')).not.toBeInTheDocument();
    });
  });

  it('N5 守护：无关联变更直接保存 → 零 plot-point PATCH、零 story-arc PATCH', async () => {
    const state = makeState();
    mockOutlineApi(state);
    renderLibrary();
    const user = userEvent.setup();
    await enterOutlineTab(user);
    const arcs = await screen.findByTestId('outline-arcs');
    await user.click(within(arcs).getByTestId('outline-arc-edit-a1'));
    const dialog = await screen.findByTestId('outline-arc-dialog');
    // ⚠️ RED 时此用例 FAIL（outline-arc-chapters 缺失）；GREEN 后该断言通过，成为「无变更→零 PATCH」守护
    await within(dialog).findByTestId('outline-arc-chapters');
    // 不改任何东西直接保存
    await user.click(within(dialog).getByTestId('outline-arc-save'));
    await waitFor(() => {
      expect(screen.queryByTestId('outline-arc-dialog')).not.toBeInTheDocument();
    });
    // 零 plot-point PATCH、零 story-arc PATCH
    expect(
      apiFetchMock.mock.calls.some(
        (c) => /^\/api\/v1\/plot-points\//.test(c[0]) && c[1]?.method === 'PATCH',
      ),
    ).toBe(false);
    expect(
      apiFetchMock.mock.calls.some(
        (c) => /^\/api\/v1\/story-arcs\//.test(c[0]) && c[1]?.method === 'PATCH',
      ),
    ).toBe(false);
  });
});
