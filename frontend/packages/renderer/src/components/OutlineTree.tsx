/**
 * F43 P3 大纲三级树（specs/f43-setting-library-crud/spec.md §5.14-5.15）：
 * 整体 → 卷 → 章 → 情节点（level/parent_id 前端建树；孤立章降级顶层；未知 level 按整体兜底）；
 * 三级展开收起（有子节点才渲染 toggle，叶子不渲染）；各层新增按钮（本批占位，创建入口后置）；
 * 章关联徽标（chapter_id 非空 → 📎 + 章节标题，title=lib.chapterRefTip；未关联 → 「关联章节」按钮，
 * 点击仅 toast lib.chapterLinkPick，不打开选择器 D9）；
 * 情节点首次展开按需拉取 GET /outlines/{id}/plot-points + 前端本地缓存（收起再展开不重拉）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, Pencil, Trash2 } from 'lucide-react';
import { apiFetch, errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import { useToastStore } from '../stores/toast';
import type { LibraryItemDTO } from './LibraryCreateDialog';

export type OutlineLevel = 'overall' | 'volume' | 'chapter';

const OUTLINE_LEVELS: readonly OutlineLevel[] = ['overall', 'volume', 'chapter'];

/** 大纲 DTO（spec §2.8：level/parent_id/chapter_id/point_count） */
export interface OutlineItemDTO extends LibraryItemDTO {
  level?: OutlineLevel | string;
  parent_id?: string | number | null;
  chapter_id?: string | number | null;
  point_count?: number;
}

/** 情节点 DTO（spec §2.8：GET /outlines/{id}/plot-points） */
export interface PlotPointDTO {
  id: string | number;
  name?: string;
  type?: string;
  description?: string;
  position?: number;
}

/** 前端建树节点（parent_id 树，孤儿降级顶层） */
interface OutlineTreeNode {
  item: OutlineItemDTO;
  children: OutlineTreeNode[];
}

export interface OutlineTreeProps {
  outlines: OutlineItemDTO[];
  /** chapter_id → 章节标题（GET /projects/{pid}/chapters 映射，library.tsx 装配） */
  chapterTitles: Record<string, string>;
  onEdit: (item: LibraryItemDTO) => void;
  onDelete: (item: LibraryItemDTO) => void;
  /** 各层新增按钮入口（本批占位：打开创建对话框；parent_id/情节点创建后置） */
  onAdd?: () => void;
}

/** level 归一化：缺失/非法 level 按 overall 兜底（兼容旧数据，顶层渲染） */
function normalizeLevel(level: unknown): OutlineLevel {
  return OUTLINE_LEVELS.includes(level as OutlineLevel) ? (level as OutlineLevel) : 'overall';
}

/** §5.14：items → 树——overall 顶层；volume 挂 overall；chapter 挂 volume；孤儿（parent 缺失）降级顶层 */
function buildOutlineTree(items: OutlineItemDTO[]): OutlineTreeNode[] {
  const nodes = new Map<string, OutlineTreeNode>();
  for (const item of items) {
    nodes.set(String(item.id), { item, children: [] });
  }
  const roots: OutlineTreeNode[] = [];
  for (const item of items) {
    const node = nodes.get(String(item.id));
    if (!node) continue;
    const parentId = item.parent_id;
    if (parentId !== null && parentId !== undefined && nodes.has(String(parentId))) {
      nodes.get(String(parentId))!.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

function OutlineNodeView({
  node,
  depth,
  collapsed,
  pointsByChapter,
  chapterTitles,
  onToggle,
  onEdit,
  onDelete,
  onAdd,
  onLinkChapter,
}: {
  node: OutlineTreeNode;
  depth: number;
  collapsed: Set<string | number>;
  pointsByChapter: Record<string, PlotPointDTO[]>;
  chapterTitles: Record<string, string>;
  onToggle: (id: string | number) => void;
  onEdit: (item: LibraryItemDTO) => void;
  onDelete: (item: LibraryItemDTO) => void;
  onAdd: () => void;
  onLinkChapter: () => void;
}) {
  const { t } = useI18n();
  const { item, children } = node;
  const level = normalizeLevel(item.level);
  const idStr = String(item.id);
  const isChapter = level === 'chapter';
  const points = isChapter ? (pointsByChapter[idStr] ?? []) : [];
  const hasChildren =
    children.length > 0 || (isChapter && ((item.point_count ?? 0) > 0 || points.length > 0));
  const isCollapsed = collapsed.has(item.id);
  const hasChapterRef = isChapter && item.chapter_id !== null && item.chapter_id !== undefined;
  const chapterTitle = hasChapterRef ? (chapterTitles[String(item.chapter_id)] ?? '') : '';
  return (
    <div data-testid={`outline-${level}-${item.id}`} className="tree-node">
      <div
        className="tree-row group flex items-center gap-2 px-3 py-2 text-[13px] text-ink transition-colors duration-150 hover:bg-surface-2/60"
        style={{ paddingLeft: depth * 18 + 12 }}
      >
        {hasChildren ? (
          <button
            type="button"
            data-testid={`outline-toggle-${item.id}`}
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
        <span className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2">
          {t(`lib.level.${level}`)}
        </span>
        <span className="min-w-0 flex-1 truncate">{item.name ?? ''}</span>
        {isChapter &&
          (hasChapterRef ? (
            <span
              data-testid={`outline-chapter-ref-${item.id}`}
              title={t('lib.chapterRefTip')}
              className="inline-flex shrink-0 items-center gap-1 rounded-full border border-line bg-surface-3/60 px-2 py-0.5 text-[11px] text-ink-2"
            >
              <span aria-hidden="true">📎</span>
              {chapterTitle}
            </span>
          ) : (
            <button
              type="button"
              data-testid={`outline-chapter-link-${item.id}`}
              className="inline-flex shrink-0 items-center rounded-md border border-dashed border-accent/50 px-2 py-0.5 text-[11px] text-accent transition duration-150 hover:bg-accent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={onLinkChapter}
            >
              {t('lib.chapterLink')}
            </button>
          ))}
        {level === 'overall' && (
          <button
            type="button"
            data-testid={`outline-add-volume-${item.id}`}
            aria-label={`${t('lib.addVolume')} ${item.name ?? ''}`}
            className="shrink-0 rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={onAdd}
          >
            {t('lib.addVolume')}
          </button>
        )}
        {level === 'volume' && (
          <button
            type="button"
            data-testid={`outline-add-chapter-${item.id}`}
            aria-label={`${t('lib.addChapter')} ${item.name ?? ''}`}
            className="shrink-0 rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={onAdd}
          >
            {t('lib.addChapter')}
          </button>
        )}
        {isChapter && (
          <button
            type="button"
            data-testid={`outline-add-point-${item.id}`}
            aria-label={`${t('lib.addPoint')} ${item.name ?? ''}`}
            className="shrink-0 rounded-md border border-line px-2 py-0.5 text-[11px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={onAdd}
          >
            {t('lib.addPoint')}
          </button>
        )}
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
        </div>
      </div>
      {!isCollapsed &&
        children.map((child) => (
          <OutlineNodeView
            key={String(child.item.id)}
            node={child}
            depth={depth + 1}
            collapsed={collapsed}
            pointsByChapter={pointsByChapter}
            chapterTitles={chapterTitles}
            onToggle={onToggle}
            onEdit={onEdit}
            onDelete={onDelete}
            onAdd={onAdd}
            onLinkChapter={onLinkChapter}
          />
        ))}
      {isChapter && !isCollapsed && (
        <div style={{ paddingLeft: (depth + 1) * 18 + 12 }} className="py-1 pr-3">
          {points.length > 0 ? (
            <div className="space-y-1">
              {points.map((pt) => (
                <div
                  key={String(pt.id)}
                  data-testid={`outline-point-${pt.id}`}
                  className="group flex items-center gap-2 rounded-md bg-surface-2/50 px-2.5 py-1.5 text-[12px] text-ink"
                >
                  <span className="min-w-0 flex-1 truncate">{pt.name ?? ''}</span>
                  {pt.type ? (
                    <span className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[10px] text-ink-2">
                      {pt.type}
                    </span>
                  ) : null}
                  <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
                    <button
                      type="button"
                      data-testid={`outline-point-edit-${pt.id}`}
                      aria-label={`${t('lib.edit')} ${pt.name ?? ''}`}
                      className="rounded p-1 text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <Pencil className="h-3 w-3" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      data-testid={`outline-point-del-${pt.id}`}
                      aria-label={`${t('lib.delete')} ${pt.name ?? ''}`}
                      className="rounded p-1 text-ink-3 transition duration-150 hover:bg-surface-3 hover:text-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <Trash2 className="h-3 w-3" aria-hidden="true" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-md px-2.5 py-1.5 text-[12px] text-ink-3">{t('lib.empty.points')}</div>
          )}
        </div>
      )}
    </div>
  );
}

export function OutlineTree({ outlines, chapterTitles, onEdit, onDelete, onAdd }: OutlineTreeProps) {
  const { t } = useI18n();
  const roots = useMemo(() => buildOutlineTree(outlines), [outlines]);
  const [collapsed, setCollapsed] = useState<Set<string | number>>(new Set());
  const [pointsByChapter, setPointsByChapter] = useState<Record<string, PlotPointDTO[]>>({});
  const fetchedRef = useRef<Set<string>>(new Set());

  const fetchPlotPoints = useCallback(async (chapterId: string | number) => {
    const key = String(chapterId);
    if (fetchedRef.current.has(key)) return;
    fetchedRef.current.add(key);
    try {
      const data = await apiFetch<{ items?: PlotPointDTO[] }>(`/api/v1/outlines/${key}/plot-points`);
      setPointsByChapter((prev) => ({ ...prev, [key]: data.items ?? [] }));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
      setPointsByChapter((prev) => ({ ...prev, [key]: [] }));
    }
  }, []);

  // 情节点按需拉取：默认全展开 → 挂载即拉；收起再展开不重拉（本地缓存，O8 契约）
  useEffect(() => {
    const visit = (nodes: OutlineTreeNode[]) => {
      for (const node of nodes) {
        const level = normalizeLevel(node.item.level);
        const id = node.item.id;
        if (level === 'chapter' && (node.item.point_count ?? 0) > 0 && !collapsed.has(id)) {
          void fetchPlotPoints(id);
        }
        if (!collapsed.has(id)) visit(node.children);
      }
    };
    visit(roots);
  }, [roots, collapsed, fetchPlotPoints]);

  const toggleCollapsed = (id: string | number) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleLinkChapter = () => {
    useToastStore.getState().pushToast('warn', t('lib.chapterLinkPick'));
  };

  const handleAdd = () => onAdd?.();

  return (
    <div
      data-testid="library-list"
      className="overflow-hidden rounded-lg border border-line bg-surface shadow-card"
    >
      <div data-testid="outline-tree" className="divide-y divide-line">
        {roots.length === 0 ? (
          <div className="px-4 py-8 text-center text-[13px] text-ink-2">{t('common.empty')}</div>
        ) : (
          roots.map((node) => (
            <OutlineNodeView
              key={String(node.item.id)}
              node={node}
              depth={0}
              collapsed={collapsed}
              pointsByChapter={pointsByChapter}
              chapterTitles={chapterTitles}
              onToggle={toggleCollapsed}
              onEdit={onEdit}
              onDelete={onDelete}
              onAdd={handleAdd}
              onLinkChapter={handleLinkChapter}
            />
          ))
        )}
      </div>
    </div>
  );
}
