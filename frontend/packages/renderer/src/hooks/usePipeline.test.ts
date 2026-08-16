/**
 * usePipeline hook 测试契约（#298 RED 阶段，spec §5.6 GUI 写作入口管线化）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/hooks/usePipeline.ts 并匹配：
 *
 * export type PipelineMode = 'write_auto' | 'write_continue';
 * export type PipelineRunStatus = 'idle' | 'running' | 'success' | 'failed';
 * export interface UsePipelineOptions {
 *   projectId: string;
 *   chapterId: string;
 *   genre: string;
 *   targetWords: number;
 *   writingStyle: string;
 *   chapterTitle: string;
 * }
 * export interface UsePipelineResult {
 *   status: PipelineRunStatus;
 *   error: string | null;
 *   finalOutput: string;
 *   totalDurationMs: number;
 *   start: (mode: PipelineMode) => void;   // 执行中再次调用 = 无操作（防并发）
 * }
 * export function usePipeline(options: UsePipelineOptions): UsePipelineResult;
 *
 * 行为契约：
 * - start('write_auto') → executePipeline({project_id, pipeline:'builtin:write_auto',
 *   chapter_id, variables:{genre?, target_words?, writing_style?, chapter_title?}}（非空才注入）)
 * - start('write_continue') → executePipeline({pipeline:'builtin:write_continue',
 *   variables:{writing_style?, chapter_title?}})（#318：前文摘要由后端生成注入 context，
 *   前端不再传 chapterStore.content 全文）
 * - chapter_title（当前章节标题）非空才注入，write_auto 与 write_continue 均注入（G1 #366）
 * - 轮询 getExecutionStatus(execution_id)（1s 间隔，setTimeout 递归）：
 *   status==='completed' → chapterStore.setContent(final_output) + status='success'
 *   status==='failed' → status='failed' + error
 *   其它（pending/running）→ 继续轮询
 * - 并发保护：running 中再次 start 无操作（executePipeline 仅 1 次）
 * - 卸载停止轮询（不再调 getExecutionStatus）
 * - 生命周期（timer/executionId）不入 chapter store
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { usePipeline } from './usePipeline';
import { executePipeline, getExecutionStatus, confirmExecution } from '../api/pipeline';
import { useChapterStore } from '../stores/chapter';

vi.mock('../api/pipeline', () => ({
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);
const confirmMock = vi.mocked(confirmExecution);

const OPTS = {
  projectId: 'p1',
  chapterId: 'c1',
  genre: '玄幻',
  targetWords: 800000,
  writingStyle: '文笔细腻',
  chapterTitle: '第一章',
};

beforeEach(() => {
  vi.useFakeTimers();
  executeMock.mockReset();
  statusMock.mockReset();
  confirmMock.mockReset();
  executeMock.mockResolvedValue({
    execution_id: 'e1',
    pipeline: 'builtin:write_auto',
    project_id: 'p1',
    status: 'pending',
    created_at: '',
  });
  statusMock.mockResolvedValue({
    execution_id: 'e1',
    pipeline: 'builtin:write_auto',
    project_id: 'p1',
    status: 'pending',
    stages: [],
    final_output: '',
    total_duration_ms: 0,
    error: '',
  });
  useChapterStore.setState({
    volumes: [],
    chapters: [],
    currentChapterId: 'c1',
    content: '已有正文',
    loading: false,
    error: null,
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('usePipeline — 状态机（idle → running → success | failed）', () => {
  it('初始状态：idle / 无错误 / 空成品', () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
    expect(result.current.finalOutput).toBe('');
    expect(result.current.totalDurationMs).toBe(0);
  });

  it('start(write_auto)：execute 携带 builtin:write_auto + variables（非空注入）', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    expect(result.current.status).toBe('running');
    expect(executeMock).toHaveBeenCalledTimes(1);
    expect(executeMock).toHaveBeenCalledWith({
      project_id: 'p1',
      pipeline: 'builtin:write_auto',
      chapter_id: 'c1',
      variables: { genre: '玄幻', target_words: '800000', writing_style: '文笔细腻', chapter_title: '第一章' },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
  });

  it('start(write_continue)：pipeline=builtin:write_continue + variables 不含 context（#318 后端生成）', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_continue');
    });
    expect(executeMock).toHaveBeenCalledWith({
      project_id: 'p1',
      pipeline: 'builtin:write_continue',
      chapter_id: 'c1',
      variables: { writing_style: '文笔细腻', chapter_title: '第一章' },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
  });

  it('chapterTitle 为空串：variables 不含 chapter_title 键（守护）', async () => {
    const { result } = renderHook(() => usePipeline({ ...OPTS, chapterTitle: '' }));
    act(() => {
      result.current.start('write_auto');
    });
    const body = executeMock.mock.calls[0][0];
    expect(body.variables).toBeDefined();
    expect(body.variables).not.toHaveProperty('chapter_title');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
  });

  it('轮询 pending → completed：setContent(final_output) + status=success', async () => {
    statusMock
      .mockResolvedValueOnce({
        execution_id: 'e1',
        pipeline: 'builtin:write_auto',
        project_id: 'p1',
        status: 'pending',
        stages: [],
        final_output: '',
        total_duration_ms: 0,
        error: '',
      })
      .mockResolvedValueOnce({
        execution_id: 'e1',
        pipeline: 'builtin:write_auto',
        project_id: 'p1',
        status: 'completed',
        stages: [],
        final_output: '修订后的成品章节',
        total_duration_ms: 1200,
        error: '',
      });

    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    // 首次 poll（execute 后立即）返回 pending → 排程 1s 后重试
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(statusMock).toHaveBeenCalledWith('e1');
    // 1s 后第二次 poll 返回 completed
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.status).toBe('success');
    expect(result.current.finalOutput).toBe('修订后的成品章节');
    expect(result.current.totalDurationMs).toBe(1200);
    // 成品落章：chapter store content = final_output
    expect(useChapterStore.getState().content).toBe('修订后的成品章节');
    // 终态后不再轮询
    const statusCalls = statusMock.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(statusMock.mock.calls.length).toBe(statusCalls);
  });

  it('轮询 failed：status=failed + error 透传（不落章）', async () => {
    statusMock.mockResolvedValue({
      execution_id: 'e1',
      pipeline: 'builtin:write_auto',
      project_id: 'p1',
      status: 'failed',
      stages: [],
      final_output: '',
      total_duration_ms: 800,
      error: '管线执行失败: 阶段 writer 重试耗尽',
    });
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('管线执行失败: 阶段 writer 重试耗尽');
    // 失败不落章（content 保持原值）
    expect(useChapterStore.getState().content).toBe('已有正文');
  });
});

describe('usePipeline — 并发保护 / 卸载清理', () => {
  it('running 中二次 start 无操作（executePipeline 仅 1 次）', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    act(() => {
      result.current.start('write_auto');
    });
    expect(executeMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
  });

  it('execute 网络失败：status=failed + error（不崩溃）', async () => {
    executeMock.mockRejectedValue(new Error('Kernel unreachable'));
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('Kernel unreachable');
  });

  it('卸载停止轮询：unmount 后不再调 getExecutionStatus', async () => {
    const { result, unmount } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
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

  it('生命周期不入 store：serialize 后无 timer/executionId 字段', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    const serialized = JSON.stringify(useChapterStore.getState());
    expect(serialized).not.toContain('executionId');
    expect(() => JSON.parse(serialized)).not.toThrow();
  });
});

describe('usePipeline — HITL interrupt 态（#343：waiting_hitl → awaiting_human + confirm 续跑）', () => {
  const WAITING_STATUS = {
    execution_id: 'e1',
    pipeline: 'builtin:write_auto',
    project_id: 'p1',
    status: 'waiting_hitl' as const,
    stages: [],
    final_output: '',
    total_duration_ms: 0,
    error: '',
    hitl_pending: { question: '确认执行下一角色 reviser？', role: 'reviser' },
  };

  it('轮询 waiting_hitl → status=awaiting_human + hitlPending 暴露 + 停止轮询', async () => {
    statusMock.mockResolvedValue(WAITING_STATUS);
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
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

  it('confirm(true) → confirmExecution 携带 approved + 轮询续跑 → completed 落章', async () => {
    statusMock
      .mockResolvedValueOnce(WAITING_STATUS)
      .mockResolvedValueOnce({
        execution_id: 'e1',
        pipeline: 'builtin:write_auto',
        project_id: 'p1',
        status: 'completed',
        stages: [],
        final_output: '确认后成品',
        total_duration_ms: 3000,
        error: '',
      });
    confirmMock.mockResolvedValue({
      execution_id: 'e1',
      status: 'completed',
      final_output: '确认后成品',
    });
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.status).toBe('awaiting_human');
    act(() => {
      result.current.confirm(true);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(confirmMock).toHaveBeenCalledWith('e1', true);
    // confirm 后继续轮询 → completed → success + 落章
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.status).toBe('success');
    expect(result.current.finalOutput).toBe('确认后成品');
    expect(useChapterStore.getState().content).toBe('确认后成品');
  });

  it('confirm(false) → confirmExecution approved=false → 拒绝续跑（回退）', async () => {
    statusMock.mockResolvedValueOnce(WAITING_STATUS).mockResolvedValueOnce({
      execution_id: 'e1',
      pipeline: 'builtin:write_auto',
      project_id: 'p1',
      status: 'completed',
      stages: [],
      final_output: '拒绝后回退成品',
      total_duration_ms: 2000,
      error: '',
    });
    confirmMock.mockResolvedValue({
      execution_id: 'e1',
      status: 'completed',
      final_output: '拒绝后回退成品',
    });
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.status).toBe('awaiting_human');
    act(() => {
      result.current.confirm(false);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(confirmMock).toHaveBeenCalledWith('e1', false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.status).toBe('success');
    expect(useChapterStore.getState().content).toBe('拒绝后回退成品');
  });

  it('supervisor 配置存在时 execute body 带 mode=supervisor + hitl_roles', async () => {
    const { result } = renderHook(() =>
      usePipeline({ ...OPTS, supervisor: { hitl_roles: ['reviser'] } }),
    );
    act(() => {
      result.current.start('write_auto');
    });
    expect(executeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        project_id: 'p1',
        pipeline: 'builtin:write_auto',
        chapter_id: 'c1',
        mode: 'supervisor',
        supervisor: { hitl_roles: ['reviser'] },
        variables: expect.objectContaining({ chapter_title: '第一章' }),
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
  });
});
