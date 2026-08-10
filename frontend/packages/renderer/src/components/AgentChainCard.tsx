/** 写作 Agent 链（spec §4.2.3）：Architect/Writer/Auditor/Reviser 四行开关 ↔ config.agent_*；
 *  #225 三态语义：null=关闭（禁用角色）；字符串=开启且指定模型；
 *  "__default__"（AGENT_DEFAULT_SENTINEL）=跟随默认（预留，前端不暴露中间态 UI） */
import { ClipboardCheck, Network, PenLine, RefreshCw, type LucideIcon } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';
import { useAgentStore } from '../stores/agent';
import { AGENT_DEFAULT_SENTINEL, type ProjectConfig } from '../stores/project';
import { Switch } from './ui/switch';

type AgentField = 'agent_architect' | 'agent_writer' | 'agent_auditor' | 'agent_reviser';

const AGENT_ROLES: Array<{ field: AgentField; nameKey: string; descKey: string; icon: LucideIcon }> = [
  { field: 'agent_architect', nameKey: 'ag.architect', descKey: 'ag.architectDesc', icon: Network },
  { field: 'agent_writer', nameKey: 'ag.writer', descKey: 'ag.writerDesc', icon: PenLine },
  { field: 'agent_auditor', nameKey: 'ag.auditor', descKey: 'ag.auditorDesc', icon: ClipboardCheck },
  { field: 'agent_reviser', nameKey: 'ag.reviser', descKey: 'ag.reviserDesc', icon: RefreshCw },
];

export interface AgentChainCardProps {
  /** 开关变更回调（#105 🔴-2：AgentPanel 即改即存 PATCH；不传则仅更新本地 store） */
  onConfigChange?: () => void;
}

function agentPatch(field: AgentField, value: string | null | undefined): Partial<ProjectConfig> {
  switch (field) {
    case 'agent_architect':
      return { agent_architect: value };
    case 'agent_writer':
      return { agent_writer: value };
    case 'agent_auditor':
      return { agent_auditor: value };
    case 'agent_reviser':
      return { agent_reviser: value };
    default:
      return {};
  }
}

export function AgentChainCard({ onConfigChange }: AgentChainCardProps = {}) {
  const { t } = useI18n();
  const config = useAgentStore((s) => s.config);
  const setConfig = useAgentStore((s) => s.setConfig);

  return (
    <section data-testid="agent-chain-card" className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <h2 className="font-serif text-[17px] font-semibold">{t('ag.chainTitle')}</h2>
      <p className="mt-1 text-[12px] text-ink-3">{t('ag.chainDesc')}</p>
      <div className="mt-4 divide-y divide-line">
        {AGENT_ROLES.map((role) => {
          const value = config[role.field];
          // 三态语义（#225）：null=关闭（禁用角色）；字符串=开启且指定模型；
          // "__default__"（AGENT_DEFAULT_SENTINEL）=跟随默认（预留）
          const checked = typeof value === 'string';
          const tag =
            value == null ? t('ag.disabled') : value === AGENT_DEFAULT_SENTINEL ? t('ag.defaultModel') : value;
          const toggle = () => {
            // 关闭 → 显式 null（JSON.stringify 保留 → 后端落库 null → 重启仍关闭）；
            // 打开 → sentinel "__default__"（跟随默认，本期无模型选择 UI）
            setConfig(agentPatch(role.field, checked ? null : AGENT_DEFAULT_SENTINEL));
            onConfigChange?.();
          };
          return (
            <div key={role.field} className="flex items-center gap-3 py-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-weak text-accent">
                <role.icon className="h-4 w-4" aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium">{t(role.nameKey)}</span>
                  <span className="rounded bg-surface-3 px-1.5 py-0.5 text-[11px] text-ink-3">{tag}</span>
                </div>
                <p className="mt-0.5 text-[12px] text-ink-3">{t(role.descKey)}</p>
              </div>
              <Switch checked={checked} onCheckedChange={toggle} aria-label={t(role.nameKey)} />
            </div>
          );
        })}
      </div>
    </section>
  );
}
