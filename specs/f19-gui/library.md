# 设定库（主视图） — 交互规格

> 页面: library | 路由: /library（无 cat 参数 → 默认 characters 分类） | 组件: pages/library.tsx（cat 未指定 → activeCat='characters'）
> 对应 design/GUI/library/（官方简图 library.html + library-<state>.png，见后续补图）

## 1. 画面样式

- 原型引用：design/GUI/library/（设定库六 tab + 项目选择器；各分类数据页见 design/GUI/characters/ 等六个目录）
- 参考锚点（真实实现，src/pages/library.tsx）：
  - 页面容器：`mx-auto max-w-[1080px] px-12 py-10`；标题 h1「设定库」（font-serif 26px，testid library-page 根节点）
  - 项目上下文行（mt-5，flex-wrap）：项目选择器（w-56 Select，library-project-select，placeholder「当前项目」）+ 面包屑（library-breadcrumb，「设定库 · 项目名 / 分类」，13px ink-2）+ 顶部保存指示（lib-save-indicator，仅编辑保存路径驱动：saving「保存中…」/ saved「已保存」2s 自动隐藏）
  - 六分类 tab（library-tabs，role=tablist，border-b）：角色 / 世界观 / 大纲 / 时间线 / 伏笔 / 知识图谱；激活 = accent 下边框 + accent 文字，闲置 ink-2 hover 加深；点击 handleTabChange → setSearchParams({cat}) 同步 URL
  - 工具栏（内容区右上，mb-3 justify-end）：「去创建」accent 主按钮（library-create-btn）+「AI 提取」描边按钮（extract-entry-lib）
    - 去创建可见性：仅非 knowledge 且列表非空且非加载/失败；world 需已选中分类且非地图工作台态；outline 不渲染（创建走树内＋入口）
  - 内容区三态：加载骨架（library-list 容器内 3 行 Skeleton）/ 加载失败（library-error + library-retry 重试按钮）/ 按 activeCat 分派视图（knowledge → KnowledgeGraphView；world 工作台 → MapWorkbench；outline → OutlineTree；world → WorldCategoryToolbar+WorldNodeView 树；timeline → TimelineView；其余 → LibraryItemList）
  - 无项目空态（library-empty）：虚线圆角卡片居中，Library 图标 +「选择或新建项目开始构建设定」+ 前往项目页按钮（library-go-projects）
- 布局说明：纵向单栏——标题 → 项目上下文行 → tab 栏 → 内容区；弹层（创建/编辑对话框、删除确认、角色详情、复制、关系表单等）统一挂页面根部；全局反馈走 toast 三态（ok/err/warn，§14.2 约定）
- 分类内容区细节见各分类规格：characters.md / world.md / outline.md / timeline.md / foreshadow.md / knowledge.md

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 项目选择器（library-project-select） | 显示当前项目名（无 → placeholder） | 展开项目列表（projects 全量） | — | 选中 → selectProject + 分类内容按新项目重载 | — | 切换时重置角色详情面板；未选项目 → 空态引导 |
| 分类 tab（library-tabs） | 当前分类 accent 下边框 | handleTabChange → URL cat 同步 + 内容重载 | 拉取中 → 内容区骨架 | 新分类视图渲染 | 拉取失败 → 错误态可重试 | 侧边导航 /library?cat=x 直达联动（URL 变化反向同步 tab）；切换时重置角色详情面板 |
| 前往项目页（library-go-projects） | 空态主按钮 | navigate('/projects') | — | 路由切换 | — | 仅 currentProjectId===null 时渲染 |
| 去创建（library-create-btn） | accent 主按钮（列表非空时） | 打开 LibraryCreateDialog（cat=activeCat，编辑态空） | 保存中按钮禁用 | 保存成功 → 关框 + reloadKey 刷新列表 | err toast，对话框保持可改重试 | knowledge 不渲染；world 需选中分类（语义=创建子条目）；outline 不渲染；world 工作台态隐藏；空列表由空态 CTA 覆盖 |
| AI 提取（extract-entry-lib） | 描边按钮 | 打开 AIExtractDialog（提取类型/章节选择/开始提取） | 提取中（extract.running） | 完成 toast + 最近提取记录 | 失败 toast | 仅 currentProjectId 非 null 渲染；提取类型含角色/世界观/伏笔/知识关系等，结果写入对应分类 |
| 顶部保存指示（lib-save-indicator） | 不渲染（idle） | 编辑保存发起 → saving | 「保存中…」 | 「已保存」2s 自动隐藏（timer 清理防重叠） | 失败回 idle + err toast | 仅编辑（PATCH）路径驱动；创建/删除保持 toast 语义 |
| 加载骨架 | 3 行 Skeleton | — | — | 数据到达渲染列表 | — | 骨架保持至请求 settle |
| 失败重试（library-retry） | 「加载失败，请重试」+ 重试按钮 | reloadKey+1 重新拉取 | 骨架 | 列表渲染 | 再次失败仍错误态 | 重试不丢当前分类与 URL |

## 3. 验收

- N1：无项目 → 空态引导 +「前往项目页」跳 /projects
- N2：六分类 tab 点击切换 + URL cat 参数同步 + 侧边导航 /library?cat=x 直达联动
- N3：项目选择器切换 → 内容按新项目重载 + 面包屑项目名同步
- N4：加载骨架 / 失败重试闭环
- N5：「去创建」与「AI 提取」按分类可见性规则正确显隐（knowledge 无创建；world 需选中分类；outline 树内创建）
