/**
 * #1300：设定库长列表分类的**服务端分页**数据装配 hook。
 *
 * 背景：library.tsx 各分类（characters / world / foreshadow）此前一次性拉取
 * `cat.endpoint(pid)` 且**不传 limit/offset**（后端默认 limit=50），total 字段
 * 虽在响应里但从未被消费 → 超过 50 条即静默截断、无翻页入口。
 *
 * 本 hook 承载分页 state + 拉取 + 页码收敛，自 library.tsx 拆出（该文件基线 897 行，
 * 距 900 行护栏仅 3 行，**不得**在其内新增分页逻辑；同 useOutlineLibrary / useWorldCategories 先例）。
 *
 * 适用分类：characters / world / foreshadow（后端端点均支持 `?limit=&offset=` 且返回 total）。
 * 不适用：
 *   - timeline：TimelineView 消费 `{event_timeline, narrative_order}` 双数组结构，非分页列表
 *   - knowledge：fetchKnowledgeGraph 返回 nodes+edges 聚合，非分页端点
 *   - outline：已有 useOutlineLibrary（顶层分页 + 卷章全量缓存的特殊形态）
 *
 * 分页语义：
 *   - 切分类 / 切项目 / reloadKey 变化 → 重置到第 1 页（页码不跨分类复用）
 *   - total 收缩（删除后）→ 页码收敛到最后一页（防停留空页）
 *   - 失败：首页失败置 loadFailed（页面 error 态可重试）；翻页失败停留原页 + err toast
 */
import { useEffect, useRef, useState } from 'react';
import { apiFetch, errorMessage } from '../api/client';
import { useToastStore } from '../stores/toast';

/** #1300：设定库列表页默认每页条数（长列表；与日志页 50 同档） */
export const LIBRARY_PAGE_SIZE = 50;

/** 支持服务端分页的设定库分类 */
export type PageableCatKey = 'characters' | 'world' | 'foreshadow';

interface ListData<T> {
  items?: T[];
  total?: number;
}

export interface LibraryPageData<T> {
  items: T[];
  loading: boolean;
  loadFailed: boolean;
  page: number;
  setPage: (page: number) => void;
  total: number;
}

/**
 * 拉取分页列表。
 *
 * @param currentProjectId 当前项目（null = 未选项目 → 清空）
 * @param activeCat        当前分类 key（非分页分类 → 本 hook 不拉取，恒空）
 * @param reloadKey        外部刷新信号（数据面变更 / 增删改后 bump）
 * @param endpoint         列表端点构造器（相对 base_url，含 /api/v1 前缀）
 * @param extraQuery       #1320 附加查询条件（如 `{ role_rank: 'protagonist' }`）；变化即重拉并重置页码
 */
export function useLibraryPagedList<T>(
  currentProjectId: string | null,
  activeCat: string,
  reloadKey: number,
  endpoint: (projectId: string) => string,
  extraQuery?: Record<string, string> | null,
): LibraryPageData<T> {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  // #1320：筛选条件指纹（与 scope 同档：变化 = 新数据集 → 页码归零 + 首拉重新计数）
  const extraKey = extraQuery
    ? Object.entries(extraQuery)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, v]) => `${k}=${v}`)
        .join('&')
    : '';
  // 分类/项目/筛选切换 → 页码重置（不复用上一数据集的页码）；reloadKey 不重置页码
  const scopeRef = useRef<string | null>(null);
  // 首拉是否成功过：用于区分「页级失败（error 态）」与「翻页失败（仅 toast，保留原数据）」
  const loadedOnceRef = useRef(false);
  const isPageable = activeCat === 'characters' || activeCat === 'world' || activeCat === 'foreshadow';

  useEffect(() => {
    if (!currentProjectId || !isPageable) {
      setItems([]);
      setTotal(0);
      setLoading(false);
      setLoadFailed(false);
      scopeRef.current = null;
      return;
    }
    const scope = `${currentProjectId}/${activeCat}/${extraKey}`;
    const freshScope = scopeRef.current !== scope;
    if (freshScope) {
      scopeRef.current = scope;
      loadedOnceRef.current = false; // 换分类/换项目/换筛选 → 首拉重新计数（失败仍走页级 error 态）
    }
    // 切项目/切分类/切筛选 → 本次拉取按第 1 页发起（页码 state 同步收敛）
    const effectivePage = freshScope ? 0 : page;
    if (freshScope && page !== 0) setPage(0);

    let cancelled = false;
    setLoading(true);
    // #1300：每次拉取都清 error 态——否则 reloadKey 重试（retry 按钮）后 loadFailed 永久为 true，
    // 列表无法从错误态恢复；scope 变化只是「页码是否归零」的判据，与 error 态无关。
    setLoadFailed(false);
    const offset = effectivePage * LIBRARY_PAGE_SIZE;
    const sep = endpoint(currentProjectId).includes('?') ? '&' : '?';
    // #1320：筛选条件随分页一起下发（服务端过滤 → total 为过滤后口径）
    const filterQs = extraKey ? `&${extraKey}` : '';
    void apiFetch<ListData<T>>(
      `${endpoint(currentProjectId)}${sep}limit=${LIBRARY_PAGE_SIZE}&offset=${offset}${filterQs}`,
    )
      .then((data) => {
        if (cancelled) return;
        const nextItems = data.items ?? [];
        const nextTotal = data.total ?? nextItems.length;
        setItems(nextItems);
        setTotal(nextTotal);
        setLoading(false);
        loadedOnceRef.current = true;
        // 删除后 total 收缩 → 页码收敛到最后一页（防停留空页）
        if (offset >= nextTotal && nextTotal > 0) {
          setPage(Math.max(0, Math.ceil(nextTotal / LIBRARY_PAGE_SIZE) - 1));
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoading(false);
        if (freshScope || !loadedOnceRef.current) {
          setItems([]);
          setTotal(0);
          setLoadFailed(true);
        } else {
          // 翻页失败：停留原页原数据，仅提示（不置页级 error 态）
          useToastStore.getState().pushToast('err', errorMessage(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, activeCat, reloadKey, page, isPageable, endpoint, extraKey]);

  return { items, loading, loadFailed, page, setPage, total };
}
