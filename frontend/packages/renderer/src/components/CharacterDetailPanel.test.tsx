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
import { render, screen, within } from '@testing-library/react';
import { CharacterDetailPanel } from './CharacterDetailPanel';
import {
  listCharacterRelations,
  listProjectCharacters,
  listCharacterGroups,
  type CharacterRelation,
  type ProjectCharacter,
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

function renderPanel() {
  return render(<CharacterDetailPanel item={currentChar} projectId="p1" onClose={() => {}} />);
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
