/**
 * ⚠️ 契约文件（Issue #107 TemplateDialog RED 阶段，spec §9.2.5 / §9.5 / M4）
 *
 * GREEN 新建 src/components/TemplateDialog.tsx，必须匹配：
 *
 * 组件契约（受控弹窗，纯表单——不做 API 调用，保存走回调）：
 * - props：{ open: boolean; onOpenChange(open: boolean): void;
 *   editing?: AgentTemplate | null; onCreate(input: AgentTemplateInput): void;
 *   onUpdate(input: AgentTemplateInput): void }
 *   AgentTemplate / AgentTemplateInput 结构同 stores/templates 契约
 *   （GREEN 类型可来自 store 或组件内定义）
 * - open=true → role=dialog + data-testid="template-dialog"；标题：editing 空 →「新建模板」，
 *   editing 有值 →「编辑模板」；open=false → 不渲染
 * - 表单字段：
 *   * 模板名称：label「模板名称」+ data-testid="template-name-input"，必填
 *     —— 空 → 内联错误（tpl.nameRequired「模板名称不能为空」）+ 不提交（onCreate/onUpdate 不调用）
 *   * 描述：label「描述」+ data-testid="template-description-input"
 *   * 主模型下拉：combobox aria-label「主模型」+ data-testid="template-main-model"
 *   * 四角色行（role ∈ architect | writer | auditor | reviser）：
 *     - 行容器 data-testid="template-role-row-<role>"
 *     - 模型下拉 combobox aria-label「<角色名> 模型」（架构师模型 / 执笔模型 / 审校模型 /
 *       修订模型，角色名复用 m.role.* 文案）+ data-testid="template-role-<role>-model"
 *     - 温度滑杆（Radix Slider，0-1.5 step 0.1）：aria-label「<角色名> 温度」+
 *       data-testid="template-role-<role>-temp" + 行内值显示 data-testid="template-role-<role>-value"
 *     - 启用开关（Radix Switch）：data-testid="template-role-<role>-enabled"；
 *       关闭 → 行内显示「关闭 = 该角色使用默认模型」（tpl.roleDisabledNote）
 *   * 默认温度滑杆：aria-label「默认温度」+ data-testid="template-default-temp" +
 *     值显示 data-testid="template-default-temp-value"
 *   * 默认字数：label「默认字数」+ data-testid="template-default-words"（number input）
 * - 按钮：保存（data-testid="template-save"，文案「保存」复用 ag.save）/
 *   取消（data-testid="template-cancel"，文案「取消」复用 dlg.cancel）
 * - 关闭：取消 → onOpenChange(false)；ESC → onOpenChange(false)
 *
 * 模型选项来源（设计假设）：主模型 / 角色模型下拉选项 = useModelsStore.providers[].models 的 id
 * （模型注册表为唯一真源；测试播种 openai + deepseek 两 provider）
 *
 * 创建模式初始值（契约）：名称/描述空；主模型空；默认温度 0.7；默认字数 800000；
 * 角色行 enabled=true + model null + temperature null（跟随默认）
 *
 * 温度显示 = 一位小数格式化（toFixed(1) 语义）；Radix roundValue 按 step 取整
 * （键盘 ArrowRight ±0.1：0.7 → 0.8，0.4 → 0.5）
 *
 * 保存 payload（onCreate/onUpdate 参数 = 完整 AgentTemplateInput）：
 * - 编辑模式：editing 全字段 + 用户修改（名称/描述/主模型/默认温度/默认字数/角色行）
 * - 关闭的角色：payload 该角色 = { model: null, temperature: null, enabled: false }
 *   （关闭语义 = 该角色使用默认模型，model/temperature 清除覆盖，spec §9.2.5 评审建议 1）
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts；复用 m.role.* / ag.save「保存」/ dlg.cancel「取消」）：
 * tpl.addTemplate='新建模板' tpl.editTemplate='编辑模板' tpl.name='模板名称'
 * tpl.description='描述' tpl.mainModel='主模型'
 * tpl.roleModel.architect='架构师模型' tpl.roleModel.writer='执笔模型'
 * tpl.roleModel.auditor='审校模型' tpl.roleModel.reviser='修订模型'
 * tpl.roleTemp.architect='架构师温度' tpl.roleTemp.writer='执笔温度'
 * tpl.roleTemp.auditor='审校温度' tpl.roleTemp.reviser='修订温度'
 * tpl.defaultTemp='默认温度' tpl.defaultWords='默认字数'
 * tpl.nameRequired='模板名称不能为空' tpl.roleDisabledNote='关闭 = 该角色使用默认模型'
 *
 * RED 预期：./TemplateDialog 模块不存在 → module-not-found（类 1 契约缺口，suite 级失败，
 * 0 test 计数）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TemplateDialog } from './TemplateDialog';
import { apiFetch } from '../api/client';
import { useModelsStore } from '../stores/models';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 契约结构（与 stores/templates 契约一致；GREEN 类型可来自 store 或组件内定义） */
interface AgentTemplateRole {
  model: string | null;
  temperature: number | null;
  enabled: boolean;
}
interface AgentTemplate {
  id: number;
  name: string;
  description: string;
  main_model: string;
  default_temperature: number;
  roles: {
    architect: AgentTemplateRole;
    writer: AgentTemplateRole;
    auditor: AgentTemplateRole;
    reviser: AgentTemplateRole;
  };
  default_words: number;
  is_default: boolean;
  used_by?: Array<{ id: string; name: string }>;
  created_at: string;
  updated_at: string;
}
interface AgentTemplateInput {
  name: string;
  description: string;
  main_model: string;
  default_temperature: number;
  roles: {
    architect: AgentTemplateRole;
    writer: AgentTemplateRole;
    auditor: AgentTemplateRole;
    reviser: AgentTemplateRole;
  };
  default_words: number;
}

const ROLE = (model: string | null, temperature: number | null, enabled: boolean): AgentTemplateRole => ({
  model,
  temperature,
  enabled,
});

/** 模型下拉选项数据源（models store 播种：openai + deepseek） */
const PROVIDERS = [
  {
    id: 1,
    name: 'openai',
    base_url: 'https://api.openai.com/v1',
    default_model: 'gpt-4o',
    models: [{ id: 'gpt-4o', type: 'chat' as const, roles: ['main', 'writer'] }],
    key_saved: true,
    max_retries: 3,
    timeout: 60,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
  },
  {
    id: 2,
    name: 'deepseek',
    base_url: 'https://api.deepseek.com',
    default_model: 'deepseek-chat',
    models: [{ id: 'deepseek-chat', type: 'chat' as const, roles: ['architect'] }],
    key_saved: false,
    max_retries: 3,
    timeout: 60,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
  },
];

const EDITING_TEMPLATE: AgentTemplate = {
  id: 1,
  name: '经典玄幻',
  description: '标准玄幻创作模板',
  main_model: 'gpt-4o',
  default_temperature: 0.7,
  roles: {
    architect: ROLE('deepseek-chat', 0.4, true),
    writer: ROLE('gpt-4o', 0.8, true),
    auditor: ROLE('gpt-4o', 0.5, true),
    reviser: ROLE('deepseek-chat', 0.6, true),
  },
  default_words: 800000,
  is_default: true,
  used_by: [
    { id: 'p1', name: '青云志' },
    { id: 'p2', name: '归墟记' },
  ],
  created_at: '2026-08-01T10:00:00Z',
  updated_at: '2026-08-05T10:00:00Z',
};

/** 编辑模式的输入形状 payload（不含 id / is_default / used_by / 时间戳） */
const EDITING_PAYLOAD: AgentTemplateInput = {
  name: '经典玄幻',
  description: '标准玄幻创作模板',
  main_model: 'gpt-4o',
  default_temperature: 0.7,
  roles: {
    architect: ROLE('deepseek-chat', 0.4, true),
    writer: ROLE('gpt-4o', 0.8, true),
    auditor: ROLE('gpt-4o', 0.5, true),
    reviser: ROLE('deepseek-chat', 0.6, true),
  },
  default_words: 800000,
};

function renderDialog(overrides?: {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  editing?: AgentTemplate | null;
  onCreate?: (input: AgentTemplateInput) => void;
  onUpdate?: (input: AgentTemplateInput) => void;
}) {
  const onOpenChange = overrides?.onOpenChange ?? vi.fn();
  const onCreate = overrides?.onCreate ?? vi.fn();
  const onUpdate = overrides?.onUpdate ?? vi.fn();
  render(
    <TemplateDialog
      open={overrides?.open ?? true}
      onOpenChange={onOpenChange}
      editing={overrides?.editing ?? null}
      onCreate={onCreate}
      onUpdate={onUpdate}
    />,
  );
  return { onOpenChange, onCreate, onUpdate };
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  // 播种模型注册表（下拉选项数据源）；同时 mock GET 兼容 GREEN 挂载 loadProviders 的实现
  useModelsStore.setState({
    providers: PROVIDERS,
    loading: false,
    error: null,
    selectedModelId: null,
    roleBinding: { main: '', architect: '', writer: '', auditor: '', reviser: '', embedding: '' },
  });
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: PROVIDERS, total: 2, offset: 0, limit: 50 };
    }
    return { ok: true };
  });
});

describe('TemplateDialog — 打开 / 关闭', () => {
  it('open=true → dialog 渲染 + 「新建模板」标题', () => {
    renderDialog();
    const dlg = screen.getByRole('dialog');
    expect(dlg).toHaveAttribute('data-testid', 'template-dialog');
    expect(within(dlg).getByText('新建模板')).toBeInTheDocument();
  });

  it('open=false → 不渲染', () => {
    renderDialog({ open: false });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('取消按钮 → onOpenChange(false)', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await user.click(screen.getByTestId('template-cancel'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('ESC → onOpenChange(false)', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await user.keyboard('{Escape}');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('编辑模式：editing 有值 → 「编辑模板」标题', () => {
    renderDialog({ editing: EDITING_TEMPLATE });
    expect(within(screen.getByRole('dialog')).getByText('编辑模板')).toBeInTheDocument();
  });
});

describe('TemplateDialog — 表单字段', () => {
  it('字段齐全：名称/描述/主模型下拉/四角色行（模型下拉+温度滑杆+开关）/默认温度/默认字数', () => {
    renderDialog();
    const dlg = screen.getByTestId('template-dialog');
    expect(within(dlg).getByTestId('template-name-input')).toBeInTheDocument();
    expect(within(dlg).getByTestId('template-description-input')).toBeInTheDocument();
    expect(within(dlg).getByTestId('template-main-model')).toBeInTheDocument();
    for (const role of ['architect', 'writer', 'auditor', 'reviser']) {
      expect(within(dlg).getByTestId(`template-role-row-${role}`)).toBeInTheDocument();
      expect(within(dlg).getByTestId(`template-role-${role}-model`)).toBeInTheDocument();
      expect(within(dlg).getByTestId(`template-role-${role}-temp`)).toBeInTheDocument();
      expect(within(dlg).getByTestId(`template-role-${role}-enabled`)).toBeInTheDocument();
    }
    expect(within(dlg).getByTestId('template-default-temp')).toBeInTheDocument();
    expect(within(dlg).getByTestId('template-default-words')).toBeInTheDocument();
  });

  it('温度滑杆范围契约：默认温度 / 各角色温度 aria-valuemin=0、aria-valuemax=1.5', () => {
    renderDialog();
    for (const name of ['默认温度', '架构师温度', '执笔温度', '审校温度', '修订温度']) {
      const slider = screen.getByRole('slider', { name });
      expect(slider).toHaveAttribute('aria-valuemin', '0');
      expect(slider).toHaveAttribute('aria-valuemax', '1.5');
    }
  });

  it('模型下拉选项来自模型注册表：主模型下拉含 gpt-4o / deepseek-chat', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole('combobox', { name: '主模型' }));
    expect(await screen.findByRole('option', { name: 'gpt-4o' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'deepseek-chat' })).toBeInTheDocument();
  });
});

describe('TemplateDialog — 校验', () => {
  it('名称空 → 保存 → 内联错误「模板名称不能为空」+ onCreate 不调用 + 对话框保持打开', async () => {
    const user = userEvent.setup();
    const { onCreate } = renderDialog();
    await user.click(screen.getByTestId('template-save'));
    expect(screen.getByText('模板名称不能为空')).toBeInTheDocument();
    expect(onCreate).not.toHaveBeenCalled();
    expect(screen.getByTestId('template-dialog')).toBeInTheDocument();
  });
});

describe('TemplateDialog — 创建保存（onCreate 完整 payload）', () => {
  it('填写表单 → 保存 → onCreate 携带完整 AgentTemplateInput', async () => {
    const user = userEvent.setup();
    const { onCreate } = renderDialog();

    await user.type(screen.getByTestId('template-name-input'), '我的模板');
    await user.type(screen.getByTestId('template-description-input'), '测试用模板');

    // 主模型下拉：选 gpt-4o
    await user.click(screen.getByRole('combobox', { name: '主模型' }));
    await user.click(await screen.findByRole('option', { name: 'gpt-4o' }));

    // 默认温度滑杆：初始 0.7 → ArrowRight → 0.8（step 0.1）
    const defaultTemp = screen.getByRole('slider', { name: '默认温度' });
    defaultTemp.focus();
    fireEvent.keyDown(defaultTemp, { key: 'ArrowRight' });

    // 默认字数
    const words = screen.getByTestId('template-default-words');
    await user.clear(words);
    await user.type(words, '500000');

    await user.click(screen.getByTestId('template-save'));

    expect(onCreate).toHaveBeenCalledWith({
      name: '我的模板',
      description: '测试用模板',
      main_model: 'gpt-4o',
      default_temperature: 0.8,
      roles: {
        architect: ROLE(null, null, true),
        writer: ROLE(null, null, true),
        auditor: ROLE(null, null, true),
        reviser: ROLE(null, null, true),
      },
      default_words: 500000,
    });
  });
});

describe('TemplateDialog — 编辑回显与保存（onUpdate）', () => {
  it('编辑模式回显：名称/描述/主模型/角色模型/温度/默认温度/默认字数', () => {
    renderDialog({ editing: EDITING_TEMPLATE });
    const dlg = screen.getByTestId('template-dialog');
    expect(within(dlg).getByTestId('template-name-input')).toHaveValue('经典玄幻');
    expect(within(dlg).getByTestId('template-description-input')).toHaveValue('标准玄幻创作模板');
    expect(within(dlg).getByTestId('template-default-words')).toHaveValue(800000);
    expect(within(dlg).getByTestId('template-main-model')).toHaveTextContent('gpt-4o');
    expect(within(dlg).getByTestId('template-role-architect-model')).toHaveTextContent('deepseek-chat');
    expect(screen.getByRole('slider', { name: '默认温度' })).toHaveAttribute('aria-valuenow', '0.7');
    expect(screen.getByRole('slider', { name: '架构师温度' })).toHaveAttribute('aria-valuenow', '0.4');
    expect(within(dlg).getByTestId('template-role-writer-enabled')).toBeChecked();
    expect(within(dlg).getByTestId('template-role-architect-enabled')).toBeChecked();
  });

  it('编辑保存：改名称 → onUpdate 携带完整 payload（其余字段保持编辑值）', async () => {
    const user = userEvent.setup();
    const { onUpdate } = renderDialog({ editing: EDITING_TEMPLATE });
    await user.clear(screen.getByTestId('template-name-input'));
    await user.type(screen.getByTestId('template-name-input'), '经典玄幻改');
    await user.click(screen.getByTestId('template-save'));
    expect(onUpdate).toHaveBeenCalledWith({ ...EDITING_PAYLOAD, name: '经典玄幻改' });
  });

  it('温度滑杆联动：调滑杆 → 显示值更新（架构师 0.4 → 0.5；默认 0.7 → 0.8）', () => {
    renderDialog({ editing: EDITING_TEMPLATE });

    const archSlider = screen.getByRole('slider', { name: '架构师温度' });
    expect(archSlider).toHaveAttribute('aria-valuenow', '0.4');
    archSlider.focus();
    fireEvent.keyDown(archSlider, { key: 'ArrowRight' });
    expect(archSlider).toHaveAttribute('aria-valuenow', '0.5');
    expect(screen.getByTestId('template-role-architect-value')).toHaveTextContent('0.5');

    const defaultSlider = screen.getByRole('slider', { name: '默认温度' });
    defaultSlider.focus();
    fireEvent.keyDown(defaultSlider, { key: 'ArrowRight' });
    expect(defaultSlider).toHaveAttribute('aria-valuenow', '0.8');
    expect(screen.getByTestId('template-default-temp-value')).toHaveTextContent('0.8');
  });

  it('开关关闭 → 行内显示「关闭 = 该角色使用默认模型」+ payload 该角色 model/temperature 清除（null）', async () => {
    const user = userEvent.setup();
    const { onUpdate } = renderDialog({ editing: EDITING_TEMPLATE });
    const dlg = screen.getByTestId('template-dialog');
    const archRow = within(dlg).getByTestId('template-role-row-architect');

    await user.click(within(archRow).getByTestId('template-role-architect-enabled'));
    expect(within(archRow).getByText('关闭 = 该角色使用默认模型')).toBeInTheDocument();

    await user.click(within(dlg).getByTestId('template-save'));
    expect(onUpdate).toHaveBeenCalledWith({
      ...EDITING_PAYLOAD,
      roles: { ...EDITING_PAYLOAD.roles, architect: ROLE(null, null, false) },
    });
  });
});
