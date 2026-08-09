/** F34 章节审计报告弹层（Issue #208，spec §8.1 Q3=C 前端最小版）：
 * 加载 / 错误 / 报告三态 + accept/reject 确认闭环；
 * findings 按 severity 分组（error → warning → info），样式沿用 NewProjectDialog 弹层 token。
 */
import { useEffect, useState, type JSX } from 'react';
import { useI18n } from '../i18n/useI18n';

/** 单条审计发现（对齐 ChapterAuditFinding 的 model_dump(mode='json')） */
export interface AuditFindingView {
  check_type: string;
  severity: 'info' | 'warning' | 'error';
  message: string;
  suggestion?: string;
  ref_entity_name?: string;
  context?: string;
}

/** 章节审计报告（对齐 ChapterAuditReport 的 model_dump(mode='json')） */
export interface AuditReportView {
  chapter_id: string;
  chapter_title: string;
  status: 'pending' | 'accepted' | 'rejected';
  findings: AuditFindingView[];
  summary: string;
  degraded: boolean;
  created_at: string;
  confirmed_at: string | null;
}

export interface AuditDialogProps {
  open: boolean;
  report: AuditReportView | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (action: 'accept' | 'reject', note: string) => void;
  confirming: boolean;
}

const SEVERITY_ORDER = ['error', 'warning', 'info'] as const;
type Severity = AuditFindingView['severity'];

export function AuditDialog({
  open,
  report,
  loading,
  error,
  onClose,
  onConfirm,
  confirming,
}: AuditDialogProps): JSX.Element | null {
  const { t } = useI18n();
  // 拒绝备注：首次点击「拒绝」展开输入框，再次点击携带输入值确认
  const [showNote, setShowNote] = useState(false);
  const [note, setNote] = useState('');

  // 报告切换（新审计 / 关闭后重开）时重置备注交互态，避免残留上轮输入
  useEffect(() => {
    setShowNote(false);
    setNote('');
  }, [report]);

  if (!open) return null;

  const severityTitle = (severity: Severity): string => {
    if (severity === 'error') return t('audit.severity.error');
    if (severity === 'warning') return t('audit.severity.warning');
    return t('audit.severity.info');
  };

  const handleReject = () => {
    if (!showNote) {
      setShowNote(true);
      return;
    }
    onConfirm('reject', note);
  };

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={report ? report.chapter_title : t('audit.errorTitle')}
        className="max-h-[80vh] w-[560px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        {loading && !report ? (
          <div
            data-testid="audit-dialog-loading"
            className="py-8 text-center text-sm text-ink-2"
          >
            {t('audit.loading')}
          </div>
        ) : !report && error ? (
          <div data-testid="audit-dialog-error">
            <h2 className="font-serif text-[18px] font-semibold">{t('audit.errorTitle')}</h2>
            <p className="mt-3 text-[13px] text-err">{error}</p>
            <div className="mt-6 flex justify-end">
              <button
                type="button"
                className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
                onClick={onClose}
              >
                {t('audit.close')}
              </button>
            </div>
          </div>
        ) : report ? (
          <>
            <h2 className="font-serif text-[18px] font-semibold">{report.chapter_title}</h2>
            {error && (
              <p data-testid="audit-dialog-error" className="mt-2 text-[13px] text-err">
                {error}
              </p>
            )}
            {report.degraded && (
              <p className="mt-2 text-[12px] text-ink-3">{t('audit.degraded')}</p>
            )}
            <div className="mt-4 space-y-4">
              {SEVERITY_ORDER.map((severity) => {
                const group = report.findings.filter((f) => f.severity === severity);
                if (group.length === 0) return null;
                return (
                  <section key={severity} className="space-y-2">
                    <h3 className="text-[13px] font-medium text-ink-2">{severityTitle(severity)}</h3>
                    {group.map((finding, i) => (
                      <div
                        key={`${severity}-${i}`}
                        className="rounded-md border border-line bg-surface-2 p-3"
                      >
                        <p className="text-[13px] text-ink">{finding.message}</p>
                        {finding.suggestion ? (
                          <p className="mt-1 text-[12px] text-ink-2">{finding.suggestion}</p>
                        ) : null}
                        {finding.ref_entity_name ? (
                          <p className="mt-1 text-[12px] text-ink-3">
                            {t('audit.related')}：{finding.ref_entity_name}
                          </p>
                        ) : null}
                      </div>
                    ))}
                  </section>
                );
              })}
            </div>
            <p className="mt-4 text-[13px] text-ink-2">{report.summary}</p>
            {showNote && (
              <textarea
                data-testid="audit-note-input"
                className="mt-3 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
                placeholder={t('audit.notePlaceholder')}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            )}
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
                onClick={onClose}
              >
                {t('audit.close')}
              </button>
              <button
                type="button"
                disabled={confirming}
                className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3 disabled:opacity-40"
                onClick={() => onConfirm('accept', '')}
              >
                {t('audit.accept')}
              </button>
              <button
                type="button"
                disabled={confirming}
                className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:opacity-40"
                onClick={handleReject}
              >
                {t('audit.reject')}
              </button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
