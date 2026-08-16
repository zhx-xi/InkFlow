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

**0.4.0 遗留**：设置持久化缺陷 #152（default_words 跳页丢失 + theme 无后端持久化）→ 0.5.0（用户拍板，2026-08-07）。✅ 已在 0.5.0 修复（PR #176）。

### 1.7 Agent 集成（0.5.0，2026-08-08 正式发布 v0.5.0 ✅）

| Issue | 内容 | 交付 | 状态 |
|-------|------|------|------|
| #51 | F24 会话管理：双实体（Session + SessionLogEntry）+ 四态状态机 + 两级删除（归档→真删） | PR #157 | ✅ |
| #139 | E2E Phase 1：按页面域拆 6 spec + CI 6 job 并行（e2e-shell 提前 required，ADR-028） | PR #156 | ✅ |
| #140 | E2E Phase 2-A：设定库 + 模型管理页 E2E 补全 | PR #156（含） | ✅ |
| #152 | 设置持久化：app_settings key-value 表 + GET/PATCH /settings + 前端双轨加载 + 主进程桥接 + 表单草稿守卫（F32，theme 后端化） | PR #176 + #197 | ✅ |
| #166 | F30 本地内核冷启动基建：kernel.json + ensure_kernel + 互斥 + stale（ADR-030 ②） | PR #171 | ✅ |
| #167 | F31 GUI 托盘常驻 + 关闭行为设置（最小化到托盘/直接退出，ADR-030 ③） | PR #172 | ✅ |
| #168 | F33 CLI 独立发布产物：inkflow-cli.zip + NSIS PATH 安装（ADR-030 ⑤） | PR #181 | ✅ |
| #183 | release.yml rc tag 自动标记 prerelease | PR #184 | ✅ |
| #185 | CLI zip 命名对齐 GUI 风格 | PR #186 | ✅ |
| #187 | GUI 任意 cwd 启动：内核 spawn 绝对路径（resourcesPath） | PR #191 | ✅ |
| #188 | 托盘品牌 logo + 内核状态菜单刷新 | PR #190 | ✅ |
| #189 | 设置持久化全局化 default_words 方案 A + 顶部「已保存」提示 | PR #190/#197 | ✅ |
| #192 | rc2 复验四缺陷：resourcesPath 回归/顶栏状态真实化/托盘 logo 源图 | PR #193 | ✅ |
| #195 | 新建项目对话框目标字数 + 遮罩点击不关闭 | PR #197 | ✅ |

**0.5.0 交付实证**：16/16 issues 全关（milestone #5 2026-08-08 关闭）· rc1→rc4 预发布迭代后 v0.5.0 正式发布（2026-08-08，Latest）。

### 1.8 导出 + 搜索 + 世界观（0.6.0，2026-08-09 里程碑关闭 ✅）

| Issue | 内容 | 交付 | 状态 |
|-------|------|------|------|
| #53 | F21 导出服务：TXT 单格式管线（v1.1 拍板仅 TXT）+ BookDocument 中间表示 + include_settings 附录开关 | PR #214 | ✅ |
| #54 | F22 全文搜索：FTS5+jieba 词法 + AI 语义检索（mode=semantic，复用 F14 RAG）+ 索引维护三态 + 跨项目 project_ids | PR #216 | ✅ |
| #169 | F38 CLI 恒经 HTTP：ensure_kernel 接线 + infrastructure/http/ 客户端层（ADR-030 ② D1=A，冷启动 4.7s→热调用 ~214ms） | PR #213 | ✅ |
| #173 | F35 世界观地点层级：parent_id 树 + 祖先链 + 级联删/reparent（真删语义，提取建树后置 0.7.0） | PR #215 | ✅ |
| #174 | F36 世界观地图视图：maps/map_pins 新表 + 图片资产 + drill-down/面包屑 + 真删删文件 | PR #220 | ✅ |
| #175 | F37 世界观跨书复制：递归子树 + 全局图（Q3=B）+ pin 降级纯注释 + CLI/API 双入口 | PR #223 | ✅ |
| #208 | F34 章节审计：audit_logs 轻量记录 + 字数/人设/设定漂移 LLM 检查 + CLI/GUI 双确认闭环 | PR #219 | ✅ |
| #196 | 设定库分类实体手动创建（空态 CTA 打开创建对话框，不再跳写作页） | PR #207 | ✅ |
| #198 | default_words 全局值重启加载（初始值回退读 fetchSettings） | PR #205 | ✅ |
| #199 | 设置保存反馈统一化（tray hint/close behavior/font 顶部「已保存」） | PR #206 | ✅ |
| #141 | E2E 设置页补全（模板 CRUD/风险确认框/Agent 链/默认模型/快捷键，~10 用例） | PR #222 | ✅ |
| #201 | 0.6.0 开工前文档一致性修复（15🔴 漂移 + spec 导航 + 立规） | PR #202 | ✅ |
| #249/#252 | memory stats 500 修复链（service 元组解包 → preference_repo 方法缺失） | PR #250/#255 | ✅ |
| #253/#254 | 打包收集链（chromadb telemetry → CLI None 参数过滤 → tiktoken 编码数据 → chromadb 全家桶 → tiktoken Rust 扩展） | PR #255/#256/#262/#263 | ✅ |
| #264 | search semantic 装配注入 + spec 收集契约测试 + 打包产物冒烟（三层防回归） | PR #265 | ✅ |
| #266 | 数据目录设置：instance.env 固定锚点 + CLI config set data-dir + GUI 设置页（DB/向量库整体迁移） | PR #272 | ✅ |
| #267 | 模型测试按钮：测试请求自包含 model（保存前测试不再回退全局默认） | PR #271 | ✅ |
| #274 | CLI agentic 长超时（30s → 300s 读超时，agentic 多步 ReAct 不再 ReadTimeout） | PR #279 | ✅ |
| #275 | agentic 系统提示注入 project_id（工具查询 + save_draft 草稿归属修复） | PR #280 | ✅ |

**0.6.0 交付实证**：12/12 issues 全关（milestone #6 2026-08-09 关闭）· 2026-08-10 v0.6.0 正式发布（Latest）· 新增 f34-f38 五个模块变体（审计型/传输改造型/树型/资产呈现型/复用型）· 全链路 CLI 恒经 HTTP 单路径（ADR-030 ② 落地）。

### 1.9 Agent 化升级（0.7.0，2026-08-11 里程碑 10/10 issues 全关 ✅）

| Issue | 内容 | 交付 | 状态 |
|-------|------|------|------|
| #90 | F26 Agent 工具基础设施：ToolSpec + deepagents 0.7.5 harness 集成（create_deep_agent + HarnessProfile `openai:<model>`）+ 5 只读工具（excluded_tools 禁默认文件系统工具；subagent task 工具 F29 用） | PR #236 | ✅ |
| #160 | F27 Writer Agent 闭环：ReAct 工具循环 + save_draft 草稿写工具（draft 表 + 确认流 draft→final）+ 四重护栏（max_steps 12 / repeat_tool 3 / empty_content 重试 / token_budget 32K）+ agent_run 决策轨迹快照 | PR #240（spec）+ #241 | ✅ |
| #159 | F28 记忆系统：diff 事件捕获（PATCH drafts 编辑端点）+ N≥2 规则化偏好学习（project_preferences + memory_events 表，confidence=1-1/(count+1)）+ F6 protected 层注入（显式设定 > 学习偏好）+ inkflow memory list/remove/stats + memory_learning extra 键默认 false | PR #242 | ✅ |
| #142 | E2E 写作页深度：树 CRUD + 工具栏 + AI 按钮状态 | PR #238 | ✅ |
| #143 | E2E 项目页 + 壳 chrome：模板创建/删除确认/窗口控制 | PR #239 | ✅ |
| #225 | Agent 链开关「关闭」状态持久化（重启后恢复开启，#105 遗留） | PR #237 | ✅ |
| #229 | writing API 资源不存在错误映射违约：_NotFoundError 500 → 404（ADR-012） | PR #234 | ✅ |
| #230 | revise_content 默认模型硬编码 openai/gpt-4o → 走项目配置回退 | PR #234 | ✅ |
| #231 | CLI chapter list 不传 --status 报 422 → 空参数过滤（帮助信息与行为一致） | PR #233 | ✅ |
| #232 | 项目页点击项目卡片不跳转写作面板（多项目无法切换） | PR #235 | ✅ |

**0.7.0 交付实证**：10/10 issues 全关（milestone #10，2026-08-11）· Agent 化主线 F26→F27→F28（deepagents 0.7.5 harness）· agentic 写作闭环（save_draft + 确认流 + 修改率基线 docs/agent-baseline-2026-08-10.md）· v0.7.0-rc1 预发布（2026-08-11）。

### 1.10 编排完全体 + Supervisor + 设定库 + RAG + skills + CLI（0.8.0，2026-08-13 18/18 issues 全关 ✅）

| Issue | 内容 | 交付 | 状态 |
|-------|------|------|------|
| #268 | Agent 链模型选择：三态 Select（真禁用/项目默认/指定模型）+ sentinel 执行修复 + 裸名兼容 + provider-configs chat 数据源 | PR #299 | ✅ |
| #269 | Agent 执行顺序编辑：agent_order 层级拓扑（槽位 0-9 同层并行）+ 双模式 B1 + 存储/API/执行三层校验 + 通用节点 + 多入口/终点引擎 | PR #305 | ✅ |
| #295 | 自定义 Agent 数据面：RoleTemplate prompt/name + ProjectConfig 自定义角色字段 | PR #309 | ✅ |
| #296 | 自定义 Agent UI：AgentChainCard 自定义角色行 | PR #315 | ✅ |
| #297 | 默认管线模板：builtin:write_auto 全自动 + builtin:write_continue 续写（F42 §5.6） | PR #308 | ✅ |
| #298 | GUI 写作入口管线化：写作页全自动/续写切换 + 执行状态 UI | PR #314 | ✅ |
| #161 | F29 Supervisor 自主编排 + HITL：自研 LangGraph StateGraph 编排层 + Command(goto) 动态路由 + 振荡护栏 + deterministic 回退 + HITL interrupt | PR #323 + #324 登记 | ✅ |
| #211 | 删除语义统一：普通实体软删→真删（F10 v1.1；F1 回收站/F24 归档保留软删） | PR #312 | ✅ |
| #276 | RAG embedding 一致性：向量指纹 + stale 检测 + 重新向量化协议 | PR #302 | ✅ |
| #70 | F19-skills 包：官方 skills/inkflow/ 资产 + 用户自定义轨 skills 命令组（install/list/verify/remove，ADR-022 双轨） | PR #304 | ✅ |
| #251 | CLI 命令面补齐：provider 管理 / agent template 管理 / project config（P1/P2/P3） | PR #300/#303/#317 | ✅ |
| #284 | 设定库 GUI 升级（F43，P0-P5）：CRUD 闭环 + 角色等级标签 + 世界观地图工作台 + 大纲三级 + 时间线双序 + 删除引用残留清理 | PR #301/#306/#311/#319/#322 | ✅ |
| #281 | 测试文件规模治理：拆分豁免超限文件 + 前端护栏扩展 + 双份冗余归并 | PR #310 | ✅ |
| #273 | coverage-backend 门禁治本：移除 chromadb 测试 --ignore 排除 | PR #321 | ✅ |
| #307 | extraction_service 拆分（978→900 行内，F14 门面） | PR #316 | ✅ |
| #313 | RoleTemplate 测试契约同步（#309 遗留） | PR #320 | ✅ |
| #283 | 0.7.0 Agent 化架构决策收尾：ADR-A~H 正式落盘 ADR-031~038 + 设计文档入库 | PR #287 + #289 | ✅ |
| #257 | 多 Agent 能力分析登记（Agent 差异化能力白名单） | PR #285 | ✅ |

**0.8.0 交付实证**：18/18 issues 全关（milestone #11，2026-08-13）· 配置驱动编排完全体（F42：三态模型选择 + agent_order 槽位 0-9 层级拓扑 + 双模式 + 通用节点 + GUI 写作管线化 write_auto/write_continue + 自定义 Agent 数据面/UI）· F29 Supervisor 自主编排 + HITL（Command(goto) 动态路由 + 振荡护栏 + deterministic 回退）· 删除语义统一（软删→真删）· RAG 指纹一致性（stale 检测 + 重新向量化）· skills 双轨（官方轨 GitHub 分发 + 用户自定义轨 CLI 导入）· CLI 命令面补齐（provider/template/project config）· 设定库 GUI 升级（F43 P0-P5）。

---

## 二、规划中功能

| Feature | 版本 | 内容 | 依赖/前置 | Issue | 状态 |
|---------|------|------|----------|-------|------|
| skills 包 | ✅ 0.8.0 | 官方 skills/inkflow/ 资产（GitHub 分发）+ 用户自定义轨 skills 命令组（导入管理） | 无 | [#70](https://github.com/zhx-xi/InkFlow/issues/70) | ✅ 已交付（PR #304，2026-08-13） |
| F20 MCP Server | ✅ 0.9.0 | MCP Server（stdio 薄客户端经 HTTP），15 聚合工具（ADR-023 v2，spec v1.1） | #166（内核冷启动基建，✅ 已实现 PR #171） | [#49](https://github.com/zhx-xi/InkFlow/issues/49) | ✅ 已交付（PR #400，2026-08-16） |
| F29 Supervisor 自主编排 | ✅ 0.8.0 | 自主编排 + HITL（Command(goto) 动态路由 + 振荡护栏 + deterministic 回退） | F26/F27/F28 | [#161](https://github.com/zhx-xi/InkFlow/issues/161) | ✅ 已交付（PR #323 + #324 登记，2026-08-13） |
| ~~F25 daemon~~ | ~~0.5.0~~ | ~~daemon 后台写作~~（**已移除**，ADR-029：伪需求；真实意图=外部 agent 经 MCP/skills 调用，由 F19 serve + F20 MCP + skills 包覆盖） | 无 | [#52](https://github.com/zhx-xi/InkFlow/issues/52) | ❌ 已关闭（2026-08-07） |
| 1.0.0 发布验收 | **1.0.0** | CLI + GUI + skills + MCP 四界面齐备；跨平台打包（macOS/Linux）+ 文档完善 + Phase 3 Gate | 以上全部 | [#55](https://github.com/zhx-xi/InkFlow/issues/55) | 🔜 已建 issue |
| F18 云端 Web 用户端 | **2.0.0** | 云 Web UI（前端一套两用，移出单机） | — | [#47](https://github.com/zhx-xi/InkFlow/issues/47) | 🔜 已建 issue |
| 云端总：云存档 + 异地写作 | **2.0.0** | 用户 API + Admin 后台 + GUI 远程模式（PostgreSQL + JWT + BYOK；无 CRDT，LWW + 修订历史） | P0-11 协议（已就绪） | [#71](https://github.com/zhx-xi/InkFlow/issues/71) | 🔜 已建 issue |

> F17 空置（PRD §6.2 标题残留编号，不使用）。
> 版本归属以 [ADR-019 v7](adr/ADR-019.md) 为准。

---

## 三、版本 → 功能映射（里程碑视角）

| 版本 | 主题 | 内容 | 状态 |
|------|------|------|------|
| 0.1.0 | 核心引擎 | F1-F8 + 云端 Protocol（Phase 1 Gate 7/7） | ✅ 已交付 |
| 0.2.0 | 创作工具链 | F9-F16 全部（8 模块：角色/世界观/大纲/时间线/伏笔/提取+RAG/审计/风格） | ✅ 已交付（2026-08-02，1589 tests / 91%） |
| 0.3.0 | GUI 桌面端（提前） | F19 GUI（内核进程化 + Electron 壳 + React 渲染层 + 视觉打磨）· F23 SSE 流式（提前）· Agent 约束体系 | ✅ 已交付（PR #83/#85/#95/#97/#100-103/#89） |
| 0.3.1 | 质量加固补丁 | #86 LLM 修复 · #87 LangGraph 重构 · #92 真实 AI CI · #104 覆盖率（后端 98.9%/96.3% 分支） | ✅ 已交付（PR #108/#110/#111/#114-#117，2026-08-06） |
| 0.4.0 | 打包 + GUI 演进 | F19 打包（exe / 安装包 / 便携 ZIP）· 导航重构 · 模型管理 · Agent 模板 | ✅ 已交付（2026-08-07 v0.4.0 正式发布，PR #120/#121/#122/#131/#132/#135/#144/#145） |
| 0.5.0 | Agent 集成 | F24 会话 · E2E 增强（#139/#140）· 设置持久化（#152）· 本地内核服务化（#166 冷启动 / #167 托盘 / #168 CLI 产物）· 发布修复链（#183/#185/#187/#188/#189/#192/#195） | ✅ 已交付（2026-08-08 v0.5.0 正式发布，PR #156/#157/#171/#172/#176/#181/#184/#186/#190/#191/#193/#194/#197） |
| 0.6.0 | 导出 + 搜索 + 世界观 | F21 导出 · F22 全文搜索 · F34 章节审计 · 世界观三连（#173/#174/#175）· CLI 恒经 HTTP（#169）· E2E 设置页（#141）· 设定库手动创建（#196）· default_words 重启加载（#198）· 保存反馈统一化（#199） | ✅ 已交付（2026-08-09 里程碑关闭；2026-08-10 v0.6.0 正式发布，PR #202/#205/#206/#207/#213/#214/#215/#216/#219/#220/#222/#223） |
| 0.7.0 | Agent 化升级 | F26 Agent 工具基础设施（deepagents 0.7.5）· F27 Writer Agent 闭环（ReAct + save_draft）· F28 记忆系统（偏好学习 + 注入）· E2E 增强（#142/#143）· bug 批（#225/#229/#230/#231/#232） | ✅ 已交付（2026-08-11 里程碑 10/10 issues 全关，PR #233-#242） |
| 0.8.0 | 编排完全体 + Supervisor + 设定库 + RAG + skills + CLI | F42 编排完全体（三态模型选择 + agent_order 槽位 0-9 + 双模板 + 自定义 Agent 数据面/UI）· F29 Supervisor（动态路由 + HITL）· 删除语义统一 · RAG 指纹 · F19-skills 包 · CLI 命令面补齐 · 设定库 GUI（F43 P0-P5） | ✅ 已交付（2026-08-13 里程碑 18/18 issues 全关，PR #285/#287/#289/#299/#302/#304/#305/#308/#309/#310/#312/#314/#315/#316/#317/#320/#321/#322/#323/#324） |
| 1.0.0 | 本地完全可用 | CLI + GUI + skills + MCP 四界面齐备 + 跨平台 + 文档 + Phase 3 Gate | 🔜 |
| 2.0.0 | 云端 | F18 云 Web · 用户 API · Admin 后台 · GUI 远程模式（云存档/异地写作） | 🔜 |

---

## 四、界面入口总览

| 界面 | 状态 | 说明 |
|------|------|------|
| CLI（Typer） | ✅ 可用（64 命令 / 17 组） | `inkflow <group> <command>`；`--json` 输出 JSON 信封 |
| REST API（FastAPI） | ✅ 可用（92 端点 / 12 router） | `inkflow serve` 启动，Swagger 见 `/docs`；本地内核通用通信契约 |
| GUI（Electron + React） | ✅ 0.3.0 可用（0.4.0 打包分发） | 本地桌面端（项目/写作/Agent/模型/设置页 + 侧边栏导航），渲染层不承载业务逻辑（ADR-020/021） |
| MCP Server | ✅ 0.9.0 | stdio 薄客户端经 HTTP，15 聚合工具（ADR-023 v2；PR #400，2026-08-16） |
| 云 Web / Admin | 🔜 2.0.0 | 与本地 GUI 共享 React 代码（一套两用） |

---

## 五、功能清单维护纪律

1. **feature 合入后**（无论实现/文档）：同步更新 ① 本文件对应行（✅ + PR 编号）② [AGENTS.md](AGENTS.md) 功能表 ③ [ADR-019](adr/ADR-019.md) 版本表 ④ spec 头部状态行 ⑤ [README.md](README.md) 里程碑表/功能列表——五项缺一即视为收尾不完整。
2. **新拆 issue**：本文件「规划中功能」表回填 issue 编号与依赖。
3. **范围变更**：里程碑内容变更必须用户拍板后才更新本文件（先例：2026-08-02 打包提前提案被否决，维持 ADR-019 v2）。
4. **实施前必读**：agent 开始任何 feature 前先读本文件（+ AGENTS.md + 对应 spec），确认边界、状态与依赖。
5. **实证优先**：本文件声明的「已实现」以源码 + 测试为准；发现漂移（如 ADR 超前声明）立即修正并记录。

---

*本文件由功能盘点建立于 2026-08-02（0.2.0 交付后），与 AGENTS.md / ADR-019 口径一致（v7 修订 2026-08-13：0.8.0 编排完全体 + Supervisor + 设定库 + RAG 指纹 + skills + CLI 补齐交付）。*
