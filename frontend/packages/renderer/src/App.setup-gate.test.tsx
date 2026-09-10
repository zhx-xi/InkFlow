/**
 * F60 AppLayout 首启引导门控集成契约（#934 N1/N3/N4）。
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 App.tsx AppLayout 必须匹配：
 *
 * AppLayout 门控顺序：`!booted` → BootGate → **`readiness==null || !ready` → SetupGuide**
 * → 主 UI（app-nav）。
 * - N1：内核就绪 + 模型未就绪 → setup-guide 渲染，app-nav 不渲染（无法进入写作主流程）
 * - N3：内核就绪 + 已有有效配置（ready=true）→ 不弹引导（零打扰），app-nav 渲染
 * - N4：引导完成（readiness 复核转 ready）→ 引导卸载，app-nav 渲染
 *
 * 判据来源：useModelReadinessStore（App 挂载后经 GET /settings/model-readiness 查询）。
 * RED 预期：GREEN 前 App.tsx 无 readiness 门控 → N1 用例 FAIL（setup-guide 缺失）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { App } from './App';
import { apiFetch } from './api/client';
import { useProjectStore } from './stores/project';
import { useChapterStore } from './stores/chapter';
import { useThemeStore } from './stores/theme';
import { useKernelStore } from './stores/kernel';
import { useModelReadinessStore } from './stores/modelReadiness';

vi.mock('./api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const READY = {
  ready: true,
  has_chat_model: true,
  has_embedding_model: true,
  reason: 'ready' as const,
};
const NOT_READY = {
  ready: false,
  has_chat_model: false,
  has_embedding_model: false,
  reason: 'no_provider' as const,
};

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  window.location.hash = '';
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useChapterStore.setState({
    volumes: [],
    chapters: [],
    currentChapterId: null,
    content: '',
    loading: false,
    error: null,
  });
  // 内核已就绪（门控前置：本文件测「模型就绪」门控，非内核门控）
  useKernelStore.setState({ status: 'ready', booted: true, healthFailures: 0 });
  useModelReadinessStore.setState({ readiness: null, loading: false });

  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/settings/model-readiness') return NOT_READY;
    if (path === '/api/v1/settings') {
      return {
        theme: 'paper',
        bg: 'default',
        lang: 'zh',
        font: 'sans',
        close_behavior: 'tray',
        tray_hint_dismissed: false,
      };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  useKernelStore.getState().stopPolling();
});

describe('AppLayout 首启引导门控（#934 N1/N3/N4）', () => {
  it('N1：模型未就绪 → 渲染 setup-guide + 主 UI 不渲染', async () => {
    render(<App />);
    await screen.findByTestId('setup-guide');
    expect(screen.queryByTestId('app-nav')).not.toBeInTheDocument();
  });

  it('N3：已有有效配置（端点返回 ready）→ 不弹引导（零打扰）+ 主 UI 渲染', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/settings/model-readiness') return READY;
      if (path === '/api/v1/settings') {
        return {
          theme: 'paper',
          bg: 'default',
          lang: 'zh',
          font: 'sans',
          close_behavior: 'tray',
          tray_hint_dismissed: false,
        };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    render(<App />);
    await screen.findByTestId('app-nav');
    expect(screen.queryByTestId('setup-guide')).not.toBeInTheDocument();
  });

  it('N4：引导完成后判据转 ready → 引导卸载 + 主 UI 渲染', async () => {
    render(<App />);
    await screen.findByTestId('setup-guide');
    // 模拟填写完成：readiness 复核转 ready（store 层驱动，等价于引导内 load() 结果）
    useModelReadinessStore.setState({ readiness: READY, loading: false });
    await waitFor(() => {
      expect(screen.queryByTestId('setup-guide')).not.toBeInTheDocument();
    });
    expect(await screen.findByTestId('app-nav')).toBeInTheDocument();
  });
});
