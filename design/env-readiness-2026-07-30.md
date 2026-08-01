# InkFlow — 环境就绪检查报告

**日期**: 2026-07-30
**项目**: InkFlow
**本地路径**: `D:\develop\projects\InkFlow`
**Hermes 工作区**: `D:\develop\hermes-projects\InkFlow`

---

## 1. 开发环境就绪矩阵

### 1.1 运行时环境

| 组件 | 版本 | 状态 | 备注 |
|------|------|------|------|
| Python | 3.11.15 | ✅ | Hermes 当前隔离环境 |
| uv | 0.11.14 | ✅ | 极速依赖解析、工具安装 |
| pip | 26.1.2 | ✅ | Hermes venv |
| Git | 已安装 | ✅ | 仓库已配置 remote origin |
| Node.js | 待确认 | ❓ | Phase 2 前端开发需要，需检查是否在系统 PATH 中 |

### 1.2 已安装 Python 依赖

| 包 | 版本 | 状态 | 用途 |
|----|------|------|------|
| FastAPI | 0.136.3 | ✅ | Web 框架 |
| uvicorn | 0.49.0 | ✅ | ASGI 服务器 |
| Pydantic | 2.13.4 | ✅ | 数据验证 |
| pydantic-settings | 2.14.2 | ✅ | 配置管理 |
| httpx | 0.28.1 | ✅ | HTTP 客户端 + 测试 |
| httpx-sse | 0.4.3 | ✅ | SSE 客户端 |
| click | 8.4.1 | ✅ | CLI 底层（Typer 依赖） |
| rich | 14.3.3 | ✅ | 终端美化 |

### 1.3 需要安装的依赖

#### 🔴 Phase 1 必装（核心引擎骨架）

```bash
# CLI 框架
pip install typer

# ORM + 数据库
pip install sqlalchemy[asyncio]
pip install aiosqlite

# 数据库迁移
pip install alembic

# 测试框架
pip install pytest
pip install pytest-asyncio

# Token 计数（LLM 相关）
pip install tiktoken

# API Key 加密存储
pip install cryptography

# 发送 HTTP 请求到 LLM API（httpx 已安装）
```

#### 🟡 Phase 1 推荐

```bash
# 结构化日志
pip install loguru

# 覆盖率
pip install pytest-cov

# Git 钩子
pip install pre-commit
```

#### 🟢 基础开发需求后安装

```bash
# 代码质量
pip install ruff           # Python linter（替代 flake8/black/isort）
pip install mypy           # 类型检查

# Phase 2：前端（Node.js 环境）
# npm install / yarn install

# Phase 2：打包
# pip install pyinstaller
# pip install pywebview

# Phase 3：MCP SDK
# pip install mcp
```

### 1.4 工具就绪

| 工具 | 状态 | 用途 |
|------|------|------|
| ```specify``` CLI v0.4.3 | ✅ | SDD 规格驱动开发 |
| GitHub CLI (gh) | ❓ 待检查 | PR/Issue 管理 |
| pre-commit | ❌ 需安装 | Git 提交钩子 |

---

## 2. SDD 工作流就绪状态

### 已加载的 Hermes Skill

| Skill | 状态 | 用途 |
|-------|------|------|
| spec-kit-sdd | ✅ | SDD 工作流（Constitution→Spec→Clarify→Plan→Tasks→Implement）|
| plan | ✅ | 编写实施计划 |
| test-driven-development | ✅ | TDD 循环强制 |
| requesting-code-review | ✅ | 提交前代码审查 |
| github-pr-workflow | ✅ | GitHub PR 管理 |
| github-code-review | ✅ | 代码审查 |
| systematic-debugging | ✅ | 系统化调试 |

### SDD 初始化步骤

```bash
cd D:\develop\projects\InkFlow
specify init . --integration openclaw
```

初始化后将生成：
- `.specify/` — 配置目录
- `.specify/constitution.md` — 空模板（需编写）
- `.specify/templates/` — 规格/计划/任务模板

---

## 3. 前置准备清单（按顺序）

### Step 1: 确认 PyPI 包名（5 分钟）
- 检查 `inkflow` 在 PyPI 是否可用
- 如被占用，需改名（建议备选：`ink-flow`, `inkflow-cli`）

### Step 2: 安装依赖（10 分钟）
```bash
pip install typer sqlalchemy[asyncio] aiosqlite alembic
pip install pytest pytest-asyncio pytest-cov
pip install tiktoken cryptography loguru
pip install pre-commit ruff mypy
```

### Step 3: SDD 初始化（5 分钟）
```bash
cd D:\develop\projects\InkFlow
specify init . --integration openclaw
```

### Step 4: 创建项目 Python 包结构（15 分钟）
```
InkFlow/
├── .specify/            # SDD 配置
├── src/
│   └── inkflow/         # 主包
│       ├── __init__.py
│       ├── __main__.py  # Entry point: inkflow
│       ├── api/         # FastAPI 路由
│       ├── models/      # Pydantic + SQLAlchemy 模型
│       ├── services/    # 业务逻辑
│       ├── providers/   # LLM Provider 适配器
│       ├── cli/         # Typer CLI 命令
│       └── core/        # 配置、日志、数据库
├── tests/               # 测试目录
├── docs/                # 文档
├── specs/               # SDD 规格文件
├── pyproject.toml       # 项目配置
└── README.md            # 项目介绍
```

### Step 5: 编写 Constitution（30 分钟）
- 项目原则、技术标准、开发规范
- 代码质量标准（TDD 强制、覆盖率 ≥ 70%）
- 架构原则（Protocol-first、依赖注入、单一职责）
- 提交规范（conventional commits）

### Step 6: 编写 Phase 1 Spec（1-2 小时）
入 F1-F7 的完整规格文件：
- F1: 项目/书籍管理
- F2: 章节管理
- F3: AI 写作管道
- F4: Agent 编排
- F5: LLM Provider 适配
- F6: 上下文管理
- F7: CLI 接口

### Step 7: 搭建 CI 流水线（30 分钟）
- GitHub Actions 配置
- pytest 自动运行
- Ruff lint
- Mypy 类型检查

---

## 4. 风险与注意事项

### 已知风险
1. **Hermes venv vs 项目 venv**：当前 FastAPI 安装于 Hermes 的 venv 中。项目应创建独立 venv，使用 `uv venv` 隔离环境
2. **Windows 路径问题**：部分 Python 包在 Windows 上有特殊处理需求（如 `uvicorn[standard]` 的 watchfiles）
3. **Node.js 版本**：Phase 2 前端需确认 Node.js 可用版本
4. **PyPI 包名**：`inkflow` 可能被占用，需确认

### 已记录到 Memory 的信息
- 项目路径：`D:\develop\projects\InkFlow`（源码） / `D:\develop\hermes-projects\InkFlow`（工作区）
- 远程仓库：`https://github.com/zhx-xi/InkFlow.git`
- CLI 命令：`inkflow`
- SDD 工作流：spec-kit-sdd skill
- 技术栈：FastAPI + SQLAlchemy async + Typer + Pydantic v2 + SQLite
