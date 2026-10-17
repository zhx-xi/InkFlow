# F44: 长任务编排器（long-task-orchestrator）功能规格

> **端**: cross
> **依据**: `design/agentic-orchestrator-and-memory-design-2026-08-14.md` §2 全文（唯一真相）、`docs/f44-orchestrator-spike-2026-08-17.md`（M1 门禁）
> **依赖**: [F6 上下文](../f6-context/spec.md) · [F27 Writer Agent](../f27-writer-agent/spec.md) · [F29 Supervisor](../f29-supervisor/spec.md) · [F39 多 Agent](../f39-multi-agent/spec.md) · [F42 Agent 链](../f42-agent-chain/spec.md) · [F43 设定库 GUI](../f43-setting-library-gui/spec.md)
> **参考 ADR**: [ADR-035](../../adr/agent/ADR-035.md)（编排引擎 = Deep Agents harness）· [ADR-006v2](../../adr/agent/ADR-006v2.md)（Agent 编排 LangGraph StateGraph）· [ADR-015](../../adr/llm/ADR-015.md)（LangChain 隔离）· [ADR-019](../../adr/packaging/ADR-019.md)（编号口径）· [ADR-027](../../adr/test-ci/ADR-027.md)（覆盖率门禁）

---

## 1. 概述

本 spec 覆盖「一句话→全书」长任务编排器的四个阶段（访谈式 Planner / 顺序派发 / 卷级编排 / 持久化与干预），是其唯一真相来源。定位（设计 §0/§1.1）：**学习 agent 开发 + 个人自用**，非商业产品——planner-executor、HITL、checkpoint、长上下文、多 agent 状态流逐概念落在 F26-F42 既有代码上做增量。**交付面 = 全栈**：后端 API + CLI 之外，阶段 1-4 **全含 GUI 面板**（主面板=主 agent 对话/思考/计划/调用子 agent；次面板=子 agent 详情手动点开；观察流三层密度 UI；干预控件；回归摘要面板）——定位「**全栈长任务编排器**」（后端编排引擎 + 前端交互面板一体交付）。

**一句话 → [Planner 访谈循环] → [Orchestrator Loop（逐章/逐卷推进 + 卷级 checkpoint + 跨运行 resume）] → [Executor（复用 F42 管线 + F27 writer agent）] → [护栏系统] → [恢复策略]**（设计 §2.2 架构）。

### 1.1 问题陈述

改造前存在六类缺口，四阶段设计即针对它们：

1. **无「一句话 → 计划」入口**：大纲生成是单次请求（`OutlineGenerateRequest`），无多轮访谈会话载体。
2. **无长任务编排元数据**：`ExecutionStore` 只有单次执行记录，无书级运行（run 分组 / 计划树 / 进度状态机）。
3. **无章级执行前置检查**：`create_execution` 前不查「该章已有内容 / 执行已完成」→ 重跑产生重复内容与双倍费用。
4. **无卷级并行执行**：既有编排均为单次运行内编排，无「卷内多章并行、卷间串行 + 边界确认」图形态。
5. **checkpointer 为 InMemorySaver**（进程内存），跨重启丢状态。
6. **无运行中干预**：执行启动后只能轮询状态 / 确认 HITL，无 pause / resume / 改向 / 编辑。

### 1.2 与样板差异

非 F9 实体 CRUD（WritingPlan 是新表但非普通业务实体）、非 F27 闭环型（多 agent 分层）、非 F29 动态路由型（无 supervisor 决策角色，路由=计划树）、非 F42/F46 配置驱动型（拓扑由计划树+进度驱动，非用户配置）——本模块是**编排元数据 + 计划树驱动执行**：后端新增 WritingPlan 实体/访谈会话/书级运行 API/干预 API；CLI 新增 `inkflow book` 命令组；前端交互（主面板对话/子 agent 展开行/观察流三层密度/干预控件）**已拍板全含**。

### 1.3 边界声明

- **不含** F45 记忆演进（独立里程碑；其 M2 依赖本模块阶段 4 之后的长跑证据）
- **不含** deepagents `task` 工具嵌套委派（F26 已禁用）：阶段 3 委派形态 = LangGraph Send API 并行 fan-out（设计 §2.3-3 硬约束），包装 F27 writer-agent，**不是** deepagents subagent 工具
- **不含** 章内断点、幂等键框架、唯一索引冲突框架、token 精确核算、双面板精致化、三级 agent（设计 §2.5 苦工清单「先能用再修」）；访谈分批状态机已由 LLM 动态提问取代（§5.1，确定性分批仅保留为 LLM 失败降级兜底，§7 场景 15）；GUI 仅含基础面板交互（§5 各阶段 GUI 小节），品牌动画/视觉打磨等精致化仍按 ui-design-taste 克制原则留范围外（§10）
- **不含** MCP 表现层（F20 薄客户端经 HTTP，本模块端点经既有 HTTP 通道天然可用，不新增 MCP 工具）

---

## 2. 数据模型

### 2.1 WritingPlan 领域实体（新建 `domain/models/writing_plan.py`）

设计 §2.2 数据模型决策：**planner 产出的大纲/角色直接写现有 `outline`/`character` 实体（复用 P3+P4 三级结构 level/parent_id/chapter_id），`WritingPlan` 只存编排元数据（结构树 + 进度 + 产物引用），不重复存内容**——打通设定库与 RAG 检索（outline/character 落库后天然可被 RAG 检索，WritingPlan 不持有正文副本）。

```python
class PlanNodeStatus(StrEnum):
    """计划节点进度状态机（设计 §2.2 +  要点：pending/in_progress/done/failed/skipped）。"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

class WritingPlan(BaseModel):
    """书级编排元数据（新建表 writing_plans）。

    Attributes:
        id: 计划 UUID.
        project_id: 所属项目 UUID.
        title: 书名/计划名（planner 访谈产出，或用户一句话标题）.
        status: 计划状态（drafting=访谈中 / ready=可执行 / running=执行中 /
                completed / aborted）.
        root_outline_id: 书级大纲（level=overall）UUID —— 结构树锚点，章/卷经
            outline 表 level/parent_id 推导，本表不重复存树.
        character_ids: 主角/配角 character 实体 id 列表（planner 产出）.
        limits: 多维上限（§2.4），含「至少一道有限护栏」校验.
        progress: 节点进度快照 {outline_id: PlanNodeStatus}（执行时更新，
            与 outline 表共存；以本字段为权威进度）.
        execution_refs: 章执行引用 {outline_id: execution_id}（章→agent_executions 记录）.
        tasklist: supervisor 产出的任务清单——有序条目列表
            [{op, outline_id, title}]（op ∈ write_chapter/audit_chapter/revise_chapter/
            mark_done/finish_book；决策重试耗尽时追加 {op: "__degraded__", reason}）。
            「计划 / 决策记录」面，**非约束**：不驱动 progress（progress 恒为
            「实际执行态」权威源，单向，零双写漂移）.
        thread_id: LangGraph checkpoint thread_id（阶段 4 落库，§2.3）.
        created_at / updated_at: 时间戳.
    """
    model_config = {"from_attributes": True}
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    status: str = "drafting"
    root_outline_id: uuid.UUID | None = None
    character_ids: list[uuid.UUID] = Field(default_factory=list)
    limits: dict[str, int] = Field(default_factory=dict)
    progress: dict[str, str] = Field(default_factory=dict)      # outline_id -> status
    execution_refs: dict[str, str] = Field(default_factory=dict)  # outline_id -> execution_id
    tasklist: list[dict] = Field(default_factory=list)          # supervisor 任务清单
    thread_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
```

**决策论证表**：

| 决策 | 方案 | 理由 | 否决备选 |
|------|------|------|----------|
| WritingPlan 载体 | **独立表**（writing_plans + 元数据字段） | 编排元数据（进度/上限/执行引用/thread_id）与业务内容（大纲/角色）生命周期不同：大纲可独立编辑，进度随执行漂移；独立表零侵入 outline 表既有唯一索引语义 | outline 表加 column（污染内容表 + 每卷/每章都要加进度列 + 与 outline CRUD 耦合） |
| 结构树存储 | **root_outline_id 锚点 + outline 表推导** | outline 已含 level/parent_id/chapter_id 三级结构（P3+P4），重复存树=双份真相漂移；锚点 + 引用即可还原全树 | WritingPlan 内嵌树 JSON（重复内容，违反设计 §2.2「不重复存内容」） |
| 计划产物归属 | **直接写 outline/character 实体** | 打通设定库与 RAG（outline/character 落库即被检索）；planner 不持有私有副本 | WritingPlan 内嵌大纲副本（隔离于 RAG，需二次同步） |

### 2.2 访谈会话载体（新建 `domain/models/planner_session.py`； 扩展确定项/冲突/总体确认字段）

访谈式 Planner 的多轮会话（设计 §2.1 约束 5/6：分批 ≤5 问、问题即模板；起问题由 LLM 动态生成，确定项/冲突/总体确认落会话供 消费）：

```python
class PlannerSession(BaseModel):
    """访谈会话（新建表 planner_sessions，阶段 1； 扩展）。

    Attributes:
        id: 会话 UUID.
        project_id: 所属项目 UUID.
        status: drafting / completed / declined（「全部你决定」= declined → 直接跑 F42）.
        one_liner: 用户一句话（题材/体裁/篇幅/主角等原始输入）.
        round: 当前轮次（每轮 ≤5 问）.
        asked_questions: 已问问题快照（JSON，供问题即模板复用；由 LLM 生成）.
        answers: 用户回答快照 {question_id: answer}.
        authorized: 显式授权项（如「配角自定」「细节自定」，设计 §2.1 约束 1 完成度授权）.
        confirmed_items: 已确定项快照——
            LLM 每轮从对话提取，只提问未确定项；全量落库供 会话/记忆 UI +
            提取记忆/设定库 + 用户审计（§5.1 后端契约）.
        conflicts: 冲突/回问记录——
            回答与已确定项/设定冲突或不合理时回问用户重新确认（§5.1）.
        confirming: 是否处于末尾总体确认阶段——
            必答项齐备后置 True，向用户列出全部确定项待总体确认；confirm 通过 →
            completed；用户修改 → 回 questioning 重问（§5.1）.
        writing_plan_id: 会话完成后关联的 WritingPlan UUID（None = 未完成）.
        created_at / updated_at.
    """
    model_config = {"from_attributes": True}
    id: uuid.UUID
    project_id: uuid.UUID
    status: str = "drafting"
    one_liner: str
    round: int = 1
    asked_questions: list[dict] = Field(default_factory=list)
    answers: dict[str, str] = Field(default_factory=dict)
    authorized: list[str] = Field(default_factory=list)
    confirmed_items: list[dict] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    confirming: bool = False
    writing_plan_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
```

>  注：`confirmed_items`/`conflicts`/`confirming` 为增量字段——既有 planner_sessions 表加 JSON 列（零迁移，nullable 默认空，§8.2 MODIFY 登记）；既有 drafting/completed/declined 状态语义不变（confirming 为对话阶段标志，非 status 值）。

### 2.3 AgentExecutionORM 扩展（阶段 4，`infrastructure/database/models/agent.py` MODIFY）

`agent_executions` 表加 1 列（Spike ⑥ 结论 + 「thread_id 落 agent_executions」）：

```python
thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
"""LangGraph checkpoint thread_id（书级运行 ↔ 图 checkpoint 一一映射；None = 非书级运行）"""
```

零迁移（`create_all` + 轻量幂等迁移，无 alembic）：新列 nullable 无默认值变更，既有行兼容。

### 2.4 多维上限（设计 §2.1 约束 3 + 「至少一道有限护栏」不变式）

```python
class BookLimits(BaseModel):
    """书级运行上限配置（请求体可传；缺省取 ProjectConfig.extra 项目级默认，Q2=C 拍板，§12 D11）。

    - max_chapters: 硬护栏——章节数上限（默认 100，可配置）
    - max_agent_calls: 硬护栏——子 agent 调用次数上限（默认 200，可配置）
    - max_tokens: 软护栏——累计 token 预算（默认 200_000，可配置；超限告警，
      不强制终止，与硬护栏区分——「token 软上限，硬护栏=章数/步数/子调用数」）
    - max_sessions: 硬护栏——访谈轮次上限（默认 5 轮 × 5 问）
    """
    max_chapters: int = 100
    max_agent_calls: int = 200
    max_tokens: int = 200_000
    max_sessions: int = 5

def validate_at_least_one_hard_limit(limits: BookLimits) -> None:
    """「至少一道有限护栏」不变式：max_chapters/max_agent_calls
    至少一个为有限值（>0）；全部无上限（0 或 None）→ ValueError 拒绝启动。"""
```

**读取优先级**：请求体 `BookLimits` 显式 > 项目级 `ProjectConfig.extra`（键 `book_max_chapters`/`book_max_agent_calls`/`book_max_tokens`/`book_max_sessions`）> §2.4 默认常量。载体 = **ProjectConfig.extra 项目级扩展字典**（F1 既有字段，零 MODIFY——F43 P1 四层核实：extra 在 domain/ORM/router/service 均已透传；**不是** F32 全局 settings，与 F27 预算护栏「全局设置」语义分道，理由见 §12 D11）。

**计数器**：运行中在 `WritingPlan.progress`/`execution_refs` 旁维护 `counters`（调用数/累计 token/已生成章数）——阶段 1 写死 `max_chapters=1/max_agent_calls=1` 但计数器立起来；阶段 2 起可配置（§5.2）。

## 3. API 契约

新路由 `api/routers/books.py`，前缀 `/api/v1/agent/books`（与既有 agent router `/api/v1/agent/pipelines/*` 同域，复用 `api/deps.py` get_db/鉴权模式）。全部端点 202 异步语义（与 F42 execute 同构：启动即返回、状态经 GET 轮询）。

### 3.1 端点总览

| 方法/路径 | 阶段 | 说明 | 状态码 |
|-----------|------|------|--------|
| `POST /planner` | 1 | 启动访谈会话（body 一句话 + project_id）→ 返回会话 + 第一轮 ≤5 问 | 201 |
| `POST /planner/{session_id}/respond` | 1 | 回复本轮问题（或 `auto=true` 全部你决定）→ 下一轮问 / 冲突回问 / 末尾总体确认（`confirm`）/ 完成返回 WritingPlan | 200 |
| `GET /planner/{session_id}` | 1 | 访谈会话状态（已问问题/回答快照 + 确定项/冲突，问题即模板复用；供用户审计回溯） | 200 |
| `POST /runs` | 1/2/3/4 | `write_book` 启动书级运行（body：writing_plan_id 或 one_liner；limits；mode；**：`force` + `confirm_overwrite` 双条件显式覆盖**，见 §5.8） | 202 |
| `GET /runs/{run_id}` | 1-4 | 书级运行状态（进度树 + 计数器 + 当前 interrupt + 章级只报告） | 200 |
| `POST /runs/{run_id}/confirm` | 3 | 卷级 HITL 确认（body `{approved, decision?}`；非 waiting_hitl → 422） | 200 |
| `POST /runs/{run_id}/intervene` | 4 | 中途干预（pause/resume/改向/编辑，§3.3） | 200 |
| `GET /runs/{run_id}/summary` | 4 | 回归摘要 + 结构化运行日志（§3.4） | 200 |
| `POST /runs/{run_id}/reset` | 4 | 重置执行态（清 progress/execution_refs + 退回 `ready`，**不删正文**； 方案 B——「不删旧稿就重跑」出口） | 200 |
| `POST /chapters/{chapter_id}/restore-previous` | 4 | 把 `chapters.previous_content` 写回 `content`；无旧稿 → 409；章不存在 → 404 | 200 |

### 3.2 请求/响应示例（阶段 1 访谈 + 阶段 3 卷确认）

 注：访谈问题由 LLM 按 `one_liner` + 项目设定动态生成——`questions[]` 含 `kind` 字段（`general` 通用必答 = 题材/篇幅/主题等必须确认项；`targeted` 针对性 = 按小说大纲/类型/设定动态提问），`template` 仍保留（问题即模板，可点击复制）；响应新增 `confirmed_items`/`conflicts`/`confirming`（§2.2 同构）。

```jsonc
// POST /api/v1/agent/books/planner
{ "project_id": "uuid", "one_liner": "写一本关于时间旅者的悬疑小说" }
// 201 —— 第一轮：通用必答 + 针对性并存
{ "session_id": "uuid", "round": 1,
  "questions": [
    { "id": "q1", "text": "题材：悬疑为主，还是悬疑+科幻混合？", "template": "悬疑为主，但加入 ___ 元素", "kind": "general" },
    { "id": "q2", "text": "篇幅：预计多少字？", "template": "约 ___ 字", "kind": "general" },
    { "id": "q3", "text": "主题：能否一句话描述主题？", "template": "主题是 ___", "kind": "general" },
    { "id": "q4", "text": "时间旅者的设定：穿越机制是设备还是能力？", "template": "穿越通过 ___ 实现", "kind": "targeted" }
  ], "max_rounds": 5,
  "confirmed_items": [], "conflicts": [], "confirming": false }

// POST /api/v1/agent/books/planner/{session_id}/respond
{ "answers": { "q1": "悬疑为主，加入时间悖论科幻元素" }, "auto": false }
// 200 —— LLM 提取已确定项 + 只问未确定项
{ "session_id": "uuid", "round": 2, "completed": false,
  "questions": [ { "id": "q5", "text": "配角：需要几个主要配角？", "template": "___ 个", "kind": "general" } ],
  "confirmed_items": [ { "key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user" } ],
  "conflicts": [], "confirming": false }

// POST /api/v1/agent/books/planner/{session_id}/respond （冲突/不合理回问）
{ "answers": { "q5": "配角 5 个" } }
// 200
{ "session_id": "uuid", "round": 3, "completed": false,
  "questions": [ { "id": "q6", "text": "5 个配角对 10 万字篇幅偏多，建议 2-3 个——仍按 5 个？", "kind": "conflict" } ],
  "confirmed_items": [ { "key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user" } ],
  "conflicts": [ { "round": 2, "question_id": "q5", "answer": "配角 5 个", "conflict_with": "篇幅/复杂度合理性", "resolution": "pending" } ],
  "confirming": false }

// POST /api/v1/agent/books/planner/{session_id}/respond （末尾总体确认）
{ "answers": { "q6": "那配角 2 个" } }
// 200 —— 必答项齐备 → confirming=true，questions 空，列全部确定项
{ "session_id": "uuid", "round": 4, "completed": false, "questions": [],
  "confirmed_items": [
    { "key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user" },
    { "key": "篇幅", "value": "10 万字", "source": "user" },
    { "key": "主题", "value": "时间旅者自我救赎", "source": "llm_inferred" },
    { "key": "配角数", "value": "2 个", "source": "user" }
  ],
  "conflicts": [ { "round": 2, "question_id": "q5", "answer": "配角 5 个", "conflict_with": "篇幅/复杂度合理性", "resolution": "resolved" } ],
  "confirming": true }

// POST /api/v1/agent/books/planner/{session_id}/respond （总体确认通过 → 完成）
{ "confirm": true }
// 200 { "session_id": "uuid", "round": 4, "completed": true, "confirming": false, "writing_plan": { ... } }

// POST /api/v1/agent/books/runs/{run_id}/confirm （阶段 3 卷边界 interrupt 时）
{ "approved": true, "decision": "继续下一卷" }
// 200 { "run_id": "uuid", "status": "running", "next_checkpoint": "卷 2" }
```

### 3.3 干预 API（阶段 4，粒度=卷级锚点 + 章级被动动作，Q3=A 已拍板 ✅ v1.1，§12 D12）

```jsonc
// POST /api/v1/agent/books/runs/{run_id}/intervene
// pause：暂停书级运行（后台任务挂起，卷边界 checkpoint 已存）
{ "action": "pause" }
// resume：恢复运行（等价 Command(resume)，跨进程后同样可用）
{ "action": "resume" }
// redirect：改向——跳过某章（mark failed/skipped）或改下一章执行顺序
{ "action": "redirect", "target": "outline_id", "to": "skip" }
// edit：编辑进行中状态（章 brief/大纲文本），干预效果带差异标注（§3.4）
{ "action": "edit", "target": "outline_id", "payload": { "brief": "修改后的章 brief" } }
```

### 3.4 观察流三层密度 + 回归摘要（设计 §2.6 自用三件核心）

| 端点/字段 | 密度 | 内容 |
|-----------|------|------|
| `GET /runs/{run_id}` `trace` 字段 | 三层 | 表演=主 agent 思考/决策/子 agent 调用轨迹全文；仪表=每章状态 + 计数；无声=仅进度树。默认全开，查询参数 `density=performance|dashboard|silent` 可压缩 |
| `GET /runs/{run_id}/summary` | — | 回归摘要：到哪了（进度树）/接下来（下一卷/章）/已耗（计数）一页说清；结构化运行日志 = `steps` JSON 快照（镜像 F27 AgentStep 序列），可回放复盘导出 |
| 干预响应 `diff` 字段 | — | 干预后输出带差异标注（edit 前后 brief/大纲文本 diff，difflib 字面 diff 即可，零 LLM） |

> GUI 对接：三层密度切换控件（表演/仪表/无声）消费同一 `density` 查询参数；`trace`/`summary`/`diff` 为 GUI 观察流与回归摘要面板的渲染数据源（§5.4 GUI 交互设计）。

### 3.5 异常映射

| 异常 | 状态码 | 说明 |
|------|--------|------|
| 会话不存在 | 404 | planner session 查无 |
| 运行不存在 | 404 | run_id 查无 |
| 上限校验失败（全无护栏） | 422 | `validate_at_least_one_hard_limit` ValueError |
| 「内容已写」安全阀命中 | 409 | 该章已有内容/执行已完成（设计 §2.3-1，§5.2） |
| 非法干预动作/目标 | 422 | 非 pause/resume/redirect/edit；目标 outline 不存在 |
| 非 waiting_hitl 确认 | 422 | 卷确认仅在 interrupt 暂停点可用（F29 confirm 同构） |
| 非 confirming 阶段 confirm | 422 | 末尾总体确认仅在 `confirming=true` 时可用（`confirm` 请求体；F29 confirm 同构防呆） |
| outline 撞名 | 409 | 复用既有唯一索引语义（批量生成撞 IntegrityError → 服务层捕获转 409，见 §6） |
| planner 完成路径·总纲同名 | 422 | `_complete` 按名查重复用既有总纲；无从复用（未装配查重面 / 并发窗口二次查名仍缺）→ `OutlineNameConflictError` → 422 + 消息即 detail。**区别上方 409**：那行是**批量生成**路径的 DB `IntegrityError` 捕获，本行是完成路径的领域前置校验异常（与 `extractions.py` 既有映射同源） |
| planner 完成路径·主角同名 | 422 | 同上（`CharacterNameConflictError`，F9 `CharacterServiceError` 家族，与 `characters.py` 既有映射一致） |

## 4. CLI 命令签名

新命令组 `inkflow book`（`cli/commands/book_cmd.py`，F7 全局约定：`--json` 信封 / 退出码 0/1/2 / 错误码）。访谈/运行全程可脚本化，输出 Rich 进度树。

```bash
# 阶段 1：访谈式 Planner
inkflow book plan start "写一本关于时间旅者的悬疑小说" --project <uuid>   # 启动访谈，打印第一轮问题（通用必答 + 针对性）
inkflow book plan respond <session> "悬疑为主，加入时间悖论"              # 回复一轮（LLM 提取确定项 → 只问未确定项）
inkflow book plan confirm <session>                                       # 末尾总体确认通过（列全部确定项后）
inkflow book plan auto "写一本关于时间旅者的悬疑小说" --project <uuid>    # 「全部你决定」→ 直接跑 F42 write_auto
inkflow book plan show <session>                                          # 会话状态（问题即模板复用 + 确定项/冲突快照）

# 阶段 2-4：书级运行
inkflow book run <plan_id> [--limits max_chapters=5,max_tokens=200000]    # 启动（顺序派发/卷级按进度）
inkflow book run <plan_id> --force --confirm-overwrite                    # ：显式跳过安全闸并覆盖已有正文（旧稿落 chapters.previous_content）
inkflow book status <run_id> [--density performance|dashboard|silent]     # 状态轮询（观察流三层密度）
inkflow book confirm <run_id> --approved --decision "继续下一卷"          # 卷级 HITL 确认（阶段 3）
inkflow book intervene <run_id> --action pause|resume|redirect|edit ...   # 中途干预（阶段 4）
inkflow book summary <run_id> [--export <file.json>]                      # 回归摘要 + 结构化日志导出
```

**「全部你决定」兜底**（设计 §2.1 约束 7）：`plan auto` = 拒访谈 → 完全自主生成 → 跑 F42 `write_auto` 管线（§5.1 委托契约衔接）。

## 5. 关键差异节：长任务编排（Planner 访谈 → Orchestrator Loop → Executor → 护栏 → 恢复）

按 - 四阶段组织。每阶段为独立实现批（可独立合入），但共享本 spec 的数据模型与 §6 组织规则。

### 5.1 阶段 1：访谈式 Planner + WritingPlan + 委托

**访谈循环**（设计 §2.1 约束 5/6/7；** 起为 LLM 动态提问**，D1 需求 1-5 全落地）：
- 每轮 ≤5 问，问题**由 LLM 动态生成**（不再硬编码 ROUND1/ROUND2 常量）——**通用必答**（题材/篇幅/主题等必须确认项，`kind=general`）+ **针对性**（按 one_liner/小说大纲/类型/设定动态提问，`kind=targeted`）并存；问题仍带 `template`（问题即模板，可复制修改后作为回复）；全程可跳过/回改
- **已确定项提取**（D1 需求 2）：每次回答后 LLM 提取「已确定项」→ `PlannerSession.confirmed_items` 落库（key/value/source）；下轮问题**只问未确定项**（prompt 注入 confirmed_items 去重，不重复提问）
- **冲突/不合理回问**（D1 需求 3）：回答与已确定项/项目设定冲突或不合理 → `conflicts` 记录（含 resolution=pending）+ 生成冲突回问题（`kind=conflict`）请用户重新确认
- **末尾总体确认**（D1 需求 4）：必答项齐备 + 无 pending 冲突 → `confirming=true`，向用户**列出全部确定项**待总体确认；`confirm=true` → 完成（创建 WritingPlan）；用户修改某项 → 回 questioning 重问
- 大纲/主角 = **必须对话确认**（通用必答项服务端强约束，见后端契约）；配角/细节 = 显式授权后自定（`authorized` 字段，「完成度授权」）
- 「全部你决定」= 拒访谈 → 完全自主生成 = 跑 F42 `write_auto`（委托契约见下），WritingPlan 仍创建（状态=auto）
- 访谈会话载体 = `PlannerSession`（§2.2）；完成后创建 `WritingPlan`（§2.1）+ planner 产出**直接写 outline/character 实体**（§2.1 决策论证表）
- **模型解析链**：提问引擎的模型经 `resolve_model(None, 项目 config.model, 全局默认)` 单点解析（优先级 `agent > 项目 > 全局`）；项目配置经 `project_repo.get(session.project_id)` 读取——**入参为领域 UUID**（ADR-060 D9，`require_uuid_pk` 在 repo 内完成 UUID→int 归一，调用方**不得**自行 `.int`）。可预期失败（DB 抖动）→ 回退全局默认（零告警，§7 场景 15 语义不变）；**契约违规（如裸 int 入参 → `TypeError`）必须冒泡**，不得静默降级成「未配置模型」
- **完成路径幂等**：`_complete`（LLM confirm 与确定性降级**两条路径共用**）对总纲与主角均**先按项目内名称查重复用**（`outline_repo.get_by_name` / `character_repo.get_by_name`），命中即复用既有行并回填 `root_outline_id` / `character_ids`；创建时撞名（并发窗口）→ 二次查名复用；未装配查重面且撞名 → 原样抛出（**不得**静默跳过创建，也**不得**改生成名新建）；两种冲突经 API 映射 422 + 可读 detail（§3.5）
- **产物质量护栏**：① LLM 失败降级的兜底题材题**中性化**——题面保留「题材」必答关键词但不得自带任何具体题材预设（如「悬疑」），避免与 one_liner 语境脱节；② `WritingPlan.title` = one_liner 前 **30 字**短标题（对齐会话自动命名 30 字先例，≤30 字保持原文），outline name = 短标题 +「（书级大纲）」、完整 one_liner 进 description；③ planner 建主角经装配闭包构造 `CharacterCreate` DTO，缺省补 `extra.role_rank=protagonist`；主角名短名化护栏；④ `_complete` 落库 limits **从访谈 answers/confirmed_items 文本提取**章数（见下「上限」）

**LLM 动态提问引擎**（PR-1 后端契约，S3 实现轨）：

```
问题生成/确定项提取/冲突检测 = PlannerService.start/respond 内单次 LLM 调用（结构化 JSON 输出）：
  prompt 输入 = one_liner + 项目设定摘要（outline/character 已落库内容 + F28 偏好注入链复用）
                + 会话历史（answers/confirmed_items/conflicts，已确定项不再重复提问）
  prompt 输出 = { questions: ≤5 问[{id, text, template?, kind: general|targeted|conflict}],
                  confirmed_items: [{key, value, source: user|llm_inferred}],
                  conflicts: [{conflict_with, resolution: pending|resolved}] }
  服务端强约束：通用必答项（题材/篇幅/主题）未确认时必须出现在 questions 中——LLM 输出校验
                （缺失必答项 → 该轮拒绝/补问，防 LLM 漏问）；校验失败重试 1 次
  失败降级：LLM 调用失败/超时 → 重试 1 次 → 仍失败 → 回退 ROUND1/ROUND2 确定性常量
            ，访谈不阻塞；兜底题面不得自带题材预设
  落库：confirmed_items/conflicts/confirming 全量写 PlannerSession（§2.2 字段）；
        GET /planner/{session_id} 返回快照供用户审计（D1 需求 5 +）
```

**agent 工厂**（复用 F27，换 system prompt）：复用 `build_agentic_writer`（`agentic_writer.py` 签名实证：model/api_key/base_url/deps/system_prompt/tool_ids/skill_ids/profile_key/expected_project_id/expected_chapter_id）——白名单工具 + skill 拼接 + save_draft 回收 + agent_run 轨迹，仅 system_prompt 换为「章 writer」模板（含大纲切片/风格/偏好注入）。

**委托契约**（章 brief → save_draft 回收）：
```
章 brief = outline 章节点切片（描述/父卷上下文） + character 主角/配角摘要 + 风格/偏好（F28 注入链）
→ build_agentic_writer(system_prompt=渲染后的章 brief) → ReAct 循环 → save_draft（单工具单事务）
→ Draft 落库（status=draft） → 章级只报告（约束 8：不 interrupt）
```

**上限**：写死 `max_chapters=1/max_agent_calls=1`——计数器字段/校验逻辑先存在，阶段 2 放开配置。** 修订**：`_complete` 访谈完成路径改为**从访谈输入提取**——扫描 answers + confirmed_items 文本中「N 章」阿拉伯数字声明（先剔除「第N章」章序引用防误抽，多处命中取最大）→ `max_chapters=n / max_agent_calls=2n`（卷轨拆章+逐章委托余量）；无声明保持 STAGE1 保守兜底 1/1（auto/`_run_auto` 路径无访谈输入，仍写死 STAGE1）。`POST /runs` 请求体显式 limits 仍按 §2.4 优先级链覆盖落库值。

**对话式 UI**（PR-2 前端契约，S3 实现轨）：

```
BookPlannerPanel 固定表单 → 对话式消息流（ChatPanel  先例）：
  - 消息列表：assistant（问题/冲突回问/确定项汇总）/ user（one_liner/回答/确认）——LLM 动态提问天然对话式
  - 输入框 + 发送：自由文本回答（不再逐题表单填写）
  - 问题即模板保留：消息内嵌 template chip 点击填入输入框
  - confirmed_items 汇总卡片：confirming=true 时展示全部确定项 + 确认/修改按钮
    （确认 → respond {confirm:true}；修改 → 输入新值重新回问）
  - conflicts 警示样式：kind=conflict 消息高亮展示冲突内容 + 待确认
  - 「全部你决定」（auto=true）一键委托按钮保留
  - 前端契约扩展（api/books.ts）：PlannerQuestion 加 kind；respond 响应加
    confirmed_items/conflicts/confirming；PlannerRespondRequest 加 confirm
```

**GUI 交互设计**：
- **单面板对话（访谈）**：写作页域或新 book 页的面板承载访谈对话——先例 = `ChatPanel`（`executePipeline(builtin:chat)` → 1s 轮询 `getExecutionStatus` → completed 消息 + 「插入正文」→ `chapterStore.setContent`），本阶段对接 `POST /planner` + `POST /planner/{id}/respond`（SSE 复用 F23 基建，访谈问题即模板可点击复制）；「全部你决定」（auto=true）一键委托按钮；对话式增强：确定项汇总卡片（confirming=true 展示 + 确认/修改）、冲突回问警示样式（kind=conflict）
- **子 agent 展开行（观察流）**：访谈/委托执行轨迹按 `GET /runs/{run_id}` `trace` 字段渲染可展开行（子 agent 调用/思考/工具调用），默认折叠、手动点开（次面板语义）
- 状态：`PlannerSession`（drafting/completed/declined + confirming 对话阶段标志）→ `WritingPlan`（drafting/auto）驱动面板阶段切换；聊天消息本地 store（镜像 chapterStore 模式）
- 落点（写作页域 vs 新 book 页）由实现会话定；本 spec 只定交互语义 + 端点对接 + 状态（§8 frontend 组件清单）

### 5.2 阶段 2：顺序派发 + 进度状态机 + 多维上限 + 安全阀

**计划=数据**：章列表入 `outline` 表（level=chapter + parent_id 挂 volume；level=overall 书级锚点 + level=volume 卷节点，P3+P4 三级结构已就绪零 MODIFY）。

**顺序派发**：`write_book(plan)` 按 outline 树顺序逐章执行（阶段 2 无并行；阶段 3 起卷内 Send 扇出）。每章执行 = F42 `builtin:write_auto` 管线（或 F27 agentic 章 writer，按章 brief 委托）。

**章级进度状态机**：`WritingPlan.progress` 每章落库 `pending → in_progress → done/failed/skipped`（章级只报告，不 interrupt）。

**多维上限**（§2.4）：`BookLimits` 可配置（章数/token/调用，阶段 2 放开）；启动前校验「至少一道有限护栏」（`validate_at_least_one_hard_limit`）——token 为软护栏（超限告警），章数/调用数为硬护栏（超限终止）。

**「内容已写」安全阀**（设计 §2.3-1，最高优先级）：`create_execution` 前查该章已有内容（`Chapter.content` 非空 / `Draft` 存在）/执行已完成（`execution_refs[outline_id]` 存在且 status=done）→ **拒绝重跑**（409，§3.5）——一行 WHERE 拆掉「重复内容 + 双倍费用」。

**章级幂等写**：每章一次 save_draft（同一章执行不重复写；重复调用被安全阀拦截在前）。** 修订**：安全阀只拦「重复**执行**」，拦不住单次 agent run 内 LLM 自主多次 save_draft（rc5 实测 10 章 12 稿）→ 幂等下沉工具层：book 轨装配链把章锚点（`expected_source_outline_id`=outline 章节点 id，`expected_volume_outline_id`=卷 outline 节点 id）传给 save_draft 工具，工具按「同项目 + 同章（bound_chapter_id/source_outline_id）」查未确认稿，存在 → 覆盖内容返回同 draft_id，不存在 → create（契约见 F27 spec §5.2「装配期锚点绑定 + 同章幂等」）。

**锚点传递**：委托兜底路径 `draft_service.create(source_outline_id=chapter["outline_id"], …)` 与 agent 自调 save_draft 路径**必须同锚点**（同族路径统一拍板先例）——writer_factory 增 `expected_source_outline_id`/`expected_volume_outline_id` 形参，`book_pipeline._delegate_chapter`、`book_service._delegate_chapter`、`book_agentic_pipeline._delegate_write` 三委托点装配时传入（`books.py _writer_factory` → `build_agentic_writer` 透传）。目标：book run 终态 `drafts.source_outline_id` 非空 → confirm 自动建章后 D4 回填 `outlines.chapter_id` 生效。

**自动建卷 + 章节归卷**：confirm 的 D4 自动建章分支只透传 `draft.volume_id`——book 轨该值恒 None（卷 outline 节点的 `outlines.volume_id` 列未写），导致书级运行写完全书后 `GET /volumes` 为 0、章节全部 `volume_id=None`（数据面实证：10 章 0 卷 10 未分组，而大纲树完整）。修订：`DraftService` 增可选注入 `volume_ensurer`（`(project_id, chapter_outline_id) -> 卷 UUID | None`，弱依赖永不抛错）；confirm 建章前按「**草稿既有 `volume_id` 优先** → 否则沿生效来源 outline（显式参数 > 草稿 `source_outline_id`， 口径）上溯 `parent_id` 至 `level=volume` 卷大纲 → 取其 `name` 按 (project_id, title) **ensure** `volumes` 行 → 否则 None」解析卷并透传 `create_chapter(volume_id=…)`。装配点 = `api/deps_draft.make_volume_ensurer`（db 会话闭包工厂，镜像 `make_outline_bindder`），通用轨（`deps.get_draft_service`）与 book 轨（`books._build_book_service`）双注入。**幂等**：同项目同名卷复用（多章同卷一行；重复 confirm 不重复建卷）。**无卷父**（章节点无 parent / parent 非 volume / 跨项目 / 行不存在）→ 保持 `volume_id=None`（不臆造卷）。

**GUI 交互设计**：
- **章级进度状态 UI**：`WritingPlan.progress` 渲染（pending/in_progress/done/failed/skipped 状态徽标 + 章进度条/进度树），`GET /runs/{run_id}` 轮询驱动（镜像 `ChatPanel` 1s 轮询模式）；观察流密度=仪表（每章状态 + 计数器）
- **安全阀 409 文案展示**：「该章已有内容，拒绝重跑」错误 toast/内联提示（防用户重复点击启动）
- 状态：progress 快照为权威（§6 R2），GUI 只读渲染不持有执行状态

### 5.3 阶段 3：卷级编排 + Send map-reduce + 卷级 HITL + 失败恢复

**两级层级**：书级由主 agent（supervisor，F29 复用）承担——负责卷规划/卷间推进/失败补救决策；卷级由**卷 planner 动态拆章**（每卷章节数/顺序由卷 planner 决定，落 outline 表 chapter 节点；卷边界确认时原子落库——Spike 遗留验证点 2）。

**Send map-reduce 并行 fan-out**（Spike ①-④ 已证实，设计 §2.3-3）：
```python
def volume_fan_out(state: VolState) -> Command:
    """卷节点：Send 扇出该卷全部章执行节点（无 interrupt）。"""
    return Command(goto=[Send("write_chapter", {"chapter": ch}) for ch in state["chapters"]])

class VolState(TypedDict, total=False):
    chapters: list[dict]
    results: Annotated[dict[str, str], operator.or_]   # map-reduce 聚合（Spike ② 必备 reducer）
```
- **扇出形态 = `Command(goto=[Send(...)])`，不是 `return [Send(...)]`**（经典文档写法报 InvalidUpdateError；`_control_branch` 只认 Command 形态）
- **聚合通道必须 `Annotated[dict, operator.or_]` reducer**（Spike ②：同 superstep 并发写普通 dict 报 INVALID_CONCURRENT_GRAPH_UPDATE；镜像 `PipelineState.results` 既有模式）
- 章执行节点包装 F27 writer-agent（§5.1 委托契约），**节点内不放 interrupt**（Spike ④：分支内 interrupt → multiple pending interrupts → resume 必须带 interrupt id，语义歧义；设计 §2.3-2 硬约束实证）

**卷级 HITL 锚点**（约束 8：卷级暂停、章级只报告）：
```
volume_fan_out（Send 扇出，无 interrupt） → write_chapter 分支（并行，只写进度）
→ join（map-reduce 回收） → volume_boundary（interrupt 串行点，问用户） → 下一卷
```
Spike ③ 实测：卷内全部章并行写完 → 卷边界 interrupt 暂停（next=('volume_boundary',)）→ `Command(resume="y")` 续跑下一卷——语义精确符合设计。

**失败恢复策略树**（设计 §2.3-4 +  验收）：
```
章级失败 → 重试 N 次（默认 2） → 标记 failed 继续（章级只报告，进度落库）
卷级失败 → interrupt 用户决定 或 授权主 agent 决定（supervisor 补救）
```

**卷内承接两阶段（并行下保承接）**

卷内并行扇出（`Send`）是为提速刻意设计，但**各章互不知情**——无承接、无因果、无「上一章结尾的悬念」。修订方向是**在并行下保证承接**（**不取消并行**，方案 A 未采纳）：

```
START → bootstrap → prepare_continuity（B：写前定承接表，一次 LLM 调用/卷）
      → volume_fan_out（Send 扇出，payload 带本章 carry/hook）
        → write_chapter（并行；brief 注入【上一章结尾】/【本章结尾钩子】）
      → join → volume_audit（C：逐章 F34 审计 + 阻断判定）→ volume_boundary
```

**B 阶段 `prepare_continuity`（写前定「承接点 + 章末钩子」）**：

- **位置**：`volume_fan_out` **之前**。此位置是硬要求——扇出后各分支同时启动，任何一条都拿不到前章**正文**；因此承接信息必须**只依赖大纲面**（卷纲 + 各章章纲 + 前一章章纲），在扇出前一次性确定。
- **成本**：**一次 LLM 调用生成整卷承接表**（非每章一次）——30 章卷 30 次调用不可接受。
- **产出与通道**：`VolumeState["continuity"]: dict[str, dict]`，键 = `str(outline_id)`，值 = `{"carry": 本章开头应承接什么, "hook": 本章结尾应留下什么}`。卷推进（`_goto_next_volume`）时清空重算（**不进下一卷**——否则跨卷串味）。
- **注入**：`Send` payload 携带本章 carry/hook → `_delegate_chapter` 追加承接段进 `system_prompt`（**复用既有 `_build_chapter_brief` / `resolve_brief_setting` 通道**，不新造注入路径）。**隔离性**：章 A 的 brief 只含章 A 的承接，绝不串入他章。
- **降级**：LLM 调用失败 / JSON 解析失败 → 空承接表（brief 不注入），**不阻断写作**（宁缺毋滥：无据可依时不做伪承接）。
- **缺卷纲**：降级为「仅前后章纲」（章纲恒在），承接仍可生成。

**C 阶段 `volume_audit`（写后卷级审计，复用 F34）**：

- **位置**：`join` **之后**、`volume_boundary` **之前**。`write_chapter → join` 直连**保持不动**（既有拓扑契约不受影响）。
- **实现**：逐章委派 **F34 `ChapterAuditService.audit(project_id, chapter_id)`**（**不新造审计实现**）——重点复用 补的两类 `check_type`：**前后章连贯性**（`cross_chapter`，正是本 issue 诉求）+ **大纲符合度**（`outline_compliance`）。failed 章跳过（无正文可审）。
- **阻断判定**：经 `_audit_bridge.report_to_audit_dict` 扁平化 → `blocking_update`（**复用 唯一口径**：`severity == error` 且 `degraded == false` 才阻断；`warning`/`info` 不阻断，`degraded` 告警不阻断——「没审出来 ≠ 审出问题」）。
- **阻断后果**：不进入 `volume_boundary`，`VolumeState["audit_blocked"]` 写入原因 + `status="blocked"`（**复用 已登记的阻断终态**），已完成产出保留。
- **向后兼容**：`audit_service` 未装配（`None`）→ 节点透传至 `volume_boundary`，行为与改造前逐字一致。审计异常 → 吞掉 + warning，不阻断编排。
- **节点内不加 `interrupt`**：审计是纯计算；章执行分支内 interrupt 是 Spike ④ 硬约束（resume 语义歧义），本阶段同样不引入。

**单章轨（F49）不在本修订范围**：F49 书级轨是串行路由、无并行互不知情问题（其零前文问题属 另一轨迹）。

**F29 护栏复用**：步数/连续调用/fallback 护栏（`SupervisorExecuteConfig.max_steps/max_consecutive/fallback_on_error`），步数上限随计划缩放（`max_agent_calls` 按计划章数换算，防长书超步）。

**GUI 交互设计**：
- **卷级 HITL 确认对话框**：`GET /runs/{run_id}` 状态=waiting_hitl 时弹出确认对话框（approve/reject 按钮 + decision 文本输入，镜像 CLI `book confirm` 语义）→ `POST /runs/{run_id}/confirm`；非 waiting_hitl 不显示（对齐 422 防呆语义）
- **卷内并行进度**：卷内章并行执行在观察流仪表密度聚合展示（章级徽标批量推进，不做动画滚动）
- 状态：interrupt 暂停点由后端驱动（next checkpoint 提示「卷 2」等），GUI 只消费 `confirm` 端点

### 5.4 阶段 4：AsyncSqliteSaver + 跨重启 resume + 干预 API

**checkpointer 持久化**（Spike ⑤ 已证实）：InMemorySaver → **AsyncSqliteSaver**（`langgraph-checkpoint-sqlite`，Spike 临时装入实测 v3.1.1 可用）——**独立 SQLite 文件**（`AsyncSqliteSaver.from_conn_string()`），不与业务表挤同一 WAL 连接。**pyproject 新增依赖**（§11）。

**thread_id 落库**（Spike ⑥ +）：每书级运行一个 thread_id，落 `agent_executions.thread_id` 列（§2.3）——书级运行 ↔ 图 checkpoint 一一映射；同 thread_id 续跑、不同 thread_id 全新 run（Spike ⑥ 实证）。

**跨重启续跑**（Spike ⑦ 已证实， 验收前置）：章边界续跑（不做章内断点）；resume 时 `Command(update={...})` **重注入 llm_client**——F29 模式复用（`supervisor_pipeline.py` L45-47 实证：`llm_client: Annotated[LLMClientProtocol, UntrackedValue(LLMClientProtocol)]` 不参与 checkpointer 序列化，resume 时注入）。杀进程 → 重启 → resume → 无重复内容（安全阀兜底）。

**干预 API**（粒度=卷级锚点 + 章级被动动作，Q3=A 已拍板 ✅ v1.1，§12 D12）：`POST /runs/{run_id}/intervene`——pause（后台任务挂起，卷边界 checkpoint 已存）/ resume（等价 Command(resume)）/ redirect（跳过章/改序）/ edit（改章 brief，difflib 差异标注）。FastAPI 后台任务承载运行（`BackgroundTasks` 或独立 task 管理，运行中用户可做别的）。

**回归摘要 + 结构化运行日志**（设计 §2.6-3）：`GET /runs/{run_id}/summary`——到哪了/接下来/已耗一页说清；`steps` JSON 快照（镜像 F27 AgentStep 序列）可回放复盘导出（`inkflow book summary --export`）。

**GUI 交互设计**：
- **干预控件**：运行工具栏 pause/resume 按钮 + 章行内 redirect（跳过/重试/标记 failed）+ 章 brief 编辑（edit）→ `POST /runs/{run_id}/intervene`；干预响应 `diff` 字段高亮展示（edit 前后差异，difflib 字面 diff）；已完成章干预控件禁用（422 语义防呆）
- **回归摘要面板**：`GET /runs/{run_id}/summary` 渲染（到哪了/接下来/已耗一页说清 + 结构化运行日志回放/导出按钮，镜像 CLI `--export`）
- **观察流三层密度切换**：表演（trace 全文）/仪表（章状态+计数）/无声（仅进度树）三档切换 → `density` 查询参数（§3.4 GUI 对接注）
- **克制原则（ui-design-taste）**：安静纸张感（暖白背景非纯白）、动效 ≤200ms 仅状态变化、SSE 流式是唯一「动态感」来源、写作页核心区域信息密度最低档（面板可折叠/默认收起）

### 5.5 完成态判据与失败原因可见

> 背景：（PR）修复「key 缺失静默空值」路径后，**凭据存在但无效**（key 吊销 / provider 故障 / ollama daemon 未运行）时残留同形态假绿——`resolve_llm_credentials` 只验「有没有 key」不验「能不能用」，装配成功后章委托运行期抛错 → 全章 `progress=failed`、`tokens_used=0`、顶层 `status=completed`。book run 为 fire-and-forget 后台任务，用户只能靠轮询 status 发现，status 又不含失败原因，定位成本极高。

**完成态判据（三轨统一）**：一切「欲设 completed」的收尾点（`write_book` 章循环结束 / `write_book_volume` execute 正常返回 / `confirm_run`、`resume_run` result.status=completed / `write_book_agentic` result.status=completed）改为按**章级事实**派生：

| 章级事实 | run 终态 |
|---|---|
| 任一章 `needs_review`（审计阻断待人工介入，） | `blocked`（**新增终态**：审计阻断，优先级最高） |
| failed 章 > 0 且 done 章 == 0 | `failed` |
| failed 章 > 0 且 done 章 > 0 | `degraded`（新增终态：部分成功） |
| failed 章 == 0 | `completed` |

`aborted` / `waiting_hitl` 既有语义不变（护栏中止/ HITL 暂停不重新派生）。无章快路径（`prepare_run` 无目标章）不派生，维持 completed。

**审计阻断终态 `blocked`**。审计结论成为写作链门禁——阻断级 finding（`severity == "error"`，唯一口径 `_audit_bridge.BLOCKING_SEVERITY`）出现即停止后续章节（不静默继续），已完成产出保留。判定与消费点：

- **判定唯一实现点**：`_audit_bridge.audit_blocks_writing` / `inspect_audit_conclusion`（全自动轨与交互式轨共用，禁各自另立阈值）；`warning`/`info` **不**阻断。
- **全自动轨（`book_agentic_pipeline`）**：`_audit_chapter` 审计后写 `audit_blocked={outline_id: 原因}` + `status="blocked"`；闸门置于**决策之前**（阻断后连决策请求都不再发，确定性停止，不依赖模型自觉），**`_fallback_node` 兜底路径同受闸**（否则「决策重试耗尽 → fallback」会绕过阻断把后续章写满）；`_finalize_audit_block` 收尾把被阻断章 `progress[oid] = "needs_review"` 并写 `progress_reason`。
- **优雅停止语义（非抛异常中断）**：已完成章的 `progress`/`results`/`execution_refs` 全部保留，仅被阻断章标记 `needs_review`——「停止后续章节但不丢弃已完成产出」。
- **交互式轨**：复用既有 `audit_logs.status="pending"` → `confirm(accept|reject)` 状态机（不另造路径），审计出阻断级 finding 时停在 pending 等用户决定，不自动 accepted。
- **`degraded` 例外（硬性）**：审计 `degraded=true`（LLM 审计失败降级）**不阻断**但须**告警**——「没审出来 ≠ 审出问题」；`inspect_audit_conclusion` 以 `verdict` 三态（`blocked`/`degraded`/`passed`）显式区分「审了且过」vs「没审成」，**不得把 degraded 当通过**。

**章级事实权威源（按轨）**：静态轨 = `plan.progress`（服务层自持）；volume/agentic 轨 = 收尾时 `volume_pipeline/agentic_pipeline.get_checkpoint_state(thread_id)["results"]`（`{outline_id: execution_id | "failed"}`）同步回 `plan.progress` 后派生；pipeline 鸭子无 `get_checkpoint_state`（阶段 3 旧测试形态）→ 跳过派生维持原状态（防御分支，向后兼容守护）。收尾读取必须是 resume/execute 动作完成后的**重读（fresh read）**：`confirm_run` / `resume_run` 动作前的那次读取仅用于 `__interrupt__` 判定，**不得复用为事实源**——动作前快照不含续跑段章事实，复用即 假绿残留（独立评审 MAJOR 发现）。resume_run 单测的 checkpoint 读取次数契约相应放宽为「至少一次含动作后重读」。

**失败原因可见（验收 2 落定）**：`WritingPlan` 新增顶层字段 `progress_reason: str | None`（ORM String(2000) nullable + `ensure_writing_plan_progress_reason_column` 幂等迁移，镜像 `hitl_payload` 先例）。收尾派生为 failed/degraded 时写入摘要（≤2000 截断）：静态轨 = 每章「outline_id: 异常类名: 消息」行（委托失败即时采集，单前缀不重复）；volume/agentic 轨 = failed 章列表 + 「凭据无效或运行时错误，详见章执行日志」提示。`GET /runs/{run_id}` 与 `GET /runs/{run_id}/summary` 响应新增顶层键 `progress_reason`，**仅 `failed`/`degraded`/`blocked`态透出**（其余状态按状态门控返回 null，中间态不显示陈旧值）；`mark_failed`（整单异常兜底，无章级原因语义）清空该字段——防跨态泄漏。

**同类异常短路剩余章（裁定：不做）**：原因可见后用户可经 `intervene redirect` 处置；「连续 N 章同型异常即中止」有误伤风险（provider 瞬时抖动 + 章级重试已兜），且后台任务强杀语义未定。留待真实使用反馈再起。

**GUI/CLI**：CLI `book status` 与 GUI `runStatus` 徽标为字符串透传，`degraded`/`failed` 自动呈现（轮询停止条件为非 running/pending，无需改）。（degraded 专属样式见下）。

**GUI 状态档位色 + 失败原因可见**：`BookRunPanel` 运行状态徽标由「固定灰底字符串透传」升级为**语义档位色**——文本仍原文透传（`completed`/`failed`/`degraded`/…），徽标按状态映射低饱和语义类（对齐 `ui-design-taste` 克制原则，色源 = 主题 token `ok`/`warn`/`err`，随三主题切换）：

| runStatus | 徽标语义类 | 色档 |
|---|---|---|
| `completed` | `run-badge-completed` | 绿（ok/10 底 · ok 字） |
| `failed` | `run-badge-failed` | 红（err/10 底 · err 字） |
| `degraded` | `run-badge-degraded` | 橙黄（warn/10 底 · warn 字，部分成功警示档） |
| `blocked` | `run-badge-blocked` | 橙红（warn/10 底 · err 字，审计阻断待人工介入档） |
| 其余（running/pending/paused/waiting_hitl/aborted） | 无 `run-badge-*` 钩子 | 中性（surface-3 底 · ink 字），维持现状 |

`progress_reason` 渲染：前端 `RunStatusResponse` 类型 + `book` store 新增 `progressReason: string \| null`（`loadRunStatus` 透传 `res.progress_reason ?? null`，`reset` 清零）；面板在 `(runStatus 为 failed/degraded/blocked) 且 progressReason 非空` 时渲染「失败原因」块（`run-progress-reason`：标签 `book.run.reason` + 理由文本，含 outline_id 定位锚点；后端已按状态门控，前端双保险）；理由 >200 字符默认 `line-clamp-3` 三行截断 + 展开/收起按钮（镜像记忆页 `SummaryCard` 先例）。i18n：`book.run.reason` / `book.run.reason.expand` / `book.run.reason.collapse`（zh/en 对称）。契约：`BookRunPanel.test.tsx`+ `stores/book.test.ts`（progressReason 透传/reset）。简图原型 + 高保真：`design/GUI/book/book-run.html` 与 `book-run-<state>.png`（五档：running/completed/failed/degraded/degraded-expanded）。

```text
┌ 书级运行面板（BookRunPanel）──────────────────────────────┐
│ 运行状态  [ degraded ]        ← 橙黄档位徽标（文本透传） │
│ ⚠ 失败原因                                  ← 仅警示档  │
│   o-ch12: RuntimeError: LLM provider 调用失败（…）       │
│   o-ch13: ConnectionError: ollama daemon 未响应（…）     │
│   o-ch14: RuntimeError: 上下文超限，章纲超 12k tokens …  │
│   ▸ 展开                                                │
│ [表演][仪表][无声][回归摘要]                             │
│ 已写章节: 12 / 15 · Agent 调用: 34/60 · Token 182k/400k │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░ 80%  [trace 行徽标 badge-* 五态]  │
└──────────────────────────────────────────────────────────┘
```

**契约翻转**：`test_write_book_chapter_failure_marks_failed_continues`（部分失败旧期望 completed）按本节翻转为 `degraded`——先对齐 spec 再动（本节即对齐依据）。

### 5.6 token 用量采集（卷轨 / agentic 轨）

> 背景：（PR）修复期间明确搁置项——卷轨/agentic 轨委托成功后丢弃 `usage_metadata`（`_delegate_chapter`/`_delegate_write` 只取正文落 Draft），checkpoint state 无逐章 usage 通道，服务层收尾「token 记账不动」→ `counters.tokens_used` 对两轨恒 0、`max_tokens` 软护栏对两轨失效（仅 `max_agent_calls`/`max_chapters` 在守）。**禁止用估算常数替代真实 usage**。

**usage 事件通道（图内，volume/agentic 两轨对称）**：`VolumeState`/`BookAgenticState` 新增 `usage: Annotated[list[dict], operator.add]`（reducer 只增通道，对齐 §6 R5；checkpoint 持久化 → 跨 HITL resume/跨重启续跑不丢不重，LangGraph 已完成节点不重放）。事件 schema：`{"source": "write"|"audit"|"decision"|"supervisor", "chapter": "<outline_id 或 ''>", "prompt_tokens": int, "completion_tokens": int, "total_tokens": int}`——**每成功 LLM 调用恰一事件，取自真实响应载体**（agent.invoke 结果 messages 的 `usage_metadata`（input/output/total 键族 + prompt/completion 别名回退，顶层 `result["usage"]` legacy 回退）/ llm.chat 响应的 `token_usage`（`usage_metadata` 回退））；失败/异常/解析失败 attempt、非 LLM 路径（continue/abort 分支、mark_done）**零事件**（防伪计费）。采集面全覆盖：write 委托（含 revise/fallback 内 write）、audit 委托、agentic supervisor 决策 chat（可解析响应才计）、volume 卷级失败 `decision="supervisor"` 补救 chat。

**服务层同步（`plan.limits`，两轨）**：提取 helper 收敛 `domain/services/usage_accounting.py`（纯函数：`result_usage`/`chat_response_usage` 三元组 + `extract_total_tokens` 总视图；book_service re-export `_extract_usage_tokens` 兼容）。`_finalize_from_state`（facts 非 None 分支）与 waiting_hitl 落库点（`write_book_volume`/`confirm_run`/`resume_run` 的 `except VolumeHITLInterrupt` → `_sync_usage_from_state` 读 checkpoint）将事件列表**求和覆盖**写 `plan.limits["tokens_used"/"prompt_tokens"/"completion_tokens"]`（覆盖=幂等：收尾链后一次覆盖吞并前次值，绝不翻倍）。软护栏语义不变：`total > max_tokens → tokens_warning=True` 仅告警不终止；硬护栏零变化。旧 checkpoint 无 usage 键/空列表 → 三键不写（向后兼容守护）；计数在 waiting_hitl 窗口经落库点同步，GUI/CLI 可见。

**counters 扩展**：`_build_counters` 7 键 → **9 键**（新增 `prompt_tokens`/`completion_tokens`，读 `plan.limits.get(key, 0)`）；API/GUI 透传零破坏（dict passthrough）。static 轨 `_delegate_chapter` 同步分列累计三值（原仅 total）。

**验证锚点**：三轨各跑一本书（卷轨含跨卷 HITL resume + 跨重启 resume_run），`counters.tokens_used > 0` ≈ 真实用量、无重复计费、`tokens_warning` 三轨一致可触发。

### 5.7 写作凭据「项目感知 + per-delegate」解析

> 背景：rc2 旅程实测「开始写作」主路径全章 failed、tokens=0。终裁探针实证的根因链中 book 轨独占一环（R3）：`_build_book_service` **装配期一次性** `resolve_llm_credentials(config.llm_default_model)` 并闭包捕获——项目 `config.model` 已配置从未参与解析；全局默认为空时旧 resolver 遍历注册表取 `models[0]`（不筛 type）把 zhipu `embedding-3` 装成 chat 模型 → 运行期 400（R1 全局面，见 ADR-049）。

**凭据解析下沉到委托时机（R3 修复）**：
- `_build_book_service` 装配期**零解析**（删除顶层 resolve 与闭包捕获）；
- `_writer_factory` **每次委托**读目标项目配置（`_project_config_getter(expected_project_id)`，getter 不可用/项目不存在 → project_model=None 降级）→ `resolve_llm_credentials(config.llm_default_model, project_model=…)`——多项目并发 run 各章天然使用所属项目模型；
- `POST /runs`（`start_run`）入口**无条件预检**：同链解析（plan 缺失 → project_model=None 继续），无解 → **422 先于 404/状态变更**（fail-fast 零残留，保 契约 3「422 不启动后台」语义）。

**422 语义升级（承接）**： 验「有没有 key」； 之后 实证还须验「装配的是不是可用 chat 模型」与「模型从哪来」——预检 + per-delegate 双点使凭据错误在入口可见（progress_reason 通道沿用 §5.5，运行期异常兜底不变）。

**测试锚**：`backend/tests/unit/api/routers/test_book_run_929.py`（R1-R4 + G1：装配期零解析 / 委托收到 project_model kw / 真实 getter 透传项目模型 / 预检先于 prepare）。

### 5.8 `book run --force` 显式覆盖正文与旧稿备份落点

> 与 `reset`（只清**执行态**、不删正文）的关系：`reset` 之后若正文仍在，安全阀依旧拦截，用户只能自己删正文。本方案是它的**补充出口**——「**显式**跳过安全阀 + **覆盖**正文 + 旧稿可恢复」的第三条路。⚠️ 会**主动写 `chapters.content`**，覆盖即数据丢失 → 备份是硬要求。

**旧稿落点（方案 A2）**：`chapters` 新增 `previous_content`（`Text`，nullable），**不新造表**（抄 `outline_service` 的 `extra["replace_snapshot"]` 快照先例 + 仓库既有 `LenientJSON` 列先例）。未选方案备案：

| 方案 | 旧稿落点 | 未选原因（可推翻，若要推翻请新开 issue） |
|---|---|---|
| A1 | `drafts` 表（`Draft.chapter_id`=该章，`status=draft`） | 🔴 **代码级语义冲突**：`draft_service.confirm()` 取 `target = draft.chapter_id or chapter_id`（`domain/services/draft_service.py:219`）⇒ 确认「备份草稿」会把**旧文写回该章、静默回退新正文**；若为规避把 `chapter_id` 留空，备份草稿就成了**无章节锚点的裸草稿**（口径见 `POST /agent/drafts/prune-orphans`—— 起该判据按**所属项目**判孤儿，项目健在的备份草稿不在清理面；但「无锚点裸草稿」本身即 A1 不可靠的根因）⇒ 备份不可信 |
| A3 | 不落旧稿，覆盖前显式提示 + 二次确认 | 一次误点旧稿永久消失（不可恢复）；A2 的「上一稿快照」是通用能力，后续任何覆盖/重写入口都可复用 |

> 另已排除：`DataChangeEvent`（审计/SSE 变更流）**不含正文载荷**，不能当备份源。

**快照规则（写路径，`ChapterService.update_chapter`）**：落实新正文**之前**，若「归一后的新正文 ≠ 库中旧正文」且「旧正文非空白」→ 把**库中旧正文**（`existing.content`，逐字）写进 `previous_content`。

- 旧正文为空白（`""` / 纯空白）→ **不写空壳**：`previous_content` 保持原值（「有正文」判据与安全阀 `content_checker` 同口径：`.strip()` 后非空）
- 只改标题 / 正文值未变（幂等写）→ **不产生快照**（无内容丢失，备份无意义）
- 连续覆盖 → `previous_content` 恒为**紧邻上一版**（不是首版）
- 该规则是 `update_chapter` 的**唯一收口**（GUI 手编正文 / 草稿 confirm / book 轨审计落章 `_audit_bridge.persist_chapter_body` 全部经此路径），故无需把 `force` 位透传到写路径深处

**恢复读口**：`POST /chapters/{chapter_id}/restore-previous` → `ChapterService.restore_previous_content(chapter_id)`

- 把 `previous_content` 写回 `content`；**恢复动作自身也遵守同一覆盖口径**（旧稿是被新正文覆盖掉的，恢复同样先落一次快照）⇒ 结果是 `content` ⇄ `previous_content` 的**双向切换**，可再恢复回去
- `previous_content` 为空白 → **409**「无可恢复的旧稿」（不静默 200）；章不存在 → **404**
- GUI 入口另开单（本增量只交付 API + CLI 读侧可见）

**请求面：双条件（`force` + `confirm_overwrite`）**

- `POST /runs` body 新增 `force: bool = False` / `confirm_overwrite: bool = False`；**两者必须成对**，只给其一 → `ValueError`「force 与 confirm_overwrite 必须同时提供」→ **422**。目的：防止任何自动化链路**静默**带上 force（覆盖正文 = 数据丢失，必须有人显式二次确认）。
- **force 只做显式跳过**：`force=True + confirm_overwrite=True` 时跳过「内容已写」安全阀；🔴 **安全阀判据本身零改动** —— 否则 `reset` 的语义解释会跟着漂移（reset 之所以安全，正因「正文还在 ⇒ 闸门仍拦」）。`force=False` 路径行为与调用面**逐字不变**。
- **force 必须到达后台执行体**：`prepare_run` 只预检 + 落 `running`，真正写正文的是后台任务里的 `write_book` / `write_book_volume` / `write_book_agentic` —— 三者都吃 `force`（否则 force 只跳过入口预检，后台写正文时仍撞阀 → 特性等于没做）。
- **后台执行体的 session 归属**：`POST /runs` 的后台执行体在**请求 session** 上运行（`Depends(get_db)`）——请求结束会话关闭后任务仍触库会重新 checkout 连接且不归还（连接泄漏，GC 打印 `non-checked-in connection` 告警）；故经 `run_with_session_release(coro, db)` 包装，任务结束（**含异常**）显式 `close()` 归还连接（幂等）。行为 / 端点零变化。
- **备份落点随响应可见**（硬约束「不做静默备份」）：force 成功（202）时响应体带

  ```jsonc
  { "run_id": "uuid", "status": "running",
    "overwrite": { "forced": true,
                   "backup_target": "chapters.previous_content",   // 去哪找回
                   "chapters_to_backup": 2 } }                     // 待备份章数（= 目标章中当前已有正文的章数；0 = 无旧稿可备）
  ```

- **CLI**：`inkflow book run <plan_id> --force --confirm-overwrite`（只透传、不做本地判定 —— 双条件是服务层不变量）；不带 flag 时 body 逐字不变；响应含 `overwrite` 时人类输出点明备份列与章数。

**reset（B）语义不变**：B 继续不动正文；A 是 B 的补充出口而非替代。

**测试锚**：迁移四形态 `backend/tests/unit/infrastructure/database/test_chapters_previous_content_migration_1430.py`；快照 + 恢复 `backend/tests/unit/domain/services/test_chapter_previous_content_1430.py`；双条件 + 后台透传 `backend/tests/unit/domain/services/test_book_run_force_1430.py` + `tests/api/test_book_force_overwrite_1430.py`；恢复读口 `tests/api/test_chapter_restore_previous_1430.py`；CLI `tests/cli/test_cli_book_force_1430.py`。

### 5.9 supervisor 任务清单（落库 + 供决策）

> **范围定性**：不造「LLM 预产出清单」这一第二套来源；清单 = **book-level supervisor 的产出**。三点实现结论见 §12 D15。

**本质：产出 vs 记录，不是两套决策源。** supervisor（`BookAgenticPipeline._supervisor_node`）本就逐步决策 `{action, op, outline_id}`；本增量把这些**被接受的决策**累积成一份**结构化清单**并持久化——**清单不覆盖也不约束** supervisor 的决策。

- **产出**：每条被接受的决策 → `tasklist` 追加一条 `{op, outline_id, title}`（`title` = 目标章名，取不到 → `outline_id`；`op="finish_book"` 条目 `outline_id=""`）。
- **降级留痕（schema 校验失败）**：决策 4 次重试耗尽（`_decide_next_action` 返回 `("", "", "")`）→ 追加 `{op: "__degraded__", reason: "decision_invalid"}`，随后走**既有** `fallback_on_error` 分支（默认 → deterministic fallback；`False` → abort）——**不崩、记降级、可继续**。
- **持久化**：运行收尾（`execute` / `resume` 的返回路径，**含抛 `BookAgenticHITLInterrupt` 之前**）把 checkpoint state 的 `tasklist` 写回 `plan.tasklist`（就在共享 `plan` 引用上写，由 `BookService.write_book_agentic` 的 `update_writing_plan` 落库；沿用 `_finalize_audit_block` 先例）。
- **读回**：`execute` 启动时以 `plan.tasklist` **播种**初始 state → 下一次运行 / resume 的决策消息里带上「上次清单」段（**提示上下文**）→ 「清单可被后续决策读回」。
- **非约束**：`_guarded_route` 与 `_build_decision_messages` 的**既有约束语义零改动**——清单只是上下文，supervisor 仍可跳过 / 改序（负例见 §9.2 场景 14）。
- **权威源单向**：`progress` 只由操作节点写（write/audit/revise/mark_done）；`tasklist` 只由 supervisor 决策写 → 每字段单一 writer，**构造上零双写漂移**（§12 D15）。
- **GUI 读口**：`get_summary` 新增附加键 `tasklist`（复用 tasklist 条目；**`steps` 逐字不变**）→ 「计划（tasklist）vs 实际（`steps[].status`）」。
- **代码落点**：纯函数工具箱下沉到新模块 `infrastructure/agent/book_agentic_tasklist.py`（`book_agentic_pipeline.py` 已达 891 行、`book_service.py` 888 行，**贴 900 行护栏**；镜像 `book_agentic_helpers.py`  体积治理先例）。

**测试锚**：`backend/tests/unit/infrastructure/agent/test_book_agentic_tasklist_1439.py`（产出/持久化/回读/降级/非约束）+ `backend/tests/unit/domain/services/test_book_tasklist_summary_1439.py`（`get_summary.tasklist` + `steps` 契约不变）+ `backend/tests/unit/infrastructure/database/test_writing_plan_tasklist_migration_1439.py`（迁移三形态）。

## 6. 组织规则

编排域专属约定（各阶段实现共享，避免每阶段重复设计）：

| # | 规则 | 说明 |
|---|------|------|
| R1 | **planner 产出直写既有实体** | outline/character 落库经既有 service（`outline_service`/`character_service`），不绕过业务校验；撞唯一索引（项目内 outline 名唯一）→ 服务层捕获 IntegrityError 转 409（§3.5），planner 自动改生成名重试 1 次 |
| R2 | **进度权威 = WritingPlan.progress** | 章级状态以 WritingPlan 快照为权威（outline 表只存结构，不存执行状态）；进度变更每次落库（章级只报告但状态必须落盘） |
| R3 | **「内容已写」检查先于一切执行** | 安全阀（§5.2）在 `create_execution` 之前、任何子 agent 调用之前；误判宁可拒绝不可重跑（防双倍费用优先） |
| R4 | **interrupt 只放卷边界** | 全编排图唯一允许 interrupt 的位置 = 卷边界串行点（Spike ④ 硬约束实证）；章执行节点/并行分支内**禁 interrupt** |
| R5 | **并行聚合走 reducer** | 任何并行写通道必须 `Annotated[..., operator.or_]` 或等价 reducer（Spike ②）；禁止普通 dict 通道承载并行写 |
| R6 | **上限「至少一道有限护栏」** | 启动前校验（§2.4）；计数器先于执行立起来（阶段 1 写死值也算有限护栏） |
| R7 | **委托契约固定形态** | 章 brief 构造 → build_agentic_writer → save_draft 回收 → Draft 落库 → 进度更新；每章一次 save_draft（幂等写） |
| R8 | **恢复策略树固定** | 章级失败 → 重试 N 次 → failed 继续；卷级失败 → interrupt 用户决定/授权主 agent（§5.3） |
| R9 | **llm_client 不序列化** | 编排图状态中 llm_client 用 `UntrackedValue` 标注（F29 模式），跨重启 resume 时 `Command(update={...})` 重注入（§5.4） |
| R10 | **干预效果可见** | 任何干预（redirect/edit）响应带 `diff` 字段（difflib 字面 diff，零 LLM） |
| R11 | **访谈 LLM 动态提问护栏** | ① 通用必答项（题材/篇幅/主题）服务端强约束——LLM 输出校验缺失必答项 → 拒绝/补问（防漏问）；② 已确定项（confirmed_items）为唯一提问去重依据——只问未确定项；③ 冲突/不合理必须回问（conflicts 记录 + kind=conflict 问题），不允许静默采纳；④ LLM 失败降级到确定性常量（ROUND1/ROUND2 兜底），访谈不阻塞 |

## 7. 边界情况与错误处理

| # | 场景 | 行为 | 归属阶段 |
|---|------|------|----------|
| 1 | 用户拒访谈（「全部你决定」） | 访谈 completed（declined）→ 直接跑 F42 write_auto，WritingPlan 状态=auto | 1 |
| 2 | 访谈轮次超上限 | `max_sessions` 硬护栏 → 自动完成（已获信息 + 其余自定授权） | 1 |
| 3 | planner 生成大纲撞名 | 服务层捕获唯一索引 IntegrityError → 改生成名重试 1 次 → 仍撞 409 | 1 |
| 4 | 该章已有内容/执行已完成 | 「内容已写」安全阀 → 409 拒绝重跑（不创建 execution） | 2 |
| 5 | 上限全部无限制 | `validate_at_least_one_hard_limit` → 422 拒绝启动 | 2 |
| 6 | token 软上限超限 | 告警（trace 记录），不强制终止；硬护栏（章数/调用数）超限 → 终止 + 进度落库 | 2 |
| 7 | 章级执行失败 | 重试 N 次（默认 2）→ 仍失败 → 标记 failed 继续下一章（章级只报告） | 3 |
| 8 | 卷级失败（卷中断言失败/不可恢复） | interrupt 暂停 → 用户决定（继续/跳过/中止）或授权主 agent 补救（supervisor） | 3 |
| 9 | Send 分支内 interrupt（误用） | 不提供该用法（§6 R4）；如实现引入 → 测试断言禁止（Spike ④ 教训） | 3 |
| 10 | 进程被杀/断电 | 阶段 4：AsyncSqliteSaver 已落卷边界 checkpoint → 重启后 resume 续跑（章边界），安全阀防重复内容 | 4 |
| 11 | resume 时 llm_client 丢失 | F29 模式：UntrackedValue 不序列化 → resume 时 Command(update) 重注入，缺失则 422 提示重新注入 | 4 |
| 12 | 干预目标不存在/非法动作 | 422（§3.5）；干预不改变已完成章（progress=done 拒绝 redirect/edit） | 4 |
| 13 | 并行执行中 pause | 卷边界 checkpoint 已存，pause 挂起后台任务；并行分支进行中的章允许完成（不做章内断点） | 4 |
| 14 | 书级运行与业务表同 WAL 冲突 | 禁止：checkpoint 独立 SQLite 文件（Spike ⑤），业务库连接不受影响 | 4 |
| 15 | LLM 动态提问失败/超时 | 重试 1 次 → 仍失败 → 回退 ROUND1/ROUND2 确定性常量→ 访谈不阻塞；LLM 恢复后下轮回到动态提问 | 1 |
| 16 | 回答与已确定项/设定冲突或不合理 | conflicts 记录（resolution=pending）+ 生成 kind=conflict 回问题请用户重新确认；用户新回答 resolve 后继续（不得静默采纳冲突值，§6 R11） | 1 |
| 17 | 末尾总体确认被用户修改 | confirming=true 时用户提交修改项 → 回 questioning 重问该确定项（新值进 confirmed_items，旧值留痕 conflicts 或覆盖并记录历史）→ 重新确认 | 1 |
| 18 | 完成路径总纲/主角已存在 | 按名查重 → **复用**既有实体（不新建、不改名）；并发窗口撞名 → 二次查名复用；仍取不到 → 领域异常经 API 映射 422 + 可读 detail（**不得**静默吞、不得 500 无详情、不得静默跳过创建） | 1 |
| 19 | 仅配项目级模型（全局默认为空） | `resolve_model(None, 项目 config.model, 全局)` 取项目级 → 访谈走 LLM 动态提问（**不得**因 repo 入参契约违规而静默降级模板题库）；真无任何模型 → 保留模板题库降级（恰好一次 WARN）；非契约类失败（DB 抖动）→ 回退全局默认（零 WARN） | 1 |

## 9. 测试策略

### 9.1 层次（镜像既有三层 + LLM 依赖开关）

| 层 | 文件 | 覆盖 | 命令 |
|----|------|------|------|
| 单元 | `backend/tests/unit/domain/models/test_writing_plan_model.py` / `test_book_service.py` / `test_planner_service.py` | 模型校验、上限校验（至少一道护栏）、进度状态机、安全阀判定（纯逻辑，mock 仓储）、访谈循环（mock LLM） | `pytest tests/unit/` |
| 集成 | `tests/integration/test_book_repository.py` | WritingPlan/PlannerSession 仓储（in-memory SQLite）、thread_id 落库、confirmed_items/conflicts JSON 列读写 | 顶层集成 job |
| API | `tests/api/test_books_api.py` | 端点契约：planner 启谈/回复/confirm/auto（LLM mock）、runs 启动/状态、confirm、intervene、summary、异常映射（404/409/422） | integration-agent-backend 链登记 |
| 单元 | `backend/tests/unit/domain/services/test_planner_service_1462_1463.py` / `test_repo_id_contract_1462.py` / `backend/tests/unit/api/routers/test_books_planner_conflict_1463.py` | 项目级模型解析（契约违规冒泡 + 可预期降级两向 + 真无模型降级）、完成路径幂等（总纲/主角 × 两条调用路径 × 并发窗口 × 无从复用响亮失败）、同族 `.int` 漏网静态回归锁、领域冲突 → 422 | `pytest tests/unit/` |
| API | `tests/api/test_books_planner_project_model_1462.py` | 仅配项目级模型（全局为空）下 book plan 全链路（真实 SQLite repo + 假 LLM）：LLM 动态提问 → `confirming=true` → confirm 200；同项目同 one_liner 第二次访谈同样成功 | integration-agent-backend 链登记 |
| 单元 | `backend/tests/unit/infrastructure/agent/test_book_agentic_tasklist_1439.py` / `backend/tests/unit/domain/services/test_book_tasklist_summary_1439.py` / `backend/tests/unit/infrastructure/database/test_writing_plan_tasklist_migration_1439.py` | supervisor 清单产出 + 持久化回读（下一次运行播种）+ 降级条目 + 非约束（清单不覆盖决策）+ `get_summary.tasklist` 且 `steps` 逐字不变 + 迁移三形态 | `pytest tests/unit/` |
| CLI | `tests/cli/test_book_cmd.py` | `inkflow book` 命令组（CliRunner + 临时 SQLite，isolated_db 双 patch 模式） | integration-cli-backend 链登记 |
| E2E | `tests/e2e/test_book_long_run.py` | 长任务端到端：真实 LLM 走 **e2e-ai-backend 开关模式**（CI 默认 skip，本地 `INKFLOW_E2E_LLM_*` env 真实 API；LLM 依赖测试不放默认 CI 链，F39 实证） | `pytest tests/e2e/` + env |
| 前端组件（Vitest） | `frontend/packages/renderer/src/components/__tests__/book*.test.tsx` | 访谈对话流、子 agent 展开行、章级进度 UI、HITL 确认对话框、干预控件、三层密度切换、回归摘要面板（mock API，F43 前端测试模式） | `pnpm test`（→ `pnpm --filter renderer test` → `vitest run`，frontend CI job） |

### 9.2 关键测试场景（每阶段 RED 契约锚点）

1. **安全阀**：章已有内容 → create_execution 拒绝（409 语义）；执行已完成（execution_refs done）→ 拒绝；内容为空 + 无执行 → 放行
2. **至少一道有限护栏**：全 0/None limits → ValueError；max_chapters=0 但 max_agent_calls=5 → 通过
3. **访谈循环**：≤5 问/轮；问题即模板（questions[].template 返回）；auto=true → 直接 F42 路径；授权项（配角自定）→ authorized 记录—— 扩展：mock LLM 动态提问——通用必答 + 针对性并存（kind 字段断言）；回答后提取 confirmed_items 落库且下轮只问未确定项（不重复提问）；冲突回答 → conflicts 记录 + kind=conflict 回问；必答项齐备 → confirming=true 列全部确定项；confirm=true → 完成；LLM 失败 → 降级 ROUND1/ROUND2 常量兜底
4. **Send fan-out map-reduce**（阶段 3，真实 LangGraph 图）：3 章并行 → join 回收 3 结果；聚合通道 reducer 生效（Spike ② 断言形态）
5. **卷边界 HITL**（阶段 3，真实 checkpointer）：卷内章全部写完 → interrupt 暂停 → approve 续卷 / reject 中止（F29 HITL 双分支同构）
6. **失败恢复策略树**（阶段 3）：章级失败重试 2 次 → failed 继续；卷级失败 → interrupt 用户决定（mock supervisor 补救）
7. **跨重启 resume**（阶段 4，真实 AsyncSqliteSaver + 子进程）：进程 1 跑到卷边界 → 进程 2 同文件 resume → 完成无重复（Spike ⑦ 闭环复刻为测试）
8. **干预 API**（阶段 4）：pause → 状态 paused；resume → 续跑；redirect 跳过章 → progress skipped；edit → diff 标注；干预已完成章 → 422
9. **GUI 主路径闭环**（阶段 1，Vitest + E2E，Q1=C v1.1）：访谈对话 → 委托 → 子 agent 展开行可见 → 草稿回收（「插入正文」）；E2E 走 e2e-ai-backend 开关模式
10. **GUI 干预/密度**（阶段 4，Vitest，Q1=C v1.1）：干预控件触发 intervene API + diff 高亮；三层密度切换 → `density` 参数正确传递；HITL 对话框仅 waiting_hitl 显示
11. **GUI 对话式访谈**（阶段 1，Vitest）：消息流渲染 assistant 问题/用户回答；模板 chip 点击填入；confirming=true 渲染确定项汇总卡片（确认 → respond {confirm:true}；修改 → 重新回问）；kind=conflict 消息警示样式；auto 按钮保留
12. **supervisor 清单产出 + 持久化 + 回读**：跑一次 agentic 轨 → `plan.tasklist` 非空且条目形如 `{op, outline_id, title}`（每条被接受决策一条）；持久化后新 `execute`（同 plan 二次运行）的决策消息含「上次清单」段（读回）；`get_checkpoint_state()["tasklist"]` 与 `plan.tasklist` 同源
13. **降级留痕**：LLM 决策恒非法（4 次重试耗尽）→ 追加 `{op: "__degraded__", reason: "decision_invalid"}` 条目 + 运行走既有 fallback/abort（**不崩、可继续**）
14. **非约束**：清单预置「按序」条目而 LLM 决策改序 / 跳过 → 实际路由**按 LLM 决策**执行（清单不覆盖决策，`_guarded_route` 语义零改动）
15. **`get_summary` 复用 + `steps` 不变**：summary 含附加键 `tasklist`；`steps` 键集 / 条目形态与 段 2 契约**逐字一致**（零回归）

### 9.3 覆盖率与门禁

- 模块 ≥80%（ADR-027 全仓口径 98.5% 行 / 95% 分支不变，新模块按增量纳入）
- 前端组件测试纳入 frontend CI job（`vitest run`）；GUI 主路径 E2E 走 e2e-ai-backend 开关模式（CI 默认 skip，本地 env 驱动）
- 不测不存在的功能：阶段划分内的功能按阶段验收，跨阶段功能（如阶段 1 的卷级扇出）不写前置测试（gap 记 issue）
- 测试文件新增登记 ci.yml（顶层 tests 显式登记模式）；`backend/tests/unit/` 全目录跑零登记（既有）

## 10. 不在范围内

| # | 项 | 归属/原因 |
|---|----|----------|
| 1 | F45 记忆演进（M1 用户级偏好 / M2 语义风格提取） | 独立里程碑 /；M2 依赖本模块阶段 4 长跑证据 |
| 2 | deepagents task 工具嵌套委派 | F26 已禁用（工具调用语义无法程序化控制）；委派形态=Send API（设计 §2.3-3） |
| 3 | 章内断点、幂等键框架、唯一索引冲突框架、token 精确核算、双面板精致化、三级 agent、遥测看板 | 设计 §2.5 苦工清单「先能用再修」（访谈分批状态机已由 LLM 动态提问取代，见 §1.3 边界声明） |
| 4 | 干预粒度升级（章级 checkpoint / 章内暂停） | 设计 §2.3-2 interrupt 只放卷边界；章级干预仅被动动作（跳过/重试/标记）——Q3=A 拍板确认 |
| 5 | 并行 token-aware 规划、记忆回写（阶段 5 打磨） | 设计 §2.4 阶段 5 暂不建 issue，待阶段 1-4 完成后评估 |
| 6 | MCP 工具面 | F20 薄客户端经 HTTP 天然可用；不新增 MCP 工具 |
| 7 | 云端部署/多用户 | Constitution P1 本地优先 |
| 8 | 会话/记忆 UI | 独立模块——本模块只交付访谈确定项**落会话数据**（confirmed_items/conflicts，§2.2），UI 消费与展示由会话/记忆 UI 承接；它依赖本模块会话落库 |

## 11. 依赖关系

| 依赖 | 说明 | 证据 / 状态 |
|------|------|------|
| F42 管线（write_auto/write_continue） | Executor 执行体（阶段 2 顺序派发、阶段 3 Send 分支复用） | （`test_agent_service.py` / `test_planner_service.py`） |
| F27 writer-agent | agent 工厂复用（build_agentic_writer 换 system prompt）、save_draft 回收、agent_run 轨迹 | （`test_agentic_writer_service.py`） |
| F29 Supervisor | 书级主 agent 决策（卷规划/卷间推进/失败补救）+ 护栏（steps/consecutive/fallback）+ UntrackedValue llm_client 模式 | （`test_supervisor_pipeline.py`） |
| F39 Agent 实体 | 能力白名单（tool_ids/skill_ids）供章 writer 装配 | （`test_agentic_whitelist.py` 24 用例绿，装配点 `agentic_writer.py:173-227`） |
| F6 context | 上下文注入链（章 brief 变量） | — |
| outline/character 实体（F11/F9 + F43 P3/P4 三级结构） | planner 产出落库（level/parent_id/chapter_id） | （`test_outline_p3.py` / `test_outline_tree_guard.py`） |
| F32 settings | 多维上限默认键 —— **不 MODIFY** | —（仅引用，零改动） |
| **langgraph-checkpoint-sqlite** | AsyncSqliteSaver（阶段 4） | ⏳ 新增依赖（Spike ⑤ 实证缺失） |
| LLM 客户端（llm_client 注入链，F27/F29 模式） | 访谈 LLM 动态提问引擎；模型未配置前置校验 | — |
| 会话/记忆 UI | 下游消费方：访谈确定项落会话（confirmed_items/conflicts）→ 会话列表/归档/删除/记忆提取 | ⏳ 下游模块 |
| 被依赖 | F45 M2 依赖本模块阶段 4 证据；会话/记忆 UI 为下游消费方 | — |

> ✅ **状态标记已复核并修正**：上表 `F6 context` / `F39 Agent 实体` 两行
> 的 `—` 原为**无证据谎报**。W1/W2 已修复实现，本表两行现附可验证证据
> （测试文件 + PR 号 + 装配点行号），同表其余 `—` 行亦补齐承载测试。
> 原审计发现 的 b 部分**已闭环**；a 部分（证据门禁）见 PR
> （`contract-guard.md` §「spec 状态标记证据要求」+ `ci.yml` contract filter）。
> 同类另见 `specs/f6-context/spec.md` §11、`specs/f3-writing/spec.md` §11（同批修正）。

## 12. 关键架构决策记录

| 决策点 | 选择 | 理由 | 备选（否决） |
|--------|------|------|--------------|
| D1 阶段 3 扇出形态 | `Command(goto=[Send(...)])` | Spike ① 实证只认 Command 形态（`return [Send(...)]` 报 InvalidUpdateError） | 经典文档写法（实测失败） |
| D2 并行聚合通道 | `Annotated[dict, operator.or_]` reducer | Spike ② 同 superstep 并发写普通 dict 报 INVALID_CONCURRENT_GRAPH_UPDATE；镜像 PipelineState.results | 普通 dict（实测失败） |
| D3 interrupt 落点 | 只放卷边界串行点 | Spike ③④ 实证：分支内 interrupt → multiple pending interrupts → resume 需 interrupt id（歧义）；卷边界暂停语义精确 | Send 分支内 interrupt（实测不可行） |
| D4 阶段 4 checkpointer | AsyncSqliteSaver 独立 SQLite 文件 | Spike ⑤ 独立连接不与业务 WAL 挤；项目 async FastAPI 匹配 | InMemorySaver（跨重启丢状态， 验收落空）；SqliteSaver 同步（async 栈不匹配） |
| D5 thread_id 落库 | `agent_executions.thread_id` 列（每书级运行一 thread_id） | Spike ⑥ 同 id 续跑/异 id 全新；「thread_id 落 agent_executions」 | 独立映射表（过度设计，一书一 id 足够） |
| D6 跨重启 resume | 章边界续跑 + `Command(update)` 重注入 llm_client（UntrackedValue） | Spike ⑦ 跨进程闭环实证；F29 模式复用（supervisor_pipeline L45-47） | 章内断点（设计 §2.5 苦工，不做） |
| D7 WritingPlan 载体 | 独立表只存编排元数据，结构树=root_outline_id 锚点 | 设计 §2.2 数据模型决策：planner 产出直写 outline/character，不重复存内容 | outline 加 column（污染内容表）；内嵌树（双份真相） |
| D8 「内容已写」安全阀 | create_execution 前 WHERE 检查（内容/执行完成 → 拒绝） | 设计 §2.3-1：危险的从来不是丢状态，是缺「这章已写」标记 | 无（不检查=重复内容+双倍费用） |
| D9 恢复策略树 | 章级重试 N → failed 继续；卷级 interrupt 用户/主 agent | 设计 §2.3-4 + 约束 4（用户决定或显式授权主 agent） | 全自动重试（违背约束 4）；全人工（长书不可用） |
| D10 多维上限 | 硬护栏（章数/调用数）+ 软护栏（token）+「至少一道有限护栏」校验 | 设计 §2.1 约束 3 +「至少一道有限护栏」不变式；F27 预算护栏先例 | 全部无上限（违背不变式）；全部硬上限（token 精确核算=苦工） |
| D11 上限配置载体 | **ProjectConfig.extra 项目级默认 + 请求体 BookLimits**（读取优先级 = 请求显式 > 项目级 extra > 默认常量） | 项目级上限语义更贴合「每本书独立约束」（extra 为 F1 既有字段，四层已透传零 MODIFY） | 全局 settings 扩展键（A，否决——与「每本书独立约束」语义分道，徒增跨模块 MODIFY）；仅请求体（B，否决——默认不可改） |
| D12 干预粒度 | 卷级锚点 + 章级被动动作（skip/retry/标记）——Q3=A 拍板确认 | 设计 §2.3-2 interrupt 只放卷边界；章级干预不引入新 checkpoint | 章级精细 checkpoint（违反设计约束 + 大成本） |
| D13 访谈提问引擎 | **LLM 动态提问**：单次 LLM 调用返回问题 + 确定项提取 + 冲突标记（结构化 JSON）——通用必答 + 针对性并存；服务端强约束必答项校验；LLM 失败降级到确定性常量（ROUND1/ROUND2） |  问题必须感知用户输入（问题必须感知用户输入：按 one_liner + 项目设定动态生成；提取已确定项只问未确定项；冲突回问；末尾总体确认；确定项落会话供 /记忆/审计）；确定性状态机不感知输入（已否决） | 纯确定性状态机（不感知输入，用户否决）；纯 LLM 无服务端校验（必答项可能漏问，违背「大纲/主角必须对话确认」） |
| D14 完成路径实体幂等 | 建前按项目内名称**查重复用**既有实体（总纲 / 主角）；并发窗口撞名 → 二次查名复用；无从复用 → 原样抛领域异常 → API 映射 **422** + 消息即 detail | 与 §5.2 章级幂等写、`make_volume_ensurer`「同项目同名卷复用」同惯例；客户端超时/进程被杀后**同一项目第二次完成不得永久失败**；复用既有行保住 `root_outline_id` / `character_ids` 结构锚点。另 ：`project_repo.get` 入参必须是领域 UUID（ADR-060 D9），契约违规（`TypeError`）不得被 `except Exception` 静默降级 | 改生成名重试（§6 R1 旧措辞——用户可见名漂移 + 新建孤儿结构）；静默跳过创建（丢主角且无提示）；修 `require_uuid_pk` 放开裸 int（违反 ADR-060 D9）；通用「唯一索引冲突框架」（§10 范围外） |
| D15 supervisor 任务清单落点与产消链路 | **落点 = `writing_plans` 新增 `tasklist` JSON 列**（不新造表、不进记忆域）；**粒度 = 混合**（章级锚点 + op 级步骤）；**输出协议 = 复用既有结构化 JSON 决策协议**（不引入工具调用）；supervisor 每条被接受决策追加一条条目，决策重试耗尽追加降级条目，收尾回写 `plan.tasklist`、下次 `execute` 播种读回；`get_summary.steps` 契约不变 + 附加键 `tasklist` | **权威源判据**：`progress`（实际执行态）唯一权威源不变；`tasklist` 只由 supervisor 决策写、**单向不写 progress** → 每字段单一 writer，零双写漂移。**弃独立表**：run 级 1:1 附属、`progress`/`limits`/`execution_refs` 既有 JSON 列先例、无按 run_id 之外查询需求（Rule of Three 未达），独立表徒增 join/FK/迁移。**弃记忆域**：`memory_service` 是跨项目长期知识 + **语义检索**，本需求要「精确取回本 run 上次清单」，语义召回不保证命中，且第二存储引入跨存储一致性对账 —— 直接违反「谁是权威源」判据。**弃工具调用协议**：supervisor 已有 JSON 决策 + 4 次重试 + fallback，清单**由被接受决策派生** → 零新增解析面、零新增 schema 失败分支（降级路径 = 既有 fallback/abort + 一条降级留痕条目） | 独立任务表（过度设计 + 双写风险）；记忆域（语义检索 ≠ 精确 key 回读）；工具调用 todo 协议（新解析面 + 与既有 JSON 决策双协议并存）；`get_summary.steps` 改形状（破坏 段 2 契约） |
| 问题 1 前端交付面 | 阶段 1-4 全含 GUI 面板（主/次面板 + 观察流 UI + 干预控件） | GUI 是「学习 agent 开发」的观察面，缺面板则该定位落空 | 仅后端 API + CLI（GUI 归后续前端批次）；先交付中等密度面板 |
| 问题 2 多维上限载体 | `ProjectConfig.extra` 项目级配置（章数 / token / 调用数） | 与既有项目配置合并语义一致，无新表 | 全局 settings（无法按书区分）；新建上限表（过度设计） |
| 问题 3 干预粒度 | 章级 + 卷级动作（pause / resume / 改向 / 编辑进行中状态） | 与「改向/编辑」验收范围一致 | 仅卷级动作（覆盖变窄） |
| 问题 4 访谈动态提问拆分 | 拆 2 个独立 PR：后端提问引擎先行 + 前端对话式 UI 依赖其契约 | 前后端可独立验收，回滚粒度细 | 单 PR 全量（评审面大、回滚粗） |

## 13. 验收标准

按阶段分组。**所有里程碑验收以本节 M1-M22（含 GUI 子里程碑 M3b/M6b/M9b/M12b）为准**。

### 13.1 阶段 1：M1-M3

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M1 | 一句话 → 访谈 → 一章草稿端到端（访谈 ≤5 问/轮、问题即模板、授权项记录；：问题由 LLM 动态生成——通用必答 + 针对性并存） | `inkflow book plan start "..."` + `plan respond` + `plan run`；pytest 访谈循环 + 委托契约单测 |
| M2 | 「全部你决定」路径跑 F42 write_auto；WritingPlan 状态=auto | `inkflow book plan auto "..."`；单测断言 F42 调用 + 状态 |
| M3 | 上限写死章=1/调用=1 但计数器立起来；WritingPlan/PlannerSession 落库 | `inkflow book status` 显示计数；仓储集成测试 |
| M3b | GUI：单面板访谈对话可用 + 子 agent 展开行可见 | Vitest 组件测试（mock API，访谈→委托→展开行→草稿回收闭环）+ 手工验收（写作页或 book 页） |

### 13.2 阶段 2：M4-M6

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M4 | 3-5 章顺序生成 + 每章状态显示（pending→done/failed/skipped 落库） | `inkflow book run <plan>` + `book status`；API 轮询断言进度树 |
| M5 | 上限配置生效（章数/token/调用可配置 + 至少一道有限护栏启动前校验） | limits 参数化测试：全无护栏 422；硬护栏超限终止；token 软超限告警 |
| M6 | 「内容已写」安全阀拒绝重跑 | 已有内容/已完成章 create_execution → 409；安全阀单测 + API 测试 |
| M6b | GUI：章级进度状态 UI（状态徽标 + 进度条，观察流仪表密度） | Vitest 组件测试（mock runs 状态轮询）+ 手工验收 |

### 13.3 阶段 3：M7-M9

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M7 | 一卷端到端：卷 planner 动态拆章 → Send map-reduce 并行扇出 → join 回收 | pytest 真实 LangGraph 图（3 章并行 + reducer 聚合）；`book run` 一卷 |
| M8 | 卷边界暂停确认（约束 8 卷级暂停、章级只报告） | `book status` 显示 waiting_hitl + `book confirm --approved`；F29 HITL 双分支测试同构 |
| M9 | 子 agent 失败 → 报告 → 用户选择 → 主 agent 补救（恢复策略树） | 章级失败重试 N → failed 继续；卷级失败 interrupt 用户决定/授权 supervisor；策略树测试 |
| M9b | GUI：卷级 HITL 确认对话框（waiting_hitl → approve/reject + decision） | Vitest 组件测试（mock confirm 端点）+ 手工验收 |

### 13.4 阶段 4：M10-M12

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M10 | 杀进程 → 重启 → resume → 断言无重复内容 | 子进程测试（Spike ⑦ 闭环复刻）：P1 跑到卷边界 → P2 resume 完成 → 无重复 Draft |
| M11 | 干预指令生效可见（pause/resume/改向/编辑 + 差异标注） | `book intervene` 各动作 + `diff` 字段断言；已完成章干预 422 |
| M12 | 回归摘要 + 结构化运行日志（到哪了/接下来/可导出） | `book summary --export <file.json>` 断言 steps JSON 快照 + 进度树 |
| M12b | GUI：干预控件（pause/resume/redirect/edit + diff 高亮）+ 回归摘要面板 + 观察流三层密度切换 | Vitest 组件测试 + E2E（GUI 主路径闭环）；`pnpm test`（vitest run） |

### 13.5 访谈 LLM 动态提问：M13-M14

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M13 | 后端提问引擎（PR-1， 验收「访谈问题由 LLM 按 one_liner+项目设定动态生成；已确定项不再重复提问；确定项落会话可回溯」） | mock LLM 单测（通用必答 + 针对性并存、提取 confirmed_items 只问未确定项、冲突回问、末尾总体确认 confirm=true 完成、LLM 失败降级 ROUND1/ROUND2）；API 测试（confirm 端点 + confirmed_items/conflicts 响应字段）；`book plan show` 回溯确定项 |
| M14 | 前端对话式 UI（PR-2， 验收「后端+前端测试全绿」） | Vitest 组件测试（对话式消息流、确定项汇总卡片确认/修改、kind=conflict 警示、auto 按钮）；`pnpm test`（vitest run） |

### 13.6 覆盖 + 旧稿备份 + 恢复读口：M15-M17

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M15 | 迁移三形态 + 幂等（旧库补列且**存量 previous_content 恒 NULL**（零回填）/ 新库 no-op / 表不存在 no-op / 连续两次调用等价）；ORM 基线已重导 | `pytest backend/tests/unit/infrastructure/database/test_chapters_previous_content_migration_1430.py`；`uv run python ci_cd/check_orm_migration_drift.py --regen` 后 `git diff --exit-code ci_cd/orm_migration_baseline.json` |
| M16 | 备份「覆盖前必落」（旧正文逐字进 `previous_content`）+「旧值为空不留空壳」+ 恢复读口可写回（且恢复自身遵守覆盖口径 = 双向切换）；`chapters.previous_content` 随章资源可回读 | `pytest backend/tests/unit/domain/services/test_chapter_previous_content_1430.py tests/api/test_chapter_restore_previous_1430.py` |
| M17 | 双条件拒绝（只给 force / 只给 confirm_overwrite → 422）；force 抵达后台执行体；备份落点随 force 响应可见；**非 force 路径零变化**（既有安全闸用例全绿 + 非 force 请求调用面逐字不变） | `pytest backend/tests/unit/domain/services/test_book_run_force_1430.py tests/api/test_book_force_overwrite_1430.py backend/tests/unit/domain/services/test_book_service_safety_gate_1265.py backend/tests/unit/domain/services/test_book_reset_1282.py tests/cli/test_cli_book_force_1430.py` |

### 13.7 planner 完成路径缺陷修复：M18-M19

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M18 | 仅配项目级模型（全局默认为空）→ 访谈走 LLM 动态提问（不落模板题库）；`resolve_model` 的「项目」一级非空；**契约违规（裸 int）不被吞**（显式失败）；真未配任何模型仍降级模板题库；非契约类失败（DB 抖动）仍回退全局默认 | `pytest backend/tests/unit/domain/services/test_planner_service_1462_1463.py`；`pytest tests/api/test_books_planner_project_model_1462.py`（真实 repo + 假 LLM，全链路 start → respond → confirm） |
| M19 | 完成路径幂等：同项目第二次 confirm / 第二次访谈**复用**既有总纲与主角（各只 create 一次，`root_outline_id` / `character_ids` 指向既有行）；并发窗口二次查名复用；无从复用 → 422 + 可读 detail（非 500 无详情）；同族 `.int` 漏网（`memory_service` ×2 / `agent_service_context` ×1）收口且静态回归锁生效 | `pytest backend/tests/unit/domain/services/test_planner_service_1462_1463.py backend/tests/unit/domain/services/test_repo_id_contract_1462.py backend/tests/unit/api/routers/test_books_planner_conflict_1463.py` |

### 13.8 supervisor 任务清单落库与决策：M20-M22

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M20 | supervisor 产出结构化清单并**持久化**（`plan.tasklist` 非空、条目形如 `{op, outline_id, title}`，每条被接受决策一条；收尾含 HITL 中断前回写） | `pytest backend/tests/unit/infrastructure/agent/test_book_agentic_tasklist_1439.py` |
| M21 | 清单**可被后续决策读回**（同 plan 二次 `execute` 的决策消息含「上次清单」段；`get_checkpoint_state()["tasklist"]` 与 `plan.tasklist` 同源）；**不产生两套「下一步」**（清单**不覆盖** supervisor 的 `{action, op, outline_id}` 决策——负例：把清单当约束强制按序 → 必须不成立） | 同上（读回 + 非约束用例） |
| M22 | **GUI 复用**：`get_summary.steps` 契约不变 + 附加键 `tasklist`（「计划 vs 实际」可对照）；**schema 校验失败有降级**（LLM 输出非法 → 不崩 + 记降级条目 + 可继续）；**既有轨零回归**（静态轨 / 卷级轨不受影响各一条断言）；迁移三形态 + 幂等（旧库补列 / 新库 no-op / 表不存在 no-op / 连续两次等价） | `pytest backend/tests/unit/domain/services/test_book_tasklist_summary_1439.py backend/tests/unit/infrastructure/database/test_writing_plan_tasklist_migration_1439.py`；`uv run python ci_cd/check_orm_migration_drift.py --regen` 后 `git diff --exit-code ci_cd/orm_migration_baseline.json` |
