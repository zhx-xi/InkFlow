# F10: 世界观管理 (world_service) — 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-01 | **依据**: PRD v2.1 §6.2 P1-02, Constitution P1-P6, ADR-019
> **所属阶段**: Phase 2 — 创作工具链（0.2.0 里程碑第二个模块，估算 3-5 人天）
> **关联 Issues**: [#40](https://github.com/zhx-xi/InkFlow/issues/40)
> **依赖**: F1 ✅, F5 ✅（前置）；F6 ✅（数据源集成点，见 §11 与待澄清 Q1）
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md) (模块化单体), [ADR-002](../../adr/ADR-002.md) (六边形分层), [ADR-003](../../adr/ADR-003.md) (Repository), [ADR-004](../../adr/ADR-004.md) (Pydantic v2), [ADR-007v2](../../adr/ADR-007v2.md) (包结构), [ADR-010](../../adr/ADR-010.md) (上下文分层), [ADR-012](../../adr/ADR-012.md) (错误处理), [ADR-014](../../adr/ADR-014.md) (ChatPromptTemplate), [ADR-015](../../adr/ADR-015.md) (LangChain 隔离), [ADR-016](../../adr/ADR-016.md) (loguru), [ADR-017](../../adr/ADR-017.md) (CI 门禁), [ADR-018](../../adr/ADR-018.md) (测试分层), [ADR-019](../../adr/ADR-019.md) (版本里程碑)
> **状态**: ✅ 已实现（PR #57）

>
> **快速导航**（2026-08-08 #201）：
> [1. 概述](L12) · [2. 数据模型](L34) · [3. API 契约](L213) · [4. CLI 命令签名](L344)
> [5. AI 提取模式（样板核心，同 F9 §5）](L401) · [6. 分类与查询规则](L488) · [7. 边界情况与错误处理](L515) · [8. 文件结构](L547)
> [9. 测试策略](L638) · [10. 不在范围内](L682) · [11. 依赖关系](L702) · [12. 关键架构决策记录](L730)
> [13. 验收标准](L752) · [待澄清问题（≤ 3 个，评审时确认）](L768)
---

## 1. 概述

管理小说的**世界观条目**（创建/查询/更新/软删除），以**类别（category）**承载世界观层级设定（规则/设定/约束/组织/地理等），并支持**从章节文本用 LLM 自动提取世界观信息**（条目名/类别/内容）。

**核心价值**: 作者与 AI Agent 可以维护结构化世界观设定；AI 提取把「写在正文里的世界观信息」沉淀为可复用的设定档案，为 F6 上下文注入（世界观设定进 Prompt）、F16 一致性审计提供数据基础。

**样板模块定位**: F9（角色管理）已沉淀「**实体 + AI 提取**」模式；F10 是 0.2.0 创作工具链**第二个**应用该模式的模块，**完全复用 F9 骨架**：

```
实体模型(domain/models) → CRUD Port(domain/ports) → Repository(infrastructure) → Service(domain/services)
        → API Router + CLI（薄层）→ AI 提取管线（LLM 模板 + 解析 + 合并落库）
```

F9 spec 已明示「F10 实施时直接对照 F9 §5 与对应文件结构，不应重新发明」。本 spec §5/§8/§12 逐处标注「同 F9 §N」，实施时对照 F9 源码替换领域实体（WorldSetting ↔ Character）与模板名（world_extract ↔ character_extract）即可，**不重新设计管线**。

**边界声明**:
- F10 只做**单次、单章节文本**的基础提取（输入一段文本 → 输出世界观条目并合并落库）。增量提取、批量/全书提取、定时提取、指代消解归 **F14 统一提取服务**（Issue #44），见 §10
- F10 不实现 F6 上下文注入（`ContextSourceProtocol` 的 `world_setting` 数据源）；实体与查询能力为其预留，集成点见 §11 与待澄清 Q1
- F10 是世界观**条目/设定管理**，**不是复杂知识图谱**：不做条目间关系表、不做类别层级树（决策见 §2.2/§2.3，理由详见 §12）

---

## 2. 数据模型

遵循 F1 Project 的「领域 Pydantic 实体 + 请求/更新 DTO + ORM 双模型」模式（ADR-004）。领域层 id 为 UUID，数据库 int 自增映射（同 F1 §12）。

### 2.1 WorldSetting（世界观条目）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，DB int 自增映射 |
| project_id | UUID | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目 |
| name | str | NOT NULL, 1-50 字符, 去空白 | 条目名（如「灵气复苏」「宗门等级体系」）；**项目内活动条目唯一**（partial unique，见 §2.4） |
| category | str | NOT NULL, DEFAULT "", ≤ 50 字符, 去空白 | 类别（建议值：设定/规则/约束/组织/地理/种族/文化/科技/魔法体系；自由文本，受控词表归 F14）；空串 = 未分类 |
| content | str | NOT NULL, DEFAULT "", ≤ 20000 字符 | 条目内容/详细设定 |
| extra | dict[str, Any] | NOT NULL, DEFAULT {} | 扩展字典（来源章节、标签、别名等 Phase 2+ 字段预留） |
| is_deleted | bool | NOT NULL, DEFAULT False, 已索引 | 软删除标记 |
| created_at | datetime | NOT NULL, AUTO | 创建时间 (UTC) |
| updated_at | datetime | NOT NULL, AUTO | 更新时间 (UTC) |

**业务规则**:
- `name` 项目内**活动条目唯一** = 「同名 = 同一世界观条目」，这是 AI 提取合并策略的锚点（§5.4），也防止手误重复建档
- `category` 是**条目属性**（平铺字段），不是独立实体：PRD「层级设定（规则/设定/约束）」以条目类别表达；类别无独立生命周期（描述/排序/成员数），独立建表属过度设计（决策理由见 §2.2 与 §12）
- 类别**层级树**（category 父子关系）不在 F10 范围（§10）
- 条目间**不建立外键关联**：「规则A 约束 设定B」类引用用 content 自由文本表达；独立 `WorldRelation` 表属 Phase 2+（决策理由见 §2.3 与 §12）

### 2.2 分类设计决策（不建独立分组表）

对标 F9 `CharacterGroup` 的「分组实体」位置，F10 评估后**不引入 WorldCategory/WorldGroup 表**，用 `category` 字段承载：

| 考量 | 结论 |
|------|------|
| PRD 语义 | P1-02 仅要求「层级设定（规则/设定/约束）」——是条目的**类别属性**，不是「条目归入分组」的容器关系 |
| 独立表的价值 | 类别表只有在需要「类别描述/排序/成员数统计/类别 CRUD」时才值得；MVP 均不需要 |
| LLM 提取兼容 | 类别作为字段可随条目一并提取/合并；独立表则需要「提取→建类别→挂条目」三步编排 |
| 代价 | 若 Phase 2+ 需要类别管理，从字段迁移到表是低成本演进（category 已是规范化文本） |

> 「层级」一词在此解读为**条目的类型维度**（规则/设定/约束等），不是数据结构上的树/继承。真正的层级树归 Phase 2+（§10）。

### 2.3 条目关联设计决策（MVP 不建 WorldRelation 表）

对标 F9 `CharacterRelation` 的「关系图谱」位置，F10 评估后**MVP 不引入 WorldRelation 表**：

| 考量 | 结论 |
|------|------|
| 需求来源 | PRD P1-02 未要求条目间关系图谱；Issue #40 仅「层级设定 + 规则约束管理 + AI 提取」 |
| 与 F9 的差异 | 角色关系（师徒/敌对）是创作**核心结构**，需双向查询；世界观条目间引用（「规则A 约束 设定B」）是**增强语义**，MVP 用 content 自由文本即可表达 |
| 图谱代价 | 关系表需要两端校验、级联软删、图谱查询 API——一套 F9 §2.3/§6.1 的完整机制，收益在 MVP 阶段不成比例 |
| 演进路径 | F14 统一提取/ F16 一致性审计如需要「规则→设定」溯源，再引入 WorldRelation 表（Phase 2+），届时对照 F9 §2.3/§3.3/§6.1 实现 |

> 结论：**倾向简单，避免过度设计**（Constitution P5 YAGNI）。`extra` 字典可临时承载轻量引用标记（不保证图谱能力，不做查询承诺）。

### 2.4 唯一约束（partial unique index，SQLite）

```python
# ORM __table_args__（SQLAlchemy 2.0 + SQLite partial index）
__table_args__ = (
    Index(
        "uq_world_settings_active_name",
        "project_id", "name",
        unique=True,
        sqlite_where=text("is_deleted = 0"),
    ),
)
```

**为什么是 partial index**: 「同名 = 同一世界观条目」是 AI 提取合并策略的锚点（§5.4），活动条目名必须唯一；而**软删除后再创建同名条目**是合法操作（旧档案已废弃），partial index 恰好两者兼得（已删除行不参与唯一性）。服务层再做一次同名检查以给出友好 422 文案。

### 2.5 领域模型（Pydantic v2 语法，参照 F9 `domain/models/character.py`）

```python
def _validate_name(v: str) -> str:
    """共享的条目名校验：去空白后非空且不超过 50 字符."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("条目名不能为空")
    if len(stripped) > 50:
        raise ValueError("条目名不能超过 50 个字符")
    return stripped


def _validate_category(v: str) -> str:
    """共享的类别校验：去空白且不超过 50 字符（空串 = 未分类，允许）."""
    stripped = v.strip()
    if len(stripped) > 50:
        raise ValueError("类别不能超过 50 个字符")
    return stripped


def _validate_content(v: str) -> str:
    """共享的内容校验：不超过 20000 字符（不强制去空白，正文可能含排版空白）."""
    if len(v) > 20000:
        raise ValueError("内容不能超过 20000 个字符")
    return v


class WorldSetting(BaseModel):
    """世界观条目领域实体. 对应 world_settings 表."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    category: str = ""
    content: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class WorldCreate(BaseModel):
    """创建世界观条目请求 DTO."""
    project_id: uuid.UUID
    name: str
    category: str = ""
    content: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        return _validate_category(v)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        return _validate_content(v)


class WorldUpdate(BaseModel):
    """更新世界观条目请求 DTO — 所有字段可选（exclude_unset 语义，同 F1）.

    category: None 表示不修改；"" 表示清除类别（置为未分类）.
    只有传入的字段会被更新，未传入的字段保持不变.
    """
    name: str | None = None
    category: str | None = None
    content: str | None = None

    # name/category/content 复用 WorldCreate 的校验逻辑（None 时直接返回）
```

### 2.6 提取相关模型（§5 详述）

```python
class ExtractedWorldSetting(BaseModel):
    """LLM 提取出的单个世界观条目（schema 校验用）.

    name 非法（空/超长）时该条被跳过并记录 warning，不影响其余条目落库.
    category/content 为 None 或空串时落库为空串（未分类/无内容）.
    """
    name: str                  # 1-50 去空白；非法 → 该条跳过 + warning
    category: str | None = None   # ≤ 50 去空白；None/空串 = 未分类
    content: str | None = None    # ≤ 20000；None/空串 = 无内容


class WorldExtractRequest(BaseModel):
    """世界观信息提取请求."""
    project_id: uuid.UUID
    text: str                  # 必填, 去空白非空, ≤ 50000 字符
    model: str | None = None   # 覆盖项目默认模型（格式 provider/model_name）


class WorldExtractionResult(BaseModel):
    """世界观提取结果 — 合并落库后的报告.

    （无 relations 字段：F10 不建条目关联表，见 §2.3）
    """
    created: list[WorldSetting]
    updated: list[WorldSetting]
    warnings: list[str]
    model: str
```

---

## 3. API 契约

端点风格沿用 F2/F9：**创建/列表/类别汇总嵌套于项目路径**，**详情/更新/删除扁平**。错误响应格式沿用 F1/F2/F9（`{"detail": "..."}` 404 / 422）。

### 3.1 端点总览（8 个，镜像 F9 §3.1 布局；无分组/关系端点，见 §2.2/§2.3）

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/projects/{project_id}/world-settings` | 创建条目 | `WorldCreate` | 201 + WorldSetting |
| GET | `/api/v1/projects/{project_id}/world-settings` | 条目列表 | Query: `?search=&category=&sort_by=&sort_desc=&offset=&limit=` | 200 + `{items, total, offset, limit}` |
| GET | `/api/v1/projects/{project_id}/world-settings/categories` | 类别汇总（含条目数） | — | 200 + `{items, total}` |
| GET | `/api/v1/world-settings/{setting_id}` | 条目详情 | — | 200 + WorldSetting JSON |
| PATCH | `/api/v1/world-settings/{setting_id}` | 更新条目 | `WorldUpdate` | 200 + WorldSetting |
| DELETE | `/api/v1/world-settings/{setting_id}` | 删除条目 | Query: `?force=true` | 204（默认软删除） |
| POST | `/api/v1/world-settings/{setting_id}/restore` | 恢复条目 | — | 200 + WorldSetting |
| POST | `/api/v1/world-settings/extract` | AI 提取世界观信息 | `WorldExtractRequest` | 200 + WorldExtractionResult |

> `POST /world-settings/extract` 在 router 中注册于 `POST /world-settings/{setting_id}` 之前，避免路径歧义（同 F9 characters.py 做法）。

### 3.2 请求/响应示例 — 条目 CRUD

**创建条目**:
```http
POST /api/v1/projects/3f2e1d4a-.../world-settings
Content-Type: application/json

{ "name": "灵气复苏", "category": "设定", "content": "公元 2048 年全球灵气浓度回升，觉醒者出现。" }
```
→ 201
```json
{
  "id": "9b1c2d3e-...", "project_id": "3f2e1d4a-...", "name": "灵气复苏",
  "category": "设定", "content": "公元 2048 年全球灵气浓度回升，觉醒者出现。",
  "extra": {}, "is_deleted": false,
  "created_at": "2026-08-01T10:00:00Z", "updated_at": "2026-08-01T10:00:00Z"
}
```

**列出条目（搜索 + 类别过滤 + 分页）**:
```http
GET /api/v1/projects/3f2e1d4a-.../world-settings?search=灵气&category=设定&sort_by=name&sort_desc=false&offset=0&limit=20
```
→ 200 `{"items": [...], "total": 1, "offset": 0, "limit": 20}`

**同名冲突**:
```http
POST /api/v1/projects/3f2e1d4a-.../world-settings
{ "name": "灵气复苏" }
```
→ 422 `{"detail": "同名世界观条目已存在（条目名在项目内必须唯一）"}`

**更新条目（清除类别）**:
```http
PATCH /api/v1/world-settings/9b1c2d3e-...
{ "content": "（修订版内容……）", "category": "" }
```
→ 200（更新后 WorldSetting JSON，category 为空串）

**软删除 / 恢复 / 硬删除**:
```http
DELETE /api/v1/world-settings/9b1c2d3e-...            → 204（软删除）
POST /api/v1/world-settings/9b1c2d3e-.../restore      → 200 + WorldSetting
DELETE /api/v1/world-settings/9b1c2d3e-...?force=true → 204（物理删除）
```

### 3.3 请求/响应示例 — 类别汇总与提取

**类别汇总**（支持「层级设定」管理的只读视图）:
```http
GET /api/v1/projects/3f2e1d4a-.../world-settings/categories
```
→ 200
```json
{
  "items": [
    {"category": "设定", "count": 4},
    {"category": "规则", "count": 3},
    {"category": "约束", "count": 1}
  ],
  "total": 3
}
```
> 仅统计**活动条目**；空类别（未分类）条目不出现；按 count 降序、category 升序排列。该字段由仓储聚合，不建表。

**AI 提取**:
```http
POST /api/v1/world-settings/extract
Content-Type: application/json

{ "project_id": "3f2e1d4a-...", "text": "第一章正文……" }
```
→ 200
```json
{
  "created": [{"id": "...", "name": "灵气复苏", "category": "设定", ...}],
  "updated": [{"id": "...", "name": "宗门等级", "category": "规则", ...}],
  "warnings": ["条目 \"？？\" 名称为空已跳过"],
  "model": "deepseek/deepseek-chat"
}
```

### 3.4 错误响应格式（沿用 F1/F2/F9/ADR-012）

```json
// 404 — 资源不存在
{"detail": "项目不存在"}
{"detail": "世界观条目不存在"}

// 422 — 业务校验失败 / Pydantic 验证失败
{"detail": "同名世界观条目已存在（条目名在项目内必须唯一）"}
{"detail": "类别不能超过 50 个字符"}
{"detail": "内容不能超过 20000 个字符"}

// 500 — LLM 提取失败（日志记录原始异常，不泄漏堆栈）
{"detail": "世界观提取失败: LLM 输出无法解析，请重试"}
{"detail": "LLM 调用失败，请稍后重试"}
```

**异常映射表**:

| 异常/场景 | 状态码 | 响应 |
|-----------|--------|------|
| 项目/条目不存在（Service 返回 None） | 404 | 见上 |
| 无效 UUID 格式 | 404 | 统一解析失败处理（同 F9 `_parse_id`） |
| 同名条目 | 422 | 服务层业务校验（`WorldNameConflictError`，消息即 detail） |
| Pydantic `ValidationError` | 422 | FastAPI 自动生成 |
| `WorldExtractionError`（LLM 输出解析失败，重试后仍失败） | 500 | `"世界观提取失败: LLM 输出无法解析，请重试"` |
| `LLMRequestError`（F5 重试耗尽） | 500 | `"LLM 调用失败，请稍后重试"` |

---

## 4. CLI 命令签名

遵循 F7 §5 全局约定：`--json` 统一信封 `{"ok": true, "data": ...}` / `{"ok": false, "error": {"code", "message"}}`；退出码 0/1/2/130；错误码 NOT_FOUND / VALIDATION_ERROR / LLM_ERROR / DB_ERROR；删除类命令二次确认 + `--force`；`--json` + 无 `--force` 的删除 → `VALIDATION_ERROR`（沿用 F7 §7）。`world` 组在 F10 落地时并入 F7 命令树（`cli/app.py` 注册，同 F9 character 组）。

### 4.1 world 组（委托 WorldService；无子组——F10 无子实体，见 §2.2/§2.3）

```bash
inkflow world create --project-id <uuid> --name <str> \
    [--category <str>] [--content <str>] [--json]

inkflow world list --project-id <uuid> \
    [--search <str>] [--category <str>] \
    [--sort <name|category|updated_at|created_at>] [--sort-desc/--no-sort-desc] [--json]

inkflow world categories --project-id <uuid> [--json]   # 类别汇总（含条目数）

inkflow world get --id <uuid> [--json]

inkflow world update --id <uuid> \
    [--name <str>] [--category <str|"">] [--content <str>] [--json]
    # --category "" 表示清除类别（置为未分类）

inkflow world delete --id <uuid> [--force] [--permanent] [--json]
inkflow world restore --id <uuid> [--json]

inkflow world extract --project-id <uuid> \
    --text <str> | --text-file <path> [--model <str>] [--json]
```

### 4.2 输出格式

```bash
# 默认人类可读
✅ 世界观条目创建成功: [灵气复苏] (设定)
✅ 条目已删除: [灵气复苏]
✅ 提取完成: 新增 3 个条目, 更新 1 个条目, 跳过 2 条, 警告 2 条
⚠️ 提取完成但有警告: 条目 "？？" 名称为空已跳过; 条目 "灵力体系" 类别超长已跳过

# --json 输出
inkflow world create --project-id ... --name "灵气复苏" --category 设定 --json
→ {"ok": true, "data": {"id": "...", "name": "灵气复苏", "category": "设定", ...}}

inkflow world extract --project-id ... --text-file ch3.txt --json
→ {"ok": true, "data": {"created": [...], "updated": [...],
     "warnings": [...], "model": "deepseek/deepseek-chat"}}

inkflow world get --id 00000000-0000-0000-0000-000000000000 --json
→ {"ok": false, "error": {"code": "NOT_FOUND", "message": "世界观条目不存在"}}   # 退出码 1

inkflow world delete --id ... --json
→ {"ok": false, "error": {"code": "VALIDATION_ERROR", "message": "删除需 --force 或交互确认"}}  # 退出码 1
```

**`--text-file` 设计理由**（同 F9 §4.3）: 章节文本可达数千字，作为命令行参数在 Windows 下受 8191 字符限制；`--text` 与 `--text-file` 互斥（同时传入 → 退出码 2）。

---

## 5. AI 提取模式（样板核心，同 F9 §5）

> ⚠️ **本节与 F9 §5 一一对应，是 F9 骨架的直接复用**：提取管线（模板渲染 → LLM → JSON 解析 → 修复式重试 → 合并落库）的**实现直接对照 F9 `_character_extractor.py`**，仅替换领域实体（WorldSetting ↔ Character）与模板名（world_extract ↔ character_extract）。以下内容为 F10 的实体化副本，供实现与评审对照，不重复设计。

### 5.1 模式总览（同 F9 §5.1 骨架，无 relations 步骤）

```
 ┌────────────────────────────────────────────────────────────┐
 │ 输入: WorldExtractRequest {project_id, text, model?}        │
 └──────────────────────────┬─────────────────────────────────┘
                            ▼
 ① 校验项目存在（F1 ProjectRepository）→ 404
 ② 渲染 world_extract.yaml（F5 PromptManager，变量: text）
 ③ LLMClient.chat(model or project.config.model, temperature=0.2)
 ④ 解析 JSON → Pydantic schema 校验（ExtractedWorldSetting）
    ├─ 失败 → 修复式重试（附错误信息）≤ 2 次 → 仍失败 → WorldExtractionError
 ⑤ 合并落库（单 DB session 事务）:
    └─ 条目: 按 (project_id, name) 匹配活动条目 → 存在=更新(非空覆盖) / 不存在=创建
 ⑥ 返回 WorldExtractionResult（created/updated/warnings + 实际模型）
```

**模式要点（与 F9 §5.1 完全一致）**:
1. **模板与代码分离**: 提取指令在 `infrastructure/llm/templates/world_extract.yaml`（ADR-014/015），领域服务只组装变量
2. **LLM 输出 schema 校验**: 用 Pydantic 模型校验原始 JSON，非法条目**跳过 + warning**，整批非法才抛错
3. **合并锚点 = 项目内唯一键**: 条目用 name，与 §2.4 partial unique 对齐
4. **失败策略**: LLM 调用失败（F5 重试耗尽）→ 透传 `LLMRequestError`；解析失败重试 ≤2 → `WorldExtractionError`；**合并阶段不重试**（已落库数据不可重复合并）
5. **单事务**: 整个合并在一个 session 内完成，任何异常回滚，无部分落库

### 5.2 LLM 模板（`world_extract.yaml`）

```yaml
name: world_extract
description: 从章节文本提取世界观信息条目（结构化 JSON 输出）
system_prompt: |
  你是小说世界观信息提取器。从给定的章节文本中提取明确出现或明确暗示的世界观信息条目，
  包括世界设定、规则、约束、组织、地理、种族、文化、科技、魔法体系等。
  只提取文本中直接出现的或明确暗示的信息，不要臆造。
  输出严格 JSON，不要输出任何其他文字，格式如下：
  {
    "world_settings": [
      {"name": "条目名", "category": "类别或空", "content": "内容描述或空"}
    ]
  }
  category 从以下建议值中选择最合适的：设定、规则、约束、组织、地理、种族、文化、科技、
  魔法体系；无法判断时留空。world_settings 中不要包含重复的条目名。
human_prompt: |
  章节文本：
  {text}
variables:
  - text
```

### 5.3 解析与重试（同 F9 §5.3）

| 场景 | 行为 |
|------|------|
| 输出为合法 JSON 且通过 schema 校验 | 进入合并 |
| 输出含代码块围栏/前后缀文字 | 提取首个 `{...}` 平衡片段（`_extract_json_fragment`），再解析 |
| 仍失败 | 构建修复 Prompt（原输出 + 解析错误信息 + 「只输出 JSON」）重试，`retry_count += 1`，≤ 2 次 |
| 3 次（1 次原始 + 2 次修复）均失败 | `WorldExtractionError`（含原始输出片段，日志记录） |

> 与 F3 格式重试（≤3）同源但更保守（同 F9）：提取是批处理操作，无「部分可用」输出，失败必须显式报错而非静默返回。

### 5.4 合并策略（同名条目规则，同 F9 §5.4 单实体版）

**条目合并（按项目内活动条目 name 精确匹配）**:

| 情况 | 行为 | 计入 |
|------|------|------|
| 项目内存在同名**活动**条目 | 非空提取字段**覆盖**对应字段（category/content 独立判断），更新 updated_at | `updated` |
| 不存在 | 创建新条目 | `created` |
| 存在但已**软删除** | 视为不存在 → **创建新条目**（不隐式恢复旧档案；partial unique 允许） | `created` + warning「存在已删除的同名条目档案」 |
| 提取字段非法（name 空/超长、category/content 超长） | 该条**跳过** | `warnings` |

**幂等性**: 对同一文本重复提取，第二次应产出空 `created`/`updated` 列表（全部命中已有数据，非空字段覆盖后值不变）——这是合并策略正确性的关键验收点（同 F9）。

### 5.5 提取输入约束（同 F9 §5.5）

| 约束 | 值 | 说明 |
|------|-----|------|
| text | 去空白非空，≤ 50000 字符 | 空 → 422「章节文本不能为空」 |
| 默认模型 | `project.config.model` | F1 项目配置 |
| temperature | 固定 0.2（结构化输出低温稳定） | 不对外暴露 |
| 并发 | 不限制（单用户本地工具；同文本并发提取由唯一键兜底） | — |

---

## 6. 分类与查询规则

（对应 F9 §6「关系图谱与分组管理规则」的位置；F10 无图谱/分组，本节承载分类语义与查询规则）

### 6.1 分类语义

- `category` 是条目的**平铺属性**（一对一），不是独立实体（§2.2 决策）：规则/设定/约束等层级通过类别表达
- **建议值清单**（设定/规则/约束/组织/地理/种族/文化/科技/魔法体系）仅用于 LLM 模板引导与 CLI/UI 提示，**不做枚举校验**——LLM 输出类别不可控，受控词表归 F14（同 F9 relation_type 处理）
- **空类别 = 未分类**，允许；`GET /world-settings/categories` 不包含未分类条目，未分类条目通过 `category=` 空串过滤查询
- 类别**层级树**（父子关系）不在 F10 范围（§10）
- 规则/约束类条目在 F6 上下文注入中的**优先级排序**归 F6 集成（§11），F10 只保证 category 可被查询过滤，不预判注入语义

### 6.2 搜索与排序（条目列表，沿用 F1 §6/F9 §6.3）

| 参数 | 默认值 | 约束 | 说明 |
|------|--------|------|------|
| `search` | — | — | 对 name 不区分大小写子串匹配（icontains） |
| `category` | — | 1-50 字符 | 类别**精确**过滤；`category=` 空串查询未分类条目 |
| `sort_by` | `updated_at` | `name` / `category` / `updated_at` / `created_at` | 排序字段 |
| `sort_desc` | `true` | — | 降序 |
| `offset` / `limit` | 0 / 50 | offset ≥ 0, limit [1, 100] | 分页 |

- **类别汇总**（`GET /world-settings/categories`）：活动条目按 category 分组计数（排除空类别），按 count 降序、category 升序返回；由仓储层聚合（`list_categories`），不建表
- 条目**内容**全文检索不在 F10 范围（F22 搜索服务，§10）

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 创建条目名为空/全空白 | 422: "条目名不能为空" |
| 创建条目名 > 50 字符 | 422: "条目名不能超过 50 个字符" |
| 创建条目名与项目内**活动**条目重复 | 422: "同名世界观条目已存在（条目名在项目内必须唯一）" |
| 软删除后**再创建同名条目** | ✅ 成功（partial unique 排除已删除行；服务层同名检查仅限活动条目） |
| category > 50 字符 | 422: "类别不能超过 50 个字符" |
| content > 20000 字符 | 422: "内容不能超过 20000 个字符" |
| 获取/更新/软删除/硬删除不存在的条目 | 404: "世界观条目不存在" |
| 硬删除已软删除的条目 | 404: "世界观条目不存在"（已排除） |
| 恢复不存在的条目 | 404: "世界观条目不存在" |
| 恢复未删除的条目 | 正常返回（重复操作无毒，同 F1） |
| 条目不存在 / 无效 UUID 格式 | 404: "世界观条目不存在"（统一 `_parse_id` 处理） |
| 提取 text 为空/全空白 | 422: "章节文本不能为空" |
| 提取 text > 50000 字符 | 422: "章节文本不能超过 50000 个字符" |
| 提取时项目不存在 | 404: "项目不存在" |
| LLM 返回非 JSON / 无法解析 | 修复重试 ≤ 2 → 仍失败 → 500: "世界观提取失败: LLM 输出无法解析，请重试" |
| LLM 返回空条目列表 | 200 + 空 created/updated + warning "未提取到世界观信息" |
| LLM 输出中个别条目非法（空名等） | 该条跳过 + warning，**不影响其他条目落库** |
| 提取时 LLM 调用失败（网络/Key） | 500: "LLM 调用失败，请稍后重试"（F5 已内部重试 3 次） |
| 合并中途 DB 错误 | 整体回滚（单事务），无部分落库 |
| 条目列表搜索/类别过滤无结果 | 200: `{"items": [], "total": 0}` |
| 分页越界 | 200: 空 items（同 F1） |
| 类别汇总无活动条目 | 200: `{"items": [], "total": 0}` |
| 项目硬删除 | 条目级联物理删除（FK CASCADE）；项目软删除不影响条目数据 |
| `--text` 与 `--text-file` 同时传入 | CLI 退出码 2（用法错误） |
| 提取合并幂等性 | 同文本二次提取 → created/updated 为空（全部命中已有） |

---

## 8. 文件结构

遵循 ADR-007v2 包结构，与 F9 真实源码树一一对应。新增/修改文件：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── world.py             ← CREATE: WorldSetting, WorldCreate, WorldUpdate,
│   │   │                             WorldExtractRequest, WorldExtractionResult,
│   │   │                             ExtractedWorldSetting
│   │   └── __init__.py          ← MODIFY: 导出新模型
│   ├── ports/
│   │   ├── world_repository.py  ← CREATE: WorldRepositoryProtocol
│   │   ├── world_errors.py      ← CREATE: WorldExtractionError / WorldServiceError /
│   │   │                             WorldNotFoundError / ProjectNotFoundError /
│   │   │                             WorldNameConflictError
│   │   └── __init__.py          ← MODIFY: 导出
│   └── services/
│       ├── world_service.py     ← CREATE: WorldService（条目 CRUD + extract 入口）
│       ├── _world_extractor.py  ← CREATE: 提取管线（对照 F9 _character_extractor.py
│       │                             骨架：模板渲染 → LLM → JSON 解析 → 修复重试 → 合并）
│       └── __init__.py          ← MODIFY
├── infrastructure/
│   ├── llm/templates/
│   │   └── world_extract.yaml   ← CREATE: 提取模板（§5.2）
│   └── database/
│       ├── models/
│       │   ├── world.py         ← CREATE: WorldSettingORM
│       │   │                        （partial unique index, FK, soft-delete 标记）
│       │   └── __init__.py      ← MODIFY: 注册 WorldSettingORM（create_tables 依赖）
│       └── repositories/
│           ├── world_repo.py    ← CREATE: SQLiteWorldRepository
│           └── __init__.py      ← MODIFY
├── api/
│   ├── routers/
│   │   ├── world_settings.py    ← CREATE: 8 个端点（条目 CRUD + categories + extract）
│   │   └── __init__.py          ← MODIFY
│   ├── deps.py                  ← MODIFY: get_world_service
│   └── app.py                   ← MODIFY: 注册 world_settings.router
└── cli/
    ├── commands/
    │   ├── world.py             ← CREATE: world 组（create/list/categories/get/update/
    │   │                             delete/restore/extract）
    │   └── __init__.py          ← MODIFY
    └── app.py                   ← MODIFY: 注册 world 命令组

backend/tests/
├── unit/
│   ├── test_world_models.py     ← CREATE: 领域模型/DTO 验证 + 提取 DTO schema
│   ├── test_world_repo.py       ← CREATE: 仓储集成测试（in-memory SQLite，含 partial unique）
│   ├── test_world_service.py    ← CREATE: 服务测试（条目 CRUD + 业务校验）
│   ├── test_world_extraction.py ← CREATE: 提取管线测试（Mock LLM：解析/重试/合并/幂等）
│   └── test_world_api.py        ← CREATE: API 集成测试（Mock Service）
└── test_cli_world.py            ← CREATE: CLI 测试（Mock WorldService，信封/退出码）
```

> 测试文件位置与现有树一致（同 F9）：仓储/API 集成测试放 `tests/unit/`，CLI 测试放 `tests/` 根。

### 8.1 WorldRepositoryProtocol（参照 F9 `character_repository.py` Protocol 风格）

```python
class WorldRepositoryProtocol(Protocol):
    """世界观条目仓储端口.

    按 spec §2.4: 项目内活动条目 name 唯一（partial unique）；
    软删除后同名可复用。list_categories 聚合活动条目类别计数。

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9）。
    """

    # ── WorldSetting ──
    async def add(self, setting: WorldSetting) -> WorldSetting: ...
    async def get(self, setting_id: int) -> WorldSetting | None: ...
    async def get_by_name(self, project_id: int, name: str) -> WorldSetting | None: ...
    async def list(self, project_id: int, search: str | None = None,
                   category: str | None = None, sort_by: str = "updated_at",
                   sort_desc: bool = True, offset: int = 0,
                   limit: int = 50) -> tuple[builtins.list[WorldSetting], int]: ...
    async def list_categories(self, project_id: int) -> builtins.list[tuple[str, int]]: ...
    async def update(self, setting: WorldSetting) -> WorldSetting: ...
    async def soft_delete(self, setting_id: int) -> bool: ...
    async def restore(self, setting_id: int) -> WorldSetting | None: ...
    async def hard_delete(self, setting_id: int) -> bool: ...
```

> 仓储层方法入参用 int（与 F9/SummaryRepositoryProtocol 一致）；Service 负责 UUID ↔ int 转换（沿用 F1 `_to_int_id` 模式）。

---

## 9. 测试策略

### 测试层次（沿用 ADR-018 三层目录 + pytest markers；六层结构同 F9 §9）

```text
单元测试: 领域模型/DTO 验证 + 提取 DTO schema          ~12 cases
集成测试: SQLiteWorldRepository（in-memory SQLite）     ~14 cases
服务测试: WorldService（Mock Repository）               ~12 cases
提取测试: 提取管线（Mock LLM，全合并分支）              ~13 cases
API 测试: 8 端点（Mock Service）                       ~14 cases
CLI 测试: world 组（Mock WorldService）                ~16 cases
```

### 关键测试场景

**领域模型**: name 空/空白/超长 → ValidationError / category 空串合法、超长 → ValidationError / content 超长 → ValidationError / 默认值（category="", content=""）/ WorldUpdate 部分更新语义（category: None 不修改、"" 清除）/ ExtractedWorldSetting schema（name 必填、category/content 可空）/ WorldExtractRequest（text 空 → 422、超长 → 422）

**仓储**: 条目 CRUD 往返 / `get_by_name` 命中与未命中 / 活动同名唯一（partial unique：插入第二个活动同名 → IntegrityError；软删除后可再插同名）/ 软删除后 get 返回 None / `list` 搜索与 category 过滤 / `list_categories` 聚合（计数、排除空类别、排序）/ 分页 / 硬删除 FK 级联（项目删除 → 条目级联）

**服务**: 创建/更新/软删/恢复全流程 / 同名活动条目 → 422 / 条目不存在各操作 → None → 404 / extract 入口编排（项目不存在 → 404；extractor/project_repo 未注入 → 配置错误）

**提取（Mock LLM，遵循 ADR-015；断言同 F9）**:
- 合法 JSON → 全部落库，created/updated 计数正确
- 同名已存在 → 更新（非空覆盖，`updated`），幂等性（二次提取全空）
- 软删除同名 → 新建 + warning
- 非法条目（空名/超长）→ 跳过 + warning，其余正常落库
- 输出带围栏/前缀文字 → `_extract_json_fragment` 提取成功
- 输出完全非法 → 修复重试 2 次 → WorldExtractionError
- Mock LLM 抛 LLMRequestError → 透传（不消耗解析重试）
- 空条目列表 → 空结果 + warning
- 断言 Prompt 使用 world_extract 模板 + 变量 text + 项目默认模型 + temperature 0.2

**API**: 8 端点成功路径 / 404 全路径（项目/条目）/ 422 业务校验（同名冲突、字段超长）/ extract 200 / extract LLM 失败 → 500 / categories 汇总 / 无效 UUID → 404

**CLI**: 各子命令成功路径与参数透传 / 信封格式与退出码 0/1/2 / delete 二次确认 + `--force` / `--json` + delete 无 `--force` → VALIDATION_ERROR / `--text` 与 `--text-file` 互斥 → 退出码 2 / extract 人类可读摘要与 `--json` 完整结果 / NOT_FOUND、LLM_ERROR 错误信封

### 覆盖率目标

- F10 模块行覆盖率 **≥ 80%**（DTO 验证 100%、合并策略全分支，同 F9）
- 全仓覆盖率 **≥ 60%**（0.2.0 DoD，ADR-019）
- CI 门禁：ruff + mypy + pytest 全绿（ADR-017/018）

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|----------|
| 增量提取 / 批量章节提取 / 全书扫描 / 定时提取 | **F14 统一提取服务**（#44）——F10 只做单次单文本基础提取 |
| 指代消解（「这个世界」「法则」等归并到具体条目） | F14（依赖全文索引/上下文） |
| 提取预览（dry-run，先看后落库） | F14 或 0.2.x 增强；MVP 以结果报告（created/updated）代替 |
| 受控类别词表（枚举/自定义类别库） | F14 定义（F10 用自由文本 ≤50 字符 + 建议值清单，同 F9 relation_type 处理） |
| 条目间关系/引用图谱（WorldRelation 表） | **Phase 2+**（F14 后按需引入；MVP 用 content 自由文本引用，决策见 §2.3/§12） |
| 类别层级树（category 父子关系/继承） | Phase 2+（F16 一致性审计可能需要「规则→设定」溯源） |
| 规则/约束冲突检测（条目间矛盾） | F16 一致性审计（Phase 2） |
| F6 `world_setting` 数据源真实实现（替换空实现） | 集成点，见 §11 与待澄清 Q1 |
| 世界观版本历史 / 条目变更审计日志 | F15 审计服务（Issue 待创建） |
| 写作时世界观一致性检查 | F16 一致性审计（Phase 2） |
| 条目内容全文检索 | F22 搜索服务（Phase 3） |
| 跨项目世界观共享/引用/合并 | Phase 4 云端 |
| 世界观可视化 / 导出 | F18 Web UI（0.3.0）/ F21 导出服务（0.6.0） |

---

## 11. 依赖关系

与 F1 §11 / F2 §11 / F9 §11 已声明依赖保持一致（F1 被依赖列表含 F6/F7，F2 被依赖列表含 F6/F7，F9 在其上追加；F10 同构）：

```text
F10 依赖:
  F1 (project_service) ✅ — 项目存在性校验（404）；project.config.model 作为提取默认模型
  F5 (llm_service)     ✅ — LLMClientProtocol.chat + PromptTemplateProtocol（world_extract 模板，
                             ADR-014/015 隔离：domain/ 零 LangChain import，CI 强制检查）
  F2 (chapter_service) — 可选：CLI extract --text-file 读取章节内容时不做 F2 校验（直接文本输入），
                          不产生硬依赖

F10 被依赖:
  F6 (context_service) ✅ — world_setting 数据源（compressible 层，见 F6 spec §3.2）：
                            F6 已留 ContextSourceProtocol 空实现 WorldSettingSource
                            （infrastructure/context/sources.py，注释为 ADR-019 前旧编号
                            「F9 世界设定数据源」），0.2.0 替换为真实实现（基于 F10 Repository
                            查询世界观条目）。实现归属待澄清（Q1，同 F9 Q1）
  F7 (CLI)             ✅ — world 命令组并入 F7 命令树（cli/app.py 注册）
  F14 (统一提取)        ⏳ — (#44) 复用 F10 的合并/落库能力与唯一键约定
  F15 (审计)            ⏳ — (Issue 待创建) 世界观条目变更作为审计数据源
  F20 (MCP)             ⏳ — (Phase 3) manage_world 工具基于本模块 API
```

> ⚠️ **编号口径说明**: F6 spec §10 与 `infrastructure/context/sources.py` 中 WorldSettingSource 注释「F9 世界设定数据源」为 ADR-019 之前的旧编号（旧口径 F8=角色/F9=世界观）；按 [ADR-019](../../adr/ADR-019.md) 现行口径 **F9 = 角色管理**、**F10 = 世界观**、F14 = 统一提取。本 spec 及后续 F 模块一律以 ADR-019 为准（与 F9 spec §11 同一声明）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| 分类建模 | `category` 为 WorldSetting 字段（自由文本 ≤50 字符，空串=未分类），**不建独立类别/分组表** | PRD「层级设定（规则/设定/约束）」是条目类别属性而非容器实体；类别无独立生命周期（描述/排序/成员数），独立表徒增 CRUD 且与 AI 提取「条目+类别一并落库」的流程不匹配；需要时从字段迁移到表是低成本演进 |
| 条目关联 | **MVP 不建 WorldRelation 表**；「规则A 约束 设定B」用 content 自由文本表达 | PRD P1-02 未要求条目间关系图谱；世界观条目间引用是增强语义而非创作核心结构（与 F9 角色关系不同）；避免过度设计（P5 YAGNI），F14 后按需对照 F9 §2.3/§6.1 引入 |
| 同名语义 | 「项目内活动条目 name 唯一」= 同一条目 | 这是 AI 提取合并的锚点（§5.4），也防止手误重复建档 |
| 唯一约束实现 | SQLite partial unique index（`WHERE is_deleted = 0`） | 软删除后再创建同名条目合法；比「服务层检查 + 全表唯一」更稳（DB 兜底） |
| 合并策略 | 非空字段覆盖；不隐式恢复软删除档案 | 确定性、幂等、可重跑；隐式恢复会带来「意外复活」的不可预期行为 |
| 提取重试 | 解析失败修复式重试 ≤ 2 次（F3 模式），合并阶段不重试 | 提取无部分可用输出，失败显式报错；合并重试会导致重复写入 |
| 提取温度 | 固定 0.2 低温 | 结构化 JSON 输出稳定性优先（F3/F9 先例） |
| 提取模板 | `world_extract.yaml` 走 F5 PromptManager | ADR-014/015：模板与代码分离、domain/ 零 LangChain |
| 提取管线 | **完全复用 F9 §5 骨架**（对照 `_character_extractor.py` 实现） | F9 spec 明示「F10 实施时直接对照 F9 §5 与对应文件结构，不应重新发明」；仅替换实体与模板名 |
| 端点布局 | 创建/列表/类别汇总嵌套项目路径，详情扁平（同 F2/F9） | 与 F2 §3/F9 §3 端点风格一致，OpenAPI 分组清晰 |
| extract 端点 | `POST /api/v1/world-settings/extract`（动作型，返回 200） | 与 F3 writing / F9 characters 动作型端点一致；单次同步调用，不做任务队列（YAGNI） |
| 类别汇总端点 | `GET /world-settings/categories`（只读聚合） | 「层级设定」管理的最小可用视图（各类别条目数一目了然）；单条聚合查询，成本极低 |
| CLI 布局 | `inkflow world` 顶级组（无子组） | 条目是顶级实体；F9 character 的 group 子组因分组是子实体，F10 无子实体故不嵌套 |
| 文本输入 | `--text` / `--text-file` 双通道 | Windows 命令行参数 8191 字符限制，章节文本需文件通道 |
| 提取事务 | 合并单 session 事务，失败全回滚 | 无部分落库；合并失败不会留下半套条目 |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 领域模型 + DTO 验证（含 partial unique 语义、提取 DTO schema） | `pytest tests/unit/test_world_models.py -v` 全绿 |
| M2 | 仓储层全部方法（条目 CRUD + 类别汇总 + 唯一约束） | `pytest tests/unit/test_world_repo.py -v` 全绿 |
| M3 | 服务层 CRUD + 业务校验（同名冲突等） | `pytest tests/unit/test_world_service.py -v` 全绿 |
| M4 | AI 提取管线（解析/重试/合并策略/幂等性，Mock LLM） | `pytest tests/unit/test_world_extraction.py -v` 全绿 |
| M5 | API 8 端点 + 错误路径全绿 | `pytest tests/unit/test_world_api.py -v` 全绿 |
| M6 | CLI world 组（信封/退出码/确认交互/双文本通道） | `pytest tests/test_cli_world.py -v` 全绿 |
| M7 | 真实 LLM 联调：对一章正文执行 extract 成功落库 | 手工验证（配置任一 Provider Key，`inkflow world extract`） |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest -v` 全绿；F10 模块行覆盖 ≥ 80%、全仓 ≥ 60%（0.2.0 DoD）；ruff + mypy 通过（CI 门禁 ADR-017） |
| M9 | domain/ 零 LangChain import | CI 强制检查通过（沿用 F5/F6/F9 约束） |

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | F6 `WorldSettingSource` 空实现（`infrastructure/context/sources.py`）的替换是否纳入 F10 里程碑？该文件属 F6 模块，但真实实现依赖 F10 Repository | 影响 F10 收尾范围与 F6 文件修改归属 | 建议：F10 只交付实体/查询能力；替换作为 0.2.0 内 F6 联调任务（写 F10 plan 时单独列出）——**同 F9 Q1 决策** |
| Q2 | 分类/关联语义确认：MVP 按「category 自由文本字段 + 不建条目关联表」实现（本 spec 已按此设计）；是否需要独立类别表（类别描述/排序/管理）或条目间关联表（WorldRelation）？ | 影响数据模型与 API（独立表需新增 CRUD 端点） | 建议：保持字段方案，独立类别表/关联表列入 Phase 2+（F14 后按需）——**同 F9 Q2 决策 A（MVP 最小集）** |
| Q3 | 条目软删除后再次提取到同名条目：当前设计为「新建新档案 + warning」。是否期望「自动恢复旧档案并合并」？ | 影响合并策略与数据生命周期 | 建议：保持新建（不隐式恢复），旧档案由用户显式 restore——**同 F9 Q3 决策 A** |

---

*本文档为 F10 功能规格（What），实施步骤（How）见后续 `specs/f10-world-service/plan.md`。所有里程碑验收以本节 M1-M9 为准。*
