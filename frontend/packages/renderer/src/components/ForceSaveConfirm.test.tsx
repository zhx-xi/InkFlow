/**
 * #936 C 项前端契约：探测门禁 422 → 强制保存确认框（GUI 逃生门）。
 *
 * 背景：后端保存前对「新增/改动模型条目」做 type-aware 最小探测，失败 → 422
 * （detail 含「如需强制保存请使用 force=true」）。GUI 主路径必须给显式逃生门：
 * 默认必过（#929 拍板②「不静默」），失败时不静默吞错 → 提示 + 可选强制保存。
 *
 * 契约：
 * N1. 门禁拒绝（422 + detail 含 force 提示）→ 弹 `probe-gate-confirm`，**不落库**
 * N2. 确认「仍然强制保存」→ 以 `?force=true` 重发 → 成功 → 关闭
 * N3. 取消 → 保留草稿、不落库、弹窗关闭
 * N4. 非门禁错误（如 500 / 422 无 force 提示）→ 走普通失败提示，**不弹确认框**
 * N5. `isForceableProbeRejection` 判据：仅 422 + force 提示为真（防误判）
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AddModelDialog } from './AddModelDialog';
import { isForceableProbeRejection } from './probeGate';
import { ApiError } from '../api/client';
import type { ProviderConfig } from '../stores/models';

const PROVIDER: ProviderConfig = {
  id: 2,
  name: 'deepseek',
  base_url: 'https://api.deepseek.com/v1',
  default_model: 'deepseek-chat',
  models: [],
  key_saved: false,
  max_retries: 3,
  timeout: 120,
  created_at: '2026-09-10T00:00:00Z',
  updated_at: '2026-09-10T00:00:00Z',
};

const GATE_DETAIL =
  '模型 deepseek/deepseek-chat 缺少 API Key，无法探测；如需强制保存请使用 force=true';

function renderDialog(onAdd: ReturnType<typeof vi.fn>) {
  return render(
    <AddModelDialog
      open
      providers={[PROVIDER]}
      onOpenChange={vi.fn()}
      onAdd={onAdd}
      onDone={vi.fn()}
    />,
  );
}

/** 填一行模型草稿（模型 ID 必填，否则 handleSave 直接 return） */
async function fillModelRow(modelId = 'deepseek-chat') {
  const user = userEvent.setup();
  const input = screen.getByLabelText(/模型 ID 1/);
  await user.type(input, modelId);
  return user;
}

describe('isForceableProbeRejection 判据', () => {
  it('422 + detail 含 force 提示 → true（门禁拒绝）', () => {
    expect(isForceableProbeRejection(new ApiError(422, GATE_DETAIL))).toBe(true);
  });

  it('422 但不含 force 提示 → false（普通校验失败，不得误判）', () => {
    expect(isForceableProbeRejection(new ApiError(422, 'name 不能为空'))).toBe(false);
  });

  it('非 422（如 500）含 force 字样 → false（只认状态码 422）', () => {
    expect(isForceableProbeRejection(new ApiError(500, 'force=true'))).toBe(false);
  });

  it('非 Error 值 → false（防御）', () => {
    expect(isForceableProbeRejection('boom')).toBe(false);
    expect(isForceableProbeRejection(null)).toBe(false);
  });
});

describe('AddModelDialog 探测门禁确认（#936 C）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('N1: 门禁 422 → 弹确认框且不关闭主弹窗', async () => {
    const onAdd = vi.fn().mockRejectedValue(new ApiError(422, GATE_DETAIL));
    renderDialog(onAdd);
    const user = await fillModelRow();
    await user.click(screen.getByRole('button', { name: '保存' }));

    expect(await screen.findByTestId('probe-gate-confirm')).toBeInTheDocument();
    expect(screen.getByTestId('probe-gate-detail')).toHaveTextContent('deepseek-chat');
    // 主弹窗仍在（草稿保留）
    expect(screen.getByTestId('add-model-dialog')).toBeInTheDocument();
    // 首次调用未带 force
    expect(onAdd.mock.calls[0][2]).toBeUndefined();
  });

  it('N2: 确认强制保存 → 以 force=true 重发并关闭', async () => {
    const onAdd = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(422, GATE_DETAIL))
      .mockResolvedValueOnce(undefined);
    const onOpenChange = vi.fn();
    const onDone = vi.fn();
    render(
      <AddModelDialog
        open
        providers={[PROVIDER]}
        onOpenChange={onOpenChange}
        onAdd={onAdd}
        onDone={onDone}
      />,
    );
    const user = await fillModelRow();
    await user.click(screen.getByRole('button', { name: '保存' }));
    await user.click(await screen.findByTestId('probe-gate-force'));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    // 第二次调用带 force=true
    expect(onAdd.mock.calls[1][2]).toEqual({ force: true });
    expect(onDone).toHaveBeenCalledWith({ succeeded: 1, failed: 0, errors: [] });
  });

  it('N3: 取消 → 不落库（无 force 重发）+ 确认框关闭', async () => {
    const onAdd = vi.fn().mockRejectedValue(new ApiError(422, GATE_DETAIL));
    renderDialog(onAdd);
    const user = await fillModelRow();
    await user.click(screen.getByRole('button', { name: '保存' }));
    await user.click(await screen.findByTestId('probe-gate-cancel'));

    await waitFor(() =>
      expect(screen.queryByTestId('probe-gate-confirm')).not.toBeInTheDocument(),
    );
    // 只有首次（无 force）调用，取消不重发
    expect(onAdd).toHaveBeenCalledTimes(1);
    // 主弹窗仍在（草稿保留可重试）
    expect(screen.getByTestId('add-model-dialog')).toBeInTheDocument();
  });

  it('N4: 非门禁错误（500）→ 不弹确认框，走普通失败路径', async () => {
    const onAdd = vi.fn().mockRejectedValue(new ApiError(500, '内部错误'));
    renderDialog(onAdd);
    const user = await fillModelRow();
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('probe-gate-confirm')).not.toBeInTheDocument();
  });
});
