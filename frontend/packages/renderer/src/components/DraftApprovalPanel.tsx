/**
 * 草稿审批面板（Issue #653）：写作页右栏挂载，展示项目待审批 AI 草稿。
 * 挂载时 projectId 非空 → listDrafts 加载；确认/驳回/编辑保存成功后重新加载列表
 * （刷新闭环）；顶部「清理孤儿」触发 pruneOrphans() 后同样刷新。
 */
import { useCallback, useEffect, useState } from 'react';
import { confirmDraft, listDrafts, pruneOrphans, rejectDraft, updateDraft, type DraftDto } from '../api/drafts';
import { errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';

export function DraftApprovalPanel({ projectId }: { projectId: string | null }) {
  const { t } = useI18n();
  const [drafts, setDrafts] = useState<DraftDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editValue, setEditValue] = useState('');

  const load = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await listDrafts(projectId);
      setDrafts(result.items);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  // 挂载 / projectId 变化 → 自动加载；null 守卫不发请求
  useEffect(() => {
    if (projectId) {
      void load();
    }
  }, [projectId, load]);

  const handleConfirm = async (draft: DraftDto): Promise<void> => {
    try {
      await confirmDraft(draft.id);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleReject = async (draft: DraftDto): Promise<void> => {
    try {
      await rejectDraft(draft.id);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handlePrune = async (): Promise<void> => {
    try {
      await pruneOrphans();
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleEditSave = async (draft: DraftDto): Promise<void> => {
    try {
      await updateDraft(draft.id, editValue);
      setEditingIndex(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <aside
      data-testid="draft-approval-panel"
      className="flex min-h-0 flex-col border-t border-line"
    >
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="text-[13px] font-semibold">{t('write.drafts.title')}</span>
        <button
          type="button"
          data-testid="draft-prune"
          className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
          onClick={() => void handlePrune()}
        >
          {t('write.drafts.prune')}
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {loading && drafts.length === 0 ? (
          <div
            data-testid="draft-loading"
            className="rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-3"
          >
            {t('write.drafts.loading')}
          </div>
        ) : error !== null && drafts.length === 0 ? (
          <div
            data-testid="draft-error"
            className="rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-3"
          >
            {t('write.drafts.error')}: {error}
          </div>
        ) : drafts.length === 0 ? (
          <div
            data-testid="draft-empty"
            className="rounded-md border border-line bg-surface p-3 text-[12px] leading-relaxed text-ink-3"
          >
            {t('write.drafts.empty')}
          </div>
        ) : (
          drafts.map((draft, index) => (
            <section
              key={draft.id}
              data-testid={`draft-item-${index}`}
              className="rounded-md border border-line bg-surface p-3"
            >
              <div data-testid={`draft-title-${index}`} className="text-[13px] font-medium">
                {draft.summary}
              </div>
              <div
                data-testid={`draft-content-${index}`}
                className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed text-ink-2"
              >
                {draft.content}
              </div>
              {editingIndex === index ? (
                <div className="mt-2 space-y-2">
                  <textarea
                    data-testid={`draft-edit-input-${index}`}
                    value={editValue}
                    onChange={(event) => setEditValue(event.target.value)}
                    rows={5}
                    className="w-full rounded border border-line bg-surface-2 p-2 text-[12px]"
                  />
                  <button
                    type="button"
                    data-testid={`draft-edit-save-${index}`}
                    className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
                    onClick={() => void handleEditSave(draft)}
                  >
                    {t('write.drafts.save')}
                  </button>
                </div>
              ) : (
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    data-testid={`draft-confirm-${index}`}
                    className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
                    onClick={() => void handleConfirm(draft)}
                  >
                    {t('write.drafts.confirm')}
                  </button>
                  <button
                    type="button"
                    data-testid={`draft-reject-${index}`}
                    className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
                    onClick={() => void handleReject(draft)}
                  >
                    {t('write.drafts.reject')}
                  </button>
                  <button
                    type="button"
                    data-testid={`draft-edit-${index}`}
                    className="rounded border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
                    onClick={() => {
                      setEditingIndex(index);
                      setEditValue(draft.content);
                    }}
                  >
                    {t('write.drafts.edit')}
                  </button>
                </div>
              )}
            </section>
          ))
        )}
      </div>
    </aside>
  );
}
