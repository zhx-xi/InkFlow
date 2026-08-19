/**
 * #480 检索页（Issue #480 RAG embedding 增强检索）：GET /api/v1/search 客户端契约。
 * 复用 apiFetch 统一错误映射（ApiError / KernelOfflineError），不重新实现 fetch。
 */
import { apiFetch } from './client';

/** 单条检索命中（对齐后端 GET /api/v1/search hit） */
export interface SearchHitDto {
  entity_type: string;
  entity_id: string;
  project_id: string;
  title: string;
  snippet: string;
  score: number;
}

/** 检索响应（对齐后端 GET /api/v1/search） */
export interface SearchResponseDto {
  total: number;
  hits: SearchHitDto[];
  query: string;
  types: string[] | null;
  mode: 'keyword' | 'semantic';
  project_ids: string[];
}

/** 检索参数（mode 缺省 → 'semantic'，本轨拍板默认语义检索；limit/offset 缺省不携带，后端默认 20/0） */
export interface SearchParams {
  q: string;
  projectId: string;
  mode?: 'keyword' | 'semantic';
  types?: string[];
  limit?: number;
  offset?: number;
}

/** 检索：GET /api/v1/search（q / project_id / mode / types 逗号分隔 / limit / offset） */
export async function fetchSearch(params: SearchParams): Promise<SearchResponseDto> {
  const qs = new URLSearchParams({
    q: params.q,
    project_id: params.projectId,
    mode: params.mode ?? 'semantic',
  });
  if (params.types && params.types.length > 0) {
    qs.set('types', params.types.join(','));
  }
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  return apiFetch<SearchResponseDto>(`/api/v1/search?${qs.toString()}`, { method: 'GET' });
}
