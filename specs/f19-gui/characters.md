# 设定库·角色 — 交互规格

> 页面: characters | 路由: /library?cat=characters | 组件: pages/library.tsx（cat=characters）+ LibraryItemList（withCharacterExtras）+ CharacterDetailPanel + LibraryCreateDialog（cat=characters）
> 对应 design/GUI/characters/（官方简图 characters.html + characters-<state>.png，见后续补图）

## 1. 画面样式

- 原型引用：design/GUI/characters/
- 参考锚点（真实实现）：
  - 端点：GET /api/v1/projects/{pid}/characters（分页 {items,total,offset,limit}）；PATCH /api/v1/characters/{id}；DELETE /api/v1/characters/{id}；GET /api/v1/projects/{pid}/character-groups（分组列表，数组顺序 = 渲染顺序）
  - 等级选项卡（character-rank-tabs，列表顶部 chip 组）：总览 / 主角 / 重要配角 / 配角 / 场景角色 / 一次性角色；激活 = accent 填充（ACTIVE），闲置 surface-3；点击当前等级不取消，需点「全部」恢复
  - 分组卡片：组头「{组名} · {n}人」（lib-group-title，12px ink-2）+ 成员行；未分组收尾（lib-group-ungrouped）；空组隐藏
  - 列表行（lib-item，py-2.5 13px）：名称按钮（lib-name-<id>，可点击 → 打开角色详情面板，hover accent）+ 等级徽标（lib-rank-<id>，圆角胶囊，五档分色：主角 accent / 重要配角 accent/40 / 配角 surface-3 / 场景角色 surface-2 / 一次性角色 surface-3 弱化，未知等级中性兜底）+ 标签 chips（lib-tags-<id>，extra.groups，surface-3 胶囊）+ 悬停操作（D12：opacity 0→100，编辑 lib-edit-<id> 铅笔 / 删除 lib-delete-<id> 垃圾桶；focus-within 键盘可见）
  - 创建/编辑对话框（library-create-dialog，520px）：名称（必填）+ 性格/背景/目标（textarea×3）+ 等级下拉（library-create-rank，必填无默认，placeholder「选择等级」）+ 标签编辑器（TagEditor：输入回车添加；建议标签 = 当前项目角色 extra.groups 并集，数据驱动）
  - 角色详情面板（character-detail-panel，640px 弹层，max-h 85vh 滚动）：标题 = 角色名 + 关闭按钮；分组区（角色分组：多选 checkbox 列表 + 「未分组」选项 + 管理分组…幽灵按钮）；关系区（角色关系：添加关系主按钮 + 关系列表 [空态「暂无关系」；行 = 对方名 · 关系类型 accent + 描述 + 悬停编辑/删除] + 内联关系表单 [对方角色下拉/类型/描述]）
  - 分组管理弹层（character-group-manage-panel，480px）：分组列表（行 = 组名 + 成员数 + 悬停编辑/删除）+ 新建分组表单（分组名/描述）
- 布局说明：内容区 = 等级选项卡 → 分组卡片堆叠（组头 + 成员列表，未分组殿后）；行内操作悬停显现；三个弹层（创建/编辑、详情面板、分组管理）挂页面根部

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 等级选项卡 chip | 总览激活，其余闲置 | 切换 selectedRank → 列表按 extra.role_rank 过滤 | — | 分览渲染（分组卡片同步过滤） | — | 点击当前等级不取消；未知/缺失等级角色只出现在总览；「未分组」仅指分组不含等级 |
| 行名称（lib-name） | 纯文本（flex-1 truncate） | 打开角色详情面板（ref.openDetail） | — | 面板渲染（数据取 items 最新对象） | — | 仅 characters 分类可点；切 tab / 切项目自动关闭面板 |
| 行编辑（lib-edit） | 悬停显现铅笔图标 | 打开编辑对话框（预填现值） | saving 禁用 | PATCH 成功 → 关框 + 刷新 + 顶部「已保存」 | err toast，对话框保持可改重试 | 旧数据无等级 → 占位重选（E14）；标签整体替换语义 |
| 行删除（lib-delete） | 悬停显现垃圾桶 | 打开 ConfirmDialog（lib-confirm-dialog） | DELETE 请求 | ok toast + 列表刷新 | err toast + 关框 | 遮罩点击不关闭（#195）；关闭仅 取消/Esc/确认成功 |
| 去创建（library-create-btn / 空态 CTA） | 列表非空或空态「去创建」 | 打开创建对话框（空表单） | — | POST 成功 → 关框 + 刷新 | err toast | 名称 + 等级双必填才 enabled（E13） |
| 对话框保存（library-create-save） | disabled 直至名称非空且等级已选 | handleSave（PATCH/POST 由父级分支） | saving「保存中…」禁用防重复提交 | 父级关框 + reloadKey 刷新 | err toast（父级） | ESC 关闭；遮罩点击不关闭；body 含完整 extra {role_rank, groups} |
| 详情面板打开/关闭 | 弹层（role=dialog） | 关闭按钮 / onClose | — | 面板卸载 | — | 列表刷新后 item 取最新（group_id 等字段同步） |
| 分组 checkbox（character-group-option） | 多选列表 + 未分组选项 | 勾选 → 即时 PATCH 角色 groups | — | 分组卡片/徽标刷新 | err toast | N:M 多分组（group_ids 权威，旧 group_id 兜底）；「未分组」= 清空选择（互斥语义） |
| 添加/编辑关系（character-rel-add / rel-edit） | 面板内联表单 | 对方角色必选 + 类型 + 描述，提交 | — | ok toast + 关系列表刷新 | err toast | 对方角色下拉 = 排除自身的其余角色（otherCharacters）；编辑模式对方角色 disabled 不可改 |
| 删除关系（character-rel-delete） | 悬停显现 | ConfirmDialog（character-rel 确认） | DELETE | ok toast + 列表移除 | err toast | 确认文案「删除后不可恢复」 |
| 管理分组（character-group-manage） | 幽灵按钮 | 打开分组管理弹层 | — | — | — | 弹层内 CRUD：新建（名称+描述，sort_order 顺位递增）、行编辑、行删除（成员变未分组） |
| 标签编辑器（TagEditor） | 输入框 + 已选 chips | 回车添加；点建议「+ tag」 | — | chip 加入已选 | — | 建议 = 项目内角色 groups 并集；已选去重保序 |

## 3. 验收

- N1：等级选项卡六档（总览+五档）过滤 + 点「全部」恢复
- N2：分组卡片按组渲染（组名 · 人数）+ 未分组收尾 + 空组隐藏
- N3：行名点击打开详情面板（分组多选 / 关系 CRUD / 分组管理闭环）
- N4：创建/编辑对话框名称+等级双必填 gate + 顶部保存指示 + 删除二次确认
- N5：悬停操作按钮 + focus-within 键盘可达（D12）
