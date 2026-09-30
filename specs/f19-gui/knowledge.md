# 设定库·知识图谱 — 交互规格

> 页面: knowledge | 路由: /library?cat=knowledge | 组件: pages/library.tsx（cat=knowledge）+ KnowledgeGraphView + KnowledgeGraphCanvas + RelationList + RelationForm
> 对应 design/GUI/knowledge/（官方简图 knowledge.html + knowledge-<state>.png）

## 1. 画面样式

- 原型引用：design/GUI/knowledge/knowledge.html + knowledge-<state>.png（empty/graph/list/relation-form/graph-color-a/graph-color-b/graph-filter-a/graph-filter-b/graph-filter-b-collapsed）
> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：设定库（页面标题）  主题 Select  语言 Select  窗口控制 │
├──────────────────────────────────────────────────────────────┤
│ 标题区：设定库（font-serif 26px）                            │
│ [项目选择器 青云志 ▾]  面包屑：设定库 · 青云志 / 知识图谱    │
├──────────────────────────────────────────────────────────────┤
│ 分类 tab：角色│世界观│大纲│时间线│伏笔│知识图谱              │
├──────────────────────────────────────────────────────────────┤
│ 工具栏：[＋新建关系] [图谱视图│关系列表] [显示全部实体]      │
├────────────────/-┬───────────────────────────────────────────┤
│ 筛选面板(224)   │  [图谱视图]                              │
│ 🔍搜索实体名…   │ ┌───────────────────────────────────────┐ │
│ 类别      6     │ │ 图谱画布 520px（@xyflow：拖拽/缩放     │ │
│  ☑ ●角色        │ │  0.2-2）                              │ │
│  ☑ ●世界观      │ │   (角色)苏云舟 ──师承──> (角色)白眉道人│ │
│  ☑ ●大纲 …      │ │   (世界观)青云宗 <──加入── (角色)林晚照│ │
│ 实体      20    │ │   (时间线)夜访剑冢 ──埋设于──> (伏笔)…│ │
│  ☐ 阿九 …       │ │ 节点=类型圆点+名称（同类型个体再着色，  │ │
│                │ │  见 §4）；边=贝塞尔+箭头+关系类型 label │ │
│                │ │ 左下详情卡 / 右下＝图例六类 + 画布提示  │ │
│ ── 筛选：全部 · 显示 20 个实体 ──│ └───────────────────┘ │
│ [« 折叠]      [清除筛选]         │ ← 「底部折叠栏」所属面板底部 │
├────────────────┴───────────────────────────────────────────┤
│ 折叠态：面板消失，画布恢复全宽，底部换一条折叠栏：            │
│ [🔍 筛选 角色·苏云舟·显示 5 个实体  …  [清除筛选][展开筛选 »]]│
│   （筛选生效时该栏描边/摘要用 accent 强调）                  │
│ 关系列表视图：起点→ 关系类型 → 终点 + 描述 + [编辑][删除]    │
│   （列表视图隐藏筛选面板/折叠栏/图例——决策④：不筛选列表）    │
│ 弹层：关系表单（起点/终点 类型+实体 + 关系类型必填 + 描述）  │
│ 图谱空态：虚线卡片「图谱为空」+ 去角色页创建按钮             │
│   （空态隐藏画布 + 筛选面板/折叠栏 + 图例）                  │
└──────────────────────────────────────────────────────────────┘
```
- 参考锚点（真实实现，F48 §5.4）：
  - 端点：GET /api/v1/projects/{pid}/knowledge-graph（一次返回 nodes + edges 聚合）；GET/POST /api/v1/projects/{pid}/knowledge-relations（分页 + source_type/target_type/relation_type/source 过滤）；PATCH/DELETE /api/v1/knowledge-relations/{id}（真删）
  - 工具栏（flex-wrap）：新建关系（library-kg-new-relation，accent 主按钮 + Plus 图标）+ 视图切换胶囊组（library-kg-view-graph「图谱视图」默认激活 / library-kg-view-list「关系列表」，激活 = accent-weak 填充 + accent 文字）+ **全量实体开关（library-kg-scope-all，独立按钮，与视图胶囊组同级但不在其容器内——该容器的 aria-pressed 只服务图谱/列表两态）**
  - **节点集范围（#1325）**：`GET /knowledge-graph?scope=related|all`，**缺省 related** = 只显示「参与至少一条关系」的实体（无关系时回退角色全集）；`scope=all` = 六类实体全量（完整体检视图）。开关 aria-pressed 反映 scope，点击在 related/all 间切换并重拉图谱。文案 `lib.knowledge.scopeAll`「显示全部实体」
  - 图谱画布（library-kg-canvas，h-[520px] 圆角卡片，@xyflow/react v12）：
    - 六类实体节点（自定义节点 KgNode）：角色/世界观/大纲/时间线/伏笔/地图标记，各类型专属底色/边框/文字色/圆点色（TYPE_STYLES 十六进制表）；节点 = **左侧 target 锚点 + 圆点 + 名称 + 右侧 source 锚点**（两个 `<Handle>` 带 `className="kg-handle"`，为「拖线建关系」的前置）
    - 有向边（自定义边 KgEdge）：贝塞尔路径 + 箭头（ArrowClosed）+ 边中央 label（关系类型，SVG text）；边 id 保留 kr:/cr: 前缀
    - **样式表依赖（#1325 关键）**：`@xyflow/react/dist/style.css` 必须在 `src/main.tsx` 显式 import——库 CSS 提供 `.react-flow__node{position:absolute}`（缺 → 节点堆叠）、`.react-flow__edges{position:absolute}`、`.react-flow__edge-path{stroke:...}`（缺 → 边 stroke 无值 = SVG 默认 none = **边不可见**）
    - 画布默认能力：**拖拽节点（受控 state，拖后位置保持 + 结束写入 localStorage，按 project_id 键）** / 滚轮缩放（minZoom 0.2 / maxZoom 2）/ 点空白取消选中
    - **拉线建关系（#1325）**：从节点右侧 source 锚点拖到另一节点左侧 target 锚点 → 本地即时成一条空心 label 边 + 打开关系表单预填两端（relation_type 待填）；保存走既有 POST，保存后随图谱重拉收敛（失败不留幽灵边）
    - **画布提示（#1325，对齐 design/GUI/knowledge/knowledge.html）**：右下角「滚轮缩放 · 拖拽节点」小字提示（`lib.knowledge.canvasHint`，pointer-events-none）
    - 点击节点 → 左下角节点详情卡（library-kg-node-detail，w-64）：类型 + 名称 + 「去编辑」按钮（library-kg-node-edit-<entity_id>）
    - 点击边 → 左下角边详情卡（library-kg-edge-detail，w-72）：label + 描述 + 来源（source_table）+ 编辑/删除按钮（仅 knowledge_relations 边；cr: 角色关系边只读无操作按钮）
  - 图谱空态（library-kg-empty，画布下方虚线卡片）：「图谱为空」+ 引导文案（去实体页创建或新建关系）+ 去角色页创建按钮（library-kg-empty-cta → 父级切 characters tab）
  - 关系列表（library-kg-relation-list，圆角卡片 divide-y）：行 = 起点名（font-medium）→ 关系类型（accent）→ 终点名 + 描述（12px ink-2）+ 悬停编辑（library-kg-rel-edit）/删除（library-kg-rel-delete）；名称经图谱节点解析（type + entity_id → name，缺省回退原始 id）；空态「暂无关系，点击「新建关系」创建」
  - **关系列表分页（#1325）**：列表下方分页条（`testIdPrefix="library-kg-page"`，复用 #1300 `Pagination`）——prev / info「第 N / M 页（共 T 条）」/ next；请求带 `?limit=50&offset=`（旧实现不带分页参数 → 后端默认 limit=50 使第 51 条起永久不可见）；首页 prev 禁用 / 末页 next 禁用
  - 关系表单（library-kg-relation-form，520px 遮罩弹层，max-h 90vh）：起点类型/起点实体 + 终点类型/终点实体（双列 grid；类型下拉切换清空已选实体；实体下拉缺实体时 disabled）+ 关系类型（placeholder「如：属于 / 参与 / 师徒」）+ 描述（可选）+ 保存/取消
  - 删除确认（library-kg-confirm-* ConfirmDialog）：标题 = 关系类型，确认文案不可恢复，danger 红色
  - 无障碍：画布容器内 sr-only 图数据摘要（library-kg-summary）——节点名 + 边「起点 label 终点」拼接（jsdom 断言兜底）
  - 无实体创建入口：knowledge 分类 createCat=null，工具栏不渲染「去创建」；实体创建走各实体分类页
  - **节点个体着色（#1373，规则见 §4）**：TYPE_STYLES 的六类底色/边框/文字/圆点仍是**类型基准色**；在其上叠加**个体色**——同类型内按 `hash(name|id)` 派生（3 色相 × 2 明度），使同类型的多个实体互相可辨
  - **图例（#1373）**：`library-kg-legend`（画布右下角常驻，不占版面高度）——「图例」+ 六类圆点/类型名（`library-kg-legend-<type>`）+ 原「滚轮缩放 · 拖拽节点」提示（`lib.knowledge.canvasHint`，由独立 `.kg-tag` 并入本行）
  - **类别/实体筛选（#1373，拍板取 B + 折叠）**：左侧筛选面板（`library-kg-filter-panel`，224px）
    - 搜索（`library-kg-filter-panel-search`）：按名过滤下方实体列表（不改画布）
    - 类别组（`library-kg-filter-panel-cat-<type>`）：六类行（每行带类型圆点），**单选语义**（点另一类替换；全不选 = 不做类别过滤）；组标题右侧显示类别数（6）
    - 实体组（`library-kg-filter-panel-entity-<type>-<id>`）：当前可见实体列表，**单选、再点取消**（= 邻接子图）；组标题右侧显示实体数
    - 统计行（`library-kg-filter-summary`）：「筛选：<类别> · <实体> · 显示 N 个实体」
    - **面板底部折叠栏**：`[« 折叠]`（`library-kg-filter-collapse`）+ `[清除筛选]`（`library-kg-filter-panel-clear`）
    - **折叠后**：面板整块消失、画布**恢复全宽**；画布下方出现**底部折叠栏**（`library-kg-filterbar`）＝ `🔍 筛选 <摘要> … [清除筛选]（-clear） [展开筛选 »]（-expand）`；筛选结果**保持生效**；筛选生效时该栏描边与摘要用 accent 强调（`body[data-filter-active="1"]`）
    - **选择即本地记忆（决策③）**：`inkflow:kg:filters:<project_id>` 存 `{category, entity}`（与画布位置记忆同构）；面板开合存 `inkflow:kg:panel`（全局偏好）。正常打开（无 hash）= 按记忆恢复；无记忆 = 类别「全部」+ 实体未选 + 面板展开。存储不可用 / JSON 损坏 → 静默回退默认，不抛错
    - **一键清除筛选**：三处入口（折叠栏 `-clear` / 面板 `-panel-clear` / 备选形态 `-clear`）同一行为——类别回「全部」+ 清空实体与搜索 + **同步更新记忆**
    - 筛选**只在图谱视图渲染**（列表视图/空态隐藏全部筛选控件——决策④：不筛选关系列表）；筛选生效时隐藏节点详情卡（用户尚未点选）
  - **备选形态（未采用，仅原型对照）**：顶部两行 chip 组（`library-kg-filters` + `library-kg-filter-category` / `-cat-<type>` / `library-kg-filter-entity` / `-entity-<type>-<id>` / `-entity-more` / `-search` / `-clear`）——见 `knowledge-graph-filter-a.png`
  - **🔴 原型内嵌的 `.kg-note`「方案取舍说明条」是设计注释，不是产品 UI**（#1375 同款约定）——实现时不要做进页面

- 布局说明：图谱视图 = 左侧筛选面板（224px、可折叠）+ 右侧主栏（纵向：工具栏 → 画布）；**折叠态**下主栏占满宽度、画布下方多一条折叠栏；图例与详情卡均叠在画布内（图例右下、详情卡左下，互不重叠）；关系表单与删除确认挂页面根部；图谱/列表切换为本地 view 状态（列表视图激活时按需拉取 relations，增删改经 reloadKey 局部刷新）

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 新建关系（library-kg-new-relation） | accent 主按钮 | 打开 RelationForm（create 模式，起点默认角色/终点默认世界观） | — | POST 成功 → 关框 + reloadKey 局部刷新（图谱/列表同步） | err toast | 表单提交 gate：起点实体 + 终点实体 + 关系类型三要素齐备（submit 拦截） |
| 视图切换（library-kg-view-graph / -list） | 图谱视图默认激活 | 切换 view → 列表视图激活时按需拉取 relations（分页响应） | — | 列表/画布渲染 | 拉取失败 → 空列表 | 切换不丢另一视图数据；reloadKey 局部刷新两视图 |
| 图谱节点点击 | 节点渲染（类型着色） | 选中 → 左下详情卡 + 「去编辑」 | — | 「去编辑」按类型跳对应分类 tab（character→角色 / world→世界观 / outline→大纲 / timeline→时间线 / foreshadow→伏笔 / map_pin→世界观地图工作台） | — | 点空白画布取消选中；同时只保留一个选中对象（节点/边互斥） |
| 图谱边点击 | 有向边 + label | 选中 → 左下边详情卡 | — | 编辑/删除按钮可用（仅 knowledge_relations 边） | — | cr: 前缀边（角色关系）只读展示来源；删除走 ConfirmDialog（library-kg-confirm） |
| 关系列表编辑/删除 | 悬停显现 | 编辑 → RelationForm（edit 模式回填六元组 + 描述）/ 删除 → ConfirmDialog（真删） | — | PATCH/DELETE → 关框 + 刷新 + ok toast | err toast | 删除标题 = 关系类型；确认文案不可恢复 |
| 关系表单保存（library-kg-form-save） | 三要素齐备可提交 | handleRelationSave（create → POST /projects/{pid}/knowledge-relations；edit → PATCH /knowledge-relations/{id}） | — | 关框 + reloadKey 刷新 | err toast，表单保持打开可改 | 类型切换清空对应实体选择；实体下拉随类型联动过滤（entities 按 type 过滤）；ESC/取消关闭 |
| 图谱空态 CTA（library-kg-empty-cta） | 虚线卡片按钮 | 切到 characters tab（onGoEntities） | — | 分类切换 + 角色页渲染 | — | 仅 nodes 空时渲染；引导文案含「新建关系」双路径 |
| 画布交互（拖拽/缩放） | @xyflow 默认 | 拖节点 / 滚轮缩放 | — | 布局即时更新 + 拖拽结束位置写入 localStorage | — | minZoom 0.2 / maxZoom 2；jsdom 下 SVG 边不渲染（真实浏览器渲染层），sr-only 摘要兜底断言；**拖拽位移/连线几何只能真实浏览器复验** |
| 全量实体开关（library-kg-scope-all） | related 默认（aria-pressed=false） | 点击 → scope 切 all（或回 related）→ 重拉图谱 | — | 节点集按新 scope 渲染 + aria-pressed 翻转 | err toast | 与视图切换互不影响；无关系时 related 恒回退角色全集 |
| 画布拉线（Handle 拖拽） | 节点两侧锚点（kg-handle） | source 锚点拖到 target 锚点 → 本地即时成边 + 打开关系表单预填两端 | — | 表单保存 → POST → 图谱重拉收敛 | err toast，表单保持打开 | 同节点自环由后端 422 兜底；保存失败不留幽灵边（下次重拉覆盖本地暂态边） |
| 关系列表分页（library-kg-page-*） | 首页（prev 禁用） | next/prev 翻页 → 以新 offset 重拉 | — | 列表换页 + info 更新 | 拉取失败 → 空列表 | limit 恒 50；末页 next 禁用；视图切到图谱后分页条消失 |
| **类别行（library-kg-filter-panel-cat-&lt;type&gt;）（#1373）** | 全不选 = 不做类别过滤 | 点某类 → 命中；点另一类 → 替换；再点同类 → 取消 | — | 画布只渲染该类节点 + 两端都可见的边 | — | 单选语义；切换类别**清空已选实体**；与「显示全部实体」scope 开关互不影响 |
| **实体行（library-kg-filter-panel-entity-&lt;type&gt;-&lt;id&gt;）（#1373）** | 未选（无高亮） | 点击 → 命中该实体（邻接子图）；再点取消 | — | 画布只渲染「该实体 + 一跳邻居」及其之间的边；节点详情卡隐藏 | — | 与类别筛选取**交集**；不在当前搜索结果内则不可选 |
| **实体搜索（library-kg-filter-panel-search）（#1373）** | 空 | 输入 → 过滤下方实体列表 | — | 列表按名收窄 | — | 只过滤列表，不直接改画布；无匹配 → 列表为空 |
| **折叠面板（library-kg-filter-collapse）（#1373）** | 展开态可见（面板底部栏左侧） | 点击 → 面板整块收起 + 画布下方出现底部折叠栏 | — | 画布恢复全宽（原型 732 → 968px）；筛选结果**保持生效** | — | 开合状态写入 `inkflow:kg:panel`；列表/空态不渲染 |
| **展开筛选（library-kg-filterbar-expand）（#1373）** | 折叠态可见 | 点击 → 面板还原，勾选态从记忆回填 | — | 回到 224px 面板布局 | — | — |
| **一键清除筛选（-filterbar-clear / -filter-panel-clear）（#1373）** | 常驻（图谱视图） | 点击 → 类别回「全部」+ 清空实体与搜索 | — | 画布恢复全量节点 + 详情卡复现 | — | 三处入口同一行为；**同步更新记忆**；列表/空态不渲染 |
| **筛选记忆（localStorage）（#1373）** | 无记录 → 默认「全部 + 面板展开」 | 用户每次选择 / 折叠即写入 | — | 重开或刷新按记忆恢复（筛选值 + 面板开合） | 记忆损坏 / 存储不可用 → 静默回退默认，不抛错 | 键 `inkflow:kg:filters:<project_id>`（值 `{category, entity}`）+ `inkflow:kg:panel` |
| **图例（library-kg-legend）（#1373）** | 常驻（图谱视图右下角） | 不可交互（纯说明） | — | — | — | 列表视图 / 空态隐藏；窄画布（展开态）下与详情卡不重叠 |

## 3. 验收

- N1：图谱/关系列表双视图切换 + 列表按需拉取
- N2：六类实体节点着色 + 有向边 label + 点击节点/边出详情卡（互斥选中）
- N3：节点「去编辑」按类型跳对应分类 tab（map_pin → 世界观地图工作台）
- N4：关系创建/编辑/删除闭环（三要素 gate + 确认框 + 局部刷新）
- N5：图谱空态引导 + sr-only 数据摘要（无障碍/测试断言兜底）
- **N6（#1325）**：图谱**连线可见**（`@xyflow/react/dist/style.css` 已 import）——节点不再堆叠、边 stroke 有值
- **N7（#1325）**：节点集范围开关（`library-kg-scope-all`）：默认 related（只显示参与关系者，无关系回退角色全集）；切 all 显示六类全量
- **N8（#1325）**：画布节点可拖拽且位置保持（写 localStorage）；节点两侧 `kg-handle` 锚点可**拉线建关系**（预填两端 + 落库）
- **N9（#1325）**：关系列表分页（`library-kg-page-*`）——请求带 `limit/offset`，跨页可达第 51+ 条
- **N10（#1373）**：**节点个体着色**——同类型多实体在画布上**肉眼可辨**（类型色相带内 3 色相 × 2 明度派生；判据用「最大单通道差 ≥ 40」而非「rgb 不相等」）；同一实体跨会话/跨刷新**同色**（着色必须为纯函数）；图例（`library-kg-legend`）常驻列出六类 + 画布提示
- **N11（#1373）**：**类别筛选**——`library-kg-filter-panel-cat-<type>` 单选，命中后画布只渲染该类节点与被保留的边；切换类别清空已选实体；点「清除筛选」恢复全量
- **N12（#1373）**：**实体筛选**——`library-kg-filter-panel-entity-*` 选中后只渲染「该实体 + 一跳邻居」及其之间的边；与类别筛选取交集；筛选态隐藏节点详情卡
- **N13（#1373）**：筛选控件（面板 / 折叠栏 / 备选 chip 行）**只在图谱视图**渲染（列表视图与空态都不出现——决策④：不筛选关系列表）
- **N14（#1373）**：**折叠不牺牲画布宽度**——`library-kg-filter-collapse` 收起面板后画布宽度恢复到全宽（原型实测 732 → 968px），筛选结果**保持生效**；折叠栏提供「展开筛选」回入口；面板开合状态本地记住
- **N15（#1373）**：**选择即本地记忆 + 一键清除**——`localStorage['inkflow:kg:filters:<project_id>']` 存 `{category, entity}`，重开/刷新按记忆恢复（含面板折叠态 `inkflow:kg:panel`）；三处「清除筛选」入口同一行为并同步更新记忆；记忆损坏或存储不可用时静默回退默认（不抛错）

## 4. 节点着色与筛选规则（#1373）

### 4.1 着色：三条可选路径（原型只画 A / B 两版）

改前现状：`components/knowledge-graph/KnowledgeGraphCanvas.tsx` 的 `TYPE_STYLES` 按 `data.type` 六类各一色 → **同类型实体完全同色**，节点一多无法分辨谁是谁（v0.15.0-rc5 GUI 反馈）。

| 方案 | 做法 | 跨会话稳定 | 契约改动 | 取舍 |
|------|------|-----------|---------|------|
| **A（✅ 采用，原型默认）** | 前端派生：类型色相带内按 `hash(name\|id)` 取 3 色相（±18°）× 2 明度 | ✅ 同实体永远同色 | ❌ 零改动 | 类型一眼可辨 + 同类个体可辨；代价：同类内属「同色系微差」，极密时仍需靠名称辨认 |
| **A′（A 的契约变体，原型未出图）** | 同一套色板，但由后端在 graph 响应返回稳定 `color` / `palette_index` | ✅（更强：可跨端/跨导出统一） | ✅ 改 `GraphNode` 契约 + 后端派生 | 视觉与 A 一致；换来「导出图 / CLI 报告 / 未来云端同色」与「前端零算法」；代价：契约变更 + 存量兼容 |
| **B（备选，原型出图对照）** | 同类型内**图邻接贪心着色**（相邻节点必定异色） | ❌ 图的增删会重排颜色 | ❌ 零改动 | 追连线最不易看丢；代价：颜色不稳定、用户无法形成长期记忆——实测 8 个角色里只有「苏云舟」与其余 7 个异色，**个体分辨力反而低于 A** |

色板参数（方案 A，已按浏览器真实渲染校准）：
- 类型基准色相：`character 4 · world 217 · outline 142 · timeline 45 · foreshadow 262 · map_pin 25`（与既有 `TYPE_STYLES` 圆点色同源）
- 个体派生：`hue = 基准 ± 18°`（3 档）× 明度 2 档；圆点 `L 58%/42%`、边框 `L 82%/66%`、底色 `L 96%/88%`、文字 `L 34%/24%`
- 🔴 **校准依据（视觉复核实测）**：初版取 `±13° / 明度 6%`，浏览器实渲后**8 个角色看起来仍是一个色**——「字符串不等 ≠ 肉眼可辨」。故 `_tools/shot-knowledge-graph-scope.cjs` 的可辨性判据为 **`typeColorSpread()` 的最大单通道差 ≥ 40**，而非 rgb 字符串不等
- **纯函数约束**：同 `id+name` 恒得同色；脚本用「同状态重放两次逐节点比对色值」守护（防 `Math.random` 类实现）

### 4.2 筛选语义

```text
可见节点 = (类别命中 | 类别 = 全部) 且 (未选实体 | 节点 ∈ {选中实体} ∪ 一跳邻居)
保留边   = 两端节点均可见
```

- 类别：**单选**（全不选 = 不做类别过滤）——不用「多选」，与图谱「一次看一类」的主要用法一致
- 实体：**单选**（再点取消）——选中即「邻接子图」视图；与类别取交集
- 搜索框：只过滤实体列表，不直接改画布
- **形态 B（左侧筛选面板，✅ 采用）**：实体规模大时可滚动 / 可搜索 / 可多选语义；**配「底部折叠栏」抵消其唯一劣势**——展开态占宽 224px（画布 968 → 732px），点「折叠」后面板整块消失、画布恢复全宽，改由画布下方的折叠栏承载摘要 / 清除 / 展开；筛选结果在折叠态保持生效（用户拍板原话：「添加底部折叠栏和折叠功能，不牺牲画布宽度」）
- **形态 A（顶部两行 chip 组，未采用，仅原型对照）**：不占横向空间、复用既有 `.rank-chip` 视觉；出局原因是实体多时 chip 行会换行抬高页面（`knowledge-graph-filter-a.png` 保留对照）
- **记忆（决策③）**：每次用户选择即写入 `inkflow:kg:filters:<project_id>`（`{category, entity}`）；面板开合写 `inkflow:kg:panel`。**只在用户动作时写**，截图/演示态（`setState`）不写，避免污染记忆
- **悬置（决策④）**：筛选**暂不作用于关系列表**——列表端点已支持 `source_type/target_type`（F48 §3.1），但按实体 id 过滤无对应 query 参数，需另开契约扩展；本版列表视图直接不渲染筛选控件

### 4.3 实现时需新增的 i18n key（`i18n/zh.ts` + `en.ts` 同步）

`lib.knowledge.filter.category`（类别）· `lib.knowledge.filter.entity`（实体）· `lib.knowledge.filter.all`（全部）· `lib.knowledge.filter.search`（搜索实体名…）· `lib.knowledge.filter.more`（更多 {n}）· `lib.knowledge.filter.clear`（清除筛选）· `lib.knowledge.filter.empty`（当前筛选下没有可见实体）· `lib.knowledge.filter.shown`（显示 {n} 个实体）· `lib.knowledge.filter.collapse`（折叠）· `lib.knowledge.filter.expand`（展开筛选）· `lib.knowledge.legend`（图例）

> ⚠️ 落地前先核 `i18n/zh.ts` / `en.ts` 的行数上限（两者等高，净增必须 ≤ 0，见项目既有约定）。

### 4.4 原型已用 testid（实现请沿用，勿另起名）

**采用（形态 B）**：`library-kg-legend` · `library-kg-legend-<type>` · `library-kg-filter-panel` · `library-kg-filter-panel-search` · `library-kg-filter-panel-cat-<type>` · `library-kg-filter-panel-entity-<type>-<id>` · `library-kg-filter-panel-clear` · `library-kg-filter-collapse` · `library-kg-filter-summary` · `library-kg-filterbar` · `library-kg-filterbar-summary` · `library-kg-filterbar-clear` · `library-kg-filterbar-expand` · `library-kg-filter-empty` · `library-kg-node-<type>-<id>`

**备选（形态 A，未采用，仅原型保留）**：`library-kg-filters` · `library-kg-filter-category` · `library-kg-filter-cat-<type>`（含 `-cat-all`）· `library-kg-filter-entity` · `library-kg-filter-entity-<type>-<id>` · `library-kg-filter-entity-more` · `library-kg-filter-search` · `library-kg-filter-clear`
