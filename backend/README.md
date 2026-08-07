# InkFlow 后端（Python 内核）

InkFlow 的本地 AI 写作内核：领域逻辑 + LLM/Agent/RAG 基础设施 + CLI + REST API，以模块化单体 + Clean Architecture 组织（[ADR-001/002](adr/README.md)）。

## 目录结构

```
backend/
├── pyproject.toml          # 依赖 + 工具配置（Ruff / mypy / pytest / hatchling）
├── uv.lock                 # 依赖锁定唯一真相（ADR-025，CI --frozen）
├── .venv/                  # 本地虚拟环境（uv 创建，勿手工 venv）
├── src/inkflow/
│   ├── core/               # 配置、数据库连接（WAL/busy_timeout、幂等迁移）
│   ├── domain/             # 领域层：models / services / ports（Protocol，零框架依赖）
│   ├── infrastructure/     # 基础设施层：database / llm / agent / rag / prompt / context
│   ├── api/                # FastAPI 表现层（routers + deps）
│   ├── cli/                # Typer 表现层（commands）
│   └── mcp/                # 表现层：MCP Server（1.0.0 F20 建立，ADR-023）
└── tests/                  # 单元测试（集成/API/CLI 测试在仓库根 tests/）
```

> 完整目录树见 `ARCHITECTURE.md §2`；模块功能清单见仓库根 `FEATURES.md`。

## 开发环境

```powershell
# 前提：Python 3.11+ + uv
cd backend
uv sync --extra dev        # 安装开发依赖（dev 组在 [project.optional-dependencies]）
uv run inkflow --help      # 查看 CLI（uv run 自动使用 backend/.venv）
```

- **依赖锁定纪律（ADR-025）**：日常 `uv sync --frozen`；升级依赖 = 改 pyproject → `uv lock` → 全量测试 → PR 附带 lock 变更。禁止 `python -m venv` / `virtualenv` 手工建 venv。
- **测试**：单元 `uv run pytest tests/unit/ -q`；集成/API/CLI 在仓库根 `tests/`（CI 分层见 ADR-018；覆盖率门禁 98.5/95.0 见 ADR-027）。

## 版本号机制

**源码树版本 ≠ 发布版本**（有意设计）：

| 位置 | 版本 | 说明 |
|------|------|------|
| `pyproject.toml` | 0.1.0 | 开发基线版本 |
| `src/inkflow/__init__.py` | 动态 | `importlib.metadata` 读取已安装包版本 |
| 发布产物 | v0.4.0 等 | `release.yml` 在 tag v* 触发时注入 `pyproject.toml`（先于 uv sync），构建出的内核 exe 版本 = tag 版本 |

因此开发期 `inkflow.__version__` 可能显示 0.1.0（editable install 的 dist-info 记录 pyproject 版本），发布产物显示 tag 版本（如 0.4.0）——这是正常行为，非缺陷。发布流程见 `.github/workflows/release.yml`（f19-packaging spec `specs/f19-packaging/spec.md` §2.4）。

## 数据库迁移

无 Alembic 基建（依赖已声明但未启用）：schema 由 `Base.metadata.create_all` 管理（lifespan 启动建表），结构变更采用轻量幂等迁移（PRAGMA 判列 + ALTER TABLE，接线于 `core/database.py`）。详见 `AGENTS.md §2 技术栈「迁移」行`。

## 相关文档

- 项目总约定 / AI 行为准则：仓库根 `AGENTS.md`
- 架构导航：仓库根 `ARCHITECTURE.md`
- 功能规格（SDD 真相来源）：仓库根 `specs/`
- 架构决策记录：仓库根 `adr/README.md`
- 功能清单：仓库根 `FEATURES.md`
- 变更日志：仓库根 `CHANGELOG.md`
