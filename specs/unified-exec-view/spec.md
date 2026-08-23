# 统一 AI 执行工作流视图 —— 链式静态 + agentic 动态双时间线（#599）

> **Spec（0.12.0，2026-08-23）**：将「续写/生成/全自动/对话」等 AI 动作**全部展示到同一个 AI 执行详情视图**，用**统一执行模型**渲染两种形态——
> **链式**（固定 stage 静态序列）与 **agentic**（deepagents 动态 tool_call 轨迹）。工作流栏可置于视图上方/下方。
>
> 依赖：#597（chat 接入 deepagents 系统级 Agent）已合入 main；本 spec 在其上做**统一执行渲染**。
>
> ## 拍板记录（2026-08-23，用户拍板）
>
> | 决策 | 结论 | 说明 |
> |------|------|------|
> | D10 统一 agent_run 双形态 | **A：统一执行视图** | 链式=静态 stage 序列、agentic=动态 tool_call 轨迹，**都渲染到同一「查看 AI 执行详情」入口**。物理存储：链式仍在 `agent_executions`（stages/trace/relations），agentic 在 `agent_runs`（steps/tool_calls）——二者各有 GET 端点；**视图层统一**，不物理合并两表（避免大规模高风险 refactor + 迁移；符合「可逆性」「不做架构宇航员」）。物理库存合列为后续增值项。 |
> | D12 双入口统一出口 | **A：同一入口看双态** | 续写/生成按钮（链式，`executionId`）+ 对话/全自动（agentic，`runId`）都经**同一个 ExecutionDetailPanel** 渲染；panel 的项目级历史列表**同时列出链式 execution + agentic run**，任一点击进入对应详情。 |
>
> ## 设计原则（理解 D10-A 的落地边界）
>
> 1. **统一的是「视图」不是「存储」**：D10-A「落到 agent_run + steps」在本 issue 的实现语义 = 两种动**都能被同一视图模型渲染**。链式数据源（`GET /api/v1/agent/pipelines/executions/{id}` → stages）与 agentic 数据源（`GET /api/v1/agent/runs/{id}` → steps）都有结构化轨迹，面板按类型归一渲染。
> 2. **不重复造 abstraction**：面板用判别数据驱动（`executionId` → 链式分支；`runId` → agentic 分支），而非强行造一个中间「统一 timeline」抽象层——每种形态天然线性，判别 prop 已足够，避免过度架构造型。
> 3. **可逆**：面板新增 `runId`/`workflowPlacement` 可选 prop，零破坏既有链式/历史契约。

---

## 1. 现状与分析（代码实锤）

| 动作类型 | 后端记录 | 数据源端点 | 前端现有入口 |
|----------|----------|-----------|--------------|
| 续写/生成（链式） | `agent_executions`（stages/trace/relations/final） | `GET /api/v1/agent/pipelines/executions/{id}`（已有） | `ExecutionDetailPanel` `executionId` 驱动（#543 已修 null） |
| 全自动/对话（agentic） | `agent_runs`（mode/status/steps→tool_calls/final_content） | `GET /api/v1/agent/runs/{id}`（已有，`agent_runs.py` F27） | **无前端入口**（`api/runs.ts` 不存在） |

- **链式固定序列**：`agent_service._apply_agent_order` 生成固定 stage 序列 → `agent_executions.stages` 静态快照。
- **agentic 动态轨迹**：deepagents ReAct loop → `AgenticWriterService._build_steps(history)` → `AgentRun.steps`（每步 `index/message_content/tool_calls[]/tokens`；`tool_calls[].tool_name/arguments/result/is_error`）。见 `domain/models/agent_run.py`。
- **chat agent**（#597）：SSE 流式（`/chat/agent/stream`），对话后无持久 run id 暴露到 GUI——本 spec 的 agentic 详情聚焦 agent run（全自动/对话若产生 run 即可回看；chat 流式会话持久化挂后续）。

---

## 2. 前端契约

### 2.1 `api/runs.ts`（NEW）

```ts
import { apiFetch } from './client';

export interface AgentToolCallDto {
  step_index: number;
  tool_name: string;
  arguments: Record<string, unknown>;
  result: string;
  is_error: boolean;              // 工具执行是否失败（工具信封 {"ok": false}）
}

export interface AgentStepDto {
  index: number;                  // 步骤序号（0 起）
  message_content: string;        // 该步 AIMessage 文本（空 = 只调工具）
  tool_calls: AgentToolCallDto[];
  tokens: number;
}

export interface AgentRunDto {
  id: string;
  project_id: string;
  chapter_id: string | null;
  mode: string;                   // 'agentic'
  status: string;                 // running/completed/failed/terminated_by_guardrail
  steps: AgentStepDto[];
  final_content: string;
  draft_id: string | null;
  model: string;
  token_usage_total: number;
  terminated_by: string;          // llm/max_steps/repeat_tool/total_tool_calls/empty_content/token_budget
  created_at: string;
  updated_at: string;
}

/** 拉取单次 agentic run 决策轨迹（GET /api/v1/agent/runs/{id}） */
export async function getRun(runId: string): Promise<AgentRunDto> {
  return apiFetch<AgentRunDto>(`/api/v1/agent/runs/${runId}`);
}

/** 项目 run 列表（倒序分页，GET /api/v1/agent/runs?project_id=<id>&limit=<n>） */
export async function listRuns(
  projectId: string,
  limit = 20,
): Promise<{ items: AgentRunDto[]; total: number }> {
  const qs = new URLSearchParams({ project_id: projectId, limit: String(limit) });
  return apiFetch<{ items: AgentRunDto[]; total: number }>(`/api/v1/agent/runs?${qs.toString()}`);
}
```

- 后端 `_dump(run)` → `model_dump(mode='json')`：`project_id/chapter_id` 为 UUID 字符串，`steps` JSON 快照，`tool_calls[].arguments` 为 dict。DTO 形状与之一致。

### 2.2 `ExecutionDetailPanel.tsx`（MODIFY）— 双时间线渲染 + 工作流栏 + 统一历史

**导出**：`export function ExecutionDetailPanel(props: { executionId?: string | null; runId?: string | null; projectId?: string; workflowPlacement?: 'top' | 'bottom' })`

**判别逻辑**：
- `runId` 非空 → **agentic 模式**：`getRun(runId)` → 渲染动态工具调用流。
- 否则 `executionId` 非空 → **链式模式**：既有 `getExecutionStatus(executionId)`（apiFetch）→ 渲染固定 stage 序列（stages/trace/relations/final 区块保留）。
- 否则 `projectId` 非空 → **统一历史列表**（#586 扩展）：**同时**请求 `GET /agent/pipelines/executions?project_id=` + `GET /agent/runs?project_id=` → 渲染链式 items + agentic items。
- 否则 → `exec-detail-empty` 空态（不请求）。

**agentic 模式渲染**（动态工具调用流）：
- 区块 `exec-detail-steps`：`AgentRunDto.steps` 逐条渲染。
- 单步卡 `exec-detail-step-<index>`：显示 `index` + `message_content`（有文本时）。
- 该步内的工具卡 `exec-detail-tool-call-<stepIndex>-<n>`：`tool_name` 徽标 + `arguments` 摘要 + `result` 摘要 + `is_error` 时降级样式。
- **空 steps** → 区块内 `exec-detail-steps-empty` 提示。
- 底部（或顶部，随 workflowPlacement）工作流栏：`exec-detail-final` 显示 `final_content` + `token_usage_total`。

**工作流栏（`workflowPlacement`）**：
- 渲染一个横向压缩条 `exec-workflow-bar`：链式显示 `stage_id` 序列（`exec-workflow-stage-<stage_id>`）；agentic 显示 step 序号步进（`exec-workflow-step-<index>`）+ pipeline/run 名 + status 徽标。
- `workflowPlacement='bottom'` → 面板底部；缺省/`'top'` → 顶部。（#599「可在上方/下方加新栏显示工作流」）

**统一历史列表（#586 扩展）**：
- 容器 `exec-history-list`；链式 item `exec-history-item-<execution_id>`（既有语义保留）；agentic item **`exec-history-run-<run_id>`**（新）。
- 两者都为空 → `exec-detail-empty`（守卫：既有 writing.test.tsx L627 契约不变）。
- 点击 agentic run item → panel 内部 state 设 `activeRunId` → 进入 agentic 详情（同 `runId` 渲染路径）。点击链式 item 同理 → 链式详情。保证「双入口统一出口」闭环。
- 请求失败 → 显示错误（不崩溃）；单侧（runs）失败不影响 executions 列表渲染（防御：catch 后置空）。

**testid 总表（新增）**：
- `exec-detail-steps` / `exec-detail-step-<index>` / `exec-detail-tool-call-<stepIndex>-<n>` / `exec-detail-steps-empty`
- `exec-workflow-bar` / `exec-workflow-stage-<stage_id>` / `exec-workflow-step-<index>`
- `exec-history-run-<run_id>`（agentic 历史项）

**既有 testid 保留**：`exec-detail` / `exec-detail-empty` / `exec-history-list` / `exec-history-item-<id>` / `exec-detail-stages` / `exec-detail-stage-<id>` / `exec-detail-trace` / `exec-detail-trace-<n>` / `exec-detail-relations` / `exec-detail-final`。

### 2.3 后端演进（零 src 变更）

- `api/routers/agent_runs.py` 已注册 `GET /api/v1/agent/runs`（list）+ `GET /api/v1/agent/runs/{id}`（detail），`app.py` L219 已 `include_router(agent_runs.router)`；`deps.py` 已提供 `get_agent_run_repo`。**本 issue 不新增后端端点/迁移**——前端直接消费既有契约。
- QA 后端 pytest/ruff/mypy 为**回归**（本 issue 零后端 src 改动，应全绿）。

### 2.4 i18n（zh.ts / en.ts 同步新增）

```
write.detail.steps         // AI 决策步骤
write.detail.stepsEmpty    // 暂无决策记录
write.detail.toolCall      // 工具调用
write.detail.run           // Agent 运行
write.detail.workflow      // 工作流
write.detail.chain         // 链式
write.detail.agentic       // 智能体
```

## 3. 测试策略（RED 契约 → GREEN）

### 3.1 前端 RED（Vitest + RTL，`ExecutionDetailPanel.test.tsx` 追加 + `runs.test.ts` 新建）

- **agentic 详情**：`runId='r1'` → mock `getRun` 返回含 2 step + tool_call 的 run → `exec-detail-steps` / `exec-detail-step-0` / `exec-detail-tool-call-0-0`（tool_name/arguments/result）渲染；空 steps → `exec-detail-steps-empty`。
- **工作流栏**：`runId` + `workflowPlacement='top'` → `exec-workflow-bar` 在面板顶部（`exec-detail` 首位）；`='bottom'` → 末位；`exec-workflow-step-<index>` 渲染。
- **统一历史**：`executionId=null` + `projectId='p1'` → mock executions 列表 + vs `listRuns` → `exec-history-item-e1` + `exec-history-run-r1` 同屏；两者皆空 → `exec-detail-empty`；点击 `exec-history-run-r1` → 进入 agentic 详情（`getRun` 被调）。
- **runs.test.ts**：`getRun` → apiFetch(`/api/v1/agent/runs/r1`)；`listRuns` → apiFetch(`/api/v1/agent/runs?project_id=p1&limit=20`) + `{items,total}` 返回。

### 3.2 既有契约不变（守护）

- `exec-detail-empty`（无 executionId + 无 projectId）；history 空 → `exec-detail-empty`；链式 stages/trace/relations/final 渲染；失败显示错误。

## 4. 范围外声明

- **物理合并链式 → agent_runs 表**：不实施（视图层统一已满足「同一入口看双态」；库存合并列为后续增值项，需评估 agent_service 写入路径 + 迁移）。
- **chat agent 流式会话持久化 run id**：对话后若无 run 记录则不显示 agentic 详情（agent run 已有则回看）；chat 流式 run 持久化挂后续。
- **E2E（page.route 拦截）**：本 issue 聚焦组件契约 + 单测；E2E 扩展（双时间线跳转）挂后续，避免本批覆盖面过大。
- **CLI 输出 trace**：不新增（范围外，同 F47 §3.3）。

## 5. 文件结构

| 文件 | 变更 |
|------|------|
| `frontend/packages/renderer/src/api/runs.ts` | NEW（§2.1） |
| `frontend/packages/renderer/src/api/runs.test.ts` | NEW（RED） |
| `frontend/packages/renderer/src/components/ExecutionDetailPanel.tsx` | MODIFY（§2.2：runId agentic + workflow bar + 统一历史） |
| `frontend/packages/renderer/src/components/ExecutionDetailPanel.test.tsx` | MODIFY（追加 agentic/workflow/历史 describe） |
| `frontend/packages/renderer/src/i18n/zh.ts` / `en.ts` | MODIFY（§2.4 key） |

## 6. 门禁

- **M0** spec 定稿合入（本文件）。
- **M1** RED confirm FAIL（agentic 详情 / 工作流栏 / 统一历史 / runs API）。
- **M2** GREEN + `vitest` + `tsc --noEmit` 全绿 + 后端 `pytest tests/unit/ ../tests/` + `ruff` + `mypy` 全绿。
- **M3** PR merged（body `Closes #599`）+ #599 CLOSED + worktree 清理。
