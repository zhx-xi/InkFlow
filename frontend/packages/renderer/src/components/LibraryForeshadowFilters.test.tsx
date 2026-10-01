/**
 * #1376 伏笔页筛选/排序条（方案 A）单元契约 —— RED 优先。
 *
 * 【设计基准】design/GUI/foreshadow/foreshadow.html 形态 A（`fs-bar-a`）：
 *   回收状态 chip 三态（全部/未回收/已回收）+ 检索框（标题 OR 位置，实时）+ 计数行
 *   「显示 N / 共 M 条」+ 排序切换（优先级 高→低 / 低→高）。
 *   🔴 原型内嵌的 `design-note` 方案取舍说明条（data-design-annotation）**不得**做进产品 UI
 *      （specs/f19-gui/foreshadow.md §4.4）——本契约含反向断言。
 *
 * 【契约（GREEN 目标）】组件为**纯展示受控件**（零内部筛选 state）：
 *   筛选/排序的 state 由页面持有并下沉服务端（?status= / ?search= / ?sort_*），
 *   组件只负责渲染 + 上抛意图 —— 否则「筛选只作用于当前页」旧缺陷会重现（#1300/#1320）。
 *
 * RED 预期：GREEN 前 `LibraryForeshadowFilters` 模块不存在 → collection error → FAIL。
 */
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LibraryForeshadowFilters } from './LibraryForeshadowFilters';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

function renderBar(props?: Partial<Parameters<typeof LibraryForeshadowFilters>[0]>) {
  const handlers = {
    onStatusChange: vi.fn(),
    onQueryChange: vi.fn(),
    onToggleSort: vi.fn(),
  };
  render(
    <LibraryForeshadowFilters
      status="all"
      query=""
      sortDesc
      shown={8}
      total={8}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe('#1376 筛选条：回收状态 chip 三态', () => {
  it('渲染三态 chip（全部/未回收/已回收），选中态由 status prop 决定（互斥单选）', () => {
    renderBar({ status: 'open' });

    expect(screen.getByTestId('foreshadow-filters')).toBeInTheDocument();
    expect(screen.getByTestId('fs-status-chips')).toBeInTheDocument();
    // status='open' → 未回收激活，其余两个非激活（三态互斥）
    expect(screen.getByTestId('fs-status-chip-open')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('fs-status-chip-all')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('fs-status-chip-resolved')).toHaveAttribute('aria-pressed', 'false');
  });

  it('缺省 status="all" → 「全部」激活（= 不加筛选条件）', () => {
    renderBar();
    expect(screen.getByTestId('fs-status-chip-all')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('fs-status-chip-open')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('fs-status-chip-resolved')).toHaveAttribute('aria-pressed', 'false');
  });

  it('点击 chip → 上抛对应状态值（组件不自行筛选/不改内部态）', async () => {
    const user = userEvent.setup();
    const { onStatusChange } = renderBar();

    await user.click(screen.getByTestId('fs-status-chip-open'));
    expect(onStatusChange).toHaveBeenLastCalledWith('open');

    await user.click(screen.getByTestId('fs-status-chip-resolved'));
    expect(onStatusChange).toHaveBeenLastCalledWith('resolved');

    await user.click(screen.getByTestId('fs-status-chip-all'));
    expect(onStatusChange).toHaveBeenLastCalledWith('all');
  });
});

describe('#1376 筛选条：检索框（标题 OR 位置）', () => {
  it('输入即上抛（无需 Enter）：逐字触发 onQueryChange，取值与输入一致', async () => {
    const user = userEvent.setup();
    const { onQueryChange } = renderBar();

    // 受控 + 假父级回填：模拟真实页面（页面持有 query state）
    const input = screen.getByTestId('fs-search-input') as HTMLInputElement;
    await user.click(input);
    await user.keyboard('剑');

    expect(onQueryChange).toHaveBeenCalled();
    expect(onQueryChange).toHaveBeenLastCalledWith('剑');
    // 未按 Enter 也已上抛（实时检索语义）
    expect(onQueryChange).toHaveBeenCalledTimes(1);
  });

  it('受控值回填：query prop 变化 → 输入框值与之一致（页面为唯一真相）', () => {
    const { rerender } = render(
      <LibraryForeshadowFilters
        status="all"
        query=""
        sortDesc
        shown={8}
        total={8}
        onStatusChange={vi.fn()}
        onQueryChange={vi.fn()}
        onToggleSort={vi.fn()}
      />,
    );
    const input = screen.getByTestId('fs-search-input') as HTMLInputElement;
    expect(input.value).toBe('');

    rerender(
      <LibraryForeshadowFilters
        status="all"
        query="第 2 章"
        sortDesc
        shown={1}
        total={1}
        onStatusChange={vi.fn()}
        onQueryChange={vi.fn()}
        onToggleSort={vi.fn()}
      />,
    );
    expect((screen.getByTestId('fs-search-input') as HTMLInputElement).value).toBe('第 2 章');
  });

  it('受控 Harness：连打两字后页面态为完整输入（无内部 state 抢占）', async () => {
    function Harness() {
      const [q, setQ] = useState('');
      return (
        <LibraryForeshadowFilters
          status="all"
          query={q}
          sortDesc
          shown={8}
          total={8}
          onStatusChange={vi.fn()}
          onQueryChange={setQ}
          onToggleSort={vi.fn()}
        />
      );
    }
    render(<Harness />);
    await userEvent.setup().type(screen.getByTestId('fs-search-input'), '第2章');
    expect((screen.getByTestId('fs-search-input') as HTMLInputElement).value).toBe('第2章');
  });
});

describe('#1376 筛选条：计数行 + 排序切换', () => {
  it('计数行随筛选同步：「显示 {本页} / 共 {筛选后总数} 条」', () => {
    const { rerender } = render(
      <LibraryForeshadowFilters
        status="all"
        query=""
        sortDesc
        shown={8}
        total={8}
        onStatusChange={vi.fn()}
        onQueryChange={vi.fn()}
        onToggleSort={vi.fn()}
      />,
    );
    expect(screen.getByTestId('fs-count')).toHaveTextContent('显示 8 / 共 8 条');

    // 未回收筛选（原型实测 8→6）：本页 6 / 共 6
    rerender(
      <LibraryForeshadowFilters
        status="open"
        query=""
        sortDesc
        shown={6}
        total={6}
        onStatusChange={vi.fn()}
        onQueryChange={vi.fn()}
        onToggleSort={vi.fn()}
      />,
    );
    expect(screen.getByTestId('fs-count')).toHaveTextContent('显示 6 / 共 6 条');
  });

  it('排序默认「优先级 高→低」；sortDesc=false → 「优先级 低→高」（图标随向）', () => {
    const { rerender } = render(
      <LibraryForeshadowFilters
        status="all"
        query=""
        sortDesc
        shown={8}
        total={8}
        onStatusChange={vi.fn()}
        onQueryChange={vi.fn()}
        onToggleSort={vi.fn()}
      />,
    );
    expect(screen.getByTestId('fs-sort-toggle')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('fs-sort-label')).toHaveTextContent('优先级 高→低');

    rerender(
      <LibraryForeshadowFilters
        status="all"
        query=""
        sortDesc={false}
        shown={8}
        total={8}
        onStatusChange={vi.fn()}
        onQueryChange={vi.fn()}
        onToggleSort={vi.fn()}
      />,
    );
    expect(screen.getByTestId('fs-sort-toggle')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('fs-sort-label')).toHaveTextContent('优先级 低→高');
  });

  it('点击排序 → 上抛 onToggleSort（组件不改内部方向）', async () => {
    const { onToggleSort } = renderBar();
    await userEvent.setup().click(screen.getByTestId('fs-sort-toggle'));
    expect(onToggleSort).toHaveBeenCalledTimes(1);
  });
});

describe('#1376 筛选条：边界（原型设计注释条不得进产品 UI）', () => {
  it('不渲染原型 `design-note` 方案取舍说明条（data-design-annotation 缺席）', () => {
    renderBar({ status: 'open' });
    expect(document.querySelector('[data-design-annotation]')).toBeNull();
    expect(screen.queryByTestId('fs-note-filter-a')).not.toBeInTheDocument();
  });

  it('不渲染口径 2 章节选择器 / 方案 B 下拉（本期只落形态 A + 口径 1，N10/§4.2）', () => {
    renderBar();
    expect(screen.queryByTestId('fs-chapter-picker')).not.toBeInTheDocument();
    expect(screen.queryByTestId('fs-status-select')).not.toBeInTheDocument();
    expect(screen.queryByTestId('fs-priority-min')).not.toBeInTheDocument();
  });
});
