/**
 * F43 P1（#284 第二批，specs/f43-setting-library-crud/spec.md v1.1 §2.2-2.3/§5.1-5.5/§9.2 R1-R13）：
 * 角色等级必填（D1）+ 分组标签多选（D2）+ 世界观树与分类筛选（D3）+ 世界观复制 GUI（F37 跨项目 copy）。
 *
 * ⚠️ 本批契约拆分至独立文件 library-p1.test.tsx：library.test.tsx 已 788 行，追加将超 900 行护栏。
 *
 * GREEN 契约（library.tsx + LibraryCreateDialog.tsx + 新组件 TagEditor/CopyDialog + i18n zh/en §6 表）：
 *
 * 角色等级（§5.1）：
 * - 创建/编辑对话框角色分类渲染「等级」下拉（shadcn Select，trigger data-testid=library-create-rank），
 *   五档选项 = lib.rank.protagonist/major/minor/scene/walkon（zh：主角/重要配角/配角/场景角色/一次性角色），
 *   占位 lib.rank.placeholder「选择等级」；编辑预填 editing.extra.role_rank ?? ''（旧数据无等级 → 占位重选）
 * - canSave gate：名称/标题必填 + 等级必填双满足才 enabled（D1 必填无默认）
 * - 列表行等级徽标 data-testid=lib-rank-x（文本 = lib.rank. 映射文案；缺省不渲染）
 *
 * 分组标签（§5.2，TagEditor）：
 * - lib-tag-input 输入框（占位 lib.tags.placeholder「输入标签，回车添加」；回车/逗号创建；strip 后空 → 不创建）
 * - 已选 chips data-testid=lib-tag-chip-<tag>，chip 内含 × 移除按钮（点击后 chip 消失）
 * - 建议标签按钮 data-testid=lib-tag-suggest-<tag>（来源 = 当前项目角色 extra.groups 并集；点击追加；重复忽略）
 * - 列表行标签 chips（只读）data-testid=lib-tags-x
 * - 保存 body：extra: { role_rank, groups }（groups 去重保序；编辑总发送完整 extra，spec §3.2 整体替换语义）
 *
 * 世界观树（§5.3）：
 * - items 含 parent_id，前端建树（顶层 = parent_id null/缺失；孤儿降级顶层）；列表区渲染树
 * - 展开/收起 toggle data-testid=world-tree-toggle-<id>（仅渲染在有子节点的行；叶子无 toggle）
 * - 契约：默认展开；点 toggle 收起 = 子节点不渲染（条件渲染）；再点展开
 *
 * 世界观分类筛选（§5.4）：
 * - 工具栏 chips data-testid=world-cat-filter-<category>：默认分组 地图/势力/功法/门派/秘境 + 数据中自定义
 *   category 自动进 chips（去重）；无「全部」chip（D-10）
 * - 点 chip = 按 category 过滤顶层节点（含其子树整体显隐，树不拆散）；再点同 chip = 取消筛选回默认
 *
 * 世界观复制 GUI（§5.5，CopyDialog）：
 * - 行内复制按钮 world-copy-<id>（树节点操作区）；顶部整体复制 world-copy-all（工具栏，文案 lib.copy.all「整体复制」）
 * - CopyDialog：data-testid=world-copy-dialog；范围 chips world-copy-scope-subtree（本体+全部子级，默认）/
 *   world-copy-scope-self（仅本体）；顶部整体复制入口 → 范围固定「全部」，scope chips 隐藏
 * - 目标项目 Select：trigger data-testid=world-copy-target（选项 = useProjectStore.projects 排除当前项目，E20）
 * - 确认 world-copy-ok / 取消 world-copy-cancel（#195：遮罩不关闭）
 * - 确认 → POST /api/v1/projects/{targetId}/world-settings/copy
 *   body：行内 subtree { source_project_id, root_setting_id }（无 self_only 或 false）；
 *        行内 self   { source_project_id, root_setting_id, self_only: true }；
 *        整体        { source_project_id }（无 root_setting_id）
 * - 成功 → ok toast lib.copy.result「已复制 {n} 条到「{name}」」（WorldCopyResult.created 长度）+ 对话框关闭
 * - 失败 → err toast + 对话框保持打开可重试（E24）
 * - 单项目（目标列表空）→ world-copy-all disabled（E21，提示 lib.copy.needTwo）
 *
 * 新增 i18n key（zh/en §6 表，GREEN 补）：lib.rank.*（5 档 + placeholder + label）、lib.tags.*、
 * lib.worldCat.label、lib.copy.title/scope/scope.subtree/scope.self/target/ok/all/result/skipped/needTwo。
 *
 * RED 预期：以上 testid 全部不存在（P1 实现未落地）→ element-missing / disabled 断言 FAIL（类 3 契约缺口）。
 * R6/R11/R13 各拆 2 个 it（POST/PATCH、subtree/self、失败/单项目），共 16 it。
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
  // 默认兜底：projects 双项目（复制目标前提）；各分类空列表（用例内重设）
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1, projectP2], total: 2, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('设定库页 — F43 P1 角色等级/标签/世界观树/复制（#284）', () => {
  /** 角色完整 DTO（P0 fullChar 模式 + P1 extra） */
  const fullChar: Record<string, unknown> = {
    id: 'c1', name: '林晚', personality: '孤傲', background: '剑客', goals: '决战',
  };

  /** 世界观层级树数据（w1 顶层 + w1a/w1b 子级 + w1a1 孙级，§9.2 R8 契约） */
  const worldTree: Array<Record<string, unknown>> = [
    { id: 'w1', name: '九州', category: '地图', content: '天下地理' },
    { id: 'w1a', name: '中州', category: '地图', content: '中原腹地', parent_id: 'w1' },
    { id: 'w1b', name: '东荒', category: '地图', content: '蛮荒之地', parent_id: 'w1' },
    { id: 'w1a1', name: '昆仑山', category: '秘境', content: '仙山福地', parent_id: 'w1a' },
  ];

  /** 播种 p1 + 角色列表回显式 mock（GET 返回数组 / POST 入数组 / PATCH 扁平端点合并，spec §3.1） */
  function mockCharacters(chars: Array<Record<string, unknown>>) {
    const data = chars.map((c) => ({ ...c }));
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') return { items: [projectP1, projectP2], total: 2, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/characters') {
        if (init?.method === 'POST') {
          const body = init.body as Record<string, unknown>;
          const created = { id: 'c9', ...body };
          data.push(created);
          return created;
        }
        return { items: data, total: data.length, offset: 0, limit: 50 };
      }
      if (init?.method === 'PATCH' && path.startsWith('/api/v1/characters/')) {
        const id = path.split('/').pop();
        const idx = data.findIndex((c) => String(c.id) === id);
        if (idx >= 0) {
          data[idx] = { ...data[idx], ...(init.body as Record<string, unknown>) };
          return data[idx];
        }
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1, projectP2], currentProjectId: 'p1' });
    });
  }

  /** #376：世界观 tab 默认进地图工作台 → 点 map-bc-world 退出回列表页（P1 分类 chips/复制交互在列表页断言） */
  async function enterWorldList(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('map-workbench');
    await user.click(screen.getByTestId('map-bc-world'));
    await screen.findByTestId('library-list');
  }

  /**
   * 播种 p1 + 世界观列表/复制端点 mock。
   * copyResult=null → 复制端点 reject（R13a 失败路径）；默认返回 WorldCopyResult（created 2 条）。
   */
  function mockWorldTree(
    worldItems: Array<Record<string, unknown>>,
    projectList: Array<typeof projectP1> = [projectP1, projectP2],
    copyResult: Record<string, unknown> | null = {
      created: [{ id: 'x1' }, { id: 'x2' }], skipped: [], maps_created: [], pins_created: 0, warnings: [],
    },
  ) {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') return { items: projectList, total: projectList.length, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/world-settings') {
        return { items: worldItems, total: worldItems.length, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p2/world-settings/copy' && init?.method === 'POST') {
        if (copyResult === null) throw new Error('复制失败');
        return copyResult;
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: projectList, currentProjectId: 'p1' });
    });
  }

  /** 角色 tab 空态 → CTA 打开创建对话框（#196 模式；POST 回显入数组） */
  async function openRoleCreateDialog() {
    act(() => {
      useProjectStore.setState({ projects: [projectP1, projectP2], currentProjectId: 'p1' });
    });
    const chars: Array<Record<string, unknown>> = [];
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') return { items: [projectP1, projectP2], total: 2, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/characters') {
        if (init?.method === 'POST') {
          const body = init.body as Record<string, unknown>;
          const created = { id: 'c9', ...body };
          chars.push(created);
          return created;
        }
        return { items: chars, total: chars.length, offset: 0, limit: 50 };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    renderLibrary();
    const empty = await screen.findByTestId('library-tab-empty');
    await user.click(within(empty).getByTestId('library-tab-empty-cta'));
    const dialog = await screen.findByTestId('library-create-dialog');
    return { user, dialog };
  }

  /** 选等级（shadcn Select：点 trigger → 选项 portal 到 body → 点 option） */
  async function pickRank(user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement, rankLabel: string) {
    await user.click(within(dialog).getByTestId('library-create-rank'));
    await user.click(await screen.findByRole('option', { name: rankLabel }));
  }

  it('R1 创建对话框渲染等级下拉 + 标签编辑器；仅填名称不选等级 → 保存 disabled（D1 必填无默认）', async () => {
    const { user, dialog } = await openRoleCreateDialog();
    // 等级下拉（shadcn Select trigger）+ 标签编辑器输入框
    expect(within(dialog).getByTestId('library-create-rank')).toBeInTheDocument();
    expect(within(dialog).getByTestId('lib-tag-input')).toBeInTheDocument();
    // 初始 disabled（名称 + 等级双必填）
    expect(within(dialog).getByTestId('library-create-save')).toBeDisabled();
    // 仅填名称 → 仍 disabled（E13：未选等级不触发请求）
    await user.type(within(dialog).getByLabelText('名称'), '叶孤城');
    expect(within(dialog).getByTestId('library-create-save')).toBeDisabled();
  });

  it('R2 填名称 + 选等级「重要配角」→ 保存 enabled → POST body 含 extra.role_rank=major', async () => {
    const { user, dialog } = await openRoleCreateDialog();
    const save = within(dialog).getByTestId('library-create-save');
    await user.type(within(dialog).getByLabelText('名称'), '叶孤城');
    await pickRank(user, dialog, '重要配角');
    await waitFor(() => {
      expect(within(dialog).getByTestId('library-create-save')).toBeEnabled();
    });
    await user.click(save);
    await waitFor(() => {
      const postCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/characters' && c[1]?.method === 'POST',
      );
      expect(postCall).toBeTruthy();
      expect((postCall![1]!.body as { extra?: { role_rank?: string } }).extra).toEqual(
        expect.objectContaining({ role_rank: 'major' }),
      );
    });
  });

  it('R3 编辑预填：editing 带 extra role_rank/groups → 下拉显示「重要配角」+ 标签 chip「主角团」存在', async () => {
    mockCharacters([{ ...fullChar, extra: { role_rank: 'major', groups: ['主角团'] } }]);
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-edit-c1'));
    const dialog = await screen.findByTestId('library-create-dialog');
    expect(within(dialog).getByTestId('library-create-rank')).toHaveTextContent('重要配角');
    expect(within(dialog).getByTestId('lib-tag-chip-主角团')).toBeInTheDocument();
  });

  it('R4 建议标签（项目内 groups 并集）点击追加 + 回车创建 + 重复/空白忽略', async () => {
    mockCharacters([
      { ...fullChar, id: 'c1', name: '林晚', extra: { role_rank: 'major', groups: ['主角团'] } },
      { ...fullChar, id: 'c2', name: '沈砚', extra: { role_rank: 'minor', groups: ['青云宗'] } },
    ]);
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-edit-c1'));
    const dialog = await screen.findByTestId('library-create-dialog');
    // 建议 = 当前项目角色 extra.groups 并集（D-13 数据驱动）
    expect(within(dialog).getByTestId('lib-tag-suggest-主角团')).toBeInTheDocument();
    expect(within(dialog).getByTestId('lib-tag-suggest-青云宗')).toBeInTheDocument();
    // 点击建议 → chip 出现
    await user.click(within(dialog).getByTestId('lib-tag-suggest-青云宗'));
    expect(within(dialog).getByTestId('lib-tag-chip-青云宗')).toBeInTheDocument();
    // 输入回车 → 新 chip
    const input = within(dialog).getByTestId('lib-tag-input');
    await user.type(input, '新标签{Enter}');
    expect(within(dialog).getByTestId('lib-tag-chip-新标签')).toBeInTheDocument();
    // 重复输入忽略（E15 去重保序）
    await user.type(input, '新标签{Enter}');
    expect(within(dialog).getAllByTestId(/^lib-tag-chip-新标签$/)).toHaveLength(1);
    // 空白输入忽略（E15 strip 后空 → 不创建）
    await user.type(input, '   {Enter}');
    expect(within(dialog).getAllByTestId(/^lib-tag-chip-/)).toHaveLength(3);
  });

  it('R5 标签 × 移除 → chip 消失；保存 body extra.groups 不含该标签', async () => {
    mockCharacters([{ ...fullChar, extra: { role_rank: 'major', groups: ['主角团', '青云宗'] } }]);
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-edit-c1'));
    const dialog = await screen.findByTestId('library-create-dialog');
    // chip 内 × 按钮移除
    const chip = within(dialog).getByTestId('lib-tag-chip-主角团');
    await user.click(within(chip).getByRole('button'));
    expect(within(dialog).queryByTestId('lib-tag-chip-主角团')).not.toBeInTheDocument();
    // 保存 → PATCH body groups 不含被移除标签
    await user.click(within(dialog).getByTestId('library-create-save'));
    await waitFor(() => {
      const patchCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/characters/c1' && c[1]?.method === 'PATCH',
      );
      expect(patchCall).toBeTruthy();
      const body = patchCall![1]!.body as { extra: { role_rank: string; groups: string[] } };
      expect(body.extra).toEqual({ role_rank: 'major', groups: ['青云宗'] });
    });
  });

  it('R6a 角色创建保存 body：extra = { role_rank, groups } 完整合并发送', async () => {
    const { user, dialog } = await openRoleCreateDialog();
    await user.type(within(dialog).getByLabelText('名称'), '叶孤城');
    await pickRank(user, dialog, '重要配角');
    await user.type(within(dialog).getByTestId('lib-tag-input'), '主角团{Enter}');
    await user.click(within(dialog).getByTestId('library-create-save'));
    await waitFor(() => {
      const postCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/characters' && c[1]?.method === 'POST',
      );
      expect(postCall).toBeTruthy();
      const body = postCall![1]!.body as { name: string; extra: { role_rank: string; groups: string[] } };
      expect(body.extra).toEqual({ role_rank: 'major', groups: ['主角团'] });
    });
  });

  it('R6b 角色编辑保存 body：extra 完整合并（role_rank + 新标签，spec §3.2 整体替换语义）', async () => {
    mockCharacters([{ ...fullChar, extra: { role_rank: 'major', groups: ['主角团'] } }]);
    const user = userEvent.setup();
    renderLibrary();

    await screen.findByTestId('library-list');
    await user.click(screen.getByTestId('lib-edit-c1'));
    const dialog = await screen.findByTestId('library-create-dialog');
    await user.type(within(dialog).getByTestId('lib-tag-input'), '青云宗{Enter}');
    await user.click(within(dialog).getByTestId('library-create-save'));
    await waitFor(() => {
      const patchCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/characters/c1' && c[1]?.method === 'PATCH',
      );
      expect(patchCall).toBeTruthy();
      const body = patchCall![1]!.body as { extra: { role_rank: string; groups: string[] } };
      // 编辑总是发送完整 extra（role_rank + groups 合并，避免整体替换丢字段）
      expect(body.extra).toEqual({ role_rank: 'major', groups: ['主角团', '青云宗'] });
    });
  });

  it('R7 角色列表行渲染等级徽标 lib-rank-c1（「重要配角」）+ 标签区 lib-tags-c1 含 chips', async () => {
    mockCharacters([{ ...fullChar, extra: { role_rank: 'major', groups: ['主角团', '青云宗'] } }]);
    renderLibrary();

    await screen.findByTestId('library-list');
    expect(screen.getByTestId('lib-rank-c1')).toHaveTextContent('重要配角');
    const tags = screen.getByTestId('lib-tags-c1');
    expect(tags).toHaveTextContent('主角团');
    expect(tags).toHaveTextContent('青云宗');
  });

  it('R8 世界观树渲染：parent_id 层级 + toggle 展开/收起（子节点显隐）', async () => {
    mockWorldTree(worldTree);
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('library-list');
    // 有子节点才渲染 toggle（w1/w1a 有子；w1b 叶子无）
    expect(screen.getByTestId('world-tree-toggle-w1')).toBeInTheDocument();
    expect(screen.getByTestId('world-tree-toggle-w1a')).toBeInTheDocument();
    expect(screen.queryByTestId('world-tree-toggle-w1b')).not.toBeInTheDocument();
    // 默认展开：子节点可见
    expect(screen.getByText('中州')).toBeInTheDocument();
    // 点 toggle 收起 → 子树不渲染
    await user.click(screen.getByTestId('world-tree-toggle-w1'));
    expect(screen.queryByText('中州')).not.toBeInTheDocument();
    // 再点展开 → 恢复
    await user.click(screen.getByTestId('world-tree-toggle-w1'));
    expect(screen.getByText('中州')).toBeInTheDocument();
  });

  it('R9 世界观分类 chips：默认仅「地图」（#352）+ 数据自定义自动进；无「全部」chip（D-10）', async () => {
    mockWorldTree([...worldTree, { id: 'w2', name: '宗门', category: '组织', content: '宗门林立' }]);
    const user = userEvent.setup();
    renderLibrary();

    await enterWorldList(user);
    // #352 拍板：默认分组仅「地图」；数据中自定义分类「组织」「秘境」自动进 chips（D-11 数据驱动）
    for (const cat of ['地图', '组织', '秘境']) {
      expect(screen.getByTestId(`world-cat-filter-${cat}`)).toBeInTheDocument();
    }
    // #352：势力/功法/门派 不再默认预置（题材相关分类按项目由用户/agent 创建）
    for (const cat of ['势力', '功法', '门派']) {
      expect(screen.queryByTestId(`world-cat-filter-${cat}`)).not.toBeInTheDocument();
    }
    // 无「全部」chip（D3 拍板：未选 = 展示所有，toggle 取消）
    expect(screen.queryByTestId('world-cat-filter-全部')).not.toBeInTheDocument();
  });

  it('R10 分类筛选 toggle：点 chip 仅显示该分类顶层（含子树）→ 再点同 chip 全部恢复', async () => {
    mockWorldTree([
      { id: 'w1', name: '九州', category: '地图', content: '天下地理' },
      { id: 'w1a', name: '中州', category: '地图', content: '中原腹地', parent_id: 'w1' },
      { id: 'w2', name: '宗门', category: '组织', content: '宗门林立' },
      { id: 'w3', name: '昆仑派', category: '门派', content: '仙门' },
    ]);
    const user = userEvent.setup();
    renderLibrary();

    await enterWorldList(user);
    // 默认展示所有
    expect(screen.getByText('宗门')).toBeInTheDocument();
    expect(screen.getByText('昆仑派')).toBeInTheDocument();
    // 点「地图」→ 仅地图分类顶层（含子树）显示
    await user.click(screen.getByTestId('world-cat-filter-地图'));
    expect(screen.getByText('九州')).toBeInTheDocument();
    expect(screen.getByText('中州')).toBeInTheDocument();
    expect(screen.queryByText('宗门')).not.toBeInTheDocument();
    expect(screen.queryByText('昆仑派')).not.toBeInTheDocument();
    // 再点同 chip → 取消筛选，全部恢复
    await user.click(screen.getByTestId('world-cat-filter-地图'));
    expect(screen.getByText('宗门')).toBeInTheDocument();
    expect(screen.getByText('昆仑派')).toBeInTheDocument();
  });

  it('R11a 行内复制（subtree 默认）：world-copy-w1 → CopyDialog → 目标 p2 → body 无 self_only → ok toast 创建数', async () => {
    mockWorldTree(worldTree);
    const user = userEvent.setup();
    renderLibrary();

    await enterWorldList(user);
    await user.click(screen.getByTestId('world-copy-w1'));
    const dialog = await screen.findByTestId('world-copy-dialog');
    // 范围 chips：本体+全部子级（默认）/ 仅本体
    expect(within(dialog).getByTestId('world-copy-scope-subtree')).toBeInTheDocument();
    expect(within(dialog).getByTestId('world-copy-scope-self')).toBeInTheDocument();
    // 目标项目：排除当前项目（E20：p1 不可选）
    await user.click(within(dialog).getByTestId('world-copy-target'));
    const p2Option = await screen.findByRole('option', { name: '归墟记' });
    expect(screen.queryByRole('option', { name: '青云志' })).not.toBeInTheDocument();
    await user.click(p2Option);
    // 确认 → POST copy（subtree 默认：无 self_only 或 false）
    await user.click(within(dialog).getByTestId('world-copy-ok'));
    await waitFor(() => {
      const copyCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p2/world-settings/copy' && c[1]?.method === 'POST',
      );
      expect(copyCall).toBeTruthy();
      const body = copyCall![1]!.body as {
        source_project_id: string; root_setting_id: string; self_only?: boolean;
      };
      expect(body).toEqual(expect.objectContaining({ source_project_id: 'p1', root_setting_id: 'w1' }));
      expect(body.self_only === undefined || body.self_only === false).toBe(true);
    });
    // 成功 → 对话框关闭 + ok toast 含创建数（lib.copy.result：已复制 2 条到「归墟记」）
    await waitFor(() => {
      expect(screen.queryByTestId('world-copy-dialog')).not.toBeInTheDocument();
      expect(
        useToastStore.getState().toasts.some(
          (t) => t.type === 'ok' && t.message.includes('已复制 2 条到「归墟记」'),
        ),
      ).toBe(true);
    });
  });

  it('R11b 行内复制（仅本体）：选 world-copy-scope-self → body 含 self_only=true', async () => {
    mockWorldTree(worldTree);
    const user = userEvent.setup();
    renderLibrary();

    await enterWorldList(user);
    await user.click(screen.getByTestId('world-copy-w1'));
    const dialog = await screen.findByTestId('world-copy-dialog');
    await user.click(within(dialog).getByTestId('world-copy-scope-self'));
    await user.click(within(dialog).getByTestId('world-copy-target'));
    await user.click(await screen.findByRole('option', { name: '归墟记' }));
    await user.click(within(dialog).getByTestId('world-copy-ok'));
    await waitFor(() => {
      const copyCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p2/world-settings/copy' && c[1]?.method === 'POST',
      );
      expect(copyCall).toBeTruthy();
      expect(copyCall![1]!.body).toEqual(
        expect.objectContaining({ source_project_id: 'p1', root_setting_id: 'w1', self_only: true }),
      );
    });
  });

  it('R12 顶部整体复制：world-copy-all → CopyDialog 无范围 chips → body 仅 { source_project_id }', async () => {
    mockWorldTree(worldTree);
    const user = userEvent.setup();
    renderLibrary();

    await enterWorldList(user);
    await user.click(screen.getByTestId('world-copy-all'));
    const dialog = await screen.findByTestId('world-copy-dialog');
    // 整体复制：范围固定「全部」，scope chips 隐藏
    expect(within(dialog).queryByTestId('world-copy-scope-subtree')).not.toBeInTheDocument();
    expect(within(dialog).queryByTestId('world-copy-scope-self')).not.toBeInTheDocument();
    await user.click(within(dialog).getByTestId('world-copy-target'));
    await user.click(await screen.findByRole('option', { name: '归墟记' }));
    await user.click(within(dialog).getByTestId('world-copy-ok'));
    await waitFor(() => {
      const copyCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p2/world-settings/copy' && c[1]?.method === 'POST',
      );
      expect(copyCall).toBeTruthy();
      // 严格：无 root_setting_id / 无 self_only
      expect(copyCall![1]!.body).toEqual({ source_project_id: 'p1' });
    });
  });

  it('R13a 复制失败：POST reject → err toast + CopyDialog 保持打开可重试（E24）', async () => {
    mockWorldTree(worldTree, [projectP1, projectP2], null);
    const user = userEvent.setup();
    renderLibrary();

    await enterWorldList(user);
    await user.click(screen.getByTestId('world-copy-w1'));
    const dialog = await screen.findByTestId('world-copy-dialog');
    await user.click(within(dialog).getByTestId('world-copy-target'));
    await user.click(await screen.findByRole('option', { name: '归墟记' }));
    await user.click(within(dialog).getByTestId('world-copy-ok'));
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
    });
    // 对话框保持打开（可修改重试）
    expect(screen.getByTestId('world-copy-dialog')).toBeInTheDocument();
  });

  it('R13b 单项目环境：world-copy-all disabled（E21，需至少两个项目）', async () => {
    mockWorldTree(worldTree, [projectP1]);
    const user = userEvent.setup();
    renderLibrary();

    await enterWorldList(user);
    expect(screen.getByTestId('world-copy-all')).toBeDisabled();
  });
});
