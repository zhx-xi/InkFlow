import { useEffect, useState } from 'react';
import { History, X } from 'lucide-react';
import { apiFetch, errorMessage } from '../../api/client';
import { cn } from '../../lib/cn';
import { ConfirmDialog } from '../ConfirmDialog';
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

/** 面板行内次要动作按钮 */
const ROW_BTN_CLS =
  'rounded-md border border-line px-2.5 py-0.5 text-[12px] text-ink-2 transition duration-180 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60';

/** #1590 详情面板：暂存条目（GET .../staging/{batch_id} 元素形状） */
interface StagedItemDTO {
  id?: number;
  entity_type: string;
  action: string;
  name: string;
  payload: Record<string, unknown>;
}

/** #1590 详情字段顺序（逐一取自 payload；空值给占位，绝不渲染 null） */
const DETAIL_FIELDS = [
  'title',
  'description',
  'time_display',
  'parse_reason',
  'time_value',
  'time_unit',
  'era',
  'era_value',
  'era_scale',
  'narrative_position',
  'timeline_flag',
  'entity_type',
  'action',
] as const;

/** entity_type → 既有 i18n 标签（未登记的原值兜底显示原值） */
const ENTITY_TYPE_KEY: Record<string, string> = {
  character: 'extract.character',
  world_setting: 'extract.world',
  timeline_event: 'extract.timeline',
  foreshadowing: 'extract.foreshadowing',
  knowledge_relation: 'extract.knowledgeGraph',
};

/** 补时间单位档位（对齐 f12 §2.7；复用时间线待确认区同款键） */
const DETAIL_UNITS = [
  { value: '年', key: 'lib.tlPendUnit.year' },
  { value: '月', key: 'lib.tlPendUnit.month' },
  { value: '日', key: 'lib.tlPendUnit.day' },
] as const;

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
  /** #1590：取消二次确认弹窗的目标批次（null = 关） */
  const [cancelPrompt, setCancelPrompt] = useState<PendingBatch | null>(null);
  /** #1590：条目详情面板的目标批次（null = 关） */
  const [detailBatch, setDetailBatch] = useState<PendingBatch | null>(null);

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

  /** #1590：取消 = 清本批暂存（不可逆）——只由确认弹窗的「×」触发 */
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
          className="absolute right-0 top-[calc(100%+6px)] z-20 w-[520px] rounded-lg border border-line bg-surface p-3 shadow-card"
        >
          <p className="text-[12px] text-ink-3">{t('extract.pendingNote')}</p>
          <div className="mt-2.5 flex flex-col gap-1.5">
            {batches.map((batch) => (
              <div
                key={batch.batch_id}
                data-testid="extract-pending-item"
                className="flex cursor-pointer items-center gap-2 rounded-md border border-line bg-surface-2 px-2.5 py-2 text-[12px] text-ink"
                /* #1590：整行可点开详情（行内按钮经 closest('button') 排除） */
                onClick={(e) => {
                  if ((e.target as HTMLElement).closest('button') !== null) return;
                  setDetailBatch(batch);
                }}
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
                    data-testid="extract-pending-detail"
                    className={ROW_BTN_CLS}
                    onClick={() => setDetailBatch(batch)}
                  >
                    {t('extract.pendingDetail')}
                  </button>
                  <button
                    type="button"
                    data-testid="extract-pending-view"
                    className={ROW_BTN_CLS}
                    onClick={() => void view(batch)}
                  >
                    {t('extract.pendingView')}
                  </button>
                  <button
                    type="button"
                    data-testid="extract-pending-cancel"
                    className={ROW_BTN_CLS}
                    /* #1590：不再点了即删 —— 先弹二次确认 */
                    onClick={() => setCancelPrompt(batch)}
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

      {/* #1590（拍板 D7=A）：取消批次二次确认——右上角「×」= 确认取消（destructive）·「—」= 最小化保留（零请求）；底部「返回」只关弹窗 */}
      <ConfirmDialog
        open={cancelPrompt !== null}
        testidPrefix="extract-pending-cancel-prompt"
        title={t('extract.pendingCancelTitle')}
        message={t('extract.pendingCancelBody')}
        confirmText={t('extract.pendingCancelBack')}
        hideCancel
        onConfirm={() => setCancelPrompt(null)}
        onOpenChange={(open) => {
          if (!open) setCancelPrompt(null);
        }}
        minimizeLabel={t('extract.pendingCancelMinimize')}
        onMinimize={() => {
          setCancelPrompt(null);
          setPanelOpen(false);
        }}
        destructiveLabel={t('extract.cancel')}
        onDestructive={() => {
          const target = cancelPrompt;
          setCancelPrompt(null);
          if (target !== null) void cancel(target);
        }}
      />

      {/* #1590（拍板 D8=B）：条目详情右侧面板 */}
      {detailBatch !== null && (
        <StagedDetailDrawer
          projectId={projectId}
          batch={detailBatch}
          onClose={() => setDetailBatch(null)}
        />
      )}
    </div>
  );
}

/** #1590（拍板 D8=B）：条目详情右侧面板。
 *
 *  为什么这样：批次行只能看到「类型 / 条数 / 时间」，作者无法核对暂存内容（title / 时间原文 / 未定原因）
 *  就得盲确认或盲取消。字段**逐一取自** `GET .../staging/{batch_id}` 的 `payload`（零新端点）；
 *  底部是**单一**动作区（确认落库 / 丢弃），避免与面板行的批次级按钮语义分叉。
 *  「确认落库」强制带时间（f12 §2.9 D3：未填则禁用，条目级端点缺 time_value → 422）。
 */
function StagedDetailDrawer({
  projectId,
  batch,
  onClose,
}: {
  projectId: string;
  batch: PendingBatch;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const refreshPending = useExtractStore((s) => s.refreshPending);
  const [items, setItems] = useState<StagedItemDTO[]>([]);
  const [selected, setSelected] = useState(0);
  const [time, setTime] = useState('');
  const [unit, setUnit] = useState<string>(DETAIL_UNITS[0].value);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  // 开面板 / 每次动作后重读本批明细（唯一数据源 = 服务端）
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await apiFetch<{ items?: StagedItemDTO[] }>(
          `/api/v1/projects/${projectId}/extractions/staging/${batch.batch_id}`,
        );
        if (!cancelled) setItems(data.items ?? []);
      } catch (err) {
        if (!cancelled) pushToast('err', errorMessage(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, batch.batch_id, reloadKey, pushToast]);

  // Esc 关闭（镜像 ConfirmDialog 的 document 级监听）
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const item = items[selected] ?? items[0];
  const activeIndex = item === undefined ? -1 : items.indexOf(item);
  const timeValue = time.trim() === '' ? null : Number(time);
  const timeValid = timeValue !== null && Number.isFinite(timeValue);

  /** 空值 → 占位文案（绝不渲染 null）；entity_type / action 走显示名 */
  const displayOf = (row: StagedItemDTO, key: string): string | null => {
    if (key === 'entity_type') {
      const labelKey = ENTITY_TYPE_KEY[row.entity_type];
      return labelKey === undefined ? row.entity_type : t(labelKey);
    }
    if (key === 'action') {
      return row.action === 'create' ? t('extract.pendingActionCreate') : t('extract.pendingActionUpdate');
    }
    const raw = row.payload?.[key];
    if (raw === null || raw === undefined || raw === '') return null;
    return typeof raw === 'string' ? raw : String(raw);
  };

  const runItem = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      await refreshPending(projectId);
      if (items.length <= 1) {
        onClose(); // 最后一条已处理 → 批次空了
        return;
      }
      setReloadKey((k) => k + 1);
    } catch (err) {
      pushToast('err', errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleConfirmItem = () =>
    item === undefined || timeValue === null
      ? Promise.resolve()
      : runItem(() =>
          apiFetch(
            `/api/v1/projects/${projectId}/extractions/staging/${batch.batch_id}/items/${item.id}/confirm`,
            { method: 'POST', body: { time_value: timeValue, time_unit: unit } },
          ),
        );

  const handleDiscardItem = () =>
    item === undefined
      ? Promise.resolve()
      : runItem(() =>
          apiFetch(
            `/api/v1/projects/${projectId}/extractions/staging/${batch.batch_id}/items/${item.id}`,
            { method: 'DELETE' },
          ),
        );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('extract.pendingDrawerTitle')}
      data-testid="extract-pending-drawer"
      className="fixed inset-y-0 right-0 z-40 flex w-[430px] flex-col border-l border-line bg-surface shadow-card"
    >
      <div className="flex shrink-0 items-start justify-between border-b border-line px-4 py-3">
        <div>
          <h2 className="font-serif text-[16px] font-semibold">{t('extract.pendingDrawerTitle')}</h2>
          <div className="mt-1 flex items-center gap-1.5 text-[11px] text-ink-3">
            <span className="rounded-full bg-surface-3 px-2 py-px text-ink-2">
              {EXTRACT_RUN_TYPE_LABELS[batch.type] ?? batch.type}
            </span>
            <span>{t('extract.pendingCount', { count: batch.item_count })}</span>
            <span>{batch.created_at.slice(0, 16).replace('T', ' ')}</span>
          </div>
        </div>
        <button
          type="button"
          data-testid="extract-pending-drawer-close"
          aria-label={t('audit.close')}
          className="rounded p-1 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          onClick={onClose}
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <p className="text-[11px] text-ink-3">{t('extract.pendingDrawerItems')}</p>
        <div className="mt-2 flex flex-col gap-1">
          {items.map((row, index) => (
            <button
              key={row.id ?? index}
              type="button"
              data-testid="extract-pending-drawer-item"
              className={cn(
                'flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-[12px] transition duration-180 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60',
                index === activeIndex
                  ? 'border-accent bg-accent-weak text-ink'
                  : 'border-line bg-surface-2 text-ink-2 hover:bg-surface-3',
              )}
              onClick={() => setSelected(index)}
            >
              <span className="truncate">{row.name}</span>
              <span className="ml-auto rounded-full bg-surface-3 px-2 py-px text-[11px] text-ink-3">
                {row.action === 'create' ? t('extract.pendingActionCreate') : t('extract.pendingActionUpdate')}
              </span>
            </button>
          ))}
        </div>

        {item !== undefined && (
          <div
            data-testid="extract-pending-drawer-detail"
            className="mt-4 flex flex-col gap-1.5 border-t border-dashed border-line pt-3"
          >
            {DETAIL_FIELDS.map((key) => {
              const shown = displayOf(item, key);
              return (
                <div key={key} className="flex gap-2 text-[12px] leading-relaxed">
                  <span className="w-[74px] flex-none text-ink-3">{t(`extract.pendingField.${key}`)}</span>
                  <span
                    data-testid={`extract-pending-field-${key}`}
                    className={cn('min-w-0 flex-1 break-words', shown === null ? 'text-ink-3' : 'text-ink')}
                  >
                    {shown ?? t('extract.pendingFieldEmpty')}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="flex-none border-t border-line px-4 py-3">
        <label className="flex items-center gap-1.5 text-[12px] text-ink-2">
          {t('extract.pendingTimeLabel')}
          <input
            data-testid="extract-pending-drawer-time"
            value={time}
            placeholder={t('extract.pendingTimePlaceholder')}
            onChange={(e) => setTime(e.target.value)}
            className="w-[90px] rounded-md border border-line bg-bg px-2 py-1 text-[12px] tabular-nums text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <select
            data-testid="extract-pending-drawer-unit"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            className="rounded-md border border-line bg-bg px-1.5 py-1 text-[12px] text-ink-2"
          >
            {DETAIL_UNITS.map((u) => (
              <option key={u.value} value={u.value}>
                {t(u.key)}
              </option>
            ))}
          </select>
        </label>
        <div className="mt-2.5 flex items-center gap-2">
          <button
            type="button"
            data-testid="extract-pending-discard"
            disabled={busy || item === undefined}
            className="rounded-md border border-line px-3 py-1 text-[13px] text-ink-2 transition duration-180 hover:border-err/40 hover:bg-err/5 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:opacity-40"
            onClick={() => void handleDiscardItem()}
          >
            {t('lib.tlPendDiscard')}
          </button>
          <button
            type="button"
            data-testid="extract-pending-item-confirm"
            disabled={!timeValid || busy || item === undefined}
            className="ml-auto rounded-md bg-accent px-3 py-1 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-default disabled:bg-surface-3 disabled:text-ink-3"
            onClick={() => void handleConfirmItem()}
          >
            {t('extract.confirm')}
          </button>
        </div>
      </div>
    </div>
  );
}
