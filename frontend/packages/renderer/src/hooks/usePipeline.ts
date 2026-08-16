/**
 * 管线执行 hook（spec §5.6）：提交 execute + 轮询 execution 状态 + 成品落章
 * 状态机: idle → running → success | failed
 * - start('write_auto') → executePipeline(builtin:write_auto)
 * - start('write_continue') → executePipeline(builtin:write_continue)
 * - 轮询 getExecutionStatus（1s 间隔 setTimeout 递归）：
 *   completed → chapterStore.setContent(final_output) + status='success'
 *   failed → status='failed' + error
 *   其它 → 继续轮询
 * - 并发保护：running 中再次 start 无操作
 * - 卸载清理 timer
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { executePipeline, getExecutionStatus, type PipelineExecuteRequest } from '../api/pipeline';
import { errorMessage } from '../api/client';
import { useChapterStore } from '../stores/chapter';

export type PipelineMode = 'write_auto' | 'write_continue';
export type PipelineRunStatus = 'idle' | 'running' | 'success' | 'failed';

export interface UsePipelineOptions {
  projectId: string;
  chapterId: string;
  genre: string;
  targetWords: number;
  writingStyle: string;
  chapterTitle: string;
}

export interface UsePipelineResult {
  status: PipelineRunStatus;
  error: string | null;
  finalOutput: string;
  totalDurationMs: number;
  start: (mode: PipelineMode) => void;
}

const POLL_INTERVAL_MS = 1000;

export function usePipeline(options: UsePipelineOptions): UsePipelineResult {
  const [status, setStatus] = useState<PipelineRunStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [finalOutput, setFinalOutput] = useState('');
  const [totalDurationMs, setTotalDurationMs] = useState(0);
  const inFlightRef = useRef(false);
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
      };
      executePipeline(body)
        .then((res) => {
          void poll(res.execution_id);
        })
        .catch((err) => {
          setError(errorMessage(err));
          setStatus('failed');
          inFlightRef.current = false;
        });
    },
    [options.projectId, options.chapterId, buildVariables, poll],
  );

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  return { status, error, finalOutput, totalDurationMs, start };
}
