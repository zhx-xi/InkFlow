/** #1376：伏笔页筛选态钩子（页面侧唯一出口）—— 筛选/排序下沉服务端。
 *
 * 【落点】纯前端过滤当前页会漏掉其他页的命中项（#1300/#1320 纪律），故 state 在此装配成
 * ``extraQuery``（services 分页 hook 逐次下发），``total`` 才是筛选后口径：
 *   - ``status !== 'all'`` → ``{ status }``
 *   - 检索词非空 → ``{ search }``（匹配面 = 标题 OR 位置，后端并集语义）
 *   - 升序（``sortDesc === false``）→ ``{ sort_by: 'priority', sort_desc: 'false' }``
 *     （降序 = 后端缺省 → **不发**排序参数，保证「不选筛选 = 改动前请求」不变）
 *
 * 检索词 250ms 防抖后进 extraQuery（输入框仍显示即时值）；``active`` 只看 status / 检索，
 * 排序不计入（切换排序不触发「空结果态」替代通用空态）。 */
import { useEffect, useMemo, useState } from 'react';
import type { ForeshadowFilterBarProps, ForeshadowFilterStatus } from '../components/LibraryForeshadowFilters';

export type { ForeshadowFilterBarProps };

/** 检索框防抖窗口（ms） */
export const FORESHADOW_QUERY_DEBOUNCE_MS = 250;

export interface UseForeshadowFiltersResult {
  /** 是否有筛选生效（status / 检索；排序不计入）—— 决定「空结果态」替代通用空态 */
  active: boolean;
  /** 服务端筛选/排序参数（无任何条件 = null） */
  extraQuery: Record<string, string> | null;
  /** 直传 LibraryItemList 的筛选条字段 */
  barProps: ForeshadowFilterBarProps;
}

export function useForeshadowFilters(): UseForeshadowFiltersResult {
  const [status, setStatus] = useState<ForeshadowFilterStatus>('all');
  const [query, setQuery] = useState('');
  const [sortDesc, setSortDesc] = useState(true);
  const [debouncedQuery, setDebouncedQuery] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), FORESHADOW_QUERY_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const search = debouncedQuery.trim();

  const extraQuery = useMemo<Record<string, string> | null>(() => {
    const conditions: Record<string, string> = {};
    if (status !== 'all') conditions.status = status;
    if (search !== '') conditions.search = search;
    if (!sortDesc) {
      conditions.sort_by = 'priority';
      conditions.sort_desc = 'false';
    }
    return Object.keys(conditions).length === 0 ? null : conditions;
  }, [status, search, sortDesc]);

  const active = status !== 'all' || search !== '';

  return {
    active,
    extraQuery,
    barProps: {
      status,
      query,
      sortDesc,
      active,
      onStatusChange: setStatus,
      onQueryChange: setQuery,
      onToggleSort: () => setSortDesc((v) => !v),
      // 清除筛选 = 状态回「全部」+ 清空检索词；不改变排序方向（N9 边界）
      onClear: () => {
        setStatus('all');
        setQuery('');
        setDebouncedQuery('');
      },
    },
  };
}
