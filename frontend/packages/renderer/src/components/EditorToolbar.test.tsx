/**
 * EditorToolbar 测试契约（Issue #105 §6.2④ 快捷键提示，spec §7.6）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 src/components/EditorToolbar.tsx 必须匹配：
 *
 * §6.2④ 快捷键提示（新增，双通道发现性 #79 Q2 拍板 C 延续）：
 * - 每个工具栏按钮暴露 title 属性，内容含对应快捷键（实现二选一：
 *   A. title={i18n 文案 + ' (Ctrl+Z)'}；B. 新增 i18n key write.toolbar.undoShortcut 等
 *   —— 断言按 stringContaining 快捷键字面量，不锁死格式）
 * - 快捷键映射（与写作页监听一致）：
 *   撤销 Ctrl+Z / 重做 Ctrl+Y / 保存 Ctrl+S / 续写 Ctrl+Enter / 生成 Ctrl+Shift+Enter
 * - hover 浮层为 title 的原生表现（jsdom 不测视觉浮层，title 属性即契约锚点）
 *
 * 既有行为保持（迁移自 writing.test.tsx 工具栏断言）：
 * - 按钮：撤销/重做（i18n 文案）、保存 data-testid="toolbar-save"、续写/生成
 * - disabled 传递：续写/生成按钮 disabled 跟随 prop
 * - 点击回调：onUndo/onRedo/onSave/onContinue/onGenerate
 *
 * RED 预期：当前按钮无 title 属性 → toHaveAttribute('title') 断言 FAIL。
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EditorToolbar } from './EditorToolbar';

function renderToolbar(overrides: Partial<Parameters<typeof EditorToolbar>[0]> = {}) {
  const props = {
    disabled: false,
    onUndo: vi.fn(),
    onRedo: vi.fn(),
    onSave: vi.fn(),
    onContinue: vi.fn(),
    onGenerate: vi.fn(),
    ...overrides,
  };
  render(<EditorToolbar {...props} />);
  return props;
}

describe('工具栏 — 快捷键提示（Issue #105 §6.2④）', () => {
  it('撤销/重做/保存/续写/生成按钮 title 含对应快捷键', () => {
    renderToolbar();
    const toolbar = screen.getByTestId('editor-toolbar');

    expect(within(toolbar).getByRole('button', { name: '撤销' })).toHaveAttribute('title', expect.stringContaining('Ctrl+Z'));
    expect(within(toolbar).getByRole('button', { name: '重做' })).toHaveAttribute('title', expect.stringContaining('Ctrl+Y'));
    expect(within(toolbar).getByTestId('toolbar-save')).toHaveAttribute('title', expect.stringContaining('Ctrl+S'));
    expect(within(toolbar).getByRole('button', { name: '续写' })).toHaveAttribute('title', expect.stringContaining('Ctrl+Enter'));
    expect(within(toolbar).getByRole('button', { name: '生成' })).toHaveAttribute('title', expect.stringContaining('Ctrl+Shift+Enter'));
  });

  it('快捷键提示可区分：生成含 Shift、续写不含 Shift（防复制粘贴错误）', () => {
    renderToolbar();
    const toolbar = screen.getByTestId('editor-toolbar');

    expect(within(toolbar).getByRole('button', { name: '生成' })).toHaveAttribute('title', expect.stringContaining('Shift+Enter'));
    expect(within(toolbar).getByRole('button', { name: '续写' })).toHaveAttribute('title', expect.not.stringContaining('Shift'));
  });
});

describe('工具栏 — 既有行为保持（迁移自 writing.test.tsx）', () => {
  it('渲染：撤销/重做/保存/续写/生成 + toolbar-save testid', () => {
    renderToolbar();
    const toolbar = screen.getByTestId('editor-toolbar');
    expect(within(toolbar).getByRole('button', { name: '撤销' })).toBeInTheDocument();
    expect(within(toolbar).getByRole('button', { name: '重做' })).toBeInTheDocument();
    expect(within(toolbar).getByTestId('toolbar-save')).toBeInTheDocument();
    expect(within(toolbar).getByRole('button', { name: '续写' })).toBeInTheDocument();
    expect(within(toolbar).getByRole('button', { name: '生成' })).toBeInTheDocument();
  });

  it('disabled 传递：续写/生成按钮禁用（其余可用）', () => {
    renderToolbar({ disabled: true });
    const toolbar = screen.getByTestId('editor-toolbar');
    expect(within(toolbar).getByRole('button', { name: '续写' })).toBeDisabled();
    expect(within(toolbar).getByRole('button', { name: '生成' })).toBeDisabled();
    expect(within(toolbar).getByRole('button', { name: '撤销' })).toBeEnabled();
    expect(within(toolbar).getByTestId('toolbar-save')).toBeEnabled();
  });

  it('点击回调：撤销/重做/保存/续写/生成各自触发', async () => {
    const user = userEvent.setup();
    const props = renderToolbar();
    const toolbar = screen.getByTestId('editor-toolbar');

    await user.click(within(toolbar).getByRole('button', { name: '撤销' }));
    expect(props.onUndo).toHaveBeenCalledTimes(1);

    await user.click(within(toolbar).getByRole('button', { name: '重做' }));
    expect(props.onRedo).toHaveBeenCalledTimes(1);

    await user.click(within(toolbar).getByTestId('toolbar-save'));
    expect(props.onSave).toHaveBeenCalledTimes(1);

    await user.click(within(toolbar).getByRole('button', { name: '续写' }));
    expect(props.onContinue).toHaveBeenCalledTimes(1);

    await user.click(within(toolbar).getByRole('button', { name: '生成' }));
    expect(props.onGenerate).toHaveBeenCalledTimes(1);
  });
});
