/** #1002：大纲树建树模型（从 OutlineTree.tsx 拆出以守 900 行护栏）。
 *  建树 = parent_id 挂树（整体→卷→章；孤儿降级顶层），挂树后逐层兄弟排序：
 *  sort_order asc（缺省 0）→ created_at 倒序（新在前，保 AI 插树顶）→ id 升序；
 *  sortDesc=true 整体镜像（主键与 tie 全镜像，specs/f19-gui/outline.md §2）。 */
import type { OutlineItemDTO } from './OutlineTree';

/** 前端建树节点（parent_id 树，孤儿降级顶层） */
export interface OutlineTreeNode {
  item: OutlineItemDTO;
  children: OutlineTreeNode[];
}

/** #1002：兄弟比较——sort_order asc（缺省 0）→ created_at 倒序（新在前）→ id 字符串升序 */
function compareOutlineSiblings(a: OutlineItemDTO, b: OutlineItemDTO): number {
  const byOrder = (a.sort_order ?? 0) - (b.sort_order ?? 0);
  if (byOrder !== 0) return byOrder;
  const byCreated = (b.created_at ?? '').localeCompare(a.created_at ?? '');
  if (byCreated !== 0) return byCreated;
  return String(a.id) < String(b.id) ? -1 : String(a.id) > String(b.id) ? 1 : 0;
}

/** §5.14：items → 树——overall 顶层；volume 挂 overall；chapter 挂 volume；孤儿（parent 缺失）降级顶层。
 *  #1002：先挂树后逐层兄弟排序（sortDesc=true 整体镜像，主键与 tie 全镜像） */
export function buildOutlineTree(items: OutlineItemDTO[], sortDesc = false): OutlineTreeNode[] {
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
  const sortNodes = (list: OutlineTreeNode[]) =>
    [...list].sort((x, y) => {
      const cmp = compareOutlineSiblings(x.item, y.item);
      return sortDesc ? -cmp : cmp;
    });
  const resort = (list: OutlineTreeNode[]) => {
    for (const node of list) {
      node.children = resort(sortNodes(node.children));
    }
    return list;
  };
  return resort(sortNodes(roots));
}
