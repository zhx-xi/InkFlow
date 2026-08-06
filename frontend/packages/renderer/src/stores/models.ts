/**
 * 模型管理 store（Issue #106，spec §8.2③ / §8.3 / §8.6 M3/M4）：
 * provider 注册表加载/增删 + 选中模型 + 角色绑定草稿（六槽位）。
 */
import { create } from 'zustand';
import { apiFetch, errorMessage } from '../api/client';

export interface ProviderModel {
  id: string;
  type: 'chat' | 'embedding';
  roles: string[];
}

export interface ProviderConfig {
  id: string;
  name: string;
  base_url: string;
  default_model: string;
  models: ProviderModel[];
  key_saved: boolean;
  max_retries: number;
  timeout: number;
  created_at: string;
  updated_at: string;
}

/** 列表端点响应信封（§4.4 惯例：{ items, total, offset, limit }） */
export interface ProviderListResponse {
  items: ProviderConfig[];
  total: number;
  offset?: number;
  limit?: number;
}

/** 角色绑定草稿：写作主模型 + 四角色 + RAG embedding（六槽位） */
export interface RoleBindingDraft {
  main: string;
  architect: string;
  writer: string;
  auditor: string;
  reviser: string;
  embedding: string;
}

export const EMPTY_ROLE_BINDING: RoleBindingDraft = {
  main: '',
  architect: '',
  writer: '',
  auditor: '',
  reviser: '',
  embedding: '',
};

export interface AddProviderInput {
  name: string;
  base_url: string;
  api_key?: string;
}

interface ModelsState {
  providers: ProviderConfig[];
  loading: boolean;
  error: string | null;
  selectedModelId: string | null;
  roleBinding: RoleBindingDraft;

  loadProviders: () => Promise<void>;
  addProvider: (input: AddProviderInput) => Promise<ProviderConfig>;
  deleteProvider: (id: string) => Promise<void>;
  selectModel: (id: string | null) => void;
  setRoleBinding: (role: keyof RoleBindingDraft, modelId: string) => void;
}

export const useModelsStore = create<ModelsState>((set) => ({
  providers: [],
  loading: false,
  error: null,
  selectedModelId: null,
  roleBinding: { ...EMPTY_ROLE_BINDING },

  loadProviders: async () => {
    set({ loading: true, error: null });
    try {
      // 列表端点惯例：{ items, total } 信封；兼容裸数组响应（失败路径契约 mock）
      const data = await apiFetch<ProviderListResponse | ProviderConfig[]>(
        '/api/v1/provider-configs',
      );
      const providers = Array.isArray(data) ? data : data.items;
      set({ providers, loading: false, error: null });
    } catch (err) {
      // 失败不清空已加载列表
      set({ error: errorMessage(err), loading: false });
    }
  },

  addProvider: async (input) => {
    const { name, base_url, api_key } = input;
    try {
      // Q3 主路径：填了 Key 先加密落盘（/settings/llm-keys），再注册 provider-configs
      if (api_key) {
        await apiFetch('/api/v1/settings/llm-keys', {
          method: 'POST',
          body: { provider: name, api_key },
        });
      }
      const created = await apiFetch<ProviderConfig>('/api/v1/provider-configs', {
        method: 'POST',
        body: { name, base_url },
      });
      set((s) => ({ providers: [...s.providers, created], error: null }));
      return created;
    } catch (err) {
      set({ error: errorMessage(err) });
      throw err;
    }
  },

  deleteProvider: async (id) => {
    try {
      await apiFetch(`/api/v1/provider-configs/${id}`, { method: 'DELETE' });
      set((s) => ({ providers: s.providers.filter((p) => p.id !== id), error: null }));
    } catch (err) {
      // 失败（内置 seed 409 / used_by）：列表不变，错误上抛到 error 状态
      set({ error: errorMessage(err) });
    }
  },

  selectModel: (id) => set({ selectedModelId: id }),

  setRoleBinding: (role, modelId) =>
    set((s) => ({ roleBinding: { ...s.roleBinding, [role]: modelId } })),
}));
