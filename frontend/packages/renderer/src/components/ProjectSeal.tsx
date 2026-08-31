/** 项目印章（spec §4.2.1）：所有主题常驻，颜色跟随 accent，文字取书名关键字（暂按首字） */
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../i18n/useI18n';
import { useChapterStore } from '../stores/chapter';
import type { Project } from '../stores/project';

export interface ProjectSealProps {
  project?: Project;
}

export function ProjectSeal({ project }: ProjectSealProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  if (!project) return null;
  const glyph = Array.from(project.name)[0] ?? '';
  return (
    <div
      className="flex cursor-pointer items-center gap-2.5 px-4 py-3"
      onClick={() => {
        // #841 5a：清除当前章节 → 全局 chat 视图
        useChapterStore.getState().setCurrentChapter(null);
        navigate('/writing');
      }}
    >
      <span
        data-testid="project-seal"
        aria-label={project.name}
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 font-serif text-[18px]"
        style={{ color: 'var(--accent)', borderColor: 'var(--accent)' }}
      >
        {glyph}
      </span>
      <div className="min-w-0">
        <div className="truncate text-[13px] font-semibold">{project.name}</div>
        <div className="text-[11px] text-ink-3">{t('nav.writing')}</div>
      </div>
    </div>
  );
}
