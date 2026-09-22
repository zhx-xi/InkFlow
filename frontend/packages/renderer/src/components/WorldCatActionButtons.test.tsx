/**
 * #1375 ①A 创建按钮语义拆分（升级自 #1321 契约）— GUI 契约
 *
 * 覆盖（issue #1375 ①A + specs/f19-gui/world.md N11，已拍板 2026-09-22）：
 *   - world-cat-add「新建分类」恒开分类对话框（不随选中分类改变语义；
 *     #1321 的 world-cat-add-always 恒开语义并入本钮，独立钮退役）
 *   - world-cat-add-entry「新建条目」选中分类时启用、未选中禁用（title「请先选择分类」）
 *   - 空态（未传 onCreateWorld）不渲染 world-cat-add-entry
 *
 * 历史：#1321 曾以 world-cat-add-always 补恒开入口；#1375 ①A 将两钮语义去歧——
 * 恒开分类语义由 world-cat-add 承担，#568 的「随选中态切换」退役。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorldCatActionButtons } from './WorldCatActionButtons';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#1375 ①A 创建按钮语义拆分（世界观工具栏）', () => {
  it('E1 world-cat-add 恒开分类对话框：即使提供 onCreateWorld（选中分类）也不切语义', async () => {
    const onAddCategory = vi.fn();
    const onCreateWorld = vi.fn();
    render(
      <WorldCatActionButtons
        onAddCategory={onAddCategory}
        onOpenMapView={() => {}}
        onCreateWorld={onCreateWorld}
        activeWorldCat="势力"
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByTestId('world-cat-add'));
    expect(onAddCategory).toHaveBeenCalledTimes(1);
    expect(onCreateWorld).not.toHaveBeenCalled();
    // #1321 的 world-cat-add-always 恒开语义已并入 world-cat-add → 不再渲染独立钮
    expect(screen.queryByTestId('world-cat-add-always')).not.toBeInTheDocument();
  });

  it('E2 world-cat-add-entry：未选中分类 → 禁用 + title「请先选择分类」；选中 → 启用 + 点击走 onCreateWorld', async () => {
    const onCreateWorld = vi.fn();
    const { rerender } = render(
      <WorldCatActionButtons
        onAddCategory={() => {}}
        onOpenMapView={() => {}}
        onCreateWorld={onCreateWorld}
        activeWorldCat={null}
      />,
    );
    expect(screen.getByTestId('world-cat-add-entry')).toBeDisabled();
    expect(screen.getByTestId('world-cat-add-entry')).toHaveAttribute('title', '请先选择分类');
    rerender(
      <WorldCatActionButtons
        onAddCategory={() => {}}
        onOpenMapView={() => {}}
        onCreateWorld={onCreateWorld}
        activeWorldCat="势力"
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByTestId('world-cat-add-entry'));
    expect(onCreateWorld).toHaveBeenCalledTimes(1);
  });

  it('E3 空态（未传 onCreateWorld）→ 不渲染 world-cat-add-entry（无分类可挂条目）', () => {
    render(<WorldCatActionButtons onAddCategory={() => {}} onOpenMapView={() => {}} />);
    expect(screen.getByTestId('world-cat-add')).toBeInTheDocument();
    expect(screen.queryByTestId('world-cat-add-entry')).not.toBeInTheDocument();
  });
});
