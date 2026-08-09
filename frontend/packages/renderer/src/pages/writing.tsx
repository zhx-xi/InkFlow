/** 写作页（spec §4.2.1）：三栏 + 工具栏快捷键 + SSE 流式区 + 上下文折叠 + 印章常驻 + 状态栏 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Compass } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { auditChapter, confirmAudit, type AuditReportDto } from '../api/audit';
import { errorMessage } from '../api/client';
import { AuditDialog } from '../components/AuditDialog';
import { ChapterEditor } from '../components/ChapterEditor';
import { ContextPanel } from '../components/ContextPanel';
import { EditorToolbar } from '../components/EditorToolbar';
import { ProjectTree } from '../components/ProjectTree';
import { StatusBar } from '../components/StatusBar';
import { StreamArea } from '../components/StreamArea';
import { Skeleton } from '../components/ui/skeleton';
import { useStream } from '../hooks/useStream';
import { useI18n } from '../i18n/useI18n';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';

/** 无项目引导态（仅挂载于无项目分支，避免无 Router 上下文的测试报错） */
function WritingEmptyState() {
  const { t } = useI18n();
  const navigate = useNavigate();
  return (
    <div data-testid="writing-empty" className="flex h-full items-center justify-center">
      <div className="text-center">
        <Compass className="mx-auto h-10 w-10 text-ink-3" aria-hidden="true" />
        <p className="mt-3 text-[15px] text-ink-2">{t('write.empty.title')}</p>
        <button
          type="button"
          className="mt-5 rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink"
          onClick={() => navigate('/projects')}
        >
          {t('write.empty.back')}
        </button>
      </div>
    </div>
  );
}

export function WritingPage() {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const projects = useProjectStore((s) => s.projects);
  const projectsLoading = useProjectStore((s) => s.loading);
  const projectsError = useProjectStore((s) => s.error);
  const selectProject = useProjectStore((s) => s.selectProject);
  const loadChapterTree = useChapterStore((s) => s.loadChapterTree);
  const currentChapterId = useChapterStore((s) => s.currentChapterId);
  const saveContent = useChapterStore((s) => s.saveContent);
  const content = useChapterStore((s) => s.content);
  const chapters = useChapterStore((s) => s.chapters);
  const chaptersLoading = useChapterStore((s) => s.loading);

  const currentProject = projects.find((p) => p.id === currentProjectId) ?? projects[0];
  const effectiveProjectId = currentProjectId ?? currentProject?.id ?? '';
  const stream = useStream({ projectId: effectiveProjectId, chapterId: currentChapterId ?? '' });
  const { status, text, wordCount, summary, error, start, stop, retry } = stream;

  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const dirtyRef = useRef(false);
  const loadedRef = useRef<string | null>(null);

  const save = useCallback(async () => {
    await saveContent();
    setSavedAt(new Date());
  }, [saveContent]);

  // F34 章节审计（Issue #208）：报告为瞬态 UI 状态（F19 先例），不新增 store
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditReport, setAuditReport] = useState<AuditReportDto | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditConfirming, setAuditConfirming] = useState(false);

  const handleAudit = useCallback(async () => {
    if (!effectiveProjectId || !currentChapterId) return;
    setAuditOpen(true);
    setAuditLoading(true);
    setAuditError(null);
    setAuditReport(null);
    try {
      const report = await auditChapter(effectiveProjectId, currentChapterId);
      setAuditReport(report);
    } catch (err) {
      setAuditError(errorMessage(err));
    } finally {
      setAuditLoading(false);
    }
  }, [effectiveProjectId, currentChapterId]);

  const handleConfirm = useCallback(
    async (action: 'accept' | 'reject', note: string) => {
      if (!effectiveProjectId || !currentChapterId) return;
      setAuditConfirming(true);
      try {
        await confirmAudit(effectiveProjectId, currentChapterId, action, note);
        // 确认成功 → 关闭弹层（闭环）；失败保留弹层显示 error
        setAuditOpen(false);
        setAuditReport(null);
      } catch (err) {
        setAuditError(errorMessage(err));
      } finally {
        setAuditConfirming(false);
      }
    },
    [effectiveProjectId, currentChapterId],
  );

  // 挂载自动加载当前项目卷章树；currentProjectId 为空时回退首个项目（路由直入写作页场景）
  useEffect(() => {
    const pid = currentProjectId ?? projects[0]?.id ?? null;
    if (pid === null) return;
    if (currentProjectId !== pid) selectProject(pid);
    if (loadedRef.current !== pid) {
      loadedRef.current = pid;
      void loadChapterTree(pid);
    }
  }, [currentProjectId, projects, selectProject, loadChapterTree]);

  // 自动保存：用户编辑后 2s 防抖落盘（SSE done 帧提交 content 不触发）
  useEffect(() => {
    if (!dirtyRef.current) return;
    const timer = setTimeout(() => {
      dirtyRef.current = false;
      void save();
    }, 2000);
    return () => clearTimeout(timer);
  }, [content, save]);

  const handleContentChange = (value: string) => {
    dirtyRef.current = true;
    useChapterStore.getState().setContent(value);
  };

  const handleKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      if (!e.ctrlKey) return;
      const key = e.key.toLowerCase();
      if (e.shiftKey && key === 'enter') {
        e.preventDefault();
        start('generate');
        return;
      }
      switch (key) {
        case 'z':
          e.preventDefault();
          document.execCommand('undo');
          break;
        case 'y':
          e.preventDefault();
          document.execCommand('redo');
          break;
        case 's':
          e.preventDefault();
          void save();
          break;
        case 'enter':
          e.preventDefault();
          start('continue');
          break;
        default:
          break;
      }
    },
    [start, save],
  );

  if (effectiveProjectId === '' && !projectsLoading && !projectsError) {
    return <WritingEmptyState />;
  }

  const currentChapter = chapters.find((c) => c.id === currentChapterId);
  const displayWords = status === 'generating' ? wordCount : currentChapter?.word_count ?? 0;
  const model = summary?.model ?? currentProject?.config?.model ?? null;
  const generating = status === 'generating';

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-0 flex-1">
        <aside
          data-testid="project-tree"
          className="flex w-[208px] shrink-0 flex-col border-r border-line bg-surface-2"
        >
          {chaptersLoading && chapters.length === 0 ? (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="flex items-center gap-2 border-b border-line p-3">
                <Skeleton className="h-8 w-8 rounded-full" />
                <div className="space-y-1.5">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-2.5 w-14" />
                </div>
              </div>
              <div className="flex-1 space-y-2 p-2">
                <Skeleton className="h-5 w-16" />
                {Array.from({ length: 6 }, (_, i) => (
                  <Skeleton key={i} className="h-6 w-full" />
                ))}
              </div>
            </div>
          ) : (
            <ProjectTree />
          )}
        </aside>
        <main data-testid="editor" className="group flex min-w-0 flex-1 flex-col bg-surface">
          <EditorToolbar
            disabled={generating}
            onUndo={() => document.execCommand('undo')}
            onRedo={() => document.execCommand('redo')}
            onSave={() => void save()}
            onContinue={() => start('continue')}
            onGenerate={() => start('generate')}
            onAudit={() => void handleAudit()}
          />
          <ChapterEditor onEditorKeyDown={handleKeyDown} onContentChange={handleContentChange} />
          <StreamArea
            status={status}
            text={text}
            wordCount={wordCount}
            summary={summary}
            error={error}
            onStop={stop}
            onRetry={retry}
          />
        </main>
        <ContextPanel />
      </div>
      <AuditDialog
        open={auditOpen}
        report={auditReport}
        loading={auditLoading}
        error={auditError}
        onClose={() => setAuditOpen(false)}
        onConfirm={(a, n) => void handleConfirm(a, n)}
        confirming={auditConfirming}
      />
      <StatusBar model={model} wordCount={displayWords} savedAt={savedAt} />
    </div>
  );
}
