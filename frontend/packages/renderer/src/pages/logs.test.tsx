/**
 * #496 统一日志页 RED 阶段契约测试（contract-496.md §6）
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/pages/logs.tsx（命名导出 LogsPage），必须匹配：
 *
 * 接线（Mock 依赖）：
 * - LogsPage 必须 import { fetchLogs, fetchLogMessages } from '../api/logs'
 *   （本文件 vi.mock 该模块；GREEN 若改 import 源 → mock 不生效 → 测试炸，属契约违约）
 * - 项目下拉选项来自 useProjectStore.projects（测试经 setState 播种）；页面**不**默认按
 *   当前项目过滤（初始态 = 全部项目，project_id 不出现在挂载请求）
 * - 挂载即查：fetchLogs 默认 { level:'INFO,WARN,ERROR', limit:50, page:0 }
 *   （tab=all 不传 caller_type；level=INFO 默认 → DEBUG 记录不出现）
 * - 挂载 + lang（useThemeStore.lang）变化时 fetchLogMessages(lang) 拉远端消息目录；
 *   远端失败静默（console.warn）回退本地字典
 *
 * data-testid 即契约（§6.1）：
 * - logs-page 根；logs-title（h1=t('logs.title')='日志'）；logs-sub（t('logs.sub')）
 * - 分类 tab（role=tab）：log-tab-all / log-tab-kernel / log-tab-gui / log-tab-ai
 * - log-level-select（Radix Select，trigger 文案 = 当前级别标签 t('logs.level.*')）
 * - log-project-select（Radix Select；选项 = useProjectStore.projects.name + 「全部项目」）
 * - log-q-input / log-correlation-input（textbox，aria-label 含 placeholder）
 * - log-from-input / log-to-input（type=datetime-local，aria-label=开始时间/结束时间）
 * - log-search-btn（文案 t('logs.search')='查询'）、log-reset-btn（'重置'）、
 *   log-refresh-btn（'刷新'）
 * - log-list 列表容器；log-row 每记录：行内 log-level-badge / log-message /
 *   log-timestamp / log-caller-type / log-caller-name；可选 log-duration /
 *   log-error-code / log-correlation
 * - log-empty（'暂无日志'）/ log-loading（'加载日志…'）/ log-error（'日志加载失败'）
 * - log-page-prev / log-page-next / log-page-info
 *
 * 查询参数状态机（§6.2）：
 * - kernel tab → caller_type:'api,agent,tool,cli,mcp'（page 归 0 立即重查）；
 *   gui → 'frontend'；ai → 'llm'；all → caller_type 不出现
 * - level DEBUG → level 键不出现（全量）；WARN → 'WARN,ERROR'；ERROR → 'ERROR'；
 *   INFO（选回默认）→ 'INFO,WARN,ERROR'
 * - 项目选中（UUID）→ project_id；选回「全部项目」→ 不传
 * - q/correlation_id/from/to 经「查询」按钮提交（空白不传；datetime-local 值原样）
 * - 重置 → 回默认参数 + UI 控件归位；刷新 → 当前条件原样重查（计数 +1）
 * - prev 在 page=0 disabled；next 在 (page+1)*50>=total disabled
 * - 查询失败 → log-error（列表不渲染）；total=0 → log-empty
 * - 过期响应防护：两次慢查询乱序返回 → 最终渲染第二次数据
 *
 * message 渲染契约（§6.3）：log-message = interpolate(远端目录[message_key] ??
 * 本地 t(message_key), params)——远端目录命中 → 远端模板插值；远端缺键 → 本地 t()
 * 插值；lang=en → en 文案。用例 29-32 以 zh 逐字文案断言（§4.2）。
 *
 * #930 卡片可读性契约（log.call 词条回退 / duration 三档格式化 / params 摘要行 /
 * stack 展开）已逐字搬移至兄弟文件 logs-card-readable-930.test.tsx（900 行护栏，
 * #478 先例）；本文件仅保留 L~660 既有 duration 断言的 #930 升级（1234 → 1.2s）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LogsPage } from './logs';
import { fetchLogMessages, fetchLogs } from '../api/logs';
import { useProjectStore, type Project } from '../stores/project';
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

const PAGE_A_UUID = 'u-1';

function makeProject(id: string, name: string): Project {
  return {
    id,
    name,
    tags: [],
    language: 'zh-CN',
    target_words: 100000,
    config: {},
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
  };
}

/** 播种项目列表（缺省空；currentProjectId 缺省 null = 未选项目） */
function seedProjects(currentProjectId: string | null = null): void {
  useProjectStore.setState({
    projects: [makeProject(PAGE_A_UUID, '测试项目A'), makeProject('u-2', '测试项目B')],
    currentProjectId,
    loading: false,
    error: null,
  });
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
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  fetchLogsMock.mockReset();
  fetchLogMessagesMock.mockReset();
  fetchLogsMock.mockResolvedValue(makePage());
  fetchLogMessagesMock.mockResolvedValue({});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('日志页 — 挂载与默认查询（§6.2）', () => {
  it('【R】挂载即查：fetchLogs 默认参数 {level:INFO,WARN,ERROR,limit:50,page:0} + fetchLogMessages(lang) 拉远端目录', async () => {
    renderLogsPage();

    await waitFor(() => {
      expect(fetchLogsMock).toHaveBeenCalledWith({ level: 'INFO,WARN,ERROR', limit: 50, page: 0 });
    });
    expect(fetchLogMessagesMock).toHaveBeenCalledWith('zh');
    expect(screen.getByTestId('logs-page')).toBeInTheDocument();
  });

  it('【R】结构元素齐全：标题/副标题/四 tab/级别+项目下拉/筛选输入/查询重置刷新按钮/分页控件', async () => {
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    expect(screen.getByTestId('logs-title')).toHaveTextContent('日志');
    expect(screen.getByTestId('logs-sub')).toHaveTextContent('内核 / GUI / AI 统一日志');

    // 分类 tab（role=tab），aria-selected 表当前
    expect(screen.getByRole('tab', { name: '全部' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: '内核' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'GUI' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'AI' })).toBeInTheDocument();

    // 级别下拉默认 INFO 文案
    expect(screen.getByTestId('log-level-select')).toHaveTextContent('INFO');
    // 项目下拉默认「全部项目」
    expect(screen.getByTestId('log-project-select')).toHaveTextContent('全部项目');

    // 筛选输入（aria-label 锚定）
    expect(screen.getByRole('textbox', { name: /搜索日志内容/ })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /关联 ID/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/开始时间/)).toBeInTheDocument();
    expect(screen.getByLabelText(/结束时间/)).toBeInTheDocument();

    // 按钮文案（§4.2 逐字）
    expect(screen.getByTestId('log-search-btn')).toHaveTextContent('查询');
    expect(screen.getByTestId('log-reset-btn')).toHaveTextContent('重置');
    expect(screen.getByTestId('log-refresh-btn')).toHaveTextContent('刷新');

    // 分页控件
    expect(screen.getByTestId('log-page-prev')).toBeInTheDocument();
    expect(screen.getByTestId('log-page-next')).toBeInTheDocument();
    expect(screen.getByTestId('log-page-info')).toBeInTheDocument();
  });

  it('【R】默认全部项目：currentProjectId 已播种 → 挂载请求仍无 project_id（不按当前项目过滤）', async () => {
    seedProjects(PAGE_A_UUID);
    renderLogsPage();

    await waitFor(() => expect(logsCallCount()).toBe(1));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0 });
  });
});

describe('日志页 — 分类 tab → caller_type（§6.2）', () => {
  it('【R】点 kernel tab → 立即重查 + caller_type:api,agent,tool,cli,mcp', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByRole('tab', { name: '内核' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({
      level: 'INFO,WARN,ERROR',
      limit: 50,
      page: 0,
      caller_type: 'api,agent,tool,cli,mcp',
    });
  });

  it('【R】kernel tab 切换 page 归 0：先翻页到 page:1 再切 kernel → 新查询 page:0 + caller_type', async () => {
    fetchLogsMock.mockResolvedValue(makePage({ items: [makeRecord()], total: 120, offset: 0 }));
    const user = userEvent.setup();
    renderLogsPage();
    await screen.findByTestId('log-row');

    await user.click(screen.getByTestId('log-page-next'));
    await waitFor(() => expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 1 }));

    await user.click(screen.getByRole('tab', { name: '内核' }));
    await waitFor(() => expect(logsCallCount()).toBe(3));
    expect(lastLogsParams()).toEqual({
      level: 'INFO,WARN,ERROR',
      limit: 50,
      page: 0,
      caller_type: 'api,agent,tool,cli,mcp',
    });
  });

  it('【R】点 gui tab → caller_type:frontend', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByRole('tab', { name: 'GUI' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0, caller_type: 'frontend' });
  });

  it('【R】点 ai tab → caller_type:llm', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByRole('tab', { name: 'AI' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0, caller_type: 'llm' });
  });

  it('【R】点 all tab → caller_type 不出现（从 kernel 切回全部）', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByRole('tab', { name: '内核' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));

    await user.click(screen.getByRole('tab', { name: '全部' }));
    await waitFor(() => expect(logsCallCount()).toBe(3));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0 });
  });
});

describe('日志页 — level 下拉（§6.2）', () => {
  it('【R】选项齐全：DEBUG/INFO/WARN/ERROR 四个 level 选项', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByTestId('log-level-select'));
    const options = await screen.findAllByRole('option');
    expect(options.map((o) => o.textContent)).toEqual(
      expect.arrayContaining(['DEBUG', 'INFO', 'WARN', 'ERROR']),
    );
    await user.keyboard('{Escape}');
  });

  it('【R】level→DEBUG：level 键不出现（全量含 DEBUG）', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByTestId('log-level-select'));
    await user.click(await screen.findByRole('option', { name: 'DEBUG' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ limit: 50, page: 0 });
  });

  it('【R】level→WARN：level:WARN,ERROR', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByTestId('log-level-select'));
    await user.click(await screen.findByRole('option', { name: 'WARN' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ level: 'WARN,ERROR', limit: 50, page: 0 });
  });

  it('【R】level→ERROR：level:ERROR', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByTestId('log-level-select'));
    await user.click(await screen.findByRole('option', { name: 'ERROR' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ level: 'ERROR', limit: 50, page: 0 });
  });

  it('【R】level→INFO（选回默认）：level 回到 INFO,WARN,ERROR', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByTestId('log-level-select'));
    await user.click(await screen.findByRole('option', { name: 'WARN' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));

    await user.click(screen.getByTestId('log-level-select'));
    await user.click(await screen.findByRole('option', { name: 'INFO' }));
    await waitFor(() => expect(logsCallCount()).toBe(3));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0 });
  });
});

describe('日志页 — 项目选择（§6.2）', () => {
  it('【R】选中项目（UUID u-1）→ 立即重查 + project_id:u-1（其余默认不变）', async () => {
    seedProjects();
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByTestId('log-project-select'));
    await user.click(await screen.findByRole('option', { name: '测试项目A' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({
      level: 'INFO,WARN,ERROR',
      limit: 50,
      page: 0,
      project_id: PAGE_A_UUID,
    });
    expect(screen.getByTestId('log-project-select')).toHaveTextContent('测试项目A');
  });

  it('【R】选回「全部项目」→ project_id 不传（回默认参数）', async () => {
    seedProjects();
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByTestId('log-project-select'));
    await user.click(await screen.findByRole('option', { name: '测试项目A' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));

    await user.click(screen.getByTestId('log-project-select'));
    await user.click(await screen.findByRole('option', { name: '全部项目' }));
    await waitFor(() => expect(logsCallCount()).toBe(3));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0 });
    expect(screen.getByTestId('log-project-select')).toHaveTextContent('全部项目');
  });
});

describe('日志页 — 查询条件（q/correlation/from/to，§6.2）', () => {
  it('【R】输入 q + 点查询 → +q（page 归 0）', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.type(screen.getByTestId('log-q-input'), '崩溃');
    await user.click(screen.getByTestId('log-search-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0, q: '崩溃' });
  });

  it('【R】q 空白（未输入）点查询 → q 不传（仅重查一次）', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByTestId('log-search-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0 });
  });

  it('【R】输入 correlation_id + 点查询 → +correlation_id', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.type(screen.getByTestId('log-correlation-input'), 'c-42');
    await user.click(screen.getByTestId('log-search-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({
      level: 'INFO,WARN,ERROR',
      limit: 50,
      page: 0,
      correlation_id: 'c-42',
    });
  });

  it('【R】from/to 填写（datetime-local）+ 点查询 → 原样 ISO 串提交', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    fireEvent.change(screen.getByTestId('log-from-input'), {
      target: { value: '2026-09-01T08:00' },
    });
    fireEvent.change(screen.getByTestId('log-to-input'), {
      target: { value: '2026-09-02T08:00' },
    });
    await user.click(screen.getByTestId('log-search-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({
      level: 'INFO,WARN,ERROR',
      limit: 50,
      page: 0,
      from: '2026-09-01T08:00',
      to: '2026-09-02T08:00',
    });
  });
});

describe('日志页 — 重置 / 刷新（§6.2）', () => {
  it('【R】点重置：回默认参数重查 + UI 各控件归位（级别 INFO/项目全部/q/correlation/from/to 清空/tab 全部）', async () => {
    seedProjects();
    fetchLogsMock.mockResolvedValue(makePage({ items: [makeRecord()], total: 0, offset: 0 }));
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    // 制造非默认筛选态：项目A + 级别 WARN + q/correlation/from/to
    await user.click(screen.getByTestId('log-project-select'));
    await user.click(await screen.findByRole('option', { name: '测试项目A' }));
    await waitFor(() => expect(logsCallCount()).toBe(2));

    await user.click(screen.getByTestId('log-level-select'));
    await user.click(await screen.findByRole('option', { name: 'WARN' }));
    await waitFor(() => expect(logsCallCount()).toBe(3));

    await user.type(screen.getByTestId('log-q-input'), 'x');
    await user.type(screen.getByTestId('log-correlation-input'), 'c-99');
    fireEvent.change(screen.getByTestId('log-from-input'), { target: { value: '2026-09-01T08:00' } });
    fireEvent.change(screen.getByTestId('log-to-input'), { target: { value: '2026-09-02T08:00' } });
    await user.click(screen.getByTestId('log-search-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(4));
    expect(lastLogsParams()).toEqual({
      level: 'WARN,ERROR',
      limit: 50,
      page: 0,
      project_id: PAGE_A_UUID,
      q: 'x',
      correlation_id: 'c-99',
      from: '2026-09-01T08:00',
      to: '2026-09-02T08:00',
    });

    // 重置 → 回默认参数 + UI 归位
    await user.click(screen.getByTestId('log-reset-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(5));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0 });

    expect(screen.getByTestId('log-level-select')).toHaveTextContent('INFO');
    expect(screen.getByTestId('log-project-select')).toHaveTextContent('全部项目');
    expect(screen.getByTestId('log-q-input')).toHaveValue('');
    expect(screen.getByTestId('log-correlation-input')).toHaveValue('');
    expect(screen.getByTestId('log-from-input')).toHaveValue('');
    expect(screen.getByTestId('log-to-input')).toHaveValue('');
    expect(screen.getByRole('tab', { name: '全部' })).toHaveAttribute('aria-selected', 'true');
  });

  it('【R】点刷新：当前条件原样重查（调用计数 +1，参数与上次查询一致）', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.click(screen.getByTestId('log-refresh-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0 });
  });

  it('【R】刷新保留当前筛选：先设 q 查询再刷新 → 重查参数含 q', async () => {
    const user = userEvent.setup();
    renderLogsPage();
    await waitFor(() => expect(logsCallCount()).toBe(1));

    await user.type(screen.getByTestId('log-q-input'), 'x');
    await user.click(screen.getByTestId('log-search-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(2));

    await user.click(screen.getByTestId('log-refresh-btn'));
    await waitFor(() => expect(logsCallCount()).toBe(3));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 0, q: 'x' });
  });
});

describe('日志页 — 分页（§6.2）', () => {
  it('【R】prev 在 page=0 disabled；点下一页 → page:1 且渲染第二页数据；prev 恢复可用', async () => {
    const rec0 = makeRecord({ message_key: 'log.event.page_load', params: { page: 'P0' } });
    const rec1 = makeRecord({ message_key: 'log.event.page_load', params: { page: 'P1' } });
    fetchLogsMock.mockResolvedValueOnce(makePage({ items: [rec0], total: 120, offset: 0 }));
    fetchLogsMock.mockResolvedValueOnce(makePage({ items: [rec1], total: 120, offset: 50 }));

    const user = userEvent.setup();
    renderLogsPage();
    await screen.findByText('页面加载：P0'); // 首页数据渲染（本地 t() 插值：页面加载：{page}）

    // page=0：prev disabled、next enabled（(0+1)*50=50 < 120）
    expect(screen.getByTestId('log-page-prev')).toBeDisabled();
    expect(screen.getByTestId('log-page-next')).not.toBeDisabled();

    await user.click(screen.getByTestId('log-page-next'));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 1 });

    // 第二页数据渲染
    expect(await screen.findByText('页面加载：P1')).toBeInTheDocument();
    // page=1：prev 恢复可用
    expect(screen.getByTestId('log-page-prev')).not.toBeDisabled();
  });

  it('【R】next 在 (page+1)*50>=total 时 disabled：total=3 单页 → next disabled；末页 page=2 → next disabled', async () => {
    // total=3 单页：mount 即末页 → prev/next 都 disabled
    fetchLogsMock.mockResolvedValue(makePage({ items: [makeRecord()], total: 3, offset: 0 }));
    renderLogsPage();
    await screen.findByTestId('log-row');
    expect(screen.getByTestId('log-page-prev')).toBeDisabled();
    expect(screen.getByTestId('log-page-next')).toBeDisabled();
  });

  it('【R】翻到末页（page=2, total=120）→ next disabled（150>=120）', async () => {
    const rec = (tag: string) =>
      makeRecord({ message_key: 'log.event.page_load', params: { page: tag } });
    fetchLogsMock.mockResolvedValueOnce(makePage({ items: [rec('P0')], total: 120, offset: 0 }));
    fetchLogsMock.mockResolvedValueOnce(makePage({ items: [rec('P1')], total: 120, offset: 50 }));
    fetchLogsMock.mockResolvedValueOnce(makePage({ items: [rec('P2')], total: 120, offset: 100 }));

    const user = userEvent.setup();
    renderLogsPage();
    await screen.findByText('页面加载：P0');
    await user.click(screen.getByTestId('log-page-next'));
    await waitFor(() => expect(logsCallCount()).toBe(2));
    await user.click(screen.getByTestId('log-page-next'));
    await waitFor(() => expect(logsCallCount()).toBe(3));
    expect(lastLogsParams()).toEqual({ level: 'INFO,WARN,ERROR', limit: 50, page: 2 });

    expect(await screen.findByText('页面加载：P2')).toBeInTheDocument();
    // (2+1)*50=150 >= 120 → next disabled；prev 可用
    expect(screen.getByTestId('log-page-next')).toBeDisabled();
    expect(screen.getByTestId('log-page-prev')).not.toBeDisabled();
    // page-info 含 total
    expect(screen.getByTestId('log-page-info')).toHaveTextContent('120');
  });
});

describe('日志页 — 状态：空态/错误态/加载态（§6.2）', () => {
  it('【R】total=0 且成功 → log-empty（文案「暂无日志」），无 log-row', async () => {
    renderLogsPage();
    const empty = await screen.findByTestId('log-empty');
    expect(empty).toHaveTextContent('暂无日志');
    expect(screen.queryByTestId('log-row')).not.toBeInTheDocument();
  });

  it('【R】fetchLogs reject → log-error（文案「日志加载失败」或错误消息），列表不渲染', async () => {
    fetchLogsMock.mockRejectedValue(new Error('内核未就绪'));
    renderLogsPage();

    const err = await screen.findByTestId('log-error');
    expect(err).toHaveTextContent(/日志加载失败|内核未就绪/);
    expect(screen.queryByTestId('log-row')).not.toBeInTheDocument();
  });

  it('【R】查询中 → log-loading（文案「加载日志…」）；resolve 后渲染列表、加载态消失', async () => {
    let resolveLoad!: (v: LogsResponseDto) => void;
    fetchLogsMock.mockImplementation(
      () => new Promise<LogsResponseDto>((resolve) => { resolveLoad = resolve; }),
    );
    renderLogsPage();

    const loading = await screen.findByTestId('log-loading');
    expect(loading).toHaveTextContent('加载日志');
    resolveLoad(makePage({ items: [makeRecord()], total: 1, offset: 0 }));

    expect(await screen.findByTestId('log-row')).toBeInTheDocument();
    expect(screen.queryByTestId('log-loading')).not.toBeInTheDocument();
  });
});

describe('日志页 — 行渲染与 message 三层回退（§6.3）', () => {
  it('【R】行结构齐全：level badge/timestamp/caller-type/caller-name/message + 可选 duration/error-code/correlation', async () => {
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [
          makeRecord({
            level: 'ERROR',
            caller_type: 'llm',
            caller_name: 'OutlineAgent',
            message_key: 'log.event.api_retry',
            params: { attempt: 2 },
            correlation_id: 'c-42',
            duration_ms: 1234,
            error_code: 'E502',
          }),
        ],
        total: 1,
        offset: 0,
      }),
    );
    renderLogsPage();

    const row = await screen.findByTestId('log-row');
    expect(within(row).getByTestId('log-level-badge')).toHaveTextContent('ERROR');
    expect(within(row).getByTestId('log-message')).toHaveTextContent('API 重试：第 2 次');
    expect(within(row).getByTestId('log-timestamp')).toHaveTextContent('2026-09-04');
    expect(within(row).getByTestId('log-caller-type')).toBeInTheDocument();
    expect(within(row).getByTestId('log-caller-name')).toHaveTextContent('OutlineAgent');
    // 可选片段：字段存在即渲染；#930 时长格式化（1234ms < 60s → 1.2s）
    expect(within(row).getByTestId('log-duration')).toHaveTextContent('1.2s');
    expect(within(row).getByTestId('log-error-code')).toHaveTextContent('E502');
    expect(within(row).getByTestId('log-correlation')).toHaveTextContent('c-42');
  });

  it('【R】远端目录命中 → 远端模板插值：渲染「远端模板 第一章」', async () => {
    fetchLogMessagesMock.mockResolvedValue({
      'log.event.create_chapter': '远端模板 {title}',
    });
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [makeRecord({ message_key: 'log.event.create_chapter', params: { title: '第一章' } })],
        total: 1,
        offset: 0,
      }),
    );
    renderLogsPage();

    expect(await screen.findByText('远端模板 第一章')).toBeInTheDocument();
  });

  it('【R】远端目录缺键 → 本地 t() 插值：渲染「创建章节：第一章」（zh）', async () => {
    fetchLogMessagesMock.mockResolvedValue({}); // 远端无 log.event.create_chapter
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [makeRecord({ message_key: 'log.event.create_chapter', params: { title: '第一章' } })],
        total: 1,
        offset: 0,
      }),
    );
    renderLogsPage();

    expect(await screen.findByText('创建章节：第一章')).toBeInTheDocument();
    expect(fetchLogMessagesMock).toHaveBeenCalledWith('zh');
  });

  it('【R】lang=en → 拉远端目录(en) 且本地回退走 en 文案：「Created chapter: 第一章」', async () => {
    useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'en' });
    fetchLogMessagesMock.mockResolvedValue({});
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [makeRecord({ message_key: 'log.event.create_chapter', params: { title: '第一章' } })],
        total: 1,
        offset: 0,
      }),
    );
    renderLogsPage();

    expect(fetchLogMessagesMock).toHaveBeenCalledWith('en');
    expect(await screen.findByText('Created chapter: 第一章')).toBeInTheDocument();
  });

  it('【R】lang 变化（zh→en）→ 重新拉远端目录 + 行文案随语言切换', async () => {
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [makeRecord({ message_key: 'log.event.create_chapter', params: { title: '第一章' } })],
        total: 1,
        offset: 0,
      }),
    );
    renderLogsPage();
    expect(await screen.findByText('创建章节：第一章')).toBeInTheDocument();
    await waitFor(() => expect(fetchLogMessagesMock).toHaveBeenCalledWith('zh'));

    useThemeStore.setState({ lang: 'en' });
    await waitFor(() => expect(fetchLogMessagesMock).toHaveBeenCalledWith('en'));
    expect(await screen.findByText('Created chapter: 第一章')).toBeInTheDocument();
  });

  it('【R】远端目录拉取失败（reject）→ 静默回退本地 t() 渲染，页面不崩', async () => {
    fetchLogMessagesMock.mockRejectedValue(new Error('远端目录不可达'));
    fetchLogsMock.mockResolvedValue(
      makePage({
        items: [makeRecord({ message_key: 'log.event.create_chapter', params: { title: '第一章' } })],
        total: 1,
        offset: 0,
      }),
    );
    renderLogsPage();

    expect(await screen.findByText('创建章节：第一章')).toBeInTheDocument();
  });
});

describe('日志页 — 过期响应防护（§6.2）', () => {
  it('【R】两次慢查询乱序返回 → 最终渲染第二次数据（过期响应不覆盖）', async () => {
    const resolvers: Array<(v: LogsResponseDto) => void> = [];
    fetchLogsMock.mockImplementation(
      () => new Promise<LogsResponseDto>((resolve) => { resolvers.push(resolve); }),
    );
    const user = userEvent.setup();
    renderLogsPage(); // 查询 #1（慢，挂载）

    await screen.findByTestId('log-loading');
    await user.click(screen.getByTestId('log-refresh-btn')); // 查询 #2（慢，刷新）
    await waitFor(() => expect(resolvers.length).toBe(2));

    // #2 先返回 → 渲染第二次数据
    resolvers[1](
      makePage({
        items: [
          makeRecord({ message_key: 'log.event.page_load', params: { page: '新结果' } }),
        ],
        total: 1,
        offset: 50,
      }),
    );
    expect(await screen.findByText('页面加载：新结果')).toBeInTheDocument();

    // #1 后返回（过期）→ 不得覆盖第二次渲染结果
    resolvers[0](
      makePage({
        items: [
          makeRecord({ message_key: 'log.event.create_chapter', params: { title: '过期旧结果' } }),
        ],
        total: 1,
        offset: 0,
      }),
    );
    await waitFor(() => {
      expect(screen.queryByText('创建章节：过期旧结果')).not.toBeInTheDocument();
    });
    expect(screen.getByText('页面加载：新结果')).toBeInTheDocument();
  });
});
