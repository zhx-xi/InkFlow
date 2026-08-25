/**
 * useExecutionPoll hook 契约（#472 R0 前置重构：统一管线执行/轮询）
 *
 * ⚠️ 本文件 = 契约。#642-1（缺陷 A）后 start 路径由 executePipeline+轮询 改为 streamPipeline SSE 流式：
 *
 * export type PipelineRunStatus = 'idle' | 'running' | 'success' | 'failed' | 'awaiting_human';
 * export interface UseExecutionPollResult {
 *   status: PipelineRunStatus;
 *   error: string | null;
 *   finalOutput: string;
 *   totalDurationMs: number;
 *   hitlPending: { question: string; role: string } | null;
 *   executionId: string | null; // #543：仅 poll(executionId) 记录（流式 start 无 execution_id）
 *   streamSinkRef: MutableRefObject<PipelineStreamSink>; // #642-1：流式回调 sink（ChatPanel 注册复用）
 *   start: (body: PipelineExecuteRequest) => void;   // 并发保护：执行中再次调用 = 无操作
 *   confirm: (approved: boolean) => void;            // HITL 确认；无 executionId = 无操作
 *   poll: (executionId: string) => void;             // 手动启动轮询（同时记录 executionId 供 confirm）
 * }
 * export function useExecutionPoll(): UseExecutionPollResult;
 *
 * 行为契约（#642-1 流式 + #472 R0 语义）：
 * - start(body) → status='running' + streamPipeline(body, {onDelta/onDone/onToolCall/onToolResult/onError})：
 *   onDelta(d) → 透传 streamSinkRef.onDelta（ChatPanel 流式渲染）
 *   onDone(f)  → streamSinkRef.onDone + finalOutput=f.final_output + error=null + status='success'
 *   onError(m) → error=m + status='failed'
 *   （#642-1：流式帧无 hitl/duration 类型；executionId 不在 start 路径产生）
 * - poll(executionId) 手动轮询 getExecutionStatus（1s 间隔）：
 *   completed → success + finalOutput/totalDurationMs；failed → failed + error；
 *   waiting_hitl → awaiting_human + hitlPending + 停止轮询
 * - confirm(approved) → confirmExecution(executionId, approved) + 续跑轮询（无 executionId = 无操作）
 * - 并发保护：执行中再次 start 无操作（streamPipeline 仅 1 次）；终态后允许再次 start
 * - 轮询网络失败 → status='failed' + error
 * - 卸载停止轮询（不再调 getExecutionStatus）
 * - 生命周期（timer/executionId）不入任何 store（纯组件内状态）
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useExecutionPoll } from './useExecutionPoll';
import {
  streamPipeline,
  executePipeline,
  getExecutionStatus,
  confirmExecution,
} from '../api/pipeline';

vi.mock('../api/pipeline', () => ({
  streamPipeline: vi.fn(),
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

const streamPipelineMock = vi.mocked(streamPipeline);
const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);
const confirmMock = vi.mocked(confirmExecution);

/** #642-1：每次 streamPipeline 调用的 body/callbacks 捕获（用例手动驱动 SSE 帧） */
interface CapturedPipelineStream {
  body: {
    project_id: string;
    pipeline: string;
    chapter_id?: string;
    variables?: Record<string, string>;
    mode?: string;
    supervisor?: { hitl_roles: string[] };
  };
  callbacks: {
    onDelta: (delta: string) => void;
    onDone: (frame: { done: boolean; final_output?: string }) => void;
    onError: (message: string) => void;
    onToolCall?: (call: { id: string; name: string; args: Record<string, unknown> }) => void;
    onToolResult?: (res: { id: string; name: string; result: string }) => void;
  };
}
let capturedStream: CapturedPipelineStream | null = null;

const BODY = {
  project_id: 'p1',
  pipeline: 'builtin:chat',
  variables: { prompt: '你好' },
};

const PENDING = {
  execution_id: 'e1',
  pipeline: 'builtin:chat',
  project_id: 'p1',
  status: 'pending' as const,
  stages: [],
  final_output: '',
  total_duration_ms: 0,
  error: '',
};

beforeEach(() => {
  vi.useFakeTimers();
  streamPipelineMock.mockReset();
  executeMock.mockReset();
  statusMock.mockReset();
  confirmMock.mockReset();
  capturedStream = null;
  // 默认 streamPipeline 捕获 callbacks，不自动 emit（用例手动驱动帧）
  streamPipelineMock.mockImplementation((_body, callbacks) => {
    capturedStream = {
      body: _body as CapturedPipelineStream['body'],
      callbacks: callbacks as CapturedPipelineStream['callbacks'],
    };
    return Promise.resolve(() => {});
  });
  statusMock.mockResolvedValue(PENDING);
});

afterEach(() => {
  vi.useRealTimers();
  capturedStream = null;
});

describe('useExecutionPoll — 状态机（idle → running → success | failed | awaiting_human）', () => {
  it('初始状态：idle / 无错误 / 空成品 / 无 HITL / 无 executionId', () => {
    const { result } = renderHook(() => useExecutionPoll());
    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
    expect(result.current.finalOutput).toBe('');
    expect(result.current.totalDurationMs).toBe(0);
    expect(result.current.hitlPending).toBeNull();
    // #543：初始无 executionId（执行详情页数据源）
    expect(result.current.executionId).toBeNull();
  });

  it('start（#642-1 流式）不产生 executionId；poll(executionId) 记录并终态保留（#543）', async () => {
    statusMock.mockResolvedValue({
      ...PENDING,
      status: 'completed',
      final_output: 'x',
      total_duration_ms: 100,
    });
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    // 流式路径无 execution_id 响应 → start 后 executionId 保持 null
    expect(result.current.executionId).toBeNull();
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
    expect(result.current.status).toBe('success');
    expect(result.current.executionId).toBeNull();
    // poll 手动记录 executionId（执行详情页数据源），终态保留
    act(() => {
      result.current.poll('e1');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.executionId).toBe('e1');
    expect(result.current.status).toBe('success');
  });

  it('start(body)：status=running + streamPipeline(body) 精确 body（#642-1 取代 executePipeline）', async () => {
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    expect(result.current.status).toBe('running');
    expect(streamPipelineMock).toHaveBeenCalledTimes(1);
    expect(streamPipelineMock).toHaveBeenCalledWith(
      BODY,
      expect.objectContaining({
        onDelta: expect.any(Function),
        onDone: expect.any(Function),
        onError: expect.any(Function),
      }),
    );
    // 旧 executePipeline 入口不再被调用（#642-1 替换断言）
    expect(executeMock).not.toHaveBeenCalled();
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
    expect(result.current.status).toBe('success');
  });

  it('onDelta 流式透传 sink + onDone(final_output) → success + finalOutput（#642-1）', async () => {
    const { result } = renderHook(() => useExecutionPoll());
    const sinkDelta = vi.fn();
    const sinkDone = vi.fn();
    result.current.streamSinkRef.current.onDelta = sinkDelta;
    result.current.streamSinkRef.current.onDone = sinkDone;
    act(() => {
      result.current.start(BODY);
    });
    act(() => {
      capturedStream?.callbacks.onDelta('对话回复');
    });
    // 流式增量透传 ChatPanel sink（#642-1 复用既有流式渲染）
    expect(sinkDelta).toHaveBeenCalledWith('对话回复');
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: '对话回复内容' });
    });
    expect(sinkDone).toHaveBeenCalledWith({ done: true, final_output: '对话回复内容' });
    expect(result.current.status).toBe('success');
    expect(result.current.finalOutput).toBe('对话回复内容');
    expect(result.current.error).toBeNull();
    // 流式帧无 duration 字段 → totalDurationMs 保持 0（不再从轮询状态获取）
    expect(result.current.totalDurationMs).toBe(0);
  });

  it('onError → failed + error 透传（#642-1）', async () => {
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    act(() => {
      capturedStream?.callbacks.onError('LLM 调用失败');
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('LLM 调用失败');
  });

  it('poll 轮询 waiting_hitl：awaiting_human + hitlPending 暴露 + 停止轮询（getExecutionStatus 契约保留）', async () => {
    statusMock.mockResolvedValue({
      ...PENDING,
      status: 'waiting_hitl',
      hitl_pending: { question: '确认执行下一角色 reviser？', role: 'reviser' },
    });
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.poll('e1');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.status).toBe('awaiting_human');
    expect(result.current.hitlPending).toEqual({
      question: '确认执行下一角色 reviser？',
      role: 'reviser',
    });
    // 终态后不再轮询（无 timer 排程）
    const statusCalls = statusMock.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(statusMock.mock.calls.length).toBe(statusCalls);
  });
});

describe('useExecutionPoll — confirm / 并发保护 / 失败路径', () => {
  it('confirm(true)：confirmExecution(e1, true) + 续跑轮询 → completed → success', async () => {
    statusMock
      .mockResolvedValueOnce({
        ...PENDING,
        status: 'waiting_hitl',
        hitl_pending: { question: '确认继续？', role: 'reviser' },
      })
      .mockResolvedValueOnce({ ...PENDING, status: 'completed', final_output: '确认后成品' });
    confirmMock.mockResolvedValue({ execution_id: 'e1', status: 'completed', final_output: '确认后成品' });
    const { result } = renderHook(() => useExecutionPoll());
    // #642-1：start 走流式不轮询；HITL 中断经 poll 路径（executionId 记录）
    act(() => {
      result.current.poll('e1');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.status).toBe('awaiting_human');
    act(() => {
      result.current.confirm(true);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(confirmMock).toHaveBeenCalledWith('e1', true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.status).toBe('success');
    expect(result.current.finalOutput).toBe('确认后成品');
  });

  it('confirm(false)：confirmExecution(e1, false)', async () => {
    statusMock.mockResolvedValue({
      ...PENDING,
      status: 'waiting_hitl',
      hitl_pending: { question: '确认继续？', role: 'reviser' },
    });
    confirmMock.mockResolvedValue({ execution_id: 'e1', status: 'completed', final_output: '' });
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.poll('e1');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    act(() => {
      result.current.confirm(false);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(confirmMock).toHaveBeenCalledWith('e1', false);
  });

  it('confirm 无 executionId：无操作（confirmExecution 未调用，状态不变）', () => {
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.confirm(true);
    });
    expect(confirmMock).not.toHaveBeenCalled();
    expect(result.current.status).toBe('idle');
  });

  it('并发保护：执行中二次 start 无操作（streamPipeline 仅 1 次）', async () => {
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    act(() => {
      result.current.start(BODY);
    });
    expect(streamPipelineMock).toHaveBeenCalledTimes(1);
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
  });

  it('success 后允许再次 start（并发保护不永久锁死）', async () => {
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: '第一次' });
    });
    expect(result.current.status).toBe('success');
    act(() => {
      result.current.start({ ...BODY, variables: { prompt: '第二次' } });
    });
    expect(streamPipelineMock).toHaveBeenCalledTimes(2);
    expect(streamPipelineMock).toHaveBeenLastCalledWith(
      { ...BODY, variables: { prompt: '第二次' } },
      expect.any(Object),
    );
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: '第二次' });
    });
  });

  it('onError 网络失败：failed + error（不崩溃）', async () => {
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    act(() => {
      capturedStream?.callbacks.onError('Kernel unreachable');
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('Kernel unreachable');
  });

  it('streamPipeline 异常 rejection 被 .catch 吞掉：不崩溃（错误经 onError 帧表达）', async () => {
    streamPipelineMock.mockRejectedValue(new Error('Kernel unreachable'));
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // .catch(()=>{}) 吞掉 rejection → 状态保持 running（等待 onError 帧）
    expect(result.current.status).toBe('running');
  });

  it('轮询网络失败：failed + error（停止轮询）', async () => {
    statusMock.mockRejectedValue(new Error('poll broken'));
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.poll('e1');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('poll broken');
  });
});

describe('useExecutionPoll — 手动 poll / 卸载清理', () => {
  it('poll(executionId) 手动启动轮询 → completed → success + finalOutput', async () => {
    statusMock.mockResolvedValue({
      ...PENDING,
      execution_id: 'e9',
      status: 'completed',
      final_output: '手动成品',
    });
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.poll('e9');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(statusMock).toHaveBeenCalledWith('e9');
    expect(result.current.status).toBe('success');
    expect(result.current.finalOutput).toBe('手动成品');
  });

  it('卸载停止轮询：unmount 后不再调 getExecutionStatus', async () => {
    const { result, unmount } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.poll('e1');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const callsBefore = statusMock.mock.calls.length;
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(statusMock.mock.calls.length).toBe(callsBefore);
  });
});
