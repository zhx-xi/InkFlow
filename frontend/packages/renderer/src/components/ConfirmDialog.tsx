/** 共享删除确认框（F43，specs/f43-setting-library-gui/spec.md §2.3）：
 * 设定库列表项 + 项目卡片两处消费（Rule of Two 已到）。
 * 关闭路径 = 取消按钮 / Esc / 父级确认成功后 onOpenChange(false)；
 * 遮罩点击不关闭（#195 拍板，与 TemplateDialog 旧确认框不同）。
 */
import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { useI18n } from '../i18n/useI18n';

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: ReactNode; // 支持多行（D11 统一文案 + 追加警告行）
  confirmText: string;
  danger?: boolean; // true = 确认按钮红色（text-err 系，对齐 models.tsx 删除按钮）
  testidPrefix: string; // 例如 'lib-confirm' / 'project-delete'
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmText,
  danger = false,
  testidPrefix,
  onConfirm,
  onOpenChange,
}: ConfirmDialogProps) {
  const { t } = useI18n();

  // Esc 关闭（document 级监听覆盖框内任意焦点；尊重 Radix Select 等已 preventDefault 的 Escape）
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onOpenChange(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onOpenChange]);

  if (!open) return null;

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        data-testid={`${testidPrefix}-dialog`}
        className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">{title}</h2>
        <div className="mt-3 space-y-1.5 text-[13px] text-ink-2">{message}</div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid={`${testidPrefix}-cancel`}
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            data-testid={`${testidPrefix}-ok`}
            className={
              danger
                ? 'rounded-md border border-err/40 px-4 py-1.5 text-sm text-err transition duration-180 hover:bg-err/10 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60'
                : 'rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60'
            }
            onClick={onConfirm}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
