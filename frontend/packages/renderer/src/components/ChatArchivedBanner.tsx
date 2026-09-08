/**
 * #1015 归档 AI 对话只读加载（N14/N15）：横幅 + 状态 hook。
 * - useArchivedConversation：conversationId 非空 → fetchChatConversations(
 *   { projectId, includeDeleted: true }) 本地查 is_deleted（失败/查不到 → 保守按活动处理）；
 * - ChatArchivedBanner：提示「仅查看」+ 恢复入口。
 */
import { useEffect, useState } from 'react';
import { fetchChatConversations, restoreChatConversation } from '../api/chat';
import { errorMessage } from '../api/client';
import { tStatic, useI18n } from '../i18n/useI18n';
import { useToastStore } from '../stores/toast';

/** 查询指定会话归档态并暴露恢复动作（成功本地解除归档 + ok toast） */
export function useArchivedConversation(
  projectId: string,
  conversationId: string | null,
  onRestored: () => void,
): { archived: boolean; restore: () => void } {
  const [archived, setArchived] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setArchived(false);
    if (!conversationId) return;
    fetchChatConversations({ projectId, includeDeleted: true })
      .then((res) => {
        if (!cancelled) {
          setArchived(
            res.items.find((c) => c.conversation_id === conversationId)?.is_deleted ?? false,
          );
        }
      })
      .catch(() => {
        // 查询失败：保守按活动会话处理（不阻塞消息加载）
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, conversationId]);

  const restore = (): void => {
    if (!conversationId) return;
    void restoreChatConversation(conversationId)
      .then(() => {
        setArchived(false);
        useToastStore.getState().pushToast('ok', tStatic('sessions.restoredToast'));
        onRestored();
      })
      .catch((err) => {
        useToastStore.getState().pushToast('err', errorMessage(err));
      });
  };

  return { archived, restore };
}

/** 归档横幅：仅查看提示 + 恢复按钮（点击交 ChatPanel restoreFromBanner） */
export function ChatArchivedBanner({ onRestore }: { onRestore: () => void }) {
  const { t } = useI18n();
  return (
    <div
      data-testid="chat-archived-banner"
      role="status"
      className="flex items-center gap-3 rounded-md border border-line bg-surface px-3 py-2 text-[13px]"
    >
      <span className="flex-1 text-ink-2">{t('write.chat.archivedBanner')}</span>
      <button
        type="button"
        data-testid="chat-archived-restore"
        className="rounded-md border border-line bg-surface px-3 py-1 text-[12px] text-ink-2 transition-colors hover:bg-surface-3 hover:text-ink"
        onClick={onRestore}
      >
        {t('sessions.restore')}
      </button>
    </div>
  );
}
