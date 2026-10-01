/** F48 知识图谱 tab 装配视图（spec §5.4：工具栏「新建关系」+ 图谱/关系列表切换 +
 *  图谱画布（含空态引导）/ 关系列表；装配回调由 pages/library.tsx 提供）
 *  #1325：工具栏追加独立「全量节点」开关（图谱节点集范围 related/all）。 */
import { useEffect, useMemo, useState } from 'react';
import { Plus, Search } from 'lucide-react';
import type {
  EntityType,
  GraphEdge,
  GraphNode,
  GraphScope,
  KnowledgeRelation,
} from '../../api/knowledge-graph';
import { useI18n } from '../../i18n/useI18n';
import { cn } from '../../lib/cn';
import { DrawioIoControls } from './DrawioIoControls';
import { ENTITY_TYPE_KEYS, KnowledgeGraphCanvas } from './KnowledgeGraphCanvas';
import { deriveNodeColor, typeBaseDot } from './kgColor';
import {
  DEFAULT_KG_FILTER,
  KG_CATEGORIES,
  computeVisibleIds,
  readKgFilter,
  readKgPanel,
  visibleEdges,
  writeKgFilter,
  writeKgPanel,
  type KgFilterState,
} from './kgFilter';
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
  /** #1360：drawio 导入/导出所需项目 id（缺省 → 控件禁用） */
  projectId?: string;
  /** #1360：导入成功后回调（父侧 bump reloadKey 触发图谱重拉） */
  onImported?: () => void;
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
  projectId,
  onImported,
}: KnowledgeGraphViewProps) {
  const { t } = useI18n();

  /** #1373 筛选态（决策③：只在用户动作时写记忆；挂载时读一次） */
  const [filter, setFilter] = useState<KgFilterState>(() => readKgFilter(persistKey));
  /** 面板开合（无记忆 / 记忆为 open → 展开） */
  const [panelOpen, setPanelOpen] = useState<boolean>(() => readKgPanel() !== false);
  /** 搜索词（只过滤下方实体列表，不改画布） */
  const [query, setQuery] = useState('');

  /** 节点集到位后校验记忆里的实体仍存在（防「选中了不存在的实体」） */
  useEffect(() => {
    if (nodes.length === 0) return;
    setFilter((prev) =>
      prev.entity && !nodes.some((n) => n.id === prev.entity) ? { ...prev, entity: null } : prev,
    );
  }, [nodes]);

  const graphEmpty = nodes.length === 0;
  const filterActive = filter.category !== 'all' || filter.entity !== null;
  const visibleIds = useMemo(() => computeVisibleIds(nodes, edges, filter), [nodes, edges, filter]);
  const visibleNodes = useMemo(() => nodes.filter((n) => visibleIds.has(n.id)), [nodes, visibleIds]);
  const visibleEdgeList = useMemo(() => visibleEdges(edges, visibleIds), [edges, visibleIds]);
  /** 实体列表池：受搜索词收窄（不改画布可见集） */
  const entityPool = useMemo(() => {
    const q = query.trim();
    return q === '' ? nodes : nodes.filter((n) => n.name.includes(q));
  }, [nodes, query]);
  const selectedEntityName = filter.entity
    ? (nodes.find((n) => n.id === filter.entity)?.name ?? null)
    : null;
  const categoryLabel =
    filter.category === 'all' ? t('lib.knowledge.filter.all') : t(ENTITY_TYPE_KEYS[filter.category]);
  const filterLabel = selectedEntityName ? `${categoryLabel} · ${selectedEntityName}` : categoryLabel;
  const shownText = t('lib.knowledge.filter.shown', { n: visibleNodes.length });

  /** 类别单选：点同类取消（回「全部」）；切换类别时清空已选实体 */
  const selectCategory = (type: EntityType) => {
    const next: KgFilterState =
      filter.category === type ? { category: 'all', entity: null } : { category: type, entity: null };
    setFilter(next);
    writeKgFilter(persistKey, next);
  };
  /** 实体单选：点同一实体取消 */
  const toggleEntity = (id: string) => {
    const next: KgFilterState = {
      category: filter.category,
      entity: filter.entity === id ? null : id,
    };
    setFilter(next);
    writeKgFilter(persistKey, next);
  };
  const clearFilter = () => {
    const next: KgFilterState = { ...DEFAULT_KG_FILTER };
    setFilter(next);
    setQuery('');
    writeKgFilter(persistKey, next);
  };
  const setPanel = (open: boolean) => {
    setPanelOpen(open);
    writeKgPanel(open);
  };

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
        {/* #1360：drawio 导入 / 导出（spec §5.7） */}
        <DrawioIoControls projectId={projectId} onImported={onImported} />
      </div>
      {view === 'graph' ? (
        <div className="flex items-start gap-3" data-testid="library-kg-view">
          {/* #1373 左侧筛选面板（决策②：224px = Tailwind w-56；空态不渲染） */}
          {!graphEmpty && panelOpen && (
            <aside
              data-testid="library-kg-filter-panel"
              className="flex w-56 shrink-0 flex-col self-stretch rounded-lg border border-line bg-surface shadow-card"
            >
              {/* 搜索（只过滤下方实体列表，不改画布） */}
              <div className="flex flex-none items-center gap-1.5 border-b border-line px-2.5 py-2">
                <Search className="h-3.5 w-3.5 text-ink-3" aria-hidden="true" />
                <input
                  type="text"
                  data-testid="library-kg-filter-panel-search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t('lib.knowledge.filter.search')}
                  className="w-full border-none bg-transparent text-[12px] text-ink outline-none placeholder:text-ink-3"
                />
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto py-1">
                <div>
                  <div className="flex items-center justify-between px-2.5 pb-1 pt-0.5 text-[10px] font-medium uppercase tracking-wider text-ink-3">
                    <span>{t('lib.knowledge.filter.category')}</span>
                    <span data-testid="library-kg-filter-panel-cat-count">{KG_CATEGORIES.length}</span>
                  </div>
                  {/* 类别单选（点另一类替换；点同类取消） */}
                  {KG_CATEGORIES.map((type) => (
                    <label
                      key={type}
                      className="flex cursor-pointer items-center gap-1.5 px-2.5 py-1 text-[12px] text-ink-2 hover:bg-surface-2 hover:text-ink"
                    >
                      <input
                        type="checkbox"
                        data-testid={`library-kg-filter-panel-cat-${type}`}
                        checked={filter.category === type}
                        onChange={() => selectCategory(type)}
                        className="h-3.5 w-3.5 flex-none accent-accent"
                      />
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ backgroundColor: typeBaseDot(type) }}
                        aria-hidden="true"
                      />
                      <span className="truncate">{t(ENTITY_TYPE_KEYS[type])}</span>
                    </label>
                  ))}
                </div>
                <div>
                  <div className="flex items-center justify-between px-2.5 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wider text-ink-3">
                    <span>{t('lib.knowledge.filter.entity')}</span>
                    <span data-testid="library-kg-filter-panel-entity-count">{entityPool.length}</span>
                  </div>
                  {/* 实体单选（邻接子图 = 该实体 + 一跳邻居） */}
                  {entityPool.map((n) => (
                    <label
                      key={n.id}
                      className="flex cursor-pointer items-center gap-1.5 px-2.5 py-1 text-[12px] text-ink-2 hover:bg-surface-2 hover:text-ink"
                    >
                      <input
                        type="checkbox"
                        data-testid={`library-kg-filter-panel-entity-${n.type}-${n.entity_id}`}
                        checked={filter.entity === n.id}
                        onChange={() => toggleEntity(n.id)}
                        className="h-3.5 w-3.5 flex-none accent-accent"
                      />
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ backgroundColor: deriveNodeColor(n).dot }}
                        aria-hidden="true"
                      />
                      <span className="truncate">{n.name}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div
                data-testid="library-kg-filter-summary"
                className="flex-none truncate border-t border-line px-2.5 py-1.5 text-[11px] text-ink-3"
              >
                {t('lib.knowledge.filter.summary', { label: filterLabel, shown: shownText })}
              </div>
              <div className="flex flex-none items-center justify-between gap-2 border-t border-line px-2.5 py-2 text-[11px] text-ink-3">
                <button
                  type="button"
                  data-testid="library-kg-filter-collapse"
                  className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => setPanel(false)}
                >
                  {t('lib.knowledge.filter.collapse')}
                </button>
                <button
                  type="button"
                  data-testid="library-kg-filter-panel-clear"
                  className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={clearFilter}
                >
                  {t('lib.knowledge.filter.clear')}
                </button>
              </div>
            </aside>
          )}

          <div className="min-w-0 flex-1">
            {!graphEmpty && (
              <KnowledgeGraphCanvas
                nodes={visibleNodes}
                edges={visibleEdgeList}
                persistKey={persistKey}
                onConnectNodes={onConnectNodes}
                onOpenEntity={onOpenEntity}
                onEditEdge={onEditEdge}
                onDeleteEdge={onDeleteEdge}
                filterActive={filterActive && !graphEmpty}
                showLegend={!graphEmpty}
              />
            )}
            {/* 筛选无结果（图谱本身非空） */}
            {!graphEmpty && visibleNodes.length === 0 && (
              <div
                data-testid="library-kg-filter-empty"
                className="mt-3 rounded-lg border border-dashed border-line bg-surface px-6 py-8 text-center"
              >
                <p className="text-[13px] text-ink-2">{t('lib.knowledge.filter.empty')}</p>
              </div>
            )}
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

            {/* 折叠态：底部折叠栏（决策②：零横向占用，画布全宽） */}
            {!graphEmpty && !panelOpen && (
              <div
                data-testid="library-kg-filterbar"
                className={cn(
                  'mt-3 flex items-center gap-2 rounded-lg border bg-surface px-3 py-1.5 text-[12px] text-ink-2 shadow-card',
                  filterActive ? 'border-accent' : 'border-line',
                )}
              >
                <Search className="h-3.5 w-3.5 flex-none text-ink-3" aria-hidden="true" />
                <span
                  data-testid="library-kg-filterbar-summary"
                  className={cn('min-w-0 truncate', filterActive && 'font-medium text-accent')}
                >
                  {t('lib.knowledge.filterbar.summary', { label: filterLabel, shown: shownText })}
                </span>
                <span className="flex-1" />
                <button
                  type="button"
                  data-testid="library-kg-filterbar-clear"
                  className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={clearFilter}
                >
                  {t('lib.knowledge.filter.clear')}
                </button>
                <button
                  type="button"
                  data-testid="library-kg-filterbar-expand"
                  className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => setPanel(true)}
                >
                  {t('lib.knowledge.filter.expand')}
                </button>
              </div>
            )}
          </div>
        </div>
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
