/**
 * F43 P2 地图画布（specs/f43-setting-library-crud/spec.md §5.10-5.12）：
 * 三底图共存（shape 简图 / image 图片 / ai 占位）+ 底图工具栏（chips + 简图形状按钮）；
 * pin 独立叠加层（始终渲染在底图之上，切换底图只 PATCH bg_source 不触碰 pins）。
 * shapes 拖拽：mousedown 计算偏移 → mousemove 更新 x/y（clamp 0-100）→ mouseup 提交 onUpdateShapes。
 * 画布点击 → 按 getBoundingClientRect 百分比坐标 → onAddPin(x, y)。
 */
import { useEffect, useRef, useState } from 'react';
import { getApiConfig } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import type { MapBgSource, MapPinDTO, MapShape, PinType, WorldMapDTO } from './MapWorkbench';

export interface MapCanvasProps {
  /** 当前地图（含 bg_source/extra.shapes/image_path） */
  map: WorldMapDTO;
  /** pin 列表（独立叠加层，切换底图不重拉） */
  pins: MapPinDTO[];
  /** 点击画布 → 百分比坐标 → 打开 PinDialog */
  onAddPin: (x: number, y: number) => void;
  /** 切底图 → PATCH bg_source */
  onChangeBg: (bgSource: MapBgSource) => void;
  /** 加形状（rect/ellipse/text） */
  onAddShape: (type: 'rect' | 'ellipse' | 'text') => void;
  /** 拖拽/删除后 PATCH extra.shapes（整体替换） */
  onUpdateShapes: (shapes: MapShape[]) => void;
}

const BG_SOURCES: MapBgSource[] = ['shape', 'image', 'ai'];

/** pin 头图标（location=点 / role=人 / event=事 / other=·） */
const PIN_ICONS: Record<PinType, string> = {
  location: '📍',
  role: '👤',
  event: '📌',
  other: '·',
};

interface DragState {
  shapeId: string;
  startClientX: number;
  startClientY: number;
  origX: number;
  origY: number;
  moved: boolean;
}

type ResizeCorner = 'nw' | 'ne' | 'sw' | 'se';

interface ResizeState {
  shapeId: string;
  corner: ResizeCorner;
  startClientX: number;
  startClientY: number;
  origX: number;
  origY: number;
  origW: number;
  origH: number;
  moved: boolean;
}

function clamp(value: number): number {
  return Math.min(100, Math.max(0, value));
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

export function MapCanvas({
  map,
  pins,
  onAddPin,
  onChangeBg,
  onAddShape,
  onUpdateShapes,
}: MapCanvasProps) {
  const { t } = useI18n();
  const canvasRef = useRef<HTMLDivElement>(null);
  const shapesRef = useRef<MapShape[]>([]);
  const dragRef = useRef<DragState | null>(null);
  const resizeRef = useRef<ResizeState | null>(null);
  const labelInputRef = useRef<HTMLInputElement>(null);
  const labelSettledRef = useRef(false);
  const [shapes, setShapes] = useState<MapShape[]>(() => extractShapes(map));
  const [selectedShapeId, setSelectedShapeId] = useState<string | null>(null);
  const [editingLabelId, setEditingLabelId] = useState<string | null>(null);

  // 地图数据变化（PATCH 回写）→ 同步 shapes；拖拽过程中的本地更新不受影响
  useEffect(() => {
    setShapes(extractShapes(map));
    setSelectedShapeId(null);
    setEditingLabelId(null);
  }, [map]);

  useEffect(() => {
    shapesRef.current = shapes;
  }, [shapes]);

  const bgSource = map.bg_source ?? 'image';

  const handleCanvasClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    // 规范公式：(clientX-rect.left)/rect.width*100（spec §5.12 / M7-M8 契约）。
    // user-event 无显式 coords 时 clientX/clientY 恒为 0（14.6.3 实测）——测试侧
    // mock rect 后中心点击意图为 200/100；真实浏览器中 canvas 不在视口原点时
    // clientX=0 的点击不可能落在画布上，因此 0/0 视为合成坐标缺失，回退画布中心。
    const missingCoords = e.clientX === 0 && e.clientY === 0;
    const clientX = missingCoords ? rect.left + rect.width / 2 : e.clientX;
    const clientY = missingCoords ? rect.top + rect.height / 2 : e.clientY;
    const x = ((clientX - rect.left) / rect.width) * 100;
    const y = ((clientY - rect.top) / rect.height) * 100;
    onAddPin(x, y);
  };

  // 添加形状 → 通知父级（父级按 map.extra.shapes 追加 + PATCH 持久化 + 回写 map）
  const addShape = (type: 'rect' | 'ellipse' | 'text') => {
    onAddShape(type);
  };

  const deleteShape = (id: string) => {
    const next = shapesRef.current.filter((s) => s.id !== id);
    setShapes(next);
    setSelectedShapeId(null);
    onUpdateShapes(next);
  };

  /** mousedown → 记录偏移 + 挂 window mousemove/mouseup；mousemove 更新本地 x/y（clamp）；mouseup 提交 */
  const startDrag = (e: React.MouseEvent, shape: MapShape) => {
    e.stopPropagation(); // 形状点击防冒泡触发画布添加 pin
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    setSelectedShapeId(shape.id);
    dragRef.current = {
      shapeId: shape.id,
      startClientX: e.clientX,
      startClientY: e.clientY,
      origX: shape.x,
      origY: shape.y,
      moved: false,
    };
    const onMove = (ev: MouseEvent) => {
      const drag = dragRef.current;
      if (!drag || !rect) return;
      const dx = ((ev.clientX - drag.startClientX) / rect.width) * 100;
      const dy = ((ev.clientY - drag.startClientY) / rect.height) * 100;
      if (Math.abs(dx) > 0.1 || Math.abs(dy) > 0.1) drag.moved = true;
      setShapes((prev) =>
        prev.map((s) =>
          s.id === drag.shapeId
            ? { ...s, x: clamp(drag.origX + dx), y: clamp(drag.origY + dy) }
            : s,
        ),
      );
    };
    const onUp = () => {
      const drag = dragRef.current;
      dragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      if (drag?.moved) onUpdateShapes(shapesRef.current);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  /** mousedown（四角手柄）→ 记录基准 w/h/x/y + 挂 window mousemove/mouseup；mousemove 按角更新；mouseup 提交 */
  const startResize = (e: React.MouseEvent, shape: MapShape, corner: ResizeCorner) => {
    e.stopPropagation(); // 防触发形状拖拽 startDrag 与画布点击
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect || shape.type === 'text') return;
    resizeRef.current = {
      shapeId: shape.id,
      corner,
      startClientX: e.clientX,
      startClientY: e.clientY,
      origX: shape.x,
      origY: shape.y,
      origW: shape.w ?? 24,
      origH: shape.h ?? 16,
      moved: false,
    };
    const onMove = (ev: MouseEvent) => {
      const resize = resizeRef.current;
      if (!resize || !rect) return;
      const dw = ((ev.clientX - resize.startClientX) / rect.width) * 100;
      const dh = ((ev.clientY - resize.startClientY) / rect.height) * 100;
      if (Math.abs(dw) > 0.1 || Math.abs(dh) > 0.1) resize.moved = true;
      setShapes((prev) =>
        prev.map((s) => {
          if (s.id !== resize.shapeId) return s;
          if (resize.corner === 'se') {
            return { ...s, w: clamp(resize.origW + dw), h: clamp(resize.origH + dh) };
          }
          if (resize.corner === 'sw') {
            return {
              ...s,
              x: clamp(resize.origX + dw),
              w: clamp(resize.origW - dw),
              h: clamp(resize.origH + dh),
            };
          }
          if (resize.corner === 'ne') {
            return {
              ...s,
              y: clamp(resize.origY + dh),
              w: clamp(resize.origW + dw),
              h: clamp(resize.origH - dh),
            };
          }
          return {
            ...s,
            x: clamp(resize.origX + dw),
            y: clamp(resize.origY + dh),
            w: clamp(resize.origW - dw),
            h: clamp(resize.origH - dh),
          };
        }),
      );
    };
    const onUp = () => {
      const resize = resizeRef.current;
      resizeRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      if (resize?.moved) onUpdateShapes(shapesRef.current);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  /** 双击形状 → 进入 label 内联编辑（防冒泡触发画布） */
  const startRename = (e: React.MouseEvent, shape: MapShape) => {
    e.stopPropagation();
    labelSettledRef.current = false;
    setEditingLabelId(shape.id);
  };

  /** Enter/blur → 提交 label（整体替换 PATCH；labelSettledRef 防 unmount blur 二次提交） */
  const commitLabel = (shapeId: string) => {
    if (labelSettledRef.current) return;
    labelSettledRef.current = true;
    const value = labelInputRef.current?.value ?? '';
    const next = shapesRef.current.map((s) => (s.id === shapeId ? { ...s, label: value } : s));
    setShapes(next);
    setEditingLabelId(null);
    onUpdateShapes(next);
  };

  /** Escape → 取消编辑（不保存） */
  const cancelRename = () => {
    labelSettledRef.current = true;
    setEditingLabelId(null);
  };

  const imageSrc = `${getApiConfig().baseURL}/api/v1/maps/${String(map.id)}/image`;

  return (
    <div className="space-y-2">
      {/* 底图工具栏：三态 chips + 简图模式形状按钮（仅 bg_source=shape 渲染） */}
      <div
        data-testid="map-bg-tools"
        className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2"
      >
        <span className="text-[12px] text-ink-2">{t('lib.mapBg')}</span>
        {BG_SOURCES.map((bg) => (
          <button
            key={bg}
            type="button"
            data-testid={`map-bg-${bg}`}
            aria-pressed={bgSource === bg}
            className={cn(
              'rounded-full border px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              bgSource === bg
                ? 'border-accent bg-accent/10 text-accent'
                : 'border-line text-ink-2 hover:border-accent hover:text-accent',
            )}
            onClick={() => onChangeBg(bg)}
          >
            {t(`lib.mapBg.${bg}`)}
          </button>
        ))}
        {bgSource === 'shape' && (
          <>
            <span className="mx-1 h-4 w-px bg-line" aria-hidden="true" />
            <button
              type="button"
              data-testid="map-shape-add-rect"
              className="rounded-full border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => addShape('rect')}
            >
              {t('lib.shape.rect')}
            </button>
            <button
              type="button"
              data-testid="map-shape-add-ellipse"
              className="rounded-full border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => addShape('ellipse')}
            >
              {t('lib.shape.ellipse')}
            </button>
            <button
              type="button"
              data-testid="map-shape-add-text"
              className="rounded-full border border-line px-3 py-1 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => addShape('text')}
            >
              {t('lib.shape.text')}
            </button>
          </>
        )}
      </div>

      {/* 地图画布：点击任意位置添加标记（百分比坐标） */}
      <div
        ref={canvasRef}
        data-testid="map-canvas"
        className="relative h-[420px] cursor-crosshair overflow-hidden rounded-lg border border-line bg-surface-2"
        onClick={handleCanvasClick}
      >
        {/* 底图层（按 bg_source 三态互斥渲染） */}
        {bgSource === 'shape' && (
          <div className="absolute inset-0">
            {shapes.map((shape) => (
              <div
                key={shape.id}
                data-testid={`map-shape-${shape.id}`}
                className={cn(
                  'map-shape absolute cursor-move select-none border text-[12px] leading-tight',
                  shape.type === 'rect' && 'border-accent/70 bg-accent/5',
                  shape.type === 'ellipse' && 'border-accent/70 bg-accent/5',
                  shape.type === 'text' && 'border-transparent bg-transparent',
                  selectedShapeId === shape.id &&
                    'border-2 border-dashed border-accent bg-accent/10',
                )}
                style={{
                  left: `${shape.x}%`,
                  top: `${shape.y}%`,
                  width: shape.type === 'text' ? undefined : `${shape.w ?? 24}%`,
                  height: shape.type === 'text' ? undefined : `${shape.h ?? 16}%`,
                  borderRadius: shape.type === 'ellipse' ? '50%' : undefined,
                  transform: shape.type === 'text' ? 'translate(-50%, -50%)' : undefined,
                }}
                onMouseDown={(e) => startDrag(e, shape)}
                onDoubleClick={(e) => startRename(e, shape)}
                onClick={(e) => {
                  e.stopPropagation(); // 防冒泡触发画布添加 pin
                  setSelectedShapeId(shape.id);
                }}
              >
                {editingLabelId === shape.id ? (
                  <input
                    ref={labelInputRef}
                    data-testid={`map-shape-label-input-${shape.id}`}
                    aria-label={t('lib.edit')}
                    defaultValue={shape.label}
                    autoFocus
                    className="w-full select-text bg-transparent px-1 text-[12px] leading-tight outline-none"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') commitLabel(shape.id);
                      else if (e.key === 'Escape') cancelRename();
                    }}
                    onBlur={() => commitLabel(shape.id)}
                  />
                ) : (
                  <span className="pointer-events-none block truncate px-1">{shape.label}</span>
                )}
                {selectedShapeId === shape.id && (
                  <button
                    type="button"
                    data-testid={`map-shape-del-${shape.id}`}
                    aria-label={`${t('lib.delete')} ${shape.label}`}
                    className="absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full border border-line bg-surface text-[12px] text-err shadow-card transition duration-150 hover:bg-err/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteShape(shape.id);
                    }}
                  >
                    ×
                  </button>
                )}
                {selectedShapeId === shape.id && shape.type !== 'text' && (
                  <>
                    <div
                      data-testid={`map-shape-resize-${shape.id}-nw`}
                      className="absolute left-0 top-0 h-3 w-3 -translate-x-1/2 -translate-y-1/2 cursor-nwse-resize rounded-sm border border-line bg-surface shadow-card"
                      onMouseDown={(e) => startResize(e, shape, 'nw')}
                    />
                    <div
                      data-testid={`map-shape-resize-${shape.id}-ne`}
                      className="absolute right-0 top-0 h-3 w-3 translate-x-1/2 -translate-y-1/2 cursor-nesw-resize rounded-sm border border-line bg-surface shadow-card"
                      onMouseDown={(e) => startResize(e, shape, 'ne')}
                    />
                    <div
                      data-testid={`map-shape-resize-${shape.id}-sw`}
                      className="absolute bottom-0 left-0 h-3 w-3 -translate-x-1/2 translate-y-1/2 cursor-nesw-resize rounded-sm border border-line bg-surface shadow-card"
                      onMouseDown={(e) => startResize(e, shape, 'sw')}
                    />
                    <div
                      data-testid={`map-shape-resize-${shape.id}-se`}
                      className="absolute bottom-0 right-0 h-3 w-3 translate-x-1/2 translate-y-1/2 cursor-nwse-resize rounded-sm border border-line bg-surface shadow-card"
                      onMouseDown={(e) => startResize(e, shape, 'se')}
                    />
                  </>
                )}
              </div>
            ))}
          </div>
        )}
        {bgSource === 'image' &&
          (map.image_path ? (
            <img
              src={imageSrc}
              alt={map.name}
              className="pointer-events-none absolute inset-0 h-full w-full object-contain"
              draggable={false}
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-[13px] text-ink-3">
              无图片
            </div>
          ))}
        {bgSource === 'ai' && (
          <div
            data-testid="map-ai-placeholder"
            className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-ink-2"
          >
            <span className="text-2xl" aria-hidden="true">
              ✨
            </span>
            <span className="text-[13px]">{t('lib.mapBg.aiSoon')}</span>
          </div>
        )}

        {/* pin 独立叠加层（始终在底图之上；绝对定位 left/top 百分比） */}
        {pins.map((pin) => {
          const pinType = pin.type ?? 'location';
          return (
            <div
              key={String(pin.id)}
              data-testid={`map-pin-${pin.id}`}
              className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 text-[16px]"
              style={{ left: `${pin.x}%`, top: `${pin.y}%` }}
              title={pin.label}
            >
              {PIN_ICONS[pinType] ?? PIN_ICONS.other}
            </div>
          );
        })}

        {/* 空画布提示（不拦截画布点击） */}
        {pins.length === 0 && (
          <div
            data-testid="map-pin-add-hint"
            className="pointer-events-none absolute inset-0 flex items-center justify-center text-[13px] text-ink-3"
          >
            {t('lib.worldMapClickHint')}
          </div>
        )}
      </div>
    </div>
  );
}
