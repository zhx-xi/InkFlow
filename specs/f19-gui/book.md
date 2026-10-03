# 成书页 · 书级编排 — 交互规格

> 页面: book | 路由: /book | 组件: pages/book.tsx（BookPage）+ components/BookPlannerPanel + components/BookRunPanel
> 对应 design/GUI/book/（官方简图 book-run.html + book-run-<state>.png）
> **Spec 变更**（2026-10-02 · #1333 段 2）：§1 补任务列表三方案线框 + 原型引用；§2 新增控件行；§3 由「待定义」升级为完整设计定义（6 问结论 + 状态语义 + 漂移登记 + 待拍板）；§4 追加 N14-N21。设计轨产出见同 PR 的 `design/GUI/book/`。
> **实现轨回写**（同 PR · #1333 段 2）：§1 的「无侧边栏入口 / `book.run.noRun` 分支」已按拍板与实测结论改写；§3.4 D-1/D-2/D-3 已修复（D-3 含后端同族门控）；§4 N11/N18 口径按落地形态校正。

## 1. 画面样式

- 原型引用：design/GUI/book/ —— ① `book-run.html` + `book-run-<state>.png`（运行面板 7 态：running / completed / failed / degraded / degraded-expanded / reset-confirm / overwrite-notice，900×792）；② `book.html` + `book-<scheme>-<state>.png`（**段 2 任务列表**：scheme ∈ legacy（现状对照）/ a（侧栏）/ b（看板）/ c（单栏时间线），state ∈ running / blocked，另有 `book-legend.png` 状态语义图例；1280×800 @DPR1）。两套视口尺寸不同：① 是 #903/#1288 遗留资产（#1440 加 `overwrite-notice` 态），② 按项目标准视口（ui-prototype-workflow 坑 #27）
- ⚠️ **命名说明**：本页原型文件名为 `book-run.html`（非其它 14 页的 `<page>.html` 形态），与其它页命名不统一。本规格沿用现状、**不做改名**（改名会同时动原型资产与 `design/GUI/_tools/` 截图脚本，收益低于风险）。一致性门禁 `ci_cd/check_gui_spec_sync.py` 只校验**目录级**对应（`design/GUI/book/` ↔ `specs/f19-gui/book.md`），对目录内文件命名无语义要求。
- ✅ **本页侧边栏入口（#1333 段 2 已落地）**：`AppNav` WRITING 组新增「成书」项 → `/book`（`nav-item-book`，i18n `nav.book` = 「成书」/「Book」）。此前 #597 D11=A 曾删除该入口（本页沦为只能靠路由 `App.tsx` 直达的孤儿），段 2 §3.5-4 拍板恢复（验收 N23）。
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
│     ├─ 态 0（**水合态**，#1466）：首屏挂载 / projectId prop 变更 →
│     │   `GET /agent/books/plans?project_id=`（取 items[0]，后端 updated_at DESC）
│     │   · plan.status ∉ {ready, auto}（run 已启动）→ runId=plan.id（→ 态 3 运行面板）
│     │   · plan.status ∈ {ready, auto}（有计划无 run）→ 计划卡（→ 态 2）
│     │   · items 空 → 起点表单（→ 态 1）
│     │   · 跳过条件：projectId 为空 / 本会话已开始（sessionId 非空）→ 不发请求
│     │   ⚠️ 水合是**加载中间态**，不新增视觉状态（复现既有三态），见 §4 N31-N33
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
│             [重置运行 run-reset（非 running 态；带确认框）]
│             diff banner（run-diff-banner，可关闭）
│             计数：run-counter-chapters / calls / tokens
│             token 预警 run-token-warning
│             进度条 run-progress-bar（done/total）
│             进度列表 run-progress-list ★（段 2 任务列表，见 §3.2 Q5 / §3.3）
│               = 逐 outlineId 渲染 ExecutionTraceRow
│                 （五态徽标 pending/in_progress/done/
│                   failed/skipped，默认折叠可展开）
│             回归摘要面板（run-summary-toggle 开启时）
└──────────────────────────────────────────────────────────────┘
```

> 低保真排版示意简图 · 段 2 任务列表三方案（区块+标签，非精确像素；详见 §3）

```text
【方案 C · 单栏任务时间线（推荐）】
┌────────────────────────────────────────────────────────────────────┐
│ 顶栏：主题/语言 Select  窗口控制（壳层通用）                        │
├────────────────────────────────────────────────────────────────────┤
│ 项目名 book-project  [运行状态徽标 run-status]  [实时通道指示]      │
│ 计数 run-counter-chapters / run-counter-calls  [进度条]  [暂停]     │
│ 失败原因 run-progress-reason（failed / degraded / blocked 非空时）  │
│ ┌ 任务列表 run-task-list ★段 2 新增 ─────────────────────────────┐ │
│ │ [已完成]   第一章 · 章名                     3,120 字   [展开] │ │
│ │ [进行中]   第三章 · 章名   当前动作 write_chapter      进行中  │ │
│ │   └ 展开：write_chapter / audit_chapter / revise_chapter       │ │
│ │ [待人工介入] 第四章 · 章名  ← 审计阻断原因行（warn 色）        │ │
│ │ [待处理]   第五章 · 章名                              待写     │ │
│ └────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘

【方案 A · 侧栏任务列表】
┌───────────────────────────────┬────────────────────────────────────┐
│ 主区 · 运行面板               │ 任务列表（常驻侧栏 330px）★        │
│  运行状态徽标 / 计数 / 进度条 │ [已完成] 第一章 · 章名   3,120 字  │
│  干预 暂停 / 恢复             │ [进行中] 第三章  当前动作 write_…  │
│  密度 表演 / 仪表 / 无声      │ [待人工介入] 第四章（审计原因行）  │
│  回归摘要 / 重置运行          │ [失败] 第八章（provider 失败）     │
└───────────────────────────────┴────────────────────────────────────┘

【方案 B · 主区看板（三列）】
┌─ 待处理 5 ──────┬─ 进行中 1 ──────┬─ 已完成 2 ───────┐
│ [待人工介入] 四  │ [进行中] 第三章  │ [已完成] 第一章  │
│  审计阻断原因行  │  当前动作 …      │  3,120 字        │
│ [待处理] 第五章  │                  │ [已完成] 第二章  │
│ [失败] 第八章    │                  │                  │
└──────────────────┴──────────────────┴──────────────────┘
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
    - **重置运行 `run-reset`**（#1288）：`runStatus !== 'running'` 时渲染（与后端 reset 对 `running` 抛 422「运行已在进行中，不可重置」同族防呆）→ 点击打开共享 `ConfirmDialog`（`testidPrefix='run-reset'`，`danger`；`run-reset-dialog` / `run-reset-cancel` / `run-reset-ok`）→ 确认后 `useBookStore().resetRun()` 调 `POST /runs/{run_id}/reset`（**无请求体**），成功后运行态整体归零（`runId` / `runStatus` / `progress` / `counters` / `progressReason` / `waitingHitl` / `hitlPayload` / `interveneDiff` / `summary`）→ 页级回到「计划就绪 + 开始写作」分支（`writingPlan` **保留**，重跑闭环）；取消 / Esc 关闭且**不发**请求。⚠️ 确认文案须含「**重置 ≠ 删除正文**」（只清执行状态、不删正文/草稿；旧正文需自行处理，否则重跑仍被安全闸 #1265 判据拦截）
    - 密度三档（本地 state，**零额外请求**）：`run-density-performance`（章行内干预控件）/ `run-density-dashboard` / `run-density-silent`（**不渲染** `run-progress-list`）；`aria-pressed` 标记当前档
    - `run-summary-toggle` → 切换 `BookSummaryPanel`；`run-diff-banner`（`interveneDiff` 非空时）+ `run-diff-close`
    - 计数四行（`max_tokens` 与 `tokens_used` 均定义时 token 两行才渲染）：`run-counter-chapters`（`chapters_written / max_chapters`）、`run-counter-calls`（`agent_calls / max_agent_calls`）、`run-counter-tokens-run`（**#1431 本轮**：`max(0, tokens_used − tokenBaseline)`，`tokenBaseline` 为纯前端 store 字段，reset 成功时捕获的累计值；跨计划残留时归 0、不渲染负数）、`run-counter-tokens`（**#1431 累计账单**：`plan.limits.tokens_used / max_tokens`，**reset 不清零**）
    - `run-token-warning`：`counters.tokens_warning === true` 时渲染（**#1431**：告警由后端的**累计**账单判定，故文案（`book.run.tokenWarning`）必须点名「累计」（含重置前历史），否则用户见「我明明重置了、怎么还告警」的困惑——本轮用量单独计）
    - 进度条 `run-progress-bar`：`done / total`，宽度 = `min(100, round(done/total*100))%`（`total > 0` 才渲染）
    - 进度列表 `run-progress-list`（**#1333 段 2 起被 `run-task-list` 包裹**）：数据源 = `GET /runs/{id}/summary` 的 `steps`（章名 / 卷名 / 章内步骤），状态取实时 `progress[outline_id]`；`steps` 未就绪时回退 `Object.entries(progress)`（旧形态，零回归）。逐行渲染 `ExecutionTraceRow`（**六态**徽标 + 默认折叠 + 卷分组）。🔴 **漂移 D-1 已修复**：`needs_review` 补入 `STATUS_LABEL_KEYS` / `STATUS_BADGE_CLASSES`（`badge-needs_review` + warn 色），不再落回 `pending`「待处理」。
      - **卷分组（N24）**：按 `steps[].volume_name` 连续分组 → `task-volume-<i>` / `task-volume-header-<i>` / `task-volume-toggle-<i>`；**全 done 的卷默认折叠**（章行不渲染，可展开）。
      - **章内步骤（N15）**：`steps[].substeps` 非空（仅 agentic 轨）才渲染 `trace-substeps-toggle-<outlineId>`，展开显示 `trace-substep-<outlineId>-<op>` chips（`now` 档高亮）。
      - **章名（N14）**：`trace-row-name-<outlineId>`（`steps[].name`；后端 join outline，取不到回退 `outline_id`）。
    - `VolumeHITLDialog`（卷级 HITL 确认框）
  - ~~未启动（**组件内部**分支）：`book.run.noRun`（「暂无运行」）纯文本~~ → 🔴 **#1333 段 2 实测结论：该分支产品路径不可达，已删除**（连同 i18n key `book.run.noRun`）。`BookRunPanel` 唯一生产消费者是 `BookPlannerPanel.tsx:137`（以 `runId !== null` 门控）；`runId` 转 null 时消费者自身改走计划卡分支 → 面板被卸载。现 `BookRunPanel` 在 `runId === null` 时直接返回 `null`（验收 N26 / §3.5-6）。
    - ⚠️ **同名遮蔽（历史记录）**：页级 `runId` 与 `BookRunPanel` 读取的是**同一个 store 字段**，两处分支不同——页级为 `null` 时根本不渲染 `BookRunPanel`。这正是上条「不可达」的成因，段 2 据此删除该分支。
  - **水合（#1466）**：`components/BookPlannerPanel.tsx` 挂载 / `projectId` prop 变更时经 `useEffect` 调 `useBookStore().hydrate(projectId)`；store（`stores/book.ts`）经 `listBookPlans`（`api/books.ts`）请求 `GET /api/v1/agent/books/plans?project_id=&offset=0&limit=50`，取 `items[0]`（后端 `updated_at DESC` 最新在前）：
    - `plan.status ∉ {ready, auto}`（run 已启动：running / paused / waiting_hitl / completed / failed / degraded / blocked …）→ `sessionStatus='completed'` + `writingPlan=plan` + `runId=plan.id` + `runStatus=plan.status` + `progress` 同步（渲染**运行面板**；`counters` 由 `BookRunPanel` 既有 `GET /runs/{id}` 轮询补，水合不重复取）
    - `plan.status ∈ {ready, auto}`（planner 落库的两种未启动态，含 reset 后退回 ready）→ `sessionStatus='completed'` + `writingPlan=plan` + `runId=null`（渲染**计划卡**）
    - `items` 空 → `sessionStatus='idle'` + `writingPlan=null` + `runId=null`（渲染**起点表单**）
    - 边界：`projectId` 为 `null`/`''` **或** 本会话已开始（`sessionId !== null`）→ **不发请求**（不覆盖会话内 state）；请求失败仅记 `error`，三态不伪造
    - 🔴 语义前提：**run 载体 = `WritingPlan.id`**（`book_service.get_status`「run_id（= WritingPlan.id 字符串）」）→ plan 与 run 一一对应，「plans + 各自最近 run」退化为 plans 列表本身，**不新增第二套状态判断**（渲染仍由既有 `sessionStatus` + `runId` 驱动）
  - 布局说明：纵向单栏（`max-w-2xl`）；访谈态与「计划卡 / 运行面板」互斥（由 `sessionStatus` 切换），计划卡与运行面板互斥（由 `runId` 切换）；运行面板内区块按「状态 → 失败原因 → 工具栏 → diff → 计数 → 进度 → 列表 → 摘要」顺序堆叠

## 2. 动作样式（按钮 × 状态表）

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 去项目页（book-page-go-projects） | 无当前项目时显示 | `navigate('/projects')` | — | 跳转 | — | 仅空态分支渲染 |
| 开始访谈（book-planner-start） | 一句话为空 → disabled | 提交一句话，进入对话流 | 禁用 | 追加 user 气泡 + assistant 提问 | `book-planner-error` | ESC/取消语义未定义（见 §3.5 待拍板项 8） |
| 用模板（book-template-<qid>） | assistant 提问行内按钮 | 以模板文本填充回答 | — | 回答框可继续编辑 | — | 不直接提交（需再点发送） |
| 发送（book-send） | 回答框非空白（`answer.trim() !== ''`） | 追加 user 气泡 | — | 生成下一问或确认卡 | err 行 | 空白不可提交 |
| 确认卡确认（book-confirm-ok） | 确认卡渲染时 | 接受全部条目 | — | 进入下一阶段/启动 | err 行 | 逐项可先「编辑」再确认 |
| 确认卡编辑（book-confirm-edit-<key> → submit） | 条目行内 | 展开 `book-confirm-edit-input-<key>` → 提交该条 | 提交中 | 条目文案更新 | err 行 | 提交后收起输入 |
| 保存上限（book-limits-save） | 可点 | 提交 4 项上限（max_chapters / max_agent_calls / max_tokens / max_sessions） | `limits.saving` → disabled + 文案切 `set.saving` | 值回显 | `book-start-error` | 数值型输入（null → 空串显示），非法值由后端校验 |
| 开始运行（book-start-run） | 计划态可点 | 启动 book run → `runId` 置值 | 禁用 | 切到运行面板 | `book-start-error` | 同一计划重复启动语义未定义（见 §3.5 待拍板项 7） |
| 暂停（run-intervene-pause） | `running` 时渲染 | POST pause | — | 状态转 `paused` → 按钮换成 resume | err | 非 running 态不渲染该按钮 |
| 恢复（run-intervene-resume） | `paused` 时渲染 | POST resume | — | 状态转 `running` | err | 非 paused 态不渲染该按钮 |
| 密度三档（run-density-performance / dashboard / silent） | `aria-pressed` 标记当前档 | 切换本地密度 | — | 列表/控件密度即时变化 | — | `silent` 下**不渲染** `run-progress-list`；零额外请求 |
| 回归摘要（run-summary-toggle） | 未展开 | 切换 `BookSummaryPanel` | — | 面板显隐 | — | 纯本地 state |
| 重置运行（run-reset，#1288） | `runStatus !== 'running'` 时渲染 | 打开共享 `ConfirmDialog`（`run-reset-dialog`） | — | 确认 → `POST /runs/{run_id}/reset` **恰好一次** → 运行态归零、页级回「计划就绪 + 开始写作」（`writingPlan` 保留） | store `error`，面板保留（失败不假装成功） | 取消 / Esc → 关闭且**不发**请求；`running` 态**不渲染**该按钮（后端 422 防呆）；确认文案须含「重置 ≠ 删除正文」 |
| Token 用量（run-counter-tokens-run 本轮 / run-counter-tokens 累计，#1431） | `max_tokens` 与 `tokens_used` 均定义时渲染两行 | — | 随轮询刷新 | 本轮 = 累计 − `tokenBaseline`（`Math.max(0, …)`，跨计划残留归 0） | — | 累计 = `plan.limits.tokens_used`，**reset 不清零**；`tokens_warning` 按累计判定，`run-token-warning` 文案点名「累计」 |
| 原因展开（run-progress-reason-toggle） | 仅 `length > 200` 时渲染 | 展开/收起全文 | — | `line-clamp-3` 解除/恢复 | — | ≤200 字不渲染该按钮 |
| diff 关闭（run-diff-close） | `interveneDiff` 非空时 | `clearInterveneDiff()` | — | banner 消失 | — | 只清展示，不回滚数据 |
| 进度行展开（ExecutionTraceRow） | 默认折叠 | 展开该章摘要/干预控件 | — | 行内控件显示 | — | `done` 章干预控件禁用（422 防呆） |
| 任务列表（run-task-list，新增 · §3.2 Q5=C） | 有进度时渲染 | 展开/收起该章章内步骤（本地 state） | — | 步骤 chips 显示 | — | 静态/卷级轨无章内步骤 → 不渲染展开入口；`silent` 密度不渲染 |
| 卷折叠（task-volume-toggle-<i>，新增 · §3.5-5/N24） | 该卷全 `done` → 默认折叠；否则展开 | 展开/收起该卷章行（本地 state） | — | 卷体行显隐 | — | 无卷归属的 steps（`volume_name` 为空）不渲染卷头 / 不折叠（平铺） |
| 状态语义补齐（新增 · §3.3） | needs_review / blocked 出现时 | — | — | — | — | 纯呈现：`needs_review` → 「待人工介入」warn 色；run `blocked` → 「审计阻断 · 已停止」warn 色且失败原因块渲染（修 D-1/D-2/D-3） |
| 实时通道指示（run-live，新增 · §3.2 Q3=C） | 运行中渲染 | — | 连接中 → 已连接 | 推送到达即触发一次 run status 拉取 | 断开 → 静默降级为低频轮询 | 推送断连不得报错阻断页面；终态由轮询兜底确认 |

## 3. 自动写作任务列表 · 设计定义（#1333 段 2 · 0.16.0）

> **性质**：本节是段 2 的**设计交付**（设计轨产出，本轨不实现）。6 问结论见 §3.2，状态语义见 §3.3，
> 与已合入实现的漂移登记见 §3.4，待用户拍板项见 §3.5，与关联 issue 的对齐见 §3.6。
> 实现轨按本节 + §4 验收 N14-N21 落地。
> **原型**：`design/GUI/book/book.html` + `book-<scheme>-<state>.png`（legacy / a / b / c 四形态 × running / blocked）
> + `book-legend.png`（状态语义图例）。
> ⚠️ 原型内 `data-design-annotation="1"` 的「方案取舍说明条」是**评审注解**，**实现时不得做进产品 UI**。

**用户原话（2026-09-20，设计意图来源）**：

> 「我之前这个页面是想在**自动写作时让 agent 列出任务列表**，然后**用户可以实时看到当前进度**的，不过忘记实现了，先记上 issue，后续再完整定义并实现。」

### 3.1 现状事实基线（实测，非推断）

| # | 事实 | 证据 |
|---|---|---|
| F1 | **不存在「任务」实体**。`run-progress-list` 条目 = `Object.entries(progress)` 按 `outlineId` 派生（章级）；`get_summary.steps[]` 同为章级派生且**无章名** | `BookRunPanel.tsx:237`、`book_service.py:677-685` |
| F2 | 「agent 决定下一步做什么」只在 **agentic 轨**：LLM supervisor 输出 `{action, op, outline_id}`，`op ∈ {write_chapter, audit_chapter, revise_chapter, mark_done, finish_book}`，`route_history` 累积 op 序列 | `book_agentic_pipeline.py:122-128`、`:213-243`、`:294-299` |
| F3 | **静态轨 / 卷级轨无 agent 决策**：章按 `sort_order` 顺序派发，`progress` 由 service 直写 | `book_service.py:227-253` |
| F4 | 实时通道现状 = **1s 轮询** `GET /runs/{id}`，终态自动停（`status ∉ {running, pending}`） | `BookRunPanel.tsx:63-73` |
| F5 | 变更推送 `GET /api/v1/events/stream`（F23 §15）已存在、前端已封装；但 `DataChangeEvent.domain` 枚举**不含** `writing_plan` / book run → **run 状态跃迁（paused / waiting_hitl / blocked）不产生事件** | `domain/models/data_change_event.py:27-30`、`api/routers/events.py` |
| F6 | book run 写正文经 `chapter_service.update_chapter` → **会**发 `chapter`/`update` 事件（可作「有变化」的失效信号） | `infrastructure/agent/_audit_bridge.py:271`、`domain/services/chapter_service.py:275` |
| F7 | 后端已有 run 级 `blocked` 与章级 `needs_review`（#1267），**前端两者零映射** | `book_run_mixin.py:199-200`、`book_agentic_pipeline.py:673`；renderer grep 命中 0 |
| F8 | 对外面完备：CLI `inkflow book run/status/confirm/intervene/summary` + `book plan *`；MCP `manage_book`（10 action）；API 8 端点 | `cli/commands/book_cmd.py`、`mcp/tools/book_tools.py`、`api/routers/books.py` |

### 3.2 六个设计问题的结论

> **6 问结论已于 2026-10-02 全数拍板**（用户「全按照推荐」）→ 下表「推荐」列即**已拍板结论**，归档见 §3.5。

| # | 设计问题 | 候选 | **推荐** | 取舍（放弃了什么） |
|---|---|---|---|---|
| Q1 | agent 如何产出任务清单 | A 新增 LLM 预产出（结构化输出 / 工具调用 todo 协议）· B 从既有 `progress` 派生 · C 复用 agentic `route_history` 作动作流水 · **D = B + C 分轨** | **D**：静态/卷级轨 = B；agentic 轨 = B 为主 + C 作「当前动作」指示 | 取 D 得零新增 LLM 调用、零 schema 解析失败分支，且任务 = 真实执行面。**弃 A**：与 supervisor 决策职责重叠（两套「下一步」来源会打架）、新增 token 成本；A 另开 issue 挂后续里程碑（见 §3.5-2） |
| Q2 | 任务粒度 | A 章级 · B 章内步骤级 · C **混合** | **C**：章级为主线 + 展开看章内步骤 | 章级 = 用户视角（「第 N 章写完了吗」）；子步骤仅 agentic 轨可得（F2），静态/卷级轨无可展开 → 隐藏入口。既有 `ExecutionTraceRow` 的「行 + 展开」正是 C 的容器，零新数据面 |
| Q3 | 实时通道 | A 沿用 1s 轮询 · B 改走 F23 SSE · C **SSE 为主 + 轮询兜底** | **C**（配套 Q4-D2 补 `writing_plan` 发布点） | SSE 复用 ADR-053「事件 = 失效信号 → 拉取」语义；但 domain 枚举无 book run（F5）→ 不补发布点则暂停 / HITL / 阻断无信号。**弃纯 B**：单点依赖推送、断连即瞎；**弃纯 A**：1s 轮询在长任务上持续空转 |
| Q4 | 与既有数据面关系 | ① 零新增字段（纯派生）· ② 新增 `tasks` JSON 列 · ③ **升级 `get_summary.steps` 为任务视图契约（零 DDL）** + D2 发布 `writing_plan` 变更事件 | **③ + D2** | 取 ③：`steps` 已是「章级派生」的正式契约，补 `name`（后端 join outline 取章名，现前端只能显示 `outlineId`）+ `substeps` 即可承载，**零 DDL**。**弃 ②**：任务状态是 `progress` 的重新表达，落独立列 = 双写来源必漂移。**弃 ①**：章名缺失使列表不可读（F1） |
| Q5 | GUI 呈现 | A 侧栏任务列表 · B 主区看板三列 · C **单栏任务时间线** | **C**（A 为可选增强；B 不推荐） | 取 C：改动最小、与既有折叠/密度/干预控件一脉相承，数百章可滚动分页。**A** 收益（常驻可见）在本页不成立（整页即看板）且需单栏改双栏；**B** 在长篇（数百章）下三列各自滚动 → 总览价值消失、单卡宽压到约 1/3（实测见 `book-b-*.png`） |
| Q6 | 是否影响 MCP / CLI 面 | A 不暴露 · B **复用既有 `status` / `summary`**（仅 `steps` 补字段） · C 新增 `book tasks` 命令 + MCP action | **B** | 任务清单是既有 `progress` / `steps` 的**呈现层重表达**，不新增语义 → CLI `inkflow book status` 与 MCP `manage_book action=status/summary` 天然覆盖，零新增对外契约面。**弃 C**：同一「任务」概念在 GUI/CLI/MCP/API 四层各造一套 = 漂移源 |

### 3.3 状态语义（段 2 补齐 #1267 缺档）

**章级任务态（`progress[outline_id]`，6 态）**

| 值 | 文案（i18n key） | 语义色语义类 | 来源 |
|---|---|---|---|
| `pending` | 待处理（`book.trace.pending`） | 中性 `badge-pending` | `progress` 缺该键 / 显式 pending |
| `in_progress` | 进行中（`book.trace.in_progress`） | accent `badge-in_progress` | service 置 `in_progress` |
| `done` | 已完成（`book.trace.done`） | ok `badge-done` | 委托成功、正文落库 |
| `failed` | 失败（`book.trace.failed`） | err `badge-failed` | 委托异常 |
| `skipped` | 已跳过（`book.trace.skipped`） | 中性虚线 `badge-skipped` | 硬护栏超限跳过 |
| `needs_review` | **待人工介入（新增 `book.trace.needs_review`）** | **warn** `badge-needs_review` | **#1267** `_finalize_audit_block` 审计阻断 |

**run 级态（`GET /runs/{id}` 的 `status`）**：`ready` / `running` / `paused` / `waiting_hitl` / `completed` / `failed` / `degraded` / **`blocked`（#1267 新增档位）**。
段 2 需给 `blocked` 独立语义：徽标文案「**审计阻断 · 已停止**」（新增 `book.run.status.blocked`）+ warn 色，
且失败原因块渲染门控由 `failed | degraded` 扩为 `failed | degraded | blocked`（修 D-3）。

**章内子步骤（仅 agentic 轨，Q2=C）**：`write_chapter` / `audit_chapter` / `revise_chapter` / `mark_done`
（`_OPERATION_POOL`，F2），状态由 `route_history` + `audit_results` 派生为 `done` / `now` 两档。

### 3.4 漂移登记（本轨只上报，不改实现）

| # | 漂移 | 证据 | 处置建议（实现轨） |
|---|---|---|---|
| D-1 | 章状态 `needs_review` 前端无映射 → `STATUS_LABEL_KEYS` / `STATUS_BADGE_CLASSES` 兜底 `pending`「待处理」中性灰 → **被审计阻断的章显示成「还没写」**，语义相反 | `ExecutionTraceRow.tsx:20-35`、`book_agentic_pipeline.py:673` | ✅ **已修复（#1333 段 2 实现轨）**：补 6 态映射 + 新增 `book.trace.needs_review`（「待人工介入」）+ `badge-needs_review`（warn 色） |
| D-2 | run 状态 `blocked` 无档位 → `RUN_BADGE_CLASSES` 兜底中性灰，且徽标直接渲染英文枚举原文（`{runStatus ?? '–'}`） | `BookRunPanel.tsx:26-30`、`:90` | ✅ **已修复**：补 `run-badge-blocked`（warn 色）+ `book.run.status.blocked`（「审计阻断 · 已停止」）；completed/failed/degraded **保持原文透传**（既有单测契约「原文透传」，见 §4 口径说明） |
| D-3 | `progress_reason`（审计阻断原因）渲染门控是 `failed \| degraded` → **blocked 时原因对用户不可见**，与 #1267「审计结果必须有后果、返回给用户」相悖 | `BookRunPanel.tsx:55-58`；**后端同族门控** `book_service.get_status:413` / `get_summary:702` 亦为 `{"failed", "degraded"}` | ✅ **已修复（前端 + 后端同批）**：两处门控同时扩为 `failed \| degraded \| blocked`（只改前端则 `progress_reason` 恒为 `None`，缺陷仍在，属实现轨实测补充的同一缺陷另一半） |
| D-4 | 段 1 页规格 §1 的「五态徽标 / run 四档」表述落后于 #1267 的六态 / 多档 | 本节 vs F7 | **本轨已就地更正**（§1 进度列表条 + §3.3） |

### 3.5 拍板结果（2026-10-02 · 用户「全按照推荐」）

| # | 决策点 | **结论（已拍板）** |
|---|---|---|
| 1 | 任务列表 GUI 方案（§3.2 Q5） | **C · 单栏任务时间线**（原型 `book-c-*.png` 即实现基准；A/B 保留作对照，不实现） |
| 2 | 「真实 LLM 预产出任务清单」（§3.2 Q1 的 A 方案） | **另开 issue **#1439** 挂 0.17.0** —— 不塞本期（与 supervisor 决策职责重叠，收益/成本比低） |
| 3 | 实时通道落地范围（§3.2 Q3 / Q4-D2） | **同批新增 `writing_plan` 域发布点**（run 状态跃迁发 `publish_change`）→ 须同步 F23 spec §15.2.1 枚举，属 MODIFY 既有模块；验收 N22 |
| 4 | 导航入口（§1 第 7 项） | **新增 `AppNav`「成书」项 → `/book`**（i18n `nav.book` 已存在）；验收 N23 |
| 5 | 长篇（数百章）列表规模策略 | **按卷分组 + 已完成卷默认折叠**（零新依赖）；验收 N24 |
| 6 | `book.run.noRun` 分支可达性（§1 同名遮蔽条） | **实测结论（实现轨）：产品路径不可达** —— `BookRunPanel` 唯一生产消费者是 `BookPlannerPanel.tsx:137`，以 `runId !== null` 门控渲染；`runId` 转 null 时该消费者自身改走计划卡分支 → 面板被卸载，`runId === null` 分支永不渲染。**处置：删除该分支 + `book.run.noRun` i18n key**（验收 N26） |
| 7 | 同一计划重复启动 `book-start-run` 语义 | **拒绝 409**（前端只透错，不静默新建 run）；验收 N25 |
| 8 | 访谈阶段 ESC / 取消语义 | **不加**（超出本页任务看板主题，另议） |

> 拍板后的增量验收 N22-N26 见 §4。被改期项（#2）已转独立 issue 挂 0.17.0；被否决项（§3.2 Q1-A / Q5-A / Q5-B / Q6-C）
> 不实现，原型与本节保留作决策留痕。

### 3.6 与关联 issue 的对齐说明

| issue | 状态 | 对任务看板的影响 | 段 2 处置 |
|---|---|---|---|
| **#1267** 审计阻断 | CLOSED（已实现） | 新增 run `blocked` + 章 `needs_review`，并把阻断原因写入 `progress_reason` | **必须对齐**：补 D-1/D-2/D-3 三处呈现 —— 任务看板的「状态语义完整性」以此为前提 |
| **#1282 / #1288** reset 出口 | CLOSED（已实现） | `reset` 清 `progress` / `execution_refs`、plan 回 `ready`；GUI `run-reset` 非 running 态渲染 | 任务列表随 reset 归零（`runId = null` → 回计划卡分支）；**不改语义**，验收沿用 N13 |
| **#1430** force 覆盖 + A2 备份 | CLOSED（已实现） | `chapters.previous_content` 落旧稿；`force` 须与 `confirm_overwrite` 成对 | 可选增量：被覆盖过的章在任务行加「已有上一稿」徽标 + 恢复入口 → 已建 **#1440**（#1430 已注明「GUI 入口可另开」），段 2 不纳入。**#1440 已交付（本仓同批）**：徽标 + 恢复入口落在**写作页章节树**（writing.md §15）；本页落「N 章已备份，可恢复」计数提示（§5）—— **任务行级徽标因 `steps[]` 无 `chapter_id` 不纳入**（见 §5.1） |
| **#1333 段 1** | 已完成 | 本页规格 + 原型目录已非孤儿 | 本轨在段 1 基础上补设计定义；L4 自指指针**保留不动** |

## 4. 验收

- N1：空态（无当前项目）→ `book-page-empty` + 「去项目页」跳 `/projects`
- N2：有项目 → `book-project` 显示项目名 + 访谈面板渲染
- N3：访谈流 → 一句话必填启用开始；user 气泡 / assistant 提问 / 用模板 / 确认卡（确认 + 逐项编辑）
- N4：计划态（`sessionStatus === 'completed'` 且 `runId === null`）→ 计划标题 + 状态二档（`auto` / `ready`）+ 4 项上限可保存（saving 禁用）+ 开始运行（`runId` 置值后切运行面板）
- N5：运行面板状态徽标四档着色（completed / failed / degraded / 其它中性）
- N6：失败原因块仅在 `failed | degraded` 且非空时渲染 + >200 字截断与展开/收起
- N7：干预按钮互斥（`running` → 暂停 / `paused` → 恢复）
- N8：密度三档切换为本地态零请求；`silent` 下不渲染 `run-progress-list`
- N9：计数四行（含 #1431 本轮 / 累计两行）+ token 预警（`tokens_warning`）+ 进度条（`total > 0`）按条件渲染
- N10：`run-progress-list` 逐 `outlineId` 渲染 `ExecutionTraceRow`，五态徽标 + 默认折叠
- N11（**#1333 段 2 改写**）：`runId === null` → `BookRunPanel` 返回 `null`（不渲染面板、不发请求）。原「`book.run.noRun`「暂无运行」纯文本」分支经实测**产品路径不可达**，已删除（连同 i18n key），见 N26
- N12：轮询 1s 间隔、终态自动停（`status` 既非 `running` 也非 `pending`）
- N13（#1288）：`runStatus !== 'running'` → `run-reset` 可点；点击弹 `run-reset-dialog`，文案含「重置 ≠ 删除正文」；取消 → 关闭且不发请求；确认 → `POST /runs/{run_id}/reset` 恰好一次 + 运行面板回空态（`runId` 清空，页级回「计划就绪」）；失败（422）→ 面板保留 + `error` 记录

### 段 2 验收（#1333 · 设计定义见 §3）

> **口径说明**：N16 / N17 扩展 N5（run 徽标「四档」）、N6（原因块门控）、N10（章徽标「五态」）的状态口径
> —— 段 2 落地后以 N16 / N17 为准（四档 → 含 `blocked`；五态 → 六态含 `needs_review`）。
>
> **N16 文案口径（实现轨）**：`run-status` 徽标**仅 `blocked`** 收编中文文案（`book.run.status.blocked`「审计阻断 · 已停止」）；
> `completed` / `failed` / `degraded` 保持英文枚举**原文透传** —— 既有单测契约（`toHaveTextContent('completed')` 等）如此钉死。
>
> **N18 口径（实现轨）**：「推送为主 + 轮询兜底」的落地形态 = **保留既有 1s 轮询**（N12 契约不变，兼作兜底与终态确认）
> + 新增 `writing_plan` SSE 订阅（订阅就绪 `event=null` / 推送帧到达，各触发**一次** `GET /runs/{id}`）；
> `run-live` 的 `data-live` 由 `connecting` → `connected`（订阅就绪即置位，推送断连静默、不报错不阻断）。
> **未**把轮询降为更长间隔：N12「1s 间隔 + 终态自动停」是已合入的单测契约，降频会使其失真（刻意保守，非遗漏）。

- N14（§3.2 Q4=③）：任务列表 `run-task-list` 逐 `progress` 条目渲染章级行，**每行含章名**（`get_summary.steps[].name` 由后端 join outline 补齐，不得只显示 `outlineId`）
- N15（§3.2 Q1/Q2）：章内步骤展开仅当该轨提供子步骤时渲染（agentic 轨 = `write_chapter` / `audit_chapter` / `revise_chapter` / `mark_done` 派生；静态轨 / 卷级轨**不渲染展开入口**）
- N16（§3.3 · 修 D-2/D-3）：run `blocked` → 徽标渲染「审计阻断 · 已停止」+ warn 语义类（**不得**落回中性灰或英文原文）；且此时 `run-progress-reason` **渲染**（门控含 `blocked`）
- N17（§3.3 · 修 D-1）：章 `needs_review` → 徽标渲染「待人工介入」+ warn 语义类（**不得**落回 `book.trace.pending`「待处理」）
- N18（§3.2 Q3=C）：实时通道 = 推送为主 + 轮询兜底 —— 推送帧到达触发**一次** `GET /runs/{id}`；推送断连静默降级为低频轮询，**不报错、不阻断页面**；终态仍由轮询确认
- N19：`silent` 密度下**不渲染**任务列表（沿用 N8 语义，任务列表属观察流）
- N20：reset 后任务列表清空且页级回「计划就绪」（沿用 N13，追加断言 `progress` 归零）
- N21：原型内 `data-design-annotation="1"` 的方案取舍说明条**不得**出现在产品 UI（评审注解，见 §3 头部声明）
- N22（§3.5-3 · 拍板）：后端在 book run 状态跃迁写路径末尾发布 `publish_change("writing_plan", "update", plan.id, plan.project_id)`；`GET /api/v1/events/stream?project_id=` 可收到该域事件；F23 spec §15.2.1 的 `domain` 枚举同步登记 `writing_plan`
- N23（§3.5-4 · 拍板）：`AppNav` 新增「成书」项（`nav.book`）→ 跳 `/book`；本页不再是只能靠路由直达的孤儿
- N24（§3.5-5 · 拍板）：任务列表按卷分组渲染，**已完成卷默认折叠**（可展开）；章数 ≥ 100 时不出现明显渲染卡顿
- N25（§3.5-7 · 拍板）：同一计划重复启动 → 后端 409，前端只透错（**不静默新建 run**）
- N26（§3.5-6）：`book.run.noRun` 分支可达性给出实测结论并回写 §1；不可达则删除该分支与对应 i18n key

### #1431 验收（本轮 vs 累计 Token 用量）

> **编号说明**：本节的实现轨验收项接续既有全局编号（段 1 = N1–N13、段 2 = N14–N26、§5 = N27–N29），故自 **N30** 起编，避免与段 2 已占用的 N14 冲突。

- N30：运行面板把 token 用量拆成**两个独立 testid** 并存显示——`run-counter-tokens-run`（**本轮** = `Math.max(0, counters.tokens_used − tokenBaseline)`，`tokenBaseline` 为 reset 成功时捕获的累计值）与 `run-counter-tokens`（**累计**账单 = `plan.limits.tokens_used`，reset **不清零**）；两值来源不同、可辨（本轮行不得混入累计值）；`tokens_warning` 由**累计**档判定，故 `max_tokens` 告警（`run-token-warning`）文案必须点名「累计」

### #1466 验收（成书页水合 —— 让已有 plan/run 可见）

> **编号说明**：接续既有全局编号（段 1 = N1–N13、段 2 = N14–N26、§5 = N27–N29、#1431 = N30），自 **N31** 起编。
> **缺陷来源**：0.16.0-rc1 实测——CLI 已建书并跑完 book run（10 章落库），进「成书」页仍只有空白起点表单；
> 根因两层：① 后端无「列项目 plan / run」端点（`GET /agent/books/runs?project_id=` → **405**）；
> ② `stores/book.ts` 从不水合（纯内存态）。

- N31（后端）：`GET /api/v1/agent/books/plans?project_id=<uuid>` → 200 + `{items, total, offset, limit}`（**不再是 405**，信封同 `GET /planner` 列表）；`items` 元素为 `WritingPlan`（自带 `status`/`progress`/`limits` = run 状态摘要），按 `updated_at DESC` 最新在前；空项目 → 200 + `items=[]`（**非 404**）；非法 `project_id` → 422；只读无副作用（GET 语义）
- N32（前端）：成书页首屏挂载 / `projectId` prop 变更 → 调 `hydrate(projectId)`，据水合结果落三态——有已启动 run（`plan.status ∉ {ready, auto}`）→ **运行面板**（`runId` 非空）；有计划无 run（`ready`/`auto`）→ **计划卡**；都无 → **起点表单**
- N33（边界 + 反例守护）：`projectId` 为 `null`/`''` **或** 本会话已开始（`sessionId !== null`）→ **不发请求**；**当前会话内新建 plan/run 的原有三态路径不受影响**（`sessionStatus`/`runId` 驱动不变，未新增第二套状态判断）

## 5. #1440 force 覆盖备份提示 + 「已有上一稿」GUI 读口

> 来源：§3.6 的转出项（「被覆盖过的章在任务行加『已有上一稿』徽标 + 恢复入口」）→ **本单（#1440）落地**。
> 后端已具备（#1430 A2 / PR #1433）：`chapters.previous_content` + `POST /chapters/{id}/restore-previous`
> （经 `update_chapter` 覆盖写 ⇒ `content` ⇄ `previous_content` **互换**，可再切回）。
> 本节记录 **GUI 侧落地形态 + 范围裁量**；写作页章节树侧（徽标 + 恢复入口）见 `specs/f19-gui/writing.md` §15。

### 5.1 画面/布局补充

- 运行面板新增**备份提示** `run-overwrite-notice`：`runOverwrite !== null && chapters_to_backup > 0` 时渲染
  （文案 `book.run.overwrite.notice` = 「{count} 章已备份，可恢复」/「{count} chapter(s) backed up, restorable」），
  位置在 `run-token-warning` 之后、进度条之前。
- 数据来源 = `POST /api/v1/agent/books/runs` 响应的**可选**字段
  `overwrite = { forced, backup_target, chapters_to_backup }`（仅 `force=true` 覆盖成功时后端追加）→ `startRun` 收录进
  store 的 `runOverwrite`；`resetRun` / `reset` 归零。
- 🔴 **现状边界（如实记录）**：GUI 的 `startBookRun` **不传 `force` / `confirm_overwrite`**（本单未开放 force 开关，
  破坏性覆盖不在授权范围）→ 该提示在**真实 GUI 交互中暂不可达**，属「响应带 `overwrite` 即展示」的忠实实现，
  为后续开放 force 入口预留。**CLI / MCP 面本单不做**（`inkflow book run --force` 与 `manage_book run` 的
  `force` / `confirm_overwrite` 已由 #1430 提供）。
- ⚠️ **任务行级「已被覆盖过」徽标（§3.6 原设想的落点之一）经评估不纳入**：
  任务行数据源 `GET /runs/{id}/summary` 的 `steps[]` 字段为
  `{index, outline_id, name, status, execution_id, volume_name, substeps}` —— **不含 `chapter_id`**
  （`backend/src/inkflow/domain/services/book_outline_mixin.py::_build_task_steps`）→ 前端无法把任务行**可靠**映射到
  「哪一章的 `previous_content`」；按 `name` ↔ 章标题匹配属脆弱耦合，不取。
  **故行级徽标落点移至写作页章节树**（`specs/f19-gui/writing.md` §15），本页以「N 章已备份」计数提示作总览。
  如需任务行级徽标，须后端在 `steps[]` 补 `chapter_id`（另开单；本单**后端零改动**）。

原型基准（`design/GUI/book/`）：
- `book-run-overwrite-notice.png` —— `overwrite-notice` 态：提示条位于计数区与进度条之间；
- 生成脚本 `design/GUI/_tools/shot-book-token-scope-1431.cjs`（900×792，与 `book-run-*.png` 家族同视口）；
  断言脚本 `design/GUI/_tools/shot-w8-restore-previous-1440.cjs`
  （断言：`overwrite-notice` 态可见 + 文案正确 + 其余 6 态**不渲染**；全绿）。
- ⚠️ 本轨在 `book-run.html` 的 `caption` 追加了 #1440 说明行 → 该页**既有 6 张状态图全量重出**（同 PR diff）。

### 5.2 动作样式补充

| 控件 | 初始态 | 点击后 | 进行中 | 成功 | 失败 | 边界 |
|------|--------|--------|--------|------|------|------|
| 备份提示（`run-overwrite-notice`） | `runOverwrite` 非 `null` 且 `chapters_to_backup > 0` 时渲染 | 非交互（纯提示） | — | — | — | 计数为 0 / 响应无 `overwrite` 键 → **不渲染**（反例守护） |

### 5.3 验收补充

- N27：`POST /runs` 响应带 `overwrite.chapters_to_backup = 3` → 面板渲染 `run-overwrite-notice` 且文案含「3」与「可恢复」；
  且 `startRun` 把该字段收录进 store 的 `runOverwrite`。
- N28：`chapters_to_backup = 0` **或** 响应无 `overwrite` 键（非 force）→ `runOverwrite` 保持 `null`、提示**不渲染**
  （反例守护）。
- N29：`resetRun` / `reset` → `runOverwrite` 归零（重跑闭环不留旧提示）。
