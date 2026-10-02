/**
 * #1333 段 2 —— 自动写作任务看板（前端契约，RED 先行）
 *
 * 设计真相源：`specs/f19-gui/book.md` §1 方案 C 线框 / §2 控件表 / §3 设计定义 / §4 N14-N26。
 * 原型基准：`design/GUI/book/book.html`（方案 C · 单栏任务时间线）+ `book-c-*.png`。
 *
 * 本文件锁定 §4 中**前端**部分的验收：
 *
 * 结构 testid（GREEN 必须提供）：
 * - run-task-list           任务列表容器（段 2 新增；silent 密度不渲染 → N19）
 * - task-volume-<i>         卷分组容器（i = 卷在 steps 中的出现序，从 0 起）
 * - task-volume-header-<i>  卷头（含卷名文本）
 * - task-volume-toggle-<i>  卷折叠开关（已完成卷默认折叠 → N24）
 * - task-volume-body-<i>    卷体（折叠时**不渲染**内部章行）
 * - trace-row-<outlineId>   章行（复用既有 ExecutionTraceRow）
 * - trace-row-name-<outlineId> 章名文本（N14：不得只显示 outlineId）
 * - trace-substeps-toggle-<outlineId> / trace-substeps-<outlineId> / trace-substep-<outlineId>-<op>
 *                           章内步骤展开入口 / 容器 / 步骤 chip（N15：仅 agentic 轨渲染）
 * - run-live                实时通道指示（N18）；`data-live` = connecting | connected
 *
 * 行为契约：
 * - 任务行数据源：`GET /runs/{id}/summary` 的 steps（含 name/volume_name/substeps）；
 *   summary 未就绪 → 回退 progress（既有形态，零回归）
 * - 章状态取**实时** `progress[outline_id]`（轮询 1s），章名 / 卷名 / 章内步骤取 summary
 * - `needs_review` 章徽标 → 文案 key `book.trace.needs_review` + 语义类 `badge-needs_review`
 *   （修 D-1：不得落回「待处理」）
 * - run `blocked` → 徽标语义类 `run-badge-blocked` + 文案 key `book.run.status.blocked`
 *   （修 D-2：不得落回中性灰 / 英文原文）+ 失败原因块渲染（修 D-3）
 * - SSE：订阅 `writing_plan` 域；帧到达 → 恰好一次 `GET /runs/{id}`；订阅就绪（null）
 *   同样刷新；断连不报错不阻断（N18）
 * - 静态 / 卷级轨（substeps 全空）→ 不渲染 `trace-substeps-toggle-*`（N15）
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, act, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BookRunPanel } from './BookRunPanel';
import { useBookStore } from '../stores/book';
import { useThemeStore } from '../stores/theme';
import { apiFetch } from '../api/client';
import { useDataChangeSubscription } from '../hooks/useDataChangeSubscription';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

vi.mock('../hooks/useDataChangeSubscription', () => ({
  useDataChangeSubscription: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);
const subMock = vi.mocked(useDataChangeSubscription);

const RUN_URL = '/api/v1/agent/books/runs/wp-1';
const SUMMARY_URL = '/api/v1/agent/books/runs/wp-1/summary';

const counters = { max_chapters: 4, max_agent_calls: 20, agent_calls: 4, chapters_written: 2 };

/** 三卷 4 章：第一卷全 done（→ 默认折叠）、第二卷 needs_review（→ 展开）、第三卷 pending。 */
const STEPS = [
  {
    index: 0,
    outline_id: 'o-v1c1',
    name: '开端',
    status: 'done',
    execution_id: 'e-1',
    volume_name: '第一卷',
    substeps: [
      { op: 'write_chapter', status: 'done' },
      { op: 'audit_chapter', status: 'done' },
      { op: 'mark_done', status: 'done' },
    ],
  },
  {
    index: 1,
    outline_id: 'o-v1c2',
    name: '发展',
    status: 'done',
    execution_id: 'e-2',
    volume_name: '第一卷',
    substeps: [],
  },
  {
    index: 2,
    outline_id: 'o-v2c1',
    name: '转折',
    status: 'needs_review',
    execution_id: null,
    volume_name: '第二卷',
    substeps: [
      { op: 'write_chapter', status: 'done' },
      { op: 'audit_chapter', status: 'done' },
    ],
  },
  {
    index: 3,
    outline_id: 'o-v3c1',
    name: '终局',
    status: 'pending',
    execution_id: null,
    volume_name: '第三卷',
    substeps: [],
  },
];

const PROGRESS = {
  'o-v1c1': 'done',
  'o-v1c2': 'done',
  'o-v2c1': 'needs_review',
  'o-v3c1': 'pending',
};

function mockApi(
  status: Record<string, unknown> = { status: 'running', progress: PROGRESS },
  summary: Record<string, unknown> | null = {},
) {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === RUN_URL) {
      return { run_id: 'wp-1', counters, ...status };
    }
    if (path === SUMMARY_URL) {
      if (summary === null) throw new Error('summary disabled');
      return { run_id: 'wp-1', status: 'running', progress: PROGRESS, counters, next: { finished: true }, ...summary };
    }
    throw new Error(`unexpected: ${path}`);
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  subMock.mockReset();
  subMock.mockImplementation(() => undefined);
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
    progressReason: null,
    progress: {},
    counters: null,
    progressStats: { total: 0, done: 0, inProgress: 0, failed: 0, skipped: 0, pending: 0 },
    waitingHitl: false,
    hitlPayload: null,
    confirming: false,
    density: 'dashboard',
    interveneDiff: null,
    intervening: false,
    summary: null,
    summaryLoading: false,
    loading: false,
    error: null,
  });
});

afterEach(() => {
  cleanup();
});

describe('#1333 任务列表 — 章级行 + 章名（N14）', () => {
  it('summary.steps 就绪 → run-task-list 逐章渲染，行含章名（非 outlineId）', async () => {
    mockApi({ status: 'running', progress: PROGRESS }, { steps: STEPS });
    useBookStore.setState({ runId: 'wp-1', runStatus: 'running', progress: PROGRESS, counters });

    render(<BookRunPanel />);

    expect(await screen.findByTestId('run-task-list')).toBeInTheDocument();
    // 第二卷（需人工介入）+ 第三卷默认展开
    expect(await screen.findByTestId('trace-row-o-v2c1')).toBeInTheDocument();
    expect(screen.getByTestId('trace-row-name-o-v2c1')).toHaveTextContent('转折');
    expect(screen.getByTestId('trace-row-name-o-v3c1')).toHaveTextContent('终局');
  });
});

describe('#1333 任务列表 — 卷分组 + 已完成卷默认折叠（N24）', () => {
  it('按卷分组；全 done 的卷默认折叠（章行不渲染），可展开', async () => {
    const user = userEvent.setup();
    mockApi({ status: 'running', progress: PROGRESS }, { steps: STEPS });
    useBookStore.setState({ runId: 'wp-1', runStatus: 'running', progress: PROGRESS, counters });

    render(<BookRunPanel />);

    const header0 = await screen.findByTestId('task-volume-header-0');
    expect(header0).toHaveTextContent('第一卷');
    // 第一卷全 done → 默认折叠 → 章行不渲染
    expect(screen.queryByTestId('trace-row-o-v1c1')).not.toBeInTheDocument();
    // 第二卷含 needs_review → 不折叠
    expect(screen.getByTestId('trace-row-o-v2c1')).toBeInTheDocument();

    await user.click(screen.getByTestId('task-volume-toggle-0'));
    expect(await screen.findByTestId('trace-row-o-v1c1')).toBeInTheDocument();
    expect(screen.getByTestId('trace-row-name-o-v1c1')).toHaveTextContent('开端');
  });
});

describe('#1333 状态语义完整性（修 D-1 / D-2 / D-3）', () => {
  it('章 needs_review → 「待人工介入」语义（badge-needs_review），不得落回 badge-pending', async () => {
    mockApi({ status: 'running', progress: PROGRESS }, { steps: STEPS });
    useBookStore.setState({ runId: 'wp-1', runStatus: 'running', progress: PROGRESS, counters });

    render(<BookRunPanel />);

    const badge = await screen.findByTestId('trace-row-status-o-v2c1');
    expect(badge).toHaveClass('badge-needs_review');
    expect(badge).not.toHaveClass('badge-pending');
  });

  it('run blocked → run-badge-blocked 语义类 + 中文文案（非英文原文）', async () => {
    mockApi(
      {
        status: 'blocked',
        progress: PROGRESS,
        progress_reason: '第四章：审计阻断（人设漂移 severity=error），已停止后续章节',
      },
      { steps: STEPS },
    );
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'running',
      progress: PROGRESS,
      counters,
    });

    render(<BookRunPanel />);

    const badge = await screen.findByTestId('run-status');
    await waitFor(() => {
      expect(badge).toHaveClass('run-badge-blocked');
    });
    expect(badge).not.toHaveTextContent('blocked');
  });

  it('run blocked → 失败原因块渲染（N16 / 修 D-3）', async () => {
    const reason = '第四章：审计阻断（人设漂移 severity=error），已停止后续章节';
    mockApi({ status: 'blocked', progress: PROGRESS, progress_reason: reason }, { steps: STEPS });
    useBookStore.setState({ runId: 'wp-1', runStatus: 'blocked', progressReason: reason, progress: PROGRESS, counters });

    render(<BookRunPanel />);

    const block = await screen.findByTestId('run-progress-reason');
    expect(block).toHaveTextContent(reason);
  });
});

describe('#1333 章内步骤展开（N15）', () => {
  it('agentic 轨（substeps 非空）→ 渲染展开入口，展开显示步骤 chip', async () => {
    const user = userEvent.setup();
    mockApi({ status: 'running', progress: PROGRESS }, { steps: STEPS });
    useBookStore.setState({ runId: 'wp-1', runStatus: 'running', progress: PROGRESS, counters });

    render(<BookRunPanel />);

    const toggle = await screen.findByTestId('trace-substeps-toggle-o-v2c1');
    expect(screen.queryByTestId('trace-substeps-o-v2c1')).not.toBeInTheDocument();

    await user.click(toggle);
    const list = await screen.findByTestId('trace-substeps-o-v2c1');
    expect(list).toHaveTextContent('write_chapter');
    expect(screen.getByTestId('trace-substep-o-v2c1-audit_chapter')).toBeInTheDocument();
  });

  it('静态轨（substeps 全空）→ 不渲染展开入口（N15）', async () => {
    const staticSteps = STEPS.map((s) => ({ ...s, substeps: [] }));
    mockApi({ status: 'running', progress: PROGRESS }, { steps: staticSteps });
    useBookStore.setState({ runId: 'wp-1', runStatus: 'running', progress: PROGRESS, counters });

    render(<BookRunPanel />);

    await screen.findByTestId('run-task-list');
    expect(screen.queryByTestId('trace-substeps-toggle-o-v2c1')).not.toBeInTheDocument();
  });
});

describe('#1333 密度与列表（N19）', () => {
  it('silent 密度 → 不渲染 run-task-list（观察流下线）', async () => {
    mockApi({ status: 'running', progress: PROGRESS }, { steps: STEPS });
    useBookStore.setState({ runId: 'wp-1', runStatus: 'running', density: 'silent', progress: PROGRESS, counters });

    render(<BookRunPanel />);

    await screen.findByTestId('run-status');
    expect(screen.queryByTestId('run-task-list')).not.toBeInTheDocument();
  });
});

describe('#1333 实时通道（N18 / N22）', () => {
  it('订阅 writing_plan 域；推送帧到达 → 恰好一次 run status 拉取 + data-live=connected', async () => {
    mockApi({ status: 'running', progress: PROGRESS }, { steps: STEPS });
    useBookStore.setState({ runId: 'wp-1', runStatus: 'running', progress: PROGRESS, counters });

    render(<BookRunPanel />);
    await screen.findByTestId('run-live');

    const [domains] = subMock.mock.calls[0];
    expect(domains).toContain('writing_plan');

    const statusCalls = () => apiFetchMock.mock.calls.filter(([p]) => p === RUN_URL).length;
    const before = statusCalls();

    const onInvalidate = subMock.mock.calls[0][1] as (ev: unknown) => void;
    await act(async () => {
      onInvalidate({
        domain: 'writing_plan',
        op: 'update',
        resource_id: 'wp-1',
        project_id: 'p1',
      });
    });

    await waitFor(() => {
      expect(statusCalls()).toBe(before + 1);
    });
    expect(screen.getByTestId('run-live')).toHaveAttribute('data-live', 'connected');
  });

  it('订阅就绪（event=null）同样触发一次刷新，且不报错阻断页面（N18）', async () => {
    mockApi({ status: 'paused', progress: PROGRESS }, { steps: STEPS });
    useBookStore.setState({ runId: 'wp-1', runStatus: 'running', progress: PROGRESS, counters });

    render(<BookRunPanel />);
    await screen.findByTestId('run-live');

    const statusCalls = () => apiFetchMock.mock.calls.filter(([p]) => p === RUN_URL).length;
    const before = statusCalls();

    const onInvalidate = subMock.mock.calls[0][1] as (ev: unknown) => void;
    await act(async () => {
      onInvalidate(null);
    });

    await waitFor(() => {
      expect(statusCalls()).toBe(before + 1);
    });
    expect(await screen.findByTestId('book-run-panel')).toBeInTheDocument();
  });
});
