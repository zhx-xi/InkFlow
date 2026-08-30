/** chat 删除授权 UX 文案（#766 阶段② 三态分段控件 + HITL 确认弹窗；从 zh.ts/en.ts 拆出以符合 900 行护栏，与 chat-ux.ts / session-ux.ts 同模式）。 */
export const chatDeleteUxZh: Record<string, string> = {
  'write.chat.deleteMode.manual': '手动',
  'write.chat.deleteMode.askOnce': '一次确认',
  'write.chat.deleteMode.auto': '全自动',
  'write.chat.deleteMode.confirmTitle': '确认删除',
  'write.chat.deleteMode.confirmDelete': '确认删除',
  'write.chat.deleteMode.cancel': '取消',
};

export const chatDeleteUxEn: Record<string, string> = {
  'write.chat.deleteMode.manual': 'Manual',
  'write.chat.deleteMode.askOnce': 'Ask once',
  'write.chat.deleteMode.auto': 'Auto',
  'write.chat.deleteMode.confirmTitle': 'Confirm Delete',
  'write.chat.deleteMode.confirmDelete': 'Confirm Delete',
  'write.chat.deleteMode.cancel': 'Cancel',
};
