/**
 * #1373 知识图谱「类别/实体筛选」纯函数契约（unit 层，纯函数 + 记忆读写）
 * #1465：类别由「单选」改为「**多选（默认全选）**」——全选 = 显示全部，取消某类 = 隐藏该类。
 * 对应 specs/f19-gui/knowledge.md §4.2（筛选语义）+ 验收 N11/N12/N13/N15/N18
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【拍板口径（#1465，2026-10-07）】
 * - 🔴 类别 = **多选、默认全选**（`categories: EntityType[]`；全选 == 显示全部）
 * - 实体 = 单选（再点取消）→ 该实体 + 一跳邻居；与类别取交集
 * - 记忆键 `inkflow:kg:filters:<project_id>`（值 `{categories, entity}`）
 *   + `inkflow:kg:panel`（`'open' | 'closed'`）；**旧格式 `{category}` 兼容为「只勾该类」**
 * - 零后端改动（对既有 graph 响应做前端过滤）
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  DEFAULT_KG_FILTER,
  KG_CATEGORIES,
  KG_FILTERS_STORAGE_KEY,
  KG_PANEL_STORAGE_KEY,
  adjacentOf,
  computeVisibleIds,
  kgFiltersKey,
  readKgFilter,
  readKgPanel,
  sanitizeKgFilter,
  visibleEdges,
  writeKgFilter,
  writeKgPanel,
  type KgFilterState,
} from './kgFilter';
import type { GraphEdge, GraphNode } from '../../api/knowledge-graph';

const NODES: GraphNode[] = [
  { id: 'character:c1', type: 'character', entity_id: 'c1', name: '林尘' },
  { id: 'character:c2', type: 'character', entity_id: 'c2', name: '阿澈' },
  { id: 'character:c3', type: 'character', entity_id: 'c3', name: '白丁' },
  { id: 'world:w1', type: 'world', entity_id: 'w1', name: '清河县' },
  { id: 'world:w2', type: 'world', entity_id: 'w2', name: '断崖' },
];

const EDGES: GraphEdge[] = [
  { id: 'kr:1', source: 'character:c1', target: 'world:w1', label: '属于', source_table: 'knowledge_relations' },
  { id: 'kr:2', source: 'character:c2', target: 'character:c1', label: '同门', source_table: 'knowledge_relations' },
  { id: 'kr:3', source: 'world:w2', target: 'world:w1', label: '相邻', source_table: 'knowledge_relations' },
];

const ALL = [...KG_CATEGORIES];
const visible = (filter: KgFilterState): string[] => [...computeVisibleIds(NODES, EDGES, filter)].sort();
const allNodeIds = (): string[] => NODES.map((n) => n.id).sort();

beforeEach(() => {
  localStorage.clear();
});

describe('#1465 类别多选（默认全选）', () => {
  it('默认态 = 六类全选 + 未选实体 → 显示全部', () => {
    expect(DEFAULT_KG_FILTER).toEqual({ categories: ALL, entity: null });
    expect(visible(DEFAULT_KG_FILTER)).toEqual(allNodeIds());
  });

  it('N18① 负例守护：全选 == 显示全部', () => {
    expect(visible({ categories: [...ALL], entity: null })).toEqual(allNodeIds());
  });

  it('N11 取消某类 → 该类节点隐藏，其余保留（多选非替换）', () => {
    expect(visible({ categories: ALL.filter((t) => t !== 'character'), entity: null })).toEqual([
      'world:w1',
      'world:w2',
    ]);
    expect(visible({ categories: ['character'], entity: null })).toEqual([
      'character:c1',
      'character:c2',
      'character:c3',
    ]);
  });

  it('类别全部取消 → 无可见节点（合法态，画布走筛选空态）', () => {
    expect(visible({ categories: [], entity: null })).toEqual([]);
  });

  it('N12 实体筛选：邻接子图 = 该实体 + 一跳邻居', () => {
    expect(visible({ categories: [...ALL], entity: 'character:c1' })).toEqual([
      'character:c1',
      'character:c2',
      'world:w1',
    ]);
    // 孤立视角：w2 只有 w1 一个邻居
    expect(visible({ categories: [...ALL], entity: 'world:w2' })).toEqual(['world:w1', 'world:w2']);
  });

  it('N12 类别 ∩ 实体：两者同时生效时取交集', () => {
    // 实体邻接 = {c1, c2, w1}；类别 world → 交集 = {w1}
    expect(visible({ categories: ['world'], entity: 'character:c1' })).toEqual(['world:w1']);
    // 实体邻接 = {c1, c2, w1}；类别 character → 交集 = {c1, c2}
    expect(visible({ categories: ['character'], entity: 'character:c1' })).toEqual([
      'character:c1',
      'character:c2',
    ]);
  });

  it('adjacentOf：含自身 + 双向一跳邻居', () => {
    expect([...adjacentOf('character:c1', EDGES)].sort()).toEqual([
      'character:c1',
      'character:c2',
      'world:w1',
    ]);
    expect([...adjacentOf('character:c3', EDGES)]).toEqual(['character:c3']);
  });

  it('保留边 = 两端节点均可见（任一端被过滤掉 → 边不保留）', () => {
    const vis = computeVisibleIds(NODES, EDGES, { categories: ['character'], entity: null });
    const kept = visibleEdges(EDGES, vis).map((e) => e.id);
    // kr:1 两端 c1(可见)/w1(不可见) → 丢弃；kr:2 两端均角色 → 保留
    expect(kept).toEqual(['kr:2']);
    // 全量时边一条不少
    const all = computeVisibleIds(NODES, EDGES, DEFAULT_KG_FILTER);
    expect(visibleEdges(EDGES, all)).toHaveLength(EDGES.length);
  });

  it('筛选不修改入参（纯函数：不就地排序/删除调用方数组）', () => {
    const nodeIds = NODES.map((n) => n.id);
    const edgeIds = EDGES.map((e) => e.id);
    computeVisibleIds(NODES, EDGES, { categories: ['world'], entity: 'character:c1' });
    visibleEdges(EDGES, new Set(['world:w1']));
    expect(NODES.map((n) => n.id)).toEqual(nodeIds);
    expect(EDGES.map((e) => e.id)).toEqual(edgeIds);
  });
});

describe('#1465 选择记忆（新格式 + 旧格式向后兼容）', () => {
  it('N15 记忆键形态：`inkflow:kg:filters:<project_id>` 与 `inkflow:kg:panel`', () => {
    expect(KG_FILTERS_STORAGE_KEY).toBe('inkflow:kg:filters');
    expect(KG_PANEL_STORAGE_KEY).toBe('inkflow:kg:panel');
    expect(kgFiltersKey('p1')).toBe('inkflow:kg:filters:p1');
    // 无 project_id 时退化为基键（与画布位置记忆同构）
    expect(kgFiltersKey(undefined)).toBe('inkflow:kg:filters');
  });

  it('N15 读写往返：写入 categories 后在 `<基键>:<pid>` 上可读回，且与其它项目隔离', () => {
    writeKgFilter('p1', { categories: ['character'], entity: 'character:c1' });
    expect(localStorage.getItem('inkflow:kg:filters:p1')).toContain('"categories"');
    expect(readKgFilter('p1')).toEqual({ categories: ['character'], entity: 'character:c1' });
    // 另一个项目读不到本项目记忆
    expect(readKgFilter('p2')).toEqual(DEFAULT_KG_FILTER);
  });

  it('N15 无记忆 = 默认（六类全选 + 面板展开）', () => {
    expect(readKgFilter('p1')).toEqual(DEFAULT_KG_FILTER);
    expect(readKgPanel()).toBeNull();
  });

  it('N18 旧格式（#1373 单选 `category`）兼容：具体类 → 只勾该类；all → 全选', () => {
    expect(sanitizeKgFilter({ category: 'character', entity: null })).toEqual({
      categories: ['character'],
      entity: null,
    });
    expect(sanitizeKgFilter({ category: 'all', entity: null })).toEqual({
      categories: ALL,
      entity: null,
    });
  });

  it('N15 记忆损坏 / 存储不可用 → 静默回退默认，不抛错', () => {
    localStorage.setItem('inkflow:kg:filters:p1', 'not-json{{{');
    expect(() => readKgFilter('p1')).not.toThrow();
    expect(readKgFilter('p1')).toEqual(DEFAULT_KG_FILTER);

    localStorage.setItem('inkflow:kg:panel', 'weird-value');
    expect(() => readKgPanel()).not.toThrow();
    expect(readKgPanel()).toBeNull();
  });

  it('N15 记忆值校验：非法类别回全选；已不存在的实体回 null（防幽灵选中）', () => {
    expect(sanitizeKgFilter({ categories: ['不存在的类别'] })).toEqual({
      categories: [],
      entity: null,
    });
    expect(sanitizeKgFilter(null)).toEqual(DEFAULT_KG_FILTER);
    expect(sanitizeKgFilter('字符串')).toEqual(DEFAULT_KG_FILTER);
    expect(sanitizeKgFilter({ category: '不存在的类别' })).toEqual(DEFAULT_KG_FILTER);
    expect(sanitizeKgFilter({ categories: ['world'], entity: 'character:c1' })).toEqual({
      categories: ['world'],
      entity: 'character:c1',
    });
    // 实体不在当前图谱中 → 丢弃（否则会出现「选中了不存在的实体」）
    expect(
      sanitizeKgFilter({ categories: ['world'], entity: 'character:c9' }, new Set(['world:w1'])),
    ).toEqual({ categories: ['world'], entity: null });
  });

  it('N15 面板开合记忆：open/closed 往返', () => {
    writeKgPanel(true);
    expect(localStorage.getItem('inkflow:kg:panel')).toBe('open');
    expect(readKgPanel()).toBe(true);
    writeKgPanel(false);
    expect(localStorage.getItem('inkflow:kg:panel')).toBe('closed');
    expect(readKgPanel()).toBe(false);
  });
});
