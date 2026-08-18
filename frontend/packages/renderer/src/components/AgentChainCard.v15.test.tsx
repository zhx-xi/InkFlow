/**
 * ⚠️ 契约文件（v1.5 #484 链动态化：添加角色 + 角色池 + 自定义 Agent 进链，spec §5.7.2/§5.7.3/§5.7.4）
 *
 * 拆分自 AgentChainCard.test.tsx（900 行护栏，2026-08-19 #484）——本文件仅含 v1.5
 * 新增契约；既有 F42/#269/#296/#473/F46 契约见 AgentChainCard.test.tsx（兄弟文件，
 * mock 数据源与本文件同构：BUILTIN_AGENTS 6 内置含 worldview/polisher role_key）。
 *
 * GREEN 修改 src/components/AgentChainCard.tsx，必须匹配：
 *
 * 行渲染规则（v1.5，spec §5.7.1「默认不在链中」+ §5.7.3「添加角色」）：
 * - 默认模板模式（agent_order 空）：渲染内置 4 链角色行（architect/writer/auditor/reviser，
 *   数据源 = agents 按 role_key 派生，既有）+ 模板 roles 非内置键行（兼容既有，§5.7.2 注）
 * - 配置驱动模式（agent_order 非空）：渲染 order 中角色行（含新添加的 worldview/polisher/自定义）
 * - 世界观顾问/润色师/自定义 Agent 默认不在链中 → 不渲染行，出现在角色池（可「添加角色」进链）
 *
 * 添加角色（§5.7.3）：
 * - 按钮 data-testid="agent-chain-add-role"（卡片角色行列表之后、依赖编辑器之前）
 * - 点击 → 角色池选择器：选项 data-testid="agent-chain-role-option-<field>"
 *   （field = agent_<role_key>，如 agent_worldview），文案 = 角色名（agents 真源）
 * - 角色池 = 可进链角色（6 内置 role_key 非 null + 自定义 agents + 模板 roles 非内置键）
 *   − 已在链中的角色（不重复显示）
 * - 选角色 → ① 写入三态字段 = AGENT_DEFAULT_SENTINEL（跟随默认）：
 *   内置 → config.agent_<role_key>；自定义 → config.agent_roles[agent_<role_key>]
 *   ② agent_order 显式化：默认 4 层 + 新角色追加到末尾层（配置驱动模式显式化，B1 语义）
 *   ③ onConfigChange() 调用（即改即存链路）
 *
 * 删除角色（§5.7.3「关闭 = 移除」）：
 * - 新添加角色行关闭（switch off）→ agent_* = null + 从 agent_order 剔除（空层压缩）
 *   + 非默认角色行消失（角色回到池可重新添加）
 *
 * 新角色行交互 = 既有 M6 契约（槽位号 agent-order-slot-<field> / 上移下移 /
 * 模型 Select agent-model-select-<field>，§5.7.3「新增角色同样支持」）；添加即写
 * sentinel → Switch ON → Select 已渲染（无需再点开关，点击为关闭语义）。
 *
 * 自定义 Agent 进链（§5.7.2/§5.7.4）：Agent 管理创建（builtin=false，role_key 由
 * 服务层分配）→ 角色池出现（field=agent_<role_key>）→ 添加 → 三态走 agent_roles +
 * order 末尾层；行显示名 = agents 真源 name。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentChainCard } from './AgentChainCard';
import { AGENT_DEFAULT_SENTINEL, type ProjectConfig } from '../stores/project';
import { useAgentStore } from '../stores/agent';
import { useAgentsStore } from '../stores/agents';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useTemplatesStore } from '../stores/templates';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** v1.5 #484：ProjectConfig 新增 agent_worldview/agent_polisher 三态字段（GREEN 补 stores/project.ts 类型） */
type V15Config = ProjectConfig & {
  agent_worldview?: string | null;
  agent_polisher?: string | null;
};

/** #473 R1 / v1.5 #484：后端 BUILTIN_AGENT_SPECS 6 内置镜像（role_key 派生真源的 mock 数据源） */
const BUILTIN_AGENTS = [
  { id: 101, name: '架构师', description: '章节结构/大纲规划', icon: '🏗️', system_prompt: '你是架构师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'architect', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 102, name: '写手', description: '正文生成', icon: '✍️', system_prompt: '你是写手。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'writer', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 103, name: '审校员', description: '一致性审计', icon: '🔍', system_prompt: '你是审校员。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'auditor', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 104, name: '修订师', description: '修订打磨', icon: '🛠️', system_prompt: '你是修订师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'reviser', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 105, name: '世界观顾问', description: '世界观一致', icon: '🌍', system_prompt: '你是世界观顾问。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'worldview', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 106, name: '润色师', description: '文笔润色', icon: '✨', system_prompt: '你是润色师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'polisher', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
] as const;

/** provider-configs mock：openai(gpt-4o chat + embedding) / zhipu(glm-4.5 chat) / ollama(qwen3 chat) */
const PROVIDERS: ProviderConfig[] = [
  {
    id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
    models: [
      { id: 'gpt-4o', type: 'chat', roles: ['main'] },
      { id: 'text-embedding-3-small', type: 'embedding', roles: ['rag'] },
    ],
    key_saved: true, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
  {
    id: 2, name: 'zhipu', base_url: 'https://open.bigmodel.cn/api/paas/v4', default_model: 'glm-4.5',
    models: [{ id: 'glm-4.5', type: 'chat', roles: [] }],
    key_saved: false, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
  {
    id: 3, name: 'ollama', base_url: 'http://127.0.0.1:11434', default_model: 'qwen3',
    models: [{ id: 'qwen3', type: 'chat', roles: [] }],
    key_saved: false, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: PROVIDERS, total: 3, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/agent-templates') {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/agents') {
      return { items: BUILTIN_AGENTS, total: 6, offset: 0, limit: 50 };
    }
    return { ok: true };
  });
  useAgentStore.setState({ config: {}, apiKeyDraft: '', testStatus: 'idle', testMessage: null });
  useAgentsStore.setState({ agents: [], tools: [], skills: [], loading: false, error: null });
  useModelsStore.setState({
    providers: [],
    loading: false,
    error: null,
    selectedModelId: null,
    roleBinding: { main: '', architect: '', writer: '', auditor: '', reviser: '', embedding: '' },
  });
  useTemplatesStore.setState({ templates: [], loading: false, error: null, defaultTemplateId: null });
});

async function renderCard() {
  const onConfigChange = vi.fn();
  render(<AgentChainCard onConfigChange={onConfigChange} />);
  await waitFor(() => {
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/provider-configs');
  });
  return onConfigChange;
}

describe('AgentChainCard — v1.5 #484 添加角色 + 角色池（spec §5.7.2/§5.7.3）', () => {
  const V15_DEFAULT_ORDER = [
    ['agent_architect'],
    ['agent_writer'],
    ['agent_auditor'],
    ['agent_reviser'],
  ];

  it('默认模式：4 内置行 + 添加角色按钮存在；worldview/polisher 不在行中', async () => {
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('架构师');
    // 默认链 4 角色行
    expect(within(card).getAllByRole('switch')).toHaveLength(4);
    // 世界观顾问/润色师默认不在链中（不渲染行）
    expect(within(card).queryByText('世界观顾问')).not.toBeInTheDocument();
    expect(within(card).queryByText('润色师')).not.toBeInTheDocument();
    // 添加角色按钮
    expect(within(card).getByTestId('agent-chain-add-role')).toBeInTheDocument();
  });

  it('点添加 → 角色池显示未在链中角色（worldview/polisher 选项，testid 契约）', async () => {
    const user = userEvent.setup();
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('架构师');

    await user.click(within(card).getByTestId('agent-chain-add-role'));

    // 角色池选项：agent_worldview / agent_polisher（未在链中）
    expect(screen.getByTestId('agent-chain-role-option-agent_worldview')).toBeInTheDocument();
    expect(screen.getByTestId('agent-chain-role-option-agent_polisher')).toBeInTheDocument();
    // 已在链中的 4 角色不重复出现
    expect(screen.queryByTestId('agent-chain-role-option-agent_architect')).not.toBeInTheDocument();
  });

  it('添加世界观顾问 → 行出现 + agent_worldview=sentinel + agent_order 显式化（末尾层）', async () => {
    const user = userEvent.setup();
    const onConfigChange = await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('架构师');

    await user.click(within(card).getByTestId('agent-chain-add-role'));
    await user.click(screen.getByTestId('agent-chain-role-option-agent_worldview'));

    // 行出现（switch 名 = agents 真源显示名）
    expect(await within(card).findByText('世界观顾问')).toBeInTheDocument();
    expect(within(card).getAllByRole('switch')).toHaveLength(5);
    // 三态字段 = sentinel（跟随默认）
    expect((useAgentStore.getState().config as V15Config).agent_worldview).toBe(AGENT_DEFAULT_SENTINEL);
    // agent_order 显式化：默认 4 层 + worldview 末尾层
    expect(useAgentStore.getState().config.agent_order).toEqual([
      ...V15_DEFAULT_ORDER,
      ['agent_worldview'],
    ]);
    expect(onConfigChange).toHaveBeenCalled();
  });

  it('添加润色师 → 行出现 + agent_polisher=sentinel + order 追加末尾（新角色同等待遇）', async () => {
    const user = userEvent.setup();
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('架构师');

    await user.click(within(card).getByTestId('agent-chain-add-role'));
    await user.click(screen.getByTestId('agent-chain-role-option-agent_polisher'));

    expect(await within(card).findByText('润色师')).toBeInTheDocument();
    expect((useAgentStore.getState().config as V15Config).agent_polisher).toBe(AGENT_DEFAULT_SENTINEL);
    expect(useAgentStore.getState().config.agent_order).toEqual([
      ...V15_DEFAULT_ORDER,
      ['agent_polisher'],
    ]);
  });

  it('新角色行支持既有 M6 交互：槽位号 + 模型 Select（§5.7.3「新增角色同样支持」）', async () => {
    const user = userEvent.setup();
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('架构师');

    await user.click(within(card).getByTestId('agent-chain-add-role'));
    await user.click(screen.getByTestId('agent-chain-role-option-agent_worldview'));
    await within(card).findByText('世界观顾问');

    // 槽位号 = 4（末尾层）
    expect(screen.getByTestId('agent-order-slot-agent_worldview')).toHaveTextContent('4');
    // 添加即写 sentinel（三态 1）→ Switch 已 ON → 模型 Select 已渲染（无需再点开关，
    // 点击会变成关闭语义；既有三态契约由 v1.5-3「添加 → sentinel」保证）
    expect(await screen.findByTestId('agent-model-select-agent_worldview')).toBeInTheDocument();
    // 下拉含「跟随默认」+ chat 模型选项
    await user.click(screen.getByTestId('agent-model-select-agent_worldview'));
    expect(screen.getByRole('option', { name: '跟随默认' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'zhipu/glm-4.5' })).toBeInTheDocument();
  });

  it('关闭新添加角色（配置驱动模式）→ null + order 剔除 + 行消失（角色回池）', async () => {
    const user = userEvent.setup();
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('架构师');

    await user.click(within(card).getByTestId('agent-chain-add-role'));
    await user.click(screen.getByTestId('agent-chain-role-option-agent_worldview'));
    await within(card).findByText('世界观顾问');

    // 关闭 worldview（行 switch）
    const switches = within(card).getAllByRole('switch');
    const worldviewSwitch = switches.find((s) => s.getAttribute('aria-label') === '世界观顾问');
    await user.click(worldviewSwitch!);

    expect((useAgentStore.getState().config as V15Config).agent_worldview).toBeNull();
    // order 剔除 + 空层压缩 → 回默认 4 层
    expect(useAgentStore.getState().config.agent_order).toEqual(V15_DEFAULT_ORDER);
    // 非默认角色行消失（回到角色池）
    expect(within(card).queryByText('世界观顾问')).not.toBeInTheDocument();
  });

  it('已在链中的角色不重复出现在角色池（添加后池选项消失）', async () => {
    const user = userEvent.setup();
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('架构师');

    await user.click(within(card).getByTestId('agent-chain-add-role'));
    await user.click(screen.getByTestId('agent-chain-role-option-agent_worldview'));
    await within(card).findByText('世界观顾问');

    // 再开池：worldview 已在链中 → 不显示；polisher 仍显示
    await user.click(within(card).getByTestId('agent-chain-add-role'));
    expect(screen.queryByTestId('agent-chain-role-option-agent_worldview')).not.toBeInTheDocument();
    expect(screen.getByTestId('agent-chain-role-option-agent_polisher')).toBeInTheDocument();
  });
});

describe('AgentChainCard — v1.5 #484 自定义 Agent 进链（spec §5.7.2/§5.7.4）', () => {
  /**
   * 契约：Agent 管理创建的自定义 Agent（builtin=false，role_key 由服务层分配）→
   * 角色池出现（§5.7.2「角色池 = Agent 管理全量」）→ 添加进链 →
   * 三态字段走 config.agent_roles（key = agent_<role_key>，既有 #296 语义）+
   * agent_order 末尾层；行显示名 = agents 真源 name。
   */
  const CUSTOM_AGENTS = [
    ...BUILTIN_AGENTS,
    {
      id: 201, name: '研究员', description: '设定核查', icon: '🔬',
      system_prompt: '你是研究员，负责核查章节设定一致性。', tool_ids: [], skill_ids: [],
      model_override: null, temperature_override: null, builtin: false, role_key: 'researcher',
      created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z',
    },
  ];

  function mockAgentsWithCustom() {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') {
        return { items: PROVIDERS, total: 3, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/agent-templates') {
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/agents') {
        return { items: CUSTOM_AGENTS, total: 7, offset: 0, limit: 50 };
      }
      return { ok: true };
    });
  }

  it('自定义 Agent 出现在角色池（builtin=false 分组，field=agent_researcher）', async () => {
    const user = userEvent.setup();
    mockAgentsWithCustom();
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('架构师');

    await user.click(within(card).getByTestId('agent-chain-add-role'));
    expect(screen.getByTestId('agent-chain-role-option-agent_researcher')).toBeInTheDocument();
  });

  it('添加自定义 Agent → 行出现（真源 name）+ agent_roles sentinel + order 追加末尾', async () => {
    const user = userEvent.setup();
    mockAgentsWithCustom();
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('架构师');

    await user.click(within(card).getByTestId('agent-chain-add-role'));
    await user.click(screen.getByTestId('agent-chain-role-option-agent_researcher'));

    expect(await within(card).findByText('研究员')).toBeInTheDocument();
    expect(useAgentStore.getState().config.agent_roles).toEqual({
      agent_researcher: AGENT_DEFAULT_SENTINEL,
    });
    expect(useAgentStore.getState().config.agent_order).toEqual([
      ['agent_architect'],
      ['agent_writer'],
      ['agent_auditor'],
      ['agent_reviser'],
      ['agent_researcher'],
    ]);
  });

  it('自定义 Agent 行开关/模型 Select 走 agent_roles（#296 既有三态语义对新角色生效）', async () => {
    const user = userEvent.setup();
    mockAgentsWithCustom();
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('架构师');

    await user.click(within(card).getByTestId('agent-chain-add-role'));
    await user.click(screen.getByTestId('agent-chain-role-option-agent_researcher'));
    await within(card).findByText('研究员');

    // 打开 → sentinel（添加时已写）；选具体模型 → agent_roles provider/model
    await user.click(screen.getByTestId('agent-model-select-agent_researcher'));
    await user.click(await screen.findByRole('option', { name: 'zhipu/glm-4.5' }));
    expect(useAgentStore.getState().config.agent_roles).toEqual({
      agent_researcher: 'zhipu/glm-4.5',
    });
  });
});
