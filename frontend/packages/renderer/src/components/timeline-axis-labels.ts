/**
 * #1323/#1374 时间线轴标签派生（纯函数，独立于 TimelineView 组件文件——
 * 避免 react-refresh/only-export-components 告警，并便于单测直调）。
 *
 * #1374 双序轴向语义分流（issue #1374 拍板「A 拆半」+ specs/f19-gui/timeline.md §1.1）：
 * - **叙事序**：轴刻度 = **章**（章刻度 `tl-chtick-<chapterId>` 承载真实章节标题）；
 *   世界内时间降为**行内小字**（ink-3 降级，`dim: true`）
 * - **世界序**：轴刻度 = **世界内时间**（行内主轴本身即刻度，`dim: false`）
 * 旧实现 `void view`（view 被显式忽略）→ 两序轴完全相同（#1374 现象根因之一）。
 *
 * 🔴 #1323 G2（保留不破）：停用「第{n}章」拼接。`narrative_position` 是**单一线性序号**
 * （`domain/models/timeline.py:158`；`specs/f12-timeline/spec.md:91` 明确「不携带
 * 『第几章第几段』的章节语义」），把它拼成「第 N 章」是语义错用 —— DB 实测 215 条
 * 只有 34 个不同位置值，同一「第 7 章」会重复 10 次。**真实章节标题**改由
 * `source_chapter_id` → `chapterTitles` 映射给出，呈现在**章刻度**（叙事序，见 TimelineView）
 * 或**来源章胶囊**（世界序，`tl-src-<id>`）。
 *
 * 回退链（两序一致）：
 * - 世界内时间：`time_display` → `time_value + time_unit` → 「未知」占位
 * - 副标记（`sub`）：保留槽位但不承载章号（章信息由章刻度 / 来源章胶囊承载）
 */
import type { TimelineEventDTO } from './TimelineView';

export type TimelineViewMode = 'narrative' | 'world';

/** #1374：轴标签（main = 世界内时间文本；dim = 叙事序下降级为行内小字） */
export interface TimelineAxisLabel {
  /** 主轴文本（世界内时间；叙事序下为行内小字、世界序下即轴刻度） */
  main: string;
  /** 副标记（保留槽位；当前两序均不承载章号，章信息由章刻度 / 来源章胶囊承载） */
  sub: string;
  /** #1374：是否降级渲染（叙事序 = true → ink-3 小字；世界序 = false → 轴刻度态） */
  dim: boolean;
}

export function axisLabels(
  ev: TimelineEventDTO,
  view: TimelineViewMode,
  t: (key: string, params?: Record<string, string | number>) => string,
): TimelineAxisLabel {
  const timeText = ev.time_display
    ? ev.time_display
    : ev.time_value !== null && ev.time_value !== undefined
      ? `${ev.time_value}${ev.time_unit ?? ''}`
      : t('lib.tlTimeUnknown');
  // #1374：两序分流 —— 叙事序轴在「章」刻度上（时间降级为行内小字）；
  // 世界序轴即世界内时间（行内主轴 = 刻度本体）。
  if (view === 'narrative') {
    return { main: timeText, sub: '', dim: true };
  }
  return { main: timeText, sub: '', dim: false };
}
