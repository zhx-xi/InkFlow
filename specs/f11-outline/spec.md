# F11: 大纲管理 (outline_service) — 功能规格
> **端**: backend

> **Spec 版本**: 1.0 | **日期**: 2026-08-01 | **依据**: PRD v2.1 §6.2 P1-03, Constitution P1-P6, ADR-019
> **所属阶段**: Phase 2 — 创作工具链（0.2.0 里程碑第三个模块，估算 3-4 人天）
> **关联 Issues**: [#41](https://github.com/zhx-xi/InkFlow/issues/41)
> **依赖**: F1 ✅, F5 ✅（前置）；F6 ✅（数据源集成点，见 §11 与待澄清 Q1）；F2（边界声明，非硬依赖，见 §11）
> **参考 ADR**: [ADR-001](../../adr/architecture/ADR-001.md) (模块化单体), [ADR-002](../../adr/architecture/ADR-002.md) (六边形分层), [ADR-003](../../adr/database/ADR-003.md) (Repository), [ADR-004](../../adr/database/ADR-004.md) (Pydantic v2), [ADR-007v2](../../adr/architecture/ADR-007v2.md) (包结构), [ADR-010](../../adr/llm/ADR-010.md) (上下文分层), [ADR-012](../../adr/architecture/ADR-012.md) (错误处理), [ADR-014](../../adr/llm/ADR-014.md) (ChatPromptTemplate), [ADR-015](../../adr/llm/ADR-015.md) (LangChain 隔离), [ADR-016](../../adr/service/ADR-016.md) (loguru), [ADR-017](../../adr/test-ci/ADR-017.md) (CI 门禁), [ADR-018](../../adr/test-ci/ADR-018.md) (测试分层), [ADR-019](../../adr/packaging/ADR-019.md) (版本里程碑)
> **状态**: ✅ 已实现（PR #58）

>
> **快速导航**（2026-08-08 #201）：
> [1. 概述](L12) · [2. 数据模型](L44) · [3. API 契约](L369) · [4. CLI 命令签名](L612)
> [5. AI 生成模式（关键差异：生成而非提取）](L702) · [6. 大纲/弧线/情节点组织规则](L841) · [7. 边界情况与错误处理](L874) · [8. 文件结构](L921)
> [9. 测试策略](L1040) · [10. 不在范围内](L1087) · [11. 依赖关系](L1109) · [12. 关键架构决策记录](L1144)
> [13. 验收标准](L1170) · [待澄清问题（≤ 3 个，评审时确认）](L1186)
---

## 1. 概述

管理小说的**结构化大纲**（卷/章/节规划层的创建/查询/更新/软删除）、**情节点**（故事关键节点，有序、带类型）与**故事弧线**（跨章节的情节发展线，情节点的组织维度），并支持**基于项目设定用 LLM 自动生成大纲**（大纲名/情节点/弧线）。

**核心价值**: 作者与 AI Agent 可以在写作前维护结构化创作规划；AI 生成把「项目设定/创作约束」转化为可落库的大纲初稿，为 F3 写作（按大纲续写）、F6 上下文注入（大纲进 Prompt，protected 层）提供数据基础。

**与 F9/F10 样板的关系（关键差异）**: F9（角色）/F10（世界观）已沉淀「**实体 + AI 提取**」模式；F11 是 0.2.0 创作工具链**第三个**应用该骨架的模块，但 AI 场景从「提取」变为「**生成**」——这是本模块与样板的核心差异：

```text
F9/F10 提取:  章节文本(text) ──LLM──▶ 结构化实体 ──合并落库──▶ 实体档案
F11  生成:    项目设定/约束(prompt) ──LLM──▶ 结构化大纲 ──新建落库──▶ 大纲规划
```

**复用** F9/F10 管线的骨架部分：模板渲染 → LLM（temperature 0.2）→ JSON 解析 → Pydantic schema 校验 → 修复式重试（≤2）→ 单事务落库（`_outline_generator.py` 对照 `_world_extractor.py` 实现，§5 详述）。
**不同**的部分：输入是「项目信息 + 可选约束」而非章节文本；落库是「生成即新建」（大纲无合并语义）而非「同名 upsert 合并」；落库可选（`save` 参数，支持只预览不落库）。§5 是本节差异的完整展开。

**三个概念的建模定位**:

| 概念 | 定位 | 说明 |
|------|------|------|
| **Outline（大纲）** | 项目级实体（1:N） | 一个规划版本（卷/章/节规划层的容器，含名称/描述/排序） |
| **PlotPoint（情节点）** | 大纲级实体（1:N） | 大纲的骨架：有序、带类型（开篇/发展/转折/高潮/结局）的关键节点 |
| **StoryArc（故事弧线）** | 项目级实体（1:N） | 跨大纲/跨章节的情节发展线（如「主角成长线」「反派线」）；情节点可选挂弧线（arc_id） |

**边界声明**:
- F11 管「**写作前的规划**」，F2 chapter_service 管「**已创建的卷/章**」——两者**不互相依赖**：F11 不强制绑定 chapter，大纲情节点不与实际章节挂钩（「大纲章节 ↔ 实际章节」映射归 Phase 2+，见 §10）
- F11 不做大纲的**树形层级表**（卷→章→节节点树）：MVP 以「大纲 + 有序情节点序列」表达结构（情节点 type + position 提供宏观骨架），树形规划大纲归 Phase 2+（决策见 §2.2/§12）
- F11 不实现 F6 上下文注入（`ContextSourceType.OUTLINE` 数据源）：F6 已有 `ProjectConfigOutlineSource`（读 `project.config.extra["outline"]`，**已实现**）；F11 实体化后两者关系与改造归属见 §11 与待澄清 Q1
- F11 的弧线/情节点是**简单外键组织**（弧线 ← 情节点），不做依赖图、不做节点间关系表（决策见 §2.3/§12）

---

## 2. 数据模型

遵循 F1 Project 的「领域 Pydantic 实体 + 请求/更新 DTO + ORM 双模型」模式（ADR-004）。领域层 id 为 UUID，数据库 int 自增映射（同 F1 §12）。

### 2.1 Outline（大纲）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，DB int 自增映射 |
| project_id | UUID | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目 |
| name | str | NOT NULL, 1-50 字符, 去空白 | 大纲名（如「第一卷大纲」「主线规划 v1」）；**项目内活动大纲唯一**（partial unique，见 §2.4） |
| description | str | NOT NULL, DEFAULT "", ≤ 5000 字符 | 大纲总体描述（故事主线概述） |
| sort_order | int | NOT NULL, DEFAULT 0, ≥ 0 | 大纲间排序权重（小者在前） |
| extra | dict[str, Any] | NOT NULL, DEFAULT {} | 扩展字典（生成标记、来源约束等 Phase 2+ 字段预留） |
| is_deleted | bool | NOT NULL, DEFAULT False, 已索引 | 软删除标记 |
| created_at | datetime | NOT NULL, AUTO | 创建时间 (UTC) |
| updated_at | datetime | NOT NULL, AUTO | 更新时间 (UTC) |

**业务规则**:
- `name` 项目内**活动大纲唯一** = 「同名 = 同一规划版本」，防止手误重复建档；软删除后再创建同名大纲合法（partial unique）
- **大纲软删除 → 其情节点级联软删除**；大纲恢复 → 情节点级联恢复（服务层实现，保证规划结构一致）；大纲硬删除 → 情节点物理删除（DB FK CASCADE）；**弧线不受影响**（弧线是项目级组织维度，见 §2.3）

### 2.2 PlotPoint（情节点）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID |
| outline_id | UUID | NOT NULL, FK→outlines.id (CASCADE), 已索引 | 所属大纲（大纲软删/硬删 → 级联） |
| project_id | UUID | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目（冗余存储，便于弧线归属校验与项目隔离，同 F9 CharacterRelation 先例） |
| name | str | NOT NULL, 1-100 字符, 去空白 | 情节点名（如「主角获得金手指」）；**大纲内允许重名**（不做唯一约束，见 §2.4） |
| type | str | NOT NULL, DEFAULT "", ≤ 20 字符, 去空白 | 情节点类型（建议值：开篇/发展/转折/高潮/结局；自由文本，受控词表归 F14）；空串 = 未分类 |
| description | str | NOT NULL, DEFAULT "", ≤ 5000 字符 | 情节点要点描述（该节点发生什么） |
| position | int | NOT NULL, DEFAULT 0, ≥ 0 | 大纲内排序（小者在前）；创建缺省 = 大纲内 max(position)+1；允许重复 |
| arc_id | UUID? | NULLABLE, FK→story_arcs.id (SET NULL), 已索引 | 所属故事弧线（可选；弧线软删 → 置 NULL） |
| extra | dict[str, Any] | NOT NULL, DEFAULT {} | 扩展字典（参与角色、地点等 Phase 2+ 字段预留） |
| is_deleted | bool | NOT NULL, DEFAULT False, 已索引 | 软删除标记 |
| created_at | datetime | NOT NULL, AUTO | 创建时间 (UTC) |
| updated_at | datetime | NOT NULL, AUTO | 更新时间 (UTC) |

**业务规则**:
- `arc_id` 必须属于**同一项目**（以 outline 的项目为准；弧线归属不一致 → 422「弧线不存在于该项目」，镜像 F9 分组归属校验）
- 情节点**软删除/恢复不影响弧线**（arc_id 保留）；弧线软删 → 成员情节点 arc_id 置 NULL（情节点本身保留，同 F9 分组删除语义）
- `position` 允许重复：排序按 `(position ASC, created_at ASC)` 稳定输出；不做唯一约束（position 是展示排序权重而非业务键，同 F9 `sort_order` 处理）

### 2.3 StoryArc（故事弧线）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID |
| project_id | UUID | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目 |
| name | str | NOT NULL, 1-50 字符, 去空白 | 弧线名（如「主角成长线」「反派线」）；**项目内活动弧线唯一**（partial unique，见 §2.4） |
| description | str | NOT NULL, DEFAULT "", ≤ 500 字符 | 弧线说明 |
| is_deleted | bool | NOT NULL, DEFAULT False, 已索引 | 软删除标记 |
| created_at / updated_at | datetime | NOT NULL, AUTO | 同上 |

**业务规则**:
- 弧线是**项目级**概念（不挂大纲）：一条弧线可串联**多个大纲**的情节点（多次 AI 生成的大纲可复用同名弧线）——弧线是「跨规划版本」的组织维度
- 弧线软删 → 成员情节点 arc_id 置 NULL（不级联删情节点）；弧线恢复**不恢复**成员关联（同 F9 分组删除/恢复语义，无级联恢复）

### 2.4 唯一约束（partial unique index，SQLite）

```python
# ORM __table_args__（SQLAlchemy 2.0 + SQLite partial index）
__table_args__ = (
    Index(
        "uq_outlines_active_name",
        "project_id", "name",
        unique=True,
        sqlite_where=text("is_deleted = 0"),
    ),
    Index(
        "uq_story_arcs_active_name",
        "project_id", "name",
        unique=True,
        sqlite_where=text("is_deleted = 0"),
    ),
)
```

**为什么是 partial index**: 「项目内活动大纲/弧线同名唯一」防止手误重复建档，也是 AI 生成时**弧线按名复用**（§5.4）的锚点；软删除后再创建同名实体是合法操作（旧规划已废弃），partial index 两者兼得。服务层再做一次同名检查以给出友好 422 文案。
**PlotPoint 不设唯一约束**: 情节点名允许重复（「高潮」可在多个弧线/位置出现），position 允许重复（排序权重），无自然业务唯一键——唯一约束在此无意义（YAGNI）。

### 2.5 领域模型（Pydantic v2 语法，参照 F10 `domain/models/world.py`）

```python
def _validate_name(v: str, field: str = "名称", max_len: int = 50) -> str:
    """共享的名称校验：去空白后非空且不超过 max_len 字符."""
    stripped = v.strip()
    if not stripped:
        raise ValueError(f"{field}不能为空")
    if len(stripped) > max_len:
        raise ValueError(f"{field}不能超过 {max_len} 个字符")
    return stripped


def _validate_type(v: str) -> str:
    """情节点类型校验：去空白且不超过 20 字符（空串 = 未分类，允许）."""
    stripped = v.strip()
    if len(stripped) > 20:
        raise ValueError("情节点类型不能超过 20 个字符")
    return stripped


def _validate_description(v: str, field: str = "描述", max_len: int = 5000) -> str:
    """描述类字段校验：不超过 max_len 字符（不强制去空白）."""
    if len(v) > max_len:
        raise ValueError(f"{field}不能超过 {max_len} 个字符")
    return v


class Outline(BaseModel):
    """大纲领域实体. 对应 outlines 表."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str = ""
    sort_order: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class PlotPoint(BaseModel):
    """情节点领域实体. 对应 plot_points 表."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    outline_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    type: str = ""
    description: str = ""
    position: int = 0
    arc_id: uuid.UUID | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class StoryArc(BaseModel):
    """故事弧线领域实体. 对应 story_arcs 表."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str = ""
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class OutlineCreate(BaseModel):
    """创建大纲请求 DTO."""
    project_id: uuid.UUID
    name: str
    description: str = ""
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v, "大纲名", 50)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _validate_description(v, "大纲描述", 5000)

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, v: int) -> int:
        if v < 0:
            raise ValueError("排序权重不能为负数")
        return v


class OutlineUpdate(BaseModel):
    """更新大纲请求 DTO — 所有字段可选（exclude_unset 语义，同 F1）."""
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None

    # name/description/sort_order 复用 OutlineCreate 的校验逻辑（None 时直接返回）


class PlotPointCreate(BaseModel):
    """创建情节点请求 DTO — project_id 取自大纲，不在 body."""
    outline_id: uuid.UUID
    name: str
    type: str = ""
    description: str = ""
    position: int | None = None   # None = 追加到大纲末尾（max+1）
    arc_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v, "情节点名", 100)

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        return _validate_type(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _validate_description(v, "情节点描述", 5000)

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("排序位置不能为负数")
        return v


class PlotPointUpdate(BaseModel):
    """更新情节点请求 DTO.

    arc_id: None 表示不修改；"" 表示清除弧线归属（置为不挂弧线）.
    只有传入的字段会被更新，未传入的字段保持不变.
    """
    name: str | None = None
    type: str | None = None
    description: str | None = None
    position: int | None = None
    arc_id: uuid.UUID | str | None = None   # str "" = 清除弧线

    # name/type/description/position 复用 PlotPointCreate 的校验逻辑（None 时直接返回）


class StoryArcCreate(BaseModel):
    """创建故事弧线请求 DTO."""
    project_id: uuid.UUID
    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v, "弧线名", 50)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _validate_description(v, "弧线说明", 500)


class StoryArcUpdate(BaseModel):
    """更新故事弧线请求 DTO — 所有字段可选."""
    name: str | None = None
    description: str | None = None

    # 校验复用 StoryArcCreate（None 时直接返回）
```

### 2.6 生成相关模型（§5 详述）

```python
class GeneratedArc(BaseModel):
    """LLM 生成出的弧线（schema 校验用）.

    name 非法（空/超长）时该条被跳过并记录 warning，不影响其余落库.
    """
    name: str                                  # 1-50 去空白；非法 → 跳过 + warning
    description: str | None = None             # ≤ 500；None/空串 = 无说明


class GeneratedPlotPoint(BaseModel):
    """LLM 生成出的情节点（schema 校验用）.

    name 非法（空/超长）时该条被跳过并记录 warning，不影响其余落库.
    arc 为弧线名引用（须能在 arcs 列表或库中解析）；无法解析 → 跳过关联 + warning，
    情节点本身照常落库（arc_id=None）.
    """
    name: str                                  # 1-100 去空白；非法 → 跳过 + warning
    type: str | None = None                    # ≤ 20；None/空串 = 未分类
    description: str | None = None             # ≤ 5000；None/空串 = 无描述
    arc: str | None = None                     # 弧线名引用（落库时解析为 arc_id）


class GeneratedOutline(BaseModel):
    """LLM 生成的结构化大纲（schema 校验用，§5.2 模板输出）.

    name/description 缺省时回退到请求参数（request.name / ""）.
    """
    name: str | None = None
    description: str | None = None
    arcs: list[GeneratedArc] = []              # 可空
    plot_points: list[GeneratedPlotPoint] = []  # 可空（空 → warning）


class OutlineGenerateRequest(BaseModel):
    """AI 生成大纲请求."""
    project_id: uuid.UUID
    name: str | None = None    # 目标大纲名；缺省 "未命名大纲"（撞名 → 422）
    prompt: str | None = None  # 可选创作约束/设定摘要（自由文本，≤ 20000；None/空 = 无约束）
    num_chapters: int | None = None  # 可选规划章节数提示（1-100）
    save: bool = True          # True=自动落库；False=仅返回预览（不创建任何实体）
    model: str | None = None   # 覆盖项目默认模型（格式 provider/model_name）
    target_outline_id: uuid.UUID | None = None  # #668：追加目标大纲（§5.4 追加模式）；None=生成即新建


class OutlineGenerationResult(BaseModel):
    """大纲生成结果.

    save=True: outline/plot_points/arcs 为落库后的实体（含新 id）.
    save=False: preview 为生成的原始结构（未落库，无 id），outline 为 None.
    """
    saved: bool
    outline: Outline | None = None
    plot_points: list[PlotPoint] = []
    arcs: list[StoryArc] = []
    preview: GeneratedOutline | None = None    # 仅 save=False 时非空
    warnings: list[str] = []
    model: str
```

---

## 3. API 契约

端点风格沿用 F2/F9/F10：**创建/列表嵌套于项目或大纲路径**，**详情/更新/删除扁平**。错误响应格式沿用 F1/F2/F9/F10（`{"detail": "..."}` 404 / 422）。

### 3.1 端点总览（18 个，镜像 F10 §3.1 布局；情节点嵌套大纲、弧线嵌套项目）

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/projects/{project_id}/outlines` | 创建大纲 | `OutlineCreate` | 201 + Outline |
| GET | `/api/v1/projects/{project_id}/outlines` | 大纲列表 | Query: `?search=&sort_by=&sort_desc=&offset=&limit=` | 200 + `{items, total, offset, limit}`（含 point_count） |
| GET | `/api/v1/outlines/{outline_id}` | 大纲详情（含 plot_points 聚合） | — | 200 + Outline JSON |
| PATCH | `/api/v1/outlines/{outline_id}` | 更新大纲 | `OutlineUpdate` | 200 + Outline |
| DELETE | `/api/v1/outlines/{outline_id}` | 删除大纲（级联软删情节点） | Query: `?force=true` | 204（默认软删除） |
| POST | `/api/v1/outlines/{outline_id}/restore` | 恢复大纲（级联恢复情节点） | — | 200 + Outline |
| POST | `/api/v1/outlines/generate` | AI 生成大纲 | `OutlineGenerateRequest` | 200 + OutlineGenerationResult |
| POST | `/api/v1/outlines/{outline_id}/plot-points` | 创建情节点 | `PlotPointCreate` | 201 + PlotPoint |
| GET | `/api/v1/outlines/{outline_id}/plot-points` | 情节点列表（position 升序） | — | 200 + `{items, total}`（含 arc_name） |
| GET | `/api/v1/plot-points/{point_id}` | 情节点详情 | — | 200 + PlotPoint JSON（含 arc_name） |
| PATCH | `/api/v1/plot-points/{point_id}` | 更新情节点 | `PlotPointUpdate` | 200 + PlotPoint |
| DELETE | `/api/v1/plot-points/{point_id}` | 删除情节点 | Query: `?force=true` | 204（默认软删除） |
| POST | `/api/v1/plot-points/{point_id}/restore` | 恢复情节点 | — | 200 + PlotPoint |
| POST | `/api/v1/projects/{project_id}/story-arcs` | 创建弧线 | `StoryArcCreate` | 201 + StoryArc |
| GET | `/api/v1/projects/{project_id}/story-arcs` | 弧线列表 | — | 200 + `{items, total}`（含 point_count） |
| GET | `/api/v1/story-arcs/{arc_id}` | 弧线详情（含成员情节点 points 聚合） | — | 200 + StoryArc JSON |
| PATCH | `/api/v1/story-arcs/{arc_id}` | 更新弧线 | `StoryArcUpdate` | 200 + StoryArc |
| DELETE | `/api/v1/story-arcs/{arc_id}` | 删除弧线（成员 arc_id 置 NULL） | Query: `?force=true` | 204（默认软删除） |
| POST | `/api/v1/story-arcs/{arc_id}/restore` | 恢复弧线 | — | 200 + StoryArc |

> `POST /outlines/generate` 在 router 中注册于 `POST /outlines/{outline_id}/plot-points` 之前，避免路径歧义（同 F9 characters.py / F10 world_settings.py 做法）。

### 3.2 请求/响应示例 — 大纲 CRUD

**创建大纲**:
```http
POST /api/v1/projects/3f2e1d4a-.../outlines
Content-Type: application/json

{ "name": "第一卷大纲", "description": "主角觉醒与宗门初试锋芒", "sort_order": 1 }
```
→ 201
```json
{
  "id": "9b1c2d3e-...", "project_id": "3f2e1d4a-...", "name": "第一卷大纲",
  "description": "主角觉醒与宗门初试锋芒", "sort_order": 1,
  "extra": {}, "is_deleted": false,
  "created_at": "2026-08-01T10:00:00Z", "updated_at": "2026-08-01T10:00:00Z"
}
```

**列出大纲（搜索 + 分页）**:
```http
GET /api/v1/projects/3f2e1d4a-.../outlines?search=第一卷&sort_by=name&sort_desc=false&offset=0&limit=20
```
→ 200
```json
{
  "items": [
    {"id": "9b1c2d3e-...", "name": "第一卷大纲", "point_count": 8, "sort_order": 1, ...}
  ],
  "total": 1, "offset": 0, "limit": 20
}
```
> `point_count`（活动情节点数）由 API 层聚合，不入库。

**同名冲突**:
```http
POST /api/v1/projects/3f2e1d4a-.../outlines
{ "name": "第一卷大纲" }
```
→ 422 `{"detail": "同名大纲已存在（大纲名在项目内必须唯一）"}`

**大纲详情（含情节点聚合）**:
```http
GET /api/v1/outlines/9b1c2d3e-...
```
→ 200
```json
{
  "id": "9b1c2d3e-...", "project_id": "3f2e1d4a-...", "name": "第一卷大纲",
  "description": "...", "sort_order": 1, "extra": {}, "is_deleted": false,
  "created_at": "...", "updated_at": "...",
  "plot_points": [
    {"id": "...", "name": "主角登场", "type": "开篇", "description": "...",
     "position": 1, "arc_id": null, "arc_name": null},
    {"id": "...", "name": "金手指觉醒", "type": "转折", "description": "...",
     "position": 2, "arc_id": "7a8b9c0d-...", "arc_name": "主角成长线"}
  ]
}
```
> `plot_points` 为该大纲的**活动**情节点（position 升序），`arc_name` 由 API 层聚合（JOIN 弧线名），不入库。

**软删除 / 恢复 / 硬删除**（级联语义见 §7）:
```http
DELETE /api/v1/outlines/9b1c2d3e-...            → 204（软删除，情节点级联软删）
POST /api/v1/outlines/9b1c2d3e-.../restore      → 200 + Outline（情节点级联恢复）
DELETE /api/v1/outlines/9b1c2d3e-...?force=true → 204（物理删除，情节点级联物理删除）
```

### 3.3 请求/响应示例 — 情节点与弧线

**创建情节点**（嵌套于大纲路径）:
```http
POST /api/v1/outlines/9b1c2d3e-.../plot-points
Content-Type: application/json

{ "name": "主角登场", "type": "开篇", "description": "林尘在青云宗外门测试中展露废柴体质", "arc_id": null }
```
→ 201（PlotPoint JSON，position 自动分配 = 大纲末尾 +1）

**情节点列表**:
```http
GET /api/v1/outlines/9b1c2d3e-.../plot-points
```
→ 200 `{"items": [{"id": "...", "name": "主角登场", "type": "开篇", "position": 1, "arc_name": null, ...}], "total": 1}`

**更新情节点（清除弧线归属）**:
```http
PATCH /api/v1/plot-points/5a1b2c3d-...
{ "type": "发展", "arc_id": "" }
```
→ 200（更新后 PlotPoint JSON，arc_id 为 null）

**创建弧线 / 弧线列表**:
```http
POST /api/v1/projects/3f2e1d4a-.../story-arcs
{ "name": "主角成长线", "description": "林尘从废柴到强者的蜕变轨迹" }
```
→ 201（StoryArc JSON）
```http
GET /api/v1/projects/3f2e1d4a-.../story-arcs
```
→ 200 `{"items": [{"id": "...", "name": "主角成长线", "point_count": 3, ...}], "total": 1}`

**弧线详情（含成员情节点）**:
```http
GET /api/v1/story-arcs/7a8b9c0d-...
```
→ 200
```json
{
  "id": "7a8b9c0d-...", "project_id": "3f2e1d4a-...", "name": "主角成长线",
  "description": "...", "is_deleted": false, "created_at": "...", "updated_at": "...",
  "points": [
    {"id": "...", "outline_id": "9b1c2d3e-...", "outline_name": "第一卷大纲",
     "name": "金手指觉醒", "type": "转折", "position": 2}
  ]
}
```
> `points` 为该弧线的**活动**成员情节点（可能跨多个大纲），`outline_name` 由 API 层聚合，不入库。

**删除弧线**（成员自动解除关联，情节点本身不受影响）:
```http
DELETE /api/v1/story-arcs/7a8b9c0d-... → 204
```

### 3.4 请求/响应示例 — AI 生成大纲

**生成并落库（默认 save=true）**:
```http
POST /api/v1/outlines/generate
Content-Type: application/json

{
  "project_id": "3f2e1d4a-...",
  "name": "第一卷大纲",
  "prompt": "主角林尘，废柴体质逆袭；风格偏爽文；世界观：灵气复苏",
  "num_chapters": 30
}
```
→ 200
```json
{
  "saved": true,
  "outline": {"id": "9b1c2d3e-...", "name": "第一卷大纲", "description": "...", ...},
  "plot_points": [
    {"id": "...", "name": "主角登场", "type": "开篇", "description": "...", "position": 1, "arc_id": null},
    {"id": "...", "name": "金手指觉醒", "type": "转折", "description": "...", "position": 2,
     "arc_id": "7a8b9c0d-...", ...}
  ],
  "arcs": [
    {"id": "7a8b9c0d-...", "name": "主角成长线", "description": "...", ...}
  ],
  "warnings": ["情节点 \"？？\" 名称为空已跳过"],
  "model": "deepseek/deepseek-chat"
}
```

**仅预览（save=false，不落库）**:
```http
POST /api/v1/outlines/generate
{ "project_id": "3f2e1d4a-...", "save": false }
```
→ 200
```json
{
  "saved": false,
  "outline": null,
  "plot_points": [], "arcs": [],
  "preview": {
    "name": null,
    "description": "……",
    "arcs": [{"name": "主角成长线", "description": "……"}],
    "plot_points": [{"name": "主角登场", "type": "开篇", "description": "……", "arc": "主角成长线"}]
  },
  "warnings": [],
  "model": "deepseek/deepseek-chat"
}
```
> save=false 仅「试生成看效果」，不创建任何实体；确认保存需 save=true 重新生成或手动创建（「预览 → 确认 → 落库」闭环归 0.2.x，见 §10）。
> **#668 追加**：请求体可带 `target_outline_id`（UUID）——save=true 时生成的情节点**追加**到该既有大纲末尾（position 从 max+1 起，不新建大纲、不覆盖既有点，详见 §5.4 追加模式）；save=false 时该字段仅透传预览，不校验目标。

### 3.5 错误响应格式（沿用 F1/F2/F9/F10/ADR-012）

```json
// 404 — 资源不存在
{"detail": "项目不存在"}
{"detail": "大纲不存在"}
{"detail": "情节点不存在"}
{"detail": "弧线不存在"}

// 422 — 业务校验失败 / Pydantic 验证失败
{"detail": "同名大纲已存在（大纲名在项目内必须唯一）"}
{"detail": "同名弧线已存在（弧线名在项目内必须唯一）"}
{"detail": "弧线不存在于该项目"}
{"detail": "大纲名不能超过 50 个字符"}

// 500 — LLM 生成失败（日志记录原始异常，不泄漏堆栈）
{"detail": "大纲生成失败: LLM 输出无法解析，请重试"}
{"detail": "LLM 调用失败，请稍后重试"}
```

**异常映射表**:

| 异常/场景 | 状态码 | 响应 |
|-----------|--------|------|
| 项目/大纲/情节点/弧线不存在（Service 返回 None） | 404 | 见上 |
| 无效 UUID 格式 | 404 | 统一解析失败处理（同 F9/F10 `_parse_id`） |
| 同名大纲/弧线、弧线跨项目 | 422 | 服务层业务校验（`OutlineNameConflictError` / `ArcNameConflictError` / `ArcNotInProjectError`，消息即 detail） |
| Pydantic `ValidationError` | 422 | FastAPI 自动生成 |
| `OutlineGenerationError`（LLM 输出解析失败，重试后仍失败） | 500 | `"大纲生成失败: LLM 输出无法解析，请重试"` |
| `LLMRequestError`（F5 重试耗尽） | 500 | `"LLM 调用失败，请稍后重试"` |

---

## 4. CLI 命令签名

遵循 F7 §5 全局约定：`--json` 统一信封 `{"ok": true, "data": ...}` / `{"ok": false, "error": {"code", "message"}}`；退出码 0/1/2/130；错误码 NOT_FOUND / VALIDATION_ERROR / LLM_ERROR / DB_ERROR；删除类命令二次确认 + `--force`；`--json` + 无 `--force` 的删除 → `VALIDATION_ERROR`（沿用 F7 §7）。`outline` 组在 F11 落地时并入 F7 命令树（`cli/app.py` 注册，同 F9 character 组 / F10 world 组）。

### 4.1 outline 组（委托 OutlineService；情节点/弧线为子组，同 F9 group 子组布局）

```bash
inkflow outline create --project-id <uuid> --name <str> \
    [--description <str>] [--sort-order <int>] [--json]

inkflow outline list --project-id <uuid> \
    [--search <str>] \
    [--sort <name|updated_at|created_at>] [--sort-desc/--no-sort-desc] [--json]

inkflow outline get --id <uuid> [--json]          # 含情节点聚合

inkflow outline update --id <uuid> \
    [--name <str>] [--description <str>] [--sort-order <int>] [--json]

inkflow outline delete --id <uuid> [--force] [--permanent] [--json]
inkflow outline restore --id <uuid> [--json]
```

### 4.2 point 子组（嵌套于 outline 下；情节点是大纲的子实体）

```bash
inkflow outline point list --outline-id <uuid> [--json]

inkflow outline point create --outline-id <uuid> --name <str> \
    [--type <str>] [--description <str>] [--position <int>] [--arc-id <uuid>] [--json]
    # --position 缺省 = 大纲末尾追加

inkflow outline point update --id <uuid> \
    [--name <str>] [--type <str>] [--description <str>] [--position <int>] \
    [--arc-id <uuid|"">] [--json]       # --arc-id "" 表示清除弧线归属

inkflow outline point delete --id <uuid> [--force] [--json]
```

### 4.3 arc 子组（嵌套于 outline 下；弧线是项目级组织维度，同 F9 group 挂 project 但归角色域的布局）

```bash
inkflow outline arc list --project-id <uuid> [--json]

inkflow outline arc create --project-id <uuid> --name <str> [--description <str>] [--json]

inkflow outline arc update --id <uuid> [--name <str>] [--description <str>] [--json]

inkflow outline arc delete --id <uuid> [--force] [--json]
```

### 4.4 generate 子命令

```bash
inkflow outline generate --project-id <uuid> \
    [--name <str>] [--prompt <str>] [--prompt-file <path>] [--num-chapters <int>] \
    [--save/--no-save] [--model <str>] [--json]
    # --save 默认开启；--no-save 仅预览不落库
```

### 4.5 输出格式

```bash
# 默认人类可读
✅ 大纲创建成功: [第一卷大纲]
✅ 情节点创建成功: [主角登场] (开篇)
✅ 弧线创建成功: [主角成长线]
✅ 大纲生成并保存: [第一卷大纲]，含 8 个情节点、2 条弧线
🔍 大纲预览（未保存）: 8 个情节点、2 条弧线 —— 使用 --save 保存后落库
⚠️ 生成完成但有警告: 情节点 "？？" 名称为空已跳过; 情节点 "无名" 的弧线 "未命名线" 无法解析已跳过关联

# --json 输出
inkflow outline create --project-id ... --name "第一卷大纲" --json
→ {"ok": true, "data": {"id": "...", "name": "第一卷大纲", ...}}

inkflow outline generate --project-id ... --prompt "爽文, 废柴逆袭" --json
→ {"ok": true, "data": {"saved": true, "outline": {...}, "plot_points": [...],
     "arcs": [...], "warnings": [...], "model": "deepseek/deepseek-chat"}}

inkflow outline get --id 00000000-0000-0000-0000-000000000000 --json
→ {"ok": false, "error": {"code": "NOT_FOUND", "message": "大纲不存在"}}   # 退出码 1

inkflow outline delete --id ... --json
→ {"ok": false, "error": {"code": "VALIDATION_ERROR", "message": "删除需 --force 或交互确认"}}  # 退出码 1
```

**`--prompt-file` 设计理由**（同 F9/F10 `--text-file`）: 创作约束/设定摘要可达数千字，作为命令行参数在 Windows 下受 8191 字符限制；`--prompt` 与 `--prompt-file` 互斥（同时传入 → 退出码 2）。

---

## 5. AI 生成模式（关键差异：生成而非提取）

> ⚠️ **本节是 F11 与 F9/F10 样板的核心差异点**：管线**骨架**（模板渲染 → LLM → JSON 解析 → 修复式重试 → 单事务落库）复用 F9/F10 `_character_extractor.py` / `_world_extractor.py` 的实现模式（`_outline_generator.py` 对照实现）；但**输入、合并语义、落库策略**与提取模式不同，逐项差异见 §5.6。

### 5.1 模式总览

```text
 ┌──────────────────────────────────────────────────────────────┐
 │ 输入: OutlineGenerateRequest {project_id, name?, prompt?,     │
 │                               num_chapters?, save?, model?}   │
 └──────────────────────────┬───────────────────────────────────┘
                            ▼
 ① 校验项目存在（F1 ProjectRepository）→ 404；组装 project_info
    （项目名/类型/目标字数/写作风格/extra，不查 F9/F10 档案）
 ② 渲染 outline_generate.yaml（F5 PromptManager，变量: project_info/prompt/num_chapters）
 ③ LLMClient.chat(model or project.config.model, temperature=0.2)
 ④ 解析 JSON → Pydantic schema 校验（GeneratedOutline / GeneratedPlotPoint / GeneratedArc）
    ├─ 失败 → 修复式重试（附错误信息）≤ 2 次 → 仍失败 → OutlineGenerationError
 ⑤ 落库（save=True，单 DB session 事务）:
    ├─ 大纲: 同名活动冲突 → OutlineNameConflictError(422)；否则创建（生成即新建，无合并）
    ├─ 弧线: 按 (project_id, name) 匹配活动弧线 → 存在=复用 / 不存在=创建
    └─ 情节点: 按输出顺序分配 position（1,2,3...）；arc 名称解析为 arc_id
         （本批新建或库中已有）→ 无法解析 → 跳过关联 + warning
 ⑥ 返回 OutlineGenerationResult（saved/outline/plot_points/arcs/warnings/model；
    save=False → preview 原始结构，不落库）
```

**模式要点**:
1. **模板与代码分离**: 生成指令在 `infrastructure/llm/templates/outline_generate.yaml`（ADR-014/015），领域服务只组装变量（同 F9/F10）
2. **LLM 输出 schema 校验**: 用 Pydantic 模型校验原始 JSON，非法条目**跳过 + warning**，整批非法才抛错（同 F9/F10）
3. **生成上下文 = 项目基本信息 + 可选约束**: 不聚合 F9/F10 档案（角色/世界观）——MVP 由用户经 `prompt` 携带设定；自动聚合归 Phase 2+（§10）
4. **失败策略**: LLM 调用失败（F5 重试耗尽）→ 透传 `LLMRequestError`；解析失败重试 ≤2 → `OutlineGenerationError`；**落库阶段不重试**（已落库数据不可重复写入）
5. **单事务**: 大纲 + 弧线 + 情节点在同一个 session 内完成，任何异常回滚，无部分落库（同 F9/F10）
6. **save=false 不落库**: 管线只执行 ①-④ + 组装 preview，跳过 ⑤（不创建任何实体、不做同名检查）

### 5.2 LLM 模板（`outline_generate.yaml`）

```yaml
name: outline_generate
description: 根据项目设定与创作约束生成小说大纲（结构化 JSON 输出）
system_prompt: |
  你是小说大纲规划师。根据给定的项目信息与创作约束，生成一份完整的小说大纲。
  大纲由情节点序列构成：每个情节点是故事的关键节点，按故事发生顺序排列；
  情节点可归属到故事弧线（跨章节的情节发展线）。
  输出严格 JSON，不要输出任何其他文字，格式如下：
  {
    "outline": {"name": "大纲名", "description": "大纲总体描述"},
    "arcs": [
      {"name": "弧线名", "description": "弧线说明"}
    ],
    "plot_points": [
      {"name": "情节点名", "type": "开篇|发展|转折|高潮|结局", "description": "要点描述", "arc": "弧线名或 null"}
    ]
  }
  要求：
  - plot_points 必须按故事发生顺序排列（服务端按顺序分配位置）
  - type 从以下值中选择：开篇、发展、转折、高潮、结局；无法判断时留空
  - arc 必须引用 arcs 列表中的弧线名；没有归属则为 null
  - arcs 中不要包含重复的弧线名；plot_points 中不要包含重复的情节点名
  - 大纲名尽量简洁（不超过 50 字）
  {% if num_chapters %}请将情节点数量控制在约 {{ num_chapters }} 个，使每个情节点大致对应一段连续章节。{% endif %}
human_prompt: |
  项目信息：
  {project_info}

  创作约束：
  {prompt}
variables:
  - project_info
  - prompt
  - num_chapters
```

> `project_info` 由服务层组装（项目名/类型/目标字数/写作风格/extra 中的已有信息），格式为纯文本，不传 F9/F10 档案（§5.1 要点 3）。`num_chapters` 为可选的模板条件段（Jinja2，F5 PromptManager 支持）。

### 5.3 解析与重试（同 F9/F10 §5.3）

| 场景 | 行为 |
|------|------|
| 输出为合法 JSON 且通过 schema 校验 | 进入落库/预览 |
| 输出含代码块围栏/前后缀文字 | 提取首个 `{...}` 平衡片段（`_extract_json_fragment`），再解析 |
| 仍失败 | 构建修复 Prompt（原输出 + 解析错误信息 + 「只输出 JSON」）重试，`retry_count += 1`，≤ 2 次 |
| 3 次（1 次原始 + 2 次修复）均失败 | `OutlineGenerationError`（含原始输出片段，日志记录） |

> 与 F9/F10 一致：生成是批处理操作，无「部分可用」输出，失败必须显式报错而非静默返回。

### 5.4 落库策略（生成即新建 + 弧线复用）

**大纲（生成即新建，无合并语义）**:

| 情况 | 行为 | 计入 |
|------|------|------|
| 项目内无同名**活动**大纲 | 创建新大纲（name 取 LLM 输出的 name 或请求 name，缺省「未命名大纲」） | 落库 |
| 项目内存在同名**活动**大纲 | **422 冲突**（`OutlineNameConflictError`，生成不合并/不覆盖旧规划） | 报错 |
| 存在同名但已软删除 | 视为不存在 → 创建新大纲（partial unique 允许） | 落库 |

**弧线（按名复用，跨大纲组织维度）**:

| 情况 | 行为 | 计入 |
|------|------|------|
| 项目内存在同名**活动**弧线 | **复用**（不新建、不覆盖描述） | `arcs`（复用实例） |
| 不存在 | 创建新弧线 | `arcs`（新实例） |
| 弧线名非法（空/超长） | 该条跳过 | `warnings` |

**情节点（顺序落库 + 弧线引用解析）**:

| 情况 | 行为 | 计入 |
|------|------|------|
| name 合法 | 按输出顺序分配 position（1,2,3...）创建；arc 名可解析（本批新建或库中已有活动弧线）→ 挂 arc_id | `plot_points` |
| arc 名无法解析（LLM 幻觉/不在弧线列表且库中不存在） | **情节点照常创建**，arc_id=None（跳过关联） | `plot_points` + warning「情节点 X 的弧线 Y 无法解析已跳过关联」 |
| name 非法（空/超长）、type/description 超长 | 该条**跳过**（不影响其余落库） | `warnings` |

**幂等性说明（与提取模式的关键差异）**: 提取模式承诺「同文本二次提取 → 空 diff」；**生成模式不承诺幂等**——LLM 每次输出内容不同，重复生成会创建新大纲（同名则 422）。落库唯一性由大纲名唯一约束兜底，弧线复用保证组织维度不重复。

**追加模式（#668，`target_outline_id` 非空且 `save=true`）**：

| 情况 | 行为 | 计入 |
|------|------|------|
| 目标大纲存在且属于请求项目 | **不新建大纲**（跳同名检查、不回写大纲字段，generated.name/level/parent 忽略）；新生成情节点作为 target 的子级追加：单次 `next_position()` 取起点，按输出顺序批量递增（max+1, max+2, ...）；既有情节点零改动（无更新/删除）；弧线仍按上表「按名复用/新建」 | `outline`=target 实例，`plot_points`=**仅本次新增**（`point_count`=新增数） |
| 目标不存在或跨项目 | `OutlineNotFoundError` → 404「大纲不存在」（service 入口预检 + generator 落库前权威校验双层；LLM 调用前快速失败不耗 token） | 报错 |
| `target_outline_id` + `save=false` | 纯预览：不校验目标、零落库、不落库分支不触达（语义 = 既有预览） | `preview` |

> 追加 ≠ 覆盖：既有情节点的顺序/内容/归属保持不变，追加只增不改不删（替换/覆盖语义另行跟踪，#669）。
> 并发追加竞态（两请求同取 next_position）不处理——单用户本地工具，2.0 云域议题。

### 5.5 生成输入约束

| 约束 | 值 | 说明 |
|------|-----|------|
| prompt | 可选；提供时去空白非空，≤ 20000 字符 | 空/None = 无约束（仅用项目信息生成） |
| num_chapters | 可选，[1, 100] | 规划章节数提示（仅影响模板与 LLM，不强制） |
| 默认模型 | `project.config.model` | F1 项目配置 |
| temperature | 固定 0.2（结构化 JSON 输出低温稳定） | 不对外暴露（生成创意由 prompt 表达，同 F9/F10 决策） |
| 并发 | 不限制（单用户本地工具） | — |

### 5.6 生成 vs 提取：差异对照表

| 维度 | F9/F10 提取（样板） | F11 生成（本模块） |
|------|--------------------|--------------------|
| 输入 | 章节文本 `text`（必填） | 项目信息 + 可选 `prompt`/`num_chapters` |
| 方向 | 文本 → 实体（沉淀既有信息） | 设定 → 规划（创作新内容） |
| 模板 | `{module}_extract.yaml`（变量 text） | `outline_generate.yaml`（变量 project_info/prompt/num_chapters） |
| schema | ExtractedCharacter/WorldSetting | GeneratedOutline（outline+arcs+plot_points 三层） |
| 合并语义 | 同名 upsert（非空字段覆盖） | **生成即新建**（大纲同名 → 422 不覆盖）；弧线按名复用 |
| 落库策略 | 必然落库（无 save 参数） | `save` 参数：默认落库；`save=false` 仅预览不落库 |
| 幂等性 | 同文本二次提取 → 空 diff | 不承诺幂等（每次生成新内容） |
| 事务范围 | 单实体批合并 | 三实体（大纲+弧线+情节点）单事务新建 |

---

## 6. 大纲/弧线/情节点组织规则

（对应 F9 §6「关系图谱与分组管理规则」/ F10 §6「分类与查询规则」的位置；F11 无图谱，本节承载三实体的组织语义与查询规则）

### 6.1 大纲与情节点语义

- **大纲 = 一个规划版本**：项目下可有多个大纲（多版本规划，`sort_order` 排序）；同名唯一防止重复建档
- **情节点 = 大纲的骨架**：大纲的内容由有序情节点表达（position 升序）；情节点 type 提供宏观结构（开篇/发展/转折/高潮/结局），position 提供线性顺序——MVP 以此表达「结构化大纲」，不做卷/章/节树形表（§10）
- **级联规则**：大纲软删 → 情节点级联软删；大纲恢复 → 级联恢复（服务层：`soft_delete_outline` 内先删大纲再删其情节点）；大纲硬删 → 情节点物理删除（FK CASCADE）
- 软删除的大纲/情节点不进入任何查询结果

### 6.2 弧线语义

- 弧线是**项目级**组织维度（不挂大纲）：可串联多个大纲的情节点（跨规划版本追踪一条情节发展线）
- 弧线删除（软删除）→ 成员情节点 `arc_id` 置 NULL（情节点本身保留）；弧线恢复**不恢复**成员关联（同 F9 分组语义）
- 情节点与弧线是**一对一可选归属**（单 `arc_id`）；「情节点属多条弧线」的多对多不在范围（§10）
- `point_count` 为弧线内活动情节点数，由 API 层聚合

### 6.3 搜索与排序（大纲列表，沿用 F1 §6/F9 §6.3/F10 §6.2）

| 参数 | 默认值 | 约束 | 说明 |
|------|--------|------|------|
| `search` | — | — | 对 name 不区分大小写子串匹配（icontains） |
| `sort_by` | `updated_at` | `name` / `updated_at` / `created_at` | 排序字段 |
| `sort_desc` | `true` | — | 降序 |
| `offset` / `limit` | 0 / 50 | offset ≥ 0, limit [1, 100] | 分页 |

- **情节点列表**：固定 `position ASC, created_at ASC` 稳定排序，无排序/分页参数（大纲内情节点通常 ≤ 数百，YAGNI）
- **弧线列表**：固定 `name ASC`（组织维度按名浏览），无排序/分页参数
- 情节点/弧线**内容全文检索**不在 F11 范围（F22 搜索服务，§10）

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 创建大纲名为空/全空白 | 422: "大纲名不能为空" |
| 创建大纲名 > 50 字符 | 422: "大纲名不能超过 50 个字符" |
| 创建大纲名与项目内**活动**大纲重复 | 422: "同名大纲已存在（大纲名在项目内必须唯一）" |
| 软删除后**再创建同名大纲** | ✅ 成功（partial unique 排除已删除行；服务层同名检查仅限活动大纲） |
| 大纲 description > 5000 / sort_order < 0 | 422（字段校验） |
| 获取/更新/软删除/硬删除不存在的大纲 | 404: "大纲不存在" |
| 硬删除已软删除的大纲 | 404: "大纲不存在"（已排除） |
| 恢复不存在的大纲 | 404: "大纲不存在" |
| 恢复未删除的大纲 | 正常返回（重复操作无毒，同 F1） |
| 大纲软删除 | 204；其情节点**级联软删除** |
| 大纲恢复 | 200；其情节点**级联恢复** |
| 大纲硬删除 | 204；其情节点物理删除（FK CASCADE），弧线不受影响 |
| 创建情节点名为空/全空白 | 422: "情节点名不能为空" |
| 情节点名 > 100 字符 | 422: "情节点名不能超过 100 个字符" |
| type > 20 字符 | 422: "情节点类型不能超过 20 个字符" |
| position < 0 | 422: "排序位置不能为负数" |
| 创建情节点时大纲不存在 | 404: "大纲不存在" |
| 情节点 arc_id 指向不存在的弧线 | 422: "弧线不存在于该项目"（含跨项目/不存在统一处理） |
| 更新情节点 arc_id 清除（""） | ✅ 成功，arc_id 置 NULL |
| 获取/更新/删除不存在的情节点 | 404: "情节点不存在" |
| 创建弧线名与项目内活动弧线重复 | 422: "同名弧线已存在（弧线名在项目内必须唯一）" |
| 获取/更新/删除不存在的弧线 | 404: "弧线不存在" |
| 弧线软删除 | 204；成员情节点 arc_id 置 NULL（情节点保留） |
| 弧线恢复 | 200；**不恢复**成员关联 |
| 生成时项目不存在 | 404: "项目不存在" |
| 生成 prompt > 20000 字符 | 422: "创作约束不能超过 20000 个字符" |
| 生成 num_chapters 越界（<1 或 >100） | 422: "规划章节数需在 1-100 之间" |
| 生成 save=true 且大纲名与活动大纲重复 | 422: "同名大纲已存在（大纲名在项目内必须唯一）"（生成即新建，不覆盖） |
| 生成 save=false | 200 + preview；**不创建任何实体**、不做同名检查 |
| LLM 返回非 JSON / 无法解析 | 修复重试 ≤ 2 → 仍失败 → 500: "大纲生成失败: LLM 输出无法解析，请重试" |
| LLM 返回空情节点列表 | 200 + 空 plot_points + warning "未生成情节点"（save=true 时大纲/弧线照常落库） |
| LLM 输出中个别情节点/弧线非法（空名等） | 该条跳过 + warning，**不影响其余落库** |
| 情节点 arc 引用无法解析的名字 | 情节点照常创建（arc_id=None）+ warning（不创建悬空关联） |
| 生成时 LLM 调用失败（网络/Key） | 500: "LLM 调用失败，请稍后重试"（F5 已内部重试 3 次） |
| 落库中途 DB 错误 | 整体回滚（单事务），无部分落库 |
| 大纲列表搜索无结果 / 分页越界 | 200: 空 items（同 F1） |
| 弧线列表无活动弧线 | 200: `{"items": [], "total": 0}` |
| 项目硬删除 | 大纲/情节点/弧线级联物理删除（FK CASCADE）；项目软删除不影响数据 |
| `--prompt` 与 `--prompt-file` 同时传入 | CLI 退出码 2（用法错误） |
| 生成幂等性 | **不承诺**（每次生成新内容）；同名大纲由唯一约束兜底报 422 |

---

## 8. 文件结构

遵循 ADR-007v2 包结构，与 F9/F10 真实源码树一一对应。新增/修改文件：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── outline.py             ← CREATE: Outline, PlotPoint, StoryArc,
│   │   │                              OutlineCreate, OutlineUpdate, PlotPointCreate,
│   │   │                              PlotPointUpdate, StoryArcCreate, StoryArcUpdate,
│   │   │                              OutlineGenerateRequest, OutlineGenerationResult,
│   │   │                              GeneratedOutline, GeneratedPlotPoint, GeneratedArc
│   │   └── __init__.py            ← MODIFY: 导出新模型
│   ├── ports/
│   │   ├── outline_repository.py  ← CREATE: OutlineRepositoryProtocol
│   │   ├── outline_errors.py      ← CREATE: OutlineGenerationError / OutlineServiceError /
│   │   │                              OutlineNotFoundError / PlotPointNotFoundError /
│   │   │                              StoryArcNotFoundError / ProjectNotFoundError /
│   │   │                              OutlineNameConflictError / ArcNameConflictError /
│   │   │                              ArcNotInProjectError
│   │   └── __init__.py            ← MODIFY: 导出
│   └── services/
│       ├── outline_service.py     ← CREATE: OutlineService（三实体 CRUD + generate 入口）
│       ├── _outline_generator.py  ← CREATE: 生成管线（对照 F10 _world_extractor.py 骨架：
│       │                             模板渲染 → LLM → JSON 解析 → 修复重试 → 落库/预览）
│       └── __init__.py            ← MODIFY
├── infrastructure/
│   ├── llm/templates/
│   │   └── outline_generate.yaml  ← CREATE: 生成模板（§5.2）
│   └── database/
│       ├── models/
│       │   ├── outline.py         ← CREATE: OutlineORM, PlotPointORM, StoryArcORM
│       │   │                        （partial unique index, FK, soft-delete 标记）
│       │   └── __init__.py        ← MODIFY: 注册 3 个 ORM（create_tables 依赖）
│       └── repositories/
│           ├── outline_repo.py    ← CREATE: SQLiteOutlineRepository
│           └── __init__.py        ← MODIFY
├── api/
│   ├── routers/
│   │   ├── outlines.py            ← CREATE: 18 个端点（三实体 CRUD + generate）
│   │   └── __init__.py            ← MODIFY
│   ├── deps.py                    ← MODIFY: get_outline_service
│   └── app.py                     ← MODIFY: 注册 outlines.router
└── cli/
    ├── commands/
    │   ├── outline.py             ← CREATE: outline 组（create/list/get/update/delete/restore/
    │   │                              generate + point 子组 + arc 子组）
    │   └── __init__.py            ← MODIFY
    └── app.py                     ← MODIFY: 注册 outline 命令组

backend/tests/
├── unit/
│   ├── test_outline_models.py     ← CREATE: 领域模型/DTO 验证 + 生成 DTO schema
│   ├── test_outline_repo.py       ← CREATE: 仓储集成测试（in-memory SQLite，含级联/partial unique）
│   ├── test_outline_service.py    ← CREATE: 服务测试（三实体 CRUD + 业务校验 + 级联）
│   ├── test_outline_generation.py ← CREATE: 生成管线测试（Mock LLM：解析/重试/落库策略/弧线复用）
│   └── test_outline_api.py        ← CREATE: API 集成测试（Mock Service）
└── test_cli_outline.py            ← CREATE: CLI 测试（Mock OutlineService，信封/退出码）
```

> 测试文件位置与现有树一致（同 F9/F10）：仓储/API 集成测试放 `tests/unit/`，CLI 测试放 `tests/` 根。

### 8.1 OutlineRepositoryProtocol（参照 F10 `world_repository.py` Protocol 风格）

```python
class OutlineRepositoryProtocol(Protocol):
    """大纲/情节点/弧线仓储端口.

    按 spec §2.4: 项目内活动大纲/弧线 name 唯一（partial unique）；
    软删除后同名可复用。大纲软删 → 情节点级联（服务层编排
    soft_delete_points_of / restore_points_of）；弧线软删 → 成员
    arc_id 置 NULL（clear_arc_of_points）。

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9/F10）。
    """

    # ── Outline ──
    async def add(self, outline: Outline) -> Outline: ...
    async def get(self, outline_id: int) -> Outline | None: ...
    async def get_by_name(self, project_id: int, name: str) -> Outline | None: ...
    async def list(self, project_id: int, search: str | None = None,
                   sort_by: str = "updated_at", sort_desc: bool = True,
                   offset: int = 0, limit: int = 50) -> tuple[builtins.list[Outline], int]: ...
    async def update(self, outline: Outline) -> Outline: ...
    async def soft_delete(self, outline_id: int) -> bool: ...
    async def restore(self, outline_id: int) -> Outline | None: ...
    async def hard_delete(self, outline_id: int) -> bool: ...
    async def soft_delete_points_of(self, outline_id: int) -> None: ...  # 级联软删情节点
    async def restore_points_of(self, outline_id: int) -> None: ...      # 级联恢复情节点

    # ── PlotPoint ──
    async def add_point(self, point: PlotPoint) -> PlotPoint: ...
    async def get_point(self, point_id: int) -> PlotPoint | None: ...
    async def list_points(self, outline_id: int) -> builtins.list[PlotPoint]: ...  # position ASC
    async def list_points_by_arc(self, arc_id: int) -> builtins.list[PlotPoint]: ...
    async def next_position(self, outline_id: int) -> int: ...   # 大纲内 max(position)+1（无情节点时 = 1）
    async def update_point(self, point: PlotPoint) -> PlotPoint: ...
    async def soft_delete_point(self, point_id: int) -> bool: ...
    async def restore_point(self, point_id: int) -> PlotPoint | None: ...
    async def hard_delete_point(self, point_id: int) -> bool: ...
    async def clear_arc_of_points(self, arc_id: int) -> None: ...  # 弧线删除时成员 arc_id 置 NULL

    # ── StoryArc ──
    async def add_arc(self, arc: StoryArc) -> StoryArc: ...
    async def get_arc(self, arc_id: int) -> StoryArc | None: ...
    async def get_arc_by_name(self, project_id: int, name: str) -> StoryArc | None: ...
    async def list_arcs(self, project_id: int) -> builtins.list[StoryArc]: ...  # name ASC
    async def update_arc(self, arc: StoryArc) -> StoryArc: ...
    async def soft_delete_arc(self, arc_id: int) -> bool: ...
    async def restore_arc(self, arc_id: int) -> StoryArc | None: ...
    async def hard_delete_arc(self, arc_id: int) -> bool: ...
```

> 仓储层方法入参用 int（与 F9/F10 RepositoryProtocol 一致）；Service 负责 UUID ↔ int 转换（沿用 F1 `_to_int_id` 模式）。`next_position` 在 `add_point` 前调用（position=None 时）。

---

## 9. 测试策略

### 测试层次（沿用 ADR-018 三层目录 + pytest markers；六层结构同 F9/F10 §9）

```text
单元测试: 领域模型/DTO 验证 + 生成 DTO schema           ~14 cases
集成测试: SQLiteOutlineRepository（in-memory SQLite）    ~18 cases
服务测试: OutlineService（Mock Repository）              ~16 cases
生成测试: 生成管线（Mock LLM，全落库/预览分支）           ~15 cases
API 测试: 18 端点（Mock Service）                       ~20 cases
CLI 测试: outline 组（Mock OutlineService）             ~20 cases
```

### 关键测试场景

**领域模型**: 三实体 name 空/空白/超长 → ValidationError / type 空串合法、超长 → ValidationError / position 负数 → ValidationError / description 超长 → ValidationError / OutlineUpdate/PlotPointUpdate 部分更新语义（arc_id None 不修改、"" 清除）/ PlotPointCreate position=None 合法 / GeneratedOutline schema（plot_points 可空、GeneratedPlotPoint.arc 可空）/ OutlineGenerateRequest（prompt 超长 → 422、num_chapters 越界 → 422、save 默认 True）

**仓储**: 三实体 CRUD 往返 / `get_by_name`（大纲/弧线）命中与未命中 / 活动同名唯一（partial unique：插入第二个活动同名 → IntegrityError；软删除后可再插同名）/ 软删除后 get 返回 None / `next_position`（空大纲 → 1、追加 → max+1）/ `list_points` position ASC 稳定排序 / `list_points_by_arc` 按弧线聚合 / `clear_arc_of_points`（弧线删除 → 成员 arc_id NULL）/ 大纲软删级联情节点（`soft_delete_points_of`）/ 恢复级联 / `list` 搜索与分页 / 弧线列表 name ASC / 硬删除 FK 级联（大纲硬删 → 情节点级联；项目硬删 → 三实体级联）

**服务**: 三实体创建/更新/软删/恢复全流程 / 同名活动大纲 → 422 / 同名活动弧线 → 422 / arc_id 跨项目或不存在 → 422 / 大纲不存在各操作 → None → 404 / 大纲软删 → 级联情节点软删编排 / 大纲恢复 → 级联恢复 / 弧线软删 → 成员 arc_id 置 NULL 编排 / generate 入口编排（项目不存在 → 404；generator/project_repo 未注入 → 配置错误）

**生成（Mock LLM，遵循 ADR-015；断言同 F9/F10）**:
- 合法 JSON → save=true 全落库：大纲/弧线/情节点计数正确，position 从 1 递增
- 弧线复用：库中已有同名活动弧线 → 不新建、情节点挂既有 arc_id
- 弧线名无法解析（情节点 arc 引用）→ 情节点照常创建 + warning
- 非法条目（空名/超长）→ 跳过 + warning，其余正常落库
- 大纲名与活动大纲冲突（save=true）→ OutlineNameConflictError（422 语义）
- 软删除同名大纲 → 新建（不隐式恢复）
- 输出带围栏/前缀文字 → `_extract_json_fragment` 提取成功
- 输出完全非法 → 修复重试 2 次 → OutlineGenerationError
- Mock LLM 抛 LLMRequestError → 透传（不消耗解析重试）
- 空情节点列表 → 大纲/弧线照常落库 + warning「未生成情节点」
- save=false → 返回 preview（GeneratedOutline），**零落库**（断言 repo 无 add 调用、无同名检查）
- 断言 Prompt 使用 outline_generate 模板 + 变量 project_info/prompt/num_chapters + 项目默认模型 + temperature 0.2

**API**: 18 端点成功路径 / 404 全路径（项目/大纲/情节点/弧线）/ 422 业务校验（同名大纲、同名弧线、arc 跨项目、字段超长）/ generate 200（save=true/false 两态）/ generate LLM 失败 → 500 / 大纲详情含 plot_points 聚合（arc_name）/ 弧线详情含 points 聚合（outline_name）/ 大纲列表 point_count / 无效 UUID → 404

**CLI**: 各子命令成功路径与参数透传 / 信封格式与退出码 0/1/2 / delete 二次确认 + `--force` / `--json` + delete 无 `--force` → VALIDATION_ERROR / `--prompt` 与 `--prompt-file` 互斥 → 退出码 2 / generate 人类可读摘要（保存 vs 预览）与 `--json` 完整结果 / NOT_FOUND、LLM_ERROR 错误信封

### 覆盖率目标

- F11 模块行覆盖率 **≥ 80%**（DTO 验证 100%、落库策略全分支、级联路径，同 F9/F10）
- 全仓覆盖率 **≥ 60%**（0.2.0 DoD，ADR-019）
- CI 门禁：ruff + mypy + pytest 全绿（ADR-017/018）

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|----------|
| 大纲 ↔ 实际章节自动映射（情节点绑定 chapter_id、生成时自动建章） | **Phase 2+**——F2 管实际章节，F11 管规划层；映射需要写作状态联动，超出 3-4 人天 MVP |
| 卷/章/节**树形**大纲结构（OutlineNode 层级表，节点含标题/摘要/子节点） | Phase 2+——MVP 以「大纲 + 有序情节点（type/position）」表达结构（决策见 §2.2/§12）；F2 已有卷/章实体，不重复建树 |
| 多版本大纲对比 / 差异 diff | Phase 2+（F15 审计或独立功能） |
| 拖拽排序 UI / 批量重排（position 自动重排算法） | F18 Web UI（0.3.0）；MVP 支持手动设置 position |
| 生成「预览 → 确认 → 落库」闭环（draft 持久化） | 0.2.x 增强；MVP 以 save=false 试生成 + save=true 落库代替 |
| 生成时自动聚合角色/世界观档案（F9/F10 Repository 查询作为上下文） | Phase 2+——MVP 由用户经 prompt 携带设定，F11 不依赖 F9/F10（见 §11） |
| 情节点多对多弧线 / 弧线层级（子弧线） | Phase 2+（MVP 一对一可选归属） |
| 情节点依赖图 / 节点间关系表（「转折 A 触发 高潮 B」） | 避免过度设计（P5 YAGNI）——规划管理不是项目管理工具，简单外键组织即可 |
| 受控情节点类型词表（枚举/自定义类型库） | F14 定义（F11 用自由文本 ≤20 字符 + 建议值清单，同 F10 category 处理） |
| F6 `outline` 数据源改造（ProjectConfigOutlineSource 改为读 F11 Repository） | 集成点，见 §11 与待澄清 Q1 |
| 大纲变更审计日志 | F15 审计服务（Issue 待创建） |
| 写作时按大纲推进检查（当前章对应哪个情节点） | F16 一致性审计（Phase 2）/ F3 集成 |
| 大纲/情节点内容全文检索 | F22 搜索服务（Phase 3） |
| 跨项目大纲共享/引用/合并 | Phase 4 云端 |
| 大纲可视化（时间线/流程视图）/ 导出 | F18 Web UI（0.3.0）/ F21 导出服务（0.6.0） |

---

## 11. 依赖关系

与 F1 §11 / F2 §11 / F9 §11 / F10 §11 已声明依赖保持一致（F10 被依赖列表含 F6/F7/F14/F15/F20；F11 同构并在其上调整）：

```text
F11 依赖:
  F1 (project_service) ✅ — 项目存在性校验（404）；project.config.model 作为生成默认模型；
                            project_info 组装（项目名/类型/目标字数/写作风格/extra）
  F5 (llm_service)     ✅ — LLMClientProtocol.chat + PromptTemplateProtocol
                            （outline_generate 模板，ADR-014/015 隔离：domain/ 零 LangChain
                            import，CI 强制检查）
  F9/F10 (角色/世界观)  — 不依赖：生成上下文不聚合角色/世界观档案（MVP 经 prompt 携带，
                           自动聚合归 Phase 2+，§10）
  F2 (chapter_service) — 边界声明（非硬依赖）：F11 管「写作前规划」，F2 管「已创建卷/章」；
                           不互相绑定，映射归 Phase 2+（§10）

F11 被依赖:
  F6 (context_service) ✅ — outline 数据源（protected 层，见 F6 spec §3.2）：
                            F6 已有 ProjectConfigOutlineSource（infrastructure/context/sources.py，
                            读 project.config.extra["outline"]，**已实现**——与 F9/F10 的
                            Character/WorldSettingSource 空实现不同）；F11 实体化大纲落地后，
                            该源是否改为读 F11 Repository（大纲/情节点 → 注入上下文）
                            实现归属待澄清（Q1，见下）
  F7 (CLI)             ✅ — outline 命令组并入 F7 命令树（cli/app.py 注册）
  F14 (统一提取)        ⏳ — (#44) 大纲作为提取目标类型之一（提取文本 → 更新/追加情节点）；
                            复用 F11 的实体/唯一键约定
  F15 (审计)            ⏳ — (Issue 待创建) 大纲/情节点/弧线变更作为审计数据源
  F20 (MCP)             ⏳ — (Phase 3) manage_outline 工具基于本模块 API
```

> ⚠️ **编号口径说明**: F6 spec §3.2 表格中 outline 数据源标注「（F10 落地后替换）」为 ADR-019 之前的旧编号（旧口径 F10=大纲）；按 [ADR-019](../../adr/packaging/ADR-019.md) 现行口径 **F11 = 大纲管理**、F10 = 世界观。本 spec 及后续 F 模块一律以 ADR-019 为准（与 F9/F10 spec §11 同一声明）。
> **与 F9/F10 的 Q1 差异**: F9/F10 的 Character/WorldSettingSource 是**空实现**（替换 = 填充实现）；F11 的 outline 源是**已实现的 config 通道**（替换 = 迁移数据通道，影响面更大——涉及 `project.config.extra["outline"]` 既有数据），因此 F6 源改造归属更需要评审确认（Q1）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| 三实体建模 | Outline（项目级）+ PlotPoint（大纲级，arc_id 可选挂弧线）+ StoryArc（项目级） | PRD P1-03「结构化大纲/情节点/故事弧线」三概念一一对应；弧线是跨大纲的组织维度（项目级），情节点是单个大纲的骨架（大纲级） |
| 大纲结构表达 | MVP 以「大纲 + 有序情节点序列」表达结构化大纲，**不建卷/章/节树形表** | F2 已有卷/章实体（实际章节层），F11 不重复建树；情节点 type（开篇/发展/转折/高潮/结局）+ position 提供宏观结构与线性顺序；树形大纲（OutlineNode 自引用表）归 Phase 2+（P5 YAGNI） |
| 情节点归属 | 情节点挂 outline_id（大纲级），不直接挂 project | 情节点是大纲的组成元素（一个规划版本的骨架）；弧线（项目级）提供跨大纲的第二个组织维度 |
| 弧线组织 | 弧线项目级 + 情节点一对一可选 arc_id；**不做依赖图/节点关系表** | 弧线是「组织维度」而非图谱边（与 F9 角色关系不同）；简单外键组织即可，避免过度设计（P5 YAGNI） |
| 同名语义 | 「项目内活动大纲/弧线 name 唯一」；情节点允许重名 | 大纲/弧线同名唯一防止重复建档且是生成时弧线复用的锚点；情节点无自然唯一键（「高潮」可多次出现） |
| 唯一约束实现 | SQLite partial unique index（`WHERE is_deleted = 0`） | 软删除后再创建同名实体合法；比「服务层检查 + 全表唯一」更稳（DB 兜底，同 F9/F10） |
| **生成模式（关键差异）** | **生成即新建**：大纲同名 → 422 不覆盖；弧线按名复用；无 upsert 合并 | 提取是「沉淀既有信息」（同名=同一实体，需合并）；生成是「创作新规划」（同名=冲突，覆盖会丢失旧规划）；弧线是组织维度（复用不冲突） |
| 生成落库策略 | `save` 参数：默认自动落库；save=false 仅预览（不落库、无确认闭环） | 任务上下文建议「生成返回结构化结果 + 可选自动保存参数」；预览-确认闭环需要 draft 持久化，归 0.2.x（YAGNI） |
| 生成上下文 | project_info（F1 项目基本信息）+ 可选 prompt/num_chapters；**不查 F9/F10 档案** | 保持 F11 依赖面最小（仅 F1/F5）；自动聚合角色/世界观归 Phase 2+（用户可经 prompt 携带设定） |
| 生成重试 | 解析失败修复式重试 ≤ 2 次（F3/F9/F10 模式），落库阶段不重试 | 生成无部分可用输出，失败显式报错；落库重试会导致重复写入 |
| 生成温度 | 固定 0.2 低温 | 结构化 JSON 输出稳定性优先（F3/F9/F10 先例）；创意由 prompt 表达 |
| 生成模板 | `outline_generate.yaml` 走 F5 PromptManager | ADR-014/015：模板与代码分离、domain/ 零 LangChain |
| 生成管线 | **复用 F9/F10 §5 骨架**（对照 `_world_extractor.py` 实现），仅替换实体/模板/落库语义 | 不重新设计管线；差异集中在本 spec §5.6 对照表 |
| 级联规则 | 大纲软删 → 情节点级联软删/恢复；弧线软删 → 成员 arc_id 置 NULL（不级联删情节点、不恢复关联） | 大纲是情节点的容器（容器级联）；弧线是组织维度（同 F9 分组语义：解除关联不删成员） |
| 端点布局 | 创建/列表嵌套（大纲挂项目、情节点挂大纲、弧线挂项目），详情扁平（同 F2/F9/F10） | 与既有端点风格一致，OpenAPI 分组清晰 |
| generate 端点 | `POST /api/v1/outlines/generate`（动作型，返回 200；save 参数控制落库） | 与 F3 writing / F9 extract / F10 extract 动作型端点一致；单次同步调用，不做任务队列（YAGNI） |
| CLI 布局 | `inkflow outline` 顶级组 + `point`/`arc` 子组 | 情节点是大纲的子实体、弧线是规划域组织维度（同 F9 character group 三级嵌套先例）；避免顶级命令膨胀 |
| 生成输入 | `--prompt` / `--prompt-file` 双通道 | Windows 命令行参数 8191 字符限制，长约束需文件通道（同 F9/F10 `--text-file`） |
| 落库事务 | 大纲+弧线+情节点单 session 事务，失败全回滚 | 无部分落库；生成失败不会留下半套规划 |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 领域模型 + DTO 验证（三实体 + 生成 DTO schema，含 partial unique 语义） | `pytest tests/unit/test_outline_models.py -v` 全绿 |
| M2 | 仓储层全部方法（三实体 CRUD + 级联 + 唯一约束 + next_position/clear_arc） | `pytest tests/unit/test_outline_repo.py -v` 全绿 |
| M3 | 服务层 CRUD + 业务校验（同名/arc 归属/级联编排） | `pytest tests/unit/test_outline_service.py -v` 全绿 |
| M4 | AI 生成管线（解析/重试/落库策略/弧线复用/save 两态，Mock LLM） | `pytest tests/unit/test_outline_generation.py -v` 全绿 |
| M5 | API 18 端点 + 错误路径全绿 | `pytest tests/unit/test_outline_api.py -v` 全绿 |
| M6 | CLI outline 组（信封/退出码/确认交互/point+arc 子组/generate） | `pytest tests/test_cli_outline.py -v` 全绿 |
| M7 | 真实 LLM 联调：对项目执行 generate 成功落库（含弧线复用） | 手工验证（配置任一 Provider Key，`inkflow outline generate`；二次生成验证同名 422 与弧线复用） |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest -v` 全绿；F11 模块行覆盖 ≥ 80%、全仓 ≥ 60%（0.2.0 DoD）；ruff + mypy 通过（CI 门禁 ADR-017） |
| M9 | domain/ 零 LangChain import | CI 强制检查通过（沿用 F5/F6/F9/F10 约束） |

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | F6 `ProjectConfigOutlineSource`（`infrastructure/context/sources.py`，读 `project.config.extra["outline"]`，**已实现**）在 F11 实体化大纲落地后是否改为读 F11 Repository？改造归属 F11 还是 0.2.0 内 F6 联调任务？**注意与 F9/F10 的差异**：F9/F10 的数据源是空实现（填充即可），outline 源是已工作的 config 通道（改造 = 迁移数据通道，涉及既有 `config.extra["outline"]` 数据） | 影响 F11 收尾范围、F6 文件修改归属与既有 config 大纲数据的兼容策略 | 建议：F11 只交付实体/查询能力；F6 源改造作为 0.2.0 内 F6 联调任务单独列出（改造前 config 通道继续可用，不阻塞） |
| Q2 | 生成落库策略确认：MVP 按「默认自动落库（save=true）+ save=false 试生成预览（无确认闭环）」实现（本 spec 已按此设计）；是否需要「预览 → 确认 → 落库」闭环（draft 持久化，用户确认后保存）？ | 影响 generate API 与落库流程（闭环需新增 draft 存储与确认端点） | 建议：MVP 无闭环（save=false 仅试生成）；确认式保存归 0.2.x（任务上下文建议已采纳） |
| Q3 | 弧线/情节点关系确认：情节点挂大纲（outline_id）+ 可选挂弧线（arc_id，弧线项目级、跨大纲复用）；是否需要「情节点直接挂项目（不挂大纲）」或「弧线挂大纲（每条弧线限定单大纲）」？ | 影响数据模型与 API 路径（情节点/弧线的嵌套层级） | 建议：按本 spec 设计——情节点是大纲的骨架（挂大纲），弧线是跨大纲的组织维度（挂项目）；多对多弧线归 Phase 2+ |

---

*本文档为 F11 功能规格（What），实施步骤（How）见后续 `specs/f11-outline/plan.md`。所有里程碑验收以本节 M1-M9 为准。*
## 14. 动作确认

> 每个端点/命令的完整状态流表（基于 §3 API + §4 CLI + §7 边界事实，不重复）。

### 14.1 端点状态流（§3.1 枚举 19 端点，表头标注 18）

| 端点 | 前置条件 | 动作/状态转换 | 成功 | 失败 | 边界 |
|------|---------|--------------|------|------|------|
| POST /projects/{project_id}/outlines | 项目存在 | 校验 name（非空/≤50/项目内活动唯一）→ 创建 | 201 + Outline | 404「项目不存在」；422「大纲名不能为空」/「大纲名不能超过 50 个字符」/「同名大纲已存在（大纲名在项目内必须唯一）」 | description>5000 / sort_order<0 → 422；软删后同名可再建（partial unique） |
| GET /projects/{project_id}/outlines | 项目存在 | 搜索/排序/分页 → 过滤活动大纲 | 200 + {items,total,offset,limit}（含 point_count 聚合） | 404「项目不存在」 | search 空不过滤；limit≤100；分页越界 → 空 items |
| GET /outlines/{outline_id} | 大纲存在 | 查询 + plot_points 聚合（活动、position 升序、arc_name JOIN） | 200 + Outline JSON | 404「大纲不存在」 | 无效 UUID → 404（_parse_id） |
| PATCH /outlines/{outline_id} | 大纲存在 | 部分更新（exclude_unset） | 200 + Outline | 404「大纲不存在」；422（name 非法/同名冲突） | 字段不传=不改 |
| DELETE /outlines/{outline_id} | 大纲存在 | 软删除 + 情节点级联软删 | 204 | 404「大纲不存在」（不存在/已软删） | 不传 force=软删；?force=true=物理删除（情节点 FK CASCADE 级联物理删，弧线不受影响） |
| POST /outlines/{outline_id}/restore | 大纲存在（硬删除外） | 恢复 + 情节点级联恢复 | 200 + Outline | 404「大纲不存在」 | 未软删时恢复=无操作成功；硬删后不可恢复 |
| POST /outlines/generate | 项目存在 | LLM 生成（修复重试 ≤2）→ save=true 落库 / save=false 仅预览 | 200 + OutlineGenerationResult（saved/outline/plot_points/arcs/warnings/model 或 preview） | 404「项目不存在」；422（prompt>20000「创作约束不能超过 20000 个字符」/num_chapters 越界「规划章节数需在 1-100 之间」/save=true 同名大纲）；500「大纲生成失败: LLM 输出无法解析，请重试」/「LLM 调用失败，请稍后重试」 | save=false 不创建任何实体、不做同名检查；空情节点列表 → 200 + warning「未生成情节点」；个别非法条目跳过 + warning 不影响其余落库；落库单事务整体回滚 |
| POST /outlines/{outline_id}/plot-points | 大纲存在 | 校验 → 创建（position=大纲末尾+1） | 201 + PlotPoint | 404「大纲不存在」；422「情节点名不能为空」/「情节点名不能超过 100 个字符」/「情节点类型不能超过 20 个字符」/「排序位置不能为负数」/「弧线不存在于该项目」 | arc_id 可空；arc_id 跨项目/不存在统一 422 |
| GET /outlines/{outline_id}/plot-points | 大纲存在 | 列表（position 升序，arc_name 聚合） | 200 + {items,total} | 404「大纲不存在」 | — |
| GET /plot-points/{point_id} | 情节点存在 | 查询 | 200 + PlotPoint（含 arc_name） | 404「情节点不存在」 | — |
| PATCH /plot-points/{point_id} | 情节点存在 | 部分更新（含 arc_id 清除） | 200 + PlotPoint | 404「情节点不存在」；422 字段校验 | arc_id="" → 置 null |
| DELETE /plot-points/{point_id} | 情节点存在 | 软删除 | 204 | 404「情节点不存在」 | ?force=true 物理删除 |
| POST /plot-points/{point_id}/restore | 情节点存在（硬删除外） | 恢复 | 200 + PlotPoint | 404「情节点不存在」 | — |
| POST /projects/{project_id}/story-arcs | 项目存在 | 校验 name（项目内活动唯一）→ 创建 | 201 + StoryArc | 404「项目不存在」；422「同名弧线已存在（弧线名在项目内必须唯一）」 | — |
| GET /projects/{project_id}/story-arcs | 项目存在 | 列表（含 point_count） | 200 + {items,total} | 404「项目不存在」 | 无活动弧线 → 空 items |
| GET /story-arcs/{arc_id} | 弧线存在 | 查询 + points 聚合（跨大纲成员，outline_name JOIN） | 200 + StoryArc JSON | 404「弧线不存在」 | — |
| PATCH /story-arcs/{arc_id} | 弧线存在 | 部分更新 | 200 + StoryArc | 404「弧线不存在」；422 同名冲突 | — |
| DELETE /story-arcs/{arc_id} | 弧线存在 | 软删除（成员情节点 arc_id 置 NULL，情节点保留） | 204 | 404「弧线不存在」 | ?force=true 物理删除 |
| POST /story-arcs/{arc_id}/restore | 弧线存在（硬删除外） | 恢复（**不恢复**成员关联） | 200 + StoryArc | 404「弧线不存在」 | — |

### 14.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| outline create | 项目存在 | 创建 | 「✅ 大纲创建成功: [第一卷大纲]」/ --json | 404 NOT_FOUND；422 VALIDATION_ERROR | — |
| outline list | 项目存在 | 列表（--search/--sort） | 列表 / JSON | 404 | — |
| outline get | 大纲存在 | 查询（含情节点聚合） | JSON | 404「大纲不存在」 | — |
| outline update | 大纲存在 | 更新 | JSON | 404；422 | — |
| outline delete | 大纲存在 | 二次确认（--force 跳过）→ 软删；--permanent 硬删 | 204 | 404；--json 无 --force → VALIDATION_ERROR「删除需 --force 或交互确认」（退出码 1） | — |
| outline restore | 大纲存在 | 恢复（级联恢复情节点） | 200 | 404 | — |
| outline point list | 大纲存在 | 列表 | 列表 / JSON | 404 | — |
| outline point create | 大纲存在 | 创建（--position 缺省=末尾追加） | 「✅ 情节点创建成功: [主角登场] (开篇)」 | 404；422 | — |
| outline point update | 情节点存在 | 更新（--arc-id "" 清除弧线归属） | JSON | 404；422 | — |
| outline point delete | 情节点存在 | 二次确认（--force） | 204 | 404；--json 无 --force → VALIDATION_ERROR | — |
| outline arc list | 项目存在 | 列表 | 列表 / JSON | 404 | — |
| outline arc create | 项目存在 | 创建 | 「✅ 弧线创建成功: [主角成长线]」 | 404；422 同名 | — |
| outline arc update | 弧线存在 | 更新 | JSON | 404；422 | — |
| outline arc delete | 弧线存在 | 二次确认（--force） | 204 | 404；--json 无 --force → VALIDATION_ERROR | — |
| outline generate | 项目存在 | AI 生成（--save 默认开/--no-save 预览；--model） | 「✅ 大纲生成并保存: [...]，含 8 个情节点、2 条弧线」/「🔍 大纲预览（未保存）: ...」/「⚠️ 生成完成但有警告: ...」；--json 信封 | 404；422；500 LLM_ERROR | --prompt 与 --prompt-file 互斥（同传 → 退出码 2）；错误码 NOT_FOUND/VALIDATION_ERROR/LLM_ERROR/DB_ERROR |

### 14.3 验收锚点（写入 §14）

- A1：POST outlines 空 name → 422「大纲名不能为空」（非 500/非 422 原文泄漏）
- A2：同名大纲 → 422「同名大纲已存在（大纲名在项目内必须唯一）」；软删后再建同名 → 成功
- A3：DELETE outlines → 204 后其情节点级联软删（GET plot-points 不含）；restore → 级联恢复
- A4：generate save=false → 200 + preview 且不创建任何实体；save=true 同名 → 422
- A5：generate LLM 输出无法解析（重试后仍失败）→ 500「大纲生成失败: LLM 输出无法解析，请重试」
- A6：弧线软删 → 204 且成员情节点 arc_id 置 NULL（情节点保留）；弧线恢复 → 不恢复成员关联

### 14.4 Spec 漂移标注（追加时核对实现 routers/outlines.py）

- **restore 端点缺失**：spec §3.1/§4.1 声明的 `POST /outlines/{outline_id}/restore`、`POST /plot-points/{point_id}/restore`、`POST /story-arcs/{arc_id}/restore` 及 CLI `outline restore` 在实现中缺失（routers/outlines.py 无 restore 路由；services 无 restore 方法；CLI 无 restore 命令）——恢复能力未落地，且 §3.1 表头「18 个」与枚举 19 端点不符（次要）。
- **实现侧新增端点**：`GET /outlines/by-volume/{volume_id}` 为 spec §3.1 未声明端点（疑 F56 卷-大纲关联功能）——实现路由 17 条 vs spec 枚举 19 端点，构成不同。
