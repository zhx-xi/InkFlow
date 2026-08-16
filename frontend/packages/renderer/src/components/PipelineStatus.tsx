/** 管线执行状态区（spec §5.6）：进行中/成功/失败/待人工确认（#343 内联 HITL 卡片） */
import { useI18n } from '../i18n/useI18n';
import type { PipelineRunStatus } from '../hooks/usePipeline';

export interface PipelineStatusProps {
  status: PipelineRunStatus;
  error: string | null;
  hitlPending?: { question: string; role: string } | null;
  onConfirm?: (approved: boolean) => void;
  confirming?: boolean;
}

export function PipelineStatus({
  status,
  error,
  hitlPending,
  onConfirm,
  confirming = false,
}: PipelineStatusProps) {
  const { t } = useI18n();
  return (
    <div data-testid="pipeline-status" className="min-h-[84px] border-t border-line bg-surface px-6 py-3 text-[13px]">
      {status === 'running' && (
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-err">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-err" />
            {t('write.pipeline.running')}
          </span>
        </div>
      )}
      {status === 'success' && <div className="text-ok">{t('write.pipeline.success')}</div>}
      {status === 'failed' && error && (
        <div className="text-err">{t('write.pipeline.failed', { message: error })}</div>
      )}
      {status === 'idle' && <div className="text-ink-3">{t('write.stream.idle')}</div>}
      {status === 'awaiting_human' && hitlPending && (
        <div
          data-testid="hitl-confirm-card"
          className="flex items-center gap-3 rounded-md border border-amber-400/60 bg-amber-400/10 px-3 py-2"
        >
          <span className="flex-1 text-ink">{hitlPending.question}</span>
          <button
            type="button"
            data-testid="hitl-confirm-approve"
            aria-label={t('write.hitl.approve')}
            disabled={confirming}
            className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 hover:bg-surface-3 disabled:opacity-40"
            onClick={() => onConfirm?.(true)}
          >
            {t('write.hitl.approve')}
          </button>
          <button
            type="button"
            data-testid="hitl-confirm-reject"
            aria-label={t('write.hitl.reject')}
            disabled={confirming}
            className="rounded-md bg-accent px-3 py-1 text-[12px] text-accent-ink hover:bg-accent-hover disabled:opacity-40"
            onClick={() => onConfirm?.(false)}
          >
            {t('write.hitl.reject')}
          </button>
        </div>
      )}
    </div>
  );
}
