# specs/ — 功能规格索引

> SDD（Spec-Driven Development）真相来源：每 feature 一个目录 `specs/f<编号>-<短名>/spec.md`。
> 版本归属以 [ADR-019 v7](../adr/packaging/ADR-019.md) 为准；完整功能清单见 [FEATURES.md](../FEATURES.md)。
> 篇幅纪律（2026-08-08 #201 立规）：新 spec 默认单文件 ≤800 行；超过且章节内聚可拆时允许 `references/` 子目录（spec.md 头部必须声明清单）；已实现 spec 只加「快速导航」块不物理拆分。

## 分类索引

### 核心引擎（0.1.0，Phase 1）

| Feature | 规格 | 主侧 | 功能域 | 状态 |
|---------|------|------|------|------|
| F1 项目服务 | [`f1-project/spec.md`](f1-project/spec.md) | 后端 | api | ✅ 已实现（PR #8） |
| F2 章节服务 | [`f2-chapter/spec.md`](f2-chapter/spec.md) | 后端 | api | ✅ 已实现（PR #9） |
| F3 写作管道 | [`f3-writing/spec.md`](f3-writing/spec.md) | 后端 | writing | ✅ 已实现（PR #21） |
| F4 Agent 编排 | [`f4-pipeline-engine/spec.md`](f4-pipeline-engine/spec.md) | 后端 | agent | ✅ 已实现（PR #22） |
| F5 LLM Provider | [`f5-llm-provider/spec.md`](f5-llm-provider/spec.md) | 后端 | llm | ✅ 已实现（PR #16） |
| F6 上下文服务 | [`f6-context/spec.md`](f6-context/spec.md) | 后端 | context | ✅ 已实现（PR #27） |
| F7 CLI 接口 | [`f7-cli/spec.md`](f7-cli/spec.md) | 后端 | cli | ✅ 已实现（PR #28） |
| F8 CI 测试分层 | 无独立 spec（ADR-018） | 跨端 | test-ci | ✅ 已实现（PRs #24+#25） |

### 创作工具链（0.2.0，Phase 2）

| Feature | 规格 | 主侧 | 功能域 | 状态 |
|---------|------|------|------|------|
| F9 角色管理（提取型样板） | [`f9-character/spec.md`](f9-character/spec.md) | 后端 | api | ✅ 已实现（PR #56） |
| F10 世界观管理（镜像成品） | [`f10-world-settings/spec.md`](f10-world-settings/spec.md) | 后端 | api | ✅ 已实现（PR #57） |
| F11 大纲管理（生成型） | [`f11-outline/spec.md`](f11-outline/spec.md) | 后端 | writing | ✅ 已实现（PR #58） |
| F12 时间线管理（确定性检查型） | [`f12-timeline/spec.md`](f12-timeline/spec.md) | 后端 | api | ✅ 已实现（PR #63） |
| F13 伏笔管理（F6 集成型） | [`f13-foreshadowing/spec.md`](f13-foreshadowing/spec.md) | 后端 | api | ✅ 已实现（PR #64） |
| F14 统一提取（横切收敛型门面） | [`f14-extraction/spec.md`](f14-extraction/spec.md) | 后端 | extraction | ✅ 已实现（PR #72） |
| F15 一致性审计（横切审计型） | [`f15-consistency-audit/spec.md`](f15-consistency-audit/spec.md) | 后端 | audit | ✅ 已实现（PR #74） |
| F16 风格检测（确定性文本分析型） | [`f16-style-analysis/spec.md`](f16-style-analysis/spec.md) | 后端 | writing | ✅ 已实现（PR #75） |
| F87 LangGraph 状态重构 | 并入 [`f4-pipeline-engine/spec.md`](f4-pipeline-engine/spec.md)（见附录） | 后端 | agent | ✅ 已实现（PR #110，2026-08-29 并入 F4） |

### GUI 桌面与传输（0.3.0）

| Feature | 规格 | 主侧 | 功能域 | 状态 |
|---------|------|------|------|------|
| F19 GUI（多子任务章节 §2-§9） | [`f19-gui/spec.md`](f19-gui/spec.md) | 前端 | gui | ✅ §2-§9 已合入 |
| F19 打包分发 | [`f19-packaging/spec.md`](f19-packaging/spec.md) | 跨端 | packaging | ✅ 已实现（PR #144+#145，v0.4.0） |
| F23 SSE 流式（传输增强型） | [`f23-sse/spec.md`](f23-sse/spec.md) | 后端 | transport | ✅ 已实现（PR #83） |

### 内核服务化与设置（0.5.0，ADR-030）

| Feature | 规格 | 主侧 | 功能域 | 状态 |
|---------|------|------|------|------|
| F24 会话管理（会话履历型） | [`f24-session/spec.md`](f24-session/spec.md) | 后端 | session | ✅ 已实现（PR #157） |
| F30 内核冷启动基建（客户端发现型） | [`f30-kernel/spec.md`](f30-kernel/spec.md) | 后端 | kernel | ✅ 已实现（PR #171） |
| F31 GUI 托盘常驻 | [`f31-gui-tray/spec.md`](f31-gui-tray/spec.md) | 前端 | gui | ✅ 已实现（PR #172） |
| F32 设置持久化（设置域横切型） | [`f32-settings/spec.md`](f32-settings/spec.md) | 跨端 | settings | ✅ 已实现（PR #176+#197） |
| F33 CLI 独立发布产物 | [`f33-cli-dist/spec.md`](f33-cli-dist/spec.md) | 后端 | cli | ✅ 已实现（PR #181） |

### 导出 + 搜索 + 世界观（0.6.0）

| Feature | 规格 | 主侧 | 功能域 | 状态 |
|---------|------|------|------|------|
| F21 导出服务 | [`f21-export/spec.md`](f21-export/spec.md) | 后端 | export | ✅ 已实现（PR #214） |
| F22 全文搜索 | [`f22-search/spec.md`](f22-search/spec.md) | 后端 | rag | ✅ 已实现（PR #216） |
| F34 章节审计 | [`f34-chapter-audit/spec.md`](f34-chapter-audit/spec.md) | 后端 | audit | ✅ 已实现（PR #219） |
| F38 CLI 恒经 HTTP（传输改造型） | [`f38-cli-http/spec.md`](f38-cli-http/spec.md) | 后端 | cli | ✅ 已实现（PR #213） |
| F35 世界观地点层级（树型） | [`f35-world-tree/spec.md`](f35-world-tree/spec.md) | 后端 | api | ✅ 已实现（PR #215） |
| F36 世界观地图视图（资产呈现型） | [`f36-world-map/spec.md`](f36-world-map/spec.md) | 后端 | api | ✅ 已实现（PR #220） |
| F37 世界观跨书复制（复用型） | [`f37-world-copy/spec.md`](f37-world-copy/spec.md) | 后端 | api | ✅ 已实现（PR #223） |

### Agent 化升级（0.7.0，已交付 ✅）

| Feature | 规格 | 主侧 | 功能域 | 状态 |
|---------|------|------|------|------|
| F26 Agent 工具基础设施 | [`f26-agent-tools/spec.md`](f26-agent-tools/spec.md) | 后端 | agent | ✅ 已实现（PR #236） |
| F27 Writer Agent 闭环 | [`f27-writer-agent/spec.md`](f27-writer-agent/spec.md) | 后端 | agent | ✅ 已实现（spec PR #240 + 实现 PR #241） |
| F28 记忆系统 | [`f28-memory-learning/spec.md`](f28-memory-learning/spec.md) | 后端 | memory | ✅ 已实现（PR #242） |

### 编排完全体 + Supervisor + 设定库 + skills + CLI（0.8.0，已交付 ✅）

| Feature | 规格 | 主侧 | 功能域 | 状态 |
|---------|------|------|------|------|
| F42 Agent 链配置驱动编排 | [`f42-agent-chain/spec.md`](f42-agent-chain/spec.md) | 后端 | agent | ✅ 已实现（spec-only PR #288/#290/#292/#294 + 实现 PR #299/#305/#308/#309/#315/#314） |
| F43 设定库 GUI 升级 | [`f43-setting-library-gui/spec.md`](f43-setting-library-gui/spec.md) | 前端 | gui | ✅ 已实现（PR #301/#306/#311/#319/#322） |
| F29 Supervisor 自主编排 | [`f29-supervisor/spec.md`](f29-supervisor/spec.md) | 后端 | agent | ✅ 已实现（PR #323 + #324 登记） |
| F19-skills 包 | [`f19-skills/spec.md`](f19-skills/spec.md) | 后端 | skills | ✅ 已实现（PR #304） |
| F10 删除语义统一（v1.1） | [`f10-world-settings/spec.md`](f10-world-settings/spec.md) | 后端 | api | ✅ 已实现（PR #57 v1.0 + #312 v1.1 删除语义统一） |
| F14 提取门面拆分 | [`f14-extraction/spec.md`](f14-extraction/spec.md) | 后端 | extraction | ✅ 已实现（PR #72 + #316 拆分） |

### 多 Agent 一期 + MCP + RAG 切片 + DAG 编排（0.9.0，已交付 ✅）

| Feature | 规格 | 主侧 | 功能域 | 状态 |
|---------|------|------|------|------|
| F39 多 Agent 一期（F39/40/41 合并） | [`f39-multi-agent/spec.md`](f39-multi-agent/spec.md) | 后端 | agent | ✅ 已实现（实现 PR #403/#408/#407） |
| F20 MCP Server | [`f20-mcp/spec.md`](f20-mcp/spec.md) | 后端 | mcp | ✅ 已实现（PR #400/#402） |
| F46 DAG 编排 | [`f46-dag/spec.md`](f46-dag/spec.md) | 后端 | agent | ✅ 已实现（PR #412） |
| F47 写作页聊天框/执行详情页 | [`f47-chat-exec-detail/spec.md`](f47-chat-exec-detail/spec.md) | 跨端 | api+gui | ✅ 已实现（PR #418） |
| F14 RAG 切片扩展（v1.2） | [`f14-extraction/spec.md`](f14-extraction/spec.md) | 后端 | extraction | ✅ 已实现（PR #401/#413） |

### 长任务编排器 + 记忆演进（0.10.0，已交付 ✅）

| Feature | 规格 | 主侧 | 功能域 | 状态 |
|---------|------|------|------|------|
| F44 长任务编排器 | [`f44-book-orchestrator/spec.md`](f44-book-orchestrator/spec.md) | 后端 | agent | ✅ 已实现（spec PR #436/#440 + 实现 PR #441/#443/#445/#446/#447/#448/#453/#454） |
| F45 记忆系统演进 | [`f45-memory-evolution/spec.md`](f45-memory-evolution/spec.md) | 后端 | memory | ✅ 已实现（spec PR #435/#439 + 实现 PR #442/#452） |

## 其他已完成/进行中功能（按功能域）

| Feature | 规格 | 主侧 | 功能域 | 状态 |
|---------|------|------|------|------|
| F48 知识图谱 | [`f48-knowledge-graph/spec.md`](f48-knowledge-graph/spec.md) | 后端 | rag | ✅ 已实现（PR #478/#479） |
| F49 记忆衰减 | [`f49-memory-decay/spec.md`](f49-memory-decay/spec.md) | 后端 | memory | ✅ 已实现（#617/618/619） |
| F50 LangSmith 可观测性 | [`f50-langsmith/spec.md`](f50-langsmith/spec.md) | 后端 | llm | ✅ 已实现（ADR-042，#629） |
| F51 Agent 工具面 v2 | 并入 [`f26-agent-tools/spec.md`](f26-agent-tools/spec.md)（见附录） | 后端 | agent | ✅ 已实现（2026-08-29 并入 F26，#766） |
| F49 自主全自动写作 | 并入 [`f27-writer-agent/spec.md`](f27-writer-agent/spec.md)（见附录） | 后端 | agent | 📝 草案（2026-08-29 并入 F27） |
| F50 MCP 分发引导 | 并入 [`f20-mcp/spec.md`](f20-mcp/spec.md)（见附录） | 后端 | mcp | 📝 草案（2026-08-29 并入 F20） |
| F51 打包产物 Debug 模式 | [`f51-debug-mode/spec.md`](f51-debug-mode/spec.md) | 跨端 | debug | 🔲 待实现（#713/#714/#715，0.13.0） |
| F53 对话机密脱敏 | [`f53-secret-redact/spec.md`](f53-secret-redact/spec.md) | 后端 | security | 📝 草案（#614） |
| F54 执行链路可重放 | [`f54-trace-replay/spec.md`](f54-trace-replay/spec.md) | 后端 | llm | 📝 草案（#615） |
| F55 统一执行视图 | [`f55-unified-exec-view/spec.md`](f55-unified-exec-view/spec.md) | 跨端 | api+gui | 📝 草案（#599） |
| F52 云端 Protocol（P0-11 更名） | [`f52-cloud-protocol/spec.md`](f52-cloud-protocol/spec.md) | 后端 | cloud | ✅ 已实现（PR #37） |
| F58 Chat Agent 层级化工具矩阵 + Scope 授权 | [`f58-agent-tool-scope/spec.md`](f58-agent-tool-scope/spec.md) | 跨端 | agent | 📝 草案（ADR-050，0.13.0） |

### 卷概念统一（0.12.0，P0）

| Feature | 规格 | 主侧 | 功能域 | 状态 |
|---------|------|------|------|------|
| 卷数据模型统一（Volume↔卷纲） | [`f56-volume-outline-link/spec.md`](f56-volume-outline-link/spec.md) | 后端 | api | 📝 草案（#592） |

---

> F17 空置（PRD §6.2 标题残留编号）；F18 云端（2.0.0）、F20 MCP（0.9.0）；F25 daemon 已移除（ADR-029）不复用。
