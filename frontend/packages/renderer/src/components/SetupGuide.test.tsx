/**
 * F60 首启模型配置引导组件契约（RED — #934 §5 / N1-N5）。
 *
 * ⚠️ 本文件 = 契约。GREEN 必须新建 src/components/SetupGuide.tsx，导出：
 *
 *   export function SetupGuide(): JSX.Element
 *
 * 组件契约（spec §5.1-§5.6）：
 * - 全屏引导容器 data-testid="setup-guide"；不可 ESC 关闭（无 ESC 监听）
 * - 三步指示：data-testid="setup-steps"，步骤 1/2/3 各一项（setup-step-1..3）
 * - 步骤 1：Provider 列表 + 添加 Provider（setup-add-provider）+ 下一步（setup-to-step2）
 * - 步骤 2：chat 模型下拉（setup-chat-select）+ 测试连接（setup-test-conn）
 *   + 失败错误行（setup-test-error）+ 上一步（setup-back-step1）
 * - 步骤 3：embedding 录入 + 跳过（setup-skip-embedding）+ 完成（setup-finish）
 * - 步骤切换：setup-to-step2 进入步骤 2；步骤 2 测试通过后进入步骤 3
 * - N5：llm/test 返回 {ok:false, message} → 留在步骤 2 + 展示 message + 可重试
 * - 完成/跳过 → 调 useModelReadinessStore.getState().load() 复核判据
 *   （由 App 层据新判据卸载本组件；组件自身不 unmount）
 *
 * i18n：新增 key 前缀 setup.*（GREEN 补 zh.ts/en.ts）；断言用 data-testid
 * 而非硬编码中文（防文案微调脆弱）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SetupGuide } from './SetupGuide';
import { apiFetch } from '../api/client';
import { useModelReadinessStore } from '../stores/modelReadiness';
import { useModelsStore } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 已注册一个带 chat 模型的 provider（步骤 1 完成态，可进入步骤 2） */
const PROVIDERS = [
  {
    id: 1,
    name: 'deepseek',
    base_url: 'https://api.deepseek.com/v1',
    default_model: '',
    models: [{ id: 'deepseek-chat', type: 'chat', roles: [] }],
    key_saved: true,
    max_retries: 3,
    timeout: 120,
    created_at: '2026-09-10T00:00:00Z',
    updated_at: '2026-09-10T00:00:00Z',
  },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  useModelReadinessStore.setState({
    readiness: {
      ready: false,
      has_chat_model: false,
      has_embedding_model: false,
      reason: 'no_provider',
    },
    loading: false,
  });
  useModelsStore.setState({ providers: [], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  // 默认 enrichment：provider 列表信封（组件挂载即 loadProviders）
  apiFetchMock.mockImplementation(async (url: string) => {
    if (url === '/api/v1/provider-configs') {
      return { items: PROVIDERS, total: PROVIDERS.length };
    }
    return { ok: true };
  });
});

/** 渲染并等待 provider 列表加载完成（步骤 1 可交互） */
async function renderLoaded() {
  render(<SetupGuide />);
  await waitFor(() => expect(screen.getByTestId('setup-to-step2')).toBeEnabled());
}

/** 推进到步骤 3（步骤 2 探测通过） */
async function advanceToStep3(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId('setup-to-step2'));
  await user.click(screen.getByTestId('setup-chat-select'));
  await user.click(await screen.findByRole('option', { name: 'deepseek/deepseek-chat' }));
  await user.click(screen.getByTestId('setup-test-conn'));
  await waitFor(() => expect(screen.getByTestId('setup-skip-embedding')).toBeInTheDocument());
}

describe('SetupGuide — 首启配置引导（#934 N1-N5）', () => {
  it('N1：渲染全屏引导容器 + 三步指示', async () => {
    await renderLoaded();
    expect(screen.getByTestId('setup-guide')).toBeInTheDocument();
    expect(screen.getByTestId('setup-steps')).toBeInTheDocument();
    expect(screen.getByTestId('setup-step-1')).toBeInTheDocument();
    expect(screen.getByTestId('setup-step-2')).toBeInTheDocument();
    expect(screen.getByTestId('setup-step-3')).toBeInTheDocument();
  });

  it('N2：步骤 3 有「跳过」按钮（embedding 可跳过）', async () => {
    const user = userEvent.setup();
    await renderLoaded();
    await advanceToStep3(user);
    expect(screen.getByTestId('setup-skip-embedding')).toBeInTheDocument();
  });

  it('N5：llm/test 失败 → 留在引导 + 展示可读错误 + 可重试', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/v1/provider-configs') {
        return { items: PROVIDERS, total: PROVIDERS.length };
      }
      if (url === '/api/v1/settings/llm/test') {
        return { ok: false, message: 'invalid api key' };
      }
      return { ok: true };
    });
    await renderLoaded();
    await user.click(screen.getByTestId('setup-to-step2'));
    await user.click(screen.getByTestId('setup-chat-select'));
    await user.click(await screen.findByRole('option', { name: 'deepseek/deepseek-chat' }));
    await user.click(screen.getByTestId('setup-test-conn'));
    await waitFor(() => {
      expect(screen.getByTestId('setup-test-error')).toHaveTextContent('invalid api key');
    });
    // 仍在引导内（未卸载）+ 可重试（按钮仍可点）
    expect(screen.getByTestId('setup-guide')).toBeInTheDocument();
    expect(screen.getByTestId('setup-test-conn')).toBeEnabled();
  });

  it('N1/N4：跳过 embedding → 触发 readiness 刷新（load 被调用）', async () => {
    const user = userEvent.setup();
    const loadSpy = vi.spyOn(useModelReadinessStore.getState(), 'load').mockResolvedValue();
    await renderLoaded();
    await advanceToStep3(user);
    await user.click(screen.getByTestId('setup-skip-embedding'));
    await waitFor(() => expect(loadSpy).toHaveBeenCalled());
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// #1152 RED 契约
//
// 缺陷 1：SetupGuide.tsx:164-175 provider 列表行是纯展示 <div>（无 onClick、
//         从不把 editing 传给 ProviderDialog）→ 首启只能「新增」，不能回改已
//         注册 provider 的 base_url / default_model。
// 缺陷 2：SetupGuide.tsx:49-51 loadProviders 只在挂载跑一次；「下一步」仅
//         setStep(2) → chat_model_source 停在挂载时旧值 → 步骤 2 下拉空
//         （rc8 打包产物实测：后端候选有 deepseek/deepseek-flash，前端不刷新）。
//
// 修复方向（#1152 方案 A）：行 onClick → ProviderDialog editing={p}；
//   「下一步」onClick 先 await loadProviders() 再 setStep(2)。
// ─────────────────────────────────────────────────────────────────────────────

/** rc8 实测形态：provider 已注册但 models[] 为空 —— chat 候选只在信封 chat_model_source 里 */
const PROVIDERS_NO_MODELS = [{ ...PROVIDERS[0], models: [] }];

/** 可编辑态 provider：三个预填字段均非空（空值预填断言无意义） */
const PROVIDER_EDITABLE = {
  ...PROVIDERS[0],
  base_url: 'https://api.deepseek.com/v1',
  default_model: 'deepseek/deepseek-flash',
  models: [],
};

/** GET /api/v1/provider-configs 实际请求次数（= loadProviders 拉取次数） */
const providerListCalls = () =>
  apiFetchMock.mock.calls.filter((c) => c[0] === '/api/v1/provider-configs').length;

describe('SetupGuide — #1152 provider 行可编辑 + 步骤 2 候选源刷新', () => {
  it('D1：点击 provider 行 → 打开 ProviderDialog', async () => {
    apiFetchMock.mockImplementation(async (url: string) =>
      url === '/api/v1/provider-configs' ? { items: [PROVIDER_EDITABLE], total: 1 } : { ok: true },
    );
    await renderLoaded();

    fireEvent.click(screen.getByTestId('setup-provider-deepseek'));

    expect(await screen.findByTestId('provider-dialog')).toBeInTheDocument();
  });

  it('D1：编辑对话框预填该 provider 的 name / base_url / default_model', async () => {
    apiFetchMock.mockImplementation(async (url: string) =>
      url === '/api/v1/provider-configs' ? { items: [PROVIDER_EDITABLE], total: 1 } : { ok: true },
    );
    await renderLoaded();

    fireEvent.click(screen.getByTestId('setup-provider-deepseek'));
    const dlg = await screen.findByTestId('provider-dialog');

    expect(within(dlg).getByLabelText('名称')).toHaveValue('deepseek');
    expect(within(dlg).getByLabelText('Base URL')).toHaveValue('https://api.deepseek.com/v1');
    expect(within(dlg).getByLabelText('模型')).toHaveValue('deepseek/deepseek-flash');
  });

  it('D2：步骤 2 chat 下拉含重新拉取到的候选（chat_model_source.project_models）', async () => {
    const user = userEvent.setup();
    // 挂载时后端候选源尚未就绪（rc8 真实时序）；「下一步」触发的第二次拉取才有候选
    let calls = 0;
    apiFetchMock.mockImplementation(async (url: string) => {
      if (url !== '/api/v1/provider-configs') return { ok: true };
      calls += 1;
      return calls === 1
        ? { items: PROVIDERS_NO_MODELS, total: PROVIDERS_NO_MODELS.length }
        : {
            items: PROVIDERS_NO_MODELS,
            total: PROVIDERS_NO_MODELS.length,
            chat_model_source: {
              project_models: ['deepseek/deepseek-flash'],
              default_model: '',
            },
          };
    });
    await renderLoaded();

    await user.click(screen.getByTestId('setup-to-step2'));
    await user.click(await screen.findByTestId('setup-chat-select'));

    expect(
      await screen.findByRole('option', { name: 'deepseek/deepseek-flash' }),
    ).toBeInTheDocument();
  });

  it('D3：进入步骤 2 前重新拉取 provider 列表（loadProviders 再次执行）', async () => {
    const user = userEvent.setup();
    await renderLoaded();
    const before = providerListCalls();
    expect(before).toBeGreaterThan(0); // 挂载时已拉过一次

    await user.click(screen.getByTestId('setup-to-step2'));

    await waitFor(() => expect(providerListCalls()).toBeGreaterThan(before));
  });

  it('D5a 反例守护：有 provider 时「下一步」不 disabled，且仍可进入步骤 2', async () => {
    await renderLoaded();

    expect(screen.getByTestId('setup-to-step2')).toBeEnabled();
    fireEvent.click(screen.getByTestId('setup-to-step2'));

    expect(await screen.findByTestId('setup-chat-select')).toBeInTheDocument();
  });

  it('D5b 反例守护：setup-add-provider 仍能打开对话框（新增路径不回归）', async () => {
    await renderLoaded();

    fireEvent.click(screen.getByTestId('setup-add-provider'));

    const dlg = await screen.findByTestId('provider-dialog');
    expect(within(dlg).getByLabelText('名称')).toHaveValue('');
  });

  // 缺陷 3：SetupGuide.tsx:93-101 llm/test 请求体硬编码 api_key:'' → 后端必填
  // 非空校验 422（detail 是 pydantic 数组，UI 显示红字 JSON，步骤 2 死路）。
  // 修复方向：请求体去掉 api_key 字段 → 后端回退 keychain（ProviderDialog 已存）。
  it('D6：点「测试连接」发出的请求体不含 api_key 字段', async () => {
    const user = userEvent.setup();
    const bodies: Array<Record<string, unknown>> = [];
    apiFetchMock.mockImplementation(async (url: string, init?: { body?: unknown }) => {
      if (url === '/api/v1/provider-configs') {
        return { items: PROVIDERS, total: PROVIDERS.length };
      }
      if (url === '/api/v1/settings/llm/test') {
        bodies.push((init?.body ?? {}) as Record<string, unknown>);
        return { ok: true };
      }
      return { ok: true };
    });
    await renderLoaded();

    await user.click(screen.getByTestId('setup-to-step2'));
    await user.click(screen.getByTestId('setup-chat-select'));
    await user.click(await screen.findByRole('option', { name: 'deepseek/deepseek-chat' }));
    await user.click(screen.getByTestId('setup-test-conn'));

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).not.toHaveProperty('api_key');
    // 其余字段仍在（不是整包发空）
    expect(bodies[0]).toMatchObject({ provider: 'deepseek', model: 'deepseek/deepseek-chat' });
  });

  // 用户指正（2026-09-14）：步骤 2 是「填模型」，模型列表应从 provider 的 /models
  // 实时读取（POST /api/v1/provider-configs/models），不是注册表静态值。
  // 后端该端点已实现（provider_configs.py:209-244，含 keychain 回退）；
  // 前端 ProviderDialog.tsx:127-154 已有调用范式，SetupGuide 应复用。
  it('D7：步骤 2 调 /provider-configs/models 实时探测并渲染返回的模型', async () => {
    const user = userEvent.setup();
    const probeBodies: Array<Record<string, unknown>> = [];
    apiFetchMock.mockImplementation(async (url: string, init?: { body?: unknown }) => {
      if (url === '/api/v1/provider-configs') {
        // 注册表恒空 models[]（rc8 实测各 provider chat 型均为 []）
        return { items: PROVIDERS_NO_MODELS, total: PROVIDERS_NO_MODELS.length };
      }
      if (url === '/api/v1/provider-configs/models') {
        probeBodies.push((init?.body ?? {}) as Record<string, unknown>);
        // 上游真实探测结果（非注册表值）
        return { ok: true, models: ['deepseek-chat', 'deepseek-reasoner'] };
      }
      return { ok: true };
    });
    await renderLoaded();

    await user.click(screen.getByTestId('setup-to-step2'));
    await user.click(await screen.findByTestId('setup-chat-select'));

    // 探测端点被调用且带 base_url（+ provider，供 keychain 回退）
    await waitFor(() => expect(probeBodies.length).toBeGreaterThan(0));
    expect(probeBodies[0]).toHaveProperty('base_url');
    // 下拉渲染的是**探测返回**的模型（注册表为空也必须有值）
    expect(
      await screen.findByRole('option', { name: /deepseek-chat/ }),
    ).toBeInTheDocument();
  });

  it('D8 反例守护：探测失败 → 可读提示，不崩且可重试', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/v1/provider-configs') {
        return { items: PROVIDERS_NO_MODELS, total: PROVIDERS_NO_MODELS.length };
      }
      if (url === '/api/v1/provider-configs/models') {
        return { ok: false, message: '模型发现失败：无法连接上游服务，请检查 Base URL 与网络' };
      }
      return { ok: true };
    });
    await renderLoaded();

    await user.click(screen.getByTestId('setup-to-step2'));

    // 不崩：步骤 2 容器仍在
    expect(await screen.findByTestId('setup-chat-select')).toBeInTheDocument();
    // 且必须展示**可读错误**（非恒真的存在性断言——`setup-models-error` 只在
    // discoveryError 非空时渲染，探测全失败时必现）
    const err = await screen.findByTestId('setup-models-error');
    expect(err).toBeInTheDocument();
    expect(err.textContent).toContain('模型发现失败');
  });

  // ── 缺陷 A（用户复验 2026-09-14）：下拉仍是静态候选（看到 v4-flash）──────
  // 根因：discoverChatModels 的 `if (!p.base_url.trim())` 在 base_url=null 时抛
  // TypeError（实测 openai 的 base_url 就是 null）→ 循环中断 → setProbedOptions
  // 从未执行 → probedOptions 空 → 退回静态候选。
  it('D9：provider base_url 为 null 时不抛错，且其余 provider 仍被探测（探测结果生效）', async () => {
    const user = userEvent.setup();
    // null base_url 的 provider 排在前面（复刻实测顺序：openai 更早）
    const providersWithNull = [
      {
        id: 9,
        name: 'openai',
        base_url: null, // ← 实测值就是 null
        default_model: '',
        models: [],
        key_saved: false,
        max_retries: 3,
        timeout: 120,
        created_at: '2026-09-10T00:00:00Z',
        updated_at: '2026-09-10T00:00:00Z',
      },
      ...PROVIDERS_NO_MODELS,
    ];
    apiFetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/v1/provider-configs') {
        return { items: providersWithNull, total: providersWithNull.length };
      }
      if (url === '/api/v1/provider-configs/models') {
        // 上游探测成功 → 返回真实模型（与静态候选不同名，便于区分来源）
        return { ok: true, models: ['deepseek-probe-only'] };
      }
      return { ok: true };
    });
    await renderLoaded();

    await user.click(screen.getByTestId('setup-to-step2'));
    await user.click(await screen.findByTestId('setup-chat-select'));

    // 探测结果必须生效（null base_url 未中断循环）
    expect(
      await screen.findByRole('option', { name: /deepseek-probe-only/ }),
    ).toBeInTheDocument();
  });

  it('D10：探测有结果时下拉只含探测结果，不混入静态候选的 provider_default 项', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (url: string) => {
      if (url === '/api/v1/provider-configs') {
        // 信封带一个 provider_default 静态候选（实测 v4-flash 的来源）
        return {
          items: PROVIDERS_NO_MODELS,
          total: PROVIDERS_NO_MODELS.length,
          chat_model_source: {
            project_models: [],
            default_model: 'deepseek/deepseek-v4-flash',
          },
        };
      }
      if (url === '/api/v1/provider-configs/models') {
        return { ok: true, models: ['probe-only-model'] };
      }
      return { ok: true };
    });
    await renderLoaded();

    await user.click(screen.getByTestId('setup-to-step2'));
    await user.click(await screen.findByTestId('setup-chat-select'));

    // 探测结果在
    expect(await screen.findByRole('option', { name: /probe-only-model/ })).toBeInTheDocument();
    // 静态 provider_default 项**不在**（探测有结果时不得混入）
    expect(
      screen.queryByRole('option', { name: /deepseek-v4-flash/ }),
    ).not.toBeInTheDocument();
  });

  // ── 缺陷 B（用户复验 2026-09-14）：选中的模型未落 models[] ──────────────
  // 根因：handleTestConnection 只 PATCH default_model，从不写 models[]
  // → 设置页「模型表」读 models[] → 空 → 用户以为没生效、需手动再加。
  it('D11：步骤 2 测试连接成功后，选中模型进入该 provider 的 models[]（设置页可见）', async () => {
    const user = userEvent.setup();
    const addModel = vi.fn().mockResolvedValue(undefined);
    // spy useModelsStore.addModel（落 models[] 的既有 action）
    const originalAddModel = useModelsStore.getState().addModel;
    useModelsStore.setState({ addModel });

    const patchBodies: Array<Record<string, unknown>> = [];
    apiFetchMock.mockImplementation(
      async (url: string, init?: { method?: string; body?: unknown }) => {
        if (url === '/api/v1/provider-configs') {
          return { items: PROVIDERS, total: PROVIDERS.length };
        }
        if (url === '/api/v1/provider-configs/models') {
          return { ok: true, models: ['deepseek-chat'] };
        }
        if (url === '/api/v1/settings/llm/test') {
          return { ok: true };
        }
        if (/^\/api\/v1\/provider-configs\/\d+$/.test(url)) {
          patchBodies.push((init?.body ?? {}) as Record<string, unknown>);
          return { ...PROVIDERS[0] };
        }
        return { ok: true };
      },
    );
    await renderLoaded();

    await user.click(screen.getByTestId('setup-to-step2'));
    await user.click(await screen.findByTestId('setup-chat-select'));
    await user.click(await screen.findByRole('option', { name: 'deepseek/deepseek-chat' }));
    await user.click(screen.getByTestId('setup-test-conn'));

    // 既要写 default_model，也要把选中模型落进 models[]
    await waitFor(() => {
      const wrote = patchBodies.some((b) => 'models' in b) || addModel.mock.calls.length > 0;
      expect(wrote).toBe(true);
    });
    if (addModel.mock.calls.length > 0) {
      expect(addModel).toHaveBeenCalledWith(
        expect.any(Number),
        expect.objectContaining({ type: 'chat' }),
      );
    }
    useModelsStore.setState({ addModel: originalAddModel });
  });
});
