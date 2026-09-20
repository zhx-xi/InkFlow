/**
 * #1321 世界观分类条件必填 + 恒显新建分类入口 — GUI 契约
 *
 * 覆盖（issue #1321 §9 断言 7 + §5 GUI 门控）：
 *   - world 非根条目（isRoot 未传 / false）分类为空 → save 按钮 disabled
 *   - world 非根条目填了分类 → save 按钮 enabled
 *   - world 根条目（isRoot=true）→ 分类输入框不渲染，门控不生效（#722 守护）
 *   - 必填提示锚点 library-create-category-required 渲染/消失
 *
 * RED 预期（实现前 canSave 只覆盖 characters rank）：
 *   G1/G2 断言 disabled 失败（按钮恒 enabled）；G4 提示锚点缺失。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LibraryCreateDialog } from './LibraryCreateDialog';
import { useThemeStore } from '../stores/theme';

const onSave = vi.fn();

function renderWorldDialog(props?: { isRoot?: boolean }) {
  return render(
    <LibraryCreateDialog
      open
      cat="world"
      editing={null}
      isRoot={props?.isRoot}
      onSave={onSave}
      onOpenChange={() => {}}
    />,
  );
}

beforeEach(() => {
  onSave.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#1321 world 非根条目分类必填门控', () => {
  it('G1 非根 + 分类空 → save disabled（仅名称非空不够）', async () => {
    renderWorldDialog({ isRoot: false });
    const user = userEvent.setup();
    await user.type(screen.getByTestId('library-create-name'), '清河县城');
    expect(screen.getByTestId('library-create-save')).toBeDisabled();
  });

  it('G2 非根 + 分类非空 → save enabled', async () => {
    renderWorldDialog({ isRoot: false });
    const user = userEvent.setup();
    await user.type(screen.getByTestId('library-create-name'), '清河县城');
    await user.type(screen.getByLabelText('类别'), '地理');
    expect(screen.getByTestId('library-create-save')).toBeEnabled();
  });

  it('G3 根条目（isRoot=true）→ 分类输入框不渲染，名称非空即可 save（#722 守护）', async () => {
    renderWorldDialog({ isRoot: true });
    const user = userEvent.setup();
    await user.type(screen.getByTestId('library-create-name'), '世界观');
    expect(screen.queryByLabelText('类别')).not.toBeInTheDocument();
    expect(screen.getByTestId('library-create-save')).toBeEnabled();
  });

  it('G4 非根 + 分类空 → 必填提示锚点渲染；填入后消失', async () => {
    renderWorldDialog({ isRoot: false });
    const user = userEvent.setup();
    await user.type(screen.getByTestId('library-create-name'), '清河县城');
    expect(screen.getByTestId('library-create-category-required')).toBeInTheDocument();
    await user.type(screen.getByLabelText('类别'), '地理');
    expect(screen.queryByTestId('library-create-category-required')).not.toBeInTheDocument();
  });
});
