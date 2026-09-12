/**
 * F60 首启模型配置引导（#934 §5）—— 三步最小闭环，GUI 主路径。
 *
 * 触发：App 层据 useModelReadinessStore.readiness.ready === false 渲染本组件
 * （全屏封面，同 BootGate 模式，不可 ESC 关闭）。
 *
 * 三步（spec §5.2-§5.4）：
 *   1. Provider + API Key（复用 ProviderDialog）
 *   2. chat 模型（必填）+ 连通探测（复用 POST /settings/llm/test）
 *   3. embedding 模型（可跳过 → 语义检索置灰，不阻断）
 *
 * 完成判据 = 后端 readiness 复核为 true（本组件不自判——完成动作后调
 * readiness.load()，由 App 层据新判据卸载本组件）。
 */
import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { apiFetch, errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { selectChatModelOptions, useModelsStore } from '../stores/models';
import { useModelReadinessStore } from '../stores/modelReadiness';
import { useToastStore } from '../stores/toast';
import { ProviderDialog } from './ProviderDialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

interface LlmTestResponse {
  ok: boolean;
  message?: string;
  error?: string;
}

type Step = 1 | 2 | 3;

export function SetupGuide() {
  const { t } = useI18n();
  const providers = useModelsStore((s) => s.providers);
  const chatModelSource = useModelsStore((s) => s.chatModelSource);
  const loadProviders = useModelsStore((s) => s.loadProviders);
  const addModel = useModelsStore((s) => s.addModel);
  const loadReadiness = useModelReadinessStore((s) => s.load);
  const pushToast = useToastStore((s) => s.pushToast);

  const [step, setStep] = useState<Step>(1);
  const [providerDialogOpen, setProviderDialogOpen] = useState(false);
  const [selectedModel, setSelectedModel] = useState('');
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  // #1129：并入同源候选（项目级 / 全局默认）——只认注册表时此下拉为空 → 用户死路
  const chatOptions = selectChatModelOptions(providers, chatModelSource);

  /** 步骤 1 → 2：至少一个 provider 已注册（key 由 ProviderDialog 内联存储） */
  const hasProvider = providers.length > 0;

  /** 步骤 2 连通探测（复用 llm/test，spec §5.3） */
  const handleTestConnection = async () => {
    if (testing || !selectedModel) return;
    setTesting(true);
    setTestError(null);
    try {
      const providerName = selectedModel.split('/')[0] ?? '';
      const provider = providers.find((p) => p.name === providerName);
      const res = await apiFetch<LlmTestResponse>('/api/v1/settings/llm/test', {
        method: 'POST',
        body: {
          provider: providerName,
          model: selectedModel,
          base_url: provider?.base_url ?? '',
          api_key: '',
        },
      });
      if (!res.ok) {
        // N5：留在步骤 2，错误可读，可重试
        setTestError(res.message ?? res.error ?? t('setup.testUnknown'));
        return;
      }
      // 探测通过 → 落 provider 默认模型（provider/model 格式，spec §5.3）
      if (provider) {
        await apiFetch(`/api/v1/provider-configs/${provider.id}`, {
          method: 'PATCH',
          body: { default_model: selectedModel },
        });
      }
      setStep(3);
    } catch (err) {
      setTestError(errorMessage(err));
    } finally {
      setTesting(false);
    }
  };

  /** 步骤 3：跳过（不写任何 embedding 配置，spec §5.4 N2） */
  const handleSkipEmbedding = async () => {
    setFinishing(true);
    try {
      await loadReadiness();
    } finally {
      setFinishing(false);
    }
  };

  /** 步骤 3：完成（用户已在外层配置 embedding；此处仅复核判据） */
  const handleFinish = async () => {
    setFinishing(true);
    try {
      await loadReadiness();
    } finally {
      setFinishing(false);
    }
  };

  /** 添加 embedding 模型：选中 provider 后追加一条 type=embedding 条目 */
  const handleAddEmbedding = async (providerId: number, modelId: string) => {
    const target = providers.find((p) => p.id === providerId);
    if (!target || !modelId.trim()) return;
    try {
      await addModel(providerId, { id: modelId.trim(), type: 'embedding', roles: [] });
      void loadReadiness();
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  return (
    <div
      data-testid="setup-guide"
      className="fixed inset-0 z-40 flex items-center justify-center overflow-y-auto bg-bg px-6 py-10"
    >
      <div className="w-full max-w-[560px] rounded-lg border border-line bg-surface p-8 shadow-card">
        <h1 className="font-serif text-[22px] font-semibold">{t('setup.title')}</h1>
        <p className="mt-2 text-[13px] text-ink-2">{t('setup.sub')}</p>

        {/* 三步指示 */}
        <ol data-testid="setup-steps" className="mt-6 space-y-1 text-[13px]">
          <li
            data-testid="setup-step-1"
            className={step === 1 ? 'font-medium text-ink' : 'text-ink-3'}
          >
            1. {t('setup.step1')}
          </li>
          <li
            data-testid="setup-step-2"
            className={step === 2 ? 'font-medium text-ink' : 'text-ink-3'}
          >
            2. {t('setup.step2')}
          </li>
          <li
            data-testid="setup-step-3"
            className={step === 3 ? 'font-medium text-ink' : 'text-ink-3'}
          >
            3. {t('setup.step3')}
          </li>
        </ol>

        <div className="mt-6 space-y-4">
          {step === 1 && (
            <div className="space-y-4">
              <p className="text-[13px] text-ink-2">{t('setup.providerHint')}</p>
              <div className="space-y-2">
                {providers.map((p) => (
                  <div
                    key={p.id}
                    data-testid={`setup-provider-${p.name}`}
                    className="flex items-center justify-between rounded-md border border-line px-3 py-2 text-[13px]"
                  >
                    <span>{p.name}</span>
                    <span className={p.key_saved ? 'text-ok' : 'text-ink-3'}>
                      {p.key_saved ? t('setup.keySaved') : t('setup.keyMissing')}
                    </span>
                  </div>
                ))}
              </div>
              <button
                type="button"
                data-testid="setup-add-provider"
                className="flex items-center gap-1 rounded-md border border-line px-4 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3"
                onClick={() => setProviderDialogOpen(true)}
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                {t('setup.addProvider')}
              </button>
              <button
                type="button"
                data-testid="setup-to-step2"
                disabled={!hasProvider}
                className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover disabled:opacity-50"
                onClick={() => setStep(2)}
              >
                {t('setup.next')}
              </button>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <p className="text-[13px] text-ink-2">{t('setup.chatHint')}</p>
              <Select value={selectedModel || undefined} onValueChange={setSelectedModel}>
                <SelectTrigger data-testid="setup-chat-select" className="w-full">
                  <SelectValue placeholder={t('setup.chatPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {chatOptions.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {testError && (
                <p data-testid="setup-test-error" className="text-[12px] text-err">
                  {testError}
                </p>
              )}
              <div className="flex gap-2">
                <button
                  type="button"
                  data-testid="setup-test-conn"
                  disabled={testing || !selectedModel}
                  className="rounded-md border border-line px-4 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 disabled:opacity-50"
                  onClick={() => void handleTestConnection()}
                >
                  {testing ? t('setup.testing') : t('setup.testConn')}
                </button>
                <button
                  type="button"
                  data-testid="setup-back-step1"
                  className="rounded-md border border-line px-4 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3"
                  onClick={() => setStep(1)}
                >
                  {t('setup.back')}
                </button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <p className="text-[13px] text-ink-2">{t('setup.embeddingHint')}</p>
              <EmbeddingPicker onAdd={handleAddEmbedding} />
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  data-testid="setup-skip-embedding"
                  disabled={finishing}
                  className="rounded-md border border-line px-4 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 disabled:opacity-50"
                  onClick={() => void handleSkipEmbedding()}
                >
                  {t('setup.skipEmbedding')}
                </button>
                <button
                  type="button"
                  data-testid="setup-finish"
                  disabled={finishing}
                  className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover disabled:opacity-50"
                  onClick={() => void handleFinish()}
                >
                  {t('setup.finish')}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <ProviderDialog
        open={providerDialogOpen}
        onOpenChange={setProviderDialogOpen}
        onSaved={() => {
          void loadProviders();
        }}
      />
    </div>
  );
}

/** 步骤 3 的 embedding 模型录入（provider + 裸模型名 → 追加 type=embedding 条目） */
function EmbeddingPicker({ onAdd }: { onAdd: (providerId: number, modelId: string) => void }) {
  const { t } = useI18n();
  const providers = useModelsStore((s) => s.providers);
  const [providerId, setProviderId] = useState<string>('');
  const [modelId, setModelId] = useState('');

  return (
    <div className="space-y-3 rounded-md border border-line p-4">
      <Select value={providerId || undefined} onValueChange={setProviderId}>
        <SelectTrigger data-testid="setup-embedding-provider" className="w-full">
          <SelectValue placeholder={t('setup.embeddingProvider')} />
        </SelectTrigger>
        <SelectContent>
          {providers.map((p) => (
            <SelectItem key={p.id} value={String(p.id)}>
              {p.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <input
        data-testid="setup-embedding-model"
        aria-label={t('setup.embeddingModel')}
        className="w-full rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
        value={modelId}
        onChange={(e) => setModelId(e.target.value)}
        placeholder="embedding-3"
      />
      <button
        type="button"
        data-testid="setup-add-embedding"
        disabled={!providerId || !modelId.trim()}
        className="flex items-center gap-1 rounded-md border border-line px-4 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 disabled:opacity-50"
        onClick={() => onAdd(Number(providerId), modelId)}
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
        {t('setup.addEmbedding')}
      </button>
    </div>
  );
}
