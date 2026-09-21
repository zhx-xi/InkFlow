/**
 * #1300：设定库「非分页分类」的数据装配 hook（自 library.tsx 拆出）。
 *
 * 覆盖分类：
 *   - timeline：GET /timeline 返回 `{event_timeline, narrative_order}` 双数组（TimelineView 消费）
 *   - knowledge：fetchKnowledgeGraph 返回 `{nodes, edges}` 图谱聚合（非分页列表端点）
 *
 * 拆出动机（两条）：① 本文件原在 library.tsx 内联（120+ 行），而 library.tsx 基线 897 行、
 * 距 900 行护栏仅 3 行——#1300 新增分页接线必须同步把既有装配下沉，否则触线；
 * ② 与 useLibraryPagedList / useOutlineLibrary 形成「三个分类族各一个装配 hook」的一致形态。
 *
 * 行为保持（零语义变更）：切项目清空全部四组 state；失败 → loadFailed（页级 error 态可重试）。
 */
import { useEffect, useState } from 'react';
import { apiFetch } from '../api/client';
import {
  fetchKnowledgeGraph,
  type GraphEdge,
  type GraphNode,
  type GraphScope,
} from '../api/knowledge-graph';

/** timeline 列表端点响应（TimelineView 双数组；非分页） */
export interface TimelineViewData {
  event_timeline?: unknown[];
  narrative_order?: unknown[];
}

interface CatEndpoint {
  key: string;
  endpoint: (projectId: string) => string;
}

export interface LibraryCategoryData<T> {
  items: T[];
  timelineNarrative: T[];
  graphNodes: GraphNode[];
  graphEdges: GraphEdge[];
  loading: boolean;
  loadFailed: boolean;
}

/**
 * 拉取 timeline / knowledge 分类数据。
 *
 * @param cats 分类表（用于取当前分类的端点构造器；调用方传入以保持单一事实来源）
 * @param scope 图谱节点集范围（knowledge 分类用；#1325，默认 related 保证既有调用零改动）
 */
export function useLibraryCategoryData<T>(
  currentProjectId: string | null,
  activeCat: string,
  reloadKey: number,
  cats: CatEndpoint[],
  scope: GraphScope = 'related',
): LibraryCategoryData<T> {
  const [items, setItems] = useState<T[]>([]);
  const [timelineNarrative, setTimelineNarrative] = useState<T[]>([]);
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  const current = cats.find((c) => c.key === activeCat) ?? cats[0];
  // #1002/#1300：outline 由 useOutlineLibrary、characters/world/foreshadow 由 useLibraryPagedList 负责
  const owned = current !== undefined && current.key !== 'outline'
    && current.key !== 'characters' && current.key !== 'world' && current.key !== 'foreshadow';

  useEffect(() => {
    if (!currentProjectId || !owned) {
      setItems([]);
      setTimelineNarrative([]);
      setGraphNodes([]);
      setGraphEdges([]);
      setLoading(false);
      setLoadFailed(false);
      return;
    }
    let cancelled = false;
    if (current.key === 'knowledge') {
      // F48 §5.4：图谱视图一次拉取 nodes+edges（非列表端点；不动 loading——列表局部刷新不 unmount）
      setLoadFailed(false);
      void fetchKnowledgeGraph(currentProjectId, scope)
        .then((view) => {
          if (cancelled) return;
          setGraphNodes(view.nodes ?? []);
          setGraphEdges(view.edges ?? []);
          setItems([]);
          setTimelineNarrative([]);
          setLoading(false);
        })
        .catch(() => {
          if (cancelled) return;
          setGraphNodes([]);
          setGraphEdges([]);
          setItems([]);
          setTimelineNarrative([]);
          setLoading(false);
          setLoadFailed(true);
        });
      return () => {
        cancelled = true;
      };
    }
    setLoading(true);
    setLoadFailed(false);
    void apiFetch<{ items?: T[] } & TimelineViewData>(current.endpoint(currentProjectId))
      .then((data) => {
        if (cancelled) return;
        if (current.key === 'timeline') {
          setItems((data.event_timeline ?? []) as T[]);
          setTimelineNarrative((data.narrative_order ?? []) as T[]);
        } else {
          setItems(data.items ?? []);
          setTimelineNarrative([]);
        }
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setItems([]);
        setTimelineNarrative([]);
        setLoading(false);
        setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, activeCat, reloadKey, owned, current, scope]);

  return { items, timelineNarrative, graphNodes, graphEdges, loading, loadFailed };
}
