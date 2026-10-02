/**
 * #1334 ①C：世界观分类 kind 判据（单一真相源）——列表页树与地图树（#721）同源复用。
 *
 * 判据（spec specs/f10-world-settings/spec.md §16.4 / §16.8）：
 * - abstract 分类的条目**不进树**（列表页 WorldNodeView 主树 / 地图树 MapDirectoryTree）
 * - `category=""`（未分类）→ 按 geo 处理 ⇒ 进树
 * - `category` 有值但分类未注册（未命中分类表）→ 按 geo 处理 ⇒ 进树
 * - 分类表缺省（undefined / 空）→ 无 kind 约束，全量进树
 */
import { describe, expect, it } from 'vitest';
import { buildKindByCategory, isWorldItemVisibleInTree } from './worldCategoryKind';
import type { WorldCategoryEntity } from '../hooks/useWorldCategories';

const cats: WorldCategoryEntity[] = [
  { id: 'g1', name: '地理', kind: 'geo', count: 0 },
  { id: 'a1', name: '势力', kind: 'abstract', count: 0 },
];

describe('#1334 世界观分类 kind 判据（与 #721 同一口径）', () => {
  const kindByCategory = buildKindByCategory(cats);

  it('abstract 分类的条目不进树', () => {
    expect(isWorldItemVisibleInTree('势力', kindByCategory)).toBe(false);
  });

  it('geo 分类的条目进树', () => {
    expect(isWorldItemVisibleInTree('地理', kindByCategory)).toBe(true);
  });

  it('反例守护：未分类（category="" / null / undefined）按 geo 处理 → 进树', () => {
    expect(isWorldItemVisibleInTree('', kindByCategory)).toBe(true);
    expect(isWorldItemVisibleInTree(null, kindByCategory)).toBe(true);
    expect(isWorldItemVisibleInTree(undefined, kindByCategory)).toBe(true);
  });

  it('反例守护：分类未注册（分类表未命中）按 geo 处理 → 进树', () => {
    expect(isWorldItemVisibleInTree('文化', kindByCategory)).toBe(true);
    expect(isWorldItemVisibleInTree('地图', kindByCategory)).toBe(true);
  });

  it('分类表缺省（undefined / 空表）→ 全量进树（#721「缺省 = 全量进树」口径）', () => {
    expect(isWorldItemVisibleInTree('势力', buildKindByCategory(undefined))).toBe(true);
    expect(isWorldItemVisibleInTree('势力', buildKindByCategory([]))).toBe(true);
  });

  it('同名词后者覆盖前者的确定性：同名分类只保留最后一个 kind（分类表唯一性由上游保证）', () => {
    const dup = buildKindByCategory([
      { name: '秘境', kind: 'abstract' },
      { name: '秘境', kind: 'geo' },
    ]);
    expect(dup.get('秘境')).toBe('geo');
    expect(isWorldItemVisibleInTree('秘境', dup)).toBe(true);
  });
});
