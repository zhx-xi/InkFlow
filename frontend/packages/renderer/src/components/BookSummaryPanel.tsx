/**
 * 回归摘要面板（F44 阶段4 #338 S4b 契约）：无 props，读 useBookStore 的 summary /
 * summaryLoading / loadSummary；挂载时 summary 为空且 runId 非空 → loadSummary(runId)。
 * 展示 progress 派生进度（done/total）、next 卷信息（finished=true → 「全部完成」）、
 * steps 结构化运行日志、导出 JSON（Blob + a[download] 镜像 CLI --export 产物语义）。
 */
import { useEffect } from 'react';
import { useI18n } from '../i18n/useI18n';
import { deriveProgressStats, useBookStore } from '../stores/book';

export function BookSummaryPanel() {
  const { t } = useI18n();
  const runId = useBookStore((s) => s.runId);
  const summary = useBookStore((s) => s.summary);
  const summaryLoading = useBookStore((s) => s.summaryLoading);
  const loadSummary = useBookStore((s) => s.loadSummary);

  useEffect(() => {
    if (summary === null && runId !== null) {
      // 挂载空态契约：loadSummary 同步置 summaryLoading=true（store 中间态断言），
      // 若在 effect 内同步调用会吞掉初始空态帧；延迟到同步渲染帧之后，保证
      // book-summary-empty 初始帧可被同步断言，同时挂载加载（waitFor）不受影响。
      const timer = setTimeout(() => {
        void loadSummary(runId);
      }, 0);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [summary, runId, loadSummary]);

  if (summaryLoading) {
    return <div data-testid="book-summary-loading">{t('book.summary.loading')}</div>;
  }
  if (summary === null) {
    return <div data-testid="book-summary-empty">{t('book.summary.empty')}</div>;
  }

  const stats = deriveProgressStats(summary.progress);

  const handleExport = (): void => {
    const blob = new Blob([JSON.stringify(summary, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `book-summary-${summary.run_id}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      data-testid="book-summary-panel"
      className="rounded-md border border-line bg-surface-2 p-3"
    >
      <div data-testid="book-summary-progress" className="text-[13px] text-ink-2">
        {t('book.summary.progress')}: {stats.done} / {stats.total}
      </div>
      <div data-testid="book-summary-next" className="mt-1 text-[13px] text-ink-2">
        {t('book.summary.next')}:{' '}
        {summary.next.finished
          ? t('book.summary.nextDone')
          : summary.next.volume_index !== undefined && summary.next.total_volumes !== undefined
            ? `${summary.next.volume_index} / ${summary.next.total_volumes}`
            : ''}
      </div>
      <div data-testid="book-summary-steps" className="mt-2 space-y-1">
        {summary.steps.map((step) => (
          <div
            key={step.index}
            data-testid={`book-summary-step-${step.index}`}
            className="rounded border border-line px-2 py-1 text-[12px] text-ink-2"
          >
            {step.index} · {step.status}
            {step.execution_id !== null && ` · ${step.execution_id}`}
          </div>
        ))}
      </div>
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          data-testid="book-summary-export"
          className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
          onClick={handleExport}
        >
          {t('book.summary.export')}
        </button>
      </div>
    </div>
  );
}
