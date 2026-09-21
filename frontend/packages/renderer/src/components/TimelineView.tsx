/**
 * F43 P4 时间线双序 + 两级检查（specs/f43-setting-library-gui/spec.md §5.16-5.17）：
 * 工具栏（timeline-toolbar）= 双序 chips（tl-view-narrative 默认激活 / tl-view-world）+
 * 整体检查（tl-check-all）+ 图例（tl-legend）；
 * 双序切换仅本地切换显示数组（零额外请求；narrative_order 为空时回退 event_timeline）；
 * 行内单事件检查（tl-check-one-<id>）；检查结果 toast 契约见 library-p4.test.tsx docstring。
 *
 * #1301（spec↔实现漂移修复）：补**时间轴渲染**（tl-axis）。
 * #1323（R6-3 拍板）：轴**保留形态**，改为「**章分组容器**」——
 * - 旧实现把同一批 `displayed` **渲染两遍**（`tl-axis` 逐事件轴 + `library-list` 列表）→
 *   用户看到「上下两块」重复。现在**单一容器**：轴即列表，每个事件恰好渲染一次。
 * - 旧实现用 `narrative_position` 拼「第 N 章」当主轴 —— 该字段是**单一线性序号**
 *   （`domain/models/timeline.py:158`；`specs/f12-timeline/spec.md:91` 明确不携带章节语义），
 *   DB 实测 215 条只有 34 个不同位置值（同一「第 7 章」重复 10 次）。
 *   现改为按 `source_chapter_id` **分组**，header 用**真实章节标题**
 *   （`chapterTitles` 映射，形态照抄 hooks/useOutlineLibrary.ts:107-108 先例）。
 * - 未归章事件（`source_chapter_id` 空）落「未分章」组（`tl-group-__none__`）。
 * 轴为竖向（时间轴惯例；spec 未指定方向）。
 * ⚠️ timeline_flag 语义（spec f12 §6.2:707）：后端为**自由文本 str**（""=正叙 / flashback / flashforward），
 * 非布尔；本组件此前 DTO 声明成 boolean 属漂移，已按真实契约改为 string | boolean（兼容旧 mock），
 * 且**轴渲染不使用该字段**（仅语义标记，与「轴锚点」无关——「时间轴锚点」猜想已证伪）。
 * ⚠️ #1323 G6：后端一致性检查已改**包含式**匹配中文标记（倒叙/插叙），前端不参与该判定。
 *
 * #1302：列表行内编辑（tl-edit-<id>）/ 删除（tl-delete-<id>）入口——形态照抄
 * LibraryItemList.tsx:148-167 先例（group-hover + focus-within 双触发保证键盘可达可见）；
 * 编辑复用 LibraryCreateDialog（editing prop），删除走页面级 ConfirmDialog。
 */
import { useMemo, useState } from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import { apiFetch, errorMessage } from '../api/client';
import { axisLabels } from './timeline-axis-labels';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import { useToastStore } from '../stores/toast';

/** 时间线事件 DTO（spec §2.9：time_value/time_display/narrative_position）
 *  #1323：补 `source_chapter_id`（后端 `api/routers/timeline.py:207` 的 model_dump
 *  早已返回；DB 实测 214/215 非空）→ 用于章分组与真实章节标题。 */
export interface TimelineEventDTO {
  id: string | number;
  title?: string;
  description?: string;
  time_value?: number | null;
  time_unit?: string | null;
  time_display?: string | null;
  narrative_position?: number | null;
  /** #1323：提取来源章节 id（null/缺省 = 手工事件 → 落「未分章」组） */
  source_chapter_id?: string | number | null;
  /** spec f12 §6.2:707：自由文本（""=正叙 / flashback / flashforward），非布尔。
   *  旧 DTO 误声明为 boolean（漂移）；`string | boolean` 兼容历史 mock 数据。 */
  timeline_flag?: string | boolean;
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
  /** #1323：章节 id → 真实标题映射（形态照抄 useOutlineLibrary 的 chapterTitles）。
   *  缺省/缺失时 header 退化为「未知章节」占位，事件不消失。 */
  chapterTitles?: Record<string, string>;
  /** #1302：行内编辑入口（打开 LibraryCreateDialog 编辑模式）；缺省不渲染按钮。
   *  形参用 TimelineEventDTO 的结构子集（id/title/description 等），便于与页面级
   *  LibraryItemDTO 回调共用（后者字段更宽，不可逆赋值会被 tsc 拦下）。 */
  onEdit?: (event: TimelineRowRef) => void;
  /** #1302：行内删除入口（打开页面级二次确认）；缺省不渲染按钮 */
  onDelete?: (event: TimelineRowRef) => void;
}

/** #1302：行内操作回调只需行的标识与标题（可被 LibraryItemDTO 回调安全承接 —— 参数逆变安全） */
export interface TimelineRowRef {
  id: string | number;
  title?: string;
}

type TimelineViewMode = 'narrative' | 'world';

/** #1323：未归章事件的分组键（source_chapter_id 为空） */
const NO_CHAPTER_KEY = '__none__';

/** #1323：一个章分组（键 = source_chapter_id 字符串，或未分章的哨兵键） */
interface ChapterGroup {
  key: string;
  events: TimelineEventDTO[];
}

/** #1323：按 source_chapter_id 分组（保持 displayed 的原始顺序 → 组内顺序即该序的顺序） */
function groupByChapter(events: TimelineEventDTO[]): ChapterGroup[] {
  const order: string[] = [];
  const buckets = new Map<string, TimelineEventDTO[]>();
  for (const ev of events) {
    const raw = ev.source_chapter_id;
    const key = raw === null || raw === undefined || raw === '' ? NO_CHAPTER_KEY : String(raw);
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)!.push(ev);
  }
  return order.map((key) => ({ key, events: buckets.get(key)! }));
}

export function TimelineView({
  projectId,
  eventTimeline,
  narrativeOrder,
  chapterTitles,
  onEdit,
  onDelete,
}: TimelineViewProps) {
  const { t } = useI18n();
  const [view, setView] = useState<TimelineViewMode>('narrative');

  // 双序切换 = 本地切换显示数组（零额外请求，T2/T3 契约）；narrative_order 空 → 回退 event_timeline（旧数据兜底）
  const displayed = useMemo(() => {
    if (view === 'world') return eventTimeline;
    return narrativeOrder.length > 0 ? narrativeOrder : eventTimeline;
  }, [view, eventTimeline, narrativeOrder]);

  // #1323：章分组（一章一个 header；组内顺序 = 当前序的顺序）
  const groups = useMemo(() => groupByChapter(displayed), [displayed]);

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

      {/* #1323 时间轴 = 章分组容器（竖向；每事件恰好渲染一次；空列表不渲染轴） */}
      {displayed.length > 0 ? (
        <div
          data-testid="tl-axis"
          aria-label={t('lib.tlAxis')}
          className="space-y-3"
        >
          <div data-testid="library-list" className="space-y-3">
          {groups.map((group) => (
            <div
              key={group.key}
              data-testid={`tl-group-${group.key}`}
              className="relative rounded-lg border border-line bg-surface px-4 py-3 shadow-card"
            >
              {/* 轴线本体：左侧竖线，贯穿本组节点 */}
              <span aria-hidden="true" className="absolute bottom-5 left-[7px] top-9 w-px bg-line" />
              <div
                data-testid={`tl-group-title-${group.key}`}
                className="mb-2 pl-5 text-[12px] font-medium text-ink-2"
              >
                {group.key === NO_CHAPTER_KEY
                  ? t('lib.tlGroupNone')
                  : (chapterTitles?.[group.key] ?? t('lib.tlChapterUnknown'))}
              </div>
              <ol className="space-y-2">
                {group.events.map((ev) => {
                  const labels = axisLabels(ev, view, t);
                  return (
                    <li
                      key={String(ev.id)}
                      data-testid={`tl-axis-node-${ev.id}`}
                      className="group relative flex items-center gap-3 pl-5 text-[12px]"
                    >
                      {/* 节点圆点（贴轴线上） */}
                      <span
                        aria-hidden="true"
                        className="absolute left-0 top-1/2 h-[7px] w-[7px] -translate-y-1/2 rounded-full bg-accent"
                      />
                      <span
                        data-testid={`tl-axis-main-${ev.id}`}
                        className="shrink-0 font-medium tabular-nums text-ink"
                      >
                        {labels.main}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-ink-2">{ev.title ?? ''}</span>
                      {labels.sub ? (
                        <span
                          data-testid={`tl-axis-sub-${ev.id}`}
                          className="shrink-0 text-[11px] text-ink-3"
                        >
                          {labels.sub}
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
                      {/* #1302：悬停显示操作按钮；focus-within 保证键盘可达可见（照抄 LibraryItemList.tsx:148-149） */}
                      <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
                        <button
                          type="button"
                          data-testid={`tl-edit-${ev.id}`}
                          aria-label={`${t('lib.edit')} ${ev.title ?? ''}`}
                          className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => onEdit?.(ev)}
                        >
                          <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          data-testid={`tl-delete-${ev.id}`}
                          aria-label={`${t('lib.delete')} ${ev.title ?? ''}`}
                          className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => onDelete?.(ev)}
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
          ))}
        </div>
          </div>
      ) : null}
    </div>
  );
}
