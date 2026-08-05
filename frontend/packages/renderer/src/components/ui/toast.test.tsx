/**
 * ToastHost 组件测试（Issue #105，spec §6.2①：三态 / aria-live / 关闭）
 *
 * ⚠️ Coverage-Gap 补测（非 RED）：实现已存在（src/components/ui/toast.tsx），
 * 测试直接挂载真实组件 + useToastStore.setState 播种，预期直接全绿。
 *
 * 覆盖面：
 * - 空态：toasts=[] → 渲染 aria-live="polite" 容器、无 role=status
 * - 三态：ok/err/warn 各一条 → 三条 role=status + 各自 message 文案
 * - 关闭：每条 toast 有关闭按钮（aria-label=t('toast.close')「关闭」）
 *   → 点击 → dismissToast 从 store 移除
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ToastHost } from './toast';
import { useToastStore } from '../../stores/toast';
import { useThemeStore } from '../../stores/theme';
import type { Toast } from '../../stores/toast';

function seed(toasts: Toast[]) {
  useToastStore.setState({ toasts });
}

beforeEach(() => {
  useToastStore.setState({ toasts: [] });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('ToastHost — 空态（aria-live 容器）', () => {
  it('toasts 为空：渲染 aria-live="polite" 容器、无 role=status', () => {
    const { container } = render(<ToastHost />);
    const live = container.querySelector('[aria-live="polite"]');
    expect(live).not.toBeNull();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('ToastHost — 三态渲染', () => {
  it('ok/err/warn 各一条 → 三条 role=status + 各自 message 文案', () => {
    seed([
      { id: 't-ok', type: 'ok', message: '已保存' },
      { id: 't-err', type: 'err', message: '保存失败' },
      { id: 't-warn', type: 'warn', message: '字数超出限制' },
    ]);
    render(<ToastHost />);

    const statuses = screen.getAllByRole('status');
    expect(statuses).toHaveLength(3);
    expect(screen.getByText('已保存')).toBeInTheDocument();
    expect(screen.getByText('保存失败')).toBeInTheDocument();
    expect(screen.getByText('字数超出限制')).toBeInTheDocument();
  });
});

describe('ToastHost — 关闭按钮', () => {
  it('每条 toast 有 aria-label=「关闭」按钮；点击 → dismissToast 从 store 移除', async () => {
    const user = userEvent.setup();
    seed([
      { id: 't-1', type: 'ok', message: '第一条' },
      { id: 't-2', type: 'err', message: '第二条' },
    ]);
    render(<ToastHost />);

    const closeButtons = screen.getAllByRole('button', { name: '关闭' });
    expect(closeButtons).toHaveLength(2);

    await user.click(closeButtons[0]);

    // store 中移除 + DOM 同步移除
    expect(useToastStore.getState().toasts.map((t) => t.message)).toEqual(['第二条']);
    expect(screen.queryByText('第一条')).not.toBeInTheDocument();
    expect(screen.getByText('第二条')).toBeInTheDocument();
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });
});
