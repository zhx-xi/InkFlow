/**
 * #699 世界观分类弹窗增加 kind 类型选择（geo/abstract），默认 geo。
 * 契约：onSave(name, kind)；kind 单选 testid world-cat-kind-geo / world-cat-kind-abstract。
 * 该文件为本 issue 新建（此前无 WorldCategoryDialog 测试）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorldCategoryDialog } from './WorldCategoryDialog';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('WorldCategoryDialog — #699 kind 选择', () => {
  it('kind 单选可见，默认 geo 选中', () => {
    render(<WorldCategoryDialog open onSave={vi.fn()} onOpenChange={vi.fn()} />);
    expect(screen.getByTestId('world-cat-kind-geo')).toBeChecked();
    expect(screen.getByTestId('world-cat-kind-abstract')).not.toBeChecked();
  });

  it('默认 geo 保存 → onSave(name, "geo")', async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<WorldCategoryDialog open onSave={onSave} onOpenChange={vi.fn()} />);
    await user.type(screen.getByTestId('world-cat-name'), '势力');
    await user.click(screen.getByTestId('world-cat-save'));
    expect(onSave).toHaveBeenCalledWith('势力', 'geo');
  });

  it('选抽象类 → onSave(name, "abstract")', async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<WorldCategoryDialog open onSave={onSave} onOpenChange={vi.fn()} />);
    await user.click(screen.getByTestId('world-cat-kind-abstract'));
    await user.type(screen.getByTestId('world-cat-name'), '门派');
    await user.click(screen.getByTestId('world-cat-save'));
    expect(onSave).toHaveBeenCalledWith('门派', 'abstract');
  });
});

describe('WorldCategoryDialog — 空名校验（spec N5）', () => {
  it('名称为空 → 保存按钮 disabled + 显示「分类名不能为空」红字', () => {
    render(<WorldCategoryDialog open onSave={vi.fn()} onOpenChange={vi.fn()} />);
    expect(screen.getByTestId('world-cat-save')).toBeDisabled();
    expect(screen.getByText('分类名不能为空')).toBeInTheDocument();
  });

  it('输入名称后 → 保存按钮 enabled + 红字消失', async () => {
    const user = userEvent.setup();
    render(<WorldCategoryDialog open onSave={vi.fn()} onOpenChange={vi.fn()} />);
    await user.type(screen.getByTestId('world-cat-name'), '势力');
    expect(screen.getByTestId('world-cat-save')).toBeEnabled();
    expect(screen.queryByText('分类名不能为空')).not.toBeInTheDocument();
  });
});
