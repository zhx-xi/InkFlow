/**
 * Agent 管理列表（Issue #260 F41，spec §5.5 / §8.3 / §13 M8）：
 * 自包含——挂载时 loadAgents + loadToolCatalog + loadSkills（3 GET，失败静默 error 不阻塞渲染）。
 * 内置 Agent 只读（builtin 徽标 + 工具/skill chips + prompt 预览）；
 * 自定义 Agent 可编辑/删除（删除有确认框）；新建/编辑走 AgentEditDialog。
 */
import { useEffect, useState } from 'react';
import { useI18n } from '../i18n/useI18n';
import { useAgentsStore, type AgentEntity, type AgentInput, type ToolDomain, type ToolOp } from '../stores/agents';
import { useI18nMessagesStore, useTScope } from '../stores/i18n';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';
import { AgentEditDialog } from './AgentEditDialog';
import { ConfirmDialog } from './ConfirmDialog';

/** #957 F58：只读矩阵行 = 固定 8 域（与 AgentEditDialog DOMAINS 同序，spec §2.1） */
const DOMAINS: ToolDomain[] = [
  'outline',
  'character',
  'world',
  'timeline',
  'foreshadowing',
  'memory',
  'writing',
  'agent_chain',
];

/** 列 = read/write/delete（与 AgentEditDialog OPS 同序） */
const OPS: ToolOp[] = ['read', 'write', 'delete'];

export function AgentList() {
  const { t } = useI18n();
  const tScope = useTScope();
  const lang = useThemeStore((s) => s.lang);
  const loadI18nMessages = useI18nMessagesStore((s) => s.load);
  const pushToast = useToastStore((s) => s.pushToast);
  const agents = useAgentsStore((s) => s.agents);
  const tools = useAgentsStore((s) => s.tools);
  const skills = useAgentsStore((s) => s.skills);
  const loadAgents = useAgentsStore((s) => s.loadAgents);
  const loadToolCatalog = useAgentsStore((s) => s.loadToolCatalog);
  const loadSkills = useAgentsStore((s) => s.loadSkills);
  const createAgent = useAgentsStore((s) => s.createAgent);
  const updateAgent = useAgentsStore((s) => s.updateAgent);
  const deleteAgent = useAgentsStore((s) => s.deleteAgent);
  const copyAgent = useAgentsStore((s) => s.copyAgent);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AgentEntity | null>(null);
  const [pendingDelete, setPendingDelete] = useState<AgentEntity | null>(null);
  const [detailAgent, setDetailAgent] = useState<AgentEntity | null>(null);
  const [showResolvedTools, setShowResolvedTools] = useState(false);

  // #957 F58 §4.3：远端 i18n 目录单飞加载（失败静默 → tScope 本地回退）；
  // 声明在业务 GET 之前：其 fetch 先入队，先落地，避免详情弹窗测试捕获在途请求
  useEffect(() => {
    void loadI18nMessages(lang);
  }, [lang, loadI18nMessages]);

  // 挂载加载 3 端点（工具目录 + 技能列表为双向视图映射数据源）
  useEffect(() => {
    void loadAgents();
    void loadToolCatalog();
    void loadSkills();
  }, [loadAgents, loadToolCatalog, loadSkills]);

  /** 工具名映射：resolved_tool_names 元素（后端已 resolve）→ 目录 name（未命中显示原名） */
  const toolLabel = (toolName: string): string => {
    const tool = tools.find((x) => x.name === toolName);
    return tool ? tool.name : toolName;
  };

  /** 只读矩阵勾选态：(domain,op) ∈ agent.grants（grants 缺失 = 旧数据 → 全 false） */
  const isGranted = (agent: AgentEntity, domain: ToolDomain, op: ToolOp): boolean =>
    (agent.grants ?? []).some((g) => g.domain === domain && g.ops.includes(op));

  /** skill 名映射：skill_ids 元素（字符串化 id）→ skills[].id 匹配 → name；未命中显示 #<id> */
  const skillLabel = (skillId: string): string => {
    const skill = skills.find((x) => String(x.id) === skillId);
    return skill ? skill.name : `#${skillId}`;
  };

  /**
   * #957 F58 §3：卡片 chips 数据源 = resolved_tool_names（后端 _to_response 恒有）。
   * 对缺失该字段的旧 fixture/数据回退 tool_ids（兼容未迁移的既有设置页测试与旧快照）。
   */
  const chipToolNames = (agent: AgentEntity): string[] => agent.resolved_tool_names ?? agent.tool_ids;

  const handleOpenCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const handleOpenEdit = (agent: AgentEntity) => {
    setEditing(agent);
    setDialogOpen(true);
  };

  const handleSave = async (input: AgentInput) => {
    try {
      if (editing) await updateAgent(editing.id, input);
      else await createAgent(input);
      pushToast('ok', t('toast.agentSaved'));
      setDialogOpen(false);
    } catch {
      pushToast('err', t('toast.saveFailed'));
    }
  };

  const handleDelete = async () => {
    if (!pendingDelete) return;
    const agent = pendingDelete;
    setPendingDelete(null);
    await deleteAgent(agent.id);
    // 列表刷新（服务端权威：DELETE 后重新 GET）
    await loadAgents();
    pushToast('ok', t('toast.agentDeleted'));
  };

  const handleCopy = async (agent: AgentEntity) => {
    try {
      await copyAgent(agent.id);
      pushToast('ok', t('toast.agentCopied'));
    } catch {
      pushToast('err', t('toast.saveFailed'));
    }
  };

  return (
    <div data-testid="agent-list" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-medium">{t('set.agents.title')}</span>
        <button
          type="button"
          data-testid="agent-new-btn"
          className="rounded-md bg-accent px-3 py-1.5 text-xs text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          onClick={handleOpenCreate}
        >
          {t('set.agents.new')}
        </button>
      </div>

      {agents.length === 0 && <p className="text-[12px] text-ink-3">{t('set.agents.noCustom')}</p>}

      <div className="space-y-3">
        {agents.map((agent) => (
          <div
            key={agent.id}
            data-testid={`agent-card-${agent.id}`}
            className="rounded-md border border-line p-3"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-[14px] font-medium">
                  {agent.icon ? `${agent.icon} ` : ''}
                  {agent.name}
                </span>
                {agent.builtin && (
                  <span
                    data-testid={`agent-builtin-badge-${agent.id}`}
                    className="rounded bg-surface-3 px-1.5 py-0.5 text-[11px] text-ink-2"
                  >
                    {t('set.agents.builtin')}
                  </span>
                )}
              </div>
              {!agent.builtin && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    data-testid={`agent-edit-${agent.id}`}
                    className="rounded-md border border-line px-2.5 py-1 text-xs text-ink-2 transition duration-180 hover:bg-surface-3"
                    onClick={() => handleOpenEdit(agent)}
                  >
                    {t('tpl.edit')}
                  </button>
                  <button
                    type="button"
                    data-testid={`agent-del-${agent.id}`}
                    className="rounded-md border border-err/40 px-2.5 py-1 text-xs text-err transition duration-180 hover:bg-err/10"
                    onClick={() => setPendingDelete(agent)}
                  >
                    {t('tpl.delete')}
                  </button>
                </div>
              )}
              {agent.builtin && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    data-testid={`agent-detail-${agent.id}`}
                    className="rounded-md border border-line px-2.5 py-1 text-xs text-ink-2 transition duration-180 hover:bg-surface-3"
                    onClick={() => {
                      setDetailAgent(agent);
                      setShowResolvedTools(false);
                    }}
                  >
                    {t('set.agents.detail')}
                  </button>
                  <button
                    type="button"
                    data-testid={`agent-copy-${agent.id}`}
                    className="rounded-md border border-line px-2.5 py-1 text-xs text-ink-2 transition duration-180 hover:bg-surface-3"
                    onClick={() => void handleCopy(agent)}
                  >
                    {t('set.agents.copy')}
                  </button>
                </div>
              )}
            </div>

            {agent.description && (
              <p className="mt-1 text-[12px] text-ink-2">{agent.description}</p>
            )}

            {(chipToolNames(agent).length > 0 || agent.skill_ids.length > 0) && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {chipToolNames(agent).map((toolName) => (
                  <span
                    key={toolName}
                    data-testid={`agent-tool-chip-${toolName}`}
                    className="rounded bg-surface-3 px-1.5 py-0.5 text-[11px] text-ink-2"
                  >
                    {toolLabel(toolName)}
                  </span>
                ))}
                {agent.skill_ids.map((skillId) => (
                  <span
                    key={skillId}
                    data-testid={`agent-skill-chip-${skillId}`}
                    className="rounded bg-surface-3 px-1.5 py-0.5 text-[11px] text-ink-2"
                  >
                    {skillLabel(skillId)}
                  </span>
                ))}
              </div>
            )}

            {agent.system_prompt && (
              <p className="mt-2 line-clamp-2 text-[12px] text-ink-3">{agent.system_prompt}</p>
            )}
          </div>
        ))}
      </div>

      <AgentEditDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editing={editing}
        onCreate={(input) => void handleSave(input)}
        onUpdate={(input) => void handleSave(input)}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        title={pendingDelete?.name ?? ''}
        message={t('set.agents.deleteConfirm', { name: pendingDelete?.name ?? '' })}
        confirmText={t('lib.delete.ok')}
        danger
        testidPrefix="agent-delete"
        onConfirm={() => void handleDelete()}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      />

      {detailAgent && (
        <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
          <div
            role="dialog"
            aria-modal="true"
            aria-label={detailAgent.name}
            data-testid="agent-detail-dialog"
            className="max-h-[85vh] w-[560px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="font-serif text-[18px] font-semibold">
                {detailAgent.icon} {detailAgent.name}
              </h2>
              <button
                type="button"
                data-testid="agent-detail-close"
                aria-label="关闭"
                className="rounded-md border border-line px-2.5 py-1 text-xs text-ink-2 hover:bg-surface-3"
                onClick={() => setDetailAgent(null)}
              >
                ✕
              </button>
            </div>
            {detailAgent.description && (
              <p className="mt-1 text-[13px] text-ink-2">{detailAgent.description}</p>
            )}
            <div className="mt-3">
              <div className="text-[12px] font-medium text-ink-2">{t('set.agents.prompt')}</div>
              <pre
                data-testid="agent-detail-prompt"
                className="mt-1 whitespace-pre-wrap rounded-md border border-line bg-surface-2 p-3 text-[12px] text-ink"
              >
                {detailAgent.system_prompt}
              </pre>
            </div>
            {/* #957 F58 §3：只读 scope 矩阵 + resolved 计数 + 工具清单折叠（默认折叠） */}
            <div className="mt-3">
              <div className="text-[12px] font-medium text-ink-2">{t('set.agents.tools')}</div>
              <div data-testid="agent-scope-detail" className="mt-1.5 rounded-md border border-line p-3">
                <div className="grid grid-cols-[minmax(0,1fr)_repeat(3,44px)] items-center gap-x-2 text-[11px]">
                  <span />
                  {OPS.map((op) => (
                    <span key={op} className="text-center font-medium text-ink-2">
                      {tScope(`agent.scope.${op}`)}
                    </span>
                  ))}
                </div>
                {DOMAINS.map((domain) => (
                  <div
                    key={domain}
                    className="mt-1 grid grid-cols-[minmax(0,1fr)_repeat(3,44px)] items-center gap-x-2 text-[11px]"
                  >
                    <span>{tScope(`agent.scope.domain.${domain}`)}</span>
                    {OPS.map((op) => {
                      const granted = isGranted(detailAgent, domain, op);
                      return (
                        <span
                          key={op}
                          data-testid={`agent-detail-scope-${domain}-${op}`}
                          data-checked={granted ? 'true' : 'false'}
                          className="text-center"
                        >
                          {granted ? '✓' : '—'}
                        </span>
                      );
                    })}
                  </div>
                ))}
              </div>
              {(detailAgent.grants ?? []).length === 0 && (
                <div data-testid="agent-scope-empty" className="mt-1.5 text-[12px] text-ink-3">
                  {tScope('agent.scope.noGrants')}
                </div>
              )}
              <div className="mt-2 flex items-center justify-between gap-2 text-[12px]">
                <span data-testid="agent-detail-resolved-count">
                  {tScope('agent.scope.resolvedCount', {
                    n: (detailAgent.resolved_tool_names ?? []).length,
                  })}
                </span>
                <button
                  type="button"
                  data-testid="agent-detail-resolved-toggle"
                  className="rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-2 hover:bg-surface-3"
                  onClick={() => setShowResolvedTools((v) => !v)}
                >
                  {showResolvedTools ? tScope('agent.scope.hideTools') : tScope('agent.scope.showTools')}
                </button>
              </div>
              {showResolvedTools && (detailAgent.resolved_tool_names ?? []).length > 0 && (
                <ul className="mt-1.5 space-y-1 text-[12px] text-ink-2">
                  {(detailAgent.resolved_tool_names ?? []).map((name) => (
                    <li key={name} data-testid={`agent-detail-resolved-tool-${name}`}>
                      {toolLabel(name)}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {detailAgent.skill_ids.length > 0 && (
              <div className="mt-3">
                <div className="text-[12px] font-medium text-ink-2">{t('set.agents.skills')}</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {detailAgent.skill_ids.map((skillId) => (
                    <span
                      key={skillId}
                      data-testid={`agent-detail-skill-${skillId}`}
                      className="rounded bg-surface-3 px-1.5 py-0.5 text-[11px] text-ink-2"
                    >
                      {skillLabel(skillId)}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
