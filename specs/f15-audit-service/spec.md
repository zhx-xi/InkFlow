# F15: 一致性审计服务 (audit_service) — 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-02 | **依据**: PRD v2.1 §6.2 P1-07, Constitution P1-P6, ADR-012/018/019
> **所属阶段**: Phase 2 — 创作工具链（0.2.0 里程碑**第七个**模块，估算 3-5 人天）
> **关联 Issues**: [#45](https://github.com/zhx-xi/InkFlow/issues/45)
> **依赖**: F1 ✅（项目存在性校验）；F2 ✅（章节读取——事件 `source_chapter_id` 跨模块引用校验 + 提取缺口对照）；F9 ✅（角色/关系/分组档案读取）；F10 ✅（世界条目读取）；F12 ✅（事件档案读取 + **委托 `TimelineService.check_consistency`** 时间线维度）；F13 ✅（伏笔档案读取 + `event_id` 锚点校验）；F14 ✅（`extraction_runs` 状态读取）；F5 — **不依赖**（F15 无 LLM，见 §1/§5）
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md) (模块化单体), [ADR-002](../../adr/ADR-002.md) (六边形分层), [ADR-003](../../adr/ADR-003.md) (Repository), [ADR-004](../../adr/ADR-004.md) (Pydantic v2), [ADR-007v2](../../adr/ADR-007v2.md) (包结构), [ADR-012](../../adr/ADR-012.md) (错误处理), [ADR-016](../../adr/ADR-016.md) (loguru), [ADR-017](../../adr/ADR-017.md) (CI 门禁), [ADR-018](../../adr/ADR-018.md) (测试分层), [ADR-019](../../adr/ADR-019.md) (版本里程碑)
> **状态**: ✅ 已实现（PR #74）

---

## 1. 概述

对项目内**角色 / 时间线 / 世界 / 伏笔 4 个维度**做**一致性审计**：以确定性规则扫描各模块档案（角色关系/分组引用、时间线双线一致性、世界档案健康度、伏笔事件锚点与状态机、跨维度引用联动、F14 提取缺口），汇总输出一份 **AuditReport 审计报告**（summary + findings）。审计是**当前数据快照的只读计算**——不落库、不修改任何数据（验收标准 ①「4 维度一致性检查」+ ②「可生成审计报告」的直接表达）。

**核心价值**: 长篇小说创作的数据分散在 F9-F13 五套档案里，作者与 AI Agent 需要一个「一键体检」入口：哪些角色关系引用了已删除的角色、时间线有没有未声明的倒叙、伏笔是否挂了已软删的事件、状态与时间戳是否矛盾、F14 增量提取有没有失败/漏跑的章节——一次调用全部暴露，修完再跑即收敛。**与 F12 双线检查的区别**: F12 只查时间线**内部**；F15 查**全部档案 + 档案之间的跨模块引用**（F14 引入的 `source_chapter_id` → F2 章节、F13 的 `event_id` → F12 事件，正是长篇小说最容易出现悬挂引用的地方）。

**与 F9-F14 样板的关系（关键差异——本模块是「横切审计型」：F12 确定性检查型与 F14 横切收敛门面型的杂交）**: F9/F10 沉淀「实体 + AI 提取」，F11 演进为「实体 + AI 生成」，F12 演进为「实体 + 确定性检查（无 LLM）」，F13 演进为「实体 + 状态追踪 + F6 注入（无 LLM）」，F14 演进为「横切收敛门面（无新实体 + 增量 + RAG）」；**F15 不再新建任何业务实体表，也不新增任何 LLM 管线**——它是**只读聚合**：继承 F12 的「纯内存确定性计算、严格幂等、无副作用、可快照断言」（§5），继承 F14 的「跨模块读取、门面式依赖注入」（§5.1/§8），两者叠加出「对 4 维档案做一次性一致性体检」的横切能力：

```text
F9/F10 提取:  章节文本(text) ──LLM──▶ 结构化实体 ──合并落库──▶ 实体档案
F11  生成:    项目设定/约束(prompt) ──LLM──▶ 结构化大纲 ──新建落库──▶ 大纲规划
F12  检查:    事件档案(双时间维度) ──确定性算法──▶ 双线视图 + 冲突报告
F13  追踪:    伏笔档案(状态机) ──确定性追踪──▶ 状态流转
F14  门面:    6 种类型 ──分发──▶ 既有管线 + 增量提取 + RAG 索引（不建新档案）

F15  审计:    4 维档案(角色/时间线/世界/伏笔) + 跨模块引用 ──确定性规则──▶ AuditReport
               ├─ 角色:    关系 from/to 引用完整性 + 分组 group_id 引用完整性（R-C1/R-C2）
               ├─ 时间线:  委托 F12 check_consistency 双线一致性（R-T1，不重写算法）
               ├─ 世界:    条目内容健康度 + 档案缺口提示（R-W1/R-W2）
               ├─ 伏笔:    event_id 锚点存在性 + status/resolved_at 状态机一致性（R-F1/R-F2）
               └─ 跨维度:  事件 source_chapter_id → F2 章节 + F14 extraction_runs 缺口（R-X1/R-X2）
```

**复用** 各模块的既有读取能力：`CharacterRepositoryProtocol`（含 `list_relations(project_id)` 全量关系查询）、`WorldRepositoryProtocol.list`、`ForeshadowingRepositoryProtocol.list`、`ChapterRepositoryProtocol.list_chapters`、`ExtractionRunRepositoryProtocol.list`（F14）——F15 服务层构造注入这些 Protocol 与 F12 `TimelineService`（委托 `view()`/`check_consistency()`，**不重写双线检查算法**，同 F14 门面「注入各模块 Service/仓储、不复制逻辑」的先例）；软删集合（既有查询不可见的 `is_deleted=1` 数据）经 **F15 自有补充查询端口** `AuditRepositoryProtocol` 获取（§8.2）。**无跨模块 MODIFY**：所有数据读取走既有 Protocol 方法（角色/世界/伏笔用分页循环取全量，零新增方法，论证见 §5.1/§12）。

**边界声明**:
- F15 **不建新实体表**（无 audit_reports 表）：审计是「当前数据快照的只读计算」，输出内存中的 AuditReport；**审计历史落库/多次运行轨迹对比归 Phase 2+**（见 §10）
- F15 **无 LLM、无 RAG**：所有检查规则是确定性算法（镜像 F12 §5 的模式）；domain/ 零 LangChain import 门禁天然满足；无模板、无重试、无解析、无合并
- F15 **不修复数据**：发现的问题由作者经各模块 CRUD/动作端点修正后重跑审计（无副作用——镜像 F12 check「无副作用」要点）
- F15 的**时间线维度 = 汇总 F12 报告**：委托 `TimelineService.check_consistency`，将其 conflicts/flashbacks 转换为统一 findings，并在报告中嵌套原始 `ConsistencyReport` 供深挖（§5.3）
- F15 的**世界维度**是「档案健康度 + 缺口提示」级检查（世界条目无跨模块引用字段，检查内容论证见 §5.4/待澄清 Q2）
- F15 的 **F14 extraction_runs 缺口**为「状态可观测」级别：error 状态 run 报 warning、从未提取的章节报 info（完整逐章缺口对比归 Phase 2+，见 §5.5/待澄清 Q3）

---

## 2. 数据模型

F15 是横切审计型模块：**不新建任何业务实体表、不新建任何 ORM 模型**（YAGNI——审计报告是瞬态计算结果，不落库，见 §1/§10/§12）；领域层新增一组**纯 Pydantic 报告模型**（AuditDimension / AuditSeverity / AuditFinding / DimensionSummary / AuditSummary / AuditReport），全部可序列化（`model_dump(mode="json")` 直接进 API/CLI 信封）。领域层 id 为 UUID，数据库 int 自增映射的约定对本模块不适用（无表）。**引用** F12 `ConsistencyReport`（`domain/models/timeline.py` 已定义）作为时间线维度的嵌套原始报告——引用不重定义（同 F14 引用 `VectorStoreProtocol` 先例，§2.4）。

### 2.1 AuditDimension / AuditSeverity（枚举）

```python
class AuditDimension(StrEnum):
    """审计维度（PRD P1-07 验收标准 ① 的 4 维度 + 跨维度联动）."""

    CHARACTER = "character"        # 角色（关系/分组引用完整性）
    TIMELINE = "timeline"          # 时间线（委托 F12 双线一致性）
    WORLD = "world"                # 世界（档案健康度 + 缺口）
    FORESHADOWING = "foreshadowing"  # 伏笔（event_id 锚点 + 状态机）
    CROSS = "cross"                # 跨维度联动（事件→章节、提取缺口）


class AuditSeverity(StrEnum):
    """严重级别（§6.2 语义）."""

    ERROR = "error"      # 引用断裂 / 状态矛盾 —— 数据不一致，需修正
    WARNING = "warning"  # 软删引用 / 可恢复异常 —— 数据一致但值得注意
    INFO = "info"        # 缺口 / 健康度提示 —— 不涉及一致性
```

> **为什么 CROSS 独立成维度**: 事件 `source_chapter_id`（F12 实体 → F2 章节）与 extraction_runs 缺口（F14 记录 → F2 章节）都是**跨模块引用**，不属于任何单一档案维度；独立维度让 summary 按「4 档案维度 + 跨维度」组织，验收标准 ① 的 4 维度计数可直接从 `by_dimension` 读取（cross 额外计）。

### 2.2 AuditFinding（单条审计发现）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | str | **稳定键** `f"{rule_id}:{entity_key}"`（快照断言/去重锚点；entity_key = 实体 UUID 字符串，时间线冲突对 = `"{prev_id}:{next_id}"`，run 缺口 = source_key） |
| rule_id | str | 规则标识（如 `character.relation_ref`；完整清单见 §5.2） |
| dimension | AuditDimension | 所属维度（由 rule_id 决定，冗余存储便于过滤） |
| severity | AuditSeverity | 严重级别（规则固定级别，§5.2 表） |
| message | str | 人类可读描述（含修正建议，如「关系 林晚→?? 的 to 端指向不存在的角色」） |
| entity_type | str | 违规主体类型（`character`/`relation`/`group`/`world_setting`/`event`/`foreshadowing`/`chapter`/`run`） |
| entity_id | uuid.UUID? | 违规主体 id（run 缺口无 UUID → None，id 字段承载） |
| entity_name | str | 违规主体名称（标题/姓名/条目名；无名称场景用 id 短串） |
| ref_type | str? | 引用目标类型（悬空/软删场景：`character`/`group`/`event`/`chapter`） |
| ref_id | uuid.UUID? | 引用目标 id（如悬空的 to_character_id） |
| data | dict[str, Any] | 附加上下文（时间线冲突对快照、run 状态等；§5 各规则明细） |

### 2.3 AuditReport / AuditSummary（审计报告）

```python
class DimensionSummary(BaseModel):
    """单维度发现计数."""

    error: int = 0
    warning: int = 0
    info: int = 0


class AuditSummary(BaseModel):
    """审计汇总 — consistent 仅由 error 级 findings 决定（§6.2）."""

    consistent: bool                      # error 级 findings 为空
    total: int                            # findings 总数
    by_dimension: dict[AuditDimension, DimensionSummary]  # 5 维度计数
    counts: dict[str, int]                # 档案规模观测: 角色/关系/分组/条目/事件/伏笔/章节/runs 计数


class AuditReport(BaseModel):
    """审计报告（§5.1 编排输出）— 只读计算的瞬态结果，不落库."""

    project_id: uuid.UUID
    generated_at: datetime                # UTC
    summary: AuditSummary
    findings: list[AuditFinding]          # 按 (dimension 序, severity 序, entity_name) 稳定排序（§6.3）
    timeline_check: ConsistencyReport | None  # F12 原始报告嵌套（时间线维度深挖；无事件/委托失败为 None 的语义见 §5.3）
```

**字段表（AuditSummary.counts）**:

| 键 | 含义 | 数据源 |
|----|------|--------|
| characters | 活动角色数 | CharacterRepositoryProtocol.list 分页循环 |
| relations | 活动关系数 | CharacterRepositoryProtocol.list_relations（全量） |
| groups | 活动分组数 | CharacterRepositoryProtocol.list_groups（全量） |
| world_settings | 活动世界条目数 | WorldRepositoryProtocol.list 分页循环 |
| events | 活动事件数 | TimelineService.view().narrative_order |
| foreshadowings | 活动伏笔数 | ForeshadowingRepositoryProtocol.list 分页循环 |
| chapters | 活动章节数 | ChapterRepositoryProtocol.list_chapters 分页循环 |
| extraction_runs | run 记录数 | ExtractionRunRepositoryProtocol.list 分页循环 |

> **counts 的设计意图**: 报告不止报「问题」，也报「档案规模」——作者一眼看到「关系 3 条 / 事件 12 个 / 伏笔 5 条」即可判断审计覆盖面；`extraction_runs` 计数让「从未跑过提取」的项目（counts=0）与「跑过但失败」的项目（run error → warning）可区分（§5.5）。计算成本与规则扫描共享同一次全量读取（§5.1 步骤 ②——不重复查询）。

### 2.4 引用 F12 ConsistencyReport（不重定义 — 已存在）

`backend/src/inkflow/domain/models/timeline.py` 已定义完整报告模型，F15 **原样引用**（`AuditReport.timeline_check` 字段类型）：

| 定义 | 内容 | F15 用途 |
|------|------|----------|
| `ConsistencyReport` | project_id / checked / skipped / consistent / conflicts / flashbacks / event_timeline / narrative_order | 时间线维度嵌套原始报告（§5.3） |
| `TimelineConflict` | conflict_type（order_conflict/flashback/flashforward）/ prev / next / message | 转换 findings 的输入（§5.3 转换表） |
| `TimelineEventRef` | id / title / time_value / time_display / narrative_position / timeline_flag | 冲突对快照（写入 finding.data，§5.3） |

> **不重定义原则（同 F14 §2.4）**: F12 的检查算法与报告模型是单一真相，F15 委托 `TimelineService.check_consistency` 获得 `ConsistencyReport` 后只做**转换**（conflicts/flashbacks → findings）与**嵌套透传**，不复制模型、不重算算法。

### 2.5 领域模型代码（Pydantic v2 语法）

```python
# domain/models/audit.py
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from inkflow.domain.models.timeline import ConsistencyReport  # F12 已定义，引用不重定义（§2.4）


class AuditDimension(StrEnum):
    """审计维度（§2.1）."""

    CHARACTER = "character"
    TIMELINE = "timeline"
    WORLD = "world"
    FORESHADOWING = "foreshadowing"
    CROSS = "cross"


class AuditSeverity(StrEnum):
    """严重级别（§2.1/§6.2）."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class AuditFinding(BaseModel):
    """单条审计发现（§2.2）— id 为稳定键，供快照断言与去重."""

    id: str
    rule_id: str
    dimension: AuditDimension
    severity: AuditSeverity
    message: str
    entity_type: str
    entity_id: uuid.UUID | None = None
    entity_name: str = ""
    ref_type: str | None = None
    ref_id: uuid.UUID | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class DimensionSummary(BaseModel):
    """单维度发现计数（§2.3）."""

    error: int = 0
    warning: int = 0
    info: int = 0


class AuditSummary(BaseModel):
    """审计汇总（§2.3）— consistent 仅由 error 级 findings 决定."""

    consistent: bool
    total: int
    by_dimension: dict[AuditDimension, DimensionSummary] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)


class AuditReport(BaseModel):
    """审计报告（§2.3）— 只读计算的瞬态结果，不落库."""

    project_id: uuid.UUID
    generated_at: datetime
    summary: AuditSummary
    findings: list[AuditFinding] = Field(default_factory=list)
    timeline_check: ConsistencyReport | None = None
```

> 报告模型全部为纯 Pydantic 输出模型（无 `from_attributes` 需求——不映射 ORM）；`model_dump(mode="json")` 直接进 API 响应与 CLI `--json` 信封（同 F12 ConsistencyReport 序列化先例）。

### 2.6 报告模型决策论证表

| 备选方案 | 优点 | 缺点 | 结论 |
|----------|------|------|------|
| **纯内存瞬态报告 + findings 列表（选定）** | 报告由数据即时推导，永不「过期」；无存储/查询/清理逻辑；快照断言直接对返回值 | 无历史轨迹（多次运行对比需自己存 JSON） | ✅ MVP（审计是快照计算，§1/§12） |
| 落库 audit_reports 表（报告 + 快照 JSON） | 有历史可回溯 | 报告过期问题（数据变报告旧）；表结构/查询/清理三块设计；超出 3-5 人天 | ❌ 否决（归 Phase 2+，§10） |
| **单报告模型 AuditReport（选定）** | 一个端点一次返回全部（体检心智）；summary + findings + 嵌套 timeline_check 三层结构覆盖摘要/明细/深挖 | 无（findings 量级 ≤ 数百） | ✅ 选定（§2.3） |
| 每维度独立端点/独立报告 | 按需拉取 | 5 次往返；「整体一致性」无法一次判断；验收标准 ②「生成审计报告」是单数报告 | ❌ 否决（YAGNI） |
| **三级严重级别 error/warning/info（选定）** | 与各模块软删语义对齐（软删引用 = warning 而非 error）；consistent 语义清晰（仅 error 决定） | 级别语义需文档化（§6.2） | ✅ 选定（§6.2/§12） |
| 两级（error/info） | 模型更简 | 软删引用（合法但值得注意）无处安放——要么误报 error 要么降级 info 丢失提示价值 | ❌ 否决（§5.4 软删语义论证） |
| **finding.id 稳定键（选定）** | 快照断言/去重锚点；未来增量对比（Phase 2+ 历史归档）的基础 | 无 | ✅ 选定（§2.2/§6.3） |
| finding 无 id | 模型更简 | 无法断言「同一条 finding 是否再次出现」；快照测试需整体比对 | ❌ 否决（确定性测试是 F12 继承的验收基线，§9） |

---

## 3. API 契约

端点风格沿用既有约定：**审计是项目级只读计算**，嵌套项目路径；**用 GET 而非 POST**——镜像 F12 `GET /api/v1/projects/{project_id}/timeline/check` 先例（幂等只读计算无副作用，GET 语义正确且可缓存，F12 §12 论证）。错误响应格式沿用 F1/F2/F9-F14（`{"detail": "..."}` 404/500）。

### 3.1 端点总览（1 个）

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| GET | `/api/v1/projects/{project_id}/audit` | 4 维度一致性审计（只读幂等，无副作用） | — | 200 + AuditReport |

> **无查询参数（YAGNI）**: 审计报告是「全量体检」，findings 量级 ≤ 数百，一次性返回（同 F12 check 全量返回先例）；维度/级别过滤让调用方在客户端做（`--json` 后过滤成本为零）。`/audit` 为静态路径段，与既有路由无歧义（无 `{resource_id}` 兄弟段，同 F14 `/extract` 扁平先例）。

### 3.2 请求/响应示例

**审计一个存在不一致的项目**:
```http
GET /api/v1/projects/3f2e1d4a-.../audit
```
→ 200
```json
{
  "project_id": "3f2e1d4a-...",
  "generated_at": "2026-08-02T12:00:00Z",
  "summary": {
    "consistent": false,
    "total": 5,
    "by_dimension": {
      "character": {"error": 1, "warning": 1, "info": 0},
      "timeline": {"error": 1, "warning": 0, "info": 0},
      "world": {"error": 0, "warning": 0, "info": 1},
      "foreshadowing": {"error": 0, "warning": 1, "info": 0},
      "cross": {"error": 0, "warning": 0, "info": 0}
    },
    "counts": {
      "characters": 3, "relations": 2, "groups": 1,
      "world_settings": 4, "events": 6, "foreshadowings": 2,
      "chapters": 3, "extraction_runs": 5
    }
  },
  "findings": [
    {
      "id": "character.relation_ref:7a4f2c91-...",
      "rule_id": "character.relation_ref",
      "dimension": "character",
      "severity": "error",
      "message": "关系 林晚→?? 的 to 端指向不存在的角色（悬空引用，请删除该关系或恢复目标角色）",
      "entity_type": "relation",
      "entity_id": "7a4f2c91-...",
      "entity_name": "林晚→??",
      "ref_type": "character",
      "ref_id": "11111111-1111-1111-1111-111111111111",
      "data": {"relation_type": "敌对", "from_character_id": "9b1c2d3e-..."}
    },
    {
      "id": "character.group_ref:5e6f7a8b-...",
      "rule_id": "character.group_ref",
      "dimension": "character",
      "severity": "warning",
      "message": "角色 沈砚 的分组引用指向已软删的分组（分组已删除但成员引用残留）",
      "entity_type": "character",
      "entity_id": "5e6f7a8b-...",
      "entity_name": "沈砚",
      "ref_type": "group",
      "ref_id": "c1d2e3f4-...",
      "data": {}
    },
    {
      "id": "timeline.dual_consistency:9b1c2d3e-...:4a5b6c7d-...",
      "rule_id": "timeline.dual_consistency",
      "dimension": "timeline",
      "severity": "error",
      "message": "未声明的倒叙: 叙事顺序中「林晚入宫」(时间 5.0) 之后是「外门往事」(时间 3.0)——时间倒流（可修正时间，或给后者加 flashback 标记）",
      "entity_type": "event",
      "entity_id": "9b1c2d3e-...",
      "entity_name": "林晚入宫",
      "ref_type": "event",
      "ref_id": "4a5b6c7d-...",
      "data": {
        "conflict_type": "order_conflict",
        "prev": {"id": "9b1c2d3e-...", "title": "林晚入宫", "time_value": 5.0, "time_display": "", "narrative_position": 1, "timeline_flag": ""},
        "next": {"id": "4a5b6c7d-...", "title": "外门往事", "time_value": 3.0, "time_display": "", "narrative_position": 2, "timeline_flag": ""}
      }
    },
    {
      "id": "world.archive_gap:3f2e1d4a-...",
      "rule_id": "world.archive_gap",
      "dimension": "world",
      "severity": "info",
      "message": "项目已有 3 个章节但尚未建立世界观档案（可运行 inkflow extract run --type setting 提取）",
      "entity_type": "project",
      "entity_id": "3f2e1d4a-...",
      "entity_name": "测试项目",
      "ref_type": null,
      "ref_id": null,
      "data": {}
    },
    {
      "id": "foreshadowing.event_anchor:1a2b3c4d-...",
      "rule_id": "foreshadowing.event_anchor",
      "dimension": "foreshadowing",
      "severity": "warning",
      "message": "伏笔「铜镜的秘密」锚点事件已软删（锚点保留但事件不在时间线视图中，请确认是否需解除挂接）",
      "entity_type": "foreshadowing",
      "entity_id": "1a2b3c4d-...",
      "entity_name": "铜镜的秘密",
      "ref_type": "event",
      "ref_id": "8e9f0a1b-...",
      "data": {}
    }
  ],
  "timeline_check": {
    "project_id": "3f2e1d4a-...",
    "checked": 6,
    "skipped": 0,
    "consistent": false,
    "conflicts": [
      {
        "conflict_type": "order_conflict",
        "prev": {"id": "9b1c2d3e-...", "title": "林晚入宫", "time_value": 5.0, "time_display": "", "narrative_position": 1, "timeline_flag": ""},
        "next": {"id": "4a5b6c7d-...", "title": "外门往事", "time_value": 3.0, "time_display": "", "narrative_position": 2, "timeline_flag": ""},
        "message": "叙事顺序中「林晚入宫」之后是「外门往事」，但世界内时间 5.0 > 3.0——时间倒流（未声明倒叙）"
      }
    ],
    "flashbacks": [],
    "event_timeline": [],
    "narrative_order": []
  }
}
```

**审计一个完全一致的项目**:
```http
GET /api/v1/projects/3f2e1d4a-.../audit
```
→ 200（summary.consistent=true，findings 仅含 info/warning 级或无）
```json
{
  "project_id": "3f2e1d4a-...",
  "generated_at": "2026-08-02T12:00:00Z",
  "summary": {
    "consistent": true,
    "total": 0,
    "by_dimension": {
      "character": {"error": 0, "warning": 0, "info": 0},
      "timeline": {"error": 0, "warning": 0, "info": 0},
      "world": {"error": 0, "warning": 0, "info": 0},
      "foreshadowing": {"error": 0, "warning": 0, "info": 0},
      "cross": {"error": 0, "warning": 0, "info": 0}
    },
    "counts": {"characters": 0, "relations": 0, "groups": 0, "world_settings": 0,
               "events": 0, "foreshadowings": 0, "chapters": 0, "extraction_runs": 0}
  },
  "findings": [],
  "timeline_check": {
    "project_id": "3f2e1d4a-...",
    "checked": 0, "skipped": 0, "consistent": true,
    "conflicts": [], "flashbacks": [],
    "event_timeline": [], "narrative_order": []
  }
}
```

**项目不存在**:
```http
GET /api/v1/projects/00000000-0000-0000-0000-000000000000/audit
```
→ 404 `{"detail": "项目不存在"}`

### 3.3 错误响应格式（沿用 F1/F2/F9-F14/ADR-012）

```json
// 404 — 资源不存在
{"detail": "项目不存在"}

// 500 — DB 读取失败（loguru 记录）
{"detail": "内部错误: ..."}
```

**异常映射表**:

| 异常/场景 | 状态码 | 响应 |
|-----------|--------|------|
| 项目不存在（`ProjectRepositoryProtocol.get` → None，服务层统一校验） | 404 | `{"detail": "项目不存在"}` |
| 无效 UUID 格式（project_id 路径参数） | 404 | 统一解析失败处理（同 F9-F14 `_parse_id`） |
| 任一档案仓储读取失败（DB 错误） | 500 | 全局处理器（loguru，ADR-012/016） |
| 委托 F12 `check_consistency` 内部失败（项目已校验，理论不可达；仓储异常） | 500 | 全局处理器（loguru） |

> **与 F9-F14 的差异**: F15 是**无输入校验错误面**的模块（唯一参数是路径 project_id，无请求体、无查询参数）——错误面只有 404（项目/无效 UUID）与 500（DB）；无 422 业务校验错误、无 LLM 错误、无提取/生成错误（同 F12 无 LLM 错误面，且比 F12 更小——F12 有字段校验 422，F15 无输入字段）。

---

## 4. CLI 命令签名

遵循 F7 §5 全局约定：`--json` 统一信封 `{"ok": true, "data": ...}` / `{"ok": false, "error": {"code", "message"}}`；退出码 0/1/2/130；错误码 NOT_FOUND / **DB_ERROR**（**无 LLM_ERROR、无 VALIDATION_ERROR**——F15 无 LLM、无输入校验失败场景）。`audit` 组在 F15 落地时并入 F7 命令树（`cli/app.py` 注册，同 F12 timeline 组 / F14 extract 组）。

### 4.1 audit 组（只读审计入口）

```bash
inkflow audit check --project-id <uuid> [--json]
    # 对项目执行 4 维度一致性审计，输出人类可读摘要（或 --json 完整 AuditReport）
    # 只读幂等：不修改任何数据，可重复执行（同 F12 timeline check）
    # 退出码恒 0（成功执行；发现不一致是「结果」而非「执行错误」——Q1 论证见 §12/待澄清 Q1）
```

### 4.2 输出格式

```bash
# 默认人类可读 — 一致
✅ 审计通过 (project 3f2e1d4a-...): 0 error / 1 warning / 2 info（角色 3 · 关系 2 · 事件 6 · 伏笔 2 · 条目 4 · 章节 3）

# 默认人类可读 — 发现不一致
🔍 审计完成 (project 3f2e1d4a-...): ❌ 不一致（3 error / 2 warning / 1 info）
  [error] 角色: 关系 林晚→?? 的 to 端指向不存在的角色（悬空引用）
  [error] 时间线: 未声明的倒叙「林晚入宫」(5.0) →「外门往事」(3.0)
  [error] 伏笔: 「身世之谜」status=resolved 但 resolved_at 为空
  [warning] 角色: 角色 沈砚 的分组引用指向已软删的分组
  [warning] 伏笔: 「铜镜的秘密」锚点事件已软删
  [info] 世界: 项目已有 3 个章节但尚未建立世界观档案
  （共 6 条发现；完整报告见 inkflow audit check --json）

# --json 输出（完整 AuditReport）
inkflow audit check --project-id 3f2e1d4a-... --json
→ {"ok": true, "data": {"project_id": "3f2e1d4a-...", "generated_at": "...",
   "summary": {"consistent": false, "total": 6, "by_dimension": {...}, "counts": {...}},
   "findings": [...], "timeline_check": {...}}}

inkflow audit check --project-id 00000000-0000-0000-0000-000000000000 --json
→ {"ok": false, "error": {"code": "NOT_FOUND", "message": "项目不存在"}}  # 退出码 1
```

> **人类可读摘要规则**: 第一行永远给出 `consistent` 结论（✅ 审计通过 / ❌ 不一致）+ 三级计数；`error` 与 `warning` 级逐条列出（`[级别] 维度: 消息`），`info` 级只计数不逐条（避免噪音，`--json` 有全部）；最后一行提示 `--json` 获取完整报告（有 findings 时）。

---

## 5. 审计规则引擎（横切审计核心）

> ⚠️ **本节是 F15 与 F9-F14 样板的核心差异点**：F9/F10 的 §5 是「AI 提取管线」，F11 的 §5 是「AI 生成管线」，F12 的 §5 是「单一档案一致性检查算法」，F13 的 §5 是「状态机 + F6 注入」，F14 的 §5 是「门面分发 + 增量 + RAG」；本模块的 §5 是**跨 4 档案 + 跨模块引用的确定性规则引擎**——不设计新管线、不新建实体，而是**读取各模块档案 + 委托 F12 检查 + 逐规则扫描**。算法性质完全继承 F12：纯内存、严格幂等、无副作用、可快照断言（§5.1 要点）。

### 5.1 模式总览（编排 + 规则注册表）

```text
 ┌────────────────────────────────────────────────────────────┐
 │ 输入: AuditService.run_audit(project_id)                    │
 └───────────────────────────┬────────────────────────────────┘
                             ▼
 ① 校验项目存在（ProjectRepositoryProtocol.get → None → 404「项目不存在」）
 ② 全量读取（一次会话内完成，§5.1 要点 4）:
    ├─ F9  角色 list 分页循环 + 关系 list_relations 全量 + 分组 list_groups 全量
    ├─ F10 世界条目 list 分页循环
    ├─ F12 委托 TimelineService.view()（全量事件，narrative_order 视图）
    ├─ F13 伏笔 list 分页循环（全部状态）
    ├─ F2  章节 list_chapters 分页循环（仅需 id 列表 + 计数）
    └─ F14 run 记录 list 分页循环（全部类型）
 ③ 规则引擎（§5.2 注册表，按维度顺序执行，纯内存）:
    ├─ character:    R-C1 关系引用完整性 / R-C2 分组引用完整性
    ├─ timeline:     R-T1 委托 F12 check_consistency → 转换 findings
    ├─ world:        R-W1 条目内容健康度 / R-W2 档案缺口
    ├─ foreshadowing: R-F1 event_id 锚点存在性 / R-F2 status-resolved_at 一致性
    └─ cross:        R-X1 事件 source_chapter_id → F2 章节 / R-X2 提取 run 缺口
 ④ 汇总（AuditSummary: by_dimension 计数 + counts 档案规模，§2.3）
 ⑤ 排序（dimension 序 → severity 序 → entity_name，§6.3）→ 返回 AuditReport
```

**模式要点**:
1. **零业务逻辑复制**：所有档案读取走各模块既有 Protocol（F9-F14 已实现）；时间线检查委托 F12 `TimelineService.check_consistency`（不重写算法）；F15 只做「读取 + 规则扫描 + 汇总」——同 F14 门面「不复制管线」的先例
2. **项目校验单一入口**：服务层统一校验一次（404）；委托 F12 时其内部会再次校验（幂等，成本可忽略——保持 F12 不感知 F15，同 F14 要点 2）
3. **规则全确定性**：每条规则是纯函数（输入 = 快照数据集，输出 = findings 列表），同一数据永远得到同一报告（快照断言友好，同 F12 §5 要点 1）
4. **单次全量读取**：所有规则共享步骤 ② 的数据快照（角色/关系/分组/条目/事件/伏笔/章节/runs），**不逐规则重复查询**——审计是低频操作（量级 ≤ 数百条记录），一次读取 + 内存扫描总成本毫秒级
5. **全量读取策略 = 分页循环（零跨模块 MODIFY）**：F9/F10/F13 的 Protocol 只有分页 `list`（limit ≤ 100），F15 在服务层循环拉取（offset += 100 直到不足一页）；F12 事件走 `TimelineService.view()`（全量）；F9 关系/分组已有全量方法（`list_relations(project_id)` / `list_groups(project_id)`）直接用。**不给 F9/F10/F13 加 `list_all` 方法**——为审计给 5 个模块加方法违背 YAGNI，分页循环成本可忽略（论证见 §12）
6. **失败即异常（ADR-012）**：任一仓储读取失败 → 抛异常（router 转 500）；不吞错、不产出「部分报告」（审计报告必须完整，部分结果会误导）
7. **无副作用**：审计不修改任何数据；修正动作由作者经各模块 CRUD/动作端点执行后重跑（同 F12 要点 4）

**编排伪代码（run_audit 与两条规则示例——其余规则同构，§5.4/§5.5）**:

```python
async def run_audit(self, project_id: uuid.UUID) -> AuditReport:
    """4 维度一致性审计编排（spec §5.1 步骤 ①-⑤）."""
    project = await self._project_repo.get(_to_int_id(project_id))
    if project is None:
        raise ProjectNotFoundError()                     # ① 项目校验（404）
    # ② 单次全量读取（分页循环，§5.1 要点 4/5）
    chars, rels, groups = await self._load_characters(project_id)      # list 分页 + list_relations + list_groups
    worlds = await self._load_worlds(project_id)                       # list 分页循环
    events, deleted_events = await self._load_events(project_id)       # view().narrative_order + audit_repo 软删事件集合
    fores = await self._load_foreshadowings(project_id)                # list 分页循环
    chapters = await self._load_chapters(project_id)                   # list_chapters 分页循环
    runs = await self._load_runs(project_id)                           # run_repo.list 分页循环
    deleted_chars, deleted_groups = await self._audit_repo.list_deleted(project_id.int)  # 软删集合（§5.1 注）
    # ③ 规则引擎（按维度序执行，全部纯内存）
    findings: list[AuditFinding] = []
    findings += self._audit_character(chars, rels, groups, deleted_chars, deleted_groups)  # R-C1/R-C2
    timeline_check = await self._timeline_service.check_consistency(project_id)  # R-T1 委托 F12
    findings += self._audit_timeline(timeline_check)                   # 转换（§5.3）
    findings += self._audit_world(worlds, len(chapters))               # R-W1/R-W2
    findings += self._audit_foreshadowing(fores, events, deleted_events)  # R-F1/R-F2
    findings += self._audit_cross(events, chapters, runs)              # R-X1/R-X2
    # ④ 汇总 + ⑤ 排序（§6.3）
    summary = self._summarize(findings, counts={...})                  # consistent 仅由 error 决定
    return AuditReport(project_id=project_id, generated_at=datetime.now(UTC),
                       summary=summary,
                       findings=sorted(findings, key=_finding_sort_key),
                       timeline_check=timeline_check)

def _audit_character(self, chars, rels, groups, deleted_chars, deleted_groups) -> list[AuditFinding]:
    """R-C1 关系引用完整性 + R-C2 分组引用完整性（纯函数，可单测）."""
    active = {c.id for c in chars}
    deleted = set(deleted_chars)
    findings = []
    for r in rels:                             # list_relations 全量（F9 已提供）
        for end, label in ((r.from_character_id, "from"), (r.to_character_id, "to")):
            if end in active:
                continue
            if end in deleted:
                findings.append(AuditFinding(...severity=WARNING...))  # 软删 → warning
            else:
                findings.append(AuditFinding(...severity=ERROR...))    # 悬空 → error
    ...
    return findings
```

> **注（软删集合的数据来源 — F15 自有补充查询）**: 各模块既有 Protocol 查询**默认不含软删**（`list`/`list_relations`/`list_groups`/`view` 语义均为活动数据，见各 Protocol docstring）——而审计的「软删 → warning」分级（R-C1/R-C2/R-F1）需要**软删集合**。既有模块**没有**只读的软删列表方法（`restore` 会改数据、`get` 不含软删，均不可用），因此 F15 新建**自有补充查询端口** `domain/ports/audit_repository.py`（`AuditRepositoryProtocol`，§8.2）并由 `infrastructure/database/repositories/audit_repo.py` 实现（SQLAlchemy 直接对 characters / character_groups / timeline_events 表查 `is_deleted=1`，只读、按 project_id 过滤）——**零跨模块 MODIFY**：不改动任何既有 Protocol/仓储，软删集合查询是审计特有的读取需求，由 F15 自己的 port + 实现承载（依赖方向合法：domain/ports → infrastructure 实现）。F2 章节**无软删概念**（硬删除，§5.5 注），R-X1 不需要软删章节集合。

### 5.2 规则注册表（8 条规则）

| 规则 | rule_id | 维度 | 严重级别 | 数据源 | 判定条件（违规即产出 finding） |
|------|---------|------|----------|--------|-------------------------------|
| 关系引用完整性 | `character.relation_ref` | character | error / warning | F9 关系 + 角色 + audit_repo 软删集合 | 活动关系的 from/to 端指向：**软删角色** → warning；**不存在**（DB 级悬空）→ error |
| 分组引用完整性 | `character.group_ref` | character | error / warning | F9 角色 + 分组 + audit_repo 软删集合 | 活动角色的 group_id 指向：**软删分组** → warning；**不存在** → error |
| 时间线双线一致性 | `timeline.dual_consistency` | timeline | error / info | F12 ConsistencyReport | 委托 F12：order_conflict → error；flashback/flashforward → info（已声明合法）；无冲突 → 无 finding |
| 世界条目内容健康度 | `world.entry_content` | world | info | F10 条目 | 活动条目 content 为空（仅名称无描述）→ info |
| 世界档案缺口 | `world.archive_gap` | world | info | F2 章节 + F10 条目 | 项目有 ≥ 1 个活动章节且 0 个活动世界条目 → info |
| 伏笔事件锚点 | `foreshadowing.event_anchor` | foreshadowing | error / warning | F13 伏笔 + F12 事件 + audit_repo 软删集合 | 活动伏笔的 event_id 指向：**软删事件** → warning（F13 语义：软删不影响锚点，审计提示）；**不存在** → error |
| 伏笔状态机一致性 | `foreshadowing.status_time` | foreshadowing | error | F13 伏笔 | status=resolved 且 resolved_at=None → error；status=open 且 resolved_at≠None → error |
| 事件来源章节 | `timeline.source_chapter` | cross | error | F12 事件 + F2 章节 | 活动事件的 source_chapter_id 指向**不存在的章节** → error（F2 章节为硬删除、F14 FK ON DELETE SET NULL 应置 None——残留即异常数据） |
| 提取 run 缺口 | `extraction.run_gap` | cross | warning / info | F14 run + F2 章节 | run.status=error → warning「提取失败」；活动章节从未有任何 run 记录 → info「从未提取」 |

> **规则集规模论证（MVP 可交付范围内）**: 8 条规则覆盖 PRD 4 维度 + 跨维度联动，每条规则都有明确的判定条件、报告条目类型、严重级别（验收标准 ① 的实证路径）；规则量级控制在 3-5 人天估算内——**每增加一条规则 ≈ 规则函数 + 测试用例 × 3-5**，候选但未纳入的规则（角色名相似度提示、世界类别受控词表、伏笔长期未回收提醒等）见 §10 与 §12。

### 5.3 时间线维度（R-T1 — 委托 F12，不重写算法）

**委托路径**: `TimelineService.check_consistency(project_id, include_flashbacks=True)`（F12 §5，确定性相邻对扫描）→ 返回 `ConsistencyReport`。F15 **不复制扫描算法**，只做**转换**：

| ConsistencyReport 元素 | 转换结果 | 严重级别 | finding.data |
|------------------------|----------|----------|--------------|
| `conflicts[]`（order_conflict） | 每条 → 1 条 finding（rule_id=`timeline.dual_consistency`） | **error** | `{"conflict_type": "order_conflict", "prev": {...TimelineEventRef}, "next": {...TimelineEventRef}}` |
| `flashbacks[]`（flashback/flashforward） | 每条 → 1 条 finding（同 rule_id） | **info**（已声明合法，不破坏 consistent） | 同上（conflict_type 原样） |
| `checked` / `skipped` | 无 finding（观测数据进 timeline_check 嵌套报告） | — | — |
| `consistent=true` | 无 finding | — | — |

**finding 定位字段**（时间线冲突对是「两事件」而非「单实体」）: `entity_type="event"`、`entity_id=prev.id`（叙事靠前者）、`entity_name=prev.title`、`ref_type="event"`、`ref_id=next.id`；finding.id = `timeline.dual_consistency:{prev_id}:{next_id}`（稳定键含两端）。

**嵌套原始报告**: `AuditReport.timeline_check = ConsistencyReport`（原样透传，含 event_timeline/narrative_order 视图）——作者需要时间线深挖时不用再调 F12 端点；`summary.consistent` **不**由 timeline_check.consistent 单独决定，而是由全部 error findings 决定（时间线 error 转换后自然计入，语义统一）。

**边界语义（与 F12 一致，透传不重算）**: 0/1 个事件 → 无 finding；全部时间未知 → checked=0、skipped=n、无 finding；未声明逆序 → error；已声明 flashback/flashforward → info（合法叙事手法不是错误，F12 §5.4）。

### 5.4 角色 / 世界 / 伏笔维度规则明细

**R-C1 关系引用完整性**（`character.relation_ref`）:

```text
输入: 活动关系列表 R + 活动角色 id 集合 C_active + 软删角色 id 集合 C_deleted（来自 audit_repo，§5.1 注）
对每条 r ∈ R:
  对端 ∈ {r.from_character_id, r.to_character_id}:
    ├─ 对端 ∈ C_active        → 通过
    ├─ 对端 ∈ C_deleted       → warning「关系 {from}→{to} 的 {端} 指向已软删的角色」
    │                            （F9 语义: 角色软删会级联软删其关系——正常路径不可达，
    │                              残留即历史数据/硬删窗口异常，提示作者确认）
    └─ 对端 ∉ C_active ∪ C_deleted → error「关系 {from}→{to} 的 {端} 指向不存在的角色（悬空引用）」
```

**R-C2 分组引用完整性**（`character.group_ref`）:

```text
输入: 活动角色列表 C + 活动分组 id 集合 G_active + 软删分组 id 集合 G_deleted（来自 audit_repo，§5.1 注）
对每条 c ∈ C（group_id 非 None）:
  ├─ group_id ∈ G_active  → 通过
  ├─ group_id ∈ G_deleted → warning「角色 {name} 的分组引用指向已软删的分组」
  │                          （F9 语义: 软删分组时成员 group_id 置 NULL——正常路径不可达，残留即异常）
  └─ group_id ∉ G_active ∪ G_deleted → error「角色 {name} 的分组引用指向不存在的分组（悬空引用）」
```

**R-W1 世界条目内容健康度**（`world.entry_content`）:

```text
输入: 活动世界条目列表 W
对每条 w ∈ W: w.content 为空（strip 后为空串）→ info「条目 {name} 缺少内容描述（仅有名称）」
```

**R-W2 世界档案缺口**（`world.archive_gap`）:

```text
输入: 活动章节数 n_chapters + 活动世界条目数 n_world
n_chapters ≥ 1 且 n_world == 0 → info「项目已有 {n} 个章节但尚未建立世界观档案」
```

**R-F1 伏笔事件锚点**（`foreshadowing.event_anchor`）:

```text
输入: 活动伏笔列表 F + 活动事件 id 集合 E_active + 软删事件 id 集合 E_deleted（来自 audit_repo，§5.1 注）
对每条 f ∈ F（event_id 非 None）:
  ├─ event_id ∈ E_active  → 通过
  ├─ event_id ∈ E_deleted → warning「伏笔 {title} 锚点事件已软删」
  │                          （F13 语义: 事件软删不影响伏笔 event_id 锚点——锚点保留、注入 metadata
  │                            原样携带；审计提示作者该事件已不在时间线视图中，确认是否需解除挂接）
  └─ event_id ∉ E_active ∪ E_deleted → error「伏笔 {title} 锚点事件不存在（悬空锚点）」
```

**R-F2 伏笔状态机一致性**（`foreshadowing.status_time`）:

```text
输入: 活动伏笔列表 F
对每条 f ∈ F:
  ├─ f.status == resolved 且 f.resolved_at is None → error
  │    「伏笔 {title} 状态为 resolved 但 resolved_at 为空（状态与时间戳矛盾）」
  └─ f.status == open 且 f.resolved_at is not None → error
       「伏笔 {title} 状态为 open 但存在 resolved_at（状态与时间戳矛盾）」
```

> **软删引用语义与 F9-F14 各 spec 一致（关键设计）**: ① 软删实体的引用**不是 error**——各模块的软删语义本就允许「记录保留、引用保留」（F13: 事件软删不影响伏笔锚点），审计报 **warning** 提示作者注意；② 只有**硬删/异常数据导致的悬空**（目标在活动集合与软删集合中都不存在）才报 **error**——正常业务路径下 F9/F13/F14 的 FK ON DELETE SET NULL / 级联删除会阻止悬空产生（F2 章节为**硬删除**，事件 `source_chapter_id` 在章节删除时被 FK SET NULL 置 None，故 R-X1 只有 error 档、无软删分支，§5.5 注），error 级意味着「数据已处于异常状态」（历史迁移、手工 DB 操作、并发窗口），需要人工修复；③ 该分级与各模块 spec 的删除语义一一对应（F9 §2.4 级联软删、F13 §2.1 锚点保留、F14 §2.6 章节联动（按 F2 实际语义：章节硬删 → SET NULL）），审计不引入新语义。

### 5.5 跨维度联动规则明细（R-X1 / R-X2）

**R-X1 事件来源章节**（`timeline.source_chapter` — F14 引入的跨模块引用）:

```text
输入: 活动事件列表 E（含 source_chapter_id）+ 活动章节 id 集合 CH_active
对每条 e ∈ E（source_chapter_id 非 None）:
  ├─ source_chapter_id ∈ CH_active → 通过
  └─ source_chapter_id ∉ CH_active → error
       「事件 {title} 的来源章节不存在（悬空来源；F2 章节为硬删除、F14 FK ON DELETE SET NULL
         在章节删除时应将 source_chapter_id 置 None——残留即异常数据）」
```

> **注（F2 章节无软删概念 — 与 F14 spec 措辞的差异）**: F14 spec §2.6 曾写「章节**软删** → 事件保留 source_chapter_id（历史来源锚点）」——但 F2 章节的实际实现为**硬删除**（`ChapterRepositoryProtocol.delete_chapter` 物理删除，Chapter 领域模型与 chapters 表均无 `is_deleted` 列，见 F2 spec §3.2「DELETE ... 硬删除」与真实树 `domain/models/chapter.py`）；章节删除时 timeline_events 的 `source_chapter_id` FK（ON DELETE SET NULL，`infrastructure/database/models/timeline.py`）自动置 None、事件保留。**F15 以真实实现为准**：R-X1 只有「悬空 → error」一档（正常路径下 FK 已保证不悬空，残留即异常数据），无软删分支——审计不引入 F14 spec 措辞中不存在的「章节软删」概念。

**R-X2 提取 run 缺口**（`extraction.run_gap` — F14 extraction_runs 状态可观测）:

```text
输入: run 记录列表 RUN + 活动章节列表 CH（仅 id）+ 提取类型集合 TYPES = {character, setting, foreshadowing, timeline}
① status 观测: 对每条 r ∈ RUN:
    r.status == "error" → warning「提取失败: [{type}] 源 {source_key} — {error}（可重试）」
② 缺口观测: 对每条 c ∈ CH:
    c.id 不在任何 run 的 source_key 中（str(c.id) 比对）→ info「章节 {title} 从未执行过提取」
      （source_key="manual" 的 run 不参与章节比对）
```

> **为什么 MVP 只做「状态可观测」级（待澄清 Q3 建议答案）**: ① `run.status=error` 的失败行 → warning 是**零成本高价值**（F14 语义: 失败源不写 run，error 行是防御保留——见 F14 §6.2；真正的失败缺口 = 「有章节无 run」，即 ②）；② 「从未提取章节」按章节粒度提示（info，不噪音化）——完整缺口分析（按类型 × 章节矩阵、hash 过期判定、`timeline_auto_extract` 开关感知）归 Phase 2+（§10）；③ 章节量级 ≤ 数百，info 条数与章节数同量级可接受（信息本身有价值：作者知道哪些章还没沉淀进档案）。

### 5.6 审计规则引擎 vs 既有样板：差异对照表

| 维度 | F9/F10 提取（样板） | F12 检查（样板） | F14 门面（样板） | F15 审计（本模块） |
|------|--------------------|------------------|------------------|------------------|
| 建模对象 | 新实体档案 | 新实体档案（事件） | 无新实体（收敛既有） | **无新实体表（纯报告模型）** |
| 输入 | 章节文本（必填） | 事件档案（库内） | 统一 ExtractionRequest | **5 套档案快照 + F12 委托结果（库内）** |
| 引擎 | LLM 提取 | 确定性算法（单档案） | 编排（委托 + 增量 + RAG） | **确定性规则引擎（跨档案）** |
| 新增管线 | 1 条 | 0 | 2 条 | **0（无 LLM、无模板、无重试）** |
| 副作用 | 合并落库 | 无副作用 | 委托落库 + run upsert | **无副作用（只读）** |
| 幂等性 | 同文本空 diff | 严格幂等 | 增量判定 | **严格幂等（同数据同报告，快照断言）** |
| 落库 | 同名合并 | 无 | run 记录 | **无（审计历史归 Phase 2+，§10）** |
| 错误面 | LLM_ERROR + 提取错误 | 无 LLM | LLM/RAG/提取错误 | **仅 NOT_FOUND / DB_ERROR（最小错误面）** |
| 测试方式 | Mock LLM 分支 | 快照断言 | Mock 各模块 Service | **Mock 各模块仓储 + Mock TimelineService，快照断言** |
| 跨模块 | F6 替换归联调 | 无 | 委托 5 模块 + MODIFY F12 | **读取 6 模块 + 委托 F12，零跨模块 MODIFY**（软删集合走自有 audit_repo，§8.2） |

---

## 6. 审计组织规则

（对应 F12 §6「事件与双线语义/时间线组织规则」、F14 §6「类型注册表」的位置；F15 无实体，本节承载维度组织、严重级别语义、报告排序与规则注册约定）

### 6.1 维度组织与规则归属

- **4 档案维度**（验收标准 ① 的 4 维度）+ **1 跨维度**（cross）——`AuditDimension` 枚举封闭（5 值）
- 每条规则**固定归属一个维度**（规则注册表 §5.2），rule_id 命名 = `{维度}.{规则短名}`（如 `character.relation_ref`）——维度过滤 = 规则过滤，无独立规则集配置（YAGNI）
- **规则注册表实现**（`audit_service.py` 内部）：规则按维度分组为私有方法（`_audit_character` / `_audit_timeline` / `_audit_world` / `_audit_foreshadowing` / `_audit_cross`），`run_audit` 依序调用——顺序固定保证输出稳定（快照断言）
- 执行顺序 = 维度枚举顺序（character → timeline → world → foreshadowing → cross）；**单条规则内部按数据源返回顺序扫描**（分页循环已保证稳定序：F9 list 默认 updated_at DESC、F12 view 按 narrative_position ASC、F13 list 默认 priority DESC——规则不重新排序输入，只产出 findings）

### 6.2 严重级别语义

| 级别 | 含义 | 对 consistent 的影响 | 典型场景 |
|------|------|---------------------|----------|
| **error** | 引用断裂 / 状态矛盾——数据不一致，**需修正** | **决定 consistent**（任一 error → consistent=false） | 悬空关系/分组/锚点、状态-时间戳矛盾、未声明时间倒流 |
| **warning** | 软删引用 / 可恢复异常——数据一致但值得注意 | 不影响 | 软删角色/分组/事件被引用、提取失败 run |
| **info** | 缺口 / 健康度提示——不涉及一致性 | 不影响 | 未建立档案、条目无内容、从未提取章节、已声明倒叙 |

- `summary.consistent = (error 级 findings 为空)`——**仅由 error 决定**（同 F12 `consistent = conflicts 为空` 的语义同构：warning/info 是提示不是错误）
- 级别由**规则固定**（§5.2 表），不随数据变化浮动（同一规则同一级别——可预测、可测试；「升级/降级」配置归 Phase 2+，YAGNI）

### 6.3 报告排序与去重

- **findings 排序**: `(dimension 枚举序, severity 序 error→warning→info, entity_name ASC, id ASC)`——完全确定性，快照断言友好；跨维度（cross）排最后
- **去重**: finding.id 为稳定键（§2.2），规则引擎保证同一次审计内 id 不重复（每条违规恰好一条 finding；时间线冲突对按 (prev_id, next_id) 唯一——F12 相邻对扫描天然无重复对）
- **同引用多主体不聚合**: 多条伏笔挂同一软删事件 → 每条伏笔各一条 finding（作者需要知道**哪条**伏笔受影响，逐条可操作）；不按引用目标聚合（聚合视图归 Phase 2+，§10）

### 6.4 审计触发与重复执行

- 审计是**手动触发**的只读计算（API/CLI），无自动触发/定时任务（归 F25 daemon，§10）
- **重复执行幂等**: 同一项目同一数据两次审计 → 报告逐字段相等（快照断言可证）；数据变更后重跑即反映新状态（无增量状态需要维护——同 F12 要点 3「增量友好」）
- 审计**不感知** F14 的 `timeline_auto_extract` 设置项（时间线维度永远委托 F12 检查——审计检查的是「档案现状」而非「提取配置」，设置项语义归 F14 §2.6）

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 项目不存在 | 404: "项目不存在"（服务层统一校验，§5.1 步骤 ①） |
| 无效 UUID 格式（project_id） | 404（统一 `_parse_id` 处理，同 F9-F14） |
| 空项目（无任何档案/章节） | 200：consistent=true，findings 空，counts 全 0，timeline_check 空报告（checked=0） |
| 有章节无任何档案（角色/世界/伏笔/事件均 0） | 200：R-W2 info「未建立世界观档案」+ R-X2 info「章节从未提取」（×章节数）；consistent=true（无 error） |
| 0 / 1 个时间线事件 | R-T1 无 finding（F12 语义: 空/单事件时间线无矛盾可言） |
| 全部事件时间未知 | R-T1 无 finding（checked=0、skipped=n，透传嵌套报告） |
| 关系引用已软删角色 | R-C1 warning（F9 级联软删语义下正常路径不可达——角色软删级联软删关系，残留即异常，提示确认） |
| 关系引用不存在的角色（悬空） | R-C1 error（目标不在活动 ∪ 软删集合） |
| 角色 group_id 指向软删/不存在的分组 | R-C2 warning / error（F9 语义: 软删分组时成员 group_id 置 NULL——残留即异常） |
| 伏笔 event_id 指向软删事件 | R-F1 warning（F13 语义: 软删不影响锚点——锚点保留、注入原样携带；审计提示事件已不在视图） |
| 伏笔 event_id 指向不存在的事件（悬空） | R-F1 error（正常路径 F13 服务层校验 + FK SET NULL 会阻止，悬空即异常数据） |
| 伏笔 status=resolved 但 resolved_at 为空 | R-F2 error（状态与时间戳矛盾；正常路径 F13 resolve 动作端点自动设置 resolved_at，矛盾即异常数据） |
| 伏笔 status=open 但 resolved_at 非空 | R-F2 error（同上；reopen 会清空 resolved_at） |
| 事件 source_chapter_id 指向不存在的章节 | R-X1 error（F2 章节为硬删除、F14 FK ON DELETE SET NULL 在章节删除时应置 None——残留即异常数据；**无软删章节分支**，§5.5 注） |
| run 记录 status=error | R-X2 warning「提取失败（可重试）」（run.error 截断 ≤ 500 字符入 data） |
| 活动章节从未有任何 run 记录 | R-X2 info「章节从未提取」（source_key="manual" 的 run 不参与章节比对） |
| 章节分页循环拉取中途章节被删除 | 单用户本地工具无并发竞态（同 F9-F13）；快照以读取时刻为准（§5.1 要点 4） |
| 任一档案仓储读取失败（DB 错误） | 抛异常 → 500（全局处理器，loguru；不产出部分报告，§5.1 要点 6） |
| 委托 F12 check_consistency 抛异常 | 500（项目已校验，理论不可达；仓储异常透传） |
| 项目硬删除后残留引用 | 各表 FK CASCADE 已级联（F9-F14 均已配置）——审计不可见硬删项目；如残留（历史库）→ 各悬空规则 error 报告 |
| CLI 审计发现 error findings | 退出码 **0**（成功执行；发现问题是结果——Q1 论证见 §12/待澄清 Q1）；人类可读摘要显示 ❌ 不一致 |
| CLI 项目不存在 / 无效 UUID | 退出码 1 + NOT_FOUND 信封（同 F12 先例） |
| CLI --json 输出 | 完整 AuditReport（model_dump(mode="json")），信封 {"ok": true, "data": ...} |

---

## 8. 文件结构

遵循 ADR-007v2 包结构，与真实源码树一一对应。新增/修改文件（**对照主仓 `backend/src/inkflow/` 真实树逐文件核对**——F9-F14 已合入 main，本节声明全部基于现行树）：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── audit.py           ← CREATE: AuditDimension, AuditSeverity, AuditFinding,
│   │   │                            DimensionSummary, AuditSummary, AuditReport
│   │   │                            （引用 F12 ConsistencyReport，§2.4——不重定义）
│   │   └── __init__.py        ← MODIFY: 导出新模型
│   ├── ports/
│   │   ├── audit_errors.py    ← CREATE: AuditServiceError / ProjectNotFoundError（404）
│   │   ├── audit_repository.py ← CREATE: AuditRepositoryProtocol（软删集合补充查询，
│   │   │                            list_deleted(project_id) -> (软删角色 ids, 软删分组 ids,
│   │   │                            软删事件 ids)——§8.2；既有 Protocol 无只读软删查询，§5.1 注）
│   │   └── __init__.py        ← MODIFY: 导出
│   └── services/
│       ├── audit_service.py   ← CREATE: AuditService（run_audit 编排 + 8 条规则（§5.2）
│       │                            + 汇总 + 排序；构造注入 F1/F2/F9/F10/F13/F14 仓储
│       │                            Protocol + F12 TimelineService + AuditRepositoryProtocol
│       │                            ——只依赖 domain/ports/ 与 domain/services/，不依赖
│       │                            infrastructure 具体类）
│       └── __init__.py        ← MODIFY
├── infrastructure/
│   └── database/
│       └── repositories/
│           ├── audit_repo.py  ← CREATE: SQLiteAuditRepository（AuditRepositoryProtocol 实现：
│           │                        SQLAlchemy 只读查询 characters / character_groups /
│           │                        timeline_events 表 is_deleted=1，按 project_id 过滤；
│           │                        F15 自有实现，不 MODIFY 任何既有仓储）
│           └── __init__.py    ← MODIFY
├── api/
│   ├── routers/
│   │   ├── audit.py           ← CREATE: GET /api/v1/projects/{project_id}/audit
│   │   └── __init__.py        ← MODIFY
│   ├── deps.py                ← MODIFY: get_audit_service（复用既有 get_*_service /
│   │                                各 SQLite 仓储装配，见 §8.1）
│   └── app.py                 ← MODIFY: 注册 audit.router
└── cli/
    ├── commands/
    │   ├── audit.py           ← CREATE: audit 组（check 1 命令，人类可读摘要 + --json）
    │   └── __init__.py        ← MODIFY
    └── app.py                 ← MODIFY: 注册 audit 命令组
```

```text
backend/tests/unit/
├── test_audit_models.py       ← CREATE: 报告模型/DTO 校验（枚举/字段/序列化）
├── test_audit_repo.py         ← CREATE: SQLiteAuditRepository（in-memory SQLite：软删角色/
│                                    分组/事件集合查询、project_id 过滤、空结果、活动数据排除）
├── test_audit_service.py      ← CREATE: 规则引擎测试（Mock 各仓储 + Mock TimelineService +
│                                    Mock AuditRepositoryProtocol：
│                                    8 条规则全分支 + 分页循环 + 汇总 + 排序 + 确定性/快照断言）
└── test_audit_api.py          ← CREATE: API 集成（Mock AuditService，GET /audit）

tests/cli/
└── test_cli_audit.py          ← CREATE: CLI 测试（Mock AuditService，信封/退出码/摘要）
```

> **与 F12/F13 §8 的差异（测试布局）**: CLI 测试放顶层 `tests/cli/test_cli_audit.py`（Issue #61 后的现行布局，同 F13/F14）。**infrastructure/ 唯一新增** = `repositories/audit_repo.py`（软删集合补充查询，§5.1 注/§8.2——不建表、无 ORM 模型，只读查询既有表）；**无 `infrastructure/llm/templates/`**（无 LLM）。
>
> ⚠️ **CI 覆盖盲区防范（Issue #59/#61 教训）**: `tests/cli/test_cli_audit.py` **默认不被任何 CI job 收集**——实施时必须将其**显式加入 ci.yml `integration-cli-backend` job 的 pytest 文件列表**（与现有 14 个 `../tests/cli/test_cli_*.py` 并列，当前列表: project_mock/chapter_mock/write/output/serve/config/llm/character/world/outline/timeline/foreshadowing/extraction/vector；PowerShell 反引号续行、Windows 下 pytest 不展开 glob，须显式文件名——见 §9/§12）。`backend/tests/unit/` 新文件由 `unit-test-backend` job 的 `pytest tests/unit/` 自动覆盖（无需改 ci.yml）。

### 8.1 AuditService 构造与装配（镜像 F14 门面注入模式）

```python
# domain/services/audit_service.py
class AuditService:
    """一致性审计服务（spec §5）— 跨 4 档案的确定性规则引擎.

    依赖全部通过构造函数注入（ADR-015/ADR-009，测试注入 Mock）:
    - F1 ProjectRepositoryProtocol.get 项目校验（§5.1 步骤 ①）
    - F9 CharacterRepositoryProtocol（角色/分组/关系读取）
    - F10 WorldRepositoryProtocol（世界条目读取）
    - F12 TimelineService（view 全量事件 + check_consistency 委托，§5.3）
    - F13 ForeshadowingRepositoryProtocol（伏笔读取）
    - F2 ChapterRepositoryProtocol（章节读取——R-X1/R-X2/R-W2 数据源）
    - F14 ExtractionRunRepositoryProtocol（run 读取——R-X2 数据源）
    - AuditRepositoryProtocol（软删集合补充查询——R-C1/R-C2/R-F1 分级数据源，§8.2）

    只依赖 domain/ports/ 与 domain/services/（Protocol 与领域服务），
    不依赖任何 infrastructure 实现——domain/ 零框架 import 门禁天然满足（ADR-002/015）。
    """

    def __init__(
        self,
        project_repo: ProjectRepositoryProtocol,
        character_repo: CharacterRepositoryProtocol,
        world_repo: WorldRepositoryProtocol,
        timeline_service: TimelineService,
        foreshadowing_repo: ForeshadowingRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        run_repo: ExtractionRunRepositoryProtocol,
        audit_repo: AuditRepositoryProtocol,
    ) -> None: ...

    async def run_audit(self, project_id: uuid.UUID) -> AuditReport: ...
```

```python
# api/deps.py — MODIFY: 装配（复用既有 get_*_service 与 SQLite 仓储；唯一新增实现 audit_repo）
def get_audit_service(db: AsyncSession) -> AuditService:
    """获取 AuditService 实例（F15 审计服务，spec §5/§8）.

    装配: 复用 F9/F10/F13/F14/F2/F1 各 SQLite 仓储 + F12 TimelineService
    （get_timeline_service 先例）+ SQLiteAuditRepository（F15 自有软删集合
    查询实现，§8.2）——除 audit_repo 外全部为既有实现。
    """
    return AuditService(
        project_repo=SQLiteProjectRepository(db),
        character_repo=SQLiteCharacterRepository(db),
        world_repo=SQLiteWorldRepository(db),
        timeline_service=get_timeline_service(db),
        foreshadowing_repo=SQLiteForeshadowingRepository(db),
        chapter_repo=SQLiteChapterRepository(db),
        run_repo=SQLExtractionRunRepository(db),
        audit_repo=SQLiteAuditRepository(db),
    )
```

### 8.2 AuditRepositoryProtocol（F15 自有补充查询端口 — 软删集合）

```python
# domain/ports/audit_repository.py
class AuditRepositoryProtocol(Protocol):
    """审计软删集合补充查询端口（spec §5.1 注/§5.4）.

    各模块既有 Protocol 查询默认不含软删（list/list_relations/list_groups/
    view 均为活动数据），而审计的「软删 → warning」分级（R-C1/R-C2/R-F1）
    需要软删集合——本端口承载该审计特有读取需求，由 F15 自有实现
    （infrastructure/database/repositories/audit_repo.py）提供，不改动
    任何既有 Protocol/仓储（零跨模块 MODIFY）。

    注: F2 章节无软删概念（硬删除），本端口不提供章节软删查询（§5.5 注）。
    """

    async def list_deleted(
        self, project_id: int
    ) -> tuple[builtins.list[int], builtins.list[int], builtins.list[int]]:
        """列出项目内三类软删实体 id（角色 / 分组 / 事件）.

        Args:
            project_id: 项目主键（int，与 ORM 层一致）.

        Returns:
            (软删角色 ids, 软删分组 ids, 软删事件 ids) 三元组——
            分别来自 characters / character_groups / timeline_events 表的
            is_deleted=1 行（按 project_id 过滤）.
        """
        ...
```

> **为什么 audit_repo 是「F15 自己的 port」而非 MODIFY 既有 Protocol（论证）**: ① 软删集合查询是**审计特有的读取需求**——各模块业务 CRUD 不需要「列出软删实体」（`restore` 是单实体操作、`get` 排除软删），为审计给 F9/F12 加方法 = 扩大既有模块契约面；② F15 自有 port + 实现保持「零跨模块 MODIFY」的纯消费者定位（§11），新增代码全部收在 F15 文件清单内；③ 依赖方向合法：`domain/ports/audit_repository.py` 定义契约、`infrastructure/database/repositories/audit_repo.py` 实现（同其它仓储同构，ADR-002/003）；④ 测试简单：服务层 Mock 该 port、实现层 in-memory SQLite 集成测试（§9）。

> **不新增依赖**: F15 无 LLM、无 RAG、无新表——`backend/pyproject.toml` 与 `core/config.py` **零变更**（无新依赖、无新配置项；审计为只读计算，无阈值/开关类配置——规则常量写代码常量，YAGNI）。

---

## 9. 测试策略

### 测试层次（沿用 ADR-018 三层目录 + pytest markers；层次结构同 F12/F13 §9）

```text
单元测试: 报告模型/DTO 校验（枚举、字段、序列化）        ~8 cases
集成测试: SQLiteAuditRepository（in-memory SQLite，软删集合查询）~8 cases
服务测试: AuditService 规则引擎（Mock 各仓储 + Mock TimelineService +
          Mock AuditRepositoryProtocol）                   ~32 cases
API 测试: GET /audit（Mock AuditService）               ~6 cases
CLI 测试: audit 组（Mock AuditService）                 ~10 cases
```

### 关键测试场景

**报告模型**: AuditDimension 五值 / AuditSeverity 三值 / AuditFinding 默认值（entity_id/ref_type/ref_id/data 可空）/ AuditSummary 计数逻辑（by_dimension 缺省空字典）/ AuditReport 序列化（model_dump(mode="json") 全字段）/ ConsistencyReport 引用（timeline_check=None 与完整嵌套两态）

**仓储（SQLiteAuditRepository，in-memory SQLite）**: list_deleted 命中三类软删实体（角色/分组/事件，is_deleted=1）/ 活动实体（is_deleted=0）不返回 / 空项目 → 空三元组 / project_id 过滤（跨项目软删不可见）/ 无软删行 → 空列表 / 软删后 restore 的行不再出现 / 只读断言（查询不修改数据）

**规则引擎（Mock 各仓储 + Mock TimelineService + Mock AuditRepositoryProtocol，核心 ~32 cases）**:
- **R-C1 关系引用**: 两端均活动 → 无 finding / to 端软删 → warning（message 含「已软删」）/ from 端软删 → warning / to 端不存在 → error（悬空）/ from 端不存在 → error / 空关系列表 → 无 finding / 软删关系不进入检查（repo 语义——list_relations 不含软删）
- **R-C2 分组引用**: group_id 活动 → 无 finding / group_id 软删 → warning / group_id 不存在 → error / group_id=None（未分组）→ 跳过 / 空角色列表 → 无 finding
- **R-T1 时间线委托**: Mock check_consistency 返回含 2 条 order_conflict + 1 条 flashback 的报告 → 2 error + 1 info，转换字段正确（entity_id=prev.id、ref_id=next.id、data 含 prev/next 快照、id 稳定键）/ consistent=true 报告 → 无 finding / checked=0、skipped=n → 无 finding / **委托调用断言**: Mock check_consistency 被调用且收到 project_id（include_flashbacks=True 透传）/ **嵌套透传**: AuditReport.timeline_check == Mock 报告原样
- **R-W1 条目内容**: content 为空 → info / content 非空 → 无 finding / 空白串（"   "）→ info
- **R-W2 档案缺口**: 有章节（≥1）无条目 → info / 无章节 → 无 finding / 有条目 → 无 finding
- **R-F1 事件锚点**: event_id 活动 → 无 finding / event_id 软删 → warning（F13 语义验证）/ event_id 不存在 → error / event_id=None（未挂接）→ 跳过 / 软删伏笔不进入检查（repo 语义）
- **R-F2 状态机**: resolved+无 resolved_at → error / open+有 resolved_at → error / resolved+有 resolved_at → 无 finding / open+无 resolved_at → 无 finding
- **R-X1 来源章节**: source_chapter_id 活动 → 无 finding / 软删 → warning / 不存在 → error / None（手工事件）→ 跳过
- **R-X2 run 缺口**: run.status=error → warning（data 含 error 消息）/ 章节 id 在 run source_key 中 → 无 info / 章节 id 不在 → info / source_key="manual" 不参与章节比对 / 无 run → 全部章节 info / 无章节 → 无 finding
- **分页循环（Mock list 返回固定页）**: 角色 250 条（3 页）→ 循环拉全 250 / 世界 0 条 → 循环立即结束 / list 返回空页 → 终止（防死循环）
- **汇总与排序**: 混合 findings → by_dimension 计数正确（5 维度键齐全）/ consistent 仅由 error 决定（warning+info 不影响）/ 排序 (dimension 序, severity 序, entity_name) 断言 / counts 各键计数正确（共享同一次读取——Mock 调用次数断言）
- **项目校验**: project_repo.get → None → ProjectNotFoundError（404 语义）
- **确定性/快照**: 同一 Mock 数据集两次 run_audit → 报告逐字段相等（快照断言）
- **失败传播**: 某仓储 list 抛异常 → run_audit 抛异常（不产出部分报告）

**API（Mock AuditService）**: GET /audit 成功路径（完整 AuditReport 序列化）/ 404 项目不存在（Service 抛 ProjectNotFoundError）/ 无效 UUID → 404 / 500 透传（仓储 DB 错误）/ 幂等性（两次 GET 相同响应体）

**CLI（Mock AuditService）**: check 人类可读输出（✅ 审计通过 / 🔍 不一致两种摘要、error/warning 逐条、info 只计数）/ --json 完整报告信封 / 发现 error 时退出码 0（Q1 语义）/ 项目不存在 → NOT_FOUND 信封退出码 1 / DB_ERROR 信封 / 缺 --project-id → 退出码 2（Typer 必填参数）

### 覆盖率目标

- F15 模块行覆盖率 **≥ 80%**（8 条规则全分支、分页循环、汇总/排序全路径，同 F9-F14）
- 全仓覆盖率 **≥ 60%**（0.2.0 DoD，ADR-019）
- CI 门禁：ruff + mypy + pytest 全绿（ADR-017/018）；domain/ 零 FastAPI/Typer/SQLAlchemy/LangChain import（ADR-002/015——F15 无 LLM，天然满足）
- **CI 覆盖盲区防范**: `tests/cli/test_cli_audit.py` 必须显式加入 ci.yml `integration-cli-backend` job（Issue #59/#61 教训，见 §8 注记）——实施 PR 中 ci.yml 修改与测试文件同时合入
- **CI 无网络约束**: F15 无 LLM、无 RAG、无模型下载——**所有测试纯确定性、无 Fake 注入需求**（比 F14 更简单：F14 需 FakeEmbeddings，F15 连 Embeddings 都没有；Mock 各仓储返回内存数据即可）

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|----------|
| 审计历史落库（audit_reports 表、多次运行轨迹、变更回溯对比） | Phase 2+——本 spec 决策：审计是「当前数据快照的只读计算」，报告瞬态返回（§1/§12）；历史归档需报告存储/查询/对比三块设计，超出 3-5 人天估算（YAGNI）；F14 §10「extraction_runs 历史审计」同口径归此处确认 |
| 自动修复 / 一键修正（按报告批量改数据） | 本 spec 决策：审计只读无副作用（§5.1 要点 7）；修正走各模块 CRUD/动作端点（F12 §5 先例「修正动作由作者执行后重查」）；批量修正涉及跨模块写权限与撤销语义，归 Phase 2+ |
| 实体级字段 diff / 变更审计（「哪些字段在何时被谁改过」） | Phase 2+——需各模块变更日志表（F13 §10「状态变更历史」同口径）；审计是现状快照检查，不是变更追踪 |
| LLM 语义一致性检查（剧情逻辑漏洞、角色行为矛盾等主观判断） | 非确定性检查超出本模块性质（F15 镜像 F12 确定性先例）；语义级审阅属 F3 写作审阅能力/未来扩展，不在 PRD P1-07 验收范围 |
| 大纲维度审计（F11 大纲/情节点/弧线） | 本 spec 决策：PRD P1-07 验收标准 ① 明确「角色/时间线/世界/伏笔 4 维度」，不含大纲（§1） |
| 世界条目类别受控词表 / 类别一致性 | F14 定义受控词表（F10 §10 先例：F10 类别受控词表归 F14）；F15 世界维度只做健康度与缺口（§5.4/待澄清 Q2） |
| 伏笔长期未回收提醒（open 超 N 天/叙事位置超阈值） | Phase 2+——需「回收预期位置」数据（F13 §10「回收提醒自动化」同口径）；MVP 靠 F6 注入被动提醒 |
| 角色名相似度提示（疑似重复角色） | Phase 2+——字符串相似度是启发式规则（误报风险高），且 F9 partial unique 已防完全同名；语义级重复检测归未来 |
| 完整提取缺口矩阵（类型 × 章节、hash 过期判定、timeline_auto_extract 开关感知） | Phase 2+——MVP 只做「状态可观测」级（error run → warning、从未提取章节 → info，§5.5/待澄清 Q3） |
| 审计报告持久化 / 导出 / 分享 | F21 导出服务（0.6.0）/ F18 Web UI（0.3.0）——MVP 报告经 API/CLI 瞬态获取 |
| 审计定时任务 / daemon 自动审计 | F25 daemon（Phase 3）——MVP 手动触发（API/CLI，§6.4） |
| 审计可视化（维度仪表盘、趋势图） | F18 Web UI（0.3.0）——MVP 报告为结构化 JSON + 人类可读摘要 |
| 跨项目审计 / 全局审计（多项目一次跑） | 本 spec 决策：审计是项目级资源（GET 嵌套项目路径，§3）；跨项目批量审计归 CLI 脚本层（Phase 2+） |
| 审计结果接入 F6 上下文 / 写作链路 | Phase 2+ 联调——审计是「作者主动体检」工具，不自动干预写作（与 F13 注入的被动提醒不同） |

---

## 11. 依赖关系

与 F1 §11 / F9-F14 §11 已声明依赖保持一致（F15 在其上调整——**横切审计型依赖面：读取 6 模块 + 委托 F12，零跨模块 MODIFY、唯一新增基础设施 = audit_repo**）：

```text
F15 依赖:
  F1 (project_service) ✅ — 项目存在性校验（ProjectRepositoryProtocol.get，404，§5.1 步骤 ①）
  F2 (chapter_service) ✅ — 章节读取（ChapterRepositoryProtocol.list_chapters 分页循环：
                           R-X1 事件 source_chapter_id 存在性校验（悬空 → error，无软删分支——
                           F2 章节为硬删除，§5.5 注）、R-X2 提取缺口对照、R-W2 档案缺口判定、
                           counts.chapters）
  F9 (character_service) ✅ — 角色档案读取（CharacterRepositoryProtocol: list 分页循环 +
                           list_relations 全量 + list_groups 全量——R-C1/R-C2 + counts；
                           软删角色/分组集合经 F15 自有 audit_repo 查询，§5.1 注/§8.2）
  F10 (world_service)  ✅ — 世界条目读取（WorldRepositoryProtocol.list 分页循环——R-W1/R-W2 + counts）
  F12 (timeline_service) ✅ — ① 事件档案读取（TimelineService.view() 全量事件——R-X1 数据源；
                           软删事件集合经 audit_repo 查询——R-F1 分级，§5.1 注/§8.2）；
                           ② **委托 TimelineService.check_consistency**（R-T1 时间线维度，
                           不重写算法，§5.3）；③ ConsistencyReport 模型引用（§2.4）
  F13 (foreshadowing_service) ✅ — 伏笔档案读取（ForeshadowingRepositoryProtocol.list 分页循环
                           ——R-F1/R-F2 + counts）
  F14 (extraction_service) ✅ — extraction_runs 读取（ExtractionRunRepositoryProtocol.list
                           ——R-X2 状态可观测 + counts.extraction_runs）
  F5 (llm_service)     — 不依赖：F15 无 LLM（规则引擎为确定性算法，§5）；
                           domain/ 零 LangChain import 门禁天然满足
  F6 (context_service) — 不依赖：审计不注入上下文、不感知 F6 分层
  F11 (outline_service) — 不依赖：大纲维度不在 PRD 4 维度内（§10）
  F16 (style_service)  — 不依赖（F16 风格检测未动工，且与审计无交集）

F15 被依赖:
  F7 (CLI)             ✅ — audit 命令组并入 F7 命令树（cli/app.py 注册，§4）
  F16 (风格检测)        ⏳ — (Issue #46) F16 风格报告可与审计报告并列展示（0.2.0 联调期确认，
                           本 spec 不预设接口）
  F18 (Web UI)         ⏳ — (0.3.0) 审计可视化消费本模块 API（GET /audit）
  F20 (MCP)            ⏳ — (Phase 3) audit 工具基于本模块 API（PRD §6.4 工具列表含 audit）
  F3 (writing_service) ⏳ — (Phase 2+ 联调) 审计结果作为写作前自检的可选环节（§10）
```

> **零跨模块 MODIFY 声明（与 F13/F14 的差异）**: F13 跨模块 MODIFY F6 sources.py、F14 跨模块 MODIFY F12 事件实体——**F15 无任何跨模块 MODIFY**：所有数据读取走既有 Protocol 方法（分页循环取全量，§5.1 要点 5）+ F15 自有 `AuditRepositoryProtocol`（软删集合补充查询，§8.2），不新增任何字段/方法/表到既有模块；新增代码全部收在 F15 文件清单内（§8），是创作工具链中首个「纯消费者」模块（只读依赖面）。
>
> **编号口径**: F15 = 一致性审计、F16 = 风格检测（ADR-019 现行口径）；旧文档中「F16 一致性审计」字样（如 F13 spec §1/§10 的早期表述）均为 ADR-019 之前旧编号（实际 = F15），本 spec 及后续一律以 ADR-019 为准（同 F9/F10/F12/F13/F14 spec §11 声明）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| 模块类型 | **横切审计型**（F12 确定性检查 × F14 横切门面的杂交）：无 LLM、只读聚合、不建实体表 | PRD P1-07 验收标准 ①「4 维度一致性检查」是**跨档案检查**（非新档案），验收标准 ②「可生成审计报告」是**只读计算产物**（非新数据）；F12 已证明确定性检查模式（无 LLM、幂等、可快照），F14 已证明横切读取模式（门面注入、零重写）——两者叠加即 F15，无需发明新模式（§1） |
| 不建实体表 | AuditReport 为纯内存瞬态报告模型，无 audit_reports 表/ORM | 审计是「当前数据快照的只读计算」——报告由数据即时推导，落库即引入「报告过期」问题（数据变了报告旧了）；历史归档（多次运行对比）是独立需求，归 Phase 2+（§10）；P5 YAGNI |
| 依赖注入方式 | 构造注入各模块 **Repository Protocol** + F12 **TimelineService** + F15 自有 **AuditRepositoryProtocol**（镜像 F14 门面）；只依赖 domain/ports/ + domain/services/ | 各 Protocol 已由 F9-F14 定义（§8 引用不重定义）；注入仓储而非直接 SQL（ADR-003）；不依赖 infrastructure 使服务层可纯 Mock 测试（ADR-009/015）；委托 TimelineService 而非重写双线算法——F12 算法是单一真相（§5.3，同 F14 委托各 Service 先例）；软删集合查询由 F15 自有 port 承载（§8.2） |
| 全量读取策略 | **分页循环**（list limit=100 循环拉全量），不为 F9/F10/F13 加 list_all 方法 | 审计是低频只读操作（量级 ≤ 数百），分页循环成本毫秒级；给 3 个模块加全量方法 = 跨模块 MODIFY × 3 + 各模块测试面扩大，违背 YAGNI（备选「MODIFY 加 list_all」被否决，§5.1 要点 5）；F9 关系/分组已有全量方法（list_relations/list_groups）、F12 事件走 view() 全量——已覆盖大部分读取；软删集合（分页 list 不可见）走 F15 自有 audit_repo（下一行） |
| 软删集合查询 | **F15 自有 `AuditRepositoryProtocol` + `SQLiteAuditRepository`**（只读查 characters / character_groups / timeline_events 表 is_deleted=1，按 project_id 过滤） | 既有 Protocol 无只读软删列表方法（`get` 排除软删、`restore` 会改数据，均不可用）；软删集合是**审计特有**读取需求，F15 自有 port + 实现承载（§8.2）——零跨模块 MODIFY、依赖方向合法（ADR-002/003）；备选「MODIFY F9/F12 Protocol 加 list_deleted」扩大既有契约面、污染业务端口（否决，§8.2 论证） |
| 时间线维度 | **委托 F12 check_consistency**，conflicts/flashbacks → findings 转换 + 原始 ConsistencyReport 嵌套透传 | 双线检查算法（相邻对扫描、声明制）是 F12 的成熟能力与单一真相（F12 §5.3 完备性论证）；重写 = 双份算法真相 + 双份测试面；转换层（§5.3）是纯函数可单测；嵌套报告让深挖零往返 |
| 严重级别 | 三级 error/warning/info；**consistent 仅由 error 决定** | 与 F12「consistent = conflicts 为空」语义同构（已声明倒叙不影响一致性子）；软删引用与缺口是「注意」不是「错误」——各模块软删语义本就允许引用保留（F13 锚点保留），报 error 会误伤合法数据（§6.2） |
| 软删引用分级 | 软删目标 → warning；悬空（活动 ∪ 软删集合都不存在）→ error | 与 F9-F14 删除语义一一对应（§5.4 论证）：正常业务路径 FK SET NULL/级联删除阻止悬空，error = 异常数据；软删是合法状态，warning = 提示作者确认（§5.4 注）；**F2 章节无软删概念**（硬删除 + FK SET NULL），R-X1 只有 error 档（§5.5 注） |
| API 形态 | `GET /api/v1/projects/{project_id}/audit`（只读幂等，无查询参数） | 镜像 F12 `GET .../timeline/check` 先例（无副作用 → GET 语义正确、可缓存，F12 §12 论证）；审计是项目级资源嵌套项目路径（§3）；无过滤参数——报告量级 ≤ 数百，全量返回 + 客户端过滤（YAGNI） |
| CLI 布局 | `inkflow audit check --project-id <uuid> [--json]`，人类可读摘要 + --json 完整报告 | 审计是单一心智（「体检」），一个命令足够（同 F12 check 先例）；摘要规则（error/warning 逐条、info 只计数）控制终端噪音；--json 供 Agent/脚本消费（F7 约定） |
| CLI 退出码 | **恒 0**（成功执行；发现不一致是「结果」非「执行错误」） | 与 F7 退出码语义隔离：退出码 1 = 执行错误（NOT_FOUND/DB_ERROR），审计发现问题 ≠ 命令失败；脚本消费 `data.summary.consistent` 判断（--json 信封）；备选「发现 error 退出码 1」会让脚本无法区分「审计失败」与「审计发现不一致」（待澄清 Q1） |
| 世界维度内容 | 档案健康度（空内容条目 info）+ 缺口提示（有章节无档案 info） | 世界条目无跨模块引用字段（F10 单实体、无 FK），没有「引用完整性」可查；4 维度验收要求世界维度有实际检查内容——健康度 + 缺口是确定性、低成本、有作者价值的检查（备选「占位无规则」不满足验收 ①、备选「MODIFY F10 加引用字段」超范围，待澄清 Q2） |
| extraction_runs 缺口 | 状态可观测级：error run → warning、从未提取章节 → info | F14 run 表是「每源最新状态」非历史表（F14 §2.3）；error 行防御保留、真正失败缺口 = 无 run 行（F14 §6.2）——审计把「无 run 行」转为可观测 info；完整类型 × 章节矩阵归 Phase 2+（§5.5/待澄清 Q3） |
| 错误面 | 仅 NOT_FOUND / DB_ERROR（无 422、无 LLM_ERROR） | 唯一输入是路径 project_id（无请求体/查询参数 → 无输入校验失败）；无 LLM → 无 LLM_ERROR（同 F12）；这是创作工具链最小错误面（§3.3） |
| 规则集规模 | MVP 8 条规则（§5.2），候选规则（角色名相似度、回收提醒、类别词表等）明确排除 | 每条规则 = 规则函数 + 分支测试 × 3-5，3-5 人天估算约束下 8 条是「4 维度全覆盖 + 跨维度联动」的最小完备集（§5.2 论证）；候选规则归 §10（YAGNI） |
| 报告排序与去重 | findings 按 (维度序, 级别序, entity_name, id) 稳定排序；finding.id 稳定键 | 确定性输出 = 快照断言友好（F12 §5 同款）；稳定键支持去重与未来增量对比（Phase 2+ 历史归档的基础，§6.3） |
| CLI 测试归属 | `tests/cli/test_cli_audit.py`（顶层 tests/cli/）+ ci.yml `integration-cli-backend` job 显式列出 | 新增 CLI 测试文件默认是 CI 盲区（Issue #59 实测）；显式文件列表是既有 job 风格（Windows 下 pytest 不展开 glob）；unit 新文件由 `pytest tests/unit/` 自动覆盖（§8/§9） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 报告模型 + DTO 校验（AuditDimension 5 值 / AuditSeverity 3 值 / AuditFinding 可空字段 / AuditSummary 计数 / AuditReport 序列化 + ConsistencyReport 引用） | `pytest tests/unit/test_audit_models.py -v` 全绿 |
| M2 | 规则引擎·角色维度（R-C1 关系引用完整性：活动/软删 warning/悬空 error 全分支；R-C2 分组引用完整性） | `pytest tests/unit/test_audit_service.py -v` 全绿（R-C1/R-C2 用例） |
| M3 | 规则引擎·世界 + 伏笔维度（R-W1 条目内容健康度 / R-W2 档案缺口 / R-F1 event_id 锚点（软删 warning、悬空 error）/ R-F2 status-resolved_at 状态机一致性） | `pytest tests/unit/test_audit_service.py -v` 全绿（R-W*/R-F* 用例） |
| M4 | 规则引擎·时间线委托 + 跨维度（R-T1 委托 Mock check_consistency → 转换 + 嵌套透传；R-X1 事件 source_chapter_id 章节校验；R-X2 run 缺口：error run warning + 从未提取章节 info） | `pytest tests/unit/test_audit_service.py -v` 全绿（R-T1/R-X* 用例） |
| M5 | 服务编排（分页循环全量读取 / 汇总计数 / consistent 语义 / findings 排序 / counts / 项目校验 404 / 失败传播 / 确定性快照断言） | `pytest tests/unit/test_audit_service.py -v` 全绿（编排用例） |
| M6 | API GET /audit（成功路径 / 404 项目不存在 / 无效 UUID / 500 透传 / 幂等） | `pytest tests/unit/test_audit_api.py -v` 全绿 |
| M7 | CLI audit 组（摘要两种形态 / --json 完整报告 / 退出码 0 语义 / NOT_FOUND / DB_ERROR / 缺参退出码 2）；**ci.yml `integration-cli-backend` job 显式列出 `tests/cli/test_cli_audit.py`** | `pytest tests/cli/test_cli_audit.py -v` 全绿 + CI job 覆盖确认（Issue #59/#61 教训） |
| M8 | 手工验证闭环：真实项目全流程 | 手工验证（`inkflow project create` + `chapter create` 建 2+ 章 → `audit check` 见 info（未建档案/未提取章节）→ `character create` 建 2 角色 + `relation add` 建关系 → `world create` 建条目 → `timeline create` 建 3 事件制造逆序（如 5.0/3.0/4.0）→ `foreshadowing create --event-id ...` 建伏笔挂事件 → `audit check` 见：时间线 error（未声明倒叙）+ 其余维度干净 → `timeline update` 修正时间或加 flashback 标记 → `timeline delete` 软删某事件 → `audit check` 见伏笔锚点 warning（事件已软删）+ 时间线 error 消除 → `foreshadowing update --event-id \"\"` 解除挂接 → `audit check` 全维度 error=0（warning/info 可留）→ **悬空场景**：SQLite 直接插入一条 from/to 指向不存在角色的关系（`sqlite3 data.db "INSERT INTO character_relations (...) VALUES (...)"`）→ `audit check` 见 R-C1 error「悬空引用」→ 删除该行 → 恢复一致；`--json` 信封与 summary.consistent 全程可断言） |
| M9 | 全量回归 + 覆盖率 + lint/type | `pytest -v` 全绿；F15 模块行覆盖 ≥ 80%、全仓 ≥ 60%（0.2.0 DoD）；ruff + mypy 通过（CI 门禁 ADR-017）；domain/ 零框架 import（ADR-002/015） |

> **验收标准 ↔ Issue #45 映射**: ①「4 维度一致性检查（角色/时间线/世界/伏笔）」→ M2/M3/M4（R-C1/R-C2 角色、R-T1 时间线、R-W1/R-W2 世界、R-F1/R-F2 伏笔 + R-X1/R-X2 跨维度联动，§5.2 规则注册表）；②「可生成审计报告」→ M1/M5/M6/M7/M8（AuditReport 模型 + 编排汇总 + API/CLI 输出 + 手工闭环的 summary/findings 断言）。

---

## 待澄清问题（≤ 3 个，评审时确认）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | **CLI `audit check` 发现 error 级 findings 时退出码语义？** 选项 A：退出码恒 0——发现不一致是「结果」而非「执行错误」，脚本用 `--json` 的 `data.summary.consistent` 判断（与 F7 退出码语义完全隔离，NOT_FOUND/DB_ERROR 仍为 1）；选项 B：发现 error 时退出码 1——与 F7「退出码 1 = 执行错误」语义冲突，脚本无法区分「审计失败」与「审计发现不一致」；选项 C：新增退出码 3（「审计未通过」专用）——F7 全局约定需扩展，所有 CLI 消费方需感知新码 | F7 §5 全局退出码约定的扩展范围；Agent/脚本对审计结果的编程判断方式 | **✅ 已确认（用户拍板：选项 A）**：审计是只读检查（同 F12 check），「发现问题」是正常输出；consistent 是报告数据而非进程状态；选项 C 的「专门退出码」留给 F25 daemon 联调期再评估（若 MCP/Agent 需要强信号，届时按 ADR 流程扩展） |
| Q2 | **世界维度的检查内容？**（世界条目无跨模块引用字段，F10 单实体无 FK）选项 A：档案健康度 + 缺口提示——空内容条目 → info、有章节无世界档案 → info（§5.4，本 spec 设计）；选项 B：仅占位——维度存在但 MVP 无规则（不满足验收标准 ①「4 维度一致性检查」的实证口径）；选项 C：跨模块 MODIFY F10 给世界条目加引用字段（如关联角色/章节）再查引用完整性——超 3-5 人天估算且改动已合入的 F10 | 验收标准 ① 的达成口径；世界维度是否有实际检查内容 | **✅ 已确认（用户拍板：选项 A）**：健康度 + 缺口是确定性、低成本、有作者价值的检查（「条目只有名字没有内容」「写了 3 章还没建世界观档案」都是真实创作痛点）；C 的引用字段设计应等真实需求（YAGNI） |
| Q3 | **F14 extraction_runs 缺口检查的范围？** 选项 A：状态可观测级——run.status=error → warning「提取失败」、活动章节从未有任何 run → info「从未提取」（§5.5，本 spec 设计）；选项 B：完整缺口矩阵——按类型 × 章节逐一对比（每章 × 4 类型的未提取提示，章节多时 info 噪音巨大，且需感知 `timeline_auto_extract` 开关语义）；选项 C：MVP 排除 extraction_runs——跨维度只保留 R-X1（事件→章节） | R-X2 规则的复杂面与报告噪音；「提取缺口可观测」是否纳入 MVP | **✅ 已确认（用户拍板：选项 A）**：error run 是零成本高价值信号（F14 失败即异常，run 表 error 行是防御保留——F14 §6.2）；「从未提取章节」按章节粒度 info 提示有价值且不噪音化（量级 ≤ 数百）；B 的类型矩阵 + 设置项感知归 Phase 2+ |

---

*本文档为 F15 功能规格（What），实施步骤（How）见后续 `specs/f15-audit-service/plan.md`。所有里程碑验收以本节 M1-M9 为准。*
