/** T2 风格检测（Issue #655）：风格分析报告弹层。
 * 加载 / 错误 / 报告三态（镜像 AuditDialog），样式沿用弹层 token。
 */
import { type JSX } from 'react';
import { type StyleReportDto } from '../api/style';
import { useI18n } from '../i18n/useI18n';

export type { StyleReportDto };

export interface StyleAnalyzeDialogProps {
  open: boolean;
  report: StyleReportDto | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

export function StyleAnalyzeDialog({
  open,
  report,
  loading,
  error,
  onClose,
}: StyleAnalyzeDialogProps): JSX.Element | null {
  const { t } = useI18n();

  if (!open) return null;

  const verdictText = (verdict: StyleReportDto['ai_trace']['verdict']): string => {
    if (verdict === 'likely_human') return t('write.style.verdict.human');
    if (verdict === 'uncertain') return t('write.style.verdict.uncertain');
    return t('write.style.verdict.ai');
  };

  return (
    <div
      role="presentation"
      data-testid="style-analyze-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('write.style.title')}
        className="max-h-[80vh] w-[560px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        {loading && !report ? (
          <div
            data-testid="style-dialog-loading"
            className="py-8 text-center text-sm text-ink-2"
          >
            {t('write.style.loading')}
          </div>
        ) : !report && error ? (
          <div data-testid="style-dialog-error">
            <h2 className="font-serif text-[18px] font-semibold">{t('write.style.error')}</h2>
            <p className="mt-3 text-[13px] text-err">{error}</p>
            <div className="mt-6 flex justify-end">
              <button
                type="button"
                className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
                onClick={onClose}
              >
                {t('write.style.close')}
              </button>
            </div>
          </div>
        ) : report ? (
          <div data-testid="style-dialog-report">
            <h2 className="font-serif text-[18px] font-semibold">{t('write.style.title')}</h2>
            <section data-testid="style-fingerprint" className="mt-4 space-y-2">
              <h3 className="text-[13px] font-medium text-ink-2">{t('write.style.fingerprint')}</h3>
              <p data-testid="style-fp-sentence">
                {t('write.style.fpSentence')}：{report.fingerprint.sentence_avg_len}
              </p>
              <p data-testid="style-fp-paragraph">
                {t('write.style.fpParagraph')}：{report.fingerprint.paragraph_avg_len}
              </p>
              <p data-testid="style-fp-dialogue">
                {t('write.style.fpDialogue')}：{report.fingerprint.dialogue_ratio}
              </p>
              <p data-testid="style-fp-vocab">
                {t('write.style.fpVocab')}：{report.fingerprint.vocabulary_richness}
              </p>
              <h4 className="text-[12px] font-medium text-ink-3">{t('write.style.topWords')}</h4>
              <ul className="list-inside list-disc space-y-0.5 text-[13px] text-ink">
                {report.fingerprint.top_words.map(({ word, count }) => (
                  <li key={word}>
                    <span>{word}</span> × {count}
                  </li>
                ))}
              </ul>
            </section>
            <section data-testid="style-ai-trace" className="mt-4 space-y-2">
              <h3 className="text-[13px] font-medium text-ink-2">{t('write.style.aiTrace')}</h3>
              <p data-testid="style-ai-score">
                {t('write.style.aiScore')}：{report.ai_trace.ai_score}
              </p>
              <p data-testid="style-verdict">
                {t('write.style.verdictLabel')}：{verdictText(report.ai_trace.verdict)}
              </p>
              <h4 className="text-[12px] font-medium text-ink-3">{t('write.style.evidence')}</h4>
              <ul className="list-inside list-disc space-y-0.5 text-[13px] text-ink">
                {report.ai_trace.evidence.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </section>
            <section data-testid="style-lexical" className="mt-4 space-y-2">
              <h3 className="text-[13px] font-medium text-ink-2">{t('write.style.lexical')}</h3>
              <p data-testid="style-lex-unique">
                {t('write.style.lexUnique')}：{report.lexical.unique_words}
              </p>
              <p data-testid="style-lex-total">
                {t('write.style.lexTotal')}：{report.lexical.total_words}
              </p>
              <p data-testid="style-lex-stopword">
                {t('write.style.lexStopword')}：{report.lexical.stopword_ratio}
              </p>
            </section>
            <div className="mt-6 flex justify-end">
              <button
                type="button"
                data-testid="style-dialog-close"
                className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
                onClick={onClose}
              >
                {t('write.style.close')}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
