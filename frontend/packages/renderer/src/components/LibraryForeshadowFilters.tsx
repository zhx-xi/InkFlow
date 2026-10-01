/** #1376：伏笔页筛选/排序条（设计基准 design/GUI/foreshadow/foreshadow.html 形态 A）。
 *
 * 【纯展示受控件】筛选/排序 state 由页面持有（useForeshadowFilters）并下沉服务端
 * （?status= / ?search= / ?sort_by=&sort_desc=），组件只渲染 + 上抛意图 ——
 * 组件内自持 state 会让筛选只作用于当前页（#1300/#1320 已立的纪律）。
 *
 * 匹配面口径 1：检索框 = 条目标题 OR 位置文本子串（后端 search 并集语义，spec §4.3/§4.5）；
 * 本期只落形态 A（回收状态 chip 三态 + 检索框 + 计数行 + 排序切换），不渲染章节选择器 /
 * 方案 B 下拉区间 / 原型内嵌的 design-note 说明条（§4.4、N10）。 */
import { ArrowDown, ArrowUp } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';

export type ForeshadowFilterStatus = 'all' | 'open' | 'resolved';

export interface LibraryForeshadowFiltersProps {
  status: ForeshadowFilterStatus;
  query: string;
  sortDesc: boolean;
  /** 当前页条数 */
  shown: number;
  /** 筛选后总数（服务端返回的 total） */
  total: number;
  onStatusChange: (status: ForeshadowFilterStatus) => void;
  onQueryChange: (query: string) => void;
  onToggleSort: () => void;
}

/** #1376：页面持有筛选态时直传筛选条的字段集（LibraryItemList 透传入口） */
export interface ForeshadowFilterBarProps {
  status: ForeshadowFilterStatus;
  query: string;
  sortDesc: boolean;
  /** 是否有筛选生效（status / 检索；排序不计入）—— 决定空结果态是否替代通用空态 */
  active: boolean;
  onStatusChange: (status: ForeshadowFilterStatus) => void;
  onQueryChange: (query: string) => void;
  onToggleSort: () => void;
  onClear: () => void;
}

/** chip 选中 / 闲置样式（与 LibraryItemList 等级选项卡同值） */
const ACTIVE = 'bg-accent text-accent-ink';
const IDLE = 'bg-surface-3 text-ink-2';

export function LibraryForeshadowFilters({
  status,
  query,
  sortDesc,
  shown,
  total,
  onStatusChange,
  onQueryChange,
  onToggleSort,
}: LibraryForeshadowFiltersProps) {
  const { t } = useI18n();
  // 三态互斥单选：全部 = 不加筛选条件；未回收/已回收 = 下沉 ?status=
  const CHIPS: { key: ForeshadowFilterStatus; label: string }[] = [
    { key: 'all', label: t('lib.fs.filter.statusAll') },
    { key: 'open', label: t('lib.fs.status.open') },
    { key: 'resolved', label: t('lib.fs.status.resolved') },
  ];
  return (
    <div
      data-testid="foreshadow-filters"
      className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2"
    >
      <div
        data-testid="fs-status-chips"
        role="group"
        aria-label={t('lib.fs.filter.statusLabel')}
        className="flex items-center gap-1"
      >
        {CHIPS.map((chip) => (
          <button
            key={chip.key}
            type="button"
            data-testid={`fs-status-chip-${chip.key}`}
            aria-pressed={status === chip.key}
            className={`rounded-full px-3 py-1 text-[12px] transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
              status === chip.key ? ACTIVE : IDLE
            }`}
            onClick={() => onStatusChange(chip.key)}
          >
            {chip.label}
          </button>
        ))}
      </div>
      <input
        data-testid="fs-search-input"
        type="search"
        aria-label={t('lib.fs.filter.searchLabel')}
        placeholder={t('lib.fs.filter.searchPlaceholder')}
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        className="w-56 rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink placeholder:text-ink-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
      />
      <span data-testid="fs-count" className="ml-auto text-[12px] text-ink-2">
        {t('lib.fs.filter.count', { shown, total })}
      </span>
      <button
        type="button"
        data-testid="fs-sort-toggle"
        aria-pressed={sortDesc}
        className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[12px] text-ink-2 transition duration-180 hover:bg-surface-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        onClick={onToggleSort}
      >
        {sortDesc ? (
          <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        <span data-testid="fs-sort-label">
          {sortDesc ? t('lib.fs.filter.sortDesc') : t('lib.fs.filter.sortAsc')}
        </span>
      </button>
    </div>
  );
}
