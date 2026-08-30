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
