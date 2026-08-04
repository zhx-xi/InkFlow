/** 写作页（spec §4.2.1：三栏工作区，TDD 实现批次补全） */
import { useI18n } from '../i18n/useI18n';

export function WritingPage() {
  const { t } = useI18n();
  return (
    <div className="flex h-full">
      {/* 左: 项目树 208px */}
      <aside className="w-[208px] shrink-0 border-r border-line bg-surface-2" data-testid="project-tree">
        <div className="px-4 py-3 text-sm text-ink-3">{t('write.newChapter')}</div>
      </aside>
      {/* 中: 编辑器（弹性） */}
      <main className="flex-1 min-w-0 bg-surface" data-testid="editor">
        <div className="max-w-[680px] mx-auto px-14 py-9 text-ink-3">{t('common.empty')}</div>
      </main>
      {/* 右: 上下文面板 240px（可折叠） */}
      <aside className="w-[240px] shrink-0 border-l border-line bg-surface-2" data-testid="context-panel">
        <div className="px-4 py-3 text-sm text-ink-3">{t('write.context.title')}</div>
      </aside>
    </div>
  );
}
