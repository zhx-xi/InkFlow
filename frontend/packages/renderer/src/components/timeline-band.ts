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
/** #1564：刻度带单位事件行高（px；= 事件行高）与行内上下留白 */
export const BAND_ROW_H = 24;
export const BAND_ROW_PAD = 4;
/** #1564：分页单位 = **时间刻度**（不是事件条数） */
export const BAND_TICKS_PER_PAGE = 8;
/** #1564：未知区列表高度上限（px）——画布高度不随未知事件数线性增长 */
export const BAND_UNK_MAX = 60;
/** #1564：刻度带内部几何（与 design/GUI/timeline/timeline.html 保持同值） */
const SPINE_TOP = 12;
const RULE_GAP = 10;
const UNK_HEAD_H = 24;
const BOT_PAD = 6;

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
/* ══════════════════ #1564 世界序刻度带 v2（不定高 + 时间主轴 + 按刻度分页） ══════════════════
   【spec 依据】specs/f19-gui/timeline.md §1.1（世界序刻度带 v2）/ §2（刻度带 + 分页 + 未知区行）/ §3 N16。

   拍板（issue #1564，2026-10-10）：① 每个刻度的高度 = 该刻度实际事件数（不定高）；
   ② 分页单位 = 时间刻度；③ 新增「时间主轴」= 定位 / 分页依据；④ 离群值不压扁其余刻度。

   ⚠️ 与 #1541 的差异：废止「画布高度 ∝ 事件总数 + 按 `to_global` 线性铺满」
   （该式把 `unknown` 计两次，且 252 事件（仅 12 有值）下画布 = 13,924px）。
   `to_global`（`era_value / era_scale`）口径不变——仍用于**刻度序**与跨历对齐。 */

/** 一个刻度行 = 时间主轴上的一格（`g` 去重；含跨选中历的本行事件） */
export interface BandTickRow {
  /** 全局时间标量（`to_global`） */
  g: number;
  /** 本行事件（跨选中历；同刻度顺次错开 `slot`） */
  events: BandRow[];
  /** 本行事件数（跨选中历）——行高的唯一依据（拍板 ①） */
  count: number;
  /** 各历在本刻度的本地刻度（`value` / `unit` 用于显示；键 = 轴键） */
  perAxis: Record<string, { value: number; unit: string; label: string }>;
  /** 主轴刻度文案（轴族顺序里首个在本行有刻度的历） */
  label: string;
}

/** 本页已定位的刻度行 */
export interface BandPlacedRow {
  row: BandTickRow;
  top: number;
  height: number;
}

/** 刻度带几何（含分页结果） */
export interface BandSpineLayout {
  /** 归一后的页码（0 基，越界收敛） */
  page: number;
  pageCount: number;
  totalTicks: number;
  /** 本页刻度行（含 top / height） */
  placed: BandPlacedRow[];
  /** 主轴 / 竖轴顶端 y 与高度 */
  spineTop: number;
  spineHeight: number;
  /** 未知区：虚线位置 / 列表顶端 / 列表高度 */
  unknownTop: number;
  unknownListTop: number;
  unknownListHeight: number;
  unknownHeight: number;
  /** 画布总高（unknown 只计一次） */
  height: number;
}

/** 布局 → 时间主轴刻度行（`g` 去重升序；`label` 取轴族首个有本刻度的历）。 */
export function bandTickRows(layout: BandLayout): BandTickRow[] {
  const byG = new Map<number, BandTickRow>();
  for (const row of layout.rows) {
    let tick = byG.get(row.g);
    if (tick === undefined) {
      tick = { g: row.g, events: [], count: 0, perAxis: {}, label: '' };
      byG.set(row.g, tick);
    }
    tick.events.push(row);
    tick.count += 1;
  }
  for (const axis of layout.axes) {
    for (const tick of axis.ticks) {
      const row = byG.get(tick.g);
      if (row === undefined) continue;
      row.perAxis[axis.key] = {
        value: tick.value,
        unit: tick.unit,
        label: tick.unit ? `${tick.value} ${tick.unit}` : String(tick.value),
      };
    }
  }
  const rows = Array.from(byG.values()).sort((a, b) => a.g - b.g);
  for (const row of rows) {
    const first = layout.axes.find((axis) => row.perAxis[axis.key] !== undefined);
    row.label = first === undefined ? '' : row.perAxis[first.key].label;
  }
  return rows;
}

/**
 * 主轴刻度行 → 画布几何（拍板 ①②③④）。
 *
 * - **不定高**：`height = BAND_ROW_PAD * 2 + max(1, count) * BAND_ROW_H`
 * - **纵向位置 = 刻度序号**（等距堆叠）→ 离群值只多占一行，不改动其它行
 * - **分页**：每页 `BAND_TICKS_PER_PAGE` 个刻度（`page` 越界收敛到有效范围）
 * - **未知区**：独立于刻度区；高度上限 `BAND_UNK_MAX` 且截到整行 → 不随未知事件数线性增长
 */
export function layoutBandSpine(
  tickRows: BandTickRow[],
  unknownCount: number,
  opts?: { page?: number; pageSize?: number },
): BandSpineLayout {
  const pageSize = opts?.pageSize ?? BAND_TICKS_PER_PAGE;
  const totalTicks = tickRows.length;
  const pageCount = Math.max(1, Math.ceil(totalTicks / pageSize));
  const page = Math.min(Math.max(opts?.page ?? 0, 0), pageCount - 1);
  const pageRows = tickRows.slice(page * pageSize, page * pageSize + pageSize);

  let cursor = SPINE_TOP;
  const placed: BandPlacedRow[] = pageRows.map((row) => {
    const height = BAND_ROW_PAD * 2 + Math.max(1, row.count) * BAND_ROW_H;
    const item = { row, top: cursor, height };
    cursor += height;
    return item;
  });
  const timelineBottom = cursor;

  const rawListHeight = Math.min(unknownCount * BAND_ROW_H, BAND_UNK_MAX);
  const unknownListHeight =
    unknownCount > 0 ? Math.max(BAND_ROW_H, Math.floor(rawListHeight / BAND_ROW_H) * BAND_ROW_H) : 0;
  const unknownTop = timelineBottom + RULE_GAP;
  const unknownListTop = unknownTop + UNK_HEAD_H;
  const unknownHeight = unknownCount > 0 ? RULE_GAP + UNK_HEAD_H + unknownListHeight + 8 : 0;

  return {
    page,
    pageCount,
    totalTicks,
    placed,
    spineTop: SPINE_TOP,
    spineHeight: Math.max(0, timelineBottom - SPINE_TOP),
    unknownTop,
    unknownListTop,
    unknownListHeight,
    unknownHeight,
    height: timelineBottom + unknownHeight + BOT_PAD,
  };
}
