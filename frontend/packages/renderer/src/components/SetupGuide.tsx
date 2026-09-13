/**
 * F60 首启模型配置引导（#934 §5）—— 三步最小闭环，GUI 主路径。
 *
 * 触发：App 层据 useModelReadinessStore.readiness.ready === false 渲染本组件
 * （全屏封面，同 BootGate 模式，不可 ESC 关闭）。
 *
 * 三步（spec §5.2-§5.4）：
 *   1. Provider + API Key（复用 ProviderDialog）
 *   2. chat 模型（必填，候选来自 provider /models 实时探测）+ 连通探测
 *      （复用 POST /settings/llm/test）
 *   3. embedding 模型（可跳过 → 语义检索置灰，不阻断）
 *
 * 完成判据 = 后端 readiness 复核为 true（本组件不自判——完成动作后调
 * readiness.load()，由 App 层据新判据卸载本组件）。
 */
import { useEffect, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Plus } from 'lucide-react';
import { apiFetch, errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { selectChatModelOptions, useModelsStore } from '../stores/models';
import type { ProviderConfig } from '../stores/models';
import { useModelReadinessStore } from '../stores/modelReadiness';
import { useToastStore } from '../stores/toast';
import { ProviderDialog } from './ProviderDialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

interface LlmTestResponse {
  ok: boolean;
  message?: string;
  error?: string;
}

/** POST /provider-configs/models 响应信封（与 ProviderDialog 同契约） */
interface FetchModelsResponse {
  ok: boolean;
  models?: string[];
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
  /** #1152：非空 = 打开对话框为「编辑该 provider」而非「新建」 */
  const [editingProvider, setEditingProvider] = useState<ProviderConfig | null>(null);
  const [selectedModel, setSelectedModel] = useState('');
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);
  /** #1152 缺陷 3：步骤 2 实时探测到的 chat 候选（空 = 退回静态候选） */
  const [probedOptions, setProbedOptions] = useState<Array<{ value: string; label: string }>>([]);
  const [discovering, setDiscovering] = useState(false);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  // #1129 静态候选（注册表 models[] + 信封 chat_model_source）——#1152 起仅作兜底
  const staticChatOptions = selectChatModelOptions(providers, chatModelSource);
  // #1152 缺陷 3：探测有结果就以**探测结果**为准（注册表 models[] 实测恒空 → 只认
  // 静态候选的下拉是空的，用户死路）；探测无结果/失败 → 退回静态候选
  const chatOptions = probedOptions.length > 0 ? probedOptions : staticChatOptions;

  /** 步骤 2 chat 候选实时探测（#1152 缺陷 3）：按 provider 打
   *  POST /api/v1/provider-configs/models（后端 api_key 缺省时自行回退 keychain）
   *  → 上游真实模型列表。上游多为裸模型名，这里统一拼成下拉契约值 `provider/model`
   *  （与静态候选、llm/test 的 model 入参同格式）。
   */
  const discoverChatModels = async () => {
    // 取 store 现值：loadProviders 刚刷新过，渲染闭包里的 providers 可能已过期
    const current = useModelsStore.getState().providers;
    if (current.length === 0) return;
    setDiscovering(true);
    setDiscoveryError(null);
    const found: Array<{ value: string; label: string }> = [];
    const seen = new Set<string>();
    let failure: string | null = null;
    // #1152 缺陷 A：收尾语句必须无论中途如何都执行——单个 provider 的异常若逃逸出循环，
    // probedOptions 会保持空 → 下拉退回静态候选（用户看到错误的模型来源）
    try {
      for (const p of current) {
        // base_url 为 null/空（实测 openai 走 SDK 默认端点，值就是 null）→ 无法探测：
        // 跳过、不计失败，且不得因 `.trim()` 抛 TypeError 中断其余 provider 的探测
        const baseUrl = String(p.base_url ?? '').trim();
        if (!baseUrl) continue;
        try {
          const res = await apiFetch<FetchModelsResponse>('/api/v1/provider-configs/models', {
            method: 'POST',
            body: { base_url: baseUrl, provider: p.name },
          });
          if (!res.ok) {
            failure = res.message ?? res.error ?? t('setup.testUnknown');
            continue;
          }
          for (const raw of res.models ?? []) {
            const modelId = raw.trim();
            const value = `${p.name}/${modelId}`;
            if (!modelId || seen.has(value)) continue;
            seen.add(value);
            found.push({ value, label: value });
          }
        } catch (err) {
          // 单个 provider 探测异常只记失败，继续扫其余 provider
          failure = errorMessage(err);
        }
      }
    } finally {
      setProbedOptions(found);
      // 有候选就不弹错（部分 provider 探测失败不挡主路径）；一个都没有才提示
      setDiscoveryError(found.length > 0 ? null : failure);
      setDiscovering(false);
    }
  };

  /** 步骤 1 → 2：至少一个 provider 已注册（key 由 ProviderDialog 内联存储） */
  const hasProvider = providers.length > 0;

  /** 步骤 1 → 2：先重拉 provider 列表（#1152：chat_model_source 随信封闭包同回，
   *  挂载时可能尚未就绪 → 不刷新则步骤 2 下拉为空、引导页死路），再切步 */
  const handleGoToStep2 = async () => {
    await loadProviders();
    setStep(2);
    await discoverChatModels();
  };

  /** #1152：provider 行可点 → 打开对话框并预填该 provider（复用 ProviderDialog editing） */
  const handleEditProvider = (p: ProviderConfig) => {
    setEditingProvider(p);
    setProviderDialogOpen(true);
  };

  const handleProviderRowKeyDown = (
    e: ReactKeyboardEvent<HTMLDivElement>,
    p: ProviderConfig,
  ) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleEditProvider(p);
    }
  };

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
        },
      });
      if (!res.ok) {
        // N5：留在步骤 2，错误可读，可重试
        setTestError(res.message ?? res.error ?? t('setup.testUnknown'));
        return;
      }
      // 探测通过 → 落 provider 默认模型（provider/model 格式，spec §5.3）
      // #1152 缺陷 B：设置页「模型表」渲染的是 provider.models[]，只写 default_model
      // 会让用户以为没生效（还得手动再加）→ 同一次 PATCH 把选中模型并入 models[]
      if (provider) {
        // 下拉值是 `provider/model`，models[].id 是裸模型名 → 按首个 `/` 切掉前缀
        const sep = selectedModel.indexOf('/');
        const bareModel = (sep === -1 ? selectedModel : selectedModel.slice(sep + 1)).trim();
        // 幂等：先按 id 剔除已有条目再补 chat 条目（= store.addModel 的全量替换语义），
        // 同名 chat 模型不会重复出现，其余模型原样保留
        const models = provider.models.filter((m) => m.id !== bareModel);
        if (bareModel) models.push({ id: bareModel, type: 'chat', roles: [] });
        try {
          await apiFetch(`/api/v1/provider-configs/${provider.id}`, {
            method: 'PATCH',
            body: { default_model: selectedModel, models },
          });
        } catch (err) {
          // 落表失败不阻断主路径（连通探测已通过）；提示后照常进入步骤 3
          pushToast('err', errorMessage(err));
        }
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
                    role="button"
                    tabIndex={0}
                    onClick={() => handleEditProvider(p)}
                    onKeyDown={(e) => handleProviderRowKeyDown(e, p)}
                    className="flex cursor-pointer items-center justify-between rounded-md border border-line px-3 py-2 text-[13px] transition duration-180 hover:bg-surface-3"
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
                onClick={() => void handleGoToStep2()}
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
              {discovering && <p className="text-[12px] text-ink-3">{t('m.fetchingModels')}</p>}
              {discoveryError && (
                <p data-testid="setup-models-error" className="text-[12px] text-err">
                  {discoveryError}
                </p>
              )}
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
        editing={editingProvider}
        onOpenChange={(o) => {
          setProviderDialogOpen(o);
          if (!o) setEditingProvider(null);
        }}
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
