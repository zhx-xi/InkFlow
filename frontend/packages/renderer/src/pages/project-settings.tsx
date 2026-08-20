/** 项目聚合设置页（Issue #482，D4 拍板）：聚合项目级 config 五区块——模型绑定 + Agent 模板 + Agent 链 + 字数 + 世界观；
 *  #523：Agent 模板选择保存 config.template_id（str），模板已含角色组合+模型设置；保存统一走
 *  useAgentStore.saveConfig（PATCH /api/v1/projects/{id} body { config: 全量 }） */
import { useEffect, useRef, useState } from 'react';
import { AgentChainCard } from '../components/AgentChainCard';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Switch } from '../components/ui/switch';
import { useI18n } from '../i18n/useI18n';
import { useAgentStore } from '../stores/agent';
import { selectChatModelOptions, useModelsStore } from '../stores/models';
import { AGENT_DEFAULT_SENTINEL, useProjectStore } from '../stores/project';
import { useTemplatesStore } from '../stores/templates';

export function ProjectSettingsPage() {
  const { t } = useI18n();
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const project = useProjectStore((s) => s.projects.find((p) => p.id === s.currentProjectId));
  const config = useAgentStore((s) => s.config);
  const setConfig = useAgentStore((s) => s.setConfig);
  // #523：Agent 模板列表（本区块数据源；挂载即加载，Select 选项随 store 响应式更新）
  const templates = useTemplatesStore((s) => s.templates);
  // F42 #268：默认模型/世界观模型选项 = provider-configs chat 模型扁平化（AgentChainCard 挂载会加载，直接订阅）
  const chatModelOptions = selectChatModelOptions(useModelsStore((s) => s.providers));
  // 字数输入：本地受控草稿 + dirty 标记（blur 才 setConfig + persist；镜像 GeneralPanel valueRef/dirty 语义）
  const [wordsDraft, setWordsDraft] = useState(() => String(project?.config.default_words ?? 800000));
  const wordsDirtyRef = useRef(false);

  // 播种守卫（镜像 settings.tsx AgentPanel）：agent store config 不含 agent_*/model 键时按项目 config 播种
  useEffect(() => {
    const c = useAgentStore.getState().config;
    if (Object.keys(c).some((k) => k.startsWith('agent_') || k === 'model')) return;
    const state = useProjectStore.getState();
    const p = state.projects.find((x) => x.id === state.currentProjectId);
    if (p) useAgentStore.getState().loadFromProject(p.config);
  }, [currentProjectId]);

  // #523：Agent 模板数据源（挂载即加载——与 AgentChainCard 同款，本区块生命周期内确保模板列表可用）
  useEffect(() => {
    void useTemplatesStore.getState().loadTemplates();
  }, []);

  // 切项目重读字数草稿（跨项目残留丢弃 = 上下文切换，与 GeneralPanel 同语义）
  useEffect(() => {
    const state = useProjectStore.getState();
    const p = state.projects.find((x) => x.id === state.currentProjectId);
    setWordsDraft(String(p?.config.default_words ?? 800000));
    wordsDirtyRef.current = false;
  }, [currentProjectId]);

  // 保存 = saveConfig(currentProjectId)（store 内部 PATCH 全量 config；无当前项目时静默跳过）
  const persist = () => {
    const id = useProjectStore.getState().currentProjectId;
    if (!id) return;
    void useAgentStore.getState().saveConfig(id);
  };

  if (!currentProjectId || !project) {
    return (
      <div data-testid="project-settings-page" className="mx-auto max-w-[1080px] px-12 py-10">
        <div
          data-testid="ps-empty"
          className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-16 text-center"
        >
          <p className="font-serif text-[17px] font-semibold text-ink">{t('ps.empty')}</p>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="project-settings-page" className="mx-auto max-w-[1080px] px-12 py-10">
      <h1 className="font-serif text-[26px] font-semibold">{project.name}</h1>
      <div className="mt-6 space-y-5">
        {/* ① 模型绑定：默认模型 Select（provider/model 复合键） */}
        <section className="rounded-lg border border-line bg-surface p-6 shadow-card">
          <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
            <span>{t('ag.defaultModel')}</span>
            <Select
              value={config.model ?? undefined}
              onValueChange={(v) => {
                setConfig({ model: v });
                persist();
              }}
            >
              <SelectTrigger data-testid="ps-model-select" aria-label={t('ag.defaultModel')} className="w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {chatModelOptions.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </section>

        {/* Agent 模板（#523）：builtin 三件 + 自定义模板；保存 config.template_id（str） */}
        <section data-testid="ps-template-section" className="rounded-lg border border-line bg-surface p-6 shadow-card">
          <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
            <span>{t('ag.templateTitle')}</span>
            <Select
              value={config.template_id == null ? '' : String(config.template_id)}
              onValueChange={(v) => {
                // '' = 不使用模板（解除引用 → null）；否则保存 str（builtin 键或 String(自定义 id)）
                setConfig({ template_id: v === '' ? null : v });
                persist();
              }}
            >
              <SelectTrigger data-testid="ps-template-select" aria-label={t('ag.templateTitle')} className="w-72">
                <SelectValue placeholder={t('ag.templatePlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">{t('ag.templateNone')}</SelectItem>
                <SelectItem value="builtin:write_auto">{t('ag.tplWriteAuto')}</SelectItem>
                <SelectItem value="builtin:write_continue">{t('ag.tplWriteContinue')}</SelectItem>
                <SelectItem value="builtin:chat">{t('ag.tplChat')}</SelectItem>
                {templates.map((tpl) => (
                  <SelectItem key={tpl.id} value={String(tpl.id)}>{tpl.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </section>

        {/* ② Agent 链：复用 AgentChainCard（开关/排序变更即 persist） */}
        <AgentChainCard onConfigChange={persist} />

        {/* ③ 字数：新章节默认字数，blur 保存 */}
        <section className="rounded-lg border border-line bg-surface p-6 shadow-card">
          <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
            <span>{t('set.defaultWords')}</span>
            <input
              type="number"
              data-testid="ps-words-input"
              aria-label={t('set.defaultWords')}
              className="w-56 rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
              value={wordsDraft}
              onChange={(e) => {
                setWordsDraft(e.target.value);
                wordsDirtyRef.current = true;
              }}
              onBlur={() => {
                if (!wordsDirtyRef.current) return;
                wordsDirtyRef.current = false;
                const n = Number(wordsDraft);
                if (wordsDraft === '' || !Number.isFinite(n)) return;
                setConfig({ default_words: n });
                persist();
              }}
            />
          </div>
        </section>

        {/* ④ 世界观：Switch（null=关闭 / sentinel=跟随默认）+ 开启时模型 Select */}
        <section className="rounded-lg border border-line bg-surface p-6 shadow-card">
          <div className="flex items-center justify-between gap-3">
            <div className="flex flex-col gap-1">
              <span className="text-[12px] text-ink-2">{t('ps.worldview')}</span>
            </div>
            <Switch
              data-testid="ps-worldview-switch"
              checked={typeof config.agent_worldview === 'string'}
              onCheckedChange={(checked) => {
                // #225 三态：关闭 → null；开启 → sentinel 跟随默认
                setConfig({ agent_worldview: checked ? AGENT_DEFAULT_SENTINEL : null });
                persist();
              }}
              aria-label={t('ps.worldview')}
            />
          </div>
          {typeof config.agent_worldview === 'string' && (
            <div className="mt-4 flex flex-col gap-1.5 text-[12px] text-ink-2">
              <Select
                value={config.agent_worldview ?? AGENT_DEFAULT_SENTINEL}
                onValueChange={(v) => {
                  setConfig({ agent_worldview: v });
                  persist();
                }}
              >
                <SelectTrigger data-testid="ps-worldview-model" aria-label={t('ag.defaultModel')} className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={AGENT_DEFAULT_SENTINEL}>{t('ag.followDefault')}</SelectItem>
                  {chatModelOptions.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
