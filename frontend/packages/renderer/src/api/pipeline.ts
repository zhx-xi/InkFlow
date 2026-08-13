/** Agent 管线执行 API 封装（spec §5.6 GUI 写作入口管线化） */
import { apiFetch } from './client';

export interface PipelineExecuteRequest {
  project_id: string;
  pipeline: string;
  chapter_id?: string;
  variables?: Record<string, string>;
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
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  stages: PipelineStageSnapshot[];
  final_output: string;
  total_duration_ms: number;
  error: string;
}

/** 发起管线执行（异步后台任务，返回 execution_id 供轮询） */
export async function executePipeline(body: PipelineExecuteRequest): Promise<PipelineExecuteResponse> {
  return apiFetch<PipelineExecuteResponse>('/api/v1/agent/pipelines/execute', { method: 'POST', body });
}

/** 查询执行状态（status ∈ pending/completed/failed） */
export async function getExecutionStatus(executionId: string): Promise<PipelineExecutionStatus> {
  return apiFetch<PipelineExecutionStatus>(`/api/v1/agent/pipelines/executions/${executionId}`);
}
