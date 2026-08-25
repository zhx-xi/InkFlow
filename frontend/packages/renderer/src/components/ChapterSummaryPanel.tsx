/**
 * 章节摘要面板（Issue #656）：写作页右栏挂载，展示当前章节摘要。
 * 挂载时 projectId && chapterId 非空 → getChapterSummary(chapterId) 自动加载；
 * 「刷新摘要」→ refreshChapterSummary(chapterId) 强制重新生成并更新展示（刷新闭环）。
 */
import { useCallback, useEffect, useState, type JSX } from 'react';
import { getChapterSummary, refreshChapterSummary } from '../api/context';
import { errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';

export function ChapterSummaryPanel({
  projectId,
  chapterId,
}: {
  projectId: string | null;
  chapterId: string | null;
}): JSX.Element {
  const { t } = useI18n();
  const [summary, setSummary] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (force: boolean) => {
      if (!projectId || !chapterId) return;
      setLoading(true);
      setError(null);
      try {
        const dto = force ? await refreshChapterSummary(chapterId) : await getChapterSummary(chapterId);
        setSummary(dto.summary);
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [projectId, chapterId],
  );

  // 挂载 / projectId / chapterId 变化 → 自动加载；任一为 null 守卫不发请求
  useEffect(() => {
    if (projectId && chapterId) {
      void load(false);
    }
  }, [projectId, chapterId, load]);

  return (
    <aside
      data-testid="chapter-summary-panel"
      className="flex min-h-0 flex-col border-t border-line"
    >
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span data-testid="chapter-summary-title" className="text-[13px] font-semibold">
          {t('write.summary.title')}
        </span>
        <button
          type="button"
          data-testid="chapter-summary-refresh"
          className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
          onClick={() => void load(true)}
        >
          {t('write.summary.refresh')}
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {error !== null ? (
          <div
            data-testid="chapter-summary-error"
            className="rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-3"
          >
            {t('write.summary.error')}: {error}
          </div>
        ) : loading && summary === null ? (
          <div
            data-testid="chapter-summary-loading"
            className="rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-3"
          >
            {t('write.summary.loading')}
          </div>
        ) : summary !== null && summary !== '' ? (
          <div
            data-testid="chapter-summary-content"
            className="whitespace-pre-wrap rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-2"
          >
            {summary}
          </div>
        ) : (
          <div
            data-testid="chapter-summary-empty"
            className="rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-3"
          >
            {t('write.summary.empty')}
          </div>
        )}
      </div>
    </aside>
  );
}
