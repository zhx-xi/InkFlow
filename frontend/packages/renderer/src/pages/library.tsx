/** 设定库页（spec §7.3：项目上下文 + 面包屑 + 六分类 tab + 空态引导） */
import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Library } from 'lucide-react';
import { apiFetch, ensureApiReady, errorMessage } from '../api/client';
import { LibraryCreateDialog } from '../components/LibraryCreateDialog';
import { Skeleton } from '../components/ui/skeleton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { useI18n } from '../i18n/useI18n';
import { useProjectStore } from '../stores/project';
import { useToastStore } from '../stores/toast';
import { cn } from '../lib/cn';

type CatKey = 'characters' | 'world' | 'outline' | 'timeline' | 'foreshadow' | 'rag';

interface ListItem {
  id: string | number;
  name?: string;
  title?: string;
}

interface ListResponse {
  items: ListItem[];
  total: number;
  offset: number;
  limit: number;
}

/** timeline 契约特例：GET /timeline 返回 TimelineView {event_timeline:[...]}，其余分类统一 {items:[...]} */
type TimelineResponsePath = 'event_timeline';

type CatResponse = ListResponse & { event_timeline?: ListItem[] };

const CATS: Array<{
  key: CatKey;
  labelKey: string;
  endpoint: (projectId: string) => string;
  responsePath?: TimelineResponsePath;
}> = [
  { key: 'characters', labelKey: 'nav.lib.characters', endpoint: (id) => `/api/v1/projects/${id}/characters` },
  { key: 'world', labelKey: 'nav.lib.world', endpoint: (id) => `/api/v1/projects/${id}/world-settings` },
  { key: 'outline', labelKey: 'nav.lib.outline', endpoint: (id) => `/api/v1/projects/${id}/outlines` },
  {
    key: 'timeline',
    labelKey: 'nav.lib.timeline',
    endpoint: (id) => `/api/v1/projects/${id}/timeline`,
    responsePath: 'event_timeline',
  },
  { key: 'foreshadow', labelKey: 'nav.lib.foreshadow', endpoint: (id) => `/api/v1/projects/${id}/foreshadowings` },
  { key: 'rag', labelKey: 'nav.lib.rag', endpoint: (id) => `/api/v1/projects/${id}/extractions/runs` },
];

const CAT_KEYS = CATS.map((c) => c.key);

function isCatKey(v: string | null): v is CatKey {
  return v !== null && (CAT_KEYS as string[]).includes(v);
}

export function LibraryPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const projects = useProjectStore((s) => s.projects);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const loadProjects = useProjectStore((s) => s.loadProjects);
  const selectProject = useProjectStore((s) => s.selectProject);

  // URL cat 查询参数作为初始 tab（侧边导航 /library?cat=<key> 直达联动）
  const catParam = searchParams.get('cat');
  const [activeCat, setActiveCat] = useState<CatKey>(() =>
    isCatKey(catParam) ? catParam : 'characters',
  );
  const [items, setItems] = useState<ListResponse['items']>([]);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  // #196：分类实体手动创建对话框开关（仅非 RAG 分类空态 CTA 打开）
  const [createOpen, setCreateOpen] = useState(false);

  const cat = CATS.find((c) => c.key === activeCat) ?? CATS[0];
  // rag 无创建端点（CTA 已走跳转分支），对话框仅在五个可创建分类下渲染
  const createCat = activeCat === 'rag' ? null : activeCat;
  const currentProject = projects.find((p) => p.id === currentProjectId) ?? null;

  // 挂载加载项目列表（Electron 下等待 preload 注入，与项目页同源防 401 竞态）
  useEffect(() => {
    void (async () => {
      await ensureApiReady();
      void loadProjects();
    })();
  }, [loadProjects]);

  // URL cat 变化（AppNav 直达）→ 同步激活 tab
  useEffect(() => {
    const p = searchParams.get('cat');
    if (isCatKey(p) && p !== activeCat) setActiveCat(p);
  }, [searchParams, activeCat]);

  // 当前项目 + 激活分类 → 拉取分类端点（统一响应 {items,...}；timeline 特例 {event_timeline:[...]}；
  // #105 修复批：依赖 activeCat 字符串而非 cat 对象；失败 → error 态（library-retry 可重试））
  useEffect(() => {
    if (!currentProjectId) {
      setItems([]);
      setLoading(false);
      setLoadFailed(false);
      return;
    }
    const current = CATS.find((c) => c.key === activeCat) ?? CATS[0];
    let cancelled = false;
    setLoading(true);
    setLoadFailed(false);
    void apiFetch<CatResponse>(current.endpoint(currentProjectId))
      .then((data) => {
        if (cancelled) return;
        const list = current.responsePath ? (data[current.responsePath] ?? []) : data.items;
        setItems(list);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        setLoading(false);
        setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, activeCat, reloadKey]);

  const handleTabChange = (key: CatKey) => {
    setActiveCat(key);
    setSearchParams({ cat: key });
  };

  const handleProjectChange = (id: string) => {
    selectProject(id);
  };

  // #196：POST 到当前分类创建端点 → 关闭对话框 + 复用 reloadKey 机制实时刷新列表
  const handleCreate = async (input: Record<string, unknown>) => {
    if (!currentProjectId) return;
    const current = CATS.find((c) => c.key === activeCat) ?? CATS[0];
    // rag 不适用（无创建端点；CTA 已走跳转分支，此处防御性早退）
    if (current.key === 'rag') return;
    try {
      // 关键：timeline 分类的创建端点是 /timeline/events（不是 /timeline 列表端点）
      const createEndpoint =
        current.key === 'timeline'
          ? `/api/v1/projects/${currentProjectId}/timeline/events`
          : current.endpoint(currentProjectId);
      await apiFetch(createEndpoint, { method: 'POST', body: input });
      setCreateOpen(false);
      setReloadKey((k) => k + 1); // 列表实时刷新（复用既有 reloadKey 机制）
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  return (
    <div data-testid="library-page" className="mx-auto max-w-[1080px] px-12 py-10">
      <h1 className="font-serif text-[26px] font-semibold">{t('lib.title')}</h1>

      {/* 项目上下文：选择器 + 面包屑（入口语义 = 当前项目的设定库） */}
      <div className="mt-5 flex flex-wrap items-center gap-4">
        <Select value={currentProjectId ?? undefined} onValueChange={handleProjectChange}>
          <SelectTrigger data-testid="library-project-select" aria-label={t('lib.projectSelect')} className="w-56">
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
        <div data-testid="library-breadcrumb" className="text-[13px] text-ink-2">
          {t('lib.title')}
          {currentProject ? ` · ${currentProject.name}` : ''} <span className="mx-1 text-ink-3">/</span>
          <span className="text-ink">{t(cat.labelKey)}</span>
        </div>
      </div>

      {currentProjectId === null ? (
        <div
          data-testid="library-empty"
          className="mt-8 flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-16 text-center"
        >
          <Library className="h-10 w-10 text-ink-3" aria-hidden="true" />
          <p className="mt-3 font-serif text-[17px] font-semibold text-ink">{t('lib.empty.noProject')}</p>
          <button
            type="button"
            data-testid="library-go-projects"
            className="mt-5 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={() => navigate('/projects')}
          >
            {t('lib.empty.goProjects')}
          </button>
        </div>
      ) : (
        <>
          {/* 六分类 tab（角色/世界观/大纲/时间线/伏笔/知识库 RAG） */}
          <div
            data-testid="library-tabs"
            role="tablist"
            aria-label={t('lib.title')}
            className="mt-6 flex flex-wrap gap-1 border-b border-line"
          >
            {CATS.map((c) => (
              <button
                key={c.key}
                type="button"
                role="tab"
                aria-selected={c.key === activeCat}
                className={cn(
                  'rounded-t-md border-b-2 px-3.5 py-2 text-[13px] transition-colors duration-180 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  c.key === activeCat
                    ? 'border-accent font-medium text-accent'
                    : 'border-transparent text-ink-2 hover:text-ink',
                )}
                onClick={() => handleTabChange(c.key)}
              >
                {t(c.labelKey)}
              </button>
            ))}
          </div>

          <div className="mt-5">
            {loading ? (
              <div data-testid="library-list" className="space-y-2">
                <Skeleton className="h-11 w-full" />
                <Skeleton className="h-11 w-full" />
                <Skeleton className="h-11 w-full" />
              </div>
            ) : loadFailed ? (
              <div
                data-testid="library-error"
                className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-14 text-center"
              >
                <p className="text-[13px] text-ink-2">{t('lib.loadFailed')}</p>
                <button
                  type="button"
                  data-testid="library-retry"
                  className="mt-4 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  onClick={() => setReloadKey((k) => k + 1)}
                >
                  {t('lib.retry')}
                </button>
              </div>
            ) : items.length === 0 ? (
              <div
                data-testid="library-tab-empty"
                className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-14 text-center"
              >
                <p className="text-[13px] text-ink-2">{t('lib.empty.tab', { name: t(cat.labelKey) })}</p>
                <button
                  type="button"
                  data-testid="library-tab-empty-cta"
                  className="mt-4 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  onClick={() => (cat.key === 'rag' ? navigate('/writing') : setCreateOpen(true))}
                >
                  {t('lib.empty.create')}
                </button>
              </div>
            ) : (
              <ul
                data-testid="library-list"
                className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface shadow-card"
              >
                {items.map((item) => (
                  <li key={String(item.id)} className="flex items-center gap-3 px-4 py-2.5 text-[13px] text-ink">
                    {item.title ?? item.name ?? ''}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      {/* #196：分类实体手动创建对话框（挂在页面根部，open 受控；RAG 分类不渲染） */}
      {createCat !== null && (
        <LibraryCreateDialog
          open={createOpen}
          cat={createCat}
          onCreate={handleCreate}
          onOpenChange={setCreateOpen}
        />
      )}
    </div>
  );
}
