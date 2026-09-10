/** #725 会话页重构文案（从 zh.ts/en.ts 拆出以符合 900 行护栏；镜像 role-enhance.ts 形态）。 */
export const sessionsUxZh: Record<string, string> = {
  'sessions.search.placeholder': '搜索会话标题 / 项目 / 最后消息…',
  'sessions.badge.ai': 'AI 对话',
  'sessions.badge.interview': '访谈',
  'sessions.badge.execution': '执行',
  // #770 会话页架构：会话 title 空回退文案
  'sessions.chat.titleEmpty': '未命名会话',
  // #1015 会话详情弹层 + 归档 AI 对话只读横幅
  'sessions.detail.loadFailed': '详情加载失败',
  'sessions.detail.unanswered': '（未回答）',
  // #1029 决策轨迹区块（ADR-056 软锚 sessions.context.agent_run_id）
  'sessions.detail.trace': '决策轨迹',
  'sessions.detail.traceLink': '查看执行详情',
  'sessions.detail.traceFailed': '决策轨迹加载失败',
  'write.chat.archivedBanner': '该会话已归档，仅供查看',
};

export const sessionsUxEn: Record<string, string> = {
  'sessions.search.placeholder': 'Search sessions by title / project / last message…',
  'sessions.badge.ai': 'AI chat',
  'sessions.badge.interview': 'Interview',
  'sessions.badge.execution': 'Execution',
  // #770 session page architecture: empty title fallback
  'sessions.chat.titleEmpty': 'Untitled session',
  // #1015 session detail dialog + archived AI chat read-only banner
  'sessions.detail.loadFailed': 'Failed to load details',
  'sessions.detail.unanswered': '(unanswered)',
  // #1029 decision trace block (ADR-056 soft anchor sessions.context.agent_run_id)
  'sessions.detail.trace': 'Decision Trace',
  'sessions.detail.traceLink': 'View execution detail',
  'sessions.detail.traceFailed': 'Failed to load decision trace',
  'write.chat.archivedBanner': 'This conversation is archived (read-only)',
};
