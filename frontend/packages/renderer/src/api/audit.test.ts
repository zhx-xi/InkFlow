/**
 * F34 章节审计 API 契约测试（Issue #208，spec §3.1/§3.2/§5.3）
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/api/audit.ts，必须导出：
 * - interface AuditReportDto（与 ChapterAuditReport model_dump(mode='json') 同构：
 *   chapter_id / chapter_title / status('pending'|'accepted'|'rejected') / findings /
 *   summary / degraded / created_at / confirmed_at；findings 项：
 *   check_type / severity / message / suggestion / ref_entity_name / context）
 * - auditChapter(projectId: string, chapterId: string, includeStatic = true): Promise<AuditReportDto>
 *   → POST /api/v1/projects/{projectId}/chapters/{chapterId}/audit，body { include_static }
 * - confirmAudit(projectId: string, chapterId: string, action: 'accept' | 'reject', note = ''):
 *   Promise<{ status: string; confirmed_at: string | null }>
 *   → POST /api/v1/projects/{projectId}/chapters/{chapterId}/audit/confirm，body { action, note }
 *
 * 测试策略：不 mock ../api/client（避开 #107 vi.mock 闭包坑——apiFetch 模块内闭包
 * 不被导出层替换影响）——直接 spy 全局 fetch，apiFetch 真实执行；
 * window.INKFLOW_API 注入固定 baseURL/token（client.test.ts 同款），URL 可精确断言。
 * 错误契约：HTTP 非 2xx → ApiError（status/detail 透传，errorMessage 可读）；
 * fetch reject（内核未启动）→ KernelOfflineError。
 *
 * RED 预期：./audit 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { auditChapter, confirmAudit } from './audit';
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

function lastFetchCall() {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return { url, init };
}

describe('auditChapter — 触发审计', () => {
  it('默认 includeStatic=true：POST audit 端点，body 含 include_static true', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, reportDto));
    await expect(auditChapter('p1', 'c2')).resolves.toEqual(reportDto);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const { url, init } = lastFetchCall();
    expect(url).toBe(`${BASE}/api/v1/projects/p1/chapters/c2/audit`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ include_static: true });
    const headers = init.headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('X-InkFlow-Token')).toBe('tok-1');
  });

  it('includeStatic=false → body { include_static: false }', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, reportDto));
    await auditChapter('p1', 'c2', false);
    const { init } = lastFetchCall();
    expect(JSON.parse(init.body as string)).toEqual({ include_static: false });
  });

  it('响应透传：报告 JSON 原样返回', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, reportDto));
    const result = await auditChapter('p1', 'c2');
    expect(result).toEqual(reportDto);
    expect(result.findings).toHaveLength(1);
    expect(result.degraded).toBe(false);
  });
});

describe('confirmAudit — 确认', () => {
  it('带 note：POST confirm 端点，body { action: reject, note }，响应透传', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { status: 'rejected', confirmed_at: '2026-08-09T10:05:00Z' }),
    );
    const result = await confirmAudit('p1', 'c2', 'reject', '人设需再打磨');

    expect(result).toEqual({ status: 'rejected', confirmed_at: '2026-08-09T10:05:00Z' });
    const { url, init } = lastFetchCall();
    expect(url).toBe(`${BASE}/api/v1/projects/p1/chapters/c2/audit/confirm`);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ action: 'reject', note: '人设需再打磨' });
  });

  it('默认 note 空串：body { action: accept, note: 空 }', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { status: 'accepted', confirmed_at: '2026-08-09T10:05:00Z' }),
    );
    await confirmAudit('p1', 'c2', 'accept');
    const { init } = lastFetchCall();
    expect(JSON.parse(init.body as string)).toEqual({ action: 'accept', note: '' });
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
