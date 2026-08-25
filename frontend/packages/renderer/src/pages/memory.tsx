/**
 * #486 会话/记忆 UI — 记忆页（语义总结展示 + 提取记忆 + 项目/用户级偏好管理）.
 * 无项目态不发任何请求；有项目态并行加载总结/偏好，切换项目重拉项目级数据.
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  createProjectPreference,
  createUserPreference,
  fetchMemoryStats,
  fetchMemorySummaries,
  fetchProjectPreferences,
  fetchUserPreferences,
  removeProjectPreference,
  removeMemorySummary,
  removeUserPreference,
  summarizeMemory,
  updateProjectPreference,
  updateUserPreference,
  type MemorySummariesResponse,
  type MemorySummaryDto,
  type MemoryStatsResponse,
  type PreferenceInput,
  type ProjectPreferenceDto,
  type UserPreferenceDto,
} from '../api/memory';
import { errorMessage } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useI18n } from '../i18n/useI18n';
import { useToastStore } from '../stores/toast';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';

/** 项目级偏好 category 文案映射（未知分类原样展示） */
const CATEGORY_LABEL: Record<string, string> = {
  addressing: 'memory.cat.addressing',
  style_word: 'memory.cat.style_word',
  structure: 'memory.cat.structure',
  other: 'memory.cat.other',
};

/** 用户级偏好 category 文案映射（未知分类原样展示） */
const USER_CATEGORY_LABEL: Record<string, string> = {
  addressing: 'memory.cat.user.addressing',
  style_word: 'memory.cat.user.style_word',
  structure: 'memory.cat.user.structure',
  other: 'memory.cat.user.other',
};

/** 长文本截断阈值（超过才渲染展开按钮，测试不锁细节） */
const EXPAND_THRESHOLD = 200;

/** 项目级语义总结卡片（content 全文 + meta 拼接 model · updated_at） */
function SummaryCard({ summary }: { summary: MemorySummaryDto }) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const long = summary.content.length > EXPAND_THRESHOLD;
  return (
    <div data-testid="memory-summary-card" className="rounded-lg border border-line bg-surface p-4">
      <p
        data-testid="memory-summary-content"
        className={!expanded && long ? 'line-clamp-3 text-[13px] leading-relaxed text-ink' : 'text-[13px] leading-relaxed text-ink'}
      >
        {summary.content}
      </p>
      {long && (
        <button
          type="button"
          data-testid="memory-summary-expand"
          className="mt-2 text-[12px] text-accent"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? t('memory.summary.collapse') : t('memory.summary.expand')}
        </button>
      )}
      <p data-testid="memory-summary-meta" className="mt-2 text-[12px] text-ink-3">
        {summary.model} · {summary.updated_at}
      </p>
    </div>
  );
}

/** #658：统计数字卡（只读，label + 值） */
function StatCard({ label, testid, value }: { label: string; testid: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <p className="text-[12px] text-ink-3">{label}</p>
      <p data-testid={testid} className="mt-1 font-serif text-[20px] font-semibold text-ink">
        {value}
      </p>
    </div>
  );
}

export function MemoryPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const projects = useProjectStore((s) => s.projects);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const pushToast = useToastStore((s) => s.pushToast);

  const [pid, setPid] = useState<string | null>(currentProjectId);
  const [summaries, setSummaries] = useState<MemorySummariesResponse | null>(null);
  const [prefs, setPrefs] = useState<ProjectPreferenceDto[]>([]);
  const [userPrefs, setUserPrefs] = useState<UserPreferenceDto[]>([]);
  const [memoryStats, setMemoryStats] = useState<MemoryStatsResponse | null>(null);
  const [statsError, setStatsError] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [scope, setScope] = useState<'project' | 'user'>('project');
  const [editing, setEditing] = useState<{ kind: 'project' | 'user'; id: string } | null>(null);
  const [addCategory, setAddCategory] = useState('addressing');
  const [addPattern, setAddPattern] = useState('');
  const [addValue, setAddValue] = useState('');

  /** 无项目态：projects 为空或 currentProjectId 为 null 时不出任何请求 */
  const hasProject = projects.length > 0 && currentProjectId !== null && pid !== null;

  // 加载 effect（依赖 pid）：并行拉项目级总结/偏好 + 用户级偏好
  useEffect(() => {
    if (!pid) return;
    let cancelled = false;
    void Promise.all([
      fetchMemorySummaries(pid),
      fetchProjectPreferences(pid),
      fetchUserPreferences(),
    ])
      .then(([s, p, u]) => {
        if (cancelled) return;
        setSummaries(s);
        setPrefs(p.items);
        setUserPrefs(u.items);
      })
      .catch((err) => {
        if (!cancelled) pushToast('err', errorMessage(err));
      });
    // #658：统计 fetch 单独 fire（不并入 Promise.all，失败只置 statsError，不弹 err toast、不阻断页面）
    fetchMemoryStats(pid)
      .then((s) => {
        if (!cancelled) setMemoryStats(s);
      })
      .catch(() => {
        if (!cancelled) setStatsError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [pid, pushToast]);

  const handleExtract = async (): Promise<void> => {
    if (!pid || extracting) return;
    setExtracting(true);
    setExtractError(null);
    try {
      const result = await summarizeMemory(pid, true);
      // 提取成功后刷新 summaries（也可直接 set 返回的 project/user，两种实现最终态一致）
      setSummaries(await fetchMemorySummaries(pid));
      // #546：提取反馈——有内容成功 toast；无内容（summarized=false）提示暂无内容
      if (result.summarized) {
        pushToast('ok', t('memory.extract.success'));
      } else {
        pushToast('warn', t('memory.extract.noContent'));
      }
    } catch (err) {
      setExtractError(errorMessage(err));
    } finally {
      setExtracting(false);
    }
  };

  /** #F49：删除语义总结（成功 → 重拉 summaries 走空态 + 成功 toast；失败 → 错误 toast 且卡片仍在） */
  const handleRemoveSummary = async (): Promise<void> => {
    if (!pid) return;
    try {
      await removeMemorySummary(pid);
      setSummaries(await fetchMemorySummaries(pid));
      pushToast('ok', t('memory.summary.deleteSuccess'));
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  const handleRemovePref = async (id: string): Promise<void> => {
    try {
      await removeProjectPreference(id);
      setPrefs((prev) => prev.filter((p) => p.id !== id));
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  const handleRemoveUserPref = async (id: string): Promise<void> => {
    try {
      await removeUserPreference(id);
      setUserPrefs((prev) => prev.filter((p) => p.id !== id));
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  /** #521：手动添加/编辑偏好（项目级/全局级双作用域；编辑态更新原行，新增态追加新行） */
  const handleAddSubmit = async (): Promise<void> => {
    const input: PreferenceInput = { category: addCategory, pattern: addPattern, value: addValue };
    try {
      if (editing) {
        if (editing.kind === 'project') {
          const updated = await updateProjectPreference(editing.id, input);
          setPrefs((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
        } else {
          const updated = await updateUserPreference(editing.id, input);
          setUserPrefs((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
        }
      } else if (scope === 'project' && pid) {
        const created = await createProjectPreference(pid, input);
        setPrefs((prev) => [...prev, created]);
      } else {
        const created = await createUserPreference(input);
        setUserPrefs((prev) => [...prev, created]);
      }
      setAddOpen(false);
      setEditing(null);
      setAddPattern('');
      setAddValue('');
    } catch (err) {
      pushToast('err', errorMessage(err));
    }
  };

  /** #521：取消 = 关闭表单 + 清空 pattern/value + 退出编辑态（不调任何 create/update API） */
  const handleAddCancel = useCallback((): void => {
    setAddOpen(false);
    setAddPattern('');
    setAddValue('');
    setEditing(null);
  }, []);

  /** #546：弹框 Esc 关闭（document 级监听；尊重 Radix Select 等已 preventDefault 的 Escape） */
  useEffect(() => {
    if (!addOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) handleAddCancel();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [addOpen, handleAddCancel]);

  if (!hasProject) {
    return (
      <div data-testid="memory-page" className="mx-auto max-w-[1080px] px-12 py-10">
        <h1 className="font-serif text-[26px] font-semibold">{t('memory.title')}</h1>
        <div
          data-testid="memory-no-project"
          className="mt-8 flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-16 text-center"
        >
          <p className="font-serif text-[17px] font-semibold text-ink">{t('memory.noProject')}</p>
          <button
            type="button"
            data-testid="memory-go-projects"
            className="mt-5 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={() => navigate('/projects')}
          >
            {t('memory.goProjects')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="memory-page" className="mx-auto max-w-[1080px] px-12 py-10">
      <h1 className="font-serif text-[26px] font-semibold">{t('memory.title')}</h1>

      {/* 项目选择（Radix Select，镜像 search 页） */}
      <div className="mt-6 flex flex-col gap-1.5">
        <label className="text-[12px] text-ink-3">{t('memory.project.label')}</label>
        <Select value={pid ?? undefined} onValueChange={setPid}>
          <SelectTrigger
            data-testid="memory-project-select"
            aria-label={t('memory.project.label')}
            className="w-56"
          >
            <SelectValue placeholder={t('memory.project.label')} />
          </SelectTrigger>
          <SelectContent>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* #658：统计概览（只读数字卡；fetch 未 resolve 前不渲染，防止 total 预览为 0 破坏 findByTestId 时序） */}
      {(memoryStats !== null || statsError) && (
        <section data-testid="memory-stats-section" className="mt-8">
          <h2 className="text-[15px] font-semibold text-ink">{t('memory.stats.title')}</h2>
          {statsError && (
            <div
              data-testid="memory-stats-unavailable"
              className="mt-3 rounded-lg border border-dashed border-line bg-surface px-6 py-4 text-center text-[13px] text-ink-2"
            >
              {t('memory.stats.unavailable')}
            </div>
          )}
          {memoryStats && (
            <>
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
                <StatCard
                  label={t('memory.stats.total')}
                  testid="memory-stats-total"
                  value={String(
                    memoryStats.learned_preferences +
                      (memoryStats.user_preferences?.count ?? 0) +
                      ((summaries?.project ? 1 : 0) + (summaries?.user ? 1 : 0)),
                  )}
                />
                <StatCard
                  label={t('memory.stats.projectPrefs')}
                  testid="memory-stats-project-prefs"
                  value={String(memoryStats.learned_preferences)}
                />
                <StatCard
                  label={t('memory.stats.userPrefs')}
                  testid="memory-stats-user-prefs"
                  value={String(memoryStats.user_preferences?.count ?? 0)}
                />
                <StatCard
                  label={t('memory.stats.summaries')}
                  testid="memory-stats-summaries"
                  value={String((summaries?.project ? 1 : 0) + (summaries?.user ? 1 : 0))}
                />
              </div>
              <h3 className="mt-5 text-[13px] font-semibold text-ink-2">
                {t('memory.stats.agentic')}
              </h3>
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
                <StatCard
                  label={t('memory.stats.chapters')}
                  testid="memory-stats-chapters"
                  value={String(memoryStats.agentic.chapters)}
                />
                <StatCard
                  label={t('memory.stats.directConfirms')}
                  testid="memory-stats-direct-confirms"
                  value={String(memoryStats.agentic.direct_confirms)}
                />
                <StatCard
                  label={t('memory.stats.modifyRate')}
                  testid="memory-stats-modify-rate"
                  value={Math.round(memoryStats.agentic.modify_rate * 100) + '%'}
                />
                <StatCard
                  label={t('memory.stats.regenerateRate')}
                  testid="memory-stats-regenerate-rate"
                  value={Math.round(memoryStats.agentic.regenerate_rate * 100) + '%'}
                />
                <StatCard
                  label={t('memory.stats.avgDiffChars')}
                  testid="memory-stats-avg-diff-chars"
                  value={String(memoryStats.agentic.avg_diff_chars)}
                />
              </div>
            </>
          )}
        </section>
      )}

      {/* 提取记忆入口（#658：动作行上移到统计概览之后、语义总结之前） */}
      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          data-testid="memory-extract-btn"
          disabled={extracting}
          className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-60"
          onClick={() => void handleExtract()}
        >
          {t('memory.extract')}
        </button>
        <button
          type="button"
          data-testid="memory-add-btn"
          className="rounded-md border border-line bg-surface px-4 py-1.5 text-[13px] text-ink transition-colors duration-180 hover:bg-surface-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          onClick={() => setAddOpen(true)}
        >
          {t('memory.add.title')}
        </button>
        {extracting && (
          <span data-testid="memory-extract-loading" className="text-[13px] text-ink-2">
            {t('memory.extract.loading')}
          </span>
        )}
      </div>
      {addOpen && (
        <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t('memory.add.title')}
            data-testid="memory-add-form"
            className="w-[420px] rounded-lg border border-line bg-surface p-4 shadow-card"
            onClick={(e) => e.stopPropagation()}
          >
            {editing === null && (
              <div className="flex flex-col gap-1.5">
                <label className="text-[12px] text-ink-3">{t('memory.add.scope.label')}</label>
                <Select
                  value={scope}
                  onValueChange={(v) => setScope(v === 'user' ? 'user' : 'project')}
                >
                  <SelectTrigger
                    data-testid="memory-add-scope"
                    aria-label={t('memory.add.scope.label')}
                    className="w-56"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="project">{t('memory.add.scope.project')}</SelectItem>
                    <SelectItem value="user">{t('memory.add.scope.user')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
            {scope === 'user' && editing === null && (
              <p data-testid="memory-add-user-hint" className="mt-3 text-[12px] text-ink-2">
                {t('memory.add.user.hint')}
              </p>
            )}
            <div className="mt-3 flex flex-col gap-1.5">
              <label className="text-[12px] text-ink-3">{t('memory.add.category.label')}</label>
              <Select value={addCategory} onValueChange={setAddCategory}>
                <SelectTrigger
                  data-testid="memory-add-category"
                  aria-label={t('memory.add.category.label')}
                  className="w-56"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(CATEGORY_LABEL).map(([value, labelKey]) => (
                    <SelectItem key={value} value={value}>
                      {t(labelKey)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="mt-3 flex flex-col gap-1.5">
              <label className="text-[12px] text-ink-3">{t('memory.add.pattern.label')}</label>
              <input
                data-testid="memory-add-pattern"
                value={addPattern}
                onChange={(e) => setAddPattern(e.target.value)}
                className="rounded-md border border-line bg-surface-2 px-3 py-1.5 text-[13px] text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              />
            </div>
            <div className="mt-3 flex flex-col gap-1.5">
              <label className="text-[12px] text-ink-3">{t('memory.add.value.label')}</label>
              <input
                data-testid="memory-add-value"
                value={addValue}
                onChange={(e) => setAddValue(e.target.value)}
                className="rounded-md border border-line bg-surface-2 px-3 py-1.5 text-[13px] text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              />
            </div>
            <div className="mt-4 flex items-center gap-3">
              <button
                type="button"
                data-testid="memory-add-submit"
                className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                onClick={() => void handleAddSubmit()}
              >
                {t('memory.add.submit')}
              </button>
              <button
                type="button"
                data-testid="memory-add-cancel"
                className="rounded-md border border-line bg-surface px-4 py-1.5 text-[13px] text-ink-2 transition-colors duration-180 hover:bg-surface-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                onClick={handleAddCancel}
              >
                {t('memory.add.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}
      {extractError && (
        <div
          data-testid="memory-extract-error"
          className="mt-3 rounded-lg border border-err/40 bg-surface px-4 py-3 text-[13px] text-err"
        >
          {t('memory.extract.error')}：{extractError}
        </div>
      )}

      {/* 语义总结区块 */}
      <section data-testid="memory-summary-section" className="mt-8">
        <h2 className="text-[15px] font-semibold text-ink">{t('memory.summary.title')}</h2>
        {summaries === null ? (
          <div className="mt-3 text-[13px] text-ink-2">{t('memory.summary.empty')}</div>
        ) : summaries.project === null && summaries.user === null ? (
          <div
            data-testid="memory-summary-empty"
            className="mt-3 rounded-lg border border-dashed border-line bg-surface px-6 py-10 text-center text-[13px] text-ink-2"
          >
            {t('memory.summary.empty')}
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            {summaries.project ? <SummaryCard summary={summaries.project} /> : null}
            {summaries.user ? (
              <div
                data-testid="memory-summary-user"
                className="rounded-lg border border-line bg-surface p-4"
              >
                <h3 className="text-[13px] font-semibold text-ink-2">
                  {t('memory.summary.userLabel')}
                </h3>
                <p
                  data-testid="memory-summary-user-content"
                  className="mt-1 text-[13px] leading-relaxed text-ink"
                >
                  {summaries.user.content}
                </p>
              </div>
            ) : null}
          </div>
        )}
        {summaries?.project ? (
          <button
            type="button"
            data-testid="memory-summary-delete"
            className="mt-3 rounded-md border border-line bg-surface px-3 py-1.5 text-[12px] text-ink-2 transition-colors duration-180 hover:border-err/50 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={() => void handleRemoveSummary()}
          >
            {t('memory.summary.delete')}
          </button>
        ) : null}
      </section>

      {/* 项目偏好区块 */}
      <section data-testid="memory-prefs-section" className="mt-10">
        <h2 className="text-[15px] font-semibold text-ink">{t('memory.prefs.title')}</h2>
        {prefs.length === 0 ? (
          <div
            data-testid="memory-prefs-empty"
            className="mt-3 rounded-lg border border-dashed border-line bg-surface px-6 py-10 text-center text-[13px] text-ink-2"
          >
            {t('memory.prefs.empty')}
          </div>
        ) : (
          <ul className="mt-3 space-y-3">
            {prefs.map((p) => (
              <li
                key={p.id}
                data-testid={`memory-pref-${p.id}`}
                className="rounded-lg border border-line bg-surface p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    data-testid={`memory-pref-cat-${p.id}`}
                    className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                  >
                    {CATEGORY_LABEL[p.category] ? t(CATEGORY_LABEL[p.category]) : p.category}
                  </span>
                  <span
                    data-testid={`memory-pref-count-${p.id}`}
                    className="ml-auto text-[12px] text-ink-3"
                  >
                    {p.count}
                  </span>
                  <span
                    data-testid={`memory-pref-conf-${p.id}`}
                    className="text-[12px] text-ink-3"
                  >
                    {p.confidence}
                  </span>
                </div>
                <p className="mt-2 text-[13px] text-ink">
                  <span data-testid={`memory-pref-pattern-${p.id}`}>{p.pattern}</span>
                  <span className="mx-1.5 text-ink-3">→</span>
                  <span data-testid={`memory-pref-value-${p.id}`}>{p.value}</span>
                </p>
                <div className="mt-2 flex items-center gap-2">
                  {p.superseded_by ? (
                    <span
                      data-testid={`memory-pref-superseded-${p.id}`}
                      className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                    >
                      {t('memory.prefs.superseded')}
                      <span data-testid={`memory-pref-superseded-by-${p.id}`}>{p.superseded_by}</span>
                    </span>
                  ) : null}
                  <button
                    type="button"
                    data-testid={`memory-pref-edit-${p.id}`}
                    className="rounded-md border border-line bg-surface px-3 py-1 text-[12px] text-ink-2 transition-colors duration-180 hover:bg-surface-3"
                    onClick={() => {
                      setEditing({ kind: 'project', id: p.id });
                      setAddCategory(p.category);
                      setAddPattern(p.pattern);
                      setAddValue(p.value);
                      setAddOpen(true);
                    }}
                  >
                    {t('memory.prefs.edit')}
                  </button>
                  <button
                    type="button"
                    data-testid={`memory-pref-del-${p.id}`}
                    className="rounded-md border border-line bg-surface px-3 py-1 text-[12px] text-ink-2 transition-colors duration-180 hover:border-err/50 hover:text-err"
                    onClick={() => void handleRemovePref(p.id)}
                  >
                    {t('memory.prefs.delete')}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* 用户级偏好区块 */}
      <section data-testid="memory-userprefs-section" className="mt-10">
        <h2 className="text-[15px] font-semibold text-ink">{t('memory.userPrefs.title')}</h2>
        {userPrefs.length === 0 ? (
          <div
            data-testid="memory-userprefs-empty"
            className="mt-3 rounded-lg border border-dashed border-line bg-surface px-6 py-10 text-center text-[13px] text-ink-2"
          >
            {t('memory.userPrefs.empty')}
          </div>
        ) : (
          <ul className="mt-3 space-y-3">
            {userPrefs.map((p) => (
              <li
                key={p.id}
                data-testid={`memory-userpref-${p.id}`}
                className="rounded-lg border border-line bg-surface p-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    data-testid={`memory-userpref-cat-${p.id}`}
                    className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                  >
                    {USER_CATEGORY_LABEL[p.category]
                      ? t(USER_CATEGORY_LABEL[p.category])
                      : p.category}
                  </span>
                  <span
                    data-testid={`memory-userpref-count-${p.id}`}
                    className="ml-auto text-[12px] text-ink-3"
                  >
                    {p.count}
                  </span>
                  <span
                    data-testid={`memory-userpref-conf-${p.id}`}
                    className="text-[12px] text-ink-3"
                  >
                    {p.confidence}
                  </span>
                  <span
                    data-testid={`memory-userpref-projects-${p.id}`}
                    className="text-[12px] text-ink-3"
                  >
                    {p.project_count}
                  </span>
                </div>
                <p className="mt-2 text-[13px] text-ink">
                  <span data-testid={`memory-userpref-pattern-${p.id}`}>{p.pattern}</span>
                  <span className="mx-1.5 text-ink-3">→</span>
                  <span data-testid={`memory-userpref-value-${p.id}`}>{p.value}</span>
                </p>
                <div className="mt-2 flex items-center gap-2">
                  {p.superseded_by ? (
                    <span
                      data-testid={`memory-userpref-superseded-${p.id}`}
                      className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2"
                    >
                      {t('memory.prefs.superseded')}
                      <span data-testid={`memory-userpref-superseded-by-${p.id}`}>{p.superseded_by}</span>
                    </span>
                  ) : null}
                  <button
                    type="button"
                    data-testid={`memory-userpref-edit-${p.id}`}
                    className="rounded-md border border-line bg-surface px-3 py-1 text-[12px] text-ink-2 transition-colors duration-180 hover:bg-surface-3"
                    onClick={() => {
                      setEditing({ kind: 'user', id: p.id });
                      setAddCategory(p.category);
                      setAddPattern(p.pattern);
                      setAddValue(p.value);
                      setAddOpen(true);
                    }}
                  >
                    {t('memory.prefs.edit')}
                  </button>
                  <button
                    type="button"
                    data-testid={`memory-userpref-del-${p.id}`}
                    className="rounded-md border border-line bg-surface px-3 py-1 text-[12px] text-ink-2 transition-colors duration-180 hover:border-err/50 hover:text-err"
                    onClick={() => void handleRemoveUserPref(p.id)}
                  >
                    {t('memory.prefs.delete')}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
