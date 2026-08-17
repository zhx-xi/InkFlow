/** 子 agent 展开行（F44 阶段1）：progress[outline_id] → PlanNodeStatus 摘要行，默认折叠 */
import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';
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

export function ExecutionTraceRow({ outlineId, status, executionId }: ExecutionTraceRowProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const labelKey = STATUS_LABEL_KEYS[status] ?? 'book.trace.pending';

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
        <span data-testid={`trace-row-status-${outlineId}`} className="text-[12px] text-ink-2">
          {t(labelKey)}
        </span>
      </div>
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
