/**
 * #965 F59-M4 推理档位 → 全局默认思考档位卡片（GlobalReasoningEffortCard）RED 契约。
 *
 * RED 预期：src/components/GlobalReasoningEffortCard.tsx 不存在 → import './GlobalReasoningEffortCard'
 * 失败 → 整个文件 collection error 1 个（非逐用例 FAIL；GREEN 后本文件全量转绿）。
 *
 * 契约（GREEN 实现，本文件只写测试不改 src/；镜像 components/GlobalDefaultModelCard.test.tsx）：
 * - 数据面：fetchSettings()（GET /api/v1/settings）读 default_reasoning_effort；
 *   patchSettings({ default_reasoning_effort: v })（PATCH /api/v1/settings）。
 * - global-reasoning-effort-select：Radix Select trigger，label=t('agent.thinking.globalLabel')，同七档。
 * - 保存成功 pushToast('ok', t('toast.saved'))，失败 pushToast('err', t('toast.saveFailed'))。
 *
 * i18n（F4 唯一口径，GREEN 补 zh.ts / en.ts）：
 *   agent.thinking.globalLabel=全局默认思考强度 / medium=中 / high=高
 *   toast.saved=已保存 / toast.saveFailed=保存失败
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GlobalReasoningEffortCard } from './GlobalReasoningEffortCard';
import { useToastStore } from '../stores/toast';

// client.ts 模块内函数（fetchSettings/patchSettings）经 importOriginal 展开后函数体仍引用
// 模块局部 apiFetch——因此同 theme.test.ts 模式：vi.hoisted 直接替换这两个函数为 mock。
const { fetchSettingsMock, patchSettingsMock } = vi.hoisted(() => ({
  fetchSettingsMock: vi.fn(),
  patchSettingsMock: vi.fn(),
}));

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, fetchSettings: fetchSettingsMock, patchSettings: patchSettingsMock };
});

/** GET /api/v1/settings 响应：default_reasoning_effort='medium'（F59 新键；AppSettings 未定义此字段，仅运行时透传） */
const SETTINGS_MEDIUM = { default_reasoning_effort: 'medium' };

beforeEach(() => {
  fetchSettingsMock.mockReset();
  patchSettingsMock.mockReset();
});

function renderCard() {
  return render(<GlobalReasoningEffortCard />);
}

describe('#965 F59-M4 — 全局默认思考档位卡片（GlobalReasoningEffortCard）', () => {
  it('渲染契约：fetchSettings 返回 medium → global-reasoning-effort-select 出现且显示「中」（t(agent.thinking.medium)）', async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS_MEDIUM);
    renderCard();

    // #793 纪律：UI 必须出现断言
    expect(await screen.findByTestId('global-reasoning-effort-select')).toBeInTheDocument();
    expect(screen.getByTestId('global-reasoning-effort-select')).toHaveTextContent('中');
  });

  it('变更：选择「高」→ patchSettings({ default_reasoning_effort: "high" }) + toast ok「已保存」', async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS_MEDIUM);
    patchSettingsMock.mockResolvedValue({ ...SETTINGS_MEDIUM, default_reasoning_effort: 'high' });
    const user = userEvent.setup();
    renderCard();

    await user.click(await screen.findByTestId('global-reasoning-effort-select'));
    await user.click(await screen.findByRole('option', { name: '高' }));

    await waitFor(() => {
      expect(patchSettingsMock).toHaveBeenCalledWith({ default_reasoning_effort: 'high' });
    });
    // 成功 → toast ok「已保存」（zh 默认渲染）
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts[toasts.length - 1]).toMatchObject({ type: 'ok', message: '已保存' });
    });
  });

  it('失败：patchSettings reject → toast err「保存失败」', async () => {
    fetchSettingsMock.mockResolvedValue(SETTINGS_MEDIUM);
    patchSettingsMock.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();
    renderCard();

    await user.click(await screen.findByTestId('global-reasoning-effort-select'));
    await user.click(await screen.findByRole('option', { name: '高' }));

    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts[toasts.length - 1]).toMatchObject({ type: 'err', message: '保存失败' });
    });
  });
});
