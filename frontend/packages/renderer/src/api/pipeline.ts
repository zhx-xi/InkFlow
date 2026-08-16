/** Agent 管线执行 API 封装（spec §5.6 GUI 写作入口管线化） */
import { apiFetch } from './client';

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

export interface PipelineExecutionStatus {
  execution_id: string;
  pipeline: string;
  project_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'waiting_hitl';
  stages: PipelineStageSnapshot[];
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

/** 发起管线执行（异步后台任务，返回 execution_id 供轮询） */
export async function executePipeline(body: PipelineExecuteRequest): Promise<PipelineExecuteResponse> {
  return apiFetch<PipelineExecuteResponse>('/api/v1/agent/pipelines/execute', { method: 'POST', body });
}

/** 查询执行状态（status ∈ pending/completed/failed） */
export async function getExecutionStatus(executionId: string): Promise<PipelineExecutionStatus> {
  return apiFetch<PipelineExecutionStatus>(`/api/v1/agent/pipelines/executions/${executionId}`);
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
