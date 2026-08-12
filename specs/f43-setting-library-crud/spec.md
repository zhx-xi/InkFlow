# F43 设定库 GUI 升级（P0+P1 批次）— 功能规格

> **Spec 版本**: v1.1（2026-08-13）
> **Spec 变更**: v1.1 — P1 批次（issue #284 第二批）：角色等级必填 + 分组标签多选 + 世界观树与分类筛选 + 世界观复制 GUI；后端极小改动（角色 extra 透传 + 复制 self_only 范围参数）；P0 遗留 E2E 编辑/删除契约补全。P0 交付物（六分类 CRUD 闭环 + 项目重命名/删除）已在 v1.0 合入（PR #301）。
> **阶段**: 0.8.0（issue #284 的 P1 批次；P2-P5 后续批次另开 PR）
> **估算**: 3-4 人天（前端为主 + 后端极小改动 + 前端测试 + E2E 补全）
> **关联 Issues**: #284（parent，GUI 升级总 issue）、#196（创建对话框先例）、#189（已保存指示先例）、#195（遮罩不关闭拍板）、#211（删除语义统一，P5 对齐）、#175（F37 跨书复制）
> **设计依据**: `design/setting-library-v2-decisions-2026-08-12.md`（D1 角色等级必填无默认 / D2 标签多选 / D3 世界观分类并入地图 + 无「全部」筛选 / D11 删除语义 / D12 悬停操作按钮）+ `design/setting-library-gui-gap-analysis-2026-08-12.md`
> **状态**: 待实现 🔲

---

## 1. 概述

### 1.1 模块定位

设定库 GUI（library.tsx 六分类 tab + projects.tsx 项目卡片）在 P0（PR #301，v1.0）已补齐六分类编辑/删除 + 项目重命名/删除的 CRUD 闭环。本批（P1）在三块能力上继续升级（决策文档 D1/D2/D3 + F37 复制端点消费）：

1. **角色等级必填**（D1）：等级字段必填、无默认值——新建/编辑角色未选等级时阻止保存（用户/Agent 显式选择）。
2. **角色分组标签**（D2）：wiki 标签式——可选 + 可创建 + 可多选（与等级正交；等级=分量，标签=归属）。
3. **世界观树 + 分类筛选**（D3）：世界观 tab 从平铺列表升级为层级树渲染（parent_id 树）+ 分类 chips 筛选（**无「全部」选项**——默认分组 + 用户/Agent 自定义自动进 chips；默认展示所有）。
4. **世界观复制 GUI**（F37 消费）：行内复制（节点±子级）+ 顶部整体复制——复制到目标项目（F37 跨书复制端点）。

**与 F42 的关系**：F42 = 0.9.0 多 Agent 配置（agent-chain-config），本 F43 = 0.8.0 设定库 GUI（issue #284 的 P0+P1）。编号按 AGENTS.md 模块类型谱系顺延。

### 1.2 范围（P1 交付物）

| # | 交付物 | 来源 |
|---|--------|------|
| 1 | 角色等级必填：角色创建/编辑对话框加等级下拉（五档：主角/重要配角/配角/场景角色/一次性角色）；未选等级阻止保存（保存按钮 disabled）；等级存 `extra.role_rank` | D1 |
| 2 | 角色分组标签：标签编辑器（已选 chips + 建议标签点击 + 输入回车创建）；多选存 `extra.groups`（string[]）；创建/编辑均支持 | D2 |
| 3 | 世界观树渲染：世界观 tab 按 parent_id 构建层级树（展开/收起）；行内操作按钮（编辑/删除）随 D12 悬停显示 | D3 |
| 4 | 世界观分类筛选：chips = 默认分组（地图/势力/功法/门派/秘境）+ 数据中出现的自定义分类自动进 chips；**无「全部」选项**；未选任何 chip = 展示所有 | D3 |
| 5 | 世界观复制 GUI：树节点行内复制（范围：本体+全部子级 / 仅本体）+ 工具栏顶部整体复制（全部）；选择目标项目 → F37 copy 端点 → 结果 toast | D4 + F37 |
| 6 | 后端极小改动：角色创建/更新 API 透传 `extra` 字段；复制端点支持 `self_only` 范围参数 | P0 spec §10 预告 + 决策文档 §4 |
| 7 | P0 遗留 E2E 补全：编辑保存 / 删除确认 / 取消 的 E2E 契约（P0 spec §14 Q3 登记为 P1 前置必补项） | P0 spec §14 Q3 |

### 1.3 边界声明

- 本批**只覆盖 P1**。P2-P5（地图工作台/大纲三级/时间线双序/30 天清理 job）不在本批，issue #284 保持 OPEN。
- **角色等级筛选 chips（原型有 rankFilter 含「全部」）不做**：任务书 P1 范围仅「必填 + 下拉 UI」，未列筛选；等级筛选与 D3 世界观分类筛选语义不同（世界观明确无「全部」，等级筛选若做需另拍板）→ 归 P2+ 候选，spec §10 登记。
- RAG 分类（extractions/runs）仍无编辑/删除（无端点），列表行不渲染操作按钮。
- 复制语义 = **值复制到目标项目**（F37）：源项目不受影响；仅本体范围依赖本批新增 `self_only` 参数（F37 原实现仅支持子树/全部）。
- 后端改动**极小**：无迁移（extra 列已存在）、无新端点（复用 F37 copy）、不改删除语义。

---

## 2. 数据模型（前端类型扩展 + 后端极小改动）

### 2.1 设定库列表项 DTO（library.tsx 现 `ListItem` 仅 id/name/title）

P0 v1.0 已扩展 `LibraryItemDTO`（见 `frontend/packages/renderer/src/components/LibraryCreateDialog.tsx`）。P1 追加字段：

```ts
interface LibraryItemDTO {
  id: string | number;
  name?: string;        // characters/world/outline
  title?: string;       // timeline/foreshadow
  personality?: string; // characters
  background?: string;  // characters
  goals?: string;       // characters
  category?: string;    // world
  content?: string;     // world
  description?: string; // outline/timeline/foreshadow
  time_display?: string; // timeline
  priority?: number;    // foreshadow
  location?: string;    // foreshadow
  // ── P1 新增 ──
  parent_id?: string | number | null;      // world：F35 父节点（null=顶层）
  extra?: Record<string, unknown>;         // characters：role_rank / groups 承载
}
```

- **角色等级存储**：`extra.role_rank`（string，五档枚举 key：`protagonist | major | minor | scene | walkon`）。旧数据无该键 = 未选等级（编辑时下拉显示占位）。
- **角色分组标签存储**：`extra.groups`（string[]，自由文本标签，去重保序）。旧数据无该键 = 无标签。
- **world 树**：`parent_id` 由后端 F35 返回（list 端点 `model_dump(mode="json")` 已含）；前端本地建树（顶层 = parent_id 为 null/缺失），不做分页树。

### 2.2 角色等级枚举（前端常量 + i18n）

```ts
/** 五档角色等级（D1 拍板；存 extra.role_rank） */
const ROLE_RANKS = [
  { key: 'protagonist', labelKey: 'lib.rank.protagonist' }, // 主角
  { key: 'major',       labelKey: 'lib.rank.major' },       // 重要配角
  { key: 'minor',       labelKey: 'lib.rank.minor' },       // 配角
  { key: 'scene',       labelKey: 'lib.rank.scene' },       // 场景角色
  { key: 'walkon',      labelKey: 'lib.rank.walkon' },      // 一次性角色
] as const;
```

- 下拉用 shadcn Select（library.tsx 已有 Select 依赖）；**必填无默认**（D1）：初始 value 空 → 保存按钮 disabled（与名称/标题必填同 gate）。
- 列表行渲染等级徽标（badge，`extra.role_rank` 映射 i18n 文案）+ 标签 chips（只读展示，`extra.groups`）。

### 2.3 标签编辑器（前端新组件 TagEditor，D2）

```ts
interface TagEditorProps {
  selected: string[];                    // 当前已选标签
  suggestions: string[];                 // 建议标签（项目内已用标签并集）
  onChange: (tags: string[]) => void;    // 变更回调（父级维护状态）
}
```

- 交互（wiki 风格，评审原型 §tagEditor）：
  - 已选标签渲染 chips（× 可移除）
  - 建议标签渲染 + 前缀按钮（点击追加，已选的不再显示）
  - 输入框回车/逗号创建新标签（strip 去空，去重）
- **建议标签来源**：当前项目角色列表 `extra.groups` 的并集（数据驱动，非硬编码）——角色列表已加载时直接聚合；角色 tab 打开创建/编辑对话框时可用。
- 建议标签空 → 只显示输入创建（无建议区）。

### 2.4 后端角色 DTO 扩展（极小改动，无迁移）

`Character` 领域实体/ORM/Repo 已有 `extra` 字段（LenientJSON 列，`default_factory=dict`），**P0 前 API body 未透传**——本批补齐（P0 spec §10「需 extra 字段读写」预告项）：

| 文件 | 变更 |
|------|------|
| `backend/src/inkflow/domain/models/character.py` | `CharacterCreate` 加 `extra: dict[str, Any] = Field(default_factory=dict)`；`CharacterUpdate` 加 `extra: dict[str, Any] \| None = None`（exclude_unset 语义：不传不修改；传 dict 整体替换） |
| `backend/src/inkflow/api/routers/characters.py` | `CharacterCreateBody` 加 `extra: dict[str, Any] = Field(default_factory=dict)`；create 调用透传 `data.extra` |
| `backend/src/inkflow/domain/services/character_service.py` | `create_character` 加 `extra: dict[str, Any] \| None = None` 参数 → `Character(extra=extra or {})`；`update_character` 已用 `model_copy(update=model_dump(exclude_unset=True))` → extra 自动生效（整体替换） |

- 校验：extra 自由字典，**后端不校验 role_rank/groups 内容**（Agent/CLI 写入路径可绕过 GUI 必填；必填是 GUI 契约，D1 原文「用户/Agent 显式选择」指 Agent 写入自带值）。
- 兼容：既有创建/更新测试契约不变（extra 缺省 = 空 dict / 不修改）。

### 2.5 复制请求 DTO 扩展（F37 极小扩展）

`WorldCopyRequest`（`backend/src/inkflow/domain/models/copy.py`）加范围参数：

```python
class WorldCopyRequest(BaseModel):
    source_project_id: uuid.UUID
    root_setting_id: uuid.UUID | None = None   # F37 既有：复制起点子树（含自身）；None=全部
    self_only: bool = False                     # P1 新增：True = 仅复制 root_setting_id 本体（不含子级）
```

- `self_only=True` 且 `root_setting_id=None` → 422（互斥校验，VALIDATION_ERROR）。
- `copy_service.copy` 加 `self_only: bool = False` 参数：复制集合确定分支（§5 算法 ③）：
  - `root + not self_only` → `list_descendants(root)`（既有语义，含自身全部后代）
  - `root + self_only` → `[root]`（仅本体；map 复制联动 `list_by_root_locations(source, [root.int], ...)` 自动收窄）
  - `root=None`（整体复制）→ `list_all_active(source)`（self_only 无意义，互斥校验拦）

### 2.6 复制 GUI 数据流（前端）

```
行内复制按钮（树节点 /data-testid=world-copy-<id>）：
  → CopyDialog：范围 chips（本体+全部子级[默认] / 仅本体）+ 目标项目 Select（排除当前项目）
  → 确认 → POST /api/v1/projects/{targetId}/world-settings/copy
           body { source_project_id: 当前项目 id, root_setting_id: <id>, self_only?: bool }
顶部整体复制按钮（工具栏 /data-testid=world-copy-all）：
  → CopyDialog：范围固定「全部」（chips 隐藏或禁用）+ 目标项目 Select
  → 确认 → POST .../copy body { source_project_id: 当前项目 id }（root_setting_id 缺省）
成功 → ok toast：创建 N 条（+ 地图 M / 跳过 S 有 warnings 时 err/warn toast 展示第一条）
```

- 目标项目列表 = `useProjectStore.projects` 过滤当前项目（不能复制到自己）。
- 复制结果 `WorldCopyResult`：`created`（条目数）/ `skipped`（同名冲突）/ `maps_created` / `pins_created` / `warnings`——toast 文案聚合（`lib.copy.result` 模板）。
- 复制成功后**不自动切换项目**；toast 提示「已复制到 {目标项目名}」。

---

## 3. API 契约（前端消费 + 后端极小改动）

### 3.1 端点总览表

P0 已消费的 PATCH/DELETE 端点不变（§3.2 请求体扩展 extra）。P1 新增消费 + 后端极小改动：

| 操作 | 端点 | 说明 |
|------|------|------|
| 角色创建（P1 扩展） | `POST /api/v1/projects/{id}/characters` | body 加 `extra`（透传，后端 DTO 扩展） |
| 角色编辑（P1 扩展） | `PATCH /api/v1/characters/{id}` | body 加 `extra`（exclude_unset：传 dict 整体替换；不传不修改） |
| 世界观复制（P1 消费 + 扩展） | `POST /api/v1/projects/{target}/world-settings/copy` | body `WorldCopyRequest` 加 `self_only`（F37 端点复用，零新端点） |
| 世界观树（P1 消费） | `GET /api/v1/projects/{id}/world-settings` | 既有响应已含 `parent_id`/`category`/`content`，前端建树（F35 已合） |

其余 P0 端点（PATCH/DELETE 六分类扁平 + 项目）零变更。

### 3.2 角色创建/更新 body（P1 扩展）

| 场景 | body | 后端模型 |
|------|------|---------|
| 角色创建 | `{ name, personality, background, goals, extra: { role_rank: 'major', groups: ['主角团','青云宗'] } }` | CharacterCreateBody（P1 加 `extra`） |
| 角色编辑 | `{ name?, personality?, ..., extra: { role_rank, groups } }` | CharacterUpdate（P1 加 `extra`，exclude_unset 整体替换） |

- **编辑时前端总是发送完整 `extra`**（role_rank + groups 合并）——避免整体替换语义下丢字段（P1 前端契约：buildBody 组装 `extra: { role_rank, groups }`）。
- 兼容：旧数据 `extra` 缺失 → 前端 `?? {}` 兜底；PATCH 不传 extra → 后端不修改（既有行为）。

### 3.3 世界观复制（P1 消费 F37 + self_only 扩展）

请求：

```http
POST /api/v1/projects/{target_project_id}/world-settings/copy
Content-Type: application/json

# 行内复制（子树，本体+全部子级）：
{ "source_project_id": "p1", "root_setting_id": "w1" }
# 行内复制（仅本体）：
{ "source_project_id": "p1", "root_setting_id": "w1", "self_only": true }
# 顶部整体复制（全部活动条目）：
{ "source_project_id": "p1" }
```

响应 `WorldCopyResult`（F37 既有）：

```json
{
  "created": [WorldSetting...],
  "skipped": ["同名条目A"],
  "maps_created": [WorldMap...],
  "pins_created": 3,
  "warnings": ["目标项目已存在同名条目「同名条目A」，已跳过"]
}
```

异常映射（F37 既有，零新增）：

| 场景 | 状态码 | detail |
|------|--------|--------|
| 目标项目不存在 | 404 | 项目不存在 |
| 源项目不存在 | 404 | 源项目不存在 |
| root 不在源项目/不存在 | 404 | 复制起点不存在 |
| `self_only=true` 且 `root_setting_id=None` | 422 | 仅本体复制必须指定复制起点 |
| 复制失败（repo 写异常） | 500 | 原样传播 |

### 3.4 错误映射（前端新增场景）

| 场景 | 前端行为 |
|------|---------|
| 复制失败（404/422/网络） | err toast（errorMessage）+ 复制对话框保持打开可重试 |
| 复制成功但有 skipped/warnings | ok toast 含创建数；warnings 非空 → 追加 warn toast 展示第一条 warning（同类去重不刷屏） |
| 复制成功无警告 | ok toast「已复制 N 条到 {目标项目名}」 |
| 等级未选保存 | 保存按钮 disabled（canSave gate），不触发请求 |
| 目标项目列表为空（单项目） | 复制按钮 disabled + tooltip「需至少两个项目」 |

## 4. CLI 命令签名

**无变更**。本批为前端 GUI 批次 + 后端 API 极小扩展（extra 透传 / self_only 参数），CLI 面不动（F7 约定 CLI 保持现状；角色 extra 的 CLI 写入经既有 `--extra` 或字段路径？——核实：CLI 角色创建无 extra 参数，本批不扩展 CLI，登记 #251 候选）。

---

## 5. 关键差异节（前端交互型 + 后端极小扩展 — 本模块类型）

### 5.1 角色等级必填（D1，P1 新增）

- 创建/编辑对话框角色分类渲染「等级」下拉（shadcn Select，`data-testid="library-create-rank"`），选项 = 五档 `lib.rank.*`。
- **必填无默认**（D1 铁律）：初始 value 空串（占位「选择等级」）；`canSave` gate 增加 `rank !== ''`——名称/标题必填 + 等级必填同时满足才可保存。
- 编辑模式预填：`editing.extra?.role_rank ?? ''`（旧数据无等级 → 占位，必须重选才能保存——D1 语义）。
- 保存 body：`extra: { role_rank: rank, groups }`（与标签合并）。
- 列表行渲染等级徽标：`data-testid="lib-rank-<id>"`，文本 = `lib.rank.<key>` 映射（缺省不渲染）。

### 5.2 角色分组标签（D2，P1 新增）

- 创建/编辑对话框角色分类渲染 TagEditor（§2.3）：已选 chips（`data-testid="lib-tag-chip-<tag>"` + × 移除）+ 建议标签按钮（`lib-tag-suggest-<tag>`）+ 输入框（`lib-tag-input`，回车/逗号创建）。
- 建议标签 = 当前项目角色 `extra.groups` 并集（列表加载后聚合，`useMemo`）。
- 保存 body：`extra: { role_rank, groups }`（groups = 去重保序 string[]）。
- 列表行渲染标签 chips（只读，`data-testid="lib-tags-<id>"`）。

### 5.3 世界观树渲染（D3，P1 新增）

- 世界观 tab 列表区改为树视图：`items`（含 `parent_id`）前端建树（顶层 = parent_id null/缺失），递归渲染 `.tree-node`/`.tree-row`。
- 展开/收起：toggle（`data-testid="world-tree-toggle-<id>"`）；有子节点才渲染 toggle（叶子不渲染）。
- 行内操作按钮（D12 悬停显示，P0 编辑/删除复用）：`lib-edit-<id>` / `lib-delete-<id>`（P0 testid 不变）+ 新增复制 `world-copy-<id>`。
- 树节点文案：名称 + 分类徽标（category 非空时）；空树 → 既有 `library-tab-empty` 空态（零变更）。
- **构建规则**：顶层按创建顺序（items 顺序）；子级按 parent_id 分组保序；孤儿（parent_id 指向不存在节点）降级为顶层（防御）。

### 5.4 世界观分类筛选（D3，P1 新增）

- 工具栏 chips（世界观 tab 专属）：默认分组 `['地图','势力','功法','门派','秘境']` + 当前列表数据中出现的自定义 `category`（去重，自动进 chips）。
- **无「全部」选项**（D3 拍板）：未选任何 chip = 展示所有（默认态）；点 chip = 筛选该分类；再点同 chip = 取消筛选（回到展示所有——toggle 语义，无需「全部」按钮）。
- 筛选交互：树视图按 category 过滤**顶层节点**（含其子树整体显示/隐藏——树结构不拆散）。
- chips：`data-testid="world-cat-filter-<category>"`，激活态 aria-pressed。

### 5.5 世界观复制 GUI（P1 新增）

- 行内复制按钮（树节点悬停）`world-copy-<id>` → CopyDialog：
  - 范围 chips：`world-copy-scope-subtree`（本体+全部子级，默认）/ `world-copy-scope-self`（仅本体）
  - 目标项目 Select：`world-copy-target`（排除当前项目）
  - 确认 `world-copy-ok` / 取消 `world-copy-cancel`（#195：遮罩不关闭）
- 顶部整体复制按钮（工具栏）`world-copy-all` → 同一 CopyDialog（范围固定「全部」，chips 隐藏）。
- 确认 → `POST /api/v1/projects/{target}/world-settings/copy`（§3.3 body）→ 结果 toast（§3.4）。
- 复制对话框为空态（无其他项目）→ 确认按钮 disabled。

### 5.6 世界观复制后端 self_only（F37 极小扩展）

```
copy(source, target, root=None, self_only=False):
  ③ 复制集合确定：
     root=None            → list_all_active(source)          （整体，既有）
     root + self_only     → [root]                           （仅本体，P1 新增）
     root + not self_only → list_descendants(root)           （子树，既有）
  ④-⑧ 其余步骤（冲突预筛/落库/地图/pins/报告）零改动——copy_set 缩小后自动适配
```

- 名称冲突预筛用 `get_by_parent_and_name(target, parent_new, name)`——仅本体复制时 parent_new=None（置顶层）。
- `self_only=True` + `root=None` → router 层 422（§3.3 表）。

### 5.7 P0 遗留 E2E 契约（P1 前置必补）

- e2e-library.spec.ts 追加（编辑保存 / 删除确认 / 取消）：真实内核 + 真实渲染，`PYTHONUTF8=1` + build renderer dist（inkflow-e2e-testing 流程）。
- 用例（§9.3 E2E 表）：编辑预填 → PATCH → 列表刷新 + 已保存指示；删除确认框 D11 文案 → DELETE → 条目消失 + toast；取消零请求。

## 6. 组织规则（i18n 键）

P0 key 表不变。P1 新增（zh.ts / en.ts 同步）：

| key | zh | en | 说明 |
|-----|----|----|------|
| `lib.rank.protagonist` | 主角 | Protagonist | 等级五档（D1） |
| `lib.rank.major` | 重要配角 | Major Character | |
| `lib.rank.minor` | 配角 | Minor Character | |
| `lib.rank.scene` | 场景角色 | Scene Character | |
| `lib.rank.walkon` | 一次性角色 | Walk-on | |
| `lib.rank.placeholder` | 选择等级 | Select rank | 下拉占位（必填提示） |
| `lib.rank.label` | 等级 | Rank | 表单 label / 列表徽标 aria |
| `lib.tags.label` | 标签 | Tags | 表单 label |
| `lib.tags.placeholder` | 输入标签，回车添加 | Type a tag, press Enter | TagEditor 输入框占位 |
| `lib.tags.suggest` | 建议 | Suggestions | 建议区标题 |
| `lib.tags.add` | + {tag} | + {tag} | 建议按钮文案（前缀 + 标签名） |
| `lib.worldCat.label` | 分类 | Category | 世界观筛选区标题 |
| `lib.copy.title` | 复制到项目 | Copy to Project | 复制对话框标题 |
| `lib.copy.scope` | 复制范围 | Copy scope | 范围区标题 |
| `lib.copy.scope.subtree` | 本体 + 全部子级 | Self + all children | 范围选项（默认） |
| `lib.copy.scope.self` | 仅本体 | Self only | 范围选项 |
| `lib.copy.target` | 目标项目 | Target project | 目标项目 Select label |
| `lib.copy.ok` | 复制 | Copy | 确认按钮 |
| `lib.copy.all` | 整体复制 | Copy All | 工具栏顶部按钮 |
| `lib.copy.result` | 已复制 {n} 条到「{name}」 | Copied {n} items to "{name}" | 成功 toast（created 数） |
| `lib.copy.skipped` | 跳过同名 {n} 条 | {n} skipped (duplicate names) | warnings 非空时追加提示 |
| `lib.copy.needTwo` | 需至少两个项目才能复制 | Need at least two projects | 空目标 disabled 提示 |

## 7. 边界情况与错误处理

P0 表（E1-E12）不变。P1 追加：

| # | 场景 | 行为 |
|---|------|------|
| E13 | 角色创建/编辑未选等级 | 保存按钮 disabled（canSave gate：名称/标题 + 等级双必填），不触发请求（D1） |
| E14 | 编辑旧角色无等级（extra 缺 role_rank） | 下拉占位「选择等级」；保存必须显式选择（D1 无默认语义） |
| E15 | 标签输入空白/重复 | strip 后空 → 不创建；重复 → 忽略（去重保序） |
| E16 | 标签建议区为空 | 仅显示输入框（无建议区） |
| E17 | 世界观树空 / 单节点 / 深链 | 空树 → 既有空态；单节点无 toggle；深链直接渲染树 |
| E18 | 孤儿节点（parent_id 指向不存在条目） | 降级为顶层渲染（防御，不报错） |
| E19 | 分类筛选无匹配 | 筛选后树空 → 显示「无该分类条目」轻提示（复用空态样式变体 `lib.worldCat.empty`） |
| E20 | 复制目标项目 = 当前项目 | 目标 Select 排除当前项目（不可选） |
| E21 | 单项目环境复制 | 复制按钮 disabled + tooltip（`lib.copy.needTwo`） |
| E22 | 复制 self_only + 无 root | 前端不可能触发（仅本体范围只在行内入口）；后端 422 兜底 |
| E23 | 复制同名冲突（skipped 非空） | ok toast 创建数 + warn toast 第一条 warning（不刷屏） |
| E24 | 复制失败（404/422/网络） | err toast + 复制对话框保持打开可重试 |
| E25 | 角色 PATCH 不带 extra（其他客户端） | 后端不修改 extra（exclude_unset 既有语义，兼容） |
| E26 | extra 非 dict（脏数据/手工写入） | 后端 LenientJSON 兜底 + 前端 `?? {}` 防御 |

## 8. 文件结构

| 操作 | 文件 | 变更 |
|------|------|------|
| MODIFY | `frontend/packages/renderer/src/pages/library.tsx` | 角色行等级徽标+标签 chips（5.1/5.2）；世界观树视图+分类筛选+复制按钮+CopyDialog 装配（5.3-5.5）；world 分类 CATS 端点复用 |
| MODIFY | `frontend/packages/renderer/src/components/LibraryCreateDialog.tsx` | 角色分类加等级下拉（5.1）+ TagEditor（5.2）；buildBody 加 extra 组装 |
| NEW | `frontend/packages/renderer/src/components/TagEditor.tsx` | 标签编辑器（2.3） |
| NEW | `frontend/packages/renderer/src/components/CopyDialog.tsx` | 复制对话框（5.5；范围 chips + 目标项目 Select） |
| MODIFY | `frontend/packages/renderer/src/i18n/zh.ts` / `en.ts` | §6 新 key 表 |
| MODIFY | `frontend/packages/renderer/src/pages/library.test.tsx` | 追加 P1 契约（§9.2 R1-R12） |
| MODIFY | `backend/src/inkflow/domain/models/character.py` | CharacterCreate/Update 加 extra（2.4） |
| MODIFY | `backend/src/inkflow/api/routers/characters.py` | CharacterCreateBody 加 extra + 透传（2.4） |
| MODIFY | `backend/src/inkflow/domain/services/character_service.py` | create_character 加 extra 参数（2.4） |
| MODIFY | `backend/src/inkflow/domain/models/copy.py` | WorldCopyRequest 加 self_only（2.5） |
| MODIFY | `backend/src/inkflow/domain/services/copy_service.py` | copy 加 self_only 参数 + 复制集合分支（5.6） |
| MODIFY | `backend/src/inkflow/api/routers/world_settings.py` | copy 端点透传 self_only + 互斥 422（2.5/3.3） |
| MODIFY | `backend/tests/unit/test_character_models.py` | extra 字段契约 |
| MODIFY | `backend/tests/unit/test_character_api.py` | 创建/更新带 extra 透传契约 |
| MODIFY | `backend/tests/unit/test_character_service.py` | create_character extra 参数契约 |
| MODIFY | `backend/tests/unit/test_copy_api.py` | self_only 请求契约 + 422 互斥 |
| MODIFY | `backend/tests/unit/test_copy_service.py` | self_only 复制集合分支契约 |
| MODIFY | `tests/e2e/e2e-library.spec.ts` | P0 遗留编辑/删除 E2E 契约（§9.3） |

> 无新前端测试文件 → ci.yml 前端 job 零登记；后端测试全部为既有文件 MODIFY → ci.yml 零登记（unit 由 `pytest tests/unit/` 自动覆盖）。

## 9. 测试策略

### 9.1 层次与工具

- **前端单元/组件契约**（Vitest + RTL，RED 批先行——F15 起 TDD 硬纪律）：本批主测试层（library.test.tsx 追加）。
- **后端单元契约**（pytest + unittest.mock.patch，RED 批同批）：extra 透传 + self_only 分支——本批后端极小改动仍需契约（F15 起前端/后端一律 RED 先行）。
- **E2E**（Playwright Electron，P0 遗留必补项）：e2e-library.spec.ts 追加编辑/删除契约（inkflow-e2e-testing 流程：`PYTHONUTF8=1` + build renderer dist）。

### 9.2 RED 契约用例（library.test.tsx 追加，R 系列）

| # | 用例 | 断言要点 |
|---|------|---------|
| R1 | 角色创建对话框渲染等级下拉 + 标签编辑器 | `library-create-rank` 存在；`lib-tag-input` 存在；无等级时 `library-create-save` disabled（仅填名称仍 disabled） |
| R2 | 选择等级后保存按钮 enabled | 填名称 + 选等级 → enabled；PATCH/POST body 含 `extra.role_rank` |
| R3 | 编辑预填等级 + 标签 | editing 带 `extra:{role_rank:'major',groups:['主角团']}` → 下拉显示「重要配角」+ chip 存在 |
| R4 | 标签建议渲染 + 点击追加 + 回车创建 | 项目角色含 groups → 建议按钮；点击建议 → chip 出现；输入回车 → 新 chip；重复输入忽略 |
| R5 | 标签移除（×） | 点 × → chip 消失；保存 body groups 不含该标签 |
| R6 | 角色保存 body 含完整 extra | POST/PATCH body `extra` = `{role_rank, groups}`（合并发送） |
| R7 | 角色列表行渲染等级徽标 + 标签 chips | `lib-rank-c1` 文本「重要配角」；`lib-tags-c1` 含标签 chips |
| R8 | 世界观树渲染（parent_id 层级） | 树节点含顶层 + 子级；toggle 展开/收起；子节点显隐 |
| R9 | 世界观分类 chips：默认分组 + 自定义自动进 | chips 含 地图/势力/功法/门派/秘境 + 数据中的自定义分类；**无「全部」chip** |
| R10 | 分类筛选 toggle：点 chip 筛选 → 再点取消 | 筛选后仅该分类顶层（含子树）；再点同 chip → 全部恢复 |
| R11 | 行内复制：按钮 → CopyDialog → POST copy body（subtree/self） | `world-copy-w1` → 选目标 → ok → `POST /api/v1/projects/p2/world-settings/copy` body 断言；toast 创建数 |
| R12 | 顶部整体复制：`world-copy-all` → body 无 root_setting_id | 工具栏按钮 → CopyDialog（无范围 chips）→ 确认 → body `{source_project_id}` |
| R13 | 复制失败 → err toast + 对话框保持；单项目 → 复制 disabled | reject → err toast + CopyDialog 仍在；projects 仅 1 个 → `world-copy-all` disabled |

### 9.3 E2E 契约（e2e-library.spec.ts 追加，P0 遗留必补）

| # | 用例 | 断言要点 |
|---|------|---------|
| E2E-E1 | 编辑保存闭环 | 内核预置角色 → 行编辑 → 预填 → 改名称 → 保存 → PATCH → 列表显示新名 + `lib-save-indicator`「已保存」 |
| E2E-E2 | 删除确认闭环 | 行删除 → `lib-confirm-dialog` D11 文案 → ok → DELETE → 条目消失 + ok toast |
| E2E-E3 | 删除取消零请求 | 取消/Esc → 关闭 + 条目仍在 |

### 9.4 覆盖率

- 前端：library.test.tsx 追加 ≈13 用例（R1-R13）；TagEditor/CopyDialog 由消费方契约覆盖（不单列，对齐 P0 ConfirmDialog 先例）。
- 后端：character models/api/service + copy api/service 各追加 extra/self_only 断言；目标模块 ≥80% 保持。

## 10. 不在范围内

P0 表更新（已入范围的 P1 行移除）+ P1 新行：

| 项 | 归属 | 原因 |
|----|------|------|
| ~~角色等级必填 + 标签多选（D1/D2）~~ | ✅ 本批 P1 | 已入范围（§2.2/§2.3/§5.1/§5.2） |
| ~~世界观树/分类筛选/复制 GUI（D3/D4）~~ | ✅ 本批 P1 | 已入范围（§5.3-§5.5） |
| ~~世界观 reparent/复制交互~~ | ✅ 本批 P1 | 复制 GUI 已入范围；reparent（拖拽/改挂）仍不在——后端 `?reparent_to=` 端点已就绪但 GUI 交互未拍板，归 P2+ 候选 |
| 角色等级筛选 chips（原型 rankFilter） | P2+ 候选 | 任务书 P1 范围未列；与 D3 分类筛选语义不同，需另拍板（含「全部」与否） |
| 标签管理页（增删改标签本体） | 无归属 | 标签是角色 extra 数据，无独立实体；管理页需新后端模型，Phase 2+ |
| 地图工作台（D5-D7） | P2 批次 | F36 资产 + pins 扩展 |
| 大纲三级 + 章关联（D8/D9） | P3 批次 | level 字段 + 章节 FK |
| 时间线双序 + 两级检查（D10） | P4 批次 | check 端点消费 + 双视图 |
| 删除 30 天清理 job（#211 对齐） | P5 批次 | 后端清理任务 |
| RAG 分类编辑/删除 | 无归属 | 无 PATCH/DELETE 端点（extractions/runs 为运行记录） |
| 项目硬删除/恢复（force/restore） | 无归属 | GUI 不暴露危险操作，软删语义由确认文案表达（D6） |
| CLI 设定库 CRUD / 角色 extra CLI 写入 | #251 | 另行排期 |
| ~~E2E 编辑/删除契约~~ | ✅ 本批 P1 | P0 遗留必补项已入范围（§9.3） |

---

## 11. 依赖关系

| 依赖 | 状态 | 说明 |
|------|------|------|
| #284（设定库 GUI 升级总 issue） | ✅ OPEN | 本批为 P1 子批次；PR body `Part of #284` + 注明 P1 完成 / P2-P5 未做（spec §13 M8 门禁；**禁用 `Closes #284`**——P2-P5 未完成不得关 issue） |
| P0 批次（PR #301） | ✅ 已合 | 编辑/删除/保存指示/ConfirmDialog 基座（v1.0 交付物，本批复用） |
| F35 世界观树（parent_id） | ✅ 已合 | 后端 parent_id/ancestors/descendants + list 参数（前端纯渲染） |
| F37 跨书复制 | ✅ 已合 | copy 端点/服务（本批消费 + self_only 极小扩展） |
| #196 创建对话框 | ✅ 已合 | LibraryCreateDialog 双模式基座（本批加等级/标签字段） |
| #189 已保存指示模式 | ✅ 已合 | 编辑保存反馈复用（P0 已接） |
| #195 遮罩不关闭拍板 | ✅ 已合 | CopyDialog 遵守 |
| #211 删除语义统一 | ⏳ OPEN | P5 批次对齐；本批确认文案沿用 D11（P0 已接） |
| 角色 extra 列（LenientJSON） | ✅ 已有 | 无迁移（domain/ORM/repo 已映射，仅 API 透传补齐） |

---

## 12. 关键架构决策记录

P0 表（D-1..D-6）不变。P1 追加：

| # | 决策 | 方案 | 备选否决 |
|---|------|------|---------|
| D-7 | 角色等级/标签存 `extra` JSON（`role_rank`/`groups`）而非新列/新表 | 决策文档 D1/D2 拍板；extra 列已存在（LenientJSON）零迁移；标签是自由文本集合，SQL 列/关联表对 GUI 无增益 | 新表 character_tags（需迁移 + 联表查询 + 删除语义联动，YAGNI）；等级独立列（枚举固定但迁移成本高，extra 已预留） |
| D-8 | 复制「仅本体」= `WorldCopyRequest.self_only` 参数（F37 扩展）而非新端点 | 复制集合分支最小改（`[root]` vs `list_descendants`）；DTO 向后兼容（缺省 False）；零新路由 | 新端点 `copy-self`（重复 F37 编排）；GUI 只做子树/整体（丢「仅本体」范围，与原型评审不符） |
| D-9 | 复制目标项目 = F37 跨项目语义（复制到其他项目），行内/顶部都走同一 CopyDialog | 决策文档 D4「复制到项目」；后端零新端点；源项目不受影响（值复制） | 项目内复制副本（F37 无此语义，同名冲突必然跳过——需新后端逻辑） |
| D-10 | 分类筛选无「全部」选项 + toggle 取消（未选 = 展示所有） | D3 拍板「无全部」；默认态即全量，点选筛选，再点取消回默认——交互闭环无需「全部」按钮 | 原型「全部」chip（D3 明确否决）；单选不可取消（无返回默认态路径，体验残缺） |
| D-11 | 世界观分类 chips = 默认分组 + 数据驱动自定义（非后端 categories 端点） | 列表 items 已含 category，`useMemo` 聚合零请求；自定义分类自动进 chips（D3「自动进筛选」） | 调 `/world-settings/categories` 汇总端点（多 1 请求；数据与列表可能不同步） |
| D-12 | 角色等级必填 = 前端 canSave gate（后端不校验 extra 内容） | D1「未选阻止保存」是 GUI 交互语义；后端 extra 自由字典（Agent/CLI 写入自带值，不该被 GUI 规则拦截） | 后端枚举校验（会拒绝 Agent/CLI 非五档值，破坏 extra 开放语义） |
| D-13 | 标签建议来源 = 当前项目角色 extra.groups 并集（数据驱动） | 原型 ALL_CHAR_TAGS 硬编码仅演示；数据驱动随项目增长自动丰富 | 全局词表（跨项目污染）；设置页维护（无实体可存） |

---

## 13. 验收标准

| # | 验收项 | 验证方式 |
|---|--------|---------|
| M1 | f43 spec v1.1 合入（与实现同 PR；头部版本行 + Spec 变更行 + P1 章节 + 跨节同步） | PR diff 核对 + `git log origin/main -- specs/f43-setting-library-crud/spec.md` |
| M2 | RED 批全 FAIL 有实证（前端 R1-R13 + 后端 extra/self_only 契约；测试输出存档） | 测试输出存档（RED 日志） |
| M3 | 前端测试全绿（既有 + R1-R13） | `pnpm --filter renderer test` 全绿（GREEN 后本地实证） |
| M4 | 角色等级必填拦截：创建/编辑未选等级保存按钮 disabled；选择后 enabled + body 含 extra.role_rank | library.test.tsx R1/R2/R3 + 手动核对 |
| M5 | 标签多选/创建生效：建议点击 + 回车创建 + 移除；保存 body extra.groups；列表行徽标/chips 渲染 | library.test.tsx R4-R7 + 手动核对（持久化：保存后重开对话框预填） |
| M6 | 世界观树渲染 + 分类筛选（无「全部」）+ 复制（行内±子级 / 顶部整体） | library.test.tsx R8-R13 + 手动核对 |
| M7 | P0 遗留 E2E 补全（编辑保存/删除确认/取消）通过 | `PYTHONUTF8=1` + build renderer dist + `pnpm --filter inkflow-electron test:e2e e2e-library` 输出 |
| M8 | 后端极小改动契约全绿（extra 透传 + self_only 分支） | `backend/.venv pytest backend/tests/unit/test_character_*.py test_copy_*.py` |
| M9 | PR 合入 + CI 全绿（statusCheckRollup 对照）；PR body `Part of #284` + 注明 P1 完成 / P2-P5 未做 | gh pr checks 轮询 + gh pr view |
| M10 | issue #284 保持 OPEN（P2-P5 未做，注明进度） | gh issue view 284 |

---

## 14. 待澄清问题

无阻塞级待澄清——本批交互/存储/范围全部由任务书 + 决策文档 D1/D2/D3/D4 + F37/F35 既有实现指定。以下为已拍板留痕：

- **Q1（✅ 已确认，决策文档 D1）**：角色等级必填无默认（用户/Agent 显式选择），未选阻止保存。正文 §2.2/§5.1/E13/E14 已落实。
- **Q2（✅ 已确认，决策文档 D2）**：标签 wiki 式（可选 + 可创建 + 可多选，与等级正交），存 `extra.groups`。正文 §2.3/§5.2 已落实。
- **Q3（✅ 已确认，决策文档 D3）**：世界观分类 = 默认分组（地图/势力/功法/门派/秘境）+ 自定义自动进 chips；**无「全部」选项**；默认展示所有。正文 §5.3/§5.4 已落实。
- **Q4（✅ 已确认，任务书 P1 范围）**：复制 GUI 消费 F37 端点（跨项目值复制）+ 本批 `self_only` 极小扩展；「仅本体」范围随行内复制提供。正文 §2.5/§3.3/§5.5/§5.6 已落实。
- **Q5（✅ 已确认，P0 spec §14 Q3 登记）**：编辑/删除 E2E 契约 = P1 前置必补项，本批补全。正文 §5.7/§9.3/M7 已落实。

---

## 跨节同步声明（v1.1 修订 11 处必查）

| # | 位置 | 同步点 |
|---|------|--------|
| 1 | 头部 | 版本 v1.1 + Spec 变更行 + 估算 3-4 人天 + 状态待实现 |
| 2 | §1.2/§1.3 | P1 交付物表 + 边界声明（等级筛选不做/复制跨项目/E2E 必补） |
| 3 | §2.1 | LibraryItemDTO 加 parent_id/extra |
| 4 | §2.4/§2.5 | 后端 DTO 扩展（extra/self_only） |
| 5 | §3 | API 表 + body 示例 + 异常映射 |
| 6 | §5 | 关键差异节 5.1-5.7（新增 7 小节） |
| 7 | §6 | i18n key 表（22 个新 key） |
| 8 | §7 | E13-E26 边界表 |
| 9 | §8 | 文件结构 18 行（前端 6 + 后端 6 + 测试 6） |
| 10 | §9 | RED 契约 R1-R13 + E2E 表 |
| 11 | §10/§11/§12/§13/§14 | 不在范围更新 / 依赖表 / D-7..D-13 / M1-M10 / Q1-Q5 |

---

*（Spec v1.1 完。实现阶段：Plan → RED（前端 R1-R13 + 后端 extra/self_only 契约全 FAIL 实证存档）→ Codex GREEN（唯一编码执行者）→ QA（前端全绿 + E2E + 手动核对）→ PR `feat(gui): 设定库 P1...` body `Part of #284` + 进度注明，**禁用 `Closes #284`**。）*
