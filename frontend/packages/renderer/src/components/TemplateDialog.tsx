/**
 * Agent 模板编辑弹窗（Issue #107，spec §9.2.5 / §9.5 / M4）：
 * 受控弹窗，纯表单（不做 API 调用，保存走 onCreate/onUpdate 回调）。
 * 名称必填 / 描述 / 主模型 / 四角色行（模型下拉 + 温度滑杆 0-1.5 步进 0.1 + 启用开关）/
 * 默认温度 / 默认字数。模型选项 = useModelsStore 模型注册表。
 */
import { useEffect, useMemo, useState } from 'react';
import { useI18n } from '../i18n/useI18n';
import { useModelsStore } from '../stores/models';
import type { AgentTemplate, AgentTemplateInput, AgentTemplateRole } from '../stores/templates';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Slider } from './ui/slider';
import { Switch } from './ui/switch';

const ROLES = ['architect', 'writer', 'auditor', 'reviser'] as const;
type Role = (typeof ROLES)[number];

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
  const [name, setName] = useState(editing?.name ?? '');
  const [description, setDescription] = useState(editing?.description ?? '');
  const [mainModel, setMainModel] = useState(editing?.main_model ?? '');
  const [defaultTemp, setDefaultTemp] = useState(editing?.default_temperature ?? 0.7);
  const [defaultWords, setDefaultWords] = useState(editing?.default_words ?? 800000);
  const [roles, setRoles] = useState<Record<Role, AgentTemplateRole>>({
    architect: editing ? { ...editing.roles.architect } : { ...EMPTY_ROLE },
    writer: editing ? { ...editing.roles.writer } : { ...EMPTY_ROLE },
    auditor: editing ? { ...editing.roles.auditor } : { ...EMPTY_ROLE },
    reviser: editing ? { ...editing.roles.reviser } : { ...EMPTY_ROLE },
  });
  const [nameError, setNameError] = useState<string | null>(null);

  // 打开时同步编辑值（editing 变化重开弹窗场景）；挂载时拉取模型注册表（下拉选项源）
  useEffect(() => {
    if (!open) return;
    setName(editing?.name ?? '');
    setDescription(editing?.description ?? '');
    setMainModel(editing?.main_model ?? '');
    setDefaultTemp(editing?.default_temperature ?? 0.7);
    setDefaultWords(editing?.default_words ?? 800000);
    setRoles({
      architect: editing ? { ...editing.roles.architect } : { ...EMPTY_ROLE },
      writer: editing ? { ...editing.roles.writer } : { ...EMPTY_ROLE },
      auditor: editing ? { ...editing.roles.auditor } : { ...EMPTY_ROLE },
      reviser: editing ? { ...editing.roles.reviser } : { ...EMPTY_ROLE },
    });
    setNameError(null);
    void useModelsStore.getState().loadProviders();
  }, [open, editing]);

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

  const setRole = (role: Role, patch: Partial<AgentTemplateRole>) => {
    setRoles((prev) => ({ ...prev, [role]: { ...prev[role], ...patch } }));
  };

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
      roles: {
        architect: { ...roles.architect },
        writer: { ...roles.writer },
        auditor: { ...roles.auditor },
        reviser: { ...roles.reviser },
      },
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

          {ROLES.map((role) => {
            const row = roles[role];
            const disabled = !row.enabled;
            const sliderValue = row.temperature ?? defaultTemp;
            return (
              <div
                key={role}
                data-testid={`template-role-row-${role}`}
                className="rounded-md border border-line p-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium">{t(`m.role.${role}`)}</span>
                  <Switch
                    data-testid={`template-role-${role}-enabled`}
                    checked={row.enabled}
                    onCheckedChange={(checked) =>
                      // 关闭语义 = 该角色使用默认模型：model/temperature 清除覆盖（spec §9.2.5 评审建议 1）
                      checked
                        ? setRole(role, { enabled: true })
                        : setRole(role, { enabled: false, model: null, temperature: null })
                    }
                    aria-label={t(`m.role.${role}`)}
                  />
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
                    <span>{t(`tpl.roleModel.${role}`)}</span>
                    <Select
                      value={row.model ?? ''}
                      disabled={disabled}
                      onValueChange={(v) => setRole(role, { model: v })}
                    >
                      <SelectTrigger
                        aria-label={t(`tpl.roleModel.${role}`)}
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
                      <span>{t(`tpl.roleTemp.${role}`)}</span>
                      <span data-testid={`template-role-${role}-value`} className="font-mono text-ink">
                        {sliderValue.toFixed(1)}
                      </span>
                    </div>
                    <Slider
                      data-testid={`template-role-${role}-temp`}
                      aria-label={t(`tpl.roleTemp.${role}`)}
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
