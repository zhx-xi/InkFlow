# F26: Agent 工具基础设施（agent-tools）功能规格

**Spec 版本**: 1.0（初稿待评审）
**日期**: 2026-08-03
**依据**: PRD §6.1 F3/F4/F5 + Agent 化升级路径 v1.1（design/agent-upgrade-path-2026-08-03.md）§4 Stage 0
**所属阶段**: 0.4.0+（Agent 化升级第一批），估算 3-5 人天
**关联 Issues**: #90（F26，spec 先行纯 doc PR，2026-08-03 用户明确要求）
**依赖**: ✅ F5 LLM Provider（已合入）· ✅ F4 Agent 管线（已合入）· ⏳ #87 LangGraph StateGraph 重构（建议先合，非硬阻塞）
**参考 ADR**: ADR-015（LangChain 隔离）、ADR-018（测试分层）
**状态**: ✅ 已拍板（Q1-Q3=选项 A，2026-08-03；spec 草稿待实现时随 worktree 合入主仓）

> **模块类型声明**: 本模块为 Agent 化升级新增变体——「**端口扩展 + 工具适配型**」。编号依据：AGENTS.md 模块类型谱系（F15=6/F16=7/F23=8/F19=9 口径下 F26 为第 10 个模块变体，声明编号依据见 §1）。不新建实体表、不新增业务端点；为既有 LLM 客户端端口增加工具调用能力，并将既有服务包装为只读工具集。

---

## 1. 概述

F26 为 Agent 化升级（F27 Writer Agent ReAct 闭环）提供前置基础设施：**LLM 客户端工具调用能力 + 首批 5 个只读领域工具**。

- 现状缺口（升级路径 v1.1 §2 实测）：`LLMClientProtocol` 仅 `chat`/`chat_stream`，无工具调用接口；`LangChainLLMClient` 未 bind_tools。
- 本模块交付：① 领域层 `ToolSpec`/`ToolCall`/`ToolResult`/`ChatWithToolsResponse` 模型 ② `LLMClientProtocol.chat_with_tools` 端口扩展 ③ LangChain 适配器实现（bind_tools 映射 + 弱模型自动降级）④ 5 个只读工具（包装既有 service）。
- 边界声明：**不含** ReAct 循环（F27）、写工具 save_draft（F27）、记忆系统（F28）、Supervisor（F29）。F26 是纯基础设施层，无用户可见业务功能（可选 CLI 诊断命令见待澄清 Q2）。

**与样板差异**：非 F9 实体 CRUD（无新增表）、非 F14 横切门面（无统一入口端点）、非 F23 传输增强（无流式通道）——本模块是「端口扩展」，领域模型新增 4 个纯数据结构，基础设施新增 1 个适配器实现 + 1 个工具模块。

---

## 2. 数据模型

### 2.1 领域模型（`domain/ports/llm_client.py` 新增）

```python
@dataclass
class ToolSpec:
    """工具定义 — 领域层工具契约，不泄漏 LangChain 类型。"""
    name: str                    # 工具名（snake_case，如 search_characters）
    description: str             # 工具用途描述（LLM 决定是否调用时阅读）
    input_schema: dict           # JSON Schema（Pydantic model_json_schema() 产物）

@dataclass
class ToolCall:
    """LLM 发起的一次工具调用请求。"""
    id: str                      # 调用 id（多工具并行时与结果对应）
    name: str                    # 工具名
    arguments: dict              # 已解析的参数（JSON object）

@dataclass
class ToolResult:
    """工具执行结果 — 回填给 LLM 的消息内容。"""
    call_id: str                 # 对应 ToolCall.id
    content: str                 # 文本结果（JSON 序列化或纯文本）
    is_error: bool = False       # 执行异常标记（LLM 可据此调整策略）

@dataclass
class ChatWithToolsResponse:
    """chat_with_tools 响应 — 文本与工具调用二选一或并存。"""
    content: str                 # 文本内容（无工具调用时即为正文）
    tool_calls: list[ToolCall]   # 工具调用列表（空 = 未请求工具）
    model: str
    token_usage: TokenUsage | None = None
    finish_reason: str = "stop"
```

### 2.2 决策论证

| 决策 | 方案 | 理由 |
|------|------|------|
| ToolSpec 承载 input_schema | dict（JSON Schema 原样传递） | 与 LangChain/Pydantic 双向映射都无损；避免领域层依赖 Pydantic 泛型 |
| ToolCall.arguments 类型 | dict（已解析） | 字符串 JSON 解析放适配器层，领域层拿到即用 |
| 新增模型放 llm_client.py | 与既有 ChatMessage 同文件 | 同属 LLM 客户端契约，避免 ports 文件碎片化 |

### 2.3 工具模块（`infrastructure/agent/tools/`，5 个只读工具）

```python
@dataclass
class Tool:
    """可执行工具 — spec 定义 + 实现函数。"""
    spec: ToolSpec
    func: Callable[..., Awaitable[str]]   # 异步执行，返回文本结果
```

| 工具名 | 包装服务 | 输入（JSON Schema 摘要） | 输出 |
|--------|---------|------------------------|------|
| `search_characters` | character_service（F9） | project_id, keyword?, tag? | 角色档案 JSON（名称/简介/性格/关系摘要） |
| `check_foreshadowing` | foreshadowing_service（F13） | project_id, chapter_id? | 未回收伏笔列表（内容/状态/埋设位置） |
| `get_prior_summary` | context_service（F6）/ RAG | project_id, chapter_id, window? | 前文摘要（分层注入同源数据） |
| `audit_chapter` | audit_service（F15） | project_id, chapter_id | 4 维一致性 findings（严重级别降序） |
| `count_words` | writing_service 内部 `count_words` | text | 字数统计 |

---

## 3. API 契约

**无新增 REST 端点**。F26 为内部基础设施，业务端点保持现状（F27 交付 agentic 写入入口）。

---

## 4. CLI 命令签名

待澄清 Q2：是否新增诊断命令 `inkflow agent tools list`（枚举工具名 + 描述 + JSON Schema）。
若拍板 A（新增），签名遵循 F7 全局约定：

```
inkflow agent tools list [--json]
  退出码: 0 成功 / 1 运行错误 / 2 参数错误
  --json: 信封 {"ok": true, "data": {"items": [ToolSpec...]}}
```

---

## 5. 关键差异节：端口扩展 + 工具适配

### 5.1 chat_with_tools 协议语义

```
调用方 → chat_with_tools(messages, tools=[ToolSpec...])
   ├─ 适配器 bind_tools(LangChain 格式) → LLM
   ├─ LLM 响应含 tool_calls → 解析为领域 ToolCall 列表
   ├─ LLM 响应纯文本 → tool_calls 为空列表（与 chat 语义兼容）
   └─ Provider 不支持工具 → 适配器静默降级：走普通 chat 路径，tool_calls=[]
```

**降级是核心路径不是边角**（升级路径 v1.1 §7：BYOK 弱模型 DeepSeek/GLM 工具调用不稳定）：调用方（F27 循环）必须把「tool_calls 为空 + content 非空」视为正常完成信号。

### 5.2 LangChain 适配（`infrastructure/llm/langchain_client.py` MODIFY）

- 映射：`ToolSpec` ↔ `langchain_core.tools.BaseTool`（或 dict 格式 function schema，视 1.2.10 实测为准，Spike 0 验证）。
- 解析：`AIMessage.tool_calls`（含 id/name/args）→ `ToolCall`；`AIMessage.content` → 响应文本。
- 兼容：不支持 bind_tools 的模型/Provider（捕获异常或按实测特性检测）→ 降级普通 chat。

### 5.3 工具执行约定（F27 消费方）

- 工具函数**异步**、**只读**、**不落库**（本阶段；写工具 save_draft 归 F27）。
- 异常语义：工具内部异常 → `ToolResult(is_error=True, content=错误信息)`，由 LLM 决定重试或换策略（F27 循环语义，F26 只提供机制）。
- 参数校验：JSON Schema 解析失败（arguments 非法）→ 按工具调用 id 返回 is_error 结果，不中断循环。

---

## 6. 组织规则

- 工具实现放 `infrastructure/agent/tools/`，遵循 F9 起的层约定：**调 service 层不调 ORM**（repositories 由 service 内部持有）。
- `Tool` 装配（deps.py 或 F27 装配点）负责把 service 实例注入工具工厂——F26 提供 `build_reader_tools(deps) -> list[Tool]` 工厂函数。
- 领域层 `domain/ports/llm_client.py` 不 import 任何 infrastructure 模块（ADR-015 隔离不变式）。

---

## 7. 边界情况与错误处理

| 场景 | 行为 | 错误面 |
|------|------|--------|
| Provider 不支持工具调用 | 降级普通 chat，tool_calls=[] | 无（静默） |
| bind_tools 抛异常（模型不兼容） | 捕获 → 降级普通 chat | 无（静默，记日志） |
| LLM 返回非法 JSON arguments | 适配层解析失败 → ToolCall.arguments={} + 标记 | 由调用方决定（is_error 语义） |
| 工具执行抛异常 | ToolResult(is_error=True, content=str(e)) | 不中断循环 |
| 工具名不存在（LLM 幻觉） | ToolResult(is_error=True, "未知工具") | 不中断循环 |
| 未知变量/空项目（service 404 语义） | service 抛 NotFound → is_error 结果 | 不中断循环 |

---

## 8. 文件结构

| 动作 | 文件 | 说明 |
|------|------|------|
| MODIFY | `backend/src/inkflow/domain/ports/llm_client.py` | 新增 ToolSpec/ToolCall/ToolResult/ChatWithToolsResponse + chat_with_tools Protocol 方法 |
| MODIFY | `backend/src/inkflow/infrastructure/llm/langchain_client.py` | bind_tools 映射 + tool_calls 解析 + 降级 |
| CREATE | `backend/src/inkflow/infrastructure/agent/tools/__init__.py` | 导出 build_reader_tools |
| CREATE | `backend/src/inkflow/infrastructure/agent/tools/reader_tools.py` | 5 个只读工具工厂 |
| CREATE（Q2=A） | `backend/src/inkflow/cli/commands/agent_cmd.py` 扩展 | tools list 子命令（既有 agent_cmd.py 已存在，属 MODIFY） |
| MODIFY | `backend/src/inkflow/api/deps.py` | （如装配点需要）工具工厂挂载 |
| CREATE | `backend/tests/unit/ports/test_llm_client_tools.py` | 模型 + Protocol 契约测试（unit-test-backend 自动覆盖） |
| CREATE | `backend/tests/unit/infrastructure/test_langchain_tools.py` | 适配器 mock 测试 |
| CREATE | `backend/tests/unit/agent/test_reader_tools.py` | 工具包装 service 的 mock 测试 |
| CREATE（Q2=A） | `tests/cli/test_cli_agent_tools.py` | CLI 测试（**须显式加入 ci.yml integration-cli-backend job**） |

---

## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 模型/契约 | ToolSpec→JSON Schema；ToolCall/ToolResult 字段契约；ChatWithToolsResponse 双形态（纯文本/带工具） | 100%（纯数据结构） |
| 适配器 | mock AIMessage 带 tool_calls → 正确解析；无 tool_calls → 空列表；bind_tools 异常 → 降级 | ≥90% |
| 工具 | 5 工具各 1 正例 + 1 异常（service 抛错 → is_error）；参数校验 | ≥90% |
| 回归 | 既有 1667 测试零回归（chat 路径不变） | 全仓 ≥60% |

**RED 形态**：新模型 import 报 ModuleNotFoundError（新建文件）；既有 llm_client.py 新增方法 → 契约测试 AttributeError。

---

## 10. 不在范围内

| 项 | 归属 |
|----|------|
| ReAct 循环 / 自主终止 | F27 |
| 写工具 save_draft（草稿保存 + 事务 + 审计） | F27 |
| 记忆系统（diff/偏好/注入） | F28 |
| Supervisor 编排 / HITL | F29 |
| MCP 工具暴露 | F20（同源复用） |
| 独立 ToolRegistry Protocol | YAGNI 否决——5 个工具不需要注册表抽象，F27 使用方内聚 |

---

## 11. 依赖关系

- **依赖**: F5（LLM 客户端既有实现）、F9/F13/F6/F15/F3（工具包装的 service，均已合入）、#87（StateGraph 重构——建议先合：agent 循环的 state 增量语义受益，但非硬阻塞）
- **被依赖**: F27（writer-agent 消费 chat_with_tools + 工具集）、F20（MCP 工具同源复用工具定义）
- 编号口径声明: 以 ADR-019 v5 版本表为准（F24=会话、F25=daemon 已移除不复用（ADR-029）、F26=本模块）；旧文档中指向 Agent 化升级的「F24-F28」编号已作废（升级路径 v1.1 Spec 变更行）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 备选（否决理由） |
|------|------|-----------------|
| 工具调用接口放 LLMClientProtocol | 新增 chat_with_tools（ADR-B ✅ 已拍板） | 领域层直接用 LangChain bind_tools（泄漏框架类型，破坏 ADR-015） |
| 工具注册表 | 不做独立 Protocol，工具列表模块 + 工厂函数 | ToolRegistryProtocol（5 个工具过早抽象，YAGNI——升级路径 v1.1 反思结论） |
| 首批工具 | 5 只读（角色/伏笔/前文/审计/字数） | 8 全量含写工具（写工具事务/审计设计未定，F27 交付更稳） |
| 降级语义 | 静默降级普通 chat，tool_calls=[] | 显式报错（弱模型是主力场景，报错会废掉 agentic 模式） |
| 工具异常 | is_error 结果回填，不中断 | 抛异常中断循环（LLM 失去纠错机会） |

---

## 13. 验收标准

- **M1 契约测试全绿**: `pytest tests/unit/ports/test_llm_client_tools.py` — RED（ModuleNotFoundError）→ GREEN 全过
- **M2 适配器全绿**: `pytest tests/unit/infrastructure/test_langchain_tools.py` — tool_calls 解析 + 降级双路径
- **M3 工具全绿**: `pytest tests/unit/agent/test_reader_tools.py` — 5 工具正反例
- **M4 回归**: 全仓测试零回归（unit + tests/cli 分命令跑），覆盖率 ≥60%
- **M5 冒烟（Q2=A）**: `inkflow agent tools list --json` 输出 5 个工具信封
- **M6 手工验证**: 真实 LLM（如有 key）单次 chat_with_tools 调用返回正确 tool_calls

---

## 待澄清问题

- **Q1: chat_with_tools 返回形态** ✅ 已确认（用户拍板：选项 A）
  - A. 仅返回 tool_calls，由调用方执行工具（**已拍板**——LangGraph ToolNode 语义，F27 循环自然；适配器最薄）
  - B. 客户端内部执行工具并返回结果（调用方更简单，但工具执行逻辑耦合进 LLM 客户端，破坏职责分离）
  - C. 回调注入（灵活但抽象过度，5 个工具场景无必要）
  - 建议：A

- **Q2: 是否新增 CLI 诊断命令 `inkflow agent tools list`** ✅ 已确认（用户拍板：选项 A）
  - A. 新增（**已拍板**——调试/演示价值；F27 前可独立验证工具集；估算 +0.5 人天；为 F20 工具枚举预演）
  - B. 不新增（YAGNI；F27 交付时再定）
  - 建议：A（轻量且为 F20 工具枚举预演）

- **Q3: 首批工具范围** ✅ 已确认（用户拍板：选项 A）
  - A. 5 只读（**已拍板**——升级路径 v1.1 拍板口径）
  - B. 5 只读 + save_draft 提前（写工具设计未定，拆散 F27 闭环交付）
  - C. 8 全量（范围膨胀）
  - 建议：A
