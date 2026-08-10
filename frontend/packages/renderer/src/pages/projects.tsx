/** 项目页（spec §4.2.2）：卡片网格 + 新建对话框，双入口 + 创建后跳转写作页 */
import { useEffect, useState } from 'react';
import { BookOpen } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { NewProjectDialog } from '../components/NewProjectDialog';
import { ProjectCard } from '../components/ProjectCard';
import { Skeleton } from '../components/ui/skeleton';
import { useI18n } from '../i18n/useI18n';
import { useProjectStore } from '../stores/project';
import { ensureApiReady } from '../api/client';

export function ProjectsPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const projects = useProjectStore((s) => s.projects);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const loading = useProjectStore((s) => s.loading);
  const error = useProjectStore((s) => s.error);
  const chapterProgress = useProjectStore((s) => s.chapterProgress);
  const loadProjects = useProjectStore((s) => s.loadProjects);
  const selectProject = useProjectStore((s) => s.selectProject);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    // #98 修复：Electron 下等待 preload 注入 INKFLOW_API（'inkflow:api-ready'）后再发首请求，
    // 避免「React 挂载早于注入 → 首请求无 token → 401」时序竞态；非 Electron 立即通过。
    void (async () => {
      await ensureApiReady();
      void loadProjects();
    })();
  }, [loadProjects]);

  return (
    <div className="mx-auto max-w-[1080px] px-12 py-10">
      <div className="mb-7 flex items-baseline justify-between">
        <div>
          <h1 className="font-serif text-[26px] font-semibold">{t('pj.title')}</h1>
          <p className="mt-0.5 text-[13px] text-ink-3">{t('pj.sub')}</p>
        </div>
        <button
          type="button"
          data-testid="new-project-btn"
          className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          onClick={() => setDialogOpen(true)}
        >
          {t('pj.new')}
        </button>
      </div>
      {error ? (
        <div className="rounded-lg border border-err/30 bg-surface p-6 text-sm text-err">{error}</div>
      ) : loading && projects.length === 0 ? (
        <div
          role="status"
          aria-label={t('common.loading')}
          className="grid grid-cols-3 gap-5"
        >
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="rounded-lg border border-line bg-surface p-5 shadow-card">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="mt-3 h-3 w-16" />
              <Skeleton className="mt-2 h-3 w-20" />
              <Skeleton className="mt-5 h-2 w-full" />
              <div className="mt-4 flex items-center justify-between">
                <Skeleton className="h-6 w-16" />
                <Skeleton className="h-6 w-10" />
              </div>
            </div>
          ))}
        </div>
      ) : projects.length === 0 ? (
        <div
          data-testid="projects-empty"
          className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-16 text-center"
        >
          <BookOpen className="h-10 w-10 text-ink-3" aria-hidden="true" />
          <p className="mt-3 font-serif text-[17px] font-semibold text-ink">{t('pj.empty.title')}</p>
          <p className="mt-1 text-[13px] text-ink-3">{t('pj.empty.sub')}</p>
          <button
            type="button"
            className="mt-5 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={() => setDialogOpen(true)}
          >
            {t('pj.new')}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-5">
          {projects.map((p) => (
            <ProjectCard
              key={p.id}
              project={p}
              progress={chapterProgress[p.id]}
              isCurrent={currentProjectId === p.id}
              onClick={() => {
                selectProject(p.id);
                navigate('/writing');
              }}
            />
          ))}
          <button
            type="button"
            data-testid="new-project-card"
            className="flex min-h-[168px] items-center justify-center rounded-lg border-2 border-dashed border-line text-[13px] text-ink-3 transition duration-180 hover:border-accent hover:text-accent active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={() => setDialogOpen(true)}
          >
            + {t('pj.newCard')}
          </button>
        </div>
      )}
      {dialogOpen && <NewProjectDialog onClose={() => setDialogOpen(false)} />}
    </div>
  );
}
