/**
 * #930 日志卡片可读性契约测试（fix/log-cards-930）。
 *
 * 本文件 = 契约。用例自 logs.test.tsx 机械搬移（900 行护栏，#478 先例：拆兄弟文件，
 * 断言/标题/注释逐字保持）；logs.test.tsx 头部「#930 卡片可读性契约」说明块随迁至此。
 *
 * 契约要点：
 * - log.call.* message_key 无精确词条时回退通用词条 t('log.call.generic')
 *   （zh「调用 {caller_name}」/ en「Call: {caller_name}」），禁止直出裸 key；
 *   远端目录/本地字典的精确词条仍优先于通用兜底。
 * - 插值上下文 = {caller_name, event, ...params}（params 同名键覆盖上下文）。
 * - 时长格式化 log-duration：<1000ms → 两位小数 ms（125.00ms）；<60s → 一位小数 s
 *   （1.3s）；≥60s → m+s（1m42s）。
 * - WARN/ERROR 且 params 非空 → 渲染 log-params 摘要行（k=v 文本）；INFO 不渲染。
 * - ERROR 且 stack 非空 → log-stack-toggle 按钮（zh 详情 / en Details），点击展开
 *   log-stack <pre>，再点收起；无 stack → 无按钮。
 *
 * 接线（Mock 依赖，与 logs.test.tsx 同契约）：
 * - LogsPage 必须 import { fetchLogs, fetchLogMessages } from '../api/logs'
 * - 挂载即查默认参数；fetchLogMessages(lang) 拉远端消息目录
 *
 * RED 预期：#930 用例当前必 FAIL——无 log.call.generic 词条回退（裸 key 直出）、
 * duration 裸浮点、无 log-params 行、无 log-stack 展开。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LogsPage } from './logs';
import { fetchLogMessages, fetchLogs } from '../api/logs';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/logs', () => ({ fetchLogs: vi.fn(), fetchLogMessages: vi.fn() }));

const fetchLogsMock = vi.mocked(fetchLogs);
const fetchLogMessagesMock = vi.mocked(fetchLogMessages);

/** 契约结构镜像（与 logs.test.tsx 同源；GREEN 类型从 api/logs.ts 导出） */
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

describe('日志页 — #930 卡片可读性（log.call 词条 / duration 格式化 / params 摘要 / stack）', () => {
  it('【R】log.call.* 无精确词条 → 通用回退可读文本（zh「调用 {caller_name}」），非裸 key', async () => {
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [
          makeRecord({
            level: 'WARN',
            caller_type: 'api',
            caller_name: 'query_logs',
            event: 'query_logs',
            message_key: 'log.call.query_logs',
            params: {},
          }),
        ],
        total: 1,
      }),
    );
    renderLogsPage();
    const row = await screen.findByTestId('log-row');
    expect(within(row).getByTestId('log-message')).toHaveTextContent('调用 query_logs');
    expect(within(row).getByTestId('log-message')).not.toHaveTextContent('log.call.query_logs');
  });

  it('【R】lang=en → log.call.* 通用回退走 en 文案「Call: {caller_name}」', async () => {
    useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'en' });
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [
          makeRecord({
            caller_type: 'api',
            caller_name: 'get_chapter_summary',
            event: 'get_chapter_summary',
            message_key: 'log.call.get_chapter_summary',
            params: {},
          }),
        ],
        total: 1,
      }),
    );
    renderLogsPage();
    const row = await screen.findByTestId('log-row');
    expect(within(row).getByTestId('log-message')).toHaveTextContent('Call: get_chapter_summary');
  });

  it('【R】远端目录精确词条优先于通用回退', async () => {
    fetchLogMessagesMock.mockResolvedValue({
      'log.call.invoke': '远端调用 {caller_name}',
      'log.call.generic': '远端通用 {caller_name}',
    });
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [
          makeRecord({
            caller_type: 'agent',
            caller_name: 'invoke',
            event: 'invoke',
            message_key: 'log.call.invoke',
            params: {},
          }),
        ],
        total: 1,
      }),
    );
    renderLogsPage();
    const row = await screen.findByTestId('log-row');
    expect(within(row).getByTestId('log-message')).toHaveTextContent('远端调用 invoke');
  });

  it('【R】duration 三档格式化：<1s→125.00ms、<60s→1.3s、≥60s→1m42s', async () => {
    const mk = (d: number) =>
      makeRecord({ message_key: 'log.event.page_load', params: { page: `d${d}` }, duration_ms: d });
    fetchLogsMock.mockResolvedValue(
      makePage({ items: [mk(125), mk(1300), mk(102000)], total: 3 }),
    );
    renderLogsPage();
    const rows = await screen.findAllByTestId('log-row');
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByTestId('log-duration')).toHaveTextContent('125.00ms');
    expect(within(rows[1]).getByTestId('log-duration')).toHaveTextContent('1.3s');
    expect(within(rows[2]).getByTestId('log-duration')).toHaveTextContent('1m42s');
  });

  it('【R】WARN/ERROR 且 params 非空 → log-params 摘要行（k=v）；INFO 不渲染', async () => {
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [
          makeRecord({
            level: 'WARN',
            caller_type: 'api',
            caller_name: 'get_chapter_summary',
            event: 'get_chapter_summary',
            message_key: 'log.call.get_chapter_summary',
            params: { project_id: 7, error: '章节不存在' },
          }),
          makeRecord({ level: 'INFO', params: { title: '第一章' } }),
        ],
        total: 2,
      }),
    );
    renderLogsPage();
    const rows = await screen.findAllByTestId('log-row');
    expect(within(rows[0]).getByTestId('log-params')).toHaveTextContent('project_id=7');
    expect(within(rows[0]).getByTestId('log-params')).toHaveTextContent('error=章节不存在');
    expect(within(rows[1]).queryByTestId('log-params')).not.toBeInTheDocument();
  });

  it('【R】ERROR 带 stack → 点 log-stack-toggle 展开 log-stack，再点收起；无 stack 无按钮', async () => {
    const user = userEvent.setup();
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [
          makeRecord({
            level: 'ERROR',
            caller_type: 'api',
            caller_name: 'broken',
            event: 'broken',
            message_key: 'log.call.broken',
            params: {},
            stack: 'Traceback (most recent call last):\nValueError: boom',
          }),
          makeRecord({
            level: 'ERROR',
            caller_type: 'api',
            caller_name: 'no_stack',
            event: 'no_stack',
            message_key: 'log.call.no_stack',
            params: {},
          }),
        ],
        total: 2,
      }),
    );
    renderLogsPage();
    const rows = await screen.findAllByTestId('log-row');

    // 行 1：有 stack → 有按钮，默认收起
    const toggle = within(rows[0]).getByTestId('log-stack-toggle');
    expect(within(rows[0]).queryByTestId('log-stack')).not.toBeInTheDocument();
    await user.click(toggle);
    const stack = within(rows[0]).getByTestId('log-stack');
    expect(stack).toHaveTextContent('ValueError: boom');
    await user.click(toggle);
    expect(within(rows[0]).queryByTestId('log-stack')).not.toBeInTheDocument();

    // 行 2：无 stack → 无按钮
    expect(within(rows[1]).queryByTestId('log-stack-toggle')).not.toBeInTheDocument();
  });
});
