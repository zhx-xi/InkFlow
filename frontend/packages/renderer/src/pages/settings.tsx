/** 设置页（spec §7.4：五分类导航 + 右侧面板 + 即改即存；AgentChainCard 迁移、AppearanceCard 行为并入常规） */
import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Bot, Cpu, FileText, SlidersHorizontal, UserRound } from 'lucide-react';
import inkflowIcon from '../assets/inkflow-icon-plain.svg?url&no-inline';
import inkflowIconDark from '../assets/inkflow-icon-plain-dark.svg?url&no-inline';
import inkflowIconInk from '../assets/inkflow-icon-plain-ink.svg?url&no-inline';
import { AgentChainCard } from '../components/AgentChainCard';
import { AppearanceCard } from '../components/AppearanceCard';
import { TemplateDialog } from '../components/TemplateDialog';
import { Switch } from '../components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import type { CloseBehavior } from '../api/client';
import { apiFetch, ensureApiReady, errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useAgentStore } from '../stores/agent';
import { useProjectStore } from '../stores/project';
import type { AgentTemplate, AgentTemplateInput } from '../stores/templates';
import { useTemplatesStore } from '../stores/templates';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';
import type { FontKey, ThemeName } from '../theme';
import { cn } from '../lib/cn';

type CatKey = 'general' | 'models' | 'agent' | 'templates' | 'account';

/** #189：页面顶部保存指示状态（隐藏 / 保存中 / 已保存，参考 Notion/Google Docs 顶部指示模式） */
type SaveState = 'idle' | 'saving' | 'saved';

/** #189：输入停止后自动保存的防抖间隔（ms） */
const DEFAULT_WORDS_DEBOUNCE_MS = 800;
/** #189：「已保存」指示自动隐藏间隔（ms） */
const SAVE_INDICATOR_HIDE_MS = 2_000;

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

/** 常规分类：AppearanceCard（语言/主题/背景，#105 🔴-3）+ 编辑器字体 + 关闭窗口时 + 首次托盘提示 + 新章节默认字数（真实 PATCH）+ 快捷键一览 */
function GeneralPanel() {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  // F32（#152，spec §6.3 对照表）：font / closeBehavior / trayHintDismissed 从统一设置 store 读
  //（组件本地 state 移除；行为 setter PATCH 成功才 IPC + 更新，失败回弹）
  const font = useThemeStore((s) => s.font);
  const setFont = useThemeStore((s) => s.setFont);
  const closeBehavior = useThemeStore((s) => s.closeBehavior);
  const setCloseBehavior = useThemeStore((s) => s.setCloseBehavior);
  const trayHintDismissed = useThemeStore((s) => s.trayHintDismissed);
  const setTrayHintDismissed = useThemeStore((s) => s.setTrayHintDismissed);

  // F32（#152，spec §5.4 Q3=C）：default_words ref 镜像 + dirty 跟踪——
  // 卸载 cleanup 闭包依赖 []，经 ref 读最新值（评审 🟡-7：防陈旧 state 捕获）
  const valueRef = useRef<string>(
    String(
      useProjectStore
        .getState()
        .projects.find((p) => p.id === useProjectStore.getState().currentProjectId)?.config.default_words ?? 800000,
    ),
  );
  const dirtyRef = useRef(false);
  const [defaultWords, setDefaultWords] = useState<string>(valueRef.current);
  const [, setDirty] = useState(false); // 渲染镜像：dirty 置位触发重渲染（值本身无 UI 消费）
  // #189：保存指示状态 + 计时器 ref（防抖 flush 与「已保存」自动隐藏各一）
  const [saveState, setSaveState] = useState<SaveState>('idle');
  const saveHideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const FONTS: Array<{ value: FontKey; labelKey: string }> = [
    { value: 'serif', labelKey: 'set.font.serif' },
    { value: 'sans', labelKey: 'set.font.sans' },
    { value: 'mono', labelKey: 'set.font.mono' },
  ];

  const CLOSE_BEHAVIORS: Array<{ value: CloseBehavior; labelKey: string }> = [
    { value: 'tray', labelKey: 'set.closeBehavior.tray' },
    { value: 'quit', labelKey: 'set.closeBehavior.quit' },
  ];

  // #167 F31：挂载时经 IPC 取当前行为（浏览器 dev 无 API 时可选链吞掉）；
  // F32 后仅回填 store 不触发 PATCH——与 initFromBackend 两处并存幂等（spec §5.3）
  useEffect(() => {
    void window.INKFLOW_API?.settings?.getCloseBehavior()?.then((v) => {
      useThemeStore.setState({ closeBehavior: v });
    });
  }, []);

  const markDirty = (v: string) => {
    valueRef.current = v;
    dirtyRef.current = true;
    setDefaultWords(v);
    setDirty(true);
    // #189：输入停止防抖自动保存——Electron 托盘关闭路径（hide 不卸载、无失焦）下 flush 兜底；
    // 与失焦/卸载 flush 幂等（flush 成功清 dirty，重复触发自然跳过）
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(() => {
      debounceTimerRef.current = null;
      if (dirtyRef.current) flushDefaultWords();
    }, DEFAULT_WORDS_DEBOUNCE_MS);
  };

  // F32（#152，spec §5.4 flushDefaultWords 契约）：空值/非法 → 静默不 PATCH；
  // <1000 → err toast 不 PATCH（与后端 ge=1000 对齐）；合法 → updateConfig 单次 PATCH 完整 config
  // + project store 本地合并（评审 🔴-2）；成功 → agent store setConfig + 清 dirty + ok toast；
  // 失败 → err toast + agent store 不被污染（缺陷 #4）+ dirty 保持；无当前项目 → 不保存（评审 🟢）
  const flushDefaultWords = () => {
    const n = Number(valueRef.current);
    if (valueRef.current === '' || !Number.isFinite(n)) return;
    if (n < 1000) {
      pushToast('err', t('toast.saveFailed'));
      return;
    }
    const project = useProjectStore
      .getState()
      .projects.find((p) => p.id === useProjectStore.getState().currentProjectId);
    if (!project) return;
    // #189：保存指示——开始保存 → 成功「已保存」约 2s 后隐藏；失败回到隐藏（提示走 err toast）
    setSaveState('saving');
    // 合并源 = agent store 当前 config（含 agent_* 已配置字段），而非 project store 旧快照（#105 🔴-B）
    const current = useAgentStore.getState().config;
    void useProjectStore
      .getState()
      .updateConfig(project.id, { ...current, default_words: n })
      .then(() => {
        useAgentStore.getState().setConfig({ ...current, default_words: n });
        valueRef.current = String(n);
        dirtyRef.current = false;
        setDirty(false);
        pushToast('ok', t('toast.saved'));
        setSaveState('saved');
        if (saveHideTimerRef.current) clearTimeout(saveHideTimerRef.current);
        saveHideTimerRef.current = setTimeout(() => setSaveState('idle'), SAVE_INDICATOR_HIDE_MS);
      })
      .catch(() => {
        setSaveState('idle');
        pushToast('err', t('toast.saveFailed'));
      });
  };

  const handleDefaultWordsBlur = () => {
    if (dirtyRef.current) flushDefaultWords();
  };

  // 切项目重读（缺陷 #2 修复）：currentProjectId 变化 → 重读新项目 config.default_words + 清 dirty
  //（dirty 编辑被丢弃是有意行为——项目切换 = 上下文切换，跨项目保留草稿无场景）
  useEffect(() => {
    const p = useProjectStore
      .getState()
      .projects.find((x) => x.id === useProjectStore.getState().currentProjectId);
    const v = String(p?.config.default_words ?? 800000);
    valueRef.current = v;
    dirtyRef.current = false;
    setDefaultWords(v);
    setDirty(false);
    // #189：丢弃旧项目 pending 防抖（防旧 timer 对已切换的项目补存）
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
  }, [currentProjectId]);

  // #189（rc1 发布缺陷）：窗口隐藏到托盘（Electron hide 不卸载、无失焦）→
  // document visibilitychange(hidden) → dirty 时 flush；卸载时移除监听
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.hidden && dirtyRef.current) flushDefaultWords();
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- flushDefaultWords 经 ref/store 读最新值，闭包身份无关
  }, []);

  // 卸载守卫（缺陷 #1 修复）：跳页/切分类时若 dirty → flush（fire-and-forget）
  useEffect(() => () => {
    // #189：清理防抖 / 保存指示计时器（防卸载后 timer 回调 setState）
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    if (saveHideTimerRef.current) clearTimeout(saveHideTimerRef.current);
    if (dirtyRef.current) flushDefaultWords();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 契约：依赖 [] 经 ref 读最新值（spec §5.4 实现注意）
  }, []);

  return (
    <div className="space-y-5">
      {/* #189：页面正上方保存指示（默认隐藏；保存中/已保存文案，约 2s 后自动隐藏） */}
      <div
        data-testid="settings-save-indicator"
        className={cn(
          'h-4 text-[12px] transition-opacity duration-200',
          saveState === 'idle' ? 'opacity-0' : 'opacity-100',
          saveState === 'saved' ? 'text-ok' : 'text-ink-3',
        )}
      >
        {saveState === 'saving' ? t('set.saving') : saveState === 'saved' ? t('set.saved') : ''}
      </div>
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
          <span>{t('set.closeBehavior')}</span>
          <Select value={closeBehavior} onValueChange={(v) => void setCloseBehavior(v as CloseBehavior)}>
            <SelectTrigger aria-label={t('set.closeBehavior')} className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CLOSE_BEHAVIORS.map((b) => (
                <SelectItem key={b.value} value={b.value}>
                  {t(b.labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* F32（#152，spec §6.2）：首次托盘提示开关——默认开（提示）= !trayHintDismissed；
            关闭 → setTrayHintDismissed(true)（PATCH + IPC dismiss 链路在 store） */}
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-col gap-1">
            <span className="text-[12px] text-ink-2">{t('set.trayHint')}</span>
            <span className="text-[11px] text-ink-3">{t('set.trayHintDesc')}</span>
          </div>
          <Switch
            data-testid="settings-tray-hint-switch"
            checked={!trayHintDismissed}
            onCheckedChange={(checked) => void setTrayHintDismissed(!checked)}
            aria-label={t('set.trayHint')}
          />
        </div>

        <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
          <span>{t('set.defaultWords')}</span>
          <input
            type="number"
            min={0}
            aria-label={t('set.defaultWords')}
            className="w-56 rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
            value={defaultWords}
            onChange={(e) => markDirty(e.target.value)}
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

/** 模板分类（#107 转正，spec §9.2.5 / §9.5 / M4）：列表卡片 + 新建/编辑/删除/设为默认 + 风险确认 */
function TemplatesPanel() {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const templates = useTemplatesStore((s) => s.templates);
  const loading = useTemplatesStore((s) => s.loading);
  const loadTemplates = useTemplatesStore((s) => s.loadTemplates);
  const createTemplate = useTemplatesStore((s) => s.createTemplate);
  const updateTemplate = useTemplatesStore((s) => s.updateTemplate);
  const deleteTemplate = useTemplatesStore((s) => s.deleteTemplate);
  const setDefault = useTemplatesStore((s) => s.setDefault);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AgentTemplate | null>(null);
  const [pendingDelete, setPendingDelete] = useState<AgentTemplate | null>(null);
  const [pendingSave, setPendingSave] = useState<{
    id: number;
    input: AgentTemplateInput;
    template: AgentTemplate;
  } | null>(null);

  useEffect(() => {
    void loadTemplates();
  }, [loadTemplates]);

  const handleCreate = async (input: AgentTemplateInput) => {
    try {
      await createTemplate(input);
      setDialogOpen(false);
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  const handleUpdate = async (input: AgentTemplateInput) => {
    if (!editing) return;
    // 被引用模板保存 → 风险确认（spec §9.5）；无引用 → 直接保存
    if ((editing.used_by?.length ?? 0) > 0) {
      setPendingSave({ id: editing.id, input, template: editing });
      return;
    }
    try {
      await updateTemplate(editing.id, input);
      setDialogOpen(false);
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  const confirmSave = async () => {
    if (!pendingSave) return;
    const { id, input } = pendingSave;
    setPendingSave(null);
    try {
      await updateTemplate(id, input);
      setDialogOpen(false);
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  const handleDelete = async () => {
    if (!pendingDelete) return;
    const target = pendingDelete;
    setPendingDelete(null);
    await deleteTemplate(target.id);
    const err = useTemplatesStore.getState().error;
    if (err) pushToast('err', err);
  };

  const referencedNames = (tpl: AgentTemplate) =>
    (tpl.used_by ?? []).map((p) => p.name).join('、');

  // 风险确认框文案（删除：被引用列项目名 / 无引用通用；保存：影响项目 + Agent 配置同步提示）
  const confirmMessage = pendingDelete
    ? (pendingDelete.used_by?.length ?? 0) > 0
      ? t('tpl.confirm.deleteReferenced', {
          n: pendingDelete.used_by?.length ?? 0,
          names: referencedNames(pendingDelete),
        })
      : t('tpl.confirm.delete', { name: pendingDelete.name })
    : pendingSave
      ? t('tpl.confirm.saveReferenced', {
          n: pendingSave.template.used_by?.length ?? 0,
          names: referencedNames(pendingSave.template),
        })
      : '';

  return (
    <section className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-[17px] font-semibold">{t('set.cat.templates')}</h2>
        <button
          type="button"
          data-testid="template-add-btn"
          className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          onClick={() => {
            setEditing(null);
            setDialogOpen(true);
          }}
        >
          {t('tpl.new')}
        </button>
      </div>

      <div data-testid="template-list" className="space-y-3">
        {loading && templates.length === 0 ? (
          <div className="text-[13px] text-ink-3">{t('common.loading')}</div>
        ) : (
          templates.map((tpl) => (
            <div
              key={tpl.id}
              data-testid={`template-card-${tpl.id}`}
              className="flex items-start justify-between gap-3 rounded-lg border border-line bg-surface p-4 shadow-card"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-[14px] font-medium text-ink">{tpl.name}</span>
                  {tpl.is_default && (
                    <span
                      data-testid={`template-default-badge-${tpl.id}`}
                      className="rounded-full border border-ok/30 bg-ok/10 px-2 py-0.5 text-[11px] text-ok"
                    >
                      {t('tpl.defaultBadge')}
                    </span>
                  )}
                </div>
                {tpl.description && (
                  <p className="mt-1 truncate text-[12px] text-ink-3">{tpl.description}</p>
                )}
                {(tpl.used_by?.length ?? 0) > 0 && (
                  <span
                    data-testid={`template-usedby-${tpl.id}`}
                    className="mt-2 inline-block rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-2"
                  >
                    {t('tpl.usedBy', { n: tpl.used_by?.length ?? 0 })}
                  </span>
                )}
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  type="button"
                  data-testid={`template-edit-${tpl.id}`}
                  aria-label={`${t('tpl.edit')} ${tpl.name}`}
                  className="rounded border border-line px-2.5 py-1 text-[12px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => {
                    setEditing(tpl);
                    setDialogOpen(true);
                  }}
                >
                  {t('tpl.edit')}
                </button>
                <button
                  type="button"
                  data-testid={`template-set-default-${tpl.id}`}
                  aria-label={`${t('tpl.setDefault')} ${tpl.name}`}
                  className="rounded border border-line px-2.5 py-1 text-[12px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => void setDefault(tpl.id)}
                >
                  {t('tpl.setDefault')}
                </button>
                <button
                  type="button"
                  data-testid={`template-delete-${tpl.id}`}
                  aria-label={`${t('tpl.delete')} ${tpl.name}`}
                  className="rounded border border-line px-2.5 py-1 text-[12px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => setPendingDelete(tpl)}
                >
                  {t('tpl.delete')}
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* 关闭即卸载：重开时以当前 editing 重新初始化表单（编辑模式回显） */}
      {dialogOpen && (
        <TemplateDialog
          open
          onOpenChange={setDialogOpen}
          editing={editing}
          onCreate={(input) => void handleCreate(input)}
          onUpdate={(input) => void handleUpdate(input)}
        />
      )}

      {(pendingDelete || pendingSave) && (
        <div
          role="presentation"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
          onClick={() => {
            setPendingDelete(null);
            setPendingSave(null);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t('tpl.confirm.title')}
            data-testid="template-confirm-dialog"
            className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="font-serif text-[18px] font-semibold">{t('tpl.confirm.title')}</h2>
            <p className="mt-3 text-[13px] text-ink-2">{confirmMessage}</p>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                data-testid="template-confirm-cancel"
                className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
                onClick={() => {
                  setPendingDelete(null);
                  setPendingSave(null);
                }}
              >
                {t('dlg.cancel')}
              </button>
              <button
                type="button"
                data-testid="template-confirm-ok"
                className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                onClick={() => {
                  if (pendingDelete) void handleDelete();
                  if (pendingSave) void confirmSave();
                }}
              >
                {t('tpl.confirm.ok')}
              </button>
            </div>
          </div>
        </div>
      )}
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
