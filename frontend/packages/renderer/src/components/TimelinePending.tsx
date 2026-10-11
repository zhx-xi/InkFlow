/**
 * #1581 时间线「待确认区」—— 原「未知区」退役后的替代面（spec f19-gui/timeline.md §2 / §3 N17）。
 *
 * 【语义】机器无法把 `time_display` 原文换算为时间的事件**不进时间轴**（正式表零未定事件，
 * f12 §2.9 Z1），全部落此区：作者**逐条补时间后确认**（转正为正式事件、随即上刻度带）或**丢弃**。
 * 原文 `time_display` 永不留失。
 *
 * 【数据源】两路合并（f19 §1 ④）：
 *   ① 暂存项 —— `GET .../extractions/staging`（type=timeline）→ 逐批 `GET .../staging/{batch_id}`；
 *   ② 正式表中 `time_value` 为空的**存量**事件（由调用方从已拉的 timeline 数据派生传入，零额外请求）。
 *
 * 【动作】确认**强制带时间**（未填则按钮禁用，f12 §2.9 D3）：
 *   · 暂存项 → `POST .../staging/{batch_id}/items/{item_id}/confirm` / `DELETE .../items/{item_id}`
 *   · 存量项 → `PATCH /api/v1/timeline/events/{id}`（带 time_value/time_unit）/ `DELETE` 同路径
 *
 * 【可达 100%】复用公共 `Pagination`（页大小可改），不再受 `BAND_UNK_MAX` ≈ 2 行截断。
 */
import { useEffect, useState } from 'react';
import { apiFetch, errorMessage } from '../api/client';
import { Pagination } from './Pagination';
import { useI18n } from '../i18n/useI18n';
import { useToastStore } from '../stores/toast';
import { cn } from '../lib/cn';
import type { TimelineEventDTO } from './TimelineView';

/** 暂存批次（批次列表端点元素，契约冻结形状） */
interface StagingBatchDTO {
  batch_id: string;
  type: string;
  created_at: string;
  item_count: number;
}

/** 暂存条目（GET 暂存端点元素） */
interface StagedItemDTO {
  id?: number;
  entity_type: string;
  action: string;
  name: string;
  payload: Record<string, unknown>;
}

export interface TimelinePendingProps {
  projectId: string;
  /** 正式表中 `time_value` 为空的存量事件（#1581：不迁移、在待确认区呈现） */
  undeterminedEvents: TimelineEventDTO[];
  /** 事件 → 来源章标签（与刻度带共用同一映射） */
  chapterLabelOf: (ev: TimelineEventDTO) => string;
}

/** 每页条数档位（可达 100%） */
export const PEND_PAGE_SIZES = [20, 50, 100];

/** 补时间时的单位档位（对齐 f12 §2.7 S2 常量表） */
const UNIT_KEYS = [
  { value: '日', key: 'lib.tlPendUnit.day' },
  { value: '年', key: 'lib.tlPendUnit.year' },
  { value: '月', key: 'lib.tlPendUnit.month' },
] as const;

interface PendRow {
  key: string;
  raw: string;
  title: string;
  source: string;
  reason: string;
  /** 存量正式事件（#1581：确认 = PATCH） */
  eventId?: string | number;
  /** 暂存项（#1581：确认 = 条目级端点） */
  batchId?: string;
  itemId?: number;
}

export function TimelinePending({ projectId, undeterminedEvents, chapterLabelOf }: TimelinePendingProps) {
  const { t } = useI18n();
  const [staged, setStaged] = useState<PendRow[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(PEND_PAGE_SIZES[0]);
  const [times, setTimes] = useState<Record<string, string>>({});
  const [units, setUnits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  // 暂存项拉取（批次列表 → 逐批明细；type=timeline 之外的批次不属本区）
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await apiFetch<{ batches?: StagingBatchDTO[] }>(
          `/api/v1/projects/${projectId}/extractions/staging`,
        );
        const batches = (list.batches ?? []).filter((b) => b.type === 'timeline');
        const rows: PendRow[] = [];
        for (const batch of batches) {
          const one = await apiFetch<{ items?: StagedItemDTO[] }>(
            `/api/v1/projects/${projectId}/extractions/staging/${batch.batch_id}`,
          );
          for (const item of one.items ?? []) {
            if (item.entity_type !== 'timeline_event' || item.id === undefined) continue;
            const payload = item.payload ?? {};
            rows.push({
              key: `st-${item.id}`,
              raw: typeof payload.time_display === 'string' ? payload.time_display : '',
              title: typeof payload.title === 'string' ? payload.title : item.name,
              source: '',
              reason: typeof payload.parse_reason === 'string' ? payload.parse_reason : '',
              batchId: batch.batch_id,
              itemId: item.id,
            });
          }
        }
        if (!cancelled) setStaged(rows);
      } catch {
        if (!cancelled) setStaged([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, refreshKey]);

  const eventRows: PendRow[] = undeterminedEvents.map((ev) => ({
    key: `ev-${ev.id}`,
    raw: ev.time_display ?? '',
    title: ev.title ?? '',
    source: chapterLabelOf(ev),
    reason: t('lib.tlPendReasonFallback'),
    eventId: ev.id,
  }));
  const rows = [...eventRows, ...staged];
  if (rows.length === 0) return null;

  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const safePage = Math.min(page, pages - 1);
  const pageRows = rows.slice(safePage * pageSize, safePage * pageSize + pageSize);

  const timeOf = (key: string): number | null => {
    const raw = (times[key] ?? '').trim();
    if (raw === '') return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  };

  const run = async (row: PendRow, fn: () => Promise<unknown>) => {
    setBusy(row.key);
    try {
      await fn();
      setRefreshKey((k) => k + 1);
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const handleConfirm = (row: PendRow) =>
    run(row, async () => {
      const value = timeOf(row.key);
      if (value === null) return;
      const unit = units[row.key] ?? UNIT_KEYS[0].value;
      if (row.eventId !== undefined) {
        await apiFetch(`/api/v1/timeline/events/${row.eventId}`, {
          method: 'PATCH',
          body: { time_value: value, time_unit: unit },
        });
        return;
      }
      await apiFetch(
        `/api/v1/projects/${projectId}/extractions/staging/${row.batchId}/items/${row.itemId}/confirm`,
        { method: 'POST', body: { time_value: value, time_unit: unit } },
      );
    });

  const handleDiscard = (row: PendRow) =>
    run(row, async () => {
      if (row.eventId !== undefined) {
        await apiFetch(`/api/v1/timeline/events/${row.eventId}`, { method: 'DELETE' });
        return;
      }
      await apiFetch(
        `/api/v1/projects/${projectId}/extractions/staging/${row.batchId}/items/${row.itemId}`,
        { method: 'DELETE' },
      );
    });

  return (
    <section data-testid="tl-pend" className="rounded-lg border border-line bg-surface shadow-card">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-2.5">
        <span className="text-[12.5px] font-medium text-ink">{t('lib.tlPendTitle')}</span>
        <span data-testid="tl-pend-count" className="text-[11px] tabular-nums text-ink-3">
          {t('lib.tlPendCount', { n: rows.length })}
        </span>
        <span className="ml-auto text-[11px] text-ink-3">{t('lib.tlPendHint')}</span>
      </div>
      <div className="flex items-center gap-2.5 border-b border-dashed border-line bg-surface-2 px-3.5 py-1.5 text-[11px] text-ink-3">
        <span style={{ flex: 'none', width: 132 }}>{t('lib.tlPendColRaw')}</span>
        <span style={{ flex: 1 }}>{t('lib.tlPendColEvent')}</span>
        <span style={{ flex: 'none', width: 74 }}>{t('lib.tlPendColSource')}</span>
        <span style={{ flex: 'none', width: 152 }}>{t('lib.tlPendColTime')}</span>
        <span style={{ flex: 'none', width: 150 }}>{t('lib.tlPendColReason')}</span>
        <span style={{ flex: 'none', width: 112 }}>{t('lib.tlPendColActions')}</span>
      </div>
      {pageRows.map((row) => (
        <div
          key={row.key}
          data-testid={`tl-pend-row-${row.key}`}
          className="flex items-center gap-2.5 border-b border-surface-2 px-3.5 py-1.5 text-[12px] last:border-b-0 hover:bg-surface-2"
        >
          <span
            data-testid={`tl-pend-raw-${row.key}`}
            className={cn('truncate', row.raw ? 'text-ink' : 'text-ink-3')}
            style={{ flex: 'none', width: 132 }}
          >
            {row.raw || t('lib.tlPendNoRaw')}
          </span>
          <span className="min-w-0 flex-1 truncate text-ink-2" style={{ flex: 1 }}>
            {row.title}
          </span>
          <span
            className="shrink-0 rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-3"
            style={{ flex: 'none', width: 74 }}
          >
            {row.source}
          </span>
          <span className="flex shrink-0 items-center gap-1" style={{ flex: 'none' }}>
            <input
              data-testid={`tl-pend-time-${row.key}`}
              value={times[row.key] ?? ''}
              placeholder={t('lib.tlPendPlaceholder')}
              onChange={(e) => setTimes((prev) => ({ ...prev, [row.key]: e.target.value }))}
              className="w-16 rounded-md border border-line bg-bg px-1.5 py-0.5 text-[11.5px] tabular-nums text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <select
              data-testid={`tl-pend-unit-${row.key}`}
              value={units[row.key] ?? UNIT_KEYS[0].value}
              onChange={(e) => setUnits((prev) => ({ ...prev, [row.key]: e.target.value }))}
              className="rounded-md border border-line bg-bg px-1 py-0.5 text-[11.5px] text-ink-2"
            >
              {UNIT_KEYS.map((u) => (
                <option key={u.value} value={u.value}>
                  {t(u.key)}
                </option>
              ))}
            </select>
          </span>
          <span
            data-testid={`tl-pend-reason-${row.key}`}
            className="truncate text-[11px] text-ink-3"
            style={{ flex: 'none', width: 150 }}
            title={row.reason}
          >
            {row.reason}
          </span>
          <span className="flex shrink-0 items-center gap-1.5" style={{ flex: 'none' }}>
            <button
              type="button"
              data-testid={`tl-pend-confirm-${row.key}`}
              disabled={timeOf(row.key) === null || busy === row.key}
              className="rounded-md border border-line px-2.5 py-0.5 text-[11px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink-2"
              onClick={() => void handleConfirm(row)}
            >
              {t('lib.tlPendConfirm')}
            </button>
            <button
              type="button"
              data-testid={`tl-pend-discard-${row.key}`}
              disabled={busy === row.key}
              className="rounded-md border border-line px-2.5 py-0.5 text-[11px] text-ink-2 transition duration-150 hover:border-err hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default disabled:opacity-40"
              onClick={() => void handleDiscard(row)}
            >
              {t('lib.tlPendDiscard')}
            </button>
          </span>
        </div>
      ))}
      <Pagination
        page={safePage}
        pageSize={pageSize}
        total={rows.length}
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size);
          setPage(0);
        }}
        pageSizeOptions={PEND_PAGE_SIZES}
        testIdPrefix="tl-pend"
        className="px-3.5 py-2.5"
      />
    </section>
  );
}
