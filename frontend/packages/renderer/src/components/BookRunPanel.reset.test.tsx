/**
 * BookRunPanel reset 运行（#1288 第 1 项）契约测试（RED）。
 *
 * 背景：PR #1284（#1282 已 merge）补上了「不删正文重跑」的服务端出口
 *   POST /api/v1/agent/books/runs/{run_id}/reset
 * 清 progress / execution_refs + 退回 ready，**不动** chapters.content / drafts。
 * 本文件守 GUI 侧闭环：reset 是**破坏性操作**（丢「跑过」的执行记录），
 * 必须经确认提示（说清「重置 ≠ 删除正文」）才发请求。
 *
 * ⚠️ 本文件 = 契约。GREEN 必须实现（三处）：
 *
 * ① src/api/books.ts 新增：
 *    export interface ResetRunResponse { run_id: string; status: string; }
 *    export async function resetBookRun(runId: string): Promise<ResetRunResponse>
 *      → POST /api/v1/agent/books/runs/${runId}/reset（**无请求体**）
 *    （openapi.d.ts 已含该端点，无需 gen:api 刷新；后端返回 {"run_id","status":"ready"}）
 *
 * ② src/stores/book.ts 新增 action：
 *    resetRun: () => Promise<boolean>
 *    - runId === null → 直接 return false（不发请求）
 *    - 成功 → 清空**运行态**字段回初始值：runId=null / runStatus=null / progress={} /
 *      counters=null / progressStats 归零 / progressReason=null / waitingHitl=false /
 *      hitlPayload=null / interveneDiff=null / summary=null → return true
 *      （runId 置 null ⇒ BookPlannerPanel 回到「计划就绪 + 开始写作」态，重跑闭环；
 *        writingPlan 必须**保留**，否则计划卡消失、无处点「开始写作」）
 *    - 失败 → set({ error: errorMessage(err) }) → return false（面板不消失）
 *
 * ③ src/components/BookRunPanel.tsx 工具栏（与 pause/resume/密度/摘要同排）新增：
 *    - 按钮 data-testid="run-reset"，渲染条件 = runId !== null && runStatus !== 'running'
 *      （后端 reset_run 对 status==='running' 抛 ValueError → 422「运行已在进行中，不可重置」；
 *       与 pause/resume 的「按状态互斥渲染」同族防呆）
 *    - 点击 → 打开共享 <ConfirmDialog/>（testidPrefix='run-reset'，danger）：
 *        title  = t('book.run.reset.title')
 *        message = t('book.run.reset.message')   ← 必须含「重置 ≠ 删除正文」
 *        confirmText = t('book.run.reset.confirm')
 *    - 取消（run-reset-cancel / Esc）→ 关闭且**不发** reset 请求
 *    - 确认（run-reset-ok）→ 调 store.resetRun()，**恰好一次**
 *
 * i18n（bookZh/bookEn 成对新增，键集合必须对称——i18n.contract.test.ts）：
 *    book.run.reset         = '重置运行' / 'Reset run'
 *    book.run.reset.title   = '重置运行？' / 'Reset run?'
 *    book.run.reset.message = zh 必须含「重置 ≠ 删除正文」，且说明正文不会被删除、旧正文需自行处理
 *                             例：'重置 ≠ 删除正文：只清空执行状态（进度与执行记录），
 *                                  正文与草稿不会被删除。若旧正文仍在，重跑时安全闸仍会拦截，
 *                                  需你先自行处理旧正文。'
 *    book.run.reset.confirm = '确认重置' / 'Reset'
 *
 * 断言锚 testid / 关键词，不锁死整句文案（除「重置 ≠ 删除正文」这一要点）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BookRunPanel } from './BookRunPanel';
import { useBookStore } from '../stores/book';
import { useThemeStore } from '../stores/theme';
import { apiFetch, ApiError } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const RUN_PATH = '/api/v1/agent/books/runs/wp-1';
const RESET_PATH = '/api/v1/agent/books/runs/wp-1/reset';

const runCompleted = {
  run_id: 'wp-1',
  status: 'completed',
  progress: { 'o-c1': 'done' },
  counters: { max_chapters: 2, max_agent_calls: 2, agent_calls: 1, chapters_written: 1 },
};

/** 计划（reset 后必须保留，否则页级回到「无计划」态、无处点「开始写作」重跑） */
const planFixture = {
  id: 'wp-1',
  project_id: 'p1',
  title: '示例计划',
  status: 'ready',
  root_outline_id: null,
  character_ids: [],
  limits: {},
  progress: {},
  execution_refs: {},
  thread_id: null,
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
};

/** 按路径分发的 apiFetch mock：GET 运行状态 + POST reset */
function mockApi(resetImpl?: () => unknown): void {
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === RUN_PATH && (!init?.method || init.method === 'GET')) return runCompleted;
    if (path === RESET_PATH && init?.method === 'POST') {
      if (resetImpl) return resetImpl();
      return { run_id: 'wp-1', status: 'ready' };
    }
    throw new Error(`unexpected: ${path} ${init?.method ?? 'GET'}`);
  });
}

/** 该路径 + POST 的调用次数（轮询 GET 不计入） */
function resetCallCount(): number {
  return apiFetchMock.mock.calls.filter(
    ([path, init]) =>
      path === RESET_PATH && (init as { method?: string } | undefined)?.method === 'POST',
  ).length;
}

beforeEach(() => {
  apiFetchMock.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  // 先归零 store（防上一条用例残留），再播种本组前提
  useBookStore.getState().reset();
});

describe('BookRunPanel — #1288 reset 按钮（渲染条件）', () => {
  it('runId 非空且 runStatus=completed → 渲染 run-reset 按钮', async () => {
    mockApi();
    useBookStore.setState({ runId: 'wp-1', runStatus: 'completed', progress: { 'o-c1': 'done' } });
    render(<BookRunPanel />);
    expect(await screen.findByTestId('run-reset')).toBeInTheDocument();
  });

  it('runStatus=running → 不渲染 run-reset（后端 422「运行已在进行中」防呆）', async () => {
    // 轮询返回体必须自洽为 running：否则 loadRunStatus 会把 store 刷成 completed，
    // 按钮按新状态出现 → 该负向断言失去意义（测试自身必须与被断言状态一致）
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'running',
      progress: { 'o-c1': 'in_progress' },
      counters: { max_chapters: 2, max_agent_calls: 2, agent_calls: 0, chapters_written: 0 },
    });
    useBookStore.setState({ runId: 'wp-1', runStatus: 'running', progress: {} });
    render(<BookRunPanel />);
    await screen.findByTestId('run-status');
    expect(screen.queryByTestId('run-reset')).not.toBeInTheDocument();
  });

  it('runId === null（面板空态）→ 不渲染 run-reset', () => {
    render(<BookRunPanel />);
    expect(screen.getByTestId('book-run-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('run-reset')).not.toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});

describe('BookRunPanel — #1288 reset 确认闭环', () => {
  it('点 run-reset → 确认框出现，且文案含「重置 ≠ 删除正文」', async () => {
    mockApi();
    useBookStore.setState({ runId: 'wp-1', runStatus: 'completed', progress: { 'o-c1': 'done' } });
    const user = userEvent.setup();
    render(<BookRunPanel />);
    await user.click(await screen.findByTestId('run-reset'));

    const dialog = await screen.findByTestId('run-reset-dialog');
    expect(dialog).toBeInTheDocument();
    // 关键要点：重置 ≠ 删除正文（防用户误以为重跑会重写正文，随后被安全闸拦住）
    expect(dialog).toHaveTextContent('重置 ≠ 删除正文');
    expect(screen.getByTestId('run-reset-ok')).toBeInTheDocument();
    expect(screen.getByTestId('run-reset-cancel')).toBeInTheDocument();
    // 仅打开确认框，尚未发请求
    expect(resetCallCount()).toBe(0);
  });

  it('取消 → 确认框关闭且不发 reset 请求', async () => {
    mockApi();
    useBookStore.setState({ runId: 'wp-1', runStatus: 'completed', progress: { 'o-c1': 'done' } });
    const user = userEvent.setup();
    render(<BookRunPanel />);
    await user.click(await screen.findByTestId('run-reset'));
    await user.click(await screen.findByTestId('run-reset-cancel'));

    await waitFor(() => {
      expect(screen.queryByTestId('run-reset-dialog')).not.toBeInTheDocument();
    });
    expect(resetCallCount()).toBe(0);
    // 面板与运行态不变
    expect(screen.getByTestId('run-status')).toHaveTextContent('completed');
  });

  it('确认 → POST /reset 恰好一次，且面板回到「暂无运行」空态（runId 清空）', async () => {
    mockApi();
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'completed',
      progress: { 'o-c1': 'done' },
      writingPlan: planFixture,
    });
    const user = userEvent.setup();
    render(<BookRunPanel />);
    await user.click(await screen.findByTestId('run-reset'));
    await user.click(await screen.findByTestId('run-reset-ok'));

    await waitFor(() => {
      expect(useBookStore.getState().runId).toBeNull();
    });
    expect(apiFetchMock).toHaveBeenCalledWith(RESET_PATH, { method: 'POST' });
    expect(resetCallCount()).toBe(1);
    // 面板态随之更新：状态徽标/工具栏消失，回到空态文案
    await waitFor(() => {
      expect(screen.queryByTestId('run-status')).not.toBeInTheDocument();
    });
    expect(screen.queryByTestId('run-reset')).not.toBeInTheDocument();
    expect(screen.queryByTestId('run-reset-dialog')).not.toBeInTheDocument();
    // 计划必须保留（否则页级回到「无计划」态、无处点「开始写作」重跑）
    expect(useBookStore.getState().writingPlan?.id).toBe('wp-1');
    // 运行态字段归零
    expect(useBookStore.getState().runStatus).toBeNull();
    expect(useBookStore.getState().progress).toEqual({});
    expect(useBookStore.getState().counters).toBeNull();
  });

  it('reset 失败（422 运行已在进行中）→ 面板保留 + error 记录，按钮可再次点击', async () => {
    mockApi(() => {
      throw new ApiError(422, '运行已在进行中，不可重置');
    });
    useBookStore.setState({ runId: 'wp-1', runStatus: 'completed', progress: { 'o-c1': 'done' } });
    const user = userEvent.setup();
    render(<BookRunPanel />);
    await user.click(await screen.findByTestId('run-reset'));
    await user.click(await screen.findByTestId('run-reset-ok'));

    await waitFor(() => {
      expect(useBookStore.getState().error).toContain('运行已在进行中');
    });
    // 运行态未被清空（失败不假装成功）
    expect(useBookStore.getState().runId).toBe('wp-1');
    expect(screen.getByTestId('run-status')).toBeInTheDocument();
    expect(await screen.findByTestId('run-reset')).toBeInTheDocument();
  });
});
