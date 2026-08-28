/** F27 Agent Run 决策轨迹 API 封装（#599 统一执行视图：agentic 动态工具调用流数据源）
 *
 * - getRun: 单次 agentic run 决策轨迹（GET /api/v1/agent/runs/{id}）
 * - listRuns: 项目 run 列表（倒序分页，GET /api/v1/agent/runs?project_id=<id>&limit=<n>）
 *
 * 后端 agent_runs.py（F27）已注册这两个端点；本模块将响应映射为类型化 DTO。
 */
import { apiFetch } from './client';

/** 单次工具调用记录（领域 AgentToolCall，model_dump(mode='json') 形态） */
export interface AgentToolCallDto {
  step_index: number;
  tool_name: string;
  arguments: Record<string, unknown>;
  result: string;
  /** 工具执行是否失败（工具信封 {"ok": false}） */
  is_error: boolean;
}

/** 单次 LLM 决策步骤快照（领域 AgentStep） */
export interface AgentStepDto {
  index: number;
  /** 该步 AIMessage 文本（空 = 只调工具） */
  message_content: string;
  /** 该步 LLM 思考过程（reasoning_content；推理模型才有，#740） */
  reasoning?: string;
  tool_calls: AgentToolCallDto[];
  tokens: number;
}

/** 一次 agentic 运行记录（领域 AgentRun） */
export interface AgentRunDto {
  id: string;
  project_id: string;
  chapter_id: string | null;
  mode: string;
  status: string;
  steps: AgentStepDto[];
  final_content: string;
  draft_id: string | null;
  model: string;
  token_usage_total: number;
  terminated_by: string;
  created_at: string;
  updated_at: string;
}

/** 拉取单次 agentic run 决策轨迹（GET /api/v1/agent/runs/{id}） */
export async function getRun(runId: string): Promise<AgentRunDto> {
  return apiFetch<AgentRunDto>(`/api/v1/agent/runs/${runId}`);
}

/** 项目 run 列表（倒序分页，GET /api/v1/agent/runs?project_id=<id>&limit=<n>） */
export async function listRuns(
  projectId: string,
  limit = 20,
): Promise<{ items: AgentRunDto[]; total: number }> {
  const qs = new URLSearchParams({ project_id: projectId, limit: String(limit) });
  return apiFetch<{ items: AgentRunDto[]; total: number }>(`/api/v1/agent/runs?${qs.toString()}`);
}
