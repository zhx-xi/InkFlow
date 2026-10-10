/**
 * #1465 知识图谱「筛选语义与布局四改」RED 契约（integration 层：组件交互）
 * 对应 specs/f19-gui/knowledge.md §3 N18 + §2「类别行」/「折叠面板」/「展开筛选」/「一键清除」+ §4.2
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【一句话命题】类别筛选改「默认全选的多选」、实体列表随类别过滤、筛选面板与图视图等高且内滚、
 *              折叠态由「画布下方横条」改为「画布左侧竖条（含明确展开按钮 + 六类圆点）」。
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * 【拍板口径（#1465，2026-10-07；#1529 2026-10 修订）】
 * - 类别：**多选，默认全选**；全选 == 显示全部（负例守护）；取消某类 == 隐藏该类
 * - 实体：**多选**（`entities: string[] | null`，null = 全选）；#1529 起取消类别**不再清空**实体选择
 * - 🔴 筛选信号：节点**永不从 DOM 移除** —— 活跃 = `data-dim="0"` / 变暗 = `data-dim="1"`
 *   （旧「邻接子图 = 该实体 + 一跳邻居」语义已废弃；只保留单个实体被选中 → 仅该实体活跃）
 * - 实体列表：**随类别过滤** + 按 `Intl.Collator('zh')` 排序 + **客户端分页**（页大小 10；本种子单页不渲染分页条）
 * - 高度：筛选面板/折叠竖条 **= 画布高 520px**，列表过长时**内部滚动**
 * - 折叠态：**画布左侧竖状条**（含 `[» 展开筛选]` 明确回入口 + 六类圆点 + `[✕ 清除]`）
 * - 记忆键：`inkflow:kg:filters:<pid>` 值 `{categories, entities}`；旧 `{category, entity}` 读时迁移
 *
 * 【RED 预期】本文件在实现前（旧 src）必须真跑起来并 FAIL（断言失败，非 collection error）：
 *   节点已无 `data-dim` 属性 → 以 data-dim 判活跃/变暗的用例断言失败。
 *
 * ⚠️ jsdom 无布局引擎：几何类断言（真实宽高/等高/左对齐）只能由
 *    `design/GUI/_tools/shot-knowledge-graph-scope.cjs` 在真实浏览器里验证；
 *    本文件用「结构 + class + DOM 顺序」作接近判据（见 §C 注释）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LibraryPage } from './library';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import type { GraphEdge, GraphNode } from '../api/knowledge-graph';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1', name: '项目甲', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

/** 图谱种子：3 角色 + 2 世界观（与 #1373 契约同源，便于横向对照） */
const GRAPH_SEED: { nodes: GraphNode[]; edges: GraphEdge[] } = {
  nodes: [
    { id: 'character:c1', type: 'character', entity_id: 'c1', name: '林尘' },
    { id: 'character:c2', type: 'character', entity_id: 'c2', name: '阿澈' },
    { id: 'character:c3', type: 'character', entity_id: 'c3', name: '白丁' },
    { id: 'world:w1', type: 'world', entity_id: 'w1', name: '清河县' },
    { id: 'world:w2', type: 'world', entity_id: 'w2', name: '断崖' },
  ],
  edges: [
    { id: 'kr:1', source: 'character:c1', target: 'world:w1', label: '属于', description: '', source_table: 'knowledge_relations' },
    { id: 'kr:2', source: 'character:c2', target: 'character:c1', label: '同门', description: '', source_table: 'knowledge_relations' },
    { id: 'kr:3', source: 'world:w2', target: 'world:w1', label: '相邻', description: '', source_table: 'knowledge_relations' },
  ],
};

const CAT_TYPES = ['character', 'world', 'outline', 'timeline', 'foreshadow', 'map_pin'];
const NODE_TESTIDS = GRAPH_SEED.nodes.map((n) => `library-kg-node-${n.type}-${n.entity_id}`);

function renderLibrary() {
  return render(
    <MemoryRouter initialEntries={['/library']}>
      <LibraryPage />
    </MemoryRouter>,
  );
}

async function openGraph(user: ReturnType<typeof userEvent.setup>) {
  act(() => {
    useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
  });
  const result = renderLibrary();
  await user.click(screen.getByRole('tab', { name: '知识图谱' }));
  await screen.findByTestId('library-kg-canvas');
  await waitFor(() => {
    expect(screen.getByTestId('library-kg-node-character-c1')).toBeInTheDocument();
  });
  return result;
}

/** 变暗（dim）节点 testid：全部种子节点**始终在 DOM**，筛选信号是 data-dim="1" */
function dimmedNodeTestIds(): string[] {
  return NODE_TESTIDS.filter((id) => screen.queryByTestId(id)?.getAttribute('data-dim') === '1').sort();
}

/** 活跃（正常着色）节点 testid：data-dim="0"
 *  #1568：须同时 `data-hidden="0"`（实体定向三态下被隐藏的节点虽 data-dim="0"，但不在场） */
function activeNodeTestIds(): string[] {
  return NODE_TESTIDS.filter((id) => {
    const el = screen.queryByTestId(id);
    return el?.getAttribute('data-dim') === '0' && el?.getAttribute('data-hidden') === '0';
  }).sort();
}

/** 某一个类别行的复选框（实现里 testid 直接挂在 input 上；原型里挂在 label 上 → 两者都兼容） */
function catChecked(type: string): boolean {
  const el = screen.getByTestId(`library-kg-filter-panel-cat-${type}`);
  const input = el instanceof HTMLInputElement ? el : el.querySelector('input');
  return input !== null && input.checked;
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/maps') return { items: [] };
    if (path.startsWith('/api/v1/projects/p1/knowledge-graph')) {
      return {
        nodes: GRAPH_SEED.nodes.map((n) => ({ ...n })),
        edges: GRAPH_SEED.edges.map((e) => ({ ...e })),
      };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('#1465-A 类别多选：默认全选（N18①）', () => {
  it('N18① 六类复选框默认全部勾选（视觉上勾满）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    for (const t of CAT_TYPES) {
      expect(catChecked(t), t).toBe(true);
    }
  });

  it('N18① 负例守护：全选 == 显示全部（画布与摘要与改动前一致）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    expect(activeNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    expect(dimmedNodeTestIds()).toEqual([]);
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('显示 5 个实体');
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('全部');
  });

  it('N18① 点某类 = 取消该类（多选非替换）：该类节点变暗，其余保留', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() => {
      expect(activeNodeTestIds()).toEqual(['library-kg-node-world-w1', 'library-kg-node-world-w2']);
    });
    expect(dimmedNodeTestIds()).toEqual([
      'library-kg-node-character-c1',
      'library-kg-node-character-c2',
      'library-kg-node-character-c3',
    ]);
    // 多选：另一类**保持勾选**（不是替换）
    expect(catChecked('world')).toBe(true);
  });
});

describe('#1465-B 实体列表随类别过滤（N18②）', () => {
  it('N18② 取消某类 → 该类节点与实体行双双让位；勾回 → 恢复', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    // 取消「角色」→ 角色节点变暗（仍在 DOM），实体列表也只剩世界观
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() => {
      expect(activeNodeTestIds()).toEqual(['library-kg-node-world-w1', 'library-kg-node-world-w2']);
    });
    expect(dimmedNodeTestIds()).toEqual([
      'library-kg-node-character-c1',
      'library-kg-node-character-c2',
      'library-kg-node-character-c3',
    ]);
    // 实体列表里角色全部让位，只剩世界观
    expect(screen.queryByTestId('library-kg-filter-panel-entity-character-c1')).toBeNull();
    expect(screen.queryByTestId('library-kg-filter-panel-entity-character-c2')).toBeNull();
    expect(screen.getByTestId('library-kg-filter-panel-entity-world-w1')).toBeInTheDocument();
    // 组标题计数 = 过滤后实体数（2）
    expect(screen.getByTestId('library-kg-filter-panel-entity-count')).toHaveTextContent('2');

    // 勾回「角色」→ 恢复
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() => {
      expect(activeNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    });
    expect(screen.getByTestId('library-kg-filter-panel-entity-character-c1')).toBeInTheDocument();
    expect(screen.getByTestId('library-kg-filter-panel-entity-count')).toHaveTextContent('5');
  });

  it('N18② 搜索与类别过滤取交集（搜索只在已勾选类别内收窄）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() =>
      expect(activeNodeTestIds()).toEqual(['library-kg-node-world-w1', 'library-kg-node-world-w2']),
    );

    const search = screen.getByTestId('library-kg-filter-panel-search');
    await user.type(search, '断崖');
    await waitFor(() => {
      expect(screen.getByTestId('library-kg-filter-panel-entity-world-w2')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('library-kg-filter-panel-entity-world-w1')).toBeNull();
  });

  it('N18② 取消已选实体所属类别 → 实体选择被**保留**（#1529）；勾回类别即恢复活跃', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    // 只保留「林尘」被选中：取消其余 4 个实体 → entities = [character:c1]
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c2'));
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c3'));
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-world-w1'));
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-world-w2'));
    await waitFor(() => expect(activeNodeTestIds()).toEqual(['library-kg-node-character-c1']));

    // 取消「角色」类（林尘所属）→ 无活跃节点，但实体选择**不清空**
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() => expect(activeNodeTestIds()).toEqual([]));
    expect(localStorage.getItem('inkflow:kg:filters:p1')).toContain('character:c1');

    // 勾回「角色」→ 记忆里的实体选择被恢复 → 林尘再次活跃
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() => expect(activeNodeTestIds()).toEqual(['library-kg-node-character-c1']));
  });
});

describe('#1465-C 高度对齐 + 内部滚动（N18③）', () => {
  /**
   * ⚠️ jsdom 无布局引擎（getBoundingClientRect 恒 0）→ 这里只能断「结构 + 类」；
   *    真实几何（面板高 == 画布高、顶边对齐、竖条在画布左侧）由
   *    design/GUI/_tools/shot-knowledge-graph-scope.cjs 在真实浏览器断言（railRect/canvasRect）。
   */
  it('N18③ 筛选面板固定高 = 画布高（h-[520px]），实体滚动区独立（overflow-y-auto）', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    const panel = screen.getByTestId('library-kg-filter-panel');
    expect(panel.className).toMatch(/h-\[520px\]/);
    expect(screen.getByTestId('library-kg-canvas').className).toMatch(/h-\[520px\]/);
    // 面板内部有独立的滚动容器（不撑长整页）
    expect(panel.querySelector('.overflow-y-auto')).not.toBeNull();
  });
});

describe('#1465-D 折叠态：画布左侧竖条（N18④）', () => {
  it('N18④ 折叠后竖条在视图左侧（DOM 先于画布）+ 竖排（flex-col）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() => {
      expect(screen.queryByTestId('library-kg-filter-panel')).toBeNull();
      expect(screen.getByTestId('library-kg-filterbar')).toBeInTheDocument();
    });

    const rail = screen.getByTestId('library-kg-filterbar');
    const canvas = screen.getByTestId('library-kg-canvas');
    const pos = rail.compareDocumentPosition(canvas);
    expect(pos & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(rail.className).toMatch(/flex-col/);
  });

  it('N18④ 竖条含明确的「展开筛选」按钮（aria-label）+ 六类圆点 + 清除入口', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() => expect(screen.getByTestId('library-kg-filterbar')).toBeInTheDocument());

    const expand = screen.getByTestId('library-kg-filterbar-expand');
    expect(expand.getAttribute('aria-label')).toBe('展开筛选');
    expect(screen.getByTestId('library-kg-filterbar-clear')).toBeInTheDocument();
    for (const t of CAT_TYPES) {
      expect(screen.getByTestId(`library-kg-rail-dot-${t}`), t).toBeInTheDocument();
    }
  });

  it('N18④ 竖条圆点可切换类别（隐藏类 aria-pressed=false），折叠态筛选保持生效', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() =>
      expect(activeNodeTestIds()).toEqual(['library-kg-node-world-w1', 'library-kg-node-world-w2']),
    );

    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() => expect(screen.getByTestId('library-kg-filterbar')).toBeInTheDocument());
    // 折叠不牺牲筛选结果：角色类变暗，世界观活跃
    expect(dimmedNodeTestIds()).toEqual([
      'library-kg-node-character-c1',
      'library-kg-node-character-c2',
      'library-kg-node-character-c3',
    ]);
    // 隐藏的类别圆点 aria-pressed=false，其余 true
    expect(screen.getByTestId('library-kg-rail-dot-character').getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByTestId('library-kg-rail-dot-world').getAttribute('aria-pressed')).toBe('true');

    // 点圆点勾回角色 → 画布恢复全量（折叠态也能切）
    await user.click(screen.getByTestId('library-kg-rail-dot-character'));
    await waitFor(() => {
      expect(activeNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    });
  });

  it('N18④ 竖条「展开筛选」还原面板 + 勾选态回填', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() => expect(screen.getByTestId('library-kg-filterbar')).toBeInTheDocument());

    await user.click(screen.getByTestId('library-kg-filterbar-expand'));
    await waitFor(() => {
      expect(screen.getByTestId('library-kg-filter-panel')).toBeInTheDocument();
      expect(screen.queryByTestId('library-kg-filterbar')).toBeNull();
    });
    expect(catChecked('character')).toBe(false); // 取消态回填
    expect(catChecked('world')).toBe(true);
  });
});

describe('#1465-E 记忆兼容与前序行为不回归', () => {
  it('N18 记忆写 categories 列表（新格式）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() => {
      const raw = localStorage.getItem('inkflow:kg:filters:p1') ?? '';
      expect(raw).toContain('"categories"');
      expect(raw).not.toContain('"character"');
    });
  });

  it('N18 旧记忆格式（category=character 单选）向后兼容为「只勾该类」', async () => {
    localStorage.setItem('inkflow:kg:filters:p1', JSON.stringify({ category: 'character', entity: null }));
    const user = userEvent.setup();
    await openGraph(user);
    await waitFor(() => {
      expect(activeNodeTestIds()).toEqual([
        'library-kg-node-character-c1',
        'library-kg-node-character-c2',
        'library-kg-node-character-c3',
      ]);
    });
    expect(dimmedNodeTestIds()).toEqual(['library-kg-node-world-w1', 'library-kg-node-world-w2']);
    expect(catChecked('character')).toBe(true);
    expect(catChecked('world')).toBe(false);
  });

  it('N18 旧记忆 category=all → 全选（等价默认）', async () => {
    localStorage.setItem('inkflow:kg:filters:p1', JSON.stringify({ category: 'all', entity: null }));
    const user = userEvent.setup();
    await openGraph(user);
    expect(activeNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    expect(dimmedNodeTestIds()).toEqual([]);
    for (const t of CAT_TYPES) expect(catChecked(t), t).toBe(true);
  });

  it('N10 前序：节点个体着色仍在（内联底色非空，未回归为无样式）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    const el = screen.getByTestId('library-kg-node-character-c1');
    expect(el.getAttribute('style') ?? '').toMatch(/background-color/);
  });

  it('N16 前序：空态不渲染画布 + 空态文案（#1419 不回归）', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path.startsWith('/api/v1/projects/p1/knowledge-graph')) return { nodes: [], edges: [] };
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '知识图谱' }));
    await screen.findByTestId('library-kg-empty');

    expect(screen.queryByTestId('library-kg-canvas')).toBeNull();
    expect(screen.queryByTestId('library-kg-filterbar')).toBeNull();
    expect(screen.getByTestId('library-kg-empty')).toHaveTextContent('图谱为空');
  });
});
