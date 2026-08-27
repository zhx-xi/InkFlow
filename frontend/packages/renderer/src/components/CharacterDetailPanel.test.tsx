/**
 * ⚠️ 契约文件（Issue #678：角色详情关系区双向显示缺陷 RED 阶段）
 *
 * 【背景】后端关系是双向的（character_relations 有 from/to 两方向），但 CharacterDetailPanel.tsx:358
 * 关系行只渲染 `r.to_name`。凡「当前角色为 to 端」的关系行，会把当前角色自己显示为对方 → 关系错乱。
 *
 * 【修复契约（GREEN）】行渲染按方向取对方名：
 * - 当前角色是 from 端（String(r.from_character_id) === characterId）→ 显示 to_name（对方）
 * - 当前角色是 to 端（String(r.to_character_id) === characterId）→ 显示 from_name（对方）
 * - 其余字段（relation_type / description）不因方向修复而丢失
 *
 * 【mock 模式】组件直接 import ../api/character（listCharacterRelations 等），此处 mock 整个模块，
 * 函数级 mockResolvedValue 播种双向关系数据。useThemeStore.setState({lang:'zh'}) 取中文文案。
 *
 * RED 预期：当前代码对所有关系行都渲染 to_name → 「当前角色为 to 端」用例：
 * - within(character-rel-r2).getByText('沈砚')(from_name) → element-missing，FAIL
 * - within(character-rel-r2).queryByText('林晚')(to_name=当前角色自己) 存在 → 断言 not 失败，FAIL
 *
 * 本文件禁 import GREEN 才新增的辅助模块——只经 CharacterDetailPanel 直接渲染 + mock 断言。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CharacterDetailPanel } from './CharacterDetailPanel';
import {
  listCharacterRelations,
  listProjectCharacters,
  listCharacterGroups,
  updateCharacter,
  type CharacterGroup,
  type CharacterRelation,
  type ProjectCharacter,
  type CharacterDetailModel,
} from '../api/character';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/character', () => ({
  listCharacterRelations: vi.fn(),
  listProjectCharacters: vi.fn(),
  listCharacterGroups: vi.fn(),
  createCharacterRelation: vi.fn(),
  updateCharacterRelation: vi.fn(),
  deleteCharacterRelation: vi.fn(),
  createCharacterGroup: vi.fn(),
  updateCharacterGroup: vi.fn(),
  deleteCharacterGroup: vi.fn(),
  updateCharacter: vi.fn(),
}));

/** 打开详情面板的「当前角色」（characterId = String(item.id) = 'c1'） */
const currentChar = {
  id: 'c1',
  name: '林晚',
  group_id: null,
};

/**
 * 双向关系种子：
 * - r1：当前角色 c1 为 from 端 → 对方 = to_name（沈砚）
 * - r2：当前角色 c1 为 to 端 → 对方 = from_name（沈砚）；to_name 是当前角色自己（林晚），
 *       GREEN 必须显示 from_name 而非 to_name。
 */
const RELATIONS: CharacterRelation[] = [
  {
    id: 'r1', from_character_id: 'c1', to_character_id: 'c2',
    from_name: '林晚', to_name: '沈砚', relation_type: '宿敌', description: '宿命对决',
  },
  {
    id: 'r2', from_character_id: 'c2', to_character_id: 'c1',
    from_name: '沈砚', to_name: '林晚', relation_type: '师徒', description: '剑道传承',
  },
];

function renderPanel(item: CharacterDetailModel = currentChar) {
  return render(<CharacterDetailPanel item={item} projectId="p1" onClose={() => {}} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  vi.mocked(listCharacterRelations).mockResolvedValue({
    items: RELATIONS.map((r) => ({ ...r })), total: RELATIONS.length, offset: 0, limit: 50,
  });
  vi.mocked(listProjectCharacters).mockResolvedValue({
    items: [
      { id: 'c2', name: '沈砚' },
      { id: 'c3', name: '叶孤城' },
    ] as ProjectCharacter[], total: 2, offset: 0, limit: 50,
  });
  vi.mocked(listCharacterGroups).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  // #701：updateCharacter mock 记录调用并返回可 await 的结果（组件 PATCH 后 await 不挂起）
  vi.mocked(updateCharacter).mockResolvedValue({ group_id: null, group_ids: [] });
});

describe('#678 角色详情关系区双向显示', () => {
  it('关系行按方向取对方名：from 端 → to_name；to 端 → from_name（不显示当前角色自己）', async () => {
    renderPanel();
    const list = await screen.findByTestId('character-rel-list');

    // r1：当前角色(林晚)是 from 端 → 对方 = to_name(沈砚)；from_name(林晚)是当前角色自己，不应作为"对方"
    const r1 = within(list).getByTestId('character-rel-r1');
    expect(within(r1).getByText('沈砚')).toBeInTheDocument();
    expect(within(r1).queryByText('林晚')).not.toBeInTheDocument();

    // r2：当前角色(林晚)是 to 端 → 对方 = from_name(沈砚)；to_name(林晚)是当前角色自己，绝不能显示
    const r2 = within(list).getByTestId('character-rel-r2');
    expect(within(r2).getByText('沈砚')).toBeInTheDocument();
    expect(within(r2).queryByText('林晚')).not.toBeInTheDocument();
  });

  it('双向显示不破坏字段：关系行仍渲染 relation_type 与 description', async () => {
    renderPanel();
    const list = await screen.findByTestId('character-rel-list');
    expect(within(list).getByText('宿敌')).toBeInTheDocument();    // r1 type
    expect(within(list).getByText('宿命对决')).toBeInTheDocument(); // r1 desc
    expect(within(list).getByText('师徒')).toBeInTheDocument();     // r2 type
    expect(within(list).getByText('剑道传承')).toBeInTheDocument(); // r2 desc
  });
});

describe('#701 角色多分组 N:M：分组区多选 checkbox 列表 + 全量 group_ids PATCH', () => {
  /** 分组种子（多选选项来源） */
  const GROUPS: CharacterGroup[] = [
    { id: 'g1', name: '主角团', description: '主线核心', sort_order: 1, member_count: 2 },
    { id: 'g2', name: '青云宗', description: '宗门势力', sort_order: 2, member_count: 1 },
    { id: 'g3', name: '天机阁', description: '情报组织', sort_order: 3, member_count: 1 },
  ];
  /** 已在两个分组中的角色（N:M 回显种子） */
  const multiGroupChar = { id: 'c1', name: '林晚', group_id: 'g1', group_ids: ['g1', 'g2'] };
  /** 仅在一个分组中的角色（勾选增量种子） */
  const singleGroupChar = { id: 'c1', name: '林晚', group_id: 'g1', group_ids: ['g1'] };

  beforeEach(() => {
    vi.mocked(listCharacterGroups).mockResolvedValue({
      items: GROUPS.map((g) => ({ ...g })), total: GROUPS.length, offset: 0, limit: 50,
    });
  });

  it('分组区为多选 checkbox 列表（非单选 Select）：容器 character-group-multi，每分组一项含 checkbox，含未分组项', async () => {
    renderPanel(multiGroupChar);
    // 旧实现是单选 Select（character-group-select），无多选容器 → element-missing，FAIL
    const multi = await screen.findByTestId('character-group-multi');
    for (const g of GROUPS) {
      const opt = within(multi).getByTestId(`character-group-option-${g.id}`);
      expect(within(opt).getByRole('checkbox')).toBeInTheDocument();
      expect(within(opt).getByText(g.name)).toBeInTheDocument();
    }
    const ungrouped = within(multi).getByTestId('character-group-option-ungrouped');
    expect(within(ungrouped).getByRole('checkbox')).toBeInTheDocument();
  });

  it('当前角色 group_ids 含多组 → 对应分组 checkbox 全部勾选（N:M 回显）', async () => {
    renderPanel(multiGroupChar);
    const multi = await screen.findByTestId('character-group-multi');
    expect(within(within(multi).getByTestId('character-group-option-g1')).getByRole('checkbox')).toBeChecked();
    expect(within(within(multi).getByTestId('character-group-option-g2')).getByRole('checkbox')).toBeChecked();
    expect(within(within(multi).getByTestId('character-group-option-g3')).getByRole('checkbox')).not.toBeChecked();
  });

  it('勾选新分组 → PATCH /characters/c1 body={group_ids:[既有+新]}（全量数组）', async () => {
    const user = userEvent.setup();
    renderPanel(singleGroupChar); // 既有 ['g1']
    const multi = await screen.findByTestId('character-group-multi');
    await user.click(within(within(multi).getByTestId('character-group-option-g2')).getByRole('checkbox'));
    // 旧实现无 checkbox 可点 → updateCharacter 不被调用，FAIL
    await waitFor(() => {
      expect(updateCharacter).toHaveBeenCalledTimes(1);
      const body = vi.mocked(updateCharacter).mock.calls[0][1] as { group_ids: (string | number)[] };
      expect(body.group_ids).toEqual(expect.arrayContaining(['g1', 'g2']));
      expect(body.group_ids).toHaveLength(2);
    });
  });

  it('取消勾选某分组 → PATCH body={group_ids:[剩余]}（全量数组）', async () => {
    const user = userEvent.setup();
    renderPanel(multiGroupChar); // 既有 ['g1','g2']
    const multi = await screen.findByTestId('character-group-multi');
    await user.click(within(within(multi).getByTestId('character-group-option-g1')).getByRole('checkbox'));
    await waitFor(() => {
      expect(updateCharacter).toHaveBeenCalledTimes(1);
      const body = vi.mocked(updateCharacter).mock.calls[0][1] as { group_ids: (string | number)[] };
      expect(body.group_ids).toEqual(expect.arrayContaining(['g2']));
      expect(body.group_ids).toHaveLength(1);
    });
  });

  it('勾选「未分组」→ PATCH body={group_ids:[]}（清空全部分组）', async () => {
    const user = userEvent.setup();
    renderPanel(multiGroupChar);
    const multi = await screen.findByTestId('character-group-multi');
    await user.click(within(within(multi).getByTestId('character-group-option-ungrouped')).getByRole('checkbox'));
    await waitFor(() => {
      expect(updateCharacter).toHaveBeenCalledTimes(1);
      expect(vi.mocked(updateCharacter).mock.calls[0][1]).toEqual({ group_ids: [] });
    });
  });
});
