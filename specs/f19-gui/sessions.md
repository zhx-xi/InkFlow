# 会话页 — 交互规格

> 页面: sessions | 路由: /sessions | 组件: frontend/packages/renderer/src/pages/sessions.tsx（SessionsPage，nav 项 sessions，lucide History 图标）
> 对应 design/GUI/sessions/（官方简图 sessions.html + sessions-<state>.png，见后续补图；当前目录仅 .gitkeep 占位）

## 1. 画面样式

- 原型引用：design/GUI/sessions/sessions.html + sessions-<state>.png（后续补图，目录已建）
- 参考锚点（以真实组件 pages/sessions.tsx 为准，#725 统一窗口重构 + #547/#581 AI 对话聚合 + #566 真删）：
  - 页面骨架：max-w-[1080px] 居中容器，标题「会话」
  - 顶部工具条（与会话目录同栏）：项目选择器 + 检索框（本地过滤，不重拉）
  - filter chips：全部 / 活动 / 已归档（aria-pressed 高亮，本地过滤）
  - 统一目录（session-directory）：执行会话 / 访谈会话 / AI 对话三类卡片合并，按 updated_at 倒序，类型徽标区分
  - 卡片行内：类型徽标（执行/访谈/AI 对话）+ 状态徽标（进行中/已暂停/已完成/失败 或 访谈中/已完成/已跳过）+ 已归档徽标 + 标题 + 操作按钮（归档/恢复/删除）
  - 删除确认对话框：固定遮罩 + 「删除会话？」+ 永久删除提示 +「取消/确定删除」
  - 空态：「暂无会话」（三类数据全部落定前也显示该空态容器）
- 布局说明：
  - 顶部：h1「会话」
  - 工具条（mt-5）：项目 Select（w-56）→ 检索框（min-w-[220px] flex-1，placeholder「搜索会话标题 / 项目 / 最后消息…」）
  - chips 行（mt-3）：全部/活动/已归档
  - 目录（mt-6）：卡片列表 space-y-3，每卡 p-4 圆角边框；访谈卡只读（无操作按钮），执行卡与 AI 对话卡有归档/恢复/删除
  - 删除确认：z-50 遮罩弹窗，居中 max-w-sm

## 2. 动作样式（按钮 × 状态表，逐控件）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 项目选择器（sessions-project-select） | 当前项目名（无则 placeholder「当前项目」） | 展开项目列表 | — | selectProject → 目录按项目重过滤（前端过滤不重拉） | — | 路由直入且未选项目 → 自动回退首个项目（仅一次，不覆盖用户已选） |
| 检索框（sessions-search） | 空输入，placeholder 提示 | 输入即过滤 | — | 目录按 标题/项目名/最后消息 本地过滤（trim + 小写） | — | 纯本地过滤不重拉接口；与 filter chips 叠加生效 |
| filter chips（全部/活动/已归档） | 「全部」高亮（aria-pressed） | 切换过滤条件 | — | 目录切换：已归档 → 仅 is_deleted；活动 → 仅非 is_deleted；全部 → 不过滤 | — | 本地过滤不重拉（归档回归由测试锁定）；与检索框叠加 |
| 归档按钮（session-archive / chat-conv-archive） | 活动态卡片显示，outline 样式 | archiveSession(id) / archiveChatConversation(id) | — | 本地置 is_deleted=true → 卡片转归档态 + ok toast「已归档」 | err toast「原因」 | 仅活动态渲染；归档态不显示归档按钮 |
| 恢复按钮（session-restore / chat-conv-restore） | 归档态卡片显示 | restoreSession(id) / restoreChatConversation(id) | — | 本地置 is_deleted=false → 卡片回活动态 + ok toast「已恢复」 | err toast「原因」 | 仅归档态渲染；恢复后归档徽标消失 |
| 删除按钮（session-delete / chat-conv-delete） | 所有卡片显示，hover 变红 | 打开删除确认对话框（受控 deleteTarget） | — | — | — | 仅打开对话框，不发删除请求 |
| 删除确认「取消」（session-delete-cancel） | 对话框内次按钮 | 关闭对话框 | — | 卡片不变 | — | 不调任何 API |
| 删除确认「确定删除」（session-delete-confirm） | 对话框内主按钮（accent） | deleteSession(id) / deleteChatConversation(id)（force 真删） | — | 卡片从目录移除 + ok toast「已删除」 | err toast「原因」 | 描述「此操作将永久删除会话，不可恢复」；删除后不可撤销 |
| 访谈卡片 | 只读：访谈徽标 + 状态 +「已确认 {n} 项」+ 标题 + 可选「已生成写作计划」徽标 | 无操作按钮 | — | — | — | 无归档/恢复/删除入口 |

## 3. 验收

- N1：统一目录合并三类会话（执行/访谈/AI 对话），类型徽标区分，按 updated_at 倒序；三类数据全部落定后才渲染卡片（无部分闪现）
- N2：项目选择器切换 → 目录仅显示该项目会话；未选项目时自动回退首个项目（仅一次）
- N3：filter chips 本地过滤不重拉：已归档只显示归档态、活动只显示活动态、全部不过滤；归档会话在「已归档」chip 下可见（归档回归）
- N4：检索框按 标题/项目名/最后消息 过滤，与 chips 叠加，无网络请求
- N5：执行会话与 AI 对话归档/恢复闭环：活动态可归档（ok toast）→ 归档态显示「已归档」徽标 + 恢复按钮 → 恢复后回活动态；失败均 err toast 且列表状态不变
- N6：删除需经确认对话框（含永久删除提示）；确定 → 卡片移除 + ok toast「已删除」；取消 → 无副作用
