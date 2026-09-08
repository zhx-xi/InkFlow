/**
 * #965 F59-M4 推理档位 → provider 模型列表「思考」徽标 + 手动覆盖入口（ModelsPanel）RED 契约。
 *
 * RED 预期：src/components/ModelsPanel.tsx 已存在（既有 #106 面板），但尚无「思考」列/徽标/三态 Select
 * → 本文件各用例均 FAIL 于 `getByTestId('model-reasoning-*')` element-missing（缺功能 RED），
 * 非 collection error。仅当 GREEN 实现 §B F3（ModelsPanel + stores/models.ts setModelReasoning + F4 i18n）后转绿。
 *
 * 契约（GREEN 必须匹配）：
 * - 模型表新增「思考」列（t('m.table.reasoning')）：
 *   - m.supports_reasoning === true → 徽标 data-testid="model-reasoning-badge-<id>" 文案 t('m.supportsReasoning')。
 *   - m.supports_reasoning_manual != null → 角标 data-testid="model-reasoning-manual-<id>" 文案 t('m.reasoningManual')。
 *   - 每行三态 Select data-testid="model-reasoning-<id>"：值域 'auto'|'true'|'false'（初始 = manual==null?'auto':String(manual)）；
 *     选项文案 t('m.reasoningAuto')/t('m.reasoningForceOn')/t('m.reasoningForceOff')；
 *     变更 → setModelReasoning(pid, mid, value==='auto'?null:value==='true')。
 * - store：setModelReasoning(providerId, modelId, value) → PATCH /api/v1/provider-configs/{id}
 *   body { models: 全量替换（目标模型 supports_reasoning=value，其余原样）}。
 *
 * i18n（F4 唯一口径，GREEN 补 zh.ts / en.ts）：
 *   m.table.reasoning=思考 / m.supportsReasoning=支持思考 / m.reasoningManual=手动
 *   m.reasoningAuto=自动探测 / m.reasoningForceOn=强制支持 / m.reasoningForceOff=强制不支持
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ModelsPanel } from './ModelsPanel';
import { apiFetch } from '../api/client';
import { useModelsStore, type ProviderConfig, type ProviderModel } from '../stores/models';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** F59 新增模型级字段（stores/models.ts ProviderModel 将扩展；测试经 cast 传递运行时形态） */
interface ReasoningProviderModel extends ProviderModel {
  supports_reasoning?: boolean | null;
  supports_reasoning_manual?: boolean | null;
}
interface ReasoningProviderConfig extends ProviderConfig {
  models: ReasoningProviderModel[];
}

/**
 * 契约 fixture：
 * - m1：supports_reasoning=true（支持思考）+ supports_reasoning_manual=true（手动覆盖 → 「手动」角标 + 三态初始=强制支持）。
 * - m2：supports_reasoning=false（不支持：无徽标、无手动角标、三态初始=自动探测）。
 */
const PROVIDERS: ReasoningProviderConfig[] = [
  {
    id: 1, name: 'deepseek', base_url: 'https://api.deepseek.com', default_model: 'm1',
    models: [
      {
        id: 'm1', type: 'chat', roles: [],
        supports_reasoning: true, supports_reasoning_manual: true,
      },
      {
        id: 'm2', type: 'chat', roles: [],
        supports_reasoning: false, supports_reasoning_manual: null,
      },
    ],
    key_saved: true, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  useModelsStore.setState({
    providers: [],
    loading: false,
    error: null,
    selectedModelId: null,
    roleBinding: { main: '', architect: '', writer: '', auditor: '', reviser: '', embedding: '' },
  });
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    if (path === '/api/v1/provider-configs') {
      return { items: PROVIDERS, total: 1, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/provider-configs/1' && init?.method === 'PATCH') {
      return { ...PROVIDERS[0], models: (init.body as { models: ReasoningProviderModel[] }).models };
    }
    return { ok: true };
  });
});

async function renderPanelAndSettle(): Promise<void> {
  render(<ModelsPanel />);
  await waitFor(() => expect(useModelsStore.getState().loading).toBe(false));
}

describe('#965 F59-M4 — 模型表「思考」徽标 + 手动覆盖角标（ModelsPanel）', () => {
  it('m1 支持思考：model-reasoning-badge-m1（支持思考）+ 手动角标 model-reasoning-manual-m1（手动）', async () => {
    await renderPanelAndSettle();

    // #793 纪律：UI 必须出现断言（当前无「思考」列 → element-missing FAIL）
    expect(screen.getByTestId('model-reasoning-badge-m1')).toHaveTextContent('支持思考');
    expect(screen.getByTestId('model-reasoning-manual-m1')).toHaveTextContent('手动');
  });

  it('m2 不支持思考：model-reasoning-m2 三态 Select 出现（自动探测）但无 badge、无 manual 角标', async () => {
    await renderPanelAndSettle();

    // #793 纪律：m2 行也须渲染三态 Select（初值=auto → 显示 t('m.reasoningAuto')=「自动探测」；
    // 当前无「思考」列 → element-missing FAIL，禁止仅有负向断言的伪 PASS）
    const sel = screen.getByTestId('model-reasoning-m2');
    expect(sel).toBeInTheDocument();
    expect(sel).toHaveTextContent('自动探测');
    // 无 badge / 无手动角标（supports_reasoning=false）
    expect(screen.queryByTestId('model-reasoning-badge-m2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('model-reasoning-manual-m2')).not.toBeInTheDocument();
  });

  it('三态 Select 初值：m1 手动值 true → model-reasoning-m1 显示「强制支持」', async () => {
    await renderPanelAndSettle();

    const sel = screen.getByTestId('model-reasoning-m1');
    expect(sel).toBeInTheDocument();
    // manual=true → value='true' → 显示 t('m.reasoningForceOn')=「强制支持」
    expect(sel).toHaveTextContent('强制支持');
  });

  it('把 m2 切到「强制支持」→ PATCH body.models 全量替换且 m2.supports_reasoning=true、m1 原样保留', async () => {
    const user = userEvent.setup();
    await renderPanelAndSettle();

    await user.click(screen.getByTestId('model-reasoning-m2'));
    await user.click(await screen.findByRole('option', { name: '强制支持' }));

    await waitFor(() => {
      const patch = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/provider-configs/1' && c[1]?.method === 'PATCH',
      );
      expect(patch).toBeTruthy();
      const models = (patch![1]!.body as { models: ReasoningProviderModel[] }).models;
      // 全量替换（m1 + m2，共 2 条，不丢模型）
      expect(models).toHaveLength(2);
      const m1 = models.find((m) => m.id === 'm1');
      const m2 = models.find((m) => m.id === 'm2');
      expect(m1).toEqual({ id: 'm1', type: 'chat', roles: [], supports_reasoning: true, supports_reasoning_manual: true });
      expect(m2?.supports_reasoning).toBe(true);
    });
  });
});
