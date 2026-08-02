# InkFlow Constitution — 项目章程

> 版本 2.0 | 基于 ADR-001~025 | 依据 PRD v2.2 | 2026-08-02 结构同步修订（ADR-019 v2 里程碑 + ADR-025 依赖锁定）

---

## 一、项目使命

**Build the best local-first AI-assisted novel writing tool that works for both human authors and AI agents.**

InkFlow 是一个 AI 辅助小说创作工具。它的核心价值在于：让独立创作者从安装到完成第一章 AI 写作 ≤ 30 分钟，同时为 AI Agent（如 Hermes）提供一等公民的 MCP 集成。

---

## 二、核心原则（不可妥协）

### P1: 本地优先，零配置起步
- 默认部署 = SQLite + 免认证 + 单进程
- `pip install inkflow && inkflow serve` 三步骤即可启动
- 云端部署仅在 Phase 4+ 实现，Phase 1-3 仅定义接口

### P2: 业务逻辑与界面解耦
- Domain Service 层不能依赖 FastAPI / Typer / MCP 任何框架
- 同一 Service 被 CLI + REST + MCP 三界面复用
- 新界面只需新增 Presentation 层适配器

### P3: 测试驱动开发（TDD）
- **RED → GREEN → REFACTOR** 三步循环，严格执行
- 先写失败测试 → 验证失败 → 最小实现 → 验证通过 → 重构
- 测试覆盖率目标：Phase 1 ≥ 50%, Phase 2 ≥ 60%, Phase 3 ≥ 70%
- Flaky test = 0 容忍

### P4: 依赖方向单向
```
Presentation → Domain ← Infrastructure
                    ↑ (依赖倒置：Ports/Protocols)
```
- 领域层不能 import FastAPI、Typer、SQLAlchemy
- 基础设施层实现 Domain Ports，不能反向依赖
- 每层只依赖其直接下层或 Ports 接口

### P5: YAGNI — 等到第三次再抽象
- Rule of Three：第一次写具体实现，第二次复制，第三次抽象
- 不为"将来可能需要"写代码
- Protocol 接口定义是例外——Phase 1 定义是为了云端迁移路线图

### P6: 模块化单体，接口隔离
- 单进程部署，模块间通过 Protocol 通信
- 不做微服务（单人开发，运维负担不匹配）
- 架构适应度函数防止模块间循环依赖

---

## 三、技术约束

| 约束 | 内容 |
|------|------|
| **语言** | Python 3.11+ |
| **Web 框架** | FastAPI (async) |
| **CLI 框架** | Typer |
| **ORM** | SQLAlchemy 2.0 async |
| **本地数据库** | SQLite + aiosqlite（2.0.0 云端 PostgreSQL + pgvector） |
| **数据验证** | Pydantic v2 |
| **LLM 集成** | LangChain ChatLiteLLM（ADR-005v2，底层 litellm 覆盖 100+ Provider） |
| **Agent 编排** | LangGraph StateGraph（ADR-006v2） |
| **RAG** | langchain-chroma + chromadb + BGE（ADR-013，F14 落地） |
| **Prompt 模板** | ChatPromptTemplate + YAML（ADR-014，模板在 infrastructure/llm/templates/） |
| **测试** | pytest + pytest-asyncio + pytest-cov |
| **Lint** | ruff |
| **类型检查** | mypy |
| **包管理** | uv + uv.lock 锁定（ADR-025，CI `uv sync --frozen`）；前端 pnpm + pnpm-lock.yaml |
| **代码风格** | 行宽 100，UTF-8，中文注释 |

---

## 四、代码质量标准

### 4.1 命名规范
- **模块/文件**：`snake_case`（如 `chapter_service.py`）
- **类名**：`PascalCase`（如 `ChapterService`）
- **函数/方法**：`snake_case`（如 `create_chapter`）
- **常量**：`UPPER_SNAKE_CASE`（如 `MAX_RETRIES`）
- **私有成员**：前缀 `_`（如 `self._repo`）

### 4.2 文档字符串
- 每个公开类和方法必须有中文 docstring
- 使用 Google 风格（Args / Returns / Raises）
- 私有方法可写简短注释

### 4.3 类型注解
- 所有公开函数/方法必须有完整类型注解
- 使用 `from __future__ import annotations` 启用延迟求值
- 可选类型使用 `X | None`（PEP 604），不用 `Optional[X]`

### 4.4 提交规范
```
feat: 新功能
fix: 缺陷修复
test: 添加/修改测试
refactor: 重构（不改变行为）
docs: 文档
chore: 构建/工具/依赖
```

---

## 五、测试规范

### 5.1 测试金字塔
```
        ┌──────┐
        │ E2E  │  ≤ 5（Phase 1）
        ├──────┤
        │ API  │  关键端点集成测试
        ├──────┤
        │Service│ 业务逻辑（Mock 依赖）
        ├──────┤
        │ Unit  │  领域模型验证、工具函数
        └──────┘
```

### 5.2 TDD 三步法
1. **RED**：写一个失败的测试，验证它确实因正确原因失败
2. **GREEN**：写刚好让测试通过的最少代码
3. **REFACTOR**：消除重复、改善设计，保持测试绿色

### 5.3 测试文件结构（三层目录，ADR-018）
```
backend/tests/unit/       # 纯单元测试（无 I/O、无 DB）
tests/integration/        # 仓储 + 服务层集成测试
tests/api/                # FastAPI HTTP 集成测试
tests/cli/                # CLI 端到端测试（新增文件须加入 ci.yml integration-cli-backend job）
tests/e2e/                # 全栈端到端（未来，前端接入后启用）
frontend/src/__tests__/   # 前端单元测试（未来，0.3.0 GUI 后）
```

### 5.4 Fixture 规范
- 数据库测试使用 `sqlite+aiosqlite:///:memory:`
- 每个测试函数独立 session（function scope）
- `sample_*` fixture 提供预构建的测试数据

---

## 六、SDD 工作流

```
Constitution → Specify → Clarify → Plan → Tasks → Implement
     ↑_____________ 所有步骤追溯回 Constitution _____________↓
```

### 6.1 规格文件结构
```
specs/
└── {feature-name}/
    ├── spec.md    # 什么（What）— 功能规格
    └── plan.md    # 如何（How）— 实施计划
```

### 6.2 Spec 必须包含
- 概述（1-2 句）
- 数据模型（实体、字段、关系）
- API 契约（方法、路径、请求/响应）
- CLI 命令签名
- 边界情况与错误处理
- 测试策略（至少 3 个关键测试场景）
- 不在范围内（Out of Scope）

### 6.3 Plan 必须包含
- 架构概述
- 文件清单（新建/修改）
- 逐任务分解（每个 2-5 分钟）
- 每个任务包含完整 RED→GREEN→REFACTOR 三步
- 验证命令与预期结果

---

## 七、治理

### 7.1 修订流程
1. 提出修订 PR，附带理由
2. 引用受影响的 ADR
3. 团队（或单人自我审查）确认无冲突

### 7.2 版本策略
- MAJOR：原则删除或重新定义
- MINOR：新原则或约束添加
- PATCH：措辞澄清、格式修正

### 7.3 合规检查
- 每个 PR 必须通过 ruff + mypy + pytest
- 架构适应度函数检查依赖方向（CI 强制执行）
- 所有 ADR 保持最新

---

*本 Constitution 是 InkFlow 所有架构决策和技术选择的最高依据。所有 Spec、Plan、ADR 必须与此保持一致。*
