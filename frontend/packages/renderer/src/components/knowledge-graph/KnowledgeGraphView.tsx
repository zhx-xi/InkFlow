/** F48 知识图谱 tab 装配视图（spec §5.4：工具栏「新建关系」+ 图谱/关系列表切换 +
 *  图谱画布（含空态引导）/ 关系列表；装配回调由 pages/library.tsx 提供）
 *  #1325：工具栏追加独立「全量节点」开关（图谱节点集范围 related/all）。 */
import { Plus } from 'lucide-react';
import type {
  GraphEdge,
  GraphNode,
  GraphScope,
  KnowledgeRelation,
} from '../../api/knowledge-graph';
import { useI18n } from '../../i18n/useI18n';
import { cn } from '../../lib/cn';
import { KnowledgeGraphCanvas } from './KnowledgeGraphCanvas';
import { RelationList } from './RelationList';

export interface KnowledgeGraphViewProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  relations: KnowledgeRelation[];
  view: 'graph' | 'list';
  onViewChange: (view: 'graph' | 'list') => void;
  onCreateRelation: () => void;
  onEditRelation: (relation: KnowledgeRelation) => void;
  onDeleteRelation: (relation: KnowledgeRelation) => void;
  onOpenEntity: (node: GraphNode) => void;
  onEditEdge: (edge: GraphEdge) => void;
  onDeleteEdge: (edge: GraphEdge) => void;
  /** 空态「去创建实体」引导目标（父级提供具体分类跳转） */
  onGoEntities: () => void;
  /** 图谱节点集范围（related=参与关系者 / all=六类全量） */
  scope?: GraphScope;
  onScopeChange?: (scope: GraphScope) => void;
  /** 拉线建关系：画布拖拽 Handle 连线时回调（source/target 为节点 id "<type>:<uuid>"） */
  onConnectNodes?: (source: string, target: string) => void;
  /** 画布位置持久化键（父级传 currentProjectId） */
  persistKey?: string;
  /** #1325：关系列表分页 —— 全量条数 / 当前页（0 基）/ 页大小 / 翻页回调（缺省 → 不渲染分页条） */
  relationTotal?: number;
  relationPage?: number;
  relationPageSize?: number;
  onRelationPageChange?: (page: number) => void;
}

export function KnowledgeGraphView({
  nodes,
  edges,
  relations,
  view,
  onViewChange,
  onCreateRelation,
  onEditRelation,
  onDeleteRelation,
  onOpenEntity,
  onEditEdge,
  onDeleteEdge,
  onGoEntities,
  scope,
  onScopeChange,
  onConnectNodes,
  persistKey,
  relationTotal,
  relationPage,
  relationPageSize,
  onRelationPageChange,
}: KnowledgeGraphViewProps) {
  const { t } = useI18n();
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          data-testid="library-kg-new-relation"
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          onClick={onCreateRelation}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          {t('lib.knowledge.newRelation')}
        </button>
        <div className="flex items-center gap-0.5 rounded-md border border-line bg-surface p-0.5">
          <button
            type="button"
            data-testid="library-kg-view-graph"
            aria-pressed={view === 'graph'}
            className={cn(
              'rounded px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              view === 'graph' ? 'bg-accent-weak font-medium text-accent' : 'text-ink-2 hover:text-ink',
            )}
            onClick={() => onViewChange('graph')}
          >
            {t('lib.knowledge.viewGraph')}
          </button>
          <button
            type="button"
            data-testid="library-kg-view-list"
            aria-pressed={view === 'list'}
            className={cn(
              'rounded px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              view === 'list' ? 'bg-accent-weak font-medium text-accent' : 'text-ink-2 hover:text-ink',
            )}
            onClick={() => onViewChange('list')}
          >
            {t('lib.knowledge.viewList')}
          </button>
        </div>
        {/* #1325：图谱节点集范围开关（独立按钮，不并入 view segmented 容器——
            该容器的 aria-pressed 契约只服务「图谱/列表」两态） */}
        <button
          type="button"
          data-testid="library-kg-scope-all"
          aria-pressed={scope === 'all'}
          className={cn(
            'rounded-md border border-line px-3 py-1.5 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            scope === 'all' ? 'bg-accent-weak font-medium text-accent' : 'text-ink-2 hover:text-ink',
          )}
          onClick={() => onScopeChange?.(scope === 'all' ? 'related' : 'all')}
        >
          {t('lib.knowledge.scopeAll')}
        </button>
      </div>
      {view === 'graph' ? (
        <>
          <KnowledgeGraphCanvas
            nodes={nodes}
            edges={edges}
            persistKey={persistKey}
            onConnectNodes={onConnectNodes}
            onOpenEntity={onOpenEntity}
            onEditEdge={onEditEdge}
            onDeleteEdge={onDeleteEdge}
          />
          {nodes.length === 0 && (
            <div
              data-testid="library-kg-empty"
              className="mt-3 flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-10 text-center"
            >
              <p className="font-serif text-[15px] font-semibold text-ink">{t('lib.knowledge.empty.title')}</p>
              <p className="mt-1 text-[12px] text-ink-2">{t('lib.knowledge.empty.guide')}</p>
              <button
                type="button"
                data-testid="library-kg-empty-cta"
                className="mt-3 rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={onGoEntities}
              >
                {t('lib.knowledge.empty.cta')}
              </button>
            </div>
          )}
        </>
      ) : (
        <RelationList
          relations={relations}
          entities={nodes}
          onEdit={onEditRelation}
          onDelete={onDeleteRelation}
          total={relationTotal}
          page={relationPage}
          pageSize={relationPageSize}
          onPageChange={onRelationPageChange}
        />
      )}
    </div>
  );
}
