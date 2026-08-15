/**
 * BootGate 启动门控封面契约（Issue #384 层 1，2026-08-16）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 `src/components/BootGate.tsx` 必须匹配：
 *
 * BootGate = 门控封面（AppLayout 在 !booted 时渲染，读 useKernelStore 的 status/retry）。
 * 三态中 BootGate 只渲染 booting/failed 两态（ready 由 AppLayout 转主 UI，不渲染 BootGate）：
 *
 * - 根容器 data-testid="boot-gate"
 * - 封面含装饰性 logo <img>（alt="" aria-hidden="true"，复用 AppNav 品牌三主题变体模式）
 * - booting 态：t('gate.booting')「正在启动内核…」文案 + 加载指示（spinner），**无重试按钮**
 * - failed 态：t('gate.failed')「内核连接失败」文案 + 重试按钮（role=button，文案 t('lib.retry')「重试」）
 * - 点击重试 → useKernelStore.retry()（status 同步置 booting）
 *
 * i18n 新 key 由 GREEN 补 zh.ts/en.ts：gate.booting / gate.failed；重试按钮复用 lib.retry。
 * 视觉克制（ui-design-taste）：无复杂动画，spinner 用 CSS animate-spin 简单旋转即可。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BootGate } from './BootGate';
import { useKernelStore } from '../stores/kernel';
import { useThemeStore } from '../stores/theme';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useKernelStore.setState({ status: 'booting', booted: false });
  // #384：pending mock 让 retry 的 checkHealth 挂起（status 稳定 booting，防 user.click await flush 时序竞争）
  apiFetchMock.mockImplementation(() => new Promise(() => {}));
});

afterEach(() => {
  useKernelStore.getState().stopPolling();
});

describe('BootGate — 启动门控封面（#384）', () => {
  it('booting → 封面容器 + logo + 加载文案，无重试按钮', () => {
    render(<BootGate />);
    const gate = screen.getByTestId('boot-gate');
    expect(gate).toBeInTheDocument();
    // 装饰性 logo（alt="" aria-hidden，语义由文案承载）
    const logo = gate.querySelector('img');
    expect(logo).not.toBeNull();
    expect(logo).toHaveAttribute('aria-hidden', 'true');
    // 加载文案
    expect(screen.getByText('正在启动内核…')).toBeInTheDocument();
    // 无重试按钮
    expect(screen.queryByRole('button', { name: '重试' })).not.toBeInTheDocument();
  });

  it('failed → 错误文案 + 重试按钮', () => {
    useKernelStore.setState({ status: 'failed', booted: false });
    render(<BootGate />);
    expect(screen.getByText('内核连接失败')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });

  it('点击重试 → retry()（status 同步置 booting）', async () => {
    const user = userEvent.setup();
    useKernelStore.setState({ status: 'failed', booted: false });
    render(<BootGate />);
    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(useKernelStore.getState().status).toBe('booting');
  });
});
