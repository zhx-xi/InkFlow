/**
 * ⚠️ 契约文件（Issue #679：角色列表分组卡片缺失 + 等级徽标同色 + 等级选项卡总览/分览 RED 阶段）
 *
 * 【背景】LibraryItemList.tsx:26-99 对 characters 分类纯平铺 ul，无按 group_id 的分组分区；
 * rank 徽标（:55-62）硬编码 bg-accent/10 text-accent，五档等级全同色；无等级过滤。
 *
 * 【修复契约（GREEN，用户已拍板）】
 * - 新增 prop `characterGroups?: CharacterGroup[]`（数据源 = GET /projects/{pid}/character-groups）。
 * - withCharacterExtras=true 时顶部渲染**等级选项卡**（总览/分览）：
 *   - 容器 character-rank-tabs；选项卡 character-rank-tab-<all|protagonist|major|minor|scene|walkon>
 *   - 默认选中「全部·总览」(all)：显示项目内全部角色
 *   - 选中某等级 = 分览：仅显示 extra.role_rank === 该等级的角色
 *   - 「全部」为常驻默认项（点击当前等级不取消回全部，需点「全部」）
 * - 列表按 group_id 渲染分组分区（派系卡片），未分组(group_id null/undefined)收尾组；
 *   分览下无可显成员的分组隐藏。
 * - 分组分区容器 data-testid=`lib-group-<gid>`、未分组 `lib-group-ungrouped`；分区标题
 *   `lib-group-title-<gid>` / `lib-group-ungrouped-title`（标题 = 组名，未分组 = t('lib.charGroup.ungrouped')）。
 * - rank 徽标对应等级分色阶（五档不同色，映射真实 theme token）：
 *   protagonist → bg-accent text-accent-ink   major → bg-accent/40 text-accent-ink
 *   minor → bg-surface-3 text-ink-2           scene → bg-surface-2 text-ink-3
 *   walkon → bg-surface-3 text-ink-3/60
 * - 旧 extra.groups 标签 chips（lib-tags-<id>）与 group_id 正交，分组后仍渲染。
 * - 外层容器 data-testid="library-list" 保持（既有页面契约）；行内 lib-name-<id>/lib-rank-<id>/lib-edit-<id>/lib-delete-<id> 不变。
 * - withCharacterExtras=false（非 characters 分类）保持平铺、不渲染选项卡/分组。
 *
 * RED 预期：现无选项卡/分组 → getByTestId('character-rank-tabs') / 'lib-group-g1' element-missing，FAIL；
 * 五档徽标 Set 大小=1 ≠ 5 → FAIL。
 *
 * 本文件禁 import GREEN 才新增的辅助模块——只经 LibraryItemList 直接渲染断言。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LibraryItemList } from './LibraryItemList';
import type { LibraryItemDTO } from './LibraryCreateDialog';
import type { CharacterGroup } from '../api/character';
import { useThemeStore } from '../stores/theme';

/** 项目内角色列表种子（group_id 有/无 混合；extra 仅 role_rank，无 extra.groups 避免与组名冲突） */
const ITEMS: Array<LibraryItemDTO & { group_id?: string | number | null }> = [
  { id: 'c1', name: '林晚',   group_id: 'g1',    extra: { role_rank: 'protagonist' } },
  { id: 'c2', name: '沈砚',   group_id: 'g1',    extra: { role_rank: 'major' } },
  { id: 'c3', name: '叶孤城', group_id: 'g2',    extra: { role_rank: 'minor' } },
  { id: 'c4', name: '路人甲', group_id: null,     extra: { role_rank: 'scene' } },
  { id: 'c5', name: '路人乙', group_id: undefined, extra: { role_rank: 'walkon' } },
];

/** GET /projects/{pid}/character-groups 种子 */
const GROUPS: CharacterGroup[] = [
  { id: 'g1', name: '主角团', description: '主线核心', sort_order: 1, member_count: 2 },
  { id: 'g2', name: '青云宗', description: '宗门势力', sort_order: 2, member_count: 1 },
];

function renderList(props?: Partial<Parameters<typeof LibraryItemList>[0]>) {
  return render(
    <LibraryItemList
      items={ITEMS}
      characterGroups={GROUPS}
      onEdit={vi.fn()}
      onDelete={vi.fn()}
      onOpenDetail={vi.fn()}
      {...props}
    />,
  );
}

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#679 角色列表等级选项卡(总览/分览) + 分组卡片 + 等级徽标分色', () => {
  it('默认「全部·总览」：渲染等级选项卡栏 + 全部分组（含未分组收尾组）+ 全部角色', () => {
    renderList({ withCharacterExtras: true });

    // 等级选项卡栏 + 各等级选项卡（含常驻「全部」）
    expect(screen.getByTestId('character-rank-tabs')).toBeInTheDocument();
    for (const key of ['all', 'protagonist', 'major', 'minor', 'scene', 'walkon']) {
      expect(screen.getByTestId(`character-rank-tab-${key}`)).toBeInTheDocument();
    }

    // 总览 = 全部角色
    expect(screen.getByText('林晚')).toBeInTheDocument();
    expect(screen.getByText('沈砚')).toBeInTheDocument();
    expect(screen.getByText('叶孤城')).toBeInTheDocument();
    expect(screen.getByText('路人甲')).toBeInTheDocument();
    expect(screen.getByText('路人乙')).toBeInTheDocument();

    // 分组分区：g1/g2 + 未分组收尾组
    const g1 = screen.getByTestId('lib-group-g1');
    expect(within(g1).getByTestId('lib-group-title-g1')).toHaveTextContent('主角团');
    expect(within(g1).getByText('林晚')).toBeInTheDocument();
    expect(within(g1).getByText('沈砚')).toBeInTheDocument();
    const g2 = screen.getByTestId('lib-group-g2');
    expect(within(g2).getByTestId('lib-group-title-g2')).toHaveTextContent('青云宗');
    expect(within(g2).getByText('叶孤城')).toBeInTheDocument();
    const ungrouped = screen.getByTestId('lib-group-ungrouped');
    expect(within(ungrouped).getByTestId('lib-group-ungrouped-title')).toHaveTextContent('未分组');
    expect(within(ungrouped).getByText('路人甲')).toBeInTheDocument();
    expect(within(ungrouped).getByText('路人乙')).toBeInTheDocument();

    // 外层容器 library-list 保留（既有页面契约）
    expect(screen.getByTestId('library-list')).toBeInTheDocument();
  });

  it('选中某等级选项卡（分览）：仅显示该等级角色；点「全部」恢复总览', async () => {
    const user = userEvent.setup();
    renderList({ withCharacterExtras: true });

    await user.click(screen.getByTestId('character-rank-tab-protagonist'));
    // 分览：仅主角角色（林晚），其余等级角色隐藏
    expect(screen.getByText('林晚')).toBeInTheDocument();
    expect(screen.queryByText('沈砚')).not.toBeInTheDocument();
    expect(screen.queryByText('叶孤城')).not.toBeInTheDocument();
    expect(screen.queryByText('路人甲')).not.toBeInTheDocument();
    expect(screen.queryByText('路人乙')).not.toBeInTheDocument();
    // 无主角成员的分组（青云宗）隐藏
    expect(screen.queryByTestId('lib-group-g2')).not.toBeInTheDocument();

    // 点「全部·总览」回到总览
    await user.click(screen.getByTestId('character-rank-tab-all'));
    expect(screen.getByText('沈砚')).toBeInTheDocument();
    expect(screen.getByText('叶孤城')).toBeInTheDocument();
  });

  it('rank 徽标按等级分色（五档不同色），映射真实 theme token', () => {
    renderList({ withCharacterExtras: true });

    const ids = ['c1', 'c2', 'c3', 'c4', 'c5'];
    const badgeClasses = ids.map((id) => screen.getByTestId(`lib-rank-${id}`).className);
    expect(new Set(badgeClasses).size).toBe(5);

    expect(screen.getByTestId('lib-rank-c1')).toHaveClass('bg-accent'); // 主角 实心
    expect(screen.getByTestId('lib-rank-c2')).toHaveClass('bg-accent/40'); // 重要配角
    expect(screen.getByTestId('lib-rank-c3')).toHaveClass('bg-surface-3'); // 配角
    expect(screen.getByTestId('lib-rank-c3')).toHaveClass('text-ink-2');
    expect(screen.getByTestId('lib-rank-c4')).toHaveClass('bg-surface-2'); // 场景角色
    expect(screen.getByTestId('lib-rank-c4')).toHaveClass('text-ink-3');
    expect(screen.getByTestId('lib-rank-c5')).toHaveClass('text-ink-3/60'); // 一次性
  });

  it('非 characters 分类（withCharacterExtras=false）保持平铺列表，不渲染选项卡/分组', () => {
    renderList({ withCharacterExtras: false });
    expect(screen.getByTestId('library-list')).toBeInTheDocument();
    expect(screen.queryByTestId('character-rank-tabs')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lib-group-g1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lib-group-ungrouped')).not.toBeInTheDocument();
  });

  it('分组后旧 extra.groups 标签 chips（lib-tags-*）仍渲染（与 group_id 正交）', () => {
    const withTags = [
      { id: 'c1', name: '林晚', group_id: 'g1', extra: { role_rank: 'protagonist', groups: ['主角团'] } },
    ] as Array<LibraryItemDTO & { group_id?: string | number | null }>;
    render(
      <LibraryItemList
        items={withTags}
        characterGroups={GROUPS}
        withCharacterExtras
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onOpenDetail={vi.fn()}
      />,
    );
    expect(screen.getByTestId('lib-tags-c1')).toBeInTheDocument();
    expect(screen.getByTestId('lib-rank-c1')).toHaveClass('bg-accent'); // 分组不吞掉分色
  });
});

describe('#701 角色多分组 N:M：group_ids 数组跨分组卡片', () => {
  /**
   * N:M 种子：group_ids 数组替代单值 group_id（group_id 保留仅为过渡兼容，断言一律以 group_ids 为准）。
   * - c1 林晚：group_ids 含 g1+g2 → 应同时出现在 g1/g2 两个卡片（N:M 判据）
   * - c6 双面人：group_id=null 但 group_ids=['g2'] → 按 group_ids 归 g2，绝不进未分组
   */
  const NM_ITEMS: Array<
    LibraryItemDTO & { group_id?: string | number | null; group_ids?: (string | number)[] | null }
  > = [
    { id: 'c1', name: '林晚', group_id: 'g1', group_ids: ['g1', 'g2'], extra: { role_rank: 'protagonist' } },
    { id: 'c2', name: '沈砚', group_id: 'g2', group_ids: ['g2'], extra: { role_rank: 'major' } },
    { id: 'c3', name: '路人甲', group_ids: [], extra: { role_rank: 'scene' } },
    { id: 'c4', name: '路人乙', extra: { role_rank: 'walkon' } },
    { id: 'c5', name: '路人丙', group_ids: null, extra: { role_rank: 'minor' } },
    { id: 'c6', name: '双面人', group_id: null, group_ids: ['g2'], extra: { role_rank: 'major' } },
  ];

  it('N:M：同一角色（group_ids 含 g1+g2）在 lib-group-g1 与 lib-group-g2 两个分组卡片中都出现', () => {
    renderList({ items: NM_ITEMS, withCharacterExtras: true });
    const g1 = screen.getByTestId('lib-group-g1');
    const g2 = screen.getByTestId('lib-group-g2');
    expect(within(g1).getByText('林晚')).toBeInTheDocument();
    // 旧实现按单值 group_id='g1' 分组 → 林晚只进 g1，g2 卡片找不到 → FAIL
    expect(within(g2).getByText('林晚')).toBeInTheDocument();
    expect(within(g2).getByText('沈砚')).toBeInTheDocument();
  });

  it('未分组卡片只收 group_ids 为空/undefined/null 的角色；非空者（即使 group_id 为 null）不进未分组', () => {
    renderList({ items: NM_ITEMS, withCharacterExtras: true });
    const ungrouped = screen.getByTestId('lib-group-ungrouped');
    // group_ids 为空数组/undefined/null → 归入未分组
    expect(within(ungrouped).getByText('路人甲')).toBeInTheDocument(); // []
    expect(within(ungrouped).getByText('路人乙')).toBeInTheDocument(); // undefined
    expect(within(ungrouped).getByText('路人丙')).toBeInTheDocument(); // null
    // group_ids 非空 → 绝不进未分组（旧实现：双面人 group_id=null 被误收进未分组 → FAIL）
    expect(within(ungrouped).queryByText('双面人')).not.toBeInTheDocument();
    expect(within(ungrouped).queryByText('林晚')).not.toBeInTheDocument();
    expect(within(ungrouped).queryByText('沈砚')).not.toBeInTheDocument();
    // 双面人按 group_ids=['g2'] 归入 g2 卡片（旧实现 g2 无此人 → FAIL）
    expect(within(screen.getByTestId('lib-group-g2')).getByText('双面人')).toBeInTheDocument();
  });
});
