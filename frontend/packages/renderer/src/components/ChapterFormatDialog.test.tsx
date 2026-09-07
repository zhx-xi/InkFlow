/**
 * ChapterFormatDialog 契约测试（Issue #999 章节标题双编号归一化，RED-3 批）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/components/ChapterFormatDialog.tsx 并匹配：
 *
 * export interface ChapterFormatDialogProps {
 *   open: boolean;
 *   onOpenChange: (open: boolean) => void;
 *   onSelectArabic: () => void;   // 全书统一为「第N章」（阿拉伯序号）
 *   onSelectChinese: () => void;  // 全书统一为「第X章」（中文序号）
 * }
 *
 * 结构 testid：
 * - chapter-format-dialog（容器；open=false 不渲染）
 * - chapter-format-arabic
 * - chapter-format-chinese
 * - chapter-format-cancel
 *
 * 行为契约（受控组件，#376 红线：关闭断言一律断回调，不断言 DOM 消失后再交互）：
 * - open=false → 不渲染容器；
 * - 点击 arabic → onSelectArabic()；点击 chinese → onSelectChinese()；
 * - Esc → onOpenChange(false)（镜像 ConfirmDialog 的 document keydown Esc 关闭）；
 * - 取消按钮 → onOpenChange(false)。
 *
 * 文案键（en.ts + zh.ts 双份，GREEN 补词条）：tree.formatDialog.title / message / arabic / chinese。
 * RED 期词条缺失 → useI18n().t 回退返回键名（仍非空）；本测试只断言非空，#999 表意文案由 GREEN 定稿。
 * i18n 处理方式照既有 dialog 测试（VolumeDeleteDialog）：真实 useI18n（theme store lang='zh'），不 mock t()。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ChapterFormatDialog } from './ChapterFormatDialog';
import { useThemeStore } from '../stores/theme';

function renderDialog(
  overrides: Partial<{
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onSelectArabic: () => void;
    onSelectChinese: () => void;
  }> = {},
) {
  const props = {
    open: true,
    onOpenChange: vi.fn<(open: boolean) => void>(),
    onSelectArabic: vi.fn(),
    onSelectChinese: vi.fn(),
    ...overrides,
  };
  render(<ChapterFormatDialog {...props} />);
  return props;
}

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('ChapterFormatDialog — 渲染', () => {
  it('open=false → 不渲染容器', () => {
    renderDialog({ open: false });
    expect(screen.queryByTestId('chapter-format-dialog')).not.toBeInTheDocument();
  });

  it('open=true → 渲染对话框 + arabic/chinese/cancel 三个按钮', () => {
    renderDialog();
    expect(screen.getByTestId('chapter-format-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('chapter-format-arabic')).toBeInTheDocument();
    expect(screen.getByTestId('chapter-format-chinese')).toBeInTheDocument();
    expect(screen.getByTestId('chapter-format-cancel')).toBeInTheDocument();
  });

  it('i18n 键 tree.formatDialog.* 渲染出非空文案（RED 期键缺失 → t() 回退键名仍非空；GREEN 补词条不翻测试）', () => {
    renderDialog();
    const dlg = screen.getByTestId('chapter-format-dialog');
    expect(dlg.textContent?.trim().length).toBeGreaterThan(0);
    expect(screen.getByTestId('chapter-format-arabic').textContent?.trim().length).toBeGreaterThan(0);
    expect(screen.getByTestId('chapter-format-chinese').textContent?.trim().length).toBeGreaterThan(0);
    expect(screen.getByTestId('chapter-format-cancel').textContent?.trim().length).toBeGreaterThan(0);
  });
});

describe('ChapterFormatDialog — 交互（受控，#376：断回调不断 DOM）', () => {
  it('点击 arabic → onSelectArabic() 被调', () => {
    const props = renderDialog();
    fireEvent.click(screen.getByTestId('chapter-format-arabic'));
    expect(props.onSelectArabic).toHaveBeenCalled();
  });

  it('点击 chinese → onSelectChinese() 被调', () => {
    const props = renderDialog();
    fireEvent.click(screen.getByTestId('chapter-format-chinese'));
    expect(props.onSelectChinese).toHaveBeenCalled();
  });

  it('点击 cancel → onOpenChange(false)', () => {
    const props = renderDialog();
    fireEvent.click(screen.getByTestId('chapter-format-cancel'));
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });

  it('Esc → onOpenChange(false)', () => {
    const props = renderDialog();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });
});
