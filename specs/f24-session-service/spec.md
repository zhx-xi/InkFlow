# F24: 会话管理（session_service）— 功能规格

> **Spec 版本**: 1.2 | **日期**: 2026-08-07 | **依据**: PRD v2.1 §6.2 P1-13 会话管理（持久化/多会话/恢复），Constitution P1-P6
>
> **Spec 变更**（1.0 → 1.3）: ① 1.1 删除语义按用户拍板修订为**两级删除**（首次 DELETE = 归档可解除；已归档再 DELETE = 真实删除；force 直删）——§2.5/§3.1/§3.2/§4/§7/§9/§12/§13 同步；② 1.2 待澄清 Q1/Q2/Q3 全部拍板（2026-08-07）：Q1 project_id 可空维持 / Q2 终态允许追加日志维持 / Q3 会话↔执行 MVP 软关联（新增 §5.4b 可观测键约定 + §12 决策 9 + §10 归位）；③ 1.3 F25 daemon 移除（ADR-029，2026-08-07 用户拍板）：task 会话类型保留，语义 = 外部 agent 任务履历（F20 MCP / ADR-022 skills 调用），全文「F25 daemon」表述改写
>
> **所属阶段**: 0.5.0 Agent 集成（第 1 个模块，估算 2-3 人天）
>
> **关联 Issues**: #51（F24 会话管理）；#49（F20 MCP，**被依赖**——外部 agent 任务调用方）
>
> **依赖**: ✅ F1（项目实体，project_id 可空引用）· ⏳ F20（MCP Server，本模块是被依赖方）· ⏳ F3（写作会话上下文快照，Phase 2+ 联动）
>
> **参考 ADR**: [ADR-019](../../adr/ADR-019.md)（版本里程碑/编号口径）· [ADR-018](../../adr/ADR-018.md)（测试分层）· [ADR-004](../../adr/ADR-004.md)（领域+ORM 双模型）· [ADR-012](../../adr/ADR-012.md)（错误处理）
>
> **状态**: 待实现 🔲

---

## 1. 概述

F24 会话管理为 InkFlow 提供**用户可见的业务会话**：写作会话（writing）与任务会话（task）的统一载体。会话实体记录一次写作/任务过程的**生命周期状态**（active/paused/completed/failed）、**上下文快照**（可恢复的续写/续跑依据）与**履历日志**（SessionLog 时间线条目），满足 PRD P1-13「会话持久化 / 多会话管理 / 会话恢复」。

### 1.1 模块类型定位（第 11 变体：会话履历型）

按 AGENTS.md 模块类型谱系计数（f15=6 / f16=7 / f23=8 / f19=9 / f26=10），本模块为 **第 11 变体「会话履历型」**，特征：

```
F13 状态机（动作端点迁移）  ×  F12 无 LLM（确定性）  ×  双实体父子（容器语义，同 F11）
        └───────────────▶  Session + SessionLog + 状态机 + 履历查询
```

| 维度 | 本模块 |
|------|--------|
| LLM 管线 | ❌ 无（无 `infrastructure/llm/templates/` 目录、无 `_*_generator/extractor.py`） |
| 业务实体 | ✅ Session（会话主实体）+ SessionLogEntry（日志子实体，容器语义） |
| 状态机 | ✅ 四态（active/paused/completed/failed），动作端点迁移（同 F13 模式） |
| 唯一约束 | ❌ 不设（会话是**实例**非档案：可创建多个同标题会话，无「同名 = 同一会话」语义，同 F12 §2.4） |
| 错误面 | NOT_FOUND / VALIDATION_ERROR / DB_ERROR（无 LLM_ERROR，同 F12） |
| 跨模块 MODIFY | 无（纯新增；F20 MCP / ADR-022 skills 消费本模块端口，本模块不反向依赖） |

### 1.2 会话与 F4 AgentExecution 的边界（关键声明）

| | F4 `AgentExecutionORM`（agent_executions / agent_stage_results） | F24 `Session`（sessions / session_logs） |
|---|---|---|
| 视角 | **管线内部执行记录**（pipeline 标识、stage 快照、retry_count、duration_ms） | **用户可见业务会话**（类型/状态/上下文快照/履历日志） |
| 粒度 | 一次管线运行（write_chapter 全流程） | 一次业务会话（写作会话可含多次执行；任务会话对应一次外部 agent 任务） |
| 消费方 | F4 agent_service / 调试 | CLI/API/未来 GUI/F20 MCP / ADR-022 skills（履历查询） |
| 关联 | — | **MVP 软关联**：SessionLog.payload 可观测键（`execution_id`/`agent_name`/`stage`/`tool_calls`，契约见 §5.4）；正式 FK 与 CI/CD 式执行视图归 0.7.0 Agent 化升级（Q3 拍板 2026-08-07） |

> 会话是**跨执行的任务/写作意图**，执行记录是**单次运行的技术细节**——两者并存不重叠。F24 不读取、不修改 F4 表。

### 1.3 用户拍板（2026-08-07 时间表设计会话）

- **会话承载任务履历**：外部 agent 任务（F20 MCP / ADR-022 skills 调用）基于会话——任务触发来源多样（用户 CLI 设定 / chat 指令 / 其他 agent 经 MCP/skill 调用），统一以会话记录生命周期 + 履历日志，用户可查看任务履历/历史日志
- **F20 依赖 F24**：F20 MCP Server spec 基于本 spec 定稿（被依赖方）
- **外部 agent 调用形态**：进度通知写入本模块 SessionLog（本 spec §5.4 预留进度写入契约）——原 F25 daemon 载体已移除（ADR-029，2026-08-07：伪需求判定；task 会话类型保留，语义 = 外部 agent 任务履历）

---

## 2. 数据模型

遵循 F1 Project 的「领域 Pydantic 实体 + 请求/更新 DTO + ORM 双模型」模式（ADR-004）。领域层 id 为 UUID，数据库 int 自增映射（同 F1 §12；**SessionLogEntry 用独立 UUID，不依赖 DB 自增**——日志追加由服务层分配 seq 序号，DB 层仅物理存储）。

### 2.1 Session（会话主实体）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，DB int 自增映射 |
| session_type | SessionType | NOT NULL, 已索引 | 会话类型：`writing`（写作会话）/ `task`（任务会话），见 §2.3 |
| status | SessionStatus | NOT NULL, DEFAULT "active", 已索引 | 会话状态：`active` / `paused` / `completed` / `failed`，见 §2.4 状态机 |
| project_id | UUID? | NULLABLE, FK→projects.id (SET NULL), 已索引 | 关联项目（可空 = 全局/未关联会话，如纯任务履历；写作会话通常挂项目） |
| title | str | NOT NULL, 1-100 字符, 去空白 | 会话标题（如「第三章续写」「每日定时写作」） |
| description | str | NOT NULL, DEFAULT "", ≤ 5000 字符 | 会话描述/备注 |
| context | dict[str, Any] | NOT NULL, DEFAULT {} | **上下文快照**（JSON）：写作会话 = 恢复续写所需的上下文（项目/章节/模式/参数快照）；任务会话 = 任务参数（外部 agent 目标/LLM 配置）。恢复语义见 §5.3 |
| result | dict[str, Any] | NOT NULL, DEFAULT {} | 结果快照（completed 时填充：写作产出摘要/任务执行摘要/统计） |
| error | str | NOT NULL, DEFAULT "" | 失败原因（failed 时填充，≤ 2000 字符） |
| started_at | datetime | NOT NULL, AUTO | 会话开始时间 (UTC)（= 创建时间） |
| paused_at | datetime? | NULLABLE | 最近一次暂停时间 (UTC) |
| completed_at | datetime? | NULLABLE | 完成/失败时间 (UTC) |
| created_at | datetime | NOT NULL, AUTO | 创建时间 (UTC) |
| updated_at | datetime | NOT NULL, AUTO | 更新时间 (UTC) |

**业务规则**:
- `title` **允许重复**：会话是实例（可创建多个「每日写作」任务会话），无自然业务唯一键（同 F12 §2.4，不设 partial unique index）
- `status` **不允许通过 PATCH 直接修改**：状态迁移走专用动作端点（pause/resume/complete/fail，见 §3），保证迁移规则单一入口、可校验（同 F13 §2.4 模式）
- `project_id` 可空：会话不强制绑定项目——任务履历可能跨项目（如全局外部 agent 任务）；写作会话由调用方决定是否挂项目（外部 agent 任务挂目标项目）
- 归档的会话**不进入**列表查询；日志随会话归档**不单独隐藏**（见 §2.5）

### 2.2 SessionLogEntry（日志子实体）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，DB int 自增映射 |
| session_id | UUID | NOT NULL, FK→sessions.id (CASCADE), 已索引 | 所属会话 |
| seq | int | NOT NULL, ≥ 1 | 会话内**递增序号**（1 起，服务层分配 = 会话内 max(seq)+1）；日志按 (seq ASC) 稳定排序 |
| level | str | NOT NULL, DEFAULT "info" | 日志级别：`info` / `warning` / `error` |
| message | str | NOT NULL, 1-2000 字符, 去空白 | 日志消息（如「开始写作章节 3」「LLM 调用失败，重试第 2 次」「任务完成，共 1280 字」） |
| payload | dict[str, Any] | NOT NULL, DEFAULT {} | 结构化负载（如进度百分比、token 消耗、章节 id） |
| created_at | datetime | NOT NULL, AUTO | 日志时间 (UTC) |

**业务规则**:
- `seq` 会话内唯一（服务层保证：追加时 `max(seq)+1`，同 F12 `next_position` 模式）；日志**不支持更新/删除**（履历不可篡改，追加语义）
- 日志是**会话履历**：任务进度、失败原因、恢复点、执行摘要均以日志条目呈现（§5.4 进度写入契约）
- 会话归档 → 日志**保留**（履历可追溯，仅在会话详情/日志查询按会话可见性过滤）；会话真实删除 → 日志级联物理删除（FK CASCADE）

### 2.3 会话类型设计决策（字段 vs 独立子类）

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **类型字段 + 统一上下文快照（选定）** | 单表零复杂度；context/result 为 JSON 自由结构，写作/任务各自约定键；类型只决定默认行为与校验 | 类型特定字段无强类型约束（依赖 JSON 键约定） | ✅ MVP——会话是**轻量载体**，深层语义由消费方（F3/F20）约定；强类型子类表 YAGNI（§10） |
| writing/task 分表 | 各自字段强类型 | 两套 CRUD/状态机/日志复制；跨类型履历查询需联合 | ❌ 否决（复杂度翻倍，无对应收益） |
| 纯 JSON 无类型字段 | 最简 | 无法区分写作会话与任务会话的**校验/行为**（如任务会话不允许写作恢复语义） | ❌ 否决（类型是状态机行为的前提） |

### 2.4 状态机定义（active / paused / completed / failed）

```
                    pause                    complete
  active ────────────▶ paused ────────────────▶ completed（终态）
    │                    │                        ▲
    │                    │ resume                 │
    │                    └───────────────▶ active ─┘
    │
    ├── complete ────────────────────────▶ completed（终态）
    └── fail ────────────────────────────▶ failed（终态）
```

**状态机规则**:
- `active` → `paused`（pause）：暂停进行中的会话；记录 paused_at = now
- `paused` → `active`（resume）：恢复暂停的会话；**恢复语义** = 会话重新可被消费（外部 agent 续跑任务 / 写作恢复上下文），见 §5.3；清空 paused_at
- `active` → `completed`（complete）：正常完成；记录 completed_at = now；result 由调用方在 complete 请求中提供
- `active` → `failed`（fail）：异常终止；记录 completed_at = now（统一终态时间戳）；error 由调用方提供
- `paused` → `completed` / `paused` → `failed`：**允许**（暂停后直接判定终态——用户暂停后放弃/完成）
- `completed` / `failed` → 任意：**禁止**（终态不可逆；如需重跑 → 新建会话，MVP 不支持 reopen——YAGNI 论证见 §12）
- 归档状态与会话状态**正交**：任何状态的会话都可归档（归档 = 从列表隐藏，履历通过详情仍可查，见 §2.5）

### 2.5 删除语义（归档 → 真实删除，两级；用户拍板 2026-08-07）

产品语言：**归档**（= 软删除，is_deleted=True）；两级删除流程：

- **归档**：第一次 `DELETE /api/v1/sessions/{id}` → is_deleted=True；列表/履历查询不显示；详情直接访问仍可读（与 F12/F13 事件软删一致）；**可解除归档**
- **解除归档**：`POST /api/v1/sessions/{id}/restore` → is_deleted=False（同 F12/F13 restore 端点）
- **真实删除**：对**已归档**会话再次 `DELETE /api/v1/sessions/{id}` → 物理删除 + 日志级联（FK CASCADE，不可恢复）；`?force=true` 可对活动会话一次真实删除（显式通道，与归档流程并列）
- 归档会话的日志条目在会话详情中仍可见（`GET /api/v1/sessions/{id}` 不因归档隐藏子资源——用户需追溯历史履历）；但 `GET /api/v1/sessions/{id}/logs` **跟随会话归档返回 404**（列表型查询不暴露归档会话的子资源，同 F12 软删事件不进入任何查询结果）

### 2.6 领域模型（Pydantic v2 语法，参照 F12 `domain/models/timeline.py`）

```python
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SessionType(StrEnum):
    """会话类型."""

    WRITING = "writing"   # 写作会话（上下文快照供 F3 恢复续写）
    TASK = "task"         # 任务会话（外部 agent 任务履历）


class SessionStatus(StrEnum):
    """会话状态（§2.4 状态机）."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class LogLevel(StrEnum):
    """日志级别."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


def _validate_title(v: str) -> str:
    """共享的标题校验：去空白后非空且不超过 100 字符."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("会话标题不能为空")
    if len(stripped) > 100:
        raise ValueError("会话标题不能超过 100 个字符")
    return stripped


def _validate_description(v: str) -> str:
    """共享的描述校验：不超过 5000 字符."""
    if len(v) > 5000:
        raise ValueError("会话描述不能超过 5000 个字符")
    return v


def _validate_message(v: str) -> str:
    """日志消息校验：去空白后非空且不超过 2000 字符."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("日志消息不能为空")
    if len(stripped) > 2000:
        raise ValueError("日志消息不能超过 2000 个字符")
    return stripped


class Session(BaseModel):
    """会话领域实体. 对应 sessions 表."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    session_type: SessionType
    status: SessionStatus = SessionStatus.ACTIVE
    project_id: uuid.UUID | None = None
    title: str
    description: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    started_at: datetime
    paused_at: datetime | None = None
    completed_at: datetime | None = None
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class SessionCreate(BaseModel):
    """创建会话请求 DTO."""

    session_type: SessionType
    project_id: uuid.UUID | None = None
    title: str
    description: str = ""
    context: dict[str, Any] = Field(default_factory=dict)

    _title = field_validator("title")(_validate_title)
    _description = field_validator("description")(_validate_description)


class SessionUpdate(BaseModel):
    """更新会话请求 DTO（不承载 status——状态机走动作端点，同 F13）."""

    title: str | None = None
    description: str | None = None
    context: dict[str, Any] | None = None

    @field_validator("title")
    @classmethod
    def _validate_title_opt(cls, v: str | None) -> str | None:
        return _validate_title(v) if v is not None else None

    @field_validator("description")
    @classmethod
    def _validate_description_opt(cls, v: str | None) -> str | None:
        return _validate_description(v) if v is not None else None


class SessionLogEntry(BaseModel):
    """会话日志条目领域实体. 对应 session_logs 表."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    session_id: uuid.UUID
    seq: int
    level: LogLevel = LogLevel.INFO
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SessionLogCreate(BaseModel):
    """追加日志请求 DTO."""

    level: LogLevel = LogLevel.INFO
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)

    _message = field_validator("message")(_validate_message)


class SessionComplete(BaseModel):
    """完成会话请求 DTO（active/paused → completed）."""

    result: dict[str, Any] = Field(default_factory=dict)


class SessionFail(BaseModel):
    """失败会话请求 DTO（active/paused → failed）."""

    error: str

    @field_validator("error")
    @classmethod
    def _validate_error(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("失败原因不能为空")
        if len(stripped) > 2000:
            raise ValueError("失败原因不能超过 2000 个字符")
        return stripped


class SessionView(BaseModel):
    """会话 + 履历摘要视图（详情/列表项）."""

    session: Session
    log_count: int
    last_log: SessionLogEntry | None = None
```

---

## 3. API 契约

端点风格：**会话是全局资源**（不嵌套于项目路径——任务履历跨项目，与 F12 项目级事件不同）；会话 CRUD 扁平 + 日志子资源嵌套会话路径。错误响应格式沿用 F1/F2/F9/F10/F11（`{"detail": "..."}` 404 / 422）。

### 3.1 端点总览（12 个：会话 CRUD 6 + 状态机 4 + 日志 2，镜像 F13 布局）

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/sessions` | 创建会话 | `SessionCreate` | 201 + SessionView |
| GET | `/api/v1/sessions` | 会话列表（履历查询） | Query: `?session_type=&status=&project_id=&search=&offset=&limit=` | 200 + `{items, total, offset, limit}` |
| GET | `/api/v1/sessions/{session_id}` | 会话详情（含履历摘要） | — | 200 + SessionView |
| PATCH | `/api/v1/sessions/{session_id}` | 更新会话（标题/描述/上下文） | `SessionUpdate` | 200 + Session |
| POST | `/api/v1/sessions/{session_id}/pause` | 暂停（active→paused） | — | 200 + Session |
| POST | `/api/v1/sessions/{session_id}/resume` | 恢复（paused→active） | — | 200 + Session |
| POST | `/api/v1/sessions/{session_id}/complete` | 完成（active/paused→completed） | `SessionComplete` | 200 + Session |
| POST | `/api/v1/sessions/{session_id}/fail` | 失败（active/paused→failed） | `SessionFail` | 200 + Session |
| POST | `/api/v1/sessions/{session_id}/logs` | 追加日志条目 | `SessionLogCreate` | 201 + SessionLogEntry |
| GET | `/api/v1/sessions/{session_id}/logs` | 日志列表（履历） | Query: `?offset=&limit=` | 200 + `{items, total, offset, limit}` |
| DELETE | `/api/v1/sessions/{session_id}` | 删除会话（两级：首次归档，已归档再删 = 真实删除） | Query: `?force=true` | 204（§2.5） |
| POST | `/api/v1/sessions/{session_id}/restore` | 恢复会话 | — | 200 + Session |

> 状态机端点（pause/resume/complete/fail）为**动作型**，均带落库副作用 → 一律 POST（同 F11/F13 动作端点约定）；非法迁移 → 422（InvalidSessionTransitionError）。

### 3.2 请求/响应示例 — 会话 CRUD

**创建写作会话**:
```http
POST /api/v1/sessions
Content-Type: application/json

{
  "session_type": "writing",
  "project_id": "3f2e1d4a-...",
  "title": "第三章续写",
  "description": "续写第三章，接上一章结尾",
  "context": {"chapter_id": "7b9c...", "mode": "continue", "style": "冷峻"}
}
```
→ 201
```json
{
  "session": {
    "id": "9b1c2d3e-...", "session_type": "writing", "status": "active",
    "project_id": "3f2e1d4a-...", "title": "第三章续写",
    "description": "续写第三章，接上一章结尾",
    "context": {"chapter_id": "7b9c...", "mode": "continue", "style": "冷峻"},
    "result": {}, "error": "", "started_at": "2026-08-07T10:00:00Z",
    "paused_at": null, "completed_at": null, "is_deleted": false,
    "created_at": "2026-08-07T10:00:00Z", "updated_at": "2026-08-07T10:00:00Z"
  },
  "log_count": 0,
  "last_log": null
}
```

**创建任务会话**（外部 agent 任务载体）:
```http
POST /api/v1/sessions
{
  "session_type": "task",
  "project_id": "3f2e1d4a-...",
  "title": "每日定时写作",
  "context": {"schedule": "daily", "target": 800, "chapter_range": "next"}
}
```

**会话详情（含履历摘要）**:
```http
GET /api/v1/sessions/9b1c2d3e-...
```
→ 200（SessionView；`log_count` 与 `last_log` 为履历摘要，日志全文走 `/logs`）

**列出会话（履历查询：按类型/状态/项目过滤 + 搜索 + 分页）**:
```http
GET /api/v1/sessions?session_type=task&status=completed&project_id=3f2e1d4a-...&search=每日&offset=0&limit=20
```
→ 200
```json
{
  "items": [
    {"session": {"id": "...", "session_type": "task", "status": "completed",
                 "title": "每日定时写作", ...}, "log_count": 5, "last_log": {...}}
  ],
  "total": 1, "offset": 0, "limit": 20
}
```

**更新会话（不承载 status——状态走动作端点）**:
```http
PATCH /api/v1/sessions/9b1c2d3e-...
{ "title": "第三章续写（改）", "context": {"mode": "revise", "style": "冷峻"} }
```
→ 200（更新后 Session；`context` 整体替换，未传字段不变）

**归档 / 解除归档 / 真实删除**:
```http
DELETE /api/v1/sessions/9b1c2d3e-...            → 204（第一次 = 归档）
POST /api/v1/sessions/9b1c2d3e-.../restore      → 200 + Session（解除归档）
DELETE /api/v1/sessions/9b1c2d3e-...            → 204（已归档 → 真实删除，日志级联）
DELETE /api/v1/sessions/9b1c2d3e-...?force=true → 204（活动会话直接真实删除）
```

### 3.3 请求/响应示例 — 状态机动作与日志

**暂停 / 恢复**:
```http
POST /api/v1/sessions/9b1c2d3e-.../pause
```
→ 200
```json
{"id": "9b1c2d3e-...", "status": "paused", "paused_at": "2026-08-07T11:00:00Z", ...}
```
```http
POST /api/v1/sessions/9b1c2d3e-.../resume
```
→ 200（`status: "active"`，`paused_at: null`）

**完成（携带结果快照）**:
```http
POST /api/v1/sessions/9b1c2d3e-.../complete
{ "result": {"words": 1280, "chapter_id": "7b9c...", "model": "deepseek-chat"} }
```
→ 200（`status: "completed"`，`completed_at` 已填，`result` 已写入）

**失败（携带错误原因）**:
```http
POST /api/v1/sessions/9b1c2d3e-.../fail
{ "error": "LLM 调用超时（连续 3 次重试失败）" }
```
→ 200（`status: "failed"`，`completed_at` 已填，`error` 已写入）

**追加日志（履历写入——外部 agent 进度通知契约，见 §5.4）**:
```http
POST /api/v1/sessions/9b1c2d3e-.../logs
{ "level": "info", "message": "开始写作章节 3", "payload": {"chapter_id": "7b9c...", "progress": 0.1} }
```
→ 201
```json
{"id": "a1b2...", "session_id": "9b1c2d3e-...", "seq": 1, "level": "info",
 "message": "开始写作章节 3", "payload": {"chapter_id": "7b9c...", "progress": 0.1},
 "created_at": "2026-08-07T10:00:01Z"}
```

**日志列表（按 seq 升序，分页）**:
```http
GET /api/v1/sessions/9b1c2d3e-.../logs?offset=0&limit=50
```
→ 200
```json
{
  "items": [
    {"id": "a1b2...", "session_id": "9b1c2d3e-...", "seq": 1, "level": "info",
     "message": "开始写作章节 3", "payload": {...}, "created_at": "..."},
    {"id": "c3d4...", "session_id": "9b1c2d3e-...", "seq": 2, "level": "warning",
     "message": "LLM 调用失败，重试第 2 次", "payload": {"attempt": 2}, "created_at": "..."}
  ],
  "total": 2, "offset": 0, "limit": 50
}
```

### 3.4 错误响应格式（沿用 F1/F2/F9/F10/F11/ADR-012）

| 错误类 | HTTP | detail 示例 |
|--------|------|-------------|
| SessionNotFoundError | 404 | `{"detail": "会话不存在"}` |
| ProjectNotFoundError（复用 F9 character_errors，见 §8.1） | 404 | `{"detail": "项目不存在"}`（创建时 project_id 校验） |
| SessionTransitionError（非法状态迁移） | 422 | `{"detail": "会话当前状态 completed 不允许 pause"}` |
| VALIDATION_ERROR（Pydantic 校验失败） | 422 | `{"detail": "会话标题不能为空"}` |
| DB_ERROR | 500 | `{"detail": "数据库错误"}` |

> 创建会话时若携带 `project_id`，校验项目存在（404，**前置校验先于创建**——同 F13 `_ensure_project` 模式）；`project_id=null` 不校验。终态会话（completed/failed）追加日志**允许**（履历补记，如外部 agent 写最终结果）——不设终态只读（见待澄清 Q2）。

---

## 4. CLI 命令签名

`inkflow session` 组（委托 SessionService；无子组——单父实体 + 日志子实体，同 F12 timeline 组布局）。CLI 全局约定沿用 F7 §5：JSON 信封 `{"ok", "data"/"error"}`、退出码 0/1/2/130、错误码 NOT_FOUND/VALIDATION_ERROR/DB_ERROR（**无 LLM_ERROR**——无 LLM 模块，同 F12）。

```bash
# 创建会话
inkflow session create --type task --project-id <id> --title "每日定时写作" [--description <text>] [--context-json '<json>']
#   长文本 context 用 --context-file <path>（JSON 文件；--context-json 与 --context-file 互斥，同 F9 双通道约定）

# 列出会话（履历查询）
inkflow session list [--type task] [--status completed] [--project-id <id>] [--search <kw>] [--limit 50] [--offset 0] [--json]

# 查看会话详情（含履历摘要 + 日志条数）
inkflow session get --id <session-id> [--json]

# 更新会话（标题/描述/上下文）
inkflow session update --id <session-id> [--title <text>] [--description <text>] [--context-json '<json>'] [--json]

# 状态机动作
inkflow session pause --id <session-id>
inkflow session resume --id <session-id>
inkflow session complete --id <session-id> [--result-json '<json>']
inkflow session fail --id <session-id> --error <text>

# 履历日志
inkflow session logs --id <session-id> [--limit 50] [--offset 0] [--json]
inkflow session log add --id <session-id> [--level info|warning|error] --message <text> [--payload-json '<json>']

# 删除/恢复（两级删除：首次 = 归档可恢复；已归档再删 = 真实删除；--force 直接真删）
inkflow session delete --id <session-id> [--force]
inkflow session restore --id <session-id>
```

### 4.1 输出格式

`--json` 时输出 F7 信封；非 JSON 时人性化文本（同 F12 §4.2）：

```bash
$ inkflow session list --type task --json
{"ok": true, "data": {"items": [...], "total": 3, "offset": 0, "limit": 50}}

$ inkflow session get --id 9b1c2d3e-...
会话: 每日定时写作 (task/active)
项目: 3f2e1d4a-...
开始: 2026-08-07T10:00:00Z | 日志: 5 条
上下文: {...}
```

---

## 5. 会话状态机与履历模式（关键差异：确定性状态追踪 + 履历日志）

### 5.1 模式总览

```
                 ┌─────────────────────────────────────────────┐
                 │  SessionService（CRUD + 状态机 + 日志追加）    │
                 │                                             │
  调用方          │  ① 创建: 类型/项目/标题/上下文快照 → active    │
 (CLI/F20/API)──▶│  ② 状态机: pause/resume/complete/fail        │
                 │  ③ 履历: 追加日志（进度/错误/结果）            │
                 │  ④ 恢复: resume + 上下文快照 → 续跑依据       │
                 └──────────────┬──────────────────────────────┘
                                │
                 ┌──────────────▼──────────────────────────────┐
                 │  SessionRepositoryProtocol（端口）            │
                 │  会话 CRUD + 日志追加/列表 + 状态更新          │
                 └──────────────┬──────────────────────────────┘
                                │
                 ┌──────────────▼──────────────────────────────┐
                 │  SQLiteSessionRepository（sessions/session_logs）│
                 └─────────────────────────────────────────────┘
```

### 5.2 状态机实现口径

- 状态迁移**单一入口**：Service 方法 `pause/resume/complete/fail` 内先校验当前状态合法（§2.4 迁移表），非法 → SessionTransitionError（422）
- **时间戳副产物**：pause 写 `paused_at`；resume 清 `paused_at`；complete/fail 写 `completed_at`（统一终态时间戳，不区分完成/失败时间字段——一个字段够用，YAGNI）
- **complete/fail 参数**：complete 携带 `result` 快照（写入 `result` 字段）；fail 携带 `error` 文本（写入 `error` 字段）；两者都在状态更新同一事务内落库（原子性，同 F9 单事务约定）
- **幂等性**：MVP **不承诺幂等**（重复 complete → 第二次 422 非法迁移）——与 F11「生成即新建」一致：动作语义是「迁移」而非「确保状态」，重复调用明确报错（调用方应查状态）。幂等重试由调用方（F20 MCP）实现（§10）

### 5.3 会话恢复语义

PRD P1-13「会话恢复」的落地：

- **写作会话（writing）**：`context` 快照携带恢复续写所需信息（章节 id / 模式 / 参数）；恢复 = `resume` 后消费方（F3 或未来 GUI）读取 `context` 重建写作输入。F24 自身**只存不解释**（轻量载体，深层语义由消费方约定）——恢复的实际写作动作归 F3/未来集成（§10）
- **任务会话（task）**：`context` 快照携带任务参数（目标/范围/LLM 配置）；外部 agent（F20 MCP）`resume` 后读取 context 续跑未完成任务。**这是 F20 依赖 F24 的核心契约**：外部 agent 调用的「暂停/恢复/进度」全部落在会话状态机 + 日志上
- 恢复的**进度连续性**：以日志 seq 为序查看已执行步骤（`GET /logs` 即任务履历），消费方据 `last_log`/`result` 决定续跑起点（外部 agent 的详细续跑算法由其自身定义，本模块只保证「日志可完整回溯」）

### 5.4 进度写入契约（外部 agent 消费预留）

外部 agent 进度通知按以下约定写入会话（本 spec 定义**契约形状**，F20 MCP / ADR-022 skills 实现遵守）：

| 事件 | level | message 模板 | payload 键（约定） |
|------|-------|-------------|-------------------|
| 任务开始 | info | `任务开始：<摘要>` | `progress: 0.0` |
| 每章节完成 | info | `完成章节 <N>：<标题>（<字数> 字）` | `chapter_id`, `words`, `progress: 0.x` |
| LLM 重试 | warning | `LLM 调用失败，重试第 <N> 次` | `attempt`, `error` |
| 任务完成 | info | `任务完成：共 <N> 章 <M> 字` | `progress: 1.0`, `summary` |
| 任务失败 | error | `任务失败：<原因>` | `error` |

> 进度写入与状态机**独立**：日志可在任何状态追加（含终态，Q2 拍板）；`fail` 动作与 error 日志二选一由调用方决定（fail 写 `error` 字段 + 可选日志），不强制双写。

### 5.4b 可观测键约定（agent 运行可视化铺路，Q3 拍板 2026-08-07）

为「用户查看当前哪个 agent 在工作 + 点击查看运行细节（工具/skill 调用）」预留**软关联**——日志 payload 可携带以下**可选**键（契约形状由 F24 定义，明细由 0.7.0 Agent 化升级 F27/F28 填充）：

| 键 | 类型 | 含义 | 例子 |
|----|------|------|------|
| `execution_id` | str | 对应一次底层执行记录（0.7.0 起可反查 agent_run/agent_executions 明细） | `"8f3c..."` |
| `agent_name` | str | 当前执行的 agent/管线名 | `"builtin:write_chapter"` |
| `stage` | str | 执行阶段（对应用户可见的「跑到哪一步」） | `"outline"` / `"chapter_write"` / `"style_review"` |
| `tool_calls` | list[dict] | 该步骤的工具/skill 调用快照（0.7.0 F26 工具化后填充） | `[{"tool": "search_characters", "args": {...}}]` |
| `duration_ms` | int | 该步骤耗时 | `12500` |

**规则**：
- 键**全部可选**——外部 agent 调用先填 `execution_id`/`agent_name`/`stage`/`duration_ms`（§5.4 表已含的键优先），`tool_calls` 留空（F26 工具化后才可能填充）
- 软关联 = 字符串键约定，**无 FK 约束**：F24 不读不写 F4/agent_run 表（§1.2 边界），0.7.0 加正式关联时零迁移
- 「当前哪个 agent 在工作」= 会话 status=active + `GET /sessions` 列表 `last_log.payload.agent_name`；「执行到哪一步」= `GET /sessions/{id}/logs` 的 seq 时间线（每条日志即一步）

### 5.5 会话履历 vs 提取/生成/状态机：差异对照表

| 维度 | F12 时间线（无 AI） | F13 伏笔（状态机） | **F24 会话（履历型）** |
|------|-------------------|-------------------|----------------------|
| 实体 | 单实体 | 单实体 + 状态机 | **双实体（父+日志子）** |
| 状态机 | 无 | 两态 open/resolved | **四态 active/paused/completed/failed** |
| 动作端点 | check（只读） | resolve/reopen | **pause/resume/complete/fail（全部带副作用）** |
| 子实体 | 无 | 无 | **SessionLogEntry（追加语义、seq 递增、不可篡改）** |
| 引擎 | 相邻对扫描 | 状态迁移 + 注入 | **状态迁移 + 履历日志 + 上下文快照** |
| 幂等性 | GET 天然幂等 | 动作重复 → 422 | **动作重复 → 422（显式声明）** |
| 唯一约束 | 无 | partial unique (project_id, title) | **无（实例语义，同 F12）** |
| LLM/模板 | 无 | 无 | **无** |
| 测试方式 | 构造序列 + 快照 | 状态迁移矩阵 | **状态迁移矩阵 + 日志 seq 连续性 + 上下文快照断言** |

---

## 6. 会话组织规则

### 6.1 会话归属

- 会话是**全局资源**（不属于任何项目的顶层实体，`project_id` 可空）：任务履历跨项目查询（`GET /sessions` 无项目过滤即全量）；`project_id` 仅作业务过滤维度，不构成资源嵌套路径（与 F12 项目级事件、F13 项目级伏笔不同——会话的生命周期独立于项目：项目删除不级联删会话，FK `ON DELETE SET NULL` 保留履历）
- 项目硬删除 → 会话 `project_id` 置 NULL（履历保留、降级为全局会话）；会话硬删除 → 日志级联删除

### 6.2 列表排序

会话列表默认按 `created_at DESC`（最新在前——履历查询关注最近任务）；`last_log` 为子查询聚合（会话详情与列表项同构）。日志列表按 `seq ASC`（履历顺序，不可配置——seq 即履历序号）。

### 6.3 搜索与分页（沿用 F1 §6/F9 §6.3/F10 §6.2/F11 §6.3）

- `search` 模糊匹配 `title`（LIKE 包含，大小写不敏感；不匹配 description——标题是履历检索主键）
- 过滤组合：`session_type` + `status` + `project_id` 可任意组合，全缺省 = 全量未归档会话（is_deleted=0）
- 分页 `offset`/`limit`，`limit` 默认 50、上限 200（同 F1）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| 1 | 创建会话携带不存在的 project_id | 404 ProjectNotFoundError（前置校验先于创建，同 F13 `_ensure_project`） |
| 2 | `project_id=null` 创建 | 允许（全局会话，无校验） |
| 3 | 对 completed/failed 会话调用 pause/resume/complete/fail | 422 SessionTransitionError（终态不可迁移） |
| 4 | 对 paused 会话调用 pause / 对 active 会话调用 resume | 422 SessionTransitionError（非法迁移） |
| 5 | 对不存在的会话调用任意动作/日志端点 | 404 SessionNotFoundError |
| 6 | 对归档会话调用状态机动作/追加日志 | 404 SessionNotFoundError（归档会话不可操作，同 F12 软删事件语义） |
| 7 | 对归档会话调用 GET /sessions/{id}（详情） | 200（详情可追溯；列表不显示——同 F12 软删事件「详情可读、列表不可见」） |
| 8 | 对归档会话调用 GET /logs | 404（子资源跟随父归档不可查询） |
| 8b | 对**已归档**会话再次 DELETE | 204 真实删除（物理删除 + 日志级联，不可恢复） |
| 9 | 追加日志到 completed/failed 会话 | 允许（履历补记；调用方负责语义） |
| 10 | `SessionUpdate` 携带 `status` 字段 | Pydantic `extra='ignore'`（v2 默认）→ 静默忽略，**status 不变**（不报错——F13 v1.1 教训：断言「被忽略」而非「422」） |
| 11 | `SessionUpdate` 全字段缺省（空 body `{}`） | 200 无变化（合法；不强制至少一个字段——同 F12 update 语义） |
| 12 | 日志 message 空白/超长 | 422（Pydantic validator） |
| 13 | 日志 `seq` 冲突（并发追加） | DB_ERROR 500（MVP 不处理并发日志追加——外部 agent 单任务串行写日志，见 §10；幂等重试由调用方实现） |
| 14 | 大 context/result JSON | 允许（SQLite JSON 列，无独立大小限制；调用方控制体积，外部 agent 约定 ≤ 64KB） |
| 15 | 真实删除（已归档再 DELETE / force=true） | 204 + 日志级联物理删除（不可恢复） |

---

## 8. 文件结构

遵循 ADR-007v2 包结构，与 F12/F13 真实源码树一一对应。新增/修改文件：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── session.py               ← CREATE: Session, SessionCreate, SessionUpdate,
│   │   │                                SessionLogEntry, SessionLogCreate,
│   │   │                                SessionComplete, SessionFail, SessionView,
│   │   │                                SessionType, SessionStatus, LogLevel + 校验器
│   │   └── __init__.py              ← MODIFY: 导出新模型
│   ├── ports/
│   │   ├── session_repository.py    ← CREATE: SessionRepositoryProtocol
│   │   ├── session_errors.py        ← CREATE: SessionServiceError / SessionNotFoundError /
│   │   │                                SessionTransitionError（不含 ProjectNotFoundError——
│   │   │                                复用 F9 character_errors，见下方说明）
│   │   └── __init__.py              ← MODIFY: 导出（仅本模块独有类名，同 F13 陷阱 16）
│   └── services/
│       ├── session_service.py       ← CREATE: SessionService（CRUD + 状态机 + 日志追加 + 视图）
│       └── __init__.py              ← MODIFY
├── infrastructure/
│   └── database/
│       ├── models/
│       │   ├── session.py           ← CREATE: SessionORM（索引: project_id / status /
│       │   │                            session_type / is_deleted）+ SessionLogORM
│       │   │                            （索引: session_id + (session_id, seq) 唯一约束）
│       │   └── __init__.py          ← MODIFY: 注册 ORM（create_tables 依赖）
│       └── repositories/
│           ├── session_repo.py      ← CREATE: SQLiteSessionRepository
│           └── __init__.py          ← MODIFY
├── api/
│   ├── routers/
│   │   ├── sessions.py              ← CREATE: 12 个端点（会话 CRUD + 状态机 + 日志）
│   │   └── __init__.py              ← MODIFY
│   ├── deps.py                      ← MODIFY: get_session_service
│   └── app.py                       ← MODIFY: 注册 sessions.router
└── cli/
    ├── commands/
    │   ├── session.py               ← CREATE: session 组（create/list/get/update/pause/
    │   │                                resume/complete/fail/logs/log add/delete/restore）
    │   └── __init__.py              ← MODIFY
    └── app.py                       ← MODIFY: 注册 session 命令组

backend/tests/
├── unit/
│   ├── test_session_models.py       ← CREATE: 领域模型/DTO 校验（类型/状态/标题/日志/错误）
│   ├── test_session_repo.py         ← CREATE: 仓储集成测试（in-memory SQLite，含索引/级联/软删）
│   ├── test_session_service.py      ← CREATE: 服务测试（CRUD + 状态机 + 日志 seq + 视图聚合）
│   ├── test_session_api.py          ← CREATE: API 集成测试（Mock Service，12 端点 + 错误路径）
│   └── test_session_cli.py          ← CREATE: CLI 测试（Mock SessionService，信封/退出码）
└── tests/cli/
    └── test_cli_session.py          ← CREATE: CLI 测试（同 F12/F13 惯例；⚠️ 必须显式追加
                                         ci.yml integration-cli-backend job 文件列表——Issue #59 盲区）
```

> **与 F12/F13 §8 的差异**：无 `infrastructure/llm/templates/` 目录（无 LLM，同 F12/F13）；**多一个日志子实体文件**（SessionLogORM + SessionLogEntry 模型）；无跨模块 MODIFY（纯新增）。

### 8.1 错误类与端口说明

```python
# domain/ports/session_errors.py —— 只定义本模块独有错误类
class SessionServiceError(Exception):
    """会话服务错误基类（422 语义）."""

class SessionNotFoundError(Exception):
    """会话不存在（404 语义，不继承基类——同 F12/F13 惯例）."""

class SessionTransitionError(SessionServiceError):
    """非法状态迁移（422）."""
```

> **ProjectNotFoundError 不导出到 ports/__init__.py**（F13 陷阱 16 教训）：创建会话的项目存在性校验复用 F9 `character_errors.ProjectNotFoundError`（已有全局导出），避免同名遮蔽破坏既有 router 的 except 链。sessions router 的异常处理同时 `except` F9 版 ProjectNotFoundError 与本模块 SessionNotFoundError/SessionTransitionError。

### 8.2 SessionRepositoryProtocol（参照 F13 `foreshadowing_repository.py` Protocol 风格）

```python
class SessionRepositoryProtocol(Protocol):
    """会话仓储端口.

    按 spec §2: 双实体（Session + SessionLogEntry）；会话列表按
    created_at DESC；日志按 seq ASC；归档会话不进入列表查询。
    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9-F13）。
    """

    # ── Session ──
    async def add(self, session: Session) -> Session: ...
    async def get(self, session_id: int) -> Session | None: ...
    async def list(self, session_type: str | None = None,
                   status: str | None = None,
                   project_id: int | None = None,
                   search: str | None = None,
                   offset: int = 0, limit: int = 50) -> tuple[builtins.list[Session], int]: ...
    async def list_include_deleted(self, session_id: int) -> Session | None: ...  # 详情可追溯（归档也可读）
    async def update(self, session: Session) -> Session: ...
    async def soft_delete(self, session_id: int) -> bool: ...
    async def restore(self, session_id: int) -> Session | None: ...
    async def hard_delete(self, session_id: int) -> bool: ...

    # ── SessionLogEntry ──
    async def add_log(self, entry: SessionLogEntry) -> SessionLogEntry: ...
    async def next_seq(self, session_id: int) -> int: ...        # 会话内 max(seq)+1（无日志时 = 1）
    async def list_logs(self, session_id: int, offset: int = 0,
                        limit: int = 50) -> tuple[builtins.list[SessionLogEntry], int]: ...
    async def count_logs(self, session_id: int) -> int: ...      # SessionView.log_count
    async def last_log(self, session_id: int) -> SessionLogEntry | None: ...  # SessionView.last_log
```

> 仓储层方法入参用 int（与 F9-F13 RepositoryProtocol 一致）；Service 负责 UUID ↔ int 转换（沿用 F1 `_to_int_id` 模式）。`next_seq` 在 `add_log` 前调用（seq 由服务层分配）。`list_include_deleted` 供详情端点使用（软删会话详情可追溯，§7 #7）。

---

## 9. 测试策略

### 测试层次（沿用 ADR-018 三层目录 + pytest markers；六层结构同 F9-F13 §9）

```text
单元测试: 领域模型/DTO 验证（类型/状态枚举/标题/消息/错误校验）   ~12 cases
集成测试: SQLiteSessionRepository（in-memory SQLite，含索引/级联/软删/seq）  ~16 cases
服务测试: SessionService（CRUD + 状态机 + 日志 seq + 视图聚合）   ~14 cases
状态机:   迁移矩阵专项（4 状态 × 4 动作全组合 + 时间戳副产物）    ~12 cases
API 测试: 12 端点（Mock Service，含 404/422 全路径）            ~14 cases
CLI 测试: session 组（Mock SessionService，信封/退出码）         ~12 cases
```

### 关键测试场景

1. **状态机全矩阵**：每个 (状态, 动作) 组合的合法性断言——active×{pause,complete,fail}=✅、paused×{resume,complete,fail}=✅、completed/failed×{任意}=❌ 422、paused×{pause}/active×{resume}=❌ 422
2. **时间戳副产物**：pause 写 paused_at、resume 清 paused_at、complete/fail 写 completed_at（快照断言）
3. **日志 seq 连续性**：连续追加 3 条 → seq=1,2,3；删除中间日志不可行（无删除端点）；并发 seq 冲突 → 500
4. **归档/真实删除语义**：第一次 DELETE 归档后列表不含、详情可读、logs 404、restore 解除；**已归档再 DELETE → 物理删除**（查 session_logs 表行数验证级联）；force=true 对活动会话直接真删
5. **视图聚合**：SessionView.log_count / last_log 正确（0 日志 → last_log=null）
6. **跨模块错误复用**：sessions router except F9 ProjectNotFoundError（创建时项目不存在 → 404 而非 500）
7. **CLI 信封**：成功/失败/校验错误信封形状 + 退出码（0/1/2）

### 覆盖率目标

模块行覆盖 ≥ 80%、全仓 ≥ 60%（0.2.0 DoD 基准）；**当前全仓门禁为 ADR-027：后端 98.5/95.0**——F24 新增代码必须同步补测维持门槛（QA 阶段主 agent 全仓跑 `uv run ruff check src/ tests/unit/ ../tests/` + `pytest` + `check_coverage.py 98.5 95.0`）。

---

## 10. 不在范围内

| 项 | 原因 | Phase 归属 |
|----|------|-----------|
| 写作恢复的实际续写动作 | F24 只存上下文快照不执行写作（§5.3）——写作管道是 F3 职责 | F3/未来 GUI 集成（0.5.0+） |
| 任务执行/调度（定时器/进程生命周期） | 任务执行是外部 agent（F20 MCP / ADR-022 skills）职责（本模块只提供会话载体）；定时调度已随 F25 移除（ADR-029） | F20（1.0.0）/外部 agent |
| 幂等重试 / 断点续跑算法 | 会话保证「日志可回溯」，续跑决策由消费方（F20 MCP）实现 | F20（1.0.0） |
| 与 F4 AgentExecution / agent_run 的**正式 FK 关联** | MVP 用 payload 软关联（§5.4b 可观测键）已覆盖「查看运行细节」；正式 FK 等 0.7.0 执行记录表形态确定后加（届时零迁移） | 0.7.0（Agent 化升级） |
| agent 运行可视化（CI/CD 式执行视图：当前 agent/阶段/工具调用明细） | 可观测性功能，承载 = F24 日志时间线 + payload 可观测键（§5.4b）；完整 GUI 视图归 Agent 化升级（F27/F28） | 0.7.0（Agent 化升级） |
| 会话类型强类型子类（writing/task 分表/继承模型） | §2.3 论证：单表 + JSON 快照足够（类型仅决定行为） | 永不（除非类型行为分化到无法共存） |
| 日志更新/删除端点 | 履历不可篡改（追加语义）——删除日志违背审计意图 | 永不 |
| 会话 reopen（终态复活） | 重跑 = 新建会话（YAGNI，F13 dropped 态同构论证） | 永不 |
| GUI 会话管理页 | 本模块交付 CLI/API；GUI 归后续前端里程碑 | 0.6.0+ 前端演进 |
| 会话归档后子资源联动隐藏 | 履历可追溯语义（§2.5）：日志跟随会话可见性，不单独联动 | 永不 |
| 通知/推送（桌面通知、系统托盘） | 进度通知 = 会话日志（§5.4）；系统级推送归 GUI/未来（F25 已移除，ADR-029） | GUI/未来 |

---

## 11. 依赖关系

```text
F24 依赖:
  F1（project_service）   — project_id 存在性校验 + ProjectORM FK（ON DELETE SET NULL）
  F9（character_errors）  — ProjectNotFoundError 复用（ports 导出，陷阱 16 防护）
  F7（CLI 约定）          — JSON 信封/退出码/错误码标准

F24 被依赖:
  F20（MCP Server）      — 任务会话载体 + 履历日志 + 暂停/恢复状态机（外部 agent 调用，2026-08-07 用户拍板；原 F25 daemon 载体已移除，ADR-029）
  F26+（Agent 化）        — agent 任务履历可复用会话（未来）
```

**编号口径声明**：PRD v2.1 §6.2 中 F8-F17 一行式引用 v2.0 原文，「会话管理」在 v2.0 编号为 F16（旧）；现行编号以 ADR-019 v5 为准：F24 = 会话管理、F25 = daemon（已移除不复用，ADR-029；旧文档中指向会话管理的「F16」编号已过时）。Issue #51 body 中 `specs/ff24-<name>/spec.md` 为双 f 笔误（F14 先例同款），实际目录 `specs/f24-session-service/`。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|-------------|
| 1 | 会话类型用字段而非子类 | `session_type: writing/task` + 统一 context/result JSON 快照 | 轻量载体（§2.3）；深层语义由消费方约定，避免双套 CRUD/状态机 | writing/task 分表（复杂度翻倍，无收益）；纯 JSON 无类型（无法区分行为） |
| 2 | 状态机四态 + 动作端点 | active/paused/completed/failed，pause/resume/complete/fail 专用端点 | 任务履历需要暂停/恢复语义（外部 agent 调用依赖）；迁移规则单一入口可校验（F13 模式） | PATCH 直改 status（任意跳转无法校验，F13 否决同款）；两态 open/closed（无暂停语义，不满足 PRD「暂停恢复」） |
| 3 | 双实体（Session + SessionLogEntry） | 日志子实体追加语义、seq 递增、不可篡改 | 「任务履历日志」是用户拍板的核心诉求（§1.3）；日志与状态机独立（终态也可补记）；履历查询 = GET /logs | 单实体 + JSON 日志数组（不可分页/不可独立追加校验）；无日志（不满足履历诉求） |
| 4 | 会话是全局资源（project_id 可空） | 顶层资源 + 项目过滤维度，FK SET NULL | 任务履历跨项目（全局定时任务）；项目删除保留履历 | 项目嵌套资源（履历随项目生命周期，删除即失）；强制 project_id（无法表达全局任务） |
| 5 | 终态不可 reopen | completed/failed 终态，重跑 = 新建会话 | 状态机简单可证；重跑语义 = 新会话 + 新履历（旧履历保留对照） | reopen 动作（终态复活 → 履历时序混乱，F13 dropped 态 YAGNI 同构论证） |
| 6 | 归档 → 真实删除两级 + 详情可追溯（用户拍板 2026-08-07） | 第一次 DELETE 归档（可 restore 解除）、已归档再 DELETE 真实删除、force 直删 | 产品语义「归档可解除、归档且删除 = 真删」（用户拍板）；履历可追溯是会话模块特性；与 F12/F13 软删事件兼容（底层 is_deleted 不变） | 硬删默认（误删不可恢复）；软删后详情也 404（无法追溯历史履历） |
| 7 | ProjectNotFoundError 复用 F9 | 不导出同名类（陷阱 16） | 避免 ports 遮蔽破坏既有 router except 链 | 自建 ProjectNotFoundError 并导出（F13 实测教训） |
| 8 | 动作不承诺幂等 | 重复 complete → 422 | 动作语义 = 迁移（非确保状态），重复调用明确报错；幂等重试由调用方（F20 MCP）实现 | complete 幂等（第二次返回已 completed——掩盖调用方状态盲区） |
| 9 | 会话↔执行：MVP 软关联，不加 FK（Q3 拍板 2026-08-07） | SessionLog.payload 可观测键（execution_id/agent_name/stage/tool_calls/duration_ms，§5.4b） | 用户需求「查看 agent 运行细节」（2026-08-07）：日志即时间线 + payload 即下钻入口；F4/agent_run 表 0.7.0 可能演进，FK 过早绑定有重构风险 | Session.execution_id FK（依赖 F4 表结构，0.7.0 重构风险）；SessionLog.execution_id FK（同左） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 领域模型 + DTO 验证（类型/状态枚举/标题/消息/错误校验/视图模型） | `pytest tests/unit/test_session_models.py -v` 全绿 |
| M2 | 仓储层全部方法（双实体 CRUD + 过滤列表 + seq 分配 + 归档/解除/真实删除/级联 + 视图聚合） | `pytest tests/unit/test_session_repo.py -v` 全绿 |
| M3 | 服务层 CRUD + 业务校验（项目存在性/更新忽略 status/404 全路径） | `pytest tests/unit/test_session_service.py -v` 全绿 |
| M4 | 状态机迁移矩阵（4 状态 × 4 动作全组合 + 时间戳副产物 + 终态不可逆） | `pytest tests/unit/test_session_service.py -v`（状态机专项组）全绿 |
| M5 | API 12 端点 + 错误路径全绿（404/422/跨模块错误复用） | `pytest tests/unit/test_session_api.py -v` 全绿 |
| M6 | CLI session 组（信封/退出码/状态机命令/日志命令） | `pytest ../tests/cli/test_cli_session.py -v` 全绿（且已追加 ci.yml integration-cli-backend job） |
| M7 | 手工验证：建任务会话 → 暂停 → 恢复 → 追加进度日志 → 完成 → 履历查询闭环 | 手工验证（`inkflow session create` → `pause` → `resume` → `log add` ×2 → `complete` → `logs` 看 seq 1..n 履历完整） |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest` 全绿；覆盖率达 ADR-027 门槛（98.5/95.0）；`uv run ruff check src/ tests/unit/ ../tests/` + mypy 通过；domain/ 零框架 import（ADR-002/015） |

> Issue #51 验收标准映射：PRD「会话持久化」= M1/M2（实体+仓储）、「多会话管理」= M3/M5/M6（列表过滤+CRUD）、「会话恢复」= M4/M7（状态机 resume + 上下文快照）。

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 结论 |
|---|------|------|------|
| Q1 | 会话是否**必须**挂项目？ | 数据模型约束与 API 校验（§2.1/§3.2） | ✅ 已确认（用户拍板 2026-08-07：按设计）——`project_id` **可空**；三类场景支撑（程序内 chat AI 辅助任务、跨项目/全局外部 agent 任务、项目删除后履历保留），详见正文 §2.1/§6.1 |
| Q2 | 终态会话（completed/failed）是否允许**追加日志**？ | 状态机与日志语义（§2.4/§5.4/§7 #9） | ✅ 已确认（用户拍板 2026-08-07：按设计）——**允许追加**（履历补记优先；「终态冻结」反直觉：调用方被迫在 complete 前塞完日志） |
| Q3 | 会话与 F4 AgentExecution 是否 MVP 建立关联？ | 数据模型字段与外部 agent 消费方式（§2.1/§5.4b） | ✅ 已确认（用户拍板 2026-08-07：**MVP 软关联，不加 FK**）——SessionLog.payload 可观测键（execution_id/agent_name/stage/tool_calls/duration_ms，§5.4b）承载「查看当前 agent 运行/执行到哪一步/工具调用细节」；正式 FK 与 CI/CD 式执行视图归 0.7.0 Agent 化升级（F27/F28），届时零迁移 |

---

*本文档为 F24 功能规格（What），实施步骤（How）见后续 `specs/f24-session-service/plan.md`。所有里程碑验收以本节 M1-M8 为准。*
