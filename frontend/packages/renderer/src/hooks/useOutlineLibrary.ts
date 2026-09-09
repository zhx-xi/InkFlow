/**
 * #1002：大纲 tab 数据装配 hook（specs/f19-gui/outline.md §2「排序切换/顶层分页」+ §3 N6）。
 * 消费模型 = overall 顶层分页 + 卷/章全量缓存（两路并行），树 items 合并喂 OutlineTree：
 *   - overall 路：GET /outlines?level=overall&sort_by=sort_order&sort_desc=<asc?false:true>
 *     &offset=<page*10>&limit=10 —— 排序/翻页/reload 重拉；total 收敛防空页。
 *   - 卷/章路：复用无 level 全量列表循环拉全（首页 offset=0，步进至 total，
 *     total 异常以单次响应为准）；overall 行以分页路为准，仅当分页为空
 *     （旧列表 mock / 仅卷章数据）时以全量里的 overall 兜底（防整体行丢失）。
 *     说明：P2 护栏要求卷/章不因切序重拉（计数 0 为绝对基线），且 RED mock 的
 *     「无 level → 全量」为旧行为兼容面 → 全量路走无 level 首页 + offset 步进，
 *     与后端默认全量语义一致（level 过滤仅影响 URL 形状，合并结果等价）。
 *   - 任一路 catch → pushToast('err')（P7 裁决：初始失败 err toast + library-error 页态
 *     保留；重拉失败停留原页/原数据，不置位 loadFailed）。
 * 自 library.tsx 拆分以守 900 行护栏（同 useWorldCategories 先例）。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { apiFetch, errorMessage } from '../api/client';
import type { OutlineItemDTO } from '../components/OutlineTree';
import { useToastStore } from '../stores/toast';

/** #1002：大纲顶层分页 pageSize（契约 f19 §2：pageSize=10） */
export const OUTLINE_PAGE_SIZE = 10;
/** #1002：全量路单页上限（后端 limit 最大 100） */
const OUTLINE_FULL_LIMIT = 100;

interface OutlineListData {
  items?: OutlineItemDTO[];
  total?: number;
}

/** #1002：合并 overall 当前页 + 卷/章全量缓存（overall 优先，按 id 去重；
 *  分页有行 → 全量里的 overall 不再重复进入；分页为空 → overall 兜底不丢行） */
function mergeOutlineItems(overall: OutlineItemDTO[], subs: OutlineItemDTO[]): OutlineItemDTO[] {
  const seen = new Set<string>();
  const merged: OutlineItemDTO[] = [];
  for (const item of overall) {
    const key = String(item.id);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(item);
  }
  for (const item of subs) {
    const key = String(item.id);
    if (seen.has(key)) continue;
    if (overall.length > 0 && item.level === 'overall') continue;
    seen.add(key);
    merged.push(item);
  }
  return merged;
}

/** #1002：overall 顶层页严格按 level 收口（旧列表 mock 的无 level 行走全量路兜底展示） */
function keepOverallPageItem(item: OutlineItemDTO): boolean {
  return item.level === 'overall';
}

export interface OutlineLibraryData {
  chapterTitles: Record<string, string>;
  treeItems: OutlineItemDTO[];
  sortDesc: boolean;
  setSortDesc: (desc: boolean) => void;
  page: number;
  setPage: (page: number) => void;
  total: number;
  loading: boolean;
  loadFailed: boolean;
  handleOutlineGenerated: (outline: OutlineItemDTO) => void;
}

export function useOutlineLibrary(
  currentProjectId: string | null,
  activeCat: string,
  reloadKey: number,
): OutlineLibraryData {
  const [chapterTitles, setChapterTitles] = useState<Record<string, string>>({});
  const [sortDesc, setSortDesc] = useState(false);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [pageItems, setPageItems] = useState<OutlineItemDTO[]>([]);
  const [subItems, setSubItems] = useState<OutlineItemDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const loadedOnceRef = useRef(false);
  const pidRef = useRef<string | null>(null);
  const isOutlineTab = currentProjectId !== null && activeCat === 'outline';

  // #1002：切项目重置分页/排序/缓存（页码不跨项目复用）
  useEffect(() => {
    setSortDesc(false);
    setPage(0);
    setTotal(0);
    setPageItems([]);
    setSubItems([]);
    setLoading(false);
    setLoadFailed(false);
    loadedOnceRef.current = false;
    pidRef.current = null;
  }, [currentProjectId]);

  // F43 P3：章标题映射（章关联徽标；outline tab 拉取，搬自 library.tsx 行为不变）
  useEffect(() => {
    if (currentProjectId === null || activeCat !== 'outline') {
      setChapterTitles({});
      return;
    }
    let cancelled = false;
    void apiFetch<{ items?: Array<{ id: string | number; title?: string }> }>(
      `/api/v1/projects/${currentProjectId}/chapters`,
    )
      .then((data) => {
        if (cancelled) return;
        const map: Record<string, string> = {};
        for (const ch of data.items ?? []) {
          const title = ch.title?.trim();
          if (title) map[String(ch.id)] = title;
        }
        setChapterTitles(map);
      })
      .catch(() => {
        if (!cancelled) setChapterTitles({});
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, activeCat]);

  // #1002：overall 顶层分页路（sort/page/reload 重拉；初始失败置 error 态 + err toast）
  useEffect(() => {
    if (currentProjectId === null || activeCat !== 'outline') return;
    const pid = currentProjectId;
    const freshPid = pidRef.current !== pid;
    if (freshPid) pidRef.current = pid;
    const offset = (freshPid ? 0 : page) * OUTLINE_PAGE_SIZE;
    const isInitialLoad = freshPid || !loadedOnceRef.current;
    let cancelled = false;
    setLoading(true);
    if (isInitialLoad) setLoadFailed(false);
    void apiFetch<OutlineListData>(
      `/api/v1/projects/${pid}/outlines?level=overall&sort_by=sort_order&sort_desc=${sortDesc ? 'true' : 'false'}&offset=${offset}&limit=${OUTLINE_PAGE_SIZE}`,
    )
      .then((data) => {
        if (cancelled) return;
        const items = (data.items ?? []).filter(keepOverallPageItem);
        const nextTotal = data.total ?? 0;
        loadedOnceRef.current = true;
        setPageItems(items);
        setTotal(nextTotal);
        setLoading(false);
        // 增删/生成后 total 收缩 → 页码收敛到最后一页（防停留空页）
        if (offset >= nextTotal && nextTotal > 0) {
          setPage(Math.max(0, Math.ceil(nextTotal / OUTLINE_PAGE_SIZE) - 1));
        }
      })
      .catch((err) => {
        if (cancelled) return;
        useToastStore.getState().pushToast('err', errorMessage(err));
        setLoading(false);
        if (isInitialLoad) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, activeCat, sortDesc, page, reloadKey]);

  // #1002：卷/章全量缓存路（切项目/进 tab/reload 拉全；切序/翻页不重拉）
  useEffect(() => {
    if (currentProjectId === null || activeCat !== 'outline') return;
    const pid = currentProjectId;
    let cancelled = false;
    void (async () => {
      try {
        const all: OutlineItemDTO[] = [];
        let offset = 0;
        while (true) {
          const query = offset === 0 ? '' : `?offset=${offset}&limit=${OUTLINE_FULL_LIMIT}`;
          const data = await apiFetch<OutlineListData>(
            `/api/v1/projects/${pid}/outlines${query}`,
          );
          if (cancelled) return;
          const items = data.items ?? [];
          all.push(...items);
          const nextTotal = data.total ?? offset + items.length;
          offset += items.length;
          if (offset >= nextTotal || items.length === 0) break;
        }
        if (!cancelled) setSubItems(all);
      } catch (err) {
        if (!cancelled) useToastStore.getState().pushToast('err', errorMessage(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, activeCat, reloadKey]);

  const treeItems = useMemo(
    () => (isOutlineTab ? mergeOutlineItems(pageItems, subItems) : []),
    [isOutlineTab, pageItems, subItems],
  );

  // #1002：AI 生成 → overall 页本地 prepend + total+1（页码收敛同上；sort_order=0 → asc 树顶）
  const handleOutlineGenerated = (outline: OutlineItemDTO) => {
    setPageItems((prev) => [
      outline,
      ...prev.filter((i) => String(i.id) !== String(outline.id)),
    ]);
    const nextTotal = total + 1;
    setTotal(nextTotal);
    if (page * OUTLINE_PAGE_SIZE >= nextTotal && nextTotal > 0) {
      setPage(Math.max(0, Math.ceil(nextTotal / OUTLINE_PAGE_SIZE) - 1));
    }
  };

  return {
    chapterTitles,
    treeItems,
    sortDesc,
    setSortDesc,
    page,
    setPage,
    total,
    loading,
    loadFailed,
    handleOutlineGenerated,
  };
}
