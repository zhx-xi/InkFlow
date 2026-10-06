/**
 * F34 章节审计 API 契约测试（Issue #208，spec §3.1/§3.2/§5.3；#1425 异步语义）
 *
 * ⚠️ 本文件 = 契约。GREEN 的 src/api/audit.ts 必须导出：
 * - interface AuditReportDto（与 ChapterAuditReport model_dump(mode='json') 同构）
 * - triggerAudit(projectId, chapterId, includeStatic = true): Promise<AuditAcceptedDto>
 *   → POST /api/v1/projects/{pid}/chapters/{cid}/audit，body { include_static }，
 *     响应 202 { log_id, status('running'|'completed'|'failed') }
 * - fetchAuditStatus(logId): Promise<AuditRunInfoDto>
 *   → GET /api/v1/audit-logs/{logId}/status
 * - fetchAuditDetail(logId): Promise<AuditLogDetailDto>
 *   → GET /api/v1/audit-logs/{logId}
 * - auditChapter(projectId, chapterId, includeStatic = true): Promise<AuditReportDto>
 *   → 内部「受理 → （running 时）轮询 → 取明细 → 映射」，**对外仍是报告形态**（UX 不变）
 * - confirmAudit(projectId, chapterId, action, note = ''):
 *   Promise<{ status: string; confirmed_at: string | null }>
 *   → POST .../audit/confirm，body { action, note }
 *
 * 测试策略：不 mock ../api/client（避开 #107 vi.mock 闭包坑——apiFetch 模块内闭包
 * 不被导出层替换影响）——直接 spy 全局 fetch，apiFetch 真实执行；
 * window.INKFLOW_API 注入固定 baseURL/token（client.test.ts 同款），URL 可精确断言。
 * 错误契约：HTTP 非 2xx → ApiError（status/detail 透传，errorMessage 可读）；
 * fetch reject（内核未启动）→ KernelOfflineError。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { auditChapter, confirmAudit, fetchAuditDetail, fetchAuditStatus, triggerAudit } from './audit';
import { ApiError, errorMessage, KernelOfflineError } from './client';

const BASE = 'http://api.test';

/** 契约结构镜像（GREEN 类型从 audit.ts 导出；本文件内联镜像供 mock 播种） */
interface AuditReportDto {
  chapter_id: string;
  chapter_title: string;
  status: 'pending' | 'accepted' | 'rejected';
  findings: Array<{
    check_type: string;
    severity: 'info' | 'warning' | 'error';
    message: string;
    suggestion: string;
    ref_entity_name: string;
    context: string;
  }>;
  summary: string;
  degraded: boolean;
  created_at: string;
  confirmed_at: string | null;
}

const LOG_ID = '00000000-0000-4000-8000-0000000000a1';

const acceptedDto = { log_id: LOG_ID, status: 'running' as const };

const runInfoDto = {
  log_id: LOG_ID,
  run_status: 'completed' as const,
  status: 'pending' as const,
  degraded: false,
  error: '',
  chapter_id: 'c2',
  chapter_title: '第 3 章 龙的苏醒',
  created_at: '2026-08-09T10:00:00Z',
};

const detailDto = {
  id: LOG_ID,
  project_id: 'p1',
  chapter_id: 'c2',
  chapter_title: '第 3 章 龙的苏醒',
  status: 'pending' as const,
  run_status: 'completed' as const,
  severity_summary: '0 error, 0 warnings, 1 info',
  summary: '本章整体符合设定',
  degraded: false,
  note: '',
  created_at: '2026-08-09T10:00:00Z',
  confirmed_at: null,
  error: '',
  findings: [
    {
      check_type: 'word_count',
      severity: 'info' as const,
      message: '本章 2,845 字，低于目标 3,000 字',
      suggestion: '',
      ref_entity_name: '',
      context: '',
    },
  ],
};

const reportDto: AuditReportDto = {
  chapter_id: 'c2',
  chapter_title: '第 3 章 龙的苏醒',
  status: 'pending',
  findings: [
    {
      check_type: 'word_count',
      severity: 'info',
      message: '本章 2,845 字，低于目标 3,000 字',
      suggestion: '',
      ref_entity_name: '',
      context: '',
    },
  ],
  summary: '本章整体符合设定',
  degraded: false,
  created_at: '2026-08-09T10:00:00Z',
  confirmed_at: null,
};

/** 可控 Response 替身（client.test.ts 同款） */
function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function setInjected(cfg: { baseURL: string; token: string } | undefined): void {
  Object.defineProperty(window, 'INKFLOW_API', {
    configurable: true,
    value: cfg,
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  setInjected({ baseURL: BASE, token: 'tok-1' });
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setInjected(undefined);
});

function fetchCall(index: number) {
  const [url, init] = fetchMock.mock.calls[index] as [string, RequestInit];
  return { url, init };
}

describe('triggerAudit — 202 受理（#1425）', () => {
  it('返回 { log_id, status }，POST audit 端点 + body { include_static: true }', async () => {
    fetchMock.mockResolvedValue(jsonResponse(202, acceptedDto));

    await expect(triggerAudit('p1', 'c2')).resolves.toEqual(acceptedDto);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const { url, init } = fetchCall(0);
    expect(url).toBe(`${BASE}/api/v1/projects/p1/chapters/c2/audit`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ include_static: true });
    const headers = init.headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('X-InkFlow-Token')).toBe('tok-1');
  });

  it('includeStatic=false → body { include_static: false }', async () => {
    fetchMock.mockResolvedValue(jsonResponse(202, acceptedDto));
    await triggerAudit('p1', 'c2', false);
    expect(JSON.parse(fetchCall(0).init.body as string)).toEqual({ include_static: false });
  });
});

describe('fetchAuditStatus / fetchAuditDetail — 读口（#1425 / #1420）', () => {
  it('status → GET /api/v1/audit-logs/{logId}/status，响应透传', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, runInfoDto));

    await expect(fetchAuditStatus(LOG_ID)).resolves.toEqual(runInfoDto);

    expect(fetchCall(0).url).toBe(`${BASE}/api/v1/audit-logs/${LOG_ID}/status`);
  });

  it('detail → GET /api/v1/audit-logs/{logId}，响应透传（含 findings）', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, detailDto));

    const detail = await fetchAuditDetail(LOG_ID);

    expect(fetchCall(0).url).toBe(`${BASE}/api/v1/audit-logs/${LOG_ID}`);
    expect(detail.findings).toHaveLength(1);
  });
});

describe('auditChapter — 触发审计（内部 202 + 轮询，对外报告形态）', () => {
  it('running → 轮询 status → 取明细 → 映射为 AuditReportDto', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(202, acceptedDto))
      .mockResolvedValueOnce(jsonResponse(200, runInfoDto))
      .mockResolvedValueOnce(jsonResponse(200, detailDto));

    await expect(
      auditChapter('p1', 'c2', true, { intervalMs: 1 }),
    ).resolves.toEqual(reportDto);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchCall(0).url).toBe(`${BASE}/api/v1/projects/p1/chapters/c2/audit`);
    expect(fetchCall(1).url).toBe(`${BASE}/api/v1/audit-logs/${LOG_ID}/status`);
    expect(fetchCall(2).url).toBe(`${BASE}/api/v1/audit-logs/${LOG_ID}`);
  });

  it('幂等复用命中已完成（status=completed）→ 跳过轮询，仅两次请求', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(202, { log_id: LOG_ID, status: 'completed' }))
      .mockResolvedValueOnce(jsonResponse(200, detailDto));

    const result = await auditChapter('p1', 'c2');

    expect(result).toEqual(reportDto);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchCall(1).url).toBe(`${BASE}/api/v1/audit-logs/${LOG_ID}`);
  });

  it('后台执行失败（run_status=failed）→ 抛错并透出 error 文案', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(202, acceptedDto))
      .mockResolvedValueOnce(
        jsonResponse(200, { ...runInfoDto, run_status: 'failed', error: '审计任务失败: boom' }),
      );

    await expect(auditChapter('p1', 'c2', true, { intervalMs: 1 })).rejects.toThrow('boom');
  });

  it('includeStatic=false 透传', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(202, { log_id: LOG_ID, status: 'completed' }))
      .mockResolvedValueOnce(jsonResponse(200, detailDto));

    await auditChapter('p1', 'c2', false);

    expect(JSON.parse(fetchCall(0).init.body as string)).toEqual({ include_static: false });
  });
});

describe('confirmAudit — 确认', () => {
  it('带 note：POST confirm 端点，body { action: reject, note }，响应透传', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { status: 'rejected', confirmed_at: '2026-08-09T10:05:00Z' }),
    );
    const result = await confirmAudit('p1', 'c2', 'reject', '人设需再打磨');

    expect(result).toEqual({ status: 'rejected', confirmed_at: '2026-08-09T10:05:00Z' });
    const { url, init } = fetchCall(0);
    expect(url).toBe(`${BASE}/api/v1/projects/p1/chapters/c2/audit/confirm`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ action: 'reject', note: '人设需再打磨' });
  });

  it('默认 note 空串：body { action: accept, note: 空 }', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { status: 'accepted', confirmed_at: '2026-08-09T10:05:00Z' }),
    );
    await confirmAudit('p1', 'c2', 'accept');
    expect(JSON.parse(fetchCall(0).init.body as string)).toEqual({ action: 'accept', note: '' });
  });
});

describe('audit API — 错误契约', () => {
  it('HTTP 404 + detail → ApiError，errorMessage 可读', async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { detail: 'Chapter not found' }));
    const err = await auditChapter('p1', 'c999').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).detail).toBe('Chapter not found');
    expect(errorMessage(err)).toBe('Chapter not found');
  });

  it('fetch reject（内核未启动）→ KernelOfflineError', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const err = await confirmAudit('p1', 'c2', 'accept').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(KernelOfflineError);
    expect(errorMessage(err)).toBe('Kernel unreachable');
  });
});
