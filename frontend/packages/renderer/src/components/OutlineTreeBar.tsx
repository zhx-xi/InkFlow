/** #1002：大纲卡片工具栏排序分段控件 + 顶层分页条（specs/f19-gui/outline.md §2 新两行 / §3 N6）。
 *  受控 props 由 OutlineTree 透传：sortDesc 当前方向 / onSortChange(desc)；
 *  total > pageSize 时才渲染分页条；info = lib.page.info（page/pages/total 插值）。
 *  与 OutlineTree 主文件拆分以守 900 行护栏（同 useWorldCategories 先例）。 */
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import { Pagination } from './Pagination';

const SEGMENT_BASE =
  'inline-flex items-center gap-1.5 rounded-md border px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50';

/** 排序分段控件（asc/desc，aria-pressed 标记当前方向；恒渲染，独立于 projectId gate） */
export function OutlineSortToggle({
  sortDesc,
  onSortChange,
}: {
  sortDesc: boolean;
  onSortChange?: (desc: boolean) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        data-testid="outline-sort-asc"
        aria-pressed={!sortDesc}
        className={cn(
          SEGMENT_BASE,
          !sortDesc
            ? 'border-accent bg-accent/10 font-medium text-accent'
            : 'border-line text-ink-2 hover:border-accent hover:text-accent',
        )}
        onClick={() => onSortChange?.(false)}
      >
        {t('lib.sort.asc')}
      </button>
      <button
        type="button"
        data-testid="outline-sort-desc"
        aria-pressed={sortDesc}
        className={cn(
          SEGMENT_BASE,
          sortDesc
            ? 'border-accent bg-accent/10 font-medium text-accent'
            : 'border-line text-ink-2 hover:border-accent hover:text-accent',
        )}
        onClick={() => onSortChange?.(true)}
      >
        {t('lib.sort.desc')}
      </button>
    </div>
  );
}

/** 顶层分页条（outline-page-prev / -info / -next；首页 prev disabled、末页 next disabled）。
 *  #1300：翻页 UI 统一由公共组件 Pagination 提供（数据装配逻辑仍留在 useOutlineLibrary，
 *  本组件只做布局壳对齐）；testIdPrefix='outline-page' 保留既有契约 testid。 */
export function OutlinePager({
  total,
  page,
  onPageChange,
  pageSize = 10,
}: {
  total: number;
  page: number;
  onPageChange?: (p: number) => void;
  pageSize?: number;
}) {
  return (
    <Pagination
      className="justify-center border-t border-line px-4 py-2"
      page={page}
      pageSize={pageSize}
      total={total}
      onPageChange={(p) => onPageChange?.(p)}
      testIdPrefix="outline-page"
    />
  );
}
