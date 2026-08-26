/**
 * pipeline API 封装契约测试（#298 RED 阶段，spec §5.6 GUI 写作入口管线化）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/api/pipeline.ts 并匹配：
 *
 * export interface PipelineExecuteRequest {
 *   project_id: string;
 *   pipeline: string;
 *   chapter_id?: string;
 *   variables?: Record<string, string>;
 * }
 * export interface PipelineExecuteResponse {
 *   execution_id: string;
 *   pipeline: string;
 *   project_id: string;
 *   status: string;
 *   created_at: string;
 * }
 * export interface PipelineStageSnapshot {
 *   stage_id: string;
 *   status: string;
 *   output: string;
 *   error: string;
 *   retry_count: number;
 *   duration_ms: number;
 * }
 * export interface PipelineExecutionStatus {
 *   execution_id: string;
 *   pipeline: string;
 *   project_id: string;
 *   status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
 *   stages: PipelineStageSnapshot[];
 *   final_output: string;
 *   total_duration_ms: number;
 *   error: string;
 * }
 * export function executePipeline(body: PipelineExecuteRequest): Promise<PipelineExecuteResponse>;
 * export function getExecutionStatus(executionId: string): Promise<PipelineExecutionStatus>;
 *
 * 端点契约（backend api/routers/agent.py 实证）：
 * - POST /api/v1/agent/pipelines/execute（202）→ {execution_id, pipeline, project_id, status, created_at}
 * - GET /api/v1/agent/pipelines/executions/{id} → {execution_id, pipeline, project_id, status, stages, final_output, total_duration_ms, error}
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { executePipeline, getExecutionStatus } from './pipeline';
import { apiFetch } from './client';

vi.mock('./client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 等待微任务链跑完（reader 续体全部在 microtask 内） */
const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe('executePipeline — POST /pipelines/execute', () => {
  it('透传完整请求体（project_id/pipeline/chapter_id/variables）', async () => {
    apiFetchMock.mockResolvedValue({
      execution_id: 'e1',
      pipeline: 'builtin:write_auto',
      project_id: 'p1',
      status: 'pending',
      created_at: '2026-08-13T10:00:00Z',
    });
    await executePipeline({
      project_id: 'p1',
      pipeline: 'builtin:write_auto',
      chapter_id: 'c1',
      variables: { tags: '玄幻', target_words: '800000' },
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/pipelines/execute', {
      method: 'POST',
      body: {
        project_id: 'p1',
        pipeline: 'builtin:write_auto',
        chapter_id: 'c1',
        variables: { tags: '玄幻', target_words: '800000' },
      },
    });
  });

  it('chapter_id / variables 可选（缺省不注入）', async () => {
    apiFetchMock.mockResolvedValue({
      execution_id: 'e2',
      pipeline: 'builtin:write_continue',
      project_id: 'p1',
      status: 'pending',
      created_at: '',
    });
    await executePipeline({ project_id: 'p1', pipeline: 'builtin:write_continue' });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/pipelines/execute', {
      method: 'POST',
      body: { project_id: 'p1', pipeline: 'builtin:write_continue' },
    });
  });

  it('返回执行响应（execution_id 供后续轮询）', async () => {
    const resp = {
      execution_id: 'e3',
      pipeline: 'builtin:write_auto',
      project_id: 'p1',
      status: 'pending',
      created_at: '2026-08-13T10:00:00Z',
    };
    apiFetchMock.mockResolvedValue(resp);
    await expect(executePipeline({ project_id: 'p1', pipeline: 'builtin:write_auto' })).resolves.toEqual(resp);
  });
});

describe('getExecutionStatus — GET /pipelines/executions/{id}', () => {
  it('按 execution_id 查询，返回完整执行状态', async () => {
    const status = {
      execution_id: 'e1',
      pipeline: 'builtin:write_auto',
      project_id: 'p1',
      status: 'completed' as const,
      stages: [
        { stage_id: 'reviser', status: 'completed', output: '成品内容', error: '', retry_count: 0, duration_ms: 500 },
      ],
      final_output: '成品内容',
      total_duration_ms: 1200,
      error: '',
    };
    apiFetchMock.mockResolvedValue(status);
    await expect(getExecutionStatus('e1')).resolves.toEqual(status);
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/pipelines/executions/e1');
  });

  it('失败状态透传 error 字段', async () => {
    const failed = {
      execution_id: 'e9',
      pipeline: 'builtin:write_auto',
      project_id: 'p1',
      status: 'failed' as const,
      stages: [],
      final_output: '',
      total_duration_ms: 800,
      error: '管线执行失败: 阶段 writer 重试耗尽',
    };
    apiFetchMock.mockResolvedValue(failed);
    await expect(getExecutionStatus('e9')).resolves.toEqual(failed);
  });
});

/**
 * #681 streamPipeline SSE 流式（#642-1 现状）+ 进度帧 + 超时兜底 RED
 *
 * G5a 实锤：streamPipeline（api/pipeline.ts:141-215）fetch 无超时（仅 AbortController 供主动 abort），
 * SSE 帧无 stage/无「生成较慢」提示。RED 锁定：
 * - onDone 帧可携带 execution_id（#681 执行详情页数据源，透传 useExecutionPoll.onDone 捕获）
 * - type='stage' 帧 → onStage({stage_id, stage_name})（管线进度帧）
 * - fetch 加 AbortController timeout（超时 → onError('模型生成较慢') 类提示）
 */
describe('streamPipeline — 管线进度帧 + 超时兜底（#681）', () => {
  const BASE = 'http://api.test';

  function makeReader() {
    const pending: { resolve: (r: { done: boolean; value?: Uint8Array }) => void; reject: (e: unknown) => void }[] = [];
    const reader = {
      read: () =>
        new Promise<{ done: boolean; value?: Uint8Array }>((resolve, reject) => {
          pending.push({ resolve, reject });
        }),
    } as ReadableStreamDefaultReader;
    const api = {
      push(chunk: Uint8Array) {
        pending.shift()?.resolve({ done: false, value: chunk });
      },
      end() {
        pending.shift()?.resolve({ done: true });
      },
      fail(err: unknown) {
        pending.shift()?.reject(err);
      },
    };
    return { reader, api };
  }

  interface FetchCall {
    url: string;
    init: RequestInit;
    api: ReturnType<typeof makeReader>['api'];
  }

  function stubStreamFetch(calls: FetchCall[]) {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const { reader, api } = makeReader();
      calls.push({ url, init: init ?? {}, api });
      return Promise.resolve({
        ok: true,
        status: 200,
        body: { getReader: () => reader },
      } as unknown as Response);
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  function frame(payload: Record<string, unknown>): Uint8Array {
    return new TextEncoder().encode(`data: ${JSON.stringify(payload)}\n\n`);
  }

  beforeEach(() => {
    vi.useFakeTimers();
    window.INKFLOW_API = { baseURL: BASE, token: 'tok-1' };
  });

  afterEach(() => {
    delete window.INKFLOW_API;
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('type="stage" 帧 → onStage({stage_id, stage_name})；type="done" 帧携带 execution_id', async () => {
    const { streamPipeline } = await import('./pipeline');
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const callbacks = {
      onStage: vi.fn(),
      onDelta: vi.fn(),
      onDone: vi.fn(),
      onError: vi.fn(),
    };
    const body = { project_id: 'p1', pipeline: 'builtin:write_auto' };

    await streamPipeline(body, callbacks);
    await flush();

    const reader = calls[0].api;
    reader.push(frame({ type: 'stage', stage_id: 'writer', stage_name: '写手', done: false }));
    await flush();
    expect(callbacks.onStage).toHaveBeenCalledWith({ stage_id: 'writer', stage_name: '写手' });

    reader.push(frame({ type: 'delta', delta: '正', done: false }));
    await flush();
    expect(callbacks.onDelta).toHaveBeenCalledWith('正');

    reader.push(frame({ type: 'done', done: true, final_output: '成品', execution_id: 'exec-9' }));
    await flush();
    expect(callbacks.onDone).toHaveBeenCalledWith(
      expect.objectContaining({ final_output: '成品', execution_id: 'exec-9' }),
    );
  });

  it('fetch 超时 → onError「模型生成较慢」提示（AbortController timeout 兜底）', async () => {
    const { streamPipeline } = await import('./pipeline');
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const callbacks = {
      onStage: vi.fn(),
      onDelta: vi.fn(),
      onDone: vi.fn(),
      onError: vi.fn(),
    };
    const body = { project_id: 'p1', pipeline: 'builtin:write_auto' };

    await streamPipeline(body, callbacks);
    await flush();

    // 进入读取但无帧到达（超时窗口内无任何 SSE 帧）→ 触发超时 onError
    vi.advanceTimersByTime(60000);
    await flush();

    expect(callbacks.onError).toHaveBeenCalled();
    expect(String(callbacks.onError.mock.calls[0][0])).toContain('生成较慢');
    expect(callbacks.onDone).not.toHaveBeenCalled();
  });
});
