/** #721 世界观地图树分类/结构错误：按 WorldCategory.kind 分流——geo/无类别进树，abstract 不出现在树中。 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MapDirectoryTree } from './MapDirectoryTree';
import type { WorldCategoryEntity } from '../hooks/useWorldCategories';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

const worldItems = [
  { id: 'w-root', name: '蜀山修仙宇宙', category: '', content: '', parent_id: null },
  { id: 'w-geo', name: '蜀山派', category: '国家', content: '', parent_id: 'w-root' },
  { id: 'w-abs', name: '蜀山势力', category: '势力', content: '', parent_id: 'w-root' },
];
const worldCategories: WorldCategoryEntity[] = [
  { id: 'g1', name: '国家', kind: 'geo', count: 0 },
  { id: 'a1', name: '势力', kind: 'abstract', count: 0 },
];

describe('MapDirectoryTree — #721 kind 分流', () => {
  it('geo/无类别世界进树；abstract 世界（势力）不出现在地图树中', () => {
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
    expect(screen.getByText('蜀山修仙宇宙')).toBeInTheDocument();
    expect(screen.getByText('蜀山派')).toBeInTheDocument();
    expect(screen.queryByText('蜀山势力')).not.toBeInTheDocument();
  });

  /**
   * #761 守卫：地图挂载点是 abstract 分类条目（被 visibleWorldItems 过滤出树）时，
   * 该图必须经 orphanMaps（L624-631：无 parent_map_id 且 root_location_id 不命中 worldItemIds → 顶层地图节点）
   * 兜底显示为地图树节点——绝不能「既不作 orphan 也不挂 world 节点」导致图从树消失。
   * 当前实现：worldItemIds 不含 w-abs → orphanMaps 命中 → map-tree-node-m-abs 渲染（PASS，防回归）。
   */
  it('守卫：挂 abstract 分类条目的图仍显示（orphanMaps 兜底，防 #761 filter 排除图）', () => {
    render(
      <MapDirectoryTree
        maps={[
          {
            id: 'm-abs',
            project_id: 'p1',
            name: '势力图',
            root_location_id: 'w-abs',
            parent_map_id: null,
            bg_source: 'shape',
          },
        ]}
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
    expect(screen.getByTestId('map-tree-node-m-abs')).toBeInTheDocument();
    // 条目本身仍不渲染（abstract 分流契约不变）
    expect(screen.queryByText('蜀山势力')).not.toBeInTheDocument();
  });
});
