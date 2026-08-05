/** 项目页（spec §4.2.2）：卡片网格 + 新建对话框，双入口 + 创建后跳转写作页 */
import { useEffect, useState } from 'react';
import { BookOpen } from 'lucide-react';
import { NewProjectDialog } from '../components/NewProjectDialog';
import { ProjectCard } from '../components/ProjectCard';
import { useI18n } from '../i18n/useI18n';
import { useProjectStore } from '../stores/project';

export function ProjectsPage() {
  const { t } = useI18n();
  const projects = useProjectStore((s) => s.projects);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const loading = useProjectStore((s) => s.loading);
  const error = useProjectStore((s) => s.error);
  const chapterProgress = useProjectStore((s) => s.chapterProgress);
  const loadProjects = useProjectStore((s) => s.loadProjects);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    void loadProjects();
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
          className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink"
          onClick={() => setDialogOpen(true)}
        >
          {t('pj.new')}
        </button>
      </div>
      {error ? (
        <div className="rounded-lg border border-err/30 bg-surface p-6 text-sm text-err">{error}</div>
      ) : loading && projects.length === 0 ? (
        <div className="text-sm text-ink-3">{t('common.loading')}</div>
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
            className="mt-5 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink"
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
            />
          ))}
          <button
            type="button"
            data-testid="new-project-card"
            className="flex min-h-[168px] items-center justify-center rounded-lg border-2 border-dashed border-line text-[13px] text-ink-3 transition-colors hover:border-accent hover:text-accent"
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
