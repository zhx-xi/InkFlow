/**
 * BookSummaryPanel 契约测试（F44 阶段4 #338 S4b 回归摘要面板）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/components/BookSummaryPanel.tsx 并匹配：
 *
 * export function BookSummaryPanel()
 * （无 props——读 useBookStore 的 summary / summaryLoading / loadSummary；
 *   挂载时 summary===null 且 runId 非空 → loadSummary(runId)）
 *
 * 结构 testid：
 * - book-summary-panel（容器）
 * - book-summary-loading（summaryLoading=true 加载态）
 * - book-summary-empty（summary===null 且非加载态提示）
 * - book-summary-progress（进度树 done/total 从 progress 派生）
 * - book-summary-next（next 卷信息；finished=true → 全部完成文案）
 * - book-summary-steps（steps 列表容器）
 * - book-summary-step-<index>（steps 行：index + status + execution_id）
 * - book-summary-export（导出按钮：Blob 下载 JSON 镜像 CLI --export，模拟点击 a[download]）
 *
 * 后端唯一真相（S4a #453 backend books.py summary 实证）：
 * GET /api/v1/agent/books/runs/{run_id}/summary →
 * {run_id, status, progress: Record<string,string>, counters: RunStatusCounters(7键),
 *  steps: [{index, outline_id, status, execution_id: string|null}],
 *  next: {volume_index?, total_volumes?, finished, status?}}（无 checkpoint → {finished:true}）；404 运行不存在
 *
 * 行为契约：
 * - summary===null + summaryLoading=false → book-summary-empty（无数据提示）
 * - summaryLoading=true → book-summary-loading
 * - summary 就绪 → book-summary-panel 容器 + book-summary-progress（done/total 派生）
 * - next.finished=true → book-summary-next 显示全部完成；false → volume_index / total_volumes 信息
 * - steps 非空 → book-summary-step-<index> 每行（index + status + execution_id）
 * - book-summary-export 点击 → URL.createObjectURL(new Blob([JSON.stringify(summary,null,2)],
 *   {type:'application/json'})) + 临时 a[download="book-summary-<runId>.json"] 模拟点击 + revokeObjectURL
 *
 * i18n key（GREEN 补 zh.ts/en.ts）：book.summary.loading / book.summary.empty / book.summary.progress /
 * book.summary.next / book.summary.nextDone / book.summary.steps / book.summary.export
 * （断言锚 testid 为主；nextDone 文案「全部完成」为契约定稿文案，GREEN 按 zh.ts 补键）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BookSummaryPanel } from './BookSummaryPanel';
import { useBookStore } from '../stores/book';
import { useThemeStore } from '../stores/theme';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const summaryResp = {
  run_id: 'wp-1',
  status: 'completed',
  progress: { 'o-c1': 'done', 'o-c2': 'done', 'o-c3': 'in_progress' },
  counters: {
    max_chapters: 3,
    max_agent_calls: 5,
    agent_calls: 2,
    chapters_written: 2,
    max_tokens: 200000,
    tokens_used: 12345,
    tokens_warning: false,
  },
  steps: [
    { index: 0, outline_id: 'o-c1', status: 'done', execution_id: 'e-1' },
    { index: 1, outline_id: 'o-c2', status: 'done', execution_id: 'e-2' },
    { index: 2, outline_id: 'o-c3', status: 'in_progress', execution_id: null },
  ],
  next: { volume_index: 0, total_volumes: 3, finished: false, status: 'in_progress' },
};

beforeEach(() => {
  apiFetchMock.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useBookStore.setState({
    runId: 'wp-1',
    runStatus: 'completed',
    progress: {},
    counters: null,
    // F44 阶段4（#338）新字段默认值（RED 期播种合法：Zustand 合并未知键，GREEN 后生效）
    density: 'dashboard',
    interveneDiff: null,
    intervening: false,
    summary: null,
    summaryLoading: false,
  });
  // 默认 URL 分发：GET /summary → summaryResp（挂载加载 + 摘要内容测试共用）
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/agent/books/runs/wp-1/summary') {
      return summaryResp;
    }
    throw new Error(`unexpected: ${path}`);
  });
});

describe('BookSummaryPanel — 加载/空态', () => {
  it('summaryLoading=true → book-summary-loading', () => {
    useBookStore.setState({ summaryLoading: true });
    render(<BookSummaryPanel />);
    expect(screen.getByTestId('book-summary-loading')).toBeInTheDocument();
  });

  it('summary=null + 非加载 → book-summary-empty（无数据提示）', () => {
    render(<BookSummaryPanel />);
    expect(screen.getByTestId('book-summary-empty')).toBeInTheDocument();
  });

  it('挂载时调用 loadSummary（GET /summary，runId 非空且 summary 为空）', async () => {
    render(<BookSummaryPanel />);
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1/summary');
    });
  });
});

describe('BookSummaryPanel — 摘要内容', () => {
  it('summary 就绪 → book-summary-panel 容器 + book-summary-progress（done/total 派生）', async () => {
    useBookStore.setState({ summary: summaryResp });
    render(<BookSummaryPanel />);
    expect(await screen.findByTestId('book-summary-panel')).toBeInTheDocument();
    const progress = screen.getByTestId('book-summary-progress');
    expect(progress).toHaveTextContent('2');
    expect(progress).toHaveTextContent('3');
  });

  it('next.finished=true → book-summary-next 显示全部完成（契约定稿文案）', () => {
    useBookStore.setState({ summary: { ...summaryResp, next: { finished: true } } });
    render(<BookSummaryPanel />);
    expect(screen.getByTestId('book-summary-next')).toHaveTextContent('全部完成');
  });

  it('next 未完成 → book-summary-next 显示 volume_index / total_volumes', () => {
    useBookStore.setState({ summary: summaryResp });
    render(<BookSummaryPanel />);
    const next = screen.getByTestId('book-summary-next');
    expect(next).toHaveTextContent('0');
    expect(next).toHaveTextContent('3');
  });

  it('steps 列表 → book-summary-steps 容器 + book-summary-step-<index> 每行（index + execution_id）', () => {
    useBookStore.setState({ summary: summaryResp });
    render(<BookSummaryPanel />);
    expect(screen.getByTestId('book-summary-steps')).toBeInTheDocument();
    const row0 = screen.getByTestId('book-summary-step-0');
    expect(row0).toHaveTextContent('0');
    expect(row0).toHaveTextContent('e-1');
    expect(screen.getByTestId('book-summary-step-1')).toHaveTextContent('e-2');
    expect(screen.getByTestId('book-summary-step-2')).toBeInTheDocument();
  });
});

describe('BookSummaryPanel — 导出', () => {
  it('点 book-summary-export → createObjectURL(Blob) + a[download] 模拟点击（含 runId）', async () => {
    useBookStore.setState({ summary: summaryResp });
    const createObjectURL = vi.fn(() => 'blob:mock');
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const captured: HTMLAnchorElement[] = [];
    const realCreateElement = document.createElement.bind(document);
    const createElementSpy = vi
      .spyOn(document, 'createElement')
      .mockImplementation((tag: string, options?: ElementCreationOptions) => {
        const el = realCreateElement(tag, options);
        if (tag === 'a') captured.push(el as HTMLAnchorElement);
        return el;
      });
    try {
      const user = userEvent.setup();
      render(<BookSummaryPanel />);
      await user.click(await screen.findByTestId('book-summary-export'));
      expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
      expect(clickSpy).toHaveBeenCalled();
      expect(captured.some((a) => a.download.includes('wp-1'))).toBe(true);
    } finally {
      clickSpy.mockRestore();
      createElementSpy.mockRestore();
    }
  });
});
