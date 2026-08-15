/**
 * F43 P2（specs/f43-setting-library-crud/spec.md v1.2 §2.7/§3.5/§5.8-5.13/§9.5 M1-M13）：
 * 设定库世界观 tab 地图工作台——地图节点徽标（root_location_id 识别）+ 四级面包屑回跳 +
 * 三底图切换（pin 独立叠加层）+ AI 占位 + 点击画布添加标记 + PinDialog 四类型 + 一图多标记 +
 * pin 编辑/删除 + 简图 shapes 增删。
 *
 * ⚠️ 本批契约拆分至独立文件 library-p2.test.tsx（对齐 library-p1.test.tsx 先例：
 * library.test.tsx 超 900 行护栏，兄弟文件拆分）。
 *
 * ==================== GREEN 契约（library.tsx 世界观 tab + 新组件 MapWorkbench/PinDialog + i18n zh/en §6 P2 表） ====================
 *
 * 【testid 清单】
 * 工作台/面包屑：map-workbench / map-breadcrumb / map-bc-lib / map-bc-world / map-bc-maplist /
 *   map-bc-current（文本 = 当前地图名）/ map-bg-tools / map-bg-shape / map-bg-image / map-bg-ai /
 *   map-canvas / map-ai-placeholder / map-pin-add-hint
 * 树节点徽标：world-map-badge-x（x = 世界观树节点 id；root_location_id 命中 → 渲染 🗺 + pin 数，
 *   为可点击元素，点击 → 切换画布选中该地图）
 * pin 画布标记：map-pin-x（x = pin id，绝对定位 left/top 百分比）
 * pin 列表：map-pin-list / map-pin-edit-x / map-pin-del-x / map-pin-filter-x（x = type 四档 chips）
 * PinDialog：pin-dialog / pin-name / pin-type / pin-ref / pin-save / pin-cancel
 * 简图：map-shape-add-rect / map-shape-add-ellipse / map-shape-add-text（仅 bg_source=shape 渲染）/
 *   map-shape-x / map-shape-del-x（x = 前端生成 shape id，形态 s_<timestamp>，如 s_1723456789012）
 * pin 删除确认（新增契约：ConfirmDialog testidPrefix='map-pin-confirm'）：
 *   map-pin-confirm-dialog / map-pin-confirm-ok / map-pin-confirm-cancel
 *
 * 【端点 + body 形状】
 * GET   /api/v1/projects/{pid}/maps   → {items:[Map],total}（Map: id/project_id/name/image_path/
 *   description/root_location_id/bg_source('shape'|'image'|'ai')/extra/created_at/updated_at；
 *   root_location_id 与树节点 id 字符串化比较（String(root_location_id) === String(node.id)），
 *   命中 → 该节点渲染 world-map-badge-x）
 * GET   /api/v1/maps/{id}/pins        → {items:[Pin],total}（Pin: id/map_id/location_id/ref_id/
 *   type('location'|'role'|'event'|'other')/x/y/label/created_at/updated_at）
 * PATCH /api/v1/maps/{id}             底图切换 body {bg_source:'shape'|'image'|'ai'}（只改 bg_source，
 *   不触碰 pins——独立叠加层 D-18）；
 *   简图增删 body {extra:{shapes:[...]}}（整体替换，shape id 前端生成 s_ 前缀）
 * POST  /api/v1/maps/{id}/pins        body {type, location_id?/ref_id?, x, y, label}
 *   （type=role → ref_id 关联角色；type=event → ref_id 关联事件；type=location → location_id；
 *     type=other → 两者均无）
 * PATCH /api/v1/map-pins/{id}         body 含 {label,...}（编辑保存，exclude_unset 语义）
 * DELETE /api/v1/map-pins/{id}        （真删；确认后刷新列表，行消失 + ok toast）
 *
 * 【i18n key（zh/en §6 P2 表，GREEN 补）】lib.worldMap / lib.worldMapSelectTip（选择左侧地图节点查看地图）/
 *   lib.worldMapClickHint / lib.worldMapNoPins / lib.pinType.location|role|event|other（地点/角色/事件/其他）/
 *   lib.pin.name|type|ref / lib.pin.save|cancel / lib.mapBg.shape|image|ai / lib.mapBg.aiSoon（即将推出）/
 *   lib.shape.rect|ellipse|text（＋方框/＋椭圆/＋文字）/ lib.shape.newLabel|newText（新区域/新文字）
 *
 * 【交互契约（GREEN 必守）】
 * - 画布点击坐标：测试侧 mock map-canvas.getBoundingClientRect = {left:100, top:50, width:200, height:100}，
 *   user-event 中心点击 → 事件 clientX=200 / clientY=100；GREEN 按
 *   (clientX-rect.left)/rect.width*100 → x=50；同理 y=50（M7 坐标预填 / M8 POST body 断言基准）
 * - 形状点击需 stopPropagation（防冒泡触发画布添加 pin）；形状选中（点击）后 map-shape-del-x 才显示
 * - 关联实体搜索：pin-ref 输入本地过滤已加载分类列表（type=role → characters / type=event → timeline /
 *   type=location → world-settings；type=other 隐藏 pin-ref），结果以 role=option 渲染可点击；
 *   分类列表按需拉取 GET /api/v1/projects/{pid}/characters 等端点
 * - pin 删除流：map-pin-del-x → ConfirmDialog → 确认 → DELETE → 刷新后行消失 + ok toast
 *
 * RED 预期：以上 testid 全部不存在（P2 地图工作台未实现，世界观 tab 仍为 P1 树列表）
 * → element-missing 断言 FAIL（类 3 契约缺口）；零 SyntaxError / ReferenceError / TypeError。
 * M1-M13 共 13 it（M5/M7/M8/M12 多断言拆分）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};
const projectP2 = {
  id: 'p2', name: '归墟记', genre: '仙侠', language: 'zh-CN', target_words: 500000, config: {},
  created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
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
  useToastStore.setState({ toasts: [] }); // 防跨用例 ok/err toast 残留误判
  // 默认兜底 URL 分发：projects 双项目；maps/pins 端点返回空 items 数组；其余分类端点空列表（用例内覆盖）
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1, projectP2], total: 2, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/maps') return { items: [], total: 0, offset: 0, limit: 50 };
    if (/^\/api\/v1\/maps\/[^/]+\/pins$/.test(path)) return { items: [], total: 0, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('设定库页 — F43 P2 地图工作台（世界观 tab，spec §5.8-5.13/§9.5 M1-M13）', () => {
  /** 世界观树（P1 复用：w1 顶层 + w1a 子级；地图 root_location_id 挂 w1/w1a） */
  const worldTree: Array<Record<string, unknown>> = [
    { id: 'w1', name: '九州', category: '地图', content: '天下地理' },
    { id: 'w1a', name: '中州', category: '地图', content: '中原腹地', parent_id: 'w1' },
  ];

  /** Map DTO（§2.7.2）：bg_source 默认 image；extra.shapes 存简图；root_location_id 指向树节点 w1 */
  const mapM1: Record<string, unknown> = {
    id: 'm1', project_id: 'p1', name: '九州舆图', image_path: '', description: '',
    root_location_id: 'w1', bg_source: 'image', extra: {},
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  };

  /** 简图预置地图（M13：bg_source=shape + extra.shapes 含 s_1），root_location_id 指向 w1a */
  const mapM2: Record<string, unknown> = {
    id: 'm2', project_id: 'p1', name: '中州细图', image_path: '', description: '',
    root_location_id: 'w1a', bg_source: 'shape',
    extra: { shapes: [{ id: 's_1', type: 'rect', x: 35, y: 35, w: 24, h: 16, label: '新区域' }] },
    created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  };

  /** Pin DTO（§2.7.1）：type 四档 + ref_id/location_id 互斥 */
  const pinP1: Record<string, unknown> = {
    id: 'p1', map_id: 'm1', location_id: null, ref_id: 'c1', type: 'role', x: 20, y: 30, label: '标记一',
    created_at: '2026-08-03T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  };
  const pinP2: Record<string, unknown> = {
    id: 'p2', map_id: 'm1', location_id: 'w1', ref_id: null, type: 'location', x: 40, y: 50, label: '标记二',
    created_at: '2026-08-03T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  };
  const pinP3: Record<string, unknown> = {
    id: 'p3', map_id: 'm1', location_id: null, ref_id: 'e1', type: 'event', x: 60, y: 70, label: '标记三',
    created_at: '2026-08-03T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  };

  /**
   * 播种 p1 + 地图工作台端点 mock（状态化：POST pins 追加 / PATCH map-pins 合并 / DELETE 移除；
   * PATCH maps 合并回写，供非乐观实现重渲染）。
   * refLists = 六分类关联数据（type=role → characters；type=event → timeline；本地过滤零额外端点）。
   */
  function mockMapWorkbench(
    worldItems: Array<Record<string, unknown>>,
    maps: Array<Record<string, unknown>>,
    pinsByMap: Record<string, Array<Record<string, unknown>>> = {},
    refLists: {
      characters?: Array<Record<string, unknown>>;
      timeline?: Array<Record<string, unknown>>;
    } = {},
  ) {
    // pin 列表浅拷贝（跨用例隔离；用例内状态化）
    const pinLists: Record<string, Array<Record<string, unknown>>> = {};
    for (const [mapId, list] of Object.entries(pinsByMap)) {
      pinLists[mapId] = list.map((p) => ({ ...p }));
    }

    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') {
        return { items: [projectP1, projectP2], total: 2, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/world-settings') {
        return { items: worldItems, total: worldItems.length, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/maps') {
        return { items: maps, total: maps.length, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/characters') {
        const list = refLists.characters ?? [];
        return { items: list, total: list.length, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/timeline') {
        const list = refLists.timeline ?? [];
        return { items: list, total: list.length, offset: 0, limit: 50 };
      }
      const pinsMatch = path.match(/^\/api\/v1\/maps\/([^/]+)\/pins$/);
      if (pinsMatch) {
        const mapId = pinsMatch[1];
        if (init?.method === 'POST') {
          const body = init.body as Record<string, unknown>;
          const created = { id: `p${Date.now()}`, map_id: mapId, ...body };
          const list = pinLists[mapId] ?? [];
          list.push(created);
          pinLists[mapId] = list;
          return created;
        }
        const list = pinLists[mapId] ?? [];
        return { items: list, total: list.length, offset: 0, limit: 50 };
      }
      const pinPatchMatch = path.match(/^\/api\/v1\/map-pins\/([^/]+)$/);
      if (pinPatchMatch && init?.method === 'DELETE') {
        for (const list of Object.values(pinLists)) {
          const idx = list.findIndex((p) => String(p.id) === pinPatchMatch[1]);
          if (idx >= 0) list.splice(idx, 1);
        }
        return undefined;
      }
      if (pinPatchMatch && init?.method === 'PATCH') {
        for (const list of Object.values(pinLists)) {
          const idx = list.findIndex((p) => String(p.id) === pinPatchMatch[1]);
          if (idx >= 0) list[idx] = { ...list[idx], ...(init.body as Record<string, unknown>) };
        }
        return undefined;
      }
      const mapsPatchMatch = path.match(/^\/api\/v1\/maps\/([^/]+)$/);
      if (mapsPatchMatch && init?.method === 'PATCH') {
        const idx = maps.findIndex((m) => String(m.id) === mapsPatchMatch[1]);
        if (idx >= 0) {
          maps[idx] = { ...maps[idx], ...(init.body as Record<string, unknown>) };
          return maps[idx];
        }
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1, projectP2], currentProjectId: 'p1' });
    });
  }

  /** 世界观 tab 切到地图工作台并点开地图画布（badgeId = 树节点 id，默认 w1）。
   *  #389：世界观 tab 默认停列表页 → 点「地图视图」按钮进工作台 → 点 badge 选图。 */
  async function openMapWorkbench(user: ReturnType<typeof userEvent.setup>, badgeId = 'w1') {
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('map-view-entry'));
    await screen.findByTestId('map-workbench');
    await user.click(screen.getByTestId(`world-map-badge-${badgeId}`));
    await screen.findByTestId('map-canvas');
  }

  /**
   * 中心点击画布：mock rect（left:100/top:50/width:200/height:100）→ user-event 中心 =
   * clientX=200 / clientY=100 → GREEN 按 (clientX-rect.left)/rect.width*100 计算 → x=y=50
   * （文件头交互契约；M7 打开对话框 / M8 POST body 坐标断言基准）。
   */
  async function clickCanvasCenter(user: ReturnType<typeof userEvent.setup>) {
    const canvas = await screen.findByTestId('map-canvas');
    canvas.getBoundingClientRect = () =>
      ({
        left: 100, top: 50, width: 200, height: 100, right: 300, bottom: 150, x: 100, y: 50,
        toJSON: () => ({}),
      }) as DOMRect;
    await user.click(canvas);
  }

  it('M1 世界观 tab 渲染地图工作台：挂地图的节点渲染 world-map-badge-w1；无地图节点 w1a 无徽标', async () => {
    mockMapWorkbench(worldTree, [mapM1]);
    renderLibrary();
    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    // #389：列表页 → 点「地图视图」进工作台
    await user.click(screen.getByTestId('map-view-entry'));
    await screen.findByTestId('map-workbench');
    // root_location_id=w1 命中 → 🗺 徽标渲染；w1a 无地图 → 不渲染徽标
    expect(screen.getByTestId('world-map-badge-w1')).toBeInTheDocument();
    expect(screen.queryByTestId('world-map-badge-w1a')).not.toBeInTheDocument();
  });

  it('M2 点击地图节点 → map-canvas 出现 + 面包屑 map-bc-current 文本 = 地图名', async () => {
    mockMapWorkbench(worldTree, [mapM1]);
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    // 工作台布局 + 四级面包屑当前层 = 地图名（lib.worldMap 之上第四级）
    expect(screen.getByTestId('map-workbench')).toBeInTheDocument();
    expect(screen.getByTestId('map-breadcrumb')).toBeInTheDocument();
    expect(screen.getByTestId('map-bc-current')).toHaveTextContent('九州舆图');
  });

  it('M3 面包屑回跳：点 map-bc-maplist → 清空选中 → lib.worldMapSelectTip 空态', async () => {
    mockMapWorkbench(worldTree, [mapM1]);
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    await user.click(screen.getByTestId('map-bc-maplist'));
    // 画布消失 + 未选地图空态（留在工作台；文案 lib.worldMapSelectTip）
    expect(screen.queryByTestId('map-canvas')).not.toBeInTheDocument();
    expect(screen.getByText('选择左侧地图节点查看地图')).toBeInTheDocument();
  });

  it('M4 面包屑回跳：点 map-bc-world → map-workbench 消失，回普通树视图', async () => {
    mockMapWorkbench(worldTree, [mapM1]);
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    await user.click(screen.getByTestId('map-bc-world'));
    // 退出工作台 → 普通树视图（library-list 树保留，画布消失）
    expect(screen.queryByTestId('map-workbench')).not.toBeInTheDocument();
    expect(screen.queryByTestId('map-canvas')).not.toBeInTheDocument();
    expect(screen.getByTestId('library-list')).toBeInTheDocument();
  });

  it('M5 三底图切换：点 map-bg-image → PATCH body {bg_source:image}；pins 保留且不重拉（独立叠加层）', async () => {
    mockMapWorkbench(worldTree, [{ ...mapM1, bg_source: 'shape' }], { m1: [pinP1, pinP2] });
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    // pins 初始渲染 2 个（画布标记 + 列表行）
    await waitFor(() => expect(screen.getAllByTestId(/^map-pin-p\d+$/)).toHaveLength(2));
    const pinsGetCalls = () =>
      apiFetchMock.mock.calls.filter(
        (c) => c[0] === '/api/v1/maps/m1/pins' && (c[1]?.method ?? 'GET') === 'GET',
      ).length;
    const pinsGetBefore = pinsGetCalls();
    await user.click(screen.getByTestId('map-bg-image'));
    // PATCH body 仅 bg_source（不触碰 pins / extra）
    await waitFor(() => {
      const patchCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/maps/m1' && c[1]?.method === 'PATCH'
          && (c[1]!.body as { bg_source?: string }).bg_source !== undefined,
      );
      expect(patchCall).toBeTruthy();
      expect(patchCall![1]!.body).toEqual({ bg_source: 'image' });
    });
    // pin 独立叠加层（D-18）：标记 + 列表行数不变，且未触发 pins 重拉
    expect(screen.getAllByTestId(/^map-pin-p\d+$/)).toHaveLength(2);
    expect(within(screen.getByTestId('map-pin-list')).getAllByTestId(/^map-pin-edit-/)).toHaveLength(2);
    expect(pinsGetCalls()).toBe(pinsGetBefore);
  });

  it('M6 AI 底图占位：点 map-bg-ai → map-ai-placeholder 渲染「即将推出」', async () => {
    mockMapWorkbench(worldTree, [mapM1]);
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    await user.click(screen.getByTestId('map-bg-ai'));
    const placeholder = await screen.findByTestId('map-ai-placeholder');
    expect(placeholder).toHaveTextContent('即将推出');
  });

  it('M7 点击画布添加标记：中心点击 map-canvas → pin-dialog 出现（PinDialog 表单五元素齐全）', async () => {
    mockMapWorkbench(worldTree, [mapM1]);
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    await clickCanvasCenter(user);
    const dialog = await screen.findByTestId('pin-dialog');
    // PinDialog 完整表单契约（名称/类型/关联/保存/取消）
    expect(within(dialog).getByTestId('pin-name')).toBeInTheDocument();
    expect(within(dialog).getByTestId('pin-type')).toBeInTheDocument();
    expect(within(dialog).getByTestId('pin-ref')).toBeInTheDocument();
    expect(within(dialog).getByTestId('pin-save')).toBeInTheDocument();
    expect(within(dialog).getByTestId('pin-cancel')).toBeInTheDocument();
  });

  it('M8 PinDialog 四类型 + 保存：选角色 + 关联角色 → POST body {type:role, ref_id, x, y, label}', async () => {
    mockMapWorkbench(worldTree, [mapM1], {}, { characters: [{ id: 'c1', name: '林晚' }] });
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    await clickCanvasCenter(user);
    const dialog = await screen.findByTestId('pin-dialog');
    // 名称（必填）
    await user.type(within(dialog).getByTestId('pin-name'), '苏云舟');
    // 类型四档：地点/角色/事件/其他（lib.pinType.*）
    await user.click(within(dialog).getByTestId('pin-type'));
    expect(screen.getByRole('option', { name: '地点' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '角色' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '事件' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '其他' })).toBeInTheDocument();
    await user.click(screen.getByRole('option', { name: '角色' }));
    // 关联角色搜索（本地过滤 characters 列表）→ 选中 → ref_id=c1
    await user.type(within(dialog).getByTestId('pin-ref'), '林');
    await user.click(await screen.findByRole('option', { name: '林晚' }));
    await user.click(within(dialog).getByTestId('pin-save'));
    await waitFor(() => {
      const postCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/maps/m1/pins' && c[1]?.method === 'POST',
      );
      expect(postCall).toBeTruthy();
      const body = postCall![1]!.body as Record<string, unknown>;
      expect(body).toEqual(expect.objectContaining({ type: 'role', ref_id: 'c1', label: '苏云舟' }));
      // 中心点击画布（rect mock）→ 坐标 50/50
      expect(body.x).toBeCloseTo(50, 5);
      expect(body.y).toBeCloseTo(50, 5);
    });
    // 保存成功 → ok toast + 列表刷新出新行
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'ok')).toBe(true);
    });
    expect(await screen.findByText('苏云舟')).toBeInTheDocument();
  });

  it('M9 一图多标记：3 个 pin → 画布 map-pin 3 个 + 列表 3 行 + 类型筛选 chips 四档', async () => {
    mockMapWorkbench(worldTree, [mapM1], { m1: [pinP1, pinP2, pinP3] });
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    await waitFor(() => expect(screen.getAllByTestId(/^map-pin-p\d+$/)).toHaveLength(3));
    const pinList = screen.getByTestId('map-pin-list');
    expect(within(pinList).getAllByTestId(/^map-pin-edit-/)).toHaveLength(3);
    expect(within(pinList).getAllByTestId(/^map-pin-filter-/)).toHaveLength(4);
  });

  it('M10 pin 编辑：map-pin-edit-p1 → PinDialog 预填 → 改名 → PATCH body 含新 label', async () => {
    mockMapWorkbench(worldTree, [mapM1], { m1: [pinP1] });
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    await screen.findByTestId('map-pin-list');
    await user.click(await screen.findByTestId('map-pin-edit-p1'));
    const dialog = await screen.findByTestId('pin-dialog');
    // 预填：名称 = 原 label
    expect(within(dialog).getByTestId('pin-name')).toHaveValue('标记一');
    await user.clear(within(dialog).getByTestId('pin-name'));
    await user.type(within(dialog).getByTestId('pin-name'), '新名字');
    await user.click(within(dialog).getByTestId('pin-save'));
    await waitFor(() => {
      const patchCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/map-pins/p1' && c[1]?.method === 'PATCH',
      );
      expect(patchCall).toBeTruthy();
      expect(patchCall![1]!.body).toEqual(expect.objectContaining({ label: '新名字' }));
    });
    // 保存后对话框关闭 + ok toast
    await waitFor(() => {
      expect(screen.queryByTestId('pin-dialog')).not.toBeInTheDocument();
    });
    expect(useToastStore.getState().toasts.some((t) => t.type === 'ok')).toBe(true);
  });

  it('M11 pin 删除：map-pin-del-p1 → ConfirmDialog → DELETE /api/v1/map-pins/p1 → 行消失', async () => {
    mockMapWorkbench(worldTree, [mapM1], { m1: [pinP1, pinP2] });
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    await screen.findByTestId('map-pin-list');
    await user.click(await screen.findByTestId('map-pin-del-p1'));
    const confirm = await screen.findByTestId('map-pin-confirm-dialog');
    await user.click(within(confirm).getByTestId('map-pin-confirm-ok'));
    await waitFor(() => {
      const delCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/map-pins/p1' && c[1]?.method === 'DELETE',
      );
      expect(delCall).toBeTruthy();
    });
    // 状态化 mock：DELETE 清空 → 刷新后行消失，剩 1 行 + ok toast
    const pinList = screen.getByTestId('map-pin-list');
    await waitFor(() => {
      expect(within(pinList).getAllByTestId(/^map-pin-edit-/)).toHaveLength(1);
    });
    expect(within(pinList).queryByText('标记一')).not.toBeInTheDocument();
    expect(useToastStore.getState().toasts.some((t) => t.type === 'ok')).toBe(true);
  });

  it('M12 简图 shapes 添加：切 shape 底图 → map-shape-add-rect → 新形状出现 + PATCH extra.shapes', async () => {
    mockMapWorkbench(worldTree, [mapM1]);
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user);
    // 切到简图底图 → 形状工具栏按钮出现（仅 bg_source=shape 渲染）
    await user.click(screen.getByTestId('map-bg-shape'));
    await screen.findByTestId('map-shape-add-rect');
    expect(screen.getByTestId('map-shape-add-ellipse')).toBeInTheDocument();
    expect(screen.getByTestId('map-shape-add-text')).toBeInTheDocument();
    // 点 ＋方框 → 画布出现形状（默认 label 新区域）+ PATCH {extra:{shapes:[...]}} 整体替换
    await user.click(screen.getByTestId('map-shape-add-rect'));
    await waitFor(() => {
      expect(screen.getAllByTestId(/^map-shape-s_/)).toHaveLength(1);
      expect(screen.getByText('新区域')).toBeInTheDocument();
    });
    await waitFor(() => {
      const shapePatch = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/maps/m1' && c[1]?.method === 'PATCH'
          && (c[1]!.body as { extra?: { shapes?: unknown[] } }).extra?.shapes !== undefined,
      );
      expect(shapePatch).toBeTruthy();
      const shapes = (shapePatch![1]!.body as { extra: { shapes: Array<Record<string, unknown>> } }).extra.shapes;
      expect(shapes).toHaveLength(1);
      expect(shapes[0]).toEqual(expect.objectContaining({ type: 'rect', label: '新区域' }));
      expect(String(shapes[0].id)).toMatch(/^s_/);
    });
  });

  it('M13 简图 shapes 删除：选中形状 → map-shape-del-s_1 → 形状消失 + PATCH shapes 移除', async () => {
    mockMapWorkbench(worldTree, [mapM2]);
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user, 'w1a');
    // 预置形状渲染（bg_source=shape + extra.shapes 含 s_1）
    await waitFor(() => expect(screen.getAllByTestId(/^map-shape-s_/)).toHaveLength(1));
    // 选中形状 → 删除按钮出现（选中态才渲染；形状点击须 stopPropagation）
    await user.click(screen.getByTestId('map-shape-s_1'));
    const delBtn = await screen.findByTestId('map-shape-del-s_1');
    await user.click(delBtn);
    // 形状消失 + PATCH extra.shapes 移除 s_1
    await waitFor(() => {
      expect(screen.queryByTestId('map-shape-s_1')).not.toBeInTheDocument();
    });
    await waitFor(() => {
      const shapePatch = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/maps/m2' && c[1]?.method === 'PATCH'
          && (c[1]!.body as { extra?: { shapes?: Array<{ id?: string }> } }).extra?.shapes !== undefined
          && !(c[1]!.body as { extra: { shapes: Array<{ id?: string }> } }).extra.shapes.some(
            (s) => s.id === 's_1',
          ),
      );
      expect(shapePatch).toBeTruthy();
      expect((shapePatch![1]!.body as { extra: { shapes: unknown[] } }).extra.shapes).toHaveLength(0);
    });
  });

  it('#346: 地图工作台「创建根图」按钮 → POST /projects/{pid}/maps（bg_source=shape）→ 列表刷新', async () => {
    // 扩展 mock：POST maps 返回新地图（id=m9）
    const createdMap = { ...mapM1, id: 'm9', name: '新舆图', root_location_id: null };
    const baseImpl = apiFetchMock.getMockImplementation();
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects/p1/maps' && init?.method === 'POST') {
        return createdMap;
      }
      return baseImpl!(path, init);
    });
    mockMapWorkbench(worldTree, []);
    renderLibrary();
    const user = userEvent.setup();
    // 进入地图工作台（点世界观 tab）
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('map-view-entry'));
    await screen.findByTestId('map-workbench');
    // 创建根图按钮存在
    expect(screen.getByTestId('map-create-root')).toBeInTheDocument();
    await user.click(screen.getByTestId('map-create-root'));
    // 名称输入 → 保存 → POST multipart FormData（bg_source=shape 无图可建）
    const nameInput = await screen.findByTestId('map-create-name');
    await user.type(nameInput, '新舆图');
    await user.click(screen.getByTestId('map-create-save'));
    await waitFor(() => {
      const postCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/maps' && c[1]?.method === 'POST',
      );
      expect(postCall).toBeTruthy();
      const body = postCall![1]!.body;
      // apiFetch 支持 FormData 直传（multipart）；断言关键字段
      if (body instanceof FormData) {
        expect(String(body.get('name'))).toBe('新舆图');
        expect(String(body.get('bg_source'))).toBe('shape');
      } else {
        expect(body).toEqual(expect.objectContaining({ name: '新舆图', bg_source: 'shape' }));
      }
    });
    // 创建成功 → toast + 列表刷新（新地图出现在树徽标：root_location_id null → 仅 maps 状态更新）
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((x) => x.type === 'ok')).toBe(true);
    });
  });

  it('#346/#368: 地图工作台「创建子图」按钮（挂在树节点）→ POST 携带 parent_map_id（父图 id，v1.3 图挂图层级）', async () => {
    const baseImpl = apiFetchMock.getMockImplementation();
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects/p1/maps' && init?.method === 'POST') {
        return { ...mapM1, id: 'm9', name: '中州分图', parent_map_id: 'm1' };
      }
      return baseImpl!(path, init);
    });
    mockMapWorkbench(worldTree, [mapM1]);
    renderLibrary();
    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('map-view-entry'));
    await screen.findByTestId('map-workbench');
    // 树节点 w1 行有「创建子图」按钮
    const childBtn = await screen.findByTestId('map-create-child-w1');
    await user.click(childBtn);
    const nameInput = await screen.findByTestId('map-create-name');
    await user.type(nameInput, '中州分图');
    await user.click(screen.getByTestId('map-create-save'));
    await waitFor(() => {
      const postCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/maps' && c[1]?.method === 'POST',
      );
      expect(postCall).toBeTruthy();
      const body = postCall![1]!.body;
      if (body instanceof FormData) {
        // v1.3 #368：创建子图传父图 id（parent_map_id），而非条目 id（root_location_id）
        expect(String(body.get('parent_map_id'))).toBe('m1');
        expect(body.get('root_location_id')).toBeNull();
        expect(String(body.get('bg_source'))).toBe('shape');
      } else {
        expect(body).toEqual(
          expect.objectContaining({ parent_map_id: 'm1', bg_source: 'shape' }),
        );
        expect((body as Record<string, unknown>).root_location_id).toBeUndefined();
      }
    });
  });

  it('#368: 树节点行 linkedMap 命中时显示地图名（而非条目名）', async () => {
    // mapM1（九州舆图）挂 w1；w1a 无地图 → 树行主体显示地图名「九州舆图」
    mockMapWorkbench(worldTree, [mapM1]);
    renderLibrary();
    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('map-view-entry'));
    await screen.findByTestId('map-workbench');
    const row = (await screen.findByTestId('world-map-badge-w1')).closest('.tree-row');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText('九州舆图')).toBeInTheDocument();
    // w1a 无地图 → 无徽标；条目名保留显示
    expect(screen.queryByTestId('world-map-badge-w1a')).not.toBeInTheDocument();
    expect(screen.getByText('中州')).toBeInTheDocument(); // 条目名保留（w1a 无 linkedMap）
  });

  it('#368: 前端树按图层级渲染——子图（parent_map_id）出现在父图节点下', async () => {
    // m2 为 m1 的子图（parent_map_id='m1'，root_location_id=null）
    const childMap: Record<string, unknown> = {
      id: 'm2', project_id: 'p1', name: '中州细图', image_path: '', description: '',
      root_location_id: null, parent_map_id: 'm1', bg_source: 'shape', extra: {},
      created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
    };
    mockMapWorkbench(worldTree, [mapM1, childMap]);
    renderLibrary();
    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('map-view-entry'));
    await screen.findByTestId('map-workbench');
    // 父图 m1 行（挂 w1 条目徽标）显示地图名；子图 m2 行渲染在树中（可点击选中）
    const parentRow = (await screen.findByTestId('world-map-badge-w1')).closest('.tree-row');
    expect(parentRow).not.toBeNull();
    expect(within(parentRow as HTMLElement).getByText('九州舆图')).toBeInTheDocument();
    expect(screen.getByText('中州细图')).toBeInTheDocument(); // 子图节点渲染
    const childBadge = screen.getByTestId('world-map-badge-m2');
    await user.click(childBadge);
    await screen.findByTestId('map-canvas');
    expect(screen.getByTestId('map-bc-current')).toHaveTextContent('中州细图');
  });

  it('#389: 点世界观 tab → 列表页（非地图工作台）+ 分类栏无「地图」chip + 地图视图按钮进工作台', async () => {
    mockMapWorkbench(worldTree, [mapM1]);
    renderLibrary();
    const user = userEvent.setup();
    // 点世界观 tab → 列表页（分类 chips + 世界树 + 整体复制 + 地图视图按钮），非 map-workbench
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    expect(screen.queryByTestId('map-workbench')).not.toBeInTheDocument();
    expect(screen.getByTestId('world-copy-all')).toBeInTheDocument();
    // 分类栏无「地图」chip（地图归地图工作台）
    expect(screen.queryByTestId('world-cat-filter-地图')).not.toBeInTheDocument();
    // 地图视图按钮 → 进工作台
    await user.click(screen.getByTestId('map-view-entry'));
    await screen.findByTestId('map-workbench');
    expect(screen.getByTestId('world-map-badge-w1')).toBeInTheDocument();
    // 退出工作台回列表页（map-bc-world）→ 地图视图按钮仍在
    await user.click(screen.getByTestId('map-bc-world'));
    await screen.findByTestId('library-list');
    expect(screen.getByTestId('map-view-entry')).toBeInTheDocument();
  });

  it('#377: 创建根图成功后自动选中新图（右侧渲染画布 + 面包屑=新图名）+ 树含新节点', async () => {
    // POST 返回新根图（root_location_id=null / parent_map_id=null，无条目挂靠点）
    const createdMap: Record<string, unknown> = {
      ...mapM1, id: 'm9', name: '新舆图', root_location_id: null, parent_map_id: null,
    };
    // 先装工作台默认 mock，再覆盖 POST maps（mockImplementation 整体替换，顺序不可反）
    mockMapWorkbench(worldTree, []);
    const baseImpl = apiFetchMock.getMockImplementation();
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects/p1/maps' && init?.method === 'POST') {
        return createdMap;
      }
      return baseImpl!(path, init);
    });
    renderLibrary();
    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('map-view-entry'));
    await screen.findByTestId('map-workbench');
    // 创建根图（空地图列表 → 无既有选中）
    await user.click(screen.getByTestId('map-create-root'));
    const nameInput = await screen.findByTestId('map-create-name');
    await user.type(nameInput, '新舆图');
    await user.click(screen.getByTestId('map-create-save'));
    // ① 自动选中：右侧渲染新图画布 + 面包屑当前层 = 新图名（activeMapId 已更新）
    await waitFor(() => {
      expect(screen.getByTestId('map-bc-current')).toHaveTextContent('新舆图');
    });
    expect(screen.getByTestId('map-canvas')).toBeInTheDocument();
    // ② 树含新节点：无 root_location_id 的根图作为树顶层节点渲染（可点击选中）
    expect(screen.getByTestId('world-map-badge-m9')).toBeInTheDocument();
  });

  it('#388 简图 resize：选中形状 → 拖右下角手柄 → w/h 变大 + PATCH extra.shapes 更新 w/h', async () => {
    mockMapWorkbench(worldTree, [mapM2]);
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user, 'w1a');
    await waitFor(() => expect(screen.getAllByTestId(/^map-shape-s_/)).toHaveLength(1));
    // 选中形状 → resize 手柄出现（四角 nw/ne/sw/se；本用例拖右下 se 角）
    await user.click(screen.getByTestId('map-shape-s_1'));
    const handle = await screen.findByTestId('map-shape-resize-s_1-se');
    // 拖角：mock canvas rect（width=200/height=100）→ mousedown(150,100) → window mousemove(200,120) → mouseup
    // GREEN 计算式：dw = (clientX - startClientX) / rect.width * 100；dh 同理；新 w/h = orig + dw/dh（clamp 0-100）
    const canvas = screen.getByTestId('map-canvas');
    canvas.getBoundingClientRect = () =>
      ({
        left: 100, top: 50, width: 200, height: 100, right: 300, bottom: 150, x: 100, y: 50,
        toJSON: () => ({}),
      }) as DOMRect;
    fireEvent.mouseDown(handle, { clientX: 150, clientY: 100 });
    fireEvent.mouseMove(window, { clientX: 200, clientY: 120 });
    fireEvent.mouseUp(window);
    // PATCH extra.shapes 里 s_1 的 w/h 变大（原 24/16 → 拖大后 > 24 / > 16）
    await waitFor(() => {
      const shapePatch = apiFetchMock.mock.calls.find(
        (c) =>
          c[0] === '/api/v1/maps/m2' &&
          c[1]?.method === 'PATCH' &&
          (c[1]!.body as { extra?: { shapes?: unknown[] } }).extra?.shapes !== undefined,
      );
      expect(shapePatch).toBeTruthy();
      const shapes = (
        shapePatch![1]!.body as { extra: { shapes: Array<{ id: string; w?: number; h?: number }> } }
      ).extra.shapes;
      const s = shapes.find((x) => x.id === 's_1');
      expect(s?.w).toBeGreaterThan(24);
      expect(s?.h).toBeGreaterThan(16);
    });
  });

  it('#388 简图改名：双击形状 → 内联输入 → Enter → PATCH extra.shapes 更新 label + 画布回显', async () => {
    mockMapWorkbench(worldTree, [mapM2]);
    renderLibrary();
    const user = userEvent.setup();
    await openMapWorkbench(user, 'w1a');
    await waitFor(() => expect(screen.getAllByTestId(/^map-shape-s_/)).toHaveLength(1));
    // 双击形状 → label 变内联 input（testid map-shape-label-input-s_1，初始值 = 当前 label '新区域'）
    await user.dblClick(screen.getByTestId('map-shape-s_1'));
    const input = await screen.findByTestId('map-shape-label-input-s_1');
    // 输入新名 → Enter 提交（blur 亦可提交）；input 内交互须 stopPropagation 防触发形状拖拽
    await user.clear(input);
    await user.type(input, '主城');
    await user.keyboard('{Enter}');
    // 画布回显新名 + PATCH extra.shapes 里 s_1 label = '主城'
    await waitFor(() => expect(screen.getByText('主城')).toBeInTheDocument());
    await waitFor(() => {
      const shapePatch = apiFetchMock.mock.calls.find(
        (c) =>
          c[0] === '/api/v1/maps/m2' &&
          c[1]?.method === 'PATCH' &&
          (c[1]!.body as { extra?: { shapes?: unknown[] } }).extra?.shapes !== undefined,
      );
      expect(shapePatch).toBeTruthy();
      const shapes = (
        shapePatch![1]!.body as { extra: { shapes: Array<{ id: string; label?: string }> } }
      ).extra.shapes;
      const s = shapes.find((x) => x.id === 's_1');
      expect(s?.label).toBe('主城');
    });
  });

  it('#389 分类可新建：点新建分类 → 输入 name → POST /world-categories → chips 出现', async () => {
    // 状态化分类 mock：POST 追加 + GET 读取（刷新后 chips 出现）
    const categories: Array<{ id: string; name: string; count: number }> = [];
    const baseImpl = apiFetchMock.getMockImplementation();
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects/p1/world-categories' && init?.method === 'POST') {
        const cat = { id: `wc${categories.length + 1}`, name: (init.body as { name: string }).name, count: 0 };
        categories.push(cat);
        return { ...cat, project_id: 'p1' };
      }
      if (path === '/api/v1/projects/p1/world-categories') {
        return { items: categories.map((c) => ({ ...c })), total: categories.length };
      }
      return baseImpl!(path, init);
    });
    mockMapWorkbench(worldTree, []);
    renderLibrary();
    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    // 初始无「势力」分类 chip
    expect(screen.queryByTestId('world-cat-filter-势力')).not.toBeInTheDocument();
    // 新建分类按钮 → 对话框 → 输入 → 保存
    await user.click(screen.getByTestId('world-cat-add'));
    const nameInput = await screen.findByTestId('world-cat-name');
    await user.type(nameInput, '势力');
    await user.click(screen.getByTestId('world-cat-save'));
    // POST 落库（body {name}）+ chips 出现新分类
    await waitFor(() => {
      const postCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/world-categories' && c[1]?.method === 'POST',
      );
      expect(postCall).toBeTruthy();
      expect((postCall![1]!.body as { name: string }).name).toBe('势力');
    });
    await screen.findByTestId('world-cat-filter-势力');
  });
});
