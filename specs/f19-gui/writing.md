# 写作页 — 交互规格

> 页面: writing | 路由: /writing | 组件: pages/writing.tsx
> 对应 design/GUI/writing/（官方简图 writing.html + writing-<state>.png，见后续补图）

## 1. 画面样式（简图/原型）

- 原型引用：design/GUI/writing/writing.html + writing-<state>.png（三栏布局 / 骨架加载 / 流式生成中 / 右栏折叠 / 无项目空态等状态截图）

> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：写作（页面标题）   主题 Select   语言 Select   窗口控制   │
├──────────┬────────────────────────────────┬──────────────────┤
│ 项目树    │ 编辑器（ChapterEditor）         │ 上下文注入         │
│ 项目印章  │ 工具栏：撤销/重做/保存/续写/生成 │ ContextPanel       │
│ 卷章树   │ /审计/风格检测/执行详情/全自动/   │ 写作要求/大纲/     │
│ 卷/章 CRUD│ AI 提取                        │ 角色/世界观/伏笔   │
│ 拖拽移动  │ 章节标题 + 正文编辑区           │ （勾选注入/已裁剪） │
│ +新建卷  │ ────────────────────────────── │ ───────────────── │
│ +新建章节 │ AI 对话（ChatPanel）            │ 章节摘要           │
│          │ 消息区 + 输入框 + 发送/停止      │ ChapterSummary    │
│          │ 删除授权：[手动][一次确认][全自动]│ （刷新摘要）       │
│          │  └─ 弹窗：确认删除「角色名」？   │                   │
│          │                                │                   │
├──────────┴────────────────────────────────┴──────────────────┤
│ 状态栏 StatusBar：内核连接态 / 模型 / 字数 / 自动保存时间      │
└──────────────────────────────────────────────────────────────┘
```
- 参考锚点（以真实组件为准：pages/writing.tsx + components/ProjectTree、EditorToolbar、ContextPanel、ChatPanel、ChatDeleteAuthControl、StatusBar、ChapterSummaryPanel、AuditDialog、StyleAnalyzeDialog、AIExtractDialog、AutoAuthorizationDialog）：
  - 布局：全高 flex 三栏 — 左项目树（aside project-tree）/ 中编辑器区（main）/ 右上下文栏（aside right-rail）
  - 左栏：默认宽 208px（treeWidth 受控），col-resize 拖拽 160~360px（ProjectTree RESIZE_MIN/MAX）；卷章树加载中显示骨架屏（头像/标题/6 行 Skeleton）；顶部 ProjectSeal 项目印章
  - 中栏：EditorToolbar 默认 opacity 0.35、hover 编辑器区域 group-hover 全显；下方 ChapterEditor（正文编辑）或 ExecutionDetailPanel（执行详情，视图切换）；底部 ChatPanel 对话区（含 ChatDeleteAuthControl 删除授权三态分段控件，HITL 弹窗打开期间控件禁用）
  - 右栏：默认 240px（railWidth），col-resize 90~540px；整栏可折叠为 26px 展开条（按钮 right-col-toggle）；内含 ContextPanel（写作要求/大纲/角色/世界观/伏笔卡片，数据来自设定库 assemble）+ row-resize 手柄 + ChapterSummaryPanel，面板高度各自 90~540px
  - 空态：无任何项目 → WritingEmptyState（Compass 图标 + 文案 + 「返回项目页」按钮 navigate('/projects')）
  - 流式时序：续写/生成 → ensureModelReady 前置校验（未配置 warn toast「模型未配置」不启动）→ 创建 chat 会话（失败静默降级）→ start(mode) → SSE 流式（status=running）→ done 帧 finalOutput 落章（setContent）+ 归档 AI chat 消息；error 帧展示错误
  - 状态栏 StatusBar（只读）：内核连接态 / 模型 / 字数 / 自动保存时间
- 布局说明：写作页为全高三栏卡片式工作区，左栏卷章树负责导航与管理（卷/章 CRUD + 拖拽移动），中栏为编辑主区（工具栏 + 正文 + 对话），右栏为上下文辅助区（设定上下文 + 章节摘要）。三栏均可拖拽调尺寸，右栏可整体折叠为窄条，适配沉浸写作。

## 2. 动作样式（按钮 × 状态表，逐控件）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 工具栏 撤销/重做/保存 | 图标按钮，整栏 opacity 0.35 hover 全显 | 点击执行 undo/redo/save | 无独立 loading（保存异步） | 保存成功 → 状态栏自动保存时间更新 | 保存失败 toast | 快捷键 Ctrl+Z / Ctrl+Y / Ctrl+S（document.execCommand）；生成中不禁用 |
| 续写/生成 | Wand2/Sparkles 图标按钮 | startWithCheck：ensureModelReady 未配置 → warn toast 不启动；通过后建会话再 start | 生成中（status=running）两者 disabled(opacity 40)，Sparkles animate-pulse text-accent | done → finalOutput 落章 + 状态 success + AI 消息归档 | error 帧 → error 状态展示 | 快捷键 Ctrl+Enter 续写 / Ctrl+Shift+Enter 生成；生成中禁用防并发流 |
| 章节审计 | ScanSearch 图标 | 打开 AuditDialog 并拉取报告 | 弹窗内 loading | 报告展示 + accept/reject 确认（note 备注） | 拉取失败 → 弹窗内 error 展示 | 无项目/无当前章时 handleAudit 直接 return |
| 风格分析 | Gauge 图标 | 打开 StyleAnalyzeDialog 并拉取报告 | 弹窗内 loading | 风格报告展示 | 失败 → 弹窗内 error | 同上守卫 |
| 视图切换 | Eye 图标 | editor ↔ detail 切换 | — | 正文区 ↔ ExecutionDetailPanel 互换 | — | aria-label/title 随视图变化；detail 态不渲染 ChatPanel |
| 全自动开关 | Zap 图标 aria-pressed=auto_write_enabled | toggle 项目 config.auto_write_enabled → updateConfig PATCH | PATCH 在途（即改即存） | 图标 pressed 态更新 | 失败 toast（store 内） | 无当前项目时 onToggleAuto 不动作 |
| AI 提取 | FileSearch 图标 | 打开 AIExtractDialog | 弹窗内提取中 | 提取内容入章 | 失败 toast | 仅 onExtract 传入时渲染该图标 |
| 自动保存 | 编辑置 dirty | 输入停止 2s 防抖 → saveContent | 防抖窗口内 | 成功 savedAt 更新（状态栏） | 失败 toast | SSE done 帧落章不触发防抖；隐藏窗口/卸载时 flush |
| 章节选择/新建 | 树节点点击 / 底部「+ 新建章节」 | 点击 selectChapter 载入编辑器；新建展开 inline 输入行（可先选目标卷）Enter/✓ 提交 | 卷章树首次加载骨架屏 | 新章节出现于树 + 编辑器加载 | 错误 toast（store 内） | Esc 取消；标题空 → 默认「新章节」 |
| 章节重命名/删除 | hover 显示 Pencil/Trash2（opacity 0→1） | 行内 input（Enter 提交 / Esc 取消）；删除 → ConfirmDialog 二次确认 | — | 标题更新 / 章节移除 | — | 重命名空串或未变更 → 跳过不 PATCH |
| 卷新建/重命名/删除 | 「+ 新建卷」/ hover Pencil/Trash2 | 同章节 inline 模式；删除 → VolumeDeleteDialog（章节数 + 其他卷迁移选项） | — | 卷创建/更名/删除（含章节迁移） | — | Esc 取消；标题空 → 默认「新卷」 |
| 章节拖拽移动 | 章节行 draggable（effectAllowed=move） | 拖到卷区/未分组区 drop → moveChapter | 拖经卷高亮 ring-accent | 树内章节归属更新 | — | 数据经 dataTransfer text/plain 传递 |
| 左栏宽度拖拽 | col-resize 手柄（tree-resize-handle） | mousedown 拖拽调宽 | — | 宽度 160~360px 实时更新 | — | 拖拽中 body userSelect 锁定；mouseup 结束 |
| 右栏折叠/调宽/调高 | 折叠按钮 right-col-toggle + col-resize 手柄 + row-resize 手柄 | 折叠 → 26px 展开条（PanelLeftOpen+展开 文案），再点展开恢复 | — | 宽度 90~540px / 面板高度 90~540px 实时更新 | — | 折叠态隐藏两面板与全部手柄 |
| ChatPanel 发送/停止 | 输入框 + 发送按钮（chat-send） | 发送 → streamChat 流式对话 | streaming 中发送按钮替换为「停止」（chat-interrupt，方块图标） | done → AI 消息落地 + 意图解析（onDone） | error → 错误文案不插入正文 | in-flight 再发不触发第二次流；停止 → abortChatRun(run_id) + 本地 abort 保留已生成前文；卸载 abort 清理 |
| 删除授权三态分段控件 | 三按钮（delete-mode-manual/ask-once/auto，默认 manual 选中 data-selected=true） | 点击切换 → updateChatDeletePermission(conversationId, mode) PATCH | PATCH 在途 | 选中态切换 + PATCH 生效 | 失败静默（本地选中保留，服务端不变） | conversation 缺失先 createChatConversation 再 PATCH；HITL 弹窗打开期间三按钮 disabled |
| HITL 删除确认弹窗 | interrupt SSE 帧到达 → 渲染（delete-confirm-dialog，实体名 + confirmTitle） | 点确认删除（delete-confirm-approve）→ resumeChatRun({conversation_id, approved:true})；点取消（delete-confirm-cancel）→ approved:false | — | 弹窗关闭 + resume 续跑 | resume 失败静默（弹窗关闭） | 弹窗打开期间分段控件禁用；取消不删除（approved:false 拒绝续跑） |
| 无项目空态按钮 | 「返回项目页」 | navigate('/projects') | — | 路由切换 | — | 仅无项目分支渲染（writing-empty） |

## 3. 验收

- N1：无项目进入写作页 → 空态引导（Compass + 返回项目页）；有项目 → 三栏布局 + 卷章树骨架加载后正常渲染
- N2：工具栏默认 opacity 0.35、hover 编辑器区域全显；Ctrl+Z / Ctrl+Y / Ctrl+S / Ctrl+Enter / Ctrl+Shift+Enter 五组快捷键生效
- N3：续写/生成四触发点（工具栏按钮×2 + 快捷键×2）共享模型未配置守卫：未配置 → warn toast 且不启动生成
- N4：生成中续写/生成禁用 + Sparkles 脉冲动画；SSE 停止按钮仅流式中出现，停止后保留已生成前文
- N5：章节/卷 CRUD（新建/重命名/删除确认）与章节拖拽移动完整可用；左栏 160~360px / 右栏 90~540px 可折叠 26px / 面板高度拖拽均生效
- N6：自动保存 2s 防抖落盘 + 状态栏自动保存时间更新；SSE done 帧落章不触发防抖保存
- N7：删除授权三态分段控件（delete-mode-manual/ask-once/auto）渲染三按钮，默认 manual 选中（data-selected=true / aria-pressed）；点击一次确认/全自动 → updateChatDeletePermission(conversationId, mode) PATCH 生效；conversation 缺失先建再 PATCH
- N8：interrupt SSE 帧到达 → HITL 确认弹窗（delete-confirm-dialog 显示实体名 + confirmTitle）；点确认删除 → resumeChatRun({approved:true}) 续跑删除；点取消 → {approved:false} 拒绝不删除；弹窗打开期间分段控件 disabled

## 4. #770 会话页架构增量

> 无章节写作页由「空」改全局 chat 页；章节内 chat 与全局 chat 页两套视图；会话跟随章节 + 命名/改名。完整契约见 f47 §17。

### 4.1 画面样式补充（场景 A：无章节 → 全局 chat 页）
> 低保真排版示意简图（区块+标签，非精确像素；#770 两套视图，完整契约见 f47 §17.4）

```text
场景 A：无章节选中 → 全局 chat 页（始终占满中栏、不可调节大小）
┌──────────┬────────────────────────────────────────────┐
│ 项目树    │  全局 ChatPanel（variant="full"）            │
│ 项目印章  │  ┌──────────────────────────────────────┐  │
│ 卷章树    │  │  消息区（flex-1 占满，无 resize handle） │  │
│ +新建卷   │  │  [user] 帮我看看第12章氛围              │  │
│ +新建章节 │  │  [ai]   第12章的雨夜可以更……            │  │
│          │  │  …                                      │  │
│          │  └──────────────────────────────────────┘  │
│          │  ┌──────────────────────────────────────┐  │
│          │  │  输入框                 [发送]/[停止]  │  │
│          │  └──────────────────────────────────────┘  │
│          │  （不渲染 EditorToolbar / ChapterEditor）    │
│ 右栏      │  ← 右栏 right-rail 保持                   │
│ 上下文注入│                                            │
├──────────┴────────────────────────────────────────────┤
│ 状态栏 StatusBar                                      │
└───────────────────────────────────────────────────────┘

场景 B：章节选中 → 章节内 chat（底部横栏、可调大小）
┌──────────┬────────────────────────┬──────────────────┐
│ 项目树    │  EditorToolbar          │  上下文注入        │
│ 卷章树    │  ─────────────────────  │  ContextPanel     │
│          │  ChapterEditor（正文）    │  ───────────────── │
│          │  ─────────────────────  │  章节摘要           │
│          │  ChatPanel（inline）      │  ChapterSummary   │
│          │  ⌃ resize handle         │                    │
│          │  消息区（80~480px 可调）  │                    │
│          │  输入框 + [发送]/[停止]   │                    │
├──────────┴────────────────────────┴──────────────────┤
│ 状态栏 StatusBar                                      │
└───────────────────────────────────────────────────────┘
```


- `currentChapterId === null`（有项目）时，中栏渲染全局 ChatPanel（`data-testid="global-chat"`，`variant="full"`）：
  - flex-1 占满中栏，**无 resize handle**（不可调节大小）
  - 不渲染 `EditorToolbar` / `ChapterEditor` / `ExecutionDetailPanel`
  - 左栏项目树、右栏 `right-rail` 均保持
- 与场景 B（章节选中）区别：章节内 ChatPanel 为底部横栏 inline（resize handle 80~480px）。两套视图条件分支渲染，不共享同一布局组件硬编码。

### 4.2 动作样式补充

- 章节内 chat 对话/生成/续写 → 新建会话 title=章节名；全局 chat 页对话 → 新建会话 title=首条用户消息前 30 字；均支持改名（PATCH ≤200 字符）。

### 4.3 验收补充

- N9：无章节进入写作页（有项目）→ 中栏渲染全局 chat 页（global-chat，无 resize handle），不渲染 EditorToolbar/ChapterEditor；右栏保持。
- N10：章节选中 → 章节内 ChatPanel（inline，resize handle）完整保留。
- N11：章节内对话/生成/续写均创建新会话，title=章节名；全局 chat 页对话 title=首条用户消息前 30 字；会话可改名。
