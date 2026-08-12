/**
 * Provider 添加/编辑弹窗（Issue #106，spec §8.2③ / §8.3 / §8.6 M2）：
 * 名称/预置模板/Base URL/API Key + 测试连接 toast + 保存（注册表）。
 * 关闭路径：取消 / ESC / 遮罩 → onOpenChange(false)。
 */
import { useEffect, useState } from 'react';
import { apiFetch, errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import type { ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

interface LlmTestResponse {
  ok: boolean;
  message?: string;
  error?: string;
}

export interface ProviderDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing?: ProviderConfig | null;
  onSaved: (provider: ProviderConfig) => void;
}

/** 名称校验（与 settings.py LLMKeyStoreRequest.validate_provider 一致：^[a-z0-9_-]{1,32}$） */
const NAME_RE = /^[a-z0-9_-]{1,32}$/;

/**
 * 预置模板（后端 seed 4 个：openai/deepseek/zhipu/ollama）。
 * #106 F7：base_url 与 backend infrastructure/llm/provider_config.py
 * _PROVIDER_BASE_URLS 对齐——deepseek /v1、ollama /v1、zhipu 尾斜杠、
 * openai 空（SDK 默认端点）。
 */
const PRESET_TEMPLATES: Array<{ name: string; base_url: string; model: string }> = [
  { name: 'openai', base_url: '', model: '' },
  { name: 'deepseek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  { name: 'zhipu', base_url: 'https://open.bigmodel.cn/api/paas/v4/', model: 'glm-4-flash' },
  { name: 'ollama', base_url: 'http://localhost:11434/v1', model: 'qwen2.5' },
];

export function ProviderDialog({ open, onOpenChange, editing = null, onSaved }: ProviderDialogProps) {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const [name, setName] = useState(editing?.name ?? '');
  const [baseUrl, setBaseUrl] = useState(editing?.base_url ?? '');
  const [model, setModel] = useState(editing?.default_model ?? '');
  const [apiKey, setApiKey] = useState('');
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  // 打开时同步编辑值（editing 变化重开弹窗场景）
  useEffect(() => {
    if (!open) return;
    setName(editing?.name ?? '');
    setBaseUrl(editing?.base_url ?? '');
    setModel(editing?.default_model ?? '');
    setApiKey('');
  }, [open, editing]);

  // ESC 关闭：document 级监听；尊重 Radix Select 已 preventDefault 的 Escape
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onOpenChange(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onOpenChange]);

  if (!open) return null;

  const trimmedName = name.trim();
  const nameValid = NAME_RE.test(trimmedName);
  const saveDisabled = !nameValid || saving;

  const handlePreset = (presetName: string) => {
    const preset = PRESET_TEMPLATES.find((p) => p.name === presetName);
    if (!preset) return;
    setName(preset.name);
    setBaseUrl(preset.base_url);
    setModel(preset.model);
  };

  const handleTest = async () => {
    if (testing) return;
    setTesting(true);
    try {
      const trimmedModel = model.trim();
      const res = await apiFetch<LlmTestResponse>('/api/v1/settings/llm/test', {
        method: 'POST',
        body: {
          provider: trimmedName,
          ...(trimmedModel ? { model: trimmedModel } : {}),
          base_url: baseUrl,
          api_key: apiKey,
        },
      });
      if (res.ok) {
        pushToast('ok', t('m.dialog.testOk'));
      } else {
        pushToast(
          'err',
          t('m.dialog.testFail', {
            reason: res.message ?? res.error ?? t('m.dialog.testUnknown'),
          }),
        );
      }
    } catch (err) {
      pushToast('err', t('m.dialog.testFail', { reason: errorMessage(err) }));
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    if (saveDisabled) return;
    setSaving(true);
    try {
      // 填了 Key 先加密落盘（复用 #79 /settings/llm-keys），再注册/更新 provider-configs
      if (apiKey) {
        await apiFetch('/api/v1/settings/llm-keys', {
          method: 'POST',
          body: { provider: trimmedName, api_key: apiKey },
        });
      }
      let saved: ProviderConfig;
      if (editing) {
        saved = await apiFetch<ProviderConfig>(`/api/v1/provider-configs/${editing.id}`, {
          method: 'PATCH',
          body: { name: trimmedName, base_url: baseUrl },
        });
      } else {
        saved = await apiFetch<ProviderConfig>('/api/v1/provider-configs', {
          method: 'POST',
          body: { name: trimmedName, base_url: baseUrl },
        });
      }
      onSaved(saved);
      onOpenChange(false);
    } catch {
      pushToast('err', t('toast.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={() => {
        if (!saving) onOpenChange(false);
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={editing ? t('m.editProvider') : t('m.addProvider')}
        data-testid="provider-dialog"
        className="w-[460px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">
          {editing ? t('m.editProvider') : t('m.addProvider')}
        </h2>
        <div className="mt-4 space-y-3">
          {!editing && (
            <div className="flex flex-col gap-1.5 text-[13px]">
              <span>{t('m.preset')}</span>
              <Select value={undefined} onValueChange={handlePreset}>
                <SelectTrigger aria-label={t('m.preset')} className="w-full">
                  <SelectValue placeholder={t('m.presetPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {PRESET_TEMPLATES.map((p) => (
                    <SelectItem key={p.name} value={p.name}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('m.name')}</span>
            <input
              aria-label={t('m.name')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="openai"
            />
            {trimmedName !== '' && !nameValid && (
              <p className="text-[12px] text-err">{t('m.nameInvalid')}</p>
            )}
          </label>
          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('m.model')}</span>
            <input
              aria-label={t('m.model')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="gpt-4o"
            />
          </label>
          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('m.baseUrl')}</span>
            <input
              aria-label={t('m.baseUrl')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
            />
          </label>
          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('m.apiKey')}</span>
            <input
              type="password"
              aria-label={t('m.apiKey')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              autoComplete="off"
            />
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            disabled={testing}
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3 disabled:opacity-50"
            onClick={() => void handleTest()}
          >
            {t('ag.test')}
          </button>
          <button
            type="button"
            disabled={saveDisabled}
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:opacity-50"
            onClick={() => void handleSave()}
          >
            {t('ag.save')}
          </button>
        </div>
      </div>
    </div>
  );
}
