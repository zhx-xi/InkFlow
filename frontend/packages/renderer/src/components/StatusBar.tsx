/** 状态栏（spec §4.2.1）：内核连接 / 模型 / 字数 / 自动保存 */
import { useI18n } from '../i18n/useI18n';

export interface StatusBarProps {
  model: string | null;
  wordCount: number;
  savedAt: Date | null;
}

export function StatusBar({ model, wordCount, savedAt }: StatusBarProps) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-5 border-t border-line bg-surface px-4 py-1.5 text-[11px] text-ink-3">
      <span>{t('sb.kernel')}</span>
      <span>
        {t('sb.model')}: {model ?? '—'}
      </span>
      <span>
        {t('sb.words')}: {wordCount.toLocaleString()}
      </span>
      <span>
        {t('sb.autosave')}: {savedAt ? savedAt.toLocaleTimeString() : '—'}
      </span>
    </div>
  );
}
