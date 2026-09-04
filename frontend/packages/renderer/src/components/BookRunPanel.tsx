/**
 * 运行状态/进度面板（F44 阶段1）：runId 非空时挂载轮询 GET /runs/{id}，1s 间隔至终态。
 * F44 阶段4（#338 S4b）：干预工具栏（pause/resume + 密度三档 Segmented + 摘要开关）+ diff banner +
 * 回归摘要面板；silent 密度下不渲染 run-progress-list（纯前端本地 density 状态）。
 */
import { useEffect, useState } from 'react';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import { startPolling } from '../lib/polling';
import { useBookStore } from '../stores/book';
import type { InterveneDiff } from '../api/books';
import { BookSummaryPanel } from './BookSummaryPanel';
import { ExecutionTraceRow } from './ExecutionTraceRow';
import { VolumeHITLDialog } from './VolumeHITLDialog';

/** 干预 diff 展示文本（redirect：from→to；edit：diff 文本或 before/after；banner 复用） */
function renderDiffText(diff: InterveneDiff): string {
  if (diff.diff !== undefined) return diff.diff;
  if (diff.from !== undefined && diff.to !== undefined) return `${diff.from} → ${diff.to}`;
  if (diff.before !== undefined && diff.after !== undefined) return `${diff.before} → ${diff.after}`;
  return diff.after ?? diff.before ?? '';
}

/** #903：书级运行终态三档语义钩子（先例 ExecutionTraceRow badge-<status>；测试只钉语义类不锁色值） */
const RUN_BADGE_CLASSES: Record<string, string> = {
  completed: 'run-badge-completed bg-ok/10 text-ok',
  failed: 'run-badge-failed bg-err/10 text-err',
  degraded: 'run-badge-degraded bg-warn/10 text-warn',
};

/** #903：终态失败原因折叠阈值（先例 memory EXPAND_THRESHOLD = 200） */
const REASON_EXPAND_THRESHOLD = 200;

export function BookRunPanel() {
  const { t } = useI18n();
  const [showSummary, setShowSummary] = useState(false);
  const [reasonExpanded, setReasonExpanded] = useState(false);
  const runId = useBookStore((s) => s.runId);
  const runStatus = useBookStore((s) => s.runStatus);
  const progressReason = useBookStore((s) => s.progressReason);
  const progress = useBookStore((s) => s.progress);
  const counters = useBookStore((s) => s.counters);
  const progressStats = useBookStore((s) => s.progressStats);
  const density = useBookStore((s) => s.density);
  const interveneDiff = useBookStore((s) => s.interveneDiff);
  const loadRunStatus = useBookStore((s) => s.loadRunStatus);
  const interveneRun = useBookStore((s) => s.interveneRun);
  const setDensity = useBookStore((s) => s.setDensity);
  const clearInterveneDiff = useBookStore((s) => s.clearInterveneDiff);

  const showTokens = counters?.max_tokens !== undefined && counters.tokens_used !== undefined;
  const showReason =
    (runStatus === 'failed' || runStatus === 'degraded') &&
    progressReason !== null &&
    progressReason.length > 0;
  const reasonLong = progressReason !== null && progressReason.length > REASON_EXPAND_THRESHOLD;
  const barPercent =
    progressStats.total > 0 ? Math.min(100, Math.round((progressStats.done / progressStats.total) * 100)) : 0;

  useEffect(() => {
    if (runId === null) return;
    const handle = startPolling(
      async () => {
        await loadRunStatus(runId);
        return useBookStore.getState().runStatus;
      },
      (status) => status !== 'running' && status !== 'pending',
    );
    return () => handle.cancel();
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
              className={cn(
                'rounded px-1.5 py-0.5 text-[12px]',
                RUN_BADGE_CLASSES[runStatus ?? ''] ?? 'bg-surface-3 text-ink',
              )}
            >
              {runStatus ?? '–'}
            </span>
          </div>
          {showReason && progressReason !== null && (
            <div
              data-testid="run-progress-reason"
              className="rounded border border-warn/30 bg-warn/10 px-2 py-1 text-[12px] text-ink-2"
            >
              <span data-testid="run-progress-reason-label" className="font-medium text-warn">
                {t('book.run.reason')}
              </span>
              <p
                data-testid="run-progress-reason-text"
                className={cn('mt-0.5 leading-relaxed', !reasonExpanded && reasonLong && 'line-clamp-3')}
              >
                {progressReason}
              </p>
              {reasonLong && (
                <button
                  type="button"
                  data-testid="run-progress-reason-toggle"
                  className="mt-1 text-accent hover:underline"
                  onClick={() => setReasonExpanded((v) => !v)}
                >
                  {reasonExpanded ? t('book.run.reason.collapse') : t('book.run.reason.expand')}
                </button>
              )}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            {runStatus === 'running' && (
              <button
                type="button"
                data-testid="run-intervene-pause"
                className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
                onClick={() => void interveneRun('pause')}
              >
                {t('book.run.pause')}
              </button>
            )}
            {runStatus === 'paused' && (
              <button
                type="button"
                data-testid="run-intervene-resume"
                className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
                onClick={() => void interveneRun('resume')}
              >
                {t('book.run.resume')}
              </button>
            )}
            <button
              type="button"
              data-testid="run-density-performance"
              aria-pressed={density === 'performance'}
              className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
              onClick={() => setDensity('performance')}
            >
              {t('book.run.density.performance')}
            </button>
            <button
              type="button"
              data-testid="run-density-dashboard"
              aria-pressed={density === 'dashboard'}
              className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
              onClick={() => setDensity('dashboard')}
            >
              {t('book.run.density.dashboard')}
            </button>
            <button
              type="button"
              data-testid="run-density-silent"
              aria-pressed={density === 'silent'}
              className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
              onClick={() => setDensity('silent')}
            >
              {t('book.run.density.silent')}
            </button>
            <button
              type="button"
              data-testid="run-summary-toggle"
              className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
              onClick={() => setShowSummary((v) => !v)}
            >
              {t('book.run.summary')}
            </button>
          </div>
          {interveneDiff !== null && (
            <div
              data-testid="run-diff-banner"
              className="flex items-center gap-2 rounded border border-accent/40 bg-accent/10 px-2 py-1 text-[12px] text-ink-2"
            >
              <span className="font-medium text-ink">{interveneDiff.target}</span>
              <span className="flex-1">{renderDiffText(interveneDiff)}</span>
              <button
                type="button"
                data-testid="run-diff-close"
                className="rounded px-1.5 py-0.5 text-ink-3 hover:bg-surface-3 hover:text-ink"
                onClick={() => clearInterveneDiff()}
              >
                {t('book.diff.close')}
              </button>
            </div>
          )}
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
          {density !== 'silent' && (
            <div data-testid="run-progress-list" className="space-y-1">
              {Object.entries(progress ?? {}).map(([outlineId, status]) => (
                <ExecutionTraceRow key={outlineId} outlineId={outlineId} status={status} />
              ))}
            </div>
          )}
          {showSummary && <BookSummaryPanel />}
          <VolumeHITLDialog />
        </div>
      )}
    </div>
  );
}
