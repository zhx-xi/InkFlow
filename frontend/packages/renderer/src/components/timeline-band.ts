/**
 * #1541 世界序多历共存「单块刻度带」派生（纯函数，独立于 TimelineView 组件文件——
 * 避免 react-refresh/only-export-components 告警，并便于单测直调）。
 *
 * 【spec 依据】specs/f19-gui/timeline.md §1.1（世界序刻度带）/ §3 N15
 *            + specs/f12-timeline/spec.md §2.8 E11（`to_global = era_value / era_scale`，ADR-065 / #1411）。
 *
 * 纵向口径 = 全局时间 `to_global`：
 * - **纪元轴**（`era` trim 非空）：`era_value / era_scale`（`era_scale <= 0` / 缺失 → 按 `1` 处置，与 #1411 一致）
 * - **默认轴**（`era` 空）：`time_value`（归一日尺度由后端排序保证，前端仅取相对位置）
 * - 无值 → `null`（时间未知 → 归「未知」区，不参与刻度 / 比例）
 *
 * ⚠️ 本模块**只做定位换算**，不回写 `time_value`（spec §12 判定层只读投影）。
 */

import { eraKeyOf, type TimelineEraAxis } from './timeline-era-axes';
import type { TimelineEventDTO } from './TimelineView';

/** 历配色（按轴族顺序循环；朱砂 / 黛蓝 / 赭 / 苔——对齐 InkFlow 墨韵调，非品牌色） */
export const BAND_COLORS = ['#b3462f', '#34607f', '#8a6a2f', '#5b7f4f'];
/** 默认轴（未分纪元）配色：中性灰（非「历」，不参与配色循环） */
export const BAND_DEFAULT_COLOR = '#7a7a7a';
/** 同刻度多事件的错开步长（px） */
export const BAND_ROW_GAP = 28;

/** 事件 → 全局时间标量（`to_global`；`null` = 时间未知）。 */
export function bandGlobal(ev: TimelineEventDTO): number | null {
  const era = typeof ev.era === 'string' ? ev.era.trim() : '';
  if (era !== '') {
    const raw = typeof ev.era_scale === 'number' && Number.isFinite(ev.era_scale) ? ev.era_scale : 1;
    const scale = raw > 0 ? raw : 1;
    const value = typeof ev.era_value === 'number' && Number.isFinite(ev.era_value) ? ev.era_value : null;
    return value === null ? null : value / scale;
  }
  return typeof ev.time_value === 'number' && Number.isFinite(ev.time_value) ? ev.time_value : null;
}

/** 事件 → 轴上刻度的**本地**时间值（纪元轴 = `era_value`；默认轴 = `time_value`）。 */
function bandLocal(ev: TimelineEventDTO): number | null {
  const era = typeof ev.era === 'string' ? ev.era.trim() : '';
  if (era !== '') return typeof ev.era_value === 'number' && Number.isFinite(ev.era_value) ? ev.era_value : null;
  return typeof ev.time_value === 'number' && Number.isFinite(ev.time_value) ? ev.time_value : null;
}

/** 一条历竖轴（列头 + 刻度，刻度按 `g` 去重升序）。 */
export interface BandAxis {
  key: string;
  label: string;
  isDefault: boolean;
  count: number;
  color: string;
  ticks: BandTick[];
}

/** 一个刻度（`value` = 本地时间值用于显示；`g` = 全局时间标量用于纵向定位）。 */
export interface BandTick {
  value: number;
  unit: string;
  g: number;
}

/** 一条事件行（`slot` = 同刻度内的错开序号）。 */
export interface BandRow {
  ev: TimelineEventDTO;
  axisKey: string;
  g: number;
  slot: number;
}

/** 刻度带布局（调用方传入的 `events` 应已过滤到选中历）。 */
export interface BandLayout {
  axes: BandAxis[];
  rows: BandRow[];
  unknown: TimelineEventDTO[];
  gmax: number;
}

/**
 * 派生刻度带布局。
 *
 * - `events` 中**不属于** `axes`（调用方 = 选中历）的事件被忽略（不渲染）
 * - 每历刻度 = 该历事件 `g` 值**去重升序**（同刻度只出现一次）
 * - 事件行按 `g` 升序；同 `g`（`Math.round` 同桶）顺次错开 `slot` = 0,1,2…
 * - 时间未知（`g === null`）事件收进 `unknown`
 * - `gmax` = 已知 `g` 最大值；无已知 `g` → `1`
 */
export function buildBandLayout(events: TimelineEventDTO[], axes: TimelineEraAxis[]): BandLayout {
  const bands: BandAxis[] = axes.map((axis, index) => ({
    key: axis.key,
    label: axis.label,
    isDefault: axis.isDefault,
    count: axis.count,
    color: axis.isDefault ? BAND_DEFAULT_COLOR : BAND_COLORS[index % BAND_COLORS.length],
    ticks: [],
  }));
  const byKey = new Map(bands.map((band) => [band.key, band]));
  const timed: { ev: TimelineEventDTO; axisKey: string; g: number }[] = [];
  const unknown: TimelineEventDTO[] = [];
  for (const ev of events) {
    const axisKey = eraKeyOf(ev);
    if (!byKey.has(axisKey)) continue;
    const g = bandGlobal(ev);
    if (g === null) {
      unknown.push(ev);
      continue;
    }
    timed.push({ ev, axisKey, g });
  }
  timed.sort((a, b) => a.g - b.g);
  for (const item of timed) {
    const band = byKey.get(item.axisKey)!;
    if (band.ticks.some((tick) => tick.g === item.g)) continue;
    band.ticks.push({
      value: bandLocal(item.ev) as number,
      unit: item.ev.time_unit ?? '',
      g: item.g,
    });
  }
  const rows: BandRow[] = [];
  const seen: Record<number, number> = {};
  for (const item of timed) {
    const bucket = Math.round(item.g);
    seen[bucket] = (seen[bucket] ?? 0) + 1;
    rows.push({ ev: item.ev, axisKey: item.axisKey, g: item.g, slot: seen[bucket] - 1 });
  }
  const max = timed.length > 0 ? Math.max(...timed.map((item) => item.g)) : 0;
  return { axes: bands, rows, unknown, gmax: max > 0 ? max : 1 };
}
