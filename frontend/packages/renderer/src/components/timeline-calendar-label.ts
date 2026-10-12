/**
 * #1589 / ADR-068：刻度标签**历法换算显示**（纯函数；前端**不做日历数学** —— 换算结果由后端下发）。
 *
 * 契约（specs/f12-timeline/spec.md §2.10 · ADR-068 §2.1 S1/S5）:
 * - 粒度（D4）：取「本页相邻刻度标签**互不相同**」的最粗粒度（`y` → `ym` → `ymd`）；
 * - 文案：`[N 劫] [年号] X 年 [Y 月 [Z 日]]`（年号 / 纪元名是**数据**，不硬编码）；
 * - 无 `calendar_date` ⇒ 回落「**N 日**」整数（C1 同日归整，消掉 `0.79 日` 这类亚日小数）。
 */

/** 后端换算结果（`TimelineEvent.calendar_date`；纯数据，不含文案） */
export interface CalendarDateDTO {
  year: number;
  month: number;
  day: number;
  /** 纪元周期序号（`era_cycle` 生效时） */
  cycle?: number | null;
  /** 纪元名（如「劫」；仅 `cycle` 非空时有意义） */
  era_cycle_label?: string | null;
  /** 第 1 年年号（可空） */
  epoch_label?: string | null;
}

export type CalendarGranularity = 'y' | 'ym' | 'ymd';

const ORDER: CalendarGranularity[] = ['y', 'ym', 'ymd'];

/** 日期 → 标签文案（`[N 劫] [年号] X 年 [Y 月 [Z 日]]`） */
export function formatCalendarDate(date: CalendarDateDTO, granularity: CalendarGranularity): string {
  const cycle =
    date.cycle != null && date.era_cycle_label ? `${date.cycle} ${date.era_cycle_label} ` : '';
  const year = date.epoch_label ? `${date.epoch_label} ${date.year} 年` : `${date.year} 年`;
  const parts = [year];
  if (granularity !== 'y') parts.push(`${date.month} 月`);
  if (granularity === 'ymd') parts.push(`${date.day} 日`);
  return cycle + parts.join(' ');
}

/** 取「相邻标签互不相同」的最粗粒度（跳过无历法的刻度；全是 null → `ymd`） */
export function pickGranularity(
  dates: readonly (CalendarDateDTO | null | undefined)[],
): CalendarGranularity {
  const present = dates.filter((date): date is CalendarDateDTO => Boolean(date));
  for (const granularity of ORDER) {
    let distinct = true;
    for (let i = 1; i < present.length; i += 1) {
      if (formatCalendarDate(present[i], granularity) === formatCalendarDate(present[i - 1], granularity)) {
        distinct = false;
        break;
      }
    }
    if (distinct) return granularity;
  }
  return 'ymd';
}

/** 刻度取值（`bandTickRows` 的 `perAxis` 元素 + 后端换算结果） */
export interface TickLabelInput {
  value: number;
  unit: string;
  calendarDate?: CalendarDateDTO | null;
}

/** 刻度标签：有历法 → 换算文案；无 → 回落「N 日」整数 */
export function formatTickLabel(tick: TickLabelInput, granularity: CalendarGranularity): string {
  if (tick.calendarDate) return formatCalendarDate(tick.calendarDate, granularity);
  const days = Math.floor(tick.value);
  return tick.unit ? `${days} ${tick.unit}` : String(days);
}
