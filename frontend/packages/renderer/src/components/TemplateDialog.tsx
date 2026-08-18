/**
 * Agent 模板编辑弹窗（Issue #107，spec §9.2.5 / §9.5 / M4）：
 * 受控弹窗，纯表单（不做 API 调用，保存走 onCreate/onUpdate 回调）。
 * 名称必填 / 描述 / 主模型 / 四角色行（模型下拉 + 温度滑杆 0-1.5 步进 0.1 + 启用开关）/
 * 默认温度 / 默认字数。模型选项 = useModelsStore 模型注册表。
 */
import { useEffect, useMemo, useState } from 'react';
import { useI18n } from '../i18n/useI18n';
import { useAgentsStore } from '../stores/agents';
import { useModelsStore } from '../stores/models';
import type { AgentTemplate, AgentTemplateInput, AgentTemplateRole } from '../stores/templates';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Slider } from './ui/slider';
import { Switch } from './ui/switch';

/** v1.5 #484：内置 4 角色保留 i18n 文案（m.role.* / tpl.roleModel.* / tpl.roleTemp.*）；其余角色显示名 = agents 真源 name */
const BUILTIN_ROLE_KEYS = ['architect', 'writer', 'auditor', 'reviser'];

export interface TemplateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing?: AgentTemplate | null;
  onCreate: (input: AgentTemplateInput) => void;
  onUpdate: (input: AgentTemplateInput) => void;
}

const EMPTY_ROLE: AgentTemplateRole = { model: null, temperature: null, enabled: true };

/** 温度值归一化：浮点累加（0.7 + 0.1）按 step 0.1 取整，避免 0.8000000000000001 泄漏 */
function roundTemp(value: number): number {
  return Math.round(value * 10) / 10;
}

export function TemplateDialog({ open, onOpenChange, editing = null, onCreate, onUpdate }: TemplateDialogProps) {
  const { t } = useI18n();
  const providers = useModelsStore((s) => s.providers);
  // v1.5 #484（spec §5.7.2 派生规则 3）：角色编辑列表从 GET /api/v1/agents 真源派生；
  // agents 可能为空 → roleKeys 至少含 editing.roles 键（模板快照补充），UI 不崩
  const agents = useAgentsStore((s) => s.agents) ?? [];
  const [name, setName] = useState(editing?.name ?? '');
  const [description, setDescription] = useState(editing?.description ?? '');
  const [mainModel, setMainModel] = useState(editing?.main_model ?? '');
  const [defaultTemp, setDefaultTemp] = useState(editing?.default_temperature ?? 0.7);
  const [defaultWords, setDefaultWords] = useState(editing?.default_words ?? 800000);
  const [roles, setRoles] = useState<Record<string, AgentTemplateRole>>({});
  const [nameError, setNameError] = useState<string | null>(null);

  // v1.5 #484：角色键列表 = agents role_key 非空 → 键；editing.roles 键补充（快照保留，含无实体键）
  const roleKeys = [...new Set([
    ...agents.filter((a) => a.role_key).map((a) => a.role_key as string),
    ...Object.keys(editing?.roles ?? {}),
  ])];
  const roleKeyKey = roleKeys.join('\u0000');

  // 打开时同步编辑值（editing 变化重开弹窗场景）；挂载时拉取模型注册表 + agents（角色列表真源）
  useEffect(() => {
    if (!open) return;
    setName(editing?.name ?? '');
    setDescription(editing?.description ?? '');
    setMainModel(editing?.main_model ?? '');
    setDefaultTemp(editing?.default_temperature ?? 0.7);
    setDefaultWords(editing?.default_words ?? 800000);
    // 会话重置：roles 从 editing 快照重建（任意键，§5.7.5）；agents 派生键由下方合并效果补齐
    setRoles(() => {
      const next: Record<string, AgentTemplateRole> = {};
      for (const [key, value] of Object.entries(editing?.roles ?? {})) {
        next[key] = { ...value };
      }
      return next;
    });
    setNameError(null);
    void useModelsStore.getState().loadProviders();
    void useAgentsStore.getState().loadAgents();
  }, [open, editing]);

  // agents 异步加载完成后：为新增角色键补齐默认行（EMPTY_ROLE 浅拷贝），保留用户已编辑值
  // 依赖 roleKeyKey（roleKeys 的稳定序列化）避免数组引用变化触发重渲染
  useEffect(() => {
    if (!open) return;
    setRoles((prev) => {
      const next: Record<string, AgentTemplateRole> = { ...prev };
      for (const key of roleKeyKey.split('\u0000').filter(Boolean)) {
        if (!next[key]) {
          next[key] = editing?.roles?.[key] ? { ...editing.roles[key] } : { ...EMPTY_ROLE };
        }
      }
      return next;
    });
  }, [open, roleKeyKey, editing]);

  // ESC 关闭：document 级监听；尊重 Radix Select 已 preventDefault 的 Escape
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onOpenChange(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onOpenChange]);

  const modelOptions = useMemo(
    () => [...new Set(providers.flatMap((p) => p.models.map((m) => m.id)))],
    [providers],
  );

  if (!open) return null;

  const setRole = (role: string, patch: Partial<AgentTemplateRole>) => {
    setRoles((prev) => ({ ...prev, [role]: { ...prev[role], ...patch } }));
  };

  // 显示名：4 内置保留 i18n（零回归）；新角色/自定义/快照键 = agents 真源 name ?? 裸键
  const roleName = (key: string) => agents.find((a) => a.role_key === key)?.name ?? key;
  const isBuiltinRole = (key: string) => BUILTIN_ROLE_KEYS.includes(key);
  const displayNameOf = (key: string) => (isBuiltinRole(key) ? t(`m.role.${key}`) : roleName(key));
  const modelLabelOf = (key: string) =>
    isBuiltinRole(key) ? t(`tpl.roleModel.${key}`) : `${roleName(key)}模型`;
  const tempLabelOf = (key: string) =>
    isBuiltinRole(key) ? t(`tpl.roleTemp.${key}`) : `${roleName(key)}温度`;

  const handleSave = () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setNameError(t('tpl.nameRequired'));
      return;
    }
    const input: AgentTemplateInput = {
      name: trimmed,
      description,
      main_model: mainModel,
      default_temperature: defaultTemp,
      // v1.5 #484：payload roles = roles state 全量展开（Record 任意键，§5.7.5 数据契约）
      roles: Object.fromEntries(
        Object.entries(roles).map(([key, value]) => [key, { ...value }]),
      ),
      default_words: defaultWords,
    };
    if (editing) onUpdate(input);
    else onCreate(input);
  };

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={editing ? t('tpl.editTemplate') : t('tpl.addTemplate')}
        data-testid="template-dialog"
        className="max-h-[85vh] w-[600px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">
          {editing ? t('tpl.editTemplate') : t('tpl.addTemplate')}
        </h2>
        <div className="mt-4 space-y-4">
          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('tpl.name')}</span>
            <input
              data-testid="template-name-input"
              aria-label={t('tpl.name')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            {nameError && <p className="text-[12px] text-err">{nameError}</p>}
          </label>

          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('tpl.description')}</span>
            <input
              data-testid="template-description-input"
              aria-label={t('tpl.description')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>

          <div className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('tpl.mainModel')}</span>
            <Select value={mainModel} onValueChange={setMainModel}>
              <SelectTrigger
                aria-label={t('tpl.mainModel')}
                data-testid="template-main-model"
                className="w-full"
              >
                <SelectValue placeholder="—" />
              </SelectTrigger>
              <SelectContent>
                {modelOptions.map((id) => (
                  <SelectItem key={id} value={id}>
                    {id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {roleKeys.map((role) => {
            const row = roles[role] ?? (editing?.roles?.[role] ? { ...editing.roles[role] } : { ...EMPTY_ROLE });
            const disabled = !row.enabled;
            const sliderValue = row.temperature ?? defaultTemp;
            const displayName = displayNameOf(role);
            const modelLabel = modelLabelOf(role);
            const tempLabel = tempLabelOf(role);
            return (
              <div
                key={role}
                data-testid={`template-role-row-${role}`}
                className="rounded-md border border-line p-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium">{displayName}</span>
                  <Switch
                    data-testid={`template-role-${role}-enabled`}
                    checked={row.enabled}
                    onCheckedChange={(checked) =>
                      // 关闭语义 = 该角色使用默认模型：model/temperature 清除覆盖（spec §9.2.5 评审建议 1）
                      checked
                        ? setRole(role, { enabled: true })
                        : setRole(role, { enabled: false, model: null, temperature: null })
                    }
                    aria-label={displayName}
                  />
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
                    <span>{modelLabel}</span>
                    <Select
                      value={row.model ?? ''}
                      disabled={disabled}
                      onValueChange={(v) => setRole(role, { model: v })}
                    >
                      <SelectTrigger
                        aria-label={modelLabel}
                        data-testid={`template-role-${role}-model`}
                        className="w-full"
                        disabled={disabled}
                      >
                        <SelectValue placeholder="—" />
                      </SelectTrigger>
                      <SelectContent>
                        {modelOptions.map((id) => (
                          <SelectItem key={id} value={id}>
                            {id}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
                    <div className="flex items-center justify-between">
                      <span>{tempLabel}</span>
                      <span data-testid={`template-role-${role}-value`} className="font-mono text-ink">
                        {sliderValue.toFixed(1)}
                      </span>
                    </div>
                    <Slider
                      data-testid={`template-role-${role}-temp`}
                      aria-label={tempLabel}
                      min={0}
                      max={1.5}
                      step={0.1}
                      value={[sliderValue]}
                      disabled={disabled}
                      onValueChange={([v]) => setRole(role, { temperature: roundTemp(v) })}
                    />
                  </div>
                </div>
                {disabled && (
                  <p className="mt-2 text-[12px] text-ink-3">{t('tpl.roleDisabledNote')}</p>
                )}
              </div>
            );
          })}

          <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
            <div className="flex items-center justify-between">
              <span>{t('tpl.defaultTemp')}</span>
              <span data-testid="template-default-temp-value" className="font-mono text-ink">
                {defaultTemp.toFixed(1)}
              </span>
            </div>
            <Slider
              data-testid="template-default-temp"
              aria-label={t('tpl.defaultTemp')}
              min={0}
              max={1.5}
              step={0.1}
              value={[defaultTemp]}
              onValueChange={([v]) => setDefaultTemp(roundTemp(v))}
            />
          </div>

          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('tpl.defaultWords')}</span>
            <input
              type="number"
              data-testid="template-default-words"
              aria-label={t('tpl.defaultWords')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={defaultWords}
              onChange={(e) => setDefaultWords(Number(e.target.value))}
            />
          </label>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="template-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            data-testid="template-save"
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
