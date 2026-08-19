# InkFlow — AI 辅助小说创作工具

**本地优先的 AI 小说创作工作台**：用 AI 规划大纲、撰写章节、修订文本；管理角色、世界观、时间线、伏笔；审计一致性与风格痕迹。数据存本地，无账号，API Key 加密存储。

> **完整功能清单（当前 + 规划）见 [`FEATURES.md`](FEATURES.md)** —— 本文档只列要点。

## ✨ 功能特性

### 已实现（0.1.0 → 0.10.1）

- **AI 写作管道**：生成 → 续写 → 修订，Agent 角色链编排（架构师 / 写手 / 审阅 / 修订，LangGraph）
- **创作工具链 8 件套**：
  - 角色管理（档案 / 关系图谱 / 分组，AI 提取）
  - 世界观管理（条目 / 分类汇总，AI 提取）
  - 大纲管理（大纲 / 情节点 / 弧线，AI 生成）
  - 时间线管理（事件 / 叙事双时间线 + 一致性检查）
  - 伏笔管理（埋设 / 回收追踪，写作时自动注入上下文）
  - 统一提取（6 种类型一键提取 + 增量同步 + **RAG 向量检索**）
  - 一致性审计（角色 / 时间线 / 世界 / 伏笔 4 维度）
  - 风格检测（风格指纹 / AI 痕迹 / 词汇分析）
- **GUI 桌面端（0.3.0）**：Electron 壳 + 内核进程化 + React 渲染层（项目页 / 写作页三栏 / Agent 配置页，SSE 流式输出）
- **本地产品完善（0.4.0）**：打包分发（NSIS 安装包 + 便携 ZIP，v0.4.0 2026-08-07 正式发布）· 导航重构（侧边栏 + 设定库项目上下文 + 设置页框架）· 模型管理页（多 Provider/Model 注册 + 角色绑定）· Agent 模板（引用式 + 角色独立温度 + 风险确认）
- **Agent 集成（0.5.0，v0.5.0 2026-08-08 正式发布）**：会话管理（F24：四态状态机 + 两级删除）· 本地内核服务化（冷启动 kernel.json + GUI 托盘常驻 + CLI 独立发布产物，ADR-030）· 设置持久化（app_settings + 跨重启保留 + 顶部「已保存」提示）· E2E 按页面域拆分（6 job，ADR-028）
- **导出 + 搜索 + 世界观（0.6.0，2026-08-09 里程碑关闭）**：TXT 导出（F21）· 全文搜索（F22：FTS5+jieba+语义检索）· 章节审计（F34：audit_logs + CLI/GUI 确认闭环）· 世界观三连（F35 地点树 / F36 地图视图 / F37 跨书复制）· CLI 恒经 HTTP（ADR-030 ② 落地，冷启动 4.7s→热调用 ~214ms）· 设置页 E2E 补全
- **Agent 化升级（0.7.0，v0.7.0 2026-08-12 正式发布）**：Agent 工具基础设施（F26：deepagents 0.7.5 harness + 5 只读工具）· Writer Agent 闭环（F27：ReAct 工具循环 + save_draft 草稿确认流 + 四重护栏 + 决策轨迹）· 记忆系统（F28：从修改/确认行为学习项目偏好 N≥2 + 写作上下文注入 + `inkflow memory list/remove` 可控）· 数据目录设置（#266：`config set data-dir` + GUI 设置页，instance.env 持久化，数据/DB/向量库整体迁移）· 模型测试按钮（#267：ProviderDialog 一键测试真实连接）· E2E 增强（#142/#143）· bug 批（#229 404 映射 / #230 revise 模型回退 / #225 开关持久化 / #231 chapter list / #232 项目卡片跳转）
- **编排完全体 + Supervisor + 设定库 + RAG + skills + CLI（0.8.0，2026-08-13 18/18 issues 全关）**：
  - **编排完全体（F42）**：Agent 链三态模型选择（真禁用/项目默认/指定模型）· 执行顺序编辑（agent_order 层级拓扑，槽位 0-9 同层并行）· 默认管线模板（builtin:write_auto 全自动 + builtin:write_continue 续写）· GUI 写作入口管线化 · 自定义 Agent 数据面 + UI（RoleTemplate prompt/name + ProjectConfig 自定义角色）
  - **F29 Supervisor 自主编排 + HITL**：Command(goto) 动态路由 + 振荡护栏 + deterministic 回退 + 关键节点人工确认
  - **删除语义统一**：普通实体软删→真删（F1 回收站/F24 归档保留软删）
  - **RAG 指纹一致性**：向量指纹 + stale 检测 + 重新向量化协议
  - **F19-skills 包**：官方 skills/inkflow/ 资产 + 用户自定义轨 skills 命令组（install/list/verify/remove）
  - **CLI 命令面补齐**：provider 管理 / agent template 管理 / project config
  - **设定库 GUI 升级（F43）**：CRUD 闭环 + 角色等级标签 + 世界观地图工作台 + 大纲三级 + 时间线双序
- **多 Agent 一期 + MCP + RAG 切片 + DAG 编排（0.9.0，2026-08-17 正式发布，21/21 issues 全关）**：
  - **多 Agent 能力（F39/40/41）**：Agent/Skill 实体 + 能力白名单装配 + 内置出厂配置 + skill 上传绑定 + 自定义 Agent 编辑（分组 checkbox）
  - **F20 MCP Server**：stdio 薄客户端经 HTTP + 15 聚合工具（manage_* action 枚举）+ 冷启动链路
  - **RAG 切片增强**：段落/对话/LLM 三档切片 + 滑动重叠 + 检索元数据 + 指纹联动
  - **F46 DAG 编排**：agent_relations 三类型（顺序/数据传递/条件分支）+ 确定性 gate + 列表式编辑器
  - **写作管线增强**：write_continue F6 前文摘要 + HITL GUI + 设定驱动写作（G1）+ 写作页 AI 聊天框/执行详情页
  - **GUI 修复 + 治理**：内核门控封面 + 地图 resize + 世界观导航 + unit-frontend 假绿治本 + LLM 默认切 deepseek
- **长任务编排器 + 记忆演进（0.10.0，2026-08-18，20/20 issues 全关）**：
  - **F44 长任务编排器（一句话→全书）**：访谈式 Planner（≤5 问 +「全部你决定」）→ 顺序派发 + 章级进度状态机 + 多维上限 + 内容已写安全阀 → Send map-reduce 卷级编排 + 卷级 HITL + 失败恢复 → AsyncSqliteSaver 持久化 + 跨重启 resume + 干预 API（pause/resume/改向/编辑）
  - **F45 记忆系统演进**：用户级偏好层 + 归属分层（项目级/用户级）+ 跨项目聚合 + 语义风格提取（difflib 锚点 → LLM 语义总结，替代字面碎片注入，防幻觉双向堵）
- **UI/产品修复批（0.10.1，2026-08-19，15/15 issues 全关）**：
  - **前置重构**：统一管线执行 hook（合并 usePipeline/ChatPanel/BookRunPanel 三处轮询）+ 角色集合单一来源（6 内置 agent role_key 真源）
  - **访谈 LLM 动态提问（F44 v1.2）**：模型未配置前置校验 + 访谈改名「开始对话」+ 通用必答 + 针对性 + 确定项提取 + 冲突回确认 + 总体确认 + 会话落库（LLM 失败降级确定性兜底）
  - **chat 重构**：chat 搬入工具栏栏 + 展开/收缩/拖动 + 插入校验（意图分离）+ 多生成单选
  - **知识图谱（F48）**：knowledge_relations 关系表 + 图谱画布（拖拽/缩放/点击详情/增删改）+ 定时任务规则/AI 提取
  - **检索页**：RAG embedding 增强检索
  - **模型/设置**：模型/设置合并（删 /models 页）+ 项目聚合设置页 + 模型发现（/models 拉取 + 模型 ID 点选）
  - **Agent 链动态化（F42 v1.5）**：链增删改角色 + 6 内置皆可进链 + 模板联动
  - **内置 Agent/Skill 详情复制** + **会话/记忆 UI**（列表/归档/删除 + 记忆展示/提取）
- **上下文智能装配**：写作时自动注入相关角色、世界观、伏笔，分层 Token 预算
- **多界面战略**：CLI（Typer）✅ + REST API（FastAPI）✅ + GUI（Electron + React）✅ + MCP Server ✅ + 云端 Web（2.0.0）🔜

### 规划中

云存档与异地写作（2.0.0）——明细见 [`FEATURES.md`](FEATURES.md)。

## 🚀 快速开始

前置：**Python 3.11+**，推荐 [uv](https://docs.astral.sh/uv/)。

```bash
# 1. 克隆
git clone https://github.com/zhx-xi/InkFlow.git
cd InkFlow/backend

# 2. 安装依赖（开发环境）
uv sync --extra dev

# 3. 查看 CLI（用 uv run 自动使用项目 venv backend/.venv）
uv run inkflow --help

# 4. 建一个项目试试
uv run inkflow project create "我的第一本小说"

# 5. 启动 REST API（Swagger: http://127.0.0.1:8000/docs）
uv run inkflow serve
```

> 不装 uv 也可以用 `pip install -e .`（在 `backend/` 目录下）。
> **Windows 注意**：不要直接敲 `python -m inkflow`——PATH 里的 `python` 可能解析到系统或其他虚拟环境（报 `No module named inkflow`）。统一用 `uv run`，或先激活项目 venv（`.\\.venv\\Scripts\\Activate.ps1`）再执行。

## 🏗️ 系统架构

**现状架构（模块化单体 + Clean Architecture）**：

![InkFlow 系统架构图](docs/images/inkflow-architecture.png)

**2.0.0 云端目标架构（云存档 + 异地写作，规划中，[ADR-024](adr/ADR-024.md)）**：

![InkFlow 2.0.0 云端目标架构图](docs/images/inkflow-cloud-architecture-2.0.0.png)

> 交互版（浅色/暗色主题切换）见 [`design/inkflow-architecture.html`](design/inkflow-architecture.html) 与 [`design/inkflow-cloud-architecture-2.0.0.html`](design/inkflow-cloud-architecture-2.0.0.html)（浏览器打开）。

## 🗺️ 文档导航

| 文档 | 内容 | 读者 |
|------|------|------|
| [`FEATURES.md`](FEATURES.md) | **功能清单（当前 + 规划，唯一权威）** | 所有人 |
| [`CHANGELOG.md`](CHANGELOG.md) | 版本变更日志（0.1.0 → 0.9.0） | 所有人 |
| [`design/`](design/) | 产品规格（PRD）、架构分析、里程碑评审、开发工作流 | 开发者 |
| [`specs/`](specs/) | 功能规格书（每 feature 一份，SDD 真相来源） | 开发者 |
| [`adr/`](adr/README.md) | 架构决策记录（38 条 + 索引） | 开发者 |
| [`backend/README.md`](backend/README.md) | 后端包说明（结构 / 开发环境 / 版本号机制） | 开发者 |
| [`docs/`](docs/README.md) | 使用说明（用户手册 / CLI 参考 / API 文档，建设中） | 用户 |
| [`AGENTS.md`](AGENTS.md) | AI 编码助手说明书（项目总约定 + 治理规则） | AI agent |

## 🧭 里程碑

| 版本 | 主题 | 状态 |
|------|------|------|
| 0.1.0 | 核心引擎（F1-F8 + 云端 Protocol） | ✅ |
| 0.2.0 | 创作工具链（F9-F16，1589 tests / 覆盖率 91%） | ✅ |
| 0.3.0 | GUI 桌面端 + SSE 流式（F19/F23 提前） | ✅ |
| 0.3.1 | 质量加固：LLM 客户端修复 · LangGraph 状态重构 · 真实 AI CI · 覆盖率补全（2200+ tests / 后端 98.9% 行 / 96.3% 分支 / 前端 99.1% / 92.5%） | ✅ |
| 0.4.0 | 打包 + GUI 演进（NSIS/便携 ZIP 分发 · 导航重构 · 模型管理 · Agent 模板） | ✅（v0.4.0 2026-08-07 正式发布） |
| 0.5.0 | 会话 + 内核服务化 + 设置持久化 + E2E 分层 | ✅（v0.5.0 2026-08-08 正式发布） |
| 0.6.0 | 导出 + 全文搜索 + 章节审计 + 世界观三连 + CLI 恒 HTTP + E2E 设置页 | ✅（2026-08-09 里程碑关闭） |
| 0.7.0 | Agent 化升级（deepagents harness · Writer Agent 闭环 · 记忆系统 · 数据目录设置 · 模型测试 · E2E/bug 批） | ✅（v0.7.0 2026-08-12 正式发布） |
| 0.8.0 | 编排完全体 + Supervisor + 设定库 + RAG 指纹 + skills + CLI（F42/F29/F43/F19-skills/F10） | ✅（2026-08-13 里程碑 18/18 issues 全关） |
| 0.9.0 | 多 Agent 一期 + MCP + RAG 切片 + DAG 编排（F39/40/41 + F20 + F46 + 写作管线增强） | ✅（2026-08-17 正式发布，21/21 issues 全关） |
| 0.10.0 | 长任务编排器 + 记忆演进（F44 一句话→全书 + F45 记忆 AI 总结） | ✅（2026-08-18，20/20 issues 全关） |
| 0.10.1 | UI/产品修复批（前置重构 + 访谈 LLM + chat 重构 + 知识图谱 + 检索页 + 模型/设置 + Agent 链动态化 + 会话/记忆 UI） | ✅（2026-08-19，15/15 issues 全关） |
| 1.0.0 | 本地完全可用（CLI + GUI + skills + MCP） | 🔜 |
| 2.0.0 | 云端（云存档 + 异地写作） | 🔜 |

## 🛠️ 技术栈

Python 3.11 · FastAPI（REST）· Typer（CLI）· SQLAlchemy 2 async + SQLite（未来 PostgreSQL）· LangChain / LangGraph + Deep Agents harness（deepagents 0.7.5，agentic 编排，0.7.0 起）+ 自研 LangGraph StateGraph Supervisor 动态路由（F29，0.8.0 起）· Chroma + BGE（RAG）· React 19 + Vite 6 + shadcn/ui + Zustand + Tailwind 4（前端，0.3.0 起）· Electron 34（桌面壳，0.3.0 起）

架构：**模块化单体 + Clean Architecture**（domain / infrastructure / api / cli 分层，依赖方向单向），决策全部记录于 [`adr/`](adr/README.md)。

## 📄 License

MIT
