/** F48 图谱画布（specs/f48-knowledge-graph/spec.md §5.4，Q2=A：@xyflow/react v12）
 * - GraphNode → 自定义节点（实体类型着色 + 名称）；GraphEdge → 有向边（label=relation_type，
 *   边 id 保留 GraphEdge.id（kr:/cr: 前缀））
 * - 拖拽节点 / 滚轮缩放 = @xyflow 默认能力；点击节点/边 → 画布内只读详情卡 + 回调
 *   （「去编辑」跳转目标由父级 onOpenEntity 提供，本组件不硬编码路由）
 * - 无障碍/降级：@xyflow 边渲染依赖真实 DOM 测量（jsdom 不渲染 SVG 边），容器内渲染
 *   sr-only 图数据摘要（节点名 + 「起点 label 终点」），屏幕阅读器可读且契约测试可断言
 */
import { useMemo, useState } from 'react';
import {
  BaseEdge,
  getBezierPath,
  MarkerType,
  ReactFlow,
  type EdgeProps,
  type NodeProps,
} from '@xyflow/react';
import type { Edge as RFEdge, Node as RFNode } from '@xyflow/react';
import type { EntityType, GraphEdge, GraphNode } from '../../api/knowledge-graph';
import { useI18n } from '../../i18n/useI18n';

/** 实体类型显示名 i18n key（与六分类 tab 同源语义） */
const ENTITY_TYPE_KEYS: Record<EntityType, string> = {
  character: 'lib.knowledge.type.character',
  world: 'lib.knowledge.type.world',
  outline: 'lib.knowledge.type.outline',
  timeline: 'lib.knowledge.type.timeline',
  foreshadow: 'lib.knowledge.type.foreshadow',
  map_pin: 'lib.knowledge.type.map_pin',
};

/** 节点类型着色（Tailwind 默认调色板十六进制，供画布节点与详情卡共用） */
const TYPE_STYLES: Record<EntityType, { bg: string; border: string; text: string; dot: string }> = {
  character: { bg: '#fef2f2', border: '#fecaca', text: '#991b1b', dot: '#ef4444' },
  world: { bg: '#eff6ff', border: '#bfdbfe', text: '#1e40af', dot: '#3b82f6' },
  outline: { bg: '#f0fdf4', border: '#bbf7d0', text: '#166534', dot: '#22c55e' },
  timeline: { bg: '#fefce8', border: '#fde68a', text: '#854d0e', dot: '#eab308' },
  foreshadow: { bg: '#f5f3ff', border: '#ddd6fe', text: '#5b21b6', dot: '#8b5cf6' },
  map_pin: { bg: '#fff7ed', border: '#fed7aa', text: '#9a3412', dot: '#f97316' },
};

type KgNodeData = { name: string; type: EntityType };
type KgRFNode = RFNode<KgNodeData>;

/** 自定义节点：类型着色 + 名称标签 */
function KgNode({ data }: NodeProps<KgRFNode>) {
  const style = TYPE_STYLES[data.type] ?? TYPE_STYLES.character;
  return (
    <div
      className="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[12px] font-medium shadow-card"
      style={{ backgroundColor: style.bg, borderColor: style.border, color: style.text }}
    >
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: style.dot }} aria-hidden="true" />
      <span className="whitespace-nowrap">{data.name}</span>
    </div>
  );
}

/** 自定义边：贝塞尔路径 + 有向箭头 + label（SVG text；真实浏览器渲染层） */
function KgEdge({ id, sourceX, sourceY, targetX, targetY, markerEnd, label }: EdgeProps) {
  const [edgePath] = getBezierPath({ sourceX, sourceY, targetX, targetY });
  return (
    <>
      <BaseEdge id={id} path={edgePath} markerEnd={markerEnd} />
      <text
        x={(sourceX + targetX) / 2}
        y={(sourceY + targetY) / 2}
        textAnchor="middle"
        style={{ fill: 'var(--ink-2)', fontSize: 10 }}
      >
        {label}
      </text>
    </>
  );
}

const nodeTypes = { kgNode: KgNode };
const edgeTypes = { kgEdge: KgEdge };

export interface KnowledgeGraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** 点击节点（详情卡已内建；父级可追加抽屉等） */
  onSelectNode?: (node: GraphNode) => void;
  /** 点击边（详情卡已内建；父级可追加抽屉等） */
  onSelectEdge?: (edge: GraphEdge) => void;
  /** 节点详情「去编辑」跳转目标（各实体页由父级提供） */
  onOpenEntity?: (node: GraphNode) => void;
  /** 边详情「编辑」回调（父级打开回填表单） */
  onEditEdge?: (edge: GraphEdge) => void;
  /** 边详情「删除」回调（父级二次确认后 DELETE） */
  onDeleteEdge?: (edge: GraphEdge) => void;
}

export function KnowledgeGraphCanvas({
  nodes,
  edges,
  onSelectNode,
  onSelectEdge,
  onOpenEntity,
  onEditEdge,
  onDeleteEdge,
}: KnowledgeGraphCanvasProps) {
  const { t } = useI18n();
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);

  const rfNodes = useMemo<KgRFNode[]>(
    () =>
      nodes.map((n, i) => ({
        id: n.id,
        type: 'kgNode',
        position: { x: 32 + (i % 5) * 180, y: 40 + Math.floor(i / 5) * 110 },
        data: { name: n.name, type: n.type },
      })),
    [nodes],
  );

  const rfEdges = useMemo<RFEdge[]>(
    () =>
      edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        type: 'kgEdge',
        label: e.label,
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18, color: 'var(--ink-3)' },
      })),
    [edges],
  );

  /** sr-only 数据摘要：节点名 + 边「起点 label 终点」（无障碍 + jsdom 断言兜底） */
  const summary = useMemo(
    () =>
      [
        ...nodes.map((n) => n.name),
        ...edges.map((e) => {
          const sourceName = nodes.find((n) => n.id === e.source)?.name ?? e.source;
          const targetName = nodes.find((n) => n.id === e.target)?.name ?? e.target;
          return `${sourceName} ${e.label} ${targetName}`;
        }),
      ].join('，'),
    [nodes, edges],
  );

  return (
    <div
      data-testid="library-kg-canvas"
      className="relative h-[520px] overflow-hidden rounded-lg border border-line bg-surface shadow-card"
    >
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        minZoom={0.2}
        maxZoom={2}
        onNodeClick={(_, rfNode) => {
          const node = nodes.find((n) => n.id === rfNode.id);
          if (!node) return;
          setSelectedEdge(null);
          setSelectedNode(node);
          onSelectNode?.(node);
        }}
        onEdgeClick={(_, rfEdge) => {
          const edge = edges.find((e) => e.id === rfEdge.id);
          if (!edge) return;
          setSelectedNode(null);
          setSelectedEdge(edge);
          onSelectEdge?.(edge);
        }}
        onPaneClick={() => {
          setSelectedNode(null);
          setSelectedEdge(null);
        }}
      />
      <div className="sr-only" data-testid="library-kg-summary">
        {t('lib.knowledge.graphSummary')}：{summary}
      </div>
      {selectedNode && (
        <div
          data-testid="library-kg-node-detail"
          className="absolute bottom-3 left-3 z-10 w-64 rounded-md border border-line bg-surface p-3 shadow-card"
        >
          <p className="text-[11px] text-ink-3">{t(ENTITY_TYPE_KEYS[selectedNode.type])}</p>
          <p className="mt-0.5 truncate font-serif text-[14px] font-semibold text-ink">{selectedNode.name}</p>
          {onOpenEntity && (
            <button
              type="button"
              data-testid={`library-kg-node-edit-${selectedNode.entity_id}`}
              className="mt-2 rounded-md bg-accent px-3 py-1 text-[12px] text-accent-ink transition duration-180 hover:bg-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              onClick={() => onOpenEntity(selectedNode)}
            >
              {t('lib.knowledge.node.goEdit')}
            </button>
          )}
        </div>
      )}
      {selectedEdge && (
        <div
          data-testid="library-kg-edge-detail"
          className="absolute bottom-3 left-3 z-10 w-72 rounded-md border border-line bg-surface p-3 shadow-card"
        >
          <p className="truncate text-[13px] font-medium text-ink">{selectedEdge.label}</p>
          {selectedEdge.description ? (
            <p className="mt-1 text-[12px] text-ink-2">{selectedEdge.description}</p>
          ) : null}
          <p className="mt-1 text-[11px] text-ink-3">
            {t('lib.knowledge.edge.source')}：{selectedEdge.source_table}
          </p>
          {onEditEdge && onDeleteEdge && (
            <div className="mt-2 flex items-center gap-1.5">
              <button
                type="button"
                data-testid={`library-kg-edge-edit-${selectedEdge.id}`}
                className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-180 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => onEditEdge(selectedEdge)}
              >
                {t('lib.edit')}
              </button>
              <button
                type="button"
                data-testid={`library-kg-edge-delete-${selectedEdge.id}`}
                className="rounded-md border border-err/40 px-3 py-1 text-[12px] text-err transition duration-180 hover:bg-err/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => onDeleteEdge(selectedEdge)}
              >
                {t('lib.delete')}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
