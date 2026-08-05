/** Toast 挂载点（spec §6.2①：三态 / aria-live / 低动效 ≤180ms；2s 自动消失由 store 定时器驱动） */
import { CircleCheck, CircleX, TriangleAlert, X } from 'lucide-react';
import type { Toast, ToastType } from '../../stores/toast';
import { useToastStore } from '../../stores/toast';
import { useI18n } from '../../i18n/useI18n';

const ICON_BY_TYPE: Record<ToastType, typeof CircleCheck> = {
  ok: CircleCheck,
  err: CircleX,
  warn: TriangleAlert,
};

/** 三态语义色（tokens.css 既有 ok/err/warn 变量，经 Tailwind 语义色映射） */
const COLOR_BY_TYPE: Record<ToastType, string> = {
  ok: 'text-ok',
  err: 'text-err',
  warn: 'text-warn',
};

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const { t } = useI18n();
  const Icon = ICON_BY_TYPE[toast.type];
  return (
    <div
      role="status"
      className="flex items-start gap-2.5 rounded-md border border-line bg-surface p-3 shadow-card transition-transform duration-180"
    >
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${COLOR_BY_TYPE[toast.type]}`} aria-hidden="true" />
      <span className="min-w-0 flex-1 break-words text-[13px] text-ink">{toast.message}</span>
      <button
        type="button"
        aria-label={t('toast.close')}
        className="shrink-0 rounded p-0.5 text-ink-3 transition-colors duration-180 hover:bg-surface-3 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => onDismiss(toast.id)}
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}

export function ToastHost() {
  const toasts = useToastStore((s) => s.toasts);
  const dismissToast = useToastStore((s) => s.dismissToast);

  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-80 flex-col gap-2">
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <ToastItem toast={toast} onDismiss={dismissToast} />
        </div>
      ))}
    </div>
  );
}
