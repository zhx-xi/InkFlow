/** 项目树（spec §4.2.1）：卷/章 + 字数 + 当前章高亮 + 底部新建章节（#648 卷管理：新建卷/编辑标题/删除卷） */
import { useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { Check, Pencil, Trash2, X } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';
import type { ChapterMeta, DraftTreeNode, Volume } from '../stores/chapter';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
import { ConfirmDialog } from './ConfirmDialog';
import { ProjectSeal } from './ProjectSeal';
import { VolumeDeleteDialog } from './VolumeDeleteDialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

/** #702：左栏宽度拖拽边界（最小 160 / 最大 360） */
export const RESIZE_MIN = 160;
export const RESIZE_MAX = 360;

export interface ProjectTreeProps {
  /** 左栏宽度（px），由写作页受控持有 */
  width?: number;
  /** 拖拽调宽回调（仅传入时生效） */
  onResizeWidth?: (w: number) => void;
}

export function ProjectTree({ width = 208, onResizeWidth }: ProjectTreeProps) {
  const { t } = useI18n();
  const volumes = useChapterStore((s) => s.volumes);
  const chapters = useChapterStore((s) => s.chapters);
  const currentChapterId = useChapterStore((s) => s.currentChapterId);
  const selectChapter = useChapterStore((s) => s.selectChapter);
  const createChapter = useChapterStore((s) => s.createChapter);
  // #976 草稿常显：树轨草稿 + 审批弹层入口（双击 → store 全局态，写作页消费）
  const pendingDrafts = useChapterStore((s) => s.pendingDrafts);
  const requestApproval = useChapterStore((s) => s.requestApproval);
  const createVolume = useChapterStore((s) => s.createVolume);
  const patchVolume = useChapterStore((s) => s.patchVolume);
  const deleteVolume = useChapterStore((s) => s.deleteVolume);
  const moveChapter = useChapterStore((s) => s.moveChapter);
  const patchChapter = useChapterStore((s) => s.patchChapter);
  const deleteChapter = useChapterStore((s) => s.deleteChapter);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const projects = useProjectStore((s) => s.projects);
  const currentProject = projects.find((p) => p.id === currentProjectId) ?? projects[0];
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [creatingVolume, setCreatingVolume] = useState(false);
  const [newVolumeTitle, setNewVolumeTitle] = useState('');
  const [editingVolumeId, setEditingVolumeId] = useState<string | null>(null);
  const [editVolumeTitle, setEditVolumeTitle] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<Volume | null>(null);
  const [editingChapterId, setEditingChapterId] = useState<string | null>(null);
  const [editChapterTitle, setEditChapterTitle] = useState('');
  const [deleteChapterTarget, setDeleteChapterTarget] = useState<ChapterMeta | null>(null);
  const [newVolumeId, setNewVolumeId] = useState<string | null>(null); // 新建章节目标卷（null=未分组）
  const [dragOverVolumeId, setDragOverVolumeId] = useState<string | null>(null); // 拖拽经过的卷高亮
  // #702：col-resize 拖拽起点（clientX + 起点宽度），mouseup 清空
  const dragStartRef = useRef<{ startX: number; startW: number } | null>(null);

  const startResize = (e: ReactMouseEvent) => {
    e.preventDefault();
    dragStartRef.current = { startX: e.clientX, startW: width };
    const onMove = (ev: MouseEvent) => {
      const drag = dragStartRef.current;
      if (!drag) return;
      const newW = Math.max(RESIZE_MIN, Math.min(RESIZE_MAX, drag.startW + (ev.clientX - drag.startX)));
      onResizeWidth?.(newW);
    };
    const onUp = () => {
      dragStartRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  const renderDraft = (d: DraftTreeNode) => (
    <div
      key={d.id}
      data-testid={`draft-${d.draftId}`}
      title={t('write.drafts.openApprove')}
      className="flex w-full cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-surface-3"
      onDoubleClick={() => requestApproval(d.draftId)}
    >
      <span className="min-w-0 flex-1 truncate text-left text-[12px] text-ink-2" title={d.summary}>
        {d.summary}
      </span>
      <span
        data-testid={`draft-badge-${d.draftId}`}
        className="shrink-0 rounded border border-accent/30 bg-accent-weak px-1.5 py-0.5 text-[10px] text-accent"
      >
        {t('write.drafts.pendingBadge')}
      </span>
    </div>
  );

  const renderChapter = (ch: ChapterMeta) => {
    const isCurrent = ch.id === currentChapterId;
    const isEditing = editingChapterId === ch.id;
    return (
      <div
        key={ch.id}
        // 契约断言 getByTestId('tree-chapter') 唯一且为当前章（data-current 标记）
        data-testid={isCurrent ? 'tree-chapter' : undefined}
        data-current={isCurrent ? 'true' : undefined}
        className={`group flex w-full items-center gap-2 rounded px-2 py-1.5 ${isCurrent ? 'bg-accent-weak' : ''}`}
      >
        {isEditing ? (
          <input
            autoFocus
            data-testid="chapter-edit-input"
            className="min-w-0 flex-1 rounded border border-line bg-surface px-1.5 py-0.5 text-[12px] text-ink outline-none"
            value={editChapterTitle}
            onChange={(e) => setEditChapterTitle(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void handlePatchChapter(ch);
              if (e.key === 'Escape') {
                setEditingChapterId(null);
                setEditChapterTitle('');
              }
            }}
          />
        ) : (
          // #980-2a D11：长标题悬浮 title 兜底（truncate 裁切后仍可读全文）
          <button
            type="button"
            draggable
            onDragStart={(e) => {
              e.dataTransfer?.setData('text/plain', ch.id);
              e.dataTransfer!.effectAllowed = 'move';
            }}
            onClick={() => void selectChapter(ch.id)}
            className={`min-w-0 flex-1 truncate text-left ${isCurrent ? 'text-ink' : 'text-ink-2'}`}
            title={ch.title}
          >
            <span className="truncate">{ch.title}</span>
          </button>
        )}
        {/* #980-2a D11：字数 ml-auto 置右（非 shrink-0），hover 操作钮出现时 -mr-14 让位 */}
        <span className="ml-auto text-[11px] text-ink-3 transition-all group-hover:-mr-14">
          {ch.word_count.toLocaleString()}
        </span>
        {!isEditing && (
          <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
            <button
              type="button"
              data-testid={`chapter-edit-${ch.id}`}
              aria-label="编辑章节"
              className="rounded p-1 text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={(e) => {
                e.stopPropagation();
                setEditingChapterId(ch.id);
                setEditChapterTitle(ch.title);
              }}
            >
              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
            <button
              type="button"
              data-testid={`chapter-delete-${ch.id}`}
              aria-label="删除章节"
              className="rounded p-1 text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={(e) => {
                e.stopPropagation();
                setDeleteChapterTarget(ch);
              }}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        )}
      </div>
    );
  };

  const ungrouped = chapters.filter((c) => c.volume_id === null);
  const ungroupedDrafts = pendingDrafts.filter((d) => d.volume_id === null);

  const handleCreate = async () => {
    if (!currentProjectId) return;
    const title = newTitle.trim() || '新章节';
    if (newVolumeId) {
      await createChapter(currentProjectId, title, newVolumeId);
    } else {
      await createChapter(currentProjectId, title);
    }
    setNewTitle('');
    setNewVolumeId(null);
    setCreating(false);
  };

  const handleCreateVolume = async () => {
    if (!currentProjectId) return;
    await createVolume(currentProjectId, newVolumeTitle.trim() || '新卷');
    setNewVolumeTitle('');
    setCreatingVolume(false);
  };

  const handlePatchVolume = async (v: Volume) => {
    const title = editVolumeTitle.trim();
    setEditingVolumeId(null);
    setEditVolumeTitle('');
    if (title === '' || title === v.title) return;
    await patchVolume(v.id, title);
  };

  const handlePatchChapter = async (ch: ChapterMeta) => {
    const title = editChapterTitle.trim();
    setEditingChapterId(null);
    setEditChapterTitle('');
    if (title === '' || title === ch.title) return;
    await patchChapter(ch.id, title);
  };

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <ProjectSeal project={currentProject} />
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {volumes.map((v) => (
          <div
            key={v.id}
            data-testid="tree-volume"
            className={`group mb-2 ${dragOverVolumeId === v.id ? 'rounded bg-surface-3 ring-1 ring-accent' : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOverVolumeId(v.id);
            }}
            onDragLeave={() => setDragOverVolumeId((id) => (id === v.id ? null : id))}
            onDrop={(e) => {
              e.preventDefault();
              const cid = e.dataTransfer?.getData('text/plain');
              if (cid) void moveChapter(cid, v.id);
              setDragOverVolumeId(null);
            }}
          >
            <div className="vol-row flex items-center gap-1 px-2 py-1">
              {editingVolumeId === v.id ? (
                <input
                  autoFocus
                  className="min-w-0 flex-1 rounded border border-line bg-surface px-1.5 py-0.5 text-[12px] font-semibold text-ink outline-none"
                  value={editVolumeTitle}
                  onChange={(e) => setEditVolumeTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void handlePatchVolume(v);
                    if (e.key === 'Escape') {
                      setEditingVolumeId(null);
                      setEditVolumeTitle('');
                    }
                  }}
                />
              ) : (
                <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-ink-3">
                  {v.title}
                </span>
              )}
              <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
                <button
                  type="button"
                  aria-label="编辑卷标题"
                  data-testid="vol-edit"
                  className="rounded p-1 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  onClick={() => {
                    setEditingVolumeId(v.id);
                    setEditVolumeTitle(v.title);
                  }}
                >
                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  aria-label="删除卷"
                  data-testid="vol-del-btn"
                  className="rounded p-1 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  onClick={() => setDeleteTarget(v)}
                >
                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </div>
            </div>
            <div className="space-y-0.5">
              {chapters
                .filter((c) => c.volume_id === v.id)
                .map(renderChapter)}
              {/* #976：草稿节点渲染在卷容器内章之后 */}
              {pendingDrafts
                .filter((d) => d.volume_id === v.id)
                .map(renderDraft)}
            </div>
          </div>
        ))}
        <div
          data-testid="tree-ungrouped"
          onDragOver={(e) => {
            e.preventDefault();
          }}
          onDrop={(e) => {
            e.preventDefault();
            const cid = e.dataTransfer?.getData('text/plain');
            if (cid) void moveChapter(cid, null);
          }}
        >
          {(ungrouped.length > 0 || ungroupedDrafts.length > 0) && (
            <div className="space-y-0.5">
              {ungrouped.map(renderChapter)}
              {/* #976：无卷草稿渲染在 ungrouped 容器末尾 */}
              {ungroupedDrafts.map(renderDraft)}
            </div>
          )}
        </div>
      </div>
      <div data-testid="tree-actions" className="flex flex-col gap-2 border-t border-line p-2">
        {creatingVolume && (
          <div data-testid="tree-create-volume-row" className="flex items-center gap-1">
            <input
              autoFocus
              className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-1 text-[13px] outline-none"
              value={newVolumeTitle}
              onChange={(e) => setNewVolumeTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleCreateVolume();
                if (e.key === 'Escape') {
                  setCreatingVolume(false);
                  setNewVolumeTitle('');
                }
              }}
              placeholder="新建卷标题"
            />
            <button
              type="button"
              aria-label="创建卷"
              className="rounded p-1.5 text-ok transition duration-180 hover:bg-surface-3 active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              onClick={() => void handleCreateVolume()}
            >
              <Check className="h-4 w-4" aria-hidden="true" />
            </button>
            <button
              type="button"
              aria-label={t('dlg.cancel')}
              className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-ink active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              onClick={() => {
                setCreatingVolume(false);
                setNewVolumeTitle('');
              }}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        )}
        {creating && (
          <div data-testid="tree-create-chapter-row" className="flex items-center gap-1">
            <Select
              value={newVolumeId ?? '__ungrouped__'}
              onValueChange={(val) => setNewVolumeId(val === '__ungrouped__' ? null : val)}
            >
              <SelectTrigger data-testid="chapter-volume-select" className="h-8 w-auto shrink-0">
                <SelectValue placeholder="未分组" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__ungrouped__">未分组</SelectItem>
                {volumes.map((v) => (
                  <SelectItem key={v.id} value={v.id}>
                    {v.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
        )}
        <div data-testid="tree-action-row" className="flex items-center gap-2">
          <button
            type="button"
            className="flex-1 rounded px-2 py-1.5 text-[13px] text-ink-2 hover:bg-surface-3"
            onClick={() => setCreatingVolume(true)}
          >
            + 新建卷
          </button>
          <button
            type="button"
            className="flex-1 rounded px-2 py-1.5 text-[13px] text-ink-2 hover:bg-surface-3"
            onClick={() => setCreating(true)}
          >
            + {t('write.newChapter')}
          </button>
        </div>
      </div>
      {deleteTarget && (
        <VolumeDeleteDialog
          open
          volume={deleteTarget}
          otherVolumes={volumes.filter((v) => v.id !== deleteTarget.id)}
          chapterCount={chapters.filter((c) => c.volume_id === deleteTarget.id).length}
          onConfirm={(opts) => {
            setDeleteTarget(null);
            void deleteVolume(deleteTarget.id, opts);
          }}
          onOpenChange={(o) => {
            if (!o) setDeleteTarget(null);
          }}
        />
      )}
      {deleteChapterTarget && (
        <ConfirmDialog
          open
          title={t('lib.delete.title', { name: deleteChapterTarget.title })}
          message={t('lib.delete.confirm')}
          confirmText={t('lib.delete.ok')}
          danger
          testidPrefix="chapter-del"
          onConfirm={() => {
            const target = deleteChapterTarget;
            setDeleteChapterTarget(null);
            void deleteChapter(target.id);
          }}
          onOpenChange={(open) => {
            if (!open) setDeleteChapterTarget(null);
          }}
        />
      )}
      <div
        data-testid="tree-resize-handle"
        className="absolute inset-y-0 right-0 z-10 w-1 cursor-col-resize select-none"
        onMouseDown={startResize}
        aria-hidden="true"
      />
    </div>
  );
}
