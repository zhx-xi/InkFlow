# F43 设定库 CRUD 闭环（P0 批次）— 功能规格

> **Spec 版本**: v1.0（2026-08-12）
> **阶段**: 0.8.0（issue #284 的 P0 批次；P1-P5 后续批次另开 PR）
> **估算**: 3-5 人天（纯前端 + 前端测试；后端零改动）
> **关联 Issues**: #284（parent，GUI 升级总 issue）、#196（创建对话框先例）、#189（已保存指示先例）、#195（遮罩不关闭拍板）、#211（删除语义统一，P5 对齐）
> **设计依据**: `design/setting-library-v2-decisions-2026-08-12.md`（D11 删除语义 / D12 悬停操作按钮）+ `design/setting-library-gui-gap-analysis-2026-08-12.md`（US-1/US-2/US-3）
> **状态**: 待实现 🔲

---

## 1. 概述

### 1.1 模块定位

设定库 GUI（library.tsx 六分类 tab + projects.tsx 项目卡片）目前只有**只读列表 + 创建对话框**（#196），后端六分类 PATCH/DELETE 端点与项目 PATCH/DELETE 全部就绪但 GUI 未暴露（gap-analysis §1 盘点：`library.tsx` 零 PATCH/DELETE 调用）。本批（P0）补齐 CRUD 闭环，让设定库从「只能写不能改」变为「点开即改、随时可删」。

**与 F42 的关系**：F42 = 0.9.0 多 Agent 配置（agent-chain-config），本 F43 = 0.8.0 设定库 GUI（issue #284 的 P0）。编号按 AGENTS.md 模块类型谱系顺延。

### 1.2 范围（P0 交付物）

| # | 交付物 | 来源 |
|---|--------|------|
| 1 | 设定库列表项【编辑】：行内编辑按钮 → LibraryCreateDialog 扩展为可编辑（预填现值）→ PATCH 保存 → 列表刷新 + 「已保存」顶部指示（#189 模式） | US-1 |
| 2 | 设定库列表项【删除】：行内删除按钮 → 二次确认框 → DELETE → 列表刷新 + toast | US-2 |
| 3 | 删除确认文案按 D11 统一；世界观条目追加级联警告（其全部子条目将级联删除） | D11 |
| 4 | 项目卡片【重命名/删除】：卡片菜单（重命名/删除）→ 删除二次确认（明示项目数据范围）→ PATCH/DELETE | US-3 |

### 1.3 边界声明

- 本批**只覆盖 P0**：六分类（角色/世界观/大纲/时间线/伏笔）列表项编辑/删除 + 项目重命名/删除。
- RAG 分类（extractions/runs = AI 提取运行列表）**无编辑/删除**（无对应 PATCH/DELETE 端点），列表行不渲染操作按钮。
- P1-P5（角色等级标签/世界观树与复制/地图工作台/大纲三级/时间线双序/30 天清理 job）**不在本批**，issue #284 保持 OPEN。
- 后端**零改动**：所有 PATCH/DELETE 端点与领域模型已核实（§3 端点表），前端首次消费。

---

## 2. 数据模型（前端类型扩展）

### 2.1 设定库列表项 DTO（library.tsx 现 `ListItem` 仅 id/name/title）

列表端点返回完整领域实体（`model_dump(mode="json")`），编辑预填需要全部表单字段。定义：

```ts
/** 六分类列表项完整 DTO（后端领域模型字段对齐，缺失字段兜底 ''） */
interface LibraryItemDTO {
  id: string | number;
  name?: string;        // characters/world/outline
  title?: string;       // timeline/foreshadow
  personality?: string; // characters
  background?: string;  // characters
  goals?: string;       // characters
  category?: string;    // world
  content?: string;     // world
  description?: string; // outline/timeline/foreshadow
  time_display?: string; // timeline
  priority?: number;    // foreshadow
  location?: string;    // foreshadow
}
```

### 2.2 LibraryCreateDialog 双模式扩展（MODIFY，非新建）

现 props `{ open, cat, onCreate, onOpenChange }` → 扩展为：

```ts
interface LibraryCreateDialogProps {
  open: boolean;
  cat: LibraryCreateCat;                 // 不变：characters|world|outline|timeline|foreshadow
  editing?: LibraryItemDTO | null;       // 新增：非空 = 编辑模式（预填现值）
  onSave: (input: Record<string, unknown>) => Promise<void>; // 改名：create→save，父级分支 PATCH/POST
  onOpenChange: (open: boolean) => void; // 不变
}
```

- **打开时预填**：`useEffect([open, cat, editing])` —— `editing` 非空时各字段 set 现值（`?? ''` 兜底）；空（创建模式）时重置空表单（保持 #196 既有行为）。
- **标题/保存按钮**：编辑模式 `t('lib.edit.title.<cat>')` + `t('lib.edit.save')`；创建模式保持 `lib.create.*`。
- **testid 契约不变**：容器 `library-create-dialog`、保存按钮 `library-create-save`、取消 `library-create-cancel`（既有测试零回归）。
- 字段布局、必填逻辑、ESC 关闭、遮罩不关闭（#195）与现状一致。

### 2.3 ConfirmDialog 共享组件（NEW）

删除确认框（设定库列表项 + 项目卡片两处消费，Rule of Two 已到）：

```ts
interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: ReactNode;          // 支持多行文案（D11 统一文案 + 追加警告行）
  confirmText: string;         // 确认按钮文案（默认「确认删除」）
  danger?: boolean;            // 确认按钮红色（D11：确认按钮红色）
  testidPrefix: string;        // testid 前缀（lib-confirm / project-delete），避免同屏多确认框冲突
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
}
```

- testid：`{prefix}-dialog` / `{prefix}-cancel` / `{prefix}-ok`。
- **遮罩点击不关闭（#195）**；关闭路径仅 取消按钮 / Esc / 确认成功（父级关）。与 TemplateDialog 旧确认框（遮罩可关）不同——本批新确认框一律遵守 #195。

### 2.4 project store 扩展（MODIFY stores/project.ts）

新增两个 action（失败 rethrow，调用方 toast；对齐 updateConfig 模式）：

```ts
renameProject: (id: string, name: string) => Promise<void>;
// PATCH /api/v1/projects/{id} body { name } → 本地更新 projects 中该 id 的 name
deleteProject: (id: string) => Promise<void>;
// DELETE /api/v1/projects/{id} → 本地移除；若 currentProjectId === id → 置 null；
// 清理 chapterProgress[id]
```

## 3. API 契约（前端首次消费，后端零改动）

### 3.1 端点总览表

列表端点现状不变（§3.2）；本批新增消费 **PATCH/DELETE**（六分类扁平路径 + 项目路径，全部已核实 backend/api/routers）：

| 分类 | PATCH（编辑保存） | DELETE（删除） | 删除语义（已核实服务层） |
|------|------------------|----------------|--------------------------|
| 角色 | `PATCH /api/v1/characters/{id}` | `DELETE /api/v1/characters/{id}` → 204 | 软删（is_deleted=true，可 restore） |
| 世界观 | `PATCH /api/v1/world-settings/{id}` | `DELETE /api/v1/world-settings/{id}?cascade=true` → 204 | **级联真删整棵子树**（F35：list_descendants + hard_delete_many 单事务；无子条目时也走 hard_delete_many 自身） |
| 大纲 | `PATCH /api/v1/outlines/{id}` | `DELETE /api/v1/outlines/{id}` → 204 | 软删 |
| 时间线 | `PATCH /api/v1/timeline/events/{id}` | `DELETE /api/v1/timeline/events/{id}` → 204 | 软删 |
| 伏笔 | `PATCH /api/v1/foreshadowings/{id}` | `DELETE /api/v1/foreshadowings/{id}` → 204 | 软删 |
| 项目 | `PATCH /api/v1/projects/{id}` | `DELETE /api/v1/projects/{id}` → 204 | 软删（force 参数 GUI 不暴露） |

> **世界观 cascade 决策（D11 落实）**：确认框总是显示级联警告（「其全部子条目将级联删除」），DELETE 统一带 `?cascade=true`。不预查询 descendants——任务书/决策文档指定方案；有子条目时后端 422 兜底不可达（cascade 优先），无子条目时 cascade 亦合法（真删自身，用户视角 = 条目立即消失，与确认文案一致）。

### 3.2 PATCH 请求体（编辑保存，前端构造）

与创建 DTO 同字段集（后端 Update DTO 全可选 + exclude_unset，发送全表单字段安全）：

| 分类 | PATCH body | 后端模型（已核实） |
|------|-----------|-------------------|
| 角色 | `{ name, personality, background, goals }` | CharacterUpdate（name 必校验 1-50 去空白） |
| 世界观 | `{ name, category, content }` | WorldUpdate（name/category/content 校验同 Create） |
| 大纲 | `{ name, description }` | OutlineUpdate |
| 时间线 | `{ title, time_display, description }` | TimelineEventUpdate |
| 伏笔 | `{ title, priority, location, description }` | ForeshadowingUpdate（priority 0-100） |
| 项目改名 | `{ name }` | ProjectUpdate（name 必校验 1-100 去空白） |

### 3.3 错误映射

| 场景 | 前端行为 |
|------|---------|
| PATCH/DELETE 失败（404/422/网络） | `errorMessage(err)` → err toast；编辑时对话框保持打开可重试（对齐 #196 创建失败行为）；删除时列表不变 |
| 编辑保存成功 | 关闭对话框 + `setReloadKey` 刷新列表 + 顶部「已保存」指示（§5.4） |
| 删除成功 | 关闭确认框 + `setReloadKey` 刷新列表 + ok toast（`toast.saved`） |
| 项目 DELETE 成功 | 本地移除 + currentProjectId 若等于删除 id → 置 null + ok toast |

## 4. CLI 命令签名

**无变更**。本批为纯前端 GUI 批次，不涉及 CLI（F7 约定 CLI 面保持现状；设定库 CRUD 的 CLI 缺口登记 #251，另行排期）。

---

## 5. 关键差异节（前端交互型 — 本模块类型）

### 5.1 列表行操作按钮（D12）

- 六分类（非 RAG）列表行 `<li>` 加类 `lib-item`（D12 CSS 选择器锚点：`.lib-item` 悬停显示操作按钮）。
- 行内操作按钮（悬停显示，不悬停隐藏但保留 tab 可达）：
  - 编辑：`data-testid="lib-edit-<id>"`，aria-label = `t('lib.edit') + ' ' + 名称`（图标 Pencil，lucide）
  - 删除：`data-testid="lib-delete-<id>"`，aria-label = `t('lib.delete') + ' ' + 名称`（图标 Trash2，lucide）
- 点击编辑按钮 → `setEditing(item)` + `setCreateOpen(true)`（复用既有对话框状态）。
- 点击删除按钮 → `setPendingDelete(item)`（打开 ConfirmDialog）。
- **RAG 分类行不渲染操作按钮**（无 PATCH/DELETE 端点）。

### 5.2 编辑保存流（library.tsx）

```
编辑按钮 → LibraryCreateDialog(editing=item) 预填现值
→ 用户改字段 → 保存 → handleSave(input):
    editing ? PATCH 扁平端点（§3.1 表）: POST 创建端点（#196 现状）
→ 成功: 关对话框 + setReloadKey + saveIndicator 'saved'(2s 自动隐藏)
→ 失败: err toast + 对话框保持（可修改重试）
```

- `handleCreate` 改造为 `handleSave`：分支 PATCH/POST（`editing` 状态非空 → PATCH）。
- PATCH 端点映射（按 activeCat）：characters→`/api/v1/characters/{id}`、world→`/api/v1/world-settings/{id}`、outline→`/api/v1/outlines/{id}`、timeline→`/api/v1/timeline/events/{id}`、foreshadow→`/api/v1/foreshadowings/{id}`。

### 5.3 删除确认流（library.tsx + ConfirmDialog）

```
删除按钮 → ConfirmDialog(testidPrefix='lib-confirm'):
  标题: t('lib.delete.title')（「删除{name}？」由调用方拼）
  文案: D11 统一「点击确认后立即移除（后台逻辑删除，30 天后彻底清除）」
  世界观追加行: 「该条目及其全部子条目将级联删除，不可恢复」
  确认按钮红色（danger）
→ 确认 → DELETE（世界观带 ?cascade=true）→ 关框 + reloadKey + toast('ok', toast.saved)
→ 取消 / Esc → 关框，不发请求
→ 遮罩点击 → 不关闭（#195）
```

- 确认框关闭路径仅：取消按钮 / Esc / 确认成功（父级 setPendingDelete(null)）。

### 5.4 顶部「已保存」指示器（#189 模式复用）

- library.tsx 页面顶部（面包屑行右侧或标题下）渲染 `SaveState = 'idle' | 'saving' | 'saved'` 指示器：
  - `data-testid="lib-save-indicator"`；saving 文案 `t('lib.saving')`（「保存中…」），saved 文案 `t('lib.saved')`（「已保存」，复用 `set.saved` 语义，新增独立 key 更清晰）。
  - 成功 2s 自动隐藏（SAVE_INDICATOR_HIDE_MS = 2_000，对齐 settings.tsx #189 实现）。
  - **仅编辑保存路径驱动**（创建/删除保持现状：创建 = 关框 + 刷新，删除 = toast；任务书 P0 范围明确「PATCH 保存 → 已保存指示」）。

### 5.5 项目卡片菜单（重命名/删除，US-3）

- ProjectCard 右上角（writing-badge 同侧）加菜单按钮：`data-testid="project-card-menu-<id>"`（icon MoreHorizontal，lucide；**点击 stopPropagation**，防止触发卡片跳转 #232）。
- 菜单项（shadcn DropdownMenu 或轻量 popover，二选一按 react-frontend-stack 既有组件约定）：
  - 重命名：`data-testid="project-rename-<id>"` → 打开重命名对话框
  - 删除：`data-testid="project-delete-<id>"` → 打开删除确认框
- **重命名对话框**（轻量单字段）：`data-testid="project-rename-dialog"`；输入 `project-rename-input`（预填现名，strip 非空才可保存）；保存 `project-rename-save` → `store.renameProject(id, name)` → PATCH 成功 → 关框 + ok toast；失败 → err toast + 框保持；取消 `project-rename-cancel` / Esc 关闭；遮罩不关闭（#195）。
- **删除确认框**：`ConfirmDialog(testidPrefix='project-delete')`；文案明示项目数据范围：「删除项目「{name}」？其章节、设定、大纲、时间线数据将全部删除」+ D11 统一行；确认 → `store.deleteProject(id)` → 卡片消失 + ok toast；若删除的是当前项目 → currentProjectId 置 null（面包屑/写作页随之回到未选态）。
- 菜单按钮/菜单项键盘可达（role=button + tabIndex，对齐 #232 可点击卡片先例）。

### 5.6 store action 语义

- `renameProject` / `deleteProject` 失败 **rethrow**（页面 catch → err toast；对齐 #125 行为契约升级：store 不吞错）。
- `deleteProject` 成功同步更新本地三处：projects 数组、currentProjectId（条件置 null）、chapterProgress（删除键）。

## 6. 组织规则（i18n 键）

新增 key 表（zh.ts / en.ts 同步；命名空间 lib.* 沿用现状，pj.* 沿用项目页现状）：

| key | zh | en | 说明 |
|-----|----|----|------|
| `lib.edit` | 编辑 | Edit | 行操作按钮 |
| `lib.delete` | 删除 | Delete | 行操作按钮 |
| `lib.edit.title.characters` | 编辑角色 | Edit Character | 编辑对话框标题（5 分类各一） |
| `lib.edit.title.world` | 编辑世界观 | Edit World Setting | |
| `lib.edit.title.outline` | 编辑大纲 | Edit Outline | |
| `lib.edit.title.timeline` | 编辑时间线事件 | Edit Timeline Event | |
| `lib.edit.title.foreshadow` | 编辑伏笔 | Edit Foreshadowing | |
| `lib.edit.save` | 保存 | Save | 编辑模式保存按钮（可复用 `lib.create.save`，独立 key 语义清晰） |
| `lib.saving` | 保存中… | Saving… | 顶部指示器 saving 态 |
| `lib.saved` | 已保存 | Saved | 顶部指示器 saved 态 |
| `lib.delete.title` | 删除{name}？ | Delete {name}? | 确认框标题（{name} 参数） |
| `lib.delete.confirm` | 点击确认后立即移除（后台逻辑删除，30 天后彻底清除） | Removing immediately after confirmation (soft delete; permanently purged after 30 days) | **D11 统一文案** |
| `lib.delete.worldCascade` | 该条目及其全部子条目将级联删除，不可恢复 | This entry and all its children will be cascade-deleted and cannot be recovered | 世界观追加行 |
| `lib.delete.ok` | 确认删除 | Delete | 确认按钮（红色） |
| `pj.rename` | 重命名 | Rename | 卡片菜单项 |
| `pj.delete` | 删除 | Delete | 卡片菜单项 |
| `pj.rename.title` | 重命名项目 | Rename Project | 重命名对话框标题 |
| `pj.rename.placeholder` | 项目名称 | Project name | 输入占位/aria-label |
| `pj.rename.save` | 保存 | Save | 重命名保存按钮 |
| `pj.delete.title` | 删除项目「{name}」？ | Delete project "{name}"? | 项目删除确认标题 |
| `pj.delete.range` | 其章节、设定、大纲、时间线数据将全部删除 | Its chapters, settings, outlines, and timeline data will all be deleted | 项目数据范围明示 |
| `pj.delete.ok` | 确认删除 | Delete | 确认按钮（红色） |

复用既有：`dlg.cancel`（取消）、`toast.saved`（已保存 toast）、`lib.create.*`（创建模式字段 label）、`lib.loadFailed`/`lib.retry`。

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| E1 | 编辑保存 PATCH 失败（404/422/网络） | err toast（errorMessage）+ 对话框保持打开可重试（对齐 #196） |
| E2 | 删除 DELETE 失败 | err toast + 列表不变 + 确认框关闭（失败后不再重复确认） |
| E3 | 世界观条目删除（有/无子条目） | 统一级联警告文案 + `?cascade=true`（§3.1 决策） |
| E4 | RAG 分类行 | 不渲染编辑/删除按钮（无端点） |
| E5 | 编辑预填字段缺失（旧数据/子集 mock） | `?? ''` 兜底空串，必填字段为空时保存按钮 disabled（复用 canSave） |
| E6 | 重命名输入 strip 后为空 | 保存按钮 disabled（对齐 NewProjectDialog 书名校验） |
| E7 | 删除的是当前项目（currentProjectId === id） | deleteProject 成功后 currentProjectId 置 null；项目页/设定库/写作页回到未选态 |
| E8 | 项目删除确认文案 | D11 统一行 + 数据范围行（章节/设定/大纲/时间线） |
| E9 | 确认框遮罩点击 / Esc | 遮罩点击不关闭（#195）；Esc 关闭；取消按钮关闭；均不发请求 |
| E10 | 菜单按钮点击冒泡 | stopPropagation 防止触发卡片跳转（#232） |
| E11 | 保存中重复点击 | 保存按钮 disabled（saving 态，复用 #196 模式） |
| E12 | 列表刷新失败（删除/编辑后 reloadKey 触发） | 既有 error 态 + library-retry 兜底（#105 修复批，不新增逻辑） |

## 8. 文件结构

| 操作 | 文件 | 变更 |
|------|------|------|
| MODIFY | `frontend/packages/renderer/src/pages/library.tsx` | 列表行操作按钮（5.1）、编辑状态 + handleSave PATCH/POST 分支（5.2）、删除确认（5.3）、顶部保存指示器（5.4）、`lib-item` 类 |
| MODIFY | `frontend/packages/renderer/src/components/LibraryCreateDialog.tsx` | props 扩展 `editing?` + `onCreate→onSave`；打开预填（2.2） |
| NEW | `frontend/packages/renderer/src/components/ConfirmDialog.tsx` | 共享删除确认框（2.3） |
| MODIFY | `frontend/packages/renderer/src/components/ProjectCard.tsx` | 卡片菜单按钮 + 菜单项（5.5）；stopPropagation |
| MODIFY | `frontend/packages/renderer/src/pages/projects.tsx` | 重命名对话框 + 删除确认框装配（5.5）；调用 store actions |
| MODIFY | `frontend/packages/renderer/src/stores/project.ts` | `renameProject` / `deleteProject` actions（2.4） |
| MODIFY | `frontend/packages/renderer/src/i18n/zh.ts` / `en.ts` | §6 key 表 |
| MODIFY | `frontend/packages/renderer/src/pages/library.test.tsx` | 追加编辑/删除契约（§9） |
| MODIFY | `frontend/packages/renderer/src/pages/projects.test.tsx` | 追加重命名/删除契约（§9） |
| MODIFY | `frontend/packages/renderer/src/stores/project.test.ts` | 追加 renameProject/deleteProject 契约（§9） |

> 无新测试文件 → ci.yml 前端测试 job 无需登记（既有 renderer test job 覆盖全仓测试文件）。
> 本批**不新建** `LibraryEditDialog`：复用 LibraryCreateDialog 双模式（§12 D-1）。

---

## 9. 测试策略

### 9.1 层次与工具

- **前端单元/组件契约**（Vitest + RTL，RED 批先行——F15 起 TDD 硬纪律，前端不破例）：本批唯一测试层。
- E2E：**本批不补**（任务书 P0 交付物未强制；编辑保存/删除确认/取消的 E2E 契约登记为 P1 批次前置必补项，届时 inkflow-e2e-testing 流程 PYTHONUTF8=1 + build renderer dist）。

### 9.2 RED 契约文件与用例（全部 MODIFY 既有文件追加 describe）

**library.test.tsx 追加（F43 编辑/删除契约）**：

| # | 用例 | 断言要点 |
|---|------|---------|
| L1 | 行编辑按钮点击 → 对话框打开且预填现值 | 点击 `lib-edit-c1` → `library-create-dialog` 出现，名称 input value = '林晚'（getByDisplayValue） |
| L2 | 编辑保存 → PATCH 扁平端点 + 列表刷新 + 已保存指示 | 改名称 → 保存 → `PATCH /api/v1/characters/c1` body `{name,...}`；关框；`lib-save-indicator` 文本 '已保存'；列表显示新名 |
| L3 | 编辑保存失败 → err toast + 对话框保持 | PATCH reject → err toast + `library-create-dialog` 仍在 |
| L4 | 行删除按钮 → 确认框（D11 文案） | 点击 `lib-delete-c1` → `lib-confirm-dialog` 含「点击确认后立即移除（后台逻辑删除，30 天后彻底清除）」+ 标题含名称 |
| L5 | 确认删除 → DELETE + 列表刷新 + toast | 点 `lib-confirm-ok` → `DELETE /api/v1/characters/c1`；列表消失；ok toast |
| L6 | 世界观删除 → 级联警告 + `?cascade=true` | 世界观 tab 点删除 → 确认框含级联文案；确认 → `DELETE /api/v1/world-settings/w1?cascade=true` |
| L7 | 取消/遮罩不关闭（#195） | 点 `lib-confirm-cancel` → 关闭且零 DELETE 调用；重开点遮罩 → 仍打开 |
| L8 | Esc 关闭确认框 | keydown Escape → 关闭，零请求 |
| L9 | 删除失败 → err toast + 列表不变 | DELETE reject → err toast；条目仍在 |
| L10 | RAG 行无操作按钮 | RAG tab → 行内无 `lib-edit-*`/`lib-delete-*` |

**projects.test.tsx 追加（F43 项目菜单契约）**：

| # | 用例 | 断言要点 |
|---|------|---------|
| P1 | 卡片菜单按钮 → 菜单项（重命名/删除） | 点击 `project-card-menu-p1` → `project-rename-p1` / `project-delete-p1` 可见 |
| P2 | 菜单按钮不触发卡片跳转 | 点击菜单按钮 → currentProjectId 不变、无 writing 路由跳转 |
| P3 | 重命名：输入新名 → PATCH body `{name}` → 卡片更新 + toast | 打开 `project-rename-dialog`（input 预填 '青云志'）→ 改名 → `project-rename-save` → `PATCH /api/v1/projects/p1` body `{name:'新名'}` → 卡片显示新名 |
| P4 | 重命名失败 → err toast + 框保持 | PATCH reject → err toast + dialog 仍在 |
| P5 | 删除：确认框（数据范围文案）→ DELETE → 卡片消失 | `project-delete-p1` → `project-delete-dialog` 含「章节、设定、大纲、时间线」+ D11 行 → ok → `DELETE /api/v1/projects/p1` → 卡片消失 |
| P6 | 删除当前项目 → currentProjectId 置 null | currentProjectId='p1' 时删除 p1 → store.currentProjectId === null |
| P7 | 删除取消 → 零请求 | cancel → 无 DELETE 调用 |

**stores/project.test.ts 追加（store actions 契约）**：

| # | 用例 | 断言要点 |
|---|------|---------|
| S1 | renameProject：PATCH + 本地更新 | mock PATCH 返回 → projects[0].name 更新 |
| S2 | renameProject 失败 rethrow | PATCH reject → `await expect(...).rejects.toThrow()` + 本地不变 |
| S3 | deleteProject：DELETE + 本地移除 + 进度清理 | 删除 p1 → projects 不含 p1、chapterProgress 无 p1 |
| S4 | deleteProject 删除当前项目 → currentProjectId null | currentProjectId='p1' → 删 p1 → null |
| S5 | deleteProject 失败 rethrow | DELETE reject → rejects + 本地不变 |

### 9.3 覆盖率

- 本批无新组件级测试文件（ConfirmDialog 由 L4-L9/P5-P7 消费方契约全覆盖，不单列）。
- 目标：追加用例后 renderer 包测试全绿（既有基线 + 新增 ≈ 15-18 用例）；前端 CI job 无新增文件登记。

## 10. 不在范围内

| 项 | 归属 | 原因 |
|----|------|------|
| 角色等级必填 + 标签多选（D1/D2） | P1 批次 | 需 extra 字段读写 + 筛选 UI |
| 世界观树/分类筛选/复制 GUI（D3/D4） | P1 批次 | parent_id 树渲染 + copy 端点消费 |
| 地图工作台（D5-D7） | P2 批次 | F36 资产 + pins 扩展 |
| 大纲三级 + 章关联（D8/D9） | P3 批次 | level 字段 + 章节 FK |
| 时间线双序 + 两级检查（D10） | P4 批次 | check 端点消费 + 双视图 |
| 删除 30 天清理 job（#211 对齐） | P5 批次 | 后端清理任务 |
| RAG 分类编辑/删除 | 无归属 | 无 PATCH/DELETE 端点（extractions/runs 为运行记录） |
| 世界观 reparent/复制交互 | P1 批次 | 本批仅 cascade 删除路径 |
| 项目硬删除/恢复（force/restore） | 无归属 | GUI 不暴露危险操作，软删语义由确认文案表达（D6） |
| CLI 设定库 CRUD | #251 | 另行排期 |
| E2E 编辑/删除契约 | P1 前置 | 本批单元/组件契约先行 |

---

## 11. 依赖关系

| 依赖 | 状态 | 说明 |
|------|------|------|
| #284（设定库 GUI 升级总 issue） | ✅ OPEN | 本批为 P0 子批次，PR body `Closes #284` 不成立 → 本批 PR 用 `Part of #284` 语义（spec 关联 + PR body 注明进度，issue 不关闭，M5 门禁） |
| 后端六分类 PATCH/DELETE 端点 | ✅ 已就绪 | §3 表已逐文件核实（characters/world_settings/outlines/timeline/foreshadowings/project routers） |
| #196 创建对话框 | ✅ 已合 | LibraryCreateDialog 双模式改造基座 |
| #189 已保存指示模式 | ✅ 已合 | settings.tsx SaveState 模式复用 |
| #195 遮罩不关闭拍板 | ✅ 已合 | 新确认框遵守 |
| #232 可点击卡片 a11y 三件套 | ✅ 已合 | 菜单按钮键盘可达复用 |
| #211 删除语义统一 | ⏳ OPEN | P5 批次对齐；本批确认文案已按 D11 预留切换点（§3.1 注） |

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 备选否决 |
|---|------|------|---------|
| D-1 | LibraryCreateDialog 双模式扩展（`editing` prop）而非新建 LibraryEditDialog | 字段结构/校验/关闭路径全复用，改动面最小；testid 契约零回归 | 新建独立编辑对话框（重复 ~300 行表单逻辑） |
| D-2 | 删除确认 = 共享 ConfirmDialog 组件 | 设定库 + 项目两处消费（Rule of Two 已到）；testidPrefix 避免同屏冲突 | 两处各自内联确认框（重复遮罩/Esc/按钮逻辑，且 #195 语义易漂移） |
| D-3 | 世界观删除统一 `?cascade=true` + 级联警告 | 任务书 D11 拍板方案；零预查询，交互最简；后端 cascade 优先语义保证有子条目必删成功 | A. 预查询 descendants 决定参数（多 1 请求，语义更精确但复杂）；B. 试删 422 后升级确认（两次确认交互重） |
| D-4 | 删除/编辑失败 store rethrow + 页面 toast | 对齐 #125 行为契约升级（store 不吞错）；页面单一错误呈现点 | store 内吞错置 error 字段（项目页 error 态语义不同，复用会混） |
| D-5 | 编辑成功 → 顶部「已保存」指示；删除成功 → toast | 任务书指定（#189 模式 vs 既有 toast 语义）；指示器仅编辑路径驱动，创建/删除不扩 | 全部用 toast（丢 #189 顶部指示产品语义）；全部用指示器（删除是破坏性操作，toast 更醒目） |
| D-6 | 项目重命名为轻量单字段对话框，不复用 NewProjectDialog | NewProjectDialog 是完整创建表单（题材/语言/字数/模板），重命名只需名称 | 复用 NewProjectDialog（表单语义错位，误改其它字段风险） |

---

## 13. 验收标准

| # | 验收项 | 验证方式 |
|---|--------|---------|
| M1 | 六分类列表行编辑：预填现值 → PATCH 扁平端点 → 列表刷新 + 「已保存」顶部指示（2s 隐藏） | library.test.tsx L1-L3 + 手动核对 |
| M2 | 六分类列表行删除：确认框 D11 统一文案 → DELETE → 列表刷新 + toast | library.test.tsx L4-L5/L9 |
| M3 | 世界观删除：级联警告文案 + `?cascade=true` | library.test.tsx L6 |
| M4 | 确认框 #195：遮罩点击不关闭；关闭仅 取消/Esc/成功 | library.test.tsx L7-L8 |
| M5 | 项目重命名：卡片菜单 → 预填 → PATCH `{name}` → 卡片更新 | projects.test.tsx P1-P4 |
| M6 | 项目删除：确认框明示数据范围 + D11 行 → DELETE → 卡片消失；当前项目删除 → currentProjectId 置 null | projects.test.tsx P5-P7 |
| M7 | store actions：renameProject/deleteProject（rethrow / 本地三处同步） | project.test.ts S1-S5 |
| M8 | RED 批全 FAIL 实证存档 → Codex GREEN → 本地前端测试全绿 | 测试输出存档（RED） + `pnpm --filter renderer test` 全绿（GREEN） |
| M9 | PR 合入 + CI 全绿（statusCheckRollup 对照）+ spec 同 PR 合入 | gh pr checks 轮询 |
| M10 | issue #284 保持 OPEN，PR body 注明 P0 完成 / P1-P5 未做 | gh issue view |

---

## 14. 待澄清问题

无阻塞级待澄清——本批交互/文案/反馈路径全部由任务书 + 决策文档 D11/D12 + 既有拍板（#189/#195/#196/#232）指定。以下为已拍板留痕：

- **Q1（✅ 已确认，用户拍板：D11 决策文档）**：世界观删除 = 统一级联警告 + `cascade=true`，不预查询 descendants。正文 §3.1 已按拍板落实。
- **Q2（✅ 已确认，任务书指定）**：编辑保存反馈 = #189 顶部「已保存」指示器；删除反馈 = toast（`toast.saved`）。正文 §5.4/§3.3 已落实。
- **Q3（✅ 已确认，任务书 P0 范围）**：本批不补 E2E，编辑/删除 E2E 契约登记 P1 批次前置必补项。正文 §9.1 已落实。

---

*（Spec 完。实现阶段：Plan → RED（测试先行全 FAIL 实证）→ Codex GREEN（唯一编码执行者）→ QA → PR `feat(gui): ...` body `Part of #284` + 进度注明。）*
