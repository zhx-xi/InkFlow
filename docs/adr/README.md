# InkFlow ADR 索引

> 架构决策记录（Architecture Decision Records）目录。
> 依据：Nygard ADR 格式（状态 / 背景 / 决策 / 备选方案 / 影响）
> 治理要求：Constitution §7.3 — 所有 ADR 保持最新；每个 PR 引用的 ADR 必须与代码一致。

## 编号规则

- 顺序递增，不复用编号
- 决策被取代时：旧 ADR 标记 `已弃用` 并指向新 ADR；新 ADR 标记 `已接受` 并注明替代关系（如 ADR-005 → ADR-005v2）
- 新决策优先引用相关旧 ADR 作为上下文

## 决策记录

| 编号 | 标题 | 状态 | 日期 |
|------|------|------|------|
| [ADR-001](ADR-001.md) | 模块化单体 + 严格接口隔离 | ✅ 已接受 | 2026-07-30 |
| [ADR-002](ADR-002.md) | Clean/Hexagonal 风格分层 | ✅ 已接受 | 2026-07-30 |
| [ADR-003](ADR-003.md) | Repository 模式封装 SQLAlchemy | ✅ 已接受 | 2026-07-30 |
| [ADR-004](ADR-004.md) | Pydantic v2 作为统一数据契约 | ✅ 已接受 | 2026-07-30 |
| [ADR-005](ADR-005.md) | LLM Provider — LiteLLM 统一对接 | ⛔ 已弃用（被 ADR-005v2 取代） | 2026-07-30 |
| [ADR-005v2](ADR-005v2.md) | LLM Provider — LangChain ChatLiteLLM | ✅ 已接受 | 2026-07-31 |
| [ADR-006](ADR-006.md) | Agent 编排 — 管道链模式 | ⛔ 已弃用（被 ADR-006v2 取代） | 2026-07-30 |
| [ADR-006v2](ADR-006v2.md) | Agent 编排 — LangGraph StateGraph | ✅ 已接受 | 2026-07-31 |
| [ADR-007v2](ADR-007v2.md) | 项目包结构（infrastructure 按技术分目录） | ✅ 已接受 | 2026-07-31 |
| [ADR-008](ADR-008.md) | 配置管理 — Pydantic Settings 分层配置 | ✅ 已接受 | 2026-07-30 |
| [ADR-009](ADR-009.md) | 依赖注入策略 | ✅ 已接受 | 2026-07-30 |
| [ADR-010](ADR-010.md) | 上下文管理 — Token 预算 → RAG 增强 | ✅ 已接受 | 2026-07-30 |
| [ADR-011](ADR-011.md) | 异步无阻塞架构 | ✅ 已接受 | 2026-07-30 |
| [ADR-012](ADR-012.md) | 错误处理策略 | ✅ 已接受 | 2026-07-30 |
| [ADR-013](ADR-013.md) | RAG 检索 — LangChain Chroma + 本地 Embedding | ✅ 已接受（Phase 2 实现） | 2026-07-31 |
| [ADR-014](ADR-014.md) | Prompt 模板管理 — LangChain ChatPromptTemplate | ✅ 已接受 | 2026-07-31 |
| [ADR-015](ADR-015.md) | 引入 LangChain 全家桶 — 决策理由与约束 | ✅ 已接受 | 2026-07-31 |
| [ADR-016](ADR-016.md) | 日志方案 — loguru 结构化日志 | ✅ 已接受 | 2026-07-31 |
| [ADR-017](ADR-017.md) | CI 代码质量检查 — Reviewdog + Ruff 统一门禁 | ✅ 已接受 | 2026-07-31 |
| [ADR-018](ADR-018.md) | 测试分层与 CI Job 并行化 — 三层目录 + 按功能链路拆分 job | ✅ 已接受 | 2026-07-31 |

## 当前有效决策速览

- **架构风格**: 模块化单体（ADR-001）+ 六边形分层（ADR-002）
- **数据访问**: Repository 模式（ADR-003），SQLite + AsyncSQLAlchemy
- **数据契约**: Pydantic v2 全栈（ADR-004）
- **LLM**: LangChain ChatLiteLLM（ADR-005v2，替代 005）
- **Agent 编排**: LangGraph StateGraph（ADR-006v2，替代 006）
- **RAG**: LangChain Chroma + BGE 本地 Embedding（ADR-013）
- **Prompt**: ChatPromptTemplate + YAML（ADR-014）
- **日志**: loguru 结构化（ADR-016）
- **CI 代码质量**: Reviewdog + Ruff 统一门禁（ADR-017）
- **CI 测试分层**: 三层目录 + 按功能链路并行 job（ADR-018）

*来源：docs/architecture-analysis-2026-07-30.md §三（2026-07-31 提取为独立目录）*
