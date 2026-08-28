/** AI 执行详情页（spec §4.3 + #599 统一执行视图）：链式静态 + agentic 动态双时间线
 *
 * 判别逻辑（优先级从高到低）：
 * - runId（props）/ activeRunId（历史点击）非空 → agentic 模式：getRun(runId) → 动态工具调用流；
 * - executionId / activeExecutionId 非空 → 链式模式：GET /executions/{id} → stages/trace/relations/final；
 * - projectId 非空 → 统一历史列表：GET /executions?project_id= + listRuns(projectId) 同屏；
 * - 否则 → exec-detail-empty 空态（不发起请求）。
 *
 * 工作流栏（workflowPlacement）：默认/'top' 置详情区块上方；'bottom' 置下方。
 * 请求失败显示错误文案（不崩溃）；空数组也渲染对应区块。
 */
import { useEffect, useState, type ReactNode } from 'react';
import { apiFetch, errorMessage } from '../api/client';
import { getRun, listRuns, type AgentRunDto } from '../api/runs';
import { type PipelineExecutionListItem, type PipelineExecutionStatus } from '../api/pipeline';
import { useI18n } from '../i18n/useI18n';

export interface ExecutionDetailPanelProps {
  executionId?: string | null;
  /** #599：agentic run id（新增，优先级最高） */
  runId?: string | null;
  projectId?: string;
  /** #599：工作流栏位置（缺省/'top' 顶部，'bottom' 底部） */
  workflowPlacement?: 'top' | 'bottom';
}

/** #599：横向压缩工作流栏（链式 stage 步进 / agentic step 步进） */
function WorkflowBar({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div
      data-testid="exec-workflow-bar"
      className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface-2 px-3 py-2"
    >
      <span className="text-[12px] font-medium text-ink-3">{label}</span>
      {children}
    </div>
  );
}

export function ExecutionDetailPanel({
  executionId,
  runId,
  projectId,
  workflowPlacement = 'top',
}: ExecutionDetailPanelProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<PipelineExecutionStatus | null>(null);
  const [executions, setExecutions] = useState<PipelineExecutionListItem[]>([]);
  /** #599：当前 agentic run 详情（getRun 结果） */
  const [run, setRun] = useState<AgentRunDto | null>(null);
  /** #599：项目 agentic runs 历史（listRuns 结果） */
  const [runs, setRuns] = useState<AgentRunDto[]>([]);
  /** #599：历史列表点击后进入链式详情的内部 id */
  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(null);
  /** #599：历史列表点击后进入 agentic 详情的内部 id */
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  /** #740：agentic 每步思考折叠块展开状态（key = step.index） */
  const [expandedThink, setExpandedThink] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  /** #740：切换某步思考折叠块展开态 */
  const toggleThink = (index: number) =>
    setExpandedThink((prev) => ({ ...prev, [index]: !prev[index] }));

  useEffect(() => {
    // #599：agentic 模式（优先级最高）
    const targetRunId = runId ?? activeRunId;
    if (targetRunId) {
      let cancelled = false;
      setRun(null);
      setError(null);
      getRun(targetRunId)
        .then((data) => {
          if (!cancelled) setRun(data);
        })
        .catch((err) => {
          if (!cancelled) setError(errorMessage(err));
        });
      return () => {
        cancelled = true;
      };
    }
    // 链式模式（既有：#586 detail 不调用列表端点）
    const targetExecutionId = executionId ?? activeExecutionId;
    if (targetExecutionId) {
      let cancelled = false;
      setStatus(null);
      setError(null);
      apiFetch<PipelineExecutionStatus>(`/api/v1/agent/pipelines/executions/${targetExecutionId}`)
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
    // #599：统一历史——链式 executions + agentic runs 同时请求，单侧失败不影响另一侧
    if (projectId) {
      let cancelled = false;
      setExecutions([]);
      setRuns([]);
      setError(null);
      apiFetch<{ items?: PipelineExecutionListItem[] }>(
        `/api/v1/agent/pipelines/executions?project_id=${projectId}`,
      )
        .then((data) => {
          if (!cancelled) setExecutions(data?.items ?? []);
        })
        .catch((err) => {
          if (!cancelled) {
            setExecutions([]);
            setError(errorMessage(err));
          }
        });
      // 防御：listRuns 失败/返回 undefined → items 置空（Promise.resolve 兼容非 promise 返回值）
      void Promise.resolve(listRuns(projectId))
        .catch(() => null)
        .then((data) => {
          if (!cancelled) setRuns(data?.items ?? []);
        });
      return () => {
        cancelled = true;
      };
    }
    setStatus(null);
    setExecutions([]);
    setRuns([]);
    setError(null);
  }, [runId, activeRunId, executionId, activeExecutionId, projectId, workflowPlacement]);

  const targetRunId = runId ?? activeRunId;
  const targetExecutionId = executionId ?? activeExecutionId;

  // #599：agentic 模式（动态工具调用流）
  if (targetRunId) {
    const workflowBar = run ? (
      <WorkflowBar label={t('write.detail.workflow')}>
        {run.steps.map((step) => (
          <span
            key={step.index}
            data-testid={`exec-workflow-step-${step.index}`}
            className="rounded bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2"
          >
            {step.index}
          </span>
        ))}
        <span
          data-testid="exec-run-status"
          className="ml-auto rounded px-2 py-0.5 text-[11px] text-ink-3"
        >
          {run.status}
        </span>
      </WorkflowBar>
    ) : null;
    return (
      <div data-testid="exec-detail" className="h-full overflow-y-auto px-4 py-3 text-[13px]">
        {error ? (
          <p className="text-err">{error}</p>
        ) : run ? (
          <>
            {workflowPlacement !== 'bottom' ? workflowBar : null}
            <section data-testid="exec-detail-steps" className="mb-4">
              <h3 className="text-[12px] font-medium text-ink-3">{t('write.detail.steps')}</h3>
              {run.steps.length === 0 ? (
                <div data-testid="exec-detail-steps-empty" className="mt-2 text-ink-2">
                  {t('write.detail.stepsEmpty')}
                </div>
              ) : (
                run.steps.map((step) => (
                  <div
                    key={step.index}
                    data-testid={`exec-detail-step-${step.index}`}
                    className="mt-2 rounded-md border border-line bg-surface-2 p-2"
                  >
                    {/* #740：思考折叠块（仅 reasoning 真值时渲染，默认折叠） */}
                    {step.reasoning ? (
                      <div
                        data-testid={`exec-think-${step.index}`}
                        aria-expanded={!!expandedThink[step.index]}
                        className="mb-1 rounded border border-line bg-surface px-2 py-1"
                        onClick={() => toggleThink(step.index)}
                      >
                        <button
                          type="button"
                          data-testid={`exec-think-toggle-${step.index}`}
                          aria-expanded={!!expandedThink[step.index]}
                          className="flex w-full items-center gap-1.5 text-left"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleThink(step.index);
                          }}
                        >
                          <span className="inline-block w-3 shrink-0 text-ink-3">
                            {expandedThink[step.index] ? '▾' : '›'}
                          </span>
                          <span className="text-ink">🧠</span>
                          <span className="font-medium text-ink">{t('write.chat.thinking')}</span>
                        </button>
                        {expandedThink[step.index] && (
                          <div className="mt-1 whitespace-pre-wrap border-t border-line pt-1 text-ink-2">
                            {step.reasoning}
                          </div>
                        )}
                      </div>
                    ) : null}
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink">{step.index}</span>
                      {step.message_content ? (
                        <span className="text-ink-2">{step.message_content}</span>
                      ) : null}
                    </div>
                    {step.tool_calls.length > 0 ? (
                      <div className="mt-2">
                        <h4 className="text-[12px] font-medium text-ink-3">
                          {t('write.detail.toolCall')}
                        </h4>
                        {step.tool_calls.map((tool, n) => (
                          <div
                            key={`${step.index}-${n}`}
                            data-testid={`exec-detail-tool-call-${step.index}-${n}`}
                            className={`mt-1 rounded border p-2 ${
                              tool.is_error ? 'border-err/40 bg-err/10' : 'border-line bg-surface-3'
                            }`}
                          >
                            <span
                              className={`mr-2 rounded px-1.5 py-0.5 text-[11px] font-medium ${
                                tool.is_error ? 'text-err' : 'text-ink-2'
                              }`}
                            >
                              {tool.tool_name}
                            </span>
                            <span className="text-ink-2">{JSON.stringify(tool.arguments)}</span>
                            {tool.result ? (
                              <p className="mt-1 truncate text-ink-3">{tool.result}</p>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))
              )}
            </section>
            <section data-testid="exec-detail-final" className="mb-4">
              <h3 className="text-[12px] font-medium text-ink-3">{t('write.detail.final')}</h3>
              <p className="mt-1 whitespace-pre-wrap text-ink">
                {run.final_content || t('write.detail.unknown')}
              </p>
              <p className="mt-1 text-ink-3">{run.token_usage_total}</p>
            </section>
            {workflowPlacement === 'bottom' ? workflowBar : null}
          </>
        ) : null}
      </div>
    );
  }

  // 链式模式（既有：stages/trace/relations/final 语义不变）
  if (targetExecutionId) {
    const workflowBar = status ? (
      <WorkflowBar label={t('write.detail.workflow')}>
        {status.stages.map((stage) => (
          <span
            key={stage.stage_id}
            data-testid={`exec-workflow-stage-${stage.stage_id}`}
            className="rounded bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2"
          >
            {stage.stage_id}
          </span>
        ))}
        <span className="ml-auto rounded px-2 py-0.5 text-[11px] text-ink-3">{status.status}</span>
      </WorkflowBar>
    ) : null;
    return (
      <div data-testid="exec-detail" className="h-full overflow-y-auto px-4 py-3 text-[13px]">
        {error ? (
          <p className="text-err">{error}</p>
        ) : status ? (
          <>
            {workflowPlacement !== 'bottom' ? workflowBar : null}
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
            {workflowPlacement === 'bottom' ? workflowBar : null}
          </>
        ) : null}
      </div>
    );
  }

  // #599：统一历史列表（链式 + agentic 同屏）
  if (projectId) {
    return (
      <div data-testid="exec-history-list" className="h-full overflow-y-auto px-4 py-3 text-[13px]">
        {error ? <p className="text-err">{error}</p> : null}
        {executions.length === 0 && runs.length === 0 ? (
          <div data-testid="exec-detail-empty">{t('write.detail.empty')}</div>
        ) : (
          <>
            {executions.length > 0 ? (
              <section className="mb-4">
                <h3 className="text-[12px] font-medium text-ink-3">{t('write.detail.chain')}</h3>
                {executions.map((item) => (
                  <div
                    key={item.execution_id}
                    data-testid={`exec-history-item-${item.execution_id}`}
                    className="mb-2 cursor-pointer rounded-md border border-line bg-surface-2 p-2"
                    onClick={() => {
                      setActiveExecutionId(item.execution_id);
                      setActiveRunId(null);
                    }}
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
                ))}
              </section>
            ) : null}
            {runs.length > 0 ? (
              <section>
                <h3 className="text-[12px] font-medium text-ink-3">{t('write.detail.run')}</h3>
                {runs.map((item) => (
                  <div
                    key={item.id}
                    data-testid={`exec-history-run-${item.id}`}
                    className="mb-2 cursor-pointer rounded-md border border-line bg-surface-2 p-2"
                    onClick={() => {
                      setActiveRunId(item.id);
                      setActiveExecutionId(null);
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink">{t('write.detail.agentic')}</span>
                      <span className="text-ink-3">{item.status}</span>
                    </div>
                    <div className="mt-1 flex items-center gap-3 text-ink-2">
                      <span>{item.created_at}</span>
                      <span>{item.token_usage_total} tokens</span>
                    </div>
                  </div>
                ))}
              </section>
            ) : null}
          </>
        )}
      </div>
    );
  }

  return <div data-testid="exec-detail-empty">{t('write.detail.empty')}</div>;
}
