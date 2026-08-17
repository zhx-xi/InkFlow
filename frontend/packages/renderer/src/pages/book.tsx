/** 书级编排页（F44 阶段1）：项目选择后进入 BookPlannerPanel 单面板访谈 */
import { useNavigate } from 'react-router-dom';
import { BookPlannerPanel } from '../components/BookPlannerPanel';
import { useI18n } from '../i18n/useI18n';
import { useProjectStore } from '../stores/project';

export function BookPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const projects = useProjectStore((s) => s.projects);

  const currentProject = projects.find((p) => p.id === currentProjectId) ?? projects[0];
  const effectiveProjectId = currentProjectId ?? currentProject?.id ?? '';

  if (effectiveProjectId === '') {
    return (
      <div data-testid="book-page" className="flex h-full items-center justify-center">
        <div data-testid="book-page-empty" className="text-center">
          <p className="text-[15px] text-ink-2">{t('book.empty.title')}</p>
          <button
            type="button"
            data-testid="book-page-go-projects"
            className="mt-5 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink hover:bg-accent-hover"
            onClick={() => navigate('/projects')}
          >
            {t('book.empty.goProjects')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="book-page" className="mx-auto flex h-full max-w-2xl flex-col gap-3 p-4">
      <h2 data-testid="book-project" className="text-[15px] font-medium text-ink">
        {currentProject?.name ?? ''}
      </h2>
      <BookPlannerPanel projectId={effectiveProjectId} />
    </div>
  );
}
