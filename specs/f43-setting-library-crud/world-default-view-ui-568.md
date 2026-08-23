# F43 增量 spec（#568）：世界观默认视图 UI 完整重设计

> **Spec 版本**: v1.0（2026-08-23） | **依据**: Issue #568 + issue #568 评论（2026-08-22，用户细化）+ #567/#588 拍板链
> **所属阶段**: 0.12.0（issue #568，enhancement）
> **前置**: F43 P1（#306，世界观树/分类筛选/复制）✅、F43 P2（#311，地图工作台）✅、#567（根世界观单例 + 临时隐藏创建入口）✅、#588（已有根条目仍可创建，回归）✅
> **关联 ADR / spec**: [`specs/f43-setting-library-crud/spec.md`](./spec.md)（F43 本体 P0-P5）、[`specs/f10-world-service/spec.md`](../f10-world-service/spec.md)（后端条目/分类/复制能力）、`design/setting-library-v2-decisions-2026-08-12.md`（拍板 D1-D13）
> **状态**: 🔨 起草中（#568）

## 0. 本 spec 定位

F43 本体（P0-P5）已实现「世界观树视图 + 分类筛选 chips + 地图工作台 + 复制」。本 spec 是 **F43 的增量 UI 规格**，只覆盖 **#568 世界观默认视图（非地图）的信息层级与入口交互重设计**，不改后端（零 API 变更）。后端能力（根单例校验、分类实体、复制、树形 parent_id）已在 F10/F35/F37/F43 落地，本 spec 只消费既有接口。

> ⚠️ **范围红线**：不新增后端端点 / 不改 schema / 不改 F43 已合入的地图工作台交互（MapWorkbench 语义保持不变）。仅动 `pages/library.tsx` 的世界观区块渲染 + `components/WorldNodeView.tsx` + `components/WorldCatActionButtons.tsx` + i18n。

## 1. 背景与现状（代码实锤）

世界观 tab 在 `frontend/packages/renderer/src/pages/library.tsx` 的渲染分支：

| 分支条件 | 渲染 | 位置 |
|---------|------|------|
| `activeCat === 'world' && workbenchActive && (items.length > 0 \|\| maps.length > 0)` | 地图工作台 `MapWorkbench` | L658-681 |
| `items.length === 0` | 空态 `library-tab-empty`（「去创建」CTA + 地图入口） | L682-705 |
| `activeCat === 'world'`（有数据、非工作台） | **默认视图**：分类筛选工具栏 + `WorldNodeView` 树视图 | L706-771 |

**默认视图现状（本 spec 重设计对象，L706-771）**：
- 分类筛选工具栏：`lib.worldCat.label` 标题 + `worldCatActionButtons` + `world-copy-all`
- `WorldNodeView`（`components/WorldNodeView.tsx`）：递归树，每行 = `[折叠toggle][名称][类别徽标][hover:编辑/删除/复制]`

**信息层级问题（#568 核心）**：树行当前只展示 `name + category`，**没有描述预览、没有子条目数、没有标签**。对照 Notion / 语雀知识库默认视图（每条目一行：主标题 + 次级属性行），当前「名称 + 徽标」是**信息层级最弱形态**——用户无法在列表层扫读条目语义，必须逐行点开编辑。

**入口交互问题（#588 细化，issue #568 评论）**：`WorldCatActionButtons` 的 `showCreate` 恒 `true`（#588 修正后台 #567 恒隐藏），导致**任意状态都显示「新建分类」创建按钮**。用户 rc7 复验反馈「任意分类都显示创建按钮，且创建对话框类别字段为空（需手动选）」，期望：
- **默认（未选分类 / 根态）不显示创建按钮**（根世界观单例，#567 拍板：一项目一根，不能重复建根）
- **仅选中自定义分类 chip 时显示创建按钮**（在该分类下创建子条目的合理入口）
- **点击创建时对话框「标题」与「类别」字段按当前选中分类自动填充**

## 2. 设计（本 spec 定稿）

### 2.1 信息层级（默认视图每条目行，对齐 Notion/语雀）

世界观条目在默认视图渲染为「**两行式信息卡行**」（树行保留缩进层级，重组行内内容）：

```text
[折叠toggle]  名称（主标题，font-medium）              [类别徽标] [子条目数徽标]  [hover: 编辑/删除/复制]
              └ 描述预览（content 单行截断，ink-2 次级文案，max 1 行）
```

层级从高到低：**名称 → 描述 → 类别/子条目数 → 行内操作**。

| 字段 | 来源（`LibraryItemDTO`） | 渲染规则 |
|------|------------------------|---------|
| 名称 | `item.name` | 主标题，`font-medium`，truncate 单行（既有） |
| 描述预览 | `item.content` | 次级文案，`text-ink-2`，`truncate` 单行；**空串/缺失则该行不渲染**（保持行高收敛） |
| 类别徽标 | `item.category` | 既有 `bg-surface-3` 圆形徽标；空串不渲染 |
| 子条目数 | `children.length`（树已构建） | 徽标文案 `{N} 子条目`；`children.length === 0` 不渲染 |
| 标签 | `item.extra?.tags`（预留；当前无种子） | **本 spec 不渲染**（数据未下沉，YAGNI；见 §4） |

> **「标签」决策**：F43 只给角色（characters）下沉了 `extra.groups` 标签，世界观条目 `extra` 无独立标签语义。信息层级里的「标签」在本 spec 中由「类别徽标 + 子条目数」承接（分类即世界观的组织维度）。不凭空新增 `extra.tags` 字段消费（无数据源）。此为「层级清晰」而非「新增字段」。

### 2.2 入口交互（create 入口显隐状态矩阵）

以「是否有根条目」+「当前选中分类」两个维度定义创建入口显隐。world tab 的创建入口有两处：① 工具栏常驻 `library-create-btn`（"去创建"，#545，L599）= **创建子条目**（LibraryCreateDialog）；② `WorldCatActionButtons` 的 `world-cat-add`（L728）= **新建分类实体**（WorldCategoryDialog，#389，语义不变）。

| # | activeWorldCat | 上下文 | `library-create-btn` | `world-cat-add` | 空态 CTA（`library-tab-empty-cta`） | 依据 |
|---|---------------|--------|----------------------|-----------------|-----------------------------------|------|
| 1 | —（空态） | `items.length === 0`（无任何条目） | 不渲染（空态分支走 empty CTA） | **恒显示**（建分类实体可随时做） | **保留**（可建根） | #567 「空项目保留去创建 CTA」 |
| 2 | `null`（默认/根态） | 有根条目、**未选分类 chip** | **隐藏**（根态不渲染） | **恒显示**（分类树可扩展，非根条目） | 不渲染（非空态） | #567 根单例：不能再建根；#568 评论「默认分类不显示去创建」 |
| 3 | 非 `null`（选中自定义分类） | 有根条目、**选中某分类 chip** | **显示** | 恒显示 | 不渲染 | #568 评论「仅自定义分类下出现创建按钮」 |

**第 3 行的「去创建」= 在该分类下创建子条目**。点击后打开 `LibraryCreateDialog`，**预填**：

| 对话框字段 | 预填值 | 新增 i18n |
|-----------|--------|----------|
| 标题（`lib.create.title.*`） | 选 `world` 且选中分类时用**新增 key** `lib.create.title.worldCategory`（zh `创建分类` / en `Create Category`），语义 = 在选中分类下建子条目 | ✅ |
| 类别（`category` 输入） | `activeWorldCat`（当前选中的分类名） | — |

> **⚠️ 入口语义（定稿，2026-08-23）**：`library-create-btn`（"去创建"）承担「创建子条目」（#568 用户评论核心：选中分类时出现 + 对话框标题/类别预填）。用户评论里的「创建按钮」指 `library-create-btn`（rc7 截图「世界观页『去创建』按钮 + 创建世界观对话框（类别为空）」）——并非 `world-cat-add`。因此：
> - **`library-create-btn`**：#568 新增语义——world 根态隐藏（根单例）、选中分类显示（创建子条目、类别预填）→ 由 L599 条件 `(activeCat !== 'world' || activeWorldCat !== null)` + `LibraryCreateDialog` 的 `initialCategory={activeWorldCat}` 实现
> - **`world-cat-add`**（"新建分类"）：**保留** `WorldCategoryDialog`（#389 新建分类实体，语义不变、恒显示）。分类实体是受控词表，独立于根条目单例，可随时新增（#567 单例约束的是「根 WorldSetting」，非分类实体）。

> **「默认分类」术语澄清**：issue #568 评论的「默认分类」= `activeWorldCat === null`（未选任何分类 chip，即根态）——此时不显示创建按钮；「自定义分类」= `activeWorldCat` 非空（选中了某个分类实体 chip）——此时显示创建按钮并预填。

### 2.3 分类 chips（无「全部」，保持 #567 语义）

`world-cat-filter-<cat>` chips 保持：**无「全部」选项**（默认展示所有，点 chip 筛选，再点同 chip 取消）。本 spec **不改 chip 显隐逻辑**，只在其选中态驱动 §2.2 的创建入口。

### 2.4 视图切换（默认视图 ↔ 地图视图）

既有语义**保持不变**，本 spec 只明确入口归属：

| 切换方向 | 入口 | testid | 状态 |
|---------|------|--------|------|
| 默认视图 → 地图视图 | 工具栏/空态 `WorldCatActionButtons` 的「地图视图」按钮 | `map-view-entry` | ✅ 既有 |
| 地图视图 → 默认视图 | `MapWorkbench` 的「返回设定」（`worldMapBack`）→ `onExitWorkbench` → `setWorkbenchActive(false)` | —（MapWorkbench 内） | ✅ 既有 |

> **决策**：视图切换入口位置不变（工具栏 + 空态），不新增第二个地图入口，避免入口漂移（对齐 #567「地图视图从世界观 tab 挂接」）。本 spec 不改 `MapWorkbench`。

## 3. 前端文件变更面

| 文件 | 变更 |
|------|------|
| `components/WorldNodeView.tsx` | ① 行内新增描述预览（`item.content` 单行截断，`world-node-desc-<id>`，非空才渲染）；② 新增子条目数徽标（`children.length`，`world-node-childcount-<id>`，>0 才渲染）；③ `WorldTreeNode` 保持。900 行护栏不受影响 |
| `components/WorldCatActionButtons.tsx` | 不改（`world-cat-add` 恒显示，`onCreateWorld` 可选 prop 已加但调用方未用——保留向后兼容，不引入行为变化） |
| `pages/library.tsx` | ① `library-create-btn`（L599）条件改 `(activeCat !== 'world' \|\| activeWorldCat !== null)`（world 根态隐藏）；② 默认视图 `LibraryCreateDialog` 传 `initialCategory={activeCat === 'world' ? (activeWorldCat ?? undefined) : undefined}`；③ `WorldCatActionButtons` 空态/默认视图均保持 `world-cat-add` 恒显示（onAddCategory 建分类实体，语义不变） |
| `components/LibraryCreateDialog.tsx` | 新增可选 prop `initialCategory?: string`——`category` 初始值用它（编辑模式优先 `editing?.category ?? ''`）；新建模式 world + 非空 initialCategory 时标题走 `lib.create.title.worldCategory` |
| `i18n/zh.ts`、`i18n/en.ts` | 新增 `lib.create.title.worldCategory`（创建分类 / Create Category）+ `lib.worldNode.childCount`（{count} 子条目 / {count} children） |

## 4. 不在范围内（YAGNI）

| 项 | 原因 |
|----|------|
| 世界观条目 `extra.tags` 标签字段下沉 | 无后端数据源（F43 仅角色有 groups）；不凭空造消费 |
| 描述展开/详情面板 | 编辑对话框已承载全文；列表层单行预览足够，展开交互属 Phase 2+ |
| 新增地图视图入口 / MapWorkbench 改造 | 既有入口语义正确，避免漂移 |
| 后端任何变更 | 只消费既有接口 |
| 默认分类 chips 隐藏「地图」 | F10 §2.2 已定「地图」非世界观分类、不渲染为 chip（既有） |

## 5. 测试契约（RED 目标，`frontend/packages/renderer/src/pages/library.test.tsx` 世界观区块）

### 5.1 信息层级

- 树行渲染**描述预览**：seed 条目带 `content` → 该行出现描述预览文本段（`world-node-desc-<id>`），内容为 `content` 截断
- 树行渲染**子条目数徽标**：父条目（有 `children`）→ 出现 `world-node-childcount-<id>`，文案 `{N} 子条目`；无子条目 → 不渲染
- 描述预览为空（`content=''`）→ 该行不渲染描述段（行高收敛）

### 5.2 入口交互（核心，覆盖 #567/#588 反转）

- **空态**（无条目）：`world-cat-add` 显示 + `library-tab-empty-cta` 显示（建根入口保留）
- **有根条目 + activeWorldCat=null**（默认/根态，未选分类）：`world-cat-add` **不显示**（`queryByTestId` 为 null）——这是 #588→#568 行为反转
- **有根条目 + 选中分类 chip**：`world-cat-add` 显示；点击 → 创建对话框打开，`library-create-name` 可用，**「类别」输入（`lib.create.category`）值 = 选中分类名**，对话框标题 = `lib.create.title.worldCategory` 文案
- **无「全部」chip**：分类 chips 区域无「全部」按钮（断言不渲染）

### 5.3 视图切换

- `map-view-entry` 在默认视图工具栏 + 空态均可点；地图工作台退出（`返回设定`）后回到默认视图（`workbenchActive=false`）

### 5.4 守护用例（既有契约不回归）

- `library-list` 树容器 testid 不变
- `world-copy-all` 顶部整体复制仍在

## 6. 完成门禁

- **M0**：本 spec 定稿（父侧合入）
- **M1**：RED 确认 FAIL（§5.1 信息层级 / §5.2 入口交互 / §5.3 视图切换）
- **M2**：Codex GREEN + 父侧重跑全绿（`cd frontend/packages/renderer; pnpm vitest run` + `pnpm tsc --noEmit`）
- **M3**：PR merged（`Closes #568`）+ worktree 清理 + FEATURES.md/README 同步
