/**
 * #1218 RED 契约：AppLayout 模型就绪查询的「自愈」——外部配置完成后主 UI 自动放行。
 *
 * 缺陷（#1218）
 * ------------
 * `App.tsx` 的 readiness 查询是**一次性**的（`booted` 翻转时查一次）。若查询发生在
 * 外部配置（CLI/API/另一窗口）落库**之前**，readiness 停在 null/false →
 * `<SetupGuide />` 全屏**永久**盖住主 UI，不会自愈（只能手动刷新/重启）。
 * 对比：内核状态 `useKernelStore` 有轮询（`startPolling`），readiness 没有。
 *
 * GREEN 契约（App.tsx）
 * --------------------
 * 1. **未就绪 → 持续重查**：readiness 非 ready 期间，每 `READINESS_POLL_INTERVAL_MS`
 *    重查一次（镜像 `useKernelStore` 的 `startPolling` 模式，间隔照抄）；
 * 2. **就绪即停**：readiness.ready === true 后**不再**查询（避免无谓请求）；
 * 3. **focus → 立即重查**（窗口聚焦补充手段）——但**已就绪时零查询**
 *    （避免用户每次切窗口回 GUI 都打一次后端）；
 * 4. **卸载清理**：组件卸载后不再有任何查询（无定时器/监听器泄漏）。
 *
 * 数据来源 = F23 变更推送（§15.6.2 失效矩阵已列 `provider_config → modelReadiness`）：
 * 外部写入（cli/mcp/agent）经 SSE 送达 → 立即重查；轮询是推送丢失时的兜底。
 *
 * RED 形态
 * --------
 * GREEN 前仅有一次挂载查询 → 「未就绪持续性重查」用例在推进定时器后查询数仍为 1 → FAIL。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from './App';
import { apiFetch } from './api/client';
import { useProjectStore } from './stores/project';
import { useChapterStore } from './stores/chapter';
import { useThemeStore } from './stores/theme';
import { useKernelStore } from './stores/kernel';
import { READINESS_POLL_INTERVAL_MS, useModelReadinessStore } from './stores/modelReadiness';

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

const READINESS_PATH = '/api/v1/settings/model-readiness';

/** 就绪判据查询次数（排除其它端点噪声） */
function readinessCalls(): number {
  return apiFetchMock.mock.calls.filter((c) => c[0] === READINESS_PATH).length;
}

function mockEndpoints(readinessImpl: () => Promise<unknown>) {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === READINESS_PATH) return await readinessImpl();
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
}

async function flushMicrotasks(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
  });
}

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
  useKernelStore.setState({ status: 'ready', booted: true, healthFailures: 0 });
  useModelReadinessStore.setState({ readiness: null, loading: false });
});

afterEach(() => {
  vi.useRealTimers();
  useKernelStore.getState().stopPolling();
  useModelReadinessStore.getState().stopPolling();
});

describe('AppLayout 就绪查询自愈（#1218）', () => {
  it('N1218-1：未就绪 → 按 READINESS_POLL_INTERVAL_MS 持续重查（非一次性）', async () => {
    vi.useFakeTimers();
    mockEndpoints(async () => NOT_READY);
    render(<App />);
    await flushMicrotasks();

    expect(readinessCalls()).toBe(1); // 挂载首查（既有语义）

    await act(async () => {
      vi.advanceTimersByTime(READINESS_POLL_INTERVAL_MS);
      await Promise.resolve();
    });
    expect(readinessCalls()).toBe(2);

    await act(async () => {
      vi.advanceTimersByTime(READINESS_POLL_INTERVAL_MS);
      await Promise.resolve();
    });
    expect(readinessCalls()).toBe(3);
  });

  it('N1218-2：未就绪 → 就绪翻转后主 UI 自动放行（无需刷新/重启）+ 停轮询', async () => {
    vi.useFakeTimers();
    let ready = false;
    mockEndpoints(async () => (ready ? READY : NOT_READY));
    render(<App />);
    await flushMicrotasks();

    expect(screen.getByTestId('setup-guide')).toBeInTheDocument();
    expect(screen.queryByTestId('app-nav')).not.toBeInTheDocument();

    ready = true; // 外部（CLI/API）完成配置 → 判据转 ready
    await act(async () => {
      vi.advanceTimersByTime(READINESS_POLL_INTERVAL_MS);
      await Promise.resolve();
    });

    expect(screen.queryByTestId('setup-guide')).not.toBeInTheDocument();
    expect(screen.getByTestId('app-nav')).toBeInTheDocument();

    // 就绪即停：再推进多个周期，不应再有 readiness 查询
    const settled = readinessCalls();
    await act(async () => {
      vi.advanceTimersByTime(READINESS_POLL_INTERVAL_MS * 3);
      await Promise.resolve();
    });
    expect(readinessCalls()).toBe(settled);
  });

  it('N1218-3：窗口 focus → 立即重查（未就绪时）', async () => {
    mockEndpoints(async () => NOT_READY);
    render(<App />);
    await flushMicrotasks();
    expect(readinessCalls()).toBe(1);

    fireEvent.focus(window);
    await waitFor(() => expect(readinessCalls()).toBe(2));
  });

  it('N1218-4：已就绪 → focus 仍重查（外部改配置后纠偏；单次 GET 代价可忽略）', async () => {
    mockEndpoints(async () => READY);
    render(<App />);
    await screen.findByTestId('app-nav');
    const settled = readinessCalls();

    fireEvent.focus(window);
    await waitFor(() => expect(readinessCalls()).toBe(settled + 1));
  });

  it('N1218-5【G】：卸载后不再查询（无定时器/监听器泄漏）', async () => {
    vi.useFakeTimers();
    mockEndpoints(async () => NOT_READY);
    const view = render(<App />);
    await flushMicrotasks();
    const before = readinessCalls();

    view.unmount();
    await act(async () => {
      vi.advanceTimersByTime(READINESS_POLL_INTERVAL_MS * 4);
      await Promise.resolve();
    });
    fireEvent.focus(window);
    await flushMicrotasks();

    expect(readinessCalls()).toBe(before);
  });
});
