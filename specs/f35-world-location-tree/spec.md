# F35: 世界观地点层级（world-location-tree）— 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-09 | **依据**: 设计书 `design/world-geo-hierarchy-2026-08-08.md` §4（workspace）、PRD v2.1 §6.2 P1-02、F10 spec（世界观既有模块）、Constitution P1-P6
>
> **所属阶段**: 0.6.0 世界观三连 Step 1（数据地基，估算 2-3 人天）
>
> **关联 Issues**: [#173](https://github.com/zhx-xi/InkFlow/issues/173)（本模块）· #174（地图视图，**依赖本模块**）· #175（跨书复制，**依赖本模块**）
>
> **依赖**: ✅ F10（world_settings 表 + WorldService + WorldExtractor 管线）· ✅ F1（项目 FK 校验）· ✅ F24 语义（两级删除：归档/真删/force——本模块在树上扩展该语义）
>
> **参考 ADR**: [ADR-019](../../adr/ADR-019.md)（版本里程碑）· [ADR-002](../../adr/ADR-002.md)（六边形分层）· [ADR-003](../../adr/ADR-003.md)（Repository）· [ADR-004](../../adr/ADR-004.md)（Pydantic v2）· [ADR-012](../../adr/ADR-012.md)（错误处理）
>
> **状态**: 待实现 🔲（0.6.0）

---

## 1. 概述

在 F10 世界观条目（扁平列表 + 类别分类）之上，为**地点类条目**增加**任意深度包含层级**（邻接表 `parent_id`）：表达「清河县城 ∈ 青州 ∈ 大越国 ∈ 东大陆 ∈ 星球…」这类跨尺度包含关系，支撑主角跨尺度冒险叙事。这是世界观三连（#173/#174/#175）的**数据地基**——#174 地图 pin 关联地点、#175 跨书递归复制都依赖本模块的树结构查询能力。

**核心交付**：

```text
F10 现状:  world_settings（扁平列表，name 项目内唯一）
F35 增量:  + parent_id 自引用列（可空=顶层）
           + extra.scale 尺度自由文本标签
           + 同级唯一（partial unique (project_id, parent_id, name)）
           + 递归 CTE 祖先链/子树查询
           + 循环引用防护 + 归档级联（Q1 拍板）
           + 提取模板增强（「A 属于 B」parent 挂接，Q2 拍板）
```

### 1.1 模块类型定位（F10 扩展型，非新变体）

按 AGENTS.md 模块类型谱系，本模块**不新增实体表、不新增独立变体**——是 F10「实体 + AI 提取」模式的**模块内扩展**（同 f19-packaging「增量专项型」先例：不新建业务变体，MODIFY 既有模块为主）。特征：

| 维度 | 本模块 |
|------|--------|
| 新实体表 | ❌ 无（world_settings 加列） |
| 新 API 端点 | ✅ 2 个只读（ancestors / descendants）+ MODIFY 3 个既有端点（create/update 加 parent_id，delete 级联） |
| 新 CLI 命令 | ✅ 2 个只读（`world ancestors` / `world descendants`） |
| 核心机制 | ✅ parent_id 邻接表 + SQLite 递归 CTE + 循环防护 + 归档级联 + 提取 parent 挂接 |
| 跨模块 MODIFY | ❌ 无（全部改动在 F10 既有文件域内） |
| 错误面 | 新增 WorldCycleError（422）/ WorldParentNotFoundError（404 语义） |

### 1.2 边界声明

- **不推翻** F10 决策：不建条目间关系表（F10 §2.3）、不建类别层级树（F10 §2.2）——`parent_id` 是**地理条目的包含关系**，category 分类体系保持扁平
- **范围限定**：只做「地点树数据层」，地图视图（#174）与跨书复制（#175）不在本模块
- **F6 上下文注入增强**（按祖先链注入「主角位于清河县城，属青州/大越国」）**不在本模块**（涉及跨模块 MODIFY F6 sources.py，后续单独评估，见 §10）
- **F16 一致性审计**的地理归属检查（地点归属矛盾）不在本模块（§10）

---

## 2. 数据模型

### 2.1 world_settings 新增列

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| parent_id | int \| NULL | 自引用 FK → world_settings.id（ON DELETE CASCADE 语义，见 §2.3），可空，已索引 | 父地点；NULL = 顶层地点（宇宙/位面/独立世界） |
| extra.scale | str（extra 内键） | 自由文本，非枚举 | 尺度标签（县城/星球/河系群…）；`extra` 既有 JSON 列零迁移承载 |

**业务规则**：

1. **任意深度**：不限制层数（设计书 §2.2 认知纠偏：层级是数据不是代码——「九层尺度」是特定作品尺度，不是固定枚举）
2. **scale 语义**：纯展示标签（`extra["scale"]`），不参与任何查询/校验逻辑；缺失 = 无尺度标注
3. **parent 归属校验**：`parent_id` 必须指向**同一项目**内活动地点，否则 422（跨项目挂接禁止——数据隔离基线）
4. **循环引用防护**：创建/更新时校验「父节点 ≠ 自身或其子孙」（§5.2）
5. **name 唯一性语义演进**：项目内**全局唯一** → **同级唯一**（§2.4），这是 F10 语义的**有意变更**

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
    is_deleted: bool = False
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

### 2.4 同级唯一 + 顶层应用层校验

```text
SQLite partial unique index (project_id, parent_id, name) WHERE is_deleted = 0:
  - parent_id 非 NULL 行：DB 约束生效（同级同名唯一）
  - parent_id NULL 行（顶层）：SQLite unique index 对 NULL 不冲突（NULL ≠ NULL）
    → DB 约束失效 → 服务层显式校验「顶层同名」→ 422
```

| 场景 | 校验层 | 语义 |
|------|--------|------|
| 顶层（parent NULL）同名 | 服务层（get_by_name 同款逻辑 + parent IS NULL 过滤） | 422「同名世界观条目已存在」 |
| 同级（parent 相同）同名 | DB partial unique（IntegrityError 兜底）+ 服务层预检 | 422 友好文案 |
| 不同父同名 | 允许（有意行为变更：跨层同名合法，如两座「旧城区」） | ✅ 新语义 |

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
| GET | `/api/v1/projects/{project_id}/world-settings` | **MODIFY** | 响应条目新增 `parent_id` 字段；新增 `parent_id` 查询参数（过滤某父的直接子级，可选） |
| GET | `/api/v1/world-settings/{setting_id}/ancestors` | **CREATE** | 祖先链（含自身）：`[自身, 父, 祖父, ...]`，用于面包屑/上下文注入 |
| GET | `/api/v1/world-settings/{setting_id}/descendants` | **CREATE** | 子树（含自身）：`[自身, 全部子孙]`，用于复制/级联删除/地图树 |
| PATCH | `/api/v1/world-settings/{setting_id}` | **MODIFY** | 请求体新增 `parent_id`（出现即更新：null=置顶 / 非 null=挂接）；循环/跨项目 → 422 |
| DELETE | `/api/v1/world-settings/{setting_id}` | **MODIFY** | 语义扩展：归档级联（Q1 拍板）；force 直删级联子树 |
| POST | `/api/v1/world-settings/{setting_id}/restore` | **MODIFY** | 恢复父地点时是否级联恢复子地点（Q1 拍板，建议：是——对称语义） |

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
- 删除/恢复命令语义与 API 同步（级联行为由 service 决定，CLI 无感知）
- 错误码：`WorldCycleError`/`WorldParentNotFoundError`/`WorldNameConflictError` → `VALIDATION_ERROR`；不存在 → `NOT_FOUND`（复用 F10 CLI 既有映射）

---

## 5. 关键差异：地点树（邻接表 + 递归 CTE + 级联语义）

### 5.1 服务层变更（`domain/services/world_service.py`）

**create_setting 新增校验顺序**（load-bearing，负例必须命中目标校验分支）：

```text
① project 存在（router 路径参数校验 + repo.get）
② parent_id 若提供 → 父存在 + 同项目（否则 WorldParentNotFoundError）
③ 同级同名校验（含顶层应用层校验）→ WorldNameConflictError
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

### 5.2 循环引用防护算法

```python
async def _assert_no_cycle(pid_int: int, new_parent_id: int | None) -> None:
    """校验 new_parent_id 不是 self 或其子孙（O(depth)，ancestors CTE 复用）."""
    if new_parent_id is None:
        return
    if new_parent_id == pid_int:
        raise WorldCycleError()
    # 沿 new_parent 向上收集祖先链；若链中出现 self → 循环
    ancestor_ids = await repo.collect_ancestor_ids(new_parent_id)  # CTE 复用
    if pid_int in ancestor_ids:
        raise WorldCycleError()
```

> 利用**祖先链 CTE 反向校验**：新增/移动节点只需查「新父的祖先链是否含自身」——O(depth) 而非全树扫描（几千条量级差异可忽略，但语义更直白）。

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

-- 子树（含自身）：复制/级联删除/地图树
WITH RECURSIVE descendants(id, name, parent_id) AS (
  SELECT id, name, parent_id FROM world_settings WHERE id = :sid AND is_deleted = 0
  UNION ALL
  SELECT w.id, w.name, w.parent_id FROM world_settings w
  JOIN descendants d ON w.parent_id = d.id
  WHERE w.is_deleted = 0
) SELECT id, name, parent_id FROM descendants;
```

- **仓库端口新增**：`collect_ancestor_ids(setting_id: int) -> list[int]` / `list_descendants(setting_id: int) -> list[WorldSetting]`（返回活动条目，按 depth/created_at 稳定排序）
- 祖先链排序：**自身在前**（列表索引 0 = 自身，末尾 = 最高祖先）——面包屑反向展示即可，避免客户端二次排序
- 子树排序：**层序**（父先于子，同层按 created_at ASC）——复制/地图树确定性输出

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

> ⚠️ **FK 约束说明**：SQLite `ALTER TABLE ADD COLUMN` **不支持带 FOREIGN KEY 约束**——既有库升级后 `parent_id` 列无 DB 级 FK（应用层 ② 校验兜底）；全新安装由 `create_all` 建表（含 FK）。两路径终态语义一致（应用层强制），DB 级 FK 仅新库有（防手改 SQL）。此差异在 §12 决策记录。

### 5.5 归档/删除级联语义（Q1 拍板后固化）

沿用 F24 两级删除语义（产品语言「归档」），在树上扩展：

| 操作 | F10 现状 | F35（Q1=是 时） |
|------|----------|------------------|
| 首次 DELETE（归档） | 仅自身 is_deleted=1 | **级联归档子树**（全部子孙 is_deleted=1）——否则树断裂（子挂在不可见父下） |
| 已归档再 DELETE（真删） | 物理删自身 | **级联物理删子树** |
| `?force=true` | 物理删自身 | **级联物理删子树** |
| restore | 恢复自身 | **级联恢复子树**（对称语义，Q1 建议；否则恢复父后子仍归档，树断裂） |

> 实现注意：级联归档用一条 `UPDATE ... WHERE id IN (子树CTE)`；级联真删/force 用 `DELETE ... WHERE id IN (子树CTE)`——子树集合来自 §5.3 CTE。

### 5.6 LLM 提取增强（Q2 拍板后固化）

**模板**（`infrastructure/llm/templates/world_extract.yaml`）：

```yaml
system_prompt: |
  ...（既有，追加：）
  若条目是地点（category 为「地理」或明确地点），识别其归属关系：
  当文本表达「A 属于/位于/隶属于 B」（如「清河县城是青州治下」），
  输出 A 时带 "parent_name": "B"。
  输出严格 JSON，格式：
  {"world_settings": [
    {"name": "条目名", "category": "类别或空", "content": "内容或空", "parent_name": "父条目名或空"}
  ]}
```

**解析模型**（`domain/models/world.py`）：`ExtractedWorldSetting` 新增 `parent_name: str | None = None`（LLM 输出文本名，非 id）。

**合并逻辑**（`_world_extractor.py` `_merge`）：

```text
创建新条目时:
  ① parent_name 非空 → repo.get_by_name(pid, parent_name) 找同项目活动条目
  ② 找到 → 新条目 parent_id = 该条目 id（循环防护：不可能成环——父先于子创建，提取按顺序处理
     但 LLM 可能先输出子后输出父 → 两遍处理：第一遍创建全部无父条目，第二遍补挂 parent）
  ③ 找不到 → 置顶层 + warning「父地点「X」不存在，已置为顶层」
  ④ parent_name 为空 → 顶层
更新既有条目时: 不修改 parent_id（提取不覆盖用户手动维护的层级——AI 辅助不推翻人工结构）
```

> ⚠️ **父子顺序依赖**：LLM 输出条目顺序无保证——合并须**两遍**：第一遍全部创建（parent 暂空）→ 第二遍按 parent_name 补挂。若第二遍仍找不到父（父条目本次未提取），保持顶层 + warning。

---

## 6. 组织规则

- **目录归属**：全部改动在 F10 既有文件域（`domain/models/world.py`、`domain/ports/world_repository.py`、`domain/ports/world_errors.py`、`domain/services/world_service.py`、`domain/services/_world_extractor.py`、`infrastructure/database/models/world.py`、`infrastructure/database/repositories/world_repo.py`、`api/routers/world_settings.py`、`cli/commands/world.py`、`infrastructure/llm/templates/world_extract.yaml`）——**零新增业务文件**
- **迁移函数归属**：`core/database.py`（与 `ensure_provider_builtin_key_column` 并列）+ `api/app.py` lifespan 接线
- **排序规则**：ancestors 自身在前；descendants 层序（父先子后，同层 created_at ASC）——确定性输出（F15 教训：排序键用稳定 ASCII/时间键，不用中文文本）
- **日志**：级联归档/真删/循环拦截/提取挂接 warning 均走 loguru（`logger.info/warning`，F10 既有风格）

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
| 8 | 归档父地点 | 级联归档子树（Q1=是） |
| 9 | 归档的父 restore | 级联恢复子树（Q1 建议对称） |
| 10 | 父归档后单独访问子 | 子不可见（列表过滤 is_deleted=0，树自然隐藏） |
| 11 | 级联真删/force 中途失败 | SQLite 事务回滚（单语句 UPDATE/DELETE WHERE id IN → 原子） |
| 12 | 提取 parent_name 找不到父 | 置顶层 + warning（不阻断其余条目落库） |
| 13 | 提取两遍处理后仍无父 | 保持顶层（合法——顶层地点不需要父） |
| 14 | 深树（>10 层）递归 CTE | SQLite 默认 recursion limit 1000，几千条量级无风险（设计书 §4.3） |
| 15 | 迁移时表不存在（全新环境） | no-op，create_all 建新表自动含列+索引 |

---

## 8. 文件结构（对照真实 F10 源码树）

| 文件 | 变更 | 内容 |
|------|------|------|
| `backend/src/inkflow/domain/models/world.py` | **MODIFY** | WorldSetting/WorldCreate/WorldUpdate 加 `parent_id`；ExtractedWorldSetting 加 `parent_name` |
| `backend/src/inkflow/domain/ports/world_repository.py` | **MODIFY** | Protocol 新增 `collect_ancestor_ids` / `list_descendants` |
| `backend/src/inkflow/domain/ports/world_errors.py` | **MODIFY** | 新增 `WorldParentNotFoundError` / `WorldCycleError`（均继承 WorldServiceError） |
| `backend/src/inkflow/domain/services/world_service.py` | **MODIFY** | create/update 校验链（父存在/同级同名/循环）；delete/restore 级联；`_assert_no_cycle` |
| `backend/src/inkflow/domain/services/_world_extractor.py` | **MODIFY** | `_merge` 两遍挂接（parent_name → parent_id） |
| `backend/src/inkflow/infrastructure/database/models/world.py` | **MODIFY** | parent_id 列 + FK + 新索引 `uq_world_settings_active_name_parent` |
| `backend/src/inkflow/infrastructure/database/repositories/world_repo.py` | **MODIFY** | `collect_ancestor_ids` / `list_descendants`（递归 CTE）；`_orm_to_domain`/`_domain_to_orm`/`update` 三写点加 parent_id（F14 教训） |
| `backend/src/inkflow/infrastructure/llm/templates/world_extract.yaml` | **MODIFY** | 模板加 parent_name 输出 |
| `backend/src/inkflow/core/database.py` | **MODIFY** | `ensure_world_parent_id_column` 幂等迁移 |
| `backend/src/inkflow/api/app.py` | **MODIFY** | lifespan 接线迁移函数（与 ensure_provider_builtin_key_column 同处） |
| `backend/src/inkflow/api/routers/world_settings.py` | **MODIFY** | create/update body 加 parent_id；新增 ancestors/descendants 端点；delete/restore 语义不变（service 级联） |
| `backend/src/inkflow/cli/commands/world.py` | **MODIFY** | 新增 `ancestors`/`descendants` 子命令；create/update 加 `--parent` 参数 |
| `backend/tests/unit/test_world_*.py` | **MODIFY** | 既有测试补 parent_id 字段 + 新用例（见 §9） |
| `backend/tests/unit/test_world_location_tree.py` | **CREATE** | 地点树专项测试（CTE/循环/级联/迁移） |
| `tests/cli/test_cli_world.py` | **MODIFY** | ancestors/descendants 命令 + --parent 参数用例 |

> **CI 盲区防范**：`tests/cli/test_cli_world.py` 已在 ci.yml `integration-cli-backend` 文件列表（L411 实测）——新增命令用例在同文件内追加，**无需改 ci.yml**；新增单元测试落在 `backend/tests/unit/` 自动覆盖。

---

## 9. 测试策略

### 层次

```text
单元（repo）:  递归 CTE 祖先链/子树（真 SQLite 集成，含 3 层以上深树）   ~10 cases
单元（service）: 校验链（父不存在/跨项目/循环 3 形态/同级同名/顶层同名/置顶） ~14 cases
单元（service）: 级联归档/级联恢复/级联真删/force（子树集合断言）           ~8 cases
单元（extractor）: parent_name 挂接（找到/找不到/两遍顺序/不覆盖更新）      ~6 cases
单元（迁移）: 幂等（列存在 no-op / 列缺失 ALTER / 表不存在 no-op / 索引替换） ~4 cases
API（集成）: 端点契约（create with parent/ancestors/descendants/PATCH 置顶） ~8 cases
CLI:        ancestors/descendants/--parent/错误码映射                        ~6 cases
```

### 关键测试场景

1. **递归 CTE 正确性**：建 3 层树（国→州→县），`collect_ancestor_ids(县)` = [州, 国]；`list_descendants(国)` = [州, 县]（层序）
2. **循环防护三形态**：parent=自身 / parent=子 / parent=孙（通过移动现有节点触发，非仅创建）
3. **顶层同名 vs 同级同名 vs 跨层同名**：三者行为断言（前两者 422，后者 200）
4. **级联归档**：归档父 → 全部子孙 is_deleted=1；restore 父 → 全部子孙恢复
5. **迁移幂等**：表存在列缺失 → ALTER 成功；再跑 → no-op；表不存在 → no-op；旧索引被替换、新索引生效（`PRAGMA index_list` 断言）
6. **提取挂接**：LLM 输出 [父, 子] 乱序 → 两遍处理后子挂到父；parent_name 找不到 → 顶层 + warning；更新路径不覆盖既有 parent_id
7. **repo 三写点**：add/get/update 后 parent_id 往返一致（F14「写路径完备性」教训）
8. **PATCH 置顶**：`{"parent_id": null}` → 条目 parent 置 NULL；`{}`（未出现）→ 不修改

### 覆盖率

模块新增代码行覆盖 ≥ 80%（既有全仓门禁 ADR-027：98.5/95.0 需补测维持）。

---

## 10. 不在范围内

| 项 | 原因 | 归属 |
|----|------|------|
| 地图视图（maps/map_pins 表 + 图片 + pin） | 独立 Step 2 | #174（0.6.0） |
| 跨书递归复制/导出 | 独立 Step 3，依赖本模块子树查询 | #175（0.6.0） |
| F6 上下文注入按祖先链增强 | 跨模块 MODIFY F6 sources.py；数据地基先行，注入增强后续评估 | 后续（0.6.0 内另议或 1.0.0） |
| F16 地理一致性审计规则 | 独立审计规则增强 | 后续 |
| 相邻关系（neighbors） | 设计书 §5.3 明确不做，extra 预留 | Phase 3+ |
| 类别层级树（category 父子） | F10 §2.2 既有决策，本模块不推翻 | 永不 |
| 引用共享（project_id 可空 + 关联表） | 设计书 §6.2 后置路径，真实需求触发 | 未排期 |

---

## 11. 依赖关系

```text
F35 依赖:
  F10（world_settings 表/WorldService/Extractor） — 全部改动在其文件域内
  F1（项目存在性校验）— create/update 既有依赖
  F24 语义（两级删除）— 归档/真删/force 在树上的扩展（不代码依赖，语义沿用）

F35 被依赖:
  #174（地图视图）— map_pins.location_id 关联地点需要 parent 树存在
  #175（跨书复制）— 递归子树复制使用 list_descendants
```

**编号口径声明**：本模块为 0.6.0 世界观三连 Step 1（#173），非 PRD F 系列新业务模块——采用「F35」编号承接（F30-F33 已占用：F30=#166/F31=#167/F32=#152/F33=#168；F34=#169 CLI 恒 HTTP）。若与未来编号冲突以 ADR-019 v5+ 为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|-------------|
| 1 | 邻接表 parent_id | 自引用 FK 可空列 | 移动 O(1)、本地量级 CTE 足够、与既有 FK 惯例一致（设计书 D1） | 物化路径/闭包表（复杂度高，量级无收益） |
| 2 | scale = extra.scale 自由文本 | 非枚举非结构 | 不同作品尺度不同，写死即死（D2） | 枚举 9 层（死设计） |
| 3 | 唯一性从全局改为同级 | (project_id, parent_id, name) partial unique | 跨层同名合法（两座「旧城区」），层级语义自然 | 维持全局唯一（阻止合法跨层同名） |
| 4 | 顶层同名应用层校验 | 服务层显式校验 | SQLite unique index NULL 不冲突（设计书 §4.2 已知坑） | 依赖 DB（静默失效） |
| 5 | 循环防护用祖先链反向校验 | 查新父祖先链是否含自身 | O(depth)、复用 CTE、语义直白 | 全树扫描（量级无差别但语义绕） |
| 6 | 级联归档/恢复（Q1=是） | 子树集合 UPDATE | 树不断裂（子不可挂在不可见父下）；对称语义 | 仅自身归档（树断裂） |
| 7 | 迁移无 FK 约束（既有库） | ALTER ADD COLUMN 不带 FK + 应用层校验 | SQLite ADD COLUMN 不支持 FK；两路径终态一致 | 重建表（破坏数据/复杂度高） |
| 8 | 提取两遍挂接 + 不覆盖人工层级 | 先建全量再补挂；更新不动 parent | LLM 输出顺序无保证；AI 辅助不推翻人工结构（产品哲学） | 单遍（顺序依赖易错）；提取覆盖 parent（人工结构被 AI 覆盖） |
| 9 | 新增端点只读 2 个 | ancestors/descendants | 树查询是核心交付（面包屑/复制/地图树），CLI/API 都要用 | 不暴露（数据在列表里客户端自组装——递归不可达） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 数据模型 + 迁移（列/索引/幂等） | `pytest backend/tests/unit/test_world_location_tree.py -k migration` 全绿；全新库 create_all 含列；旧库升级幂等 |
| M2 | 递归 CTE（ancestors/descendants） | repo 测试全绿（3 层树正确序）；API ancestors/descendants 契约测试全绿 |
| M3 | 校验链（父不存在/跨项目/循环/同级同名/顶层同名/置顶） | service + API 测试全绿（负例命中目标校验分支——F13 教训：先建存在实体再测负例） |
| M4 | 级联删除语义（归档/恢复/真删/force） | service 测试全绿（子树集合断言）；API DELETE/restore 契约测试全绿 |
| M5 | 提取增强（parent_name 挂接） | extractor 测试全绿（找到/找不到/乱序两遍/不覆盖更新）；模板改动回归 |
| M6 | CLI（ancestors/descendants/--parent） | `pytest ../tests/cli/test_cli_world.py -v` 全绿 |
| M7 | 手工验证 | 创建 3 层树 → ancestors 面包屑正确 → 归档父 → 子树全隐藏 → restore → 全恢复 → 循环挂接被拒（422） |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；覆盖率达 ADR-027 门槛（98.5/95.0）；`uv run ruff check src/ tests/unit/ ../tests/` + mypy 通过 |

> Issue #173 验收标准映射：parent_id 邻接表 = M1/M2；递归 CTE = M2；同级唯一 + 顶层应用层校验 = M3；循环防护 = M3；两级删除级联 = M4；幂等迁移 = M1；提取增强 = M5。

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | **归档是否级联子树**？父地点归档时子地点是否一并归档（设计书 Q1，建议：是——否则树断裂；且 restore 对称级联）？ | 影响删除/恢复语义与 API 契约 | A：级联归档 + 级联恢复（对称），真删/force 同例级联 |
| Q2 | **提取模板增强是否本轮做**（设计书 Q2，建议：做——否则手工挂接层级成本高）？若做，更新既有条目时是否允许提取修正 parent（建议：**不覆盖**——提取只在新条目创建时挂接，AI 不推翻人工维护的层级）？ | 影响模板/提取器改动范围与行为契约 | A：做；创建时挂接，更新不覆盖 |
| Q3 | **列表接口是否加 `parent_id` 查询参数**（过滤某父的直接子级）？ | 影响前端树渲染取数方式（#174 地图树导航） | A：加（`?parent_id=<id>` 过滤直接子级；缺省 = 全量列表，向后兼容） |

---

*本文档为 F35 功能规格（What），实施步骤（How）见后续 `specs/f35-world-location-tree/plan.md`。所有里程碑验收以本节 M1-M8 为准。*
