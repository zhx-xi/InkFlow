/** F48 知识图谱 API 客户端（specs/f48-knowledge-graph/spec.md §3.1：图谱聚合 + 关系 CRUD，apiFetch 封装同 client.ts 模式） */
import { ApiError, apiFetch, getApiConfig, KernelOfflineError } from './client';

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

/** 图谱节点集范围（#1325）：related=参与至少一条关系者（无关系时后端回退角色全集）/ all=六类全量 */
export type GraphScope = 'related' | 'all';

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

/** 关系列表查询参数（spec §3.1：source_type/target_type/relation_type/source 过滤 + offset/limit 分页） */
export interface KnowledgeRelationListParams {
  source_type?: EntityType;
  target_type?: EntityType;
  relation_type?: string;
  source?: 'manual' | 'ai';
  /** 分页偏移（0 基；#1325 关系列表分页接线） */
  offset?: number;
  /** 每页条数（#1325；缺省由后端给默认值） */
  limit?: number;
}

/** 关系列表响应（spec §3.1：{items,total,offset,limit}） */
export interface KnowledgeRelationListResponse {
  items: KnowledgeRelation[];
  total: number;
  offset: number;
  limit: number;
}

/** GET /api/v1/projects/{pid}/knowledge-graph?scope=——图谱聚合查询（nodes+edges 一次返回，spec §5.4）
 *  #1325：scope 决定节点集（related 默认 / all 六类全量）。 */
export async function fetchKnowledgeGraph(
  projectId: string,
  scope: GraphScope = 'related',
): Promise<KnowledgeGraphView> {
  return apiFetch<KnowledgeGraphView>(
    `/api/v1/projects/${projectId}/knowledge-graph?scope=${scope}`,
  );
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

/** drawio 导入模式（spec §5.7.3）：merge=不删既有行 / replace=先清空再写入 */
export type KnowledgeGraphImportMode = 'merge' | 'replace';

/** 导入过程中被跳过 / 拒绝的一条边（spec §5.7.3 响应体 details 元素） */
export interface KnowledgeGraphImportIssue {
  kind: 'skipped' | 'failed';
  edge_id: string;
  label: string;
  reason: string;
}

/** 导入结果（spec §5.7.3；计数恒等式 total == imported + skipped + failed） */
export interface KnowledgeGraphImportResult {
  mode: KnowledgeGraphImportMode;
  total: number;
  imported: number;
  skipped: number;
  failed: number;
  deleted: number;
  details: KnowledgeGraphImportIssue[];
}

/** 解析 Content-Disposition 文件名：优先 RFC 5987 filename*（UTF-8 百分号解码），兼容 filename="..." */
function parseFilename(contentDisposition: string | null): string | null {
  if (!contentDisposition) return null;
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(contentDisposition);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      return null;
    }
  }
  const plain = /filename="([^"]+)"/i.exec(contentDisposition);
  if (plain) {
    try {
      return decodeURIComponent(plain[1]);
    } catch {
      return null;
    }
  }
  return null;
}

/** 导出 drawio：GET /api/v1/projects/{pid}/knowledge-graph/export?format=mxgraph（application/xml） */
export async function exportKnowledgeGraphFile(
  projectId: string,
): Promise<{ filename: string; content: string }> {
  const { baseURL, token } = getApiConfig();
  const headers = new Headers();
  if (token) headers.set('X-InkFlow-Token', token);
  const res = await fetch(
    `${baseURL}/api/v1/projects/${projectId}/knowledge-graph/export?format=mxgraph`,
    { headers },
  );
  if (res.status === 401) throw new KernelOfflineError();
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? detail);
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new ApiError(res.status, detail);
  }
  const content = await res.text();
  const filename = parseFilename(res.headers.get('Content-Disposition')) ?? 'knowledge-graph.drawio';
  return { filename, content };
}

/** 导入 drawio：POST /api/v1/projects/{pid}/knowledge-graph/import?mode=<mode>（原始 XML body） */
export async function importKnowledgeGraphFile(
  projectId: string,
  xml: string,
  mode: KnowledgeGraphImportMode,
): Promise<KnowledgeGraphImportResult> {
  const { baseURL, token } = getApiConfig();
  const headers = new Headers({ 'Content-Type': 'application/xml' });
  if (token) headers.set('X-InkFlow-Token', token);
  const res = await fetch(
    `${baseURL}/api/v1/projects/${projectId}/knowledge-graph/import?mode=${mode}`,
    { method: 'POST', headers, body: xml },
  );
  if (res.status === 401) throw new KernelOfflineError();
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? detail);
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as KnowledgeGraphImportResult;
}
