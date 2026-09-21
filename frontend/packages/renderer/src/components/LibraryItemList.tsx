/** 设定库扁平分类通用列表（角色/伏笔；F43 P1：角色等级徽标 + 标签 chips + 行内编辑/删除，D12 悬停显示；
 *  2026-08-19 自 pages/library.tsx 机械搬移——900 行护栏 #88；
 *  #679：characters 分类等级选项卡（总览/分览）+ group_id 分组卡片 + 五档等级徽标分色）；
 *  #1324：foreshadow 分类行扩展（状态徽标 + 优先级 + 位置徽标，对齐 design/GUI/foreshadow/foreshadow.html） */
import { useEffect, useState } from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import { listCharacterGroups, type CharacterGroup } from '../api/character';
import type { LibraryItemDTO } from './LibraryCreateDialog';
import { useI18n } from '../i18n/useI18n';

/** #679/#701：角色行含 group_id（旧单选过渡）与 group_ids（N:M 多分组）；LibraryItemDTO 未声明，此处本地补全类型 */
type LibraryItemWithGroup = LibraryItemDTO & {
  group_id?: string | number | null;
  group_ids?: (string | number)[] | null;
};

/** #1324：伏笔行状态/回收时间；API 已返回（routers/foreshadowings.py:171 f.model_dump），DTO 未声明 */
type LibraryItemForeshadow = LibraryItemDTO & {
  status?: string;
  resolved_at?: string | null;
};

/** #701：角色归属分组 ids —— group_ids 数组优先（N:M 权威）；缺失时兜底旧单选 group_id */
const groupIdsOf = (item: LibraryItemDTO): (string | number)[] => {
  const withGroup = item as LibraryItemWithGroup;
  if (Array.isArray(withGroup.group_ids)) return withGroup.group_ids;
  return withGroup.group_id == null ? [] : [withGroup.group_id];
};

/** #1324：回收时间显示（ADR-055：存储 UTC → GUI 本地时区；仅取日期，无效值原样透传） */
const formatResolvedAt = (raw: string): string => {
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

export interface LibraryItemListProps {
  items: LibraryItemDTO[];
  /** characters 分类渲染等级徽标 + 标签 chips（其余分类缺省不渲染） */
  withCharacterExtras?: boolean;
  /** #1324：foreshadow 分类渲染状态徽标 + 优先级 + 位置徽标（缺省不渲染） */
  withForeshadowExtras?: boolean;
  /** #679：角色分组列表（characters 分类分组卡片数据源；数组顺序 = 分组渲染顺序）。可注入（测试）或经 projectId 内部拉取。 */
  characterGroups?: CharacterGroup[];
  /** #679：characters 分类内部拉取角色分组（当 characterGroups 未注入时）所需的项目 id */
  projectId?: string;
  /**
   * #1320：等级筛选的**受控值**（提供时组件不再自持 state——筛选需下沉服务端，
   * 故由页面持有并向列表请求传 ?role_rank=，total 才是筛选后口径）。
   * 未提供 → 退化为既有的非受控内部 state（组件内过滤当前页）。
   */
  rank?: string;
  /** #1320：等级筛选变更回调（受控模式必配；页面据此重拉 + 页码归零） */
  onRankChange?: (rank: string) => void;
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

/** #1324：伏笔状态徽标分色（未回收 = accent-weak，已回收 = 中性 surface-3；对齐原型 .fs-status） */
const FS_STATUS_BADGE: Record<string, string> = {
  resolved: 'bg-surface-3 text-ink-2',
  open: 'bg-accent/20 text-accent-ink',
};

/** #679：等级选项卡激活 / 闲置样式（chip） */
const ACTIVE = 'bg-accent text-accent-ink';
const IDLE = 'bg-surface-3 text-ink-2';

export function LibraryItemList({
  items,
  withCharacterExtras = false,
  withForeshadowExtras = false,
  characterGroups,
  projectId,
  rank,
  onRankChange,
  onEdit,
  onDelete,
  onOpenDetail,
}: LibraryItemListProps) {
  const { t } = useI18n();
  // #679：等级选项卡（'all' = 全部·总览，常驻默认项；点击当前等级不取消，需点「全部」）
  // #1320：受控优先（页面持有 → 筛选可下沉服务端）；未提供 rank 时保留既有非受控行为
  const [innerRank, setInnerRank] = useState<string>('all');
  const isControlled = rank !== undefined;
  const selectedRank = isControlled ? rank : innerRank;
  const selectRank = (next: string) => {
    if (!isControlled) setInnerRank(next);
    onRankChange?.(next);
  };
  // #679：- 分组数据源 = 注入的 characterGroups（测试/受控）或按 projectId 内部拉取（受控缺省）
  const [fetchedGroups, setFetchedGroups] = useState<CharacterGroup[]>([]);
  useEffect(() => {
    if (!withCharacterExtras || characterGroups || !projectId) return;
    let cancelled = false;
    void listCharacterGroups(projectId)
      .then((data) => {
        if (!cancelled) setFetchedGroups(data.items ?? []);
      })
      .catch(() => {
        if (!cancelled) setFetchedGroups([]);
      });
    return () => {
      cancelled = true;
    };
  }, [withCharacterExtras, characterGroups, projectId]);
  const effectiveGroups = characterGroups ?? fetchedGroups;
  // #679：等级选项卡顺序（总览 → 主角 → 重要配角 → 配角 → 场景角色 → 一次性角色）
  const RANK_OPTIONS = ['all', 'protagonist', 'major', 'minor', 'scene', 'walkon'].map((key) => ({
    key,
    label: t('lib.rank.' + key),
  }));
  // #679：分览过滤（'all' 显示全部角色）
  // #1320：服务端已按 role_rank 过滤并返回该等级全量 → 此处不得二次窄化，否则跨页项被误剪
  const visibleItems = isControlled
    ? items
    : selectedRank === 'all'
      ? items
      : items.filter((i) => String((i.extra as Record<string, unknown>)?.role_rank ?? '') === selectedRank);
  // #679：分组卡片（仅 characters；按 characterGroups 数组顺序，空组隐藏；未分组收尾）
  const groupSections = withCharacterExtras
    ? effectiveGroups
        .map((g) => ({
          group: g,
          members: visibleItems.filter((i) => groupIdsOf(i).map(String).includes(String(g.id))),
        }))
        .filter((sec) => sec.members.length > 0)
    : [];
  const ungroupedItems = withCharacterExtras
    ? visibleItems.filter((i) => groupIdsOf(i).length === 0)
    : [];

  // #1324：伏笔行扩展节点（标题之后渲染 —— 标题仍 flex-1 truncate，不被挤掉；缺省返回 null 不渲染）
  const renderForeshadowExtras = (item: LibraryItemDTO) => {
    if (!withForeshadowExtras) return null;
    const fs = item as LibraryItemForeshadow;
    const resolved = fs.status === 'resolved';
    const resolvedAt = resolved && fs.resolved_at ? formatResolvedAt(fs.resolved_at) : '';
    return (
      <>
        <span
          data-testid={`lib-fs-status-${item.id}`}
          className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${
            FS_STATUS_BADGE[fs.status ?? 'open'] ?? FS_STATUS_BADGE.open
          }`}
        >
          {t(resolved ? 'lib.fs.status.resolved' : 'lib.fs.status.open')}
          {resolvedAt !== '' && (
            <span data-testid={`lib-fs-resolved-at-${item.id}`}> · {resolvedAt}</span>
          )}
        </span>
        <span data-testid={`lib-fs-priority-${item.id}`} className="shrink-0 text-[11px] text-ink-3">
          {t('lib.fs.priority', { n: fs.priority ?? 0 })}
        </span>
        {fs.location !== '' && fs.location != null && (
          <span
            data-testid={`lib-fs-location-${item.id}`}
            className="shrink-0 max-w-[14rem] truncate rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2"
          >
            {fs.location}
          </span>
        )}
      </>
    );
  };

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
        {renderForeshadowExtras(item)}
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
            onClick={() => selectRank(opt.key)}
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
