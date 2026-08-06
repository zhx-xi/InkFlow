/**
 * 模型多选一次性添加弹窗（Issue #106 F3，spec §8.2③ L929）：
 * 选择目标 Provider → 逐行录入模型 ID / 类型（chat|embedding）/ 角色标记
 * → 保存时逐条 PATCH /api/v1/provider-configs/{id}（store.addModel 追加全量）。
 * 下一迭代的 Provider 模型拉取不在本章（任务书：不要求）。
 */
import { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';
import type { ProviderConfig, ProviderModel } from '../stores/models';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

interface ModelDraftRow {
  id: string;
  type: 'chat' | 'embedding';
  roles: string;
}

export interface AddModelDialogProps {
  open: boolean;
  providers: ProviderConfig[];
  onOpenChange: (open: boolean) => void;
  onAdd: (providerId: number, model: ProviderModel) => Promise<void>;
  onDone: () => void;
}

export function AddModelDialog({
  open,
  providers,
  onOpenChange,
  onAdd,
  onDone,
}: AddModelDialogProps) {
  const { t } = useI18n();
  const [providerId, setProviderId] = useState<number | null>(null);
  const [rows, setRows] = useState<ModelDraftRow[]>([]);
  const [saving, setSaving] = useState(false);

  // 打开时重置草稿：默认第一个 Provider + 一行空条目
  useEffect(() => {
    if (!open) return;
    setProviderId(providers[0]?.id ?? null);
    setRows([{ id: '', type: 'chat', roles: '' }]);
    setSaving(false);
  }, [open, providers]);

  if (!open) return null;

  // 首帧兜底：providerId 尚未被 effect 填充时直接用第一个 Provider，避免
  // Radix Select 由 uncontrolled 切换到 controlled 的告警
  const activeProviderId = providerId ?? providers[0]?.id ?? null;

  const updateRow = (index: number, patch: Partial<ModelDraftRow>) => {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const addRow = () => setRows((prev) => [...prev, { id: '', type: 'chat', roles: '' }]);

  const removeRow = (index: number) => setRows((prev) => prev.filter((_, i) => i !== index));

  const handleSave = async () => {
    if (saving || activeProviderId === null) return;
    const models = rows
      .map((row) => ({
        id: row.id.trim(),
        type: row.type,
        roles: row.roles
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
      }))
      .filter((model) => model.id !== '');
    if (models.length === 0) return;
    setSaving(true);
    try {
      for (const model of models) {
        await onAdd(activeProviderId, model);
      }
      onDone();
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={() => {
        if (!saving) onOpenChange(false);
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('m.addModel')}
        data-testid="add-model-dialog"
        className="w-[620px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">{t('m.addModel')}</h2>
        <div className="mt-4 space-y-3">
          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('m.providerSelect')}</span>
            <Select
              value={activeProviderId === null ? undefined : String(activeProviderId)}
              onValueChange={(v) => setProviderId(Number(v))}
            >
              <SelectTrigger aria-label={t('m.providerSelect')} className="w-full">
                <SelectValue placeholder={t('m.providerSelect')} />
              </SelectTrigger>
              <SelectContent>
                {providers.map((p) => (
                  <SelectItem key={p.id} value={String(p.id)}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>

          {rows.map((row, index) => (
            <div
              key={index}
              className="flex items-end gap-2 rounded-md border border-line p-2"
            >
              <label className="flex flex-1 flex-col gap-1.5 text-[13px]">
                <span>{t('m.modelId')}</span>
                <input
                  aria-label={`${t('m.modelId')} ${index + 1}`}
                  className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
                  value={row.id}
                  onChange={(e) => updateRow(index, { id: e.target.value })}
                  placeholder="gpt-4o-mini"
                />
              </label>
              <label className="flex w-[120px] flex-col gap-1.5 text-[13px]">
                <span>{t('m.table.type')}</span>
                <Select
                  value={row.type}
                  onValueChange={(v) => updateRow(index, { type: v as 'chat' | 'embedding' })}
                >
                  <SelectTrigger aria-label={`${t('m.table.type')} ${index + 1}`} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="chat">chat</SelectItem>
                    <SelectItem value="embedding">embedding</SelectItem>
                  </SelectContent>
                </Select>
              </label>
              <label className="flex flex-1 flex-col gap-1.5 text-[13px]">
                <span>{t('m.table.roles')}</span>
                <input
                  aria-label={`${t('m.table.roles')} ${index + 1}`}
                  className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
                  value={row.roles}
                  onChange={(e) => updateRow(index, { roles: e.target.value })}
                  placeholder="writing, audit"
                />
              </label>
              <button
                type="button"
                aria-label={`${t('m.delete')} ${index + 1}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => removeRow(index)}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          ))}

          <button
            type="button"
            className="flex items-center gap-1 rounded-md border border-line px-3 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={addRow}
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t('m.addRow')}
          </button>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            disabled={saving}
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:opacity-50"
            onClick={() => void handleSave()}
          >
            {t('ag.save')}
          </button>
        </div>
      </div>
    </div>
  );
}
