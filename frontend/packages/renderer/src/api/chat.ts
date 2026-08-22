/**
 * SSE 流式聊天客户端（#541，契约 = api/chat.test.ts）
 * - POST /api/v1/chat/stream + fetch ReadableStream（EventSource 不支持 POST/自定义头）
 * - 帧: data: {delta, done:false} × N → {done:true}；流中错误: {done:true, error}
 * - 停止: AbortController.abort() → 服务端终止生成器
 * - 行为镜像 src/api/sse.ts streamWriting：行缓冲按 \n\n 切帧取 data: 行
 */
import { apiFetch, getApiConfig } from './client';

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

/** #547：chat 消息实体（对齐后端 GET/POST /api/v1/chat/messages 契约） */
export interface ChatMessageDto {
  id: string;
  project_id: string;
  role: 'user' | 'ai';
  content: string;
  intent: 'content' | 'conversation' | null;
  created_at: string;
}

/** #547：会话聚合实体（对齐后端 GET /api/v1/chat/conversations 契约） */
export interface ChatConversationDto {
  project_id: string;
  project_name: string | null;
  last_message: string;
  message_count: number;
  /** #581：true=已归档对话（后端 include_deleted=true 聚合输出，镜像 sessions.is_deleted） */
  is_deleted: boolean;
  updated_at: string;
}

/** 拉取项目 chat 消息历史（时间升序，分页） */
export async function fetchChatMessages(
  projectId: string,
  offset = 0,
  limit = 50,
): Promise<{ items: ChatMessageDto[]; total: number; offset: number; limit: number }> {
  const qs = new URLSearchParams({
    project_id: projectId,
    offset: String(offset),
    limit: String(limit),
  });
  return apiFetch(`/api/v1/chat/messages?${qs.toString()}`, { method: 'GET' });
}

/** 追加 chat 消息（落库） */
export async function saveChatMessage(body: {
  project_id: string;
  role: 'user' | 'ai';
  content: string;
  intent?: 'content' | 'conversation' | null;
}): Promise<ChatMessageDto> {
  const payload: {
    project_id: string;
    role: 'user' | 'ai';
    content: string;
    intent?: 'content' | 'conversation' | null;
  } = { ...body };
  if (body.intent === undefined) {
    delete payload.intent;
  }
  return apiFetch('/api/v1/chat/messages', { method: 'POST', body: payload });
}

/** 会话页聚合列表（#581：includeDeleted=true 时含已归档全量，镜像 api/sessions.ts fetchSessions） */
export async function fetchChatConversations(params?: {
  includeDeleted?: boolean;
}): Promise<{ items: ChatConversationDto[]; total: number }> {
  const qs = new URLSearchParams();
  if (params?.includeDeleted) qs.set('include_deleted', 'true');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch(`/api/v1/chat/conversations${suffix}`);
}

/** #581：恢复已归档 chat 会话：POST /api/v1/chat/conversations/{projectId}/restore → ChatConversation */
export async function restoreChatConversation(projectId: string): Promise<ChatConversationDto> {
  return apiFetch<ChatConversationDto>(`/api/v1/chat/conversations/${projectId}/restore`, {
    method: 'POST',
  });
}

/** #566：归档 chat 消息：DELETE /api/v1/chat/messages/{id}（无 force = 软删，204） */
export async function archiveChatMessage(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/chat/messages/${id}`, { method: 'DELETE' });
}

/** #566：真删 chat 消息：DELETE /api/v1/chat/messages/{id}?force=true（204） */
export async function deleteChatMessage(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/chat/messages/${id}?force=true`, { method: 'DELETE' });
}

/** #566：恢复 chat 消息：POST /api/v1/chat/messages/{id}/restore → ChatMessage */
export async function restoreChatMessage(id: string): Promise<ChatMessageDto> {
  return apiFetch<ChatMessageDto>(`/api/v1/chat/messages/${id}/restore`, { method: 'POST' });
}

/** #566：归档整个项目 chat 会话（sessions 页对话区块用）：DELETE /api/v1/chat/conversations/{projectId}（204） */
export async function archiveChatConversation(projectId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/chat/conversations/${projectId}`, { method: 'DELETE' });
}

/** #566：真删整个项目 chat 会话：DELETE /api/v1/chat/conversations/{projectId}?force=true（204） */
export async function deleteChatConversation(projectId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/chat/conversations/${projectId}?force=true`, { method: 'DELETE' });
}
