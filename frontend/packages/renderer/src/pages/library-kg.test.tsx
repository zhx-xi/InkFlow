/**
 * ⚠️ 契约文件（F48 知识图谱 RED 阶段，specs/f48-knowledge-graph/spec.md v1.1 §5.4/§2.4/§3.1/§9）
 *
 * GREEN 改造 src/pages/library.tsx（rag tab → knowledge tab）+ i18n zh/en，必须匹配以下契约：
 *
 * 【tab 改造（§5.4）】
 * - CATS：key 'rag' → 'knowledge'；labelKey 'nav.lib.rag' → 'nav.lib.knowledge'
 *   （i18n 新 key：nav.lib.knowledge，zh='知识图谱'，en='Knowledge Graph'）
 * - endpoint：'/api/v1/projects/{id}/extractions/runs' → GET '/api/v1/projects/{id}/knowledge-graph'
 *   （响应 = {nodes: GraphNode[], edges: GraphEdge[]}，§2.4：节点 id="<entity_type>:<entity_uuid>"，
 *   边 id="kr:<uuid>"（knowledge_relations）/ "cr:<uuid>"（character_relations））
 * - PATCH/DELETE_ENDPOINTS 继续排除 knowledge（图谱关系编辑走画布/列表内交互，非列表行编辑）
 * - 空态 CTA：knowledge tab 不再 navigate('/writing')，改图谱空态引导（见下）
 *
 * 【图谱视图（knowledge tab 默认视图）】
 * - 画布容器 data-testid="library-kg-canvas"：@xyflow/react 渲染（GREEN 才装依赖）；
 *   节点显示 GraphNode.name、边显示 GraphEdge.label（有向箭头）
 * - 图谱 tab 内工具栏按钮：
 *   - library-kg-new-relation：「新建关系」按钮
 *   - library-kg-view-graph：「图谱视图」切换按钮
 *   - library-kg-view-list：「关系列表」切换按钮
 *
 * 【图谱空态（§5.4/§7 #14）】
 * - graph 返回 {nodes: [], edges: []} → data-testid="library-kg-empty" + 文案
 *   t('lib.knowledge.empty.title')（zh='图谱为空'；i18n 新增 lib.knowledge.* 组）
 * - 空态可含「去角色/世界观等实体页创建」引导链接（GREEN 自定 testid，非本契约面）
 *
 * 【建关系表单（§5.4 工具栏「新建关系」→ 表单；保存成功后关闭/收起）】
 * - 容器 data-testid="library-kg-relation-form"；字段 testid：
 *   - library-kg-form-source-type：起点类型选择（选项=六实体类型显示名：角色/世界观/大纲/时间线/伏笔/地图标记，
 *     选中后显示「角色」）
 *   - library-kg-form-source-entity：起点实体选择（选项=当前所选类型的图谱节点名，如「林尘」）
 *   - library-kg-form-target-type：终点类型选择
 *   - library-kg-form-target-entity：终点实体选择
 *   - library-kg-form-relation-type：关系类型输入（原生 input）
 *   - library-kg-form-description：描述输入
 *   - library-kg-form-save：保存按钮
 * - 提交 → POST '/api/v1/projects/{pid}/knowledge-relations'（§3.1/§3.2），body =
 *   {source_type, source_id, target_type, target_id, relation_type, description}
 *   （source_id/target_id = 实体 UUID = GraphNode.entity_id，非节点 id 字符串）
 * - 成功后局部刷新（重拉 graph 或本地更新——spec §5.4「实现期定」，测试不钉策略）
 *
 * 【关系列表视图（§5.4 列表模式复用 F9 交互）】
 * - 容器 data-testid="library-kg-relation-list"；列表加载 GET '/api/v1/projects/{pid}/knowledge-relations'
 *   （§3.1：{items,total,offset,limit}，只含 knowledge_relations 行，不含 character_relations 行）
 * - 行内按钮：library-kg-rel-edit-<rid>（编辑）/ library-kg-rel-delete-<rid>（删除）
 * - 编辑 → 表单回填现值 → 保存 → PATCH '/api/v1/knowledge-relations/{rid}'（§3.1：六元组可改 + description）
 * - 删除 → DELETE '/api/v1/knowledge-relations/{rid}'（真删，§3.1/§2.1 规则 7）→ 行消失
 *   （二次确认可选：若实现用 library-kg-confirm-dialog + library-kg-confirm-ok）
 *
 * 【数据流】图谱视图加载 GET knowledge-graph（一次 nodes+edges，§5.4）；关系列表视图加载
 * GET knowledge-relations。图谱画布内交互（拖拽/缩放/节点详情抽屉/边详情）属画布组件契约
 * （GREEN 时组件测试覆盖），本文件只锁 tab 装配 + 数据流 + 关系增删改 wire 契约；
 * jsdom 无法验证的拖拽/缩放留 M6 手工验证（§13 M6）。
 *
 * RED 预期：旧实现 rag tab（知识库 RAG）无 '知识图谱' tab → 各用例 element-missing（类 3 契约缺口）；
 * 回归守护用例（既有 tab 仍渲染）为确认型，RED 期 PASS 刻意。
 *
 * ⚠️ 本文件禁 import 任何 GREEN 才建模块（KnowledgeGraphCanvas 等）——全部经 library.tsx 渲染 +
 * apiFetch mock 断言（同 library-p*.test.tsx 模式）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
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

/** §2.4/§3.2 种子：图谱聚合查询响应（节点 id="<type>:<uuid>"，边 id="kr:<uuid>"） */
const GRAPH_SEED = {
  nodes: [
    { id: 'character:c1', type: 'character', entity_id: 'c1', name: '林尘' },
    { id: 'world:w1', type: 'world', entity_id: 'w1', name: '清河县' },
  ],
  edges: [
    {
      id: 'kr:9', source: 'character:c1', target: 'world:w1',
      label: '属于', description: '林尘的家乡', source_table: 'knowledge_relations',
    },
  ],
};

/** §3.2 种子：关系列表响应行（只含 knowledge_relations 行） */
const RELATION_SEED = [
  {
    id: '9', project_id: 'p1', source_type: 'character', source_id: 'c1',
    target_type: 'world', target_id: 'w1', relation_type: '属于',
    description: '林尘的家乡', source: 'manual',
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z',
  },
];

/** 状态化关系数组（beforeEach 重置；POST 追加 / PATCH 合并 / DELETE 移除，供「刷新后变化」断言） */
let relations: Array<Record<string, unknown>> = [];

function renderLibrary(initialPath = '/library') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LibraryPage />
    </MemoryRouter>,
  );
}

/** 端点命中断言（宽容单参/双参：契约 = 拉取了该端点，不约束 init 形状） */
function fetchCalled(path: string): boolean {
  return apiFetchMock.mock.calls.some((c) => c[0] === path);
}

/** 下拉/combobox 选择（原生 select 与 Radix 双分支兼容；选项可访问名 = optionText） */
async function selectCombo(
  el: HTMLElement,
  optionText: string,
  user: ReturnType<typeof userEvent.setup>,
) {
  if (el.tagName === 'SELECT') {
    const opt = Array.from(el.querySelectorAll('option')).find(
      (o) => o.textContent?.trim() === optionText,
    );
    await user.selectOptions(el, opt ?? optionText);
  } else {
    await user.click(el);
    await user.click(await screen.findByRole('option', { name: optionText }));
  }
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  relations = RELATION_SEED.map((r) => ({ ...r }));
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    const method = init?.method ?? 'GET';
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/maps') return { items: [] };
    if (path === '/api/v1/projects/p1/knowledge-graph') {
      return {
        nodes: GRAPH_SEED.nodes.map((n) => ({ ...n })),
        edges: GRAPH_SEED.edges.map((e) => ({ ...e })),
      };
    }
    if (path === '/api/v1/projects/p1/knowledge-relations') {
      if (method === 'POST') {
        const created = {
          id: '10', project_id: 'p1', source: 'manual',
          created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-02T10:00:00Z',
          ...((init?.body ?? {}) as Record<string, unknown>),
        };
        relations.unshift(created);
        return created;
      }
      return { items: relations.map((r) => ({ ...r })), total: relations.length, offset: 0, limit: 50 };
    }
    if (path.startsWith('/api/v1/knowledge-relations/')) {
      const rid = path.slice('/api/v1/knowledge-relations/'.length);
      const idx = relations.findIndex((r) => r.id === rid);
      if (method === 'PATCH' && idx >= 0) {
        relations[idx] = { ...relations[idx], ...((init?.body ?? {}) as Record<string, unknown>) };
        return relations[idx];
      }
      if (method === 'DELETE' && idx >= 0) {
        relations.splice(idx, 1);
        return undefined;
      }
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('F48 知识图谱 tab（spec §5.4）', () => {
  it('切到「知识图谱」tab：渲染图谱画布容器 + 触发 GET /knowledge-graph（nodes+edges 种子）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '知识图谱' }));
    expect(await screen.findByTestId('library-kg-canvas')).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/knowledge-graph')).toBe(true);
    });
    // 画布渲染节点名（GraphNode.name）与边标签（GraphEdge.label）
    await waitFor(() => {
      expect(screen.getByTestId('library-kg-canvas')).toHaveTextContent('林尘');
      expect(screen.getByTestId('library-kg-canvas')).toHaveTextContent('属于');
    });
  });

  it('图谱空态：graph 返回空 → library-kg-empty 空态引导（lib.knowledge.empty.title）', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/knowledge-graph') return { nodes: [], edges: [] };
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '知识图谱' }));
    const empty = await screen.findByTestId('library-kg-empty');
    expect(empty).toHaveTextContent('图谱为空');
  });

  it('新建关系：工具栏按钮 → 表单渲染 → 提交 POST /knowledge-relations（六元组+description）→ 列表视图出现新行', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '知识图谱' }));
    await user.click(await screen.findByTestId('library-kg-new-relation'));
    const form = await screen.findByTestId('library-kg-relation-form');
    expect(within(form).getByTestId('library-kg-form-source-type')).toBeInTheDocument();
    expect(within(form).getByTestId('library-kg-form-source-entity')).toBeInTheDocument();
    expect(within(form).getByTestId('library-kg-form-target-type')).toBeInTheDocument();
    expect(within(form).getByTestId('library-kg-form-target-entity')).toBeInTheDocument();
    expect(within(form).getByTestId('library-kg-form-relation-type')).toBeInTheDocument();
    expect(within(form).getByTestId('library-kg-form-description')).toBeInTheDocument();

    await selectCombo(within(form).getByTestId('library-kg-form-source-type'), '角色', user);
    await selectCombo(within(form).getByTestId('library-kg-form-source-entity'), '林尘', user);
    await selectCombo(within(form).getByTestId('library-kg-form-target-type'), '世界观', user);
    await selectCombo(within(form).getByTestId('library-kg-form-target-entity'), '清河县', user);
    fireEvent.change(within(form).getByTestId('library-kg-form-relation-type'), {
      target: { value: '出身' },
    });
    fireEvent.change(within(form).getByTestId('library-kg-form-description'), {
      target: { value: '林尘的故乡' },
    });
    await user.click(within(form).getByTestId('library-kg-form-save'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/knowledge-relations' && c[1]?.method === 'POST',
      );
      expect(call).toBeTruthy();
    });
    const postCall = apiFetchMock.mock.calls.find(
      (c) => c[0] === '/api/v1/projects/p1/knowledge-relations' && c[1]?.method === 'POST',
    )!;
    // §3.2：body = 六元组 + description（source_id/target_id = 实体 UUID）
    expect(postCall[1]?.body).toEqual(
      expect.objectContaining({
        source_type: 'character',
        source_id: 'c1',
        target_type: 'world',
        target_id: 'w1',
        relation_type: '出身',
        description: '林尘的故乡',
      }),
    );

    // 成功后局部刷新（重拉 graph 或本地更新，spec §5.4 实现期定）→ 列表视图可见新行
    await user.click(await screen.findByTestId('library-kg-view-list'));
    await waitFor(() => {
      expect(screen.getByTestId('library-kg-relation-list')).toHaveTextContent('出身');
    });
  });

  it('图谱视图/关系列表切换：列表模式渲染关系行（label/source/target 可读）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '知识图谱' }));
    expect(await screen.findByTestId('library-kg-canvas')).toBeInTheDocument();
    expect(screen.getByTestId('library-kg-view-graph')).toBeInTheDocument();

    await user.click(screen.getByTestId('library-kg-view-list'));
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/knowledge-relations')).toBe(true);
    });
    const list = await screen.findByTestId('library-kg-relation-list');
    expect(within(list).getByText('属于')).toBeInTheDocument();
    expect(within(list).getByText('林尘')).toBeInTheDocument();
    expect(within(list).getByText('清河县')).toBeInTheDocument();

    await user.click(screen.getByTestId('library-kg-view-graph'));
    expect(await screen.findByTestId('library-kg-canvas')).toBeInTheDocument();
  });

  it('关系列表删除：点删除 → DELETE /knowledge-relations/{rid} → 行消失（状态化 mock）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '知识图谱' }));
    await user.click(await screen.findByTestId('library-kg-view-list'));
    const list = await screen.findByTestId('library-kg-relation-list');
    await user.click(within(list).getByTestId('library-kg-rel-delete-9'));

    // 二次确认可选（真删语义；若实现：library-kg-confirm-dialog + library-kg-confirm-ok）
    const confirm = await screen.findByTestId('library-kg-confirm-dialog').catch(() => null);
    if (confirm) {
      await user.click(within(confirm).getByTestId('library-kg-confirm-ok'));
    }
    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/knowledge-relations/9' && c[1]?.method === 'DELETE',
      );
      expect(call).toBeTruthy();
    });
    await waitFor(() => {
      expect(within(list).queryByText('属于')).not.toBeInTheDocument();
    });
  });

  it('关系列表编辑：点编辑 → 表单回填 → PATCH /knowledge-relations/{rid} → 行更新', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '知识图谱' }));
    await user.click(await screen.findByTestId('library-kg-view-list'));
    const list = await screen.findByTestId('library-kg-relation-list');
    await user.click(within(list).getByTestId('library-kg-rel-edit-9'));

    // 表单回填现值（编辑契约：关系类型输入框 = 属于）
    const form = await screen.findByTestId('library-kg-relation-form');
    const relInput = within(form).getByTestId('library-kg-form-relation-type') as HTMLInputElement;
    expect(relInput.value).toBe('属于');
    fireEvent.change(relInput, { target: { value: '出身' } });
    await user.click(within(form).getByTestId('library-kg-form-save'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/knowledge-relations/9' && c[1]?.method === 'PATCH',
      );
      expect(call).toBeTruthy();
    });
    const patchCall = apiFetchMock.mock.calls.find(
      (c) => c[0] === '/api/v1/knowledge-relations/9' && c[1]?.method === 'PATCH',
    )!;
    // §3.1：PATCH 全可选（六元组可改 + description）
    expect(patchCall[1]?.body).toEqual(expect.objectContaining({ relation_type: '出身' }));
    // 刷新后更新（状态化 mock PATCH 合并回写 → 重拉/本地更新均显示新值）
    await waitFor(() => {
      expect(within(list).getByText(/出身/)).toBeInTheDocument();
    });
  });

  it('回归守护：既有分类 tab（角色等）仍渲染 + 六 tab 总数不变（确认型，RED 期 PASS 刻意）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    renderLibrary();

    const tabs = screen.getByTestId('library-tabs');
    expect(within(tabs).getAllByRole('tab')).toHaveLength(6);
    for (const name of ['角色', '世界观', '大纲', '时间线', '伏笔']) {
      expect(within(tabs).getByRole('tab', { name })).toBeInTheDocument();
    }
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/characters')).toBe(true);
    });
  });

  it('i18n：en 语言下知识图谱 tab 文案 = Knowledge Graph（nav.lib.knowledge en 值）', async () => {
    useThemeStore.setState({ lang: 'en' });
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: 'Knowledge Graph' }));
    expect(await screen.findByTestId('library-kg-canvas')).toBeInTheDocument();
  });
});
