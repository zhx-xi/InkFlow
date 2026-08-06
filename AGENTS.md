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
| `FEATURES.md` | 功能清单唯一权威（已实现模块全表 + 规划 + 版本映射） |
| `adr/README.md` | ADR 索引（改代码前先查；27 条有效） |
| `CONTRIBUTING.md` | 人类贡献者指南 |

---

## 1. 项目概览

**InkFlow** 是一个 AI 辅助小说创作工具。帮助作者使用 AI 规划大纲、撰写章节、修订文本、审阅质量。

| 维度 | 说明 |
|------|------|
| **团队** | 单人开发 |
| **时间线** | SemVer 版本里程碑（ADR-019 v2）：0.1.0 ✅ → 0.2.0 ✅（F9-F16 已交付）→ 0.3.0 GUI（F19 提前 + F23 SSE 提前）→ 0.3.1 质量加固（#86 LLM 修复 ✅ / #87 状态重构 ✅ / #92 真实 AI CI ✅ / #104 覆盖率 ✅）→ 0.4.0 skills 包+打包 → 0.5.0 MCP+会话+daemon → 0.6.0 导出+搜索 → **1.0.0 = 本地完全可用（CLI+GUI+skills+MCP）** → **2.0.0 = 云端**；对应 PRD W10-W24 周计划（明细见下方里程碑表） |
| **部署模式** | 本地优先（SQLite，免认证）；**2.0.0 云端里程碑**：云存档/异地写作（PostgreSQL + JWT + BYOK，无 CRDT），GUI/CLI 远程模式连接云端 |
| **多界面** | GUI（Electron，React 复用）+ CLI（Typer）+ REST API（FastAPI：本地内核通用通信契约，亦为云端用户 API 同一契约）+ MCP Server（stdio 直连 domain）（+ 云端 Web/Admin 后台） |
| **工作流** | SDD + TDD：先写 spec → 再写测试（RED）→ 写代码（GREEN）→ 重构 |
| **仓库** | `https://github.com/zhx-xi/InkFlow` |

### 里程碑（ADR-019 v2，2026-08-02 产品形态决策重排，Issue #65）

| 版本 | 内容 |
|------|------|
| 0.1.0 ✅ | F1-F8 + 云端 Protocol（Phase 1 Gate 7/7，已交付） |
| 0.2.0 ✅ | F9-F16 创作工具链（F9-F16 ✅ 已交付，PR #56/#57/#58/#63/#64/#72/#74/#75） |
| 0.3.0 | F19 GUI（Electron 壳 + 内核进程化 + React 渲染层）· F23 SSE 流式 ✅（PR #83，已交付）——F19 子任务 A 内核进程化 ✅（PR #85，#77）· 子任务 B Electron 壳 ✅（PR #95，#78）· 子任务 C React 渲染层 ✅（PR #97，#79）· 子任务 D 导航重构+设置页框架 ✅（PR #120/#121，#105）· 子任务 E 模型管理页 ✅（PR #122，#106：ProviderConfig 注册表 + 模型管理页 + 角色绑定只读区 + 顶栏 Select + 自绘窗口按钮，覆盖率 99.27%）· 模型管理修复 ✅（PR #131/#132，#125/#126：addModel rethrow + 部分失败保留草稿 + builtin_key 判重防 seed 复活，2026-08-06）· 子任务 F Agent 模板 ✅（PR #135，#107：AgentTemplate 实体（引用式）+ 角色独立温度链（0.7 哨兵移除）+ 风险确认框 + 新建项目模板下拉，三层测试全绿） |
| 0.3.1 | 质量加固补丁（milestone #9）：#86 LLM 客户端修复 ✅（PR #108：timeout→request_timeout + zhipu 注册 + audit 路由）· #87 LangGraph 状态重构 ✅（PR #110：StateGraph(dict)→TypedDict+reducer，节点增量返回，type: ignore 清零）· #92 真实 AI CI job ✅（PR #111：e2e-ai-backend，label run-ai-tests 触发 + workflow_dispatch 兜底；tests/e2e/ T1+T2，缺 key 永远 skip；⚠️ 真实验证需先配 LLM_API_KEY secret）· #104 覆盖率补全 ✅（PR #114/#115/#116/#117：三层补测至后端 98.90% 行/96.32% 分支、前端 99.11%/92.51%、API 端点 100%、E2E 三页；CI 门槛 98.5/95.0 常态化，口径见 ADR-027） |
| 0.4.0 | skills 包（三通道分发）· F19 打包（exe / 安装包 / 便携 ZIP） |
| 0.5.0 | F20 MCP（stdio 直连 domain）· F24 会话 · F25 daemon |
| 0.6.0 | F21 导出 · F22 全文搜索 |
| 1.0.0 🎉 | **本地完全可用 = CLI + GUI + skills + MCP** + 跨平台 + 文档 + 全量验收 |
| 2.0.0 ☁️ | 云端：F18 云 Web（移出单机）· 用户 API · Admin 后台 · GUI 远程模式 |

### Phase 1 功能（F1-F8，已完成）

F1 项目/书籍 · F2 章节 · F3 写作管道 · F4 Agent 编排 · F5 LLM Provider · F6 上下文 · F7 CLI · F8 CI 分层（详情见 FEATURES.md）

### Phase 2 功能（F9-F16，0.2.0 创作工具链）

| # | 模块 | 说明 | 状态 |
|---|------|------|------|
| F9 | `character_service` | 角色管理（档案/关系图谱/分组 + AI 提取） | ✅ 已完成（PR #56） |
| F10 | `world_service` | 世界观管理（条目/分类汇总 + AI 提取） | ✅ 已完成（PR #57） |
| F11 | `outline_service` | 大纲管理（大纲/情节点/弧线 + AI 生成） | ✅ 已完成（PR #58） |
| F12 | `timeline_service` | 时间线管理（事件/叙事双时间线 + 一致性检查，无 LLM） | ✅ 已完成（PR #63） |
| F13 | `foreshadowing_service` | 伏笔管理（埋设/回收追踪；写作时注入） | ✅ 已完成（PR #64） |
| F14 | `extraction_service` | 统一提取服务（6 种提取类型；增量提取；RAG 落地 ADR-013） | ✅ 已完成（PR #72） |
| F15 | `audit_service` | 一致性审计（角色/时间线/世界/伏笔 4 维度） | ✅ 已完成（PR #74） |
| F16 | `style_service` | 风格检测（风格指纹/AI 痕迹/词汇分析） | ✅ 已完成（PR #75） |

> 模块类型谱系：F9/F10 提取型 → F11 生成型 → F12 确定性检查型（无 LLM）→ F13 状态追踪+F6 注入型（无 LLM，首个自带 F6 数据源替换）→ F14 横切收敛型（门面：收敛 F9-F13 管线 + 增量提取 + RAG 首次落地 ADR-013）→ F15 横切审计型（纯消费者：只读聚合 4 维档案 + 跨模块引用，零跨模块 MODIFY）→ F16 确定性文本分析型（无 LLM 主体 + LLM 深度分析可选 + jieba 增强：文本统计特征计算，StyleReport 瞬态输出，F14 STYLE 槽位注册 handler 接口零变更）→ **F23 传输增强型（零新实体：WritingStreamEvent 判别联合 DTO + service 流式方法 + API SSE 端点 + CLI 默认流式，SSE 一条代码路径两用 ADR-021）**。后续模块实施时先对照对应变体样板（`specs/f14-extraction-service/spec.md` 为横切模板；`specs/f16-style-service/spec.md` 为确定性文本分析模板；`specs/f23-sse-stream/spec.md` 为传输增强模板；F13 另含 F6 集成模式 `specs/f13-foreshadowing-service/spec.md` §5）。

### Phase 3 功能（F18-F25，2026-08-02 形态决策后归属调整）

F18 web_ui（云端 2.0.0）· F19 GUI（0.3.0 GUI / 0.4.0 打包，子任务 A ✅ PR #85 / B ✅ PR #95 / C ✅ PR #97 / D ✅ PR #120/#121 / E ✅ PR #122）· F20 MCP（0.5.0）· F21 导出（0.6.0）· F22 搜索（0.6.0）· F23 SSE ✅（PR #83）· F24 会话（0.5.0）· F25 daemon（0.5.0）

> F17 空置（PRD §6.2 标题残留编号）。F18-F25 版本归属以 ADR-019 v2 为准（PRD §6.3/6.4 原归属已被形态决策重排）。

---

## 2. 技术栈

| 层面 | 技术 | 备注 |
|------|------|------|
| 语言 | Python **3.11+** | 必须 `from __future__ import annotations` |
| Web 框架 | FastAPI ≥ 0.110 + uvicorn[standard] | async 优先 |
| CLI | Typer ≥ 0.12 + Rich ≥ 13.0 | `inkflow` 命令入口 |
| ORM | SQLAlchemy ≥ 2.0 (async) + aiosqlite ≥ 0.20 | SQLite 本地，未来切 PostgreSQL |
| 迁移 | Alembic ≥ 1.13 | |
| 数据验证 | Pydantic ≥ 2.0 + pydantic-settings ≥ 2.0 | `model_config = {"from_attributes": True}` |
| LLM Provider | langchain-core + langchain-community + langchain-openai | ChatOpenAI（custom base_url 兼容多 Provider，ADR-005v2） |
| Agent 编排 | langgraph ≥ 0.2.0 | StateGraph：Phase 1 顺序链，Phase 2 自定义 DAG |
| RAG | langchain-chroma + chromadb + sentence-transformers | 本地向量库 + BGE Embedding |
| Prompt 模板 | ChatPromptTemplate（langchain-core） | YAML 模板 + 变量验证 |
| 追踪 | langsmith ≥ 0.2.0（可选） | 开发/调试用，默认关闭 |
| 加密 | cryptography ≥ 42.0 | API Key AES-256-GCM |
| HTTP | httpx ≥ 0.27 + httpx-sse ≥ 0.4 | |
| 日志 | Loguru ≥ 0.7 | |
| 测试 | pytest ≥ 8.0 + pytest-asyncio + pytest-cov + pytest-rerunfailures | CI 覆盖率门槛：后端 98.5% 行 / 95% 分支（coverage-backend job，口径 ADR-027）、前端 renderer/electron vitest thresholds（99.11%/92.51%） |
| Lint | Ruff ≥ 0.6 | 规则集见 backend/pyproject.toml；行宽 100 |
| 类型检查 | mypy ≥ 1.10 | 严格化配置见 backend/pyproject.toml |
| 构建 | hatchling | `[tool.hatch.build.targets.wheel]` |

---

## 3. 关键路径

| 路径 | 说明 |
|------|------|
| `backend/src/inkflow/` | 源码（core / domain / infrastructure / api / cli / mcp 分层；**完整目录树见 ARCHITECTURE.md §2**） |
| `backend/tests/unit/` | 单元测试（纯后端，无 I/O） |
| `tests/` | 集成 + API + CLI 测试（顶层；conftest.py 共享 fixture） |
| `specs/f<X>-<name>/spec.md` | SDD 规格（每 feature 一个目录，**唯一真相**） |
| `adr/` | ADR 决策记录（索引 `adr/README.md`，27 条有效） |
| `design/` | PRD + 架构分析 + Gate 评审（文件名带日期） |
| `docs/` | 用户使用说明（纯用户文档，README 见 `docs/README.md`） |
| `frontend/` | 前端（pnpm workspace 双包：renderer + electron，0.3.0 F19 起） |
| `ci_cd/` | CI 质量护栏脚本（file_length / noqa_reason） |
| `.github/workflows/ci.yml` | CI（分层触发过滤，PR #82） |
| `D:\develop\projects\InkFlow-ft\<feature>\` | git worktree（每个 feature 一个工作副本，只读主仓） |

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

| ADR | 决策 |
|-----|------|
| [ADR-001](adr/ADR-001.md) | 架构风格：模块化单体 |
| [ADR-002](adr/ADR-002.md) | 分层：Clean/Hexagonal |
| [ADR-003](adr/ADR-003.md) | 数据库：SQLite (async) + Repository |
| [ADR-004](adr/ADR-004.md) | 数据契约：Pydantic v2 全栈 |
| [ADR-005v2](adr/ADR-005v2.md) | LLM Provider：**LangChain ChatOpenAI**（OpenAI 兼容路由） |
| [ADR-006v2](adr/ADR-006v2.md) | Agent 编排：**LangGraph StateGraph**（v2.0） |
| [ADR-013](adr/ADR-013.md) | RAG：**LangChain Chroma + BGE**（Phase 2） |
| [ADR-014](adr/ADR-014.md) | Prompt：**ChatPromptTemplate + YAML**（v2.0） |
| [ADR-016](adr/ADR-016.md) | 日志：Loguru 结构化日志 |
| — | 认证：Phase 1-3 无需认证 |
| — | ID 类型：UUID v4 |
| — | 软删除：is_deleted 标记 + 回收站 |
| [ADR-015](adr/ADR-015.md) | **LangChain 隔离**：Protocol 模式 |
| [ADR-017](adr/ADR-017.md) | **CI 代码质量**：Reviewdog + Ruff |
| [ADR-018](adr/ADR-018.md) | **测试分层**：三层目录 + 按功能并行 CI |
| [ADR-019](adr/ADR-019.md) | **版本里程碑**：SemVer + 1.0.0 = 本地完全可用（v2：+2.0.0 云端） |
| [ADR-020](adr/ADR-020.md) | 单机 GUI：**Electron** + 共享 React 渲染层 |
| [ADR-021](adr/ADR-021.md) | **本地内核进程化**：localhost REST + SSE |
| [ADR-022](adr/ADR-022.md) | **skills 包**：源码单一真相 + 三通道分发 |
| [ADR-023](adr/ADR-023.md) | **MCP Server**：stdio + SDK 直连 domain |
| [ADR-024](adr/ADR-024.md) | **云架构**：双前缀（user/admin）+ owner_id 隔离 + 拆分预留 |
| [ADR-025](adr/ADR-025.md) | **依赖锁定**：uv + uv.lock（Python）+ pnpm-lock.yaml 约定（前端） | 供应链加固：全传递依赖 sha256 锁定；CI `uv sync --frozen` 可复现构建 |

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

- `specs/f1-project-service/spec.md`：F1 项目/书籍管理规格（Phase 1 样板）
- `specs/f2-chapter-service/spec.md`：F2 卷/章节管理规格
- `specs/f9-character-service/spec.md`：F9 角色管理规格（0.2.0 提取型样板）
- `specs/f11-outline-service/spec.md`：F11 大纲管理规格（生成型）
- `specs/f12-timeline-service/spec.md`：F12 时间线管理规格（确定性检查型，最新完整模板）
- `specs/f13-foreshadowing-service/spec.md`：F13 伏笔管理规格（状态追踪 + F6 注入集成型）
- `specs/f14-extraction-service/spec.md`：F14 统一提取服务规格（横切收敛门面 + 增量提取 + RAG 首次落地）
- `specs/f15-audit-service/spec.md`：F15 一致性审计服务规格（横切审计型：只读聚合 + 8 规则引擎 + 零跨模块 MODIFY）
- `specs/f16-style-service/spec.md`：F16 风格检测服务规格（确定性文本分析型：风格指纹 12 项 + AI 痕迹 8 特征 + jieba 词汇增强 + LLM 深度分析可选 + F14 STYLE 槽位落地）
- `specs/f23-sse-stream/spec.md`：F23 SSE 流式输出规格（传输增强型：统一 /stream 端点 + mode 判别联合 + SSE 帧协议 + CLI 默认流式）
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

# 5. 安装开发依赖（依赖锁定见 ADR-025：uv + uv.lock）
cd backend
uv sync --frozen
```

**🔴 依赖锁定约定（ADR-025）**：
- **Python 后端**：`backend/uv.lock` 是唯一真相（锁定全部传递依赖 + sha256）。日常安装/同步一律 `uv sync --frozen`；升级依赖 = 改 pyproject.toml → `uv lock` → 全量测试 → PR 附带 lock 变更。CI 用 `astral-sh/setup-uv@v5` + `uv sync --frozen` + `uv run <cmd>`。**环境创建/重建一律 uv（`uv venv` / `uv sync`），禁止 `python -m venv` / `virtualenv`**——手工 venv 残缺后残留外壳（`.venv-broken-*`）会污染 git status（#123 实测，2026-08-06）。
- **前端（F18/F19 建立时生效）**：必须提交 `pnpm-lock.yaml`（pnpm install 自动生成，锁定全部包 + integrity 哈希）；CI 必须 `pnpm install --frozen-lockfile`（否则 lock 被静默更新 = 没锁）；升级依赖 = 显式 `pnpm update` / 改 package.json 后重新生成 lock，PR 附带 lock 变更。

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
| P0 | `specs/f12-timeline-service/spec.md` | F12 功能规格（0.2.0 最新完整模板：单实体 + 确定性算法） |
| P0 | `specs/f13-foreshadowing-service/spec.md` | F13 功能规格（状态机 + F6 注入集成：event_id 锚点 + ForeshadowingSource 替换） |
| P0 | `specs/f14-extraction-service/spec.md` | F14 功能规格（横切收敛门面：6 类型统一接口 + 增量提取 + RAG 落地） |
| P0 | `specs/f15-audit-service/spec.md` | F15 功能规格（横切审计型：4 维档案只读聚合 + 8 规则引擎 + 零跨模块 MODIFY） |
| P0 | `specs/f16-style-service/spec.md` | F16 功能规格（确定性文本分析型：风格指纹/AI 痕迹/词汇分析 + LLM 深度分析可选 + F14 STYLE 槽位落地） |
| P0 | `specs/f23-sse-stream/spec.md` | F23 功能规格（传输增强型：统一 /stream 端点 + mode 判别联合 + SSE 帧协议 + CLI 默认流式） |
| P1 | `design/architecture-analysis-2026-07-30.md` | 架构分析总览；ADR 索引表（决策详情在 `adr/`） |
| P1 | `design/workflow.md` | git worktree + PR 流程详解 |
| P1 | `backend/pyproject.toml` | 依赖版本、工具配置（Ruff、mypy、pytest） |
| P1 | `tests/conftest.py` | 集成测试共享 fixture（db_session、sample_project） |
| P2 | `design/prd-inkflow-v2.1-2026-07-30.md` | 产品需求文档（想做什么、为什么做） |
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

> 完整陷阱清单（25 条：UUID.int/跨模块遮蔽/CI 盲区/Windows 坑/流程治理）见 `ai-traps.md`。

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

- 组合优于继承；early return 优于深层嵌套
- 依赖注入优于 monkeypatch（测试时传 mock 依赖，而非 patch 类属性）
- 标准库/SDK 优先，不手搓已有轮子；无官方实现时遵循行业标准
- 无 monster files（>900 行会被 `ci_cd/check_file_length.py` 拦截）；文件/目录结构有意识设计
- 新代码全类型化：避免裸 `Any`（存量 Any 渐进清理中——数量降至零后开启 `disallow_any_explicit` 预算门）；边界用 Pydantic 校验后传类型化变量
- 提交信息与 PR 标题遵循 Conventional Commits（commit-msg 钩子 + CI 双重拦截）
