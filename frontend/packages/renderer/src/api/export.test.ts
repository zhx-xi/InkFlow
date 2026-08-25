/**
 * 项目导出 API 契约测试（exportProjectFile）
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/api/export.ts，必须导出：
 * - interface ExportFileOptions { includeSettings: boolean; fallbackBaseName: string }
 * - interface ExportFileResult { filename: string; content: string }
 * - export async function exportProjectFile(
 *     projectId: string, opts: ExportFileOptions,
 *   ): Promise<ExportFileResult>
 *   → GET /api/v1/projects/{projectId}/export?format=txt[&include_settings=true]
 *   → 200 text/plain：filename 取 Content-Disposition filename*（RFC 5987 UTF-8 百分号解码），
 *     缺失时回退 `${fallbackBaseName}-txt.txt`；401 → KernelOfflineError；其他非 2xx → ApiError
 *
 * 测试策略：不 mock ../api/client（#107 vi.mock 闭包坑——apiFetch 模块内闭包不被导出层替换影响），
 * 直接 spy 全局 fetch，apiFetch 真实执行；window.INKFLOW_API 注入固定 baseURL/token，
 * URL 可精确断言。响应体为 text/plain（非 JSON）：mock 用真实 `new Response(text, {...})`，
 * 锁 res.text() 读取路径（非 res.json()）。
 *
 * RED 预期：./export 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { exportProjectFile } from './export';
import { ApiError, errorMessage, KernelOfflineError } from './client';

const BASE = 'http://local';

function setInjected(cfg: { baseURL: string; token: string } | undefined): void {
  Object.defineProperty(window, 'INKFLOW_API', {
    configurable: true,
    value: cfg,
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  setInjected({ baseURL: BASE, token: 'tok' });
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

describe('exportProjectFile — 请求形态', () => {
  it('includeSettings=true → URL 含 include_settings=true，带 X-InkFlow-Token 头', async () => {
    fetchMock.mockResolvedValue(
      new Response('正文', { status: 200, headers: { 'Content-Type': 'text/plain; charset=utf-8' } }),
    );
    await exportProjectFile('p1', { includeSettings: true, fallbackBaseName: '剑来' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const { url, init } = lastFetchCall();
    expect(url).toBe(`${BASE}/api/v1/projects/p1/export?format=txt&include_settings=true`);
    const headers = init.headers as Headers;
    expect(headers.get('X-InkFlow-Token')).toBe('tok');
  });

  it('includeSettings=false → URL 为 /export?format=txt（不含 include_settings）', async () => {
    fetchMock.mockResolvedValue(
      new Response('正文', { status: 200, headers: { 'Content-Type': 'text/plain; charset=utf-8' } }),
    );
    await exportProjectFile('p1', { includeSettings: false, fallbackBaseName: '剑来' });

    const { url } = lastFetchCall();
    expect(url).toBe(`${BASE}/api/v1/projects/p1/export?format=txt`);
  });
});

describe('exportProjectFile — 错误契约', () => {
  it('401 → KernelOfflineError', async () => {
    fetchMock.mockResolvedValue(new Response('Unauthorized', { status: 401 }));
    const err = await exportProjectFile('p1', { includeSettings: false, fallbackBaseName: '剑来' }).catch(
      (e: unknown) => e,
    );

    expect(err).toBeInstanceOf(KernelOfflineError);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as KernelOfflineError).status).toBe(401);
  });

  it('404 + detail JSON → ApiError(404, detail)，errorMessage 可读', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: '项目不存在' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const err = await exportProjectFile('p1', { includeSettings: false, fallbackBaseName: '剑来' }).catch(
      (e: unknown) => e,
    );

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).detail).toBe('项目不存在');
    expect(errorMessage(err)).toBe('项目不存在');
  });
});

describe('exportProjectFile — 成功解析（text/plain）', () => {
  it('200 + Content-Disposition filename* → filename 为 UTF-8 解码文件名，content 为响应文本', async () => {
    const body = '第一章 剑来\n正文内容';
    fetchMock.mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: {
          'Content-Type': 'text/plain; charset=utf-8',
          'Content-Disposition': "attachment; filename*=UTF-8''%E5%89%91%E6%9D%A5-txt.txt",
        },
      }),
    );

    const result = await exportProjectFile('p1', { includeSettings: false, fallbackBaseName: '剑来' });
    expect(result.filename).toBe('剑来-txt.txt');
    expect(result.content).toBe(body);
  });

  it('200 + 无 Content-Disposition → filename 回退 `${fallbackBaseName}-txt.txt`', async () => {
    fetchMock.mockResolvedValue(
      new Response('正文', { status: 200, headers: { 'Content-Type': 'text/plain; charset=utf-8' } }),
    );

    const result = await exportProjectFile('p1', { includeSettings: false, fallbackBaseName: '剑来' });
    expect(result.filename).toBe('剑来-txt.txt');
    expect(result.content).toBe('正文');
  });
});
