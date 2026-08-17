# Changelog

所有重要变更记录于此文件，格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。

> 版本口径以 [ADR-019 v8](adr/ADR-019.md) 为准；完整功能清单见 [FEATURES.md](FEATURES.md)。

## [0.9.0] - 2026-08-17

### 新增
- **F39/40/41 多 Agent 一期（#258/#259/#260，PR #403/#408/#407）**：Agent/Skill 实体 + 能力白名单装配 + 内置出厂配置 + skill 上传绑定（frontmatter + 可用 Agent 指定 + 删除保护）+ 自定义 Agent 编辑（prompt + 函数分组 checkbox）
- **F20 MCP Server（#49，PR #400）**：stdio 薄客户端经 HTTP + 15 聚合工具（manage_* 同源契约）+ 冷启动自动拉起内核
- **RAG 切片三档（#277/#278，PR #401/#413）**：段落切片 + 滑动重叠 + 检索元数据增强 + 对话识别/LLM 智能切片（降级 + sha256 增量）+ 指纹联动
- **F46 DAG 编排（#270，PR #412）**：agent_relations 三类型（sequential/data/conditional）+ 确定性 gate（关键词「通过/PASS」）+ 列表式编辑器
- **写作管线增强（#318/#343/#366/#379，PR #411/#417/#414/#418）**：write_continue 集成 F6 前文摘要 + HITL 确认流 GUI（usePipeline interrupt 态）+ e2e gaps G1-G4（设定驱动写作）+ 写作页 AI 聊天框/执行详情页
- **内核门控（#384，PR #398）**：写作页 e2e「内核已连接」strict mode flaky 治理
- **LLM 默认模型切 deepseek（#415，PR #416）**：生成管线默认 deepseek-v4-flash + E2E 管线模型动态化（e2e-llm.config.ts + env 覆盖）

### 修复
- 地图简形 resize + 世界观页导航（#388/#389，PR #393/#396）
- e2e-frontend-settings 三个既有失败（#399，PR #404）
- library-p3 地图工作台契约未同步 + unit-frontend 假绿（#405，PR #406）
- 打包收集残留旧版 dist-info → 版本注入失效（#421，PR #422/#423）
- 打包产物缺 inkflow-mcp.exe——MCP 入口未随 CLI/便携打包（#424，PR #425/#426/#427）
- embedding 模型 id 带 provider 前缀 → RAG reindex/retrieve 全挂（#428，PR #429）
- agentic 写作被护栏稳定终止——单工具连续改为会话总工具调用上限（#430，PR #431）

### 变更
- 0.9.0 预发布迭代 rc1-rc8（2026-08-16 ~ 08-17）：rc 验证发现 4 打包/装配/护栏缺陷（#421/#424/#428/#430）→ 逐轮修复后 rc8 全量验证通过 + GUI 用户复验确认；2026-08-17 正式发布（21/21 issues 全关）

## [0.8.0] - 2026-08-15

### 新增
- **F19 Skills 包（#70，PR #304）**：官方轨 `skills/inkflow/`（GitHub 分发，frontmatter 五字段 + 26 文件）随 CLI zip/便携包携带（#342）；用户自定义轨 `inkflow skills install/list/verify/remove`（纯本地文件操作，ADR-022 双轨）
- **F29 Supervisor 自主编排 + HITL（#161，PR #323）**：动态路由 Command(goto) + 振荡护栏 + deterministic 回退 + 人工确认流（#343 后续 GUI 落地）
- **F42 编排完全体**：Agent 链模型选择（#268）/ 执行顺序 agent_order 配置驱动（#269）/ 自定义 Agent 数据面 RoleTemplate（#295）/ 自定义角色 UI（#296）/ 默认管线模板 write_auto + write_continue（#297）/ GUI 写作页管线化（#298）
- **CLI 命令面补齐（#251）**：provider 管理 `llm provider` 组 + 模型注册/测试 + Agent 模板管理组 + `project update --config` + volume/outline/map/summary/context assemble（P1 #300 / P2 #303 / P3 #317）
- **RAG embedding 一致性（#276）**：向量指纹 + stale 检测 + 重新向量化四步协议（status → 改模型 → reindex → fresh）
- **设定库 GUI 升级（#284）**：CRUD 闭环 + 角色等级标签 + 世界观地图工作台 + 大纲三级 + 时间线双序
- **删除语义统一（#211）**：普通实体软删→真删（仅 F24 会话保留归档语义）
- **地图工作台目录树（#378）**：左侧目录树风格 + 拖拽移动调整 parent_map_id 层级（#385 修复落库）
- **世界观默认分类（#352）**：仅「地图」，其余按项目由用户/agent 创建

### 修复
- 覆盖门禁漂移 + 测试文件规模治理（#273/#281/#307）
- project 硬删不级联清理孤儿数据（#327）
- reindex 空 prompt / embedding 维度探测（#328）
- summary get/refresh 硬编码 openai/gpt-4o（#329）
- 本地 BGE fallback 未打包 + retrieve 裸 500（#330/#341）
- skills 随安装包分发通道落地（#342）
- write_auto architect 重试耗尽真实 LLM 链路（#344）
- 写作页跨项目 content 不刷新（#345）/ 地图缺创建根图按钮（#346）/ Agent 链保存失败（#347）/ 设置页模型不一致（#348）/ 模板默认字数弹窗（#349）/ 背景按钮对比度（#350）
- 地图列表显示条目名 + 创建子图失败（#368）/ 挂载清空正文风险（#371）
- 默认配置路径双形态（sentinel + 缺键/None）回退项目 model（#367/#373）
- 全局滚动条主题样式（#375）/ 地图左栏冗余分类栏（#376）/ 创建根图自动选中（#377）
- PATCH parent_map_id 不落库（#385）

### 变更
- 0.8.0 预发布迭代 rc1-rc6（2026-08-13 ~ 08-15）：GUI 复验发现 10 缺陷（#375-#379/#384 系列 + #385 阻断）→ 修复后 rc6 全量验证通过 + GUI 用户复验全部确认；正式版产物 exe 173.2MB / 便携 zip 211.6MB / CLI zip 104.3MB
- 0.8.0 发布前文档同步（#325）：AGENTS/ADR-019/FEATURES/README/specs + workspace 设计文档（#283/#387）

## [0.7.0] - 2026-08-12

### 新增
- **F26 Agent 工具基础设施（#90，PR #236）**：deepagents 0.7.5 harness 编排 + 5 只读领域工具（search_characters / check_foreshadowing / get_prior_summary / audit_chapter / count_words），静态注册表 + 工具工厂（adr/ADR-035.md v6）
- **F27 Writer Agent 闭环（#160，PR #240/#241）**：ReAct 工具循环 + save_draft 草稿确认流（draft → confirm → 正式章节）+ 四重护栏（repeat_tool / max_steps / empty_content / token_budget）+ agent_run 决策轨迹全量快照（adr/ADR-034.md / adr/ADR-036.md）
- **F28 记忆系统（#159，PR #242）**：diff 事件捕获 + N≥2 偏好学习 + protected 层注入写作上下文 + `inkflow memory list/remove/stats`（adr/ADR-037.md / adr/ADR-038.md）
- **数据目录设置（#266，PR #272）**：`config set data-dir` + GUI 设置页——`%APPDATA%\InkFlow\instance.env` 固定锚点持久化 INKFLOW_DATA_DIR，DB/向量库/chroma 整体迁移，三端一致（CLI config show = 设置 API = 实际目录）
- **模型测试按钮（#267，PR #271）**：ProviderDialog 测试请求自包含 model（不依赖未保存的注册表状态），真实 key 一键验证连接
- E2E 增强（#142 PR #238 写作页 / #143 PR #239 项目页+壳）

### 修复
- writing 404 映射 + revise 模型回退（#229/#230，PR #234）
- chapter list --status + Agent 链开关持久化 + 项目卡片跳转（#231/#225/#232，PR #233/#237/#235）
- memory stats 500——service 未解包 repo 元组（#249，PR #250）
- rc3 三缺陷：preference_repo 方法缺失 + CLI None 参数过滤 + chromadb telemetry 收集（#252/#253/#254，PR #255）
- 打包收集链：#253 补充（tiktoken 编码数据 → chromadb 全家桶 collect_all → tiktoken/tiktoken_ext Rust 扩展，PR #256/#262/#263）
- search semantic 装配注入 + spec 收集契约测试 + 打包产物冒烟（#264，PR #265）
- CLI agentic 30s 读超时 → 长超时（#274，PR #279）
- agentic 系统提示未注入 project_id → 工具查询全空 + 草稿落孤儿项目（#275，PR #280）

### 变更
- 0.7.0 预发布迭代 rc1-rc10（2026-08-11 ~ 08-12），收集类缺陷五轮洋葱剥皮（posthog → tiktoken 数据 → chromadb Rust → tiktoken Rust 扩展）后收敛，正式版体积 exe 173.0MB / 便携 zip 211.4MB / CLI zip 104.2MB（vs 0.6.0：+14%/+14%/+38%，deepagents 硬依赖 + 收集类全家桶代价）

## [0.6.0] - 2026-08-10

### 新增
- **F21 导出服务（#53，PR #214）**：TXT 单格式管线（v1.1 拍板仅 TXT）+ BookDocument 中间表示 + include_settings 设定附录开关（零新增依赖）
- **F22 全文搜索（#54，PR #216）**：FTS5+jieba 词法主检索 + AI 语义检索（mode=semantic，复用 F14 RAG）+ 索引维护三态（懒重建/ai_maintenance 增量/手动全量）+ 跨项目 project_ids 选择器
- **CLI 恒经 HTTP（#169，PR #213）**：ensure_kernel 接线 + infrastructure/http/ 客户端层（ADR-030 ② D1=A，冷启动 4.7s→热调用 ~214ms）
- **世界观三连**：
  - F35 地点树（#173，PR #215）：parent_id 邻接表 + 祖先链 + 级联删/reparent（真删语义）
  - F36 地图视图（#174，PR #220）：maps/map_pins 新表 + 图片资产 + drill-down/面包屑 + 真删删文件
  - F37 跨书复制（#175，PR #223）：递归子树 + 全局图 + pin 降级纯注释 + CLI/API 双入口
- **F34 章节审计（#208，PR #219）**：audit_logs 轻量记录 + 字数/人设/设定漂移 LLM 检查 + CLI/GUI 双确认闭环
- **设定库分类实体手动创建（#196，PR #207）**：空态 CTA 打开创建对话框（不再跳写作页）
- **E2E 设置页补全（#141，PR #222）**：模板 CRUD/风险确认框/Agent 链/默认模型/快捷键（~10 用例，ADR-028）

### 修复
- default_words 全局值重启加载（#198，PR #205）：设置页初始值回退读 fetchSettings（无项目不再显示兜底 800000）
- 设置保存反馈统一化（#199，PR #206）：tray hint/close behavior/font 切换顶部「已保存」指示

### 变更
- 0.6.0 开工前文档一致性修复（#201，PR #202）：spec 头部状态 ×4、ADR 条数 28→30、specs/README 索引、16 个长 spec 快速导航块、spec 篇幅纪律立规

## [0.5.0] - 2026-08-08

### 新增
- **F24 会话管理（#51，PR #157）**：双实体（Session + SessionLogEntry）+ 四态状态机（active/paused/completed/failed）+ 两级删除（归档→真删，F24 拍板）
- **本地内核服务化（ADR-030）**：
  - 冷启动基建（#166，PR #171）：kernel.json 状态文件 + ensure_kernel() 三态（复用/互斥拉起/stale 清理）
  - GUI 托盘常驻（#167，PR #172）：关闭→最小化托盘（内核保持）+ 托盘菜单（打开/内核状态/退出）+ 关闭行为设置
  - CLI 独立发布产物（#168，PR #181）：inkflow-cli.zip 第 4 发布产物 + NSIS PATH 安装（F33）
- **设置持久化（#152，PR #176 + #197）**：app_settings key-value 表 + GET/PATCH /settings + 前端双轨加载 + 主进程桥接 + 表单草稿守卫（F32；default_words 全局默认语义 + theme 后端化）
- **E2E 按页面域拆分（#139/#140，PR #156）**：6 spec + CI 6 job 并行；e2e-shell 提前第一批 required（ADR-028）
- **回归防护补测（PR #194）**：内核 spawn 路径来源（resourcesPath）+ 托盘图标源图居中完整性（#192）

### 修复（发布修复链 rc1-rc4）
- release.yml rc tag 自动标记 prerelease（#183，PR #184）
- CLI zip 命名对齐 GUI 风格（#185，PR #186）
- GUI 任意 cwd 启动：内核 spawn 改绝对路径（#187，PR #191）
- 托盘品牌 logo + 内核状态菜单刷新（#188，PR #190）
- default_words 全局化 + 顶部「已保存」提示（#189，PR #190/#197）
- rc2 复验四缺陷：resourcesPath 回归/顶栏内核状态真实化/托盘 logo 源图（#192，PR #193）
- 新建项目对话框目标字数 + 遮罩点击不关闭（#195，PR #197）

## [0.4.0] - 2026-08-07

### 新增
- **打包分发（#48，PR #144）**：PyInstaller 内核 onedir + electron-builder NSIS 安装包 + 便携 ZIP；release.yml tag v* 自动发布（发布门禁 #145，rc.1-rc.6 迭代修复后正式发布）
- **GUI 导航重构（#105，PR #120/#121）**：侧边栏 + 设定库项目上下文 + 设置页框架（承接 #99 交互反馈实现）
- **GUI 模型管理页（#106，PR #122 + 修复 #131/#132）**：ProviderConfig 注册表（内置 seed + key 回退链）+ 模型管理页 + 角色绑定只读区 + 顶栏 Select + 自绘窗口按钮
- **GUI Agent 模板（#107，PR #135）**：AgentTemplate 实体（引用式运行时装配）+ 角色独立温度链（0.7 哨兵移除）+ 风险确认框 + 新建项目模板下拉
- **架构图（PR #134）**：现状 + 2.0.0 云端目标 HTML 交互版 + README 引入

### 修复
- 模型管理缺陷（#125/#126，PR #131/#132）：addModel 吞异常掩盖部分失败、内置 provider 改名后重启被 seed 复活
- 打包运行时修复链（#145，rc.1-rc.6）：artifact 下载/组装修复、GH_TOKEN 显式注入、版本注入先于 uv sync、renderer into asar、品牌图标接入
- CI uv cache 修复 + job 分批（#128）

### 变更
- 文档同步（PR #134/#154）：ChatLiteLLM 残留清理、spec 头部状态全量修正、里程碑归属修正

### 已知遗留
- 设置持久化缺陷 #152（default_words 跳页丢失 + theme 无后端持久化）→ 0.5.0

## [0.3.1] - 2026-08-06

### 修复
- **LLM 客户端（#86，PR #108）**：timeout→request_timeout + zhipu 注册 + audit 路由残留修复
- **LangGraph 状态重构（#87，PR #110）**：StateGraph(dict)→TypedDict + reducer，节点增量返回，type: ignore 清零

### 新增
- **真实 AI CI（#92，PR #111）**：e2e-ai-backend job（label run-ai-tests 触发 + workflow_dispatch 兜底），T1 连通性 + T2 真实生成
- **覆盖率三层全覆盖（#104，PR #114-#117）**：后端 98.90% 行 / 96.32% 分支、前端 99.11%/92.51%、API 端点 100%、E2E 三页；CI 门槛 98.5/95.0 常态化（ADR-027）

## [0.3.0] - 2026-08-05

### 新增
- **F19 GUI 桌面端**：
  - 内核进程化（#77，PR #85）：`inkflow serve` 强化 — `--port 0` + 端口文件/token 交付 + WAL/busy_timeout + 健康检查（ADR-021）
  - Electron 壳（#78，PR #95）：主进程拉起内核 / 健康检查 / 崩溃拉起 / 回收防僵尸
  - React 渲染层（#79，PR #97）：核心写作界面 + 项目管理 + Agent 配置 + SSE 流式渲染（React 19 + Vite 6 + shadcn/ui + Zustand + Tailwind 4）
  - 视觉打磨（#98，PR #100-103）：Radix 控件 + 品牌接入 + 空态 + 菜单栏移除 + 顶栏 logo 修复链
- **F23 SSE 流式（#50，PR #83）**：统一 `POST /api/v1/writing/stream` 端点 + mode 判别联合 + SSE 帧协议 + CLI 默认流式
- **Agent 约束体系（#88，PR #89）**：AGENTS.md 行为准则 + CLAUDE.md 跳板 + 工具链强化（借鉴 LiteLLM）

## [0.2.0] - 2026-08-02

### 新增
- **创作工具链 8 模块**（F9-F16）：
  - F9 角色管理（#39，PR #56，样板模块：档案/关系图谱/分组 + AI 提取）
  - F10 世界观管理（#40，PR #57）
  - F11 大纲管理（#41，PR #58，首个 AI 生成模块）
  - F12 时间线管理（#42，PR #63，首个无 LLM 模块：确定性一致性检查）
  - F13 伏笔管理（#43，PR #64，F6 集成型：状态机 + 写作时注入）
  - F14 统一提取（#44，PR #72，横切门面 + 增量提取 + **RAG 首次落地**，ADR-013）
  - F15 一致性审计（#45，PR #74，4 维档案只读聚合）
  - F16 风格检测（#46，PR #75，确定性文本分析 + jieba + LLM 深度分析可选）
- **产品形态批量决策（#65，PR #66）**：ADR-019 v2 + ADR-020~024 + PRD v2.2
- **依赖供应链加固（#67，PR #68）**：uv + uv.lock 锁定 181 包 + sha256（ADR-025）

### 实测
- 1589 tests / 覆盖率 91%（DoD ≥60%）；64 CLI 命令 / 12 router / 92 API 端点

## [0.1.0] - 2026-07-31

### 新增
- **核心引擎**（F1-F8，Phase 1 Gate 7/7）：
  - F1 项目/书籍管理（#1，PR #8）
  - F2 卷/章节管理（#2，PR #9）
  - F3 AI 写作管道（#3，PR #21）：生成 → 续写 → 修订
  - F4 Agent 编排（#4，PR #22）：LangGraph StateGraph 角色链
  - F5 LLM Provider 适配（#5，PR #16）：ChatOpenAI 兼容路由 + API Key AES-256-GCM（ADR-005v2）
  - F6 上下文管理（#6，PR #27）：分层 Token 预算 + 章节摘要
  - F7 CLI 接口（#7，PR #28）：JSON 信封 / 退出码 / 错误码
  - F8 CI 测试分层（#23，PR #24/#25）
- **P0-11 云端接口 Protocol（#34，PR #36/#37）**：Auth / Database / Storage / User / Sync / MCPTransport

[0.6.0]: https://github.com/zhx-xi/InkFlow/milestone/6
[0.5.0]: https://github.com/zhx-xi/InkFlow/releases/tag/v0.5.0
[0.4.0]: https://github.com/zhx-xi/InkFlow/releases/tag/v0.4.0
[0.3.1]: https://github.com/zhx-xi/InkFlow/milestone/9
[0.3.0]: https://github.com/zhx-xi/InkFlow/milestone/3
[0.2.0]: https://github.com/zhx-xi/InkFlow/milestone/2
[0.1.0]: https://github.com/zhx-xi/InkFlow/milestone/1
