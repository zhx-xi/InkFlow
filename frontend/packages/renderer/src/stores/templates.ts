/**
 * Agent 模板 store（Issue #107，spec §9.2 / §9.3 / §9.5）：
 * 模板列表加载/创建/更新/删除/复制 + 默认模板维护。
 * 镜像 src/stores/models.ts 的 zustand 模式（apiFetch + errorMessage）。
 */
import { create } from 'zustand';
import { apiFetch, errorMessage } from '../api/client';

/** 角色键（architect/writer/auditor/reviser 为内置链角色键 = 后端 BUILTIN_AGENT_SPECS.role_key；自定义角色键追加在后；model/temperature null = 跟随默认） */
export interface AgentTemplateRole {
  model: string | null;
  temperature: number | null;
  enabled: boolean;
  /** F42 #295：自定义角色 prompt/name（后端 _to_response 已透出；内置四键可能缺省） */
  prompt?: string | null;
  name?: string | null;
}

/** Agent 模板实体（后端 AgentTemplate DTO；used_by 列表端点即完整实体） */
export interface AgentTemplate {
  id: number;
  name: string;
  description: string;
  main_model: string;
  default_temperature: number;
  /** F42 #295：roles 放宽为索引签名（四键必有语义保留在数据契约，自定义键追加在后） */
  roles: Record<string, AgentTemplateRole>;
  default_words: number;
  is_default: boolean;
  used_by?: Array<{ id: string; name: string }>;
  created_at: string;
  updated_at: string;
}

/** 创建/更新请求体（不含 id / is_default / used_by / 时间戳） */
export interface AgentTemplateInput {
  name: string;
  description: string;
  main_model: string;
  default_temperature: number;
  // 内置 4 键契约（#473 R1：与后端 role_key 对应；AgentTemplate.roles 放宽为 Record 追加自定义键）
  roles: {
    architect: AgentTemplateRole;
    writer: AgentTemplateRole;
    auditor: AgentTemplateRole;
    reviser: AgentTemplateRole;
  };
  default_words: number;
}

/** 列表端点响应信封（§4.4 惯例：{ items, total, offset, limit }） */
interface AgentTemplateListResponse {
  items: AgentTemplate[];
  total: number;
  offset?: number;
  limit?: number;
}

interface TemplatesState {
  templates: AgentTemplate[];
  loading: boolean;
  error: string | null;
  defaultTemplateId: number | null;

  loadTemplates: () => Promise<void>;
  createTemplate: (input: AgentTemplateInput) => Promise<AgentTemplate>;
  updateTemplate: (id: number, patch: Partial<AgentTemplateInput>) => Promise<AgentTemplate>;
  deleteTemplate: (id: number) => Promise<void>;
  duplicateTemplate: (id: number) => Promise<AgentTemplate>;
  setDefault: (id: number) => Promise<void>;
  loadDefault: () => Promise<void>;
}

export const useTemplatesStore = create<TemplatesState>((set) => ({
  templates: [],
  loading: false,
  error: null,
  defaultTemplateId: null,

  loadTemplates: async () => {
    set({ loading: true, error: null });
    try {
      const data = await apiFetch<AgentTemplateListResponse>('/api/v1/agent-templates');
      set({ templates: data.items, loading: false, error: null });
    } catch (err) {
      // 失败不清空已加载列表
      set({ error: errorMessage(err), loading: false });
    }
  },

  createTemplate: async (input) => {
    try {
      const created = await apiFetch<AgentTemplate>('/api/v1/agent-templates', {
        method: 'POST',
        body: input,
      });
      set((s) => ({ templates: [...s.templates, created], error: null }));
      return created;
    } catch (err) {
      set({ error: errorMessage(err) });
      throw err;
    }
  },

  updateTemplate: async (id, patch) => {
    try {
      const updated = await apiFetch<AgentTemplate>(`/api/v1/agent-templates/${id}`, {
        method: 'PATCH',
        body: patch,
      });
      set((s) => ({
        templates: s.templates.map((t) => (t.id === id ? updated : t)),
        error: null,
      }));
      return updated;
    } catch (err) {
      // 失败：error 设置 + 列表不变 + rethrow（保存流程需感知失败）
      set({ error: errorMessage(err) });
      throw err;
    }
  },

  deleteTemplate: async (id) => {
    try {
      await apiFetch(`/api/v1/agent-templates/${id}`, { method: 'DELETE' });
      set((s) => ({ templates: s.templates.filter((t) => t.id !== id), error: null }));
    } catch (err) {
      // 失败（409 被引用等）：列表不变，错误上抛到 error 状态
      set({ error: errorMessage(err) });
    }
  },

  duplicateTemplate: async (id) => {
    try {
      const dup = await apiFetch<AgentTemplate>(`/api/v1/agent-templates/${id}/duplicate`, {
        method: 'POST',
      });
      set((s) => ({ templates: [...s.templates, dup], error: null }));
      return dup;
    } catch (err) {
      set({ error: errorMessage(err) });
      throw err;
    }
  },

  setDefault: async (id) => {
    try {
      // 后端 SetDefaultRequest.id 契约为 str（Pydantic v2 拒绝 int → 422），必须 String(id)
      await apiFetch('/api/v1/agent-templates/default', { method: 'PATCH', body: { id: String(id) } });
      set((s) => ({
        defaultTemplateId: id,
        templates: s.templates.map((t) => ({ ...t, is_default: t.id === id })),
        error: null,
      }));
    } catch (err) {
      set({ error: errorMessage(err) });
    }
  },

  loadDefault: async () => {
    try {
      const data = await apiFetch<AgentTemplate>('/api/v1/agent-templates/default');
      set({ defaultTemplateId: data.id, error: null });
    } catch (err) {
      set({ error: errorMessage(err) });
    }
  },
}));
