/**
 * F43 P2 地图工作台（specs/f43-setting-library-gui/spec.md §5.8-5.12）：
 * 世界观 tab 工作台态——四级面包屑回跳（设定库/世界观/地图视图/{地图名}）+
 * 左侧世界观树（P1 树渲染复用：parent_id 建树 + 分类 chips + 复制/编辑/删除；
 * 地图节点渲染 🗺 world-map-badge-<节点id> + pin 数徽标）+ 右侧画布/pin 列表。
 * pins 增删改（POST/PATCH/DELETE）、底图切换（PATCH bg_source）、shapes 持久化
 * （PATCH extra.shapes）均在组件内完成（消费方契约 library-p2.test.tsx 覆盖）。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, MapPlus, Pencil, Trash2 } from 'lucide-react';
import { ApiError, apiFetch, errorMessage } from '../api/client';
import { cn } from '../lib/cn';
import { useI18n } from '../i18n/useI18n';
import type { WorldCategoryEntity } from '../hooks/useWorldCategories';
import { useToastStore } from '../stores/toast';
import { ConfirmDialog } from './ConfirmDialog';
import type { LibraryItemDTO } from './LibraryCreateDialog';
import { MapCanvas } from './MapCanvas';
import { MapCreateDialog } from './MapCreateDialog';
import { MapDirectoryTree } from './MapDirectoryTree';
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
  parent_map_id?: string | number | null; // #368 v1.3：图挂父图；null/undefined=根图
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
  /** #761：创建图后回传父级（localMaps 是 props 拷贝，必须反向同步） */
  onMapsChanged?: (maps: WorldMapDTO[]) => void;
  /** 当前选中地图 id */
  activeMapId: string | null;
  onSelectMap: (mapId: string) => void;
  /** 面包屑层级 1/2 回跳（退出工作台） */
  onExitWorkbench: () => void;
  /** 面包屑层级 3 回跳（清空选中地图） */
  onClearMap: () => void;
  // ── P1 树交互（library.tsx 既有状态/回调复用）──
  worldCategories: string[];
  /** #721：世界观分类实体（kind 分流——转发给 MapDirectoryTree 过滤 abstract 条目） */
  worldCatEntities?: WorldCategoryEntity[];
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

const PIN_TYPES: PinType[] = ['location', 'role', 'event', 'other'];

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

/** #346 创建地图轻量对话框（MapCreateDialog.tsx，2026-08-14 拆分） */

export function MapWorkbench({
  projectId,
  worldItems,
  maps,
  onMapsChanged,
  activeMapId,
  onSelectMap,
  onExitWorkbench,
  onClearMap,
  worldCatEntities,
  collapsedIds,
  onToggle,
  onEdit,
  onDelete,
  onCopy,
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
  // #979：当前选中 pin id（画布 pin / 列表行互斥高亮，切换地图时重置）
  const [selectedPinId, setSelectedPinId] = useState<string | null>(null);
  const [createDialog, setCreateDialog] = useState<{
    open: boolean;
    rootLocationId: string | number | null;
    parentMapId: string | number | null; // #368 v1.3：创建子图传父图 id（parent_map_id）
  }>({ open: false, rootLocationId: null, parentMapId: null });
  // #378：重命名目标（非空 → MapCreateDialog editing 模式）与删除确认目标
  const [renameTarget, setRenameTarget] = useState<WorldMapDTO | null>(null);
  const [pendingDeleteMap, setPendingDeleteMap] = useState<WorldMapDTO | null>(null);
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
      setSelectedPinId(null);
      return;
    }
    setSelectedPinId(null); // #979：切换地图时重置 pin 选中态
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

  // #979：选中 pin 行滚动定位（测试环境已桩 no-op；实现从简）
  useEffect(() => {
    if (!selectedPinId) return;
    const rowEl = document.querySelector(`[data-testid="map-pin-row-${selectedPinId}"]`);
    rowEl?.scrollIntoView({ block: 'nearest' });
  }, [selectedPinId]);

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
      setLocalMaps((prev) => {
        const next = prev.map((m) =>
          String(m.id) === String(activeMap.id)
            ? updated
              ? { ...m, ...updated }
              : { ...m, bg_source: bgSource }
            : m,
        );
        onMapsChanged?.(next);
        return next;
      });
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  /** #346/#368 创建地图：multipart FormData（bg_source 固定 shape；子图携带 parent_map_id，根图可挂条目） */
  const handleCreateMap = async (name: string) => {
    try {
      // #761：本地已知同名图 → 直接 err toast，不再发 POST（避免后端「已存在」误报）
      if (localMaps.some((m) => m.name === name)) {
        useToastStore.getState().pushToast('err', t('toast.saveFailed'));
        return;
      }
      const fd = new FormData();
      fd.append('name', name);
      fd.append('bg_source', 'shape');
      // #368 v1.3：创建子图传父图 id（parent_map_id），而非条目 id
      if (createDialog.parentMapId != null) {
        fd.append('parent_map_id', String(createDialog.parentMapId));
      }
      // 创建根图挂条目场景（root_location_id 保留）
      if (createDialog.rootLocationId != null) {
        fd.append('root_location_id', String(createDialog.rootLocationId));
      }
      const created = await apiFetch<WorldMapDTO | { items?: WorldMapDTO[] }>(
        `/api/v1/projects/${projectId}/maps`,
        { method: 'POST', body: fd },
      );
      // 返回完整地图 → 追加本地列表；否则（列表形状响应）回退重拉
      if (created && typeof created === 'object' && 'id' in created) {
        setLocalMaps((prev) => {
          const next = [...prev, created];
          onMapsChanged?.(next);
          return next;
        });
        // #377：创建成功后自动选中新图（右侧渲染画布 + 树高亮）
        onSelectMap(String(created.id));
      } else {
        const data = await apiFetch<{ items?: WorldMapDTO[] }>(
          `/api/v1/projects/${projectId}/maps`,
        );
        setLocalMaps(data.items ?? []);
      }
      setCreateDialog({ open: false, rootLocationId: null, parentMapId: null });
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  /** #721：创建子图入口——真实地图节点直接以其为父；世界观条目未挂图时先物化根图再建子图 */
  const handleCreateChild = async (target: WorldMapDTO | LibraryItemDTO) => {
    // WorldMapDTO 必有 bg_source，LibraryItemDTO 无 → in 收窄两条路径
    if ('bg_source' in target) {
      setCreateDialog({ open: true, rootLocationId: null, parentMapId: target.id });
      return;
    }
    // 世界观条目：已挂图 → 以挂载图为父（与既有行为一致）
    const linkedMap =
      localMaps.find(
        (m) =>
          m.root_location_id !== null &&
          m.root_location_id !== undefined &&
          String(m.root_location_id) === String(target.id),
      ) ?? null;
    if (linkedMap) {
      setCreateDialog({ open: true, rootLocationId: null, parentMapId: linkedMap.id });
      return;
    }
    // 未挂图 → 先物化该世界的根图（name=条目名 / bg_source=shape / root_location_id=条目 id，无 parent_map_id）
    try {
      const fd = new FormData();
      fd.append('name', target.name ?? '');
      fd.append('bg_source', 'shape');
      fd.append('root_location_id', String(target.id));
      const created = await apiFetch<WorldMapDTO | { items?: WorldMapDTO[] }>(
        `/api/v1/projects/${projectId}/maps`,
        { method: 'POST', body: fd },
      );
      if (created && typeof created === 'object' && 'id' in created) {
        setLocalMaps((prev) => {
          const next = [...prev, created];
          onMapsChanged?.(next);
          return next;
        });
        setCreateDialog({ open: true, rootLocationId: null, parentMapId: created.id });
        return;
      }
      // 列表形状响应 → 回退重拉并按 root_location_id 找回物化图
      const data = await apiFetch<{ items?: WorldMapDTO[] }>(`/api/v1/projects/${projectId}/maps`);
      const items = data.items ?? [];
      setLocalMaps(items);
      const materialized = items.find(
        (m) =>
          m.root_location_id !== null &&
          m.root_location_id !== undefined &&
          String(m.root_location_id) === String(target.id),
      );
      if (materialized) {
        setCreateDialog({ open: true, rootLocationId: null, parentMapId: materialized.id });
      }
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  /** #378 拖拽改挂：PATCH parent_map_id（目标 id 或 null=变根图）→ 回写本地列表 + ok toast */
  const handleReparent = async (mapId: string, parentMapId: string | null) => {
    try {
      const updated = await apiFetch<WorldMapDTO | undefined>(`/api/v1/maps/${mapId}`, {
        method: 'PATCH',
        body: { parent_map_id: parentMapId },
      });
      setLocalMaps((prev) => {
        const next = prev.map((m) =>
          String(m.id) === String(mapId)
            ? updated
              ? { ...m, ...updated }
              : { ...m, parent_map_id: parentMapId }
            : m,
        );
        onMapsChanged?.(next);
        return next;
      });
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  /** #378 循环拖拽被拒：err toast（组件内已拦截，不发 PATCH） */
  const handleCycleReject = () => {
    useToastStore.getState().pushToast('err', t('lib.map.cycleReject'));
  };

  /** #378 重命名地图：PATCH body {name} → 回写本地列表 + 关闭对话框 + ok toast */
  const handleRenameMap = async (map: WorldMapDTO, name: string) => {
    try {
      const updated = await apiFetch<WorldMapDTO | undefined>(`/api/v1/maps/${map.id}`, {
        method: 'PATCH',
        body: { name },
      });
      setLocalMaps((prev) => {
        const next = prev.map((m) =>
          String(m.id) === String(map.id) ? (updated ? { ...m, ...updated } : { ...m, name }) : m,
        );
        onMapsChanged?.(next);
        return next;
      });
      setRenameTarget(null);
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  /** #378 删除地图：ConfirmDialog 确认 → DELETE /maps/{id} → 过滤本地列表；422（有子图）→ 提示 */
  const handleDeleteMap = async () => {
    if (!pendingDeleteMap) return;
    const target = pendingDeleteMap;
    try {
      await apiFetch(`/api/v1/maps/${target.id}`, { method: 'DELETE' });
      setLocalMaps((prev) => {
        const next = prev.filter((m) => String(m.id) !== String(target.id));
        onMapsChanged?.(next);
        return next;
      });
      setPendingDeleteMap(null);
      if (activeMapId !== null && String(activeMapId) === String(target.id)) {
        onClearMap();
      }
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      setPendingDeleteMap(null);
      if (err instanceof ApiError && err.status === 422) {
        useToastStore.getState().pushToast('err', t('lib.map.deleteHasChildren'));
      } else {
        useToastStore.getState().pushToast('err', errorMessage(err));
      }
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
      setLocalMaps((prev) => {
        const next = prev.map((m) => {
          if (String(m.id) !== String(activeMap.id)) return m;
          if (updated) return { ...m, ...updated };
          return { ...m, extra: { ...(m.extra ?? {}), shapes } };
        });
        onMapsChanged?.(next);
        return next;
      });
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
        <span className="ml-auto flex items-center gap-2">
          {/* #346：创建根图（无父地点）——面包屑右缘 */}
          <button
            type="button"
            data-testid="map-create-root"
            title={t('lib.map.createRoot')}
            className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => setCreateDialog({ open: true, rootLocationId: null, parentMapId: null })}
          >
            <MapPlus className="h-3.5 w-3.5" aria-hidden="true" />
            {t('lib.map.createRoot')}
          </button>
          <span className="text-[12px] text-ink-3">
            {pins.length}
            {t('lib.worldMapPins')}
          </span>
        </span>
      </div>

      <div className="flex items-start gap-4">
        {/* 左栏：#378 地图目录树（library-list testid 保留，供 P2 既有契约等待） */}
        <aside className="w-[260px] shrink-0 space-y-3">
          <div
            data-testid="library-list"
            className="overflow-hidden rounded-lg border border-line bg-surface shadow-card"
          >
            <MapDirectoryTree
              maps={localMaps}
              activeMapId={activeMapId}
              onSelectMap={onSelectMap}
              onCreateChild={(target) => void handleCreateChild(target)}
              onDeleteMap={(map) => setPendingDeleteMap(map)}
              onRenameMap={(map) => setRenameTarget(map)}
              onReparent={(mapId, parentMapId) => void handleReparent(mapId, parentMapId)}
              onCycleReject={handleCycleReject}
              worldItems={worldItems}
              worldCategories={worldCatEntities}
              collapsedIds={collapsedIds}
              onToggle={onToggle}
              onEdit={onEdit}
              onDelete={onDelete}
              onCopy={onCopy}
              pinCounts={pinCounts}
            />
          </div>
        </aside>

        {/* 右栏：画布 + pin 列表 / 未选地图空态 */}
        <div className="min-w-0 flex-1 overflow-x-auto">
          {activeMap ? (
            <div className="space-y-3">
              <MapCanvas
                map={activeMap}
                pins={pins}
                selectedPinId={selectedPinId}
                onSelectPin={(pin) => setSelectedPinId(String(pin.id))}
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
                          data-testid={`map-pin-row-${pin.id}`}
                          data-selected={selectedPinId === String(pin.id) ? 'true' : undefined}
                          className="group flex items-center gap-2 px-3 py-2 text-[13px] text-ink"
                          onClick={() => setSelectedPinId(String(pin.id))}
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
                              onClick={(e) => {
                                e.stopPropagation(); // #979：行内编辑防冒泡覆盖选中态
                                openEditPin(pin);
                              }}
                            >
                              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                            </button>
                            <button
                              type="button"
                              data-testid={`map-pin-del-${pin.id}`}
                              aria-label={`${t('lib.delete')} ${pin.label}`}
                              className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              onClick={(e) => {
                                e.stopPropagation(); // #979：行内删除防冒泡覆盖选中态
                                setPendingDeletePin(pin);
                              }}
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

      {/* #346/#368 创建地图对话框（根图 parentMapId=null / 子图预填父图 id）；#378 重命名模式（editing=renameTarget） */}
      <MapCreateDialog
        open={createDialog.open || renameTarget !== null}
        editing={renameTarget}
        onSave={(name) => {
          if (renameTarget !== null) {
            void handleRenameMap(renameTarget, name);
          } else {
            void handleCreateMap(name);
          }
        }}
        onOpenChange={(open) => {
          if (!open) {
            setCreateDialog({ open: false, rootLocationId: null, parentMapId: null });
            setRenameTarget(null);
          }
        }}
      />

      {/* #378 删除地图二次确认（真删；422 有子图 → err toast 提示） */}
      {pendingDeleteMap && (
        <ConfirmDialog
          open
          title={t('lib.delete.title', { name: pendingDeleteMap.name })}
          message={t('lib.delete.confirm')}
          confirmText={t('lib.delete.ok')}
          danger
          testidPrefix="map-delete-confirm"
          onConfirm={() => void handleDeleteMap()}
          onOpenChange={(open) => {
            if (!open) setPendingDeleteMap(null);
          }}
        />
      )}

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
