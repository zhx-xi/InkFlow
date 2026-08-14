/**
 * #368 v1.3 子图节点视图（2026-08-15，从 MapWorkbench.tsx 拆分——组件超 900 行护栏）。
 * 图挂图层级：递归渲染孙图，深度不限；🗺 徽标点击选中地图，行内按钮创建孙图。
 */
import { MapPlus } from 'lucide-react';
import { cn } from '../lib/cn';
import { useI18n } from '../i18n/useI18n';
import type { WorldMapDTO } from './MapWorkbench';
/** #368 v1.3：子图轻量行（图挂图层级）——复用 tree-row 样式 + 🗺 徽标 + 可点击选中 + 行内创建子图；递归渲染孙图 */
export function MapChildNodeView({
  map,
  depth,
  childrenByParent,
  pinCounts,
  activeMapId,
  onSelectMap,
  onCreateChild,
}: {
  map: WorldMapDTO;
  depth: number;
  collapsed?: Set<string | number>; // 入参保留（与 WorkbenchNodeView 递归契约一致；子图行简化不做折叠）
  childrenByParent: Map<string, WorldMapDTO[]>;
  pinCounts: Record<string, number>;
  activeMapId: string | null;
  onSelectMap: (mapId: string) => void;
  onCreateChild: (map: WorldMapDTO) => void;
}) {
  const { t } = useI18n();
  const isActive = activeMapId !== null && String(map.id) === String(activeMapId);
  const childMaps = childrenByParent.get(String(map.id)) ?? [];
  return (
    <div className="tree-node">
      <div
        data-testid={`map-child-row-${map.id}`}
        className="tree-row group flex items-center gap-2 px-3 py-2 text-[13px] text-ink transition-colors duration-150 hover:bg-surface-2/60"
        style={{ paddingLeft: depth * 18 + 12 }}
      >
        {/* 展开箭头占位（子图行简化：不做折叠，始终展开递归渲染） */}
        <span className="h-5 w-5 shrink-0" aria-hidden="true" />
        <button
          type="button"
          data-testid={`world-map-badge-${map.id}`}
          aria-label={`${t('lib.worldMap')} ${map.name}`}
          title={map.name}
          className={cn(
            'flex shrink-0 items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[11px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            isActive
              ? 'border-accent bg-accent/10 text-accent'
              : 'border-line text-ink-2 hover:border-accent hover:text-accent',
          )}
          onClick={() => onSelectMap(String(map.id))}
        >
          <span aria-hidden="true">🗺</span>
          <span>{pinCounts[String(map.id)] ?? 0}</span>
        </button>
        <button
          type="button"
          data-testid={`map-child-name-${map.id}`}
          title={map.name}
          className="min-w-0 flex-1 truncate text-left text-ink transition-colors duration-150 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={() => onSelectMap(String(map.id))}
        >
          {map.name}
        </button>
        {/* 行内「创建子图」按钮：传父图 id（parent_map_id） */}
        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
          <button
            type="button"
            data-testid={`map-create-child-${map.id}`}
            aria-label={`${t('lib.map.createChild')} ${map.name}`}
            title={t('lib.map.createChild')}
            className="rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => onCreateChild(map)}
          >
            <MapPlus className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>
      {childMaps.map((child) => (
        <MapChildNodeView
          key={String(child.id)}
          map={child}
          depth={depth + 1}
          childrenByParent={childrenByParent}
          pinCounts={pinCounts}
          activeMapId={activeMapId}
          onSelectMap={onSelectMap}
          onCreateChild={onCreateChild}
        />
      ))}
    </div>
  );
}
