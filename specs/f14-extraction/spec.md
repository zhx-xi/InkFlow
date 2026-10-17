# F14: 统一提取服务 (extraction_service) — 功能规格

> **端**: backend
> **依据**: PRD v2.1 §6.2 P1-06, Constitution P1-P6, ADR-013, ADR-019
> **依赖**: [F1 项目](../f1-project/spec.md) · [F2 章节](../f2-chapter/spec.md) · [F5 LLM Provider](../f5-llm-provider/spec.md) · [F9 角色](../f9-character/spec.md) · [F10 世界观](../f10-world-settings/spec.md) · [F11 大纲](../f11-outline/spec.md) · [F12 时间线](../f12-timeline/spec.md) · [F13 伏笔](../f13-foreshadowing/spec.md) · [F16 风格分析](../f16-style-analysis/spec.md)
> **参考 ADR**: [ADR-001](../../adr/architecture/ADR-001.md) (模块化单体), [ADR-002](../../adr/architecture/ADR-002.md) (六边形分层), [ADR-003](../../adr/database/ADR-003.md) (Repository), [ADR-004](../../adr/database/ADR-004.md) (Pydantic v2), [ADR-007v2](../../adr/architecture/ADR-007v2.md) (包结构), [ADR-010](../../adr/llm/ADR-010.md) (上下文分层), [ADR-012](../../adr/architecture/ADR-012.md) (错误处理), [ADR-013](../../adr/llm/ADR-013.md) (RAG: LangChain Chroma + BGE), [ADR-015](../../adr/llm/ADR-015.md) (LangChain 隔离), [ADR-016](../../adr/service/ADR-016.md) (loguru), [ADR-017](../../adr/test-ci/ADR-017.md) (CI 门禁), [ADR-018](../../adr/test-ci/ADR-018.md) (测试分层), [ADR-019](../../adr/packaging/ADR-019.md) (版本里程碑)

---

## 1. 概述

> **时间口径**（ADR-055）：本模块时间字段**存储 / API / MCP / `--json` 一律 UTC ISO 原始值**；CLI 人类输出经 `cli/_time.format_local` 转**系统本地时区**显示（naive 串 = UTC 口径先补 tzinfo 再换算）。硬约束惯例，非可配置开关。

把 F9-F13 已存在的**提取 / 生成 / 检查**能力收敛到一个**统一接口**（`ExtractionType` 7 种 + 增量提取），并落地 **ADR-013 RAG**（实现 `domain/ports/vector_store.py` 已定义的 `VectorStoreProtocol`：LangChain Chroma + BGE 本地 Embedding）。

**核心价值**: 作者与 AI Agent 面对「从章节文本/项目资料沉淀创作档案」时只有一个入口（`inkflow extract run` / `POST /api/v1/extract`），不用记 5 套模块各自的 extract/generate/check 命令；重复提取同一内容不再浪费 LLM token（增量提取只处理变更内容）；F9-F13 已建档案可一键索引进向量库，为 F6 上下文分层与 F3 写作提供语义检索数据基础（ADR-013 的落地实证）。

**与 F9-F13 样板的关系（关键差异——本模块是「横切收敛型」而非「实体 CRUD 型」）**: F9/F10 沉淀「实体 + AI 提取」，F11 演进为「实体 + AI 生成」，F12 演进为「实体 + 确定性检查（无 LLM）」，F13 演进为「实体 + 状态追踪 + F6 注入（无 LLM）」；**F14 不再新建任何业务实体档案**，而是把五条既有管线**收敛**到一个门面（Facade）背后，并叠加两块既有样板都没有的增值能力——**增量提取**（内容变更追踪，只处理变更源）与 **RAG 向量索引**（ADR-013 首次落地）：

```text
F9/F10 提取:  章节文本(text) ──LLM──▶ 结构化实体 ──合并落库──▶ 实体档案
F11  生成:    项目设定/约束(prompt) ──LLM──▶ 结构化大纲 ──新建落库──▶ 大纲规划
F12  检查:    事件档案(双时间维度) ──确定性算法──▶ 双线视图 + 冲突报告
F13  追踪:    伏笔档案(状态机) ──确定性追踪──▶ 状态流转
F14  新增:    章节文本(text) ──LLM──▶ 时间线事件 ──合并落库──▶ F12 事件档案（设置项开启时）

F14  门面:    ExtractionType(7 种) ──分发──▶ 上述管线（character/setting 委托提取、
             outline 委托生成、timeline 提取/检查双语义（设置项切换）、foreshadowing 新建提取管线、
             style 注册 handler（F16 ✅）、knowledge_relation 委托 F48 关系提取（项目级规则集，
             零 LLM））+ 增量提取（hash 变更追踪） + RAG 索引（ADR-013）
```

**复用** F9/F10/F11/F12/F13 的既有管线（`CharacterService.extract` / `WorldService.extract` / `OutlineService.generate` / `TimelineService.check_consistency`——门面直接注入各模块 Service 委托，**不重写管线**）；F13 移交的「伏笔 AI 提取」（F13 spec §10）与 Q2 拍板的「时间线事件提取」（章节文本 → 时间线事件，`timeline_auto_extract` 设置项控制，§5.5）是本模块**新建的两条 LLM 管线**（`_foreshadowing_extractor.py` + `foreshadowing_extract.yaml` / `_timeline_extractor.py` + `timeline_extract.yaml`，均镜像 F9/F10 提取骨架）；时间线提取需**跨模块 MODIFY F12**（事件实体加 `source_chapter_id` 来源章节字段 + 仓储 `list_by_chapter`，F13 改 F6 sources.py 先例，§2.6/§8）；`VectorStoreProtocol`（P0-11 已定义，5 种 EntityType + IndexableEntity/RetrievedEntity）由本模块首次实现为 `infrastructure/rag/langchain_vector_store.py`。

**边界声明**:
- F14 不做**新实体档案**：不建角色/世界观/伏笔表，所有落库仍走 F9-F13 的仓储与合并语义（§2/§5）
- F14 不做**F6 数据源替换**（CharacterSettingSource/WorldSettingSource 空实现）：归联调阶段（F13 先例：F9/F10 的注入替换不纳入模块里程碑），见 §10/§11
- F14 的**增量提取**是「按源（章节/文本）变更」粒度 + 事件-章节联动（Q3 综合方案：源 sha256 hash + F12 事件 `source_chapter_id`，§2.6/§5.2/§5.5）；实体级字段 diff 仍归 Phase 2+（§10/§12）
- F14 的 RAG 落地**只做基础设施与编排**：索引触发（提取后自动索引 / 全量重建）、检索入口（API/CLI）；**不接入 F3/F6 写作链路**（RAG 注入写作上下文归 Phase 2+ 联调，见 §10）
- F14 的 **STYLE 类型**（F16 风格检测）由 F16 注册 handler：接口契约（枚举/API/CLI）在 F14 全量支持，`StyleService.analyze`（确定性文本分析 + LLM 深度分析可选）返回 200 + StyleReport（§6.1/§12）
- F14 的 **TIMELINE 类型**＝「章节文本 → 时间线事件」LLM 提取管线 + `timeline_auto_extract` 设置项（**默认 false**——AI 自动写事件档案需用户显式开启）；开启时提取事件（跨模块 MODIFY F12 事件实体加 `source_chapter_id`），关闭时退回 F12 确定性检查；事件自动删除归 Phase 2+（§2.6/§5.5/§10）
- F14 的 **RAG 切片可配置**＝切片策略模式（fixed/paragraph/dialogue/llm，§5.6.1）+ 滑动重叠开关（默认关，§5.6.3）+ 检索元数据补强（章节 x/y + chunk 偏移 + 时间戳，§5.6.4）+ 切片参数纳入向量指纹（§5.6.5）；对话/LLM 档为后置档（§5.6.6/§5.6.7）；切片配置经 F32 `app_settings` 读写（跨模块 MODIFY F32 settings）

---

## 2. 数据模型

F14 是横切收敛型模块：**不新建业务实体表**，新增一张**增量追踪记录表**（extraction_runs）+ 一组 DTO/枚举；向量侧的数据类（EntityType / IndexableEntity / RetrievedEntity）**已由 P0-11 在 `domain/ports/vector_store.py` 定义，本模块引用不重定义**（§2.4）。领域层 id 为 UUID，数据库 int 自增映射（同 F1 §12 / ADR-004）。

### 2.1 ExtractionType（7 种提取类型，统一接口的入口枚举）

```python
class ExtractionType(StrEnum):
    """统一提取接口的 7 种类型（PRD P1-06 验收标准 ①）。"""

    CHARACTER = "character"        # 角色提取 → 委托 F9 CharacterService.extract
    SETTING = "setting"            # 世界提取 → 委托 F10 WorldService.extract
    OUTLINE = "outline"            # 大纲生成 → 委托 F11 OutlineService.generate（生成模式）
    TIMELINE = "timeline"          # 时间线事件提取（设置项开启，§5.5）/ 一致性检查（关闭，委托 F12 check_consistency）
    FORESHADOWING = "foreshadowing"  # 伏笔提取 → 本模块新建 ForeshadowingExtractor（F13 移交，§5.4）
    STYLE = "style"                # 风格检测 → F16 已注册 StyleService.analyze（§6.1）
    KNOWLEDGE_RELATION = "knowledge_relation"  # 知识图谱关系提取 → F48 RelationExtractionService（项目级规则提取，零 LLM）
```

**类型语义表**（每种类型在统一接口中的「输入模式 / 引擎 / 落库 / 增量 / RAG 映射」见 §6.1 注册表；本节只列身份映射）:

| ExtractionType | 对应模块 | 委托管线 | 管线性质 | 输入 |
|----------------|----------|----------|----------|------|
| `character` | F9 | `CharacterService.extract` | LLM 提取（模板+解析+重试+合并） | text / chapter_ids |
| `setting` | F10 | `WorldService.extract` | LLM 提取（同上，无 relations） | text / chapter_ids |
| `outline` | F11 | `OutlineService.generate` | LLM 生成（生成即新建，同名 422） | prompt / num_chapters |
| `timeline` | F12（实体 MODIFY）+ F14（管线） | `TimelineExtractor.extract`（设置项**开启**）/ `TimelineService.check_consistency`（设置项**关闭**——v1.1 起为兜底语义） | LLM 提取（章节文本 → 时间线事件，镜像 F9 骨架，合并到 F12 事件档案）/ 确定性检查（无 LLM） | 开启：text / chapter_ids；关闭：无（库内事件档案） |
| `foreshadowing` | F13 | `ForeshadowingExtractor`（F14 新建） | LLM 提取（镜像 F9 骨架，合并到 F13 档案） | text / chapter_ids |
| `style` | F16 ✅ | `StyleService.analyze`（F16 注册，§6.1） | 确定性文本分析（+ LLM 深度分析可选，仅独立入口） | text / chapter_ids |
| `knowledge_relation` | F48 ✅ | `RelationExtractionService.extract_for_project`（`method="rule"`） | 确定性规则集（R1/R2/R3，零 LLM） | 无（项目级；不接受 text/chapter_ids → 422） |

> **为什么 OUTLINE/TIMELINE 也算「提取类型」**: PRD P1-06 明确列出 6 种类型统一接口；大纲与时间线在创作工具链中的角色是「从创作资料收敛出结构化产物」，与角色/世界/伏笔同属「一键沉淀」的用户心智。统一接口对它们做**语义适配**（outline=生成；timeline=提取（设置项开启）或检查（关闭）），而不是强行为它们编造「从文本提取」的管线——能力等价、入口统一（论证见 §5.7/§12）。
>
> **TIMELINE 双语义切换（v1.1，Q2 拍板）**: 由设置项 `project.config.extra["timeline_auto_extract"]`（默认 **false**）切换——开启 = 「LLM 提取（章节文本 → 时间线事件）」语义；关闭 = F12 确定性检查（v1.0 的单一语义，现为兜底）。请求 `auto_extract` / CLI `--auto-extract` 可单次覆盖；**判定在门面层**，关闭时不调用 LLM（§2.6/§5.5）。

### 2.2 ExtractionRequest / ExtractionResult / ReindexResult（DTO）

```python
class ExtractionRequest(BaseModel):
    """统一提取请求 — 类型相关参数由 type 决定（§6.4 输入约束表）.

    text 与 chapter_ids 互斥（二选一，仅 character/setting/foreshadowing 使用；
    timeline 设置项开启时同样使用）;
    prompt/num_chapters/save 仅 outline 使用; include_flashbacks 仅 timeline 使用;
    auto_extract 仅 timeline 使用（None=跟随项目配置 timeline_auto_extract）;
    index 对 character/setting/foreshadowing/timeline（开启时）生效.
    """

    project_id: uuid.UUID
    type: ExtractionType
    text: str | None = None                  # 手动文本（与 chapter_ids 互斥，≤ 50000 字符）
    chapter_ids: list[uuid.UUID] | None = None  # 章节模式（从 F2 读取内容，增量追踪，≤ 100 章）
    prompt: str | None = None                # outline: 生成约束（透传 F11）
    num_chapters: int | None = None          # outline: 规划章节数 1-100（透传 F11）
    save: bool = True                        # outline: 落库开关（透传 F11；False=仅预览）
    include_flashbacks: bool = True          # timeline: 透传 F12 check_consistency（关闭语义）
    auto_extract: bool | None = None         # timeline: 覆盖项目配置 timeline_auto_extract（§2.6；None=跟随项目配置）
    model: str | None = None                 # LLM 类型: 覆盖项目默认模型（provider/model_name）
    index: bool = False                      # 提取成功后自动索引本次产物（RAG，§5.6）
    force: bool = False                      # 忽略增量 skip，强制重跑（§5.2）
    granularity: Granularity = Granularity.FINE  # character/setting: 提取粒度（§5.8.3；其他类型非 FINE → 422）
    dry_run: bool = False                    # character/setting: 预览不落库（§5.8.4；其他类型 true → 422）

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("章节文本不能为空")
        if len(stripped) > 50000:
            raise ValueError("章节文本不能超过 50000 个字符")
        return stripped

    @field_validator("chapter_ids")
    @classmethod
    def validate_chapter_ids(cls, v: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("chapter_ids 不能为空列表")
        if len(v) > 100:
            raise ValueError("单次提取章节数不能超过 100")
        return v

    @field_validator("num_chapters")
    @classmethod
    def validate_num_chapters(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not 1 <= v <= 100:
            raise ValueError("num_chapters 必须在 1-100 之间")
        return v

class Granularity(StrEnum):
    """提取粒度（§5.8.3；仅 character / setting 生效，其他类型非 FINE → 422）."""

    FINE = "fine"      # 默认：LLM 输出几条落几条
    COARSE = "coarse"  # 粗粒度：模板注入粗粒度指令 + 每源条目上限（§5.8.3）

class ExtractionStatus(StrEnum):
    """统一结果状态 — MVP 产出 SUCCESS / SKIPPED；ERROR 预留（§5.3）."""

    SUCCESS = "success"    # 管线执行完成（含部分成功：部分源 skip、部分源执行）
    SKIPPED = "skipped"    # 全部源内容未变更（增量提取，§5.2），未调用 LLM
    ERROR = "error"        # 预留：门面内错误走异常（ADR-012），该值供 run 记录表使用

class ExtractionResult(BaseModel):
    """统一提取结果 — 各类型共用的信封结构（§5.3 字段语义）."""

    type: ExtractionType
    status: ExtractionStatus
    skipped_reason: str | None = None   # status=skipped 时说明（如「内容未变更（源: chapter xxx）」）
    processed_sources: int = 0          # 本次实际执行管线的源数（章节模式=执行的章数，手动=1）
    skipped_sources: int = 0            # 本次因内容未变更跳过的源数
    created: int = 0                    # 归一化「新增」计数（§5.3 各类型口径）
    updated: int = 0                    # 归一化「更新」计数
    warnings: list[str] = []
    model: str | None = None            # 实际使用的 LLM 模型（LLM 类型；timeline 关闭时为 None）
    indexed: bool = False               # 本次是否执行了向量索引（request.index 且类型支持）
    batch_id: str | None = None         # 本次 run 落库批次标识（§5.8.5；dry_run / 无写入时 None）
    detail: dict[str, Any] = Field(default_factory=dict)  # 各类型原始结果 model_dump（§5.3）

class ReindexResult(BaseModel):
    """全量重建索引结果（vector reindex / POST vector/reindex）."""

    project_id: uuid.UUID
    entity_types: list[EntityType]      # 实际处理的实体类型
    indexed: int                        # 索引的实体总数（含 upsert 覆盖）
    warnings: list[str] = []

class RollbackResult(BaseModel):
    """批次回滚结果（§5.8.5）."""

    batch_id: str
    deleted: int = 0                    # 实际删除的条目数（幂等：重复回滚 → 0）
    warnings: list[str] = []
```

**字段表（ExtractionResult）**:

| 字段 | 类型 | 说明 |
|------|------|------|
| type | ExtractionType | 请求类型原样回显 |
| status | ExtractionStatus | success / skipped（error 走异常 + run 记录，§5.3） |
| skipped_reason | str? | skipped 时的原因文案（如「内容未变更（源: chapter 7a4f2c91-...）」） |
| processed_sources | int | 执行管线的源数（章节模式=执行的章数；手动=1；outline=1；timeline=开启时按源数、关闭时=1） |
| skipped_sources | int | 增量跳过的源数（章节模式=hash 相同的章数；手动=0 或 1；timeline 关闭时=0） |
| created / updated | int | 归一化计数（character=角色数、setting=条目数、foreshadowing=伏笔数、outline=1/0、timeline=开启时=事件数、关闭时=0） |
| warnings | list[str] | 各管线 warning 汇总（解析条目跳过、软删同名新建等） |
| model | str? | 实际 LLM 模型（LLM 类型）；timeline 关闭时（检查）为 None |
| indexed | bool | request.index=true 且类型支持时是否完成索引（§5.6；timeline 关闭时恒 False） |
| detail | dict | 原始模块结果（CharacterExtractionResult / WorldExtractionResult / OutlineGenerationResult / ConsistencyReport / ForeshadowingExtractionResult / TimelineExtractionResult（开启时）的 model_dump），含实体列表与冲突明细 |

### 2.3 ExtractionRun（增量追踪记录表 — F14 唯一的落库数据）

**用途**: 记录「每个 (project, type, 源) 的最后一次提取状态」，增量提取的判定依据（§5.2）。**每源一行最新状态（upsert），不是历史表**——历史变更审计归 F15（§10）。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | int | PK AUTOINCREMENT | DB 自增主键（领域层暴露 UUID 语义可省——run 仅供状态查询，直接暴露 int id，同 timeline_events 先例） |
| project_id | int | NOT NULL, FK→projects.id (CASCADE), 已索引 | 所属项目（项目硬删 → 级联清理） |
| type | str | NOT NULL, 已索引 | `ExtractionType.value` |
| source_key | str? | NOT NULL（NULL 仅历史兼容预留） | 源标识：章节模式=`str(chapter_id)`；手动模式=`"manual"` |
| content_hash | str? | NOT NULL | 源内容 sha256（UTF-8），增量判定指纹（§5.2） |
| status | str | NOT NULL, DEFAULT "success" | `success` / `skipped` / `error`（失败 run 也落库，供 `extract status` 观察缺口） |
| created_count | int | NOT NULL, DEFAULT 0 | 该源本次新增数 |
| updated_count | int | NOT NULL, DEFAULT 0 | 该源本次更新数 |
| warnings_json | str | NOT NULL, DEFAULT "[]" | warnings JSON 序列化（loguru 之外的持久化可观测性） |
| error | str? | NULLABLE | status=error 时的错误消息（截断 ≤ 500 字符） |
| model | str? | NULLABLE | 该源实际使用的 LLM 模型 |
| indexed | bool | NOT NULL, DEFAULT False | 该源是否已索引（index=true 且类型支持时置 True） |
| run_at | datetime | NOT NULL, AUTO | 本次运行时间 (UTC) |

**唯一约束**: `UNIQUE (project_id, type, source_key)`（SQLite `INSERT ... ON CONFLICT DO UPDATE` upsert）——同一 (项目, 类型, 源) 只保留**最新一次** run 状态。`outline` 类型：source_key 固定 `"full"`（每次执行，不 skip，§5.2）；`timeline` 类型：**设置项关闭时** source_key 固定 `"full"`（每次执行，只读检查），**开启时**按章节/文本源增量（同 character，§5.2/§5.5）。

**业务规则**:
- run 是**提取过程的副产物**：不提供独立创建/更新端点（只有查询：`extract status` / GET runs，§3/§4）
- `status=skipped` 的行同样落库（记录「已确认未变更」事实，避免重复比对日志缺失）
- 章节被删除后 run 行**保留**（孤儿行，不影响任何逻辑；项目删除时 FK CASCADE 清理）
- run **不参与**任何提取/合并逻辑的数据流——它只读 hash 判定 skip（§5.2 步骤 ①）

```python
# ORM __table_args__（SQLAlchemy 2.0 + SQLite）
__table_args__ = (
    UniqueConstraint("project_id", "type", "source_key", name="uq_extraction_runs_source"),
)
```

### 2.4 引用 VectorStoreProtocol（不重定义 — P0-11 已存在）

`backend/src/inkflow/domain/ports/vector_store.py` 已定义完整协议，F14 **原样引用**：

| 定义 | 内容 | F14 用途 |
|------|------|----------|
| `EntityType` (StrEnum) | `character` / `setting` / `foreshadowing` / `timeline_event` / `chapter_chunk` | 与 `ExtractionType` 的映射键（§5.6/§6.1） |
| `IndexableEntity` (dataclass) | `id: str` / `entity_type` / `project_id: str` / `content: str` / `metadata: dict[str, str\|int\|float]` | 索引输入统一模型（§5.6 构建规则） |
| `RetrievedEntity` (dataclass) | `entity_id` / `entity_type` / `content` / `relevance_score: float` / `metadata` | 检索输出（API/CLI 直接序列化） |
| `VectorStoreProtocol` | `index` / `index_batch` / `retrieve` / `delete` / `delete_project`（全部 async） | 基础设施实现契约（§5.6/§8） |

> **EntityType 与 ExtractionType 不对齐（设计要点）**: ADR-013 的 5 种 EntityType 中 `timeline_event` / `chapter_chunk` 分别来自 F12 事件档案与 F2 章节内容，`outline`/`style` **不在**向量索引范围（大纲是规划版本、风格是文本属性，MVP 无检索价值）；索引源 = 实体档案（character/setting/foreshadowing/timeline_event）+ 章节分块（chapter_chunk），与「提取类型」是两个正交维度（§5.6/§6.1 映射表）。

### 2.5 领域模型代码（Pydantic v2 语法）

```python
# domain/models/extraction.py
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from inkflow.domain.ports.vector_store import EntityType  # P0-11 已定义，引用不重定义（§2.4）

class ExtractionType(StrEnum):
    """统一提取接口的 7 种类型（§2.1）。"""

    CHARACTER = "character"
    SETTING = "setting"
    OUTLINE = "outline"
    TIMELINE = "timeline"
    FORESHADOWING = "foreshadowing"
    STYLE = "style"
    KNOWLEDGE_RELATION = "knowledge_relation"

class ExtractionStatus(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    ERROR = "error"

class ExtractionRequest(BaseModel):
    """统一提取请求（§2.2）— 类型相关参数约束见 §6.4。"""

    project_id: uuid.UUID
    type: ExtractionType
    text: str | None = None
    chapter_ids: list[uuid.UUID] | None = None
    prompt: str | None = None
    num_chapters: int | None = None
    save: bool = True
    include_flashbacks: bool = True
    auto_extract: bool | None = None
    model: str | None = None
    index: bool = False
    force: bool = False

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("章节文本不能为空")
        if len(stripped) > 50000:
            raise ValueError("章节文本不能超过 50000 个字符")
        return stripped

    @field_validator("chapter_ids")
    @classmethod
    def validate_chapter_ids(cls, v: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("chapter_ids 不能为空列表")
        if len(v) > 100:
            raise ValueError("单次提取章节数不能超过 100")
        return v

    @field_validator("num_chapters")
    @classmethod
    def validate_num_chapters(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not 1 <= v <= 100:
            raise ValueError("num_chapters 必须在 1-100 之间")
        return v

class ExtractionResult(BaseModel):
    """统一提取结果（§2.2/§5.3）。"""

    type: ExtractionType
    status: ExtractionStatus
    skipped_reason: str | None = None
    processed_sources: int = 0
    skipped_sources: int = 0
    created: int = 0
    updated: int = 0
    warnings: list[str] = Field(default_factory=list)
    model: str | None = None
    indexed: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)

class ExtractionRun(BaseModel):
    """增量追踪记录（§2.3）— 每 (project, type, source) 一行最新状态。"""

    model_config = {"from_attributes": True}

    id: int
    project_id: uuid.UUID
    type: ExtractionType
    source_key: str
    content_hash: str
    status: ExtractionStatus = ExtractionStatus.SUCCESS
    created_count: int = 0
    updated_count: int = 0
    warnings_json: str = "[]"
    error: str | None = None
    model: str | None = None
    indexed: bool = False
    run_at: datetime

class ReindexResult(BaseModel):
    """全量重建索引结果（§5.6）。"""

    project_id: uuid.UUID
    entity_types: list[EntityType]
    indexed: int
    warnings: list[str] = Field(default_factory=list)
```

> 注: `ExtractionRun` 领域模型引用 `EntityType`（ReindexResult 用），从 `domain/ports/vector_store.py` 导入（P0-11，ADR-002 依赖方向允许 domain 内互引）。

### 2.6 TIMELINE 提取设置项与事件-章节联动（跨模块 MODIFY F12）

**设置项 `timeline_auto_extract`**（F1 `ProjectConfig.extra` 模式——项目级扩展配置字典，无需 F1 schema 变更）:

| 层级 | 键/参数 | 默认 | 说明 |
|------|---------|------|------|
| 项目配置 | `project.config.extra["timeline_auto_extract"]` | **false** | 是否开启「章节文本 → 时间线事件」LLM 自动提取（AI 自动写事件档案默认关闭，需用户显式开启——§12 论证） |
| 请求覆盖 | `ExtractionRequest.auto_extract: bool \| None = None` | None = 跟随项目配置 | API 单次请求覆盖（§2.2/§6.4） |
| CLI 覆盖 | `--auto-extract / --no-auto-extract` | 缺省 None = 跟随项目配置 | CLI 单次调用覆盖（§4） |

判定顺序：请求显式值 → 项目配置 `extra` → 默认 false。**判定在门面层完成**（§5.1 要点 7）——关闭时不调用 LLM，直接委托 F12 确定性检查。

**F12 事件实体新增 `source_chapter_id`（跨模块 MODIFY F12 — 属于 F12 实体，本 spec 声明修改）**:

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| source_chapter_id | uuid.UUID?（DB int?） | NULLABLE, FK→chapters.id ON DELETE SET NULL, 已索引 | 事件**来源章节**——LLM 提取事件时记录（事件-章节联动锚点）；手工建档为 None；章节硬删 → 置 None（事件保留） |

配套修改（F13 改 F6 `sources.py` 先例——既有模块文件随本模块一并修改，见 §8 模块归属）: `domain/models/timeline.py`（TimelineEvent + TimelineEventCreate/Update 对应字段）、`domain/ports/timeline_repository.py`（Protocol 加 `list_by_chapter`）、`infrastructure/database/models/timeline.py`（ORM 列 + FK + 索引）、`infrastructure/database/repositories/timeline_repo.py`（实现 `list_by_chapter`）。

**事件合并匹配键**: `(project_id, title, source_chapter_id)`——同章同名事件 = 同一事件（更新），跨章同名 = 不同事件（新建），手工事件（source_chapter_id=None）不参与提取合并匹配（匹配逻辑在**服务层**——F12 事件表无 partial unique，表结构不引入唯一索引，§5.5 合并策略）。

**章节联动语义（Q3 综合方案）**:
- 章节内容变更 → hash 变化 → 重提取该章 → 按匹配键更新该章事件（**只增改不删除**）
- 章节**软删** → 事件保留 `source_chapter_id`（历史来源锚点）；章节**硬删** → FK ON DELETE SET NULL（来源置空，事件保留）
- 提取移除「章节中不再出现的事件」的自动删除 → Phase 2+（MVP 只增改不删除，§10）

---

## 3. API 契约

端点风格沿用既有约定：**统一提取入口扁平**（`POST /api/v1/extract`——type 是资源维度而非项目维度，镜像 F9 `/characters/extract` 扁平先例）；**runs 查询与向量动作嵌套项目路径**（项目级资源）。错误响应格式沿用 F1/F2/F9-F13（`{"detail": "..."}` 404/422；LLM/管线失败 500）。

### 3.1 端点总览（7 个）

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/extract` | 统一提取（7 种类型分发 + 增量 + 可选索引） | `ExtractionRequest` | 200 + ExtractionResult |
| GET | `/api/v1/projects/{project_id}/extractions/runs` | 增量状态列表 | Query: `?type=&offset=&limit=` | 200 + `{items, total, offset, limit}` |
| POST | `/api/v1/projects/{project_id}/vector/reindex` | 全量重建索引（RAG） | `{entity_types?: [...]}` | 200 + ReindexResult |
| POST | `/api/v1/projects/{project_id}/vector/retrieve` | 语义检索（RAG） | `{query, entity_types?, top_k?, min_score?}` | 200 + `{items: [RetrievedEntity]}` |
| GET | `/api/v1/projects/{project_id}/vector/status` | 向量库状态（stale 原因，含 chunking_changed） | — | 200 + `{stale, reason?}` |
| PUT | `/api/v1/vector/embedding-model` | 切换激活 embedding 模型 | `{provider, model_id}`（必填校验） | 200（404「Provider 不存在」/「模型不存在」，422 缺失） |
| POST | `/api/v1/projects/{project_id}/extractions/rollback` | 按批次整批回滚本次提取**新建**的条目（§5.8.5，幂等） | `{batch_id}` | 200 + RollbackResult |

> `/api/v1/extract` 为**静态路径段**，无与既有路由的歧义（F10 §3.1 的 extract 路径歧义处理不适用——本端点无 `{resource_id}` 兄弟段）。
> 切片配置（mode/chunk_size/overlap）经 F32 `GET/PATCH /settings` 读写（§5.6.3，F32 已有端点），本 spec **不新增 API 端点**；`vector/status` 的 stale reason 已含 `chunking_changed`（§5.6.5）。

### 3.2 请求/响应示例 — 统一提取

**章节模式提取角色（增量 + 自动索引）**:
```http
POST /api/v1/extract
Content-Type: application/json

{
  "project_id": "3f2e1d4a-...",
  "type": "character",
  "chapter_ids": ["7a4f2c91-...", "9b1c2d3e-..."],
  "index": true
}
```
→ 200（两章均执行；提取 + 合并落库 + 角色索引）
```json
{
  "type": "character",
  "status": "success",
  "skipped_reason": null,
  "processed_sources": 2,
  "skipped_sources": 0,
  "created": 3,
  "updated": 2,
  "warnings": ["跳过非法角色条目 #2: name: 角色名不能为空"],
  "model": "openai/gpt-4o",
  "indexed": true,
  "detail": {
    "created": [{"id": "...", "name": "林晚", "personality": "...", "background": "...", "goals": "..."}],
    "updated": [{"id": "...", "name": "沈砚", "personality": "..."}],
    "relations_created": [...], "relations_updated": [...], "warnings": [...], "model": "openai/gpt-4o"
  }
}
```

**手动文本提取世界观**:
```http
POST /api/v1/extract
{"project_id": "3f2e1d4a-...", "type": "setting", "text": "青云城坐落于……"}
```
→ 200（status=success；detail 为 WorldExtractionResult 的 model_dump）

**增量 skip（同一章节第二次提交，内容未变更）**:
```http
POST /api/v1/extract
{"project_id": "3f2e1d4a-...", "type": "character", "chapter_ids": ["7a4f2c91-..."]}
```
→ 200
```json
{
  "type": "character",
  "status": "skipped",
  "skipped_reason": "内容未变更（源: chapter 7a4f2c91-...）",
  "processed_sources": 0,
  "skipped_sources": 1,
  "created": 0, "updated": 0, "warnings": [],
  "model": null, "indexed": false,
  "detail": {}
}
```
（未调用 LLM；`--force` / `force=true` 可强制重跑，§5.2）

**大纲生成（统一入口走 F11 生成模式）**:
```http
POST /api/v1/extract
{
  "project_id": "3f2e1d4a-...",
  "type": "outline",
  "prompt": "复仇与救赎双线并进",
  "num_chapters": 30,
  "save": true
}
```
→ 200（detail 为 OutlineGenerationResult；同名活动大纲 → 422 透传 F11 `OutlineNameConflictError`）

**时间线事件提取（设置项开启——`auto_extract: true` 单次覆盖；统一入口走 F14 时间线提取管线）**:
```http
POST /api/v1/extract
{
  "project_id": "3f2e1d4a-...",
  "type": "timeline",
  "chapter_ids": ["7a4f2c91-...", "9b1c2d3e-..."],
  "auto_extract": true,
  "index": true
}
```
→ 200（status=success；created/updated=新建/更新事件数；detail 为 TimelineExtractionResult；事件带 source_chapter_id=来源章节；index=true 时事件索引为 timeline_event）

**时间线一致性检查（设置项关闭——默认；统一入口走 F12 确定性检查，无 LLM）**:
```http
POST /api/v1/extract
{"project_id": "3f2e1d4a-...", "type": "timeline"}
```
→ 200（status=success；created/updated=0；detail 为 ConsistencyReport：conflicts/flashbacks/consistent）

**STYLE 类型（F16 已注册 handler——确定性分析，§6.1）**:
```http
POST /api/v1/extract
{"project_id": "3f2e1d4a-...", "type": "style", "text": "第一章……"}
```
→ 200（status=success；created=0/updated=0——无实体产物；detail 为 StyleReport：fingerprint 风格指纹 / ai_trace AI 痕迹 / lexical 词汇分析摘要，llm_assessment=None——门面恒确定性，F16 spec §8.2 归一语义）

**输入冲突与缺失**:
```http
POST /api/v1/extract
{"project_id": "3f2e1d4a-...", "type": "character", "text": "……", "chapter_ids": ["7a4f2c91-..."]}
→ 422 {"detail": "text 与 chapter_ids 不能同时使用"}

POST /api/v1/extract
{"project_id": "3f2e1d4a-...", "type": "character"}
→ 422 {"detail": "character/setting/foreshadowing 类型必须提供 text 或 chapter_ids"}

POST /api/v1/extract
{"project_id": "3f2e1d4a-...", "type": "outline", "text": "……"}
→ 422 {"detail": "outline 类型不支持 text/chapter_ids（使用 prompt/num_chapters）"}

POST /api/v1/extract
{"project_id": "00000000-0000-0000-0000-000000000000", "type": "character", "text": "……"}
→ 404 {"detail": "项目不存在"}
```
> 其余 422 场景（timeline 设置项关闭时携带 text、章节不存在/跨项目等）见 §3.4 异常映射表与 §7。

### 3.3 请求/响应示例 — runs 查询 / 向量索引 / 向量检索

**增量状态列表**:
```http
GET /api/v1/projects/3f2e1d4a-.../extractions/runs?type=character&offset=0&limit=50
```
→ 200
```json
{
  "items": [
    {"id": 1, "project_id": "3f2e1d4a-...", "type": "character", "source_key": "7a4f2c91-...",
     "content_hash": "a1b2c3...", "status": "success", "created_count": 2, "updated_count": 1,
     "warnings_json": "[]", "error": null, "model": "openai/gpt-4o", "indexed": true,
     "run_at": "2026-08-02T10:00:00Z"},
    {"id": 2, "project_id": "3f2e1d4a-...", "type": "character", "source_key": "9b1c2d3e-...",
     "content_hash": "d4e5f6...", "status": "error", "created_count": 0, "updated_count": 0,
     "warnings_json": "[]", "error": "3 次尝试后仍无法解析为合法 JSON", "model": "openai/gpt-4o",
     "indexed": false, "run_at": "2026-08-02T09:00:00Z"}
  ],
  "total": 2, "offset": 0, "limit": 50
}
```

**全量重建索引**:
```http
POST /api/v1/projects/3f2e1d4a-.../vector/reindex
{"entity_types": ["character", "setting", "foreshadowing", "timeline_event", "chapter_chunk"]}
```
→ 200
```json
{
  "project_id": "3f2e1d4a-...",
  "entity_types": ["character", "setting", "foreshadowing", "timeline_event", "chapter_chunk"],
  "indexed": 87,
  "warnings": []
}
```
（缺省 entity_types = 全部 5 种；对已有档案全量 upsert，幂等）

**语义检索**:
```http
POST /api/v1/projects/3f2e1d4a-.../vector/retrieve
{"query": "林晚右肩的胎记", "entity_types": ["foreshadowing"], "top_k": 5, "min_score": 0.3}
```
→ 200
```json
{
  "items": [
    {"entity_id": "9b1c2d3e-...", "entity_type": "foreshadowing",
     "content": "伏笔：林晚的身世。林晚右肩的胎记与女主母亲的信物相同……",
     "relevance_score": 0.82,
     "metadata": {"project_id": "3f2e1d4a-...", "name": "林晚的身世", "status": "open"}}
  ]
}
```

### 3.4 错误响应格式（沿用 F1/F2/F9-F13/ADR-012）

```json
// 404 — 资源不存在
{"detail": "项目不存在"}

// 422 — 业务校验失败 / Pydantic 验证失败 / 类型不支持
{"detail": "text 与 chapter_ids 不能同时使用"}
{"detail": "character/setting/foreshadowing 类型必须提供 text 或 chapter_ids"}
{"detail": "outline 类型不支持 text/chapter_ids（使用 prompt/num_chapters）"}
{"detail": "时间线自动提取未开启（配置 timeline_auto_extract）"}
{"detail": "章节不存在"}
{"detail": "章节不属于该项目"}
{"detail": "大纲同名已存在（透传 F11 OutlineNameConflictError）"}

// 500 — LLM / 管线 / RAG 失败（loguru 记录）
{"detail": "LLM 调用失败: ..."}
{"detail": "角色提取失败: 2 次修复重试后仍无法解析为合法 JSON（...）"}
{"detail": "RAG 向量库不可用: Embedding 模型加载失败（首次使用需联网下载 ~100MB）"}
```

**异常映射表**:

| 异常/场景 | 状态码 | 响应 |
|-----------|--------|------|
| 项目不存在（门面统一校验 `ProjectRepositoryProtocol.get` → None） | 404 | `{"detail": "项目不存在"}` |
| 无效 UUID 格式（project_id / chapter_ids 内） | 404 / 422 | 统一解析失败处理（同 F9-F13 `_parse_id`；chapter_ids 内非法 UUID → Pydantic 422） |
| text 与 chapter_ids 互斥 / 缺失 / 类型不匹配（§6.4） | 422 | 服务层业务校验（`ExtractionValidationError`，消息即 detail） |
| timeline 设置项未开启且携带 text/chapter_ids | 422 | `ExtractionValidationError`（消息「时间线自动提取未开启（配置 timeline_auto_extract）」——设置项判定在门面层，§5.5） |
| STYLE 类型调用 | 200 | 成功返回（`StyleValidationError` 等 F16 错误见 F16 spec §3.3） |
| chapter_ids 指向不存在章节（含软删——F2 get 不含软删） | 422 | `ChapterNotFoundError`（「章节不存在」） |
| chapter_ids 指向其他项目章节 | 422 | `ChapterNotInProjectError`（「章节不属于该项目」） |
| outline 同名活动大纲 | 422 | 透传 F11 `OutlineNameConflictError`（同 F11 现状） |
| LLM 调用失败 | 500 | 透传 `LLMRequestError`（F5 重试耗尽，不消耗解析重试；router 转 500，同 F9-F11） |
| 提取解析重试耗尽（character/setting/foreshadowing/timeline） | 500 | 透传 `CharacterExtractionError` / `WorldExtractionError` / `ForeshadowingExtractionError` / `TimelineExtractionError` |
| 生成解析重试耗尽（outline） | 500 | 透传 `OutlineGenerationError` |
| RAG 暂时不可用（vector_store 未装配 / BGE 模型加载失败） | **503 + Retry-After** | `RAGUnavailableError`（消息含「RAG 向量库不可用」前缀——调用方可区分「暂时不可用（可重试）」与「请求错误」） |
| chroma 存储层错误（hnsw 段读取失败等） | 500 | `VectorStoreError`（消息即 detail，服务层自愈重试后仍失败） |
| run 记录 DB 错误 | 500 | 全局处理器（loguru，ADR-012/016） |

> **与 F9-F13 的差异**: F14 是首个**同时携带** LLM 错误（LLM_ERROR）、管线错误（EXTRACTION_ERROR）与 RAG 错误（RAG_ERROR）的模块；「类型不支持」作为 422 业务错误表达（区别于 404/501，见 §12 决策表——STYLE 占位 422 已被 F16 取代，仅剩防御性「未注册类型」分支）。

---

## 4. CLI 命令签名

遵循 F7 §5 全局约定：`--json` 统一信封 `{"ok": true, "data": ...}` / `{"ok": false, "error": {"code", "message"}}`；退出码 0/1/2/130。**错误码**：NOT_FOUND / VALIDATION_ERROR / LLM_ERROR / DB_ERROR（沿用）+ **EXTRACTION_ERROR**（提取/生成管线解析失败）+ **RAG_ERROR**（向量库不可用/检索失败）——**UNSUPPORTED_TYPE 已随 F16 删除**（STYLE 已注册 handler，错误码对 style 不再可达，F16 spec §8.2）。`extract` / `vector` 组在 F14 落地时并入 F7 命令树（`cli/app.py` 注册，同 F9-F13 各组）。

### 4.1 extract 组（统一提取入口 + 增量状态）

```bash
inkflow extract run --project-id <uuid> \
    --type <character|setting|outline|timeline|foreshadowing|style|knowledge_relation> \
    [--text <str> | --text-file <path> | --chapters <uuid,uuid,...>] \
    [--prompt <str>] [--num-chapters <int>] [--no-save] \
    [--auto-extract | --no-auto-extract] \
    [--model <str>] [--index] [--force]
    [--granularity <fine|coarse>] [--dry-run] [--json]
    # --granularity / --dry-run 仅 character / setting 生效（§5.8.3/§5.8.4）
    # --text/--text-file/--chapters 三选一（互斥，同 F9 character extract 先例；
    #   timeline 设置项开启时同样使用，见 §6.4）
    # --no-save 仅 outline 生效（透传 F11 save=false，仅预览不落库）
    # --auto-extract/--no-auto-extract 仅 timeline 生效（缺省 None = 跟随项目配置
    #   timeline_auto_extract：开启=LLM 事件提取，关闭=F12 确定性检查，§5.5）
    # --index 提取成功后自动索引本次产物（§5.6）；--force 忽略增量 skip 强制重跑（§5.2）
    # --type style → F16 已注册 handler（§6.1）：成功退出码 0（校验失败 → VALIDATION_ERROR 信封，F16 spec §3.3）
    # --type knowledge_relation → F48 关系提取：项目级单源、规则集提取（零 LLM），不带源参数；
    #   带 --text/--text-file/--chapters → 422「knowledge_relation 类型不支持 text/chapter_ids（项目级提取，无需源参数）」（§6.4）

inkflow extract status --project-id <uuid> [--type <character|setting|outline|timeline|foreshadowing|style|knowledge_relation>] [--json]
    # 列出该项目各 (type, 源) 的最近一次 run 状态（§2.3）

inkflow extract rollback --project-id <uuid> --batch-id <str> [--json]
    # 按批次整批回滚：删除该项目下该 batch_id 的新建条目（幂等；§5.8.5）
```

### 4.2 vector 组（RAG 索引与检索）

```bash
inkflow vector reindex --project-id <uuid> \
    [--type <character|setting|foreshadowing|timeline_event|chapter_chunk>] [--json]
    # 缺省 --type = 全部 5 种实体类型；从 F9-F13 档案 + F2 章节全量重建（幂等 upsert，§5.6）
    # 可重复 --type 指定多个（如 --type character --type setting）
    # 切片配置（mode/chunk_size/overlap）经 app_settings 持久化（§5.6.3），reindex 不加
    #   --chunk-mode 等覆盖参数（Q6 待拍板，§10）

inkflow vector retrieve --project-id <uuid> --query <str> \
    [--type <character|setting|foreshadowing|timeline_event|chapter_chunk>] \
    [--top-k <int>] [--min-score <float>] [--json]
    # --top-k 默认 10（config.retrieval_top_k）；--min-score 默认 0.0
    # 结果按 relevance_score 降序
```

### 4.3 输出格式

```bash
# 默认人类可读
✅ 提取完成: character 处理 2 个源（跳过 0），新增 3 更新 2，警告 1 条
⏭ 提取跳过: character 内容未变更（源: chapter 7a4f2c91-...），未调用 LLM
📋 提取状态（project 3f2e1d4a-...）:
  [character] 7a4f2c91-... — ✅ success (新增 2 更新 1, 已索引)
  [setting]   9b1c2d3e-... — ⏭ skipped (内容未变更)
  [character] 5e6f7a8b-... — ❌ error (3 次尝试后仍无法解析为合法 JSON)
✅ 索引完成: character/setting/foreshadowing/timeline_event/chapter_chunk 共 87 条
🔍 检索结果 (query: 林晚右肩的胎记, top 5):
  1. [foreshadowing] 林晚的身世 — 0.82
     （伏笔：林晚的身世。林晚右肩的胎记与女主母亲的信物相同……）

# --json 输出
inkflow extract run --project-id 3f2e1d4a-... --type character --chapters 7a4f2c91-... --index --json
→ {"ok": true, "data": {"type": "character", "status": "success", "processed_sources": 1,
   "skipped_sources": 0, "created": 2, "updated": 1, "indexed": true, "detail": {...}}}

inkflow extract run --project-id 3f2e1d4a-... --type timeline --chapters 7a4f2c91-... --auto-extract --json
→ {"ok": true, "data": {"type": "timeline", "status": "success", "processed_sources": 1,
   "skipped_sources": 0, "created": 2, "updated": 1, "indexed": false, "detail": {...}}}
   # --auto-extract 显式开启（覆盖项目配置）；缺省跟随项目配置 timeline_auto_extract（§2.6）

inkflow extract run --project-id 3f2e1d4a-... --type style --text "……" --json
→ {"ok": true, "data": {"type": "style", "status": "success", "processed_sources": 1,
   "skipped_sources": 0, "created": 0, "updated": 0, "indexed": false, "detail": {...StyleReport...}}}  # 退出码 0（F16 已注册 handler，§6.1）

inkflow extract run --project-id 00000000-0000-0000-0000-000000000000 --type character --text "……" --json
→ {"ok": false, "error": {"code": "NOT_FOUND", "message": "项目不存在"}}  # 退出码 1

inkflow vector retrieve --project-id ... --query "林晚" --json
→ {"ok": true, "data": {"items": [{"entity_id": "...", "entity_type": "foreshadowing",
   "content": "...", "relevance_score": 0.82, "metadata": {...}}]}}
```

---

## 5. 统一提取门面与增量提取算法（横切收敛核心）

> ⚠️ **本节是 F14 与 F9-F13 样板的核心差异点**：F9/F10 的 §5 是「AI 提取管线」，F11 的 §5 是「AI 生成管线」，F12 的 §5 是「一致性检查算法」，F13 的 §5 是「状态机 + F6 注入」；本模块的 §5 是**门面分发 + 增量提取算法 + RAG 索引流程**——不设计新管线（除 F13 移交的伏笔提取与 Q2 拍板的时间线提取，两条均镜像 F9 骨架），而是**编排既有管线**并叠加两块横切能力。

### 5.1 模式总览（门面分发）

```text
 ┌──────────────────────────────────────────────────────────────────┐
 │ 输入: ExtractionRequest {project_id, type, text|chapter_ids, ...} │
 └───────────────────────────────┬──────────────────────────────────┘
                                 ▼
 ① 门面统一校验项目存在（ProjectRepositoryProtocol.get → None → 404「项目不存在」）
 ② 类型注册表查 handler（§6.1）:
    ├─ STYLE → StyleService.analyze（F16 已注册，确定性分析，§6.1）
    ├─ 未注册类型 → UnsupportedExtractionTypeError（422，防御性，枚举已封闭）
    └─ 已注册 → 继续
 ③ 增量判定（§5.2）: 计算源变更集（hash 比对 run 表）
    ├─ 全部未变更 且 not force → 返回 ExtractionResult(status=skipped)，不调用 LLM
    └─ 有变更源 → 逐源执行
 ④ 逐源执行（§5.2/§5.4/§5.5）:
    ├─ character    → CharacterService.extract(text)         （F9 管线）
    ├─ setting      → WorldService.extract(text)             （F10 管线）
    ├─ outline      → OutlineService.generate(prompt/…)      （F11 管线，save 透传）
    ├─ timeline     → 设置项开启: TimelineExtractor.extract(text)（F14 新建管线，§5.5）
    │                  设置项关闭: TimelineService.check_consistency()（F12 确定性检查）
    └─ foreshadowing→ ForeshadowingExtractor.extract(text)   （F14 新建管线，§5.4）
 ⑤ 每源成功后: upsert ExtractionRun（hash/计数/模型/状态，§2.3）
 ⑥ request.index=true 且类型支持 → 索引本次产物（§5.6）
 ⑦ 汇总返回 ExtractionResult（§5.3）
```

**模式要点**:
1. **门面零业务逻辑**：提取/合并/校验语义全部在 F9-F13 管线内（门面不复制），F14 只做分发、增量判定、结果归一与索引编排
2. **项目校验单一入口**：门面统一校验一次（404），委托的各模块 Service 内部会再次校验（幂等，成本可忽略——保持既有模块不感知 F14）
3. **增量判定先于 LLM**：hash 比对是纯本地计算（O(文本长度)），全部未变更时**零 LLM 调用**（验收标准 ②「只处理变更内容」的实证路径）
4. **逐章独立事务**：章节模式下每章「提取 + 合并 + run 更新」顺序执行；某章失败 → 立即抛异常终止，**已成功章已落库并有 run 记录**——重跑时成功章 skip、失败章重试（增量提取的价值演示，§5.2）
5. **失败即异常**（ADR-012）：门面不吞异常；LLM/管线/RAG 错误透传给 router 转 500；run 表记录 error 状态供事后观察
6. **横切能力解耦**：增量追踪（run 表）与 RAG 索引（vector_store）都是门面的可选环节——`force` 可绕过前者、`index` 默认关闭后者，两条能力独立演进
7. **设置项判定在门面层（v1.1，Q2 拍板）**：timeline 的 `auto_extract` 判定（请求显式值 → 项目配置 `timeline_auto_extract` → 默认 false，§2.6）在门面完成——**关闭时不调用 LLM**，直接委托 `TimelineService.check_consistency()`；开启时才进入 `TimelineExtractor`（§5.5）

### 5.2 增量提取算法（只处理变更内容）

**变更指纹 = 源内容 sha256**（UTF-8 hexdigest）。判定规则：

| 场景 | 判定 | 行为 |
|------|------|------|
| 章节模式：run 表中 (type, chapter_id) 的 content_hash == 当前章节 hash，且 not force | **skip** | 不调用 LLM；`skipped_sources += 1` |
| 章节模式：无 run 行 / hash 不同 / force=true | **执行** | 读章节内容 → 管线 → upsert run |
| 手动模式：source_key="manual"，hash 相同，且 not force | **skip** | 同一文本重复提交幂等跳过 |
| outline | **每次执行** | 生成不承诺幂等（每次新内容）（§12 论证） |
| timeline（设置项**关闭**） | **每次执行** | 确定性检查是廉价只读——增量无意义（§12 论证） |
| timeline（设置项**开启**） | **按源 hash 增量** | 章节/文本源与 character 同规则——只处理变更内容，重提取按 `source_chapter_id` 联动更新事件（§5.2 伪代码/§5.5） |
| 章节内容 > 50000 字符 | **422** | 单章超限（分块提取归 Phase 2+，§10） |

**为什么 hash 而非 updated_at（论证）**: 提取语义是**内容驱动**——文本变了才需要重跑；`updated_at` 会因标题/状态等元数据修改而误触发（白跑 LLM），也会因「内容回退到旧版本」而漏触发（hash 相同则结果必然相同，模块合并幂等性保证）。hash 计算成本 O(n)（≤ 50000 字符，微秒级），章节量级 ≤ 数百，全量比对可忽略。**与模块幂等性叠加**：即使 hash 判定失效重跑，F9/F10/F13 的同名合并也是空 diff（F9 spec §5.4 幂等性验收点）——双保险。

**伪代码（门面 extract 的增量环节）**:

```python
async def _resolve_sources(request) -> list[_Source]:
    """计算待执行源列表（含 skip 判定）."""
    if request.type is ExtractionType.OUTLINE:
        return [_Source(key="full", text=None, skip=False)]  # 每次执行
    if request.type is ExtractionType.TIMELINE and not _auto_extract_on(request):
        # 设置项关闭 → F12 确定性检查（只读、无文本输入），每次执行
        return [_Source(key="full", text=None, skip=False)]
    # timeline 设置项开启 → 与 character 相同的章节/文本源增量（hash 判定，§5.5）
    if request.text is not None:
        h = sha256(request.text.encode("utf-8")).hexdigest()
        run = await self._run_repo.get(request.project_id, request.type, "manual")
        skip = run is not None and run.content_hash == h and not request.force
        return [_Source(key="manual", text=request.text, skip=skip)]
    sources = []
    for chapter_id in request.chapter_ids:          # 章节模式
        chapter = await self._chapter_repo.get_chapter(chapter_id.int)  # F2 语义: 不含软删
        if chapter is None:
            raise ChapterNotFoundError()
        if chapter.project_id != request.project_id:
            raise ChapterNotInProjectError()
        if len(chapter.content) > 50000:
            raise ExtractionValidationError("章节内容超过提取上限（50000 字符）")
        h = sha256(chapter.content.encode("utf-8")).hexdigest()
        run = await self._run_repo.get(request.project_id, request.type, str(chapter_id))
        skip = run is not None and run.content_hash == h and not request.force
        sources.append(_Source(key=str(chapter_id), text=chapter.content, skip=skip))
    return sources
```

**执行与 run 更新**:

```python
async def _run_sources(request, sources) -> ExtractionResult:
    """逐源执行管线；失败立即抛异常（已成功源的 run 已落库，重跑自动 skip）."""
    processed = skipped = created = updated = 0
    warnings: list[str] = []
    model: str | None = None
    detail: dict[str, Any] = {}
    for src in sources:
        if src.skip:
            skipped += 1
            continue
        result = await self._dispatch(request, src)   # §5.1 步骤 ④
        processed += 1
        created += _count_created(result)             # 各类型归一化（§5.3）
        updated += _count_updated(result)
        warnings.extend(result_warnings(result))
        model = getattr(result, "model", None) or model
        if processed == 1:                            # detail 保留首个执行源的原始结果
            detail = result.model_dump(mode="json")
        await self._run_repo.upsert(ExtractionRun(
            project_id=request.project_id, type=request.type,
            source_key=src.key, content_hash=src.hash,
            status=ExtractionStatus.SUCCESS,
            created_count=..., updated_count=..., warnings_json=json.dumps(warnings, ensure_ascii=False),
            model=model, indexed=..., run_at=datetime.now(UTC),
        ))
    if processed == 0:
        return ExtractionResult(type=request.type, status=ExtractionStatus.SKIPPED,
                                skipped_reason=f"内容未变更（源: {sources[0].key}）",
                                processed_sources=0, skipped_sources=skipped)
    return ExtractionResult(type=request.type, status=ExtractionStatus.SUCCESS,
                            processed_sources=processed, skipped_sources=skipped,
                            created=created, updated=updated, warnings=warnings,
                            model=model, indexed=..., detail=detail)
```

**失败语义（关键设计）**: 章节模式批量执行时，第 N 章 LLM/解析失败 → 门面抛异常（router 500），**第 1..N-1 章已落库 + 已有 run 记录**；用户重跑同一请求 → 成功章 hash 相同 skip、失败章重新执行。`extract status` 可见「哪些章成功、哪些章缺 run（失败缺口）」。这与 F9 单文本「合并阶段不重试」语义一致（落库数据不可重复合并），且天然构成「断点续跑」——**增量提取验收标准 ② 的核心实证**。

### 5.3 统一结果结构（ExtractionResult 语义）

| 维度 | character | setting | outline | timeline | foreshadowing |
|------|-----------|---------|---------|----------|---------------|
| created 口径 | 新建角色数 | 新建条目数 | save=true 且新建 → 1；预览 → 0 | 开启：新建事件数；关闭：0（检查无产物） | 新建伏笔数 |
| updated 口径 | 更新角色数 | 更新条目数 | 0 | 开启：更新事件数；关闭：0 | 更新伏笔数 |
| detail | CharacterExtractionResult（含 relations_*） | WorldExtractionResult | OutlineGenerationResult（outline/plot_points/arcs 或 preview） | 开启：TimelineExtractionResult；关闭：ConsistencyReport（conflicts/flashbacks/consistent） | ForeshadowingExtractionResult |
| model | 实际模型 | 实际模型 | 实际模型 | 开启：实际模型；关闭：None | 实际模型 |
| warnings | 合并/解析警告 | 同左 | 生成/落库警告 | 开启：解析/合并警告；关闭：无（确定性） | 解析/合并警告 |
| indexed 生效 | ✅ | ✅ | ❌（warning「outline 类型不支持自动索引」） | 开启：✅（提取事件索引 timeline_event）；关闭：❌（同左 warning） | ✅ |

> `indexed` 对 outline 恒为 False、对 timeline 关闭时恒为 False，且**不报错**（忽略 + warnings 提示）——索引对象是实体档案（§2.4），大纲/检查无对应档案；timeline 开启时提取的事件是 F12 实体档案，`index=true` 生效（索引为 timeline_event）；全量索引用 `vector reindex --type timeline_event`（事件档案来自 F12，§5.6）。

### 5.4 伏笔提取管线（ForeshadowingExtractor — F13 移交，F14 新建 LLM 管线之一）

**现状**: F13 spec §10 明确「伏笔 AI 提取 / 回收自动检测归 F14 统一提取服务」——F13 无 LLM 管线（状态追踪与注入均为确定性实现），伏笔档案目前只能手工建档。

**管线设计**（镜像 F9 `_character_extractor.py` 骨架，仅替换领域实体与模板）:

```text
① 校验项目存在 —— 由门面统一负责（§5.1），extractor 不重复
② 取候选章号清单 —— chapter_repo 分页取满项目章节（首页 offset=0；续页 offset=已取条数，
   limit=100；total 缺失/空页即停），构造「序号: 标题」逐行文本（序号自 1 起；无章节 → 空串）
③ 渲染 foreshadowing_extract.yaml（PromptManager，变量: text, chapters）
④ LLMClient.chat(model or project.config.model, temperature=0.2)
⑤ 解析 JSON → Pydantic schema 校验（ExtractedForeshadowing）
   → 非法条目跳过 + warning
⑥ 修复式重试 ≤ 2 次（附错误信息）→ 仍失败 → ForeshadowingExtractionError
⑦ 章号映射: first_chapter_number ∈ [1, len(chapters)] → 对应章节 UUID；
   越界 / 清单为空 / None → None（宽容降级，不抛错、不丢条目）
⑧ 合并落库（§5.4 合并策略）: 按 (project_id, title) 匹配活动伏笔 →
   存在=更新(非空字段覆盖，含 first_chapter_id) / 不存在=创建（priority 默认 50）
⑨ 返回 ForeshadowingExtractionResult（created/updated/warnings + model）
```

**模板 `foreshadowing_extract.yaml`**（§5.2 结构同 character_extract.yaml）:

```yaml
name: foreshadowing_extract
description: 从章节文本提取伏笔埋设（结构化 JSON 输出）
system_prompt: |
  你是小说伏笔提取器。从给定的章节文本中提取作者埋设的伏笔（暗示未来
  情节发展的细节、物件、承诺、秘密），以及已有伏笔的进一步铺垫更新。
  只提取文本中直接出现的或明确暗示的信息，不要臆造。
  输出严格 JSON，不要输出任何其他文字，格式如下：
  {
    "foreshadowings": [
      {"title": "伏笔名（短，如『铜镜的秘密』）", "description": "伏笔内容与预期回收方式或空",
       "location": "埋设位置描述或空（如『第 5 章·林晚沐浴场景』）",
       "first_chapter_number": 首次埋设章节的序号（必须严格取自下方「章节候选清单」中的序号；
                               清单为空或无法确定时填 null）}
    ]
  }
  foreshadowings 中不要包含重复的伏笔名。
human_prompt: |
  章节候选清单（序号: 标题）：
  {chapters}

  章节文本：
  {text}
variables:
  - text
  - chapters
```

**合并策略（复用 F13 档案约定）**:

| 情况 | 行为 | 计入 |
|------|------|------|
| 项目内存在同名**活动**伏笔 | 非空提取字段覆盖（description/location/**first_chapter_id** 独立判断；本次未选出章号 → 保留既有值），**不重置 status**（open/resolved 原样保留），更新 updated_at | `updated` |
| 不存在 | 创建新伏笔（status=open，priority=50，event_id=None，first_chapter_id=映射值或 None） | `created` |
| 存在但已**软删除** | 视为不存在 → 创建新档案（partial unique 允许；warning「存在已删除的同名伏笔档案」） | `created` + warning |
| 提取字段非法（title 空/超长等） | 该条跳过 | `warnings` |

> **MVP 不自动回收（不做「正文 → 伏笔兑现」识别）**: 回收检测的误报成本高（「伏笔提及 ≠ 伏笔回收」，作者意图无法从文本可靠推断），且 F13 状态机语义（resolved 是作者对「已兑现」的确认）不适合自动迁移；自动回收归 Phase 2+（F15 审计需要时，见 §10）。**合并锚点 = F13 partial unique `(project_id, title)`**——F13 spec §12 已声明「同名唯一为 F14 提取提供合并锚点」，本节兑现该承诺。

**幂等性**: 对同一文本重复提取，第二次应产出空 created/updated（全部命中已有档案，非空覆盖后值不变）——与 F9/F10 相同的验收点。

### 5.5 时间线提取管线（TimelineExtractor — F14 新建 LLM 管线）

**背景**: timeline 类型初始仅委托 F12 确定性检查；「章节文本 → 时间线事件」提取纳入 MVP，且 AI 自动化须由设置项控制是否开启（§2.6）。**两种语义并存，由 `timeline_auto_extract` 设置项切换**：开启 = 本节提取管线（新建/更新 F12 事件档案）；关闭 = F12 `check_consistency`（§5.1 步骤 ④ 分发）。

**管线设计**（镜像 F9 `_character_extractor.py` 骨架，仅替换领域实体与模板）:

```text
① 校验项目存在 —— 由门面统一负责（§5.1），extractor 不重复
② 渲染 timeline_extract.yaml（PromptManager，变量: text）
③ LLMClient.chat(model or project.config.model, temperature=0.2)
④ 解析 JSON → Pydantic schema 校验（ExtractedTimelineEvent）
   → 非法条目跳过 + warning
⑤ 修复式重试 ≤ 2 次（附错误信息）→ 仍失败 → TimelineExtractionError
⑥ 合并落库（§5.5 合并策略）: 按 (project_id, title, source_chapter_id) 匹配活动事件 →
   存在=非空字段覆盖 / 不存在=新建（time_value=None、narrative_position=LLM 输出或 None、
   timeline_flag 透传）/ 软删同名同章=新建 + warning
⑦ 返回 TimelineExtractionResult（created/updated/warnings + model）
```

**LLM 输出 schema `ExtractedTimelineEvent`**（Pydantic 校验，字段级非法 → 跳过 + warning）:

| 字段 | 类型 | 说明 |
|------|------|------|
| title | str（必填，1-100 字符） | 事件标题 |
| description | str \| None | 事件描述（该时刻发生了什么；None = 不覆盖） |
| time_value | float \| None | 世界内时间数值键（无法推断 → null；校验同 F12：有限且 \|v\| ≤ 1e12） |
| time_unit | str \| None | 时间单位标签（纪元/年/月/日/时；None = 不覆盖）。**仅在确实解析出 `time_value` 时有意义**——解析不出值时管线留空（防「假非空」，§5.5 时间表达契约） |
| time_display | str \| None | **原文时间表达**（照抄文本，如「三月初二」「觉醒前世记忆后两年」）；≤ 100 字符、去空白；None = 不覆盖。**解析不出累计天数时必须保留本字段**（原文表达不得丢，§5.5 时间表达契约） |
| narrative_position | int \| None | 叙事位置（LLM 输出或 null——新建时 null = F12 追加语义） |
| timeline_flag | str \| None | 时间线标记（""/flashback/flashforward；None = 不覆盖） |

**模板 `timeline_extract.yaml`**（结构同 character_extract.yaml）:

```yaml
name: timeline_extract
description: 从章节文本提取时间线事件（结构化 JSON 输出）
system_prompt: |
  你是小说时间线事件提取器。从给定的章节文本中提取「世界内发生的事件」：
  事件本身、时间、叙事位置与倒叙/插叙标记。事件是实例——同一事件可能在
  多个章节被提及，本章新出现的事件才提取；已提过的事件只输出更新信息。
  只提取文本中直接出现的或明确暗示的信息，不要臆造。
  time_display 填该事件在**原文中的时间表达，原样照抄**（如「三月初二」
  「觉醒前世记忆后两年」）；文本未给出任何时间线索时输出空串。
  time_value 统一为**项目内累计天数**（自故事起点起算的连续天数），time_unit 恒为「日」；
  无法把 time_display 换算为累计天数时 time_value 输出 null——此时 time_unit 也输出空串，
  但 time_display **必须保留原文表达**（不得两者都空）。
  不要用「本章第几天」这类段内相对计数器，也不要臆造纪元/年份/月份等时间轴。
  叙事位置 = 事件在本章叙事中出现的先后（从 1 开始）；无法判断输出 null。
  叙事位置**仅在本章内有意义**（章内序，系统会自行换算为全局序），不要跨章延续编号。
  timeline_flag 只取以下值之一（无标记输出空串）：
  ""（正叙，默认）、"倒叙"（本章叙述顺序早于其世界内时间的回溯段落）、
  "插叙"（本章叙述顺序晚于其世界内时间的预叙/前瞻段落）。
  输出严格 JSON，不要输出任何其他文字，格式如下：
  {
    "events": [
      {"title": "事件标题（短，如『林晚入宫』）", "description": "该时刻发生了什么或空",
       "time_display": "三月初二", "time_value": 3.5, "time_unit": "日",
       "narrative_position": 1, "timeline_flag": ""}
    ]
  }
  events 中不要包含重复的事件标题。
human_prompt: |
  章节文本：
  {text}
variables:
  - text
```

**合并策略（匹配键 `(project_id, title, source_chapter_id)`）**:

| 情况 | 行为 | 计入 |
|------|------|------|
| 项目内存在同 (title, source_chapter_id) 的**活动**事件 | 非空提取字段覆盖（title/description/time_value/time_unit/**time_display**/narrative_position/timeline_flag **独立判断，不动 None 未知值**），更新 updated_at | `updated` |
| 不存在 | 创建新事件（source_chapter_id=当前章节；`time_value`/`time_display` = LLM 输出（未解析出则为 `null` → 落 `None`/空串）；`time_unit` 仅在 `time_value` 非 None 时落值、否则空串——见 §5.5 时间表达契约；narrative_position=LLM 输出或 None——None 走 F12 追加语义、timeline_flag 透传） | `created` |
| 存在但已**软删除** | 视为不存在 → 创建新事件 + warning「存在已删除的同名同章事件」 | `created` + warning |
| 提取字段非法（title 空/超长、time_value 越界等） | 该条跳过 | `warnings` |

> **匹配逻辑在服务层**: F12 事件表**无任何唯一约束**（事件是实例而非档案，F12 spec §2.4）——同名同章匹配由 TimelineExtractor 经 `TimelineRepositoryProtocol.list_by_chapter` 拉取该章事件后按 title 比对完成，**表结构不引入唯一索引**（跨模块 MODIFY F12 仅加列 + FK + 索引，§8）。

**写前分流 + 后置时间归一**：合并阶段的**新建**分支前追加一步：

1. 若 `ee.time_value is None` 且 `ee.time_display` 非空 → 调 `parse_time_display(ee.time_display)`
   （`domain/services/_timeline_text_time.py`，**确定性、零 LLM**，[f12 §2.9](../f12-timeline/spec.md) Z2）；
2. 解析成功 → 用解析出的 `value` / `unit` / `era` 填该事件的 `time_value` / `time_unit`（`era` 非空时一并写入；
   `time_display` **原样保留**）；
3. 解析失败 / 仍无值 → **不调用 `repo.add`**（正式表零变更，Z1），该事件进 `TimelineExtractionResult.pending`
   并记 `reason`（门面据此落暂存，Z3）；
4. `time_unit` 仅在 `time_value` 非 None 时落值（时间表达不变量保持）。

**干跑（`dry_run=True`，含 `stage=True`）行为不变**：`pending` 为空、全部 would-be 新建照旧进 `created`
（暂存批次级路径依赖该口径）。**存量已落库的未定事件不回溯改写**（Z5）。

**事件-章节联动语义（精确提取 + 事件与章节联动）**:

| 场景 | 行为 |
|------|------|
| 章节内容变更（hash 变化） | 重提取该章 → 同 (title, source_chapter_id) 事件被更新（非空覆盖）、新事件创建——**只增改不删除** |
| 章节软删 | 事件**保留** source_chapter_id（历史来源锚点；章节列表不可见但事件档案可追溯来源） |
| 章节硬删 | FK ON DELETE SET NULL → source_chapter_id 置 None（事件保留、来源解除——同 F13 event_id 硬删语义） |
| 提取时事件不再出现于章节 | **不删除**（移除事件的自动删除归 Phase 2+，§10） |
| 手工事件（source_chapter_id=None） | 不参与提取合并匹配（匹配键含来源章；跨章同名 = 不同事件） |

**幂等性**: 对同一文本重复提取，第二次应产出空 created/updated（全部命中已有事件，非空覆盖后值不变）——与 F9/F10/F13 相同的验收点。

**时间表达契约**：

时间字段的两个失效形态（世界序视图满屏「未知」、一致性检查无输入）源于：① 管线在新建落库处**硬编码** `time_display=""`；② 提示词未要求该字段。契约如下（治根 + 展示兜底）：

| # | 契约 |
|---|------|
| T1 | **每事件必须给 `time_display`**（原文时间表达，照抄文本）；文本无任何时间线索 → 空串 |
| T2 | 解析不出累计天数 → `time_value = null` **但 `time_display` 必须保留**（不得两者都空） |
| T3 | `time_unit` 仅在**确实解析出 `time_value`** 时写入；未解析出值 → 留空（防「假非空」：rc1 的 `time_unit='日' ×182` 即此类噪声，会掩盖真实缺口） |
| T4 | **不变量不回归**：§2.7 S10「单位固定（日）+ 项目内累计时基 + 不确定即 null」语义不变；`time_display` 是**展示面兜底**，不参与排序 / 一致性检查（同 F12 §2.7 S6「归一用比较、不回写库」的精神） |
| T5 | 前端（方案 C）世界序取值链**优先消费 `time_display`**（原文），两者皆空才落「未知」占位——前端既有实现已满足（`timeline-axis-labels.ts` 的 `axisLabels` 与 `timeline-era-axes.ts` 的 `timeScaleText`），本轨以契约测试**守护**（防后续改动回归） |

**契约测试**: `tests/unit/domain/services/test_timeline_extractor.py::TestTimelineTimeDisplayContract1526`（管线保留原文 / 非空率 > 80% / `time_unit` 防假非空 / 更新覆盖）+ `TestTimelineExtractPromptContract1526`（zh/en 提示词必须要求 `time_display`）+ 前端 `timeline-axis-labels.test.ts`（原文兜底 C1-C3）。

**设置项切换（门面层判定，§2.6）**: `auto_extract=false`（请求/CLI/项目配置任一显式关闭）→ 门面**不调用 LLM**，直接委托 `TimelineService.check_consistency()`（§5.1 步骤 ④）；`auto_extract=true` → 进入本节提取管线。判定顺序：请求显式值 → 项目配置 `timeline_auto_extract` → 默认 false。

### 5.6 RAG 索引流程（ADR-013 首次落地）

**基础设施**（§8）: `infrastructure/rag/langchain_vector_store.py` 实现 `VectorStoreProtocol`：

```python
class LangChainVectorStore:
    """VectorStoreProtocol 实现 — LangChain Chroma + 本地 Embedding（ADR-013）.

    - 每 EntityType 一个 collection（config.vector_store_collections，
      collection 名 = f"inkflow_{entity_type.value}"）
    - 项目隔离 = metadata.project_id 过滤（查询 always 带 project_id，Protocol 强制）
    - embeddings 由构造注入（生产 HuggingFaceBgeEmbeddings(BAAI/bge-small-zh-v1.5)，
      测试 FakeEmbeddings）——BGE 模型首次使用需联网下载 ~100MB，懒加载（§7/§11 影响）
    - chromadb 同步 API 用 asyncio.to_thread 包装（不阻塞事件循环）
    - chromadb 客户端统一传 Settings(anonymized_telemetry=False)（关闭匿名遥测，
      本地运行数据不出本机）
    - 距离度量 cosine；relevance_score = 1 - distance
    """

    def __init__(self, persist_dir: Path, embeddings: Embeddings) -> None: ...

    async def index(self, entity: IndexableEntity) -> None: ...        # upsert by id
    async def index_batch(self, entities: list[IndexableEntity]) -> None: ...
    async def retrieve(self, query, *, project_id, entity_types=None,
                       top_k=10, min_score=0.0) -> list[RetrievedEntity]: ...
        # 每类型查对应 collection（where={"project_id": project_id}），
        # 合并后按 relevance_score 降序取 top_k；score < min_score 过滤
    async def delete(self, entity_id: str, entity_type: EntityType) -> None: ...
    async def delete_project(self, project_id: str) -> int: ...
        # 遍历 5 个 collection，collection.delete(where={"project_id": project_id})，返回删除总数
```

**索引内容构建（IndexableEntity → 档案文本投影）**:

| EntityType | 数据源 | content（投影） | metadata |
|-----------|--------|-----------------|----------|
| `character` | F9 角色档案 | `姓名：{name}\n性格：{personality}\n背景：{background}\n目标：{goals}` | `{name, status?}` |
| `setting` | F10 世界设定 | `名称：{name}\n分类：{category}\n内容：{content}` | `{name, category}` |
| `foreshadowing` | F13 伏笔档案 | `伏笔：{title}\n{description}\n（埋设位置：{location}）` | `{name, status}` |
| `timeline_event` | F12 事件档案 | `事件：{title}\n{description}\n时间：{time_value} {time_unit}\n叙事位置：{narrative_position}` | `{title, timeline_flag, chapter_id?}`（chapter_id = source_chapter_id——来自章节提取的事件写入，手工建档/未知来源省略；供按章节过滤检索结果） |
| `chapter_chunk` | F2 章节内容（分块） | 块文本（切片策略模式按 mode 切分，§5.6.1；默认 fixed ~500 字） | `{chapter_id, chapter_title, chunk_index, chapter_x, chapter_y, volume_title?, chunk_start, indexed_at}` |

- `IndexableEntity.id` = 实体 UUID 字符串；章节分块 overlap=0 时 = `f"{chapter_id}:{idx}"`（现状），overlap>0 时 = `f"{chapter_id}:{idx}:{start_offset}"`（§5.6.3）→ Chroma upsert 幂等
- `metadata` 自动附带 `project_id`（检索过滤键）
- 分块规则（`domain/services/_chunking.py` 纯函数，切片策略模式）: 见 §5.6.1-§5.6.7——三档切片（fixed/paragraph/dialogue/llm）+ 滑动重叠 + 元数据补强；默认 fixed（现状 ~500 字标点回溯无重叠）保持存量行为与向量不变

**索引触发（两种路径）**:

| 路径 | 入口 | 行为 | 用途 |
|------|------|------|------|
| **增量索引** | `extract` 带 `index=true` | 提取成功后，本次 created/updated 实体（character/setting/foreshadowing/timeline（开启时提取的事件））→ index_batch；章节模式额外索引该章 chapter_chunk | 日常提取即索引（按需开启） |
| **全量重建** | `vector reindex` / POST vector/reindex | 从各模块仓储全量拉取档案（分页循环 `list(limit=100)`；timeline 用已有 `list_all`；章节用 `list_chapters` 分页循环）→ index_batch | 升级/初始化/索引修复（幂等 upsert，可重复执行） |

**批量索引分片**: `LangChainVectorStore._index_batch_sync` 内按模块常量
`_EMBED_MAX_INPUTS_PER_REQUEST`（64 条 = zhipu embedding-3 单请求 input 上限）分片调用
`embed_documents` 后合并，再一次性 upsert —— 实体总数 > 64 的项目重建索引不再因上游
400 code 1214（「input数组最大不得超过64条」）中断；合并顺序 = 有效实体顺序（`_probe_embedding`
取末条与分片前语义一致）。单条路径 `_index_sync` 逐条提交，不受影响。该常量与空串守卫正交
（先过滤空白 content，再对有效集分片）；接入第二个 embedding provider 时改为按 provider 取值。

**检索入口**: `vector retrieve` / POST vector/retrieve（§3/§4）。**不接入 F3/F6 写作链路**（RAG 注入写作上下文归 Phase 2+ 联调，见 §10——MVP 只交付「能索引、能检索」的实证闭环）。

**RAG 可用性策略**:

| 场景 | 行为 |
|------|------|
| vector_store 未装配（deps 初始化失败） | `RAGUnavailableError`（**503 + Retry-After**）——不影响非 RAG 功能（extract 不带 index 照常工作） |
| BGE 模型首次下载（~100MB，需网络） | 懒加载：首次 index/retrieve 时初始化（deps 层模块级单例缓存）；失败 → RAGUnavailableError（**503 + Retry-After**，消息提示联网/重试） |
| chroma 持久化目录不可写 / 损坏 | `VectorStoreError`（500，loguru 记录） |
| retrieve 无结果 | 200 + 空 items（正常路径，同 F9 空搜索） |

#### 5.6.1 切片策略模式（ChunkingMode — 四档可配）

将单一 `chunk_text` 扩展为**策略模式**：一个入口按 `mode` 分发到切片器，为对话/LLM 档预留统一接口。三档成本递增（docs `rag-vector-enhancement-requirements.md` §2.1 已定）：**段落（零成本）< 对话（纯规则零 LLM）< LLM 分析（token 成本）**。

```python
# domain/services/_chunking.py（扩展，纯函数 + 零框架依赖，ADR-002/015）

class ChunkingMode(StrEnum):
    FIXED = "fixed"            # 固定字符切片（现状：~500 字标点回溯，无重叠）
    PARAGRAPH = "paragraph"    # 段落切片（空行切分 + 超长段降级标点回溯）
    DIALOGUE = "dialogue"      # 对话切片（说话人切换 + 短块合并）
    LLM = "llm"                # LLM 语义分析切片（注入 analyzer + 失败降级）

@dataclass
class Chunk:
    text: str          # 块文本
    start_offset: int  # 块在原文中的起始字符偏移（0-based；overlap 块 id 用）

def chunk_text(
    text: str,
    *,
    mode: ChunkingMode = ChunkingMode.FIXED,
    chunk_size: int = 500,
    overlap_ratio: float = 0.0,
    analyzer: Callable[[str], list[int]] | None = None,  # 仅 LLM 档注入
) -> list[Chunk]: ...
    # 空文本 → []；chunk_size <= 0 → ValueError（保持既有契约，§7）
```

- `mode` / `chunk_size` / `overlap_ratio` 来自全局设置（app_settings，§5.6.3/§5.6.5）；`analyzer` 仅 LLM 档由装配层注入（`_chunking.py` 零 LLM import）。
- 三档共享 `Chunk{text, start_offset}` 返回结构与块 id 规则（§5.6.3）；overlap=0 时 FIXED 行为与现状逐字一致（向后兼容，存量向量无需重建）。

#### 5.6.2 段落切片器

```text
规则（纯函数 _chunk_paragraph）:
① 按空行（连续 \n\n）切分为段落（单 \n 不切，保留段落内换行）
② 单段长度 <= chunk_size → 直接作为一块
③ 单段长度 > chunk_size → 降级标点回溯（复用 FIXED 逻辑：从边界向前找 。！？\n 切分）
④ 空文本 → []；chunk_size 可配（默认 500，范围 100-2000）
```

- 段落边界贴合小说「空行分段」语义结构；超长段降级保证单块不超 chunk_size（embedding 质量与固定档一致）。
- `chunk_size <= 0` → ValueError（与 FIXED 同契约）；`chunk_size` 越界（<100 或 >2000）由 app_settings 校验层 422（§5.6.3）。

#### 5.6.3 滑动重叠开关（默认关）

```text
全局设置（app_settings，§2 数据模型 + §8 跨模块 MODIFY F32 settings）:
  rag_chunk_overlap       : bool  = False   # 重叠开关，默认关
  rag_chunk_overlap_ratio : float = 0.15    # 重叠比例，范围 [0.10, 0.20]
```

- **块 id**：overlap=0 → `{chapter_id}:{idx}`（现状不变）；overlap>0 → `{chapter_id}:{idx}:{start_offset}`（重叠块 idx 不足以唯一标识，追加字符偏移）。
- **检索去重**：overlap>0 时相邻块共享内容，检索合并按 `(entity_type, 源实体 id)` 去重取最高分再截断 top_k——chapter_chunk 的「源实体 id」= `chapter_id`（章节）非块 id（同章节多块命中只留最高分一条，杜绝相邻重复块刷屏，QA §P1-1）。
- **不变式**：overlap=0 保持「拼接还原原文」不变式；overlap>0 打破该不变式 → 断言改为弱不变式「原文每字符至少被一个块覆盖」（§9，QA §4.1-A4）。

#### 5.6.4 检索元数据补强

chapter_chunk 的 `metadata` 在现有 `{chapter_id, chapter_title, chunk_index}` 基础上新增（全部 `str|int|float`）：

| 键 | 类型 | 说明 |
|----|------|------|
| `chapter_x` | int | 全书第 x 章（按 order_index 排序，1-based） |
| `chapter_y` | int | 全书共 y 章（章节总数） |
| `volume_title` | str? | 所属卷标题（有 volume_id 时；无卷项目省略） |
| `chunk_start` | int | 块起始字符偏移（供定位；overlap 时与 start_offset 一致） |
| `indexed_at` | str | 索引时间戳（ISO 8601，reindex 统一写入） |

- `_map_retrieved` 延续 `.get()` fallback 约定（旧数据缺键不崩：`metadata.get("chapter_x")` 等，缺失回退现状展示，QA §P2-1）——**任何新代码禁止直接 `metadata["chapter_x"]` 下标访问**。
- 章节 x/y 语义与卷信息表达见 §12 决策 24。

#### 5.6.5 切片参数纳入指纹（不重定义协议）

复用既有指纹协议（`domain/models/vector_fingerprint.py` 的 `ChunkingFingerprint{mode, chunk_size, overlap_ratio, chunker_version}` 已存在）——**本 spec 只声明装配接线，不重定义协议**：

- reindex 装配时从 app_settings 读取切片配置快照 → `build_fingerprint(chunking={mode, chunk_size, overlap_ratio, chunker_version})` 写入指纹（`_extraction_rag.py` reindex 的 `_fingerprint_provider`）。
- 任一字段变更（含 `chunker_version` 手动 bump）→ `compare_fingerprints` 报 `chunking_changed` → stale → GUI/CLI 提示重新向量化（复用 status 端点 + 警告条）。
- `chunker_version` 语义：切片算法改版手动 +1（对话/LLM 切片器边界规则调整、LLM analyzer 换 prompt 等不可复现变更），强制触发 stale（QA §P2-2 chunk id 漂移管控）。

#### 5.6.6 对话切片器

```text
规则（纯函数 _chunk_dialogue）:
① 说话人切换识别：中文对话形态——引号（「」“”）开头、破折号（——）开头、冒号+引号（：“）等
   标记对话起始；连续对话归并为一块
② 短块合并：对话块长度 < min_dialogue_len（默认 100 字符）→ 合并邻近叙述上下文
   （向前合并，保持时间顺序）
③ 无对话文本（无引号/破折号标记）→ 降级段落切片（§5.6.2，不产生空块）
④ 空文本 → []
```

- 纯规则零 LLM 成本；识别规则易错（中文对话形态多样），M4 落地前需真实对话体样本验证（QA §2.5 Q2.5）。
- 说话人切换点 = 语义边界（一段对话 = 一个完整情境），召回片段自洽（docs §2.1）。

#### 5.6.7 LLM 分析切片器

```text
规则（装配层注入 analyzer，_chunking.py 保持纯函数）:
① 语义切分：analyzer（LLM 回调，复用 F5 LangChainLLMClient + llm_chunk.yaml 模板）
   返回语义边界偏移列表 → 按边界切分
② 增量：复用 F14 _content_hash（sha256，extraction_runs.content_hash）——内容未变的章节
   跳过 LLM 分析（直接复用上次切片结果 / 跳过重灌），控制「重新向量化」成本（QA §P2-2）
③ 失败降级：analyzer 异常 / 未配置对话模型 / 超时 → 降级段落切片（§5.6.2）+ logger.warning
   ——不允许 reindex 整体失败（QA §4.1-A3）
④ chunk id 漂移管控：LLM 输出非确定（同章两次切分边界不同）→ 变更时手动 bump chunker_version
   触发 stale（§5.6.5），避免残留（QA §P2-2）
```

- LLM 档成本最高（每次重建 token 成本），选择时 GUI/CLI 预估 token（docs §2.3）。
- `_chunking.py` 通过 `analyzer: Callable[[str], list[int]] | None` 注入，domain 层零 LLM import（ADR-015）；analyzer 装配在 deps/装配层（复用 F5 LLMClient，未配置对话模型 → 降级段落 + warning，§7）。

#### 5.6.8 hnsw 段就绪判定与读侧自愈

**缺陷**：全新 collection（或「写完 A collection 再写 B collection」）之后，目标 collection 的 `retrieve` 恒 500 ——
`向量检索失败：chromadb hnsw 段读取失败（<entity_type>）`；对同一 collection 再做一次写之后才可读。

**根因（chroma 1.5）**：每个 collection 有 `METADATA`（sqlite）与 `VECTOR`（hnsw-local-persisted）两个 segment；
一次「别的 collection 的写」会把本 collection 的 `METADATA.max_seq_id` 推前、而 `VECTOR.max_seq_id` 原地不动。
带 `where` 的读 plan 要求两段一致，于是抛 `Error finding id`（冷启动未落盘时同族报 `Nothing found on disk`）。
**等待不恢复**——只有对**本 collection** 再发生一次写才触发 pending log 的 apply；`reindex` 的 commit-last 指纹写
（`inkflow_meta`）恰是最后一次写，故 reindex 返回后目标 collection 必然不可读。

**契约**：

| 项 | 规则 |
|----|------|
| 段就绪判定（读侧自愈） | `_retrieve_sync` 首次 `InternalError` 后取该 collection 内本项目一条现存记录、把 metadata **原样回写**（chroma `update` 只替换传入字段 → document/embedding 不动，数据面语义零变化）以触发 pending log apply，再重试真实查询 |
| 写次数有界 | `_SEGMENT_HEAL_MAX_WRITES` = 2；**不做墙钟等待**（等待无效） |
| 文案 | `VectorStoreError` 消息「向量检索失败：chromadb hnsw 段未就绪（<entity_type>），请重试一次」——不指引重建索引 |
| 不采用 | 读侧固定次数重试 + 固定时间预算（等待无效，已删除该路径）；写侧 flush 探针保持不变 |

**回归锁定**：`tests/unit/infrastructure/rag/test_vector_segment_ready_1563.py` 4 条（根因断言 / 空写须为元数据 no-op / 文案 / 写次数有界），全部确定性；既有契约（清晰上抛、恒失败不上抛、写侧落盘自检）不回归。

### 5.7 横切收敛 vs 实体样板：差异对照表

| 维度 | F9/F10 提取（样板） | F11 生成（样板） | F12 检查（样板） | F13 追踪（样板） | F14 门面（本模块） |
|------|--------------------|--------------------|------------------|------------------|------------------|
| 建模对象 | 新实体档案（角色/世界） | 新实体档案（大纲三件套） | 新实体档案（事件） | 新实体档案（伏笔） | **无新实体**（收敛既有档案；跨模块 MODIFY F12 事件实体加 source_chapter_id） |
| 输入 | 章节文本（必填） | 项目设定 + 约束 | 事件档案（库内） | 伏笔档案（库内） | 统一 ExtractionRequest（类型决定输入） |
| 引擎 | LLM 提取 | LLM 生成 | 确定性算法 | 确定性状态机 | **编排**（委托上述四类 + 新建伏笔/时间线提取） |
| 新增管线 | 1 条 | 1 条 | 0 | 0 | **2 条**（foreshadowing，F13 移交 + timeline，Q2 拍板）+ 0 条重写 |
| 增量 | 无（重复提取 = 空 diff 幂等） | 无（不承诺幂等） | 无（只读） | 无（状态迁移幂等） | **hash 变更追踪，只处理变更源**（验收 ②） |
| RAG | 无 | 无 | 无 | 无 | **ADR-013 首次落地**（验收 ③） |
| 落库 | 同名合并（单事务） | 生成即新建 | 无副作用 | 状态迁移 | 委托各模块落库 + run 记录 upsert |
| 错误面 | LLM_ERROR + 提取错误 | LLM_ERROR + 生成错误 | 无 LLM | 无 LLM | LLM_ERROR + EXTRACTION_ERROR + RAG_ERROR（UNSUPPORTED_TYPE 已随 F16 删除） |
| 测试方式 | Mock LLM 分支 | Mock LLM 分支 | 快照断言 | 表驱动状态机 | Mock 各模块服务 + FakeEmbeddings + 临时 chroma |

---

### 5.8 提取写入策略（类别归属 / 近义合并 / 粒度 / dry-run / 批次回滚）

> **背景**：`extract run --type character|setting` 若无写入约束会大幅冲稀设定库（同库条目成倍膨胀），
> 且类别归属被压平（提取条目落在项目分类体系之外，GUI 分类视图里被压平）。
> 本节定义五条收敛策略，**仅对 character / setting 生效**（其他类型传 `granularity != fine`
> 或 `dry_run=true` → 422，§6.4）。

#### 5.8.1 类别归属（setting）

- 提取前读取项目已有分类清单（`WorldRepositoryProtocol.list_world_categories`）；
  清单**不可判**（仓储为 Mock / 未实现该方法 / 非列表返回）→ **跳过类别校验**
  （保持既有语义；既有单测替身依赖该守卫）。
- 渲染模板时把清单以 `{categories}` 变量注入（空清单 →「（无）」），引导 LLM 从既有分类中选择。
- **落库前严格校验**：LLM 输出 `category`
  （strip 后）**非空且不在项目已有分类集合中** → **拒绝整批**：
  - 抛 `WorldCategoryNotRegisteredError`（422），消息**列出全部缺失分类名**
    （去重、保留首次出现顺序），供 agent / CLI 据此建类；
  - 该批次**正式表零写入**（批次内已合法的条目同样不落库）；
  - **禁止**自动建类（不提供 `auto-create`）。
- **项目无任何分类时同样拒绝**：清单**可判**（真实仓储返回列表）但为空 ⇒ LLM 产出的
  任何非空类别都属「未注册」→ 拒绝。
- **空类别（LLM 主动留空）不拒绝**：prompt 明确「无法判断时留空」→ 维持
  「未分类」语义（落空串）。**拒绝口径仅覆盖「非空但未注册」的类别。**
- **与复制路径的语义区分（重要）**：`world copy --auto-create-categories` 是**复制路径**
  的**用户显式开关**（用户主动要求自动建类），行为**不变**；本节约束的是**提取路径**
  的**默认行为**（缺类别则拒绝）。二者不冲突，勿混用。

> **拒绝的落点 = 两条写回路径的单一漏斗**：直接写（`stage=false`）与两段式暂存
> （`stage=true`，§5.9）都经 `_world_extractor._merge` 的**同一**预检 —— 暂存路径下
> 管线以 `dry_run=true` 调用同一函数，故 stage 提取在**落暂存之前**即被拒绝：
> 暂存区零行、`confirm_staged` 无物可物化（物化侧无后门，无需另设闸门）。

#### 5.8.2 合并而非新建（character / setting）

条目匹配按三档顺序（`_normalize_name` = 去首尾及**全部内部空白**）：

| 档 | 判据 | 行为 |
|----|------|------|
| ① 同名 | 归一化后相等 | 走既有「非空字段覆盖」更新（幂等：无变化不写、不计 updated） |
| ② 近义 | 归一化后**互为子串**，且较短者长度 ≥ 2 且 ≥ 较长者长度的 50% | 合并到已有条目：保留已有 `name` / `category` / `parent_id` / `extra`，`content` 以 `\n\n` 追加（已包含该段则幂等跳过）+ warning「条目「B」与已有「A」近义，已合并」 |
| ③ 无匹配 | 其余 | 新建 |

> 反向守护：归一化后无包含关系的条目**必须**新建，不得误合并。

#### 5.8.3 粒度控制

`granularity` ∈ {`fine`（默认）, `coarse`}：

- `fine`：现状（LLM 输出几条落几条）。
- `coarse`：① 模板注入粗粒度指令（`{granularity_hint}` 变量）；
  ② **确定性上限** —— 每源解析后、合并前按 LLM 输出顺序取前 `_COARSE_MAX_ITEMS`（5）条，
  超出部分丢弃 + warning「coarse 粒度：丢弃 N 条超出上限的条目」。

同一 LLM 输出下 `coarse` 落库条目数**严格少于** `fine`（可测断言，见 §9）。

#### 5.8.4 预览（dry-run）

`dry_run=true`：执行 LLM + 解析 + 合并决策，但**不写实体、不写 run 表**；返回
`created` / `updated` 计数与 `detail`（含将落库的条目清单），`batch_id=None`。
**忽略增量 skip**（恒执行，保证预览有效）——预览会真实调用 LLM（成本提示见 §10）。
**类别严格校验同样生效**：预览遇未注册类别同样拒绝（§5.8.1），
不因「只是预览」而放过 —— 否则预览结果与实际落库行为不一致。

#### 5.8.5 批次标识与整批回滚

- 非 dry_run 落库时生成 `batch_id = f"ext-{uuid4().hex[:16]}"`，**同一 request 的全部源共享**，
  作为**新建**条目上的 `batch_id` 列落库（`world_settings.batch_id` / `characters.batch_id`，
  可空 TEXT，§8）。被**更新**的条目不改写其原 `batch_id`（保护更早批次的可回滚性）。
- 回滚：`POST /api/v1/projects/{project_id}/extractions/rollback` body `{"batch_id": "..."}`
  → 单事务删除该项目下该 `batch_id` 的条目（`DELETE WHERE project_id=? AND batch_id=?`），
  返回 `RollbackResult{batch_id, deleted, warnings}`。
- **幂等**：重复回滚 → `deleted=0`，不报错。
- **不恢复被更新条目的历史值**（未存快照）→ 返回 warning 提示「本次 run 的更新条目不回滚」。
- 回滚替代「按 `created_at` 小时窗口猜时间」的做法（批次标识是唯一权威）。

#### 5.9 两段式暂存（stage / confirm / cancel）

**语义**：提取产物先落**暂存区**（正式表零变更），用户确认后物化进正式表；取消则清空暂存。

**请求**：`POST /api/v1/extract` 增 `stage: bool = False`。

- `stage=true`：对该次提取**走零写入**（各类型管线以 `dry_run=true` 调用，不写实体 /
  关系、不写 run 表），随后把 `detail.created` / `detail.updated` 的条目清单落到
  `extract_staging` 表；信封回 `batch_id`。
- **支持范围**：`granularity` / `dry_run` 仍**仅
  character / setting**（不变）；`stage` 覆盖全部**可物化**类型——character /
  setting / foreshadowing / timeline（要求该类型物化仓储已装配）+ knowledge_relation
  （关系物化走 F48 关系写入点）；outline / style 无档案实体产物 → 422。
- `stage` 与 `dry_run` 同时传 → 422（互斥）。

**暂存表 `extract_staging`**：`project_id` / `batch_id` / `type` / `entity_type` /
`action`(create\|update) / `target_id`(update 时指向被覆盖行) / `payload`(JSON) / `created_at`。

**entity_type 枚举**：`character` / `world_setting` / `foreshadowing` /
`timeline_event` / `knowledge_relation`（由 ExtractionType 映射，见 `_STAGE_TARGETS`
分派表）。knowledge_relation 的 stage 结果由 F48 确定性规则集「只算不写」产出
would-be 关系、置于信封 `detail.created` 后落暂存（不写 knowledge_relations 表）。
该「只算不写」经 F48 `RelationExtractionService.extract_rules` **公开 compute-only 入口**
（原私有 `_extract_rules` 升公开），消除跨模块私有调用，规则集与语义不变。

**端点**：

| 方法 | 路径 | 返回 |
|---|---|---|
| GET | `/api/v1/projects/{pid}/extractions/staging/{batch_id}` | `StagedListResult{batch_id, items[]}`（元素 `StagedEntry{id, entity_type, action, name, payload}`） |
| POST | `/api/v1/projects/{pid}/extractions/staging/{batch_id}/confirm` | `ConfirmStagedResult{batch_id, created, updated}` |
| POST | `/api/v1/projects/{pid}/extractions/staging/{batch_id}/cancel` | `CancelStagedResult{batch_id, deleted}` |
| **GET** | **`/api/v1/projects/{pid}/extractions/staging`** | **`{batches: [{batch_id, type, created_at, item_count}]}`**（**新→旧**，`created_at DESC`） |
| **POST** | **`/api/v1/projects/{pid}/extractions/staging/{batch_id}/items/{item_id}/confirm`** | **`{item_id, event_id}`**（body `{time_value, time_unit}`） |
| **DELETE** | **`/api/v1/projects/{pid}/extractions/staging/{batch_id}/items/{item_id}`** | **`{deleted}`**（`1` 删除 / `0` 不存在，幂等） |

**批次列表端点（契约冻结）**：`GET .../extractions/staging` 返回**本项目的暂存批次聚合**（新→旧），
以供「待确认提取（N）」入口与待确认区消费。
- **形状冻结**：`{batches: [{batch_id: str, type: str, created_at: iso8601, item_count: int}]}`——`type` = `ExtractionType.value`；**新→旧**排序。
- **「未确认」由存在性表达**：暂存表**无 status 列**（行在 = 未确认），本端点**不引入**状态字段、**不新增迁移**。
- 无批次 → `{"batches": []}`（幂等）；项目不存在 → 404（同 rollback 口径）。

**条目级动作**：`item_id` = 暂存行 `id`（`StagedEntry.id`）。
- **条目 confirm**：按 `(project_id, batch_id, item_id)` 取该行 → 复用该行既有物化路径（`entity_type` → 仓储 `add`），
  **写入前以 body 的 `time_value`/`time_unit` 覆盖 payload 的时间字段**（`time_display` 原样保留）→ 删除该行
  （**只删本行**，同批其余行保留）。`time_value` 为**必填有限数值**（未给 → 422，[f12 §2.9](../f12-timeline/spec.md) D3「确认强制带时间」）。
- **条目 DELETE**：只删该行，零物化（同 cancel 语义，粒度到行）；重复删除 → `deleted=0`，不报错。
- **与批次级的关系**：批次级 `confirm` / `cancel` **语义与行为逐条不变**（前端「AI 提取结果」对话框仍用它）；条目级是**增量能力**，两者共用同一物化分派表（`_STAGE_TARGETS` / `_ENTITY_TARGETS`）。

**写前分流（时间线专用）**：TIMELINE 管线的 `_merge` 在**写库前**对每条新建事件做**后置归一**（[f12 §2.9](../f12-timeline/spec.md) Z2）——
解析失败/无 `time_value` 者**不调用仓储**，作为 `TimelineExtractionResult.pending` 返回；门面在非 `stage` 路径下把
`pending` 落暂存（`entity_type=timeline_event`、`action=create`；`payload` 为该事件的 `model_dump` 并附
`parse_reason`（失败原因，物化时被 Pydantic 忽略））。`stage=true` 路径**行为不变**（全部条目本就落暂存）。

**列表端点（供 GUI「待确认提取（N）」入口消费）**：
`GET /api/v1/projects/{pid}/extractions/staging` → `{batches: [{batch_id, type, created_at, item_count}]}`
（新→旧；「未确认」由存在性表达）。计数口径 = **批次数**（非条目数）。

**前端生命周期（GUI 侧；本层语义不变）**：暂存批次**不随宿主页卸载而失效**——GUI 把提取会话
（`open` / `minimized` / `staged`）提升到全局 store 并挂 App 层，宿主重挂载 / 路由切换后浮窗与结果视图
仍在；关闭对话框只清结果视图（暂存行仍在库中，经「待确认提取」入口的
`GET .../staging/{batch_id}` 读回后再 confirm / cancel）。`stage` → `confirm` 物化 / `cancel` 清空 /
过期清理三条语义**均不变**。

**物化纪律**：confirm 逐行按 `entity_type` 反序列化（Character / WorldSetting /
Foreshadowing / TimelineEvent / KnowledgeRelation 各自 `model_validate(payload)`），再按
`action` 走**该类型对应**仓储（`create` → `repo.add(entity)`；`update` →
`repo.update(entity)`；knowledge_relation → 关系仓储 `add`）——只要求该行对应仓储已装配
（支持部分装配），**不得绕过既有合并语义**；物化后删除本批暂存行。
**幂等**：重复 cancel / confirm 空批 → 计数 0，不报错；项目不存在 → 404（同 rollback 口径）。

**过期清理（内核启动期）**：内核**启动期幂等清理**超期未确认的暂存行——`created_at`
早于「当前 UTC − 阈值天数」的行，在 lifespan（`reconcile_stale_running_plans` 之后、
scheduler 之前）被删除（`core/startup_cleanup.py: cleanup_expired_staging` →
`SQLExtractStagingRepository.delete_expired`），返回清理条数并落日志。

- **阈值**：模块常量 `STAGING_RETENTION_DAYS = 30`（对齐软删 30 天纪律），函数参数
  `retention_days` 可覆盖（测试 / 后续接入设置）；阈值走**代码常量**（对齐本仓
  F15/F16「阈值 → 代码常量 YAGNI」惯例）——**未新增全局 config 项**。
- **范式**：复用 `reconcile_stale_running_plans` 的**启动期维护范式**（lifespan 内
  幂等执行、返回条数）——本仓**无真定时器范式**，故不引入调度库（AGENTS §10.2 简单优先）。
- **幂等**：重复清理 → 第二次 0 行、0 报错；已 confirm / cancel 批次无残留行 → 清理
  不报错、**正式表零影响**（暂存表独立）。
- **失败不阻塞启动**：清理异常被吞并记 WARNING（同 scheduler shutdown 吞异常约定）。
- **不新增索引**：暂存表小且随 confirm / cancel 清空，启动期全表扫描成本可忽略
  （故不走 `ensure_*` 幂等迁移三件套）。

## 6. 提取类型注册表与增量状态语义

（对应 F9 §6「关系图谱与分组管理规则」的位置；F14 无图谱，本节承载类型注册、输入约束与 run 状态语义）

### 6.1 类型注册表（7 槽，7 实现——STYLE 由 F16 注册 handler，§12）

| 槽位 | handler | 输入模式 | 增量追踪 | RAG 映射 | 依赖 |
|------|---------|----------|----------|----------|------|
| `character` | `CharacterService.extract` | text / chapter_ids | ✅ | character | F9 ✅ |
| `setting` | `WorldService.extract` | text / chapter_ids | ✅ | setting | F10 ✅ |
| `outline` | `OutlineService.generate` | prompt / num_chapters / save | ❌（每次执行） | —（无档案） | F11 ✅ |
| `timeline` | `TimelineExtractor.extract`（设置项开启）/ `TimelineService.check_consistency`（设置项关闭——判定在门面层，§5.5） | 开启：text / chapter_ids；关闭：无（库内事件） | ✅（开启，按源 hash）/ ❌（关闭，每次执行） | timeline_event（增量索引 + reindex） | F12 ✅（实体 MODIFY）+ F14 管线 |
| `foreshadowing` | `ForeshadowingExtractor`（F14 新建） | text / chapter_ids | ✅ | foreshadowing | F13 ✅ |
| `style` | `StyleService.analyze`（F16 注册，§12） | text / chapter_ids | ❌（每次执行，确定性只读计算——F16 语义） | —（不在 RAG 范围） | F16 ✅ |
| `knowledge_relation` | `RelationExtractionService.extract_for_project`（`method="rule"`） | 无（项目级单源 `"full"`；text/chapter_ids → 422） | ❌（每次执行，规则集确定性计算，无增量价值） | —（不在 RAG 范围；index=true 忽略 + warning） | F48 ✅ |

> **关系 no-write 公开入口**：两段式暂存 stage 下知识关系「只算不写」经
> `RelationExtractionService.extract_rules`（**公开 compute-only 入口**，原私有
> `_extract_rules`；`extract_for_project` 内部同样复用之）——消除 `_extraction_staging`
> 对 F48 服务的**私有跨模块调用**；规则集与提取语义**不变**（仅可见性提升）。

**注册表实现**（`extraction_service.py` 内部 dict：`ExtractionType → handler`）:

```python
# 分发注册表（构造时装配；STYLE 槽位由 F16 注册 StyleService.analyze，§6.1）
# TIMELINE 槽位为双 handler 选择器（§5.5）: 设置项开启 → TimelineExtractor.extract，
# 关闭 → TimelineService.check_consistency（门面层判定，§5.1 要点 7）
_HANDLERS: dict[ExtractionType, ...] = {
    ExtractionType.CHARACTER: self._character_service.extract,
    ExtractionType.SETTING: self._world_service.extract,
    ExtractionType.OUTLINE: self._outline_service.generate,
    ExtractionType.TIMELINE: self._timeline_handler,   # 设置项切换（§5.5）
    ExtractionType.FORESHADOWING: self._foreshadowing_extractor.extract,
    ExtractionType.STYLE: self._style_service.analyze,  # F16 注册（F16 spec §8.2，接口零变更兑现）
    ExtractionType.KNOWLEDGE_RELATION: self._knowledge_relation_handler,  # F48 关系提取
}
```

> **STYLE 槽位论证**: ① 验收标准「≥6 种提取类型统一接口」要求接口层面齐全——枚举、API、CLI 全量支持；② F16 落地只需在注册表填 handler（`StyleService.analyze`），**接口零变更**（F16 spec §8.2）；③ STYLE 调用返回 200 + ExtractionResult（detail=StyleReport）。

### 6.2 run 状态语义（success / skipped / error）

| 状态 | 含义 | 产生时机 | 消费方 |
|------|------|----------|--------|
| `success` | 该源管线执行完成并落库 | 每源执行成功后 upsert | extract status / runs 列表 |
| `skipped` | 该源内容未变更，确认跳过 | 全源 skip 时对**首个源** upsert 一行 skipped（记录确认事实） | 同上 |
| `error` | 该源执行失败 | **失败源不写 run**（无 run 行 = 失败缺口）——error 行仅历史兼容/防御保留；`status` 字段供未来部分失败语义扩展 | 同上（缺 run 行即缺口） |

> **设计说明**: MVP 失败即抛异常（§5.2），失败源**不写 error 行**——「无 run 行」本身就是缺口信号（`extract status` 对比章节列表即可发现未处理章节），避免 error 行与「下次重跑覆盖」的竞态语义。`error` 枚举值保留（run 表 status 字段，供 Phase 2+ 部分失败语义使用）。

**run 更新时机**: 每源成功后立即 upsert（逐章落库，§5.2）——非「全部成功才写」；这样批量提取中途失败时，成功源的 run 已持久化（断点续跑基础）。

### 6.3 skip 判定规则表（增量提取决策）

| 条件组合 | 结果 | 说明 |
|----------|------|------|
| 类型 ∈ {character, setting, foreshadowing, timeline（开启时）} 且源 hash == run.content_hash 且 not force | skip | 核心增量路径 |
| 同上但 force=true | 执行 | 强制重跑（作者想重新审视 LLM 结果） |
| outline | 执行 | 生成不承诺幂等（§5.2） |
| knowledge_relation | 执行 | 项目级单源、规则集确定性计算（每次执行，无增量价值） |
| timeline（设置项关闭） | 执行 | 确定性检查只读廉价（§5.2） |
| 无 run 行 | 执行 | 首次提取 |
| hash 不同 | 执行 | 内容已变更 |
| 手动模式重复提交同一文本 | skip | source_key="manual" 同 hash |
| 章节内容超 50000 | 422 | 单章超限，分块归 Phase 2+ |

### 6.4 各类型输入约束（统一接口的类型相关校验）

| 类型 | text/chapter_ids | prompt/num_chapters/save | include_flashbacks | auto_extract | index | granularity | dry_run |
|------|------------------|--------------------------|--------------------|--------------|-------|-------------|---------|
| character / setting | **必须提供其一**（互斥） | 无效（422） | 无效（422） | 无效（422） | ✅ 生效 | ✅ 生效（§5.8.3） | ✅ 生效（§5.8.4） |
| foreshadowing | **必须提供其一**（互斥） | 无效（422） | 无效（422） | 无效（422） | ✅ 生效 | 无效（422） | 无效（422） |
| outline | 无效（422） | prompt 可选 / num_chapters 1-100 / save 默认 true | 无效（422） | 无效（422） | 忽略 + warning |
| timeline | 开启：**必须提供其一**（互斥，同 character）；关闭：无效（422） | 无效（422） | ✅ 透传 F12（关闭语义） | ✅ 仅 timeline 生效（bool \| None；None=跟随项目配置） | ✅ 生效（开启）/ 忽略 + warning（关闭） |
| style | **必须提供其一**（互斥，同 character/setting/foreshadowing——F16 落地后语义） | 无效（422） | 无效（422） | 无效（422） | 忽略 + warning「style 类型不支持自动索引」 |
| knowledge_relation | 无效（422——项目级提取，不接受源参数） | 无效（422） | 无效（422） | 无效（422） | 忽略 + warning「knowledge_relation 类型不支持自动索引」 |

> 类型不匹配的字段一律 422 而非静默忽略（显式错误优先，同 F13 event_id 校验风格；`knowledge_relation` 为项目级提取，携带 text/chapter_ids → 422「knowledge_relation 类型不支持 text/chapter_ids（项目级提取，无需源参数）」）；`index` 对 outline / timeline（关闭时）是**忽略 + warnings 提示**（非错误——索引是增强行为，不阻塞提取主流程）；`auto_extract` 是 timeline 专属覆盖参数——显式 `true`/`false` 覆盖项目配置 `timeline_auto_extract`，缺省 None 跟随项目配置（§2.6）；timeline 关闭时携带 text/chapter_ids → 422「时间线自动提取未开启（配置 timeline_auto_extract）」（设置项判定在门面层，§5.5）。

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 项目不存在（所有类型） | 404: "项目不存在"（门面统一校验） |
| text 与 chapter_ids 同时提供 | 422: "text 与 chapter_ids 不能同时使用" |
| character/setting/foreshadowing 无 text 且无 chapter_ids | 422: "character/setting/foreshadowing 类型必须提供 text 或 chapter_ids" |
| outline 携带 text/chapter_ids | 422: "outline 类型不支持 text/chapter_ids（使用 prompt/num_chapters）" |
| timeline 设置项关闭且携带 text/chapter_ids | 422: "时间线自动提取未开启（配置 timeline_auto_extract）"（设置项判定在门面层，§5.5） |
| STYLE 类型调用 | 200 + ExtractionResult（detail=StyleReport，created=0/updated=0/model=None，F16 spec §5.3 归一语义） |
| `knowledge_relation` 无源参数调用 | 200 + ExtractionResult（项目级规则关系提取：created=新增关系数、updated=0、model=None、indexed=false；与 `inkflow knowledge extract --method rule` 同一执行体） |
| `knowledge_relation` 携带 text/chapter_ids | 422: "knowledge_relation 类型不支持 text/chapter_ids（项目级提取，无需源参数）" |
| `knowledge_relation` 但门面未装配关系提取服务（防御） | 422: "不支持的提取类型"（UnsupportedExtractionTypeError——注册表槽位缺失时兜底，不静默成功） |
| text 为空/全空白 / > 50000 字符 | 422（Pydantic，同 F9 约束） |
| 章节内容 > 50000 字符 | 422: "章节内容超过提取上限（50000 字符）" |
| chapter_ids 指向不存在/软删章节 | 422: "章节不存在"（F2 get 不含软删） |
| chapter_ids 指向其他项目章节 | 422: "章节不属于该项目" |
| 批量章节中某章 LLM/解析失败 | 抛异常 → 500；**已成功章已落库 + run 已写**；重跑自动 skip 成功章（§5.2 断点续跑） |
| 批量章节全部未变更 | 200 + status=skipped（零 LLM 调用） |
| 混合：部分 skip 部分执行 | 200 + status=success（processed_sources/skipped_sources 分别计数） |
| outline 同名活动大纲 | 422 透传 F11 OutlineNameConflictError（同 F11 现状） |
| outline save=false（预览） | 200 + detail=preview（不落库、不做同名检查，F11 语义透传） |
| timeline 关闭时无事件 / 全部事件 time_value 为 None | 200 + detail（ConsistencyReport：consistent=True / skipped 计数，F12 语义） |
| timeline 开启时提取：事件合并匹配 | 200 + created/updated 按事件数计；同 (project_id, title, source_chapter_id) 活动事件 → 非空字段覆盖（不动 None）；不存在 → 新建（time_value=None、narrative_position=LLM 输出或 None、timeline_flag 透传）；软删同名同章 → 新建 + warning（§5.5 合并策略） |
| timeline 开启时章节内容变更后重提取 | 该章 hash 变化 → 执行 → 同源事件被更新（联动）；已成功章重跑自动 skip（§5.2/§5.5） |
| timeline 事件来源章节软删 | 事件保留 source_chapter_id（历史来源锚点；章节列表不可见但档案可追溯，§5.5） |
| timeline 事件来源章节硬删 | FK ON DELETE SET NULL → source_chapter_id 置 None（事件保留；同 F13 event_id 硬删语义，§5.5） |
| timeline 提取时事件不再出现于章节 | **不删除**（只增改不删除；自动删除归 Phase 2+，§10） |
| 手动模式重复提交同一文本 | 200 + status=skipped（source_key="manual" 同 hash） |
| --force 重跑未变更源 | 200 + status=success（强制执行，run hash 更新） |
| RAG：vector_store 未装配 / BGE 下载失败 | **503 + Retry-After: "RAG 向量库不可用: ..."**（RAGUnavailableError）；**不影响非 RAG 功能**（retrieve 优雅降级防吞空 INTERNAL_ERROR——hnsw 段读取失败不再吞成「内部错误（无详情）」） |
| chroma 存储层错误（hnsw 段读取失败等，读侧自愈后仍失败） | 500: "向量检索失败：chromadb hnsw 段未就绪（<entity_type>），请重试一次"（VectorStoreError，清晰可定位，**不吞空**） |
| extract 带 index=true 但类型为 outline / timeline（关闭时） | 200 + indexed=false + warning "outline/timeline 类型不支持自动索引"（不报错；timeline 开启时 index 生效） |
| vector retrieve 无结果 / min_score 过滤全空 | 200 + 空 items（正常路径） |
| vector retrieve query 空白（空串/纯空格） | store 层确定性降级：`logger.warning` + 返回 `[]`（不调 embed_query、不打 chroma；外部 zhipu 400 1213 家族根治，端点契约不变仍 200 空 items） |
| 索引实体 content 空白 | store 层逐条跳过：`logger.warning`（含实体 id）+ 不 embed 不 upsert（reindex 继续不中断；批量全空 → 零 embed 调用） |
| 批量索引单组有效实体数 > 64 | store 层分片：`embed_documents` 按 `_EMBED_MAX_INPUTS_PER_REQUEST`（64）分批提交后合并，再一次性 upsert（每类型一次）——超限不再触发上游 400 code 1214、重建不中断、指纹可达 `fresh`；单条路径不受影响 |
| vector retrieve top_k 越界（≤0 或 >50） | 422（Pydantic 校验 top_k 1-50，min_score 0-1） |
| vector retrieve 遇 chromadb hnsw 段读取失败（"Nothing found on disk" / "Error finding id" 同族） | **段就绪判定 + 读侧自愈**（§5.6.8）：首次 `InternalError` → 对本 collection 做一次元数据空写（`_heal_stuck_segment`，写次数有界 `_SEGMENT_HEAL_MAX_WRITES`=2）触发段 apply → 重试真实查询；成功 → 200 命中（relevance_score 降序）。仍失败 → 500「向量检索失败：chromadb hnsw 段未就绪（<entity_type>），请重试一次」（清晰可定位、**不吞空**「内部错误（无详情）」、**不指引重建索引**——重建无效，重试一次即过） |
| vector reindex 空项目（无档案） | 200 + indexed=0（正常路径） |
| vector reindex 未指定 entity_types | 默认全部 5 种（config.vector_store_collections） |
| extract 非法 type 值（API 层） | 422（Pydantic 枚举校验） |
| extract --type 非法值（CLI） | 退出码 2（Typer Choice 校验） |
| CLI --text 与 --text-file 同时使用 | 退出码 2（同 F9 character extract 先例） |
| CLI vector retrieve 缺 --query | 退出码 2（Typer 必填参数） |
| run 表 upsert DB 错误 | 500（全局处理器；提取产物已落库——run 是副产物，失败不回滚实体） |
| 项目硬删除 | extraction_runs 级联物理删除（FK CASCADE）；chroma 向量数据**不自动清理**（孤儿向量，检索按 project_id 过滤不可见；`vector reindex` 覆盖；全量清理归 Phase 2+，见 §12） |
| 切片：空文本（所有模式） | 返回 `[]`（不产生块，不索引） |
| 切片：chunk_size <= 0 | ValueError（`_chunking.py` 契约，同 FIXED） |
| 切片：chunk_size 越界（<100 或 >2000）/ overlap_ratio 越界（<0.10 或 >0.20） | 422（app_settings 校验层，§5.6.3） |
| 切片：overlap>0 且文本长度 < chunk_size | 1 块（不产生重复块） |
| 切片：对话模式无对话文本 | 降级段落切片（§5.6.6，不产生空块） |
| 切片：LLM analyzer 失败 / 未配置对话模型 / 超时 | 降级段落切片 + logger.warning，reindex 不中断（§5.6.7） |
| 检索：旧向量数据缺新元数据键（chapter_x 等） | `_map_retrieved` `.get()` fallback 不崩（§5.6.4） |
| 切片配置变更 | stale（chunking_changed）→ 提示重新向量化；重建前检索继续用旧向量（200 非空，§5.6.5） |
| 非 character/setting 类型传 granularity != fine / dry_run=true | 422: "granularity/dry_run 仅支持 character/setting 类型" |
| character/setting `dry_run=true` | 200 + ExtractionResult（created/updated = 「将写入」计数，`batch_id=null`；**DB 零写入**——实体与 run 表均不落） |
| setting 提取：LLM 类别不在项目已有分类中 | **拒绝整批**：422 `WorldCategoryNotRegisteredError`，消息列出**全部**缺失分类名（去重、保序）+ 该批次**正式表零写入**；`stage` 路径在落暂存前拒绝（暂存区零行）。项目无分类时同样拒绝。**空类别不拒绝**（LLM 主动留空 → 维持未分类）。由 agent / CLI 建类后重试（禁自动建类；`--auto-create-categories` 仅复制路径） |
| 提取条目与已有条目近义 | 合并到已有条目（content 追加 + warning），**不新建**；条目总数不因重复提取线性增长 |
| 回滚不存在 / 已回滚的 batch_id | 200 + RollbackResult(deleted=0)（幂等，不报错） |
| 回滚 batch 含此前批次条目 | 不受影响——batch_id 精确匹配；被更新的条目不携带本批 batch_id |

---

## 8. 模块归属与端口契约

遵循 ADR-007v2 包结构；新增/修改按层归属：

- **domain/models**：`extraction.py`（ExtractionType / ExtractionStatus / ExtractionRequest / ExtractionResult / ExtractionRun / ReindexResult）；`vector_fingerprint.py`（指纹协议，§5.6.5 复用）
- **domain/ports**：`extraction_errors.py`（错误类族）、`extraction_run_repository.py`（§8.1）、`extraction_staging_repository.py`（§5.9）、`vector_store.py`（既有 `VectorStoreProtocol`，不重定义）
- **domain/services**：`extraction_service.py`（门面）、`_foreshadowing_extractor.py` + `_timeline_extractor.py`（提取管线）、`_chunking.py`（切片纯函数）、`_llm_chunk_analyzer.py`（LLM 切片分析）、`_extraction_rag.py`（索引编排）、`_extraction_staging.py`（暂存编排）、`_timeline_text_time.py`（原文时间解析，确定性）
- **infrastructure**：`database/models/extraction.py` + `repositories/extraction_run_repo.py` / `extraction_staging_repo.py`；`rag/langchain_vector_store.py`（`VectorStoreProtocol` 唯一实现）
- **api / cli**：`api/routers/extractions.py`（端点，§3.1）、`cli/commands/extract.py` + `cli/commands/vector.py`（§4）
- **跨模块 MODIFY**：F12 `models/timeline.py` + `repositories/timeline_repo.py`（`source_chapter_id` + `list_by_chapter`，§2.6/§5.5）；F32 `app_settings`（切片配置四键，§5.6.3）；F9/F10 `characters` / `world_settings`（`batch_id` 列，§5.8.5）
- **测试文件归属**：`backend/tests/unit/**`（自动收集）；CLI 测试在顶层 `tests/cli/`，**须显式登记 ci.yml `integration-cli-backend` job**（Windows pytest 不展开 glob）

### 8.1 ExtractionRunRepositoryProtocol（参照 F9 `character_repository.py` Protocol 风格）

```python
class ExtractionRunRepositoryProtocol(Protocol):
    """增量追踪记录仓储端口（§2.3）.

    每 (project_id, type, source_key) 一行最新状态（upsert）；
    get 供门面增量判定（§5.2），list 供 runs 查询（§3.3）。
    """

    async def get(
        self, project_id: int, type: ExtractionType, source_key: str
    ) -> ExtractionRun | None: ...
    async def upsert(self, run: ExtractionRun) -> ExtractionRun: ...
        # INSERT ... ON CONFLICT(project_id, type, source_key) DO UPDATE
    async def list(
        self, project_id: int, type: ExtractionType | None = None,
        offset: int = 0, limit: int = 50,
    ) -> tuple[builtins.list[ExtractionRun], int]: ...
        # 按 run_at DESC 排序（最新在前）
```

> 仓储层入参用 int（与 F9-F13 RepositoryProtocol 一致）；Service 负责 UUID ↔ int 转换（沿用 F1 `_to_int_id` 模式）。`upsert` 用 SQLite `ON CONFLICT` 保证原子性（并发重复提取时最后写入者胜——单用户本地工具，无竞态处理，同 F9-F13）。
>
> 本 Protocol 只承载增量判定所需方法（get/upsert/list）；时间线提取所需的跨模块方法（`TimelineRepositoryProtocol.list_by_chapter`）属 **MODIFY F12**（§8 模块归属），不在本 Protocol 内新增。

---

## 9. 测试策略

### 测试层次（沿用 ADR-018 三层目录 + pytest markers；层次结构同 F13 §9）

```text
单元测试: 领域模型/DTO 校验（枚举、互斥、类型约束）      ~15 cases
集成测试: SQLExtractionRunRepository（in-memory SQLite） ~10 cases
服务测试: ExtractionService 门面（Mock 各模块 Service）   ~28 cases
管线测试: ForeshadowingExtractor（Mock LLM 分支）        ~15 cases
管线测试: TimelineExtractor（Mock LLM 分支 + 设置项切换）~15 cases
切片测试: chunk_text + 切片器变体（段落/重叠/对话/LLM 降级）  ~25 cases
RAG 测试: LangChainVectorStore（FakeEmbeddings + tmp chroma）~15 cases
API 测试: 4 端点（Mock ExtractionService）               ~15 cases
CLI 测试: extract/vector 组（Mock ExtractionService）    ~20 cases
```

### 关键测试场景

**领域模型**: ExtractionType 六值 / ExtractionRequest 校验（text 空/超 50000 → 422；text 与 chapter_ids 互斥；chapter_ids 空列表/超 100 → 422；num_chapters 越界；非法 UUID → 422；type 非法值 → 422）/ ExtractionResult 默认值与 status 枚举 / ExtractionRun 领域模型 from_attributes

**仓储（run）**: get 命中/未命中 / upsert 新建 + 同键更新（ON CONFLICT：字段整体覆盖，run_at 更新）/ list 按 type 过滤、run_at DESC、分页 / 项目硬删 → 级联清理 / 空表 list

**服务（门面，Mock 各模块 Service + Mock run_repo + Mock chapter_repo + Mock vector_store）**:
- 分发正确性：5 种委托类型分别委托对应 Service 方法，参数透传（text / prompt+num_chapters+save / include_flashbacks / model）
- 项目校验：project_repo.get → None → ProjectNotFoundError（所有类型统一）
- 增量判定：hash 相同 + not force → skip（status=skipped、processed=0、零 LLM 调用断言——Mock handler 未被调用）/ hash 不同 → 执行 / 无 run → 执行 / force=true → 执行
- 手动模式：source_key="manual" 同文本重复 → skip；不同文本 → 执行
- 批量章节：部分 skip 部分执行 → success + 计数正确；章节不存在 → ChapterNotFoundError；跨项目章节 → ChapterNotInProjectError；章节超 50000 → 422
- **断点续跑（核心验收）**：Mock handler 第 2 章抛 LLMRequestError → 门面抛异常；断言第 1 章 run 已 upsert；重跑 → 第 1 章 skip、第 2 章执行
- outline：每次执行（run 断言 upsert）；outline 同名冲突异常透传
- timeline 设置项判定：项目配置开启 → 委托 TimelineExtractor；请求 auto_extract=true 覆盖关闭的配置 → 委托 TimelineExtractor；auto_extract=false 覆盖开启的配置 → **不调用 LLM**（Mock extractor 未被调用）直接委托 check_consistency；缺省 None 跟随项目配置
- timeline 关闭语义：每次执行（run 断言 upsert）、include_flashbacks 透传、携带 text/chapter_ids → 422「时间线自动提取未开启」
- timeline 开启语义：章节/文本源增量 skip 判定同 character；提取事件 → TimelineExtractionResult 归一计数
- STYLE：成功路径（F16 已注册——Mock StyleService 委托断言 + 归一 created=0/updated=0；占位测试已随 F16 同步，见 F16 spec §9）
- index=true：Mock vector_store.index_batch 收到本次 created/updated 实体转成的 IndexableEntity（content 投影正确、metadata 含 project_id）；章节模式额外收到 chapter_chunk 块；outline / timeline（关闭时）→ indexed=false + warning；timeline（开启时）→ 提取事件索引为 timeline_event（metadata 含 chapter_id=source_chapter_id）
- RAG 未装配（vector_store=None）+ index=true → RAGUnavailableError（503 + Retry-After）
- 结果归一：各类型 created/updated 计数口径（§5.3）；detail 保留首个执行源原始结果

**伏笔提取管线（Mock LLM）**: 合法 JSON → 合并落库 / 代码块围栏 → `_extract_json_fragment` / 修复重试 ≤2 → ForeshadowingExtractionError（raw_output 截断 500）/ 条目级非法 → 跳过 + warning / 同名活动伏笔 → 非空覆盖且 **status 不重置** / 软删同名 → 新建 + warning / 幂等：同文本二次提取 → 空 diff / 自环与关系逻辑不适用（伏笔无关系）

**时间线提取管线（Mock LLM，§5.5）**: 合法 JSON → 合并落库（事件带 source_chapter_id）/ 修复重试 ≤2 → TimelineExtractionError / 条目级非法（title 空、time_value 越界）→ 跳过 + warning / 合并匹配：同 (title, source_chapter_id) 活动事件 → 非空字段覆盖且 **None 不动**（time_value/time_unit/narrative_position/timeline_flag 独立判断）/ 不存在 → 新建（time_value=None、narrative_position=LLM 输出或 None、timeline_flag 透传）/ 软删同名同章 → 新建 + warning / 手工事件（source_chapter_id=None）不匹配 → 新建 / 幂等：同文本二次提取 → 空 diff / **章节联动**：章节内容变更 → 重提取 → 同源事件更新（list_by_chapter Mock 断言查询键）/ 章节硬删 → source_chapter_id 置 None（repo 层语义）/ 设置项关闭 → extractor 不被调用

**分块（chunk_text，FIXED 现状，保持既有契约）**: 500 字边界 / 标点边界回溯（。！？\n）/ 短文本 1 块 / 空文本 0 块 / 中文计数正确

**切片器变体（test_chunking_modes.py，§5.6.1-§5.6.7）**:
- 段落模式：空行切分 / 单段 ≤ chunk_size 一块 / 超长段降级标点回溯 / 空文本 [] / chunk_size<=0 ValueError
- 重叠：overlap=0 拼接还原原文不变式 / overlap=10%/20% 相邻块重叠率 ∈ 区间 / overlap>0 弱不变式「原文每字符至少被一块覆盖」/ 超短文本（<chunk_size）不产生重复块 / 块 id 三态（overlap=0 `{chapter_id}:{idx}`、overlap>0 `{chapter_id}:{idx}:{start_offset}`）
- 对话模式：说话人切换边界（引号/破折号/冒号+引号）/ 连续对话归并 / 短块合并叙述上下文 / 无对话文本降级段落 / 空文本 []
- LLM 模式：注入 mock analyzer（返回边界列表）→ 边界生效 / analyzer 异常 → 降级段落（reindex 不中断）/ 内容 hash 相同 → 不重复调用 analyzer（增量契约）
- 元数据：_project_chapter_chunk 输出 chapter_x/chapter_y/volume_title/chunk_start/indexed_at；_map_retrieved 缺键 .get() fallback 不崩
- 指纹联动：切片配置变更 → compare_fingerprints 报 chunking_changed（既有纯函数，复用其测试）

**RAG（真实 chroma + FakeEmbeddings，tmp 目录）**: index → collection upsert（id 幂等：同 id 二次 index 覆盖）/ index_batch / retrieve 按 project_id where 过滤（跨项目不可见）/ entity_types 过滤 / cosine 分数 = 1 - distance（FakeEmbeddings 固定向量可断言排序）/ min_score 过滤 / top_k 截断 / delete 单实体 / delete_project 返回删除数 / 空库 retrieve → 空列表 / **FakeEmbeddings 维度一致性**（size=384，与 BGE 输出维度同）/ **timeline_event 投影**（metadata 含 chapter_id=source_chapter_id——来自章节提取的事件；手工事件省略该键，§5.6 表）

**API（Mock ExtractionService）**: 4 端点成功路径（含 extract 全字段、style 成功（F16 已注册）、auto_extract 透传、runs 分页、reindex 缺省类型、retrieve 参数校验）/ 404 项目不存在 / 422 全路径（互斥、缺失、类型不匹配、timeline 未开启带文本、top_k 越界）/ 500 透传（LLM/管线）与 **503 + Retry-After 透传（RAGUnavailableError）** / 无效 UUID → 404 / 信封序列化（ExtractionResult.model_dump(mode="json")）

**CLI（Mock ExtractionService）**: extract run 各类型参数透传（--text/--text-file/--chapters 三选一、--prompt、--num-chapters、--no-save、--auto-extract/--no-auto-extract、--index、--force）/ status 人类可读与 --json / vector reindex 缺省与多 --type / vector retrieve 参数与排序输出 / 信封格式与退出码 0/1/2 / STYLE → 成功信封（退出码 0，F16 已注册）/ NOT_FOUND / RAG_ERROR 信封 / --text 与 --text-file 同时 → 退出码 2 / --type 非法值 → 退出码 2

### 覆盖率目标

- F14 模块行覆盖率 **≥ 80%**（门面分发全分支、增量判定全分支、RAG 实现全方法，同 F9-F13）
- 全仓覆盖率 **≥ 60%**（DoD，ADR-019）
- CI 门禁：ruff + mypy + pytest 全绿（ADR-017/018）；domain/ 零 FastAPI/Typer/SQLAlchemy/LangChain import（ADR-002/015——`_chunking.py` 纯函数、门面只依赖 Protocol）
- **CI 覆盖盲区防范**: `tests/cli/test_cli_extraction_crud.py`/`test_cli_extraction_errors.py` 与 `tests/cli/test_cli_vector.py` 必须显式加入 ci.yml `integration-cli-backend` job（Issue #59/#61 教训，见 §8 注记）——实施 PR 中 ci.yml 修改与测试文件同时合入
- **CI 无网络约束**: 所有测试**不触发 BGE 模型下载**——RAG 测试一律 FakeEmbeddings 注入；生产装配（deps.get_vector_store）不进入任何测试路径（BGE 下载 ~100MB 只在真实运行时发生，§11 影响）

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|----------|
| 新实体档案表（角色/世界/伏笔/大纲/事件） | 本 spec 决策：F14 是横切收敛型，实体与合并语义全部复用 F9-F13（§1/§5） |
| F6 数据源替换（CharacterSettingSource / WorldSettingSource 空实现） | 联调阶段（F13 先例：F9/F10 的注入替换不纳入模块里程碑；F13 因注入是验收标准本体而例外） |
| RAG 接入 F3/F6 写作链路（检索结果注入写作 Prompt） | Phase 2+ 联调——MVP 只交付「能索引、能检索」实证闭环（§5.6）；注入策略（何时检索、预算分配）归 ADR-013 影响节后续决策 |
| 时间线事件自动删除（提取移除章节中不再存在的事件） | Phase 2+——MVP 提取只增改不删除（§5.5 联动语义）；自动删除需「事件-章节存在性核对」策略（作者可能有意保留跨章事件），F15 审计需要时再设计 |
| 伏笔自动回收检测（正文 → 兑现识别） | Phase 2+（§5.4 论证：误报成本高 + F13 状态机语义需人工确认） |
| 实体级增量提取（字段级 diff、跨章节实体追踪） | Phase 2+——MVP 按源 hash + 事件 source_chapter_id 联动（Q3 已拍板综合方案，§2.6/§5.5）；字段级 diff 需跨章节实体来源追踪，F15 审计需要时再设计 |
| 长章节分块提取（> 50000 字符自动切块多次调用） | Phase 2+（F22 长文处理联动）——MVP 单章超限 422 |
| 向量数据随项目删除自动清理 | Phase 2+——孤儿向量按 project_id 过滤不可见，`vector reindex` 可覆盖（§7/§12） |
| 向量集合管理（collection 生命周期、迁移、备份） | Phase 2+——MVP 固定 5 个 collection（config.vector_store_collections 已定） |
| RAG 混合检索（BM25 + 向量）、rerank | Phase 2+——MVP cosine 相似度 + 切片策略模式（§5.6） |
| 风格检测（F16 本体：风格指纹/AI 痕迹/词汇分析） | F16 风格检测服务——F14 注册 handler 兑现（§6.1） |
| extraction_runs 历史审计（多次运行轨迹、变更回溯） | F15 审计服务（Phase 2）——run 表每源一行最新状态（§2.3） |
| RAG 检索结果用于 F15 审计的跨模块一致性核对 | F15 审计服务（Phase 2） |
| 增量提取定时任务 / daemon 自动提取 | F25 daemon（Phase 3）——MVP 手动触发（API/CLI） |
| 项目级切片配置覆盖（每项目独立 mode/chunk_size/overlap） | Phase 2+——MVP 全局 app_settings（§5.6.3，需求文档 Q2.1 建议全局；小说类型差异支持项目级，需项目配置持久化 + API 扩展） |
| CLI `vector reindex --chunk-mode/--chunk-size/--overlap` 显式覆盖 | 后置 P2（需求文档 §2.3 建议）——MVP 切片配置经 app_settings 持久化，reindex 不加覆盖参数（YAGNI，见 §12 决策） |
| 检索结果位置跳转（点击结果跳原文章节） | P2 前端增强——MVP 只展示位置文本（章节 x/y），§5.6.4 |
| 对话切片真实样本收集与识别规则验证 | 落地前需真实对话体样本验证识别规则 |
| LLM 档 token 成本预估弹窗（选 LLM 档时展示） | 后置 P2（docs §2.3）——MVP LLM 档仅降级 + 日志 |

---

## 11. 依赖关系

与 F1 §11 / F9-F13 §11 已声明依赖保持一致（F14 在其上调整——**首个横切收敛型依赖面：委托 5 个模块 + RAG 落地**）：

```text
F14 依赖:
  F1 (project_service) ✅ — 项目存在性校验（门面统一校验，404，§5.1）
  F2 (chapter_service) ✅ — 章节读取（chapter_ids 模式：F2 ChapterRepositoryProtocol.get_chapter，
                           增量源 + chapter_chunk 索引数据源，§5.2/§5.6）；
                           事件-章节联动（F12 事件 source_chapter_id FK→chapters.id，§2.6/§5.5）
  F5 (llm_service)     ✅ — LLM 客户端 + PromptManager（伏笔/时间线提取管线装配，§5.4/§5.5）
  F9 (character_service) ✅ — 委托 CharacterService.extract（CHARACTER 类型）
  F10 (world_service)  ✅ — 委托 WorldService.extract（SETTING 类型）
  F11 (outline_service) ✅ — 委托 OutlineService.generate（OUTLINE 类型，save 透传）
  F12 (timeline_service) ✅ — ① 委托 TimelineService.check_consistency（TIMELINE 类型，设置项
                            关闭语义）；② **跨模块 MODIFY F12 实体**（TimelineEvent 加
                            source_chapter_id + TimelineRepositoryProtocol.list_by_chapter——
                            F13 改 F6 sources.py 先例，§2.6/§5.5/§8）；③ timeline_event
                            索引数据源（增量 + reindex，§5.6）
  F13 (foreshadowing_service) ✅ — ① 委托档案（FORESHADOWING 合并落库复用 F13 实体/仓储/
                            partial unique 合并锚点，§5.4）；② foreshadowing 索引数据源
  F16 (style_service)  ✅ — STYLE 类型依赖：注册 `StyleService.analyze` handler（§6.1，接口零变更）
  F6 (context_service) — 不依赖（不替换数据源，归联调阶段，§10）
  ADR-013 (RAG)        ✅ — 本模块落地：实现 VectorStoreProtocol（P0-11 已定义，
                            不重定义）；LangChain Chroma + BAAI/bge-small-zh-v1.5
                            （§5.6/§8）；依赖已锁定（chromadb/langchain-chroma/
                            sentence-transformers，pyproject），不新增
  F32 (settings_service) ✅ — 切片配置经 app_settings 读取（跨模块 MODIFY F32 settings 四键，
                            §5.6.3/§8）；SettingsService.get_settings 供 reindex 装配读配置快照
  向量指纹协议          — 切片参数纳入指纹引用其 ChunkingFingerprint / compare_fingerprints /
                            reindex 四步协议（§5.6.5，**不重定义**）
  ADR-012 (错误处理)    ✅ — 门面失败即异常；错误码新增 EXTRACTION_ERROR / RAG_ERROR
                            （UNSUPPORTED_TYPE 已随 F16 删除，§3.4/§4）

F14 被依赖:
  F7 (CLI)             ✅ — extract / vector 命令组并入 F7 命令树（cli/app.py 注册）
  F15 (审计)            ⏳ — 提取 run 状态与各档案作为 4 维度一致性审计数据源；
                            run 表升级为历史表的需求在此确认（§10）
  F20 (MCP)            ⏳ — (Phase 3) extract / vector 工具基于本模块 API
  F6 (context_service) ⏳ — (联调阶段) RAG 检索结果作为动态上下文候选源（ADR-013 影响节）
  F3 (writing_service) ⏳ — (Phase 2+ 联调) 写作时 RAG 检索注入（§10）
```

> **ADR-013 影响节（本模块实证）**: ① BGE 模型首次下载 ~100MB（HF hub，需网络）——懒加载 + RAGUnavailableError 降级，非 RAG 功能不受影响；② chromadb 持久化磁盘占用（每项目 ~10-50MB，`config.vector_store_dir` 默认 `./data/chroma`）；③ 检索延迟 ~10-50ms（本地 CPU），不阻塞 LLM 调用大头延迟；④ `VectorStoreProtocol` 的检索接口强制 project_id——多项目数据天然隔离（metadata where 过滤，§5.6）。

---

## 12. 决策表

全 spec 唯一决策落点。

| 决策点 | 选择 | 理由 | 备选（否决） |
|--------|------|------|--------------|
| 1 模块类型 | **横切收敛型门面**（不建新实体档案） | 「统一接口」而非新实体是验收核心；F9-F13 管线与合并语义成熟，重写或复制任一条管线都是重复投资；门面 + 注册表使新类型落地只需注册 handler | 为每种类型建新实体档案（与 F9-F13 边界冲突） |
| 2 委托方式 | 门面注入**各模块 Service**（`CharacterService.extract` 等），不注入底层 extractor | 各 Service 已封装项目校验 + 提取器装配；门面零业务逻辑（§5.1）；伏笔例外——F13 无提取方法，F14 新建 extractor 直接装配（§5.4） | 注入底层 extractor（重复实现项目校验与装配） |
| 3 统一接口形态 | `ExtractionType` 7 值枚举 + `ExtractionRequest`（type 决定输入）+ `ExtractionResult`（统一信封，detail 保留原始结果） | 一份契约覆盖提取/生成/检查三类语义；detail 避免信息损失；created/updated 归一提供轻量摘要 | 每类型一套请求/响应（消费者需分支记忆） |
| 4 OUTLINE/TIMELINE 语义适配 | outline 委托**生成**（save 透传）；timeline **双语义**（`timeline_auto_extract` 开启 = LLM 提取管线，关闭 = F12 确定性检查） | 大纲/时间线属「一键沉淀」心智，语义适配即可；写入型自动化默认关闭（显式开启 = 知情同意） | 为大纲/时间线另造「文本提取」管线（新管线 × 2，超出估算）；timeline 恒确定性检查（丢失提取能力） |
| 5 增量粒度 | **按源（章节/文本）sha256 hash** + 事件-章节联动（匹配键含 `source_chapter_id`） | hash 精确、不受元数据干扰、内容回退也能判定；联动使「章节变更 → 该章事件精准更新」闭环；与模块合并幂等叠加双保险 | 实体字段级 diff（需跨章节来源追踪，Phase 2+）；`updated_at` 时间戳（不可靠） |
| 6 增量记录形态 | `extraction_runs` 每 (project, type, source) **一行最新状态**（UNIQUE + upsert） | 增量判定只需最新指纹；历史轨迹归审计；upsert 原子避免查-写竞态；失败源不写行 = 缺口信号（§6.2） | 历史表（无消费者，YAGNI） |
| 7 批量失败语义 | 逐章独立执行 + 失败即抛异常 + 已成功章 run 已落库（断点续跑） | 与 F9「合并阶段不重试」一致；run 表使部分成功可观测；重跑自动 skip 成功章 | 全批回滚（已完成工作浪费）；吞错继续（静默缺口） |
| 8 STYLE 槽位 | 注册表槽位 + `StyleService.analyze` handler（接口零变更） | 接口层先齐全，F16 落地只填 handler | 从枚举/API/CLI 剔除（接口要变一次）；501 预留通道（语义混乱） |
| 9 RAG 落地范围 | 基础设施（LangChainVectorStore）+ 索引编排（index=true 增量 / reindex 全量）+ 检索入口（API/CLI）；**不接 F3/F6** | 「向量存储落地」的可演示闭环即达标；写作注入涉及预算/触发策略，归 Phase 2+ | 直接接入写作链路（触发策略未定，超范围） |
| 10 collection 组织 | 每 EntityType 一个 collection（`inkflow_{type}`）+ `metadata.project_id` 过滤 | 单 collection 混合类型使 where 组合复杂且类型维度被稀释；与 EntityType 一一对应，检索过滤即选 collection | 单 collection + type 字段（过滤组合复杂） |
| 11 embedding 注入 | 构造注入：生产 BGE / 测试 FakeEmbeddings；deps 层懒加载 | BGE 下载 ~100MB 不能进测试；注入使真实 chroma 测试可行 | 全局单例硬编码（测试不可行） |
| 12 RAG 可用性降级 | 未装配/模型加载失败 → `RAGUnavailableError`（503 + Retry-After），不影响非 RAG 功能 | RAG 是增强能力；extract 不带 index 照常工作；消息提示联网/重试 | 500 统错（调用方无法区分可重试） |
| 13 索引内容与分块 | 各档案字段拼装纯文本 content + metadata 透传关键字段；分块纯函数 ~500 字/标点回溯/无重叠，块 id = `{chapter_id}:{idx}` | 检索匹配 content 文本，metadata 供过滤/展示；投影与分块均为确定性纯函数（可单测）；块 id 稳定 → upsert 幂等 | 存结构化 JSON 进向量库（embedding 语义退化） |
| 14 项目删除与向量 | 项目硬删 → run 表 FK CASCADE；chroma 向量**不自动清理**（孤儿不可见，reindex 覆盖） | 向量库生命周期管理归 Phase 2+；不把项目删除与向量清理耦合（YAGNI）；`delete_project` 能力已备 | 项目删除级联清向量（跨存储事务复杂度高） |
| 15 错误码 | 新增 `EXTRACTION_ERROR` / `RAG_ERROR`（沿用 NOT_FOUND / VALIDATION_ERROR / LLM_ERROR / DB_ERROR）；「类型未注册」用 422 | 首个同时携带 LLM + 管线 + RAG 错误面的模块；独立码保证脚本可编程处理；422 承载业务校验语义 | 501 表达「类型不支持」（与业务校验混淆） |
| 16 API / CLI 布局 | 统一入口扁平 `POST /api/v1/extract` + runs/向量嵌套项目路径；CLI 两个顶级组 `extract` / `vector` | type 是资源维度（镜像 F9 `/characters/extract` 扁平先例）；runs/vector 是项目级资源；提取与向量是两个用户心智 | 塞进既有模块组（命令树膨胀）；单顶级组混放（心智混淆） |
| 17 伏笔提取合并 | 按 (project_id, title) 匹配活动伏笔 → 非空覆盖 / 新建；`status` 永不重置；不自动回收 | F13 partial unique 的「同名 = 同一伏笔」档案语义；status 是作者确认的状态机，自动迁移会破坏「已回收」语义；误报成本高 | 按描述相似度合并（不确定）；自动回收（误报率高） |
| 18 CLI 测试归属 | CLI 测试在顶层 `tests/cli/` + ci.yml `integration-cli-backend` job 显式列出文件 | 新 CLI 测试默认是 CI 盲区；显式文件列表是既有 job 风格（Windows pytest 不展开 glob）；unit 新文件自动覆盖 | 依赖 glob（CI 上不展开 → 假绿） |
| 19 时间线提取管线 | 新建「章节文本 → 时间线事件」LLM 提取管线 + `timeline_auto_extract`（默认 false；请求/CLI 可单次覆盖）；关闭退回确定性检查 | AI 自动写事件档案是副作用型能力，默认关闭 = 避免意外改档；显式开启即知情同意；关闭语义保留确定性检查 | 恒确定性检查（无提取能力）；默认开启（写入型自动化无门槛） |
| 20 事件-章节联动 | F12 事件加 `source_chapter_id`（可空 FK，ON DELETE SET NULL，已索引）；匹配键 `(project_id, title, source_chapter_id)`；仓储加 `list_by_chapter` | 与 F13 `event_id` 锚点同构（引用方负责校验，被引用方只加可空 FK）；同章同名 = 同一事件，跨章同名 = 不同事件；章节硬删不丢事件档案 | 仅按 title 匹配（跨章误合并）；不存来源（无法联动更新） |
| 21 切片策略模式 | `ChunkingMode` 四值（fixed/paragraph/dialogue/llm）+ `chunk_text` 按 mode 分发，共享 `Chunk{text, start_offset}` 与块 id 规则 | 固定 500 字切片不符合小说语义结构（对话密集章被硬切）；策略模式为后续档预留统一接口；默认 fixed 保持存量行为与向量不变 | 只做固定切片（语义结构丢失）；一次做透四档（成本递增未验证） |
| 22 重叠与指纹 | `rag_chunk_overlap` 默认 False，比例 [0.10, 0.20]；overlap>0 时块 id 加 `start_offset`、检索按章节去重取最高分；切片参数纳入指纹（`chunker_version` 手动 bump） | 默认关保持存量行为与索引体积；指纹联动使切片变更触发 stale → 提示重建（杜绝幽灵块）；去重防相邻重复块刷屏 | 默认开重叠（存量向量全失效）；不纳指纹（切片变更后检索结果静默错配） |
| 23 对话/LLM 切片降级 | 无对话文本 / analyzer 失败 / 未配模型 → 降级段落切片 + warning，reindex 不中断；LLM 档复用内容 hash 增量 | 失败不中断重建；hash 增量控制 LLM 档成本；降级保证任何文本都有可用切片 | 失败即整体失败（重建不可用） |
| 24 检索元数据口径 | 全书级 `chapter_x` / `chapter_y`（按 order_index 全局排序）+ `volume_title`；卷内序后置 | 复用 order_index 零额外 join；卷信息仅作展示 | 卷内级（无卷项目需退化逻辑）；两者都写（字段冗余） |
| 25 切片配置暴露面 | 仅 `app_settings`（GET/PATCH /settings）；`reindex` 不加覆盖参数 | 最小暴露面；配置持久化即生效；CLI 覆盖参数无场景（YAGNI） | CLI `--chunk-mode/--chunk-size/--overlap`（与持久化配置冲突） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 领域模型 + DTO 校验（ExtractionType 7 值（含 `KNOWLEDGE_RELATION`）/ ExtractionRequest 互斥与类型约束 / ExtractionResult / ExtractionRun / ReindexResult） | `pytest backend/tests/unit/domain/models/test_extraction_models.py -v` 全绿 |
| M2 | ExtractionRun 仓储（get/upsert(ON CONFLICT)/list，in-memory SQLite） | `pytest backend/tests/unit/infrastructure/database/test_extraction_run_repo.py -v` 全绿 |
| M3 | 门面分发（Mock 各模块 Service：7 类型委托（timeline 双语义：设置项开/关；STYLE → StyleService.analyze，F16 已注册；KNOWLEDGE_RELATION → F48 关系提取）+ 项目校验 + 结果归一） | `pytest backend/tests/unit/domain/services/test_extraction_service.py -v` 全绿 |
| M4 | 增量提取算法（hash 变更检测 / skip / force / 手动模式 / 断点续跑 / 部分失败语义；timeline 开启时按源增量、关闭时每次执行） | `pytest backend/tests/unit/domain/services/test_extraction_service.py -v` 全绿（增量相关用例） |
| M5 | 伏笔提取管线（foreshadowing_extract.yaml + ForeshadowingExtractor：解析/重试/合并/幂等） | `pytest backend/tests/unit/domain/services/test_foreshadowing_extractor.py -v` 全绿 |
| M5b | **时间线提取管线**（timeline_extract.yaml + TimelineExtractor：解析/重试/事件合并（匹配键 (project_id, title, source_chapter_id)）/ 设置项开/关切换（门面层判定）/ 事件-章节联动语义；含跨模块 MODIFY F12 四文件（source_chapter_id 字段 + list_by_chapter）） | `pytest backend/tests/unit/domain/services/test_timeline_extractor.py -v` 全绿 + F12 相关用例（test_timeline_repo 增补 list_by_chapter 用例） |
| M6 | LangChainVectorStore（FakeEmbeddings + tmp chroma：index/index_batch/retrieve/delete/delete_project/cosine/min_score/project_id 过滤） | `pytest backend/tests/unit/infrastructure/rag/test_langchain_vector_store.py -v` 全绿 |
| M7 | 章节分块 + reindex/retrieve 编排（_chunking.py + ExtractionService.reindex/retrieve + 索引编排） | `pytest backend/tests/unit/domain/services/test_chunking.py backend/tests/unit/domain/services/test_extraction_service.py -v` 全绿 |
| M8 | API 4 端点 + 错误路径全绿 | `pytest backend/tests/unit/api/routers/test_extractions_api.py -v` 全绿 |
| M9 | CLI extract/vector 组（信封/退出码/RAG_ERROR；style 走成功路径）；**ci.yml `integration-cli-backend` job 显式列出 `tests/cli/test_cli_extraction_crud.py`/`test_cli_extraction_errors.py` 与 `tests/cli/test_cli_vector.py`** | `pytest tests/cli/test_cli_extraction_crud.py tests/cli/test_cli_extraction_errors.py tests/cli/test_cli_vector.py -v` 全绿 + CI job 覆盖确认 |
| M10 | 手工验证闭环（含 BGE 首次下载）：建项目/章节 → 增量提取 → 索引 → 检索 → 变更重提取 → **时间线提取联动** | 手工验证（`inkflow chapter create` 建 2+ 章 → `inkflow extract run --type character --chapters ... --index` 首次 success → 再次同请求 status=skipped（⏭）→ 修改第 2 章内容（`chapter update`）→ 再提取只处理第 2 章（processed_sources=1、skipped_sources=1）→ `inkflow vector reindex` 全量 → `inkflow vector retrieve --query <章节人物/伏笔关键词>` 返回相关实体（首次自动下载 BGE ~100MB，需网络）→ **时间线场景**：项目更新设置 `config.extra["timeline_auto_extract"]=true`（或每次调用带 `--auto-extract` 单次覆盖）→ `inkflow extract run --type timeline --chapters ...` 提取事件 → `inkflow timeline list` 事件带 `source_chapter_id`（来源章节）→ 修改某章内容后重提取 → 同源事件被更新（updated>0）、新事件 created → 章节硬删后事件保留且 source_chapter_id 置空） |
| M11 | 全量回归 + 覆盖率 + lint/type | `pytest -v` 全绿；F14 模块行覆盖 ≥ 80%、全仓 ≥ 60%（DoD）；ruff + mypy 通过（CI 门禁 ADR-017）；domain/ 零框架 import（ADR-002/015，含 `_chunking.py`） |
| M12 | 切片器变体 + 重叠 + 元数据 + 指纹联动 | `pytest backend/tests/unit/domain/services/test_chunking_modes.py backend/tests/unit/domain/services/test_chunking.py -v` 全绿（段落切分/重叠率 ∈ 区间/块 id 三态/对话降级/LLM 降级/元数据 fallback/指纹联动）；扩展 test_search_service.py 元数据缺键 `.get()` fallback 用例；手工：改切片配置 → stale → `vector reindex` → 检索正常且无幽灵块、无相邻重复块 |
| M13 | 对话切片器 + LLM 分析切片器 | `pytest backend/tests/unit/domain/services/test_chunking_modes.py -v` 全绿（说话人切换边界/短块合并/无对话降级段落；LLM mock analyzer 边界生效/失败降级不中断/hash 相同跳过 analyzer）；手工：对话文本检索返回对话级 chunk；LLM 档内容未变章节不重复调用 analyzer |

---
