/**
 * SSE 流式消费（spec §4.4/§4.5，契约 = F23 spec §6）
 * - POST /api/v1/writing/stream + fetch ReadableStream（EventSource 不支持 POST/自定义头）
 * - 帧: data: {delta, done:false} × N → {done:true, format_valid?, word_count?, model?, warnings?}
 *       流中错误: {done:true, error}
 * - 停止: AbortController.abort() → 服务端 is_disconnected 终止生成器（F23 §5.3）
 * - store 边界: 生命周期在 useStream hook 持有，store 不持有非序列化对象
 */

import { getApiConfig } from './client';

export interface StreamGenerateBody {
  mode: 'generate';
  project_id: string;
  chapter_id: string;
  outline: string;
  min_words?: number;
}

export interface StreamContinueBody {
  mode: 'continue';
  project_id: string;
  chapter_id: string;
  existing_content: string;
  target_words?: number;
}

export interface StreamReviseBody {
  mode: 'revise';
  project_id: string;
  chapter_id: string;
  content: string;
  feedback: string;
}

export type StreamRequestBody = StreamGenerateBody | StreamContinueBody | StreamReviseBody;

/** 帧载荷（F23 spec §6.2 字段省略规则：None/空值不出现） */
export interface StreamFrame {
  done: boolean;
  delta?: string;
  error?: string;
  format_valid?: boolean | null;
  warnings?: string[];
  word_count?: number | null;
  model?: string | null;
  token_usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number } | null;
}

export type StreamStatus = 'idle' | 'generating' | 'done' | 'error' | 'stopped';

export interface StreamCallbacks {
  /** 每帧 delta（调用方自行 rAF 批渲染，§4.5） */
  onDelta: (delta: string) => void;
  /** done 帧（携带结果摘要字段） */
  onDone: (frame: StreamFrame) => void;
  /** error 帧 / 网络错误 */
  onError: (message: string) => void;
}

/** 发起流式写作请求；返回 abort 函数（组件/effect 持有，卸载时调用） */
export async function streamWriting(
  body: StreamRequestBody,
  callbacks: StreamCallbacks,
): Promise<() => void> {
  const { baseURL, token } = getApiConfig();
  const controller = new AbortController();

  const run = async () => {
    try {
      const res = await fetch(`${baseURL}/api/v1/writing/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'X-InkFlow-Token': token } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        callbacks.onError(`HTTP ${res.status}`);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      // 行缓冲: SSE 帧以空行分隔（\n\n），data: JSON 行可能分块到达
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // 逐帧切分（F23 §6.3: data: 行 + \n\n 空行）
        let sepIndex: number;
        while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
          const rawFrame = buffer.slice(0, sepIndex);
          buffer = buffer.slice(sepIndex + 2);
          const dataLine = rawFrame
            .split('\n')
            .find((l) => l.startsWith('data:'))
            ?.slice(5)
            .trim();
          if (!dataLine) continue;
          const frame = JSON.parse(dataLine) as StreamFrame;
          if (frame.delta) callbacks.onDelta(frame.delta);
          if (frame.error) {
            callbacks.onError(frame.error);
            return;
          }
          if (frame.done) {
            callbacks.onDone(frame);
            return;
          }
        }
      }
      // 流结束但无 done 帧（异常断开）
      callbacks.onError('Stream ended unexpectedly');
    } catch (err) {
      if (controller.signal.aborted) return; // 主动停止，不算错误
      callbacks.onError(err instanceof Error ? err.message : String(err));
    }
  };

  void run();
  return () => controller.abort();
}
