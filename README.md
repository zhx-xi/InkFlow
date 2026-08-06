# InkFlow — AI 辅助小说创作工具

**本地优先的 AI 小说创作工作台**：用 AI 规划大纲、撰写章节、修订文本；管理角色、世界观、时间线、伏笔；审计一致性与风格痕迹。数据存本地，无账号，API Key 加密存储。

> **完整功能清单（当前 + 规划）见 [`FEATURES.md`](FEATURES.md)** —— 本文档只列要点。

## ✨ 功能特性

### 已实现（0.1.0 → 0.3.1）

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
- **上下文智能装配**：写作时自动注入相关角色、世界观、伏笔，分层 Token 预算
- **多界面战略**：CLI（Typer）✅ + REST API（FastAPI）✅ + GUI（Electron + React）✅ + MCP Server（1.0.0）🔜 + 云端 Web（2.0.0）🔜

### 规划中

打包分发（0.4.0）· 会话 / daemon（0.5.0）· skills 包 + MCP Server（1.0.0）· 导出 / 全文搜索（0.6.0）· 云存档与异地写作（2.0.0）——明细见 [`FEATURES.md`](FEATURES.md)。

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
| [`design/`](design/) | 产品规格（PRD）、架构分析、里程碑评审、开发工作流 | 开发者 |
| [`specs/`](specs/) | 功能规格书（每 feature 一份，SDD 真相来源） | 开发者 |
| [`adr/`](adr/README.md) | 架构决策记录（27 条 + 索引） | 开发者 |
| [`docs/`](docs/README.md) | 使用说明（用户手册 / CLI 参考 / API 文档，建设中） | 用户 |
| [`AGENTS.md`](AGENTS.md) | AI 编码助手说明书（项目总约定 + 治理规则） | AI agent |

## 🧭 里程碑

| 版本 | 主题 | 状态 |
|------|------|------|
| 0.1.0 | 核心引擎（F1-F8 + 云端 Protocol） | ✅ |
| 0.2.0 | 创作工具链（F9-F16，1589 tests / 覆盖率 91%） | ✅ |
| 0.3.0 | GUI 桌面端 + SSE 流式（F19/F23 提前） | ✅ |
| 0.3.1 | 质量加固：LLM 客户端修复 · LangGraph 状态重构 · 真实 AI CI · 覆盖率补全（2200+ tests / 后端 98.9% 行 / 96.3% 分支 / 前端 99.1% / 92.5%） | ✅ |
| 0.4.0 | 打包分发 | 🔜 |
| 0.5.0 | 会话 + daemon | 🔜 |
| 0.6.0 | 导出 + 全文搜索 | 🔜 |
| 1.0.0 | 本地完全可用（CLI + GUI + skills + MCP） | 🔜 |
| 2.0.0 | 云端（云存档 + 异地写作） | 🔜 |

## 🛠️ 技术栈

Python 3.11 · FastAPI（REST）· Typer（CLI）· SQLAlchemy 2 async + SQLite（未来 PostgreSQL）· LangChain / LangGraph（LLM / Agent）· Chroma + BGE（RAG）· React 19 + Vite 6 + shadcn/ui + Zustand + Tailwind 4（前端，0.3.0 起）· Electron 34（桌面壳，0.3.0 起）

架构：**模块化单体 + Clean Architecture**（domain / infrastructure / api / cli 分层，依赖方向单向），决策全部记录于 [`adr/`](adr/README.md)。

## 📄 License

MIT
