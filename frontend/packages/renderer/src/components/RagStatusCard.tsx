/**
 * #276 RAG 向量检索状态卡（#481 从 settings.tsx ModelsPanel 迁出为独立组件）：
 * 挂载于设置页模型分类，展示当前 embedding 模型 + 匹配状态，支持确认后全量重建。
 */
import { useEffect, useMemo, useState } from 'react';
import { fetchVectorStatus, postVectorReindex, putEmbeddingModel, type VectorStatusDto } from '../api/vector';
import { useI18n } from '../i18n/useI18n';
import { useModelsStore } from '../stores/models';
import { useProjectStore } from '../stores/project';
import { useToastStore } from '../stores/toast';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

export function RagStatusCard() {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const [status, setStatus] = useState<VectorStatusDto | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  // #525：embedding 模型切换保存中（防并发 PUT）
  const [saving, setSaving] = useState(false);
  const providers = useModelsStore((s) => s.providers);

  // #276：挂载 / 切换项目 → 查询向量库状态；内核未就绪等失败静默（不炸 UI）
  useEffect(() => {
    if (!currentProjectId) return;
    let cancelled = false;
    setStatus(null);
    void (async () => {
      try {
        const data = await fetchVectorStatus(currentProjectId);
        if (!cancelled) setStatus(data ?? null);
      } catch {
        // 内核未就绪等失败静默（不炸 UI）
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentProjectId]);

  /** #276：reason 文案映射（unknown / model_changed / chunking_changed / schema_old） */
  const reasonText = (reason: string | null): string => {
    switch (reason) {
      case 'model_changed':
        return t('set.rag.reason.modelChanged');
      case 'chunking_changed':
        return t('set.rag.reason.chunkingChanged');
      case 'schema_old':
        return t('set.rag.reason.schemaOld');
      case 'unknown':
        return t('set.rag.reason.unknown');
      default:
        return '';
    }
  };

  /** #525：注册表 embedding 模型扁平化选项（value/label = provider/model） */
  const embeddingOptions = useMemo(
    () =>
      providers.flatMap((p) =>
        p.models
          .filter((m) => m.type === 'embedding')
          .map((m) => ({ value: `${p.name}/${m.id}`, label: `${p.name}/${m.id}` })),
      ),
    [providers],
  );

  /** #525：当前生效 embedding 模型（provider/model；未配置 → undefined） */
  const currentEmbedding = status?.configured_fp
    ? `${status.configured_fp.embedding.provider}/${status.configured_fp.embedding.model_id}`
    : undefined;

  /** #525：切换激活 embedding 模型 → PUT 全局设置 → 刷新向量状态 + 注册表 */
  const handleEmbeddingChange = async (value: string) => {
    const [provider, ...rest] = value.split('/');
    const modelId = rest.join('/');
    if (!provider || !modelId || saving) return;
    setSaving(true);
    try {
      await putEmbeddingModel(provider, modelId);
      const data = await fetchVectorStatus(currentProjectId!);
      setStatus(data ?? null);
      void useModelsStore.getState().loadProviders();
    } catch {
      pushToast('err', t('toast.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  /** #276：确认 → 全量重建 → 刷新状态；失败 → err toast */
  const handleReindex = async () => {
    if (!currentProjectId || reindexing) return;
    setReindexing(true);
    try {
      await postVectorReindex(currentProjectId);
      const data = await fetchVectorStatus(currentProjectId);
      setStatus(data ?? null);
    } catch {
      pushToast('err', t('toast.saveFailed'));
    } finally {
      setReindexing(false);
      setConfirming(false);
    }
  };

  return (
    <section className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <h2 className="font-serif text-[17px] font-semibold">{t('set.rag.title')}</h2>

      {status && (
        <div
          data-testid="rag-status-card"
          className="mt-5 space-y-3 rounded-lg border border-line bg-surface-2 p-4"
        >
          <div className="flex items-center gap-2 text-[12px] text-ink-2">
            <span>{t('set.rag.model')}</span>
            <span data-testid="rag-model-name" className="font-medium text-ink">
              {status.configured_fp?.embedding.model_id ?? '—'}
            </span>
          </div>

          {/* #525：切换激活 embedding 模型（无 embedding 模型 → 不渲染 Select） */}
          {embeddingOptions.length > 0 && (
            <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
              <span>{t('set.rag.selectModel')}</span>
              <Select
                value={currentEmbedding}
                onValueChange={(v) => void handleEmbeddingChange(v)}
              >
                <SelectTrigger
                  data-testid="rag-embedding-select"
                  aria-label={t('set.rag.selectModel')}
                  className="w-56"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {embeddingOptions.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {status.reason === 'no_embedding' && (
            <div data-testid="rag-no-embedding" className="text-[12px] text-ink-3">
              {t('set.rag.noEmbedding')}
            </div>
          )}

          {!status.stale && status.reason !== 'no_embedding' && status.configured_fp && (
            <div className="text-[12px] text-ok">{t('set.rag.fresh')}</div>
          )}

          {status.stale && (
            <>
              <div
                data-testid="rag-stale-banner"
                className="rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-[12px] text-warn"
              >
                {t('set.rag.stale')}
                {reasonText(status.reason) ? `（${reasonText(status.reason)}）` : ''}
              </div>
              <button
                type="button"
                data-testid="rag-reindex-btn"
                disabled={reindexing}
                className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-60"
                onClick={() => setConfirming(true)}
              >
                {t('set.rag.reindex')}
              </button>
            </>
          )}
        </div>
      )}

      {confirming && status && (
        <div
          role="presentation"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
          onClick={() => setConfirming(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t('set.rag.title')}
            data-testid="rag-confirm-dialog"
            className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="font-serif text-[18px] font-semibold">{t('set.rag.title')}</h2>
            <p className="mt-3 text-[13px] text-ink-2">
              {status.dimension_mismatch ? t('set.rag.confirmDestructive') : t('set.rag.confirm')}
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
                onClick={() => setConfirming(false)}
              >
                {t('dlg.cancel')}
              </button>
              <button
                type="button"
                data-testid="rag-confirm-ok"
                className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                onClick={() => void handleReindex()}
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
