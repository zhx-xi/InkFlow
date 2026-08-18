/**
 * useExecutionPoll hook 契约（#472 R0 前置重构：统一管线执行/轮询）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/hooks/useExecutionPoll.ts 并匹配：
 *
 * export type PipelineRunStatus = 'idle' | 'running' | 'success' | 'failed' | 'awaiting_human';
 * export interface UseExecutionPollResult {
 *   status: PipelineRunStatus;
 *   error: string | null;
 *   finalOutput: string;
 *   totalDurationMs: number;
 *   hitlPending: { question: string; role: string } | null;
 *   start: (body: PipelineExecuteRequest) => void;   // 并发保护：执行中再次调用 = 无操作
 *   confirm: (approved: boolean) => void;            // HITL 确认；无 executionId = 无操作
 *   poll: (executionId: string) => void;             // 手动启动轮询（同时记录 executionId 供 confirm）
 * }
 * export function useExecutionPoll(): UseExecutionPollResult;
 *
 * 行为契约（对齐 usePipeline #298 语义 + 通用化，供 usePipeline 与 ChatPanel 复用）：
 * - start(body) → status='running' + executePipeline(body) + 自动轮询 getExecutionStatus：
 *   completed → status='success' + finalOutput/totalDurationMs
 *   failed → status='failed' + error
 *   waiting_hitl → status='awaiting_human' + hitlPending + 停止轮询
 *   其它（pending/running）→ 1s 后继续轮询
 * - confirm(approved) → confirmExecution(executionId, approved) + 续跑轮询
 * - 并发保护：执行中再次 start 无操作（executePipeline 仅 1 次）；终态后允许再次 start
 * - execute 网络失败 → status='failed' + error
 * - 轮询网络失败 → status='failed' + error
 * - 卸载停止轮询（不再调 getExecutionStatus）
 * - 生命周期（timer/executionId）不入任何 store（纯组件内状态）
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useExecutionPoll } from './useExecutionPoll';
import {
  executePipeline,
  getExecutionStatus,
  confirmExecution,
} from '../api/pipeline';

vi.mock('../api/pipeline', () => ({
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);
const confirmMock = vi.mocked(confirmExecution);

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
  executeMock.mockReset();
  statusMock.mockReset();
  confirmMock.mockReset();
  executeMock.mockResolvedValue({
    execution_id: 'e1',
    pipeline: 'builtin:chat',
    project_id: 'p1',
    status: 'pending',
    created_at: '',
  });
  statusMock.mockResolvedValue(PENDING);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useExecutionPoll — 状态机（idle → running → success | failed | awaiting_human）', () => {
  it('初始状态：idle / 无错误 / 空成品 / 无 HITL', () => {
    const { result } = renderHook(() => useExecutionPoll());
    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
    expect(result.current.finalOutput).toBe('');
    expect(result.current.totalDurationMs).toBe(0);
    expect(result.current.hitlPending).toBeNull();
  });

  it('start(body)：status=running + executePipeline(body) 精确 body + 自动轮询', async () => {
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    expect(result.current.status).toBe('running');
    expect(executeMock).toHaveBeenCalledTimes(1);
    expect(executeMock).toHaveBeenCalledWith(BODY);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(statusMock).toHaveBeenCalledWith('e1');
  });

  it('轮询 pending → completed：success + finalOutput + totalDurationMs + 停止轮询', async () => {
    statusMock
      .mockResolvedValueOnce(PENDING)
      .mockResolvedValueOnce({
        ...PENDING,
        status: 'completed',
        final_output: '对话回复内容',
        total_duration_ms: 900,
      });
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // 1s 后第二次 poll 返回 completed
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.status).toBe('success');
    expect(result.current.finalOutput).toBe('对话回复内容');
    expect(result.current.totalDurationMs).toBe(900);
    // 终态后不再轮询
    const statusCalls = statusMock.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(statusMock.mock.calls.length).toBe(statusCalls);
  });

  it('轮询 failed：failed + error 透传', async () => {
    statusMock.mockResolvedValue({ ...PENDING, status: 'failed', error: 'LLM 调用失败' });
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('LLM 调用失败');
  });

  it('轮询 waiting_hitl：awaiting_human + hitlPending 暴露 + 停止轮询', async () => {
    statusMock.mockResolvedValue({
      ...PENDING,
      status: 'waiting_hitl',
      hitl_pending: { question: '确认执行下一角色 reviser？', role: 'reviser' },
    });
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
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
    act(() => {
      result.current.start(BODY);
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
      result.current.start(BODY);
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

  it('confirm 无 executionId：无操作（confirmExecution 未调用，状态不变）', async () => {
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.confirm(true);
    });
    expect(confirmMock).not.toHaveBeenCalled();
    expect(result.current.status).toBe('idle');
  });

  it('并发保护：执行中二次 start 无操作（executePipeline 仅 1 次）', async () => {
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    act(() => {
      result.current.start(BODY);
    });
    expect(executeMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
  });

  it('success 后允许再次 start（并发保护不永久锁死）', async () => {
    statusMock.mockResolvedValue({ ...PENDING, status: 'completed', final_output: '第一次' });
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.status).toBe('success');
    act(() => {
      result.current.start({ ...BODY, variables: { prompt: '第二次' } });
    });
    expect(executeMock).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
  });

  it('execute 网络失败：failed + error（不崩溃）', async () => {
    executeMock.mockRejectedValue(new Error('Kernel unreachable'));
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('Kernel unreachable');
  });

  it('轮询网络失败：failed + error（停止轮询）', async () => {
    statusMock.mockRejectedValue(new Error('poll broken'));
    const { result } = renderHook(() => useExecutionPoll());
    act(() => {
      result.current.start(BODY);
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
      result.current.start(BODY);
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
