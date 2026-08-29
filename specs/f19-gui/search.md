# 检索页 — 交互规格

> 页面: search | 路由: /search | 组件: frontend/packages/renderer/src/pages/search.tsx（SearchPage，nav 项 search，lucide Search 图标）
> 对应 design/GUI/search/（官方简图 search.html + search-<state>.png，见后续补图；当前目录仅 .gitkeep 占位）

## 1. 画面样式

- 原型引用：design/GUI/search/search.html + search-<state>.png（后续补图，目录已建）
- 参考锚点（以真实组件 pages/search.tsx 为准，#480 RAG embedding 增强检索 + #657 索引维护）：
  - 页面骨架：max-w-[1080px] 居中容器，标题「检索」（font-serif 26px）+ 副标题「基于 RAG embedding 的语义/关键词检索」
  - 检索表单：检索模式 Select / 项目 Select / 检索输入框 / 「检索」按钮，flex-wrap 一行排布（gap-4）
  - 无项目空态：Search 图标 + 「请先创建或选择项目」+「前往项目页」按钮（跳 /projects），不发检索请求
  - 结果列表：「共 {total} 条结果」摘要 + 命中卡片（entity_type 徽标 / score 右对齐 / title / snippet）
  - 命中跳转：章节 → /writing 并选中章节；角色/世界观/大纲/时间线/伏笔 → /library?cat=<对应 tab>
  - 索引维护卡片：项目范围 Select（当前项目/全部项目）+ 索引类型 Select（两者/仅全文/仅向量）+「重建索引」按钮 + 确认弹窗 + 三态反馈（进行中/完成/失败）
- 布局说明：
  - 顶部：h1 + 副标题
  - 检索区（mt-6）：模式 Select（w-32）→ 项目 Select（w-56）→ 输入框（max-w-xs 弹性）→ 检索按钮
  - 索引维护卡（mt-8）：标题 + 描述 + 双 Select 行 + 重建按钮 + 反馈块（loading/ok/err 三态）
  - 结果区（mt-8）：loading / error / results / empty 四态互斥展示

## 2. 动作样式（按钮 × 状态表，逐控件）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 检索按钮（search-btn） | accent 实心「检索」 | 提交表单 handleSearch | 结果区显示「检索中…」块（按钮本身不禁用） | 结果列表 / 空态「未找到相关内容」 | 「检索失败，请重试：{原因}」错误块 | q strip 后为空 / 未选项目 → 不发请求；无防抖，进行中可重复点击并发 |
| 检索模式 Select（search-mode-select） | 默认「语义」 | 展开选项「语义/关键词」 | — | 选择即生效，作为下次检索参数 mode | — | 选项仅 semantic/keyword 二值 |
| 项目 Select（search-project-select） | 默认当前项目 | 展开项目列表（project store） | — | 选择即生效，作为下次检索参数 projectId | — | 未选项目 → placeholder「选择项目」且检索不发请求 |
| 命中卡片（search-hit） | 卡片可点（hover bg-surface-3） | 按 entity_type 跳转 | — | 路由切换 | — | chapter → /writing + selectChapter；character/world/outline/timeline/foreshadow → /library?cat=…；未知类型 → 无操作 |
| 重建索引按钮（rebuild-btn） | accent「重建索引」 | 打开确认弹窗（不直接发请求） | disabled（confirmOpen 或 running 时 opacity-60） | 进入轮询反馈 | — | 弹窗打开期间禁用防重复 |
| 确认弹窗（rebuild-confirm-dialog） | 标题「确认重建索引？」+ API 费用提示 +「取消/确定重建」 | 确定 → postIndexRebuild；取消 → 关闭 | — | 启动任务 + 立即查一次 + 每 2s 轮询 | 请求失败 → 页面内 err 块（后端缺席 404 不炸 UI） | 范围=当前项目且已选 → project_ids=[currentProjectId]；全部项目/未选 → null（后端默认全部）；Esc 关闭，遮罩点击不关闭 |
| 轮询反馈（rebuild-loading） | 不渲染 | — | spinner + 「正在重建索引… · 步骤（全文/向量） · 进度 {done}/{total} 项目」 | status=done → 停止轮询，绿块「索引重建完成 · rebuilt_at · {n} 个项目」 | status=failed 或单次轮询异常 → 停止轮询，红块「索引重建失败：{原因}」 | 组件卸载 clearInterval；done/failed 均停止轮询；单次轮询异常不保持 loading |
| 索引范围/类型 Select | 默认「当前项目」「两者」 | 展开选项 | — | 选择即生效，决定重建参数 | — | 范围：current/all；类型：both/fulltext/vector |

## 3. 验收

- N1：无项目空态渲染「请先创建或选择项目」+ 前往项目页按钮，且不发起任何检索请求
- N2：输入查询 → 点检索 → 结果列表展示 total + 命中卡片（徽标/score/title/snippet）；q strip 为空或未选项目不发请求
- N3：检索四态互斥：loading「检索中…」/ error「检索失败，请重试：{原因}」/ 结果列表 / 空态（total=0）
- N4：命中卡片跳转映射：chapter → /writing + selectChapter；角色/世界观/大纲/时间线/伏笔 → /library?cat=…；未知类型无操作
- N5：索引维护卡齐全（范围/类型/重建按钮），默认「当前项目」+「两者」；点重建先出确认弹窗（含 API 费用提示），确定才发请求
- N6：重建三态闭环：running 轮询（2s 间隔，spinner+步骤+进度）→ done 绿块（rebuilt_at + 项目数）/ failed 红块（原因）；轮询异常或 404 落入 err 块且页面其余交互不受影响
- N7：参数映射：范围=当前项目且已选项目 → project_ids=[id]；全部项目/未选 → null；索引类型 both/fulltext/vector 直传
