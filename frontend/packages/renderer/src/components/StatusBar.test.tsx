/**
 * 状态栏空值契约（Issue #98 RED 阶段，spec §5.2.7 差距 #8；#384 内核状态 store 化）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 StatusBar 必须匹配（行为断言，不测样式）：
 *
 * - model 空字符串 '' 与 null 统一显示「未设置」（#520 拍板：非 '—'；i18n sb.modelUnset）
 *   - '' 时渲染「模型: 未设置」，不得渲染「模型: 」空值残留
 * - 内核连接项状态值：从 useKernelStore 读（#384 单一真相源）——**移除 kernelConnected prop**
 *   - status='ready' → t('sb.kernel')「内核已连接」
 *   - status='failed'（或 booting）→ t('sb.kernelOffline')「内核未就绪」
 *   （#98 假契约「缺省 true 恒显已连接」废除——writing.tsx L234 未传 prop 导致假状态，改为 store 读真实状态）
 * - StatusBar 根容器 data-testid="statusbar"（供 E2E scope，消除 strict mode violation）
 * - 正常 model 值渲染「模型: {model}」不变（回归）
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusBar } from './StatusBar';
import { useThemeStore } from '../stores/theme';
import { useKernelStore } from '../stores/kernel';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useKernelStore.setState({ status: 'booting', booted: false });
});

afterEach(() => {
  useKernelStore.getState().stopPolling();
});

describe('StatusBar — 空值契约（#98 §5.2.7）', () => {
  it('model 空字符串 → 显示「未设置」（#520，非「—」）', () => {
    render(<StatusBar model="" wordCount={0} savedAt={null} />);
    expect(screen.getByText('模型: 未设置')).toBeInTheDocument();
    expect(screen.queryByText('模型: —')).not.toBeInTheDocument();
  });

  it('model null → 显示「未设置」（#520，非「—」）', () => {
    render(<StatusBar model={null} wordCount={0} savedAt={null} />);
    expect(screen.getByText('模型: 未设置')).toBeInTheDocument();
    expect(screen.queryByText('模型: —')).not.toBeInTheDocument();
  });

  it('model 正常值 → 显示「模型: {model}」', () => {
    render(<StatusBar model="gpt-4o" wordCount={1234} savedAt={null} />);
    expect(screen.getByText('模型: gpt-4o')).toBeInTheDocument();
    expect(screen.getByText('字数: 1,234')).toBeInTheDocument();
  });

  it('内核连接项状态值：store status=ready → 「内核已连接」', () => {
    useKernelStore.setState({ status: 'ready', booted: true });
    render(<StatusBar model={null} wordCount={0} savedAt={null} />);
    expect(screen.getByText('内核已连接')).toBeInTheDocument();
  });

  it('内核连接项状态值：store status=failed → 「内核未就绪」（不显示已连接）', () => {
    useKernelStore.setState({ status: 'failed', booted: true });
    render(<StatusBar model={null} wordCount={0} savedAt={null} />);
    expect(screen.getByText('内核未就绪')).toBeInTheDocument();
    expect(screen.queryByText('内核已连接')).not.toBeInTheDocument();
  });
});
