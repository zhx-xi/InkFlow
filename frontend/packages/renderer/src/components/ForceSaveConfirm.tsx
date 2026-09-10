/**
 * #936 C 项 GUI 消费面：探测门禁 422 的「强制保存」确认框。
 *
 * 背景：后端 `provider_config_service.create/update` 保存前对「新增/改动模型条目」
 * 做 type-aware 最小探测，失败 → 422（detail 含模型 id + 摘要 + 「如需强制保存请
 * 使用 force=true」）。GUI 主路径（模型管理页 / 首启引导）必须给用户**显式逃生门**
 * —— 默认必过（#929 拍板②「不静默」），失败时不静默吞错，而是提示 + 可选强制保存。
 *
 * 设计要点：
 * - **全路径统一**：模型管理页（addModel / setModelReasoning）与首启引导（SetupGuide）
 *   共用本组件 + `isForceableProbeRejection` 判据（判据在 `probeGate.ts`，禁止同族分叉）。
 * - 422 + detail 含 force 提示 = 可强制；其余错误（404/500/网络）走普通错误提示。
 * - 「强制保存」→ 调用方以 `force=true` 重发；取消 → 保留草稿不落库。
 */
import { AlertTriangle } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';

export interface ForceSaveConfirmProps {
  open: boolean;
  /** 后端 422 detail（含模型 id + 失败摘要），直接展示给用户 */
  detail: string;
  /** 用户确认强制保存 */
  onConfirm: () => void;
  /** 用户取消（保留草稿，不落库） */
  onCancel: () => void;
}

export function ForceSaveConfirm({ open, detail, onConfirm, onCancel }: ForceSaveConfirmProps) {
  const { t } = useI18n();
  if (!open) return null;

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30"
      onClick={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('m.probeGate.title')}
        data-testid="probe-gate-confirm"
        className="w-[480px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warn" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <h2 className="font-serif text-[17px] font-semibold">{t('m.probeGate.title')}</h2>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-2">
              {t('m.probeGate.body')}
            </p>
            <p
              data-testid="probe-gate-detail"
              className="mt-2 rounded-md border border-line bg-surface-3 px-3 py-2 text-[12px] leading-relaxed text-ink-2"
            >
              {detail}
            </p>
            <p className="mt-2 text-[12px] text-ink-3">{t('m.probeGate.warning')}</p>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="probe-gate-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={onCancel}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            data-testid="probe-gate-force"
            className="rounded-md bg-warn px-4 py-1.5 text-sm text-white transition duration-180 hover:opacity-90 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={onConfirm}
          >
            {t('m.probeGate.force')}
          </button>
        </div>
      </div>
    </div>
  );
}
