/**
 * #378 地图工作台目录树 + 拖拽层级（issue #378 + specs/f36-world-map/spec.md v1.3 §2.1 parent_map_id）：
 * 左栏地图树改文件树风格（根图→子图→孙图，缩进层级 + 图标区分 + 连接线），
 * 节点 hover 操作（新建子图/删除/编辑），拖拽调整 parent_map_id 层级。
 *
 * ⚠️ 本批契约独立文件 library-p3.test.tsx（library-p2.test.tsx 已近 900 行护栏）。
 *
 * ==================== GREEN 契约（MapWorkbench 左栏目录树 + 拖拽，mock apiFetch） ====================
 *
 * 【testid 清单】
 * 目录树容器：map-directory-tree
 * 节点行：map-tree-node-<mapId>（根图/子图统一；行内可拖拽）
 * 拖拽把手：map-tree-drag-<mapId>（draggable 元素，dragstart 携带源图 id）
 * 树空白区（拖到根/空白 → parent_map_id=null）：map-tree-drop-zone
 * 节点操作（hover 显示）：map-tree-child-<mapId>（新建子图）/ map-tree-del-<mapId>（删除）/
 *   map-tree-edit-<mapId>（编辑）
 * 选中态：map-tree-node-<mapId> 行 class 含 active（activeMapId 命中）
 *
 * 【端点 + body 形状】
 * GET   /api/v1/projects/{pid}/maps   → {items:[Map],total}（Map 含 id/name/parent_map_id/root_location_id）
 * PATCH /api/v1/maps/{id}             拖拽改挂 body {parent_map_id: '<目标 id>' | null}
 *   （null = 拖到空白/根 → 变根图；目标 id = 成为其子图）
 *
 * 【交互契约（GREEN 必守）】
 * - 树层级：parent_map_id=null → 顶层根图；parent_map_id=<id> → 该 id 图下子图（递归，深度不限）；
 *   子图行缩进大于父图行（style.paddingLeft 数值递增）
 * - 拖拽：dragstart 源（map-tree-drag-<src>）→ dragover 目标节点（map-tree-node-<dst>）→ drop →
 *   PATCH /api/v1/maps/<src> body {parent_map_id: <dst>} → 成功刷新后树重排（src 出现在 dst 下）
 * - 拖到空白区（map-tree-drop-zone）→ PATCH body {parent_map_id: null} → src 变根图
 * - 循环拒绝：拖源图到其自身子孙节点（如 root1 → child1）→ 不发 PATCH + err toast
 * - 拖拽不引入新依赖（原生 HTML5 drag & drop：onDragStart/onDragOver/onDrop）
 *
 * RED 预期：map-directory-tree / map-tree-* 全部不存在（当前左栏为条目树 + 🗺 徽标混合）→
 * element-missing 断言 FAIL；PATCH parent_map_id 断言无调用 → FAIL。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { LibraryPage } from './library';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};
const projectP2 = {
  id: 'p2', name: '归墟记', tags: ['仙侠'], language: 'zh-CN', target_words: 500000, config: {},
  created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

function renderLibrary() {
  return render(
    <MemoryRouter initialEntries={['/library']}>
      <LibraryPage />
      <Routes>
        <Route path="/projects" element={<div />} />
        <Route path="/writing" element={<div />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** #378 地图目录树地图工厂：parent_map_id 定义层级 */
function makeMap(id: string, name: string, parent_map_id: string | null = null) {
  return {
    id, project_id: 'p1', name, image_path: '', description: '',
    root_location_id: null, parent_map_id, bg_source: 'shape', extra: {},
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  };
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useToastStore.setState({ toasts: [] });
});

describe('#378 地图工作台目录树 + 拖拽层级（世界观 tab，issue #378）', () => {
  /** 状态化 mock：maps 数组可变；PATCH /maps/{id} 合并回写 parent_map_id */
  function mockMapTree(maps: Array<Record<string, unknown>>) {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') {
        return { items: [projectP1, projectP2], total: 2, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/maps') {
        return { items: maps, total: maps.length, offset: 0, limit: 50 };
      }
      const mapsPatchMatch = path.match(/^\/api\/v1\/maps\/([^/]+)$/);
      if (mapsPatchMatch && init?.method === 'PATCH') {
        const idx = maps.findIndex((m) => String(m.id) === mapsPatchMatch[1]);
        if (idx >= 0) {
          maps[idx] = { ...maps[idx], ...(init.body as Record<string, unknown>) };
          return maps[idx];
        }
      }
      if (/^\/api\/v1\/maps\/[^/]+\/pins$/.test(path)) return { items: [], total: 0, offset: 0, limit: 50 };
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1, projectP2], currentProjectId: 'p1' });
    });
  }

  /** 进世界观 tab（#389 导航反转：tab 默认停列表页/空态 → 点「地图视图」按钮才进工作台） */
  async function enterWorkbench(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('map-view-entry');
    await user.click(screen.getByTestId('map-view-entry'));
    await screen.findByTestId('map-workbench');
  }

  /** 构造 drag 事件 dataTransfer（jsdom 无完整 DataTransfer） */
  function makeDataTransfer() {
    return { setData: vi.fn(), getData: vi.fn(() => ''), dropEffect: 'move' as const };
  }

  it('T1 目录树渲染层级：根图顶层、子图缩进递增、孙图更深，节点可选中', async () => {
    const maps = [
      makeMap('root1', '九州总图'),
      makeMap('child1', '中州分图', 'root1'),
      makeMap('grand1', '中州细图', 'child1'),
      makeMap('root2', '南疆总图'),
    ];
    mockMapTree(maps);
    renderLibrary();
    const user = userEvent.setup();
    await enterWorkbench(user);
    // 目录树容器存在
    const tree = await screen.findByTestId('map-directory-tree');
    // 四个节点行均渲染
    for (const id of ['root1', 'child1', 'grand1', 'root2']) {
      expect(within(tree).getByTestId(`map-tree-node-${id}`)).toBeInTheDocument();
    }
    // 层级缩进：child1 > root1，grand1 > child1（style.paddingLeft 数值递增）
    const pad = (id: string) => {
      const node = within(tree).getByTestId(`map-tree-node-${id}`);
      return Number.parseInt(node.style.paddingLeft || '0', 10);
    };
    expect(pad('child1')).toBeGreaterThan(pad('root1'));
    expect(pad('grand1')).toBeGreaterThan(pad('child1'));
    expect(pad('root2')).toBe(pad('root1'));
    // 点击节点 → 选中（面包屑显示地图名）
    await user.click(within(tree).getByTestId('map-tree-node-child1'));
    expect(screen.getByTestId('map-bc-current')).toHaveTextContent('中州分图');
  });

  it('T2 拖拽到另一节点 → PATCH body {parent_map_id: 目标 id} → 树重排', async () => {
    const maps = [
      makeMap('root1', '九州总图'),
      makeMap('root2', '南疆总图'),
      makeMap('child1', '中州分图', 'root1'),
    ];
    mockMapTree(maps);
    renderLibrary();
    const user = userEvent.setup();
    await enterWorkbench(user);
    const tree = await screen.findByTestId('map-directory-tree');
    // 拖 child1 → root2：PATCH /maps/child1 body {parent_map_id: root2}
    fireEvent.dragStart(within(tree).getByTestId('map-tree-drag-child1'), {
      dataTransfer: makeDataTransfer(),
    });
    fireEvent.dragOver(within(tree).getByTestId('map-tree-node-root2'));
    fireEvent.drop(within(tree).getByTestId('map-tree-node-root2'));
    await waitFor(() => {
      const patchCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/maps/child1' && c[1]?.method === 'PATCH',
      );
      expect(patchCall).toBeTruthy();
      expect((patchCall![1]!.body as { parent_map_id?: string | null }).parent_map_id).toBe('root2');
    });
    // 状态化 mock 合并 → 树重排：child1 出现在 root2 下（缩进 == 一级子图）
    await waitFor(() => {
      const childNode = within(tree).getByTestId('map-tree-node-child1');
      const root2Node = within(tree).getByTestId('map-tree-node-root2');
      expect(Number.parseInt(childNode.style.paddingLeft || '0', 10)).toBeGreaterThan(
        Number.parseInt(root2Node.style.paddingLeft || '0', 10),
      );
    });
  });

  it('T3 拖拽到空白/根区域 → PATCH body {parent_map_id: null} → 变根图', async () => {
    const maps = [
      makeMap('root1', '九州总图'),
      makeMap('child1', '中州分图', 'root1'),
    ];
    mockMapTree(maps);
    renderLibrary();
    const user = userEvent.setup();
    await enterWorkbench(user);
    const tree = await screen.findByTestId('map-directory-tree');
    fireEvent.dragStart(within(tree).getByTestId('map-tree-drag-child1'), {
      dataTransfer: makeDataTransfer(),
    });
    const zone = within(tree).getByTestId('map-tree-drop-zone');
    fireEvent.dragOver(zone);
    fireEvent.drop(zone);
    await waitFor(() => {
      const patchCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/maps/child1' && c[1]?.method === 'PATCH',
      );
      expect(patchCall).toBeTruthy();
      expect((patchCall![1]!.body as { parent_map_id?: string | null }).parent_map_id).toBeNull();
    });
    // 树重排：child1 缩进回根图层级（与 root1 同级）
    await waitFor(() => {
      const childNode = within(tree).getByTestId('map-tree-node-child1');
      const root1Node = within(tree).getByTestId('map-tree-node-root1');
      expect(Number.parseInt(childNode.style.paddingLeft || '0', 10)).toBe(
        Number.parseInt(root1Node.style.paddingLeft || '0', 10),
      );
    });
  });

  it('T4 循环拖拽拒绝：拖源图到自身子孙 → 不发 PATCH + err toast', async () => {
    const maps = [
      makeMap('root1', '九州总图'),
      makeMap('child1', '中州分图', 'root1'),
      makeMap('grand1', '中州细图', 'child1'),
    ];
    mockMapTree(maps);
    renderLibrary();
    const user = userEvent.setup();
    await enterWorkbench(user);
    const tree = await screen.findByTestId('map-directory-tree');
    // 拖 root1 → 其子孙 child1（循环）：前端拒绝，不发 PATCH
    fireEvent.dragStart(within(tree).getByTestId('map-tree-drag-root1'), {
      dataTransfer: makeDataTransfer(),
    });
    fireEvent.dragOver(within(tree).getByTestId('map-tree-node-child1'));
    fireEvent.drop(within(tree).getByTestId('map-tree-node-child1'));
    // 断言无 PATCH 调用（等待一小段确保无异步触发）
    await new Promise((r) => setTimeout(r, 150));
    const patchCalls = apiFetchMock.mock.calls.filter(
      (c) => /^\/api\/v1\/maps\/[^/]+$/.test(c[0]) && c[1]?.method === 'PATCH',
    );
    expect(patchCalls).toHaveLength(0);
    // err toast（循环拖拽被拒提示）
    expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
  });

  it('T5 节点 hover 操作：新建子图/删除/编辑按钮存在，点击新建子图 → POST 带 parent_map_id', async () => {
    const maps = [
      makeMap('root1', '九州总图'),
      makeMap('child1', '中州分图', 'root1'),
    ];
    const baseImpl = apiFetchMock.getMockImplementation();
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects/p1/maps' && init?.method === 'POST') {
        return { ...makeMap('m9', '新分图'), id: 'm9', name: '新分图', parent_map_id: 'child1' };
      }
      return baseImpl!(path, init);
    });
    mockMapTree(maps);
    renderLibrary();
    const user = userEvent.setup();
    await enterWorkbench(user);
    const tree = await screen.findByTestId('map-directory-tree');
    // hover 操作按钮（测试环境恒渲染；opacity 样式不影响存在性断言）
    expect(within(tree).getByTestId('map-tree-child-child1')).toBeInTheDocument();
    expect(within(tree).getByTestId('map-tree-del-child1')).toBeInTheDocument();
    expect(within(tree).getByTestId('map-tree-edit-child1')).toBeInTheDocument();
    // 新建子图 → 对话框 → POST 携带 parent_map_id=child1
    await user.click(within(tree).getByTestId('map-tree-child-child1'));
    const nameInput = await screen.findByTestId('map-create-name');
    await user.type(nameInput, '新分图');
    await user.click(screen.getByTestId('map-create-save'));
    await waitFor(() => {
      const postCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/maps' && c[1]?.method === 'POST',
      );
      expect(postCall).toBeTruthy();
      const body = postCall![1]!.body;
      if (body instanceof FormData) {
        expect(String(body.get('parent_map_id'))).toBe('child1');
      } else {
        expect(body).toEqual(expect.objectContaining({ parent_map_id: 'child1' }));
      }
    });
  });
});
