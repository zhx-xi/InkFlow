/**
 * 首次授权弹框（#598 D9-a1）：触发全自动（agentic）写作时检测到未授权（
 * auto_write_enabled=false）弹出；确认 → PATCH config 开启开关并关闭，取消 → 仅关闭。
 * 视觉镜像 VolumeHITLDialog（fixed inset 遮罩 + dialog card + title + 说明 + 确认/取消）。
 */
import { useI18n } from '../i18n/useI18n';
import { useProjectStore } from '../stores/project';

interface AutoAuthorizationDialogProps {
  /** 目标项目 id（开关写入该项目 config.auto_write_enabled） */
  projectId: string;
  /** 是否显示（由父级在首次触发全自动且未授权时置 true） */
  open: boolean;
  onClose: () => void;
}

export function AutoAuthorizationDialog({
  projectId,
  open,
  onClose,
}: AutoAuthorizationDialogProps) {
  const { t } = useI18n();

  if (!open) return null;

  const handleConfirm = () => {
    void useProjectStore.getState().updateConfig(projectId, { auto_write_enabled: true });
    onClose();
  };

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('write.autoAuth.title')}
        data-testid="auto-auth-dialog"
        className="w-[520px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="font-serif text-[16px] font-semibold">{t('write.autoAuth.title')}</p>
        <p className="mt-3 text-[13px] text-ink-2">{t('write.autoAuth.body')}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            data-testid="auto-auth-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-[13px] text-ink-2 hover:bg-surface-3"
            onClick={onClose}
          >
            {t('write.autoAuth.cancel')}
          </button>
          <button
            type="button"
            data-testid="auto-auth-confirm"
            className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink hover:bg-accent-hover"
            onClick={handleConfirm}
          >
            {t('write.autoAuth.confirm')}
          </button>
        </div>
      </div>
    </div>
  );
}
