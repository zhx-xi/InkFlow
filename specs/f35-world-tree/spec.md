# F35: 世界观地点层级（world-location-tree）— 功能规格
> **端**: backend

> **Spec 版本**: 1.1 | **日期**: 2026-08-09 | **依据**: 设计书 `design/world-geo-hierarchy-2026-08-08.md` §4（workspace）、PRD v2.1 §6.2 P1-02、F10 spec（世界观既有模块）、Constitution P1-P6
>
> **Spec 变更**（1.0 → 1.1，2026-08-09 拍板）：Q1-Q3 全拍板——**Q1 删除语义=真删 + 子地点级联/reparent（D1/D2/D4/D6，非归档级联）**；**Q2 提取建树后置给内置 Agent（D8，本轮不做模板增强）**；Q3=列表 parent_id 过滤（A）。**边界 X（D7 + 0.8.0 #211）**：F10 既有单条删除/restore（软删）保持现状不动，本模块新增树级删除操作为**真删**——差异显式声明（§1.2/§5.5）；统一改造登记 [#211](https://github.com/zhx-xi/InkFlow/issues/211)（0.8.0）。
>
> **所属阶段**: 0.6.0 世界观三连 Step 1（数据地基，估算 2-3 人天）
>
> **关联 Issues**: [#173](https://github.com/zhx-xi/InkFlow/issues/173)（本模块）· #174（地图视图，**依赖本模块**）· #175（跨书复制，**依赖本模块**）· #211（F10 删除语义统一，**后置登记**）
>
> **依赖**: ✅ F10（world_settings 表 + WorldService + WorldRepositoryProtocol）· ✅ F1（项目 FK 校验）· ⏳ F24 语义（仅会话保留归档；本模块不沿用两级删除——见 §1.2）
>
> **参考 ADR**: [ADR-019](../../adr/ADR-019.md)（版本里程碑）· [ADR-002](../../adr/ADR-002.md)（六边形分层）· [ADR-003](../../adr/ADR-003.md)（Repository）· [ADR-004](../../adr/ADR-004.md)（Pydantic v2）· [ADR-012](../../adr/ADR-012.md)（错误处理）
>
> **状态**: ✅ 已实现（PR #215，#173 2026-08-09）

---

## 1. 概述

在 F10 世界观条目（扁平列表 + 类别分类）之上，为**地点类条目**增加**任意深度包含层级**（邻接表 `parent_id`）：表达「清河县城 ∈ 青州 ∈ 大越国 ∈ 东大陆 ∈ 星球…」这类跨尺度包含关系，支撑主角跨尺度冒险叙事。这是世界观三连（#173/#174/#175）的**数据地基**——#174 地图 pin 关联地点、#175 跨书递归复制都依赖本模块的树结构查询能力。

**核心交付**：

```text
F10 现状:  world_settings（扁平列表，name 项目内唯一，软删 + restore）
F35 增量:  + parent_id 自引用列（可空=顶层）
           + extra.scale 尺度自由文本标签
           + 同级唯一（partial unique (project_id, parent_id, name)）
           + 递归 CTE 祖先链/子树查询
           + 循环引用防护
           + 删除语义：真删 + 子地点级联/reparent（D1-D6 拍板）
           + 列表 parent_id 过滤（Q3=A）
```

### 1.1 模块类型定位（F10 扩展型，非新变体）

按 AGENTS.md 模块类型谱系，本模块**不新增实体表、不新增独立变体**——是 F10「实体 + AI 提取」模式的**模块内扩展**（同 f19-packaging「增量专项型」先例：不新建业务变体，MODIFY 既有模块为主）。特征：

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ 无（world_settings 加列） |
| 新 API 端点 | ✅ 2 个只读（ancestors / descendants）+ MODIFY 3 个既有端点（create/update 加 parent_id，delete 加 cascade/reparent 参数） |
| 新 CLI 命令 | ✅ 2 个只读（`world ancestors` / `world descendants`）+ delete 加参数 |
| 核心机制 | ✅ parent_id 邻接表 + SQLite 递归 CTE + 循环防护 + 真删级联/reparent + 列表过滤 |
| 跨模块 MODIFY | ❌ 无（全部改动在 F10 既有文件域内） |
| 错误面 | 新增 WorldCycleError / WorldParentNotFoundError（422）/ WorldChildrenActionRequiredError（422） |

### 1.2 边界声明

- **不推翻** F10 决策：不建条目间关系表（F10 §2.3）、不建类别层级树（F10 §2.2）——`parent_id` 是**地理条目的包含关系**，category 分类体系保持扁平
- **范围限定**：只做「地点树数据层」，地图视图（#174）与跨书复制（#175）不在本模块
- **⚠️ 删除语义边界（边界 X，2026-08-09 拍板）**：本模块**新增的树级删除操作（级联删/reparent）为真删**（物理删除，不可恢复）；**F10 既有单条删除（DELETE 默认软删）与 restore 端点保持现状不动**（0.2.0 已合入契约，F14 提取合并/F15 审计依赖软删排除逻辑）——两语义并存，差异见 §5.5；**全项目删除语义统一（软删→真删）登记 #211（0.8.0）**
- **提取建树后置（D8）**：`world_extract.yaml` 模板增强（「A 属于 B」→ parent 挂接）**本轮不做**——由后续内置 Agent（0.7.0 Agent 化升级，F26/F27 方向）专门承接，登记见 §10；本轮 F10 提取端点行为不变（提取条目全部落顶层）
- **F6 上下文注入增强**（按祖先链注入「主角位于清河县城，属青州/大越国」）**不在本模块**（涉及跨模块 MODIFY F6 sources.py，后续单独评估，见 §10）
- **F16 一致性审计**的地理归属检查不在本模块（§10）

---

## 2. 数据模型

### 2.1 world_settings 新增列

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| parent_id | int \| NULL | 自引用 FK → world_settings.id（ORM 声明，运行时由应用层校验——见 §5.5 迁移说明），可空，已索引 | 父地点；NULL = 顶层地点（宇宙/位面/独立世界） |
| extra.scale | str（extra 内键） | 自由文本，非枚举 | 尺度标签（县城/星球/河系群…）；`extra` 既有 JSON 列零迁移承载 |

**业务规则**：

1. **任意深度**：不限制层数（设计书 §2.2 认知纠偏：层级是数据不是代码——「九层尺度」是特定作品尺度，不是固定枚举）
2. **scale 语义**：纯展示标签（`extra["scale"]`），不参与任何查询/校验逻辑；缺失 = 无尺度标注
3. **parent 归属校验**：`parent_id` 必须指向**同一项目**内活动地点，否则 422（跨项目挂接禁止——数据隔离基线）
4. **循环引用防护**：创建/更新时校验「父节点 ≠ 自身或其子孙」（§5.2）
5. **name 唯一性语义演进**：项目内**全局唯一** → **同级唯一**（§2.4），这是 F10 语义的**有意变更**——连带影响 F10 提取合并锚点（§2.4 声明）

### 2.2 领域模型变更（`domain/models/world.py`）

```python
class WorldSetting(BaseModel):
    """世界观条目领域实体 — 对应 world_settings 表（F35 新增 parent_id）."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    category: str = ""
    content: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    parent_id: uuid.UUID | None = None   # ← F35 新增：父地点；None = 顶层
    is_deleted: bool = False             # F10 既有（软删现状保留，边界 X）
    created_at: datetime
    updated_at: datetime


class WorldCreate(BaseModel):
    """创建世界观条目请求 DTO — F35 新增 parent_id."""
    project_id: uuid.UUID
    name: str
    category: str = ""
    content: str = ""
    parent_id: uuid.UUID | None = None   # ← F35 新增（None = 顶层）


class WorldUpdate(BaseModel):
    """更新世界观条目请求 DTO — F35 新增 parent_id.

    parent_id 的 None 语义与 category 不同：
    - 字段未出现（exclude_unset）→ 不修改 parent
    - 字段出现且为 null → 置顶（提升为顶层地点）
    - 字段出现且非 null → 挂接到指定父地点
    """
    name: str | None = None
    category: str | None = None
    content: str | None = None
    parent_id: uuid.UUID | None = None   # ← F35 新增
```

> ⚠️ **None 语义差异（load-bearing）**：F10 既有 `WorldUpdate` 的 None = 不修改（category/content）；`parent_id` 若沿用该语义则**无法表达「置顶」**。本 spec 显式区分：**`exclude_unset` 判断字段是否出现**，出现即更新（None = 置顶）。实现时 service 层须用 `model_fields_set` 判断（F10 `update_setting` 现用 `model_dump(exclude_unset=True)` 过滤 None——parent_id 需特殊处理，§5.1）。

### 2.3 ORM 变更（`infrastructure/database/models/world.py`）

```python
class WorldSettingORM(Base):
    """世界观条目 ORM 模型 — 映射到 world_settings 表."""

    __tablename__ = "world_settings"

    __table_args__ = (
        Index(
            "uq_world_settings_active_name_parent",   # ← 替换旧 uq_world_settings_active_name
            "project_id", "parent_id", "name",
            unique=True,
            sqlite_where=text("is_deleted = 0"),
        ),
    )

    # ... 既有列不变 ...

    parent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("world_settings.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """父地点（自引用 FK，可空=顶层；已索引）."""
```

**索引替换**：旧 `uq_world_settings_active_name (project_id, name)` 与新语义冲突（全局唯一会阻止不同父下同名地点）——**必须删除并重建**为 `(project_id, parent_id, name)`。这是行为变更（§2.1 规则 5），迁移在 §5.4。

### 2.4 同级唯一 + 顶层应用层校验 + 提取合并锚点声明

```text
SQLite partial unique index (project_id, parent_id, name) WHERE is_deleted = 0:
  - parent_id 非 NULL 行：DB 约束生效（同级同名唯一）
  - parent_id NULL 行（顶层）：SQLite unique index 对 NULL 不冲突（NULL ≠ NULL）
    → DB 约束失效 → 服务层显式校验「顶层同名」→ 422
```

| 场景 | 校验层 | 语义 |
|------|--------|------|
| 顶层（parent NULL）同名 | 服务层（`get_by_parent_and_name(pid, None, name)`，§5.1） | 422「同名世界观条目已存在」 |
| 同级（parent 相同）同名 | DB partial unique（IntegrityError 兜底）+ 服务层预检 | 422 友好文案 |
| 不同父同名 | 允许（有意行为变更：跨层同名合法，如两座「旧城区」） | ✅ 新语义 |

**⚠️ F10 提取合并锚点声明（R1 评审修复，2026-08-09）**：F10 提取合并（`_world_extractor.py` `_merge`）以「同名 = 同一世界观条目」为锚点，其前提是**项目内全局唯一**。F35 改为同级唯一后：
- `WorldRepositoryProtocol.get_by_name(project_id, name)` **不再保证唯一匹配**（跨层同名可能多条）——**本轮不改动 extractor**（提取增强后置 D8），但**必须定义确定性匹配规则**：`get_by_name` 返回项目内同名活动条目中**最早创建（created_at ASC）的一条**；多条场景由提取合并隐式命中首条，spec 声明此契约（防实现自行发明）
- 提取条目全部落顶层（无 parent 挂接）——顶层同名冲突时按 F10 现状合并语义处理（同名=同一条目）

### 2.5 决策论证表

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **邻接表 parent_id（选定）** | 移动节点 O(1)；本地 SQLite 几千条量级递归 CTE 毫秒级；与 F9/F10 既有 FK 惯例一致 | 深树递归查询依赖 CTE（SQLite 3.8.3+ 支持） | ✅ 设计书 D1 |
| 物化路径（path string） | 子树查询免递归 | 移动节点需重写整棵子树路径；长度上限 | ❌ 否决（本地量级无性能收益，复杂度高） |
| 闭包表（closure table） | 任意深度查询 O(1) | 双表维护、写入成本高、移动节点级联改闭包 | ❌ 否决（几千条量级 CTE 足够，D1） |
| scale 硬编码枚举（9 层） | 校验简单 | 不同作品尺度不同，写死即死（设计书 §2.2） | ❌ 否决（extra.scale 自由文本，D2） |

---

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 变更 | 说明 |
|------|------|------|------|
| POST | `/api/v1/projects/{project_id}/world-settings` | **MODIFY** | 请求体新增 `parent_id`（可空）；父不存在/跨项目/循环 → 422 |
| GET | `/api/v1/projects/{project_id}/world-settings` | **MODIFY** | 响应条目新增 `parent_id` 字段；新增 `parent_id` 查询参数（过滤某父的直接子级，Q3=A；`?parent_id=none` = 顶层地点） |
| GET | `/api/v1/world-settings/{setting_id}/ancestors` | **CREATE** | 祖先链（含自身）：`[自身, 父, 祖父, ...]`，用于面包屑/上下文注入 |
| GET | `/api/v1/world-settings/{setting_id}/descendants` | **CREATE** | 子树（含自身）：`[自身, 全部子孙]`，用于复制/级联删除/地图树 |
| PATCH | `/api/v1/world-settings/{setting_id}` | **MODIFY** | 请求体新增 `parent_id`（出现即更新：null=置顶 / 非 null=挂接）；循环/跨项目 → 422 |
| DELETE | `/api/v1/world-settings/{setting_id}` | **MODIFY** | **D6 参数**：`?cascade=true` = 真删子树（递归物理删）\| `?reparent_to=<id>` = 真删自身 + 子地点改挂新父（缺省置顶层）；**有子地点且未指定 → 422**（强制显式选择）；无子地点 → F10 既有软删语义保持（边界 X，§5.5） |

> **⚠️ 无 restore 端点（D7 拍板）**：本模块**不新增** restore；F10 既有 `POST /world-settings/{setting_id}/restore` 保持现状（恢复 F10 单条软删），但**不扩展**到树操作（级联恢复/子树恢复不在本模块——真删不可恢复，树级操作无恢复语义）。

### 3.2 请求/响应示例

**创建带父地点**：

```http
POST /api/v1/projects/1/world-settings
Content-Type: application/json

{"name": "清河县城", "category": "地理", "content": "...", "parent_id": "3"}
```

```json
201
{"id": "5", "project_id": "1", "name": "清河县城", "category": "地理",
 "content": "...", "extra": {}, "parent_id": "3",
 "is_deleted": false, "created_at": "...", "updated_at": "..."}
```

**置顶更新**（PATCH body 显式 null）：

```json
PATCH /api/v1/world-settings/5
{"parent_id": null}
→ {"id": "5", ..., "parent_id": null, ...}
```

**级联真删**（有子地点必须显式选择）：

```http
DELETE /api/v1/world-settings/1?cascade=true
→ 204（子树整棵物理删除）

DELETE /api/v1/world-settings/1
→ 422 {"detail": "该地点存在子地点，必须指定 cascade=true（级联删除）或 reparent_to=<id>（子地点改挂新父）"}
```

**祖先链**：

```http
GET /api/v1/world-settings/5/ancestors
→ {"items": [{"id": "5", "name": "清河县城", ...},
             {"id": "3", "name": "青州", ...},
             {"id": "1", "name": "大越国", ...}],
   "total": 3}
```

### 3.3 异常映射表（§3.4 既有映射 + 新增）

| 异常 | 状态码 | detail |
|------|--------|--------|
| WorldParentNotFoundError（新增） | 422 | 父地点不存在或不在同一项目 |
| WorldCycleError（新增） | 422 | 不能将地点挂接到自身或其子孙下 |
| WorldChildrenActionRequiredError（新增） | 422 | 该地点存在子地点，必须指定 cascade 或 reparent_to |
| WorldReparentTargetError（新增） | 422 | reparent 目标地点不存在/不在同一项目/是自身子树 |
| WorldNameConflictError（既有） | 422 | 同级同名（含顶层应用层校验） |
| WorldNotFoundError（既有） | 404 | 条目不存在 |
| ProjectNotFoundError（既有） | 404 | 项目不存在 |

> 新增错误类继承 `WorldServiceError`（422 语义），复用 F10 `world_errors.py` 既有映射链（router `_run_service` 已 catch `WorldServiceError` 子类——新增类零 router 改动）。

---

## 4. CLI 命令签名

`inkflow world` 组新增 2 个只读子命令（薄层，委托 service；F7 全局约定：`--json` 信封/退出码 0/1/2）：

```bash
inkflow world ancestors <setting_id>        # 祖先链（含自身），根在前
inkflow world descendants <setting_id>      # 子树（含自身），层序输出
```

- 响应信封 `{"ok": true, "data": {"items": [...]}}`；条目含 `parent_id`
- 既有 `world create/update` 子命令新增 `--parent <UUID>` 参数（缺省 = 顶层）
- `world delete` 子命令新增参数（D6）：`--cascade`（真删子树）/ `--reparent-to <UUID>`（真删自身 + 子改挂新父）；有子地点且未指定 → `VALIDATION_ERROR`（与 API 422 一致）
- 错误码：`WorldCycleError`/`WorldParentNotFoundError`/`WorldChildrenActionRequiredError`/`WorldNameConflictError` → `VALIDATION_ERROR`；不存在 → `NOT_FOUND`（复用 F10 CLI 既有映射）

---

## 5. 关键差异：地点树（邻接表 + 递归 CTE + 删除语义）

### 5.1 服务层变更（`domain/services/world_service.py`）

**create_setting 新增校验顺序**（load-bearing，负例必须命中目标校验分支）：

```text
① project 存在（router 路径参数校验 + repo.get）
② parent_id 若提供 → 父存在 + 同项目（否则 WorldParentNotFoundError）
③ 同级同名校验（含顶层应用层校验，get_by_parent_and_name）→ WorldNameConflictError
④ 循环防护（仅当 parent_id 提供）→ WorldCycleError
⑤ 落库
```

**update_setting 的 parent_id 特殊处理**（F10 现用 `model_dump(exclude_unset=True)` 过滤 None——parent_id 需单独分支）：

```python
updates = {k: v for k, v in update.model_dump(exclude_unset=True).items() if v is not None}
# F35: parent_id 出现即更新（None = 置顶）
if "parent_id" in update.model_fields_set:
    updates["parent_id"] = update.parent_id  # 可能为 None（置顶）
```

置顶/改挂前同样跑 ②③④ 校验（父存在/同级同名/循环）。

**仓库协议新增**（评审 S5 修复）：

```python
# WorldRepositoryProtocol 新增:
async def get_by_parent_and_name(
    project_id: int, parent_id: int | None, name: str
) -> WorldSetting | None:
    """按 (project_id, parent_id, name) 查询活动条目（parent_id=None = 顶层）——同级唯一校验用."""
```

### 5.2 循环引用防护算法

```python
async def _assert_no_cycle(pid_int: int, new_parent_id: int | None) -> None:
    """校验 new_parent_id 不是 self 或其子孙（O(depth)，ancestors CTE 复用）."""
    if new_parent_id is None:
        return
    if new_parent_id == pid_int:
        raise WorldCycleError()
    ancestor_ids = await repo.collect_ancestor_ids(new_parent_id)  # CTE 复用
    if pid_int in ancestor_ids:
        raise WorldCycleError()
```

> 利用**祖先链 CTE 反向校验**：新增/移动节点只需查「新父的祖先链是否含自身」——O(depth) 而非全树扫描。

### 5.3 递归 CTE（`infrastructure/database/repositories/world_repo.py`）

```sql
-- 祖先链（含自身）：面包屑/上下文注入/循环防护
WITH RECURSIVE ancestors(id, name, parent_id) AS (
  SELECT id, name, parent_id FROM world_settings WHERE id = :sid AND is_deleted = 0
  UNION ALL
  SELECT w.id, w.name, w.parent_id FROM world_settings w
  JOIN ancestors a ON w.id = a.parent_id
  WHERE w.is_deleted = 0
) SELECT id, name, parent_id FROM ancestors;

-- 子树（含自身）：复制/级联删除
WITH RECURSIVE descendants(id, name, parent_id) AS (
  SELECT id, name, parent_id FROM world_settings WHERE id = :sid AND is_deleted = 0
  UNION ALL
  SELECT w.id, w.name, w.parent_id FROM world_settings w
  JOIN descendants d ON w.parent_id = d.id
  WHERE w.is_deleted = 0
) SELECT id, name, parent_id FROM descendants;
```

- **仓库端口新增**：`collect_ancestor_ids(setting_id: int) -> list[int]` / `list_descendants(setting_id: int) -> list[WorldSetting]`（返回活动条目，层序稳定排序）/ `get_by_parent_and_name`（§5.1）/ `list` 加 `parent_id` 过滤参数（Q3=A，`parent_id=None` 语义用哨兵区分「未过滤」与「顶层」——实现用 `parent_id: int | None = None` + 额外 `top_level_only: bool = False` 或 sentinel）
- 祖先链排序：**自身在前**（列表索引 0 = 自身，末尾 = 最高祖先）——面包屑反向展示即可
- 子树排序：**层序**（父先于子，同层按 created_at ASC）——复制确定性输出

### 5.4 幂等迁移（无 alembic）

沿用 `core/database.py` 既有先例（`ensure_provider_builtin_key_column`，PR #176）：

```python
def ensure_world_parent_id_column(conn: Connection) -> None:
    """#173：为既有库 world_settings 补 parent_id 列 + 替换唯一索引（幂等）."""
    cols = conn.execute(text("PRAGMA table_info(world_settings)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含列+新索引）
    if "parent_id" not in names:
        conn.execute(text("ALTER TABLE world_settings ADD COLUMN parent_id INTEGER"))
    # 唯一索引替换：旧全局唯一 → 新同级唯一（先删旧，再建新，幂等）
    conn.execute(text("DROP INDEX IF EXISTS uq_world_settings_active_name"))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_world_settings_active_name_parent "
        "ON world_settings (project_id, parent_id, name) WHERE is_deleted = 0"
    ))
```

接线：`api/app.py` lifespan（`ensure_provider_builtin_key_column` 同处，`engine.begin()` + `conn.run_sync`）。

> ⚠️ **FK 约束说明**：SQLite `ALTER TABLE ADD COLUMN` **不支持带 FOREIGN KEY 约束**——既有库升级后 `parent_id` 列无 DB 级 FK（应用层校验兜底）；全新安装由 `create_all` 建表（含 FK）。生产连接未开 `PRAGMA foreign_keys=ON`（`apply_sqlite_pragma` 现状），故**运行时 FK 语义一律由 service 层显式保证**（D10=b 全局决策，§12 决策 10）。

### 5.5 删除语义（D1-D7 拍板，load-bearing）

**语义总则**（2026-08-09 拍板）：

| 操作 | 无子地点 | 有子地点 |
|------|----------|----------|
| `DELETE`（无参数） | **F10 既有软删**（is_deleted=1，边界 X——现状保持） | **422 WorldChildrenActionRequiredError**（强制显式选择） |
| `DELETE ?cascade=true` | 真删自身 | **真删整棵子树**（递归物理删，D4=A；子地点不可恢复） |
| `DELETE ?reparent_to=<id>` | 真删自身 | **真删自身 + 全部直接子地点改挂新父**（D2=A；reparent 目标校验同 §5.1 ②，缺省目标 = 置顶层？→ **reparent_to 必填，不提供缺省置顶选项**——见下） |
| restore | F10 既有单条恢复保持 | **不扩展**（树级无恢复，D7） |

> ⚠️ **reparent 缺省语义决策**：D2 建议「缺省置顶层」，经复核（三角色评审）改为 **reparent_to 必填**——「置顶层」是隐式破坏树结构的操作，应显式表达为 `reparent_to` 指向顶层父链上的目标；若用户确需置顶，CLI/前端以「reparent 到项目根」表达（或未来 GUI 提供置顶选项）。**有子地点 + reparent_to 目标存在子地点自身子树 → WorldReparentTargetError（422）**。

**实现注意**：

```text
级联真删:  1) 子树集合 = list_descendants(id)（层序）
           2) 单事务 DELETE WHERE id IN (子树集合)（原子，失败回滚）
reparent:  1) 直接子地点集合 = list(parent_id == id)
           2) 校验 reparent 目标（存在/同项目/非自身子树）
           3) 单事务: UPDATE world_settings SET parent_id = <target> WHERE parent_id = id
                      + DELETE 自身
           4) 子地点层级深度不变（原孙子继续挂子——树结构整体平移）
```

**⚠️ F10 单条软删差异声明**：本模块树级操作（cascade/reparent）为真删；F10 无参 DELETE 仍软删——**同一端点双语义**，spec 显式声明（客户端按参数选择）。全项目统一（软删→真删）为 0.8.0 #211。

### 5.6 提取建树（后置声明，D8 拍板）

**本轮不做**。设计书 §4.6「A 属于 B → parent 挂接」由**后续内置 Agent**（0.7.0 Agent 化升级，F26 agent-tools / F27 writer-agent 方向）专门承接。数据层钩子已就绪（parent_id 列 + create/update/CLI `--parent` 挂接能力），Agent 仅需调既有接口。

**承接要求清单**（登记 §10，供 0.7.0 排期引用）：

1. 同名歧义解析：同级唯一语义下 `get_by_name` 不再唯一（跨层同名多条）——Agent 需按 `(parent_name, name)` 或祖先链解析（配合 §2.4 确定性匹配规则）
2. 两遍挂接：LLM 输出顺序无保证 → 先建全量再补挂
3. 不覆盖人工层级：更新路径不动 parent_id（AI 辅助不推翻人工结构——产品哲学，#160/F27 先例）
4. 批内同名落顶层冲突：顶层同名 422 → Agent 需消歧（改名/归并）

**本轮 F10 提取端点行为**：不变（提取条目全部落顶层，按 F10 现状同名合并）。

---

## 6. 组织规则

- **目录归属**：全部改动在 F10 既有文件域（`domain/models/world.py`、`domain/ports/world_repository.py`、`domain/ports/world_errors.py`、`domain/services/world_service.py`、`infrastructure/database/models/world.py`、`infrastructure/database/repositories/world_repo.py`、`api/routers/world_settings.py`、`cli/commands/world.py`）——**零新增业务文件，零提取器改动**（提取后置 D8）
- **迁移函数归属**：`core/database.py`（与 `ensure_provider_builtin_key_column` 并列）+ `api/app.py` lifespan 接线
- **排序规则**：ancestors 自身在前；descendants 层序（父先子后，同层 created_at ASC）——确定性输出（F15 教训：排序键用稳定时间键，不用中文文本）
- **日志**：级联真删/reparent/循环拦截均走 loguru（`logger.info/warning`，F10 既有风格）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| 1 | parent_id 指向不存在条目 | 422 WorldParentNotFoundError |
| 2 | parent_id 指向**已软删**条目 | 422（活动条目才可作父——软删父不可挂接） |
| 3 | parent_id 指向**其他项目**条目 | 422（跨项目挂接禁止） |
| 4 | parent_id = 自身 | 422 WorldCycleError |
| 5 | parent_id = 自身子孙 | 422 WorldCycleError |
| 6 | 顶层同名 | 422 WorldNameConflictError（应用层校验） |
| 7 | 不同父同名 | ✅ 允许（新语义） |
| 8 | DELETE 无参数 + 无子地点 | F10 既有软删（is_deleted=1，边界 X） |
| 9 | DELETE 无参数 + 有子地点 | 422 WorldChildrenActionRequiredError（强制选择） |
| 10 | DELETE ?cascade=true | 真删整棵子树（单事务原子） |
| 11 | DELETE ?reparent_to=<id> + 目标非法 | 422 WorldReparentTargetError（不存在/跨项目/自身子树） |
| 12 | reparent 后子地点层级 | 直接子改挂目标；孙子层级不变（树整体平移） |
| 13 | 提取（F10 端点，本轮不改） | 提取条目全部落顶层；同名按 F10 合并语义（§2.4 锚点声明） |
| 14 | 深树（>10 层）递归 CTE | SQLite 默认 recursion limit 1000，几千条量级无风险（设计书 §4.3） |
| 15 | 迁移时表不存在（全新环境） | no-op，create_all 建新表自动含列+索引 |
| 16 | `?parent_id=none` 过滤 | 返回顶层地点（parent_id IS NULL）；`?parent_id=<id>` 返回直接子级；缺省全量（向后兼容） |

---

## 8. 文件结构（对照真实 F10 源码树）

| 文件 | 变更 | 内容 |
|------|------|------|
| `backend/src/inkflow/domain/models/world.py` | **MODIFY** | WorldSetting/WorldCreate/WorldUpdate 加 `parent_id` |
| `backend/src/inkflow/domain/ports/world_repository.py` | **MODIFY** | Protocol 新增 `collect_ancestor_ids` / `list_descendants` / `get_by_parent_and_name`；`list` 加 `parent_id` 过滤参数 |
| `backend/src/inkflow/domain/ports/world_errors.py` | **MODIFY** | 新增 `WorldParentNotFoundError` / `WorldCycleError` / `WorldChildrenActionRequiredError` / `WorldReparentTargetError`（继承 WorldServiceError） |
| `backend/src/inkflow/domain/services/world_service.py` | **MODIFY** | create/update 校验链（父存在/同级同名/循环）；delete cascade/reparent 编排；`_assert_no_cycle`；`get_by_parent_and_name` 调用 |
| `backend/src/inkflow/infrastructure/database/models/world.py` | **MODIFY** | parent_id 列 + FK + 新索引 `uq_world_settings_active_name_parent` |
| `backend/src/inkflow/infrastructure/database/repositories/world_repo.py` | **MODIFY** | `collect_ancestor_ids` / `list_descendants` / `get_by_parent_and_name`（递归 CTE）；`list` 加 parent_id 过滤；`_orm_to_domain`/`_domain_to_orm`/`update` 三写点加 parent_id（F14 教训） |
| `backend/src/inkflow/core/database.py` | **MODIFY** | `ensure_world_parent_id_column` 幂等迁移 |
| `backend/src/inkflow/api/app.py` | **MODIFY** | lifespan 接线迁移函数（与 ensure_provider_builtin_key_column 同处） |
| `backend/src/inkflow/api/routers/world_settings.py` | **MODIFY** | create/update body 加 parent_id；新增 ancestors/descendants 端点；delete 加 cascade/reparent_to 参数与 422 校验 |
| `backend/src/inkflow/cli/commands/world.py` | **MODIFY** | 新增 `ancestors`/`descendants` 子命令；create/update 加 `--parent`；delete 加 `--cascade`/`--reparent-to` |
| `backend/tests/unit/test_world_*.py` | **MODIFY** | 既有测试补 parent_id 字段 + 新用例（见 §9） |
| `backend/tests/unit/test_world_location_tree.py` | **CREATE** | 地点树专项测试（CTE/循环/删除语义/过滤/迁移） |
| `tests/cli/test_cli_world.py` | **MODIFY** | ancestors/descendants 命令 + --parent + delete 参数用例 |

> **CI 盲区防范**：`tests/cli/test_cli_world.py` 已在 ci.yml `integration-cli-backend` 文件列表（L411 实测）——新增命令用例在同文件内追加，**无需改 ci.yml**；新增单元测试落在 `backend/tests/unit/` 自动覆盖。

---

## 9. 测试策略

### 层次

```text
单元（repo）:  递归 CTE 祖先链/子树（真 SQLite 集成，含 3 层以上深树）   ~10 cases
单元（service）: 校验链（父不存在/跨项目/循环 3 形态/同级同名/顶层同名/置顶） ~14 cases
单元（service）: 删除语义（无子软删/有子 422/级联真删/reparent 平移/目标校验） ~10 cases
单元（repo）:   列表 parent_id 过滤（缺省/直接子级/top_level_only）            ~4 cases
单元（迁移）: 幂等（列存在 no-op / 列缺失 ALTER / 表不存在 no-op / 索引替换） ~4 cases
API（集成）:  端点契约（create with parent/ancestors/descendants/PATCH 置顶/DELETE 参数） ~10 cases
CLI:        ancestors/descendants/--parent/delete 参数/错误码映射              ~8 cases
```

### 关键测试场景

1. **递归 CTE 正确性**：建 3 层树（国→州→县），`collect_ancestor_ids(县)` = [州, 国]；`list_descendants(国)` = [州, 县]（层序）
2. **循环防护三形态**：parent=自身 / parent=子 / parent=孙（通过移动现有节点触发，非仅创建）
3. **顶层同名 vs 同级同名 vs 跨层同名**：三者行为断言（前两者 422，后者 200）
4. **删除语义矩阵**：无子 DELETE → 软删（is_deleted=1）；有子 DELETE 无参 → 422；`?cascade=true` → 子树全物理删（断言行消失，非 is_deleted）；`?reparent_to` → 自身删 + 子改挂目标 + 孙子层级不变
5. **reparent 目标校验**：目标不存在/跨项目/目标是自身子孙 → 422（负例命中目标校验分支——F13 教训）
6. **列表过滤**：`?parent_id=<id>` 直接子级 / `?parent_id=none` 顶层 / 缺省全量（向后兼容回归）
7. **迁移幂等**：表存在列缺失 → ALTER 成功；再跑 → no-op；表不存在 → no-op；旧索引被替换、新索引生效（`PRAGMA index_list` 断言）
8. **repo 三写点**：add/get/update 后 parent_id 往返一致（F14「写路径完备性」教训）
9. **PATCH 置顶**：`{"parent_id": null}` → 条目 parent 置 NULL；`{}`（未出现）→ 不修改
10. **F10 提取回归**：既有提取测试全绿（本轮不改 extractor——行为不变声明验证）

### 覆盖率

模块新增代码行覆盖 ≥ 80%（既有全仓门禁 ADR-027：98.5/95.0 需补测维持）。

---

## 10. 不在范围内

| 项 | 原因 | 归属 |
|----|------|------|
| 地图视图（maps/map_pins 表 + 图片 + pin） | 独立 Step 2 | #174（0.6.0） |
| 跨书递归复制/导出 | 独立 Step 3，依赖本模块子树查询 | #175（0.6.0） |
| **提取自动建树（「A 属于 B」parent 挂接）** | **D8 拍板后置**：内置 Agent 专门做（承接要求清单见 §5.6） | **内置 Agent（0.7.0，F26/F27 方向）** |
| **F10 删除语义统一（软删→真删）** | **边界 X 拍板**：本模块树级操作真删，F10 单条软删保持现状 | **#211（0.8.0）** |
| F6 上下文注入按祖先链增强 | 跨模块 MODIFY F6 sources.py；数据地基先行，注入增强后续评估 | 后续（0.6.0 内另议或 1.0.0） |
| F16 地理一致性审计规则 | 独立审计规则增强 | 后续 |
| 相邻关系（neighbors） | 设计书 §5.3 明确不做，extra 预留 | Phase 3+ |
| 类别层级树（category 父子） | F10 §2.2 既有决策，本模块不推翻 | 永不 |
| 引用共享（project_id 可空 + 关联表） | 设计书 §6.2 后置路径，真实需求触发 | 未排期 |
| 树级 restore（级联恢复） | D7 拍板：真删不可恢复，树级无恢复语义 | 永不 |

---

## 11. 依赖关系

```text
F35 依赖:
  F10（world_settings 表/WorldService/Repository）— 全部改动在其文件域内
  F1（项目存在性校验）— create/update 既有依赖
  ⏳ F24 语义（两级删除）— 本模块**不沿用**（仅会话保留归档，2026-08-09 拍板）

F35 被依赖:
  #174（地图视图）— map_pins.location_id 关联地点需要 parent 树存在
  #175（跨书复制）— 递归子树复制使用 list_descendants
```

**编号口径声明**：本模块为 0.6.0 世界观三连 Step 1（#173），非 PRD F 系列新业务模块——采用「F35」编号承接（F30-F33 已占用：F30=#166/F31=#167/F32=#152/F33=#168；F38=#169 CLI 恒 HTTP）。若与未来编号冲突以 ADR-019 v5+ 为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|-------------|
| 1 | 邻接表 parent_id | 自引用 FK 可空列 | 移动 O(1)、本地量级 CTE 足够、与既有 FK 惯例一致（设计书 D1） | 物化路径/闭包表（复杂度高，量级无收益） |
| 2 | scale = extra.scale 自由文本 | 非枚举非结构 | 不同作品尺度不同，写死即死（D2） | 枚举 9 层（死设计） |
| 3 | 唯一性从全局改为同级 | (project_id, parent_id, name) partial unique | 跨层同名合法（两座「旧城区」），层级语义自然 | 维持全局唯一（阻止合法跨层同名） |
| 4 | 顶层同名应用层校验 | `get_by_parent_and_name` 服务层校验 | SQLite unique index NULL 不冲突（设计书 §4.2 已知坑） | 依赖 DB（静默失效） |
| 5 | 循环防护用祖先链反向校验 | 查新父祖先链是否含自身 | O(depth)、复用 CTE、语义直白 | 全树扫描（量级无差别但语义绕） |
| 6 | **删除语义：真删 + 级联/reparent（D1-D6 拍板）** | 树级操作物理删；有子 422 强制选择 | 删除=删除（产品语言收敛，会话唯一保留归档）；级联/reparent 显式选择防误删整棵 | 两级删除（归档级联——被用户否决，归档=会话专属） |
| 7 | 迁移无 FK 约束（既有库） | ALTER ADD COLUMN 不带 FK + 应用层校验 | SQLite ADD COLUMN 不支持 FK；两路径终态一致 | 重建表（破坏数据/复杂度高） |
| 8 | **提取建树后置（D8 拍板）** | 本轮不做模板增强；内置 Agent 承接 | AI 行为归 Agent 域（F26/F27 已规划）；数据层先行（parent_id + 挂接接口就绪） | 模板增强（LLM 输出顺序脆弱、覆盖人工层级风险） |
| 9 | **边界 X：F10 单条软删保持（D7）** | 无参 DELETE 软删 + restore 端点不扩展 | 已合入契约（F14/F15 依赖软删逻辑）；统一改造 0.8.0 #211 | 本轮统一真删（跨模块行为变更超范围） |
| 10 | **FK 运行时由 service 显式保证（D10=b）** | 级联/校验全部 service 层；不动 apply_sqlite_pragma | 生产连接未开 foreign_keys=ON，测试开——依赖 DB FK = 测试绿生产挂 | 全局开 FK pragma（回归 F1-F16 全族，独立后续项） |
| 11 | 新增端点只读 2 个 | ancestors/descendants | 树查询是核心交付（面包屑/复制），CLI/API 都要用 | 不暴露（列表自组装——递归不可达） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 数据模型 + 迁移（列/索引/幂等） | `pytest backend/tests/unit/test_world_location_tree.py -k migration` 全绿；全新库 create_all 含列；旧库升级幂等 |
| M2 | 递归 CTE（ancestors/descendants） | repo 测试全绿（3 层树正确序）；API ancestors/descendants 契约测试全绿 |
| M3 | 校验链（父不存在/跨项目/循环/同级同名/顶层同名/置顶） | service + API 测试全绿（负例命中目标校验分支） |
| M4 | **删除语义（无子软删/有子 422/级联真删/reparent 平移/目标校验）** | service 测试全绿（删除矩阵断言）；API DELETE 参数契约测试全绿 |
| M5 | **列表 parent_id 过滤（Q3=A）** | `pytest backend/tests/unit/test_world_location_tree.py -k 'filter'` 全绿（缺省/直接子级/top_level_only）；API `GET /world-settings?parent_id=` 契约测试全绿（向后兼容回归） |
| M6 | CLI（ancestors/descendants/--parent/delete 参数） | `pytest ../tests/cli/test_cli_world.py -v` 全绿 |
| M7 | 手工验证 | 创建 3 层树 → ancestors 面包屑正确 → 无参删父（422）→ cascade 真删（子树消失）→ 重建后 reparent（子改挂）→ 循环挂接被拒（422） |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；覆盖率达 ADR-027 门槛（98.5/95.0）；`uv run ruff check src/ tests/unit/ ../tests/` + mypy 通过 |

> Issue #173 验收标准映射：parent_id 邻接表 = M1/M2；递归 CTE = M2；同级唯一 + 顶层应用层校验 = M3；循环防护 = M3；真删级联/reparent = M4；幂等迁移 = M1；提取建树 → 后置（§10 登记，0.7.0 内置 Agent）；列表过滤 = M5。

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 结论 |
|---|------|------|------|
| Q1 | 删除语义：归档级联 or 真删级联？ | 删除/恢复语义与 API 契约 | ✅ 已确认（2026-08-09 拍板：D1-D7）——**真删 + 子地点级联/reparent（D6 参数，有子 422 强制选择）；F10 单条软删保持（边界 X，#211 后置统一）**（§3.1/§5.5/§12 决策 6/9） |
| Q2 | 提取模板增强是否本轮做？更新是否覆盖 parent？ | 模板/提取器改动范围 | ✅ 已确认（2026-08-09 拍板：D8）——**本轮不做，后置内置 Agent（0.7.0）；F10 提取端点行为不变**（§5.6/§10/§12 决策 8） |
| Q3 | 列表接口是否加 parent_id 查询参数？ | 前端树渲染取数方式 | ✅ 已确认（2026-08-09 拍板：选项 A）——**加 `?parent_id=<id>` / `?parent_id=none` 过滤，缺省全量向后兼容**（§3.1/§5.3/§13 M5） |

---

*本文档为 F35 功能规格（What），实施步骤（How）见后续 `specs/f35-world-tree/plan.md`。所有里程碑验收以本节 M1-M8 为准。*
## 14. 动作确认

> 基于 §3 API + §4 CLI + §7 边界事实的状态流表，不新增行为。

### 14.1 端点状态流

| 端点 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| POST /api/v1/projects/{project_id}/world-settings（MODIFY） | 项目存在 | 校验父存在/同项目/无环/同级同名 → 建条目 | 201 + WorldSetting（含 parent_id） | 422 WorldParentNotFoundError（父地点不存在或不在同一项目）；422 WorldCycleError（不能将地点挂接到自身或其子孙下）；422 WorldNameConflictError（同级同名） | parent_id 可空 = 顶层 |
| GET /api/v1/projects/{project_id}/world-settings（MODIFY） | 项目存在 | 列表 + parent_id 过滤 | 200 + {items,total,offset,limit} | — | ?parent_id=<id> 直接子级；?parent_id=none 顶层；缺省全量（向后兼容） |
| GET /api/v1/world-settings/{setting_id}/ancestors（CREATE） | 条目存在 | 递归 CTE 祖先链（含自身） | 200 + {items,total} | 404 WorldNotFoundError | 根在前，用于面包屑/上下文注入 |
| GET /api/v1/world-settings/{setting_id}/descendants（CREATE） | 条目存在 | 递归 CTE 子树（含自身） | 200 + {items,total} | 404 WorldNotFoundError | 用于复制/级联删除/地图树 |
| PATCH /api/v1/world-settings/{setting_id}（MODIFY） | 条目存在 | 更新（parent_id 出现即更新） | 200 + WorldSetting | 404 WorldNotFoundError；422 WorldCycleError（自身/子孙）；422 WorldParentNotFoundError（跨项目） | parent_id null = 置顶 |
| DELETE /api/v1/world-settings/{setting_id}（无子地点） | 条目存在·无子地点 | F10 既有软删（is_deleted=1） | 204 | 404 WorldNotFoundError | ⚠️ 边界 X：与 F10 v1.1 真删语义存在跨 spec 张力（§5.5，#211 后置统一） |
| DELETE /api/v1/world-settings/{setting_id}?cascade=true（有子地点） | 条目存在·有子地点 | 递归真删整棵子树（单事务原子） | 204 | 404 WorldNotFoundError | 真删不可恢复 |
| DELETE /api/v1/world-settings/{setting_id}?reparent_to=<id>（有子地点） | 条目存在·有子地点 | 直接子改挂新父 + 真删自身 | 204 | 422 WorldReparentTargetError（reparent 目标地点不存在/不在同一项目/是自身子树） | 孙子层级不变（树整体平移） |
| DELETE /api/v1/world-settings/{setting_id}（有子地点且未指定） | 条目存在·有子地点 | 拒绝删除 | 422 WorldChildrenActionRequiredError（该地点存在子地点，必须指定 cascade 或 reparent_to） | — | 强制显式选择 |

### 14.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| world ancestors <setting_id> | 条目存在 | 祖先链查询 | {ok:true, data:{items}}（含 parent_id） | NOT_FOUND 退出码 1 | 只读薄层，根在前 |
| world descendants <setting_id> | 条目存在 | 子树查询 | {ok:true, data:{items}} | NOT_FOUND 退出码 1 | 只读薄层，层序输出 |
| world create/update --parent <UUID> | 父校验通过 | 建/改挂条目 | ✅ / --json | VALIDATION_ERROR（循环/父不存在/同名，与 API 422 一致）；NOT_FOUND | 缺省 = 顶层 |
| world delete --cascade / --reparent-to <UUID> | 条目存在 | 真删子树 / 改挂后真删 | ✅ / --json | 有子未指定 → VALIDATION_ERROR（与 API 422 一致）；NOT_FOUND | — |

### 14.3 验收锚点

- A1：parent_id = 自身或自身子孙 → 422 WorldCycleError（防环）
- A2：DELETE 有子地点未指定 cascade/reparent_to → 422 WorldChildrenActionRequiredError
- A3：?cascade=true → 整棵子树单事务真删（不可恢复）
- A4：?reparent_to 目标不存在/跨项目/自身子树 → 422 WorldReparentTargetError；成功后直接子改挂、孙子层级不变
- A5：顶层同名 → 422 WorldNameConflictError；不同父同名 → ✅ 允许
- A6：?parent_id=none → 仅顶层地点；?parent_id=<id> → 直接子级；缺省全量（向后兼容）
