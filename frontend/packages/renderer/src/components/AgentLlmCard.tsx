/** 模型接入卡片（spec §4.2.3）：服务商/模型/API Key/温度滑杆/默认字数 + 测试连接 + 保存 */
import { useState } from 'react';
import { useI18n } from '../i18n/useI18n';
import { useAgentStore } from '../stores/agent';
import { useProjectStore } from '../stores/project';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Slider } from './ui/slider';

const PROVIDERS = ['openai', 'deepseek', 'ollama'];

export function AgentLlmCard() {
  const { t } = useI18n();
  const config = useAgentStore((s) => s.config);
  const apiKeyDraft = useAgentStore((s) => s.apiKeyDraft);
  const testStatus = useAgentStore((s) => s.testStatus);
  const testMessage = useAgentStore((s) => s.testMessage);
  const setConfig = useAgentStore((s) => s.setConfig);
  const setApiKeyDraft = useAgentStore((s) => s.setApiKeyDraft);
  const testConnection = useAgentStore((s) => s.testConnection);
  const submitApiKey = useAgentStore((s) => s.submitApiKey);
  const saveConfig = useAgentStore((s) => s.saveConfig);
  const projectId = useProjectStore((s) => s.currentProjectId);
  const [provider, setProvider] = useState('openai');
  const [defaultWords, setDefaultWords] = useState(800000);

  const handleTest = () => {
    void testConnection({ provider, model: config.model ?? '', api_key: apiKeyDraft });
  };

  const handleSave = async () => {
    if (projectId === null) return;
    // Q3 主路径：draft 非空先落 key（加密存储）并清空，再由 saveConfig PATCH config
    if (apiKeyDraft) {
      await submitApiKey({ provider, model: config.model ?? '', api_key: apiKeyDraft });
    }
    await saveConfig(projectId);
  };

  return (
    <section data-testid="agent-llm-card" className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <h2 className="font-serif text-[17px] font-semibold">{t('ag.llmTitle')}</h2>
      <p className="mt-1 text-[12px] text-ink-3">{t('ag.llmDesc')}</p>
      <div className="mt-4 grid grid-cols-2 gap-x-5 gap-y-3">
        <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
          <span>{t('ag.provider')}</span>
          <Select
            value={provider}
            onValueChange={(v) => setProvider(v)}
          >
            <SelectTrigger
              aria-label={t('ag.provider')}
              className="w-full"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PROVIDERS.map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <label className="flex flex-col gap-1.5 text-[12px] text-ink-2">
          <span>{t('ag.model')}</span>
          <input
            aria-label={t('ag.model')}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-[13px] outline-none focus:border-accent"
            value={config.model ?? ''}
            onChange={(e) => setConfig({ model: e.target.value })}
            placeholder="gpt-4o / deepseek-chat"
          />
        </label>
        <label className="flex flex-col gap-1.5 text-[12px] text-ink-2">
          <span>{t('ag.apiKey')}</span>
          <input
            type="password"
            aria-label={t('ag.apiKey')}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-[13px] outline-none focus:border-accent"
            value={apiKeyDraft}
            onChange={(e) => setApiKeyDraft(e.target.value)}
            placeholder="sk-..."
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1.5 text-[12px] text-ink-2">
          <span>{t('ag.temperature')}</span>
          <div className="flex items-center gap-2">
            <Slider
              aria-label={t('ag.temperature')}
              min={0}
              max={2}
              step={0.1}
              value={[config.temperature ?? 0.7]}
              onValueChange={(values) => setConfig({ temperature: values[0] })}
              className="flex-1"
            />
            <span className="w-8 text-right text-[13px]">{(config.temperature ?? 0.7).toFixed(1)}</span>
          </div>
        </label>
        <label className="flex flex-col gap-1.5 text-[12px] text-ink-2">
          <span>{t('ag.defaultWords')}</span>
          <input
            type="number"
            min={0}
            aria-label={t('ag.defaultWords')}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-[13px] outline-none focus:border-accent"
            value={defaultWords}
            onChange={(e) => setDefaultWords(Number(e.target.value))}
          />
        </label>
      </div>
      {testMessage && (
        <div
          className={`mt-3 text-[13px] ${
            testStatus === 'ok' ? 'text-ok' : testStatus === 'fail' ? 'text-err' : 'text-ink-2'
          }`}
        >
          {testMessage}
        </div>
      )}
      <div className="mt-5 flex gap-2">
        <button
          type="button"
          className="rounded-md border border-line px-4 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 disabled:opacity-50"
          disabled={testStatus === 'testing'}
          onClick={handleTest}
        >
          {testStatus === 'testing' ? t('ag.testing') : t('ag.test')}
        </button>
        <button
          type="button"
          className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          onClick={() => void handleSave()}
        >
          {t('ag.save')}
        </button>
      </div>
    </section>
  );
}
