/** 写作页（spec §4.2.1）：三栏 + 工具栏快捷键 + SSE 流式区 + 上下文折叠 + 印章常驻 + 状态栏 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { ChapterEditor } from '../components/ChapterEditor';
import { ContextPanel } from '../components/ContextPanel';
import { EditorToolbar } from '../components/EditorToolbar';
import { ProjectTree } from '../components/ProjectTree';
import { StatusBar } from '../components/StatusBar';
import { StreamArea } from '../components/StreamArea';
import { useStream } from '../hooks/useStream';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';

export function WritingPage() {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const projects = useProjectStore((s) => s.projects);
  const selectProject = useProjectStore((s) => s.selectProject);
  const loadChapterTree = useChapterStore((s) => s.loadChapterTree);
  const currentChapterId = useChapterStore((s) => s.currentChapterId);
  const saveContent = useChapterStore((s) => s.saveContent);
  const content = useChapterStore((s) => s.content);
  const chapters = useChapterStore((s) => s.chapters);

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
          <ProjectTree />
        </aside>
        <main data-testid="editor" className="group flex min-w-0 flex-1 flex-col bg-surface">
          <EditorToolbar
            disabled={generating}
            onUndo={() => document.execCommand('undo')}
            onRedo={() => document.execCommand('redo')}
            onSave={() => void save()}
            onContinue={() => start('continue')}
            onGenerate={() => start('generate')}
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
      <StatusBar model={model} wordCount={displayWords} savedAt={savedAt} />
    </div>
  );
}
