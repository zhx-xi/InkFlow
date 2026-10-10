/**
 * #1353 时间线纪元轴族文案域（zh/en）。
 *
 * 独立成文件而非写入 zh.ts / en.ts：后两者基线已贴 900 行护栏
 * （ci_cd/check_file_length.py），新增 5 键即触线；同 foreshadow-filter.ts 先例。
 */
export const timelineEraZh: Record<string, string> = {
  'lib.tlAxisPicker': '纪元轴：',
  'lib.tlEraDefault': '未分纪元',
  'lib.tlLegend.worldEras': '轴=纪元 · 每轴独立时间刻度 · 勾选控制显示哪几条轴',
  'lib.create.era': '纪元',
  'lib.create.eraValue': '纪元内数值',
  /* #1564 世界序刻度带 v2（不定高 + 时间主轴 + 按刻度分页）—— 上/下页文案复用 pagination.page.prev/next */
  'lib.tlBandMainAxis': '时间主轴',
  'lib.tlBandPageInfo': '第 {page} / {pages} 页 · 每页 {size} 刻度 · 共 {total} 刻度',
};

export const timelineEraEn: Record<string, string> = {
  'lib.tlAxisPicker': 'Era axes:',
  'lib.tlEraDefault': 'No era',
  'lib.tlLegend.worldEras': 'Axis = era · each era has its own time scale · tick to choose which axes to show',
  'lib.create.era': 'Era',
  'lib.create.eraValue': 'Value in era',
  'lib.tlBandMainAxis': 'Main axis',
  'lib.tlBandPageInfo': 'Page {page} / {pages} · {size} ticks/page · {total} ticks',
};
