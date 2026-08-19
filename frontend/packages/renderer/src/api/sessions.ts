/**
 * #486 会话/记忆 UI — 会话 API 契约（F24 sessions + F44 PlannerSession 列表）.
 * 复用 apiFetch 统一错误映射（ApiError / KernelOfflineError），不重新实现 fetch.
 */
import { apiFetch } from './client';
import type { PlannerSessionDto } from './books';

export type { ConfirmedItem, ConflictRecord, PlannerQuestion, PlannerSessionDto } from './books';

/** 会话实体（对齐后端 Session model_dump(mode='json')） */
export interface SessionDto {
  id: string;
  session_type: string;
  status: string;
  project_id: string | null;
  title: string;
  description: string;
  context: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string;
  started_at: string;
  paused_at: string | null;
  completed_at: string | null;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
}

/** 会话列表项视图（session + 履历聚合，对齐后端 SessionView） */
export interface SessionViewDto {
  session: SessionDto;
  log_count: number;
  last_log: {
    id: string;
    session_id: string;
    seq: number;
    level: string;
    message: string;
    payload: Record<string, unknown>;
    created_at: string;
  } | null;
}

/** 会话列表响应（GET /api/v1/sessions） */
export interface SessionListResponse {
  items: SessionViewDto[];
  total: number;
  offset: number;
  limit: number;
}

/** 会话列表查询参数（include_deleted=true 时含已归档全量；limit/offset 缺省不携带） */
export interface FetchSessionsParams {
  includeDeleted?: boolean;
  sessionType?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

/** 访谈会话列表响应（GET /api/v1/agent/books/planner） */
export interface PlannerSessionListResponse {
  items: PlannerSessionDto[];
  total: number;
  offset: number;
  limit: number;
}

/** 会话列表：GET /api/v1/sessions（#486 会话页需列出/恢复已归档会话） */
export async function fetchSessions(params: FetchSessionsParams): Promise<SessionListResponse> {
  const qs = new URLSearchParams();
  if (params.includeDeleted) qs.set('include_deleted', 'true');
  if (params.sessionType) qs.set('session_type', params.sessionType);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  return apiFetch<SessionListResponse>(`/api/v1/sessions?${qs.toString()}`, { method: 'GET' });
}

/** 归档会话：DELETE /api/v1/sessions/{id}（无 force 查询参数 = 软删除语义，204） */
export async function archiveSession(sessionId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/sessions/${sessionId}`, { method: 'DELETE' });
}

/** 真实删除会话：DELETE /api/v1/sessions/{id}?force=true（204） */
export async function deleteSession(sessionId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/sessions/${sessionId}?force=true`, { method: 'DELETE' });
}

/** 恢复已归档会话：POST /api/v1/sessions/{id}/restore → Session */
export async function restoreSession(sessionId: string): Promise<SessionDto> {
  return apiFetch<SessionDto>(`/api/v1/sessions/${sessionId}/restore`, { method: 'POST' });
}

/** 访谈会话列表：GET /api/v1/agent/books/planner（可选参数缺省不携带） */
export async function fetchPlannerSessions(params?: {
  projectId?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<PlannerSessionListResponse> {
  const qs = new URLSearchParams();
  if (params?.projectId) qs.set('project_id', params.projectId);
  if (params?.status) qs.set('status', params.status);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  return apiFetch<PlannerSessionListResponse>(`/api/v1/agent/books/planner?${qs.toString()}`, {
    method: 'GET',
  });
}
