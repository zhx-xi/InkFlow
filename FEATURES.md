# InkFlow 功能清单（Feature Matrix）

> **本文件是 InkFlow 功能全景的唯一权威清单**：当前已实现 + 规划中，供**人**（用户/评审者）与 **agent**（编码助手）共同对齐——动手实施任何功能前，先读本文件确认边界与状态。
>
> 维护规则见文末「功能清单维护纪律」。

## 图例

| 标记 | 含义 |
|------|------|
| ✅ | 已实现并合入 main（附 PR 编号） |
| 🔄 | 进行中 / 已排期（附 Issue 编号） |
| 🔜 | 规划中（版本已定，未拆 issue 或未动工） |

---

## 一、当前已实现功能

### 1.1 核心引擎（0.1.0，F1-F8 + P0-11，Phase 1 Gate 7/7 ✅）

| 模块 | 核心能力 | CLI 入口 | REST API 前缀 | Spec / 依据 | 状态 |
|------|---------|---------|--------------|------------|------|
| F1 `project_service` | 项目/书籍管理：CRUD + 软删除 + 回收站 | `inkflow project create/list/get/delete/restore` | `/api/v1/projects` | [`specs/f1-project-service/`](specs/f1-project-service/spec.md) | ✅ PR #8 |
| F2 `chapter_service` | 卷/章节管理：层级结构、章节移动、状态流转 | `inkflow volume create/list/delete` · `inkflow chapter create/list/get/update/delete` | `/api/v1/projects/{id}/volumes` · `/chapters` | [`specs/f2-chapter-service/`](specs/f2-chapter-service/spec.md) | ✅ PR #9 |
| F3 `writing_service` | AI 写作管道：生成 → 续写 → 修订 | `inkflow write next/continue/revise` | `/api/v1/write/generate|continue|revise` | [`specs/f3-writing-service/`](specs/f3-writing-service/spec.md) | ✅ PR #21 |
| F4 `agent_service` | Agent 编排：架构师/写手/审阅/修订角色链（LangGraph StateGraph） | `inkflow agent run/status/validate/template` | `/api/v1/pipelines/*` | [`specs/f4-agent-service/`](specs/f4-agent-service/spec.md) | ✅ PR #22 |
| F5 `llm_service` | LLM Provider 适配（OpenAI/DeepSeek/…，ChatOpenAI 兼容路由）；API Key AES-256-GCM 加密存储 | `inkflow llm list/set-key` | 配置侧（无 REST 端点） | [`specs/f5-llm-provider/`](specs/f5-llm-provider/spec.md) | ✅ PR #16 |
| F6 `context_service` | 上下文管理：角色/世界观/伏笔/时间线注入 + 章节摘要（分层 Token 预算） | 经写作管道自动装配 | `/api/v1/context/assemble` · `/chapters/{id}/summary` | [`specs/f6-context-service/`](specs/f6-context-service/spec.md) | ✅ PR #27 |
| F7 `cli_interface` | 全局 CLI 约定：JSON 信封 / 退出码 / 错误码（`--json` 全局选项） | 所有 `inkflow` 命令 | — | [`specs/f7-cli-interface/`](specs/f7-cli-interface/spec.md) | ✅ PR #28 |
| F8 CI 治理 | 测试分层（unit / integration / CLI）+ CI 门禁（ruff + mypy + pytest + 覆盖率） | — | — | [ADR-018](adr/ADR-018.md)（无独立 spec） | ✅ PRs #24+#25 |
| P0-11 云端 Protocol | 云端接口端口契约：Auth / Database / Storage / User / Sync / MCPTransport（Protocol 定义，实现留云端里程碑） | — | 端口定义（domain/ports/cloud/） | [`specs/p0-11-cloud-protocols/`](specs/p0-11-cloud-protocols/spec.md) | ✅ PR #37 |

### 1.2 创作工具链（0.2.0，F9-F16，8 模块全交付 ✅）

| 模块 | 核心能力 | CLI 入口 | REST API 前缀 | Spec | 状态 |
|------|---------|---------|--------------|------|------|
| F9 `character_service` | 角色管理：档案 / 关系图谱 / 分组 + AI 提取（样板模块，提取型） | `inkflow character create/list/get/update/delete/restore/relate/unrelate/relations/extract` | `/api/v1/characters*` · `/character-groups*` | [`specs/f9-character-service/`](specs/f9-character-service/spec.md) | ✅ PR #56 |
| F10 `world_service` | 世界观管理：条目 / 分类汇总 + AI 提取（镜像成品） | `inkflow world create/list/categories/get/update/delete/restore/extract` | `/api/v1/world-settings*` | [`specs/f10-world-service/`](specs/f10-world-service/spec.md) | ✅ PR #57 |
| F11 `outline_service` | 大纲管理：大纲 / 情节点 / 弧线 + AI 生成（首个生成型，生成即新建） | `inkflow outline create/list/get/update/delete/restore/generate` | `/api/v1/outlines*` · `/plot-points*` · `/story-arcs*` | [`specs/f11-outline-service/`](specs/f11-outline-service/spec.md) | ✅ PR #58 |
| F12 `timeline_service` | 时间线管理：事件 / 叙事双时间线 + 一致性检查（首个无 LLM 模块，确定性算法） | `inkflow timeline create/list/view/check/get/update/delete/restore` | `/api/v1/timeline*` | [`specs/f12-timeline-service/`](specs/f12-timeline-service/spec.md) | ✅ PR #63 |
| F13 `foreshadowing_service` | 伏笔管理：伏笔档案 + 状态机（埋设/回收/重开）+ 写作时注入 F6 上下文（F6 集成型，无 LLM） | `inkflow foreshadowing create/list/get/update/delete/restore/resolve/reopen` | `/api/v1/foreshadowings*` | [`specs/f13-foreshadowing-service/`](specs/f13-foreshadowing-service/spec.md) | ✅ PR #64 |
| F14 `extraction_service` | 统一提取门面：6 种提取类型（角色/世界/大纲/时间线/伏笔/风格）分发到各模块既有入口 + 增量提取（源 sha256 hash）+ **RAG 首次落地**（Chroma + BGE，ADR-013） | `inkflow extract run/status` | `/api/v1/extract*` · `/vector/reindex|retrieve` | [`specs/f14-extraction-service/`](specs/f14-extraction-service/spec.md) | ✅ PR #72 |
| F15 `audit_service` | 一致性审计：角色 / 时间线 / 世界 / 伏笔 4 维度（横切审计型，纯消费者零跨模块修改） | `inkflow audit check` | `/api/v1/projects/{id}/audit` | [`specs/f15-audit-service/`](specs/f15-audit-service/spec.md) | ✅ PR #74 |
| F16 `style_service` | 风格检测：风格指纹 / AI 痕迹 / 词汇分析（确定性文本分析型，jieba 增强 + LLM 深度分析可选） | `inkflow style analyze` | `/api/v1/projects/{id}/style/analyze` | [`specs/f16-style-service/`](specs/f16-style-service/spec.md) | ✅ PR #75 |

**0.2.0 交付实证**：1589 测试通过 / 覆盖率 91%（DoD ≥60%）· 64 个 CLI 命令 · 12 个 API router（92 端点）· Milestone #2 已关闭（2026-08-02）。

### 1.3 横切能力（跨模块，已落地）

| 能力 | 说明 | 依据 |
|------|------|------|
| RAG 向量检索 | Chroma 本地向量库 + BGE Embedding；`inkflow vector reindex/retrieve` | ADR-013，F14 落地 |
| 依赖锁定 | Python `uv.lock` 全量锁定（181 包 + sha256）；前端 `pnpm-lock.yaml` 约定 | ADR-025 |
| 日志与错误体系 | Loguru；统一错误码 + JSON 信封（CLI） | ADR-016 / ADR-012 |

### 1.4 GUI 桌面端 + SSE 流式（0.3.0，F19/F23 提前交付 ✅）

| Feature | 核心能力 | 交付 | 状态 |
|---------|---------|------|------|
| F19-GUI 子任务 A：内核进程化 | `inkflow serve` 强化：`--port 0` + 端口文件/token 交付 + WAL/busy_timeout + 健康检查（ADR-021） | PR #85 | ✅ |
| F19-GUI 子任务 B：Electron 壳 | 主进程：拉起内核 / 健康检查 / 崩溃拉起 / 回收防僵尸 | PR #95 | ✅ |
| F19-GUI 子任务 C：React 渲染层 | 核心写作界面 + 项目管理 + Agent 配置 + SSE 流式渲染（React 19 + Vite 6 + shadcn/ui + Zustand + Tailwind 4） | PR #97 | ✅ |
| F23 SSE 流式 | SSE 流式输出（GUI 流式写作依赖，首 token ≤2s） | PR #83 | ✅ |

### 1.5 质量加固（0.3.1，milestone #9 ✅）

| Issue | 内容 | 交付 | 状态 |
|-------|------|------|------|
| #86 | LLM 客户端修复：timeout→request_timeout + zhipu 注册 + audit 路由 | PR #108 | ✅ |
| #87 | LangGraph 状态重构：StateGraph(dict)→TypedDict+reducer，节点增量返回 | PR #110 | ✅ |
| #92 | 真实 AI CI job：e2e-ai-backend（label 触发 + workflow_dispatch 兜底） | PR #111 | ✅ |
| #104 | 覆盖率补全：三层全覆盖（后端 98.90% 行/96.32% 分支、前端 99.11%/92.51%、API 端点 100%、E2E 三页）；CI 门槛 98.5/95.0 常态化（ADR-027） | PR #114/#115/#116/#117 | ✅ |

### 1.6 本地产品完善（0.4.0，2026-08-07 正式发布 v0.4.0 ✅）

| Issue | 内容 | 交付 | 状态 |
|-------|------|------|------|
| #48 | F19 打包分发：PyInstaller 内核 onedir + electron-builder NSIS 安装包 + 便携 ZIP + release.yml tag v* 自动发布（B+ 装配：chromadb 进包 + API embedding 接线；数据目录 sys.frozen→%APPDATA%） | PR #144（发布门禁 #145：rc.1-rc.6 迭代修复后 v0.4.0 正式发布，exe 144.3MB + zip 175.5MB） | ✅ |
| #105 | F19-GUI 导航重构：侧边栏 + 设定库项目上下文 + 设置页框架（承接 #99 交互反馈实现） | PR #120/#121 | ✅ |
| #106 | F19-GUI 模型管理页：ProviderConfig 注册表（内置 seed + key 回退链）+ 模型管理页 + 角色绑定只读区 + 顶栏 Select + 自绘窗口按钮 | PR #122 + 修复 PR #131/#132（#125/#126：addModel rethrow + 部分失败保留草稿 + builtin_key 判重防 seed 复活） | ✅ |
| #107 | F19-GUI Agent 模板：AgentTemplate 实体（引用式运行时装配）+ 角色独立温度链（0.7 哨兵移除）+ 风险确认框 + 新建项目模板下拉 | PR #135 | ✅ |

**0.4.0 遗留**：设置持久化缺陷 #152（default_words 跳页丢失 + theme 无后端持久化）→ 0.5.0（用户拍板，2026-08-07）。

---

## 二、规划中功能

| Feature | 版本 | 内容 | 依赖/前置 | Issue | 状态 |
|---------|------|------|----------|-------|------|
| skills 包 | **1.0.0** | 小说写作 skills（源码单一真相 + 三通道分发） | 无 | [#70](https://github.com/zhx-xi/InkFlow/issues/70) | 🔜 已建 issue |
| F20 MCP Server | **1.0.0** | MCP Server（stdio 直连 domain），≥15 工具（ADR-023） | 无 | [#49](https://github.com/zhx-xi/InkFlow/issues/49) | 🔜 已建 issue |
| F24 会话管理 | **0.5.0** | 写作会话 / 恢复 | 无 | [#51](https://github.com/zhx-xi/InkFlow/issues/51) | 🔜 已建 issue |
| F25 daemon | **0.5.0** | daemon 后台写作（本地；云端无常驻任务） | 无 | [#52](https://github.com/zhx-xi/InkFlow/issues/52) | 🔜 已建 issue |
| F21 导出服务 | **0.6.0** | 导出 EPUB / MD / TXT / DOCX（≥3 格式） | 无 | [#53](https://github.com/zhx-xi/InkFlow/issues/53) | 🔜 已建 issue |
| F22 全文搜索 | **0.6.0** | 全文搜索 | 无 | [#54](https://github.com/zhx-xi/InkFlow/issues/54) | 🔜 已建 issue |
| 1.0.0 发布验收 | **1.0.0** | CLI + GUI + skills + MCP 四界面齐备；跨平台打包（macOS/Linux）+ 文档完善 + Phase 3 Gate | 以上全部 | [#55](https://github.com/zhx-xi/InkFlow/issues/55) | 🔜 已建 issue |
| F18 云端 Web 用户端 | **2.0.0** | 云 Web UI（前端一套两用，移出单机） | — | [#47](https://github.com/zhx-xi/InkFlow/issues/47) | 🔜 已建 issue |
| 云端总：云存档 + 异地写作 | **2.0.0** | 用户 API + Admin 后台 + GUI 远程模式（PostgreSQL + JWT + BYOK；无 CRDT，LWW + 修订历史） | P0-11 协议（已就绪） | [#71](https://github.com/zhx-xi/InkFlow/issues/71) | 🔜 已建 issue |

> F17 空置（PRD §6.2 标题残留编号，不使用）。
> 版本归属以 [ADR-019 v4](adr/ADR-019.md) 为准。

---

## 三、版本 → 功能映射（里程碑视角）

| 版本 | 主题 | 内容 | 状态 |
|------|------|------|------|
| 0.1.0 | 核心引擎 | F1-F8 + 云端 Protocol（Phase 1 Gate 7/7） | ✅ 已交付 |
| 0.2.0 | 创作工具链 | F9-F16 全部（8 模块：角色/世界观/大纲/时间线/伏笔/提取+RAG/审计/风格） | ✅ 已交付（2026-08-02，1589 tests / 91%） |
| 0.3.0 | GUI 桌面端（提前） | F19 GUI（内核进程化 + Electron 壳 + React 渲染层 + 视觉打磨）· F23 SSE 流式（提前）· Agent 约束体系 | ✅ 已交付（PR #83/#85/#95/#97/#100-103/#89） |
| 0.3.1 | 质量加固补丁 | #86 LLM 修复 · #87 LangGraph 重构 · #92 真实 AI CI · #104 覆盖率（后端 98.9%/96.3% 分支） | ✅ 已交付（PR #108/#110/#111/#114-#117，2026-08-06） |
| 0.4.0 | 打包 + GUI 演进 | F19 打包（exe / 安装包 / 便携 ZIP）· 导航重构 · 模型管理 · Agent 模板 | ✅ 已交付（2026-08-07 v0.4.0 正式发布，PR #120/#121/#122/#131/#132/#135/#144/#145） |
| 0.5.0 | Agent 集成 | F24 会话 · F25 daemon | 🔜 |
| 0.6.0 | 导出 + 搜索 | F21 导出 · F22 全文搜索 | 🔜 |
| 1.0.0 | 本地完全可用 | CLI + GUI + skills + MCP 四界面齐备 + 跨平台 + 文档 + Phase 3 Gate | 🔜 |
| 2.0.0 | 云端 | F18 云 Web · 用户 API · Admin 后台 · GUI 远程模式（云存档/异地写作） | 🔜 |

---

## 四、界面入口总览

| 界面 | 状态 | 说明 |
|------|------|------|
| CLI（Typer） | ✅ 可用（64 命令 / 17 组） | `inkflow <group> <command>`；`--json` 输出 JSON 信封 |
| REST API（FastAPI） | ✅ 可用（92 端点 / 12 router） | `inkflow serve` 启动，Swagger 见 `/docs`；本地内核通用通信契约 |
| GUI（Electron + React） | ✅ 0.3.0 可用（0.4.0 打包分发） | 本地桌面端（项目/写作/Agent/模型/设置页 + 侧边栏导航），渲染层不承载业务逻辑（ADR-020/021） |
| MCP Server | 🔜 1.0.0 | stdio 直连 domain（ADR-023） |
| 云 Web / Admin | 🔜 2.0.0 | 与本地 GUI 共享 React 代码（一套两用） |

---

## 五、功能清单维护纪律

1. **feature 合入后**（无论实现/文档）：同步更新 ① 本文件对应行（✅ + PR 编号）② [AGENTS.md](AGENTS.md) 功能表 ③ [ADR-019](adr/ADR-019.md) 版本表 ④ spec 头部状态行 ⑤ [README.md](README.md) 里程碑表/功能列表——五项缺一即视为收尾不完整。
2. **新拆 issue**：本文件「规划中功能」表回填 issue 编号与依赖。
3. **范围变更**：里程碑内容变更必须用户拍板后才更新本文件（先例：2026-08-02 打包提前提案被否决，维持 ADR-019 v2）。
4. **实施前必读**：agent 开始任何 feature 前先读本文件（+ AGENTS.md + 对应 spec），确认边界、状态与依赖。
5. **实证优先**：本文件声明的「已实现」以源码 + 测试为准；发现漂移（如 ADR 超前声明）立即修正并记录。

---

*本文件由功能盘点建立于 2026-08-02（0.2.0 交付后），与 AGENTS.md / ADR-019 口径一致（v4 修订 2026-08-07：0.4.0 交付 + GUI 演进）。*
