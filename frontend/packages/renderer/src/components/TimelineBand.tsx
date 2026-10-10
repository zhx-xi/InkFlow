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
 * - **按刻度分页**：`tl-band-pager`（`BAND_TICKS_PER_PAGE` 个刻度/页）
 * - **未知区**（`tl-band-unknown`）：块底独立区 + 限高内滚动（全部事件仍在 DOM；画布高度不随其增长）
 * - **底色**（#1565）：容器 = **页面底色 token**（`bg-bg`），保留边框 / 圆角 / `shadow-card`
 */
import { Fragment } from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import { cn } from '../lib/cn';
import {
  BAND_DEFAULT_COLOR,
  BAND_ROW_H,
  BAND_ROW_PAD,
  BAND_TICKS_PER_PAGE,
  bandTickRows,
  layoutBandSpine,
  type BandLayout,
} from './timeline-band';
import type { TimelineEventDTO, TimelineRowRef } from './TimelineView';

export interface TimelineBandProps {
  /** 世界序刻度带布局（`buildBandLayout` 产物） */
  band: BandLayout;
  /** 当前页码（0 基；越界由 `layoutBandSpine` 收敛） */
  page: number;
  onPageChange: (page: number) => void;
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
  onPageChange,
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
  const geo = layoutBandSpine(bandTickRows(band), band.unknown.length, { page });
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
        className="relative rounded-lg border border-line bg-surface shadow-card"
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
              className="absolute h-[7px] w-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full border-[1.5px] border-ink-3 bg-surface"
              style={{ left: MAINX, top: item.top + item.height / 2 }}
            />
          </Fragment>
        ))}
        {/* 各历竖轴 + 本历刻度（同刻度只出现一次；`<i>` = 本历页内刻度序号） */}
        {band.axes.map((axis) => {
          const ticks = geo.placed.filter((item) => item.row.perAxis[axis.key] !== undefined);
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
                      className="absolute h-[9px] w-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 bg-surface"
                      style={{ left: xOf(axis.key), top: cy, borderColor: axis.color }}
                    />
                    <span
                      data-testid={`tl-band-tick-${axis.key}-${index}`}
                      className="absolute -translate-y-1/2 whitespace-nowrap bg-surface px-1 text-[11px] tabular-nums text-ink-3"
                      style={{ left: xOf(axis.key) + 9, top: cy }}
                    >
                      {tick.unit ? `${tick.value} ${tick.unit}` : tick.value}
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
        {/* 时间未知：块底独立区（限高内滚动；全部事件仍在 DOM，画布高度不随其增长） */}
        {band.unknown.length > 0 ? (
          <>
            <span
              aria-hidden="true"
              data-testid="tl-band-unknown"
              className="absolute left-0 right-0 border-t border-dashed border-line"
              style={{ top: geo.unknownTop }}
            />
            <span
              data-testid="tl-band-unknown-head"
              className="absolute flex items-center gap-1 text-[11.5px] text-ink-2"
              style={{ left: MAINX + 4, top: geo.unknownTop + 4 }}
            >
              {t('lib.tlTimeUnknown')}
              <span className="tabular-nums text-ink-3">{band.unknown.length}</span>
            </span>
            <div
              data-testid="tl-band-unknown-list"
              className="absolute overflow-y-auto"
              style={{ left: EVX, right: 18, top: geo.unknownListTop, height: geo.unknownListHeight }}
            >
              {band.unknown.map((ev) => row(ev))}
            </div>
          </>
        ) : null}
      </div>
      {/* #1564：分页单位 = 时间刻度（拍板 ②） */}
      <div
        data-testid="tl-band-pager"
        className="mt-2 flex items-center justify-center gap-3 text-[12px] text-ink-2"
      >
        <button
          type="button"
          data-testid="tl-band-page-prev"
          disabled={geo.page === 0}
          className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink-2"
          onClick={() => onPageChange(Math.max(0, geo.page - 1))}
        >
          {t('pagination.page.prev')}
        </button>
        <span data-testid="tl-band-pageinfo" className="tabular-nums">
          {t('lib.tlBandPageInfo', {
            page: geo.page + 1,
            pages: geo.pageCount,
            size: BAND_TICKS_PER_PAGE,
            total: geo.totalTicks,
          })}
        </span>
        <button
          type="button"
          data-testid="tl-band-page-next"
          disabled={geo.page >= geo.pageCount - 1}
          className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink-2"
          onClick={() => onPageChange(Math.min(geo.pageCount - 1, geo.page + 1))}
        >
          {t('pagination.page.next')}
        </button>
      </div>
    </>
  );
}
