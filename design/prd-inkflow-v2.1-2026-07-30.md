# InkFlow — AI 辅助小说创作工具 · 产品规格书（v2.1 更新版）

**日期**: 2026-07-30（更新）
**来源**: 基于 v2.0 PRD（InkChain）重命名 + 完善
**项目名称**: InkFlow（原 InkChain）
**项目路径**: `D:\develop\projects\InkFlow`
**远程仓库**: `https://github.com/zhx-xi/InkFlow.git`
**CLI 命令**: `inkflow`
**PyPI 包名**: `inkflow`（待确认可用性）

---

## 📌 TL;DR（执行摘要）

- **核心定位**: 全新 Python 后端 AI 辅助小说创作工具，前后端分离架构（Python FastAPI + React），从零设计每个功能
- **部署策略**: **本地优先** — Phase 1-3 全力实现本地自部署；云端部署只设计接口（Python Protocol/ABC），实现延后至 Phase 4+
- **打包目标**: `pip install` → PyInstaller exe → 安装包 → 桌面端（pywebview），逐步降低用户使用门槛
- **技术选型**: FastAPI + Typer + SQLAlchemy 2.0 async + Pydantic v2 + SQLite（本地）/ PostgreSQL（云端接口预留）
- **Agent 集成**: CLI `--json` + MCP Server（stdio），可被 Hermes 等 AI Agent 调用
- **资源约束**: **单人开发**（非团队），时间线已据此调整，Phase 1-3 约 12-16 周（3-4 个月）
- **SDD 工作流**: GitHub Spec-Kit SDD + TDD，规格驱动开发

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 推荐方案 | 全新 Python FastAPI 后端 + React 前端分离 + 本地优先部署 + MCP Agent 集成 |
| 优先级 | P0（13 项，核心写作引擎）/ P1（16 项，创作工具+UI+打包+Agent）/ P2（云端接口+停车场） |
| 资源约束 | 单人全栈开发（1 FTE），Phase 1-3 约 12-16 周（3-4 个月） |
| 风险等级 | 🟡 中高（单人开发 = Web UI 和 Agent 编排并行工作受限） |
| 打包方案 | pip → PyInstaller exe → Inno Setup 安装包 → pywebview 桌面端（均可行，分阶段实现） |

---

## 1. 产品目标（3 个正交目标）

### 目标 A：从零构建完整的 AI 写作核心能力
- 23 个功能模块覆盖小说创作全流程（项目管理→世界观→角色→大纲→AI写作→审校→导出）
- CLI + Web UI 双界面，满足技术用户和非技术用户
- 多模型路由（BYOK），支持 OpenAI/Anthropic/DeepSeek/Ollama 等
- **成功判据**: 用户从安装到完成第一章 AI 写作 ≤ 30 分钟

### 目标 B：AI Agent 原生集成
- 冷启动 ≤ 500ms（常驻服务模式）
- SSE 流式写作输出
- MCP Server（stdio），≥ 15 个整合工具
- 渐进式工具发现（Progressive Discovery）
- **成功判据**: Hermes 通过 MCP 发现并调用 InkFlow 完成一章创作，全程流式

### 目标 C：工程健康度从第一天就达标
- Bug-to-Feature ≤ 0.5:1
- CI/测试维护提交占比 ≤ 15%
- 单元测试覆盖率 ≥ 70%
- E2E 测试 ≤ 50（精简有效）
- Flaky test = 0
- **成功判据**: 连续 4 周 CI 绿色

---

## 2. 用户故事（5 个场景）

1. **独立创作者从零开始** — 下载安装包 → 双击启动桌面端 → 建书 → 配置 AI 模型 → 写第一章，全程无需命令行或 Python 环境
2. **技术用户 CLI 驱动** — `pip install inkflow` → `inkflow project create` → `inkflow write next --json` → 脚本化批量生成
3. **AI Agent 通过 MCP 调用** — Hermes 发现 InkFlow MCP 工具 → 流式生成章节 → 结构化 JSON 返回 → 自动审校循环
4. **弱模型格式稳定性** — DeepSeek/GLM 生成内容格式不一致时，自动重试 + 格式修复，确保写作管道不中断
5. **后台挂机写作** — 配置 daemon 定时任务 → 自动生成章节 → 审校 → 通知用户审阅

---

## 3. 用户研究洞察（来自瑞思）

### 三类用户画像

| 画像 | 身份 | 核心诉求 | 关键痛点 |
|------|------|---------|---------|
| A — 独立创作者 | 网文作者/同人写手/编剧 | AI 辅助"写→审→修"循环，降低产能瓶颈 | 环境安装门槛、弱模型中断、长篇上下文管理 |
| B — 团队/多用户（Phase 4+） | 3-10 人工作室 | 多人协作管理 IP 世界观 | 当前不支持多用户（云端延后实现） |
| C — AI Agent 调用方 | Hermes/Claude Code 等 | 结构化 JSON I/O、低延迟、流式、工具发现 | 需要常驻服务、MCP 协议、流式输出 |

### 关键洞察
1. **"装好就能用"是第一门槛** — 非技术创作者最大障碍是环境配置
2. **AI Agent 是战略级用户** — Python 重写是引入 MCP/流式/常驻服务的最佳时机
3. **弱模型格式中断是创作流断点** — 需统一格式校验层和自动重试机制
4. **长篇上下文管理是核心挑战** — 需要 protected/compressible/dynamic 分层上下文管理

---

## 4. 竞品对比

| 维度 | InkFlow | NovelWriter (kisscelia) | SillyTavern | Sudowrite | NovelCrafter | Manuskript |
|------|---------|------|------|------|------|------|
| 后端 | Python (FastAPI) | Python (FastAPI) | Node.js | 闭源 | 闭源 | Python (PyQt) |
| 前端 | React (独立 SPA) | Web | Web(非分离) | Web | Web | 桌面单体 |
| 部署 | 本地优先+云端预留 | Docker | 本地自部署 | SaaS | SaaS | 桌面 |
| BYOK | ✅ 多 Provider 路由 | ✅ | ✅ | ✅ Model Router | ✅ 300+ | ❌ |
| CLI/API | ✅ CLI+REST+MCP | ✅ REST | ❌ | ❌ | ✅ API | ❌ |
| AI Agent 集成 | ✅ MCP Server | ❌ | ❌ | ❌ | ❌ | ❌ |
| 桌面端 | ✅ pywebview | ❌ | ❌ | ❌ | ❌ | ✅ PyQt |
| 开源 | ✅ | ✅ | ✅ (28K+) | ❌ | ❌ | ✅ |

**差异化定位**: 本地自部署 + 桌面端体验 + CLI/MCP Agent 调用 + 完整创作工具链 + Python AI 生态原生 — 没有竞品同时实现以上五个维度。

---

## 5. 技术架构设计

### 5.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      客户端层                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ 桌面端    │  │ Web UI   │  │ CLI      │  │ MCP      │    │
│  │ (pywebview)│  │ (React)  │  │ (Typer)  │  │ (Agent)  │    │
│  └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘    │
│        │ HTTP/REST+SSE     │ HTTP        │ stdio       │      │
└────────┼──────────────────┼─────────────┼─────────────┼──────┘
         │                  │             │             │
         ▼                  ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────┐
│                   InkFlow Python 后端                        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              FastAPI Application                     │    │
│  │  REST Router │ SSE Streamer │ MCP Server │ Static   │    │
│  └───────────────────────┬─────────────────────────────┘    │
│                          │                                  │
│  ┌───────────────────────┴─────────────────────────────┐    │
│  │                Service Layer                         │    │
│  │  project │ chapter │ writing │ agent │ llm │ context│    │
│  │  character │ world │ outline │ timeline │ foreshadow│    │
│  │  extraction │ audit │ style │ session │ daemon     │    │
│  │  output │ search │ mcp                           │    │
│  └───────────────────────┬─────────────────────────────┘    │
│                          │                                  │
│  ┌───────────────────────┴─────────────────────────────┐    │
│  │              Interface Layer (Protocols)             │    │
│  │  DatabaseProtocol │ AuthProtocol │ StorageProtocol   │    │
│  │  UserProtocol │ SyncProtocol │ MCPTransport         │    │
│  └───────┬───────────────────────────────┬─────────────┘    │
│          │ Local Implementations          │ Cloud (Phase 4+) │
│          ▼                                ▼                  │
│  ┌──────────────┐                ┌──────────────┐           │
│  │ SQLite       │                │ PostgreSQL   │           │
│  │ LocalTrust   │                │ JWTAuth      │           │
│  │ LocalFile    │                │ CloudStorage │           │
│  │ SingleUser   │                │ MultiTenant  │           │
│  │ stdio MCP    │                │ HTTP MCP     │           │
│  └──────────────┘                └──────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 后端技术栈

| 层 | 技术 | 版本要求 | 当前状态 | 选型理由 |
|----|------|---------|---------|---------|
| Web 框架 | FastAPI | 0.110+ | ✅ 0.136.3 已安装 | 原生异步、自动 OpenAPI 文档 |
| CLI 框架 | Typer | 0.12+ | ❌ 需安装 | 与 FastAPI 共享 Pydantic 模型 |
| ORM | SQLAlchemy 2.0 async | 2.0+ | ❌ 需安装 | 双数据库支持、异步 |
| 本地 DB | SQLite + aiosqlite | — | ❌ 需安装 | 零配置、单文件 |
| 数据验证 | Pydantic v2 | 2.0+ | ✅ 2.13.4 已安装 | FastAPI/Typer 原生集成 |
| 配置 | Pydantic Settings | — | ✅ 2.14.2 已安装 | 环境变量 + 类型安全 |
| HTTP 客户端 | httpx | — | ✅ 0.28.1 已安装 | 异步 HTTP、流式 |
| 结构化日志 | loguru | — | ❌ 需安装 | 比 logging 更简洁、结构化 |
| 测试框架 | pytest | 8+ | ❌ 需安装 | 生态强大、fixture/parametrize |
| 异步测试 | pytest-asyncio | — | ❌ 需安装 | 支持 async 测试 |
| 覆盖率 | pytest-cov | — | ❌ 需安装 | 覆盖率报告 |
| API 测试 | httpx (测试模式) | — | ✅ 0.28.1 | FastAPI TestClient 使用 httpx |
| Agent 协议 | MCP | — | ❌ 需调研 | 行业标准、stdio 本地 |
| 桌面窗口 | pywebview | 5+ | ❌ Phase 2 安装 | 原生 WebView |
| 打包 | PyInstaller | 6+ | ❌ Phase 2 安装 | 成熟、跨平台 |
| 包管理 | uv + pip | uv 0.11+ | ✅ uv 0.11.14 | 极速依赖解析、工具安装 |

### 5.3 前端架构

| 维度 | 方案 |
|------|------|
| 技术栈 | React 19 + Vite 6 + Zustand 5 + shadcn/ui + Tailwind 4 |
| API 对接 | OpenAPI → openapi-typescript 自动生成 TS 类型 + API Client |
| 构建产物 | dist/ 静态文件，由 FastAPI StaticFiles 挂载（本地） |
| 状态管理 | Zustand store，API 数据用 SWR/TanStack Query |
| 流式渲染 | EventSource (SSE) 消费流式写作输出 |

### 5.4 本地部署架构（Phase 1-3 重点）

```bash
# 方式 1: pip 安装（开发者/技术用户）
pip install inkflow
inkflow serve  # 启动 Web 服务，打开浏览器

# 方式 2: 桌面端（普通用户）
# 双击 InkFlow.exe → pywebview 窗口打开 → 后端自动启动

# 方式 3: CLI 模式（Agent/脚本）
inkflow project create --name "My Novel" --json
inkflow write next --project-id 1 --json
```

**本地模式特性**:
- SQLite 单文件数据库，零配置
- 免认证（localhost 信任）
- 零外网依赖（除用户自配的 LLM API）
- MCP stdio 本地通信
- 数据全部存储在用户指定目录

---

## 6. 功能需求设计（23 个功能模块）

### 6.1 核心写作引擎（Phase 1）

#### F1: 项目/书籍管理（project_service）
| 需求项 | 说明 | 验收标准 |
|--------|------|---------|
| 创建项目 | 项目名称、题材、语言、目标字数 | CLI + Web UI 均可创建 |
| 项目配置 | AI 模型配置、Agent 角色配置、写作风格 | 配置可导出/导入 JSON |
| 项目列表 | 查看所有项目，切换当前项目 | 支持搜索和排序 |
| 项目删除 | 删除项目及关联数据 | 需二次确认，支持回收站 |

**数据模型**: `Project { id, name, genre, language, target_words, config: JSON, created_at, updated_at }`

#### F2: 章节管理（chapter_service）
| 需求项 | 说明 | 验收标准 |
|--------|------|---------|
| 卷管理 | 创建/删除/重命名/排序卷 | 支持拖拽排序（Web UI） |
| 章节管理 | 创建/删除/编辑/排序章节 | 支持跨卷移动 |
| 章节状态 | draft → writing → review → final | 状态变更可追踪 |
| 字数统计 | 自动统计章节/卷/全书字数 | 实时更新 |
| 内容编辑 | 富文本编辑（Web UI）/ 纯文本（CLI） | 支持 Markdown |

**数据模型**: `Volume { id, project_id, title, order_index }`, `Chapter { id, project_id, volume_id, title, content, status, word_count, order_index }`

#### F3: AI 写作管道（writing_service）
| 需求项 | 说明 | 验收标准 |
|--------|------|---------|
| 生成章节 | 从大纲+上下文生成完整章节 | 输出 ≥ 2000 字，格式正确 |
| 续写内容 | 接续已有内容继续写作 | 风格一致，衔接自然 |
| 修改润色 | 基于反馈修改指定段落 | 保留原文风格，修复指定问题 |
| 格式校验 | LLM 输出格式验证 | 格式异常自动重试 ≤ 3 次 |
| 流式输出 | SSE 逐 token 推送（Phase 2） | 首 token ≤ 2s |
| 写作循环 | 生成→审校→修订自动化 | 可配置循环次数 |

#### F4: Agent 编排（agent_service）
| 需求项 | 说明 | 验收标准 |
|--------|------|---------|
| Agent 角色 | Architect / Writer / Auditor / Reviser | 角色可配置 Prompt/模型/温度 |
| 编排流程 | Architect→Writer→Auditor→Reviser 链式执行 | 可跳过/重试任意环节 |
| Agent 配置 | 每项目独立 Agent 配置 | 配置可模板化，跨项目复用 |
| 自定义 Agent | 用户可创建自定义 Agent 角色 | 支持 Prompt 模板 + 工具权限 |
| 执行状态 | 实时显示当前 Agent 和执行进度 | Web UI + CLI 均可查看 |

#### F5: LLM Provider 适配（llm_service）
| 需求项 | 说明 | 验收标准 |
|--------|------|---------|
| 统一接口 | LLMClient Protocol，统一 chat/complete/stream | 新增 Provider 仅实现接口 |
| 内置 Provider | OpenAI / Anthropic / DeepSeek / Ollama / 自定义 OpenAI 兼容 | Phase 1 ≥ 3 个可用 |
| 模型路由 | 不同任务路由到不同模型 | 写作用 GPT-4，审校用 Claude |
| 流式支持 | async generator 逐 token 返回 | 兼容所有 Provider |
| 重试与超时 | 自动重试 + 指数退避 + 超时控制 | 重试 ≤ 3 次，超时可配 |
| API Key 管理 | 本地 AES-256-GCM 加密存储 | Key 不明文落盘 |
| Token 计数 | 精确计算输入/输出 Token 数 | 支持 tiktoken |

#### F6: 上下文管理（context_service）
| 需求项 | 说明 | 验收标准 |
|--------|------|---------|
| Token 预算 | 根据模型上下文窗口分配 Token | 不超过模型限制的 80% |
| 上下文分层 | protected / compressible / dynamic | 分层可配置 |
| 角色注入 | 自动注入相关角色信息到 Prompt | 按章节内容匹配相关角色 |
| 世界设定注入 | 自动注入相关世界设定 | 按 chapter location 匹配 |
| 前文摘要 | 自动生成前 N 章摘要注入 | 摘要质量可配置 |
| 伏笔追踪 | 注入未解决的伏笔提醒 | 确保前后呼应 |

#### F7: CLI 命令行接口（cli_interface）
| 需求项 | 说明 | 验收标准 |
|--------|------|---------|
| 命令结构 | `inkflow <subcommand> <action> [options]` | 支持嵌套子命令 |
| --json 输出 | 所有命令支持 JSON 输出 | JSON Schema 定义输出格式 |
| --help | 每级命令自动生成帮助 | Typer 原生支持 |
| Shell 补全 | Bash/Zsh/Fish/PowerShell 补全 | Typer 原生支持 |
| serve 命令 | 启动 Web 服务器 | 自动打开浏览器（可选） |
| 核心命令 | project / chapter / write / character / world / outline | Phase 1 覆盖核心命令 |

**命令示例**:
```bash
inkflow serve                          # 启动 Web 服务
inkflow project create --name "..." --genre xuanhuan
inkflow chapter list --project-id N --json
inkflow write next --project-id N --count 5
inkflow character add --project-id N --name "..." --json
inkflow audit check --project-id N --json
inkflow export --project-id N --format epub
```

### 6.2 创作工具链（Phase 2）

#### F8-F17: 角色管理/世界观管理/大纲管理/时间线管理/伏笔管理/统一提取服务/一致性审计/风格检测/会话管理/后台写作守护
（详细需求见原 v2.0 文档第 6.2 节，此处不再重复）

### 6.3 用户界面（Phase 2-3）

#### F18: Web UI（web_ui）
**技术栈**: React 19 + Vite 6 + Zustand 5 + shadcn/ui + Tailwind 4
**API 对接**: OpenAPI → openapi-typescript 自动生成
**核心界面**: 章节编辑器、管理面板、Agent 配置、SSE 流式

#### F19: 打包与分发（packaging）
详见第 8 节「打包方案设计」

### 6.4 Agent 集成（Phase 3）

#### F20: MCP Server（mcp_service）
**核心工具**: manage_project, manage_chapter, manage_character, manage_relation, manage_timeline, manage_world, manage_outline, manage_foreshadowing, write, audit, extract, export, search, manage_session, tool_search（≥ 15 工具）

#### F21: 导出服务（output_service）
EPUB / Markdown / TXT / DOCX（Phase 3 ≥ 3 种）

#### F22: 全文搜索（search_service）
跨内容类型搜索、类型筛选、搜索高亮

### 6.5 云端接口设计（Phase 4+，仅定义接口不实现）

| 接口 | 本地实现（Phase 1-3） | 云端实现（Phase 4+） |
|------|---------------------|---------------------|
| `AuthProtocol` | LocalTrust（免认证） | JWTAuth（OAuth 2.1） |
| `DatabaseProtocol` | SQLiteAdapter | PostgreSQLAdapter |
| `StorageProtocol` | LocalFileStorage | CloudObjectStorage |
| `UserProtocol` | SingleUser（无用户概念） | MultiTenant（多租户） |
| `SyncProtocol` | 无同步 | CloudSync（项目同步） |
| `MCPTransport` | stdio（本地） | Streamable HTTP（云端） |

---

## 7. 打包方案设计

### 推荐实现路径

```
Phase 1: pip install inkflow && inkflow serve
    ↓ (开发者/早期用户)
Phase 2: PyInstaller --onedir + Inno Setup 安装包 + 便携 ZIP
    ↓ (大众用户，Windows 优先)
Phase 2-3: + pywebview 桌面窗口
    ↓ (更好的桌面体验)
```

### 各方案对比

| 方案 | 形态 | 实现难度 | 体积 | 用户体验 | 实现阶段 |
|------|------|---------|------|---------|---------|
| pip install | Python 包 | 🟢 低 | 0（系统 Python） | 需 Python 环境 | Phase 1 |
| PyInstaller --onedir | 文件夹 | 🟢 低 | ~60-80MB | 解压即用 | Phase 2 |
| Inno Setup 安装包 | .exe 安装程序 | 🟢 低-中 | ~40-60MB | 安装到 Program Files | Phase 2 |
| pywebview 桌面端 | 原生窗口 | 🟡 中 | ~70-90MB | 真正的桌面应用体验 | Phase 2-3 |

---

## 8. 需求池与优先级

### 总览

| 优先级 | 数量 | 估算人天 | 交付阶段 |
|--------|------|---------|---------|
| P0 | 13 | 55-80 | Phase 1 |
| P1 | 16 | 45-70 | Phase 2-3 |
| P2 | 云端+停车场 | — | Phase 4+ |
| **合计** | **29+云端** | **100-150** | **3-4 个月（单人）** |

### P0 需求（Phase 1 — 核心写作引擎）

| 编号 | 需求 | 验收标准 | 估算(人天) |
|------|------|---------|----------|
| P0-01 | FastAPI 框架搭建 | OpenAPI 文档自动生成；统一错误处理；结构化日志 | 3-5 |
| P0-02 | SQLAlchemy 数据层 | SQLite 持久化；异步无阻塞；JSON 字段支持 | 4-6 |
| P0-03 | Pydantic 数据模型 | 全部数据模型类型安全；422 错误详细信息 | 2-3 |
| P0-04 | LLM Provider 适配层 | 统一 LLMClient 接口；≥ 3 个 Provider；streaming 支持 | 6-10 |
| P0-05 | Agent 编排引擎 | Architect→Writer→Auditor→Reviser 链式执行；角色可配置 | 12-18 |
| P0-06 | AI 写作管道 | 生成/续写/修改；格式校验+重试；上下文注入 | 8-12 |
| P0-07 | 上下文管理 | Token 预算；分层注入（角色/世界/前文摘要/伏笔） | 5-8 |
| P0-08 | 项目/章节管理 | CRUD；卷/章层级；字数统计 | 4-6 |
| P0-09 | Typer CLI 框架 | serve/project/chapter/write 核心命令；--json 输出 | 4-6 |
| P0-10 | 本地免认证+零外网 | 无需认证配置；无外部网络（除 LLM API） | 1-2 |
| P0-11 | 云端接口 Protocol 定义 | Database/Auth/Storage/User/Sync Protocol 定义完毕 | 2-3 |
| P0-12 | CI 流水线 | PR 自动运行测试；覆盖率检查；lint | 2-3 |
| P0-13 | 基础测试 | 核心链路单测 ≥ 50%；关键 E2E 3-5 个 | 3-5 |

### P1 需求（Phase 2 — 创作工具 + UI + 打包）

| 编号 | 需求 | 验收标准 | 估算(人天) |
|------|------|---------|----------|
| P1-01 | 角色管理 | 档案/关系图谱/分组；AI 提取 | 4-6 |
| P1-02 | 世界观管理 | 层级设定/规则约束；AI 提取 | 3-5 |
| P1-03 | 大纲管理 | 结构化大纲/情节点/故事弧线；AI 生成 | 3-4 |
| P1-04 | 时间线管理 | 事件/叙事双时间线；一致性检查 | 3-4 |
| P1-05 | 伏笔管理 | 埋设/回收追踪；写作时注入 | 2-3 |
| P1-06 | 统一提取服务 | 6 种提取类型；统一接口；增量提取 | 4-6 |
| P1-07 | 一致性审计 | 角色/时间线/世界/伏笔 4 维度检查 | 3-5 |
| P1-08 | 风格检测 | 风格指纹/AI 痕迹检测/词汇分析 | 2-3 |
| P1-09 | Web UI | 写作界面/管理面板/Agent 配置；SSE 流式 | 10-15 |
| P1-10 | 打包分发 | PyInstaller + 安装包 + 便携 ZIP + pywebview 桌面端 | 4-6 |

### P1 需求（Phase 3 — Agent 集成 + 补全）

| 编号 | 需求 | 验收标准 | 估算(人天) |
|------|------|---------|----------|
| P1-11 | MCP Server | ≥ 15 工具；stdio 传输；渐进式发现 | 5-8 |
| P1-12 | SSE 流式输出 | 逐 token 推送；前端实时渲染 | 2-3 |
| P1-13 | 会话管理 | 持久化/多会话/恢复 | 2-3 |
| P1-14 | daemon 后台写作 | 定时写作/暂停恢复/进度通知 | 2-3 |
| P1-15 | 导出服务 | EPUB/Markdown/TXT/DOCX ≥ 3 种 | 3-4 |
| P1-16 | 全文搜索 | 跨内容类型/筛选/高亮 | 2-3 |

### P2 停车场（Phase 4+）

云端认证实现(JWT/OAuth)、PostgreSQL 适配器、多用户协作、MCP Streamable HTTP、Tauri 桌面端等

---

## 9. 时间线与里程碑（单人开发版）

### 整体路线图

| 时间窗口 | 主题 | Phase | 关键交付 | 核心风险 |
|---------|------|-------|---------|---------|
| 第 1-2 周 (W1-W2) | 奠基：项目骨架+SDD 初始化 | P0 S1 | FastAPI 骨架、SDD 初始化、Constitution+Spec、CI 流水线、测试框架、LLM 适配层(接口) | 🟢 低—骨架搭建 |
| 第 3-4 周 (W3-W4) | 数据层+核心模型 | P0 S2 | SQLAlchemy 数据层、Pydantic 模型、SQLite Schema、项目/章节 CRUD、LLM Provider × 3、Protocol 定义 | 🟡 中—数据设计决策 |
| 第 5-7 周 (W5-W7) | ★ 核心引擎：Agent+写作管道 | P0 S3 | Agent 编排引擎、写作管道(生成/续写/修改)、上下文管理、格式校验+重试 | 🔴 高—Agent 编排复杂度 |
| 第 8-9 周 (W8-W9) | CLI+收尾 | P0 S4 | Typer CLI 完整命令、--json 输出、`inkflow serve`、基础 Web 占位页、E2E 测试 | 🟡 中—集成测试 |
| 第 10-12 周 (W10-W12) | 创作工具 | P1 S5-S6 | 角色/世界/大纲/时间线/伏笔管理、统一提取服务、一致性审计、风格检测 | 🟡 中—提取准确率 |
| 第 13-15 周 (W13-W15) | ★ Web UI 开发 | P1 S7 | React 前端搭建、写作界面、管理面板、Agent 配置、SSE 流式 | 🔴 高—前端单人全栈 |
| 第 15-16 周 (W15-W16) | 打包+桌面端 | P1 S8 | PyInstaller exe、安装包、便携 ZIP、pywebview 桌面端 | 🟡 中—兼容性 |
| 第 17-19 周 (W17-W19) | ★ Agent 集成 | P1 S9 | MCP Server(≥15工具)、SSE 流式、会话管理、daemon 后台写作 | 🔴 中高—MCP 协议 |
| 第 20-21 周 (W20-W21) | 导出+搜索+打磨 | P1 S10 | 导出服务(≥3格式)、全文搜索、Bug 修复、性能优化 | 🟢 低 |
| 第 22-24 周 (W22-W24) | 跨平台+验收 | P1 S11-S12 | 跨平台打包(macOS/Linux)、文档完善、Phase 3 Gate 评审 | 🟢 中 |

### Phase 1 详细 Sprint（W1-W9）

**Sprint 1.1 — 框架奠基 (W1-W2)**
- SDD 初始化：`specify init .`
- 编写 Constitution（项目章程）
- 编写 Phase 1 Spec（F1-F7 功能规格）
- FastAPI 项目骨架搭建
- Pydantic v2 数据模型基础定义
- Typer CLI 框架基础
- CI 流水线（GitHub Actions）
- 测试框架（pytest + pytest-asyncio + pytest-cov）

**Sprint 1.2 — 数据层+LLM 适配 (W3-W4)**
- SQLAlchemy 2.0 async 配置 + SQLite Schema
- Repository 模式数据层
- LLM Provider 抽象接口 + OpenAI/DeepSeek 适配器
- 云端 Protocol 接口定义（Database/Auth/Storage/User/Sync）
- 项目/章节 CRUD（project_service + chapter_service）

**Sprint 1.3 — Agent 编排+写作管道 (W5-W7)** ★ 关键路径
- Agent 编排引擎（Architect/Writer/Auditor/Reviser）
- 写作管道（生成/续写/修改）
- 格式校验 + 自动重试
- 上下文管理（Token 预算 + 分层注入）
- Prompt 模板系统
- 所有核心 CLI 命令

**Sprint 1.4 — 本地部署收尾 (W8-W9)**
- `inkflow serve` 命令
- 基础 Web 页面（占位/健康检查）
- 本地免认证
- 关键 E2E 测试（3-5 个）
- Phase 1 Gate 评审

### Phase Gate Criteria

**Phase 1 Gate (W9)**:
1. ✅ 可通过 CLI 完成完整 AI 写作流程（建书→写章节→审校）
2. ✅ ≥ 3 个 LLM Provider 可用
3. ✅ `inkflow serve` 可启动 Web 服务
4. ✅ 云端 Protocol 接口全部定义完毕
5. ✅ 测试覆盖率 ≥ 50%
6. ✅ Bug-to-Feature ≤ 1.0:1
7. ✅ 本地部署 ≤ 3 步（pip install → configure → serve）

**Phase 2 Gate (W16)**:
1. ✅ Web UI 功能覆盖 ≥ 90%
2. ✅ 角色/世界/大纲/时间线/伏笔 全部可用
3. ✅ 统一提取服务 ≥ 6 种类型
4. ✅ 审计服务可生成报告
5. ✅ daemon 可定时写作
6. ✅ Windows exe + 安装包 + 桌面端 三种打包方式可用
7. ✅ 测试覆盖率 ≥ 60%

**Phase 3 Gate (W24)**:
1. ✅ MCP Server 可用（≥ 15 工具）
2. ✅ SSE 流式输出（首 token ≤ 2s）
3. ✅ 导出 ≥ 3 种格式
4. ✅ 全文搜索可用
5. ✅ 三平台打包可用
6. ✅ 测试覆盖率 ≥ 70%
7. ✅ Bug-to-Feature ≤ 0.5:1
8. ✅ E2E ≤ 50，Flaky = 0

### 工程指标追踪

| 指标 | Phase 1 | Phase 2 | Phase 3 | 最终目标 |
|------|---------|---------|---------|---------|
| Bug-to-Feature | ≤ 1.0:1 | ≤ 0.7:1 | ≤ 0.5:1 | ≤ 0.5:1 |
| CI 提交占比 | ≤ 20% | ≤ 18% | ≤ 15% | ≤ 15% |
| 测试覆盖率 | ≥ 50% | ≥ 60% | ≥ 70% | ≥ 70% |
| E2E 数 | ≤ 20 | ≤ 40 | ≤ 50 | ≤ 50 |
| Flaky test | 0 | 0 | 0 | 0 |

---

## 10. 环境就绪检查 / 前置准备清单

### 10.1 开发环境现状

#### ✅ 已就绪
| 项目 | 版本 | 状态 |
|------|------|------|
| Python | 3.11.15 | ✅ |
| uv | 0.11.14 | ✅ |
| Git | 已安装 | ✅ |
| FastAPI | 0.136.3 | ✅ pip 已安装 |
| Pydantic | 2.13.4 | ✅ pip 已安装 |
| uvicorn | 0.49.0 | ✅ pip 已安装 |
| httpx | 0.28.1 | ✅ pip 已安装 |
| click | 8.4.1 | ✅ pip 已安装 |
| rich | 14.3.3 | ✅ pip 已安装 |
| Specify CLI | 0.4.3 | ✅ uv tool 已安装 |
| 远程仓库 | github.com/zhx-xi/InkFlow | ✅ |
| VS Code | 已安装 | ✅ (specify check 确认) |

#### ❌ 需要安装
| 包 | 用途 | 安装命令 | 优先级 |
|----|------|---------|--------|
| Typer | CLI 框架 | `pip install typer` | 🔴 Phase 1 必备 |
| SQLAlchemy | ORM | `pip install sqlalchemy[asyncio]` | 🔴 Phase 1 必备 |
| aiosqlite | 异步 SQLite 驱动 | `pip install aiosqlite` | 🔴 Phase 1 必备 |
| alembic | 数据库迁移 | `pip install alembic` | 🟡 Phase 1 推荐 |
| pytest | 测试框架 | `pip install pytest` | 🔴 Phase 1 必备 |
| pytest-asyncio | 异步测试 | `pip install pytest-asyncio` | 🔴 Phase 1 必备 |
| pytest-cov | 覆盖率 | `pip install pytest-cov` | 🟡 Phase 1 推荐 |
| pytest-xdist | 并行测试 | `pip install pytest-xdist` | 🟢 可选 |
| loguru | 结构化日志 | `pip install loguru` | 🟡 Phase 1 推荐 |
| tiktoken | Token 计数 | `pip install tiktoken` | 🟡 Phase 1 推荐 |
| cryptography | API Key 加密 | `pip install cryptography` | 🟡 Phase 1 推荐 |
| httpx-sse | SSE 客户端 | 已安装 ✅ | 用于 SSE 测试 |
| mcp | MCP SDK | 待 Phase 3 安装 | 🟢 Phase 3 安装 |
| pywebview | 桌面端 | 待 Phase 2 安装 | 🟢 Phase 2 安装 |
| PyInstaller | 打包 | 待 Phase 2 安装 | 🟢 Phase 2 安装 |
| pre-commit | Git 钩子 | `pip install pre-commit` | 🟡 推荐 |

#### Node.js 前端（Phase 2 准备）
| 工具 | 用途 | 安装命令 |
|------|------|---------|
| Node.js 20+ | 前端运行时 | 需确认 |
| npm/yarn/pnpm | 包管理 | 需确认 |
| React 19 | UI 框架 | Phase 2 安装 |
| Vite 6 | 构建工具 | Phase 2 安装 |

### 10.2 前置 Skill 清单

| Skill | 用途 | 状态 | 安装方式 |
|-------|------|------|---------|
| spec-kit-sdd | GitHub Spec-Kit SDD 工作流 | ✅ 已加载 | Hermes 内置 skill |
| plan | Plan 模式，编写实施计划 | ✅ 已加载 | Hermes 内置 skill |
| test-driven-development | TDD 工作流强制 | ✅ 已加载 | Hermes 内置 skill |
| requesting-code-review | 代码审查前置检查 | ✅ 已加载 | Hermes 内置 skill |
| github-pr-workflow | GitHub PR 生命周期管理 | ✅ 已加载 | Hermes 内置 skill |
| github-code-review | PR 代码审查工作流 | ✅ 已加载 | Hermes 内置 skill |
| systematic-debugging | 4 阶段根因调试 | ✅ 已加载 | Hermes 内置 skill |

### 10.3 SDD 初始化步骤

```bash
# 1. 进入项目目录
cd D:\develop\projects\InkFlow

# 2. 初始化 Spec-Kit（创建 .specify/ 目录）
specify init . --integration openclaw

# 3. 编写 Constitution（项目章程）
# 4. 编写 Phase 1 Spec
# 5. Clarify → Plan → Tasks → Implement
```

---

## 11. Non-goals（明确不做什么）

1. **不做迁移工具** — 这是全新项目，不从任何旧项目迁移数据
2. **不实现云端功能** — Phase 1-3 仅本地部署，云端只定义接口不实现
3. **不支持实时协作编辑(CRDT)** — Phase 5+ 考虑
4. **不实现自有 LLM 推理** — InkFlow 是 LLM 调用方，Ollama 通过 OpenAI 兼容 API 接入
5. **不做移动端 App** — 响应式 Web UI 适配
6. **不实现付费/订阅系统** — 云端商业化是独立项目
7. **不做影视化和开放世界** — P2 停车场
8. **不做自动测试生成** — 测试手写
9. **不追求与任何旧版本兼容** — 全部从零设计
10. **不一启动就并行前后端** — 单人开发，Phase 1 纯后端，Phase 2 才开始前端

---

## 12. 关键路径风险分析（单人开发）

| # | 风险 | 等级 | 影响 | 缓解措施 |
|---|------|------|------|---------|
| 1 | Agent 编排复杂度（12-18 人天） | 🔴 | 阻塞 Phase 1 核心链路 | 增量交付：先链式→再并行→再自定义；简化首版 |
| 2 | 单人前后端并行困难 | 🔴 | Phase 2 Web UI 可能延期 | Phase 1 只做后端；Phase 2 前端独立 Sprint；API 契约先行 |
| 3 | MCP 协议成熟度 | 🟡 | Phase 3 Agent 集成 | 先用简单 stdio 实现；渐进式工具发现 |
| 4 | 打包兼容性（Windows） | 🟡 | Phase 2 交付 | PyInstaller 成熟方案；尽早集成测试 |
| 5 | 前端学习成本 | 🟡 | Phase 2 效率 | 后端开发者→React 有一定学习曲线；优先核心 UI |
| 6 | 估算偏差（±30%） | 🟡 | 整体时间线 | 缓冲区 2-4 周；9 个月上限 |

---

## 13. 待确认

1. **PyPI 包名** — `inkflow` 是否被占用？
2. **LLM Provider 优先级** — Phase 1 先支持哪些？推荐 OpenAI + DeepSeek + Ollama
3. **前端技术栈确认** — React 19 全家桶 vs 简化方案？
4. **macOS/Linux 打包优先级** — Phase 2 先只做 Windows？
5. **Agent 编排引擎简化策略** — 首版是否简化到只做链式执行？

---

## ✅ 下一步行动清单

| # | 行动 | 优先级 | 预计耗时 |
|---|------|--------|---------|
| 1 | 确认 `inkflow` PyPI 包名可用 | 🔴 立即 | 5 分钟 |
| 2 | SDD 初始化（`specify init .`） | 🔴 W1 第一件事 | 2 分钟 |
| 3 | 安装缺失依赖（Typer/SQLAlchemy/aiosqlite/pytest/pytest-asyncio） | 🔴 W1 | 5 分钟 |
| 4 | 编写 Constitution（项目章程） | 🔴 W1 | 30 分钟 |
| 5 | 编写 Phase 1 Spec（F1-F7 功能规格） | 🔴 W1 | 1-2 小时 |
| 6 | 创建 Python 项目结构（src/inkflow layout） | 🔴 W1 | 15 分钟 |
| 7 | 搭建 FastAPI 骨架 + 健康检查 | 🔴 W1 | 30 分钟 |
| 8 | 搭建 CI 流水线（GitHub Actions） | 🟡 W1-W2 | 30 分钟 |
| 9 | 安装 pre-commit 并配置 | 🟡 W1 | 10 分钟 |

---

> 本 PRD 基于 v2.0 版（InkChain）更新为 InkFlow 命名，并针对单人开发场景调整了时间线和风险评估。
