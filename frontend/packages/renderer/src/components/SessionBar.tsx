/** 左侧独立会话栏（#762）：按 updated_at 分桶 today/week/earlier，折叠状态持久化 localStorage */
import { useEffect, useMemo, useState } from 'react';
import { ChevronsDown, ChevronsUp } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { fetchChatConversations, type ChatConversationDto } from '../api/chat';
import { useI18n } from '../i18n/useI18n';
import { useChapterStore } from '../stores/chapter';

const COLLAPSE_KEY = 'session-bar.collapsed';

/** updated_at -> 本地日期分桶：today（当日）/ week（近 7 天内非今日）/ earlier（更早） */
function bucketOf(isoDate: string): 'today' | 'week' | 'earlier' {
  const d = new Date(isoDate);
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) return 'today';
  const dayMs = 24 * 60 * 60 * 1000;
  if (now.getTime() - d.getTime() < 7 * dayMs) return 'week';
  return 'earlier';
}

/** 短时间展示：当日 HH:mm，更早 MM-DD HH:mm（契约未约束格式） */
function shortDate(isoDate: string): string {
  const d = new Date(isoDate);
  const pad = (n: number) => String(n).padStart(2, '0');
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  return sameDay ? hm : `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`;
}

export function SessionBar({ projectId }: { projectId?: string | null }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  // #770：章节锚点 = 会话 title 匹配当前项目章节标题（匹配 → 章节页；否则 → 全局 chat 页）
  const chapters = useChapterStore((s) => s.chapters);
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === 'true',
  );
  const [items, setItems] = useState<ChatConversationDto[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchChatConversations({
      includeDeleted: true,
      ...(projectId ? { projectId } : {}),
    })
      .then((res) => {
        if (!cancelled) setItems(res.items);
      })
      .catch(() => {
        if (!cancelled) setItems([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const groups = useMemo(() => {
    const buckets: Record<'today' | 'week' | 'earlier', ChatConversationDto[]> = {
      today: [],
      week: [],
      earlier: [],
    };
    for (const item of items) {
      buckets[bucketOf(item.updated_at)].push(item);
    }
    for (const key of ['today', 'week', 'earlier'] as const) {
      buckets[key].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    }
    return buckets;
  }, [items]);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem(COLLAPSE_KEY, next ? 'true' : 'false');
      return next;
    });
  };

  return (
    <aside
      data-testid="session-bar"
      data-collapsed={collapsed ? 'true' : undefined}
      className="flex min-h-0 flex-col gap-1 px-2"
    >
      <div data-testid="session-bar-header" className="flex items-center justify-between">
        <span className="truncate text-[10px] font-medium uppercase tracking-[0.14em] text-ink-3">
          {t('nav.group.sessions')}
        </span>
        <button
          type="button"
          data-testid="session-bar-toggle"
          aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
          className="rounded p-0.5 text-ink-3 transition-colors duration-180 hover:bg-surface-3 hover:text-ink"
          onClick={toggleCollapsed}
        >
          {collapsed ? (
            <ChevronsDown className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <ChevronsUp className="h-3.5 w-3.5" aria-hidden="true" />
          )}
        </button>
      </div>

      {!collapsed && (
        <div className="min-h-0 space-y-0.5">
          {loading && items.length === 0 ? null : items.length === 0 ? (
            <div data-testid="session-bar-empty" className="p-2 text-[12px] text-ink-3">
              {t('common.empty')}
            </div>
          ) : (
            (['today', 'week', 'earlier'] as const).map((bucket) => {
              const bucketItems = groups[bucket];
              if (bucketItems.length === 0) return null;
              return (
                <div key={bucket} data-testid={`session-time-${bucket}`} className="mt-1 space-y-0.5">
                  <div className="text-[10px] uppercase tracking-[0.14em] text-ink-3">
                    {t(`session.time.${bucket}`)}
                  </div>
                  {bucketItems.map((conv) => {
                    const match = chapters.find((c) => c.title === conv.title);
                    return (
                      <button
                        key={conv.conversation_id}
                        type="button"
                        data-testid={`session-item-${conv.conversation_id}`}
                        onClick={() =>
                          match
                            ? navigate(`/writing?chapter_id=${match.id}`)
                            : navigate(`/writing?conversation_id=${conv.conversation_id}`)
                        }
                        className="flex w-full flex-col items-start rounded-md px-2 py-1.5 text-left text-[12px] text-ink-2 hover:bg-surface-3 hover:text-ink"
                      >
                        {/* #770：优先展示会话 title（章节锚点），空则回退 last_message */}
                        {/* #770：优先展示会话 title（章节锚点），空则回退 last_message；
                            title 非空时 last_message 仍展示为副行（#762 契约保留） */}
                        <span className="min-w-0 flex-1 truncate">
                          {conv.title || conv.last_message || t('common.empty')}
                        </span>
                        {conv.title && conv.last_message ? (
                          <span className="truncate text-[11px] text-ink-3">{conv.last_message}</span>
                        ) : null}
                        <span className="text-ink-3">
                          {t('session.messages', { count: conv.message_count })} · {shortDate(conv.updated_at)}
                        </span>
                        {conv.is_deleted && (
                          <span data-testid="session-item-archived" className="text-ink-3">
                            {t('session.archived')}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              );
            })
          )}
        </div>
      )}
    </aside>
  );
}
