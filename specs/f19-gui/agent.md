# Agent 配置/模板 — 交互规格

> 页面: agent | 路由: /settings?cat=agent（+ /settings?cat=templates）| 组件: pages/settings.tsx（AgentPanel / TemplatesPanel）+ components/AgentChainCard、AgentList、AgentEditDialog、TemplateDialog、AgentRelationEditor
> 对应 design/GUI/agent/（官方简图 agent.html + agent-<state>.png，见后续补图）

## 1. 画面样式（简图/原型）

- 原型引用：design/GUI/agent/agent.html + agent-<state>.png（Agent 链卡片 / 角色池展开 / 依赖编辑器 / Agent 列表 / 编辑弹窗 / 模板列表 / 模板编辑弹窗 / 风险确认框等状态截图）

> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：设置（页面标题）   主题 Select   语言 Select   窗口控制   │
├──────────┬───────────────────────────────────────────────────┤
│ 分类导航   │ Agent 分类（?cat=agent）                          │
│ ▸ 常规    │ 写作 Agent 链卡片（AgentChainCard）               │
│ ▸ 模型    │   角色行×N：图标+角色名+状态徽标+槽位号+↑↓+        │
│ ▸ Agent  │   模型下拉+依赖入口+Switch 开关                    │
│ ▸ 模板    │   ＋添加角色 → 角色池（真源未进链角色）            │
│ ▸ 技能    │ 默认模型 Select（chat 模型扁平列表）               │
│ ▸ 账户    │ Agent 列表（AgentList）                           │
│ 激活项高亮│   [＋新建 Agent]                                  │
│          │   内置卡片：名称+内置徽标+描述+工具/技能 chips     │
│          │   （只读：详情/复制）   自定义卡片（编辑/删除）     │
│          │ ────────────────────────────────────────────       │
│          │ 模板分类（?cat=templates，TemplatesPanel）          │
│          │   标题行 [＋新建模板]                              │
│          │   模板卡片列表：名称+默认徽标+描述+被引用数        │
│          │   编辑 / 设为默认 / 删除 三按钮                    │
└──────────┴───────────────────────────────────────────────────┘
```
- 参考锚点（以真实组件为准，真实实现优先于 §14 master）：
  - Agent 分类（AgentPanel）：AgentChainCard（写作 Agent 链，角色行开关列表 + 添加角色 + 依赖入口）→ 默认模型 Select → AgentList（Agent 管理列表）
  - Agent 链角色行：图标块 + 角色名 + 状态徽标 + 槽位号 + 上移/下移 + 模型下拉（开启时）+ 依赖入口（GitBranch）+ Switch；角色来源 = agents 真源按 role_key 派生（内置 builtin）∪ 模板自定义角色 ∪ 角色池添加
  - 三态语义（#225）：value=null → 关闭（disabled 徽标）；字符串 → 开启且指定模型；AGENT_DEFAULT_SENTINEL（__default__）→ 跟随默认（「默认模型」徽标）；模型未注册 → warn 色徽标（未注册模型/模型格式需修正）
  - 槽位与顺序：槽位号徽标（agent-order-slot）+ 上移/下移按钮；移动/开关在配置驱动模式（agent_order 非空）下同步改写 agent_order 并压缩空层
  - 角色池（添加角色）：agents 真源中未进链的角色按钮，点选即加入链尾 + 写入 sentinel
  - 依赖编辑器：点行内 GitBranch 展开 AgentRelationEditor（角色间依赖关系区）
  - 默认模型 Select：chat 模型扁平化列表（provider-configs），绑定 config.model
  - Agent 列表：卡片列表 — 名称（含 icon）+ 内置徽标 + 描述 + 工具/技能 chips + prompt 两行截断；内置只读（详情/复制按钮），自定义可编辑/删除；顶部「新建 Agent」按钮；空列表显示「无自定义 Agent」文案
  - 模板分类（TemplatesPanel）：标题行 + 「新建模板」按钮；模板卡片列表 — 名称 + 默认徽标（ok 色）+ 描述 + 被引用数徽标 + 编辑/设为默认/删除三按钮
  - 弹窗族：AgentEditDialog（620px）/ TemplateDialog（600px，max-h 85vh 可滚动）/ 详情弹窗（560px）/ 风险确认框（420px）
- 布局说明：Agent 分类自上而下为「链配置 → 默认模型 → Agent 实体管理」三层：链卡片逐角色一行（开关/模型/顺序/依赖），其后为全局默认模型下拉，最下为可增删改的 Agent 列表。模板分类为标题 + 按钮 + 卡片列表，所有变更走「即改即存 PATCH（链/默认模型）」或「弹窗表单提交（Agent/模板 CRUD）」。

## 2. 动作样式（按钮 × 状态表，逐控件）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 链角色开关 | Switch，checked=value 为字符串 | 开 → 写 sentinel 跟随默认；关 → 显式 null | persist PATCH 在途（in-flight 守卫） | store 合并 + 徽标刷新 | err toast「保存失败」，store 不被污染 | 关同步从 agent_order 剔除并压缩空层；开（配置驱动模式）插入默认槽位；「至少 1 个启用角色」由后端约束（422） |
| 链角色模型下拉 | 开启时显示，选项 = 跟随默认 + chat 模型列表 | 选择模型 → agentPatch 写入 | persist PATCH 在途 | 徽标更新为模型名 | err toast + 回退 | 选择未注册模型 → warn 徽标提示 |
| 槽位号 + 上移/下移 | 槽位号徽标 + ↑/↓ 按钮（首层上移禁用、末层下移禁用） | 上移并入上一层（并行），下移并入下一层 | — | agent_order 更新 + 槽位号刷新 | — | 移动空层压缩；未启用角色移动时自动启用（sentinel）防后端 422 |
| 依赖入口 | GitBranch 按钮 | 展开/收起 AgentRelationEditor | — | 依赖关系区渲染（变更即存） | — | 与开关独立展开态 |
| 添加角色 | 「+ 添加角色」按钮 | 展开角色池（agents 真源未进链角色） | — | 点角色 → 入链尾 + sentinel + 关闭角色池 | — | 已进链角色不显示 |
| 默认模型 Select | config.model 当前值（未设显示占位） | 选择 → setConfig + persist | PATCH 在途 | store 合并 | err toast | 无当前项目时 persist 直接 return（不保存） |
| Agent 新建 | 「新建 Agent」按钮（agent-new-btn） | 打开 AgentEditDialog（空表单） | — | — | — | 挂载即 3 GET（agents/工具目录/技能列表），失败静默不阻塞 |
| Agent 编辑/保存 | 自定义卡片「编辑」按钮 | 打开 AgentEditDialog（回显）→ 保存 → create/update | 弹窗内保存中 | ok toast「已保存」+ 关闭 | err toast + 保持打开 | 名称必填（nameError 内联）；内置 Agent 无编辑/删除按钮 |
| Agent 删除 | 自定义卡片「删除」按钮（err 色描边） | ConfirmDialog 确认（含名称） | DELETE + 列表重 GET | ok toast「已删除」 | err toast（store error） | 内置 Agent 只读不可删 |
| Agent 详情/复制 | 内置卡片「详情」「复制」按钮 | 详情 → 弹窗（icon/名称/描述/prompt pre/工具/技能 chips）；复制 → copyAgent | — | 详情展示 / ok toast「已复制」 | 复制失败 err toast | 详情弹窗 ✕ 关闭；复制生成新实体入列表 |
| AgentEditDialog 表单 | 名称/描述/图标/prompt textarea/**scope 矩阵**（F58 #957：行=8 功能域 大纲/角色/世界观/时间线/伏笔/记忆/写作/Agent 链，列=读/写/删三 checkbox；该域该操作无可用工具 → 格子渲染但 disabled；删除列头带 tooltip「暴露删除工具；每次删除仍需会话确认（双闸，ADR-043）」）/技能搜索+勾选/模型覆盖/温度覆盖 | 填写 + 勾矩阵格 → 保存 | — | 保存成功（见上）；提交 grants（域行序 × read/write/delete 序，空 ops 域剔除；不再提交 tool_ids） | 名称空 → 内联错误 | 编辑回显 = API 响应 grants（后端已对旧 tool_ids 数据 resolve 推断，前端零推断逻辑）；技能搜索过滤 + 勾选；model/temperature override 可留空（null） |
| Agent 详情弹窗（内置） | 工具区块 = scope 矩阵只读回显（8×3，data-checked）+「共 N 个工具」计数（resolved_tool_names 长度） | 点「查看工具清单」 | — | 展开工具名逐行清单（默认折叠防噪声）；再点收起 | — | grants 全空 → 「未授权任何工具域」；域名走 F57 双层词条（远端 messages 目录优先，前端本地回退） |
| 模板新建 | 「新建模板」按钮（template-add-btn） | 打开 TemplateDialog（空表单） | — | — | — | 挂载 loadTemplates |
| 模板编辑 | 卡片「编辑」按钮 | 打开 TemplateDialog（回显 editing） | — | — | — | 被引用（used_by>0）→ 先弹风险确认框，确认后才保存 |
| 模板设为默认 | 卡片「设为默认」按钮 | setDefault → PATCH /agent-templates/default | — | 默认徽标迁移到该卡片 | err toast | 默认状态经 store 本地同步（is_default 唯一） |
| 模板删除 | 卡片「删除」按钮 | 被引用 → 风险确认框（列出项目名 n 个 + 级联提示）；未引用 → 通用确认 | DELETE 请求 | 列表移除（store filter） | err toast（store error，如 409 被引用；列表不变） | 前端对所有模板（含默认）均渲染删除按钮，无禁用分支；确认框遮罩点击可关闭 |
| TemplateDialog 保存 | 名称（必填）/描述/主模型/角色行/默认温度/默认字数 | 保存 → onCreate/onUpdate 回调 | — | 成功 → 关闭 + 列表刷新 | 校验失败 toast；名称空 → 内联错误 | 角色行 = agents role_key 派生（内置 4 角色 i18n + 自定义）；每行模型下拉 + 温度滑杆 0~1.5 step 0.1 + 启用开关（关 = 清除 model/temperature 覆盖）；默认温度滑杆同参 |
| 被引用模板保存/删除风险确认 | 风险确认框（标题 + 文案列项目名 + 取消/确认） | 确认 → 执行保存/删除 | — | 保存/删除成功（删除级联清空引用项目 template_id，回退默认模板装配） | err toast + 保持 | 取消 → 不执行；确认后一次写 |
| 链开关并发 PATCH 守卫 | — | 连续快速切换 | persisting 中再次变更挂起（pendingRef） | 当前 PATCH 结束以最新 config 补存（不丢最后一次 toggle） | — | 防并发 PATCH 竞态 |

## 3. 验收

- N1：Agent 链四内置角色（+ 进链扩展角色/自定义角色）开关三态语义正确：关闭/跟随默认/指定模型徽标各自展示；开关即改即存且并发 PATCH 守卫不丢最后一次切换
- N2：上移/下移边界正确（首层上移、末层下移禁用）；移动自动启用未启用角色；空层压缩
- N3：添加角色 → 角色池（真源派生）→ 入链生效；依赖入口展开/收起 AgentRelationEditor
- N4：Agent 列表：内置只读（详情/复制）、自定义编辑/删除（删除有确认框）；AgentEditDialog 名称必填 + 技能多选 + model/temp override；**工具授权 = F58 scope 矩阵（#957）**：8 域 × 读/写/删勾选，无工具格 disabled，删除列头 tooltip；保存提交 grants（不再提交 tool_ids），编辑回显 API resolve 后的 grants（旧 tool_ids 数据打开即见推断矩阵，前端零推断）；详情弹窗矩阵回显 +「共 N 个工具」计数，工具名清单默认折叠可展开
- N5：模板 CRUD + 设为默认徽标迁移；被引用模板保存/删除 → 风险确认框（列项目名），确认/取消两分支均符合上表
- N6：TemplateDialog 角色行模型下拉 + 温度滑杆 0~1.5（step 0.1）+ 启用开关；名称必填校验
