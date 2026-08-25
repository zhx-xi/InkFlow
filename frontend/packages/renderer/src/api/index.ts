/**
 * #657 索引维护（Issue #657 检索页重建索引入口）：POST /api/v1/index/rebuild
 * 异步重建全文 FTS5 + 向量索引（后端 #659 配套：异步 202 + 进度轮询）。
 * 复用 apiFetch 统一错误映射（ApiError / KernelOfflineError），不重新实现 fetch。
 */
import { apiFetch } from './client';

/** 重建参数（project_ids 缺省/null = 全部项目；scope 缺省 = 'both'） */
export interface IndexRebuildParams {
  project_ids?: string[] | null;
  scope?: 'fulltext' | 'vector' | 'both';
}

/** 重建启动响应（对齐 POST /index/rebuild 202 响应） */
export interface IndexRebuildStartDto {
  task_id: string;
  status: string;
}

/** 重建进度响应（对齐 GET /index/rebuild/status 响应） */
export interface IndexRebuildStatusDto {
  status: 'running' | 'done' | 'failed';
  step: 'fulltext' | 'vector';
  progress_done: number;
  progress_total: number;
  rebuilt_at: string | null;
  error: string | null;
}

/** 发起索引重建：POST /api/v1/index/rebuild（project_ids 缺省 → null 全部项目） */
export async function postIndexRebuild(params: IndexRebuildParams): Promise<IndexRebuildStartDto> {
  return apiFetch<IndexRebuildStartDto>('/api/v1/index/rebuild', {
    method: 'POST',
    body: { project_ids: params.project_ids ?? null, scope: params.scope ?? 'both' },
  });
}

/** 查询重建进度：GET /api/v1/index/rebuild/status?task_id=<id> */
export async function fetchIndexRebuildStatus(taskId: string): Promise<IndexRebuildStatusDto> {
  return apiFetch<IndexRebuildStatusDto>(
    `/api/v1/index/rebuild/status?task_id=${encodeURIComponent(taskId)}`,
    { method: 'GET' },
  );
}
