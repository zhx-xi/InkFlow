/** 写作页（spec §4.2.1）：三栏 + 工具栏快捷键 + SSE 流式区 + 上下文折叠 + 印章常驻 + 状态栏 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { Compass } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { auditChapter, confirmAudit, type AuditReportDto } from '../api/audit';
import { analyzeStyle, type StyleReportDto } from '../api/style';
import { errorMessage } from '../api/client';
import { AuditDialog } from '../components/AuditDialog';
import { AutoAuthorizationDialog } from '../components/AutoAuthorizationDialog';
import { ChapterEditor } from '../components/ChapterEditor';
import { ChatPanel } from '../components/ChatPanel';
import { ChapterSummaryPanel } from '../components/ChapterSummaryPanel';
import { ContextPanel } from '../components/ContextPanel';
import { DraftApprovalPanel } from '../components/DraftApprovalPanel';
import { EditorToolbar } from '../components/EditorToolbar';
import { ExecutionDetailPanel } from '../components/ExecutionDetailPanel';
import { AIExtractDialog } from '../components/extract/AIExtractDialog';
import { PipelineStatus } from '../components/PipelineStatus';
import { ProjectTree } from '../components/ProjectTree';
import { StatusBar } from '../components/StatusBar';
import { StyleAnalyzeDialog } from '../components/StyleAnalyzeDialog';
import { Skeleton } from '../components/ui/skeleton';
import { usePipeline } from '../hooks/usePipeline';
import { useI18n } from '../i18n/useI18n';
import { useChapterStore } from '../stores/chapter';
import { ensureModelReady } from '../stores/models';
import { useProjectStore } from '../stores/project';
import { useToastStore } from '../stores/toast';

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
  const { t } = useI18n();
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
  const pipeline = usePipeline({
    projectId: effectiveProjectId,
    chapterId: currentChapterId ?? '',
    tags: currentProject?.tags ?? [],
    targetWords: currentProject?.target_words ?? 0,
    writingStyle: currentProject?.config?.writing_style ?? '',
    chapterTitle: chapters.find((c) => c.id === currentChapterId)?.title ?? '',
    supervisor: currentProject?.config?.supervisor ?? null,
  });
  const {
    status,
    error,
    start,
    hitlPending,
    confirm,
    executionId,
    currentStage,
    stageName,
    stageProgress,
    stageElapsedMs,
  } = pipeline;

  // #474 P0：模型未配置前置校验（续写/生成四触发点共用守卫）
  const startWithCheck = useCallback(
    async (mode: 'write_auto' | 'write_continue') => {
      if (!(await ensureModelReady())) {
        useToastStore.getState().pushToast('warn', t('common.modelNotConfigured'));
        return;
      }
      start(mode);
    },
    [start, t],
  );

  // F47 #379（spec §4.2）：正文编辑 ↔ AI 执行详情视图切换，默认 editor
  const [view, setView] = useState<'editor' | 'detail'>('editor');
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [confirming, setConfirming] = useState(false);
  // #598 D9-a1：首次授权弹框开关（默认关闭；「触发全自动且未授权」时置 true）
  const [autoAuthOpen, setAutoAuthOpen] = useState(false);
  const dirtyRef = useRef(false);
  const loadedRef = useRef<string | null>(null);
  // #702：左栏宽度受控（ProjectTree col-resize 手柄回调）；#703：右栏面板高度
  const [treeWidth, setTreeWidth] = useState(208);
  const [contextPanelH, setContextPanelH] = useState(240);
  const [summaryPanelH, setSummaryPanelH] = useState(160);

  // #703：右栏 row-resize 拖拽 — target 指定被拖高的上一面板（context / summary）
  const startRailResize = useCallback(
    (target: 'context' | 'summary') => (e: ReactMouseEvent) => {
      e.preventDefault();
      const startY = e.clientY;
      const startH = target === 'context' ? contextPanelH : summaryPanelH;
      const setH = target === 'context' ? setContextPanelH : setSummaryPanelH;
      document.body.style.userSelect = 'none';
      const onMove = (ev: MouseEvent) => {
        const next = Math.max(90, Math.min(540, startH + (ev.clientY - startY)));
        setH(next);
      };
      const onUp = () => {
        document.body.style.userSelect = '';
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    },
    [contextPanelH, summaryPanelH],
  );

  const handleHitlConfirm = useCallback(
    (approved: boolean) => {
      setConfirming(true);
      // confirm 内部状态机续跑；成功后恢复 confirming
      confirm(approved);
      // 简单起见：confirm 是异步续跑，成功/失败态由 usePipeline 内部处理；
      // 这里延迟重置 confirming（轮询成功后 UI 已切换）
      setTimeout(() => setConfirming(false), 1500);
    },
    [confirm],
  );

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

  // T2 风格检测（Issue #655）：报告为瞬态 UI 状态（镜像 F34 审计，不新增 store）
  const [styleOpen, setStyleOpen] = useState(false);
  const [styleReport, setStyleReport] = useState<StyleReportDto | null>(null);
  const [styleLoading, setStyleLoading] = useState(false);
  const [styleError, setStyleError] = useState<string | null>(null);
  // #652：AI 提取弹窗开关
  const [extractOpen, setExtractOpen] = useState(false);

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

  const handleStyleAnalyze = useCallback(async () => {
    if (!effectiveProjectId || !currentChapterId) return;
    setStyleOpen(true);
    setStyleLoading(true);
    setStyleError(null);
    setStyleReport(null);
    try {
      const r = await analyzeStyle(effectiveProjectId, { chapter_ids: [currentChapterId] });
      setStyleReport(r);
    } catch (err) {
      setStyleError(errorMessage(err));
    } finally {
      setStyleLoading(false);
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
        startWithCheck('write_auto');
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
          startWithCheck('write_continue');
          break;
        default:
          break;
      }
    },
    [startWithCheck, save],
  );

  if (effectiveProjectId === '' && !projectsLoading && !projectsError) {
    return <WritingEmptyState />;
  }

  const currentChapter = chapters.find((c) => c.id === currentChapterId);
  const displayWords = currentChapter?.word_count ?? 0;
  const model = currentProject?.config?.model ?? null;
  const generating = status === 'running';

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-0 flex-1">
        <aside
          data-testid="project-tree"
          className="flex shrink-0 flex-col border-r border-line bg-surface-2"
          style={{ width: treeWidth }}
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
            <ProjectTree width={treeWidth} onResizeWidth={setTreeWidth} />
          )}
        </aside>
        <main data-testid="editor" className="group flex min-w-0 flex-1 flex-col bg-surface">
          <EditorToolbar
            disabled={generating}
            generating={generating}
            onUndo={() => document.execCommand('undo')}
            onRedo={() => document.execCommand('redo')}
            onSave={() => void save()}
            onContinue={() => startWithCheck('write_continue')}
            onGenerate={() => startWithCheck('write_auto')}
            onAudit={() => void handleAudit()}
            onStyleAnalyze={() => void handleStyleAnalyze()}
            view={view}
            onToggleView={() => setView((v) => (v === 'editor' ? 'detail' : 'editor'))}
            autoWriteEnabled={currentProject?.config?.auto_write_enabled === true}
            onToggleAuto={() => {
              if (currentProject) {
                void useProjectStore.getState().updateConfig(currentProject.id, {
                  auto_write_enabled: !(currentProject.config?.auto_write_enabled === true),
                });
              }
            }}
            onExtract={() => setExtractOpen(true)}
          />
          {view === 'editor' ? (
            <ChapterEditor onEditorKeyDown={handleKeyDown} onContentChange={handleContentChange} />
          ) : (
            <ExecutionDetailPanel executionId={executionId} projectId={effectiveProjectId} />
          )}
          {view === 'editor' && effectiveProjectId !== '' && currentChapterId !== null ? (
            <ChatPanel
              projectId={effectiveProjectId}
              chapterId={currentChapterId ?? undefined}
              chapterContent={content}
              streamSink={pipeline.streamSinkRef}
            />
          ) : null}
          <PipelineStatus
            status={status}
            error={error}
            hitlPending={hitlPending}
            onConfirm={handleHitlConfirm}
            confirming={confirming}
            currentStage={currentStage}
            stageName={stageName}
            stageProgress={stageProgress}
            stageElapsedMs={stageElapsedMs}
          />
        </main>
        <aside
          data-testid="right-rail"
          className="flex w-[240px] shrink-0 flex-col border-l border-line bg-surface-2"
        >
          <div
            data-testid="rail-panel-context"
            style={{ height: `${contextPanelH}px` }}
            className="min-h-0 shrink-0 flex flex-col"
          >
            <ContextPanel
              projectId={effectiveProjectId}
              chapterId={currentChapterId}
              model={model}
              writingRequirements={currentProject?.config?.writing_style ?? '上下文预览'}
            />
          </div>
          <div
            data-testid="rail-resize-handle-0"
            className="h-2 shrink-0 cursor-row-resize select-none border-t border-line bg-surface-3"
            onMouseDown={startRailResize('context')}
            aria-hidden="true"
          />
          <div
            data-testid="rail-panel-summary"
            style={{ height: `${summaryPanelH}px` }}
            className="min-h-0 shrink-0 flex flex-col"
          >
            <ChapterSummaryPanel projectId={effectiveProjectId} chapterId={currentChapterId} />
          </div>
          <div
            data-testid="rail-resize-handle-1"
            className="h-2 shrink-0 cursor-row-resize select-none border-t border-line bg-surface-3"
            onMouseDown={startRailResize('summary')}
            aria-hidden="true"
          />
          <div
            data-testid="rail-panel-drafts"
            className="min-h-[120px] shrink-0 flex flex-col"
          >
            <DraftApprovalPanel projectId={effectiveProjectId} />
          </div>
        </aside>
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
      <StyleAnalyzeDialog
        open={styleOpen}
        report={styleReport}
        loading={styleLoading}
        error={styleError}
        onClose={() => {
          setStyleOpen(false);
        }}
      />
      {/* #598 D9-a1：首次授权弹框 —— 默认关闭；由「触发全自动且未授权」动作置 true。
          注：全自动实际从 chat 触发的接线在后续里程碑（#597 已删书级入口），
          本批保证组件可用 + 不干扰写作页加载（未授权不自动弹框）。 */}
      <AutoAuthorizationDialog
        projectId={effectiveProjectId}
        open={autoAuthOpen}
        onClose={() => setAutoAuthOpen(false)}
      />
      {/* #652：AI 提取弹窗（默认写作页当前章 + 当前正文，避免重复拉取） */}
      <AIExtractDialog
        open={extractOpen}
        onClose={() => setExtractOpen(false)}
        projectId={effectiveProjectId}
        defaultChapterId={currentChapterId ?? undefined}
        defaultText={content}
      />
      <StatusBar model={model} wordCount={displayWords} savedAt={savedAt} />
    </div>
  );
}
