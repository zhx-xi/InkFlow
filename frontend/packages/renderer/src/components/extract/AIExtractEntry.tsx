import { useEffect, useState } from 'react';
import { History } from 'lucide-react';
import { apiFetch, errorMessage } from '../../api/client';
import { EXTRACT_RUN_TYPE_LABELS } from '../../i18n/extract-keys';
import { useI18n } from '../../i18n/useI18n';
import { useExtractStore, type PendingBatch } from '../../stores/extract';
import { useProjectStore } from '../../stores/project';
import { useToastStore } from '../../stores/toast';
import type { ExtractKind } from './AIExtractDialog';

/** #1566：资料库分类 → 弹框默认提取类型（未登记分类 = 无来源页上下文 → 回落 character） */
const KIND_BY_CAT: Record<string, ExtractKind> = {
  characters: 'character',
  world: 'world',
  timeline: 'timeline',
  foreshadow: 'foreshadowing',
  knowledge: 'knowledgeGraph',
};

const ENTRY_BTN_CLS =
  'rounded-md border border-line px-4 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60';

/** #652：「AI 提取」入口（设定库工具栏按钮，自包含）。
 *
 *  #1582：**对话框不再挂在这里**（原宿主页局部 `useState` → 宿主重挂载即丢会话）。
 *  按钮只把 `openDialog()` 打进全局 store，对话框由 App 层常驻组件渲染。
 *  #1566：cat = 当前资料库分类 → 弹框默认类型随来源页（未登记分类回落 character）。
 */
export function AIExtractEntry({ cat }: { cat?: string }) {
  const { t } = useI18n();
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const openDialog = useExtractStore((s) => s.openDialog);

  if (currentProjectId === null) return null;

  return (
    <>
      <ExtractPendingEntry projectId={currentProjectId} />
      <button
        type="button"
        data-testid="extract-entry-lib"
        className={ENTRY_BTN_CLS}
        onClick={() => openDialog(currentProjectId, cat ? KIND_BY_CAT[cat] : undefined)}
      >
        {t('extract.title')}
      </button>
    </>
  );
}

/** #1582（拍板 B2-a）：「待确认提取（N）」入口 —— 未确认暂存批次的唯一可见入口。
 *
 *  为什么需要：两段式（#1545/#1546）在确认前正式表零变更，产物只在 `extract_staging`；
 *  结果只有靠本入口才能在关掉对话框 / 关掉 App 后仍被找回（否则只能等 #1551 的 30 天过期清理）。
 *  N = **批次数**（非条目数）；N=0 不渲染（不占位）。
 */
export function ExtractPendingEntry({ projectId }: { projectId: string }) {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const pending = useExtractStore((s) => s.pending);
  const pendingFor = useExtractStore((s) => s.pendingFor);
  const refreshPending = useExtractStore((s) => s.refreshPending);
  const viewBatch = useExtractStore((s) => s.viewBatch);
  const [panelOpen, setPanelOpen] = useState(false);

  // 挂载 / 切项目 → 重算 N（批次只存在服务端，「关掉 App 后回来」也靠这一步）
  useEffect(() => {
    void refreshPending(projectId);
  }, [projectId, refreshPending]);

  // 不串项目：只认归属本项目的列表（切项目瞬间列表为空，等新响应）
  const batches = pendingFor === projectId ? pending : [];
  if (batches.length === 0) return null;

  const confirm = async (batch: PendingBatch) => {
    try {
      await apiFetch(
        `/api/v1/projects/${projectId}/extractions/staging/${batch.batch_id}/confirm`,
        { method: 'POST' },
      );
      pushToast('ok', t('extract.done'));
    } catch (err) {
      pushToast('err', errorMessage(err));
      return;
    }
    await refreshPending(projectId);
    setPanelOpen(false);
  };

  const cancel = async (batch: PendingBatch) => {
    try {
      await apiFetch(
        `/api/v1/projects/${projectId}/extractions/staging/${batch.batch_id}/cancel`,
        { method: 'POST' },
      );
    } catch (err) {
      pushToast('err', errorMessage(err));
      return;
    }
    await refreshPending(projectId);
    setPanelOpen(false);
  };

  /** 查看：读单批（既有端点）→ 按 action 拆新增/更新 → 交结果视图 */
  const view = async (batch: PendingBatch) => {
    try {
      const data = await apiFetch<{ items?: Array<{ action?: string; name?: string; id?: string }> }>(
        `/api/v1/projects/${projectId}/extractions/staging/${batch.batch_id}`,
      );
      const items = data.items ?? [];
      viewBatch(projectId, {
        batchIds: [batch.batch_id],
        created: items.filter((i) => i.action === 'create'),
        updated: items.filter((i) => i.action === 'update'),
      });
      setPanelOpen(false);
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        data-testid="extract-pending-entry"
        className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        onClick={() => setPanelOpen((v) => !v)}
      >
        <History className="h-3.5 w-3.5" aria-hidden="true" />
        {t('extract.pending')}
        <span className="inline-flex h-[17px] min-w-[17px] items-center justify-center rounded-full bg-warn px-1.5 text-[11px] leading-none text-surface">
          {batches.length}
        </span>
      </button>

      {panelOpen && (
        <div
          data-testid="extract-pending-panel"
          className="absolute right-0 top-[calc(100%+6px)] z-20 w-[430px] rounded-lg border border-line bg-surface p-3 shadow-card"
        >
          <p className="text-[12px] text-ink-3">{t('extract.pendingNote')}</p>
          <div className="mt-2.5 flex flex-col gap-1.5">
            {batches.map((batch) => (
              <div
                key={batch.batch_id}
                data-testid="extract-pending-item"
                className="flex items-center gap-2 rounded-md border border-line bg-surface-2 px-2.5 py-2 text-[12px] text-ink"
              >
                <span className="rounded-full bg-surface-3 px-2 py-px text-[11px] text-ink-2">
                  {EXTRACT_RUN_TYPE_LABELS[batch.type] ?? batch.type}
                </span>
                <span>{t('extract.pendingCount', { count: batch.item_count })}</span>
                <span className="text-[11px] text-ink-3">
                  {batch.created_at.slice(0, 16).replace('T', ' ')}
                </span>
                <span className="ml-auto flex items-center gap-1.5">
                  <button
                    type="button"
                    data-testid="extract-pending-view"
                    className="rounded-md border border-line px-2.5 py-0.5 text-[12px] text-ink-2 transition duration-180 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                    onClick={() => void view(batch)}
                  >
                    {t('extract.pendingView')}
                  </button>
                  <button
                    type="button"
                    data-testid="extract-pending-cancel"
                    className="rounded-md border border-line px-2.5 py-0.5 text-[12px] text-ink-2 transition duration-180 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                    onClick={() => void cancel(batch)}
                  >
                    {t('extract.cancel')}
                  </button>
                  <button
                    type="button"
                    data-testid="extract-pending-confirm"
                    className="rounded-md border border-accent px-2.5 py-0.5 text-[12px] text-accent transition duration-180 hover:bg-accent hover:text-accent-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                    onClick={() => void confirm(batch)}
                  >
                    {t('extract.confirm')}
                  </button>
                </span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-ink-3">{t('extract.pendingFoot')}</p>
        </div>
      )}
    </div>
  );
}
