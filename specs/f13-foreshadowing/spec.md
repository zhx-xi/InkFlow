# F13: 伏笔管理 (foreshadowing_service) — 功能规格
> **端**: backend

> **Spec 版本**: 1.1 | **日期**: 2026-08-01 | **依据**: PRD v2.1 §6.2 P1-05, Constitution P1-P6, ADR-019
> **Spec 变更**: v1.1 — 用户拍板 Q1=选项 C：伏笔绑定 F12 时间线事件（event_id 锚点）；移除独立 narrative_position；F12 升级为硬依赖（须先合入 main）；详见 §2.2/§11/§12
> **所属阶段**: Phase 2 — 创作工具链（0.2.0 里程碑第五个模块，估算 2-3 人天）
> **关联 Issues**: [#43](https://github.com/zhx-xi/InkFlow/issues/43)
> **依赖**: F1 ✅（前置）；F6 ✅（上下文注入契约，ForeshadowingSource 替换，见 §5/§11）；F12 ✅（硬依赖：event_id 事件锚点，timeline_events 表 + TimelineRepositoryProtocol 事件校验，**F12 须先合入 main**，见 §11）；F2（边界声明，非硬依赖，见 §11）；F5 — **不依赖**（F13 无 LLM，见 §1/§5）
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md) (模块化单体), [ADR-002](../../adr/ADR-002.md) (六边形分层), [ADR-003](../../adr/ADR-003.md) (Repository), [ADR-004](../../adr/ADR-004.md) (Pydantic v2), [ADR-007v2](../../adr/ADR-007v2.md) (包结构), [ADR-010](../../adr/ADR-010.md) (上下文分层), [ADR-012](../../adr/ADR-012.md) (错误处理), [ADR-016](../../adr/ADR-016.md) (loguru), [ADR-017](../../adr/ADR-017.md) (CI 门禁), [ADR-018](../../adr/ADR-018.md) (测试分层), [ADR-019](../../adr/ADR-019.md) (版本里程碑)
> **状态**: ✅ 已实现（PR #64）

>
> **快速导航**（2026-08-08 #201）：
> [1. 概述](L13) · [2. 数据模型](L39) · [3. API 契约](L287) · [4. CLI 命令签名](L470)
> [5. 伏笔状态机与注入模式（关键差异：确定性状态追踪 + F6 数据源替换）](L530) · [6. 伏笔组织规则](L673) · [7. 边界情况与错误处理](L707) · [8. 文件结构](L746)
> [9. 测试策略](L859) · [10. 不在范围内](L895) · [11. 依赖关系](L916) · [12. 关键架构决策记录](L957)
> [13. 验收标准](L981) · [待澄清问题（≤ 3 个，评审时确认）](L996)
---

## 1. 概述

管理小说的**伏笔档案**（创建/查询/更新/软删除），跟踪每条伏笔的**生命周期状态**（open 已埋设未回收 → resolved 已回收），并作为 **F6 上下文注入的真实数据源**：写作时把「未回收伏笔」按优先级注入写作 Prompt，提醒作者不要忘记兑现埋下的伏笔（验收标准 2「写作时注入伏笔提示」）。

**核心价值**: 作者与 AI Agent 可以维护「埋了什么伏笔、是否已回收」的结构化档案；写作时 F3/F6 组装上下文自动注入未解决伏笔提醒，避免「埋了不回收」的长篇一致性硬伤；为 F15 审计（伏笔维度一致性）、F16 一致性审计提供数据基础。

**与 F9/F10/F11/F12 样板的关系（关键差异）**: F9/F10 沉淀「**实体 + AI 提取**」模式，F11 演进为「**实体 + AI 生成**」，F12 演进为「**实体 + 确定性一致性检查**（无 LLM）」；F13 是 0.2.0 创作工具链**第五个**应用该骨架的模块，增值能力拆为两块——**确定性状态追踪**（同 F12 无 LLM）与 **F6 上下文注入集成**（这是 F12 没有的、F13 独有的第二增值点）：

```text
F9/F10 提取:  章节文本(text) ──LLM──▶ 结构化实体 ──合并落库──▶ 实体档案
F11  生成:    项目设定/约束(prompt) ──LLM──▶ 结构化大纲 ──新建落库──▶ 大纲规划
F12  检查:    事件档案(双时间维度) ──确定性算法──▶ 双线视图 + 冲突报告
F13  追踪:    伏笔档案(状态机) ──确定性追踪──▶ 状态流转
      + 注入:  伏笔档案(open) ──ForeshadowingSource──▶ ContextItem ──F6 dynamic 层──▶ 写作 Prompt
```

**复用** F9/F10/F11/F12 的骨架部分：实体模型（domain/models）→ CRUD Port（domain/ports）→ Repository（infrastructure）→ Service（domain/services）→ API Router + CLI（薄层）。**不同**的部分：无 LLM 模板/解析/重试管线（无 `infrastructure/llm/templates/` 目录）；§5 从 F12 的「一致性检查算法」变为「**状态机 + F6 注入模式**」（ForeshadowingSource 从空实现替换为真实数据源——**F13 是首个自带 F6 数据源替换的 Phase 2 模块**，与 F9/F10 的「只交付实体、替换归联调」不同，理由见 §12 决策表与待澄清 Q2）。

**边界声明**:
- F13 不做**伏笔 AI 提取 / 回收自动检测**：章节文本 → 伏笔埋设、正文 → 伏笔兑现的自动识别归 **F14 统一提取服务**（P1-06，Issue #44），见 §10
- F13 不做**跨模块全维度一致性审计**（角色/世界观/时间线/伏笔联动审计）：归 **F15 审计服务**（P1-07，Issue 待创建），见 §10
- F13 不做**伏笔-F2 章节强绑定**：埋设位置用自由文本 `location` 表达，不绑定 F2 卷/章（同 F11/F12 边界声明）；**伏笔绑定 F12 时间线事件（event_id 锚点）已纳入 MVP**（用户拍板 Q1=选项 C，见 §2.2/§11）
- F13 的**注入范围**：全部未回收（open）伏笔，按 priority 降序进入 F6 dynamic 层，由预算层按 token 裁剪（论证见 §5.4/§12）

---

## 2. 数据模型

遵循 F1 Project 的「领域 Pydantic 实体 + 请求/更新 DTO + ORM 双模型」模式（ADR-004）。领域层 id 为 UUID，数据库 int 自增映射（同 F1 §12）。

### 2.1 Foreshadowing（伏笔档案）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 领域层 UUID，DB int 自增映射 |
| project_id | UUID | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目 |
| title | str | NOT NULL, 1-100 字符, 去空白 | 伏笔名（如「林晚的身世」「铜镜的秘密」）；**项目内活动伏笔唯一**（partial unique，见 §2.3） |
| description | str | NOT NULL, DEFAULT "", ≤ 5000 字符 | 伏笔详情（埋设内容、预期回收方式） |
| priority | int | NOT NULL, DEFAULT 50, 0-100, 已索引 | **注入优先级**（大者先注入；F6 dynamic 层排序契约的键，见 §5.4/§6.2） |
| status | str | NOT NULL, DEFAULT "open", 已索引 | 伏笔状态（`open` / `resolved`，见 §2.4 状态机） |
| location | str | NOT NULL, DEFAULT "", ≤ 200 字符, 去空白 | 埋设位置描述（自由文本，如「第 3 章·林晚出场段落」「青云城初见」）；空 = 未记录；不挂事件时作者仍可写「第 3 章」 |
| event_id | UUID? | NULLABLE, FK→timeline_events.id (ON DELETE SET NULL), 已索引 | **时间线事件锚点**（F12 事件，埋设落点；事件自带 time_value/narrative_position，伏笔的叙事位置从事件获取——移除独立 narrative_position 字段避免双份真相，见 §2.2）；None = 未挂接 |
| resolved_at | datetime? | NULLABLE, 已索引 | 回收时间 (UTC)；status=resolved 时由服务层自动设置，reopen 时清空 |
| extra | dict[str, Any] | NOT NULL, DEFAULT {} | 扩展字典（标签、关联角色名等 Phase 2+ 字段预留） |
| is_deleted | bool | NOT NULL, DEFAULT False, 已索引 | 软删除标记 |
| created_at | datetime | NOT NULL, AUTO | 创建时间 (UTC) |
| updated_at | datetime | NOT NULL, AUTO | 更新时间 (UTC) |

**业务规则**:
- `title` 项目内**活动伏笔唯一** = 「同名 = 同一伏笔」——伏笔是**档案**而非实例（见 §2.3 论证）；防止手误重复建档
- `status` **不允许通过 PATCH 直接修改**：状态迁移走专用动作端点（`resolve` / `reopen`，见 §3/§2.4），保证迁移规则单一入口、可校验
- `priority` 是作者维护的**自由整数**（0-100），建议值仅提示不校验（受控词表归 F14，同 F9 relation_type / F10 category 处理）
- `resolved_at` 只由状态迁移维护（resolve 设置 / reopen 清空），**不接受外部写入**
- 软删除的伏笔**不进入**注入集合与列表（默认过滤）
- 回收说明（在哪回收、如何兑现）MVP 写进 `description` 更新或 `extra`，不设独立字段（见待澄清 Q3）
- `event_id` 非 None 时（创建/更新）：事件必须**存在且属于同一项目**——经 F12 `TimelineRepositoryProtocol.get` 校验（F12 语义：get **不含软删事件**，故软删事件不可挂接 → 422「事件不存在」）；`event.project_id != 伏笔.project_id` → 422「事件不属于该项目」（§3.4）
- `event_id` **不唯一**：一个事件可挂多条伏笔（无 unique 约束，仅索引）
- 事件**软删**（F12 语义：记录保留、不进入视图）**不影响**已挂接伏笔的 `event_id`：锚点保留，注入 metadata 原样携带（§5.3）；事件**硬删**（force）→ FK ON DELETE SET NULL 自动置 None（挂接解除，论证见 §12）

### 2.2 埋设/回收位置表达（决策：自由文本 location + event_id 事件锚点）

> **v1.1 变更（用户拍板 Q1=选项 C）**: 伏笔绑定 F12 时间线事件（event_id 锚点）；**移除独立 `narrative_position` 字段**——F12 事件本身携带 `time_value` / `narrative_position`（F12 spec §2.1），伏笔挂事件后叙事位置从事件获取；独立字段会造成「伏笔位置序号」与「事件叙事位置」双份真相（改事件叙事位置时伏笔侧不同步漂移）。

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **自由文本 location + event_id 事件锚点（选定）** | 伏笔落点与 F12 时间线联动（叙事位置/世界内时间从事件获取，单一真相）；location 保留作者自由描述（不挂事件时仍可写「第 3 章」）；事件软删不影响锚点（§2.1） | F12 为硬依赖（须先合入 main，§11）；挂接需事件存在性 + 同项目校验（复用 F12 `TimelineRepositoryProtocol.get`，F13 仓储无新增方法，§8.1） | ✅ MVP（用户拍板 Q1=选项 C） |
| 自由文本 location + 独立 narrative_position（v1.0 设计） | 零跨模块依赖；narrative_position 提供可排序锚点 | **双份真相**：F12 事件已带 narrative_position，独立字段与之漂移（改事件叙事位置 ≠ 伏笔侧）；v1.0 时「F12 未合入 main」是临时约束，现已解除 | ❌ 移除（冗余字段，YAGNI；叙事位置统一从事件获取） |
| 绑定 F2 章节（chapter_id FK） | 位置精确到章，可「按当前章节过滤未回收伏笔」 | 需 F2 跨模块硬依赖与章节存在性校验；章节重排/删除时锚点失效需级联处理 | ❌ 否决（F11/F12 边界声明先例：规划层与章节层互不绑定；按章节过滤注入归 Phase 2+，见待澄清 Q3） |

### 2.3 唯一约束（partial unique index，SQLite）

```python
# ORM __table_args__（SQLAlchemy 2.0 + SQLite partial index）
__table_args__ = (
    Index(
        "uq_foreshadowings_active_title",
        "project_id", "title",
        unique=True,
        sqlite_where=text("is_deleted = 0"),
    ),
)
```

**为什么是 partial index**: 「同名 = 同一伏笔」——伏笔是**档案**（一条伏笔一个生命周期：埋设 → 追踪 → 回收），「林晚的身世」只应有一条档案，同名重复建档是手误或重复提取；而**软删除后再创建同名伏笔**是合法操作（旧档案已废弃，作者重新埋同一条线），partial index 恰好两者兼得（已删除行不参与唯一性）。服务层再做一次同名检查以给出友好 422 文案。

**与 F12 的对比论证**（F12 无唯一约束、F13 有唯一约束，两者不矛盾）:

| 维度 | F12 时间线事件（实例） | F13 伏笔（档案） |
|------|----------------------|-----------------|
| 语义 | 事件是**实例**：多个「回忆」「战斗」事件合法存在，「同名 = 同一事件」不成立 | 伏笔是**档案**：「同名 = 同一伏笔」，一条伏笔一个生命周期 |
| 业务后果 | 同刻/同题事件各自独立、互不影响 | 同名重复建档 = 双份状态真相（一条 open 一条 resolved 时无法判断） |
| 唯一约束 | 不设（title/narrative_position/time_value 均可重复） | 设 partial unique `(project_id, title WHERE is_deleted=0)` |

> F13 因此**有同名冲突检查**（422），错误面比 F12 多一类（见 §3.4 异常映射表）。

### 2.4 状态机定义（open / resolved，不设 dropped）

```text
                        ┌──────────┐
              resolve   │          │   reopen
        ┌──────────────▶│ resolved │◀─────────────┐
        │               │          │              │
        │               └──────────┘              │
   ┌────┴─────┐                                  ┌─┴──────┐
   │   open   │                                  │ open   │（同一条线）
   └──────────┘                                  └────────┘
        │
        └── DELETE（软删除）──▶ deleted（任意状态可删；不注入、列表不可见）
                                   │
                                   └── restore ──▶ 恢复为原状态（open/resolved 保留）
```

| 迁移 | 动作 | 前置状态 | 后置状态 | 副作用 |
|------|------|----------|----------|--------|
| 埋设 | 创建（POST） | — | open | 默认状态；priority 默认 50 |
| 回收 | `resolve` | open | resolved | 自动设置 `resolved_at = now(UTC)` |
| 重新开启 | `reopen` | resolved | open | 自动清空 `resolved_at` |
| 废弃 | DELETE（软删除） | open / resolved | deleted | 不注入、列表不可见；restore 可恢复 |
| 恢复 | `restore` | deleted | 原状态 | open/resolved 状态与 resolved_at 原样保留 |

**状态机规则**:
- **MVP 不设 dropped 状态**（架构师候选方案，论证见 §12 决策表）：「废弃伏笔」与「软删除」在注入/追踪语义上完全等价（都不注入、档案保留、可恢复），软删除 + 同名重建已覆盖「作废后重埋同题材」场景；独立 dropped 态需要额外迁移端点与测试面，收益不成比例（P5 YAGNI）。若 F15 审计需要区分「废弃」与「删除」的变更记录，Phase 2+ 再加第三态
- `resolve` 已 resolved 的伏笔 → **幂等成功**（重复操作无毒，同 F12 restore 未删除的语义）
- `reopen` 已 open 的伏笔 → 幂等成功
- 软删除（deleted）的伏笔执行 resolve/reopen → 404「伏笔不存在」（已排除）
- 状态迁移**不记录历史轨迹**（无状态变更日志表）；变更审计归 F15（§10）

### 2.5 领域模型（Pydantic v2 语法，参照 F12 `domain/models/timeline.py`）

```python
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ForeshadowingStatus(StrEnum):
    """伏笔生命周期状态（§2.4 状态机）."""

    OPEN = "open"          # 已埋设未回收（进入 F6 注入集合）
    RESOLVED = "resolved"  # 已回收（不注入；档案保留）


def _validate_title(v: str) -> str:
    """共享的伏笔名校验：去空白后非空且不超过 100 字符."""
    stripped = v.strip()
    if not stripped:
        raise ValueError("伏笔名不能为空")
    if len(stripped) > 100:
        raise ValueError("伏笔名不能超过 100 个字符")
    return stripped


def _validate_description(v: str) -> str:
    """共享的描述校验：不超过 5000 字符（不强制去空白）."""
    if len(v) > 5000:
        raise ValueError("伏笔描述不能超过 5000 个字符")
    return v


def _validate_priority(v: int) -> int:
    """共享的优先级校验：0-100 闭区间."""
    if not 0 <= v <= 100:
        raise ValueError("优先级必须在 0-100 之间")
    return v


def _validate_location(v: str) -> str:
    """共享的埋设位置校验：去空白且不超过 200 字符（空串 = 未记录，允许）."""
    stripped = v.strip()
    if len(stripped) > 200:
        raise ValueError("埋设位置不能超过 200 个字符")
    return stripped


class Foreshadowing(BaseModel):
    """伏笔档案领域实体. 对应 foreshadowings 表."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str = ""
    priority: int = 50
    status: ForeshadowingStatus = ForeshadowingStatus.OPEN
    location: str = ""                       # 埋设位置自由文本（空 = 未记录；不挂事件时仍可写「第 3 章」）
    event_id: uuid.UUID | None = None        # F12 时间线事件锚点（None = 未挂接；叙事位置从事件获取）
    resolved_at: datetime | None = None      # 回收时间（仅状态迁移维护）
    extra: dict[str, Any] = Field(default_factory=dict)
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class ForeshadowingCreate(BaseModel):
    """创建伏笔请求 DTO — status 不可传（创建即 open，回收走 resolve 端点）."""
    project_id: uuid.UUID
    title: str
    description: str = ""
    priority: int = 50
    location: str = ""
    event_id: uuid.UUID | None = None   # F12 事件锚点（None = 不挂接；存在性/同项目校验在服务层，§2.1）

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        return _validate_title(v)

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        return _validate_description(v)

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int) -> int:
        return _validate_priority(v)

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str) -> str:
        return _validate_location(v)


class ForeshadowingUpdate(BaseModel):
    """更新伏笔请求 DTO — 所有字段可选（exclude_unset 语义，同 F1）.

    location: None 表示不修改；"" 表示清除埋设位置（置为未记录）.
    event_id: None 表示不修改；"" 表示解除事件挂接（置为 None）.
    status/resolved_at 不可通过本 DTO 修改（状态迁移走 resolve/reopen 端点，§2.4）.
    只有传入的字段会被更新，未传入的字段保持不变.
    """
    title: str | None = None
    description: str | None = None
    priority: int | None = None
    location: str | None = None
    event_id: uuid.UUID | str | None = None   # str "" = 解除事件挂接

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        return _validate_title(v) if v is not None else None

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        return _validate_description(v) if v is not None else None

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int | None) -> int | None:
        return _validate_priority(v) if v is not None else None

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str | None) -> str | None:
        return _validate_location(v) if v is not None else None

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, v: uuid.UUID | str | None) -> uuid.UUID | str | None:
        if isinstance(v, str):
            if v != "":
                raise ValueError("解除事件挂接请传空字符串")
            return v
        return v
```

> `event_id` 的「None = 不修改，"" = 解除挂接」双语义与 F11 `arc_id`（`uuid | str | None`）、F12 `time_value`（`float | str | None`）、F10 `category`（"" = 清除）同构，是既有项目约定。

---

## 3. API 契约

端点风格沿用 F2/F9/F10/F12：**创建/列表嵌套于项目路径**，**详情/更新/删除/状态动作扁平**。错误响应格式沿用 F1/F2/F9/F10/F11/F12（`{"detail": "..."}` 404 / 422）。

### 3.1 端点总览（8 个，镜像 F12 §3.1 布局；单实体 + 状态机动作端点）

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/projects/{project_id}/foreshadowings` | 创建伏笔（status=open） | `ForeshadowingCreate` | 201 + Foreshadowing |
| GET | `/api/v1/projects/{project_id}/foreshadowings` | 伏笔列表 | Query: `?search=&status=&sort_by=&sort_desc=&offset=&limit=` | 200 + `{items, total, offset, limit}` |
| GET | `/api/v1/foreshadowings/{foreshadowing_id}` | 伏笔详情 | — | 200 + Foreshadowing JSON |
| PATCH | `/api/v1/foreshadowings/{foreshadowing_id}` | 更新伏笔（不含 status） | `ForeshadowingUpdate` | 200 + Foreshadowing |
| DELETE | `/api/v1/foreshadowings/{foreshadowing_id}` | 删除伏笔 | Query: `?force=true` | 204（默认软删除） |
| POST | `/api/v1/foreshadowings/{foreshadowing_id}/restore` | 恢复伏笔 | — | 200 + Foreshadowing |
| POST | `/api/v1/foreshadowings/{foreshadowing_id}/resolve` | 标记回收（open→resolved） | — | 200 + Foreshadowing |
| POST | `/api/v1/foreshadowings/{foreshadowing_id}/reopen` | 重新开启（resolved→open） | — | 200 + Foreshadowing |

> `/foreshadowings` 下全部为**静态路径段 + 固定动作段**（`restore`/`resolve`/`reopen` 无 `{foreshadowing_id}` 动态段冲突），无需注册顺序注意（同 F12 §3.1 说明；F10 的 extract 路径歧义处理在此不适用）。

### 3.2 请求/响应示例 — 伏笔 CRUD

**创建伏笔（挂接 F12 事件）**:
```http
POST /api/v1/projects/3f2e1d4a-.../foreshadowings
Content-Type: application/json

{
  "title": "林晚的身世",
  "description": "林晚右肩的胎记与女主母亲的信物相同；预期第 30 章前后揭露。",
  "priority": 80,
  "location": "第 5 章·林晚沐浴场景",
  "event_id": "7a4f2c91-..."
}
```
→ 201（事件 7a4f2c91 存在且属于该项目；伏笔叙事位置从事件获取，不再独立存储）
```json
{
  "id": "9b1c2d3e-...", "project_id": "3f2e1d4a-...", "title": "林晚的身世",
  "description": "林晚右肩的胎记与女主母亲的信物相同；预期第 30 章前后揭露。",
  "priority": 80, "status": "open",
  "location": "第 5 章·林晚沐浴场景", "event_id": "7a4f2c91-...",
  "resolved_at": null, "extra": {}, "is_deleted": false,
  "created_at": "2026-08-01T10:00:00Z", "updated_at": "2026-08-01T10:00:00Z"
}
```

**创建伏笔（不挂接事件，仅自由文本位置）**:
```http
POST /api/v1/projects/3f2e1d4a-.../foreshadowings
{
  "title": "铜镜的秘密",
  "location": "第 3 章"
}
```
→ 201（event_id 为 null；location 自由文本兜底）

**挂接不存在的事件**:
```http
POST /api/v1/projects/3f2e1d4a-.../foreshadowings
{ "title": "铜镜的秘密", "event_id": "11111111-1111-1111-1111-111111111111" }
```
→ 422 `{"detail": "事件不存在"}`（含已软删事件——F12 get 不含软删，§2.1）

**挂接其他项目的事件**:
```http
POST /api/v1/projects/3f2e1d4a-.../foreshadowings
{ "title": "铜镜的秘密", "event_id": "7a4f2c91-..." }
```
→ 422 `{"detail": "事件不属于该项目"}`（7a4f2c91 属于另一项目）

**伏笔详情**（响应结构同创建响应，完整 Foreshadowing JSON）:
```http
GET /api/v1/foreshadowings/9b1c2d3e-...
```
→ 200（Foreshadowing JSON；404 语义见 §3.4）

**列出伏笔（状态过滤 + 搜索 + 排序 + 分页）**:
```http
GET /api/v1/projects/3f2e1d4a-.../foreshadowings?status=open&search=身世&sort_by=priority&sort_desc=true&offset=0&limit=20
```
→ 200
```json
{
  "items": [
    {"id": "9b1c2d3e-...", "title": "林晚的身世", "priority": 80, "status": "open",
     "location": "第 5 章·林晚沐浴场景", "event_id": "7a4f2c91-...", ...}
  ],
  "total": 1, "offset": 0, "limit": 20
}
```

**同名冲突**:
```http
POST /api/v1/projects/3f2e1d4a-.../foreshadowings
{ "title": "林晚的身世" }
```
→ 422 `{"detail": "同名伏笔已存在（伏笔名在项目内必须唯一）"}`

**清除埋设位置、修改优先级**:
```http
PATCH /api/v1/foreshadowings/9b1c2d3e-...
{ "priority": 90, "location": "" }
```
→ 200（更新后 Foreshadowing JSON，priority=90，location 为空串）

**解除事件挂接**:
```http
PATCH /api/v1/foreshadowings/9b1c2d3e-...
{ "event_id": "" }
```
→ 200（event_id 为 null；传非空字符串 → 422，见 §3.4）

**软删除 / 恢复 / 硬删除**:
```http
DELETE /api/v1/foreshadowings/9b1c2d3e-...            → 204（软删除）
POST /api/v1/foreshadowings/9b1c2d3e-.../restore      → 200 + Foreshadowing
DELETE /api/v1/foreshadowings/9b1c2d3e-...?force=true → 204（物理删除）
```

### 3.3 请求/响应示例 — 状态机动作

**标记回收（open→resolved，自动设置 resolved_at）**:
```http
POST /api/v1/foreshadowings/9b1c2d3e-.../resolve
```
→ 200
```json
{
  "id": "9b1c2d3e-...", "title": "林晚的身世", "priority": 80,
  "status": "resolved", "location": "第 5 章·林晚沐浴场景",
  "event_id": "7a4f2c91-...",
  "resolved_at": "2026-08-10T03:00:00Z",
  "updated_at": "2026-08-10T03:00:00Z", ...
}
```

**重新开启（resolved→open，清空 resolved_at）**:
```http
POST /api/v1/foreshadowings/9b1c2d3e-.../reopen
```
→ 200（status 为 "open"，resolved_at 为 null）

**幂等动作（对已 resolved 的伏笔再次 resolve）**:
```http
POST /api/v1/foreshadowings/9b1c2d3e-.../resolve
```
→ 200（重复操作无毒：状态不变，resolved_at 不更新——同 F12 restore 未删除的语义）

### 3.4 错误响应格式（沿用 F1/F2/F9/F10/F11/F12/ADR-012）

```json
// 404 — 资源不存在
{"detail": "项目不存在"}
{"detail": "伏笔不存在"}

// 422 — 业务校验失败 / Pydantic 验证失败
{"detail": "同名伏笔已存在（伏笔名在项目内必须唯一）"}
{"detail": "伏笔名不能为空"}
{"detail": "伏笔名不能超过 100 个字符"}
{"detail": "伏笔描述不能超过 5000 个字符"}
{"detail": "优先级必须在 0-100 之间"}
{"detail": "埋设位置不能超过 200 个字符"}
{"detail": "事件不存在"}
{"detail": "事件不属于该项目"}
{"detail": "解除事件挂接请传空字符串"}
```

**异常映射表**:

| 异常/场景 | 状态码 | 响应 |
|-----------|--------|------|
| 项目/伏笔不存在（Service 返回 None） | 404 | 见上 |
| 无效 UUID 格式 | 404 | 统一解析失败处理（同 F9/F10/F11/F12 `_parse_id`） |
| 同名活动伏笔 | 422 | 服务层业务校验（`ForeshadowingNameConflictError`，消息即 detail） |
| event_id 指向不存在的事件（含已软删事件） | 422 | 服务层经 F12 `TimelineRepositoryProtocol.get` 校验（`EventNotFoundError`，消息「事件不存在」） |
| event_id 指向其他项目的事件 | 422 | 服务层校验 `event.project_id == 伏笔.project_id`（`EventNotInProjectError`，消息「事件不属于该项目」） |
| Pydantic `ValidationError`（含 event_id 清除传非空字符串、event_id 非法 UUID 格式） | 422 | FastAPI 自动生成 |
| DB 错误 | 500 | 全局处理器（loguru 记录，ADR-012/016） |

> **与 F9/F10/F11 的差异**：无 LLM 相关错误（无 `LLMRequestError`/提取/生成错误）。**与 F12 的差异**：多两类错误——同名冲突（F13 有唯一约束，见 §2.3）与事件校验（event_id 跨模块引用 F12，见 §2.1/§12）。

---

## 4. CLI 命令签名

遵循 F7 §5 全局约定：`--json` 统一信封 `{"ok": true, "data": ...}` / `{"ok": false, "error": {"code", "message"}}`；退出码 0/1/2/130；错误码 NOT_FOUND / VALIDATION_ERROR / **DB_ERROR**（**无 LLM_ERROR**——F13 无 LLM）；删除类命令二次确认 + `--force`；`--json` + 无 `--force` 的删除 → `VALIDATION_ERROR`（沿用 F7 §7）。`foreshadowing` 组在 F13 落地时并入 F7 命令树（`cli/app.py` 注册，同 F9 character 组 / F10 world 组 / F11 outline 组 / F12 timeline 组）。

### 4.1 foreshadowing 组（委托 ForeshadowingService；无子组——F13 单实体，同 F10 world 组布局）

```bash
inkflow foreshadowing create --project-id <uuid> --title <str> \
    [--description <str>] [--priority <int>] [--location <str>] \
    [--event-id <uuid>] [--json]
    # status 固定为 open（创建即埋设）；--event-id 挂接 F12 时间线事件（缺省 = 不挂接）

inkflow foreshadowing list --project-id <uuid> \
    [--status <open|resolved>] [--search <str>] \
    [--sort <priority|title|status|updated_at|created_at>] \
    [--sort-desc/--no-sort-desc] [--json]

inkflow foreshadowing get --id <uuid> [--json]

inkflow foreshadowing update --id <uuid> \
    [--title <str>] [--description <str>] [--priority <int>] \
    [--location <str|"">] [--event-id <uuid|"">] [--json]
    # --location "" 表示清除埋设位置；--event-id "" 表示解除事件挂接（置为 None）

inkflow foreshadowing delete --id <uuid> [--force] [--permanent] [--json]
inkflow foreshadowing restore --id <uuid> [--json]

inkflow foreshadowing resolve --id <uuid> [--json]    # 标记回收（open→resolved）
inkflow foreshadowing reopen --id <uuid> [--json]     # 重新开启（resolved→open）
```

> 命令名 `resolve` / `reopen` 与 Python 内置无关键字冲突（`resolve` 是 `str` 方法名、`reopen` 非保留字），Typer 命令注册正常（同 F12 §4.1 的 `check`/`view` 先例）。

### 4.2 输出格式

```bash
# 默认人类可读
✅ 伏笔创建成功: [林晚的身世]（优先级 80，未回收）
✅ 伏笔已回收: [林晚的身世]
✅ 伏笔已重新开启: [林晚的身世]
✅ 伏笔已删除: [林晚的身世]
📋 未回收伏笔 3 条: 1. [林晚的身世] (优先级 80, 第 5 章·林晚沐浴场景) 2. [铜镜的秘密] (优先级 60) ...
🔍 已回收伏笔 1 条: [铜镜的秘密] (回收于 2026-08-10)

# --json 输出
inkflow foreshadowing create --project-id ... --title "林晚的身世" --priority 80 --json
→ {"ok": true, "data": {"id": "...", "title": "林晚的身世", "priority": 80, "status": "open", ...}}

inkflow foreshadowing resolve --id ... --json
→ {"ok": true, "data": {"id": "...", "title": "林晚的身世", "status": "resolved", "resolved_at": "2026-08-10T03:00:00Z", ...}}

inkflow foreshadowing get --id 00000000-0000-0000-0000-000000000000 --json
→ {"ok": false, "error": {"code": "NOT_FOUND", "message": "伏笔不存在"}}   # 退出码 1

inkflow foreshadowing delete --id ... --json
→ {"ok": false, "error": {"code": "VALIDATION_ERROR", "message": "删除需 --force 或交互确认"}}  # 退出码 1
```

---

## 5. 伏笔状态机与注入模式（关键差异：确定性状态追踪 + F6 数据源替换）

> ⚠️ **本节是 F13 与 F9/F10/F11/F12 样板的核心差异点**：F9/F10 的 §5 是「AI 提取管线」，F11 的 §5 是「AI 生成管线」，F12 的 §5 是「一致性检查算法」；本模块的 §5 是**纯确定性的状态追踪 + F6 上下文注入集成**——**无 LLM、无模板、无重试、无合并**。F13 是首个在 spec 层**直接承接 F6 数据源替换**的 Phase 2 模块（F9/F10 的替换归 0.2.0 联调，F13 因验收标准 2「写作时注入」而必须纳入，见 §12 决策表）。

### 5.1 模式总览

```text
 ┌────────────────────────────────────────────────────────────┐
 │ 输入: ForeshadowingService（CRUD + resolve/reopen 状态机）    │
 └──────────────────────────┬─────────────────────────────────┘
                            ▼
 ① 作者/（F14 未来）通过 API/CLI 维护伏笔档案（title/description/priority/status…）
 ② 状态机: open ──resolve──▶ resolved（自动记 resolved_at）；reopen 反向
 ③ F6 注入: 写作时 F3 调用 ContextService.build_context
    └─ ForeshadowingSource.collect(project_id, chapter_id)   ← 本模块实现（替换空实现）
        ├─ 查询项目全部 status=open 且未软删除的伏笔（按 priority DESC）
        ├─ 每条构造 ContextItem(source=FORESHADOWING, title=「伏笔：XXX」,
        │     content=提醒文本, priority=伏笔.priority, metadata={...})
        └─ 返回列表 → F6 dynamic 层按 priority 降序注入，超预算裁剪（dropped）
 ④ 写作 Prompt 中出现「## 伏笔：XXX」分段 → LLM 写作时自然带上未回收伏笔约束
```

**模式要点**:
1. **状态追踪为纯确定性逻辑**：状态迁移表（§2.4）是唯一规则源，同一输入永远得到同一结果（可快照测试）
2. **注入文本为确定性模板构造**：不调用 LLM（无模板文件、无解析、无重试）——伏笔提醒是结构化数据的文本投影，LLM 加工归 F14（§10）
3. **F6 集成是契约实现而非新机制**：`ForeshadowingSource` 的空实现位置、`ContextSourceProtocol.collect(project_id, chapter_id)` 签名、dynamic 层排序/裁剪规则全部由 F6 已定义（F6 spec §3.2/§4.5），F13 只填充真实数据
4. **注入无缓存**：每次组装实时收集（伏笔量级 ≤ 数百，无性能压力；resolve/reopen 后下次写作立即生效——YAGNI 不做缓存失效机制）

### 5.2 状态机定义与迁移规则

状态机（两态 + 软删除）已在 §2.4 定义，本节补充实现口径：

| 规则 | 说明 |
|------|------|
| 迁移来源 | 只有 3 个入口：创建（→open）、`resolve`（open→resolved）、`reopen`（resolved→open）；DELETE/restore 不改变 status 字段 |
| resolve 实现 | 查询活动伏笔 → 不存在 → 404；status=open → 置 resolved + `resolved_at=now(UTC)`；已 resolved → 原样返回（幂等） |
| reopen 实现 | 查询活动伏笔 → 不存在 → 404；status=resolved → 置 open + `resolved_at=None`；已 open → 原样返回（幂等） |
| 软删除实现 | 任意状态可软删除；恢复后 status/resolved_at 原样保留 |
| 并发 | 单用户本地工具，不处理并发状态竞争（同 F10/F12；DB 行级更新兜底） |

### 5.3 ForeshadowingSource 实现（替换 `infrastructure/context/sources.py` 空实现）

**现状**（`backend/src/inkflow/infrastructure/context/sources.py`）: `ForeshadowingSource.collect()` 是空实现，`# TODO: Phase 2: F14 伏笔管理数据源`（**F14 为 ADR-019 前旧编号，实际属 F13**，编号口径见 §11）；`api/deps.py` 中以 `ForeshadowingSource()` 无参实例化装配进 sources dict。

**替换方案**:

```python
class ForeshadowingSource:
    """伏笔数据源 — 收集未回收（open）伏笔提醒（F13 真实实现）.

    Args:
        foreshadowing_repo: 伏笔仓储（list_open 查询 open 状态活动伏笔）.
    """

    def __init__(self, foreshadowing_repo: ForeshadowingRepositoryProtocol) -> None:
        self._repo = foreshadowing_repo

    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        """收集全部未回收伏笔的提醒条目.

        - 项目不存在/无 open 伏笔 → 空列表（跳过，不报错，同 F6 数据源惯例）
        - 项目存在但所有伏笔已回收/已软删除 → 空列表（正常路径）
        - chapter_id 参数 MVP 不使用（全量注入 open 伏笔，按章节过滤归 Phase 2+，见待澄清 Q3）
        """
        items = await self._repo.list_open(project_id.int)   # (priority DESC, updated_at DESC)
        return [
            ContextItem(
                source=ContextSourceType.FORESHADOWING,
                title=f"伏笔：{f.title}",
                content=_render_reminder(f),                 # 确定性模板，见下
                priority=f.priority,                          # 透传伏笔优先级（F6 dynamic 层排序键）
                metadata={
                    "foreshadowing_id": str(f.id),
                    "status": f.status.value,
                    "location": f.location,
                    "event_id": str(f.event_id) if f.event_id else None,
                },
            )
            for f in items
        ]
```

**提醒文本确定性模板**（`_render_reminder`，纯函数，无 LLM）:

```text
未回收伏笔：{title}。
{description}
（埋设位置：{location}）   ← 仅当 location 非空时拼接
```

| ContextItem 字段 | 取值 | 说明 |
|------------------|------|------|
| source | `ContextSourceType.FORESHADOWING` | F6 已定义枚举值（dynamic 层，F6 spec §3.2） |
| title | `"伏笔：{title}"` | 注入分段标题（同「角色：林晚」「第 3 章摘要」惯例） |
| content | 提醒文本（确定性模板） | 全部来自档案字段，无 LLM 加工 |
| priority | `伏笔.priority`（0-100，默认 50） | **F6 dynamic 层按 priority 降序消费**（F6 spec §4.2/§4.5） |
| metadata | `{foreshadowing_id, status, location, event_id}` | 供 F3/F6 调试与未来按章节过滤使用；event_id 原样透传（挂接事件即携带 UUID 字符串，未挂接为 null） |

> **叙事位置获取口径（v1.1）**: 伏笔不再独立存储 narrative_position——挂接事件的伏笔，其叙事位置 = 所挂 F12 事件的 `narrative_position`（F12 spec §2.1）。MVP 注入**不跨模块查询事件**（提醒文本只拼伏笔字段，模板见上）；若未来需要「按叙事位置过滤注入」（待澄清 Q3），走 F12 事件数据（collect 侧注入 timeline_repo 或读取 F12 视图），归 Phase 2+。

### 5.4 注入时机与排序（写作链路）

**注入时机**: F3 写作（`write next/continue`）→ `ContextService.build_context(request)` → 收集阶段调用 `sources[FORESHADOWING].collect(project_id, chapter_id)`（F6 spec §4.1 流程第 1 步）→ dynamic 层预算分配（F6 spec §4.5）→ `render_system_prompt` 渲染为 `## 伏笔：XXX` 分段（F6 spec §4.1 流程第 6 步）。

**排序与裁剪（F6 已定义，F13 只保证数据契约）**:

| 规则 | 来源 |
|------|------|
| 伏笔条目按 `priority` 降序注入 | F6 spec §4.2「伏笔条目按 priority 降序」 |
| 混合时摘要优先（保证连贯性），伏笔次之；同优先级先到先得 | F6 spec §4.2 |
| dynamic 层只选择、不压缩；放不下直接裁剪，记 `DroppedItem(reason="over_budget")` | F6 spec §4.5 |
| 预算为 0 或候选为空 → 空注入（正常路径，不报错） | F6 spec §4.5 |

**注入范围论证（全部 open vs 仅高优先级）**: MVP **注入全部 open 伏笔**（priority 降序）——① 伏笔量级小（单项目通常 ≤ 数十条），全量候选 + F6 预算裁剪已保证不超窗口，额外加「优先级阈值过滤」是重复裁剪逻辑（YAGNI）；② 高优先级之外的伏笔偶尔也需被想起（低优先级伏笔恰恰最容易被忘）；③ F6 的裁剪记录（dropped）已提供「哪些伏笔没进 Prompt」的可观测性。按章节/位置过滤注入（如「只提醒第 5 章之前埋的伏笔」）归 Phase 2+（待澄清 Q3 建议答案）。

### 5.5 输入约束与边界

| 约束 | 值 | 说明 |
|------|-----|------|
| 注入范围 | 项目内全部 **open 且未软删除** 伏笔 | resolved/deleted 不注入；无分页/过滤参数（YAGNI） |
| 排序 | `(priority DESC, updated_at DESC)` | 与列表默认排序一致（§6.3）；priority 相等按 updated_at 兜底 |
| 项目不存在 | 空列表 | 同 F6 数据源惯例（跳过不报错）；F6 组装层另有项目校验 |
| 无伏笔/全部已回收 | 空列表 → 空注入 | 正常路径 |
| chapter_id | 签名保留、MVP 不使用 | Protocol 契约兼容（F6 定义），过滤归 Phase 2+ |
| event_id 锚点 | 仅透传 metadata，不校验/不查询事件 | 挂接校验发生在 Service 层（§2.1）；事件软删不影响注入（提醒文本只来自伏笔字段）；事件硬删 → FK SET NULL，event_id 变 null（§2.1/§12） |
| 预算裁剪 | F6 dynamic 层处理 | 伏笔不阻塞写作（同摘要失败策略，F6 spec §4.6） |

### 5.6 状态追踪+注入 vs 提取/生成/一致性检查：差异对照表

| 维度 | F9/F10 提取（样板） | F11 生成（样板） | F12 一致性检查（样板） | F13 状态追踪+注入（本模块） |
|------|--------------------|--------------------|------------------------|--------------------------|
| 输入 | 章节文本 `text`（必填） | 项目信息 + 可选 prompt/num_chapters | 事件档案（双时间维度，库内已有） | 伏笔档案（状态 + 字段，库内已有） |
| 方向 | 文本 → 实体（沉淀既有信息） | 设定 → 规划（创作新内容） | 双线 → 报告（验证一致性） | 档案 → 提醒条目（注入写作上下文） |
| 引擎 | LLM（模板 + 解析 + 修复重试） | LLM（模板 + 解析 + 修复重试） | 确定性算法（无 LLM） | **确定性状态机 + 确定性文本模板（无 LLM）** |
| 模板 | `{module}_extract.yaml` | `outline_generate.yaml` | 无模板 | **无模板**（无 `infrastructure/llm/templates/`） |
| 副作用 | 合并落库（单事务） | 新建落库（单事务，save 可跳过） | 无副作用（只读计算） | resolve/reopen 落库（状态迁移）；collect 只读 |
| 幂等性 | 同文本二次提取 → 空 diff | 不承诺幂等 | 严格幂等（同数据同报告） | 状态迁移幂等（重复 resolve/reopen 无毒）；collect 纯读 |
| 失败模式 | LLMRequestError / 解析重试耗尽 | 同左 | 无（纯内存计算） | 无 LLM 失败；仅 DB 读取（同 F12） |
| 测试方式 | Mock LLM 分支覆盖 | 同左 | 快照断言 + 序列构造用例 | 状态迁移表驱动用例 + ContextItem 构造断言（Mock Repo） |
| 跨模块集成 | F6 数据源替换归联调 | 同左 | 无 | **F6 数据源替换纳入本模块**（§5.3，验收标准 2 的实证路径） |

---

## 6. 伏笔组织规则

（对应 F12 §6「事件与双线语义/时间线组织规则」的位置；F13 单实体，本节承载状态语义、priority 语义与查询规则）

### 6.1 状态语义与流转规则

- **open（未回收）** = 已埋设、等待兑现：唯一进入 F6 注入集合的状态（§5.3）
- **resolved（已回收）** = 故事中已兑现/已揭露：不注入，档案保留供作者回溯（「这本书埋了哪些伏笔、都回收了吗」）
- 流转只走 §2.4 迁移表：创建→open；`resolve`→resolved；`reopen`→open；DELETE/restore 不改变 status
- `resolved_at` 是状态迁移的**只读副产物**（resolve 设置 / reopen 清空），作者不可直接修改
- 软删除的伏笔不进入任何列表与注入视图；恢复后原状态原样保留

### 6.2 priority 语义

- `priority` 是**注入优先级**（int 0-100，默认 50，大者先注入）——F6 dynamic 层排序契约的键（F6 spec §4.2）
- 建议值（CLI/UI 提示用，**不做枚举校验**——自由整数，受控词表归 F14，同 F9 relation_type / F10 category 处理）：80 = 高（主线伏笔，近期必须回收）、50 = 中（默认）、20 = 低（彩蛋/背景伏笔）
- `priority` 与 `status` **独立正交**：回收不重置优先级（作者可事后调整）；列表/注入排序均与状态过滤组合使用
- `priority` 相等的条目按 `updated_at DESC` 兜底（稳定排序）

### 6.3 搜索与排序（伏笔列表，沿用 F1 §6/F9 §6.3/F10 §6.2/F12 §6.3）

| 参数 | 默认值 | 约束 | 说明 |
|------|--------|------|------|
| `search` | — | — | 对 title 不区分大小写子串匹配（icontains） |
| `status` | — | `open` / `resolved` | 状态**精确**过滤；不传 = 全部活动伏笔（open + resolved） |
| `sort_by` | `priority` | `priority` / `title` / `status` / `updated_at` / `created_at` | 排序字段（伏笔语境下优先级为自然默认，与注入顺序一致；event_id 为 UUID 无排序业务意义，不参与排序） |
| `sort_desc` | `true` | — | 降序（priority 排序时大者在前） |
| `offset` / `limit` | 0 / 50 | offset ≥ 0, limit [1, 100] | 分页 |

- 伏笔**内容/描述全文检索**不在 F13 范围（F22 搜索服务，§10）
- 列表**不区分注入视图**：注入集合 = 列表过滤 `status=open` 的全量子集（无独立端点，YAGNI）

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 创建伏笔名为空/全空白 | 422: "伏笔名不能为空" |
| 创建伏笔名 > 100 字符 | 422: "伏笔名不能超过 100 个字符" |
| 创建伏笔名与项目内**活动**伏笔重复 | 422: "同名伏笔已存在（伏笔名在项目内必须唯一）" |
| 软删除后**再创建同名伏笔** | ✅ 成功（partial unique 排除已删除行；服务层同名检查仅限活动条目） |
| description > 5000 字符 | 422: "伏笔描述不能超过 5000 个字符" |
| priority 超出 0-100 | 422: "优先级必须在 0-100 之间" |
| location > 200 字符 | 422: "埋设位置不能超过 200 个字符" |
| 创建/更新 event_id 指向不存在的事件 | 422: "事件不存在"（含已软删事件——F12 get 不含软删，§2.1） |
| 创建/更新 event_id 指向其他项目的事件 | 422: "事件不属于该项目" |
| 创建伏笔时项目不存在 | 404: "项目不存在" |
| 获取/更新/软删除/硬删除不存在的伏笔 | 404: "伏笔不存在" |
| 硬删除已软删除的伏笔 | 404: "伏笔不存在"（已排除） |
| 恢复不存在的伏笔 | 404: "伏笔不存在" |
| 恢复未删除的伏笔 | 正常返回（重复操作无毒，同 F1） |
| resolve 不存在的伏笔 | 404: "伏笔不存在" |
| resolve 已软删除的伏笔 | 404: "伏笔不存在"（已排除，§2.4） |
| resolve 已 resolved 的伏笔 | ✅ 幂等成功（状态不变，resolved_at 不更新） |
| reopen 已 open 的伏笔 | ✅ 幂等成功（状态不变） |
| 更新 event_id 传 ""（解除挂接） | ✅ 成功，置 None |
| 更新 event_id 传非空字符串（如 "abc"） | 422（解除事件挂接只接受空字符串；Create/Update 传非法 UUID 格式 → Pydantic 422） |
| 已挂接伏笔的事件被软删 | ✅ event_id 保留（锚点保留，§2.1）；注入 metadata 原样携带；resolve/reopen/更新不受影响 |
| 已挂接伏笔的事件被硬删（force） | ✅ FK ON DELETE SET NULL 自动置 None（挂接解除，无 422；论证见 §12） |
| 更新 location 传 ""（清除） | ✅ 成功，置 ""（未记录） |
| 更新请求携带 status/resolved_at 字段 | 422（Pydantic 忽略未知字段 → 不生效；状态迁移走动作端点，§2.4） |
| F6 注入：项目无伏笔 / 全部已回收 / 全部已软删除 | 空列表 → 空注入（正常路径，不报错） |
| F6 注入：dynamic 预算不足 | 伏笔条目被裁剪 + `DroppedItem(reason="over_budget")`，**不阻塞写作**（F6 行为） |
| F6 注入：项目不存在 | collect 返回空列表（F6 数据源惯例；组装层另有项目校验） |
| resolve 后立即写作 | 该伏笔不再出现于注入集合（无缓存，实时生效） |
| 伏笔列表搜索无结果 / 分页越界 | 200: 空 items（同 F1） |
| 项目硬删除 | 伏笔级联物理删除（FK CASCADE）；项目软删除不影响伏笔数据 |
| CLI 删除类命令无 `--force` | 二次确认；`--json` 下 → VALIDATION_ERROR（沿用 F7 §7） |
| CLI 非法 `--status` 值（如 `--status pending`） | 退出码 2（用法错误，Typer Choice 校验） |

---

## 8. 文件结构

遵循 ADR-007v2 包结构，与 F9/F10/F11/F12 真实源码树一一对应。新增/修改文件（**对照主仓 `backend/src/inkflow/` 真实树逐文件核对**）：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── foreshadowing.py      ← CREATE: ForeshadowingStatus, Foreshadowing,
│   │   │                              ForeshadowingCreate, ForeshadowingUpdate
│   │   └── __init__.py           ← MODIFY: 导出新模型
│   ├── ports/
│   │   ├── foreshadowing_repository.py ← CREATE: ForeshadowingRepositoryProtocol
│   │   ├── foreshadowing_errors.py     ← CREATE: ForeshadowingServiceError(422 基类) /
│   │   │                              ForeshadowingNotFoundError(404，不继承基类) /
│   │   │                              ProjectNotFoundError / ForeshadowingNameConflictError /
│   │   │                              EventNotFoundError / EventNotInProjectError（422，§3.4）
│   │   └── __init__.py           ← MODIFY: 导出
│   └── services/
│       ├── foreshadowing_service.py ← CREATE: ForeshadowingService（CRUD + resolve/reopen
│       │                              + 同名检查 + resolved_at 维护 + event_id 事件校验；
│       │                              构造注入 TimelineRepositoryProtocol——事件校验复用
│       │                              F12 仓储，F13 仓储无新增方法，见 §8.1）
│       └── __init__.py           ← MODIFY
├── infrastructure/
│   ├── context/
│   │   └── sources.py            ← MODIFY: ForeshadowingSource 空实现 → 真实实现
│   │                                  （注入 foreshadowing_repo；更新模块 docstring 中
│   │                                  「待 F8/F9/F14 落地后替换」的旧编号口径，见 §11）
│   └── database/
│       ├── models/
│       │   ├── foreshadowing.py  ← CREATE: ForeshadowingORM
│       │   │                          （索引: project_id / (project_id, status) /
│       │   │                          (project_id, priority) / (project_id, event_id)；
│       │   │                          event_id FK→timeline_events.id (ON DELETE SET NULL)
│       │   │                          ——F12 表须已存在（硬依赖，§11）；
│       │   │                          partial unique (project_id, title WHERE is_deleted=0)；
│       │   │                          soft-delete 标记）
│       │   └── __init__.py       ← MODIFY: 注册 ForeshadowingORM（create_tables 依赖）
│       └── repositories/
│           ├── foreshadowing_repo.py ← CREATE: SQLiteForeshadowingRepository
│           └── __init__.py       ← MODIFY
├── api/
│   ├── routers/
│   │   ├── foreshadowings.py     ← CREATE: 8 个端点（CRUD + restore + resolve + reopen）
│   │   └── __init__.py           ← MODIFY
│   ├── deps.py                   ← MODIFY: get_foreshadowing_service 复用 F12 已实现的
│   │                                 timeline_repository 获取路径（如 get_timeline_repository），
│   │                                 构造 ForeshadowingService(foreshadowing_repo, timeline_repo)
│   │                                 （事件校验用，§3.4/§8.1）；get_context_service 装配改为
│   │                                 ForeshadowingSource(foreshadowing_repo)
│   │                                 （注入链路不跨模块——不注入 timeline_repo，§5.3）
│   └── app.py                    ← MODIFY: 注册 foreshadowings.router
└── cli/
    ├── commands/
    │   ├── foreshadowing.py      ← CREATE: foreshadowing 组（create/list/get/update/delete/
    │   │                              restore/resolve/reopen 8 命令）
    │   └── __init__.py           ← MODIFY
    └── app.py                    ← MODIFY: 注册 foreshadowing 命令组
```

```text
backend/tests/
├── unit/
│   ├── test_foreshadowing_models.py ← CREATE: 领域模型/DTO 验证（含清除语义、状态枚举）
│   ├── test_foreshadowing_repo.py   ← CREATE: 仓储集成测试（in-memory SQLite，含 partial unique）
│   ├── test_foreshadowing_service.py← CREATE: 服务测试（CRUD + 同名 422 + 状态机迁移）
│   ├── test_foreshadowing_source.py ← CREATE: F6 数据源专项（ContextItem 构造/排序/空数据，§5.3）
│   └── test_foreshadowing_api.py    ← CREATE: API 集成测试（Mock Service）

tests/cli/
└── test_cli_foreshadowing.py        ← CREATE: CLI 测试（Mock ForeshadowingService，信封/退出码）
```

> **与 F12 §8 的差异（测试布局）**: F12 spec 写于 Issue #61（CLI 测试目录治理）合入前，其 `backend/tests/test_cli_timeline.py` 位置已过时——**现行布局为顶层 `tests/cli/`**（主仓 `tests/cli/` 已有 14 个 `test_cli_*.py`，ci.yml `integration-cli-backend` job 显式列出）。F13 的 CLI 测试放 `tests/cli/test_cli_foreshadowing.py`。
>
> ⚠️ **CI 覆盖盲区防范（Issue #59/#61 教训）**: `tests/cli/test_cli_foreshadowing.py` **默认不被任何 CI job 收集**——实施时必须将其**显式加入 ci.yml `integration-cli-backend` job 的 pytest 文件列表**（`../tests/cli/test_cli_foreshadowing.py`，与现有 10 个文件并列；PowerShell 反引号续行、Windows 下 pytest 不展开 glob，须显式文件名——见 §9/§12）。

### 8.1 ForeshadowingRepositoryProtocol（参照 F10 `world_repository.py` / F12 `timeline_repository.py` Protocol 风格）

```python
class ForeshadowingRepositoryProtocol(Protocol):
    """伏笔档案仓储端口.

    按 spec §2: 单实体；项目内活动伏笔 title 唯一（partial unique）；
    软删除后同名可复用。list_open 供 F6 数据源查询注入集合
    （status=open 且未软删除，按 (priority DESC, updated_at DESC) 排序）。

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9/F10/F11/F12）。
    """

    # ── Foreshadowing ──
    async def add(self, f: Foreshadowing) -> Foreshadowing: ...
    async def get(self, foreshadowing_id: int) -> Foreshadowing | None: ...
    async def get_by_title(self, project_id: int, title: str) -> Foreshadowing | None: ...
    async def list(self, project_id: int, search: str | None = None,
                   status: str | None = None, sort_by: str = "priority",
                   sort_desc: bool = True, offset: int = 0,
                   limit: int = 50) -> tuple[builtins.list[Foreshadowing], int]: ...
    async def list_open(self, project_id: int) -> builtins.list[Foreshadowing]: ...  # F6 注入集合（priority DESC）
    async def update(self, f: Foreshadowing) -> Foreshadowing: ...
    async def soft_delete(self, foreshadowing_id: int) -> bool: ...
    async def restore(self, foreshadowing_id: int) -> Foreshadowing | None: ...
    async def hard_delete(self, foreshadowing_id: int) -> bool: ...
```

> 仓储层方法入参用 int（与 F9/F10/F11/F12 RepositoryProtocol 一致）；Service 负责 UUID ↔ int 转换（沿用 F1 `_to_int_id` 模式）。`list_open` 返回顺序即 F6 注入顺序（§5.3 直接消费）。
>
> **事件校验（v1.1）**: F13 仓储**无新增事件查询方法**——event_id 存在性 + 同项目校验复用 **F12 `TimelineRepositoryProtocol.get`**（Service 层构造注入，装配见 §8 deps.py），校验语义与 F12 一致（get 不含软删事件）。

---

## 9. 测试策略

### 测试层次（沿用 ADR-018 三层目录 + pytest markers；六层结构同 F12 §9）

```text
单元测试: 领域模型/DTO 验证（含清除语义、状态枚举）       ~13 cases
集成测试: SQLiteForeshadowingRepository（in-memory SQLite）~15 cases
服务测试: ForeshadowingService（Mock Repository，状态机）  ~16 cases
数据源测试: ForeshadowingSource（Mock Repo，ContextItem 构造）~8 cases
API 测试: 8 端点（Mock Service）                           ~14 cases
CLI 测试: foreshadowing 组（Mock ForeshadowingService）    ~15 cases
```

### 关键测试场景

**领域模型**: title 空/空白/超长 → ValidationError / description 超长 → ValidationError / priority 越界（-1、101）→ ValidationError、边界（0、100）合法 / location 超长 → ValidationError / event_id 合法 UUID 与 None 合法、非法 UUID 格式 → ValidationError / ForeshadowingStatus 枚举两值（open/resolved）/ ForeshadowingUpdate 部分更新语义（priority None 不修改；location None 不修改、"" 清除；event_id None 不修改、"" 解除挂接、非空字符串 → 422）/ ForeshadowingCreate 无 status 字段（默认 open）

**仓储**: 伏笔 CRUD 往返（含 event_id 挂接/解除持久化）/ `get_by_title` 命中与未命中 / 活动同名唯一（partial unique：插入第二个活动同名 → IntegrityError；软删除后可再插同名）/ 软删除后 get 返回 None / `list` 搜索、status 过滤（open/resolved/不传=全部）、各 sort_by 排序（priority 默认降序）/ `list_open` 只含 open 活动伏笔、按 (priority DESC, updated_at DESC)、resolved/软删除排除 / 分页 / 硬删除 FK 级联（项目删除 → 伏笔级联）/ **事件硬删 → 伏笔 event_id 自动置 None（FK ON DELETE SET NULL，PRAGMA foreign_keys=ON 下验证）**

**服务**: 创建/更新/软删/恢复全流程 / 同名活动伏笔 → 422 / 伏笔不存在各操作 → None → 404 / resolve 编排（open→resolved + resolved_at 设置；已 resolved 幂等；软删除 → 404）/ reopen 编排（resolved→open + resolved_at 清空；已 open 幂等）/ status 不可经 update 修改 / 项目不存在 → 404 / **event_id 校验编排**：挂接成功（Mock timeline_repo.get 命中同项目）→ 事件不存在（get 返回 None）→ 422 / 跨项目事件 → 422 / 已软删事件（get 返回 None）→ 422 / update event_id="" 解除挂接 → None / update 未传 event_id → 不修改

**数据源（ForeshadowingSource，Mock Repo）**: 有 open 伏笔 → 逐条 ContextItem（source=FORESHADOWING、title 前缀「伏笔：」、content 模板正确、priority 透传、metadata 完整含 event_id）/ 挂接事件伏笔 metadata.event_id 为 UUID 字符串、未挂接为 null / priority 降序返回 / description 为空时 content 模板省略描述段 / location 为空时模板省略位置段 / 无 open 伏笔 → 空列表 / 全部 resolved → 空列表 / 项目不存在（repo 返回空）→ 空列表 / 软删除的伏笔不出现（repo 语义保证）

**API**: 8 端点成功路径（含创建/更新带 event_id）/ 404 全路径（项目/伏笔）/ 422 业务校验（同名冲突、字段超长、priority 越界、事件不存在、事件跨项目、清除传非空字符串）/ resolve/reopen 状态迁移示例响应（resolved_at 设置与清空）/ 幂等 resolve → 200 / 无效 UUID → 404

**CLI**: 各命令成功路径与参数透传（含 `--event-id`）/ 信封格式与退出码 0/1/2 / delete 二次确认 + `--force` / `--json` + delete 无 `--force` → VALIDATION_ERROR / resolve/reopen 人类可读输出（✅ 伏笔已回收/已重新开启）与 `--json` 完整对象 / `--status` 非法值 → 退出码 2 / NOT_FOUND 错误信封 / `--location ""`、`--event-id ""` 清除语义透传

### 覆盖率目标

- F13 模块行覆盖率 **≥ 80%**（DTO 验证 100%、状态机迁移全分支、数据源构造全分支，同 F9/F10/F11/F12）
- 全仓覆盖率 **≥ 60%**（0.2.0 DoD，ADR-019）
- CI 门禁：ruff + mypy + pytest 全绿（ADR-017/018）；domain/ 零 FastAPI/Typer/SQLAlchemy/LangChain import（全局约束，ADR-002/015——F13 无 LLM，天然满足）
- **CI 覆盖盲区防范**: `tests/cli/test_cli_foreshadowing.py` 必须显式加入 ci.yml `integration-cli-backend` job（Issue #59/#61 教训，见 §8 注记）——实施 PR 中 ci.yml 修改与测试文件同时合入，否则 CLI 测试为「盲区绿」

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|----------|
| 伏笔 AI 提取 / 回收自动检测（章节文本 → 伏笔埋设、正文 → 伏笔兑现识别、自然语言位置解析） | **F14 统一提取服务**（P1-06，Issue #44）——F13 状态追踪与注入均为确定性实现，无 LLM；F14 落地时复用本模块实体/状态/priority 约定 |
| 跨模块全维度一致性审计（角色/世界观/时间线/伏笔联动审计） | **F15 审计服务**（P1-07，Issue 待创建）——F13 只管理伏笔**内部**状态生命周期 |
| 伏笔-章节强绑定（chapter_id FK、按当前章节过滤注入） | Phase 2+——同 F11/F12 边界声明：F13 管「伏笔数据」，F2 管「已创建卷/章」，互不绑定；章节级注入过滤归 Phase 2+（见待澄清 Q3） |
| dropped（废弃）状态与迁移端点 | 本 spec 决策：MVP 不设（软删除语义覆盖「废弃」，YAGNI，见 §2.4/§12）；F15 需要区分「废弃/删除」变更记录时再加第三态 |
| 受控 priority 词表 / 状态受控词表（枚举校验） | F14 定义（F13 用自由整数 0-100 + 建议值清单，同 F9 relation_type / F10 category 处理） |
| 伏笔类别/标签体系（多对多标签、类别树） | Phase 2+——MVP 经 extra 预留（同 F10 §2.3 决策思路） |
| 回收位置结构化追踪（resolved_location 字段、回收章节绑定） | Phase 2+——MVP 回收说明写 description/extra（待澄清 Q3 建议答案） |
| 状态变更历史 / 伏笔变更审计日志 | F15 审计服务（Phase 2） |
| 伏笔回收提醒自动化（逾期未回收告警、按叙事位置提醒） | Phase 2+——MVP 靠 F6 注入「全部 open 伏笔」被动提醒 |
| 伏笔向量索引 / 语义检索（ADR-013 `foreshadowing` 实体类型） | F14/RAG 集成（Phase 2）——索引内容来自本模块伏笔档案，见 §11 |
| 拖拽排序 UI / 批量状态操作 | F18 Web UI（0.3.0 里程碑）；MVP 支持手动设置 priority 与逐条 resolve |
| 伏笔全文检索 | F22 搜索服务（Phase 3） |
| 伏笔可视化 / 导出 | F18 Web UI（0.3.0 里程碑）/ F21 导出服务（0.6.0） |
| 跨项目伏笔共享/引用 | Phase 4 云端 |

---

## 11. 依赖关系

与 F1 §11 / F9 §11 / F10 §11 / F11 §11 / F12 §11 已声明依赖保持一致（F13 在其上调整——**无 LLM 依赖、有 F6 数据源替换依赖**）：

```text
F13 依赖:
  F1 (project_service) ✅ — 项目存在性校验（404）
  F6 (context_service) ✅ — 上下文注入契约：ForeshadowingSource 替换（infrastructure/context/
                           sources.py 空实现 → 真实实现 + api/deps.py 装配注入 foreshadowing_repo）；
                           数据契约见 F6 spec §3.2（foreshadowing = dynamic 层）、§4.2/§4.5
                           （伏笔按 priority 降序、预算裁剪）
  F2 (chapter_service) — 边界声明（非硬依赖）：埋设位置用自由文本 location，
                          不绑定 F2 卷/章实体（§2.2）
  F12 (timeline_service) ✅ — **硬依赖**：① timeline_events 表（ForeshadowingORM.event_id
                          FK→timeline_events.id ON DELETE SET NULL，F12 表须已存在）；
                          ② TimelineRepositoryProtocol.get 事件校验（存在性 + 同项目，
                          §2.1/§3.4）。**F12 须先合入 main**，F13 实现前 rebase 最新 main。
                          F12 spec §11 声明「F13 实施时确认」→ 本 spec 确认结论：
                          **伏笔挂 F12 事件（event_id），已纳入 MVP**（用户拍板 Q1=选项 C，
                          §2.2/§12/待澄清 Q1）
  F5 (llm_service)     — 不依赖：F13 无 LLM（状态追踪为确定性逻辑、注入文本为确定性模板，§5）；
                           domain/ 零 LangChain import 门禁天然满足

F13 被依赖:
  F7 (CLI)             ✅ — foreshadowing 命令组并入 F7 命令树（cli/app.py 注册）
  F14 (统一提取)        ⏳ — (#44) 伏笔 AI 提取/回收自动检测归 F14（章节文本 → 伏笔埋设/兑现）；
                            复用本模块实体/状态/priority 约定（status/resolved_at/resolved 迁移）
  F15 (审计)            ⏳ — (Issue 待创建) 伏笔状态与变更作为 4 维度一致性审计数据源之一
                            （P1-07：角色/时间线/世界/伏笔）
  F16 (风格/一致性)      ⏳ — (Phase 2) 跨模块一致性审计输入之一
  F20 (MCP)             ⏳ — (Phase 3) manage_foreshadowing 工具基于本模块 API
  ADR-013 (RAG)         ⏳ — (Phase 2) foreshadowing 作为向量索引实体类型（写作涉及未回收伏笔时检索），
                            索引内容来自本模块伏笔档案
```

> ⚠️ **编号口径说明**: F6 spec §3.2/§10 与 `infrastructure/context/sources.py` 中 ForeshadowingSource 注释「F14 伏笔管理数据源」、`domain/models/context.py` 中「空实现 (F14 Phase 2)」均为 **ADR-019 之前的旧编号**（旧口径 F14=伏笔）；按 [ADR-019](../../adr/ADR-019.md) 现行口径 **F13 = 伏笔管理**、F14 = 统一提取。本 spec 及后续 F 模块一律以 ADR-019 为准（与 F9/F10/F12 spec §11 同一声明）。F13 实施时同步更新 sources.py 模块 docstring 中的旧编号注释。

> 与 F9/F10/F11/F12 的依赖面差异：F11 依赖 F1+F5（生成需要 LLM）、F12 仅依赖 F1；**F13 依赖 F1+F6（数据源替换）+F12（事件锚点硬依赖）**——是创作工具链中首个「实体模块 + 自带上下文集成 + 跨模块实体引用」的组合依赖面。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| 单实体建模 | Foreshadowing（项目级伏笔档案），**无第二张实体表** | PRD P1-05「埋设/回收追踪」是单档案生命周期管理；伏笔类别/标签/关系均非 MVP 核心结构（同 F10「分类用字段不建表、MVP 不建关联表」决策思路，见 §10） |
| 唯一约束 | partial unique index `(project_id, title WHERE is_deleted = 0)`，同名创建 422 | 伏笔是**档案**而非实例：一条伏笔一个生命周期，「林晚的身世」只应有一条档案（防手误重复建档 + 为 F14 提取提供合并锚点）；软删除后可重建同名；**与 F12 的对比**：时间线事件是实例（多「回忆」事件合法）故无唯一约束，伏笔的「同名 = 同一伏笔」语义决定必须唯一（§2.3 论证表） |
| 状态机 | **两态 open/resolved + 软删除**，迁移走专用动作端点（resolve/reopen） | 「埋设/回收追踪」验收标准的直接表达；专用端点保证迁移规则单一入口、可校验（同 restore 先例）；**dropped 论证**：废弃与软删除在注入/追踪语义上完全等价（都不注入、档案保留、可恢复），软删除 + 同名重建已覆盖「作废后重埋」场景，独立第三态徒增端点与测试面（P5 YAGNI）；F15 需要区分「废弃/删除」变更记录时 Phase 2+ 再加 |
| 位置表达 | 自由文本 `location` + **event_id 事件锚点**（v1.1，用户拍板 Q1=选项 C）；**移除独立 `narrative_position`** | 伏笔落点与 F12 时间线联动，叙事位置从事件获取（单一真相）；v1.0 的 narrative_position 与 F12 事件字段构成**双份真相**（改事件叙事位置时伏笔侧漂移）故移除（YAGNI）；location 保留自由文本兜底（不挂事件仍可写「第 3 章」）；F2 章节 FK 维持否决（§2.2 论证表） |
| event_id 引用方式 | **DB 级 FK ON DELETE SET NULL + 服务层校验** | ① 引用完整性由 DB 兜底：事件硬删（force）→ 伏笔 event_id 自动置 None（挂接解除），项目硬删 → 伏笔/事件各自 FK CASCADE（无悬挂引用）；② 服务层校验提供友好 422（「事件不存在」/「事件不属于该项目」），DB FK 仅作并发/硬删窗口兜底；③ SQLite 需 PRAGMA foreign_keys=ON——已由 F10/F12 测试基建覆盖（in-memory SQLite 连接开启），无新增基建成本；④ 备选逻辑引用（无 FK）：事件硬删后伏笔 event_id 悬挂，服务层每次查询需检测无效锚点（额外查询 + 状态不一致窗口），收益仅为「免 PRAGMA 依赖」，不值（否决） |
| 事件校验职责 | **Service 层复用 F12 `TimelineRepositoryProtocol.get`**（构造注入 timeline_repo），校验存在性 + `event.project_id` 相等 → 422 | F12 已实现该 Protocol（真实代码 `domain/ports/timeline_repository.py`，get 不含软删事件），F13 仓储**无新增方法**（避免两套事件查询逻辑）；F6 注入链路不跨模块（ForeshadowingSource 只注入 foreshadowing_repo，事件软删不影响注入，§5.3）；错误类 `EventNotFoundError` / `EventNotInProjectError`（§3.4） |
| priority 字段 | int 0-100 默认 50（大者先注入） | F6 dynamic 层排序契约的键（F6 spec §4.2「伏笔条目按 priority 降序」）；无 priority 字段则 F6 无法对伏笔排序、注入顺序不可控 |
| F6 集成归属 | **ForeshadowingSource 真实实现纳入 F13 里程碑**（MODIFY sources.py + deps.py） | 验收标准 2「写作时注入伏笔提示」的**实证路径**——不替换则验收标准无法演示；与 F9/F10 的差异：F9/F10 的注入非 PRD 验收标准，替换归 0.2.0 联调（Q1 先例），F13 的注入是验收标准本体（待澄清 Q2 确认） |
| 注入范围 | **全部 open 伏笔 + priority 降序**，由 F6 dynamic 层按预算裁剪 | 伏笔量级小（≤ 数十条），全量候选 + 预算裁剪已保证不超窗口，加阈值过滤是重复裁剪逻辑（YAGNI）；低优先级伏笔恰恰最易被忘；F6 dropped 记录已提供裁剪可观测性（§5.4 论证） |
| 注入文本 | 确定性模板拼接（`_render_reminder` 纯函数），无 LLM 无模板文件 | 伏笔提醒是结构化数据的文本投影，确定性可测试；LLM 加工（如「把伏笔融入剧情建议」）归 F14（§10） |
| 回收动作 | 专用端点 `resolve` / `reopen`（POST，落库副作用） | 显式状态迁移（同 restore 先例）；PATCH 不承载 status（防任意跳转）；动作端点幂等（重复 resolve/reopen 无毒，同 F12 restore 未删除语义） |
| resolved_at | 只读副产物字段：resolve 自动设置、reopen 清空、不接受外部写入 | 回收时间的唯一真相来源；避免「状态与时间戳不一致」的双份真相 |
| 端点布局 | 创建/列表嵌套项目路径，详情/更新/删除/动作扁平（同 F2/F9/F10/F12） | 与既有端点风格一致，OpenAPI 分组清晰；`/foreshadowings` 下全静态路径段，无路径歧义（F10 extract 处理不适用） |
| CLI 布局 | `inkflow foreshadowing` 顶级组 8 个扁平命令（无子组） | 单实体模块（同 F10 world 组 / F12 timeline 组布局）；避免顶级命令膨胀；resolve/reopen 人类可读输出 + `--json` 完整对象 |
| 更新清除语义 | `event_id`/`location` 用 `""` 清除（None = 不修改） | 与 F10 category、F11 arc_id、F12 time_value 的既有约定同构（event_id 的 `uuid | str | None` 型与 F11 arc_id 完全同构）；None 与 "" 双语义解决「可空字段无法表达清除」的 Pydantic 更新难题 |
| 无 LLM 错误面 | 错误码仅 NOT_FOUND / VALIDATION_ERROR / DB_ERROR（无 LLM_ERROR） | 同 F12：无 LLM 模块错误面最小；比 F12 多两类错误——同名冲突（唯一约束的必然结果，§2.3）与事件校验（event_id 跨模块引用，§3.4） |
| CLI 测试归属 | `tests/cli/test_cli_foreshadowing.py`（顶层 tests/cli/，Issue #61 迁移后布局）+ ci.yml `integration-cli-backend` job 显式列出 | 新增 CLI 测试文件默认是 CI 盲区（Issue #59 实测）；显式文件列表是既有 job 风格（Windows 下 pytest 不展开 glob，陷阱 15） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 领域模型 + DTO 验证（状态枚举/priority/event_id 锚点与清除语义） | `pytest tests/unit/test_foreshadowing_models.py -v` 全绿 |
| M2 | 仓储层全部方法（单实体 CRUD + partial unique + list_open + status 过滤） | `pytest tests/unit/test_foreshadowing_repo.py -v` 全绿 |
| M3 | 服务层 CRUD + 业务校验（同名 422/事件校验 422（不存在/跨项目）/状态机迁移/resolved_at 维护/404 全路径） | `pytest tests/unit/test_foreshadowing_service.py -v` 全绿 |
| M4 | F6 数据源替换（ForeshadowingSource：ContextItem 构造/priority 透传/空数据/排序） | `pytest tests/unit/test_foreshadowing_source.py -v` 全绿 |
| M5 | API 8 端点 + 错误路径全绿 | `pytest tests/unit/test_foreshadowing_api.py -v` 全绿 |
| M6 | CLI foreshadowing 组（信封/退出码/确认交互/resolve-reopen 输出）；**ci.yml `integration-cli-backend` job 显式列出 `tests/cli/test_cli_foreshadowing.py`** | `pytest tests/cli/test_cli_foreshadowing.py -v` 全绿 + CI job 覆盖确认（Issue #59/#61 教训） |
| M7 | 手工验证闭环：建伏笔挂 F12 事件 → 写作注入 → 回收 → 不再注入 | 手工验证（`inkflow timeline create` 建事件 → `inkflow foreshadowing create --event-id <事件> ...` 建 2+ 伏笔（其中 ≥1 条挂接事件）→ `inkflow write next --show-context` 看到「## 伏笔：XXX」分段且按 priority 排序 → `resolve` 一条 → 再写作该条不再出现；F6 dynamic 预算充足时全部 open 注入） |
| M8 | 全量回归 + 覆盖率 + lint/type | `pytest -v` 全绿；F13 模块行覆盖 ≥ 80%、全仓 ≥ 60%（0.2.0 DoD）；ruff + mypy 通过（CI 门禁 ADR-017）；domain/ 零框架 import（ADR-002/015） |

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | ~~伏笔的「埋设/回收位置」如何表达？~~ **✅ 已确认（用户拍板：选项 C）**：伏笔绑定 F12 时间线事件（event_id 锚点）；移除独立 `narrative_position`（事件自带叙事位置，单一真相）；F12 升级为硬依赖（须先合入 main） | — | 本 spec 已按选项 C 修订：§2.1/§2.2/§3/§5/§11/§12；F12 §11「F13 实施时确认」闭环 = **伏笔挂 F12 事件（event_id），已纳入 MVP** |
| Q2 | ~~F6 `ForeshadowingSource` 空实现（`infrastructure/context/sources.py`）与 `api/deps.py` 装配的替换是否纳入 F13 里程碑？~~ **✅ 已确认（用户拍板：纳入 F13）**：F6 数据源替换纳入本模块——与 F9/F10 先例的差异在于 F13 的注入是 PRD 验收标准 2 本体（F10 的注入非验收标准）；不纳入则验收标准无法实证 | — | 本 spec 已按「纳入」设计：§5.3/§8/§13；M7 手工验证含完整写作注入闭环 |
| Q3 | ~~F6 注入范围：MVP 注入**全部 open 伏笔**（priority 降序，F6 预算层裁剪）；是否需要**仅高优先级**（如 priority ≥ 阈值）或**按叙事位置过滤**？~~ **✅ 已确认（用户拍板：选项 A）**：MVP 注入全部 open 伏笔 + priority 降序 | — | 本 spec 已按选项 A 设计：§5.4 注入范围论证（量级小 + 预算裁剪兜底 + 低优先级最易被忘 + dropped 可观测）；按章节/叙事位置过滤归 Phase 2+（叙事位置数据走 F12 事件，§5.3） |

---

*本文档为 F13 功能规格（What），实施步骤（How）见后续 `specs/f13-foreshadowing/plan.md`。所有里程碑验收以本节 M1-M8 为准。*
