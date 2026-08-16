/**
 * ⚠️ 契约文件（Issue #270 F46 Agent 关联关系 DAG 编排，spec §5.2 + §1.2.2；2026-08-16）
 *
 * GREEN 修改 src/components/AgentRelationEditor.tsx（CREATE），必须匹配：
 *
 * 结构（data-testid 即契约，spec §5.2）：
 * - agent-relation-editor：关系列表容器（F46 新增，E2E 锚点）
 * - agent-relation-add：新增关系入口/依赖选择器（F46 新增，E2E 锚点）——点击展开
 *   from/to/type 三选 + 确认；已展开时容器内渲染
 * - agent-relation-row-<idx>：关系行（from → to [type] + 删除按钮 agent-relation-del-<idx>）
 * - agent-relation-empty：空关系列表提示
 * - agent-relation-dag-preview：只读 DAG 预览容器（SVG）
 * - agent-relation-dag-node-<role>：预览节点（角色字段名，去 agent_ 前缀）
 * - agent-relation-dag-edge-<from>-<to>：预览边（type 决定样式类，见下）
 *
 * 数据模型（spec §2.1 + §5.2）：
 * - ProjectConfig.agent_relations?: {from: string; to: string; type: string}[]
 *   （from/to 带 agent_ 前缀角色字段名；type ∈ sequential/data/conditional）
 * - 角色数据源 = 内置 4（agent_architect/agent_writer/agent_auditor/agent_reviser）
 *   ∪ config.agent_roles keys（自定义角色）
 * - 读取走 useAgentStore.config；变更走 setConfig + onConfigChange（F42 即改即存链路）
 *
 * 交互（spec §5.2 列表式编辑 + 校验前端镜像）：
 * - 点 agent-relation-add → 展开选择器（from Select + to Select + type Select + 确认按钮）
 * - 确认 → setConfig({agent_relations: [...既有, {from, to, type}]}) + onConfigChange()
 * - 自环（from == to）→ 前端预检拦截（提示「不能自环」，不提交）
 * - 重复边（已存在同 from/to）→ 前端预检拦截（提示「重复」，不提交）
 * - 删除 → setConfig({agent_relations: 移除后}) + onConfigChange()
 * - 选择 conditional 类型时显示提示「conditional 边要求目标角色是源角色的唯一后继」
 *   （spec §5.2 conditional 边约束提示）
 *
 * 只读 DAG 预览（spec §1.2.2 可视化表达 + §5.2）：
 * - 节点 = 角色集合（内置 4 + agent_roles，data-testid=agent-relation-dag-node-<role>）
 * - 边 = agent_relations（data-testid=agent-relation-dag-edge-<from>-<to>）
 * - 三类型边样式：sequential=实线 / data=实线+数据标记 / conditional=虚线（样式类契约：
 *   edge-seq / edge-data / edge-cond，断言 className 含对应类）
 * - 预览只读（无编辑交互，画布拖拽归远期 §10）
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts）：
 * - ag.relationTitle='关联关系' / 'Agent Relations'
 * - ag.relationAdd='添加关系' / 'Add relation'
 * - ag.relationFrom='源角色' / 'From'
 * - ag.relationTo='目标角色' / 'To'
 * - ag.relationType='类型' / 'Type'
 * - ag.relationEmpty='暂无关联关系' / 'No relations'
 * - ag.relationSelfLoop='不能自环' / 'Cannot be self-loop'
 * - ag.relationDuplicate='该关系已存在' / 'Relation already exists'
 * - ag.relationCondHint='conditional 边要求目标角色是源角色的唯一后继'
 *   / 'conditional edge requires the target to be the only successor of the source'
 *
 * RED 预期：AgentRelationEditor 组件不存在 → import 失败（module-not-found，文件级
 * 收集失败）；既有 AgentChainCard.test.tsx 追加段见该文件。全部新用例 RED。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentRelationEditor } from './AgentRelationEditor';
import { useAgentStore } from '../stores/agent';
import { useModelsStore } from '../stores/models';
import { useTemplatesStore } from '../stores/templates';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 契约 fixture：三条关系（三类型各一）+ 自定义角色（researcher） */
const RELATIONS = [
  { from: 'agent_architect', to: 'agent_writer', type: 'sequential' },
  { from: 'agent_writer', to: 'agent_auditor', type: 'data' },
  { from: 'agent_auditor', to: 'agent_reviser', type: 'conditional' },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/agent-templates') {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    return { ok: true };
  });
  useAgentStore.setState({
    config: {},
    apiKeyDraft: '',
    testStatus: 'idle',
    testMessage: null,
  });
  useModelsStore.setState({
    providers: [],
    loading: false,
    error: null,
    selectedModelId: null,
    roleBinding: { main: '', architect: '', writer: '', auditor: '', reviser: '', embedding: '' },
  });
  useTemplatesStore.setState({ templates: [], loading: false, error: null, defaultTemplateId: null });
});

function seedRelations(relations: typeof RELATIONS = RELATIONS) {
  act(() => {
    useAgentStore.getState().setConfig({ agent_relations: relations });
  });
}

async function renderEditor() {
  const onConfigChange = vi.fn();
  render(<AgentRelationEditor onConfigChange={onConfigChange} />);
  return onConfigChange;
}

describe('AgentRelationEditor — F46 #270 关系列表（spec §5.2）', () => {
  it('关系列表渲染：每条边 from → to [type]（行 testid + 文案）', async () => {
    seedRelations();
    await renderEditor();
    const editor = screen.getByTestId('agent-relation-editor');
    // 三行
    expect(within(editor).getAllByTestId(/^agent-relation-row-/)).toHaveLength(3);
    // 行内容：from → to [type]
    expect(within(editor).getByText(/agent_architect/)).toBeInTheDocument();
    expect(within(editor).getByText(/agent_writer/)).toBeInTheDocument();
    expect(within(editor).getByText(/conditional/)).toBeInTheDocument();
  });

  it('空关系列表 → 空态提示（agent-relation-empty）', async () => {
    seedRelations([]);
    await renderEditor();
    expect(screen.getByTestId('agent-relation-empty')).toBeInTheDocument();
  });

  it('删除关系 → setConfig 移除该边 + onConfigChange 调用', async () => {
    const user = userEvent.setup();
    seedRelations();
    const onConfigChange = await renderEditor();
    const editor = screen.getByTestId('agent-relation-editor');
    const rows = within(editor).getAllByTestId(/^agent-relation-row-/);
    await user.click(within(rows[0]).getByTestId('agent-relation-del-0'));

    const config = useAgentStore.getState().config;
    expect(config.agent_relations).toHaveLength(2);
    expect(config.agent_relations?.[0]).toEqual({
      from: 'agent_writer',
      to: 'agent_auditor',
      type: 'data',
    });
    expect(onConfigChange).toHaveBeenCalled();
  });
});

describe('AgentRelationEditor — F46 #270 新增关系 + 预检（spec §5.2）', () => {
  it('点添加 → 展开选择器（from/to/type 三选 + 确认）', async () => {
    const user = userEvent.setup();
    await renderEditor();
    await user.click(screen.getByTestId('agent-relation-add'));
    // 选择器展开：三 Select + 确认按钮
    expect(screen.getByTestId('agent-relation-from-select')).toBeInTheDocument();
    expect(screen.getByTestId('agent-relation-to-select')).toBeInTheDocument();
    expect(screen.getByTestId('agent-relation-type-select')).toBeInTheDocument();
    expect(screen.getByTestId('agent-relation-confirm')).toBeInTheDocument();
  });

  it('确认新增 → setConfig 追加 {from,to,type} + onConfigChange', async () => {
    const user = userEvent.setup();
    seedRelations([]);
    const onConfigChange = await renderEditor();
    await user.click(screen.getByTestId('agent-relation-add'));

    // from=agent_auditor / to=agent_reviser / type=conditional
    await user.click(screen.getByTestId('agent-relation-from-select'));
    await user.click(await screen.findByRole('option', { name: 'agent_auditor' }));
    await user.click(screen.getByTestId('agent-relation-to-select'));
    await user.click(await screen.findByRole('option', { name: 'agent_reviser' }));
    await user.click(screen.getByTestId('agent-relation-type-select'));
    await user.click(await screen.findByRole('option', { name: 'conditional' }));
    await user.click(screen.getByTestId('agent-relation-confirm'));

    const config = useAgentStore.getState().config;
    expect(config.agent_relations).toEqual([
      { from: 'agent_auditor', to: 'agent_reviser', type: 'conditional' },
    ]);
    expect(onConfigChange).toHaveBeenCalled();
  });

  it('自环预检：from == to → 提示「不能自环」，不提交', async () => {
    const user = userEvent.setup();
    seedRelations([]);
    const onConfigChange = await renderEditor();
    await user.click(screen.getByTestId('agent-relation-add'));
    await user.click(screen.getByTestId('agent-relation-from-select'));
    await user.click(await screen.findByRole('option', { name: 'agent_writer' }));
    await user.click(screen.getByTestId('agent-relation-to-select'));
    await user.click(await screen.findByRole('option', { name: 'agent_writer' }));
    await user.click(screen.getByTestId('agent-relation-confirm'));

    expect(screen.getByTestId('agent-relation-error')).toHaveTextContent('不能自环');
    expect(useAgentStore.getState().config.agent_relations).toEqual([]);
    expect(onConfigChange).not.toHaveBeenCalled();
  });

  it('重复边预检：已存在同 from/to → 提示「已存在」，不提交', async () => {
    const user = userEvent.setup();
    seedRelations();
    const onConfigChange = await renderEditor();
    await user.click(screen.getByTestId('agent-relation-add'));
    await user.click(screen.getByTestId('agent-relation-from-select'));
    await user.click(await screen.findByRole('option', { name: 'agent_architect' }));
    await user.click(screen.getByTestId('agent-relation-to-select'));
    await user.click(await screen.findByRole('option', { name: 'agent_writer' }));
    await user.click(screen.getByTestId('agent-relation-confirm'));

    expect(screen.getByTestId('agent-relation-error')).toHaveTextContent('已存在');
    expect(useAgentStore.getState().config.agent_relations).toHaveLength(3);
    expect(onConfigChange).not.toHaveBeenCalled();
  });

  it('选择 conditional 类型 → 显示唯一后继约束提示（agent-relation-cond-hint）', async () => {
    const user = userEvent.setup();
    await renderEditor();
    await user.click(screen.getByTestId('agent-relation-add'));
    await user.click(screen.getByTestId('agent-relation-type-select'));
    await user.click(await screen.findByRole('option', { name: 'conditional' }));

    expect(screen.getByTestId('agent-relation-cond-hint')).toBeInTheDocument();
  });
});

describe('AgentRelationEditor — F46 #270 只读 DAG 预览（spec §1.2.2 + §5.2）', () => {
  it('预览渲染：节点 = 角色集合（内置 4 + agent_roles 自定义）', async () => {
    seedRelations();
    act(() => {
      useAgentStore.getState().setConfig({ agent_roles: { agent_researcher: 'openai/gpt-4o' } });
    });
    await renderEditor();
    const preview = screen.getByTestId('agent-relation-dag-preview');
    // 内置 4 + 自定义 researcher = 5 节点
    expect(within(preview).getByTestId('agent-relation-dag-node-architect')).toBeInTheDocument();
    expect(within(preview).getByTestId('agent-relation-dag-node-writer')).toBeInTheDocument();
    expect(within(preview).getByTestId('agent-relation-dag-node-auditor')).toBeInTheDocument();
    expect(within(preview).getByTestId('agent-relation-dag-node-reviser')).toBeInTheDocument();
    expect(within(preview).getByTestId('agent-relation-dag-node-researcher')).toBeInTheDocument();
  });

  it('预览边渲染：每条关系一条边（edge testid）', async () => {
    seedRelations();
    await renderEditor();
    const preview = screen.getByTestId('agent-relation-dag-preview');
    expect(within(preview).getByTestId('agent-relation-dag-edge-architect-writer')).toBeInTheDocument();
    expect(within(preview).getByTestId('agent-relation-dag-edge-writer-auditor')).toBeInTheDocument();
    expect(within(preview).getByTestId('agent-relation-dag-edge-auditor-reviser')).toBeInTheDocument();
  });

  it('三类型边样式：sequential=edge-seq / data=edge-data / conditional=edge-cond（className 契约）', async () => {
    seedRelations();
    await renderEditor();
    const preview = screen.getByTestId('agent-relation-dag-preview');
    expect(
      within(preview).getByTestId('agent-relation-dag-edge-architect-writer').className,
    ).toContain('edge-seq');
    expect(
      within(preview).getByTestId('agent-relation-dag-edge-writer-auditor').className,
    ).toContain('edge-data');
    expect(
      within(preview).getByTestId('agent-relation-dag-edge-auditor-reviser').className,
    ).toContain('edge-cond');
  });

  it('预览只读：无新增/删除按钮（仅关系列表区有交互）', async () => {
    seedRelations();
    await renderEditor();
    const preview = screen.getByTestId('agent-relation-dag-preview');
    expect(within(preview).queryByTestId('agent-relation-add')).not.toBeInTheDocument();
    expect(within(preview).queryByTestId(/^agent-relation-del-/)).not.toBeInTheDocument();
  });
});
