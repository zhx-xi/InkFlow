/**
 * #526 RED 契约：设置→模型 全局默认模型卡片（GlobalDefaultModelCard）。
 *
 * 契约（GREEN 实现，本文件只写测试不改 src/）：
 * - global-model-select：chat 模型扁平化 Select trigger（selectChatModelOptions，
 *   选项 value/label = `${provider.name}/${model.id}`，如 deepseek/deepseek-v4-flash）
 * - 当前值 = GET /api/v1/config 的 default_model（api/config.ts 新导出 fetchConfig）
 * - 切换模型 → 保存调 patchConfig(llmDefaultModel)（PATCH /api/v1/config {llm_default_model}）
 *   → 成功 toast ok「已保存」/ 失败 toast err「保存失败」（useToastStore 真断言）
 *
 * Mock 形态：vi.mock('../api/config')（fetchConfig/patchConfig）；真 useModelsStore.setState
 * 注入 providers（deepseek 2 chat + zhipu 1 chat）。
 *
 * RED 预期：组件不存在 → import './GlobalDefaultModelCard' 失败 → 整个文件 collection error 1 个
 * （非逐用例 FAIL）；记录形态即可。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GlobalDefaultModelCard } from './GlobalDefaultModelCard';
import { fetchConfig, patchConfig } from '../api/config';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/config', () => ({
  fetchConfig: vi.fn(),
  patchConfig: vi.fn(),
}));

const fetchConfigMock = vi.mocked(fetchConfig);
const patchConfigMock = vi.mocked(patchConfig);

/** 注册表 fixtures：deepseek 2 chat（deepseek-v4-flash + deepseek-chat）；zhipu 1 chat（glm-4） */
const PROVIDERS: ProviderConfig[] = [
  {
    id: 1, name: 'deepseek', base_url: 'https://api.deepseek.com', default_model: 'deepseek-v4-flash',
    models: [
      { id: 'deepseek-v4-flash', type: 'chat', roles: ['main'] },
      { id: 'deepseek-chat', type: 'chat', roles: ['architect'] },
    ],
    key_saved: true, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
  {
    id: 2, name: 'zhipu', base_url: 'https://open.bigmodel.cn/api/paas/v4', default_model: 'glm-4',
    models: [{ id: 'glm-4', type: 'chat', roles: ['writer'] }],
    key_saved: true, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
];

/** GET /api/v1/config 响应（#526 契约：default_model 为当前生效全局默认模型） */
const CONFIG_DEFAULT = { default_model: 'deepseek/deepseek-v4-flash' };

beforeEach(() => {
  fetchConfigMock.mockReset();
  patchConfigMock.mockReset();
  useModelsStore.setState({ providers: PROVIDERS });
  useToastStore.setState({ toasts: [] });
});

function renderCard() {
  return render(<GlobalDefaultModelCard />);
}

describe('GlobalDefaultModelCard — 全局默认模型（#526）', () => {
  it('test_renders_select_with_chat_options：Select 存在，选项含 chat 模型扁平化（provider/model）', async () => {
    fetchConfigMock.mockResolvedValue(CONFIG_DEFAULT);
    const user = userEvent.setup();
    renderCard();

    const trigger = await screen.findByTestId('global-model-select');
    expect(trigger).toBeInTheDocument();
    await user.click(trigger);
    // selectChatModelOptions 扁平化（chat 模型才入选项）
    expect(await screen.findByRole('option', { name: 'deepseek/deepseek-v4-flash' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'deepseek/deepseek-chat' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'zhipu/glm-4' })).toBeInTheDocument();
  });

  it('test_current_value_from_config：当前值 = fetchConfig 返回的 default_model', async () => {
    fetchConfigMock.mockResolvedValue(CONFIG_DEFAULT);
    renderCard();
    // Radix SelectValue 渲染选中项文本到 trigger 内
    expect(await screen.findByTestId('global-model-select')).toHaveTextContent('deepseek/deepseek-v4-flash');
  });

  it('test_save_calls_patch_config：切换 → patchConfig(llmDefaultModel) + toast ok「已保存」', async () => {
    fetchConfigMock.mockResolvedValue(CONFIG_DEFAULT);
    patchConfigMock.mockResolvedValue({ ok: true });
    const user = userEvent.setup();
    renderCard();
    await screen.findByTestId('global-model-select');

    await user.click(screen.getByTestId('global-model-select'));
    await user.click(await screen.findByRole('option', { name: 'deepseek/deepseek-chat' }));

    // 保存调用：PATCH /api/v1/config {llm_default_model}
    await waitFor(() => {
      expect(patchConfigMock).toHaveBeenCalledWith('deepseek/deepseek-chat');
    });
    // 成功 → toast ok「已保存」（zh 默认渲染）
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts[toasts.length - 1]).toMatchObject({ type: 'ok', message: '已保存' });
    });
  });

  it('test_save_failure_toast：patchConfig reject → toast err「保存失败」', async () => {
    fetchConfigMock.mockResolvedValue(CONFIG_DEFAULT);
    patchConfigMock.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();
    renderCard();
    await screen.findByTestId('global-model-select');

    await user.click(screen.getByTestId('global-model-select'));
    await user.click(await screen.findByRole('option', { name: 'deepseek/deepseek-chat' }));

    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts[toasts.length - 1]).toMatchObject({ type: 'err', message: '保存失败' });
    });
  });
});
