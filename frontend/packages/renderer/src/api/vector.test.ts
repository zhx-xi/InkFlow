/**
 * #276 S2c RAG 向量状态/重建 API 契约测试（Issue #276，范围 3/4）
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/api/vector.ts，必须导出：
 * - interface VectorStatusDto：{ configured_fp: FingerprintDto | null;
 *   indexed_fp: FingerprintDto | null; stale: boolean; reason: string | null;
 *   dimension_mismatch: boolean }（对齐后端 GET /vector/status 响应）
 * - interface FingerprintDto：{ schema_version: number;
 *   embedding: { provider: string; model_id: string; base_url: string;
 *   dimension: number | null }; chunking: { mode: string; chunk_size: number;
 *   overlap_ratio: number; chunker_version: number };
 *   indexed_at: string | null; status: string }
 * - interface ReindexResultDto：{ project_id: string; entity_types: string[];
 *   indexed: number; warnings: string[]; collections_recreated: boolean }
 * - fetchVectorStatus(projectId: string): Promise<VectorStatusDto>
 *   → GET /api/v1/projects/{projectId}/vector/status（200 语义，状态查询不炸）
 * - postVectorReindex(projectId: string, entityTypes?: string[]):
 *   Promise<ReindexResultDto>
 *   → POST /api/v1/projects/{projectId}/vector/reindex，body { entity_types }，
 *   缺省 → null（服务层全量 5 种）
 *
 * 测试策略：不 mock ../api/client（#107 vi.mock 闭包坑）——直接 spy 全局
 * fetch，apiFetch 真实执行；window.INKFLOW_API 注入固定 baseURL/token
 * （audit.test.ts / client.test.ts 同款），URL 可精确断言。
 * 错误契约：HTTP 非 2xx → ApiError（status/detail 透传）。
 *
 * RED 预期：./vector 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchVectorStatus, postVectorReindex } from './vector';
import { ApiError } from './client';

const BASE = 'http://api.test';
const PID = '3f2e1d4a-0000-4000-8000-000000000001';

/** 契约结构镜像（GREEN 类型从 vector.ts 导出；本文件内联镜像供 mock 播种） */
interface FingerprintDto {
  schema_version: number;
  embedding: {
    provider: string;
    model_id: string;
    base_url: string;
    dimension: number | null;
  };
  chunking: { mode: string; chunk_size: number; overlap_ratio: number; chunker_version: number };
  indexed_at: string | null;
  status: string;
}

interface VectorStatusDto {
  configured_fp: FingerprintDto | null;
  indexed_fp: FingerprintDto | null;
  stale: boolean;
  reason: string | null;
  dimension_mismatch: boolean;
}

const fingerprint: FingerprintDto = {
  schema_version: 1,
  embedding: {
    provider: 'openai',
    model_id: 'text-embedding-3-small',
    base_url: `${BASE}/v1`,
    dimension: 384,
  },
  chunking: { mode: 'fixed', chunk_size: 500, overlap_ratio: 0, chunker_version: 1 },
  indexed_at: '2026-08-12T08:00:00Z',
  status: 'fresh',
};

const statusDto: VectorStatusDto = {
  configured_fp: fingerprint,
  indexed_fp: fingerprint,
  stale: false,
  reason: null,
  dimension_mismatch: false,
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

describe('fetchVectorStatus', () => {
  it('GET /vector/status 并解析响应字段', async () => {
    mockFetchOnce(statusDto);
    const result = await fetchVectorStatus(PID);
    expect(result).toEqual(statusDto);
    expect(result.stale).toBe(false);
    expect(result.configured_fp?.embedding.model_id).toBe('text-embedding-3-small');
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/projects/${PID}/vector/status`);
    expect(init?.method).toBe('GET');
  });

  it('stale 响应（unknown reason）原样解析', async () => {
    mockFetchOnce({ ...statusDto, indexed_fp: null, stale: true, reason: 'unknown' });
    const result = await fetchVectorStatus(PID);
    expect(result.stale).toBe(true);
    expect(result.reason).toBe('unknown');
    expect(result.indexed_fp).toBeNull();
  });

  it('HTTP 非 2xx → ApiError（status/detail 透传）', async () => {
    mockFetchOnce({ detail: '项目不存在' }, 404);
    await expect(fetchVectorStatus(PID)).rejects.toBeInstanceOf(ApiError);
    try {
      await fetchVectorStatus(PID);
    } catch (e) {
      expect((e as ApiError).status).toBe(404);
    }
  });
});

describe('postVectorReindex', () => {
  it('POST /vector/reindex body entity_types 透传', async () => {
    mockFetchOnce({
      project_id: PID,
      entity_types: ['character', 'setting'],
      indexed: 12,
      warnings: [],
      collections_recreated: false,
    });
    const result = await postVectorReindex(PID, ['character', 'setting']);
    expect(result.indexed).toBe(12);
    expect(result.collections_recreated).toBe(false);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/projects/${PID}/vector/reindex`);
    expect(init?.method).toBe('POST');
    const body = JSON.parse(String(init?.body));
    expect(body.entity_types).toEqual(['character', 'setting']);
  });

  it('缺省 entityTypes → body entity_types=null（服务层全量）', async () => {
    mockFetchOnce({
      project_id: PID,
      entity_types: ['character', 'setting', 'foreshadowing', 'timeline_event', 'chapter_chunk'],
      indexed: 87,
      warnings: [],
      collections_recreated: false,
    });
    const result = await postVectorReindex(PID);
    expect(result.indexed).toBe(87);
    const init = vi.mocked(fetch).mock.calls[0][1];
    const body = JSON.parse(String(init?.body));
    expect(body.entity_types).toBeNull();
  });

  it('维度不匹配重建 → collections_recreated=true 解析', async () => {
    mockFetchOnce({
      project_id: PID,
      entity_types: ['character'],
      indexed: 42,
      warnings: [],
      collections_recreated: true,
    });
    const result = await postVectorReindex(PID, ['character']);
    expect(result.collections_recreated).toBe(true);
  });
});
