/** #725 会话页重构文案（从 zh.ts/en.ts 拆出以符合 900 行护栏；镜像 role-enhance.ts 形态）。 */
export const sessionsUxZh: Record<string, string> = {
  'sessions.search.placeholder': '搜索会话标题 / 项目 / 最后消息…',
  'sessions.badge.ai': 'AI 对话',
  'sessions.badge.interview': '访谈',
  'sessions.badge.execution': '执行',
  // #770 会话页架构：会话 title 空回退文案
  'sessions.chat.titleEmpty': '未命名会话',
};

export const sessionsUxEn: Record<string, string> = {
  'sessions.search.placeholder': 'Search sessions by title / project / last message…',
  'sessions.badge.ai': 'AI chat',
  'sessions.badge.interview': 'Interview',
  'sessions.badge.execution': 'Execution',
  // #770 session page architecture: empty title fallback
  'sessions.chat.titleEmpty': 'Untitled session',
};
