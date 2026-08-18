/** 设定库扁平分类通用列表（角色/伏笔；F43 P1：角色等级徽标 + 标签 chips + 行内编辑/删除，D12 悬停显示；
 *  2026-08-19 自 pages/library.tsx 机械搬移——900 行护栏 #88） */
import { Pencil, Trash2 } from 'lucide-react';
import type { LibraryItemDTO } from './LibraryCreateDialog';
import { useI18n } from '../i18n/useI18n';

export interface LibraryItemListProps {
  items: LibraryItemDTO[];
  /** characters 分类渲染等级徽标 + 标签 chips（其余分类缺省不渲染） */
  withCharacterExtras?: boolean;
  onEdit: (item: LibraryItemDTO) => void;
  onDelete: (item: LibraryItemDTO) => void;
}

export function LibraryItemList({
  items,
  withCharacterExtras = false,
  onEdit,
  onDelete,
}: LibraryItemListProps) {
  const { t } = useI18n();
  return (
    <ul
      data-testid="library-list"
      className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface shadow-card"
    >
      {items.map((item) => {
        // F43 P1（§5.1/§5.2）：角色行等级徽标 + 标签 chips（缺省不渲染）
        const rank = withCharacterExtras ? String(item.extra?.role_rank ?? '') : '';
        const groups =
          withCharacterExtras && Array.isArray(item.extra?.groups)
            ? (item.extra!.groups as unknown[]).filter((g): g is string => typeof g === 'string')
            : [];
        return (
          <li
            key={String(item.id)}
            className="group lib-item flex items-center gap-3 px-4 py-2.5 text-[13px] text-ink"
          >
            <span className="min-w-0 flex-1 truncate">{item.title ?? item.name ?? ''}</span>
            {rank !== '' && (
              <span
                data-testid={`lib-rank-${item.id}`}
                className="shrink-0 rounded-full bg-accent/10 px-2 py-0.5 text-[11px] text-accent"
              >
                {t(`lib.rank.${rank}`)}
              </span>
            )}
            {groups.length > 0 && (
              <div data-testid={`lib-tags-${item.id}`} className="flex shrink-0 items-center gap-1">
                {groups.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
            {/* F43 §5.1（D12）：悬停显示操作按钮；focus-within 保证键盘可达可见 */}
            <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
              <button
                type="button"
                data-testid={`lib-edit-${item.id}`}
                aria-label={`${t('lib.edit')} ${item.title ?? item.name ?? ''}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => onEdit(item)}
              >
                <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              <button
                type="button"
                data-testid={`lib-delete-${item.id}`}
                aria-label={`${t('lib.delete')} ${item.title ?? item.name ?? ''}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => onDelete(item)}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
