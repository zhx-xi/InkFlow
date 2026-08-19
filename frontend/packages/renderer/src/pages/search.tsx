/** #480 检索页（Issue #480 RAG embedding 增强检索）：消费既有端点 GET /api/v1/search，纯前端零后端改动 */
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search } from 'lucide-react';
import { fetchSearch, type SearchResponseDto } from '../api/search';
import { errorMessage } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useI18n } from '../i18n/useI18n';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';

type SearchMode = 'keyword' | 'semantic';

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
                      className="rounded-lg border border-line bg-surface p-4"
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
