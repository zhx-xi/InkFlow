# 设定库·世界观 — 交互规格

> 页面: world | 路由: /library?cat=world | 组件: pages/library.tsx（cat=world）+ WorldCategoryToolbar + WorldNodeView + WorldCategoryDialog + CopyDialog + MapWorkbench（MapDirectoryTree / MapCanvas / PinDialog / MapCreateDialog）+ LibraryCreateDialog（cat=world）
> 对应 design/GUI/world/（官方简图 world.html + world-<state>.png，见后续补图）

## 1. 画面样式

- 原型引用：design/GUI/world/
> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：设定库（页面标题）  主题 Select  语言 Select  窗口控制 │
├──────────────────────────────────────────────────────────────┤
│ 标题区：设定库（font-serif 26px）                            │
│ [项目选择器 青云志 ▾]  面包屑：设定库 · 青云志 / 世界观      │
├──────────────────────────────────────────────────────────────┤
│ 分类 tab：角色│世界观│大纲│时间线│伏笔│知识图谱              │
├──────────────────────────────────────────────────────────────┤
│ 分类工具栏：地理× 城市× 秘境× 势力× 功法×（选中高亮）        │
│   [＋新建分类]  [地图视图]                 [整体复制]（右缘）│
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ 树视图（递归行：toggle+名称+描述预览+分类/子条目数徽标） │ │
│ │   ├─ 青云山 [地理] [3 子条目]    悬停 [编辑][删除][复制] │ │
│ │   │  ├─ 青云宗 [势力] [2 子条目]                         │ │
│ │   │  │  ├─ 剑冢 [秘境]                                   │ │
│ │   │  │  └─ 藏经阁 [地理]                                 │ │
│ │   │  └─ 剑冢区域 [秘境]                                  │ │
│ │   └─ 青云剑诀 [功法]                                     │ │
│ └──────────────────────────────────────────────────────────┘ │
│ 弹层：复制对话框（范围 chips 本体+全部子级/仅本体+目标项目） │
│                                                              │
│ 地图工作台：面包屑 设定库 › 世界观 › 地图视图 › 地图名       │
│   左 260px 目录树（地图+世界条目混排，拖拽/重命名/删除）     │
│   右画布：底图 tab（简图/图片/AI）+形状工具＋方框＋椭圆＋文字│
│   点击画布添加标记；pin 列表（类型筛选 地点/角色/事件/其他） │
└──────────────────────────────────────────────────────────────┘
```
- 参考锚点（真实实现）：
  - 端点：GET /api/v1/projects/{pid}/world-settings（items 含 parent_id/category/content）；POST 同列表端点 / PATCH /api/v1/world-settings/{id}；DELETE /api/v1/world-settings/{id}?cascade=true；GET /projects/{pid}/maps；POST /projects/{pid}/world-settings/copy（F37）；POST /projects/{pid}/world-categories（分类实体）
  - 分类工具栏（WorldCategoryToolbar，mb-3 flex-wrap）：标签「分类」+ 分类 chips（world-cat-filter-<name>：地理类前置 🗺 图标，选中 = accent 边框 + accent/10 淡填充，再点同 chip 取消选中——无「全部」项，未选 = 展示所有）+ chip 内 ×删除（world-cat-delete-<name>，hover err）+ 按钮组（world-cat-add 新建分类 / map-view-entry 地图视图，共用描边样式）+ 右缘整体复制（world-copy-all：Copy 图标 +「整体复制」，仅项目数 ≥2 时 enabled）
  - 地图视图入口门控（#699）：无选中分类或选中地理类 → 显示「地图视图」；选中抽象类 → 隐藏
  - 树视图（library-list 容器，圆角卡片）：WorldNodeView 递归行——toggle（world-tree-toggle-<id>，仅子节点渲染，ChevronRight 展开旋转 90°）+ 名称（font-medium）+ 描述预览（world-node-desc-<id>，12px ink-2 截断一行）+ 分类徽标（surface-3 胶囊）+ 子条目数徽标（world-node-childcount-<id>「{n} 子条目」）+ 悬停操作（编辑 lib-edit-<id> / 删除 lib-delete-<id> / 复制 world-copy-<id>）；行缩进 depth*18+12
  - 创建/编辑对话框（library-create-dialog，cat=world）：名称（必填）+ 类别（根条目 isRoot 时隐藏输入）+ 内容 textarea；选中分类时新建 = 创建子条目（标题「创建分类」，initialCategory 预填，isRoot=false）
  - 新建分类对话框（world-cat-dialog，420px）：分类名（必填，maxLength 100，空值下方红字「分类名不能为空」）+ 类型 radio（world-cat-kind-geo「地理」/ world-cat-kind-abstract「抽象」）+ 类型提示文字
  - 复制对话框（world-copy-dialog，420px）：范围 chips（world-copy-scope-subtree「本体 + 全部子级」默认 / world-copy-scope-self「仅本体」，仅行内 subtree 模式渲染）+ 目标项目 Select（world-copy-target，已排除当前项目）+ 复制按钮（world-copy-ok，目标未选 disabled）
  - 地图工作台（map-workbench，space-y-3）：四级面包屑（map-bc-lib 设定库 / map-bc-world 世界观 / map-bc-maplist 地图视图 / map-bc-current「🗺 地图名」）+ 创建根图（map-create-root，MapPlus 图标）+ pin 计数（{n} 个标记）+ 左 260px 目录树（MapDirectoryTree：地图树 + 世界条目树混排，含 pin 计数徽标、拖拽改挂、重命名、删除）+ 右栏画布（MapCanvas：底图 tab 简图/图片/AI[「即将推出」禁用] + 形状工具 ＋方框/＋椭圆/＋文字 + 点击画布任意位置添加标记）+ pin 列表（类型筛选 chips 地点/角色/事件/其他 + 行：类型徽标/名称/关联名/悬停编辑删除）
  - 空态（library-tab-empty）：「还没有世界观，去创建」+ CTA + 额外 WorldCatActionButtons（新建分类 + 地图视图）
- 布局说明：列表视图 = 分类工具栏 → 树卡片；地图工作台 = 面包屑 → 左右两栏（左树 260px / 右画布弹性）；全部弹层挂页面根部

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 分类 chip（world-cat-filter） | 未选中描边 | 选中 → 整树按 category 过滤（保留匹配节点 + 子树） | — | 过滤树渲染 | — | 再点取消（null = 全部）；筛选无匹配 → 轻空态（common.empty）；一项目一根（#567） |
| 分类删除（×） | chip 旁 × | handleWorldCatDelete（hook 内删除 + 刷新） | 请求中 | 分类 chips 刷新 + 清空筛选 | err toast | 删除分类不删条目（仅移除归类） |
| 新建分类（world-cat-add） | 描边按钮 | 打开 WorldCategoryDialog | — | 保存 → 分类 chips 刷新（父级关框 + reloadKey） | err toast | 类型二选一默认 geo；名称空不可保存 |
| 地图视图（map-view-entry） | 描边按钮 | setWorkbenchActive(true) | — | 工作台渲染（左树 + 右画布/未选地图空态） | — | 选中抽象类分类时隐藏；世界条目空但有地图仍可进入（#378） |
| 树 toggle（world-tree-toggle） | 展开态（箭头 90°） | 收起/展开子树 | — | 子树隐藏/显示 | — | 仅子节点行渲染；默认全部展开 |
| 行编辑（lib-edit） | 悬停显现 | 打开编辑对话框（预填 name/category/content） | saving 禁用 | PATCH 成功 → 关框 + 刷新 + 顶部「已保存」 | err toast | 类别编辑态优先 editing.category |
| 行删除（lib-delete） | 悬停显现 | ConfirmDialog（lib-confirm-dialog，追加红字级联警告行） | DELETE ?cascade=true | ok toast + 树刷新 | err toast + 关框 | 警告「该条目及其全部子条目将级联删除，不可恢复」；遮罩点击不关闭 |
| 行复制（world-copy） | 悬停显现 | 打开 CopyDialog（subtree 模式，rootId 绑定） | copying 禁用 | ok toast「已复制 n 条到 name」+ warnings 追加 warn toast / skipped 追加跳过数 | err toast，对话框保持打开可重试（E24） | 目标项目排除当前项目；确认 disabled 直至目标已选；Esc 关闭 |
| 整体复制（world-copy-all） | 右缘按钮（ml-auto） | 打开 CopyDialog（all 模式，范围 chips 隐藏） | copying 禁用 | 同上 toast 语义 | err toast + 保持打开 | 仅 1 项目 → disabled + title「需至少两个项目才能复制」（E21） |
| 创建/编辑对话框 | 与 library 通用双模式 | 名称必填 | saving | POST/PATCH → 关框 + 刷新 | err toast | 根条目（isRoot）隐藏类别输入；选中分类新建 = 创建子条目（标题「创建分类」） |
| 工作台面包屑 | 三段可点 + 当前地图名 | 层级 1/2（设定库/世界观）→ 退出工作台；层级 3（地图视图）→ 清空选中地图 | — | 视图切换 | — | 当前地图名纯展示（含 🗺 前缀） |
| 创建根图（map-create-root） | 面包屑右缘按钮 | 打开 MapCreateDialog（parentMapId=null） | — | 目录树新增根图 | err toast | 子图创建走目录树行内「创建子图」入口 |
| 画布底图/形状 | 底图 tab（简图默认/图片/AI「即将推出」）+ 形状按钮 | 切换底图 / 添加形状 | 保存中 | 画布即时更新 | err toast | 形状可拖拽编辑（MapCanvas 内部）；AI 底图禁用态 |
| pin 添加/编辑（PinDialog） | 画布点击或列表行编辑 | 名称/类型（地点/角色/事件/其他）/关联实体（搜索）/坐标 | — | pin 列表 + 画布同步 | err toast | 未选地图 → 右侧「选择左侧地图节点查看地图」空态；遮罩点击不关闭 |
| pin/地图删除 | 悬停显现 / 树内 | ConfirmDialog | DELETE | 移除 + 计数刷新 | err toast | 地图有子图 → 422 err toast 提示先移走子图或级联删除 |

## 3. 验收

- N1：分类 chips 筛选整棵树（保留匹配节点+子树）+ 无「全部」项 + 再点取消
- N2：树行两行式信息（名称 + 描述预览）+ 分类/子条目数徽标 + toggle 收起展开
- N3：行内编辑/删除（级联警告红字）/复制 + 顶部整体复制（双模式 CopyDialog）
- N4：地图工作台进入/退出 + 创建根图 + pin 列表类型筛选 + 未选地图空态
- N5：新建分类对话框（geo/abstract 二选一 + 空名校验 + 地图入口门控）
