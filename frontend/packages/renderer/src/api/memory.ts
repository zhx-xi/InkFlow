/**
 * #486 会话/记忆 UI — 记忆 API 契约（F28 agent memory 端点消费）.
 * 复用 apiFetch 统一错误映射（ApiError / KernelOfflineError），不重新实现 fetch.
 */
import { apiFetch } from './client';

/** 语义总结 DTO（对齐后端 MemorySummaryDto） */
export interface MemorySummaryDto {
  content: string;
  anchor_hash: string;
  anchor_count: number;
  model: string;
  updated_at: string;
}

/** 语义总结响应（GET /api/v1/agent/memory/summaries） */
export interface MemorySummariesResponse {
  project_id: string;
  project: MemorySummaryDto | null;
  user: MemorySummaryDto | null;
}

/** 提取记忆响应（POST /api/v1/agent/memory/summarize） */
export interface SummarizeMemoryResponse {
  project_id: string;
  summarized: boolean;
  project: MemorySummaryDto | null;
  user: MemorySummaryDto | null;
}

/** 项目级偏好 DTO（对齐后端 ProjectPreferenceDto） */
export interface ProjectPreferenceDto {
  id: string;
  project_id: string;
  category: string;
  pattern: string;
  value: string;
  confidence: number;
  count: number;
  source_events: string[];
  created_at: string;
  updated_at: string;
}

/** 用户级偏好 DTO（对齐后端 UserPreferenceDto） */
export interface UserPreferenceDto {
  id: string;
  category: string;
  pattern: string;
  value: string;
  confidence: number;
  count: number;
  project_count: number;
  source_projects: string[];
  source_events: string[];
  created_at: string;
  updated_at: string;
}

/** 偏好列表响应（items 泛型：项目级默认 / 用户级显式 UserPreferenceDto） */
export interface PreferencesResponse<T = ProjectPreferenceDto> {
  items: T[];
  total: number;
}

/** 语义总结：GET /api/v1/agent/memory/summaries?project_id= */
export async function fetchMemorySummaries(projectId: string): Promise<MemorySummariesResponse> {
  const qs = new URLSearchParams({ project_id: projectId });
  return apiFetch<MemorySummariesResponse>(`/api/v1/agent/memory/summaries?${qs.toString()}`, {
    method: 'GET',
  });
}

/** 提取记忆：POST /api/v1/agent/memory/summarize（force 显式 true 才携带） */
export async function summarizeMemory(
  projectId: string,
  force?: boolean,
): Promise<SummarizeMemoryResponse> {
  const qs = new URLSearchParams({ project_id: projectId });
  if (force === true) qs.set('force', 'true');
  return apiFetch<SummarizeMemoryResponse>(`/api/v1/agent/memory/summarize?${qs.toString()}`, {
    method: 'POST',
  });
}

/** 项目级偏好：GET /api/v1/agent/preferences?project_id= */
export async function fetchProjectPreferences(projectId: string): Promise<PreferencesResponse> {
  const qs = new URLSearchParams({ project_id: projectId });
  return apiFetch<PreferencesResponse>(`/api/v1/agent/preferences?${qs.toString()}`, {
    method: 'GET',
  });
}

/** 删除项目级偏好：DELETE /api/v1/agent/preferences/{id} */
export async function removeProjectPreference(preferenceId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/agent/preferences/${preferenceId}`, { method: 'DELETE' });
}

/** 用户级偏好：GET /api/v1/agent/user-preferences */
export async function fetchUserPreferences(): Promise<PreferencesResponse<UserPreferenceDto>> {
  return apiFetch<PreferencesResponse<UserPreferenceDto>>('/api/v1/agent/user-preferences', {
    method: 'GET',
  });
}

/** 删除用户级偏好：DELETE /api/v1/agent/user-preferences/{id} */
export async function removeUserPreference(preferenceId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/agent/user-preferences/${preferenceId}`, { method: 'DELETE' });
}
