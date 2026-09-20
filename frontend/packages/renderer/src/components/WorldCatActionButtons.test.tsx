/**
 * #1321 恒显「新建分类」入口 — GUI 契约
 *
 * 覆盖（issue #1321 §5 入口拆分）：
 *   - 列表工具栏：选中分类时 world-cat-add 变「建条目」语义，但 world-cat-add-always
 *     仍恒开分类对话框（用户不再丢失建分类入口）
 *   - 地图工作台：左栏头部渲染 world-cat-add-always（地图分支此前无任何建分类入口）
 *
 * RED 预期（实现前无该 testid）：E1/E2 getByTestId 失败（element-missing）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorldCatActionButtons } from './WorldCatActionButtons';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#1321 恒显新建分类入口', () => {
  it('E1 选中分类（onCreateWorld 已传）→ world-cat-add 走建条目，world-cat-add-always 仍开分类框', async () => {
    const onAddCategory = vi.fn();
    const onCreateWorld = vi.fn();
    render(
      <WorldCatActionButtons
        onAddCategory={onAddCategory}
        onOpenMapView={() => {}}
        onCreateWorld={onCreateWorld}
        showAddCategoryAlways
      />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByTestId('world-cat-add'));
    expect(onCreateWorld).toHaveBeenCalledTimes(1);
    expect(onAddCategory).not.toHaveBeenCalled();

    await user.click(screen.getByTestId('world-cat-add-always'));
    expect(onAddCategory).toHaveBeenCalledTimes(1);
  });

  it('E2 未传 showAddCategoryAlways（空态分支）→ 不渲染 world-cat-add-always', () => {
    render(<WorldCatActionButtons onAddCategory={() => {}} onOpenMapView={() => {}} />);
    expect(screen.getByTestId('world-cat-add')).toBeInTheDocument();
    expect(screen.queryByTestId('world-cat-add-always')).not.toBeInTheDocument();
  });
});
