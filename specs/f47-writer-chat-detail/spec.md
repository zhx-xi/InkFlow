# F47 写作页底部 AI 聊天框 + AI 执行详情页（#379）

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
