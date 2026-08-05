/**
 * AppearanceCard 测试契约（Issue #105 §6.2⑤ 主题可视化预览卡片，spec §7.4 设置页-常规 / §7.6）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 src/components/AppearanceCard.tsx 必须匹配：
 *
 * 结构（data-testid）：
 * - `appearance-card`：卡片根锚点（迁移到设置页常规分类后的新锚点；
 *   旧 `agent-appearance-card` 由页面级测试负责迁移，本文件不依赖旧锚点）
 * - `theme-preview-paper` / `theme-preview-night` / `theme-preview-ink`：
 *   三主题缩略预览卡（素笺/夜航/墨韵，CSS 色块模拟）
 *
 * 交互语义：
 * - 预览卡为 role="radio"（name = 素笺/夜航/墨韵），点击 → themeStore.theme 变更
 * - 选中态 = aria-checked="true" + accent ring（视觉类由实现决定，不测样式）
 * - 背景/语言下拉保持既有行为（combobox「背景」随主题过滤 / combobox「语言」切换 lang）
 *
 * 测试挂载：组件不依赖路由，直接 render；beforeEach 重置 theme store。
 * RED 预期：`appearance-card` / `theme-preview-*` testid 不存在 → element-missing。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppearanceCard } from './AppearanceCard';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('外观卡片 — 主题可视化预览卡（Issue #105 §6.2⑤）', () => {
  it('渲染：appearance-card 锚点 + 三主题缩略预览卡', () => {
    render(<AppearanceCard />);
    expect(screen.getByTestId('appearance-card')).toBeInTheDocument();
    expect(screen.getByTestId('theme-preview-paper')).toBeInTheDocument();
    expect(screen.getByTestId('theme-preview-night')).toBeInTheDocument();
    expect(screen.getByTestId('theme-preview-ink')).toBeInTheDocument();
  });

  it('点击预览卡 → themeStore.theme 变更（素笺/夜航/墨韵三主题）', async () => {
    const user = userEvent.setup();
    render(<AppearanceCard />);

    await user.click(screen.getByTestId('theme-preview-night'));
    expect(useThemeStore.getState().theme).toBe('night');

    await user.click(screen.getByTestId('theme-preview-ink'));
    expect(useThemeStore.getState().theme).toBe('ink');

    await user.click(screen.getByTestId('theme-preview-paper'));
    expect(useThemeStore.getState().theme).toBe('paper');
  });

  it('选中态：当前主题预览卡 aria-checked=true，其余 false（role=radio 语义）', () => {
    useThemeStore.setState({ theme: 'night', bg: 'navy', lang: 'zh' });
    render(<AppearanceCard />);

    const night = screen.getByTestId('theme-preview-night');
    const paper = screen.getByTestId('theme-preview-paper');
    expect(night).toHaveAttribute('aria-checked', 'true');
    expect(paper).toHaveAttribute('aria-checked', 'false');
    // 可访问性语义：预览卡暴露 role=radio（键盘可聚焦，选中态可被辅助技术读取）
    expect(night).toHaveAttribute('role', 'radio');
    expect(within(night).getByText('夜航')).toBeInTheDocument();
  });
});

describe('外观卡片 — 背景/语言下拉（迁移后行为不变）', () => {
  it('背景 combobox 随主题过滤：paper → 默认+羊皮纸，不含墨蓝黑/深褐纸', async () => {
    const user = userEvent.setup();
    render(<AppearanceCard />);

    await user.click(screen.getByRole('combobox', { name: '背景' }));
    const opts = await screen.findAllByRole('option');
    const names = opts.map((o) => o.textContent ?? '');
    expect(names).toContain('默认');
    expect(names).toContain('羊皮纸');
    expect(names).not.toContain('墨蓝黑');
    await user.keyboard('{Escape}');
  });

  it('语言切换：zh → en → themeStore.lang=en', async () => {
    const user = userEvent.setup();
    render(<AppearanceCard />);

    await user.click(screen.getByRole('combobox', { name: '语言' }));
    await user.click(await screen.findByRole('option', { name: 'EN' }));
    expect(useThemeStore.getState().lang).toBe('en');
  });
});
