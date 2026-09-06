/**
 * Agent 创建/编辑弹窗（Issue #260 F41，spec §5.5 / §8.3）：
 * 受控弹窗，纯表单——不做 API 调用，保存走 onCreate/onUpdate 回调。
 * 工具授权 = scope 矩阵（#957 F58：8 域 × read/write/delete）+ skill 可搜索多选 + 模型/温度覆盖。
 * 数据源 = useAgentsStore.tools / .skills 订阅（父级 AgentList 挂载已加载）。
 */
import { useEffect, useMemo, useState } from 'react';
import { useI18n } from '../i18n/useI18n';
import { useAgentsStore, type AgentEntity, type AgentInput, type GrantEntry, type ToolDomain, type ToolOp } from '../stores/agents';
import { useTScope } from '../stores/i18n';

export interface AgentEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing?: AgentEntity | null;
  onCreate: (input: AgentInput) => void;
  onUpdate: (input: AgentInput) => void;
}

/** #957 F58：矩阵行 = 固定 8 域常量序（spec §2.1 枚举序，非 catalog 派生） */
const DOMAINS: ToolDomain[] = [
  'outline',
  'character',
  'world',
  'timeline',
  'foreshadowing',
  'memory',
  'writing',
  'agent_chain',
];

/** 矩阵列 = read/write/delete（保存 payload 的 ops 展开序） */
const OPS: ToolOp[] = ['read', 'write', 'delete'];

export function AgentEditDialog({
  open,
  onOpenChange,
  editing = null,
  onCreate,
  onUpdate,
}: AgentEditDialogProps) {
  const { t } = useI18n();
  const tScope = useTScope();
  const tools = useAgentsStore((s) => s.tools);
  const skills = useAgentsStore((s) => s.skills);
  // #957 F58：格子可用性 = catalog 按 (domain,op) 过滤（is_core 不进目录，无需再滤 allow_custom_agent）
  const cellTools = (domain: ToolDomain, op: ToolOp): typeof tools =>
    tools.filter((tool) => tool.domain === domain && tool.op === op);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [icon, setIcon] = useState('');
  const [prompt, setPrompt] = useState('');
  // 授权状态 = GrantEntry[]（编辑回显 editing.grants ?? []；前端零 tool_ids 推断）
  const [grants, setGrants] = useState<GrantEntry[]>([]);
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
    setGrants(editing?.grants ?? []);
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

  /** 当前 grants 中是否含 (domain, op) */
  const hasGrant = (domain: ToolDomain, op: ToolOp): boolean =>
    (grants.find((g) => g.domain === domain)?.ops ?? []).includes(op);

  /** 格子点击切换授权；域内 ops 空时整条 domain 移除 */
  const toggleGrant = (domain: ToolDomain, op: ToolOp) => {
    setGrants((prev) => {
      const entry = prev.find((g) => g.domain === domain);
      const ops = entry ? [...entry.ops] : [];
      if (ops.includes(op)) {
        const next = ops.filter((x) => x !== op);
        return next.length === 0
          ? prev.filter((g) => g.domain !== domain)
          : prev.map((g) => (g.domain === domain ? { domain, ops: next } : g));
      }
      return entry
        ? prev.map((g) => (g.domain === domain ? { domain, ops: [...g.ops, op] } : g))
        : [...prev, { domain, ops: [op] }];
    });
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
    // 保存 payload：域按 DOMAINS 行序展开，ops 按 read→write→delete；空域剔除；无 tool_ids 键
    const grantsPayload: GrantEntry[] = DOMAINS.flatMap((domain) => {
      const ops = OPS.filter((op) => hasGrant(domain, op));
      return ops.length === 0 ? [] : [{ domain, ops }];
    });
    const input: AgentInput = {
      name: trimmedName,
      description,
      icon,
      system_prompt: prompt,
      grants: grantsPayload,
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

          {/* #957 F58：scope 矩阵（8 域 × read/write/delete；无工具格 disabled 但恒渲染） */}
          <div className="flex flex-col gap-2 text-[13px]">
            <span>{t('set.agents.tools')}</span>
            <div data-testid="agent-scope-matrix" className="rounded-md border border-line p-3">
              <div className="grid grid-cols-[minmax(0,1fr)_repeat(3,56px)] items-center gap-x-2 text-[12px]">
                <span />
                {OPS.map((op) => (
                  <span
                    key={op}
                    data-testid={`agent-scope-head-${op}`}
                    className="text-center font-medium text-ink-2"
                  >
                    {tScope(`agent.scope.${op}`)}
                  </span>
                ))}
                <span />
                <span />
                <span />
                <span
                  data-testid="agent-scope-delete-help"
                  title={tScope('agent.scope.delete.tooltip')}
                  className="text-[11px] text-ink-3"
                >
                  {tScope('agent.scope.delete.tooltip')}
                </span>
              </div>
              {DOMAINS.map((domain) => (
                <div
                  key={domain}
                  data-testid={`agent-scope-row-${domain}`}
                  className="mt-1.5 grid grid-cols-[minmax(0,1fr)_repeat(3,56px)] items-center gap-x-2 text-[12px]"
                >
                  <span>{tScope(`agent.scope.domain.${domain}`)}</span>
                  {OPS.map((op) => {
                    const enabled = cellTools(domain, op).length > 0;
                    const checked = hasGrant(domain, op);
                    return (
                      <label
                        key={op}
                        data-testid={`agent-scope-cell-${domain}-${op}`}
                        className="flex cursor-pointer items-center justify-center"
                      >
                        <input
                          type="checkbox"
                          className="h-3.5 w-3.5 accent-accent"
                          disabled={!enabled}
                          checked={checked}
                          onChange={() => toggleGrant(domain, op)}
                        />
                      </label>
                    );
                  })}
                </div>
              ))}
            </div>
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
