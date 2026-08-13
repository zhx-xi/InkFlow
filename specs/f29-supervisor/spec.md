# F29: Supervisor 自主编排 + HITL 功能规格（supervisor-agent）

**Spec 版本**: 1.0（初稿，2026-08-13）
**日期**: 2026-08-13
**依据**: Issue #161（F29 Supervisor 自主编排 + HITL）+ roadmap v2 拍板记录 5-9（2026-08-12：F29 当前做 + 路由振荡护栏 + deterministic 回退）+ F42 spec v1.3（§5.3.1 _apply_agent_order 通用节点 / §5.5 deepagents 兼容 / §5.6 成品身份）+ Spike 验证报告 `docs/f29-supervisor-spike-2026-08-13.md`（M1 结论：自研 LangGraph StateGraph 编排层）
**所属阶段**: 0.8.0（轨道 B Agent 编排链收尾：F42 spec → #268 ✅ → #269 ✅ → **#161 F29**），估算 8-12 人天
**关联 Issues**: #161（本模块）；被依赖：无（系列终点）；前置：✅ #87 LangGraph StateGraph 重构 / ✅ #269 agent_order 编排（F42 §5.3.1）
**依赖**: ✅ F42 #269 已合入（PR #305：通用节点 + 多入口/终点引擎）· ✅ F26 deepagents 集成层（PR #236）· ✅ F27 agentic writer（PR #240/#241）· ✅ F28 agent-memory（PR #242）· LangGraph 1.2.10（venv 已锁）· checkpointer（InMemorySaver 内置 / SqliteSaver 待定）
**参考 ADR**: [adr/ADR-035.md](../adr/ADR-035.md)（编排引擎=Deep Agents harness 0.7.5，原 ADR-E）、ADR-006v2（Agent 编排 LangGraph StateGraph）、ADR-015（LangChain 隔离）
**状态**: 待实现 🔲

> **模块类型声明**: 本模块为「**自主编排型**」（第 13 变体，接续 F42 配置驱动编排型）——在既有 LangGraphAgentPipeline（静态 DAG 引擎）之上新增 **Supervisor 动态路由编排层**：supervisor 节点经 LLM 决策返回 `Command(goto=role)` 动态选择下一执行角色（替代静态边拓扑），配套路由振荡护栏（同角色连续调度上限 3 + 步数上限 30）、deterministic 回退（异常/超限回退固定链）与 HITL（关键节点人工确认）。无新实体表；复用既有 ExecutionStore 执行记录。

---


## 1. 概述

### 1.1 现状缺口（2026-08-13 源码实证）

| # | 缺口 | 实证 | 归属 |
|---|------|------|------|
| ① | **执行拓扑静态**：管线按 DAG 边执行，角色顺序/重复由模板或 agent_order 预定义，LLM 无自主决策权 | `langgraph_pipeline.py` L106-120（StateGraph 按 output_to 建边）；`agent_service.py` `_apply_agent_order`（F42 §5.3.1 静态重排） | #161 |
| ② | **无动态路由能力**：deepagents 0.7.5 无 Command(goto)/supervisor 概念（grep 源码零命中）；LangGraph 原生 Command(goto) 未被使用 | Spike ①⑤：`deepagents/graph.py` create_agent 固定 ReAct 循环 | #161 |
| ③ | **无振荡护栏**：LLM 自主路由可能同角色连续调度/无限循环，无计数上限 | 现状无动态路由（①）→ 无护栏需求 | #161 |
| ④ | **无 deterministic 回退**：异常/超限时无固定链兜底 | 现状静态 DAG 无「动态决策失败」路径 | #161 |
| ⑤ | **无 HITL**：关键节点（如成品落定前）无法人工确认/中断 | LangGraph `interrupt()` 原生能力未被使用；F27 save_draft 是工具级确认流（非节点级 interrupt） | #161 |
| ⑥ | **执行记录无 HITL 状态**：AgentExecutionORM.status 无 waiting_hitl 语义 | `execution_store.py` L20-35（create 仅 pending）；`api/routers/agent.py` L33-46（202 异步） | #161 |

### 1.2 与样板差异

非 F9 实体 CRUD（无新增表）、非 F26 集成型（无新 SDK 适配）、非 F27 闭环型（单 agent ReAct 循环）——本模块是**编排层增强**：新增 `SupervisorPipeline`（实现既有 `AgentPipelineProtocol`，内部构建 supervisor 图），复用既有 `pipeline_nodes.generic_node` 角色执行体 + `PipelineState` 状态 + `ExecutionStore` 执行记录；AgentService 增加 supervisor 模式装配（新增 `mode` 参数）。

### 1.3 边界声明

- **不含** deepagents harness 改造：F29 编排层 = 自研 LangGraph StateGraph（Spike M1 定稿）；deepagents 0.7.5 保持 F27 单 agent 闭环独立（F42 §5.5 兼容结论不变）。**不新增 deepagents 依赖**。
- **不含** F42 agent_order 静态拓扑改造：本模块新增**并行编排模式**（supervisor 动态路由），F42 静态 DAG 模式保持默认；两者通过 `AgentService.execute` 的 `mode` 参数切换（默认 static 向后兼容）。
- **不含** GUI 前端：HITL 确认入口本期为 API 层（`POST /api/v1/agent/pipelines/executions/{id}/confirm`），GUI 渲染层确认 UI 归后续 issue（F19 渲染层为主入口的既有约定）。
- **不含** CLI 命令：supervisor 执行经既有 `inkflow agent execute`（#251 已合入）或 API 直达；无新 CLI 命令。
- **不含** 持久 checkpointer（SqliteSaver）：本期 HITL 用 InMemorySaver（进程内）；跨进程恢复（判据 D 跨步恢复）归远期。

---


## 2. 数据模型

### 2.1 AgentExecutionORM.status 扩展（`database/models/agent.py` MODIFY）

既有 `status` 字段为字符串（pending/running/completed/failed）。本模块新增 **`waiting_hitl`** 语义（HITL 等待人工确认）：

```python
# AgentExecutionORM.status 取值扩展（不新增列，复用既有 status 字符串字段）
# 既有: "pending" | "running" | "completed" | "failed"
# 新增: "waiting_hitl" —— supervisor 执行中断于 interrupt()，等待 POST confirm 恢复
```

- **零迁移**：字符串字段，无新列；执行记录表中不存在该值的存量数据不受影响。
- 状态转换链：`pending → running → waiting_hitl ⇄ running → completed/failed`。

### 2.2 PipelineExecuteRequest.mode 扩展（`domain/models/agent_pipeline.py` MODIFY）

```python
class PipelineExecuteRequest(BaseModel):
    # ...既有字段不变（project_id/pipeline/chapter_id/variables/role_overrides）
    mode: Literal["static", "supervisor"] = Field(default="static", description="执行模式：static=既有静态 DAG（默认）；supervisor=动态路由编排")
    supervisor: SupervisorExecuteConfig | None = Field(default=None, description="supervisor 模式配置（mode=supervisor 时生效）")
```

- **默认 static**：既有调用零改动（向后兼容）。
- `SupervisorExecuteConfig`（新 DTO）：

```python
class SupervisorExecuteConfig(BaseModel):
    """Supervisor 模式执行配置。"""

    max_steps: int = Field(default=30, ge=1, le=100, description="路由步数上限（振荡护栏）")
    max_consecutive: int = Field(default=3, ge=1, le=10, description="同角色连续调度上限（振荡护栏）")
    hitl_roles: list[str] = Field(default_factory=list, description="HITL 确认角色列表（这些角色执行前 interrupt 等待确认；空=无 HITL）")
    fallback_on_error: bool = Field(default=True, description="异常/超限时回退固定链（deterministic 兜底）；False = 直接失败")
    supervisor_prompt: str | None = Field(default=None, description="supervisor 决策 system prompt 覆盖（默认模板）")
```

### 2.3 SupervisorState（新，`infrastructure/agent/supervisor_pipeline.py` 内部）

```python
class SupervisorState(TypedDict):
    """Supervisor 图状态 — PipelineState 扩展 + supervisor 专属键。"""

    # 复用 PipelineState 既有键（context/stages/llm_client/results/_abort）
    context: PipelineContext
    stages: dict[str, PipelineStage]
    llm_client: LLMClientProtocol
    _abort: NotRequired[bool]
    results: Annotated[dict[str, StageResult], operator.or_]

    # supervisor 专属键
    route_history: Annotated[list[str], lambda a, b: a + b]  # 路由历史（append 增量）
    steps: int                                                # 总步数（last-wins，节点自算）
    consecutive: int                                          # 同角色连续调度计数（last-wins）
    last_role: str                                            # 上一个执行角色（振荡检测基准）
    final_output: str                                         # 成品（reviser 输出，与 F42 §5.6 一致）
    hitl_pending: NotRequired[bool]                           # HITL 暂停标记
```

### 2.4 决策论证

| 决策 | 方案 | 理由 |
|------|------|------|
| 编排引擎 | **自研 LangGraph StateGraph（supervisor 图）** | Spike ①：deepagents 0.7.5 无动态路由；LangGraph 原生 Command(goto)/interrupt 全覆盖（Spike ②-⑤） |
| 动态路由 | `Command(goto=role)` 方案 A（supervisor 无静态出边） | Spike ②：方案 B（条件边+Command 并存）fan-out 教训；Command 全权控制路由最干净 |
| 执行入口 | `PipelineExecuteRequest.mode` 扩展（默认 static） | 零迁移；既有 execute 端点自然支持；无新端点（API 层零新增） |
| 角色执行体 | 复用 `pipeline_nodes.generic_node`（扩展 PipelineState） | 与 F42 配置驱动管线同语义；零重复实现（Spike ⑥） |
| 振荡护栏 | `steps`/`consecutive` last-wins 计数 + supervisor 节点内部校验 | 步数上限 30 + 同角色连续上限 3（issue #161 验收要点；Spike ③） |
| deterministic 回退 | fallback 节点 = 固定链（architect→writer→auditor→reviser 剩余角色） | issue #161 保底；异常/超限时用户可退回固定链（Spike ④） |
| HITL | `interrupt()` + `Command(resume)`（InMemorySaver checkpointer） | LangGraph 原生；approve/reject 双分支可编程（Spike ⑤）；持久化归远期 |
| 成品身份 | final_output = reviser 输出（与 F42 §5.6 一致） | 评审 🔴-1 定义；supervisor 结束时机 = LLM 决策「完成」或护栏触发 |

---


## 3. API 契约

**无新增 REST 端点**。supervisor 模式经既有 `POST /api/v1/agent/pipelines/execute`（`api/routers/agent.py` L33-46）扩展：body 增加 `mode` 字段（默认 static）。执行记录/状态查询/列表复用既有 `GET /pipelines/executions/{id}` / `GET /pipelines/executions`。

**新增 1 个 HITL 确认端点**（`api/routers/agent.py` MODIFY）：

| 变更 | 端点 | 说明 |
|------|------|------|
| execute 扩展 | `POST /api/v1/agent/pipelines/execute` | body 增加 `mode: "static"\|"supervisor"` + `supervisor: SupervisorExecuteConfig`（§2.2）；mode=supervisor → 走 SupervisorPipeline |
| **HITL 确认（新）** | `POST /api/v1/agent/pipelines/executions/{id}/confirm` | body `{approved: bool, comment?: str}`；执行记录 status=waiting_hitl 时恢复（approved=True 继续 / False 终止）；非 waiting_hitl → 422 |
| 状态查询 | `GET /pipelines/executions/{id}` | status=waiting_hitl 时响应含 `hitl_pending` 详情（interrupt payload：待确认角色/原因/时间） |

**请求示例（supervisor 模式）**：

```json
POST /api/v1/agent/pipelines/execute
{
  "project_id": "00000000-0000-0000-0000-000000000001",
  "pipeline": "builtin:write_chapter",
  "mode": "supervisor",
  "supervisor": {
    "max_steps": 30,
    "max_consecutive": 3,
    "hitl_roles": ["reviser"],
    "fallback_on_error": true
  }
}
```

**响应**（既有 execute 信封，mode 字段透传）：
```json
{
  "execution_id": "...",
  "pipeline": "builtin:write_chapter",
  "project_id": "...",
  "status": "pending",
  "created_at": "...",
  "mode": "supervisor"
}
```

**异常映射表**：

| 场景 | 状态码 | detail |
|------|--------|--------|
| mode=supervisor 且 supervisor 配置缺失 | 422 | 「supervisor 模式需要 supervisor 配置」 |
| supervisor.max_steps 越界（>100） | 422 | Pydantic validator（§2.2） |
| confirm 目标执行记录不存在 | 404 | 「执行记录不存在」 |
| confirm 目标非 waiting_hitl 状态 | 422 | 「执行记录不在等待确认状态」 |
| supervisor 决策 LLM 失败重试耗尽 | 执行失败（既有 PipelineError 路径） | fallback_on_error=true → 回退固定链；false → FAILED |
| 振荡护栏触发（连续/步数超限） | 执行完成（状态=completed，route_history 含 fallback 标记） | 非错误路径（护栏是设计语义） |

---


## 4. CLI 命令签名

**本模块不新增 CLI 命令**。supervisor 模式经既有 `inkflow agent execute`（#251 已合入，`cli/commands/agent_cmd.py`）透传：`--mode supervisor` + `--supervisor-json '{"max_steps": 30, ...}'`（实现确认参数形态，以 #251 已合入签名为准）。HITL 确认经 `inkflow agent confirm --execution-id N --approved`（或等效形态，实现确认）。

- **约束**：① `PipelineExecuteRequest` 字段扩展不得破坏 #251 的 execute 透传（mode 有默认值 static，零改动兼容）；② CLI 确认命令若未实现，HITL 验收降级为 API 层验证（curl confirm），并在 PR 说明标注。

---


## 5. 关键差异节：Supervisor 自主编排（动态路由 + 护栏 + 回退 + HITL）

### 5.1 编排层架构总览

```
既有静态模式（默认，F42 已实现）            supervisor 模式（本模块新增）
┌─────────────────────────────┐   ┌──────────────────────────────────────┐
│ LangGraphAgentPipeline      │   │ SupervisorPipeline (AgentPipelineProtocol)│
│  = StateGraph(静态边)        │   │  = StateGraph(supervisor 图)          │
│  stages[].input_from/output_to │   │  supervisor 节点(Command(goto))      │
│  决定拓扑（F42 _apply_agent_order）│   │  → role 节点(generic_node 复用)     │
└─────────────────────────────┘   │  → hitl 节点(interrupt)               │
                                  │  → fallback 节点(固定链)              │
                                  └──────────────────────────────────────┘
```

**消费链**：`AgentService.execute`（`domain/services/agent_service.py`）→ mode 分派：
- `static`（默认）：既有路径（_apply_agent_order + _merge_role_configs → LangGraphAgentPipeline）
- `supervisor`：_merge_role_configs（角色池装配，**不执行 _apply_agent_order 静态重排**）→ SupervisorPipeline.execute

**角色池语义**：supervisor 模式的角色池 = 模板 stages（装配后：模型/温度/prompt 覆盖完成）的**角色集合**（忽略 input_from/output_to 边关系——动态路由取代静态拓扑）。启用角色过滤复用 `_merge_role_configs` 现有逻辑（agent_* 三态语义不变：null=跳过）。

### 5.2 Supervisor 图构建（`infrastructure/agent/supervisor_pipeline.py` CREATE）

```python
class SupervisorPipeline:
    """Supervisor 动态路由编排引擎 — 实现 AgentPipelineProtocol。

    - validate: 角色池合法性（非空 / 无重复 id / 终点角色类型——成品身份 F42 §5.6）
    - execute: 构建 supervisor 图 → InMemorySaver checkpointer → ainvoke
      → 路由循环直至 END 或护栏触发 → PipelineResult 汇总
    """

    def __init__(self, llm_client: LLMClientProtocol, *, checkpointer=None):
        self._llm = llm_client
        self._checkpointer = checkpointer or InMemorySaver()
```

**图拓扑（方案 A：supervisor 无静态出边，Command 全权控制）**：

```
START → supervisor ──Command(goto=role)──→ role_node ──→ hitl ──→ supervisor
                │                             ↑              │
                └──Command(goto=END)──────────┘              │
                └──Command(goto=fallback)────→ fallback ──→ END
```

- `supervisor` 节点：LLM 决策 → 校验护栏 → 返回 `Command(update={...}, goto=role/END/fallback)`；**不设静态出边**（Spike ② 教训）
- `role_<stage_id>` 节点：包装 `pipeline_nodes.generic_node`（复用既有重试/失败语义）
- `hitl` 节点：`interrupt()` 等待人工确认（hitl_roles 含该角色时）
- `fallback` 节点：固定链执行（architect→writer→auditor→reviser 剩余未执行角色）
- 所有角色节点执行后静态边回 `supervisor`（`add_edge(role, "supervisor")`）

### 5.3 Supervisor 决策节点（LLM 动态路由核心）

```python
async def supervisor_node(state: SupervisorState, config: SupervisorExecuteConfig) -> Command:
    """LLM 决策下一个执行角色 → Command(goto)。

    决策输入（system prompt 组装）：
    - 任务上下文（PipelineContext.variables）
    - 可用角色池（state["stages"] 全部 role id + name + 摘要）
    - 路由历史（state["route_history"]，防重复/振荡感知）
    - 各角色已有输出（state["results"]，成品/修订判断依据）
    - 护栏约束声明（max_steps/max_consecutive）

    决策输出（LLM 结构化输出）：
    - {"action": "execute", "role": "<stage_id>"} → Command(goto=role)
    - {"action": "finish"}                        → Command(goto=END, final_output=reviser输出)
    - {"action": "fallback"}                      → Command(goto=fallback)（LLM 主动回退）

    护栏校验（节点内部，LLM 决策后强制）：
    - steps >= max_steps            → Command(goto=fallback)（步数超限）
    - role == last_role and consecutive >= max_consecutive → Command(goto=fallback)（振荡）
    - role 不在角色池              → Command(goto=fallback)（非法角色防御）
    - 空 content 重试（F27 教训）：LLM 决策解析失败/空 → 重试 N 次 → fallback
    """
```

- **LLM 决策实现**：复用 `LLMClientProtocol.chat`（`langchain_client.py`），supervisor 角色 = 独立 AgentRole（`id="supervisor"`, system_prompt=默认模板或 config.supervisor_prompt, model=config.llm_default_model）——**不消费 agent_***（与 F42 §5.5 agentic 路径同边界）；决策解析 = 结构化输出（`parse_model_string` 剥离前缀后调用，F26 §5.5 复用）。
- **弱模型护栏**：supervisor 决策同样面临空 content 风险（F26 Spike ② ~66%）——决策解析失败/空 → 自动重试（附路由历史重申决策指令）→ 仍空 → guardrail 终止标记 → fallback（deterministic 兜底，用户可退回固定链）。

### 5.4 振荡护栏（路由振荡检测 + 上限）

| 护栏 | 阈值（默认） | 语义 | 触发路径 |
|------|------------|------|---------|
| 同角色连续调度 | `max_consecutive=3` | 同一角色**连续**被调度 ≥3 次 → 判定振荡 → 回退固定链 | supervisor 节点内部校验（LLM 决策后） |
| 总步数 | `max_steps=30` | 路由循环总步数 ≥30 → 判定失控 → 回退固定链 | supervisor 节点内部校验 |
| 非法角色 | 角色不在角色池 | LLM 决策输出未知角色 → 防御回退 | supervisor 节点内部校验 |

- **计数实现**（last-wins 字段，节点自算）：`role_node` 返回 `{"steps": state.steps+1, "consecutive": (last_role==role ? consecutive+1 : 1), "last_role": role}`——切换角色自动重置连续计数。
- **护栏触发非错误**：`route_history` 追加 `"__fallback__"` 标记 + `final_output` = fallback 链成品；执行记录 status=completed（非 failed）。
- **防振荡语义**（Spike ③ 实证）：consecutive 达上限前 supervisor 已收到计数反馈（system prompt 含「最近路由」），LLM 自然避免同角色连续调度；护栏是**最后防线**（LLM 决策后强制校验）。

### 5.5 deterministic 回退（固定链兜底）

```python
async def fallback_node(state: SupervisorState, stages: list[PipelineStage]) -> dict:
    """deterministic 回退：固定链执行剩余角色。

    固定链顺序（与 F42 默认拓扑一致）：architect → writer → auditor → reviser
    - 已执行角色（state["results"] 有 COMPLETED 条目）跳过
    - 剩余角色按固定链顺序依次执行（复用 generic_node 语义）
    - final_output = 最后执行的 reviser 输出（F42 §5.6 成品身份）
    """
```

- 触发条件：① 步数超限 ② 振荡护栏 ③ 非法角色 ④ LLM 决策失败重试耗尽 ⑤ LLM 主动 fallback。
- 回退后用户仍可查看 route_history（前段动态路由轨迹）——「用户可退回固定链」的产品保底语义。
- `fallback_on_error=false` 时：①-④ 直接 FAILED（不回退），⑤ 仍回退（LLM 主动）。

### 5.6 HITL（关键节点人工确认）

```python
async def hitl_node(state: SupervisorState) -> dict:
    """HITL：角色执行前 interrupt 等待人工确认。

    触发条件：stage_id in config.hitl_roles
    payload: {"question": "确认执行角色 {role}（{name}）？", "role": stage_id,
              "route_history": state["route_history"], "context": ...}
    resume: Command(resume={"approved": True}) → 继续执行
            Command(resume={"approved": False}) → Command(goto=fallback)（拒绝 → 回退固定链）
    """
```

- **确认端点**：`POST /pipelines/executions/{id}/confirm`（§3）→ 查找执行记录 status=waiting_hitl → 从 checkpointer 恢复图 → `Command(resume=...)` → 更新状态。
- **状态持久化**：`AgentService._run_pipeline` 在 interrupt 捕获点更新 ExecutionStore status=waiting_hitl（含 payload 快照）；confirm 后恢复 running。
- **checkpointer 生命周期**：InMemorySaver 实例存于 SupervisorPipeline（进程内）；执行完成后清 checkpoint（内存释放）；进程重启后 waiting_hitl 记录标记为 failed（「中断后进程重启」边界，§7）。
- **超时语义**（实现确认）：waiting_hitl 超时（如 24h，实现可配置）→ 自动终止 failed；本期默认无超时（人工确认无期限），超时归远期。

### 5.7 成品身份与结束条件（F42 §5.6 衔接）

- **final_output = reviser 输出**：supervisor 决策 finish 时，取 `state["results"]["reviser"]`（reviser 未执行/禁用时 = 最后执行的内容角色 writer 输出；architect/auditor 永不作为成品——F42 §5.6 语义）。
- **结束条件**：① LLM 决策 finish（自然结束）② 护栏触发回退（fallback 链完成）③ HITL 拒绝（回退固定链完成）。
- **PipelineResult 汇总**：`stages` = 全部执行过的角色 StageResult（按 route_history 顺序，重复执行的角色合并为一次快照或保留多次执行记录——实现确认，默认保留多次）；`final_output` 如上；`status` = completed/failed。

---


## 6. 组织规则

- `SupervisorPipeline` 归属 infrastructure 层（`infrastructure/agent/supervisor_pipeline.py`），实现既有 `AgentPipelineProtocol`（`domain/ports/agent_pipeline.py`）——domain 层不感知 LangGraph API（ADR-015 保持）。
- supervisor 图状态 = `PipelineState` 扩展（`infrastructure/agent/supervisor_pipeline.py` 内部 TypedDict，不污染既有 PipelineState）。
- supervisor 决策角色（LLM 调用）走 `LLMClientProtocol.chat`（与 generic_node 同通道）——**不消费 agent_*/agent_order**（F42 §5.5 边界）。
- `mode` 分派在 `AgentService.execute`（domain 服务层，单一装配点）——router 层零逻辑。
- HITL 确认端点复用既有 `_svc` 装配（`api/routers/agent.py` L27-30）。
- checkpointer 注入：`SupervisorPipeline.__init__(checkpointer=...)`（测试可注入 Mock；默认 InMemorySaver）。

---


## 7. 边界情况与错误处理

| 场景 | 行为 | 错误面 |
|------|------|--------|
| mode=supervisor 但 supervisor 配置缺失 | API 422（§3 异常表） | 输入拒绝 |
| supervisor 决策 LLM 空 content（弱模型） | 自动重试（附路由历史）→ 仍空 → fallback（deterministic 兜底） | 防御回退（F26 教训） |
| supervisor 决策输出非法角色 | 护栏校验 → fallback | 防御回退 |
| 振荡（同角色连续 ≥3） | 护栏触发 → fallback（route_history 含 __fallback__） | 设计语义（非错误） |
| 步数超限（≥30） | 护栏触发 → fallback | 设计语义（非错误） |
| fallback_on_error=false 且 LLM 决策失败 | 直接 FAILED（PipelineError） | 执行失败 |
| 角色执行 LLM 失败（非 supervisor 决策） | 复用 generic_node 重试语义（required failed + _abort / 非 required skipped） | 既有 PipelineError 路径 |
| HITL 角色执行前 | interrupt() 暂停 → ExecutionStore status=waiting_hitl | 设计语义 |
| confirm approved | Command(resume) 继续 | 无 |
| confirm rejected | Command(resume={"approved": False}) → fallback 固定链 | 设计语义（拒绝走回退） |
| confirm 目标非 waiting_hitl | API 422「执行记录不在等待确认状态」 | 输入拒绝 |
| confirm 目标不存在 | API 404 | 资源不存在 |
| 进程重启（waiting_hitl 遗留） | 执行记录标记 failed（checkpointer 内存态丢失） | 边界（持久化归远期） |
| 全部角色已执行且 LLM 仍不 finish | steps 超限 → fallback（fallback 链空执行 → final_output = 最近 reviser/writer） | 护栏兜底 |
| 角色池为空（全部关闭） | validate 拒绝 → PipelineError「管线至少需要一个阶段」 | 执行失败 |
| 成品角色（reviser）被禁用/未执行 | final_output = 最后执行的内容角色（writer）输出 | 软降级（F42 §5.6） |

---


## 8. 文件结构

> 对照真实源码树（2026-08-13 实证）。文件路径以主仓根为基准。

### 后端

| 动作 | 文件 | 说明 |
|------|------|------|
| CREATE | `backend/src/inkflow/infrastructure/agent/supervisor_pipeline.py` | SupervisorPipeline（§5.2）+ SupervisorState（§2.3）+ supervisor_node/role_node/hitl_node/fallback_node（§5.3-5.6） |
| MODIFY | `backend/src/inkflow/domain/models/agent_pipeline.py` | PipelineExecuteRequest 增加 `mode` + `SupervisorExecuteConfig`（§2.2） |
| MODIFY | `backend/src/inkflow/domain/services/agent_service.py` | `execute()` mode 分派（supervisor → 角色池装配 + SupervisorPipeline）；`_run_pipeline` HITL 状态更新（waiting_hitl/confirm 恢复）；`confirm_execution()` 新方法 |
| MODIFY | `backend/src/inkflow/api/routers/agent.py` | execute 透传 mode（既有端点）；新增 `POST /pipelines/executions/{id}/confirm`（§3） |
| MODIFY | `backend/src/inkflow/infrastructure/agent/execution_store.py` | 新增 `update_status`（waiting_hitl）+ `get_hitl_payload`（payload 快照） |
| CREATE | `backend/tests/unit/test_supervisor_pipeline.py` | SupervisorPipeline 整模块 RED（§9） |
| CREATE | `backend/tests/unit/test_supervisor_state.py` | SupervisorState/计数（steps/consecutive/route_history）契约 |
| MODIFY | `backend/tests/unit/test_agent_service.py`（既有，追加） | mode 分派（supervisor 走角色池装配不重排）+ confirm_execution 契约 |
| MODIFY | `backend/tests/unit/test_agent_api.py` 或等效（既有，追加） | execute mode 透传 + confirm 端点契约（422/404/成功） |
| MODIFY | `backend/tests/unit/test_langgraph_pipeline.py`（既有，守护） | 静态模式零回归（mode 默认 static） |

### 前端

**本模块无前端变更**（HITL 确认 UI 归后续 issue；F42 §5.6 GUI 写作管线化已独立拆 issue）。

---


## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 模型/契约（后端） | PipelineExecuteRequest.mode 默认 static（守护）；SupervisorExecuteConfig validator（max_steps 越界拒绝/默认值）；mode=supervisor 无 config → 422 | ≥90% |
| 服务（后端） | `execute()` mode 分派：supervisor 模式角色池 = 装配后 stages（不执行 _apply_agent_order 重排）；confirm_execution（waiting_hitl → resume/404/422） | ≥90% |
| 编排层（后端，整模块 RED） | **动态路由**：mock LLM 决策序列 → Command(goto) 路由正确（route_history 断言）；**振荡护栏**：同角色连续 3 次 → fallback；**步数上限**：steps=30 → fallback；**非法角色** → fallback；**deterministic 回退**：fallback 链执行剩余角色 + final_output=reviser；**HITL**：hitl_roles 命中 → interrupt payload + confirm resume 继续 / reject 回退；**空 content 重试**：决策空 → 重试 → fallback；**成品身份**：finish 时 final_output=reviser（禁用时 writer） | ≥90% |
| 集成（后端） | SupervisorPipeline + InMemorySaver 真实图执行（mock LLMClientProtocol 决策响应表 per-step）；**方案 A 拓扑验证**：supervisor 无静态出边、Command 全权控制（Spike ② 教训回归） | ≥90% |
| API（后端） | execute mode=supervisor 202；confirm 端点 404/422/成功；GET 状态含 hitl_pending | ≥90% |
| E2E（如扩） | 不扩（本模块无前端/GUI 变更） | — |
| 回归 | **静态模式零回归**：mode 默认 static 时既有测试全绿（test_langgraph_pipeline/test_agent_service 既有用例不动）；deepagents 路径（F27）零回归（不触碰） | 全仓 ≥60%（ADR-027 门禁） |

**RED 形态**：`SupervisorPipeline` 模块不存在 → ImportError（收集期）；`PipelineExecuteRequest.mode` 缺失 → 用例传 mode=supervisor 报 extra 拒绝（Pydantic）或断言 mode 字段失败；confirm 端点未注册 → 404。

**测试无网络约束**：mock `LLMClientProtocol.chat`（既有 test_agent_service 模式）；supervisor 决策 LLM mock 返回预置结构化输出序列（side_effect 按调用序）；InMemorySaver 真实使用（不 mock checkpointer——HITL resume 必须真实验证）。

---


## 10. 不在范围内

| 项 | 归属 |
|----|------|
| GUI HITL 确认 UI（等待状态展示/确认按钮） | 后续 issue（F19 渲染层既有约定；本模块 API 层先行） |
| 持久 checkpointer（SqliteSaver/跨进程恢复，判据 D 跨步恢复） | 远期（本模块 InMemorySaver 进程内） |
| deepagents harness 改造（subagent 动态路由） | 不规划（Spike ① 定稿：自研 LangGraph 编排层；deepagents 保持 F27 独立） |
| F42 agent_order 静态拓扑改造 | 不规划（本模块新增 supervisor 模式并行；static 默认保留） |
| supervisor 决策模型按角色差异化（#257 能力白名单） | 0.9.0 F39-F41 |
| HITL 超时自动终止 | 远期（本期默认无期限人工确认） |
| 前端执行状态 UI（supervisor 模式轨迹展示） | 后续 issue |
| supervisor 模式并行角色执行 | 不规划（动态路由 = 单角色串行循环；并行归 #270 DAG） |

---


## 11. 依赖关系

- **依赖**：#269 agent_order（✅ PR #305：通用节点 + 多入口/终点引擎，supervisor 角色执行体复用）、F26 deepagents（✅，模型名剥离/parse_model_string 复用）、F27 agentic（✅，空 content 护栏经验）、LangGraph 1.2.10（✅ venv 锁定，Command(goto)/interrupt 原生能力 Spike 实证）、checkpointer（InMemorySaver 内置）。
- **被依赖**：无（系列终点）。
- **编号口径声明**：F29 为 Agent 化升级链（F26-F29）收尾；模块类型「自主编排型」接续 F42「配置驱动编排型」（AGENTS.md 谱系计数延续）。

---


## 12. 关键架构决策记录

| 决策 | 方案 | 备选（否决理由） |
|------|------|-----------------|
| 编排引擎 | **自研 LangGraph StateGraph（supervisor 图）** | deepagents subagent 机制（无 Command(goto) 能力，无法程序化施加护栏，Spike ①）；LangGraph 裸图（正是所选，Command/interrupt 原生） |
| 动态路由 | **Command(goto=role) 方案 A（supervisor 无静态出边）** | 方案 B（条件边 + Command 并存 → fan-out + GraphRecursionError，Spike ② 实证否决）；条件边路由（护栏放条件边 → 与 Command 互斥，语义分裂） |
| 角色执行体 | **复用 pipeline_nodes.generic_node** | 重写角色节点（重复实现，F42 通用节点已有）；deepagents subagent 包装（工具循环语义不符，超范围） |
| 执行入口 | **PipelineExecuteRequest.mode 扩展（默认 static）** | 新端点（API 面重复，execute 202 异步语义天然复用）；CLI 新命令（#251 已覆盖 execute 透传） |
| 振荡护栏 | **steps/consecutive last-wins 计数 + supervisor 节点内部校验** | 条件边护栏（与 Command 互斥，Spike ②）；LangGraph 内置 recursion_limit（全局限制，非角色级语义） |
| deterministic 回退 | **fallback 节点 = 固定链（architect→writer→auditor→reviser 剩余角色）** | 直接失败（产品保底落空，用户无法退回固定链）；重新执行全部角色（浪费已执行输出） |
| HITL | **interrupt() + Command(resume)（InMemorySaver）** | 工具级 interrupt_on（deepagents 语义，非节点级）；轮询式确认（无 interrupt 原生暂停）；持久 checkpointer（SqliteSaver 新依赖 + 生命周期复杂度，归远期） |
| 成品身份 | **final_output = reviser 输出（F42 §5.6 一致）** | 最后执行角色输出（可能是 architect/auditor 非内容产出）；不定义（成品类型漂移） |
| 决策 LLM | 复用 `LLMClientProtocol.chat`（独立 supervisor 角色） | deepagents harness 决策（F27 单 agent 边界冲突）；结构化输出 SDK（新依赖，parse_model_string 复用既有） |

---


## 13. 验收标准

> 对应 issue #161 验收要点 + 本任务 M1-M9 门禁。实现 PR `Closes #161`。

- **M1 Spike 结论（已完成）**: `docs/f29-supervisor-spike-2026-08-13.md` — deepagents 0.7.5 无动态路由 → 自研 LangGraph StateGraph 编排层
- **M2 Spec 合入**: 本 spec 合入 worktree 分支（spec 与实现同 PR）
- **M3 RED 批全 FAIL**: `pytest backend/tests/unit/test_supervisor_pipeline.py test_supervisor_state.py` — 收集期 ModuleNotFoundError（模块不存在）+ 追加段 422/404 FAIL（既有文件）
- **M4 后端测试全绿**: `pytest backend/tests/unit/` — 本模块 + 既有零回归（static 默认守护）
- **M5 Supervisor 自主编排动态路由**: `test_supervisor_pipeline.py::test_dynamic_route` — mock LLM 决策序列 → Command(goto) 路由正确（route_history 断言）
- **M6 振荡护栏 + deterministic 回退**: `test_supervisor_pipeline.py::test_oscillation_guard` + `test_fallback_chain` — 同角色连续 3 次/步数 30 超限 → fallback 固定链 + final_output=reviser
- **M7 HITL 关键节点人工确认**: `test_supervisor_pipeline.py::test_hitl_confirm` + API confirm 端点契约 — interrupt payload 暂停 → POST confirm approved 恢复 / rejected 回退
- **M8 PR 合入 + CI 全绿**: PR title Conventional Commits，body `Closes #161`；statusCheckRollup 全部 job 绿（含新增测试文件 ci.yml 登记）
- **M9 issue 关闭 + 清理**: #161 closed；worktree 清理

---

## 待澄清问题

> F29 起草自检后剩余设计决策点（实现确认项已并入正文，此处仅阻塞级）：

- **Q1（阻塞级）：HITL 确认交互形态** ✅ 已确认（用户拍板：选项 A）— supervisor 模式的 HITL 是**全新交互模式**（节点级 interrupt），与 F27 save_draft 工具级确认流不同。
  - **A. API 先行**（已拍板）：POST confirm 端点 + GET 状态含 hitl_pending；GUI/CLI 后续接（本 spec 默认此方案）
  - B. CLI 确认命令同步实现（`inkflow agent confirm`）：CLI 面完整，估算 +1-2 人天
  - C. 本期不做 HITL（仅动态路由 + 护栏 + 回退）：范围收缩，但 issue #161 验收要点「HITL：interrupt() 人工确认」落空
- **Q2（设计决策级）：supervisor 决策 LLM 模型来源** ✅ 已确认（用户拍板：选项 A）—
  - **A. `config.llm_default_model`**（已拍板，与 F27 agentic 一致）
  - B. 独立配置字段（supervisor 专用模型）
  - C. 复用 reviser 角色模型（成品角色模型）
- **Q3（设计决策级）：重复执行角色的执行记录形态** ✅ 已确认（用户拍板：选项 A）— supervisor 允许同一角色多次执行（如 writer 写 2 次再审）。
  - **A. 保留多次执行记录**（已拍板，route_history 顺序展开 stages 快照，每次执行一个 StageResult）
  - B. 合并为单条（只保留最后执行结果）
