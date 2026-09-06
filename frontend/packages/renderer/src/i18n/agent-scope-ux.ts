/**
 * #957 F58 Agent scope 矩阵 UX 文案（contract-957 §4.1，16 键 zh/en 逐字对称）：
 * 从 zh.ts/en.ts 拆出防 900 行护栏（#762 先例）；远端目录覆盖词条走 stores/i18n。
 */
export const agentScopeUxZh: Record<string, string> = {
  'agent.scope.read': '读',
  'agent.scope.write': '写',
  'agent.scope.delete': '删',
  'agent.scope.delete.tooltip': '暴露删除工具；每次删除仍需会话确认（双闸，ADR-043）',
  'agent.scope.resolvedCount': '共 {n} 个工具',
  'agent.scope.showTools': '查看工具清单',
  'agent.scope.hideTools': '收起工具清单',
  'agent.scope.noGrants': '未授权任何工具域',
  'agent.scope.domain.outline': '大纲',
  'agent.scope.domain.character': '角色',
  'agent.scope.domain.world': '世界观',
  'agent.scope.domain.timeline': '时间线',
  'agent.scope.domain.foreshadowing': '伏笔',
  'agent.scope.domain.memory': '记忆',
  'agent.scope.domain.writing': '写作',
  'agent.scope.domain.agent_chain': 'Agent 链',
};

export const agentScopeUxEn: Record<string, string> = {
  'agent.scope.read': 'Read',
  'agent.scope.write': 'Write',
  'agent.scope.delete': 'Delete',
  'agent.scope.delete.tooltip':
    'Exposes delete tools; each deletion still requires in-session confirmation (double gate, ADR-043)',
  'agent.scope.resolvedCount': '{n} tools resolved',
  'agent.scope.showTools': 'Show tool list',
  'agent.scope.hideTools': 'Hide tool list',
  'agent.scope.noGrants': 'No tool domain granted',
  'agent.scope.domain.outline': 'Outline',
  'agent.scope.domain.character': 'Characters',
  'agent.scope.domain.world': 'World Building',
  'agent.scope.domain.timeline': 'Timeline',
  'agent.scope.domain.foreshadowing': 'Foreshadowing',
  'agent.scope.domain.memory': 'Memory',
  'agent.scope.domain.writing': 'Writing',
  'agent.scope.domain.agent_chain': 'Agent Chain',
};
