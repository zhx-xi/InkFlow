/** 设定库扁平分类通用列表（角色/伏笔；F43 P1：角色等级徽标 + 标签 chips + 行内编辑/删除，D12 悬停显示；
 *  2026-08-19 自 pages/library.tsx 机械搬移——900 行护栏 #88；
 *  #679：characters 分类等级选项卡（总览/分览）+ group_id 分组卡片 + 五档等级徽标分色） */
import { useState } from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import type { CharacterGroup } from '../api/character';
import type { LibraryItemDTO } from './LibraryCreateDialog';
import { useI18n } from '../i18n/useI18n';

/** #679：角色行含 group_id（后端 Character model 字段；LibraryItemDTO 未声明，此处本地补全类型） */
type LibraryItemWithGroup = LibraryItemDTO & { group_id?: string | number | null };

export interface LibraryItemListProps {
  items: LibraryItemDTO[];
  /** characters 分类渲染等级徽标 + 标签 chips（其余分类缺省不渲染） */
  withCharacterExtras?: boolean;
  /** #679：角色分组列表（characters 分类分组卡片数据源；数组顺序 = 分组渲染顺序） */
  characterGroups?: CharacterGroup[];
  onEdit: (item: LibraryItemDTO) => void;
  onDelete: (item: LibraryItemDTO) => void;
  /** #650/#651：characters 分类行名字可点击 → 打开角色详情面板（缺省保持纯 span 展示） */
  onOpenDetail?: (item: LibraryItemDTO) => void;
}

/** #679：五档等级徽标分色（映射真实 theme token；未知等级兜底中性色） */
const RANK_BADGE: Record<string, string> = {
  protagonist: 'bg-accent text-accent-ink',
  major: 'bg-accent/40 text-accent-ink',
  minor: 'bg-surface-3 text-ink-2',
  scene: 'bg-surface-2 text-ink-3',
  walkon: 'bg-surface-3 text-ink-3/60',
};

/** #679：等级选项卡激活 / 闲置样式（chip） */
const ACTIVE = 'bg-accent text-accent-ink';
const IDLE = 'bg-surface-3 text-ink-2';

export function LibraryItemList({
  items,
  withCharacterExtras = false,
  characterGroups = [],
  onEdit,
  onDelete,
  onOpenDetail,
}: LibraryItemListProps) {
  const { t } = useI18n();
  // #679：等级选项卡（'all' = 全部·总览，常驻默认项；点击当前等级不取消，需点「全部」）
  const [selectedRank, setSelectedRank] = useState<string>('all');
  // #679：等级选项卡顺序（总览 → 主角 → 重要配角 → 配角 → 场景角色 → 一次性角色）
  const RANK_OPTIONS = ['all', 'protagonist', 'major', 'minor', 'scene', 'walkon'].map((key) => ({
    key,
    label: t('lib.rank.' + key),
  }));
  // #679：分览过滤（'all' 显示全部角色）
  const visibleItems =
    selectedRank === 'all'
      ? items
      : items.filter((i) => String((i.extra as Record<string, unknown>)?.role_rank ?? '') === selectedRank);
  // #679：分组卡片（仅 characters；按 characterGroups 数组顺序，空组隐藏；未分组收尾）
  const groupSections = withCharacterExtras
    ? characterGroups
        .map((g) => ({
          group: g,
          members: visibleItems.filter((i) => String((i as LibraryItemWithGroup).group_id) === String(g.id)),
        }))
        .filter((sec) => sec.members.length > 0)
    : [];
  const ungroupedItems = withCharacterExtras
    ? visibleItems.filter((i) => {
        const groupId = (i as LibraryItemWithGroup).group_id;
        return groupId === null || groupId === undefined;
      })
    : [];

  // F43 P1（§5.1/§5.2）：角色行等级徽标 + 标签 chips（缺省不渲染）
  const renderRow = (item: LibraryItemDTO) => {
    const rank = withCharacterExtras ? String(item.extra?.role_rank ?? '') : '';
    const rankBadgeCls = RANK_BADGE[rank] ?? 'bg-surface-3 text-ink-2';
    const groups =
      withCharacterExtras && Array.isArray(item.extra?.groups)
        ? (item.extra!.groups as unknown[]).filter((g): g is string => typeof g === 'string')
        : [];
    return (
      <li
        key={String(item.id)}
        className="group lib-item flex items-center gap-3 px-4 py-2.5 text-[13px] text-ink"
      >
        {withCharacterExtras && onOpenDetail ? (
          <button
            type="button"
            data-testid={`lib-name-${item.id}`}
            title={t('lib.charDetail.open')}
            className="min-w-0 flex-1 truncate rounded text-left transition-colors duration-150 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
            onClick={() => onOpenDetail(item)}
          >
            {item.title ?? item.name ?? ''}
          </button>
        ) : (
          <span className="min-w-0 flex-1 truncate">{item.title ?? item.name ?? ''}</span>
        )}
        {rank !== '' && (
          <span
            data-testid={`lib-rank-${item.id}`}
            className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${rankBadgeCls}`}
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
  };

  if (!withCharacterExtras) {
    // 非 characters 分类：保持既有平铺 <ul> 原样
    return (
      <ul
        data-testid="library-list"
        className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface shadow-card"
      >
        {items.map((item) => renderRow(item))}
      </ul>
    );
  }

  return (
    <div
      data-testid="library-list"
      className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface shadow-card"
    >
      {/* #679：等级选项卡（总览/分览） */}
      <div data-testid="character-rank-tabs" className="flex flex-wrap gap-1 px-3 py-2">
        {RANK_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            type="button"
            data-testid={`character-rank-tab-${opt.key}`}
            aria-pressed={selectedRank === opt.key}
            className={`rounded-full px-3 py-1 text-[12px] transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selectedRank === opt.key ? ACTIVE : IDLE}`}
            onClick={() => setSelectedRank(opt.key)}
          >
            {opt.label}
          </button>
        ))}
      </div>
      {groupSections.map(({ group, members }) => (
        <section key={String(group.id)} data-testid={`lib-group-${group.id}`}>
          <div
            data-testid={`lib-group-title-${group.id}`}
            className="px-4 pt-3 pb-1.5 text-[12px] font-medium text-ink-2"
          >
            {group.name} · {group.member_count}人
          </div>
          <ul className="divide-y divide-line">{members.map((item) => renderRow(item))}</ul>
        </section>
      ))}
      {ungroupedItems.length > 0 && (
        <section data-testid="lib-group-ungrouped">
          <div
            data-testid="lib-group-ungrouped-title"
            className="px-4 pt-3 pb-1.5 text-[12px] font-medium text-ink-2"
          >
            {t('lib.charGroup.ungrouped')}
          </div>
          <ul className="divide-y divide-line">{ungroupedItems.map((item) => renderRow(item))}</ul>
        </section>
      )}
    </div>
  );
}
