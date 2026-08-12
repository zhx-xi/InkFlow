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
| [ADR-005v2](ADR-005v2.md) | LLM Provider — LangChain ChatOpenAI（OpenAI 兼容路由） | ✅ 已接受 | 2026-07-31 |
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
| [ADR-019](ADR-019.md) | 版本里程碑管理 — SemVer + 1.0.0 = 本地完全可用（v5：里程碑重排 v2 + skills 后移 v3 + F20 MCP 后移 v4 + F25 daemon 移除 v5） | ✅ 已接受（v5 修订） | 2026-08-01（v5 2026-08-07） |
| [ADR-020](ADR-020.md) | GUI 技术选型 — Electron + 共享 React 渲染层（单机主界面，D2） | ✅ 已接受 | 2026-08-02 |
| [ADR-021](ADR-021.md) | 本地内核进程化 — 独立进程 + localhost REST + SSE 通信（GUI↔内核，D3） | ✅ 已接受 | 2026-08-02 |
| [ADR-022](ADR-022.md) | skills 包形态 — 源码单一真相 + 三通道分发（D4） | ✅ 已接受 | 2026-08-02 |
| [ADR-023](ADR-023.md) | MCP Server 设计 — 官方 SDK + stdio + **薄客户端经 HTTP（v2，2026-08-07 ADR-030 D3=A 修订）**（skills 先行、MCP 后移 1.0.0，D5 修订） | ✅ 已接受 | 2026-08-02（v2: 2026-08-07） |
| [ADR-024](ADR-024.md) | 云架构拓扑 — 同进程双前缀（user/admin）+ owner_id 隔离（D6） | ✅ 已接受 | 2026-08-02 |
| [ADR-025](ADR-025.md) | 依赖锁定策略 — uv + uv.lock（Python）+ pnpm-lock.yaml 约定（前端） | ✅ 已接受 | 2026-08-02 |
| [ADR-026](ADR-026.md) | 真实 AI CI job — label 触发 + workflow_dispatch 兜底（e2e-ai-backend） | ✅ 已接受 | 2026-08-04 |
| [ADR-027](ADR-027.md) | 测试覆盖率门禁 — 三层全覆盖（#104：后端 98.5/95.0 + 前端 vitest thresholds + 口径修正） | ✅ 已接受 | 2026-08-06 |
| [ADR-028](ADR-028.md) | E2E 按页面域拆分 + 门禁口径（6 spec + 6 job；e2e-shell 提前第一批 required；AI 链路只测 UI 状态；1.0.0 全页面覆盖） | ✅ 已接受 | 2026-08-06 |
| [ADR-029](ADR-029.md) | F25 daemon 移除 — 伪需求判定 + 意图已覆盖（外部 agent 经 MCP/skills 调用由 F19 serve + F20 MCP + skills 包承担；#52） | ✅ 已接受 | 2026-08-07 |
| [ADR-030](ADR-030.md) | 本地内核服务化 — 冷启动协议（kernel.json + ensure_kernel）+ 常驻生命周期 + CLI 恒经 HTTP + GUI 托盘常驻 + MCP 薄客户端（D1-D4 拍板 2026-08-07） | ✅ 已接受 | 2026-08-07 |
| [ADR-031](ADR-031.md) | Agent 化双模式开关 — deterministic（默认）+ agentic（显式开启）（原 ADR-A，agent-upgrade-path 落盘） | ✅ 已接受 | 2026-08-12 |
| [ADR-032](ADR-032.md) | 工具调用接口位置 — 扩展 LLMClientProtocol（领域层 ToolSpec，不泄漏 LangChain 类型）（原 ADR-B） | ✅ 已接受 | 2026-08-12 |
| [ADR-033](ADR-033.md) | 预算护栏数值 — max_steps=12 / token 32K / 同工具连续 3（F27 实现实测定稿，原 ADR-C） | ✅ 已接受 | 2026-08-12 |
| [ADR-034](ADR-034.md) | 护栏触发语义 — 产物保留 + terminated_by_guardrail 映射 FAILED + 可回退 deterministic（原 ADR-D） | ✅ 已接受 | 2026-08-12 |
| [ADR-035](ADR-035.md) | Agentic 编排引擎 — deepagents 0.7.5 harness（v0.7.0 实测定稿，原 ADR-E） | ✅ 已接受 | 2026-08-12 |
| [ADR-036](ADR-036.md) | 写工具形态 — 内部自定义工具 save_draft（草稿 + 用户确认 + 三约束，原 ADR-F） | ✅ 已接受 | 2026-08-12 |
| [ADR-037](ADR-037.md) | 记忆提取方式 — 规则化统计（N≥2 阈值）先行，LLM 提取第二阶段；结构化偏好表（原 ADR-G） | ✅ 已接受 | 2026-08-12 |
| [ADR-038](ADR-038.md) | 记忆开关 — memory_learning 项目级默认 false（显式开启，F13 同构）（原 ADR-H） | ✅ 已接受 | 2026-08-12 |

## 当前有效决策速览

- **架构风格**: 模块化单体（ADR-001）+ 六边形分层（ADR-002）
- **数据访问**: Repository 模式（ADR-003），SQLite + AsyncSQLAlchemy
- **数据契约**: Pydantic v2 全栈（ADR-004）
- **LLM**: LangChain ChatOpenAI 兼容路由（ADR-005v2，替代 005）
- **Agent 编排**: LangGraph StateGraph（ADR-006v2，替代 006）
- **RAG**: LangChain Chroma + BGE 本地 Embedding（ADR-013）
- **Prompt**: ChatPromptTemplate + YAML（ADR-014）
- **日志**: loguru 结构化（ADR-016）
- **CI 代码质量**: Reviewdog + Ruff 统一门禁（ADR-017）
- **CI 测试分层**: 三层目录 + 按功能链路并行 job（ADR-018）
- **CI 真实 AI 验证**: label 触发 + workflow_dispatch 兜底，e2e-ai-backend job（ADR-026，0.3.1 实现）
- **CI 覆盖率门禁**: 后端 98.5% 行 / 95% 分支（coverage-backend job + check_coverage.py）+ 前端 vitest thresholds；口径 = XML 权威 + RAG 排除 + Protocol 方法体排除（ADR-027，0.3.1 实现）
- **CI E2E 门禁**: 按页面域拆 6 job；e2e-shell 第一批恒跑 required、页面级第二批信息性；AI 链路只测 UI 状态（真实 AI 走 ADR-026）；1.0.0 全页面按钮可达（ADR-028，0.5.0 起实施）
- **版本里程碑**: SemVer 版本号管理；1.0.0 = 本地完全可用（CLI+GUI+skills+MCP）；2.0.0 = 云端（云 Web + 用户 API + Admin 后台 + GUI 远程模式）（ADR-019 v5，2026-08-07：v2 里程碑重排 + v3 skills 后移 1.0.0 + v4 F20 MCP 后移 1.0.0 + v5 F25 daemon 移除）

*来源：design/architecture-analysis-2026-07-30.md §三（2026-07-31 提取为独立目录）*
