# 项目页 — 交互规格

> 页面: projects | 路由: /projects（根路由 / 重定向同页）| 组件: pages/projects.tsx
> 对应 design/GUI/projects/（官方简图 projects.html + projects-<state>.png，见后续补图）

## 1. 画面样式（简图/原型）

- 原型引用：design/GUI/projects/projects.html + projects-<state>.png（卡片网格 / 加载骨架 / 空态 / 新建对话框 / 卡片菜单 / 重命名 / 删除确认 / 导出对话框等状态截图）

> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：我的项目（页面标题）   主题 Select   语言 Select   窗口控制│
├──────────────────────────────────────────────────────────────┤
│ 页面标题区：我的项目 + 副标题（本地存储·自动存档）  [＋新建项目] │
├──────────────────────────────────────────────────────────────┤
│ 卡片网格（grid-cols-3）                                      │
│ ┌─────────┐ ┌─────────┐ ┌─────────┐                         │
│ │ 项目卡片 │ │ 项目卡片 │ │ 项目卡片 │                         │
│ │ 书名/标签│ │ 书名/标签│ │ 书名/标签│                         │
│ │ 字数/进度│ │ 字数/进度│ │ 字数/进度│                         │
│ │ 相对时间 │ │ 相对时间 │ │ 相对时间 │                         │
│ │ 进度条   │ │ 进度条   │ │ 进度条   │                         │
│ │ 菜单▾    │ │ 菜单▾    │ │ 菜单▾    │                         │
│ └─────────┘ └─────────┘ └─────────┘                         │
│ ┌──────────┐                                                 │
│ │ 末位新建卡 │ ＋新建项目（虚线卡片）                          │
│ └──────────┘                                                 │
└──────────────────────────────────────────────────────────────┘
```
- 参考锚点（以真实组件为准：pages/projects.tsx + components/ProjectCard、NewProjectDialog、RenameProjectDialog、ConfirmDialog、ExportDialog）：
  - 布局：max-w-[1080px] 居中滚动容器（px-12 py-10）；顶部标题区（h1 书名 + 副标题）右侧「新建项目」主按钮（new-project-btn）
  - 网格：grid-cols-3 gap-5 项目卡片 + 末位虚线新建卡片（new-project-card，min-h 168px）；加载中显示 3 张骨架卡片（role=status）；加载失败显示错误横幅；无项目显示空态引导（BookOpen + 标题/副文案 + CTA）
  - 项目卡片：书名 + 标签全拼（逗号分隔，空标签不渲染行）+ 目标字数 + 章节进度 n/m + 相对更新时间（刚刚/n 分钟前/n 小时前/n 天前/n 周前）+ 进度条（role=progressbar）+ 右上角卡片菜单（MoreHorizontal）；当前写作项目 → accent 边框 + 「写作中」角标
  - 卡片菜单：修改 / 重命名 / 导出 / 删除 四项（点击外部关闭；Enter/Space 可达）
  - 对话框族：新建（NewProjectDialog，遮罩点击不关闭 #195）/ 重命名（轻量单字段）/ 删除（ConfirmDialog danger）/ 导出（ExportDialog）——均遮罩不关闭，关闭仅 取消/Esc/成功
- 布局说明：项目页为居中限宽滚动页，上为标题与新建主入口，下为三列卡片网格。每张卡片聚合项目元信息与写作进度，末位虚线卡片作为第二新建入口。所有次级操作收纳进卡片右上角菜单，避免卡片表面堆叠按钮。

## 2. 动作样式（按钮 × 状态表，逐控件）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 新建项目（主按钮） | accent 实心「新建项目」（new-project-btn） | 打开 NewProjectDialog | — | — | — | 与末位虚线卡片为双入口，同开同一对话框 |
| 新建项目（末位卡片） | 虚线边框「+ 新建项目」（new-project-card） | 打开 NewProjectDialog | — | — | — | 空态 CTA 按钮同样打开对话框 |
| 新建对话框 · 书名 | 文本输入框 | 输入书名 | — | — | 提交时 strip 空 → 内联「书名必填」；>100 字 → 「书名过长」 | 必填 1-100；错误内联展示，对话框保持打开可改 |
| 新建对话框 · 标签 | 预设标签多选 Select + 自定义输入 + 已选 chips | 点选切换选中态；自定义 Enter 新增（去重非空）；chip × 移除 | — | 标签集合实时更新 | — | 未选任何标签 → 提交时报「至少一个标签」；建议来自本地轻量注册表（tags 聚合 + 旧 genre 枚举） |
| 新建对话框 · 语言/目标字数/模板 | zh-CN/en Select；字数 number（默认 800000）；模板 Select（默认模板 + 已建模板） | 修改表单值 | — | — | — | 字数初始读全局 default_words（fetch 失败 800000 兜底；用户已输入不覆盖）；空/非法 → 800000；模板选「默认模板」= 不带 template_id（引用式：模板改 → 项目同步生效） |
| 新建对话框 · 提交 | 取消/创建按钮 | 创建 → createProject（submitting 防双击）→ navigate('/writing') | submitting 期间按钮禁用、ESC 不关闭 | 201 → 跳转写作页 | 创建失败 → 内联错误（含原因）保持打开可重试 | ESC/取消关闭 + 焦点归还触发按钮；遮罩点击不关闭（#195）；in-flight 时 ESC 忽略 |
| 项目卡片点击 | 卡片 role=button + cursor-pointer | selectProject + navigate('/writing') | — | 路由切换进入写作页 | — | Enter/Space 键等价点击；写作中项目 accent 边框 + 角标 |
| 卡片菜单 | 右上角 MoreHorizontal 图标（hover 高亮） | 展开菜单（修改/重命名/导出/删除） | — | 菜单项执行对应动作后关闭 | — | 点击外部关闭；菜单内点击 stopPropagation 不触发卡片跳转 |
| 卡片菜单 · 修改 | 菜单项「修改」 | selectProject + navigate('/settings/project')（项目聚合设置页） | — | 路由切换 | — | 锚定项目后进入设置 |
| 重命名对话框 | 单字段输入（预填当前名）+ 取消/保存 | 保存 → renameProject | saving 中保存禁用、ESC 不关闭 | ok toast「已保存」+ 关闭 | err toast + 对话框保持可改重试 | strip 后空 → 保存按钮 disabled；Esc/取消/成功三路径关闭；遮罩点击不关闭（#195） |
| 删除确认框 | ConfirmDialog danger（标题含项目名 + 数据范围说明） | 确认 → deleteProject（DELETE） | 删除请求在途 | 成功/失败均关闭确认框；成功 ok toast，卡片由 store 驱动消失 | 失败 err toast（store rethrow 不吞错） | 遮罩点击不关闭（#195）；取消 → 不删除 |
| 导出对话框 | 范围勾选（设定档案附录）+ 导出位置 + 文件名 + 导出按钮 | 导出 → exportProjectFile fetch 文本 → Electron IPC 写盘 | saving 中 | ok toast「导出成功」+ 关闭 | err toast + 保持打开 | 遮罩点击不关闭；关闭 = 取消/成功 |
| 页面加载/错误 | 首挂载 ensureApiReady（Electron preload 时序防 401）→ loadProjects | — | 3 张骨架卡片（role=status aria-label=加载中） | 卡片网格渲染 | 错误横幅（err 边框 + 文案） | 有缓存列表时加载不显示骨架（仅 projects.length===0 且 loading） |

## 3. 验收

- N1：双入口（主按钮 + 末位虚线卡片 + 空态 CTA）均能打开 NewProjectDialog；Esc/取消/成功三路径关闭，遮罩点击不关闭
- N2：新建表单校验：书名必填 1-100、标签至少一个；创建成功跳转 /writing；失败内联展示原因且可重试
- N3：卡片聚合展示书名/标签/目标字数/章节进度/相对更新时间/进度条；写作中项目 accent 边框 + 角标
- N4：卡片菜单四项（修改→/settings/project、重命名、导出、删除）各自对话框行为符合上表；删除有二次确认且遮罩不关闭
- N5：重命名成功 ok toast、失败 err toast 且对话框保持可改；删除失败 err toast
