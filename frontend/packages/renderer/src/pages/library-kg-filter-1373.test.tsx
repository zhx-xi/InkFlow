/**
 * #1373 知识图谱「节点个体着色 + 类别/实体筛选」RED 契约（integration 层：组件交互）
 * 对应 specs/f19-gui/knowledge.md §1/§2/§4 + 验收 N10-N15
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【本次要证明的命题（一句话）】
 * 图谱视图出现「左侧筛选面板（可折叠）+ 折叠栏 + 图例」，类别/实体筛选真正作用到画布，
 * 折叠不牺牲画布宽度（面板整块移出 DOM），且选择结果被本地记忆（重挂载后恢复）。
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * 【拍板口径（2026-09-30 起，经 #1465 / #1529 演进）】
 * - 决策① 着色 A（色相分层）→ 画布节点用「类型基准色相 4 档 × 3 明度 = 12 色槽」的个体色（非固定 hex）
 * - 决策② 筛选 B（左侧 224px 面板 + 可折叠；折叠后画布全宽）——非顶部 chip 组
 * - 决策③ 默认 = 全部实体 + 面板展开；选择记忆（记住上次筛选与面板开合）
 * - 决策④ 筛选不作用于关系列表：列表视图/空态不渲染筛选控件
 * - 🔴 #1529 语义：类别 = 多选（默认全选）；实体 = 多选（`entities: string[] | null`，null = 全选）。
 *   节点「活跃」= type ∈ categories 且（entities === null 或 id ∈ entities）；其余**变暗但仍渲染**，
 *   画布**永不**按筛选裁剪节点集 —— 筛选信号是节点上的 `data-dim="1|0"`，不再是「节点从 DOM 消失」。
 *   点实体行 = 取消/勾回该实体（默认全选态下点一次 = 仅它变暗）；旧「邻接子图 = 该实体 + 一跳邻居」
 *   语义已退休（只保留单个实体被选中 → 仅该实体活跃）。
 *
 * 【实现面契约（父侧定稿）】
 * - 纯函数模块：`components/knowledge-graph/kgColor.ts`（TYPE_HUE / hash32 / deriveNodeColor / typeBaseDot）
 *   + `components/knowledge-graph/kgFilter.ts`（DEFAULT_KG_FILTER / computeVisibleIds（返回**活跃**节点集）/
 *   kgFiltersKey / readKgFilter / writeKgFilter / sanitizeKgFilter / readKgPanel / writeKgPanel）
 *   —— 单测见 kgColor.test.ts / kgFilter.test.ts（本文件只证明「接线到 UI」）
 * - 画布节点 testid：`library-kg-node-<type>-<entity_id>`；**始终渲染**，并带 `data-dim="1|0"`；
 *   个体色写在节点与圆点的内联样式上
 * - 筛选面板 testid：`library-kg-filter-panel` · `-search` · `-cat-count` · `-cat-<type>` ·
 *   `-entity-count` · `-entity-<type>-<entity_id>` · `-panel-clear`；折叠 `library-kg-filter-collapse`；
 *   摘要 `library-kg-filter-summary`
 * - 折叠栏 testid：`library-kg-filterbar` · `-summary` · `-clear` · `-expand`
 * - 图例 testid：`library-kg-legend` · `library-kg-legend-<type>`；筛选无结果 `library-kg-filter-empty`
 *   （`!graphEmpty && activeIds.size === 0`）
 * - 实体列表：`Intl.Collator('zh')` 按 name 排序 + **客户端分页**（页大小 10）；本种子 5 节点 →
 *   单页、不渲染分页条
 * - 记忆键：`inkflow:kg:filters:<project_id>`（`{categories, entities}`）+ `inkflow:kg:panel`（'open' | 'closed'）
 *   —— 旧 `{category, entity}` 读时迁移
 *
 * 【RED 预期】本文件在实现前（旧 src）必须真跑起来并 FAIL（断言失败，非 collection error）：
 *   节点尚无 `data-dim` 属性 → 所有以 data-dim 判「活跃/变暗」的用例断言失败。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LibraryPage } from './library';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import type { GraphEdge, GraphNode } from '../api/knowledge-graph';
import { TYPE_HUE, deriveNodeColor } from '../components/knowledge-graph/kgColor';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1', name: '项目甲', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

/** 图谱种子：3 角色 + 2 世界观；c1 的邻接 = {c1, c2（同门）, w1（属于）}(#1529 邻接语义已退休，仅留作种子)
 *  🔴 显式标注 GraphNode/GraphEdge：否则字面量把 type 推成 string，无法喂给强类型的 deriveNodeColor */
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

const NODE_TESTIDS = GRAPH_SEED.nodes.map((n) => `library-kg-node-${n.type}-${n.entity_id}`);

function renderLibrary() {
  return render(
    <MemoryRouter initialEntries={['/library']}>
      <LibraryPage />
    </MemoryRouter>,
  );
}

/** 进入知识图谱 tab 并等画布节点渲染完成（返回 render 结果，供重挂载用例） */
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

/** 变暗（dim）节点的 testid：画布上所有种子节点**始终在 DOM**，筛选信号是 data-dim="1" */
function dimmedNodeTestIds(): string[] {
  return NODE_TESTIDS.filter((id) => screen.queryByTestId(id)?.getAttribute('data-dim') === '1').sort();
}

/** 活跃（正常着色）节点的 testid：data-dim="0"（type ∈ 已选类别 且 实体命中）
 *  #1568：须同时 `data-hidden="0"`（被隐藏节点虽 `data-dim="0"`，但不在场） */
function activeNodeTestIds(): string[] {
  return NODE_TESTIDS.filter((id) => {
    const el = screen.queryByTestId(id);
    return el?.getAttribute('data-dim') === '0' && el?.getAttribute('data-hidden') === '0';
  }).sort();
}

/** 断言画布仍渲染全部种子节点（#1529：筛选只变暗，不移除） */
function expectAllNodesRendered(): void {
  for (const id of NODE_TESTIDS) expect(screen.getByTestId(id), id).toBeInTheDocument();
}

/** 读取元素内联样式里的某个颜色（jsdom 会把颜色归一化为 rgb(...)） */
function inlineColor(el: HTMLElement, prop: string): string {
  const style = el.getAttribute('style') ?? '';
  const m = new RegExp(`${prop}:\\s*([^;]+)`).exec(style);
  return m ? m[1].trim() : '';
}

/** hsl(H, S%, L%) → rgb(R, G, B)，与 jsdom 归一化结果同口径 */
function hslToRgb(h: number, s: number, l: number): string {
  const hh = ((h % 360) + 360) % 360;
  const ss = s / 100;
  const ll = l / 100;
  const c = (1 - Math.abs(2 * ll - 1)) * ss;
  const x = c * (1 - Math.abs(((hh / 60) % 2) - 1));
  const m = ll - c / 2;
  let rgb: number[];
  if (hh < 60) rgb = [c, x, 0];
  else if (hh < 120) rgb = [x, c, 0];
  else if (hh < 180) rgb = [0, c, x];
  else if (hh < 240) rgb = [0, x, c];
  else if (hh < 300) rgb = [x, 0, c];
  else rgb = [c, 0, x];
  return `rgb(${rgb.map((v) => Math.round((v + m) * 255)).join(', ')})`;
}

/** hsl 字符串 → rgb 字符串（测试侧换算，用于比对 jsdom 归一化后的内联色） */
function hslStringToRgb(value: string): string {
  const m = /^hsl\((\d+), (\d+)%, (\d+)%\)$/.exec(value);
  if (!m) return '';
  return hslToRgb(Number(m[1]), Number(m[2]), Number(m[3]));
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

describe('#1373-A 节点个体着色（决策①：色相分层，同类型个体可辨）', () => {
  it('N10 画布节点 testid = library-kg-node-<type>-<entity_id> 且默认带 data-dim="0"（供着色/筛选断言锚定）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    // #1529：全部种子节点始终在 DOM，默认（未筛选）均为 data-dim="0"
    for (const id of NODE_TESTIDS) {
      const el = screen.getByTestId(id);
      expect(el, id).toBeInTheDocument();
      expect(el.getAttribute('data-dim'), id).toBe('0');
    }
  });

  it('N10 个体色写入内联样式：底色 = 该实体派生色（不再是六类固定 hex）', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    for (const n of GRAPH_SEED.nodes) {
      const el = screen.getByTestId(`library-kg-node-${n.type}-${n.entity_id}`);
      const derived = deriveNodeColor(n);
      expect(inlineColor(el, 'background-color'), `${n.id} 底色`).toBe(hslStringToRgb(derived.bg));
      // 圆点必须是「个体色」而非类型基准色（旧实现六类固定 hex 会在此 FAIL）
      const dot = el.querySelector('.kg-dot') as HTMLElement | null;
      expect(dot, `${n.id} 圆点`).not.toBeNull();
      expect(inlineColor(dot as HTMLElement, 'background-color')).toBe(hslStringToRgb(derived.dot));
    }
  });

  it('N10 类型色相带：节点底色色相落在该类型基准色相 ±18° 内', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    for (const n of GRAPH_SEED.nodes) {
      const el = screen.getByTestId(`library-kg-node-${n.type}-${n.entity_id}`);
      const derived = deriveNodeColor(n);
      const hue = Number(/^hsl\((\d+),/.exec(derived.bg)?.[1]);
      const dist = Math.min(Math.abs(hue - TYPE_HUE[n.type]), 360 - Math.abs(hue - TYPE_HUE[n.type]));
      expect(dist, `${n.id} 色相 ${hue} vs 基准 ${TYPE_HUE[n.type]}`).toBeLessThanOrEqual(18);
      expect(inlineColor(el, 'background-color')).not.toBe('');
    }
  });

  it('N10 图例常驻：library-kg-legend + 六类 library-kg-legend-<type> + 画布提示', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    const legend = screen.getByTestId('library-kg-legend');
    expect(legend).toBeInTheDocument();
    for (const t of ['character', 'world', 'outline', 'timeline', 'foreshadow', 'map_pin']) {
      expect(screen.getByTestId(`library-kg-legend-${t}`), t).toBeInTheDocument();
    }
    // 原「滚轮缩放 · 拖拽节点」提示并入图例行（不占版面高度）
    expect(legend).toHaveTextContent('滚轮缩放');
    expect(legend).toHaveTextContent('图例');
  });
});

describe('#1373-B 类别/实体筛选（决策②③④：左侧面板 + 折叠 + 记忆）', () => {
  it('N11 默认态：面板展开、全部实体可见、摘要呈「全部 · 显示 5 个实体」（决策③）', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    expect(screen.getByTestId('library-kg-filter-panel')).toBeInTheDocument();
    // 折叠态入口在展开态不出现
    expect(screen.queryByTestId('library-kg-filterbar')).toBeNull();
    // #1529：默认全量活跃、无人变暗（画布不被裁剪）
    expect(activeNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    expect(dimmedNodeTestIds()).toEqual([]);
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('显示 5 个实体');
    // 类别组 = 六类（每类一行）
    for (const t of ['character', 'world', 'outline', 'timeline', 'foreshadow', 'map_pin']) {
      expect(screen.getByTestId(`library-kg-filter-panel-cat-${t}`), t).toBeInTheDocument();
    }
    // 实体组 = 当前可见实体列表（5 行）
    for (const n of GRAPH_SEED.nodes) {
      expect(
        screen.getByTestId(`library-kg-filter-panel-entity-${n.type}-${n.entity_id}`),
        n.id,
      ).toBeInTheDocument();
    }
  });

  /* #1465：原「N11 类别单选」「N11 类别替换（单选非多选）」两条用例的命题已被
     pages/library-kg-filter-1465.test.tsx（#1465 契约）取代 —— 类别改「多选、默认全选」，
     点某类 = 取消该类（不再是「替换/回全部」）。 */

  it('N12 实体多选：点实体 = 取消它（仅它变暗，其余保留）；再点恢复全量', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    // #1529：点「林尘」→ 从全选里去掉它 → 仅它变暗，其余 4 个仍活跃（且全部仍在 DOM）
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c1'));
    await waitFor(() => {
      expect(dimmedNodeTestIds()).toEqual(['library-kg-node-character-c1']);
    });
    expect(activeNodeTestIds()).toEqual([
      'library-kg-node-character-c2',
      'library-kg-node-character-c3',
      'library-kg-node-world-w1',
      'library-kg-node-world-w2',
    ]);
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('显示 4 个实体');
    expectAllNodesRendered();

    // 再点同一实体 → 勾回 = 恢复全量（entities 回到 null）
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c1'));
    await waitFor(() => {
      expect(dimmedNodeTestIds()).toEqual([]);
    });
    expect(activeNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('显示 5 个实体');
  });

  it('N12 类别 ∩ 实体：#1568 实体定向三态（只留「林尘」被选中 + 取消世界观类）', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    // #1465：点类别 = 取消该类 → 取消世界观，世界观两节点变暗
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-world'));
    await waitFor(() => {
      expect(dimmedNodeTestIds()).toEqual(['library-kg-node-world-w1', 'library-kg-node-world-w2']);
    });
    // 取消 c2 / c3 → 角色类里只留「林尘」被选中（实体定向激活）
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c2'));
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c3'));
    await waitFor(() => {
      expect(activeNodeTestIds()).toEqual(['library-kg-node-character-c1']);
    });
    // #1568 三态（收窄 #1529）：c2 与 c1 相连 → 灰显保位；c3 既未选中也不相连 → **隐藏**
    // （#1529 时 c3 还只是灰显）；世界观两节点属**类别外** → 维持「只降灰、不隐藏」（N21 类别路不回归）
    expect(dimmedNodeTestIds()).toEqual([
      'library-kg-node-character-c2',
      'library-kg-node-world-w1',
      'library-kg-node-world-w2',
    ]);
    expect(screen.getByTestId('library-kg-node-character-c3').getAttribute('data-hidden')).toBe('1');
    expect(screen.getByTestId('library-kg-node-world-w2').getAttribute('data-hidden')).toBe('0');
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('显示 1 个实体');
  });

  it('N11 类别变更不清空无关实体选择（#1529：取消无关类别 → 实体选择保持）', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    // 取消（变暗）「林尘」
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c1'));
    await waitFor(() => expect(dimmedNodeTestIds()).toEqual(['library-kg-node-character-c1']));
    // 取消**世界观**（与「林尘」无关的类别）→ 实体选择保持；世界观两节点一并变暗
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-world'));
    await waitFor(() => {
      expect(dimmedNodeTestIds()).toEqual([
        'library-kg-node-character-c1',
        'library-kg-node-world-w1',
        'library-kg-node-world-w2',
      ]);
    });
    expect(activeNodeTestIds()).toEqual(['library-kg-node-character-c2', 'library-kg-node-character-c3']);
    // 实体选择未被清空（记忆仍是 entities 数组，未回退全选）
    expect(localStorage.getItem('inkflow:kg:filters:p1')).toContain('"entities"');
  });

  it('N15 搜索只过滤实体列表，不改画布', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    fireEvent.change(screen.getByTestId('library-kg-filter-panel-search'), {
      target: { value: '断崖' },
    });
    await waitFor(() => {
      expect(screen.getByTestId('library-kg-filter-panel-entity-world-w2')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('library-kg-filter-panel-entity-character-c1')).toBeNull();
    // 画布不受搜索影响（全部活跃、无人变暗）
    expect(activeNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    expect(dimmedNodeTestIds()).toEqual([]);
  });

  it('筛选无结果：全部节点变暗但仍在 DOM + library-kg-filter-empty 提示', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    // #1465：取消种子里的全部两类（角色 + 世界观）→ 无活跃节点
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-world'));
    await waitFor(() => {
      expect(screen.getByTestId('library-kg-filter-empty')).toBeInTheDocument();
    });
    // #1529：画布不裁剪 —— 所有节点仍在 DOM，只是全部变暗
    expect(activeNodeTestIds()).toEqual([]);
    expect(dimmedNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    expectAllNodesRendered();
    // 图谱本身非空 → 不误报「图谱为空」
    expect(screen.queryByTestId('library-kg-empty')).toBeNull();
  });

  it('N14 折叠：面板整块移出 DOM + 左侧竖条接管 + 筛选保持生效', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    // #1465：点类别 = 取消该类 → 取消角色，世界观保持活跃
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() =>
      expect(activeNodeTestIds()).toEqual(['library-kg-node-world-w1', 'library-kg-node-world-w2']),
    );

    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() => {
      expect(screen.queryByTestId('library-kg-filter-panel')).toBeNull();
      expect(screen.getByTestId('library-kg-filterbar')).toBeInTheDocument();
    });
    // 折叠不牺牲筛选结果（N14 的核心）：角色类仍变暗，世界观活跃
    expect(dimmedNodeTestIds()).toEqual([
      'library-kg-node-character-c1',
      'library-kg-node-character-c2',
      'library-kg-node-character-c3',
    ]);
    expect(screen.getByTestId('library-kg-filterbar-summary')).toHaveTextContent('显示 2 个实体');
  });

  it('N14 展开：点折叠栏「展开筛选」还原面板，勾选态回填', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() => expect(screen.queryByTestId('library-kg-filter-panel')).toBeNull());

    await user.click(screen.getByTestId('library-kg-filterbar-expand'));
    await waitFor(() => {
      expect(screen.getByTestId('library-kg-filter-panel')).toBeInTheDocument();
      expect(screen.queryByTestId('library-kg-filterbar')).toBeNull();
    });
  });

  it('N15 一键清除筛选：面板入口与折叠栏入口同一行为（恢复全量 + 记忆同步）', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    // ① 面板入口
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c1')); // 取消林尘
    await waitFor(() => expect(dimmedNodeTestIds()).toEqual(['library-kg-node-character-c1']));
    await user.click(screen.getByTestId('library-kg-filter-panel-clear'));
    await waitFor(() => expect(activeNodeTestIds()).toEqual([...NODE_TESTIDS].sort()));
    expect(dimmedNodeTestIds()).toEqual([]);
    expect(localStorage.getItem('inkflow:kg:filters:p1')).toContain('"categories"');

    // ② 折叠栏入口
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character')); // 取消角色类
    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() =>
      expect(activeNodeTestIds()).toEqual(['library-kg-node-world-w1', 'library-kg-node-world-w2']),
    );
    await user.click(screen.getByTestId('library-kg-filterbar-clear'));
    await waitFor(() => expect(activeNodeTestIds()).toEqual([...NODE_TESTIDS].sort()));
  });

  it('N15 选择即记忆：类别/实体/折叠写入 localStorage（决策③）', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    // #1529：点实体 = 取消它；记忆写 categories + entities（数组）
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c2'));
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-world'));
    await user.click(screen.getByTestId('library-kg-filter-collapse'));

    await waitFor(() => {
      const raw = localStorage.getItem('inkflow:kg:filters:p1') ?? '';
      expect(raw).toContain('"categories"');
      expect(raw).toContain('"entities"'); // #1529：新记忆形态（旧 `entity` 已废弃）
      expect(raw).not.toContain('"world"'); // 类别已取消「世界观」
      expect(raw).not.toContain('"character:c2"'); // 点实体 = 取消它（多选集合）
      expect(raw).toContain('character:c1'); // 其余实体保持选中
      expect(localStorage.getItem('inkflow:kg:panel')).toBe('closed');
    });
  });

  it('N15 重挂载后按记忆恢复（筛选值 + 面板折叠态）', async () => {
    const user = userEvent.setup();
    const first = await openGraph(user);

    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() => expect(localStorage.getItem('inkflow:kg:panel')).toBe('closed'));

    first.unmount();

    // 重新挂载（模拟切页签 / 刷新）：应恢复「角色类已取消 + 面板收起」→ 仅世界观活跃
    const user2 = userEvent.setup();
    renderLibrary();
    await user2.click(screen.getByRole('tab', { name: '知识图谱' }));
    await screen.findByTestId('library-kg-canvas');
    await waitFor(() => {
      expect(activeNodeTestIds()).toEqual(['library-kg-node-world-w1', 'library-kg-node-world-w2']);
    });
    expect(screen.queryByTestId('library-kg-filter-panel')).toBeNull();
    expect(screen.getByTestId('library-kg-filterbar')).toBeInTheDocument();
  });

  it('N15 记忆损坏 / 幽灵实体 → 静默回退默认（不抛错）', async () => {
    localStorage.setItem('inkflow:kg:filters:p1', 'not-json{{{');
    localStorage.setItem('inkflow:kg:panel', 'weird');
    const user = userEvent.setup();
    await openGraph(user);

    expect(activeNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    expect(dimmedNodeTestIds()).toEqual([]);
    expect(screen.getByTestId('library-kg-filter-panel')).toBeInTheDocument();
  });

  it('N15 记忆里的实体已不存在 → 丢弃（不出现「选中了不存在的实体」）', async () => {
    // 旧格式 {category, entity}（#1529 读时迁移）；幽灵实体 character:c9 不在图谱中
    localStorage.setItem(
      'inkflow:kg:filters:p1',
      JSON.stringify({ category: 'all', entity: 'character:c9' }),
    );
    const user = userEvent.setup();
    await openGraph(user);

    // 节点集到位后记忆里的幽灵实体被丢弃 → 恢复全量（全部活跃）
    await waitFor(() => {
      expect(activeNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    });
  });
});

describe('#1373-C 筛选控件只属于图谱视图（决策④：不筛选关系列表）', () => {
  it('N13 关系列表视图：筛选面板 / 折叠栏 / 图例 / 筛选空态都不渲染', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    await user.click(screen.getByTestId('library-kg-view-list'));
    await screen.findByTestId('library-kg-relation-list');

    expect(screen.queryByTestId('library-kg-filter-panel')).toBeNull();
    expect(screen.queryByTestId('library-kg-filterbar')).toBeNull();
    expect(screen.queryByTestId('library-kg-legend')).toBeNull();
    expect(screen.queryByTestId('library-kg-filter-empty')).toBeNull();
  });

  it('N13 图谱空态：筛选面板 / 折叠栏 / 图例让位（无可筛对象）', async () => {
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

    expect(screen.queryByTestId('library-kg-filter-panel')).toBeNull();
    expect(screen.queryByTestId('library-kg-filterbar')).toBeNull();
    expect(screen.queryByTestId('library-kg-legend')).toBeNull();
    expect(screen.queryByTestId('library-kg-filter-empty')).toBeNull();
  });
});
