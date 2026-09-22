/**
 * F43 P4 时间线双序 + 两级检查（specs/f43-setting-library-gui/spec.md §5.16-5.17）：
 * 工具栏（timeline-toolbar）= 双序 chips（tl-view-narrative 默认激活 / tl-view-world）+
 * 筛选（#1374）+ 整体检查（tl-check-all）+ 图例（tl-legend）；双序切换仅本地切换显示数组
 * （零额外请求；narrative_order 为空时回退 event_timeline）；
 * 行内单事件检查（tl-check-one-<id>）；检查结果 toast 契约见 library-p4.test.tsx docstring。
 *
 * #1301（spec↔实现漂移修复）：补**时间轴渲染**（tl-axis）。
 * #1323（R6-3 拍板，保留不破）：**单一容器**（轴即列表，每个事件恰好渲染一次）；
 * 按 `source_chapter_id` 分组，章刻度用**真实章节标题**（`chapterTitles` 映射，
 * 形态照抄 hooks/useOutlineLibrary.ts 先例）；未归章事件落「未分章」刻度。
 * `narrative_position` 是**单一线性序号**（`domain/models/timeline.py:158`；
 * `specs/f12-timeline/spec.md:91` 明确不携带章节语义）→ 仅用于排序，
 * 不拼「第 N 章」（DB 实测 215 条只有 34 个不同值）。
 * ⚠️ timeline_flag 语义（spec f12 §6.2:707）：后端为**自由文本 str**
 * （""=正叙 / flashback / flashforward），非布尔；本组件 DTO 声明为 string | boolean（兼容旧 mock）。
 * ⚠️ #1323 G6：后端一致性检查为**包含式**匹配中文标记（倒叙/插叙），前端不参与判定；
 * 本组件**筛选**复用同源词表（FILTER 词表见下）。
 *
 * #1374（issue 拍板「A 拆半」+ specs/f19-gui/timeline.md §1.1）：**双序轴向语义分流**——
 * - **叙事序**：轴刻度 = **章**（章刻度 `tl-chtick-<chapterId>`，真实章节标题；
 *   组顺序 = 章序（`chapterOrder` 章节列表顺序）→ 章内 `narrative_position` 合成序）；
 *   事件行内世界内时间**降级为小字**（ink-3）
 * - **世界序**：轴刻度 = **世界内时间**（行内主轴即刻度）；**无章分组容器**；
 *   行尾 = 来源章胶囊（`tl-src-<id>`）
 * - **筛选**（客户端，两序共用）：按章（`tl-filter-chapter` / `tl-fp-item-<key>`；
 *   全部章节 / 各章 / 未分章）+ 按事件类型（`tl-filter-type` / `tl-tp-item-<key>`；
 *   正叙/倒叙/插叙，词表对齐后端 #1323 G6）；重置 = 「全部」
 * - ⚠️ 数据面：#1374 纪元分轴（多纪元）不在本变更范围 —— 留 0.16.0（#1353/#1328）
 *
 * #1302：列表行内编辑（tl-edit-<id>）/ 删除（tl-delete-<id>）入口——形态照抄
 * LibraryItemList.tsx:148-167 先例（group-hover + focus-within 双触发保证键盘可达可见）；
 * 编辑复用 LibraryCreateDialog（editing prop），删除走页面级 ConfirmDialog。
 */
import { useMemo, useState } from 'react';
import { Check, ChevronDown, Filter, Pencil, Trash2 } from 'lucide-react';
import { apiFetch, errorMessage } from '../api/client';
import { axisLabels } from './timeline-axis-labels';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import { useToastStore } from '../stores/toast';

/** 时间线事件 DTO（spec §2.9：time_value/time_display/narrative_position）
 *  #1323：补 `source_chapter_id`（后端 `api/routers/timeline.py:207` 的 model_dump
 *  早已返回；DB 实测 214/215 非空）→ 用于章刻度与真实章节标题。 */
export interface TimelineEventDTO {
  id: string | number;
  title?: string;
  description?: string;
  time_value?: number | null;
  time_unit?: string | null;
  time_display?: string | null;
  narrative_position?: number | null;
  /** #1323：提取来源章节 id（null/缺省 = 手工事件 → 落「未分章」） */
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
   *  缺省/缺失时刻度退化为「未知章节」占位，事件不消失。 */
  chapterTitles?: Record<string, string>;
  /** #1374：章序（章节列表顺序）——叙事序组顺序与章筛选项列表由此决定；
   *  缺省时回退「事件首次出现顺序」（#1323 合成序）且筛选面板仅列事件中出现的章。 */
  chapterOrder?: string[];
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

/** #1374：章筛选值（'all' = 不过滤 / 章节 id / 未分章哨兵） */
type ChapterFilter = string;

/** #1374：事件类型筛选值 */
type TypeFilter = 'all' | 'normal' | 'flashback' | 'flashforward';

/** #1374：倒叙/插叙词表（对齐后端 #1323 G6 包含式匹配；判定序 = 后端 _classify_pair） */
const FLASHBACK_WORDS = ['flashback', '倒叙', '回忆'];
const FLASHFORWARD_WORDS = ['flashforward', '插叙', '预叙'];

/** #1374：类型筛选项 → i18n key（类型名） */
const TYPE_LABEL_KEYS: Record<TypeFilter, string> = {
  all: 'lib.tlFilterAll',
  normal: 'lib.tlFlag.normal',
  flashback: 'lib.tlFlag.flashback',
  flashforward: 'lib.tlFlag.flashforward',
};

const TYPE_OPTIONS: TypeFilter[] = ['all', 'normal', 'flashback', 'flashforward'];

/** #1374：事件 → 章刻度键（source_chapter_id 为空 → 未分章哨兵） */
function chapterKeyOf(ev: TimelineEventDTO): string {
  const raw = ev.source_chapter_id;
  return raw === null || raw === undefined || raw === '' ? NO_CHAPTER_KEY : String(raw);
}

/** #1374：事件类型分类（与后端 #1323 G6 同源词表；未标记自由文本（空串/「梦境」）→ 正叙） */
function classifyFlag(flag?: string | boolean | null): Exclude<TypeFilter, 'all'> {
  if (typeof flag !== 'string' || !flag) return 'normal';
  const lowered = flag.toLowerCase();
  if (FLASHBACK_WORDS.some((w) => lowered.includes(w))) return 'flashback';
  if (FLASHFORWARD_WORDS.some((w) => lowered.includes(w))) return 'flashforward';
  return 'normal';
}

/** #1323：一个章分组（键 = source_chapter_id 字符串，或未分章的哨兵键） */
interface ChapterGroup {
  key: string;
  events: TimelineEventDTO[];
}

/** #1323：按章刻度键分组（保持传入顺序 → 组内顺序即该序的顺序） */
function groupByChapter(events: TimelineEventDTO[]): ChapterGroup[] {
  const order: string[] = [];
  const buckets = new Map<string, TimelineEventDTO[]>();
  for (const ev of events) {
    const key = chapterKeyOf(ev);
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)!.push(ev);
  }
  return order.map((key) => ({ key, events: buckets.get(key)! }));
}

/**
 * #1374：叙事序按**章序**稳定排序（章内保持原相对顺序 —— narrative_position 升序）。
 * - 已登记章（chapterOrder 内）：按索引升序
 * - 未知章节（有 source_chapter_id 但不在 chapterOrder）：已登记章之后、「未分章」之前
 * - 未分章：轴末尾
 * chapterOrder 缺省/为空 → 原样返回（回退 #1323 的「事件首次出现顺序」组序）。
 */
function sortByChapterOrder(
  events: TimelineEventDTO[],
  chapterOrder?: string[],
): TimelineEventDTO[] {
  if (!chapterOrder || chapterOrder.length === 0) return events;
  const rankOfKey = new Map(chapterOrder.map((key, i) => [key, i] as const));
  const fallbackRank = Number.MAX_SAFE_INTEGER - 1;
  const rankOf = (ev: TimelineEventDTO): number => {
    const key = chapterKeyOf(ev);
    if (key === NO_CHAPTER_KEY) return Number.MAX_SAFE_INTEGER;
    return rankOfKey.get(key) ?? fallbackRank;
  };
  return events
    .map((ev, index) => ({ ev, index, rank: rankOf(ev) }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map((entry) => entry.ev);
}

export function TimelineView({
  projectId,
  eventTimeline,
  narrativeOrder,
  chapterTitles,
  chapterOrder,
  onEdit,
  onDelete,
}: TimelineViewProps) {
  const { t } = useI18n();
  const [view, setView] = useState<TimelineViewMode>('narrative');
  // #1374：筛选状态（客户端；对两序共用 —— 切序不丢筛选）
  const [chapterFilter, setChapterFilter] = useState<ChapterFilter>('all');
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');
  const [chapterPanelOpen, setChapterPanelOpen] = useState(false);
  const [typePanelOpen, setTypePanelOpen] = useState(false);

  // 双序切换 = 本地切换显示数组（零额外请求，T2/T3 契约）；narrative_order 空 → 回退 event_timeline（旧数据兜底）
  const base = useMemo(
    () => (view === 'world' ? eventTimeline : narrativeOrder.length > 0 ? narrativeOrder : eventTimeline),
    [view, eventTimeline, narrativeOrder],
  );

  // #1374：叙事序按章序（章节列表顺序）稳定排序；世界序保持后端 time_value 升序
  const sorted = useMemo(
    () => (view === 'world' ? base : sortByChapterOrder(base, chapterOrder)),
    [view, base, chapterOrder],
  );

  // #1374：筛选（在序内排序之后、分组之前；两序共用）
  const filtered = useMemo(
    () =>
      sorted.filter((ev) => {
        if (chapterFilter !== 'all' && chapterKeyOf(ev) !== chapterFilter) return false;
        if (typeFilter !== 'all' && classifyFlag(ev.timeline_flag) !== typeFilter) return false;
        return true;
      }),
    [sorted, chapterFilter, typeFilter],
  );

  // #1323：章分组（仅叙事序；一章一个刻度；组内顺序 = 章内叙事序）
  const groups = useMemo(
    () => (view === 'narrative' ? groupByChapter(filtered) : []),
    [view, filtered],
  );

  // #1374：章筛选项（全部章节 → 章序各章 → 未分章；order 缺省时回退「事件中出现的章」）
  const chapterOptions = useMemo(() => {
    const keys =
      chapterOrder && chapterOrder.length > 0
        ? chapterOrder
        : Array.from(new Set(sorted.map((ev) => chapterKeyOf(ev)))).filter(
            (key) => key !== NO_CHAPTER_KEY,
          );
    return ['all', ...keys, NO_CHAPTER_KEY];
  }, [chapterOrder, sorted]);

  /** #1374：章刻度 / 来源章胶囊 / 筛选标签共用的章名（未分章 / 未知章节占位） */
  const chapterLabel = (key: string): string =>
    key === NO_CHAPTER_KEY
      ? t('lib.tlGroupNone')
      : (chapterTitles?.[key] ?? t('lib.tlChapterUnknown'));

  const chapterFilterLabel =
    chapterFilter === 'all' ? t('lib.tlFilterAll') : chapterLabel(chapterFilter);
  const typeFilterLabel = t(TYPE_LABEL_KEYS[typeFilter]);

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

  /** #1374：筛选面板选项行（原型 .tl-fp-item 形态：勾选框 + 文本；选中 = accent 填充 + ✓） */
  const renderFilterOption = (
    testId: string,
    selected: boolean,
    label: string,
    onSelect: () => void,
  ) => (
    <button
      key={testId}
      type="button"
      data-testid={testId}
      aria-pressed={selected}
      className={cn(
        'flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12px] transition duration-150',
        selected ? 'bg-accent-weak font-medium text-accent' : 'text-ink hover:bg-surface-2',
      )}
      onClick={onSelect}
    >
      <span
        aria-hidden="true"
        className={cn(
          'flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-[4px] border',
          selected ? 'border-accent bg-accent text-accent-ink' : 'border-ink-3',
        )}
      >
        {selected ? <Check className="h-2.5 w-2.5" aria-hidden="true" /> : null}
      </span>
      {label}
    </button>
  );

  /** #1374：事件行（两序共用；差异 = 时间是否降级 + 是否渲染来源章胶囊） */
  const renderEventNode = (ev: TimelineEventDTO, opts: { showSrc: boolean }) => {
    const labels = axisLabels(ev, view, t);
    return (
      <li
        key={String(ev.id)}
        data-testid={`tl-axis-node-${ev.id}`}
        className="group relative flex items-center gap-3 pl-5 text-[12px]"
      >
        {/* 节点圆点（贴轴线上）：叙事序 = 空心（刻度在章上） / 世界序 = 实心（时间即刻度） */}
        <span
          aria-hidden="true"
          className={cn(
            'absolute left-0 top-1/2 h-[7px] w-[7px] -translate-y-1/2 rounded-full',
            view === 'world' ? 'bg-accent' : 'border border-accent bg-surface',
          )}
        />
        <span
          data-testid={`tl-axis-main-${ev.id}`}
          className={cn('shrink-0 font-medium tabular-nums', labels.dim ? 'text-ink-3' : 'text-ink')}
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
        {opts.showSrc ? (
          <span
            data-testid={`tl-src-${ev.id}`}
            className="shrink-0 rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-3"
          >
            {chapterLabel(chapterKeyOf(ev))}
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

        {/* #1374：按章筛选（全部章节 / 各章 / 未分章；单选点选） */}
        <div className="relative">
          <button
            type="button"
            data-testid="tl-filter-chapter"
            aria-expanded={chapterPanelOpen}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md border px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              chapterFilter !== 'all'
                ? 'border-accent bg-accent-weak text-accent'
                : 'border-line text-ink-2 hover:border-accent hover:text-accent',
            )}
            onClick={() => {
              setChapterPanelOpen((open) => !open);
              setTypePanelOpen(false);
            }}
          >
            <Filter className="h-3 w-3" aria-hidden="true" />
            {t('lib.tlFilterChapter', { label: chapterFilterLabel })}
            <ChevronDown className="h-3 w-3" aria-hidden="true" />
          </button>
          {chapterPanelOpen ? (
            <div
              data-testid="tl-filter-panel"
              className="absolute left-0 top-[calc(100%+6px)] z-50 max-h-72 min-w-[220px] overflow-y-auto rounded-lg border border-line bg-surface p-1.5 shadow-card"
            >
              <div className="px-2.5 pb-1 pt-1 text-[11px] text-ink-3">
                {t('lib.tlFilterChapterTitle')}
              </div>
              {chapterOptions.map((key) =>
                renderFilterOption(
                  `tl-fp-item-${key}`,
                  chapterFilter === key,
                  key === 'all' ? t('lib.tlFilterAllChapters') : chapterLabel(key),
                  () => {
                    setChapterFilter(key);
                    setChapterPanelOpen(false);
                  },
                ),
              )}
            </div>
          ) : null}
        </div>

        {/* #1374：按事件类型筛选（正叙/倒叙/插叙；词表对齐后端 #1323 G6） */}
        <div className="relative">
          <button
            type="button"
            data-testid="tl-filter-type"
            aria-expanded={typePanelOpen}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md border px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              typeFilter !== 'all'
                ? 'border-accent bg-accent-weak text-accent'
                : 'border-line text-ink-2 hover:border-accent hover:text-accent',
            )}
            onClick={() => {
              setTypePanelOpen((open) => !open);
              setChapterPanelOpen(false);
            }}
          >
            <Filter className="h-3 w-3" aria-hidden="true" />
            {t('lib.tlFilterType', { label: typeFilterLabel })}
            <ChevronDown className="h-3 w-3" aria-hidden="true" />
          </button>
          {typePanelOpen ? (
            <div
              data-testid="tl-filter-type-panel"
              className="absolute left-0 top-[calc(100%+6px)] z-50 min-w-[180px] rounded-lg border border-line bg-surface p-1.5 shadow-card"
            >
              <div className="px-2.5 pb-1 pt-1 text-[11px] text-ink-3">
                {t('lib.tlFilterTypeTitle')}
              </div>
              {TYPE_OPTIONS.map((key) =>
                renderFilterOption(`tl-tp-item-${key}`, typeFilter === key, t(TYPE_LABEL_KEYS[key]), () => {
                  setTypeFilter(key);
                  setTypePanelOpen(false);
                }),
              )}
            </div>
          ) : null}
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
          {view === 'narrative' ? t('lib.tlLegend.narrative') : t('lib.tlLegend.world')}
        </span>
      </div>

      {/* #1374 轴主体：叙事序 = 章刻度容器（tl-chgroup-<chapterId> + tl-chtick-<chapterId>）；
          世界序 = 世界内时间单轴（无章分组；行尾来源章胶囊）。每事件恰好渲染一次。 */}
      {filtered.length > 0 ? (
        <div data-testid="tl-axis" aria-label={t('lib.tlAxis')} className="space-y-3">
          <div data-testid="library-list" className="space-y-3">
            {view === 'narrative' ? (
              groups.map((group) => (
                <div
                  key={group.key}
                  data-testid={`tl-chgroup-${group.key}`}
                  className="relative rounded-lg border border-line bg-surface px-4 py-3 shadow-card"
                >
                  {/* 轴线本体：左侧竖线，贯穿本刻度组节点 */}
                  <span aria-hidden="true" className="absolute bottom-5 left-[7px] top-9 w-px bg-line" />
                  <div
                    data-testid={`tl-chtick-${group.key}`}
                    className={cn(
                      'relative mb-2 pl-5 text-[12px] font-medium',
                      group.key === NO_CHAPTER_KEY ? 'text-ink-2' : 'text-ink',
                    )}
                  >
                    {/* 刻度标记（◆ 菱形，区别于事件行圆点；未分章 = 灰刻度） */}
                    <span
                      aria-hidden="true"
                      className={cn(
                        'absolute left-0 top-1/2 h-2 w-2 -translate-y-1/2 rotate-45 rounded-[2px]',
                        group.key === NO_CHAPTER_KEY ? 'border border-ink-3 bg-surface' : 'bg-accent',
                      )}
                    />
                    {chapterLabel(group.key)}
                    <span className="ml-2 text-[11px] font-normal text-ink-3">
                      {t('lib.tlChCount', { n: group.events.length })}
                    </span>
                  </div>
                  <ol className="space-y-2">
                    {group.events.map((ev) => renderEventNode(ev, { showSrc: false }))}
                  </ol>
                </div>
              ))
            ) : (
              <div className="relative rounded-lg border border-line bg-surface px-4 py-3 shadow-card">
                <span aria-hidden="true" className="absolute bottom-5 left-[7px] top-5 w-px bg-line" />
                <ul className="space-y-2">
                  {filtered.map((ev) => renderEventNode(ev, { showSrc: true }))}
                </ul>
              </div>
            )}
          </div>
        </div>
      ) : base.length > 0 ? (
        // #1374：筛选后无匹配 → 轻空态（数据存在、被筛选条件排除）
        <div className="rounded-lg border border-line bg-surface px-4 py-8 text-center text-[13px] text-ink-2">
          {t('common.empty')}
        </div>
      ) : null}
    </div>
  );
}
