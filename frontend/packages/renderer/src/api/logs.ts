/**
 * #496 统一日志页 API 客户端（contract-496 §5）：GET /api/v1/logs 查询 + GET /api/v1/i18n/messages
 * 远端消息目录拉取。镜像 api/search.ts 形态：apiFetch + URLSearchParams，缺省参数不携带。
 */
import { apiFetch } from './client';

/** 单条结构化日志（对齐后端 GET /logs LogRecordDto，字段逐字见 §5） */
export interface LogRecordDto {
  timestamp: string;
  level: string; // 'DEBUG'|'INFO'|'WARN'|'ERROR'（后端存原始形态）
  logger: string;
  caller_type: string; // 'api'|'agent'|'llm'|'tool'|'cli'|'mcp'|'frontend'
  caller_name: string;
  event: string;
  message_key: string;
  params: Record<string, unknown>;
  correlation_id: string;
  trace_id?: string | null;
  span_id?: string | null;
  project_id?: number | null;
  entity_id?: string | null;
  duration_ms?: number | null;
  error_code?: string | null;
  stack?: string | null;
}

/** 日志查询参数（page 从 0 起；level/caller_type 支持逗号分隔多值） */
export interface LogsQueryParams {
  level?: string; // 逗号多值（页面默认 'INFO,WARN,ERROR'；DEBUG 选项 = 不传）
  caller_type?: string; // 逗号多值（分类映射见 §6）
  project_id?: string; // UUID 串
  from?: string;
  to?: string;
  q?: string;
  correlation_id?: string;
  page?: number;
  limit?: number;
}

/** GET /logs 响应 data（F7 信封 {ok,data} 解包后） */
export interface LogsResponseDto {
  items: LogRecordDto[];
  total: number;
  offset: number;
  limit: number;
}

/** 后端 F7 统一信封：{ok, data}（GET /logs 与 GET /i18n/messages 同一信封） */
interface Envelope<T> {
  ok: boolean;
  data: T;
}

/**
 * 查询日志：GET /api/v1/logs?<qs>。
 * URL 序列化契约：空串参数不携带；page=0 不携带（后端默认 0）；limit 显式传入时携带。
 */
export async function fetchLogs(params: LogsQueryParams): Promise<LogsResponseDto> {
  const qs = new URLSearchParams();
  if (params.level) qs.set('level', params.level);
  if (params.caller_type) qs.set('caller_type', params.caller_type);
  if (params.project_id) qs.set('project_id', params.project_id);
  if (params.from) qs.set('from', params.from);
  if (params.to) qs.set('to', params.to);
  if (params.q) qs.set('q', params.q);
  if (params.correlation_id) qs.set('correlation_id', params.correlation_id);
  if (params.page !== undefined && params.page > 0) qs.set('page', String(params.page));
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  const query = qs.toString();
  const env = await apiFetch<Envelope<LogsResponseDto>>(
    `/api/v1/logs${query ? `?${query}` : ''}`,
    { method: 'GET' },
  );
  return env.data;
}

/** 拉取远端消息目录：GET /api/v1/i18n/messages?lng=<lng> → env.data */
export async function fetchLogMessages(lng: string): Promise<Record<string, string>> {
  const qs = new URLSearchParams({ lng });
  const env = await apiFetch<Envelope<Record<string, string>>>(
    `/api/v1/i18n/messages?${qs.toString()}`,
    { method: 'GET' },
  );
  return env.data;
}
