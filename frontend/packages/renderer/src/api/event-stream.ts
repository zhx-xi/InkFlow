/**
 * 数据面变更事件订阅客户端（F23 spec §15.5.1 / §15.5.4）
 *
 * - GET {baseURL}/api/v1/events/stream + fetch ReadableStream（长驻订阅流）
 *   ⚠️ 不用 EventSource：带不了 X-InkFlow-Token 自定义头（同 §15.4.1 裁决，与 §3.1 写作流同法）
 * - 帧形态与写作流一致（`data: <json>\n\n`），但 **schema 不同**：事件帧没有 done 字段
 *   （长驻流不结束）→ 独立解码器，判别靠 domain + op 存在（D15-5，不复用 sse.ts 的 StreamFrame）
 * - 非法帧（JSON 解析失败 / 非事件帧）→ 跳过该帧，不断开订阅（§15.5.3 E6）
 * - 断连 → 指数退避重连（1s → 2s → 4s → 上限 30s，§15.5.4）
 * - 取消：返回 abort 函数（生命周期持有者调用）
 */

import { getApiConfig } from './client';

/**
 * 变更帧（spec §15.5.1 帧 schema）。
 * 字段省略规则同写作帧（§6.2）：None/空值不发键 → 除 domain/op/resource_id 外均可缺省。
 */
export interface DataChangeFrame {
  /** 变更域（资源类型）：project|chapter|volume|character|map|agent_template|settings|… */
  domain: string;
  /** 操作类型：create|update|delete（D15-9：只三值） */
  op: string;
  /** 被变更资源的标识（UUID 字符串或整型主键字符串） */
  resource_id: string;
  /** resource_id 兼容别名（§15.2.1，双输出） */
  entity_id?: string;
  /** 所属项目 UUID；全局域缺省（null 时帧内省略键） */
  project_id?: string | null;
  /** 发起方：gui|cli|mcp|agent|scheduler|unknown（self-originated 过滤用，ADR-053 D3） */
  source?: string;
  /** W3C traceparent（#931 上下文透传） */
  traceparent?: string;
  /** 事件产生时刻（ISO-8601 UTC） */
  occurred_at?: string;
}

/** 重连退避：首次 1s → 每失败一次翻倍 → 上限 30s（spec §15.5.4） */
const RECONNECT_INITIAL_MS = 1000;
const RECONNECT_MAX_MS = 30000;

/** 非法帧归类（解析失败 / 非事件帧）：跳过并记 warning，不断开订阅（§15.5.3 E6） */
function parseFrame(dataLine: string): DataChangeFrame | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(dataLine);
  } catch {
    console.warn('[event-stream] 跳过无法解析的事件帧:', dataLine);
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null) return null;
  const frame = parsed as Partial<DataChangeFrame>;
  // 事件帧判别：domain + op 存在（D15-5；写作帧无这两个字段 → 天然不会被误判为事件帧）
  if (typeof frame.domain !== 'string' || typeof frame.op !== 'string') return null;
  return frame as DataChangeFrame;
}

/** 可中断 sleep（abort 时立即结束等待，供取消后无需等到退避到期） */
function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const finish = (): void => {
      clearTimeout(timer);
      signal.removeEventListener('abort', finish);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    signal.addEventListener('abort', finish, { once: true });
    if (signal.aborted) finish();
  });
}

/**
 * 订阅内核数据面变更事件；返回 abort 函数（生命周期持有者调用）。
 *
 * 注：spec §15.5.4 给出的签名是 `(onEvent, onError?)`；第三个可选参数用于承载
 * 「重连成功」信号（spec 要求重连后做兜底全量 refetch，但未规定信号通道）——
 * 不传时行为与 §15.5.4 文档签名一致。
 *
 * @param onEvent 每收到一个合法变更帧回调一次
 * @param onError 断连 / HTTP 错误 / 流异常结束的消息（重连前触发，非致命）
 * @param onReconnect 重连成功回调（第 2 次及以后的连接尝试成功；首次即成功不触发）
 *   → 调用方做兜底全量 refetch（§15.5.4）
 */
export async function subscribeDataChanges(
  onEvent: (ev: DataChangeFrame) => void,
  onError?: (message: string) => void,
  onReconnect?: () => void,
): Promise<() => void> {
  const { baseURL, token } = getApiConfig();
  const controller = new AbortController();
  let backoffMs = RECONNECT_INITIAL_MS;
  /** 连接尝试次数：首次即成功不算「重连」；此后任一成功 = 可能错过事件 → 兜底 refetch */
  let attempts = 0;

  /** 读一条连接直到结束；帧按 `data:` 行 + `\n\n` 空行切分（同 §6.3 传输形态） */
  const readStream = async (body: ReadableStream<Uint8Array>): Promise<void> => {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

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
        const frame = parseFrame(dataLine);
        if (frame) onEvent(frame);
      }
    }
  };

  const run = async (): Promise<void> => {
    while (!controller.signal.aborted) {
      const isReconnect = attempts > 0;
      attempts += 1;
      let connected = false;
      try {
        const res = await fetch(`${baseURL}/api/v1/events/stream`, {
          headers: { ...(token ? { 'X-InkFlow-Token': token } : {}) },
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          onError?.(`HTTP ${res.status}`);
        } else {
          connected = true;
          if (isReconnect) onReconnect?.();
          await readStream(res.body);
          if (!controller.signal.aborted) onError?.('Stream ended unexpectedly');
        }
      } catch (err) {
        if (controller.signal.aborted) return; // 主动 abort，不算错误
        onError?.(err instanceof Error ? err.message : String(err));
      }
      if (controller.signal.aborted) return;

      // 连接成功 → 退避重置（下次断连从 1s 重新起步）；失败 → 逐次翻倍至上限
      if (connected) backoffMs = RECONNECT_INITIAL_MS;
      await delay(backoffMs, controller.signal);
      backoffMs = Math.min(backoffMs * 2, RECONNECT_MAX_MS);
    }
  };

  void run();
  return () => controller.abort();
}
