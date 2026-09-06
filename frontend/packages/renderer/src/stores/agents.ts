/**
 * Agent 管理 store（Issue #260 F41，spec §5.5 / §8.3）：
 * Agent 列表 / 工具目录 / 技能列表加载 + CRUD。
 * 镜像 src/stores/templates.ts 的 apiFetch + errorMessage 模式。
 */
import { create } from 'zustand';
import { apiFetch, errorMessage } from '../api/client';

/** 工具域（8 值枚举序，spec §2.1；后端 GRANT_TOOL_MAP 域） */
export type ToolDomain =
  | 'outline'
  | 'character'
  | 'world'
  | 'timeline'
  | 'foreshadowing'
  | 'memory'
  | 'writing'
  | 'agent_chain';

/** 域内操作序：read → write → delete（保存 payload ops 序） */
export type ToolOp = 'read' | 'write' | 'delete';

/** 授权条目：domain × ops（grants 提交/回显唯一数据面） */
export interface GrantEntry {
  domain: ToolDomain;
  ops: ToolOp[];
}

/** Agent 实体（对齐后端 13 字段，model_dump(mode=json)） */
export interface AgentEntity {
  id: number;
  name: string;
  description: string;
  icon: string;
  system_prompt: string;
  tool_ids: string[];
  skill_ids: string[];
  model_override: string | null;
  temperature_override: number | null;
  builtin: boolean;
  /** #473 R1：内置链角色键映射（architect/writer/auditor/reviser）；非链内置/自定义为 null */
  role_key?: string | null;
  /**
   * #957 F58：后端 _to_response 恒有（resolve 后，含旧 tool_ids 反查）；
   * 声明可选以兼容旧数据与既有测试 fixture，组件内一律以 `?? []` 兜底。
   */
  grants?: GrantEntry[];
  resolved_tool_names?: string[];
  created_at: string | null;
  updated_at: string | null;
}

/** 创建/更新请求体（不含 id/builtin/时间戳） */
export interface AgentInput {
  name: string;
  description: string;
  icon: string;
  system_prompt: string;
  /** #957 F58：唯一授权提交面；全不勾 = []（后端清除 tool_ids） */
  grants: GrantEntry[];
  skill_ids: string[];
  model_override: string | null;
  temperature_override: number | null;
}

/**
 * 工具目录项（GET /agents/tools；group ∈ writing|retrieval|audit|project）。
 * #838: allow_custom_agent=false = is_core 核心工具（自定义 agent 选择列表不渲染）。
 */
export interface ToolSpec {
  name: string;
  description: string;
  group: string;
  input_schema: unknown;
  allow_custom_agent: boolean;
  is_core: boolean;
  /**
   * #957 F58：catalog 每项已带 domain/op（is_core 不进目录）；
   * 运行值属于 ToolDomain/ToolOp 枚举，类型放宽为 string 兼容测试 fixture 的字面量收窄。
   */
  domain: string;
  op: string;
}

/** 技能列表项（GET /skills；agent_ids 反查由后端计算） */
export interface SkillSummary {
  id: number;
  name: string;
  description: string;
  source: string;
  agent_ids?: Array<{ id: number; name: string }>;
}

/** 列表端点响应信封（§4.4 惯例：{ items, total }） */
interface AgentListResponse {
  items: AgentEntity[];
  total: number;
}

interface ToolCatalogResponse {
  items: ToolSpec[];
}

interface SkillListResponse {
  items: SkillSummary[];
  total: number;
}

interface AgentsState {
  agents: AgentEntity[];
  tools: ToolSpec[];
  skills: SkillSummary[];
  loading: boolean;
  error: string | null;

  loadAgents: () => Promise<void>;
  loadToolCatalog: () => Promise<void>;
  loadSkills: () => Promise<void>;
  createAgent: (input: AgentInput) => Promise<AgentEntity>;
  updateAgent: (id: number, patch: Partial<AgentInput>) => Promise<AgentEntity>;
  deleteAgent: (id: number) => Promise<void>;
  copyAgent: (id: number) => Promise<AgentEntity>;
}

export const useAgentsStore = create<AgentsState>((set) => ({
  agents: [],
  tools: [],
  skills: [],
  loading: false,
  error: null,

  loadAgents: async () => {
    set({ loading: true, error: null });
    try {
      const data = await apiFetch<AgentListResponse>('/api/v1/agents');
      set({ agents: data.items, loading: false, error: null });
    } catch (err) {
      // 失败不清空已加载列表
      set({ error: errorMessage(err), loading: false });
    }
  },

  loadToolCatalog: async () => {
    try {
      const data = await apiFetch<ToolCatalogResponse>('/api/v1/agents/tools');
      set({ tools: data.items, error: null });
    } catch (err) {
      set({ error: errorMessage(err) });
    }
  },

  loadSkills: async () => {
    try {
      const data = await apiFetch<SkillListResponse>('/api/v1/skills');
      set({ skills: data.items, error: null });
    } catch (err) {
      set({ error: errorMessage(err) });
    }
  },

  createAgent: async (input) => {
    try {
      const created = await apiFetch<AgentEntity>('/api/v1/agents', {
        method: 'POST',
        body: input,
      });
      set((s) => ({ agents: [...s.agents, created], error: null }));
      return created;
    } catch (err) {
      // 失败：error 设置 + 列表不变 + rethrow（保存流程需感知失败）
      set({ error: errorMessage(err) });
      throw err;
    }
  },

  updateAgent: async (id, patch) => {
    try {
      const updated = await apiFetch<AgentEntity>(`/api/v1/agents/${id}`, {
        method: 'PATCH',
        body: patch,
      });
      set((s) => ({
        agents: s.agents.map((a) => (a.id === id ? updated : a)),
        error: null,
      }));
      return updated;
    } catch (err) {
      set({ error: errorMessage(err) });
      throw err;
    }
  },

  deleteAgent: async (id) => {
    try {
      await apiFetch(`/api/v1/agents/${id}`, { method: 'DELETE' });
      set((s) => ({ agents: s.agents.filter((a) => a.id !== id), error: null }));
    } catch (err) {
      // 失败（409 内置等）：列表不变，错误上抛到 error 状态
      set({ error: errorMessage(err) });
    }
  },

  copyAgent: async (id) => {
    try {
      const created = await apiFetch<AgentEntity>(`/api/v1/agents/${id}/duplicate`, {
        method: 'POST',
      });
      set((s) => ({ agents: [...s.agents, created], error: null }));
      return created;
    } catch (err) {
      // 失败：error 设置 + 列表不变 + rethrow（复制流程需感知失败）
      set({ error: errorMessage(err) });
      throw err;
    }
  },
}));
