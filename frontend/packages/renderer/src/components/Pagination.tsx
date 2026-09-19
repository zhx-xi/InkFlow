/**
 * #1300：分页公共组件（分页逻辑此前两处内联且形态不一，本组件为唯一实现）。
 *
 * props：
 *   page / pageSize / total / onPageChange  —— 必填受控三件套 + 翻页回调（page 为 0 基）
 *   onPageSizeChange?(size)   —— 未提供 → 不渲染页大小 Select（大纲树形态）
 *   pageSizeOptions?          —— 默认 [10, 25, 50, 100]（对齐日志页现状）
 *   testIdPrefix?             —— 默认 'pagination'；logs 页传 'log-page'、大纲传 'outline-page'
 *                                以保留既有契约 testid（迁移零改测）
 *   className?                —— 外层布局钩子（各页容器间距不同）
 *
 * 边界语义（契约 Pagination.test.tsx 锁定）：
 *   首页 prev 禁用 / 末页 next 禁用 / total=0 不崩（pages 收敛 1，双向禁用）/
 *   pageSize 切换重置到第 1 页（已是首页则不产生冗余 onPageChange）。
 */
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';

/** 默认页大小档位（对齐日志页现状 PAGE_SIZES） */
export const DEFAULT_PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

const BUTTON_CLS =
  'rounded-md border border-line bg-surface px-3 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-50';

export interface PaginationProps {
  /** 当前页（0 基） */
  page: number;
  /** 每页条数（<= 0 视为未提供 → 回退 10） */
  pageSize: number;
  /** 总条数 */
  total: number;
  /** 翻页回调（收到 0 基页码） */
  onPageChange: (page: number) => void;
  /** 页大小变更回调；未提供 → 不渲染 Select */
  onPageSizeChange?: (pageSize: number) => void;
  /** 可选页大小档位 */
  pageSizeOptions?: number[];
  /** testid 前缀（既有契约保留用） */
  testIdPrefix?: string;
  /** 外层容器类名（布局钩子） */
  className?: string;
}

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  testIdPrefix = 'pagination',
  className,
}: PaginationProps) {
  const { t } = useI18n();
  const safeSize = pageSize > 0 ? pageSize : 10;
  const safeTotal = Math.max(0, total);
  const safePage = Math.max(0, page);
  const pages = Math.max(1, Math.ceil(safeTotal / safeSize));
  const lastPage = (safePage + 1) * safeSize >= safeTotal;
  // total=0 → next 必须禁用（lastPage 在安全 total 下恒真，无需额外分支）

  const handlePageSizeChange = (value: string) => {
    const next = Number(value);
    if (!Number.isFinite(next) || next <= 0) return;
    if (!pageSizeOptions.includes(next)) return;
    onPageSizeChange?.(next);
    // 页大小变更 → 重置到第 1 页（已首页则不产生冗余回调）
    if (safePage !== 0) onPageChange(0);
  };

  return (
    <div className={cn('flex flex-wrap items-center gap-3', className)}>
      {onPageSizeChange && (
        <div className="flex flex-col gap-1.5">
          <Select value={String(safeSize)} onValueChange={handlePageSizeChange}>
            <SelectTrigger
              data-testid={`${testIdPrefix}-size-select`}
              aria-label={t('pagination.page.size.label')}
              className="h-8 w-24"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {pageSizeOptions.map((size) => (
                <SelectItem key={size} value={String(size)}>
                  {String(size)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      <button
        type="button"
        data-testid={`${testIdPrefix}-prev`}
        disabled={safePage === 0}
        className={BUTTON_CLS}
        onClick={() => onPageChange(safePage - 1)}
      >
        {t('pagination.page.prev')}
      </button>
      <span data-testid={`${testIdPrefix}-info`} className="text-[13px] text-ink-2">
        {t('pagination.page.info', { page: safePage + 1, pages, total: safeTotal })}
      </span>
      <button
        type="button"
        data-testid={`${testIdPrefix}-next`}
        disabled={lastPage}
        className={BUTTON_CLS}
        onClick={() => onPageChange(safePage + 1)}
      >
        {t('pagination.page.next')}
      </button>
    </div>
  );
}
