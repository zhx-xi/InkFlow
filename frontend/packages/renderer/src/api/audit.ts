/**
 * F34 章节审计（Issue #208，spec §3.1/§3.2/§5.3；#1425 异步语义）
 *
 * #1425：`POST .../audit` 由阻塞 200 改为 **202 + {log_id, status}**（后台执行），
 * findings 经 v1.4 读口 `GET /api/v1/audit-logs/{log_id}` 取回，状态经
 * `GET /api/v1/audit-logs/{log_id}/status` 轮询。
 *
 * **GUI 调用面保持 UX 不变**：`auditChapter` 内部完成「受理 → 轮询 → 取结果 → 映射」，
 * 对外仍返回 `AuditReportDto`（`writing.tsx` 的弹层/加载态零改动）；需要自管轮询的
 * 调用方用 `triggerAudit`（= `--no-wait` 语义）。
 *
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

/** 任务执行态（#1425，与确认态 status 正交） */
export type AuditRunStatusDto = 'running' | 'completed' | 'failed';

/** POST .../audit 的 202 受理响应（#1425） */
export interface AuditAcceptedDto {
  log_id: string;
  status: AuditRunStatusDto;
}

/** GET /audit-logs/{log_id}/status 的响应（#1425 轮询读口，轻量） */
export interface AuditRunInfoDto {
  log_id: string;
  run_status: AuditRunStatusDto;
  status: 'pending' | 'accepted' | 'rejected';
  degraded: boolean;
  error: string;
  chapter_id: string | null;
  chapter_title: string;
  created_at: string;
}

/** GET /audit-logs/{log_id} 的响应（#1420 读口 + #1425 执行态） */
export interface AuditLogDetailDto {
  id: string;
  project_id: string;
  chapter_id: string | null;
  chapter_title: string;
  status: 'pending' | 'accepted' | 'rejected';
  run_status: AuditRunStatusDto;
  severity_summary: string;
  summary: string;
  degraded: boolean;
  note: string;
  created_at: string;
  confirmed_at: string | null;
  error: string;
  findings: AuditFindingDto[];
}

/** 轮询节奏（毫秒）——测试可用 `options` 覆盖 */
const POLL_INTERVAL_MS = 1500;
/** 轮询总预算（毫秒）——超时抛错（含 log_id 恢复指引） */
const POLL_TIMEOUT_MS = 600_000;

export interface AuditPollOptions {
  /** 轮询间隔毫秒（默认 1500） */
  intervalMs?: number;
  /** 总预算毫秒（默认 600000） */
  timeoutMs?: number;
}

/** 触发章节审计（202 受理）：POST /api/v1/projects/{pid}/chapters/{cid}/audit（body { include_static }） */
export async function triggerAudit(
  projectId: string,
  chapterId: string,
  includeStatic = true,
): Promise<AuditAcceptedDto> {
  return apiFetch<AuditAcceptedDto>(`/api/v1/projects/${projectId}/chapters/${chapterId}/audit`, {
    method: 'POST',
    body: { include_static: includeStatic },
  });
}

/** 查询任务运行状态（#1425 轮询读口）：GET /api/v1/audit-logs/{logId}/status */
export async function fetchAuditStatus(logId: string): Promise<AuditRunInfoDto> {
  return apiFetch<AuditRunInfoDto>(`/api/v1/audit-logs/${logId}/status`);
}

/** 取回审计记录明细（#1420 读口）：GET /api/v1/audit-logs/{logId} */
export async function fetchAuditDetail(logId: string): Promise<AuditLogDetailDto> {
  return apiFetch<AuditLogDetailDto>(`/api/v1/audit-logs/${logId}`);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 轮询至终态（running → completed/failed）；超预算抛 Error（含 log_id 指引） */
export async function pollAuditStatus(
  logId: string,
  options: AuditPollOptions = {},
): Promise<AuditRunInfoDto> {
  const intervalMs = options.intervalMs ?? POLL_INTERVAL_MS;
  const timeoutMs = options.timeoutMs ?? POLL_TIMEOUT_MS;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const info = await fetchAuditStatus(logId);
    if (info.run_status !== 'running') {
      return info;
    }
    if (Date.now() >= deadline) {
      throw new Error(`审计任务超时未完成（log_id: ${logId}）——可用「审计记录」按 ID 查询结果`);
    }
    await sleep(intervalMs);
  }
}

/** 记录明细 → 报告形态（UI 侧沿用 AuditReportDto，零改动） */
function toReportDto(detail: AuditLogDetailDto): AuditReportDto {
  return {
    chapter_id: detail.chapter_id ?? '',
    chapter_title: detail.chapter_title,
    status: detail.status,
    findings: detail.findings,
    summary: detail.summary,
    degraded: detail.degraded,
    created_at: detail.created_at,
    confirmed_at: detail.confirmed_at,
  };
}

/**
 * 触发章节审计并等到结果（**GUI 默认路径**，#1425：内部 202 + 轮询，UX 与同步版一致）。
 *
 * 幂等复用命中已完成记录时后端直接返回 `status='completed'` → 跳过轮询。
 * 后台执行失败（`run_status='failed'`）→ 抛 Error（error 文案透传）。
 */
export async function auditChapter(
  projectId: string,
  chapterId: string,
  includeStatic = true,
  options: AuditPollOptions = {},
): Promise<AuditReportDto> {
  const accepted = await triggerAudit(projectId, chapterId, includeStatic);
  if (accepted.status === 'failed') {
    throw new Error(`审计任务失败（log_id: ${accepted.log_id}）`);
  }
  if (accepted.status === 'running') {
    const info = await pollAuditStatus(accepted.log_id, options);
    if (info.run_status === 'failed') {
      throw new Error(info.error || `审计任务失败（log_id: ${accepted.log_id}）`);
    }
  }
  return toReportDto(await fetchAuditDetail(accepted.log_id));
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
