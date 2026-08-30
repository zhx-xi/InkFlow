/**
 * ⚠️ 契约文件（#650 角色关系 GUI RED 阶段，specs/f9-character/gui-role-enhance-red-contract.md T1）
 *
 * GREEN 改造 src/pages/library.tsx：角色 tab 行名字加可点击入口 → 打开 CharacterDetailPanel
 * （新建「角色详情面板」组件，承载关系区 + 分组区）；本文件只锁 T1 关系区契约。
 *
 * 【角色详情面板入口（GREEN 新增，library.tsx）】
 * - 角色行 LibraryItemList：characters 分类的「名字」可点击（或新增「详情」图标按钮）→ 打开 CharacterDetailPanel
 * - 面板容器 data-testid="character-detail-panel"，标题 = 角色名；关闭按钮 character-detail-close
 *
 * 【T1 关系区契约（面板内，端点已后端实现）】
 * - 端点映射：
 *   GET    /api/v1/characters/{cid}/relations → {items:[{id, from_character_id, to_character_id,
 *          from_name, to_name, relation_type, description}], total}
 *   POST   /api/v1/characters/{cid}/relations (201) body={to_character_id, relation_type, description}
 *          （from=路径角色，不随 body 提交）
 *   PATCH  /api/v1/characters/{cid}/relations/{rid} body={relation_type?, description?}（from/to 不变）
 *   DELETE /api/v1/characters/{cid}/relations/{rid} (204) 真删
 * - character-rel-add：「＋ 添加关系」按钮
 * - character-rel-form：添加/编辑关系表单容器
 *   - character-rel-form-to：对方角色下拉（选项 = 项目内其他角色）
 *   - character-rel-form-type：关系类型输入
 *   - character-rel-form-desc：描述输入
 *   - character-rel-form-save：保存按钮
 * - character-rel-list：关系列表容器；空态 character-rel-empty 文案「暂无关系」
 * - 关系行 character-rel-<rid>（含 to_name / relation_type / description）
 *   - 行内编辑 character-rel-edit-<rid> → 表单回填 → 保存 → PATCH
 *   - 行内删除 character-rel-delete-<rid> → ConfirmDialog character-rel-confirm-dialog +
 *     character-rel-confirm-ok → DELETE → 行消失
 *
 * 【mock 模式（照抄 library-kg.test.tsx）】
 * - vi.mock('../api/client', importOriginal) 保留 apiFetch 其余导出（ensureApiReady 等），apiFetch 换 vi.fn()
 * - useProjectStore.setState 播种 projectP1 + currentProjectId='p1'；useThemeStore.setState({lang:'zh'})
 * - 状态化 mockImplementation：GET /api/v1/projects 返回项目；GET /api/v1/projects/p1/characters 返回角色列表；
 *   GET /api/v1/characters/{cid}/relations 返回状态化 relations 数组（POST unshift / PATCH 合并 / DELETE splice，
 *   供「刷新后变化」断言）
 * - fetchCalled(path) = apiFetchMock.mock.calls.some(c => c[0]===path)
 *
 * RED 预期：角色 tab 当前无详情面板（LibraryItemList 名字 span 不可点击）→ 各用例在
 * findByTestId('character-detail-panel') 处 element-missing（类 3 契约缺口），全部 6 it FAIL。
 * 本文件禁 import 任何 GREEN 才建模块（CharacterDetailPanel / 关系组件等）——全部经 library.tsx 渲染 +
 * apiFetch mock 断言（同 library-kg.test.tsx / library-p1.test.tsx 模式）。
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

/** 项目内角色列表种子（c1 = 打开详情面板的角色；c2/c3 = 「对方角色」下拉选项） */
const CHARACTER_SEED = [
  { id: 'c1', name: '林晚' },
  { id: 'c2', name: '沈砚' },
  { id: 'c3', name: '叶孤城' },
];

/** T1 契约种子：GET /characters/{cid}/relations 行（from/to 名 + 类型 + 描述） */
const RELATION_SEED = [
  {
    id: 'r1', from_character_id: 'c1', to_character_id: 'c2',
    from_name: '林晚', to_name: '沈砚', relation_type: '宿敌', description: '宿命对决',
  },
  {
    id: 'r2', from_character_id: 'c1', to_character_id: 'c3',
    from_name: '林晚', to_name: '叶孤城', relation_type: '师徒', description: '剑道传承',
  },
];

/** 面板角色名映射（POST 创建时 from=路径角色，GREEN 后端契约） */
const CHAR_NAMES: Record<string, string> = { c1: '林晚' };

/** 状态化关系数组（beforeEach 重置；POST unshift / PATCH 合并 / DELETE splice，供「刷新后变化」断言） */
let relations: Array<Record<string, unknown>> = [];

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

/**
 * 角色 tab 就绪 → 点角色行名字（GREEN 契约：characters 分类名字可点击）→ 等待详情面板出现。
 * RED 期：名字 span 不可点击 → findByTestId('character-detail-panel') 超时 element-missing（锚定点）。
 */
async function openCharacterDetail(user: ReturnType<typeof userEvent.setup>, name = '林晚') {
  await screen.findByTestId('library-list');
  await user.click(screen.getByText(name));
  return screen.findByTestId('character-detail-panel');
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  relations = RELATION_SEED.map((r) => ({ ...r }));
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    const method = init?.method ?? 'GET';
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/maps') return { items: [] };
    if (path === '/api/v1/projects/p1/characters') {
      return { items: CHARACTER_SEED.map((c) => ({ ...c })), total: CHARACTER_SEED.length, offset: 0, limit: 50 };
    }
    // T1：角色关系端点（状态化：POST unshift / PATCH 合并 / DELETE splice / GET 回显）
    const relMatch = path.match(/^\/api\/v1\/characters\/([^/]+)\/relations(?:\/([^/]+))?$/);
    if (relMatch) {
      const cid = relMatch[1];
      const rid = relMatch[2];
      if (method === 'POST' && !rid) {
        const created = {
          id: 'r9', from_character_id: cid, from_name: CHAR_NAMES[cid] ?? '',
          created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-02T10:00:00Z',
          ...((init?.body ?? {}) as Record<string, unknown>),
        };
        relations.unshift(created);
        return created;
      }
      if (rid) {
        const idx = relations.findIndex((r) => r.id === rid);
        if (method === 'PATCH' && idx >= 0) {
          relations[idx] = { ...relations[idx], ...((init?.body ?? {}) as Record<string, unknown>) };
          return relations[idx];
        }
        if (method === 'DELETE' && idx >= 0) {
          relations.splice(idx, 1);
          return undefined;
        }
      }
      return { items: relations.map((r) => ({ ...r })), total: relations.length, offset: 0, limit: 50 };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('#650 角色关系 GUI（T1 关系区契约，角色详情面板内）', () => {
  it('打开详情面板（点角色名）→ 面板渲染（标题=角色名 + 关闭按钮）→ GET /characters/c1/relations 列表含 to_name/relation_type', async () => {
    // 预期 FAIL：角色 tab 无详情面板入口（名字不可点击）→ character-detail-panel element-missing
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openCharacterDetail(user);
    // 面板标题 = 角色名 + 关闭按钮
    expect(panel).toHaveTextContent('林晚');
    expect(within(panel).getByTestId('character-detail-close')).toBeInTheDocument();
    // 打开面板 → 拉取关系列表
    await waitFor(() => {
      expect(fetchCalled('/api/v1/characters/c1/relations')).toBe(true);
    });
    const list = await within(panel).findByTestId('character-rel-list');
    expect(within(list).getByText('沈砚')).toBeInTheDocument();   // to_name
    expect(within(list).getByText('宿敌')).toBeInTheDocument();    // relation_type
    expect(within(list).getByText('宿命对决')).toBeInTheDocument(); // description
    expect(within(list).getByTestId('character-rel-r1')).toBeInTheDocument();
  });

  it('空态：GET /characters/c1/relations 返回 [] → character-rel-empty 文案「暂无关系」', async () => {
    // 预期 FAIL：详情面板不存在 → character-detail-panel element-missing（空态无从渲染）
    relations = [];
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openCharacterDetail(user);
    const empty = await within(panel).findByTestId('character-rel-empty');
    expect(empty).toHaveTextContent('暂无关系');
  });

  it('添加关系：点 character-rel-add → 表单字段齐全 → 选对方角色+填类型/描述 → POST body 断言 → 列表出现新行', async () => {
    // 预期 FAIL：详情面板不存在 → character-detail-panel element-missing（表单/保存无从触发）
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openCharacterDetail(user);
    await user.click(within(panel).getByTestId('character-rel-add'));
    const form = await within(panel).findByTestId('character-rel-form');
    expect(within(form).getByTestId('character-rel-form-to')).toBeInTheDocument();
    expect(within(form).getByTestId('character-rel-form-type')).toBeInTheDocument();
    expect(within(form).getByTestId('character-rel-form-desc')).toBeInTheDocument();

    await selectCombo(within(form).getByTestId('character-rel-form-to'), '沈砚', user);
    fireEvent.change(within(form).getByTestId('character-rel-form-type'), { target: { value: '挚友' } });
    fireEvent.change(within(form).getByTestId('character-rel-form-desc'), { target: { value: '患难与共' } });
    await user.click(within(form).getByTestId('character-rel-form-save'));

    // POST body 契约：{to_character_id, relation_type, description}（from=路径角色，不提交）
    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/characters/c1/relations' && c[1]?.method === 'POST',
      );
      expect(call).toBeTruthy();
    });
    const postCall = apiFetchMock.mock.calls.find(
      (c) => c[0] === '/api/v1/characters/c1/relations' && c[1]?.method === 'POST',
    )!;
    expect(postCall[1]?.body).toEqual(
      expect.objectContaining({
        to_character_id: 'c2',
        relation_type: '挚友',
        description: '患难与共',
      }),
    );
    // 成功后局部刷新（状态化 mock POST unshift → 重拉/本地更新均显示新行）
    const list = await within(panel).findByTestId('character-rel-list');
    await waitFor(() => {
      expect(within(list).getByText('挚友')).toBeInTheDocument();
    });
  });

  it('编辑关系：点行内 character-rel-edit-r1 → 表单回填现值 → 改类型保存 → PATCH body 断言 → 行更新', async () => {
    // 预期 FAIL：详情面板不存在 → character-detail-panel element-missing（编辑无从触发）
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openCharacterDetail(user);
    const list = await within(panel).findByTestId('character-rel-list');
    await user.click(within(list).getByTestId('character-rel-edit-r1'));

    // 表单回填现值（编辑契约：类型输入 = 宿敌）
    const form = await within(panel).findByTestId('character-rel-form');
    const typeInput = within(form).getByTestId('character-rel-form-type') as HTMLInputElement;
    expect(typeInput.value).toBe('宿敌');
    fireEvent.change(typeInput, { target: { value: '盟友' } });
    await user.click(within(form).getByTestId('character-rel-form-save'));

    // PATCH body 契约：{relation_type?, description?}（from/to 不变）
    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/characters/c1/relations/r1' && c[1]?.method === 'PATCH',
      );
      expect(call).toBeTruthy();
    });
    const patchCall = apiFetchMock.mock.calls.find(
      (c) => c[0] === '/api/v1/characters/c1/relations/r1' && c[1]?.method === 'PATCH',
    )!;
    expect(patchCall[1]?.body).toEqual(expect.objectContaining({ relation_type: '盟友' }));
    // 刷新后更新（状态化 mock PATCH 合并回写 → 重拉/本地更新均显示新值）
    await waitFor(() => {
      expect(within(list).getByText('盟友')).toBeInTheDocument();
    });
  });

  it('删除关系：点行内 character-rel-delete-r1 → 确认框 character-rel-confirm-dialog → confirm-ok → DELETE 断言 → 行消失', async () => {
    // 预期 FAIL：详情面板不存在 → character-detail-panel element-missing（删除无从触发）
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openCharacterDetail(user);
    const list = await within(panel).findByTestId('character-rel-list');
    await user.click(within(list).getByTestId('character-rel-delete-r1'));

    // 二次确认（契约强制：character-rel-confirm-dialog + character-rel-confirm-ok）
    const confirm = await screen.findByTestId('character-rel-confirm-dialog');
    await user.click(within(confirm).getByTestId('character-rel-confirm-ok'));

    // DELETE /characters/{cid}/relations/{rid}（真删）→ 行消失
    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/characters/c1/relations/r1' && c[1]?.method === 'DELETE',
      );
      expect(call).toBeTruthy();
    });
    await waitFor(() => {
      expect(within(list).queryByTestId('character-rel-r1')).not.toBeInTheDocument();
    });
    // r2 行仍在（只删目标行）
    expect(within(list).getByTestId('character-rel-r2')).toBeInTheDocument();
  });

  it('关闭面板：点 character-detail-close → 面板消失（关系区随之卸载）', async () => {
    // 预期 FAIL：详情面板不存在 → character-detail-panel element-missing（关闭无从触发）
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();

    const panel = await openCharacterDetail(user);
    await user.click(within(panel).getByTestId('character-detail-close'));
    await waitFor(() => {
      expect(screen.queryByTestId('character-detail-panel')).not.toBeInTheDocument();
    });
  });
});
