# InkFlow AI 编码常见陷阱

> 完整清单（AGENTS.md §9 引用）。**动手前快速扫一遍**；高频陷阱已内联到 AGENTS.md。
> 陷阱以「实现时踩过」为准，新陷阱随实战追加。

## 架构层

| # | 陷阱 | 解决 |
|---|------|------|
| 1 | **领域层引用了基础设施** | `domain/` 下绝不能出现 `import infrastructure` 或 SQLAlchemy/Starlette |
| 2 | **领域层导入了 LangChain** | `domain/` 下出现 `from langchain` 会触发 CI 失败。用 `domain/ports/` Protocol 替代（ADR-015） |
| 9 | **Protocol 中直接使用 LangChain 类型** | `domain/ports/` 的 Protocol 只能用 Python 标准类型 + 自定义 dataclass |
| 16 | **跨模块同名错误类遮蔽** | 每模块 errors 文件可定义通用名类，但 `ports/__init__.py` 导出**仅限本模块独有类名**（如 ForeshadowingNotFoundError）；通用名类（ProjectNotFoundError）从 F9 既有导出复用 |
| 17 | **跨模块硬依赖的集成文件修改** | 只改目标类（如 sources.py 的 ForeshadowingSource），不碰其他数据源类；deps.py 装配走依赖注入 |

## 数据与 ORM

| # | 陷阱 | 解决 |
|---|------|------|
| 7 | **ORM 转换函数放错层** | `infrastructure/database/models/` 只放纯映射；`_orm_to_domain`/`_domain_to_orm` 必须在 repositories 层（否则 ruff F821/UP037） |
| 8 | **软删除后 get() 仍返回数据** | Repository.get() 必须过滤 `is_deleted=False` |
| 18 | **UUID.int 128 位 vs SQLite INTEGER 64 位** | 跨实体引用（project_id/event_id 等 FK 值）必须用**持久化返回对象的 id**（小整数映射 UUID），不是调用方随机 uuid4()——否则 OverflowError |
| 19 | **冒烟负例的前置条件** | 测「跨项目事件 422」必须**先建第二个存在项目**再用其 id；负例要命中目标校验分支，前置校验必须已通过 |

## 测试

| # | 陷阱 | 解决 |
|---|------|------|
| 3 | **CLI 测试用环境变量设置 DB** | 用 `monkeypatch.setattr` 直接替换 `engine` 和 `async_session_factory`（pydantic-settings import 时已读取 env） |
| 6 | **patch 只设源模块不设 CLI 模块** | Python `from X import Y` 在 import 时绑定，CLI 模块需要单独 patch |
| 11 | **单元 + 集成测试不能放在同一命令** | 两个 `tests/` 目录（backend 和顶层）有命名冲突，必须分开跑 |
| 13 | **新增测试文件 ≠ CI 会跑它** | `backend/tests/` 根目录的 CLI 测试是 CI 盲区；新 CLI 测试文件必须手动加入 ci.yml `integration-cli-backend` job |
| 14 | **CLI help 断言在 CI 彩色环境失败** | Typer/Rich FORCE_COLOR 把 `--count` 渲染成 `-count`；用 `CliRunner(env={"NO_COLOR": "1"})` |
| 15 | **PowerShell 不展开 glob** | pytest 收到字面 `test_*.py` 报 no tests ran；CI 必须显式文件列表（ruff 自己支持 glob 可保留） |

## Windows / 工具链

| # | 陷阱 | 解决 |
|---|------|------|
| 4 | **裸 `mypy` 命令在 Windows 上失败** | 使用 `python -m mypy`（uv trampoline 兼容）；`uv run mypy` 亦可 |
| 5 | **Ruff UP042 报 StrEnum** | Python 3.11 native `StrEnum`，确保 `target-version = "py311"` |
| 10 | **LangChain 版本升级破坏兼容** | `uv lock` 时 pyproject.toml 的 `<2.0.0` 上限保护；手动升级需显式 `uv lock` 重新解析 + 跑全量测试 |
| 12 | **CI job 名带 `-backend` 后缀** | 前端接入后会有 `-frontend` 后缀，新增 job 时注意命名约定 |
| 20 | **pre-commit ruff 版本漂移** | 本地 venv 可能更新到 0.16+，与 `.pre-commit-config.yaml` 钉住版本漂移 → commit 前先 `git add -A` 再 commit，或 `pre-commit run ruff-format --files` 预修 |
| 21 | **后台 serve 污染测试** | 跑测试前先杀 `inkflow serve`（否则污染 tests/unit/test_log.py） |
| 22 | **hermes 终端 `&` 调用运算符误判** | 命令以 `& "path"` 开头会被 Hermes 终端误判为后台；写完整路径裸命令 |
| 23 | **PowerShell 输出管道 BOM 污染** | `curl | python -c` 管道注入 UTF-8 BOM；先 `-o` 落文件再读，或走 gh api |

## 流程与治理

| # | 陷阱 | 解决 |
|---|------|------|
| 13 | **Issue/PR 完成后配置同步** | 每个 Issue/PR 完成后检查 AGENTS.md、ADR、pyproject.toml、ci.yml、FEATURES.md 是否过时（#23 教训）；PR 模板已固化该检查 |
| 24 | **main 分支被直接修改** | 禁止；一切变更走 worktree + PR（docs-only 也走 PR） |
| 25 | **AGENTS.md 超过 20K 字符** | Hermes 上下文文件 head+tail 截断丢中间；新内容写 ARCHITECTURE.md / docs/ 而非塞入 AGENTS.md |
