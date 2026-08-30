/**
 * 会话栏 i18n 文案（#762 左侧独立会话栏；拆分出 zh.ts/en.ts 以符合 900 行护栏，
 * 与 chat-ux.ts / writing-ux.ts / sessions-ux.ts 同模式）。useI18n 聚合。
 */
export const sessionUxZh: Record<string, string> = {
  'nav.group.sessions': '会话',
  'session.time.today': '今天',
  'session.time.week': '本周',
  'session.time.earlier': '更早',
  'session.archived': '已归档',
  'session.messages': '{count} 条',
};

export const sessionUxEn: Record<string, string> = {
  'nav.group.sessions': 'Sessions',
  'session.time.today': 'Today',
  'session.time.week': 'This Week',
  'session.time.earlier': 'Earlier',
  'session.archived': 'Archived',
  'session.messages': '{count} msgs',
};
