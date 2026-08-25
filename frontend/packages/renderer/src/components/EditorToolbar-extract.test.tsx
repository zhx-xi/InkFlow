/**
 * 写作页编辑器工具栏「AI 提取」入口 RED 契约测试（#652）。
 *
 * 【契约（父侧定稿）】
 * - EditorToolbar 新增可选 prop onExtract?: () => void
 * - 工具栏图标行末（audit 分隔线之后）新增「AI 提取」图标按钮
 *   data-testid='extract-entry-write'（aria-label = i18n write.toolbar.extract）
 * - 点击 → 回调 onExtract（打开 AIExtractDialog，由 writing.tsx 接线）
 * - onExtract 未传（既有用法，如旧测试）→ 按钮可选渲染或不渲染（契约宽松：
 *   仅 onExtract 存在时渲染该图标，避免破坏既有调用点）
 *
 * 【RED 预期失败形态】extract-entry-write 不存在（EditorToolbar 未加图标）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorToolbar } from './EditorToolbar';

beforeEach(() => {
  vi.restoreAllMocks();
});

function renderToolbar(overrides: Partial<React.ComponentProps<typeof EditorToolbar>> = {}) {
  return render(
    <EditorToolbar
      disabled={false}
      onUndo={() => {}}
      onRedo={() => {}}
      onSave={() => {}}
      onContinue={() => {}}
      onGenerate={() => {}}
      onAudit={() => {}}
      {...overrides}
    />,
  );
}

describe('写作页工具栏 — 「AI 提取」入口（#652）', () => {
  it('契约1：传入 onExtract → 渲染 AI 提取图标按钮（extract-entry-write）', () => {
    renderToolbar({ onExtract: () => {} });
    expect(screen.getByTestId('extract-entry-write')).toBeInTheDocument();
  });

  it('契约2：点击 AI 提取图标 → 调用 onExtract 回调', async () => {
    const user = userEvent.setup();
    const onExtract = vi.fn();
    renderToolbar({ onExtract });
    await user.click(screen.getByTestId('extract-entry-write'));
    expect(onExtract).toHaveBeenCalledTimes(1);
  });

  it('契约3（守护）：未传 onExtract（既有调用点）→ 不渲染该图标，既有按钮零回归', () => {
    renderToolbar();
    expect(screen.queryByTestId('extract-entry-write')).not.toBeInTheDocument();
    // 既有控件仍在
    expect(screen.getByTestId('toolbar-save')).toBeInTheDocument();
    expect(screen.getByTestId('view-toggle')).toBeInTheDocument();
  });
});
