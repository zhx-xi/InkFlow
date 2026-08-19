/**
 * #480 检索 API 契约测试（Issue #480 RAG embedding 增强检索）
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/api/search.ts，必须导出：
 * - interface SearchHitDto { entity_type: string; entity_id: string; project_id: string;
 *   title: string; snippet: string; score: number }
 * - interface SearchResponseDto { total: number; hits: SearchHitDto[]; query: string;
 *   types: string[] | null; mode: 'keyword' | 'semantic'; project_ids: string[] }
 * - interface SearchParams { q: string; projectId: string; mode?: 'keyword' | 'semantic';
 *   types?: string[]; limit?: number; offset?: number }
 * - fetchSearch(params: SearchParams): Promise<SearchResponseDto>
 *   → GET /api/v1/search，URL 参数契约（对齐后端 GET /api/v1/search，routers/search.py）：
 *     q（必填，1-100）／project_id／mode（缺省 → 'semantic'，本轨默认语义检索；
 *     后端缺省 keyword 但前端本轨拍板默认 semantic）／types（逗号分隔）／
 *     limit／offset（缺省不携带，后端默认 20/0）
 *
 * 测试策略：不 mock ../api/client（#107 vi.mock 闭包坑）——直接 spy 全局 fetch，
 * apiFetch 真实执行；window.INKFLOW_API 注入固定 baseURL/token（vector.test.ts 同款），
 * URL 用 new URL 解析 searchParams 精确断言（q 中文自动 encodeURIComponent）。
 * 错误契约：HTTP 非 2xx → ApiError（status/detail 透传）。
 *
 * RED 预期：./search 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchSearch } from './search';
import { ApiError } from './client';

const BASE = 'http://api.test';
const PID = '3f2e1d4a-0000-4000-8000-000000000002';

/** 契约结构镜像（GREEN 类型从 search.ts 导出；本文件内联镜像供 mock 播种） */
interface SearchHitDto {
  entity_type: string;
  entity_id: string;
  project_id: string;
  title: string;
  snippet: string;
  score: number;
}

interface SearchResponseDto {
  total: number;
  hits: SearchHitDto[];
  query: string;
  types: string[] | null;
  mode: 'keyword' | 'semantic';
  project_ids: string[];
}

const searchResponseDto: SearchResponseDto = {
  total: 2,
  hits: [
    { entity_type: 'character', entity_id: 'e1', project_id: PID, title: '林惊羽', snippet: '青云门弟子…', score: 0.87 },
    { entity_type: 'chapter', entity_id: 'e2', project_id: PID, title: '第一章 青云山', snippet: '青云山脚下…', score: 0.72 },
  ],
  query: '青云',
  types: null,
  mode: 'semantic',
  project_ids: [PID],
};

function mockFetchOnce(body: unknown, status = 200): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }),
  );
}

beforeEach(() => {
  Object.defineProperty(window, 'INKFLOW_API', {
    configurable: true,
    value: { baseURL: BASE, token: 'test-token' },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('fetchSearch — URL 拼装', () => {
  it('q/projectId/mode 拼入 URL（GET /api/v1/search，中文 q 正确编码）', async () => {
    mockFetchOnce(searchResponseDto);
    await fetchSearch({ q: '青云', projectId: PID, mode: 'semantic' });

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('GET');
    expect(String(url)).toContain(`${BASE}/api/v1/search?`);
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe('/api/v1/search');
    expect(parsed.searchParams.get('q')).toBe('青云'); // encodeURIComponent 后解码等价
    expect(parsed.searchParams.get('project_id')).toBe(PID);
    expect(parsed.searchParams.get('mode')).toBe('semantic');
  });

  it('缺省 mode → URL mode=semantic（本轨默认语义检索）', async () => {
    mockFetchOnce(searchResponseDto);
    await fetchSearch({ q: 'x', projectId: PID });

    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.searchParams.get('mode')).toBe('semantic');
  });

  it('limit/offset 透传；缺省不携带（后端默认 20/0）', async () => {
    mockFetchOnce(searchResponseDto);
    await fetchSearch({ q: 'x', projectId: PID, limit: 10, offset: 20 });

    let url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.searchParams.get('limit')).toBe('10');
    expect(url.searchParams.get('offset')).toBe('20');

    mockFetchOnce(searchResponseDto);
    await fetchSearch({ q: 'x', projectId: PID });
    // mockFetchOnce 每次调用都重新 stubGlobal（全新 vi.fn）→ 读新 mock 的 calls[0]
    url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.searchParams.has('limit')).toBe(false);
    expect(url.searchParams.has('offset')).toBe(false);
  });

  it('types 数组 → 逗号分隔（character,world）', async () => {
    mockFetchOnce(searchResponseDto);
    await fetchSearch({ q: 'x', projectId: PID, types: ['character', 'world'] });

    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.searchParams.get('types')).toBe('character,world');
  });
});

describe('fetchSearch — 响应解析与错误契约', () => {
  it('响应解析：total / hits[0].title / score / mode 正确', async () => {
    mockFetchOnce(searchResponseDto);
    const result = await fetchSearch({ q: '青云', projectId: PID });

    expect(result.total).toBe(2);
    expect(result.hits[0].title).toBe('林惊羽');
    expect(result.hits[0].score).toBe(0.87);
    expect(result.mode).toBe('semantic');
    expect(result.project_ids).toEqual([PID]);
  });

  it('HTTP 非 2xx → ApiError（status/detail 透传）', async () => {
    mockFetchOnce({ detail: '项目不存在' }, 404);
    await expect(fetchSearch({ q: 'x', projectId: PID })).rejects.toBeInstanceOf(ApiError);
    try {
      await fetchSearch({ q: 'x', projectId: PID });
    } catch (e) {
      expect((e as ApiError).status).toBe(404);
      expect((e as ApiError).detail).toBe('项目不存在');
    }
  });
});
