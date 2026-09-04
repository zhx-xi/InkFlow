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
  'log.event.kernel_ready': '内核就绪：端口 {port}（pid {pid}）',
  'log.event.kernel_failure': '内核健康检查失败：第 {attempt}/{max} 次',
  'log.event.kernel_exit': '内核进程退出：code {code} signal {signal}',
  'log.event.kernel_spawn_error': '内核启动失败：{error}',
  'log.event.kernel_crash': '内核崩溃：{code}',
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
  'log.event.kernel_ready': 'Kernel ready: port {port} (pid {pid})',
  'log.event.kernel_failure': 'Kernel health check failed: attempt {attempt}/{max}',
  'log.event.kernel_exit': 'Kernel process exited: code {code} signal {signal}',
  'log.event.kernel_spawn_error': 'Kernel spawn failed: {error}',
  'log.event.kernel_crash': 'Kernel crashed: {code}',
};
