/** #276 RAG 向量检索（Issue #276，spec 范围 3/4）：状态查询 + 全量重建 API 契约。
 * 复用 apiFetch 统一错误映射（ApiError / KernelOfflineError），不重新实现 fetch。
 */
import { apiFetch } from './client';

/** 索引指纹（对齐后端 Fingerprint 的 model_dump(mode='json')） */
export interface FingerprintDto {
  schema_version: number;
  embedding: {
    provider: string;
    model_id: string;
    base_url: string;
    dimension: number | null;
  };
  chunking: { mode: string; chunk_size: number; overlap_ratio: number; chunker_version: number };
  indexed_at: string | null;
  status: string;
}

/** 向量库状态（对齐 GET /vector/status 响应） */
export interface VectorStatusDto {
  configured_fp: FingerprintDto | null;
  indexed_fp: FingerprintDto | null;
  stale: boolean;
  reason: string | null;
  dimension_mismatch: boolean;
}

/** 全量重建结果（对齐 POST /vector/reindex 响应） */
export interface ReindexResultDto {
  project_id: string;
  entity_types: string[];
  indexed: number;
  warnings: string[];
  collections_recreated: boolean;
}

/** 查询向量库状态：GET /api/v1/projects/{projectId}/vector/status（只读，不触发重建） */
export async function fetchVectorStatus(projectId: string): Promise<VectorStatusDto> {
  return apiFetch<VectorStatusDto>(`/api/v1/projects/${projectId}/vector/status`, {
    method: 'GET',
  });
}

/** 全量重建向量索引：POST /api/v1/projects/{projectId}/vector/reindex（body { entity_types }；缺省 → null = 服务层全量 5 种） */
export async function postVectorReindex(
  projectId: string,
  entityTypes?: string[],
): Promise<ReindexResultDto> {
  return apiFetch<ReindexResultDto>(`/api/v1/projects/${projectId}/vector/reindex`, {
    method: 'POST',
    body: { entity_types: entityTypes ?? null },
  });
}
