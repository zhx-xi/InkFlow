/**
 * #932 日志页 UX RED 契约测试（feat/log-page-ux-932）。
 *
 * 契约四组：
 *   S1 页大小 Select、S2 行点击详情、S3 只看此链、S4 调用链视图。
 *
 * 本文件 = 契约。GREEN 实现必须匹配全部 data-testid 与 fetchLogs 参数断言：
 *   - 页大小：log-page-size-select（Radix Select，aria-label 每页条数，默认 '50'，
 *     选项 value=label '10'/'25'/'50'/'100'）→ 切换重查 + limit + page 归 0；
 *     log-page-info 页数按 limit 重算（total=120, limit=10 → 12 页）。
 *   - 行点击：log-row 可点击（tabindex + aria-expanded，Enter 展开）→ log-detail
 *     （raw timestamp / message-key / 插值 message / params JSON.stringify（null,2）/
 *     error-code / trace / correlation / duration #930 规则 / stack 仅 ERROR）。
 *     log-copy-trace-btn / log-copy-correlation-btn → navigator.clipboard.writeText。
 *   - 只看此链：log-chain-only-btn（trace 优先于 correlation；皆空 disabled + title 提示）
 *     → 重查 + log-chain-chip（内 log-chain-clear-btn 清空回退 / log-reset-btn 重置归零）。
 *   - 调用链：log-chain-view-btn → 独立 query {trace_id, limit:200}（精确，不带 level/
 *     caller_type/page）→ log-chain-view；log-chain-node 按 timestamp 升序 + node-duration
 *     （#930 规则）+ node-error-code（无则不渲染）；节点可展开；log-chain-back-btn 返回；
 *     返回后刷新回主查询（limit 保持切换值、无 trace_id 残留）。
 *   - 双语：lang=en → 'Filter to this chain' / 'View full call chain'。
 *
 * 接线（Mock 依赖，与 logs.test.tsx / #930 同契约）：
 *   - LogsPage 必须 import { fetchLogs, fetchLogMessages } from '../api/logs'
 *   - 挂载即查默认参数；fetchLogMessages(lang) 拉远端消息目录。
 *
 * RED 预期：全部用例 FAIL——log-page-size-select / log-detail / log-chain-* /
 *   log-copy-* / log-chain-view* 当前均不存在，首个 getByTestId 即抛 not found。
 *
 * 说明：合同文本写成 user.click(within(row).getByTestId('log-row'))；因现有 #496/#930
 *   契约用 findAllByTestId('log-row') 且每记录唯一 testid，GREEN 不得再加同名 testid，
 *   故此处按「点击唯一的 log-row 元素本身」解释（user.click(row)），语义为「点行展开详情」。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LogsPage } from './logs';
import { fetchLogMessages, fetchLogs } from '../api/logs';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/logs', () => ({ fetchLogs: vi.fn(), fetchLogMessages: vi.fn() }));

const fetchLogsMock = vi.mocked(fetchLogs);
const fetchLogMessagesMock = vi.mocked(fetchLogMessages);

/** 契约结构镜像（GREEN 类型从 api/logs.ts 导出；本文件内联镜像供 mock 播种） */
interface LogRecordDto {
  timestamp: string;
  level: string;
  logger: string;
  caller_type: string;
  caller_name: string;
  event: string;
  message_key: string;
  params: Record<string, unknown>;
  correlation_id: string;
  trace_id?: string | null;
  span_id?: string | null;
  project_id?: number | null;
  entity_id?: string | null;
  duration_ms?: number | null;
  error_code?: string | null;
  stack?: string | null;
}

interface LogsResponseDto {
  items: LogRecordDto[];
  total: number;
  offset: number;
  limit: number;
}

function makeRecord(overrides: Partial<LogRecordDto> = {}): LogRecordDto {
  return {
    timestamp: '2026-09-04T01:00:00.000Z',
    level: 'INFO',
    logger: 'renderer',
    caller_type: 'frontend',
    caller_name: 'WritingPage',
    event: 'create_chapter',
    message_key: 'log.event.create_chapter',
    params: { title: '第一章' },
    correlation_id: '',
    ...overrides,
  };
}

function makePage(overrides: Partial<LogsResponseDto> = {}): LogsResponseDto {
  return { items: [], total: 0, offset: 0, limit: 50, ...overrides };
}

function renderLogsPage() {
  return render(
    <MemoryRouter>
      <LogsPage />
    </MemoryRouter>,
  );
}

/** 最近一次 fetchLogs 调用实参 */
function lastLogsParams(): Record<string, unknown> {
  const calls = fetchLogsMock.mock.calls;
  return calls[calls.length - 1][0] as Record<string, unknown>;
}

function logsCallCount(): number {
  return fetchLogsMock.mock.calls.length;
}

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  fetchLogsMock.mockReset();
  fetchLogMessagesMock.mockReset();
  fetchLogsMock.mockResolvedValue(makePage());
  fetchLogMessagesMock.mockResolvedValue({});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('日志页 — #932 页大小 Select（S1）', () => {
  it('【R】结构+默认：log-page-size-select 存在且显示 50，选项 10/25/50/100', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    const pageSize = screen.getByTestId('log-page-size-select');
    expect(pageSize).toHaveTextContent('50');
    expect(pageSize).toHaveAttribute('aria-label', '每页条数');

    await user.click(pageSize);
    const options = await screen.findAllByRole('option');
    expect(options.map((o) => o.textContent)).toEqual(
      expect.arrayContaining(['10', '25', '50', '100']),
    );
    await user.keyboard('{Escape}');
  });

  it('【R】切到 25 → 新查询 {level:INFO,WARN,ERROR, limit:25, page:0}', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByTestId('log-page-size-select'));
    await user.click(await screen.findByRole('option', { name: '25' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 25, page: 0 });
  });

  it('【R】先翻到 page:1 再切大小 10 → 新查询 limit:10 + page 归 0', async () => {
    fetchLogsMock.mockResolvedValue(makePage({ items: [makeRecord()], total: 120, offset: 0 }));
    const user = userEvent.setup();
    renderLogsPage();
    await screen.findByTestId('log-row');

    await user.click(screen.getByTestId('log-page-next'));
    await waitFor(() =>
      expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 1 }),
    );

    await user.click(screen.getByTestId('log-page-size-select'));
    await user.click(await screen.findByRole('option', { name: '10' }));
    await waitFor(() => expect(logsCallCount()).toBe(3));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 10, page: 0 });
  });

  it('【R】分页器联动：limit=10,total=120 → 页面 12；next → limit:10,page:1', async () => {
    fetchLogsMock.mockResolvedValue(makePage({ items: [makeRecord()], total: 120, offset: 0 }));
    const user = userEvent.setup();
    renderLogsPage();
    await screen.findByTestId('log-row');

    await user.click(screen.getByTestId('log-page-size-select'));
    await user.click(await screen.findByRole('option', { name: '10' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));

    expect(screen.getByTestId('log-page-info')).toHaveTextContent('第 1 / 12 页 · 共 120 条');
    await user.click(screen.getByTestId('log-page-next'));
    await waitFor(() => expect(logsCallCount()).toBe(3));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 10, page: 1 });
  });
});

describe('日志页 — #932 行点击详情（S2）', () => {
  const errorRec = () =>
    makeRecord({
      timestamp: '2026-09-04T01:02:03.456+08:00',
      level: 'ERROR',
      caller_type: 'api',
      caller_name: 'POST /api/v1/chapters',
      event: 'http_fail',
      message_key: 'log.call.api',
      params: { project_id: 'p-7', status_code: 404 },
      correlation_id: 'c-42',
      trace_id: 'e9f2a3b4c5d6e7f80123456789abcdef',
      duration_ms: 1234.5,
      error_code: 'E404',
      stack: 'Traceback...\nRuntimeError: boom',
    });

  it('【R】点 log-row → 展开 log-detail（时间/消息/参数/错误码/trace/关联ID/时长/stack），再点收起', async () => {
    const user = userEvent.setup();
    fetchLogsMock.mockResolvedValue(makePage({ items: [errorRec()], total: 1, offset: 0 }));
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    expect(screen.queryByTestId('log-detail')).not.toBeInTheDocument();

    await user.click(row);

    const detail = screen.getByTestId('log-detail');
    expect(within(detail).getByTestId('log-detail-timestamp')).toHaveTextContent('2026-09-04T01:02:03.456+08:00');
    expect(within(detail).getByTestId('log-detail-message-key')).toHaveTextContent('log.call.api');
    // message 为插值结果（非空即可）
    expect(within(detail).getByTestId('log-detail-message').textContent).toBeTruthy();
    // params 用 JSON.stringify(params, null, 2) 渲染（非 k=v 摘要）
    expect(within(detail).getByTestId('log-detail-params')).toHaveTextContent('"project_id": "p-7"');
    expect(within(detail).getByTestId('log-detail-error-code')).toHaveTextContent('E404');
    expect(within(detail).getByTestId('log-detail-trace')).toHaveTextContent('e9f2a3b4c5d6e7f80123456789abcdef');
    expect(within(detail).getByTestId('log-detail-correlation')).toHaveTextContent('c-42');
    expect(within(detail).getByTestId('log-detail-duration')).toHaveTextContent('1.2s');
    expect(within(detail).getByTestId('log-detail-stack')).toHaveTextContent('RuntimeError: boom');

    // 再点一次 → 收起
    await user.click(row);
    expect(screen.queryByTestId('log-detail')).not.toBeInTheDocument();
  });

  it('【R】复制：点 log-copy-trace-btn → navigator.clipboard.writeText(trace_id)', async () => {
    // 镜像 McpSettingsCard.test 先例：fireEvent.click（不经 userEvent.setup，
    // 后者会无条件替换 navigator.clipboard 为内部 stub 吞掉 spy）。
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    fetchLogsMock.mockResolvedValue(makePage({ items: [errorRec()], total: 1, offset: 0 }));
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    fireEvent.click(row);
    screen.getByTestId('log-detail');

    fireEvent.click(screen.getByTestId('log-copy-trace-btn'));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('e9f2a3b4c5d6e7f80123456789abcdef'));
  });

  it('【R】键盘可达：log-row 可聚焦（tabindex），Enter 展开 log-detail，aria-expanded 切换', async () => {
    fetchLogsMock.mockResolvedValue(makePage({ items: [errorRec()], total: 1, offset: 0 }));
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    expect(row).toHaveAttribute('tabindex');
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(screen.getByTestId('log-detail')).toBeInTheDocument();
    expect(row).toHaveAttribute('aria-expanded', 'true');
  });

  it('【R】守护 #930：log-stack-toggle 只展开 log-stack 不触发 log-detail；详情内 stack 用 log-detail-stack', async () => {
    const user = userEvent.setup();
    fetchLogsMock.mockResolvedValue(makePage({ items: [errorRec()], total: 1, offset: 0 }));
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    // 行内 stack 摘要折叠 → 展开，但不得触发 log-detail（stopPropagation 守护）
    await user.click(within(row).getByTestId('log-stack-toggle'));
    expect(within(row).getByTestId('log-stack')).toBeInTheDocument();
    expect(screen.queryByTestId('log-detail')).not.toBeInTheDocument();

    // 点行展开详情 → 其中 stack 区块 id 是 log-detail-stack（与 log-stack 互不冲突）
    await user.click(row);
    expect(screen.getByTestId('log-detail-stack')).toBeInTheDocument();
    expect(screen.getByTestId('log-detail-stack')).not.toBe(screen.getByTestId('log-stack'));
  });

  it('【R】非 ERROR（WARN）行展开详情 → 无 log-detail-stack（stack 仅 ERROR 展示）', async () => {
    const user = userEvent.setup();
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [
          makeRecord({
            level: 'WARN',
            caller_type: 'api',
            caller_name: 'query_logs',
            event: 'query_logs',
            message_key: 'log.call.query_logs',
            params: { project_id: 'p-7' },
            correlation_id: 'c-42',
            trace_id: null,
            duration_ms: 50,
          }),
        ],
        total: 1,
        offset: 0,
      }),
    );
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    await user.click(row);
    expect(screen.getByTestId('log-detail')).toBeInTheDocument();
    expect(screen.queryByTestId('log-detail-stack')).not.toBeInTheDocument();
  });
});

describe('日志页 — #932 只看此链（S3）', () => {
  const recWithTrace = () =>
    makeRecord({
      level: 'ERROR',
      caller_type: 'api',
      caller_name: 'POST /api/v1/chapters',
      event: 'http_fail',
      message_key: 'log.call.api',
      params: { project_id: 'p-7', status_code: 404 },
      correlation_id: 'c-42',
      trace_id: 't-1',
      duration_ms: 50,
      error_code: 'E404',
      stack: 'boom',
    });

  it('【R】trace 优先：点 log-chain-only-btn → 重查 +trace_id:t-1，筛选栏出现 log-chain-chip', async () => {
    const user = userEvent.setup();
    fetchLogsMock.mockResolvedValue(makePage({ items: [recWithTrace()], total: 1, offset: 0 }));
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    await user.click(row);
    screen.getByTestId('log-detail');

    await user.click(screen.getByTestId('log-chain-only-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0, trace_id: 't-1' });

    const chip = screen.getByTestId('log-chain-chip');
    expect(chip).toHaveTextContent('t-1');
  });

  it('【R】仅 correlation_id（trace null）→ 重查 +correlation_id:c-9 且关联ID输入回填', async () => {
    const user = userEvent.setup();
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [
          makeRecord({
            level: 'ERROR',
            caller_type: 'api',
            caller_name: 'get_chapter_summary',
            event: 'get_chapter_summary',
            message_key: 'log.call.get_chapter_summary',
            params: {},
            correlation_id: 'c-9',
            trace_id: null,
          }),
        ],
        total: 1,
        offset: 0,
      }),
    );
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    await user.click(row);
    screen.getByTestId('log-detail');

    await user.click(screen.getByTestId('log-chain-only-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({
      level: 'INFO,WARN,ERROR',
      limit: 50,
      page: 0,
      correlation_id: 'c-9',
    });
    expect(lastLogsParams()).not.toHaveProperty('trace_id');
    expect(screen.getByTestId('log-correlation-input')).toHaveValue('c-9');
  });

  it('【R】trace 与 correlation 皆空 → log-chain-only-btn disabled 且 title 非空（提示）', async () => {
    const user = userEvent.setup();
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [
          makeRecord({
            level: 'ERROR',
            caller_type: 'api',
            caller_name: 'empty',
            event: 'empty',
            message_key: 'log.call.empty',
            params: {},
            correlation_id: '',
            trace_id: null,
          }),
        ],
        total: 1,
        offset: 0,
      }),
    );
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    await user.click(row);
    screen.getByTestId('log-detail');

    const btn = screen.getByTestId('log-chain-only-btn');
    expect(btn).toBeDisabled();
    expect(btn.getAttribute('title')).toBeTruthy();
  });

  it('【R】清空链过滤：点 log-chain-clear-btn → 回退默认参数且 log-chain-chip 消失', async () => {
    const user = userEvent.setup();
    fetchLogsMock.mockResolvedValue(makePage({ items: [recWithTrace()], total: 1, offset: 0 }));
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    await user.click(row);
    screen.getByTestId('log-detail');
    await user.click(screen.getByTestId('log-chain-only-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));

    await user.click(within(screen.getByTestId('log-chain-chip')).getByTestId('log-chain-clear-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(3));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0 });
    expect(screen.queryByTestId('log-chain-chip')).not.toBeInTheDocument();
  });

  it('【R】重置归零：链过滤激活后点 log-reset-btn → 回默认参数且 log-chain-chip 消失', async () => {
    const user = userEvent.setup();
    fetchLogsMock.mockResolvedValue(makePage({ items: [recWithTrace()], total: 1, offset: 0 }));
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    await user.click(row);
    screen.getByTestId('log-detail');
    await user.click(screen.getByTestId('log-chain-only-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));

    await user.click(screen.getByTestId('log-reset-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(3));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0 });
    expect(screen.queryByTestId('log-chain-chip')).not.toBeInTheDocument();
  });
});

describe('日志页 — #932 调用链视图（S4）', () => {
  const mainWithTrace = () =>
    makeRecord({
      level: 'ERROR',
      caller_type: 'api',
      caller_name: 'POST /api/v1/chapters',
      event: 'http_fail',
      message_key: 'log.call.api',
      params: { project_id: 'p-7', status_code: 404 },
      correlation_id: 'c-42',
      trace_id: 't-9',
      duration_ms: 50,
      error_code: 'E404',
      stack: 'boom',
    });

  it('【R】点 log-chain-view-btn → 精确查询 {trace_id,limit:200} + 渲染 log-chain-view（主列表隐藏）', async () => {
    const user = userEvent.setup();
    fetchLogsMock
      .mockResolvedValueOnce(makePage({ items: [mainWithTrace()], total: 1, offset: 0 }))
      .mockResolvedValueOnce(makePage({ items: [mainWithTrace()], total: 1, offset: 0 }));
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    await user.click(row);
    screen.getByTestId('log-detail');

    await user.click(screen.getByTestId('log-chain-view-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ trace_id: 't-9', limit: 200 });
    expect(screen.getByTestId('log-chain-view')).toBeInTheDocument();
    expect(screen.queryByTestId('log-row')).not.toBeInTheDocument();
  });

  it('【R】时间序：链节点 DOM 顺序按 timestamp 升序，各节点渲染 duration 与 error_code', async () => {
    const user = userEvent.setup();
    const recA = makeRecord({
      timestamp: '2026-09-04T00:01:00Z',
      level: 'ERROR',
      caller_type: 'api',
      caller_name: 'chain-a',
      event: 'a',
      message_key: 'log.call.a',
      params: {},
      correlation_id: 'c-x',
      trace_id: 't-9',
      duration_ms: 1300,
      error_code: 'E301',
      stack: null,
    });
    const recB = makeRecord({
      timestamp: '2026-09-04T00:02:00Z',
      level: 'ERROR',
      caller_type: 'api',
      caller_name: 'chain-b',
      event: 'b',
      message_key: 'log.call.b',
      params: {},
      correlation_id: 'c-x',
      trace_id: 't-9',
      duration_ms: 2600,
      stack: null, // 无 error_code → 节点不渲染 log-chain-node-error-code
    });
    const recC = makeRecord({
      timestamp: '2026-09-04T00:03:00Z',
      level: 'ERROR',
      caller_type: 'api',
      caller_name: 'chain-c',
      event: 'c',
      message_key: 'log.call.c',
      params: {},
      correlation_id: 'c-x',
      trace_id: 't-9',
      duration_ms: 3900,
      error_code: 'E303',
      stack: null,
    });
    // 链查询 mock：降序给 items（T3 最新在前），面板内须按 timestamp 升序渲染
    fetchLogsMock
      .mockResolvedValueOnce(makePage({ items: [mainWithTrace()], total: 1, offset: 0 }))
      .mockResolvedValueOnce(makePage({ items: [recC, recA, recB], total: 3, offset: 0 }));
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    await user.click(row);
    screen.getByTestId('log-detail');

    await user.click(screen.getByTestId('log-chain-view-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));

    const nodes = await screen.findAllByTestId('log-chain-node');
    expect(nodes).toHaveLength(3);
    expect(nodes[0]).toHaveTextContent('00:01:00');
    expect(nodes[1]).toHaveTextContent('00:02:00');
    expect(nodes[2]).toHaveTextContent('00:03:00');
    expect(within(nodes[0]).getByTestId('log-chain-node-duration')).toHaveTextContent('1.3s');
    expect(within(nodes[1]).getByTestId('log-chain-node-duration')).toHaveTextContent('2.6s');
    expect(within(nodes[2]).getByTestId('log-chain-node-duration')).toHaveTextContent('3.9s');
    expect(within(nodes[0]).getByTestId('log-chain-node-error-code')).toHaveTextContent('E301');
    expect(within(nodes[1]).queryByTestId('log-chain-node-error-code')).not.toBeInTheDocument();
    expect(within(nodes[2]).getByTestId('log-chain-node-error-code')).toHaveTextContent('E303');
  });

  it('【R】节点可展开详情：点第 0 个 log-chain-node → 其内出现 log-detail（message-key 等于该记录）', async () => {
    const user = userEvent.setup();
    const recA = makeRecord({
      timestamp: '2026-09-04T00:01:00Z',
      level: 'ERROR',
      caller_type: 'api',
      caller_name: 'chain-a',
      event: 'a',
      message_key: 'log.call.a',
      params: {},
      correlation_id: 'c-x',
      trace_id: 't-9',
      duration_ms: 1300,
      error_code: 'E301',
      stack: null,
    });
    const recC = makeRecord({
      timestamp: '2026-09-04T00:03:00Z',
      level: 'ERROR',
      caller_type: 'api',
      caller_name: 'chain-c',
      event: 'c',
      message_key: 'log.call.c',
      params: {},
      correlation_id: 'c-x',
      trace_id: 't-9',
      duration_ms: 3900,
      error_code: 'E303',
      stack: null,
    });
    fetchLogsMock
      .mockResolvedValueOnce(makePage({ items: [mainWithTrace()], total: 1, offset: 0 }))
      .mockResolvedValueOnce(makePage({ items: [recA, recC], total: 2, offset: 0 }));
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    await user.click(row);
    screen.getByTestId('log-detail');

    await user.click(screen.getByTestId('log-chain-view-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));

    const nodes = await screen.findAllByTestId('log-chain-node');
    await user.click(nodes[0]); // 升序第 0 个 = 最旧 00:01 → recA
    const detail = within(nodes[0]).getByTestId('log-detail');
    expect(within(detail).getByTestId('log-detail-message-key')).toHaveTextContent('log.call.a');
  });

  it('【R】返回：点 log-chain-back-btn → 链视图消失、log-row 恢复；刷新回主查询（limit 保持切换值）', async () => {
    const user = userEvent.setup();
    const mainPage = () => makePage({ items: [mainWithTrace()], total: 120, offset: 0 });
    fetchLogsMock
      .mockResolvedValueOnce(mainPage())
      .mockResolvedValueOnce(mainPage())
      .mockResolvedValueOnce(mainPage())
      .mockResolvedValueOnce(mainPage());
    renderLogsPage();

    await screen.findByTestId('log-row');
    // 先切页大小到 25（验证「limit 保持切换后的值」）
    await user.click(screen.getByTestId('log-page-size-select'));
    await user.click(await screen.findByRole('option', { name: '25' }));
    await waitFor(() => expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 25, page: 0 }));

    const row = await screen.findByTestId('log-row');
    await user.click(row);
    screen.getByTestId('log-detail');
    await user.click(screen.getByTestId('log-chain-view-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(3));
    screen.getByTestId('log-chain-view');

    await user.click(screen.getByTestId('log-chain-back-btn'));
    await waitFor(() => expect(screen.queryByTestId('log-chain-view')).not.toBeInTheDocument());
    expect(await screen.findByTestId('log-row')).toBeInTheDocument();

    await user.click(screen.getByTestId('log-refresh-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(4));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 25, page: 0 });
  });

  it('【R】双语抽查：lang=en → 只看此链/查看完整调用链 走 en 文案', async () => {
    useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'en' });
    const user = userEvent.setup();
    fetchLogsMock.mockResolvedValue(makePage({ items: [mainWithTrace()], total: 1, offset: 0 }));
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    await user.click(row);
    screen.getByTestId('log-detail');

    expect(screen.getByTestId('log-chain-only-btn')).toHaveTextContent('Filter to this chain');
    expect(screen.getByTestId('log-chain-view-btn')).toHaveTextContent('View full call chain');
  });
});
