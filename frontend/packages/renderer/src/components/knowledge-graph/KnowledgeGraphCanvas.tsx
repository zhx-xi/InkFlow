/** F48 图谱画布（specs/f48-knowledge-graph/spec.md §5.4，Q2=A：@xyflow/react v12）
 * - GraphNode → 自定义节点（实体类型着色 + 名称）；GraphEdge → 有向边（label=relation_type，
 *   边 id 保留 GraphEdge.id（kr:/cr: 前缀））
 * - 拖拽节点 / 滚轮缩放 = @xyflow 默认能力；点击节点/边 → 画布内只读详情卡 + 回调
 *   （「去编辑」跳转目标由父级 onOpenEntity 提供，本组件不硬编码路由）
 * - 无障碍/降级：@xyflow 边渲染依赖真实 DOM 测量（jsdom 不渲染 SVG 边），容器内渲染
 *   sr-only 图数据摘要（节点名 + 「起点 label 终点」），屏幕阅读器可读且契约测试可断言
 *
 * #1325 升级（spec §5.2/§5.4）：
 * - 受控节点/边 state（useState + applyNodeChanges/applyEdgeChanges）→ 拖拽后位置不被网格覆盖
 * - KgNode 挂 source/target 两个 Handle → 可拖线建关系（onConnect 本地即时成边 + 上报父级落库）
 * - 拖拽结束按 project_id 把位置写入 localStorage（存储不可用时静默降级为会话内）
 * - 画布右下角「滚轮缩放 · 拖拽节点」提示（对齐 design/GUI/knowledge/knowledge.html）
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  BaseEdge,
  getBezierPath,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  type Connection,
  type EdgeChange as RFEdgeChange,
  type EdgeProps,
  type NodeChange as RFNodeChange,
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

/** 位置持久化 localStorage 基键（#1325）；带 project_id 时以 `:<project_id>` 后缀隔离 */
const KG_POSITIONS_STORAGE_KEY = 'inkflow:kg:positions';

/** 位置记忆键：`<基键>` 或 `<基键>:<project_id>`（跨项目位置互不污染） */
function kgPositionsKey(persistKey?: string): string {
  return persistKey ? `${KG_POSITIONS_STORAGE_KEY}:${persistKey}` : KG_POSITIONS_STORAGE_KEY;
}

/** 读取位置记忆（jsdom / 隐私模式双守卫：存储不可用或 JSON 异常 → {}，不抛错） */
function readSavedPositions(persistKey?: string): Record<string, { x: number; y: number }> {
  if (typeof localStorage === 'undefined') return {};
  try {
    const raw = localStorage.getItem(kgPositionsKey(persistKey));
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return {};
    return parsed as Record<string, { x: number; y: number }>;
  } catch {
    return {};
  }
}

/** 写入位置记忆（同上双守卫：存储不可用 → 静默，位置记忆退化为会话内） */
function writeSavedPositions(
  persistKey: string | undefined,
  positions: Record<string, { x: number; y: number }>,
): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(kgPositionsKey(persistKey), JSON.stringify(positions));
  } catch {
    // 存储不可用（隐私模式 / 配额）→ 静默
  }
}

/** 自定义节点：类型着色 + 名称标签 + 左右两个连线锚点（#1325：拉线建关系前置） */
function KgNode({ data }: NodeProps<KgRFNode>) {
  const { t } = useI18n();
  const style = TYPE_STYLES[data.type] ?? TYPE_STYLES.character;
  return (
    <div
      className="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[12px] font-medium shadow-card"
      style={{ backgroundColor: style.bg, borderColor: style.border, color: style.text }}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="kg-handle"
        aria-label={t('lib.knowledge.form.targetType')}
      />
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: style.dot }} aria-hidden="true" />
      <span className="whitespace-nowrap">{data.name}</span>
      <Handle
        type="source"
        position={Position.Right}
        className="kg-handle"
        aria-label={t('lib.knowledge.form.sourceType')}
      />
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
  /** 位置持久化键（父级传 currentProjectId；缺省用常量基键） */
  persistKey?: string;
  /** 拉线建关系：拖拽 Handle 连线时回调（source/target 为节点 id "<type>:<uuid>"） */
  onConnectNodes?: (source: string, target: string) => void;
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

/** 画布对外入口：包一层 ReactFlowProvider（画布内的 @xyflow hooks 需要该上下文） */
export function KnowledgeGraphCanvas(props: KnowledgeGraphCanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  );
}

function CanvasInner({
  nodes,
  edges,
  persistKey,
  onConnectNodes,
  onSelectNode,
  onSelectEdge,
  onOpenEntity,
  onEditEdge,
  onDeleteEdge,
}: KnowledgeGraphCanvasProps) {
  const { t } = useI18n();
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);

  /** 受控画布 state（#1325）：拖拽/连线只改 state，不再每次渲染按固定网格重算 */
  const [rfNodes, setRfNodes] = useState<KgRFNode[]>([]);
  const [rfEdges, setRfEdges] = useState<RFEdge[]>([]);

  /** 初始布局：固定网格（仅首次/节点集变化时用；拖拽后由 state 保持） */
  const layoutNodes = useMemo<KgRFNode[]>(
    () =>
      nodes.map((n, i) => ({
        id: n.id,
        type: 'kgNode',
        position: { x: 32 + (i % 5) * 180, y: 40 + Math.floor(i / 5) * 110 },
        data: { name: n.name, type: n.type },
      })),
    [nodes],
  );

  const dataEdges = useMemo<RFEdge[]>(
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

  /** 持久化位置（localStorage，按 project_id 键）——挂载/切项目时读一次 */
  const savedPositions = useRef<Record<string, { x: number; y: number }>>({});
  useEffect(() => {
    savedPositions.current = readSavedPositions(persistKey);
  }, [persistKey]);

  /** 节点集变化 → 用「记忆位置 → 端到端 localStorage → 网格」三级回退重建（保留已拖拽位置） */
  useEffect(() => {
    const persisted = readSavedPositions(persistKey);
    setRfNodes(
      layoutNodes.map((n) => ({
        ...n,
        position: savedPositions.current[n.id] ?? persisted[n.id] ?? n.position,
      })),
    );
  }, [layoutNodes, persistKey]);

  /** 业务边变化 → 同步进 state（本地 addEdge 的「待落库」边随后被覆盖，保存失败不留幽灵边） */
  useEffect(() => {
    setRfEdges(dataEdges);
  }, [dataEdges]);

  /** 最近一次渲染的节点集：拖拽结束读位置用（避免在 render 期调用 @xyflow hooks） */
  const nodesRef = useRef<KgRFNode[]>([]);
  nodesRef.current = rfNodes;

  // 钉住变更类型参数（NodeChange/EdgeChange 的 add/replace 变体带 node/edge 泛型）：
  // 默认泛型会让 applyNodeChanges 把 state 退化成 NodeBase[]，此处显式对齐自定义节点/边类型
  const handleNodesChange = useCallback((changes: RFNodeChange<KgRFNode>[]) => {
    setRfNodes((prev) => applyNodeChanges(changes, prev));
  }, []);
  const handleEdgesChange = useCallback((changes: RFEdgeChange<RFEdge>[]) => {
    setRfEdges((prev) => applyEdgeChanges(changes, prev));
  }, []);
  /** 拉线建关系（#1325 P2）：本地即时成边 + 上报父级（父级弹 RelationForm 落库） */
  const handleConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target) return;
      setRfEdges((prev) =>
        addEdge(
          {
            ...conn,
            type: 'kgEdge',
            label: '',
            markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18, color: 'var(--ink-3)' },
          },
          prev,
        ),
      );
      onConnectNodes?.(conn.source, conn.target);
    },
    [onConnectNodes],
  );
  /** 拖拽结束 → 位置落 localStorage（按 project_id 键） */
  const handleNodeDragStop = useCallback(() => {
    const map: Record<string, { x: number; y: number }> = {};
    for (const n of nodesRef.current) map[n.id] = { ...n.position };
    // 同步刷新内存记忆：否则后续「节点集变化重建」会用挂载时的旧快照覆盖刚拖出的位置
    savedPositions.current = map;
    writeSavedPositions(persistKey, map);
  }, [persistKey]);

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
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={handleConnect}
        onNodeDragStop={handleNodeDragStop}
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
      {/* #1325：拖拽/缩放提示（对齐 design/GUI/knowledge/knowledge.html 的「滚轮缩放 · 拖拽节点」） */}
      <span className="pointer-events-none absolute bottom-2 right-2 z-10 rounded-md border border-line bg-surface/90 px-2 py-0.5 text-[11px] text-ink-3">
        {t('lib.knowledge.canvasHint')}
      </span>
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
