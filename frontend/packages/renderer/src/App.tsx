/** 应用骨架（spec §7.2：HashRouter 四路由 + 侧边导航 + 顶栏职责回归——页面标题/主题/语言/内核状态（品牌由侧边栏品牌区承载），不再承担导航） */
import { useEffect } from 'react';
import { HashRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useI18n } from './i18n/useI18n';
import { useThemeEffect } from './theme';
import { useThemeStore } from './stores/theme';
import type { Lang, ThemeName } from './theme';
import { AppNav } from './components/AppNav';
import { WindowControls } from './components/WindowControls';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './components/ui/select';
import { ToastHost } from './components/ui/toast';
import { WritingPage } from './pages/writing';
import { ModelsPage } from './pages/models';
import { ProjectsPage } from './pages/projects';
import { LibraryPage } from './pages/library';
import { SettingsPage } from './pages/settings';

/** 页面标题随路由变化（顶栏文本元素；正文 h1 承担 heading 语义） */
const TITLE_BY_PATH: Record<string, string> = {
  '/': 'pj.title',
  '/projects': 'pj.title',
  '/writing': 'nav.writing',
  '/library': 'lib.title',
  '/models': 'm.title',
  '/settings': 'set.title',
};

function AppLayout() {
  useThemeEffect();
  // F32 设置持久化（#152，spec §5.2 步骤 ②）：挂载时双轨加载设置（localStorage 快照 → 后端覆盖），恰好一次
  useEffect(() => {
    void useThemeStore.getState().initFromBackend();
  }, []);
  const { t, lang } = useI18n();
  const location = useLocation();
  const theme = useThemeStore((s) => s.theme);
  const setTheme = useThemeStore((s) => s.setTheme);
  const setLang = useThemeStore((s) => s.setLang);

  const pageTitleKey = TITLE_BY_PATH[location.pathname] ?? 'pj.title';

  return (
    <div className="flex h-dvh overflow-hidden">
      {/* 侧边导航（三分组/折叠；品牌 logo + 文字由品牌区承载，顶栏不再重复） */}
      <AppNav showBrand={true} />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* 顶栏：页面标题 + 全局状态；品牌已移至侧边栏品牌区，不再承担导航（无 role=link） */}
        <header
          role="banner"
          className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-surface px-4 [-webkit-app-region:drag]"
        >
          <span className="text-[13px] text-ink-2">{t(pageTitleKey)}</span>
          {/* #106 用户拍板：右侧末尾自绘窗口控制按钮（颜色随主题 + 背景变体） */}
          <div className="ml-auto flex h-full items-center gap-3">
            <Select value={theme} onValueChange={(v) => setTheme(v as ThemeName)}>
              <SelectTrigger
                data-testid="header-theme-select"
                aria-label={t('ap.theme')}
                className="w-auto [-webkit-app-region:no-drag]"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="paper">{t('theme.paper')}</SelectItem>
                <SelectItem value="night">{t('theme.night')}</SelectItem>
                <SelectItem value="ink">{t('theme.ink')}</SelectItem>
              </SelectContent>
            </Select>
            <Select value={lang} onValueChange={(v) => setLang(v as Lang)}>
              <SelectTrigger
                data-testid="header-lang-select"
                aria-label={t('ap.lang')}
                className="w-auto [-webkit-app-region:no-drag]"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="zh">{t('lang.zh')}</SelectItem>
                <SelectItem value="en">{t('lang.en')}</SelectItem>
              </SelectContent>
            </Select>
            <span className="text-[12px] text-ink-3 [-webkit-app-region:no-drag]">{t('sb.kernel')}</span>
            <WindowControls />
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<ProjectsPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/writing" element={<WritingPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/models" element={<ModelsPage />} />
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
