/**
 * #1564 世界序「刻度带 v2」视图（不定高刻度行 + 时间主轴 + 按刻度分页）。
 *
 * 【spec 依据】specs/f19-gui/timeline.md §1.1（世界序刻度带 v2）/ §2（刻度带 + 分页 + 未知区行）/ §3 N16
 *
 * 从 TimelineView 抽出：① 内聚（刻度带自成一体）；② 保住 `ci_cd/check_file_length.py` 的 900 行护栏。
 *
 * 形态要点（拍板 2026-10-10 / issue #1564）：
 * - **不定高**：每刻度一行，行高 = `BAND_ROW_PAD * 2 + 该刻度事件数 * BAND_ROW_H`（`layoutBandSpine`）
 * - **时间主轴**（`tl-band-main`）：刻度序 = 跨选中历 `to_global` 去重升序，作为定位 / 分页依据
 * - **按刻度分页**（#1599）：复用共享 `Pagination`（`testIdPrefix='tl-band-page'`）——
 *   分页单位仍是**时间刻度**，每页刻度数可选（档位 8 / 16 / 32 / 64，默认 8）
 * - **待确认区**（#1581）：原「未知区」退役 —— 未定事件不进正式表（故不在刻度带内），
 *   改由刻度带下方的 `TimelinePending` 承载（原文可读、可确认 / 丢弃、分页可达 100%）
 * - **底色**（#1565）：容器 = **页面底色 token**（`bg-bg`），保留边框 / 圆角 / `shadow-card`
 */
import { Fragment } from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import { cn } from '../lib/cn';
import {
  BAND_DEFAULT_COLOR,
  BAND_ROW_H,
  BAND_ROW_PAD,
  BAND_TICK_PAGE_SIZES,
  bandTickRows,
  layoutBandSpine,
  type BandLayout,
  type BandTickRow,
} from './timeline-band';
import { Pagination } from './Pagination';
import type { TimelineEventDTO, TimelineRowRef } from './TimelineView';
import { formatTickLabel, pickGranularity, type CalendarDateDTO } from './timeline-calendar-label';

/** 刻度行 → 该轴在该行的**后端换算结果**（#1589；null = 该轴未配历法 → 前端回落「N 日」） */
const calendarDateOf = (row: BandTickRow, axisKey: string): CalendarDateDTO | null =>
  row.events.find((item) => item.axisKey === axisKey)?.ev.calendar_date ?? null;

export interface TimelineBandProps {
  /** 世界序刻度带布局（`buildBandLayout` 产物） */
  band: BandLayout;
  /** 当前页码（0 基；越界由 `layoutBandSpine` 收敛） */
  page: number;
  /** 每页刻度数（#1599：受控；档位见 `BAND_TICK_PAGE_SIZES`，默认 `BAND_TICKS_PER_PAGE`） */
  pageSize: number;
  onPageChange: (page: number) => void;
  /** 每页刻度数变更（#1599；由父级同步重置到第 1 页） */
  onPageSizeChange: (pageSize: number) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
  /** 事件 → 来源章胶囊文案（未分章 / 未知章节占位由调用方兜底） */
  chapterLabelOf: (ev: TimelineEventDTO) => string;
  /** 行内「单事件检查」 */
  onCheckOne: (id: string | number) => void;
  onEdit?: (event: TimelineRowRef) => void;
  onDelete?: (event: TimelineRowRef) => void;
}

export function TimelineBand({
  band,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
  t,
  chapterLabelOf,
  onCheckOne,
  onEdit,
  onDelete,
}: TimelineBandProps) {
  const AX0 = 150;
  const AXDX = 104;
  const EVX = 352;
  const MAINX = 88;
  const geo = layoutBandSpine(bandTickRows(band), { page, pageSize });
  const xOf = (key: string): number => AX0 + band.axes.findIndex((axis) => axis.key === key) * AXDX;
  const colorOf = (key: string): string =>
    band.axes.find((axis) => axis.key === key)?.color ?? BAND_DEFAULT_COLOR;

  /** `top` 缺省 = 文档流（未知区滚动列表）；给值 = 绝对定位（刻度区） */
  const row = (ev: TimelineEventDTO, top?: number) => (
    <div
      key={String(ev.id)}
      data-testid={`tl-axis-node-${ev.id}`}
      className={cn(
        'flex h-6 items-center gap-2 rounded-md px-2 text-[12px] transition-colors duration-150 hover:bg-surface-2',
        top === undefined ? 'relative' : 'absolute',
      )}
      style={top === undefined ? undefined : { left: EVX, right: 18, top }}
    >
      <span className="min-w-0 flex-1 truncate text-ink">{ev.title ?? ''}</span>
      <span
        data-testid={`tl-src-${ev.id}`}
        className="shrink-0 rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-3"
      >
        {chapterLabelOf(ev)}
      </span>
      <button
        type="button"
        data-testid={`tl-check-one-${ev.id}`}
        className="shrink-0 rounded-md border border-line px-2.5 py-1 text-[11px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => void onCheckOne(ev.id)}
      >
        {t('lib.tlCheckOne')}
      </button>
      <button
        type="button"
        data-testid={`tl-edit-${ev.id}`}
        aria-label={`${t('lib.edit')} ${ev.title ?? ''}`}
        className="rounded p-1 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => onEdit?.(ev)}
      >
        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      <button
        type="button"
        data-testid={`tl-delete-${ev.id}`}
        aria-label={`${t('lib.delete')} ${ev.title ?? ''}`}
        className="rounded p-1 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => onDelete?.(ev)}
      >
        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  );

  return (
    <>
      <div
        data-testid="tl-band"
        className="relative rounded-lg border border-line bg-bg shadow-card"
        style={{ height: geo.height }}
      >
        {/* 历列头（轴名 + 计数） */}
        {band.axes.map((axis) => (
          <span
            key={axis.key}
            data-testid={`tl-band-head-${axis.key}`}
            className="absolute top-0.5 flex -translate-x-1/2 items-center gap-1.5 whitespace-nowrap text-[11.5px] font-medium text-ink"
            style={{ left: xOf(axis.key) }}
          >
            <span
              aria-hidden="true"
              className="h-[3px] w-[10px] rounded-sm"
              style={{ background: axis.color }}
            />
            {axis.isDefault ? t('lib.tlEraDefault') : axis.label}
            <span className="font-normal text-ink-3">{axis.count}</span>
          </span>
        ))}
        {/* 时间主轴（拍板 ③：定位 / 分页依据）：竖线 + 每行刻度点 + 横向参考线 */}
        <span
          aria-hidden="true"
          className="absolute -translate-x-1/2 text-[11px] text-ink-3"
          style={{ left: MAINX, top: 0 }}
        >
          {t('lib.tlBandMainAxis')}
        </span>
        <span
          data-testid="tl-band-main"
          aria-hidden="true"
          className="absolute w-[2px] rounded-sm bg-ink-3 opacity-45"
          style={{ left: MAINX, top: geo.spineTop, height: geo.spineHeight }}
        />
        {geo.placed.map((item, index) => (
          <Fragment key={`main-${index}`}>
            <span
              data-testid="tl-band-rowguide"
              aria-hidden="true"
              className="absolute border-t border-dashed border-line opacity-75"
              style={{ left: MAINX, right: 18, top: item.top + item.height / 2 }}
            />
            <span
              data-testid={`tl-band-mainnode-${index}`}
              aria-hidden="true"
              className="absolute h-[7px] w-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full border-[1.5px] border-ink-3 bg-bg"
              style={{ left: MAINX, top: item.top + item.height / 2 }}
            />
          </Fragment>
        ))}
        {/* 各历竖轴 + 本历刻度（同刻度只出现一次；`<i>` = 本历页内刻度序号） */}
        {band.axes.map((axis) => {
          const ticks = geo.placed.filter((item) => item.row.perAxis[axis.key] !== undefined);
          // #1589 / ADR-068 D4：粒度按**本页**相邻刻度自适应（相邻标签互不相同的最粗粒度）
          const granularity = pickGranularity(
            ticks.map((item) => calendarDateOf(item.row, axis.key)),
          );
          return (
            <Fragment key={`axis-${axis.key}`}>
              <span
                aria-hidden="true"
                data-testid={`tl-band-spine-${axis.key}`}
                className="absolute w-[2px] rounded-sm"
                style={{
                  left: xOf(axis.key),
                  top: geo.spineTop,
                  height: geo.spineHeight,
                  background: axis.color,
                  opacity: 0.42,
                }}
              />
              {ticks.map((item, index) => {
                const tick = item.row.perAxis[axis.key];
                const cy = item.top + item.height / 2;
                return (
                  <Fragment key={`tick-${axis.key}-${index}`}>
                    <span
                      aria-hidden="true"
                      data-testid={`tl-band-node-${axis.key}-${index}`}
                      className="absolute h-[9px] w-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 bg-bg"
                      style={{ left: xOf(axis.key), top: cy, borderColor: axis.color }}
                    />
                    <span
                      data-testid={`tl-band-tick-${axis.key}-${index}`}
                      className="absolute -translate-y-1/2 whitespace-nowrap bg-bg px-1 text-[11px] tabular-nums text-ink-3"
                      style={{ left: xOf(axis.key) + 9, top: cy }}
                    >
                      {formatTickLabel(
                        {
                          value: tick.value,
                          unit: tick.unit,
                          calendarDate: calendarDateOf(item.row, axis.key),
                        },
                        granularity,
                      )}
                    </span>
                  </Fragment>
                );
              })}
            </Fragment>
          );
        })}
        {/* 事件行：行内顺次错开（行高已含事件数） */}
        {geo.placed.map((item) =>
          item.row.events.map((rowItem, slot) => {
            const x = xOf(rowItem.axisKey);
            const y = item.top + BAND_ROW_PAD + slot * BAND_ROW_H;
            return (
              <Fragment key={String(rowItem.ev.id)}>
                <span
                  aria-hidden="true"
                  data-testid={`tl-band-link-${rowItem.ev.id}`}
                  className="absolute h-px"
                  style={{
                    left: x,
                    top: y + 12,
                    width: EVX - x - 6,
                    background: colorOf(rowItem.axisKey),
                    opacity: 0.2,
                  }}
                />
                {row(rowItem.ev, y)}
              </Fragment>
            );
          }),
        )}
        {/* #1581：「未知区」退役 —— 未定事件不进正式表（故不在刻度带内），
            改由刻度带下方的待确认区（TimelinePending）承载。 */}
      </div>
      {/* #1564：分页单位 = 时间刻度（拍板 ②）；#1599：改用共享 `Pagination`（形态同页内「待确认区」）
          —— 页 / 总页 / 总刻度四要素由组件呈现（「共 N 条」的 N = 总刻度数），每页刻度数可选 */}
      <div data-testid="tl-band-pager" className="mt-2">
        <Pagination
          className="justify-center"
          page={geo.page}
          pageSize={pageSize}
          total={geo.totalTicks}
          onPageChange={onPageChange}
          onPageSizeChange={onPageSizeChange}
          pageSizeOptions={BAND_TICK_PAGE_SIZES}
          testIdPrefix="tl-band-page"
        />
      </div>
    </>
  );
}
