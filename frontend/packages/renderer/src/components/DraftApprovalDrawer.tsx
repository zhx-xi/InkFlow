/**
 * #976 草稿审批弹层（契约 §3.3：镜像 ConfirmDialog 遮罩/dialog 语义 + 确认闭环）。
 * - open 变化 → listDrafts(projectId, 'draft') 载入待审批草稿；
 * - 行内确认钮 → confirmDraft API → 成功 toast + onClose + 树/草稿双轨重拉；
 *   失败 → 框内 drafts-drawer-error 透传错误文案（409 等）；
 * - Esc / 遮罩点击 = onClose。
 */
import { useEffect, useState, type JSX } from 'react';
import { Check, X } from 'lucide-react';
import { confirmDraft, listDrafts, type DraftDto } from '../api/drafts';
import { errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
import { useToastStore } from '../stores/toast';

export interface DraftApprovalDrawerProps {
  open: boolean;
  onClose: () => void;
}

/** 正文超过 60 字符 → 收起态截断 + 「展开看全文/收起」切换（镜像 DraftApprovalPanel #749） */
const PREVIEW_LIMIT = 60;

export function DraftApprovalDrawer({ open, onClose }: DraftApprovalDrawerProps): JSX.Element | null {
  const { t } = useI18n();
  const projectId = useProjectStore((s) => s.currentProjectId);
  const [items, setItems] = useState<DraftDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  // open/projectId 变化 → 重载列表（关闭即静默；旧请求经 cancelled 丢弃）
  useEffect(() => {
    if (!open) return;
    setError(null);
    setExpandedId(null);
    if (!projectId) {
      setItems([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const result = await listDrafts(projectId, 'draft');
        if (!cancelled) setItems(result.items);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, projectId]);

  // Esc 关闭（document 级监听，尊重已 preventDefault 的 Escape——镜像 ConfirmDialog）
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  const handleConfirm = async (draft: DraftDto): Promise<void> => {
    setError(null);
    setConfirmingId(draft.id);
    try {
      await confirmDraft(draft.id);
      useToastStore.getState().pushToast('ok', t('write.drafts.confirmDone'));
      // 确认可能自动建章/改绑 → 卷章树 + 草稿双轨重拉（store 内部链式 loadPendingDrafts）
      if (projectId) void useChapterStore.getState().loadChapterTree(projectId);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setConfirmingId(null);
    }
  };

  if (!open) return null;

  return (
    <div
      role="presentation"
      data-testid="drafts-overlay"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('write.drafts.title')}
        data-testid="drafts-drawer"
        className="flex max-h-[78vh] w-[560px] flex-col rounded-lg border border-line bg-surface shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-line px-5 py-3">
          <h2 className="font-serif text-[16px] font-semibold">{t('write.drafts.title')}</h2>
          <button
            type="button"
            aria-label={t('dlg.cancel')}
            className="rounded p-1 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={onClose}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
          {loading && items.length === 0 ? (
            <div
              data-testid="drafts-drawer-loading"
              className="rounded-md border border-line bg-surface-2 p-3 text-[12px] leading-relaxed text-ink-3"
            >
              {t('write.drafts.loading')}
            </div>
          ) : error !== null && items.length === 0 ? (
            <div
              data-testid="drafts-drawer-error"
              className="rounded-md border border-err/30 bg-err/5 p-3 text-[12px] leading-relaxed text-err"
            >
              {t('write.drafts.error')}: {error}
            </div>
          ) : items.length === 0 && !loading ? (
            <div
              data-testid="drafts-drawer-empty"
              className="rounded-md border border-line bg-surface-2 p-3 text-[12px] leading-relaxed text-ink-3"
            >
              {t('write.drafts.empty')}
            </div>
          ) : (
            items.map((draft) => {
              const isLong = draft.content.length > PREVIEW_LIMIT;
              const expanded = expandedId === draft.id;
              const shown = isLong && !expanded
                ? `${draft.content.slice(0, PREVIEW_LIMIT)}…`
                : draft.content;
              return (
                <section
                  key={draft.id}
                  data-testid={`drafts-drawer-item-${draft.id}`}
                  className="rounded-md border border-line bg-surface-2 p-3"
                >
                  <div className="text-[13px] font-medium text-ink" title={draft.summary}>
                    {draft.summary}
                  </div>
                  <div className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed text-ink-2">
                    {shown}
                  </div>
                  {isLong && (
                    <button
                      type="button"
                      className="mt-1 rounded border border-line px-2 py-0.5 text-[12px] text-ink-3 transition hover:bg-surface-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                      onClick={() => setExpandedId((cur) => (cur === draft.id ? null : draft.id))}
                    >
                      {expanded ? t('write.drafts.collapse') : t('write.drafts.expand')}
                    </button>
                  )}
                  <div className="mt-3 flex items-center justify-end gap-2">
                    <button
                      type="button"
                      className="rounded-md border border-line px-3 py-1 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                      onClick={onClose}
                    >
                      {t('dlg.cancel')}
                    </button>
                    <button
                      type="button"
                      data-testid={`drafts-drawer-confirm-${draft.id}`}
                      disabled={confirmingId === draft.id}
                      className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:opacity-40"
                      onClick={() => void handleConfirm(draft)}
                    >
                      <Check className="h-3.5 w-3.5" aria-hidden="true" />
                      {t('write.drafts.confirm')}
                    </button>
                  </div>
                </section>
              );
            })
          )}
          {error !== null && items.length > 0 && (
            <p
              data-testid="drafts-drawer-error"
              className="rounded-md border border-err/30 bg-err/5 px-3 py-2 text-[12px] leading-relaxed text-err"
            >
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
