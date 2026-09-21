/**
 * #1323 时间线轴标签派生（纯函数，独立于 TimelineView 组件文件——
 * 避免 react-refresh/only-export-components 告警，并便于单测直调）。
 *
 * 双序「主轴 + 副标记」映射：
 * - 世界序：主轴 = 世界内时间；副标记 = 章内序（章分组内仍有用）
 * - 叙事序：主轴 = 世界内时间；副标记 = 无
 *
 * 🔴 #1323 G2 修正：**停用 `lib.tlChapter`（「第{n}章」）**。
 * `narrative_position` 是**单一线性序号**（`domain/models/timeline.py:158`；
 * `specs/f12-timeline/spec.md:91` 明确「不携带『第几章第几段』的章节语义」），
 * 把它拼成「第 N 章」是语义错用 —— DB 实测 215 条只有 34 个不同位置值，
 * 同一「第 7 章」会重复 10 次。**真实章节标题**改由 `source_chapter_id` →
 * `chapterTitles` 映射给出，呈现在**章分组 header**（见 TimelineView）。
 *
 * 回退链：
 * - 世界内时间：`time_display` → `time_value + time_unit` → 「未知」占位
 * - 主轴：世界内时间（两序一致，时间始终是有信息量的那一维）
 * - 副标记：叙事序下不再渲染章号；世界序下同样不渲染（章节信息已在分组 header）
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
  void view;
  // #1323：副标记留空 —— 章节信息由章分组 header 承载（不再由 narrative_position 拼章号）
  return { main: timeText, sub: '' };
}
