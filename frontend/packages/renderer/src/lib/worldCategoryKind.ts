/**
 * #1334 ①C：世界观分类 kind 判据（单一真相源）——地图树（#721）与列表页主树（#1334 ①C）共用。
 *
 * 判据（spec specs/f10-world-settings/spec.md §16.4 / §16.8）：
 * - abstract 分类的条目「不进树」；仅当该分类被选中筛选时可见（由列表页数据源自行保留）
 * - 「空/未注册分类按 geo 处理」：category="" / null / undefined → 进树；有值但未命中分类表 → 进树
 * - 分类表缺省（undefined）→ 无 kind 约束，全量进树
 *
 * 禁止在此文件之外另立第二套 kind 判定（列表页树与地图树必须同源复用）。
 */

/** 分类名 → kind 映射；categories 缺省时返回空表；同名后者覆盖前者（与既有 Map#set 循环一致）。 */
export function buildKindByCategory(
  categories: readonly { name: string; kind?: 'geo' | 'abstract' }[] | undefined,
): Map<string, 'geo' | 'abstract' | undefined> {
  const kindByCategory = new Map<string, 'geo' | 'abstract' | undefined>();
  for (const c of categories ?? []) {
    kindByCategory.set(c.name, c.kind);
  }
  return kindByCategory;
}

/** 条目分类是否进树：abstract 分类 → false；空/未注册分类按 geo 处理 → true。 */
export function isWorldItemVisibleInTree(
  category: string | null | undefined,
  kindByCategory: ReadonlyMap<string, 'geo' | 'abstract' | undefined>,
): boolean {
  const key = category ?? '';
  if (key === '') return true;
  return kindByCategory.get(key) !== 'abstract';
}
