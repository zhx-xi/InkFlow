/** 侧边导航（spec §7.2：三分组 / 52px 可折叠窄条 / Agent 快捷入口 / NavLink active 态） */
import { useState, type ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';
import {
  BookOpen,
  Bot,
  ChevronsLeft,
  ChevronsRight,
  Clock,
  Cpu,
  Database,
  FolderOpen,
  Globe,
  Library,
  ListTree,
  PenLine,
  Settings,
  Sparkles,
  Users,
  type LucideIcon,
} from 'lucide-react';
import inkflowIcon from '../assets/inkflow-icon-plain.svg?url&no-inline';
import inkflowIconDark from '../assets/inkflow-icon-plain-dark.svg?url&no-inline';
import inkflowIconInk from '../assets/inkflow-icon-plain-ink.svg?url&no-inline';
import { useI18n } from '../i18n/useI18n';
import { useThemeStore } from '../stores/theme';
import type { ThemeName } from '../theme';
import { cn } from '../lib/cn';

/** 品牌图标按主题三版切换（与 App 顶栏同源模式） */
const LOGO_BY_THEME: Record<ThemeName, string> = {
  paper: inkflowIcon,
  night: inkflowIconDark,
  ink: inkflowIconInk,
};

interface NavItemDef {
  key: string;
  href?: string;
  labelKey: string;
  icon: LucideIcon;
}

const WRITING_ITEMS: NavItemDef[] = [
  { key: 'writing', href: '/writing', labelKey: 'nav.writing', icon: PenLine },
  { key: 'projects', href: '/projects', labelKey: 'nav.projects', icon: BookOpen },
];

const LIBRARY_ITEMS: NavItemDef[] = [
  { key: 'library', href: '/library', labelKey: 'nav.library', icon: Library },
  { key: 'characters', href: '/library?cat=characters', labelKey: 'nav.lib.characters', icon: Users },
  { key: 'world', href: '/library?cat=world', labelKey: 'nav.lib.world', icon: Globe },
  { key: 'outline', href: '/library?cat=outline', labelKey: 'nav.lib.outline', icon: ListTree },
  { key: 'timeline', href: '/library?cat=timeline', labelKey: 'nav.lib.timeline', icon: Clock },
  { key: 'foreshadow', href: '/library?cat=foreshadow', labelKey: 'nav.lib.foreshadow', icon: Sparkles },
  { key: 'rag', href: '/library?cat=rag', labelKey: 'nav.lib.rag', icon: Database },
];

/** models = #106 占位禁用项（无 href，点击不导航）；agent 快捷入口直达 /settings?cat=agent */
const SYSTEM_ITEMS: Array<NavItemDef & { placeholder?: boolean }> = [
  { key: 'models', labelKey: 'nav.models', icon: Cpu, placeholder: true },
  { key: 'agent', href: '/settings?cat=agent', labelKey: 'nav.agent', icon: Bot },
  { key: 'settings', href: '/settings', labelKey: 'nav.settings', icon: Settings },
];

function navCls({ isActive }: { isActive: boolean }) {
  return cn(
    'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors duration-180',
    isActive
      ? 'bg-accent-weak font-medium text-accent'
      : 'text-ink-2 hover:bg-surface-3 hover:text-ink',
  );
}

function NavGroup({
  testKey,
  labelKey,
  icon: Icon,
  collapsed,
  children,
}: {
  testKey: string;
  labelKey: string;
  icon: LucideIcon;
  collapsed: boolean;
  children: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div data-testid={`nav-group-${testKey}`} className="px-2">
      <div
        className={cn(
          'flex items-center gap-1.5 px-2 pb-1 pt-3 text-[10px] font-medium uppercase tracking-[0.14em] text-ink-3',
          collapsed && 'justify-center px-0 py-2',
        )}
      >
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        {!collapsed && <span className="truncate">{t(labelKey)}</span>}
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

export function AppNav({ showBrand = true }: { showBrand?: boolean }) {
  const { t } = useI18n();
  const theme = useThemeStore((s) => s.theme);
  const [collapsed, setCollapsed] = useState(false);

  return (
    <nav
      data-testid="app-nav"
      data-collapsed={collapsed ? 'true' : undefined}
      aria-label={t('nav.group.writing')}
      className={cn(
        'flex shrink-0 flex-col border-r border-line bg-surface-2 transition-[width] duration-180',
        collapsed ? 'w-[52px]' : 'w-[216px]',
      )}
    >
      {/* 品牌区：logo 装饰性（三主题变体）+ 文字（App 内由顶栏承载品牌，showBrand=false 隐藏文字避免重复） */}
      <div className={cn('flex items-center gap-2 border-b border-line px-3 py-2.5', collapsed && 'justify-center px-0')}>
        <img src={LOGO_BY_THEME[theme]} alt="" aria-hidden="true" className="h-6 w-6 shrink-0" />
        {showBrand && !collapsed && (
          <span className="truncate font-serif text-[15px] font-semibold text-ink">{t('app.brand')}</span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        <NavGroup testKey="writing" labelKey="nav.group.writing" icon={FolderOpen} collapsed={collapsed}>
          {WRITING_ITEMS.map((item) => (
            <NavLink key={item.key} to={item.href!} className={navCls} data-testid={`nav-item-${item.key}`}>
              <item.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              {!collapsed && <span className="truncate">{t(item.labelKey)}</span>}
            </NavLink>
          ))}
        </NavGroup>

        <NavGroup testKey="library" labelKey="nav.group.library" icon={Library} collapsed={collapsed}>
          {LIBRARY_ITEMS.map((item) => (
            <NavLink
              key={item.key}
              to={item.href!}
              className={({ isActive }) => cn(navCls({ isActive }), item.key === 'library' && 'font-medium')}
              data-testid={`nav-item-${item.key}`}
            >
              <item.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              {!collapsed && <span className="truncate">{t(item.labelKey)}</span>}
            </NavLink>
          ))}
        </NavGroup>

        <NavGroup testKey="system" labelKey="nav.group.system" icon={Settings} collapsed={collapsed}>
          {SYSTEM_ITEMS.map((item) => {
            if (item.placeholder) {
              // #106 模型管理：占位禁用项，渲染但不导航
              return (
                <div
                  key={item.key}
                  data-testid={`nav-item-${item.key}`}
                  aria-disabled="true"
                  className={cn(navCls({ isActive: false }), 'cursor-not-allowed opacity-50')}
                >
                  <item.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  {!collapsed && <span className="truncate">{t(item.labelKey)}</span>}
                </div>
              );
            }
            const isAgent = item.key === 'agent';
            const link = isAgent ? (
              // Agent 为快捷入口而非页面：用 Link 渲染，不产生 aria-current（页面归属为「设置」）
              <Link
                key={item.key}
                to={item.href!}
                className={navCls({ isActive: false })}
                data-testid={`nav-item-${item.key}`}
              >
                <item.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {!collapsed && <span className="truncate">{t(item.labelKey)}</span>}
              </Link>
            ) : (
              <NavLink
                key={item.key}
                to={item.href!}
                className={navCls}
                data-testid={`nav-item-${item.key}`}
              >
                <item.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {!collapsed && <span className="truncate">{t(item.labelKey)}</span>}
              </NavLink>
            );
            return isAgent ? (
              <div key={item.key} data-testid="appnav-agent-shortcut">
                {link}
              </div>
            ) : (
              link
            );
          })}
        </NavGroup>
      </div>

      <div className="flex-none border-t border-line p-2">
        {collapsed ? (
          <button
            type="button"
            data-testid="nav-expand-btn"
            aria-label={t('nav.expand')}
            className="flex w-full items-center justify-center rounded-md px-2.5 py-1.5 text-ink-3 transition-colors duration-180 hover:bg-surface-3 hover:text-ink"
            onClick={() => setCollapsed(false)}
          >
            <ChevronsRight className="h-4 w-4" aria-hidden="true" />
          </button>
        ) : (
          <button
            type="button"
            data-testid="nav-collapse-btn"
            aria-label={t('nav.collapse')}
            className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[12px] text-ink-3 transition-colors duration-180 hover:bg-surface-3 hover:text-ink"
            onClick={() => setCollapsed(true)}
          >
            <ChevronsLeft className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{t('nav.collapse')}</span>
          </button>
        )}
      </div>
    </nav>
  );
}
