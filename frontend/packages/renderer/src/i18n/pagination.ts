/**
 * #1300：分页公共组件文案（zh/en）。
 *
 * 独立成文件而非写入 zh.ts / en.ts：后两者基线已 899 / 898 行，逼近 900 行护栏
 * （ci_cd/check_file_length.py），新增 4 键即触线；同 logs-ux.ts / sessions-ux.ts 先例。
 */
export const paginationZh: Record<string, string> = {
  'pagination.page.prev': '上一页',
  'pagination.page.next': '下一页',
  'pagination.page.info': '第 {page} / {pages} 页 · 共 {total} 条',
  'pagination.page.size.label': '每页条数',
};

export const paginationEn: Record<string, string> = {
  'pagination.page.prev': 'Previous',
  'pagination.page.next': 'Next',
  'pagination.page.info': 'Page {page} / {pages} · {total} entries',
  'pagination.page.size.label': 'Page size',
};
