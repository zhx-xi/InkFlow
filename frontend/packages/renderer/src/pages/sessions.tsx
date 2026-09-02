/**
 * #725 会话页重构 — 统一窗口 / 按项目分区 / 检索同栏 / 归档回归.
 * 移除「访谈会话/执行会话/AI 对话」三个独立分区，统一为一个会话目录
 * （session-directory），三类卡片以类型徽标区分；顶部项目选择器按
 * currentProjectId 前端过滤；检索框同栏过滤标题/项目名/最后消息。
 * 数据流：前端一次拉全量（执行含归档 / 访谈全量 / AI 对话含归档），
 * filter chips 纯本地过滤不重拉（Q3 归档回归由测试锁定）。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
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
import {
  archiveChatConversation,
  deleteChatConversation,
  fetchChatConversations,
  renameChatConversation,
  restoreChatConversation,
  type ChatConversationDto,
} from '../api/chat';
import { errorMessage } from '../api/client';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { useI18n } from '../i18n/useI18n';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
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

/** 统一目录卡片项（kind 前缀防三类 id 冲突：ex-* / pl-* / conv-*） */
type DirectoryItem =
  | { kind: 'ex'; id: string; updatedAt: string; isDeleted: boolean; view: SessionViewDto }
  | { kind: 'pl'; id: string; updatedAt: string; isDeleted: false; planner: PlannerSessionDto }
  | { kind: 'conv'; id: string; updatedAt: string; isDeleted: boolean; conv: ChatConversationDto };

export function SessionsPage() {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const navigate = useNavigate();
  // #770：点击会话 → 用 title 匹配当前项目章节标题（匹配 → 章节页；否则 → 全局 chat 页）
  const chapters = useChapterStore((s) => s.chapters);

  const projects = useProjectStore((s) => s.projects);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const loadProjects = useProjectStore((s) => s.loadProjects);
  const selectProject = useProjectStore((s) => s.selectProject);

  const [plannerItems, setPlannerItems] = useState<PlannerSessionDto[]>([]);
  const [sessions, setSessions] = useState<SessionViewDto[]>([]);
  // #547：AI 对话聚合列表
  const [conversations, setConversations] = useState<ChatConversationDto[]>([]);
  // #770：行内改名 state（renameTarget = conversation_id；renameValue = 输入值）
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [filter, setFilter] = useState<SessionFilter>('all');
  const [search, setSearch] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [plannerLoaded, setPlannerLoaded] = useState(false);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [conversationsLoaded, setConversationsLoaded] = useState(false);
  // S3e F6：页内错误态（任一顶部数据源失败）+ 重试计数器（retry 触发三路 effect 重新拉取）
  const [loadError, setLoadError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const projectDefaulted = useRef(false);
  // 三类数据全部落定后才渲染目录卡片（避免异步竞态导致部分卡片闪现）
  const allLoaded = plannerLoaded && sessionsLoaded && conversationsLoaded;

  // 项目列表：项目选择器 + 按项目过滤的目录数据源
  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  // 仅在未选项目（路由直入 / 初始空）时回退首个项目；不覆盖用户已选项目
  useEffect(() => {
    if (currentProjectId === null && projects.length > 0 && !projectDefaulted.current) {
      projectDefaulted.current = true;
      selectProject(projects[0].id);
    }
  }, [projects, currentProjectId, selectProject]);

  // 访谈会话：一次拉取全量（缺省分页 50）
  useEffect(() => {
    void fetchPlannerSessions()
      .then((res) => setPlannerItems(res.items))
      .catch((err) => {
        pushToast('err', errorMessage(err));
        setLoadError(true);
      })
      .finally(() => setPlannerLoaded(true));
  }, [pushToast, reloadKey]);

  // 执行会话：一次拉取含已归档全量，chips 切换纯本地过滤不重拉
  useEffect(() => {
    void fetchSessions({ includeDeleted: true })
      .then((res) => setSessions(res.items))
      .catch((err) => {
        pushToast('err', errorMessage(err));
        setLoadError(true);
      })
      .finally(() => setSessionsLoaded(true));
  }, [pushToast, reloadKey]);

  // #547/#581：AI 对话聚合列表（含已归档全量，失败静默）
  useEffect(() => {
    void fetchChatConversations({ includeDeleted: true })
      .then((res) => setConversations(res.items))
      .catch(() => {
        // S3e F6：任一数据源失败 → 页内错误态（重试按钮可整页重拉）
        setLoadError(true);
      })
      .finally(() => setConversationsLoaded(true));
  }, [reloadKey]);

  /** 统一目录：三类会话按 currentProjectId 合并 → filter/search 过滤 → updated_at 倒序 */
  const directoryItems = useMemo(() => {
    const projectSessions = sessions.filter((v) => v.session.project_id === currentProjectId);
    const projectPlanners = plannerItems.filter((p) => p.project_id === currentProjectId);
    const projectConvs = conversations.filter((c) => c.project_id === currentProjectId);
    // 统一窗口无条件合并三类（#725 Q1=A / Q3）：执行 + 访谈 + AI 对话
    const items: DirectoryItem[] = [
      ...projectSessions.map((view) => ({
        kind: 'ex' as const,
        id: view.session.id,
        updatedAt: view.session.updated_at,
        isDeleted: view.session.is_deleted,
        view,
      })),
      ...projectPlanners.map((planner) => ({
        kind: 'pl' as const,
        id: planner.id,
        updatedAt: planner.updated_at,
        isDeleted: false as const,
        planner,
      })),
      ...projectConvs.map((conv) => ({
        kind: 'conv' as const,
        id: `conv-${conv.conversation_id}`,
        updatedAt: conv.updated_at,
        isDeleted: conv.is_deleted,
        conv,
      })),
    ];

    return items
      .filter((item) => {
        if (filter === 'archived') return item.isDeleted;
        if (filter === 'active') return !item.isDeleted;
        return true;
      })
      .filter((item) => {
        const q = search.trim().toLowerCase();
        if (!q) return true;
        const projectName = (projectId: string | null): string =>
          projects.find((p) => p.id === projectId)?.name ?? '';
        if (item.kind === 'ex') {
          const s = item.view.session;
          return [s.title, projectName(s.project_id), item.view.last_log?.message ?? ''].some((f) =>
            f.toLowerCase().includes(q),
          );
        }
        if (item.kind === 'pl') {
          return [item.planner.one_liner, projectName(item.planner.project_id)].some((f) =>
            f.toLowerCase().includes(q),
          );
        }
        return [item.conv.title ?? '', item.conv.project_name ?? '', item.conv.last_message].some((f) =>
          f.toLowerCase().includes(q),
        );
      })
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }, [sessions, plannerItems, conversations, projects, currentProjectId, filter, search]);

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

  /** #581：AI 对话会话归档（软删），成功后本地置 is_deleted=true 转归档态 */
  const handleArchiveConversation = async (conversationId: string): Promise<void> => {
    try {
      await archiveChatConversation(conversationId);
      setConversations((prev) =>
        prev.map((c) => (c.conversation_id === conversationId ? { ...c, is_deleted: true } : c)),
      );
      pushToast('ok', t('sessions.archivedToast'));
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  /** #581：AI 对话会话恢复：POST conversations/{projectId}/restore → 本地置 is_deleted=false 回活动态 */
  const handleRestoreConversation = async (conversationId: string): Promise<void> => {
    try {
      await restoreChatConversation(conversationId);
      setConversations((prev) =>
        prev.map((c) => (c.conversation_id === conversationId ? { ...c, is_deleted: false } : c)),
      );
      pushToast('ok', t('sessions.restoredToast'));
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  /** #566：AI 对话会话真删（force=true），成功后本地移除该卡片 */
  const handleDeleteConversation = async (conversationId: string): Promise<void> => {
    try {
      await deleteChatConversation(conversationId);
      setConversations((prev) => prev.filter((c) => c.conversation_id !== conversationId));
      pushToast('ok', t('sessions.deletedToast'));
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  /** #770：行内改名提交 → PATCH /chat/conversations/{id} body {title}；成功本地更新 + ok toast */
  const handleRenameConversation = async (): Promise<void> => {
    if (!renameTarget) return;
    const id = renameTarget;
    const value = renameValue.trim();
    // f19 §4.2 边界：空 / 超 200 字符 → err toast，不发请求
    if (!value || value.length > 200) {
      pushToast('err', t('write.chat.renameInvalid'));
      return;
    }
    try {
      await renameChatConversation(id, value);
      setConversations((prev) =>
        prev.map((c) => (c.conversation_id === id ? { ...c, title: value } : c)),
      );
      pushToast('ok', t('write.chat.renamed'));
      setRenameTarget(null);
      setRenameValue('');
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  /** #770：点击会话标题 → title 匹配章节则跳章节页；否则跳全局 chat 页 */
  const handleConversationNavigate = (conv: ChatConversationDto): void => {
    const match = chapters.find((c) => c.title === conv.title);
    navigate(match ? `/writing?chapter_id=${match.id}` : `/writing?conversation_id=${conv.conversation_id}`);
  };

  /** S3e F6：整页重试——清错误 + 复位三路 loaded 标记 + reloadKey 递增触发三路重新拉取 */
  const handleRetry = (): void => {
    setLoadError(false);
    setPlannerLoaded(false);
    setSessionsLoaded(false);
    setConversationsLoaded(false);
    setReloadKey((k) => k + 1);
  };

  return (
    <div data-testid="sessions-page" className="mx-auto max-w-[1080px] px-12 py-10">
      <h1 className="font-serif text-[26px] font-semibold">{t('sessions.title')}</h1>

      {/* 顶部工具条：项目选择器 + 检索框（与会话目录同栏） */}
      <div className="mt-5 flex flex-wrap items-center gap-4">
        <Select value={currentProjectId ?? undefined} onValueChange={selectProject}>
          <SelectTrigger
            data-testid="sessions-project-select"
            aria-label={t('lib.projectSelect')}
            className="w-56"
          >
            <SelectValue placeholder={t('lib.projectSelect')} />
          </SelectTrigger>
          <SelectContent>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <input
          type="text"
          data-testid="sessions-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('sessions.search.placeholder')}
          className="h-9 min-w-[220px] flex-1 rounded-md border border-line bg-surface px-3 text-[13px] text-ink transition-colors placeholder:text-ink-3 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 focus:ring-offset-bg"
        />
      </div>

      {/* filter chips：作用于整个目录（本地过滤，不重拉） */}
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

      {/* 统一目录：AI 对话 + 访谈 + 执行 合并展示 */}
      <div data-testid="session-directory" className="mt-6">
        {loadError ? (
          <div
            data-testid="sessions-error"
            role="alert"
            className="rounded-lg border border-err/30 bg-surface p-6 text-sm text-err"
          >
            <p>{t('lib.loadFailed')}</p>
            <button
              type="button"
              data-testid="sessions-retry"
              className="mt-4 rounded-md border border-line bg-surface px-4 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-ink"
              onClick={handleRetry}
            >
              {t('lib.retry')}
            </button>
          </div>
        ) : !allLoaded ? (
          <div
            data-testid="sessions-loading"
            role="status"
            className="rounded-lg border border-dashed border-line bg-surface px-6 py-12 text-center text-[13px] text-ink-2"
          >
            {t('common.loading')}
          </div>
        ) : directoryItems.length === 0 ? (
          <div
            data-testid="sessions-empty"
            className="rounded-lg border border-dashed border-line bg-surface px-6 py-12 text-center text-[13px] text-ink-2"
          >
            {t('sessions.empty')}
          </div>
        ) : (
          <ul className="space-y-3">
            {directoryItems.map((item) => (
              <li
                key={`${item.kind}-${item.id}`}
                data-testid="session-directory-card"
                className="rounded-lg border border-line bg-surface p-4"
              >
                {item.kind === 'ex' ? (
                  <>
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        data-testid={`session-type-${item.view.session.id}`}
                        className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                      >
                        {t('sessions.badge.execution')}
                      </span>
                      <span className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-3">
                        {SESSION_TYPE_LABEL[item.view.session.session_type]
                          ? t(SESSION_TYPE_LABEL[item.view.session.session_type])
                          : item.view.session.session_type}
                      </span>
                      <span
                        data-testid={`session-status-${item.view.session.id}`}
                        className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                      >
                        {SESSION_STATUS_LABEL[item.view.session.status]
                          ? t(SESSION_STATUS_LABEL[item.view.session.status])
                          : item.view.session.status}
                      </span>
                      {item.view.session.is_deleted && (
                        <span
                          data-testid={`session-archived-${item.view.session.id}`}
                          className="rounded bg-surface-3 px-2 py-0.5 text-[11px] text-ink-3"
                        >
                          {t('sessions.archived')}
                        </span>
                      )}
                      <h3 className="ml-auto font-serif text-[15px] font-semibold text-ink">
                        <span data-testid={`session-title-${item.view.session.id}`}>
                          {item.view.session.title}
                        </span>
                      </h3>
                    </div>
                    <div className="mt-3 flex gap-2">
                      {!item.view.session.is_deleted ? (
                        <button
                          type="button"
                          data-testid={`session-archive-${item.view.session.id}`}
                          className="rounded-md border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 hover:text-ink"
                          onClick={() => void handleArchive(item.view.session.id)}
                        >
                          {t('sessions.archive')}
                        </button>
                      ) : (
                        <button
                          type="button"
                          data-testid={`session-restore-${item.view.session.id}`}
                          className="rounded-md border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 hover:text-ink"
                          onClick={() => void handleRestore(item.view.session.id)}
                        >
                          {t('sessions.restore')}
                        </button>
                      )}
                      <button
                        type="button"
                        data-testid={`session-delete-${item.view.session.id}`}
                        className="rounded-md border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 transition-colors duration-180 hover:border-err/50 hover:text-err"
                        onClick={() => setDeleteTarget(item.view.session.id)}
                      >
                        {t('sessions.delete')}
                      </button>
                    </div>
                  </>
                ) : item.kind === 'pl' ? (
                  <>
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        data-testid={`session-type-${item.planner.id}`}
                        className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                      >
                        {t('sessions.badge.interview')}
                      </span>
                      <span
                        data-testid={`session-status-${item.planner.id}`}
                        className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                      >
                        {PLANNER_STATUS_LABEL[item.planner.status]
                          ? t(PLANNER_STATUS_LABEL[item.planner.status])
                          : item.planner.status}
                      </span>
                      <span
                        data-testid={`planner-confirmed-${item.planner.id}`}
                        className="ml-auto text-[12px] text-ink-3"
                      >
                        {t('sessions.planner.confirmed', { n: (item.planner.confirmed_items ?? []).length })}
                      </span>
                    </div>
                    <h3 className="mt-2 font-serif text-[15px] font-semibold text-ink">
                      <span data-testid={`session-title-${item.planner.id}`}>
                        {item.planner.one_liner}
                      </span>
                    </h3>
                    {item.planner.writing_plan_id ? (
                      <span
                        data-testid={`planner-writing-plan-${item.planner.id}`}
                        className="mt-2 inline-block rounded bg-surface-3 px-2 py-0.5 text-[12px] text-ink-2"
                      >
                        {t('sessions.planner.writingPlan')}
                      </span>
                    ) : null}
                  </>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        data-testid={`session-type-conv-${item.conv.conversation_id}`}
                        className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                      >
                        {t('sessions.badge.ai')}
                      </span>
                      {!item.conv.is_deleted ? (
                        <span
                          data-testid={`session-status-conv-${item.conv.conversation_id}`}
                          className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                        >
                          {t('sessions.status.active')}
                        </span>
                      ) : (
                        <>
                          <span
                            data-testid={`session-archived-conv-${item.conv.conversation_id}`}
                            className="rounded bg-surface-3 px-2 py-0.5 text-[11px] text-ink-3"
                          >
                            {t('sessions.archived')}
                          </span>
                          <span
                            data-testid={`chat-conv-archived-${item.conv.conversation_id}`}
                            className="rounded bg-surface-3 px-2 py-0.5 text-[11px] text-ink-3"
                          >
                            {t('sessions.archived')}
                          </span>
                        </>
                      )}
                      <h3 className="font-serif text-[15px] font-semibold text-ink">
                        <button
                          type="button"
                          data-testid={`session-title-conv-${item.conv.conversation_id}`}
                          onClick={() => handleConversationNavigate(item.conv)}
                          className="text-left hover:text-accent"
                        >
                          {/* #770：title 空回退 project_name；两者皆空 → 未命名会话 */}
                          {item.conv.title || item.conv.project_name || t('sessions.chat.titleEmpty')}
                        </button>
                      </h3>
                      <span className="ml-auto rounded bg-surface-3 px-2 py-0.5 text-[12px] text-ink-2">
                        {t('sessions.chat.count', { n: item.conv.message_count })}
                      </span>
                    </div>
                    {/* #825：title 与 last_message 相同时不重复展示（一次一个清晰标题）；不同时保留消息预览 */}
                    {item.conv.last_message !== item.conv.title ? (
                      <p className="mt-2 truncate text-[13px] text-ink-2">{item.conv.last_message}</p>
                    ) : null}
                    <div className="mt-3 flex gap-2">
                      {renameTarget === item.conv.conversation_id ? (
                        <input
                          type="text"
                          data-testid={`chat-conv-rename-input-${item.conv.conversation_id}`}
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              void handleRenameConversation();
                            } else if (e.key === 'Escape') {
                              setRenameTarget(null);
                              setRenameValue('');
                            }
                          }}
                          autoFocus
                          className="h-8 w-48 rounded-md border border-line bg-surface px-2 text-[13px] text-ink outline-none focus:border-accent"
                        />
                      ) : (
                        <button
                          type="button"
                          data-testid={`chat-conv-rename-${item.conv.conversation_id}`}
                          className="rounded-md border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 hover:text-ink"
                          onClick={() => {
                            setRenameTarget(item.conv.conversation_id);
                            setRenameValue(item.conv.title ?? '');
                          }}
                        >
                          {t('write.chat.rename')}
                        </button>
                      )}
                      {!item.conv.is_deleted ? (
                        <button
                          type="button"
                          data-testid={`chat-conv-archive-${item.conv.conversation_id}`}
                          className="rounded-md border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 hover:text-ink"
                          onClick={() => void handleArchiveConversation(item.conv.conversation_id)}
                        >
                          {t('sessions.archive')}
                        </button>
                      ) : (
                        <button
                          type="button"
                          data-testid={`chat-conv-restore-${item.conv.conversation_id}`}
                          className="rounded-md border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 hover:text-ink"
                          onClick={() => void handleRestoreConversation(item.conv.conversation_id)}
                        >
                          {t('sessions.restore')}
                        </button>
                      )}
                      <button
                        type="button"
                        data-testid={`chat-conv-delete-${item.conv.conversation_id}`}
                        className="rounded-md border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 transition-colors duration-180 hover:border-err/50 hover:text-err"
                        onClick={() => void handleDeleteConversation(item.conv.conversation_id)}
                      >
                        {t('sessions.delete')}
                      </button>
                    </div>
                    <span
                      data-testid={`chat-conversation-updated-${item.conv.conversation_id}`}
                      className="mt-2 block text-[11px] text-ink-3"
                    >
                      {item.conv.updated_at}
                    </span>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

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
