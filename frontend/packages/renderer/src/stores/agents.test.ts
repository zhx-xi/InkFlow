/**
 * ⚠️ 契约文件（Issue #260 F41 Agent 管理 store，spec §5.5 / §8.3）
 *
 * GREEN 新建 src/stores/agents.ts，必须匹配：
 *
 * 类型契约：
 * - AgentEntity { id: number; name: string; description: string; icon: string;
 *   system_prompt: string; tool_ids: string[]; skill_ids: string[];
 *   model_override: string | null; temperature_override: number | null;
 *   builtin: boolean; created_at: string | null; updated_at: string | null }
 *   （对齐后端 12 字段，model_dump(mode=json)）
 * - AgentInput { name: string; description: string; icon: string;
 *   system_prompt: string; tool_ids: string[]; skill_ids: string[];
 *   model_override: string | null; temperature_override: number | null }
 *   （创建/更新请求体，不含 id/builtin/时间戳）
 * - ToolSpec { name: string; description: string; group: string; input_schema: unknown }
 *   （GET /agents/tools 目录项；group ∈ writing|retrieval|audit|project）
 * - SkillSummary { id: number; name: string; description: string; source: string;
 *   agent_ids?: Array<{ id: number; name: string }> }
 *   （GET /skills 列表项；agent_ids 反查由后端计算）
 *
 * store 契约（useAgentsStore，镜像 stores/templates.ts apiFetch 模式）：
 * - state: agents: AgentEntity[]; tools: ToolSpec[]; skills: SkillSummary[];
 *   loading: boolean; error: string | null
 * - loadAgents(): GET /api/v1/agents → {items,total} → agents；失败 error + 列表不清空
 * - loadToolCatalog(): GET /api/v1/agents/tools → {items} → tools
 * - loadSkills(): GET /api/v1/skills → {items,total} → skills
 * - createAgent(input): POST /api/v1/agents body=AgentInput → 201 实体 → agents 追加 + return；
 *   失败 error + rethrow（保存流程需感知失败）
 * - updateAgent(id, patch): PATCH /api/v1/agents/{id} body=Partial<AgentInput> → 200 → agents 替换 + return；
 *   失败 error + rethrow
 * - deleteAgent(id): DELETE /api/v1/agents/{id}（204）→ agents 过滤；失败 error（不 rethrow，镜像 templates.deleteTemplate）
 *
 * 端点信封（后端实证）：列表 {items,total}；tools {items}；POST/PATCH 返回完整实体（无信封）
 *
 * RED 预期：./stores/agents 模块不存在 → module-not-found（类 1 契约缺口）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { apiFetch } from '../api/client';
import { useAgentsStore } from './agents';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 契约结构（与 stores/agents 契约一致；GREEN 类型可来自 store 或测试内定义） */
interface AgentEntity {
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
  created_at: string | null;
  updated_at: string | null;
}
interface AgentInput {
  name: string;
  description: string;
  icon: string;
  system_prompt: string;
  tool_ids: string[];
  skill_ids: string[];
  model_override: string | null;
  temperature_override: number | null;
}

const BUILTIN_AGENT: AgentEntity = {
  id: 1,
  name: '架构师',
  description: '章节结构/大纲规划',
  icon: '🏗️',
  system_prompt: '你是架构师，负责章节结构与大纲规划。',
  tool_ids: ['search_characters', 'check_foreshadowing', 'get_prior_summary'],
  skill_ids: ['1'],
  model_override: null,
  temperature_override: null,
  builtin: true,
  created_at: '2026-08-16T00:00:00Z',
  updated_at: '2026-08-16T00:00:00Z',
};

const CUSTOM_AGENT: AgentEntity = {
  id: 2,
  name: '我的润色师',
  description: '专注文笔润色的自定义角色',
  icon: '✨',
  system_prompt: '你是润色师，负责润色文笔。',
  tool_ids: ['count_words', 'save_draft'],
  skill_ids: ['3'],
  model_override: 'zhipu/glm-4.5',
  temperature_override: 0.6,
  builtin: false,
  created_at: '2026-08-16T01:00:00Z',
  updated_at: '2026-08-16T01:00:00Z',
};

const CUSTOM_INPUT: AgentInput = {
  name: '我的润色师',
  description: '专注文笔润色的自定义角色',
  icon: '✨',
  system_prompt: '你是润色师，负责润色文笔。',
  tool_ids: ['count_words', 'save_draft'],
  skill_ids: ['3'],
  model_override: 'zhipu/glm-4.5',
  temperature_override: 0.6,
};

const TOOL_ITEMS = [
  { name: 'save_draft', description: '保存章节草稿（agent 唯一写面）', group: 'writing', input_schema: {} },
  { name: 'search_characters', description: '搜索项目内角色档案', group: 'retrieval', input_schema: {} },
  { name: 'count_words', description: '中英文混合字数统计', group: 'audit', input_schema: {} },
];

const SKILL_ITEMS = [
  { id: 1, name: 'outline-planning', description: '大纲规划方法论', source: 'builtin', agent_ids: [{ id: 1, name: '架构师' }] },
  { id: 3, name: 'web-research', description: '网络调研方法论', source: 'user_upload', agent_ids: [] },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  useAgentsStore.setState({
    agents: [],
    tools: [],
    skills: [],
    loading: false,
    error: null,
  });
});

describe('useAgentsStore — 列表加载', () => {
  it('loadAgents: GET /api/v1/agents 信封 {items,total} → agents 填充 + loading false', async () => {
    apiFetchMock.mockResolvedValue({ items: [BUILTIN_AGENT, CUSTOM_AGENT], total: 2 });
    await useAgentsStore.getState().loadAgents();
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agents');
    expect(useAgentsStore.getState().agents).toHaveLength(2);
    expect(useAgentsStore.getState().agents[1].name).toBe('我的润色师');
    expect(useAgentsStore.getState().loading).toBe(false);
    expect(useAgentsStore.getState().error).toBeNull();
  });

  it('loadToolCatalog: GET /api/v1/agents/tools {items} → tools 填充', async () => {
    apiFetchMock.mockResolvedValue({ items: TOOL_ITEMS });
    await useAgentsStore.getState().loadToolCatalog();
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agents/tools');
    expect(useAgentsStore.getState().tools).toHaveLength(3);
    expect(useAgentsStore.getState().tools[0].group).toBe('writing');
  });

  it('loadSkills: GET /api/v1/skills {items,total} → skills 填充', async () => {
    apiFetchMock.mockResolvedValue({ items: SKILL_ITEMS, total: 2 });
    await useAgentsStore.getState().loadSkills();
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/skills');
    expect(useAgentsStore.getState().skills).toHaveLength(2);
    expect(useAgentsStore.getState().skills[1].source).toBe('user_upload');
  });

  it('loadAgents 失败：error 设置 + 已加载列表不清空 + loading false', async () => {
    useAgentsStore.setState({ agents: [BUILTIN_AGENT] });
    apiFetchMock.mockRejectedValue(new Error('network'));
    await useAgentsStore.getState().loadAgents();
    expect(useAgentsStore.getState().error).not.toBeNull();
    expect(useAgentsStore.getState().agents).toHaveLength(1);
    expect(useAgentsStore.getState().loading).toBe(false);
  });
});

describe('useAgentsStore — CRUD', () => {
  it('createAgent: POST /api/v1/agents body=AgentInput → 201 实体追加 + return', async () => {
    apiFetchMock.mockResolvedValue({ ...CUSTOM_AGENT, id: 9 });
    const created = await useAgentsStore.getState().createAgent(CUSTOM_INPUT);
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/agents',
      expect.objectContaining({ method: 'POST', body: CUSTOM_INPUT }),
    );
    expect(created.id).toBe(9);
    expect(useAgentsStore.getState().agents).toHaveLength(1);
    expect(useAgentsStore.getState().agents[0].name).toBe('我的润色师');
  });

  it('createAgent 失败：error 设置 + rethrow（保存流程感知失败）', async () => {
    apiFetchMock.mockRejectedValue(new Error('duplicate'));
    await expect(useAgentsStore.getState().createAgent(CUSTOM_INPUT)).rejects.toThrow('duplicate');
    expect(useAgentsStore.getState().error).not.toBeNull();
    expect(useAgentsStore.getState().agents).toHaveLength(0);
  });

  it('updateAgent: PATCH /api/v1/agents/{id} body=patch → agents 替换 + return', async () => {
    useAgentsStore.setState({ agents: [CUSTOM_AGENT] });
    apiFetchMock.mockResolvedValue({ ...CUSTOM_AGENT, name: '润色师 v2', tool_ids: ['count_words'] });
    const updated = await useAgentsStore.getState().updateAgent(2, { name: '润色师 v2', tool_ids: ['count_words'] });
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/agents/2',
      expect.objectContaining({ method: 'PATCH', body: { name: '润色师 v2', tool_ids: ['count_words'] } }),
    );
    expect(updated.name).toBe('润色师 v2');
    expect(useAgentsStore.getState().agents[0].name).toBe('润色师 v2');
    expect(useAgentsStore.getState().agents).toHaveLength(1);
  });

  it('deleteAgent: DELETE /api/v1/agents/{id} → agents 过滤', async () => {
    useAgentsStore.setState({ agents: [BUILTIN_AGENT, CUSTOM_AGENT] });
    apiFetchMock.mockResolvedValue(undefined);
    await useAgentsStore.getState().deleteAgent(2);
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agents/2', expect.objectContaining({ method: 'DELETE' }));
    expect(useAgentsStore.getState().agents).toHaveLength(1);
    expect(useAgentsStore.getState().agents[0].name).toBe('架构师');
  });
});
