/**
 * #761 世界观地图「创建后从其他页面返回即消失 + 同名误报已存在」RED 契约（页面级，复现用户 v0.12.1rc2 症状链）。
 *
 * ── 精确根因（源码实勘 2026-08-29）──
 * ① MapWorkbench.tsx L135 `useState<WorldMapDTO[]>(maps)`：localMaps 只是 props maps 的拷贝；
 *    L160-162 `useEffect(() => { setLocalMaps(maps); }, [maps])` 只做 props → local 单向同步。
 * ② MapWorkbench.tsx L344-353 handleCreateMap：创建成功后只 `setLocalMaps((prev) => [...prev, created])`（L345），
 *    **没有任何机制回传父级 library.tsx 的 maps 状态**（MapWorkbenchProps 无 onMapsChanged 类回调）。
 * ③ library.tsx L220-236 maps 拉取 useEffect 依赖仅 `[currentProjectId]`：切 tab / 退出重进 workbench 均不重拉，
 *    创建图也不触发 reloadKey —— library.maps 永远是陈旧的（不含新建图）。
 * ④ MapWorkbench 被卸载（退出工作台 / 切走世界观 tab）再挂载时，localMaps 重新从 props maps（陈旧）初始化 →
 *    新建的图从树消失（症状 1）。
 * ⑤ DB 中图已存在（POST 已落库）→ 用户再次创建同名 → 后端 map_service.py L160-161 get_by_name 命中 →
 *    MapNameConflictError「已存在」（症状 2）。同名判据本身合理（项目内唯一），误报只是 ④ 的下游症状。
 *
 * ── GREEN 契约（Codex 实现方向，二选一或组合）──
 * A. MapWorkbench 新增 `onMapsChanged?: (maps: WorldMapDTO[]) => void` 回调，handleCreateMap 成功后
 *    `onMapsChanged([...localMaps, created])`（或局部追加）；library.tsx 接线 `setMaps`。
 * B. library.tsx maps useEffect 增加重拉触发（如 reloadKey/activeCat 依赖）——创建图后父级能拿到新列表。
 * 二者都满足后：MapWorkbench 重挂载 → localMaps 从含新图的 maps 初始化 → 树显示该图 → 用户不再重复创建同名。
 * 同名防御（第二层）：handleCreateMap 开头本地检查 `localMaps.some(m => m.name === name)` → 命中直接 err toast，
 *   不发 POST（本文件测试 3 锁定）。
 *
 * ── RED 关键 ──
 * 测试 mock：POST /projects/p1/maps 恒返回创建成功的新图（id=m100，root_location_id=null → 走 orphanMaps 渲染
 * map-tree-node-m100）；GET /projects/p1/maps 恒返回空列表（模拟「后端有、前端 library.maps 未同步」的起点）。
 * 当前实现：创建图后 localMaps 有 m100（workbench 内可见），退出/切 tab 重挂载后 m100 消失 → 断言 FAIL（RED）。
 *
 * 本文件只写测试，禁改 src/ 生产代码（由 Codex 实现修复）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
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

/** world-settings 条目：category 空（不触发 abstract 过滤），让世界观树有根节点 */
const worldItems = [{ id: 'w1', name: '九州', category: '', content: '天下地理', parent_id: null }];

/** POST /projects/p1/maps 返回的创建成功新图（root_location_id=null → 独立根图，orphanMaps 渲染 map-tree-node-m100） */
const createdMapM100 = {
  id: 'm100',
  project_id: 'p1',
  name: '新舆图',
  root_location_id: null,
  parent_map_id: null,
  bg_source: 'shape',
  created_at: '2026-08-29T10:00:00Z',
  updated_at: '2026-08-29T10:00:00Z',
};
/** 第二次同名 POST 的响应（模拟后端放行/不同 id；真实后端同名会 422，此处只需避免 React key 冲突噪音） */
const createdMapM101 = { ...createdMapM100, id: 'm101' };

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

/** 收集 POST /api/v1/projects/p1/maps 调用（创建地图端点） */
function postMapCalls() {
  return apiFetchMock.mock.calls.filter(
    (c) => c[0] === '/api/v1/projects/p1/maps' && c[1]?.method === 'POST',
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  let postCount = 0;
  // 默认 URL 分发：projects 双项目；world-settings 有条目（树可见）；GET maps 恒空列表（模拟父级未同步）；
  // POST maps 恒返回创建成功的新图（首次 m100，后续 m101 防 key 冲突噪音）
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/world-settings') {
      return { items: worldItems, total: 1, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/projects/p1/maps') {
      if (init?.method === 'POST') {
        postCount += 1;
        return postCount === 1 ? createdMapM100 : createdMapM101;
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    if (/^\/api\/v1\/maps\/[^/]+\/pins$/.test(path)) return { items: [], total: 0, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

/** 进入世界观 tab 并打开地图工作台（工具栏「地图视图」入口 map-view-entry） */
async function openWorkbench(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('tab', { name: '世界观' }));
  await screen.findByTestId('library-list');
  await user.click(screen.getByTestId('map-view-entry'));
  await screen.findByTestId('map-workbench');
}

/** 工作台内创建根图「新舆图」（map-create-root → 输入名 → 保存 → POST 返回 m100） */
async function createRootMap(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId('map-create-root'));
  const nameInput = await screen.findByTestId('map-create-name');
  await user.type(nameInput, '新舆图');
  await user.click(screen.getByTestId('map-create-save'));
  // 创建成功后：localMaps 追加 m100 → 树显示 map-tree-node-m100（workbench 内当前实现可见）
  await screen.findByTestId('map-tree-node-m100');
}

describe('#761 世界观地图 — 创建后退出/切 tab 返回，树必须仍显示该图（localMaps 不回传父级 maps 根因）', () => {
  it('RED：创建根图 → 退出工作台（map-bc-world）→ 重新进入 → 树仍显示 map-tree-node-m100', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();
    await openWorkbench(user);
    await createRootMap(user);

    // 退出工作台（面包屑「世界观」回跳）→ map-workbench 卸载
    await user.click(screen.getByTestId('map-bc-world'));
    await waitFor(() => {
      expect(screen.queryByTestId('map-workbench')).not.toBeInTheDocument();
    });

    // 重新进入工作台 → MapWorkbench 重新挂载
    await user.click(screen.getByTestId('map-view-entry'));
    await screen.findByTestId('map-workbench');

    // RED：当前实现 MapWorkbench L135 localMaps 从 props maps（library.maps 陈旧空列表）重新初始化 →
    // m100 从树消失 → queryByTestId 为 null → FAIL。
    expect(screen.getByTestId('map-tree-node-m100')).toBeInTheDocument();
  });

  it('RED：创建根图 → 切到「角色」tab → 切回「世界观」tab → 树仍显示 map-tree-node-m100（用户「从其他页面返回」场景）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();
    await openWorkbench(user);
    await createRootMap(user);

    // 切到其他页面（角色 tab，空态无 library-list）→ MapWorkbench 卸载；再切回世界观 → MapWorkbench 重新挂载
    await user.click(screen.getByRole('tab', { name: '角色' }));
    await screen.findByTestId('library-tab-empty');
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('map-workbench');

    // RED：同上，localMaps 从陈旧 maps 初始化 → m100 消失 → FAIL
    expect(screen.getByTestId('map-tree-node-m100')).toBeInTheDocument();
  });

  it('RED：同名二次创建被本地拦截——第二次保存不重复 POST /maps（不误报后端「已存在」）', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();
    await openWorkbench(user);
    await createRootMap(user);
    const postsAfterFirst = postMapCalls().length;
    expect(postsAfterFirst).toBe(1); // 第一次创建确实发出过一次 POST

    // 再次以同名「新舆图」创建：正确契约 = 前端本地已知同名（localMaps 已有 m100）→ 不发 POST、直接 err toast
    await user.click(screen.getByTestId('map-create-root'));
    const nameInput = await screen.findByTestId('map-create-name');
    await user.type(nameInput, '新舆图');
    await user.click(screen.getByTestId('map-create-save'));
    await waitFor(() => {
      // RED：当前实现 handleCreateMap 无本地同名检查 → 第二次 POST 照样发出 → 长度变 2 → FAIL。
      expect(postMapCalls().length).toBe(1);
    });
  });
});
