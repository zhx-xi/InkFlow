# AGENTS.md — AI 编码助手说明书

> **给 AI 的一句话**：单人开发 Python 后端项目，Clean Architecture（模块化单体）+ SDD（Spec-Driven Development）+ TDD；动手写代码前先读 `specs/` 的 spec 与 `design/` 的架构分析。

## 0. 文件体系与权威源（先读）

| 文件 | 角色 |
|------|------|
| `.specify/constitution.md` | **项目章程（最高依据）**：核心原则 P1-P6 + 技术约束 + 代码质量标准 + 测试规范 + SDD 流程 + 治理。⚠️ **不在 AI 自动上下文中，需主动读取** |
| `AGENTS.md`（本文件） | 项目总约定 + AI 行为准则（§10）+ 核心纪律（SDD/TDD/ADR/编码） |
| `ARCHITECTURE.md` | 架构导航：完整目录树、组件职责、模块类型谱系 → 样板 spec、加新模块步骤。**改架构/加模块前先读** |
| `ai-traps.md` | AI 编码常见陷阱完整清单（§9 只留高频 TOP） |
| `FEATURES.md` | 功能清单唯一权威（已实现模块全表 + 规划 + 版本→功能映射） |
| `adr/README.md` | ADR 索引 + 编号规则 + 当前有效决策速览（改代码前先查） |
| `backend/pyproject.toml` | 依赖版本、工具配置（Ruff / mypy / pytest） |
| `docs/evidence/README.md` | **证据归档**：被 ADR/spec/注释引用的历史证据（原 `.hermes/` 散落件） |
| `CONTRIBUTING.md` | 人类贡献者指南 |

本文件只保留**指针 + 无法从代码推导的纪律**；规范细节一律以权威源为准，不在此复制（复制体必然漂移，见 #1190）。Hermes 上下文 first-match-wins 只自动加载本文件，`.specify/constitution.md` 不在自动上下文中，需主动读取。

🔴 **禁止引用 `.hermes/` 与 `.tmp/` 下的路径**（在 ADR / spec / 源码注释 / 测试 docstring / issue body 里）
—— 两者都是 **gitignored 工作区草稿目录**：不随仓库分发、**其他协作者拿不到**、且会被定期清理。

- 需要长期引用的证据 → 放 **`docs/evidence/`** 并在其 README 登记
- 临时契约 / 探针 / 设计稿 → 引用 **GitHub issue（`#NNN`）** 或 **ADR**，不要写本地文件路径
- 由来：此前大量 RED 契约与审计汇总写在 `.hermes/plans/`，清理后全仓留下 **37 处引用、31 处悬空**（详见 `docs/evidence/README.md`）

## 1. 项目概览
**InkFlow** 是一个 AI 辅助小说创作工具。帮助作者使用 AI 规划大纲、撰写章节、修订文本、审阅质量。

> 版本里程碑（0.1.0 → 2.0.0，ADR-019 v12）、功能全表、模块类型谱系 → 见 `FEATURES.md`；架构见 `ARCHITECTURE.md`。

## 2. 技术栈（易错项）
权威源：`constitution §三`（技术约束）+ `backend/pyproject.toml`（依赖与工具配置）。以下 3 条易错事实无法从代码推导：

- Python **3.13+**（ADR-058），所有文件顶部必须 `from __future__ import annotations`
- **Alembic 在依赖中但未启用**（ADR-054 已接受·实施挂下期）——schema 由 `create_all` + 32 个 `ensure_*` 幂等迁移管理
- 覆盖率门禁：后端 **98.5% 行 / 95.0% 分支**（ADR-027）

## 3. 关键路径
完整目录树见 `ARCHITECTURE.md §2`。两条易错事实：`tests/e2e/` 已启用（ADR-028，Playwright Electron + 真实内核）；git worktree 根为 `D:\develop\projects\InkFlow-ft\<feature>\`（每个 feature 一个工作副本，主仓只读）。

## 4. 架构规则
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

### 4.4 关键设计决策
全部技术选型（模块化单体/六边形分层/SQLite/LLM 路由/Agent 编排/RAG/CI 门禁/版本里程碑等）→ **`adr/README.md`「当前有效决策速览」**，改代码前先查相关 ADR。

**🔴 ADR 治理规则（所有 AI 会话必须遵守）**：

1. 动手改代码前，先查 `adr/README.md` 索引确认相关决策
2. 决策变更（技术选型、架构调整）必须**先写/改 ADR，再改代码**，PR 引用 ADR 编号
3. 新增决策：创建 `adr/ADR-NNN.md`（Nygard 格式：状态 / 背景 / 决策 / 备选方案 / 影响），然后在 `README.md` 索引登记
4. 编号顺序递增不复用；决策被取代时旧 ADR 标记 `已弃用` 并指向新 ADR（如 ADR-005 → ADR-005v2）
5. Constitution §7.3：所有 ADR 保持最新；架构分析文档只保留索引表，不维护内嵌副本

### 4.6 GUI 改动必须同步设计双件套（三件同步）

任何改动 `frontend/**/pages/*.tsx` 或 `frontend/**/components/**` 的 **UI 行为/布局**的 PR，
必须**同 PR 同步以下三件**：

1. `design/GUI/<page>/<page>.html` —— 交互原型
2. `design/GUI/<page>/<page>-<state>.png` —— 受影响状态的截图
3. `specs/f19-gui/<page>.md` —— 页交互规格

⚠️ 原型 HTML 是「设计基准」，页规格是「实现的对照面」。**两者都不更新 = 漂移**（#1326 实测 8 页）。
⚠️ PNG 由 `design/GUI/_tools/*.cjs` 截图脚本生成（本地 headless，**非 CI**）
   → **门禁无法自动验证 PNG 内容，只能靠人工自查**。
⚠️ 门禁 `ci_cd/check_gui_spec_sync.py` 只校验「目录/文件对应 + 孤儿」，
   **拦不住「改了没同步」**（那靠本纪律 + PR 自查）。

**判据（自查三问）**：本 PR 是否改了 UI 行为/布局？→ 对应页目录是哪个？→ 三件是否都在本 PR diff 里？

## 5. 开发工作流（SDD + TDD）
整个开发流程为：**Spec → Test (RED) → Code (GREEN) → Refactor → PR → Merge**

### 5.1 SDD：Spec 先行
**动手写代码前必须阅读对应的 spec 文件。** 完整 spec 清单见 `specs/` 目录（F8 无 spec，见 ADR-018）。样板 spec（对照最接近的变体）：`specs/f1-project/spec.md`（格式范例）、`specs/f9-character/spec.md`（提取型）、`specs/f11-outline/spec.md`（生成型）、`specs/f14-extraction/spec.md`（横切收敛门面型）、`specs/f16-style-analysis/spec.md`（确定性文本分析型）、`specs/f23-sse/spec.md`（传输增强型）、`specs/f32-settings/spec.md`（设置域横切型）、`specs/f42-agent-chain/spec.md`（配置驱动编排型）、`specs/f60-first-run-guide/spec.md`（首启门控型）。

- 每个模块 spec 定义了：数据模型、API 契约、CLI 命令、边界情况、测试策略
- **spec 是开发的唯一真相来源**。如果发现 spec 与实现矛盾，先更新 spec，再改代码
- **Spec 篇幅纪律（2026-08-08 #201 立规）**：新 spec 默认单文件 ≤800 行；超过且章节内聚可拆时，允许 `specs/f<X>-<name>/references/` 子目录，但 spec.md 头部必须显式声明 references/ 清单；已实现 spec 只加「快速导航」块

### 5.2 开始新功能
流程细节（git worktree + PR）见 `design/workflow.md`；依赖锁定见 ADR-025（`backend/uv.lock` 唯一真相，日常一律 `uv sync --frozen`）。**环境创建/重建一律 uv，禁止 `python -m venv` / `virtualenv`。**

### 5.3 TDD 循环（RED-GREEN-REFACTOR）
```
1. RED:   写测试 → 运行 → 确认 FAIL
2. GREEN: 写最少代码 → 运行 → 确认 PASS
3. REFACTOR: 重构 → 运行 → 仍 PASS
4. 提交：  git commit -m "type: message"
```

### 5.4 提交规范（Conventional Commits）
规范见 `constitution §四 4.4`；提交信息与 PR 标题由 `.githooks/check_commit_msg.py` 钩子 + CI 双重校验。

### 5.5 提交前检查（pre-push）
```powershell
cd D:\develop\projects\InkFlow-ft\fX-xxx\backend
python -m ruff check --no-cache src/ tests/unit/ ..\tests\    # lint（src + 单元 + 集成）
python -m mypy src/                                           # ⚠️ 用 python -m mypy（Windows uv trampoline 兼容）
python -m pytest tests/unit/ -q                               # 单元测试
python -m pytest ..\tests\integration\ ..\tests\api\ ..\tests\cli\ -q  # 集成测试
```

### 5.6 创建 PR + 合并
流程见 `design/workflow.md`：`gh pr create --base main` → CI 通过后 `gh pr merge --squash --delete-branch`。

### 5.7 清理
流程见 `design/workflow.md`：`git worktree remove` + `git branch -d`。

## 6. 编码规范
### 6.1 Python 风格
规范见 `constitution §四 4.5`（`from __future__ import annotations` / `StrEnum`（Ruff UP042）/ async 全栈 / 中文 docstring）。

### 6.2 Ruff 规则
规则集与行宽见 `backend/pyproject.toml`。格式化标准 = `ruff format`（#1148 起为 CI 硬门禁：
`lint-backend` job 跑 `ruff format --check src/ tests/unit/ ../tests/ ../ci_cd/`）；
pre-commit 钩子版本必须与 CI 实际版本一致（当前钉 v0.16.1，随 uv.lock 升级需同步改
`backend/.pre-commit-config.yaml` 的 `rev`，否则格式结论互逆、钩子会重排 CI 已认可的代码）。

### 6.3 Pydantic v2 模式
规范见 `constitution §四`：`model_config = {"from_attributes": True}`（非 `class Config`）；类型注解用 `str | None` / `list[X]`。

### 6.4 导入排序（isort via Ruff）
Ruff isort 自动修复：标准库 → 第三方库 → 项目内。

## 7. 测试
### 7.1 测试分层（详见 ADR-018）
分层与共享 fixture 见 ADR-018 + `constitution §五` + `tests/conftest.py`；数据库用每测试独立 `sqlite+aiosqlite:///:memory:`，async 用 `pytest-asyncio`（`asyncio_mode = "auto"`）。

### 7.2 CLI 测试 isolated_db 模式 ⚠️ 重要
CLI 测试**必须同时 patch 源模块与 CLI 模块**（Python import 缓存）：`inkflow.core.database` 的 `engine`/`async_session_factory` + `inkflow.cli.commands.<x>.async_session_factory`；完整 fixture 见 `tests/cli/conftest.py`。禁用 `monkeypatch.setenv("INKFLOW_DATABASE_URL", ...)`（pydantic-settings 在 import 时已读取）。

### 7.3 serve 冒烟测试
验证 `inkflow serve --no-open` 真正启动了服务器：子进程启动 → 轮询 `/health` 端点 → 确认 200 → 清理（模式见 `tests/cli/test_cli_serve.py`）。

### 7.4 TDD 铁律：每层都要 RED
**所有产出代码的层必须有测试，无一例外。** CLI、API 路由、serve 命令都测。RED 任务必须排在实现任务之前：
```
❌ 错误 — CLI 任务只有手动验证：Task 11: Implement CLI → 验证: python -m inkflow project create --name "测试"
✅ 正确 — RED 任务在前：Task 10.5: Write CLI tests (RED) → Task 11: Implement CLI (GREEN)
```

## 8. 关键文件
本节内容已并入 §0 权威源表。

## 9. 常见陷阱（高频 TOP）

| # | 陷阱 | 解决 |
|---|------|------|
| 1 | **领域层引用了基础设施** | `domain/` 下绝不能出现 `import infrastructure` 或 SQLAlchemy/Starlette |
| 2 | **领域层导入了 LangChain** | `domain/` 下出现 `from langchain` 会触发 CI 失败。用 `domain/ports/` Protocol 替代 |
| 3 | **CLI 测试用环境变量设置 DB** | 用 `monkeypatch.setattr` 直接替换 `engine` 和 `async_session_factory` |
| 11 | **单元 + 集成测试不能放在同一命令** | 两个 `tests/` 目录（backend 和顶层）有命名冲突，必须分开跑 |
| 13 | **Issue/PR 完成后检查配置同步** | 每个 Issue 完成后检查 AGENTS.md、ADR、pyproject.toml、ci.yml、FEATURES.md 是否过时 |
| 26 | **改契约源 → 硬编码快照断言连锁过期** | 改 `agent/tools/registry.py` 表前必读 `docs/contract-guard.md` 联保清单；CI `contract` filter 命中即跑 `e2e-frontend-settings`（#993/#985） |

> 完整陷阱清单（UUID.int/跨模块遮蔽/CI 盲区/Windows 坑/流程治理等）见 `ai-traps.md`。

## 10. AI 行为准则
### 10.1 Think Before Coding — 不假设，不藏困惑，显式化权衡
- 动手前**陈述你的假设**；不确定就问
- 存在多种解释时**全部呈现**，不要静默选一个
- 有更简单的方案就说出来，**该推回就推回**
- 哪里不清楚就停下，说出困惑点，再问

### 10.2 Simplicity First — 解决问题的最小代码，零投机
- 不做超出要求的功能；不为单次使用做抽象
- 不添加未要求的「灵活性/可配置性」；不为不可能的场景写错误处理
- 200 行能写成 50 行就重写。问自己：「资深工程师会觉得这过度复杂吗？」**不做架构宇航员。**

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

## 11. 发布记录（Release Log）
发布记录见 `CHANGELOG.md` + `FEATURES.md`。
