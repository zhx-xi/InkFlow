# F47 写作页底部 AI 聊天框 + AI 执行详情页（#379）
> **端**: cross

> **Spec 变更**（v1.0 → v1.1，2026-08-23，#597 增量）：本版将聊天框从「纯 LLM 对话 + 意图解析」（#541 streamChat，单轮对话、无工具）升级为 **ChatPanel 驱动 deepagents 系统级 Agent**（#551 C1，拍板 D8=A）——消息发出后走 deepagents agent loop（system agent 全量暴露工具），流式返回「工具调用 + 结果 + 最终回复」；同时**删除侧边栏 `nav.book` 书级编排入口**（拍板 D11=A），`/book` 路由与 BookPlannerPanel 保留（F44 编排能力迁移为对话内触发的全自动编排流程，非物理删除）。本增量明确新增后端 chat agent 端点 + SSE 帧协议扩展（见 §14）。

> **Spec 变更**（v1.1 → v1.2，2026-08-29，#762-#765 增量）：将对话/写作会话提升为全局一等对象——左侧新增与「设定库」同级的独立**会话栏**（#762，取代 #752 会话入设定库栏 + 折叠/展开）；续写/生成按钮改为**创建新会话**而非页脚内联进度条（#763）；移除右栏「草稿审批」面板（审批/保存收敛到章节页顶部按钮，右栏只留上下文注入，D3，#764）；右栏折叠按钮移到左缘 +「折叠」提示（#765）。详见 §15。

## 1. 概述

写作页底部横栏从被动状态条改造为 **AI 聊天框**（可与 AI 对话，结果经用户确认落章），
工具栏新增**视图切换按钮**（正文编辑 ↔ AI 执行详情）。详情页展示执行过程的
**思维链（reasoning）+ 工具调用（tool_calls）+ 子 agent 路由（supervisor 决策）+ 各阶段输出 + 最终回复**。

文章落章流程不变（F27 save_draft → confirm → final 既有流；聊天/详情是旁路观察层，不替代正文编辑）。

### 1.1 与既有模块的边界

- **复用**：`executePipeline` / `getExecutionStatus` / `confirmExecution`（api/pipeline.ts）全链路；
  `agent_executions` 表（stages 快照 + relations 快照）；`usePipeline` 轮询模式（#298 管线化后 GUI 主路径）。
- **修正任务书认知**：任务书称「聊天框流式复用 SSE」。实测 GUI 管线化（#298）后主路径为
  **execute 202 → 轮询**（usePipeline 1s 间隔），SSE 端点（F23 `/writing/{id}/stream`）是旧单 LLM 流式、
  与管线无关。**本 spec 决策：聊天框复用现有轮询链路**（零后端新流式端点）；SSE 流式增强列为范围外。
- **修正任务书认知 2**：任务书称「agentic 决策轨迹已记录，只缺暴露端点」。实测 GUI 管线角色节点
  （`pipeline_nodes._call_llm_node`）为**单次 LLM 调用**（无 deepagents ReAct、无 tool_calls），
  supervisor 决策只存在内存 `route_history` 不落库；F27 agentic 轨迹在 `agent_runs` 表（GUI 无入口）。
  故**详情页 trace 数据需后端新增捕获**（D1=A 拍板），非仅暴露端点。

### 1.2 拍板记录（2026-08-16，用户全选 A）

| 决策 | 结论 |
|------|------|
| D1 轨迹数据源 | A：后端新增捕获（角色节点 reasoning + supervisor 决策 → `trace` JSON 列落库） |
| D2 聊天后端形态 | A：新增 `builtin:chat` 单轮对话管线（复用 execute/executions 全链路） |
| D3 落章交互 | A：聊天结果生成后显示「插入正文」按钮 → setContent 编辑器 → 用户保存（F27 既有 save 流） |
| D4 视图切换 | A：同一路由内 state 切换（工具栏 toggle：editor-view ↔ detail-view） |
| D5 E2E | A：新增确定性 E2E（page.route 拦截，零真实 LLM） |

## 2. 数据模型

### 2.1 trace 轨迹（`agent_executions.trace` 新列）

```
AgentExecutionORM.trace: LenientJSON(fallback=[])   # 新增列，默认 []
```

单条 TraceEntry 结构：

```json
{
  "node": "architect",          // 节点/阶段 id；supervisor 决策 = "supervisor"
  "type": "stage" | "decision", // stage=角色节点执行；decision=supervisor 路由决策
  "reasoning": "LLM 推理文本",   // 角色节点=AIMessage content；decision=决策 JSON 原文
  "tool_calls": [],             // 工具调用列表（当前管线角色节点无工具，恒 [] 占位；F27 agentic 未来可接）
  "output": "阶段输出摘要",      // stage 类型填阶段 output（前 500 字符截断）；decision 类型空串
  "duration_ms": 123,           // stage 类型填阶段耗时；decision 填决策调用耗时
  "ts": "2026-08-16T10:00:00Z"  // UTC ISO 时间
}
```

### 2.2 builtin:chat 管线模板（pipeline_templates.py 新增）

```
BUILTIN_TEMPLATES["builtin:chat"] = PipelineConfig(
    name="AI 对话 (1 阶段)",
    stages=[PipelineStage(id="chat", name="对话助手", agent=AgentRole(
        id="chat",
        name="对话助手",
        system_prompt=<对话系统提示：小说创作助手，结合设定库与上下文回答用户提问>,
        model=config.llm_default_model,
    ))],
    source="builtin",
)
```

- 输入 variables：`prompt`（必填，用户对话文本）、可选 `chapter_context`（当前章正文/前文，由前端拼接传入）。
- 输出：`final_output` = LLM 回复文本。
- 单阶段、无工具循环（v1 范围；工具增强挂后续 issue）。
- `_run_pipeline` 的设定注入（#366 G1）对 chat 同样生效（角色/世界观/大纲摘要进 `variables.setting`），
  对话助手可感知项目设定。

### 2.3 PipelineResult 扩展

```
PipelineResult.trace: list[dict] = []   # 执行过程 trace 条目（pipeline 内收集，随 result 返回）
```

LangGraph pipeline（supervisor/generic）在 State 增加 `trace` 通道，执行过程中各节点 append
TraceEntry；`execute()` 返回时随 `PipelineResult` 带出。

## 3. API 契约

### 3.1 GET /api/v1/agent/pipelines/executions/{execution_id}（扩展）

响应在既有字段基础上新增：

```json
{
  "execution_id": "...",
  "pipeline": "builtin:write_auto",
  "status": "completed",
  "stages": [...],          // 既有
  "relations": [...],       // 既有
  "trace": [...],           // 新增：TraceEntry[]，无轨迹时 []
  "final_output": "...",
  "total_duration_ms": 1200,
  "error": "",
  "hitl_pending": null
}
```

### 3.2 POST /api/v1/agent/pipelines/execute（扩展）

- `pipeline` 字段接受 `"builtin:chat"`（既有 schema 无需变更，chat 为新模板注册）。
- `variables` 支持 `prompt` / `chapter_context`。
- 其余语义不变（202 + execution_id，后台 fire-and-forget）。

### 3.3 无 CLI 变更

聊天/详情均为 GUI 观察层；CLI `agent status --json` 已可见 stages/relations，trace 不新增 CLI 输出（范围外）。

## 4. 前端契约

### 4.1 底部聊天框（ChatPanel，子任务 1）

- 组件 `components/ChatPanel.tsx`，渲染于写作页底部横栏（替代原 PipelineStatus 区域布局，
  `statusbar` 精简信息行保留）。
- testid：`chat-panel` / `chat-input` / `chat-send` / `chat-msg-user-<n>` / `chat-msg-ai-<n>` /
  `chat-insert-<n>`（插入正文按钮）。
- 行为：
  - 发送 → `executePipeline({pipeline:'builtin:chat', project_id, variables:{prompt, chapter_context}})`
    → 轮询 `getExecutionStatus`（复用 usePipeline 模式，或 ChatPanel 内部独立轮询）→
    `status==='completed'` → assistant 消息展示 `final_output` + 「插入正文」按钮。
  - 插入正文 → `chapterStore.setContent(final_output)` + toast 提示（不自动保存；用户按 Ctrl+S 或保存按钮落盘，F27 既有 save 流）。
  - 失败 → 消息区显示错误（不崩溃）。
  - 并发保护：发送中再次发送无操作（inFlight 守卫）。
- **与现有管线的交互**：聊天框独立于「生成/续写」管线（各自 inFlight）；聊天执行记录同样落
  `agent_executions`（pipeline=builtin:chat），详情页可查看。

### 4.2 工具栏切换按钮（子任务 2）

- `EditorToolbar` 右侧新增切换按钮：testid `view-toggle`，aria-label 按当前视图
  （`write.view.toDetail` / `write.view.toEditor`），图标 lucide `ListRestart` 或 `Eye`/`Pencil`。
- 视图 state 在 WritingPage：`view: 'editor' | 'detail'`，默认 `'editor'`。
- 切换后主编辑区渲染：editor-view → `ChapterEditor`（既有）；detail-view → `ExecutionDetailPanel`。

### 4.3 AI 执行详情页（ExecutionDetailPanel，子任务 2）

- 组件 `components/ExecutionDetailPanel.tsx`，数据源 `GET /api/v1/agent/pipelines/executions/{id}`
  （当前执行记录 id 由 usePipeline/chat 执行 id 提供；无执行记录 → 空态）。
- testid：`exec-detail` / `exec-detail-stages` / `exec-detail-stage-<stage_id>` /
  `exec-detail-trace` / `exec-detail-trace-<n>` / `exec-detail-relations` / `exec-detail-final` /
  `exec-detail-empty`。
- 展示：
  - **stages**：每阶段 status/output/error/retry_count/duration_ms（stage 卡）。
  - **trace**：每条目 node/type/reasoning/tool_calls/output/duration_ms（决策与阶段分色）。
  - **relations**：agent 边 + gate_result（F46 数据）。
  - **最终回复**：final_output + total_duration_ms。
- 详情页数据与聊天框共用同一 execution 记录：聊天执行 → 详情页展示该次 chat 的 trace/stages。

### 4.4 i18n 新增 key（zh.ts / en.ts 同步）

```
write.chat.placeholder      // 与 AI 对话，如「帮我写一段打斗场景」
write.chat.send             // 发送
write.chat.insert           // 插入正文
write.chat.inserted         // 已插入正文，按 Ctrl+S 保存
write.chat.failed           // 对话失败: {message}
write.view.toDetail         // 查看 AI 执行详情
write.view.toEditor         // 返回正文编辑
write.detail.empty          // 暂无执行记录
write.detail.stages         // 各阶段输出
write.detail.trace          // 思维链 / 工具调用
write.detail.relations      // Agent 关系
write.detail.final          // 最终回复
write.detail.unknown        // 未知
```

## 5. 边界与错误表

| 场景 | 行为 |
|------|------|
| chat 无 prompt（空发送） | 前端禁用发送按钮（非空才可点）；后端 `variables.prompt` 缺省 → 422（复用 PipelineExecuteRequest 校验） |
| chat 管线执行失败 | 消息区显示 `write.chat.failed`，不插入正文 |
| 插入正文时无章节选中 | 按钮禁用（currentChapterId 为空） |
| 详情页无执行记录 | `exec-detail-empty` 空态提示 |
| trace 列缺失（旧库未迁移） | 幂等迁移 `ensure_agent_executions_trace_column`（app.py lifespan 注册）；`getattr(execution,'trace',[])` 防御 |
| supervisor 管线无决策（静态模式） | trace 仅含 stage 条目；decision 条目仅在 supervisor 模式产生 |
| 聊天执行与生成/续写并发 | 各自 inFlight 独立（聊天不影响生成，反之亦然） |

## 6. 测试策略

### 6.1 后端 RED 契约（pytest）

- `test_agent_trace.py`：`update_stages` 带 trace 参数落库；`get_status` 返回 trace；
  ORM 列缺省 `[]`；迁移函数三形态（旧库补列/新库 no-op/无表 no-op）。
- `test_chat_pipeline.py`：`BUILTIN_TEMPLATES["builtin:chat"]` 单阶段模板存在；
  chat 模板执行（FakeLLM）→ final_output=LLM 回复；trace 含 chat 节点 reasoning。
- `test_pipeline_execute_chat.py`（API 层）：POST execute pipeline=builtin:chat → 202 +
  execution_id；轮询 get_status → completed + final_output + trace 非空。
- supervisor trace：supervisor 模式执行（FakeLLM 决策）→ trace 含 decision 条目。

### 6.2 前端 RED 契约（Vitest + RTL）

- `ChatPanel.test.tsx`：发送 → executePipeline(builtin:chat, {prompt, chapter_context}) →
  轮询 completed → assistant 消息 + 插入正文按钮；插入 → setContent + toast；
  失败 → 错误消息；发送中并发保护；空输入禁用发送。
- `ExecutionDetailPanel.test.tsx`：mock `GET /pipelines/executions/{id}` 返回
  stages/trace/relations/final → 各区块渲染；空态；加载态。
- `EditorToolbar.test.tsx`（升级）：view-toggle 按钮存在 + 点击回调。
- `writing.test.tsx`（升级）：默认 editor-view；点 toggle → detail-view（渲染
  ExecutionDetailPanel）；切换回 editor-view → ChapterEditor 恢复。

### 6.3 E2E（确定性，page.route 拦截）

- 新 spec `e2e-writer-chat.spec.ts`（追加 e2e-writing 或新文件，视 900 行护栏）：
  - 聊天框渲染 + 输入 + 发送 → assistant 消息（page.route 拦截 execute 202 + 轮询 completed）。
  - 插入正文 → 编辑器 value 更新。
  - 切换按钮 → 详情页渲染（route 返回预置 stages/trace）。
  - 零真实 LLM（全部 route 拦截），CI 稳定。
- 既有 `e2e-writing.spec.ts` 的 `pipeline-status` / `statusbar` testid 契约若被改造影响 → 同步升级。

## 7. 范围外声明

- **SSE 流式聊天**：本 spec 聊天走轮询（见 §1.1 决策）；流式体验增强挂后续 issue。
- **F27 agentic 工具循环接入 GUI**：`agent_runs` 轨迹不与 `agent_executions.trace` 合并；
  GUI 管线仍为单次 LLM 角色节点；tool_calls 恒 `[]`（占位契约），agentic 工具循环接入挂后续。
- **MCP / F44 卷级编排 / f41/f40/f39 多 Agent**：详情页只展示任意执行记录轨迹，不新增执行端能力。
- **CLI 输出 trace**：不新增（§3.3）。
- **聊天记忆 / F28 偏好学习**：聊天历史不持久化（刷新即清），F28 事件源接入挂后续。

## 8. 文件结构

### 8.1 后端（PR 1 + PR 2）

| 文件 | 变更 |
|------|------|
| `backend/src/inkflow/infrastructure/agent/pipeline_templates.py` | MODIFY：新增 `_build_chat_template()` + `BUILTIN_TEMPLATES["builtin:chat"]`（PR 1） |
| `backend/src/inkflow/infrastructure/database/models/agent.py` | MODIFY：`AgentExecutionORM.trace` 列（PR 2） |
| `backend/src/inkflow/core/database.py` | MODIFY：`ensure_agent_executions_trace_column` 幂等迁移（PR 2） |
| `backend/src/inkflow/app.py` | MODIFY：lifespan 注册迁移（PR 2） |
| `backend/src/inkflow/domain/models/agent_pipeline.py` | MODIFY：`PipelineResult.trace` 字段（PR 2） |
| `backend/src/inkflow/infrastructure/agent/pipeline_nodes.py` | MODIFY：`_call_llm_node` 收集 stage trace（PR 2） |
| `backend/src/inkflow/infrastructure/agent/supervisor_pipeline.py` | MODIFY：`_decide_next_action` 收集 decision trace（PR 2） |
| `backend/src/inkflow/infrastructure/database/execution_store.py` | MODIFY：`update_stages` 接受 trace + 落库（PR 2） |
| `backend/src/inkflow/domain/services/agent_service.py` | MODIFY：`_run_pipeline` 透传 trace 到 `update_stages`；`get_status` 返回 trace（PR 2） |
| `backend/tests/unit/test_agent_trace.py` | NEW（PR 2 RED） |
| `backend/tests/unit/test_chat_pipeline.py` | NEW（PR 1 RED） |
| `tests/api/test_pipeline_execute_chat.py` | NEW（PR 1 RED） |

### 8.2 前端

| 文件 | 变更 |
|------|------|
| `frontend/packages/renderer/src/components/ChatPanel.tsx` | NEW（PR 1） |
| `frontend/packages/renderer/src/components/ChatPanel.test.tsx` | NEW（PR 1 RED） |
| `frontend/packages/renderer/src/components/ExecutionDetailPanel.tsx` | NEW（PR 2） |
| `frontend/packages/renderer/src/components/ExecutionDetailPanel.test.tsx` | NEW（PR 2 RED） |
| `frontend/packages/renderer/src/components/EditorToolbar.tsx` | MODIFY：view-toggle 按钮（PR 2） |
| `frontend/packages/renderer/src/components/EditorToolbar.test.tsx` | MODIFY：view-toggle 契约（PR 2 RED） |
| `frontend/packages/renderer/src/pages/writing.tsx` | MODIFY：ChatPanel 接入 + view state + 详情视图分支（PR 1+2） |
| `frontend/packages/renderer/src/pages/writing.test.tsx` | MODIFY：聊天框 + 切换契约（PR 1+2 RED） |
| `frontend/packages/renderer/src/i18n/zh.ts` / `en.ts` | MODIFY：§4.4 key（PR 1+2） |
| `frontend/packages/renderer/src/api/pipeline.ts` | MODIFY：`PipelineExecutionStatus` 加 `trace` 字段（PR 2） |
| `tests/e2e/e2e-writer-chat.spec.ts` | NEW（PR 2，确定性 route 拦截） |
| `tests/e2e/e2e-writing.spec.ts` | MODIFY（如受改造影响同步 testid） |

## 9. 交付拆分（2 PR）

- **PR 1（子任务 1，Part of #379）**：后端 builtin:chat 模板 + 前端 ChatPanel +
  插入正文 + i18n + 相关 RED/GREEN。
- **PR 2（子任务 2，Closes #379）**：后端 trace 捕获（列/迁移/端点）+ 前端
  ExecutionDetailPanel + 视图切换 + E2E + i18n。
- 门禁：M1 RED 全 FAIL · M2 前端测试全绿 · M3 聊天框（轮询 + 插入正文）· M4 切换按钮 ·
  M5 详情页（stages/trace/relations/子 agent）· M6 落章不变 · M7 PR 合入 CI 绿 · M8 #379 closed。

---

## 14. chat 系统级 Agent（#597，2026-08-23 增量）

> 本模块在 v1.1 引入 `ChatPanel 驱动 deepagents 系统级 Agent`（#551 C1）。§4.1（v1.0 的「轮询 builtin:chat 聊天框」）经 #541 streamChat（纯 LLM 对话）迭代后，由本 §14 再次升级为 **agent loop 工具流式**。§4.1 §4.4 的 testid/i18n 契约在 #541-#581 已落地并扩充，本 §14 只做增量（工具流 + 删入口 + 能力迁移），不推翻既有契约。

### 14.1 拍板记录（2026-08-23，用户拍板）

| 决策 | 结论 | 说明 |
|------|------|------|
| D8 | **A：ChatPanel 跑 deepagents agent loop**（复用 `build_deep_agent` harness，聊天即 agent） | system agent 全量暴露工具（5 只读 + save_draft），消息发出后 agent 自主决定工具调用序列 |
| D11 | **A：删 nav.book 入口，F44 编排能力迁移进对话** | 删除侧边栏 `nav.book` 导航项；`/book` 路由 + BookPage + BookPlannerPanel + 后端 books.py **全部保留**（能力迁移，非物理删除） |

### 14.2 后端契约：chat agent 流式端点（新增）

**新增 `POST /api/v1/chat/agent/stream`**（SSE 流式，与既有 `POST /api/v1/chat/stream` 并存；后者为 #541 纯 LLM 对话端点，保留向后兼容，ChatPanel 改用 agent 端点）。

- **装配**（`get_chat_agent_service`，deps.py 新增）：`build_deep_agent(model=config.llm_default_model, api_key, base_url, tools=全量工具, system_prompt=chat_system_agent_prompt, profile_key=None)`。
  - `tools` = `build_reader_tools(ReaderToolDeps(character_service, foreshadowing_service, summary_service, chapter_audit_service))`（全量 5 只读）+ `build_save_draft_tool(SaveDraftToolDeps(draft_service, audit_service, expected_project_id=data.project_id, expected_chapter_id=data.chapter_id))`。
  - `system_prompt` = **全新「系统级 Agent」提示**（区别于 §1 `_CHAT_ASSISTANT_PROMPT` 纯对话提示）：声明拥有全部工具（检索/写入/审计），可自主完成创作任务，输出正文。
  - 模型/密钥/base_url 装配镜像 `get_agentic_writer_service`（deps.py L241-252 同源 provider_config 解析）。
- **执行**：`agent.astream_events({"messages": [SystemMessage(system_prompt), HumanMessage(prompt + 章节上下文)]}, version="v2")` 迭代事件流 → SSE 帧。技术路径 spike 已确认（deepagents 0.7.5 编译图为 `CompiledStateGraph`，支持 `astream_events`）。
- **SSE 帧协议扩展**（`_encode_frame` 增 `type` 键，区分帧类型）：

```jsonc
// data: <JSON>\n\n
{ "type": "delta",      "delta": "文本增量",            "done": false }
{ "type": "tool_call",  "id": "call_1", "name": "search_characters", "args": { "project_id": "..." }, "done": false }
{ "type": "tool_result","id": "call_1", "name": "search_characters", "result": "{\"ok\": true,...}", "done": false }
{ "type": "done",       "done": true }
{ "type": "error",      "error": "LLM 调用失败，请稍后重试", "done": true }
```

- 事件映射（astream_events → SSE 帧）：
  - `on_chat_model_stream`（run_type=llm + chunk）→ `delta` 帧（LLM token 增量）
  - `on_tool_start` → `tool_call` 帧（工具名 + 参数）
  - `on_tool_end` → `tool_result` 帧（工具输出 JSON 信封）
  - agent loop 结束 → `done` 帧
  - `LLMRequestError` / `RAGUnavailableError` → `error` 帧
- **错误语义**：prompt 空白 → 422（复用既有 `ChatStreamRequest` 校验）；工具内部错误 → `error` 帧（不中断整体，工具信封 `{"ok": false}` 已含业务错误）。

### 14.3 前端契约：ChatPanel 工具流式（MODIFY）

- `api/chat.ts` 的 `streamChat` **保留函数名**、仅升级为 agent 端点（POST `/api/v1/chat/agent/stream`），`ChatStreamFrame` 扩展 `type` 字段 + `id`/`name`/`args`/`result`；callbacks 新增 `onToolCall` / `onToolResult`。
- `ChatPanel.tsx`：流式渲染工具调用卡片 + 结果卡片 + 最终 delta。testid 新增：
  - `chat-tool-call-<n>`（工具调用卡片：工具名 + 参数摘要，data-name 属性）
  - `chat-tool-result-<n>`（工具结果卡片：结果 JSON 摘要 / `tool-error` 样式）
- 既有契约保留：#541 并发保护（inFlight）、#474 模型未配置 guard、#477 意图解析（仅对最终回复 delta 文本 parse）、#547 持久化、#581 删除/归档。

### 14.4 删 nav.book 入口 + F44 能力迁移（D11=A）

- `AppNav.tsx` `WRITING_ITEMS` 删除 `{ key: 'book', href: '/book', labelKey: 'nav.book', icon: NotebookPen }`；`NotebookPen` 图标 import 若无其他使用则一并删除（避免 unused import）。
- **保留**：`App.tsx` `/book` 路由（`<Route path="/book" element={<BookPage />} />`）+ `TITLE_BY_PATH['/book'] = 'nav.book'`；`BookPage.tsx` + `BookPlannerPanel`；后端 `books.py`（F44 编排逻辑）；i18n `nav.book`（供 TITLE_BY_PATH / BookPage 页面标题）。
- **能力迁移语义**：`/book` 不再从侧边栏进入；F44 的「访谈→计划→运行」全自动编排未来由对话内 system agent 触发（#598/#599 实现 tool 触发，非本增量范围）；本增量仅删导航入口 + 保证 `/book` 路由仍直达。
- 测试同步：`AppNav.test.tsx` 新增 `expect(screen.queryByTestId('nav-item-book')).not.toBeInTheDocument()`（正向守卫）；`book.test.tsx` 保留（BookPage/路由可达性不受导航删除影响）；`App.routing.test.tsx` 若有 `nav-item-book` 断言同步删除。

### 14.5 测试策略（RED 契约）

**后端（pytest）**：
- `tests/unit/test_chat_agent_stream.py`（NEW，RED）：`get_chat_agent_service` 装配全量工具（5 只读 + save_draft，mock service）；SSE 帧协议三形态（delta / tool_call+tool_result / done）；错误帧（LLMRequestError → error）；astream_events 事件流 → 帧映射（on_chat_model_stream → delta，on_tool_start → tool_call，on_tool_end → tool_result）；prompt 空白 422。
- `tests/api/test_chat_agent_api.py`（NEW，RED）：POST `/api/v1/chat/agent/stream` 冒烟（mock harness，帧类型表）。

**前端（Vitest + RTL）**：
- `ChatPanel.test.tsx`（MODIFY RED）：新增 describe——工具流渲染：mock `streamChat`（保留函数名升级）驱动 onToolCall → 工具卡片 `chat-tool-call-<n>` / onToolResult → 结果卡片 `chat-tool-result-<n>` / 最终 delta → ai 消息；并发保护（inFlight 仍适用）；空输入禁用发送。
- `AppNav.test.tsx`（MODIFY RED）：新增 `nav-item-book` 不存在守卫。
- `book.test.tsx`：不改（BookPage/路由可达性保持）。

### 14.6 文件结构

**后端**：
| 文件 | 变更 |
|------|------|
| `backend/src/inkflow/api/routers/chat_stream.py` | MODIFY：新增 `/chat/agent/stream` 端点 + `_encode_frame` 扩展 type 帧 |
| `backend/src/inkflow/infrastructure/agent/chat_agent_service.py` | NEW：`ChatAgentService`（astream_events 事件→帧映射，infrastructure 层，可 import deepagents；ADR-015 隔离） |
| `backend/src/inkflow/infrastructure/agent/pipeline_templates.py` | MODIFY：新增 `_CHAT_SYSTEM_AGENT_PROMPT` 常量 |
| `backend/src/inkflow/api/deps.py` | MODIFY：新增 `get_chat_agent_service`（全量工具装配） |
| `backend/tests/unit/test_chat_agent_stream.py` | NEW（RED） |
| `tests/api/test_chat_agent_api.py` | NEW（RED） |

**前端**：
| 文件 | 变更 |
|------|------|
| `frontend/packages/renderer/src/api/chat.ts` | MODIFY：`streamChat`（保留函数名升级 agent 端点）+ `ChatStreamFrame.type/id/name/args/result` + `onToolCall/onToolResult` |
| `frontend/packages/renderer/src/components/ChatPanel.tsx` | MODIFY：工具流渲染（tool_call/result 卡片） |
| `frontend/packages/renderer/src/components/AppNav.tsx` | MODIFY：删 `nav.book` 入口 + NotebookPen import |
| `frontend/packages/renderer/src/components/ChatPanel.test.tsx` | MODIFY（RED）：工具流 describe |
| `frontend/packages/renderer/src/components/AppNav.test.tsx` | MODIFY（RED）：nav-item-book 不存在守卫 |

### 14.7 关键架构决策记录

| 决策 | 方案 | 理由/备选否决 |
|------|------|------|
| 工具流式技术路径 | **`agent.astream_events(version="v2")`** | deepagents 0.7.5 编译图为 `CompiledStateGraph`（spike 已证支持 astream_events）；产出 on_chat_model_stream/on_tool_start/on_tool_end 标准事件，天然映射 SSE 帧。备选 `astream(stream_mode="updates")` 粒度偏粗（节点级非 token/tool 级），否决 |
| chat agent 端点形态 | **新增 `/api/v1/chat/agent/stream`**，与既有 `/chat/stream` 并存 | 保留 #541 纯对话端点（向后兼容 + 降级路径）；agent 端点独立演进而非破坏旧契约。备选「改造 `/chat/stream` 为 agent」破坏既有测试与 api/chat.test.ts 契约，否决 |
| 系统 agent 工具面 | **全量 5 只读 + save_draft** | 复用 F26/F27 工具工厂（build_reader_tools + build_save_draft_tool），system agent 全量暴露；白名单过滤（tool_ids）供 #598/#599 后续按需收敛 |
| 工具内部错误隔离 | **工具信封 `{"ok": false}` 吞异常** | 工具工厂既有语义（F26/F27 约束），agent loop 不因单工具失败中断；HTTP 层仅 LLM/基础设施异常转 error 帧 |

### 14.8 验收里程碑（M 门禁，叠加 v1.0 M1-M8）

- **N1**：`POST /api/v1/chat/agent/stream` 流式返回 delta/tool_call/tool_result/done 帧（pytest 契约）。
- **N2**：ChatPanel 发送消息 → deepagents agent loop → 流式渲染工具调用卡片 + 结果卡片 + 最终回复。
- **N3**：AppNav 无 `nav-item-book`；`/book` 路由仍直达 BookPage。
- **N4**：前端 vitest + tsc 全绿；后端 pytest + ruff + mypy 全绿。
- **N5**：PR 合入（Part of #551，#551 保持 OPEN；Closes #597）。

## 15. 会话栏 + 生成新会话 + 右栏重构（#762-#765，2026-08-29 增量）

### 15.1 需求映射
| Issue | 需求 | 决策 |
|---|---|---|
| #762 | 左侧独立「会话」栏（与设定库同级）+ 折叠/展开；会话全部显示 | D1 独立；D2 分组简化 |
| #763 | 续写/生成按钮 → 创建新会话（非页脚「执行中」进度条） | 生成挂到会话 |
| #764 | 去掉草稿审批右栏，审批/保存移到章节页顶部按钮 | D3 右栏只留上下文注入 |
| #765 | 右栏折叠按钮移到左缘 +「折叠」提示词 | — |

### 15.2 会话域模型
- 会话 = 后端 `/chat/conversations` 线程（#744 已实现，复用不新建；含 `is_deleted` 归档语义）。
- 左侧导航新增「会话」分组（与设定库同级，取代 #752 会话入设定库栏的做法），列表 = `GET /chat/conversations?include_deleted=true`；每项显示 `last_message` / `message_count` / `updated_at`。
- **#825 修正**：后端 `GET /chat/conversations` **不收 project_id**（忽略未定义 query）→ 会话栏须**本地按当前项目 `project_id` 过滤**（镜像 sessions.tsx）；每条目显示**单一 title**（空回退 last_message，无冗余底部小 title）；折叠按钮位于「会话」标题行最右（justify-between）。
- 会话栏容器折叠/展开状态 → `localStorage` 持久化；分组按时间 + 置顶（简化，勿照搬 Hermes 三级分组）。

### 15.3 生成→新会话契约
- 续写/生成按钮点击 → `POST /chat/conversations {project_id}` 创建新线程 → 该次生成挂到新会话 → 会话栏出现新项。
- 移除写作页页脚内联「执行中 N%」进度条；生成进度改在会话视图中呈现。
- 关联 #760：会话 run 状态持久化（`AgentRun.status`），跳页返回可自动恢复、不僵死 running。

### 15.4 右栏重构契约
- 移除右栏「草稿审批」面板（从右栏去掉）；审批/保存收敛到章节页顶部功能按钮。
- 右栏折叠按钮移到右栏左缘，加「折叠」提示词（图标 + 文字）。
- 关联 #759：上下文注入面板空写作要求时显示「未填写写作要求」占位（不渲染 422 原始 JSON）。

### 15.5 决策记录
| 决策 | 方案 | 理由/备选否决 |
|---|---|---|
| D1 会话栏 | 左侧独立「会话」栏（+折叠） | 域清晰（会话=运行时对象）；取代 #752 入设定库栏 |
| D2 分组 | 时间 + 置顶 | 个人写作场景；勿照搬 Hermes 三级分组（复杂度收益低） |
| D3 右栏 | 只留「上下文注入」 | 草稿审批冗余；审批/保存收敛章节顶部 |

### 15.6 文件结构
| 文件 | 变更 |
|---|---|
| `frontend/packages/renderer/src/components/AppNav.tsx` + `.test.tsx` | MODIFY：新增「会话」导航组（与设定库同级），会话迁出设定库栏（#762） |
| `frontend/packages/renderer/src/components/SessionBar.tsx` + `.test.tsx` | CREATE：会话栏（折叠展开 + 列表 + 分组）（#762） |
| `frontend/packages/renderer/src/pages/writing.tsx` + `.test.tsx` | MODIFY：续写/生成按钮 → `createChatConversation`（#763）；去页脚进度条 |
| `frontend/packages/renderer/src/components/DraftApprovalPanel.tsx` | MODIFY/REMOVE：从右栏移除（#764） |
| `frontend/packages/renderer/src/components/ContextPanel.tsx` + 右栏容器 | MODIFY：折叠按钮左移 +「折叠」提示（#765）；空需求占位（#759） |

### 15.7 验收 M（叠加 v1.0 M1-M8 + v1.1 N1-N5）
- **P1**：左侧会话栏显示项目会话（含归档 `is_deleted`）；折叠/展开状态持久化。
- **P2**：续写/生成 → 新会话出现在会话栏；写作页页脚无「执行中」进度条。
- **P3**：右栏无「草稿审批」；审批/保存在章节页顶部按钮可操作。
- **P4**：右栏折叠按钮在左缘 + 显示「折叠」提示。
- **P5**：上下文注入空写作要求显示占位（非 422 原始 JSON）（关联 #759）。
- **P6**：前端 vitest + tsc 全绿；PR 合入（Closes #762/#763/#764/#765）。

### 15.8 待澄清
- 无（D1/D2/D3 已拍板 2026-08-29）。

## 16. 交互规格（交互类专用）

### 16.1 画面样式（简图/原型）

- 原型引用：design/GUI/writing/（写作页：编辑器 + 底部聊天横栏 + 右栏上下文注入）、design/GUI/sessions/（左侧会话栏）；各状态截图 &lt;page&gt;-&lt;state&gt;.png
- 参考锚点（§4 前端契约 + §14/§15 增量契约）：
  - 布局：写作页底部横栏 = 聊天框（ChatPanel，替代原 PipelineStatus 区域布局，statusbar 精简信息行保留）；左侧导航新增「会话」分组（与设定库同级，取代 #752 会话入设定库栏的做法）
  - 聊天：消息列表（user/ai）+ 工具调用/结果卡片流式渲染 + 最终回复 + 「插入正文」按钮；失败 → 消息区错误展示不崩溃
  - 详情：AI 执行详情页（stages 阶段卡 / trace 决策分色 / relations 边 + gate 判定 / 最终回复 + 总耗时）；无执行记录 → 空态引导
  - 会话：会话栏列表（last_message / message_count / updated_at），折叠/展开持久化，分组按时间 + 置顶（简化，勿照搬 Hermes 三级分组）
  - 右栏：只留「上下文注入」面板（移除草稿审批），折叠按钮在右栏左缘 +「折叠」提示词；空写作要求 → 「未填写写作要求」占位
- 布局说明：写作页 = 编辑器主区 + 底部聊天横栏（发送中 inFlight 守卫，流式增量渲染 delta 文本与工具卡片，SSE 帧 type 区分 delta/tool_call/tool_result/done/error）；详情视图经工具栏 view-toggle 切换（默认 editor-view）；左栏会话与设定库同级分组，折叠为图标窄条。

### 16.2 动作样式（按钮 × 状态表，逐控件）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 聊天输入框（chat-input） | 空输入 + 发送禁用 | 输入文本 | 发送中再次发送无操作（inFlight 守卫） | — | — | 空输入禁用发送；模型未配置 guard（#474） |
| 发送按钮（chat-send） | 非空可点 | 调 agent 端点 SSE 流式（POST /api/v1/chat/agent/stream） | 流式渲染 delta 增量 + 工具调用/结果卡片 | assistant 消息展示最终回复 | 错误帧 → 消息区显示 write.chat.failed（不崩溃） | 错误帧 done=true；工具内部错误 → 工具信封 ok=false 不中断整体 |
| 插入正文按钮（chat-insert-&lt;n&gt;） | assistant 消息后出现 | chapterStore.setContent(final_output) | — | toast「已插入正文，按 Ctrl+S 保存」（write.chat.inserted） | — | 无章节选中（currentChapterId 为空）→ 按钮禁用；不自动保存（F27 既有 save 流） |
| 工具调用卡片（chat-tool-call-&lt;n&gt;） | — | 流式出现（工具名 + 参数摘要，data-name 属性） | — | — | — | 逐工具一张卡片 |
| 工具结果卡片（chat-tool-result-&lt;n&gt;） | — | 流式出现（结果 JSON 摘要） | — | tool-error 样式 | 结果信封 ok=false 展示业务错误 | — |
| 视图切换按钮（view-toggle） | 默认 editor-view（aria-label 查看 AI 执行详情 write.view.toDetail） | 切换 editor ↔ detail | — | 主编辑区渲染 ChapterEditor（editor-view）/ ExecutionDetailPanel（detail-view） | — | 图标 lucide ListRestart 或 Eye/Pencil；aria-label 按当前视图（write.view.toEditor 返回正文编辑） |
| AI 执行详情页（exec-detail） | 无执行记录 → 空态（exec-detail-empty） | 数据源 GET /pipelines/executions/{id} | 加载态 | 渲染 stages（status/output/error/retry_count/duration_ms）/ trace（node/type/reasoning/tool_calls/output/duration_ms 分色）/ relations（边 + gate_result）/ 最终回复 | — | trace 无决策条目（静态模式仅 stage 条目，decision 仅 supervisor 模式产生）；旧库未迁移 → getattr trace 空数组防御 |
| 会话栏折叠（SessionBar） | 展开列表 | 折叠/展开 | — | 状态持久化（localStorage） | — | 分组按时间 + 置顶；归档会话 is_deleted 也显示（include_deleted=true） |
| 续写/生成按钮 | 常驻 | POST /chat/conversations 创建新会话 → 该次生成挂到新会话 | 生成中 | 会话栏出现新项 | 错误 toast | 移除写作页页脚内联「执行中 N%」进度条；生成进度改在会话视图呈现 |
| 右栏折叠按钮 | 右栏左缘 +「折叠」提示词（图标 + 文字） | 收起右栏 | — | 展开条可恢复 | — | 右栏只留上下文注入面板 |
| 上下文注入面板 | 空写作要求 | — | — | 显示「未填写写作要求」占位 | — | 不渲染 422 原始 JSON（#759） |

### 16.3 验收

- N1：聊天框发送 → 流式/轮询 → assistant 消息 + 插入正文按钮；插入 → 编辑器 value 更新（v1.0 M3 + §14.8 N2）
- N2：失败 → 错误消息不崩溃；发送中并发保护；空输入禁用发送（M3）
- N3：view-toggle 切换 editor ↔ detail；详情页渲染 stages/trace/relations/final + 空态（M4/M5）
- N4：工具流式渲染 tool_call/result 卡片 + 最终回复（§14.8 N2）
- N5：AppNav 无 nav-item-book（正向守卫）且 /book 路由仍直达 BookPage（§14.8 N3）
- N6：会话栏显示项目会话（含归档）+ 折叠持久化；续写/生成 → 新会话；页脚无「执行中」进度条（§15.7 P1/P2）
- N7：右栏无「草稿审批」+ 折叠按钮左缘 + 上下文注入空需求占位（§15.7 P3/P4/P5）
- N8：前端 vitest + tsc 全绿；E2E e2e-writer-chat 确定性 page.route 拦截（M7 + §14.8 N4）

## 17. 会话页架构（#770，2026-08-30 增量）

> 本模块把「写作会话/聊天会话」提升为全局一等对象，与 §15 会话栏（#762）+ 生成新会话（#763）衔接。核心：**无章节写作页 → 全局 chat 页** + **章节内会话跟随章节** + **会话命名/改名**。

### 17.1 需求映射

| Issue | 需求 | 决策 |
|---|---|---|
| #770 | 无章节写作页由「空」改全局 chat 页（始终占最大画布、不可调节大小） | A：中栏条件渲染全局 ChatPanel（flex-1，无 resize handle），不渲染 EditorToolbar/ChapterEditor；右栏保持 |
| #770 | 章节内 chat 默认最小且可调（与全局 chat 页两套视图） | B：章节选中 → 现有底部横栏 ChatPanel（resize handle 80~480px）不变 |
| #770 | 每次不同章节用 chat 都创建新会话，会话名默认=章节名 | C：创建时机 = chat 对话 或 点生成/续写按钮（非选中章节即建）；title=章节名 |
| #770 | 生成/续写每次开新会话（对齐 #763 P3-A） | 已实现（§15 write_continue/write_auto 建会话），保持 |

### 17.2 会话域模型

- 会话 = 后端 `/chat/conversations` 线程（#744 已实现，复用不新建；含 `is_deleted` 归档语义）。
- **不新增 `chapter_id` 字段**，也不新增任何章节关联字段（用户拍板 2026-08-30）。
- 会话 `title` 是**唯一的章节锚点**（匹配章节或回退全局页）。导航规则见 §17.4。

### 17.3 后端契约（#770 增量）

| 项 | 变更 |
|---|---|
| 字段 | `Conversation` + `ConversationORM` 加 `title: str`（可空/默认空，上限 **200** 字符，对齐章节标题 `String(200)`） |
| 创建 | `ConversationCreate` DTO 加 `title`（可选）；`POST /api/v1/chat/conversations` 透传 title |
| 改名 | 新增 `PATCH /api/v1/chat/conversations/{conversation_id}`（body `{title}`，上限 200） |
| 返回 | `list_conversations` + `_conversation_to_json` + 前端 `ChatConversationDto` 加 `title` 字段 |
| 迁移 | conversations 表加 `title` 列（幂等 `ensure_conversation_title_column`，lifespan 注册） |

命名规则：
- 章节内新建会话 → `title` = 章节名（如「第十二章 剑心蒙尘」）
- 全局 chat 页新建会话 → `title` = 首条用户消息前 **30 字**（少于 30 字取全部）
- 手动改名 → PATCH，任意 ≤200 字符

### 17.4 前端契约

#### 17.4.1 无章节 → 全局 chat 页（场景 A）

- `pages/writing.tsx`：`currentChapterId === null`（且有项目）时，中栏渲染全局 ChatPanel：
  - `data-testid="global-chat"`（新容器）；ChatPanel `variant="full"`（或等价 prop），flex-1 占满中栏，**不渲染 resize handle**（不可调节大小）
  - 不渲染 `EditorToolbar` / `ChapterEditor` / `ExecutionDetailPanel`
  - 右栏 `right-rail` 保持（上下文注入仍有用）；左栏项目树保持
- 全局 ChatPanel 发送/流式/工具卡片/意图解析复用章节内 ChatPanel 全部行为（§4.1/§14.3 契约），**仅大小可调性不同**（full=不可调 / inline=可调）

#### 17.4.2 章节内 chat 可调（场景 B）

- 章节选中 → 现有 `ChatPanel`（inline，resize handle 80~480px）完整保留，**不改**。
- **两套视图用条件分支渲染，不共享同一布局组件硬编码**（full 与 inline 的 wrapper/行为分离）。

#### 17.4.3 会话跟随章节 + 命名（场景创建）

- 章节内 chat 对话 → `createChatConversation(projectId, { title: 章节名 })` 建立**新会话**（非复用现有线程）；`conversationIdRef` 跟随。
- 章节内点生成/续写 → `startWithCheck` 已建新会话（#763），补传 `title: 章节名`。
- 全局 chat 页对话 → `createChatConversation(projectId)`（无章节），title 由首条用户消息前 30 字落库（发送时 saveChatMessage 前先 set title）。

#### 17.4.4 会话命名/改名

- `SessionBar` / `sessions.tsx` 展示会话 `title`（空则回退 `project_name` / `last_message`）。
- 会话改名入口：`sessions.tsx` 卡片行内「改名」按钮 → PATCH `/chat/conversations/{id}` body `{title}`。
- 章节内 ChatPanel 也提供改名（可选，聚焦 sessions 页）。

#### 17.4.5 导航规则（基于 title 匹配章节，非 chapter_id）

- 点击会话（SessionBar / sessions 卡片）→ 用 `title` 去匹配「当前项目章节标题」：
  - 匹配到 → `navigate('/writing?chapter_id=<章ID>')` + 选中该章节（写作页 + 章节内 chat）
  - 匹配不到（改名了 / 全局会话 / 章节不存在）→ `navigate('/writing?conversation_id=<会话ID>')` → 全局 chat 页加载历史并继续
- `SessionBar` 保持自包含（点击目标可后续重定向，§15 契约不变）。

### 17.5 i18n 新增 key（zh.ts / en.ts 同步）

```
write.chat.globalTitle      // 全局对话
write.chat.rename           // 重命名
write.chat.renamed          // 已重命名
sessions.chat.titleEmpty    // 未命名会话
```

### 17.6 测试策略（RED 契约）

**后端（pytest）**：
- `tests/unit/test_conversation_title.py`（NEW）：`Conversation` 领域模型 `title` 字段默认空 / 上限 200 校验（超 200 → ValidationError）；`ConversationCreate` 带/不带 title；`ensure_conversation_title_column` 幂等迁移三形态（旧库补列/新库 no-op/无表 no-op）。
- `tests/api/test_chat_conversation.py`（NEW 或 MODIFY）：`POST /chat/conversations` 带 title → 201 返回含 title；`PATCH /chat/conversations/{id}` 改 title（成功/404/超 200 → 422）；`GET /chat/conversations` 返回 title；`_conversation_to_json` 序列化含 title。

**前端（Vitest + RTL）**：
- `writing.test.tsx`（MODIFY RED）：无章节 → 渲染全局 chat 页（`global-chat` testid，无 resize handle / 无 EditorToolbar）；章节选中 → 章节内 ChatPanel（resize handle 存在）。
- `ChatPanel.test.tsx`（MODIFY RED）：full variant 不渲染 resize handle；inline 渲染（回归）。
- `writing-chat-agent-reply.test.tsx`（MODIFY 或 NEW）：章节内对话 → createChatConversation 传 title=章节名；全局对话 → title=首条用户消息前 30 字。
- `sessions.test.tsx`（MODIFY RED）：会话卡片展示 title；改名按钮 → PATCH；点击 title 匹配章节 → 跳章节页；匹配不到 → 跳全局 chat 页。
- `SessionBar.test.tsx`（MODIFY 或 NEW）：展示 title（空回退 last_message）；点击导航（匹配→章节 / 不匹配→全局）。**#825 UI 元素必须出现断言**：mock 会话列表返回条目 → `getByText('蜀山，我是掌门')` / `session-item-<id>` 出现（非「暂无数据」）；每条目仅一个清晰标题；折叠按钮在「会话」行最右；无会话 → `session-bar-empty` 空态；`projectId` 生效时仅显示该项目线程。

### 17.7 文件结构（#770 增量）

**后端**：
| 文件 | 变更 |
|---|---|
| `backend/src/inkflow/domain/models/conversation.py` | MODIFY：`Conversation.title` + `ConversationCreate.title` + 上限 200 校验 |
| `backend/src/inkflow/infrastructure/database/models/conversation.py` | MODIFY：`ConversationORM.title` 列（String(200)，nullable，default="") |
| `backend/src/inkflow/core/database.py` | MODIFY：`ensure_conversation_title_column` 幂等迁移 |
| `backend/src/inkflow/app.py` | MODIFY：lifespan 注册迁移 |
| `backend/src/inkflow/api/routers/chat_messages.py` | MODIFY：`ConversationCreate` 透传 title；`_conversation_to_json` 加 title；新增 `PATCH /conversations/{id}` |
| `backend/src/inkflow/domain/services/chat_message_service.py` | MODIFY：`create_conversation` 接受 title；新增 `rename_conversation` |
| `backend/src/inkflow/infrastructure/database/repositories/chat_message_repo.py` | MODIFY：`create_conversation` 落 title；新增 `rename_conversation` |

**前端**：
| 文件 | 变更 |
|---|---|
| `frontend/packages/renderer/src/pages/writing.tsx` | MODIFY：无章节 → 全局 chat 页分支（场景 A）；章节建会话传 title |
| `frontend/packages/renderer/src/components/ChatPanel.tsx` | MODIFY：`variant="full"` 不渲染 resize handle + flex-1 占满 |
| `frontend/packages/renderer/src/pages/sessions.tsx` | MODIFY：展示 title；改名按钮；PATCH；导航规则 |
| `frontend/packages/renderer/src/components/SessionBar.tsx` | MODIFY：展示 title；导航规则（匹配→章节/不匹配→全局） |
| `frontend/packages/renderer/src/api/chat.ts` | MODIFY：`ChatConversationDto.title` + `createChatConversation` 传 title + `renameChatConversation` |
| `frontend/packages/renderer/src/i18n/zh.ts` / `en.ts` | MODIFY：§17.5 key |

### 17.8 验收（M 叠加 §14.8 N + §15.7 P）

- **Q1**：无章节写作页 → 全局 chat 页（始终占满、无 resize handle）；有项目无章节不渲染 EditorToolbar/ChapterEditor；右栏保持。
- **Q2**：章节内 chat 默认最小且可调（resize handle 80~480px）；两套视图条件分支渲染（full/inline 行为分离）。
- **Q3**：不同章节用 chat 均创建新会话，title=章节名；点生成/续写也开新会话（#763 保持）。
- **Q4**：全局 chat 页新建会话 title=首条消息前 30 字；会话可改名（PATCH ≤200 字符）。
- **Q5**：点击会话 title 匹配章节 → 跳对应章节；匹配不到 → 跳全局 chat 页；`/sessions` 路由不删除。
- **Q6（#825 UI 元素必须出现）**：左侧会话栏（SessionBar）渲染会话条目（`session-item-<id>` / title 文案出现，非「暂无数据」）；每条目仅一个清晰标题（无冗余底部小 title）；折叠按钮位于「会话」标题行最右；无会话 → `session-bar-empty` 空态；`projectId` 生效时仅显示该项目线程。
- **Q7**：前端 vitest + tsc 全绿；后端 pytest + ruff + mypy 全绿；PR 合入（Closes #770）。
