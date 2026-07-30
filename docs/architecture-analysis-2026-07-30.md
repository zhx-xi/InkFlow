# InkFlow — 架构分析与决策记录

**日期**: 2026-07-30
**依据**: `docs/prd-inkflow-v2.1-2026-07-30.md` (v2.1 PRD)
**作者**: 软件架构师

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
│   │   │  DatabaseProtocol │ LlmClientProtocol             │  │   │
│   │   │  AuthProtocol │ StorageProtocol                   │  │   │
│   │   │  MCPTransportProtocol │ ...                       │  │   │
│   │   └───────────────────────────────────────────────────┘  │   │
│   └──────────────────────┬─────────────────────────────────┘   │
│                          │                                      │
│                          ▼                                      │
│   ┌────────────────────────────────────────────────────────┐   │
│   │                 Infrastructure Layer                     │   │
│   │                                                         │   │
│   │   ┌────────────┐  ┌──────────┐  ┌────────────────┐    │   │
│   │   │ SQLAlchemy  │  │ LLM      │  │ LocalFile      │    │   │
│   │   │ Repository  │  │ Provider │  │ Storage        │    │   │
│   │   │ (SQLite)    │  │ (OpenAI/ │  │                │    │   │
│   │   │             │  │ DeepSeek)│  │                │    │   │
│   │   └────────────┘  └──────────┘  └────────────────┘    │   │
│   │                                                         │   │
│   │   ┌────────────┐  ┌──────────┐  ┌────────────────┐    │   │
│   │   │ Cloud Repo │  │ Cloud    │  │ CloudStorage   │    │   │
│   │   │ (PG, F2F)  │  │ Auth     │  │ (Phase 4+)     │   │   │
│   │   └────────────┘  └──────────┘  └────────────────┘    │   │
│   └────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────┘
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

**层级职责**:

| 层 | 目录 | 职责 | 依赖 |
|---|------|------|------|
| Presentation | `api/` `cli/` `mcp/` | HTTP 路由 / CLI 命令 / MCP 工具；DTO 转换 | → Application |
| Application | (可选，当前并入 Domain) | 请求编排、事务边界 | → Domain |
| Domain | `services/` `models/` | 业务逻辑、领域模型、Protocol 定义 | 无框架依赖 |
| Infrastructure | `infrastructure/` | SQLAlchemy Repository、LLM Provider、文件存储 | → Domain Ports |

**影响**:
- ✅ 三界面共享 Service 层，业务逻辑不重复
- ✅ Infrastructure 可替换（SQLite ↔ PG、LocalAuth ↔ JWT）
- ❗ 增加初始代码量（接口定义 + 依赖注入）
- ❗ 单人开发下需克制"过度抽象"倾向（Rule of Three）

---

### ADR-003: Repository 模式封装 SQLAlchemy

**状态**: 已接受

**背景**: SQLAlchemy 2.0 async + SQLite 作为本地持久化方案。PRD 要求测试覆盖率 ≥ 70%，数据库层需可 mock。

**决策**: 使用 Repository 模式封装 SQLAlchemy Session，Repository 实现 `DatabaseProtocol` 接口。

```
Service → DatabaseProtocol (Port) ← SQLAlchemyRepository (Adapter)
```

**关键设计原则**:
1. Repository 接收和返回**领域模型**（Pydantic models），而非 ORM 模型
2. SQLAlchemy ORM 模型作为 Repository 内部实现细节，不泄漏到 Service 层
3. CRUD + 自定义查询方法以 Protocol 定义类型签名

```
# 示例
class DatabaseProtocol(Protocol):
    async def get_project(self, project_id: int) -> Project | None: ...
    async def save_project(self, project: Project) -> Project: ...
    async def list_projects(self) -> list[Project]: ...

class SQLiteRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_project(self, project_id: int) -> Project | None:
        row = await self._session.get(ProjectORM, project_id)
        return Project.model_validate(row) if row else None
```

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
- **数据库 Schema 映射**: SQLAlchemy ORM 从 Pydantic schema 生成
- **配置**: `pydantic-settings` 管理环境配置

```
Pydantic Domain Model
    ├── FastAPI: 自动生成 OpenAPI Schema + 请求校验
    ├── Typer: 自动生成 CLI args + help 文本
    ├── MCP: JSON Schema 输出
    └── SQLAlchemy: ORM 映射（可选项，或独立定义）
```

**影响**:
- ✅ 一份模型定义，三界面自动生成校验/文档/序列化
- ✅ Pydantic v2 性能大幅提升（Rust 内核）
- ❗ SQLAlchemy ORM 与 Pydantic 模型之间存在映射代码
- ❗ 需注意 Pydantic v2 与 FastAPI 版本兼容性（当前均已就绪）

---

### ADR-005: LLM Provider — LiteLLM 统一对接（2026-07-30 更新）

**状态**: 已接受（更新版）

**背景**: PRD 要求 ≥ 3 个 Provider（OpenAI、DeepSeek、Ollama），不同任务路由不同模型。原方案计划手写适配器，评估后改用 **LiteLLM**（`litellm` 包），覆盖 100+ Provider。

**决策**: 薄 Protocol 包装 LiteLLM，Service 层只依赖 Protocol。

```python
# domain/ports/llm_client.py
class LLMClient(Protocol):
    async def chat(self, messages: list[dict], **kwargs) -> ChatResponse: ...
    async def chat_stream(self, messages: list[dict], **kwargs) -> AsyncIterator[StreamEvent]: ...

# infrastructure/llm/litellm_client.py
class LiteLLMClient:
    """封装 litellm，隔离第三方依赖"""
    async def chat(self, messages, **kwargs):
        resp = await litellm.acompletion(
            model=kwargs.get("model", "gpt-4o"),
            messages=messages,
            **kwargs,
        )
        return ChatResponse.from_litellm(resp)
```

**与原始方案对比**:
| 维度 | 手写适配器（原方案） | LiteLLM（新方案） |
|------|-------------------|-------------------|
| 代码量 | ~500 行 | ~50 行（薄封装） |
| Provider 数量 | 3-4 个 | 100+ |
| 流式支持 | 需自行封装 | 原生 async generator |
| Token 计数 | tiktoken 手动调用 | 内置 |

**模型路由**: 通过配置层指定 `task → model` 映射（如 `writing → gpt-4o`, `audit → claude-3-haiku`），LiteLLM 自动处理 Provider 差异。

**影响**:
- ✅ 100+ Provider 零代码添加，单人开发成本最低
- ✅ 测试可注入 MockClient，不依赖实际 API
- ✅ 内置流式、重试、Token 计数，省去 ~500 行适配器代码
- ❗ litellm 是第三方依赖，升级可能有 breaking changes（通过薄 Protocol 隔离）
- ❗ 极端场景（特殊 Provider 行为）可能需要绕过 litellm 直接调用 API

---

### ADR-006: Agent 编排 — 管道链模式（Pipeline Chain）

**状态**: 已接受（首版简化）

**背景**: PRD 要求 Architect→Writer→Auditor→Reviser 链式执行（P0-05, 12-18 人天，高风险）。

**决策**: Phase 1 实现**顺序管道链（Sequential Pipeline Chain）**：

```
Input → [Architect] → Outline → [Writer] → Draft → [Auditor] → Feedback → [Reviser] → Final
         ↑ Agent 角色：Prompt + Model + Temperature 配置
         ↓ 每个阶段：可跳过、可重试（≤ 3 次）
```

**Phase 1 简化策略**（控制风险）:
1. 角色配置为「Prompt 模板 + Model 映射 + Temperature」，不引入复杂 Agent 框架
2. 执行流为「顺序链」，不支持并行/分支（Phase 2 再扩展）
3. 每个阶段的 Prompt 模板从 `prompts/` 目录加载（YAML），不硬编码
4. 输出是结构化数据（JSON），便于下一阶段消费和审计跟踪

```python
class AgentChain:
    """管道链编排引擎"""

    async def execute(
        self,
        context: WritingContext,
        roles: list[AgentRole],  # [Architect, Writer, Auditor, Reviser]
        max_retries: int = 3,
    ) -> ChainResult:
        ...
```

**影响**:
- ✅ 首版 12-18 人天风险可控 → 简化后约 6-10 人天
- ✅ 管线链可测试（Mock 每个 AgentRole 的 LLM 调用）
- ❗ 不支持并行 Agent（Phase 2 加）
- ❗ Prompt 模板质量直接影响输出，需要迭代优化

---

### ADR-007: 项目包结构

**状态**: 已接受

**背景**: 需要清晰的模块边界，支持三界面复用，且为 SDD 工作流兼容。

**决策**: Monorepo 结构：

```
backend/                         # Python 后端
├── src/inkflow/                 # 主 Python 包
│   ├── __init__.py
│   ├── __main__.py              # Entry point: `inkflow` CLI
│
├── api/                            # FastAPI 路由（Presentation）
│   ├── __init__.py
│   ├── app.py                      # FastAPI 应用创建
│   ├── deps.py                     # 依赖注入（FastAPI Depends）
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── chapter.py
│   │   ├── writing.py
│   │   ├── agent.py
│   │   ├── context.py
│   │   └── health.py
│   └── middleware.py               # 统一错误处理/日志
│
├── cli/                            # Typer CLI（Presentation）
│   ├── __init__.py
│   ├── app.py                      # Typer app 创建
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── chapter.py
│   │   ├── write.py
│   │   ├── character.py
│   │   ├── world.py
│   │   ├── outline.py
│   │   ├── audit.py
│   │   ├── export.py
│   │   └── serve.py
│   └── output.py                   # JSON/Table 输出格式
│
├── mcp/                            # MCP Server（Presentation, Phase 3）
│   ├── __init__.py
│   ├── server.py                   # MCP Server 初始化
│   └── tools/                      # ≥ 15 MCP 工具
│
├── domain/                         # Domain 层（业务逻辑 + 接口定义）
│   ├── __init__.py
│   ├── models/                     # Pydantic 领域模型
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── chapter.py
│   │   ├── character.py
│   │   ├── world.py
│   │   ├── outline.py
│   │   ├── timeline.py
│   │   ├── foreshadowing.py
│   │   ├── agent.py
│   │   └── context.py
│   ├── services/                   # 业务服务
│   │   ├── __init__.py
│   │   ├── project_service.py
│   │   ├── chapter_service.py
│   │   ├── writing_service.py
│   │   ├── agent_service.py
│   │   ├── context_service.py
│   │   ├── character_service.py
│   │   ├── world_service.py
│   │   ├── outline_service.py
│   │   ├── timeline_service.py
│   │   ├── foreshadowing_service.py
│   │   ├── audit_service.py
│   │   ├── extraction_service.py
│   │   ├── style_service.py
│   │   ├── search_service.py
│   │   └── output_service.py
│   ├── ports/                      # 出站接口（Protocol 定义）
│   │   ├── __init__.py
│   │   ├── database.py             # DatabaseProtocol
│   │   ├── llm_client.py           # LLMClientProtocol
│   │   ├── auth.py                 # AuthProtocol
│   │   ├── storage.py              # StorageProtocol
│   │   └── user.py                 # UserProtocol
│   └── exceptions.py               # 领域级异常
│
├── infrastructure/                 # 基础设施（Adapter 实现）
│   ├── __init__.py
│   ├── database/                   # SQLAlchemy + SQLite
│   │   ├── __init__.py
│   │   ├── engine.py               # 引擎创建 + session 管理
│   │   ├── models/                 # SQLAlchemy ORM 模型
│   │   │   ├── __init__.py
│   │   │   ├── project.py
│   │   │   ├── chapter.py
│   │   │   └── ...
│   │   └── repositories/           # Repository 实现
│   │       ├── __init__.py
│   │       ├── project_repo.py
│   │       ├── chapter_repo.py
│   │       └── ...
│   ├── llm/                        # LLM Provider 适配器
│   │   ├── __init__.py
│   │   ├── openai_client.py
│   │   ├── deepseek_client.py
│   │   ├── ollama_client.py
│   │   └── base.py                 # 共享工具（HTTP client, retry, tokenize）
│   ├── auth/                       # 本地免认证（Phase 1）/ JWT（Phase 4+）
│   │   ├── __init__.py
│   │   └── local_trust.py
│   └── storage/                    # 本地文件存储
│       ├── __init__.py
│       └── local_file_storage.py
│
├── core/                           # 共享基础设施（Config/Log/DB session）
│   ├── __init__.py
│   ├── config.py                   # Pydantic Settings
│   ├── logger.py                   # loguru 配置
│   ├── database.py                 # 数据库 session 工厂
│   └── dependencies.py             # 共享 DI 容器
│
├── prompts/                        # Agent Prompt 模板（YAML）
│   ├── architect.yaml
│   ├── writer.yaml
│   ├── auditor.yaml
│   └── reviser.yaml
│
└── __about__.py                    # 版本号、作者信息
```

**影响**:
- ✅ 三层（Presentation/Domain/Infrastructure）清晰分离
- ✅ 模块按业务聚合（project/chapter/agent...），而非按技术层次
- ❗ Phase 1 某些模块（character/world/timeline）只有占位接口
- ❗ 文件数量较多（~60+ 文件），需 IDE 辅助导航

---

### ADR-008: 配置管理 — Pydantic Settings 分层配置

**状态**: 已接受

**背景**: PRD 需要多 Provider API Key 加密存储、任务模型路由、用户可配参数。

**决策**: 使用 `pydantic-settings` 实现三层配置：

```python
# 1. 默认配置（硬编码）
class DefaultSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INKFLOW_")

    # 数据库
    database_url: str = "sqlite+aiosqlite:///inkflow.db"

    # LLM Provider
    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # 模型路由
    model_routing: dict[str, str] = {
        "writing": "gpt-4o",
        "audit": "claude-3-haiku",
        "outline": "deepseek-chat",
    }

    # Token 预算
    context_token_budget: int = 128000
    context_protected_ratio: float = 0.3
    context_compressible_ratio: float = 0.5
    context_dynamic_ratio: float = 0.2

# 2. .env 文件（本地覆盖）
# INKFLOW_OPENAI_API_KEY=sk-xxx

# 3. 项目级配置（存储在 SQLite 中的 JSON 字段，每项目独立）
# Project.config 覆盖全局默认值
```

**影响**:
- ✅ 类型安全，IDE 自动补全
- ✅ 环境变量支持，适合 Docker/云端部署
- ✅ 项目级配置独立，支持每个项目不同模型路由
- ❗ API Key 加密存储（cryptography）需要额外处理

---

### ADR-009: 依赖注入策略

**状态**: 已接受

**背景**: Service 层依赖 Repository、LLM Client 等基础设施，需要可测试性。

**决策**: 三套 DI 方案对应三个界面：

| 界面 | DI 方案 | 说明 |
|------|---------|------|
| FastAPI API | `FastAPI Depends` | 原生支持，Request-scoped |
| Typer CLI | 构造函数注入 + lazy factory | Typer 无 DI 容器，手动注入 |
| MCP Server | 构造函数注入 | Server 启动时一次性注入 |

**统一原则**: Service 类通过构造函数接受依赖，不直接引用全局变量。

```python
class ProjectService:
    """构造注入，不依赖全局状态"""

    def __init__(
        self,
        db: DatabaseProtocol,
        llm: LLMClientProtocol | None = None,  # 可选依赖
    ):
        self._db = db
        self._llm = llm

# FastAPI: Depends 工厂
async def get_project_service(
    db: DatabaseProtocol = Depends(get_db),
) -> ProjectService:
    return ProjectService(db=db)

# CLI: 手动传参
def main():
    db = create_sqlite_repository()
    service = ProjectService(db=db)
    ...
```

**影响**:
- ✅ 测试时直接构造 `ProjectService(mock_db)`，无需框架
- ✅ FastAPI Depends 做自动生命周期管理
- ❗ CLI/MCP 需要手动管理依赖图（Service 数量增多时需 DI 容器，如 `lazy` 或简单的 `ServiceFactory`）

---

### ADR-010: 上下文管理 — 分层 Token 预算

**状态**: 已接受

**背景**: PRD F6 要求 Token 预算管理、分层上下文（protected/compressible/dynamic）、角色注入、世界设定注入、前文摘要、伏笔追踪。

**决策**: 实现三层 Token 预算分配模型：

```
上下文 Budget（100%）
│
├── Protected（30%）— 必须保留的内容
│   ├── Project 设定（Genre/Language/Target Words）
│   ├── 当前章节的 Agent 角色 Prompt
│   └── 关键角色档案（按章节匹配 Top-K）
│
├── Compressible（50%）— 可摘要压缩的内容
│   ├── 前 N 章摘要（自动生成，N 可配）
│   ├── 世界设定（按 location 匹配）
│   ├── 相关伏笔（未解决的）
│   └── 时间线事件（最近 Top-M）
│
└── Dynamic（20%）— 按需注入，超预算截断
    ├── 完整的上文（对话/情节）
    ├── 额外角色档案
    └── 额外世界设定
```

```python
@dataclass
class ContextBudget:
    total: int
    protected_limit: int      # total * protected_ratio
    compressible_limit: int   # total * compressible_ratio
    dynamic_limit: int        # total * dynamic_ratio

class ContextService:
    async def build_context(
        self,
        project_id: int,
        chapter_id: int,
        budget: ContextBudget,
    ) -> WritingContext:
        # 1. 计算 Token 预算
        # 2. 收集 Protected 内容（精确匹配）
        # 3. 生成 Compressible 摘要
        # 4. 注入 Dynamic 内容（截断到预算）
        # 5. 返回组装好的上下文
        ...
```

**影响**:
- ✅ 适配不同模型的上下文窗口（8K/32K/128K/200K）
- ✅ 摘要策略使长篇小说管理成为可能
- ❗ Token 计数精度在不同模型间不一致
- ❗ 摘要质量直接影响 Agent 写作质量

---

### ADR-011: 异步无阻塞架构

**状态**: 已接受

**背景**: PRD 要求流式输出（SSE）、LLM API 调用、后台 daemon 写作。

**决策**: 全异步栈，所有 I/O 使用 `async/await`：

```python
# 全链路异步
FastAPI (async) → Service (async) → Repository (async) → SQLAlchemy (async)
                                   → LLM Client (async) → httpx (async)
                                   → File Storage (async) → aiofiles
```

**同步例外**：
- CLI 启动入口（`asyncio.run()` 包装）
- Typer 命令本身同步，内部调用 `asyncio.run()` 或 `async` 命令
- MCP Server 在事件循环中运行

**影响**:
- ✅ 流式输出：单连接支持 SSE，资源占用低
- ✅ 并发 LLM 调用：多个 Provider 请求可并行
- ❗ SQLite 虽然是单线程，但 aiosqlite 异步化避免阻塞事件循环
- ❗ 调试异步代码比同步复杂（调用栈更复杂）

---

### ADR-012: 错误处理策略

**状态**: 已接受

**背景**: 三个界面需要统一的错误处理，避免重复代码。

**决策**: 领域级异常（Domain Exceptions）→ 统一错误处理中间件 → 界面适配

```python
# domain/exceptions.py
class InkFlowError(Exception):
    """所有领域异常的基类"""
    code: str
    detail: str
    status_code: int = 500

class ProjectNotFoundError(InkFlowError):
    code = "PROJECT_NOT_FOUND"
    status_code = 404

class LLMRequestError(InkFlowError):
    code = "LLM_REQUEST_FAILED"
    status_code = 502

class ContextBudgetExceededError(InkFlowError):
    code = "CONTEXT_BUDGET_EXCEEDED"
    status_code = 400

# API: FastAPI ExceptionHandler
@app.exception_handler(InkFlowError)
async def inkflow_error_handler(request, exc: InkFlowError):
    return JSONResponse(status_code=exc.status_code, content={
        "error": {"code": exc.code, "detail": exc.detail}
    })

# CLI: 捕获并输出
try:
    result = service.method()
except InkFlowError as e:
    console.print(f"[red]Error ({e.code}):[/] {e.detail}")
    raise typer.Exit(code=1)

# MCP: 返回错误 JSON-RPC
```

**影响**:
- ✅ 三界面复用同一套异常类
- ✅ 错误信息统一，前端/CLI/Agent 解析一致
- ❗ 需覆盖所有可能的错误场景（Phase 1 聚焦核心场景）

---

## 四、容量估算

基于 PRD 单人开发 + 本地部署场景：

| 指标 | 估值 | 说明 |
|------|------|------|
| 数据库大小 | ~10-50MB / 项目 | SQLite，纯文本为主 |
| Token 消耗 | ~5K-50K / 写作调用 | 取决于上下文长度和生成量 |
| LLM API 延迟 | 5-30s / 调用 | 首版不支持并行 Agent |
| 服务内存 | ~50-150MB | Python + FastAPI + SQLAlchemy |
| 启动时间 | < 2s（冷启动） | FastAPI + uvloop |

---

## 五、质量属性分析

| 质量属性 | 目标 | 实现策略 |
|---------|------|---------|
| **可测试性** | 覆盖率 ≥ 70% | Repository Mock、LLM Mock、DI 注入 |
| **可维护性** | 新人 1 周可上手 | 分层清晰、ADR 记录决策理由 |
| **可扩展性** | 新增 Provider ≤ 1 天 | Protocol 接口 + Config 配置 |
| **性能** | API 响应 ≤ 100ms（非 LLM） | 异步全链路、SQLite 索引 |
| **安全性** | API Key 不落明文 | AES-256-GCM 加密存储 |
| **可观测性** | 关键路径全链路日志 | loguru 结构化日志 + Request ID |

---

## 六、关键反模式规避

| 反模式 | InkFlow 的解药 |
|--------|---------------|
| 分布式单体 | 不上微服务，保持模块化单体 |
| 金锤子 | PyPI 包名冲突 → 备选方案；对话类 UI 不强行用 React |
| 简历驱动开发 | ADR 记录每个选型的业务理由 |
| 过早抽象 | Rule of Three：等到第三个类似实现再抽象 |
| 共享数据库 | Repository 模式隔离数据访问 |
| 大泥球 | 模块按业务（project/chapter/agent）分层，非按技术 |
| 贫血领域模型 | Service 包含业务逻辑，而非仅 CRUD |

---

## 七、演进路径

```
Phase 1 (W1-W9): 模块化单体骨架
  ├── FastAPI + SQLite + LLM × 3 + Agent 链 + CLI
  └── 为 Phase 2 提供 REST API 契约

Phase 2 (W10-W16): 创作工具 + Web UI + 打包
  ├── React 前端消费同一 REST API
  ├── 新增 character/world/outline/timeline 模块
  └── pywebview + PyInstaller 桌面端

Phase 3 (W17-W24): Agent 集成 + 补全
  ├── MCP Server 包装 Service 层
  ├── SSE 流式输出
  └── daemon 后台写作

Phase 4+ (未来): 云端迁移
  ├── 实现 AuthProtocol → JWTAuth
  ├── 实现 DatabaseProtocol → PostgreSQL
  └── 单体拆分（如果需要多团队）
```

---

## 八、待处理架构 TODO

| # | 事项 | 优先级 | 说明 |
|---|------|--------|------|
| 1 | PyPI 包名 `inkflow` 可用性检查 | 🔴 | 阻塞 pip install 发布 |
| 2 | SDD 初始化 `specify init .` | 🔴 | 生成 .specify/ 和模板 |
| 3 | 编写 Constitution（项目章程） | 🔴 | SDD 工作流起点 |
| 4 | 编写 Phase 1 Spec（F1-F7） | 🔴 | 架构决策的落地基础 |
| 5 | Node.js 版本确认 | 🟡 | Phase 2 前端需要 |
| 6 | MCP SDK 调研 | 🟡 | Phase 3 需要 |
| 7 | Model routing 默认配比确定 | 🟡 | 影响 Phase 1 F5 实现 |

---

*本文档是对 `docs/prd-inkflow-v2.1-2026-07-30.md` 的架构分析输出。每个 ADR 都可以作为 SDD 工作流中 Plan/Implement 阶段的输入。*
