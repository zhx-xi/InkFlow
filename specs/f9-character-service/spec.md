# F9: 角色管理 (character_service) — 功能规格

> **Spec 版本**: 1.1 | **日期**: 2026-08-23 | **依据**: PRD v2.1 §6.2 P1-01, Constitution P1-P6, ADR-019
> **所属阶段**: Phase 2 — 创作工具链（0.2.0 里程碑第一个模块，估算 4-6 人天）
> **关联 Issues**: [#39](https://github.com/zhx-xi/InkFlow/issues/39), [#593](https://github.com/zhx-xi/InkFlow/issues/593)（brief 字段）
> **依赖**: F1 ✅, F2 ✅, F5 ✅（前置）；F6 ✅（数据源集成点，见 §11 与待澄清 Q1）
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md) (模块化单体), [ADR-002](../../adr/ADR-002.md) (六边形分层), [ADR-003](../../adr/ADR-003.md) (Repository), [ADR-004](../../adr/ADR-004.md) (Pydantic v2), [ADR-007v2](../../adr/ADR-007v2.md) (包结构), [ADR-010](../../adr/ADR-010.md) (上下文分层), [ADR-012](../../adr/ADR-012.md) (错误处理), [ADR-014](../../adr/ADR-014.md) (ChatPromptTemplate), [ADR-015](../../adr/ADR-015.md) (LangChain 隔离), [ADR-016](../../adr/ADR-016.md) (loguru), [ADR-017](../../adr/ADR-017.md) (CI 门禁), [ADR-018](../../adr/ADR-018.md) (测试分层), [ADR-019](../../adr/ADR-019.md) (版本里程碑)
> **状态**: ✅ 已实现（PR #56）

> **Spec 变更（v1.1，2026-08-23，issue #593）**: `Character` 新增 **`brief`** 字段（一句话简介，≤500 字符，默认空串）——F6 上下文注入采用「名 + brief」轻量化（D5=A），未填 brief 时 F6 降级截 `personality`。新增于 §2.1 字段表 / §2.5 领域模型 / CharacterCreate / CharacterUpdate，DB 侧列由 `ensure_characters_brief_column` 幂等迁移补齐（§8）。

>
> **快速导航**（2026-08-08 #201）：
> [1. 概述](L12) · [2. 数据模型](L33) · [3. API 契约](L239) · [4. CLI 命令签名](L406)
> [5. AI 提取模式（样板核心）](L476) · [6. 关系图谱与分组管理规则](L572) · [7. 边界情况与错误处理](L600) · [8. 文件结构](L641)
> [9. 测试策略](L743) · [10. 不在范围内](L788) · [11. 依赖关系](L808) · [12. 关键架构决策记录](L835)
> [13. 验收标准](L856) · [待澄清问题（≤ 3 个，评审时确认）](L872)
---

## 1. 概述

管理小说的**角色档案**（创建/查询/更新/软删除）、**角色分组**（阵营/组织归类）与**角色关系图谱**（角色间有向关系边），并支持**从章节文本用 LLM 自动提取角色与关系**（名称/性格/背景/目标/关系）。

**核心价值**: 作者与 AI Agent 可以维护结构化角色设定；AI 提取把「写在正文里的角色信息」沉淀为可复用的设定档案，为 F6 上下文注入（角色设定进 Prompt）、F3 写作一致性提供数据基础。

**样板模块定位（全项目关键）**: F9 是 0.2.0 创作工具链的**第一个模块**，负责沉淀「**实体 + AI 提取**」模式，F10-F13（世界观/大纲/时间线/伏笔）将复用同一套骨架：

```
实体模型(domain/models) → CRUD Port(domain/ports) → Repository(infrastructure) → Service(domain/services)
        → API Router + CLI（薄层）→ AI 提取管线（LLM 模板 + 解析 + 合并落库）
```

§5 将完整描述该模式；F10-F13 实施时直接对照本节与对应文件结构，不应重新发明。

**边界声明**:
- F9 只做**单次、单章节文本**的基础提取（输入一段文本 → 输出角色/关系并合并落库）。增量提取、批量/全书提取、定时提取、指代消解归 **F14 统一提取服务**（Issue #44），见 §10
- F9 不实现 F6 上下文注入（`ContextSourceProtocol` 的 `character_setting` 数据源）；实体与查询能力为其预留，集成点见 §11

---

## 2. 数据模型

遵循 F1 Project 的「领域 Pydantic 实体 + 请求/更新 DTO + ORM 双模型」模式（ADR-004）。领域层 id 为 UUID，数据库 int 自增映射（同 F1 §12）。

### 2.1 Character（角色）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，DB int 自增映射 |
| project_id | UUID | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目 |
| name | str | NOT NULL, 1-50 字符, 去空白 | 角色名；**项目内活动角色唯一**（partial unique，见 §2.4） |
| personality | str | NOT NULL, DEFAULT "", ≤ 5000 字符 | 性格描述 |
| background | str | NOT NULL, DEFAULT "", ≤ 20000 字符 | 背景故事 |
| goals | str | NOT NULL, DEFAULT "", ≤ 5000 字符 | 目标/动机 |
| brief | str | NOT NULL, DEFAULT "", ≤ 500 字符 | **v1.1（#593）** 一句话简介（F6 上下文轻量化注入用，名+brief；未填时 F6 降级截 personality） |
| group_id | UUID? | NULLABLE, FK→character_groups.id (SET NULL), 已索引 | 所属分组（一对一；多对多标签见 §10） |
| extra | dict[str, Any] | NOT NULL, DEFAULT {} | 扩展字典（外貌/口头禅等 Phase 2+ 字段预留） |
| is_deleted | bool | NOT NULL, DEFAULT False, 已索引 | 软删除标记 |
| created_at | datetime | NOT NULL, AUTO | 创建时间 (UTC) |
| updated_at | datetime | NOT NULL, AUTO | 更新时间 (UTC) |

> **说明**: 任务上下文中的 `relations` 字段**不作为 Character 的入库字段**——关系由独立的 `CharacterRelation` 表（§2.3）表达，避免「JSON 嵌入 + 关系表」双份真相。角色详情 API 响应中内联只读聚合的 `relations` 列表（§3.4），满足「档案中直接可见关系」的直觉。

### 2.2 CharacterGroup（角色分组）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID |
| project_id | UUID | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目 |
| name | str | NOT NULL, 1-50 字符, 去空白 | 分组名（如「主角团」「反派」）；**项目内活动分组唯一** |
| description | str | NOT NULL, DEFAULT "", ≤ 500 字符 | 分组说明 |
| sort_order | int | NOT NULL, DEFAULT 0, ≥ 0 | 列表排序权重（小者在前） |
| is_deleted | bool | NOT NULL, DEFAULT False | 软删除标记 |
| created_at / updated_at | datetime | NOT NULL, AUTO | 同上 |

### 2.3 CharacterRelation（角色关系 — 关系图谱的有向边）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID |
| project_id | UUID | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目（冗余存储，便于按项目查询与隔离） |
| from_character_id | UUID | NOT NULL, FK→characters.id (CASCADE), 已索引 | 关系起点（如「林尘 的 师父 是 青云真人」→ from=林尘） |
| to_character_id | UUID | NOT NULL, FK→characters.id (CASCADE), 已索引 | 关系终点 |
| relation_type | str | NOT NULL, 1-20 字符, 去空白 | 关系类型（自由文本，如「师徒」「宿敌」「青梅竹马」；受控词表归 F14） |
| description | str | NOT NULL, DEFAULT "", ≤ 500 字符 | 关系说明 |
| is_deleted | bool | NOT NULL, DEFAULT False | 软删除标记 |
| created_at / updated_at | datetime | NOT NULL, AUTO | 同上 |

**业务规则**:
- 有向边：`from` → `to` 语义明确；图谱查询按**双向**返回（见 §6）
- **禁止自环**：`from_character_id == to_character_id` → 422「关系两端不能是同一角色」（自环在写作场景无意义，且徒增图谱噪音）
- 两端必须属于**同一项目**（以 from 角色所在项目为准，to 角色归属不一致 → 422）
- 活动关系中 `(project_id, from_character_id, to_character_id, relation_type)` 唯一（partial unique，见 §2.4）；完全相同的边重复创建 → 422「该关系已存在」
- 角色**软删除 → 其所有关系（双向）级联软删除**；角色恢复 → 级联恢复（服务层实现，保证图谱一致）；角色**硬删除 → 关系物理删除**（DB FK CASCADE）

### 2.4 唯一约束（partial unique index，SQLite）

```python
# ORM __table_args__（SQLAlchemy 2.0 + SQLite partial index）
__table_args__ = (
    Index(
        "uq_characters_active_name",
        "project_id", "name",
        unique=True,
        sqlite_where=text("is_deleted = 0"),
    ),
    Index(
        "uq_character_groups_active_name",
        "project_id", "name",
        unique=True,
        sqlite_where=text("is_deleted = 0"),
    ),
    Index(
        "uq_character_relations_active_key",
        "project_id", "from_character_id", "to_character_id", "relation_type",
        unique=True,
        sqlite_where=text("is_deleted = 0"),
    ),
)
```

**为什么是 partial index**: 「同名 = 同一角色」是 AI 提取合并策略的锚点（§5.4），活动角色名必须唯一；而**软删除后再创建同名角色**是合法操作（旧档案已废弃），partial index 恰好两者兼得（已删除行不参与唯一性）。服务层再做一次同名检查以给出友好 422 文案。

### 2.5 领域模型（Pydantic v2 语法，参照 F1 `domain/models/project.py`）

```python
class Character(BaseModel):
    """角色领域实体. 对应 characters 表."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    personality: str = ""
    background: str = ""
    goals: str = ""
    brief: str = ""  # v1.1（#593）：一句话简介，F6 上下文轻量化注入
    group_id: uuid.UUID | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class CharacterCreate(BaseModel):
    """创建角色请求 DTO."""
    project_id: uuid.UUID
    name: str
    personality: str = ""
    background: str = ""
    goals: str = ""
    brief: str = ""  # v1.1（#593）
    group_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("角色名不能为空")
        if len(stripped) > 50:
            raise ValueError("角色名不能超过 50 个字符")
        return stripped

    @field_validator("brief")
    @classmethod
    def validate_brief(cls, v: str) -> str:
        """v1.1（#593）：brief 去空白, ≤ 500 字符（F6 注入轻量化）. """
        stripped = v.strip()
        if len(stripped) > 500:
            raise ValueError("角色简介不能超过 500 个字符")
        return stripped


class CharacterUpdate(BaseModel):
    """更新角色请求 DTO — 所有字段可选（exclude_unset 语义，同 F1）.

    group_id: None 表示清除分组；不传该字段表示不修改.
    """
    name: str | None = None
    personality: str | None = None
    background: str | None = None
    goals: str | None = None
    brief: str | None = None  # v1.1（#593）
    group_id: uuid.UUID | None = None

    # name 复用 CharacterCreate.validate_name 的校验逻辑（None 时直接返回）


class CharacterGroup(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str = ""
    sort_order: int = 0
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class CharacterRelation(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    project_id: uuid.UUID
    from_character_id: uuid.UUID
    to_character_id: uuid.UUID
    relation_type: str
    description: str = ""
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class CharacterRelationCreate(BaseModel):
    """创建关系 DTO — from 端由路径参数（所属角色）决定."""
    to_character_id: uuid.UUID
    relation_type: str   # 1-20 去空白
    description: str = ""  # ≤ 500
```

### 2.6 提取相关模型（§5 详述）

```python
class ExtractedCharacter(BaseModel):
    """LLM 提取出的单个角色（schema 校验用）."""
    name: str                  # 1-50 去空白；非法 → 该条跳过 + warning
    personality: str | None = None
    background: str | None = None
    goals: str | None = None


class ExtractedRelation(BaseModel):
    """LLM 提取出的关系（schema 校验用；名称引用，落库前解析为 id）."""
    from_name: str
    to_name: str
    relation_type: str
    description: str | None = None


class CharacterExtractRequest(BaseModel):
    """角色提取请求."""
    project_id: uuid.UUID
    text: str                  # 必填, 去空白非空, ≤ 50000 字符
    model: str | None = None   # 覆盖项目默认模型（格式 provider/model_name）


class CharacterExtractionResult(BaseModel):
    """角色提取结果 — 合并落库后的报告."""
    created: list[Character]
    updated: list[Character]
    relations_created: list[CharacterRelation]
    relations_updated: list[CharacterRelation]
    warnings: list[str]
    model: str
```

---

## 3. API 契约

端点风格沿用 F2：**创建/列表嵌套于项目路径**，**详情/更新/删除扁平**。错误响应格式沿用 F1/F2（`{"detail": "..."}` 404 / 422）。

### 3.1 端点总览

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/projects/{project_id}/characters` | 创建角色 | `CharacterCreate` | 201 + Character |
| GET | `/api/v1/projects/{project_id}/characters` | 角色列表 | Query: `?search=&group_id=&sort_by=&sort_desc=&offset=&limit=` | 200 + `{items, total, offset, limit}` |
| GET | `/api/v1/characters/{character_id}` | 角色详情（含 relations 聚合） | — | 200 + Character JSON |
| PATCH | `/api/v1/characters/{character_id}` | 更新角色 | `CharacterUpdate` | 200 + Character |
| DELETE | `/api/v1/characters/{character_id}` | 删除角色 | Query: `?force=true` | 204（默认软删除） |
| POST | `/api/v1/characters/{character_id}/restore` | 恢复角色（含级联恢复关系） | — | 200 + Character |
| GET | `/api/v1/characters/{character_id}/relations` | 角色关系列表（双向） | — | 200 + `{items, total}` |
| POST | `/api/v1/characters/{character_id}/relations` | 创建关系（from=路径角色） | `CharacterRelationCreate` | 201 + CharacterRelation |
| PATCH | `/api/v1/characters/{character_id}/relations/{relation_id}` | 更新关系 | `{relation_type?, description?}` | 200 + CharacterRelation |
| DELETE | `/api/v1/characters/{character_id}/relations/{relation_id}` | 删除关系（软删除） | — | 204 |
| POST | `/api/v1/projects/{project_id}/character-groups` | 创建分组 | `{name, description?, sort_order?}` | 201 + CharacterGroup |
| GET | `/api/v1/projects/{project_id}/character-groups` | 分组列表（含 member_count） | — | 200 + `{items, total}` |
| GET | `/api/v1/character-groups/{group_id}` | 分组详情（含 member_count） | — | 200 + CharacterGroup |
| PATCH | `/api/v1/character-groups/{group_id}` | 更新分组 | `{name?, description?, sort_order?}` | 200 + CharacterGroup |
| DELETE | `/api/v1/character-groups/{group_id}` | 删除分组（成员 group_id 置空） | — | 204（软删除） |
| POST | `/api/v1/characters/extract` | AI 提取角色/关系 | `CharacterExtractRequest` | 200 + CharacterExtractionResult |

### 3.2 请求/响应示例 — 角色 CRUD

**创建角色**:
```http
POST /api/v1/projects/3f2e1d4a-.../characters
Content-Type: application/json

{ "name": "林尘", "personality": "坚韧隐忍", "background": "废柴体质觉醒者", "group_id": null }
```
→ 201
```json
{
  "id": "9b1c2d3e-...", "project_id": "3f2e1d4a-...", "name": "林尘",
  "personality": "坚韧隐忍", "background": "废柴体质觉醒者", "goals": "",
  "group_id": null, "extra": {}, "is_deleted": false,
  "created_at": "2026-08-01T10:00:00Z", "updated_at": "2026-08-01T10:00:00Z"
}
```

**列出角色（搜索 + 分组过滤 + 分页）**:
```http
GET /api/v1/projects/3f2e1d4a-.../characters?search=林&group_id=5a1b2c3d-...&sort_by=name&sort_desc=false&offset=0&limit=20
```
→ 200 `{"items": [...], "total": 1, "offset": 0, "limit": 20}`

**同名冲突**:
```http
POST /api/v1/projects/3f2e1d4a-.../characters
{ "name": "林尘" }
```
→ 422 `{"detail": "同名角色已存在（角色名在项目内必须唯一）"}`

**更新角色（清除分组）**:
```http
PATCH /api/v1/characters/9b1c2d3e-...
{ "goals": "成为青云宗首席弟子", "group_id": null }
```
→ 200（更新后 Character JSON，group_id 为 null）

**软删除 / 恢复 / 硬删除**:
```http
DELETE /api/v1/characters/9b1c2d3e-...            → 204（软删除）
POST /api/v1/characters/9b1c2d3e-.../restore      → 200 + Character
DELETE /api/v1/characters/9b1c2d3e-...?force=true → 204（物理删除，关系级联删除）
```

### 3.3 请求/响应示例 — 关系与分组

**创建关系**（from=路径角色）:
```http
POST /api/v1/characters/9b1c2d3e-.../relations
Content-Type: application/json

{ "to_character_id": "7a8b9c0d-...", "relation_type": "师徒", "description": "青云真人收林尘为关门弟子" }
```
→ 201（CharacterRelation JSON）

**查看角色关系（双向聚合）**:
```http
GET /api/v1/characters/9b1c2d3e-.../relations
```
→ 200
```json
{
  "items": [
    {"id": "...", "from_character_id": "9b1c2d3e-...", "to_character_id": "7a8b9c0d-...",
     "relation_type": "师徒", "description": "...", "from_name": "林尘", "to_name": "青云真人"},
    {"id": "...", "from_character_id": "2e3f4a5b-...", "to_character_id": "9b1c2d3e-...",
     "relation_type": "宿敌", "description": "...", "from_name": "萧炎", "to_name": "林尘"}
  ],
  "total": 2
}
```
> `from_name`/`to_name` 由 API 层聚合（JOIN 或批量查询），**不入库**。

**分组管理**:
```http
POST /api/v1/projects/3f2e1d4a-.../character-groups
{ "name": "主角团", "description": "主角及其伙伴", "sort_order": 1 }
```
→ 201（CharacterGroup JSON）
```http
GET /api/v1/projects/3f2e1d4a-.../character-groups
```
→ 200 `{"items": [{"id": "...", "name": "主角团", "member_count": 3, ...}], "total": 1}`

**删除分组**（成员自动解除分组，角色本身不受影响）:
```http
DELETE /api/v1/character-groups/5a1b2c3d-... → 204
```

### 3.4 角色详情响应（含 relations 聚合）

`GET /api/v1/characters/{id}` 在 Character JSON 基础上附加只读字段：
```json
{
  "id": "...", "project_id": "...", "name": "林尘",
  "personality": "...", "background": "...", "goals": "...",
  "group_id": "5a1b2c3d-...", "extra": {}, "is_deleted": false,
  "created_at": "...", "updated_at": "...",
  "relations": [
    {"id": "...", "to_character_id": "7a8b9c0d-...", "to_name": "青云真人",
     "relation_type": "师徒", "description": "..."}
  ]
}
```
> `relations` 为该角色**双向**（作为 from 或 to）的活动关系，省略 `from_character_id`（恒等于本角色）。该字段由 API 层聚合，不写入实体/数据库。

### 3.5 错误响应格式（沿用 F1/F2/ADR-012）

```json
// 404 — 资源不存在
{"detail": "项目不存在"}
{"detail": "角色不存在"}
{"detail": "分组不存在"}
{"detail": "关系不存在"}

// 422 — 业务校验失败 / Pydantic 验证失败
{"detail": "同名角色已存在（角色名在项目内必须唯一）"}
{"detail": "关系两端不能是同一角色"}
{"detail": "该关系已存在"}
{"detail": "角色与目标角色不属于同一项目"}
{"detail": "分组不存在于该项目"}

// 500 — LLM 提取失败（日志记录原始异常，不泄漏堆栈）
{"detail": "角色提取失败: LLM 输出无法解析，请重试"}
{"detail": "LLM 调用失败，请稍后重试"}
```

**异常映射表**:

| 异常/场景 | 状态码 | 响应 |
|-----------|--------|------|
| 项目/角色/分组/关系不存在（Service 返回 None） | 404 | 见上 |
| 无效 UUID 格式 | 404 | 统一解析失败处理（同 F1 `_parse_project_id`） |
| 同名角色/分组、自环、重复关系、跨项目关系、分组不属于该项目 | 422 | 服务层业务校验 |
| Pydantic `ValidationError` | 422 | FastAPI 自动生成 |
| `CharacterExtractionError`（LLM 输出解析失败，重试后仍失败） | 500 | `"角色提取失败: LLM 输出无法解析，请重试"` |
| `LLMRequestError`（F5 重试耗尽） | 500 | `"LLM 调用失败，请稍后重试"` |

---

## 4. CLI 命令签名

遵循 F7 §5 全局约定：`--json` 统一信封 `{"ok": true, "data": ...}` / `{"ok": false, "error": {"code", "message"}}`；退出码 0/1/2/130；错误码 NOT_FOUND / VALIDATION_ERROR / LLM_ERROR / DB_ERROR；删除类命令二次确认 + `--force`；`--json` + 无 `--force` 的删除 → `VALIDATION_ERROR`（沿用 F7 §7）。`character` 组在 F9 落地时并入 F7 命令树（`cli/app.py` 注册）。

### 4.1 character 组（委托 CharacterService）

```bash
inkflow character create --project-id <uuid> --name <str> \
    [--personality <str>] [--background <str>] [--goals <str>] \
    [--group-id <uuid>] [--json]

inkflow character list --project-id <uuid> \
    [--search <str>] [--group-id <uuid>] \
    [--sort <name|updated_at|created_at>] [--sort-desc/--no-sort-desc] [--json]

inkflow character get --id <uuid> [--json]

inkflow character update --id <uuid> \
    [--name <str>] [--personality <str>] [--background <str>] [--goals <str>] \
    [--group-id <uuid|"">] [--json]        # --group-id "" 表示清除分组

inkflow character delete --id <uuid> [--force] [--permanent] [--json]
inkflow character restore --id <uuid> [--json]

inkflow character relations --id <uuid> [--json]          # 双向关系列表
inkflow character relate --id <uuid> --to <uuid> --type <str> [--description <str>] [--json]
inkflow character unrelate --id <uuid> --relation-id <uuid> [--force] [--json]

inkflow character extract --project-id <uuid> \
    --text <str> | --text-file <path> [--model <str>] [--json]
```

### 4.2 group 子组（嵌套于 character 下）

```bash
inkflow character group list   --project-id <uuid> [--json]
inkflow character group create --project-id <uuid> --name <str> [--description <str>] [--json]
inkflow character group update --id <uuid> [--name <str>] [--description <str>] [--json]
inkflow character group delete --id <uuid> [--force] [--json]
```

### 4.3 输出格式

```bash
# 默认人类可读
✅ 角色创建成功: [林尘] (主角团)
✅ 角色已删除: [林尘]
✅ 提取完成: 新增 3 个角色, 更新 1 个角色, 新增 4 条关系, 更新 0 条, 跳过 2 条, 警告 2 条
⚠️ 提取完成但有警告: 角色 "？？" 名称为空已跳过; 关系 萧炎→？？ 无法解析已跳过

# --json 输出
inkflow character create --project-id ... --name "林尘" --json
→ {"ok": true, "data": {"id": "...", "name": "林尘", ...}}

inkflow character extract --project-id ... --text-file ch3.txt --json
→ {"ok": true, "data": {"created": [...], "updated": [...],
     "relations_created": [...], "relations_updated": [...],
     "warnings": [...], "model": "deepseek/deepseek-chat"}}

inkflow character get --id 00000000-0000-0000-0000-000000000000 --json
→ {"ok": false, "error": {"code": "NOT_FOUND", "message": "角色不存在"}}   # 退出码 1

inkflow character delete --id ... --json
→ {"ok": false, "error": {"code": "VALIDATION_ERROR", "message": "删除需 --force 或交互确认"}}  # 退出码 1
```

**`--text-file` 设计理由**: 章节文本可达数千字，作为命令行参数在 Windows 下受 8191 字符限制；`--text` 与 `--text-file` 互斥（同时传入 → 退出码 2）。

---

## 5. AI 提取模式（样板核心）

### 5.1 模式总览（F10-F13 复用骨架）

```
 ┌────────────────────────────────────────────────────────────┐
 │ 输入: CharacterExtractRequest {project_id, text, model?}    │
 └──────────────────────────┬─────────────────────────────────┘
                            ▼
 ① 校验项目存在（F1 ProjectRepository）→ 404
 ② 渲染 character_extract.yaml（F5 PromptManager，变量: text）
 ③ LLMClient.chat(model or project.config.model, temperature=0.2)
 ④ 解析 JSON → Pydantic schema 校验（ExtractedCharacter / ExtractedRelation）
    ├─ 失败 → 修复式重试（附错误信息）≤ 2 次 → 仍失败 → CharacterExtractionError
 ⑤ 合并落库（单 DB session 事务）:
    ├─ 角色: 按 (project_id, name) 匹配活动角色 → 存在=更新(非空覆盖) / 不存在=创建
    └─ 关系: 名称解析为 id → 按 (from, to, type) 匹配 → upsert
 ⑥ 返回 CharacterExtractionResult（created/updated/warnings + 实际模型）
```

**模式要点（F10-F13 照此实现）**:
1. **模板与代码分离**: 提取指令在 `infrastructure/llm/templates/{module}_extract.yaml`（ADR-014/015），领域服务只组装变量
2. **LLM 输出 schema 校验**: 用 Pydantic 模型校验原始 JSON，非法条目**跳过 + warning**，整批非法才抛错
3. **合并锚点 = 项目内唯一键**: 角色用 name、关系用 (from, to, type)，与 §2.4 partial unique 对齐
4. **失败策略**: LLM 调用失败（F5 重试耗尽）→ 透传 `LLMRequestError`；解析失败重试 ≤2 → `CharacterExtractionError`；**合并阶段不重试**（已落库数据不可重复合并）
5. **单事务**: 整个合并在一个 session 内完成，任何异常回滚，无部分落库

### 5.2 LLM 模板（`character_extract.yaml`）

```yaml
name: character_extract
description: 从章节文本提取角色与关系（结构化 JSON 输出）
system_prompt: |
  你是小说角色信息提取器。从给定的章节文本中提取出场角色及其性格、背景、目标，
  以及角色之间的明确关系。只提取文本中直接出现的或明确暗示的信息，不要臆造。
  输出严格 JSON，不要输出任何其他文字，格式如下：
  {
    "characters": [
      {"name": "角色名", "personality": "性格描述或空", "background": "背景或空", "goals": "目标或空"}
    ],
    "relations": [
      {"from": "角色A", "to": "角色B", "type": "关系类型", "description": "说明或空"}
    ]
  }
  characters 中不要包含重复的角色名。
human_prompt: |
  章节文本：
  {text}
variables:
  - text
```

### 5.3 解析与重试

| 场景 | 行为 |
|------|------|
| 输出为合法 JSON 且通过 schema 校验 | 进入合并 |
| 输出含代码块围栏/前后缀文字 | 提取首个 `{...}` 平衡片段（`_extract_json_fragment`），再解析 |
| 仍失败 | 构建修复 Prompt（原输出 + 解析错误信息 + 「只输出 JSON」）重试，`retry_count += 1`，≤ 2 次 |
| 3 次（1 次原始 + 2 次修复）均失败 | `CharacterExtractionError`（含原始输出片段，日志记录） |

> 与 F3 格式重试（≤3）同源但更保守：提取是批处理操作，无「部分可用」输出，失败必须显式报错而非静默返回。

### 5.4 合并策略（同名角色规则）

**角色合并（按项目内活动角色 name 精确匹配）**:

| 情况 | 行为 | 计入 |
|------|------|------|
| 项目内存在同名**活动**角色 | 非空提取字段**覆盖**对应字段（personality/background/goals 独立判断），更新 updated_at | `updated` |
| 不存在 | 创建新角色（group_id=None） | `created` |
| 存在但已**软删除** | 视为不存在 → **创建新角色**（不隐式恢复旧档案；partial unique 允许） | `created` + warning「存在已删除的同名角色档案」 |
| 提取字段非法（name 空/超长、字段超长） | 该条**跳过** | `warnings` |

**关系合并（名称解析 → 键匹配）**:

| 情况 | 行为 | 计入 |
|------|------|------|
| `from_name`/`to_name` 都能解析为项目内角色 id（本次创建/更新或库中已存在） | 按 `(from_id, to_id, relation_type)` 查活动关系：存在 → 更新 description（提取值非空时）；不存在 → 创建 | `relations_updated` / `relations_created` |
| 任一端名称无法解析（LLM 幻觉/不在提取列表且库中不存在） | **跳过**，不创建悬空关系 | `warnings` |
| 两端为同一角色名 | 跳过（对齐自环禁令） | `warnings` |
| 已存在但软删除的同键关系 | 创建新活动记录（partial unique 允许） | `relations_created` |

**幂等性**: 对同一文本重复提取，第二次应产出空 `created`/`updated` 列表（全部命中已有数据，非空字段覆盖后值不变）——这是合并策略正确性的关键验收点。

### 5.5 提取输入约束

| 约束 | 值 | 说明 |
|------|-----|------|
| text | 去空白非空，≤ 50000 字符 | 空 → 422「章节文本不能为空」 |
| 默认模型 | `project.config.model` | F1 项目配置 |
| temperature | 固定 0.2（结构化输出低温稳定） | 不对外暴露 |
| 并发 | 不限制（单用户本地工具；同文本并发提取由唯一键兜底） | — |

---

## 6. 关系图谱与分组管理规则

### 6.1 关系图谱语义

- **有向存储，双向查询**: 边有方向（`from → to`），但图谱查询（角色详情 relations、`GET /characters/{id}/relations`）一律返回该角色作为 from 或 to 的**全部活动边**——作者视角的关系图谱是无向展示的
- 软删除角色/关系不进入任何图谱查询结果
- 角色恢复时级联恢复其关系（服务层：`restore_character` 内先恢复角色，再恢复 `from_character_id = 角色 or to_character_id = 角色` 的关系）
- 图谱整体导出/可视化不在 F9 范围（F18 Web UI）

### 6.2 分组语义

- 分组是**项目内**概念：`character_groups.project_id` 隔离，角色只能加入**同一项目**的分组（`update_character(group_id=...)` 时校验分组归属 → 422「分组不存在于该项目」）
- 分组删除（软删除）→ 服务层将成员角色 `group_id` 置为 NULL（角色本身不动）；`GET /character-groups` 不返回已删除分组
- `member_count` 为分组内活动角色数，由 API 层聚合
- 一对一归属（单 `group_id`）；「标签多对多」不在范围（§10）

### 6.3 搜索与排序（角色列表，沿用 F1 §6）

| 参数 | 默认值 | 约束 | 说明 |
|------|--------|------|------|
| `search` | — | — | 对 name 不区分大小写子串匹配（icontains） |
| `group_id` | — | UUID | 按分组过滤 |
| `sort_by` | `updated_at` | `name` / `updated_at` / `created_at` | 排序字段 |
| `sort_desc` | `true` | — | 降序 |
| `offset` / `limit` | 0 / 50 | offset ≥ 0, limit [1, 100] | 分页 |

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 创建角色名为空/全空白 | 422: "角色名不能为空" |
| 创建角色名 > 50 字符 | 422: "角色名不能超过 50 个字符" |
| 创建角色名与项目内**活动**角色重复 | 422: "同名角色已存在（角色名在项目内必须唯一）" |
| 软删除后**再创建同名角色** | ✅ 成功（partial unique 排除已删除行；服务层同名检查仅限活动角色） |
| 获取/更新/软删除/硬删除不存在的角色 | 404: "角色不存在" |
| 硬删除已软删除的角色 | 404: "角色不存在"（已排除） |
| 恢复不存在的角色 | 404: "角色不存在" |
| 恢复未删除的角色 | 正常返回（重复操作无毒，同 F1） |
| 角色不存在 / 无效 UUID 格式 | 404: "角色不存在"（统一 `_parse_id` 处理） |
| 分组不存在 / 无效 UUID | 404: "分组不存在" |
| 角色 update 时 group_id 不属于该项目 | 422: "分组不存在于该项目" |
| 删除分组 | 204；成员角色 group_id 置 NULL（角色保留） |
| 关系两端是同一角色 | 422: "关系两端不能是同一角色" |
| 关系 to 角色不存在 | 404: "角色不存在" |
| 关系 to 角色与 from 角色不同项目 | 422: "角色与目标角色不属于同一项目" |
| 重复创建相同活动关系 (from,to,type) | 422: "该关系已存在" |
| 更新/删除不存在的关系 | 404: "关系不存在" |
| 角色软删除 | 204；其双向关系级联软删除 |
| 角色硬删除 | 204；其双向关系物理删除（FK CASCADE） |
| 角色恢复 | 200；其关系级联恢复 |
| 提取 text 为空/全空白 | 422: "章节文本不能为空" |
| 提取 text > 50000 字符 | 422: "章节文本不能超过 50000 个字符" |
| 提取时项目不存在 | 404: "项目不存在" |
| LLM 返回非 JSON / 无法解析 | 修复重试 ≤ 2 → 仍失败 → 500: "角色提取失败: LLM 输出无法解析，请重试" |
| LLM 返回空角色列表 | 200 + 空 created/updated + warning "未提取到角色信息" |
| LLM 输出中个别条目非法（空名等） | 该条跳过 + warning，**不影响其他条目落库** |
| 关系引用提取列表外且库中不存在的名字 | 关系跳过 + warning，不创建悬空关系 |
| 提取时 LLM 调用失败（网络/Key） | 500: "LLM 调用失败，请稍后重试"（F5 已内部重试 3 次） |
| 合并中途 DB 错误 | 整体回滚（单事务），无部分落库 |
| 角色列表搜索/分组过滤无结果 | 200: `{"items": [], "total": 0}` |
| 分页越界 | 200: 空 items（同 F1） |
| 项目硬删除 | 角色/分组/关系级联物理删除（FK CASCADE）；项目软删除不影响角色数据 |
| `--text` 与 `--text-file` 同时传入 | CLI 退出码 2（用法错误） |
| 提取合并幂等性 | 同文本二次提取 → created/updated 为空（全部命中已有） |

---

## 8. 文件结构

遵循 ADR-007v2 包结构，与现有真实源码树一致。新增/修改文件：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── character.py          ← CREATE: Character, CharacterGroup, CharacterRelation,
│   │   │                             CharacterCreate, CharacterUpdate, CharacterRelationCreate,
│   │   │                             CharacterExtractRequest, CharacterExtractionResult,
│   │   │                             ExtractedCharacter, ExtractedRelation
│   │   └── __init__.py           ← MODIFY: 导出新模型
│   ├── ports/
│   │   ├── character_repository.py ← CREATE: CharacterRepositoryProtocol
│   │   ├── character_errors.py   ← CREATE: CharacterExtractionError
│   │   └── __init__.py           ← MODIFY: 导出
│   └── services/
│       ├── character_service.py  ← CREATE: CharacterService（角色/分组/关系 CRUD + extract 入口）
│       ├── _character_extractor.py ← CREATE: 提取管线（模板渲染 → LLM → JSON 解析 → 合并策略）
│       └── __init__.py           ← MODIFY
├── infrastructure/
│   ├── llm/templates/
│   │   └── character_extract.yaml ← CREATE: 提取模板（§5.2）
│   └── database/
│       ├── models/
│       │   ├── character.py      ← CREATE: CharacterORM, CharacterGroupORM, CharacterRelationORM
│       │   │                        （partial unique index, FK, soft-delete 标记）
│       │   └── __init__.py       ← MODIFY: 注册 3 个 ORM（create_tables 依赖）
│       └── repositories/
│           ├── character_repo.py ← CREATE: SQLiteCharacterRepository
│           └── __init__.py       ← MODIFY
├── api/
│   ├── routers/
│   │   ├── characters.py         ← CREATE: 16 个端点（角色 CRUD + relations + groups + extract）
│   │   └── __init__.py           ← MODIFY
│   ├── deps.py                   ← MODIFY: get_character_service
│   └── app.py                    ← MODIFY: 注册 characters.router
└── cli/
    ├── commands/
    │   ├── character.py          ← CREATE: character 组（create/list/get/update/delete/restore/
    │   │                             relations/relate/unrelate/extract + group 子组）
    │   └── __init__.py           ← MODIFY
    └── app.py                    ← MODIFY: 注册 character 命令组

backend/tests/
├── unit/
│   ├── test_character_models.py  ← CREATE: 领域模型/DTO 验证 + 提取 DTO schema
│   ├── test_character_repo.py    ← CREATE: 仓储集成测试（in-memory SQLite，含级联/partial unique）
│   ├── test_character_service.py ← CREATE: 服务测试（角色/分组/关系 CRUD + 业务校验）
│   ├── test_character_extraction.py ← CREATE: 提取管线测试（Mock LLM：解析/重试/合并/幂等）
│   └── test_character_api.py     ← CREATE: API 集成测试（Mock Service）
└── test_cli_character.py         ← CREATE: CLI 测试（Mock CharacterService，信封/退出码）
```

> 测试文件位置与现有树一致：仓储/API 集成测试放 `tests/unit/`（参照 `test_summary_repo.py`/`test_context_api.py`），CLI 测试放 `tests/` 根（参照 `test_cli_project.py`）。

### 8.1 CharacterRepositoryProtocol（参照 `summary_repository.py` Protocol 风格）

```python
class CharacterRepositoryProtocol(Protocol):
    """角色/分组/关系仓储端口."""

    # ── Character ──
    async def add(self, character: Character) -> Character: ...
    async def get(self, character_id: int) -> Character | None: ...
    async def get_by_name(self, project_id: int, name: str) -> Character | None: ...
    async def list(self, project_id: int, search: str | None = None,
                   group_id: int | None = None, sort_by: str = "updated_at",
                   sort_desc: bool = True, offset: int = 0,
                   limit: int = 50) -> tuple[list[Character], int]: ...
    async def update(self, character: Character) -> Character: ...
    async def soft_delete(self, character_id: int) -> bool: ...
    async def restore(self, character_id: int) -> Character | None: ...
    async def hard_delete(self, character_id: int) -> bool: ...

    # ── CharacterGroup ──
    async def add_group(self, group: CharacterGroup) -> CharacterGroup: ...
    async def get_group(self, group_id: int) -> CharacterGroup | None: ...
    async def list_groups(self, project_id: int) -> list[CharacterGroup]: ...
    async def update_group(self, group: CharacterGroup) -> CharacterGroup: ...
    async def soft_delete_group(self, group_id: int) -> bool:  # 成员 group_id 置 NULL
    async def hard_delete_group(self, group_id: int) -> bool: ...

    # ── CharacterRelation ──
    async def add_relation(self, relation: CharacterRelation) -> CharacterRelation: ...
    async def get_relation(self, relation_id: int) -> CharacterRelation | None: ...
    async def get_relation_by_key(self, from_id: int, to_id: int,
                                  relation_type: str) -> CharacterRelation | None: ...
    async def list_relations(self, project_id: int,
                             character_id: int | None = None) -> list[CharacterRelation]: ...
    async def update_relation(self, relation: CharacterRelation) -> CharacterRelation: ...
    async def soft_delete_relation(self, relation_id: int) -> bool: ...
    async def hard_delete_relation(self, relation_id: int) -> bool: ...
    async def soft_delete_relations_of(self, character_id: int) -> None: ...  # 级联
    async def restore_relations_of(self, character_id: int) -> None: ...      # 级联
```

> 仓储层方法入参用 int（与现有 SummaryRepositoryProtocol 一致）；Service 负责 UUID ↔ int 转换（沿用 F1 `_to_int_id` 模式）。

---

## 9. 测试策略

### 测试层次（沿用 ADR-018 三层目录 + pytest markers）

```text
单元测试: 领域模型/DTO 验证 + 提取 DTO schema          ~15 cases
集成测试: SQLiteCharacterRepository（in-memory SQLite） ~18 cases
服务测试: CharacterService（Mock Repository）           ~15 cases
提取测试: 提取管线（Mock LLM，全合并分支）              ~14 cases
API 测试: 16 端点（Mock Service）                      ~18 cases
CLI 测试: character 组（Mock CharacterService）         ~20 cases
```

### 关键测试场景

**领域模型**: name 空/空白/超长 → ValidationError / 默认值（personality="", group_id=None）/ CharacterUpdate 部分更新语义 / ExtractedCharacter schema（name 必填）/ CharacterExtractRequest（text 空 → 422、超长 → 422）

**仓储**: 角色/分组/关系 CRUD 往返 / `get_by_name` 命中与未命中 / 活动同名唯一（partial unique：插入第二个活动同名 → IntegrityError；软删除后可再插同名）/ 软删除后 get 返回 None / 分组软删除后成员 group_id 置 NULL / 角色软删除级联关系（双向）/ 恢复级联 / `list_relations` 双向 / 分页与搜索 / 硬删除 FK 级联

**服务**: 创建/更新/软删/恢复全流程 / 同名活动角色 → 422 / group_id 跨项目 → 422 / 自环 → 422 / 重复关系 → 422 / 关系跨项目 → 422 / 角色不存在各操作 → None → 404 / 级联软删与恢复的编排

**提取（Mock LLM，遵循 ADR-015）**:
- 合法 JSON → 全部落库，created/updated 计数正确
- 同名已存在 → 更新（非空覆盖，`updated`），幂等性（二次提取全空）
- 软删除同名 → 新建 + warning
- 非法条目（空名/超长）→ 跳过 + warning，其余正常落库
- 关系引用不可解析名字 → 跳过 + warning，无悬空关系
- 输出带围栏/前缀文字 → `_extract_json_fragment` 提取成功
- 输出完全非法 → 修复重试 2 次 → CharacterExtractionError
- Mock LLM 抛 LLMRequestError → 透传（不消耗解析重试）
- 空角色列表 → 空结果 + warning
- 断言 Prompt 使用 character_extract 模板 + 变量 text + 项目默认模型 + temperature 0.2

**API**: 16 端点成功路径 / 404 全路径（项目/角色/分组/关系）/ 422 业务校验（同名/自环/重复关系/跨项目）/ extract 200 / extract LLM 失败 → 500 / 角色详情含 relations 聚合 / 无效 UUID → 404

**CLI**: 各子命令成功路径与参数透传 / 信封格式与退出码 0/1/2 / delete 二次确认 + `--force` / `--json` + delete 无 `--force` → VALIDATION_ERROR / `--text` 与 `--text-file` 互斥 → 退出码 2 / extract 人类可读摘要与 `--json` 完整结果 / NOT_FOUND、LLM_ERROR 错误信封

### 覆盖率目标

- F9 模块行覆盖率 **≥ 80%**（DTO 验证 100%、合并策略全分支、级联删除路径）
- 全仓覆盖率 **≥ 60%**（0.2.0 DoD，ADR-019）
- CI 门禁：ruff + mypy + pytest 全绿（ADR-017/018）

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|----------|
| 增量提取 / 批量章节提取 / 全书扫描 / 定时提取 | **F14 统一提取服务**（#44）——F9 只做单次单文本基础提取 |
| 指代消解（「他/她」「主角」归并到具体角色） | F14（依赖全文索引/上下文） |
| 提取预览（dry-run，先看后落库） | F14 或 0.2.x 增强；MVP 以结果报告（created/updated）代替 |
| 角色别名管理（一人多名映射） | F14 |
| 受控关系类型词表（枚举/自定义类型库） | F14 定义（F9 用自由文本 ≤20 字符） |
| F6 `character_setting` 数据源真实实现（替换空实现） | 集成点，见 §11 与待澄清 Q1 |
| 写作时角色一致性检查 / 角色出场统计 | F16 一致性审计（Phase 2）；统计 Phase 3+ |
| 角色头像/图片/语音 | Phase 2+ 媒体管理 |
| 标签多对多（角色属多个分组） | Phase 2+（F9 一对一 `group_id`） |
| 跨项目角色共享/引用/合并 | Phase 4 云端 |
| 关系图谱可视化 / 导出 | F18 Web UI（0.3.0） |
| 角色变更审计日志 | F15 审计服务（Issue 待创建） |
| 角色-章节关联（出场章节记录） | Phase 3+ |

---

## 11. 依赖关系

与 F1 §11 / F2 §11 已声明依赖保持一致（F1 被依赖列表含 F6/F7，F2 被依赖列表含 F6/F7，F9 在其上追加）：

```text
F9 依赖:
  F1 (project_service) ✅ — 项目存在性校验（404）；project.config.model 作为提取默认模型
  F5 (llm_service)     ✅ — LLMClientProtocol.chat + PromptTemplateProtocol（character_extract 模板，
                             ADR-014/015 隔离：domain/ 零 LangChain import，CI 强制检查）
  F2 (chapter_service) — 可选：CLI extract --text-file 读取章节内容时不做 F2 校验（直接文本输入），
                          不产生硬依赖

F9 被依赖:
  F6 (context_service) ✅ — character_setting 数据源（compressible 层，见 F6 spec §3.2）：
                            F6 已留 ContextSourceProtocol 空实现（infrastructure/context/sources.py），
                            0.2.0 替换为真实实现（基于 F9 Repository 查询角色档案）。
                            实现归属待澄清（Q1）
  F7 (CLI)             ✅ — character 命令组并入 F7 命令树（cli/app.py 注册）
  F14 (统一提取)        ⏳ — (#44) 复用 F9 的合并/落库能力与唯一键约定
  F15 (审计)            ⏳ — (Issue 待创建) 角色变更作为审计数据源
  F20 (MCP)             ⏳ — (Phase 3) manage_character / manage_relation 工具基于本模块 API
```

> ⚠️ **编号口径说明**: F6 spec §10 与 `infrastructure/context/sources.py` 注释中的「F8（角色）/F9（世界观）」为 ADR-019 之前的旧编号；按 [ADR-019](../../adr/ADR-019.md) 现行口径 **F9 = 角色管理**、F10 = 世界观、F14 = 统一提取。本 spec 及后续 F 模块一律以 ADR-019 为准。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| 关系存储 | 独立 `character_relations` 表，而非 Character 内嵌 JSON | 关系图谱需要双向边查询与按项目隔离；内嵌 JSON 无法高效查询且产生双份真相。角色详情响应的 `relations` 为 API 层只读聚合 |
| 同名语义 | 「项目内活动角色 name 唯一」= 同一角色 | 这是 AI 提取合并的锚点（§5.4），也防止手误重复建档 |
| 唯一约束实现 | SQLite partial unique index（`WHERE is_deleted = 0`） | 软删除后再创建同名角色合法；比「服务层检查 + 全表唯一」更稳（DB 兜底） |
| 合并策略 | 非空字段覆盖；不隐式恢复软删除档案 | 确定性、幂等、可重跑；隐式恢复会带来「意外复活」的不可预期行为 |
| 提取重试 | 解析失败修复式重试 ≤ 2 次（F3 模式），合并阶段不重试 | 提取无部分可用输出，失败显式报错；合并重试会导致重复写入 |
| 提取温度 | 固定 0.2 低温 | 结构化 JSON 输出稳定性优先（F3 修订亦用低温先例） |
| 提取模板 | `character_extract.yaml` 走 F5 PromptManager | ADR-014/015：模板与代码分离、domain/ 零 LangChain |
| 分组模型 | 一对一 `group_id`（FK SET NULL），不做标签多对多 | MVP 最小集（PRD「分组管理」）；多对多属 Phase 2+，F14 后按需 |
| 关系级联 | 角色软删 → 关系双向软删；恢复 → 级联恢复；硬删 → FK CASCADE | 图谱一致性：软删除的角色不应残留可见边；恢复后图谱原样回来 |
| 端点布局 | 创建/列表嵌套项目路径，详情扁平（同 F2） | 与 F2 §3 端点风格一致，OpenAPI 分组清晰 |
| extract 端点 | `POST /api/v1/characters/extract`（动作型，返回 200） | 与 F3 writing 动作型端点一致；单次同步调用，不做任务队列（YAGNI） |
| CLI 分组子命令 | `inkflow character group ...` 三级嵌套 | 分组是角色域的子实体（F2 的 volume 为顶级实体故用顶级组）；避免顶级 `group` 语义歧义 |
| 文本输入 | `--text` / `--text-file` 双通道 | Windows 命令行参数 8191 字符限制，章节文本需文件通道 |
| 提取事务 | 合并单 session 事务，失败全回滚 | 无部分落库；合并失败不会留下半套角色/关系 |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 领域模型 + DTO 验证（含 partial unique 语义、提取 DTO schema） | `pytest tests/unit/test_character_models.py -v` 全绿 |
| M2 | 仓储层全部方法（角色/分组/关系 CRUD + 级联 + 唯一约束） | `pytest tests/unit/test_character_repo.py -v` 全绿 |
| M3 | 服务层 CRUD + 业务校验（同名/自环/跨项目/级联恢复） | `pytest tests/unit/test_character_service.py -v` 全绿 |
| M4 | AI 提取管线（解析/重试/合并策略/幂等性，Mock LLM） | `pytest tests/unit/test_character_extraction.py -v` 全绿 |
| M5 | API 16 端点 + 错误路径全绿 | `pytest tests/unit/test_character_api.py -v` 全绿 |
| M6 | CLI character 组（信封/退出码/确认交互/双文本通道） | `pytest tests/test_cli_character.py -v` 全绿 |
| M7 | 真实 LLM 联调：对一章正文执行 extract 成功落库 | 手工验证（配置任一 Provider Key，`inkflow character extract`） |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest -v` 全绿；F9 模块行覆盖 ≥ 80%、全仓 ≥ 60%（0.2.0 DoD）；ruff + mypy 通过（CI 门禁 ADR-017） |
| M9 | domain/ 零 LangChain import | CI 强制检查通过（沿用 F5/F6 约束） |

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | F6 `CharacterSettingSource` 空实现（`infrastructure/context/sources.py`）的替换是否纳入 F9 里程碑？该文件属 F6 模块，但真实实现依赖 F9 Repository | 影响 F9 收尾范围与 F6 文件修改归属 | 建议：F9 只交付实体/查询能力；替换作为 0.2.0 内 F6 联调任务（写 F9 plan 时单独列出） |
| Q2 | 分组语义确认：MVP 按「一对一归属（阵营/组织）」实现；是否需要「标签多对多」（同一角色属多个分组）？ | 影响数据模型与 API（多对多需关联表） | 建议：MVP 一对一，多对多列入 Phase 2+（本 spec 已按此设计） |
| Q3 | 角色软删除后再次提取到同名角色：当前设计为「新建新档案 + warning」。是否期望「自动恢复旧档案并合并」？ | 影响合并策略与数据生命周期 | 建议：保持新建（不隐式恢复），旧档案由用户显式 restore |

---

*本文档为 F9 功能规格（What），实施步骤（How）见后续 `specs/f9-character-service/plan.md`。所有里程碑验收以本节 M1-M9 为准。*
