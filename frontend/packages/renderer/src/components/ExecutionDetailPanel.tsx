/** AI 执行详情页（spec §4.3）：数据源 GET /api/v1/agent/pipelines/executions/{id}
 *
 * - 无 executionId → 空态（不发起请求）
 * - 有 executionId → 渲染 stages / trace / relations / final 四个区块；
 *   请求失败显示错误文案（不崩溃）；空数组也渲染对应区块。
 */
import { useEffect, useState } from 'react';
import { apiFetch, errorMessage } from '../api/client';
import { type PipelineExecutionListItem, type PipelineExecutionStatus } from '../api/pipeline';
import { useI18n } from '../i18n/useI18n';

export interface ExecutionDetailPanelProps {
  executionId?: string | null;
  projectId?: string;
}

export function ExecutionDetailPanel({ executionId, projectId }: ExecutionDetailPanelProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<PipelineExecutionStatus | null>(null);
  const [executions, setExecutions] = useState<PipelineExecutionListItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (executionId) {
      // #586: detail mode keeps GET /executions/{id}; never calls list endpoint
      let cancelled = false;
      setStatus(null);
      setError(null);
      apiFetch<PipelineExecutionStatus>(`/api/v1/agent/pipelines/executions/${executionId}`)
        .then((data) => {
          if (!cancelled) setStatus(data);
        })
        .catch((err) => {
          if (!cancelled) setError(errorMessage(err));
        });
      return () => {
        cancelled = true;
      };
    }
    if (projectId) {
      // #586: no executionId + projectId -> history list GET /executions?project_id=<id>
      let cancelled = false;
      setExecutions([]);
      setError(null);
      apiFetch<{ items?: PipelineExecutionListItem[] }>(
        `/api/v1/agent/pipelines/executions?project_id=${projectId}`,
      )
        .then((data) => {
          if (!cancelled) setExecutions(data?.items ?? []);
        })
        .catch((err) => {
          if (!cancelled) setError(errorMessage(err));
        });
      return () => {
        cancelled = true;
      };
    }
    setStatus(null);
    setExecutions([]);
    setError(null);
  }, [executionId, projectId]);

  // #586: no executionId + projectId -> render execution history list
  if (!executionId && projectId) {
    return (
      <div data-testid="exec-history-list" className="h-full overflow-y-auto px-4 py-3 text-[13px]">
        {error ? (
          <p className="text-err">{error}</p>
        ) : executions.length === 0 ? (
          <div data-testid="exec-detail-empty">{t('write.detail.empty')}</div>
        ) : (
          executions.map((item) => (
            <div
              key={item.execution_id}
              data-testid={`exec-history-item-${item.execution_id}`}
              className="mb-2 rounded-md border border-line bg-surface-2 p-2"
            >
              <div className="flex items-center gap-2">
                <span className="font-medium text-ink">{item.pipeline}</span>
                <span className="text-ink-3">{item.status}</span>
              </div>
              <div className="mt-1 flex items-center gap-3 text-ink-2">
                <span>{item.created_at}</span>
                <span>{item.total_duration_ms} ms</span>
              </div>
            </div>
          ))
        )}
      </div>
    );
  }

  if (!executionId) {
    return <div data-testid="exec-detail-empty">{t('write.detail.empty')}</div>;
  }

  return (
    <div data-testid="exec-detail" className="h-full overflow-y-auto px-4 py-3 text-[13px]">
      {error ? (
        <p className="text-err">{error}</p>
      ) : status ? (
        <>
          <section data-testid="exec-detail-stages" className="mb-4">
            <h3 className="text-[12px] font-medium text-ink-3">{t('write.detail.stages')}</h3>
            {status.stages.map((stage) => (
              <div
                key={stage.stage_id}
                data-testid={`exec-detail-stage-${stage.stage_id}`}
                className="mt-2 rounded-md border border-line bg-surface-2 p-2"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink">{stage.stage_id}</span>
                  <span className="text-ink-3">{stage.status || t('write.detail.unknown')}</span>
                </div>
                {stage.output ? (
                  <p className="mt-1 whitespace-pre-wrap text-ink-2">{stage.output}</p>
                ) : null}
                {stage.error ? <p className="mt-1 text-err">{stage.error}</p> : null}
              </div>
            ))}
          </section>
          <section data-testid="exec-detail-trace" className="mb-4">
            <h3 className="text-[12px] font-medium text-ink-3">{t('write.detail.trace')}</h3>
            {(status.trace ?? []).map((entry, index) => (
              <div
                key={index}
                data-testid={`exec-detail-trace-${index}`}
                className="mt-2 rounded-md border border-line bg-surface-2 p-2"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-ink">{entry.node}</span>
                  <span className="text-ink-3">{entry.type || t('write.detail.unknown')}</span>
                </div>
                {entry.reasoning ? (
                  <p className="mt-1 whitespace-pre-wrap text-ink-2">{entry.reasoning}</p>
                ) : null}
              </div>
            ))}
          </section>
          <section data-testid="exec-detail-relations" className="mb-4">
            <h3 className="text-[12px] font-medium text-ink-3">{t('write.detail.relations')}</h3>
            {(status.relations ?? []).map((rel, index) => (
              <div key={index} className="mt-1 text-ink-2">
                {rel.from} → {rel.to}
                {rel.gate_result ? <span className="ml-2 text-ink-3">{rel.gate_result}</span> : null}
              </div>
            ))}
          </section>
          <section data-testid="exec-detail-final" className="mb-4">
            <h3 className="text-[12px] font-medium text-ink-3">{t('write.detail.final')}</h3>
            <p className="mt-1 whitespace-pre-wrap text-ink">
              {status.final_output || t('write.detail.unknown')}
            </p>
            <p className="mt-1 text-ink-3">{status.total_duration_ms} ms</p>
          </section>
        </>
      ) : null}
    </div>
  );
}
