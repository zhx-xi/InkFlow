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
 * #485 内置 Agent 详情 + 复制（追加契约，2026-08-19）：
 * - 内置卡片（builtin=true）新增「详情」按钮 data-testid=agent-detail-{id}、「复制」按钮
 *   data-testid=agent-copy-{id}；自定义卡片（builtin=false）不渲染 agent-detail- / agent-copy- 前缀
 * - 「详情」→ 弹层 data-testid=agent-detail-dialog（role=dialog 或 aria-modal=true 二者满足其一）：
 *   system_prompt 全文 data-testid=agent-detail-prompt、工具列表 data-testid=agent-detail-tool-{toolName}
 *   （每工具一项）、skill 列表 data-testid=agent-detail-skill-{skillId}；弹层数据用 store agents
 *   数组本地渲染——零新请求（详情交互不得触发额外 fetch）；关闭按钮 data-testid=agent-detail-close
 * - 「复制」→ store copyAgent(id)：POST /api/v1/agents/{id}/duplicate → 成功 toast
 *   t('toast.agentCopied')「已复制」（新 i18n key，GREEN 补 zh/en）；失败 → t('toast.saveFailed')「保存失败」
 *   （刷新实现不锁：copyAgent 内部追加或 loadAgents 重拉均可，测试只锁 POST 调用 + toast）
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
  /** #957 F58：后端 _to_response 恒有（resolve 后，含旧 tool_ids 反查） */
  grants?: Array<{ domain: 'outline' | 'character' | 'world' | 'timeline' | 'foreshadowing' | 'memory' | 'writing' | 'agent_chain'; ops: Array<'read' | 'write' | 'delete'> }>;
  resolved_tool_names?: string[];
}
interface ToolSpec {
  name: string;
  description: string;
  group: string;
  input_schema: unknown;
  /** #838: 是否允许自定义 agent 勾选（false = is_core 核心工具，选择区不渲染） */
  allow_custom_agent: boolean;
  /** #838: 核心工具标记（后端工具目录 is_core） */
  is_core: boolean;
  /** #957 F58：catalog 每项已带 domain/op（is_core 不进目录） */
  domain: 'outline' | 'character' | 'world' | 'timeline' | 'foreshadowing' | 'memory' | 'writing' | 'agent_chain';
  op: 'read' | 'write' | 'delete';
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
  grants: [
    { domain: 'character', ops: ['read'] },
    { domain: 'foreshadowing', ops: ['read'] },
    { domain: 'writing', ops: ['read'] },
  ],
  resolved_tool_names: ['search_characters', 'check_foreshadowing', 'get_prior_summary'],
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
  grants: [{ domain: 'writing', ops: ['read', 'write'] }],
  resolved_tool_names: ['count_words', 'save_draft'],
  skill_ids: ['3'],
  model_override: 'zhipu/glm-4.5',
  temperature_override: 0.6,
  builtin: false,
  created_at: '2026-08-16T01:00:00Z',
  updated_at: '2026-08-16T01:00:00Z',
};

const TOOL_ITEMS: ToolSpec[] = [
  { name: 'save_draft', description: '保存章节草稿（agent 唯一写面）', group: 'writing', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'writing', op: 'write' },
  { name: 'search_characters', description: '搜索项目内角色档案', group: 'retrieval', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'character', op: 'read' },
  { name: 'check_foreshadowing', description: '列出未回收伏笔', group: 'retrieval', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'foreshadowing', op: 'read' },
  { name: 'get_prior_summary', description: '获取前文摘要', group: 'retrieval', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'writing', op: 'read' },
  { name: 'audit_chapter', description: '单章一致性审计', group: 'audit', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'writing', op: 'read' },
  { name: 'count_words', description: '中英文混合字数统计', group: 'audit', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'writing', op: 'read' },
];

const SKILL_ITEMS: SkillSummary[] = [
  { id: 1, name: 'outline-planning', description: '大纲规划方法论', source: 'builtin', agent_ids: [{ id: 1, name: '架构师' }] },
  { id: 3, name: 'web-research', description: '网络调研方法论', source: 'user_upload', agent_ids: [] },
];

/** 默认 mock：URL 分发（挂载 3 GET + 业务请求 + #485 duplicate 副本） */
function mockDefault() {
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/agents/1/duplicate' && init?.method === 'POST') {
      return { ...BUILTIN_AGENT, id: 10, name: '架构师 副本', builtin: false };
    }
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

describe('AgentList — 内置详情 + 复制（#485）', () => {
  it('内置卡片有详情+复制按钮；自定义卡片无（agent-detail-/agent-copy- 前缀仅 builtin）', async () => {
    render(<AgentList />);
    await screen.findByTestId('agent-card-1');
    const card1 = screen.getByTestId('agent-card-1');
    expect(within(card1).getByTestId('agent-detail-1')).toBeInTheDocument();
    expect(within(card1).getByTestId('agent-copy-1')).toBeInTheDocument();
    const card2 = screen.getByTestId('agent-card-2');
    expect(within(card2).queryByTestId('agent-detail-2')).not.toBeInTheDocument();
    expect(within(card2).queryByTestId('agent-copy-2')).not.toBeInTheDocument();
  });

  it('点详情 → 弹层：system_prompt 全文 + 工具列表 + skill 列表（零新请求）', async () => {
    const user = userEvent.setup();
    render(<AgentList />);
    await screen.findByTestId('agent-card-1');
    const fetchCountBefore = apiFetchMock.mock.calls.length;
    await user.click(screen.getByTestId('agent-detail-1'));
    const dlg = await screen.findByTestId('agent-detail-dialog');
    expect(dlg.getAttribute('role') === 'dialog' || dlg.getAttribute('aria-modal') === 'true').toBe(true);
    expect(screen.getByTestId('agent-detail-prompt').textContent).toContain(BUILTIN_AGENT.system_prompt);
    // #957 父侧迁移（⑨ 族：契约 §3 工具区块 = scope 矩阵，旧 agent-detail-tool-* chips 废止）
    expect(screen.getByTestId('agent-scope-detail')).toBeInTheDocument();
    expect(screen.getByTestId('agent-detail-resolved-count')).toBeInTheDocument();
    expect(screen.queryByTestId('agent-detail-tool-search_characters')).not.toBeInTheDocument();
    expect(screen.getByTestId('agent-detail-skill-1')).toBeInTheDocument();
    // 详情弹层零新请求（数据来自 store agents 本地渲染）——等挂载 GET 全部落定后再比对
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.length).toBe(fetchCountBefore);
    });
  });

  it('点详情后再点关闭按钮（agent-detail-close）→ 弹层消失', async () => {
    const user = userEvent.setup();
    render(<AgentList />);
    await screen.findByTestId('agent-card-1');
    await user.click(screen.getByTestId('agent-detail-1'));
    await screen.findByTestId('agent-detail-dialog');
    await user.click(screen.getByTestId('agent-detail-close'));
    await waitFor(() => {
      expect(screen.queryByTestId('agent-detail-dialog')).not.toBeInTheDocument();
    });
  });

  it('点复制 → POST /api/v1/agents/1/duplicate → toast「已复制」', async () => {
    const user = userEvent.setup();
    render(<AgentList />);
    await screen.findByTestId('agent-card-1');
    await user.click(screen.getByTestId('agent-copy-1'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/agents/1/duplicate',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.message.includes('已复制'))).toBe(true);
    });
  });

  it('复制失败 → 错误 toast（toast.saveFailed）', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/agents/1/duplicate' && init?.method === 'POST') {
        throw new Error('duplicate failed');
      }
      if (path === '/api/v1/agents') return { items: [BUILTIN_AGENT, CUSTOM_AGENT], total: 2 };
      if (path === '/api/v1/agents/tools') return { items: TOOL_ITEMS };
      if (path === '/api/v1/skills') return { items: SKILL_ITEMS, total: 2 };
      return { ok: true };
    });
    render(<AgentList />);
    await screen.findByTestId('agent-card-1');
    await user.click(screen.getByTestId('agent-copy-1'));
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.message.includes('保存失败'))).toBe(true);
    });
  });
});

describe('AgentList — scope 详情矩阵（#957 F58，【R】）', () => {
  /** RESOLVED 源 vs tool_ids 源分歧 fixture：证明卡片 chips 数据源 = resolved_tool_names（非 tool_ids） */
  const SCOPE_AGENT: AgentEntity = {
    ...BUILTIN_AGENT,
    id: 5,
    name: 'scope-agent',
    tool_ids: ['legacy_deprecated_tool'],
    grants: [{ domain: 'character', ops: ['read'] }],
    resolved_tool_names: ['search_characters'],
  };

  function mockScope(agents: AgentEntity[]) {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/agents') return { items: agents, total: agents.length };
      if (path === '/api/v1/agents/tools') return { items: TOOL_ITEMS };
      if (path === '/api/v1/skills') return { items: SKILL_ITEMS, total: 2 };
      return { ok: true };
    });
  }

  it('卡片工具 chips 数据源 = resolved_tool_names（tool_ids 已被后端分辨率替代）', async () => {
    mockScope([SCOPE_AGENT]);
    render(<AgentList />);
    await screen.findByTestId('agent-card-5');
    // tool_ids=['legacy_deprecated_tool'] 但 resolved=['search_characters'] → chips 显示 resolved 名
    expect(screen.getByTestId('agent-tool-chip-search_characters')).toBeInTheDocument();
    expect(screen.queryByTestId('agent-tool-chip-legacy_deprecated_tool')).not.toBeInTheDocument();
  });

  it('详情弹窗只读矩阵回显：character-read checked + resolved 计数 + 默认折叠 + 展开显工具行', async () => {
    const user = userEvent.setup();
    mockScope([SCOPE_AGENT]);
    render(<AgentList />);
    await screen.findByTestId('agent-card-5');
    await user.click(screen.getByTestId('agent-detail-5'));
    await screen.findByTestId('agent-detail-dialog');
    const matrix = screen.getByTestId('agent-scope-detail');
    // 8 域 × 3 列全渲染；character-read 有授权 → checked
    expect(within(matrix).getByTestId('agent-detail-scope-character-read').getAttribute('data-checked')).toBe('true');
    expect(within(matrix).getByTestId('agent-detail-scope-character-write').getAttribute('data-checked')).toBe('false');
    // resolved 计数可见（resolved 数 = 1）
    expect(screen.getByTestId('agent-detail-resolved-count')).toHaveTextContent('1');
    // 默认折叠：工具清单行不渲染
    expect(screen.queryByTestId('agent-detail-resolved-tool-search_characters')).not.toBeInTheDocument();
    // 展开开关 → 每工具一行
    await user.click(screen.getByTestId('agent-detail-resolved-toggle'));
    expect(screen.getByTestId('agent-detail-resolved-tool-search_characters')).toBeInTheDocument();
  });

  it('grants 全空 → agent-scope-empty + resolved 计数 0 仍渲染', async () => {
    const user = userEvent.setup();
    const EMPTY_AGENT: AgentEntity = {
      ...BUILTIN_AGENT,
      id: 6,
      name: 'empty-scope',
      tool_ids: [],
      grants: [],
      resolved_tool_names: [],
    };
    mockScope([EMPTY_AGENT]);
    render(<AgentList />);
    await screen.findByTestId('agent-card-6');
    await user.click(screen.getByTestId('agent-detail-6'));
    await screen.findByTestId('agent-detail-dialog');
    expect(screen.getByTestId('agent-scope-empty')).toBeInTheDocument();
    // resolved 计数区块仍渲染 0
    expect(screen.getByTestId('agent-detail-resolved-count')).toHaveTextContent('0');
  });
});
