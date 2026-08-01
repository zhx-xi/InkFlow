# AGENTS.md — AI 编码助手说明书

> **给 AI 的一句话**：这是一个单人开发的 Python 后端项目，使用 Clean Architecture（模块化单体），
> 严格遵循 SDD（Spec-Driven Development）+ TDD，所有代码必须在 `backend/` 目录下工作。
> 动手写代码之前，先读 `specs/` 中的 spec 和 `design/` 中的架构分析。

---

## 1. 项目概览

**InkFlow** 是一个 AI 辅助小说创作工具。帮助作者使用 AI 规划大纲、撰写章节、修订文本、审阅质量。

| 维度 | 说明 |
|------|------|
| **团队** | 单人开发 |
| **时间线** | SemVer 版本里程碑（ADR-019）：0.1.0 ✅ → 0.2.0~0.6.0 → **1.0.0 = 本地完全可用**（后端+CLI+UI）；对应 PRD W10-W24 周计划 |
| **部署模式** | 本地优先（SQLite，免认证），Phase 4+ 迁移云端 |
| **三界面** | CLI（Typer）+ REST API（FastAPI）+ 未来 MCP Server |
| **工作流** | SDD + TDD：先写 spec → 再写测试（RED）→ 写代码（GREEN）→ 重构 |
| **仓库** | `https://github.com/zhx-xi/InkFlow` |

### Phase 1 功能（F1-F8，已完成）

| # | 模块 | 说明 |
|---|------|------|
| F1 | `project_service` | 项目/书籍管理（CRUD + 软删除 + 回收站） |
| F2 | `chapter_service` | 卷/章节管理（层级、状态流转） |
| F3 | `writing_service` | AI 写作管道（生成→修订→审阅） |
| F4 | `agent_service` | Agent 编排（架构师/写手/审阅/修订角色链） |
| F5 | `llm_service` | LLM Provider 适配（OpenAI/DeepSeek/...） |
| F6 | `context_service` | 上下文管理（角色/世界观/伏笔/时间线） |
| F7 | `cli_interface` | CLI 命令行接口（`inkflow` 命令） |

---

## 2. 技术栈

| 层面 | 技术 | 备注 |
|------|------|------|
| 语言 | Python **3.11+** | 必须用 `from __future__ import annotations` |
| Web 框架 | FastAPI ≥ 0.110 + uvicorn[standard] | async 优先 |
| CLI | Typer ≥ 0.12 + Rich ≥ 13.0 | `inkflow` 命令入口 |
| ORM | SQLAlchemy ≥ 2.0 (async) + aiosqlite ≥ 0.20 | **SQLite 本地**，未来切 PostgreSQL |
| 迁移 | Alembic ≥ 1.13 | |
| 数据验证 | Pydantic ≥ 2.0 + pydantic-settings ≥ 2.0 | `model_config = {"from_attributes": True}` |
| LLM Provider | langchain-core + langchain-community + langchain-openai | **ChatLiteLLM** 封装（底层 litellm，覆盖 100+ Provider） |
| Agent 编排 | langgraph ≥ 0.2.0 | **StateGraph** — Phase 1 顺序链，Phase 2 用户自定义 DAG |
| RAG | langchain-chroma + chromadb + sentence-transformers | 本地向量库 + BGE Embedding（Phase 2） |
| Prompt 模板 | ChatPromptTemplate（langchain-core） | YAML 模板文件 + 变量验证 |
| 追踪 | langsmith ≥ 0.2.0（可选） | LangSmith 追踪（开发/调试用，默认关闭） |
| 加密 | cryptography ≥ 42.0 | API Key AES-256-GCM 加密 |
| HTTP | httpx ≥ 0.27 + httpx-sse ≥ 0.4 | |
| 日志 | Loguru ≥ 0.7 | |
| 测试 | pytest ≥ 8.0 + pytest-asyncio + pytest-cov | 覆盖率目标 ≥ 70% |
| Lint | Ruff ≥ 0.6 | 规则：E, F, I, N, W, UP；行宽 100 |
| 类型检查 | mypy ≥ 1.10 | `ignore_missing_imports = true` |
| 构建 | hatchling | `[tool.hatch.build.targets.wheel]` |

---

## 3. 目录结构

```
D:\develop\projects\
├── InkFlow\                         # 主仓库（main 分支，只读）
│   ├── AGENTS.md                    # ← 本文件
│   ├── README.md
│   ├── backend\
│   │   ├── pyproject.toml           # 项目配置、依赖、工具设置
│   │   ├── src\inkflow\             # ★ 源码
│   │   │   ├── __main__.py          # CLI 入口
│   │   │   ├── core\                # 配置、数据库连接、日志（基础设施配置）
│   │   │   │   ├── config.py        #   InkFlowConfig (pydantic-settings)
│   │   │   │   ├── database.py      #   async engine + session factory
│   │   │   │   └── log.py           #   Loguru 配置
│   │   │   ├── domain\              # ★ 领域层（核心，不依赖任何框架）
│   │   │   │   ├── models\          #   聚合/实体/值对象 (Project, Chapter, ...)
│   │   │   │   ├── services\        #   领域服务（业务编排）
│   │   │   │   └── ports\           #   出站端口 (Protocol 定义)
│   │   │   ├── infrastructure\      # 基础设施层（实现 domain/ports）
│   │   │   │   └── database\
│   │   │   │       ├── models\      #   SQLAlchemy ORM 模型
│   │   │   │       └── repositories\ #   仓储实现
│   │   │   ├── api\                 # ★ 表现层：REST API
│   │   │   │   ├── app.py           #   FastAPI 应用工厂
│   │   │   │   ├── deps.py          #   依赖注入
│   │   │   │   └── routers\         #   路由 (project, chapter, ...)
│   │   │   └── cli\                 # ★ 表现层：CLI
│   │   │       └── commands\        #   命令实现 (project, chapter, ...)
│   │   └── tests\                   # ★ 单元测试（纯后端，无 I/O）
│   │       └── unit\                #   纯函数 + Mock + DTO 校验
│   │           ├── conftest.py       #   最小化 fixture（event_loop + temp_keys_dir）
│   │           ├── test_chapter_dtos.py
│   │           ├── test_project_dtos.py
│   │           ├── test_writing_models.py
│   │           ├── test_writing_service.py
│   │           ├── test_format_validator.py
│   │           ├── test_key_manager.py
│   │           ├── test_prompt_manager.py
│   │           ├── test_llm_client.py
│   │           ├── test_agent_service.py
│   │           ├── test_agent_templates.py
│   │           └── test_langgraph_pipeline.py
│   ├── tests\                        # ★ 集成 + E2E 测试（顶层，跨后端/前端）
│   │   ├── conftest.py               #   共享 DB fixture（db_session, sample_project, ...）
│   │   ├── integration\              #   仓储 + 服务层集成测试
│   │   │   ├── test_chapter_repository.py
│   │   │   ├── test_chapter_service.py
│   │   │   ├── test_project_repository.py
│   │   │   ├── test_project_service.py
│   │   │   └── test_agent_pipeline.py
│   │   ├── api\                      #   FastAPI HTTP 集成测试
│   │   │   ├── conftest.py           #   override_get_db fixture
│   │   │   ├── test_health.py
│   │   │   ├── test_chapter_api.py
│   │   │   ├── test_project_api.py
│   │   │   ├── test_writing_api.py
│   │   │   └── test_agent_api.py
│   │   ├── cli\                      #   CLI 集成测试
│   │   │   ├── conftest.py           #   isolated_db + _parse_json_output
│   │   │   ├── test_cli_project.py
│   │   │   ├── test_cli_chapter.py
│   │   │   ├── test_cli_writing.py
│   │   │   └── test_cli_agent.py
│   │   └── e2e\                      #   全栈端到端（未来）
│   ├── specs\                       # SDD 规格文件（每个 feature 一个目录）
│   │   ├── f1-project-service\
│   │   │   └── spec.md              # F1 项目/书籍管理规格
│   │   └── f2-chapter-service\
│   │       └── spec.md              # F2 卷/章节管理规格
│   ├── docs\                        # 架构/产品文档
│   │   ├── adr\                     # ★ ADR 决策记录（索引见 adr/README.md）
│   │   │   ├── README.md            #   ADR 索引 + 编号规则
│   │   │   └── ADR-NNN.md           #   单个决策记录（Nygard 格式）
│   │   ├── architecture-analysis-2026-07-30.md
│   │   ├── prd-inkflow-v2.1-2026-07-30.md
│   │   └── workflow.md              # 开发工作流详解
│   └── .github\                     # CI 配置
│       └── workflows\
│
└── InkFlow-ft\                      # git worktree 工作目录（并行 feature）
    └── f1-project-model\            # 当前活跃 feature 的工作副本
```

---

## 4. 架构规则

### 4.1 架构风格：模块化单体 (Modular Monolith)

**不是微服务。** 单人开发不需要分布式复杂度。但模块之间通过 **Protocol**（接口）严格隔离，
为将来按需拆分做准备。

```
表现层 (API/CLI/MCP)  →  应用层  →  领域层 (Service + Model + Port)
                                       ↑
                                 基础设施层 (实现 Port)
```

### 4.2 依赖方向（不可违反）

```
✅ 正确：API/CLI → Domain Service → Port (Protocol) ← Infrastructure (实现)
✅ 正确：所有层都可以依赖 domain/models（纯数据对象）
✅ 正确：infrastructure/ 可以导入 langchain_* 包

❌ 禁止：domain/ 导入 FastAPI、Typer、SQLAlchemy、LangChain、任何框架
❌ 禁止：domain/ 导入 infrastructure/
❌ 禁止：domain 层出现 "from langchain" 或 "import langchain"
❌ 禁止：两个 domain service 互相循环导入
❌ 禁止：domain/ 导入 api/ 或 cli/
```

**🔴 LangChain 隔离规则（CI 强制检查）**：

```bash
# domain 层不允许任何 LangChain import
grep -r "from langchain" src/inkflow/domain/ && echo "VIOLATION: domain layer must not import LangChain" && exit 1
grep -r "import langchain" src/inkflow/domain/ && echo "VIOLATION: domain layer must not import LangChain" && exit 1
```

如果 domain 层需要 LLM/Agent/RAG 能力，通过 `domain/ports/` 中的 Protocol 定义接口，infrastructure 层用 LangChain 实现。

### 4.3 Protocol 契约

领域层通过 `typing.Protocol` 定义出站端口，基础设施层实现：

```python
# domain/ports/project_repository.py
class ProjectRepositoryProtocol(Protocol):
    async def add(self, project: Project) -> Project: ...
    async def get(self, project_id: int) -> Project | None: ...
    # ...

# infrastructure/database/repositories/project_repo.py
class ProjectRepository:  # 实现 Protocol，无需显式继承
    async def add(self, project: Project) -> Project: ...
```

### 4.4 关键设计决策

| ADR | 决策 | 理由 |
|-----|------|------|
| [ADR-001](adr/ADR-001.md) | 架构风格：模块化单体 | 单人团队，避免微服务运维负担；接口隔离保未来拆分 |
| [ADR-002](adr/ADR-002.md) | 分层：Clean/Hexagonal | 三界面共享 Service；依赖方向指向 Domain |
| [ADR-003](adr/ADR-003.md) | 数据库：SQLite (async) + Repository | 本地优先，零配置；Repository 隔离，未来切 PostgreSQL |
| [ADR-004](adr/ADR-004.md) | 数据契约：Pydantic v2 全栈 | 一份模型三界面复用；类型安全 |
| [ADR-005v2](adr/ADR-005v2.md) | LLM Provider：**LangChain ChatLiteLLM**（v2.0） | 保留 100+ Provider 覆盖 + 获得 LangChain callback/LangSmith/LCEL 生态 |
| [ADR-006v2](adr/ADR-006v2.md) | Agent 编排：**LangGraph StateGraph**（v2.0） | Phase 1 顺序链、Phase 2 DAG；LangSmith 可视化；内置 checkpointing |
| [ADR-013](adr/ADR-013.md) | RAG：**LangChain Chroma + BGE**（Phase 2） | 本地向量库 + 中文 SOTA Embedding；长篇小说一致性保障 |
| [ADR-014](adr/ADR-014.md) | Prompt：**ChatPromptTemplate + YAML**（v2.0） | 模板与代码分离；变量验证；非技术人员可编辑 |
| [ADR-016](adr/ADR-016.md) | 日志：Loguru 结构化日志 | 双出口（stderr + 文件）、rotation/retention 内置 |
| — | 认证：Phase 1-3 无需认证 | 本地运行，免认证；Phase 4+ 通过 AuthProtocol 扩展 |
| — | ID 类型：UUID v4 | 避免自增 ID 碰撞，支持未来分布式场景 |
| — | 软删除：is_deleted 标记 + 回收站 | Phase 1 保险策略，用户可恢复误删数据 |
| [ADR-015](adr/ADR-015.md) | **LangChain 隔离**：Protocol 模式 | Domain 零 LangChain 依赖 → 框架可替换性；CI 强制检查 |
| [ADR-017](adr/ADR-017.md) | **CI 代码质量**：Reviewdog + Ruff | PR 内联注解；一次执行双重用途 |
| [ADR-018](adr/ADR-018.md) | **测试分层**：三层目录 + 按功能并行 CI | 单元/集成/API/CLI/E2E 分离；backend 后缀预留前端 |

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

**动手写代码前必须阅读对应的 spec 文件。**

- `specs/f1-project-service/spec.md`：F1 项目/书籍管理规格
- `specs/f2-chapter-service/spec.md`：F2 卷/章节管理规格
- 每个模块 spec 定义了：数据模型、API 契约、CLI 命令、边界情况、测试策略
- spec 是开发的唯一真相来源。如果发现 spec 与实现矛盾，先更新 spec，再改代码

### 5.2 开始新功能

```powershell
# 1. 切换到主仓库
cd D:\develop\projects\InkFlow

# 2. 确保 main 最新
git checkout main && git pull origin main

# 3. 创建 feature 分支 + worktree
git branch feat/fX-xxx main
git worktree add D:\develop\projects\InkFlow-ft\fX-xxx feat/fX-xxx
git push origin feat/fX-xxx

# 4. 在 worktree 中工作
cd D:\develop\projects\InkFlow-ft\fX-xxx

# 5. 安装开发依赖
cd backend
pip install -e ".[dev]"
```

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
python -m ruff check src/ tests/unit/ ..\\tests\\    # lint（覆盖 src + 单元 + 集成）
python -m mypy src/                                   # 类型检查
python -m pytest tests/unit/ -q                       # 单元测试（裸 pytest = 仅单元）
python -m pytest ..\\tests\\integration\\ ..\\tests\\api\\ ..\\tests\\cli\\ -q  # 集成测试
```

**注意：** 使用 `python -m mypy` 而非裸 `mypy`（Windows uv trampoline 兼容性问题）。

### 5.6 创建 PR + 合并

```powershell
# 在 feature worktree 内
gh pr create \
  --title "F<N>: <标题>" \
  --body "Closes #<N>" \
  --label "P0" \
  --base main

# CI 通过后，自行 squash merge
gh pr merge --squash --delete-branch
```

### 5.7 清理

```powershell
cd D:\develop\projects\InkFlow
git branch -d feat/fX-xxx
git worktree remove D:\develop\projects\InkFlow-ft\fX-xxx
Remove-Item -Recurse -Force D:\develop\projects\InkFlow-ft\fX-xxx
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

- **E/W**: pycodestyle 错误和警告
- **F**: Pyflakes（未使用导入、未定义变量等）
- **I**: isort（导入排序，自动修复）
- **N**: PEP 8 命名约定
- **UP**: pyupgrade（自动升级到 Python 3.11+ 语法）

### 6.3 Pydantic v2 模式

```python
# ✅ 领域模型
class Project(BaseModel):
    model_config = {"from_attributes": True}  # 允许从 ORM 对象构建
    id: uuid.UUID
    name: str
    config: ProjectConfig = Field(default_factory=ProjectConfig)

# ✅ 请求 DTO
class ProjectCreate(BaseModel):
    name: str
    genre: Genre = Genre.QITA

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str: ...

# ✅ 更新 DTO（所有字段可选）
class ProjectUpdate(BaseModel):
    name: str | None = None
```

### 6.4 导入排序（isort via Ruff）

```python
# 1. 标准库
from __future__ import annotations
import uuid
from datetime import datetime

# 2. 第三方库
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

# 3. 项目内
from inkflow.domain.models.project import Genre
from inkflow.core.config import config
```

---

## 7. 测试

### 7.1 测试分层（详见 ADR-018）

```
backend/tests/unit/          ← 纯单元测试（无 I/O，无 DB，最快）
tests/integration/            ← 仓储 + 服务层集成测试（真实 in-memory SQLite）
tests/api/                    ← FastAPI HTTP 集成测试（ASGITransport + dependency override）
tests/cli/                    ← CLI 集成测试（CliRunner + 临时 SQLite）
tests/e2e/                    ← 全栈端到端（未来，前端接入后启用）
```

### 7.2 关键 fixture

| fixture | 位置 | 说明 |
|---------|------|------|
| `event_loop` | `backend/tests/unit/conftest.py` | session-scoped async event loop |
| `temp_keys_dir` | `backend/tests/unit/conftest.py` | 临时密钥存储目录 |
| `db_session` | `tests/conftest.py` | function-scoped in-memory SQLite session |
| `sample_project` | `tests/conftest.py` | 预创建的 ProjectORM 实例 |
| `override_get_db` | `tests/api/conftest.py` | FastAPI dependency override → 测试 DB |
| `isolated_db` | `tests/cli/conftest.py` | 独立临时 SQLite + monkeypatch |

- **数据库**：每个测试独立的 `sqlite+aiosqlite:///:memory:`，自动建表/销毁
- **async**：`pytest-asyncio` + `asyncio_mode = "auto"`
- **覆盖率**：`pytest-cov`，目标 ≥ 70%

### 7.3 CLI 测试 isolated_db 模式 ⚠️ 重要

CLI 测试需要同时 patch **源模块** 和 **CLI 模块**（Python import 缓存问题）：

```python
@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # ★ 必须 patch 两个模块
    import inkflow.core.database as db
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "async_session_factory", factory)

    import inkflow.cli.commands.project as cli_mod
    monkeypatch.setattr(cli_mod, "async_session_factory", factory)
    yield
```

**避免的做法**：
- ❌ `monkeypatch.setenv("INKFLOW_DATABASE_URL", ...)` — pydantic-settings 在 import 时已读取
- ❌ `autouse=True` + `sys.modules` 清理 — 会污染其他测试
- ❌ 只 patch `inkflow.core.database` 不 patch `inkflow.cli.commands.project`

### 7.4 serve 冒烟测试

验证 `inkflow serve --no-open` 真正启动了服务器：

```python
# 子进程启动 → 轮询 /health 端点 → 确认 200 → 清理
proc = subprocess.Popen(
    [sys.executable, "-m", "inkflow", "serve", "--no-open", "--port", "18765"],
    env=env, ...
)
for _ in range(20):
    time.sleep(0.3)
    conn = http.client.HTTPConnection("127.0.0.1", 18765, timeout=2)
    conn.request("GET", "/health")
    if conn.getresponse().status == 200: return
pytest.fail("server did not start")
```

### 7.5 TDD 铁律：每层都要 RED

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
| P0 | `specs/f1-project-service/spec.md` | F1 功能规格（数据模型、API、CLI、边界条件） |
| P0 | `specs/f2-chapter-service/spec.md` | F2 功能规格（卷/章节、状态流转） |
| P1 | `design/architecture-analysis-2026-07-30.md` | 架构分析总览；ADR 索引表（决策详情在 `adr/`） |
| P1 | `design/workflow.md` | git worktree + PR 流程详解 |
| P1 | `backend/pyproject.toml` | 依赖版本、工具配置（Ruff、mypy、pytest） |
| P1 | `tests/conftest.py` | 集成测试共享 fixture（db_session、sample_project） |
| P2 | `design/prd-inkflow-v2.1-2026-07-30.md` | 产品需求文档（想做什么、为什么做） |
| P3 | `design/env-readiness-2026-07-30.md` | 环境就绪检查清单 |

---

## 9. 常见陷阱

| # | 陷阱 | 解决 |
|---|------|------|
| 1 | **领域层引用了基础设施** | `domain/` 下绝不能出现 `import infrastructure` 或 SQLAlchemy/Starlette |
| 2 | **领域层导入了 LangChain** | `domain/` 下出现 `from langchain` 会触发 CI 失败。用 `domain/ports/` Protocol 替代 |
| 3 | **CLI 测试用环境变量设置 DB** | 用 `monkeypatch.setattr` 直接替换 `engine` 和 `async_session_factory` |
| 4 | **裸 `mypy` 命令在 Windows 上失败** | 使用 `python -m mypy`（uv trampoline 兼容） |
| 5 | **Ruff UP042 报 StrEnum** | Python 3.11 native `StrEnum`，确保 `target-version = "py311"` |
| 6 | **patch 只设源模块不设 CLI 模块** | Python `from X import Y` 在 import 时绑定，CLI 模块需要单独 patch |
| 7 | **忘记 `from __future__ import annotations`** | 所有新文件必须加 |
| 8 | **软删除后 get() 仍返回数据** | Repository.get() 必须过滤 `is_deleted=False` |
| 9 | **Protocol 中直接使用 LangChain 类型** | `domain/ports/` 的 Protocol 只能用 Python 标准类型 + 自定义 dataclass |
| 10 | **LangChain 版本升级破坏兼容** | pip install 时 pyproject.toml 的 `<0.4.0` 上限保护；手动升级需跑全量测试 |
| 11 | **单元 + 集成测试不能放在同一命令** | 两个 `tests/` 目录（backend 和顶层）有命名冲突，必须分开跑 |
| 12 | **CI job 名带 `-backend` 后缀** | 前端接入后会有 `-frontend` 后缀，新增 job 时注意命名约定 |
| 13 | **Issue/PR 完成后检查配置同步** | 每个 Issue 完成后检查 AGENTS.md、ADR、pyproject.toml 等文件是否过时 |
