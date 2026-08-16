/**
 * ⚠️ 契约文件（Issue #260 F41 Agent 创建/编辑弹窗，spec §5.5 / §8.3 / §13 M8）
 *
 * GREEN 新建 src/components/AgentEditDialog.tsx，必须匹配：
 *
 * 组件契约（受控弹窗，纯表单——不做 API 调用，保存走回调；镜像 TemplateDialog 先例）：
 * - props：{ open: boolean; onOpenChange(open: boolean): void;
 *   editing?: AgentEntity | null; onCreate(input: AgentInput): void;
 *   onUpdate(input: AgentInput): void }
 *   AgentEntity / AgentInput 结构同 stores/agents 契约（GREEN 类型可来自 store 或组件内定义）
 * - open=true → role=dialog + data-testid="agent-dialog"；标题：editing 空 →「新建 Agent」，
 *   editing 有值 →「编辑 Agent」；open=false → 不渲染
 * - 表单字段：
 *   * 名称：label「名称」+ data-testid="agent-name-input"，必填
 *     —— 空 → 内联错误（set.agents.nameRequired「名称不能为空」）+ 不提交（onCreate/onUpdate 不调用）
 *   * 描述：label「描述」+ data-testid="agent-desc-input"
 *   * 图标：label「图标」+ data-testid="agent-icon-input"
 *   * System Prompt：label「System Prompt」+ data-testid="agent-prompt-input"（textarea）
 *   * 函数分组 checkbox（D2 拍板：分组勾选，多选白名单）：
 *     - 按工具目录 group 聚合渲染四组，组容器 data-testid="agent-tool-group-<group>"
 *       （writing→写作 / retrieval→检索 / audit→审计 / project→项目）
 *     - 每组内每个工具一个 label 容器（内含 checkbox 控件 + 工具 name + description 文本）：
 *       data-testid="agent-tool-<name>"（testid 落在 label 容器上；点击容器 = 切换勾选）
 *     - project 组为空（本期无项目域工具）→ 组容器可省略不渲染（负向 queryByTestId 不断言）
 *   * skill 绑定（可搜索列表）：搜索输入 data-testid="agent-skill-search"
 *     （输入过滤 skills 列表）+ 每 skill 一个 label 容器（内含 checkbox 控件 + name 文本）：
 *     data-testid="agent-skill-<id>"（testid 落在 label 容器上；容器文本含 skill name）；
 *     列表空 → 提示（set.agents.noSkills「暂无可用技能」）
 *   * 模型覆盖：label「模型覆盖」+ data-testid="agent-model-input"
 *     （placeholder set.agents.modelPlaceholder「provider/model，留空跟随默认」）
 *   * 温度覆盖：label「温度覆盖」+ data-testid="agent-temp-input"（number，0-2）
 * - 按钮：保存（data-testid="agent-dialog-save"）取消（data-testid="agent-dialog-cancel"）
 * - 关闭：取消 → onOpenChange(false)；ESC → onOpenChange(false)
 * - 数据源：useAgentsStore.skills / .tools 订阅（父级 AgentList 挂载已 loadSkills/loadToolCatalog，
 *   本组件不发起 API 调用）
 *
 * 创建模式初始值（契约）：名称/描述/图标/prompt 空；工具全不勾选；skill 全不勾选；
 * 模型覆盖空；温度覆盖空
 * 编辑模式初始值（契约）：editing 全字段回填（名称/描述/图标/prompt/已勾选工具/
 * 已勾选 skill/模型覆盖/温度覆盖）
 *
 * 保存 payload（onCreate/onUpdate 参数 = 完整 AgentInput）：
 * - tool_ids = 勾选工具 name 列表；skill_ids = 勾选 skill id 字符串化列表（String(id)，后端 str 契约）
 * - model_override = 输入文本 trim 后或 null；temperature_override = 数字或 null（空 → null）
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts；复用 ag.save「保存」/ dlg.cancel「取消」）：
 * set.agents.newAgent='新建 Agent' set.agents.editAgent='编辑 Agent'
 * set.agents.name='名称' set.agents.description='描述' set.agents.icon='图标'
 * set.agents.prompt='System Prompt' set.agents.nameRequired='名称不能为空'
 * set.agents.funcGroup.writing='写作' set.agents.funcGroup.retrieval='检索'
 * set.agents.funcGroup.audit='审计' set.agents.funcGroup.project='项目'
 * set.agents.skillsTitle='技能' set.agents.searchSkills='搜索技能…' set.agents.noSkills='暂无可用技能'
 * set.agents.modelOverride='模型覆盖' set.agents.tempOverride='温度覆盖'
 * set.agents.modelPlaceholder='provider/model，留空跟随默认'
 *
 * RED 预期：./AgentEditDialog 模块不存在 → module-not-found（类 1 契约缺口）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentEditDialog } from './AgentEditDialog';
import { apiFetch } from '../api/client';
import { useAgentsStore } from '../stores/agents';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 契约结构（与 stores/agents 契约一致；GREEN 类型可来自 store 或组件内定义） */
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

const EDITING_AGENT: AgentEntity = {
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

const TOOL_ITEMS = [
  { name: 'save_draft', description: '保存章节草稿（agent 唯一写面）', group: 'writing', input_schema: {} },
  { name: 'search_characters', description: '搜索项目内角色档案', group: 'retrieval', input_schema: {} },
  { name: 'check_foreshadowing', description: '列出未回收伏笔', group: 'retrieval', input_schema: {} },
  { name: 'get_prior_summary', description: '获取前文摘要', group: 'retrieval', input_schema: {} },
  { name: 'audit_chapter', description: '单章一致性审计', group: 'audit', input_schema: {} },
  { name: 'count_words', description: '中英文混合字数统计', group: 'audit', input_schema: {} },
];

const SKILL_ITEMS = [
  { id: 1, name: 'outline-planning', description: '大纲规划方法论', source: 'builtin', agent_ids: [] },
  { id: 3, name: 'web-research', description: '网络调研方法论', source: 'user_upload', agent_ids: [] },
];

function seedStore() {
  useAgentsStore.setState({
    agents: [EDITING_AGENT],
    tools: TOOL_ITEMS,
    skills: SKILL_ITEMS,
    loading: false,
    error: null,
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  seedStore();
});

describe('AgentEditDialog — 创建模式', () => {
  it('渲染：dialog + 标题「新建 Agent」+ 全字段 + 四函数组 + skill 列表 + 模型/温度', () => {
    render(
      <AgentEditDialog
        open
        onOpenChange={() => undefined}
        onCreate={() => undefined}
        onUpdate={() => undefined}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    expect(dlg).toHaveTextContent('新建 Agent');
    expect(within(dlg).getByTestId('agent-name-input')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-desc-input')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-icon-input')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-prompt-input')).toBeInTheDocument();
    // 函数分组（D2）：写作/检索/审计三组渲染（project 组本期空）
    expect(within(dlg).getByTestId('agent-tool-group-writing')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-tool-group-retrieval')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-tool-group-audit')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-tool-save_draft')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-tool-count_words')).toBeInTheDocument();
    // skill 绑定：2 skill checkbox（label 容器含 name 文本）
    expect(within(dlg).getByTestId('agent-skill-1')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-skill-1')).toHaveTextContent('outline-planning');
    expect(within(dlg).getByTestId('agent-skill-3')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-skill-3')).toHaveTextContent('web-research');
    expect(within(dlg).getByTestId('agent-model-input')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-temp-input')).toBeInTheDocument();
  });

  it('函数分组 checkbox：工具 description 可见（勾选 UI 说明）', () => {
    render(
      <AgentEditDialog
        open
        onOpenChange={() => undefined}
        onCreate={() => undefined}
        onUpdate={() => undefined}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    const writingGroup = within(dlg).getByTestId('agent-tool-group-writing');
    expect(writingGroup).toHaveTextContent('保存章节草稿（agent 唯一写面）');
  });

  it('skill 绑定：搜索输入过滤列表', async () => {
    const user = userEvent.setup();
    render(
      <AgentEditDialog
        open
        onOpenChange={() => undefined}
        onCreate={() => undefined}
        onUpdate={() => undefined}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    await user.type(within(dlg).getByTestId('agent-skill-search'), 'web');
    expect(within(dlg).queryByTestId('agent-skill-1')).not.toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-skill-3')).toBeInTheDocument();
  });

  it('创建保存：勾选工具 + 绑 skill + 填模型/温度 → onCreate(完整 AgentInput)', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn();
    render(
      <AgentEditDialog
        open
        onOpenChange={() => undefined}
        onCreate={onCreate}
        onUpdate={() => undefined}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    await user.type(within(dlg).getByTestId('agent-name-input'), '润色师');
    await user.type(within(dlg).getByTestId('agent-desc-input'), '专注润色');
    await user.type(within(dlg).getByTestId('agent-icon-input'), '✨');
    await user.type(within(dlg).getByTestId('agent-prompt-input'), '你是润色师。');
    await user.click(within(dlg).getByTestId('agent-tool-count_words'));
    await user.click(within(dlg).getByTestId('agent-tool-save_draft'));
    await user.click(within(dlg).getByTestId('agent-skill-3'));
    await user.type(within(dlg).getByTestId('agent-model-input'), 'zhipu/glm-4.5');
    await user.type(within(dlg).getByTestId('agent-temp-input'), '0.6');
    await user.click(within(dlg).getByTestId('agent-dialog-save'));
    expect(onCreate).toHaveBeenCalledWith({
      name: '润色师',
      description: '专注润色',
      icon: '✨',
      system_prompt: '你是润色师。',
      tool_ids: ['count_words', 'save_draft'],
      skill_ids: ['3'],
      model_override: 'zhipu/glm-4.5',
      temperature_override: 0.6,
    });
  });

  it('名称必填：空名称 → 内联错误 + 不提交', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn();
    render(
      <AgentEditDialog
        open
        onOpenChange={() => undefined}
        onCreate={onCreate}
        onUpdate={() => undefined}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    await user.click(within(dlg).getByTestId('agent-dialog-save'));
    expect(within(dlg).getByText('名称不能为空')).toBeInTheDocument();
    expect(onCreate).not.toHaveBeenCalled();
  });

  it('取消 → onOpenChange(false)', async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(
      <AgentEditDialog
        open
        onOpenChange={onOpenChange}
        onCreate={() => undefined}
        onUpdate={() => undefined}
      />,
    );
    await user.click(screen.getByTestId('agent-dialog-cancel'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe('AgentEditDialog — 编辑模式', () => {
  it('预填：editing 全字段回填（名称/prompt/已勾选工具/skill/模型/温度）+ 标题「编辑 Agent」', () => {
    render(
      <AgentEditDialog
        open
        editing={EDITING_AGENT}
        onOpenChange={() => undefined}
        onCreate={() => undefined}
        onUpdate={() => undefined}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    expect(dlg).toHaveTextContent('编辑 Agent');
    expect(within(dlg).getByTestId('agent-name-input')).toHaveValue('我的润色师');
    expect(within(dlg).getByTestId('agent-prompt-input')).toHaveValue('你是润色师，负责润色文笔。');
    expect(within(dlg).getByTestId('agent-tool-count_words')).toBeChecked();
    expect(within(dlg).getByTestId('agent-tool-save_draft')).toBeChecked();
    expect(within(dlg).getByTestId('agent-tool-search_characters')).not.toBeChecked();
    expect(within(dlg).getByTestId('agent-skill-3')).toBeChecked();
    expect(within(dlg).getByTestId('agent-model-input')).toHaveValue('zhipu/glm-4.5');
  });

  it('编辑保存：改名称 + 取消一个工具 → onUpdate(完整 AgentInput)', async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <AgentEditDialog
        open
        editing={EDITING_AGENT}
        onOpenChange={() => undefined}
        onCreate={() => undefined}
        onUpdate={onUpdate}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    const nameInput = within(dlg).getByTestId('agent-name-input');
    await user.clear(nameInput);
    await user.type(nameInput, '润色师 v2');
    await user.click(within(dlg).getByTestId('agent-tool-save_draft'));
    await user.click(within(dlg).getByTestId('agent-dialog-save'));
    expect(onUpdate).toHaveBeenCalledWith({
      name: '润色师 v2',
      description: '专注文笔润色的自定义角色',
      icon: '✨',
      system_prompt: '你是润色师，负责润色文笔。',
      tool_ids: ['count_words'],
      skill_ids: ['3'],
      model_override: 'zhipu/glm-4.5',
      temperature_override: 0.6,
    });
  });
});
