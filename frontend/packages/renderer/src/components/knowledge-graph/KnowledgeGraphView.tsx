/** F48 知识图谱 tab 装配视图（spec §5.4：工具栏「新建关系」+ 图谱/关系列表切换 +
 *  图谱画布（含空态引导）/ 关系列表；装配回调由 pages/library.tsx 提供） */
import { Plus } from 'lucide-react';
import type { GraphEdge, GraphNode, KnowledgeRelation } from '../../api/knowledge-graph';
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
      </div>
      {view === 'graph' ? (
        <>
          <KnowledgeGraphCanvas
            nodes={nodes}
            edges={edges}
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
        />
      )}
    </div>
  );
}
