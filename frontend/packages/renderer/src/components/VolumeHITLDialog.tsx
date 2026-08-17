/**
 * 卷级 HITL 确认对话框（F44 阶段3 #337）：waiting_hitl 时弹出，
 * 卷边界 approve/reject；卷失败 continue/abort/supervisor（镜像 CLI book confirm 语义）。
 */
import { useI18n } from '../i18n/useI18n';
import { useBookStore } from '../stores/book';

export function VolumeHITLDialog() {
  const { t } = useI18n();
  const waitingHitl = useBookStore((s) => s.waitingHitl);
  const hitlPayload = useBookStore((s) => s.hitlPayload);
  const confirming = useBookStore((s) => s.confirming);
  const confirmRun = useBookStore((s) => s.confirmRun);

  if (!waitingHitl || hitlPayload === null) return null;
  const isFailure = hitlPayload.failed !== undefined;

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={hitlPayload.question}
        data-testid="volume-hitl-dialog"
        className="w-[520px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <p data-testid="volume-hitl-question" className="font-serif text-[16px] font-semibold">
          {hitlPayload.question}
        </p>
        {isFailure ? (
          <div className="mt-4 space-y-3">
            <p className="text-[13px] text-ink-2">{t('book.hitl.failedList')}</p>
            <div data-testid="volume-hitl-failed-list" className="space-y-1">
              {(hitlPayload.failed ?? []).map((outlineId) => (
                <div
                  key={outlineId}
                  data-testid={`volume-hitl-failed-${outlineId}`}
                  className="rounded border border-err/30 bg-err/5 px-2 py-1 text-[12px] text-ink-2"
                >
                  {outlineId}
                </div>
              ))}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                data-testid="volume-hitl-continue"
                disabled={confirming}
                className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink hover:bg-accent-hover disabled:opacity-50"
                onClick={() => void confirmRun(true, 'continue')}
              >
                {t('book.hitl.continue')}
              </button>
              <button
                type="button"
                data-testid="volume-hitl-abort"
                disabled={confirming}
                className="rounded-md border border-err/40 px-4 py-1.5 text-[13px] text-err hover:bg-err/10 disabled:opacity-50"
                onClick={() => void confirmRun(false, 'abort')}
              >
                {t('book.hitl.abort')}
              </button>
              <button
                type="button"
                data-testid="volume-hitl-supervisor"
                disabled={confirming}
                className="rounded-md border border-line px-4 py-1.5 text-[13px] text-ink-2 hover:bg-surface-3 disabled:opacity-50"
                onClick={() => void confirmRun(true, 'supervisor')}
              >
                {t('book.hitl.supervisor')}
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            <div className="space-y-1">
              {Object.entries(hitlPayload.progress ?? {}).map(([outlineId, status]) => (
                <div
                  key={outlineId}
                  data-testid={`volume-hitl-progress-${outlineId}`}
                  className="rounded border border-line bg-surface-2 px-2 py-1 text-[12px] text-ink-2"
                >
                  {outlineId}: {status}
                </div>
              ))}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                data-testid="volume-hitl-approve"
                disabled={confirming}
                className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink hover:bg-accent-hover disabled:opacity-50"
                onClick={() => void confirmRun(true)}
              >
                {t('book.hitl.approve')}
              </button>
              <button
                type="button"
                data-testid="volume-hitl-reject"
                disabled={confirming}
                className="rounded-md border border-err/40 px-4 py-1.5 text-[13px] text-err hover:bg-err/10 disabled:opacity-50"
                onClick={() => void confirmRun(false)}
              >
                {t('book.hitl.reject')}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
