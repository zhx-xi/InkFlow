/**
 * 管线执行 hook（spec §5.6）：提交 execute + 轮询 execution 状态 + 成品落章
 * 状态机: idle → running → success | failed | awaiting_human（HITL 中断，#343）
 * - start('write_auto') → executePipeline(builtin:write_auto)
 * - start('write_continue') → executePipeline(builtin:write_continue)
 * - 轮询 getExecutionStatus（1s 间隔 setTimeout 递归）：
 *   completed → chapterStore.setContent(final_output) + status='success'
 *   failed → status='failed' + error
 *   waiting_hitl → hitlPending 暴露 + status='awaiting_human' + 停止轮询（等待 confirm）
 *   其它 → 继续轮询
 * - confirm(approved) → confirmExecution(execution_id, approved) 后继续轮询续跑
 * - 并发保护：running 中再次 start 无操作
 * - 卸载清理 timer
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  confirmExecution,
  executePipeline,
  getExecutionStatus,
  type PipelineExecuteRequest,
} from '../api/pipeline';
import { errorMessage } from '../api/client';
import { useChapterStore } from '../stores/chapter';

export type PipelineMode = 'write_auto' | 'write_continue';
export type PipelineRunStatus = 'idle' | 'running' | 'success' | 'failed' | 'awaiting_human';

export interface UsePipelineOptions {
  projectId: string;
  chapterId: string;
  genre: string;
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
  start: (mode: PipelineMode) => void;
  confirm: (approved: boolean) => void;
}

const POLL_INTERVAL_MS = 1000;

export function usePipeline(options: UsePipelineOptions): UsePipelineResult {
  const [status, setStatus] = useState<PipelineRunStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [finalOutput, setFinalOutput] = useState('');
  const [totalDurationMs, setTotalDurationMs] = useState(0);
  const [hitlPending, setHitlPending] = useState<{ question: string; role: string } | null>(null);
  const inFlightRef = useRef(false);
  const executionIdRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const buildVariables = useCallback(
    (mode: PipelineMode): Record<string, string> => {
      const vars: Record<string, string> = {};
      if (options.writingStyle) vars.writing_style = options.writingStyle;
      // #366 G1 设定驱动写作：当前章节标题非空才注入（write_auto 与 write_continue 均注入）
      if (options.chapterTitle) vars.chapter_title = options.chapterTitle;
      // 全自动生成：题材与目标字数作为生成约束注入（spec §5.6 write_auto）
      if (mode === 'write_auto') {
        if (options.genre) vars.genre = options.genre;
        if (options.targetWords > 0) vars.target_words = String(options.targetWords);
      }
      return vars;
    },
    [options.genre, options.targetWords, options.writingStyle, options.chapterTitle],
  );

  const poll = useCallback(async (executionId: string) => {
    try {
      const s = await getExecutionStatus(executionId);
      if (s.status === 'completed') {
        useChapterStore.getState().setContent(s.final_output);
        setFinalOutput(s.final_output);
        setTotalDurationMs(s.total_duration_ms);
        setError(null);
        setStatus('success');
        inFlightRef.current = false;
      } else if (s.status === 'failed') {
        setError(s.error || '执行失败');
        setStatus('failed');
        inFlightRef.current = false;
      } else if (s.status === 'waiting_hitl') {
        setHitlPending(
          s.hitl_pending ? { question: s.hitl_pending.question, role: s.hitl_pending.role } : null,
        );
        setStatus('awaiting_human');
        inFlightRef.current = false; // 停止轮询，等待人工确认
      } else {
        timerRef.current = setTimeout(() => {
          void poll(executionId);
        }, POLL_INTERVAL_MS);
      }
    } catch (err) {
      setError(errorMessage(err));
      setStatus('failed');
      inFlightRef.current = false;
    }
  }, []);

  const start = useCallback(
    (mode: PipelineMode) => {
      if (inFlightRef.current) return; // 防并发
      inFlightRef.current = true;
      setError(null);
      setFinalOutput('');
      setTotalDurationMs(0);
      setStatus('running');

      const body: PipelineExecuteRequest = {
        project_id: options.projectId,
        pipeline: `builtin:${mode}`,
        ...(options.chapterId ? { chapter_id: options.chapterId } : {}),
        variables: buildVariables(mode),
        ...(options.supervisor?.hitl_roles?.length
          ? { mode: 'supervisor' as const, supervisor: { hitl_roles: options.supervisor.hitl_roles } }
          : {}),
      };
      executePipeline(body)
        .then((res) => {
          executionIdRef.current = res.execution_id;
          void poll(res.execution_id);
        })
        .catch((err) => {
          setError(errorMessage(err));
          setStatus('failed');
          inFlightRef.current = false;
        });
    },
    [options.projectId, options.chapterId, options.supervisor?.hitl_roles, buildVariables, poll],
  );

  const confirm = useCallback(
    (approved: boolean) => {
      const executionId = executionIdRef.current;
      if (!executionId) return;
      setStatus('running');
      confirmExecution(executionId, approved)
        .then(() => {
          setHitlPending(null);
          void poll(executionId);
        })
        .catch((err) => {
          setError(errorMessage(err));
          setStatus('failed');
          inFlightRef.current = false;
        });
    },
    [poll],
  );

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  return { status, error, finalOutput, totalDurationMs, hitlPending, start, confirm };
}
