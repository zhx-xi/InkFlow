/**
 * #1301 时间线轴标签派生（纯函数，独立于 TimelineView 组件文件——
 * 避免 react-refresh/only-export-components 告警，并便于单测直调）。
 *
 * 双序「主轴 + 副标记」映射（#1301 用户原话；spec f12:621/702 · f43:773 · f19:34）：
 * - 世界序：主轴 = 世界内时间；副标记 = 章节（narrative_position）
 * - 叙事序：主轴 = 章节；副标记 = 世界内时间
 *
 * 回退链：
 * - 世界内时间：`time_display` → `time_value + time_unit` → 「未知」占位
 * - 章节：`第{n}章`（narrative_position）→ 空串（无叙事位置则不渲染副标记）
 */
import type { TimelineEventDTO } from './TimelineView';

export type TimelineViewMode = 'narrative' | 'world';

export function axisLabels(
  ev: TimelineEventDTO,
  view: TimelineViewMode,
  t: (key: string, params?: Record<string, string | number>) => string,
): { main: string; sub: string } {
  const timeText = ev.time_display
    ? ev.time_display
    : ev.time_value !== null && ev.time_value !== undefined
      ? `${ev.time_value}${ev.time_unit ?? ''}`
      : t('lib.tlTimeUnknown');
  const chapterText =
    ev.narrative_position !== null && ev.narrative_position !== undefined
      ? t('lib.tlChapter', { n: ev.narrative_position })
      : '';
  return view === 'world'
    ? { main: timeText, sub: chapterText }
    : { main: chapterText, sub: timeText };
}
