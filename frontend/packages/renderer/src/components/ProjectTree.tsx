/** 项目树（spec §4.2.1）：卷/章 + 字数 + 当前章高亮 + 底部新建章节 */
import { useState } from 'react';
import { Check, X } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';
import type { ChapterMeta } from '../stores/chapter';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
import { ProjectSeal } from './ProjectSeal';

export function ProjectTree() {
  const { t } = useI18n();
  const volumes = useChapterStore((s) => s.volumes);
  const chapters = useChapterStore((s) => s.chapters);
  const currentChapterId = useChapterStore((s) => s.currentChapterId);
  const selectChapter = useChapterStore((s) => s.selectChapter);
  const createChapter = useChapterStore((s) => s.createChapter);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const projects = useProjectStore((s) => s.projects);
  const currentProject = projects.find((p) => p.id === currentProjectId) ?? projects[0];
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState('');

  const renderChapter = (ch: ChapterMeta) => {
    const isCurrent = ch.id === currentChapterId;
    return (
      <button
        key={ch.id}
        type="button"
        // 契约断言 getByTestId('tree-chapter') 唯一且为当前章（data-current 标记）
        data-testid={isCurrent ? 'tree-chapter' : undefined}
        data-current={isCurrent ? 'true' : undefined}
        onClick={() => void selectChapter(ch.id)}
        className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-[13px] ${
          isCurrent ? 'bg-accent-weak text-ink' : 'text-ink-2 hover:bg-surface-3'
        }`}
      >
        <span className="truncate">{ch.title}</span>
        <span className="shrink-0 text-[11px] text-ink-3">{ch.word_count.toLocaleString()}</span>
      </button>
    );
  };

  const ungrouped = chapters.filter((c) => c.volume_id === null);

  const handleCreate = async () => {
    if (!currentProjectId) return;
    await createChapter(currentProjectId, newTitle.trim() || '新章节');
    setNewTitle('');
    setCreating(false);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ProjectSeal project={currentProject} />
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {volumes.map((v) => (
          <div key={v.id} data-testid="tree-volume" className="mb-2">
            <div className="px-2 py-1 text-[12px] font-semibold text-ink-3">{v.title}</div>
            <div className="space-y-0.5">
              {chapters
                .filter((c) => c.volume_id === v.id)
                .map(renderChapter)}
            </div>
          </div>
        ))}
        {ungrouped.length > 0 && <div className="space-y-0.5">{ungrouped.map(renderChapter)}</div>}
      </div>
      <div className="border-t border-line p-2">
        {creating ? (
          <div className="flex gap-1">
            <input
              autoFocus
              className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-1 text-[13px] outline-none"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleCreate();
                if (e.key === 'Escape') {
                  setCreating(false);
                  setNewTitle('');
                }
              }}
              placeholder={t('write.newChapter')}
            />
            <button
              type="button"
              aria-label={t('write.newChapter')}
              className="rounded p-1.5 text-ok transition duration-180 hover:bg-surface-3 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              onClick={() => void handleCreate()}
            >
              <Check className="h-4 w-4" aria-hidden="true" />
            </button>
            <button
              type="button"
              aria-label={t('dlg.cancel')}
              className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-ink active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              onClick={() => {
                setCreating(false);
                setNewTitle('');
              }}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="w-full rounded px-2 py-1.5 text-[13px] text-ink-2 hover:bg-surface-3"
            onClick={() => setCreating(true)}
          >
            + {t('write.newChapter')}
          </button>
        )}
      </div>
    </div>
  );
}
