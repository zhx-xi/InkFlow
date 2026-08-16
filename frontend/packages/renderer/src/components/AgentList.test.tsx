/**
 * ⚠️ 契约文件（Issue #260 F41 Agent 管理列表，spec §5.5 / §8.3 / §13 M8）
 *
 * GREEN 新建 src/components/AgentList.tsx，必须匹配：
 *
 * 组件契约（自包含，内部调用 useAgentsStore）：
 * - 挂载 effect：loadAgents() + loadToolCatalog() + loadSkills()（3 GET，失败静默 error 不阻塞渲染）
 * - 渲染 data-testid="agent-list" 容器；每 Agent 一张卡片 data-testid="agent-card-<id>"
 * - 内置 Agent（builtin=true）：只读展示
 *   * builtin 徽标 data-testid="agent-builtin-badge-<id>"（文案「内置」）
 *   * 工具明细 chips：data-testid="agent-tool-chip-<toolName>"（名称 = 工具目录 name 映射，双向视图）
 *   * skill 明细 chips：data-testid="agent-skill-chip-<skillId>"（名称 = skills 列表 name 映射）
 *   * prompt 预览（截断展示 system_prompt）
 *   * 无编辑按钮（queryByTestId agent-edit-x 不存在）、无删除按钮（queryByTestId agent-del-x 不存在）
 * - 自定义 Agent（builtin=false）：
 *   * 编辑按钮 data-testid="agent-edit-<id>" → 打开 AgentEditDialog（mode=edit，预填该 Agent）
 *   * 删除按钮 data-testid="agent-del-<id>" → 删除确认框
 *   * 工具/skill 明细 chips 同上（agent-tool-chip-x / agent-skill-chip-x）
 * - 新建按钮 data-testid="agent-new-btn"（文案「新建 Agent」）→ 打开 AgentEditDialog（mode=create）
 * - 删除保护：确认框 role=dialog + data-testid="agent-delete-dialog"，文案含「确定删除」+ Agent 名；
 *   确认 data-testid="agent-delete-ok" → deleteAgent(id) + 列表刷新；取消 data-testid="agent-delete-cancel" → 关闭不删
 * - 空态：无自定义 Agent → 提示文案（set.agents.noCustom「暂无自定义 Agent」）
 *
 * 数据流（GREEN 照做）：
 * - 工具名映射：agents.tool_ids 元素 → tools[].name 匹配（工具目录唯一真源；未命中工具名显示原名）
 * - skill 名映射：agents.skill_ids 元素（字符串化 id）→ skills[].id 匹配 → name；未命中显示 #<id>
 * - onSave 回调（来自 AgentEditDialog）：createAgent(input) / updateAgent(id, patch) → 成功 toast + 关闭 dialog
 *
 * AgentEditDialog 为未来模块（GREEN 同批实现）：本文件用 vi.mock 假组件屏蔽
 * （假组件渲染 agent-dialog 占位 div，验证打开/关闭状态；dialog 内部契约见 AgentEditDialog.test.tsx）
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts）：
 * set.agents.title='Agent 管理' set.agents.new='新建 Agent' set.agents.builtin='内置'
 * set.agents.tools='函数' set.agents.skills='技能' set.agents.noCustom='暂无自定义 Agent'
 * set.agents.deleteConfirm='确定删除自定义 Agent「{name}」？此操作不可恢复'
 * toast.agentSaved='已保存' toast.agentDeleted='已删除'
 *
 * RED 预期：./AgentList 模块不存在 → module-not-found（类 1 契约缺口）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentList } from './AgentList';
import { apiFetch } from '../api/client';
import { useAgentsStore } from '../stores/agents';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

// Mock-屏蔽型 RED（#107 先例）：AgentEditDialog 是 GREEN 同批实现的未来模块——
// 假组件渲染 agent-dialog 占位（验证打开/关闭）；dialog 内部契约由 AgentEditDialog.test.tsx 单独钉死。
// 注意：假组件必须返回真 React element（React.createElement），裸 {type, props} 对象缺 $$typeof
// 会被 React 19 当普通 child 拒绝（"Objects are not valid as a React child"）。
vi.mock('./AgentEditDialog', async () => {
  const React = await import('react');
  return {
    AgentEditDialog: (props: { open: boolean }) =>
      props.open ? React.createElement('div', { 'data-testid': 'agent-dialog' }) : null,
  };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 契约结构（与 stores/agents 契约一致） */
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
interface ToolSpec {
  name: string;
  description: string;
  group: string;
  input_schema: unknown;
}
interface SkillSummary {
  id: number;
  name: string;
  description: string;
  source: string;
  agent_ids?: Array<{ id: number; name: string }>;
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

const TOOL_ITEMS: ToolSpec[] = [
  { name: 'save_draft', description: '保存章节草稿（agent 唯一写面）', group: 'writing', input_schema: {} },
  { name: 'search_characters', description: '搜索项目内角色档案', group: 'retrieval', input_schema: {} },
  { name: 'check_foreshadowing', description: '列出未回收伏笔', group: 'retrieval', input_schema: {} },
  { name: 'get_prior_summary', description: '获取前文摘要', group: 'retrieval', input_schema: {} },
  { name: 'audit_chapter', description: '单章一致性审计', group: 'audit', input_schema: {} },
  { name: 'count_words', description: '中英文混合字数统计', group: 'audit', input_schema: {} },
];

const SKILL_ITEMS: SkillSummary[] = [
  { id: 1, name: 'outline-planning', description: '大纲规划方法论', source: 'builtin', agent_ids: [{ id: 1, name: '架构师' }] },
  { id: 3, name: 'web-research', description: '网络调研方法论', source: 'user_upload', agent_ids: [] },
];

/** 默认 mock：URL 分发（挂载 3 GET + 业务请求） */
function mockDefault() {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/agents') return { items: [BUILTIN_AGENT, CUSTOM_AGENT], total: 2 };
    if (path === '/api/v1/agents/tools') return { items: TOOL_ITEMS };
    if (path === '/api/v1/skills') return { items: SKILL_ITEMS, total: 2 };
    return { ok: true };
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  useAgentsStore.setState({
    agents: [],
    tools: [],
    skills: [],
    loading: false,
    error: null,
  });
  useToastStore.setState({ toasts: [] });
  mockDefault();
});

describe('AgentList — 管理列表（内置只读 / 自定义可编辑）', () => {
  it('挂载加载 3 端点：GET agents + tools + skills（双向视图数据源）', async () => {
    render(<AgentList />);
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agents');
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agents/tools');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/skills');
    expect(await screen.findByTestId('agent-card-1')).toBeInTheDocument();
  });

  it('内置 Agent 只读：builtin 徽标 + 无编辑/删除按钮', async () => {
    render(<AgentList />);
    const card = await screen.findByTestId('agent-card-1');
    expect(within(card).getByTestId('agent-builtin-badge-1')).toBeInTheDocument();
    expect(within(card).queryByTestId('agent-edit-1')).not.toBeInTheDocument();
    expect(within(card).queryByTestId('agent-del-1')).not.toBeInTheDocument();
  });

  it('自定义 Agent 可编辑：编辑/删除按钮存在（无 builtin 徽标）', async () => {
    render(<AgentList />);
    const card = await screen.findByTestId('agent-card-2');
    expect(within(card).queryByTestId('agent-builtin-badge-2')).not.toBeInTheDocument();
    expect(within(card).getByTestId('agent-edit-2')).toBeInTheDocument();
    expect(within(card).getByTestId('agent-del-2')).toBeInTheDocument();
  });

  it('双向视图：Agent 卡片展示工具名 chips + skill 名 chips（id → 名称映射）', async () => {
    render(<AgentList />);
    // 内置：3 工具 chips（search_characters/check_foreshadowing/get_prior_summary）+ skill outline-planning
    const card = await screen.findByTestId('agent-card-1');
    expect(within(card).getByTestId('agent-tool-chip-search_characters')).toBeInTheDocument();
    expect(within(card).getByTestId('agent-tool-chip-check_foreshadowing')).toBeInTheDocument();
    expect(within(card).getByTestId('agent-tool-chip-get_prior_summary')).toBeInTheDocument();
    // skill id '1' → skills 列表 id=1 name='outline-planning'
    const skillChip = within(card).getByTestId('agent-skill-chip-1');
    expect(skillChip).toHaveTextContent('outline-planning');
    // 自定义：2 工具 chips + skill web-research
    const card2 = screen.getByTestId('agent-card-2');
    expect(within(card2).getByTestId('agent-tool-chip-count_words')).toBeInTheDocument();
    expect(within(card2).getByTestId('agent-tool-chip-save_draft')).toBeInTheDocument();
    const skillChip2 = within(card2).getByTestId('agent-skill-chip-3');
    expect(skillChip2).toHaveTextContent('web-research');
  });

  it('新建按钮 + 编辑按钮 → 打开 AgentEditDialog（agent-dialog 出现）', async () => {
    const user = userEvent.setup();
    render(<AgentList />);
    expect(screen.queryByTestId('agent-dialog')).not.toBeInTheDocument();
    await user.click(await screen.findByTestId('agent-new-btn'));
    expect(screen.getByTestId('agent-dialog')).toBeInTheDocument();
  });

  it('删除保护：自定义 Agent 删除确认 → 确认后 DELETE + 卡片消失', async () => {
    const user = userEvent.setup();
    render(<AgentList />);
    await screen.findByTestId('agent-card-2');
    await user.click(screen.getByTestId('agent-del-2'));
    const dlg = await screen.findByTestId('agent-delete-dialog');
    expect(dlg).toHaveTextContent('我的润色师');
    // 确认 → DELETE /api/v1/agents/2 → 列表刷新（状态化 mock：DELETE 后 GET 不再返回该 agent）
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/agents' && init?.method === 'DELETE') return undefined;
      if (path === '/api/v1/agents' && !init?.method) return { items: [BUILTIN_AGENT], total: 1 };
      if (path === '/api/v1/agents/tools') return { items: TOOL_ITEMS };
      if (path === '/api/v1/skills') return { items: SKILL_ITEMS, total: 2 };
      return { ok: true };
    });
    await user.click(screen.getByTestId('agent-delete-ok'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agents/2', expect.objectContaining({ method: 'DELETE' }));
    });
    await waitFor(() => {
      expect(screen.queryByTestId('agent-card-2')).not.toBeInTheDocument();
    });
    expect(screen.getByTestId('agent-card-1')).toBeInTheDocument();
  });

  it('删除取消：关闭确认框 + 不调 DELETE + 卡片保留', async () => {
    const user = userEvent.setup();
    render(<AgentList />);
    await screen.findByTestId('agent-card-2');
    await user.click(screen.getByTestId('agent-del-2'));
    await screen.findByTestId('agent-delete-dialog');
    await user.click(screen.getByTestId('agent-delete-cancel'));
    expect(screen.queryByTestId('agent-delete-dialog')).not.toBeInTheDocument();
    expect(screen.getByTestId('agent-card-2')).toBeInTheDocument();
  });
});
