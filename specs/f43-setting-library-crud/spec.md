# F43 设定库 GUI 升级（P0+P1+P2+P3+P4 批次）— 功能规格

> **Spec 版本**: v1.3（2026-08-13）
> **Spec 变更**: v1.3 — P3+P4 批次（issue #284 第四/五批）：大纲三级结构（整体/卷/章，level 字段标记 + parent_id 层级）+ 章关联写作章节（chapter_id → chapters）+ 时间线双序（叙事序/世界序切换）+ 两级检查（工具栏整体检查 + 事件行内单事件检查）；后端扩展（outlines 加 level/parent_id/chapter_id 三列 + 单事件检查端点）。P2 交付物（地图工作台）已在 v1.2 合入（PR #311）。
> **阶段**: 0.8.0（issue #284 的 P3+P4 批次；P5 后续批次另开 PR）
> **估算**: 5-8 人天（前后端混合：后端扩展 ~2-3 + 前端大纲三级树/时间线双序 ~3-5 + 测试）
> **关联 Issues**: #284（parent，GUI 升级总 issue）、#174（F36 地图）、#3（F3 章节，章关联目标）、#196（创建对话框先例）、#189（已保存指示先例）、#195（遮罩不关闭拍板）、#211（删除语义统一，P5 对齐）
> **设计依据**: `design/setting-library-v2-decisions-2026-08-12.md`（D8 大纲三级 / D9 章关联 / D10 时间线双序+两级检查）+ `specs/f11-outline-service/spec.md`（outlines 数据基础）+ `specs/f12-timeline-service/spec.md`（双序/check 数据基础）
> **状态**: 待实现 🔲

---

## 1. 概述

### 1.1 模块定位

设定库 GUI（library.tsx 六分类 tab + projects.tsx 项目卡片）通过 issue #284 分 P0-P5 批次升级。P0（PR #301，v1.0）补齐六分类编辑/删除 + 项目重命名/删除 CRUD 闭环；P1（PR #306，v1.1）补齐角色等级必填（D1）+ 分组标签多选（D2）+ 世界观树/分类筛选（D3）+ 世界观复制（F37）；P2（PR #311，v1.2）落地地图工作台（D4-D7）。本批（P3+P4，v1.3）在大纲与时间线方向继续升级（决策文档 D8/D9/D10）：

1. **大纲三级结构**（D8）：整体→卷→章→情节点（`level` 字段标记 + `parent_id` 层级），各层展开/收起/新增。
2. **章关联写作章节**（D9）：章关联实际写作章节（`chapter_id`）；已关联显示 📎 徽标，未关联显示「关联章节」按钮。
3. **时间线双序**（D10）：叙事序/世界序切换视图。
4. **两级检查**（D10）：工具栏整体一致性检查 + 事件行内单事件检查。

**与 F42 的关系**：F42 = 0.9.0 多 Agent 配置（agent-chain-config），本 F43 = 0.8.0 设定库 GUI（issue #284 的 P0-P4）。编号按 AGENTS.md 模块类型谱系顺延。

### 1.2 范围（P3+P4 交付物）

P0（六分类 CRUD 闭环，PR #301）+ P1（角色等级/标签/世界观树/复制，PR #306）+ P2（地图工作台，PR #311）已合入。本批 P3+P4 在大纲与时间线方向升级（决策文档 D8/D9/D10 + F11/F12 后端扩展）：

| # | 交付物 | 来源 |
|---|--------|------|
| 1 | 地图入口（D4/D5）：世界观 tab = 地图工作台——世界观树节点挂接地图视图（点击地图节点切换画布） | D4 |
| 2 | 三底图共存（D5）：底图工具栏（简图/图片/AI）+ 底图模式切换；**pin 独立叠加层，切换底图不影响标记** | D5 |
| 3 | 简图模式（D5）：方框/椭圆/文字可拖拽（shapes 存 `maps.extra` JSON）；工具栏 ＋方框/＋椭圆/＋文字 | D5 |
| 4 | 图片模式（D5）：复用 F36 图片上传（map_asset_store，image_path）+ 换图 | D5 + F36 |
| 5 | AI 模式（D5）：**占位后置**（「即将推出」禁用态），不做 AI 生成 | D5 |
| 6 | 一图多标记（D6）：点击画布任意位置添加标记；类型=地点/角色/事件/其他；关联设定实体（角色/事件/地点，可搜索）；pin 列表可编辑/删除 | D6 |
| 7 | 面包屑导航（D7）：设定库 / 世界观 / 地图视图 / {地图名}，逐级可回跳 | D7 |
| 8 | 后端扩展：`map_pins` 加 `type` 枚举 + `ref_id` 关联（角色/事件/地点）；`maps` 加 `bg_source` + `extra`（shapes）；简图地图创建（无图片） | 决策文档 §3/§4 |
| 9 | 大纲三级结构（D8）：整体→卷→章→情节点，`level` 字段标记（overall/volume/chapter）+ `parent_id` 层级 | D8 |
| 10 | 章关联（D9）：章关联实际写作章节（`chapter_id` → chapters）；已关联显示 📎 徽标，未关联显示「关联章节」按钮（选择器后置） | D9 |
| 11 | 时间线双序（D10）：叙事序/世界序切换视图 | D10 |
| 12 | 两级检查（D10）：工具栏整体检查 + 事件行内单事件检查 | D10 |
| 13 | 后端扩展：`outlines` 加 `level`/`parent_id`/`chapter_id` 三列 + 迁移；单事件检查端点 `GET /timeline/events/{id}/check` | 决策文档 §3/§4 |

### 1.3 边界声明

- 本批**覆盖 P3+P4**（大纲三级 + 章关联 + 时间线双序 + 两级检查）。P5（30 天清理 job）不在本批，issue #284 保持 OPEN（PR body `Part of #284`，禁用 `Closes #284`）。
- **AI 底图不做**（D5 拍板「占位后置」）：仅渲染「即将推出」禁用态，无生成逻辑、无 LLM 调用。
- **简图地图创建（无图片）**：需放宽 `maps.image_path` NOT NULL 语义（简图模式无图）。SQLite ALTER 无法改 NOT NULL 约束 → 简图模式 `image_path` 存空串 `""`，service 按 `bg_source` 校验（image 模式必须有图，shape 模式可空）。
- **pin 关联实体校验**：`type=role` → `ref_id` 指向同项目活动角色；`type=event` → `ref_id` 指向同项目活动事件；`type=location` → 沿用 F36 `location_id`（指向同项目活动地点）；`type=other` → 无关联（纯注释 pin）。跨项目/软删实体 → 422。
- 地图创建仍复用 F36 端点（本批扩展 `bg_source` 参数支持简图）；**不新增绘图引擎**（形状是简单绝对定位 div，非 SVG 笔刷/图层）。
- 角色等级筛选 chips（P1 §10 登记）仍归 P2+ 候选，本批不做。

- **大纲三级 level 默认值（向后兼容）**：旧平铺大纲（含情节点）默认 `level=chapter`（孤立章，parent_id 空，渲染时降级为顶层）——情节点天然挂其下（零迁移，D8「章→情节点」严格成立）。用户之后可新建 overall/volume 把孤立章挂入层级。
- **三级层级约束（严格）**：`overall` 无 parent；`volume` 只能 parent=`overall`；`chapter` 只能 parent=`volume`（或 parent 空 = 孤立章）。非法层级/跨项目/不存在 parent → 422。
- **章关联约束（D9）**：仅 `level=chapter` 可关联写作章节（`chapter_id`）；关联章节须同项目且存在，跨项目/软删 → 422；`chapter_id` 可清除（置空）。「关联章节」按钮的**选择器后置**（D9 拍板）——本批仅渲染按钮 + 📎 徽标，章节选择器交互后置。
- **情节点挂载**：情节点仍挂 `outline_id`（不关心 level，历史兼容）；新建情节点仅在 `level=chapter` 节点（前端渲染「＋情节点」按钮仅 chapter 层级）。
- **时间线双序数据已就绪**：F12 已含 `time_value`（世界序）+ `narrative_position`（叙事序）+ `TimelineView` 双视图端点——本批仅前端消费双视图切换，零后端字段新增。
- **单事件检查语义**：单事件检查 = 该事件与其叙事相邻事件的逆序对（作为 prev/next 的 order_conflict/flashback/flashforward）；`time_value` 为 None 的事件不参与检查（返回 `checked=false`）。

---

## 2. 数据模型（前端类型扩展 + 后端加列扩展）

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

### 2.7 地图工作台后端扩展（P2，F36 增量）

P0/P1 的后端改动（角色 extra / 复制 self_only）零迁移。P2 需 **F36 maps/map_pins 表加列**——这是本批相对前两批的质变（加列迁移 + DTO/服务/路由扩展）。

#### 2.7.1 map_pins 扩展：type 枚举 + ref_id 关联（D6）

F36 `map_pins` 现仅 `location_id`（关联地点）。D6 需四类标记 + 关联角色/事件/地点。扩展：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `type` | str | NOT NULL, DEFAULT 'location' | 枚举 `location`/`role`/`event`/`other`（旧数据默认 location） |
| `ref_id` | int \| NULL | 可空，已索引 | 关联实体主键（int，与 ORM 层一致）；`type` 推导目标表 |

**关联语义**（A-1 落地，`location_id` 保留为 `type=location` 的兼容别名——F36 既有端点/CLI/测试零破坏）：

| type | 关联列 | 目标表 | 校验 |
|------|--------|--------|------|
| `location` | `location_id`（F36 既有） | world_settings | 同项目活动地点（F36 既有校验链） |
| `role` | `ref_id` | characters | 同项目活动角色（本批新增） |
| `event` | `ref_id` | timeline_events | 同项目活动事件（本批新增） |
| `other` | 两者均 NULL | — | 纯注释 pin，无关联 |

- `ref_id` 是**领域 UUID 映射的 int 主键**（沿用 F1 `_to_int_id` 模式），存 ORM 层 int。
- `role`/`event` 关联校验需 `CharacterRepositoryProtocol` / `TimelineRepositoryProtocol` 注入 `MapService`（本批 MapService 依赖扩展：`character_repo` / `timeline_repo` 可选注入，默认 None 向后兼容——无注入时跳过校验仅透传，防破坏既有 F36 测试）。
- `type=location` 时 `ref_id` 为 NULL（用 location_id）；`type=role/event` 时 `location_id` 为 NULL（用 ref_id）。不双列并存。

#### 2.7.2 maps 扩展：bg_source + extra（shapes 存储，D5）

F36 `maps` 现仅 `image_path`（NOT NULL）。D5 三底图共存需底图模式字段 + 简图形状存储。扩展：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `bg_source` | str | NOT NULL, DEFAULT 'image' | 枚举 `shape`/`image`/`ai`（旧数据默认 image） |
| `extra` | JSON | NOT NULL, DEFAULT `{}` | LenientJSON；存简图形状 `{"shapes": [...]}` |
| `image_path` | str | NOT NULL（语义放宽，非约束变更） | shape 模式存空串 `""`；image 模式必填（SQLite 无法 ALTER 改 NOT NULL，见 §1.3） |

**shapes 结构**（简图模式，`extra.shapes`）：

```ts
interface MapShape {
  id: string;                 // 前端生成唯一 id（如 's_<timestamp>'）
  type: 'rect' | 'ellipse' | 'text';
  x: number; y: number;       // 相对画布百分比 0-100
  w?: number; h?: number;     // rect/ellipse 的宽高（百分比）；text 无
  label: string;              // 显示文本
}
```

- `bg_source` 决定画布渲染：`shape` → shapes 数组；`image` → image_path 图片；`ai` → 占位。
- **pin 独立叠加层**（D5 核心契约）：pins 存独立表 `map_pins`，与 bg_source/shapes 正交——切换底图只改 `maps.bg_source`，pins 列表零影响。
- `bg_source` 三态是**互斥展示**，非数据互斥：切到 shape 不删 image_path，切到 image 不删 shapes（都可回切）。AI 是占位态（不落任何数据）。

#### 2.7.3 迁移（database.py `ensure_*_column` 模式）

沿用 F35 `ensure_world_parent_id_column` 幂等模式，新增 `ensure_map_columns(conn)`：

```text
① PRAGMA table_info(maps) → 无 bg_source → ALTER TABLE maps ADD COLUMN bg_source VARCHAR(16) DEFAULT 'image'
② PRAGMA table_info(maps) → 无 extra → ALTER TABLE maps ADD COLUMN extra JSON（LenientJSON fallback {}）
③ PRAGMA table_info(map_pins) → 无 type → ALTER TABLE map_pins ADD COLUMN type VARCHAR(16) DEFAULT 'location'
④ PRAGMA table_info(map_pins) → 无 ref_id → ALTER TABLE map_pins ADD COLUMN ref_id INTEGER
```

- 表不存在（全新环境）→ no-op，等 `create_all` 建新表（ORM 已含新列）。
- `ensure_map_columns` 在 lifespan `create_tables()` 后调用（对齐 F35 接线）。

#### 2.8 大纲三级 + 章关联后端扩展（P3，F11 加列）

F11 `outlines` 现仅平铺（name/description/sort_order/extra），情节点挂 `outline_id`。D8 三级结构 + D9 章关联需加三列：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `level` | str | NOT NULL, DEFAULT 'chapter' | 枚举 `overall`/`volume`/`chapter`（旧数据默认 chapter = 孤立章） |
| `parent_id` | int \| NULL | 可空，自引用 FK→outlines.id（SET NULL），已索引 | 父大纲：volume→overall、chapter→volume；None = 顶层/孤立章 |
| `chapter_id` | int \| NULL | 可空，FK→chapters.id（SET NULL），已索引 | 章关联实际写作章节（仅 level=chapter 可设） |

**层级校验（严格，决策点 2.A）**：

| 场景 | 校验 |
|------|------|
| level 非法（非 overall/volume/chapter） | 422（OutlineServiceError 子类） |
| overall + parent_id 非空 | 422（overall 不允许挂父） |
| volume + parent 非 overall（同项目） | 422（卷只能挂整体） |
| chapter + parent 非 volume（同项目） | 422（章只能挂卷）；parent 空 = 孤立章（合法） |
| chapter_id 非空且 level ≠ chapter | 422（仅章可关联章节） |
| chapter_id 指向不存在/跨项目/软删章节 | 422 |

**Outline 领域实体扩展**（`domain/models/outline.py`）：

```python
class Outline(BaseModel):
    # ... 既有字段 ...
    level: str = "chapter"                    # P3：overall/volume/chapter
    parent_id: uuid.UUID | None = None        # P3：父大纲
    chapter_id: uuid.UUID | None = None       # P3：关联写作章节（仅 chapter）
```

**OutlineCreate/Update 扩展**（字段 + 校验同上表）；`OutlineUpdate.parent_id`/`chapter_id` 传 `""` = 清除（置 None，对齐 PlotPointUpdate.arc_id 先例）。

**ORM 加列**（`infrastructure/database/models/outline.py`）：

```python
level: Mapped[str] = mapped_column(String(16), nullable=False, default="chapter")
parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("outlines.id", ondelete="SET NULL"), nullable=True, index=True)
chapter_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True)
```

**迁移**（`database.py` `ensure_outline_columns(conn)`，沿用 F35/F43-P2 幂等模式）：

```text
① PRAGMA table_info(outlines) → 无 level → ALTER ADD COLUMN level VARCHAR(16) DEFAULT 'chapter'
② → 无 parent_id → ALTER ADD COLUMN parent_id INTEGER
③ → 无 chapter_id → ALTER ADD COLUMN chapter_id INTEGER
```

表不存在 → no-op，等 `create_all` 建新表。在 `create_tables()` 后接线（与 ensure_map_columns 同点）。

**校验依赖注入**：`OutlineService.__init__` 加 `chapter_repo: ChapterRepositoryProtocol | None = None`（可选注入，校验 chapter_id 用）；`deps.py` 装配传真实 repo，既有测试构造不传 → 跳过 chapter 校验（向后兼容，对齐 MapService 先例）。parent 层级校验用 `repository.get(parent_id)` 查父大纲 level。

#### 2.9 时间线单事件检查（P4，零字段新增）

F12 双序数据（time_value/narrative_position）+ `TimelineView` + `check_consistency` 已就绪。本批仅新增**单事件检查**（决策点 3.A）：

**EventCheckReport 响应模型**（`domain/models/timeline.py` 新增）：

```python
class EventCheckReport(BaseModel):
    event_id: uuid.UUID
    checked: bool                          # 该事件 time_value 是否非 None（None = 不参与检查）
    consistent: bool                       # conflicts 为空
    conflicts: list[TimelineConflict] = []   # 该事件参与的 order_conflict
    flashbacks: list[TimelineConflict] = []  # 该事件参与的 flashback/flashforward
```

**check_event 方法**（`TimelineService` 新增）：取该事件 + 其叙事相邻事件（prev/next），复用相邻对扫描分类逻辑，返回该事件作为 prev 或 next 的逆序对。

- 复用 `check_consistency` 的相邻对分类（§5.3 同款）：`prev.time > next.time` 且 next 标记 flashback → flashbacks；prev 标记 flashforward → flashbacks；否则 conflicts。
- 单事件最多参与两对（与 prev、与 next），返回这两对中该事件涉及的全部冲突。

---

## 3. API 契约（前端消费 + 后端扩展）

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

### 3.5 地图工作台 API（P2，F36 端点扩展）

P2 前端消费 F36 maps/map_pins 端点（§3.1 表不变），后端 DTO 扩展：

#### 3.5.1 pin 端点扩展（type + ref_id）

| 操作 | 端点 | 变更 |
|------|------|------|
| 添加 pin（扩展） | `POST /api/v1/maps/{id}/pins` | body `MapPinCreate` 加 `type`（默认 location）+ `ref_id`（可空） |
| 更新 pin（扩展） | `PATCH /api/v1/map-pins/{id}` | body `MapPinUpdate` 加 `type` + `ref_id`（exclude_unset 语义） |
| 列表（消费） | `GET /api/v1/maps/{id}/pins` | 响应 `MapPin` 加 `type` + `ref_id` 字段 |

**MapPinCreate 扩展**：

```python
class MapPinCreate(BaseModel):
    location_id: uuid.UUID | None = None      # F36 既有：type=location 用
    ref_id: uuid.UUID | None = None           # P2 新增：type=role/event 用
    type: str = "location"                    # P2 新增：location/role/event/other
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    label: str = ""
```

**body 示例**：

```json
// type=role（关联角色）
POST /api/v1/maps/9/pins
{"type": "role", "ref_id": "c7...", "x": 42.5, "y": 68.0, "label": "苏云舟"}

// type=location（F36 既有语义，向后兼容）
{"type": "location", "location_id": "7", "x": 30.0, "y": 40.0, "label": "清河县城"}
```

#### 3.5.2 maps 端点扩展（bg_source + extra）

| 操作 | 端点 | 变更 |
|------|------|------|
| 创建地图（扩展） | `POST /api/v1/projects/{pid}/maps` | Form 加 `bg_source`（默认 image）；bg_source=shape 时 file 可选（无图，image_path 存空串） |
| 更新地图（扩展） | `PATCH /api/v1/maps/{id}` | body `WorldMapUpdate` 加 `bg_source` + `extra`（shapes 整体替换语义） |

**WorldMapUpdate 扩展**：

```python
class WorldMapUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    root_location_id: uuid.UUID | None = None   # F36 既有
    bg_source: str | None = None                 # P2 新增：shape/image/ai
    extra: dict | None = None                    # P2 新增：{"shapes": [...]}
```

- `bg_source=shape` 创建地图：file 缺省 → image_path 存空串 `""`；`bg_source=image` 且无 file → 422（MapAssetError 语义扩展）。
- shapes 保存走 `PATCH /maps/{id}` body `extra: {shapes: [...]}`（整体替换 shapes 数组）。

#### 3.5.3 异常映射（P2 新增）

| 异常 | 状态码 | detail |
|------|--------|--------|
| MapPinRefNotFoundError | 422 | pin 关联角色/事件不存在或不在同一项目 |
| MapBgSourceError | 422 | bg_source 非法 / image 模式缺图片 |
| 既有 F36 异常（§3.3 F36 spec） | 404/422/500 | 不变 |

#### 3.6 大纲端点扩展（P3，level/parent_id/chapter_id 透传）

| 操作 | 端点 | 变更 |
|------|------|------|
| 创建大纲（扩展） | `POST /api/v1/projects/{pid}/outlines` | body `OutlineCreateBody` 加 `level`（默认 chapter）+ `parent_id` + `chapter_id` |
| 更新大纲（扩展） | `PATCH /api/v1/outlines/{id}` | body `OutlineUpdate` 加 `level` + `parent_id` + `chapter_id`（exclude_unset；`""` 清除） |
| 列表/详情（消费） | `GET /projects/{pid}/outlines`、`GET /outlines/{id}` | 响应 `Outline` 加 `level` + `parent_id` + `chapter_id` |

**OutlineCreateBody 扩展**：

```python
class OutlineCreateBody(BaseModel):
    name: str
    description: str = ""
    sort_order: int = 0
    level: str = "chapter"                    # P3：overall/volume/chapter
    parent_id: uuid.UUID | None = None        # P3：父大纲
    chapter_id: uuid.UUID | None = None       # P3：关联章节
```

**body 示例**：

```json
// 创建整体大纲
POST /api/v1/projects/p1/outlines
{"name": "初入江湖", "level": "overall", "description": "..."}

// 在整体下创建卷
{"name": "第一卷", "level": "volume", "parent_id": "<overall-id>"}

// 在卷下创建章 + 关联写作章节
{"name": "试剑大典", "level": "chapter", "parent_id": "<volume-id>", "chapter_id": "<chapter-id>"}
```

**异常映射（P3 新增）**：

| 异常 | 状态码 | detail |
|------|--------|--------|
| OutlineLevelError | 422 | level 非法 |
| OutlineHierarchyError | 422 | 层级约束违反（overall 挂父 / volume 非挂 overall / chapter 非挂 volume） |
| OutlineChapterRefError | 422 | chapter_id 仅 chapter 可设 / 章节不存在或跨项目 |

#### 3.7 时间线单事件检查端点（P4 新增）

| 操作 | 端点 | 说明 |
|------|------|------|
| 单事件检查（新增） | `GET /api/v1/timeline/events/{event_id}/check` | 返回 `EventCheckReport`（该事件参与的所有逆序冲突） |

- 事件不存在 → 404「事件不存在」。
- `time_value` 为 None → `checked=false`，conflicts/flashbacks 均空，consistent=true（不参与检查，非冲突）。
- 复用 `TimelineConflict` 模型（§2.6），零新冲突类型。

响应示例：

```json
{
  "event_id": "t5",
  "checked": true,
  "consistent": false,
  "conflicts": [{"conflict_type":"order_conflict","prev":{...},"next":{...},"message":"..."}],
  "flashbacks": []
}
```

## 4. CLI 命令签名

**无变更**。本批为前端 GUI 批次 + 后端 API 扩展（pin type/ref_id 透传、maps bg_source/extra 透传），CLI 面不动（F7 约定 CLI 保持现状；pin type/ref_id 的 CLI 写入经既有 `--location` 路径不变，新增 `--type`/`--ref` 登记 #251 候选，本批不做）。

---

## 5. 关键差异节（前端交互型 + 后端扩展 — 本模块类型）

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

### 5.8 地图工作台布局（D4/D5/D7，P2 新增）

世界观 tab 挂接地图视图，布局（参照原型 §3，`data-testid="map-workbench"`）：

```text
┌ 面包屑: 设定库 / 世界观 / 地图视图 / 🗺 {当前地图}   [右: 尺度 · N 个标记]
├─────────────────────────────┬────────────────────────────────────┐
│ 左栏: 世界观树（250px）      │ 右栏: 底图工具栏（简图/图片/AI +   │
│  · 🗺 地图节点 + pin 数徽标  │        ＋方框/＋椭圆/＋文字）        │
│  · 分类徽标/尺度/复制/编辑/删│ 地图画布（常驻，点击添加标记）      │
│  · 点击地图节点切换画布      │ pin 列表（类型徽标+名称+关联+操作） │
└─────────────────────────────┴────────────────────────────────────┘
```

- **入口**：世界观 tab 从「树列表」升级为「地图工作台」——左侧世界观树保留（P1 树渲染），右侧新增画布 + pin 列表。
- **地图节点识别**：世界观树节点若 `root_location_id` 挂有地图（前端拉 `GET /projects/{pid}/maps` 建 `location_id → map` 映射），渲染 🗺 图标 + pin 数徽标（`data-testid="world-map-badge-<id>"`）。
- **切换画布**：点击地图节点 → `setActiveMapId` → 画布渲染该地图的底图 + pins。
- **无地图的节点**：仍显示为普通树节点（可编辑/删除/复制），不触发画布切换。

### 5.9 面包屑导航（D7，P2 新增）

`data-testid="map-breadcrumb"`，四级逐级可回跳：

| 层级 | 文案 | 点击行为 |
|------|------|---------|
| 1 设定库 | `lib.title` | 回设定库首页（activeCat 不变，退出地图工作台 → 普通树视图） |
| 2 世界观 | `nav.lib.world` | 回世界观 tab（同层级 1，但保留世界观 tab 选中） |
| 3 地图视图 | `lib.worldMap` | 回地图工作台（清空 activeMapId，显示「选择地图」空态） |
| 4 {地图名} | 当前地图名 | 当前态（不可点） |

- 面包屑数据：`设定库 / 世界观` 是静态层级，`地图视图` 是工作台态，`{地图名}` 来自 activeMap.name。
- 层级 1/2 回跳 = 退出地图工作台（关闭画布/pin 列表，世界观 tab 回普通树视图）；层级 3 回跳 = 留在工作台但清空选中地图（空态提示「选择左侧地图节点」）。
- testid：`map-bc-lib` / `map-bc-world` / `map-bc-maplist` / `map-bc-current`。

### 5.10 三底图切换 + pin 独立叠加层（D5，P2 新增）

底图工具栏 `data-testid="map-bg-tools"`，三态 chips + 简图形状按钮：

- 底图 chips：`map-bg-shape` / `map-bg-image` / `map-bg-ai`（激活态 aria-pressed）。
- 切换底图 → `PATCH /maps/{id}` body `{bg_source: 'shape'|'image'|'ai'}` → 画布重渲染底图。
- **pin 独立叠加层（核心契约）**：pins 与 bg_source 正交——切换底图**只改 bg_source 字段**，不触碰 pins 列表；画布上 pins 始终叠加在底图之上（`map-pin` 绝对定位层）。
- AI 底图：`map-bg-ai` 选中 → 画布渲染「✨ 即将推出」禁用占位（`map-ai-placeholder`），无生成逻辑。
- 简图模式工具栏追加 ＋方框/＋椭圆/＋文字：`map-shape-add-rect` / `map-shape-add-ellipse` / `map-shape-add-text`（仅 bg_source=shape 时渲染）。

### 5.11 简图形状（D5，P2 新增）

- 形状渲染：`.map-shape`（绝对定位 div，`left/top/width/height` 百分比）；`type=rect` 矩形框、`ellipse` 圆角 50%、`text` 纯文本。
- 添加：点 ＋方框/＋椭圆 → push `{type:'rect'|'ellipse', x:35, y:35, w:24, h:16, label:'新区域'}`；＋文字 → `{type:'text', x:45, y:45, label:'新文字'}`。
- 拖拽：mousedown → 计算偏移 → mousemove 更新 x/y（百分比）→ mouseup 提交 `PATCH /maps/{id} extra:{shapes}`。
- 选中：点击形状 → `selectedShape` 高亮（`.selected` dashed outline）+ 显示删除按钮 `shape-del`。
- 删除：点 × → 移除该 shape → 提交 PATCH。
- shapes 持久化：**任何增删/拖拽结束 → `PATCH /maps/{id}` body `{extra: {shapes: [...]}}`（整体替换）**。
- testid：形状 `map-shape-<id>` / 删除 `map-shape-del-<id>`。

### 5.12 一图多标记（D6，P2 新增）

**点击画布添加**：

- 画布 `data-testid="map-canvas"` 点击任意位置 → 计算相对坐标（`(clientX-rect.left)/rect.width*100`）→ 打开 pin 对话框（预填 x/y）。
- 空画布提示 `map-pin-add-hint`：「点击画布任意位置添加标记」。

**pin 对话框（`PinDialog`，新增组件）**：

| 字段 | testid | 说明 |
|------|--------|------|
| 标记名称（必填） | `pin-name` | label，1-50 字符去空白 |
| 标记类型 | `pin-type` | shadcn Select 四档：地点/角色/事件/其他（`lib.pinType.*`） |
| 关联实体（可搜索） | `pin-ref` | 按类型搜索关联实体（见下） |
| 保存 / 取消 | `pin-save` / `pin-cancel` | #195 遮罩不关闭 |

- **关联实体搜索**：`type=location` → 搜地点（world-settings 列表）；`type=role` → 搜角色（characters）；`type=event` → 搜事件（timeline events）；`type=other` → 无关联字段（隐藏）。
- 关联实体搜索 = 复用前端已加载的六分类列表数据（本地过滤，零额外端点）；选中后存 `location_id`（location 型）或 `ref_id`（role/event 型）。
- 保存 → `POST /maps/{id}/pins` body（§3.5.1）→ 刷新 pins 列表 + ok toast。

**pin 列表（`data-testid="map-pin-list"`）**：

- 行渲染：类型徽标（`lib.pinType.<type>` 徽标）+ 名称 + 关联实体名 + 编辑/删除按钮。
- 编辑 `map-pin-edit-<id>` → 重开 PinDialog（预填）→ `PATCH /map-pins/{id}`。
- 删除 `map-pin-del-<id>` → ConfirmDialog（D11 文案，真删）→ `DELETE /map-pins/{id}`。
- 类型筛选 chips（列表头）：`map-pin-filter-<type>`（四档），点击过滤列表（前端本地过滤）。

**画布 pin 渲染**：

- pin 绝对定位（`left/top` 百分比），`data-testid="map-pin-<id>"`。
- pin 头图标按类型：`location`=点/`role`=人/`event`=事/`other`=·（原型 §5 图标语义）。

### 5.13 后端 service 扩展（P2，F36 service 增量）

`map_service.py` 扩展（对齐 §2.7）：

```text
add_pin(map_id, type='location', location_id=None, ref_id=None, x, y, label):
  ① map 存在（既有）
  ② type 校验：type 非法 → MapBgSourceError（或新错误）→ 422
  ③ location 型：location_id → world_repo.get 校验同项目（既有 MapPinLocationNotFoundError）
     role 型：ref_id → character_repo.get 校验同项目活动角色（新 MapPinRefNotFoundError）
     event 型：ref_id → timeline_repo.get 校验同项目活动事件（新 MapPinRefNotFoundError）
     other 型：两者均 NULL
  ④ 落库（MapPin 加 type/ref_id 字段）

update_pin(pin_id, update):  type/ref_id 进入 exclude_unset 合并（对齐 location_id 既有语义）

create_map(...):  bg_source 参数（默认 image）；shape 模式 file 可空 → image_path=''；
                  image 模式 file 必填 → 缺图 422
update_map(...):  bg_source/extra 进入 WorldMapUpdate exclude_unset 合并
```

- `character_repo` / `timeline_repo` 注入 `MapService.__init__`（可选，默认 None）——`deps.py` 装配时传入真实 repo，既有测试构造不传 → 跳过校验（向后兼容）。

### 5.14 大纲三级树渲染（D8，P3 新增）

大纲 tab 列表区从平铺升级为三级树（`data-testid="outline-tree"`），层级 = overall（顶层）→ volume → chapter → 情节点：

- **建树**：前端拉 `GET /projects/{pid}/outlines`（响应含 level/parent_id），本地建树——overall 顶层（parent_id 空且 level=overall）；volume 挂 overall（parent_id=overall.id）；chapter 挂 volume（parent_id=volume.id）；**孤立章**（level=chapter 且 parent_id 空）降级为顶层。
- **节点渲染**：overall 卡片（`outline-overall-<id>`）+ 卷（`outline-volume-<id>`）+ 章（`outline-chapter-<id>`）+ 情节点（`outline-point-<id>`）。
- **展开/收起**：toggle（`outline-toggle-<id>`）——overall/volume/chapter 三级均支持；有子节点才渲染 toggle（叶子不渲染）。
- **各层新增**：overall 节点「＋卷」按钮（`outline-add-volume-<parentId>`）；volume 节点「＋章」按钮（`outline-add-chapter-<parentId>`）；chapter 节点「＋情节点」按钮（`outline-add-point-<chapterId>`）。
- **情节点拉取**：chapter 首次展开时 `GET /outlines/{chapterId}/plot-points` 按需拉取（前端本地缓存）；情节点行内编辑/删除（复用 P0 情节点编辑/删除，`outline-point-edit-<id>`/`outline-point-del-<id>`）。
- **大纲行内操作**：编辑/删除按钮沿用 P0 `lib-edit-<id>`/`lib-delete-<id>`（D12 悬停显示）；overall/volume/chapter 三级均可编辑/删除。

### 5.15 章关联徽标（D9，P3 新增）

- chapter 节点若 `chapter_id` 非空 → 渲染 📎 徽标（`outline-chapter-ref-<id>`，含关联章节标题）；未关联 → 渲染「关联章节」按钮（`outline-chapter-link-<id>`）。
- 「关联章节」按钮点击 → 本批仅 toast 提示「请选择要关联的写作章节」（**选择器后置**，D9 拍板），不打开章节选择器。
- 章节标题来源：前端加载项目章节列表（`GET /projects/{pid}/chapters`）建 `chapter_id → title` 映射；未加载到 → 徽标仅显示 📎 图标（无标题）。

### 5.16 时间线双序切换（D10，P4 新增）

时间线 tab 工具栏（`data-testid="timeline-toolbar"`）加双序切换 chips：

- 序 chips：`tl-view-narrative`（叙事序）/ `tl-view-world`（世界序），激活态 aria-pressed。
- 数据源：`GET /projects/{pid}/timeline` 返回 `TimelineView { event_timeline, narrative_order }`——叙事序显示 `narrative_order`（narrative_position 升序），世界序显示 `event_timeline`（time_value 升序，未知排末尾）。
- **前端数据获取改造**：timeline 分类从「仅取 event_timeline」改为「取完整 TimelineView」（存 event_timeline + narrative_order 两个数组），切换仅本地切换显示数组，零额外请求。
- 图例：`tl-legend`（「点=叙事顺序 · 时间轴=世界内时间」）。

### 5.17 两级检查（D10，P4 新增）

**整体检查**（工具栏按钮 `tl-check-all`）：

- 点击 → `GET /projects/{pid}/timeline/check` → 结果 toast：consistent=true → `lib.tlCheckOK`（「未发现矛盾事件」）；否则 `lib.tlCheckWarn`（「发现 {n} 处时间矛盾」）。

**单事件检查**（行内按钮 `tl-check-one-<id>`）：

- 点击 → `GET /timeline/events/{id}/check` → 结果 toast：checked=false → 「该事件无时间信息，跳过检查」；consistent=true → 「与上下文一致」；否则列出该事件参与的第一条冲突 message。
- 单事件检查按钮渲染在每个事件行内（`tl-check-one-<id>`）。

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

P2 新增（地图工作台；zh.ts / en.ts 同步）：

| key | zh | en | 说明 |
|-----|----|----|------|
| `lib.worldMap` | 地图视图 | Map View | 面包屑层级 3 / 工作台态 |
| `lib.worldMapBack` | 返回设定 | Back to settings | 面包屑层级 1/2 回跳（可选） |
| `lib.worldMapPins` | 个标记 | pins | 计数后缀（N 个标记） |
| `lib.worldMapClickHint` | 点击画布任意位置添加标记 | Click anywhere on canvas to add a marker | 空画布提示 |
| `lib.worldMapNoPins` | 该地图还没有标记，点击画布添加 | No markers yet — click the canvas to add one | pin 列表空态 |
| `lib.worldMapSelectTip` | 选择左侧地图节点查看地图 | Select a map node to view | 未选地图空态 |
| `lib.pinType.location` | 地点 | Location | 标记类型四档 |
| `lib.pinType.role` | 角色 | Character | |
| `lib.pinType.event` | 事件 | Event | |
| `lib.pinType.other` | 其他 | Other | |
| `lib.pinNew` | 添加标记 | Add Marker | pin 对话框标题（新建） |
| `lib.pinEdit` | 编辑标记 | Edit Marker | pin 对话框标题（编辑） |
| `lib.pin.name` | 标记名称 | Marker name | 名称 label |
| `lib.pin.type` | 标记类型 | Marker type | 类型 label |
| `lib.pin.ref` | 关联实体 | Linked entity | 关联实体 label |
| `lib.pin.refPlaceholder` | 搜索关联（{type}）… | Search {type}… | 关联搜索占位 |
| `lib.pin.refNone` | 不关联 | No link | 关联「无」选项 |
| `lib.pin.save` | 保存 | Save | 保存按钮 |
| `lib.mapBg` | 底图 | Base | 底图工具栏标题 |
| `lib.mapBg.shape` | 简图 | Sketch | 底图三态 |
| `lib.mapBg.image` | 图片 | Image | |
| `lib.mapBg.ai` | AI | AI | |
| `lib.mapBg.aiSoon` | 即将推出 | Coming soon | AI 占位 |
| `lib.shape.rect` | ＋方框 | + Box | 简图形状按钮 |
| `lib.shape.ellipse` | ＋椭圆 | + Ellipse | |
| `lib.shape.text` | ＋文字 | + Text | |
| `lib.shape.newLabel` | 新区域 | New area | 方框/椭圆默认 label |
| `lib.shape.newText` | 新文字 | New text | 文字默认 label |

P3+P4 新增（大纲三级 + 章关联 + 时间线双序；zh.ts / en.ts 同步）：

| key | zh | en | 说明 |
|-----|----|----|------|
| `lib.level.overall` | 整体 | Overall | 大纲层级（D8） |
| `lib.level.volume` | 卷 | Volume | |
| `lib.level.chapter` | 章 | Chapter | |
| `lib.volumes` | 卷 | Volumes | 计数后缀 |
| `lib.chapters` | 章 | Chapters | 计数后缀 |
| `lib.outlinePoints` | 情节点 | Plot Points | 情节点计数 |
| `lib.empty.points` | 暂无情节点 | No plot points | 情节点空态 |
| `lib.chapterRefTip` | 已关联写作章节，点击可在写作页打开 | Linked to a writing chapter | 📎 徽标 title |
| `lib.chapterLink` | 关联章节 | Link chapter | 关联章节按钮 |
| `lib.chapterLinkPick` | 请选择要关联的写作章节 | Select the chapter to link | 选择器后置 toast |
| `lib.addVolume` | ＋卷 | + Volume | 新增卷按钮 |
| `lib.addChapter` | ＋章 | + Chapter | 新增章按钮 |
| `lib.addPoint` | ＋情节点 | + Plot Point | 新增情节点按钮 |
| `lib.tlView.narrative` | 叙事序 | Narrative order | 双序 chips |
| `lib.tlView.world` | 世界序 | World time | 双序 chips |
| `lib.tlCheck` | 一致性检查 | Consistency check | 整体检查按钮 |
| `lib.tlCheckOne` | 单事件检查 | Check event | 行内检查按钮 |
| `lib.tlLegend` | 点=叙事顺序 · 时间轴=世界内时间 | Dot = narrative order · axis = world time | 图例 |
| `lib.tlCheckOK` | 未发现矛盾事件 | No conflicts found | 检查通过 toast |
| `lib.tlCheckWarn` | 发现 {n} 处时间矛盾 | {n} time conflicts found | 检查警告 toast |
| `lib.tlCheckSkip` | 该事件无时间信息，跳过检查 | No time info, skipped | 单事件跳过 toast |
| `lib.tlCheckEventOK` | 与上下文一致 | Consistent with context | 单事件通过 toast |

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

P2 追加：

| # | 场景 | 行为 |
|---|------|------|
| E27 | pin type 非法（非 location/role/event/other） | 422 MapBgSourceError（或专用错误） |
| E28 | type=role 但 ref_id 指向不存在/跨项目/软删角色 | 422 MapPinRefNotFoundError |
| E29 | type=event 但 ref_id 指向不存在/跨项目/软删事件 | 422 MapPinRefNotFoundError |
| E30 | type=location 但 location_id 缺失 | 沿用 F36：location_id 可空（纯注释语义兼容），但 type=location + 空 location_id = 纯注释 pin（不报错） |
| E31 | 切换底图（shape↔image↔ai） | PATCH bg_source 成功 → pins 列表零影响（独立叠加层契约）；shape→image 回切 shapes 不丢，image→shape 回切 image_path 不丢 |
| E32 | bg_source=shape 创建地图（无图片） | image_path 存空串；后续切 image 时需上传图片（无图则 image 模式画布显示「无图片」占位） |
| E33 | bg_source=image 创建/换图缺 file | 422 MapBgSourceError |
| E34 | 简图 shapes 拖拽越界（x/y < 0 或 > 100） | 前端 clamp 到 0-100（拖拽时边界钳制，不持久化越界值） |
| E35 | 点击画布坐标计算（含偏移/缩放） | 用 `getBoundingClientRect` 相对百分比；容器 resize 后坐标仍正确（百分比语义） |
| E36 | pin 对话框关联实体搜索无匹配 | 显示「无匹配」轻提示 + 「不关联」选项 |
| E37 | type=other pin | 关联字段隐藏；保存 body 不含 location_id/ref_id（均 NULL） |
| E38 | 地图删除后画布仍选中该地图 | 删除地图 → activeMapId 置空 → 面包屑回「地图视图」空态 |
| E39 | 未选任何地图进入工作台 | 画布显示 `lib.worldMapSelectTip` 空态；面包屑止于「地图视图」 |
| E40 | pin 列表类型筛选 | 前端本地过滤（四档 chips），无匹配显示空态 |

P3+P4 追加：

| # | 场景 | 行为 |
|---|------|------|
| E41 | level 非法（创建/更新） | 422 OutlineLevelError |
| E42 | overall 挂父（parent_id 非空） | 422 OutlineHierarchyError |
| E43 | volume parent 非 overall（同项目） | 422 OutlineHierarchyError |
| E44 | chapter parent 非 volume（同项目） | 422 OutlineHierarchyError |
| E45 | chapter_id 非空但 level ≠ chapter | 422 OutlineChapterRefError |
| E46 | chapter_id 指向不存在/跨项目/软删章节 | 422 OutlineChapterRefError |
| E47 | 孤立章（level=chapter 且 parent 空） | 渲染降级为顶层（合法，非错误） |
| E48 | chapter_id 清除（PATCH `""`） | 置 None，📎 徽标消失 → 「关联章节」按钮 |
| E49 | 大纲三级树空 / 单层 / 深链 | 空 → 既有空态；单层无 toggle；深链直接渲染 |
| E50 | 情节点拉取失败（网络） | chapter 展开显示「情节点加载失败」轻提示 + 重试 |
| E51 | 时间线双序切换 | 本地切换数组，零请求；空序显示空态 |
| E52 | 整体检查无事件 | toast「未发现矛盾事件」（checked=0，consistent） |
| E53 | 单事件检查 time_value None | toast「该事件无时间信息，跳过检查」 |
| E54 | 单事件检查有冲突 | toast 显示第一条冲突 message（含修正建议） |
| E55 | 单事件检查事件不存在 | 404（事件已删除），前端 err toast |

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

P2 追加（地图工作台 + 后端扩展）：

**前端**：

| 操作 | 文件 | 变更 |
|------|------|------|
| MODIFY | `frontend/packages/renderer/src/pages/library.tsx` | 世界观 tab 挂接地图工作台（5.8）：地图节点识别 + activeMapId + 面包屑（5.9）+ 底图工具栏（5.10）+ 画布 + pin 列表装配 |
| NEW | `frontend/packages/renderer/src/components/MapWorkbench.tsx` | 地图工作台主组件（面包屑 + 左树 + 右画布 + pin 列表） |
| NEW | `frontend/packages/renderer/src/components/PinDialog.tsx` | pin 对话框（5.12：名称 + 类型 + 关联实体搜索） |
| NEW | `frontend/packages/renderer/src/components/MapCanvas.tsx` | 画布（底图渲染 + shapes 拖拽 + 点击添加 pin + pin 叠加层） |
| MODIFY | `frontend/packages/renderer/src/i18n/zh.ts` / `en.ts` | §6 P2 新 key 表 |
| MODIFY | `frontend/packages/renderer/src/pages/library-p2.test.tsx`（新兄弟文件） | P2 契约（§9.4） |

**后端**：

| 操作 | 文件 | 变更 |
|------|------|------|
| MODIFY | `backend/src/inkflow/domain/models/map.py` | MapPin 加 type/ref_id；MapPinCreate/Update 加 type/ref_id；WorldMap 加 bg_source/extra；WorldMapUpdate 加 bg_source/extra |
| MODIFY | `backend/src/inkflow/domain/ports/map_errors.py` | MapPinRefNotFoundError + MapBgSourceError（422 类） |
| MODIFY | `backend/src/inkflow/domain/services/map_service.py` | add_pin/update_pin 加 type/ref_id + 关联校验（character_repo/timeline_repo 可选注入）；create_map/update_map 加 bg_source/extra |
| MODIFY | `backend/src/inkflow/domain/ports/map_repository.py` | MapPin 加 type/ref_id 透传（协议签名不变，实体加字段） |
| MODIFY | `backend/src/inkflow/infrastructure/database/models/map.py` | MapORM 加 bg_source/extra；MapPinORM 加 type/ref_id |
| MODIFY | `backend/src/inkflow/infrastructure/database/repositories/map_repo.py` | ORM ↔ 领域映射补 type/ref_id/bg_source/extra |
| MODIFY | `backend/src/inkflow/api/routers/maps.py` | add_pin/update_pin 透传 type/ref_id；create_map 加 bg_source Form；update_map 透传 bg_source/extra |
| MODIFY | `backend/src/inkflow/api/deps.py` | get_map_service 注入 character_repo/timeline_repo |
| MODIFY | `backend/src/inkflow/core/database.py` | `ensure_map_columns(conn)`（§2.7.3）+ lifespan 接线 |
| NEW | `backend/tests/unit/test_map_p2.py` | P2 后端契约（§9.5 B1-B7）：models 字段 + service 校验 + api 透传 + repo 往返 + 迁移 |

> **测试文件拆分（900 行护栏）**：library.test.tsx 已 ~788 行，P2 前端契约估算 ~400 行 → 拆 `library-p2.test.tsx` 兄弟文件（自带全套基础设施，对齐 P1 `library-p1.test.tsx` 先例）；后端契约新拆 `test_map_p2.py`（test_map_service.py 已 830 行，追加会超 900 护栏）。
> **ci.yml 登记**：前端无新测试文件目录（同 pages/ 目录，既有 job glob 覆盖）；后端 unit 测试由 `pytest tests/unit/` 全目录跑（非显式文件列表）→ 新文件 `test_map_p2.py` 自动覆盖，零登记。

P3+P4 追加（大纲三级 + 章关联 + 时间线双序 + 单事件检查）：

**前端**：

| 操作 | 文件 | 变更 |
|------|------|------|
| MODIFY | `frontend/packages/renderer/src/pages/library.tsx` | 大纲 tab 挂接 OutlineTree（5.14/5.15）；时间线 tab 挂接 TimelineView（5.16/5.17）+ 完整 TimelineView 获取改造 |
| NEW | `frontend/packages/renderer/src/components/OutlineTree.tsx` | 大纲三级树（overall/volume/chapter/情节点 + 展开收起 + 各层新增 + 章关联徽标） |
| NEW | `frontend/packages/renderer/src/components/TimelineView.tsx` | 时间线双序切换 + 两级检查（工具栏整体 + 行内单事件） |
| MODIFY | `frontend/packages/renderer/src/i18n/zh.ts` / `en.ts` | §6 P3+P4 新 key 表 |
| NEW | `frontend/packages/renderer/src/pages/library-p3.test.tsx` | P3 前端契约（§9.6 O 系列） |
| NEW | `frontend/packages/renderer/src/pages/library-p4.test.tsx` | P4 前端契约（§9.6 T 系列） |

**后端**：

| 操作 | 文件 | 变更 |
|------|------|------|
| MODIFY | `backend/src/inkflow/domain/models/outline.py` | Outline/OutlineCreate/OutlineUpdate 加 level/parent_id/chapter_id + 校验 |
| MODIFY | `backend/src/inkflow/domain/ports/outline_errors.py` | OutlineLevelError/OutlineHierarchyError/OutlineChapterRefError（422 类） |
| MODIFY | `backend/src/inkflow/domain/services/outline_service.py` | create_outline/update_outline 加 level/parent_id/chapter_id + 层级校验 + chapter_repo 注入 |
| MODIFY | `backend/src/inkflow/infrastructure/database/models/outline.py` | OutlineORM 加 level/parent_id/chapter_id |
| MODIFY | `backend/src/inkflow/infrastructure/database/repositories/outline_repo.py` | ORM↔领域映射补 level/parent_id/chapter_id |
| MODIFY | `backend/src/inkflow/api/routers/outlines.py` | OutlineCreateBody 加字段 + create/update 透传 |
| MODIFY | `backend/src/inkflow/api/deps.py` | get_outline_service 注入 chapter_repo |
| MODIFY | `backend/src/inkflow/core/database.py` | ensure_outline_columns + lifespan 接线 |
| MODIFY | `backend/src/inkflow/domain/models/timeline.py` | EventCheckReport 模型 |
| MODIFY | `backend/src/inkflow/domain/services/timeline_service.py` | check_event 方法 |
| MODIFY | `backend/src/inkflow/api/routers/timeline.py` | GET /timeline/events/{id}/check 端点 |
| NEW | `backend/tests/unit/test_outline_p3.py` | P3 后端契约（§9.7 O 系列） |
| MODIFY | `backend/tests/unit/test_timeline_check.py` | P4 单事件检查契约（§9.7 T 系列） |

> **测试文件拆分（900 行护栏，本批）**：`library.tsx` 已 847 行 → 大纲/时间线渲染拆独立组件 `OutlineTree.tsx`/`TimelineView.tsx`；前端契约拆 `library-p3.test.tsx`/`library-p4.test.tsx`；后端 `test_outline_service.py`(626)/`test_outline_api.py`(740) 追加会超护栏 → 新拆 `test_outline_p3.py`；`test_timeline_check.py`(396) 追加单事件检查契约安全。

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

### 9.5 P2 测试策略（地图工作台 + 后端扩展）

**层次**：

- **前端单元/组件契约**（Vitest + RTL，RED 批先行）：新拆 `library-p2.test.tsx` 兄弟文件（§8），MapWorkbench/PinDialog/MapCanvas 由消费方契约覆盖（对齐 P0 ConfirmDialog 先例，不单列）。
- **后端单元契约**（pytest + unittest.mock.patch，RED 批同批）：**新拆 `test_map_p2.py`**（§8）装 map models/service/api/repo 的 type/ref_id/bg_source/extra 扩展契约（独立文件——test_map_service.py 已 830 行，追加会超 900 护栏）。
- **E2E**：本批不补地图 E2E（任务书未强制；地图交互 E2E 登记 P3 批次前置必补，对齐 P0 spec §14 Q3 先例）。

**前端 RED 契约（library-p2.test.tsx，M 系列）**：

| # | 用例 | 断言要点 |
|---|------|---------|
| M1 | 世界观 tab 渲染地图工作台（地图节点 🗺 徽标） | 有地图的节点 `world-map-badge-<id>` 存在；无地图节点不渲染徽标 |
| M2 | 点击地图节点 → 画布切换 + 面包屑含地图名 | 点地图节点 → `map-canvas` 出现；`map-bc-current` 文本 = 地图名 |
| M3 | 面包屑回跳：地图视图 → 空态 | 点 `map-bc-maplist` → activeMapId 清空 → `lib.worldMapSelectTip` 空态 |
| M4 | 面包屑回跳：世界观/设定库 → 退出工作台 | 点 `map-bc-world` → `map-workbench` 消失，回普通树视图 |
| M5 | 三底图切换：shape↔image↔ai 只改 bg_source，pins 保留 | 点 `map-bg-image` → PATCH body `{bg_source:'image'}`；pins 列表数量不变（独立叠加层） |
| M6 | AI 底图占位 | 点 `map-bg-ai` → `map-ai-placeholder` 渲染「即将推出」 |
| M7 | 点击画布添加标记 → PinDialog 打开 + 坐标预填 | 点 `map-canvas` → `pin-dialog` 出现；x/y 已计算 |
| M8 | PinDialog 四类型下拉 + 保存 POST body（type+ref） | 选类型=角色 + 关联角色 → 保存 → POST body `{type:'role', ref_id, x, y, label}` |
| M9 | 一图多标记：多个 pin 渲染 + 列表计数 | 3 个 pin → `map-pin-*` 3 个 + 列表 3 行 |
| M10 | pin 列表编辑 → PATCH body | 点 `map-pin-edit-<id>` → 改名 → PATCH body 含新 label |
| M11 | pin 列表删除 → DELETE + 列表刷新 | 点 `map-pin-del-<id>` → ConfirmDialog → DELETE `/map-pins/{id}` → 行消失 |
| M12 | 简图 shapes：添加方框/椭圆/文字 | 点 `map-shape-add-rect` → `map-shape-*` 出现；shapes PATCH body `extra.shapes` |
| M13 | 简图 shapes 删除 | 点 `map-shape-del-<id>` → shape 消失 + PATCH |

**后端 RED 契约（test_map_p2.py，B 系列）**：

| # | 层 | 契约 |
|---|----|------|
| B1 | models | MapPinCreate/Update 含 type/ref_id 字段（默认 location/None）；WorldMapUpdate 含 bg_source/extra |
| B2 | service | add_pin type=role 校验 ref_id → character_repo.get（不存在 → MapPinRefNotFoundError） |
| B3 | service | add_pin type=event 校验 ref_id → timeline_repo.get（不存在 → MapPinRefNotFoundError） |
| B4 | service | add_pin type 非法 → 422 |
| B5 | service | create_map bg_source=shape 无 file → image_path=''；bg_source=image 缺 file → 422 |
| B6 | api | POST pins 透传 type/ref_id；PATCH map 透传 bg_source/extra |
| B7 | repo | MapPin ORM ↔ 领域往返含 type/ref_id；Map ORM 往返含 bg_source/extra |

> **向后兼容约束（GREEN 必守）**：`MapPin` 领域实体加 `type`/`ref_id` 必须带默认值（`type="location"`, `ref_id=None`）；`WorldMap` 加 `bg_source`/`extra` 必须带默认值（`bg_source="image"`, `extra={}`）——否则 `copy_service.copy`（L227 构造 `MapPin(location_id/x/y/label)`，只传旧字段）与既有 F36 测试构造 TypeError。

### 9.6 P3+P4 前端 RED 契约（Vitest + RTL）

**P3 大纲三级 + 章关联（library-p3.test.tsx，O 系列）**：

| # | 用例 | 断言要点 |
|---|------|---------|
| O1 | 大纲三级树渲染 | 数据含 overall/volume/chapter → `outline-overall-*`/`outline-volume-*`/`outline-chapter-*` 层级渲染 |
| O2 | 孤立章降级顶层 | level=chapter 且 parent 空 → 渲染为顶层节点 |
| O3 | 三级展开/收起 | 点 `outline-toggle-<id>` → 子节点显隐 |
| O4 | 各层新增按钮 | overall 有 `outline-add-volume-*`；volume 有 `outline-add-chapter-*`；chapter 有 `outline-add-point-*` |
| O5 | 章关联徽标（已关联） | chapter 有 chapter_id → `outline-chapter-ref-<id>` 显示 📎 + 章节标题 |
| O6 | 章关联按钮（未关联） | chapter 无 chapter_id → `outline-chapter-link-<id>` 按钮 |
| O7 | 关联章节按钮点击 toast | 点 `outline-chapter-link-<id>` → toast「请选择要关联的写作章节」（选择器后置） |
| O8 | 情节点拉取 + 渲染 | chapter 展开 → `GET /outlines/{id}/plot-points` → `outline-point-*` 渲染 |

**P4 时间线双序 + 两级检查（library-p4.test.tsx，T 系列）**：

| # | 用例 | 断言要点 |
|---|------|---------|
| T1 | 双序切换 chips 渲染 + 默认叙事序 | `tl-view-narrative` 默认激活；`tl-view-world` 存在 |
| T2 | 世界序切换 | 点 `tl-view-world` → 列表按 time_value 升序（未知排末尾） |
| T3 | 叙事序切换 | 点 `tl-view-narrative` → 列表按 narrative_position 升序 |
| T4 | 整体检查按钮 + 结果 toast | 点 `tl-check-all` → `GET /timeline/check` → consistent → toast「未发现矛盾事件」 |
| T5 | 整体检查发现冲突 | check 返回 conflicts → toast「发现 {n} 处时间矛盾」 |
| T6 | 单事件检查按钮 + 一致 toast | 点 `tl-check-one-<id>` → `GET /timeline/events/{id}/check` → consistent → toast「与上下文一致」 |
| T7 | 单事件检查冲突 toast | check 返回冲突 → toast 显示第一条 message |
| T8 | 单事件检查跳过（无时间） | check 返回 checked=false → toast「该事件无时间信息，跳过检查」 |

### 9.7 P3+P4 后端 RED 契约（pytest + unittest.mock.patch）

**P3 大纲扩展（test_outline_p3.py，O 系列）**：

| # | 层 | 契约 |
|---|----|------|
| OB1 | models | Outline/OutlineCreate/OutlineUpdate 含 level/parent_id/chapter_id（默认 chapter/None/None） |
| OB2 | models | level 非法 → 校验错误 |
| OB3 | service | create_outline level=overall + parent_id 非空 → OutlineHierarchyError |
| OB4 | service | create_outline level=volume + parent 非 overall → OutlineHierarchyError |
| OB5 | service | create_outline level=chapter + parent 非 volume → OutlineHierarchyError |
| OB6 | service | create_outline level=chapter + chapter_id 指向不存在章节 → OutlineChapterRefError |
| OB7 | service | create_outline level=overall + chapter_id 非空 → OutlineChapterRefError |
| OB8 | service | 孤立章（chapter + parent 空）合法创建 |
| OB9 | api | POST outlines 透传 level/parent_id/chapter_id；PATCH 透传 + `""` 清除 |
| OB10 | repo | Outline ORM↔领域往返含 level/parent_id/chapter_id |
| OB11 | database | ensure_outline_columns 迁移（旧表加列 + 幂等 + 表不存在 no-op） |

**P4 单事件检查（test_timeline_check.py 追加，T 系列）**：

| # | 层 | 契约 |
|---|----|------|
| TB1 | service | check_event 返回该事件参与的逆序冲突（order_conflict） |
| TB2 | service | check_event flashback/flashforward 分类 |
| TB3 | service | check_event time_value None → checked=false |
| TB4 | service | check_event 事件不存在 → None（router 转 404） |
| TB5 | api | GET /timeline/events/{id}/check 返回 EventCheckReport |

### 9.8 P2 遗留地图 E2E（本批必补，§10 已登记）

P2 spec §9.5 登记「地图 E2E = P3 前置必补」。本批补 P2 遗留地图 E2E（e2e-library.spec.ts 追加，`PYTHONUTF8=1` + build renderer dist）：

| # | 用例 | 断言要点 |
|---|------|---------|
| E2E-M1 | 地图工作台入口 + 面包屑 | 世界观 tab → 地图节点 → 画布 + 面包屑含地图名 |
| E2E-M2 | 一图多标记 | 点击画布添加 pin → POST → pin 列表刷新 |
| E2E-M3 | 三底图切换 | 切换 bg_source → PATCH + pins 保留 |

> P3/P4 大纲/时间线 E2E 不在本批（任务书未强制，登记后续批次）。

## 10. 不在范围内

P0 表更新（已入范围的 P1 行移除）+ P1 新行：

| 项 | 归属 | 原因 |
|----|------|------|
| ~~角色等级必填 + 标签多选（D1/D2）~~ | ✅ 本批 P1 | 已入范围（§2.2/§2.3/§5.1/§5.2） |
| ~~世界观树/分类筛选/复制 GUI（D3/D4）~~ | ✅ 本批 P1 | 已入范围（§5.3-§5.5） |
| ~~世界观 reparent/复制交互~~ | ✅ 本批 P1 | 复制 GUI 已入范围；reparent（拖拽/改挂）仍不在——后端 `?reparent_to=` 端点已就绪但 GUI 交互未拍板，归 P2+ 候选 |
| 角色等级筛选 chips（原型 rankFilter） | P2+ 候选 | 任务书 P1 范围未列；与 D3 分类筛选语义不同，需另拍板（含「全部」与否） |
| 标签管理页（增删改标签本体） | 无归属 | 标签是角色 extra 数据，无独立实体；管理页需新后端模型，Phase 2+ |
| ~~地图工作台（D5-D7）~~ | ✅ 本批 P2 | 已入范围（§2.7/§3.5/§5.8-5.13） |
| AI 底图生成 | 后置（D5 拍板） | 仅占位「即将推出」，无 LLM 生成逻辑 |
| 内置绘图引擎（笔刷/图层） | 未来（F36 §10 同） | 简图是简单绝对定位 div，非专业绘图 |
| pin 关联势力/功法等其它实体 | P2+ 候选 | 本批仅角色/事件/地点三类（D6 拍板） |
| ~~地图 E2E 契约~~ | ✅ 本批 P3+P4 | P2 遗留必补已入范围（§9.8 E2E-M1..M3） |
| CLI pin type/ref_id 写入 | #251 | 本批 CLI 面不动 |
| ~~大纲三级 + 章关联（D8/D9）~~ | ✅ 本批 P3 | 已入范围（§2.8/§3.6/§5.14-5.15） |
| ~~时间线双序 + 两级检查（D10）~~ | ✅ 本批 P4 | 已入范围（§2.9/§3.7/§5.16-5.17） |
| 删除 30 天清理 job（#211 对齐） | P5 批次 | 后端清理任务 |
| RAG 分类编辑/删除 | 无归属 | 无 PATCH/DELETE 端点（extractions/runs 为运行记录） |
| 项目硬删除/恢复（force/restore） | 无归属 | GUI 不暴露危险操作，软删语义由确认文案表达（D6） |
| ~~E2E 编辑/删除契约~~ | ✅ 本批 P1 | P0 遗留必补项已入范围（§9.3） |

---

## 11. 依赖关系

| 依赖 | 状态 | 说明 |
|------|------|------|
| #284（设定库 GUI 升级总 issue） | ✅ OPEN | 本批为 P3+P4 子批次；PR body `Part of #284` + 注明 P3+P4 完成 / P5 未做（spec §13 M 门禁；**禁用 `Closes #284`**——P5 未完成不得关 issue） |
| P0 批次（PR #301） | ✅ 已合 | 编辑/删除/保存指示/ConfirmDialog 基座（v1.0 交付物，本批复用） |
| P1 批次（PR #306） | ✅ 已合 | 角色等级/标签/世界观树/复制（v1.1 交付物，本批世界观树渲染复用） |
| P2 批次（PR #311） | ✅ 已合 | 地图工作台（v1.2 交付物，本批沿用） |
| F35 世界观树（parent_id） | ✅ 已合 | 后端 parent_id/ancestors/descendants + list 参数（前端纯渲染） |
| F36 地图（#174） | ✅ 已合 | maps/map_pins 表 + pins 端点 + 图片资产（P2 已扩展 type/ref_id/bg_source/extra） |
| F11 大纲（outlines/plot_points/story_arcs） | ✅ 已合 | 本批扩展 level/parent_id/chapter_id（加列级） |
| F12 时间线（timeline_events + TimelineView + check） | ✅ 已合 | 本批消费双视图 + 新增单事件检查端点 |
| F3 章节（#3，chapters 表） | ✅ 已合 | 章关联目标（chapter_id → chapters.id） |
| #196 创建对话框 | ✅ 已合 | LibraryCreateDialog 双模式基座 |
| #189 已保存指示模式 | ✅ 已合 | 编辑保存反馈复用（P0 已接） |
| #195 遮罩不关闭拍板 | ✅ 已合 | PinDialog/ConfirmDialog 遵守 |
| #312 删除语义统一（F10） | ✅ 已合 | 普通实体软删→真删；本批大纲/时间线沿用真删语义（P5 仅剩 30 天清理 job） |
| 角色 extra 列（LenientJSON） | ✅ 已有 | 无迁移（P1 已透传） |

---

## 12. 关键架构决策记录

P0 表（D-1..D-6）+ P1 表（D-7..D-13）不变。P2 追加：

| # | 决策 | 方案 | 备选否决 |
|---|------|------|---------|
| D-14 | pin 关联角色/事件 = `type` 枚举 + `ref_id` 关联列；`location_id` 保留为 `type=location` 兼容别名 | 单一关联语义清晰；location_id 零破坏（F36 端点/CLI/测试不动）；type 推导目标表 | A-2 三列（location_id/role_id/event_id 冗余同步易错）；A-3 废弃 location_id 迁移（破坏 F36 全链） |
| D-15 | shapes 存 `maps.extra` JSON（LenientJSON）而非新表 | 对齐角色 extra 先例；形状是画布附属无独立查询；零新表 | 新表 map_shapes（独立查询 YAGNI） |
| D-16 | image_path 语义放宽（shape 存空串）而非 ALTER 改 NOT NULL | SQLite ALTER 无法改列约束；空串语义清晰（shape=无图）；service 按 bg_source 校验 | 重建表迁移（破坏面大）；占位路径 hack（脏） |
| D-17 | 角色/事件关联校验 = MapService 可选注入 character_repo/timeline_repo（默认 None） | 向后兼容（既有 F36 测试构造不传→跳过校验）；deps 装配传真实 repo | 硬注入（破坏既有测试构造） |
| D-18 | pin 独立叠加层 = 数据正交（pins 独立表，与 bg_source/shapes 无 FK） | D5 拍板「切换底图不影响标记」；前端只 PATCH bg_source，pins 零触碰 | pins 挂 bg_source 下（切换即失效，违反 D5） |
| D-19 | 大纲三级 = `level` 字段标记（overall/volume/chapter）+ `parent_id` 自引用（非独立 volume/chapter 实体） | 单一 outlines 表加列即可；对齐决策文档 §4「level 字段标记」推荐；情节点挂 outline 不变 | 独立 volume/chapter 实体表（复用 F3 Volume/Chapter 会混淆写作侧语义，且迁移重） |
| D-20 | 旧大纲 level 默认 `chapter`（孤立章） | 情节点天然挂其下（零迁移，D8「章→情节点」严格）；孤立章渲染降级顶层（同 P1 世界观树孤儿降级） | 默认 overall（情节点挂 overall 违反「章→情节点」结构） |
| D-21 | 三级层级严格校验（overall 无父 / volume→overall / chapter→volume） | D8 明确三级；后端轻校验防脏数据；孤立章 parent 空合法 | 宽松（parent 只校验同项目存在）——层级错乱风险 |
| D-22 | 章关联 = `chapter_id` FK→chapters（仅 level=chapter 可设）+ 选择器后置 | D9 拍板「选择器后置」；仅 chapter 可关联符合「章关联写作章节」语义；FK SET NULL 章节删除不破坏大纲 | 任意 level 可关联（语义模糊）；本批实现选择器（D9 拍板后置，不做） |
| D-23 | 单事件检查 = 独立端点 `GET /timeline/events/{id}/check`（复用相邻对扫描） | RESTful 清晰；复用 check_consistency 分类逻辑（零新冲突类型）；前端行内按需调用 | 复用 check + `?event_id=` 参数（语义混在整体检查端点）；纯前端筛选（依赖整体 check 全量返回，开销大） |

---

## 13. 验收标准

| # | 验收项 | 验证方式 |
|---|--------|---------|
| M1 | f43 spec v1.3 合入（与实现同 PR；头部版本行 + Spec 变更行 + P3+P4 章节 + 跨节同步） | PR diff 核对 + `git log origin/main -- specs/f43-setting-library-crud/spec.md` |
| M2 | RED 批全 FAIL 有实证（前端 O1-O8/T1-T8 + 后端 OB1-OB11/TB1-TB5 契约；测试输出存档） | 测试输出存档（RED 日志） |
| M3 | 前端测试全绿（既有 + P1 R 系列 + P2 M 系列 + P3 O 系列 + P4 T 系列） | `pnpm --filter renderer test` 全绿（GREEN 后本地实证） |
| M4 | 大纲三级（整体/卷/章）展开收起 + 章关联写作章节徽标 | library-p3.test.tsx O1-O8 + 手动核对 |
| M5 | 时间线叙事序/世界序切换正确 + 整体/单事件检查 | library-p4.test.tsx T1-T8 + 手动核对 |
| M6 | P2 遗留地图 E2E 补全（E2E-M1..M3） | e2e-library.spec.ts 全绿（PYTHONUTF8=1 + build renderer dist） |
| M7 | 后端扩展契约全绿（大纲 level/parent_id/chapter_id + 单事件检查） | `backend/.venv pytest backend/tests/unit/test_outline_p3.py backend/tests/unit/test_timeline_check.py` |
| M8 | PR 合入 + CI 全绿（statusCheckRollup 对照）；PR body `Part of #284` + 注明 P3+P4 完成 / P5 未做 | gh pr checks 轮询 + gh pr view |
| M9 | issue #284 保持 OPEN（P5 未做，注明进度）；worktree 清理 + 状态标记 ✅ | gh issue view 284 |

---

## 14. 待澄清问题

无阻塞级待澄清——本批交互/存储/范围全部由任务书 + 决策文档 D4/D5/D6/D7 + F36 既有实现指定。以下为已拍板留痕：

- **Q1（✅ 已确认，决策文档 D5 + 用户拍板 A-1/B-1/C-1）**：pin 关联模型 = `type` 枚举 + `ref_id` 统一关联列（location_id 保留为 type=location 兼容别名）；shapes 存 `maps.extra` JSON；image_path 语义放宽（shape 存空串，非 ALTER 改约束）。正文 §2.7/D-14/D-15/D-16 已落实。
- **Q2（✅ 已确认，决策文档 D5）**：AI 底图占位后置，本批不实现生成逻辑。正文 §5.10/§10 已落实。
- **Q3（✅ 已确认，决策文档 D6）**：标记类型四档（地点/角色/事件/其他），关联实体三类（角色/事件/地点）；pin 删除沿用 F36 真删语义。正文 §2.7.1/§5.12/§11 已落实。
- **Q4（✅ 已确认，决策文档 D7）**：面包屑四级（设定库/世界观/地图视图/{地图名}），逐级可回跳。正文 §5.9 已落实。
- **Q5（✅ 已确认，用户拍板「P2 前后端混合」）**：P2 非纯前端——需后端扩展（pins type/ref_id、maps bg_source/extra、简图创建、迁移），任务书「前端为主」已修正为「前后端混合」。正文 §1.2/§2.7/§8 已落实。
- **Q6（✅ 已确认，用户拍板 1.A）**：大纲三级 level 默认值 = `chapter`（旧大纲 → 孤立章，情节点零迁移）。正文 §1.3/§2.8/D-20 已落实。
- **Q7（✅ 已确认，用户拍板 2.A）**：三级层级严格约束（overall 无父 / volume→overall / chapter→volume；孤立章 parent 空合法）。正文 §1.3/§2.8/D-21 已落实。
- **Q8（✅ 已确认，用户拍板 3.A）**：单事件检查 = 独立端点 `GET /timeline/events/{id}/check`（复用相邻对扫描）。正文 §2.9/§3.7/D-23 已落实。

---

## 跨节同步声明（v1.3 修订必查）

| # | 位置 | 同步点 |
|---|------|--------|
| 1 | 头部 | 版本 v1.3 + Spec 变更行 + 估算 5-8 人天 + 关联 Issues 加 #3 |
| 2 | §1.2/§1.3 | P3+P4 交付物表（13 项）+ 边界声明（level 默认/层级约束/章关联/情节点/双序/单事件检查） |
| 3 | §2.8/§2.9 | 后端扩展（outlines level/parent_id/chapter_id + 层级校验 + 迁移 + EventCheckReport + check_event） |
| 4 | §3.6/§3.7 | 大纲端点扩展 + 单事件检查端点 + 异常映射 |
| 5 | §5 | 关键差异节 5.14-5.17（大纲三级树/章关联徽标/时间线双序/两级检查） |
| 6 | §6 | i18n key 表（23 个新 key） |
| 7 | §7 | E41-E55 边界表 |
| 8 | §8 | 文件结构（前端 6 + 后端 13） |
| 9 | §9 | RED 契约 O1-O8/T1-T8 + 后端 OB1-OB11/TB1-TB5 + 地图 E2E |
| 10 | §10/§11/§12/§13/§14 | 不在范围更新 / 依赖表 / D-19..D-23 / M1-M9 / Q6-Q8 |

---

*（Spec v1.3 完。实现阶段：Plan → RED（前端 O1-O8/T1-T8 + 后端 OB1-OB11/TB1-TB5 契约全 FAIL 实证存档）→ Codex GREEN（唯一编码执行者）→ QA（前端全绿 + 手动核对大纲三级/时间线双序）→ PR `feat(gui): 设定库 P3+P4 大纲三级与时间线双序...` body `Part of #284` + 进度注明 P3+P4 完成 / P5 未做，**禁用 `Closes #284`**。）*
