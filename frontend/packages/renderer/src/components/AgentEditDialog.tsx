/**
 * Agent 创建/编辑弹窗（Issue #260 F41，spec §5.5 / §8.3）：
 * 受控弹窗，纯表单——不做 API 调用，保存走 onCreate/onUpdate 回调。
 * 函数分组 checkbox（D2 拍板）+ skill 可搜索多选 + 模型/温度覆盖。
 * 数据源 = useAgentsStore.tools / .skills 订阅（父级 AgentList 挂载已加载）。
 */
import { useEffect, useMemo, useState } from 'react';
import { useI18n } from '../i18n/useI18n';
import { useAgentsStore, type AgentEntity, type AgentInput } from '../stores/agents';

export interface AgentEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing?: AgentEntity | null;
  onCreate: (input: AgentInput) => void;
  onUpdate: (input: AgentInput) => void;
}

/** 函数分组展示顺序 + i18n key（D2 拍板：writing/retrieval/audit/project 四组） */
const TOOL_GROUPS = [
  { group: 'writing', labelKey: 'set.agents.funcGroup.writing' },
  { group: 'retrieval', labelKey: 'set.agents.funcGroup.retrieval' },
  { group: 'audit', labelKey: 'set.agents.funcGroup.audit' },
  { group: 'project', labelKey: 'set.agents.funcGroup.project' },
] as const;

export function AgentEditDialog({
  open,
  onOpenChange,
  editing = null,
  onCreate,
  onUpdate,
}: AgentEditDialogProps) {
  const { t } = useI18n();
  const tools = useAgentsStore((s) => s.tools);
  const skills = useAgentsStore((s) => s.skills);
  // #838: 只渲染 allow_custom_agent=true 的工具 checkbox（is_core 核心工具自然不出现）
  const availableTools = tools.filter((tool) => tool.allow_custom_agent === true);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [icon, setIcon] = useState('');
  const [prompt, setPrompt] = useState('');
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [modelOverride, setModelOverride] = useState('');
  const [tempOverride, setTempOverride] = useState('');
  const [nameError, setNameError] = useState<string | null>(null);
  const [skillQuery, setSkillQuery] = useState('');

  // 打开时同步编辑值（editing 变化重开弹窗场景）；创建模式初始值全空
  useEffect(() => {
    if (!open) return;
    setName(editing?.name ?? '');
    setDescription(editing?.description ?? '');
    setIcon(editing?.icon ?? '');
    setPrompt(editing?.system_prompt ?? '');
    setSelectedTools(editing?.tool_ids ?? []);
    // skill_ids 后端 str 契约：勾选状态按 String(skill.id) 匹配
    setSelectedSkills((editing?.skill_ids ?? []).map(String));
    setModelOverride(editing?.model_override ?? '');
    setTempOverride(
      editing?.temperature_override === null || editing?.temperature_override === undefined
        ? ''
        : String(editing.temperature_override),
    );
    setNameError(null);
    setSkillQuery('');
  }, [open, editing]);

  // ESC 关闭：document 级监听；尊重已 preventDefault 的 Escape
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onOpenChange(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onOpenChange]);

  // skill 搜索过滤（按名称，大小写不敏感）
  const filteredSkills = useMemo(() => {
    const q = skillQuery.trim().toLowerCase();
    if (!q) return skills;
    return skills.filter((s) => s.name.toLowerCase().includes(q));
  }, [skills, skillQuery]);

  if (!open) return null;

  const toggleTool = (toolName: string) => {
    setSelectedTools((prev) =>
      prev.includes(toolName) ? prev.filter((x) => x !== toolName) : [...prev, toolName],
    );
  };

  const toggleSkill = (skillId: number) => {
    const key = String(skillId);
    setSelectedSkills((prev) =>
      prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key],
    );
  };

  const handleSave = () => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setNameError(t('set.agents.nameRequired'));
      return;
    }
    const trimmedModel = modelOverride.trim();
    const input: AgentInput = {
      name: trimmedName,
      description,
      icon,
      system_prompt: prompt,
      tool_ids: selectedTools,
      skill_ids: selectedSkills,
      model_override: trimmedModel === '' ? null : trimmedModel,
      temperature_override: tempOverride.trim() === '' ? null : Number(tempOverride),
    };
    if (editing) onUpdate(input);
    else onCreate(input);
  };

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={editing ? t('set.agents.editAgent') : t('set.agents.newAgent')}
        data-testid="agent-dialog"
        className="max-h-[85vh] w-[620px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">
          {editing ? t('set.agents.editAgent') : t('set.agents.newAgent')}
        </h2>
        <div className="mt-4 space-y-4">
          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('set.agents.name')}</span>
            <input
              data-testid="agent-name-input"
              aria-label={t('set.agents.name')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            {nameError && <p className="text-[12px] text-err">{nameError}</p>}
          </label>

          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('set.agents.description')}</span>
            <input
              data-testid="agent-desc-input"
              aria-label={t('set.agents.description')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('set.agents.icon')}</span>
            <input
              data-testid="agent-icon-input"
              aria-label={t('set.agents.icon')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('set.agents.prompt')}</span>
            <textarea
              data-testid="agent-prompt-input"
              aria-label={t('set.agents.prompt')}
              rows={3}
              className="w-full resize-y rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </label>

          {/* 函数分组 checkbox（D2 拍板：分组勾选，多选白名单；project 组本期空可不渲染） */}
          <div className="flex flex-col gap-3 text-[13px]">
            <span>{t('set.agents.tools')}</span>
            {TOOL_GROUPS.map(({ group, labelKey }) => {
              const groupTools = availableTools.filter((tool) => tool.group === group);
              if (groupTools.length === 0) return null;
              return (
                <div
                  key={group}
                  data-testid={`agent-tool-group-${group}`}
                  className="rounded-md border border-line p-3"
                >
                  <span className="text-[12px] font-medium text-ink-2">{t(labelKey)}</span>
                  <div className="mt-2 space-y-2">
                    {groupTools.map((tool) => (
                      <label key={tool.name} className="flex items-start gap-2 text-[13px]">
                        <input
                          type="checkbox"
                          data-testid={`agent-tool-${tool.name}`}
                          className="mt-0.5 accent-accent"
                          checked={selectedTools.includes(tool.name)}
                          onChange={() => toggleTool(tool.name)}
                        />
                        <span className="flex flex-col">
                          <span className="font-medium">{tool.name}</span>
                          <span className="text-[12px] text-ink-2">{tool.description}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          {/* skill 绑定（可搜索多选） */}
          <div className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('set.agents.skillsTitle')}</span>
            <input
              data-testid="agent-skill-search"
              aria-label={t('set.agents.searchSkills')}
              placeholder={t('set.agents.searchSkills')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={skillQuery}
              onChange={(e) => setSkillQuery(e.target.value)}
            />
            {filteredSkills.length === 0 ? (
              <p className="text-[12px] text-ink-3">{t('set.agents.noSkills')}</p>
            ) : (
              <div className="max-h-36 space-y-1.5 overflow-y-auto rounded-md border border-line p-3">
                {filteredSkills.map((skill) => (
                  <div
                    key={skill.id}
                    role="checkbox"
                    aria-checked={selectedSkills.includes(String(skill.id))}
                    data-testid={`agent-skill-${skill.id}`}
                    className="flex cursor-pointer items-center gap-2 text-[13px]"
                    onClick={() => toggleSkill(skill.id)}
                  >
                    <span
                      aria-hidden="true"
                      className="flex h-4 w-4 items-center justify-center rounded border border-line text-[11px]"
                    >
                      {selectedSkills.includes(String(skill.id)) ? '✓' : ''}
                    </span>
                    <span>{skill.name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('set.agents.modelOverride')}</span>
            <input
              data-testid="agent-model-input"
              aria-label={t('set.agents.modelOverride')}
              placeholder={t('set.agents.modelPlaceholder')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={modelOverride}
              onChange={(e) => setModelOverride(e.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('set.agents.tempOverride')}</span>
            <input
              type="number"
              min={0}
              max={2}
              step={0.1}
              data-testid="agent-temp-input"
              aria-label={t('set.agents.tempOverride')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={tempOverride}
              onChange={(e) => setTempOverride(e.target.value)}
            />
          </label>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="agent-dialog-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            data-testid="agent-dialog-save"
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={handleSave}
          >
            {t('ag.save')}
          </button>
        </div>
      </div>
    </div>
  );
}
