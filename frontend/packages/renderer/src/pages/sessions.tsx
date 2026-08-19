/**
 * #486 会话/记忆 UI — 会话页（访谈会话 + 执行会话：归档/恢复/删除）.
 * 访谈会话一次拉取（fetchPlannerSessions）；执行会话一次拉取含归档全量
 * （fetchSessions({ includeDeleted: true })），chips 切换为纯前端本地过滤，不重拉.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  archiveSession,
  deleteSession,
  fetchPlannerSessions,
  fetchSessions,
  restoreSession,
  type PlannerSessionDto,
  type SessionViewDto,
} from '../api/sessions';
import { errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useToastStore } from '../stores/toast';

type SessionFilter = 'all' | 'active' | 'archived';

/** 访谈会话 status 文案映射（未知状态原样展示） */
const PLANNER_STATUS_LABEL: Record<string, string> = {
  drafting: 'sessions.planner.status.drafting',
  completed: 'sessions.planner.status.completed',
  declined: 'sessions.planner.status.declined',
};

/** 执行会话 status 文案映射（未知状态原样展示） */
const SESSION_STATUS_LABEL: Record<string, string> = {
  active: 'sessions.status.active',
  paused: 'sessions.status.paused',
  completed: 'sessions.status.completed',
  failed: 'sessions.status.failed',
};

/** 执行会话类型文案映射（未知类型原样展示） */
const SESSION_TYPE_LABEL: Record<string, string> = {
  writing: 'sessions.type.writing',
  task: 'sessions.type.task',
};

const FILTERS: Array<{ key: SessionFilter; labelKey: string }> = [
  { key: 'all', labelKey: 'sessions.filter.all' },
  { key: 'active', labelKey: 'sessions.filter.active' },
  { key: 'archived', labelKey: 'sessions.filter.archived' },
];

export function SessionsPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const pushToast = useToastStore((s) => s.pushToast);

  const [plannerItems, setPlannerItems] = useState<PlannerSessionDto[]>([]);
  const [plannerLoading, setPlannerLoading] = useState(true);
  const [sessions, setSessions] = useState<SessionViewDto[]>([]);
  const [filter, setFilter] = useState<SessionFilter>('all');
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  // 访谈会话：一次拉取全量（缺省分页 50）
  useEffect(() => {
    void fetchPlannerSessions()
      .then((res) => setPlannerItems(res.items))
      .catch((err) => pushToast('err', errorMessage(err)))
      .finally(() => setPlannerLoading(false));
  }, [pushToast]);

  // 执行会话：一次拉取含已归档全量，chips 切换纯本地过滤不重拉
  useEffect(() => {
    void fetchSessions({ includeDeleted: true })
      .then((res) => setSessions(res.items))
      .catch((err) => pushToast('err', errorMessage(err)));
  }, [pushToast]);

  /** 过滤后可见执行会话（全部 = 不过滤；活动 = 未归档；已归档 = is_deleted） */
  const visibleSessions = useMemo(() => {
    if (filter === 'active') return sessions.filter((v) => !v.session.is_deleted);
    if (filter === 'archived') return sessions.filter((v) => v.session.is_deleted);
    return sessions;
  }, [sessions, filter]);

  const handleArchive = async (id: string): Promise<void> => {
    try {
      await archiveSession(id);
      setSessions((prev) =>
        prev.map((v) =>
          v.session.id === id ? { ...v, session: { ...v.session, is_deleted: true } } : v,
        ),
      );
      pushToast('ok', t('sessions.archivedToast'));
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  const handleRestore = async (id: string): Promise<void> => {
    try {
      await restoreSession(id);
      setSessions((prev) =>
        prev.map((v) =>
          v.session.id === id ? { ...v, session: { ...v.session, is_deleted: false } } : v,
        ),
      );
      pushToast('ok', t('sessions.restoredToast'));
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  const handleDeleteConfirm = async (): Promise<void> => {
    if (!deleteTarget) return;
    const id = deleteTarget;
    setDeleteTarget(null);
    try {
      await deleteSession(id);
      setSessions((prev) => prev.filter((v) => v.session.id !== id));
      pushToast('ok', t('sessions.deletedToast'));
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  return (
    <div data-testid="sessions-page" className="mx-auto max-w-[1080px] px-12 py-10">
      <h1 className="font-serif text-[26px] font-semibold">{t('sessions.title')}</h1>

      {/* 访谈会话区块 */}
      <section data-testid="planner-section" className="mt-8">
        <h2 className="text-[15px] font-semibold text-ink">{t('sessions.planner.title')}</h2>
        {plannerLoading ? (
          <div
            data-testid="planner-loading"
            className="mt-3 rounded-lg border border-line bg-surface px-4 py-6 text-center text-[13px] text-ink-2"
          >
            {t('sessions.planner.loading')}
          </div>
        ) : plannerItems.length === 0 ? (
          <div
            data-testid="planner-empty"
            className="mt-3 flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-12 text-center"
          >
            <p className="font-serif text-[15px] font-semibold text-ink">
              {t('sessions.planner.empty')}
            </p>
            <button
              type="button"
              data-testid="planner-go-book"
              className="mt-4 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              onClick={() => navigate('/book')}
            >
              {t('sessions.planner.goBook')}
            </button>
          </div>
        ) : (
          <ul className="mt-3 space-y-3">
            {plannerItems.map((item) => (
              <li
                key={item.id}
                data-testid="planner-card"
                className="rounded-lg border border-line bg-surface p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    data-testid={`planner-status-${item.id}`}
                    className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                  >
                    {PLANNER_STATUS_LABEL[item.status]
                      ? t(PLANNER_STATUS_LABEL[item.status])
                      : item.status}
                  </span>
                  <span
                    data-testid={`planner-confirmed-${item.id}`}
                    className="ml-auto text-[12px] text-ink-3"
                  >
                    {t('sessions.planner.confirmed', { n: (item.confirmed_items ?? []).length })}
                  </span>
                </div>
                <h3 className="mt-2 font-serif text-[15px] font-semibold text-ink">
                  <span data-testid={`planner-one-liner-${item.id}`}>{item.one_liner}</span>
                </h3>
                {item.writing_plan_id ? (
                  <span
                    data-testid={`planner-writing-plan-${item.id}`}
                    className="mt-2 inline-block rounded bg-surface-3 px-2 py-0.5 text-[12px] text-ink-2"
                  >
                    {t('sessions.planner.writingPlan')}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* 执行会话区块 */}
      <section data-testid="sessions-section" className="mt-10">
        <h2 className="text-[15px] font-semibold text-ink">{t('sessions.runs.title')}</h2>
        <div className="mt-3 flex gap-2">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              data-testid={`sessions-filter-${f.key}`}
              aria-pressed={filter === f.key}
              className="rounded-md border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 hover:text-ink aria-pressed:border-accent aria-pressed:bg-accent-weak aria-pressed:text-accent"
              onClick={() => setFilter(f.key)}
            >
              {t(f.labelKey)}
            </button>
          ))}
        </div>

        {visibleSessions.length === 0 ? (
          <div
            data-testid="sessions-empty"
            className="mt-3 rounded-lg border border-dashed border-line bg-surface px-6 py-12 text-center text-[13px] text-ink-2"
          >
            {t('sessions.empty')}
          </div>
        ) : (
          <ul className="mt-3 space-y-3">
            {visibleSessions.map((view) => {
              const s = view.session;
              return (
                <li
                  key={s.id}
                  data-testid="session-card"
                  className="rounded-lg border border-line bg-surface p-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-serif text-[15px] font-semibold text-ink">
                      <span data-testid={`session-title-${s.id}`}>{s.title}</span>
                    </h3>
                    <span
                      data-testid={`session-status-${s.id}`}
                      className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                    >
                      {SESSION_STATUS_LABEL[s.status]
                        ? t(SESSION_STATUS_LABEL[s.status])
                        : s.status}
                    </span>
                    <span
                      data-testid={`session-type-${s.id}`}
                      className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                    >
                      {SESSION_TYPE_LABEL[s.session_type]
                        ? t(SESSION_TYPE_LABEL[s.session_type])
                        : s.session_type}
                    </span>
                    {s.is_deleted && (
                      <span
                        data-testid={`session-archived-${s.id}`}
                        className="rounded bg-surface-3 px-2 py-0.5 text-[11px] text-ink-3"
                      >
                        {t('sessions.archived')}
                      </span>
                    )}
                  </div>
                  <div className="mt-3 flex gap-2">
                    {!s.is_deleted ? (
                      <button
                        type="button"
                        data-testid={`session-archive-${s.id}`}
                        className="rounded-md border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 hover:text-ink"
                        onClick={() => void handleArchive(s.id)}
                      >
                        {t('sessions.archive')}
                      </button>
                    ) : (
                      <button
                        type="button"
                        data-testid={`session-restore-${s.id}`}
                        className="rounded-md border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 hover:text-ink"
                        onClick={() => void handleRestore(s.id)}
                      >
                        {t('sessions.restore')}
                      </button>
                    )}
                    <button
                      type="button"
                      data-testid={`session-delete-${s.id}`}
                      className="rounded-md border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 transition-colors duration-180 hover:border-err/50 hover:text-err"
                      onClick={() => setDeleteTarget(s.id)}
                    >
                      {t('sessions.delete')}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* 删除确认对话框（受控 state deleteTarget） */}
      {deleteTarget && (
        <div
          data-testid="session-delete-dialog"
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        >
          <div className="w-full max-w-sm rounded-lg border border-line bg-surface p-5 shadow-card">
            <h3 className="font-serif text-[17px] font-semibold text-ink">
              {t('sessions.delete.dialog.title')}
            </h3>
            <p className="mt-2 text-[13px] text-ink-2">{t('sessions.delete.dialog.desc')}</p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                data-testid="session-delete-cancel"
                className="rounded-md border border-line bg-surface px-4 py-1.5 text-[13px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 hover:text-ink"
                onClick={() => setDeleteTarget(null)}
              >
                {t('sessions.delete.cancel')}
              </button>
              <button
                type="button"
                data-testid="session-delete-confirm"
                className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                onClick={() => void handleDeleteConfirm()}
              >
                {t('sessions.delete.confirm')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
