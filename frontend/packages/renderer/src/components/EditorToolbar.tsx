/** 编辑器工具栏（spec §4.2.1 Q2 拍板 C）：默认 opacity 0.35、hover 编辑器区域全显 + 快捷键 */
import { Eye, FileSearch, Gauge, Redo2, Save, ScanSearch, Sparkles, Undo2, Wand2, Zap } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';

export interface EditorToolbarProps {
  disabled: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onSave: () => void;
  onContinue: () => void;
  onGenerate: () => void;
  /** F34 章节审计（Issue #208）：打开审计报告弹层 */
  onAudit: () => void;
  /** T2 风格检测（Issue #655）：打开风格分析报告弹层 */
  onStyleAnalyze?: () => void;
  /** F47 #379（spec §4.2）：视图切换（editor → detail）；缺省 editor、onToggleView 可选以兼容既有用法 */
  view?: 'editor' | 'detail';
  onToggleView?: () => void;
  /** #598 D9-a1：项目级「是否全自动」开关状态与切换回调（可选，兼容既有用法） */
  autoWriteEnabled?: boolean;
  onToggleAuto?: () => void;
  /** #652：AI 提取（打开提取弹窗；仅传入时渲染图标，兼容既有调用点） */
  onExtract?: () => void;
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
  onAudit,
  onStyleAnalyze,
  view = 'editor',
  onToggleView,
  autoWriteEnabled,
  onToggleAuto,
  onExtract,
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
      <span className="mx-1 h-4 w-px bg-line" />
      <button
        type="button"
        aria-label={t('write.toolbar.audit')}
        title={t('write.toolbar.audit')}
        className={ICON_BTN_CLS}
        disabled={disabled}
        onClick={onAudit}
      >
        <ScanSearch className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        data-testid="toolbar-style-analyze"
        aria-label={t('write.toolbar.style')}
        title={t('write.toolbar.style')}
        className={ICON_BTN_CLS}
        disabled={disabled}
        onClick={onStyleAnalyze}
      >
        <Gauge className="h-4 w-4" aria-hidden="true" />
      </button>
      <span className="mx-1 h-4 w-px bg-line" />
      <button
        type="button"
        data-testid="view-toggle"
        aria-label={view === 'detail' ? t('write.view.toEditor') : t('write.view.toDetail')}
        title={view === 'detail' ? t('write.view.toEditor') : t('write.view.toDetail')}
        className={ICON_BTN_CLS}
        onClick={onToggleView}
      >
        <Eye className="h-4 w-4" aria-hidden="true" />
      </button>
      <button
        type="button"
        data-testid="auto-toggle"
        aria-label={t('write.toolbar.autoToggle')}
        title={t('write.toolbar.autoToggle')}
        aria-pressed={autoWriteEnabled === true}
        className={ICON_BTN_CLS}
        onClick={onToggleAuto}
      >
        <Zap className="h-4 w-4" aria-hidden="true" />
      </button>
      {onExtract && (
        <button
          type="button"
          data-testid="extract-entry-write"
          aria-label={t('write.toolbar.extract')}
          title={t('write.toolbar.extract')}
          className={ICON_BTN_CLS}
          onClick={onExtract}
        >
          <FileSearch className="h-4 w-4" aria-hidden="true" />
        </button>
      )}
    </div>
  );
}
