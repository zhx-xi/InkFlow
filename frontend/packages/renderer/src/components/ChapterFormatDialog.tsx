/** #999 章节标题格式冲突弹窗（受控组件，仿 ConfirmDialog 结构）：
 *  焦点陷阱 / Esc → onOpenChange(false) / 遮罩点击不关闭（#195 先例）。
 *  关闭路径一律由父级置 open=false——本组件不自关闭 state（#376 红线）。
 */
import { useEffect, useRef } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useI18n } from '../i18n/useI18n';

/** S3e F3：框内可聚焦元素（初始焦点 + Tab 焦点陷阱共用；过滤 disabled / aria-hidden 元素） */
function getDialogFocusables(dialog: HTMLElement): HTMLElement[] {
  return Array.from(
    dialog.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((el) => el.getAttribute('aria-hidden') !== 'true');
}

export interface ChapterFormatDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 全书统一为「第N章」（阿拉伯序号） */
  onSelectArabic: () => void;
  /** 全书统一为「第X章」（中文序号） */
  onSelectChinese: () => void;
}

export function ChapterFormatDialog({
  open,
  onOpenChange,
  onSelectArabic,
  onSelectChinese,
}: ChapterFormatDialogProps) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDivElement | null>(null);

  // Esc 关闭（document 级监听覆盖框内任意焦点）
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onOpenChange(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onOpenChange]);

  // S3e F3：打开后初始焦点落入框内（首个可聚焦控件；无控件则聚焦对话框容器本身）
  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusables = getDialogFocusables(dialog);
    (focusables[0] ?? dialog).focus();
  }, [open]);

  /** S3e F3：Tab 焦点陷阱——焦点在首/尾元素（或逃出框内）时回绕，不逃出对话框 */
  const handleDialogKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab') return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusables = getDialogFocusables(dialog);
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement as HTMLElement | null;
    if (e.shiftKey) {
      if (active === first || !dialog.contains(active)) {
        e.preventDefault();
        last.focus();
      }
    } else if (active === last || !dialog.contains(active)) {
      e.preventDefault();
      first.focus();
    }
  };

  if (!open) return null;

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('tree.formatDialog.title')}
        data-testid="chapter-format-dialog"
        tabIndex={-1}
        className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleDialogKeyDown}
      >
        <h2 className="font-serif text-[18px] font-semibold">{t('tree.formatDialog.title')}</h2>
        <div className="mt-3 text-[13px] text-ink-2">{t('tree.formatDialog.message')}</div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="chapter-format-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            data-testid="chapter-format-arabic"
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={onSelectArabic}
          >
            {t('tree.formatDialog.arabic')}
          </button>
          <button
            type="button"
            data-testid="chapter-format-chinese"
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={onSelectChinese}
          >
            {t('tree.formatDialog.chinese')}
          </button>
        </div>
      </div>
    </div>
  );
}
