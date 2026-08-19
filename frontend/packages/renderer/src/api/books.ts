/** F44 #335：书级编排（书计划访谈 + 写作运行）REST API 封装，镜像 pipeline.ts 模式（S1a #441 契约） */
import { apiFetch } from './client';

export interface PlannerQuestion {
  id: string;
  text: string;
  template: string;
  /** F44 v1.2 #475：问题类型（conflict=冲突回问；可选，既有 seed 无 kind 向后兼容） */
  kind?: 'general' | 'targeted' | 'conflict';
}

/** F44 v1.2 #475：末尾总体确认阶段确定项（wire 契约） */
export interface ConfirmedItem {
  key: string;
  value: string;
  source: 'user' | 'llm_inferred' | 'auto';
}

/** F44 v1.2 #475：冲突记录（round/question_id/answer 可选，向后兼容） */
export interface ConflictRecord {
  round?: number;
  question_id?: string;
  answer?: string;
  conflict_with: string;
  resolution: 'pending' | 'resolved';
}

export interface PlannerStartResponse {
  session_id: string;
  round: number;
  questions: PlannerQuestion[];
  max_rounds: number;
  /** F44 v1.2 #475：末尾总体确认数据（可选，向后兼容） */
  confirmed_items?: ConfirmedItem[];
  conflicts?: ConflictRecord[];
  confirming?: boolean;
}

export interface PlannerRespondRequest {
  /** v1.2 #475：confirm=true（末尾总体确认）时无 answers 键 */
  answers?: Record<string, string>;
  auto?: boolean;
  /** F44 v1.2 #475：末尾总体确认（confirm=true 时请求体不含 auto 键） */
  confirm?: boolean;
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
  /** F44 v1.2 #475：末尾总体确认数据（可选，向后兼容） */
  confirmed_items?: ConfirmedItem[];
  conflicts?: ConflictRecord[];
  confirming?: boolean;
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
  /** F44 v1.2 #475：末尾总体确认数据（可选，向后兼容） */
  confirmed_items?: ConfirmedItem[];
  conflicts?: ConflictRecord[];
  confirming?: boolean;
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
  /** F44 阶段3 #337：HITL 暂停标志 + 确认载荷（可选，向后兼容） */
  waiting_hitl?: boolean;
  hitl_payload?: HitlPayload | null;
}

/** F44 阶段3 #337：卷级 HITL 确认载荷（卷边界 / 卷失败两种形态） */
export interface HitlPayload {
  question: string;
  volume_index?: number;
  /** 卷边界：章 outline_id → done/failed */
  progress?: Record<string, string>;
  /** 卷失败：failed 章列表 */
  failed?: string[];
}

export interface ConfirmRunRequest {
  approved?: boolean;
  decision?: string;
}

export interface ConfirmRunResponse {
  run_id: string;
  status: string;
  hitl_payload?: HitlPayload | null;
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
    // v1.2 #475：confirm=true（末尾总体确认）时 body 精确为 {confirm:true}，不注入 auto 键
    body: { ...body, ...(body.confirm === true ? {} : { auto: body.auto ?? false }) },
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

/** 提交卷级 HITL 确认（approve/reject 或卷失败三决策；响应仍 waiting_hitl → 下一卷再次暂停） */
export async function confirmBookRun(runId: string, body: ConfirmRunRequest): Promise<ConfirmRunResponse> {
  return apiFetch<ConfirmRunResponse>(`/api/v1/agent/books/runs/${runId}/confirm`, { method: 'POST', body });
}

/** F44 阶段4 #338：运行干预动作（暂停/继续/重定向/编辑 brief） */
export type InterveneAction = 'pause' | 'resume' | 'redirect' | 'edit';

/** 运行干预请求体（S4a #453：action + 按动作可选字段） */
export interface InterveneRequest {
  action: InterveneAction;
  /** redirect/edit：章 outline_id */
  target?: string;
  /** redirect：skip | retry | mark_failed */
  to?: string;
  /** edit：新章 brief */
  payload?: { brief?: string };
}

/** 干预 diff 高亮（redirect 形态 from/to；edit 形态 before/after/diff） */
export interface InterveneDiff {
  target: string;
  from?: string;
  to?: string;
  before?: string;
  after?: string;
  diff?: string;
}

/** 干预响应（pause/resume 无 diff；redirect/edit 带 diff） */
export interface InterveneResponse {
  run_id: string;
  status: string;
  diff?: InterveneDiff;
}

/** 回归摘要步骤行（progress/execution_refs 派生，不含章名） */
export interface RunSummaryStep {
  index: number;
  outline_id: string;
  status: string;
  execution_id: string | null;
}

/** 回归摘要 next 卷信息（无 checkpoint → {finished:true}） */
export interface RunSummaryNext {
  volume_index?: number | null;
  total_volumes?: number | null;
  finished: boolean;
  status?: string | null;
}

/** 回归摘要全量（GET /runs/{id}/summary） */
export interface RunSummaryResponse {
  run_id: string;
  status: string;
  progress: Record<string, string>;
  counters: RunStatusCounters;
  steps: RunSummaryStep[];
  next: RunSummaryNext;
}

/** 干预运行（pause/resume/redirect/edit；404 运行不存在 / 422 其他） */
export async function interveneBookRun(runId: string, body: InterveneRequest): Promise<InterveneResponse> {
  return apiFetch<InterveneResponse>(`/api/v1/agent/books/runs/${runId}/intervene`, { method: 'POST', body });
}

/** 回归摘要（progress/counters/steps/next 全量透传） */
export async function getBookRunSummary(runId: string): Promise<RunSummaryResponse> {
  return apiFetch<RunSummaryResponse>(`/api/v1/agent/books/runs/${runId}/summary`);
}
