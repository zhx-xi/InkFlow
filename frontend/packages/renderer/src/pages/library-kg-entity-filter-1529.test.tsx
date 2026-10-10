/**
 * #1529（0.17.0 W8g）知识图谱「实体筛选语义统一 + 拼音排序 + 分页」RED 契约（integration 层：组件交互）
 * 对应 specs/f19-gui/knowledge.md §2「实体行 / 实体列表排序+分页 / 分类块分页」+ §3 N19 + §4.2
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【一句话命题】实体筛选从「单选 + 邻接子图 + 摘除未选中节点」改为
 *               **多选集合（默认全选）+ 未勾选统一灰显（不摘除，画布布局不跳动）**，
 *               实体列表按拼音排序、并拆出**与分类块互不相干**的独立分页。
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * 【拍板口径（#1529，2026-10-08/09 用户）】
 * - 实体 = 多选集合、默认全选；取消某实体 = **该实体与相关边灰显**（不再是「隐藏」/「邻接子图」）
 * - 灰显判据落在 DOM：画布节点 `data-dim="1"`（未勾选）/ `"0"`（勾选）
 * - 面板拆**两个独立块**：分类块（6 条，自带分页条） / 实体块（自带独立分页条 + 每页条数）
 * - 实体列表 = 已勾选类别 ∩ 搜索词 → `Intl.Collator('zh')` 排序 → 纯前端分页切片
 * - `filterActive` 判据统一：`categories.length < 6 || entities !== null`
 *
 * 【RED 预期】本文件在实现前必须真跑起来并 FAIL（断言失败，非 collection error）：
 *   当前实现是「单选 + 摘除」，故 `data-dim` 属性不存在、实体行是单选、分页条/排序均缺席 → 断言失败。
 *
 * ⚠️ jsdom 无布局引擎：边的灰显、真实几何（等高/左对齐）只能在真实浏览器由
 *    `design/GUI/_tools/shot-knowledge-graph-scope.cjs` 断言（节点 data-dim 在 jsdom 可断言）。
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

/** 12 个实体（> 每页 10 条 → 分页出现）；含一个拉丁名以验证中英文混排 */
const SEED: GraphNode[] = [
  { id: 'character:c1', type: 'character', entity_id: 'c1', name: '林尘' },
  { id: 'character:c2', type: 'character', entity_id: 'c2', name: '阿澈' },
  { id: 'character:c3', type: 'character', entity_id: 'c3', name: '白丁' },
  { id: 'character:c4', type: 'character', entity_id: 'c4', name: '苏离' },
  { id: 'character:c5', type: 'character', entity_id: 'c5', name: 'Aaron' },
  { id: 'world:w1', type: 'world', entity_id: 'w1', name: '清河县' },
  { id: 'world:w2', type: 'world', entity_id: 'w2', name: '断崖' },
  { id: 'world:w3', type: 'world', entity_id: 'w3', name: '云梦泽' },
  { id: 'outline:o1', type: 'outline', entity_id: 'o1', name: '初入江湖' },
  { id: 'timeline:t1', type: 'timeline', entity_id: 't1', name: '夜访' },
  { id: 'foreshadow:f1', type: 'foreshadow', entity_id: 'f1', name: '断剑' },
  { id: 'map_pin:m1', type: 'map_pin', entity_id: 'm1', name: '城北' },
];

const EDGES: GraphEdge[] = [
  { id: 'kr:1', source: 'character:c1', target: 'world:w1', label: '属于', description: '', source_table: 'knowledge_relations' },
  { id: 'kr:2', source: 'character:c2', target: 'character:c1', label: '同门', description: '', source_table: 'knowledge_relations' },
];

const SEED_NAMES = SEED.map((n) => n.name);
const NODE_TESTIDS = SEED.map((n) => `library-kg-node-${n.type}-${n.entity_id}`);
const ENTITY_ROW = /^library-kg-filter-panel-entity-(character|world|outline|timeline|foreshadow|map_pin)-/;
const CAT_TYPES = ['character', 'world', 'outline', 'timeline', 'foreshadow', 'map_pin'];

/** 期望排序（与实现同口径：Intl.Collator('zh')，中文出拼音序） */
const pinyinSorted = (names: string[]): string[] =>
  names.slice().sort((a, b) => new Intl.Collator('zh').compare(a, b));

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

/** 画布上节点的灰显标记（`data-dim="1"` = 未勾选 → 灰显） */
function dimmedNodeTestIds(): string[] {
  return NODE_TESTIDS.filter((id) => screen.getByTestId(id).getAttribute('data-dim') === '1').sort();
}
/** #1568：实体定向三态下被**隐藏**的节点（`data-hidden="1"`） */
function hiddenNodeTestIds(): string[] {
  return NODE_TESTIDS.filter((id) => screen.getByTestId(id).getAttribute('data-hidden') === '1').sort();
}
/** 可见实体行（面板实体块当前页） */
function entityRowTestIds(): string[] {
  return screen.getAllByTestId(ENTITY_ROW).map((el) => el.getAttribute('data-testid') ?? '').sort();
}
function entityRowNames(): string[] {
  return screen.getAllByTestId(ENTITY_ROW).map((el) => el.querySelector('.nm')?.textContent ?? '');
}
function entityCheckedRows(): number {
  return screen.getAllByTestId(ENTITY_ROW).filter((el) => {
    const input = el instanceof HTMLInputElement ? el : el.querySelector('input');
    return input !== null && input.checked;
  }).length;
}
function catChecked(type: string): boolean {
  const el = screen.getByTestId(`library-kg-filter-panel-cat-${type}`);
  const input = el instanceof HTMLInputElement ? el : el.querySelector('input');
  return input !== null && input.checked;
}
const idOfName = (name: string): string => {
  const n = SEED.find((x) => x.name === name);
  if (!n) throw new Error(`seed 里没有 ${name}`);
  return `${n.type}-${n.entity_id}`;
};

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

describe('#1529-A 实体多选：默认全选 + 未勾选统一灰显（不摘除）', () => {
  it('N19① 默认全选：第 1 页实体行全部勾选，画布 12 节点全部 `data-dim="0"`', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    expect(entityCheckedRows()).toBe(10);
    expect(dimmedNodeTestIds()).toEqual([]);
    for (const id of NODE_TESTIDS) expect(screen.getByTestId(id), id).toBeInTheDocument();
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('全部');
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('显示 12 个实体');
  });

  it('N19① 取消某实体 → **该节点灰显、其余正常、画布不摘除**（第 1 页首行）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    const firstName = pinyinSorted(SEED_NAMES)[0];
    const firstId = idOfName(firstName);

    await user.click(screen.getByTestId(`library-kg-filter-panel-entity-${firstId}`));

    await waitFor(() => {
      expect(screen.getByTestId(`library-kg-node-${firstId}`).getAttribute('data-dim')).toBe('1');
    });
    // 只它灰显（其余 11 个仍正常）
    expect(dimmedNodeTestIds()).toEqual([`library-kg-node-${firstId}`]);
    // 🔴 不摘除：12 个节点仍在画布上
    for (const id of NODE_TESTIDS) expect(screen.getByTestId(id), id).toBeInTheDocument();
    // 该行取消勾 + 可见数下降
    expect(entityCheckedRows()).toBe(9);
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('显示 11 个实体');
  });

  it('N19① 再点一次 → 恢复（勾回即正常彩色）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    const firstId = idOfName(pinyinSorted(SEED_NAMES)[0]);
    await user.click(screen.getByTestId(`library-kg-filter-panel-entity-${firstId}`));
    await waitFor(() => expect(dimmedNodeTestIds()).toHaveLength(1));
    await user.click(screen.getByTestId(`library-kg-filter-panel-entity-${firstId}`));
    await waitFor(() => expect(dimmedNodeTestIds()).toEqual([]));
    expect(screen.getByTestId('library-kg-filter-summary')).toHaveTextContent('显示 12 个实体');
  });

  it('🔴 #1568 实体定向三态：只勾一个实体 → 它彩色 / 相连者灰显保位 / 其余**隐藏**（收窄 #1529 的「统一灰显」）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    const ordered = pinyinSorted(SEED_NAMES);
    // 逐页取消全部 12 个实体（entities = [] → 空选，画布走筛选空态）
    for (const name of ordered.slice(0, 10)) {
      await user.click(screen.getByTestId(`library-kg-filter-panel-entity-${idOfName(name)}`));
    }
    await waitFor(() => expect(dimmedNodeTestIds()).toHaveLength(0));
    await user.click(screen.getByTestId('library-kg-entity-page-next'));
    await waitFor(() => expect(entityRowNames()).toEqual(ordered.slice(10)));
    for (const name of ordered.slice(10)) {
      await user.click(screen.getByTestId(`library-kg-filter-panel-entity-${idOfName(name)}`));
    }
    await user.click(screen.getByTestId('library-kg-entity-page-prev'));

    // 只勾回「林尘」（c1）→ 三态：它彩色；c2 / w1（相连）灰显保位；其余 9 个隐藏。
    // 旧邻接语义会把一跳邻居**变彩色** —— 三态下它们只灰显，不重新点亮。
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c1'));
    await waitFor(() => {
      expect(screen.getByTestId('library-kg-node-character-c1').getAttribute('data-dim')).toBe('0');
    });
    expect(screen.getByTestId('library-kg-node-character-c1').getAttribute('data-hidden')).toBe('0');
    expect(dimmedNodeTestIds()).toEqual(['library-kg-node-character-c2', 'library-kg-node-world-w1']);
    expect(hiddenNodeTestIds()).toHaveLength(9);
  });

  it('N19① filterActive 判据统一：仅取消一个实体 → 筛选生效（折叠后竖条描边 accent）', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    // 对照：未筛选时折叠 → 竖条无 accent 描边
    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() => expect(screen.getByTestId('library-kg-filterbar')).toBeInTheDocument());
    expect(screen.getByTestId('library-kg-filterbar').className).not.toMatch(/border-accent/);
    await user.click(screen.getByTestId('library-kg-filterbar-expand'));
    await waitFor(() => expect(screen.getByTestId('library-kg-filter-panel')).toBeInTheDocument());

    // 仅取消一个实体 → 筛选生效
    await user.click(screen.getByTestId(`library-kg-filter-panel-entity-${idOfName(pinyinSorted(SEED_NAMES)[0])}`));
    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() => {
      expect(screen.getByTestId('library-kg-filterbar').className).toMatch(/border-accent/);
    });
  });
});

describe('#1529-B 类别与实体同规则：取消类别 → 灰显而非摘除', () => {
  it('N11/N19 取消「角色」→ 5 个角色节点灰显，世界观等仍正常，画布不摘除 12 节点', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() => expect(dimmedNodeTestIds()).toHaveLength(5));
    expect(dimmedNodeTestIds()).toEqual(
      SEED.filter((n) => n.type === 'character')
        .map((n) => `library-kg-node-${n.type}-${n.entity_id}`)
        .sort(),
    );
    for (const id of NODE_TESTIDS) expect(screen.getByTestId(id), id).toBeInTheDocument();
    // #1465 ② 守住：实体列表同步去掉该类实体
    expect(screen.queryByTestId('library-kg-filter-panel-entity-character-c1')).toBeNull();
    // 勾回 → 全部正常
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() => expect(dimmedNodeTestIds()).toEqual([]));
    expect(catChecked('character')).toBe(true);
  });

  it('N19⑤ 取消类别**不再清空**实体选择（勾回即恢复）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-filter-panel-entity-character-c1'));
    await waitFor(() => expect(dimmedNodeTestIds()).toEqual(['library-kg-node-character-c1']));

    // 取消「角色」→ 该类 5 个节点全灰（含刚取消的 c1）
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() => expect(dimmedNodeTestIds()).toHaveLength(5));
    // 类别切换**不改写**实体集合：记忆里仍是「除 c1 外的 11 个」
    const stored = JSON.parse(localStorage.getItem('inkflow:kg:filters:p1') ?? '{}');
    expect(stored.entities).toHaveLength(11);
    expect(stored.entities).not.toContain('character:c1');

    // 勾回「角色」→ 被保留的选择原样生效：c1 仍灰、其余 11 个正常
    await user.click(screen.getByTestId('library-kg-filter-panel-cat-character'));
    await waitFor(() => expect(dimmedNodeTestIds()).toEqual(['library-kg-node-character-c1']));
  });
});

describe('#1529-C 实体列表：拼音排序 + 独立分页 + 每页条数', () => {
  it('N19② 实体列表按 Intl.Collator(\'zh\') 拼音序排列（断言顺序，且确实重排过）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    const expected = pinyinSorted(SEED_NAMES);
    expect(entityRowNames()).toEqual(expected.slice(0, 10));
    // 与「节点集原始顺序」不同 → 证明真的排过序（不是刚好一致）
    expect(entityRowNames()).not.toEqual(SEED_NAMES.slice(0, 10));
  });

  it('N19③ 分页：12 条 / 每页 10 → 首页 prev 禁用、next 可翻；第 2 页 = 拼音序第 11-12 条', async () => {
    const user = userEvent.setup();
    await openGraph(user);

    expect(screen.getByTestId('library-kg-entity-page-info')).toHaveTextContent('1 / 2');
    expect(screen.getByTestId('library-kg-entity-page-prev')).toBeDisabled();
    expect(screen.getByTestId('library-kg-entity-page-next')).not.toBeDisabled();
    expect(entityRowTestIds()).toHaveLength(10);

    await user.click(screen.getByTestId('library-kg-entity-page-next'));
    await waitFor(() => {
      expect(screen.getByTestId('library-kg-entity-page-info')).toHaveTextContent('2 / 2');
    });
    expect(entityRowNames()).toEqual(pinyinSorted(SEED_NAMES).slice(10));
    expect(screen.getByTestId('library-kg-entity-page-next')).toBeDisabled();
    expect(screen.getByTestId('library-kg-entity-page-prev')).not.toBeDisabled();
    // 分页只重绘列表 → 画布不受影响
    expect(dimmedNodeTestIds()).toEqual([]);
    for (const id of NODE_TESTIDS) expect(screen.getByTestId(id), id).toBeInTheDocument();
  });

  it('N19④ 分类块与实体块各自一套分页（互不相干）：分类块分页条常态不出现', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    const panel = screen.getByTestId('library-kg-filter-panel');
    // 两个独立块 = 两个独立滚动区
    expect(panel.querySelectorAll('.overflow-y-auto').length).toBeGreaterThanOrEqual(2);
    // 分类 6 条 ≤ 每页条数 → 分类块分页条不渲染；实体 12 条 → 实体块分页条在场
    expect(screen.queryByTestId('library-kg-cat-page')).toBeNull();
    expect(screen.getByTestId('library-kg-entity-page')).toBeInTheDocument();
    // 翻实体页不影响分类块
    await user.click(screen.getByTestId('library-kg-entity-page-next'));
    await waitFor(() => expect(screen.getByTestId('library-kg-entity-page-info')).toHaveTextContent('2 / 2'));
    expect(screen.queryByTestId('library-kg-cat-page')).toBeNull();
    for (const t of CAT_TYPES) expect(screen.getByTestId(`library-kg-filter-panel-cat-${t}`)).toBeInTheDocument();
  });

  it('N19④ 每页条数可改：控件在场（10/25/50/100）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    expect(screen.getByTestId('library-kg-entity-page-size-select')).toBeInTheDocument();
  });

  it('N19③ 搜索收窄后再分页：搜索「断」→ 池收窄且回第 1 页', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-entity-page-next'));
    await waitFor(() => expect(screen.getByTestId('library-kg-entity-page-info')).toHaveTextContent('2 / 2'));

    const search = screen.getByTestId('library-kg-filter-panel-search');
    await user.type(search, '断');
    await waitFor(() => {
      // 拼音序：断剑(duànjiàn) < 断崖(duànyá)
      expect(entityRowNames()).toEqual(['断剑', '断崖']);
    });
    // 池 2 条 ≤ 每页 10 → 分页条让位（且不再停在第 2 页）
    expect(screen.queryByTestId('library-kg-entity-page')).toBeNull();
  });
});

describe('#1529-D 前序不回归（#1465 四改 / #1373 / #1419）', () => {
  it('#1465 ① 类别默认全选 6/6（全选 == 显示全部）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    for (const t of CAT_TYPES) expect(catChecked(t), t).toBe(true);
    expect(dimmedNodeTestIds()).toEqual([]);
  });

  it('#1465 ③ 面板与画布等高 + 内部独立滚动区（两块各一）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    const panel = screen.getByTestId('library-kg-filter-panel');
    expect(panel.className).toMatch(/h-\[520px\]/);
    expect(screen.getByTestId('library-kg-canvas').className).toMatch(/h-\[520px\]/);
    expect(panel.querySelectorAll('.overflow-y-auto').length).toBeGreaterThanOrEqual(2);
  });

  it('#1465 ④ 折叠态：左侧竖条（DOM 先于画布）+ 竖排 + 明确展开入口', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    await user.click(screen.getByTestId('library-kg-filter-collapse'));
    await waitFor(() => expect(screen.getByTestId('library-kg-filterbar')).toBeInTheDocument());
    const rail = screen.getByTestId('library-kg-filterbar');
    const canvas = screen.getByTestId('library-kg-canvas');
    expect(rail.compareDocumentPosition(canvas) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(rail.className).toMatch(/flex-col/);
    expect(screen.getByTestId('library-kg-filterbar-expand').getAttribute('aria-label')).toBe('展开筛选');
  });

  it('#1373 N10 节点个体着色仍在（内联底色非空）', async () => {
    const user = userEvent.setup();
    await openGraph(user);
    expect(screen.getByTestId('library-kg-node-character-c1').getAttribute('style') ?? '').toMatch(/background-color/);
    expect(screen.getByTestId('library-kg-legend')).toBeInTheDocument();
  });

  it('#1419 N16 空态不渲染画布（筛选控件一并让位）', async () => {
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
    expect(screen.queryByTestId('library-kg-filter-panel')).toBeNull();
    expect(screen.queryByTestId('library-kg-entity-page')).toBeNull();
  });
});
