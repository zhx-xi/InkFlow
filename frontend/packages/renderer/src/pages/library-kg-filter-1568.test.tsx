/**
 * #1568 + #1569（0.17.0 rc2 修复批 W10b-1）RED 契约（integration 层：组件交互）
 * 对应 specs/f19-gui/knowledge.md §1/§2/§3 N12/N20/N21/N22 + §4.2/§4.4
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【一句话命题】
 * ①（#1568）「清除筛选」名实不符 → 拆成**「全选」+「全部取消」两个独立入口**；
 *    且**实体定向筛选改三态**：选中=彩色 / 相连=灰显保位 / 无关=**隐藏**（类别路仍只降灰）。
 * ②（#1569）改「每页条数」后**分页条不再消失**（含每页条数选择器 → 可改回）+ 回第 1 页 +
 *    分类块/实体块判据各自独立。
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * 【拍板口径（#1568/#1569，2026-10-10 用户）】
 * - #1568 = B + C：#1568 → 「全选」保留语义 + 另加「全部取消」；实体定向路改三态（**部分收窄 #1529**）
 * - #1569 = A：size 变更归零 + 判据按「总数 > 当前 size」+ 两块独立
 *
 * 【RED 预期】本文件在实现前必须真跑起来并 FAIL（断言失败，非 collection error）：
 *   当前 `data-hidden` 属性不存在、`-cancel-all` 入口不存在、实体分页条在「池 ≤ size」时整体消失。
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

/** 8 实体；边 kr:1 = c1→w1（属于）、kr:2 = c2→c1（同门）→ c1 的邻居 = {c2, w1} */
const SEED: GraphNode[] = [
  { id: 'character:c1', type: 'character', entity_id: 'c1', name: '林尘' },
  { id: 'character:c2', type: 'character', entity_id: 'c2', name: '阿澈' },
  { id: 'character:c3', type: 'character', entity_id: 'c3', name: '白丁' },
  { id: 'world:w1', type: 'world', entity_id: 'w1', name: '清河县' },
  { id: 'world:w2', type: 'world', entity_id: 'w2', name: '断崖' },
  { id: 'outline:o1', type: 'outline', entity_id: 'o1', name: '初入江湖' },
  { id: 'timeline:t1', type: 'timeline', entity_id: 't1', name: '夜访' },
  { id: 'foreshadow:f1', type: 'foreshadow', entity_id: 'f1', name: '断剑' },
];
const EDGES: GraphEdge[] = [
  { id: 'kr:1', source: 'character:c1', target: 'world:w1', label: '属于', description: '', source_table: 'knowledge_relations' },
  { id: 'kr:2', source: 'character:c2', target: 'character:c1', label: '同门', description: '', source_table: 'knowledge_relations' },
];

const NODE_TESTIDS = SEED.map((n) => `library-kg-node-${n.type}-${n.entity_id}`);

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
  renderLibrary();
  await user.click(screen.getByRole('tab', { name: '知识图谱' }));
  await screen.findByTestId('library-kg-canvas');
  await waitFor(() => {
    expect(screen.getByTestId('library-kg-node-character-c1')).toBeInTheDocument();
  });
}

/** 画布节点灰显（data-dim="1"）—— 保留但降灰 */
function dimmedNodeTestIds(): string[] {
  return NODE_TESTIDS.filter((id) => screen.getByTestId(id).getAttribute('data-dim') === '1').sort();
}
/** 画布节点隐藏（data-hidden="1"）—— 不显示、不参与连线 */
function hiddenNodeTestIds(): string[] {
  return NODE_TESTIDS.filter((id) => screen.getByTestId(id).getAttribute('data-hidden') === '1').sort();
}
/** 画布节点彩色（data-dim="0" 且 data-hidden="0"） */
function coloredNodeTestIds(): string[] {
  return NODE_TESTIDS.filter((id) => {
    const el = screen.getByTestId(id);
    return el.getAttribute('data-dim') === '0' && el.getAttribute('data-hidden') === '0';
  }).sort();
}

const node = (id: string) => screen.getByTestId(`library-kg-node-${id.replace(':', '-')}`);
/** `character:c1` → `library-kg-node-character-c1`（画布/实体行的 testid 用连字符） */
const nodeTid = (id: string) => `library-kg-node-${id.replace(':', '-')}`;

/** 构造「实体定向」态：默认全选 → **逐个取消不在 ids 内的实体**（类别保持全选）。
 *  注：不可借「全部取消」构造——#1568 拍板下它会连类别一起清空（实体列表随之变空）。 */
async function focusEntities(user: ReturnType<typeof userEvent.setup>, ids: string[]) {
  const keep = new Set(ids.map((id) => id.replace(':', '-')));
  for (const n of SEED) {
    const key = `${n.type}-${n.entity_id}`;
    if (keep.has(key)) continue;
    await user.click(screen.getByTestId(`library-kg-filter-panel-entity-${key}`));
  }
}

/** #1569：驱动实体块的「每页条数」Select（Radix 需先点 trigger 再点 option） */
async function pickEntityPageSize(user: ReturnType<typeof userEvent.setup>, size: string) {
  await user.click(screen.getByTestId('library-kg-entity-page-size-select'));
  const opt = await screen.findByRole('option', { name: size });
  await user.click(opt);
  await waitFor(() => {});
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
      return { nodes: SEED.map((n) => ({ ...n })), edges: EDGES.map((e) => ({ ...e })) };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('#1568-A「全选」/「全部取消」两态分离（名实相符）', () => {
  it('N20 两个独立入口并存：面板底部「全部取消」+「全选」同时在场且标签不同', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    const cancelAll = screen.getByTestId('library-kg-filter-panel-cancel-all');
    const selectAll = screen.getByTestId('library-kg-filter-panel-clear');
    expect(cancelAll).toBeInTheDocument();
    expect(selectAll).toBeInTheDocument();
    expect(cancelAll.textContent).toContain('全部取消');
    expect(selectAll.textContent).toContain('全选');
    expect(cancelAll.textContent).not.toBe(selectAll.textContent);
  });

  it('N20 点「全部取消」→ 类别与实体全不选 + 画布全部灰显（无高亮无隐藏）+ 空态卡片', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    await user.click(screen.getByTestId('library-kg-filter-panel-cancel-all'));

    await waitFor(() => expect(screen.getByTestId('library-kg-filter-empty')).toBeInTheDocument());
    expect(dimmedNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    expect(hiddenNodeTestIds()).toEqual([]);
    expect(coloredNodeTestIds()).toEqual([]);
    // 记忆同步：类别与实体都落空数组
    expect(JSON.parse(localStorage.getItem('inkflow:kg:filters:p1') ?? '{}')).toEqual({
      categories: [],
      entities: [],
    });
    // 类别块仍渲染 6 行（可重新勾选，不是死锁）
    for (const t of ['character', 'world', 'outline', 'timeline', 'foreshadow', 'map_pin']) {
      expect(screen.getByTestId(`library-kg-filter-panel-cat-${t}`), t).toBeInTheDocument();
    }
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('显示 0 个实体');
  });

  it('N20「全选」与「全部取消」互不覆盖：取消后可一键全选恢复，反之亦然', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    await user.click(screen.getByTestId('library-kg-filter-panel-cancel-all'));
    await waitFor(() => expect(coloredNodeTestIds()).toEqual([]));

    // 「全选」入口仍在（未被「全部取消」吞掉）→ 点它恢复全量
    await user.click(screen.getByTestId('library-kg-filter-panel-clear'));
    await waitFor(() => expect(coloredNodeTestIds()).toEqual([...NODE_TESTIDS].sort()));
    expect(dimmedNodeTestIds()).toEqual([]);
    expect(hiddenNodeTestIds()).toEqual([]);

    // 反向：再取消一个实体后点「全部取消」
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c1'));
    await waitFor(() => expect(coloredNodeTestIds()).not.toEqual([...NODE_TESTIDS].sort()));
    await user.click(screen.getByTestId('library-kg-filter-panel-cancel-all'));
    await waitFor(() => expect(coloredNodeTestIds()).toEqual([]));
  });

  it('N20 折叠竖条内亦有「全部取消」入口（与面板底部同语义）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() => expect(screen.getByTestId('library-kg-filterbar')).toBeInTheDocument());

    const barCancelAll = screen.getByTestId('library-kg-filterbar-cancel-all');
    expect(barCancelAll).toBeInTheDocument();
    expect(screen.getByTestId('library-kg-filterbar-clear')).toBeInTheDocument();

    await user.click(barCancelAll);
    await waitFor(() => expect(coloredNodeTestIds()).toEqual([]));
  });
});

describe('#1568-B 实体定向三态（彩色 / 灰显保位 / 隐藏）', () => {
  it('N12 选中 1 个实体：它彩色、其邻居灰显保位（仍在 DOM）、其余**隐藏**', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    await focusEntities(user, ['character:c1']);

    await waitFor(() => expect(node('character:c1').getAttribute('data-dim')).toBe('0'));
    expect(node('character:c1').getAttribute('data-hidden')).toBe('0');
    // 相连未选 → 灰显保位
    expect(dimmedNodeTestIds()).toEqual(['library-kg-node-character-c2', 'library-kg-node-world-w1']);
    for (const id of ['character:c2', 'world:w1']) {
      expect(node(id).getAttribute('data-hidden'), id).toBe('0');
    }
    // 既未选中也不相连 → 隐藏
    expect(hiddenNodeTestIds()).toEqual(
      ['character:c3', 'foreshadow:f1', 'outline:o1', 'timeline:t1', 'world:w2'].map(nodeTid).sort(),
    );
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('显示 1 个实体');
  });

  it('N12 取消实体定向（回全选）→ 全部恢复显示（无灰显无隐藏）', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    await focusEntities(user, ['character:c1']);
    await waitFor(() => expect(hiddenNodeTestIds()).toHaveLength(5));

    await user.click(screen.getByTestId('library-kg-filter-panel-clear'));
    await waitFor(() => {
      expect(dimmedNodeTestIds()).toEqual([]);
      expect(hiddenNodeTestIds()).toEqual([]);
      expect(coloredNodeTestIds()).toEqual([...NODE_TESTIDS].sort());
    });
  });

  it('N12 多选（≥2）按**并集邻居**处理，无抖动', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    // c1（邻 w1/c2）+ w2（无边）→ 并集邻居 = {c2, w1}
    await focusEntities(user, ['character:c1', 'world:w2']);

    await waitFor(() => expect(coloredNodeTestIds()).toEqual(['library-kg-node-character-c1', 'library-kg-node-world-w2']));
    expect(dimmedNodeTestIds()).toEqual(['library-kg-node-character-c2', 'library-kg-node-world-w1']);
    expect(hiddenNodeTestIds()).toEqual(
      ['character:c3', 'foreshadow:f1', 'outline:o1', 'timeline:t1'].map(nodeTid).sort(),
    );
  });

  it('N21 类别路不回归：未做实体定向时取消类别 = 只降灰、**不隐藏**', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));

    await waitFor(() => expect(dimmedNodeTestIds()).toHaveLength(3));
    expect(hiddenNodeTestIds()).toEqual([]); // 一个都不许隐藏
    expect(coloredNodeTestIds()).toEqual(
      SEED.filter((n) => n.type !== 'character').map((n) => nodeTid(n.id)).sort(),
    );
  });

  it('N21 实体定向激活时**类别外节点仍只灰显、永不隐藏**', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    // 只选 c1；再取消「世界观」类别 → w1（邻居）/w2（类别外）都只灰显，不许隐藏
    await focusEntities(user, ['character:c1']);
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-world'));

    await waitFor(() => expect(node('world:w2').getAttribute('data-dim')).toBe('1'));
    expect(node('world:w2').getAttribute('data-hidden')).toBe('0');
    expect(node('world:w1').getAttribute('data-hidden')).toBe('0');
    expect(hiddenNodeTestIds()).toEqual(
      ['character:c3', 'foreshadow:f1', 'outline:o1', 'timeline:t1'].map(nodeTid).sort(),
    );
  });
});

describe('#1569 分页条：改「每页条数」后不消失 + 回第 1 页 + 两块独立', () => {
  /** 43 条池（贴近真实项目「43+ 角色」）—— 单页装不下，才谈得上「改 size 后翻页能力」 */
  const BIG: GraphNode[] = Array.from({ length: 43 }, (_, i) => ({
    id: `character:c${i + 1}`,
    type: 'character' as const,
    entity_id: `c${i + 1}`,
    name: `角色${String(i + 1).padStart(2, '0')}`,
  }));
  const BIG_ROW = /^library-kg-filter-panel-entity-character-/;

  function mockBigGraph() {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/maps') return { items: [] };
      if (path.startsWith('/api/v1/projects/p1/knowledge-graph')) {
        return { nodes: BIG.map((n) => ({ ...n })), edges: [] };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
  }

  it('N22 翻页后改「每页条数」→ 分页条仍在 + 回到第 1 页（不出现空白页）', async () => {
    mockBigGraph();
    const user = userEvent.setup();
    await openGraph(user);

    expect(screen.getByTestId('library-kg-entity-page-info')).toHaveTextContent('1 / 5');
    await user.click(screen.getByTestId('library-kg-entity-page-next'));
    await waitFor(() => expect(screen.getByTestId('library-kg-entity-page-info')).toHaveTextContent('2 / 5'));

    // 改 size：分页条必须仍在 + 页码归零（原实现：页号不归零 → 可能空白页）
    await pickEntityPageSize(user, '25');
    expect(screen.getByTestId('library-kg-entity-page')).toBeInTheDocument();
    expect(screen.getByTestId('library-kg-entity-page-info')).toHaveTextContent('1 / 2');
    expect(screen.queryAllByTestId(BIG_ROW)).toHaveLength(25);
    expect(screen.getAllByTestId(BIG_ROW)[0].getAttribute('data-testid')).toBe(
      'library-kg-filter-panel-entity-character-c1',
    );
  });

  it('N22 池 ≤ 新 size 时分页条**仍在**（含每页条数选择器 → 用户能改回来）', async () => {
    mockBigGraph();
    const user = userEvent.setup();
    await openGraph(user);

    // 43 ≤ 100：原实现整体消失（含选择器）→ 用户无法改回，只能刷新
    await pickEntityPageSize(user, '100');
    expect(screen.getByTestId('library-kg-entity-page')).toBeInTheDocument();
    expect(screen.getByTestId('library-kg-entity-page-size-select')).toBeInTheDocument();
    expect(screen.getByTestId('library-kg-entity-page-info')).toHaveTextContent('1 / 1');
    expect(screen.getByTestId('library-kg-entity-page-next')).toBeDisabled();
    expect(screen.queryAllByTestId(BIG_ROW)).toHaveLength(43);

    // 改回来仍然可用
    await pickEntityPageSize(user, '10');
    expect(screen.getByTestId('library-kg-entity-page-info')).toHaveTextContent('1 / 5');
  });

  it('N22 分类块与实体块判据各自独立：改实体块 size 不影响分类块的出场', async () => {
    mockBigGraph();
    const user = userEvent.setup();
    await openGraph(user);

    // 六类 ≤ 每页条数 → 分类块分页条常态不出现（#1529 锁定契约）
    expect(screen.queryByTestId('library-kg-cat-page')).toBeNull();

    await pickEntityPageSize(user, '100');
    expect(screen.getByTestId('library-kg-entity-page')).toBeInTheDocument();
    expect(screen.queryByTestId('library-kg-cat-page')).toBeNull();
    for (const t of ['character', 'world', 'outline', 'timeline', 'foreshadow', 'map_pin']) {
      expect(screen.getByTestId(`library-kg-filter-panel-cat-${t}`), t).toBeInTheDocument();
    }
  });
});
