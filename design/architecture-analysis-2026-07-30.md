# InkFlow — 架构分析与决策记录（v2.0）

**日期**: 2026-07-31（v2.0 更新：引入 LangChain 全家桶）
**前版**: v1.0（2026-07-30，LiteLLM + 自定义 Pipeline）
**依据**: `design/prd-inkflow-v2.1-2026-07-30.md` + 产品愿景扩展
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

> **2026-07-31 更新**: 全部 ADR 已提取为独立文件，见 [`adr/`](../adr/README.md)（含索引）。
> 本目录不再维护内嵌副本，避免双份漂移。新增决策请直接在 `adr/` 创建 ADR-NNN.md 并在索引登记。

| 编号 | 标题 | 状态 |
|------|------|------|
| [ADR-001](../adr/architecture/ADR-001.md) | 模块化单体 + 严格接口隔离 | ✅ 已接受 |
| [ADR-002](../adr/architecture/ADR-002.md) | Clean/Hexagonal 风格分层 | ✅ 已接受 |
| [ADR-003](../adr/database/ADR-003.md) | Repository 模式封装 SQLAlchemy | ✅ 已接受 |
| [ADR-004](../adr/database/ADR-004.md) | Pydantic v2 作为统一数据契约 | ✅ 已接受 |
| [ADR-005(→v2)](../adr/llm/ADR-005v2.md) | LLM Provider — LiteLLM 统一对接 | ⛔ 已弃用（被 ADR-005v2 取代） |
| [ADR-005v2](../adr/llm/ADR-005v2.md) | LLM Provider — LangChain ChatLiteLLM | ✅ 已接受 |
| [ADR-006(→v2)](../adr/agent/ADR-006v2.md) | Agent 编排 — 管道链模式 | ⛔ 已弃用（被 ADR-006v2 取代） |
| [ADR-006v2](../adr/agent/ADR-006v2.md) | Agent 编排 — LangGraph StateGraph | ✅ 已接受 |
| [ADR-007v2](../adr/architecture/ADR-007v2.md) | 项目包结构（infrastructure 按技术分目录） | ✅ 已接受 |
| [ADR-008](../adr/service/ADR-008.md) | 配置管理 — Pydantic Settings 分层配置 | ✅ 已接受 |
| [ADR-009](../adr/service/ADR-009.md) | 依赖注入策略 | ✅ 已接受 |
| [ADR-010](../adr/llm/ADR-010.md) | 上下文管理 — Token 预算 → RAG 增强 | ✅ 已接受 |
| [ADR-011](../adr/architecture/ADR-011.md) | 异步无阻塞架构 | ✅ 已接受 |
| [ADR-012](../adr/architecture/ADR-012.md) | 错误处理策略 | ✅ 已接受 |
| [ADR-013](../adr/llm/ADR-013.md) | RAG 检索 — LangChain Chroma + 本地 Embedding | ✅ 已接受（Phase 2 实现） |
| [ADR-014](../adr/llm/ADR-014.md) | Prompt 模板管理 — LangChain ChatPromptTemplate | ✅ 已接受 |
| [ADR-015](../adr/llm/ADR-015.md) | 引入 LangChain 全家桶 — 决策理由与约束 | ✅ 已接受 |
| [ADR-016](../adr/service/ADR-016.md) | 日志方案 — loguru 结构化日志 | ✅ 已接受 |

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

*本文档是对 `design/prd-inkflow-v2.1-2026-07-30.md` 的 v2.0 架构分析输出。v1.0（LiteLLM + 自定义 Pipeline 方案）已归档，v2.0（LangChain 全家桶）为当前有效版本。*
