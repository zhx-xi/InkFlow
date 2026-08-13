/**
 * F43 P4 时间线双序 + 两级检查（specs/f43-setting-library-crud/spec.md §5.16-5.17）：
 * 工具栏（timeline-toolbar）= 双序 chips（tl-view-narrative 默认激活 / tl-view-world）+
 * 整体检查（tl-check-all）+ 图例（tl-legend）；
 * 双序切换仅本地切换显示数组（零额外请求；narrative_order 为空时回退 event_timeline）；
 * 行内单事件检查（tl-check-one-<id>）；检查结果 toast 契约见 library-p4.test.tsx docstring。
 */
import { useMemo, useState } from 'react';
import { apiFetch, errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import { useToastStore } from '../stores/toast';

/** 时间线事件 DTO（spec §2.9：time_value/time_display/narrative_position） */
export interface TimelineEventDTO {
  id: string | number;
  title?: string;
  description?: string;
  time_value?: number | null;
  time_unit?: string | null;
  time_display?: string | null;
  narrative_position?: number | null;
  timeline_flag?: boolean;
}

/** 完整 TimelineView（spec §5.16：双数组 = 后端排序结果，前端仅本地切换显示数组） */
export interface TimelineViewData {
  project_id?: string | number;
  total?: number;
  event_timeline: TimelineEventDTO[];
  narrative_order: TimelineEventDTO[];
}

interface ConflictDTO {
  conflict_type?: string;
  prev?: string;
  next?: string;
  message?: string;
}

interface OverallCheckResult {
  checked: number;
  skipped: number;
  consistent: boolean;
  conflicts: ConflictDTO[];
  flashbacks?: unknown[];
}

interface EventCheckResult {
  event_id?: string | number;
  checked: boolean;
  consistent: boolean;
  conflicts: ConflictDTO[];
  flashbacks?: unknown[];
}

export interface TimelineViewProps {
  projectId: string;
  /** 世界序（time_value 升序、None 排末尾） */
  eventTimeline: TimelineEventDTO[];
  /** 叙事序（narrative_position 升序） */
  narrativeOrder: TimelineEventDTO[];
}

type TimelineViewMode = 'narrative' | 'world';

export function TimelineView({ projectId, eventTimeline, narrativeOrder }: TimelineViewProps) {
  const { t } = useI18n();
  const [view, setView] = useState<TimelineViewMode>('narrative');

  // 双序切换 = 本地切换显示数组（零额外请求，T2/T3 契约）；narrative_order 空 → 回退 event_timeline（旧数据兜底）
  const displayed = useMemo(() => {
    if (view === 'world') return eventTimeline;
    return narrativeOrder.length > 0 ? narrativeOrder : eventTimeline;
  }, [view, eventTimeline, narrativeOrder]);

  const handleCheckAll = async () => {
    try {
      const res = await apiFetch<OverallCheckResult>(`/api/v1/projects/${projectId}/timeline/check`);
      if (res.consistent) {
        useToastStore.getState().pushToast('ok', t('lib.tlCheckOK'));
      } else {
        useToastStore
          .getState()
          .pushToast('warn', t('lib.tlCheckWarn', { n: (res.conflicts ?? []).length }));
      }
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  const handleCheckOne = async (eventId: string | number) => {
    try {
      const res = await apiFetch<EventCheckResult>(`/api/v1/timeline/events/${eventId}/check`);
      if (res.checked === false) {
        useToastStore.getState().pushToast('warn', t('lib.tlCheckSkip'));
      } else if (res.consistent) {
        useToastStore.getState().pushToast('ok', t('lib.tlCheckEventOK'));
      } else {
        const conflicts = res.conflicts ?? [];
        useToastStore
          .getState()
          .pushToast('warn', conflicts[0]?.message ?? t('lib.tlCheckWarn', { n: conflicts.length }));
      }
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  return (
    <div className="space-y-3">
      <div data-testid="timeline-toolbar" className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1 rounded-full border border-line p-0.5">
          <button
            type="button"
            data-testid="tl-view-narrative"
            aria-pressed={view === 'narrative'}
            className={cn(
              'rounded-full px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              view === 'narrative' ? 'bg-accent text-accent-ink' : 'text-ink-2 hover:text-ink',
            )}
            onClick={() => setView('narrative')}
          >
            {t('lib.tlView.narrative')}
          </button>
          <button
            type="button"
            data-testid="tl-view-world"
            aria-pressed={view === 'world'}
            className={cn(
              'rounded-full px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              view === 'world' ? 'bg-accent text-accent-ink' : 'text-ink-2 hover:text-ink',
            )}
            onClick={() => setView('world')}
          >
            {t('lib.tlView.world')}
          </button>
        </div>
        <button
          type="button"
          data-testid="tl-check-all"
          className="inline-flex items-center rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={() => void handleCheckAll()}
        >
          {t('lib.tlCheck')}
        </button>
        <span data-testid="tl-legend" className="text-[12px] text-ink-3">
          {t('lib.tlLegend')}
        </span>
      </div>

      <ul
        data-testid="library-list"
        className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface shadow-card"
      >
        {displayed.map((ev) => (
          <li key={String(ev.id)} className="group flex items-center gap-3 px-4 py-2.5 text-[13px] text-ink">
            <span className="min-w-0 flex-1 truncate">{ev.title ?? ''}</span>
            {ev.time_display ? (
              <span className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2">
                {ev.time_display}
              </span>
            ) : null}
            <button
              type="button"
              data-testid={`tl-check-one-${ev.id}`}
              aria-label={`${t('lib.tlCheckOne')} ${ev.title ?? ''}`}
              className="shrink-0 rounded-md border border-line px-2.5 py-1 text-[11px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => void handleCheckOne(ev.id)}
            >
              {t('lib.tlCheckOne')}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
