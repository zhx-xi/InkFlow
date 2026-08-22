/** 章节编辑器（spec §4.2.1 Q1 拍板 A）：段落化纯文本 textarea，16px/行高 1.85/首行缩进 2em */
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useI18n } from '../i18n/useI18n';
import { useChapterStore } from '../stores/chapter';

export interface ChapterEditorProps {
  onEditorKeyDown: (e: ReactKeyboardEvent<HTMLDivElement>) => void;
  onContentChange: (value: string) => void;
}

export function ChapterEditor({ onEditorKeyDown, onContentChange }: ChapterEditorProps) {
  const { t } = useI18n();
  const content = useChapterStore((s) => s.content);
  const chapters = useChapterStore((s) => s.chapters);
  const currentChapterId = useChapterStore((s) => s.currentChapterId);
  const currentChapter = chapters.find((c) => c.id === currentChapterId);

  return (
    <div className="flex min-h-0 flex-1 flex-col" onKeyDown={onEditorKeyDown}>
      <div className="border-b border-line px-8 py-4">
        <h2 className="font-serif text-[18px] font-semibold">{currentChapter?.title ?? ''}</h2>
        <div className="mt-0.5 text-[12px] text-ink-3">
          {currentChapter ? `${currentChapter.word_count.toLocaleString()} ${t('sb.words')}` : ''}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <textarea
          data-testid="chapter-editor"
          className="h-full w-full resize-none bg-transparent px-8 py-6 text-[16px] leading-[1.85] text-ink outline-none [text-indent:2em]"
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
          placeholder={currentChapter ? '' : t('write.empty.noChapter')}
        />
      </div>
    </div>
  );
}
