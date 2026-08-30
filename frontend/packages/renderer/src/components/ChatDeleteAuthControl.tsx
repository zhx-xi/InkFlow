/**
 * #766 阶段②：Chat 删除授权三态分段控件 + HITL 确认弹窗
 * （从 ChatPanel.tsx 拆出以守 900 行护栏；testid / i18n 值 / 事件逻辑与拆分前完全一致）。
 */
import { useI18n } from '../i18n/useI18n';

export interface ChatDeleteAuthControlProps {
  deletePermission: 'manual' | 'ask_once' | 'auto';
  onModeChange: (mode: 'manual' | 'ask_once' | 'auto') => void;
  interruptPayload: { tool: string; entity_id: string; entity_name: string } | null;
  onApprove: () => void;
  onCancel: () => void;
}

export function ChatDeleteAuthControl({
  deletePermission,
  onModeChange,
  interruptPayload,
  onApprove,
  onCancel,
}: ChatDeleteAuthControlProps) {
  const { t } = useI18n();
  return (
    <>
      {/* #766 阶段②：删除授权三态分段控件（HITL 弹窗打开期间禁用，防中断中改权限） */}
      <div className="flex items-center gap-1">
        <button
          type="button"
          data-testid="delete-mode-manual"
          data-selected={deletePermission === 'manual' ? 'true' : 'false'}
          aria-pressed={deletePermission === 'manual'}
          disabled={interruptPayload !== null}
          className={`rounded-md border px-2 py-0.5 text-[12px] disabled:opacity-40 ${
            deletePermission === 'manual' ? 'border-accent text-ink' : 'border-line text-ink-2'
          }`}
          onClick={() => void onModeChange('manual')}
        >
          {t('write.chat.deleteMode.manual')}
        </button>
        <button
          type="button"
          data-testid="delete-mode-ask-once"
          data-selected={deletePermission === 'ask_once' ? 'true' : 'false'}
          aria-pressed={deletePermission === 'ask_once'}
          disabled={interruptPayload !== null}
          className={`rounded-md border px-2 py-0.5 text-[12px] disabled:opacity-40 ${
            deletePermission === 'ask_once' ? 'border-accent text-ink' : 'border-line text-ink-2'
          }`}
          onClick={() => void onModeChange('ask_once')}
        >
          {t('write.chat.deleteMode.askOnce')}
        </button>
        <button
          type="button"
          data-testid="delete-mode-auto"
          data-selected={deletePermission === 'auto' ? 'true' : 'false'}
          aria-pressed={deletePermission === 'auto'}
          disabled={interruptPayload !== null}
          className={`rounded-md border px-2 py-0.5 text-[12px] disabled:opacity-40 ${
            deletePermission === 'auto' ? 'border-accent text-ink' : 'border-line text-ink-2'
          }`}
          onClick={() => void onModeChange('auto')}
        >
          {t('write.chat.deleteMode.auto')}
        </button>
      </div>
      {/* #766 阶段②：HITL 删除授权确认弹窗（interrupt 帧到达时渲染） */}
      {interruptPayload && (
        <div
          data-testid="delete-confirm-dialog"
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
        >
          <div className="rounded-md border border-line bg-surface px-4 py-3 shadow-lg">
            <h3 className="mb-1 text-[13px] font-medium text-ink">{t('write.chat.deleteMode.confirmTitle')}</h3>
            <p className="mb-3 text-[13px] text-ink-2">{interruptPayload.entity_name}</p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                data-testid="delete-confirm-cancel"
                className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 hover:bg-surface-3"
                onClick={() => void onCancel()}
              >
                {t('write.chat.deleteMode.cancel')}
              </button>
              <button
                type="button"
                data-testid="delete-confirm-approve"
                className="rounded-md bg-accent px-3 py-1 text-[12px] text-accent-ink hover:bg-accent-hover"
                onClick={() => void onApprove()}
              >
                {t('write.chat.deleteMode.confirmDelete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
