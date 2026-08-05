/** 应用骨架（spec §7.2：HashRouter 四路由 + 侧边导航 + 顶栏职责回归——品牌/页面标题/主题/语言/内核状态，不再承担导航） */
import { HashRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { type MouseEvent as ReactMouseEvent } from 'react';
import inkflowIcon from './assets/inkflow-icon-plain.svg?url&no-inline';
import inkflowIconDark from './assets/inkflow-icon-plain-dark.svg?url&no-inline';
import inkflowIconInk from './assets/inkflow-icon-plain-ink.svg?url&no-inline';
import { useI18n } from './i18n/useI18n';
import { useThemeEffect } from './theme';
import { useThemeStore } from './stores/theme';
import type { ThemeName } from './theme';
import { AppNav } from './components/AppNav';
import { ToastHost } from './components/ui/toast';
import { WritingPage } from './pages/writing';
import { ProjectsPage } from './pages/projects';
import { LibraryPage } from './pages/library';
import { SettingsPage } from './pages/settings';

/** 品牌图标按主题三版切换（spec §5.2.8：环流口，paper→素笺/ night→夜航/ ink→墨韵） */
const LOGO_BY_THEME: Record<ThemeName, string> = {
  paper: inkflowIcon,
  night: inkflowIconDark,
  ink: inkflowIconInk,
};

/** 页面标题随路由变化（顶栏文本元素；正文 h1 承担 heading 语义） */
const TITLE_BY_PATH: Record<string, string> = {
  '/': 'pj.title',
  '/projects': 'pj.title',
  '/writing': 'nav.writing',
  '/library': 'lib.title',
  '/settings': 'set.title',
};

const THEME_CYCLE: ThemeName[] = ['paper', 'night', 'ink'];

function AppLayout() {
  useThemeEffect();
  const { t, lang } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);
  const setLang = useThemeStore((s) => s.setLang);

  const pageTitleKey = TITLE_BY_PATH[location.pathname] ?? 'pj.title';
  const toggleTheme = () => {
    const next = THEME_CYCLE[(THEME_CYCLE.indexOf(theme) + 1) % THEME_CYCLE.length];
    setTheme(next);
  };
  const toggleLang = () => setLang(lang === 'zh' ? 'en' : 'zh');

  // Agent 快捷入口整行可点（spec §7.2）：jsdom 无命中测试，userEvent 点击包装 div 无法落到内部
  // NavLink（AppNav 已落盘不可改），由 App 层委托接管；真实浏览器中内部 <a> 自行导航，不重复接管
  const handleShortcutClick = (e: ReactMouseEvent<HTMLDivElement>) => {
    const target = e.target as Element;
    if (target.closest?.('[data-testid="appnav-agent-shortcut"]') && !target.closest('a')) {
      e.preventDefault();
      navigate('/settings?cat=agent');
    }
  };

  return (
    <div className="flex h-dvh overflow-hidden" onClick={handleShortcutClick}>
      {/* 侧边导航（三分组/折叠；品牌文字由顶栏承载，避免重复） */}
      <AppNav showBrand={false} />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* 顶栏：品牌 + 页面标题 + 全局状态；不再承担导航（无 role=link） */}
        <header
          role="banner"
          className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-surface px-4"
        >
          <img src={LOGO_BY_THEME[theme]} alt="" aria-hidden="true" className="h-6 w-6" />
          <span className="font-serif text-[15px] font-semibold">{t('app.brand')}</span>
          <span className="text-[13px] text-ink-2">{t(pageTitleKey)}</span>
          <div className="ml-auto flex items-center gap-3">
            <button
              type="button"
              data-testid="header-theme-toggle"
              aria-label={t('ap.theme')}
              className="rounded-md border border-line px-2.5 py-1 text-[12px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={toggleTheme}
            >
              {t(`theme.${theme}`)}
            </button>
            <button
              type="button"
              data-testid="header-lang"
              aria-label={t('ap.lang')}
              className="rounded-md border border-line px-2.5 py-1 text-[12px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={toggleLang}
            >
              {t(`lang.${lang}`)}
            </button>
            <span className="text-[12px] text-ink-3">{t('sb.kernel')}</span>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<ProjectsPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/writing" element={<WritingPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/projects" replace />} />
          </Routes>
        </main>
      </div>

      {/* Toast 挂载点（布局根部，fixed 定位） */}
      <ToastHost />
    </div>
  );
}

export function App() {
  return (
    <HashRouter>
      <AppLayout />
    </HashRouter>
  );
}
