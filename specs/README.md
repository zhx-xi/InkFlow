# specs/ — 功能规格索引

> SDD（Spec-Driven Development）真相来源：每 feature 一个目录 `specs/f<编号>-<短名>/spec.md`。
> 版本归属以 [ADR-019 v5](../adr/ADR-019.md) 为准；完整功能清单见 [FEATURES.md](../FEATURES.md)。
> 篇幅纪律（2026-08-08 #201 立规）：新 spec 默认单文件 ≤800 行；超过且章节内聚可拆时允许 `references/` 子目录（spec.md 头部必须声明清单）；已实现 spec 只加「快速导航」块不物理拆分。

## 分类索引

### 核心引擎（0.1.0，Phase 1）

| Feature | 规格 | 状态 |
|---------|------|------|
| F1 项目服务 | [`f1-project-service/spec.md`](f1-project-service/spec.md) | ✅ 已实现（PR #8） |
| F2 章节服务 | [`f2-chapter-service/spec.md`](f2-chapter-service/spec.md) | ✅ 已实现（PR #9） |
| F3 写作管道 | [`f3-writing-service/spec.md`](f3-writing-service/spec.md) | ✅ 已实现（PR #21） |
| F4 Agent 编排 | [`f4-agent-service/spec.md`](f4-agent-service/spec.md) | ✅ 已实现（PR #22） |
| F5 LLM Provider | [`f5-llm-provider/spec.md`](f5-llm-provider/spec.md) | ✅ 已实现（PR #16） |
| F6 上下文服务 | [`f6-context-service/spec.md`](f6-context-service/spec.md) | ✅ 已实现（PR #27） |
| F7 CLI 接口 | [`f7-cli-interface/spec.md`](f7-cli-interface/spec.md) | ✅ 已实现（PR #28） |
| F8 CI 测试分层 | 无独立 spec（ADR-018） | ✅ 已实现（PRs #24+#25） |
| P0-11 云端 Protocol | [`p0-11-cloud-protocols/spec.md`](p0-11-cloud-protocols/spec.md) | ✅ 已实现（PR #37） |

### 创作工具链（0.2.0，Phase 2）

| Feature | 规格 | 状态 |
|---------|------|------|
| F9 角色管理（提取型样板） | [`f9-character-service/spec.md`](f9-character-service/spec.md) | ✅ 已实现（PR #56） |
| F10 世界观管理（镜像成品） | [`f10-world-service/spec.md`](f10-world-service/spec.md) | ✅ 已实现（PR #57） |
| F11 大纲管理（生成型） | [`f11-outline-service/spec.md`](f11-outline-service/spec.md) | ✅ 已实现（PR #58） |
| F12 时间线管理（确定性检查型） | [`f12-timeline-service/spec.md`](f12-timeline-service/spec.md) | ✅ 已实现（PR #63） |
| F13 伏笔管理（F6 集成型） | [`f13-foreshadowing-service/spec.md`](f13-foreshadowing-service/spec.md) | ✅ 已实现（PR #64） |
| F14 统一提取（横切收敛型门面） | [`f14-extraction-service/spec.md`](f14-extraction-service/spec.md) | ✅ 已实现（PR #72） |
| F15 一致性审计（横切审计型） | [`f15-audit-service/spec.md`](f15-audit-service/spec.md) | ✅ 已实现（PR #74） |
| F16 风格检测（确定性文本分析型） | [`f16-style-service/spec.md`](f16-style-service/spec.md) | ✅ 已实现（PR #75） |
| F87 LangGraph 状态重构 | [`f87-langgraph-refactor/spec.md`](f87-langgraph-refactor/spec.md) | ✅ 已实现（PR #110） |

### GUI 桌面与传输（0.3.0）

| Feature | 规格 | 状态 |
|---------|------|------|
| F19 GUI（多子任务章节 §2-§9） | [`f19-gui/spec.md`](f19-gui/spec.md) | ✅ §2-§9 已合入 |
| F19 打包分发 | [`f19-packaging/spec.md`](f19-packaging/spec.md) | ✅ 已实现（PR #144+#145，v0.4.0） |
| F23 SSE 流式（传输增强型） | [`f23-sse-stream/spec.md`](f23-sse-stream/spec.md) | ✅ 已实现（PR #83） |

### 内核服务化与设置（0.5.0，ADR-030）

| Feature | 规格 | 状态 |
|---------|------|------|
| F24 会话管理（会话履历型） | [`f24-session-service/spec.md`](f24-session-service/spec.md) | ✅ 已实现（PR #157） |
| F30 内核冷启动基建（客户端发现型） | [`f30-kernel-bootstrap/spec.md`](f30-kernel-bootstrap/spec.md) | ✅ 已实现（PR #171） |
| F31 GUI 托盘常驻 | [`f31-gui-tray/spec.md`](f31-gui-tray/spec.md) | ✅ 已实现（PR #172） |
| F32 设置持久化（设置域横切型） | [`f32-settings-persistence/spec.md`](f32-settings-persistence/spec.md) | ✅ 已实现（PR #176+#197） |
| F33 CLI 独立发布产物 | [`f33-cli-dist/spec.md`](f33-cli-dist/spec.md) | ✅ 已实现（PR #181） |

### Agent 化升级（0.7.0，规划中）

| Feature | 规格 | 状态 |
|---------|------|------|
| F26 Agent 工具基础设施 | [`f26-agent-tools/spec.md`](f26-agent-tools/spec.md) | ✅ 已拍板（Q1-Q3=A，2026-08-03）待实现 |

---

> F17 空置（PRD §6.2 标题残留编号）；F18 云端（2.0.0）、F20 MCP（1.0.0）、F21 导出（0.6.0）、F22 搜索（0.6.0）、F27-F29 规划中无 spec；F25 daemon 已移除（ADR-029）不复用。
