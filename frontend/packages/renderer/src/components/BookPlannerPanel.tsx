/** 书级编排访谈单面板（F44 阶段1）：one-liner 启动 → 轮次问题/模板 → 计划 → 委托运行面板 */
import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useBookLimits, type BookLimitsValues } from '../hooks/useBookLimits';
import { useBookStore } from '../stores/book';
import { ensureModelReady } from '../stores/models';
import { useProjectStore } from '../stores/project';
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
  const messages = useBookStore((s) => s.messages);
  const error = useBookStore((s) => s.error);
  const writingPlan = useBookStore((s) => s.writingPlan);
  const runId = useBookStore((s) => s.runId);
  const projects = useProjectStore((s) => s.projects);
  const startPlanner = useBookStore((s) => s.startPlanner);
  const respond = useBookStore((s) => s.respond);
  const respondAuto = useBookStore((s) => s.respondAuto);
  const respondConfirm = useBookStore((s) => s.respondConfirm);
  const startRun = useBookStore((s) => s.startRun);

  const [oneLiner, setOneLiner] = useState('');
  const [answer, setAnswer] = useState('');
  /** #544：独立项目选择（初始 = 传入 prop；切换不联动 useProjectStore.currentProjectId） */
  const [selectedProjectId, setSelectedProjectId] = useState(projectId);
  /** #544：起点模板（new 默认 / continue 续写 / branch 分支） */
  const [startMode, setStartMode] = useState<'new' | 'continue' | 'branch'>('new');
  /** #544：选中源大纲 id（'' = 未选；仅 continue/branch 生效） */
  const [sourceOutlineId, setSourceOutlineId] = useState('');
  const [outlines, setOutlines] = useState<Array<{ id: string; name: string }>>([]);
  /** F44 v1.2 #475：确认卡片修改编辑态（key + 新值） */
  const [editKey, setEditKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');

  /** #544：continue/branch 时拉取选中项目的大纲列表（切换项目/模板重拉；new 隐藏不拉） */
  useEffect(() => {
    if (startMode === 'new') {
      setOutlines([]);
      setSourceOutlineId('');
      return;
    }
    let cancelled = false;
    setSourceOutlineId('');
    void apiFetch<{ items: Array<{ id: string; name: string }> }>(
      `/api/v1/projects/${selectedProjectId}/outlines`,
    )
      .then((data) => {
        if (!cancelled) setOutlines(data.items);
      })
      .catch(() => {
        // 拉取失败仅清空选项（未选时 start 不传 source_outline_id，不阻塞启动）
        if (!cancelled) setOutlines([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedProjectId, startMode]);

  const handleStart = async () => {
    const text = oneLiner.trim();
    if (!text) return;
    // #474 P0：模型未配置前置校验（startPlanner 前）
    if (!(await ensureModelReady())) {
      useToastStore.getState().pushToast('warn', t('common.modelNotConfigured'));
      return;
    }
    // #544：恒传 4 参——new 无源大纲传 null；continue/branch 传选中源大纲 id（未选 null）
    void startPlanner(
      selectedProjectId,
      text,
      startMode,
      startMode === 'new' ? null : sourceOutlineId || null,
    );
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

  /** 进入修改编辑态：从空值开始输入（提交回问 answers 键 = 确定项 key） */
  const startEdit = (key: string) => {
    setEditKey(key);
    setEditValue('');
  };

  /** 提交修改：respond({key: 新值}) 回 questioning 重问，随后清空编辑态 */
  const submitEdit = () => {
    if (editKey === null) return;
    const text = editValue.trim();
    if (!text) return;
    void respond({ [editKey]: text });
    setEditKey(null);
    setEditValue('');
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
          <div className="flex flex-wrap items-center gap-2">
            <select
              data-testid="book-project-select"
              className="rounded-md border border-line bg-surface px-2 py-1 text-[13px] text-ink outline-none focus:border-accent"
              value={selectedProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <select
              data-testid="book-start-mode"
              className="rounded-md border border-line bg-surface px-2 py-1 text-[13px] text-ink outline-none focus:border-accent"
              value={startMode}
              onChange={(e) => setStartMode(e.target.value as 'new' | 'continue' | 'branch')}
            >
              <option value="new">{t('book.startMode.new')}</option>
              <option value="continue">{t('book.startMode.continue')}</option>
              <option value="branch">{t('book.startMode.branch')}</option>
            </select>
            {startMode !== 'new' && (
              <select
                data-testid="book-source-outline"
                className="rounded-md border border-line bg-surface px-2 py-1 text-[13px] text-ink outline-none focus:border-accent"
                value={sourceOutlineId}
                onChange={(e) => setSourceOutlineId(e.target.value)}
              >
                <option value="">{t('book.startMode.selectOutline')}</option>
                {outlines.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            )}
          </div>
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
          {/* F44 v1.2 #475：对话式消息流（spec §5.1 PR-2；user 消息 + assistant 问题 + 确认卡片） */}
          <div data-testid="book-msg-list" className="space-y-3">
            {messages.map((m, index) => {
              if (m.role === 'user') {
                return (
                  <div
                    key={m.id}
                    data-testid={`book-msg-user-${index}`}
                    className="rounded-md bg-surface px-3 py-2 text-[13px] text-ink"
                  >
                    {m.text}
                  </div>
                );
              }
              if (m.kind === 'question') {
                const isConflict = m.questionKind === 'conflict';
                return (
                  <div
                    key={m.id}
                    data-testid={isConflict ? `book-msg-conflict-${m.questionId}` : undefined}
                    className={
                      isConflict
                        ? 'rounded-md border border-err/40 bg-err/10 px-3 py-2'
                        : 'rounded-md bg-surface px-3 py-2'
                    }
                  >
                    <p data-testid={`book-question-${m.questionId}`} className="text-[13px] text-ink">
                      {m.text}
                    </p>
                    {isConflict && (
                      <span className="mt-1 inline-block text-[12px] text-err">{t('book.conflict.label')}</span>
                    )}
                    <button
                      type="button"
                      data-testid={`book-template-${m.questionId}`}
                      className="mt-1 rounded-md border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
                      onClick={() => handleTemplate(m.template ?? '')}
                    >
                      {t('book.template.copy')}
                    </button>
                  </div>
                );
              }
              if (m.kind === 'confirm_summary') {
                return (
                  <div
                    key={m.id}
                    data-testid="book-confirm-card"
                    className="rounded-md border border-accent/40 bg-accent-weak px-3 py-2"
                  >
                    <p className="text-[13px] font-medium text-ink">{m.text || t('book.confirm.title')}</p>
                    <ul className="mt-2 space-y-1">
                      {m.confirmedItems?.map((item) => (
                        <li
                          key={item.key}
                          data-testid={`book-confirm-item-${item.key}`}
                          className="text-[13px] text-ink-2"
                        >
                          {item.key}：{item.value}
                        </li>
                      ))}
                    </ul>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        data-testid="book-confirm-ok"
                        className="rounded-md bg-accent px-3 py-1 text-[12px] text-accent-ink hover:bg-accent-hover"
                        onClick={() => void respondConfirm()}
                      >
                        {t('book.confirm.ok')}
                      </button>
                      {m.confirmedItems?.map((item) => (
                        <button
                          key={item.key}
                          type="button"
                          data-testid={`book-confirm-edit-${item.key}`}
                          className="rounded-md border border-line px-2 py-1 text-[12px] text-ink-2 hover:bg-surface-3"
                          onClick={() => startEdit(item.key)}
                        >
                          {t('book.confirm.edit')}
                        </button>
                      ))}
                    </div>
                    {editKey !== null && (
                      <div className="mt-2 flex items-center gap-2">
                        <input
                          data-testid={`book-confirm-edit-input-${editKey}`}
                          className="flex-1 rounded-md border border-line bg-surface px-2 py-1 text-[13px] text-ink outline-none focus:border-accent"
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                        />
                        <button
                          type="button"
                          data-testid={`book-confirm-edit-submit-${editKey}`}
                          className="rounded-md bg-accent px-3 py-1 text-[12px] text-accent-ink hover:bg-accent-hover"
                          onClick={submitEdit}
                        >
                          {t('book.confirm.editSubmit')}
                        </button>
                      </div>
                    )}
                  </div>
                );
              }
              return null;
            })}
          </div>

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
