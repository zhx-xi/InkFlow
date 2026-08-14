/**
 * ⚠️ 契约文件（Issue #268 F42 模型选择，spec §5.2 + §2.2 三态语义；2026-08-12）
 *
 * GREEN 修改 src/components/AgentChainCard.tsx，必须匹配：
 *
 * 结构（data-testid 即契约，保留既有）：
 * - agent-chain-card：卡片根容器（既有，不改）
 * - 每行 Switch：role=switch，aria-label=t(role.nameKey)（既有，不改）
 * - 每行模型 Select（Switch 打开时条件渲染）：data-testid=`agent-model-select-<field>`
 *   （如 agent-model-select-agent_architect），Radix combobox；关闭时不渲染
 * - 既有 tag 展示位（L70 span）承担三种状态：
 *   * 未注册模型（config 值不在选项列表）→ 文本 t('ag.unregisteredModel')（警告样式）
 *   * 格式不合规（config 值无 /，裸名）→ 文本 t('ag.modelFormatFix')（警告样式）
 *   * 正常 → 现有逻辑不变（ag.disabled / ag.defaultModel / 模型名）
 *
 * 数据源（spec §5.2 Q3）：
 * - GET /api/v1/provider-configs → items[].models[type=chat].id，扁平为 <provider>/<model>
 *   （provider 名取 items[].name），经 stores/models.ts selectChatModelOptions 计算
 * - 「跟随默认」选项固定置顶，值 = AGENT_DEFAULT_SENTINEL（'__default__'）
 * - 组件挂载时调 loadProviders()（useModelsStore），Select 选项随 store 更新
 *
 * 三态交互映射（spec §2.2 表）：
 * - Switch off → PATCH null（setConfig({field: null}) + onConfigChange）
 * - Switch on → 默认「跟随默认」→ PATCH '__default__'；Select 选具体模型 →
 *   PATCH '<provider>/<model>'（如 'zhipu/glm-4.5'）
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts）：
 * - ag.followDefault='跟随默认' / 'Follow default'（Select 置顶选项文案）
 * - ag.unregisteredModel='未注册模型' / 'Unregistered model'
 * - ag.modelFormatFix='格式需修正（应为 provider/model）' / 'Format needs fix (provider/model)'
 *
 * RED 预期：AgentChainCard 现无 Select（L59 打开恒写 sentinel）→ 新用例全部
 * element-missing / 断言型 FAIL；既有行为（开关写 sentinel/null）保持绿。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentChainCard } from './AgentChainCard';
import { AGENT_DEFAULT_SENTINEL } from '../stores/project';
import { useAgentStore } from '../stores/agent';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useTemplatesStore, type AgentTemplate } from '../stores/templates';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

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
    return { ok: true };
  });
  useAgentStore.setState({ config: {}, apiKeyDraft: '', testStatus: 'idle', testMessage: null });
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
  // 挂载 → loadProviders() → Select 选项就绪（RED 阶段无 Select 查询将超时）
  await waitFor(() => {
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/provider-configs');
  });
  return onConfigChange;
}

describe('AgentChainCard — F42 模型选择（spec §5.2）', () => {
  it('四行渲染保留：Architect/Writer/Auditor/Reviser + 4 开关（既有契约）', async () => {
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    expect(within(card).getByText('Architect 大纲架构师')).toBeInTheDocument();
    expect(within(card).getByText('Writer 执笔')).toBeInTheDocument();
    expect(within(card).getByText('Auditor 审校')).toBeInTheDocument();
    expect(within(card).getByText('Reviser 修订')).toBeInTheDocument();
    expect(within(card).getAllByRole('switch')).toHaveLength(4);
  });

  it('初始全关：无任何模型 Select 渲染（queryByTestId 均不存在）', async () => {
    await renderCard();
    for (const field of ['agent_architect', 'agent_writer', 'agent_auditor', 'agent_reviser']) {
      expect(screen.queryByTestId(`agent-model-select-${field}`)).not.toBeInTheDocument();
    }
  });

  it('打开 Architect → Select 出现；「跟随默认」置顶 + provider/model 选项（chat 扁平）', async () => {
    const user = userEvent.setup();
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    await user.click(switches[0]);
    const select = await screen.findByTestId('agent-model-select-agent_architect');
    expect(select).toBeInTheDocument();

    // 打开 Select → 选项：跟随默认（置顶，值 sentinel）+ openai/gpt-4o + zhipu/glm-4.5 + ollama/qwen3
    await user.click(select);
    const options = await screen.findAllByRole('option');
    expect(options[0]).toHaveTextContent('跟随默认');
    expect(screen.getByRole('option', { name: 'openai/gpt-4o' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'zhipu/glm-4.5' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'ollama/qwen3' })).toBeInTheDocument();
    // embedding 模型不得出现（chat 过滤契约）
    expect(screen.queryByRole('option', { name: 'openai/text-embedding-3-small' })).not.toBeInTheDocument();
  });

  it('打开默认「跟随默认」→ setConfig sentinel + onConfigChange 调用（三态映射 1）', async () => {
    const user = userEvent.setup();
    const onConfigChange = await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    await user.click(switches[0]);
    await screen.findByTestId('agent-model-select-agent_architect');

    expect(useAgentStore.getState().config.agent_architect).toBe(AGENT_DEFAULT_SENTINEL);
    expect(onConfigChange).toHaveBeenCalled();
  });

  it('选具体模型 zhipu/glm-4.5 → setConfig provider/model + onConfigChange（三态映射 2）', async () => {
    const user = userEvent.setup();
    const onConfigChange = await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    await user.click(switches[1]); // Writer 打开
    const select = await screen.findByTestId('agent-model-select-agent_writer');
    await user.click(select);
    await user.click(await screen.findByRole('option', { name: 'zhipu/glm-4.5' }));

    expect(useAgentStore.getState().config.agent_writer).toBe('zhipu/glm-4.5');
    expect(onConfigChange).toHaveBeenCalled();
  });

  it('关闭 → setConfig null + Select 消失（三态映射 3）', async () => {
    const user = userEvent.setup();
    const onConfigChange = await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    // 先打开（Select 出现）
    await user.click(switches[0]);
    await screen.findByTestId('agent-model-select-agent_architect');

    // 再关闭 → null + Select 不渲染
    await user.click(switches[0]);
    expect(useAgentStore.getState().config.agent_architect).toBeNull();
    expect(onConfigChange).toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByTestId('agent-model-select-agent_architect')).not.toBeInTheDocument();
    });
  });

  it('回读：config.agent_writer 已有具体模型 → 开关 on + Select 回显该值', async () => {
    act(() => {
      useAgentStore.getState().setConfig({ agent_writer: 'zhipu/glm-4.5' });
    });
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    expect(within(card).getAllByRole('switch')[1]).toBeChecked();
    expect(screen.getByTestId('agent-model-select-agent_writer')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('agent-model-select-agent_writer')).toHaveTextContent('zhipu/glm-4.5');
    });
  });

  it('未注册模型标记：config 值不在选项列表 → tag 显示「未注册模型」警告（保存不阻塞）', async () => {
    act(() => {
      useAgentStore.getState().setConfig({ agent_writer: 'vanished/gpt-9' });
    });
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    // 开关仍 on（字符串值），tag 显示未注册警告
    expect(within(card).getAllByRole('switch')[1]).toBeChecked();
    expect(within(card).getByText('未注册模型')).toBeInTheDocument();
  });

  it('格式不合规标记：config 值无 /（裸名）→ tag 显示「格式需修正（应为 provider/model）」', async () => {
    act(() => {
      useAgentStore.getState().setConfig({ agent_architect: 'gpt-4o' });
    });
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    expect(within(card).getAllByRole('switch')[0]).toBeChecked();
    expect(within(card).getByText('格式需修正（应为 provider/model）')).toBeInTheDocument();
  });
});

describe('AgentChainCard — F42 #269 执行顺序编辑（spec §5.3/M6）', () => {
  /** 默认拓扑常量（与后端默认模板槽位一致：architect=0/writer=1/auditor=2/reviser=3） */
  const DEFAULT_ORDER = [
    ['agent_architect'],
    ['agent_writer'],
    ['agent_auditor'],
    ['agent_reviser'],
  ];

  function slotOf(field: string): HTMLElement {
    return screen.getByTestId(`agent-order-slot-${field}`);
  }

  function moveUp(field: string): HTMLElement {
    return screen.getByTestId(`agent-order-move-up-${field}`);
  }

  function moveDown(field: string): HTMLElement {
    return screen.getByTestId(`agent-order-move-down-${field}`);
  }

  it('空 agent_order（默认模板模式）→ 显示默认拓扑槽位 0-3', async () => {
    await renderCard();
    expect(slotOf('agent_architect')).toHaveTextContent('0');
    expect(slotOf('agent_writer')).toHaveTextContent('1');
    expect(slotOf('agent_auditor')).toHaveTextContent('2');
    expect(slotOf('agent_reviser')).toHaveTextContent('3');
  });

  it('每行上移/下移按钮：首行上移禁用、末行下移禁用（边界）', async () => {
    await renderCard();
    expect(moveUp('agent_architect')).toBeDisabled();
    expect(moveDown('agent_reviser')).toBeDisabled();
    expect(moveUp('agent_writer')).toBeEnabled();
    expect(moveDown('agent_writer')).toBeEnabled();
  });

  it('回读：config.agent_order 非空 → 槽位号按配置显示（writer=0/architect=1）', async () => {
    act(() => {
      useAgentStore.getState().setConfig({
        agent_order: [['agent_writer'], ['agent_architect']],
        agent_writer: 'openai/gpt-4o',
        agent_architect: 'openai/gpt-4o',
      });
    });
    await renderCard();
    expect(slotOf('agent_writer')).toHaveTextContent('0');
    expect(slotOf('agent_architect')).toHaveTextContent('1');
  });

  it('#347: 移动时自动启用被移动角色（防后端 C1 422「配置驱动模式至少需要 1 个启用角色」）', async () => {
    const user = userEvent.setup();
    const onConfigChange = await renderCard();
    // 初始全 null（默认模板模式）——移动 Writer 上移
    await user.click(moveUp('agent_writer'));

    const config = useAgentStore.getState().config;
    // agent_order 显式化（既有语义）
    expect(config.agent_order).toEqual([
      ['agent_architect', 'agent_writer'],
      ['agent_auditor'],
      ['agent_reviser'],
    ]);
    // #347：被移动角色自动启用（sentinel 跟随默认）→ 后端 C1 校验恒过
    expect(config.agent_writer).toBe(AGENT_DEFAULT_SENTINEL);
    expect(onConfigChange).toHaveBeenCalled();
  });

  it('#347: 零启用角色时移动内置角色 → 被移动角色自动启用（不再产生 422 配置）', async () => {
    const user = userEvent.setup();
    await renderCard();
    // 全 null 默认模式，移动 Auditor 下移
    await user.click(moveDown('agent_auditor'));
    const config = useAgentStore.getState().config;
    expect(config.agent_auditor).toBe(AGENT_DEFAULT_SENTINEL);
    // 至少一个启用角色 → C1 恒过
    const enabled = Object.entries(config).filter(
      ([k, v]) => k.startsWith('agent_') && v != null && v !== '',
    );
    expect(enabled.length).toBeGreaterThan(0);
  });

  it('点击 Writer 上移（空 agent_order）→ agent_order 显式化默认拓扑并移动（并入上一层 = 并行组）', async () => {
    const user = userEvent.setup();
    const onConfigChange = await renderCard();

    await user.click(moveUp('agent_writer'));

    expect(useAgentStore.getState().config.agent_order).toEqual([
      ['agent_architect', 'agent_writer'],
      ['agent_auditor'],
      ['agent_reviser'],
    ]);
    expect(onConfigChange).toHaveBeenCalled();
  });

  it('点击 Writer 下移（默认拓扑）→ 并入下一层（auditor 层 = 并行组）', async () => {
    const user = userEvent.setup();
    const onConfigChange = await renderCard();

    await user.click(moveDown('agent_writer'));

    expect(useAgentStore.getState().config.agent_order).toEqual([
      ['agent_architect'],
      ['agent_auditor', 'agent_writer'],
      ['agent_reviser'],
    ]);
    expect(onConfigChange).toHaveBeenCalled();
  });

  it('点击 Auditor 上移（默认拓扑）→ 并入 writer 层 → PATCH 结构为并行组', async () => {
    const user = userEvent.setup();
    await renderCard();

    await user.click(moveUp('agent_auditor'));

    expect(useAgentStore.getState().config.agent_order).toEqual([
      ['agent_architect'],
      ['agent_writer', 'agent_auditor'],
      ['agent_reviser'],
    ]);
  });

  it('关闭角色（配置驱动模式）→ agent_order 剔除该角色（B1：关闭动作 = null + order 移除）', async () => {
    const user = userEvent.setup();
    act(() => {
      useAgentStore.getState().setConfig({
        agent_order: DEFAULT_ORDER,
        agent_writer: 'openai/gpt-4o',
      });
    });
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    // Writer 行 = 索引 1（Architect/Writer/Auditor/Reviser 固定顺序）
    await user.click(switches[1]);

    expect(useAgentStore.getState().config.agent_writer).toBeNull();
    // 剔除后空层压缩：[[architect],[auditor],[reviser]]
    expect(useAgentStore.getState().config.agent_order).toEqual([
      ['agent_architect'],
      ['agent_auditor'],
      ['agent_reviser'],
    ]);
  });

  it('开启角色（配置驱动模式）→ agent_order 加入默认槽位（writer→1）', async () => {
    const user = userEvent.setup();
    act(() => {
      useAgentStore.getState().setConfig({
        agent_order: [['agent_architect'], ['agent_auditor'], ['agent_reviser']],
      });
    });
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    await user.click(switches[1]); // Writer 开启

    expect(useAgentStore.getState().config.agent_writer).toBe(AGENT_DEFAULT_SENTINEL);
    expect(useAgentStore.getState().config.agent_order).toEqual(DEFAULT_ORDER);
  });

  it('默认模式（agent_order 空）开关动作不写入 agent_order（B1：保持默认模板模式）', async () => {
    const user = userEvent.setup();
    const onConfigChange = await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    await user.click(switches[0]); // Architect 开启

    expect(useAgentStore.getState().config.agent_architect).toBe(AGENT_DEFAULT_SENTINEL);
    // agent_order 保持未配置（undefined/缺省）→ 后端默认模板模式
    expect(useAgentStore.getState().config.agent_order).toBeUndefined();
    expect(onConfigChange).toHaveBeenCalled();
  });
});

describe('AgentChainCard — F42 #296 自定义角色行（spec §5.3.4）', () => {
  /** 含自定义角色的模板：researcher（带 name）+ editor（无 name，回退裸名） */
  const TEMPLATE_WITH_CUSTOM = {
    id: 2,
    name: '悬疑推理模板',
    description: '',
    main_model: 'openai/gpt-4o',
    default_temperature: 0.7,
    roles: {
      architect: { model: null, temperature: null, enabled: true },
      writer: { model: null, temperature: null, enabled: true },
      auditor: { model: null, temperature: null, enabled: true },
      reviser: { model: null, temperature: null, enabled: true },
      researcher: { model: null, temperature: null, enabled: true, name: '资料研究员', prompt: '你负责搜集资料' },
      editor: { model: null, temperature: null, enabled: true, name: null, prompt: '你负责润色' },
    },
    default_words: 800000,
    is_default: false,
    used_by: [],
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  } as unknown as AgentTemplate;

  /** 覆盖默认 mock：agent-templates 返回含自定义角色的模板（config.template_id=2 匹配） */
  function mockTemplatesWithCustom() {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') {
        return { items: PROVIDERS, total: 3, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/agent-templates') {
        return { items: [TEMPLATE_WITH_CUSTOM], total: 1, offset: 0, limit: 50 };
      }
      return { ok: true };
    });
  }

  it('R1 自定义角色行渲染：模板 roles 非四键 → researcher/editor 行（显示名 = name 或裸名）', async () => {
    mockTemplatesWithCustom();
    act(() => useAgentStore.getState().setConfig({ template_id: 2 }));
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    expect(await within(card).findByText('资料研究员')).toBeInTheDocument();
    expect(within(card).getByText('editor')).toBeInTheDocument();
    // 4 内置 + 2 自定义 = 6 开关
    expect(within(card).getAllByRole('switch')).toHaveLength(6);
  });

  it('R2 无模板引用（template_id 缺失）→ 无自定义角色行（只内置 4）', async () => {
    mockTemplatesWithCustom();
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    // 模板已加载但 config 无 template_id → 不渲染自定义角色行
    expect(within(card).getAllByRole('switch')).toHaveLength(4);
    expect(within(card).queryByText('资料研究员')).not.toBeInTheDocument();
  });

  it('R3 自定义开关开 → agent_roles sentinel（三态映射 1）', async () => {
    const user = userEvent.setup();
    mockTemplatesWithCustom();
    act(() => useAgentStore.getState().setConfig({ template_id: 2 }));
    const onConfigChange = await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('资料研究员');
    const switches = within(card).getAllByRole('switch');
    await user.click(switches[4]); // researcher = 内置 4 之后第 1 个
    expect(useAgentStore.getState().config.agent_roles).toEqual({ agent_researcher: AGENT_DEFAULT_SENTINEL });
    expect(onConfigChange).toHaveBeenCalled();
  });

  it('R4 自定义 Select 选模型 → agent_roles provider/model（三态映射 2）', async () => {
    const user = userEvent.setup();
    mockTemplatesWithCustom();
    act(() => useAgentStore.getState().setConfig({ template_id: 2 }));
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('资料研究员');
    await user.click(within(card).getAllByRole('switch')[4]); // 开启 researcher
    const select = await screen.findByTestId('agent-model-select-agent_researcher');
    await user.click(select);
    await user.click(await screen.findByRole('option', { name: 'zhipu/glm-4.5' }));
    expect(useAgentStore.getState().config.agent_roles).toEqual({ agent_researcher: 'zhipu/glm-4.5' });
  });

  it('R5 自定义关 → agent_roles null（三态映射 3）', async () => {
    const user = userEvent.setup();
    mockTemplatesWithCustom();
    act(() =>
      useAgentStore.getState().setConfig({
        template_id: 2,
        agent_roles: { agent_researcher: AGENT_DEFAULT_SENTINEL },
      }),
    );
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('资料研究员');
    await user.click(within(card).getAllByRole('switch')[4]); // 关闭 researcher
    expect(useAgentStore.getState().config.agent_roles).toEqual({ agent_researcher: null });
  });

  it('R6 自定义角色默认槽位号（4/5 按模板 roles 顺序）', async () => {
    mockTemplatesWithCustom();
    act(() => useAgentStore.getState().setConfig({ template_id: 2 }));
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('资料研究员');
    expect(screen.getByTestId('agent-order-slot-agent_researcher')).toHaveTextContent('4');
    expect(screen.getByTestId('agent-order-slot-agent_editor')).toHaveTextContent('5');
  });

  it('R7 回读 agent_order 含自定义角色 → 槽位按配置显示（researcher=0）', async () => {
    mockTemplatesWithCustom();
    act(() =>
      useAgentStore.getState().setConfig({
        template_id: 2,
        agent_order: [
          ['agent_researcher'],
          ['agent_architect'],
          ['agent_writer'],
          ['agent_auditor'],
          ['agent_reviser'],
        ],
        agent_roles: { agent_researcher: AGENT_DEFAULT_SENTINEL },
      }),
    );
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('资料研究员');
    expect(screen.getByTestId('agent-order-slot-agent_researcher')).toHaveTextContent('0');
  });

  it('R8 回读 config.agent_roles 已有模型 → 开关 on + Select 回显', async () => {
    mockTemplatesWithCustom();
    act(() =>
      useAgentStore.getState().setConfig({
        template_id: 2,
        agent_roles: { agent_researcher: 'zhipu/glm-4.5' },
      }),
    );
    await renderCard();
    const card = screen.getByTestId('agent-chain-card');
    await within(card).findByText('资料研究员');
    expect(within(card).getAllByRole('switch')[4]).toBeChecked();
    expect(screen.getByTestId('agent-model-select-agent_researcher')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('agent-model-select-agent_researcher')).toHaveTextContent('zhipu/glm-4.5');
    });
  });
});
