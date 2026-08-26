/**
 * 管线执行 hook（spec §5.6）：提交 execute + 轮询 execution 状态 + 成品落章
 * 状态机: idle → running → success | failed | awaiting_human（HITL 中断，#343）
 * - start('write_auto') → executePipeline(builtin:write_auto)
 * - start('write_continue') → executePipeline(builtin:write_continue)
 * - 轮询/confirm/并发保护/卸载清理统一由 useExecutionPoll 承担（#472 R0）
 * - completed → chapterStore.setContent(final_output) + status='success'（落章保留在本 hook）
 */
import { useCallback, useEffect, type MutableRefObject } from 'react';
import type { PipelineExecuteRequest } from '../api/pipeline';
import { useChapterStore } from '../stores/chapter';
import { useExecutionPoll, type PipelineRunStatus, type PipelineStreamSink } from './useExecutionPoll';

export type PipelineMode = 'write_auto' | 'write_continue';
export type { PipelineRunStatus } from './useExecutionPoll';

export interface UsePipelineOptions {
  projectId: string;
  chapterId: string;
  /** #595：项目标签（write_auto 题材 = tags 全拼，space join） */
  tags: string[];
  targetWords: number;
  writingStyle: string;
  chapterTitle: string;
  supervisor?: { hitl_roles?: string[] } | null;
}

export interface UsePipelineResult {
  status: PipelineRunStatus;
  error: string | null;
  finalOutput: string;
  totalDurationMs: number;
  hitlPending: { question: string; role: string } | null;
  executionId: string | null; // #543：透传 useExecutionPoll 的 executionId（执行详情页数据源）
  /** #681：当前管线阶段 id */
  currentStage: string | null;
  /** #681：当前管线阶段 display name */
  stageName: string | null;
  /** #681：阶段进度估算（百分比整数） */
  stageProgress: number;
  /** #681：生成整体耗时（ms） */
  stageElapsedMs: number;
  /** #642-1：透传 useExecutionPoll 的 streamSinkRef（写作页传给 ChatPanel 复用流式渲染） */
  streamSinkRef: MutableRefObject<PipelineStreamSink>;
  start: (mode: PipelineMode) => void;
  confirm: (approved: boolean) => void;
}

export function usePipeline(options: UsePipelineOptions): UsePipelineResult {
  const pollState = useExecutionPoll();

  const buildVariables = useCallback(
    (mode: PipelineMode): Record<string, string> => {
      const vars: Record<string, string> = {};
      if (options.writingStyle) vars.writing_style = options.writingStyle;
      // #366 G1 设定驱动写作：当前章节标题非空才注入（write_auto 与 write_continue 均注入）
      if (options.chapterTitle) vars.chapter_title = options.chapterTitle;
      // 全自动生成：题材与目标字数作为生成约束注入（spec §5.6 write_auto）
      if (mode === 'write_auto') {
        // #595：题材 = tags 全拼（空数组注入空串——RED 契约「自由标签不强制题材」）
        vars.tags = options.tags.join(' ');
        if (options.targetWords > 0) vars.target_words = String(options.targetWords);
      }
      return vars;
    },
    [options.tags, options.targetWords, options.writingStyle, options.chapterTitle],
  );

  const start = useCallback(
    (mode: PipelineMode) => {
      const body: PipelineExecuteRequest = {
        project_id: options.projectId,
        pipeline: `builtin:${mode}`,
        ...(options.chapterId ? { chapter_id: options.chapterId } : {}),
        variables: buildVariables(mode),
        ...(options.supervisor?.hitl_roles?.length
          ? { mode: 'supervisor' as const, supervisor: { hitl_roles: options.supervisor.hitl_roles } }
          : {}),
      };
      pollState.start(body);
    },
    [options.projectId, options.chapterId, options.supervisor?.hitl_roles, buildVariables, pollState.start],
  );

  const confirm = useCallback(
    (approved: boolean) => {
      pollState.confirm(approved);
    },
    [pollState.confirm],
  );

  // 成品落章：success 后写入 chapter store（依赖 [status]，每次 success 触发一次，与现实现语义一致）
  useEffect(() => {
    if (pollState.status === 'success') {
      useChapterStore.getState().setContent(pollState.finalOutput);
    }
  }, [pollState.status]);

  return {
    status: pollState.status,
    error: pollState.error,
    finalOutput: pollState.finalOutput,
    totalDurationMs: pollState.totalDurationMs,
    hitlPending: pollState.hitlPending,
    executionId: pollState.executionId,
    currentStage: pollState.currentStage,
    stageName: pollState.stageName,
    stageProgress: pollState.stageProgress,
    stageElapsedMs: pollState.stageElapsedMs,
    streamSinkRef: pollState.streamSinkRef,
    start,
    confirm,
  };
}
