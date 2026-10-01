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
};

export const timelineEraEn: Record<string, string> = {
  'lib.tlAxisPicker': 'Era axes:',
  'lib.tlEraDefault': 'No era',
  'lib.tlLegend.worldEras': 'Axis = era · each era has its own time scale · tick to choose which axes to show',
  'lib.create.era': 'Era',
  'lib.create.eraValue': 'Value in era',
};
