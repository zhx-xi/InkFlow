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

/** React hook：挂载时应用主题；语言变化时更新 html lang */
export function useThemeEffect(): void {
  const theme = useThemeStore((s) => s.theme);
  const bg = useThemeStore((s) => s.bg);
  const lang = useThemeStore((s) => s.lang);

  useEffect(() => {
    applyTheme(theme, bg);
    // #106 用户反馈：系统标题栏 overlay 跟随主题（Electron 方案 A）
    window.INKFLOW_API?.setTitleBarTheme?.(theme);
  }, [theme, bg]);

  // #106 修复：preload 注入晚于 React 挂载时，挂载期调用被可选链吞掉且主题不再变化，
  // 永不补发。监听 'inkflow:api-ready'（preload expose 完成后 dispatch）后补发当前主题，
  // 从 store getState 取最新值避免闭包过期；cleanup 移除监听防重复。
  useEffect(() => {
    const onApiReady = (): void => {
      window.INKFLOW_API?.setTitleBarTheme?.(useThemeStore.getState().theme);
    };
    window.addEventListener('inkflow:api-ready', onApiReady);
    return () => {
      window.removeEventListener('inkflow:api-ready', onApiReady);
    };
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  }, [lang]);
}
