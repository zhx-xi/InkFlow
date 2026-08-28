/**
 * #741 缺陷②（前端判别 bug）RED 契约：MapWorkbench 创建子图时父图不存在。
 *
 * ── 根因（bug-hunter curl 已实证，后端正常）──
 * MapWorkbench.tsx L364 `if ('project_id' in target)` 判别失效：
 * 后端 world-settings 响应 setting.model_dump(mode="json") 含 project_id 字段（world_settings.py L226），
 * library.tsx 原样透传 → worldItems 运行时对象**带 project_id** → 世界条目被误判为 WorldMapDTO →
 * parentMapId = target.id（条目 id）→ POST /maps 把条目 id 当 parent_map_id → 后端 422「父地图不存在」。
 * 同时物化根图路径（L380-411）成死代码 → 条目永远无 linkedMap → 不能拖动/点开不显示。
 *
 * ── GREEN 契约（Codex 实现）──
 * worldItems 条目（即使带 project_id 泄漏）且无挂载图时，点「创建子图」：
 *   ① 先物化根图：POST /api/v1/projects/{pid}/maps，FormData { name, bg_source:'shape',
 *      root_location_id:<条目 id> }，**无 parent_map_id**；
 *   ② 物化成功后以**物化图 id** 作为 parent_map_id 打开创建子图对话框；
 *   ③ 保存子图 POST body.parent_map_id = 物化图 id（非条目 id）。
 *
 * ── RED 关键 ──
 * mock 的世界条目对象**必须带 project_id**（`{id:'w1', name:'蜀山修仙宇宙', project_id:'p1', ...}`），
 * 否则当前 `'project_id' in target`=false 会走物化路径 → 测试假绿。
 * 当前实现（判别 bug）：点击后不物化、直接以条目 id 开对话框、保存 POST parent_map_id=条目 id → 断言 FAIL。
 *
 * 本文件只写测试，禁改 src/ 生产代码（由 Codex 实现修复）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MapWorkbench } from './MapWorkbench';
import { apiFetch } from '../api/client';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 世界条目——⚠️ 带 project_id 泄漏（真实后端 world-settings 透传形状），类别/内容空、无父 */
const leakedWorldItems = [
  { id: 'w1', name: '蜀山修仙宇宙', project_id: 'p1', category: '', content: '', parent_id: null },
];

/** 对照组：无 project_id 泄漏的干净条目（守护用例用，正常形状） */
const cleanWorldItems = [
  { id: 'w1', name: '蜀山修仙宇宙', category: '', content: '', parent_id: null },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useToastStore.setState({ toasts: [] });
});

function renderWorkbench(worldItems: Array<Record<string, unknown>>) {
  return render(
    <MapWorkbench
      projectId="p1"
      worldItems={worldItems as never}
      maps={[]} // 无任何地图 → 条目无挂载图，创建子图必须先物化根图
      activeMapId={null}
      onSelectMap={vi.fn()}
      onExitWorkbench={vi.fn()}
      onClearMap={vi.fn()}
      worldCategories={[]}
      activeWorldCat={null}
      onWorldCatChange={vi.fn()}
      collapsedIds={new Set()}
      onToggle={vi.fn()}
      onEdit={vi.fn()}
      onDelete={vi.fn()}
      onCopy={vi.fn()}
      copyTargetOptions={[]}
      onCopyAll={vi.fn()}
    />,
  );
}

/** 收集 POST /api/v1/projects/p1/maps 调用（创建根图/子图都走此端点） */
function postMapCalls() {
  return apiFetchMock.mock.calls.filter(
    (c) => c[0] === '/api/v1/projects/p1/maps' && c[1]?.method === 'POST',
  );
}

/** 默认 mock：任何 POST /maps 都返回创建成功的物化图（id=m100，root_location_id=w1） */
function mockPostReturnsMaterializedMap() {
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    if (path === '/api/v1/projects/p1/maps' && init?.method === 'POST') {
      return {
        id: 'm100',
        project_id: 'p1',
        name: '蜀山修仙宇宙',
        root_location_id: 'w1',
        parent_map_id: null,
        bg_source: 'shape',
      };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
}

describe('MapWorkbench — #741 缺陷② 创建子图时父图不存在（project_id 泄漏判别 bug）', () => {
  it('RED：带 project_id 泄漏的条目 + 无地图 → 点「创建子图」先物化根图（POST root_location_id=条目id、无 parent_map_id），保存子图 parent_map_id=物化图id', async () => {
    mockPostReturnsMaterializedMap();
    renderWorkbench(leakedWorldItems);
    const user = userEvent.setup();

    // 无挂载图条目渲染「创建子图」入口（#721：🗺 图标 + map-create-child-<条目id>）
    await user.click(screen.getByTestId('map-create-child-w1'));

    // ① RED：点击瞬间应物化根图——第一次 POST /maps body 含 root_location_id='w1' 且无 parent_map_id。
    //    当前实现：'project_id' in target=true → 直接以条目 id 开对话框，点击后无任何 POST → waitFor 超时 FAIL。
    await waitFor(() => {
      const calls = postMapCalls();
      expect(calls.length).toBeGreaterThanOrEqual(1);
      const body = calls[0]![1]!.body as FormData;
      expect(String(body.get('root_location_id'))).toBe('w1'); // 物化根图挂条目
      expect(body.get('parent_map_id')).toBeNull(); // 根图无父
    });

    // ② 物化成功后才打开创建子图对话框 → 输入子图名 → 保存
    const nameInput = await screen.findByTestId('map-create-name');
    await user.type(nameInput, '蜀山分图');
    await user.click(screen.getByTestId('map-create-save'));

    // ③ RED：保存子图的 POST body.parent_map_id=物化图 id（m100），root_location_id 为空。
    //    当前实现：parent_map_id='w1'（条目 id）→ 断言 FAIL。
    await waitFor(() => {
      const calls = postMapCalls();
      expect(calls.length).toBeGreaterThanOrEqual(2);
      const saveBody = calls[calls.length - 1]![1]!.body as FormData;
      expect(String(saveBody.get('parent_map_id'))).toBe('m100');
      expect(saveBody.get('root_location_id')).toBeNull();
    });
  });

  it('RED：带 project_id 泄漏的条目 → 创建子图对话框打开前，物化 POST 必须已发生（判别 bug 直接锚点）', async () => {
    let materializePosted = false;
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects/p1/maps' && init?.method === 'POST') {
        materializePosted = true;
        return {
          id: 'm100',
          project_id: 'p1',
          name: '蜀山修仙宇宙',
          root_location_id: 'w1',
          parent_map_id: null,
          bg_source: 'shape',
        };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    renderWorkbench(leakedWorldItems);
    const user = userEvent.setup();

    await user.click(screen.getByTestId('map-create-child-w1'));
    // 对话框打开（物化成功是对话框打开的前置条件——修复后先 await 物化 POST 再 setCreateDialog）
    await screen.findByTestId('map-create-name');

    // RED：当前实现 'project_id' in target=true → 对话框直接以条目 id 打开、无物化 POST → false → FAIL
    expect(materializePosted).toBe(true);
  });

  it('守卫（PASS 合法）：无 project_id 泄漏的干净条目 + 无地图 → 点「创建子图」仍走物化路径（防修复过度回归正常形状）', async () => {
    mockPostReturnsMaterializedMap();
    renderWorkbench(cleanWorldItems);
    const user = userEvent.setup();

    await user.click(screen.getByTestId('map-create-child-w1'));

    // 干净条目 'project_id' in target=false → 当前实现已走物化路径 → 本用例 PASS（守卫）
    await waitFor(() => {
      const calls = postMapCalls();
      expect(calls.length).toBeGreaterThanOrEqual(1);
      const body = calls[0]![1]!.body as FormData;
      expect(String(body.get('root_location_id'))).toBe('w1');
      expect(body.get('parent_map_id')).toBeNull();
    });
    // 物化后对话框打开，且父图为物化图 id
    await screen.findByTestId('map-create-name');
    await user.type(screen.getByTestId('map-create-name'), '蜀山分图');
    await user.click(screen.getByTestId('map-create-save'));
    await waitFor(() => {
      const calls = postMapCalls();
      expect(calls.length).toBeGreaterThanOrEqual(2);
      const saveBody = calls[calls.length - 1]![1]!.body as FormData;
      expect(String(saveBody.get('parent_map_id'))).toBe('m100');
    });
  });
});
