/**
 * #1373 知识图谱「类别/实体筛选」纯函数契约（unit 层，纯函数 + 记忆读写）
 * #1465：类别由「单选」改为「**多选（默认全选）**」——全选 = 显示全部，取消某类 = 隐藏该类。
 * #1529（W8g）：**① 实体同步改为多选集合（默认全选）**；**② 未勾选 = 灰显而非摘除**（画布保留全部节点）；
 *                 **③ 邻接子图语义退休**（不再「选中一个实体 = 该实体 + 一跳邻居」）。
 * 对应 specs/f19-gui/knowledge.md §4.2（筛选语义）+ 验收 N11/N12/N15/N18/N19
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【拍板口径（#1529，2026-10-08 用户）】
 * - 🔴 实体 = **多选集合、默认全选**（`entities: string[] | null`；`null` = 全选）
 * - 🔴 未勾选 = **统一灰显**（节点与边都保留在画布上）→ `computeVisibleIds` 返回的是
 *      **「高亮（正常彩色）节点集」**，不再摘除任何节点（`visibleEdges` 已删除——边由画布按两端是否高亮自行降灰）
 * - 🔴 邻接子图退休：选中单个实体**不再**把一跳邻居带进来
 * - 记忆键 `inkflow:kg:filters:<project_id>`（值 `{categories, entities}`）
 *   + `inkflow:kg:panel`（`'open' | 'closed'`）；旧格式 `{category}` / `{entity}` 向后兼容
 * - 零后端改动（对既有 graph 响应做前端高亮/灰显）
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  DEFAULT_KG_FILTER,
  KG_CATEGORIES,
  KG_FILTERS_STORAGE_KEY,
  KG_PANEL_STORAGE_KEY,
  computeHiddenIds,
  computeVisibleIds,
  kgFiltersKey,
  readKgFilter,
  readKgPanel,
  sanitizeKgFilter,
  writeKgFilter,
  writeKgPanel,
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
/** 高亮（正常彩色）节点集 */
const active = (filter: { categories: typeof ALL; entities: string[] | null }): string[] =>
  [...computeVisibleIds(NODES, EDGES, filter)].sort();
const allNodeIds = (): string[] => NODES.map((n) => n.id).sort();

beforeEach(() => {
  localStorage.clear();
});

describe('#1529 实体多选（默认全选）——与类别语义统一', () => {
  it('默认态 = 六类全选 + 实体全选（`entities: null`）→ 全部节点高亮', () => {
    expect(DEFAULT_KG_FILTER).toEqual({ categories: ALL, entities: null });
    expect(active(DEFAULT_KG_FILTER)).toEqual(allNodeIds());
  });

  it('N19① 负例守护：全选 == 显示全部（无任何灰显）', () => {
    expect(active({ categories: [...ALL], entities: null })).toEqual(allNodeIds());
  });

  it('N19① 取消某实体 → 该实体不再高亮，其余照常（`entities` = 高亮白名单，非黑名单）', () => {
    expect(active({ categories: [...ALL], entities: ['character:c2', 'character:c3', 'world:w1', 'world:w2'] })).toEqual(
      ['character:c2', 'character:c3', 'world:w1', 'world:w2'],
    );
  });

  it('N19① 实体集合为空 → 无高亮节点（合法态，画布走筛选空态）', () => {
    expect(active({ categories: [...ALL], entities: [] })).toEqual([]);
  });

  it('🔴 邻接子图退休：只勾一个实体 → **只它高亮**（不再带一跳邻居 c2 / w1）', () => {
    expect(active({ categories: [...ALL], entities: ['character:c1'] })).toEqual(['character:c1']);
    expect(active({ categories: [...ALL], entities: ['world:w2'] })).toEqual(['world:w2']);
  });

  it('N12 类别 ∩ 实体：两者同时生效时取交集', () => {
    expect(active({ categories: ['world'], entities: ['character:c1', 'world:w1'] })).toEqual(['world:w1']);
    expect(active({ categories: ['character'], entities: ['character:c1', 'character:c2', 'world:w1'] })).toEqual([
      'character:c1',
      'character:c2',
    ]);
  });

  it('N11 类别多选：取消某类 → 该类节点不再高亮，其余保留（多选非替换）', () => {
    expect(active({ categories: ALL.filter((t) => t !== 'character'), entities: null })).toEqual(['world:w1', 'world:w2']);
  });

  it('筛选不修改入参（纯函数：不就地排序/删除调用方数组）', () => {
    const nodeIds = NODES.map((n) => n.id);
    const edgeIds = EDGES.map((e) => e.id);
    computeVisibleIds(NODES, EDGES, { categories: ['world'], entities: ['character:c1'] });
    expect(NODES.map((n) => n.id)).toEqual(nodeIds);
    expect(EDGES.map((e) => e.id)).toEqual(edgeIds);
  });
});

describe('#1529 选择记忆（新格式 + 旧格式向后兼容）', () => {
  it('N15 记忆键形态：`inkflow:kg:filters:<project_id>` 与 `inkflow:kg:panel`', () => {
    expect(KG_FILTERS_STORAGE_KEY).toBe('inkflow:kg:filters');
    expect(KG_PANEL_STORAGE_KEY).toBe('inkflow:kg:panel');
    expect(kgFiltersKey('p1')).toBe('inkflow:kg:filters:p1');
    expect(kgFiltersKey(undefined)).toBe('inkflow:kg:filters');
  });

  it('N15 读写往返：写入 categories + entities 后可读回，且与其它项目隔离', () => {
    writeKgFilter('p1', { categories: ['character'], entities: ['character:c1'] });
    expect(localStorage.getItem('inkflow:kg:filters:p1')).toContain('"entities"');
    expect(readKgFilter('p1')).toEqual({ categories: ['character'], entities: ['character:c1'] });
    expect(readKgFilter('p2')).toEqual(DEFAULT_KG_FILTER);
  });

  it('N15 无记忆 = 默认（六类全选 + 实体全选 + 面板展开）', () => {
    expect(readKgFilter('p1')).toEqual(DEFAULT_KG_FILTER);
    expect(readKgPanel()).toBeNull();
  });

  it('N19 新格式：`entities: null` = 全选；数组 = 只勾这些', () => {
    expect(sanitizeKgFilter({ categories: ['world'], entities: null })).toEqual({ categories: ['world'], entities: null });
    expect(sanitizeKgFilter({ categories: ['world'], entities: ['world:w1'] })).toEqual({
      categories: ['world'],
      entities: ['world:w1'],
    });
    expect(sanitizeKgFilter({ categories: ['world'], entities: [] })).toEqual({ categories: ['world'], entities: [] });
  });

  it('N18 旧格式（#1373 单选 `category`）兼容：具体类 → 只勾该类；all → 全选', () => {
    expect(sanitizeKgFilter({ category: 'character', entity: null })).toEqual({ categories: ['character'], entities: null });
    expect(sanitizeKgFilter({ category: 'all', entity: null })).toEqual({ categories: ALL, entities: null });
  });

  it('N19 旧格式 `entity`（单选）兼容为「只勾该实体」', () => {
    expect(sanitizeKgFilter({ categories: ALL, entity: 'character:c1' })).toEqual({
      categories: ALL,
      entities: ['character:c1'],
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

  it('N19 记忆值校验：非法类别回全选；已不存在的实体被丢弃（防幽灵选中）', () => {
    expect(sanitizeKgFilter({ categories: ['不存在的类别'] })).toEqual({ categories: [], entities: null });
    expect(sanitizeKgFilter(null)).toEqual(DEFAULT_KG_FILTER);
    expect(sanitizeKgFilter('字符串')).toEqual(DEFAULT_KG_FILTER);
    expect(sanitizeKgFilter({ category: '不存在的类别' })).toEqual(DEFAULT_KG_FILTER);
    // 传入当前图谱节点集 → 幽灵实体被丢弃；**全被丢弃 = 回退全选**（不出现「选中了不存在的实体」）
    expect(sanitizeKgFilter({ categories: ['world'], entities: ['character:c9'] }, new Set(['world:w1']))).toEqual({
      categories: ['world'],
      entities: null,
    });
    // 部分幽灵 → 只保留仍存在的；**收敛后恰好覆盖全集 → 塌缩为全选**（「实体 n/n」假筛选态不许出现）
    expect(
      sanitizeKgFilter({ categories: ['world'], entities: ['world:w1', 'character:c9'] }, new Set(['world:w1'])),
    ).toEqual({ categories: ['world'], entities: null });
    expect(
      sanitizeKgFilter(
        { categories: ['world'], entities: ['world:w1'] },
        new Set(['world:w1', 'world:w2']),
      ),
    ).toEqual({ categories: ['world'], entities: ['world:w1'] });
    // 数组 = 全集 → 塌缩为 null（全选）
    expect(sanitizeKgFilter({ categories: ALL, entities: ['character:c1', 'character:c2'] }, new Set(['character:c1', 'character:c2']))).toEqual({
      categories: ALL,
      entities: null,
    });
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

/**
 * #1568（0.17.0 rc2）：实体定向**三态**的「隐藏」集 —— **部分收窄 #1529 的「一律降灰、不隐藏」**。
 * 语义：仅 `entities !== null`（实体定向激活）时启用；类别外节点**永不隐藏**（类别路不回归）。
 */
describe('#1568 computeHiddenIds 实体定向三态', () => {
  it('实体全选（`entities === null`）→ 无隐藏（保持 #1529 二态）', () => {
    expect([...computeHiddenIds(NODES, EDGES, { categories: [...ALL], entities: null })]).toEqual([]);
  });

  it('选中 1 个实体 → 隐藏「既未选中也不相连」者；相连者不隐藏', () => {
    // c1 的邻居 = c2（同门）/ w1（属于）→ 二者不隐藏；c3 / w2 隐藏
    expect(
      [...computeHiddenIds(NODES, EDGES, { categories: [...ALL], entities: ['character:c1'] })].sort(),
    ).toEqual(['character:c3', 'world:w2']);
  });

  it('多选（≥2）按**并集邻居**处理', () => {
    // 选中 c1 + w2 → 并集邻居 = {c2, w1}；仅 c3 隐藏
    expect(
      [...computeHiddenIds(NODES, EDGES, { categories: [...ALL], entities: ['character:c1', 'world:w2'] })].sort(),
    ).toEqual(['character:c3']);
  });

  it('🔴 类别外节点**永不隐藏**（类别路维持「不摘除、只降灰」）', () => {
    // 类别只留 character；选中 c1 → w1 / w2 属类别外 → 只降灰、不隐藏
    expect([
      ...computeHiddenIds(NODES, EDGES, { categories: ['character'], entities: ['character:c1'] }),
    ]).toEqual(['character:c3']);
  });

  it('空选（`entities: []`）→ 全部隐藏（「全部取消」的实体侧效果）', () => {
    expect([
      ...computeHiddenIds(NODES, EDGES, { categories: [...ALL], entities: [] }),
    ].sort()).toEqual(NODES.map((n) => n.id).sort());
  });

  it('纯函数：不修改入参', () => {
    const ids = NODES.map((n) => n.id);
    computeHiddenIds(NODES, EDGES, { categories: [...ALL], entities: ['character:c1'] });
    expect(NODES.map((n) => n.id)).toEqual(ids);
  });
});
