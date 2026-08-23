# F6 上下文面板 GUI（ContextPanel 接 API）— 交互规格（#594）

> **Spec 版本**: 1.0 | **日期**: 2026-08-23 | **依据**: PRD v2.1 §6.1 F6, f6-context-service/spec.md v1.1 (issue #593), f19-gui/spec.md §4.2.1, issue #594
> **所属范围**: 上下文面板由**静态占位**改造为**接 assemble API 渲染真实上下文条目**（F6 调试/P2 Web UI 的前置一步，#594）
> **关联 Issues**: [#594](https://github.com/zhx-xi/InkFlow/issues/594)
> **依赖**: F6 v1.1（#593：override 通道 + Character.brief 已合入 main）、#592（角色档案 brief）

> **Spec 变更说明**：f6-context-service/spec.md §10 声明「上下文可视化调试 UI → Phase 2 Web UI」不在后端 spec 范围；
> 本文件为 **#594 前端接 API 的 GUI 交互契约**，与后端 spec 无冲突，作为其 GUI 补充。决策已拍板（2026-08-23）：D3=A 三级全注入；D4=A 先自动注入+展开/修改；覆盖 D1 override 通道（#593 已做）。

---

## 1. 概述

写作页右侧「上下文注入」面板（现有 `ContextPanel.tsx` 为静态占位，4 张卡片恒显 `common.empty`）改造为：
挂载/项目切换/章节切换时调 **`POST /api/v1/context/assemble`** 预览当前上下文组装结果，
按来源展示真实条目（写作要求/大纲/角色/世界观/章节摘要/伏笔）：
- **大纲**自动注入三级（总体/卷/章），缺级降级（后端 `OutlineSource` 已合并渲染，前端透传展示）；
- **角色/伏笔**条目展示为**可勾选标签**，勾选状态经 `override` 通道反向影响组装结果（白名单语义）；
- 无数据 / 未选章节 → 空态；折叠条（26px）保留不变。

### 1.1 与既有模块边界

- **新建** `src/api/context.ts`：封装 `assembleContext()`（唯一新 API 封装，走既有 `apiFetch`）。
- **改造** `src/components/ContextPanel.tsx`：静态占位 → 数据驱动。**不新增**角色/伏笔独立列表 API——
  候选「可勾选注入项」从 assemble 结果中提取 `character_setting` / `foreshadowing` 来源的 blocks
  （避免范围膨胀；被预算裁剪的条目只出现在 `dropped`，不展示为勾选项）。
- **改造** `src/pages/writing.tsx`：给 `<ContextPanel />` 传 `projectId` / `chapterId` / `model` / `writingRequirements` props。
- **i18n**：zh.ts / en.ts 补 `write.context.*` 新 key。

### 1.2 关键决策（已拍板）

| 决策 | 结论 |
|------|------|
| D1 override 通道 | ✅ 已由 #593 后端实现（context_service `_apply_override`）——本 spec 只做前端勾选接线 |
| D3 大纲注入 | A：三级（总体/卷/章）全注入；缺级降级由后端保证，前端透传 content |
| D4 交互 | A：面板自动注入（挂载/切章即 assemble）+ 角色/伏笔标签可展开勾选 + 点击修改 |

---

## 2. API 契约（前端消费面）

### 2.1 `POST /api/v1/context/assemble`

请求体（`ContextRequest`，后端 Pydantic）：

```json
{
  "project_id": "3f2e1d4a-...",
  "chapter_id": "9b1c2d3e-...",
  "model": "deepseek/deepseek-v4-flash",
  "writing_requirements": "小说创作",
  "max_tokens": null,
  "override": { "character_ids": ["<uuid>"], "foreshadowing_ids": [] }
}
```

- `writing_requirements` **必填**（min_length=1）；GUI 预览用项目 `config.writing_style`，为空回退固定占位「上下文预览」。
- `override` 可缺省/为 null → 后端视为全注入。勾选语义（白名单）：
  - `character_ids` 非空 → 只注入 `metadata.character_id` 命中的角色；空 → 注入全部
  - `foreshadowing_ids` 非空 → 只注入 `metadata.foreshadowing_id` 命中的伏笔；空 → 注入全部
  - 只过滤 `character_setting` / `foreshadowing`，不影响 outline/world/summary 等

响应（`ContextAssemblyResult`）：

```json
{
  "blocks": [
    { "item": { "source": "outline", "title": "大纲", "content": "总体：……\n卷：……\n章：……",
                "priority": 0, "metadata": { "outline_ids": ["<uuid>"] } },
      "layer": "protected", "token_count": 120, "compressed": false }
  ],
  "budget_tokens": 51200,
  "total_tokens": 6420,
  "model": "deepseek/deepseek-v4-flash",
  "dropped": [ { "item": {}, "reason": "over_budget" } ]
}
```

`item.source ∈ {writing_requirements, outline, character_setting, world_setting, chapter_summary, foreshadowing, preference}`。

### 2.2 错误响应

- 400（`writing_requirements` 为空 / protected 超限）、404（项目/章节不存在）→ 前端展示错误文案，不崩溃。

---

## 3. 前端契约

### 3.1 组件 props（writing.tsx 传入）

```ts
interface ContextPanelProps {
  projectId: string | null;
  chapterId: string | null;
  model: string | null;             // 项目 config.model（provider/model 格式）
  writingRequirements: string;      // 项目 writing_style；为空回退「上下文预览」
}
```

### 3.2 testid

| testid | 说明 |
|--------|------|
| `context-panel` | 面板容器（保留） |
| `context-collapse` / `context-expand-bar` | 折叠/展开（保留，26px 折叠条不变） |
| `context-panel-content` | 内容区（保留） |
| `context-empty` | 空态（无 projectId/chapterId/model 或 blocks 为空） |
| `context-error` | 错误提示（assemble 失败） |
| `context-block-<source>` | 每个来源分组容器（source = `writing_requirements`/`outline`/`character_setting`/`world_setting`/`chapter_summary`/`foreshadowing`） |
| `context-outline` | 大纲块（含三级 content 透传，`whitespace-pre-wrap` 保留换行） |
| `context-character-<n>` | 第 n 个角色注入项（勾选标签） |
| `context-foreshadow-<n>` | 第 n 个伏笔注入项（勾选标签） |
| `context-item-toggle-<n>` | 角色/伏笔项内勾选开关（checkbox） |
| `context-dropped` | 被裁剪条目区（dropped 非空时展示；含 `context-dropped-<n>`） |

> 注：`<n>` 为角色/伏笔各自序号（0 起），跨来源独立序号，与 ChatPanel `chat-msg-<kind>-<seq>` 惯例一致。

### 3.3 行为

- **自动注入**：挂载 / `projectId` / `chapterId` 变化 → 调 `assembleContext`，渲染 blocks 按 source 分组。
  - 有 projectId + chapterId + model 才 assemble；任缺 → 空态。
  - assemble 请求 `override` 由当前勾选集构造；`writing_requirements` 固定传 props。
- **三级大纲**：`outline` block 的 `content` 原样渲染（后端已合并 `总体/卷/章：name —— desc` 多行，
  `whitespace-pre-wrap` 保留换行）；缺级降级由后端保证，前端透传。
- **角色/伏笔勾选（override 白名单）**：
  - 从 blocks 中提取 `character_setting` / `foreshadowing` 来源条目作为「注入项」，每项渲染勾选标签。
  - 初始勾选状态 = 该项当前在 blocks（即已注入）；全部注入时 override 传空数组（= 全注入）。
  - 取消某项 → 其 id 从 `override.character_ids` / `foreshadowing_ids` 移除 → 重新 assemble → 结果变化。
  - 勾选某项 → 其 id 加入对应数组 → 重新 assemble。
  - **白名单语义**：勾选集 = 被注入集合。`character_ids` 为空 = 注入全部；只勾选部分 = 只注入这些。
- **点击修改**：大纲块/角色/伏笔条目可点击 → 展开显示完整 `content`（默认折叠行数超限时）。v1 实现为
  「点击展开/收起条目内容」，不做行内编辑（编辑角色/伏笔本体属 F9/F13 管理页范围外）。
- **折叠条**：折叠态（26px）→ 仅 `context-expand-bar`；展开态 → 内容区 + `context-collapse`。保留既有实现。

### 3.4 i18n 新增 key（zh.ts / en.ts 同步）

```ts
write.context.inject        // 注入
write.context.required      // 写作要求
write.context.outline       // 大纲（已有，复用）
write.context.characters    // 角色（已有）
write.context.world         // 世界观（已有）
write.context.foreshadow    // 伏笔（已有）
write.context.dropped       // 已裁剪
write.context.tokens        // {total}/{budget} tokens
```

> 复用已有：`write.context.title` / `write.context.collapse` / `write.context.expand` / `common.empty`。

---

## 4. 边界与错误表

| 场景 | 行为 |
|------|------|
| 无 projectId / 无 chapterId / model 为空 | 空态 `context-empty`（不调 assemble） |
| blocks 为空（项目无角色/大纲/摘要等） | 空态（保留「暂无数据」提示，但**有数据时不得显示空态**） |
| assemble 失败（网络/400/404） | `context-error` 显示错误文案，不崩溃 |
| override 全不勾选（character_ids 空） | 后端视为全注入（默认行为） |
| 角色/伏笔被预算裁剪 | 出现在 `dropped` → 渲染到 `context-dropped` 区；不进勾选项 |
| outline 缺级 | 后端合并 content 只含存在的级；前端透传展示（缺级降级） |
| 折叠态 | 26px 折叠条，仅展开按钮；不触发 assemble（懒加载）—— 展开后首次再挂载时自动注入 |

---

## 5. 测试策略（前端 RED，Vitest + RTL）

### 5.1 `ContextPanel.test.tsx`（RED 契约，核心 3 用例）

1. **有数据显示真实条目（非空态）**：mock `assembleContext` 返回含 outline + character 的 blocks →
   断言渲染 `context-block-outline` / `context-block-character_setting` / `context-character-0`，
   **不渲染** `context-empty`；空数据 → 渲染 `context-empty`。
2. **勾选/取消注入项 → 组装结果变化（override 生效）**：mock assemble 首次返回角色 A、B → 取消角色 A →
   断言 `assembleContext` 被再次调用且 `override.character_ids` 不含 A（白名单语义）。
3. **三级大纲自动注入**：mock assemble 返回 outline block（content 含 `总体：…\n卷：…\n章：…`）→
   断言 `context-outline` 显示三段文本（含换行保留）。

**守护用例**（当前实现天然 PASS，防回归）：折叠态渲染 `context-expand-bar` 且无 `context-panel-content`；
`context-collapse` 点击切换。

### 5.2 mock 方式

- `vi.mock('../api/context')` → `assembleContext` 捕获 body（含 override），用例手动改写 resolved 值。
- `apiFetch` 走既有封装（ContextPanel 只经 `assembleContext`，不裸 fetch）。

### 5.3 QA 门禁

```
cd frontend/packages/renderer; pnpm vitest run && pnpm tsc --noEmit
```

---

## 6. 文件结构

| 文件 | 变更 |
|------|------|
| `frontend/packages/renderer/src/api/context.ts` | NEW：`assembleContext()` + 类型（ContextRequest/Override/Block/Item/Result） |
| `frontend/packages/renderer/src/components/ContextPanel.tsx` | MODIFY：静态占位 → assemble 数据驱动 + 三级大纲 + 勾选 override |
| `frontend/packages/renderer/src/components/ContextPanel.test.tsx` | NEW（RED） |
| `frontend/packages/renderer/src/pages/writing.tsx` | MODIFY：`<ContextPanel />` 传 props |
| `frontend/packages/renderer/src/i18n/zh.ts` / `en.ts` | MODIFY：§3.4 key |

> 900 行护栏：ContextPanel.tsx 若超行 → 拆子组件（如 `ContextBlockSection` / `ContextToggleItem`）。

---

## 7. 范围外

- 角色/伏笔的**行内编辑**（改 brief/优先级）→ F9/F13 管理页。
- 独立「角色/伏笔候选列表」API（项目全量角色/伏笔作为勾选项）→ 后续 issue（当前只从 assemble 结果提取）。
- 预算/分层可视化（每层 token 占比图）→ 后续。
- E2E（真实渲染验证三级换行）+ 后端联调零真实 LLM 的 page.route 拦截 → 本 issue 暂以单元层覆盖。
