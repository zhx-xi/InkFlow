/** #722 创建根世界观去掉「类别」输入框（根不应有类别）。新契约测试，独立文件。 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LibraryCreateDialog } from './LibraryCreateDialog';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('LibraryCreateDialog — #722 根世界观去掉「类别」输入框', () => {
  it('创建根世界观（isRoot=true）不渲染类别输入框，仍保留名称/内容', () => {
    render(
      <LibraryCreateDialog open cat="world" isRoot onSave={vi.fn()} onOpenChange={vi.fn()} />,
    );
    expect(screen.queryByLabelText('类别')).not.toBeInTheDocument();
    expect(screen.getByLabelText('名称')).toBeInTheDocument();
  });

  it('创建子/下级世界观（isRoot=false）渲染类别输入框', () => {
    render(
      <LibraryCreateDialog open cat="world" isRoot={false} onSave={vi.fn()} onOpenChange={vi.fn()} />,
    );
    expect(screen.getByLabelText('类别')).toBeInTheDocument();
  });
});
