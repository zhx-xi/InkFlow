/** Agent 配置 store（映射 ProjectConfig 表单，spec §4.2.3；保存 = PATCH /projects/{id}） */
import { create } from 'zustand';
import { apiFetch, errorMessage } from '../api/client';
import type { ProjectConfig } from './project';

export interface ApiKeyInput {
  provider: string;
  model: string;
  api_key: string;
}

interface LlmTestResponse {
  ok: boolean;
  message?: string;
  /** 兼容旧契约响应的原因字段（页面级测试仍 mock error） */
  error?: string;
}

interface AgentState {
  /** 表单草稿（未保存） */
  config: ProjectConfig;
  /** API Key 输入（仅内存，提交到 /settings/llm-keys 后清空） */
  apiKeyDraft: string;
  /** 测试连接状态 */
  testStatus: 'idle' | 'testing' | 'ok' | 'fail';
  testMessage: string | null;

  setConfig: (patch: Partial<ProjectConfig>) => void;
  setApiKeyDraft: (key: string) => void;
  setTestStatus: (status: AgentState['testStatus'], message?: string | null) => void;
  /** 从项目加载（打开 Agent 页时） */
  loadFromProject: (config: ProjectConfig) => void;

  submitApiKey: (input: ApiKeyInput) => Promise<void>;
  testConnection: (input: ApiKeyInput) => Promise<void>;
  saveConfig: (projectId: string, provider?: string) => Promise<void>;
}

export const useAgentStore = create<AgentState>((set, get) => ({
  config: {},
  apiKeyDraft: '',
  testStatus: 'idle',
  testMessage: null,

  setConfig: (patch) => set((s) => ({ config: { ...s.config, ...patch } })),
  setApiKeyDraft: (apiKeyDraft) => set({ apiKeyDraft }),
  setTestStatus: (testStatus, testMessage = null) => set({ testStatus, testMessage }),
  loadFromProject: (config) => set({ config, testStatus: 'idle', testMessage: null }),

  submitApiKey: async (input) => {
    await apiFetch('/api/v1/settings/llm-keys', { method: 'POST', body: input });
    set({ apiKeyDraft: '' });
  },

  testConnection: async (input) => {
    set({ testStatus: 'testing', testMessage: null });
    try {
      const res = await apiFetch<LlmTestResponse>('/api/v1/settings/llm/test', {
        method: 'POST',
        body: input,
      });
      if (res.ok) {
        set({ testStatus: 'ok', testMessage: '连接成功' });
      } else {
        set({ testStatus: 'fail', testMessage: `连接失败: ${res.message ?? res.error ?? '未知错误'}` });
      }
    } catch (err) {
      set({ testStatus: 'fail', testMessage: `连接失败: ${errorMessage(err)}` });
    }
  },

  saveConfig: async (projectId, provider) => {
    const { config, apiKeyDraft } = get();
    // Q3 主路径：先落 key（加密存储），清空 draft，再 PATCH config
    if (apiKeyDraft) {
      await apiFetch('/api/v1/settings/llm-keys', {
        method: 'POST',
        body: { provider: provider ?? '', model: config.model ?? '', api_key: apiKeyDraft },
      });
      set({ apiKeyDraft: '' });
    }
    await apiFetch(`/api/v1/projects/${projectId}`, {
      method: 'PATCH',
      body: { config },
    });
  },
}));
