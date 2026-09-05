/**
 * #931 RED 契约：GUI 入口面 W3C traceparent（前端生成根 trace，每请求子 span）。
 *
 * 缺陷背景：前端只发 X-Correlation-Id；拍板 A 后 traceparent 为链路主锚。
 *
 * GREEN 实现契约（src/api/client.ts MODIFY）：
 * 1. 模块级根 trace 懒生成：newTraceId() 32 位小写 hex（crypto.getRandomValues）
 *    → 首次访问时生成，应用生命周期内恒定（一次 GUI 会话 = 一条根 trace）。
 * 2. apiFetch 每请求附加 `traceparent: 00-<根traceId>-<新spanId 16hex>-01`
 *    （内核建子 span，parent=本请求 span）。
 * 3. reportLog 同样附加 traceparent（前端日志与 API 调用同 trace 聚合）。
 * 4. 导出 getTraceId(): string（根 trace；测试与排障用）。
 *
 * 零回归：既有 X-Correlation-Id 行为（logging.test.ts）不变。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiFetch, getTraceId, reportLog, type FrontendLogRecord } from './client';

const BASE = 'http://api.test';
const TP_RE = /^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$/;

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function setInjected(cfg: { baseURL: string; token: string } | undefined): void {
  Object.defineProperty(window, 'INKFLOW_API', { configurable: true, value: cfg });
}

let fetchMock: ReturnType<typeof vi.fn>;
let warnSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  setInjected({ baseURL: BASE, token: 'tok-1' });
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  warnSpy.mockRestore();
  setInjected(undefined);
});

const record: FrontendLogRecord = {
  level: 'info',
  caller_type: 'frontend',
  caller_name: 'WritingPage',
  event: 'probe',
  message_key: 'log.event.probe',
  params: {},
  correlation_id: 'corr-tp',
  timestamp: '2026-09-05T00:00:00.000Z',
};

describe('#931 apiFetch — traceparent 头', () => {
  it('每请求带合法 W3C traceparent（根 trace 稳定 + span 逐请求新生成）', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await apiFetch('/health');
    await apiFetch('/projects');

    const h1 = (fetchMock.mock.calls[0][1] as RequestInit).headers as Headers;
    const h2 = (fetchMock.mock.calls[1][1] as RequestInit).headers as Headers;
    const tp1 = h1.get('traceparent');
    const tp2 = h2.get('traceparent');
    expect(tp1, 'apiFetch 必须附加 traceparent（#931 入口面根 span）').toMatch(TP_RE);
    expect(tp2).toMatch(TP_RE);
    expect(tp1!.slice(3, 35)).toBe(tp2!.slice(3, 35)); // 同根 trace_id
    expect(tp1!.slice(36, 52)).not.toBe(tp2!.slice(36, 52)); // 子 span 各异
  });

  it('getTraceId() = 头中的 trace_id 且 32 位小写 hex、会话内恒定', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await apiFetch('/health');
    const tp = ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
      'traceparent',
    );
    expect(getTraceId()).toMatch(/^[0-9a-f]{32}$/);
    expect(tp!.slice(3, 35)).toBe(getTraceId());
    expect(getTraceId()).toBe(getTraceId()); // 稳定
  });
});

describe('#931 reportLog — traceparent 头', () => {
  it('前端日志上报与 API 请求同根 trace', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await reportLog(record);
    const tp = ((fetchMock.mock.calls[0][1] as RequestInit).headers as Headers).get(
      'traceparent',
    );
    expect(tp, 'reportLog 必须带 traceparent').toMatch(TP_RE);
    expect(tp!.slice(3, 35)).toBe(getTraceId());
  });
});
