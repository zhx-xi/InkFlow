/** F48 知识图谱 tab 装配视图（spec §5.4：工具栏「新建关系」+ 图谱/关系列表切换 +
 *  图谱画布（含空态引导）/ 关系列表；装配回调由 pages/library.tsx 提供）
 *  #1325：工具栏追加独立「全量节点」开关（图谱节点集范围 related/all）。 */
import { useEffect, useMemo, useState } from 'react';
import { Check, ChevronsRight, Plus, Search, X } from 'lucide-react';
import type {
  EntityType,
  GraphEdge,
  GraphNode,
  GraphScope,
  KnowledgeRelation,
} from '../../api/knowledge-graph';
import { useI18n } from '../../i18n/useI18n';
import { cn } from '../../lib/cn';
import { Pagination } from '../Pagination';
import { DrawioIoControls } from './DrawioIoControls';
import { ENTITY_TYPE_KEYS, KnowledgeGraphCanvas } from './KnowledgeGraphCanvas';
import { deriveNodeColor, typeBaseDot } from './kgColor';
import {
  DEFAULT_KG_FILTER,
  KG_CATEGORIES,
  computeHiddenIds,
  computeVisibleIds,
  readKgFilter,
  readKgPanel,
  reconcileKgFilter,
  sortByEntityName,
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
  /** #1529：分类块 / 实体块各一套分页状态（page 0 基，两块互不相干） */
  const [catPage, setCatPage] = useState(0);
  const [catPageSize, setCatPageSize] = useState(10);
  const [entityPage, setEntityPage] = useState(0);
  const [entityPageSize, setEntityPageSize] = useState(10);

  /** #1529：节点集变化 → 收敛记忆里的幽灵实体（无变化返回原引用，不触发重渲染） */
  useEffect(() => {
    setFilter((prev) => reconcileKgFilter(prev, new Set(nodes.map((n) => n.id))));
  }, [nodes]);

  const graphEmpty = nodes.length === 0;
  // #1529：判据统一——类别少勾 或 实体非全选（entities !== null）即视为筛选生效
  const filterActive =
    filter.categories.length < KG_CATEGORIES.length || filter.entities !== null;
  /** #1529：画布不再摘除节点/边——只算「高亮（正常彩色）节点集」，未高亮者由画布降灰
   *  #1568：实体定向激活时另算「隐藏集」（三态：彩色/灰显保位/隐藏） */
  const activeIds = useMemo(() => computeVisibleIds(nodes, edges, filter), [nodes, edges, filter]);
  const hiddenIds = useMemo(() => computeHiddenIds(nodes, edges, filter), [nodes, edges, filter]);
  /** 实体列表池（#1529）：已勾选类别 ∩ 搜索词 → 拼音序（纯前端分页切片，不改画布高亮） */
  const entityPool = useMemo(() => {
    const q = query.trim();
    return sortByEntityName(
      nodes.filter((n) => filter.categories.includes(n.type) && (q === '' || n.name.includes(q))),
    );
  }, [nodes, query, filter.categories]);
  /** 实体池变化（类别勾选 / 搜索词）→ 实体块回第 1 页（分类块分页不受影响） */
  useEffect(() => {
    setEntityPage(0);
  }, [entityPool]);
  const entityRows = entityPool.slice(entityPage * entityPageSize, (entityPage + 1) * entityPageSize);
  /** 分类块（#1529）：6 条自带一套分页 —— 常态 ≤ 每页条数 → 分页条不出场 */
  const catRows = KG_CATEGORIES.slice(catPage * catPageSize, (catPage + 1) * catPageSize);
  const categoryLabel =
    filter.categories.length === KG_CATEGORIES.length
      ? t('lib.knowledge.filter.all')
      : /* #1568：「全部取消」后类别为空 → 读「无」（否则摘要留空档「筛选： · …」） */
        filter.categories.length === 0
        ? t('lib.knowledge.filter.none')
        : filter.categories.map((type) => t(ENTITY_TYPE_KEYS[type])).join('/');
  /** 实体非全选时在标签后附「 · 实体 已选/总数」 */
  const filterLabel =
    filter.entities === null
      ? categoryLabel
      : `${categoryLabel} · ${t('lib.knowledge.filter.entity')} ${filter.entities.length}/${nodes.length}`;
  const shownText = t('lib.knowledge.filter.shown', { n: activeIds.size });

  /** 类别多选（#1465）：切换某类（取消 = 该类降灰 / 勾回 = 恢复）；
   *  #1529：**不再清空实体选择**（消隐改降灰后不存在「选中了看不见的实体」） */
  const toggleCategory = (type: EntityType) => {
    const categories = filter.categories.includes(type)
      ? filter.categories.filter((t) => t !== type)
      : KG_CATEGORIES.filter((t) => t === type || filter.categories.includes(t));
    const next: KgFilterState = { categories, entities: filter.entities };
    setFilter(next);
    writeKgFilter(persistKey, next);
  };
  /** 实体多选（#1529）：按「当前有效集合」（`entities ?? 全部节点 id`）翻转；
   *  勾满 = 塌缩为 `null`（全选同义），避免与默认态两种表示并存 */
  const toggleEntity = (id: string) => {
    const effective = filter.entities ?? nodes.map((n) => n.id);
    const flipped = effective.includes(id)
      ? effective.filter((x) => x !== id)
      : [...effective, id];
    const next: KgFilterState = {
      categories: filter.categories,
      entities: flipped.length === nodes.length ? null : flipped,
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
  /** #1568：「全选」的**反义入口** —— 取消所有选中（类别 + 实体全不选；画布走筛选空态） */
  const cancelAllFilter = () => {
    const next: KgFilterState = { categories: [], entities: [] };
    setFilter(next);
    setQuery('');
    setEntityPage(0);
    setCatPage(0);
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
              className="flex h-[520px] w-56 shrink-0 flex-col rounded-lg border border-line bg-surface shadow-card"
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
              {/* 块① 类别（#1529：独立滚动体 + 自带一套分页；点某类 = 取消/勾回该类，多选非替换） */}
              <div className="flex min-h-0 flex-1 flex-col border-b border-line">
                <div className="flex flex-none items-center justify-between px-2.5 pb-1 pt-1.5 text-[10px] font-medium uppercase tracking-wider text-ink-3">
                  <span>{t('lib.knowledge.filter.category')}</span>
                  <span data-testid="library-kg-filter-panel-cat-count">{KG_CATEGORIES.length}</span>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto pb-1">
                  {catRows.map((type) => (
                    <label
                      key={type}
                      className="flex cursor-pointer items-center gap-1.5 px-2.5 py-1 text-[12px] text-ink-2 hover:bg-surface-2 hover:text-ink"
                    >
                      <input
                        type="checkbox"
                        data-testid={`library-kg-filter-panel-cat-${type}`}
                        checked={filter.categories.includes(type)}
                        onChange={() => toggleCategory(type)}
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
                {KG_CATEGORIES.length > catPageSize && (
                  <div data-testid="library-kg-cat-page" className="flex-none border-t border-line px-1.5 py-1">
                    <Pagination
                      compact
                      page={catPage}
                      pageSize={catPageSize}
                      total={KG_CATEGORIES.length}
                      onPageChange={setCatPage}
                      onPageSizeChange={setCatPageSize}
                      testIdPrefix="library-kg-cat-page"
                    />
                  </div>
                )}
              </div>
              {/* 块② 实体（#1529：多选集合、拼音序、独立滚动体 + 独立分页与每页条数） */}
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="flex flex-none items-center justify-between px-2.5 pb-1 pt-1.5 text-[10px] font-medium uppercase tracking-wider text-ink-3">
                  <span>{t('lib.knowledge.filter.entity')}</span>
                  <span data-testid="library-kg-filter-panel-entity-count">{entityPool.length}</span>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto pb-1">
                  {entityRows.map((n) => (
                    <label
                      key={n.id}
                      data-testid={`library-kg-filter-panel-entity-${n.type}-${n.entity_id}`}
                      className="flex cursor-pointer items-center gap-1.5 px-2.5 py-1 text-[12px] text-ink-2 hover:bg-surface-2 hover:text-ink"
                    >
                      <input
                        type="checkbox"
                        checked={filter.entities === null || filter.entities.includes(n.id)}
                        onChange={() => toggleEntity(n.id)}
                        className="h-3.5 w-3.5 flex-none accent-accent"
                      />
                      <span
                        className="h-2 w-2 shrink-0 rounded-full"
                        style={{ backgroundColor: deriveNodeColor(n).dot }}
                        aria-hidden="true"
                      />
                      <span className="nm truncate">{n.name}</span>
                    </label>
                  ))}
                </div>
                {entityPool.length > entityPageSize && (
                  <div data-testid="library-kg-entity-page" className="flex-none border-t border-line px-1.5 py-1">
                    <Pagination
                      compact
                      page={entityPage}
                      pageSize={entityPageSize}
                      total={entityPool.length}
                      onPageChange={setEntityPage}
                      onPageSizeChange={setEntityPageSize}
                      testIdPrefix="library-kg-entity-page"
                    />
                  </div>
                )}
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
                {/* #1568：「全部取消」与「全选」并列（两态分开，不混用一个入口） */}
                <button
                  type="button"
                  data-testid="library-kg-filter-panel-cancel-all"
                  className="rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={cancelAllFilter}
                >
                  {t('lib.knowledge.filter.cancelAll')}
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

          {/* #1465 折叠态：画布**左侧**竖状筛选条（明确展开按钮 + 六类圆点 + 清除；高与画布等高） */}
          {!graphEmpty && !panelOpen && (
            <aside
              data-testid="library-kg-filterbar"
              className={cn(
                'flex h-[520px] w-[46px] shrink-0 flex-col items-center gap-1.5 rounded-lg border bg-surface py-2 shadow-card',
                filterActive ? 'border-accent' : 'border-line',
              )}
            >
              <button
                type="button"
                data-testid="library-kg-filterbar-expand"
                aria-label={t('lib.knowledge.filter.expand')}
                title={t('lib.knowledge.filter.expand')}
                className="flex h-7 w-7 flex-none items-center justify-center rounded-md border border-line text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => setPanel(true)}
              >
                <ChevronsRight className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              <span className="h-px w-5 flex-none bg-line" aria-hidden="true" />
              <div className="flex min-h-0 flex-1 flex-col items-center gap-2 overflow-y-auto py-0.5">
                {KG_CATEGORIES.map((type) => (
                  <button
                    key={type}
                    type="button"
                    data-testid={`library-kg-rail-dot-${type}`}
                    aria-pressed={filter.categories.includes(type)}
                    title={t(ENTITY_TYPE_KEYS[type])}
                    className={cn(
                      'h-3.5 w-3.5 flex-none rounded-full transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      !filter.categories.includes(type) && 'opacity-25',
                    )}
                    style={{ backgroundColor: typeBaseDot(type) }}
                    onClick={() => toggleCategory(type)}
                  />
                ))}
              </div>
              {/* #1568：「全部取消」（✕）与「全选」（✓）并列——与面板底部同语义 */}
              <button
                type="button"
                data-testid="library-kg-filterbar-cancel-all"
                aria-label={t('lib.knowledge.filter.cancelAll')}
                title={t('lib.knowledge.filter.cancelAll')}
                className="flex h-7 w-7 flex-none items-center justify-center rounded-md border border-line text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={cancelAllFilter}
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              <button
                type="button"
                data-testid="library-kg-filterbar-clear"
                aria-label={t('lib.knowledge.filter.clear')}
                title={t('lib.knowledge.filter.clear')}
                className="flex h-7 w-7 flex-none items-center justify-center rounded-md border border-line text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={clearFilter}
              >
                <Check className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              <span data-testid="library-kg-filterbar-summary" className="sr-only">
                {t('lib.knowledge.filterbar.summary', { label: filterLabel, shown: shownText })}
              </span>
            </aside>
          )}
          <div className="min-w-0 flex-1">
            {!graphEmpty && (
              <KnowledgeGraphCanvas
                nodes={nodes}
                edges={edges}
                activeIds={activeIds}
                hiddenIds={hiddenIds}
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
            {!graphEmpty && activeIds.size === 0 && (
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
