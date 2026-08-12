/** 项目页（spec §4.2.2 + F43 §5.5）：卡片网格 + 新建对话框，双入口 + 创建后跳转写作页；
 * F43：卡片菜单重命名/删除（重命名轻量单字段对话框 + 删除二次确认，均 #195 遮罩不关闭） */
import { useEffect, useState } from 'react';
import { BookOpen } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { errorMessage, ensureApiReady } from '../api/client';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { NewProjectDialog } from '../components/NewProjectDialog';
import { ProjectCard } from '../components/ProjectCard';
import { Skeleton } from '../components/ui/skeleton';
import { useI18n } from '../i18n/useI18n';
import { useProjectStore, type Project } from '../stores/project';
import { useToastStore } from '../stores/toast';

/** F43 §5.5：项目重命名对话框（轻量单字段；遮罩点击不关闭 #195，关闭仅 取消/Esc/成功） */
function RenameProjectDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const { t } = useI18n();
  const renameProject = useProjectStore((s) => s.renameProject);
  const pushToast = useToastStore((s) => s.pushToast);
  const [name, setName] = useState(project.name);
  const [saving, setSaving] = useState(false);

  // Esc 关闭（document 级监听；in-flight 时忽略关闭路径，防误关丢进度）
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented && !saving) onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose, saving]);

  // strip 后为空 → 保存按钮 disabled（对齐 NewProjectDialog 书名校验，spec E6）
  const canSave = name.trim() !== '' && !saving;

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      await renameProject(project.id, name.trim());
      onClose();
      pushToast('ok', t('toast.saved'));
    } catch (err) {
      // 失败：err toast + 对话框保持可修改重试（spec E1 对齐；store rethrow 不吞错）
      pushToast('err', errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('pj.rename.title')}
        data-testid="project-rename-dialog"
        className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">{t('pj.rename.title')}</h2>
        <div className="mt-4">
          <label className="flex flex-col gap-1.5 text-[13px]">
            <span>{t('pj.rename.placeholder')}</span>
            <input
              data-testid="project-rename-input"
              aria-label={t('pj.rename.placeholder')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="project-rename-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={onClose}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            data-testid="project-rename-save"
            disabled={!canSave}
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => void handleSave()}
          >
            {t('pj.rename.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

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
  const deleteProject = useProjectStore((s) => s.deleteProject);
  const [dialogOpen, setDialogOpen] = useState(false);
  // F43：卡片菜单重命名 / 删除确认对象（非空 = 对应对话框打开）
  const [renaming, setRenaming] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState<Project | null>(null);

  useEffect(() => {
    // #98 修复：Electron 下等待 preload 注入 INKFLOW_API（'inkflow:api-ready'）后再发首请求，
    // 避免「React 挂载早于注入 → 首请求无 token → 401」时序竞态；非 Electron 立即通过。
    void (async () => {
      await ensureApiReady();
      void loadProjects();
    })();
  }, [loadProjects]);

  // F43 §5.5：项目删除确认 → store.deleteProject（DELETE）→ 成功/失败均关闭确认框；
  // 成功 ok toast（卡片消失由 store 驱动），失败 err toast（store rethrow 不吞错）
  const handleProjectDelete = async () => {
    if (!deleting) return;
    const target = deleting;
    try {
      await deleteProject(target.id);
      setDeleting(null);
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      setDeleting(null);
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

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
              onRename={setRenaming}
              onDelete={setDeleting}
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

      {/* F43 §5.5：重命名对话框（关闭 = 取消/Esc/成功；遮罩点击不关闭 #195） */}
      {renaming && <RenameProjectDialog project={renaming} onClose={() => setRenaming(null)} />}

      {/* F43 §5.5：删除二次确认（数据范围行 + D11 统一行；遮罩点击不关闭 #195） */}
      {deleting && (
        <ConfirmDialog
          open
          title={t('pj.delete.title', { name: deleting.name })}
          message={
            <>
              <p>{t('pj.delete.range')}</p>
              <p>{t('lib.delete.confirm')}</p>
            </>
          }
          confirmText={t('pj.delete.ok')}
          danger
          testidPrefix="project-delete"
          onConfirm={() => void handleProjectDelete()}
          onOpenChange={(open) => {
            if (!open) setDeleting(null);
          }}
        />
      )}
    </div>
  );
}
