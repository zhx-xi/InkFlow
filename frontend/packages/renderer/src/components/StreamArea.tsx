/** SSE 流式区（spec §4.5）：生成中 live 标记 + 停止；done 摘要行；format_valid=false warnings + 手动重试 */
import { useI18n } from '../i18n/useI18n';
import type { StreamStatus, StreamSummary } from '../hooks/useStream';

export interface StreamAreaProps {
  status: StreamStatus;
  text: string;
  wordCount: number;
  summary: StreamSummary | null;
  error: string | null;
  onStop: () => void;
  onRetry: () => void;
}

export function StreamArea({ status, text, wordCount, summary, error, onStop, onRetry }: StreamAreaProps) {
  const { t } = useI18n();
  return (
    <div data-testid="stream-area" className="min-h-[84px] border-t border-line bg-surface px-6 py-3 text-[13px]">
      {status === 'generating' && (
        <div className="mb-2 flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-err">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-err" />
            {t('write.stream.generating')}
          </span>
          <span className="text-ink-3">
            {wordCount} {t('sb.words')}
          </span>
          <button
            type="button"
            className="ml-auto rounded border border-line px-2.5 py-1 text-[12px] text-ink-2 hover:bg-surface-2"
            onClick={onStop}
          >
            {t('write.stream.stop')}
          </button>
        </div>
      )}
      {text && <div className="whitespace-pre-wrap leading-[1.85]">{text}</div>}
      {status === 'idle' && !text && <div className="text-ink-3">{t('write.stream.idle')}</div>}
      {status === 'done' && summary && (
        <div className="mt-2 border-t border-line pt-2">
          <div className="flex items-center gap-3">
            <span className={summary.formatValid === false ? 'text-err' : 'text-ok'}>
              {t('write.stream.done', {
                words: summary.wordCount ?? 0,
                model: summary.model ?? '—',
                valid: summary.formatValid === false ? t('write.stream.invalid') : t('write.stream.valid'),
              })}
            </span>
            {summary.formatValid === false && (
              <button
                type="button"
                className="rounded border border-line px-2.5 py-0.5 text-[12px] text-ink-2 hover:bg-surface-2"
                onClick={onRetry}
              >
                {t('write.retry')}
              </button>
            )}
          </div>
          {summary.formatValid === false &&
            (summary.warnings ?? []).map((w) => (
              <div key={w} className="mt-1 text-err">
                {w}
              </div>
            ))}
        </div>
      )}
      {status === 'error' && error && <div className="text-err">{t('write.stream.error', { message: error })}</div>}
      {status === 'stopped' && <div className="text-ink-2">{t('write.stream.stopped')}</div>}
    </div>
  );
}
