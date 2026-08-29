# 角色增强 GUI RED 契约（T1 关系 #650 + T2 分组 #651）

> 本文件是 Codex GREEN 实现的权威契据。前端角色 tab 当前**无独立「角色详情面板」**
> ——GREEN 需在 `library.tsx` 角色行加「点名字打开详情面板」入口，新建
> `CharacterDetailPanel` 组件承载关系区 + 分组区。
> 参考模板：`library-kg.test.tsx`（知识图谱关系 CRUD mock 模式）+ `library-p1.test.tsx`
>（角色 extra.role_rank/groups 契约）。

## 通用 mock 模式（沿用 library-kg.test.tsx）
- `vi.mock('../api/client', importOriginal)` 保留 `apiFetch`，mock 为 `vi.fn()`
- `useProjectStore.setState({ projects:[p1], currentProjectId:'p1' })`
- `apiFetchMock.mockImplementation(async (path, init) => {...})` 状态化 mock
- `fetchCalled(path)` = `apiFetchMock.mock.calls.some(c => c[0]===path)`
- 播种：`/api/v1/projects` 返回项目；`/api/v1/projects/p1/characters` 返回角色列表

## 端点契约（后端已实现，源码核实）
### 关系（#650）
- `GET /api/v1/characters/{cid}/relations` → `{items:[{id, from_character_id, to_character_id, from_name, to_name, relation_type, description}], total}`
- `POST /api/v1/characters/{cid}/relations` (201) body=`{to_character_id, relation_type, description}`；from=路径角色
- `PATCH /api/v1/characters/{cid}/relations/{rid}` body=`{relation_type?, description?}`（from/to 不变）
- `DELETE /api/v1/characters/{cid}/relations/{rid}` (204) 真删

### 分组（#651）
- `GET /api/v1/projects/{pid}/character-groups` → `{items:[{id, name, description, sort_order, member_count}], total}`
- `POST /api/v1/projects/{pid}/character-groups` (201) body=`{name, description, sort_order}` → CharacterGroup
- `PATCH /api/v1/character-groups/{gid}` body=`{name?, description?, sort_order?}`
- `DELETE /api/v1/character-groups/{gid}` (204) 真删
- 角色归属分组：`PATCH /api/v1/characters/{cid}` body=`{group_id}`（角色表有 group_id 字段）

## 角色详情面板入口（GREEN 新增，library.tsx）
- 角色行 `LibraryItemList`：给 `characters` 分类的**名字加可点击**（或新增"详情"图标按钮），
  点击 → 打开 `CharacterDetailPanel`。
- 角色详情面板容器 `data-testid="character-detail-panel"`，标题 = 角色名。
- 关闭按钮 `character-detail-close`。

## T1 关系区契约（面板内）
- `character-rel-add`：「＋ 添加关系」按钮
- `character-rel-form`：添加/编辑关系表单容器
  - `character-rel-form-to`：对方角色下拉（选项=项目内其他角色）
  - `character-rel-form-type`：关系类型输入
  - `character-rel-form-desc`：描述输入
  - `character-rel-form-save`：保存按钮
- `character-rel-list`：关系列表容器（空态=`character-rel-empty` 文案「暂无关系」）
- 关系行：`character-rel-<rid>`（含 to_name / relation_type / description）
  - 行内编辑 `character-rel-edit-<rid>` → 表单回填 → 保存 → `PATCH`
  - 行内删除 `character-rel-delete-<rid>` → ConfirmDialog `character-rel-confirm-dialog` + `character-rel-confirm-ok` → `DELETE` → 行消失
- 断言点：
  1. 打开详情面板 → GET `/characters/{cid}/relations` 渲染列表（含 to_name/relation_type）
  2. 空态：GET 返回 [] → `character-rel-empty`
  3. 添加：点添加 → 表单 → 选对方角色+填类型+描述 → 保存 → POST body 断言 → 列表出现新行/重拉
  4. 编辑：点行内编辑 → 表单回填 → 改类型 → 保存 → PATCH body 断言 → 行更新
  5. 删除：点行内删除 → 确认框 → 确认 → DELETE 断言 → 行消失

## T2 分组区契约（面板内）
- 分组选择下拉 `character-group-select`（选项=GET /projects/{pid}/character-groups）
  - 选中 → `PATCH /characters/{cid}` body `{group_id}` → 面板显示当前分组名
  - 含「未分组」清空项（group_id=null）
- `character-group-manage`：「管理分组…」按钮 → 打开分组管理面板
  - `character-group-manage-panel`：面板容器
  - `character-group-add`：新建分组按钮 → 表单 `character-group-form`（name/description）→ POST
  - 分组行：`character-group-row-<gid>`（name + member_count + ✎/🗑）
    - 行内编辑 `character-group-edit-<gid>` → PATCH
    - 行内删除 `character-group-delete-<gid>` → ConfirmDialog `character-group-confirm-dialog` → DELETE
- 断言点：
  1. 打开详情面板 → GET /projects/{pid}/character-groups → 分组下拉渲染（含当前 group 名）
  2. 选分组 → PATCH /characters/{cid} body `{group_id}` → 面板更新
  3. 打开管理面板 → GET 列表渲染（name/member_count）
  4. 新建分组 → POST body `{name, description}` → 列表出现
  5. 编辑分组 → PATCH → 更新
  6. 删除分组 → 确认框 → DELETE → 行消失
  7. role_rank 与分组正交：等级下拉（`library-create-rank`）存在且独立，分组不合并进等级控件
