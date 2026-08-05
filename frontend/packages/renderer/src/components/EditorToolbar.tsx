/** 编辑器工具栏（spec §4.2.1 Q2 拍板 C）：默认 opacity 0.35、hover 编辑器区域全显 + 快捷键 */
import { Redo2, Save, Sparkles, Undo2, Wand2 } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';

export interface EditorToolbarProps {
  disabled: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onSave: () => void;
  onContinue: () => void;
  onGenerate: () => void;
}

const ICON_BTN_CLS =
  'rounded p-1.5 text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-ink active:scale-[0.96] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:opacity-40';

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
        aria-label={t('write.toolbar.undo')}
        title={`${t('write.toolbar.undo')} (Ctrl+Z)`}
        className={ICON_BTN_CLS}
        onClick={onUndo}
      >
        <Undo2 className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label={t('write.toolbar.redo')}
        title={`${t('write.toolbar.redo')} (Ctrl+Y)`}
        className={ICON_BTN_CLS}
        onClick={onRedo}
      >
        <Redo2 className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        data-testid="toolbar-save"
        aria-label={t('write.toolbar.save')}
        title={`${t('write.toolbar.save')} (Ctrl+S)`}
        className={ICON_BTN_CLS}
        onClick={onSave}
      >
        <Save className="h-4 w-4" aria-hidden="true" />
      </button>
      <span className="mx-1 h-4 w-px bg-line" />
      <button
        type="button"
        aria-label={t('write.toolbar.continue')}
        title={`${t('write.toolbar.continue')} (Ctrl+Enter)`}
        className={ICON_BTN_CLS}
        disabled={disabled}
        onClick={onContinue}
      >
        <Wand2 className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        aria-label={t('write.toolbar.generate')}
        title={`${t('write.toolbar.generate')} (Ctrl+Shift+Enter)`}
        className={ICON_BTN_CLS}
        disabled={disabled}
        onClick={onGenerate}
      >
        <Sparkles className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
