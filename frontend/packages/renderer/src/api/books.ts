/** F44 #335：书级编排（书计划访谈 + 写作运行）REST API 封装，镜像 pipeline.ts 模式（S1a #441 契约） */
import { apiFetch } from './client';

export interface PlannerQuestion {
  id: string;
  text: string;
  template: string;
}

export interface PlannerStartResponse {
  session_id: string;
  round: number;
  questions: PlannerQuestion[];
  max_rounds: number;
}

export interface PlannerRespondRequest {
  answers: Record<string, string>;
  auto?: boolean;
}

export interface WritingPlanDto {
  id: string;
  project_id: string;
  title: string;
  status: string;
  root_outline_id: string | null;
  character_ids: string[];
  limits: Record<string, number>;
  progress: Record<string, string>;
  execution_refs: Record<string, string>;
  thread_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlannerRespondResponse {
  session_id: string;
  round: number;
  completed: boolean;
  questions: PlannerQuestion[];
  writing_plan: WritingPlanDto | null;
}

export interface PlannerSessionDto {
  id: string;
  project_id: string;
  status: string;
  one_liner: string;
  round: number;
  asked_questions: PlannerQuestion[];
  answers: Record<string, string>;
  authorized: string[];
  writing_plan_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface BookRunRequest {
  writing_plan_id: string;
  limits?: Record<string, number>;
  mode?: string;
}

export interface BookRunResponse {
  run_id: string;
  status: string;
}

export interface RunStatusCounters {
  max_chapters: number;
  max_agent_calls: number;
  agent_calls: number;
  chapters_written: number;
  /** S2a #445：token 软护栏（可选键向后兼容） */
  max_tokens?: number;
  tokens_used?: number;
  tokens_warning?: boolean;
}

export interface RunStatusResponse {
  run_id: string;
  status: string;
  progress: Record<string, string>;
  counters: RunStatusCounters;
}

/** 启动书计划访谈（POST /planner → 201 第一轮问题） */
export async function startPlanner(body: { project_id: string; one_liner: string }): Promise<PlannerStartResponse> {
  return apiFetch<PlannerStartResponse>('/api/v1/agent/books/planner', { method: 'POST', body });
}

/** 回答当前轮问题（auto=false 提交 answers；auto=true 全部你决定） */
export async function respondPlanner(
  sessionId: string,
  body: PlannerRespondRequest,
): Promise<PlannerRespondResponse> {
  return apiFetch<PlannerRespondResponse>(`/api/v1/agent/books/planner/${sessionId}/respond`, {
    method: 'POST',
    body: { ...body, auto: body.auto ?? false },
  });
}

/** 获取访谈会话全量快照（含 answers/authorized） */
export async function getPlannerSession(sessionId: string): Promise<PlannerSessionDto> {
  return apiFetch<PlannerSessionDto>(`/api/v1/agent/books/planner/${sessionId}`);
}

/** 启动书级写作运行（run 载体 = WritingPlan.id，202 异步语义） */
export async function startBookRun(body: BookRunRequest): Promise<BookRunResponse> {
  return apiFetch<BookRunResponse>('/api/v1/agent/books/runs', { method: 'POST', body });
}

/** 查询运行状态（进度表 outline_id → PlanNodeStatus + 计数器） */
export async function getBookRunStatus(runId: string): Promise<RunStatusResponse> {
  return apiFetch<RunStatusResponse>(`/api/v1/agent/books/runs/${runId}`);
}
