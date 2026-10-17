# 设定库·时间线 — 交互规格

> 页面: timeline | 路由: /library?cat=timeline | 组件: pages/library.tsx（cat=timeline）+ TimelineView + LibraryCreateDialog（cat=timeline）
> 对应 design/GUI/timeline/（官方简图 timeline.html + timeline-<state>.png）




## 1. 画面样式

- 原型引用：design/GUI/timeline/timeline.html + timeline-<state>.png（状态集：empty / narrative / narrative-filter / world / world-eras / world-eras-multi / world-eras-b（对照）/ world-single（单轴刻度带）/ world-band（多历刻度带）/ world-band-p2（翻页）/ world-band-metric（离群策略对照）/ world-band-dense（252 事件量级）/ world-band-dense-legacy（旧公式复现·对照）/ world-band-night（深色主题底色）/ world-band-pending（待确认区））
> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：设定库（页面标题）  主题 Select  语言 Select  窗口控制 │
├──────────────────────────────────────────────────────────────┤
│ 标题区：设定库（font-serif 26px）                            │
│ [项目选择器 项目甲 ▾]  面包屑：设定库 · 项目甲 / 时间线      │
├──────────────────────────────────────────────────────────────┤
│ 分类 tab：角色│世界观│大纲│时间线│伏笔│知识图谱              │
├──────────────────────────────────────────────────────────────┤
│ 工具栏：[叙事序│世界序] [章：全部▾] [类型：全部▾]            │
│         [（仅世界序+轴族≥2）纪元轴：chip1✓ chip2 chip3]      │
│         [一致性检查]  ← 图例 12px ink-3 随序切换             │
│   图例·叙事序「轴=章 · 事件按章推进排列；行内小字=世界内时间」│
│   图例·世界序「轴=世界内时间（升序）· 行尾=来源章」           │
│   图例·世界序·纪元「轴=纪元 · 默认只显示主力轴 · 勾选切换」   │
│ ┌─ 叙事序：轴 = 章 ────────────────────────────────────────┐│
│ │ ◆ 第十一章 事件乙  1 个事件   ← 章刻度（标题+计数）   ││
│ │ ┃   ○ 示例历 17 年 师父闭关前夜…    [单事件检查] [✎][🗑] ││
│ │ ◆ 第十二章 夜访地点乙  2 个事件                            ││
│ │ ┃   ○ 示例历 217 年 角色甲下山…                          ││
│ │ ┃   ○ 示例历 297 年 夜访地点乙…                            ││
│ │ ◇ 未分章 1 个事件（灰刻度，落轴末尾；每事件恰好渲染一次） ││
│ └──────────────────────────────────────────────────────────┘│
│ ┌─ 世界序 · 刻度带（不定高 + 时间主轴 + 按刻度分页） ─────────┐│
│ │   ▪ 示例历 12        ▪ 示例仙历 8   ← 历列头（色块 + 计数）││
│ │  时间主轴│            │                                    ││
│ │   ●────○ 示例历 17 年┼── 示例历事件 1        [第十一章]     ││
│ │   ○┈┈┈╌1024 年┈┈┈┈┈┈示例仙界事件 1          [未分章]     ││
│ │   ●────○ 示例历 121 年┼─ 示例历事件 2        [第十二章]     ││
│ │   ●────○ 示例历 217 年┼─ 示例历事件 3        [第十三章]     ││
│ │   │    │              └─ 示例历事件 4（同刻度→行高翻倍）   ││
│ │   ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄ ││
│ │   待确认时间 2 条（补时间后确认转正 / 丢弃）               ││
│ │   示例历 12 年 · 有历但时间待考的记录一  [输入][确认][丢弃]││
│ │  ──────────────────────────────────────────────────────  ││
│ │  [8▾] ‹ 上一页  第 1 / 2 页 · 共 15 条  下一页 ›             ││
│ └─────────────────────────────────────────────────────────┘│
│ 每个刻度一「行」：行高 = 该刻度事件数（不定高）；左侧时间主轴给纵向│
│ 序位与分页；离群值只多占一行、不压扁其它刻度                        │
│ 空态：library-tab-empty「还没有时间线，去创建」+ CTA         │
└──────────────────────────────────────────────────────────────┘
```

> ⚠️ 世界序在多纪元数据下为「纪元轴族 + 轴选择器」（见 §1.1 表末两行 / §2 轴选择器行 / §3 N11-N13）。原型见 design/GUI/timeline/。

### §1.1 双序轴向定义

| 序 | 轴刻度 | 排序键 | 分组 | 行内主信息 | 行尾副信息 |
|----|--------|--------|------|------------|------------|
| **叙事序** | **章**（章节标题原样；「第 N 章」序号由标题归一化保证，前端零拼接） | 章序（章节列表顺序）→ 章内 `narrative_position`（合成序） | 按章分组（容器 `tl-chgroup-<chapterId>`，刻度 `tl-chtick-<chapterId>` 含「N 个事件」计数） | 事件标题；世界内时间为行内小字（ink-3 降级，`tl-axis-main-<id>`） | —（章信息即刻度） |
| **世界序 · 单轴**（`era` 全空 = 单一默认轴） | **世界内时间**（`time_display` → 「`era_value` + 单位」→ 「`time_value` + 单位」→ 「未知」） | 刻度序 = `to_global`（默认轴 = `normalized_days`；§2.8 E11 口径）**去重升序**；**纵向位置 = 刻度序号**（等距）、**行高 = 该刻度事件数**；未知事件不进刻度带（见 N17） | **1 条竖轴刻度带**（`tl-band` / `tl-band-spine-<key>`）+ **时间主轴**（`tl-band-main`）：同刻度合并、事件行顺次错开；**按刻度分页**（默认 8 刻度/页，见 N18） | 事件行（`tl-axis-node-<id>`），以**历色连线**（`tl-band-link-<id>`）指回本轴刻度点（行内不重复时间） | 来源章胶囊（`tl-src-<id>`） |
| **世界序 · 多历**（轴族 ≥ 2） | **纪元**（轴 = 正式列 `era`；无纪元事件归**默认轴**「未分纪元」，R6-4） | 轴族顺序 = 事件流**首次出现**；**刻度序** = 跨选中历的 `to_global = era_value / era_scale`（ADR-065 口径）**去重升序**；**纵向位置 = 刻度序号**（序号行、等距）+ **行高 = 该刻度事件数** → 离群值只多占一行 | **同一块内 N 条历竖轴**（`tl-band-head-<key>` + `tl-band-spine-<key>`，每历一色）+ **左侧时间主轴**（`tl-band-main`）+ 右侧事件区；**不上下堆叠泳道卡片**（负例：`tl-lane-*` 不出现）；同刻度只出现一次、事件行顺次错开 | 刻度标签（`tl-band-tick-<key>-<i>`）= 本地时间值 + 单位；事件行**不重复时间**，以**历色连线**指回刻度点 | 来源章胶囊（`tl-src-<id>`） |
| **轴选择器** | — | — | 多选 chips（`tl-axis-chip-<key>`，key = 轴名 / 默认轴哨兵 `__none__`；`aria-pressed` = 勾选态） | 仅**世界序**且**轴族 ≥ 2 条**时可见；默认只勾选**主力轴**（事件数最多，并列取先出现） | 至少保留一条轴（取消最后一条无效） |

- **未分章**（`source_chapter_id` 空）：叙事序 = 轴末尾灰刻度（`tl-chtick-__none__`，文案 `lib.tlGroupNone`「未分章」）；世界序 = 行尾胶囊「未分章」
- **未知章节**（`source_chapter_id` 有值但映射缺失）：叙事序刻度退化为 `lib.tlChapterUnknown`「未知章节」占位；世界序胶囊同文案
- **纪元分轴（多纪元）**：事件以**正式列** `era`（轴名）+ `era_value`（轴内值）+ `era_scale`（流速比）承载纪元（ADR-065；`extra.era` / `extra.era_value` 为遗留快照，不再作为数据源）→ 世界序按轴族渲染 + 轴选择器。**边界**：`time_value` 仍是跨轴全局标量，一致性检查**不按纪元分桶**；`era_scale` 只参与刻度纵向定位（`to_global`），不参与刻度文案。原型：`timeline-world-eras.png`（默认：仅主力轴）/ `timeline-world-eras-multi.png`（多轴同时显示）/ `timeline-world-eras-b.png`（对照：行内时间、不合并）
- **筛选维度**：按章（`source_chapter_id` + 章节列表；按钮 `tl-filter-chapter`，面板 `tl-filter-panel` / 选项 `tl-fp-item-<key>`：`all` / 各章节 id / `__none__`）、按事件类型（`timeline_flag`：正叙/倒叙/插叙；按钮 `tl-filter-type`，面板 `tl-filter-type-panel` / 选项 `tl-tp-item-<key>`）；面板含标题行（`lib.tlFilterChapterTitle`「按章筛选」/ `lib.tlFilterTypeTitle`「按事件类型筛选」）+ 勾选框选项；单选点选（选后即过滤 + 面板收起）、客户端筛选（**两序共用**，切序不丢）、重置 = 「全部」；按世界/纪元 = 世界序**轴选择器**（见 §1.1 表末两行 —— 控制**显示哪几条纪元轴**，与「筛选」按钮语义不同，不做按轴过滤）、⛔ 按角色关联（无正式字段，`extra` 预留）
- **图例**（`lib.tlLegend.narrative` / `lib.tlLegend.world` / `lib.tlLegend.worldEras`，随序与选择器切换）：叙事序「轴=章 · 事件按章推进排列；行内小字=世界内时间」/ 世界序「轴=世界内时间（升序，未知末尾）· 不再按章分组；行尾=来源章」/ 世界序·纪元「轴=纪元 · 每轴独立时间刻度 · 勾选控制显示哪几条轴」
- 🔴 **时间表达 = 纪年式**：时间展示优先 `time_display` 原样（如「示例历 317 年」「始皇三年」）；**不使用相对时间文案**（「xx 年前」「xx 年后」）。`time_value + time_unit` 回退仅为存量占位；世界序刻度回退链 = `time_display` → 「`era_value` + 单位」→ 「`time_value` + 单位」→ 「未知」；轴名**不进入**刻度文案（只在历列头出现）—— 提取器补 `time_display` / 纪元字段归 f12 §2.8 E8

- 参考锚点：
  - 端点：GET /api/v1/projects/{pid}/timeline（返回双数组 {event_timeline, narrative_order}，每事件含 source_chapter_id）；创建 POST /api/v1/projects/{pid}/timeline/events（注意不是列表端点）；PATCH /api/v1/timeline/events/{id}；DELETE /api/v1/timeline/events/{id}；整体检查 POST /api/v1/projects/{pid}/timeline/check；单事件检查 POST /api/v1/timeline/events/{id}/check
  - 工具栏（timeline-toolbar，flex-wrap）：双序 chips 组（圆角描边容器内：tl-view-narrative「叙事序」默认激活 accent 填充 / tl-view-world「世界序」闲置 ink-2）+ 筛选两枚（tl-filter-chapter「章：<label>」/ tl-filter-type「类型：<label>」）+ 轴选择器（`tl-axis-picker`，文案「纪元轴：」+ chips `tl-axis-chip-<key>`，key = 轴名 / 默认轴哨兵 `__none__`，`aria-pressed` = 勾选态；**仅世界序 + 轴族 ≥ 2 条**时可见）+ 一致性检查（tl-check-all，描边按钮）+ 图例（tl-legend，12px ink-3，文案随序切换：`lib.tlLegend.narrative` / `lib.tlLegend.world` / `lib.tlLegend.worldEras`）
  - **轴主体**（tl-axis，竖向；叙事序 = 章刻度容器 / 世界序 = 刻度带）：每事件恰好渲染一次（轴即列表）。叙事序：容器 `tl-chgroup-<chapterId>`（未分章 = `tl-chgroup-__none__`）+ 刻度 `tl-chtick-<chapterId>`（◆ 刻度标记 + 真实章节标题 + 「N 个事件」计数，来自 `lib.tlChCount`）+ 刻度下事件行；世界序：**无 `tl-chgroup`**；**世界序刻度带**：容器 `tl-band`（**单块**），左侧 N 条历竖轴（`tl-band-head-<key>` 历名 + 色块 + 计数；`tl-band-spine-<key>` 一色一轴；刻度点 `tl-band-node-<key>-<i>` + 标签 `tl-band-tick-<key>-<i>`），右侧事件区（`tl-axis-node-<id>`，`tl-band-link-<id>` 历色连线指回本历刻度点）；刻度纵向位置 = `to_global`；同刻度只出现一次、事件行顺次错开；时间未知事件不进刻度带（归待确认区，见 N17）。**单轴**（`era` 全空）= 1 条竖轴刻度带
  - **章节映射数据面**：`GET /projects/{pid}/chapters`（**翻全量** —— 后端 limit 默认 50/页，215 章项目须 offset 步进拉全，否则刻度大面积「未知章节」）；timeline 与 outline tab 均拉取（见 hooks/useOutlineLibrary.ts）
  - 事件行（tl-axis-node-<id>）= 主轴（tl-axis-main-<id>，**世界内时间**：time_display → time_value+time_unit → lib.tlTimeUnknown「未知」；叙事序降级 ink-3 小字）+ 标题（flex-1 truncate）+ 单事件检查（tl-check-one-<id>）+ 行内编辑/删除（tl-edit-<id> / tl-delete-<id>）；**世界序行尾 = 来源章胶囊**（tl-src-<id>，章标题 / 「未分章」/「未知章节」）。⚠️ 世界序（刻度带）的**事件行不渲染 `tl-axis-main-<id>`**（时间刻度在刻度带 `tl-band-tick-<key>-<i>`；单轴与多历一致）
  - 🔴 **`narrative_position` 不用于显示章号**：它是**单一线性序号**（domain/models/timeline.py；specs/f12-timeline/spec.md §5 明确「不携带第几章第几段的章节语义」），仅用于**排序**与后端一致性检查；章号由章节标题承载，前端不由序号拼「第 N 章」（同一序号会被多章复用 → 章号重复，`lib.tlChapter` 不存在）
  - 双序切换 = 本地切换显示数组（零额外请求）；narrative_order 为空 → 回退 event_timeline（旧数据兜底）
  - 创建/编辑对话框（library-create-dialog，cat=timeline）：标题（必填，字段名 title）+ 时间显示（time_display）+ **纪元（`era`，testid `library-create-era`）+ 纪元内数值（`era_value`，testid `library-create-era-value`）**（写入正式列 `era` / `era_value`）+ 描述
  - 空态：无事件 → library-tab-empty「还没有时间线，去创建」+ CTA；列表非空时工具栏「去创建」（library-create-btn）常显（timeline 非 outline/world 特例）
- 布局说明：纵向单栏——工具栏 → 序主体（叙事序 = 章分组容器，每章一组、组内事件行；世界序 = 刻度带，左侧历竖轴 + 时间主轴、右侧事件区）→ 待确认区（仅世界序有内容时渲染）
- 🔴 **一致性检查的倒叙/插叙识别为包含式匹配**：`timeline_flag` 是**自由文本**，后端同时识别中文（倒叙/插叙/预叙/回忆）与英文（flashback/flashforward）子串；与倒叙/插叙无关的自由文本（如「梦境」）仍按未标记处理

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 双序 chips（tl-view-narrative / tl-view-world） | 叙事序默认激活 | 切换**轴语义**：叙事序 → **章轴**（章刻度 + 章下事件）；世界序 → **时间轴**（全局时间序、无章分组、行尾来源章胶囊）。实现 = 本地切换显示数组 + 渲染结构分流（零额外请求，T2/T3 契约） | — | 列表即时切换（零额外请求，T2/T3 契约） | — | 叙事序组内 narrative_order 空 → 回退 event_timeline（§5.16 契约）；叙事序组顺序 = 章序（`chapterOrder` 章节列表顺序），章序缺失回退「事件首次出现顺序」 |
| 筛选（tl-filter-chapter / tl-filter-type） | 描边按钮「章：全部」「类型：全部」（带 filter 图标 + ▾ 箭头） | 展开下拉面板（标题行 + 勾选框选项，单选）；点选即过滤 + 面板收起；两枚面板互斥（开一枚合另一枚） | — | 列表即时过滤（客户端，**对两序共用**）；按钮高亮（非「全部」时 accent）+ 标签回显（如「章：第十二章」「类型：倒叙」） | — | 「全部」= 不过滤；无匹配 → 轻空态（`common.empty`）；按世界/纪元 = 世界序轴选择器（语义不同）；按角色 = 不排期（数据面缺字段） |
| 一致性检查（tl-check-all） | 描边按钮 | POST /timeline/check | 请求中 | 无矛盾 → ok toast「未发现矛盾事件」 | 有矛盾 → warn toast「发现 n 处时间矛盾」；请求失败 → err toast | 矛盾数 = conflicts 数组长度；倒叙/插叙（含中文自由文本）计入 flashbacks 不计 conflicts |
| 单事件检查（tl-check-one） | 行内按钮 | POST /timeline/events/{id}/check | 请求中 | checked=false → warn「该事件无时间信息，跳过检查」；consistent → ok「与上下文一致」 | 有矛盾 → warn（首条冲突 message 或「发现 n 处时间矛盾」）；请求失败 → err toast | 检查结果不入列表持久化；flashbacks 预留 |
| 去创建（library-create-btn / 空态 CTA） | 列表非空或空态 | 打开创建对话框 | — | POST /timeline/events → 关框 + reloadKey 刷新 | err toast | 标题必填（requiredValue=title） |
| 行内编辑（tl-edit-<id>）/ 删除（tl-delete-<id>） | 悬停/focus-within 显示 | 编辑 → LibraryCreateDialog 编辑模式；删除 → 页面级 ConfirmDialog | saving 禁用 | 关框 + 刷新 | err toast | PATCH/DELETE /timeline/events/{id} |
| 对话框保存（library-create-save） | 标题非空 enabled | handleSave（timeline 分支创建端点 = /timeline/events；payload 含 `era`（去空白）+ `era_value`（数值；空串 = 无轴内值/清除）） | saving 禁用 | 关框 + 刷新 | err toast（`era` 超长 / `era_value` 非有限 → 422） | ESC/取消关闭；遮罩点击不关闭 |
| 轴选择器（tl-axis-picker / tl-axis-chip-<key>） | **仅世界序且轴族 ≥ 2 条**时可见；默认只勾选**主力轴**（事件数最多，并列取先出现）；chip 文案 = 轴名（默认轴 = 「未分纪元」） | 点选 chip → 切换勾选态 → 刻度带即时重渲染（客户端，零额外请求） | — | 列表重渲染为选中历的竖轴（刻度带，每选中历一条） | — | **至少保留一条轴**：取消最后一条 → 无效；轴族 == 1 条（无纪元数据）→ 选择器不渲染，世界序为**单轴刻度带**（1 条竖轴） |
| 刻度带（`tl-band`；历列头 `tl-band-head-<key>` / 竖轴 `tl-band-spine-<key>` / 刻度点 `tl-band-node-<key>-<i>` + 标签 `tl-band-tick-<key>-<i>` / 连线 `tl-band-link-<id>`；时间主轴 `tl-band-main` + 行参考线 `tl-band-rowguide` + 主轴刻度点 `tl-band-mainnode-<i>`） | 纯文本展示（每历一色：列头 = 历名 + 计数；轴上刻度 = 本地时间值；**配了历法的轴 → 后端换算的 `calendar_date` 文案**（`[N 劫] [年号] X 年 [Y 月 [Z 日]]`，粒度按本页相邻刻度自适应，见 N19）） | — | — | — | — | 无交互；**每个刻度一「行」、行高 = 该刻度事件数**（不定高）；**纵向位置 = 刻度序号**（离群值不压扁其余刻度）；**同刻度只出现一次**、事件行顺次错开；容器底色 = **页面底色 token**（`bg-bg`），保留边框 / 圆角 / `shadow-card`；**未配历法零回归**（回落「N 日」整数、亚日小数同日归整；换算由后端下发 → 前端**零日历数学**） |
| 刻度带分页（**共享 `Pagination`**，`testIdPrefix="tl-band-page"` → `tl-band-pager` 容器 / `tl-band-page-prev` / `tl-band-page-info` / `tl-band-page-next` / `tl-band-page-size-select`） | 页码器 = 公共分页组件形态：**每页刻度数选择器（`[8, 16, 32, 64]`，默认 8）** + 「‹ 上一页」+「第 {page} / {pages} 页 · 共 {total} 条」（`{total}` = **总刻度数**）+「下一页 ›」；首页禁用「上一页」、末页禁用「下一页」 | 点上一页 / 下一页 → **按刻度**推进一页；**切每页刻度数 → 回到第 1 页**（页数重算、`tl-band-page-info` 更新、刻度集合与事件重算） | — | 刻度带即时重渲染（客户端，零额外请求） | — | **分页单位 = 时间刻度**（不是事件条数，语义不变）；翻页后**刻度集合变化**（事件随刻度切片，其它页的事件不在 DOM）；每页刻度数档位 = `BAND_TICK_PAGE_SIZES`（`[8,16,32,64]`），默认 `BAND_TICKS_PER_PAGE` = 8；条目文案沿用公共组件的「共 N 条」（N = 刻度数）——与同页待确认区同源；未定事件**不参与**刻度分页（待确认区自有分页，见下行） |
| **待确认区（`tl-pend`）** | 标题「待确认时间 N 条」+ 六列表头（**原文时间 / 事件 / 来源 / 时间（可填）/ 未定原因 / 操作**）+ 行列表 + 分页条。每行「确认」**默认禁用**（须先补时间）、「丢弃」可点 | 补时间 → 「确认」启用 → 点确认 = **转正**（该条物化为正式事件、出现在刻度带，并从待确认区消失）；点「丢弃」= 该条丢弃、正式表零变更 | 请求中（按钮禁用） | 列表即时刷新（转正项进刻度带；总数 −1） | err toast（保持行不变） | **可达 100%**：分页（复用公共 `Pagination`，`tl-pend-size-select` 每页 20 / 50 / 100 条 + `tl-pend-info` 总数）；空 → 整块不渲染；**不存在「未知」表达** |
| 图例（tl-legend） | 纯文本展示（文案随序切换） | — | — | — | — | 无交互 |
| 章刻度（tl-chtick-<chapterId>） | 纯文本展示（◆ 刻度标记 + 真实章节标题 + 「N 个事件」计数） | — | — | — | — | 无交互；映射缺失 → 「未知章节」；未归章 → 「未分章」（`tl-chtick-__none__`，灰刻度、轴末尾） |

## 3. 验收

- N1：双序 chips 切换**轴语义**：叙事序 = 章轴 / 世界序 = 时间轴；叙事序组内 narrative_order 空回退 event_timeline
- N2：整体一致性检查 → ok / warn 双态 toast；**已声明倒叙/插叙（含中文自由文本）不计入 conflicts**
- N3：单事件检查 → skip / ok / warn 三态 toast
- N4：创建事件（标题必填）+ 空态 CTA + 列表非空常驻「去创建」
- N5：**轴刻度语义**—— 叙事序刻度 = **章**（章节标题原样 + 「N 个事件」计数，`tl-chtick-<chapterId>`）；世界序刻度 = **世界内时间**；图例随序切换（`lib.tlLegend.narrative` / `lib.tlLegend.world`）；行内时间小字（叙事序降级 ink-3）
- N6：**叙事序 = 章轴**—— 按 source_chapter_id 分组为章刻度（容器 `tl-chgroup-<chapterId>`）；刻度用**真实章节标题**，**不含由 narrative_position 拼出的「第N章」**；组顺序 = 章序（章节列表顺序）→ 组内按章内叙事序排列
- N7：**每个事件恰好渲染一次** —— tl-axis-node-<id> 数量 == 过滤后事件数，事件标题在页面上各出现一次（不再「轴 + 列表」两块重复渲染）；**世界序无章分组容器**
- N8：**未分章 / 未知章节落位**—— 叙事序：未归章事件落轴末尾灰刻度（`tl-chtick-__none__`，文案「未分章」），映射缺失刻度退化「未知章节」；世界序：行尾胶囊显示来源章（未分章 / 未知章节同文案）
- N9：**筛选**—— 按章筛选 → 列表仅显示该章事件（两序共用；未分章项可选）；按事件类型筛选（正叙/倒叙/插叙，包含式匹配对齐后端词表）；重置 = 「全部」
- N10：**世界序 = 时间轴**—— 事件按 `time_value` **归一日尺度**升序、无章分组（未知事件不进刻度带，见 N17）；行尾 = 来源章胶囊（`tl-src-<id>`）
- N11：**轴选择器**—— 世界序且**轴族 ≥ 2 条**时渲染 `tl-axis-picker`；chip = `tl-axis-chip-<key>`（key = 轴名 / 默认轴 `__none__`），`aria-pressed` 反映勾选；**默认只勾选主力轴**（事件数最多者）；**叙事序不渲染**选择器（轴选择器只属世界序）
- N12：**按选中轴渲染历竖轴**—— 每条选中轴在刻度带内一条历竖轴（`tl-band-head-<key>` / `tl-band-spine-<key>`），轴名只在该历列头出现一次；轴内刻度按 `to_global` 升序（见 N15）；未勾选的轴不渲染；**每个事件恰好渲染一次**（跨轴无重复）
- N13：**默认轴（R6-4）**—— 无纪元事件归默认轴「未分纪元」（可与纪元轴同时勾选；事件不丢、不改判）；**纪元数据存在但轴族仅 1 条**（所有事件同纪元）视为「有纪元数据」→ **该历 1 条竖轴刻度带**（见 N15），**不渲染选择器**
- N14：**刻度标签回退链**—— 刻度标签 = `time_display` 原样 → 「`era_value` + `time_unit`」→ 「`time_value` + `time_unit`」→ 「未知」（`lib.tlTimeUnknown`）；轴名**不进入**刻度标签（只在历列头出现）
- N15：**多历共存刻度带**—— 世界序渲染**单个块** `tl-band`：左侧 **N 条历竖轴**（`tl-band-head-<key>` = 历名 + 色块 + 计数；`tl-band-spine-<key>` 一色一轴），右侧事件区；**无上下堆叠的 `tl-lane-*` 卡片**。**刻度纵向位置 = `to_global = era_value / era_scale`**（ADR-065 口径）→ **不同流速的历，刻度隔断疏密不同**（负例：把 `era_scale` 从 1 改成 10，同一 `era_value` 的刻度必须上移，且不得落到其它历的刻度位置）。**同刻度多事件**：刻度 `tl-band-tick-<key>-<i>` / 刻度点 `tl-band-node-<key>-<i>` 只出现一次，事件行 `tl-axis-node-<id>` 顺次错开（无重叠）。**事件↔刻度对应**：每个事件行有一条 `tl-band-link-<id>` 连到**本历**竖轴上的刻度点（他历事件不得连到他历轴上）。**单轴**（`era` 全空）= **1 条竖轴**刻度带（不平铺）。未知时间事件不进刻度带（归待确认区，见 N17）。既有行为不回归：轴选择器（轴族 ≥ 2 才显示）、来源章胶囊 `tl-src-<id>`、单事件检查、一致性检查、按章/按类型筛选
- N16：**刻度带布局**—— ① **未知事件不进刻度带**（见 N17）：画布高度**不随未知事件数增长**；② **不定高**：同一轴内不同刻度行高不同，且行高 = `BAND_ROW_PAD * 2 + 该刻度事件数 * BAND_ROW_H`（与该刻度事件数正相关）；③ **分页按刻度**：每页 `BAND_TICKS_PER_PAGE` = 8，翻页后**刻度集合**变化（负例：第 1 页含「示例历 17 年」不含「示例历 517 年」，第 2 页反之），首页禁用「上一页」、末页禁用「下一页」；④ **时间主轴**：`tl-band-main` 存在，主轴刻度点（`tl-band-mainnode-*`）数 = 本页刻度行数（可据此定位）；⑤ **离群值不压扁**：构造「1 个极大值 + 若干正常值」→ 其它刻度行的 `top` 与不含离群值时**逐行相等**（序号行布局的结构性免疫）；⑥ **底色**：刻度带容器 class 含 `bg-bg` 且**不含** `bg-surface`；浅色 + 深色两主题目视各一次（`timeline-world-band.png` / `timeline-world-band-night.png`），边框 / 圆角 / 事件行悬停态不回归；⑦ **单轴（`era` 全空）与多历（轴族 ≥2）两态均正确**；⑧ **既有不回归**：来源章胶囊 / 单事件检查 / 一致性检查 / 按章·按类型筛选。**负例**：`tl-lane-*` / `tl-timenode-*` 不出现；刻度带**不**渲染 `tl-axis-main-<id>`
- N17：**零未知 + 待确认区**—— ① 世界序**不渲染**「未知」区块（`tl-band-unknown` / `tl-band-unknown-head` / `tl-band-unknown-list` 均不存在）；`unknown` 事件**不出现在刻度带**；② 待确认区（`tl-pend`）渲染于刻度带**下方**、分页可达 100%（复用公共 `Pagination`，`testIdPrefix="tl-pend"` → `tl-pend-info` 含「共 N 条」、`tl-pend-size-select` 可改每页条数；条数 > 每页条数时可翻页翻到末条）；③ 每行含**原文时间**（`tl-pend-raw-*`，原文为空 → 占位文案）+ **未定原因**（`tl-pend-reason-*`）+ 时间输入（`tl-pend-time-*`）+ 单位选择 + 「确认」（`tl-pend-confirm-*`，**未填时间时 `disabled`**）+ 「丢弃」（`tl-pend-discard-*`）；④ 确认（带时间）→ 该条**转正**：正式表 +1、刻度带出现该事件、待确认区 −1；⑤ 丢弃 → 正式表**零变更**、待确认区 −1；⑥ **负例**：不存在「未知 N」文案；确认按钮在未填时间时不可用。**既有不回归**：不定高刻度 / 时间主轴 / 按刻度分页 / 离群不压扁；页面底色；单轴 + 多历两态；来源章胶囊 / 单事件检查 / 一致性检查 / 按章·按类型筛选；两段式 stage/confirm/cancel。
- N18：**刻度带分页复用公共组件 + 每页刻度数可选**—— ① 页脚由**共享 `Pagination`** 渲染（`testIdPrefix="tl-band-page"`）：`tl-band-page-size-select` **存在**（自绘 pager 版本无此元素 → 契约可分辨）；② 档位 = **8 / 16 / 32 / 64**，**默认 8**（首屏分页节奏与默认每页 8 刻度一致）；③ **切到 32 → 本页刻度行数 = 32 且回到第 1 页**（负例：先翻到第 2 页再切档 → `info` = 「第 1 / 3 页 · 共 80 条」、`prev` 禁用、本页含第 32 个刻度而页大小 8 时该刻度不在 DOM）；④ **页码信息语义不丢**：`tl-band-page-info` 含 **当前页 / 总页 / 总刻度数**（「共 N 条」，N = 总刻度数）；首末页禁用态正确（80 刻度 / 每页 8 → 末页余 8）；⑤ **分页单位仍是时间刻度**（翻页后刻度集合变化）；**既有不回归**：不定高刻度 / 时间主轴 / 按刻度分页 / 离群不压扁；页面底色。
- N19：**刻度标签历法换算显示**（ADR-068）—— ① 事件带 `calendar_date`（后端按轴换算；未配历法的轴 = `null`）→ 刻度标签显示 `[N 劫] [年号] X 年 [Y 月 [Z 日]]`；② **粒度按本页相邻刻度自适应**：取「相邻标签**互不相同**」的最粗档（`X 年` → `X 年 Y 月` → `X 年 Y 月 Z 日`）⇒ 同一页内**不会出现两个相同的刻度标签**；③ `era_cycle` 生效 ⇒ 前插「N {label}」（如「3 劫 250 年」），`epoch_label` 非空 ⇒ 「开元 9 年」—— 年号 / 纪元名是**轴数据**，前端**不硬编码**；④ **未配历法 ⇒ 零回归**：回落「N 日」**整数**（亚日小数**同日归整** → `0.79 日` / `3.27 日` 不再出现；负例：`0.79` 显示「0 日」）；⑤ **双轴各按自己历法**（D1）：同一日数在两轴上各显示自己的年月日；⑥ **前端零日历数学**（换算结果由后端下发；前端只「选粒度 + 拼文案」）。**既有不回归**：不定高 / 主轴 / 按刻度分页 / 离群不压扁；页面底色；零未知 + 待确认区。
