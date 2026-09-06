/** 写作页草稿域 UX 文案（#749 展开/收起 + #976 常显/审批；插值用单花括号 {count}，从 zh.ts/en.ts 拆出以符 900 行护栏）。 */
export const writingUxZh: Record<string, string> = {
  'write.drafts.expand': '展开看全文',
  'write.drafts.collapse': '收起',
  'write.drafts.pending': '草稿 ({count})',
  'write.drafts.pendingBadge': '草稿/未审批',
  'write.drafts.openApprove': '审批草稿',
  'write.drafts.confirmDone': '草稿已确认',
};

export const writingUxEn: Record<string, string> = {
  'write.drafts.expand': 'Show Full Text',
  'write.drafts.collapse': 'Collapse',
  'write.drafts.pending': 'Drafts ({count})',
  'write.drafts.pendingBadge': 'Draft',
  'write.drafts.openApprove': 'Approve draft',
  'write.drafts.confirmDone': 'Draft confirmed',
};
