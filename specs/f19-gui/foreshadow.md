# 设定库·伏笔 — 交互规格

> 页面: foreshadow | 路由: /library?cat=foreshadow | 组件: pages/library.tsx（cat=foreshadow）+ LibraryItemList（无角色扩展）+ LibraryCreateDialog（cat=foreshadow）
> 对应 design/GUI/foreshadow/（官方简图 foreshadow.html + foreshadow-<state>.png）

## 1. 画面样式

- 原型引用：design/GUI/foreshadow/foreshadow.html + foreshadow-<state>.png（状态枚举：main / filter-a / filter-b / search-title / chapter-match-text / chapter-match-struct / sort-asc / noresult / legacy / empty / create-dialog）
> 低保真排版示意简图（区块+标签，非精确像素）
> ⚠️ 筛选/排序条（下图 🔷 段）为 **#1376 设计基线：原型已出、实现未做**；`legacy` 态 = 当前实现的真实形态。其余区块均以已合入实现为准。

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
│ │ 🔷 筛选/排序条（#1376 待实现）                            │ │
│ │  回收状态 [全部][未回收][已回收]   ← chip 三态（选中=accent）│ │
│ │  检索 [__标题或位置，如：剑 / 第 2 章__] ← 实时，无需 Enter│ │
│ │                      排序 [优先级 高→低]   显示 5 / 共 8 条│ │
│ ├──────────────────────────────────────────────────────────┤ │
│ │ 平铺列表：标题 + 状态徽标 + 优先级 + 位置                │ │
│ │   师父闭关的真相  [未回收] 优先级 90  第11章·闭关        │ │
│ │   断剑的秘密      [未回收] 优先级 75  第13章·山门        │ │
│ │   林晚照的旧玉佩  [已回收] 优先级 40  第8章·初见         │ │
│ │   未署名的旧信    [未回收] 优先级 20  （location 空→无徽标）│ │
│ │ 行悬停显现 [编辑][删除]（D12）                           │ │
│ │ 注：location 为自由文本，原文照显（非结构化章号）        │ │
│ │ 筛选后 0 条 → 卡内展示「当前筛选条件下没有匹配的伏笔」+  │ │
│ │   [清除筛选]（**不**复用「还没有伏笔，去创建」空态）     │ │
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
  - 🔷 #1376 检索/筛选控件（原型已出、未实现）：`fs-status-chips`（回收状态三态）/ `fs-search-input`（检索框，匹配面 = 标题 OR 位置）/ `fs-sort-toggle`（排序切换）/ `fs-count`（显示 N / 共 N 条）/ `fs-noresult` + `fs-clear-filters`（无结果态）；口径 2 备选为 `fs-chapter-picker`（章节选择，需后端先行）
  - 后端状态机（GUI 只读展示）：status open/resolved（创建即 open，回收走 resolve 端点）；Create/Update DTO 均无 status 字段——行内状态徽标**只读**，无状态切换控件（原型亦无此按钮，见 #1324 拍板）
- 布局说明：纵向单栏——工具栏 → 卡片（筛选/排序条 → 平铺列表）；行内标题 flex-1 truncate 在前，其后依次状态徽标/优先级/位置徽标（均 shrink-0），末尾编辑/删除（悬停显现）；对话框遮罩挂页面根部

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 去创建（library-create-btn / 空态 CTA） | 列表非空或空态 | 打开创建对话框（空表单） | — | POST 成功 → 关框 + reloadKey 刷新 | err toast | 标题必填（title 字段） |
| 行编辑（lib-edit） | 悬停显现铅笔图标 | 打开编辑对话框（预填 title/priority/location/description） | saving 禁用 | PATCH 成功 → 关框 + 刷新 + 顶部「已保存」 | err toast，对话框保持可改重试 | 优先级缺失回填兜底 50 |
| 行删除（lib-delete） | 悬停显现垃圾桶 | ConfirmDialog（lib-confirm-dialog） | DELETE 请求 | ok toast + 列表刷新 | err toast + 关框 | 遮罩点击不关闭（#195）；关闭仅 取消/Esc/确认成功 |
| 对话框保存（library-create-save） | 标题非空 enabled | handleSave（PATCH/POST 父级分支） | saving「保存中…」禁用 | 父级关框 + 刷新 | err toast | 优先级原生 min/max 0-100；ESC/取消关闭；遮罩点击不关闭 |
| AI 提取（extract-entry-lib） | 描边按钮 | AIExtractDialog（类型 = 伏笔，章节选择） | 提取中 | 完成 toast + 最近提取记录 | 失败 toast | 仅 currentProjectId 非 null 渲染；章节下拉**全量加载**（#1407：翻页取满章节列表 `total`，>50 章项目可选第 51 章起） |
| 状态机控件（open/resolved 切换） | 无（原型与实现均无此控件） | — | — | — | — | 后端 status 字段与 resolve/reopen 端点存在，但 GUI **只读展示**状态徽标，不提供切换入口（#1324 拍板：超原型，另议） |
| 🔷 回收状态 chip（#1376 待实现） | 「全部」选中（= 不加筛选条件） | 选中任一 chip → 列表重拉/重filter + 计数更新 + 页码归零 | 列表 loading | 列表与 `显示 N / 共 N 条` 同步 | — | 三态互斥单选（只有两个状态值 → 三态等效覆盖「多选」语义）；「全部」= 不传 status |
| 🔷 检索输入框（#1376 待实现） | 空（不过滤） | 输入即筛（**实时，无需 Enter**） | — | 列表 + 计数更新 | — | 匹配面 = **条目标题 OR 位置文本**（大小写不敏感子串）。标题面可复用后端 `?search=`（title icontains，零改动）；位置面需 `?location=`（**已拍板采纳**）——在此之前纯前端只过滤当前页；**location 为空或不含查询子串者位置面不命中**（口径 1 固有代价，见 §4.2）；清空 = 不过滤 |
| 🔷 出现章节·口径 2 章节选择（#1376 待实现，依赖后端先行） | 空（不过滤） | 「选择章节」→ 章节多选 → 按结构化关联过滤 | — | 列表 + 计数更新 | — | 语义准确无漏项；**依赖 F14 提取侧补 foreshadowing ↔ chapter 关联字段，本期不可用** |
| 🔷 排序切换（#1376 待实现） | 「优先级 高→低」（降序，= 后端 ?sort_by=priority&sort_desc=true 默认值） | 点击 → 反向（低→高）+ 图标换向 | — | 列表重排 | — | 同优先级按 updated_at DESC 兜底（F13 spec §6.2）；切换后页码归零 |
| 🔷 清除筛选（#1376 待实现） | 仅筛选结果 0 条时显示 | 清空 status/位置/章节条件 → 恢复全量 | — | 列表恢复 | — | 不改变排序方向 |
| 🔷 筛选无结果提示（#1376 待实现） | 0 条时替换列表区 | — | — | — | — | 文案「当前筛选条件下没有匹配的伏笔」+ 清除入口；**不得**复用 library-tab-empty（会把「筛掉了」误报成「没有数据」） |

## 3. 验收

- N1：列表行展示标题 + 悬停编辑/删除（D12）
- N2：创建/编辑对话框（标题必填 + 优先级 0-100 默认 50 + 位置/描述）
- N3：删除二次确认（不可恢复文案）
- N4：空态 CTA + 列表非空常驻「去创建」+ AI 提取入口（伏笔类型）
- N5：列表行渲染状态徽标（未回收/已回收，已回收附回收日期）+ 优先级「优先级 {n}」+ 位置徽标（location 原文照显）；状态徽标**只读**，无状态切换控件（与后端 resolve/reopen 端点的差异如实保留）

> 以下 N6-N11 属 **#1376 设计基线（原型已出、实现未做）**——实现前不得据本节判定「已实现」：

- N6（#1376）：筛选/排序条位于列表卡片顶部（与角色页 character-rank-tabs 同位置同形态）；含「回收状态」chip 三态 + 「检索」框（标题 + 位置，实时）+ 「显示 N / 共 N 条」计数 + 排序切换
- N7（#1376）：回收状态筛选 = 三态互斥（全部/未回收/已回收）；切换后列表、计数、页码同步
- N8（#1376）：排序切换在「优先级 高→低 / 低→高」两向间切换，图标随向变化
- N9（#1376）：筛选结果 0 条 → 卡内展示「当前筛选条件下没有匹配的伏笔」+「清除筛选」；空态 `library-tab-empty` 不参与
- N10（#1376）：筛选/排序控件仅 foreshadow 分类渲染（其他分类不出现）
- N11（#1376）：检索框**输入即筛**（无需 Enter）；匹配面 = 条目标题 OR 位置文本（大小写不敏感子串）；原型实测输入「剑」→ 命中标题含「剑」的 4 条 + 位置含「剑」的 1 条（5/8）

## 4. #1376 设计基线：筛选/排序（原型已出 · 未实现）

> 归档来源：本页原型 `design/GUI/foreshadow/foreshadow.html`（多形态属性切换）+ 10 张状态 PNG；
> 截图与断言脚本 `design/GUI/_tools/shot-1376-foreshadow-filter.cjs`（本地 headless，**非 CI**）。

### 4.1 两种筛选栏形态（待用户拍板）

| 形态 | 控件 | 优点 | 代价 | 原型 PNG |
|---|---|---|---|---|
| **A（已拍板）** | 回收状态 chip 三态 + **检索框**（标题 + 位置，实时）+ 排序**切换按钮** | 复用 character-rank-tabs 既有视觉；chip 三态即可覆盖两值状态的全部筛选语义；文本可按「第 2 章」**子串跨多条**命中，且兼作条目标题检索 | 文本自由输入易写错；无法枚举已知值 | `foreshadow-main.png` / `foreshadow-filter-a.png` / `foreshadow-search-title.png` |
| B | 回收状态**下拉** + **优先级区间**（0–100 两输入）+ 出现章节**位置枚举下拉** + 排序**下拉** | 更紧凑；支持优先级区间；枚举下拉无输入错误 | 只能精确匹配既有 location 值，不能子串命中；区间/多选条件下要保持正确 total 与跨页结果需后端补参数 | `foreshadow-filter-b.png` |

### 4.2 「出现章节」两种口径（已拍板：口径 1）

| 口径 | 语义 | 命中示例（原型 8 条种子数据，查询「第 2 章」） | 代价 | 原型 PNG |
|---|---|---|---|---|
| **1（已拍板）** | 单一检索框按**条目标题 OR `location` 文本**子串匹配（标题面 = 复用后端 `?search=`；位置面 = 口径 1） | 命中 **1 条**（林晚照的旧玉佩）——本例「第 2 章」标题面无命中 | 🔴 **位置面：location 为空者必然不命中**；location 未规范写章号者（如「开篇 · 序章梦境」）同样不命中——上例共 **2 条被漏**（无名剑客的遗言 / 未署名的旧信）。文本规范全靠用户自觉 | `foreshadow-chapter-match-text.png` |
| 2 | 按**结构化 `foreshadowing ↔ chapter` 关联**过滤 | 命中 **3 条**（含口径 1 漏掉的两条），无漏项 | 🔴 需 F14 提取侧补关联字段（跨 F12/F14）→ **本期不可用**，跨模块改造，建议单独立 issue 挂后续版本 | `foreshadow-chapter-match-struct.png` |

### 4.3 🔴 后端契约实证（决定「前端 vs 后端筛选」的取舍）

> 本轮以源码为准核实，结论**修正了 issue #1376 正文的假设**（正文称方案 B 的 `status=` / `order_by=priority` 「需同步 API 契约」）：

| 能力 | 后端现状（源码位置） | 结论 |
|---|---|---|
| 状态过滤 | ✅ **已支持**：`GET /projects/{pid}/foreshadowings?status=`（单值精确匹配 `open`/`resolved`）— `backend/src/inkflow/api/routers/foreshadowings.py:146-155`、`infrastructure/database/repositories/foreshadowing_repo.py:179-180` | 状态筛选**零后端改动**（两值 → 三态 chip 全覆盖） |
| 排序 | ✅ **已支持**：`?sort_by=priority&sort_desc=`（白名单 priority/title/status/updated_at/created_at，缺省 priority + 同优先级 updated_at DESC 兜底）— `foreshadowing_repo.py:187-198` | 优先级升/降序**零后端改动** |
| 文本搜索 | ⚠️ **仅匹配 title**：`?search=` → `ForeshadowingORM.title.icontains(search)` — `foreshadowing_repo.py:176-177` | 「出现章节」若走服务端**需新增** `?location=`（或扩展 search 覆盖面） |
| 位置过滤 / 优先级区间 / 章节关联 | ❌ 均**无** | 口径 2 与方案 B 的区间能力需后端先行 |
| 前端机制 | ✅ 已有先例：`useLibraryPagedList(..., extraQuery)`（#1320 角色等级筛选 `?role_rank=` 即走此路，extraQuery 变化即重拉 + 页码归零）— `hooks/useLibraryPagedList.ts:55-61`、`pages/library.tsx:161-167` | 状态/排序可直接复用该机制 |

🔴 **由此推论（分页语义约束）**：#1300/#1320 已确立「筛选须下沉服务端，否则 total 口径错 + 跨页项漏取」。纯前端过滤只作用于当前页——在分页已启用的伏笔列表上会漏掉其他页的命中项。**本轮已拍板：位置面一并服务端化（新增 `?location=`）**，故实现后四项（状态 / 标题检索 / 位置 / 排序）全部走服务端、无跨页漏项。⚠️ `?location=` 落地时须同步 API 契约 + 契约测试（`docs/contract-guard.md` 联保清单）。

### 4.4 原型内设计注释条（实现时**不得**做进产品 UI）

原型每态带一条虚线说明条（`class="design-note"` + `data-design-annotation="1"`），标注该方案的推荐理由与取舍。
⚠️ 这是**评审用设计注解**，不是产品文案——实现阶段一律不渲染，且不得为了「对齐原型」把它加进列表卡片。

### 4.5 拍板结果（2026-10-01 用户确认）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 筛选栏形态 | **A**（chip 组）；**且检索框兼作条目标题检索**——按输入内容实时检索（无需 Enter），匹配面 = 条目标题 OR 位置文本 |
| 2 | 「出现章节」口径 | **口径 1**（位置文本）先落；口径 2（结构化关联）单独立 issue 挂后续版本 |
| 3 | 排序默认方向 | **降序**（priority 大者在前 = 后端默认 + 注入顺序） |
| 4 | 实现落点 | 状态 / 排序 / 标题检索走服务端（后端**已有** `?status=` / `?sort_by=priority` / `?search=`，零后端改动）；**接受新增 `?location=`** 把位置面一并服务端化（避免纯前端只过滤当前页） |

> 原兜底默认（形态 A + 口径 1 + 降序）已与本轮结论一致，不再作为待定项。
