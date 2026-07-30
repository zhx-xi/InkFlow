# InkFlow — 架构分析与决策记录（v2.0）

**日期**: 2026-07-31（v2.0 更新：引入 LangChain 全家桶）
**前版**: v1.0（2026-07-30，LiteLLM + 自定义 Pipeline）
**依据**: `docs/prd-inkflow-v2.1-2026-07-30.md` + 产品愿景扩展
**作者**: 软件架构师

> **v2.0 核心变更**：将 LLM Provider 抽象从裸 LiteLLM 迁移到 LangChain `ChatLiteLLM`，Agent 编排从自定义 Pipeline 迁移到 LangGraph `StateGraph`，RAG 层引入 LangChain Chroma + sentence-transformers。

---

## 核心约束回顾

从 PRD 中提取的 7 个关键约束，所有架构决策必须在此之内：

| # | 约束 | 影响 |
|---|------|------|
| C1 | **单人开发**（1 FTE） | 微服务不可行，架构复杂度必须与团队规模匹配 |
| C2 | **本地优先**（Phase 1-3 不部署云端） | SQLite 持久化、免认证、零外网依赖（除 LLM API） |
| C3 | **三界面共存**：CLI + REST API + MCP | 业务逻辑必须与界面解耦，同一 Service 为三个界面复用 |
| C4 | **Protocol-first** 云端接口预留 | 接口（Protocol/ABC）在 Phase 1 定义，云端实现在 Phase 4+ |
| C5 | **SDD + TDD 工作流** | 架构文档作为 SDD 的一部分；测试覆盖率 ≥ 70% |
| C6 | **Phase 1 纯后端** | 前端（React）Phase 2 再启动；API 契约先行 |
| C7 | **24 周时间线** | 每个 ADR 选择"够用且容易改变"的方案，而非"最优雅"的方案 |

---

## 一、架构风格选择

```
模 块 化 单 体（Modular Monolith）
│
├── 适合：单人开发，边界逐渐清晰
├── 避免：微服务的运维负担、分布式调试、网络延迟
├── 保留：模块间严格接口隔离，为将来拆分做准备
└── 过渡路径：当某个模块需要独立扩展时，从模块→服务（如 Phase 4 的 Auth → 独立服务）
```

### 选型矩阵

| 维度 | 模块化单体 | 微服务 | 解释 |
|------|-----------|--------|------|
| 开发效率（单人） | ✅ 高 | ❌ 低 | 微服务 3 个服务 = 3 倍 CI/CD/调试开销 |
| 未来可拆分性 | ✅ 接口隔离 | ✅ 天然 | 模块化单体 + 好接口 = 可拆分 |
| 运维复杂度 | 🟢 低 | 🔴 高 | 1 个进程 vs N 个进程 + 服务发现 + 链路追踪 |
| 故障隔离 | 🟡 进程内 | ✅ 进程间 | 单体架构单进程故障影响全局 |
| 分布式事务 | 无 | 需要 Saga | 单体只需数据库事务 |
| 团队匹配度 | ✅ 单人 | ❌ 需要 > 3 人 | Conway 定律：架构复制沟通结构 |

**决策**: 模块化单体，但模块间通过明确的 `Protocol`（接口）通信。

---

## 二、分层架构

```
┌────────────────────────────────────────────────────────────────┐
│                     Presentation Layer                         │
│   ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐    │
│   │  FastAPI     │  │  Typer CLI   │  │  MCP Server       │    │
│   │  REST + SSE  │  │  (inkflow)   │  │  (stdio, F20)     │    │
│   │  (P0-01)     │  │  (F7, P0-09) │  │  (P1-11)          │    │
│   └──────┬──────┘  └──────┬───────┘  └────────┬──────────┘    │
│          │                 │                    │               │
│          ▼                 ▼                    ▼               │
│   ┌────────────────────────────────────────────────────────┐   │
│   │                 Application Layer                       │   │
│   │  Request DTO → 调用 Service → 返回 Response DTO        │   │
│   │  依赖注入中间层：将 Service 注入到 Router/CLI/MCP 中    │   │
│   └──────────────────────┬─────────────────────────────────┘   │
│                          │                                      │
│                          ▼                                      │
│   ┌────────────────────────────────────────────────────────┐   │
│   │                   Domain Layer                          │   │
│   │                                                         │   │
│   │   ┌──────────────────┐  ┌─────────────────────────┐    │   │
│   │   │  Services         │  │  Domain Models          │    │   │
│   │   │  (业务编排)       │  │  (聚合/实体/值对象)      │    │   │
│   │   │  project/chapter  │  │  Project/Chapter/Volume  │    │   │
│   │   │  writing/agent    │  │  Character/World/Outline  │   │   │
│   │   │  context/llm      │  │  Foreshadowing/Timeline  │    │   │
│   │   └────────┬─────────┘  └─────────────────────────┘    │   │
│   │            │                                            │   │
│   │   ┌────────▼─────────────────────────────────────────┐  │   │
│   │   │  Ports（出站接口 / Protocol 定义）                  │  │   │
│   │   │  ProjectRepositoryProtocol                        │  │   │
│   │   │  LLMClientProtocol │ AgentPipelineProtocol        │  │   │
│   │   │  VectorStoreProtocol │ PromptTemplateProtocol      │  │   │
│   │   │  AuthProtocol │ StorageProtocol (Phase 4+)         │  │   │
│   │   └───────────────────────────────────────────────────┘  │   │
│   └──────────────────────┬─────────────────────────────────┘   │
│                          │                                      │
│                          ▼                                      │
│   ┌────────────────────────────────────────────────────────┐   │
│   │                 Infrastructure Layer                     │   │
│   │                                                         │   │
│   │   ┌────────────┐  ┌──────────┐  ┌────────────────┐    │   │
│   │   │ SQLAlchemy  │  │ LangChain│  │ Chroma         │    │   │
│   │   │ Repository  │  │ LLM      │  │ Vector Store   │    │   │
│   │   │ (SQLite)    │  │ Client   │  │ (本地 RAG)     │    │   │
│   │   └────────────┘  └──────────┘  └────────────────┘    │   │
│   │                                                         │   │
│   │   ┌────────────┐  ┌──────────┐  ┌────────────────┐    │   │
│   │   │ LangGraph   │  │ Prompt   │  │ LocalFile      │    │   │
│   │   │ Pipeline    │  │ Manager  │  │ Storage        │    │   │
│   │   │ (Agent 编排)│  │ (模板)   │  │                │    │   │
│   │   └────────────┘  └──────────┘  └────────────────┘    │   │
│   │                                                         │   │
│   │   ┌────────────┐  ┌──────────┐  ┌────────────────┐    │   │
│   │   │ Cloud Repo │  │ Cloud    │  │ CloudStorage   │    │   │
│   │   │ (PG, F2F)  │  │ Auth     │  │ (Phase 4+)     │   │   │
│   │   └────────────┘  └──────────┘  └────────────────┘    │   │
│   └────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────┘
```

**层级职责**:

| 层 | 目录 | 职责 | 依赖 |
|---|------|------|------|
| Presentation | `api/` `cli/` `mcp/` | HTTP 路由 / CLI 命令 / MCP 工具；DTO 转换 | → Application |
| Application | (可选，当前并入 Domain) | 请求编排、事务边界 | → Domain |
| Domain | `services/` `models/` `ports/` | 业务逻辑、领域模型、Protocol 定义 | **零框架依赖** |
| Infrastructure | `infrastructure/` | SQLAlchemy Repository、LangChain LLM Client、LangGraph Pipeline、Chroma VectorStore | → Domain Ports |

**关键规则**：

```
✅ 允许：所有层可以依赖 domain/models（纯数据对象）
✅ 允许：infrastructure/ 导入 langchain_*
❌ 禁止：domain/ 导入 FastAPI、Typer、SQLAlchemy、LangChain、任何框架
❌ 禁止：domain/ 导入 infrastructure/
❌ 禁止：两个 domain service 互相循环导入
```

---

## 三、架构决策记录（ADR）

---

### ADR-001: 模块化单体 + 严格接口隔离

**状态**: 已接受

**背景**: 单人开发，24 周时间线。PRD 要求三个界面（CLI/REST/MCP）共享同一业务逻辑，且为云端迁移预留接口。

**决策**: 采用模块化单体（Modular Monolith），模块之间通过 `typing.Protocol`（Python 结构化子类型）定义接口边界，基础设施实现可替换。

**备选方案**:
| 方案 | 优点 | 缺点 |
|------|------|------|
| 模块化单体（选定） | 开发效率高、单进程调试、数据库事务简单、可逐步拆分 | 单进程故障影响全局 |
| 微服务 | 独立部署、故障隔离 | 单人运维 3+ 服务不可行 |
| 纯单体（无模块边界） | 最快起步 | 无法演进，后期重构风险高 |

**影响**:
- ✅ Service 层可实现 CLI/REST/MCP 三界面复用
- ✅ Protocol 定义清晰，云端迁移有据可依
- ❗ 需建立架构适应度函数，防止模块间循环依赖
- ❗ 需纪律性维护模块边界

---

### ADR-002: Clean/Hexagonal 风格分层

**状态**: 已接受

**背景**: 三种界面类型（CLI/REST/MCP）共享同一业务逻辑，且本地实现与云端实现可替换。

**决策**: 采用六边形架构风格，依赖方向始终指向 Domain 层：
```
Presentation → Application → Domain ←→ Infrastructure
                                    ↑ 依赖倒置
                               Ports (Protocols)
```

**影响**:
- ✅ 三界面共享 Service 层，业务逻辑不重复
- ✅ Infrastructure 可替换（SQLite ↔ PG、LangChain ↔ 其他、LocalAuth ↔ JWT）
- ✅ 测试时可注入 Mock 实现，无需实际 LLM API 或数据库
- ❗ 增加初始代码量（接口定义 + 依赖注入）
- ❗ 单人开发下需克制"过度抽象"倾向（Rule of Three）

---

### ADR-003: Repository 模式封装 SQLAlchemy

**状态**: 已接受

**背景**: SQLAlchemy 2.0 async + SQLite 作为本地持久化方案。PRD 要求测试覆盖率 ≥ 70%，数据库层需可 mock。

**决策**: 使用 Repository 模式封装 SQLAlchemy Session，Repository 实现 `ProjectRepositoryProtocol` 接口。

```
Service → ProjectRepositoryProtocol (Port) ← SQLAlchemyRepository (Adapter)
```

**设计原则**:
1. Repository 接收和返回领域模型（Pydantic models），而非 ORM 模型
2. SQLAlchemy ORM 模型作为 Repository 内部实现细节，不泄漏到 Service 层
3. CRUD + 自定义查询方法以 Protocol 定义类型签名

**影响**:
- ✅ 测试时可注入 MockRepository，不依赖真实数据库
- ✅ Domain 层不依赖 SQLAlchemy，降低耦合
- ❗ ORM ↔ Domain Model 转换有性能开销（但 SQLite 场景可忽略）
- ❗ 对简单 CRUD 场景，多了一层抽象

---

### ADR-004: Pydantic v2 作为统一数据契约

**状态**: 已接受

**背景**: FastAPI 和 Typer 都原生使用 Pydantic；PRD 要求数据验证类型安全。

**决策**: Pydantic v2 模型贯穿全栈：
- **Domain Models**: 业务实体、值对象（Pydantic `BaseModel`）
- **Request/Response DTOs**: API 输入输出（FastAPI 自动校验/序列化）
- **CLI 参数**: Typer 自动从 Pydantic 字段生成 help/validation
- **配置**: `pydantic-settings` 管理环境配置

**影响**:
- ✅ 一份模型定义，三界面自动生成校验/文档/序列化
- ✅ Pydantic v2 性能大幅提升（Rust 内核）
- ❗ SQLAlchemy ORM 与 Pydantic 模型之间存在映射代码

---

### ~~ADR-005: LLM Provider — LiteLLM 统一对接~~（v1.0，已被 ADR-005v2 取代）

**状态**: 已弃用 · 被 ADR-005v2 取代 · 🟡 风险等级：低（未实现，无迁移成本）

**v1.0 决策**: 薄 Protocol 包装 LiteLLM，~50 行代码覆盖 100+ Provider。

**弃用原因**: LiteLLM 裸调方案虽然轻量，但缺乏 LangChain 生态的 callback 体系、LCEL 管道组合能力和 LangSmith 调试追踪，限制了复杂 Agent 管线的可观测性和可组合性。

---

### ADR-005v2: LLM Provider — LangChain ChatLiteLLM

**状态**: 已接受（替代 ADR-005 v1.0）· 🟢 风险等级：低-中

**背景**:
1. PRD 要求 ≥ 3 个 Provider（OpenAI、DeepSeek、Ollama），不同任务路由不同模型
2. 复杂 Agent 管线需要统一的 callback 体系和可观测性（LangSmith）
3. ChatLiteLLM 同时继承 LiteLLM 的 Provider 覆盖和 LangChain 的 `BaseChatModel` 接口

**决策**: 使用 LangChain `ChatLiteLLM` 作为 LLM 客户端实现，通过 `LLMClientProtocol` 隔离领域层。

```
domain/ports/llm_client.py           ← LLMClientProtocol (纯 Python)
infrastructure/llm/langchain_client.py  ← LangChainLLMClient (实现 Protocol，内部使用 ChatLiteLLM)
```

**为什么是 ChatLiteLLM 而不是 ChatOpenAI？**

| 选项 | 优点 | 缺点 |
|------|------|------|
| **ChatLiteLLM（选定）** | 继承 LiteLLM 的 100+ Provider 覆盖 + 实现 LangChain `BaseChatModel` 接口，获得 callback 和 LangSmith | 多一层依赖 |
| ChatOpenAI + ChatAnthropic 各自 | 原生 LangChain 集成 | 每个 Provider 一个类，切换模型需改代码 |
| 裸 LiteLLM（v1.0 方案） | 最轻量 | 无法利用 LangChain 的 callback 和 LangSmith 生态 |

**关键接口**：

```python
# domain/ports/llm_client.py — 零框架依赖
class LLMClientProtocol(Protocol):
    async def chat(self, messages: list[ChatMessage], *, model: str | None = None, ...) -> ChatResponse: ...
    def chat_stream(self, messages: list[ChatMessage], *, model: str | None = None, ...) -> AsyncIterator[StreamEvent]: ...
    async def count_tokens(self, messages: list[ChatMessage], *, model: str | None = None) -> int: ...

# infrastructure/llm/langchain_client.py — LangChain 实现
class LangChainLLMClient:
    def _get_model(self, model: str) -> BaseChatModel:
        return ChatLiteLLM(model=model, callbacks=self._callbacks)
```

**影响**:
- ✅ 保留 LiteLLM 100+ Provider 覆盖（ChatLiteLLM 底层仍是 litellm）
- ✅ 获得 LangSmith 调试追踪、LCEL 管道、LangChain callback 体系
- ✅ 测试时注入 Mock 实现，不依赖 LangChain
- ❗ LangChain 版本升级可能有 breaking changes（pin minor 版本 + CI 检测）
- ❗ 增加 ~5 个 LangChain 包的依赖体积（~数十 MB）
- ❗ Domain `ChatMessage`/`ChatResponse` 需与 LangChain 的 `AIMessage` 做薄转换

---

### ~~ADR-006: Agent 编排 — 管道链模式（Pipeline Chain）~~（v1.0，已被 ADR-006v2 取代）

**状态**: 已弃用 · 被 ADR-006v2 取代 · 🟡 风险等级：低（未实现，无迁移成本）

---

### ADR-006v2: Agent 编排 — LangGraph StateGraph

**状态**: 已接受（替代 ADR-006 v1.0）· 🟡 风险等级：中

**背景**:
1. PRD 要求 Architect→Writer→Auditor→Reviser 链式执行（F4）
2. 后续规划：用户自定义 Agent 管线（DAG + 条件分支）
3. LangGraph 的 StateGraph 天然支持从顺序链到 DAG 的渐进式升级

**决策**: 使用 LangGraph `StateGraph` 作为 Agent 管线引擎，通过 `AgentPipelineProtocol` 隔离领域层。

```
domain/ports/agent_pipeline.py          ← AgentPipelineProtocol (纯 Python)
infrastructure/agent/langgraph_pipeline.py  ← LangGraphAgentPipeline (实现 Protocol)
```

**Phase 1: 固定顺序链（Architect → Writer → Auditor → Reviser）**
```python
# LangGraph 构建（内部）
workflow = StateGraph(PipelineState)
workflow.add_node("architect", architect_node)
workflow.add_node("writer", writer_node)
workflow.add_node("auditor", auditor_node)
workflow.add_node("reviser", reviser_node)
workflow.add_edge("architect", "writer")
workflow.add_edge("writer", "auditor")
workflow.add_edge("auditor", "reviser")
workflow.add_edge("reviser", END)
workflow.set_entry_point("architect")
app = workflow.compile()
```

**Phase 2: 用户自定义 DAG（从 YAML 配置动态构建 StateGraph）**
```yaml
pipeline:
  stages:
    - id: world_building
      agent: world_architect
      output_to: [outline]
    - id: outline
      agent: outline_writer
      output_to: [chapter_write, foreshadow_plant]  # 并行分支
    - id: chapter_write
      agent: chapter_writer
      output_to: [style_review]
    - id: foreshadow_plant
      agent: foreshadow_agent
      output_to: []  # 不阻塞主链
```

**与 v1.0 方案对比**:
| 维度 | v1.0 自定义 Pipeline | v2.0 LangGraph |
|------|---------------------|----------------|
| Phase 1 复杂度 | ~200 行 | ~200 行（LangGraph 声明式更短） |
| Phase 2 DAG 升级 | 需要重写拓扑排序、并行调度 | 只需改 `add_edge` → `add_conditional_edges` |
| 可观测性 | 需自建日志/追踪 | LangSmith 内置追踪 |
| Checkpointing | 需自己实现 | LangGraph 内置（管线中断可恢复） |
| 错误处理 | 需自己实现重试逻辑 | LangGraph 内置 + 自定义 fallback |

**影响**:
- ✅ Phase 1 代码量与自定义方案相当，但 Phase 2 扩展成本大幅降低
- ✅ LangGraph checkpointing → 管线中断可恢复（对 daemon 后台写作很重要）
- ❗ LangGraph 处于快速迭代期（v0.2），API 可能变化（pin 版本 + 薄 Protocol 隔离）
- ❗ 新手需要理解 StateGraph / Node / Edge 等概念，有上手成本

---

### ADR-007v2: 项目包结构（更新版）

**状态**: 已接受

**v2.0 变更**: infrastructure 层新增 `llm/`、`agent/`、`rag/` 目录，domain/ports 新增 4 个 Protocol。

```
backend/src/inkflow/
├── __init__.py
├── __main__.py

├── api/                            # FastAPI 路由（Presentation）
│   ├── app.py / deps.py
│   └── routers/ (project, chapter, writing, agent, health)

├── cli/                            # Typer CLI（Presentation）
│   └── commands/ (project, chapter, write, serve)

├── mcp/                            # MCP Server（Phase 3）
│   └── tools/

├── domain/                         # Domain 层（零框架依赖）
│   ├── models/                     # Pydantic 领域模型
│   │   └── (project, chapter, character, agent, ...)
│   ├── services/                   # 业务服务
│   │   └── (project, chapter, writing, agent, context, ...)
│   ├── ports/                      # 出站接口（Protocol 定义）
│   │   ├── project_repository.py   # F1 (已实现)
│   │   ├── llm_client.py           # ADR-005v2 🆕
│   │   ├── agent_pipeline.py       # ADR-006v2 🆕
│   │   ├── vector_store.py         # ADR-013 🆕
│   │   └── prompt_template.py      # ADR-014 🆕
│   └── exceptions.py

├── infrastructure/                 # 基础设施（Adapter 实现）
│   ├── database/                   # SQLAlchemy + SQLite
│   │   ├── models/                 # ORM 模型
│   │   └── repositories/           # Repository 实现
│   ├── llm/                        # LangChain LLM Client 🆕
│   │   └── langchain_client.py     # ChatLiteLLM 封装
│   ├── agent/                      # LangGraph Agent Pipeline 🆕
│   │   └── langgraph_pipeline.py   # StateGraph 封装
│   ├── rag/                        # RAG 检索 🆕
│   │   └── langchain_vector_store.py  # Chroma + BGE Embedding
│   ├── prompt/                     # Prompt 模板管理 🆕
│   │   └── langchain_prompt_manager.py  # ChatPromptTemplate + YAML
│   ├── auth/local_trust.py
│   └── storage/local_file_storage.py

├── core/                           # 共享基础设施
│   ├── config.py                   # Pydantic Settings（LangChain 配置）
│   ├── database.py / log.py

└── prompts/                        # Agent Prompt 模板（YAML）
    ├── architect.yaml
    ├── writer.yaml
    ├── auditor.yaml
    └── reviser.yaml
```

**影响**:
- ✅ infrastructure 层按技术实现分目录（llm/agent/rag/prompt），业务模块在 domain 层
- ✅ 每个 infrastructure 子模块可独立替换（如换 RAG 方案只需改 rag/ 目录）
- ❗ 文件数量增加（~70+ 文件）

---

### ADR-008: 配置管理 — Pydantic Settings 分层配置

**状态**: 已接受（v2.0 扩展了 LLM/RAG 配置项）

**更新**: 新增以下配置分组：
- **LangSmith**: API Key、项目名、启用开关
- **Embedding**: 模型名（`BAAI/bge-small-zh-v1.5`）、推理设备
- **向量库**: chromadb 持久化路径、collection 列表
- **LLM 超时/重试**: 请求超时、最大重试次数

详见 `backend/src/inkflow/core/config.py`。

---

### ADR-009: 依赖注入策略

**状态**: 已接受（不变）

---

### ADR-010: 上下文管理 — 分层 Token 预算 → RAG 增强

**状态**: 已接受（Phase 1 仍用 Token 预算，Phase 2 引入 RAG）

**v2.0 变更**: ADR-013（RAG）作为 Phase 2 的补充方案。Phase 1 先用 Token 预算模型保证基础可用，Phase 2 用 RAG 替换"Compressible"层的摘要注入，实现精确语义检索。

---

### ADR-011: 异步无阻塞架构

**状态**: 已接受（不变）

---

### ADR-012: 错误处理策略

**状态**: 已接受（v2.0 扩展了 LLM/RAG 相关异常类型）

**v2.0 扩展**: 新增异常类型：
- `LLMRequestError`: LLM API 调用失败（网络/超时/Provider 错误）
- `ContextBudgetExceededError`: Token 预算超限
- `AgentPipelineError`: Agent 管线执行失败
- `VectorStoreError`: 向量库操作失败
- `PromptRenderError`: Prompt 模板渲染失败

---

### ADR-013: RAG 检索 — LangChain Chroma + 本地 Embedding 🆕

**状态**: 已接受 · 🟡 风险等级：中 · Phase 2 实现

**背景**:
1. 长篇小说的上下文管理不能只靠 Token 预算——写第 50 章时需要第 3 章埋的伏笔，但早已被挤出上下文窗口
2. 角色一致性、世界设定连贯性、伏笔追踪需要精确的语义检索
3. PRD F6 的"分层上下文"在 Token 预算模型下是粗粒度的，RAG 提供细粒度补充

**决策**: 使用 **LangChain Chroma**（chromadb 的 LangChain 集成）+ **sentence-transformers** 本地 Embedding 模型。

```
domain/ports/vector_store.py              ← VectorStoreProtocol (纯 Python)
infrastructure/rag/langchain_vector_store.py  ← LangChainVectorStore (实现 Protocol)
```

**为什么本地 Embedding 而不是 API？**
| 方案 | 成本 | 延迟 | 隐私 | 中文效果 |
|------|------|------|------|---------|
| **BAAI/bge-small-zh-v1.5（选定）** | 免费 | < 10ms | ✅ 本地 | ⭐⭐⭐⭐⭐ MTEB 中文榜首 |
| OpenAI text-embedding-3-small | ~$0.02/1M tokens | ~100ms | ❌ 数据离开本地 | ⭐⭐⭐⭐ |
| 不做 RAG（纯 Token 预算） | — | — | — | 长篇小说一致性无法保证 |

**RAG 实体类型**:
| EntityType | 索引内容 | 检索触发时机 |
|-----------|---------|------------|
| `character` | 角色档案（姓名、外貌、性格、关系） | 该角色在当前章节出现时 |
| `setting` | 世界设定（地点描述、规则、文化） | 当前章节场景切换时 |
| `foreshadowing` | 伏笔（已埋设/已回收） | 每次写作调用时检索未回收伏笔 |
| `timeline_event` | 时间线事件 | 写作涉及时间跳跃时 |
| `chapter_chunk` | 章节文本块（~500 字/chunk） | 需要前文精确引用时 |

**实现预览**:
```python
class LangChainVectorStore:
    def __init__(self, persist_dir: Path):
        self._embeddings = HuggingFaceBgeEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        self._stores: dict[str, Chroma] = {
            "character": Chroma(
                collection_name="characters",
                embedding_function=self._embeddings,
                persist_directory=str(persist_dir / "characters"),
            ),
            # ... 每种实体类型一个 collection
        }

    async def retrieve(self, query, *, project_id, entity_types, top_k=10):
        # 多 collection 联合检索 → 按 relevance 排序 → 返回 top_k
        ...
```

**影响**:
- ✅ 长篇小说一致性保障，是竞品没有的差异化功能
- ✅ 全本地运行，零额外 API 费用
- ✅ 首次运行自动下载 Embedding 模型（~100MB，仅一次）
- ✅ LangChain Chroma 提供统一的 VectorStore 接口
- ❗ Embedding 模型首次下载需网络（首次安装时自动处理）
- ❗ chromadb 持久化会增加磁盘占用（每项目 ~10-50MB）
- ❗ RAG 检索延迟约 10-50ms（本地 + CPU），不影响 LLM 调用的大头延迟

---

### ADR-014: Prompt 模板管理 — LangChain ChatPromptTemplate 🆕

**状态**: 已接受 · 🟢 风险等级：低 · Phase 1 实现

**背景**: 项目有多个 Agent 角色（Architect/Writer/Auditor/Reviser）和后续用户自定义角色，每个角色有独立的 Prompt 模板。需要统一的模板加载、变量注入、验证机制。

**决策**: 使用 LangChain `ChatPromptTemplate` 管理模板，通过 `PromptTemplateProtocol` 隔离领域层。

```
domain/ports/prompt_template.py              ← PromptTemplateProtocol
infrastructure/prompt/langchain_prompt_manager.py  ← LangChainPromptManager
prompts/*.yaml                                ← 模板文件
```

**模板格式（YAML）**:
```yaml
# prompts/writer.yaml
name: writer
description: 小说章节写手 — 根据大纲和上下文创作正文
system_prompt: |
  你是一位资深{genre}小说作家，笔名「墨流」。

  ## 写作风格
  {style_requirements}

  ## 上下文
  ### 相关角色
  {character_context}

  ### 世界设定
  {world_context}

  ### 前文摘要
  {previous_summary}

  ### 待回收伏笔
  {pending_foreshadowing}

human_prompt: |
  请创作第{chapter_number}章：{chapter_title}

  大纲：
  {outline}
variables:
  - genre
  - style_requirements
  - character_context
  - world_context
  - previous_summary
  - pending_foreshadowing
  - chapter_number
  - chapter_title
  - outline
```

**优势**: `ChatPromptTemplate` 的类型安全 + `MessagesPlaceholder` 的动态消息插入，比手写 `str.format()` 健壮。

**影响**:
- ✅ 模板与代码分离，非技术人员可编辑 YAML
- ✅ 变量验证，缺少变量时提前报错
- ✅ 支持多语言 Prompt（中文/英文模板共存）
- ❗ YAML 模板编辑需注意缩进和转义

---

### 🔴 ADR-015: 引入 LangChain 全家桶 — 决策理由与约束 🆕

**状态**: 已接受 · 🔴 风险等级：中高（框架锁定）

**背景**: 这个决策是所有 v2.0 变更的根因。需要明确记录"为什么"和"有什么代价"。

**为什么引入 LangChain？**

| 理由 | 权重 | 说明 |
|------|------|------|
| Provider 统一 | 🔴 决定性 | ChatLiteLLM 单一接口覆盖 100+ Provider，模型切换零代码 |
| 可观测性 | 🔴 决定性 | LangSmith 提供 LLM 调用链的可视化调试，复杂 Agent 管线必备 |
| 管线可组合性 | 🟡 支撑性 | LCEL 声明式管道 + LangGraph StateGraph 使 Agent 逻辑可测试、可扩展 |
| 生态复用 | 🟡 支撑性 | ChatPromptTemplate、Chroma integration 减少重复造轮子 |
| 社区标准 | 🟢 加分项 | LangChain 是 Python AI 开发领域最活跃的框架，问题容易找到方案 |

**LangChain vs 自研的不可逆代价**:

| 代价 | 严重程度 | 缓解措施 |
|------|---------|---------|
| 框架锁定 | 🔴 严重 | Protocol 接口隔离 → Domain 层不依赖 LangChain，最坏情况可替换 infrastructure |
| 版本 churn | 🟡 中等 | `pyproject.toml` 锁定 minor 版本（`>=0.3.0,<0.4.0`），Renovate 自动 PR |
| 上手成本 | 🟡 中等 | Phase 1 只用最稳定的子集（ChatLiteLLM + ChatPromptTemplate + StateGraph 顺序链） |
| 依赖体积 | 🟢 轻微 | 本地部署，体积不是瓶颈 |
| 调试复杂度 | 🟡 中等 | LangSmith 弥补（但不是银弹）；Protocol 层可在测试中 bypass LangChain |

**防护规则**:

```
1. domain/ 下 zero 行 LangChain import — CI 强制检查
2. 每个 Protocol 有至少一个 Mock 实现 — 测试不依赖 LangChain
3. 新增 LangChain 子包需经过评估 — 不是所有 langchain_* 都要引入
4. LangSmith 追踪默认关闭 — 仅开发/调试时通过环境变量开启
```

**备选方案**:
| 方案 | Provider覆盖 | 可观测性 | 可组合性 | 维护成本 |
|------|------------|---------|---------|---------|
| LangChain 全家桶（选定） | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| LiteLLM + 自研（v1.0） | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| LlamaIndex（仅 RAG） | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |

**影响**:
- ✅ ChatLiteLLM 统一 100+ Provider，LangSmith 提供全链路调试能力
- ✅ LCEL + LangGraph 使 Agent 管线可测试、可渐进扩展
- ✅ 生态复用减少代码量（Prompt、Chroma、Document loaders）
- ❗ 框架锁定风险：如果 LangChain 方向发生根本性变化，需要替换 infrastructure 层
- ❗ 版本升级成本：每个 minor 版本升级可能需要 1-2 天适配
- ❗ CI 需增加 "domain 层无 LangChain import" 的强制检查

---

## 四、容量估算

| 指标 | 估值 | 说明 |
|------|------|------|
| 数据库大小 | ~10-50MB / 项目 | SQLite，纯文本为主 |
| 向量库大小 | ~10-50MB / 项目 | chromadb 持久化 |
| Embedding 模型 | ~100MB（一次下载） | BAAI/bge-small-zh-v1.5 |
| Token 消耗 | ~5K-50K / 写作调用 | 取决于上下文长度和生成量 |
| LLM API 延迟 | 5-30s / 调用 | 取决于 Provider 和生成长度 |
| RAG 检索延迟 | ~10-50ms | 本地 CPU 推理 |
| 服务内存 | ~200-400MB | Python + FastAPI + SQLAlchemy + chromadb + Embedding 模型 |
| 启动时间 | < 5s（冷启动，含模型加载） | BGE-small 加载 ~1s |

---

## 五、质量属性分析

| 质量属性 | 目标 | 实现策略 |
|---------|------|---------|
| **可测试性** | 覆盖率 ≥ 70% | Repository/LLM/Pipeline/VectorStore 全部可 Mock |
| **可维护性** | 新人 1 周可上手 | 分层清晰、ADR 记录决策理由、Protocol 隔离框架 |
| **可扩展性** | 新增 Provider ≤ 1 天 | ChatLiteLLM 配置切换，无需改代码 |
| **性能** | API 响应 ≤ 100ms（非 LLM） | 异步全链路、SQLite 索引、chromadb 本地 |
| **安全性** | API Key 不落明文 | AES-256-GCM 加密存储 |
| **可观测性** | 关键路径全链路日志 + LangSmith 调试追踪 | loguru 结构化日志 + LangSmith（可选） |

---

## 六、关键反模式规避

| 反模式 | InkFlow 的解药 |
|--------|---------------|
| 分布式单体 | 不上微服务，保持模块化单体 |
| 金锤子 | 不是所有问题都用 LangChain——Phase 1 只用 ChatLiteLLM + StateGraph + ChatPromptTemplate |
| 框架锁定 | Protocol 隔离 — LangChain 仅在 infrastructure 层，可替换 |
| 过早抽象 | Rule of Three：等到第三个类似实现再抽象 |
| 共享数据库 | Repository 模式隔离数据访问 |
| 大泥球 | 模块按业务（project/chapter/agent）分层，非按技术 |
| 贫血领域模型 | Service 包含业务逻辑，而非仅 CRUD |
| LangChain 渗透领域层 | CI 强制检查：`grep -r "from langchain" src/inkflow/domain/ && exit 1` |

---

## 七、演进路径与 UI 时间线

```
Phase 1 (W1-W9) — 核心引擎（纯后端）
  ├── W1-W2: F1-F2 项目/章节 CRUD                  ✅ 已完成
  ├── W3-W4: F5 LLM Provider（LangChain ChatLiteLLM）  🔜 下一步
  ├── W5-W7: F4 Agent 编排（LangGraph StateGraph）
  ├── W5-W7: F3 AI 写作管道（LCEL 链）
  ├── W5-W7: F6 上下文管理（Token 预算，Phase 1 版本）
  ├── W8-W9: F7 CLI 完整命令
  └── W9: Phase 1 Gate — CLI 可完成完整 AI 写作流程

Phase 2 (W10-W16) — 创作工具 + RAG + 🖥️ Web UI
  ├── F8-F11: 角色/世界/大纲/时间线管理
  ├── 🆕 ADR-013 RAG 层：LangChain Chroma + BGE Embedding
  ├── 🆕 自定义 Agent（YAML 配置驱动的顺序链）
  ├── 🔴 F18: Web UI（React 19 + Vite 6 + shadcn/ui）
  │     ├── W10-W12: 前端项目搭建 + 管理面板（项目/章节 CRUD）
  │     ├── W13-W14: 写作界面 + SSE 流式渲染
  │     └── W15-W16: Agent 配置界面 + RAG 检索演示
  └── W16: Phase 2 Gate — Web UI 功能覆盖 ≥ 90%

Phase 3 (W17-W24) — Agent 集成 + 扩展
  ├── F12-F17: 伏笔/审计/风格/提取/会话/daemon
  ├── 🆕 Agent 管线 DAG 版（用户自定义 DAG）
  ├── F20: MCP Server（≥ 15 工具）
  ├── F21: 导出服务（EPUB/Markdown/TXT/DOCX）
  └── W24: Phase 3 Gate — 三平台打包可用

Phase 4+ (未来) — 云端 + 游戏MVP + Agent 管线市场
  ├── 云端部署（PostgreSQL / JWT / CloudSync）
  ├── 🆕 文字游戏 MVP（设定→短篇，2-3 天探针验证）
  └── Agent 管线模板社区分享
```

### 🖥️ UI 时间线详细说明

| 里程碑 | 时间 | 交付物 | 技术 |
|--------|------|--------|------|
| **Phase 1 占位页** | W8-W9 | `/health` 端点 + 简易状态页 | Jinja2 模板渲染（FastAPI 内置） |
| **Phase 2 前端启动** | W10 | React 项目搭建 + API Client 自动生成 | Vite 6 + openapi-typescript |
| **管理面板** | W11-W12 | 项目/章节/角色/世界 CRUD 界面 | React + Zustand + shadcn/ui |
| **写作界面** | W13-W14 | 章节编辑器 + SSE 流式输出 + Agent 进度 | EventSource + 实时渲染 |
| **Agent 配置 + RAG** | W15-W16 | 管线配置界面 + 检索调试 | LangGraph 状态视图 + RAG 检索测试 |
| **Phase 3 打磨** | W17-W21 | 完善 UI、响应式、桌面端打包 | pywebview + PyInstaller |

**关键决策**：Phase 1 **不做任何 Web UI**。原因：
1. Phase 1 的重点是核心引擎可用（CLI 驱动）
2. 前端在 API 契约稳定后再启动，避免返工
3. 单人开发无法并行后端引擎 + 前端 UI
4. Phase 1 末尾有一个 Jinja2 占位页用于冒烟测试

---

## 八、待处理事项

| # | 事项 | 优先级 | 说明 |
|---|------|--------|------|
| 1 | F3-F6 实现（写作管道 + Agent + LLM + 上下文） | 🔴 | Phase 1 核心，约 25-40 人天 |
| 2 | LangSmith API Key 配置 | 🟡 | 调试复杂 Agent 管线需要 |
| 3 | chromadb + BGE 模型集成测试 | 🟡 | Phase 2 RAG 的前置验证 |
| 4 | PyPI 包名 `inkflow` 可用性检查 | 🟡 | 阻塞 pip install 发布 |
| 5 | Node.js 环境确认 | 🟡 | Phase 2 前端需要 |
| 6 | MCP SDK 调研 | 🟡 | Phase 3 需要 |
| 7 | 文字游戏 MVP 探针 | 🟢 | Phase 4+，先不排期 |

---

*本文档是对 `docs/prd-inkflow-v2.1-2026-07-30.md` 的 v2.0 架构分析输出。v1.0（LiteLLM + 自定义 Pipeline 方案）已归档，v2.0（LangChain 全家桶）为当前有效版本。*
