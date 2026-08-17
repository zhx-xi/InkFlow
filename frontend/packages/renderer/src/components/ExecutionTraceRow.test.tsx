/**
 * ExecutionTraceRow 契约测试（F44 阶段1 GUI，spec v1.1 §5.1 GUI 小节「子 agent 展开行」）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/components/ExecutionTraceRow.tsx 并匹配：
 *
 * export interface ExecutionTraceRowProps {
 *   outlineId: string;
 *   status: string;                    // PlanNodeStatus: pending/in_progress/done/failed/skipped
 *   executionId?: string;              // execution_refs[outline_id]（S1a 阶段1 可选）
 * }
 * export function ExecutionTraceRow(props: ExecutionTraceRowProps): JSX.Element
 *
 * 结构 testid：
 * - trace-row-<outlineId>（行容器）
 * - trace-row-status-<outlineId>（状态徽标）
 * - trace-row-toggle-<outlineId>（展开/折叠按钮）
 * - trace-row-detail-<outlineId>（展开后的详情区）
 *
 * 行为契约（阶段1 基础展示层，S1a 唯一真相：GET /runs/{id} 返回 progress 章状态 +
 * counters，无 trace 字段——展开行展示执行状态摘要，trace 字段留阶段 2-4）：
 * - 默认折叠：显示状态徽标 + 折叠按钮，无详情区
 * - 点 toggle → 展开显示详情区（含状态文案 + 可选 executionId）
 * - 再点 toggle → 折叠（详情区消失）
 * - 状态徽标文案映射：pending=待处理 / in_progress=进行中 / done=已完成 /
 *   failed=失败 / skipped=已跳过（i18n key: book.trace.pending 等）
 *
 * i18n key（GREEN 补 zh.ts/en.ts）：book.trace.pending / book.trace.in_progress /
 * book.trace.done / book.trace.failed / book.trace.skipped / book.trace.detail /
 * book.trace.execution
 *
 * ⚠️ F44 阶段4（#338 S4b 章级干预控件）增量——GREEN 必须追加：
 *
 * - 组件读 useBookStore 的 density / interveneDiff（无新 props）
 * - 仅 density==='performance' 渲染章行内干预控件（⚠️ density 拍板 = 纯前端本地
 *   Zustand 状态，后端无 density 参数，见契约 §1.3）：
 *   trace-redirect-skip-<outlineId> / trace-redirect-retry-<outlineId> /
 *   trace-redirect-markfailed-<outlineId>（→ interveneRun('redirect', id, 'skip'|'retry'|'mark_failed')）
 *   trace-edit-<outlineId>（点击展开行内 brief 编辑：trace-brief-<outlineId> textarea +
 *   trace-edit-save-<outlineId> / trace-edit-cancel-<outlineId>；save → interveneRun('edit', id, undefined, {brief})）
 * - 已完成章（status==='done'）干预控件 disabled（422 已完成章不可干预 防呆）
 * - interveneDiff.target === outlineId 时行内渲染 trace-diff-<outlineId>（from→to 或 edit diff 文本）
 *
 * i18n key（GREEN 补 zh.ts/en.ts）：book.trace.skip / book.trace.retry / book.trace.markFailed /
 * book.trace.edit / book.trace.editSave / book.trace.editCancel / book.trace.briefPlaceholder
 * （断言锚 testid，不锚具体文案——缺 key 时 t() 返回 key 本身，避免 RED 期误判）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExecutionTraceRow } from './ExecutionTraceRow';
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
  // F44 阶段4（#338）新字段默认值（RED 期播种合法：Zustand 合并未知键，GREEN 后生效；
  // density 默认 'dashboard' → 既有用例保持无干预控件形态）
  useBookStore.setState({
    runId: null,
    runStatus: null,
    progress: {},
    density: 'dashboard',
    interveneDiff: null,
    intervening: false,
    summary: null,
    summaryLoading: false,
  });
});

describe('ExecutionTraceRow — 展开/折叠', () => {
  it('默认折叠：状态徽标可见，详情区不存在', () => {
    render(<ExecutionTraceRow outlineId="o-ch1" status="done" />);
    expect(screen.getByTestId('trace-row-o-ch1')).toBeInTheDocument();
    expect(screen.getByTestId('trace-row-status-o-ch1')).toBeInTheDocument();
    expect(screen.getByTestId('trace-row-toggle-o-ch1')).toBeInTheDocument();
    expect(screen.queryByTestId('trace-row-detail-o-ch1')).not.toBeInTheDocument();
  });

  it('点 toggle → 展开详情区（含状态文案 + executionId）；再点 → 折叠', async () => {
    const user = userEvent.setup();
    render(<ExecutionTraceRow outlineId="o-ch1" status="done" executionId="e-1" />);
    await user.click(screen.getByTestId('trace-row-toggle-o-ch1'));
    expect(await screen.findByTestId('trace-row-detail-o-ch1')).toHaveTextContent('已完成');
    expect(screen.getByTestId('trace-row-detail-o-ch1')).toHaveTextContent('e-1');
    await user.click(screen.getByTestId('trace-row-toggle-o-ch1'));
    expect(screen.queryByTestId('trace-row-detail-o-ch1')).not.toBeInTheDocument();
  });
});

describe('ExecutionTraceRow — 状态徽标文案', () => {
  it.each([
    ['pending', '待处理'],
    ['in_progress', '进行中'],
    ['done', '已完成'],
    ['failed', '失败'],
    ['skipped', '已跳过'],
  ])('status=%s → 徽标文案 %s', (status, label) => {
    render(<ExecutionTraceRow outlineId={`o-${status}`} status={status} />);
    expect(screen.getByTestId(`trace-row-status-o-${status}`)).toHaveTextContent(label);
  });
});

describe('ExecutionTraceRow — 阶段2 状态徽标视觉（spec §5.2 章级进度状态 UI）', () => {
  it.each([
    ['pending', 'badge-pending'],
    ['in_progress', 'badge-in_progress'],
    ['done', 'badge-done'],
    ['failed', 'badge-failed'],
    ['skipped', 'badge-skipped'],
  ])('status=%s → 徽标含状态语义 className（badge-<status>，五态可区分）', (status, cls) => {
    render(<ExecutionTraceRow outlineId={`o-${status}`} status={status} />);
    // 视觉徽标化：className 带状态语义（GREEN 用色区分；断言只钉语义类不钉色值）
    expect(screen.getByTestId(`trace-row-status-o-${status}`)).toHaveClass(cls);
  });
});

describe('ExecutionTraceRow — 阶段4 章级干预控件（#338，仅 performance 密度显示）', () => {
  const redirectDiff = { target: 'o-c1', from: 'in_progress', to: 'skipped' };

  it('performance 密度 → 行内干预控件渲染（redirect 三档 + edit + cancel）', () => {
    useBookStore.setState({ density: 'performance' });
    render(<ExecutionTraceRow outlineId="o-c1" status="in_progress" />);
    expect(screen.getByTestId('trace-redirect-skip-o-c1')).toBeInTheDocument();
    expect(screen.getByTestId('trace-redirect-retry-o-c1')).toBeInTheDocument();
    expect(screen.getByTestId('trace-redirect-markfailed-o-c1')).toBeInTheDocument();
    expect(screen.getByTestId('trace-edit-o-c1')).toBeInTheDocument();
    expect(screen.getByTestId('trace-edit-cancel-o-c1')).toBeInTheDocument();
  });

  it('dashboard 密度 → 无干预控件（现状形态，确认型）', () => {
    useBookStore.setState({ density: 'dashboard' });
    render(<ExecutionTraceRow outlineId="o-c1" status="in_progress" />);
    expect(screen.queryByTestId('trace-redirect-skip-o-c1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('trace-edit-o-c1')).not.toBeInTheDocument();
  });

  it('done 章 → 干预控件 disabled（422 已完成章不可干预 防呆）', () => {
    useBookStore.setState({ density: 'performance' });
    render(<ExecutionTraceRow outlineId="o-c1" status="done" />);
    expect(screen.getByTestId('trace-redirect-skip-o-c1')).toBeDisabled();
    expect(screen.getByTestId('trace-redirect-retry-o-c1')).toBeDisabled();
    expect(screen.getByTestId('trace-redirect-markfailed-o-c1')).toBeDisabled();
    expect(screen.getByTestId('trace-edit-o-c1')).toBeDisabled();
  });

  it('in_progress 章 → 干预控件 enabled', () => {
    useBookStore.setState({ density: 'performance' });
    render(<ExecutionTraceRow outlineId="o-c1" status="in_progress" />);
    expect(screen.getByTestId('trace-redirect-skip-o-c1')).toBeEnabled();
    expect(screen.getByTestId('trace-edit-o-c1')).toBeEnabled();
  });

  it('interveneDiff.target===outlineId → 行内 trace-diff 高亮（from→to 文本）', () => {
    useBookStore.setState({ density: 'performance', interveneDiff: redirectDiff });
    render(<ExecutionTraceRow outlineId="o-c1" status="in_progress" />);
    const diff = screen.getByTestId('trace-diff-o-c1');
    expect(diff).toBeInTheDocument();
    expect(diff).toHaveTextContent('in_progress');
    expect(diff).toHaveTextContent('skipped');
  });

  it('点 trace-edit → 行内 brief 编辑 → save → POST /intervene（走真实 store.interveneRun）', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/agent/books/runs/wp-1/intervene' && init?.method === 'POST') {
        return {
          run_id: 'wp-1',
          status: 'running',
          diff: { target: 'o-c1', before: '旧描述', after: '把主角改为双面间谍', diff: '-旧描述\n+把主角改为双面间谍' },
        };
      }
      throw new Error(`unexpected: ${path}`);
    });
    useBookStore.setState({ runId: 'wp-1', density: 'performance' });
    const user = userEvent.setup();
    render(<ExecutionTraceRow outlineId="o-c1" status="in_progress" />);
    await user.click(screen.getByTestId('trace-edit-o-c1'));
    const brief = await screen.findByTestId('trace-brief-o-c1');
    await user.type(brief, '把主角改为双面间谍');
    await user.click(screen.getByTestId('trace-edit-save-o-c1'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1/intervene', {
        method: 'POST',
        body: { action: 'edit', target: 'o-c1', payload: { brief: '把主角改为双面间谍' } },
      });
    });
    // save 成功后行内 diff 高亮（store.interveneDiff 更新驱动）
    await waitFor(() => {
      expect(screen.getByTestId('trace-diff-o-c1')).toBeInTheDocument();
    });
  });
});
