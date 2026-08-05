/** Agent 配置页（spec §4.2.3）：模型接入 + 写作 Agent 链 + 外观三卡片 */
import { AgentChainCard } from '../components/AgentChainCard';
import { AgentLlmCard } from '../components/AgentLlmCard';
import { AppearanceCard } from '../components/AppearanceCard';
import { useI18n } from '../i18n/useI18n';

export function AgentsPage() {
  const { t } = useI18n();
  return (
    <div className="mx-auto max-w-[860px] px-12 py-10">
      <div className="mb-7">
        <h1 className="font-serif text-[26px] font-semibold">{t('ag.title')}</h1>
        <p className="mt-0.5 text-[13px] text-ink-3">{t('ag.sub')}</p>
      </div>
      <div className="space-y-5">
        <AgentLlmCard />
        <AgentChainCard />
        <AppearanceCard />
      </div>
    </div>
  );
}
