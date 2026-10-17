# 设定库（主视图） — 交互规格

> 页面: library | 路由: /library（无 cat 参数 → 默认 characters 分类） | 组件: pages/library.tsx（cat 未指定 → activeCat='characters'）
> 对应 design/GUI/library/（官方简图 library.html + library-<state>.png）

## 1. 画面样式

- 原型引用：design/GUI/library/library.html + library-<state>.png（main/noproject/tab-empty）
> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：设定库（页面标题）  主题 Select  语言 Select  窗口控制 │
├──────────────────────────────────────────────────────────────┤
│ 标题区：设定库（font-serif 26px）                            │
│ [项目选择器 项目甲 ▾] 面包屑：设定库 · 项目甲 / 角色 [已保存]│
├──────────────────────────────────────────────────────────────┤
│ 分类 tab：角色│世界观│大纲│时间线│伏笔│知识图谱              │
├──────────────────────────────────────────────────────────────┤
│ 工具栏（右缘）：[去创建] [待确认提取(2)]  [AI 提取]          │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ 内容区卡片（library-list 圆角卡片）按 activeCat 分派视图 │ │
│ │   角色 → 等级选项卡 + 分组卡片                           │ │
│ │   world → 分类 chips + 树视图 / 地图工作台               │ │
│ │   大纲 → 三级树 + 故事弧 / 时间线 → 双序事件列表         │ │
│ │   伏笔 → 平铺列表 / knowledge → 图谱画布 + 关系列表      │ │
│ │ 三态：加载骨架（3 行）/ 失败重试 / 无项目空态引导卡片    │ │
│ │ 列表下方分页条：每页 Select + 上一页/信息/下一页         │ │
│ │ 弹层：创建/编辑对话框、删除确认、详情面板挂页面根部      │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```
- 参考锚点（真实实现，src/pages/library.tsx）：
  - 页面容器：`mx-auto max-w-[1080px] px-12 py-10`；标题 h1「设定库」（font-serif 26px，testid library-page 根节点）
  - 项目上下文行（mt-5，flex-wrap）：项目选择器（w-56 Select，library-project-select，placeholder「当前项目」）+ 面包屑（library-breadcrumb，「设定库 · 项目名 / 分类」，13px ink-2）+ 顶部保存指示（lib-save-indicator，仅编辑保存路径驱动：saving「保存中…」/ saved「已保存」2s 自动隐藏）
  - 六分类 tab（library-tabs，role=tablist，border-b）：角色 / 世界观 / 大纲 / 时间线 / 伏笔 / 知识图谱；激活 = accent 下边框 + accent 文字，闲置 ink-2 hover 加深；点击 handleTabChange → setSearchParams({cat}) 同步 URL
  - 工具栏（内容区右上，mb-3 justify-end）：「去创建」accent 主按钮（library-create-btn）+「待确认提取（N）」角标按钮（extract-pending-entry，仅 N>0 渲染；N = 待确认批次数）+「AI 提取」描边按钮（extract-entry-lib）
    - 去创建可见性：仅非 knowledge 且列表非空且非加载/失败；world 需已选中分类且非地图工作台态；outline 不渲染（创建走树内＋入口）
  - 内容区三态：加载骨架（library-list 容器内 3 行 Skeleton）/ 加载失败（library-error + library-retry 重试按钮）/ 按 activeCat 分派视图（knowledge → KnowledgeGraphView；world 工作台 → MapWorkbench；outline → OutlineTree；world → WorldCategoryToolbar+WorldNodeView 树；timeline → TimelineView；其余 → LibraryItemList）
  - 无项目空态（library-empty）：虚线圆角卡片居中，Library 图标 +「选择或新建项目开始构建设定」+ 前往项目页按钮（library-go-projects）
- 布局说明：纵向单栏——标题 → 项目上下文行 → tab 栏 → 内容区；弹层（创建/编辑对话框、删除确认、角色详情、复制、关系表单等）统一挂页面根部；全局反馈走 toast 三态（ok/err/warn，§14.2 约定）
- 分页条（公共组件 `components/Pagination.tsx`）：仅 **characters / foreshadow**（`PageableCatKey`）分页列表下方渲染；`library-page` 前缀，容器 `mt-4 justify-end`；左「每页条数」Select（默认 50 = `LIBRARY_PAGE_SIZE`）→ 「上一页」→ 信息「第 {n} / {m} 页 · 共 {k} 条」→ 「下一页」。服务端切片（`useLibraryPagedList`，`limit/offset`，`hooks/useLibraryPagedList.ts:27`）；**world 全量取数不分页**；首页 prev 禁用 / 末页 next 禁用；total ≤ pageSize 时组件仍渲染（双向禁用）
- 分类内容区细节见各分类规格：characters.md / world.md / outline.md / timeline.md / foreshadow.md / knowledge.md

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 项目选择器（library-project-select） | 显示当前项目名（无 → placeholder） | 展开项目列表（projects 全量） | — | 选中 → selectProject + 分类内容按新项目重载 | — | 切换时重置角色详情面板；未选项目 → 空态引导 |
| 分类 tab（library-tabs） | 当前分类 accent 下边框 | handleTabChange → URL cat 同步 + 内容重载 | 拉取中 → 内容区骨架 | 新分类视图渲染 | 拉取失败 → 错误态可重试 | 侧边导航 /library?cat=x 直达联动（URL 变化反向同步 tab）；切换时重置角色详情面板 |
| 前往项目页（library-go-projects） | 空态主按钮 | navigate('/projects') | — | 路由切换 | — | 仅 currentProjectId===null 时渲染 |
| 去创建（library-create-btn） | accent 主按钮（列表非空时） | 打开 LibraryCreateDialog（cat=activeCat，编辑态空） | 保存中按钮禁用 | 保存成功 → 关框 + reloadKey 刷新列表 | err toast，对话框保持可改重试 | knowledge 不渲染；world 需选中分类（语义=创建子条目）；outline 不渲染；world 工作台态隐藏；空列表由空态 CTA 覆盖 |
| 待确认提取（extract-pending-entry） | 描边按钮 + 角标「N」（**仅 N>0 渲染**） | 展开批次面板（extract-pending-panel，右对齐下拉）；行内四动作：**详情**（→ 右侧详情面板）· 查看（→ 还原该批结果视图）· 取消（**先弹二次确认**，确认后才清暂存）· 确认落库（批次级物化）；**整行可点 = 详情** | 面板内行操作进行中 | 确认 / 取消后角标同步下降 | 无批次 → 入口不渲染；列表拉取失败 → 空面板 + err toast | 计数 = **批次数**（非条目数）；按 currentProjectId 拉取、切项目重算（不串项目）；「查看」与「详情」都走既有 GET .../extractions/staging/{batch_id}（不新增端点） |
| AI 提取（extract-entry-lib） | 描边按钮 | 打开 AIExtractDialog（类型/范围选择，见 §2.1） | 提取中（extract.running） | 完成 toast + 最近提取记录 | 失败 toast | 仅 currentProjectId 非 null 渲染；类型=角色/世界观/时间线/伏笔/知识图谱（单选）+ 通用多选；范围=全文/按卷/按章（多选+区间）；章节下拉**全量加载**（翻页取满章节列表 `total`，>50 章项目可选第 51 章起） |
| 顶部保存指示（lib-save-indicator） | 不渲染（idle） | 编辑保存发起 → saving | 「保存中…」 | 「已保存」2s 自动隐藏（timer 清理防重叠） | 失败回 idle + err toast | 仅编辑（PATCH）路径驱动；创建/删除保持 toast 语义 |
| 加载骨架 | 3 行 Skeleton | — | — | 数据到达渲染列表 | — | 骨架保持至请求 settle |
| 失败重试（library-retry） | 「加载失败，请重试」+ 重试按钮 | reloadKey+1 重新拉取 | 骨架 | 列表渲染 | 再次失败仍错误态 | 重试不丢当前分类与 URL |
| 分页条（library-page） | 首页：prev 禁用 / next 可用（total > pageSize 时）；信息「第 1 / {m} 页 · 共 {k} 条」 | 「下一页」→ setPage(p+1) → 服务端按 `offset=(p+1)*50` 重拉；「上一页」→ setPage(p-1) | 列表区保持骨架/旧数据（hook 内部 loading） | 列表换页 + 信息更新 | 拉取失败 → 走既有错误态（library-error） | 仅 characters/foreshadow 渲染；末页 next 禁用；total ≤ 50 → 双向禁用；「每页条数」Select 变档（默认 50） |

### 2.1 AI 提取对话框（类型面 + 范围面）

> 原型：`design/GUI/library/library.html`（`extract-single` / `extract-generic` 两态；另含 `extract-timeline` 来源页默认类型 · `extract-chapter` 按章范围块（非法提示）· `extract-chapter-overlap` 重叠提示）+ `library-extract-single.png` / `library-extract-generic.png` / `library-extract-timeline.png` / `library-extract-chapter.png` / `library-extract-chapter-overlap.png`

```text
┌─ AI 提取 ──────────────────────────────────────────── × ┐
│ 提取类型（单选，默认「角色」）                             │
│ (●角色) ( 世界观) ( 时间线) ( 伏笔) ( 知识图谱) ( 通用)    │
│ [通用时] 要提取的设定（多选）                              │
│   ☑角色 ☑世界观 ☐时间线 ☑伏笔 ☐知识图谱                   │
│ 提取范围   (●全文) ( 按卷) ( 按章)                        │
│ [按卷时] ☑卷一 ☐卷二 ☑卷三                              │
│ [按章时] [第 1–10 章 ×] [第 13–20 章 ×]  ＋添加范围  全选  │
│           单次上限 100 章，超出自动分批                    │
│ [开始提取]                                              │
└─────────────────────────────────────────────────────────┘
```

- **单选** = 只提取该类；**通用** = 多选（一次提多类）。设定页默认单选。
- 类型 → 后端 `type` 映射：角色→`character`、世界观→`setting`、时间线→`timeline`、伏笔→`foreshadowing`、知识图谱→`knowledge_relation`
- **提交语义**（统一走 `POST /api/v1/extract`，`type` 由所选类型决定）：
  - 多类型 = **逐个类型各发一次请求**（N 类 = N 次）
  - 范围 → `chapter_ids`：全文 = 项目全部章；按卷 = 选中卷的全部章；按章 = 各区间展开的章
  - 单次 `chapter_ids` **≤ 100**（后端 `ExtractionRequest` validator）；超出**自动分批**（每批 ≤ 100，多请求）
  - `timeline`：只发 `chapter_ids` + `auto_extract: true`（后端只收章节模式，不收 `text`）
  - `knowledge_relation`：**不带** `text` / `chapter_ids`（项目级提取）
- 章节 / 卷列表**全量加载**（翻页取满 `total`；卷→章用章节的 `volume_id` 归并）
- **默认类型随来源页**：弹框接受来源页传入的默认类型（prop `initialKind`），打开即**单选**选中该页自身类型 —— 角色页→`character`、世界观页→`world`、时间线页→`timeline`、伏笔页→`foreshadowing`、知识图谱页→`knowledgeGraph`；**每次打开按来源页重置**（资料库入口跨分类复用同一实例，故不能只在挂载时取初值）；无来源页上下文（写作页、大纲页）→ 回落 `character`，不报错。「通用」多选**不预选**（要同时提多类由用户自行切「通用」）。
- **按章范围块**：已添加的每个 `{from,to}` 在「按章」输入区**下方**渲染为可读 chip（`第 {from}–{to} 章`），每块带 `×` 删除入口（容器 `ai-extract-range-list`、单块 `ai-extract-range-chip`、删除钮 `ai-extract-range-remove`）；删除后 chips 与提交集合同步。
- **非法输入就地提示 + 重叠提示**：空 / 非数字 / `< 1` / 起 > 止 → 就地红字提示（`ai-extract-range-error`，复用 `text-err` 12px 校验风格），**不再静默 return**；重复/重叠区间**只提示不合并**（`extract.rangeOverlap`，两段 chip 均保留），提交时按**并集**去重；「界面所见范围块之并集 = `resolveChapterIds` 产出集合」。

### 2.2 AI 提取结果视图 + 最小化

> 原型：`design/GUI/library/library.html`（`extract-result` / `extract-min` 两态）+ `library-extract-result.png` / `library-extract-min.png`

```text
┌─ AI 提取 ──────────────────────────────────────────── × ┐
│ ● 提取完成 · 待确认（未落库）                             │
│ ┌────────────────────────────────────────────────────┐ │
│ │ 新增 3                                             │ │
│ │  角色甲 [角色] / 角色壬 [角色] / 角色癸 [角色]        │ │
│ │ 更新 1                                             │ │
│ │  角色乙 [将覆盖]                                    │ │
│ └────────────────────────────────────────────────────┘ │
│ 确认后才写入设定库；取消将丢弃本次结果。批次 ext-…        │
│ [取消]                          [确认落库]              │
└─────────────────────────────────────────────────────────┘
   最小化后 → 页面右下角浮窗：[● 提取中 · … 62%  还原]
```

- **两段式**：提交一律带 `stage: true` → 产物只进暂存区（正式表零变更）；结果视图展示
  **新增** / **更新（替换）** 清单（更新项标注「将覆盖」）
- 「**确认落库**」→ `POST /projects/{pid}/extractions/staging/{batch_id}/confirm` → 关闭 + ok toast
- 「**取消**」→ `POST /projects/{pid}/extractions/staging/{batch_id}/cancel` → 关闭（丢弃本次结果）
- **最小化**：提取进行中可点「—」收起对话框 → 右下角 `ai-extract-float` 浮窗；点击浮窗「还原」恢复对话框
- testid：`ai-extract-result` / `ai-extract-created` / `ai-extract-created-item` /
  `ai-extract-updated` / `ai-extract-updated-item` / `ai-extract-confirm` / `ai-extract-cancel` /
  `ai-extract-min` / `ai-extract-float`

### 2.3 待确认提取入口 + 浮窗生命周期

> 原型：`design/GUI/library/library.html`（`extract-pending-panel` / `extract-float-pending` /
> `extract-close-prompt` 三态）+ `library-extract-pending-panel.png` / `library-extract-float-pending.png`
> / `library-extract-close-prompt.png`

```text
工具栏：[去创建]  [待确认提取 (2)]  [AI 提取]      ← N = 0 时不渲染
                    └─ 下拉面板（右对齐）：
                       ┌ 待确认提取 (2) ──────────────────────────────┐
                       │ 确认前不会写入设定库                          │
                       │ [时间线] 18 项  10-11 14:02 [查看][取消][确认落库] │
                       │ [角色]    3 项  10-11 13:47 [查看][取消][确认落库] │
                       │ 批次按时间倒序；过期未确认的批次由内核自动清理（30 天） │
                       └──────────────────────────────────────────────┘
关框（×）且有未确认结果 → 底部提示：提取结果尚未确认，已保留在「待确认提取」中
浮窗（最小化态，右下角）：[● 提取中 · … 62%  还原] / [● 提取完成 · 待确认  还原]
```

- **会话全局化（B1-a）**：`open` / `minimized` / `staged` / `initialKind` / `projectId` 提升到
  `stores/extract.ts`（zustand），对话框 + 浮窗**挂 App 层**（`App.tsx`，`ToastHost` 旁）→
  宿主页重挂载 / 路由切换均不卸载，浮窗与结果视图**存活**；`chapters` / `volumes` / `runs` /
  范围面等**一次性输入留组件内**（不上提，避免泄漏到下一次提取）。两宿主页（library / writing）
  只调 `openDialog()`，**不再各自持有页面级 extract state**。
- **关框 ≠ 丢弃结果（D5）**：`×` 只清当前结果视图 → warn toast `extract.unconfirmedKept` 指向入口；
  暂存批次仍在库中，入口「查看」用既有 `GET /api/v1/projects/{pid}/extractions/staging/{batch_id}`
  读回并渲染成结果视图（确认 / 取消语义不变）。
- **最小化（—，D3/D4）**：浮窗文案随状态变——进行中「提取中 · …」/ 有未确认结果
  「提取完成 · 待确认」（`extract.floatPending`）；「还原」恢复对话框。浮窗与对话框是同一
  App 级实例 → **跨页面可见**，即「离开相关页面」的可见提示（不额外弹 toast，避免切页噪音）。
- **入口（B2-a / D1 / D2）**：仅 `currentProjectId` 非 null 且 N>0 渲染；面板行内三动作
  查看 / 取消 / 确认落库；N = 待确认**批次数**（非条目数），App 挂载 / 切项目 / confirm / cancel
  后重算（按 `projectId` 过滤，不串项目）。
- testid：`extract-pending-entry` / `extract-pending-panel` / `extract-pending-item` /
  `extract-pending-view` / `extract-pending-confirm` / `extract-pending-cancel`

### 2.4 取消二次确认 + 条目详情右侧面板

> 原型：`design/GUI/library/library.html`（`extract-pending-cancel-prompt` / `extract-pending-detail`
> 两态）+ `library-extract-pending-cancel-prompt.png` / `library-extract-pending-detail.png`

```text
面板行：[时间线] 18 项 10-11 14:02   [详情][查看][取消][确认落库]   ← 整行可点 = 详情
        └─ 点「取消」→ 确认弹窗（右上角 − / ×）：
           ┌ 取消这批提取？                          —  × ┐
           │ 取消将清除本批暂存内容且不可恢复。若想暂时保留，    │
           │ 可点右上角「最小化」，之后仍可从「待确认提取」进入。 │
           │                                        [返回]  │
           └────────────────────────────────────────────────┘
        └─ 点「详情」/ 整行 → 右侧详情面板：
           ┌ 条目详情                                     × ┐
           │ [时间线] 18 项 · 10-11 14:02                    │
           │ 本批条目（点选查看明细）：示例事件甲[新增] …       │
           │ 标题/描述/时间原文/未定原因/时间值/时间单位/        │
           │ 纪元/纪元值/流速比/叙事位置/时间线标记/            │
           │ 实体类型/动作   ← 逐一取自 payload，空值给占位     │
           │ 补时间 [317] [年]        [丢弃]      [确认落库]   │
           └─────────────────────────────────────────────────┘
```

- **取消必先确认（D7=A）**：面板行「取消」不再点了即删 —— 打开共享 `ConfirmDialog`，出路三条：
  - 右上角 **×（destructive）** = 确认取消 → `POST .../staging/{batch_id}/cancel`（清本批暂存，**正式表零写入**；服务端语义不变）
  - 右上角 **—（最小化保留）** = **零请求**：关弹窗 + 收起面板，批次仍在「待确认提取」入口（N 不变）
  - 底部 **返回** = 只关弹窗，面板保持打开
  - 文案必须写明两条出路（会**清除**本批暂存 / 可**最小化**暂时保留），标题「取消这批提取？」
- **条目详情（D8=B）**：行内「详情」或整行 → 右侧面板，字段**逐一取自** `GET .../staging/{batch_id}`
  的 `payload`（`title` / `description` / `time_display` 原文 / `parse_reason` / 时间与纪元字段 /
  `entity_type` / `action`）；**空字段给占位文案（`extract.pendingFieldEmpty`），不渲染 null**；
  `entity_type` / `action` 走显示名（新增 / 更新）。**零新端点**。
- **面板内单一动作区**：`确认落库`（条目级 `POST .../items/{item_id}/confirm`，**未填时间则禁用** ——
  f12 §2.9 D3）· `丢弃`（`DELETE .../items/{item_id}`，零物化）。批次级「确认落库」仍在面板行
  （两者作用域不同：行=整批，面板=当前条目），避免语义分叉成两套列表按钮。
- 动作完成后重读本批明细并刷新入口计数（N）；该批最后一条被处理 → 面板自行关闭。
- testid：`extract-pending-detail` / `extract-pending-cancel-prompt-dialog`（含 `-minimize` / `-dismiss` / `-ok`）/
  `extract-pending-drawer`（含 `-item` / `-close` / `-time` / `-unit`）/ `extract-pending-field-<key>` /
  `extract-pending-item-confirm` / `extract-pending-discard`

## 3. 验收

- N1：无项目 → 空态引导 +「前往项目页」跳 /projects
- N2：六分类 tab 点击切换 + URL cat 参数同步 + 侧边导航 /library?cat=x 直达联动
- N3：项目选择器切换 → 内容按新项目重载 + 面包屑项目名同步
- N4：加载骨架 / 失败重试闭环
- N5：「去创建」与「AI 提取」按分类可见性规则正确显隐（knowledge 无创建；world 需选中分类；outline 树内创建）
- N6：characters / foreshadow 分类列表下方渲染分页条（`library-page` 前缀）——首页 prev 禁用、末页 next 禁用、信息「第 1 / {m} 页 · 共 {k} 条」正确（默认 50/页）；点「下一页」→ 服务端按 offset 重拉且 total 不变；world 分类**不**渲染分页条（全量取数）
- N7：AI 提取对话框类型单选含**时间线 / 伏笔 / 知识图谱**（共 6 项含「通用」）；中英文 i18n 键对齐
- N8：**通用**多选 → 每选中类型各发一次 `POST /api/v1/extract`，`type` 映射正确；`knowledge_relation` 不带源、`timeline` 带 `chapter_ids` + `auto_extract`
- N9：范围「全文」→ `chapter_ids` = 全部章；「按卷」多选 → 选中卷全部章；「按章」区间 → 展开；单批 > 100 章 → 自动分批
- N10：提取成功 → 对话框切结果视图（新增/更新清单）；提交带 `stage: true`；正式表零变更（确认前）
- N11：「确认落库」→ 调 confirm 端点（带 `batch_id`）→ 关框 + ok toast；「取消」→ 调 cancel 端点 → 关框
- N12：提取进行中可最小化 → 对话框收起 + 右下角 `ai-extract-float` 浮窗；点浮窗「还原」恢复对话框
- N13：弹框默认类型**随来源页**——从时间线页打开 → 「时间线」单选即选中；角色 / 世界观 / 伏笔 / 知识图谱页各自对应；无来源页上下文 → 回落「角色」且不报错；「通用」多选默认不预选（与类型面不冲突）
- N15：提取最小化后**跨路由 / 宿主页重挂载**，浮窗仍在；点「还原」可见结果视图（新增/更新清单）
- N16：存在「待确认提取（N）」入口；重开 App / 刷新后仍能列出未确认批次并可 查看 / 确认落库 / 取消；
  N = 批次数（非条目数），confirm / cancel 后同步下降
- N17：有未确认结果时关闭对话框有可见提示（`extract.unconfirmedKept`）；library 与 writing
  两宿主页同走 `stores/extract.ts`（无页面级 extract state）
- N14：「按章」添加范围 → 输入区下方**立即出现范围块 chip**（`第 {from}–{to} 章` + `×`）；每块可**单独删除**，删除后 chips 与提交集合同步；非法输入（空 / 0 / 起 > 止）有**可见提示**、不静默丢弃；重叠**只提示不合并**（保留两段）；提交时 `resolveChapterIds` 产出的章节集合 = 界面所见范围块之并集；zh/en i18n 键对齐
- N18：面板行「取消」→ **先弹二次确认**（不立即删批）；三条出路 —— 右上角 **×** → `POST .../staging/{batch_id}/cancel` → 该批消失 + 角标 N 减 1（正式表零写入）；右上角 **—** → 弹窗与面板关闭、**零请求**、批次仍在；底部「返回」→ 弹窗关闭、面板保持打开、批次仍在
- N19：确认弹窗文案写明两条出路（**会清除**本批暂存 / 可点右上角「**最小化**」暂时保留），标题「取消这批提取？」
- N20：行内「详情」**或整行**（非按钮处）→ 右侧详情面板打开；字段与 `GET .../staging/{batch_id}` 的 `payload` **逐项一致**（含 `time_display` 原文 / `parse_reason`）；空字段显示占位文案、**不出现 `null`**；点选另一条目 → 明细同步切换
- N21：面板底部「确认落库」**未填时间时禁用**，填后 `POST .../items/{item_id}/confirm` 带 `time_value` / `time_unit`（条目级）；「丢弃」走 `DELETE .../items/{item_id}` 且**零物化**（不调 confirm）；处理完该批最后一条 → 面板自行关闭 + 入口角标同步
