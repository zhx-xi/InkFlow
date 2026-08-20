/**
 * #526 全局默认模型卡片（设置页模型分类最上方）：
 * GET /api/v1/config 回显当前 default_model，切换 → PATCH /api/v1/config { llm_default_model }。
 */
import { useEffect, useMemo, useState } from 'react';
import { fetchConfig, patchConfig } from '../api/config';
import { useI18n } from '../i18n/useI18n';
import { selectChatModelOptions, useModelsStore } from '../stores/models';
import { useToastStore } from '../stores/toast';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

export function GlobalDefaultModelCard() {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const providers = useModelsStore((s) => s.providers);
  const [defaultModel, setDefaultModel] = useState('');

  // #526：挂载拉取当前全局默认模型（失败静默，不炸 UI）
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchConfig();
        if (cancelled || !data) return;
        setDefaultModel(data.default_model ?? '');
      } catch {
        // 失败静默（内核未就绪等），Select 仍渲染
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** chat 模型扁平化选项（provider/model 格式，F42 #268 selectChatModelOptions） */
  const chatModelOptions = useMemo(() => selectChatModelOptions(providers), [providers]);

  /** #526：切换 → PATCH /api/v1/config { llm_default_model } → 成功 toast ok / 失败 err */
  const handleChange = async (value: string) => {
    try {
      await patchConfig(value);
      setDefaultModel(value);
      pushToast('ok', t('toast.saved'));
    } catch {
      pushToast('err', t('toast.saveFailed'));
    }
  };

  // 无 chat 模型 → 不渲染 Select（设置页模型分类其余卡片不受影响）
  if (chatModelOptions.length === 0) {
    return null;
  }

  return (
    <section className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
        <span>{t('set.globalModel.label')}</span>
        <Select value={defaultModel} onValueChange={(v) => void handleChange(v)}>
          <SelectTrigger
            data-testid="global-model-select"
            aria-label={t('set.globalModel.label')}
            className="w-56"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {chatModelOptions.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </section>
  );
}
