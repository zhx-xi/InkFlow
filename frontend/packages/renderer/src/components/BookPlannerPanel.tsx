/** 书级编排访谈单面板（F44 阶段1）：one-liner 启动 → 轮次问题/模板 → 计划 → 委托运行面板 */
import { useState } from 'react';
import { useI18n } from '../i18n/useI18n';
import { useBookLimits, type BookLimitsValues } from '../hooks/useBookLimits';
import { useBookStore } from '../stores/book';
import { ensureModelReady } from '../stores/models';
import { useToastStore } from '../stores/toast';
import { BookRunPanel } from './BookRunPanel';

export interface BookPlannerPanelProps {
  projectId: string;
}

export function BookPlannerPanel({ projectId }: BookPlannerPanelProps) {
  const { t } = useI18n();
  const limits = useBookLimits(projectId);
  const sessionStatus = useBookStore((s) => s.sessionStatus);
  const questions = useBookStore((s) => s.questions);
  const answers = useBookStore((s) => s.answers);
  const error = useBookStore((s) => s.error);
  const writingPlan = useBookStore((s) => s.writingPlan);
  const runId = useBookStore((s) => s.runId);
  const startPlanner = useBookStore((s) => s.startPlanner);
  const respond = useBookStore((s) => s.respond);
  const respondAuto = useBookStore((s) => s.respondAuto);
  const startRun = useBookStore((s) => s.startRun);

  const [oneLiner, setOneLiner] = useState('');
  const [answer, setAnswer] = useState('');

  const handleStart = async () => {
    const text = oneLiner.trim();
    if (!text) return;
    // #474 P0：模型未配置前置校验（startPlanner 前）
    if (!(await ensureModelReady())) {
      useToastStore.getState().pushToast('warn', t('common.modelNotConfigured'));
      return;
    }
    void startPlanner(projectId, text);
  };

  const handleSend = () => {
    const text = answer.trim();
    if (!text) return;
    // 契约：发送键 = 当前轮第一个未答问题 id（answers 已答快照驱动）
    const qid = questions.find((q) => !answers[q.id])?.id ?? questions[0]?.id;
    if (!qid) return;
    void respond({ [qid]: text });
    setAnswer('');
  };

  const handleTemplate = (template: string) => {
    setAnswer(template);
  };

  const canSend = answer.trim() !== '';
  const showStart = sessionStatus === 'idle' || sessionStatus === 'drafting';

  /** 数字输入显示值：null → 空串；数字 → 字符串 */
  const inputValue = (value: number | null): string => (value === null ? '' : String(value));

  const limitFields: Array<{
    testId: string;
    field: keyof BookLimitsValues;
    label: string;
  }> = [
    { testId: 'book-limits-chapters', field: 'max_chapters', label: t('book.limits.chapters') },
    { testId: 'book-limits-calls', field: 'max_agent_calls', label: t('book.limits.calls') },
    { testId: 'book-limits-tokens', field: 'max_tokens', label: t('book.limits.tokens') },
    { testId: 'book-limits-sessions', field: 'max_sessions', label: t('book.limits.sessions') },
  ];

  if (sessionStatus === 'completed') {
    return (
      <div data-testid="book-planner-panel" className="space-y-3">
        {runId !== null ? (
          <BookRunPanel />
        ) : writingPlan !== null ? (
          <div className="rounded-md border border-line bg-surface-2 p-3">
            <p data-testid="book-plan-title" className="text-[14px] font-medium text-ink">
              {writingPlan.title}
            </p>
            <span
              data-testid="book-plan-status"
              className="mt-1 inline-block rounded bg-accent-weak px-1.5 py-0.5 text-[12px] text-accent"
            >
              {writingPlan.status === 'auto' ? t('book.plan.auto') : t('book.plan.ready')}
            </span>
            <div className="mt-3">
              <button
                type="button"
                data-testid="book-start-run"
                className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink hover:bg-accent-hover"
                onClick={() => void startRun(writingPlan.id)}
              >
                {t('book.startRun')}
              </button>
            </div>
            <div className="mt-4 space-y-2">
              <p className="text-[13px] font-medium text-ink">{t('book.limits.title')}</p>
              <div className="grid grid-cols-2 gap-2">
                {limitFields.map(({ testId, field, label }) => (
                  <label key={testId} className="flex items-center gap-2 text-[12px] text-ink-2">
                    <span className="flex-1">{label}</span>
                    <input
                      data-testid={testId}
                      type="number"
                      min={0}
                      className="w-24 rounded-md border border-line bg-surface px-2 py-1 text-[13px] text-ink outline-none focus:border-accent"
                      value={inputValue(limits.values[field])}
                      onChange={(e) =>
                        limits.setValue(field, e.target.value === '' ? null : Number(e.target.value))
                      }
                    />
                  </label>
                ))}
              </div>
              <button
                type="button"
                data-testid="book-limits-save"
                disabled={limits.saving}
                className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 hover:bg-surface-3 disabled:opacity-40"
                onClick={() => void limits.save()}
              >
                {limits.saving ? t('set.saving') : t('book.limits.save')}
              </button>
            </div>
            {error && (
              <p data-testid="book-start-error" className="mt-3 text-[13px] text-err">
                {error}
              </p>
            )}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div data-testid="book-planner-panel" className="space-y-3">
      {showStart && (
        <div className="rounded-md border border-line bg-surface-2 p-3">
          <textarea
            data-testid="book-one-liner"
            className="min-h-[64px] w-full resize-none rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
            value={oneLiner}
            onChange={(e) => setOneLiner(e.target.value)}
            placeholder={t('book.oneLiner')}
            rows={2}
          />
          <div className="mt-2">
            <button
              type="button"
              data-testid="book-planner-start"
              disabled={oneLiner.trim() === ''}
              className="rounded-md bg-accent px-4 py-1.5 text-[13px] text-accent-ink hover:bg-accent-hover disabled:opacity-40"
              onClick={handleStart}
            >
              {t('book.start')}
            </button>
          </div>
        </div>
      )}

      {sessionStatus === 'drafting' && (
        <div className="rounded-md border border-line bg-surface-2 p-3">
          {questions.map((q) => (
            <div key={q.id} className="mb-3 last:mb-0">
              <p data-testid={`book-question-${q.id}`} className="text-[13px] text-ink">
                {q.text}
              </p>
              <button
                type="button"
                data-testid={`book-template-${q.id}`}
                className="mt-1 rounded-md border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
                onClick={() => handleTemplate(q.template)}
              >
                {t('book.template.copy')}
              </button>
            </div>
          ))}

          {error && (
            <p data-testid="book-planner-error" className="mt-3 text-[13px] text-err">
              {error}
            </p>
          )}

          <div className="mt-3 flex items-center gap-2">
            <textarea
              data-testid="book-answer"
              className="min-h-[40px] flex-1 resize-none rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder={t('book.answer.placeholder')}
              rows={1}
            />
            <button
              type="button"
              data-testid="book-send"
              disabled={!canSend}
              className="rounded-md bg-accent px-4 py-2 text-[13px] text-accent-ink hover:bg-accent-hover disabled:opacity-40"
              onClick={handleSend}
            >
              {t('book.send')}
            </button>
            <button
              type="button"
              data-testid="book-auto"
              className="rounded-md border border-line px-4 py-2 text-[13px] text-ink-2 hover:bg-surface-3"
              onClick={() => void respondAuto()}
            >
              {t('book.auto')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
