/** 写作 Agent 链（spec §4.2.3）：Architect/Writer/Auditor/Reviser 四行开关 ↔ config.agent_* */
import { useI18n } from '../i18n/useI18n';
import { useAgentStore } from '../stores/agent';
import type { ProjectConfig } from '../stores/project';

type AgentField = 'agent_architect' | 'agent_writer' | 'agent_auditor' | 'agent_reviser';

const AGENT_ROLES: Array<{ field: AgentField; nameKey: string; descKey: string; glyph: string }> = [
  { field: 'agent_architect', nameKey: 'ag.architect', descKey: 'ag.architectDesc', glyph: 'A' },
  { field: 'agent_writer', nameKey: 'ag.writer', descKey: 'ag.writerDesc', glyph: 'W' },
  { field: 'agent_auditor', nameKey: 'ag.auditor', descKey: 'ag.auditorDesc', glyph: 'A' },
  { field: 'agent_reviser', nameKey: 'ag.reviser', descKey: 'ag.reviserDesc', glyph: 'R' },
];

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

export function AgentChainCard() {
  const { t } = useI18n();
  const config = useAgentStore((s) => s.config);
  const setConfig = useAgentStore((s) => s.setConfig);

  return (
    <section data-testid="agent-chain-card" className="rounded-lg border border-line bg-surface p-6">
      <h2 className="font-serif text-[17px] font-semibold">{t('ag.chainTitle')}</h2>
      <p className="mt-1 text-[12px] text-ink-3">{t('ag.chainDesc')}</p>
      <div className="mt-4 divide-y divide-line">
        {AGENT_ROLES.map((role) => {
          const value = config[role.field];
          const checked = value !== undefined;
          const tag = value === null ? t('ag.defaultModel') : value === undefined ? t('ag.removed') : value;
          const toggle = () => setConfig(agentPatch(role.field, checked ? undefined : null));
          return (
            <div key={role.field} className="flex items-center gap-3 py-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent font-serif text-[14px] text-accent-ink">
                {role.glyph}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium">{t(role.nameKey)}</span>
                  <span className="rounded bg-surface-3 px-1.5 py-0.5 text-[11px] text-ink-3">{tag}</span>
                </div>
                <p className="mt-0.5 text-[12px] text-ink-3">{t(role.descKey)}</p>
              </div>
              <input
                type="checkbox"
                role="switch"
                aria-label={t(role.nameKey)}
                checked={checked}
                onChange={toggle}
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}
