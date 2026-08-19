/**
 * #486 会话/记忆 UI — 记忆页（语义总结展示 + 提取记忆 + 项目/用户级偏好管理）.
 * 无项目态不发任何请求；有项目态并行加载总结/偏好，切换项目重拉项目级数据.
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchMemorySummaries,
  fetchProjectPreferences,
  fetchUserPreferences,
  removeProjectPreference,
  removeUserPreference,
  summarizeMemory,
  type MemorySummariesResponse,
  type MemorySummaryDto,
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
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);

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
    return () => {
      cancelled = true;
    };
  }, [pid, pushToast]);

  const handleExtract = async (): Promise<void> => {
    if (!pid || extracting) return;
    setExtracting(true);
    setExtractError(null);
    try {
      await summarizeMemory(pid, true);
      // 提取成功后刷新 summaries（也可直接 set 返回的 project/user，两种实现最终态一致）
      setSummaries(await fetchMemorySummaries(pid));
    } catch (err) {
      setExtractError(errorMessage(err));
    } finally {
      setExtracting(false);
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
      </section>

      {/* 提取记忆入口 */}
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
        {extracting && (
          <span data-testid="memory-extract-loading" className="text-[13px] text-ink-2">
            {t('memory.extract.loading')}
          </span>
        )}
      </div>
      {extractError && (
        <div
          data-testid="memory-extract-error"
          className="mt-3 rounded-lg border border-err/40 bg-surface px-4 py-3 text-[13px] text-err"
        >
          {t('memory.extract.error')}：{extractError}
        </div>
      )}

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
                <button
                  type="button"
                  data-testid={`memory-pref-del-${p.id}`}
                  className="mt-2 rounded-md border border-line bg-surface px-3 py-1 text-[12px] text-ink-2 transition-colors duration-180 hover:border-err/50 hover:text-err"
                  onClick={() => void handleRemovePref(p.id)}
                >
                  {t('memory.prefs.delete')}
                </button>
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
                </div>
                <p className="mt-2 text-[13px] text-ink">
                  <span data-testid={`memory-userpref-pattern-${p.id}`}>{p.pattern}</span>
                  <span className="mx-1.5 text-ink-3">→</span>
                  <span data-testid={`memory-userpref-value-${p.id}`}>{p.value}</span>
                </p>
                <button
                  type="button"
                  data-testid={`memory-userpref-del-${p.id}`}
                  className="mt-2 rounded-md border border-line bg-surface px-3 py-1 text-[12px] text-ink-2 transition-colors duration-180 hover:border-err/50 hover:text-err"
                  onClick={() => void handleRemoveUserPref(p.id)}
                >
                  {t('memory.prefs.delete')}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
