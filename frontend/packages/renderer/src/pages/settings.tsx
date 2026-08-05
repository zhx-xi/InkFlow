/** 设置页（spec §7.4：五分类导航 + 右侧面板 + 即改即存；AgentChainCard 迁移、AppearanceCard 行为并入常规） */
import { useEffect, useId, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Bot, Cpu, FileText, SlidersHorizontal, UserRound } from 'lucide-react';
import inkflowIcon from '../assets/inkflow-icon-plain.svg?url&no-inline';
import inkflowIconDark from '../assets/inkflow-icon-plain-dark.svg?url&no-inline';
import inkflowIconInk from '../assets/inkflow-icon-plain-ink.svg?url&no-inline';
import { AgentChainCard } from '../components/AgentChainCard';
import { RadioGroup, RadioGroupItem } from '../components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { useI18n } from '../i18n/useI18n';
import { apiFetch, ensureApiReady } from '../api/client';
import { useAgentStore } from '../stores/agent';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';
import { BG_BY_THEME, type Lang, type ThemeBg, type ThemeName } from '../theme';
import { cn } from '../lib/cn';

type CatKey = 'general' | 'models' | 'agent' | 'templates' | 'account';
type FontKey = 'serif' | 'sans' | 'mono';

const LOGO_BY_THEME: Record<ThemeName, string> = {
  paper: inkflowIcon,
  night: inkflowIconDark,
  ink: inkflowIconInk,
};

const CATS: Array<{ key: CatKey; labelKey: string; icon: typeof SlidersHorizontal }> = [
  { key: 'general', labelKey: 'set.cat.general', icon: SlidersHorizontal },
  { key: 'models', labelKey: 'set.cat.models', icon: Cpu },
  { key: 'agent', labelKey: 'set.cat.agent', icon: Bot },
  { key: 'templates', labelKey: 'set.cat.templates', icon: FileText },
  { key: 'account', labelKey: 'set.cat.account', icon: UserRound },
];

const CAT_KEYS = CATS.map((c) => c.key);

function isCatKey(v: string | null): v is CatKey {
  return v !== null && (CAT_KEYS as string[]).includes(v);
}

/** 快捷键一览（spec §7.4：Ctrl+Z/Y/S/Enter/Shift+Enter 五组；动作文案复用写作工具栏既有 key） */
const SHORTCUTS: Array<{ combo: string; labelKey: string }> = [
  { combo: 'Ctrl+Z', labelKey: 'write.toolbar.undo' },
  { combo: 'Ctrl+Y', labelKey: 'write.toolbar.redo' },
  { combo: 'Ctrl+S', labelKey: 'write.toolbar.save' },
  { combo: 'Ctrl+Enter', labelKey: 'write.toolbar.continue' },
  { combo: 'Shift+Enter', labelKey: 'write.toolbar.generate' },
];

/** 常规分类：语言 / 主题三选 / 背景变体 / 编辑器字体 / 新章节默认字数 / 快捷键一览 */
function GeneralPanel() {
  const { t } = useI18n();
  const radioGroupId = useId();
  const theme = useThemeStore((s) => s.theme);
  const bg = useThemeStore((s) => s.bg);
  const lang = useThemeStore((s) => s.lang);
  const setTheme = useThemeStore((s) => s.setTheme);
  const setBg = useThemeStore((s) => s.setBg);
  const setLang = useThemeStore((s) => s.setLang);
  const pushToast = useToastStore((s) => s.pushToast);
  // 编辑器字体 / 新章节默认字数：#106 config 字段落定前为本地状态（数字项失焦即存 toast）
  const [font, setFont] = useState<FontKey>('sans');

  const THEMES: Array<{ value: ThemeName; labelKey: string }> = [
    { value: 'paper', labelKey: 'theme.paper' },
    { value: 'night', labelKey: 'theme.night' },
    { value: 'ink', labelKey: 'theme.ink' },
  ];
  const FONTS: Array<{ value: FontKey; labelKey: string }> = [
    { value: 'serif', labelKey: 'set.font.serif' },
    { value: 'sans', labelKey: 'set.font.sans' },
    { value: 'mono', labelKey: 'set.font.mono' },
  ];

  return (
    <section className="space-y-5 rounded-lg border border-line bg-surface p-6 shadow-card">
      <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
        <span>{t('ap.lang')}</span>
        <Select value={lang} onValueChange={(v) => setLang(v as Lang)}>
          <SelectTrigger aria-label={t('ap.lang')} className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="zh">{t('lang.zh')}</SelectItem>
            <SelectItem value="en">{t('lang.en')}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="text-[12px] text-ink-2">{t('ap.theme')}</div>
        <RadioGroup
          value={theme}
          onValueChange={(v) => setTheme(v as ThemeName)}
          aria-label={t('ap.theme')}
          className="flex gap-4"
        >
          {THEMES.map((th) => (
            <div key={th.value} className="flex items-center gap-1.5 text-[13px]">
              <RadioGroupItem value={th.value} id={`${radioGroupId}-${th.value}`} />
              <label htmlFor={`${radioGroupId}-${th.value}`} className="cursor-pointer">
                {t(th.labelKey)}
              </label>
            </div>
          ))}
        </RadioGroup>
      </div>

      <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
        <span>{t('ap.bg')}</span>
        <Select value={bg} onValueChange={(v) => setBg(v as ThemeBg)}>
          <SelectTrigger aria-label={t('ap.bg')} className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {BG_BY_THEME[theme].map((b) => (
              <SelectItem key={b} value={b}>
                {t(`bg.${b}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
        <span>{t('set.font')}</span>
        <Select value={font} onValueChange={(v) => setFont(v as FontKey)}>
          <SelectTrigger aria-label={t('set.font')} className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FONTS.map((f) => (
              <SelectItem key={f.value} value={f.value}>
                {t(f.labelKey)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
        <span>{t('set.defaultWords')}</span>
        <input
          type="number"
          min={0}
          aria-label={t('set.defaultWords')}
          className="w-56 rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
          defaultValue={800000}
          onBlur={() => pushToast('ok', t('toast.saved'))}
        />
      </div>

      <div data-testid="settings-shortcuts" className="rounded-md border border-line p-4">
        <div className="text-[12px] font-medium text-ink-2">{t('set.shortcuts.title')}</div>
        <div className="mt-3 space-y-2">
          {SHORTCUTS.map((s) => (
            <div key={s.combo} className="flex items-center justify-between text-[13px]">
              <span className="text-ink-2">{t(s.labelKey)}</span>
              <kbd className="rounded border border-line bg-surface-3 px-2 py-0.5 font-mono text-[12px] text-ink">
                {s.combo}
              </kbd>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/** 模型分类：#106 落地前为摘要 + 占位 */
function ModelsPanel() {
  const { t } = useI18n();
  return (
    <section className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <h2 className="font-serif text-[17px] font-semibold">{t('set.models.summary')}</h2>
      <p className="mt-1 text-[12px] text-ink-3">{t('set.models.placeholder')}</p>
    </section>
  );
}

/** Agent 分类：AgentChainCard（行为不变）+ 默认模型下拉 */
function AgentPanel() {
  const { t } = useI18n();
  const config = useAgentStore((s) => s.config);
  const setConfig = useAgentStore((s) => s.setConfig);

  return (
    <div className="space-y-5">
      <AgentChainCard />
      <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
        <span>{t('ag.defaultModel')}</span>
        <Select
          value={config.model ? config.model : undefined}
          onValueChange={(v) => setConfig({ model: v })}
        >
          <SelectTrigger aria-label={t('ag.defaultModel')} className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {['openai', 'deepseek', 'ollama'].map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

/** 模板分类：#107 落地前为占位 */
function TemplatesPanel() {
  const { t } = useI18n();
  return (
    <section className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <h2 className="font-serif text-[17px] font-semibold">{t('set.cat.templates')}</h2>
      <p className="mt-1 text-[12px] text-ink-3">{t('set.templates.placeholder')}</p>
    </section>
  );
}

/** 账户分类：数据目录 + 数据管理（占位）+ 关于（版本/logo） */
function AccountPanel() {
  const { t } = useI18n();
  const theme = useThemeStore((s) => s.theme);
  const [version, setVersion] = useState<string | null>(null);

  // 版本号不硬编码：读内核 /health 的 version 字段（内核为唯一版本源）
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await ensureApiReady();
      try {
        const data = await apiFetch<{ version?: string }>('/health');
        if (!cancelled && typeof data.version === 'string' && data.version) setVersion(data.version);
      } catch {
        if (!cancelled) setVersion(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="space-y-5 rounded-lg border border-line bg-surface p-6 shadow-card">
      <div className="flex items-center justify-between">
        <span className="text-[12px] text-ink-2">{t('set.account.dataDir')}</span>
        <span className="font-mono text-[13px] text-ink">~/.inkflow/data</span>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[12px] text-ink-2">{t('set.account.dataMgr')}</span>
        <span className="text-[12px] text-ink-3">{t('set.account.dataMgrPlaceholder')}</span>
      </div>
      <div className="flex items-center gap-3">
        <img src={LOGO_BY_THEME[theme]} alt="" aria-hidden="true" className="h-8 w-8" />
        <div>
          <div className="text-[13px] font-medium text-ink">{t('set.account.about')}</div>
          <div className="text-[12px] text-ink-3">
            {t('app.brand')}
            {version ? ` ${t('set.account.version')} v${version}` : ''}
          </div>
        </div>
      </div>
    </section>
  );
}

export function SettingsPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeCat, setActiveCat] = useState<CatKey>(() => {
    const p = searchParams.get('cat');
    return isCatKey(p) ? p : 'general';
  });

  // URL cat 查询参数变化（AppNav Agent 快捷入口 /settings?cat=agent 直达）→ 同步激活分类
  useEffect(() => {
    const p = searchParams.get('cat');
    if (isCatKey(p) && p !== activeCat) setActiveCat(p);
  }, [searchParams, activeCat]);

  const handleCatChange = (key: CatKey) => {
    setActiveCat(key);
    setSearchParams({ cat: key });
  };

  return (
    <div data-testid="settings-page" className="flex h-full">
      <nav
        data-testid="settings-nav"
        aria-label={t('set.title')}
        className="w-48 shrink-0 border-r border-line bg-surface-2 py-4"
      >
        <div className="space-y-1 px-3">
          {CATS.map((cat) => (
            <button
              key={cat.key}
              type="button"
              data-testid={`settings-cat-${cat.key}`}
              aria-current={cat.key === activeCat ? 'page' : undefined}
              className={cn(
                'flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors duration-180 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                cat.key === activeCat
                  ? 'bg-accent-weak font-medium text-accent'
                  : 'text-ink-2 hover:bg-surface-3 hover:text-ink',
              )}
              onClick={() => handleCatChange(cat.key)}
            >
              <cat.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="truncate">{t(cat.labelKey)}</span>
            </button>
          ))}
        </div>
      </nav>

      <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="px-8 pb-2 pt-8">
          <h1 className="font-serif text-[26px] font-semibold">{t('set.title')}</h1>
        </div>
        <div data-testid="settings-panel" className="px-8 pb-10 pt-4">
          {activeCat === 'general' && <GeneralPanel />}
          {activeCat === 'models' && <ModelsPanel />}
          {activeCat === 'agent' && (
            <div data-testid="settings-agent-panel">
              <AgentPanel />
            </div>
          )}
          {activeCat === 'templates' && <TemplatesPanel />}
          {activeCat === 'account' && <AccountPanel />}
        </div>
      </div>
    </div>
  );
}
