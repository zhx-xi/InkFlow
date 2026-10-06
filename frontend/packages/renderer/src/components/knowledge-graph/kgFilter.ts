/**
 * #1373 知识图谱「类别 / 实体筛选 + 本地记忆」纯函数
 * #1465：类别由「单选」改为「多选（默认全选）」——全选 = 显示全部，取消某类 = 隐藏该类。
 * 对应 specs/f19-gui/knowledge.md §4.2 + 验收 N11 / N12 / N13 / N15 / N18
 *
 * 语义：可见节点 = 已勾选类别 ∩ 实体邻接子图（该实体 + 一跳邻居）；保留边 = 两端均可见。
 * 记忆键 `inkflow:kg:filters[:<project_id>]`（值 `{categories, entity}` JSON；旧格式 `{category}` 兼容）
 * 与 `inkflow:kg:panel`（值 `'open' | 'closed'` 字符串），与画布位置记忆 `inkflow:kg:positions` 同构。
 * 存储不可用 / 记忆损坏一律静默回退默认（绝不抛错）。
 */
import type { EntityType, GraphEdge, GraphNode } from '../../api/knowledge-graph';

/** 筛选状态（类别多选 + 实体单选；两者同时生效时取交集） */
export interface KgFilterState {
  /** 已勾选的类别（#1465：默认全选；空数组 = 全不选 → 无可见节点） */
  categories: EntityType[];
  entity: string | null;
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

/** 默认筛选态：**六类全选** + 未选实体（#1465：全选 = 显示全部） */
export const DEFAULT_KG_FILTER: KgFilterState = { categories: [...KG_CATEGORIES], entity: null };

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

/** 校验任意来源的筛选值（localStorage / 旧版本 / 手改）：
 *  非法类别按上述规则收敛；传了 nodeIds 时丢弃不在当前图谱中的实体（防「选中了已不存在的实体」） */
export function sanitizeKgFilter(raw: unknown, nodeIds?: ReadonlySet<string>): KgFilterState {
  if (typeof raw !== 'object' || raw === null) return { ...DEFAULT_KG_FILTER };
  const record = raw as Record<string, unknown>;
  const categories = sanitizeCategories(record);
  let entity: string | null = typeof record.entity === 'string' ? record.entity : null;
  if (entity !== null && nodeIds !== undefined && !nodeIds.has(entity)) entity = null;
  return { categories, entity };
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
      JSON.stringify({ categories: filter.categories, entity: filter.entity }),
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

/** 一跳邻接集（含自身；边双向：source/target 任一端匹配 id 即取对端） */
export function adjacentOf(id: string, edges: GraphEdge[]): Set<string> {
  const ids = new Set<string>([id]);
  for (const edge of edges) {
    if (edge.source === id) ids.add(edge.target);
    else if (edge.target === id) ids.add(edge.source);
  }
  return ids;
}

/** 可见节点集 = 全部节点 → 类别过滤（节点 type ∈ 已勾选类别）→ 实体邻接过滤（entity 非空），取交集 */
export function computeVisibleIds(
  nodes: GraphNode[],
  edges: GraphEdge[],
  filter: KgFilterState,
): Set<string> {
  const adjacent = filter.entity !== null ? adjacentOf(filter.entity, edges) : null;
  const ids = new Set<string>();
  for (const node of nodes) {
    if (!filter.categories.includes(node.type)) continue;
    if (adjacent !== null && !adjacent.has(node.id)) continue;
    ids.add(node.id);
  }
  return ids;
}

/** 保留边：两端均在可见集中（保持原顺序；不修改入参） */
export function visibleEdges(edges: GraphEdge[], visibleIds: ReadonlySet<string>): GraphEdge[] {
  return edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target));
}
