# InkFlow ADR 索引

> 架构决策记录（Architecture Decision Records）目录。
> 依据：Nygard ADR 格式（状态 / 背景 / 决策 / 备选方案 / 影响）
> 治理要求：Constitution §7.3 — 所有 ADR 保持最新；每个 PR 引用的 ADR 必须与代码一致。

## 目录结构（按域归类）

ADR 自 2026-09-01 起按**领域**归入子目录（保留 ADR 编号稳定，避免破坏全仓 1820+ 处文本引用）：

| 域 | 目录 | 说明 |
|----|------|------|
| 架构设计 | `architecture/` | 模块化单体 / 分层 / 包结构 / 异步 / 错误 / 云拓扑 / 依赖 |
| 数据库 | `database/` | Repository 模式 / Pydantic 数据契约 |
| service 层 | `service/` | 配置管理 / 依赖注入 / 日志 |
| LLM | `llm/` | Provider 路由 / 上下文管理 / RAG / Prompt / 可观测 |
| Agent | `agent/` | LangGraph 编排 / 双模式 / 工具接口 / 护栏 / 引擎 / 写工具 |
| 记忆与 Skills | `memory-skills/` | 记忆提取 / 开关 / Skills 真源 / 脱敏 / chat 重放 |
| 内核/运行时 | `kernel/` | 内核进程化 / 服务化 |
| API | `api/` | API 层架构基线 |
| CLI | `cli/` | CLI 层架构基线 |
| MCP | `mcp/` | MCP Server 设计 |
| GUI | `gui/` | Electron + React 渲染层 |
| 测试与 CI | `test-ci/` | CI 质量 / 测试分层 / 真实 AI / 覆盖率 / E2E |
| 打包与发布 | `packaging/` | 版本里程碑 / 打包 Debug 模式 |

## 编号规则

- 顺序递增，不复用编号
- 决策被取代时：旧 ADR 标记 `已弃用` 并指向新 ADR；新 ADR 标记 `已接受` 并注明替代关系（如 ADR-005 → ADR-005v2、ADR-006 → ADR-006v2）
- 新决策优先引用相关旧 ADR 作为上下文

## 决策记录（按域）

### 架构设计（architecture）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-001](architecture/ADR-001.md) | 模块化单体 + 严格接口隔离 | ✅ 已接受 | 2026-07-30 |
| [ADR-002](architecture/ADR-002.md) | Clean/Hexagonal 风格分层 | ✅ 已接受 | 2026-07-30 |
| [ADR-007v2](architecture/ADR-007v2.md) | 项目包结构（infrastructure 按技术分目录） | ✅ 已接受 | 2026-07-31 |
| [ADR-011](architecture/ADR-011.md) | 异步无阻塞架构 | ✅ 已接受 | 2026-07-30 |
| [ADR-012](architecture/ADR-012.md) | 错误处理策略 | ✅ 已接受 | 2026-07-30 |
| [ADR-024](architecture/ADR-024.md) | 云架构拓扑 — 双前缀单体 + owner_id 隔离 | ✅ 已接受 | 2026-08-02 |
| [ADR-025](architecture/ADR-025.md) | 依赖锁定策略 — uv + uv.lock + pnpm-lock.yaml | ✅ 已接受 | 2026-08-02 |
| [ADR-029](architecture/ADR-029.md) | F25 daemon 移除 — 伪需求判定 + 意图已覆盖 | ✅ 已接受 | 2026-08-07 |

### 数据库（database）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-003](database/ADR-003.md) | Repository 模式封装 SQLAlchemy | ✅ 已接受 | 2026-07-30 |
| [ADR-004](database/ADR-004.md) | Pydantic v2 作为统一数据契约 | ✅ 已接受 | 2026-07-30 |

### service 层（service）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-008](service/ADR-008.md) | 配置管理 — Pydantic Settings 分层配置 | ✅ 已接受 | 2026-07-30 |
| [ADR-009](service/ADR-009.md) | 依赖注入策略 | ✅ 已接受 | 2026-07-30 |
| [ADR-016](service/ADR-016.md) | 日志方案 — loguru 结构化日志 | ✅ 已接受 | 2026-07-30 |

### LLM（llm）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-005v2](llm/ADR-005v2.md) | LLM Provider — LangChain ChatOpenAI（OpenAI 兼容路由） | ✅ 已接受 | 2026-07-31 |
| [ADR-010](llm/ADR-010.md) | 上下文管理 — Token 预算 → RAG 增强 | ✅ 已接受 | 2026-07-30 |
| [ADR-013](llm/ADR-013.md) | RAG 检索 — LangChain Chroma + 本地 Embedding | ✅ 已接受 | 2026-07-31 |
| [ADR-014](llm/ADR-014.md) | Prompt 模板管理 — LangChain ChatPromptTemplate | ✅ 已接受 | 2026-07-31 |
| [ADR-015](llm/ADR-015.md) | 引入 LangChain 全家桶 — 决策理由与约束 | ✅ 已接受 | 2026-07-31 |
| [ADR-042](llm/ADR-042.md) | LangSmith 可观测性追踪接入 | ✅ 已接受 | 2026-08-24 |
| [ADR-049](llm/ADR-049.md) | LLM 模型装配 fail-fast 化 — 删除静默回退 + provider 键内置路由 + 诊断日志 | ✅ 已接受 | 2026-09-05 |

### Agent（agent）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-006v2](agent/ADR-006v2.md) | Agent 编排 — LangGraph StateGraph | ✅ 已接受 | 2026-07-31 |
| [ADR-031](agent/ADR-031.md) | Agent 化双模式开关 — deterministic + agentic | ✅ 已接受 | 2026-08-12 |
| [ADR-032](agent/ADR-032.md) | 工具调用接口位置 — 扩展 LLMClientProtocol | ✅ 已接受 | 2026-08-12 |
| [ADR-033](agent/ADR-033.md) | 预算护栏数值 — max_steps=12 / token 32K | ✅ 已接受 | 2026-08-12 |
| [ADR-034](agent/ADR-034.md) | 护栏触发语义 — 产物保留 + 可回退 deterministic | ✅ 已接受 | 2026-08-12 |
| [ADR-035](agent/ADR-035.md) | Agentic 编排引擎 — deepagents 0.7.5 harness | ✅ 已接受 | 2026-08-12 |
| [ADR-036](agent/ADR-036.md) | 写工具形态 — save_draft（草稿 + 确认 + 三约束） | ✅ 已接受 | 2026-08-12 |
| [ADR-043](agent/ADR-043.md) | AI 工具面全量注册 + 删除交互授权模型 | ✅ 已接受 | 2026-08-28 |

### 记忆与 Skills（memory-skills）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-022](memory-skills/ADR-022.md) | skills 包形态 — 源码单一真相 + 三通道分发 | ✅ 已接受 | 2026-08-02 |
| [ADR-037](memory-skills/ADR-037.md) | 记忆提取方式 — 规则化统计先行 | ✅ 已接受 | 2026-08-12 |
| [ADR-038](memory-skills/ADR-038.md) | 记忆开关 — memory_learning 项目级默认 false | ✅ 已接受 | 2026-08-12 |
| [ADR-039](memory-skills/ADR-039.md) | Skills 文件系统真源（DB 退役） | ✅ 已接受 | 2026-08-20 |
| [ADR-040](memory-skills/ADR-040.md) | 对话输入机密脱敏（A+B 双兜底） | ✅ 已接受 | 2026-08-23 |
| [ADR-041](memory-skills/ADR-041.md) | chat 会话可重放 — 复用 agent_runs | ✅ 已接受 | 2026-08-24 |

### 内核/运行时（kernel）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-021](kernel/ADR-021.md) | 本地内核进程化 — 独立进程 + REST + SSE | ✅ 已接受 | 2026-08-02 |
| [ADR-030](kernel/ADR-030.md) | 本地内核服务化 — 冷启动协议 + 生命周期 | ✅ 已接受 | 2026-08-07 |

### API（api）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-045](api/ADR-045.md) | API 层架构基线 — FastAPI 装配 + REST/SSE + 鉴权 + 错误契约 | ✅ 已接受 | 2026-09-01 |

### CLI（cli）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-046](cli/ADR-046.md) | CLI 层架构基线 — Typer 结构 + 恒经 HTTP + F7 契约 + 产物 | ✅ 已接受 | 2026-09-01 |

### MCP（mcp）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-023](mcp/ADR-023.md) | MCP Server 设计 — 官方 SDK + stdio + 薄客户端经 HTTP | ✅ 已接受 | 2026-08-02 |

### GUI（gui）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-020](gui/ADR-020.md) | GUI 技术选型 — Electron + 共享 React 渲染层 | ✅ 已接受 | 2026-08-02 |

### 测试与 CI（test-ci）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-017](test-ci/ADR-017.md) | CI 代码质量检查 — Reviewdog + Ruff 统一门禁 | ✅ 已接受 | 2026-07-31 |
| [ADR-018](test-ci/ADR-018.md) | 测试分层与 CI Job 并行化 | ✅ 已接受 | 2026-07-31 |
| [ADR-026](test-ci/ADR-026.md) | 真实 AI CI job — label 触发 + workflow_dispatch | ✅ 已接受 | 2026-08-04 |
| [ADR-027](test-ci/ADR-027.md) | 测试覆盖率门禁 — 三层全覆盖（2026-09-01 修订：+后端函数覆盖标准定义；2026-09-02 修订：+契约一致性 C1） | ✅ 已接受 | 2026-08-06 |
| [ADR-028](test-ci/ADR-028.md) | E2E 按页面域拆分 + 门禁口径 | ✅ 已接受 | 2026-08-06 |
| [ADR-047](test-ci/ADR-047.md) | 确定性 fake LLM 测试服务器（fake OpenAI） | ✅ 已接受 | 2026-09-01 |
| [ADR-048](test-ci/ADR-048.md) | 黑盒 E2E 断言契约 — GUI / CLI / MCP 三面 + MCP 错误自愈 | ✅ 已接受 | 2026-09-02 |

### 打包与发布（packaging）

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-019](packaging/ADR-019.md) | 版本里程碑管理 — SemVer + 1.0.0 = 本地可用 | ✅ 已接受（v11 修订） | 2026-08-01 |
| [ADR-044](packaging/ADR-044.md) | 打包产物 Debug 模式 — 统一开关 + 日志落点 + GUI DevTools | ✅ 已接受 | 2026-08-27 |

## 已折叠（被取代，决策并入 v2）

| 编号 | 标题 | 状态 |
|------|------|------|
| ADR-005 | LLM Provider — LiteLLM 统一对接 | ⛔ 已弃用（并入 [ADR-005v2](llm/ADR-005v2.md)） |
| ADR-006 | Agent 编排 — 管道链模式 | ⛔ 已弃用（并入 [ADR-006v2](agent/ADR-006v2.md)） |

> 上述两个旧 ADR 的独立文档已在域归类重构中删除，历史全文存档于 git 历史，其被取代缘由见对应 v2 文档头部「弃用溯源」。

## 当前有效决策速览

- **架构风格**: 模块化单体（ADR-001 [architecture/](architecture/ADR-001.md)）+ 六边形分层（ADR-002）+ 异步无阻塞（ADR-011）
- **数据访问**: Repository 模式（ADR-003 [database/](database/ADR-003.md)），SQLite + AsyncSQLAlchemy
- **数据契约**: Pydantic v2 全栈（ADR-004 [database/](database/ADR-004.md)）
- **LLM**: LangChain ChatOpenAI 兼容路由（ADR-005v2 [llm/](llm/ADR-005v2.md)，替代 005）；模型装配 fail-fast——删除注册表静默回退，`project>global` 无解即 422+诊断日志，model_routing=provider 键内置默认（ADR-049 [llm/](llm/ADR-049.md)）
- **Agent 编排**: LangGraph StateGraph → deepagents 0.7.5 harness（ADR-006v2 / ADR-035 [agent/](agent/ADR-035.md)）
- **RAG**: LangChain Chroma + BGE 本地 Embedding（ADR-013 [llm/](llm/ADR-013.md)）
- **Prompt**: ChatPromptTemplate + YAML（ADR-014 [llm/](llm/ADR-014.md)）
- **日志**: loguru 结构化（ADR-016 [service/](service/ADR-016.md)）
- **内核**: 独立进程 + REST + SSE（ADR-021），冷启动协议 + 常驻 + 多客户端（ADR-030 [kernel/](kernel/ADR-030.md)）
- **API**: FastAPI 装配 + REST/SSE + 本地 token 鉴权 + 错误契约（ADR-045 [api/](api/ADR-045.md)）
- **CLI**: Typer + 恒经 HTTP + F7 契约 + 独立产物（ADR-046 [cli/](cli/ADR-046.md)）
- **MCP**: 官方 SDK + stdio + 薄客户端经 HTTP（ADR-023 [mcp/](mcp/ADR-023.md)）
- **GUI**: Electron 壳 + 共享 React 渲染层（ADR-020 [gui/](gui/ADR-020.md)）
- **CI 质量**: Reviewdog + Ruff 统一门禁（ADR-017 [test-ci/](test-ci/ADR-017.md)）
- **CI 测试分层**: 三层目录 + 按功能链路并行 job（ADR-018 [test-ci/](test-ci/ADR-018.md)）
- **CI 真实 AI**: label 触发 + workflow_dispatch 兜底（ADR-026 [test-ci/](test-ci/ADR-026.md)）
- **CI 覆盖率门禁**: 后端 98.5% 行 / 95% 分支 + 前端 vitest thresholds（ADR-027 [test-ci/](test-ci/ADR-027.md)；2026-09-01 修订 +后端函数覆盖标准定义门禁）
- **CI E2E**: 按页面域拆 6 job；AI 链路只测 UI 状态（ADR-028 [test-ci/](test-ci/ADR-028.md)）
- **CI 确定性 fake LLM**: OpenAI 兼容 fake server + INKFLOW_LLM_BASE_URL + e2e_llm_mode 开关（ADR-047 [test-ci/](test-ci/ADR-047.md)）
- **CI 黑盒三面契约**: GUI/CLI/MCP 黑盒断言（元素±/渲染/层级·信封/错误码/退出码·工具调用/错误自愈）+ E2E 不计覆盖（ADR-048 [test-ci/](test-ci/ADR-048.md)）
- **版本里程碑**: SemVer；1.0.0 = 本地完全可用；2.0.0 = 云端（ADR-019 [packaging/](packaging/ADR-019.md) v11；ADR-024 [architecture/](architecture/ADR-024.md)）

*来源：design/architecture-analysis-2026-07-30.md §三（2026-07-31 提取为独立目录）；2026-09-01 域归类重构（ADR 编号保持稳定，仅目录分组 + 折叠 005/006 + 补号 045/046）。*
