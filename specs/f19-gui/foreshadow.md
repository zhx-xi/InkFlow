# 设定库·伏笔 — 交互规格

> 页面: foreshadow | 路由: /library?cat=foreshadow | 组件: pages/library.tsx（cat=foreshadow）+ LibraryItemList（无角色扩展）+ LibraryCreateDialog（cat=foreshadow）
> 对应 design/GUI/foreshadow/（官方简图 foreshadow.html + foreshadow-<state>.png，见后续补图）

## 1. 画面样式

- 原型引用：design/GUI/foreshadow/
> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：设定库（页面标题）  主题 Select  语言 Select  窗口控制 │
├──────────────────────────────────────────────────────────────┤
│ 标题区：设定库（font-serif 26px）                            │
│ [项目选择器 青云志 ▾]  面包屑：设定库 · 青云志 / 伏笔        │
├──────────────────────────────────────────────────────────────┤
│ 分类 tab：角色│世界观│大纲│时间线│伏笔│知识图谱              │
├──────────────────────────────────────────────────────────────┤
│ 工具栏（右缘）：[去创建]  [AI 提取（类型=伏笔）]             │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ 平铺列表：标题 + 状态徽标 + 优先级 + 位置                │ │
│ │   师父闭关的真相  [未回收] 优先级 90  第11章·闭关        │ │
│ │   断剑的秘密      [未回收] 优先级 75  第13章·山门        │ │
│ │   林晚照的旧玉佩  [已回收] 优先级 40  第8章·初见         │ │
│ │ 行悬停显现 [编辑][删除]（D12）                           │ │
│ │ 注：location 为自由文本，原文照显（非结构化章号）        │ │
│ └──────────────────────────────────────────────────────────┘ │
│ 弹层：创建/编辑对话框（标题必填+优先级 0-100+位置+描述）     │
└──────────────────────────────────────────────────────────────┘
```
- 参考锚点（真实实现）：
  - 端点：GET /api/v1/projects/{pid}/foreshadowings（分页 {items,...}）；创建 POST 同列表端点；PATCH /api/v1/foreshadowings/{id}；DELETE /api/v1/foreshadowings/{id}
  - 工具栏：列表非空时「去创建」（library-create-btn，accent 主按钮）+ AI 提取（extract-entry-lib，提取类型含「伏笔」）
  - 平铺列表（library-list，divide-y 圆角卡片）：行 = 标题（item.title，纯 span 展示，flex-1 truncate）+ 状态徽标（lib-fs-status-&lt;id&gt;，未回收=accent-weak / 已回收=surface-3；已回收时附「· 回收日期」lib-fs-resolved-at-&lt;id&gt;）+ 优先级（lib-fs-priority-&lt;id&gt;，文案「优先级 {n}」）+ 位置徽标（lib-fs-location-&lt;id&gt;，location 原文照显，空串不渲染）+ 悬停操作（编辑 lib-edit-&lt;id&gt; / 删除 lib-delete-&lt;id&gt;，D12 opacity 0→100）；无等级/标签扩展（withCharacterExtras=false）
  - #1324：扩展由 `withForeshadowExtras`（library.tsx 传 activeCat==='foreshadow'）门控——其他分类不渲染 lib-fs-* 节点
  - 创建/编辑对话框（library-create-dialog，cat=foreshadow）：标题（必填，requiredValue=title）+ 优先级（number input，min 0 max 100，默认 50）+ 位置 + 描述
  - 空态：无条目 → library-tab-empty「还没有伏笔，去创建」+ CTA
  - 后端状态机（GUI 只读展示）：status open/resolved（创建即 open，回收走 resolve 端点）；Create/Update DTO 均无 status 字段——行内状态徽标**只读**，无状态切换控件（原型亦无此按钮，见 #1324 拍板）
- 布局说明：纵向单栏——工具栏 → 平铺列表；行内标题 flex-1 truncate 在前，其后依次状态徽标/优先级/位置徽标（均 shrink-0），末尾编辑/删除（悬停显现）；对话框遮罩挂页面根部

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 去创建（library-create-btn / 空态 CTA） | 列表非空或空态 | 打开创建对话框（空表单） | — | POST 成功 → 关框 + reloadKey 刷新 | err toast | 标题必填（title 字段） |
| 行编辑（lib-edit） | 悬停显现铅笔图标 | 打开编辑对话框（预填 title/priority/location/description） | saving 禁用 | PATCH 成功 → 关框 + 刷新 + 顶部「已保存」 | err toast，对话框保持可改重试 | 优先级缺失回填兜底 50 |
| 行删除（lib-delete） | 悬停显现垃圾桶 | ConfirmDialog（lib-confirm-dialog） | DELETE 请求 | ok toast + 列表刷新 | err toast + 关框 | 遮罩点击不关闭（#195）；关闭仅 取消/Esc/确认成功 |
| 对话框保存（library-create-save） | 标题非空 enabled | handleSave（PATCH/POST 父级分支） | saving「保存中…」禁用 | 父级关框 + 刷新 | err toast | 优先级原生 min/max 0-100；ESC/取消关闭；遮罩点击不关闭 |
| AI 提取（extract-entry-lib） | 描边按钮 | AIExtractDialog（类型 = 伏笔，章节选择） | 提取中 | 完成 toast + 最近提取记录 | 失败 toast | 仅 currentProjectId 非 null 渲染 |
| 状态机控件（open/resolved 切换） | 无（原型与实现均无此控件） | — | — | — | — | 后端 status 字段与 resolve/reopen 端点存在，但 GUI **只读展示**状态徽标，不提供切换入口（#1324 拍板：超原型，另议） |

## 3. 验收

- N1：列表行展示标题 + 悬停编辑/删除（D12）
- N2：创建/编辑对话框（标题必填 + 优先级 0-100 默认 50 + 位置/描述）
- N3：删除二次确认（不可恢复文案）
- N4：空态 CTA + 列表非空常驻「去创建」+ AI 提取入口（伏笔类型）
- N5：列表行渲染状态徽标（未回收/已回收，已回收附回收日期）+ 优先级「优先级 {n}」+ 位置徽标（location 原文照显）；状态徽标**只读**，无状态切换控件（与后端 resolve/reopen 端点的差异如实保留）
