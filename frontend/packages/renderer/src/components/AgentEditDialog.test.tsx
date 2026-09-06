/**
 * ⚠️ 契约文件（#957 F58 GUI scope 勾选矩阵 + #260 F41 Agent 创建/编辑弹窗）
 *
 * GREEN 必须匹配：
 * - 非工具契约（保留迁移，【G】）：dialog/标题/名称必填/取消/ESC/skill 搜索/skill 勾选/模型/温度。
 * - 工具区块【R】：函数分组 checkbox（agent-tool-group-* / agent-tool-*）替换为 scope 矩阵：
 *   - 行 = 固定 8 域常量序 DOMAINS = ['outline','character','world','timeline','foreshadowing','memory','writing','agent_chain']
 *   - 列 = read/write/delete；testid 契约见 contract-957 §2。
 *   - 保存 payload：grants 按 DOMAINS 行序展开，ops 按 read→write→delete，不含 ops 为空的域；不含 tool_ids 键。
 *
 * RED 预期：agent-scope-* / agent-tool-group-* 守护 —— 矩阵未实现 → 元素不存在；旧 tool-group 存在 → 守护 FAIL。
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

/** 契约 §1：grant 条目（domain × ops） */
type ToolDomain =
  | 'outline'
  | 'character'
  | 'world'
  | 'timeline'
  | 'foreshadowing'
  | 'memory'
  | 'writing'
  | 'agent_chain';
type ToolOp = 'read' | 'write' | 'delete';
interface GrantEntry {
  domain: ToolDomain;
  ops: ToolOp[];
}

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
  /** #957 F58：后端 _to_response 恒有（resolve 后，含旧 tool_ids 反查） */
  grants?: GrantEntry[];
  resolved_tool_names?: string[];
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

/** ④ 编辑回显（grants 乱序入）：writing 域 write+read */
const SCOPE_EDITING_AGENT: AgentEntity = {
  ...EDITING_AGENT,
  grants: [{ domain: 'writing', ops: ['write', 'read'] }],
  resolved_tool_names: ['count_words', 'save_draft'],
};

/** ⑤ 旧数据：tool_ids 有值、grants 缺失（旧鸭子 fixture）——前端零推断 */
const LEGACY_AGENT: AgentEntity = {
  ...EDITING_AGENT,
  tool_ids: ['count_words'],
  grants: undefined,
  resolved_tool_names: undefined,
};

const TOOL_ITEMS = [
  // writing 域
  { name: 'save_draft', description: '保存章节草稿（agent 唯一写面）', group: 'writing', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'writing', op: 'write' },
  { name: 'generate', description: '续写', group: 'writing', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'writing', op: 'write' },
  { name: 'continue', description: '续写', group: 'writing', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'writing', op: 'write' },
  { name: 'revise', description: '修订', group: 'writing', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'writing', op: 'write' },
  { name: 'get_prior_summary', description: '获取前文摘要', group: 'retrieval', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'writing', op: 'read' },
  { name: 'audit_chapter', description: '单章一致性审计', group: 'audit', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'writing', op: 'read' },
  { name: 'count_words', description: '中英文混合字数统计', group: 'audit', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'writing', op: 'read' },
  // character 域
  { name: 'search_characters', description: '搜索项目内角色档案', group: 'retrieval', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'character', op: 'read' },
  { name: 'create_character', description: '创建角色', group: 'writing', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'character', op: 'write' },
  { name: 'update_character', description: '更新角色', group: 'writing', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'character', op: 'write' },
  // world 域
  { name: 'list_maps', description: '列出场景地图', group: 'retrieval', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'world', op: 'read' },
  { name: 'create_world_setting', description: '创建世界观', group: 'writing', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'world', op: 'write' },
  // outline / foreshadowing / memory
  { name: 'create_outline', description: '创建大纲', group: 'writing', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'outline', op: 'write' },
  { name: 'check_foreshadowing', description: '列出未回收伏笔', group: 'retrieval', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'foreshadowing', op: 'read' },
  { name: 'memory_list', description: '记忆列表', group: 'retrieval', input_schema: {}, allow_custom_agent: true, is_core: false, domain: 'memory', op: 'read' },
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

describe('AgentEditDialog — 创建模式（非工具契约迁移【G】）', () => {
  it('渲染：dialog + 标题「新建 Agent」+ 全字段 + skill 列表 + 模型/温度', () => {
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
    // skill 绑定：2 skill checkbox（label 容器含 name 文本）
    expect(within(dlg).getByTestId('agent-skill-1')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-skill-1')).toHaveTextContent('outline-planning');
    expect(within(dlg).getByTestId('agent-skill-3')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-skill-3')).toHaveTextContent('web-research');
    expect(within(dlg).getByTestId('agent-model-input')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-temp-input')).toBeInTheDocument();
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

  it('ESC → onOpenChange(false)', async () => {
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
    await user.keyboard('{Escape}');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe('AgentEditDialog — 编辑模式（非工具契约迁移【G】）', () => {
  it('预填（非工具字段）：名称/prompt/skill/模型回填 + 标题「编辑 Agent」', () => {
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
    expect(within(dlg).getByTestId('agent-skill-3')).toBeChecked();
    expect(within(dlg).getByTestId('agent-model-input')).toHaveValue('zhipu/glm-4.5');
  });
});

describe('AgentEditDialog — scope 矩阵（#957 F58，【R】）', () => {
  const DOMAINS = ['outline', 'character', 'world', 'timeline', 'foreshadowing', 'memory', 'writing', 'agent_chain'];
  const OPS = ['read', 'write', 'delete'];

  it('① 渲染：agent-scope-matrix + 8 域行 + 24 格 + 三列头 + 删除列头 tooltip', () => {
    render(
      <AgentEditDialog
        open
        onOpenChange={() => undefined}
        onCreate={() => undefined}
        onUpdate={() => undefined}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    const matrix = within(dlg).getByTestId('agent-scope-matrix');
    DOMAINS.forEach((d) => {
      expect(within(matrix).getByTestId(`agent-scope-row-${d}`)).toBeInTheDocument();
      OPS.forEach((op) => {
        expect(within(matrix).getByTestId(`agent-scope-cell-${d}-${op}`)).toBeInTheDocument();
      });
    });
    expect(within(matrix).getByTestId('agent-scope-head-read')).toBeInTheDocument();
    expect(within(matrix).getByTestId('agent-scope-head-write')).toBeInTheDocument();
    expect(within(matrix).getByTestId('agent-scope-head-delete')).toBeInTheDocument();
    // 删除列头说明（tooltip 文案逐字 §4.1）
    expect(within(dlg).getByTestId('agent-scope-delete-help')).toHaveAttribute(
      'title',
      '暴露删除工具；每次删除仍需会话确认（双闸，ADR-043）',
    );
  });

  it('② 可用格 disabled 映射：outline-read / agent_chain 三格 / writing-delete disabled；character-read 可用', () => {
    render(
      <AgentEditDialog
        open
        onOpenChange={() => undefined}
        onCreate={() => undefined}
        onUpdate={() => undefined}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    // 无工具格 disabled
    expect(within(dlg).getByTestId('agent-scope-cell-outline-read').querySelector('input')).toBeDisabled();
    OPS.forEach((op) => {
      expect(within(dlg).getByTestId(`agent-scope-cell-agent_chain-${op}`).querySelector('input')).toBeDisabled();
    });
    expect(within(dlg).getByTestId('agent-scope-cell-writing-delete').querySelector('input')).toBeDisabled();
    // 有工具格可用
    expect(within(dlg).getByTestId('agent-scope-cell-character-read').querySelector('input')).not.toBeDisabled();
  });

  it('③ 勾选保存：勾 character-read/write + world-read → onCreate grants 行序+ops 序，无 tool_ids 键', async () => {
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
    await user.click(within(dlg).getByTestId('agent-scope-cell-character-read'));
    await user.click(within(dlg).getByTestId('agent-scope-cell-character-write'));
    await user.click(within(dlg).getByTestId('agent-scope-cell-world-read'));
    await user.click(within(dlg).getByTestId('agent-dialog-save'));
    expect(onCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        grants: [
          { domain: 'character', ops: ['read', 'write'] },
          { domain: 'world', ops: ['read'] },
        ],
      }),
    );
    // 契约 §2：payload 不含 tool_ids 键
    expect(onCreate.mock.calls[0][0]).not.toHaveProperty('tool_ids');
  });

  it('④ 编辑回显：editing.grants 乱序入 → writing-read/write checked、delete unchecked', () => {
    render(
      <AgentEditDialog
        open
        editing={SCOPE_EDITING_AGENT}
        onOpenChange={() => undefined}
        onCreate={() => undefined}
        onUpdate={() => undefined}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    expect(within(dlg).getByTestId('agent-scope-cell-writing-read').querySelector('input')).toBeChecked();
    expect(within(dlg).getByTestId('agent-scope-cell-writing-write').querySelector('input')).toBeChecked();
    expect(within(dlg).getByTestId('agent-scope-cell-writing-delete').querySelector('input')).not.toBeChecked();
  });

  it('⑤ 旧数据：editing.tool_ids 有值且 grants 缺失 → 全格 unchecked 不崩（前端零推断）', () => {
    render(
      <AgentEditDialog
        open
        editing={LEGACY_AGENT}
        onOpenChange={() => undefined}
        onCreate={() => undefined}
        onUpdate={() => undefined}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    // 弹窗正常渲染（不崩）
    expect(within(dlg).getByTestId('agent-name-input')).toBeInTheDocument();
    // 即便 tool_ids=['count_words']，grants 缺失 → 矩阵不推断勾选（前端零推断逻辑）
    expect(within(dlg).getByTestId('agent-scope-matrix')).toBeInTheDocument();
    expect(within(dlg).getByTestId('agent-scope-cell-writing-read').querySelector('input')).not.toBeChecked();
  });

  it('⑥ 守护：旧函数分组/工具 checkbox testid 不再存在', () => {
    render(
      <AgentEditDialog
        open
        onOpenChange={() => undefined}
        onCreate={() => undefined}
        onUpdate={() => undefined}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    expect(within(dlg).queryByTestId('agent-tool-group-writing')).toBeNull();
    expect(within(dlg).queryByTestId('agent-tool-save_draft')).toBeNull();
    expect(within(dlg).queryByTestId('agent-tool-count_words')).toBeNull();
    expect(within(dlg).queryByTestId('agent-tool-group-retrieval')).toBeNull();
  });

  it('编辑保存：取消 writing-read 后 onUpdate grants（无 tool_ids 键）', async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(
      <AgentEditDialog
        open
        editing={SCOPE_EDITING_AGENT}
        onOpenChange={() => undefined}
        onCreate={() => undefined}
        onUpdate={onUpdate}
      />,
    );
    const dlg = screen.getByTestId('agent-dialog');
    // editing.grants=[{writing:['write','read']}] → 取消 read → grants=[{writing:['write']}]
    await user.click(within(dlg).getByTestId('agent-scope-cell-writing-read'));
    await user.click(within(dlg).getByTestId('agent-dialog-save'));
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        grants: [{ domain: 'writing', ops: ['write'] }],
      }),
    );
    expect(onUpdate.mock.calls[0][0]).not.toHaveProperty('tool_ids');
  });
});
