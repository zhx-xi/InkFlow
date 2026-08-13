/**
 * F43 P2 地图工作台（specs/f43-setting-library-crud/spec.md §5.8-5.12）：
 * 世界观 tab 工作台态——四级面包屑回跳（设定库/世界观/地图视图/{地图名}）+
 * 左侧世界观树（P1 树渲染复用：parent_id 建树 + 分类 chips + 复制/编辑/删除；
 * 地图节点渲染 🗺 world-map-badge-<节点id> + pin 数徽标）+ 右侧画布/pin 列表。
 * pins 增删改（POST/PATCH/DELETE）、底图切换（PATCH bg_source）、shapes 持久化
 * （PATCH extra.shapes）均在组件内完成（消费方契约 library-p2.test.tsx 覆盖）。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, Copy, Pencil, Trash2 } from 'lucide-react';
import { apiFetch, errorMessage } from '../api/client';
import { cn } from '../lib/cn';
import { useI18n } from '../i18n/useI18n';
import { useToastStore } from '../stores/toast';
import { ConfirmDialog } from './ConfirmDialog';
import type { LibraryItemDTO } from './LibraryCreateDialog';
import { MapCanvas } from './MapCanvas';
import { PinDialog, type PinRefOption, type PinSaveInput } from './PinDialog';

export type MapBgSource = 'shape' | 'image' | 'ai';
export type PinType = 'location' | 'role' | 'event' | 'other';

/** 地图 DTO（F36 §2.3 + F43 P2 §2.7.2：bg_source/extra） */
export interface WorldMapDTO {
  id: string | number;
  project_id: string | number;
  name: string;
  image_path?: string;
  description?: string;
  root_location_id?: string | number | null;
  bg_source?: MapBgSource;
  extra?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

/** pin DTO（F36 §2.3 + F43 P2 §2.7.1：type/ref_id） */
export interface MapPinDTO {
  id: string | number;
  map_id: string | number;
  location_id?: string | number | null;
  ref_id?: string | number | null;
  type?: PinType;
  x: number;
  y: number;
  label: string;
  created_at?: string;
  updated_at?: string;
}

/** 简图形状（F43 P2 §2.7.2 shapes 结构） */
export interface MapShape {
  id: string;
  type: 'rect' | 'ellipse' | 'text';
  x: number;
  y: number;
  w?: number;
  h?: number;
  label: string;
}

export interface MapWorkbenchProps {
  projectId: string;
  /** 世界观树 items（含 parent_id） */
  worldItems: LibraryItemDTO[];
  /** 地图列表（含 root_location_id 关联地点） */
  maps: WorldMapDTO[];
  /** 当前选中地图 id */
  activeMapId: string | null;
  onSelectMap: (mapId: string) => void;
  /** 面包屑层级 1/2 回跳（退出工作台） */
  onExitWorkbench: () => void;
  /** 面包屑层级 3 回跳（清空选中地图） */
  onClearMap: () => void;
  // ── P1 树交互（library.tsx 既有状态/回调复用）──
  worldCategories: string[];
  activeWorldCat: string | null;
  onWorldCatChange: (cat: string | null) => void;
  collapsedIds: Set<string | number>;
  onToggle: (id: string | number) => void;
  onEdit: (item: LibraryItemDTO) => void;
  onDelete: (item: LibraryItemDTO) => void;
  onCopy: (item: LibraryItemDTO) => void;
  onCopyAll: () => void;
  copyTargetOptions: { id: string; name: string }[];
}

interface PinListResponse {
  items: MapPinDTO[];
  total: number;
  offset: number;
  limit: number;
}

interface WorldTreeNode {
  item: LibraryItemDTO;
  children: WorldTreeNode[];
}

const PIN_TYPES: PinType[] = ['location', 'role', 'event', 'other'];

/** P1 §5.3：items → 树（顶层 = parent_id null/缺失；孤儿降级顶层；按 items 顺序保序） */
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

/** extra.shapes 防御性提取（脏数据兜底空数组） */
function extractShapes(map: WorldMapDTO): MapShape[] {
  const raw = map.extra?.shapes;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (s): s is MapShape =>
      typeof s === 'object' &&
      s !== null &&
      typeof (s as MapShape).id === 'string' &&
      ['rect', 'ellipse', 'text'].includes((s as MapShape).type),
  );
}

/** 工作台树节点视图（P1 树渲染 + P2 🗺 地图徽标；悬停操作按钮与 P1 同款 testid） */
function WorkbenchNodeView({
  node,
  depth,
  collapsed,
  mapByLocation,
  pinCounts,
  activeMapId,
  onToggle,
  onEdit,
  onDelete,
  onCopy,
  onSelectMap,
}: {
  node: WorldTreeNode;
  depth: number;
  collapsed: Set<string | number>;
  mapByLocation: Map<string, WorldMapDTO>;
  pinCounts: Record<string, number>;
  activeMapId: string | null;
  onToggle: (id: string | number) => void;
  onEdit: (item: LibraryItemDTO) => void;
  onDelete: (item: LibraryItemDTO) => void;
  onCopy: (item: LibraryItemDTO) => void;
  onSelectMap: (mapId: string) => void;
}) {
  const { t } = useI18n();
  const { item, children } = node;
  const hasChildren = children.length > 0;
  const isCollapsed = collapsed.has(item.id);
  // root_location_id 与树节点 id 字符串化比较（String === String，契约）
  const linkedMap = mapByLocation.get(String(item.id)) ?? null;
  const isActive =
    linkedMap !== null && activeMapId !== null && String(linkedMap.id) === String(activeMapId);
  return (
    <div className="tree-node">
      <div
        className="tree-row group flex items-center gap-2 px-3 py-2 text-[13px] text-ink transition-colors duration-150 hover:bg-surface-2/60"
        style={{ paddingLeft: depth * 18 + 12 }}
      >
        {hasChildren ? (
          <button
            type="button"
            data-testid={`world-tree-toggle-${item.id}`}
            aria-label={isCollapsed ? t('nav.expand') : t('nav.collapse')}
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onToggle(item.id)}
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
        )}
        <span className="min-w-0 flex-1 truncate">{item.name ?? ''}</span>
        {item.category ? (
          <span className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2">
            {item.category}
          </span>
        ) : null}
        {/* P1 行内操作按钮（D12 悬停显示；testid 与普通树视图一致） */}
        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
          <button
            type="button"
            data-testid={`lib-edit-${item.id}`}
            aria-label={`${t('lib.edit')} ${item.name ?? ''}`}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onEdit(item)}
          >
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid={`lib-delete-${item.id}`}
            aria-label={`${t('lib.delete')} ${item.name ?? ''}`}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onDelete(item)}
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            data-testid={`world-copy-${item.id}`}
            aria-label={`${t('lib.copy.title')} ${item.name ?? ''}`}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onCopy(item)}
          >
            <Copy className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>
      {!isCollapsed &&
        children.map((child) => (
          <WorkbenchNodeView
            key={String(child.item.id)}
            node={child}
            depth={depth + 1}
            collapsed={collapsed}
            mapByLocation={mapByLocation}
            pinCounts={pinCounts}
            activeMapId={activeMapId}
            onToggle={onToggle}
            onEdit={onEdit}
            onDelete={onDelete}
            onCopy={onCopy}
            onSelectMap={onSelectMap}
          />
        ))}
    </div>
  );
}

export function MapWorkbench({
  projectId,
  worldItems,
  maps,
  activeMapId,
  onSelectMap,
  onExitWorkbench,
  onClearMap,
  worldCategories,
  activeWorldCat,
  onWorldCatChange,
  collapsedIds,
  onToggle,
  onEdit,
  onDelete,
  onCopy,
  onCopyAll,
  copyTargetOptions,
}: MapWorkbenchProps) {
  const { t } = useI18n();
  // 本地地图副本：底图切换 / shapes 持久化后回写（props 仅在父级重拉时同步）
  const [localMaps, setLocalMaps] = useState<WorldMapDTO[]>(maps);
  const [pins, setPins] = useState<MapPinDTO[]>([]);
  const [pinCounts, setPinCounts] = useState<Record<string, number>>({});
  const [pinFilter, setPinFilter] = useState<PinType | null>(null);
  const [pinDialog, setPinDialog] = useState<{
    open: boolean;
    editing: MapPinDTO | null;
    defaultX: number;
    defaultY: number;
  }>({ open: false, editing: null, defaultX: 0, defaultY: 0 });
  const [pendingDeletePin, setPendingDeletePin] = useState<MapPinDTO | null>(null);
  const [refLists, setRefLists] = useState<{
    characters: Array<{ id: string | number; name?: string }>;
    timeline: Array<{ id: string | number; name?: string; title?: string }>;
  }>({ characters: [], timeline: [] });
  const shapeIdCounterRef = useRef(0);

  useEffect(() => {
    setLocalMaps(maps);
  }, [maps]);

  const activeMap =
    activeMapId === null
      ? null
      : (localMaps.find((m) => String(m.id) === String(activeMapId)) ?? null);

  // 选中地图 → 拉取 pins（独立叠加层；切换底图不重拉）
  useEffect(() => {
    if (!activeMapId) {
      setPins([]);
      return;
    }
    let cancelled = false;
    void apiFetch<PinListResponse>(`/api/v1/maps/${activeMapId}/pins`)
      .then((data) => {
        if (cancelled) return;
        const list = data.items ?? [];
        setPins(list);
        setPinCounts((prev) => ({ ...prev, [String(activeMapId)]: list.length }));
      })
      .catch(() => {
        if (!cancelled) setPins([]);
      });
    return () => {
      cancelled = true;
    };
  }, [activeMapId]);

  // P1：世界观树（parent_id 建树）+ 分类筛选作用于顶层（含子树整体显隐）
  const worldRoots = useMemo(() => buildWorldTree(worldItems), [worldItems]);
  const filteredWorldRoots = useMemo(
    () =>
      activeWorldCat === null
        ? worldRoots
        : worldRoots.filter((node) => node.item.category === activeWorldCat),
    [activeWorldCat, worldRoots],
  );
  const mapByLocation = useMemo(() => {
    const map = new Map<string, WorldMapDTO>();
    for (const m of localMaps) {
      if (m.root_location_id !== null && m.root_location_id !== undefined) {
        map.set(String(m.root_location_id), m);
      }
    }
    return map;
  }, [localMaps]);

  // 关联实体候选（worldItems 本地已加载；characters/timeline 按需拉取）
  const refOptions = useMemo<PinRefOption[]>(
    () => [
      ...worldItems.map((i) => ({
        id: String(i.id),
        name: i.name ?? i.title ?? '',
        type: 'location' as const,
      })),
      ...refLists.characters.map((c) => ({
        id: String(c.id),
        name: String(c.name ?? ''),
        type: 'role' as const,
      })),
      ...refLists.timeline.map((tl) => ({
        id: String(tl.id),
        name: String(tl.title ?? tl.name ?? ''),
        type: 'event' as const,
      })),
    ],
    [worldItems, refLists],
  );

  const ensureRefLists = () => {
    void (async () => {
      try {
        const [chars, timeline] = await Promise.all([
          apiFetch<{ items?: Array<{ id: string | number; name?: string }> }>(
            `/api/v1/projects/${projectId}/characters`,
          ),
          apiFetch<{
            items?: Array<{ id: string | number; name?: string; title?: string }>;
            event_timeline?: Array<{ id: string | number; name?: string; title?: string }>;
          }>(`/api/v1/projects/${projectId}/timeline`),
        ]);
        setRefLists({
          characters: chars.items ?? [],
          timeline: timeline.items ?? timeline.event_timeline ?? [],
        });
      } catch {
        // 关联列表加载失败不阻塞对话框（本地空列表，仍可保存纯标记）
      }
    })();
  };

  const refreshPins = async () => {
    if (!activeMapId) return;
    try {
      const data = await apiFetch<PinListResponse>(`/api/v1/maps/${activeMapId}/pins`);
      const list = data.items ?? [];
      setPins(list);
      setPinCounts((prev) => ({ ...prev, [String(activeMapId)]: list.length }));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  const openNewPin = (x: number, y: number) => {
    setPinDialog({ open: true, editing: null, defaultX: x, defaultY: y });
    ensureRefLists();
  };

  const openEditPin = (pin: MapPinDTO) => {
    setPinDialog({ open: true, editing: pin, defaultX: pin.x, defaultY: pin.y });
    ensureRefLists();
  };

  /** 保存 pin：新建 POST /maps/{id}/pins；编辑 PATCH /map-pins/{id}（label 必含，exclude_unset 语义） */
  const handlePinSave = async (input: PinSaveInput) => {
    if (!activeMap) return;
    try {
      if (pinDialog.editing) {
        const body: Record<string, unknown> = {
          label: input.label,
          type: input.type,
          x: input.x,
          y: input.y,
        };
        if (input.type === 'location') body.location_id = input.locationId ?? null;
        else body.ref_id = input.refId ?? null;
        await apiFetch(`/api/v1/map-pins/${pinDialog.editing.id}`, { method: 'PATCH', body });
      } else {
        const body: Record<string, unknown> = {
          type: input.type,
          x: input.x,
          y: input.y,
          label: input.label,
        };
        if (input.type === 'location' && input.locationId) body.location_id = input.locationId;
        else if ((input.type === 'role' || input.type === 'event') && input.refId) {
          body.ref_id = input.refId;
        }
        await apiFetch(`/api/v1/maps/${activeMap.id}/pins`, { method: 'POST', body });
      }
      setPinDialog({ open: false, editing: null, defaultX: 0, defaultY: 0 });
      useToastStore.getState().pushToast('ok', t('toast.saved'));
      await refreshPins();
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  /** 删除 pin：真删 → 刷新列表 + ok toast */
  const handleDeletePin = async () => {
    if (!pendingDeletePin) return;
    const target = pendingDeletePin;
    try {
      await apiFetch(`/api/v1/map-pins/${target.id}`, { method: 'DELETE' });
      setPendingDeletePin(null);
      useToastStore.getState().pushToast('ok', t('toast.saved'));
      await refreshPins();
    } catch (err) {
      setPendingDeletePin(null);
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  /** 底图切换：只 PATCH bg_source（pin 独立叠加层 D-18，不触碰 pins/extra） */
  const handleChangeBg = async (bgSource: MapBgSource) => {
    if (!activeMap) return;
    try {
      const updated = await apiFetch<WorldMapDTO | undefined>(`/api/v1/maps/${activeMap.id}`, {
        method: 'PATCH',
        body: { bg_source: bgSource },
      });
      setLocalMaps((prev) =>
        prev.map((m) =>
          String(m.id) === String(activeMap.id) ? (updated ? { ...m, ...updated } : { ...m, bg_source: bgSource }) : m,
        ),
      );
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  /** shapes 持久化：整体替换 PATCH extra.shapes + 回写本地地图 */
  const handleUpdateShapes = async (shapes: MapShape[]) => {
    if (!activeMap) return;
    try {
      const updated = await apiFetch<WorldMapDTO | undefined>(`/api/v1/maps/${activeMap.id}`, {
        method: 'PATCH',
        body: { extra: { shapes } },
      });
      setLocalMaps((prev) =>
        prev.map((m) => {
          if (String(m.id) !== String(activeMap.id)) return m;
          if (updated) return { ...m, ...updated };
          return { ...m, extra: { ...(m.extra ?? {}), shapes } };
        }),
      );
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  /** 添加形状：父级按 map.extra.shapes 追加（s_<timestamp> 前缀 id）+ 整体替换持久化 */
  const handleAddShape = async (type: 'rect' | 'ellipse' | 'text') => {
    if (!activeMap) return;
    shapeIdCounterRef.current += 1;
    const id = `s_${Date.now()}_${shapeIdCounterRef.current}`;
    const shape: MapShape =
      type === 'text'
        ? { id, type, x: 45, y: 45, label: t('lib.shape.newText') }
        : { id, type, x: 35, y: 35, w: 24, h: 16, label: t('lib.shape.newLabel') };
    await handleUpdateShapes([...extractShapes(activeMap), shape]);
  };

  const linkedName = (pin: MapPinDTO): string => {
    const pinType = pin.type ?? 'location';
    const linkedId = pinType === 'location' ? pin.location_id : pin.ref_id;
    if (linkedId === null || linkedId === undefined) return '';
    const opt = refOptions.find((o) => o.type === pinType && o.id === String(linkedId));
    return opt?.name ?? '';
  };

  const filteredPins =
    pinFilter === null ? pins : pins.filter((p) => (p.type ?? 'location') === pinFilter);

  return (
    <div data-testid="map-workbench" className="space-y-3">
      {/* 四级面包屑：设定库 / 世界观 / 地图视图 / {地图名}（层级 1/2 → 退出，3 → 清空选中） */}
      <div data-testid="map-breadcrumb" className="flex items-center gap-1 text-[13px] text-ink-2">
        <button
          type="button"
          data-testid="map-bc-lib"
          aria-label={t('lib.worldMapBack')}
          className="transition-colors duration-150 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={onExitWorkbench}
        >
          {t('lib.title')}
        </button>
        <ChevronRight className="h-3.5 w-3.5 text-ink-3" aria-hidden="true" />
        <button
          type="button"
          data-testid="map-bc-world"
          className="transition-colors duration-150 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={onExitWorkbench}
        >
          {t('nav.lib.world')}
        </button>
        <ChevronRight className="h-3.5 w-3.5 text-ink-3" aria-hidden="true" />
        <button
          type="button"
          data-testid="map-bc-maplist"
          className={cn(
            'transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            activeMap ? 'hover:text-accent' : 'text-ink',
          )}
          onClick={onClearMap}
        >
          {t('lib.worldMap')}
        </button>
        {activeMap && (
          <>
            <ChevronRight className="h-3.5 w-3.5 text-ink-3" aria-hidden="true" />
            <span data-testid="map-bc-current" className="text-ink">
              🗺 {activeMap.name}
            </span>
          </>
        )}
        <span className="ml-auto text-[12px] text-ink-3">
          {pins.length}
          {t('lib.worldMapPins')}
        </span>
      </div>

      <div className="flex items-start gap-4">
        {/* 左栏：P1 分类 chips + 世界观树（library-list testid 契约不变） */}
        <aside className="w-[260px] shrink-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[12px] text-ink-2">{t('lib.worldCat.label')}</span>
            {worldCategories.map((cat) => (
              <button
                key={cat}
                type="button"
                data-testid={`world-cat-filter-${cat}`}
                aria-pressed={activeWorldCat === cat}
                className={cn(
                  'rounded-full border px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  activeWorldCat === cat
                    ? 'border-accent bg-accent/10 text-accent'
                    : 'border-line text-ink-2 hover:border-accent hover:text-accent',
                )}
                onClick={() => onWorldCatChange(activeWorldCat === cat ? null : cat)}
              >
                {cat}
              </button>
            ))}
            <button
              type="button"
              data-testid="world-copy-all"
              title={copyTargetOptions.length === 0 ? t('lib.copy.needTwo') : undefined}
              disabled={copyTargetOptions.length === 0}
              className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              onClick={onCopyAll}
            >
              <Copy className="h-3.5 w-3.5" aria-hidden="true" />
              {t('lib.copy.all')}
            </button>
          </div>
          <div
            data-testid="library-list"
            className="overflow-hidden rounded-lg border border-line bg-surface shadow-card"
          >
            {filteredWorldRoots.length === 0 ? (
              <div className="px-4 py-8 text-center text-[13px] text-ink-2">{t('common.empty')}</div>
            ) : (
              filteredWorldRoots.map((node) => (
                <WorkbenchNodeView
                  key={String(node.item.id)}
                  node={node}
                  depth={0}
                  collapsed={collapsedIds}
                  mapByLocation={mapByLocation}
                  pinCounts={pinCounts}
                  activeMapId={activeMapId}
                  onToggle={onToggle}
                  onEdit={onEdit}
                  onDelete={onDelete}
                  onCopy={onCopy}
                  onSelectMap={onSelectMap}
                />
              ))
            )}
          </div>
        </aside>

        {/* 右栏：画布 + pin 列表 / 未选地图空态 */}
        <div className="min-w-0 flex-1">
          {activeMap ? (
            <div className="space-y-3">
              <MapCanvas
                map={activeMap}
                pins={pins}
                onAddPin={openNewPin}
                onChangeBg={(bg) => void handleChangeBg(bg)}
                onAddShape={(type) => void handleAddShape(type)}
                onUpdateShapes={(shapes) => void handleUpdateShapes(shapes)}
              />
              {/* pin 列表：类型筛选 chips + 行（类型徽标/名称/关联名/编辑/删除） */}
              <div
                data-testid="map-pin-list"
                className="overflow-hidden rounded-lg border border-line bg-surface shadow-card"
              >
                <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-3 py-2">
                  {PIN_TYPES.map((pinType) => (
                    <button
                      key={pinType}
                      type="button"
                      data-testid={`map-pin-filter-${pinType}`}
                      aria-pressed={pinFilter === pinType}
                      className={cn(
                        'rounded-full border px-2.5 py-0.5 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                        pinFilter === pinType
                          ? 'border-accent bg-accent/10 text-accent'
                          : 'border-line text-ink-2 hover:border-accent hover:text-accent',
                      )}
                      onClick={() => setPinFilter(pinFilter === pinType ? null : pinType)}
                    >
                      {t(`lib.pinType.${pinType}`)}
                    </button>
                  ))}
                </div>
                {filteredPins.length === 0 ? (
                  <div className="px-4 py-6 text-center text-[13px] text-ink-2">
                    {t('lib.worldMapNoPins')}
                  </div>
                ) : (
                  <ul className="divide-y divide-line">
                    {filteredPins.map((pin) => {
                      const pinType = pin.type ?? 'location';
                      const name = linkedName(pin);
                      return (
                        <li
                          key={String(pin.id)}
                          className="group flex items-center gap-2 px-3 py-2 text-[13px] text-ink"
                        >
                          <span className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2">
                            {t(`lib.pinType.${pinType}`)}
                          </span>
                          <span className="min-w-0 flex-1 truncate">{pin.label}</span>
                          {name && <span className="shrink-0 text-[12px] text-ink-3">{name}</span>}
                          <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
                            <button
                              type="button"
                              data-testid={`map-pin-edit-${pin.id}`}
                              aria-label={`${t('lib.edit')} ${pin.label}`}
                              className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              onClick={() => openEditPin(pin)}
                            >
                              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                            </button>
                            <button
                              type="button"
                              data-testid={`map-pin-del-${pin.id}`}
                              aria-label={`${t('lib.delete')} ${pin.label}`}
                              className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              onClick={() => setPendingDeletePin(pin)}
                            >
                              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                            </button>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line bg-surface px-6 py-16 text-center">
              <p className="text-[13px] text-ink-2">{t('lib.worldMapSelectTip')}</p>
            </div>
          )}
        </div>
      </div>

      {/* PinDialog：画布点击新建 / 列表编辑（#195 遮罩不关闭） */}
      <PinDialog
        open={pinDialog.open}
        editing={pinDialog.editing}
        defaultX={pinDialog.defaultX}
        defaultY={pinDialog.defaultY}
        refOptions={refOptions}
        onSave={(input) => void handlePinSave(input)}
        onOpenChange={(open) => {
          if (!open) setPinDialog({ open: false, editing: null, defaultX: 0, defaultY: 0 });
        }}
      />

      {/* pin 删除二次确认（真删；确认后刷新列表 + ok toast） */}
      {pendingDeletePin && (
        <ConfirmDialog
          open
          title={t('lib.delete.title', { name: pendingDeletePin.label })}
          message={t('lib.delete.confirm')}
          confirmText={t('lib.delete.ok')}
          danger
          testidPrefix="map-pin-confirm"
          onConfirm={() => void handleDeletePin()}
          onOpenChange={(open) => {
            if (!open) setPendingDeletePin(null);
          }}
        />
      )}
    </div>
  );
}
