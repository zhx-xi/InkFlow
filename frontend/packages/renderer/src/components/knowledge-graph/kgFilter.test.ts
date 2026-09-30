/**
 * #1373 知识图谱「类别/实体筛选」RED 契约（unit 层，纯函数 + 记忆读写）
 * 对应 specs/f19-gui/knowledge.md §4.2（筛选语义）+ 验收 N11/N12/N13/N15
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【本次要证明的命题（一句话）】
 * 前端纯函数式筛选（可见节点 = 类别 ∩ 实体邻接子图；保留边 = 两端均可见）
 * 与「选择即本地记忆」（inkflow:kg:filters:<project_id> / inkflow:kg:panel）语义成立，
 * 且存储不可用 / 记忆损坏时静默回退默认（不抛错）。
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * 【拍板口径（2026-09-30，不得改方案）】
 * - 🔴 类别 = **单选**（点另一类替换；全不选 = 不做类别过滤）——
 *   specs/f19-gui/knowledge.md §2「类别行」/§4.2 与原型实现一致（非多选）
 * - 实体 = 单选（再点取消）→ 该实体 + 一跳邻居
 * - 两者取交集；零后端改动（对既有 graph 响应做前端过滤）
 * - 记忆键 `inkflow:kg:filters:<project_id>`（值 `{category, entity}`）
 *   + `inkflow:kg:panel`（`'open' | 'closed'`，与画布位置记忆同构）
 *
 * 【RED 预期】本文件在实现前必须真跑起来并 FAIL（非 collection error）：
 *   `kgFilter` 模块不存在 → 文件级 `Failed to resolve import "./kgFilter"`（1 个 Failed Suite）
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  DEFAULT_KG_FILTER,
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

const visible = (filter: KgFilterState): string[] => [...computeVisibleIds(NODES, EDGES, filter)].sort();

beforeEach(() => {
  localStorage.clear();
});

describe('#1373 筛选语义（前端纯函数，零后端改动）', () => {
  it('默认态 = 类别「全部」+ 未选实体（决策③）', () => {
    expect(DEFAULT_KG_FILTER).toEqual({ category: 'all', entity: null });
    expect(visible(DEFAULT_KG_FILTER)).toEqual(NODES.map((n) => n.id).sort());
  });

  it('N11 类别筛选：单选 → 只保留该 type 节点', () => {
    expect(visible({ category: 'character', entity: null })).toEqual([
      'character:c1',
      'character:c2',
      'character:c3',
    ]);
    expect(visible({ category: 'world', entity: null })).toEqual(['world:w1', 'world:w2']);
  });

  it('N12 实体筛选：邻接子图 = 该实体 + 一跳邻居', () => {
    // c1 的邻居：w1（kr:1）+ c2（kr:2）；c3 / w2 不可见
    expect(visible({ category: 'all', entity: 'character:c1' })).toEqual([
      'character:c1',
      'character:c2',
      'world:w1',
    ]);
    // 孤立视角：w2 只有 w1 一个邻居
    expect(visible({ category: 'all', entity: 'world:w2' })).toEqual(['world:w1', 'world:w2']);
  });

  it('N12 类别 ∩ 实体：两者同时生效时取交集', () => {
    // 实体邻接 = {c1, c2, w1}；类别 world → 交集 = {w1}
    expect(visible({ category: 'world', entity: 'character:c1' })).toEqual(['world:w1']);
    // 实体邻接 = {c1, c2, w1}；类别 character → 交集 = {c1, c2}
    expect(visible({ category: 'character', entity: 'character:c1' })).toEqual([
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
    const vis = computeVisibleIds(NODES, EDGES, { category: 'character', entity: null });
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
    computeVisibleIds(NODES, EDGES, { category: 'world', entity: 'character:c1' });
    visibleEdges(EDGES, new Set(['world:w1']));
    expect(NODES.map((n) => n.id)).toEqual(nodeIds);
    expect(EDGES.map((e) => e.id)).toEqual(edgeIds);
  });
});

describe('#1373 选择记忆（决策③：只在用户动作时写；损坏/不可用静默回退）', () => {
  it('N15 记忆键形态：`inkflow:kg:filters:<project_id>` 与 `inkflow:kg:panel`', () => {
    expect(KG_FILTERS_STORAGE_KEY).toBe('inkflow:kg:filters');
    expect(KG_PANEL_STORAGE_KEY).toBe('inkflow:kg:panel');
    expect(kgFiltersKey('p1')).toBe('inkflow:kg:filters:p1');
    // 无 project_id 时退化为基键（与画布位置记忆同构）
    expect(kgFiltersKey(undefined)).toBe('inkflow:kg:filters');
  });

  it('N15 读写往返：写入后在 `<基键>:<pid>` 上可读回，且与其它项目隔离', () => {
    writeKgFilter('p1', { category: 'character', entity: 'character:c1' });
    expect(localStorage.getItem('inkflow:kg:filters:p1')).toContain('character:c1');
    expect(readKgFilter('p1')).toEqual({ category: 'character', entity: 'character:c1' });
    // 另一个项目读不到本项目记忆
    expect(readKgFilter('p2')).toEqual(DEFAULT_KG_FILTER);
  });

  it('N15 无记忆 = 默认（类别「全部」+ 面板展开）', () => {
    expect(readKgFilter('p1')).toEqual(DEFAULT_KG_FILTER);
    expect(readKgPanel()).toBeNull();
  });

  it('N15 记忆损坏 / 存储不可用 → 静默回退默认，不抛错', () => {
    localStorage.setItem('inkflow:kg:filters:p1', 'not-json{{{');
    expect(() => readKgFilter('p1')).not.toThrow();
    expect(readKgFilter('p1')).toEqual(DEFAULT_KG_FILTER);

    localStorage.setItem('inkflow:kg:panel', 'weird-value');
    expect(() => readKgPanel()).not.toThrow();
    expect(readKgPanel()).toBeNull();
  });

  it('N15 记忆值校验：非法类别回「全部」；已不存在的实体回 null（防幽灵选中）', () => {
    expect(sanitizeKgFilter({ category: '不存在的类别', entity: null })).toEqual(DEFAULT_KG_FILTER);
    expect(sanitizeKgFilter(null)).toEqual(DEFAULT_KG_FILTER);
    expect(sanitizeKgFilter('字符串')).toEqual(DEFAULT_KG_FILTER);
    expect(sanitizeKgFilter({ category: 'world', entity: 'character:c1' })).toEqual({
      category: 'world',
      entity: 'character:c1',
    });
    // 实体不在当前图谱中 → 丢弃（否则会出现「选中了不存在的实体」）
    expect(
      sanitizeKgFilter({ category: 'world', entity: 'character:c9' }, new Set(['world:w1'])),
    ).toEqual({ category: 'world', entity: null });
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
