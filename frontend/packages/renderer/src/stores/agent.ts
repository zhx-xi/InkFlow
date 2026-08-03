/** Agent 配置 store（映射 ProjectConfig 表单，spec §4.2.3；保存 = PATCH /projects/{id}） */
import { create } from 'zustand';
import type { ProjectConfig } from './project';

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
}

export const useAgentStore = create<AgentState>((set) => ({
  config: {},
  apiKeyDraft: '',
  testStatus: 'idle',
  testMessage: null,

  setConfig: (patch) => set((s) => ({ config: { ...s.config, ...patch } })),
  setApiKeyDraft: (apiKeyDraft) => set({ apiKeyDraft }),
  setTestStatus: (testStatus, testMessage = null) => set({ testStatus, testMessage }),
  loadFromProject: (config) => set({ config, testStatus: 'idle', testMessage: null }),
}));
