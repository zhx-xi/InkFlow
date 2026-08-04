import { useEffect } from 'react';
import { useThemeStore } from '../stores/theme';

/** 主题/背景变体/语言类型（与 tokens.css data-* 属性对应） */
export type ThemeName = 'paper' | 'night' | 'ink';
export type ThemeBg = 'default' | 'parchment' | 'navy' | 'ochre';
export type Lang = 'zh' | 'en';

/** 各主题支持的背景变体（下拉随主题过滤） */
export const BG_BY_THEME: Record<ThemeName, ThemeBg[]> = {
  paper: ['default', 'parchment'],
  night: ['default', 'navy'],
  ink: ['default', 'ochre'],
};

/** 应用主题到 html + body（双写：body 自带 data-theme 会覆盖继承值，原型踩坑教训） */
export function applyTheme(theme: ThemeName, bg: ThemeBg = 'default'): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.dataset.bg = bg;
  document.body.dataset.theme = theme;
  document.body.dataset.bg = bg;
}

/** 解析初始主题（spec §4.3 默认策略：首次素笺；未手动选择且系统深色 → 夜航；手动选择以 localStorage 为准） */
export function resolveInitialTheme(): { theme: ThemeName; bg: ThemeBg } {
  const saved = localStorage.getItem('inkflow.ui');
  if (saved) {
    try {
      const parsed = JSON.parse(saved) as { theme?: ThemeName; bg?: ThemeBg };
      if (parsed.theme) return { theme: parsed.theme, bg: parsed.bg ?? 'default' };
    } catch {
      /* 损坏的持久化数据回退默认 */
    }
  }
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  return { theme: prefersDark ? 'night' : 'paper', bg: 'default' };
}

/** React hook：挂载时应用主题；语言变化时更新 html lang */
export function useThemeEffect(): void {
  const theme = useThemeStore((s) => s.theme);
  const bg = useThemeStore((s) => s.bg);
  const lang = useThemeStore((s) => s.lang);

  useEffect(() => {
    applyTheme(theme, bg);
  }, [theme, bg]);

  useEffect(() => {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  }, [lang]);
}
