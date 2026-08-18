/** F48 知识图谱 API 客户端（specs/f48-knowledge-graph/spec.md §3.1：图谱聚合 + 关系 CRUD，apiFetch 封装同 client.ts 模式） */
import { apiFetch } from './client';

/** 六类设定实体类型（spec §2.1 规则 1：与 library.tsx 六分类 tab 对齐，rag 除外） */
export type EntityType = 'character' | 'world' | 'outline' | 'timeline' | 'foreshadow' | 'map_pin';

/** 图谱节点（spec §2.4）：id="<entity_type>:<entity_uuid>"，entity_id 为实体表主键 */
export interface GraphNode {
  id: string;
  type: EntityType;
  entity_id: string;
  name: string;
}

/** 图谱边（spec §2.4）：id="kr:<uuid>"（knowledge_relations）或 "cr:<uuid>"（character_relations） */
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  description?: string;
  source_table: string;
}

/** 图谱聚合响应（spec §2.4/§3.1：GET /projects/{pid}/knowledge-graph） */
export interface KnowledgeGraphView {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

/** 关系行（spec §2.1/§2.3）：六元组 + description + source + 时间戳 */
export interface KnowledgeRelation {
  id: string;
  project_id: string;
  source_type: EntityType;
  source_id: string;
  target_type: EntityType;
  target_id: string;
  relation_type: string;
  description: string;
  source: 'manual' | 'ai';
  created_at: string;
  updated_at: string;
}

/** 创建关系请求体（spec §2.3 KnowledgeRelationCreate：六元组 + 可选描述） */
export interface KnowledgeRelationCreateInput {
  source_type: EntityType;
  source_id: string;
  target_type: EntityType;
  target_id: string;
  relation_type: string;
  description?: string;
}

/** 更新关系请求体（spec §2.3 KnowledgeRelationUpdate：全可选） */
export type KnowledgeRelationUpdateInput = Partial<KnowledgeRelationCreateInput>;

/** 关系列表查询参数（spec §3.1：source_type/target_type/relation_type/source 过滤） */
export interface KnowledgeRelationListParams {
  source_type?: EntityType;
  target_type?: EntityType;
  relation_type?: string;
  source?: 'manual' | 'ai';
}

/** 关系列表响应（spec §3.1：{items,total,offset,limit}） */
export interface KnowledgeRelationListResponse {
  items: KnowledgeRelation[];
  total: number;
  offset: number;
  limit: number;
}

/** GET /api/v1/projects/{pid}/knowledge-graph——图谱聚合查询（nodes+edges 一次返回，spec §5.4） */
export async function fetchKnowledgeGraph(projectId: string): Promise<KnowledgeGraphView> {
  return apiFetch<KnowledgeGraphView>(`/api/v1/projects/${projectId}/knowledge-graph`);
}

/** GET /api/v1/projects/{pid}/knowledge-relations——关系列表（分页 + 过滤） */
export async function listKnowledgeRelations(
  projectId: string,
  params?: KnowledgeRelationListParams,
): Promise<KnowledgeRelationListResponse> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== '') query.set(key, value);
  }
  const qs = query.toString();
  return apiFetch<KnowledgeRelationListResponse>(
    `/api/v1/projects/${projectId}/knowledge-relations${qs ? `?${qs}` : ''}`,
  );
}

/** POST /api/v1/projects/{pid}/knowledge-relations——创建关系（六元组 + description） */
export async function createKnowledgeRelation(
  projectId: string,
  body: KnowledgeRelationCreateInput,
): Promise<KnowledgeRelation> {
  return apiFetch<KnowledgeRelation>(`/api/v1/projects/${projectId}/knowledge-relations`, {
    method: 'POST',
    body,
  });
}

/** GET /api/v1/knowledge-relations/{id}——关系详情 */
export async function getKnowledgeRelation(id: string): Promise<KnowledgeRelation> {
  return apiFetch<KnowledgeRelation>(`/api/v1/knowledge-relations/${id}`);
}

/** PATCH /api/v1/knowledge-relations/{id}——更新关系（六元组可改 + description） */
export async function updateKnowledgeRelation(
  id: string,
  body: KnowledgeRelationUpdateInput,
): Promise<KnowledgeRelation> {
  return apiFetch<KnowledgeRelation>(`/api/v1/knowledge-relations/${id}`, { method: 'PATCH', body });
}

/** DELETE /api/v1/knowledge-relations/{id}——真删（spec §2.1 规则 7） */
export async function deleteKnowledgeRelation(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/knowledge-relations/${id}`, { method: 'DELETE' });
}
