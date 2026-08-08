# Changelog

所有重要变更记录于此文件，格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。

> 版本口径以 [ADR-019 v5](adr/ADR-019.md) 为准；完整功能清单见 [FEATURES.md](FEATURES.md)。

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

[0.5.0]: https://github.com/zhx-xi/InkFlow/releases/tag/v0.5.0
[0.4.0]: https://github.com/zhx-xi/InkFlow/releases/tag/v0.4.0
[0.3.1]: https://github.com/zhx-xi/InkFlow/milestone/9
[0.3.0]: https://github.com/zhx-xi/InkFlow/milestone/3
[0.2.0]: https://github.com/zhx-xi/InkFlow/milestone/2
[0.1.0]: https://github.com/zhx-xi/InkFlow/milestone/1
