/**
 * #741 世界观地图树三缺陷 — 缺陷③（组件级）：分类标签在名字右侧不盖名。
 *
 * 事实：MapDirectoryTree.tsx 的 WorldNodeRow 中，名字 span 是 `min-w-0 flex-1 whitespace-nowrap`（L381-383），
 * 分类徽标 span 在其后（L384-388，`shrink-0 rounded-full ...`）——flex 行内名字 span 无 overflow-hidden/truncate，
 * 长名字（whitespace-nowrap 不换行）会溢出到徽标下方（「标签盖名字」）。
 * WorldNodeView.tsx（页面树）名字在 flex-col div（L95），分类徽标在其后（L106-110）。
 *
 * RED 契约（当前 FAIL）：WorldNodeRow 名字 span 必须位于分类徽标之前（DOM 顺序=分类标签在名字右边）
 * 且具备截断类（truncate / overflow-hidden）——当前实现名字 span 无截断类 → 截断断言 FAIL。
 * 守卫契约（当前 PASS，弱断言）：WorldNodeView 名字 span 已含 truncate（L96 `block truncate font-medium`），
 * 本用例防实现回归移除截断类；「真实溢出视觉」需截图门/E2E（jsdom 无法验证真实渲染溢出）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MapDirectoryTree } from './MapDirectoryTree';
import { WorldNodeView } from './WorldNodeView';
import type { WorldCategoryEntity } from '../hooks/useWorldCategories';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

/** geo 分类（#721 kind 分流：非 abstract → 进树，渲染分类徽标） */
const worldItems = [
  { id: 'w-root', name: '蜀山修仙宇宙', category: '', content: '', parent_id: null },
  { id: 'w-geo', name: '蜀山派', category: '国家', content: '', parent_id: 'w-root' },
];
const worldCategories: WorldCategoryEntity[] = [
  { id: 'g1', name: '国家', kind: 'geo', count: 0 },
];

describe('MapDirectoryTree — #741 缺陷③ 分类标签不盖名字（WorldNodeRow）', () => {
  it('名字 span 在分类徽标之前（DOM 顺序）且具备截断类（RED：当前名字 span 无 truncate/overflow-hidden → 截断断言 FAIL）', () => {
    render(
      <MapDirectoryTree
        maps={[]}
        activeMapId={null}
        onSelectMap={vi.fn()}
        onCreateChild={vi.fn()}
        onDeleteMap={vi.fn()}
        onRenameMap={vi.fn()}
        onReparent={vi.fn()}
        onCycleReject={vi.fn()}
        worldItems={worldItems}
        worldCategories={worldCategories}
      />,
    );
    // 名字 span（L381：min-w-0 flex-1 whitespace-nowrap）；分类徽标 span（L384-388：shrink-0 rounded-full）
    const nameEl = screen.getByText('蜀山派');
    const badgeEl = screen.getByText('国家');

    // ① 分类标签在名字右边：名字元素是徽标元素的前序节点（DOM 顺序）
    expect(nameEl.compareDocumentPosition(badgeEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // ② RED：名字 span 必须截断（truncate = overflow-hidden + ellipsis + nowrap），
    //    否则长名溢出到徽标下方=「标签盖名字」；当前 className=`min-w-0 flex-1 whitespace-nowrap` → 断言 FAIL。
    //    GREEN 契约：名字 span 增加 truncate（或 overflow-hidden）。
    expect(nameEl.className).toMatch(/(^|\s)(truncate|overflow-hidden)(\s|$)/);
  });
});

describe('WorldNodeView — #741 缺陷③ 回归守卫（弱断言/待截图门验证）', () => {
  it('页面树行：名字在分类徽标之前且名字 span 含 truncate（当前已满足 PASS；jsdom 无法验证真实溢出渲染，视觉部分待截图门）', () => {
    const longName = '长到会溢出到分类徽标下方的世界观名字'.repeat(10);
    render(
      <WorldNodeView
        node={{
          item: { id: 'w1', name: longName, category: '国家', content: '', parent_id: null },
          children: [],
        }}
        depth={0}
        collapsed={new Set()}
        onToggle={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onCopy={vi.fn()}
      />,
    );
    const nameEl = screen.getByText(longName);
    const badgeEl = screen.getByText('国家');

    // ① 分类标签在名字右边（DOM 顺序）
    expect(nameEl.compareDocumentPosition(badgeEl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // ② WorldNodeView L96 名字 span 已含 truncate（block truncate font-medium）→ 当前 PASS；
    //    若实现回归移除截断类则 FAIL（守卫）。说明：本用例非 RED——WorldNodeView 在当前代码下已具备截断类，
    //    真实「标签盖名字」视觉缺陷是否仍存在于页面树需截图门/E2E 验证。
    expect(nameEl.className).toMatch(/(^|\s)truncate(\s|$)/);
  });
});
