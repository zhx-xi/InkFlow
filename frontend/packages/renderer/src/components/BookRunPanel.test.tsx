/**
 * BookRunPanel 契约测试（F44 阶段1 GUI，spec v1.1 §5.1 GUI 小节「WritingPlan 进度状态显示」）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/components/BookRunPanel.tsx 并匹配：
 *
 * export function BookRunPanel(): JSX.Element
 * （无 props——读 useBookStore 的 runId/progress/counters/runStatus；挂载时轮询 loadRunStatus）
 *
 * 结构 testid：
 * - book-run-panel（容器，委托后由 BookPlannerPanel 渲染）
 * - run-status（运行状态徽标：completed/running/...）
 * - run-counter-chapters（章计数：chapters_written / max_chapters）
 * - run-counter-calls（调用计数：agent_calls / max_agent_calls）
 * - run-counter-tokens（阶段2：token 计数：tokens_used / max_tokens）
 * - run-token-warning（阶段2：tokens_warning=true 时告警提示）
 * - run-progress-bar（阶段2：章进度条 done / total）
 * - run-progress-list（progress 展开行列表容器）
 * - run-refresh（手动刷新按钮，可选）
 *
 * 行为契约（镜像 ChatPanel #379 1s 轮询 + S1a 唯一真相 GET /runs/{id}）：
 * - 挂载时加载当前 run（runId 非空 → loadRunStatus(runId)）
 * - 显示 status + counters（chapters_written/max_chapters、agent_calls/max_agent_calls）
 * - 阶段2：counters 含 tokens → 显示 run-counter-tokens（tokens_used / max_tokens）
 * - 阶段2：tokens_warning=true → 显示 run-token-warning 告警
 * - 阶段2：progressStats 派生后渲染 run-progress-bar（done / total）
 * - progress 每章渲染一个 ExecutionTraceRow（outline_id → status）
 * - 轮询：loadRunStatus 非终态（running）时 1s 后再次拉取（卸载清理 timer）
 * - 完成态（completed）停止轮询
 *
 * i18n key（GREEN 补 zh.ts/en.ts）：book.run.status / book.run.chapters /
 * book.run.calls / book.run.noRun
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { BookRunPanel } from './BookRunPanel';
import { useBookStore } from '../stores/book';
import { useThemeStore } from '../stores/theme';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

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
  });
});

describe('BookRunPanel — 运行状态显示', () => {
  it('runId 非空 → 挂载加载 loadRunStatus + 渲染状态与计数', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'completed',
      progress: { 'o-ch1': 'done' },
      counters: { max_chapters: 1, max_agent_calls: 1, agent_calls: 1, chapters_written: 1 },
    });
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'running',
      progress: {},
      counters: null,
    });
    render(<BookRunPanel />);
    expect(await screen.findByTestId('book-run-panel')).toBeInTheDocument();
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1');
    });
    expect(await screen.findByTestId('run-status')).toHaveTextContent('completed');
    expect(screen.getByTestId('run-counter-chapters')).toHaveTextContent('1');
    expect(screen.getByTestId('run-counter-chapters')).toHaveTextContent('1');
    expect(screen.getByTestId('run-counter-calls')).toHaveTextContent('1');
  });

  it('progress 每章渲染展开行（trace-row-<outlineId>）', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'completed',
      progress: { 'o-ch1': 'done', 'o-ch2': 'pending' },
      counters: { max_chapters: 2, max_agent_calls: 2, agent_calls: 1, chapters_written: 1 },
    });
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'running',
      progress: { 'o-ch1': 'done', 'o-ch2': 'pending' },
      counters: null,
    });
    render(<BookRunPanel />);
    expect(await screen.findByTestId('trace-row-o-ch1')).toBeInTheDocument();
    expect(screen.getByTestId('trace-row-o-ch2')).toBeInTheDocument();
    expect(screen.getByTestId('trace-row-status-o-ch1')).toHaveTextContent('已完成');
  });

  it('无 runId → 渲染空态文案，不发请求', () => {
    render(<BookRunPanel />);
    expect(screen.getByTestId('book-run-panel')).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});

describe('BookRunPanel — 轮询', () => {
  it('running 态轮询（1s 间隔）→ completed 后停止', async () => {
    // setup.ts 全局包装：无参 useFakeTimers() 默认 shouldAdvanceTime=true
    // （RTL asyncWrapper 排水依赖真实时间推进；显式 false 会让 findBy/waitFor 挂起）
    vi.useFakeTimers();
    try {
      apiFetchMock
        .mockResolvedValueOnce({
          run_id: 'wp-1',
          status: 'running',
          progress: {},
          counters: { max_chapters: 1, max_agent_calls: 1, agent_calls: 0, chapters_written: 0 },
        })
        .mockResolvedValueOnce({
          run_id: 'wp-1',
          status: 'completed',
          progress: { 'o-ch1': 'done' },
          counters: { max_chapters: 1, max_agent_calls: 1, agent_calls: 1, chapters_written: 1 },
        });
      useBookStore.setState({
        runId: 'wp-1',
        runStatus: 'running',
        progress: {},
        counters: null,
      });
      render(<BookRunPanel />);
      // 首次加载 + 推进 1s → 第二次轮询（completed）
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(apiFetchMock).toHaveBeenCalledTimes(2);
      expect(await screen.findByTestId('run-status')).toHaveTextContent('completed');
      // 再推进 2s → 不再轮询
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(apiFetchMock).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('BookRunPanel — 阶段2 章进度条 + token 计数（spec §5.2 观察流仪表密度）', () => {
  const counters7 = {
    max_chapters: 3,
    max_agent_calls: 5,
    agent_calls: 1,
    chapters_written: 1,
    max_tokens: 200000,
    tokens_used: 12345,
    tokens_warning: false,
  };

  it('渲染章进度条（done / total）+ token 计数（无告警）', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'completed',
      progress: { 'o-c1': 'done', 'o-c2': 'in_progress', 'o-c3': 'pending' },
      counters: counters7,
    });
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'running',
      progress: { 'o-c1': 'done', 'o-c2': 'in_progress', 'o-c3': 'pending' },
      counters: null,
    });
    render(<BookRunPanel />);
    const bar = await screen.findByTestId('run-progress-bar');
    expect(bar).toHaveTextContent('1');
    expect(bar).toHaveTextContent('3');
    const tokens = screen.getByTestId('run-counter-tokens');
    expect(tokens).toHaveTextContent('12345');
    expect(tokens).toHaveTextContent('200000');
    expect(screen.queryByTestId('run-token-warning')).not.toBeInTheDocument();
  });

  it('tokens_warning=true → 显示告警提示', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'completed',
      progress: { 'o-c1': 'done' },
      counters: { ...counters7, tokens_warning: true },
    });
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'running',
      progress: { 'o-c1': 'done' },
      counters: null,
    });
    render(<BookRunPanel />);
    expect(await screen.findByTestId('run-token-warning')).toBeInTheDocument();
  });
});
