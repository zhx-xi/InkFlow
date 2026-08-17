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
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExecutionTraceRow } from './ExecutionTraceRow';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
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
