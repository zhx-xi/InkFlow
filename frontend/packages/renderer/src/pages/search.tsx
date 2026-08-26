/** #480 检索页（Issue #480 RAG embedding 增强检索）：消费既有端点 GET /api/v1/search，纯前端零后端改动 */
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, Search } from 'lucide-react';
import { fetchSearch, type SearchResponseDto } from '../api/search';
import {
  fetchIndexRebuildStatus,
  postIndexRebuild,
  type IndexRebuildStatusDto,
} from '../api/index';
import { errorMessage } from '../api/client';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
import { useI18n } from '../i18n/useI18n';
import { ConfirmDialog } from '../components/ConfirmDialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';

type SearchMode = 'keyword' | 'semantic';

/** #657 索引维护：项目范围（当前项目 → [currentProjectId]；全部项目 → null） */
type RebuildProjectScope = 'current' | 'all';
/** #657 索引维护：索引类型（两者 / 仅全文 FTS5 / 仅向量 embedding） */
type RebuildIndexScope = 'both' | 'fulltext' | 'vector';

/** #657 重建三态反馈（页面内联，不走 Toast store）：idle / running（轮询中）/ done / error */
type RebuildPhase =
  | { phase: 'idle' }
  | { phase: 'running'; taskId: string; status: IndexRebuildStatusDto | null }
  | { phase: 'done'; rebuiltAt: string; projectCount: number }
  | { phase: 'error'; message: string };

/** entity_type 徽标中文映射（未知类型直出原值） */
const ENTITY_TYPE_LABEL: Record<string, string> = {
  character: '角色',
  chapter: '章节',
  world: '世界观',
  outline: '大纲',
  timeline: '时间线',
  foreshadow: '伏笔',
};

export function SearchPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const projects = useProjectStore((s) => s.projects);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);

  const [q, setQ] = useState('');
  const [mode, setMode] = useState<SearchMode>('semantic');
  const [projectId, setProjectId] = useState<string | null>(currentProjectId);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SearchResponseDto | null>(null);
  const [error, setError] = useState<string | null>(null);

  // #657 索引维护
  const [rebuildProjectScope, setRebuildProjectScope] = useState<RebuildProjectScope>('current');
  const [rebuildIndexScope, setRebuildIndexScope] = useState<RebuildIndexScope>('both');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [rebuildPhase, setRebuildPhase] = useState<RebuildPhase>({ phase: 'idle' });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // #657 组件卸载时清理轮询定时器（防内存泄漏）
  useEffect(() => {
    return () => {
      if (pollRef.current !== null) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, []);

  const handleSearch = async (e: FormEvent) => {
    e.preventDefault();
    const query = q.trim();
    // q strip 后为空 / 未选项目 → 不发请求
    if (!query || !projectId) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await fetchSearch({ q: query, projectId, mode }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const handleHitClick = (entityType: string, entityId: string) => {
    switch (entityType) {
      case 'chapter':
        navigate('/writing');
        void useChapterStore.getState().selectChapter(entityId);
        break;
      case 'character':
        navigate('/library?cat=characters');
        break;
      case 'world':
        navigate('/library?cat=world');
        break;
      case 'outline':
        navigate('/library?cat=outline');
        break;
      case 'timeline':
        navigate('/library?cat=timeline');
        break;
      case 'foreshadow':
        navigate('/library?cat=foreshadow');
        break;
      default:
        break;
    }
  };

  /** #657 轮询一次重建进度：done/failed → 停止轮询并落三态；running → 刷新进度；单次失败保持 loading */
  const pollRebuildStatus = async (taskId: string) => {
    try {
      const status = await fetchIndexRebuildStatus(taskId);
      if (status.status === 'done') {
        if (pollRef.current !== null) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        setRebuildPhase({
          phase: 'done',
          rebuiltAt: status.rebuilt_at ?? '',
          projectCount: status.progress_total,
        });
      } else if (status.status === 'failed') {
        if (pollRef.current !== null) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        setRebuildPhase({ phase: 'error', message: status.error ?? t('search.maintenance.fail') });
      } else {
        setRebuildPhase({ phase: 'running', taskId, status });
      }
    } catch (err) {
      if (pollRef.current !== null) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      setRebuildPhase({ phase: 'error', message: errorMessage(err) });
    }
  };

  /** #657 确认重建：postIndexRebuild 成功 → 立即查一次 + 每 2s 轮询；失败 → 直接 err（不启动轮询） */
  const handleConfirmRebuild = async () => {
    setConfirmOpen(false);
    // 当前项目范围但未选中项目 → 退化为全部项目（null = 后端默认全部，避免发送 [null]）
    const projectIds: string[] | null =
      rebuildProjectScope === 'current' && currentProjectId ? [currentProjectId] : null;
    try {
      const start = await postIndexRebuild({
        project_ids: projectIds,
        scope: rebuildIndexScope,
      });
      const taskId = start.task_id;
      setRebuildPhase({ phase: 'running', taskId, status: null });
      void pollRebuildStatus(taskId);
      pollRef.current = setInterval(() => {
        void pollRebuildStatus(taskId);
      }, 2000);
    } catch (err) {
      setRebuildPhase({ phase: 'error', message: errorMessage(err) });
    }
  };

  /** #657 当前重建进度文案（spinner 提示 + 步骤 + N/M 项目进度） */
  const rebuildStatusText = (status: IndexRebuildStatusDto | null): string => {
    if (!status) return t('search.maintenance.loading');
    const step =
      status.step === 'fulltext'
        ? t('search.maintenance.step.fulltext')
        : t('search.maintenance.step.vector');
    return `${t('search.maintenance.loading')} · ${step} · ${t('search.maintenance.progress', {
      done: status.progress_done,
      total: status.progress_total,
    })}`;
  };

  return (
    <div data-testid="search-page" className="mx-auto max-w-[1080px] px-12 py-10">
      <h1 className="font-serif text-[26px] font-semibold">{t('search.title')}</h1>
      <p className="mt-1 text-[13px] text-ink-2">{t('search.sub')}</p>

      {projects.length === 0 ? (
        <div
          data-testid="search-no-project"
          className="mt-8 flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-16 text-center"
        >
          <Search className="h-10 w-10 text-ink-3" aria-hidden="true" />
          <p className="mt-3 font-serif text-[17px] font-semibold text-ink">{t('search.noProject')}</p>
          <button
            type="button"
            data-testid="search-go-projects"
            className="mt-5 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={() => navigate('/projects')}
          >
            {t('lib.empty.goProjects')}
          </button>
        </div>
      ) : (
        <>
          <form className="mt-6 flex flex-wrap items-end gap-4" onSubmit={handleSearch}>
            <div className="flex flex-col gap-1.5">
              <label className="text-[12px] text-ink-3">{t('search.mode.label')}</label>
              <Select value={mode} onValueChange={(v) => setMode(v as SearchMode)}>
                <SelectTrigger
                  data-testid="search-mode-select"
                  aria-label={t('search.mode.label')}
                  className="w-32"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="semantic">{t('search.mode.semantic')}</SelectItem>
                  <SelectItem value="keyword">{t('search.mode.keyword')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-[12px] text-ink-3">{t('search.project.label')}</label>
              <Select value={projectId ?? undefined} onValueChange={setProjectId}>
                <SelectTrigger
                  data-testid="search-project-select"
                  aria-label={t('search.project.label')}
                  className="w-56"
                >
                  <SelectValue placeholder={t('search.project.placeholder')} />
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

            <input
              data-testid="search-input"
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('search.placeholder')}
              aria-label={t('search.placeholder')}
              className="h-9 w-full max-w-xs rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-ring/60"
            />
            <button
              type="submit"
              data-testid="search-btn"
              className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            >
              {t('search.btn')}
            </button>
          </form>

          {/* #657 索引维护：异步重建全文 FTS5 + 向量索引（后端 #659 配套） */}
          <section
            data-testid="rebuild-card"
            className="mt-8 rounded-lg border border-line bg-surface p-6 shadow-card"
          >
            <h2 className="font-serif text-[17px] font-semibold">{t('search.maintenance.title')}</h2>
            <p className="mt-1 text-[13px] text-ink-2">{t('search.maintenance.desc')}</p>

            <div className="mt-5 flex flex-wrap items-end gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-[12px] text-ink-3">
                  {t('search.maintenance.project.label')}
                </label>
                <Select
                  value={rebuildProjectScope}
                  onValueChange={(v) => setRebuildProjectScope(v as RebuildProjectScope)}
                >
                  <SelectTrigger
                    data-testid="rebuild-project-scope"
                    aria-label={t('search.maintenance.project.label')}
                    className="w-56"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="current">{t('search.maintenance.project.current')}</SelectItem>
                    <SelectItem value="all">{t('search.maintenance.project.all')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-[12px] text-ink-3">
                  {t('search.maintenance.index.label')}
                </label>
                <Select
                  value={rebuildIndexScope}
                  onValueChange={(v) => setRebuildIndexScope(v as RebuildIndexScope)}
                >
                  <SelectTrigger
                    data-testid="rebuild-index-scope"
                    aria-label={t('search.maintenance.index.label')}
                    className="w-56"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="both">{t('search.maintenance.index.both')}</SelectItem>
                    <SelectItem value="fulltext">{t('search.maintenance.index.fulltext')}</SelectItem>
                    <SelectItem value="vector">{t('search.maintenance.index.vector')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <button
                type="button"
                data-testid="rebuild-btn"
                disabled={confirmOpen || rebuildPhase.phase === 'running'}
                className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-60"
                onClick={() => setConfirmOpen(true)}
              >
                {t('search.maintenance.rebuild')}
              </button>
            </div>

            {rebuildPhase.phase === 'running' && (
              <div
                data-testid="rebuild-loading"
                className="mt-5 flex items-center gap-3 rounded-lg border border-line bg-surface-2 px-4 py-3 text-[13px] text-ink-2"
              >
                <Loader2 className="h-4 w-4 animate-spin shrink-0" aria-hidden="true" />
                <span>{rebuildStatusText(rebuildPhase.status)}</span>
              </div>
            )}

            {rebuildPhase.phase === 'done' && (
              <div
                data-testid="rebuild-ok-toast"
                className="mt-5 rounded-lg border border-ok/40 bg-ok/10 px-4 py-3 text-[13px] text-ok"
              >
                {t('search.maintenance.done')} · {rebuildPhase.rebuiltAt} ·{' '}
                {t('search.maintenance.projects', { n: rebuildPhase.projectCount })}
              </div>
            )}

            {rebuildPhase.phase === 'error' && (
              <div
                data-testid="rebuild-err-toast"
                className="mt-5 rounded-lg border border-err/40 bg-err/10 px-4 py-3 text-[13px] text-err"
              >
                {t('search.maintenance.fail')}：{rebuildPhase.message}
              </div>
            )}
          </section>

          <ConfirmDialog
            open={confirmOpen}
            title={t('search.maintenance.confirm.title')}
            message={t('search.maintenance.confirm.body')}
            confirmText={t('search.maintenance.confirm.ok')}
            testidPrefix="rebuild-confirm"
            onConfirm={() => void handleConfirmRebuild()}
            onOpenChange={setConfirmOpen}
          />

          {loading && (
            <div
              data-testid="search-loading"
              className="mt-8 rounded-lg border border-line bg-surface px-4 py-6 text-center text-[13px] text-ink-2"
            >
              {t('search.loading')}
            </div>
          )}

          {error && (
            <div
              data-testid="search-error"
              className="mt-8 rounded-lg border border-line bg-surface px-4 py-6 text-center text-[13px] text-ink-2"
            >
              {t('search.error')}：{error}
            </div>
          )}

          {result &&
            !loading &&
            (result.hits.length > 0 ? (
              <div data-testid="search-results" className="mt-8">
                <p className="text-[13px] text-ink-2">{t('search.results', { total: result.total })}</p>
                <ul className="mt-3 space-y-3">
                  {result.hits.map((hit) => (
                    <li
                      key={hit.entity_id}
                      data-testid="search-hit"
                      onClick={() => handleHitClick(hit.entity_type, hit.entity_id)}
                      aria-label={'跳转到' + hit.title}
                      className="cursor-pointer rounded-lg border border-line bg-surface p-4 hover:bg-surface-3"
                    >
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-2">
                          {ENTITY_TYPE_LABEL[hit.entity_type] ?? hit.entity_type}
                        </span>
                        <span className="ml-auto text-[12px] text-ink-3">{hit.score}</span>
                      </div>
                      <h3 className="mt-2 font-serif text-[15px] font-semibold text-ink">{hit.title}</h3>
                      <p className="mt-1 text-[13px] text-ink-2">{hit.snippet}</p>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div
                data-testid="search-empty"
                className="mt-8 flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-14 text-center"
              >
                <p className="font-serif text-[15px] font-semibold text-ink">{t('search.empty')}</p>
              </div>
            ))}
        </>
      )}
    </div>
  );
}
