/**
 * 草稿审批 API 封装（Issue #653）：项目 AI 草稿的列表/确认/驳回/编辑/清理孤儿。
 *
 * - listDrafts: 项目草稿列表（GET /api/v1/agent/drafts?project_id=<id>）
 * - confirmDraft: 确认草稿（POST /api/v1/agent/drafts/{id}/confirm）
 * - rejectDraft: 驳回草稿（POST /api/v1/agent/drafts/{id}/reject，无 body）
 * - updateDraft: 编辑草稿正文（PATCH /api/v1/agent/drafts/{id}）
 * - pruneOrphans: 清理孤儿草稿（POST /api/v1/agent/drafts/prune-orphans）
 *
 * 后端 agent_runs.py（#653）已注册这些端点；本模块将响应映射为类型化 DTO。
 */
import { apiFetch } from './client';

/** 草稿领域模型（model_dump(mode='json') 形态） */
export interface DraftDto {
  id: string;
  project_id: string;
  chapter_id: string | null;
  agent_run_id: string | null;
  content: string;
  status: string; // 'draft' | 'confirmed' | 'rejected'
  summary: string;
  created_at: string;
  confirmed_at: string | null;
  /** #976 卷归组（drafts.volume_id 列，UUID 字符串；未归组草稿缺省/为 null） */
  volume_id?: string | null;
}

/** 项目草稿列表（GET /api/v1/agent/drafts?project_id=<projectId>[&status=<status>]；status 缺省时 URL 与既有逐字一致） */
export async function listDrafts(
  projectId: string,
  status?: string,
): Promise<{ items: DraftDto[]; total: number }> {
  const qs = new URLSearchParams({ project_id: projectId });
  if (status !== undefined) qs.set('status', status);
  return apiFetch<{ items: DraftDto[]; total: number }>(`/api/v1/agent/drafts?${qs.toString()}`);
}

/** 确认草稿（POST /api/v1/agent/drafts/{draftId}/confirm；无 chapterId 时 body 为空对象） */
export async function confirmDraft(
  draftId: string,
  chapterId?: string,
): Promise<{ draft_id: string; status: string; chapter_id: string | null }> {
  return apiFetch<{ draft_id: string; status: string; chapter_id: string | null }>(
    `/api/v1/agent/drafts/${draftId}/confirm`,
    { method: 'POST', body: chapterId ? { chapter_id: chapterId } : {} },
  );
}

/** 驳回草稿（POST /api/v1/agent/drafts/{draftId}/reject，无 body） */
export async function rejectDraft(draftId: string): Promise<{ draft_id: string; status: string }> {
  return apiFetch<{ draft_id: string; status: string }>(`/api/v1/agent/drafts/${draftId}/reject`, {
    method: 'POST',
  });
}

/** 编辑草稿正文（PATCH /api/v1/agent/drafts/{draftId}，body { content }） */
export async function updateDraft(
  draftId: string,
  content: string,
): Promise<{ draft_id: string; status: string; word_count: number; learned: boolean }> {
  return apiFetch<{ draft_id: string; status: string; word_count: number; learned: boolean }>(
    `/api/v1/agent/drafts/${draftId}`,
    { method: 'PATCH', body: { content } },
  );
}

/** 清理孤儿草稿（POST /api/v1/agent/drafts/prune-orphans，body { dry_run: dryRun }） */
export async function pruneOrphans(dryRun = false): Promise<{ deleted: number }> {
  return apiFetch<{ deleted: number }>('/api/v1/agent/drafts/prune-orphans', {
    method: 'POST',
    body: { dry_run: dryRun },
  });
}
