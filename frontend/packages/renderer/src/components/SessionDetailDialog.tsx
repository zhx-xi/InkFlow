/**
 * #1015 会话详情弹层（访谈卡 / 执行卡统一只读详情，N11-N13/N16）。
 * - ex：会话元信息 + 履历日志时间线，懒加载 GET /api/v1/sessions/{id}/logs；
 * - pl：planner 快照，懒加载 GET /api/v1/agent/books/planner/{id}；
 * - 归档执行会话（is_deleted=true）底部提供恢复入口；内容始终只读。
 */
import { useEffect, useState } from 'react';
import { fetchSessionLogs, type SessionLogDto, type SessionViewDto } from '../api/sessions';
import { getPlannerSession, type PlannerSessionDto } from '../api/books';
import { useI18n } from '../i18n/useI18n';

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

export function SessionDetailDialog({
  target,
  onClose,
  onRestoreSession,
}: SessionDetailDialogProps) {
  const { t } = useI18n();
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [data, setData] = useState<DetailData | null>(null);

  // 懒加载：target 变化触发；cancelled 标志防卸载后 setState
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailed(false);
    setData(null);
    const run = async () => {
      try {
        if (target.kind === 'pl') {
          const planner = await getPlannerSession(target.planner.id);
          if (!cancelled) setData({ kind: 'pl', planner });
        } else {
          const res = await fetchSessionLogs(target.view.session.id, { limit: 200 });
          if (!cancelled) setData({ kind: 'ex', logs: res.items });
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
                {session.completed_at ? ` · ${session.completed_at}` : ''}
              </div>
              <div className="text-[12px] text-ink-2">{session.started_at}</div>
            </div>
            <div className="mt-3 space-y-1">
              {data.logs.map((log) => (
                <div key={log.seq} data-testid={`session-detail-log-${log.seq}`} className="text-ink-2">
                  [{log.level}] {log.message} · {log.created_at}
                </div>
              ))}
            </div>
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
