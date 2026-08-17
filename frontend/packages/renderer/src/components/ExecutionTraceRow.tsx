/**
 * 子 agent 展开行（F44 阶段1）：progress[outline_id] → PlanNodeStatus 摘要行，默认折叠。
 * F44 阶段4（#338 S4b）：performance 密度下渲染章行内干预控件（redirect 三档 + edit 行内 brief
 * 编辑）+ interveneDiff 目标行 diff 高亮；已完成章（done）干预控件禁用（422 防呆）。
 */
import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';
import { useBookStore } from '../stores/book';
import type { InterveneDiff } from '../api/books';
import { cn } from '../lib/cn';

export interface ExecutionTraceRowProps {
  outlineId: string;
  status: string;
  executionId?: string;
}

/** PlanNodeStatus → i18n key（pending/in_progress/done/failed/skipped） */
const STATUS_LABEL_KEYS: Record<string, string> = {
  pending: 'book.trace.pending',
  in_progress: 'book.trace.in_progress',
  done: 'book.trace.done',
  failed: 'book.trace.failed',
  skipped: 'book.trace.skipped',
};

/** 阶段2 状态徽标语义类（五态可区分；低饱和色块，ui-design-taste 克制原则） */
const STATUS_BADGE_CLASSES: Record<string, string> = {
  pending: 'badge-pending',
  in_progress: 'badge-in_progress',
  done: 'badge-done',
  failed: 'badge-failed',
  skipped: 'badge-skipped',
};

/** 干预 diff 展示文本（redirect：from→to；edit：diff 文本或 before/after） */
function renderDiffText(diff: InterveneDiff): string {
  if (diff.diff !== undefined) return diff.diff;
  if (diff.from !== undefined && diff.to !== undefined) return `${diff.from} → ${diff.to}`;
  if (diff.before !== undefined && diff.after !== undefined) return `${diff.before} → ${diff.after}`;
  return diff.after ?? diff.before ?? '';
}

export function ExecutionTraceRow({ outlineId, status, executionId }: ExecutionTraceRowProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [brief, setBrief] = useState('');
  const density = useBookStore((s) => s.density);
  const interveneDiff = useBookStore((s) => s.interveneDiff);
  const interveneRun = useBookStore((s) => s.interveneRun);
  const labelKey = STATUS_LABEL_KEYS[status] ?? 'book.trace.pending';
  const badgeClass = STATUS_BADGE_CLASSES[status] ?? STATUS_BADGE_CLASSES.pending;
  const done = status === 'done';
  const rowDiff = interveneDiff !== null && interveneDiff.target === outlineId ? interveneDiff : null;

  return (
    <div data-testid={`trace-row-${outlineId}`} className="rounded-md border border-line bg-surface-2">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <button
          type="button"
          data-testid={`trace-row-toggle-${outlineId}`}
          aria-label={t('book.trace.detail')}
          aria-expanded={expanded}
          className={cn(
            'flex h-5 w-5 items-center justify-center rounded text-ink-2 transition-colors hover:bg-surface-3 hover:text-ink',
            expanded && 'text-ink',
          )}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4" aria-hidden="true" />
          ) : (
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          )}
        </button>
        <span
          data-testid={`trace-row-status-${outlineId}`}
          className={cn('rounded px-1.5 py-0.5 text-[12px] text-ink-2', badgeClass)}
        >
          {t(labelKey)}
        </span>
        {density === 'performance' && (
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              data-testid={`trace-redirect-skip-${outlineId}`}
              disabled={done}
              className="rounded border border-line px-1.5 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3 disabled:opacity-40"
              onClick={() => void interveneRun('redirect', outlineId, 'skip')}
            >
              {t('book.trace.skip')}
            </button>
            <button
              type="button"
              data-testid={`trace-redirect-retry-${outlineId}`}
              disabled={done}
              className="rounded border border-line px-1.5 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3 disabled:opacity-40"
              onClick={() => void interveneRun('redirect', outlineId, 'retry')}
            >
              {t('book.trace.retry')}
            </button>
            <button
              type="button"
              data-testid={`trace-redirect-markfailed-${outlineId}`}
              disabled={done}
              className="rounded border border-line px-1.5 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3 disabled:opacity-40"
              onClick={() => void interveneRun('redirect', outlineId, 'mark_failed')}
            >
              {t('book.trace.markFailed')}
            </button>
            <button
              type="button"
              data-testid={`trace-edit-${outlineId}`}
              disabled={done}
              className="rounded border border-line px-1.5 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3 disabled:opacity-40"
              onClick={() => {
                setBrief('');
                setEditing((v) => !v);
              }}
            >
              {t('book.trace.edit')}
            </button>
            <button
              type="button"
              data-testid={`trace-edit-cancel-${outlineId}`}
              disabled={done}
              className="rounded border border-line px-1.5 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3 disabled:opacity-40"
              onClick={() => setEditing(false)}
            >
              {t('book.trace.editCancel')}
            </button>
          </div>
        )}
      </div>
      {density === 'performance' && editing && (
        <div data-testid={`trace-edit-area-${outlineId}`} className="border-t border-line px-3 py-2">
          <textarea
            data-testid={`trace-brief-${outlineId}`}
            placeholder={t('book.trace.briefPlaceholder')}
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            className="w-full resize-y rounded border border-line bg-surface px-2 py-1 text-[12px] text-ink outline-none focus:border-accent"
            rows={3}
          />
          <div className="mt-1 flex justify-end gap-1">
            <button
              type="button"
              data-testid={`trace-edit-save-${outlineId}`}
              disabled={done}
              className="rounded bg-accent px-2 py-0.5 text-[12px] text-accent-ink hover:bg-accent-hover disabled:opacity-40"
              onClick={() => void interveneRun('edit', outlineId, undefined, { brief })}
            >
              {t('book.trace.editSave')}
            </button>
          </div>
        </div>
      )}
      {rowDiff !== null && (
        <div
          data-testid={`trace-diff-${outlineId}`}
          className="border-t border-line bg-accent/5 px-3 py-2 text-[12px] text-ink-2"
        >
          {renderDiffText(rowDiff)}
        </div>
      )}
      {expanded && (
        <div
          data-testid={`trace-row-detail-${outlineId}`}
          className="border-t border-line px-3 py-2 text-[12px] text-ink-2"
        >
          <p>{t(labelKey)}</p>
          {executionId !== undefined && (
            <p className="mt-1 text-ink-3">
              {t('book.trace.execution')}: {executionId}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
