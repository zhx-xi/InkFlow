/**
 * REST client 薄弱分支补测（Issue #104 覆盖率：行 77.63% → 目标 ≥99%）
 *
 * 覆盖点（对应 src/api/client.ts）：
 * - apiFetch 网络失败（fetch reject → KernelOfflineError）
 * - 401 → KernelOfflineError
 * - 非 JSON 错误体（res.json 抛错 → 默认 detail `HTTP <status>`）
 * - JSON detail 为对象 → JSON.stringify
 * - body 为 FormData → 不设 Content-Type
 * - 无 token → 不设 X-InkFlow-Token 头
 * - errorMessage 三分支（ApiError / Error / 其他）
 * - getApiConfig 的 window.INKFLOW_API 分支与回退分支
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { apiFetch, errorMessage, getApiConfig, ApiError, KernelOfflineError } from './client';

const BASE = 'http://api.test';

/** 构造可控 Response 替身（ok/status/json 按需注入） */
function jsonResponse(status: number, body: unknown, jsonImpl?: () => Promise<unknown>) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: jsonImpl ?? vi.fn().mockResolvedValue(body),
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

describe('apiFetch — 成功路径', () => {
  it('GET 无 body：拼接 baseURL + token 头，不设 Content-Type', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await expect(apiFetch('/health')).resolves.toEqual({ ok: true });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE}/health`);
    const headers = init.headers as Headers;
    expect(headers.get('X-InkFlow-Token')).toBe('tok-1');
    expect(headers.get('Content-Type')).toBeNull();
    expect(init.body).toBeUndefined();
  });

  it('POST 带 JSON body：Content-Type application/json + body 序列化', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { id: 1 }));
    await expect(apiFetch('/items', { method: 'POST', body: { name: 'x' } })).resolves.toEqual({ id: 1 });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${BASE}/items`);
    const headers = init.headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('X-InkFlow-Token')).toBe('tok-1');
    expect(init.body).toBe(JSON.stringify({ name: 'x' }));
  });

  it('body 为 FormData：不设 Content-Type（由浏览器带 multipart boundary）', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    const form = new FormData();
    form.append('file', 'blob');
    await apiFetch('/upload', { method: 'POST', body: form });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    // 契约点：FormData 分支不设 Content-Type（浏览器自动带 multipart boundary）
    expect(headers.get('Content-Type')).toBeNull();
    expect(headers.get('X-InkFlow-Token')).toBe('tok-1');
  });

  it('无 token：不设 X-InkFlow-Token 头', async () => {
    setInjected({ baseURL: BASE, token: '' });
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    await apiFetch('/health');

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.get('X-InkFlow-Token')).toBeNull();
  });

  it('204 No Content（DELETE 等无响应体）→ 返回 undefined，不调 res.json()', async () => {
    // #140 E2 实测：DELETE /provider-configs/{id} 返回 204 无 body，旧实现 res.json() 抛
    // SyntaxError → store 不更新 → 前端删除 Provider 后卡片不消失（真实 bug，已修复）
    const jsonSpy = vi.fn();
    fetchMock.mockResolvedValue(jsonResponse(204, null, jsonSpy));
    await expect(apiFetch('/items/1', { method: 'DELETE' })).resolves.toBeUndefined();
    expect(jsonSpy).not.toHaveBeenCalled();
  });
});

describe('apiFetch — 错误映射', () => {
  it('网络层失败（fetch reject）→ KernelOfflineError("Kernel unreachable")', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const err = await apiFetch('/health').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(KernelOfflineError);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as KernelOfflineError).status).toBe(401);
    expect((err as KernelOfflineError).detail).toBe('Kernel unreachable');
  });

  it('401 → KernelOfflineError（默认 detail Unauthorized）', async () => {
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: 'ignored' }));
    const err = await apiFetch('/health').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(KernelOfflineError);
    expect((err as KernelOfflineError).detail).toBe('Unauthorized');
    expect((err as KernelOfflineError).status).toBe(401);
  });

  it('非 JSON 错误体（res.json 抛错）→ 默认 detail `HTTP <status>`', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(500, null, () => Promise.reject(new SyntaxError('Unexpected token'))),
    );
    const err = await apiFetch('/boom').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).detail).toBe('HTTP 500');
  });

  it('JSON detail 为字符串 → 直接取字符串', async () => {
    fetchMock.mockResolvedValue(jsonResponse(400, { detail: '标题必填' }));
    const err = await apiFetch('/bad').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(400);
    expect((err as ApiError).detail).toBe('标题必填');
  });

  it('JSON detail 为对象 → JSON.stringify 序列化', async () => {
    fetchMock.mockResolvedValue(jsonResponse(422, { detail: { field: 'title', code: 'E1' } }));
    const err = await apiFetch('/bad').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).detail).toBe(JSON.stringify({ field: 'title', code: 'E1' }));
  });
});

describe('errorMessage — 三分支', () => {
  it('ApiError → 取 detail', () => {
    expect(errorMessage(new ApiError(422, '校验失败'))).toBe('校验失败');
    expect(errorMessage(new KernelOfflineError('内核离线'))).toBe('内核离线');
  });

  it('普通 Error → 取 message', () => {
    expect(errorMessage(new Error('boom'))).toBe('boom');
  });

  it('其他值 → String() 兜底', () => {
    expect(errorMessage('string err')).toBe('string err');
    expect(errorMessage(42)).toBe('42');
    expect(errorMessage(null)).toBe('null');
  });
});

describe('getApiConfig — 注入源分支', () => {
  it('window.INKFLOW_API 已注入 → 原样返回', () => {
    setInjected({ baseURL: 'http://127.0.0.1:54321', token: 'preload-token' });
    expect(getApiConfig()).toEqual({ baseURL: 'http://127.0.0.1:54321', token: 'preload-token' });
  });

  it('未注入 → 回退 Vite env / 默认地址', () => {
    setInjected(undefined);
    const cfg = getApiConfig();
    expect(cfg.baseURL).toBe('http://127.0.0.1:8000');
    expect(cfg.token).toBe('');
  });
});
