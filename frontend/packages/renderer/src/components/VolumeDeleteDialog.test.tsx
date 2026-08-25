/**
 * VolumeDeleteDialog 契约测试（#648 卷管理 GUI CRUD，RED 阶段）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/components/VolumeDeleteDialog.tsx 并匹配：
 *
 * export interface VolumeDeleteDialogProps {
 *   open: boolean;
 *   volume: Volume;             // 待删除卷（标题展示在对话框内，标识删除目标）
 *   otherVolumes: Volume[];     // 「移动到其他卷」的目标候选（下拉选项 = 各卷标题）
 *   chapterCount: number;       // 卷内章节数：>0 需选择处理方式；=0 直接删（后端直接删）
 *   onConfirm: (options: { delete_chapters?: boolean; move_to?: string }) => void;
 *   onOpenChange: (open: boolean) => void;
 * }
 *
 * 结构 testid（前缀 vol-del）：
 * - vol-del-dialog（容器）
 * - vol-del-ok（删除确认按钮）
 * - vol-del-cancel（取消）
 * - vol-del-cascade（「级联删章」radio）
 * - vol-del-move（「移动到其他卷」radio）
 * - vol-del-target（目标卷下拉 trigger）
 *
 * 行为契约：
 * - open=false → 不渲染
 * - chapterCount > 0：
 *   删除按钮初始 disabled；
 *   选「级联删章」→ 删除 enabled，确认 → onConfirm({ delete_chapters: true })；
 *   选「移动到其他卷」→ 目标下拉启用（选项 = otherVolumes 标题），删除仍 disabled，
 *   直到选中目标卷才 enabled，确认 → onConfirm({ move_to: 目标id })
 * - chapterCount === 0：不渲染 radio，删除按钮直接 enabled，确认 → onConfirm({})
 * - 关闭路径：取消按钮 / 遮罩点击 → onOpenChange(false)
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { VolumeDeleteDialog } from './VolumeDeleteDialog';
import { useThemeStore } from '../stores/theme';
import type { Volume } from '../stores/chapter';

type DeleteOptions = { delete_chapters?: boolean; move_to?: string };

const volumes: Volume[] = [
  { id: 'v1', title: '第一卷 风起', order_index: 0 },
  { id: 'v2', title: '第二卷 云涌', order_index: 1 },
];

function renderDialog(
  overrides: Partial<{
    open: boolean;
    volume: Volume;
    otherVolumes: Volume[];
    chapterCount: number;
    onConfirm: (options: DeleteOptions) => void;
    onOpenChange: (open: boolean) => void;
  }> = {},
) {
  const props = {
    open: true,
    volume: volumes[0],
    otherVolumes: [volumes[1]],
    chapterCount: 3,
    onConfirm: vi.fn<(o: DeleteOptions) => void>(),
    onOpenChange: vi.fn<(o: boolean) => void>(),
    ...overrides,
  };
  render(<VolumeDeleteDialog {...props} />);
  return props;
}

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('VolumeDeleteDialog — 渲染', () => {
  it('open=false → 不渲染', () => {
    renderDialog({ open: false });
    expect(screen.queryByTestId('vol-del-dialog')).not.toBeInTheDocument();
  });

  it('chapterCount>0：对话框 + 卷标题 + 两个 radio（级联删章/移动到其他卷）+ 删除按钮初始 disabled', () => {
    renderDialog();
    const dlg = screen.getByTestId('vol-del-dialog');
    expect(within(dlg).getByText('第一卷 风起')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: '级联删章' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: '移动到其他卷' })).toBeInTheDocument();
    expect(screen.getByTestId('vol-del-ok')).toBeDisabled();
  });

  it('chapterCount=0：不渲染 radio，删除按钮直接 enabled', () => {
    renderDialog({ chapterCount: 0 });
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    expect(screen.getByTestId('vol-del-ok')).toBeEnabled();
  });
});

describe('VolumeDeleteDialog — 交互（chapterCount > 0）', () => {
  it('选「级联删章」→ 删除 enabled；确认 → onConfirm({ delete_chapters: true })', async () => {
    const props = renderDialog();
    const user = userEvent.setup();

    await user.click(screen.getByRole('radio', { name: '级联删章' }));
    expect(screen.getByTestId('vol-del-ok')).toBeEnabled();

    await user.click(screen.getByTestId('vol-del-ok'));
    expect(props.onConfirm).toHaveBeenCalledWith({ delete_chapters: true });
  });

  it('选「移动到其他卷」→ 目标下拉启用（选项=otherVolumes 标题）但删除仍 disabled；选中目标后才 enabled；确认 → onConfirm({ move_to: 目标id })', async () => {
    const props = renderDialog();
    const user = userEvent.setup();

    await user.click(screen.getByRole('radio', { name: '移动到其他卷' }));
    expect(screen.getByTestId('vol-del-target')).toBeEnabled();
    expect(screen.getByTestId('vol-del-ok')).toBeDisabled();

    await user.click(screen.getByTestId('vol-del-target'));
    await user.click(await screen.findByRole('option', { name: '第二卷 云涌' }));
    expect(screen.getByTestId('vol-del-ok')).toBeEnabled();

    await user.click(screen.getByTestId('vol-del-ok'));
    expect(props.onConfirm).toHaveBeenCalledWith({ move_to: 'v2' });
  });

  it('取消按钮 → onOpenChange(false)，onConfirm 不调用', async () => {
    const props = renderDialog();
    const user = userEvent.setup();

    await user.click(screen.getByTestId('vol-del-cancel'));
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
    expect(props.onConfirm).not.toHaveBeenCalled();
  });

  it('遮罩点击 → onOpenChange(false)', () => {
    const props = renderDialog();
    const dlg = screen.getByTestId('vol-del-dialog');
    fireEvent.click(dlg.parentElement as HTMLElement);
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe('VolumeDeleteDialog — 交互（chapterCount === 0）', () => {
  it('删除直接可用；确认 → onConfirm({})（无处理方式，后端直接删）', async () => {
    const props = renderDialog({ chapterCount: 0, otherVolumes: [] });
    const user = userEvent.setup();

    await user.click(screen.getByTestId('vol-del-ok'));
    expect(props.onConfirm).toHaveBeenCalledWith({});
  });
});
