/**
 * F59-M3 (#964) RED 契约 A — components/ThinkingLevelSelect 组件契约。
 *
 * 契约源：plan.md §四 components/ThinkingLevelSelect.tsx（逐字为准）：
 *  - props：value / onChange / disabled? / disabledTooltip? / className?
 *  - testid：chat-reasoning-effort（select）
 *            chat-reasoning-effort-tooltip（disabled 时）
 *            chat-reasoning-effort-option-<value>（7 个 option）
 *  - aria-label = t('reasoning.chat.label')；option 文案 = t(`reasoning.level.${value}`)
 *  - disabled → select 带 disabled 属性 + tooltip 元素文案 = disabledTooltip
 *
 * RED 形态：src/components/ThinkingLevelSelect.tsx 故意不存在 → import 失败（文件级 collection error）。
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, renderHook } from '@testing-library/react';

import { ThinkingLevelSelect } from './ThinkingLevelSelect';
import { useI18n } from '../i18n/useI18n';
import { useThemeStore } from '../stores/theme';

/** 七档（与 plan §四 REASONING_EFFORTS 顺序一致，组件未建故此处硬编码） */
const EFFORTS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'default'] as const;

describe('ThinkingLevelSelect — 渲染契约（#964）', () => {
  it('UI 必须出现：渲染后 chat-reasoning-effort 可见', () => {
    render(<ThinkingLevelSelect value="default" onChange={vi.fn()} />);
    expect(screen.getByTestId('chat-reasoning-effort')).toBeInTheDocument();
  });

  it('七档全覆盖：chat-reasoning-effort-option-<v> 各 1 个', () => {
    render(<ThinkingLevelSelect value="default" onChange={vi.fn()} />);
    for (const v of EFFORTS) {
      expect(screen.getByTestId(`chat-reasoning-effort-option-${v}`)).toBeInTheDocument();
    }
  });

  it('option 文案走 i18n：zh 下 default=跟随模型默认、high=高', () => {
    useThemeStore.setState({ lang: 'zh' });
    render(<ThinkingLevelSelect value="default" onChange={vi.fn()} />);
    expect(screen.getByTestId('chat-reasoning-effort-option-default')).toHaveTextContent('跟随模型默认');
    expect(screen.getByTestId('chat-reasoning-effort-option-high')).toHaveTextContent('高');
  });

  it('option 文案走 i18n：en 下 default=Model default、high=High', () => {
    useThemeStore.setState({ lang: 'en' });
    render(<ThinkingLevelSelect value="default" onChange={vi.fn()} />);
    expect(screen.getByTestId('chat-reasoning-effort-option-default')).toHaveTextContent('Model default');
    expect(screen.getByTestId('chat-reasoning-effort-option-high')).toHaveTextContent('High');
  });

  it('value=default → select.value === default', () => {
    render(<ThinkingLevelSelect value="default" onChange={vi.fn()} />);
    const select = screen.getByTestId('chat-reasoning-effort') as HTMLSelectElement;
    expect(select.value).toBe('default');
  });

  it('改选 high → onChange 收到 high（toHaveBeenCalledWith）', () => {
    const onChange = vi.fn();
    render(<ThinkingLevelSelect value="default" onChange={onChange} />);
    fireEvent.change(screen.getByTestId('chat-reasoning-effort'), { target: { value: 'high' } });
    expect(onChange).toHaveBeenCalledWith('high');
  });

  it('disabled 未传 → select 不禁用、无 chat-reasoning-effort-tooltip 元素', () => {
    render(<ThinkingLevelSelect value="default" onChange={vi.fn()} />);
    expect(screen.getByTestId('chat-reasoning-effort')).not.toBeDisabled();
    expect(screen.queryByTestId('chat-reasoning-effort-tooltip')).not.toBeInTheDocument();
  });

  it('disabled + disabledTooltip=X → select 禁用 + tooltip 元素出现且文本 X', () => {
    render(<ThinkingLevelSelect value="default" onChange={vi.fn()} disabled disabledTooltip="X" />);
    expect(screen.getByTestId('chat-reasoning-effort')).toBeDisabled();
    expect(screen.getByTestId('chat-reasoning-effort-tooltip')).toHaveTextContent('X');
  });

  it('aria：select aria-label = t("reasoning.chat.label")（zh 思考级别）', () => {
    useThemeStore.setState({ lang: 'zh' });
    const { result } = renderHook(() => useI18n());
    const expectedLabel = result.current.t('reasoning.chat.label');
    expect(expectedLabel).toBe('思考级别');
    render(<ThinkingLevelSelect value="default" onChange={vi.fn()} />);
    expect(screen.getByTestId('chat-reasoning-effort').getAttribute('aria-label')).toBe(expectedLabel);
  });
});
