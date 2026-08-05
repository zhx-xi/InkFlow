/** 应用骨架：HashRouter 三路由（spec §4.2：file:// 与 Electron 生产兼容） */
import { HashRouter, Navigate, NavLink, Route, Routes } from 'react-router-dom';
import inkflowIcon from './assets/inkflow-icon-plain.svg';
import inkflowIconDark from './assets/inkflow-icon-plain-dark.svg';
import inkflowIconInk from './assets/inkflow-icon-plain-ink.svg';
import { useI18n } from './i18n/useI18n';
import { useThemeEffect } from './theme';
import { useThemeStore } from './stores/theme';
import type { ThemeName } from './theme';
import { WritingPage } from './pages/writing';
import { ProjectsPage } from './pages/projects';
import { AgentsPage } from './pages/agents';

/** 品牌图标按主题三版切换（spec §5.2.8：环流口，paper→素笺 / night→夜航 / ink→墨韵） */
const LOGO_BY_THEME: Record<ThemeName, string> = {
  paper: inkflowIcon,
  night: inkflowIconDark,
  ink: inkflowIconInk,
};

function AppLayout() {
  useThemeEffect();
  const { t } = useI18n();
  const theme = useThemeStore((s) => s.theme);

  const navCls = ({ isActive }: { isActive: boolean }) =>
    `rounded px-3 py-1 text-[13px] transition-colors duration-180 ${
      isActive ? 'bg-accent text-accent-ink' : 'text-ink-2 hover:text-ink'
    }`;

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center gap-4 border-b border-line bg-surface px-4 py-2">
        <img src={LOGO_BY_THEME[theme]} alt="" aria-hidden="true" className="h-6 w-6" />
        <span className="font-serif text-[15px] font-semibold">{t('app.brand')}</span>
        <nav className="flex gap-1">
          <NavLink to="/projects" className={navCls}>
            {t('nav.projects')}
          </NavLink>
          <NavLink to="/writing" className={navCls}>
            {t('nav.writing')}
          </NavLink>
          <NavLink to="/agents" className={navCls}>
            {t('nav.agents')}
          </NavLink>
        </nav>
      </header>
      <div className="min-h-0 flex-1">
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/writing" element={<WritingPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="*" element={<Navigate to="/projects" replace />} />
        </Routes>
      </div>
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
