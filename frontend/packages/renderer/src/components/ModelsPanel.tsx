/**
 * 模型管理面板（Issue #106，spec §8.2③ / §8.3 / §8.6 M2-M4b；#481 从独立页 /models 迁入设置页模型分类）：
 * Provider 列表（名称/模型数/key_saved 徽标）+ 添加弹窗 + 模型表。
 * #523：角色绑定 UI 已移除（模板已含角色组合+模型设置，功能重复）；store roleBinding 数据面保留（历史项目回退兼容）。
 */
import { useEffect, useMemo, useState } from 'react';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { AddModelDialog, type AddModelsResult } from './AddModelDialog';
import { ProviderDialog } from './ProviderDialog';
import { useI18n } from '../i18n/useI18n';
import type { ProviderConfig, ProviderModel } from '../stores/models';
import { useModelsStore } from '../stores/models';
import { useToastStore } from '../stores/toast';

export function ModelsPanel() {
  const { t } = useI18n();
  const providers = useModelsStore((s) => s.providers);
  const loading = useModelsStore((s) => s.loading);
  const loadProviders = useModelsStore((s) => s.loadProviders);
  const addModel = useModelsStore((s) => s.addModel);
  const deleteProvider = useModelsStore((s) => s.deleteProvider);
  const pushToast = useToastStore((s) => s.pushToast);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ProviderConfig | null>(null);
  const [addModelOpen, setAddModelOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<ProviderConfig | null>(null);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  /** 全量模型行（跨 provider 展开，供模型表渲染） */
  const allModels = useMemo(
    () =>
      providers.flatMap((p) =>
        p.models.map((m) => ({
          providerId: p.id,
          providerName: p.name,
          ...m,
        })),
      ),
    [providers],
  );

  const handleSaved = () => {
    // 注册表以后端为真源：保存成功后重新拉取
    void loadProviders();
  };

  const handleAddModel = async (providerId: number, model: ProviderModel) => {
    await addModel(providerId, model);
  };

  // #125：以 AddModelDialog 逐行结果为准（不再读 store.error 的「最后一次调用」）
  const handleModelsAdded = (result: AddModelsResult) => {
    if (result.failed > 0) {
      pushToast('err', t('m.modelsFailed', { n: result.failed, reason: result.errors[0] ?? '' }));
    } else {
      pushToast('ok', t('m.modelAdded'));
    }
  };

  const handleDelete = async () => {
    if (!pendingDelete) return;
    const target = pendingDelete;
    setPendingDelete(null);
    await deleteProvider(target.id);
    const err = useModelsStore.getState().error;
    if (err) pushToast('err', err);
    else pushToast('ok', t('m.deleteDone'));
  };

  return (
    <div data-testid="models-panel" className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-[17px] font-semibold">{t('m.title')}</h2>
        <button
          type="button"
          data-testid="add-provider-btn"
          className="flex items-center gap-1.5 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          onClick={() => {
            setEditing(null);
            setDialogOpen(true);
          }}
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          {t('m.addProvider')}
        </button>
      </div>

      <section
        data-testid="provider-list"
        className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3"
      >
        {loading && providers.length === 0 ? (
          <div className="text-[13px] text-ink-3">{t('common.loading')}</div>
        ) : (
          providers.map((p) => (
            <div
              key={p.id}
              data-testid={`provider-card-${p.id}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-line bg-surface p-4 shadow-card"
            >
              <div className="min-w-0">
                <div className="truncate text-[14px] font-medium text-ink">{p.name}</div>
                <div className="mt-1.5 flex items-center gap-2">
                  <span
                    data-testid={`provider-model-count-${p.id}`}
                    className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-2"
                  >
                    {t('m.modelCount', { n: p.models.length })}
                  </span>
                  <span
                    data-testid={`provider-key-badge-${p.id}`}
                    className={
                      p.key_saved
                        ? 'rounded-full border border-ok/30 bg-ok/10 px-2 py-0.5 text-[11px] text-ok'
                        : 'rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-3'
                    }
                  >
                    {p.key_saved ? t('m.keySaved') : t('m.keyMissing')}
                  </span>
                </div>
              </div>
              <button
                type="button"
                data-testid={`provider-edit-${p.id}`}
                aria-label={`${t('m.edit')} ${p.name}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => {
                  setEditing(p);
                  setDialogOpen(true);
                }}
              >
                <Pencil className="h-4 w-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                data-testid={`provider-delete-${p.id}`}
                aria-label={`${t('m.delete')} ${p.name}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => setPendingDelete(p)}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          ))
        )}
      </section>

      <section className="rounded-lg border border-line bg-surface p-5 shadow-card">
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-[17px] font-semibold">{t('m.modelTableTitle')}</h2>
          <button
            type="button"
            data-testid="add-model-btn"
            className="flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => setAddModelOpen(true)}
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t('m.addModel')}
          </button>
        </div>
        <table data-testid="model-table" className="mt-3 w-full text-left text-[13px]">
          <thead>
            <tr className="border-b border-line text-[12px] text-ink-3">
              <th className="py-2 pr-3 font-medium">{t('m.table.id')}</th>
              <th className="py-2 pr-3 font-medium">{t('m.table.type')}</th>
              <th className="py-2 pr-3 font-medium">{t('m.table.roles')}</th>
              <th className="py-2 pr-3 font-medium">{t('m.table.provider')}</th>
            </tr>
          </thead>
          <tbody>
            {allModels.map((m) => (
              <tr
                key={`${m.providerId}-${m.id}`}
                data-testid={`model-row-${m.id}`}
                className="border-b border-line last:border-0"
              >
                <td className="py-2 pr-3 font-mono text-[12px] text-ink">{m.id}</td>
                <td className="py-2 pr-3">
                  <span className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-2">
                    {m.type}
                  </span>
                </td>
                <td className="py-2 pr-3">
                  <div className="flex flex-wrap gap-1">
                    {m.roles.map((r) => (
                      <span
                        key={r}
                        className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-2"
                      >
                        {r}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="py-2 pr-3 text-ink-2">{m.providerName}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <ProviderDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editing={editing}
        onSaved={handleSaved}
      />

      <AddModelDialog
        open={addModelOpen}
        providers={providers}
        onOpenChange={setAddModelOpen}
        onAdd={handleAddModel}
        onDone={handleModelsAdded}
      />

      {pendingDelete && (
        <div
          role="presentation"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
          onClick={() => setPendingDelete(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t('m.deleteTitle')}
            className="w-[400px] rounded-lg border border-line bg-surface p-6 shadow-card"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="font-serif text-[18px] font-semibold">{t('m.deleteTitle')}</h2>
            <p className="mt-3 text-[13px] text-ink-2">
              {t('m.deleteConfirm', { name: pendingDelete.name, n: pendingDelete.models.length })}
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
                onClick={() => setPendingDelete(null)}
              >
                {t('dlg.cancel')}
              </button>
              <button
                type="button"
                className="rounded-md border border-err/40 px-4 py-1.5 text-sm text-err transition duration-180 hover:bg-err/10"
                onClick={() => void handleDelete()}
              >
                {t('m.delete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
