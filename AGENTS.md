# AGENTS.md — AI 编码助手说明书

> **给 AI 的一句话**：这是一个单人开发的 Python 后端项目，使用 Clean Architecture（模块化单体），
> 严格遵循 SDD（Spec-Driven Development）+ TDD，所有代码必须在 `backend/` 目录下工作。
> 动手写代码之前，先读 `specs/` 中的 spec 和 `design/` 中的架构分析。

---

## 0. 文件体系（先读）

**本文件是 AI 编码助手的唯一约束源**（Hermes 项目上下文 first-match-wins，只加载 AGENTS.md；CLAUDE.md 仅为其他工具的入口跳板）。

| 文件 | 角色 |
|------|------|
| `AGENTS.md`（本文件） | 项目总约定 + AI 行为准则（§10）+ 核心纪律（SDD/TDD/ADR/编码） |
| `ARCHITECTURE.md` | 架构导航：完整目录树、组件职责、模块类型谱系 → 样板 spec、加新模块步骤。**改架构/加模块前先读** |
| `ai-traps.md` | AI 编码常见陷阱完整清单（§9 只留高频 TOP） |
| `FEATURES.md` | 功能清单唯一权威（已实现模块全表 + 规划 + 版本→功能映射） |
| `adr/README.md` | ADR 索引 + 编号规则 + 当前有效决策速览（改代码前先查） |
| `CONTRIBUTING.md` | 人类贡献者指南 |

---

## 1. 项目概览

**InkFlow** 是一个 AI 辅助小说创作工具。帮助作者使用 AI 规划大纲、撰写章节、修订文本、审阅质量。

| 维度 | 说明 |
|------|------|
| **团队** | 单人开发 |
| **部署模式** | 本地优先（SQLite，免认证）；**2.0.0 云端里程碑**：云存档/异地写作（PostgreSQL + JWT + BYOK，无 CRDT），GUI/CLI 远程模式连接云端 |
| **多界面** | GUI（Electron+React）+ CLI（Typer）+ REST API（FastAPI，本地内核通信契约）+ MCP Server（stdio 薄客户端经 HTTP） |
| **工作流** | SDD + TDD：先写 spec → 再写测试（RED）→ 写代码（GREEN）→ 重构 |
| **仓库** | `https://github.com/zhx-xi/InkFlow` |

> 版本里程碑（0.1.0 → 2.0.0，ADR-019 v8）、Phase 1-3 功能全表、模块类型谱系（F9-F46 各变体样板导航）→ **见 `FEATURES.md` + `ARCHITECTURE.md §4`**。F17 空置；F18-F24 版本归属以 ADR-019 v8 为准。

---

## 2. 技术栈

| 层面 | 技术 | 备注 |
|------|------|------|
| 语言 | Python **3.11+** | 必须 `from __future__ import annotations` |
| Web 框架 | FastAPI + uvicorn[standard] | async 优先 |
| CLI | Typer + Rich | `inkflow` 命令入口 |
| ORM | SQLAlchemy 2.0 (async) + aiosqlite | SQLite 本地（schema 由 create_all + 轻量幂等迁移管理，Alembic 未启用） |
| 数据验证 | Pydantic v2 + pydantic-settings | `model_config = {"from_attributes": True}` |
| LLM Provider | langchain-core + langchain-community + langchain-openai | ChatOpenAI（custom base_url 兼容多 Provider，ADR-005v2） |
| Agent 编排 | langgraph + deepagents harness | StateGraph：Phase 1 顺序链，Phase 2 自定义 DAG；Agent 化编排见 ADR-035/036 |
| RAG | langchain-chroma + chromadb + sentence-transformers | 本地向量库 + BGE Embedding（ADR-013） |
| Prompt 模板 | ChatPromptTemplate（langchain-core） | YAML 模板 + 变量验证（ADR-014） |
| 加密/HTTP/日志 | cryptography（AES-256-GCM）+ httpx/httpx-sse + Loguru（ADR-016） | |
| 测试 | pytest + pytest-asyncio + pytest-cov + pytest-rerunfailures | CI 覆盖率门槛：后端 98.5% 行 / 95% 分支（coverage-backend job，口径 ADR-027）、前端 vitest thresholds |
| Lint | Ruff | 规则集见 backend/pyproject.toml；行宽 100 |
| 类型检查 | mypy | 严格化配置见 backend/pyproject.toml；用 `python -m mypy` |
| 构建 | hatchling | `[tool.hatch.build.targets.wheel]` |

---

## 3. 关键路径

| 路径 | 说明 |
|------|------|
| `backend/src/inkflow/` | 源码（core / domain / infrastructure / api / cli / mcp 分层；**完整目录树见 ARCHITECTURE.md §2**） |
| `backend/tests/unit/` | 单元测试（纯后端，无 I/O） |
| `tests/` | 集成 + API + CLI 测试（顶层；conftest.py 共享 fixture） |
| `specs/f<X>-<name>/spec.md` | SDD 规格（每 feature 一个目录，**唯一真相**） |
| `adr/` | ADR 决策记录（索引 `adr/README.md`） |
| `design/` | PRD + 架构分析 + Gate 评审（文件名带日期） |
| `docs/` | 用户使用说明（纯用户文档，README 见 `docs/README.md`） |
| `frontend/` | 前端（pnpm workspace 双包：renderer + electron，0.3.0 F19 起） |
| `ci_cd/` | CI 质量护栏脚本（file_length / noqa_reason） |
| `.github/workflows/ci.yml` | CI（分层触发过滤，PR #82） |
| `D:\develop\projects\InkFlow-ft\<feature>\` | git worktree（每个 feature 一个工作副本，只读主仓） |

---

## 4. 架构规则

### 4.1 架构风格：模块化单体 (Modular Monolith)

**不是微服务。** 单人开发不需要分布式复杂度。但模块之间通过 **Protocol**（接口）严格隔离，为将来按需拆分做准备。

```
表现层 (API/CLI/MCP)  →  应用层  →  领域层 (Service + Model + Port)
                                       ↑
                                 基础设施层 (实现 Port)
```

### 4.2 依赖方向（不可违反）

```
✅ 正确：API/CLI → Domain Service → Port (Protocol) ← Infrastructure (实现)
✅ 正确：所有层都可以依赖 domain/models（纯数据对象）；infrastructure/ 可以导入 langchain_*
❌ 禁止：domain/ 导入 FastAPI、Typer、SQLAlchemy、LangChain、任何框架；domain/ 导入 infrastructure/
❌ 禁止：domain 层出现 "from langchain" 或 "import langchain"；两个 domain service 互相循环导入；domain/ 导入 api/ 或 cli/
```

**🔴 LangChain 隔离规则（CI 强制检查）**：

```bash
# domain 层不允许任何 LangChain import
grep -r "from langchain" src/inkflow/domain/ && echo "VIOLATION: domain layer must not import LangChain" && exit 1
grep -r "import langchain" src/inkflow/domain/ && echo "VIOLATION: domain layer must not import LangChain" && exit 1
```

如果 domain 层需要 LLM/Agent/RAG 能力，通过 `domain/ports/` 中的 Protocol 定义接口，infrastructure 层用 LangChain 实现。

### 4.3 Protocol 契约

领域层通过 `typing.Protocol` 定义出站端口，基础设施层实现（无需显式继承）：

```python
# domain/ports/project_repository.py（实现类无需显式继承 Protocol）
class ProjectRepositoryProtocol(Protocol):
    async def add(self, project: Project) -> Project: ...
    async def get(self, project_id: int) -> Project | None: ...
```

### 4.4 关键设计决策

全部技术选型（模块化单体/六边形分层/SQLite/LLM 路由/Agent 编排/RAG/CI 门禁/版本里程碑等）→ **`adr/README.md`「当前有效决策速览」**，改代码前先查相关 ADR。

**🔴 ADR 治理规则（所有 AI 会话必须遵守）**：

1. 动手改代码前，先查 `adr/README.md` 索引确认相关决策
2. 决策变更（技术选型、架构调整）必须**先写/改 ADR，再改代码**，PR 引用 ADR 编号
3. 新增决策：创建 `adr/ADR-NNN.md`（Nygard 格式：状态 / 背景 / 决策 / 备选方案 / 影响），然后在 `README.md` 索引登记
4. 编号顺序递增不复用；决策被取代时旧 ADR 标记 `已弃用` 并指向新 ADR（如 ADR-005 → ADR-005v2）
5. Constitution §7.3：所有 ADR 保持最新；架构分析文档只保留索引表，不维护内嵌副本

---

## 5. 开发工作流（SDD + TDD）

整个开发流程为：**Spec → Test (RED) → Code (GREEN) → Refactor → PR → Merge**

### 5.1 SDD：Spec 先行

**动手写代码前必须阅读对应的 spec 文件。** 完整 spec 清单见 `specs/` 目录（F8 无 spec，见 ADR-018）；样板 spec（对照最接近的变体）：

| 变体 | 样板 |
|------|------|
| 格式范例（Phase 1） | `specs/f1-project-service/spec.md` |
| 提取型 | `specs/f9-character-service/spec.md`（F10 镜像） |
| 生成型 | `specs/f11-outline-service/spec.md` |
| 横切收敛门面型 | `specs/f14-extraction-service/spec.md` |
| 确定性文本分析型 | `specs/f16-style-service/spec.md` |
| 传输增强型（SSE） | `specs/f23-sse-stream/spec.md` |
| 设置域横切型 | `specs/f32-settings-persistence/spec.md` |
| 配置驱动编排型 | `specs/f42-agent-chain-config/spec.md` |

- 每个模块 spec 定义了：数据模型、API 契约、CLI 命令、边界情况、测试策略
- **spec 是开发的唯一真相来源**。如果发现 spec 与实现矛盾，先更新 spec，再改代码
- **Spec 篇幅纪律（2026-08-08 #201 立规）**：新 spec 默认单文件 ≤800 行；超过且章节内聚可拆时，允许 `specs/f<X>-<name>/references/` 子目录（tests/implementation/decisions 等），但 **spec.md 头部必须显式声明 references/ 清单**（防 agent 漏读）；已实现 spec 只加「快速导航」块（§N 标题 + 行号）不物理拆分

### 5.2 开始新功能

```powershell
# 1. 切换到主仓库并确保 main 最新
cd D:\develop\projects\InkFlow
git checkout main && git pull origin main

# 2. 创建 feature 分支 + worktree（主仓只读，worktree 中工作）
git branch feat/fX-xxx main
git worktree add D:\develop\projects\InkFlow-ft\fX-xxx feat/fX-xxx
git push origin feat/fX-xxx
cd D:\develop\projects\InkFlow-ft\fX-xxx

# 3. 安装开发依赖（依赖锁定见 ADR-025：uv + uv.lock）
cd backend
uv sync --frozen
```

**🔴 依赖锁定约定（ADR-025）**：
- **Python 后端**：`backend/uv.lock` 是唯一真相（锁定全部传递依赖 + sha256）。日常安装/同步一律 `uv sync --frozen`；升级依赖 = 改 pyproject.toml → `uv lock` → 全量测试 → PR 附带 lock 变更。CI 用 `astral-sh/setup-uv@v5` + `uv sync --frozen` + `uv run <cmd>`。**环境创建/重建一律 uv（`uv venv` / `uv sync`），禁止 `python -m venv` / `virtualenv`**（手工 venv 残缺后残留外壳会污染 git status，#123 实测）。
- **前端**：必须提交 `pnpm-lock.yaml`；CI 必须 `pnpm install --frozen-lockfile`（否则 lock 被静默更新 = 没锁）；升级依赖 = 显式 `pnpm update` / 改 package.json 后重新生成 lock，PR 附带 lock 变更。

### 5.3 TDD 循环（RED-GREEN-REFACTOR）

```
1. RED:   写测试 → 运行 → 确认 FAIL
2. GREEN: 写最少代码 → 运行 → 确认 PASS
3. REFACTOR: 重构 → 运行 → 仍 PASS
4. 提交：  git commit -m "type: message"
```

### 5.4 提交规范（Conventional Commits）

```
feat:     新功能       例: feat: implement Project CRUD
fix:      Bug 修复     例: fix: project name validation rejects CJK
test:     测试         例: test: add ProjectRepository edge cases
refactor: 重构          例: refactor: extract ProjectValidator
docs:     文档         例: docs: update AGENTS.md
chore:    构建/CI/工具 例: chore: configure ruff import sort
```

### 5.5 提交前检查（pre-push）

```powershell
cd D:\develop\projects\InkFlow-ft\fX-xxx\backend
python -m ruff check src/ tests/unit/ ..\tests\    # lint（src + 单元 + 集成）
python -m mypy src/                                   # ⚠️ 用 python -m mypy（Windows uv trampoline 兼容）
python -m pytest tests/unit/ -q                       # 单元测试
python -m pytest ..\tests\integration\ ..\tests\api\ ..\tests\cli\ -q  # 集成测试
```

### 5.6 创建 PR + 合并

```powershell
# 在 feature worktree 内
gh pr create --title "F<N>: <标题>" --body "Closes #<N>" --label "P0" --base main
# CI 通过后，自行 squash merge
gh pr merge --squash --delete-branch
```

### 5.7 清理

```powershell
cd D:\develop\projects\InkFlow
git branch -d feat/fX-xxx
git worktree remove D:\develop\projects\InkFlow-ft\fX-xxx
Remove-Item -Recurse -Force D:\develop\projects\InkFlow-ft\fX-xxx  # 若残留
```

---

## 6. 编码规范

### 6.1 Python 风格

- 所有文件顶部加 `from __future__ import annotations`
- 使用 `StrEnum`（Python 3.11+），注意 Ruff UP042 规则
- Pydantic v2 风格：`model_config = {"from_attributes": True}`（非 `class Config`）
- 类型注解：`str | None`（非 `Optional[str]`）、`list[Project]`（非 `List[Project]`）
- async/await 贯穿全栈：FastAPI → Service → Repository → SQLAlchemy async
- docstring 用中文，代码用英文

### 6.2 Ruff 规则

```toml
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]
```

- **E/W**: pycodestyle 错误和警告 · **F**: Pyflakes（未使用导入、未定义变量等）· **I**: isort（导入排序，自动修复）· **N**: PEP 8 命名约定 · **UP**: pyupgrade（自动升级到 Python 3.11+ 语法）

### 6.3 Pydantic v2 模式

```python
# ✅ 领域模型（model_config 允许从 ORM 对象构建）
class Project(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    config: ProjectConfig = Field(default_factory=ProjectConfig)

# ✅ 请求 DTO（校验用 @field_validator）；更新 DTO 所有字段可选（str | None = None）
class ProjectCreate(BaseModel):
    name: str
    genre: Genre = Genre.QITA
```

### 6.4 导入排序（isort via Ruff）

```python
# 1. 标准库 → 2. 第三方库 → 3. 项目内（Ruff isort 自动修复）
from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from inkflow.domain.models.project import Genre
from inkflow.core.config import config
```

---

## 7. 测试

### 7.1 测试分层（详见 ADR-018）

```
backend/tests/unit/    ← 纯单元测试（无 I/O，无 DB，最快）
tests/integration/     ← 仓储 + 服务层集成测试（真实 in-memory SQLite）
tests/api/             ← FastAPI HTTP 集成测试（ASGITransport + dependency override）
tests/cli/             ← CLI 集成测试（CliRunner + 临时 SQLite）
tests/e2e/             ← 全栈端到端（Playwright Electron + 真实内核；AI 链路走 ADR-026/028 门禁）
```

- **数据库**：每个测试独立的 `sqlite+aiosqlite:///:memory:`，自动建表/销毁
- **async**：`pytest-asyncio` + `asyncio_mode = "auto"`
- **覆盖率**：CI 门槛后端 98.5% 行 / 95% 分支（ADR-027）；前端 vitest thresholds
- 共享 fixture（db_session / sample_project / override_get_db / isolated_db 等）见 `tests/conftest.py` 与各层 conftest

### 7.2 CLI 测试 isolated_db 模式 ⚠️ 重要

CLI 测试需要同时 patch **源模块** 和 **CLI 模块**（Python import 缓存问题；完整 fixture 见 `tests/cli/conftest.py`）：

```python
import inkflow.core.database as db
monkeypatch.setattr(db, "engine", engine)
monkeypatch.setattr(db, "async_session_factory", factory)
import inkflow.cli.commands.project as cli_mod
monkeypatch.setattr(cli_mod, "async_session_factory", factory)
```

**避免的做法**：
- ❌ `monkeypatch.setenv("INKFLOW_DATABASE_URL", ...)` — pydantic-settings 在 import 时已读取
- ❌ `autouse=True` + `sys.modules` 清理 — 会污染其他测试
- ❌ 只 patch `inkflow.core.database` 不 patch `inkflow.cli.commands.project`

### 7.3 serve 冒烟测试

验证 `inkflow serve --no-open` 真正启动了服务器：子进程启动 → 轮询 `/health` 端点 → 确认 200 → 清理（模式见 `tests/cli/test_serve.py`）。

### 7.4 TDD 铁律：每层都要 RED

**所有产出代码的层必须有测试，无一例外。** CLI、API 路由、serve 命令都测。

```markdown
❌ 错误 — CLI 任务只有手动验证
### Task 11: Typer CLI Commands
验证: python -m inkflow project create --name "测试"

✅ 正确 — RED 任务在前
### Task 10.5: Write CLI tests (RED)
### Task 11: Implement CLI (GREEN)
```

---

## 8. 关键文件

AI 编码助手在开始任何工作前，应**按顺序**阅读以下文件：

| 优先级 | 文件 | 说明 |
|--------|------|------|
| P0 | `AGENTS.md` | 本文档，项目总约定 |
| P0 | `adr/README.md` | ADR 索引 + 编号规则；改代码前先查相关决策 |
| P0 | `ARCHITECTURE.md` | 架构导航（目录树 / 组件职责 / 模块类型谱系） |
| P0 | `specs/` | 目标功能 spec（样板见 §5.1） |
| P1 | `design/architecture-analysis-2026-07-30.md` | 架构分析总览（决策详情在 `adr/`） |
| P1 | `design/workflow.md` | git worktree + PR 流程详解 |
| P1 | `backend/pyproject.toml` | 依赖版本、工具配置（Ruff、mypy、pytest） |
| P1 | `tests/conftest.py` | 集成测试共享 fixture（db_session、sample_project） |
| P2 | `design/prd-inkflow-v2.1-2026-07-30.md` | 产品需求文档 |
| P3 | `design/env-readiness-2026-07-30.md` | 环境就绪检查清单 |

---

## 9. 常见陷阱（高频 TOP）

| # | 陷阱 | 解决 |
|---|------|------|
| 1 | **领域层引用了基础设施** | `domain/` 下绝不能出现 `import infrastructure` 或 SQLAlchemy/Starlette |
| 2 | **领域层导入了 LangChain** | `domain/` 下出现 `from langchain` 会触发 CI 失败。用 `domain/ports/` Protocol 替代 |
| 3 | **CLI 测试用环境变量设置 DB** | 用 `monkeypatch.setattr` 直接替换 `engine` 和 `async_session_factory` |
| 11 | **单元 + 集成测试不能放在同一命令** | 两个 `tests/` 目录（backend 和顶层）有命名冲突，必须分开跑 |
| 13 | **Issue/PR 完成后检查配置同步** | 每个 Issue 完成后检查 AGENTS.md、ADR、pyproject.toml、ci.yml、FEATURES.md 是否过时 |

> 完整陷阱清单（UUID.int/跨模块遮蔽/CI 盲区/Windows 坑/流程治理等）见 `ai-traps.md`。

---

## 10. AI 行为准则（借鉴 LiteLLM，2026-08-03）

### 10.1 Think Before Coding — 不假设，不藏困惑，显式化权衡

- 动手前**陈述你的假设**；不确定就问
- 存在多种解释时**全部呈现**，不要静默选一个
- 有更简单的方案就说出来，**该推回就推回**
- 哪里不清楚就停下，说出困惑点，再问

### 10.2 Simplicity First — 解决问题的最小代码，零投机

- 不做超出要求的功能；不为单次使用做抽象
- 不添加未要求的「灵活性/可配置性」；不为不可能的场景写错误处理
- 200 行能写成 50 行就重写。问自己：「资深工程师会觉得这过度复杂吗？」

### 10.3 测试哲学 — 有意义测试胜过覆盖率数字

- **不写无意义测试**：测试必须能在代码损坏时 FAIL（宁可无信号，不要假信号）
- bug fix 必须防回归：让该 bug 永远不可能再出现而不破坏测试
- **扩展既有测试文件**优于新建（命名 `test_<filename>.py`，与源码对应）；新 feature 才开新文件
- 测试是契约：实现不得改测试（F15 铁律）

### 10.4 抑制必须带理由

- 每个 lint/type 抑制必须命名规则 + 理由：`# noqa: X  # <reason>`、`# mypy: ignore[...]  # <reason>`
- 禁裸 `# type: ignore`（mypy `warn_unused_ignores` 已开启，失效抑制会被检出）

### 10.5 工程惯例

- 组合优于继承；early return 优于深层嵌套；依赖注入优于 monkeypatch（测试时传 mock 依赖，而非 patch 类属性）
- 标准库/SDK 优先，不手搓已有轮子；无官方实现时遵循行业标准
- 无 monster files（>900 行会被 `ci_cd/check_file_length.py` 拦截）；文件/目录结构有意识设计
- 新代码全类型化：避免裸 `Any`（存量 Any 渐进清理中——数量降至零后开启 `disallow_any_explicit` 预算门）；边界用 Pydantic 校验后传类型化变量
- 提交信息与 PR 标题遵循 Conventional Commits（commit-msg 钩子 + CI 双重拦截）
