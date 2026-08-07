import { useEffect } from 'react';
import { useThemeStore } from '../stores/theme';

/** 主题/背景变体/语言类型（与 tokens.css data-* 属性对应） */
export type ThemeName = 'paper' | 'night' | 'ink';
export type ThemeBg = 'default' | 'parchment' | 'navy' | 'ochre';
export type Lang = 'zh' | 'en';
/** 编辑器字体（F32 #152：从 settings.tsx 本地定义移入统一类型，入设置库持久化） */
export type FontKey = 'serif' | 'sans' | 'mono';

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
