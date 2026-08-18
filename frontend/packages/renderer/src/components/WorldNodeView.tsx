/* eslint-disable react-refresh/only-export-components -- buildWorldTree 与 WorldNodeView 同文件（#88 护栏机械搬移，建树工具函数与视图强耦合） */
/** 世界观树节点视图（F43 P1 §5.3；2026-08-19 自 pages/library.tsx 机械搬移——900 行护栏 #88） */
import { ChevronRight, Copy, Pencil, Trash2 } from 'lucide-react';
import type { LibraryItemDTO } from './LibraryCreateDialog';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';

export interface WorldTreeNode {
  item: LibraryItemDTO;
  children: WorldTreeNode[];
}

/** F43 P1（§5.3）：items → 树——顶层 = parent_id null/缺失；按序保序；孤儿降级顶层（E18） */
export function buildWorldTree(items: LibraryItemDTO[]): WorldTreeNode[] {
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

/** F43 P1（§5.3）：递归树节点视图——toggle 仅渲染在有子节点行；操作按钮随 D12 悬停显示 */
export function WorldNodeView({
  node,
  depth,
  collapsed,
  onToggle,
  onEdit,
  onDelete,
  onCopy,
}: {
  node: WorldTreeNode;
  depth: number;
  collapsed: Set<string | number>;
  onToggle: (id: string | number) => void;
  onEdit: (item: LibraryItemDTO) => void;
  onDelete: (item: LibraryItemDTO) => void;
  onCopy: (item: LibraryItemDTO) => void;
}) {
  const { t } = useI18n();
  const { item, children } = node;
  const hasChildren = children.length > 0;
  const isCollapsed = collapsed.has(item.id);
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
        <span className="min-w-0 flex-1 truncate">{item.name ?? ''}</span>
        {item.category ? (
          <span className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-ink-2">
            {item.category}
          </span>
        ) : null}
        {/* F43 P1：行内操作按钮（D12 悬停显示；P0 编辑/删除 testid 不变 + 复制 world-copy-<id>） */}
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
          <WorldNodeView
            key={String(child.item.id)}
            node={child}
            depth={depth + 1}
            collapsed={collapsed}
            onToggle={onToggle}
            onEdit={onEdit}
            onDelete={onDelete}
            onCopy={onCopy}
          />
        ))}
    </div>
  );
}
