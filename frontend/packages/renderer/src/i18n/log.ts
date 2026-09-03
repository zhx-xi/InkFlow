/** 日志页 msgid（log.event.*）— 与后端 messages 键对齐（F57 #888-S3）。 */
export const logZh: Record<string, string> = {
  'log.event.create_chapter': '创建章节：{title}',
  'log.event.update_project': '更新项目：{name}',
  'log.event.delete_project': '删除项目：{name}',
  'log.event.save_chapter': '保存章节：{title}',
  'log.event.page_load': '页面加载：{page}',
  'log.event.navigate': '页面跳转：{path}',
  'log.event.user_action': '用户操作：{action}',
  'log.event.api_retry': 'API 重试：第 {attempt} 次',
  'log.event.uncaught_error': '未捕获异常：{message}',
};

export const logEn: Record<string, string> = {
  'log.event.create_chapter': 'Created chapter: {title}',
  'log.event.update_project': 'Updated project: {name}',
  'log.event.delete_project': 'Deleted project: {name}',
  'log.event.save_chapter': 'Saved chapter: {title}',
  'log.event.page_load': 'Page loaded: {page}',
  'log.event.navigate': 'Navigate to: {path}',
  'log.event.user_action': 'User action: {action}',
  'log.event.api_retry': 'API retry: attempt {attempt}',
  'log.event.uncaught_error': 'Uncaught error: {message}',
};
