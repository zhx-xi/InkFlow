# F4: Agent 编排 (agent_service) — 功能规格
> **端**: backend

> **Spec 版本**: 1.0 | **日期**: 2026-07-31 | **依据**: PRD v2.1 §6.1 F4, ADR-006v2 (LangGraph StateGraph), Constitution P1-P6
> **所属阶段**: Phase 1 — 核心引擎
> **关联 Issues**: [#4](https://github.com/zhx-xi/InkFlow/issues/4)
> **依赖**: F1 (project_service) ✅, F3 (writing_service), F5 (llm_service)
> **状态**: ✅ 已实现（PR #22）

>
> **快速导航**（2026-08-08 #201）：
> [1. 概述](L11) · [2. 数据模型](L24) · [3. API 契约](L130) · [4. CLI 命令签名](L289)
> [5. 管线执行流程与状态机](L338) · [6. 管线模板与 YAML 配置](L383) · [7. 边界情况与错误处理](L438) · [8. 文件结构](L466)
> [9. 测试策略](L505) · [10. 不在范围内](L577) · [11. 依赖关系](L592) · [12. 关键架构决策记录](L608)
---

## 1. 概述

实现多阶段 Agent 管线编排：将 Architect（架构师）→ Writer（写手）→ Auditor（审阅）→ Reviser（修订）四个角色串联成一条写作流水线，每个角色可独立配置 Prompt / 模型 / 温度。

**核心价值**: 用户运行一次 `inkflow agent run`，系统自动完成"大纲设计 → 内容生成 → 质量审校 → 修订定稿"的完整链路，全程可观测（实时查看当前阶段与进度）。

**架构决策 (ADR-006v2)**:
- 引擎采用 LangGraph `StateGraph`，但领域层通过 `AgentPipelineProtocol`（`domain/ports/agent_pipeline.py`）隔离，**领域层零 LangGraph 依赖**，测试时注入 Mock 实现即可。
- **Phase 1**: 固定 4 阶段顺序链（Architect → Writer → Auditor → Reviser）。
- **Phase 2**: 用户自定义 DAG（YAML 定义，动态构建 StateGraph，`add_edge` → `add_conditional_edges`）。

---

## 2. 数据模型

> 以下模型已定义于 `backend/src/inkflow/domain/ports/agent_pipeline.py`（领域端口），除 `PipelineConfig` 外均**不再新增**；实现阶段直接引用。

### 2.1 StageStatus 枚举

```python
class StageStatus(StrEnum):
    PENDING   = "pending"    # 待执行
    RUNNING   = "running"    # 执行中
    COMPLETED = "completed"  # 成功
    FAILED    = "failed"     # 失败（重试耗尽）
    SKIPPED   = "skipped"    # 跳过（上游失败且本阶段非必需）
```

### 2.2 AgentRole（Agent 角色定义）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| id | str | — | 角色唯一标识（architect / writer / auditor / reviser） |
| name | str | — | 角色显示名称（"架构师" / "写手" / "审阅" / "修订"） |
| system_prompt | str | — | 系统 Prompt 模板（支持 `{variable}` 占位符） |
| model | str | "openai/gpt-4o" | LLM 模型（LiteLLM 格式：`provider/model_name`） |
| temperature | float | 0.7 | LLM 温度参数，范围 [0.0, 2.0] |
| max_tokens | int? | None | 最大输出 Token 数，None=不限制 |

**角色配置合并优先级**（执行时合并，覆盖不修改模板）:
```
内置模板默认值 < 项目配置 (project.config, F1) < 执行请求 role_overrides
```

### 2.3 PipelineStage（管线阶段定义）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| id | str | — | 阶段唯一标识（outline / chapter_write / style_review ...） |
| name | str | — | 阶段显示名称 |
| agent | AgentRole | — | 该阶段使用的 Agent 角色 |
| input_from | list[str] | [] | 上游阶段 id 列表；空=管线入口阶段 |
| output_to | list[str] | [] | 下游阶段 id 列表；空=管线终点阶段 |
| max_retries | int | 3 | 阶段失败后的最大重试次数 |
| required | bool | True | False 时失败可跳过（下游继续） |

### 2.4 StageResult（单阶段执行结果）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| stage_id | str | — | 阶段 id |
| status | StageStatus | — | 阶段状态 |
| output | str | "" | 阶段输出（传递给下游） |
| error | str | "" | 错误信息（FAILED 时填充） |
| retry_count | int | 0 | 实际重试次数 |
| duration_ms | int | 0 | 阶段耗时（毫秒） |

### 2.5 PipelineResult（管线执行结果）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| stages | list[StageResult] | — | 各阶段结果列表（按执行顺序） |
| final_output | str | "" | 最终阶段输出 |
| status | StageStatus | PENDING | 管线整体状态 |
| total_duration_ms | int | 0 | 管线总耗时（毫秒） |

### 2.6 PipelineContext（管线执行上下文）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| project_id | str | — | 项目 ID |
| chapter_id | str? | None | 当前章节 ID（可选，取决于管线类型） |
| variables | dict[str, str] | {} | 用户变量，Prompt 中可用 `{variable}` 引用 |

> 领域层上下文，与 LangGraph 的 State 解耦；LangGraph 内部 State 由基础设施层自行映射。

### 2.7 PipelineConfig（管线配置 — 本次新增）

> 新增于 `domain/models/agent_pipeline.py`，用于 API 请求体与 YAML 解析后的统一载体（Phase 2 YAML 的领域模型）。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | — | 管线名称（唯一标识，如 builtin:write_chapter） |
| description | str | "" | 描述 |
| stages | list[PipelineStage] | — | 阶段定义列表（≥1） |
| source | Literal["builtin", "yaml"] | "builtin" | 管线来源；Phase 1 仅 builtin |
| version | int | 1 | 配置版本（兼容性演进） |

**业务规则**:
- `stages` 不能为空；阶段 id 全局唯一
- `input_from` / `output_to` 只能引用本管线内存在的阶段 id
- Phase 1 校验规则：有且仅有一个入口阶段（`input_from == []`）、有且仅有一个终点阶段（`output_to == []`）、无环
- 内置模板 `builtin:write_chapter` 在代码中定义，不可被用户修改（Phase 2 起允许复制为 YAML 自定义）

### 2.8 AgentPipelineProtocol（端口）

```python
class AgentPipelineProtocol(Protocol):
    async def execute(self, stages: Sequence[PipelineStage],
                      context: PipelineContext) -> PipelineResult: ...
    def validate(self, stages: Sequence[PipelineStage]) -> list[str]: ...
```

- `validate` 返回错误信息列表，空列表=定义有效（非法引用 / 多入口 / 环 / 空图等）
- `execute` 失败（所有重试耗尽且必需阶段失败）时抛 `PipelineError`（新增领域异常，定义于 ports 文件内）
- 实现方：`infrastructure/agent/langgraph_pipeline.py → LangGraphAgentPipeline`

---

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/agent/pipelines/execute` | 执行管线（异步） | `PipelineExecuteRequest` | 202 + `{execution_id, status}` |
| GET | `/api/v1/agent/pipelines/executions/{execution_id}` | 执行状态/结果 | — | 200 + Execution JSON |
| GET | `/api/v1/agent/pipelines/executions` | 最近执行列表 | Query: `?project_id=&limit=` | 200 + `{items, total}` |
| POST | `/api/v1/agent/pipelines/validate` | 校验管线配置 | `PipelineConfig` | 200 + `{valid, errors}` |
| GET | `/api/v1/agent/pipelines/templates` | 内置模板列表 | — | 200 + `{items}` |

> 执行采用 **202 异步 + 状态轮询** 模式（LLM 调用耗时数秒至数分钟，避免 HTTP 长连接）；SSE 流式推送（PRD"实时显示"）为 Phase 2 增强。

### 3.2 PipelineExecuteRequest（执行请求 DTO）

| 字段 | 类型 | 默认值 | 验证 |
|------|------|--------|------|
| project_id | UUID | **必填** | 必须存在（F1） |
| pipeline | str | "builtin:write_chapter" | 模板 id（Phase 1 仅 builtin:write_chapter） |
| chapter_id | UUID? | None | 如提供必须存在（F2） |
| variables | dict[str, str] | {} | Prompt 模板变量 |
| role_overrides | dict[str, RoleOverride]? | None | 按角色 id 覆盖 model/temperature/prompt（可选） |

**RoleOverride**（内联 DTO）: `{prompt?: str, model?: str, temperature?: float}` — 全部可选，优先级最高。

### 3.3 请求/响应示例

**执行管线**:
```http
POST /api/v1/agent/pipelines/execute
Content-Type: application/json

{
  "project_id": "3f2e1d4a-...",
  "pipeline": "builtin:write_chapter",
  "chapter_id": "9b1c2a3d-...",
  "variables": { "genre": "玄幻", "target_words": "3000" },
  "role_overrides": {
    "writer": { "temperature": 0.9 }
  }
}
```
→ 202
```json
{
  "execution_id": "5e8f2c1a-...",
  "pipeline": "builtin:write_chapter",
  "project_id": "3f2e1d4a-...",
  "status": "pending",
  "created_at": "2026-07-31T10:00:00Z"
}
```

**查询执行状态**:
```http
GET /api/v1/agent/pipelines/executions/5e8f2c1a-...
```
→ 200（执行中）
```json
{
  "execution_id": "5e8f2c1a-...",
  "pipeline": "builtin:write_chapter",
  "project_id": "3f2e1d4a-...",
  "status": "running",
  "current_stage": { "stage_id": "auditor", "status": "running", "retry_count": 1 },
  "stages": [
    { "stage_id": "architect", "status": "completed", "output": "...", "retry_count": 0, "duration_ms": 8320 },
    { "stage_id": "writer",    "status": "completed", "output": "...", "retry_count": 0, "duration_ms": 45120 },
    { "stage_id": "auditor",   "status": "running",   "output": "",     "retry_count": 1, "duration_ms": 12050 }
  ],
  "final_output": "",
  "total_duration_ms": 65840,
  "error": ""
}
```
→ 200（完成）
```json
{
  "execution_id": "5e8f2c1a-...",
  "status": "completed",
  "current_stage": null,
  "stages": [
    { "stage_id": "architect", "status": "completed", "output": "...大纲...", "retry_count": 0, "duration_ms": 8320 },
    { "stage_id": "writer",    "status": "completed", "output": "...正文...", "retry_count": 0, "duration_ms": 45120 },
    { "stage_id": "auditor",   "status": "completed", "output": "...审阅意见...", "retry_count": 1, "duration_ms": 12050 },
    { "stage_id": "reviser",   "status": "completed", "output": "...修订稿...", "retry_count": 0, "duration_ms": 23110 }
  ],
  "final_output": "...修订稿...",
  "total_duration_ms": 88600,
  "error": ""
}
```

**执行列表**:
```http
GET /api/v1/agent/pipelines/executions?project_id=3f2e1d4a-...&limit=10
```
→ 200 `{"items": [ {execution_id, pipeline, status, created_at, total_duration_ms}, ... ], "total": 1}`

**校验管线配置**:
```http
POST /api/v1/agent/pipelines/validate
Content-Type: application/json

{
  "name": "my-dag",
  "stages": [
    { "id": "architect", "name": "架构师", "agent": { "id": "architect", "name": "架构师", "system_prompt": "..." } },
    { "id": "writer", "name": "写手", "agent": { "id": "writer", "name": "写手", "system_prompt": "..." },
      "input_from": ["architect"], "output_to": ["auditor"] }
  ]
}
```
→ 200
```json
{ "valid": true, "errors": [] }
```
→ 200（非法）
```json
{ "valid": false, "errors": ["阶段 'writer' 的 input_from 引用了不存在的上游阶段 'foo'"] }
```

**模板列表**:
```http
GET /api/v1/agent/pipelines/templates
```
→ 200
```json
{
  "items": [{
    "id": "builtin:write_chapter",
    "name": "章节写作 (4 阶段)",
    "description": "Architect → Writer → Auditor → Reviser 标准写作流水线",
    "stages": ["architect", "writer", "auditor", "reviser"],
    "source": "builtin"
  }]
}
```

### 3.4 错误响应格式

```json
// 404 — 项目/章节/执行记录不存在
{"detail": "项目不存在"}
{"detail": "执行记录不存在"}

// 422 — Pydantic 验证失败 (自动生成)
{
  "detail": [{
    "loc": ["body", "role_overrides", "writer", "temperature"],
    "msg": "Input should be less than or equal to 2",
    "type": "greater_than_equal"
  }]
}
```

---

## 4. CLI 命令签名

```bash
inkflow agent run \
    --project-id <id> \
    [--chapter-id <id>] \
    [--pipeline builtin:write_chapter] \
    [--var key=value] ...        # 可重复，注入 Prompt 变量
    [--override role.field=value] ...  # 如 writer.temperature=0.9
    [--watch]                    # 阻塞轮询直到完成，实时打印阶段进度
    [--json]

inkflow agent status \
    --run-id <id> \
    [--json]

inkflow agent validate \
    --file <pipeline.yaml> \     # Phase 1 即支持结构校验（走 Protocol.validate）
    [--json]

inkflow agent template list \
    [--json]
```

### 4.1 输出示例

```bash
# 默认人类可读（--watch）
🚀 管线启动: builtin:write_chapter (项目 #1)
⏳ [1/4] architect  架构师       ... 完成 (8.3s)
⏳ [2/4] writer     写手         ... 完成 (45.1s)
⏳ [3/4] auditor    审阅         ... 重试 1/3 ...
⏳ [3/4] auditor    审阅         ... 完成 (12.1s)
⏳ [4/4] reviser    修订         ... 完成 (23.1s)
✅ 管线完成 (88.6s)

# 失败
❌ 管线失败: 阶段 'writer' 重试 3 次后仍失败: LLM 超时

# --json
inkflow agent run --project-id 1 --json
→ {"execution_id": "5e8f2c1a-...", "status": "pending"}

inkflow agent status --run-id 5e8f2c1a-... --json
→ {"execution_id": "...", "status": "completed", "stages": [...], "final_output": "..."}
```

---

## 5. 管线执行流程与状态机

### 5.1 Phase 1 固定链（builtin:write_chapter）

```
[entry] → architect → writer → auditor → reviser → [END]
```

每个阶段节点内部逻辑:
```
执行节点 (LangGraph node)
  ├── 1. 从 LangGraph State 取出上游输出 + PipelineContext
  ├── 2. 渲染 system_prompt（{variable} 替换，含上游阶段输出）
  ├── 3. 调用 LLM（经 F5 LLMClientProtocol，LiteLLM 格式模型名）
  │      └── LLM 层失败 → F5 自动重试（≤3 次 + 指数退避）
  ├── 4. 逻辑校验输出（非空、格式符合该角色契约）
  │      └── 校验失败 → 阶段级重试（≤ max_retries=3）
  └── 5. 写回 LangGraph State → 传递到下游
```

### 5.2 状态流转

| 当前状态 | 事件 | 下一状态 |
|---------|------|---------|
| pending | 调度器开始执行 | running |
| running | 阶段成功（或重试后成功） | completed |
| running | 重试耗尽且 `required=True` | failed → 管线整体 failed |
| running | 重试耗尽且 `required=False` | skipped → 下游继续 |
| — | 上游 failed/skipped（本阶段未执行） | skipped |

### 5.3 重试与跳过语义

- **重试**: 阶段内 LLM 调用失败或输出校验失败 → 重试，`retry_count` 递增；LLM 层重试（F5）不计入 `retry_count`，仅阶段级重试计入
- **跳过**: `required=False` 阶段失败 → 标记 `skipped`，下游照常执行（下游 Prompt 中该阶段输出为空字符串）
- **必需阶段失败** → 管线立即终止，未执行阶段标记 `skipped`，`PipelineResult.status = failed`，`error` 记录失败原因
- **幂等性**: 同一 `execution_id` 的重复 status 查询无副作用；执行不可重放（Phase 2 checkpoint 恢复）

### 5.4 执行记录存储

- 每次 execute 创建一条执行记录（execution_id, pipeline, project_id, status, created_at, 各阶段 StageResult 快照）
- 阶段状态实时更新（异步任务内写库），CLI/API 轮询读取
- 存储于 SQLite（复用 `core/database.py` 异步引擎），表: `agent_executions` + `agent_stage_results`

---

## 6. 管线模板与 YAML 配置

### 6.1 内置模板

| 模板 id | 阶段链 | 默认角色配置 |
|---------|--------|-------------|
| builtin:write_chapter | architect → writer → auditor → reviser | 内置默认 Prompt；model 取项目配置（`project.config.agent_architect` 等，None 则用 `project.config.model`）；temperature 取项目配置 `project.config.temperature` |

内置模板不可修改/删除；`GET /templates` 返回其元信息（不含完整 Prompt）。

### 6.2 Phase 2 预览: 用户自定义 DAG（YAML）

> 本 spec 仅定义方向与校验约束，**实现排期 Phase 2**。YAML Schema（草案）:

```yaml
name: my-workflow
description: 先写后审，坏则重写
stages:
  - id: outline
    name: 大纲
    agent:
      id: outline_agent
      name: 大纲师
      system_prompt: "为小说《{title}》写大纲"
      model: "openai/gpt-4o"
      temperature: 0.8
    output_to: [draft]
  - id: draft
    name: 初稿
    agent: { id: writer, name: 写手, system_prompt: "...", model: "deepseek/deepseek-chat", temperature: 0.9 }
    input_from: [outline]
    output_to: [review]
  - id: review
    name: 审校
    agent: { id: auditor, name: 审阅, system_prompt: "..." }
    input_from: [draft]
    output_to: [finalize]
  - id: finalize
    name: 定稿
    agent: { id: reviser, name: 修订, system_prompt: "..." }
    input_from: [review]
    required: false        # 审校失败也允许定稿
    max_retries: 2
```

**校验约束（validate 实现，Phase 2 完整启用）**:
- stages ≥ 1；id 全局唯一
- 有且仅有一个入口（`input_from == []`）
- 有且仅有一个终点（`output_to == []`）
- 无环（拓扑排序检测）
- 引用完整（input_from/output_to 均为已定义阶段）
- `temperature ∈ [0, 2]`；`model` 为 `provider/model` 格式（F5 校验）

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| 执行不存在的项目 | 404: "项目不存在" |
| 传 chapter_id 但章节不存在 | 404: "章节不存在" |
| 执行记录不存在 | 404: "执行记录不存在" |
| 模板 id 不存在 | 422: "未知管线模板: xxx" |
| 空 stages | validate → `["管线至少需要一个阶段"]` |
| 阶段 id 重复 | validate → `["阶段 id 重复: xxx"]` |
| input_from 引用不存在阶段 | validate → `["阶段 'x' 引用了不存在的上游阶段 'y'"]` |
| 多个入口阶段 | validate → `["管线必须只有一个入口阶段"]` |
| 无终点阶段 | validate → `["管线必须只有一个终点阶段"]` |
| 存在环（Phase 2 DAG） | validate → `["管线包含循环依赖: a → b → a"]` |
| temperature 超出 [0, 2] | 422: "Input should be less than or equal to 2" |
| model 非 provider/model 格式 | validate → 错误；执行时回退项目默认模型并记 warning |
| 必需阶段重试耗尽 | 管线 failed；`error` 含阶段 id 与原因；未执行阶段 skipped |
| 非必需阶段重试耗尽 | 该阶段 skipped；下游继续（输出为空串） |
| variables 缺 `{placeholder}` 对应键 | 保留占位符原样发送，不阻断执行 |
| role_overrides 指定未知角色 id | 忽略并记 warning（不阻断） |
| LLM 超时/连接错误 | F5 层自动重试；耗尽后阶段级重试；再耗尽按 required 语义处理 |
| 同一项目并发两次 execute | 允许；两条执行记录相互隔离，互不覆盖 |
| 进程中断（daemon 退出） | 执行记录 status=failed, error="执行被中断"；checkpoint 恢复为 Phase 2 |
| 模板列表为空 | 200: `{"items": []}` |
| 执行列表无记录 | 200: `{"items": [], "total": 0}` |

---

## 8. 文件结构

遵循 ADR-007v2 包结构，F4 新增/修改文件：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   └── agent_pipeline.py      ← 新增: PipelineConfig, PipelineExecuteRequest, RoleOverride
│   ├── ports/
│   │   └── agent_pipeline.py      ← 已有: StageStatus/AgentRole/PipelineStage/StageResult/
│   │                                  PipelineResult/PipelineContext/AgentPipelineProtocol
│   │                                  (+ 新增 PipelineError 异常)
│   └── services/
│       └── agent_service.py       ← 新增: AgentService (execute/status/list/validate/templates)
├── infrastructure/agent/
│   ├── langgraph_pipeline.py      ← 新增: LangGraphAgentPipeline (实现 Protocol, StateGraph 4 节点链)
│   ├── pipeline_templates.py      ← 新增: 内置模板 builtin:write_chapter (默认角色 Prompt/参数)
│   ├── pipeline_nodes.py          ← 新增: architect/writer/auditor/reviser 节点逻辑 (渲染 Prompt + 调 F5 + 输出校验)
│   └── execution_store.py         ← 新增: 执行记录 SQLite 仓储 (agent_executions/agent_stage_results)
├── api/
│   └── routers/
│       └── agent.py               ← 新增: 5 个 REST 端点
├── cli/
│   └── commands/
│       └── agent.py               ← 新增: 4 个 CLI 命令 (run/status/validate/template list)
└── core/
    └── database.py                ← 修改: 注册 agent 两张新表 (create_tables)

backend/tests/
├── test_agent_pipeline.py         ← 领域模型 + Protocol.validate 校验逻辑 (Mock 实现)
├── test_agent_service.py          ← AgentService 测试 (Mock AgentPipelineProtocol)
├── test_agent_api.py              ← API 集成测试 (Mock Service)
├── test_langgraph_pipeline.py     ← LangGraph 实现测试 (Mock LLMClient: 顺序/重试/跳过/失败)
└── conftest.py                    ← 修改: fake_llm, sample_pipeline_stages fixtures
```

---

## 9. 测试策略

### 9.1 领域模型测试

| 测试 | 验证点 |
|------|--------|
| `test_agent_role_defaults` | model="openai/gpt-4o", temperature=0.7, max_tokens=None |
| `test_agent_role_temperature_range` | 越界 → ValidationError |
| `test_pipeline_stage_defaults` | input_from/output_to=[], max_retries=3, required=True |
| `test_pipeline_config_empty_stages` | 空 stages → ValidationError |
| `test_pipeline_config_stage_id_duplicate` | 重复 id → validate 错误 |
| `test_stage_result_status` | StageStatus 枚举值完整 (pending/running/completed/failed/skipped) |

### 9.2 校验逻辑测试（Protocol.validate，Mock 实现）

| 测试 | 验证点 |
|------|--------|
| `test_validate_valid_chain` | 4 阶段链 → 空错误列表 |
| `test_validate_empty_stages` | 空 → 1 条错误 |
| `test_validate_unknown_upstream` | 引用不存在 → 错误 |
| `test_validate_multiple_entries` | 2 个入口 → 错误 |
| `test_validate_no_terminal` | 无终点 → 错误 |
| `test_validate_cycle` | a→b→a → 循环错误 |
| `test_validate_bad_model_format` | model 非 provider/model → 错误 |

### 9.3 服务测试（Mock AgentPipelineProtocol）

| 测试 | 验证点 |
|------|--------|
| `test_execute_returns_202_record` | execute → 创建 pending 记录，返回 execution_id |
| `test_execute_project_not_found` | 不存在项目 → 404 异常 |
| `test_execute_unknown_template` | 未知模板 → 422 异常 |
| `test_execute_role_overrides_merged` | 覆盖优先级: 请求 > 项目配置 > 模板默认 |
| `test_status_after_completion` | 完成后 status=completed + stages 快照 |
| `test_list_executions` | 按 project_id 过滤 + 分页 |
| `test_validate_proxies_protocol` | 服务层转发 Protocol.validate 结果 |

### 9.4 API 集成测试（Mock Service）

| 测试 | 验证点 |
|------|--------|
| `test_execute_pipeline` | POST → 202 + execution_id + status=pending |
| `test_execute_missing_project_id` | 缺字段 → 422 |
| `test_get_execution_status` | GET → 200 + status + stages |
| `test_get_execution_not_found` | GET 不存在 → 404 |
| `test_list_executions` | GET → 200 + items + total |
| `test_validate_pipeline` | POST validate → 200 + valid/errors |
| `test_list_templates` | GET templates → 200 + builtin:write_chapter |

### 9.5 LangGraph 实现测试（Mock LLMClient，不联网）

| 测试 | 验证点 |
|------|--------|
| `test_chain_executes_in_order` | architect→writer→auditor→reviser 顺序执行，输出逐级传递 |
| `test_stage_retry_then_success` | 前 2 次失败 → retry_count=2 → completed |
| `test_stage_fail_exhausts_retries` | 重试耗尽 → failed，管线 failed |
| `test_non_required_stage_skipped` | required=False 失败 → skipped，下游继续 |
| `test_required_stage_downstream_skipped` | 必需阶段失败 → 下游全部 skipped |
| `test_prompt_variable_rendering` | {variable} 正确替换（含上游输出注入） |
| `test_pipeline_error_raised` | 整体失败抛 PipelineError |
| `test_duration_recorded` | StageResult/PipelineResult duration_ms > 0 |

### 9.6 测试覆盖率目标

- 领域模型验证: 100% 覆盖所有字段默认值与约束
- validate: 覆盖全部 7 类非法图 + 合法链
- 服务: execute 全分支（成功/404/422/覆盖合并）+ status + list
- API: 覆盖全部 5 个端点 + 典型错误路径
- LangGraph 实现: 覆盖顺序/重试/跳过/失败 4 条主路径（Mock LLM 保证确定性、零成本）

---

## 10. 不在范围内

- ❌ 用户自定义 DAG 执行（Phase 2 — YAML 动态构建 StateGraph，含条件分支/并行）
- ❌ YAML 模板的创建/管理/导入导出 API（Phase 2）
- ❌ SSE 流式进度推送（Phase 2 — Web UI 需要时实现）
- ❌ 执行中断的 checkpoint 恢复（Phase 2 — LangGraph 原生能力，依赖 persistence 设计）
- ❌ 条件分支（add_conditional_edges，如"审校不通过→回写手"循环）与写作循环次数配置（Phase 2）
- ❌ LangSmith 可观测性集成（Phase 2+）
- ❌ 自定义 Agent 角色创建与工具权限（PRD §6.1 F4 — Phase 2+）
- ❌ Agent 配置的 GUI 编辑界面（Phase 2 Web UI）
- ❌ 管线执行历史的统计分析（Phase 3+）
- ❌ 并行阶段执行（多个下游同时运行 — Phase 2 起）

---

## 11. 依赖关系

```text
F4 依赖:
  F1 (project_service)   — 项目配置: project.config.model / agent_architect / agent_writer /
                            agent_auditor / agent_reviser / temperature（角色配置合并）
  F3 (writing_service)   — writer 阶段调用章节生成/修改能力，结果落库到章节
  F5 (llm_service)       — LLMClientProtocol: 实际模型调用、重试、超时、token 计数

F4 被依赖:
  F7 (CLI)               — inkflow write 命令复用 agent run 完成"生成→审校→修订"闭环
  F6 (context_service)   — (规划) 为各阶段 Prompt 注入角色/世界/前文上下文
```

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| 编排引擎 | LangGraph StateGraph (ADR-006v2) | Phase 1 链式 → Phase 2 DAG 只需 add_edge → add_conditional_edges，升级成本低 |
| 领域隔离 | `AgentPipelineProtocol` (typing.Protocol) | 领域层零 LangGraph 依赖；测试注入 Mock 即可；LangGraph API 迭代期（v0.2）需 pin 版本 |
| 执行模型 | 异步任务 + 202 + 状态轮询 | LLM 耗时数秒~分钟，避免长连接；执行记录落 SQLite 支持 CLI/API 查询 |
| 阶段重试 | 每阶段 `max_retries`（默认 3）+ `required` 标志 | 满足 PRD"可跳过/重试任意环节"；LLM 层重试由 F5 负责，两层职责分离 |
| 角色配置合并 | 模板默认 < 项目配置 < 请求 role_overrides | 单次执行可临时调参（如调高 writer 温度），不改项目配置 |
| 内置模板 | 代码内定义 `builtin:write_chapter`，不可修改 | Phase 1 聚焦一条可靠链路；自定义能力随 Phase 2 YAML 开放 |
| 状态存储 | SQLite 复用 core/database.py，两张表 | 与 F1/F2 同库同引擎，无需引入新存储；重启后可查历史执行 |
| YAML 校验 | 复用 Protocol.validate，校验先行 | validate 与 execute 共用同一套规则，杜绝"运行时才发现非法图" |


---

## 附录：f87-langgraph-refactor（原独立 spec，容器化合并）

> 本章节由原 `specs/f87-langgraph-refactor/spec.md` 合并而来（2026-08-29 spec 目录重构）。

# F87: LangGraph 管线状态重构（StateGraph(dict) → TypedDict + reducer）

**Spec 版本**: 1.0
**对应 Issue**: [#87](https://github.com/zhx-xi/InkFlow/issues/87)
**里程碑**: 0.3.1（质量加固补丁）
**类型**: 内部重构（无新用户功能，行为不变）
**分支**: `feat/f87-langgraph-refactor`
**依据**: AGENTS.md §5.1（spec 是唯一真相来源）· ADR-015（LangChain 全家桶，本重构不改变技术选型）· inkflow-dev `references/langchain-langgraph-stack.md` §6.2（方案已实测）
**状态**: ✅ 已实现（PR #110）

## 1. 概述

将 LangGraph Agent 管线的状态管理从 `StateGraph(dict)` 反模式重构为 TypedDict + 嵌套 results dict + reducer：节点只返回增量（partial updates），动态 stage key 收进嵌套 `results` dict。**外部行为（`AgentPipelineProtocol.execute/validate` 契约）完全不变**，仅内部状态表示与节点返回语义变更。

## 2. 背景与问题

2026-08-03 LangGraph 1.x 代码审查（inkflow-dev §6.2 实测）确认：

1. **整体替换语义**：`StateGraph(dict)` 下节点返回的 dict 会**整体替换** state（连初始输入的 key 都会丢失）→ 当前代码被迫让每个节点原地 mutate + 返回完整 state（`pipeline_nodes.py` L57-59 注释准确描述了这一约束）。
2. **全量复制**：每个 super-step 都复制 `context`/`stages`/`llm_client`，无谓开销。
3. **无类型安全**：state 是裸 `dict`，`langgraph_pipeline.py` 有 3 处 `type: ignore[type-var]`（L113×2、L115）+ 1 处 `type: ignore[attr-defined]`（L158）。
4. **并行定时炸弹**：注释声明「并行执行属 Phase 2」——一旦 Phase 2 并行，两个节点同时返回完整 dict 必然互相覆盖（last-write-wins），且丢失彼此写入。

## 3. 目标状态设计（已实测跑通，inkflow-dev §6.2）

### 3.1 PipelineState TypedDict

```python
class PipelineState(TypedDict):
    context: PipelineContext
    stages: dict[str, PipelineStage]
    llm_client: LLMClientProtocol
    _abort: NotRequired[bool]
    results: Annotated[dict[str, StageResult], operator.or_]  # 动态 stage key 收进嵌套 dict
```

- 动态 stage key（`{stage_id}_output/_status/...`）无法静态表达 → 用嵌套 `results: dict[str, StageResult]` 承载，`Annotated[..., operator.or_]` 声明合并 reducer。
- `_abort` 保持普通字段（覆盖语义）：节点**只置 True、从不置 False**，last-write-wins 安全（任一节点置 True 后全局生效，后续节点读到即跳过）。

### 3.2 节点增量返回（pipeline_nodes.py）

节点只返回增量，不再 mutate + 返回完整 state：

```python
async def architect_node(state: PipelineState) -> dict:
    return {"results": {stage_id: StageResult(...)}}   # 只返回增量

# 失败路径额外带 _abort：
return {"_abort": True, "results": {stage_id: StageResult(status=FAILED, ...)}}
```

各返回路径的 `results` 内容（与现状逐字段等价）：

| 路径 | results 内容 |
|------|-------------|
| 成功（第 N 次尝试） | `StageResult(stage_id, COMPLETED, output=响应, retry_count=N-1)` |
| 重试耗尽 required | `_abort: True` + `StageResult(stage_id, FAILED, error=最后错误, retry_count=max_retries)` |
| 重试耗尽非 required | `StageResult(stage_id, SKIPPED, error=最后错误, retry_count=max_retries)` |
| 上游已 abort（跳过） | `StageResult(stage_id, SKIPPED)`（不调用 LLM，output/error 为空） |

- `_build_messages` 读取上游输出改为 `state["results"][key].output`（与旧 `state.get(f"{key}_output", "")` 等价：skipped 上游的 StageResult.output 默认 `""`）。
- 节点函数签名 `state: PipelineState`，返回 `dict`（LangGraph 接受 TypedDict partial）。

### 3.3 execute 汇总逻辑（langgraph_pipeline.py）

- `workflow = StateGraph(PipelineState)`，消除全部 `type: ignore[type-var]`。
- 结果汇总从 `results` dict 读：

```python
stage_results = [
    final_state["results"].get(
        stage.id,
        StageResult(stage_id=stage.id, status=StageStatus.COMPLETED),
    )
    for stage in stages
]
```

`.get` 默认 COMPLETED 与旧 `final_state.get(f"{stage_id}_status", StageStatus.COMPLETED.value)` 语义等价（线性链中每个节点必被执行，results 均已有记录，默认值仅防御）。

- `final_output` 从 `final_state["results"][terminal.id].output` 读。
- **PipelineError.result 类型声明**：`domain/ports/agent_pipeline.py` 的 `PipelineError` 增加类属性 `result: PipelineResult | None = None`（纯类型声明，零运行时行为变化，向后兼容），消除 `type: ignore[attr-defined]`（L158）。

## 4. 行为不变约束（黑盒契约）

重构前后 `LangGraphAgentPipeline.execute()` / `validate()` 的**外部可观察行为必须逐项一致**（由既有测试锁定）：

1. 顺序执行：architect → writer → auditor → reviser 线性链、调用顺序、model/temperature 透传
2. 输出传递：下游收到上游输出（`{architect_output}` 等变量渲染、user 消息拼接格式不变）
3. validate：空图 / 重复 id / 多入口 / 多终点 / 非法上游引用 / 环检测，错误文案不变
4. 重试：max_retries 语义、retry_count 值不变
5. 跳过：required=False 失败 → skipped 下游继续；required=True 失败 → 下游全 skipped、LLM 调用计数不变
6. 失败传播：`PipelineError` 抛出时机、消息文案（含阶段 id）、`error.result` 携带的 PipelineResult 内容不变
7. 结果汇总字段：`status`/`output`/`error`/`retry_count` 逐字段等价（skipped 阶段 output="" 不变）

## 5. 文件变更

| 文件 | 动作 | 说明 |
|------|------|------|
| `backend/src/inkflow/infrastructure/agent/pipeline_nodes.py` | MODIFY | 节点改为增量返回，删除原地 mutate 与全量返回 |
| `backend/src/inkflow/infrastructure/agent/langgraph_pipeline.py` | MODIFY | PipelineState 定义 + StateGraph(PipelineState) + results 汇总 + 消除 type: ignore |
| `backend/src/inkflow/domain/ports/agent_pipeline.py` | MODIFY | PipelineError 加 `result: PipelineResult \| None = None` 类属性（纯类型声明） |
| `backend/tests/unit/test_pipeline_nodes.py` | **NEW** | 节点增量契约测试（RED 载体） |
| `backend/tests/unit/test_langgraph_pipeline.py` | 不改 | 既有黑盒契约测试，行为不变基线 |
| `specs/f4-pipeline-engine/spec.md` | NEW | 本 spec（同 PR 合入） |

## 6. 测试策略

### 6.1 既有测试（行为不变基线）

`backend/tests/unit/test_langgraph_pipeline.py` 10 个测试**一字不改**：全部经 `execute()` 黑盒断言，重构前后都必须全绿——它们是行为不变的证明。

### 6.2 新增节点契约测试（RED 载体）

`backend/tests/unit/test_pipeline_nodes.py`（新建，unit 目录自动进 CI）：

| 用例 | 断言 |
|------|------|
| 正常节点返回增量 | 直接调用 `architect_node(state)` → 返回值**只含 `results` 键**（不含 `context`/`stages`/`llm_client`）；`results[stage_id].output/status` 正确 |
| 失败路径 | 重试耗尽 required → 返回含 `_abort: True` + `results[stage_id]` FAILED + retry_count=max_retries |
| abort 跳过路径 | `_abort` 已置 → 返回 `results[stage_id]` SKIPPED，**不调用 LLM** |
| 并行合并语义 | 两个节点增量 dict 的 `results` 经 `operator.or_` 合并后两 stage key 并存（锁并行安全前提） |

### 6.3 RED 形态

当前实现（节点返回完整 state）下，新测试断言「只含 results 键」必然失败（返回值含 context/stages/llm_client）→ **AssertionError 类失败**（非收集期错误），同时既有 10 个测试保持全绿。

## 7. 验收标准

1. **测试先行（F15 规矩）**：先写新测试并确认 RED FAIL（新测试失败、既有测试全绿），再实现
2. `pytest backend/tests/unit/test_langgraph_pipeline.py backend/tests/unit/test_pipeline_nodes.py` 全绿
3. `langgraph_pipeline.py` / `pipeline_nodes.py` 中无 `type: ignore`（0 处）
4. 行为不变：§4 全部 7 项由既有黑盒测试证明（重构前后同绿）
5. 不做 Phase 2 并行（本 Issue 只做状态机制重构，并行留待后续）
6. 全量回归：backend 单元 + 顶层集成/CLI 测试全绿（CI 等价命令）

## 8. 不在范围

- Phase 2 并行执行（节点并发）
- LangGraph RetryPolicy 替换手写重试（inkflow-dev §6.4：业务语义是状态机，仍需节点内处理）
- langchain-community sunset 迁移（§6.3，单独 ADR 记录）
- 新增/修改任何用户可见 API、CLI、配置

## 9. 依赖关系

- ADR-015：LangChain 全家桶选型（本重构遵守，不引入新依赖）
- inkflow-dev §6.2：方案已实测（TypedDict + reducer 跑通）
- 无跨模块行为依赖；`domain/ports/agent_pipeline.py` 仅类型声明改动，向后兼容
## 13. 动作确认

> 基于 §3 API + §4 CLI + §7 边界事实的状态流表，不新增行为。本节属于主 spec（§1-§12）；其后「附录：f87-langgraph-refactor」为容器化合并的独立 spec，不在本节范围。

### 13.1 端点状态流

| 端点 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| POST /api/v1/agent/pipelines/execute | 项目存在；chapter_id 提供则须存在 | 校验 DTO → 创建执行记录 → 异步调度 | 202 + {execution_id, status: pending} | 404「项目不存在/章节不存在」；422（缺字段、未知模板「未知管线模板: xxx」、temperature 越界） | 202 异步 + 状态轮询；同项目并发 execute 允许，执行记录相互隔离 |
| GET /api/v1/agent/pipelines/executions/{execution_id} | 执行记录存在 | 读执行状态/结果 | 200 + Execution JSON（pending/running/completed/failed + stages 快照） | 404「执行记录不存在」 | 重复查询无副作用（幂等）；执行不可重放 |
| GET /api/v1/agent/pipelines/executions?project_id=&limit= | 无 | 最近执行列表 | 200 + {items, total} | — | 无记录 → {items: [], total: 0} |
| POST /api/v1/agent/pipelines/validate | 无 | Protocol.validate 结构校验 | 200 + {valid: true, errors: []} | 422（Pydantic） | 非法图 → {valid: false, errors: [...]}（空 stages/重复 id/多入口/无终点/环/非法引用） |
| GET /api/v1/agent/pipelines/templates | 无 | 内置模板列表 | 200 + {items} | — | 空 → {items: []}；内置模板不可修改/删除 |

### 13.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow agent run --project-id [--chapter-id --pipeline --var key=value --override role.field=value --watch --json] | 项目存在 | 创建执行 → 轮询至完成 | 🚀 管线启动 → ⏳ 各阶段进度 → ✅ 管线完成 (88.6s) / --json {execution_id, status} | 404/422 → 退出码 1；失败 → ❌ 管线失败: 阶段 'writer' 重试 3 次后仍失败: LLM 超时 | --watch 阻塞轮询；--var / --override 可重复 |
| inkflow agent status --run-id [--json] | 执行记录存在 | 查询状态/结果 | 人类可读 / --json Execution JSON | 404「执行记录不存在」 → 退出码 1 | — |
| inkflow agent validate --file <pipeline.yaml> [--json] | 无 | 结构校验（走 Protocol.validate） | 校验结果 / --json | 422 → 退出码 1 | Phase 1 即支持 |
| inkflow agent template list [--json] | 无 | 列出内置模板 | {items} / --json | — | — |

### 13.3 验收锚点

- A1：POST execute → 202 + status=pending（异步模式，非 200 长连接）
- A2：必需阶段重试耗尽 → 管线 failed + 未执行阶段全 skipped（error 含阶段 id 与原因）
- A3：非必需阶段（required=False）重试耗尽 → 该阶段 skipped + 下游继续（输出为空串）
- A4：执行记录不存在 → 404「执行记录不存在」
- A5：未知模板 id → 422「未知管线模板: xxx」
- A6：validate 非法图（input_from 引用不存在阶段）→ {valid: false, errors: [...]}，文案与 §7 一致
