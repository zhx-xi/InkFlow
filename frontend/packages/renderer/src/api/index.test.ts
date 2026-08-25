/**
 * #657 索引重建 API 契约测试（后端 #659 配套：异步重建 + 进度轮询）
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/api/index.ts，必须导出：
 * - interface IndexRebuildParams：{ project_ids?: string[] | null; scope?: 'fulltext' | 'vector' | 'both' }
 *   （project_ids 缺省/null = 全部项目；scope 缺省 = 'both'）
 * - interface IndexRebuildStartDto：{ task_id: string; status: string }
 *   （对齐 POST /index/rebuild 202 响应）
 * - interface IndexRebuildStatusDto：{ status: 'running' | 'done' | 'failed'; step: 'fulltext' | 'vector';
 *   progress_done: number; progress_total: number; rebuilt_at: string | null; error: string | null }
 *   （对齐 GET /index/rebuild/status 响应）
 * - postIndexRebuild(params: IndexRebuildParams): Promise<IndexRebuildStartDto>
 *   → POST /api/v1/index/rebuild，body { project_ids, scope }
 * - fetchIndexRebuildStatus(taskId: string): Promise<IndexRebuildStatusDto>
 *   → GET /api/v1/index/rebuild/status?task_id=<id>
 *
 * 测试策略：不 mock ../api/client（#107 vi.mock 闭包坑）——直接 spy 全局
 * fetch，apiFetch 真实执行；window.INKFLOW_API 注入固定 baseURL/token
 * （vector.test.ts / audit.test.ts 同款），URL 可精确断言。
 * 错误契约：HTTP 非 2xx → ApiError（status/detail 透传）。
 *
 * RED 预期：./index 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { postIndexRebuild, fetchIndexRebuildStatus } from './index';
import { ApiError } from './client';

const BASE = 'http://api.test';

/** 契约结构镜像（GREEN 类型从 index.ts 导出；本文件内联镜像供 mock 播种） */
interface IndexRebuildStatusDto {
  status: 'running' | 'done' | 'failed';
  step: 'fulltext' | 'vector';
  progress_done: number;
  progress_total: number;
  rebuilt_at: string | null;
  error: string | null;
}

const runningDto: IndexRebuildStatusDto = {
  status: 'running',
  step: 'fulltext',
  progress_done: 3,
  progress_total: 7,
  rebuilt_at: null,
  error: null,
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

describe('postIndexRebuild', () => {
  it('POST /index/rebuild body：project_ids + scope 透传（both 默认）', async () => {
    mockFetchOnce({ task_id: 'task-1', status: 'running' });
    const result = await postIndexRebuild({ project_ids: ['p1'], scope: 'both' });
    expect(result.task_id).toBe('task-1');
    expect(result.status).toBe('running');
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/index/rebuild`);
    expect(init?.method).toBe('POST');
    const body = JSON.parse(String(init?.body));
    expect(body.project_ids).toEqual(['p1']);
    expect(body.scope).toBe('both');
  });

  it('缺省 project_ids → body.project_ids=null（全部项目），scope=fulltext', async () => {
    mockFetchOnce({ task_id: 'task-2', status: 'running' });
    const result = await postIndexRebuild({ scope: 'fulltext' });
    expect(result.task_id).toBe('task-2');
    const init = vi.mocked(fetch).mock.calls[0][1];
    const body = JSON.parse(String(init?.body));
    expect(body.project_ids).toBeNull();
    expect(body.scope).toBe('fulltext');
  });

  it('scope=vector 透传', async () => {
    mockFetchOnce({ task_id: 'task-3', status: 'running' });
    await postIndexRebuild({ project_ids: ['p1', 'p2'], scope: 'vector' });
    const init = vi.mocked(fetch).mock.calls[0][1];
    const body = JSON.parse(String(init?.body));
    expect(body.scope).toBe('vector');
    expect(body.project_ids).toEqual(['p1', 'p2']);
  });

  it('HTTP 非 2xx → ApiError（status/detail 透传）', async () => {
    mockFetchOnce({ detail: 'scope 非法' }, 422);
    await expect(postIndexRebuild({ scope: 'bad' as never })).rejects.toBeInstanceOf(ApiError);
    try {
      await postIndexRebuild({ scope: 'bad' as never });
    } catch (e) {
      expect((e as ApiError).status).toBe(422);
    }
  });
});

describe('fetchIndexRebuildStatus', () => {
  it('GET /index/rebuild/status?task_id=<id> 并解析响应字段', async () => {
    mockFetchOnce(runningDto);
    const result = await fetchIndexRebuildStatus('task-1');
    expect(result.status).toBe('running');
    expect(result.step).toBe('fulltext');
    expect(result.progress_done).toBe(3);
    expect(result.progress_total).toBe(7);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/index/rebuild/status?task_id=task-1`);
    expect(init?.method).toBe('GET');
  });

  it('done 响应（rebuilt_at 非空）原样解析', async () => {
    mockFetchOnce({
      ...runningDto,
      status: 'done',
      progress_done: 7,
      progress_total: 7,
      rebuilt_at: '2026-08-25T12:30:00Z',
    });
    const result = await fetchIndexRebuildStatus('task-1');
    expect(result.status).toBe('done');
    expect(result.rebuilt_at).toBe('2026-08-25T12:30:00Z');
  });

  it('failed 响应（error 非空）原样解析', async () => {
    mockFetchOnce({
      ...runningDto,
      status: 'failed',
      error: 'embedding 模型不可用',
    });
    const result = await fetchIndexRebuildStatus('task-1');
    expect(result.status).toBe('failed');
    expect(result.error).toBe('embedding 模型不可用');
  });

  it('HTTP 非 2xx → ApiError（status/detail 透传）', async () => {
    mockFetchOnce({ detail: 'task_id 未注册' }, 404);
    await expect(fetchIndexRebuildStatus('nope')).rejects.toBeInstanceOf(ApiError);
    try {
      await fetchIndexRebuildStatus('nope');
    } catch (e) {
      expect((e as ApiError).status).toBe(404);
    }
  });
});
