# F44: 长任务编排器（long-task-orchestrator）功能规格
> **端**: cross

**Spec 版本**: 1.4（#903 GUI 状态档位色 + progress_reason 渲染，2026-09-04；v1.3 #897 完成态判据收紧 + 失败原因可见；v1.2 #475 访谈 LLM 动态提问）
**日期**: 2026-08-17
**依据**: 设计定稿 `design/agentic-orchestrator-and-memory-design-2026-08-14.md` §2 全文（唯一真相）+ Issue #335（阶段 1）/ #336（阶段 2）/ #337（阶段 3）/ #338（阶段 4）+ Spike 验证报告 `docs/f44-orchestrator-spike-2026-08-17.md`（M1 门禁，workspace docs）+ 已合入源码核查（F27/F42/F29/F39/F6）+ Issue #475（访谈 LLM 动态提问，D1 拍板 2026-08-19）+ #486（会话/记忆 UI，D9，下游消费方）
**所属阶段**: 0.10.0（长任务编排器，F44 四阶段），估算 24-39 人天（#335 阶段 1：5-8 / #336 阶段 2：4-6 / #337 阶段 3：7-11 / #338 阶段 4：8-10 + GUI 已含，part-time 8-10 周；v1.1 较 v1.0 的 16-26 人天增加 Q1=C GUI +8-12 与 Q2=C 项目级上限 +0.5-1）；v1.2 #475 访谈 LLM 动态提问为 0.10.1 增量（估算 5-8 人天，拆 2 PR：后端提问引擎 + 前端对话式 UI，S3 实现轨）
**关联 Issues**: [#335](https://github.com/zhx-xi/InkFlow/issues/335)（阶段 1：访谈式 Planner + WritingPlan + 委托）· [#336](https://github.com/zhx-xi/InkFlow/issues/336)（阶段 2：顺序派发 + 进度状态机 + 多维上限 + 安全阀）· [#337](https://github.com/zhx-xi/InkFlow/issues/337)（阶段 3：卷级编排 + Send map-reduce + 卷级 HITL + 失败恢复）· [#338](https://github.com/zhx-xi/InkFlow/issues/338)（阶段 4：AsyncSqliteSaver + 跨重启 resume + 干预 API）· [#475](https://github.com/zhx-xi/InkFlow/issues/475)（访谈 LLM 动态提问 + 对话式 UI + 会话落库，0.10.1，本 v1.2 修订）· [#486](https://github.com/zhx-xi/InkFlow/issues/486)（会话/记忆 UI + 归档/删除/提取记忆，0.10.1，下游消费 confirmed_items）
**依赖**: ✅ F39 Agent 实体 + 能力白名单（0.9.0 #258）· ✅ F27 writer-agent（已交付）· ✅ F42 管线 write_auto/write_continue（已交付）· ✅ F29 Supervisor（已交付）· ✅ F6 context（已交付）· ✅ outline 三级结构（F43 P3+P4 已交付）· ⏳ `langgraph-checkpoint-sqlite`（阶段 4 新增依赖，Spike ⑤ 实证缺）
**参考 ADR**: [adr/agent/ADR-035.md](../../adr/agent/ADR-035.md)（编排引擎=Deep Agents harness 0.7.5）· [ADR-006v2](../../adr/agent/ADR-006v2.md)（Agent 编排 LangGraph StateGraph）· [ADR-015](../../adr/llm/ADR-015.md)（LangChain 隔离）· [ADR-019](../../adr/packaging/ADR-019.md)（编号口径）· [ADR-027](../../adr/test-ci/ADR-027.md)（覆盖率门禁）
**状态**: ✅ 已实现（PR #441/#443/#445/#446/#447/#448/#453/#454 + #505/#504 访谈 LLM v1.2，2026-08-19）

> **Spec 变更**（v1.1 → v1.2，2026-08-19，#475 D1 拍板）：访谈从「确定性分批提问」（ROUND1/ROUND2 硬编码状态机）升级为**真 LLM 动态提问**。① 通用必答问题（题材/篇幅/主题）与针对性问题（按小说大纲/类型/设定动态生成）并存（§5.1）；② 每次回答后 LLM 提取「已确定项」（confirmed_items）落会话，下轮只问「未确定项」（§5.1/§2.2）；③ 冲突/不合理回答 → 回问用户重新确认（conflicts 记录，§5.1/§2.2/§7）；④ 必答项齐备后进入末尾总体确认（confirming=true，列出全部确定项，§5.1/§3.2）；⑤ 确定项全量落 PlannerSession（供 #486 会话/记忆 UI + 提取记忆/设定库 + 用户审计，§2.2/§11）。**拆 2 PR 边界（用户拍板，Q4 已确认 ✅）**：PR-1 后端提问引擎（PlannerService 问题生成换 LLM 调用 + 确定项提取/冲突检测，§5.1 后端契约）；PR-2 前端对话式 UI（BookPlannerPanel 固定表单 → 对话式消息流，§5.1 前端契约）。正文修订位置：§1.3/§2.2/§3.2/§4/§5.1/§6/§7/§8/§9/§10/§11/§12/§13 + 待澄清 Q4。既有确定性问题常量保留为 **LLM 失败降级兜底**（§7 场景 15），向后兼容。

> **Spec 变更**（v1.0 → v1.1，2026-08-17 用户拍板固化）：**Q1=C**（阶段 1-4 全含 GUI 面板——主/次面板 + 观察流三层密度 UI + 干预控件，+8-12 人天）· **Q2=C**（多维上限载体 = ProjectConfig.extra 项目级默认，读取优先级 = 请求 > 项目级 > 默认，+0.5-1 人天）· **Q3=A**（卷级锚点 + 章级被动动作，正文 §12 D12 已一致，仅标 ✅）。联动修订：§1 定位「全栈长任务编排器」+ 边界移除 GUI 排除；§5.1-§5.4 每阶段加「GUI 交互设计」小节；§2.4/§8/§11/§12 D11 联动 Q2=C；§8/§9/§10/§13 联动 GUI 纳入；待澄清 Q1-Q3 标 ✅ 留痕不删。

> **模块类型声明**: 本模块为「**长任务编排型**」变体——新建 WritingPlan 编排元数据表 + 访谈式 Planner + 逐卷/逐章 Orchestrator Loop + 复用 F42 管线/F27 writer agent 的 Executor + 多维护栏 + 恢复策略树。与既有编排域差异：F42/F46 是**配置驱动静态/半静态拓扑**（角色链/DAG），F29 是**运行时动态路由**（supervisor 图），本模块是**长任务分层推进**（计划树 + 进度状态机 + 卷级 HITL 锚点 + 跨运行持久化）——三者共用 LangGraph StateGraph 引擎但目标不同（§1.3 边界）。编号依据：按「最新无冲突基线」接续——F38=第 18 变体为最新无冲突基线，本模块声明**第 20 变体**（F20/F46 均已占第 19，双占用冲突以 ADR-019 v6+ 重排为准，F46 spec 笔记 2026-08-16 实录）。

---

## 1. 概述

F44 合并覆盖 **#335-#338 四阶段**，作为「一句话→全书」长任务编排器实现的唯一真相来源。定位（设计 §0/§1.1）：**学习 agent 开发 + 个人自用**，非商业产品——planner-executor、HITL、checkpoint、长上下文、多 agent 状态流逐概念落在已交付的 F26-F42 代码上做增量。**交付面 = 全栈**（Q1=C 拍板，v1.1）：后端 API + CLI 之外，阶段 1-4 **全含 GUI 面板**（主面板=主 agent 对话/思考/计划/调用子 agent；次面板=子 agent 详情手动点开；观察流三层密度 UI；干预控件；回归摘要面板）——定位「**全栈长任务编排器**」（后端编排引擎 + 前端交互面板一体交付）。

**一句话 → [Planner 访谈循环] → [Orchestrator Loop（逐章/逐卷推进 + 卷级 checkpoint + 跨运行 resume）] → [Executor（复用 F42 管线 + F27 writer agent）] → [护栏系统] → [恢复策略]**（设计 §2.2 架构）。

### 1.1 现状缺口（2026-08-17 源码实证）

| # | 缺口 | 实证 | 归属 |
|---|------|------|------|
| ① | 无「一句话 → 计划」入口：大纲生成是单次请求（OutlineGenerateRequest），无多轮访谈会话载体 | `domain/models/outline.py` OutlineGenerateRequest（单轮生成） | #335 |
| ② | 无长任务编排元数据：ExecutionStore 只有单次执行记录，无书级运行（run 分组/计划树/进度状态机） | `execution_store.py`（create_execution/update_stages/update_status/get_hitl_payload/list_executions，无 run 概念）+ `AgentExecutionORM`（无 thread_id 列） | #335/#338 |
| ③ | 无章级执行前置检查：create_execution 前不查「该章已有内容/执行已完成」→ 重跑产生重复内容 + 双倍费用 | `execution_store.py` + `Chapter.content`/`Draft`（已有字段但无检查） | #336（设计 §2.3-1 安全阀） |
| ④ | 无卷级并行执行：F42/F29 均为单次运行内编排，无「卷内多章并行、卷间串行 + 边界确认」图形态 | `langgraph_pipeline.py`/`supervisor_pipeline.py`（单运行图） | #337 |
| ⑤ | checkpointer 为 InMemorySaver（进程内存），跨重启丢状态 | `supervisor_pipeline.py`（F29 明确 InMemorySaver 归远期）+ `pyproject.toml`（无 langgraph-checkpoint-sqlite） | #338 |
| ⑥ | 无运行中干预：执行启动后只能轮询状态/确认 HITL，无 pause/resume/改向/编辑 | `api/routers/agent.py`（execute/get/confirm/list/validate） | #338 |

### 1.2 与样板差异

非 F9 实体 CRUD（WritingPlan 是新表但非普通业务实体）、非 F27 闭环型（多 agent 分层）、非 F29 动态路由型（无 supervisor 决策角色，路由=计划树）、非 F42/F46 配置驱动型（拓扑由计划树+进度驱动，非用户配置）——本模块是**编排元数据 + 计划树驱动执行**：后端新增 WritingPlan 实体/访谈会话/书级运行 API/干预 API；CLI 新增 `inkflow book` 命令组；前端交互（主面板对话/子 agent 展开行/观察流三层密度/干预控件）**已拍板全含**（Q1=C，v1.1，§5 各阶段 GUI 小节 + §8 frontend 组件）。

### 1.3 边界声明

- **不含** F45 记忆演进（#339/#340，独立里程碑，M2 依赖本模块阶段 4 之后的长跑证据）
- **不含** deepagents `task` 工具嵌套委派（F26 已禁用）：阶段 3 委派形态 = LangGraph Send API 并行 fan-out（设计 §2.3-3 硬约束），包装 F27 writer-agent，**不是** deepagents subagent 工具
- **不含** 章内断点、幂等键框架、唯一索引冲突框架、token 精确核算、双面板精致化、三级 agent（设计 §2.5 苦工清单「先能用再修」）；访谈分批状态机已于 v1.2 由 LLM 动态提问取代（§5.1，确定性分批仅保留为 LLM 失败降级兜底，§7 场景 15）；GUI 仅含基础面板交互（§5 各阶段 GUI 小节），品牌动画/视觉打磨等精致化仍按 ui-design-taste 克制原则留范围外（§10）
- **不含** MCP 表现层（F20 薄客户端经 HTTP，本模块端点经既有 HTTP 通道天然可用，不新增 MCP 工具）

---

## 2. 数据模型

### 2.1 WritingPlan 领域实体（新建 `domain/models/writing_plan.py`）

设计 §2.2 数据模型决策：**planner 产出的大纲/角色直接写现有 `outline`/`character` 实体（复用 P3+P4 三级结构 level/parent_id/chapter_id），`WritingPlan` 只存编排元数据（结构树 + 进度 + 产物引用），不重复存内容**——打通设定库与 RAG 检索（outline/character 落库后天然可被 RAG 检索，WritingPlan 不持有正文副本）。

```python
class PlanNodeStatus(StrEnum):
    """计划节点进度状态机（设计 §2.2 + #335 要点：pending/in_progress/done/failed/skipped）。"""
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

### 2.2 访谈会话载体（新建 `domain/models/planner_session.py`；v1.2 #475 扩展确定项/冲突/总体确认字段）

访谈式 Planner 的多轮会话（设计 §2.1 约束 5/6：分批 ≤5 问、问题即模板；v1.2 起问题由 LLM 动态生成，确定项/冲突/总体确认落会话供 #486 消费）：

```python
class PlannerSession(BaseModel):
    """访谈会话（新建表 planner_sessions，阶段 1；v1.2 #475 扩展）。

    Attributes:
        id: 会话 UUID.
        project_id: 所属项目 UUID.
        status: drafting / completed / declined（「全部你决定」= declined → 直接跑 F42）.
        one_liner: 用户一句话（题材/体裁/篇幅/主角等原始输入）.
        round: 当前轮次（每轮 ≤5 问）.
        asked_questions: 已问问题快照（JSON，供问题即模板复用；v1.2 由 LLM 生成）.
        answers: 用户回答快照 {question_id: answer}.
        authorized: 显式授权项（如「配角自定」「细节自定」，设计 §2.1 约束 1 完成度授权）.
        confirmed_items: 已确定项快照（v1.2 #475 D1 需求 2/5，list[dict]：
            {"key": 确定项标识, "value": 确定值, "source": "user" | "llm_inferred" | "auto"}）——
            LLM 每轮从对话提取，只提问未确定项；全量落库供 #486 会话/记忆 UI +
            提取记忆/设定库 + 用户审计（§5.1 后端契约）.
        conflicts: 冲突/回问记录（v1.2 #475 D1 需求 3，list[dict]：
            {"round", "question_id", "answer", "conflict_with", "resolution"}）——
            回答与已确定项/设定冲突或不合理时回问用户重新确认（§5.1）.
        confirming: 是否处于末尾总体确认阶段（v1.2 #475 D1 需求 4，bool）——
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

> v1.2 #475 注：`confirmed_items`/`conflicts`/`confirming` 为增量字段——既有 planner_sessions 表加 JSON 列（零迁移，nullable 默认空，§8.2 MODIFY 登记）；既有 drafting/completed/declined 状态语义不变（confirming 为对话阶段标志，非 status 值）。

### 2.3 AgentExecutionORM 扩展（阶段 4，`infrastructure/database/models/agent.py` MODIFY）

`agent_executions` 表加 1 列（Spike ⑥ 结论 + #338「thread_id 落 agent_executions」）：

```python
thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
"""LangGraph checkpoint thread_id（书级运行 ↔ 图 checkpoint 一一映射；None = 非书级运行）"""
```

零迁移（`create_all` + 轻量幂等迁移，无 alembic）：新列 nullable 无默认值变更，既有行兼容。

### 2.4 多维上限（设计 §2.1 约束 3 + #336「至少一道有限护栏」不变式）

```python
class BookLimits(BaseModel):
    """书级运行上限配置（请求体可传；缺省取 ProjectConfig.extra 项目级默认，Q2=C 拍板，v1.1，§12 D11）。

    - max_chapters: 硬护栏——章节数上限（默认 100，可配置）
    - max_agent_calls: 硬护栏——子 agent 调用次数上限（默认 200，可配置）
    - max_tokens: 软护栏——累计 token 预算（默认 200_000，可配置；超限告警，
      不强制终止，与硬护栏区分——#336「token 软上限，硬护栏=章数/步数/子调用数」）
    - max_sessions: 硬护栏——访谈轮次上限（默认 5 轮 × 5 问）
    """
    max_chapters: int = 100
    max_agent_calls: int = 200
    max_tokens: int = 200_000
    max_sessions: int = 5

def validate_at_least_one_hard_limit(limits: BookLimits) -> None:
    """「至少一道有限护栏」不变式（#336 启动前校验）：max_chapters/max_agent_calls
    至少一个为有限值（>0）；全部无上限（0 或 None）→ ValueError 拒绝启动。"""
```

**读取优先级（Q2=C 拍板，v1.1）**：请求体 `BookLimits` 显式 > 项目级 `ProjectConfig.extra`（键 `book_max_chapters`/`book_max_agent_calls`/`book_max_tokens`/`book_max_sessions`）> §2.4 默认常量。载体 = **ProjectConfig.extra 项目级扩展字典**（F1 既有字段，零 MODIFY——F43 P1 四层核实：extra 在 domain/ORM/router/service 均已透传；**不是** F32 全局 settings，与 F27 预算护栏「全局设置」语义分道，理由见 §12 D11）。

**计数器**：运行中在 `WritingPlan.progress`/`execution_refs` 旁维护 `counters`（调用数/累计 token/已生成章数）——阶段 1 写死 `max_chapters=1/max_agent_calls=1` 但计数器立起来（#335 要点）；阶段 2 起可配置（§5.2）。

## 3. API 契约

新路由 `api/routers/books.py`，前缀 `/api/v1/agent/books`（与既有 agent router `/api/v1/agent/pipelines/*` 同域，复用 `api/deps.py` get_db/鉴权模式）。全部端点 202 异步语义（与 F42 execute 同构：启动即返回、状态经 GET 轮询）。

### 3.1 端点总览

| 方法/路径 | 阶段 | 说明 | 状态码 |
|-----------|------|------|--------|
| `POST /planner` | 1 | 启动访谈会话（body 一句话 + project_id）→ 返回会话 + 第一轮 ≤5 问（v1.2 #475：LLM 动态生成，通用必答 + 针对性并存） | 201 |
| `POST /planner/{session_id}/respond` | 1 | 回复本轮问题（或 `auto=true` 全部你决定）→ 下一轮问 / 冲突回问 / 末尾总体确认（`confirm`）/ 完成返回 WritingPlan | 200 |
| `GET /planner/{session_id}` | 1 | 访谈会话状态（已问问题/回答快照 + 确定项/冲突，问题即模板复用；v1.2 供用户审计回溯） | 200 |
| `POST /runs` | 1/2/3/4 | `write_book` 启动书级运行（body：writing_plan_id 或 one_liner；limits；mode） | 202 |
| `GET /runs/{run_id}` | 1-4 | 书级运行状态（进度树 + 计数器 + 当前 interrupt + 章级只报告） | 200 |
| `POST /runs/{run_id}/confirm` | 3 | 卷级 HITL 确认（body `{approved, decision?}`；非 waiting_hitl → 422） | 200 |
| `POST /runs/{run_id}/intervene` | 4 | 中途干预（pause/resume/改向/编辑，§3.3） | 200 |
| `GET /runs/{run_id}/summary` | 4 | 回归摘要 + 结构化运行日志（§3.4） | 200 |

### 3.2 请求/响应示例（阶段 1 访谈 + 阶段 3 卷确认）

v1.2 #475 注：访谈问题由 LLM 按 `one_liner` + 项目设定动态生成——`questions[]` 含 `kind` 字段（`general` 通用必答 = 题材/篇幅/主题等必须确认项；`targeted` 针对性 = 按小说大纲/类型/设定动态提问），`template` 仍保留（问题即模板，可点击复制）；响应新增 `confirmed_items`/`conflicts`/`confirming`（§2.2 同构）。

```jsonc
// POST /api/v1/agent/books/planner
{ "project_id": "uuid", "one_liner": "写一本关于时间旅者的悬疑小说" }
// 201 —— 第一轮：通用必答 + 针对性并存（v1.2 #475 D1 需求 1）
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
// 200 —— LLM 提取已确定项 + 只问未确定项（v1.2 #475 D1 需求 2）
{ "session_id": "uuid", "round": 2, "completed": false,
  "questions": [ { "id": "q5", "text": "配角：需要几个主要配角？", "template": "___ 个", "kind": "general" } ],
  "confirmed_items": [ { "key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user" } ],
  "conflicts": [], "confirming": false }

// POST /api/v1/agent/books/planner/{session_id}/respond （冲突/不合理回问，v1.2 #475 D1 需求 3）
{ "answers": { "q5": "配角 5 个" } }
// 200
{ "session_id": "uuid", "round": 3, "completed": false,
  "questions": [ { "id": "q6", "text": "5 个配角对 10 万字篇幅偏多，建议 2-3 个——仍按 5 个？", "kind": "conflict" } ],
  "confirmed_items": [ { "key": "题材", "value": "悬疑 + 时间悖论科幻", "source": "user" } ],
  "conflicts": [ { "round": 2, "question_id": "q5", "answer": "配角 5 个", "conflict_with": "篇幅/复杂度合理性", "resolution": "pending" } ],
  "confirming": false }

// POST /api/v1/agent/books/planner/{session_id}/respond （末尾总体确认，v1.2 #475 D1 需求 4）
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

> GUI 对接（Q1=C，v1.1）：三层密度切换控件（表演/仪表/无声）消费同一 `density` 查询参数；`trace`/`summary`/`diff` 为 GUI 观察流与回归摘要面板的渲染数据源（§5.4 GUI 交互设计）。

### 3.5 异常映射

| 异常 | 状态码 | 说明 |
|------|--------|------|
| 会话不存在 | 404 | planner session 查无 |
| 运行不存在 | 404 | run_id 查无 |
| 上限校验失败（全无护栏） | 422 | `validate_at_least_one_hard_limit` ValueError |
| 「内容已写」安全阀命中 | 409 | 该章已有内容/执行已完成（设计 §2.3-1，§5.2） |
| 非法干预动作/目标 | 422 | 非 pause/resume/redirect/edit；目标 outline 不存在 |
| 非 waiting_hitl 确认 | 422 | 卷确认仅在 interrupt 暂停点可用（F29 confirm 同构） |
| 非 confirming 阶段 confirm（v1.2 #475） | 422 | 末尾总体确认仅在 `confirming=true` 时可用（`confirm` 请求体；F29 confirm 同构防呆） |
| outline 撞名 | 409 | 复用既有唯一索引语义（批量生成撞 IntegrityError → 服务层捕获转 409，见 §6） |

## 4. CLI 命令签名

新命令组 `inkflow book`（`cli/commands/book_cmd.py`，F7 全局约定：`--json` 信封 / 退出码 0/1/2 / 错误码）。访谈/运行全程可脚本化，输出 Rich 进度树。

```bash
# 阶段 1：访谈式 Planner（v1.2 #475：问题由 LLM 动态生成，确定项/冲突/总体确认落会话）
inkflow book plan start "写一本关于时间旅者的悬疑小说" --project <uuid>   # 启动访谈，打印第一轮问题（通用必答 + 针对性）
inkflow book plan respond <session> "悬疑为主，加入时间悖论"              # 回复一轮（LLM 提取确定项 → 只问未确定项）
inkflow book plan confirm <session>                                       # 末尾总体确认通过（列全部确定项后）
inkflow book plan auto "写一本关于时间旅者的悬疑小说" --project <uuid>    # 「全部你决定」→ 直接跑 F42 write_auto
inkflow book plan show <session>                                          # 会话状态（问题即模板复用 + 确定项/冲突快照，v1.2 供审计回溯）

# 阶段 2-4：书级运行
inkflow book run <plan_id> [--limits max_chapters=5,max_tokens=200000]    # 启动（顺序派发/卷级按进度）
inkflow book status <run_id> [--density performance|dashboard|silent]     # 状态轮询（观察流三层密度）
inkflow book confirm <run_id> --approved --decision "继续下一卷"          # 卷级 HITL 确认（阶段 3）
inkflow book intervene <run_id> --action pause|resume|redirect|edit ...   # 中途干预（阶段 4）
inkflow book summary <run_id> [--export <file.json>]                      # 回归摘要 + 结构化日志导出
```

**「全部你决定」兜底**（设计 §2.1 约束 7）：`plan auto` = 拒访谈 → 完全自主生成 → 跑 F42 `write_auto` 管线（§5.1 委托契约衔接）。

## 5. 关键差异节：长任务编排（Planner 访谈 → Orchestrator Loop → Executor → 护栏 → 恢复）

按 #335-#338 四阶段组织。每阶段为独立实现批（可独立合入），但共享本 spec 的数据模型与 §6 组织规则。

### 5.1 阶段 1：访谈式 Planner + WritingPlan + 委托（#335，一句话→一章）

**访谈循环**（设计 §2.1 约束 5/6/7；**v1.2 #475 起为 LLM 动态提问**，D1 需求 1-5 全落地）：
- 每轮 ≤5 问，问题**由 LLM 动态生成**（不再硬编码 ROUND1/ROUND2 常量）——**通用必答**（题材/篇幅/主题等必须确认项，`kind=general`）+ **针对性**（按 one_liner/小说大纲/类型/设定动态提问，`kind=targeted`）并存；问题仍带 `template`（问题即模板，可复制修改后作为回复）；全程可跳过/回改
- **已确定项提取**（D1 需求 2）：每次回答后 LLM 提取「已确定项」→ `PlannerSession.confirmed_items` 落库（key/value/source）；下轮问题**只问未确定项**（prompt 注入 confirmed_items 去重，不重复提问）
- **冲突/不合理回问**（D1 需求 3）：回答与已确定项/项目设定冲突或不合理 → `conflicts` 记录（含 resolution=pending）+ 生成冲突回问题（`kind=conflict`）请用户重新确认
- **末尾总体确认**（D1 需求 4）：必答项齐备 + 无 pending 冲突 → `confirming=true`，向用户**列出全部确定项**待总体确认；`confirm=true` → 完成（创建 WritingPlan）；用户修改某项 → 回 questioning 重问
- 大纲/主角 = **必须对话确认**（通用必答项服务端强约束，见后端契约）；配角/细节 = 显式授权后自定（`authorized` 字段，「完成度授权」）
- 「全部你决定」= 拒访谈 → 完全自主生成 = 跑 F42 `write_auto`（委托契约见下），WritingPlan 仍创建（状态=auto）
- 访谈会话载体 = `PlannerSession`（§2.2，v1.2 扩展 confirmed_items/conflicts/confirming）；完成后创建 `WritingPlan`（§2.1）+ planner 产出**直接写 outline/character 实体**（§2.1 决策论证表）

**LLM 动态提问引擎**（PR-1 后端契约，S3 实现轨，v1.2 #475）：

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
            （v1.1 兜底保留，§7 场景 15），访谈不阻塞
  落库：confirmed_items/conflicts/confirming 全量写 PlannerSession（§2.2 字段）；
        GET /planner/{session_id} 返回快照供用户审计（D1 需求 5 + #486）
```

**agent 工厂**（复用 F27，换 system prompt）：复用 `build_agentic_writer`（`agentic_writer.py` 签名实证：model/api_key/base_url/deps/system_prompt/tool_ids/skill_ids/profile_key/expected_project_id/expected_chapter_id）——白名单工具 + skill 拼接 + save_draft 回收 + agent_run 轨迹，仅 system_prompt 换为「章 writer」模板（含大纲切片/风格/偏好注入）。

**委托契约**（章 brief → save_draft 回收）：
```
章 brief = outline 章节点切片（描述/父卷上下文） + character 主角/配角摘要 + 风格/偏好（F28 注入链）
→ build_agentic_writer(system_prompt=渲染后的章 brief) → ReAct 循环 → save_draft（单工具单事务）
→ Draft 落库（status=draft） → 章级只报告（约束 8：不 interrupt）
```

**上限**：写死 `max_chapters=1/max_agent_calls=1`（#335「上限写死但计数器立起来」）——计数器字段/校验逻辑先存在，阶段 2 放开配置。

**对话式 UI**（PR-2 前端契约，S3 实现轨，v1.2 #475）：

```
BookPlannerPanel 固定表单 → 对话式消息流（ChatPanel #379 先例）：
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

**GUI 交互设计**（Q1=C 拍板，v1.1；依据设计 §2.6 自用三件核心 + #379 写作页 AI 聊天框先例 PR #418 已合入；**v1.2 #475 起 BookPlannerPanel 为对话式**，PR-2 前端契约见上）：
- **单面板对话（访谈）**：写作页域或新 book 页的面板承载访谈对话——先例 = `ChatPanel`（`executePipeline(builtin:chat)` → 1s 轮询 `getExecutionStatus` → completed 消息 + 「插入正文」→ `chapterStore.setContent`），本阶段对接 `POST /planner` + `POST /planner/{id}/respond`（SSE 复用 F23 基建，访谈问题即模板可点击复制）；「全部你决定」（auto=true）一键委托按钮；v1.2 对话式增强：确定项汇总卡片（confirming=true 展示 + 确认/修改）、冲突回问警示样式（kind=conflict）
- **子 agent 展开行（观察流）**：访谈/委托执行轨迹按 `GET /runs/{run_id}` `trace` 字段渲染可展开行（子 agent 调用/思考/工具调用），默认折叠、手动点开（次面板语义）
- 状态：`PlannerSession`（drafting/completed/declined + v1.2 confirming 对话阶段标志）→ `WritingPlan`（drafting/auto）驱动面板阶段切换；聊天消息本地 store（镜像 chapterStore 模式）
- 落点（写作页域 vs 新 book 页）由实现会话定；本 spec 只定交互语义 + 端点对接 + 状态（§8 frontend 组件清单）

### 5.2 阶段 2：顺序派发 + 进度状态机 + 多维上限 + 安全阀（#336，→几章）

**计划=数据**：章列表入 `outline` 表（level=chapter + parent_id 挂 volume；level=overall 书级锚点 + level=volume 卷节点，P3+P4 三级结构已就绪零 MODIFY）。

**顺序派发**：`write_book(plan)` 按 outline 树顺序逐章执行（阶段 2 无并行；阶段 3 起卷内 Send 扇出）。每章执行 = F42 `builtin:write_auto` 管线（或 F27 agentic 章 writer，按章 brief 委托）。

**章级进度状态机**：`WritingPlan.progress` 每章落库 `pending → in_progress → done/failed/skipped`（章级只报告，不 interrupt）。

**多维上限**（§2.4）：`BookLimits` 可配置（章数/token/调用，阶段 2 放开）；启动前校验「至少一道有限护栏」（`validate_at_least_one_hard_limit`）——token 为软护栏（超限告警），章数/调用数为硬护栏（超限终止）。

**「内容已写」安全阀**（设计 §2.3-1，最高优先级）：`create_execution` 前查该章已有内容（`Chapter.content` 非空 / `Draft` 存在）/执行已完成（`execution_refs[outline_id]` 存在且 status=done）→ **拒绝重跑**（409，§3.5）——一行 WHERE 拆掉「重复内容 + 双倍费用」。

**章级幂等写**：每章一次 save_draft（同一章执行不重复写；重复调用被安全阀拦截在前）。

**GUI 交互设计**（Q1=C 拍板，v1.1）：
- **章级进度状态 UI**：`WritingPlan.progress` 渲染（pending/in_progress/done/failed/skipped 状态徽标 + 章进度条/进度树），`GET /runs/{run_id}` 轮询驱动（镜像 `ChatPanel` 1s 轮询模式）；观察流密度=仪表（每章状态 + 计数器）
- **安全阀 409 文案展示**：「该章已有内容，拒绝重跑」错误 toast/内联提示（防用户重复点击启动）
- 状态：progress 快照为权威（§6 R2），GUI 只读渲染不持有执行状态

### 5.3 阶段 3：卷级编排 + Send map-reduce + 卷级 HITL + 失败恢复（#337，→一卷）

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
- **扇出形态 = `Command(goto=[Send(...)])`，不是 `return [Send(...)]`**（Spike ①：1.2.10 经典文档写法报 InvalidUpdateError，`_control_branch` 只认 Command 形态）
- **聚合通道必须 `Annotated[dict, operator.or_]` reducer**（Spike ②：同 superstep 并发写普通 dict 报 INVALID_CONCURRENT_GRAPH_UPDATE；镜像 `PipelineState.results` 既有模式）
- 章执行节点包装 F27 writer-agent（§5.1 委托契约），**节点内不放 interrupt**（Spike ④：分支内 interrupt → multiple pending interrupts → resume 必须带 interrupt id，语义歧义；设计 §2.3-2 硬约束实证）

**卷级 HITL 锚点**（约束 8：卷级暂停、章级只报告）：
```
volume_fan_out（Send 扇出，无 interrupt） → write_chapter 分支（并行，只写进度）
→ join（map-reduce 回收） → volume_boundary（interrupt 串行点，问用户） → 下一卷
```
Spike ③ 实测：卷内全部章并行写完 → 卷边界 interrupt 暂停（next=('volume_boundary',)）→ `Command(resume="y")` 续跑下一卷——语义精确符合设计。

**失败恢复策略树**（设计 §2.3-4 + #337 验收）：
```
章级失败 → 重试 N 次（默认 2） → 标记 failed 继续（章级只报告，进度落库）
卷级失败 → interrupt 用户决定 或 授权主 agent 决定（supervisor 补救）
```

**F29 护栏复用**：步数/连续调用/fallback 护栏（`SupervisorExecuteConfig.max_steps/max_consecutive/fallback_on_error`），步数上限随计划缩放（`max_agent_calls` 按计划章数换算，防长书超步）。

**GUI 交互设计**（Q1=C 拍板，v1.1）：
- **卷级 HITL 确认对话框**：`GET /runs/{run_id}` 状态=waiting_hitl 时弹出确认对话框（approve/reject 按钮 + decision 文本输入，镜像 CLI `book confirm` 语义）→ `POST /runs/{run_id}/confirm`；非 waiting_hitl 不显示（对齐 422 防呆语义）
- **卷内并行进度**：卷内章并行执行在观察流仪表密度聚合展示（章级徽标批量推进，不做动画滚动）
- 状态：interrupt 暂停点由后端驱动（next checkpoint 提示「卷 2」等），GUI 只消费 `confirm` 端点

### 5.4 阶段 4：AsyncSqliteSaver + 跨重启 resume + 干预 API（#338，→一本书）

**checkpointer 持久化**（Spike ⑤ 已证实）：InMemorySaver → **AsyncSqliteSaver**（`langgraph-checkpoint-sqlite`，Spike 临时装入实测 v3.1.1 可用）——**独立 SQLite 文件**（`AsyncSqliteSaver.from_conn_string()`），不与业务表挤同一 WAL 连接（#338 要点）。**pyproject 新增依赖**（§11）。

**thread_id 落库**（Spike ⑥ + #338）：每书级运行一个 thread_id，落 `agent_executions.thread_id` 列（§2.3）——书级运行 ↔ 图 checkpoint 一一映射；同 thread_id 续跑、不同 thread_id 全新 run（Spike ⑥ 实证）。

**跨重启续跑**（Spike ⑦ 已证实，#338 验收前置）：章边界续跑（不做章内断点）；resume 时 `Command(update={...})` **重注入 llm_client**——F29 模式复用（`supervisor_pipeline.py` L45-47 实证：`llm_client: Annotated[LLMClientProtocol, UntrackedValue(LLMClientProtocol)]` 不参与 checkpointer 序列化，resume 时注入）。杀进程 → 重启 → resume → 无重复内容（安全阀兜底）。

**干预 API**（粒度=卷级锚点 + 章级被动动作，Q3=A 已拍板 ✅ v1.1，§12 D12）：`POST /runs/{run_id}/intervene`——pause（后台任务挂起，卷边界 checkpoint 已存）/ resume（等价 Command(resume)）/ redirect（跳过章/改序）/ edit（改章 brief，difflib 差异标注）。FastAPI 后台任务承载运行（`BackgroundTasks` 或独立 task 管理，运行中用户可做别的）。

**回归摘要 + 结构化运行日志**（设计 §2.6-3）：`GET /runs/{run_id}/summary`——到哪了/接下来/已耗一页说清；`steps` JSON 快照（镜像 F27 AgentStep 序列）可回放复盘导出（`inkflow book summary --export`）。

**GUI 交互设计**（Q1=C 拍板，v1.1）：
- **干预控件**：运行工具栏 pause/resume 按钮 + 章行内 redirect（跳过/重试/标记 failed）+ 章 brief 编辑（edit）→ `POST /runs/{run_id}/intervene`；干预响应 `diff` 字段高亮展示（edit 前后差异，difflib 字面 diff）；已完成章干预控件禁用（422 语义防呆）
- **回归摘要面板**：`GET /runs/{run_id}/summary` 渲染（到哪了/接下来/已耗一页说清 + 结构化运行日志回放/导出按钮，镜像 CLI `--export`）
- **观察流三层密度切换**：表演（trace 全文）/仪表（章状态+计数）/无声（仅进度树）三档切换 → `density` 查询参数（§3.4 GUI 对接注）
- **克制原则（ui-design-taste）**：安静纸张感（暖白背景非纯白）、动效 ≤200ms 仅状态变化、SSE 流式是唯一「动态感」来源、写作页核心区域信息密度最低档（面板可折叠/默认收起）

### 5.5 v1.3 增量：完成态判据收紧 + 失败原因可见（#897）

> 背景：#860（PR #896）修复「key 缺失静默空值」路径后，**凭据存在但无效**（key 吊销 / provider 故障 / ollama daemon 未运行）时残留同形态假绿——`resolve_llm_credentials` 只验「有没有 key」不验「能不能用」，装配成功后章委托运行期抛错 → 全章 `progress=failed`、`tokens_used=0`、顶层 `status=completed`。book run 为 fire-and-forget 后台任务，用户只能靠轮询 status 发现，status 又不含失败原因，定位成本极高。

**完成态判据（三轨统一）**：一切「欲设 completed」的收尾点（`write_book` 章循环结束 / `write_book_volume` execute 正常返回 / `confirm_run`、`resume_run` result.status=completed / `write_book_agentic` result.status=completed）改为按**章级事实**派生：

| 章级事实 | run 终态 |
|---|---|
| failed 章 > 0 且 done 章 == 0 | `failed` |
| failed 章 > 0 且 done 章 > 0 | `degraded`（新增终态：部分成功） |
| failed 章 == 0 | `completed` |

`aborted` / `waiting_hitl` 既有语义不变（护栏中止/ HITL 暂停不重新派生）。无章快路径（`prepare_run` 无目标章）不派生，维持 completed。

**章级事实权威源（按轨）**：静态轨 = `plan.progress`（服务层自持）；volume/agentic 轨 = 收尾时 `volume_pipeline/agentic_pipeline.get_checkpoint_state(thread_id)["results"]`（`{outline_id: execution_id | "failed"}`）同步回 `plan.progress` 后派生；pipeline 鸭子无 `get_checkpoint_state`（阶段 3 旧测试形态）→ 跳过派生维持原状态（防御分支，向后兼容守护）。收尾读取必须是 resume/execute 动作完成后的**重读（fresh read）**：`confirm_run` / `resume_run` 动作前的那次读取仅用于 `__interrupt__` 判定，**不得复用为事实源**——动作前快照不含续跑段章事实，复用即 #897 假绿残留（独立评审 MAJOR 发现，v1.3 澄清）。resume_run 单测的 checkpoint 读取次数契约相应放宽为「至少一次含动作后重读」。

**失败原因可见（验收 2 落定）**：`WritingPlan` 新增顶层字段 `progress_reason: str | None`（ORM String(2000) nullable + `ensure_writing_plan_progress_reason_column` 幂等迁移，镜像 `hitl_payload` 先例）。收尾派生为 failed/degraded 时写入摘要（≤2000 截断）：静态轨 = 每章「outline_id: 异常类名: 消息」行（委托失败即时采集，单前缀不重复）；volume/agentic 轨 = failed 章列表 + 「凭据无效或运行时错误，详见章执行日志」提示。`GET /runs/{run_id}` 与 `GET /runs/{run_id}/summary` 响应新增顶层键 `progress_reason`，**仅 `failed`/`degraded` 态透出**（其余状态按状态门控返回 null，中间态不显示陈旧值）；`mark_failed`（整单异常兜底，无章级原因语义）清空该字段——防跨态泄漏（v1.3 澄清）。

**同类异常短路剩余章（裁定：不做）**：原因可见后用户可经 `intervene redirect` 处置；「连续 N 章同型异常即中止」有误伤风险（provider 瞬时抖动 + 章级重试已兜），且后台任务强杀语义未定。留待真实使用反馈再起。

**GUI/CLI**：CLI `book status` 与 GUI `runStatus` 徽标为字符串透传，`degraded`/`failed` 自动呈现（轮询停止条件为非 running/pending，无需改）。~~degraded 专属样式随后续 GUI 批次评估~~（**v1.4 #903 已落地，见下**）。

**GUI 状态档位色 + 失败原因可见（v1.4，#903）**：`BookRunPanel` 运行状态徽标由「固定灰底字符串透传」升级为**语义档位色**——文本仍原文透传（`completed`/`failed`/`degraded`/…），徽标按状态映射低饱和语义类（对齐 `ui-design-taste` 克制原则，色源 = 主题 token `ok`/`warn`/`err`，随三主题切换）：

| runStatus | 徽标语义类 | 色档 |
|---|---|---|
| `completed` | `run-badge-completed` | 绿（ok/10 底 · ok 字） |
| `failed` | `run-badge-failed` | 红（err/10 底 · err 字） |
| `degraded` | `run-badge-degraded` | 橙黄（warn/10 底 · warn 字，部分成功警示档） |
| 其余（running/pending/paused/waiting_hitl/aborted） | 无 `run-badge-*` 钩子 | 中性（surface-3 底 · ink 字），维持现状 |

`progress_reason` 渲染：前端 `RunStatusResponse` 类型 + `book` store 新增 `progressReason: string \| null`（`loadRunStatus` 透传 `res.progress_reason ?? null`，`reset` 清零）；面板在 `(runStatus 为 failed/degraded) 且 progressReason 非空` 时渲染「失败原因」块（`run-progress-reason`：标签 `book.run.reason` + 理由文本，含 outline_id 定位锚点；后端已按状态门控，前端双保险）；理由 >200 字符默认 `line-clamp-3` 三行截断 + 展开/收起按钮（镜像记忆页 `SummaryCard` 先例）。i18n：`book.run.reason` / `book.run.reason.expand` / `book.run.reason.collapse`（zh/en 对称）。契约：`BookRunPanel.test.tsx`（#903 describe，档位三档互斥 + 渲染条件守护 + 轮询 degraded 即停确认）+ `stores/book.test.ts`（progressReason 透传/reset）。简图原型 + 高保真：`design/GUI/book/book-run.html` 与 `book-run-<state>.png`（五档：running/completed/failed/degraded/degraded-expanded）。

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
| R11 | **访谈 LLM 动态提问护栏**（v1.2 #475） | ① 通用必答项（题材/篇幅/主题）服务端强约束——LLM 输出校验缺失必答项 → 拒绝/补问（防漏问）；② 已确定项（confirmed_items）为唯一提问去重依据——只问未确定项；③ 冲突/不合理必须回问（conflicts 记录 + kind=conflict 问题），不允许静默采纳；④ LLM 失败降级到确定性常量（ROUND1/ROUND2 兜底），访谈不阻塞 |

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
| 15 | LLM 动态提问失败/超时（v1.2 #475） | 重试 1 次 → 仍失败 → 回退 ROUND1/ROUND2 确定性常量（v1.1 兜底保留，问题即模板、分批节奏不变）→ 访谈不阻塞；LLM 恢复后下轮回到动态提问 | 1 |
| 16 | 回答与已确定项/设定冲突或不合理（v1.2 #475） | conflicts 记录（resolution=pending）+ 生成 kind=conflict 回问题请用户重新确认；用户新回答 resolve 后继续（不得静默采纳冲突值，§6 R11） | 1 |
| 17 | 末尾总体确认被用户修改（v1.2 #475） | confirming=true 时用户提交修改项 → 回 questioning 重问该确定项（新值进 confirmed_items，旧值留痕 conflicts 或覆盖并记录历史）→ 重新确认 | 1 |

## 8. 文件结构

### 8.1 新建（CREATE）

```
backend/src/inkflow/domain/models/writing_plan.py      # §2.1 WritingPlan + PlanNodeStatus + BookLimits
backend/src/inkflow/domain/models/planner_session.py   # §2.2 PlannerSession
backend/src/inkflow/domain/services/planner_service.py # 访谈循环（≤5 问/轮、问题即模板、授权、auto 兜底；v1.2 #475：LLM 动态提问——问题生成/确定项提取/冲突检测/末尾总体确认，确定性常量仅 LLM 失败降级兜底）
backend/src/inkflow/domain/services/book_service.py    # 书级运行（write_book 编排入口、进度状态机、上限校验、安全阀）
backend/src/inkflow/domain/ports/book_repository.py    # WritingPlan/PlannerSession 仓储 Protocol（§4.3 模式）
backend/src/inkflow/infrastructure/agent/book_pipeline.py      # 书级编排图（阶段 2 顺序 / 阶段 3 卷级 Send）
backend/src/inkflow/infrastructure/agent/planner_nodes.py     # 访谈/落库/委托节点（复用 pipeline_nodes 模式）
backend/src/inkflow/infrastructure/database/models/writing_plan.py   # WritingPlan ORM（经 models/__init__.py 注册自动建表）
backend/src/inkflow/infrastructure/database/models/planner_session.py # PlannerSession ORM
backend/src/inkflow/infrastructure/repositories/book_repository.py    # WritingPlan/PlannerSession 仓储实现
backend/src/inkflow/api/routers/books.py                # §3 端点
backend/src/inkflow/cli/commands/book_cmd.py            # §4 inkflow book 命令组
frontend/packages/renderer/src/api/books.ts             # /api/v1/agent/books 客户端（镜像 pipeline api 模式）
frontend/packages/renderer/src/stores/book.ts           # book 运行状态 store（镜像 chapterStore 模式）
frontend/packages/renderer/src/components/BookPlannerPanel.tsx  # 访谈对话式面板（ChatPanel #379 先例 PR #418；v1.2 #475：固定表单 → 对话式消息流，确定项汇总卡片 + 冲突警示，阶段 1）
frontend/packages/renderer/src/components/BookRunPanel.tsx      # 运行状态/进度 UI/干预控件/回归摘要面板（阶段 2-4）
frontend/packages/renderer/src/components/ExecutionTraceRow.tsx # 子 agent 展开行 + 观察流三层密度切换（trace/density，阶段 1-4）
frontend/packages/renderer/src/pages/book.tsx           # 新 book 页或并入写作页域（落点实现会话定，阶段 1）
frontend/packages/renderer/src/components/__tests__/book*.test.tsx  # 前端组件测试（Vitest，§9.1 前端层）
backend/tests/unit/test_writing_plan_model.py           # 模型/上限校验单测
backend/tests/unit/test_book_service.py                 # 服务层（安全阀/进度/上限）
backend/tests/unit/test_planner_service.py              # 访谈循环（v1.2：LLM 动态提问 mock——问题生成/确定项提取/冲突回问/总体确认/失败降级）
tests/integration/test_book_repository.py               # 仓储集成
tests/api/test_books_api.py                             # API 契约（新增文件须登记 ci.yml integration 链）
tests/cli/test_book_cmd.py                              # CLI 契约（登记 ci.yml integration-cli-backend）
tests/e2e/test_book_long_run.py                         # 长任务端到端（e2e-ai-backend 开关模式，§9）
```

### 8.2 修改（MODIFY）

| 文件 | 变更 | 阶段 |
|------|------|------|
| `infrastructure/database/models/agent.py` | AgentExecutionORM 加 `thread_id` 列（§2.3） | 4 |
| `infrastructure/database/models/planner_session.py` | PlannerSessionORM 加 3 JSON 列：`confirmed_items`/`conflicts`/`confirming`（v1.2 #475，零迁移 nullable 默认空，§2.2） | 1（v1.2） |
| `frontend/packages/renderer/src/api/books.ts` | 契约扩展（v1.2 #475）：`PlannerQuestion` 加 `kind`；respond 响应加 `confirmed_items`/`conflicts`/`confirming`；`PlannerRespondRequest` 加 `confirm`（§5.1 前端契约） | 1（v1.2） |
| `backend/pyproject.toml` | 新增依赖 `langgraph-checkpoint-sqlite>=3.1.1,<4` | 4 |
| `.github/workflows/ci.yml` | integration-agent-backend 链登记 `test_books_api.py`/`test_book_cmd.py`（顶层 tests 显式登记模式，F39 实证） | 1-4 |
| `cli/commands/__init__.py` | 注册 `book` 命令组 | 1 |
| `api/routers/__init__.py` 或 app 装配 | 注册 books router | 1 |
| `FEATURES.md` / `AGENTS.md`（如适用） | 功能清单登记（issue 完成时同步） | 4 |

> Q2=C 注（v1.1）：多维上限默认载体 = **ProjectConfig.extra 项目级扩展字典**（F1 既有字段，四层已透传）——**零 MODIFY**，无需 F32 settings 扩展键（§11 F32 行已改「不 MODIFY」；读取优先级见 §2.4）。

## 9. 测试策略

### 9.1 层次（镜像既有三层 + LLM 依赖开关）

| 层 | 文件 | 覆盖 | 命令 |
|----|------|------|------|
| 单元 | `backend/tests/unit/test_writing_plan_model.py` / `test_book_service.py` / `test_planner_service.py` | 模型校验、上限校验（至少一道护栏）、进度状态机、安全阀判定（纯逻辑，mock 仓储）、访谈循环（mock LLM，v1.2：动态提问/确定项提取/冲突回问/总体确认/失败降级） | `pytest tests/unit/` |
| 集成 | `tests/integration/test_book_repository.py` | WritingPlan/PlannerSession 仓储（in-memory SQLite）、thread_id 落库、confirmed_items/conflicts JSON 列读写（v1.2） | 顶层集成 job |
| API | `tests/api/test_books_api.py` | 端点契约：planner 启谈/回复/confirm/auto（LLM mock）、runs 启动/状态、confirm、intervene、summary、异常映射（404/409/422） | integration-agent-backend 链登记 |
| CLI | `tests/cli/test_book_cmd.py` | `inkflow book` 命令组（CliRunner + 临时 SQLite，isolated_db 双 patch 模式） | integration-cli-backend 链登记 |
| E2E | `tests/e2e/test_book_long_run.py` | 长任务端到端：真实 LLM 走 **e2e-ai-backend 开关模式**（CI 默认 skip，本地 `INKFLOW_E2E_LLM_*` env 真实 API；LLM 依赖测试不放默认 CI 链，F39 实证） | `pytest tests/e2e/` + env |
| 前端组件（Vitest） | `frontend/packages/renderer/src/components/__tests__/book*.test.tsx` | 访谈对话流（v1.2 对话式：确定项汇总卡片/冲突警示/confirm）、子 agent 展开行、章级进度 UI、HITL 确认对话框、干预控件、三层密度切换、回归摘要面板（mock API，F43 前端测试模式） | `pnpm test`（→ `pnpm --filter renderer test` → `vitest run`，frontend CI job） |

### 9.2 关键测试场景（每阶段 RED 契约锚点）

1. **安全阀**：章已有内容 → create_execution 拒绝（409 语义）；执行已完成（execution_refs done）→ 拒绝；内容为空 + 无执行 → 放行（#336 验收「安全阀拒绝重跑」）
2. **至少一道有限护栏**：全 0/None limits → ValueError；max_chapters=0 但 max_agent_calls=5 → 通过（#336）
3. **访谈循环**：≤5 问/轮；问题即模板（questions[].template 返回）；auto=true → 直接 F42 路径；授权项（配角自定）→ authorized 记录（#335）——v1.2 #475 扩展：mock LLM 动态提问——通用必答 + 针对性并存（kind 字段断言）；回答后提取 confirmed_items 落库且下轮只问未确定项（不重复提问）；冲突回答 → conflicts 记录 + kind=conflict 回问；必答项齐备 → confirming=true 列全部确定项；confirm=true → 完成；LLM 失败 → 降级 ROUND1/ROUND2 常量兜底
4. **Send fan-out map-reduce**（阶段 3，真实 LangGraph 图）：3 章并行 → join 回收 3 结果；聚合通道 reducer 生效（Spike ② 断言形态）
5. **卷边界 HITL**（阶段 3，真实 checkpointer）：卷内章全部写完 → interrupt 暂停 → approve 续卷 / reject 中止（F29 HITL 双分支同构）
6. **失败恢复策略树**（阶段 3）：章级失败重试 2 次 → failed 继续；卷级失败 → interrupt 用户决定（mock supervisor 补救）
7. **跨重启 resume**（阶段 4，真实 AsyncSqliteSaver + 子进程）：进程 1 跑到卷边界 → 进程 2 同文件 resume → 完成无重复（Spike ⑦ 闭环复刻为测试）
8. **干预 API**（阶段 4）：pause → 状态 paused；resume → 续跑；redirect 跳过章 → progress skipped；edit → diff 标注；干预已完成章 → 422
9. **GUI 主路径闭环**（阶段 1，Vitest + E2E，Q1=C v1.1）：访谈对话 → 委托 → 子 agent 展开行可见 → 草稿回收（「插入正文」）；E2E 走 e2e-ai-backend 开关模式
10. **GUI 干预/密度**（阶段 4，Vitest，Q1=C v1.1）：干预控件触发 intervene API + diff 高亮；三层密度切换 → `density` 参数正确传递；HITL 对话框仅 waiting_hitl 显示
11. **GUI 对话式访谈**（阶段 1，Vitest，v1.2 #475）：消息流渲染 assistant 问题/用户回答；模板 chip 点击填入；confirming=true 渲染确定项汇总卡片（确认 → respond {confirm:true}；修改 → 重新回问）；kind=conflict 消息警示样式；auto 按钮保留

### 9.3 覆盖率与门禁

- 模块 ≥80%（ADR-027 全仓口径 98.5% 行 / 95% 分支不变，新模块按增量纳入）
- 前端组件测试纳入 frontend CI job（`vitest run`）；GUI 主路径 E2E 走 e2e-ai-backend 开关模式（CI 默认 skip，本地 env 驱动）
- 不测不存在的功能：阶段划分内的功能按阶段验收，跨阶段功能（如阶段 1 的卷级扇出）不写前置测试（gap 记 issue）
- 测试文件新增登记 ci.yml（顶层 tests 显式登记模式）；`backend/tests/unit/` 全目录跑零登记（既有）

## 10. 不在范围内

| # | 项 | 归属/原因 |
|---|----|----------|
| 1 | F45 记忆演进（M1 用户级偏好 / M2 语义风格提取） | 独立里程碑 #339/#340；M2 依赖本模块阶段 4 长跑证据 |
| 2 | deepagents task 工具嵌套委派 | F26 已禁用（工具调用语义无法程序化控制）；委派形态=Send API（设计 §2.3-3） |
| 3 | 章内断点、幂等键框架、唯一索引冲突框架、token 精确核算、双面板精致化、三级 agent、遥测看板 | 设计 §2.5 苦工清单「先能用再修」（访谈分批状态机已于 v1.2 #475 由 LLM 动态提问取代，见 §1.3 边界声明） |
| 4 | 干预粒度升级（章级 checkpoint / 章内暂停） | 设计 §2.3-2 interrupt 只放卷边界；章级干预仅被动动作（跳过/重试/标记）——Q3=A 拍板确认（v1.1） |
| 5 | 并行 token-aware 规划、记忆回写（阶段 5 打磨） | 设计 §2.4 阶段 5 暂不建 issue，待阶段 1-4 完成后评估 |
| 6 | MCP 工具面 | F20 薄客户端经 HTTP 天然可用；不新增 MCP 工具 |
| 7 | 云端部署/多用户 | Constitution P1 本地优先 |
| 8 | 会话/记忆 UI（#486：会话列表/归档/删除/记忆查看/提取记忆） | 独立 issue #486（0.10.1，D9 拍板）——本模块（#475）只交付访谈确定项**落会话数据**（confirmed_items/conflicts，§2.2），UI 消费与展示由 #486 承接；#486 依赖本模块会话落库 |

## 11. 依赖关系

| 依赖 | 说明 | 状态 |
|------|------|------|
| F42 管线（write_auto/write_continue） | Executor 执行体（阶段 2 顺序派发、阶段 3 Send 分支复用） | ✅ 已实现 |
| F27 writer-agent | agent 工厂复用（build_agentic_writer 换 system prompt）、save_draft 回收、agent_run 轨迹 | ✅ 已实现 |
| F29 Supervisor | 书级主 agent 决策（卷规划/卷间推进/失败补救）+ 护栏（steps/consecutive/fallback）+ UntrackedValue llm_client 模式 | ✅ 已实现 |
| F39 Agent 实体 | 能力白名单（tool_ids/skill_ids）供章 writer 装配 | ✅ 已实现（0.9.0） |
| F6 context | 上下文注入链（章 brief 变量） | ✅ 已实现 |
| outline/character 实体（F11/F9 + F43 P3/P4 三级结构） | planner 产出落库（level/parent_id/chapter_id） | ✅ 已实现 |
| F32 settings | 多维上限默认键 —— **不 MODIFY**（Q2=C 拍板，v1.1：上限默认载体改为 ProjectConfig.extra 项目级默认，见 §2.4/§12 D11） | —（仅引用，零改动） |
| **langgraph-checkpoint-sqlite** | AsyncSqliteSaver（阶段 4） | ⏳ 新增依赖（Spike ⑤ 实证缺失） |
| LLM 客户端（llm_client 注入链，F27/F29 模式） | 访谈 LLM 动态提问引擎（v1.2 #475：问题生成/确定项提取/冲突检测）；模型未配置前置校验（#474 已合入） | ✅ 已实现（#498） |
| #486 会话/记忆 UI | 下游消费方：访谈确定项落会话（confirmed_items/conflicts）→ 会话列表/归档/删除/记忆提取（#486 依赖本模块，§10 第 8 行） | ⏳ 下游 issue（0.10.1） |
| 被依赖 | 无（0.10.0 首批模块，F45 M2 依赖本模块阶段 4 证据）；#486 为 0.10.1 下游消费方（v1.2 #475） | — |

**编号口径声明**：本模块为「长任务编排型」**第 20 变体**（F38=18 最新无冲突基线；F20/F46 双占第 19 变体，冲突以 ADR-019 v6+ 为准，F46 spec 笔记 2026-08-16 实录）。

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 否决备选 |
|---|------|------|------|----------|
| D1 | 阶段 3 扇出形态 | `Command(goto=[Send(...)])` | Spike ① 实证 1.2.10 只认 Command 形态（`return [Send(...)]` 报 InvalidUpdateError） | 经典文档写法（实测失败） |
| D2 | 并行聚合通道 | `Annotated[dict, operator.or_]` reducer | Spike ② 同 superstep 并发写普通 dict 报 INVALID_CONCURRENT_GRAPH_UPDATE；镜像 PipelineState.results | 普通 dict（实测失败） |
| D3 | interrupt 落点 | 只放卷边界串行点 | Spike ③④ 实证：分支内 interrupt → multiple pending interrupts → resume 需 interrupt id（歧义）；卷边界暂停语义精确 | Send 分支内 interrupt（实测不可行） |
| D4 | 阶段 4 checkpointer | AsyncSqliteSaver 独立 SQLite 文件 | Spike ⑤ 独立连接不与业务 WAL 挤；项目 async FastAPI 匹配 | InMemorySaver（跨重启丢状态，#338 验收落空）；SqliteSaver 同步（async 栈不匹配） |
| D5 | thread_id 落库 | `agent_executions.thread_id` 列（每书级运行一 thread_id） | Spike ⑥ 同 id 续跑/异 id 全新；#338「thread_id 落 agent_executions」 | 独立映射表（过度设计，一书一 id 足够） |
| D6 | 跨重启 resume | 章边界续跑 + `Command(update)` 重注入 llm_client（UntrackedValue） | Spike ⑦ 跨进程闭环实证；F29 模式复用（supervisor_pipeline L45-47） | 章内断点（设计 §2.5 苦工，不做） |
| D7 | WritingPlan 载体 | 独立表只存编排元数据，结构树=root_outline_id 锚点 | 设计 §2.2 数据模型决策：planner 产出直写 outline/character，不重复存内容 | outline 加 column（污染内容表）；内嵌树（双份真相） |
| D8 | 「内容已写」安全阀 | create_execution 前 WHERE 检查（内容/执行完成 → 拒绝） | 设计 §2.3-1：危险的从来不是丢状态，是缺「这章已写」标记 | 无（不检查=重复内容+双倍费用） |
| D9 | 恢复策略树 | 章级重试 N → failed 继续；卷级 interrupt 用户/主 agent | 设计 §2.3-4 + 约束 4（用户决定或显式授权主 agent） | 全自动重试（违背约束 4）；全人工（长书不可用） |
| D10 | 多维上限 | 硬护栏（章数/调用数）+ 软护栏（token）+「至少一道有限护栏」校验 | 设计 §2.1 约束 3 + #336 不变式；F27 预算护栏先例 | 全部无上限（违背不变式）；全部硬上限（token 精确核算=苦工） |
| D11 | 上限配置载体 | **ProjectConfig.extra 项目级默认 + 请求体 BookLimits**（读取优先级 = 请求显式 > 项目级 extra > 默认常量；Q2=C 拍板，v1.1） | 项目级上限语义更贴合「每本书独立约束」（extra 为 F1 既有字段，四层已透传零 MODIFY） | 全局 settings 扩展键（A，否决——与「每本书独立约束」语义分道，徒增跨模块 MODIFY）；仅请求体（B，否决——默认不可改） |
| D12 | 干预粒度 | 卷级锚点 + 章级被动动作（skip/retry/标记）——Q3=A 拍板确认（v1.1，正文 v1.0 已一致，仅标 ✅） | 设计 §2.3-2 interrupt 只放卷边界；章级干预不引入新 checkpoint | 章级精细 checkpoint（违反设计约束 + 大成本） |
| D13 | 访谈提问引擎（v1.2 #475 D1 拍板） | **LLM 动态提问**：单次 LLM 调用返回问题 + 确定项提取 + 冲突标记（结构化 JSON）——通用必答 + 针对性并存；服务端强约束必答项校验；LLM 失败降级到确定性常量（ROUND1/ROUND2） | #475 用户拍板 D1（问题必须感知用户输入：按 one_liner + 项目设定动态生成；提取已确定项只问未确定项；冲突回问；末尾总体确认；确定项落会话供 #486/记忆/审计）；确定性状态机不感知输入（用户否决——v1.1 现状） | 纯确定性状态机（不感知输入，用户否决）；纯 LLM 无服务端校验（必答项可能漏问，违背「大纲/主角必须对话确认」） |

## 13. 验收标准

按阶段分组（M 里程碑 ↔ #335-#338 验收原文映射）。**所有里程碑验收以本节 M1-M14（含 GUI 子里程碑 M3b/M6b/M9b/M12b，Q1=C 拍板 v1.1；v1.2 #475 新增 M13/M14）为准**。

### 13.1 阶段 1（#335）：M1-M3

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M1 | 一句话 → 访谈 → 一章草稿端到端（访谈 ≤5 问/轮、问题即模板、授权项记录；v1.2 #475：问题由 LLM 动态生成——通用必答 + 针对性并存） | `inkflow book plan start "..."` + `plan respond` + `plan run`；pytest 访谈循环 + 委托契约单测 |
| M2 | 「全部你决定」路径跑 F42 write_auto；WritingPlan 状态=auto | `inkflow book plan auto "..."`；单测断言 F42 调用 + 状态 |
| M3 | 上限写死章=1/调用=1 但计数器立起来；WritingPlan/PlannerSession 落库 | `inkflow book status` 显示计数；仓储集成测试 |
| M3b | GUI：单面板访谈对话可用 + 子 agent 展开行可见（Q1=C 拍板，v1.1） | Vitest 组件测试（mock API，访谈→委托→展开行→草稿回收闭环）+ 手工验收（写作页或 book 页） |

### 13.2 阶段 2（#336）：M4-M6

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M4 | 3-5 章顺序生成 + 每章状态显示（pending→done/failed/skipped 落库） | `inkflow book run <plan>` + `book status`；API 轮询断言进度树 |
| M5 | 上限配置生效（章数/token/调用可配置 + 至少一道有限护栏启动前校验） | limits 参数化测试：全无护栏 422；硬护栏超限终止；token 软超限告警 |
| M6 | 「内容已写」安全阀拒绝重跑（#336 验收原文） | 已有内容/已完成章 create_execution → 409；安全阀单测 + API 测试 |
| M6b | GUI：章级进度状态 UI（状态徽标 + 进度条，观察流仪表密度） | Vitest 组件测试（mock runs 状态轮询）+ 手工验收 |

### 13.3 阶段 3（#337）：M7-M9

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M7 | 一卷端到端：卷 planner 动态拆章 → Send map-reduce 并行扇出 → join 回收 | pytest 真实 LangGraph 图（3 章并行 + reducer 聚合）；`book run` 一卷 |
| M8 | 卷边界暂停确认（约束 8 卷级暂停、章级只报告） | `book status` 显示 waiting_hitl + `book confirm --approved`；F29 HITL 双分支测试同构 |
| M9 | 子 agent 失败 → 报告 → 用户选择 → 主 agent 补救（恢复策略树） | 章级失败重试 N → failed 继续；卷级失败 interrupt 用户决定/授权 supervisor；策略树测试 |
| M9b | GUI：卷级 HITL 确认对话框（waiting_hitl → approve/reject + decision） | Vitest 组件测试（mock confirm 端点）+ 手工验收 |

### 13.4 阶段 4（#338）：M10-M12

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M10 | 杀进程 → 重启 → resume → 断言无重复内容（#338 验收原文） | 子进程测试（Spike ⑦ 闭环复刻）：P1 跑到卷边界 → P2 resume 完成 → 无重复 Draft |
| M11 | 干预指令生效可见（pause/resume/改向/编辑 + 差异标注） | `book intervene` 各动作 + `diff` 字段断言；已完成章干预 422 |
| M12 | 回归摘要 + 结构化运行日志（到哪了/接下来/可导出） | `book summary --export <file.json>` 断言 steps JSON 快照 + 进度树 |
| M12b | GUI：干预控件（pause/resume/redirect/edit + diff 高亮）+ 回归摘要面板 + 观察流三层密度切换 | Vitest 组件测试 + E2E（GUI 主路径闭环）；`pnpm test`（vitest run） |

### 13.5 #475 访谈 LLM 动态提问（v1.2，0.10.1）：M13-M14

| M | 验收 | 验证命令/方式 |
|---|------|--------------|
| M13 | 后端提问引擎（PR-1，#475 验收「访谈问题由 LLM 按 one_liner+项目设定动态生成；已确定项不再重复提问；确定项落会话可回溯」） | mock LLM 单测（通用必答 + 针对性并存、提取 confirmed_items 只问未确定项、冲突回问、末尾总体确认 confirm=true 完成、LLM 失败降级 ROUND1/ROUND2）；API 测试（confirm 端点 + confirmed_items/conflicts 响应字段）；`book plan show` 回溯确定项 |
| M14 | 前端对话式 UI（PR-2，#475 验收「后端+前端测试全绿」） | Vitest 组件测试（对话式消息流、确定项汇总卡片确认/修改、kind=conflict 警示、auto 按钮）；`pnpm test`（vitest run） |

## 待澄清问题（阻塞级，已拍板固化 v1.1 + v1.2 Q4）

### Q1（阻塞级）前端交付面：F44 是否含 GUI 交互面板？

#335 验收原文「单面板 + 子 agent 展开行」与设计 §2.6 自用三件核心（观察流三层密度/检查点+随时改+效果可见）均带 GUI 交互色彩；但 #335-#338 工程要点全为后端编排（访谈式 planner、WritingPlan 实体、agent 工厂、顺序派发、Send map-reduce、AsyncSqliteSaver、干预 API、FastAPI 后台任务），且本 spec §10 已把 GUI 面板列为不在范围。

- **A（建议）**：F44 阶段 1-4 交付后端 API + CLI（观察流三层密度经 CLI `--density` 与 `status`/`summary` 命令呈现；子 agent 展开行=CLI 结构化输出 + API trace 字段）；GUI 主/次面板归 0.11.0+ 前端批次（F43 后端先行先例）。估算影响：无额外人天，GUI 需求进入前端 backlog。
- **B**：阶段 1 即含最小 GUI（单面板对话 + 子 agent 展开行），后续阶段 GUI 增量。估算影响：+3-5 人天/阶段（前端批次混入后端里程碑）。
- **C**：阶段 1-4 全含 GUI 面板（主/次面板 + 观察流 UI + 干预控件）。估算影响：+8-12 人天，0.10.0 里程碑膨胀。

> **✅ 已确认（用户拍板：选项 C）**：阶段 1-4 全含 GUI 面板（主/次面板 + 观察流三层密度 UI + 干预控件 + 回归摘要面板）。正文已按拍板结果修订：§1 定位「全栈长任务编排器」+ §1.3 边界移除 GUI 排除；§5.1-§5.4 每阶段加「GUI 交互设计」小节；§8 文件结构加 frontend 组件（api/store/BookPlannerPanel/BookRunPanel/ExecutionTraceRow/book 页）；§9 测试策略加前端 Vitest 层 + 场景 9/10；§10 移除「GUI 不在范围」行；§13 每阶段补 GUI 验收里程碑（M3b/M6b/M9b/M12b）。估算影响 +8-12 人天（已并入头部估算 24-39）。

### Q2（阻塞级）多维上限配置载体？

#336「多维上限：章数/token/调用可配置」——配置载体影响 §8 文件结构与 §11 依赖（F32 settings 是否 MODIFY）。

- **A（建议）**：请求体 `BookLimits`（`POST /runs` 直接传）+ F32 app_settings 扩展键默认值（`book_max_chapters`/`book_max_agent_calls`/`book_max_tokens`/`book_max_sessions`），读取优先级 = 请求体显式 > 全局设置 > 默认（F27 Q2 预算护栏先例：agent_max_steps 等）。估算影响：+0.5-1 人天（F32 settings 扩展 + 读取链）。
- **B**：仅请求体 `BookLimits`（默认值写死在 spec §2.4 常量）。估算影响：0 额外人天，但默认不可改。
- **C**：ProjectConfig.extra 存项目级默认。估算影响：+0.5-1 人天，与 F27 预算护栏（全局设置）语义不统一。

> **✅ 已确认（用户拍板：选项 C）**：多维上限载体 = **ProjectConfig.extra 项目级默认**（非 F32 全局 settings），读取优先级 = 请求体 BookLimits 显式 > 项目级 extra > 默认常量。正文已按拍板结果修订：§2.4 BookLimits 缺省取项目级 extra + 读取优先级说明；§8.2 Q2=C 注（extra 为 F1 既有字段，四层已透传，零 MODIFY）；§11 F32 settings 行改「不 MODIFY」；§12 D11 更新为项目级 extra（否决 A 全局 settings——与 F27 预算护栏「全局设置」语义分道，理由=项目级上限语义更贴合「每本书独立约束」）。估算影响 +0.5-1 人天（已并入头部估算）。

### Q3（阻塞级）阶段 4 干预 API 干预粒度？

#338「中途干预 API：pause/resume/改向/编辑进行中状态」——干预动作作用域影响 §3.3 契约与 §12 D12。

- **A（建议）**：卷级锚点 + 章级被动动作——pause/resume = 运行级（卷边界 checkpoint）；redirect/edit = 章级（跳过/重试/标记 failed/编辑章 brief），**不引入章级 checkpoint**（设计 §2.3-2 interrupt 只放卷边界）。估算影响：按 §3.3 契约实现，0 额外人天。
- **B**：仅卷级动作（pause/resume/整卷跳过/整卷重跑）。估算影响：-1 人天，但 #338「改向/编辑」验收覆盖变窄。
- **C**：章级精细 checkpoint（章内可暂停/单章独立恢复）。估算影响：+5-8 人天，违反设计 §2.3-2 硬约束 + §2.5 苦工清单（章内断点）。

> **✅ 已确认（用户拍板：选项 A）**：卷级锚点 + 章级被动动作——pause/resume 运行级（卷边界 checkpoint）；redirect/edit 章级（跳过/重试/标记 failed/编辑章 brief），**不引入章级 checkpoint**。正文 §12 D12 与 §3.3 契约 v1.0 已一致，无需大改——D12 已加「Q3=A 拍板确认（v1.1）」注；§10 第 4 行同步标注。

> 待澄清留痕：Q1-Q3 已于 2026-08-17 用户拍板并固化升 v1.1——Q1=✅ C（阶段 1-4 全含 GUI）/ Q2=✅ C（ProjectConfig.extra 项目级默认）/ Q3=✅ A（卷级锚点+章级被动动作）；正文已按拍板结果全节联动修订（§1/§2.4/§5/§8/§9/§10/§11/§12/§13），留痕不删除。Q4 已于 2026-08-19 用户拍板（#475 D1）并固化升 v1.2（见下）。

### Q4（阻塞级）#475 访谈 LLM 动态提问拆 2 PR 边界？

#475「访谈 LLM 动态提问 + 对话式 UI + 会话落库」（D1 拍板，0.10.1，估算 5-8 人天）——实现边界影响 §8 文件结构与 §13 验收分组（后端/前端各自独立验收）。

- **A（建议）**：拆 2 个独立 PR——**PR-1 后端提问引擎**（PlannerService 问题生成换 LLM 调用 + 确定项提取/冲突检测 + PlannerSession 扩展字段 + API 契约扩展 + CLI confirm 子命令 + 后端测试）→ **PR-2 前端对话式 UI**（BookPlannerPanel 固定表单 → 对话式消息流 + 确定项汇总卡片 + api/books.ts 契约扩展 + 前端测试），PR-1 先合、PR-2 依赖 PR-1 契约。估算影响：按 5-8 人天拆两批（后端 3-5 / 前端 2-3）。
- **B**：单 PR 全量实现（后端 + 前端一起）。估算影响：5-8 人天单批，评审面大、回滚粒度粗。

> **✅ 已确认（用户拍板：选项 A）**：拆 2 个独立 PR——后端提问引擎（PR-1）+ 前端对话式 UI（PR-2），后端先合前端依赖其后端契约。正文已按拍板结果修订：§5.1 新增「LLM 动态提问引擎」（PR-1 后端契约）+「对话式 UI」（PR-2 前端契约）；§2.2/§3.2/§4/§8.2/§9/§10/§11/§12 D13/§13.5 全节联动；头部估算并入 5-8 人天（0.10.1）。估算影响 +5-8 人天（0.10.1 增量，未并入 0.10.0 的 24-39）。

## 14. 动作确认

> 每个端点/命令的完整状态流表（基于 §3 + §4 + §5 + §7 事实，不重复）；LLM 行为确认（§14.3）覆盖长任务编排核心的 LLM 失败/重试/HITL 暂停/恢复/取消语义（§5/§7）。

### 14.1 端点状态流

| 端点 | 前置条件 | 动作/状态转换 | 成功 | 失败 | 边界 |
|------|---------|--------------|------|------|------|
| POST /api/v1/agent/books/planner | project_id 合法 | 启动访谈会话（LLM 动态提问，通用必答 + 针对性并存） | 201 + session_id + round 1 + questions（≤5 问/轮，含 template/kind） | 404（项目不存在） | max_rounds 硬护栏；确认项/冲突落会话 |
| POST /api/v1/agent/books/planner/{session_id}/respond | 会话存在 | 回复（或 auto=true）→ LLM 提取确定项 → 下轮问/冲突回问/末尾总体确认（confirming=true）/完成返回 WritingPlan | 200 + 下一轮 questions / completed=true + writing_plan | 404（会话不存在）；422（confirm 时非 confirming 阶段「仅 confirming=true 时可用」） | 用户修改确定项 → 回 questioning 重问；auto=true 直接跑 F42 write_auto |
| GET /api/v1/agent/books/planner/{session_id} | 会话存在 | 会话状态（已问问题/回答快照 + 确定项/冲突，问题即模板复用） | 200 | 404 | 供用户审计回溯（#486） |
| POST /api/v1/agent/books/runs | 计划存在 + 至少一道有限护栏 | write_book 启动（顺序派发/卷级 Send + 进度状态机 + 安全阀 + 多维上限） | 202 + run_id | 404（运行不存在）；409（内容已写安全阀「该章已有内容，拒绝重跑」）；422（上限全无限制 validate_at_least_one_hard_limit） | 202 异步语义；token 软护栏告警 / 章数调用数硬护栏终止；mode 默认 static |
| GET /api/v1/agent/books/runs/{run_id} | 运行存在 | 状态（进度树 + 计数器 + 当前 interrupt + 章级只报告） | 200 | 404 | density 三层（performance/dashboard/silent，默认全开） |
| POST /api/v1/agent/books/runs/{run_id}/confirm | 运行 waiting_hitl（卷边界 interrupt） | Command(resume) 恢复 | 200 + status + next_checkpoint | 422（非 waiting_hitl「卷确认仅在 interrupt 暂停点可用」） | body {approved, decision?}；F29 confirm 同构 |
| POST /api/v1/agent/books/runs/{run_id}/intervene | 运行存在 | pause/resume/redirect/edit（卷级锚点 + 章级被动动作） | 200 + diff 字段（redirect/edit 时，difflib 字面 diff 零 LLM） | 422（非法动作/目标 outline 不存在）；422（已完成章 progress=done 拒绝干预） | pause 卷边界 checkpoint 已存；并行分支进行中的章允许完成（不做章内断点） |
| GET /api/v1/agent/books/runs/{run_id}/summary | 运行存在 | 回归摘要（到哪了/接下来/已耗）+ 结构化运行日志 | 200 | 404 | steps JSON 快照（镜像 F27 AgentStep）可回放导出 |

### 14.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow book plan start/respond/confirm/auto/show | — | 访谈式 Planner（LLM 动态提问，问题即模板） | 退出码 0 + Rich 进度树 | 404/422 → 退出码 1 | plan auto → 拒访谈 → 跑 F42 write_auto |
| inkflow book run &lt;plan_id&gt; [--limits max_chapters=5,max_tokens=200000] | 计划存在 + 护栏 | 启动书级运行 | 退出码 0 + run_id | 404/409/422 → 退出码 1 | — |
| inkflow book status &lt;run_id&gt; [--density ...] | — | 状态轮询（观察流三层密度） | 退出码 0 | 404 → 退出码 1 | — |
| inkflow book confirm &lt;run_id&gt; --approved --decision "继续下一卷" | waiting_hitl | 卷级 HITL 确认 | 退出码 0 | 422 → 退出码 1 | — |
| inkflow book intervene &lt;run_id&gt; --action pause/resume/redirect/edit ... | 运行存在 | 中途干预 | 退出码 0 + diff 展示 | 422 → 退出码 1 | — |
| inkflow book summary &lt;run_id&gt; [--export &lt;file.json&gt;] | — | 回归摘要 + 结构化日志导出 | 退出码 0 | 404 → 退出码 1 | — |

### 14.3 LLM 行为确认（长任务编排核心，§5/§7）

| 场景 | 判定 | 动作/状态转换 | 成功 | 失败 | 边界 |
|------|------|--------------|------|------|------|
| 访谈 LLM 动态提问失败/超时 | LLM 调用失败/超时 | 重试 1 次 → 仍失败 → 回退 ROUND1/ROUND2 确定性常量 | 访谈不阻塞（问题即模板、分批节奏不变） | — | LLM 恢复后下轮回到动态提问（R11 ④） |
| 访谈必答项漏问 | LLM 输出缺通用必答项（题材/篇幅/主题） | 服务端强约束校验 → 该轮拒绝/补问；校验失败重试 1 次 | 必答项始终出现在 questions | — | R11 ①；大纲/主角必须对话确认 |
| 访谈冲突/不合理回答 | 回答与已确定项/项目设定冲突 | conflicts 记录（resolution=pending）+ kind=conflict 回问题 | 用户重新确认 → resolve 继续 | — | 不得静默采纳冲突值（R11 ③） |
| 章级执行失败 | write_chapter 委托失败 | 重试 N 次（默认 2）→ 标记 failed 继续（章级只报告，进度落库） | 重试成功 → 继续 | failed 继续下一章 | 恢复策略树（R8）；单工具单事务 save_draft |
| 卷级失败 | 卷中断言失败/不可恢复 | interrupt 暂停 → 用户决定（继续/跳过/中止）或授权主 agent 补救（supervisor） | 用户 confirm 后继续 | 中止 | 卷边界 interrupt 唯一暂停点（R4） |
| 卷级 HITL | volume_boundary interrupt（卷内全部章并行写完） | interrupt() → waiting_hitl（next=volume_boundary） | confirm approved → 下一卷；Command(resume=y) 续跑 | 中止/拒绝 | 章执行节点/并行分支内禁 interrupt（Spike ④ 硬约束）；并行聚合必须 Annotated reducer |
| 进程被杀/断电 | — | AsyncSqliteSaver 卷边界 checkpoint → 重启 resume 续跑（章边界） | 无重复内容（安全阀兜底） | — | llm_client UntrackedValue 不序列化 → resume 时 Command(update) 重注入；缺失 → 422 提示重新注入 |
| 并行执行中 pause | 卷边界 checkpoint 已存 | 挂起后台任务 | pause 生效 | — | 并行分支进行中的章允许完成（不做章内断点） |
| 安全阀命中 | 该章已有内容（Chapter.content 非空 / Draft 存在）/执行已完成（execution_refs 存在且 done） | create_execution 前拒绝重跑 | 409「该章已有内容，拒绝重跑」 | — | 误判宁可拒绝不可重跑（R3，防双倍费用优先） |
| 上限全无限制 | validate_at_least_one_hard_limit | 422 拒绝启动 | — | 422 | token 软护栏告警（trace 记录）/ 章数调用数硬护栏超限终止 + 进度落库 |
| 干预目标非法 | 动作非 pause/resume/redirect/edit / 目标 outline 不存在 / 已完成章 | 422 拒绝 | — | 422 | 干预效果带 diff 字段（R10） |

### 14.4 验收锚点

- A1：一句话 → 访谈 → 一章草稿端到端（访谈 ≤5 问/轮、问题即模板、授权项记录；LLM 动态提问）（M1）
- A2：plan auto → F42 write_auto + WritingPlan 状态=auto（M2）
- A3：3-5 章顺序生成 + 每章状态落库（pending→done/failed/skipped）（M4）
- A4：上限配置生效（全无护栏 422；硬护栏超限终止；token 软超限告警）（M5）
- A5：安全阀拒绝重跑 409（M6）
- A6：一卷端到端（卷 planner 拆章 → Send map-reduce 并行扇出 → join 回收）（M7）
- A7：卷边界暂停确认 waiting_hitl + confirm --approved（M8）
- A8：杀进程 → 重启 → resume → 无重复内容（M10）
- A9：干预指令 pause/resume/redirect/edit + diff 字段；已完成章干预 422（M11）
- A10：回归摘要 + 结构化运行日志导出（M12）
- A11：访谈 LLM 动态提问（M13）+ 前端对话式 UI（M14）
