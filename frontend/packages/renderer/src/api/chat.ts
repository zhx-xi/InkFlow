/**
 * SSE 流式聊天客户端（#541，契约 = api/chat.test.ts）
 * - POST /api/v1/chat/stream + fetch ReadableStream（EventSource 不支持 POST/自定义头）
 * - 帧: data: {delta, done:false} × N → {done:true}；流中错误: {done:true, error}
 * - 停止: AbortController.abort() → 服务端终止生成器
 * - 行为镜像 src/api/sse.ts streamWriting：行缓冲按 \n\n 切帧取 data: 行
 */
import { getApiConfig } from './client';

export interface ChatStreamBody {
  project_id: string;
  prompt: string;
  chapter_id?: string;
  chapter_context?: string;
}

export interface ChatStreamFrame {
  done: boolean;
  delta?: string;
  error?: string;
}

export interface ChatStreamCallbacks {
  onDelta: (delta: string) => void;
  onDone: (frame: ChatStreamFrame) => void;
  onError: (message: string) => void;
}

/** 发起 chat 流式请求；返回 abort 函数（组件卸载时调用） */
export async function streamChat(
  body: ChatStreamBody,
  callbacks: ChatStreamCallbacks,
): Promise<() => void> {
  const { baseURL, token } = getApiConfig();
  const controller = new AbortController();

  const run = async () => {
    try {
      const res = await fetch(`${baseURL}/api/v1/chat/stream`, {
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

        // 逐帧切分（#541 帧格式: data: 行 + \n\n 空行）
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
          const frame = JSON.parse(dataLine) as ChatStreamFrame;
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
