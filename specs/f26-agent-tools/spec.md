# F26: Agent 工具基础设施（agent-tools）功能规格
> **端**: backend

**Spec 版本**: 1.1（deepagents 方案修订）
**日期**: 2026-08-10
**依据**: PRD §6.1 F3/F4/F5 + Agent 化升级路径 v1.1（design/agent-upgrade-path-2026-08-03.md）§4 Stage 0 + Spike 0 报告（docs/deepagents-evaluation-2026-08-10.md）+ 0.7.0 路线图拍板记录 4（2026-08-10）
**所属阶段**: 0.7.0（Agent 化升级第一批），估算 2-4 人天（v1.0 为 3-5 人天，deepagents 覆盖 chat_with_tools 端口后收缩）
**关联 Issues**: #90（F26，spec v1.0 已随 spec-only PR #91 合入主仓）
**依赖**: ✅ F5 LLM Provider（已合入）· ✅ F4 Agent 管线（已合入）· ✅ #87 LangGraph 重构（已合入 0.3.1）· ✅ F34 单章审计（0.6.0 已合入，audit_chapter 包装对象）
**参考 ADR**: ADR-015（LangChain 隔离）、ADR-018（测试分层）、ADR-019（编号口径）、adr/ADR-035.md（编排引擎=Deep Agents harness 0.7.5，v6 修订）
**状态**: ✅ 已实现（PR #236，2026-08-10 合入；Q1-Q3 拍板 2026-08-03，deepagents 编排升级 2026-08-10）

> **Spec 变更**（v1.0 → v1.1，2026-08-10）：编排框架从「LangGraph 手写」升级为「Deep Agents harness」（deepagents 0.7.5，用户拍板，Spike 0 全项验证通过）。① 范围收缩：删除 `LLMClientProtocol.chat_with_tools` 端口扩展 + bind_tools 适配 + 弱模型降级逻辑（被 deepagents 工具循环覆盖）；② 新增「deepagents 集成层」（§5）：create_deep_agent 装配（ChatOpenAI 实例直传）+ HarnessProfile 注册（key 格式 `openai:<model>`）+ excluded_tools 禁用默认文件系统工具 + subagent task 工具禁用决策（F26 禁、F29 0.8.0 用）；③ 依赖变更：新增 `deepagents==0.7.5` + `langchain>=1.3.14`（现 pyproject 仅 langchain-core），硬依赖 langchain-anthropic/langchain-google-genai 打包增量留 F26 QA 实测；④ 模型名处理：provider 配置剥离 registry 前缀（`zhipu/glm-4.5` → `glm-4.5`，复用既有 `parse_model_string`）；⑤ 空 content 风险记录（Spike ②，~66% 空响应）——本阶段不处理，见 §5.7 F27 前置风险；⑥ 估算 3-5 → 2-4 人天；⑦ 验收 M1-M5 按新方案重写（§13）；⑧ audit_chapter 包装对象修正：v1.0 写 F15 audit_service（项目级 run_audit），实际应为 **F34 ChapterAuditService.audit**（单章审计，0.6.0 已合入）；count_words 修正为 `domain/services/_word_count.py` 顶层纯函数（非 writing_service 内部方法）。

> **模块类型声明**: 本模块为 Agent 化升级新增变体——「**deepagents 集成 + 工具定义型**」（v1.0 称「端口扩展 + 工具适配型」，随 deepagents 方案更名）。编号依据：AGENTS.md 模块类型谱系（F15=6/F16=7/F23=8/F19=9 口径下 F26 为第 10 个模块变体，声明编号依据见 §1）。不新建实体表、不新增业务端点；为既有 LLM 客户端增加 deepagents 编排集成，并将既有服务包装为只读工具集。

---

## 1. 概述

F26 为 Agent 化升级（F27 Writer Agent ReAct 闭环）提供前置基础设施：**deepagents 集成层 + 首批 5 个只读领域工具**。

- 现状缺口（升级路径 v1.1 §2 实测 + Spike 0）：`LLMClientProtocol` 仅 `chat`/`chat_stream`/`count_tokens`，无工具调用接口；deepagents 0.7.5 自带完整工具循环（bind_tools 内部化 + tool_calls 解析 + 结果回填），**无需自研端口**。
- 本模块交付：① 领域层 `ToolSpec` 工具定义契约 + 5 个只读工具定义（包装既有 service）② `infrastructure/agent/deepagents/` 集成层（create_deep_agent 装配 + HarnessProfile 注册 + excluded_tools 禁用 FS 工具 + subagent 禁用）③ CLI 诊断命令 `inkflow agent tools list`（Q2 已拍板）。
- 边界声明：**不含** ReAct 循环（F27）、写工具 save_draft（F27）、记忆系统（F28）、Supervisor 与 subagent（F29，0.8.0）。F26 是纯基础设施层，无用户可见业务功能（CLI 诊断命令除外）。

**与样板差异**：非 F9 实体 CRUD（无新增表）、非 F14 横切门面（无统一入口端点）、非 F23 传输增强（无流式通道）——本模块是「编排框架集成 + 工具定义」，领域层新增 1 个纯数据结构（ToolSpec），基础设施新增 1 个 deepagents 集成包 + 1 个工具模块。

---

## 2. 数据模型

### 2.1 领域模型（`domain/models/agent_tools.py` 新增）

```python
@dataclass
class ToolSpec:
    """工具定义 — 领域层工具契约，不泄漏 LangChain/deepagents 类型。

    供 CLI tools list 枚举 + deepagents 集成层映射为框架工具格式。
    """
    name: str                    # 工具名（snake_case，如 search_characters）
    description: str             # 工具用途描述（LLM 决定是否调用时阅读）
    input_schema: dict           # JSON Schema（Pydantic model_json_schema() 产物）
```

> **v1.1 删除**（原 §2.1 `domain/ports/llm_client.py` 新增方案）：`ToolCall` / `ToolResult` / `ChatWithToolsResponse` 三个模型 + `chat_with_tools` Protocol 方法——被 deepagents 内部消息循环覆盖（AIMessage.tool_calls / ToolMessage 回填），领域层无需自建传输模型。`LLMClientProtocol` 文件零改动。

### 2.2 决策论证

| 决策 | 方案 | 理由 |
|------|------|------|
| ToolSpec 承载 input_schema | dict（JSON Schema 原样传递） | 与 deepagents/Pydantic 双向映射都无损；避免领域层依赖 Pydantic 泛型 |
| ToolSpec 归属文件 | `domain/models/agent_tools.py` 新建 | v1.0 拟放 `ports/llm_client.py`——chat_with_tools 删除后该文件已无工具语义落点；工具定义是「模型」而非「LLM 客户端端口契约」，独立文件更清晰（ADR-015：领域层零 LangChain import 不变） |
| 传输模型（ToolCall/ToolResult/ChatWithToolsResponse） | 不定义 | deepagents 工具循环内部处理，领域层无需感知（v1.1 修订，原决策行废弃） |
| 编排层位置 | infrastructure 层（`infrastructure/agent/deepagents/`） | ADR-015 隔离不变式：领域层只依赖 AgentPipelineProtocol/LLMClientProtocol 端口，不感知 deepagents |

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
| `search_characters` | character_service（F9）`list_characters` | project_id, search?, group_id? | 角色档案 JSON（名称/简介/性格/关系摘要，分页 limit=50 循环取全） |
| `check_foreshadowing` | foreshadowing_service（F13）`list` | project_id, status? | 未回收伏笔列表（内容/状态/埋设位置） |
| `get_prior_summary` | summary_service（F6 前文摘要）`list_recent` | project_id, limit? | 前文摘要（最近 N 章，与 F6 注入同源数据；`list_recent(project_id, limit=10)` 实际签名无 chapter 参数——「截至某章」语义留 F27 评估） |
| `audit_chapter` | **chapter_audit_service（F34）`audit`** | project_id, chapter_id, include_static? | 单章审计报告 findings（字数 + LLM 漂移 + 静态一致性；degraded 标记） |
| `count_words` | **`domain/services/_word_count.py` 顶层函数** | text | 字数统计 |

> **v1.1 工具包装对象修正**（源码核查 2026-08-10）：① `audit_chapter` v1.0 写「audit_service（F15）run_audit」——F15 是**项目级** 4 维审计（无 chapter_id 参数），工具名语义应为**单章**审计，F34 `ChapterAuditService.audit(project_id, chapter_id)`（0.6.0 已合入）为正确包装对象；F34 含 LLM 漂移检查（非纯只读计算），工具契约「只读」指不修改业务数据，F34 内部落 audit_logs 属其自身契约（F34 Q1=C 已拍板），F26 不做额外持久化。② `count_words` v1.0 写「writing_service 内部 count_words」——实际为 `domain/services/_word_count.py` 顶层纯函数（writing_service 导入复用），工具直接包装纯函数，不经过 service。③ `get_prior_summary` v1.0 写「context_service（F6）/ RAG」——实际前文摘要服务为 `SummaryService.list_recent`（F6 上下文模块的摘要生成），RAG 检索不进首批工具（F14 RAG 覆盖缺口，见 §10）。

---

## 3. API 契约

**无新增 REST 端点**。F26 为内部基础设施，业务端点保持现状（F27 交付 agentic 写入入口）。`inkflow agent tools list` 为本地静态枚举（§4），不经 HTTP——不需要内核端点。

---

## 4. CLI 命令签名

**Q2 已拍板（2026-08-03）：新增诊断命令 `inkflow agent tools list`**。签名遵循 F7 全局约定：

```
inkflow agent tools list [--json]
  退出码: 0 成功 / 1 运行错误 / 2 参数错误
  --json: 信封 {"ok": true, "data": {"items": [ToolSpec...]}}
```

- **本地静态枚举**：工具注册表（`infrastructure/agent/tools/`）是代码内静态资源，CLI 直接 import 枚举 ToolSpec，**不 ensure_kernel、不发 HTTP**——与 F38 恒 HTTP 改造的豁免命令先例一致（F38 spec §1.3 豁免清单：config/llm 组因「API 无对应端点 + 本地静态/文件资源 + 共享 data_dir 无数据漂移」豁免；tools list 同族论证：工具定义是代码内静态注册表、无对应 API 端点、非内核运行时状态——新增豁免须在 F38 §1.3 清单登记，随 F26 实现 PR 同步）。
- 输出：每个工具 name + description + input_schema（JSON Schema 原样展示）。
- 实现位置：MODIFY `backend/src/inkflow/cli/commands/agent_cmd.py`（F38 薄层改造后 `agent` 组已存在，`run` 走 HTTP；`tools list` 是组内第一个本地豁免子命令）。

---

## 5. 关键差异节：deepagents 集成 + 工具定义

### 5.1 deepagents 装配（`infrastructure/agent/deepagents/harness.py` CREATE）

```python
def build_deep_agent(*, model: str, api_key: str, base_url: str,
                     tools: list[Tool], system_prompt: str, profile_key: str) -> Agent:
    """装配 deepagents agent — ChatOpenAI 实例直传（Spike ① 验证）。

    - model: 剥离 registry 前缀后的模型名（如 glm-4.5，见 §5.5）
    - tools: F26 只读工具集（deepagents 工具格式映射见 §5.6）
    - profile_key: HarnessProfile 注册 key（openai:<model>，见 §5.2）
    """
    chat = ChatOpenAI(model=model, openai_api_base=base_url,
                      openai_api_key=api_key, temperature=0.2)
    return create_deep_agent(model=chat, tools=[...], system_prompt=system_prompt, ...)
```

- **ChatOpenAI 实例直传 `create_deep_agent`**（Spike ① ✅）：InkFlow 多 Provider 架构（custom base_url）不破坏——实例携带 base_url/api_key/model，deepagents 直接消费。
- 装配点归属：deps.py 或 F27 装配点调用本工厂；F26 只提供工厂函数 + 单元测试，不接线生产装配（无生产调用方）。
- **F26 不接线 AgentPipelineProtocol**：端口保持现状（execute/validate），deepagents 装配由 F27 消费——ADR-015 不变式声明「deepagents 在 infrastructure 层」以 F26 集成包落位为准。

### 5.2 HarnessProfile 注册（`infrastructure/agent/deepagents/profiles.py` CREATE）

- **注册 key 格式必须是 `openai:<model>`**（Spike ③ 实测）：ChatOpenAI 实例解析 provider='openai'；文档示例的 `anthropic:...` 格式对实例不匹配，会打印 "No harness profile matched" 警告并**静默用默认**——这是隐藏坑，必须按实测格式注册。
- **好消息**：InkFlow 所有 OpenAI 兼容 provider（deepseek/zhipu/glm 等）统一解析为 provider='openai'，profile 按 identifier（模型名）注册即可，无需按 provider 区分（Spike ③）。
- 注册表形态：模块级 dict `HARNESS_PROFILES: dict[str, HarnessProfile]`，装配时按 `openai:<model>` 查找/注册。

### 5.3 excluded_tools 禁用默认文件系统工具

- deepagents 默认装配文件系统工具（read_file/write_file 等，Agent Skills 生态默认面）——**InkFlow 存储形态为 DB（SQLite + SQLAlchemy），文件系统工具无意义且是攻击面**（越权读写任意路径）。
- 方案：`create_deep_agent(..., excluded_tools=[...默认 FS 工具名...])`——Spike ③ 行为级验证 ✅：excluded agent 模型自称仅剩 task + 自定义工具，read_file 不可用。
- 默认 FS 工具名清单：**待 F26 实现确认**（以 deepagents 0.7.5 源码 default tools 列表为准，Spike ③ 实测 read_file 为其中之一）。

### 5.4 subagent task 工具禁用决策（F26 结论：**禁**）

- **背景**：deepagents 的 SubAgentMiddleware 给 agent 注入 `task` 工具（subagent 机制）；Spike ③ 实测 excluded_tools 不能移除它（框架不可移除），文档给出「disable via harness profile + no subagents」路径。
- **F26 结论：禁用 subagent**——不装配 SubAgentMiddleware（或不传 subagents 参数），理由：① F26 无 supervisor 场景（F29 才需要分层编排），subagent 是 F29 0.8.0 能力；② 弱模型（BYOK 主力）subagent 嵌套调用稳定性未验证，引入即风险；③ 工具面收敛：F26 首批 5 只读 + task 工具会干扰 LLM 工具选择（模型可能误用 subagent 而非领域工具）。
- **F29 0.8.0 恢复**：Supervisor 自主编排（#161）落地时启用 subagent，spec 届时定义装配参数。
- 实现细节（确切禁用 API）：**待 F26 实现确认**——以 deepagents 0.7.5 文档「disable via harness profile + no subagents」实测为准，spec 只定决策不定 API 形态。

### 5.5 模型名前缀剥离（Spike 遗留 ① 收敛方案）

- **问题**：InkFlow provider 注册表模型名为 LiteLLM 格式 `provider/model_name`（如 `zhipu/glm-4.5`），deepagents/ChatOpenAI 只接受官方模型名（`glm-4.5`）——`zhipu/glm-4.5` 直接传会失败（Spike ① 未测、zhipu API 只接受官方名）。
- **方案**：复用既有 `infrastructure/llm/provider_config.py::parse_model_string(model) -> (provider, model_name)`（已存在，langchain_client.py 同源使用）——装配时剥离前缀，`ChatOpenAI(model=model_name)` + `base_url` 取 provider 配置（`get_provider_config`）。
- **HarnessProfile key 与模型名联动**：`profile_key = f"openai:{model_name}"`（剥离后），与 §5.2 格式一致。
- 真实调用验证：留 F26 QA（Spike 遗留点 1：剥离前缀后的真实调用；deepseek-chat 工具调用验证为 Spike 遗留点 2，F26 QA 一并覆盖）。

### 5.6 工具映射与执行约定

- **映射**：`ToolSpec` + `Tool.func` → deepagents 工具格式（`@tool` 装饰器或 `langchain_core.tools.BaseTool`，Spike 0 脚本用 `@tool` 直传）：name/description 直接映射，input_schema 由 Pydantic 参数模型 `model_json_schema()` 生成（工具函数签名即 schema 源，不手写 dict——Spike 0 脚本先例）。
- **工具函数异步、只读、不落库**（本阶段；写工具 save_draft 归 F27；audit_chapter 的 F34 内部 audit_logs 落库属 F34 自身契约，见 §2.3 注）。
- **异常语义**：工具内部异常 → 返回错误文本（deepagents 工具循环以 ToolMessage 回填，LLM 决定重试或换策略）——F26 提供机制不提供循环（循环是 deepagents 内建）。
- **参数校验**：arguments 非法 → deepagents 框架层处理（schema 校验错误回填），F26 工具函数按 Pydantic 参数模型自动获得校验。

### 5.7 F27 前置风险：空 content（Spike ②，本阶段不处理）

- **现象**（Spike ② 实测）：system_prompt「写正文前必须先查角色档案」+ 用户要求写正文 → zhipu 在 ToolMessage 后最终 AIMessage `content=''`，复现 2 轮共 2/3 概率（V2 两次：0/3、1/3；无强制指令场景 4/4 成功）。消息序列正常（Human→AIM(tool)→Tool→AIM('')），非框架丢内容，是模型「工具已满足需求」时输出空文本。
- **F26 影响评估：不阻塞**——F26 无正文生成场景（无 ReAct 循环、无用户可见输出），工具调用本身稳定（触发率 7/7），空 content 只影响「工具后写正文」的最终产物，该场景属于 F27。
- **F27 spec 必须含重试护栏（硬性前置条件）**：最终 AIMessage content 为空 → 自动重试（附工具结果重申「请输出正文」）→ 仍空则 `terminated_by_guardrail`（映射 FAILED，与升级路径 v1.1 adr/ADR-034.md 一致）。F27 起草时本条为强制验收项。

---

## 6. 组织规则

- 工具实现放 `infrastructure/agent/tools/`，遵循 F9 起的层约定：**调 service 层不调 ORM**（repositories 由 service 内部持有）。
- `Tool` 装配（deps.py 或 F27 装配点）负责把 service 实例注入工具工厂——F26 提供 `build_reader_tools(deps) -> list[Tool]` 工厂函数。
- deepagents 集成放 `infrastructure/agent/deepagents/`（ADR-015：deepagents/langchain 类型全部封闭在 infrastructure 层，domain 零 import——集成层 import 检查纳入既有 CI 守卫）。
- 领域层 `domain/models/agent_tools.py` 只含纯数据结构 ToolSpec，不 import 任何 infrastructure 模块。
- **CLI 豁免边界**：`agent tools list` 本地枚举（§4）——只 import `infrastructure/agent/tools/` 静态注册表，不 import deepagents 集成包（避免 CLI 冷启动拖入 deepagents 依赖树，F38 恒 HTTP 性能纪律）。

---

## 7. 边界情况与错误处理

| 场景 | 行为 | 错误面 |
|------|------|--------|
| provider 模型名带 registry 前缀（zhipu/glm-4.5） | 装配时 parse_model_string 剥离 → model_name | 无（装配层处理） |
| HarnessProfile key 与模型不匹配 | "No harness profile matched" 警告 + 静默默认 profile | 无（记日志；F26 装配单测断言 key 格式） |
| excluded_tools 传入不存在的工具名 | 框架忽略或警告（以 0.7.5 实测为准） | 无（记日志） |
| 模型不支持工具调用 | deepagents 工具循环行为（Spike 0 弱模型实测工具触发稳定 7/7；降级普通 chat 由 F27 语义承接） | 不中断 |
| 工具执行抛异常 | 工具函数返回错误文本 → ToolMessage 回填 | LLM 决定重试/换策略（F27 循环语义） |
| 同一请求 LLM 一次输出多个工具调用（deepagents 并行分发，设定库工具 #837） | 所有走 DB 的 agent 工具（读/写/删除/审计）按**模块级 `asyncio.Lock`**（单例，跨所有工具实例共享）串行执行，覆盖整个 await 链（含 `audit_service.record`）；同一 AsyncSession 不再被并行协程交错 | 无（#837：串行化后不出现 `cannot start a transaction within a transaction` / `database is locked` / `This transaction is closed`） |
| 参数 schema 校验失败 | deepagents 框架层校验回填错误 | 不中断循环 |
| 最终 AIMessage content 为空 | **F26 不处理**（无消费场景）；F27 重试护栏（§5.7 硬性前置） | F27 映射 terminated_by_guardrail |
| 服务 404 语义（项目/章节不存在） | service 抛 NotFound → 工具返回错误文本 | 不中断循环 |
| CLI tools list 无工具注册 | 空 items 信封，退出码 0 | 正常运行（注册表恒非空，防御性） |

---

## 8. 文件结构

| 动作 | 文件 | 说明 |
|------|------|------|
| CREATE | `backend/src/inkflow/domain/models/agent_tools.py` | ToolSpec 纯数据结构（v1.0 拟放 ports/llm_client.py，v1.1 改为独立模型文件——chat_with_tools 删除后端口文件零改动） |
| CREATE | `backend/src/inkflow/infrastructure/agent/tools/__init__.py` | 导出 build_reader_tools + TOOL_REGISTRY（静态列表供 CLI 枚举） |
| CREATE | `backend/src/inkflow/infrastructure/agent/tools/reader_tools.py` | 5 个只读工具工厂（search_characters/check_foreshadowing/get_prior_summary/audit_chapter/count_words） |
| CREATE | `backend/src/inkflow/infrastructure/agent/deepagents/__init__.py` | 导出 build_deep_agent |
| CREATE | `backend/src/inkflow/infrastructure/agent/deepagents/harness.py` | create_deep_agent 装配工厂（ChatOpenAI 直传 + excluded_tools + subagent 禁用） |
| CREATE | `backend/src/inkflow/infrastructure/agent/deepagents/profiles.py` | HarnessProfile 注册表（key 格式 `openai:<model>`） |
| MODIFY | `backend/src/inkflow/cli/commands/agent_cmd.py` | 新增 `tools list` 子命令（本地枚举，豁免 HTTP——F38 豁免清单登记） |
| MODIFY | `backend/pyproject.toml` | 新增 deepagents==0.7.5 + langchain>=1.3.14（依赖论证见 §11） |
| CREATE | `backend/tests/unit/test_reader_tools.py` | 工具包装 service 的 mock 测试（**unit 目录扁平无 agent/ 子目录，源码核实 2026-08-10**；unit-test-backend 自动覆盖） |
| CREATE | `backend/tests/unit/test_deepagents_harness.py` | 装配/注册/excluded_tools/前缀剥离契约测试 |
| CREATE | `tests/cli/test_cli_agent_tools.py` | CLI tools list 测试（**须显式加入 ci.yml integration-cli-backend job**） |

> **v1.1 删除文件**（v1.0 清单）：`domain/ports/llm_client.py` MODIFY（chat_with_tools 取消）、`infrastructure/llm/langchain_client.py` MODIFY（bind_tools 取消）、`tests/unit/ports/test_llm_client_tools.py`、`tests/unit/infrastructure/test_langchain_tools.py`（对应端口/适配器测试取消，能力并入 harness 测试）。

---

## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 模型/契约 | ToolSpec 字段契约；工具注册表枚举（5 项静态断言） | 100%（纯数据结构） |
| 集成层（harness） | ChatOpenAI 实例直传装配（mock ChatOpenAI，**不发起真实 HTTP**）；HarnessProfile key 格式 `openai:<model>` 断言；excluded_tools 传参断言；模型名剥离（zhipu/glm-4.5 → glm-4.5，复用 parse_model_string） | ≥90% |
| 工具 | 5 工具各 1 正例 + 1 异常（service 抛错 → 错误文本）；audit_chapter 包装 F34（mock ChapterAuditService）；count_words 纯函数直测 | ≥90% |
| CLI | `tools list --json` 5 工具信封；退出码 0/1/2；本地枚举不启动内核（mock 断言 ensure_kernel 未被调用） | ≥90% |
| 回归 | 既有全仓测试零回归（LLMClientProtocol/langchain_client.py 零改动） | 全仓 ≥60%（ADR-027 门禁 98.5/95.0 全量） |

**RED 形态**：新模型 import 报 ModuleNotFoundError（新建文件）；CLI 子命令缺失 → CliRunner 测试失败。

> **测试无网络约束**：deepagents 装配测试一律 mock ChatOpenAI 实例（Spike 0 隔离 venv 真实调用仅为验证手段，不进测试路径）；真实模型冒烟见 M5（手工）。

---

## 10. 不在范围内

| 项 | 归属 |
|----|------|
| ReAct 循环 / 自主终止（deepagents 内建循环的 InkFlow 语义封装） | F27 |
| 写工具 save_draft（草稿保存 + 事务 + 审计） | F27 |
| 空 content 重试护栏 | F27（§5.7 硬性前置） |
| 记忆系统（diff/偏好/注入） | F28 |
| Supervisor 编排 / HITL / **subagent task 工具** | F29（0.8.0，#161；F26 禁用 subagent，§5.4） |
| MCP 工具暴露 | F20（同源复用工具定义） |
| RAG 语义检索进工具（get_prior_summary 仅摘要服务） | F27 或后续（F14 RAG 覆盖缺口：向量库只索引提取管线产物，手动档案/outline semantic 恒空——语义检索结果集 ⊆ keyword，先不做） |
| 独立 ToolRegistry Protocol | YAGNI 否决——5 个工具不需要注册表抽象，模块级静态 TOOL_REGISTRY 即可 |
| LangSmith tracing 接入 deepagents 调用链 | 待定（Spike 遗留点 5，与既有 tracing 关系评估后定） |

---

## 11. 依赖关系

- **新增运行时依赖**（Spike 0 实测版本）：

| 包 | 版本 | 说明 |
|----|------|------|
| deepagents | ==0.7.5 | 编排框架（langchain-ai/deepagents，基于 LangGraph），用户拍板 2026-08-10 |
| langchain | >=1.3.14 | **pyproject 现仅有 langchain-core**——deepagents 硬依赖 langchain 主包，需新增；Spike 0 实测 1.3.14 |

- **deepagents 传递硬依赖**（打包增量数据，Spike 0 实测）：langchain-anthropic 1.5.4（传递拉入 anthropic 6.10 MB）、langchain-google-genai 4.3.2（传递拉入 google 9.35 MB）——**PyInstaller 增量实测留 F26 QA**（用户体积敏感，届时给打包前后对比；deepagents.graph import ChatAnthropic → anthropic 必进产物；google-genai 是否被 import 需实测）。
- **依赖**: F5（LLM 客户端既有实现 + parse_model_string/get_provider_config 复用）、F9/F13/F6/F34/F3（工具包装的 service，均已合入）、#87（已合 0.3.1 ✅）。
- **被依赖**: F27（writer-agent 消费 build_deep_agent + 工具集）、F20（MCP 工具同源复用工具定义）、F29（0.8.0 supervisor/subagent）。
- 编号口径声明: 以 ADR-019 v5 版本表为准（F24=会话、F25=daemon 已移除不复用（ADR-029）、F26=本模块）；旧文档中指向 Agent 化升级的「F24-F28」编号已作废（升级路径 v1.1 Spec 变更行）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 备选（否决理由） |
|------|------|-----------------|
| 编排框架 | **deepagents 0.7.5（v1.1 修订，2026-08-10 用户拍板，adr/ADR-035.md 待修订）** | LangGraph 手写（不同 Agent 挂不同 skill 需自研 SKILLS_BY_ROLE 等效机制；deepagents 官方一等公民） |
| 工具调用接口 | **不做端口扩展——deepagents 内建工具循环（v1.1 修订）** | v1.0 chat_with_tools + bind_tools + 降级（被框架覆盖，自研是重复劳动；Spike 0 验证） |
| LLM 接入方式 | ChatOpenAI 实例直传 create_deep_agent（Spike ①） | 传模型字符串（破坏 InkFlow 多 Provider base_url 架构） |
| HarnessProfile key | `openai:<model>`（Spike ③ 实测格式） | `anthropic:...` 文档格式（对 ChatOpenAI 实例不匹配 → 静默默认 profile，隐藏坑） |
| 默认 FS 工具 | excluded_tools 禁用（DB 存储无文件面） | 保留（无意义 + 任意路径读写攻击面） |
| subagent task 工具 | **F26 禁用、F29 0.8.0 用（v1.1 决策）** | F26 启用（无 supervisor 场景 + 弱模型嵌套未验证 + 干扰工具选择） |
| 模型名前缀 | 剥离 registry 前缀（parse_model_string 复用） | 原样传（zhipu API 拒绝带前缀名） |
| 工具注册表 | 不做独立 Protocol，模块级静态 TOOL_REGISTRY + 工厂函数 | ToolRegistryProtocol（5 个工具过早抽象，YAGNI——升级路径 v1.1 反思结论） |
| 首批工具 | 5 只读（角色/伏笔/前文/审计/字数） | 8 全量含写工具（写工具事务/审计设计未定，F27 交付更稳） |
| 工具异常 | 错误文本回填（deepagents ToolMessage），不中断 | 抛异常中断循环（LLM 失去纠错机会） |

---

## 13. 验收标准

- **M1 集成层契约全绿**: `pytest tests/unit/test_deepagents_harness.py` — 装配（ChatOpenAI 直传 mock）+ HarnessProfile key `openai:<model>` + excluded_tools + 模型名前缀剥离；RED（ModuleNotFoundError）→ GREEN 全过
- **M2 工具全绿**: `pytest tests/unit/test_reader_tools.py` — 5 工具正反例（audit_chapter 包装 F34、count_words 纯函数）
- **M3 CLI 全绿**: `pytest tests/cli/test_cli_agent_tools.py`（**已登记 ci.yml integration-cli-backend**）— `inkflow agent tools list --json` 输出 5 工具信封 + ensure_kernel 未被调用断言
- **M4 回归**: 全仓测试零回归（unit + tests/cli 分命令跑），覆盖率 ≥60%（ADR-027 全量门禁）
- **M5 真实模型冒烟（手工）**: 真实 LLM（如有 key）经 `build_deep_agent` 装配后单次 invoke 返回正确 tool_calls（复用 Spike 0 脚本模式；覆盖剥离前缀后的真实调用——Spike 遗留点 1）

---

## 待澄清问题

- **Q1: chat_with_tools 返回形态** ✅ 已确认（用户拍板：选项 A，2026-08-03）——**v1.1 修订：已被 deepagents 方案取代**
  - A. 仅返回 tool_calls，由调用方执行工具（**v1.0 已拍板**——LangGraph ToolNode 语义）
  - B. 客户端内部执行工具并返回结果
  - C. 回调注入
  - **v1.1 修订说明（2026-08-10）**：原拍板语义被 deepagents 工具循环吸收——deepagents 内建「调用→回填→再决策」完整循环，F26 不再提供 chat_with_tools 端口，工具执行由框架完成（Q1 拍板的历史结论「工具执行不耦合 LLM 客户端」与 deepagents 架构一致：执行在框架循环层而非 LLM 客户端）。正文已按 v1.1 修订（§1/§2.1/§5.1/§12）。

- **Q2: 是否新增 CLI 诊断命令 `inkflow agent tools list`** ✅ 已确认（用户拍板：选项 A，2026-08-03）
  - A. 新增（**已拍板**——调试/演示价值；F27 前可独立验证工具集；为 F20 工具枚举预演；估算 +0.5 人天）
  - B. 不新增（YAGNI；F27 交付时再定）
  - 建议：A（轻量且为 F20 工具枚举预演）
  - **v1.1 补充**：实现形态定为**本地静态枚举**（不 ensure_kernel、不发 HTTP），与 F38 恒 HTTP 豁免命令先例一致（§4）。

- **Q3: 首批工具范围** ✅ 已确认（用户拍板：选项 A，2026-08-03）
  - A. 5 只读（**已拍板**——升级路径 v1.1 拍板口径）
  - B. 5 只读 + save_draft 提前（写工具设计未定，拆散 F27 闭环交付）
  - C. 8 全量（范围膨胀）
  - 建议：A
  - **v1.1 补充**：工具包装对象按源码核查修正（audit_chapter → F34、count_words → _word_count 纯函数、get_prior_summary → SummaryService.list_recent），见 §2.3 注。


---

## 附录：f51-agent-tools-v2（原独立 spec，容器化合并）

> 本章节由原 `specs/f51-agent-tools-v2/spec.md` 合并而来（2026-08-29 spec 目录重构）。

# F51: AI 工具面全量注册（阶段① 读+写）功能规格

**Spec 版本**: 1.0
**日期**: 2026-08-29
**依据**: adr/ADR-043.md（工具面矩阵 §1 + 分阶段 §4）+ PRD §6.1 + 源码枚举（2026-08-29 核实）
**所属阶段**: 0.12.1（工具面扩展第一批）
**关联 Issues**: #766（0.12.1）
**依赖**: ✅ F26 agent-tools（ToolSpec/Tool 模型 + build_reader_tools）· ✅ #748 设定库写工具（build_setting_write_tools）· ✅ F32/F33（相关服务已合入）· ✅ ADR-043（已合入 main）
**参考 ADR**: adr/ADR-043.md（工具面矩阵 + 删除授权模型 + 分阶段）
**状态**: 待实现 🔲
> **#838 统一工具目录与标记（2026-08-31 修订）**: 阶段①（读+写）与阶段②（删除 HITL）合入后，新增「统一工具目录」：
> `ALL_TOOL_SPECS`（`infrastructure/agent/tools/registry.py`）聚合全部 9 组 35 个工具（reader/save_draft/setting_write/setting_update/world_rw/memory/writing/delete/agent_chain），
> 每个 `ToolSpec` 加 `allow_custom_agent: bool = True`（能否被自定义 agent 勾选/调用）+ `is_core: bool = False`（系统内置核心工具，统一列表不展示/置灰）。
> 标记规则（2026-08-31 用户拍板）：`agent_run`/`agent_call`（agent 链）+ 7 个删除类（`delete_*`/`memory_remove`）= `allow_custom_agent=False, is_core=True`；
> `memory_*` 3 个 + `writing` 3 个（generate/continue/revise）暴露（保持默认暴露）；其余读写工具均默认暴露。
> `TOOL_REGISTRY` 保留为兼容别名 = `[s for s in ALL_TOOL_SPECS if s.allow_custom_agent]`（26 个，供 `_validate_tool_ids`/内置 seed/CLI `tools list` 消费）；`GET /agents/tools` 返回全量 35 个带双标记。
> 运行时物化（D7）：新增 `build_tools_by_ids(tool_ids, deps)` 按 tool_ids 白名单物化工具；chat 路径 `_run_single_agent`（deps_chat_agent.py:120）`tools=[]` 换物化结果。

> **模块类型声明**: 本 spec 为 ADR-043 落地细化的**增量契约**（非新变体），沿用 F26「deepagents 集成 + 工具定义型」的既有工具装配模式（Tool/ToolSpec/动态 deps 工厂），不加新实体表、不加新业务端点——只扩工具注册面与装配点。编号 F51 依据 ADR-019 Feature 表下一个空位（F49/F50 已占，F51 未被占）。

> **精简契约式**（2026-08-29 用户拍板）：本 spec 为既有模块（F26 工具面）的增量扩展，采精简契约结构（§1-§5），不套完整 13 节。

---

## 1. 工具面清单（ADR-043 §1 矩阵 + 源码枚举）

现状已注册工具（2026-08-29 源码核实）：`search_characters` / `check_foreshadowing` / `get_prior_summary` / `audit_chapter` / `count_words`（reader_tools `_TOOL_SPECS`）+ `save_draft`（save_draft_tool）+ `create_character` / `create_world_setting` / `create_outline`（setting_write_tools）。

| 域 | 工具 | 授权 | 状态 | 源码（service 方法核实） |
|---|---|---|---|---|
| 设定库·角色 | update_character | 写 | **新增** | character_service.update_character(character_id, CharacterUpdate) |
| 设定库·世界观 | update_world_setting | 写 | **新增** | world_service.update_setting(setting_id, WorldUpdate) |
| 设定库·大纲 | update_outline | 写 | **新增** | outline_service.update_outline(outline_id, OutlineUpdate) |
| 设定库·地图 | list_maps / create_map / update_map | 读/写 | **新增** | map_service.list_maps / create_map / update_map |
| 设定库·时间线 | list_timeline_events / create_timeline_event / update_timeline_event | 读/写 | **新增** | timeline_service.list_events / create_event / update_event |
| 设定库·伏笔 | create_foreshadowing / update_foreshadowing | 写 | **新增** | foreshadowing_service.create(ForeshadowingCreate) / update(id, ForeshadowingUpdate) |
| 记忆 | memory_list / memory_add / memory_update | 读/写 | **新增** | memory_service.list_preferences / create_preference / update_preference |
| 写作 | generate / continue / revise | 写 | **新增** | writing_service.generate_chapter / continue_writing / revise_content |
| agent 链 | agent_run / agent_call | 执行 | **新增** | agent_service.execute(PipelineExecuteRequest)（run）；call 语义见 §2.9 待拍板 |
| agent 链 | 修改 / 删除配置 | — | **❌ 不给**（D5） | 不在本期 |

> #838 更新（2026-08-31）：删除授权工具（delete_*/memory_remove 等 **7 个**）已入统一目录 `ALL_TOOL_SPECS`，但标记 `allow_custom_agent=False, is_core=True`——
> ① 不出现在自定义 agent 工具选择列表；② `_validate_tool_ids` 拒绝（自定义 agent 不可勾选）；③ 仍由装配期 per-conversation 删除授权（ADR-043 §3）守卫挂载。
> 工具命名已核对与既有 `_TOOL_SPECS`（reader/save_draft/setting_write）无冲突。

---

## 2. 各新增工具 ToolSpec 契约

统一约定（镜像既有工具，见 references 下 reader_tools/setting_write_tools 注释）：
- 每个工具 = `ToolSpec(name, description, input_schema)` + async `func(*args) -> str`（JSON 信封）。
- `project_id` 一律**不出现在 schema**——装配期由 deps.expected_project_id 闭包绑定（#680/#748 先例，LLM 不自报，防编造全零 UUID 落孤儿数据）。
- 成功信封：`{"ok": true, ...}`；失败信封：`{"ok": false, "error": "<异常消息>"}`；工具内部捕获一切 Exception 不抛出。
- 写类工具**成功/失败均落审计**（audit_service.record，actor="agent:chat"，审计调用自身异常静默）。
- func 签名保留可选 `project_id` shim（镜像 #748），但 schema 不含该键。

### 2.1 设定库·角色
- **update_character**：`description`="更新项目内角色设置（部分更新，未传字段保持不变）"，args=CharacterUpdate 字段（name?/personality?/background?/goals?/group_ids?），成功 `{"ok": true, "character_id": "<id>", "name": "<name>"}`。

### 2.2 设定库·世界观
- **update_world_setting**：`description`="更新项目内世界观设定条目（部分更新）"，args=WorldUpdate 字段（name?/category?/content?/parent_id?），成功 `{"ok": true, "setting_id": "<id>", "name": "<name>"}`。

### 2.3 设定库·大纲
- **update_outline**：`description`="更新项目内大纲条目（部分更新）"，args=OutlineUpdate 字段（name?/description?/sort_order?/level?/parent_id?/chapter_id?），成功 `{"ok": true, "outline_id": "<id>", "name": "<name>"}`。

### 2.4 设定库·地图（读+写）
- **list_maps**：读；`description`="列出项目内地图（可按根位置过滤/仅顶层）"，args(root_location_id?/top_level_only?)，成功 `{"ok": true, "data": [...]}`。
- **create_map**：写；`description`="创建项目内地图并写入设定库，返回新地图 id；同名活动地图会失败"，args(name/description?/root_location_id?)，成功 `{"ok": true, "map_id": "<id>", "name": "<name>"}`。
- **update_map**：写；`description`="更新地图元数据（部分更新；不换图）"，args(map_id/name?/description?)，成功 `{"ok": true, "map_id": "<id>"}`。

### 2.5 设定库·时间线（读+写）
- **list_timeline_events**：读；`description`="列出项目内时间线事件（可按关键字搜索/排序）"，args(search?/sort_by?)，成功 `{"ok": true, "data": [...]}`。
- **create_timeline_event**：写；`description`="创建时间线事件并写入设定库，返回新事件 id"，args(title/description?/time_value?/narrative_position?/location_id?)，成功 `{"ok": true, "event_id": "<id>", "title": "<title>"}`。
- **update_timeline_event**：写；`description`="更新时间线事件（部分更新）"，args(event_id/title?/description?/time_value?/narrative_position?)，成功 `{"ok": true, "event_id": "<id>"}`。

### 2.6 设定库·伏笔（写；读已有 check_foreshadowing）
- **create_foreshadowing**：写；`description`="创建伏笔并写入设定库，返回新伏笔 id；创建即 open"，args(title?/content/status?/priority?/location_id?)，成功 `{"ok": true, "foreshadowing_id": "<id>"}`。
- **update_foreshadowing**：写；`description`="更新伏笔（部分更新）"，args(foreshadowing_id/content?/status?/priority?)，成功 `{"ok": true, "foreshadowing_id": "<id>"}`。

### 2.7 记忆（读+写）
- **memory_list**：读；`description`="列出项目内记忆偏好（可按分类过滤）"，args(category?)，成功 `{"ok": true, "data": [...]}`。
- **memory_add**：写；`description`="添加一条记忆偏好并写入记忆库，返回新偏好 id"，args(category/pattern/note?)，成功 `{"ok": true, "preference_id": "<id>"}`。
- **memory_update**：写；`description`="更新一条记忆偏好（部分更新）"，args(preference_id/category?/pattern?/note?)，成功 `{"ok": true, "preference_id": "<id>"}`。

### 2.8 写作（写）
- **generate**：写；`description`="根据章节上下文生成正文（写入章节内容）"，args(request 对应 WritingRequest 字段)，成功 `{"ok": true, "chapter_id": "<id>", "word_count": N}`。
- **continue**：写；`description`="续写正文"，args(ContinueWritingRequest 字段)，成功 `{"ok": true, "chapter_id": "<id>", "word_count": N}`。
- **revise**：写；`description`="润色/改写正文"，args(RevisionRequest 字段)，成功 `{"ok": true, "chapter_id": "<id>", "word_count": N}`。

### 2.9 agent 链（执行；修改/删除配置不给 —— D5）
- **agent_run**：`description`="启动一次 agent 链管线执行"；args=PipelineExecuteRequest 字段（project_id?/pipeline? 等，依 DTO）；成功 `{"ok": true, "execution_id": "<id>", "status": "pending"}`。
- **agent_call**：执行单 agent 调用。⚠️ **签名待拍板**（见「待拍板」节）——默认建议 wrapper 直接调用 `agent_entity_service.get(list)` + 触发单 agent 执行，或复用 chat agent 单次 invoke；实现前须确认语义（本 spec 暂记为「待拍板：单 agent 调用语义」，体先行 run）。

---

## 3. 装配点（工具注入位）

新增工具按域**各自独立模块**（`infrastructure/agent/tools/<域>_tools.py`），每模块含：Params Pydantic 模型、ToolSpec/常量、Deps dataclass、`build_<域>_tools(deps) -> list[Tool]` 工厂。装配点四处：

| 装配点 | 现状 | 本批注入 |
|---|---|---|
| `api/deps_chat_agent.py::get_chat_agent_service` | `tools=[*reader_tools, save_draft_tool, *setting_write_tools]` | 追加 `[*setting_update_tools, *world_rw_tools, *memory_tools, *writing_tools, *agent_tools]` |
| `api/deps.py`（re-export getters + build_*） | import build_reader_tools/build_save_draft_tool/build_setting_write_tools + 各 service getter | 追加新 build_* re-export + 确认 get_map_service/get_timeline_service/get_foreshadowing_service 存在 |
| `api/deps.py::get_agentic_writer_service` → `infrastructure/agent/agentic_writer.py::build_agentic_writer` | `build_reader_tools(include=tool_ids)` + save_draft | 追加新工具组（agentic writer 工具面同步扩） |
| `domain/models/agent_tools.py` | ToolSpec（无权限字段） | **本批零改动**（权限守卫见 §4，字段留阶段②） |

> 工具面装配原则：**chat 系统级 Agent 全量注入**；agentic writer 注入「设定库读+写+记忆读」为主，写作/agent链 工具视语义（写作类与 agentic writer 自身写正文重叠，**待拍板** §候选 C）。

## 4. 权限守卫接口（删除授权 → 阶段②，本批仅留接口声明）

删除授权模型（ADR-043 §2）本批**不实现**，仅在本 spec 声明接口契约，供阶段②（删除HITL）落地：

```python
# domain/models/agent_tools.py 阶段② 追加（本批禁实现）
@dataclass
class ToolAuth:
    permission: str  # "manual" | "ask_once" | "auto"  （ADR-043 §3 权限状态域）
```

- 阶段①所有新增工具均**非删除类**（读/写），`authorization=` 隐式全量放行，无删除守卫。
- 阶段②：删除类工具默认不注册；守卫读 per-conversation 授权状态决定挂载/触发 HITL（deepagents `__interrupt__`，复用 #456）。**本批禁实现 delete_* / memory_remove 等 + 分段控件**（brief 硬约束）。

## 5. 验收标准（M1-Mn）

- **M1** 各新工具契约测试全绿（注册 + 调用 ok 信封 + 落库断言 + 失败信封覆盖）——`pytest tests/unit/test_<域>_tools.py`；新增测试文件须登记 ci.yml 对应后端 job。
- **M2** 装配点注入测试：deps_chat_agent 新工具组进 `tools=[...]`（mock 断言 build_* 被调 + 返回 Tool 列表）；agentic_writer 同步注入。
- **M3** 回归：既有全仓测试零回归（unit + tests/cli 分命令跑）；覆盖率门禁（CI 口径 98.5/95.0，本地复刻不破线）；`ci_cd/check_file_length.py 900` 对 deps.py/agentic_writer.py/新模块全过（>900 才失败）。
- **M4** spec-only PR 合入后 #766 仍 OPEN（`Part of #766` 非 `Closes`）。

---

## 待拍板问题（≤3，入 PR body 同步）

- **Q1: agent_call 单 agent 调用语义**（agent 链 "call"，§2.9）——A. 复用 agent_entity_service.get/list（配置已存在）+ 触发单 agent 执行（推荐：语义最贴合「执行单 agent」）；B. 复用 chat agent 单次 invoke（轻量但非独立 agent 链）；C. 本批仅 agent_run，call 延迟。**建议 A**：本 spec 默认 A，正文按 A 定稿；实现须以拍板为准。
- **Q2: agentic writer 是否注入写作类工具（generate/continue/revise）**——写作类与 agentic writer 自身「写正文」能力重叠，注入会造成工具面冗余 + 诱发 agent 自我调用。A. agentic writer 只加「设定读+写+记忆读」，写作工具只给 chat 系统级 Agent（推荐）；B. 全量注入。**建议 A**。
- **Q3: 地图/时间线/伏笔 读工具命名与分页**——list_maps / list_timeline_events 沿用 reader_tools `_fetch_all_pages` 分页模式（limit=50 循环），不引新分页机制；**建议维持**（实现确认）。

> **关联**：ADR-043（工具面矩阵 + 分阶段）· Issue #766（0.12.1）· spec 依据 F26 agent-tools（装配模式复用）。
> **范围边界**：阶段① 读+写工具已合入 main（§1-§5）；阶段② 删除 HITL 授权 + 分段控件 + 阶段③ agent 链调用见 §6-§7。

---

## 6. 阶段②：删除 HITL 授权（增量契约）

> ADR-043 §2-§3 落地细化。阶段① 全部合入 main 后，阶段② 交付删除类工具 + per-conversation 授权状态域 + HITL 中断 + 前端三态分段控件。

### 6.1 删除工具清单

| 域 | 工具 | 包装服务方法 | 备注 |
|---|---|---|---|
| 设定库·角色 | `delete_character` | character_service.hard_delete(id) | F9 已有 |
| 设定库·世界观 | `delete_world_setting` | world_service.hard_delete(id) | F10 |
| 设定库·大纲 | `delete_outline` | outline_service.hard_delete(id) | F11 |
| 设定库·地图 | `delete_map` | map_service.hard_delete(id) | F36，含 cleanup |
| 设定库·时间线 | `delete_timeline_event` | timeline_service.hard_delete(id) | F12 |
| 设定库·伏笔 | `delete_foreshadowing` | foreshadowing_service.hard_delete(id) | F13 |
| 记忆 | `memory_remove` | memory_service.delete_preference(id) | F28 |

> 删除工具**不进静态 TOOL_REGISTRY**（CLI tools list 不枚举），由装配期守卫决定是否注册。

### 6.2 权限状态域

```python
# domain/models/agent_tools.py 追加
@dataclass
class ToolAuth:
    """删除授权状态——per-conversation，由前端分段控件设置。"""
    delete_permission: str = "manual"  # "manual" | "ask_once" | "auto"
```

- **manual**（默认）：删除工具**不注册**，AI 无法调用删除。
- **ask_once**：删除工具注册；AI 调用删除 → 工具内部触发 `interrupt()`（deepagents HITL）→ 前端呈现确认弹窗 → 用户批准/拒绝**本次** → 结果回灌继续。批准后**本次**执行删除，不升级为 auto。
- **auto**：删除工具注册；AI 调用删除**直接执行**，不触发 HITL。

### 6.3 HITL 中断机制

复用 F44 `book_agentic_pipeline.py` 的 `interrupt()` 模式（ADR-043 §2 复用 #456）：

```python
# 删除工具 func 内部（ask_once 模式）：
from langgraph.types import interrupt
payload = {"tool": "delete_character", "entity_id": "<id>", "entity_name": "<name>"}
decision = interrupt(payload)  # 暂停，等待用户响应
if not decision.get("approved"):
    return json.dumps({"ok": False, "error": "用户拒绝删除"}, ensure_ascii=False)
# 批准 → 执行删除
```

- **ChatAgentService 扩展**：`stream_events` 遇 `__interrupt__` 帧 → 发送 `interrupt` SSE 帧（`type: "interrupt"`, `payload: {...}`）→ 前端弹窗。
- **resume 端点**：`POST /chat/resume` body `{conversation_id, approved: bool}` → ChatAgentService 调用 `agent.invoke(..., command=Command(resume={"approved": approved}))` 续跑。
- **auto 模式**：工具 func 直接执行删除，不 interrupt。

### 6.4 前端三态分段控件

ChatPanel 工具调用区域新增**分段控件**（非下拉、非闪电按钮）：

```
[手动] [一次确认] [全自动]
```

- 控件形态：三按钮分段组（`SegmentedControl` 风格），选中态高亮，未选低对比度。
- 文案/状态映射（i18n）：
  - `manual` → `write.chat.deleteMode.manual`（默认；「删除不可用」tooltip）
  - `ask_once` → `write.chat.deleteMode.askOnce`（「每次删除需确认」tooltip）
  - `auto` → `write.chat.deleteMode.auto`（「AI 可直接删除」tooltip）
- 控件变更 → `PATCH /chat/conversations/{id}` body `{delete_permission: "<mode>"}` → 后端更新 conversation 级权限状态。
- HITL 确认弹窗：interrupt SSE 帧到达 → 渲染确认弹窗（实体名 + 删除确认/取消按钮）→ 用户点击 → `POST /chat/resume`。

### 6.5 装配点改动

| 装配点 | 改动 |
|---|---|
| `deps_chat_agent.py::get_chat_agent_service` | 读 conversation 的 `delete_permission`；manual 时不注入删除工具；ask_once/auto 时注入删除工具（func 按 mode 分支 interrupt 或直接执行） |
| `api/chat_stream.py` | `stream_events` 检测 `__interrupt__` 帧 → 发 interrupt SSE 帧 |
| 新增 `api/chat_resume.py` | `POST /chat/resume` 端点 |
| `domain/models/conversation.py` | Conversation 模型加 `delete_permission: str = "manual"` 字段 |
| 前端 `ChatPanel.tsx` | 加分段控件 + HITL 确认弹窗 |

### 6.6 验收标准（阶段②）

- **M5** 删除工具契约测试（7 工具正例/拒绝/异常 → JSON 信封）——`pytest tests/unit/test_delete_tools.py`
- **M6** HITL 中断 + resume 测试（ask_once → interrupt → approve → 删除成功；reject → 不删除）——`pytest tests/unit/test_delete_hitl.py`
- **M7** 装配守卫测试（manual 不注入删除工具；auto 注入且不 interrupt）——`pytest tests/unit/test_delete_assembly.py`
- **M8** 前端 vitest（分段控件三态切换 + PATCH + HITL 弹窗 + resume 调用）——`vitest ChatPanel.delete-auth.test.tsx`
- **M9** 回归零失败

---

## 7. 阶段③：agent 链调用工具（增量契约）

> ADR-043 D5 结论：agent 链**修改/删除配置不给 AI**——只给「执行/调用」。

### 7.1 工具清单

| 工具 | 包装服务方法 | 说明 |
|---|---|---|
| `agent_run` | agent_service.execute(PipelineExecuteRequest) | 启动一次 agent 链管线执行 |
| `agent_call` | agent_entity_service.get + 单 agent 执行 | 调用单个 agent（Q1=A 拍板：复用 agent_entity_service） |

### 7.2 ToolSpec 契约

- **agent_run**：`description`="启动一次 agent 链管线执行"；args=PipelineExecuteRequest 字段（project_id 由 deps 绑定，schema 不含）；成功 `{"ok": true, "execution_id": "<id>", "status": "pending"}`。
- **agent_call**：`description`="调用单个 agent 执行一次任务"；args=`{agent_id: str, input: str}`；成功 `{"ok": true, "result": "<输出文本>"}`。

> agent 链配置修改/删除（roles/order/relations CRUD）**不给 AI**（D5）——属元配置，风险高。

### 7.3 装配点

- `deps_chat_agent.py`：注入 `agent_run` + `agent_call`（与阶段①工具同批装配）。
- `agent_run` 包装 agent_service.execute——与 F4 管线执行同源。
- `agent_call` 包装 agent_entity_service——读配置后单 agent 执行。

### 7.4 验收标准（阶段③）

- **M10** agent_run/agent_call 契约测试——`pytest tests/unit/test_agent_chain_tools.py`
- **M11** 装配注入测试——mock 断言 build_agent_chain_tools 被调
- **M12** 回归零失败

## 14. 动作确认

> 每个端点/命令的完整状态流表（基于 §3 + §4 + §5 + §7 事实，不重复）。F26 为内部基础设施，无新增 REST 端点（§3）——端点面保持现状，状态流表聚焦工具装配/执行与 CLI 诊断命令。

### 14.1 工具装配与执行状态流

| 场景 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| 装配（build_deep_agent） | model/api_key/base_url 齐备 | parse_model_string 剥离 registry 前缀 → ChatOpenAI 实例直传 create_deep_agent | Agent 装配成功 | 模型名带前缀未剥离 → zhipu API 拒绝 | HarnessProfile key 必须 openai:&lt;model&gt;，不匹配 → 「No harness profile matched」警告 + 静默默认 profile |
| LLM 调用工具（ReAct 循环内） | 工具已注册（TOOL_REGISTRY 5 只读） | Tool.func 异步执行（只读、不落库） | 返回文本 → ToolMessage 回填，deepagents 循环继续 | 工具内部异常 → 返回错误文本回填，循环不中断 | 参数 schema 校验失败 → deepagents 框架层校验回填；服务 404（项目/章节不存在）→ 错误文本 |
| excluded_tools 禁用默认 FS 工具 | — | create_deep_agent 传 excluded_tools | 工具面只剩 task + 自定义工具 | — | 默认 FS 工具名清单待 F26 实现确认（以 deepagents 0.7.5 源码 default tools 列表为准） |
| subagent task 工具 | — | 不装配 SubAgentMiddleware（或不传 subagents 参数） | F26 无 subagent 能力 | — | F29 0.8.0 恢复（届时 spec 定义装配参数） |

### 14.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow agent tools list [--json] | 无 | 本地静态枚举 TOOL_REGISTRY（不 ensure_kernel、不发 HTTP） | 退出码 0 + 5 工具信封（name/description/input_schema，§13 M3） | 退出码 1（运行错误） | 退出码 2（参数错误）；无工具注册 → 空 items 信封退出码 0（防御性，注册表恒非空） |

> 注：附录 f51（阶段① 工具面，已合入）起 TOOL_REGISTRY 扩展为完整 6 工具目录（含 save_draft 静态 spec，§2.3）——CLI 输出以注册表实际为准；§13 M3 的「5 工具信封」为 F26 交付基线契约。

### 14.3 验收锚点

- A1：CLI tools list --json 输出工具信封 + ensure_kernel 未被调用（M3）
- A2：装配测试 mock ChatOpenAI 直传 + HarnessProfile key openai:&lt;model&gt; + excluded_tools 传参断言（M1）
- A3：模型名剥离 zhipu/glm-4.5 → glm-4.5（M1）
- A4：5 工具各 1 正例 + 1 异常（service 抛错 → 错误文本，M2）
- A5：真实模型冒烟 build_deep_agent 单次 invoke 返回正确 tool_calls（M5，手工）
