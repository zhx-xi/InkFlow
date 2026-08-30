/** 角色详情 API 客户端（#650 角色关系 + #651 角色分组，specs/f9-character/gui-role-enhance-red-contract.md；apiFetch 封装同 knowledge-graph.ts 模式） */
import { apiFetch } from './client';

/** 项目角色列表行（T1 对方角色下拉选项来源；#701 N:M 归属分组 group_ids，group_id 仅过渡兼容） */
export interface ProjectCharacter {
  id: string | number;
  name: string;
  group_id?: string | number | null;
  /** #701 N:M：角色所属全部分组 id（后端 list/get 响应字段） */
  group_ids?: (string | number)[];
  /** #701 N:M：角色所属分组名（后端 list 响应解析填充） */
  group_names?: string[];
}

/** #701 角色详情面板 item 类型：多分组 N:M（group_id 仅作旧数据过渡兜底读取） */
export interface CharacterDetailModel {
  id: string | number;
  name?: string;
  title?: string;
  group_id?: string | number | null;
  group_ids?: (string | number)[] | null;
  group_names?: string[];
}

/** 角色关系行（T1：GET /characters/{cid}/relations 响应行） */
export interface CharacterRelation {
  id: string | number;
  from_character_id: string | number;
  to_character_id: string | number;
  from_name: string;
  to_name: string;
  relation_type: string;
  description: string;
}

/** 角色关系列表响应（{items,total,offset,limit}） */
export interface CharacterRelationListResponse {
  items: CharacterRelation[];
  total: number;
  offset: number;
  limit: number;
}

/** 创建关系请求体（from=路径角色，不在 body 提交） */
export interface CharacterRelationCreateInput {
  to_character_id: string | number;
  relation_type: string;
  description?: string;
}

/** 更新关系请求体（from/to 不变，全可选） */
export type CharacterRelationUpdateInput = Partial<Pick<CharacterRelationCreateInput, 'relation_type' | 'description'>>;

/** 角色分组行（T2：GET /projects/{pid}/character-groups 响应行） */
export interface CharacterGroup {
  id: string | number;
  name: string;
  description: string;
  sort_order: number;
  member_count: number;
}

/** 角色分组列表响应（{items,total,offset,limit}） */
export interface CharacterGroupListResponse {
  items: CharacterGroup[];
  total: number;
  offset: number;
  limit: number;
}

/** 创建分组请求体（sort_order 服务端可补默认，前端顺位递增） */
export interface CharacterGroupCreateInput {
  name: string;
  description?: string;
  sort_order?: number;
}

/** 更新分组请求体（全可选） */
export type CharacterGroupUpdateInput = Partial<CharacterGroupCreateInput>;

/** GET /api/v1/projects/{pid}/characters——项目角色列表（对方角色下拉 + 分组归属） */
export async function listProjectCharacters(
  projectId: string,
): Promise<{ items: ProjectCharacter[]; total: number; offset: number; limit: number }> {
  return apiFetch(`/api/v1/projects/${projectId}/characters`);
}

/** GET /api/v1/characters/{cid}/relations——角色关系列表 */
export async function listCharacterRelations(cid: string | number): Promise<CharacterRelationListResponse> {
  return apiFetch<CharacterRelationListResponse>(`/api/v1/characters/${cid}/relations`);
}

/** POST /api/v1/characters/{cid}/relations——添加关系（from=路径角色） */
export async function createCharacterRelation(
  cid: string | number,
  body: CharacterRelationCreateInput,
): Promise<CharacterRelation> {
  return apiFetch<CharacterRelation>(`/api/v1/characters/${cid}/relations`, { method: 'POST', body });
}

/** PATCH /api/v1/characters/{cid}/relations/{rid}——编辑关系（from/to 不变） */
export async function updateCharacterRelation(
  cid: string | number,
  rid: string | number,
  body: CharacterRelationUpdateInput,
): Promise<CharacterRelation> {
  return apiFetch<CharacterRelation>(`/api/v1/characters/${cid}/relations/${rid}`, { method: 'PATCH', body });
}

/** DELETE /api/v1/characters/{cid}/relations/{rid}——真删 */
export async function deleteCharacterRelation(cid: string | number, rid: string | number): Promise<void> {
  return apiFetch<void>(`/api/v1/characters/${cid}/relations/${rid}`, { method: 'DELETE' });
}

/** GET /api/v1/projects/{pid}/character-groups——角色分组列表 */
export async function listCharacterGroups(projectId: string): Promise<CharacterGroupListResponse> {
  return apiFetch<CharacterGroupListResponse>(`/api/v1/projects/${projectId}/character-groups`);
}

/** POST /api/v1/projects/{pid}/character-groups——新建分组 */
export async function createCharacterGroup(
  projectId: string,
  body: CharacterGroupCreateInput,
): Promise<CharacterGroup> {
  return apiFetch<CharacterGroup>(`/api/v1/projects/${projectId}/character-groups`, { method: 'POST', body });
}

/** PATCH /api/v1/character-groups/{gid}——编辑分组 */
export async function updateCharacterGroup(
  gid: string | number,
  body: CharacterGroupUpdateInput,
): Promise<CharacterGroup> {
  return apiFetch<CharacterGroup>(`/api/v1/character-groups/${gid}`, { method: 'PATCH', body });
}

/** DELETE /api/v1/character-groups/{gid}——真删（成员与分组的 N:M 关联一并删除） */
export async function deleteCharacterGroup(gid: string | number): Promise<void> {
  return apiFetch<void>(`/api/v1/character-groups/${gid}`, { method: 'DELETE' });
}

/** PATCH /api/v1/characters/{cid}——角色部分更新（#701 归属分组 body={group_ids:[...]} 全量数组） */
export async function updateCharacter(
  cid: string | number,
  body: { group_ids: (string | number)[] },
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/v1/characters/${cid}`, { method: 'PATCH', body });
}
