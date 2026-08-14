/** 项目卡片（spec §4.2.2 + F43 §5.5）：书名/题材/目标字数/章节进度/相对更新时间/进度条/写作中标记 + 卡片菜单 */
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { MoreHorizontal } from 'lucide-react';
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
  /** F43：卡片菜单「重命名」→ 父级打开重命名对话框（可选，缺省 = 纯展示） */
  onRename?: (project: Project) => void;
  /** F43：卡片菜单「删除」→ 父级打开删除确认框（可选，缺省 = 纯展示） */
  onDelete?: (project: Project) => void;
  /** #351：卡片菜单「修改」→ 父级 selectProject + 跳设置页（可省略，默认 = 纯展示） */
  onEdit?: (project: Project) => void;
}

export function ProjectCard({ project, progress, isCurrent, onClick, onRename, onDelete, onEdit }: ProjectCardProps) {
  const { t } = useI18n();
  // F43：菜单打开状态为组件本地 state（点击菜单项后关闭）
  const [menuOpen, setMenuOpen] = useState(false);
  // 点击外部关闭（可选增强）：容器 ref 判定点击源，避免与打开菜单的点击事件竞态
  const menuContainerRef = useRef<HTMLDivElement>(null);
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

  useEffect(() => {
    if (!menuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (menuContainerRef.current && !menuContainerRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('click', onDocClick);
    return () => document.removeEventListener('click', onDocClick);
  }, [menuOpen]);

  const handleMenuKeyDown = (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    // stopPropagation 防触发卡片级 Enter/Space 跳转（#232）
    e.stopPropagation();
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setMenuOpen(true);
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
          className="absolute right-12 top-3 rounded bg-accent px-2 py-0.5 text-[11px] text-accent-ink"
        >
          {t('pj.writing')}
        </span>
      )}
      {/* F43 §5.5：卡片菜单按钮（右上角；stopPropagation 防卡片跳转；role=button + Enter/Space 可达） */}
      <div ref={menuContainerRef} className="absolute right-3 top-3">
        <button
          type="button"
          role="button"
          tabIndex={0}
          data-testid={`project-card-menu-${project.id}`}
          aria-label={`${t('pj.rename')} / ${t('pj.delete')}`}
          className="rounded p-1 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={(e) => {
            e.stopPropagation();
            setMenuOpen((v) => !v);
          }}
          onKeyDown={handleMenuKeyDown}
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
        </button>
        {menuOpen && (
          <div
            data-testid={`project-menu-${project.id}`}
            className="absolute right-0 top-7 z-20 w-28 rounded-md border border-line bg-surface p-1 shadow-card"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              data-testid={`project-edit-${project.id}`}
              className="flex w-full items-center rounded-md px-2.5 py-1.5 text-left text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={(e) => {
                e.stopPropagation();
                setMenuOpen(false);
                onEdit?.(project);
              }}
            >
              {t('pj.edit')}
            </button>
            <button
              type="button"
              data-testid={`project-rename-${project.id}`}
              className="flex w-full items-center rounded-md px-2.5 py-1.5 text-left text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={(e) => {
                e.stopPropagation();
                setMenuOpen(false);
                onRename?.(project);
              }}
            >
              {t('pj.rename')}
            </button>
            <button
              type="button"
              data-testid={`project-delete-${project.id}`}
              className="flex w-full items-center rounded-md px-2.5 py-1.5 text-left text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={(e) => {
                e.stopPropagation();
                setMenuOpen(false);
                onDelete?.(project);
              }}
            >
              {t('pj.delete')}
            </button>
          </div>
        )}
      </div>
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
