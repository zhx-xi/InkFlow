/**
 * #1015 会话详情弹层（访谈卡 / 执行卡统一只读详情，N11-N13/N16）。
 * - ex：会话元信息 + 履历日志时间线，懒加载 GET /api/v1/sessions/{id}/logs；
 * - pl：planner 快照，懒加载 GET /api/v1/agent/books/planner/{id}；
 * - #1029：ex 会话 context 含 agent_run_id 软锚（ADR-056）→ 追加决策轨迹区块，
 *   懒加载 GET /api/v1/agent/runs/{id}（失败仅占位，不影响其余部分）；
 * - 归档执行会话（is_deleted=true）底部提供恢复入口；内容始终只读。
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchSessionLogs, type SessionLogDto, type SessionViewDto } from '../api/sessions';
import { getPlannerSession, type PlannerSessionDto } from '../api/books';
import { getRun, type AgentRunDto, type AgentStepDto } from '../api/runs';
import { useI18n } from '../i18n/useI18n';
import { formatTimestamp } from '../lib/log-format';

/** 弹层打开目标：ex=执行会话卡（含归档）/ pl=访谈会话卡 */
export type SessionDetailTarget =
  | { kind: 'ex'; view: SessionViewDto }
  | { kind: 'pl'; planner: PlannerSessionDto };

interface SessionDetailDialogProps {
  target: SessionDetailTarget;
  onClose: () => void;
  onRestoreSession: (sessionId: string) => void;
}

/** 懒加载数据：pl=planner 快照；ex=履历日志（limit 200，覆盖完整时间线） */
type DetailData =
  | { kind: 'pl'; planner: PlannerSessionDto }
  | { kind: 'ex'; logs: SessionLogDto[] };

/** #1029 软锚读取：context['agent_run_id'] 为非空字符串才算锚（无键/空串 = 存量会话降级） */
function readAgentRunId(context: Record<string, unknown>): string | null {
  const raw = context['agent_run_id'];
  return typeof raw === 'string' && raw !== '' ? raw : null;
}

/** #1029 轻量轨迹行：步骤序号 + 工具名（多个逗号连接）+ 各 tool_call 结果摘要 */
function renderTraceStep(step: AgentStepDto) {
  const toolNames = step.tool_calls.map((call) => call.tool_name).filter((name) => name !== '');
  const results = step.tool_calls.map((call) => call.result).filter((text) => text !== '');
  return (
    <div
      key={step.index}
      data-testid={`session-detail-trace-${step.index}`}
      className="rounded-md border border-line bg-surface-2 px-3 py-2"
    >
      <div className="text-ink">
        <span className="text-ink-2">{step.index + 1}.</span> {toolNames.join(', ')}
      </div>
      {results.length > 0 ? (
        <div className="mt-1 whitespace-pre-wrap text-ink-2">{results.join(' / ')}</div>
      ) : null}
    </div>
  );
}

export function SessionDetailDialog({
  target,
  onClose,
  onRestoreSession,
}: SessionDetailDialogProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [data, setData] = useState<DetailData | null>(null);
  const [trace, setTrace] = useState<AgentRunDto | null>(null);
  const [traceFailed, setTraceFailed] = useState(false);
  const agentRunId = target.kind === 'ex' ? readAgentRunId(target.view.session.context) : null;

  // 懒加载：target 变化触发；cancelled 标志防卸载后 setState；轨迹与日志/快照并行加载
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailed(false);
    setData(null);
    setTrace(null);
    setTraceFailed(false);
    const runId = target.kind === 'ex' ? readAgentRunId(target.view.session.context) : null;
    // #1029：轨迹错误独立捕获——run 加载失败不置 failed（弹层其余部分照常渲染）
    const loadTrace = async () => {
      if (!runId) return;
      try {
        const dto = await getRun(runId);
        if (!cancelled) setTrace(dto);
      } catch {
        if (!cancelled) setTraceFailed(true);
      }
    };
    const run = async () => {
      try {
        if (target.kind === 'pl') {
          const planner = await getPlannerSession(target.planner.id);
          if (!cancelled) setData({ kind: 'pl', planner });
        } else {
          const [logs] = await Promise.all([
            fetchSessionLogs(target.view.session.id, { limit: 200 }),
            loadTrace(),
          ]);
          if (!cancelled) setData({ kind: 'ex', logs: logs.items });
        }
      } catch {
        if (!cancelled) setFailed(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [target]);

  const title = target.kind === 'ex' ? target.view.session.title : target.planner.one_liner;
  const session = target.kind === 'ex' ? target.view.session : null;
  const showRestore = target.kind === 'ex' && target.view.session.is_deleted;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        data-testid="session-detail-dialog"
        role="dialog"
        aria-modal="true"
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-lg border border-line bg-surface p-5 shadow-card"
      >
        <div className="flex items-center gap-3">
          <h3
            data-testid="session-detail-title"
            className="min-w-0 flex-1 font-serif text-[17px] font-semibold text-ink"
          >
            {title}
          </h3>
          <button
            type="button"
            data-testid="session-detail-close"
            aria-label={t('audit.close')}
            className="shrink-0 rounded-md border border-line px-3 py-1 text-[13px] text-ink-2 transition-colors hover:bg-surface-3 hover:text-ink"
            onClick={onClose}
          >
            {t('audit.close')}
          </button>
        </div>

        {loading ? (
          <div data-testid="session-detail-loading" role="status" className="mt-4 text-[13px] text-ink-2">
            {t('common.loading')}
          </div>
        ) : failed || data === null ? (
          <div data-testid="session-detail-error" role="alert" className="mt-4 text-[13px] text-err">
            {t('sessions.detail.loadFailed')}
          </div>
        ) : data.kind === 'pl' ? (
          <div className="mt-4 space-y-3 overflow-y-auto text-[13px]">
            {data.planner.asked_questions.map((q) => (
              <div key={q.id} data-testid={`session-detail-qa-${q.id}`} className="rounded-md border border-line bg-surface-2 px-3 py-2">
                <div className="font-medium text-ink">{q.text}</div>
                <div className="mt-1 whitespace-pre-wrap text-ink-2">
                  {data.planner.answers[q.id] ?? t('sessions.detail.unanswered')}
                </div>
              </div>
            ))}
            {(data.planner.confirmed_items ?? []).map((item) => (
              <div
                key={item.key}
                data-testid={`session-detail-confirmed-${item.key}`}
                className="rounded-md border border-line bg-surface-2 px-3 py-2 text-ink"
              >
                {item.value}（{item.source}）
              </div>
            ))}
            {data.planner.writing_plan_id ? (
              <div data-testid="session-detail-writing-plan" className="rounded-md border border-line px-3 py-2 text-ink">
                {t('sessions.planner.writingPlan')} {data.planner.writing_plan_id}
              </div>
            ) : null}
          </div>
        ) : session && data.kind === 'ex' ? (
          <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-y-auto text-[13px]">
            <div className="space-y-1 rounded-md border border-line bg-surface-2 px-3 py-2">
              <div className="text-ink">
                <span data-testid="session-detail-meta-status">{session.status}</span>
                {session.completed_at ? ` · ${formatTimestamp(session.completed_at)}` : ''}
              </div>
              <div className="text-[12px] text-ink-2">{formatTimestamp(session.started_at)}</div>
            </div>
            <div className="mt-3 space-y-1">
              {data.logs.map((log) => (
                <div key={log.seq} data-testid={`session-detail-log-${log.seq}`} className="text-ink-2">
                  [{log.level}] {log.message} · {formatTimestamp(log.created_at)}
                </div>
              ))}
            </div>
            {agentRunId ? (
              <div className="mt-3 rounded-md border border-line px-3 py-2">
                <div className="font-medium text-ink">{t('sessions.detail.trace')}</div>
                {traceFailed ? (
                  <div
                    data-testid="session-detail-trace-error"
                    role="alert"
                    className="mt-2 text-[12px] text-err"
                  >
                    {t('sessions.detail.traceFailed')}
                  </div>
                ) : (
                  <>
                    <div className="mt-2 space-y-1">
                      {(trace?.steps ?? []).map((step) => renderTraceStep(step))}
                    </div>
                    <button
                      type="button"
                      data-testid="session-detail-trace-link"
                      className="mt-2 text-[12px] text-accent transition-colors hover:text-accent-hover"
                      onClick={() => {
                        const chapterId = trace?.chapter_id;
                        navigate(chapterId ? `/writing?chapter_id=${chapterId}` : '/writing');
                      }}
                    >
                      {t('sessions.detail.traceLink')}
                    </button>
                  </>
                )}
              </div>
            ) : null}
          </div>
        ) : null}

        {showRestore && (
          <div className="mt-5 flex justify-end border-t border-line pt-4">
            <button
              type="button"
              data-testid="session-detail-restore"
              className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition hover:bg-accent-hover active:scale-[0.98]"
              onClick={() => {
                if (session) onRestoreSession(session.id);
                onClose();
              }}
            >
              {t('sessions.restore')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
