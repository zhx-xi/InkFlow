# F47 写作页底部 AI 聊天框 + AI 执行详情页（#379）

> **Spec 变更**（v1.0 → v1.1，2026-08-23，#597 增量）：本版将聊天框从「纯 LLM 对话 + 意图解析」（#541 streamChat，单轮对话、无工具）升级为 **ChatPanel 驱动 deepagents 系统级 Agent**（#551 C1，拍板 D8=A）——消息发出后走 deepagents agent loop（system agent 全量暴露工具），流式返回「工具调用 + 结果 + 最终回复」；同时**删除侧边栏 `nav.book` 书级编排入口**（拍板 D11=A），`/book` 路由与 BookPlannerPanel 保留（F44 编排能力迁移为对话内触发的全自动编排流程，非物理删除）。本增量明确新增后端 chat agent 端点 + SSE 帧协议扩展（见 §14）。

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

