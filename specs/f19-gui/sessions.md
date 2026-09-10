# 会话页 — 交互规格

> 页面: sessions | 路由: /sessions | 组件: frontend/packages/renderer/src/pages/sessions.tsx（SessionsPage，nav 项 sessions，lucide History 图标）
> 对应 design/GUI/sessions/（官方简图 sessions.html + sessions-<state>.png，见后续补图；当前目录仅 .gitkeep 占位）

## 1. 画面样式

- 原型引用：design/GUI/sessions/sessions.html + sessions-<state>.png（后续补图，目录已建）
> 低保真排版示意简图（区块+标签，非精确像素）：

```text
┌────────┬─────────────────────────┐
│InkFlow 　　　　│　会话　　　　　　　　　　主题▾　中文▾　─ □ ×　│
│写作　　　　　　│　会话　　　　　　　　　　　　　　　　　　　　　　│
│项目　　　　　　│　项目▾　搜索会话标题 / 项目 / 最后消息… 　　　　│
│设定库　　　　　│　［全部●］　［活动］　［已归档］　　　　　　　　│
│角色　　　　　　│　┌─────────────────────┐　│
│世界观　　　　　│　│［AI对话·进行中］　青云志　　　　23 条 　│　│
│大纲　　　　　　│　│帮我看看第 12 章的氛围描写要不要再收紧…　│　│
│时间线　　　　　│　│［归档］　［删除］　　　　2026-08-30 09:41│　│
│伏笔　　　　　　│　├─────────────────────┤　│
│知识图谱　　　　│　│［执行·已完成］　第 12 章 剑心蒙尘・续写 │　│
│检索　　　　　　│　│［归档］　［删除］　　　　2026-08-30 09:12│　│
│会话　●　　　　│　├─────────────────────┤　│
│Agent 　　　　　│　│［访谈·已完成］　第二卷世界观补全访谈　　│　│
│记忆　　　　　　│　│只读访谈卡，无操作按钮　　2026-08-29 15:04│　│
│设置　　　　　　│　└─────────────────────┘　│
│［折叠］　　　　│　┌─────────────────────┐　│
│　　　　　　　　│　│删除会话？　　　　　　　　　　　　　　　　│　│
│　　　　　　　　│　│此操作将永久删除会话，不可恢复。　　　　　│　│
│　　　　　　　　│　│［取消］　　　［确定删除］　　　　　　　　│　│
│　　　　　　　　│　└─────────────────────┘　│
├────────┼─────────────────────────┤
│　　　　　　　　│　内核已连接・模型: deepseek-chat・会话: 11 　　　│
└────────┴─────────────────────────┘
```

- 参考锚点（以真实组件 pages/sessions.tsx 为准，#725 统一窗口重构 + #547/#581 AI 对话聚合 + #566 真删）：
  - 页面骨架：max-w-[1080px] 居中容器，标题「会话」
  - 顶部工具条（与会话目录同栏）：项目选择器 + 检索框（本地过滤，不重拉）
  - filter chips：全部 / 活动 / 已归档（aria-pressed 高亮，本地过滤）
  - 统一目录（session-directory）：执行会话 / 访谈会话 / AI 对话三类卡片合并，按 updated_at 倒序，类型徽标区分
  - 卡片行内：类型徽标（执行/访谈/AI 对话）+ 状态徽标（进行中/已暂停/已完成/失败 或 访谈中/已完成/已跳过）+ 已归档徽标 + 标题 + 操作按钮（归档/恢复/删除）
  - 删除确认对话框：固定遮罩 + 「删除会话？」+ 永久删除提示 +「取消/确定删除」
  - 空态：「暂无会话」（三类数据全部落定前也显示该空态容器）
  - **左侧会话栏（session-bar，AppNav 会话组 `SessionBar`，#825 修复）**：消费 `GET /chat/conversations?include_deleted=true` 拉取**全部**线程后**本地按当前项目 `project_id` 过滤**（后端不收 project_id）；每条目显示**单一 title**（空回退 `last_message`/project_name，无冗余底部小 title）`session-item-<id>` + 消息数·更新时间；**折叠按钮位于「会话」标题行最右（justify-between）**；空列表 → 「暂无数据」（`session-bar-empty`）；折叠态列表隐藏但 header + 折叠按钮仍显示
- 布局说明：
  - 顶部：h1「会话」
  - 工具条（mt-5）：项目 Select（w-56）→ 检索框（min-w-[220px] flex-1，placeholder「搜索会话标题 / 项目 / 最后消息…」）
  - chips 行（mt-3）：全部/活动/已归档
  - 目录（mt-6）：卡片列表 space-y-3，每卡 p-4 圆角边框；访谈卡只读（无操作按钮），执行卡与 AI 对话卡有归档/恢复/删除
  - 删除确认：z-50 遮罩弹窗，居中 max-w-sm

## 2. 动作样式（按钮 × 状态表，逐控件）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 | 修改履历 |
|------|--------|--------|--------|------|------|------|------|
| 项目选择器（sessions-project-select） | 当前项目名（无则 placeholder「当前项目」） | 展开项目列表 | — | selectProject → 目录按项目重过滤（前端过滤不重拉） | — | 路由直入且未选项目 → 自动回退首个项目（仅一次，不覆盖用户已选） | — |
| 检索框（sessions-search） | 空输入，placeholder 提示 | 输入即过滤 | — | 目录按 标题/项目名/最后消息 本地过滤（trim + 小写） | — | 纯本地过滤不重拉接口；与 filter chips 叠加生效 | — |
| filter chips（全部/活动/已归档） | 「全部」高亮（aria-pressed） | 切换过滤条件 | — | 目录切换：已归档 → 仅 is_deleted；活动 → 仅非 is_deleted；全部 → 不过滤 | — | 本地过滤不重拉（归档回归由测试锁定）；与检索框叠加 | — |
| 左侧会话栏（session-bar 会话条目列表） | `GET /chat/conversations?include_deleted=true` 拉取**全部**线程 → 本地按 `project_id === currentProjectId` 过滤（后端不收 project_id） | 点击条目 → title 匹配章节则跳章节页 / 匹配不到 → 全局 chat 页 | 加载中不渲染空态（loading && items 空） | 渲染当前项目会话条目（`session-item-<id>`），每项单一 title + 消息数·时间 | 拉取失败 → 静默置空 + 空态「暂无数据」 | 空列表 → 空态「暂无数据」（`session-bar-empty`）；折叠态整个列表隐藏但 header + 折叠按钮仍显示 | 新增（#825） |
| 左侧会话栏折叠按钮（session-bar-toggle） | 展开态（「折叠」图标） | 切换折叠/展开 | — | 折叠态存 localStorage（`session-bar.collapsed`） | — | 按钮位于「会话」标题行**最右侧**（justify-between）；折叠/展开图标随状态切换 | 修改（#825：按钮挪到「会话」行最右边，位置修正） |
| 左侧会话栏条目标题 | 展示会话 `title`（空回退 `last_message`/project_name） | — | — | 一次只显示**一个清晰标题**（无冗余底部小 title / 副行 last_message 重复） | — | 归档会话 `is_deleted` 亦显示（include_deleted=true）；标题过长 truncate | 修改（#825：title 精简，删除冗余底部小 title） |
| 归档按钮（session-archive / chat-conv-archive） | 活动态卡片显示，outline 样式 | archiveSession(id) / archiveChatConversation(id) | — | 本地置 is_deleted=true → 卡片转归档态 + ok toast「已归档」 | err toast「原因」 | 仅活动态渲染；归档态不显示归档按钮 | — |
| 恢复按钮（session-restore / chat-conv-restore） | 归档态卡片显示 | restoreSession(id) / restoreChatConversation(id) | — | 本地置 is_deleted=false → 卡片回活动态 + ok toast「已恢复」 | err toast「原因」 | 仅归档态渲染；恢复后归档徽标消失 | — |
| 删除按钮（session-delete / chat-conv-delete） | 所有卡片显示，hover 变红 | 打开删除确认对话框（受控 deleteTarget） | — | — | — | 仅打开对话框，不发删除请求 | — |
| 删除确认「取消」（session-delete-cancel） | 对话框内次按钮 | 关闭对话框 | — | 卡片不变 | — | 不调任何 API | — |
| 删除确认「确定删除」（session-delete-confirm） | 对话框内主按钮（accent） | deleteSession(id) / deleteChatConversation(id)（force 真删） | — | 卡片从目录移除 + ok toast「已删除」 | err toast「原因」 | 描述「此操作将永久删除会话，不可恢复」；删除后不可撤销 | — |
| 访谈卡片 | 只读：访谈徽标 + 状态 +「已确认 {n} 项」+ 标题 + 可选「已生成写作计划」徽标 | 无操作按钮 | — | — | — | 无归档/恢复/删除入口 | — |

## 3. 验收

- N1：统一目录合并三类会话（执行/访谈/AI 对话），类型徽标区分，按 updated_at 倒序；三类数据全部落定后才渲染卡片（无部分闪现）
- N2：项目选择器切换 → 目录仅显示该项目会话；未选项目时自动回退首个项目（仅一次）
- N3：filter chips 本地过滤不重拉：已归档只显示归档态、活动只显示活动态、全部不过滤；归档会话在「已归档」chip 下可见（归档回归）
- N4：检索框按 标题/项目名/最后消息 过滤，与 chips 叠加，无网络请求
- N5：执行会话与 AI 对话归档/恢复闭环：活动态可归档（ok toast）→ 归档态显示「已归档」徽标 + 恢复按钮 → 恢复后回活动态；失败均 err toast 且列表状态不变
- N6：删除需经确认对话框（含永久删除提示）；确定 → 卡片移除 + ok toast「已删除」；取消 → 无副作用
- N10（#825 UI 元素必须出现）：左侧会话栏（SessionBar）渲染时——① mock 会话列表返回含「蜀山，我是掌门」等条目 → 断言 `session-item-<id>` / `getByText('蜀山，我是掌门')` **出现**（非「暂无数据」）；② 每个条目断言**仅一个清晰标题**（无冗余底部小 title）；③ 折叠按钮 `session-bar-toggle` 断言位于「会话」标题行最右（justify-between，或在分组 header 内右对齐）；④ 无会话 → 断言空态「暂无数据」文案出现（`session-bar-empty`）。⑤ 按项目过滤：mock 含项目 p1/p2 线程，`projectId='p1'` 时仅显示 p1 条目、p2 条目不出现。

## 4. #770 会话页架构增量（会话标题/改名/导航）

> 会话列表展示 `title`；新增改名入口；点击会话按 title 匹配章节 → 跳章节页，匹配不到 → 跳全局 chat 页。完整契约见 f47 §17。

### 4.1 画面样式补充
> 低保真排版示意简图（区块+标签，非精确像素；#770 会话 title/改名/导航，完整契约见 f47 §17.4）

```text
┌────────┬──────────────────────────────────────────┐
│InkFlow │  会话                                    │
│写作    │  项目▾  搜索会话标题 / 项目 / 最后消息…    │
│会话 ●  │  [全部]  [活动]  [已归档]                 │
│        │  ┌────────────────────────────────────┐  │
│        │  │[AI对话] 第1章 初见（title 展示）     │  │
│        │  │  23 条 · 2026-08-30 09:41           │  │
│        │  │  [改名] [归档] [删除]                │  │
│        │  └────────────────────────────────────┘  │
│        │  ┌────────────────────────────────────┐  │
│        │  │[执行] 第 12 章 剑心蒙尘・续写        │  │
│        │  │  [改名] [归档] [删除]  2026-08-30   │  │
│        │  └────────────────────────────────────┘  │
│        │  （点击卡片：title 匹配章节 → /writing?    │
│        │    chapter_id=..；匹配不到 → /writing?    │
│        │    conversation_id=.. 全局 chat 页）      │
├────────┼──────────────────────────────────────────┤
│        │  内核已连接 · 模型: deepseek-chat · 会话:N │
└────────┴──────────────────────────────────────────┘
```


- 会话卡片目录（`session-directory`）AI 对话卡片展示会话 `title`（空则回退 `project_name`）；联系人标题行加「改名」按钮（`chat-conv-rename-{id}`）。
- 卡片导航：点击会话 → 用 `title` 匹配当前项目章节标题 → 匹配则 `navigate('/writing?chapter_id=...')`；匹配不到 → `navigate('/writing?conversation_id=...')`（全局 chat 页）。

### 4.2 动作样式补充

- 改名按钮（chat-conv-rename-{id}）→ 行内输入框（Enter 提交 / Esc 取消）→ PATCH `/chat/conversations/{id}` body `{title}`（≤200）；成功 → 本地更新 title + ok toast「已重命名」；失败 → err toast。

### 4.3 验收补充

- N7：AI 对话卡片展示会话 title（为空回退 project_name）。
- N8：改名入口 → PATCH → 本地 title 更新 + ok toast；超 200 → err toast；失败 → err toast 且 title 不变。
- N9：点击卡片 title 匹配章节 → 跳对应章节页；匹配不到 → 跳全局 chat 页（`/writing?conversation_id=...`）。

## 5. #836 会话命名调整（会话列表 / 会话详情）

> 左侧导航「会话」入口、SessionBar 分组标题、会话详情按钮均叫「会话」——命名不清晰。

### 5.1 逻辑/文案补充

- `nav.sessions`（AppNav 左导航「会话」按钮，跳 `/sessions`）→ **「会话详情」** / "Session Detail"。
- `nav.group.sessions`（AppNav 左导航会话分组标题）→ **「会话」** / "Sessions"（#1016 键位拆分后仅 AppNav 消费；文案于 #1016 后续修正对调，见 §8）。
- `session.group.title`（SessionBar 栏内标题，新增键，见 §7）→ **「会话列表」** / "Session List"（与会话页 header 一致）。
- `sessions.title`（会话页 header）→ **「会话列表」** / "Session List"。

### 5.2 验收补充

- N10：左侧导航「会话」按钮显示「会话详情」、跳 /sessions；AppNav 会话分组标题（`nav-group-sessions`）显示「会话」；SessionBar 栏内标题（`session-bar-header`）与会话页 header 显示「会话列表」（#1016 拆分键位 + 文案对调，见 §7/§8）。zh/en 两端一致。

## 6. #1015 三类卡点击查看详情（详情弹层 + 归档只读贯通）

> 现象：访谈「已完成」卡与执行会话卡标题为裸 `<span>`，点击无响应；归档 AI 对话跳 `/writing?conversation_id=` 后因消息随线程级联软删而显示空对话、且输入区仍可编辑。三类卡「点击→详情」交互面不对称（仅 #770 给 AI 对话实现）。
> 用户拍板：决策点 1 = A（只读详情弹层，非独立路由页）。

### 6.1 详情弹层（访谈卡 + 执行会话卡）

- 访谈卡标题 `session-title-<planner.id>`、执行会话卡标题 `session-title-<session.id>` 由 `<span>` 改为 `<button>`（testid 不变，沿用 #770 AI 对话卡 `session-title-conv-<id>` button 先例）。点击 → 打开统一只读详情弹层 `SessionDetailDialog`。
- 弹层结构（模态，镜像 session-delete-dialog 的 fixed 遮罩 + z-50 形态）：
  - `session-detail-dialog`（role=dialog aria-modal）、`session-detail-title`（卡标题）、`session-detail-close`（关闭）。
  - 访谈（variant=pl）：懒加载 `GET /api/v1/agent/books/planner/{id}`（api/books.ts getPlannerSession 既有）→ 问答轮次列表 `session-detail-qa-<q.id>`（asked_questions × answers 逐对，未答显示占位）+ 确认项列表 `session-detail-confirmed-<key>`（key: value (source)）+ 写作计划行 `session-detail-writing-plan`（writing_plan_id 非空 → 「已生成写作计划」徽标 + plan id 文本；GUI 无独立 plan 查看页、后端无 GET writing-plans 端点，v1 不做导航）。
  - 执行（variant=ex）：session 元信息（状态/类型/项目/起止时间/result 摘要）+ 履历日志时间线，懒加载 `GET /api/v1/sessions/{id}/logs`（api/sessions.ts 新增 fetchSessionLogs）→ `session-detail-log-<seq>` 逐条（level + message + created_at）。归档会话（is_deleted=true）日志仍可见（后端 list_logs 不因归档过滤，履历保留契约）。**（#1029 增补）决策轨迹区块**：session.context 含 `agent_run_id` 键时追加，懒加载 `getRun(agent_run_id)`（`GET /api/v1/agent/runs/{id}`，ADR-056）→ `session-detail-trace-<index>` 轻量行（步骤序号 + 工具名 + 结果原文）+ `session-detail-trace-link`「查看执行详情」跳 `/writing`（run 的 chapter_id 非空时附 `?chapter_id=`；⚠️ 写作页当前不消费 chapter_id、默认落编辑器视图，故 v1 = 「跳转写作页，用户自行切换执行视图」，**直达 run 执行视图的深链列为后续增量**）；无该键 = 不渲染区块（存量会话降级，不报错）；run 不存在/加载失败 → `session-detail-trace-error` 占位文案（不崩溃）。
  - 数据加载中 `session-detail-loading`；加载失败 err 文案（不崩溃，可关闭）。
  - 归档态（is_deleted=true）：弹层底部渲染恢复按钮 `session-detail-restore`（复用 handleRestore / handleRestoreConversation 语义：成功本地置 is_deleted=false + ok toast，失败 err toast）；内容始终只读。
- 访谈卡状态不限（drafting/completed/declined 均可点开）；执行卡活动/归档均可点开。

### 6.2 归档 AI 对话只读加载（/writing?conversation_id=）

- 后端 `GET /api/v1/chat/messages` 新增 `include_deleted: bool = Query(False)`，透传 repo/service：True 时返回含已归档消息（归档线程级联软删其消息，chat_message_repo.archive_conversation 行为）。默认 False 保持既有「不含已归档」语义不变。
- 前端 ChatPanel 消费 URL `conversationId`（#840）时：以 `fetchChatConversations({ includeDeleted: true })` 本地按 conversation_id 查 meta（既有端点能力，无新 GET）→ `is_deleted=true` 判定归档会话：
  - 顶部渲染「已归档」提示横幅 `chat-archived-banner` + 恢复按钮 `chat-archived-restore`（POST restore 成功后本地刷新、横幅消失、解除只读）。
  - 历史加载改传 `fetchChatMessages(cid, 0, 50, { includeDeleted: true })`（仅归档会话时传，活动会话请求不带该参数）。
  - 只读模式：不渲染输入框 `chat-input` 与发送按钮 `chat-send`（归档=可看不可续聊；恢复后可聊）。

### 6.3 验收补充

- N11：点击访谈卡标题 → `session-detail-dialog` 出现，含问答轮次（session-detail-qa-*）与确认项（session-detail-confirmed-*），数据源 = planner GET 端点懒加载；关闭返回。
- N12：点击执行会话卡标题（活动态）→ 弹层含元信息 + 履历日志时间线（session-detail-log-*），数据源 = GET /sessions/{id}/logs 懒加载。
- N13：点击归档执行会话卡标题 → 弹层只读 + `session-detail-restore` 出现；点击恢复 → restore API 调用 + ok toast。
- N14：点击归档 AI 对话卡标题 → `/writing?conversation_id=<id>` 页 ChatPanel 渲染 `chat-archived-banner` + `chat-archived-restore`；消息历史请求带 include_deleted=true 且渲染归档消息；无 `chat-input`/`chat-send`（只读）。
- N15：活动 AI 对话行为不回归——消息请求不带 include_deleted 参数、输入/发送区正常渲染（护栏）。
- N16：弹层/横幅加载失败显示 err 文案不崩溃（mock reject）。
- N22（#1029）：执行会话 `context.agent_run_id` 非空 → 弹层渲染决策轨迹区块（`session-detail-trace-*` 逐步骤 + `session-detail-trace-link`），数据源 = `GET /agent/runs/{id}` 懒加载；点击跳转入口 → 导航到写作页（`/writing`，run 的 chapter_id 非空时 URL 含 `chapter_id`；⚠️ v1 不承诺直达执行视图，见 §6.1/ADR-056 D3）。
- N23（#1029）：**存量会话不回归**——`context` 无 `agent_run_id` 键 → 不渲染轨迹区块、不发起 run 请求、无错误提示，弹层维持 #1028 形态（元信息 + 履历日志）。
- N24（#1029）：`agent_run_id` 存在但 `getRun` 失败（404/网络）→ `session-detail-trace-error` 占位文案，弹层其余部分（元信息/日志）不受影响、不崩溃。

### 6.4 数据源裁定与关联建模（#1029 升级为正式决策）

| 项 | 内容 | 修改履历 |
|----|------|---------|
| v1 裁定（#1015） | issue 建议执行会话详情消费 `GET /agent/runs/{id}`（F27 轨迹）——源码实证 F24 sessions 与 F27 agent_runs 两表无关联（sessions.id=int PK→UUID(int=id)；agent_runs.id=uuid4 字符串；无外键/无映射字段，#379 同族），以其为详情源必 404。裁定：v1 执行会话详情 = 既有 sessions 详情 + logs 端点（元信息+履历），agentic 轨迹贯通另立 issue。 | 2026-09-09 首版（#1015 / PR #1028） |
| 关联建模（#1029） | **A（选定）= `sessions.context` 软锚**：执行发起方创建会话时把 run 锚写进 `sessions.context` JSON 的 `agent_run_id` 键（`sessions.context` 已是 `LenientJSON(fallback={})` 快照列 `models/session.py:90`，且已在 API 暴露 `SessionDto.context` `api/sessions.ts:18`）→ **零 schema 迁移、零 API 契约变更**。前端弹层检测到该键 → 追加「决策轨迹」区块，懒加载既有 `GET /api/v1/agent/runs/{id}`（`api/runs.ts:49` `getRun`）。软关联与 F24 §5.4b `session_logs.payload` 观测契约同族（JSON 快照承载跨域锚点）。 | 2026-09-10 #1029（ADR-056） |
| 发起点范围（#1029） | **只覆盖同时落 `sessions` 行与 `agent_runs` 行的执行**。当前三条编排路径（agentic 写作 `agentic_writer_service`、chat 流 `chat_stream`、F4 管线）**均不写 `sessions` 行** → 自动写锚无落点，v1 锚点写入端 = 调用方经 `POST /sessions` 的 `context` 字段自带（CLI `--context-json` / API body）；未来编排路径落 sessions 时复用同一键名契约（前端零改）。F4 管线不涉（独立 `agent_executions` 表，写作页执行视图已覆盖）。 | 2026-09-10 #1029（ADR-056） |
| 弹层呈现（#1029） | **轻量列表 + 跳转写作页**：弹层宽度受限（`max-w-lg`），**不复用** `ExecutionDetailPanel`（419 行完整渲染栈 + 轮询恢复逻辑，嵌入会挤压并带入 projectId 模式副作用）→ 弹层内渲染轻量轨迹列表（步骤序号 + 工具名 + 结果原文，testid `session-detail-trace-*`）+ `session-detail-trace-link` 跳 `/writing`（chapter_id 非空时附参）。⚠️ **核实边界**：写作页不消费 `chapter_id`（`writing.tsx:62` 仅读 `conversation_id`）、默认落编辑器视图、执行视图取 F4 `executionId` 而非 agentic `runId` → v1 语义 = 「跳转写作页（用户自行切换执行视图）」，**非**「直达该 run 执行视图」；深链列为后续增量。 | 2026-09-10 #1029（ADR-056，审查修正） |
| 决策记录 | 完整备选方案（B `agent_runs.session_id` 列 / C project_id+时间窗模糊匹配 / D 新建关联表）与拒绝理由 → ADR-056 `adr/architecture/ADR-056.md`。 | 2026-09-10 #1029 |

## 7. #1016 i18n 同名键冲突（会话分组标题）与重复键护栏

> 现象：v0.13.0-rc6 左导航「会话详情」上方分组标题显示**「会话」**，与 /sessions 页标题「会话列表」不一致。
> 根因：`nav.group.sessions` 一个键被两个文案需求共用——AppNav 分组标题（期望「会话列表」）与 SessionBar 栏内短头（期望「会话」）；
> 且该键在 `zh.ts`/`en.ts` 与 `session-ux.ts` 重复定义，`useI18n` 展开合并时 `sessionUxZh/En` 在后 → 静默覆盖（#762 拆 session-ux 域时撞键引入）。

### 7.1 逻辑/文案

- `nav.group.sessions`（zh.ts/en.ts）→ **仅 AppNav 分组标题**（`nav-group-sessions`）消费：**「会话」** / "Sessions"（§8 修正后）。
- `session.group.title`（session-ux.ts，新增键）→ SessionBar 栏内标题（`session-bar-header`）：**「会话列表」** / "Session List"，与会话页 header `sessions.title` 一致（§8 修正后）。
- `session-ux.ts` 删除重复定义的 `nav.group.sessions`（zh/en 两处）。

### 7.2 护栏（i18n 聚合重复键检测）

- `i18n.contract.test.ts` 新增契约：`useI18n` 聚合的全部来源字典（zh + 12 个域字典）**两两 key 交集必须为空**（zh 侧 / en 侧各一条断言）。同名键由展开顺序静默决定胜者，重复即 FAIL——根治「后写吞前写」整族问题。

### 7.3 验收补充

- N17/N18：**已被 §8.2 的 N20/N21 取代**（首版映射的验收项；文案对调拍板见 §8，勿再引用旧编号）。
- N19：i18n 跨域字典重复键断言零命中（zh/en 两侧）。

## 8. #1016 后续修正（2026-09-09 拍板）：分组标题与会话栏标题文案对调

> §7 落地（PR #1051 / merge 7d29505）后，用户看真实渲染截图指出**位置反了**：期望上方分组标题=**「会话」**、下方会话栏标题=**「会话列表」**（会话栏才是与 /sessions 页同名的「会话列表」）。

### 8.1 逻辑/文案（最终口径）

- `nav.group.sessions`（`zh.ts:10` / `en.ts:14`）= **「会话」** / "Sessions" → AppNav 分组标题（`nav-group-sessions`）。
- `session.group.title`（`session-ux.ts:6,15`）= **「会话列表」** / "Session List" → SessionBar 栏内标题（`session-bar-header`），与会话页 header `sessions.title` 一致。
- 键位拆分与消费方归属不变（AppNav→`nav.group.sessions`、SessionBar→`session.group.title`）；本次仅**对调两侧文案值**（组件零改动）。

### 8.2 验收（取代 N17/N18）

- N20：AppNav `nav-group-sessions` = 「会话」/ "Sessions"。
- N21：SessionBar `session-bar-header` = 「会话列表」/ "Session List"（与会话页 header 一致）。
- N19 重复键护栏不变（零命中）。
