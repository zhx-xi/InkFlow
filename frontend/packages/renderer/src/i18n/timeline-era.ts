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
  /* #1564 世界序刻度带 v2（不定高 + 时间主轴 + 按刻度分页）；
     #1599 起翻页 / 每页刻度数 / 页码信息**全部复用公共分页组件**（`pagination.page.*`），本域只留主轴标题 */
  'lib.tlBandMainAxis': '时间主轴',
  /* #1581 待确认区（原「未知区」退役） */
  'lib.tlPendTitle': '待确认时间',
  'lib.tlPendCount': '{n} 条',
  'lib.tlPendHint': '机器未定时间 → 不进时间轴；补时间后确认转正，或丢弃（原文永不留失）',
  'lib.tlPendColRaw': '原文时间',
  'lib.tlPendColEvent': '事件',
  'lib.tlPendColSource': '来源',
  'lib.tlPendColTime': '时间（可填）',
  'lib.tlPendColReason': '未定原因',
  'lib.tlPendColActions': '操作',
  'lib.tlPendNoRaw': '（原文无时间线索）',
  'lib.tlPendPlaceholder': '补时间',
  'lib.tlPendConfirm': '确认',
  'lib.tlPendDiscard': '丢弃',
  'lib.tlPendReasonFallback': '存量未定时间（未记录原因）',
  'lib.tlPendUnit.day': '日',
  'lib.tlPendUnit.year': '年',
  'lib.tlPendUnit.month': '月',
};

export const timelineEraEn: Record<string, string> = {
  'lib.tlAxisPicker': 'Era axes:',
  'lib.tlEraDefault': 'No era',
  'lib.tlLegend.worldEras': 'Axis = era · each era has its own time scale · tick to choose which axes to show',
  'lib.create.era': 'Era',
  'lib.create.eraValue': 'Value in era',
  'lib.tlBandMainAxis': 'Main axis',
  'lib.tlPendTitle': 'Pending confirmation',
  'lib.tlPendCount': '{n} items',
  'lib.tlPendHint':
    'Time not resolved by machine → kept off the timeline; fill a time then confirm, or discard (original text is never lost)',
  'lib.tlPendColRaw': 'Original',
  'lib.tlPendColEvent': 'Event',
  'lib.tlPendColSource': 'Source',
  'lib.tlPendColTime': 'Time',
  'lib.tlPendColReason': 'Why undetermined',
  'lib.tlPendColActions': 'Actions',
  'lib.tlPendNoRaw': '(no time cue in source)',
  'lib.tlPendPlaceholder': 'fill in',
  'lib.tlPendConfirm': 'Confirm',
  'lib.tlPendDiscard': 'Discard',
  'lib.tlPendReasonFallback': 'Legacy undetermined time (no reason recorded)',
  'lib.tlPendUnit.day': 'day',
  'lib.tlPendUnit.year': 'year',
  'lib.tlPendUnit.month': 'month',
};
