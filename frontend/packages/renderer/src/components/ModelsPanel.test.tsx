/**
 * ⚠️ 契约文件（Issue #106 模型管理页 RED 阶段，spec §8.2③ / §8.3 / §8.6 M2-M4b；
 * #481 迁移：独立页 /models → 设置页模型分类面板，ModelsPage → components/ModelsPanel.tsx）
 *
 * GREEN 创建 src/components/ModelsPanel.tsx（命名导出 ModelsPanel，#481 从独立页迁入设置页），必须匹配：
 *
 * 结构（data-testid 即契约）：
 * - models-panel：面板根容器（原 models-page，页面 → 设置页模型分类面板）
 * - provider-list：Provider 列表容器
 * - provider-card-<id>：Provider 卡片（id = provider id；名称文本渲染）
 * - provider-key-badge-<id>：key 徽标（key_saved=true →「Key 已存」，false →「未存 Key」）
 * - provider-model-count-<id>：模型数徽标（「N 个模型」）
 * - provider-edit-<id>：Provider 卡片「编辑」按钮（F4 评审新增——models.tsx 曾硬编码
 *   editing={null} 导致编辑入口缺失；点击 → ProviderDialog 编辑模式打开）
 * - provider-delete-<id>：删除按钮（既有）
 * - add-provider-btn：添加 Provider 按钮
 * - add-model-btn：「添加模型」按钮（F3 评审新增，spec §8.2③ L929 多选一次性添加入口；
 *   点击 → 模型添加 UI 打开 = role=dialog +「添加模型」标题）
 * - model-table：模型表（行 data-testid="model-row-<modelId>"；类型标记文本 chat / embedding；
 *   角色用途徽标渲染 models[].roles 数组原文）
 * - role-binding：角色绑定区 —— 6 个 Radix Select trigger（aria-label = 主模型 / 大纲架构师 /
 *   执笔 / 审校 / 修订 / RAG embedding）；#107 未合入 → 只读展示（disabled 或 aria-disabled，
 *   M4b 依赖声明）；展示 store roleBinding 草稿值；标注「保存需 Agent 模板功能」
 *
 * 数据契约（GET /api/v1/provider-configs 响应，§8.3；FastAPI 列表包装惯例 §4.4）：
 * { items: ProviderConfig[], total, offset, limit }
 * ProviderConfig = { id, name, base_url, default_model,
 *   models: [{ id, type: 'chat' | 'embedding', roles: string[] }],
 *   key_saved: boolean, max_retries, timeout, created_at, updated_at }
 *
 * 行为：
 * - 挂载 → loadProviders()（GET /api/v1/provider-configs）
 * - 点击 add-provider-btn → ProviderDialog 打开（role=dialog +「添加 Provider」标题）
 * - 点击 provider-edit-<id> → ProviderDialog 打开且处于编辑模式
 *   （标题「编辑 Provider」+ 名称输入预填 provider name——证明 editing prop 传递，F4 评审新增）
 * - 点击 add-model-btn → 模型添加 UI 打开（role=dialog +「添加模型」标题，F3 评审新增）
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts；theme 系 / ap 系 / ag 系已有）：
 * m.title='模型管理' m.addProvider='添加 Provider' m.keySaved='Key 已存' m.keyMissing='未存 Key'
 * m.modelCount='{n} 个模型' m.role.main='主模型' m.role.architect='大纲架构师' m.role.writer='执笔'
 * m.role.auditor='审校' m.role.reviser='修订' m.role.embedding='RAG embedding'
 * m.role.saveNote='保存需 Agent 模板功能'
 * m.editProvider='编辑 Provider'（F4；ProviderDialog 已用，复用）m.edit='编辑'（编辑按钮 aria-label）
 * m.addModel='添加模型'（F3 新 key；模型添加 UI 标题）
 *
 * RED 预期（本批为评审修复契约，页面已实现）：F4 用例 FAIL 于 provider-edit-<id> 不存在
 * （element-missing）；F3 用例 FAIL 于 add-model-btn 不存在（element-missing）；既有用例保持绿。
 *
 * #125 契约升级（2026-08-06，多模型添加部分失败被掩盖）：
 * - handleModelsAdded 契约：接收 AddModelsResult（{ succeeded, failed, errors }，
 *   errors = errorMessage(err) 后的字符串数组）——页面不再从 store.error 读「最后一次调用」
 *   的结果（bug 根源：多行添加时以最后一次为准）；result.failed > 0 →
 *   pushToast('err', t('m.modelsFailed', { n: result.failed, reason: result.errors[0] ?? '' }))；
 *   否则 pushToast('ok', t('m.modelAdded'))。
 * - 新 i18n key（GREEN 补 zh.ts / en.ts）：m.modelsFailed = '{n} 行失败：{reason}'
 *   （zh）/ '{n} rows failed: {reason}'（en）。
 * - AddModelDialog 契约联动：有失败行 → 弹窗不关闭 + 草稿保留（模型 ID 输入值仍在 DOM）。
 * - RED 预期失败形态：'PATCH 失败' 用例升级后 FAIL（当前实现 toast 无「N 行失败：」前缀
 *   + 弹窗仍关闭）；成功路径用例（toast ok「已添加模型」+ 弹窗关闭）与其余用例保持绿。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ModelsPanel } from './ModelsPanel';
import { apiFetch } from '../api/client';
import { useModelsStore } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

interface ProviderModel {
  id: string;
  type: 'chat' | 'embedding';
  roles: string[];
}
interface ProviderConfig {
  id: number;
  name: string;
  base_url: string;
  default_model: string;
  models: ProviderModel[];
  key_saved: boolean;
  max_retries: number;
  timeout: number;
  created_at: string;
  updated_at: string;
}

/** 内置 seed 4 provider（openai/deepseek/zhipu/ollama，§8.2①）的列表 mock（id = 后端自增数字，与 E2E provider-card-1 契约一致） */
const PROVIDER_LIST: { items: ProviderConfig[]; total: number; offset: number; limit: number } = {
  items: [
    {
      id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
      models: [
        { id: 'gpt-4o', type: 'chat', roles: ['main', 'writer'] },
        { id: 'text-embedding-3-small', type: 'embedding', roles: ['rag'] },
      ],
      key_saved: true, max_retries: 3, timeout: 60,
      created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
    },
    {
      id: 2, name: 'deepseek', base_url: 'https://api.deepseek.com', default_model: 'deepseek-chat',
      models: [{ id: 'deepseek-chat', type: 'chat', roles: ['architect'] }],
      key_saved: false, max_retries: 3, timeout: 60,
      created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
    },
    {
      id: 3, name: 'zhipu', base_url: 'https://open.bigmodel.cn/api/paas/v4', default_model: 'glm-4',
      models: [{ id: 'glm-4', type: 'chat', roles: ['auditor'] }],
      key_saved: true, max_retries: 3, timeout: 60,
      created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
    },
    {
      id: 4, name: 'ollama', base_url: 'http://127.0.0.1:11434', default_model: '',
      models: [],
      key_saved: false, max_retries: 3, timeout: 60,
      created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
    },
  ],
  total: 4, offset: 0, limit: 50,
};

const EMPTY_BINDING = { main: '', architect: '', writer: '', auditor: '', reviser: '', embedding: '' };

function renderModelsPanel() {
  return render(<ModelsPanel />);
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useToastStore.setState({ toasts: [] });
  useModelsStore.setState({
    providers: [],
    loading: false,
    error: null,
    selectedModelId: null,
    roleBinding: { ...EMPTY_BINDING },
  });
  apiFetchMock.mockResolvedValue({ ok: true });
});

describe('模型管理页 — Provider 列表（spec §8.2③）', () => {
  it('挂载 → GET /api/v1/provider-configs；列表渲染 4 个内置 provider（名称/模型数/key 徽标）', async () => {
    apiFetchMock.mockResolvedValue(PROVIDER_LIST);
    renderModelsPanel();
    await waitFor(() => expect(useModelsStore.getState().loading).toBe(false));

    // 挂载拉取（宽容形式：不约束 init 形状）
    expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/provider-configs')).toBe(true);

    expect(screen.getByTestId('models-panel')).toBeInTheDocument();
    const list = screen.getByTestId('provider-list');
    for (const name of ['openai', 'deepseek', 'zhipu', 'ollama']) {
      expect(within(list).getByText(name)).toBeInTheDocument();
    }
    // 模型数徽标（openai=id1 2 个模型 / ollama=id4 0 个模型）
    expect(screen.getByTestId('provider-model-count-1')).toHaveTextContent('2 个模型');
    expect(screen.getByTestId('provider-model-count-4')).toHaveTextContent('0 个模型');
    // key 徽标：key_saved=true →「Key 已存」；false →「未存 Key」
    expect(screen.getByTestId('provider-key-badge-1')).toHaveTextContent('Key 已存');
    expect(screen.getByTestId('provider-key-badge-2')).toHaveTextContent('未存 Key');
  });

  it('点击添加 Provider → ProviderDialog 打开（role=dialog +「添加 Provider」标题）', async () => {
    apiFetchMock.mockResolvedValue(PROVIDER_LIST);
    const user = userEvent.setup();
    renderModelsPanel();
    await waitFor(() => expect(useModelsStore.getState().loading).toBe(false));

    await user.click(screen.getByTestId('add-provider-btn'));
    const dlg = await screen.findByRole('dialog');
    expect(within(dlg).getByText('添加 Provider')).toBeInTheDocument();
  });

  it('F4：Provider 卡片「编辑」按钮 → ProviderDialog 编辑模式（「编辑 Provider」标题 + 名称预填）', async () => {
    apiFetchMock.mockResolvedValue(PROVIDER_LIST);
    const user = userEvent.setup();
    renderModelsPanel();
    await waitFor(() => expect(useModelsStore.getState().loading).toBe(false));

    // 编辑入口存在（F4：曾硬编码 editing={null}，编辑入口缺失）
    await user.click(screen.getByTestId('provider-edit-1'));
    const dlg = await screen.findByRole('dialog');
    // 编辑模式：标题 + editing prop 传递（名称输入预填 provider name）
    expect(within(dlg).getByText('编辑 Provider')).toBeInTheDocument();
    expect(within(dlg).getByLabelText('名称')).toHaveValue('openai');
  });
});

describe('模型管理页 — 添加模型入口（F3 评审新增，spec §8.2③ L929 多选一次性添加）', () => {
  it('「添加模型」按钮存在 → 点击打开模型添加 UI（role=dialog +「添加模型」标题）', async () => {
    apiFetchMock.mockResolvedValue(PROVIDER_LIST);
    const user = userEvent.setup();
    renderModelsPanel();
    await waitFor(() => expect(useModelsStore.getState().loading).toBe(false));

    const btn = screen.getByTestId('add-model-btn');
    expect(btn).toHaveTextContent('添加模型');
    await user.click(btn);
    const dlg = await screen.findByRole('dialog');
    expect(within(dlg).getByText('添加模型')).toBeInTheDocument();
  });
});

describe('模型管理页 — 模型表（spec §8.2③ / §8.6 M3）', () => {
  it('chat / embedding 类型标记 + 角色用途徽标（roles 原文）', async () => {
    apiFetchMock.mockResolvedValue(PROVIDER_LIST);
    renderModelsPanel();
    await waitFor(() => expect(useModelsStore.getState().loading).toBe(false));

    const table = screen.getByTestId('model-table');
    // openai 的 chat 模型：类型标记 chat + 角色徽标 main / writer
    const chatRow = within(table).getByTestId('model-row-gpt-4o');
    expect(within(chatRow).getByText('chat')).toBeInTheDocument();
    expect(within(chatRow).getByText('main')).toBeInTheDocument();
    expect(within(chatRow).getByText('writer')).toBeInTheDocument();
    // openai 的 embedding 模型：类型标记 embedding + 角色徽标 rag
    const embRow = within(table).getByTestId('model-row-text-embedding-3-small');
    expect(within(embRow).getByText('embedding')).toBeInTheDocument();
    expect(within(embRow).getByText('rag')).toBeInTheDocument();
    // deepseek 的 chat 模型（architect 角色）
    const dsRow = within(table).getByTestId('model-row-deepseek-chat');
    expect(within(dsRow).getByText('chat')).toBeInTheDocument();
    expect(within(dsRow).getByText('architect')).toBeInTheDocument();
  });
});

describe('模型管理页 — 角色绑定区已移除（#523：模板已含角色组合+模型设置，UI 区块删除）', () => {
  it('role-binding 区块不渲染（6 槽位 aria-label 不出现）+ 其余区块（provider 列表/模型表）保留', async () => {
    apiFetchMock.mockResolvedValue(PROVIDER_LIST);
    act(() => {
      useModelsStore.setState({
        roleBinding: {
          main: 'gpt-4o',
          architect: '',
          writer: 'deepseek-chat',
          auditor: '',
          reviser: '',
          embedding: 'text-embedding-3-small',
        },
      });
    });
    renderModelsPanel();
    await waitFor(() => expect(useModelsStore.getState().loading).toBe(false));

    // #523：移除角色绑定 UI——区块与 6 个下拉均不存在
    expect(screen.queryByTestId('role-binding')).not.toBeInTheDocument();
    for (const label of ['主模型', '大纲架构师', '执笔', '审校', '修订', 'RAG embedding']) {
      expect(screen.queryByRole('combobox', { name: label })).not.toBeInTheDocument();
    }
    // 其余区块保留：provider 列表 + 模型表
    expect(screen.getByTestId('provider-list')).toBeInTheDocument();
    expect(screen.getByTestId('model-table')).toBeInTheDocument();
  });
});

describe('模型管理页 — 删除 Provider（确认弹窗，spec §8.6 M4b）', () => {
  it('点击删除按钮 → 确认弹窗（标题 + 确认文案含 provider 名与模型数 + 取消/删除按钮）', async () => {
    apiFetchMock.mockResolvedValue(PROVIDER_LIST);
    const user = userEvent.setup();
    renderModelsPanel();
    await screen.findByTestId('provider-card-1');

    await user.click(screen.getByTestId('provider-delete-1'));
    const dlg = screen.getByRole('dialog', { name: '删除 Provider' });
    expect(within(dlg).getByText('删除 Provider「openai」？该 Provider 有 2 个模型')).toBeInTheDocument();
    expect(within(dlg).getByRole('button', { name: '取消' })).toBeInTheDocument();
    expect(within(dlg).getByRole('button', { name: '删除' })).toBeInTheDocument();
  });

  it('取消 → 弹窗关闭 + DELETE 未调用 + Provider 卡片仍在', async () => {
    apiFetchMock.mockResolvedValue(PROVIDER_LIST);
    const user = userEvent.setup();
    renderModelsPanel();
    await screen.findByTestId('provider-card-1');

    await user.click(screen.getByTestId('provider-delete-1'));
    await user.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(apiFetchMock.mock.calls.some((c) => c[1]?.method === 'DELETE')).toBe(false);
    expect(screen.getByTestId('provider-card-1')).toBeInTheDocument();
  });

  it('遮罩点击 → 弹窗关闭（不删除）', async () => {
    apiFetchMock.mockResolvedValue(PROVIDER_LIST);
    const user = userEvent.setup();
    renderModelsPanel();
    await screen.findByTestId('provider-card-1');

    await user.click(screen.getByTestId('provider-delete-1'));
    await user.click(screen.getByRole('presentation'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(apiFetchMock.mock.calls.some((c) => c[1]?.method === 'DELETE')).toBe(false);
    expect(screen.getByTestId('provider-card-1')).toBeInTheDocument();
  });

  it('确认删除 → DELETE /api/v1/provider-configs/{id} + 卡片移除 + toast ok「已删除」', async () => {
    apiFetchMock.mockResolvedValue(PROVIDER_LIST);
    const user = userEvent.setup();
    renderModelsPanel();
    await screen.findByTestId('provider-card-1');

    await user.click(screen.getByTestId('provider-delete-1'));
    await user.click(screen.getByRole('button', { name: '删除' }));
    await waitFor(() => expect(screen.queryByTestId('provider-card-1')).not.toBeInTheDocument());
    expect(
      apiFetchMock.mock.calls.some(
        (c) => c[0] === '/api/v1/provider-configs/1' && c[1]?.method === 'DELETE',
      ),
    ).toBe(true);
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts[toasts.length - 1]).toMatchObject({ type: 'ok', message: '已删除' });
    });
  });

  it('DELETE 失败 → toast err（错误文案）+ Provider 卡片仍在', async () => {
    apiFetchMock.mockImplementation(async (_path: string, init?: { method?: string }) => {
      if (init?.method === 'DELETE') throw new Error('内置 Provider 不可删除');
      return PROVIDER_LIST;
    });
    const user = userEvent.setup();
    renderModelsPanel();
    await screen.findByTestId('provider-card-1');

    await user.click(screen.getByTestId('provider-delete-1'));
    await user.click(screen.getByRole('button', { name: '删除' }));
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts[toasts.length - 1]).toMatchObject({ type: 'err', message: '内置 Provider 不可删除' });
    });
    expect(screen.getByTestId('provider-card-1')).toBeInTheDocument();
  });
});

describe('模型管理页 — 添加模型保存（F3 全量 PATCH 语义 + toast 联动）', () => {
  it('填写模型 → 保存 → PATCH（body 含既有+新模型全量）→ 新行入表 + toast ok「已添加模型」+ 弹窗关闭', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/provider-configs/1' && init?.method === 'PATCH') {
        return { ...PROVIDER_LIST.items[0], models: (init.body as { models: ProviderModel[] }).models };
      }
      return PROVIDER_LIST;
    });
    const user = userEvent.setup();
    renderModelsPanel();
    await screen.findByTestId('provider-card-1');

    await user.click(screen.getByTestId('add-model-btn'));
    const dlg = await screen.findByTestId('add-model-dialog');
    await user.type(within(dlg).getByLabelText('模型 ID 1'), 'gpt-4o-mini');
    await user.type(within(dlg).getByLabelText('角色用途 1'), 'writing, audit');
    await user.click(within(dlg).getByRole('button', { name: '保存' }));

    // PATCH 全量语义：openai 既有 2 模型 + 新模型 = 3（后端 exclude_unset 整体替换，F3 契约）
    await waitFor(() => {
      const patch = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/provider-configs/1' && c[1]?.method === 'PATCH',
      );
      expect(patch).toBeTruthy();
      const models = (patch![1]!.body as { models: ProviderModel[] }).models;
      expect(models).toHaveLength(3);
      expect(models[models.length - 1]).toEqual({
        id: 'gpt-4o-mini',
        type: 'chat',
        roles: ['writing', 'audit'],
      });
    });
    // 弹窗关闭 + 表格新行（providerName 联动）+ toast ok
    await waitFor(() => expect(screen.queryByTestId('add-model-dialog')).not.toBeInTheDocument());
    const newRow = await screen.findByTestId('model-row-gpt-4o-mini');
    expect(within(newRow).getByText('openai')).toBeInTheDocument();
    expect(within(newRow).getByText('writing')).toBeInTheDocument();
    expect(within(newRow).getByText('audit')).toBeInTheDocument();
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts[toasts.length - 1]).toMatchObject({ type: 'ok', message: '已添加模型' });
    });
  });

  it('#125 PATCH 失败 → toast err「1 行失败：内置 Provider 不可修改」+ 弹窗不关闭 + 草稿保留', async () => {
    apiFetchMock.mockImplementation(async (_path: string, init?: { method?: string }) => {
      if (init?.method === 'PATCH') throw new Error('内置 Provider 不可修改');
      return PROVIDER_LIST;
    });
    const user = userEvent.setup();
    renderModelsPanel();
    await screen.findByTestId('provider-card-1');

    await user.click(screen.getByTestId('add-model-btn'));
    const dlg = await screen.findByTestId('add-model-dialog');
    await user.type(within(dlg).getByLabelText('模型 ID 1'), 'gpt-4o-mini');
    await user.click(within(dlg).getByRole('button', { name: '保存' }));

    // 失败行 toast：m.modelsFailed（'{n} 行失败：{reason}'）渲染结果（i18n key 由 GREEN 补；
    // RED 阶段当前实现 toast 无前缀 → 本断言 FAIL）
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts[toasts.length - 1]).toMatchObject({
        type: 'err',
        message: '1 行失败：内置 Provider 不可修改',
      });
    });
    // #125 契约：有失败 → 弹窗不关闭 + 草稿保留（模型 ID 输入值仍在 DOM；RED 阶段当前实现
    // 弹窗关闭 → 本断言 FAIL）
    expect(screen.getByTestId('add-model-dialog')).toBeInTheDocument();
    expect(within(dlg).getByLabelText('模型 ID 1')).toHaveValue('gpt-4o-mini');
  });
});

describe('模型管理页 — Provider 保存成功后重新拉取（handleSaved）', () => {
  it('添加 Provider 保存成功 → POST → onSaved → loadProviders 再次 GET', async () => {
    apiFetchMock.mockImplementation(async (_path: string, init?: { method?: string }) => {
      if (init?.method === 'POST') return PROVIDER_LIST.items[0];
      return PROVIDER_LIST;
    });
    const user = userEvent.setup();
    renderModelsPanel();
    await screen.findByTestId('provider-card-1');
    const getCountBefore = apiFetchMock.mock.calls.filter(
      (c) => c[0] === '/api/v1/provider-configs' && !c[1]?.method,
    ).length;

    await user.click(screen.getByTestId('add-provider-btn'));
    const dlg = await screen.findByRole('dialog');
    await user.type(within(dlg).getByLabelText('名称'), 'openai');
    await user.click(within(dlg).getByRole('button', { name: '保存' }));

    // handleSaved → loadProviders：GET 次数比保存前多
    await waitFor(() => {
      const getCountAfter = apiFetchMock.mock.calls.filter(
        (c) => c[0] === '/api/v1/provider-configs' && !c[1]?.method,
      ).length;
      expect(getCountAfter).toBeGreaterThan(getCountBefore);
    });
  });
});
