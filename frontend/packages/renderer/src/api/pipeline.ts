/** Agent 管线执行 API 封装（spec §5.6 GUI 写作入口管线化） */
import { apiFetch, getApiConfig } from './client';

export interface PipelineExecuteRequest {
  project_id: string;
  pipeline: string;
  chapter_id?: string;
  variables?: Record<string, string>;
  mode?: 'static' | 'supervisor';
  supervisor?: { hitl_roles: string[] };
}

export interface PipelineExecuteResponse {
  execution_id: string;
  pipeline: string;
  project_id: string;
  status: string;
  created_at: string;
}

export interface PipelineStageSnapshot {
  stage_id: string;
  status: string;
  output: string;
  error: string;
  retry_count: number;
  duration_ms: number;
}

/** F47 #379（spec §3.1）：执行记录 trace 条目（stage=角色节点执行 / decision=supervisor 路由决策） */
export interface TraceEntry {
  node: string;
  type: 'stage' | 'decision';
  reasoning: string;
  tool_calls: unknown[];
  output: string;
  duration_ms: number;
  ts: string;
}

/** F47 #379（spec §3.1）：执行记录 agent_relations 边 + gate 判定快照（F46 数据）。*/
export interface PipelineRelationEntry {
  from: string;
  to: string;
  type: string;
  gate_result?: string;
}

export interface PipelineExecutionStatus {
  execution_id: string;
  pipeline: string;
  project_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'waiting_hitl';
  stages: PipelineStageSnapshot[];
  /** F47 #379：执行轨迹（后端恒返回，默认 []；可选以兼容既有契约测试 mock） */
  trace?: TraceEntry[];
  /** F47 #379：agent_relations 边 + gate 判定快照（可缺省以兼容既有契约测试 mock）*/
  relations?: PipelineRelationEntry[];
  final_output: string;
  total_duration_ms: number;
  error: string;
  hitl_pending?: { question: string; role: string; route_history?: string[] } | null;
}

export interface PipelineConfirmResponse {
  execution_id: string;
  status: string;
  final_output: string;
}

/** #586: backend list_executions list item */
export interface PipelineExecutionListItem {
  execution_id: string;
  pipeline: string;
  status: string;
  created_at: string;
  total_duration_ms: number;
}

/** #586: backend list_executions list response */
export interface PipelineExecutionListResponse {
  items: PipelineExecutionListItem[];
  total: number;
}

/** 发起管线执行（异步后台任务，返回 execution_id 供轮询） */
export async function executePipeline(body: PipelineExecuteRequest): Promise<PipelineExecuteResponse> {
  return apiFetch<PipelineExecuteResponse>('/api/v1/agent/pipelines/execute', { method: 'POST', body });
}

/** 查询执行状态（status ∈ pending/completed/failed） */
export async function getExecutionStatus(executionId: string): Promise<PipelineExecutionStatus> {
  return apiFetch<PipelineExecutionStatus>(`/api/v1/agent/pipelines/executions/${executionId}`);
}

/** #586: list executions for a project */
export async function listExecutions(projectId: string): Promise<PipelineExecutionListResponse> {
  return apiFetch<PipelineExecutionListResponse>(
    `/api/v1/agent/pipelines/executions?project_id=${projectId}`,
  );
}

/** HITL 人工确认：approved=true 继续执行；false 拒绝（回退固定链） */
export async function confirmExecution(
  executionId: string,
  approved: boolean,
): Promise<PipelineConfirmResponse> {
  return apiFetch<PipelineConfirmResponse>(
    `/api/v1/agent/pipelines/executions/${executionId}/confirm`,
    { method: 'POST', body: { approved } },
  );
}

/** #642-1：管线 SSE 流式帧（镜像 chat.ts ChatStreamFrame；done 帧携带 final_output） */
export interface PipelineStreamFrame {
  type: 'delta' | 'tool_call' | 'tool_result' | 'done' | 'error';
  done: boolean;
  delta?: string;
  error?: string;
  id?: string;
  name?: string;
  args?: Record<string, unknown>;
  result?: string;
  /** #642-1：done 帧携带管线 final_output（与 getExecutionStatus 一致） */
  final_output?: string;
}

export interface PipelineStreamCallbacks {
  onDelta: (delta: string) => void;
  onDone: (frame: PipelineStreamFrame) => void;
  onError: (message: string) => void;
  onToolCall?: (call: { id: string; name: string; args: Record<string, unknown> }) => void;
  onToolResult?: (res: { id: string; name: string; result: string }) => void;
}

/** #642-1：管线 SSE 流式执行。POST /api/v1/agent/pipelines/stream，返回 abort。 */
export async function streamPipeline(
  body: PipelineExecuteRequest,
  callbacks: PipelineStreamCallbacks,
): Promise<() => void> {
  const { baseURL, token } = getApiConfig();
  const controller = new AbortController();

  const run = async () => {
    try {
      const res = await fetch(`${baseURL}/api/v1/agent/pipelines/stream`, {
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
          const frame = JSON.parse(dataLine) as PipelineStreamFrame;
          // 帧分发（镜像 streamChat：#597 工具帧 + #541 delta/done/error）
          if (frame.type === 'tool_call') {
            callbacks.onToolCall?.({ id: frame.id ?? '', name: frame.name ?? '', args: frame.args ?? {} });
            continue;
          }
          if (frame.type === 'tool_result') {
            callbacks.onToolResult?.({
              id: frame.id ?? '',
              name: frame.name ?? '',
              result: frame.result ?? '',
            });
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
