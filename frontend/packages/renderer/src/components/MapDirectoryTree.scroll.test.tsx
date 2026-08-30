/** #728 地地图树/地图视图多层显示不全：树容器应提供横向滚动（overflow-x-auto），深层节点不被截断。 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MapDirectoryTree } from './MapDirectoryTree';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('MapDirectoryTree — #728 横向滚动', () => {
  it('地图树容器提供横向滚动（overflow-x-auto），深层节点不被截断', () => {
    const maps = [
      { id: 'm1', project_id: 'p1', name: '大域', parent_map_id: null, root_location_id: null },
      { id: 'm2', project_id: 'p1', name: '州', parent_map_id: 'm1', root_location_id: null },
      { id: 'm3', project_id: 'p1', name: '城', parent_map_id: 'm2', root_location_id: null },
    ];
    render(
      <MapDirectoryTree
        maps={maps}
        activeMapId={null}
        onSelectMap={vi.fn()}
        onCreateChild={vi.fn()}
        onDeleteMap={vi.fn()}
        onRenameMap={vi.fn()}
        onReparent={vi.fn()}
        onCycleReject={vi.fn()}
      />,
    );
    const tree = screen.getByTestId('map-directory-tree');
    expect(tree.className).toContain('overflow-x-auto');
  });
});
