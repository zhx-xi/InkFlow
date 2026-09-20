# 成书页 · 书级编排 — 交互规格

> 页面: book | 路由: /book | 组件: pages/book.tsx（BookPage）+ components/BookPlannerPanel + components/BookRunPanel
> 对应 design/GUI/book/（官方简图 book-run.html + book-run-<state>.png）

## 1. 画面样式

- 原型引用：design/GUI/book/（book-run.html + book-run-running/completed/failed/degraded/degraded-expanded.png，共 5 张状态图）
- ⚠️ **命名说明**：本页原型文件名为 `book-run.html`（非其它 14 页的 `<page>.html` 形态），与其它页命名不统一。本规格沿用现状、**不做改名**（改名会同时动原型资产与 `design/GUI/_tools/` 截图脚本，收益低于风险）。一致性门禁 `ci_cd/check_gui_spec_sync.py` 只校验**目录级**对应（`design/GUI/book/` ↔ `specs/f19-gui/book.md`），对目录内文件命名无语义要求。
- ⚠️ **本页无侧边栏入口**（`AppNav.tsx` 无 book 项），仅 `App.tsx:169` 保留路由 `<Route path="/book" element={<BookPage />} />`。用户当前无法从导航点入本页；本规格按「已合入实现」记录现状，**不新增入口**（是否启用另议）。
> 低保真排版示意简图（区块+标签，非精确像素）

```text
┌──────────────────────────────────────────────────────────────┐
│ 顶栏：主题/语言 Select  窗口控制（壳层通用）                  │
├──────────────────────────────────────────────────────────────┤
│ 空态（无当前项目，data-testid=book-page-empty）：            │
│   文案 book.empty.title + CTA「去项目页」→ /projects          │
├──────────────────────────────────────────────────────────────┤
│ 有项目（data-testid=book-page，max-w-2xl 单栏）：            │
│  ┌─ 项目名（book-project，15px）                             │
│  └─ book-planner-panel  ★ 三态（先判 sessionStatus，再判 runId）
│     ├─ 态 1（sessionStatus !== 'completed'）＝ 访谈 / 起点配置：
│     │   [项目 Select] [起点模式 Select] [源大纲 Select]
│     │   一句话输入（book-one-liner，必填才启用开始）
│     │   [开始访谈 book-planner-start]
│     │   对话消息流（book-msg-list）：
│     │     user 气泡 / assistant 提问（book-question-<qid>）
│     │     + 用模板（book-template-<qid>）
│     │     确认卡片（book-confirm-card）逐项 确认/编辑
│     │   底部回答框（book-answer）+ [发送 book-send]
│     └─ 态 2/3（sessionStatus === 'completed'）＝ 计划卡 / 运行面板：
│        ├─ runId === null → 计划卡：
│        │    计划标题（book-plan-title = writingPlan.title）
│        │    计划状态（book-plan-status）＝ auto / ready 二档
│        │    上限配置 4 项（book-limits-chapters / calls /
│        │      tokens / sessions，数值型）
│        │    [保存 book-limits-save] [开始运行 book-start-run]
│        └─ runId !== null → book-run-panel（BookRunPanel）：
│             运行状态徽标 run-status（四档着色）
│             失败原因 run-progress-reason（>200 字截断+展开）
│             干预 [暂停 run-intervene-pause / 恢复 resume]
│             密度三档 run-density-performance/dashboard/silent
│             [回归摘要 run-summary-toggle]
│             diff banner（run-diff-banner，可关闭）
│             计数：run-counter-chapters / calls / tokens
│             token 预警 run-token-warning
│             进度条 run-progress-bar（done/total）
│             进度列表 run-progress-list ★（见 §3 待定义）
│               = 逐 outlineId 渲染 ExecutionTraceRow
│                 （五态徽标 pending/in_progress/done/
│                   failed/skipped，默认折叠可展开）
│             回归摘要面板（run-summary-toggle 开启时）
└──────────────────────────────────────────────────────────────┘
```

- 参考锚点（真实实现，F44 阶段1 + 阶段4 #338 S4b + #903）：
  - 页壳（`pages/book.tsx`，42 行，极薄）：无当前项目 → `book-page-empty` + `book-page-go-projects`（`navigate('/projects')`）；有项目 → `book-project`（项目名）+ `<BookPlannerPanel projectId={effectiveProjectId} />`。项目解析顺序 = `currentProjectId ?? projects[0]?.id ?? ''`
  - 访谈面板（`components/BookPlannerPanel.tsx`）：`book-project-select`（起点项目）/ `book-start-mode`（起点模式）/ `book-source-outline`（源大纲，#544）+ `book-one-liner` 一句话 + `book-planner-start`（一句话非空才 enabled）+ 对话流 `book-msg-list`（`book-msg-user-<i>` / `book-question-<qid>` / `book-template-<qid>` 用模板 / `book-confirm-card` + `book-confirm-item-<key>` + `book-confirm-ok` / `book-confirm-edit-<key>` → `book-confirm-edit-input-<key>` → `book-confirm-edit-submit-<key>`）+ `book-answer` + `book-send` + 错误行 `book-planner-error`
  - 计划/运行态（同文件 runId !== null 分支）：`book-plan-title`（`writingPlan.title`）+ `book-plan-status` + 上限配置输入（`book-limit-*`，数值型）+ `book-limits-save`（saving 时禁用）+ `book-start-run` + 错误行 `book-start-error`
  - 运行面板（`components/BookRunPanel.tsx`）：
    - 轮询：`runId !== null` 时 `startPolling(loadRunStatus, 终态判据 status !== 'running' && !== 'pending')`，**1s 间隔**至终态后自动停
    - 状态徽标 `run-status`：四档语义类（`RUN_BADGE_CLASSES`）—— `completed`（ok 绿）/ `failed`（err 红）/ `degraded`（warn 橙）/ 其它（中性 surface-3）。取值来自 `useBookStore().runStatus`
    - 失败原因 `run-progress-reason`：仅 `failed | degraded` **且** `progressReason` 非空时渲染；`reasonLong = progressReason.length > 200`（`REASON_EXPAND_THRESHOLD`）→ 默认 `line-clamp-3` + `run-progress-reason-toggle`（展开/收起，本地 state）
    - 干预工具栏：`running` → `run-intervene-pause`；`paused` → `run-intervene-resume`（互斥渲染）
    - 密度三档（本地 state，**零额外请求**）：`run-density-performance`（章行内干预控件）/ `run-density-dashboard` / `run-density-silent`（**不渲染** `run-progress-list`）；`aria-pressed` 标记当前档
    - `run-summary-toggle` → 切换 `BookSummaryPanel`；`run-diff-banner`（`interveneDiff` 非空时）+ `run-diff-close`
    - 计数三行：`run-counter-chapters`（`chapters_written / max_chapters`）、`run-counter-calls`（`agent_calls / max_agent_calls`）、`run-counter-tokens`（仅 `max_tokens` 与 `tokens_used` 均定义时渲染）
    - `run-token-warning`：`counters.tokens_warning === true` 时渲染
    - 进度条 `run-progress-bar`：`done / total`，宽度 = `min(100, round(done/total*100))%`（`total > 0` 才渲染）
    - 进度列表 `run-progress-list`：`Object.entries(progress)` → 逐 `outlineId` 渲染 `ExecutionTraceRow`（五态徽标 + 默认折叠）
    - `VolumeHITLDialog`（卷级 HITL 确认框）
  - 未启动（**组件内部**分支）：`BookRunPanel` 内的 `runId === null` → `book.run.noRun`（「暂无运行」）纯文本，无工具栏
    - ⚠️ **同名遮蔽注意**：页级 `runId`（`useBookStore`）与 `BookRunPanel` 读取的 `runId` 是**同一个 store 字段**，但两处判断的分支不同——页级为 `null` 时**根本不会渲染 `BookRunPanel`**（走计划卡分支），故 `book.run.noRun` 实际只在「已渲染面板但 store 的 runId 又被清空」时可见。规格按实现忠实记录，此分支可达性未实测（见 §3 待定义）
- 布局说明：纵向单栏（`max-w-2xl`）；访谈态与「计划卡 / 运行面板」互斥（由 `sessionStatus` 切换），计划卡与运行面板互斥（由 `runId` 切换）；运行面板内区块按「状态 → 失败原因 → 工具栏 → diff → 计数 → 进度 → 列表 → 摘要」顺序堆叠

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 去项目页（book-page-go-projects） | 无当前项目时显示 | `navigate('/projects')` | — | 跳转 | — | 仅空态分支渲染 |
| 开始访谈（book-planner-start） | 一句话为空 → disabled | 提交一句话，进入对话流 | 禁用 | 追加 user 气泡 + assistant 提问 | `book-planner-error` | ESC/取消语义未定义（见 §3） |
| 用模板（book-template-<qid>） | assistant 提问行内按钮 | 以模板文本填充回答 | — | 回答框可继续编辑 | — | 不直接提交（需再点发送） |
| 发送（book-send） | 回答框非空白（`answer.trim() !== ''`） | 追加 user 气泡 | — | 生成下一问或确认卡 | err 行 | 空白不可提交 |
| 确认卡确认（book-confirm-ok） | 确认卡渲染时 | 接受全部条目 | — | 进入下一阶段/启动 | err 行 | 逐项可先「编辑」再确认 |
| 确认卡编辑（book-confirm-edit-<key> → submit） | 条目行内 | 展开 `book-confirm-edit-input-<key>` → 提交该条 | 提交中 | 条目文案更新 | err 行 | 提交后收起输入 |
| 保存上限（book-limits-save） | 可点 | 提交 4 项上限（max_chapters / max_agent_calls / max_tokens / max_sessions） | `limits.saving` → disabled + 文案切 `set.saving` | 值回显 | `book-start-error` | 数值型输入（null → 空串显示），非法值由后端校验 |
| 开始运行（book-start-run） | 计划态可点 | 启动 book run → `runId` 置值 | 禁用 | 切到运行面板 | `book-start-error` | 同一计划重复启动语义未定义（见 §3） |
| 暂停（run-intervene-pause） | `running` 时渲染 | POST pause | — | 状态转 `paused` → 按钮换成 resume | err | 非 running 态不渲染该按钮 |
| 恢复（run-intervene-resume） | `paused` 时渲染 | POST resume | — | 状态转 `running` | err | 非 paused 态不渲染该按钮 |
| 密度三档（run-density-performance / dashboard / silent） | `aria-pressed` 标记当前档 | 切换本地密度 | — | 列表/控件密度即时变化 | — | `silent` 下**不渲染** `run-progress-list`；零额外请求 |
| 回归摘要（run-summary-toggle） | 未展开 | 切换 `BookSummaryPanel` | — | 面板显隐 | — | 纯本地 state |
| 原因展开（run-progress-reason-toggle） | 仅 `length > 200` 时渲染 | 展开/收起全文 | — | `line-clamp-3` 解除/恢复 | — | ≤200 字不渲染该按钮 |
| diff 关闭（run-diff-close） | `interveneDiff` 非空时 | `clearInterveneDiff()` | — | banner 消失 | — | 只清展示，不回滚数据 |
| 进度行展开（ExecutionTraceRow） | 默认折叠 | 展开该章摘要/干预控件 | — | 行内控件显示 | — | `done` 章干预控件禁用（422 防呆） |

## 3. 待定义（自动写作任务列表 — 挂 0.16.0）

> ⚠️ **本节记录用户原始设计意图，不做完整定义也不实现**（完整定义 + 实现属 **0.16.0**，见 #1333 段 2）。

**用户原话（2026-09-20）**：

> 「我之前这个页面是想在**自动写作时让 agent 列出任务列表**，然后**用户可以实时看到当前进度**的，不过忘记实现了，先记上 issue，后续再完整定义并实现。」

**现状与意图的差距（已实测，非推断）**：

| 意图要素 | 现状 | 差距 |
|---|---|---|
| agent **列出任务清单** | ❌ 无「任务清单」实体。`run-progress-list` 的条目是 `Object.entries(progress)` 按 `outlineId` **派生**（章级），任务由大纲结构隐含，**非 agent 显式产出** | 需定义「任务」的产生方与协议（LLM 输出 / 从 book run progress 派生） |
| 任务**粒度** | 现状 = **章级**（1 outlineId = 1 行） | 是否下沉到「章内步骤级」未定 |
| 实时**看到进度** | ✅ **已具备骨架**：`ExecutionTraceRow` 五态徽标（`pending` / `in_progress` / `done` / `failed` / `skipped`）+ 1s 轮询 + 进度条 | 粒度与刷新语义需按「任务」重定义 |
| 状态**实时性** | 现状 = 1s 轮询 `GET /runs/{id}` 至终态 | 是否改走推送通道（F23 `/events/stream`）待定 |

**待定义清单（段 2 需先出设计，勿直接实现）**：

1. **任务产生方**：agent 产出任务清单（LLM 输出协议）还是从既有 `book run` 的 `progress` / `counters` / `execution_refs` 派生
2. **任务粒度**：章级 / 章内步骤级
3. **实时通道**：沿用 1s 轮询 vs 走 F23 变更推送 `/events/stream`
4. **与既有结构的关系**：`progress` / `counters` / `execution_refs` 是否需要扩展字段
5. **GUI 呈现**：列表 / 进度条 / 状态徽标——原型 `book-run.html` + 5 张 PNG 是**起点**（非最终形态）
6. **影响面**：是否波及 MCP / CLI 面
7. **导航入口**：本页当前无侧边栏入口（`AppNav.tsx` 无 book 项）；「任务看板」若成为主路径，需一并决定入口与路由是否启用
8. **未定义交互边界**（§2 表格中标注「见 §3」的两条）：① 同一计划重复启动 `book-start-run` 的语义（幂等 / 拒绝 / 新建 run）；② 访谈阶段是否需要 ESC / 取消语义（现实现无取消入口）
9. **`book.run.noRun` 分支可达性**（§1 同名遮蔽条）：页级 `runId === null` 时走计划卡、不渲染 `BookRunPanel`，故该空态文案的可达条件未实测——段 2 顺带澄清（若不可达，属死分支，应一并清理）

**关联**：#1333 段 2（0.16.0）· 原型资产 `design/GUI/book/book-run.html` + 5 PNG。

## 4. 验收

- N1：空态（无当前项目）→ `book-page-empty` + 「去项目页」跳 `/projects`
- N2：有项目 → `book-project` 显示项目名 + 访谈面板渲染
- N3：访谈流 → 一句话必填启用开始；user 气泡 / assistant 提问 / 用模板 / 确认卡（确认 + 逐项编辑）
- N4：计划态（`sessionStatus === 'completed'` 且 `runId === null`）→ 计划标题 + 状态二档（`auto` / `ready`）+ 4 项上限可保存（saving 禁用）+ 开始运行（`runId` 置值后切运行面板）
- N5：运行面板状态徽标四档着色（completed / failed / degraded / 其它中性）
- N6：失败原因块仅在 `failed | degraded` 且非空时渲染 + >200 字截断与展开/收起
- N7：干预按钮互斥（`running` → 暂停 / `paused` → 恢复）
- N8：密度三档切换为本地态零请求；`silent` 下不渲染 `run-progress-list`
- N9：计数三行 + token 预警（`tokens_warning`）+ 进度条（`total > 0`）按条件渲染
- N10：`run-progress-list` 逐 `outlineId` 渲染 `ExecutionTraceRow`，五态徽标 + 默认折叠
- N11：`runId === null` → `book.run.noRun`「暂无运行」纯文本，无工具栏
- N12：轮询 1s 间隔、终态自动停（`status` 既非 `running` 也非 `pending`）
