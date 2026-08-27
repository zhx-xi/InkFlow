/**
 * #378 地图工作台目录树（specs/f36-world-map/spec.md v1.4）：左栏地图目录树 + 原生 HTML5 拖拽层级。
 * 根图（parent_map_id null/undefined）→ 子图递归；拖到节点 = PATCH parent_map_id=目标 id；
 * 拖到空白区（map-tree-drop-zone）= parent_map_id=null；循环（拖到自身/子孙）拒绝 → onCycleReject()。
 * 同时保留 P1/P2 既有树契约（world-tree-toggle-* / world-map-badge-* / map-create-child-*），
 * 保证 library-p1/p2 回归（#376/#377 契约仍在）。
 */
import { useMemo, useRef, useState } from 'react';
import { ChevronRight, Copy, GripVertical, Map as MapIcon, MapPlus, Pencil, Trash2 } from 'lucide-react';
import { cn } from '../lib/cn';
import { useI18n } from '../i18n/useI18n';
import type { WorldCategoryEntity } from '../hooks/useWorldCategories';
import type { LibraryItemDTO } from './LibraryCreateDialog';
import type { WorldMapDTO } from './MapWorkbench';

/** 世界观条目树节点（F43 P1：parent_id 建树，E18 孤儿降级顶层） */
interface WorldTreeNode {
  item: LibraryItemDTO;
  children: WorldTreeNode[];
}

export interface MapDirectoryTreeProps {
  /** 地图列表（父侧 localMaps；parent_map_id 定义层级） */
  maps: WorldMapDTO[];
  /** 当前选中地图 id */
  activeMapId: string | null;
  onSelectMap: (mapId: string) => void;
  onCreateChild: (target: WorldMapDTO | LibraryItemDTO) => void;
  onDeleteMap: (map: WorldMapDTO) => void;
  onRenameMap: (map: WorldMapDTO, name?: string) => void;
  /** 拖拽改挂：parentMapId=null 表示变为根图 */
  onReparent: (mapId: string, parentMapId: string | null) => void;
  /** 循环拖拽被拒（不发 PATCH），由父级 toast */
  onCycleReject: () => void;
  // —— 兼容 P1/P2 树契约（library-p1/p2 既有断言；可缺省）——
  worldItems?: LibraryItemDTO[];
  /** #721：世界观分类实体（kind 分流——abstract 分类的条目不进树）；缺省 = 全量进树 */
  worldCategories?: WorldCategoryEntity[];
  collapsedIds?: Set<string | number>;
  onToggle?: (id: string | number) => void;
  onEdit?: (item: LibraryItemDTO) => void;
  onDelete?: (item: LibraryItemDTO) => void;
  onCopy?: (item: LibraryItemDTO) => void;
  pinCounts?: Record<string, number>;
}

/** F43 P1（§5.3）：items → 树（顶层 = parent_id null/缺失；孤儿降级顶层；按 items 顺序保序） */
function buildWorldTree(items: LibraryItemDTO[]): WorldTreeNode[] {
  const nodes = new Map<string | number, WorldTreeNode>();
  for (const item of items) {
    nodes.set(item.id, { item, children: [] });
  }
  const roots: WorldTreeNode[] = [];
  for (const item of items) {
    const node = nodes.get(item.id);
    if (!node) continue;
    const parentId = item.parent_id;
    if (parentId !== null && parentId !== undefined && nodes.has(parentId)) {
      nodes.get(parentId)!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

/** 地图树节点行：map-tree-node-<id> 行（缩进 = depth*18+12）+ 拖拽把手 + 🗺 徽标 + hover 操作 */
function MapTreeNodeRow({
  map,
  depth,
  childrenByParent,
  activeMapId,
  dragOverId,
  pinCounts,
  onSelectMap,
  onCreateChild,
  onDeleteMap,
  onRenameMap,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDragEnd,
  onDrop,
}: {
  map: WorldMapDTO;
  depth: number;
  childrenByParent: Map<string, WorldMapDTO[]>;
  activeMapId: string | null;
  dragOverId: string | null;
  pinCounts: Record<string, number>;
  onSelectMap: (mapId: string) => void;
  onCreateChild: (target: WorldMapDTO | LibraryItemDTO) => void;
  onDeleteMap: (map: WorldMapDTO) => void;
  onRenameMap: (map: WorldMapDTO, name?: string) => void;
  onDragStart: (mapId: string) => void;
  onDragOver: (mapId: string) => void;
  onDragLeave: (mapId: string) => void;
  onDragEnd: () => void;
  onDrop: (mapId: string) => void;
}) {
  const { t } = useI18n();
  const mapId = String(map.id);
  const isActive = activeMapId !== null && String(activeMapId) === mapId;
  const isOver = dragOverId === mapId;
  const childMaps = childrenByParent.get(mapId) ?? [];
  return (
    <div className="tree-node">
      <div
        data-testid={`map-tree-node-${mapId}`}
        className={cn(
          'tree-row group flex cursor-pointer items-center gap-2 px-3 py-2 text-[13px] text-ink transition-colors duration-150 hover:bg-surface-2/60',
          isActive && 'active bg-accent/5',
          isOver && 'bg-accent/10 ring-1 ring-inset ring-accent',
        )}
        style={{ paddingLeft: depth * 18 + 12 }}
        onClick={() => onSelectMap(mapId)}
        onDragOver={(e) => {
          e.preventDefault();
          onDragOver(mapId);
        }}
        onDragLeave={() => onDragLeave(mapId)}
        onDrop={(e) => {
          e.preventDefault();
          onDrop(mapId);
        }}
      >
        {/* 拖拽把手：原生 HTML5 DnD 源（dataTransfer 携带源图 id） */}
        <span
          data-testid={`map-tree-drag-${mapId}`}
          draggable
          title={t('lib.map.drag')}
          className="flex h-5 w-5 shrink-0 cursor-grab items-center justify-center rounded text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-accent active:cursor-grabbing"
          onDragStart={(e) => {
            e.dataTransfer.setData('text/plain', mapId);
            e.dataTransfer.effectAllowed = 'move';
            onDragStart(mapId);
          }}
          onDragEnd={onDragEnd}
        >
          <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        {/* 图标：根图 🗺 / 子图小图标区分 */}
        {depth === 0 ? (
          <span className="shrink-0 text-[13px]" aria-hidden="true">
            🗺
          </span>
        ) : (
          <span className="flex h-5 w-5 shrink-0 items-center justify-center" aria-hidden="true">
            <MapIcon className="h-3.5 w-3.5 text-ink-3" />
          </span>
        )}
        {/* 徽标兼容（P2 契约：world-map-badge-<mapId>；点击选中） */}
        <button
          type="button"
          data-testid={`world-map-badge-${mapId}`}
          aria-label={`${t('lib.worldMap')} ${map.name}`}
          title={map.name}
          className={cn(
            'flex shrink-0 items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[11px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            isActive
              ? 'border-accent bg-accent/10 text-accent'
              : 'border-line text-ink-2 hover:border-accent hover:text-accent',
          )}
          onClick={() => onSelectMap(mapId)}
        >
          <span aria-hidden="true">🗺</span>
          <span>{pinCounts[mapId] ?? 0}</span>
        </button>
        <span className="min-w-0 flex-1 whitespace-nowrap">{map.name}</span>
        {/* hover 操作区（#378 契约：map-tree-child/del/edit-<id>） */}
        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
          <button
            type="button"
            data-testid={`map-tree-child-${mapId}`}
            aria-label={`${t('lib.map.createChild')} ${map.name}`}
            title={t('lib.map.createChild')}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={(e) => {
              e.stopPropagation();
              onCreateChild(map);
            }}
          >
            <MapPlus className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid={`map-tree-del-${mapId}`}
            aria-label={`${t('lib.delete')} ${map.name}`}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={(e) => {
              e.stopPropagation();
              onDeleteMap(map);
            }}
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid={`map-tree-edit-${mapId}`}
            aria-label={`${t('lib.edit')} ${map.name}`}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={(e) => {
              e.stopPropagation();
              onRenameMap(map);
            }}
          >
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>
      {childMaps.map((child) => (
        <MapTreeNodeRow
          key={String(child.id)}
          map={child}
          depth={depth + 1}
          childrenByParent={childrenByParent}
          activeMapId={activeMapId}
          dragOverId={dragOverId}
          pinCounts={pinCounts}
          onSelectMap={onSelectMap}
          onCreateChild={onCreateChild}
          onDeleteMap={onDeleteMap}
          onRenameMap={onRenameMap}
          onDragStart={onDragStart}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDragEnd={onDragEnd}
          onDrop={onDrop}
        />
      ))}
    </div>
  );
}

/** 世界观条目行：无地图 → P1 行（toggle/编辑/删除/复制）；挂地图 → 地图目录树行（P2 徽标契约） */
function WorldNodeRow({
  node,
  depth,
  mapByLocation,
  childrenByParent,
  activeMapId,
  dragOverId,
  collapsedIds,
  pinCounts,
  onToggle,
  onEdit,
  onDelete,
  onCopy,
  onSelectMap,
  onCreateChild,
  onDeleteMap,
  onRenameMap,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDragEnd,
  onDrop,
}: {
  node: WorldTreeNode;
  depth: number;
  mapByLocation: Map<string, WorldMapDTO>;
  childrenByParent: Map<string, WorldMapDTO[]>;
  activeMapId: string | null;
  dragOverId: string | null;
  collapsedIds?: Set<string | number>;
  pinCounts: Record<string, number>;
  onToggle?: (id: string | number) => void;
  onEdit?: (item: LibraryItemDTO) => void;
  onDelete?: (item: LibraryItemDTO) => void;
  onCopy?: (item: LibraryItemDTO) => void;
  onSelectMap: (mapId: string) => void;
  onCreateChild: (target: WorldMapDTO | LibraryItemDTO) => void;
  onDeleteMap: (map: WorldMapDTO) => void;
  onRenameMap: (map: WorldMapDTO, name?: string) => void;
  onDragStart: (mapId: string) => void;
  onDragOver: (mapId: string) => void;
  onDragLeave: (mapId: string) => void;
  onDragEnd: () => void;
  onDrop: (mapId: string) => void;
}) {
  const { t } = useI18n();
  const { item, children } = node;
  // root_location_id 与树节点 id 字符串化比较（#368 契约）
  const linkedMap = mapByLocation.get(String(item.id)) ?? null;
  const hasChildren = children.length > 0;
  const isCollapsed = collapsedIds?.has(item.id) ?? false;
  const isActive =
    linkedMap !== null && activeMapId !== null && String(linkedMap.id) === String(activeMapId);
  const isOver = linkedMap !== null && dragOverId === String(linkedMap.id);
  const mapChildren = linkedMap ? childrenByParent.get(String(linkedMap.id)) ?? [] : [];
  return (
    <div className="tree-node">
      <div
        data-testid={linkedMap ? `map-tree-node-${linkedMap.id}` : undefined}
        className={cn(
          'tree-row group flex items-center gap-2 px-3 py-2 text-[13px] text-ink transition-colors duration-150 hover:bg-surface-2/60',
          linkedMap && 'cursor-pointer',
          isActive && 'active bg-accent/5',
          isOver && 'bg-accent/10 ring-1 ring-inset ring-accent',
        )}
        style={{ paddingLeft: depth * 18 + 12 }}
        onClick={linkedMap ? () => onSelectMap(String(linkedMap.id)) : undefined}
        onDragOver={
          linkedMap
            ? (e) => {
                e.preventDefault();
                onDragOver(String(linkedMap.id));
              }
            : undefined
        }
        onDragLeave={linkedMap ? () => onDragLeave(String(linkedMap.id)) : undefined}
        onDrop={
          linkedMap
            ? (e) => {
                e.preventDefault();
                onDrop(String(linkedMap.id));
              }
            : undefined
        }
      >
        {hasChildren ? (
          <button
            type="button"
            data-testid={`world-tree-toggle-${item.id}`}
            aria-label={isCollapsed ? t('nav.expand') : t('nav.collapse')}
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={(e) => {
              e.stopPropagation();
              onToggle?.(item.id);
            }}
          >
            <ChevronRight
              className={cn('h-3.5 w-3.5 transition-transform duration-180', !isCollapsed && 'rotate-90')}
              aria-hidden="true"
            />
          </button>
        ) : (
          <span className="h-5 w-5 shrink-0" aria-hidden="true" />
        )}
        {linkedMap && (
          <>
            <span
              data-testid={`map-tree-drag-${linkedMap.id}`}
              draggable
              title={t('lib.map.drag')}
              className="flex h-5 w-5 shrink-0 cursor-grab items-center justify-center rounded text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-accent active:cursor-grabbing"
              onDragStart={(e) => {
                e.dataTransfer.setData('text/plain', String(linkedMap.id));
                e.dataTransfer.effectAllowed = 'move';
                onDragStart(String(linkedMap.id));
              }}
              onDragEnd={onDragEnd}
            >
              <GripVertical className="h-3.5 w-3.5" aria-hidden="true" />
            </span>
            <button
              type="button"
              data-testid={`world-map-badge-${item.id}`}
              aria-label={`${t('lib.worldMap')} ${linkedMap.name}`}
              title={linkedMap.name}
              className={cn(
                'flex shrink-0 items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[11px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                isActive
                  ? 'border-accent bg-accent/10 text-accent'
                  : 'border-line text-ink-2 hover:border-accent hover:text-accent',
              )}
              onClick={() => onSelectMap(String(linkedMap.id))}
            >
              <span aria-hidden="true">🗺</span>
              <span>{pinCounts[String(linkedMap.id)] ?? 0}</span>
            </button>
          </>
        )}
        {/* #721：未挂图的世界观条目（geo）按地图根节点渲染——🗺 图标 + 可新建子图；不参与选中/拖拽 */}
        {!linkedMap && (
          <span className="shrink-0 text-[13px]" aria-hidden="true">
            🗺
          </span>
        )}
        {/* 名称：linkedMap 命中显示地图名（#368），否则显示条目名（P1 契约） */}
        <span className="min-w-0 flex-1 whitespace-nowrap">
          {linkedMap ? linkedMap.name : (item.name ?? '')}
        </span>
        {!linkedMap && item.category ? (
          <span className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2">
            {item.category}
          </span>
        ) : null}
        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
          {linkedMap ? (
            <>
              {/* #378 新建子图（map-tree-child-<mapId>）+ P2 兼容（map-create-child-<条目id>）双 testid 同语义 */}
              <span
                data-testid={`map-create-child-${item.id}`}
                title={t('lib.map.createChild')}
                onClick={(e) => {
                  e.stopPropagation();
                  onCreateChild(linkedMap);
                }}
                className="flex"
              >
                <button
                  type="button"
                  data-testid={`map-tree-child-${linkedMap.id}`}
                  aria-label={`${t('lib.map.createChild')} ${linkedMap.name}`}
                  className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCreateChild(linkedMap);
                  }}
                >
                  <MapPlus className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </span>
              <button
                type="button"
                data-testid={`map-tree-del-${linkedMap.id}`}
                aria-label={`${t('lib.delete')} ${linkedMap.name}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteMap(linkedMap);
                }}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              <button
                type="button"
                data-testid={`map-tree-edit-${linkedMap.id}`}
                aria-label={`${t('lib.edit')} ${linkedMap.name}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={(e) => {
                  e.stopPropagation();
                  onRenameMap(linkedMap);
                }}
              >
                <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </>
          ) : (
            <>
              {/* #721：无挂载图的世界观条目（geo）渲染为地图根节点——新建子图双 testid 同语义 */}
              <span
                data-testid={`map-create-child-${item.id}`}
                title={t('lib.map.createChild')}
                onClick={(e) => {
                  e.stopPropagation();
                  onCreateChild(item);
                }}
                className="flex"
              >
                <button
                  type="button"
                  data-testid={`map-tree-child-${item.id}`}
                  aria-label={`${t('lib.map.createChild')} ${item.name ?? ''}`}
                  className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCreateChild(item);
                  }}
                >
                  <MapPlus className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </span>
              <button
                type="button"
                data-testid={`lib-edit-${item.id}`}
                aria-label={`${t('lib.edit')} ${item.name ?? ''}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={(e) => {
                  e.stopPropagation();
                  onEdit?.(item);
                }}
              >
                <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              <button
                type="button"
                data-testid={`lib-delete-${item.id}`}
                aria-label={`${t('lib.delete')} ${item.name ?? ''}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete?.(item);
                }}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              <button
                type="button"
                data-testid={`world-copy-${item.id}`}
                aria-label={`${t('lib.copy.title')} ${item.name ?? ''}`}
                className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={(e) => {
                  e.stopPropagation();
                  onCopy?.(item);
                }}
              >
                <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </>
          )}
        </div>
      </div>
      {!isCollapsed &&
        children.map((child) => (
          <WorldNodeRow
            key={String(child.item.id)}
            node={child}
            depth={depth + 1}
            mapByLocation={mapByLocation}
            childrenByParent={childrenByParent}
            activeMapId={activeMapId}
            dragOverId={dragOverId}
            collapsedIds={collapsedIds}
            pinCounts={pinCounts}
            onToggle={onToggle}
            onEdit={onEdit}
            onDelete={onDelete}
            onCopy={onCopy}
            onSelectMap={onSelectMap}
            onCreateChild={onCreateChild}
            onDeleteMap={onDeleteMap}
            onRenameMap={onRenameMap}
            onDragStart={onDragStart}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDragEnd={onDragEnd}
            onDrop={onDrop}
          />
        ))}
      {linkedMap &&
        mapChildren.map((child) => (
          <MapTreeNodeRow
            key={String(child.id)}
            map={child}
            depth={depth + 1}
            childrenByParent={childrenByParent}
            activeMapId={activeMapId}
            dragOverId={dragOverId}
            pinCounts={pinCounts}
            onSelectMap={onSelectMap}
            onCreateChild={onCreateChild}
            onDeleteMap={onDeleteMap}
            onRenameMap={onRenameMap}
            onDragStart={onDragStart}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDragEnd={onDragEnd}
            onDrop={onDrop}
          />
        ))}
    </div>
  );
}

/** #378 地图目录树：地图为树主体（根图→子图→孙图，深度不限）+ 空白区拖拽变根图 + 循环校验 */
export function MapDirectoryTree({
  maps,
  activeMapId,
  onSelectMap,
  onCreateChild,
  onDeleteMap,
  onRenameMap,
  onReparent,
  onCycleReject,
  worldItems = [],
  worldCategories,
  collapsedIds,
  onToggle,
  onEdit,
  onDelete,
  onCopy,
  pinCounts = {},
}: MapDirectoryTreeProps) {
  const { t } = useI18n();
  const dragSourceRef = useRef<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  // parent_map_id → 子图列表（Map 缓存；递归渲染，深度不限）
  const childrenByParent = useMemo(() => {
    const map = new Map<string, WorldMapDTO[]>();
    for (const m of maps) {
      if (m.parent_map_id !== null && m.parent_map_id !== undefined) {
        const key = String(m.parent_map_id);
        const list = map.get(key) ?? [];
        list.push(m);
        map.set(key, list);
      }
    }
    return map;
  }, [maps]);

  // root_location_id → 地图（世界观树节点挂图徽标；#368 字符串化比较）
  const mapByLocation = useMemo(() => {
    const map = new Map<string, WorldMapDTO>();
    for (const m of maps) {
      if (m.root_location_id !== null && m.root_location_id !== undefined) {
        map.set(String(m.root_location_id), m);
      }
    }
    return map;
  }, [maps]);

  // #721：分类 kind 分流——abstract 分类的条目不进树；空/未知分类按 geo 处理（根/未分类世界观仍显示）
  const visibleWorldItems = useMemo(() => {
    const kindByCategory = new Map<string, 'geo' | 'abstract' | undefined>();
    for (const c of worldCategories ?? []) {
      kindByCategory.set(c.name, c.kind);
    }
    return worldItems.filter((item) => {
      const category = item.category ?? '';
      if (category === '') return true;
      return kindByCategory.get(category) !== 'abstract';
    });
  }, [worldItems, worldCategories]);

  const worldRoots = useMemo(() => buildWorldTree(visibleWorldItems), [visibleWorldItems]);
  const worldItemIds = useMemo(
    () => new Set(visibleWorldItems.map((i) => String(i.id))),
    [visibleWorldItems],
  );
  // 独立根图（无 parent_map_id 且未挂任何世界观条目 → 树顶层节点）
  const orphanMaps = useMemo(
    () =>
      maps.filter((m) => {
        if (m.parent_map_id !== null && m.parent_map_id !== undefined) return false;
        const locId = m.root_location_id;
        return locId === null || locId === undefined || !worldItemIds.has(String(locId));
      }),
    [maps, worldItemIds],
  );

  /** 沿 childrenByParent BFS：candidateId 是否为 ancestorId 的子孙（循环校验） */
  const isDescendant = (candidateId: string, ancestorId: string): boolean => {
    const queue: WorldMapDTO[] = [...(childrenByParent.get(ancestorId) ?? [])];
    const seen = new Set<string>();
    while (queue.length > 0) {
      const cur = queue.shift();
      if (!cur) continue;
      const id = String(cur.id);
      if (id === candidateId) return true;
      if (!seen.has(id)) {
        seen.add(id);
        queue.push(...(childrenByParent.get(id) ?? []));
      }
    }
    return false;
  };

  /** 拖到目标节点：自身/子孙 → 循环拒绝（不发 PATCH）；否则 onReparent(源id, 目标id) */
  const handleDropOnMap = (targetId: string) => {
    const sourceId = dragSourceRef.current;
    dragSourceRef.current = null;
    setDragOverId(null);
    if (sourceId === null) return;
    if (sourceId === targetId || isDescendant(targetId, sourceId)) {
      onCycleReject();
      return;
    }
    onReparent(sourceId, targetId);
  };

  /** 拖到空白区（map-tree-drop-zone）：变根图 → onReparent(源id, null) */
  const handleDropToRoot = () => {
    const sourceId = dragSourceRef.current;
    dragSourceRef.current = null;
    setDragOverId(null);
    if (sourceId === null) return;
    onReparent(sourceId, null);
  };

  const dragProps = {
    activeMapId,
    dragOverId,
    pinCounts,
    onSelectMap,
    onCreateChild,
    onDeleteMap,
    onRenameMap,
    onDragStart: (mapId: string) => {
      dragSourceRef.current = mapId;
    },
    onDragOver: (mapId: string) => setDragOverId(mapId),
    onDragLeave: (mapId: string) =>
      setDragOverId((prev) => (prev === mapId ? null : prev)),
    onDragEnd: () => {
      dragSourceRef.current = null;
      setDragOverId(null);
    },
    onDrop: (targetId: string) => handleDropOnMap(targetId),
  };

  return (
    <div data-testid="map-directory-tree" className="flex min-h-0 flex-col overflow-x-auto">
      <div className="min-h-0 flex-1">
        {worldRoots.length === 0 && orphanMaps.length === 0 ? (
          <div className="px-4 py-8 text-center text-[13px] text-ink-2">{t('common.empty')}</div>
        ) : (
          <>
            {worldRoots.map((node) => (
              <WorldNodeRow
                key={String(node.item.id)}
                node={node}
                depth={0}
                mapByLocation={mapByLocation}
                childrenByParent={childrenByParent}
                collapsedIds={collapsedIds}
                onToggle={onToggle}
                onEdit={onEdit}
                onDelete={onDelete}
                onCopy={onCopy}
                {...dragProps}
              />
            ))}
            {orphanMaps.map((m) => (
              <MapTreeNodeRow key={String(m.id)} map={m} depth={0} childrenByParent={childrenByParent} {...dragProps} />
            ))}
          </>
        )}
      </div>
      {/* 空白区：拖到此处 = parent_map_id=null（变根图） */}
      <div
        data-testid="map-tree-drop-zone"
        className="m-2 rounded-md border border-dashed border-line px-3 py-2 text-center text-[12px] text-ink-3 transition-colors duration-150 hover:border-accent hover:text-accent"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          handleDropToRoot();
        }}
      >
        {t('lib.map.dropRoot')}
      </div>
    </div>
  );
}
