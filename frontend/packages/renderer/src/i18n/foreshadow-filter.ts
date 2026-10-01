/**
 * #1376：伏笔页筛选/排序条文案（zh/en；形态 A）。
 *
 * 独立成文件而非写入 zh.ts / en.ts：后两者基线已 900 / 899 行，贴 900 行护栏
 * （ci_cd/check_file_length.py），新增 9 键即触线；同 pagination.ts / logs-ux.ts 先例。
 */
export const foreshadowFilterZh: Record<string, string> = {
  'lib.fs.filter.statusLabel': '回收状态',
  'lib.fs.filter.statusAll': '全部',
  'lib.fs.filter.searchLabel': '检索',
  'lib.fs.filter.searchPlaceholder': '检索标题或位置，如：剑 / 第 2 章',
  'lib.fs.filter.count': '显示 {shown} / 共 {total} 条',
  'lib.fs.filter.sortDesc': '优先级 高→低',
  'lib.fs.filter.sortAsc': '优先级 低→高',
  'lib.fs.filter.noresult': '当前筛选条件下没有匹配的伏笔',
  'lib.fs.filter.clear': '清除筛选',
};

export const foreshadowFilterEn: Record<string, string> = {
  'lib.fs.filter.statusLabel': 'Status',
  'lib.fs.filter.statusAll': 'All',
  'lib.fs.filter.searchLabel': 'Search',
  'lib.fs.filter.searchPlaceholder': 'Search title or location, e.g. 剑 / 第 2 章',
  'lib.fs.filter.count': 'Showing {shown} of {total}',
  'lib.fs.filter.sortDesc': 'Priority high→low',
  'lib.fs.filter.sortAsc': 'Priority low→high',
  'lib.fs.filter.noresult': 'No foreshadowings match the current filters',
  'lib.fs.filter.clear': 'Clear filters',
};
