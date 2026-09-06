/**
 * 地图工作台三缺陷修复契约（#973 / #978 / #979，0.13.0-rc4 实测缺陷）。
 * 拆分至独立文件：library-p2.test.tsx 已 813 行，追加将破 check_file_length 900 护栏。
 *
 * ==================== GREEN 契约 ====================
 *
 * 【#973 maps 快照刷新（pages/library.tsx :220-236）】
 * - maps 拉取 effect 依赖扩为 [currentProjectId, reloadKey, workbenchActive]：
 *   进入/退出工作台（setWorkbenchActive 两处入口 :711/:725）与 reloadKey 变化（分类保存
 *   hook onSaved :156-159）均重拉 GET /api/v1/projects/{pid}/maps。
 * - 失败分支（:230-231）勿静默置空：pushToast('err', errorMessage(err))（同 MapWorkbench
 *   .refreshPins 先例；errorMessage 从 '../api/client' 导入，library.tsx :5 已在用）。
 *
 * 【#978 删除钮重叠（components/MapCanvas.tsx 选中态形状层）——用户拍板方案：把手扩大 + 删除钮框进形内】
 * - 删除钮锚位 -right-2 -top-2 → right-1 top-1（形状框内右上 4px）+ z-10（与 NE 把手
 *   4×4px 微重叠区钮优先命中）。
 * - 四角 resize 把手 h-3 w-3 (12px) → h-4 w-4 (16px)（对齐设计稿 8 向把手形态，锚点不动）。
 * - jsdom 无盒模型 → 契约退化为 className 锚位组合断言（issue #978 body 预授权的退化形态）。
 *
 * 【#979 pin 无标签不可点（components/MapCanvas.tsx :448-462 + MapWorkbench pin 列表）】
 * - MapCanvasProps 扩展：selectedPinId: string | null + onSelectPin: (pin) => void（可选属性，
 *   缺省降级现状）。
 * - pin 容器：pointer-events-none → pointer-events-auto；onClick stopPropagation（复用 shape
 *   层 :356-359 先例，防冒泡触发画布添加 pin）+ 触发 onSelectPin；图标右侧渲染
 *   <span>{pin.label}</span>（text-[12px] truncate max-w-[140px]，对齐原型「圆点+文字」）。
 * - 选中态可观测锚：画布 pin 容器 data-selected="true"；列表行 <li data-testid={`map-pin-row-${id}`}
 *   data-selected="true">（MapWorkbench 持 selectedPinId state，行 ref → scrollIntoView({block:'nearest'})）。
 * - 点击列表行同样选中（滚动定位画布不必断言，jsdom 无滚动）。
 *
 * 【testid 清单（本文件新增）】map-pin-row-x（x = pin id，列表行，#979）
 * 复用既有：map-canvas / map-pin-x / map-pin-list / map-shape-x / map-shape-del-x /
 *   map-shape-resize-x-<corner> / map-view-entry / world-map-badge-x / world-cat-add /
 *   world-cat-name / world-cat-save / pin-dialog
 *
 * RED 预期：K1-K3 / S1 / P1-P3 全部 FAIL（锚点缺失或旧行为），零 SyntaxError /
 * ReferenceError / TypeError；既有 library-p2.test.tsx 迁移点见该文件 M8（#979 迁移注释）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
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

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}{location.search}</div>;
}

function renderLibrary(initialPath = '/library') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LibraryPage />
      <Routes>
        <Route path="/projects" element={<LocationProbe />} />
        <Route path="/writing" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  // scrollIntoView 在 jsdom 不存在（GREEN 实现若直调会崩测试），桩为 no-op（不断言调用）
  Element.prototype.scrollIntoView = vi.fn();
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('地图工作台修复契约（#973 快照刷新 / #978 删除钮重叠 / #979 pin 标签与点击）', () => {
  /** 世界观树：w1 顶层 + w1a 子级（地图 root_location_id 挂靠点） */
  const worldTree: Array<Record<string, unknown>> = [
    { id: 'w1', name: '九州', category: '地图', content: '天下地理' },
    { id: 'w1a', name: '中州', category: '地图', content: '中原腹地', parent_id: 'w1' },
  ];

  const mapM1: Record<string, unknown> = {
    id: 'm1', project_id: 'p1', name: '九州舆图', image_path: '', description: '',
    root_location_id: 'w1', bg_source: 'image', extra: {},
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  };

  /** 简图预置地图（#978：bg_source=shape + s_1 方框） */
  const mapM2: Record<string, unknown> = {
    id: 'm2', project_id: 'p1', name: '中州细图', image_path: '', description: '',
    root_location_id: 'w1a', bg_source: 'shape',
    extra: { shapes: [{ id: 's_1', type: 'rect', x: 35, y: 35, w: 24, h: 16, label: '新区域' }] },
    created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  };

  const pinP1: Record<string, unknown> = {
    id: 'p1', map_id: 'm1', location_id: null, ref_id: 'c1', type: 'role', x: 20, y: 30, label: '标记一',
    created_at: '2026-08-03T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  };
  const pinP2: Record<string, unknown> = {
    id: 'p2', map_id: 'm1', location_id: 'w1', ref_id: null, type: 'location', x: 40, y: 50, label: '标记二',
    created_at: '2026-08-03T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  };

  /** 播种工作台端点 mock（GET 面，形态对齐 library-p2.test.tsx mockMapWorkbench） */
  function mockWorkbench(
    worldItems: Array<Record<string, unknown>>,
    maps: Array<Record<string, unknown>>,
    pinsByMap: Record<string, Array<Record<string, unknown>>> = {},
  ) {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') {
        return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/world-settings') {
        return { items: worldItems, total: worldItems.length, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/maps') {
        return { items: maps, total: maps.length, offset: 0, limit: 50 };
      }
      const pinsMatch = path.match(/^\/api\/v1\/maps\/([^/]+)\/pins$/);
      if (pinsMatch) {
        const list = pinsByMap[pinsMatch[1]] ?? [];
        return { items: list, total: list.length, offset: 0, limit: 50 };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
  }

  /** 世界观 tab → 列表页 → 「地图视图」进工作台 → 点徽标选图（badgeId 默认 w1） */
  async function openMapWorkbench(user: ReturnType<typeof userEvent.setup>, badgeId = 'w1') {
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('map-view-entry'));
    await screen.findByTestId('map-workbench');
    await user.click(screen.getByTestId(`world-map-badge-${badgeId}`));
    await screen.findByTestId('map-canvas');
  }

  const mapsGetCalls = () =>
    apiFetchMock.mock.calls.filter(
      (c) => c[0] === '/api/v1/projects/p1/maps' && (c[1]?.method ?? 'GET') === 'GET',
    ).length;

  // ───────── #973 maps 快照刷新 ─────────

  it('K1【R】外部建图后点「地图视图」进工作台应见新图（进工作台重拉 maps，而非挂载时空快照）', async () => {
    // 挂载时内核无图；GUI 停留期间外部（CLI/HTTP/MCP）建图 m1 → mock 热更新返回
    mockWorkbench(worldTree, []);
    renderLibrary();
    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    await waitFor(() => expect(mapsGetCalls()).toBeGreaterThanOrEqual(1));
    const mountCalls = mapsGetCalls();
    // 模拟外部建图：后续 GET maps 开始返回 m1（GUI 若不重拉则永远不可见）
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') {
        return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/world-settings') {
        return { items: worldTree, total: worldTree.length, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/maps') {
        return { items: [mapM1], total: 1, offset: 0, limit: 50 };
      }
      return init ? { items: [], total: 0 } : { items: [], total: 0, offset: 0, limit: 50 };
    });
    // 进工作台 → 应重拉（calls > mountCalls）且新图徽标出现；现状：不重拉 → badge 缺失 FAIL
    await user.click(screen.getByTestId('map-view-entry'));
    await waitFor(() => expect(mapsGetCalls()).toBeGreaterThan(mountCalls));
    expect(await screen.findByTestId('world-map-badge-w1')).toBeInTheDocument();
  });

  it('K2【R】maps 拉取失败勿静默置空：应 pushToast err（同 refreshPins 先例）', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1 };
      if (path === '/api/v1/projects/p1/maps') throw new Error('maps boom');
      return { items: [], total: 0 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    renderLibrary();
    // 现状：catch 静默 setMaps([]) 零提示 → 断言 err toast FAIL
    await waitFor(() => {
      expect(
        useToastStore.getState().toasts.some((t) => t.type === 'err' && t.message.includes('maps boom')),
      ).toBe(true);
    });
  });

  it('K3【R】reloadKey 变化（新建分类保存）→ maps 重拉（reloadKey 纳入 effect 依赖，同族列表都吃唯独 maps 不吃属遗漏面）', async () => {
    const categories: Array<{ id: string; name: string; count: number }> = [];
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/world-settings') {
        return { items: worldTree, total: worldTree.length, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/maps') return { items: [], total: 0, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/world-categories' && init?.method === 'POST') {
        const cat = { id: `wc${categories.length + 1}`, name: (init.body as { name: string }).name, count: 0 };
        categories.push(cat);
        return { ...cat, project_id: 'p1' };
      }
      if (path === '/api/v1/projects/p1/world-categories') {
        return { items: categories.map((c) => ({ ...c })), total: categories.length };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    renderLibrary();
    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    await waitFor(() => expect(mapsGetCalls()).toBeGreaterThanOrEqual(1));
    const before = mapsGetCalls();
    // 新建分类 → POST → hook onSaved → setReloadKey+1 → maps effect 应重跑
    await user.click(screen.getByTestId('world-cat-add'));
    await user.type(await screen.findByTestId('world-cat-name'), '势力');
    await user.click(screen.getByTestId('world-cat-save'));
    await screen.findByTestId('world-cat-filter-势力');
    await waitFor(() => expect(mapsGetCalls()).toBeGreaterThan(before));
  });

  // ───────── #978 删除钮锚位（方案：形内右上 + 把手扩大） ─────────

  it('S1【R】选中形状后删除钮锚位 = 形内右上（right-1/top-1/z-10），resize 把手扩大为 h-4 w-4', async () => {
    mockWorkbench(worldTree, [mapM2]);
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user, 'w1a');
    await waitFor(() => expect(screen.getAllByTestId(/^map-shape-s_/)).toHaveLength(1));
    await user.click(screen.getByTestId('map-shape-s_1'));
    const delBtn = await screen.findByTestId('map-shape-del-s_1');
    // 旧锚位（-right-2 -top-2 与 NE 把手热区重合）必须退役；新锚位 = 形内右上 + z-10
    expect(delBtn.className).toContain('right-1');
    expect(delBtn.className).toContain('top-1');
    expect(delBtn.className).toContain('z-10');
    expect(delBtn.className).not.toContain('-right-2');
    expect(delBtn.className).not.toContain('-top-2');
    const neHandle = await screen.findByTestId('map-shape-resize-s_1-ne');
    expect(neHandle.className).toContain('h-4');
    expect(neHandle.className).toContain('w-4');
    expect(neHandle.className).not.toContain('h-3');
    // 其余三角同步扩大（四角一致性）
    for (const corner of ['nw', 'sw', 'se'] as const) {
      const h = await screen.findByTestId(`map-shape-resize-s_1-${corner}`);
      expect(h.className).toContain('h-4');
    }
    // 删除功能回归：点钮 → 形状消失 + PATCH extra.shapes 移除 s_1
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1 };
      return { items: [], total: 0 };
    });
    await user.click(delBtn);
    await waitFor(() => {
      const patch = apiFetchMock.mock.calls.find(
        (c) =>
          c[0] === '/api/v1/maps/m2' &&
          c[1]?.method === 'PATCH' &&
          (c[1]!.body as { extra?: { shapes?: unknown[] } }).extra?.shapes !== undefined,
      );
      expect(patch).toBeTruthy();
      const shapes = (patch![1]!.body as { extra: { shapes: Array<{ id: string }> } }).extra.shapes;
      expect(shapes.find((x) => x.id === 's_1')).toBeUndefined();
    });
  });

  // ───────── #979 pin 标签 + 可点选中 ─────────

  it('P1【R】画布 pin 可见 label 文本 + pointer-events-auto（现状图标-only + pointer-events-none）', async () => {
    mockWorkbench(worldTree, [mapM1], { m1: [pinP1, pinP2] });
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    await waitFor(() => expect(screen.getAllByTestId(/^map-pin-p\d+$/)).toHaveLength(2));
    const pin = screen.getByTestId('map-pin-p1');
    expect(pin).toHaveTextContent('标记一');
    expect(pin.className).toContain('pointer-events-auto');
    expect(pin.className).not.toContain('pointer-events-none');
  });

  it('P2【R】点击画布 pin：stopPropagation 不新增 pin（现状点击冒泡到画布 → 误弹新建 PinDialog）', async () => {
    mockWorkbench(worldTree, [mapM1], { m1: [pinP1, pinP2] });
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    await waitFor(() => expect(screen.getAllByTestId(/^map-pin-p\d+$/)).toHaveLength(2));
    // mock canvas rect（同 library-p2 clickCanvasCenter 契约基准）：不 mock 则 handleCanvasClick
    // 的 width<=0 守卫直接 return，「pin 点击冒泡误加 pin」的缺陷形态无法在 jsdom 触达。
    const canvas = screen.getByTestId('map-canvas');
    canvas.getBoundingClientRect = () =>
      ({
        left: 100, top: 50, width: 200, height: 100, right: 300, bottom: 150, x: 100, y: 50,
        toJSON: () => ({}),
      }) as DOMRect;
    await user.click(screen.getByTestId('map-pin-p1'));
    // 【R】现状：pin pointer-events-none 无 handler → click 冒泡 canvas → onAddPin → PinDialog 弹出
    // → GREEN 后 pin 自带 onClick stopPropagation，此断言翻转 GREEN
    expect(screen.queryByTestId('pin-dialog')).not.toBeInTheDocument();
    expect(
      apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/maps/m1/pins' && c[1]?.method === 'POST'),
    ).toBe(false);
    // 【G】守护：画布空白点击加 pin 逻辑保持（pin 改可点后不得误伤 canvas onClick）
    await user.click(canvas);
    expect(await screen.findByTestId('pin-dialog')).toBeInTheDocument();
  });

  it('P3【R】点击画布 pin → 选中态：画布 data-selected + 列表行 map-pin-row-p1 data-selected（双向联动）', async () => {
    mockWorkbench(worldTree, [mapM1], { m1: [pinP1, pinP2] });
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    await waitFor(() => expect(screen.getAllByTestId(/^map-pin-p\d+$/)).toHaveLength(2));
    await user.click(screen.getByTestId('map-pin-p1'));
    // 画布 pin 选中高亮锚
    await waitFor(() =>
      expect(screen.getByTestId('map-pin-p1').getAttribute('data-selected')).toBe('true'),
    );
    // 列表行联动（滚动定位锚：新 testid map-pin-row-x；行 data-selected 供样式）
    const row = await screen.findByTestId('map-pin-row-p1');
    expect(row.getAttribute('data-selected')).toBe('true');
    expect(row).toHaveTextContent('标记一');
    // 点另一 pin → 选中切换（互斥单选）
    await user.click(screen.getByTestId('map-pin-p2'));
    await waitFor(() =>
      expect(screen.getByTestId('map-pin-p2').getAttribute('data-selected')).toBe('true'),
    );
    expect(screen.getByTestId('map-pin-p1').getAttribute('data-selected')).not.toBe('true');
    // 列表行点击 → 画布 pin 选中（双向）
    await user.click(within(screen.getByTestId('map-pin-list')).getByTestId('map-pin-row-p1'));
    await waitFor(() =>
      expect(screen.getByTestId('map-pin-p1').getAttribute('data-selected')).toBe('true'),
    );
  });
});
