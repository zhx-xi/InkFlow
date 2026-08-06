# InkFlow Agent 化升级路径 · 详细计划（v1.1）

**日期**: 2026-08-03
**状态**: ✅ 已拍板（核心路径确认，编号修正）
**依据**: PRD v2.1（design/prd-inkflow-v2.1-2026-07-30.md）+ 现有实现（backend/src/inkflow）+ 用户拍板（2026-08-03）
**参考定义**: Anthropic《Building Effective Agents》(2024-12) — workflow = 预定义代码路径编排 LLM；agent = LLM 自主决定流程与工具使用

> **Spec 变更**（v1.0 → v1.1）：① 用户拍板 4 条（自主编排后置 / 引入记忆系统 / 写工具=自定义工具+草稿机制 / 接受 spike 先行）② 模块编号修正 F24-F28 → **F26-F30**（F24=会话、F25=daemon 已被 0.5.0 里程碑占用）③ 新增 #87 依赖声明（LangGraph StateGraph 重构）④ 记忆系统（F28）进入核心路径 ⑤ MCP 同源并入 F20 不单独编号

---

## 1. 升级目标（什么叫"真 agent"）

对照四条判据，逐条给出升级后的验收语义：

| # | 判据 | 升级前（现状） | 升级后（目标） |
|---|------|--------------|--------------|
| A | **自主控制流** | 边由 `input_from/output_to` 代码写死，`_NODE_MAP` 固定 4 角色 | LLM 决定下一个执行的动作/角色（Supervisor 模式，**远期 F29**） |
| B | **工具调用循环** | `LLMClientProtocol` 无 tool calling，节点 = 单次 `chat` + 重试 | LLM ↔ 工具循环（ReAct）：调用→观察结果→再决策（F27） |
| C | **自主终止** | 固定阶段数、固定 `max_retries` | LLM 判断"达标/完成"（受安全上限约束，F27） |
| D | **跨步状态与恢复** | 无 checkpointer，进程崩溃即丢失 | 长任务状态可恢复（远期，spike 学习） |

**补充判据 E（用户拍板新增）**：**越用越智能**——从用户修改/确认/重新生成行为中学习项目偏好并注入后续生成（F28 记忆系统）。

**核心原则**：双模式并存——`deterministic`（现有静态链，默认）与 `agentic`（显式开启）。符合项目"AI 自动化默认关闭、显式开启"既有设定（F13 timeline_auto_extract 先例）。

---

## 2. 现状差距分析（已核对代码）

| 模块 | 现状 | 差距 |
|------|------|------|
| `domain/ports/llm_client.py` | 仅 `chat` / `chat_stream` | ❌ 无工具调用接口（最大缺口） |
| `infrastructure/llm/langchain_client.py` | ChatOpenAI 适配器（base_url 多 Provider） | ❌ 未 bind_tools，未暴露 tool_calls |
| `infrastructure/agent/langgraph_pipeline.py` | StateGraph 静态 DAG 执行器 | ❌ 控制流全代码决定，无条件路由 |
| `infrastructure/agent/pipeline_nodes.py` | 每节点单次 `llm.chat` + 重试 | ❌ 无循环、无工具、无自主终止 |
| `infrastructure/agent/langgraph_pipeline.py` | `StateGraph(dict)` 整体替换语义 | ⚠️ **#87（0.3.1）已规划重构为 TypedDict + reducer**——F29 supervisor 并行安全依赖它；F26/F27 单节点循环不阻塞，但优先合入更稳 |
| 工具原料（**已具备**） | character/world/outline/timeline/foreshadowing/audit/style/extraction/search + RAG vector store | ✅ 全部可包装为 agent 工具 |
| 存储形态 | **已拍板：全部入库**（SQLite + SQLAlchemy，无实体文件；实体文件仅 F21 导出产物） | ✅ 写工具 = 进程内函数调 service 层，无需文件系统抽象 |
| 可观测性 | LangSmith tracing 已在用 | ⚠️ agent 每次决策/工具调用需纳入 trace |

**关键洞察**：工具原料现成；升级核心工作量在"搭循环"（工具调用接口 + ReAct 节点 + 护栏 + 记忆闭环），不在造工具。

---

## 3. 总体架构演进

```
升级前（workflow）                    升级后（双模式 + 记忆闭环）
┌─────────────────────────┐         ┌──────────────────────────────────┐
│ 静态链: Architect→Writer │         │ deterministic（默认，现状保留）    │
│ →Auditor→Reviser        │         │  └ 静态 DAG（现有代码不动）        │
│ 每个节点 = 1 次 LLM 调用  │         │ agentic（显式开启）               │
└─────────────────────────┘         │  └ Writer Agent（ReAct 循环）     │
                                    │     └ 读工具：角色/伏笔/前文/审计    │
                                    │     └ 写工具：save_draft 草稿       │
                                    │     └ 用户确认 → 记忆系统学习偏好    │
                                    │     └ Supervisor（远期 F29）        │
                                    └──────────────────────────────────┘
                                              │
                    ┌─────────────────────────┴──────────────────────┐
                    ▼                                                ▼
            记忆闭环（F28）                                    MCP Server（F20）
  用户修改 diff → 偏好提取(N≥2) →             （工具与内部注册表同源，agent_run 远期）
  结构化偏好表 → F6 注入下次生成
```

架构不变式：
- 领域层只依赖 `LLMClientProtocol` / `AgentPipelineProtocol` 端口，不感知 LangGraph 与工具实现（Clean Architecture，延续现状）。
- 内部 agent 工具 = 进程内函数调 service 层（**自定义工具，非 MCP**——MCP 是跨进程协议，为外部 agent 设计；内部用 MCP 纯增开销）；F20 时同一批 service 薄适配暴露 MCP。

---

## 4. 分阶段计划（F26–F30 系列）

> 每阶段遵循 SDD+TDD：先写 RED 测试批（mock LLM 返回固定 tool_call 序列），确认全 FAIL 后实现 GREEN。

### Spike 0 — LangGraph 1.2.10 API 验证（1-2 天，✅ 用户已接受）

**目标**：验证 `bind_tools` / `ToolNode` / `Command` / `interrupt` / checkpointer 在 langgraph 1.2.10 的准确形态，防止 spec 写错 API（1.x breaking changes）。

**产出**：API 验证报告（每个能力：可用性 / 签名 / 与 `StateGraph(dict)` 现状的兼容性）+ 存入 `inkflow-dev` 或升级文档 references。**在 #87 合入后复验一次**（StateGraph 语义变化影响节点签名）。

### Stage 0 — 工具调用基础设施（spec F26: agent-tools）· 3-5 人天

**目标**：补齐判据 B 的前置——LLM 客户端具备工具调用能力 + 首批 5 个只读工具。

**改动范围**：
- `domain/ports/llm_client.py`：新增 `ToolSpec`（name/description/input_schema，领域层 Pydantic）+ `ToolCall` / `ToolResult` 领域模型 + `LLMClientProtocol.chat_with_tools(messages, tools, ...) -> ChatWithToolsResponse`（含 `tool_calls` 与 `content`）。
- `infrastructure/llm/langchain_client.py`：内部 `bind_tools([...])` 映射 ToolSpec ↔ LangChain schema；解析 `AIMessage.tool_calls` → 领域层 ToolCall；Provider 不支持工具调用时自动降级普通 chat（返回空 tool_calls）。
- 首批 5 个只读工具（**不做独立 ToolRegistry Protocol，YAGNI**——内聚于 F27 使用方，工具列表模块即可）：
  | 工具 | 包装的服务 | 用途 |
  |------|-----------|------|
  | `search_characters` | character_service | 按名/标签查角色档案 |
  | `check_foreshadowing` | foreshadowing_service | 查未回收伏笔 |
  | `get_prior_summary` | context_service / RAG | 前文摘要检索 |
  | `audit_chapter` | audit_service | 4 维一致性审计 |
  | `count_words` | writing_service._word_count | 字数校验 |
- 写工具 `save_draft`（草稿保存）**归 F27**（与 ReAct 闭环一起交付，保 F26 纯只读）。

**验收判据**：mock 测试证明 tool_calls 正确解析/降级；工具 JSON Schema 可枚举；既有 1667 测试零回归（chat 路径不变）。
**风险**：弱模型工具调用不稳定 → 自动降级普通 chat（核心路径，不是边角）；工具描述措辞约束检索相关性。
**学习点**：LangChain `bind_tools` + tool_calls 解析、Clean Architecture 端口隔离。

### Stage 1 — Writer Agent 闭环（spec F27: writer-agent）· 8-12 人天

**目标**：判据 B+C 达成——`writer_node` 升级为 ReAct 工具循环 + `save_draft` 草稿写工具 + 修改率指标。

**技术方案**（`infrastructure/agent/agentic_writer.py`）：
- 循环 = `llm.chat_with_tools(writer 工具集) → 执行工具 → ToolResult 回填 → 再调用 → …直到 LLM 直接输出正文或达 `max_steps`（默认 12）`。
- **写工具 `save_draft`**（用户拍板：写工具进，形态 = 草稿）：agent 只写草稿（`draft` 状态），**用户确认后才转正式章节状态**——控制感在用户手里，同时用户确认/修改动作成为 F28 记忆系统的数据源。
- **写工具工程约束**（用户拍板补充）：① 调 service 层不碰 ORM（字数统计/状态流转等领域规则不破坏）② 单工具单事务（agent run 是长任务，不跨工具事务）③ 写操作落审计日志（谁/何时/改了什么）。
- 自主终止双保险：LLM 停 = 自然终止；`max_steps` 超限 = 强制终止并标记 `terminated_by_guardrail`（映射现有 FAILED 语义，产物保留）。
- agent run 会话落库（`agent_run` 表：steps 快照、工具调用记录、token 消耗）——F28 与可观测性打底。
- **测试基建**：脚本化 mock LLM（固定 tool_call 序列驱动）——本阶段独立交付，控制 flaky 风险（PRD Flaky=0）。

**用户可见功能**：`inkflow write next --mode agentic`——生成中自动查角色设定/伏笔/前文并体现在正文；产出为草稿，用户确认后生效；CLI/API 暴露决策轨迹。
**验收判据（含质量指标）**：① mock 场景全绿（先调 2 工具再写正文 / 连续 5 次同工具触发护栏）② 真实模型 smoke：1 章 ≥ 2000 字、正文命中检索角色名/伏笔 ③ **修改率基线**：agentic vs deterministic 各生成 N 章，记录用户修改率/重新生成率（F28 生效前的基线值）。
**风险**：token 消耗 3-8 倍 → 预算护栏（32K/run）+ 成本报告；弱模型降级路径为主力路径。
**学习点**：ReAct 模式、ToolNode、guardrail、草稿-确认工作流。

### Stage 2 — 项目记忆系统（spec F28: agent-memory）· 6-10 人天（✅ 用户拍板纳入核心路径）

**目标**：判据 E 达成——从用户修改/确认/重新生成中学习项目偏好，越用越智能。

**技术方案**：
- **事件捕获**：F27 的草稿确认/修改/重新生成动作产生 diff 事件（用户修改前后对比）。
- **偏好提取**：**先规则化统计**（用户拍板建议，可解释可测试）——同一模式修改出现 **N≥2 次**才提取为偏好（防过度泛化，一次修改可能是试错）；LLM 提取为第二阶段（远期，F14 extraction 模式）。
- **存储**：结构化偏好表（`project_preference`：category/pattern/value/confidence/count/source_events）——非向量，用户可查看/删除（可控性）。
- **注入**：扩展 F6 context_provider——偏好作为写作上下文注入（protected 层），与既有角色/世界观/伏笔注入并列。
- **开关**：`memory_learning: bool` 项目级配置，**默认 false**（F13 同构：extra 键 + 请求/CLI 覆盖）。

**用户可见功能**：`inkflow memory list/remove`（查看/删除已学偏好）；"AI 已记住：称呼主角为 X"式透明提示。
**验收判据**：① 修改率/重新生成率**下降**（对比 Stage 1 基线，F28 生效证据）② 偏好提取阈值正确（1 次不学、2 次学）③ 删除偏好后立即停止注入 ④ 默认关闭（未开启时零行为变化）。
**风险**：过度学习（把一次性修改当偏好）→ N≥2 阈值 + 可删除；偏好与显式设定冲突 → 显式设定（角色档案）优先级高于学习偏好。
**学习点**：cross-thread memory 概念（LangGraph Store）、偏好学习闭环设计、可解释 AI。

### Stage 3 — 自主编排 Supervisor（spec F29: agent-supervisor）· 远期占位（✅ 用户拍板后置）

**目标**：判据 A 达成——控制流从代码迁移到 LLM。
**前置依赖**：#87（StateGraph 并行安全，0.3.1）+ F28（记忆注入为 supervisor 决策提供项目感知）。
**内容**：supervisor 节点 `Command(goto)` 动态路由 + HITL `interrupt()`（CLI 确认体验问题需先解决）+ 路由振荡护栏（同角色连续调度上限 3、步数上限 30）+ deterministic 兜底。
**产品评估（v1.1 反思保留）**：对独立创作者可能负价值（失去控制感），优先作为学习/演示能力；HITL 在 GUI（F19 渲染层）上体验优于 CLI，落地时以 GUI 为主入口。
**学习点**：Supervisor 模式、Command 动态路由、interrupt/HITL。

### Stage 4 — MCP 工具同源（并入 F20，不单独编号）· 3-5 人天

**目标**：内外一致——F20 MCP Server 的工具与内部 agent 工具同源（同一批 service 两个暴露面）。
**内容**：F20 实现时复用 F26/F27 的工具定义；`agent_run` MCP 工具（触发 agentic 模式）**远期**（嵌套 agent 价值存疑，外部 agent 自己会编排）。
**学习点**：MCP 协议、工具多面暴露。

---

## 5. 架构决策点（拍板结果 + 新增）

| # | 决策 | 结论（✅ 已拍板 / 🔲 待定） |
|---|------|---------------------------|
| ADR-A | 双模式开关 | ✅ `pipeline.mode: deterministic \| agentic`，项目级配置 + CLI/请求覆盖（F13 同构） |
| ADR-B | 工具调用接口位置 | ✅ 扩展 `LLMClientProtocol`（chat_with_tools），领域层持有 ToolSpec，不泄漏 LangChain 类型 |
| ADR-C | 预算护栏数值 | 🔲 max_steps=12 / token 32K / 同工具连续调用上限 3——待 Spike 0 实测后定稿 |
| ADR-D | 护栏触发语义 | ✅ 产物保留 + `terminated_by_guardrail`，映射 FAILED；agentic 失败可回退 deterministic |
| ADR-E | 编排引擎 | ✅ 延续 LangGraph（现状 + 学习目标一致） |
| ADR-F | 写工具形态 | ✅ 内部自定义工具（进程内调 service），非 MCP；`save_draft` 草稿机制，用户确认后生效；单工具单事务 + 审计日志 |
| ADR-G | 记忆提取方式 | ✅ 先规则化统计（N≥2 阈值），LLM 提取为第二阶段；结构化偏好表（可查看/删除） |
| ADR-H | 记忆开关 | ✅ `memory_learning` 默认 false，显式开启（F13 同构） |

---

## 6. SDD 落地规划

| 阶段 | Spec | Issue 标题 | 依赖 | 估算 | 里程碑 |
|------|------|-----------|------|------|--------|
| Spike 0 | — | LangGraph 1.2.10 API 验证（不建 issue，随 F26 记录） | #87 复验 | 1-2 天 | 0.3.1 后 |
| Stage 0 | F26 agent-tools | Agent 工具基础设施：ToolSpec + chat_with_tools + 5 只读工具 | F5（已合入）、#87 建议先合 | 3-5 人天 | 0.4.0+ |
| Stage 1 | F27 writer-agent | Writer Agent 闭环：ReAct 循环 + save_draft + 修改率基线 | F26 | 8-12 人天 | 0.4.0+ |
| Stage 2 | F28 agent-memory | 项目记忆：diff 捕获 + 规则化偏好 + 注入 + 默认关闭 | F27（事件源）、F6 | 6-10 人天 | 0.5.0+ |
| Stage 3 | F29 agent-supervisor | Supervisor 自主编排 + HITL（远期） | #87、F28 | 8-12 人天 | 待定 |
| Stage 4 | 并入 F20 | MCP 工具同源 | F26/F27、F20 | 3-5 人天 | 1.0.0（F20） |

- 核心路径（F26+F27+F28）合计 **17-27 人天**；编号口径：**F26 起**（F24=会话、F25=daemon 已占用，见 ADR-019 版本表）。
- spec 遵循 13 节结构（inkflow-spec-authoring），spec 与实现同 PR（2026-08-01 用户决策）；新增 CLI 测试文件须手动加入 ci.yml `integration-cli-backend` job。
- **#87 依赖声明**：F26/F27 用单节点循环（`StateGraph(dict)` 可运行），但 #87 的 TypedDict 增量语义对 agent 循环的 state 安全（多工具结果合并）是净收益——**建议 F26 开工前先合 #87**（0.3.1 已排期）。

---

## 7. 风险总览

| 风险 | 等级 | 缓解 |
|------|------|------|
| 弱模型工具调用不稳定（DeepSeek/GLM） | 🟡 中 | 自动降级普通 chat（核心路径）；格式校验重试复用；工具描述优化 |
| token 成本失控 | 🟡 中 | 预算护栏（ADR-C）+ 成本报告 |
| 记忆过度学习（一次性修改当偏好） | 🟡 中 | N≥2 阈值 + 用户可查看/删除 + 显式设定优先 |
| agent 循环测试 flaky | 🟡 中 | 脚本化 mock LLM 测试基建独立交付（F27） |
| 自主检索引入无关设定 | 🟢 低 | 工具描述约束 + auditor 复核 |
| 复杂度上升（双模式） | 🟡 中 | deterministic 仍为默认；agentic 增量隔离；Supervisor 远期 |

---

## 8. 学习价值映射（项目动机①）

| 阶段 | 学到的 LangGraph/Agent 模式 |
|------|---------------------------|
| Spike 0 / F26 | bind_tools、工具 schema、端口隔离 |
| F27 | ReAct 循环、ToolNode、guardrail、草稿-确认工作流 |
| F28 | cross-thread memory 概念、偏好学习闭环、可解释 AI |
| F29（远期） | Supervisor 模式、Command 动态路由、interrupt/HITL、checkpointer |
| F20 同源 | MCP 协议、工具多面暴露 |

一条主线走完 = 覆盖 LangGraph 核心概念（state/nodes/edges → tools → memory → HITL → persistence），且全部落在真实写作场景。

---

## 9. 下一步（拍板后执行）

1. ✅ 升级路径 v1.1 定稿
2. ✅ F26 spec 初稿起草 + Q1-Q3 拍板（选项 A 全确认，2026-08-03）
3. ✅ F26 Issue 已创建（0.7.0 里程碑，见 Issue 对照表）
4. 🔲 Spike 0 执行（LangGraph 1.2.10 API 验证 + #87 合入状态确认）——下个会话
5. 🔲 F26 spec 进 worktree → RED 批 → 实现（与代码同 PR）
