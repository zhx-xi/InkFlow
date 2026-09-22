# 设定库·时间线 — 交互规格

> 页面: timeline | 路由: /library?cat=timeline | 组件: pages/library.tsx（cat=timeline）+ TimelineView + LibraryCreateDialog（cat=timeline）
> 对应 design/GUI/timeline/（官方简图 timeline.html + timeline-<state>.png）
> **Spec 变更**：2026-09-21 #1323 —— ① 补轴线/章分组定义（#1301 的轴此前**无规格依据**，属推断实现；现正式入规格）；② 废除「第N章 = narrative_position」显示（语义错用，见 §1 锚点）；③ 事件按 `source_chapter_id` 章分组。
> **Spec 变更**：2026-09-22 #1374（**实现已落地**）—— **双序轴向语义分流**：叙事序轴 = **章**（章刻度 + 章下事件，刻度含「N 个事件」计数）；世界序轴 = **世界内时间**（单轴、无章分组、行尾 = 来源章胶囊）。世界序「纪元分轴」留 0.16.0（#1353，事件无 era 字段）。筛选已实现（按章 / 按事件类型，单选点选；按世界 / 按角色 = 0.16.0）。原型：design/GUI/timeline/timeline.html（状态 narrative / narrative-filter / world / world-multiaxis / empty）。

## 1. 画面样式

- 原型引用：design/GUI/timeline/timeline.html + timeline-<state>.png（#1374 起状态集：empty / narrative / narrative-filter / world / world-multiaxis）
> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：设定库（页面标题）  主题 Select  语言 Select  窗口控制 │
├──────────────────────────────────────────────────────────────┤
│ 标题区：设定库（font-serif 26px）                            │
│ [项目选择器 青云志 ▾]  面包屑：设定库 · 青云志 / 时间线      │
├──────────────────────────────────────────────────────────────┤
│ 分类 tab：角色│世界观│大纲│时间线│伏笔│知识图谱              │
├──────────────────────────────────────────────────────────────┤
│ 工具栏：[叙事序│世界序] [章：全部▾] [类型：全部▾]            │
│         [（0.16.0 参考：世界序-方案B 纪元轴选择器）]          │
│         [一致性检查]  ← 图例 12px ink-3 随序切换             │
│   图例·叙事序「轴=章 · 事件按章推进排列；行内小字=世界内时间」│
│   图例·世界序「轴=世界内时间（升序，未知末尾）· 不再按章分组」│
│ ┌─ 叙事序：轴 = 章（#1374 当前形态） ──────────────────────┐│
│ │ ◆ 第十一章 剑心为何物  1 个事件   ← 章刻度（标题+计数）   ││
│ │ ┃   ○ 青元历 17 年 师父闭关前夜…    [单事件检查] [✎][🗑] ││
│ │ ◆ 第十二章 夜访剑冢  2 个事件                            ││
│ │ ┃   ○ 青元历 217 年 苏云舟下山…                          ││
│ │ ┃   ○ 青元历 297 年 夜访剑冢…                            ││
│ │ ◇ 未分章 1 个事件（灰刻度，落轴末尾；每事件恰好渲染一次） ││
│ └──────────────────────────────────────────────────────────┘│
│ ┌─ 世界序：轴 = 世界内时间（#1374 当前形态） ──────────────┐│
│ │ ● 青元历 17 年 师父闭关前夜…   [第十一章 剑心为何物] [检查] ││
│ │ ● 青元历 217 年 苏云舟下山…  [第十二章 夜访剑冢]         ││
│ │ ● 未知      守陵人失踪…     [未分章]                     ││
│ │ 无章分组；时间升序、未知排末尾；行尾 = 来源章胶囊         ││
│ └──────────────────────────────────────────────────────────┘│
│ 空态：library-tab-empty「还没有时间线，去创建」+ CTA         │
└──────────────────────────────────────────────────────────────┘
```

> ⚠️ **#1374 已实现**（原型见 design/GUI/timeline/；本节描述即当前实现形态）。

### §1.1 双序轴向定义（#1374，已实现）

| 序 | 轴刻度 | 排序键 | 分组 | 行内主信息 | 行尾副信息 |
|----|--------|--------|------|------------|------------|
| **叙事序** | **章**（章节标题原样；「第 N 章」序号由 #999 标题归一化保证，前端零拼接） | 章序（章节列表顺序）→ 章内 `narrative_position`（#1323 合成序） | 按章分组（容器 `tl-chgroup-<chapterId>`，刻度 `tl-chtick-<chapterId>` 含「N 个事件」计数） | 事件标题；世界内时间为行内小字（ink-3 降级，`tl-axis-main-<id>`） | —（章信息即刻度） |
| **世界序** | **世界内时间**（`time_display` → `time_value+time_unit` → 「未知」） | `time_value` 升序（未知排末尾） | **无分组**（单一时间轴，无 `tl-chgroup`） | 时间刻度（tabular-nums，`tl-axis-main-<id>`） | 来源章胶囊（`tl-src-<id>`） |

- **未分章**（`source_chapter_id` 空）：叙事序 = 轴末尾灰刻度（`tl-chtick-__none__`，文案 `lib.tlGroupNone`「未分章」）；世界序 = 行尾胶囊「未分章」
- **未知章节**（`source_chapter_id` 有值但映射缺失）：叙事序刻度退化为 `lib.tlChapterUnknown`「未知章节」占位；世界序胶囊同文案
- 🔴 **纪元分轴（多纪元）不在本变更范围** —— 留 0.16.0（#1353/#1328）：事件无 `era`/`world` 字段、`time_value` 为单标量（f12 spec:84 曾否决「纪元+序号复合键」）→ 0.15.0 世界序只做**单条时间轴**；「纪元多泳道 + 轴选择器」形态见原型 `timeline-world-multiaxis.png`（方案 B 演示，供 0.16.0 参考）
- **筛选维度**（#1374 已实现）：按章（✅ `source_chapter_id` + 章节列表；按钮 `tl-filter-chapter`，面板 `tl-filter-panel` / 选项 `tl-fp-item-<key>`：`all` / 各章节 id / `__none__`）、按事件类型（✅ `timeline_flag`：正叙/倒叙/插叙；按钮 `tl-filter-type`，面板 `tl-filter-type-panel` / 选项 `tl-tp-item-<key>`）；面板含标题行（`lib.tlFilterChapterTitle`「按章筛选」/ `lib.tlFilterTypeTitle`「按事件类型筛选」）+ 勾选框选项；单选点选（选后即过滤 + 面板收起）、客户端筛选（**两序共用**，切序不丢）、重置 = 「全部」；⛔ 按世界/纪元（→ 0.16.0 #1353）、按角色关联（无正式字段，`extra` 预留）——后两者 0.15.0 不排期
- **图例**（`lib.tlLegend.narrative` / `lib.tlLegend.world`，随序切换）：叙事序「轴=章 · 事件按章推进排列；行内小字=世界内时间」/ 世界序「轴=世界内时间（升序，未知末尾）· 不再按章分组；行尾=来源章」
- 🔴 **时间表达 = 纪年式**（用户 2026-09-22 拍板）：时间展示优先 `time_display` 原样（如「青元历 317 年」「始皇三年」）；**不使用相对时间文案**（「xx 年前」「xx 年后」）。`time_value + time_unit` 回退仅为存量占位（纪年式数据由 `time_display` 承载；提取器补该字段 = #1353 范围）

- 参考锚点（真实实现，F43 P4 + #1323）：
  - 端点：GET /api/v1/projects/{pid}/timeline（返回双数组 {event_timeline, narrative_order}，每事件含 source_chapter_id）；创建 POST /api/v1/projects/{pid}/timeline/events（注意不是列表端点）；PATCH /api/v1/timeline/events/{id}；DELETE /api/v1/timeline/events/{id}；整体检查 POST /api/v1/projects/{pid}/timeline/check；单事件检查 POST /api/v1/timeline/events/{id}/check
  - 工具栏（timeline-toolbar，flex-wrap）：双序 chips 组（圆角描边容器内：tl-view-narrative「叙事序」默认激活 accent 填充 / tl-view-world「世界序」闲置 ink-2）+ 筛选两枚（tl-filter-chapter「章：<label>」/ tl-filter-type「类型：<label>」）+ 一致性检查（tl-check-all，描边按钮）+ 图例（tl-legend，12px ink-3，文案随序切换：`lib.tlLegend.narrative` / `lib.tlLegend.world`）
  - **轴主体**（tl-axis，竖向；叙事序 = 章刻度容器 / 世界序 = 单一时间轴）：每事件恰好渲染一次（轴即列表）。叙事序：容器 `tl-chgroup-<chapterId>`（未分章 = `tl-chgroup-__none__`）+ 刻度 `tl-chtick-<chapterId>`（◆ 刻度标记 + 真实章节标题 + 「N 个事件」计数，来自 `lib.tlChCount`）+ 刻度下事件行；世界序：**无 `tl-chgroup`**，事件行平铺在单一轴容器内
  - **章节映射数据面**：`GET /projects/{pid}/chapters`（**翻全量** —— 后端 limit 默认 50/页，215 章项目须 offset 步进拉全，否则刻度大面积「未知章节」）；timeline 与 outline tab 均拉取（见 hooks/useOutlineLibrary.ts）
  - 事件行（tl-axis-node-<id>）= 主轴（tl-axis-main-<id>，**世界内时间**：time_display → time_value+time_unit → lib.tlTimeUnknown「未知」；叙事序降级 ink-3 小字）+ 标题（flex-1 truncate）+ 单事件检查（tl-check-one-<id>）+ 行内编辑/删除（tl-edit-<id> / tl-delete-<id>，#1302）；**世界序行尾 = 来源章胶囊**（tl-src-<id>，章标题 / 「未分章」/「未知章节」）
  - 🔴 **`narrative_position` 不用于显示章号**（#1323 G2）：它是**单一线性序号**（domain/models/timeline.py；specs/f12-timeline/spec.md §5 明确「不携带第几章第几段的章节语义」），仅用于**排序**与后端一致性检查。旧实现用 `lib.tlChapter`（「第{n}章」）拼章号属语义错用（DB 实测 215 条仅 34 个不同位置值 → 同一「第7章」重复 10 次）；该 key 已移除
  - 双序切换 = 本地切换显示数组（零额外请求）；narrative_order 为空 → 回退 event_timeline（旧数据兜底）
  - 创建/编辑对话框（library-create-dialog，cat=timeline）：标题（必填，字段名 title）+ 时间显示（time_display）+ 描述
  - 空态：无事件 → library-tab-empty「还没有时间线，去创建」+ CTA；列表非空时工具栏「去创建」（library-create-btn）常显（timeline 非 outline/world 特例）
- 布局说明：纵向单栏——工具栏 → 章分组容器（每章一组，组内事件行）；主轴（时间）随行展示
- 🔴 **一致性检查的倒叙/插叙识别为包含式匹配**（#1323 G6）：`timeline_flag` 是**自由文本**，后端同时识别中文（倒叙/插叙/预叙/回忆）与英文（flashback/flashforward）子串；与倒叙/插叙无关的自由文本（如「梦境」）仍按未标记处理

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 双序 chips（tl-view-narrative / tl-view-world） | 叙事序默认激活 | 切换**轴语义**（#1374）：叙事序 → **章轴**（章刻度 + 章下事件）；世界序 → **时间轴**（全局时间序、无章分组、行尾来源章胶囊）。实现 = 本地切换显示数组 + 渲染结构分流（零额外请求，T2/T3 契约） | — | 列表即时切换（零额外请求，T2/T3 契约） | — | 叙事序组内 narrative_order 空 → 回退 event_timeline（§5.16 契约）；叙事序组顺序 = 章序（`chapterOrder` 章节列表顺序），章序缺失回退「事件首次出现顺序」 |
| 筛选（tl-filter-chapter / tl-filter-type，#1374） | 描边按钮「章：全部」「类型：全部」（带 filter 图标 + ▾ 箭头） | 展开下拉面板（标题行 + 勾选框选项，单选）；点选即过滤 + 面板收起；两枚面板互斥（开一枚合另一枚） | — | 列表即时过滤（客户端，**对两序共用**）；按钮高亮（非「全部」时 accent）+ 标签回显（如「章：第十二章」「类型：倒叙」） | — | 「全部」= 不过滤；无匹配 → 轻空态（`common.empty`）；按世界 / 按角色 = 0.16.0 不排期（数据面缺字段） |
| 一致性检查（tl-check-all） | 描边按钮 | POST /timeline/check | 请求中 | 无矛盾 → ok toast「未发现矛盾事件」 | 有矛盾 → warn toast「发现 n 处时间矛盾」；请求失败 → err toast | 矛盾数 = conflicts 数组长度；倒叙/插叙（含中文自由文本）计入 flashbacks 不计 conflicts |
| 单事件检查（tl-check-one） | 行内按钮 | POST /timeline/events/{id}/check | 请求中 | checked=false → warn「该事件无时间信息，跳过检查」；consistent → ok「与上下文一致」 | 有矛盾 → warn（首条冲突 message 或「发现 n 处时间矛盾」）；请求失败 → err toast | 检查结果不入列表持久化；flashbacks 预留 |
| 去创建（library-create-btn / 空态 CTA） | 列表非空或空态 | 打开创建对话框 | — | POST /timeline/events → 关框 + reloadKey 刷新 | err toast | 标题必填（requiredValue=title） |
| 行内编辑（tl-edit-<id>）/ 删除（tl-delete-<id>） | 悬停/focus-within 显示 | 编辑 → LibraryCreateDialog 编辑模式；删除 → 页面级 ConfirmDialog | saving 禁用 | 关框 + 刷新 | err toast | #1302 交付；PATCH/DELETE /timeline/events/{id} |
| 对话框保存（library-create-save） | 标题非空 enabled | handleSave（timeline 分支创建端点 = /timeline/events） | saving 禁用 | 关框 + 刷新 | err toast | ESC/取消关闭；遮罩点击不关闭 |
| 图例（tl-legend） | 纯文本展示（文案随序切换，#1374） | — | — | — | — | 无交互 |
| 章刻度（tl-chtick-<chapterId>） | 纯文本展示（◆ 刻度标记 + 真实章节标题 + 「N 个事件」计数） | — | — | — | — | 无交互；映射缺失 → 「未知章节」；未归章 → 「未分章」（`tl-chtick-__none__`，灰刻度、轴末尾） |

## 3. 验收

- N1：双序 chips 切换**轴语义**（#1374：叙事序 = 章轴 / 世界序 = 时间轴）；叙事序组内 narrative_order 空回退 event_timeline（#1323 语义保留）
- N2：整体一致性检查 → ok / warn 双态 toast；**已声明倒叙/插叙（含中文自由文本）不计入 conflicts**（#1323 G6）
- N3：单事件检查 → skip / ok / warn 三态 toast
- N4：创建事件（标题必填）+ 空态 CTA + 列表非空常驻「去创建」
- N5：**轴刻度语义**（#1374）—— 叙事序刻度 = **章**（章节标题原样 + 「N 个事件」计数，`tl-chtick-<chapterId>`）；世界序刻度 = **世界内时间**；图例随序切换（`lib.tlLegend.narrative` / `lib.tlLegend.world`）；行内时间小字（叙事序降级 ink-3）
- N6：**叙事序 = 章轴**（#1374）—— 按 source_chapter_id 分组为章刻度（容器 `tl-chgroup-<chapterId>`）；刻度用**真实章节标题**，**不含由 narrative_position 拼出的「第N章」**（#1323 G2）；组顺序 = 章序（章节列表顺序）→ 组内按章内叙事序排列
- N7：**每个事件恰好渲染一次** —— tl-axis-node-<id> 数量 == 过滤后事件数，事件标题在页面上各出现一次（不再「轴 + 列表」两块重复渲染）（#1323 G1）；**世界序无章分组容器**（#1374）
- N8：**未分章 / 未知章节落位**（#1374）—— 叙事序：未归章事件落轴末尾灰刻度（`tl-chtick-__none__`，文案「未分章」），映射缺失刻度退化「未知章节」；世界序：行尾胶囊显示来源章（未分章 / 未知章节同文案）（#1323 G3 的落位语义保留）
- N9：**筛选**（#1374）—— 按章筛选 → 列表仅显示该章事件（两序共用；未分章项可选）；按事件类型筛选（正叙/倒叙/插叙，包含式匹配对齐后端 #1323 G6 词表）；重置 = 「全部」
- N10：**世界序 = 时间轴**（#1374）—— 事件按 `time_value` 升序（未知排末尾）、无章分组；行尾 = 来源章胶囊（`tl-src-<id>`）
