/**
 * #1320：世界观列表的**全量取数** hook（替代服务端分页装配）。
 *
 * 背景：world tab 渲染的是 parent_id 整树（buildWorldTree / filterWorldTree 需全量数据
 * 才能正确建树与筛选），而 #1300 把它并入分页分类后：
 *   ① 分页条只在默认 else 分支渲染，world 走树分支 → **分页条不可达**（无翻页入口）；
 *   ② 树只用第 1 页 50 条构建 → 51+ 条世界条目**静默截断**；
 *   ③ 父条目不在本页的子条目被孤儿降级为顶层（树形失真）。
 *
 * 修法（用户已拍板）：world **不分页**——按 limit 上限（后端 le=100）循环拉全，
 * 分页条对整树无意义故不渲染。语义等价于 #1300 之前的一次性全量拉取。
 *
 * 边界：
 *   - 单次循环上限 `MAX_PAGES` 防后端 total 异常时死循环（100×20 = 2000 条，远超单项目规模）。
 *   - 中途失败：已取到的分页数据保留（避免整树清空），错误信息经 toast 暴露；
 *     首拉失败 → loadFailed（页面 error 态可重试）。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch, errorMessage } from '../api/client';
import { useToastStore } from '../stores/toast';

/** 单页拉取上限（后端 limit 约束 le=100） */
export const WORLD_FETCH_PAGE_SIZE = 100;
/** 循环上限（防 total 异常导致死循环；100×20 = 2000 条） */
const MAX_PAGES = 20;

interface ListData<T> {
  items?: T[];
  total?: number;
}

export interface WorldFullListData<T> {
  items: T[];
  loading: boolean;
  loadFailed: boolean;
}

/**
 * 全量拉取（自动翻页到取满 total）。
 *
 * @param currentProjectId 当前项目（null = 未选 → 清空）
 * @param activeCat        当前分类（仅 'world' 时拉取，其余清空）
 * @param reloadKey        外部刷新信号（数据变更 / 增删改后 bump）
 */
export function useWorldFullList<T>(
  currentProjectId: string | null,
  activeCat: string,
  reloadKey: number,
): WorldFullListData<T> {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  // 首拉是否成功过：区分「页级失败（error 态）」与「刷新失败（保留原数据 + toast）」
  const loadedOnceRef = useRef(false);

  const fetchAll = useCallback(
    async (projectId: string, cancelled: () => boolean): Promise<T[]> => {
      const collected: T[] = [];
      for (let pageNo = 0; pageNo < MAX_PAGES; pageNo += 1) {
        const offset = pageNo * WORLD_FETCH_PAGE_SIZE;
        const data = await apiFetch<ListData<T>>(
          `/api/v1/projects/${projectId}/world-settings?limit=${WORLD_FETCH_PAGE_SIZE}&offset=${offset}`,
        );
        if (cancelled()) return collected;
        const batch = data.items ?? [];
        collected.push(...batch);
        const total = data.total ?? collected.length;
        // 取满 total / 本页未满 / 本页为空 → 收敛（后端 limit 上限 100，超出需分批）
        if (collected.length >= total || batch.length < WORLD_FETCH_PAGE_SIZE) break;
      }
      return collected;
    },
    [],
  );

  useEffect(() => {
    if (!currentProjectId || activeCat !== 'world') {
      setItems([]);
      setLoading(false);
      setLoadFailed(false);
      loadedOnceRef.current = false;
      return;
    }
    let disposed = false;
    const cancelled = () => disposed;
    setLoading(true);
    setLoadFailed(false);
    void fetchAll(currentProjectId, cancelled)
      .then((all) => {
        if (disposed) return;
        setItems(all);
        setLoading(false);
        loadedOnceRef.current = true;
      })
      .catch((err: unknown) => {
        if (disposed) return;
        setLoading(false);
        if (!loadedOnceRef.current) {
          setItems([]);
          setLoadFailed(true);
        } else {
          // 刷新失败：保留已取数据（整树不清空），仅提示
          useToastStore.getState().pushToast('err', errorMessage(err));
        }
      });
    return () => {
      disposed = true;
    };
  }, [currentProjectId, activeCat, reloadKey, fetchAll]);

  return { items, loading, loadFailed };
}
