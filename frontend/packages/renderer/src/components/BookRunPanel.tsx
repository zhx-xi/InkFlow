/** 运行状态/进度面板（F44 阶段1）：runId 非空时挂载轮询 GET /runs/{id}，1s 间隔至终态 */
import { useEffect, useRef } from 'react';
import { useI18n } from '../i18n/useI18n';
import { useBookStore } from '../stores/book';
import { ExecutionTraceRow } from './ExecutionTraceRow';

const POLL_INTERVAL_MS = 1000;

export function BookRunPanel() {
  const { t } = useI18n();
  const runId = useBookStore((s) => s.runId);
  const runStatus = useBookStore((s) => s.runStatus);
  const progress = useBookStore((s) => s.progress);
  const counters = useBookStore((s) => s.counters);
  const loadRunStatus = useBookStore((s) => s.loadRunStatus);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
          <div data-testid="run-progress-list" className="space-y-1">
            {Object.entries(progress ?? {}).map(([outlineId, status]) => (
              <ExecutionTraceRow key={outlineId} outlineId={outlineId} status={status} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
