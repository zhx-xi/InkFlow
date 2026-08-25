/**
 * usePipeline hook 测试契约（#298 RED 阶段，spec §5.6 GUI 写作入口管线化）
 *
 * ⚠️ 本文件 = 契约。#642-1（缺陷 A）后 start 路径由 executePipeline+轮询 改为 streamPipeline SSE 流式
 * （usePipeline 委托 useExecutionPoll，见 src/hooks/usePipeline.ts）：
 *
 * export type PipelineMode = 'write_auto' | 'write_continue';
 * export type PipelineRunStatus = 'idle' | 'running' | 'success' | 'failed' | 'awaiting_human';
 * export interface UsePipelineOptions {
 *   projectId: string;
 *   chapterId: string;
 *   tags: string[];
 *   targetWords: number;
 *   writingStyle: string;
 *   chapterTitle: string;
 *   supervisor?: { hitl_roles?: string[] } | null;
 * }
 * export interface UsePipelineResult {
 *   status: PipelineRunStatus;
 *   error: string | null;
 *   finalOutput: string;
 *   totalDurationMs: number;
 *   hitlPending: { question: string; role: string } | null;
 *   executionId: string | null;
 *   streamSinkRef: MutableRefObject<PipelineStreamSink>;
 *   start: (mode: PipelineMode) => void;   // 执行中再次调用 = 无操作（防并发）
 *   confirm: (approved: boolean) => void;
 * }
 * export function usePipeline(options: UsePipelineOptions): UsePipelineResult;
 *
 * 行为契约（#642-1 流式）：
 * - start('write_auto') → streamPipeline({project_id, pipeline:'builtin:write_auto',
 *   chapter_id, variables:{tags?, target_words?, writing_style?, chapter_title?}}（非空才注入）)
 * - start('write_continue') → streamPipeline({pipeline:'builtin:write_continue',
 *   variables:{writing_style?, chapter_title?}})（#318：前文摘要由后端生成注入 context，
 *   前端不再传 chapterStore.content 全文）
 * - chapter_title（当前章节标题）非空才注入，write_auto 与 write_continue 均注入（G1 #366）
 * - onDone(final_output) → status='success' + finalOutput + chapterStore.setContent(final_output)（落章）
 * - onError(message) → status='failed' + error（不落章）
 * - onDelta 流式增量透传 streamSinkRef（ChatPanel 复用），不累积进 finalOutput
 * - 并发保护：running 中再次 start 无操作（streamPipeline 仅 1 次）
 * - #642-1：流式帧无 hitl 类型 → start 路径不产生 awaiting_human；HITL 中断/confirm 机器
 *   保留在 useExecutionPoll 的 poll/confirm 路径（见 useExecutionPoll.test.ts 契约）
 * - 生命周期（timer/executionId）不入 chapter store
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { usePipeline } from './usePipeline';
import {
  streamPipeline,
  executePipeline,
  getExecutionStatus,
  confirmExecution,
} from '../api/pipeline';
import { useChapterStore } from '../stores/chapter';

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

const OPTS = {
  projectId: 'p1',
  chapterId: 'c1',
  tags: ['玄幻'],
  targetWords: 800000,
  writingStyle: '文笔细腻',
  chapterTitle: '第一章',
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
  capturedStream = null;
});

describe('usePipeline — 状态机（idle → running → success | failed）', () => {
  it('初始状态：idle / 无错误 / 空成品', () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
    expect(result.current.finalOutput).toBe('');
    expect(result.current.totalDurationMs).toBe(0);
  });

  it('start(write_auto)：streamPipeline 携带 builtin:write_auto + variables（非空注入）', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    expect(result.current.status).toBe('running');
    expect(streamPipelineMock).toHaveBeenCalledTimes(1);
    expect(streamPipelineMock).toHaveBeenCalledWith(
      {
        project_id: 'p1',
        pipeline: 'builtin:write_auto',
        chapter_id: 'c1',
        variables: { tags: '玄幻', target_words: '800000', writing_style: '文笔细腻', chapter_title: '第一章' },
      },
      expect.any(Object),
    );
    // 旧 executePipeline 入口不再被调用（#642-1 替换断言）
    expect(executeMock).not.toHaveBeenCalled();
    // 驱动 done → 终态（释放并发保护）
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
  });

  it('start(write_continue)：pipeline=builtin:write_continue + variables 不含 context（#318 后端生成）', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_continue');
    });
    expect(streamPipelineMock).toHaveBeenCalledWith(
      {
        project_id: 'p1',
        pipeline: 'builtin:write_continue',
        chapter_id: 'c1',
        variables: { writing_style: '文笔细腻', chapter_title: '第一章' },
      },
      expect.any(Object),
    );
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
  });

  it('chapterTitle 为空串：variables 不含 chapter_title 键（守护）', async () => {
    const { result } = renderHook(() => usePipeline({ ...OPTS, chapterTitle: '' }));
    act(() => {
      result.current.start('write_auto');
    });
    const body = streamPipelineMock.mock.calls[0][0];
    expect(body.variables).toBeDefined();
    expect(body.variables).not.toHaveProperty('chapter_title');
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
  });

  it('onDelta 流式增量 + onDone(final_output) → success + finalOutput + 落章（#642-1）', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    // 流式增量（透传 sink，不累积进 finalOutput）
    act(() => {
      capturedStream?.callbacks.onDelta('修订后的');
    });
    act(() => {
      capturedStream?.callbacks.onDelta('成品章节');
    });
    // done 帧 final_output 落定
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: '修订后的成品章节' });
    });
    expect(result.current.status).toBe('success');
    expect(result.current.finalOutput).toBe('修订后的成品章节');
    expect(result.current.error).toBeNull();
    // 成品落章：chapter store content = final_output
    expect(useChapterStore.getState().content).toBe('修订后的成品章节');
  });

  it('onError → status=failed + error 透传（不落章）', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    act(() => {
      capturedStream?.callbacks.onError('管线执行失败: 阶段 writer 重试耗尽');
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('管线执行失败: 阶段 writer 重试耗尽');
    // 失败不落章（content 保持原值）
    expect(useChapterStore.getState().content).toBe('已有正文');
  });
});

describe('usePipeline — 并发保护 / 卸载清理', () => {
  it('running 中二次 start 无操作（streamPipeline 仅 1 次）', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    act(() => {
      result.current.start('write_auto');
    });
    expect(streamPipelineMock).toHaveBeenCalledTimes(1);
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
  });

  it('onError 网络失败：status=failed + error（不崩溃）', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    act(() => {
      capturedStream?.callbacks.onError('Kernel unreachable');
    });
    expect(result.current.status).toBe('failed');
    expect(result.current.error).toBe('Kernel unreachable');
  });

  it('#642-1 流式路径不再调用 getExecutionStatus（轮询被流式取代）；卸载无残留', async () => {
    const { result, unmount } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(statusMock).not.toHaveBeenCalled();
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(statusMock).not.toHaveBeenCalled();
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

describe('usePipeline — HITL interrupt 态（#343 + #642-1：流式 start 无 HITL 帧，HITL 机器保留在 useExecutionPoll poll/confirm 路径）', () => {
  it('#642-1 流式路径无 HITL 帧：onDone 直达 success，不出现 awaiting_human / hitlPending', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    expect(result.current.status).toBe('running');
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: '成品' });
    });
    expect(result.current.status).toBe('success');
    expect(result.current.hitlPending).toBeNull();
  });

  it('confirm 在流式路径无 executionId 时为无操作（confirmExecution 不调用，状态不变）', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    act(() => {
      result.current.confirm(true);
    });
    act(() => {
      result.current.confirm(false);
    });
    expect(confirmMock).not.toHaveBeenCalled();
    expect(result.current.status).toBe('running');
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
  });

  it('#642-1 流式 start 后 executionId 保持 null（仅 useExecutionPoll.poll 记录；#543 透传）', async () => {
    const { result } = renderHook(() => usePipeline(OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
    expect(result.current.executionId).toBeNull();
  });

  it('supervisor 配置存在时 streamPipeline body 带 mode=supervisor + hitl_roles', async () => {
    const { result } = renderHook(() =>
      usePipeline({ ...OPTS, supervisor: { hitl_roles: ['reviser'] } }),
    );
    act(() => {
      result.current.start('write_auto');
    });
    expect(streamPipelineMock).toHaveBeenCalledWith(
      expect.objectContaining({
        project_id: 'p1',
        pipeline: 'builtin:write_auto',
        chapter_id: 'c1',
        mode: 'supervisor',
        supervisor: { hitl_roles: ['reviser'] },
        variables: expect.objectContaining({ chapter_title: '第一章' }),
      }),
      expect.any(Object),
    );
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
  });
});

describe('usePipeline — #595 write_auto 题材 = tags 全拼（2026-08-23 拍板 D6=B / D6-a1）', () => {
  const TAGS_OPTS = {
    projectId: 'p1',
    chapterId: 'c1',
    tags: ['玄幻', '热血'],
    targetWords: 800000,
    writingStyle: '文笔细腻',
    chapterTitle: '第一章',
  };

  it('start(write_auto)：variables.tags = " ".join(tags)，不再注入 genre', async () => {
    const { result } = renderHook(() => usePipeline(TAGS_OPTS));
    act(() => {
      result.current.start('write_auto');
    });
    const body = streamPipelineMock.mock.calls[0][0];
    expect(body.variables).toHaveProperty('tags', '玄幻 热血');
    expect(body.variables).not.toHaveProperty('genre');
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
  });

  it('tags 空数组：write_auto 注入 tags 空串（自由标签不强制题材），不注入 genre', async () => {
    const { result } = renderHook(() => usePipeline({ ...TAGS_OPTS, tags: [] }));
    act(() => {
      result.current.start('write_auto');
    });
    const body = streamPipelineMock.mock.calls[0][0];
    expect(body.variables).toHaveProperty('tags', '');
    expect(body.variables).not.toHaveProperty('genre');
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: 'x' });
    });
  });
});
