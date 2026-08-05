/** 编辑器工具栏（spec §4.2.1 Q2 拍板 C）：默认 opacity 0.35、hover 编辑器区域全显 + 快捷键 */
import { useI18n } from '../i18n/useI18n';

export interface EditorToolbarProps {
  disabled: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onSave: () => void;
  onContinue: () => void;
  onGenerate: () => void;
}

export function EditorToolbar({
  disabled,
  onUndo,
  onRedo,
  onSave,
  onContinue,
  onGenerate,
}: EditorToolbarProps) {
  const { t } = useI18n();
  return (
    <div
      data-testid="editor-toolbar"
      className="flex items-center gap-1 border-b border-line bg-surface px-3 py-1.5 opacity-[0.35] transition-opacity duration-180 group-hover:opacity-100"
    >
      <button
        type="button"
        className="rounded px-2 py-1 text-[12px] text-ink-2 hover:bg-surface-2"
        onClick={onUndo}
      >
        {t('write.toolbar.undo')}
      </button>
      <button
        type="button"
        className="rounded px-2 py-1 text-[12px] text-ink-2 hover:bg-surface-2"
        onClick={onRedo}
      >
        {t('write.toolbar.redo')}
      </button>
      <button
        type="button"
        data-testid="toolbar-save"
        className="rounded px-2 py-1 text-[12px] text-ink-2 hover:bg-surface-2"
        onClick={onSave}
      >
        {t('write.toolbar.save')}
      </button>
      <span className="mx-1 h-4 w-px bg-line" />
      <button
        type="button"
        className="rounded px-2 py-1 text-[12px] text-ink-2 hover:bg-surface-2 disabled:opacity-40"
        disabled={disabled}
        onClick={onContinue}
      >
        {t('write.toolbar.continue')}
      </button>
      <button
        type="button"
        className="rounded px-2 py-1 text-[12px] text-ink-2 hover:bg-surface-2 disabled:opacity-40"
        disabled={disabled}
        onClick={onGenerate}
      >
        {t('write.toolbar.generate')}
      </button>
    </div>
  );
}
