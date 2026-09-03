/**
 * F57 #888-S3 前端日志上报 bridge 契约（RED）。
 *
 * 被测模块 src/api/client.ts 新增：reportLog(FrontendLogRecord) → POST
 * /api/v1/logs；setCorrelationId/getCorrelationId（页面/操作级关联 ID）；
 * apiFetch 附加 X-Correlation-Id 头。当前实现缺失 → RED。
 *
 * 契约来源：specs/f57-logging-i18n/spec.md §2.2（caller_type=frontend 结构化）
 * + §3 POST /api/v1/logs（frontend bridge）+ §7 失败兜底（非阻塞）。
 *
 * reportLog 失败语义：HTTP 非 2xx / 网络错误 → console.warn 兜底 + 不抛
 * （非阻塞，logger 调 reportLog 不 await 也不会因上报失败中断用户操作）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  apiFetch,
  getApiConfig,
  getCorrelationId,
  reportLog,
  setCorrelationId,
  type FrontendLogRecord,
} from './client';

const BASE = 'http://api.test';

/** 构造可控 Response 替身（镜像 client.test.ts 同款 helper） */
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
let warnSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  setInjected({ baseURL: BASE, token: 'tok-1' });
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  setCorrelationId('');
});

afterEach(() => {
  vi.unstubAllGlobals();
  warnSpy.mockRestore();
  setInjected(undefined);
  setCorrelationId('');
});

describe('F57 reportLog — 上报 bridge（POST /api/v1/logs）', () => {
  const record: FrontendLogRecord = {
    level: 'info',
    caller_type: 'frontend',
    caller_name: 'WritingPage',
    event: 'create_chapter',
    message_key: 'log.event.create_chapter',
    params: { title: '第一章' },
    correlation_id: 'corr-1',
    timestamp: '2026-09-03T00:00:00.000Z',
  };

  it('POST /api/v1/logs：body 序列化记录 + X-InkFlow-Token 头', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await reportLog(record);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE}/api/v1/logs`);
    expect(init.method).toBe('POST');
    const headers = init.headers as Headers;
    expect(headers.get('X-InkFlow-Token')).toBe('tok-1');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(init.body).toBe(JSON.stringify(record));
  });

  it('X-Correlation-Id 头 = 记录的 correlation_id（前端 uuid → 头）', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await reportLog(record);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.get('X-Correlation-Id')).toBe('corr-1');
  });

  it('成功（{ok:true}）→ resolve，不触发 console.warn 兜底', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await expect(reportLog(record)).resolves.toEqual({ ok: true });
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('HTTP 500 → 不抛（非阻塞）+ console.warn 兜底', async () => {
    fetchMock.mockResolvedValue(jsonResponse(500, { detail: 'boom' }));
    await expect(reportLog(record)).resolves.toBeUndefined();
    expect(warnSpy).toHaveBeenCalled();
  });

  it('网络错误（fetch reject）→ 不抛 + console.warn 兜底', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(reportLog(record)).resolves.toBeUndefined();
    expect(warnSpy).toHaveBeenCalled();
  });
});

describe('F57 setCorrelationId / getCorrelationId — 页面/操作级关联 ID', () => {
  it('默认空串（未设置）', () => {
    expect(getCorrelationId()).toBe('');
  });

  it('set 后可读回', () => {
    setCorrelationId('page-uuid-xyz');
    expect(getCorrelationId()).toBe('page-uuid-xyz');
  });
});

describe('F57 apiFetch — 附加 X-Correlation-Id 头', () => {
  it('已设置 correlation_id → 所有 API 请求附加 X-Correlation-Id 头', async () => {
    setCorrelationId('corr-global');
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await apiFetch('/health');

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.get('X-Correlation-Id')).toBe('corr-global');
  });

  it('未设置 correlation_id（空串）→ 不附加 X-Correlation-Id 头', async () => {
    setCorrelationId('');
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await apiFetch('/health');

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.get('X-Correlation-Id')).toBeNull();
  });
});

describe('F57 getApiConfig — 注入源（回归护栏）', () => {
  it('window.INKFLOW_API 已注入 → 原样返回', () => {
    setInjected({ baseURL: 'http://127.0.0.1:54321', token: 'preload-token' });
    expect(getApiConfig()).toEqual({ baseURL: 'http://127.0.0.1:54321', token: 'preload-token' });
  });
});
