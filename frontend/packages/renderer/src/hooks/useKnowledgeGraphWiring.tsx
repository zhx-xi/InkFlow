/**
 * #1325：知识图谱 tab 的「状态 + 接线」装配 hook（自 library.tsx 拆出）。
 *
 * 拆出动机与既有 `useOutlineLibrary` / `useLibraryPagedList` / `useWorldFullList` 同源：
 * library.tsx 是 900 行护栏的贴线文件，图谱 tab 新增的 scope 开关 + 关系列表服务端分页
 * + 画布拉线回调，若内联会把接线面（40+ 行 JSX props + 3 处 state + 2 个 handler）全部
 * 压在本文件上。此处只做**状态与回调装配**，视图与渲染仍由 KnowledgeGraphView 负责。
 *
 * 对外返回：`viewProps`（一次展开给 `<KnowledgeGraphView {...} />`）+ `relations`/`relationTotal`
 * （确认对话框等页面根部消费方按需读取）。视图态（kgView/scope/表单态）仍由 library.tsx 持有
 * ——表单与确认框渲染在该文件根部，状态随渲染位置就近；本 hook 只做「透传 + 分页拉取 + 拉线预填」。
 */
import { useEffect, useState } from 'react';
import {
  listKnowledgeRelations,
  type GraphEdge,
  type GraphNode,
  type GraphScope,
  type KnowledgeRelation,
} from '../api/knowledge-graph';
import type { KnowledgeGraphViewProps } from '../components/knowledge-graph/KnowledgeGraphView';

/** 关系列表页大小（复用设定库分页档位语义：50/页） */
const RELATION_PAGE_SIZE = 50;

export interface KnowledgeGraphWiring {
  /** 当前项目关系列表（服务端分页的一页） */
  relations: KnowledgeRelation[];
  /** 关系全量条数（分页条 total） */
  relationTotal: number;
  /** 展开给 <KnowledgeGraphView /> 的全部 props */
  viewProps: KnowledgeGraphViewProps;
}

export interface KnowledgeGraphWiringArgs {
  currentProjectId: string | null;
  /** 当前分类是否为 knowledge（false 时不拉取关系列表） */
  active: boolean;
  /** 图谱视图/关系列表切换（视图态由调用方持有，本 hook 只透传 + 接线） */
  kgView: 'graph' | 'list';
  onViewChange: (view: 'graph' | 'list') => void;
  /** 增删改后局部刷新键 */
  reloadKey: number;
  /** 图谱节点集范围（由调用方持有：同一 scope 要同时喂给图谱拉取 hook） */
  scope: GraphScope;
  /** 切换节点集范围（切后由调用方把关系列表页码归零） */
  onScopeChange: (scope: GraphScope) => void;
  graphNodes: GraphNode[];
  graphEdges: GraphEdge[];
  /** 节点详情「去编辑」跳转（按实体类型切 tab） */
  onOpenEntity: (node: GraphNode) => void;
  /** 打开关系表单（新建传 null / 编辑传现有行；#1325 拉线也走这条） */
  onOpenRelationForm: (relation: KnowledgeRelation | null) => void;
  /** 请求删除二次确认 */
  onRequestRelationDelete: (relation: KnowledgeRelation) => void;
  /** 空态引导目标 */
  onGoEntities: () => void;
}

export function useKnowledgeGraphWiring({
  currentProjectId,
  active,
  kgView,
  onViewChange,
  reloadKey,
  scope,
  onScopeChange,
  graphNodes,
  graphEdges,
  onOpenEntity,
  onOpenRelationForm,
  onRequestRelationDelete,
  onGoEntities,
}: KnowledgeGraphWiringArgs): KnowledgeGraphWiring {
  // #1325：关系列表服务端分页（旧实现不带 limit/offset → 后端默认 limit=50 使第 51 条起永久不可见）
  const [relationPage, setRelationPage] = useState(0);
  const [relationTotal, setRelationTotal] = useState(0);
  const [relations, setRelations] = useState<KnowledgeRelation[]>([]);

  const relationOffset = relationPage * RELATION_PAGE_SIZE;

  useEffect(() => {
    if (!currentProjectId || !active || kgView !== 'list') {
      setRelations([]);
      setRelationTotal(0);
      return;
    }
    let cancelled = false;
    void listKnowledgeRelations(currentProjectId, {
      offset: relationOffset,
      limit: RELATION_PAGE_SIZE,
    })
      .then((data) => {
        if (cancelled) return;
        setRelations(data.items ?? []);
        setRelationTotal(data.total ?? 0);
      })
      .catch(() => {
        if (cancelled) return;
        setRelations([]);
        setRelationTotal(0);
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, active, kgView, reloadKey, relationOffset]);

  /** 画布边 → 关系行（仅 knowledge_relations 可编辑；名称由节点解析） */
  const relationFromEdge = (edge: GraphEdge): KnowledgeRelation | null => {
    if (edge.source_table !== 'knowledge_relations') return null;
    const src = graphNodes.find((n) => n.id === edge.source);
    const tgt = graphNodes.find((n) => n.id === edge.target);
    if (!src || !tgt) return null;
    return {
      id: edge.id.replace(/^kr:/, ''),
      project_id: currentProjectId ?? '',
      source_type: src.type,
      source_id: src.entity_id,
      target_type: tgt.type,
      target_id: tgt.entity_id,
      relation_type: edge.label,
      description: edge.description ?? '',
      source: 'manual',
      created_at: '',
      updated_at: '',
    };
  };

  const openForm = onOpenRelationForm;

  /** #1325：拉线建关系——节点 id "<type>:<uuid>" → 表单预填两端（relation_type 留空待填） */
  const handleConnectNodes = (sourceId: string, targetId: string) => {
    const src = graphNodes.find((n) => n.id === sourceId);
    const tgt = graphNodes.find((n) => n.id === targetId);
    if (!src || !tgt) return;
    openForm({
      id: '',
      project_id: currentProjectId ?? '',
      source_type: src.type,
      source_id: src.entity_id,
      target_type: tgt.type,
      target_id: tgt.entity_id,
      relation_type: '',
      description: '',
      source: 'manual',
      created_at: '',
      updated_at: '',
    });
  };

  const viewProps: KnowledgeGraphViewProps = {
    nodes: graphNodes,
    edges: graphEdges,
    relations,
    view: kgView,
    onViewChange,
    scope,
    onScopeChange,
    persistKey: currentProjectId ?? undefined,
    onConnectNodes: handleConnectNodes,
    relationTotal,
    relationPage,
    relationPageSize: RELATION_PAGE_SIZE,
    onRelationPageChange: setRelationPage,
    onCreateRelation: () => openForm(null),
    onEditRelation: (relation: KnowledgeRelation) => openForm(relation),
    onDeleteRelation: onRequestRelationDelete,
    onOpenEntity,
    onEditEdge: (edge: GraphEdge) => {
      const relation = relationFromEdge(edge);
      if (relation) openForm(relation);
    },
    onDeleteEdge: (edge: GraphEdge) => {
      const relation = relationFromEdge(edge);
      if (relation) onRequestRelationDelete(relation);
    },
    onGoEntities,
  };

  return { relations, relationTotal, viewProps };
}
