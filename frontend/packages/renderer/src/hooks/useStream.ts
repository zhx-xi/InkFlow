/**
 * SSE 流式渲染 hook（spec §4.5）
 * 状态机: idle → generating → done | error | stopped
 * - delta 帧进队列 + requestAnimationFrame 批渲染合帧（避免逐 token 重渲染）
 * - done 帧一次性提交 chapterStore.setContent() + 摘要
 * - 流式生命周期由 hook 持有（AbortController/reader），store 不持有非序列化对象
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { streamWriting } from '../api/sse';
import type { StreamFrame, StreamRequestBody } from '../api/sse';
import { useChapterStore } from '../stores/chapter';

export type StreamMode = 'generate' | 'continue' | 'revise';

export interface StreamParams {
  /** generate: 大纲/提示（缺省 ''） */
  outline?: string;
  /** generate */
  minWords?: number;
  /** continue: 缺省 = chapterStore.getState().content */
  existingContent?: string;
  /** continue */
  targetWords?: number;
  /** revise: 缺省 '' */
  feedback?: string;
}

export interface StreamSummary {
  wordCount?: number;
  model?: string;
  formatValid?: boolean;
  warnings?: string[];
}

export type StreamStatus = 'idle' | 'generating' | 'done' | 'error' | 'stopped';

interface UseStreamOptions {
  projectId: string;
  chapterId: string;
}

interface UseStreamResult {
  status: StreamStatus;
  text: string;
  wordCount: number;
  summary: StreamSummary | null;
  error: string | null;
  start: (mode: StreamMode, params?: StreamParams) => void;
  stop: () => void;
  retry: () => void;
}

/** 客户端实时字数估算 = 非空白字符数（done 帧回填精确值） */
function countNonWhitespace(text: string): number {
  return text.replace(/\s/g, '').length;
}

export function useStream({ projectId, chapterId }: UseStreamOptions): UseStreamResult {
  const [status, setStatus] = useState<StreamStatus>('idle');
  const [text, setText] = useState('');
  const [wordCount, setWordCount] = useState(0);
  const [summary, setSummary] = useState<StreamSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 流式生命周期（不进 store）：abort 函数 / 合帧队列 / 累积文本
  const inFlightRef = useRef(false);
  const abortRef = useRef<(() => void) | null>(null);
  const modeRef = useRef<StreamMode>('generate');
  const paramsRef = useRef<StreamParams>({});
  const textRef = useRef('');
  const deltaQueueRef = useRef<string[]>([]);
  const rafRef = useRef<number | null>(null);

  /** 同步合帧（done/error 帧前强制落盘，避免残留队列） */
  const flushNow = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    const queue = deltaQueueRef.current;
    if (queue.length === 0) return;
    deltaQueueRef.current = [];
    textRef.current += queue.join('');
    setText(textRef.current);
    setWordCount(countNonWhitespace(textRef.current));
  }, []);

  const onDelta = useCallback(
    (delta: string) => {
      deltaQueueRef.current.push(delta);
      if (rafRef.current === null) {
        rafRef.current = requestAnimationFrame(() => flushNow());
      }
    },
    [flushNow],
  );

  const onDone = useCallback(
    (frame: StreamFrame) => {
      flushNow();
      // 一次性提交 store（§4.5 store 边界）
      useChapterStore.getState().setContent(textRef.current);
      setSummary({
        wordCount: frame.word_count ?? undefined,
        model: frame.model ?? undefined,
        formatValid: frame.format_valid ?? undefined,
        warnings: frame.warnings ?? [],
      });
      setWordCount(frame.word_count ?? countNonWhitespace(textRef.current));
      setError(null);
      setStatus('done');
      inFlightRef.current = false;
      abortRef.current = null;
    },
    [flushNow],
  );

  const onError = useCallback(
    (message: string) => {
      flushNow(); // 保留已生成前文（不提交 store）
      setError(message);
      setSummary(null);
      setStatus('error');
      inFlightRef.current = false;
      abortRef.current = null;
    },
    [flushNow],
  );

  const start = useCallback(
    (mode: StreamMode, params: StreamParams = {}) => {
      if (inFlightRef.current) return; // 防并发流
      modeRef.current = mode;
      paramsRef.current = params;
      inFlightRef.current = true;

      // 新流从零开始
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      deltaQueueRef.current = [];
      textRef.current = '';
      setText('');
      setWordCount(0);
      setSummary(null);
      setError(null);
      setStatus('generating');

      const storeContent = useChapterStore.getState().content;
      let body: StreamRequestBody;
      if (mode === 'generate') {
        body = {
          mode: 'generate',
          project_id: projectId,
          chapter_id: chapterId,
          outline: params.outline ?? '',
          ...(params.minWords !== undefined ? { min_words: params.minWords } : {}),
        };
      } else if (mode === 'continue') {
        body = {
          mode: 'continue',
          project_id: projectId,
          chapter_id: chapterId,
          existing_content: params.existingContent ?? storeContent,
          ...(params.targetWords !== undefined ? { target_words: params.targetWords } : {}),
        };
      } else {
        body = {
          mode: 'revise',
          project_id: projectId,
          chapter_id: chapterId,
          content: storeContent,
          feedback: params.feedback ?? '',
        };
      }

      void streamWriting(body, { onDelta, onDone, onError }).then((abort) => {
        abortRef.current = abort;
      });
    },
    [projectId, chapterId, onDelta, onDone, onError],
  );

  const stop = useCallback(() => {
    abortRef.current?.();
    abortRef.current = null;
    inFlightRef.current = false;
    flushNow();
    setStatus('stopped');
  }, [flushNow]);

  const retry = useCallback(() => {
    if (inFlightRef.current) return;
    start(modeRef.current, paramsRef.current);
  }, [start]);

  // 卸载时取消合帧 + 中止进行中的流
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      abortRef.current?.();
    };
  }, []);

  return { status, text, wordCount, summary, error, start, stop, retry };
}
