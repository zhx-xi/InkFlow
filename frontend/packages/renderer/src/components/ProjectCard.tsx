/** 项目卡片（spec §4.2.2）：书名/题材/目标字数/章节进度/相对更新时间/进度条/写作中标记 */
import { type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useI18n } from '../i18n/useI18n';
import type { ChapterProgress, Project } from '../stores/project';

type T = (key: string, params?: Record<string, string | number>) => string;

/** 相对时间：刚刚 / n 分钟前 / n 小时前 / n 天前 / n 周前（随语言格式化） */
function relativeTime(iso: string, t: T): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return t('pj.time.justNow');
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return t('pj.time.minutes', { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('pj.time.hours', { n: hours });
  const days = Math.floor(hours / 24);
  if (days < 7) return t('pj.time.days', { n: days });
  return t('pj.time.weeks', { n: Math.floor(days / 7) });
}

export interface ProjectCardProps {
  project: Project;
  progress?: ChapterProgress;
  isCurrent: boolean;
  /** #232：卡片可点击（ProjectsPage 传入 → selectProject + navigate('/writing')）；缺省 = 纯展示 */
  onClick?: () => void;
}

export function ProjectCard({ project, progress, isCurrent, onClick }: ProjectCardProps) {
  const { t } = useI18n();
  const written = progress?.written ?? 0;
  const total = progress?.total ?? 0;
  const pct = total > 0 ? Math.round((written / total) * 100) : 0;
  const progressLabel = t('pj.chapterProgress', { n: written, m: total });

  const handleKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onClick?.();
    }
  };

  return (
    <div
      data-testid="project-card"
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onClick ? handleKeyDown : undefined}
      className={`relative rounded-lg border bg-surface p-6 shadow-card transition duration-180 hover:shadow-card-hover ${
        isCurrent ? 'border-accent' : 'border-line'
      }${onClick ? ' cursor-pointer' : ''}`}
    >
      {isCurrent && (
        <span
          data-testid="writing-badge"
          className="absolute right-3 top-3 rounded bg-accent px-2 py-0.5 text-[11px] text-accent-ink"
        >
          {t('pj.writing')}
        </span>
      )}
      <h3 className="font-serif text-[18px] font-semibold">{project.name}</h3>
      <div className="mt-3 space-y-1 text-[13px] text-ink-2">
        <div>{project.genre}</div>
        <div>{project.target_words.toLocaleString('zh-CN')}</div>
        <div>{progressLabel}</div>
        <div className="text-ink-3">{relativeTime(project.updated_at, t)}</div>
      </div>
      <div
        role="progressbar"
        aria-label={progressLabel}
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className="mt-4 h-1.5 overflow-hidden rounded-full bg-surface-3"
      >
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
