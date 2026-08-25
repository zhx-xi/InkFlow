/**
 * ⚠️ 契约文件（T2 角色分组 #651 RED 阶段，specs/f9-character-service/gui-role-enhance-red-contract.md §T2 分组区契约）
 *
 * GREEN 改造 src/pages/library.tsx（角色 tab 加「点名字打开详情面板」入口 + CharacterDetailPanel
 * 组件承载分组区），必须匹配以下契约：
 *
 * 【角色详情面板入口】
 * - 角色行 LibraryItemList：characters 分类的「名字」可点击（或新增"详情"图标按钮），点击 → 打开详情面板
 * - 面板容器 data-testid="character-detail-panel"，标题 = 角色名
 * - 关闭按钮 data-testid="character-detail-close"
 *
 * 【分组端点（后端已实现，源码核实）】
 * - GET  /api/v1/projects/{pid}/character-groups → {items:[{id,name,description,sort_order,member_count}], total}
 * - POST /api/v1/projects/{pid}/character-groups (201) body={name, description, sort_order}
 * - PATCH /api/v1/character-groups/{gid} body={name?, description?, sort_order?}
 * - DELETE /api/v1/character-groups/{gid} (204) 真删
 * - 角色归属分组：PATCH /api/v1/characters/{cid} body={group_id}（角色表有 group_id 字段）
 *
 * 【T2 分组区契约（面板内）】
 * - 分组选择下拉 character-group-select（选项=GET /projects/{pid}/character-groups）
 *   - 选中 → PATCH /characters/{cid} body {group_id} → 面板显示当前分组名
 *   - 含「未分组」清空项（group_id=null）
 * - character-group-manage：「管理分组…」按钮 → 打开分组管理面板
 *   - character-group-manage-panel：面板容器
 *   - character-group-add：新建分组按钮 → 表单 character-group-form（name/description）→ POST
 *   - 分组行：character-group-row-<gid>（name + member_count + 编辑/删除按钮）
 *     - 行内编辑 character-group-edit-<gid> → PATCH
 *     - 行内删除 character-group-delete-<gid> → ConfirmDialog character-group-confirm-dialog → DELETE
 * - role_rank 与分组正交：等级下拉（library-create-rank）存在且独立，分组不合并进等级控件
 *
 * 【断言点（契据 §T2）】
 * 1. 打开详情面板 → GET /projects/{pid}/character-groups → 分组下拉渲染（含当前 group 名）
 * 2. 选分组 → PATCH /characters/{cid} body {group_id} → 面板更新
 * 3. 打开管理面板 → GET 列表渲染（name/member_count）
 * 4. 新建分组 → POST body {name, description} → 列表出现
 * 5. 编辑分组 → PATCH → 更新
 * 6. 删除分组 → 确认框 → DELETE → 行消失
 * 7. role_rank 与分组正交（守护用例）
 *
 * RED 预期：角色 tab 当前无「角色详情面板」（character-detail-panel 等 testid 全部不存在）→
 * 用例 1-6 element-missing（类 3 契约缺口）FAIL；用例 7 为回归守护（等级下拉已实现 + 分组
 * 选择不存在 → 断言天然成立），RED 期 PASS 刻意，防未来把分组合并进等级控件。
 *
 * ⚠️ 本文件禁 import 任何 GREEN 才建模块（CharacterDetailPanel 等）——全部经 library.tsx 渲染 +
 * apiFetch mock 断言（同 library-kg.test.tsx 模式）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LibraryPage } from './library';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

/** §T2 种子：角色列表（角色表含 group_id 字段；extra.role_rank/groups 沿用 F43 P1 契约） */
const CHARACTER_SEED: Array<Record<string, unknown>> = [
  {
    id: 'c1', name: '林晚', personality: '孤傲', background: '剑客', goals: '决战',
    group_id: 'g1', extra: { role_rank: 'major', groups: ['主角团'] },
  },
  {
    id: 'c2', name: '沈砚', personality: '温润', background: '医者', goals: '悬壶',
    group_id: null, extra: { role_rank: 'minor', groups: [] },
  },
];

/** §T2 种子：分组列表响应行（GET /projects/p1/character-groups） */
const GROUP_SEED: Array<Record<string, unknown>> = [
  { id: 'g1', name: '主角团', description: '主线核心', sort_order: 1, member_count: 1 },
  { id: 'g2', name: '青云宗', description: '宗门势力', sort_order: 2, member_count: 2 },
];

/** 状态化数组（beforeEach 重置；POST unshift / PATCH 合并 / DELETE splice，供「变化后」断言） */
let groups: Array<Record<string, unknown>> = [];
let characters: Array<Record<string, unknown>> = [];

function renderLibrary(initialPath = '/library') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LibraryPage />
    </MemoryRouter>,
  );
}

/** 端点命中断言（宽容单参/双参：契约 = 拉取了该端点，不约束 init 形状） */
function fetchCalled(path: string): boolean {
  return apiFetchMock.mock.calls.some((c) => c[0] === path);
}

/** 下拉/combobox 选择（原生 select 与 Radix 双分支兼容；选项可访问名 = optionText） */
async function selectCombo(
  el: HTMLElement,
  optionText: string,
  user: ReturnType<typeof userEvent.setup>,
) {
  if (el.tagName === 'SELECT') {
    const opt = Array.from(el.querySelectorAll('option')).find(
      (o) => o.textContent?.trim() === optionText,
    );
    await user.selectOptions(el, opt ?? optionText);
  } else {
    await user.click(el);
    await user.click(await screen.findByRole('option', { name: optionText }));
  }
}

/** 打开角色详情面板（角色行名字点击 → 面板；GREEN 后名字可点击） */
async function openDetailPanel(user: ReturnType<typeof userEvent.setup>, charName = '林晚') {
  await screen.findByTestId('library-list');
  await user.click(screen.getByText(charName));
  return screen.findByTestId('character-detail-panel');
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  groups = GROUP_SEED.map((g) => ({ ...g }));
  characters = CHARACTER_SEED.map((c) => ({ ...c }));
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    const method = init?.method ?? 'GET';
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/maps') return { items: [] };
    if (path === '/api/v1/projects/p1/characters') {
      return { items: characters.map((c) => ({ ...c })), total: characters.length, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/projects/p1/character-groups') {
      if (method === 'POST') {
        // §T2：POST body={name, description, sort_order} → 新分组（状态化 unshift）
        const created = {
          id: `g${groups.length + 1}`,
          sort_order: groups.length + 1,
          member_count: 0,
          ...((init?.body ?? {}) as Record<string, unknown>),
        };
        groups.unshift(created);
        return created;
      }
      return { items: groups.map((g) => ({ ...g })), total: groups.length, offset: 0, limit: 50 };
    }
    if (path.startsWith('/api/v1/character-groups/')) {
      const gid = path.slice('/api/v1/character-groups/'.length);
      const idx = groups.findIndex((g) => g.id === gid);
      if (method === 'PATCH' && idx >= 0) {
        groups[idx] = { ...groups[idx], ...((init?.body ?? {}) as Record<string, unknown>) };
        return groups[idx];
      }
      if (method === 'DELETE' && idx >= 0) {
        groups.splice(idx, 1);
        return undefined;
      }
    }
    if (path.startsWith('/api/v1/characters/')) {
      const cid = path.slice('/api/v1/characters/'.length);
      const idx = characters.findIndex((c) => c.id === cid);
      if (method === 'PATCH' && idx >= 0) {
        characters[idx] = { ...characters[idx], ...((init?.body ?? {}) as Record<string, unknown>) };
        return characters[idx];
      }
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('T2 角色分组 #651（角色详情面板分组区契约）', () => {
  it('T2-1 打开详情面板 → GET /projects/p1/character-groups → 分组下拉渲染（含当前 group 名）', async () => {
    // 预期 FAIL：角色 tab 无「角色详情面板」——character-detail-panel element-missing（类 3 契约缺口）
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openDetailPanel(user);
    // 面板标题 = 角色名
    expect(panel).toHaveTextContent('林晚');
    // 分组下拉渲染 + 显示当前分组名（c1.group_id='g1' → 主角团）
    const groupSelect = within(panel).getByTestId('character-group-select');
    expect(groupSelect).toHaveTextContent('主角团');
    // 下拉选项 = GET /projects/p1/character-groups（含「未分组」清空项）
    await user.click(groupSelect);
    expect(await screen.findByRole('option', { name: '青云宗' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '未分组' })).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/character-groups')).toBe(true);
    });
  });

  it('T2-2 选分组 → PATCH /characters/{cid} body {group_id} → 面板显示新分组名', async () => {
    // 预期 FAIL：无详情面板/分组下拉——character-detail-panel element-missing（类 3 契约缺口）
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openDetailPanel(user);
    // 选「青云宗」（g2）→ PATCH /api/v1/characters/c1 body {group_id: 'g2'}
    await selectCombo(within(panel).getByTestId('character-group-select'), '青云宗', user);

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/characters/c1' && c[1]?.method === 'PATCH',
      );
      expect(call).toBeTruthy();
    });
    const patchCall = apiFetchMock.mock.calls.find(
      (c) => c[0] === '/api/v1/characters/c1' && c[1]?.method === 'PATCH',
    )!;
    // §T2：body = {group_id}（角色表 group_id 字段赋值）
    expect(patchCall[1]?.body).toEqual(expect.objectContaining({ group_id: 'g2' }));
    // 面板显示当前分组名更新（状态化 mock PATCH 合并回写 → 重拉/本地更新均显示新值）
    await waitFor(() => {
      expect(within(panel).getByTestId('character-group-select')).toHaveTextContent('青云宗');
    });
  });

  it('T2-3 打开分组管理面板 → GET 列表渲染（name/member_count 行）', async () => {
    // 预期 FAIL：无详情面板/管理入口——character-detail-panel element-missing（类 3 契约缺口）
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openDetailPanel(user);
    await user.click(within(panel).getByTestId('character-group-manage'));
    const managePanel = await screen.findByTestId('character-group-manage-panel');
    // 分组行：name + member_count
    const rowG1 = within(managePanel).getByTestId('character-group-row-g1');
    expect(rowG1).toHaveTextContent('主角团');
    expect(rowG1).toHaveTextContent('1');
    const rowG2 = within(managePanel).getByTestId('character-group-row-g2');
    expect(rowG2).toHaveTextContent('青云宗');
    expect(rowG2).toHaveTextContent('2');
    await waitFor(() => {
      expect(fetchCalled('/api/v1/projects/p1/character-groups')).toBe(true);
    });
  });

  it('T2-4 新建分组：character-group-add → 表单 → POST body {name, description} → 列表出现新行', async () => {
    // 预期 FAIL：无详情面板/管理入口——character-detail-panel element-missing（类 3 契约缺口）
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openDetailPanel(user);
    await user.click(within(panel).getByTestId('character-group-manage'));
    const managePanel = await screen.findByTestId('character-group-manage-panel');
    await user.click(within(managePanel).getByTestId('character-group-add'));

    const form = await screen.findByTestId('character-group-form');
    fireEvent.change(within(form).getByTestId('character-group-form-name'), {
      target: { value: '天机阁' },
    });
    fireEvent.change(within(form).getByTestId('character-group-form-desc'), {
      target: { value: '情报组织' },
    });
    await user.click(within(form).getByTestId('character-group-form-save'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/character-groups' && c[1]?.method === 'POST',
      );
      expect(call).toBeTruthy();
    });
    const postCall = apiFetchMock.mock.calls.find(
      (c) => c[0] === '/api/v1/projects/p1/character-groups' && c[1]?.method === 'POST',
    )!;
    // §T2：POST body = {name, description}（sort_order 服务端/实现期定，不钉）
    expect(postCall[1]?.body).toEqual(
      expect.objectContaining({ name: '天机阁', description: '情报组织' }),
    );
    // 列表出现新行（状态化 mock POST unshift → 重拉/本地追加均可见）
    await waitFor(() => {
      const newRow = within(managePanel).getByTestId('character-group-row-g3');
      expect(newRow).toHaveTextContent('天机阁');
    });
  });

  it('T2-5 编辑分组：character-group-edit-<gid> → 表单回填 → PATCH → 行更新', async () => {
    // 预期 FAIL：无详情面板/管理入口——character-detail-panel element-missing（类 3 契约缺口）
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openDetailPanel(user);
    await user.click(within(panel).getByTestId('character-group-manage'));
    const managePanel = await screen.findByTestId('character-group-manage-panel');
    await user.click(within(managePanel).getByTestId('character-group-edit-g1'));

    // 表单回填现值（编辑契约：名称输入框 = 主角团）
    const form = await screen.findByTestId('character-group-form');
    const nameInput = within(form).getByTestId('character-group-form-name') as HTMLInputElement;
    expect(nameInput.value).toBe('主角团');
    fireEvent.change(nameInput, { target: { value: '主角团·核心' } });
    await user.click(within(form).getByTestId('character-group-form-save'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/character-groups/g1' && c[1]?.method === 'PATCH',
      );
      expect(call).toBeTruthy();
    });
    const patchCall = apiFetchMock.mock.calls.find(
      (c) => c[0] === '/api/v1/character-groups/g1' && c[1]?.method === 'PATCH',
    )!;
    // §T2：PATCH body 全可选（{name?, description?, sort_order?}）
    expect(patchCall[1]?.body).toEqual(expect.objectContaining({ name: '主角团·核心' }));
    // 行更新（状态化 mock PATCH 合并回写 → 重拉/本地更新均显示新值）
    await waitFor(() => {
      expect(within(managePanel).getByTestId('character-group-row-g1')).toHaveTextContent('主角团·核心');
    });
  });

  it('T2-6 删除分组：character-group-delete-<gid> → 确认框 → DELETE → 行消失', async () => {
    // 预期 FAIL：无详情面板/管理入口——character-detail-panel element-missing（类 3 契约缺口）
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openDetailPanel(user);
    await user.click(within(panel).getByTestId('character-group-manage'));
    const managePanel = await screen.findByTestId('character-group-manage-panel');
    await user.click(within(managePanel).getByTestId('character-group-delete-g1'));

    // 二次确认（§T2：ConfirmDialog character-group-confirm-dialog + confirm-ok）
    const confirm = await screen.findByTestId('character-group-confirm-dialog');
    await user.click(within(confirm).getByTestId('character-group-confirm-ok'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/character-groups/g1' && c[1]?.method === 'DELETE',
      );
      expect(call).toBeTruthy();
    });
    // 行消失（状态化 mock DELETE splice → 重拉/本地移除均不可见）
    await waitFor(() => {
      expect(within(managePanel).queryByTestId('character-group-row-g1')).not.toBeInTheDocument();
    });
  });

  it('T2-7 守护：role_rank 与分组正交——等级下拉 library-create-rank 存在且独立，分组不合并进等级控件', async () => {
    // 预期 PASS（守护用例，RED 期刻意）：等级下拉已实现（F43 P1）+ 当前无分组选择 → 断言天然成立；
    // 防未来 GREEN 把分组合并进等级控件（契据 §T2 断言点 7）
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    // 打开创建对话框（角色列表非空 → library-create-btn 常态入口）
    await user.click(await screen.findByTestId('library-create-btn'));
    const dialog = await screen.findByTestId('library-create-dialog');
    // 等级下拉存在（F43 P1 已实现）
    expect(within(dialog).getByTestId('library-create-rank')).toBeInTheDocument();
    // 分组选择不合并进创建对话框（分组归属详情面板 character-group-select，正交）
    expect(within(dialog).queryByTestId('character-group-select')).not.toBeInTheDocument();
    // 等级下拉选项 = 五档等级显示名，不含分组名（分组不并入等级控件）
    await user.click(within(dialog).getByTestId('library-create-rank'));
    const optionLabels = (await screen.findAllByRole('option')).map((o) => o.textContent ?? '');
    expect(optionLabels).toContain('主角');
    expect(optionLabels).not.toContain('主角团');
    expect(optionLabels).not.toContain('青云宗');
  });
});
