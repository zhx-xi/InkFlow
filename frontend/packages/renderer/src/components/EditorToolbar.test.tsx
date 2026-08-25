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
 *
 * F34 章节审计（Issue #208，spec §8.1 Q3=C 最小版）追加契约（2026-08-09）：
 * - 新 prop：onAudit: () => void（必填；renderToolbar helper 默认 props 已补 vi.fn()，
 *   既有用例零改动）
 * - 新按钮：aria-label（或 title）用 i18n 键 write.toolbar.audit（zh「审计」/ en「Audit」，
 *   GREEN 补 zh.ts + en.ts）；disabled 跟随 prop（与续写/生成一致）
 *
 * RED 预期（追加用例）：当前 EditorToolbar 无 onAudit prop 与审计按钮 →
 * 既有用例保持绿 + 新用例 element-missing（getByRole button 审计 找不到）；
 * tsc --noEmit 报 onAudit 属性缺失（TS2322，属 RED 的一部分）。
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
    onAudit: vi.fn(), // F34 #208：审计按钮回调（GREEN 前为多余键，无害）
    onStyleAnalyze: vi.fn(), // T2 风格检测：风格检测按钮回调（GREEN 前为多余键，无害）
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

describe('工具栏 — 审计按钮（F34 章节审计 Issue #208，spec §8.1 Q3=C）', () => {
  it('渲染：审计按钮（i18n write.toolbar.audit「审计」）', () => {
    renderToolbar();
    const toolbar = screen.getByTestId('editor-toolbar');
    expect(within(toolbar).getByRole('button', { name: '审计' })).toBeInTheDocument();
  });

  it('点击审计按钮 → onAudit 被调用', async () => {
    const user = userEvent.setup();
    const props = renderToolbar();
    const toolbar = screen.getByTestId('editor-toolbar');
    await user.click(within(toolbar).getByRole('button', { name: '审计' }));
    expect(props.onAudit).toHaveBeenCalledTimes(1);
  });

  it('disabled=true → 审计按钮禁用', () => {
    renderToolbar({ disabled: true });
    const toolbar = screen.getByTestId('editor-toolbar');
    expect(within(toolbar).getByRole('button', { name: '审计' })).toBeDisabled();
  });
});

describe('工具栏 — 视图切换按钮（#379 F47 §4.2）', () => {
  it('渲染 view-toggle（editor 视图时 aria-label 为「查看 AI 执行详情」）', () => {
    renderToolbar({ view: 'editor', onToggleView: vi.fn() });
    const toolbar = screen.getByTestId('editor-toolbar');
    const toggle = within(toolbar).getByTestId('view-toggle');
    expect(toggle).toHaveAttribute('aria-label', '查看 AI 执行详情');
  });

  it('detail 视图时 aria-label 为「返回正文编辑」', () => {
    renderToolbar({ view: 'detail', onToggleView: vi.fn() });
    const toolbar = screen.getByTestId('editor-toolbar');
    const toggle = within(toolbar).getByTestId('view-toggle');
    expect(toggle).toHaveAttribute('aria-label', '返回正文编辑');
  });

  it('点击 view-toggle → onToggleView 被调用', async () => {
    const user = userEvent.setup();
    const onToggleView = vi.fn();
    renderToolbar({ view: 'editor', onToggleView });
    const toolbar = screen.getByTestId('editor-toolbar');
    await user.click(within(toolbar).getByTestId('view-toggle'));
    expect(onToggleView).toHaveBeenCalledTimes(1);
  });
});

describe('工具栏 — 是否全自动切换按钮（#598 D9-a1）', () => {
  it('渲染 auto-toggle（aria-label 为「是否全自动」，位于 view-toggle 右侧）', () => {
    renderToolbar({ view: 'editor', onToggleView: vi.fn(), autoWriteEnabled: false, onToggleAuto: vi.fn() });
    const toolbar = screen.getByTestId('editor-toolbar');
    const toggle = within(toolbar).getByTestId('auto-toggle');
    expect(toggle).toHaveAttribute('aria-label', '是否全自动');
    // 位置：在 view-toggle 右侧（DOM 顺序）
    const viewToggle = within(toolbar).getByTestId('view-toggle');
    expect(viewToggle.compareDocumentPosition(toggle)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('autoWriteEnabled=false → aria-pressed=false（未授权态）', () => {
    renderToolbar({ autoWriteEnabled: false, onToggleAuto: vi.fn() });
    const toolbar = screen.getByTestId('editor-toolbar');
    expect(within(toolbar).getByTestId('auto-toggle')).toHaveAttribute('aria-pressed', 'false');
  });

  it('autoWriteEnabled=true → aria-pressed=true（已授权态）', () => {
    renderToolbar({ autoWriteEnabled: true, onToggleAuto: vi.fn() });
    const toolbar = screen.getByTestId('editor-toolbar');
    expect(within(toolbar).getByTestId('auto-toggle')).toHaveAttribute('aria-pressed', 'true');
  });

  it('点击 auto-toggle → onToggleAuto 被调用', async () => {
    const user = userEvent.setup();
    const onToggleAuto = vi.fn();
    renderToolbar({ autoWriteEnabled: false, onToggleAuto });
    const toolbar = screen.getByTestId('editor-toolbar');
    await user.click(within(toolbar).getByTestId('auto-toggle'));
    expect(onToggleAuto).toHaveBeenCalledTimes(1);
  });
});

describe('工具栏 — 风格检测按钮（T2 风格检测）', () => {
  it('渲染：风格检测按钮（testid toolbar-style-analyze，aria-label「风格检测」）', () => {
    renderToolbar();
    const toolbar = screen.getByTestId('editor-toolbar');
    const styleBtn = within(toolbar).getByTestId('toolbar-style-analyze');
    expect(styleBtn).toBeInTheDocument();
    expect(styleBtn).toHaveAttribute('aria-label', '风格检测');
  });

  it('点击风格检测按钮 → onStyleAnalyze 被调用', async () => {
    const user = userEvent.setup();
    const props = renderToolbar();
    const toolbar = screen.getByTestId('editor-toolbar');
    await user.click(within(toolbar).getByTestId('toolbar-style-analyze'));
    expect(props.onStyleAnalyze).toHaveBeenCalledTimes(1);
  });

  it('位置：在审计按钮右侧（DOM 顺序 FOLLOWING）', () => {
    renderToolbar();
    const toolbar = screen.getByTestId('editor-toolbar');
    const auditBtn = within(toolbar).getByRole('button', { name: '审计' });
    const styleBtn = within(toolbar).getByTestId('toolbar-style-analyze');
    expect(auditBtn.compareDocumentPosition(styleBtn)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});
