# 设定库·大纲 — 交互规格

> 页面: outline | 路由: /library?cat=outline | 组件: pages/library.tsx（cat=outline）+ OutlineTree + outline-dialogs（PlotPointDialog / ArcDialog / GenerateOutlineDialog / ChapterLinkDialog）+ LibraryCreateDialog（cat=outline）
> 对应 design/GUI/outline/（官方简图 outline.html + outline-<state>.png，见后续补图）

## 1. 画面样式

- 原型引用：design/GUI/outline/
> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：设定库（页面标题）  主题 Select  语言 Select  窗口控制 │
├──────────────────────────────────────────────────────────────┤
│ 标题区：设定库（font-serif 26px）                            │
│ [项目选择器 青云志 ▾]  面包屑：设定库 · 青云志 / 大纲        │
├──────────────────────────────────────────────────────────────┤
│ 分类 tab：角色│世界观│大纲│时间线│伏笔│知识图谱              │
├──────────────────────────────────────────────────────────────┤
│ 卡片工具栏：[＋整本]（仅无整体时）  [AI 生成大纲]            │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ 三级树（缩进 + toggle + 级别徽标 + 名称 + 层级动作按钮） │ │
│ │   ├─ [整体] 青云志·全书                 ＋卷             │ │
│ │   │  ├─ [卷] 第一卷·入青云              ＋章             │ │
│ │   │  │  ├─ [章] 第12章 剑心蒙尘 [已关联章节] ＋情节点    │ │
│ │   │  │  │     情节点：夜访剑冢[事件]  断剑于山门[转折]   │ │
│ │   │  │  └─ [章] 第13章 断剑 [关联章节]    ＋情节点       │ │
│ │   │  └─ [卷] 第二卷·山门风波            ＋章             │ │
│ │ 悬停行操作 [编辑][删除]；章行未关联=虚线[关联章节]按钮   │ │
│ │ 故事弧区（卡片底 border-t）：[＋新建故事弧]              │ │
│ │   剑心蒙尘 [3]  下山历练 [5]  剑冢秘辛 [2]               │ │
│ └──────────────────────────────────────────────────────────┘ │
│ 弹层：情节点 460px / 故事弧 460px / AI 生成 520px / 章关联   │
└──────────────────────────────────────────────────────────────┘
```
- 参考锚点（真实实现）：
  - 端点：GET /api/v1/projects/{pid}/outlines；PATCH /api/v1/outlines/{id}（含 chapter_id）；GET /outlines/{id}/plot-points（情节点按需拉取）；POST /outlines/{id}/plot-points；PATCH /plot-points/{id}（仅变化字段）；DELETE /plot-points/{id}；GET/POST /projects/{pid}/story-arcs；PATCH/DELETE /story-arcs/{id}；POST /outlines/generate（{project_id, save:true}）；GET /projects/{pid}/chapters（章标题映射，library.tsx 装配 chapterTitles）
  - 顶部工具栏（卡片头 border-b）：＋整本（outline-add-overall，仅无 overall 条目时渲染）+ AI 生成大纲（library-ai-generate：Wand2 图标 +「AI 生成大纲」；进行中 Loader2 旋转 + disabled）
  - 三级树（outline-tree，divide-y）：节点行 = toggle（outline-toggle-<id>，仅子节点渲染）+ 级别徽标（整体/卷/章，surface-3 胶囊，lib.level.*）+ 名称（flex-1 truncate）+ 章行附加：📎 章关联徽标（outline-chapter-ref-<id>，title「已关联写作章节，点击可在写作页打开」）或「关联章节」虚线按钮（outline-chapter-link-<id>，border-dashed accent）+ 层级动作按钮（overall 行「＋卷」outline-add-volume / volume 行「＋章」outline-add-chapter / chapter 行「＋情节点」outline-add-point）+ 悬停编辑（lib-edit）/删除（lib-delete）；行缩进 depth*18+12
  - 情节点区（章展开内，padding 下一级）：行 = 名称 + 类型徽标（surface-3 小胶囊）+ 悬停编辑（outline-point-edit）/删除（outline-point-del）；空 → 「暂无情节点」（lib.empty.points）；首次展开按需拉取 + 本地缓存（fetchedRef，收起再展开不重拉）
  - 故事弧面板（outline-arcs，卡片底部 border-t）：标题「故事弧」（font-serif 15px）+ ＋新建故事弧（outline-arc-create）+ 弧行（名称 + point_count 徽标 + 悬停编辑 outline-arc-edit / 删除 outline-arc-del）；空态「暂无故事弧」
  - 对话框（DialogShell 统一外壳，遮罩弹层）：
    - 情节点（outline-point-dialog，460px）：情节点名称（必填 gate）/ 类型 / 描述 / 故事弧下拉（「（不挂弧线）」+ 弧列表）
    - 故事弧（outline-arc-dialog，460px）：弧线名称（必填）/ 弧线描述
    - AI 生成（outline-generate-dialog，520px）：大纲名称（可选）/ 生成提示（可选）；进行中渲染 outline-generate-loading 区块（阶段 + 已生成条目数）
    - 章节关联（chapter-link-dialog，420px）：章标题列表（chapter-link-option-<id>，点击即选，saving 中禁用）
- 布局说明：单卡片 = 工具栏 → 三级树 → 故事弧区；情节点嵌在章行展开区内；对话框挂根部；创建大纲对话框由树内入口打开（预填 level/parent_id），工具栏无独立「去创建」按钮

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| ＋整本（outline-add-overall） | 仅无 overall 时显示 | 打开创建对话框（level=overall，parent=null） | saving | 新整体入树 | err toast | 已有整体不渲染（整体单例） |
| ＋卷 / ＋章（outline-add-volume / -chapter） | 层级行内描边按钮 | 打开创建对话框（预填 level + parent_id） | saving | 子节点入树 + 展开可见 | err toast | overall 行仅「＋卷」；volume 行仅「＋章」；创建对话框 level 选项按上下文限制 |
| ＋情节点（outline-add-point） | 章行按钮 | 打开 PlotPointDialog（outlineId 绑定） | saving 禁用 | POST → 该章情节点强制刷新（新点入树） | err toast | 名称必填 gate；arc 可选不挂弧线 |
| AI 生成大纲（library-ai-generate） | 工具栏按钮 | 打开 GenerateOutlineDialog | generating：按钮 Loader2 旋转禁用 + 对话框 loading 区块（outline-generate-loading / -stage / -count） | toast「大纲已生成」+ 新大纲插树顶（onOutlineGenerated）+ 情节点/弧线本地回填 | err toast | name/prompt 均可选；save:true 直写；生成中禁重复提交；回填按 id 去重防双写 |
| 章关联（outline-chapter-link） | 未关联章行虚线按钮 | 打开 ChapterLinkDialog（章标题列表） | chapterSaving：选项禁用 | PATCH chapter_id → 行内即时显示 📎 徽标（本地回写 chapterRefs） | err toast | 已关联 → 徽标 + title 提示；章列表空 → 无选项 |
| 情节点编辑/删除 | 悬停显现 | 编辑 → PlotPointDialog 预填（PATCH 仅变化字段）/ 删除 → ConfirmDialog（outline-point-confirm） | saving | 该章情节点强制刷新 | err toast | 删除真删；编辑无变化字段不请求 |
| 故事弧 CRUD | ＋新建 / 行内编辑/删除 | ArcDialog（名称必填）/ ConfirmDialog（outline-arc-confirm） | saving | 本地回写列表（不整表重拉）；删除本地移除 | err toast | point_count 徽标后端聚合；删除真删 |
| 树 toggle（outline-toggle） | 展开态 | 收起/展开 | 情节点按需拉取（仅展开且 point_count>0 时触发） | 情节点区渲染 | 拉取失败 → 该章空列表 + err toast | 本地缓存：收起再展开不重拉（O8 契约） |
| 创建/编辑大纲对话框 | 层级 select（随上下文限选项）+ 名称必填 + 描述 | 保存 | saving「保存中…」 | POST/PATCH → 关框 + 树刷新 | err toast | ESC/取消关闭；遮罩点击不关闭；level 缺失按 overall 兜底 |

## 3. 验收

- N1：三级树建树（整体 → 卷 → 章）+ 孤儿降级顶层 + 未知 level 按整体兜底
- N2：各层新增入口（＋整本/＋卷/＋章/＋情节点）预填层级上下文
- N3：情节点按需拉取 + 本地缓存 + 行内编辑/删除（PATCH 仅变化字段）
- N4：章关联选择器 → 📎 徽标即时显示（#676 解除占位）
- N5：故事弧 CRUD + AI 生成大纲（loading 反馈 + 树顶插入 + 情节点/弧线回填）
