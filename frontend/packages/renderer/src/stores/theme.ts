/** 主题/背景/语言 store（spec §4.3：localStorage 持久化 + 默认策略） */
import { create } from 'zustand';
import { BG_BY_THEME, type Lang, type ThemeBg, type ThemeName } from '../theme';

const STORAGE_KEY = 'inkflow.ui';

function readSaved(): { theme: ThemeName; bg: ThemeBg; lang: Lang } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { theme?: ThemeName; bg?: ThemeBg; lang?: Lang };
    return {
      theme: parsed.theme ?? 'paper',
      bg: parsed.bg ?? 'default',
      lang: parsed.lang ?? 'zh',
    };
  } catch {
    return null;
  }
}

function initialTheme(): ThemeName {
  const saved = readSaved();
  if (saved?.theme) return saved.theme;
  // 默认策略：未手动选择且系统深色偏好 → 夜航；否则素笺
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  return prefersDark ? 'night' : 'paper';
}

interface ThemeState {
  theme: ThemeName;
  bg: ThemeBg;
  lang: Lang;
  setTheme: (theme: ThemeName) => void;
  setBg: (bg: ThemeBg) => void;
  setLang: (lang: Lang) => void;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initialTheme(),
  bg: readSaved()?.bg ?? 'default',
  lang: readSaved()?.lang ?? 'zh',

  setTheme: (theme) => {
    // 背景变体随主题过滤（BG_BY_THEME 校验，非法组合回退 default）
    const validBgs = BG_BY_THEME[theme];
    const bg = validBgs.includes(get().bg) ? get().bg : 'default';
    set({ theme, bg });
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme, bg, lang: get().lang }));
  },
  setBg: (bg) => {
    set({ bg });
    const { theme, lang } = get();
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme, bg, lang }));
  },
  setLang: (lang) => {
    set({ lang });
    const { theme, bg } = get();
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme, bg, lang }));
  },
}));
