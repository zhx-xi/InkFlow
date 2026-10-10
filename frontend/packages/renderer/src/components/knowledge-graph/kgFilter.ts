/**
 * #1373 知识图谱「类别 / 实体筛选 + 本地记忆」纯函数
 * #1465：类别由「单选」改为「多选（默认全选）」——全选 = 显示全部，取消某类 = 隐藏该类。
 * #1529（W8g）：① 实体同步改为**多选集合（默认全选）**；② **未勾选 = 灰显而非摘除**
 *               （画布保留全部节点/边）；③ **邻接子图语义退休**（`adjacentOf` / `visibleEdges` 已删除）。
 * 对应 specs/f19-gui/knowledge.md §4.2 + 验收 N11 / N12 / N15 / N18 / N19
 *
 * 语义：**高亮（正常彩色）节点集 = 已勾选类别 ∩ 已勾选实体**（`entities === null` = 全选）；
 *      画布不再摘除任何节点/边，未高亮者由画布自行降灰（`data-dim="1"`）。
 * 记忆键 `inkflow:kg:filters[:<project_id>]`（值 `{categories, entities}` JSON；旧格式 `{category}` / `{entity}` 兼容）
 * 与 `inkflow:kg:panel`（值 `'open' | 'closed'` 字符串），与画布位置记忆 `inkflow:kg:positions` 同构。
 * 存储不可用 / 记忆损坏一律静默回退默认（绝不抛错）。
 */
import type { EntityType, GraphEdge, GraphNode } from '../../api/knowledge-graph';

/** 筛选状态（类别多选 + 实体多选集合；两者同时生效时取交集） */
export interface KgFilterState {
  /** 已勾选的类别（#1465：默认全选；空数组 = 全不选 → 无高亮节点） */
  categories: EntityType[];
  /** 已勾选的实体 id 集合（#1529：默认全选 = `null`；空数组 = 全不选，合法态） */
  entities: string[] | null;
}

/** 筛选记忆基键（带 project_id 时以 `:<project_id>` 后缀隔离） */
export const KG_FILTERS_STORAGE_KEY = 'inkflow:kg:filters';

/** 筛选面板开合记忆键（值 `'open' / 'closed'`，非 JSON） */
export const KG_PANEL_STORAGE_KEY = 'inkflow:kg:panel';

/** 六类实体（与 specs/f48-knowledge-graph/spec.md §2.1 规则 1 对齐；顺序即面板展示顺序） */
export const KG_CATEGORIES: EntityType[] = [
  'character',
  'world',
  'outline',
  'timeline',
  'foreshadow',
  'map_pin',
];

/** 默认筛选态：**六类全选** + **实体全选**（#1529：全选 = 显示全部 = 无任何灰显） */
export const DEFAULT_KG_FILTER: KgFilterState = { categories: [...KG_CATEGORIES], entities: null };

/** 实体名排序器（#1529：中文按拼音序；模块级常量，避免每次比较重建） */
const ENTITY_NAME_COLLATOR = new Intl.Collator('zh');

/** 实体名排序（#1529，纯函数：返回**新数组**，不修改入参） */
export function sortByEntityName(nodes: GraphNode[]): GraphNode[] {
  return [...nodes].sort((a, b) => ENTITY_NAME_COLLATOR.compare(a.name, b.name));
}

/** 筛选记忆键：有 project_id → `<基键>:<project_id>`，否则退化基键 */
export function kgFiltersKey(projectId?: string): string {
  return projectId ? `${KG_FILTERS_STORAGE_KEY}:${projectId}` : KG_FILTERS_STORAGE_KEY;
}

const isEntityType = (v: unknown): v is EntityType =>
  typeof v === 'string' && (KG_CATEGORIES as readonly string[]).includes(v);

/** 类别解析：新格式 `categories: string[]` 优先（空数组 = 全不选，合法态）；
 *  旧格式 `category`（#1373 单选）兼容为「只勾该类」；其余（非法 / 缺失 / `'all'`）→ 全选 */
function sanitizeCategories(record: Record<string, unknown>): EntityType[] {
  if (Array.isArray(record.categories)) return record.categories.filter(isEntityType);
  if (isEntityType(record.category)) return [record.category];
  return [...KG_CATEGORIES];
}

/** 实体解析：新格式 `entities: string[]` 优先（**保序、丢弃非字符串**；空数组 = 全不选，合法态）；
 *  旧格式 `entity`（#1373 单选）兼容为「只勾该实体」；其余（非法 / 缺失）→ 全选（`null`）。
 *  传了 nodeIds 时丢弃当前图谱中已不存在的实体：**全被丢弃 = 回退全选**、**等于全集 = 塌缩为全选** */
function sanitizeEntities(
  record: Record<string, unknown>,
  nodeIds?: ReadonlySet<string>,
): string[] | null {
  let entities: string[] | null;
  if (Array.isArray(record.entities)) {
    entities = record.entities.filter((v): v is string => typeof v === 'string');
  } else if (typeof record.entity === 'string') {
    entities = [record.entity];
  } else {
    entities = null;
  }
  if (entities === null || nodeIds === undefined) return entities;
  const kept = entities.filter((id) => nodeIds.has(id));
  if (entities.length > 0 && kept.length === 0) return null;
  // 收敛后覆盖全集 → 塌缩为 `null`（全选同义，避免「实体 n/n」假筛选态）
  if (kept.length === nodeIds.size) return null;
  return kept;
}

/** 校验任意来源的筛选值（localStorage / 旧版本 / 手改）：
 *  非法类别按上述规则收敛；传了 nodeIds 时丢弃不在当前图谱中的实体（防「选中了已不存在的实体」） */
export function sanitizeKgFilter(raw: unknown, nodeIds?: ReadonlySet<string>): KgFilterState {
  if (typeof raw !== 'object' || raw === null) return { ...DEFAULT_KG_FILTER };
  const record = raw as Record<string, unknown>;
  const categories = sanitizeCategories(record);
  const entities = sanitizeEntities(record, nodeIds);
  return { categories, entities };
}

/** 节点集变化后收敛实体选择（与 sanitize 同套幽灵规则）；**无变化时返回原引用**
 *  供 React effect 调用：同一引用 = 无谓重渲染为零（#1529） */
export function reconcileKgFilter(filter: KgFilterState, nodeIds: ReadonlySet<string>): KgFilterState {
  const { entities } = filter;
  if (entities === null) return filter;
  const kept = entities.filter((id) => nodeIds.has(id));
  if ((entities.length > 0 && kept.length === 0) || kept.length === nodeIds.size) {
    return { categories: filter.categories, entities: null };
  }
  if (kept.length === entities.length) return filter;
  return { categories: filter.categories, entities: kept };
}

/** 读筛选记忆：无值 / JSON 损坏 / localStorage 不存在 / 抛异常 → 默认态（绝不抛错） */
export function readKgFilter(projectId?: string, nodeIds?: ReadonlySet<string>): KgFilterState {
  if (typeof localStorage === 'undefined') return { ...DEFAULT_KG_FILTER };
  try {
    const raw = localStorage.getItem(kgFiltersKey(projectId));
    if (raw === null) return { ...DEFAULT_KG_FILTER };
    return sanitizeKgFilter(JSON.parse(raw) as unknown, nodeIds);
  } catch {
    return { ...DEFAULT_KG_FILTER };
  }
}

/** 写筛选记忆（仅用户动作时调用）：配额 / 隐私模式等异常静默降级 */
export function writeKgFilter(projectId: string | undefined, filter: KgFilterState): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(
      kgFiltersKey(projectId),
      JSON.stringify({ categories: filter.categories, entities: filter.entities }),
    );
  } catch {
    /* 存储不可用：静默降级为会话内筛选 */
  }
}

/** 读面板开合记忆：`'open'` → true / `'closed'` → false / 其余（含无值、抛错）→ null */
export function readKgPanel(): boolean | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    const raw = localStorage.getItem(KG_PANEL_STORAGE_KEY);
    if (raw === 'open') return true;
    if (raw === 'closed') return false;
    return null;
  } catch {
    return null;
  }
}

/** 写面板开合记忆（字符串 `'open' / 'closed'`，非 JSON）：异常静默降级 */
export function writeKgPanel(open: boolean): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(KG_PANEL_STORAGE_KEY, open ? 'open' : 'closed');
  } catch {
    /* 存储不可用：静默降级为会话内状态 */
  }
}

/** 高亮（正常彩色）节点集（#1529）= 全部节点 → 类别过滤（节点 type ∈ 已勾选类别）
 *  → 实体过滤（`entities` 非 null 时须在集合内），取交集。
 *  返回**新增 Set**、不修改入参；`_edges` 仅为保留既有 3 参签名（#1529 起不再参与筛选）。 */
export function computeVisibleIds(
  nodes: GraphNode[],
  _edges: GraphEdge[],
  filter: KgFilterState,
): Set<string> {
  const picked = filter.entities === null ? null : new Set(filter.entities);
  const ids = new Set<string>();
  for (const node of nodes) {
    if (!filter.categories.includes(node.type)) continue;
    if (picked !== null && !picked.has(node.id)) continue;
    ids.add(node.id);
  }
  return ids;
}

/** #1568：实体定向「隐藏」节点集 —— **部分收窄 #1529 的「一律降灰、不隐藏」**（仅实体定向这一路）。
 *  仅在**实体定向激活**（`entities !== null`）时启用三态；`null`（全选）→ 空集（保持 #1529 二态）。
 *    · 彩色 = `computeVisibleIds`（已勾选类别 ∩ 已勾选实体）
 *    · 灰显保位 = 与高亮集**相连**（无向，邻接来自 edges）但未高亮者
 *    · 隐藏 = 其余；🔴 **类别外节点除外** —— 类别路维持「不摘除、只降灰」（spec §4.2 / N21）
 *  返回**新增 Set**、不修改入参。边由画布按「任一端被隐藏 → 不画」处理。 */
export function computeHiddenIds(
  nodes: GraphNode[],
  edges: GraphEdge[],
  filter: KgFilterState,
): Set<string> {
  const hidden = new Set<string>();
  if (filter.entities === null) return hidden;
  const active = computeVisibleIds(nodes, edges, filter);
  const adjacent = new Set<string>();
  for (const e of edges) {
    if (active.has(e.source)) adjacent.add(e.target);
    if (active.has(e.target)) adjacent.add(e.source);
  }
  for (const n of nodes) {
    if (active.has(n.id) || adjacent.has(n.id)) continue;
    if (!filter.categories.includes(n.type)) continue;
    hidden.add(n.id);
  }
  return hidden;
}
