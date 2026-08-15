/**
 * AppLayout 启动门控集成契约（Issue #384 层 1，2026-08-16）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 App.tsx AppLayout 门控条件渲染必须匹配：
 *
 * AppLayout 根部读 useKernelStore：`!booted` → 渲染 <BootGate />（启动封面）；`booted` → 主 UI。
 * 三态（plan D1）：
 * - booting：渲染 BootGate 封面（data-testid="boot-gate"），主 UI（app-nav）不渲染
 * - ready：渲染主 UI（app-nav 存在），封面消失
 * - failed：渲染 BootGate 错误+重试（「内核连接失败」），主 UI 不渲染
 *
 * 轮询生命周期归 AppLayout 管：挂载 startPolling / 卸载 stopPolling（useEffect 依赖 []）。
 * RED 预期：GREEN 前 App.tsx 无门控（挂载即渲染主 UI + 本地 kernelOnline state）→
 * boot-gate 缺失（element-missing）；ready/failed 用例因无 BootGate/无 store 而 FAIL。
 *
 * ⚠️ 门控是异步的：render <App /> 后初始 booting → 封面，checkHealth 异步 resolve 才转 ready。
 * 本文件**不预设 ready**（走真实 booting 流程），故断言必须 findByXxx / waitFor（非同步 getBy）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { App } from './App';
import { apiFetch } from './api/client';
import { useProjectStore } from './stores/project';
import { useChapterStore } from './stores/chapter';
import { useThemeStore } from './stores/theme';
import { useKernelStore } from './stores/kernel';

vi.mock('./api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  window.location.hash = '';
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useChapterStore.setState({ volumes: [], chapters: [], currentChapterId: null, content: '', loading: false, error: null });
  useKernelStore.setState({ status: 'booting', booted: false });
});

afterEach(() => {
  useKernelStore.getState().stopPolling();
});

describe('AppLayout 启动门控（#384）', () => {
  it('booting → 封面（boot-gate）+ 主 UI 不渲染（/health 永不 resolve）', () => {
    apiFetchMock.mockImplementation((path: string) => {
      if (path === '/health') return new Promise(() => {});
      return Promise.resolve({ items: [], total: 0, offset: 0, limit: 50 });
    });
    render(<App />);
    // booting 是初始态，封面同步渲染
    expect(screen.getByTestId('boot-gate')).toBeInTheDocument();
    expect(screen.queryByTestId('app-nav')).not.toBeInTheDocument();
  });

  it('ready → 主 UI 渲染（app-nav）+ 封面消失（/health 成功）', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/health') return { ok: true };
      if (path === '/api/v1/projects') {
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/settings') {
        return { theme: 'paper', bg: 'default', lang: 'zh', font: 'sans', close_behavior: 'tray', tray_hint_dismissed: false };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    render(<App />);
    await screen.findByTestId('app-nav');
    expect(screen.queryByTestId('boot-gate')).not.toBeInTheDocument();
  });

  it('failed → 封面错误+重试（「内核连接失败」）+ 主 UI 不渲染（/health 失败）', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/health') throw new Error('kernel unreachable');
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    render(<App />);
    await screen.findByText('内核连接失败');
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
    expect(screen.queryByTestId('app-nav')).not.toBeInTheDocument();
  });
});
