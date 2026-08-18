/**
 * Agent 管理 store（Issue #260 F41，spec §5.5 / §8.3）：
 * Agent 列表 / 工具目录 / 技能列表加载 + CRUD。
 * 镜像 src/stores/templates.ts 的 apiFetch + errorMessage 模式。
 */
import { create } from 'zustand';
import { apiFetch, errorMessage } from '../api/client';

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
  created_at: string | null;
  updated_at: string | null;
}

/** 创建/更新请求体（不含 id/builtin/时间戳） */
export interface AgentInput {
  name: string;
  description: string;
  icon: string;
  system_prompt: string;
  tool_ids: string[];
  skill_ids: string[];
  model_override: string | null;
  temperature_override: number | null;
}

/** 工具目录项（GET /agents/tools；group ∈ writing|retrieval|audit|project） */
export interface ToolSpec {
  name: string;
  description: string;
  group: string;
  input_schema: unknown;
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
}));
