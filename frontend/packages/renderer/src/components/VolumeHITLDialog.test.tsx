/**
 * VolumeHITLDialog 契约测试（F44 阶段3 #337 卷级 HITL 确认对话框 + 失败恢复交互）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/components/VolumeHITLDialog.tsx 并匹配：
 *
 * export function VolumeHITLDialog(): JSX.Element | null
 * （无 props——读 useBookStore 的 waitingHitl/hitlPayload/confirming，交互调 confirmRun）
 *
 * 显示条件：
 * - waitingHitl === false || hitlPayload === null → return null（非 waiting_hitl 不显示，对齐 422 防呆）
 *
 * 结构 testid（弹窗镜像 AddModelDialog 模式：role=presentation overlay + role=dialog + aria-modal）：
 * - volume-hitl-dialog（容器，role=dialog + aria-modal）
 * - volume-hitl-question（问题文本，内容 = hitlPayload.question，服务端下发非 i18n）
 * - 卷边界形态（hitlPayload.failed === undefined）：
 *   - volume-hitl-progress-<outlineId>（progress 每章一个条目）
 *   - volume-hitl-approve（「继续下一卷」→ confirmRun(true)）
 *   - volume-hitl-reject（「中止」→ confirmRun(false)）
 * - 卷失败形态（hitlPayload.failed !== undefined）：
 *   - volume-hitl-failed-list（失败章列表容器）
 *   - volume-hitl-failed-<outlineId>（每章一行）
 *   - volume-hitl-continue（「继续」→ confirmRun(true, 'continue')）
 *   - volume-hitl-abort（「中止并结束」→ confirmRun(false, 'abort')）
 *   - volume-hitl-supervisor（「授权主 agent 处理」→ confirmRun(true, 'supervisor')）
 * - confirming=true 时所有按钮 disabled（两种形态都禁用）
 *
 * 判别：hitlPayload.failed !== undefined = 卷失败；hitlPayload.progress !== undefined = 卷边界
 * （S1a backend book_pipeline._volume_boundary / _volume_failure payload 构造实证）
 *
 * i18n key（GREEN 补 zh.ts/en.ts）：book.hitl.approve / book.hitl.reject / book.hitl.continue /
 * book.hitl.abort / book.hitl.supervisor / book.hitl.failedList
 * （本批断言以 testid 为主；文案断言仅用服务端 payload 的 question 字段，不依赖 i18n 键存在）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { VolumeHITLDialog } from './VolumeHITLDialog';
import { useBookStore } from '../stores/book';
import { useThemeStore } from '../stores/theme';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 卷边界 payload（question + volume_index + progress） */
const boundaryPayload = {
  question: '确认继续下一卷？',
  volume_index: 0,
  progress: { 'o-c1': 'done', 'o-c2': 'in_progress' },
};

/** 卷失败 payload（question + failed 章列表） */
const failurePayload = {
  question: '卷执行失败，如何继续？',
  failed: ['o-c1', 'o-c2'],
};

beforeEach(() => {
  apiFetchMock.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useBookStore.setState({
    sessionId: null,
    round: 0,
    questions: [],
    answers: {},
    authorized: [],
    sessionStatus: 'idle',
    oneLiner: '',
    writingPlan: null,
    runId: null,
    runStatus: null,
    progress: {},
    counters: null,
    progressStats: { total: 0, done: 0, inProgress: 0, failed: 0, skipped: 0, pending: 0 },
    loading: false,
    error: null,
    // F44 阶段3（#337）新字段默认值（RED 期播种合法：Zustand 合并未知键，GREEN 后生效）
    waitingHitl: false,
    hitlPayload: null,
    confirming: false,
  });
});

/** URL 分发 mock：GET /runs/{id} → waiting_hitl 响应；POST /runs/{id}/confirm → completed 响应 */
function mockApi() {
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/agent/books/runs/wp-1' && (!init?.method || init.method === 'GET')) {
      return {
        run_id: 'wp-1',
        status: 'waiting_hitl',
        progress: { 'o-c1': 'done' },
        counters: { max_chapters: 1, max_agent_calls: 1, agent_calls: 1, chapters_written: 1 },
        waiting_hitl: true,
        hitl_payload: boundaryPayload,
      };
    }
    if (path === '/api/v1/agent/books/runs/wp-1/confirm' && init?.method === 'POST') {
      return { run_id: 'wp-1', status: 'completed' };
    }
    throw new Error(`unexpected: ${path}`);
  });
}

describe('VolumeHITLDialog — 显示条件（waitingHitl/hitlPayload 驱动）', () => {
  it('默认（waitingHitl=false）→ 不渲染对话框', () => {
    render(<VolumeHITLDialog />);
    expect(screen.queryByTestId('volume-hitl-dialog')).not.toBeInTheDocument();
  });

  it('卷边界 payload（question + volume_index + progress）→ 对话框 + question + 进度条目 + approve/reject', () => {
    useBookStore.setState({ waitingHitl: true, hitlPayload: boundaryPayload });
    render(<VolumeHITLDialog />);
    expect(screen.getByTestId('volume-hitl-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('volume-hitl-question')).toHaveTextContent('确认继续下一卷？');
    expect(screen.getByTestId('volume-hitl-progress-o-c1')).toBeInTheDocument();
    expect(screen.getByTestId('volume-hitl-progress-o-c2')).toBeInTheDocument();
    expect(screen.getByTestId('volume-hitl-approve')).toBeInTheDocument();
    expect(screen.getByTestId('volume-hitl-reject')).toBeInTheDocument();
    // 卷边界形态无失败决策控件
    expect(screen.queryByTestId('volume-hitl-failed-list')).not.toBeInTheDocument();
    expect(screen.queryByTestId('volume-hitl-continue')).not.toBeInTheDocument();
  });

  it('卷失败 payload（question + failed）→ 失败章列表 + 三个决策按钮（无 approve/reject）', () => {
    useBookStore.setState({ waitingHitl: true, hitlPayload: failurePayload });
    render(<VolumeHITLDialog />);
    expect(screen.getByTestId('volume-hitl-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('volume-hitl-question')).toHaveTextContent('卷执行失败，如何继续？');
    expect(screen.getByTestId('volume-hitl-failed-list')).toBeInTheDocument();
    expect(screen.getByTestId('volume-hitl-failed-o-c1')).toBeInTheDocument();
    expect(screen.getByTestId('volume-hitl-failed-o-c2')).toBeInTheDocument();
    expect(screen.getByTestId('volume-hitl-continue')).toBeInTheDocument();
    expect(screen.getByTestId('volume-hitl-abort')).toBeInTheDocument();
    expect(screen.getByTestId('volume-hitl-supervisor')).toBeInTheDocument();
    // 卷失败形态无边界确认按钮
    expect(screen.queryByTestId('volume-hitl-approve')).not.toBeInTheDocument();
    expect(screen.queryByTestId('volume-hitl-reject')).not.toBeInTheDocument();
  });
});

describe('VolumeHITLDialog — 交互（走真实 store.confirmRun，mock apiFetch）', () => {
  it('点 approve → POST /runs/wp-1/confirm body {approved: true}', async () => {
    mockApi();
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'waiting_hitl',
      waitingHitl: true,
      hitlPayload: boundaryPayload,
    });
    const user = userEvent.setup();
    render(<VolumeHITLDialog />);
    await user.click(screen.getByTestId('volume-hitl-approve'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1/confirm', {
        method: 'POST',
        body: { approved: true },
      });
    });
  });

  it('点 reject → POST body {approved: false}', async () => {
    mockApi();
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'waiting_hitl',
      waitingHitl: true,
      hitlPayload: boundaryPayload,
    });
    const user = userEvent.setup();
    render(<VolumeHITLDialog />);
    await user.click(screen.getByTestId('volume-hitl-reject'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1/confirm', {
        method: 'POST',
        body: { approved: false },
      });
    });
  });

  it('点 continue → POST body {approved: true, decision: continue}', async () => {
    mockApi();
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'waiting_hitl',
      waitingHitl: true,
      hitlPayload: failurePayload,
    });
    const user = userEvent.setup();
    render(<VolumeHITLDialog />);
    await user.click(screen.getByTestId('volume-hitl-continue'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1/confirm', {
        method: 'POST',
        body: { approved: true, decision: 'continue' },
      });
    });
  });

  it('点 supervisor → POST body {approved: true, decision: supervisor}', async () => {
    mockApi();
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'waiting_hitl',
      waitingHitl: true,
      hitlPayload: failurePayload,
    });
    const user = userEvent.setup();
    render(<VolumeHITLDialog />);
    await user.click(screen.getByTestId('volume-hitl-supervisor'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1/confirm', {
        method: 'POST',
        body: { approved: true, decision: 'supervisor' },
      });
    });
  });
});

describe('VolumeHITLDialog — confirming 禁用', () => {
  it('confirming=true → 全部按钮 disabled（边界 + 失败两种形态）', () => {
    useBookStore.setState({
      waitingHitl: true,
      hitlPayload: boundaryPayload,
      confirming: true,
    });
    const { unmount } = render(<VolumeHITLDialog />);
    expect(screen.getByTestId('volume-hitl-approve')).toBeDisabled();
    expect(screen.getByTestId('volume-hitl-reject')).toBeDisabled();
    unmount();

    useBookStore.setState({
      waitingHitl: true,
      hitlPayload: failurePayload,
      confirming: true,
    });
    render(<VolumeHITLDialog />);
    expect(screen.getByTestId('volume-hitl-continue')).toBeDisabled();
    expect(screen.getByTestId('volume-hitl-abort')).toBeDisabled();
    expect(screen.getByTestId('volume-hitl-supervisor')).toBeDisabled();
  });
});
