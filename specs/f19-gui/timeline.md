# 设定库·时间线 — 交互规格

> 页面: timeline | 路由: /library?cat=timeline | 组件: pages/library.tsx（cat=timeline）+ TimelineView + LibraryCreateDialog（cat=timeline）
> 对应 design/GUI/timeline/（官方简图 timeline.html + timeline-<state>.png，见后续补图）

## 1. 画面样式

- 原型引用：design/GUI/timeline/
- 参考锚点（真实实现，F43 P4）：
  - 端点：GET /api/v1/projects/{pid}/timeline（返回双数组 {event_timeline, narrative_order}）；创建 POST /api/v1/projects/{pid}/timeline/events（注意不是列表端点）；PATCH /api/v1/timeline/events/{id}；DELETE /api/v1/timeline/events/{id}；整体检查 POST /api/v1/projects/{pid}/timeline/check；单事件检查 POST /api/v1/timeline/events/{id}/check
  - 工具栏（timeline-toolbar，flex-wrap）：双序 chips 组（圆角描边容器内：tl-view-narrative「叙事序」默认激活 accent 填充 / tl-view-world「世界序」闲置 ink-2）+ 一致性检查（tl-check-all，描边按钮）+ 图例（tl-legend「点=叙事顺序 · 时间轴=世界内时间」，12px ink-3）
  - 事件列表（library-list，圆角卡片 divide-y）：行 = 标题（flex-1 truncate）+ 时间显示徽标（time_display，surface-3 胶囊，11px）+ 单事件检查按钮（tl-check-one-<id>，描边小按钮，aria-label 含事件标题）
  - 双序切换 = 本地切换显示数组（零额外请求）；narrative_order 为空 → 回退 event_timeline（旧数据兜底）
  - 创建/编辑对话框（library-create-dialog，cat=timeline）：标题（必填，字段名 title）+ 时间显示（time_display）+ 描述
  - 空态：无事件 → library-tab-empty「还没有时间线，去创建」+ CTA；列表非空时工具栏「去创建」（library-create-btn）常显（timeline 非 outline/world 特例）
  - 行内无编辑/删除按钮（真实实现仅「单事件检查」行操作；PATCH/DELETE 端点存在但 GUI 未暴露行内入口）
- 布局说明：纵向单栏——工具栏 → 事件列表；时间显示徽标随行展示（无 time_display 的行不渲染徽标）

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 双序 chips（tl-view-narrative / tl-view-world） | 叙事序默认激活 | 本地切换显示数组（世界序 = event_timeline / 叙事序 = narrative_order 优先） | — | 列表即时切换 | — | narrative_order 空 → 回退 event_timeline；零额外请求（T2/T3 契约） |
| 一致性检查（tl-check-all） | 描边按钮 | POST /timeline/check | 请求中 | 无矛盾 → ok toast「未发现矛盾事件」 | 有矛盾 → warn toast「发现 n 处时间矛盾」；请求失败 → err toast | 矛盾数 = conflicts 数组长度 |
| 单事件检查（tl-check-one） | 行内按钮 | POST /timeline/events/{id}/check | 请求中 | checked=false → warn「该事件无时间信息，跳过检查」；consistent → ok「与上下文一致」 | 有矛盾 → warn（首条冲突 message 或「发现 n 处时间矛盾」）；请求失败 → err toast | 检查结果不入列表持久化；flashbacks 预留 |
| 去创建（library-create-btn / 空态 CTA） | 列表非空或空态 | 打开创建对话框 | — | POST /timeline/events → 关框 + reloadKey 刷新 | err toast | 标题必填（requiredValue=title） |
| 编辑/删除 | 行内不渲染（真实实现） | — | — | — | — | PATCH/DELETE /timeline/events/{id} 端点存在（F43 扁平端点表），GUI 行内未暴露按钮；如后续接入遵循通用对话框/确认框语义 |
| 对话框保存（library-create-save） | 标题非空 enabled | handleSave（timeline 分支创建端点 = /timeline/events） | saving 禁用 | 关框 + 刷新 | err toast | ESC/取消关闭；遮罩点击不关闭 |
| 图例（tl-legend） | 纯文本展示 | — | — | — | — | 无交互 |

## 3. 验收

- N1：双序 chips 切换列表（世界序/叙事序）+ narrative_order 空回退
- N2：整体一致性检查 → ok / warn 双态 toast
- N3：单事件检查 → skip / ok / warn 三态 toast
- N4：创建事件（标题必填）+ 空态 CTA + 列表非空常驻「去创建」
- N5：行内时间显示徽标 + 图例文案
