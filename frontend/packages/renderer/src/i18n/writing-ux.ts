/** 写作页草稿域 UX 文案（#749 展开/收起 + #976 常显/审批；插值用单花括号 {count}，从 zh.ts/en.ts 拆出以符 900 行护栏）。 */
export const writingUxZh: Record<string, string> = {
  'write.drafts.expand': '展开看全文',
  'write.drafts.collapse': '收起',
  'write.drafts.pending': '草稿 ({count})',
  'write.drafts.pendingBadge': '草稿/未审批',
  'write.drafts.openApprove': '审批草稿',
  'write.drafts.confirmDone': '草稿已确认',
  'write.drafts.rejectDone': '草稿已驳回',
  // #1440：被 book run --force 覆盖的章——「已有上一稿」徽标 + 恢复入口
  // ⚠️ 徽标文案取紧凑式（208px 栏宽下 5 字会挤掉章节标题，原型截图实证）；
  //    完整语义由 title tooltip（previousBadgeTitle）承载 —— 见 specs/f19-gui/writing.md §15.1
  'write.chapter.previousBadge': '旧稿',
  'write.chapter.previousBadgeTitle': '已有上一稿，可恢复',
  'write.chapter.restore': '恢复上一稿',
  'write.chapter.restore.title': '恢复上一稿？',
  'write.chapter.restore.message':
    '恢复将用上一稿替换当前正文（正文与上一稿互换）。这是双向切换：再恢复一次即可切回当前正文。',
  'write.chapter.restore.confirm': '恢复',
};

export const writingUxEn: Record<string, string> = {
  'write.drafts.expand': 'Show Full Text',
  'write.drafts.collapse': 'Collapse',
  'write.drafts.pending': 'Drafts ({count})',
  'write.drafts.pendingBadge': 'Draft',
  'write.drafts.openApprove': 'Approve draft',
  'write.drafts.confirmDone': 'Draft confirmed',
  'write.drafts.rejectDone': 'Draft rejected',
  // #1440: chapters overwritten by `book run --force` — badge + restore entry
  // Note: the badge label is intentionally compact (a 5-char label squeezes the chapter
  // title out at the default 208px rail width — proven by the prototype screenshot);
  // the full wording lives in the title tooltip (previousBadgeTitle) — see writing.md §15.1
  'write.chapter.previousBadge': 'Prev',
  'write.chapter.previousBadgeTitle': 'Has a previous draft (restorable)',
  'write.chapter.restore': 'Restore previous',
  'write.chapter.restore.title': 'Restore previous draft?',
  'write.chapter.restore.message':
    'Restoring swaps the current text with the previous draft. This is a two-way switch: restore again to switch back.',
  'write.chapter.restore.confirm': 'Restore',
};
