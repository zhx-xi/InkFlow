/**
 * #1322 地图树显示门控（问题 1：新建条目自动挂根致页面树污染）。
 *
 * 语义升级：地图工作台左栏「页面树」的主体是**图**——世界观条目仅在
 * 「已挂图（root_location_id 命中）或其子孙含挂图条目」时作为图容器进主树；
 * 其余无图条目移入**「未挂图条目」折叠区**（地图工作台内），**不是隐藏**
 * ——`map-create-child-*` 入口仍在折叠区内可用，用户可为无图条目建首张图。
 *
 * 与 #721 的关系：`world-kind`（abstract 不进树）契约不变，本文件只管
 * 「有图/无图」这一维。折叠区仅在传 `onCreateChild`（= 地图工作台使用面）时渲染。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MapDirectoryTree } from './MapDirectoryTree';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

/** 顶层根条目（一项目一根 #834）+ 两个子条目：一个挂图（w-geo）、一个不挂图（w-plain） */
const worldItems = [
  { id: 'w-root', name: '蜀山修仙宇宙', category: '', content: '', parent_id: null },
  { id: 'w-geo', name: '蜀山派', category: '国家', content: '', parent_id: 'w-root' },
  { id: 'w-plain', name: '未挂图条目', category: '国家', content: '', parent_id: 'w-root' },
];

const maps = [
  { id: 'm-geo', project_id: 'p1', name: '蜀山派图', parent_map_id: null, root_location_id: 'w-geo' },
];

function renderTree() {
  return render(
    <MapDirectoryTree
      maps={maps}
      activeMapId={null}
      onSelectMap={vi.fn()}
      onCreateChild={vi.fn()}
      onDeleteMap={vi.fn()}
      onRenameMap={vi.fn()}
      onReparent={vi.fn()}
      onCycleReject={vi.fn()}
      worldItems={worldItems}
    />,
  );
}

describe('MapDirectoryTree — #1322 主树只容纳已挂图条目', () => {
  it('RED：无挂图条目不在主树内（在折叠区）；有挂图条目在主树内', () => {
    renderTree();
    const main = screen.getByTestId('map-tree-main');
    // 反向断言：有图条目（w-root 因含挂图子孙、w-geo 自身挂图）在主树
    expect(main).toHaveTextContent('蜀山修仙宇宙');
    expect(main).toHaveTextContent('蜀山派');
    // 正向：无图条目已从主树移出
    expect(main).not.toHaveTextContent('未挂图条目');
  });

  it('折叠区渲染未挂图条目（默认收起）+ 保留 map-create-child-* 建图入口', async () => {
    const user = userEvent.setup();
    const onCreateChild = vi.fn();
    render(
      <MapDirectoryTree
        maps={maps}
        activeMapId={null}
        onSelectMap={vi.fn()}
        onCreateChild={onCreateChild}
        onDeleteMap={vi.fn()}
        onRenameMap={vi.fn()}
        onReparent={vi.fn()}
        onCycleReject={vi.fn()}
        worldItems={worldItems}
      />,
    );
    const toggle = screen.getByTestId('map-tree-unmapped-toggle');
    // 默认收起：无图条目不可见、建图入口不可点
    expect(screen.queryByTestId('map-create-child-w-plain')).not.toBeInTheDocument();

    await user.click(toggle);
    expect(screen.getByText('未挂图条目')).toBeInTheDocument();
    // 建首张图的入口仍在（折叠而非隐藏是本契约的核心）
    await user.click(screen.getByTestId('map-create-child-w-plain'));
    expect(onCreateChild).toHaveBeenCalledTimes(1);
    expect(onCreateChild.mock.calls[0][0]).toMatchObject({ id: 'w-plain' });
  });

  it('无图条目一个都没有时不渲染折叠区（不进主树但也不产生空壳）', () => {
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
        worldItems={worldItems.filter((i) => i.id !== 'w-plain')}
      />,
    );
    expect(screen.queryByTestId('map-tree-unmapped-toggle')).not.toBeInTheDocument();
  });
});
