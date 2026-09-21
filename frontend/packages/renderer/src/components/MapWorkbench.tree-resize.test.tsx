/**
 * #1322 地图工作台左栏左右拖动改宽（问题 2：子树深时看不全）。
 *
 * 形态照抄写作页 #702/#720（ProjectTree.tsx:70-86 startResize + writing.tsx:182-192
 * startRailColResize）：window mousemove/mouseup + clamp，**内存态不持久化**。
 * clamp 放宽到 240~640 —— 地图行含 🗺 徽标 + 分类 + 4 个行操作按钮，写作页的 360 不够。
 *
 * 🔴 拖动**不替代** overflow-x-auto（#728 契约，见 MapDirectoryTree.scroll.test.tsx）：
 * 外层卡片的 overflow-hidden 是裁切元凶，两者并存。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MapWorkbench } from './MapWorkbench';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

const worldItems = [
  { id: 'w-root', name: '蜀山修仙宇宙', category: '', content: '', parent_id: null },
];
const maps = [
  { id: 'm1', project_id: 'p1', name: '九州舆图', parent_map_id: null, root_location_id: null },
];

function renderWorkbench() {
  return render(
    <MapWorkbench
      projectId="p1"
      worldItems={worldItems}
      maps={maps}
      activeMapId={null}
      onSelectMap={vi.fn()}
      onExitWorkbench={vi.fn()}
      onClearMap={vi.fn()}
      worldCategories={[]}
      worldCatEntities={[]}
      activeWorldCat={null}
      onWorldCatChange={vi.fn()}
      collapsedIds={new Set()}
      onToggle={vi.fn()}
      onEdit={vi.fn()}
      onDelete={vi.fn()}
      onCopy={vi.fn()}
      onCopyAll={vi.fn()}
      copyTargetOptions={[]}
    />,
  );
}

/** 拖动手柄：clientX 从 from 移到 to（mousedown → mousemove ×1 → mouseup） */
function drag(handle: HTMLElement, from: number, to: number) {
  fireEvent.mouseDown(handle, { clientX: from });
  fireEvent.mouseMove(window, { clientX: to });
  fireEvent.mouseUp(window);
}

const widthOf = () => parseFloat(screen.getByTestId('map-tree-column').style.width);

describe('MapWorkbench — #1322 左栏 col-resize 改宽', () => {
  it('初始宽度 260px + 手柄存在且 cursor-col-resize', () => {
    renderWorkbench();
    expect(widthOf()).toBe(260);
    expect(screen.getByTestId('map-tree-resize-handle').className).toContain('cursor-col-resize');
  });

  it('向右拖动 → 左栏变宽；向左拖动 → 变窄', () => {
    renderWorkbench();
    const handle = screen.getByTestId('map-tree-resize-handle');
    drag(handle, 300, 420);
    expect(widthOf()).toBe(380);
    drag(handle, 300, 180);
    expect(widthOf()).toBe(260);
  });

  it('clamp 到 240~640：极端拖动不越界', () => {
    renderWorkbench();
    const handle = screen.getByTestId('map-tree-resize-handle');
    drag(handle, 300, -5000);
    expect(widthOf()).toBe(240);
    drag(handle, 300, 5000);
    expect(widthOf()).toBe(640);
  });

  it('mouseup 后不再响应 mousemove（监听器已摘除）', () => {
    renderWorkbench();
    const handle = screen.getByTestId('map-tree-resize-handle');
    drag(handle, 300, 420);
    expect(widthOf()).toBe(380);
    fireEvent.mouseMove(window, { clientX: 900 });
    expect(widthOf()).toBe(380);
  });
});
