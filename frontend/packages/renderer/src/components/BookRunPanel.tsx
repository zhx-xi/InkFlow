/** 运行状态/进度面板（F44 阶段1）：runId 非空时挂载轮询 GET /runs/{id}，1s 间隔至终态 */
import { useEffect, useRef } from 'react';
import { useI18n } from '../i18n/useI18n';
import { useBookStore } from '../stores/book';
import { ExecutionTraceRow } from './ExecutionTraceRow';
import { VolumeHITLDialog } from './VolumeHITLDialog';

const POLL_INTERVAL_MS = 1000;

export function BookRunPanel() {
  const { t } = useI18n();
  const runId = useBookStore((s) => s.runId);
  const runStatus = useBookStore((s) => s.runStatus);
  const progress = useBookStore((s) => s.progress);
  const counters = useBookStore((s) => s.counters);
  const progressStats = useBookStore((s) => s.progressStats);
  const loadRunStatus = useBookStore((s) => s.loadRunStatus);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showTokens = counters?.max_tokens !== undefined && counters.tokens_used !== undefined;
  const barPercent =
    progressStats.total > 0 ? Math.min(100, Math.round((progressStats.done / progressStats.total) * 100)) : 0;

  useEffect(() => {
    if (runId === null) return;
    let cancelled = false;
    const poll = async () => {
      await loadRunStatus(runId);
      if (cancelled) return;
      const status = useBookStore.getState().runStatus;
      if (status === 'running' || status === 'pending') {
        timerRef.current = setTimeout(() => {
          void poll();
        }, POLL_INTERVAL_MS);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, [runId, loadRunStatus]);

  return (
    <div data-testid="book-run-panel" className="rounded-md border border-line bg-surface-2 p-3">
      {runId === null ? (
        <p className="text-[13px] text-ink-3">{t('book.run.noRun')}</p>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-[12px] text-ink-3">{t('book.run.status')}</span>
            <span
              data-testid="run-status"
              className="rounded bg-surface-3 px-1.5 py-0.5 text-[12px] text-ink"
            >
              {runStatus ?? '–'}
            </span>
          </div>
          <div data-testid="run-counter-chapters" className="text-[13px] text-ink-2">
            {t('book.run.chapters')}: {counters ? `${counters.chapters_written} / ${counters.max_chapters}` : '–'}
          </div>
          <div data-testid="run-counter-calls" className="text-[13px] text-ink-2">
            {t('book.run.calls')}: {counters ? `${counters.agent_calls} / ${counters.max_agent_calls}` : '–'}
          </div>
          {showTokens && (
            <div data-testid="run-counter-tokens" className="text-[13px] text-ink-2">
              {t('book.run.tokens')}: {counters.tokens_used} / {counters.max_tokens}
            </div>
          )}
          {counters?.tokens_warning === true && (
            <div
              data-testid="run-token-warning"
              className="rounded border border-warn/40 bg-warn/10 px-2 py-1 text-[12px] text-warn"
            >
              {t('book.run.tokenWarning')}
            </div>
          )}
          {progressStats.total > 0 && (
            <div className="space-y-1">
              <div data-testid="run-progress-bar" className="text-[13px] text-ink-2">
                {t('book.run.chapters')}: {progressStats.done} / {progressStats.total}
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
                <div
                  className="h-full rounded-full bg-accent/70 transition-all"
                  style={{ width: `${barPercent}%` }}
                />
              </div>
            </div>
          )}
          <div data-testid="run-progress-list" className="space-y-1">
            {Object.entries(progress ?? {}).map(([outlineId, status]) => (
              <ExecutionTraceRow key={outlineId} outlineId={outlineId} status={status} />
            ))}
          </div>
          <VolumeHITLDialog />
        </div>
      )}
    </div>
  );
}
