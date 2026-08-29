# 设定库·知识图谱 — 交互规格

> 页面: knowledge | 路由: /library?cat=knowledge | 组件: pages/library.tsx（cat=knowledge）+ KnowledgeGraphView + KnowledgeGraphCanvas + RelationList + RelationForm
> 对应 design/GUI/knowledge/（官方简图 knowledge.html + knowledge-<state>.png，见后续补图）

## 1. 画面样式

- 原型引用：design/GUI/knowledge/
> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：设定库（页面标题）  主题 Select  语言 Select  窗口控制 │
├──────────────────────────────────────────────────────────────┤
│ 标题区：设定库（font-serif 26px）                            │
│ [项目选择器 青云志 ▾]  面包屑：设定库 · 青云志 / 知识图谱    │
├──────────────────────────────────────────────────────────────┤
│ 分类 tab：角色│世界观│大纲│时间线│伏笔│知识图谱              │
├──────────────────────────────────────────────────────────────┤
│ 工具栏：[＋新建关系]  [图谱视图│关系列表]（本地 view 切换）  │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ 图谱画布 520px（@xyflow：节点拖拽 / 滚轮缩放 0.2-2）     │ │
│ │   (角色)苏云舟 ──师承──> (角色)白眉道人                  │ │
│ │   (世界观)青云宗 <──加入── (角色)林晚照                  │ │
│ │   (时间线)夜访剑冢 ──埋设于──> (伏笔)师父闭关的真相      │ │
│ │ 节点=类型圆点+名称，边=贝塞尔+箭头+关系类型 label        │ │
│ │ 左下角详情卡：类型 + 名称 + [去编辑]（跳对应分类 tab）   │ │
│ │ 关系列表视图：起点→ 关系类型 → 终点 + 描述 + [编辑][删除]│ │
│ └──────────────────────────────────────────────────────────┘ │
│ 弹层：关系表单（起点/终点 类型+实体 + 关系类型必填 + 描述）  │
│ 图谱空态：虚线卡片「图谱为空」+ 去角色页创建按钮             │
└──────────────────────────────────────────────────────────────┘
```
- 参考锚点（真实实现，F48 §5.4）：
  - 端点：GET /api/v1/projects/{pid}/knowledge-graph（一次返回 nodes + edges 聚合）；GET/POST /api/v1/projects/{pid}/knowledge-relations（分页 + source_type/target_type/relation_type/source 过滤）；PATCH/DELETE /api/v1/knowledge-relations/{id}（真删）
  - 工具栏（flex-wrap）：新建关系（library-kg-new-relation，accent 主按钮 + Plus 图标）+ 视图切换胶囊组（library-kg-view-graph「图谱视图」默认激活 / library-kg-view-list「关系列表」，激活 = accent-weak 填充 + accent 文字）
  - 图谱画布（library-kg-canvas，h-[520px] 圆角卡片，@xyflow/react v12）：
    - 六类实体节点（自定义节点 KgNode）：角色/世界观/大纲/时间线/伏笔/地图标记，各类型专属底色/边框/文字色/圆点色（TYPE_STYLES 十六进制表）；节点 = 圆点 + 名称
    - 有向边（自定义边 KgEdge）：贝塞尔路径 + 箭头（ArrowClosed）+ 边中央 label（关系类型，SVG text）；边 id 保留 kr:/cr: 前缀
    - 画布默认能力：拖拽节点 / 滚轮缩放（minZoom 0.2 / maxZoom 2）/ 点空白取消选中
    - 点击节点 → 左下角节点详情卡（library-kg-node-detail，w-64）：类型 + 名称 + 「去编辑」按钮（library-kg-node-edit-<entity_id>）
    - 点击边 → 左下角边详情卡（library-kg-edge-detail，w-72）：label + 描述 + 来源（source_table）+ 编辑/删除按钮（仅 knowledge_relations 边；cr: 角色关系边只读无操作按钮）
  - 图谱空态（library-kg-empty，画布下方虚线卡片）：「图谱为空」+ 引导文案（去实体页创建或新建关系）+ 去角色页创建按钮（library-kg-empty-cta → 父级切 characters tab）
  - 关系列表（library-kg-relation-list，圆角卡片 divide-y）：行 = 起点名（font-medium）→ 关系类型（accent）→ 终点名 + 描述（12px ink-2）+ 悬停编辑（library-kg-rel-edit）/删除（library-kg-rel-delete）；名称经图谱节点解析（type + entity_id → name，缺省回退原始 id）；空态「暂无关系，点击「新建关系」创建」
  - 关系表单（library-kg-relation-form，520px 遮罩弹层，max-h 90vh）：起点类型/起点实体 + 终点类型/终点实体（双列 grid；类型下拉切换清空已选实体；实体下拉缺实体时 disabled）+ 关系类型（placeholder「如：属于 / 参与 / 师徒」）+ 描述（可选）+ 保存/取消
  - 删除确认（library-kg-confirm-* ConfirmDialog）：标题 = 关系类型，确认文案不可恢复，danger 红色
  - 无障碍：画布容器内 sr-only 图数据摘要（library-kg-summary）——节点名 + 边「起点 label 终点」拼接（jsdom 断言兜底）
  - 无实体创建入口：knowledge 分类 createCat=null，工具栏不渲染「去创建」；实体创建走各实体分类页
- 布局说明：纵向单栏——工具栏 → 图谱画布（或关系列表）/空态引导；关系表单与删除确认挂页面根部；图谱/列表切换为本地 view 状态（列表视图激活时按需拉取 relations，增删改经 reloadKey 局部刷新）

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 新建关系（library-kg-new-relation） | accent 主按钮 | 打开 RelationForm（create 模式，起点默认角色/终点默认世界观） | — | POST 成功 → 关框 + reloadKey 局部刷新（图谱/列表同步） | err toast | 表单提交 gate：起点实体 + 终点实体 + 关系类型三要素齐备（submit 拦截） |
| 视图切换（library-kg-view-graph / -list） | 图谱视图默认激活 | 切换 view → 列表视图激活时按需拉取 relations（分页响应） | — | 列表/画布渲染 | 拉取失败 → 空列表 | 切换不丢另一视图数据；reloadKey 局部刷新两视图 |
| 图谱节点点击 | 节点渲染（类型着色） | 选中 → 左下详情卡 + 「去编辑」 | — | 「去编辑」按类型跳对应分类 tab（character→角色 / world→世界观 / outline→大纲 / timeline→时间线 / foreshadow→伏笔 / map_pin→世界观地图工作台） | — | 点空白画布取消选中；同时只保留一个选中对象（节点/边互斥） |
| 图谱边点击 | 有向边 + label | 选中 → 左下边详情卡 | — | 编辑/删除按钮可用（仅 knowledge_relations 边） | — | cr: 前缀边（角色关系）只读展示来源；删除走 ConfirmDialog（library-kg-confirm） |
| 关系列表编辑/删除 | 悬停显现 | 编辑 → RelationForm（edit 模式回填六元组 + 描述）/ 删除 → ConfirmDialog（真删） | — | PATCH/DELETE → 关框 + 刷新 + ok toast | err toast | 删除标题 = 关系类型；确认文案不可恢复 |
| 关系表单保存（library-kg-form-save） | 三要素齐备可提交 | handleRelationSave（create → POST /projects/{pid}/knowledge-relations；edit → PATCH /knowledge-relations/{id}） | — | 关框 + reloadKey 刷新 | err toast，表单保持打开可改 | 类型切换清空对应实体选择；实体下拉随类型联动过滤（entities 按 type 过滤）；ESC/取消关闭 |
| 图谱空态 CTA（library-kg-empty-cta） | 虚线卡片按钮 | 切到 characters tab（onGoEntities） | — | 分类切换 + 角色页渲染 | — | 仅 nodes 空时渲染；引导文案含「新建关系」双路径 |
| 画布交互（拖拽/缩放） | @xyflow 默认 | 拖节点 / 滚轮缩放 | — | 布局即时更新 | — | minZoom 0.2 / maxZoom 2；jsdom 下 SVG 边不渲染（真实浏览器渲染层），sr-only 摘要兜底断言 |

## 3. 验收

- N1：图谱/关系列表双视图切换 + 列表按需拉取
- N2：六类实体节点着色 + 有向边 label + 点击节点/边出详情卡（互斥选中）
- N3：节点「去编辑」按类型跳对应分类 tab（map_pin → 世界观地图工作台）
- N4：关系创建/编辑/删除闭环（三要素 gate + 确认框 + 局部刷新）
- N5：图谱空态引导 + sr-only 数据摘要（无障碍/测试断言兜底）
