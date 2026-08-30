/** chat 运行时 UX 文案（#719 中断按钮 + #727 思考过程/工具调用折叠块；从 zh.ts/en.ts 拆出以符合 900 行护栏）。 */
export const chatUxZh: Record<string, string> = {
  'write.chat.stop': '中断',
  'write.chat.thinking': '思考过程',
  'write.chat.toolCall': '工具调用',
  // #770 会话页架构：全局 chat 页 / 改名
  'write.chat.globalTitle': '全局对话',
  'write.chat.rename': '重命名',
  'write.chat.renamed': '已重命名',
  'write.chat.renameInvalid': '标题不能超过 200 字符',
};

export const chatUxEn: Record<string, string> = {
  'write.chat.stop': 'Stop',
  'write.chat.thinking': 'Thinking',
  'write.chat.toolCall': 'Tool call',
  // #770 session page architecture: global chat / rename
  'write.chat.globalTitle': 'Global chat',
  'write.chat.rename': 'Rename',
  'write.chat.renamed': 'Renamed',
  'write.chat.renameInvalid': 'Title must be 200 characters or less',
};
