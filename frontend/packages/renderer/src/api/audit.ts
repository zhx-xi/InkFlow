/** F34 章节审计（Issue #208，spec §3.1/§3.2/§5.3）：触发审计 + accept/reject 确认闭环。
 * 复用 apiFetch 统一错误映射（ApiError / KernelOfflineError），不重新实现 fetch。
 */
import { apiFetch } from './client';

/** 单条审计发现（对齐 ChapterAuditFinding 的 model_dump(mode='json')） */
export interface AuditFindingDto {
  check_type: string;
  severity: 'info' | 'warning' | 'error';
  message: string;
  suggestion?: string;
  ref_entity_id?: string | null;
  ref_entity_name?: string;
  context?: string;
}

/** 章节审计报告（对齐 ChapterAuditReport 的 model_dump(mode='json')） */
export interface AuditReportDto {
  chapter_id: string;
  chapter_title: string;
  status: 'pending' | 'accepted' | 'rejected';
  findings: AuditFindingDto[];
  summary: string;
  degraded: boolean;
  created_at: string;
  confirmed_at: string | null;
}

/** 触发章节审计：POST /api/v1/projects/{projectId}/chapters/{chapterId}/audit（body { include_static }） */
export async function auditChapter(
  projectId: string,
  chapterId: string,
  includeStatic = true,
): Promise<AuditReportDto> {
  return apiFetch<AuditReportDto>(`/api/v1/projects/${projectId}/chapters/${chapterId}/audit`, {
    method: 'POST',
    body: { include_static: includeStatic },
  });
}

/** 确认审计结果：POST .../audit/confirm（body { action, note }），响应 { status, confirmed_at } */
export async function confirmAudit(
  projectId: string,
  chapterId: string,
  action: 'accept' | 'reject',
  note = '',
): Promise<{ status: string; confirmed_at: string | null }> {
  return apiFetch<{ status: string; confirmed_at: string | null }>(
    `/api/v1/projects/${projectId}/chapters/${chapterId}/audit/confirm`,
    { method: 'POST', body: { action, note } },
  );
}
