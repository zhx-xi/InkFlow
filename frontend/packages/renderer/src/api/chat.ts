/**
 * SSE 流式聊天客户端（#541，外部契约 = api/chat.test.ts）。
 * - POST /api/v1/chat/agent/stream（#597 deepagents 系统级 Agent 流式端点）；
 *   + fetch ReadableStream（EventSource 不支持 POST/自定义头）。
 * - 携带 data: {type, delta, done:false} × N -> {type:'done', done:true}；流中错误 {type:'error', error}
 * - #597 帧协议扩展：type='tool_call' -> onToolCall；type='tool_result' -> onToolResult；
 *   type='delta'（或 type 缺省的旧帧）-> onDelta；type='error' -> onError + return；
 *   type='done'（或无 error 的终帧）-> onDone + return
 * - 停止: AbortController.abort() -> 服务端终止生成器
 * - 行为镜像 src/api/sse.ts streamWriting：行缓冲按 \n\n 切帧，data: 行
 */
import { apiFetch, getApiConfig } from './client';

export interface ChatStreamBody {
  project_id: string;
  prompt: string;
  chapter_id?: string;
  chapter_context?: string;
}

export interface ChatStreamFrame {
  type: 'delta' | 'tool_call' | 'tool_result' | 'done' | 'error' | 'run_started' | 'reasoning';
  done: boolean;
  delta?: string;
  error?: string;
  /** #597：工具帧字段（tool_call / tool_result） */
  id?: string;
  name?: string;
  args?: Record<string, unknown>;
  result?: string;
}

export interface ChatStreamCallbacks {
  onDelta: (delta: string) => void;
  onDone: (frame: ChatStreamFrame) => void;
  onError: (message: string) => void;
  /** #597：agent 工具流回调（可选） */
  onToolCall?: (call: { id: string; name: string; args: Record<string, unknown> }) => void;
  onToolResult?: (res: { id: string; name: string; result: string }) => void;
  /** #719：run_started 帧 -> 携带 run_id（前端据此调后端 abort） */
  onRunStart?: (runId: string) => void;
  /** #727：reasoning 帧 -> 思考过程块 */
  onReasoning?: (text: string) => void;
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
      const res = await fetch(`${baseURL}/api/v1/chat/agent/stream`, {
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
      // 行缓冲：SSE 帧以空行分隔（\n\n），data: JSON 行可能分块到达
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // 逐帧切分：#541 帧格式 data: 行 + \n\n 空行
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
          // #597 帧 type 分发（兼容无 type 的旧帧：按 delta/done/error 字段兜底）
          if (frame.type === 'tool_call') {
            callbacks.onToolCall?.({ id: frame.id ?? '', name: frame.name ?? '', args: frame.args ?? {} });
            continue;
          }
          if (frame.type === 'tool_result') {
            callbacks.onToolResult?.({ id: frame.id ?? '', name: frame.name ?? '', result: frame.result ?? '' });
            continue;
          }
          if (frame.type === 'run_started') {
            callbacks.onRunStart?.(frame.id ?? '');
            continue;
          }
          if (frame.type === 'reasoning') {
            callbacks.onReasoning?.(frame.delta ?? '');
            continue;
          }
          if (frame.type === 'error' || frame.error) {
            callbacks.onError(frame.error ?? '');
            return;
          }
          if (frame.type === 'done' || frame.done) {
            callbacks.onDone(frame);
            return;
          }
          if (frame.delta) callbacks.onDelta(frame.delta);
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

/** #719：后端中断端点——POST /api/v1/chat/agent/stream/{runId}/abort */
export async function abortChatRun(runId: string): Promise<{ ok: boolean }> {
  return apiFetch(`/api/v1/chat/agent/stream/${runId}/abort`, { method: 'POST' });
}

/** #547：#744 chat 消息实体（对齐后端 GET/POST /api/v1/chat/messages 契约，含 conversation_id） */
export interface ChatMessageDto {
  id: string;
  project_id: string;
  /** #744：消息所属线程 id */
  conversation_id: string;
  role: 'user' | 'ai';
  content: string;
  intent: 'content' | 'conversation' | null;
  created_at: string;
}

/** #547：#744 会话聚合实体（对齐后端 GET /api/v1/chat/conversations 契约） */
export interface ChatConversationDto {
  /** #744：线程 id（列表/归档/新建均以 conversation 维度） */
  conversation_id: string;
  project_id: string;
  project_name: string | null;
  last_message: string;
  message_count: number;
  /** #581：true=已归档对话（后端 include_deleted=true 聚合输出，镜像 sessions.is_deleted） */
  is_deleted: boolean;
  updated_at: string;
}

/** 拉取线程 chat 消息历史（时间升序，分页；#744 按 conversation_id 过滤） */
export async function fetchChatMessages(
  conversationId: string,
  offset = 0,
  limit = 50,
): Promise<{ items: ChatMessageDto[]; total: number; offset: number; limit: number }> {
  const qs = new URLSearchParams({
    conversation_id: conversationId,
    offset: String(offset),
    limit: String(limit),
  });
  return apiFetch(`/api/v1/chat/messages?${qs.toString()}`, { method: 'GET' });
}

/** 追加 chat 消息（落库；body 逐字含 conversation_id） */
export async function saveChatMessage(body: {
  project_id: string;
  conversation_id: string;
  role: 'user' | 'ai';
  content: string;
  intent?: 'content' | 'conversation' | null;
}): Promise<ChatMessageDto> {
  const payload: {
    project_id: string;
    conversation_id: string;
    role: 'user' | 'ai';
    content: string;
    intent?: 'content' | 'conversation' | null;
  } = { ...body };
  if (body.intent === undefined) {
    delete payload.intent;
  }
  return apiFetch('/api/v1/chat/messages', { method: 'POST', body: payload });
}

/** 会话页聚合列表（#581）：includeDeleted=true 时含已归档全量，镜像 api/sessions.ts fetchSessions */
export async function fetchChatConversations(params?: {
  includeDeleted?: boolean;
  /** #744：可选按项目过滤 query */
  projectId?: string;
}): Promise<{ items: ChatConversationDto[]; total: number }> {
  const qs = new URLSearchParams();
  if (params?.includeDeleted) qs.set('include_deleted', 'true');
  if (params?.projectId) qs.set('project_id', params.projectId);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch(`/api/v1/chat/conversations${suffix}`);
}

/** #744：创建新线程：POST /api/v1/chat/conversations body {project_id} -> 201 */
export async function createChatConversation(projectId: string): Promise<ChatConversationDto> {
  return apiFetch<ChatConversationDto>('/api/v1/chat/conversations', {
    method: 'POST',
    body: { project_id: projectId },
  });
}

/** #581/#744：恢复已归档线程：POST /api/v1/chat/conversations/{conversationId}/restore */
export async function restoreChatConversation(conversationId: string): Promise<ChatConversationDto> {
  return apiFetch<ChatConversationDto>(`/api/v1/chat/conversations/${conversationId}/restore`, {
    method: 'POST',
  });
}

/** #566：归档 chat 消息：DELETE /api/v1/chat/messages/{id}（无 force = 软删，204） */
export async function archiveChatMessage(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/chat/messages/${id}`, { method: 'DELETE' });
}

/** #566：真删 chat 消息：DELETE /api/v1/chat/messages/{id}?force=true，204 */
export async function deleteChatMessage(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/chat/messages/${id}?force=true`, { method: 'DELETE' });
}

/** #566：恢复 chat 消息：POST /api/v1/chat/messages/{id}/restore -> ChatMessage */
export async function restoreChatMessage(id: string): Promise<ChatMessageDto> {
  return apiFetch<ChatMessageDto>(`/api/v1/chat/messages/${id}/restore`, { method: 'POST' });
}

/** #566/#744：归档线程：DELETE /api/v1/chat/conversations/{conversationId}，204 */
export async function archiveChatConversation(conversationId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/chat/conversations/${conversationId}`, { method: 'DELETE' });
}

/** #566/#744：真删线程：DELETE /api/v1/chat/conversations/{conversationId}?force=true，204 */
export async function deleteChatConversation(conversationId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/chat/conversations/${conversationId}?force=true`, {
    method: 'DELETE',
  });
}
