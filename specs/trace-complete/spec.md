# AI 执行链路可重放补全（#615）

> **Spec（0.12.0，2026-08-23）**：在 `#599`（统一执行视图）基础上补齐「**chat 会话可重放**」缺口——chat 流式对话（`/api/v1/chat/agent/stream`，走 deepagents ReAct）落 `run_id + steps`（含工具调用 args/result），复用 F27 `agent_runs` 表，使对话后可回看 agent 内部步骤与工具调用链路。
>
> 依赖：`#597`（chat 接 deepagents）+ `#599`（unified-exec-view，前端已支持 runId 渲染）已合入；F27 `AgentRun/AgentStep/AgentToolCall` 模型与 `GET /api/v1/agent/runs/{id}` 已存在。
>
> ## 拍板记录（2026-08-23，用户拍板 A：继续 #615）
>
> | 决策 | 结论 | 说明 |
> |------|------|------|
> | D1 run 落库方式 | **A：复用 `agent_runs` 表 + `AgentRun` 模型**（`mode="chat"`） | 零迁移（表已存在）；与 agentic run 同表、按 `mode` 区分；GET `/agent/runs/{id}` 直接复用——不新建 ChatRun 表（避免「第二次造执行实体」）。 |
> | D2 steps 构造 | 从 `astream_events v2` 收集 `on_chat_model_end`（完整 AIMessage）+ `on_tool_end`（ToolMessage）→ 组装 `AgentStep` | 镜像 F27 `_build_steps`（每条 AI 消息一个 step，tool_calls 按 tool_call_id 回填 result）。 |
> | D3 管线 trace | **不补 tool_calls**（管线单次 LLM，无工具，已核实 `pipeline_nodes._call_llm_node`）→ 范围外 | 管线 trace `tool_calls=[]` 是正确反映（非缺陷）；「推理可重放增强」（reasoning 记 prompt）列为后续增值项。 |

---

## 1. 现状与分析（源码实锤，2026-08-23）

| 链路 | 轨迹现状 | 数据源 | 缺口 |
|------|----------|--------|------|
| **chat 流式**（`/chat/agent/stream`，#597） | `chat_agent_service.stream_events` 只把事件转成 SSE 帧，**不持久化** | 无 run 记录 | **核心缺口**：对话后无 run_id 可回看 |
| **管线**（agent_executions，#599） | `pipeline_nodes._call_llm_node` **单次 LLM 调用**（`llm.chat` → `StageResult.output`），非 ReAct | `stages` + `trace`（`tool_calls=[]`）| 无工具调用（正确），trace reasoning 仅阶段输出 |
| **agentic**（agent_runs，#599/F27） | `AgentRun.steps`（含 tool_calls args/result）已完备 | `GET /agent/runs/{id}` | 无 |

- **管线无 tool_calls 是结论**：`backend/src/inkflow/infrastructure/agent/pipeline_nodes.py` L91-141 `_call_llm_node` = 单次 `llm.chat(messages)` 返回文本，无工具；故「补管线 tool_calls」是**伪缺口**，取消。
- **agent_runs 可复用**：`backend/src/inkflow/infrastructure/database/models/agent_run.py` `AgentRunORM`（agent_runs 表）含 `id/project_id/chapter_id/mode/steps(JSON)/final_content/model/token_usage_total/status`；`mode` String(20) 足够加 `"chat"`。

## 2. 需求定义

- **目标**：`/chat/agent/stream` 每次对话（一次用户 prompt → 一次 agent 执行）落一个 `AgentRun(mode="chat")`，steps 含每步 assistant 文本 + 该步工具调用（`tool_name/arguments/result/is_error`），供 `GET /api/v1/agent/runs/{id}` 回看 + 前端 #599 runId 渲染。
- **非目标**：
  - 不建新表 / 不迁移（复用 agent_runs）。
  - 不重构 SSE 帧协议（`_encode_frame` 不变）。
  - 管线 trace 增强（reasoning 记 prompt）——范围外，后续增值项。

## 3. 设计

### 3.1 steps 收集（`ChatAgentService.stream_events` 增持久化收集）

`stream_events(prompt, chapter_context)` 当前转发 `on_chat_model_stream / on_tool_start / on_tool_end` 为帧。**新增**收集：

- **assistant 消息**：`on_chat_model_end`（`run_type="llm"`）携带完整 `AIMessage`（`.content`/`.tool_calls`/`.response_metadata.usage.total_tokens`）→ 一条 `AgentStep`。
- **工具结果**：`on_tool_end` 携带 `ToolMessage`（`.name`/`.tool_call_id`/`.content`）→ 注入对应 step 的 `AgentToolCall.result`（按 `tool_call_id` 匹配），`is_error` = `'\"ok\": false' in result`。
- 最终 `AgentStep.message_content` = 该 step 的 AIMessage 文本（空 = 只调工具）；`tool_calls` = 该 AIMessage 的 tool_calls 列表（`tool_name/arguments dict/result`）。

收集器在 `stream_events` 内以「累积列表」形态维护；流结束后返回 `(steps, final_content, token_usage_total)` 供端点写回。

### 3.2 端点接线（`chat_stream.py` `stream_chat_agent`）

- 端点前置：`get_agent_run_repo` 注入（`deps.py` 已有）→ `repo.create(project_id, chapter_id, mode="chat")` 取 `run_id`。
- 流式：`svc.stream_events(...)` yield 帧；同时（或结束后）用收集到的 steps 构造终态 AgentRun。
- 流结束时（done 帧）：`repo.save(run)`（status=completed，steps，final_content=最后 assistant 文本，token_usage_total，model，terminated_by="llm"）。异常 → failed。
- **run_id 回传**：SSE `done` 帧扩展含 `run_id`（`{"type":"done","done":true,"run_id":<id>}`），供前端 #599 存 run_id → 点开详情。

### 3.3 value 复用

- `AgentRun` / `AgentStep` / `AgentToolCall` 领域模型（`domain/models/agent_run.py`）直接复用，不新建。
- `SQLiteAgentRunRepository`（`infrastructure/database/repositories/agent_run_repo.py`）`create/save` 复用。
- `GET /api/v1/agent/runs/{id}`（`agent_runs.py`）复用，`mode="chat"` 的 run 同样可查。

## 4. 测试策略（RED 契约 → GREEN）

### 4.1 单元测试

- **steps 收集**：mock `astream_events v2` 事件序列（`on_chat_model_end` AIMessage 含 tool_calls + 后续 `on_tool_end` ToolMessage）→ 断言 `ChatAgentService` 收集出 `steps`（step.message_content / tool_calls[].tool_name/arguments/result/is_error / tokens）。
- **端点落 run**：`stream_chat_agent` 流式 → mock `get_agent_run_repo` 断言 `repo.create`（mode="chat"）+ `repo.save`（status/steps/final_content）被调 + done 帧含 run_id。
- **回复用**：`test_chat_agent_stream.py` 追加用例（mock 事件收集）。

### 4.2 边界

| 边界 | 行为 |
|------|------|
| 流无 assistant 文本（只调工具）| step.message_content=""，工具调用仍记录 |
| 工具调用无对应 result | `result=""`（防御），`is_error=False` |
| LLM 异常 | run status=failed（repo.save），SSE 错误帧 |
| token_usage_total 缺失 | 0（response_metadata.usage 缺省） |

## 5. 范围外声明

- **管线 trace tool_calls 补全**：不实施（管线单次 LLM 无工具，已核实——伪缺口）。
- **管线 trace reasoning 记 prompt**：范围外，后续增值项（需改 pipeline_nodes 透传 LLM 输入）。
- **前端渲染**：`#599` 已实现 runId 渲染，本 issue 仅确保 run 落库 + run_id 回传（前端无需改动）。

## 6. 文件结构

| 文件 | 变更 |
|------|------|
| `backend/src/inkflow/infrastructure/agent/chat_agent_service.py` | MODIFY（stream_events 增 steps 收集 + 返回终态；注入 run_repo 可选）|
| `backend/src/inkflow/api/routers/chat_stream.py` | MODIFY（stream_chat_agent 前置 create + 结束 save + done 帧带 run_id）|
| `backend/src/inkflow/api/deps.py` | MODIFY（复用 get_agent_run_repo；stream_chat_agent 装配）|
| `backend/tests/unit/test_chat_agent_stream.py` | MODIFY（追加可重放收集/落库用例）|

## 7. 门禁

- **M0**：spec + ADR-041 定稿合入。
- **M1**：RED 契约 confirm FAIL。
- **M2**：GREEN + 后端 `pytest tests/unit/ ../tests/` + `ruff` + `mypy` 全绿。
- **M3**：PR merged（body `Closes #615`）+ #615 CLOSED + worktree 清理。
