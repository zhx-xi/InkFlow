/**
 * #1353 时间线纪元轴族派生（纯函数，独立于 TimelineView 组件文件——
 * 避免 react-refresh/only-export-components 告警，并便于单测直调）。
 *
 * 【spec 依据】specs/f12-timeline/spec.md §2.8（承载键 E1/E2 + 默认轴 E5）
 *            + specs/f19-gui/timeline.md §1.1（世界序 = 纪元轴族 + 轴选择器）。
 *
 * 承载约定（v1.4 / #1410：**正式列**，ADR-065；旧 `extra.era` / `extra.era_value` 为 v1.3 遗留快照，不再读取）：
 * - `era`（非空字符串，去空白）→ 该事件属于「<轴名>」轴；
 *   空 / 缺失 / 非字符串 → 归 **默认轴**（`DEFAULT_ERA_KEY`，R6-4：旧的单标量时间线）
 * - `era_value`（有限数值）→ 轴内值；非数值 / 缺失 → null（轴内值未知）
 */
import type { TimelineEventDTO } from './TimelineView';

/** 默认轴哨兵键（R6-4：无纪元的旧事件归此轴；GUI testid / 0.16.0 契约锚点）。 */
export const DEFAULT_ERA_KEY = '__none__';

/** 一条纪元轴（轴名或默认轴哨兵 + 计数 + 排序/标签元数据）。 */
export interface TimelineEraAxis {
  /** 纪元轴名，或默认轴哨兵 DEFAULT_ERA_KEY */
  key: string;
  /** 展示名（纪元轴 = 轴名；默认轴 = '' 由组件用 i18n 兜底） */
  label: string;
  /** 轴内事件数 */
  count: number;
  /** 是否默认轴（R6-4：旧的单标量时间线） */
  isDefault: boolean;
}

/** 事件 → 纪元轴名（正式列 `era` 非空字符串（trim）→ 轴名；否则 null）。 */
export function eraNameOf(ev: TimelineEventDTO): string | null {
  const raw = ev.era;
  if (typeof raw !== 'string') return null;
  const trimmed = raw.trim();
  return trimmed === '' ? null : trimmed;
}

/** 事件 → 轴键（无纪元 → 默认轴哨兵）。 */
export function eraKeyOf(ev: TimelineEventDTO): string {
  return eraNameOf(ev) ?? DEFAULT_ERA_KEY;
}

/** 事件 → 轴内值（正式列 `era_value` 有限数值 → number；否则 null）。 */
export function eraValueOf(ev: TimelineEventDTO): number | null {
  const raw = ev.era_value;
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
}

/**
 * 派生轴族：按**轴在事件流中首次出现的顺序**返回（**仅含有事件的轴**）；
 * 空事件集 → `[]`；默认轴与纪元轴并列（R6-4：不丢事件）。
 */
export function deriveEraAxes(events: TimelineEventDTO[]): TimelineEraAxis[] {
  const order: string[] = [];
  const buckets = new Map<string, { label: string; count: number; isDefault: boolean }>();
  for (const ev of events) {
    const name = eraNameOf(ev);
    const key = name ?? DEFAULT_ERA_KEY;
    const bucket = buckets.get(key);
    if (bucket === undefined) {
      buckets.set(key, { label: name ?? '', count: 1, isDefault: name === null });
      order.push(key);
    } else {
      bucket.count += 1;
    }
  }
  return order.map((key) => {
    const bucket = buckets.get(key)!;
    return { key, label: bucket.label, count: bucket.count, isDefault: bucket.isDefault };
  });
}

/** 主力轴 = 事件数最多的轴（**并列取先出现**）；空轴族 → null。 */
export function primaryEraKey(axes: TimelineEraAxis[]): string | null {
  let best: TimelineEraAxis | null = null;
  for (const axis of axes) {
    if (best === null || axis.count > best.count) best = axis;
  }
  return best === null ? null : best.key;
}

/** 轴内排序：`era_value` 升序、缺失（null）排末尾、**稳定**且**不改原数组**。 */
export function sortByEraValue(events: TimelineEventDTO[]): TimelineEventDTO[] {
  return events
    .map((ev, index) => ({ ev, index, value: eraValueOf(ev) }))
    .sort((a, b) => {
      if (a.value === null && b.value === null) return a.index - b.index;
      if (a.value === null) return 1;
      if (b.value === null) return -1;
      return a.value - b.value || a.index - b.index;
    })
    .map((entry) => entry.ev);
}

/**
 * #1467 世界序组内**时间刻度**文案（specs/f19-gui/timeline.md §1.1 / §3 N14）。
 *
 * 回退链：`time_display`（trim 非空）原样 → 「`era_value` + `time_unit`」→ 「`time_value` + `time_unit`」→ null。
 * - **轴名不进刻度文案**：轴名只出现在组头（泳道头），行内不再重复（废除 #1353 的「轴名 + 轴内值」回退）。
 * - null = 无任何时间信息 → 调用方用 i18n `lib.tlTimeUnknown` 兜底（保证同组「未知」事件合并到一个节点）。
 * - **不做跨轴换算**：`era_scale`（流速比）不参与本函数（换算归 #1411）。
 */
export function timeScaleText(ev: TimelineEventDTO): string | null {
  const display = typeof ev.time_display === 'string' ? ev.time_display.trim() : '';
  if (display !== '') return display;
  const unit = typeof ev.time_unit === 'string' ? ev.time_unit : '';
  const raw = eraValueOf(ev);
  const value = raw !== null ? raw : typeof ev.time_value === 'number' && Number.isFinite(ev.time_value) ? ev.time_value : null;
  return value === null ? null : `${value}${unit}`;
}

/** 一个时间节点（刻度文案或 null = 未知；同刻度事件合集）。 */
export interface TimelineTimeNode {
  /** 刻度文案；null = 时间未知（组件用 `lib.tlTimeUnknown` 兜底） */
  key: string | null;
  /** 该刻度下的事件（保持传入顺序） */
  events: TimelineEventDTO[];
}

/**
 * #1467 组内按**时间刻度**分层：同刻度事件合并为一个时间节点（`key` 首次出现顺序），
 * **不改原数组**、不重排（调用方先 `sortByEraValue`）。刻度缺失的事件合并到同一个 `key === null` 节点。
 */
export function groupByTime(events: TimelineEventDTO[]): TimelineTimeNode[] {
  const order: (string | null)[] = [];
  const buckets = new Map<string | null, TimelineEventDTO[]>();
  for (const ev of events) {
    const key = timeScaleText(ev);
    const bucket = buckets.get(key);
    if (bucket === undefined) {
      buckets.set(key, [ev]);
      order.push(key);
    } else {
      bucket.push(ev);
    }
  }
  return order.map((key) => ({ key, events: buckets.get(key)! }));
}
