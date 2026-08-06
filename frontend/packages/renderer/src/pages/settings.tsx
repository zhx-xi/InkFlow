/** 设置页（spec §7.4：五分类导航 + 右侧面板 + 即改即存；AgentChainCard 迁移、AppearanceCard 行为并入常规） */
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Bot, Cpu, FileText, SlidersHorizontal, UserRound } from 'lucide-react';
import inkflowIcon from '../assets/inkflow-icon-plain.svg?url&no-inline';
import inkflowIconDark from '../assets/inkflow-icon-plain-dark.svg?url&no-inline';
import inkflowIconInk from '../assets/inkflow-icon-plain-ink.svg?url&no-inline';
import { AgentChainCard } from '../components/AgentChainCard';
import { AppearanceCard } from '../components/AppearanceCard';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { useI18n } from '../i18n/useI18n';
import { apiFetch, ensureApiReady } from '../api/client';
import { useAgentStore } from '../stores/agent';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';
import type { ThemeName } from '../theme';
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

/** 快捷键一览（spec §7.4：Ctrl+Z/Y/S/Enter 五组；#105 修复批：生成 = Ctrl+Shift+Enter 非 Shift+Enter） */
const SHORTCUTS: Array<{ combo: string; labelKey: string }> = [
  { combo: 'Ctrl+Z', labelKey: 'write.toolbar.undo' },
  { combo: 'Ctrl+Y', labelKey: 'write.toolbar.redo' },
  { combo: 'Ctrl+S', labelKey: 'write.toolbar.save' },
  { combo: 'Ctrl+Enter', labelKey: 'write.toolbar.continue' },
  { combo: 'Ctrl+Shift+Enter', labelKey: 'write.toolbar.generate' },
];

/** 常规分类：AppearanceCard（语言/主题/背景，#105 🔴-3）+ 编辑器字体 + 新章节默认字数（真实 PATCH）+ 快捷键一览 */
function GeneralPanel() {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const setConfig = useAgentStore((s) => s.setConfig);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  // #105 修复批二次迭代 🟡-D：默认字数值接当前项目 config（本地编辑态，失焦 setConfig + 真实 PATCH）
  const [defaultWords, setDefaultWords] = useState<string>(() => {
    const project = useProjectStore.getState().projects.find(
      (p) => p.id === useProjectStore.getState().currentProjectId,
    );
    return String(project?.config.default_words ?? 800000);
  });
  const [font, setFont] = useState<FontKey>('sans');

  const FONTS: Array<{ value: FontKey; labelKey: string }> = [
    { value: 'serif', labelKey: 'set.font.serif' },
    { value: 'sans', labelKey: 'set.font.sans' },
    { value: 'mono', labelKey: 'set.font.mono' },
  ];

  const handleDefaultWordsBlur = () => {
    const n = Number(defaultWords);
    // 空值 / 非法值：无变更不弹 toast
    if (defaultWords === '' || !Number.isFinite(n)) return;
    // 与后端 ge=1000 对齐：低于下限不发 PATCH，直接 err toast
    if (n < 1000) {
      pushToast('err', t('toast.saveFailed'));
      return;
    }
    // 合并源 = agent store 当前 config（含 agent_* 已配置字段），而非 project store 旧快照（🔴-B）
    const current = useAgentStore.getState().config;
    setConfig({ ...current, default_words: n });
    const project = useProjectStore.getState().projects.find((p) => p.id === currentProjectId);
    if (project) {
      void apiFetch(`/api/v1/projects/${project.id}`, {
        method: 'PATCH',
        body: { config: { ...useAgentStore.getState().config, default_words: n } },
      })
        .then(() => pushToast('ok', t('toast.saved')))
        .catch(() => pushToast('err', t('toast.saveFailed')));
    }
  };

  return (
    <div className="space-y-5">
      <AppearanceCard />
      <section className="space-y-5 rounded-lg border border-line bg-surface p-6 shadow-card">
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
            value={defaultWords}
            onChange={(e) => setDefaultWords(e.target.value)}
            onBlur={handleDefaultWordsBlur}
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
    </div>
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

/** Agent 分类：AgentChainCard（行为不变，开关即改即存 #105 🔴-2）+ 默认模型下拉 */
function AgentPanel() {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const config = useAgentStore((s) => s.config);
  const setConfig = useAgentStore((s) => s.setConfig);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);

  // #105 修复批二次迭代 🔴-A：播种守卫收紧——仅当 config 不含 model 且无任何 agent_* 字段时才播种
  //（general 先改 default_words 的草稿不拦截，进入 Agent 分类仍按项目 config 重新播种）
  useEffect(() => {
    const c = useAgentStore.getState().config;
    const hasAgentFields = Object.keys(c).some((k) => k.startsWith('agent_') || k === 'model');
    if (hasAgentFields) return;
    const state = useProjectStore.getState();
    const project = state.projects.find((p) => p.id === state.currentProjectId);
    if (project) useAgentStore.getState().loadFromProject(project.config);
  }, [currentProjectId]);

  // #105 修复批二次迭代 🟡-E：saveConfig 失败弹 err toast；in-flight 守卫防并发 PATCH，
  // 期间再次变更挂起，待当前 PATCH 结束后以最新 config 补存（不丢最后一次 toggle）
  const persistingRef = useRef(false);
  const pendingRef = useRef(false);
  const persist = () => {
    if (!currentProjectId) return;
    if (persistingRef.current) {
      pendingRef.current = true;
      return;
    }
    persistingRef.current = true;
    void useAgentStore
      .getState()
      .saveConfig(currentProjectId)
      .catch(() => pushToast('err', t('toast.saveFailed')))
      .finally(() => {
        persistingRef.current = false;
        if (pendingRef.current) {
          pendingRef.current = false;
          persist();
        }
      });
  };

  return (
    <div className="space-y-5">
      <AgentChainCard onConfigChange={persist} />
      <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
        <span>{t('ag.defaultModel')}</span>
        <Select
          value={config.model ? config.model : undefined}
          onValueChange={(v) => {
            setConfig({ model: v });
            persist();
          }}
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
