/**
 * 模型多选一次性添加弹窗（Issue #106 F3，spec §8.2③ L929）：
 * 选择目标 Provider → 逐行录入模型 ID / 类型（chat|embedding）/ 角色标记
 * → 保存时逐条 PATCH /api/v1/provider-configs/{id}（store.addModel 追加全量）。
 * 下一迭代的 Provider 模型拉取不在本章（任务书：不要求）。
 */
import { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { apiFetch, errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import type { ProviderConfig, ProviderModel } from '../stores/models';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

interface ModelDraftRow {
  id: string;
  type: 'chat' | 'embedding';
  roles: string;
}

interface FetchModelsResponse {
  ok: boolean;
  models?: string[];
  message?: string;
}

/** #125 批量保存结果：逐行成功/失败计数 + errorMessage(err) 后的错误字符串数组 */
export interface AddModelsResult {
  succeeded: number;
  failed: number;
  errors: string[];
}

export interface AddModelDialogProps {
  open: boolean;
  providers: ProviderConfig[];
  onOpenChange: (open: boolean) => void;
  onAdd: (providerId: number, model: ProviderModel) => Promise<void>;
  onDone: (result: AddModelsResult) => void;
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
  const [candidates, setCandidates] = useState<string[]>([]);

  const fetchModels = async (provider: ProviderConfig) => {
    try {
      const res = await apiFetch<FetchModelsResponse>('/api/v1/provider-configs/models', {
        method: 'POST',
        body: {
          base_url: provider.base_url,
          ...(provider.name ? { provider: provider.name } : {}),
        },
      });
      setCandidates(res.ok ? (res.models ?? []) : []);
    } catch {
      // 拉取失败不崩溃：无候选列表，手动输入仍可用
      setCandidates([]);
    }
  };

  // 打开时重置草稿：默认第一个 Provider + 一行空条目
  useEffect(() => {
    if (!open) return;
    setProviderId(providers[0]?.id ?? null);
    setRows([{ id: '', type: 'chat', roles: '' }]);
    setSaving(false);
    setCandidates([]);
    const first = providers[0];
    if (first) void fetchModels(first);
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
      // #125 逐行 try/catch：失败行收集错误继续下一行，不中断（reject 不逸出）
      let succeeded = 0;
      const errors: string[] = [];
      for (const model of models) {
        try {
          await onAdd(activeProviderId, model);
          succeeded += 1;
        } catch (err) {
          errors.push(errorMessage(err));
        }
      }
      if (errors.length === 0) {
        onDone({ succeeded, failed: 0, errors: [] });
        onOpenChange(false);
      } else {
        // 有失败行：携带结果 + 弹窗不关闭 + 草稿保留（rows state 不清空，可修改重试）
        onDone({ succeeded, failed: errors.length, errors });
      }
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
              onValueChange={(v) => {
                const pid = Number(v);
                setProviderId(pid);
                const provider = providers.find((p) => p.id === pid);
                if (provider) void fetchModels(provider);
              }}
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
                {candidates.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {candidates
                      .filter(
                        (m) =>
                          row.id.trim() === '' ||
                          m.toLowerCase().includes(row.id.trim().toLowerCase()),
                      )
                      .map((m) => (
                        <button
                          key={m}
                          type="button"
                          className="rounded-md border border-line px-2.5 py-1 text-[12px] text-ink-2 transition duration-180 hover:bg-surface-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                          onClick={() => updateRow(index, { id: m })}
                        >
                          {m}
                        </button>
                      ))}
                  </div>
                )}
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
