# 设定库·时间线 — 交互规格

> 页面: timeline | 路由: /library?cat=timeline | 组件: pages/library.tsx（cat=timeline）+ TimelineView + LibraryCreateDialog（cat=timeline）
> 对应 design/GUI/timeline/（官方简图 timeline.html + timeline-<state>.png）
> **Spec 变更**：2026-09-21 #1323 —— ① 补轴线/章分组定义（#1301 的轴此前**无规格依据**，属推断实现；现正式入规格）；② 废除「第N章 = narrative_position」显示（语义错用，见 §1 锚点）；③ 事件按 `source_chapter_id` 章分组。

## 1. 画面样式

- 原型引用：design/GUI/timeline/timeline.html + timeline-<state>.png（empty/narrative/world）
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
│ 工具栏：[叙事序│世界序]  [一致性检查]  图例（12px 说明文案） │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ ● 第十一章 剑心为何物          ← 章分组 header（真实标题）│ │
│ │ ┃  300 年  师父闭关前夜…        [单事件检查] [✎] [🗑]      │ │
│ │ ● 第十二章 夜访剑冢                                      │ │
│ │ ┃  100 年  夜访剑冢…            [单事件检查] [✎] [🗑]      │ │
│ │ ┃  200 年  发现异动痕迹…        [单事件检查] [✎] [🗑]      │ │
│ │ ● 未分章                                                 │ │
│ │ ┃  未知    无章事件…            [单事件检查] [✎] [🗑]      │ │
│ │ 每事件恰好渲染一次（轴即列表，不再「轴 + 列表」两块重复） │ │
│ │ 主轴 = 世界内时间（time_display → time_value+unit → 未知）│ │
│ │ 双序切换 = 本地换数组（narrative_order 空回退旧数据）    │ │
│ └──────────────────────────────────────────────────────────┘ │
│ 空态：library-tab-empty「还没有时间线，去创建」+ CTA         │
└──────────────────────────────────────────────────────────────┘
```
- 参考锚点（真实实现，F43 P4 + #1323）：
  - 端点：GET /api/v1/projects/{pid}/timeline（返回双数组 {event_timeline, narrative_order}，每事件含 source_chapter_id）；创建 POST /api/v1/projects/{pid}/timeline/events（注意不是列表端点）；PATCH /api/v1/timeline/events/{id}；DELETE /api/v1/timeline/events/{id}；整体检查 POST /api/v1/projects/{pid}/timeline/check；单事件检查 POST /api/v1/timeline/events/{id}/check
  - 工具栏（timeline-toolbar，flex-wrap）：双序 chips 组（圆角描边容器内：tl-view-narrative「叙事序」默认激活 accent 填充 / tl-view-world「世界序」闲置 ink-2）+ 一致性检查（tl-check-all，描边按钮）+ 图例（tl-legend「点=叙事顺序 · 时间轴=世界内时间」，12px ink-3）
  - **时间轴 = 章分组容器**（tl-axis，竖向；轴线 + 节点圆点）：每章一个分组（tl-group-<chapterId>），分组 header（tl-group-title-<chapterId>）显示**真实章节标题**（来自 `GET /projects/{pid}/chapters` 的 chapter_id→title 映射，形态照抄 hooks/useOutlineLibrary.ts 的 chapterTitles）；未归章事件（source_chapter_id 空）落 `tl-group-__none__`，header 文案 `lib.tlGroupNone`（「未分章」）；映射缺失时回退 `lib.tlChapterUnknown`（「未知章节」）
  - 事件行（tl-axis-node-<id>）= 主轴（tl-axis-main-<id>，**世界内时间**：time_display → time_value+time_unit → lib.tlTimeUnknown「未知」）+ 标题（flex-1 truncate）+ 单事件检查（tl-check-one-<id>）+ 行内编辑/删除（tl-edit-<id> / tl-delete-<id>，#1302）
  - 🔴 **`narrative_position` 不用于显示章号**（#1323 G2）：它是**单一线性序号**（domain/models/timeline.py；specs/f12-timeline/spec.md §5 明确「不携带第几章第几段的章节语义」），仅用于**排序**与后端一致性检查。旧实现用 `lib.tlChapter`（「第{n}章」）拼章号属语义错用（DB 实测 215 条仅 34 个不同位置值 → 同一「第7章」重复 10 次）；该 key 已移除
  - 双序切换 = 本地切换显示数组（零额外请求）；narrative_order 为空 → 回退 event_timeline（旧数据兜底）
  - 创建/编辑对话框（library-create-dialog，cat=timeline）：标题（必填，字段名 title）+ 时间显示（time_display）+ 描述
  - 空态：无事件 → library-tab-empty「还没有时间线，去创建」+ CTA；列表非空时工具栏「去创建」（library-create-btn）常显（timeline 非 outline/world 特例）
- 布局说明：纵向单栏——工具栏 → 章分组容器（每章一组，组内事件行）；主轴（时间）随行展示
- 🔴 **一致性检查的倒叙/插叙识别为包含式匹配**（#1323 G6）：`timeline_flag` 是**自由文本**，后端同时识别中文（倒叙/插叙/预叙/回忆）与英文（flashback/flashforward）子串；与倒叙/插叙无关的自由文本（如「梦境」）仍按未标记处理

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 双序 chips（tl-view-narrative / tl-view-world） | 叙事序默认激活 | 本地切换显示数组（世界序 = event_timeline / 叙事序 = narrative_order 优先） | — | 列表即时切换（章分组不变，仅组内顺序变） | — | narrative_order 空 → 回退 event_timeline；零额外请求（T2/T3 契约） |
| 一致性检查（tl-check-all） | 描边按钮 | POST /timeline/check | 请求中 | 无矛盾 → ok toast「未发现矛盾事件」 | 有矛盾 → warn toast「发现 n 处时间矛盾」；请求失败 → err toast | 矛盾数 = conflicts 数组长度；倒叙/插叙（含中文自由文本）计入 flashbacks 不计 conflicts |
| 单事件检查（tl-check-one） | 行内按钮 | POST /timeline/events/{id}/check | 请求中 | checked=false → warn「该事件无时间信息，跳过检查」；consistent → ok「与上下文一致」 | 有矛盾 → warn（首条冲突 message 或「发现 n 处时间矛盾」）；请求失败 → err toast | 检查结果不入列表持久化；flashbacks 预留 |
| 去创建（library-create-btn / 空态 CTA） | 列表非空或空态 | 打开创建对话框 | — | POST /timeline/events → 关框 + reloadKey 刷新 | err toast | 标题必填（requiredValue=title） |
| 行内编辑（tl-edit-<id>）/ 删除（tl-delete-<id>） | 悬停/focus-within 显示 | 编辑 → LibraryCreateDialog 编辑模式；删除 → 页面级 ConfirmDialog | saving 禁用 | 关框 + 刷新 | err toast | #1302 交付；PATCH/DELETE /timeline/events/{id} |
| 对话框保存（library-create-save） | 标题非空 enabled | handleSave（timeline 分支创建端点 = /timeline/events） | saving 禁用 | 关框 + 刷新 | err toast | ESC/取消关闭；遮罩点击不关闭 |
| 图例（tl-legend） | 纯文本展示 | — | — | — | — | 无交互 |
| 章分组 header（tl-group-title-<chapterId>） | 纯文本展示（真实章节标题） | — | — | — | — | 无交互；映射缺失 → 「未知章节」；未归章 → 「未分章」 |

## 3. 验收

- N1：双序 chips 切换列表（世界序/叙事序）+ narrative_order 空回退
- N2：整体一致性检查 → ok / warn 双态 toast；**已声明倒叙/插叙（含中文自由文本）不计入 conflicts**（#1323 G6）
- N3：单事件检查 → skip / ok / warn 三态 toast
- N4：创建事件（标题必填）+ 空态 CTA + 列表非空常驻「去创建」
- N5：行内时间显示徽标（主轴）+ 图例文案
- N6：**时间轴为章分组容器** —— 按 source_chapter_id 分组，一章一个 header（tl-group-<chapterId>）；header 用**真实章节标题**，**不含由 narrative_position 拼出的「第N章」**（#1323 G2）
- N7：**每个事件恰好渲染一次** —— tl-axis-node-<id> 数量 == displayed 长度，事件标题在页面上各出现一次（不再「轴 + 列表」两块重复渲染）（#1323 G1）
- N8：**未归章事件落「未分章」组**（tl-group-__none__），不消失；章节映射缺失时 header 退化为「未知章节」占位（#1323 G3）
