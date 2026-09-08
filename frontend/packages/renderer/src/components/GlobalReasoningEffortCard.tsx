/**
 * F59 #965：全局默认思考强度卡片（设置页 LLM 区，GlobalDefaultModelCard 之后）。
 *
 * 数据面：GET /api/v1/settings 读 default_reasoning_effort（缺省/失败 → 跟随模型默认）；
 * 切换 → PATCH /api/v1/settings { default_reasoning_effort } → 成功 toast ok / 失败 err。
 */
import { useEffect, useState } from 'react';
import { fetchSettings, patchSettings } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useToastStore } from '../stores/toast';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

/** F59 #965：Agent 思考强度七档（值=英文枚举，与后端 ReasoningEffort 对齐） */
const REASONING_LEVELS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'default'] as const;

export function GlobalReasoningEffortCard() {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const [effort, setEffort] = useState('default');

  // 挂载拉取当前全局默认档位（失败静默，Select 仍渲染默认档）
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchSettings();
        if (cancelled || !data) return;
        setEffort(data.default_reasoning_effort ?? 'default');
      } catch {
        // 失败静默（内核未就绪等），Select 仍渲染
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** 切换 → PATCH /api/v1/settings { default_reasoning_effort } → 成功 toast ok / 失败 err */
  const handleChange = async (value: string) => {
    try {
      await patchSettings({ default_reasoning_effort: value });
      setEffort(value);
      pushToast('ok', t('toast.saved'));
    } catch {
      pushToast('err', t('toast.saveFailed'));
    }
  };

  return (
    <section className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
        <span>{t('agent.thinking.globalLabel')}</span>
        <Select value={effort} onValueChange={(v) => void handleChange(v)}>
          <SelectTrigger
            data-testid="global-reasoning-effort-select"
            aria-label={t('agent.thinking.globalLabel')}
            className="w-56"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {REASONING_LEVELS.map((level) => (
              <SelectItem key={level} value={level}>
                {t(`agent.thinking.${level}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </section>
  );
}
