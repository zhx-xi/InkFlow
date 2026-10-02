/**
 * 运行状态/进度面板（F44 阶段1）：runId 非空时挂载轮询 GET /runs/{id}，1s 间隔至终态。
 * F44 阶段4（#338 S4b）：干预工具栏（pause/resume + 密度三档 Segmented + 摘要开关）+ diff banner +
 * 回归摘要面板；silent 密度下不渲染 run-progress-list（纯前端本地 density 状态）。
 */
import { Fragment, useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import { startPolling } from '../lib/polling';
import { useBookStore } from '../stores/book';
import type { InterveneDiff, RunSummaryStep } from '../api/books';
import { useDataChangeSubscription } from '../hooks/useDataChangeSubscription';
import { BookSummaryPanel } from './BookSummaryPanel';
import { ConfirmDialog } from './ConfirmDialog';
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
  blocked: 'run-badge-blocked bg-warn/10 text-warn',
};

/** #1333 N16：书级运行状态 → i18n 文案（仅 blocked 收编；completed/failed/degraded 保持原文透传） */
const RUN_STATUS_LABEL_KEYS: Record<string, string> = {
  blocked: 'book.run.status.blocked',
};

/** #903：终态失败原因折叠阈值（先例 memory EXPAND_THRESHOLD = 200） */
const REASON_EXPAND_THRESHOLD = 200;

/** #1333：任务看板行（steps 缺失时由 progress 回退派生）。 */
interface TaskRow {
  outlineId: string;
  liveStatus: string;
  executionId?: string;
  name?: string;
  substeps: { op: string; status: 'done' | 'now' }[];
}

/** #1333 N24：按卷分组；volumeName=null 表示无卷分组（平铺，不折叠）。 */
interface TaskGroup {
  volumeName: string | null;
  rows: TaskRow[];
}

/** summary.steps 的 substeps（status: string）→ ExecutionTraceRow 的 done/now 二态（仅 now 有区分语义） */
function toTraceSubsteps(
  substeps: RunSummaryStep['substeps'],
): { op: string; status: 'done' | 'now' }[] {
  return (substeps ?? []).map((s) => ({ op: s.op, status: s.status === 'now' ? 'now' : 'done' }));
}

export function BookRunPanel() {
  const { t } = useI18n();
  const [showSummary, setShowSummary] = useState(false);
  const [reasonExpanded, setReasonExpanded] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  // #1333 N18：实时渠道指示（默认连接中；订阅就绪/推送到达 → connected）
  const [liveConnected, setLiveConnected] = useState(false);
  // #1333 N24：卷分组手动展开覆盖（缺省时按「全 done 折叠」推导）
  const [volumeExpanded, setVolumeExpanded] = useState<Record<number, boolean>>({});
  const runId = useBookStore((s) => s.runId);
  const runStatus = useBookStore((s) => s.runStatus);
  const progressReason = useBookStore((s) => s.progressReason);
  const progress = useBookStore((s) => s.progress);
  const counters = useBookStore((s) => s.counters);
  const progressStats = useBookStore((s) => s.progressStats);
  const density = useBookStore((s) => s.density);
  const interveneDiff = useBookStore((s) => s.interveneDiff);
  const summary = useBookStore((s) => s.summary);
  const loadRunStatus = useBookStore((s) => s.loadRunStatus);
  const loadSummary = useBookStore((s) => s.loadSummary);
  const resetRun = useBookStore((s) => s.resetRun);
  const interveneRun = useBookStore((s) => s.interveneRun);
  const setDensity = useBookStore((s) => s.setDensity);
  const clearInterveneDiff = useBookStore((s) => s.clearInterveneDiff);

  const showTokens = counters?.max_tokens !== undefined && counters.tokens_used !== undefined;
  const showReason =
    (runStatus === 'failed' || runStatus === 'degraded' || runStatus === 'blocked') &&
    progressReason !== null &&
    progressReason.length > 0;
  const statusLabelKey = RUN_STATUS_LABEL_KEYS[runStatus ?? ''];
  const reasonLong = progressReason !== null && progressReason.length > REASON_EXPAND_THRESHOLD;
  const barPercent =
    progressStats.total > 0 ? Math.min(100, Math.round((progressStats.done / progressStats.total) * 100)) : 0;

  // #1333：章名/卷名/章内步骤来自 summary.steps；未就绪 → 回退 progress（零回归旧形态）
  const steps = Array.isArray(summary?.steps) && summary.steps.length > 0 ? summary.steps : null;
  const taskGroups: TaskGroup[] = steps
    ? steps.reduce<TaskGroup[]>((groups, step) => {
        const volumeName =
          typeof step.volume_name === 'string' && step.volume_name.length > 0 ? step.volume_name : null;
        const row: TaskRow = {
          outlineId: step.outline_id,
          liveStatus: progress[step.outline_id] ?? step.status,
          executionId: step.execution_id ?? undefined,
          name: step.name,
          substeps: toTraceSubsteps(step.substeps),
        };
        const last = groups[groups.length - 1];
        if (last !== undefined && last.volumeName === volumeName) {
          last.rows.push(row);
        } else {
          groups.push({ volumeName, rows: [row] });
        }
        return groups;
      }, [])
    : [
        {
          volumeName: null,
          rows: Object.entries(progress ?? {}).map(([outlineId, status]) => ({
            outlineId,
            liveStatus: status,
            substeps: [],
          })),
        },
      ];

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

  // #1333 N14：summary 仅按「progress 键集变化」触发（不随 1s 轮询每 tick 重拉）
  const summaryKeySetRef = useRef<string | null>(null);
  useEffect(() => {
    if (runId === null) {
      summaryKeySetRef.current = null;
      return;
    }
    const keys = Object.keys(progress ?? {});
    if (keys.length === 0) return;
    const keySet = [...keys].sort().join('\u0000');
    if (summaryKeySetRef.current === keySet) return;
    summaryKeySetRef.current = keySet;
    void loadSummary(runId);
  }, [runId, progress, loadSummary]);

  // #1333 N18：SSE 推送为主通道（轮询仍为既有兜底）；断连时静默降级，不抛错不阻断渲染
  useDataChangeSubscription(['writing_plan'], (ev) => {
    if (runId === null) return;
    if (ev === null || ev.domain === 'writing_plan') {
      setLiveConnected(true);
      void loadRunStatus(runId);
    }
  });

  if (runId === null) return null;  // #1333 N26: 产品路径不可达（唯一消费者以 runId!==null 门控）

  return (
    <div data-testid="book-run-panel" className="rounded-md border border-line bg-surface-2 p-3">
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
            {statusLabelKey ? t(statusLabelKey) : (runStatus ?? '-')}
          </span>
          <span
            data-testid="run-live"
            data-live={liveConnected ? 'connected' : 'connecting'}
            className="text-[12px] text-ink-3"
          >
            {liveConnected ? t('book.run.live.connected') : t('book.run.live.connecting')}
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
          {runStatus !== 'running' && (
            <button
              type="button"
              data-testid="run-reset"
              className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
              onClick={() => setResetOpen(true)}
            >
              {t('book.run.reset')}
            </button>
          )}
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
          <div data-testid="run-task-list">
            <div data-testid="run-progress-list" className="space-y-2">
              {taskGroups.map((group, i) => {
                const completed = group.rows.every((row) => row.liveStatus === 'done');
                if (group.volumeName === null) {
                  return (
                    <Fragment key={`inline-${i}`}>
                      {group.rows.map((row) => (
                        <ExecutionTraceRow
                          key={row.outlineId}
                          outlineId={row.outlineId}
                          status={row.liveStatus}
                          executionId={row.executionId}
                          name={row.name}
                          substeps={row.substeps}
                        />
                      ))}
                    </Fragment>
                  );
                }
                const expanded = volumeExpanded[i] ?? !completed;
                return (
                  <div key={`volume-${i}`} data-testid={`task-volume-${i}`} className="space-y-1">
                    <div className="flex items-center gap-1.5">
                      <span
                        data-testid={`task-volume-header-${i}`}
                        className="text-[12px] font-medium text-ink-2"
                      >
                        {group.volumeName}
                      </span>
                      <button
                        type="button"
                        data-testid={`task-volume-toggle-${i}`}
                        aria-expanded={expanded}
                        aria-label={group.volumeName}
                        className="flex h-5 w-5 items-center justify-center rounded text-ink-2 transition-colors hover:bg-surface-3 hover:text-ink"
                        onClick={() =>
                          setVolumeExpanded((prev) => ({ ...prev, [i]: !(prev[i] ?? !completed) }))
                        }
                      >
                        {expanded ? (
                          <ChevronDown className="h-4 w-4" aria-hidden="true" />
                        ) : (
                          <ChevronRight className="h-4 w-4" aria-hidden="true" />
                        )}
                      </button>
                    </div>
                    {expanded && (
                      <div data-testid={`task-volume-body-${i}`} className="space-y-1">
                        {group.rows.map((row) => (
                          <ExecutionTraceRow
                            key={row.outlineId}
                            outlineId={row.outlineId}
                            status={row.liveStatus}
                            executionId={row.executionId}
                            name={row.name}
                            substeps={row.substeps}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
        {showSummary && <BookSummaryPanel />}
        {resetOpen && (
          <ConfirmDialog
            open={resetOpen}
            title={t('book.run.reset.title')}
            message={t('book.run.reset.message')}
            confirmText={t('book.run.reset.confirm')}
            danger
            testidPrefix="run-reset"
            onConfirm={() => {
              setResetOpen(false);
              void resetRun();
            }}
            onOpenChange={(open) => setResetOpen(open)}
          />
        )}
        <VolumeHITLDialog />
      </div>
    </div>
  );
}
