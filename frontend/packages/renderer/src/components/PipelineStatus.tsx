/** 管线执行状态区（spec §5.6）：进行中/成功/失败（替换原 SSE 流式区） */
import { useI18n } from '../i18n/useI18n';
import type { PipelineRunStatus } from '../hooks/usePipeline';

export interface PipelineStatusProps {
  status: PipelineRunStatus;
  error: string | null;
}

export function PipelineStatus({ status, error }: PipelineStatusProps) {
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
    </div>
  );
}
