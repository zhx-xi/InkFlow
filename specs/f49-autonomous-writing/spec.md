# F49: 自主全自动写作（autonomous-writing）功能规格

**Spec 版本**: 1.0（初稿，2026-08-23）
**日期**: 2026-08-23
**依据**: Issue #551（Agent 全自动写作，milestone 0.12.0）+ 用户拍板 2026-08-21（#551 归 0.12.0，拆批：后端编排核心 → 前端面板 #597 → 验证）+ 既有源码核查（F44 book run / F29 supervisor / F27 writer / deepagents harness 0.7.5）+ 参考规格 `specs/f44-long-task-orchestrator/spec.md`（书级运行骨架 + HITL + checkpoint）+ `specs/f29-supervisor/spec.md`（supervisor 动态路由 + 护栏 + 回退 + HITL）
**所属阶段**: 0.12.0（AI 全自动写作）
**关联 Issues**: [#551](https://github.com/zhx-xi/InkFlow/issues/551)（本模块，Agent 全自动写作）· [#597](https://github.com/zhx-xi/InkFlow/issues/597)（Part of #551，前端面板：Chat 接入 deepagents 系统级 Agent + 工具流式 + 删书级编排入口，S3 实现轨）· 前置：✅ F44 长任务编排器 · ✅ F29 Supervisor · ✅ F27 writer-agent · ✅ F26 deepagents 集成层
**依赖**: ✅ F44（书级运行骨架）· ✅ F29（supervisor 动态路由）· ✅ F27 agentic writer（deepagents harness）· ✅ F26（deepagents 工具链 harness.py build_deep_agent）· ✅ langgraph-checkpoint-sqlite（AsyncSqliteSaver，F44 阶段 4 已交付）· ⏳ 无新 Python 依赖
**参考 ADR**: adr/ADR-035.md（编排引擎=Deep Agents harness 0.7.5）· ADR-006v2（Agent 编排 LangGraph StateGraph）· ADR-015（LangChain 隔离）· ADR-019（编号口径）· ADR-027（覆盖率门禁）
**状态**: ✍️ 起草中（本会话 Specify）

> **模块类型声明**: 本模块为「**自主编排型**」变体（第 21 变体，接续 F29 自主编排型/F44 长任务编排型）——在既有 F44 书级运行骨架之上新增 **book-level agent 自主编排层**：书级 supervisor agent（LLM 决策 + Command(goto) 动态路由，F29 模式）替代**链式**（architect→writer→auditor→reviser 固定拓扑）与**确定性扇出**（F44 BookVolumePipeline Send fan-out 每章一次写），agent 自主决定「分章 → 写作 → 审校 → 修订 → 完成」序列；**章节级**自主循环（单章 agent 自主决定 write/audit/revise 直至满意）；配套 HITL 确认点（降级）+ 中断恢复 checkpoint（跨重启 resume）。**链式拓扑保留**（F42 static / F29 supervisor / F44 volume 既有模式零改动，仅新增 agentic 模式，向后兼容）。

> **范围声明（本会话 = 后端编排核心）**: 本 v1.0 spec 只定义**后端编排核心**（book-level 自主编排引擎 + 章节级自主循环 + HITL/恢复），对应 #551 后端批。**前端面板**（Chat 接入系统级 Agent + 工具流式显示 + 删书级编排入口）拆给 **#597（Part of #551）**，本 spec §10 仅标注边界，不定义前端契约。真正 `Closes #551` 的是 #597 完成后；本模块 PR 用 `Part of #551`，**禁 `Closes #551`**。

---

## 1. 概述

### 1.1 现状缺口（2026-08-23 源码实证）

| # | 缺口 | 实证 | 归属 |
|---|------|------|------|
| ① | **书级编排确定性**：F44 `write_book` 顺序派发 / `write_book_volume` Send fan-out，每章**一次写**，无 agent 自主分章/审校/修订决策 | `book_service.py` `write_book`/`write_book_volume` + `book_pipeline.py` `_write_chapter`（writer_factory → agent.invoke → draft_service.create 固定单写） | #551 |
| ② | **章节级无自主循环**：单章是「一次 write」，无 write/audit/revise 工具调用序列直至满意的 agent 决策 | `book_pipeline.py` `_write_chapter`（单写无循环；F27 save_draft 是工具级，非 agent 自主编排） | #551 |
| ③ | **写作主路径仍链式**：`agent_service._merge_role_configs` + `agent_order` 静态链（F42 #269）是默认；F29 supervisor 动态路由已存在但书级写作主路径未打通 | `agent_service.py` `execute()` mode 分派（static 默认 / supervisor 需显式） | #551 |
| ④ | **无 book-level supervisor**：F29 supervisor 是单次管线运行（pipeline run）的动态路由，无「书 → 章 → write/audit/revise」跨级状态 | `supervisor_pipeline.py` `SupervisorPipeline`（单 run，roles=architect/writer/auditor/reviser，无书痕迹） | #551 |

### 1.2 目标（用户一句话 → agent 自主完成全流程）

**agent 全自动写作**：用户输入一句话（或已有 WritingPlan）→ agent 自主完成「书级分章 → 逐章写作 → 审校 → 修订 → 完成」，替代链式固定拓扑。agent 自主决策（中断/跳过/并行/重试/审校修订序列），而非固定 architect→writer→auditor→reviser 顺序。

### 1.3 与样板差异

非 F9 实体 CRUD、非 F44 长任务编排型（计划树驱动的确定性推进）、非 F42 配置驱动静态链——本模块是**书级 agent 自主编排**：在 F44 书级运行骨架（WritingPlan + 进度状态机 + HITL + checkpoint）之上，把「怎么写/何时写/审校否/修订否/何时算完成」的决策从确定性代码交给 **book-level supervisor agent**（deepagents harness / F29 Command(goto) 模式）。编排图仍是 LangGraph StateGraph（ADR-006v2），checkpointer 复用 F44 AsyncSqliteSaver + thread_id 语义。

### 1.4 边界声明

- **不含** 前端面板（#597：Chat 接入 + 工具流式 + 删书级编排入口）——本 spec 只做后端编排核心
- **不含** 既有链路改造：F42 static / F29 supervisor / F44 volume 三种既有模式**零改动**，本模块新增 `mode="agentic"`（默认 static 向后兼容）
- **不含** 章内断点（同一章写作中断点恢复）——checkpoint 粒度 = 章边界（F44 阶段 4 语义）
- **不含** 并行章执行（Send fan-out 属确定性卷编排；本模块 agentic 自主编排默认**串行推进**，并行归远期 #270 DAG）
- **不含** 跨章一致性/冲突解决引擎、token 精确核算、双面板精致化
- **不含** MCP 表现层

---

## 2. 数据模型

### 2.1 复用 F44 WritingPlan / BookLimits（零新实体表）

本模块**不新增实体表**。书级运行载体 = F44 `WritingPlan`（§2.1 既有：status/progress/execution_refs/limits/thread_id/character_ids/root_outline_id），运行状态复用 F44 状态机（`drafting → ready → running → waiting_hitl ⇄ running → completed/failed/aborted`）。进度权威 = `WritingPlan.progress`（F44 §6 R2）。上限复用 `BookLimits` + `validate_at_least_one_hard_limit`（F44 §2.4「至少一道有限护栏」）。

### 2.2 AgenticRunConfig（新 DTO，`domain/models/agent_pipeline.py` 或 `domain/models/agent_book.py` MODIFY/CREATE）

```python
class AgenticBookConfig(BaseModel):
    """agentic 模式书级运行配置（mode="agentic" 时生效）。"""

    # 护栏（复用 F29 supervisor 语义 + F44 上限）
    max_steps: int = Field(default=100, ge=1, le=200, description="book-level supervisor 路由步数上限（振荡护栏）")
    max_consecutive: int = Field(default=4, ge=1, le=10, description="同操作连续调度上限（振荡护栏）")
    hitl_points: list[str] = Field(
        default_factory=list,
        description="HITL 确认点白名单：book_start / volume_boundary / chapter_done / finish；空=无 HITL（全自动）",
    )
    fallback_on_error: bool = Field(default=True, description="异常/超限回退确定性链（continue writing remaining chapters）")
    supervisor_prompt: str | None = Field(default=None, description="book supervisor 决策 system prompt 覆盖（默认模板）")
    max_chapter_cycles: int = Field(default=5, ge=1, le=20, description="章节级 write/audit/revise 循环上限（防无限修订）")
    audit_required: bool = Field(default=True, description="每章写后必须至少一次审校（规格化自主循环下限）；False=agent 可跳审")
```

**读取优先级**：请求显式 > 项目级 `ProjectConfig.extra`（键 `book_max_*`，F44 §2.4）> 默认常量。

---

## 3. API 契约

**无新增 REST 端点**。复用 F44 书级运行端点 `POST /api/v1/agent/books/runs`，`BookRunRequest.mode` 字段扩展支持 `"agentic"`（既有 `static`/`volume` 保留）：

```jsonc
// POST /api/v1/agent/books/runs
{ "writing_plan_id": "uuid", "mode": "agentic",
  "config": { "max_steps": 100, "hitl_points": ["chapter_done"] } }
// 202 { "run_id": "uuid", "status": "running" }
```

- `mode="agentic"` → `BookService.prepare_run(mode="agentic")` 预校验 → 后台 `_run_book` → `write_book_agentic()`（§5.4）
- **状态查询**：`GET /runs/{run_id}` 复用（进度树 + counters + waiting_hitl/hitl_payload）
- **HITL 确认**：`POST /runs/{run_id}/confirm` 复用（F44 confirm_run，approved/decision）
- **干预**：`POST /runs/{run_id}/intervene` 复用（pause/resume/redirect/edit，F44 §3.2）
- **异常映射**：复用 F44（404 运行不存在 / 409 内容已写安全阀 / 422 上限全无 / 422 非 waiting_hitl confirm）

> **向后兼容**：`BookRunRequest.mode` 默认 `"static"`（既有调用零改动）；新增字段 `config: AgenticBookConfig | None = None`（仅 mode="agentic" 生效，None → 默认 config）。

---

## 4. CLI 命令签名

**复用既有** `inkflow book run`（F44 §4），扩展 `--mode agentic`：

```bash
inkflow book run <plan_id> --mode agentic --limits max_chapters=5,max_tokens=200000
inkflow book status <run_id> --density performance|dashboard|silent   # 复用（agent 决策轨迹）
inkflow book confirm <run_id> --approved --decision "继续下一章"       # 复用（HITL 确认）
inkflow book intervene <run_id> --action pause|resume|redirect|edit    # 复用
```

`inkflow book plan auto`（F44）仍为「全部你决定」兜底入口，本模块 agentic 是其上游（plan → agentic 自主写）。

---

## 5. 关键差异节：book-level agent 自主编排（替代链式）

按「编排核心 → 章节自主循环 → HITL/恢复 → 装配」四段组织。每段为独立 GREEN 批。

### 5.1 编排引擎选型

**方案 A（选定）：`BookAgenticPipeline` = 自研 LangGraph StateGraph（F29 supervisor 模式），node = book-level 操作**。

```
START → bootstrap(注入 llm_client/UntrackedValue, 镜像 F29/F44)
      → book_supervisor(LLM 决策 → Command(goto=book_op / END / fallback),
         无静态出边——Spike ② 教训)
            → write_chapter(委托 F27 writer agent → save_draft → 章落盘 + 进度 done)
            → audit_chapter(章审校 LLM → 质量分/问题清单)
            → revise_chapter(按 audit 结果修订章内容 → 重新落盘)
            → mark_done(标记该章完成 → 推进下一章)
            → fallback(确定性: 剩余章一次写完成)
      → HITL(interrupt 节点, hitl_points 命中时; 无其他副作用——F29 §5.6)
```

**否决方案**：
- **方案 B（book-level deepagents agent + 工具驱动）**：deepagents 0.7.5 的 `create_deep_agent` 是单 agent ReAct 循环，无 `Command(goto)`/`interrupt` 原生能力（F29 Spike ① 实证），无法程序化施加**护栏/振荡检测/确定性回退/HITL 节点级 interrupt**——这些是 #551 硬需求（§1.2 agent 自主 + §1.4 边界）。deepagents 工具链保留用于**章节 writer 代理**（F27 既有），book-level 编排走自研图。
- **方案 C（F44 BookVolumePipeline 加 agentic flag）**：卷级 Send fan-out 是确定性并行扇出（每章一次写），改造侵入既有卷图 + 违背「agent 自主决策」语义（并行无决策序）。

**论证依据**：#551「类似 F29 Supervisor 的自主 agent 形态」→ 直接复用 F29 的 Command(goto) dynamic routing + 护栏 + 回退 + HITL；#551「复用 F44 book run」→ 复用 F44 的 WritingPlan/进度状态机/checkpoint/上限；#551「复用 deepagents 工具链」→ 章节 write 用 F27 build_agentic_writer（deepagents harness）。三者各取其长，不重复造轮子。

### 5.2 章节级自主循环（核心创新）

`BookAgenticPipeline` 的 `book_supervisor` 决策的**操作原语**（node）覆盖「单章 write/audit/revise 循环」：

- agent 可对同一章连续 goto `write_chapter → audit_chapter → revise_chapter → audit_chapter → ...` 直到其 LLM 决策认定「该章满意」→ goto `mark_done` → 下一章
- **循环上限**：`max_chapter_cycles`（默认 5）——同一章从首次 write 起累计 write/audit/revise/组合操作次数达上限 → 强制 `mark_done`（防无限修订，§7 场景 5）
- **审校下限**：`audit_required=true` 时，某章 write 后未 audit 即试图 `mark_done`/跳至下一章 → supervisor 护栏强制 goto `audit_chapter`（规格化下限，防「只写不审」降级）
- **进度落盘**：每章 write/audit/revise 完成中间态写 `WritingPlan.progress`（`in_progress`）；`mark_done` 写 `done` + `execution_refs[str(outline_id)]`；失败写 `failed`
- **章级失败重试**：write_chapter 委托失败 → 重试 N 次（默认 2，复用 F44 `retry_limit`）→ failed 标记 + trigger book_supervisor 决策（跳过/重写/中断）

**操作原语契约**（node 职责）：

| 原语 | 输入 | 执行 | 输出（状态增量） |
|------|------|------|------------------|
| `write_chapter` | outline_id + chapter brief | 委托 F27 writer agent（build_agentic_writer，章 brief 渲染）→ agent.invoke → draft_service.create | `{results[str(outline_id)]: draft.id}` + progress[outline_id]=in_progress |
| `audit_chapter` | outline_id + 章内容 | LLM 审校（质量分 + 问题清单）→ 落 audit 记录 | `{audit_results[str(outline_id)]: {score, issues}}` |
| `revise_chapter` | outline_id + audit 问题 | 委托改写 agent（按 audit 问题修订）→ draft 重新落盘 | `{results[str(outline_id)]: draft.id}` |
| `mark_done` | outline_id | progress[outline_id]=done + execution_refs 落库 | 进度快照 |
| `finish_book` | — | plan.status=completed → 全书完成 | status |

### 5.3 书级 supervisor 决策节点（F29 模式复用）

```python
async def book_supervisor_node(state: BookAgenticState, config: AgenticBookConfig, trace_sink) -> Command:
    """LLM 决策下一个 book-level 操作 → Command(goto)。

    决策输入（system prompt）：
    - 书任务上下文（WritingPlan title/one_liner + 大纲切片 + 角色摘要 + 风格偏好）
    - 可用操作池（write_chapter/audit_chapter/revise_chapter/mark_done/finish_book + 各章状态）
    - 书进度（progress 快照 + 当前章/已 done 章/失败章）
    - 路由历史（防重复/振荡感知）+ 护栏约束（max_steps/max_consecutive/max_chapter_cycles）

    决策输出（LLM 结构化 JSON）：{"action": "goto", "op": "<book_op>", "outline_id": "..."} /
    {"action": "finish"} / {"action": "fallback"}

    护栏（LLM 决策后强制，F29 §5.4）：
    - steps >= max_steps → fallback（步数超限）
    - op == last_op 且 consecutive >= max_consecutive → fallback（振荡）
    - op 不在操作池 / outline_id 非法 → fallback（非法防御）
    - 空 content / 解析失败 → 重试 N 次 → fallback（F26 弱模型教训）
    - 章节循环上限命中 → 强制 mark_done
    - audit_required 且跳审 → 强制 audit_chapter
    """
```

**LLM 决策实现**：复用 `LLMClientProtocol.chat`（`langchain_client.py`），book supervisor 角色 = 独立 AgentRole（`id="book_supervisor"`，system_prompt=默认模板或 config.supervisor_prompt，model=config.llm_default_model）——不消费 agent_*（F29 §5.3 同边界）。决策解析 = `parse_model_string` 剥离前缀 + JSON 解析（F26 §5.5 复用）。

### 5.4 BookService 装配（`domain/services/book_service.py` MODIFY）

- `write_book_agentic(plan_id, limits, config)` —— book-level 自主编排入口（镜像 write_book 校验 + 委托 BookAgenticPipeline.execute）
- `prepare_run` 增加 `mode="agentic"` 分支（预校验 = 计划存在 / 至少一道护栏 / 内容已写安全阀；不执行委托），复用 F44 §13.4 后台任务
- `_run_book`（books.py router）增加 `mode=="agentic"` → `write_book_agentic`
- `BookAgenticPipeline.execute(plan, limits, config) -> {run_id, status}`，`resume(interrupt_obj, *, approved, decision)`，`get_checkpoint_state(run_id)` —— 镜像 F44 BookVolumePipeline 接口

### 5.5 HITL 降级 + 中断恢复 checkpoint

**HITL 确认点**（`hitl_points` 白名单，默认空 = 全自动）：

| 确认点 | 触发 | payload | resume |
|--------|------|---------|--------|
| `book_start` | 书级 run 启动前 | `{question, plan_summary, proposed_first_chapter}` | approved → 继续 / rejected → fallback |
| `chapter_done` | 每章 mark_done 后（可选，默认关闭——全自动核心不打断章间） | `{question, chapter, score, quality_summary}` | approved → 下一章 / rejected → 回该章 revise |
| `finish` | 全书完成前 | `{question, chapter_count, total_progress}` | approved → completed / rejected → 继续修订 |

- **checkpoint**：复用 F44 AsyncSqliteSaver + `thread_id = str(plan.id)`（书级运行 ↔ 图 checkpoint 一一映射）；`llm_client` 用 `UntrackedValue`（F29/F44 模式，不序列化，resume 时 `Command(update=...)` 重注入）
- **跨重启 resume**：章边界续跑；杀进程 → 重启 → `resume` → 无重复内容（F44 安全阀兜底）
- **HITL 状态落库**：interrupt 时 plan.status=waiting_hitl + hitl_payload（F44 confirm_run 复用）

---

## 6. 组织规则

| # | 规则 | 说明 |
|---|------|------|
| R1 | **book-level 走自研图，章节 write 走 deepagents** | 编排决策（护栏/回退/HITL）须程序化施加（自研 StateGraph + Command(goto)）；章节 writer 复用 F27 deepagents harness（工具链） |
| R2 | **进度权威 = WritingPlan.progress** | 各操作节点中间态落盘（F44 §6 R2） |
| R3 | **「内容已写」安全阀先于一切执行** | write_chapter 前查该章已有内容/执行完成 → 拒绝重跑（F44 R3） |
| R4 | **interrupt 只放串行节点** | 唯一 interrupt 位置 = HITL 节点（book_start/chapter_done/finish）；操作节点内禁 interrupt（F44 R4） |
| R5 | **并行聚合走 reducer（本期无并行，预留）** | 若未来加并行章，results/audit_results 通道须 Annotated[dict, operator.or_]（F44 R5） |
| R6 | **护栏「至少一道有限护栏」** | 启动前 validate_at_least_one_hard_limit（F44 R6） |
| R7 | **llm_client 不序列化** | UntrackedValue + resume 重注入（F44 R9） |
| R8 | **链式拓扑保留** | mode 默认 static；agentic 新增；既有 static/supervisor/volume 零回归 |
| R9 | **HITL 降级语义** | hitl_points 默认空（全自动）；显式配置才打断；确认点缺失 → 不打断（降级而非阻塞） |
| R10 | **确定性回退** | fallback = 剩余未写章一次 write 完成（保底「完成+非空」），非 F29 角色链 |

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 | 归属 |
|---|------|------|------|
| 1 | 内容已写安全阀命中 | write_chapter 前 ChapterAlreadyWrittenError → 409（F44 R3），agent 重定向该章 audit/revise 或跳过 | 编排核心 |
| 2 | 书级 supervisor 决策 LLM 空 content（弱模型） | 重试 N 次 → 仍空 → fallback（确定性写剩余章） | 编排核心 |
| 3 | 决策输出非法 op / outline_id | 护栏 → fallback | 编排核心 |
| 4 | 振荡（同 op 连续 ≥ max_consecutive） | 护栏 → fallback（route_history 含 __fallback__） | 编排核心 |
| 5 | 章节循环超 max_chapter_cycles | 强制 mark_done（防无限修订）；进度落库 | 章节循环 |
| 6 | audit_required 且 agent 跳审 | 护栏强制 goto audit_chapter | 章节循环 |
| 7 | 章级 write 失败 | 重试 N 次 → failed 标记 → supervisor 决策（跳过/重写/HITL） | 编排核心 |
| 8 | HITL 确认点命中 | interrupt() → plan.status=waiting_hitl + payload；confirm approved 继续 / rejected 回退 | HITL |
| 9 | 进程被杀/断电 | AsyncSqliteSaver 章边界 checkpoint → 重启 resume（章边界）；安全阀防重复 | 恢复 |
| 10 | resume 时 llm_client 丢失 | UntrackedValue → Command(update) 重注入（F44 R7） | 恢复 |
| 11 | 上限全部无限制 | validate_at_least_one_hard_limit → 422（F44 R6） | 上限 |
| 12 | 无章节点（空计划） | completed 快路径（F44 §13.4） | 编排核心 |
| 13 | HITL 确认目标非 waiting_hitl | 422（F44 confirm 防呆） | HITL |

---

## 8. 文件结构

> 对照真实源码树（2026-08-23 实证）。文件路径以主仓根为基准。本会话 = 后端编排核心（#551 后端批），前端 #597 不在本 spec 文件结构内。

### 后端

| 动作 | 文件 | 说明 |
|------|------|------|
| CREATE | `backend/src/inkflow/infrastructure/agent/book_agentic_pipeline.py` | BookAgenticPipeline（§5.1-§5.3）+ BookAgenticState + book_supervisor/write_chapter/audit_chapter/revise_chapter/mark_done/finish/hitl/fallback 节点 + HITLInterrupt |
| CREATE | `backend/src/inkflow/domain/models/agent_book.py` | AgenticBookConfig（§2.2）+ 校验 |
| MODIFY | `backend/src/inkflow/domain/services/book_service.py` | `write_book_agentic()` + `prepare_run` mode=agentic 分支（§5.4） |
| MODIFY | `backend/src/inkflow/domain/services/book_run_mixin.py` | 预校验配合（如需） |
| MODIFY | `backend/src/inkflow/api/routers/books.py` | BookRunRequest 增加 `mode` Literal + `config` 字段；_run_book mode=agentic 分派（§3/§5.4） |
| MODIFY | `backend/src/inkflow/api/deps.py` 或 books.py `_build_book_service` | 装配 BookAgenticPipeline（llm_client + writer_factory + draft_service + audit_service + checkpointer 注入） |
| CREATE | `backend/tests/unit/test_book_agentic_pipeline.py` | 整模块 RED（§9） |
| CREATE | `backend/tests/unit/test_book_agentic_service.py` | write_book_agentic + prepare_run mode=agentic + confirm_run agentic 契约 |
| MODIFY | `backend/tests/unit/test_book_pipeline.py`（既有，守护） | 既有 F44 模式零回归 |
| MODIFY | `backend/tests/unit/test_book_service_stage4_gaps.py`（既有，守护） | 既有 F44 状态机零回归 |

### 前端

**本模块（后端批）无前端变更**。前端面板拆给 #597（Part of #551，S3 实现轨）。

---

## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 模型/契约 | AgenticBookConfig validator（max_steps/max_chapter_cycles 越界拒绝/默认值） | ≥90% |
| 服务 | write_book_agentic（计划/上限校验/安全阀/委托）；prepare_run mode=agentic；confirm_run agentic（404/422/成功） | ≥90% |
| 编排层（整模块 RED） | **书级自主编排**：mock LLM 决策序列（write→audit→revise→mark_done→finish）→ Command(goto) 路由正确 + **completed + 章节落盘非空**；**章节级自主循环**：同章 write→audit→revise 序列直至 mark_done；**循环上限**：超 max_chapter_cycles → 强制 mark_done；**audit_required**：跳审 → 强制 audit；**振荡护栏**：同 op 连续 ≥ max_consecutive → fallback；**步数上限** → fallback；**HITL**：hitl_points 命中 → interrupt payload + confirm resume 继续/reject 回退；**checkpoint 恢复**：execute → interrupt → 跨 restart（fresh 实例 + AsyncSqliteSaver）→ resume 续跑；**确定性回退**：fallback 写剩余章 | ≥90% |
| 集成 | BookAgenticPipeline + AsyncSqliteSaver 真实图执行（mock LLM 决策响应表）；F29/F44 既有模式零回归 | ≥90% |
| API | POST /runs mode=agentic 202；confirm 404/422；GET 状态 | ≥90% |
| 回归 | mode 默认 static 时既有测试全绿（test_book_pipeline/test_book_service 既有用例不动） | 全仓 ≥60%（ADR-027） |

**RED 形态**：`book_agentic_pipeline.py` 不存在 → ImportError（收集期）；`AgenticBookConfig` 缺失 → ImportError；`BookRunRequest.mode` 不识别 "agentic" → Pydantic extra 拒绝或分派断言失败；`write_book_agentic` 不存在 → AttributeError。

**测试无网络约束**：mock `LLMClientProtocol.chat`（book_supervisor 决策 side_effect 按调用序返回预置结构化 JSON 序列）；F27 writer agent = mock（writer_factory 返回 AsyncMock with invoke）；章节 write/audit/revise 内容 = 预置字符串；InMemorySaver / AsyncSqliteSaver 真实使用（HITL resume + 跨重启恢复必须真实验证）。

---

## 10. 不在范围内

| 项 | 归属 |
|----|------|
| 前端面板（Chat 接入系统级 Agent + 工具流式 + 删书级编排入口） | #597（Part of #551，S3 实现轨） |
| 并行章执行 | 远期（#270 DAG；本期串行推进） |
| 章内断点（同章中断恢复） | 远期（checkpoint 粒度=章边界，F44 §5.3 语义） |
| 跨章一致性/冲突解决引擎 | 远期 |
| deepagents harness 改造（book-level agent 工具驱动） | 不规划（F29 Spike ① 定稿：书级走自研图；deepagents 保留章节 writer） |
| 既有 F42 static / F29 supervisor / F44 volume 模式改造 | 不规划（新增 agentic 模式并行；链式拓扑保留） |
| MCP 表现层 | 不含 |

---

## 11. 依赖关系

- **依赖**：#551（本模块）→ F44（书级运行骨架 ✅）· F29（supervisor 动态路由 ✅）· F27（agentic writer ✅）· F26（deepagents harness ✅）· langgraph-checkpoint-sqlite（F44 阶段 4 ✅）· LangGraph 1.2.10（✅ venv 锁定）
- **被依赖**：#597（前端面板，Part of #551）消费本模块后端 API（GET /runs 状态 + POST /runs mode=agentic）
- **无新 Python 依赖**（全部既有 pip 包）
- **编号口径**：F49 为「自主编排型」变体（第 21 变体，接续 F29 自主编排型/F44 长任务编排型）

---

## 12. 关键架构决策记录

| 决策 | 方案 | 备选（否决理由） |
|------|------|-----------------|
| 编排引擎 | **自研 LangGraph StateGraph（book supervisor 节点 + Command(goto)）** | deepagents book-level agent 工具驱动（0.7.5 无 Command(goto)/interrupt，无法程序化施加护栏/HITL，F29 Spike ①）；F44 BookVolumePipeline 加 flag（确定性扇出无决策序，违背 agent 自主） |
| 章节自主循环 | **supervisor 动态路由到 write/audit/revise/mark_done 操作节点** | 单章内嵌 deepagents ReAct（工具循环语义属章节 writer，非编排级）；章内固定 write→audit→revise（非 agent 自主决策序列） |
| 执行入口 | **BookRunRequest.mode 扩展（默认 static）** | 新端点（API 面重复，F44 runs/confirm/intervene 天然复用） |
| 章节 write | **复用 F27 build_agentic_writer（deepagents harness）** | 新写章代理（重复实现） |
| checkpoint | **复用 F44 AsyncSqliteSaver + thread_id=str(plan.id)** | 新 checkpointer（F44 阶段 4 已交付，F29 §5.6 归远期） |
| HITL | **interrupt() + Command(resume)（hitl_points 白名单）** | 轮询式确认（无原生暂停）；hitl 全开（打断全自动核心，违背「全自动」产品定位——默认空即降级） |
| 成品完成判定 | **agent 自主 finish + 护栏兜底 fallback** | 确定性全写完才完成（无 agent 自主决策完成时机） |

---

## 13. 验收标准

> 对应 issue #551 后端批验收要点。实现 PR `Part of #551`（**禁 Closes #551**——前端批 #597 才关闭）。#551 保持 OPEN。

- **M0** spec 定稿合入 worktree（本会话第一步）
- **M1** RED 批全 FAIL：`pytest backend/tests/unit/test_book_agentic_pipeline.py test_book_agentic_service.py` — 收集期 ModuleNotFoundError（模块不存在）+ 追加 mode=agentic 段 FAIL
- **M2** GREEN + 父侧重跑全绿：pytest backend/tests/unit/（本模块 + 既有 F44/F29 零回归，mode 默认 static 守护）
- **M3** 书级自主编排：book_supervisor mock 决策序列 → Command(goto) 路由正确 → completed + 章节落盘非空
- **M4** 章节级自主循环：同章 write→audit→revise 直至 mark_done；循环上限强制 mark_done；audit_required 跳审强制 audit
- **M5** HITL + checkpoint 恢复：hitl_points 命中 → interrupt payload → confirm resume；跨 restart（fresh 实例 + AsyncSqliteSaver）resume 续跑
- **M6** QA 真实 LLM 场景：书级 run completed + 章节内容非空（真实 LLM key，S2 实现轨）
- **M7** PR：title Conventional Commits（冒号后首字符非大写），body `Part of #551`（无 Closes）；statusCheckRollup 全绿
- **M8** worktree 清理 + 本文件标记 ✅

---

## 待澄清问题

> 起草自检后剩余设计决策点。

- **Q1（设计决策级）：书级 supervisor 决策 LLM 来源** ✅ 已定（方案 A）— 复用 `config.llm_default_model`（与 F29 §5.3 / F27 agentic 一致）；不新增 superviso 专用模型字段。
  - A. `config.llm_default_model`（已定）
  - B. 独立配置字段
  - C. 复用 writer 角色模型
- **Q2（设计决策级）：章节自主循环的实现边界** ✅ 已定（方案 A）— supervisor 动态路由到 write/audit/revise/mark_done 操作节点（F29 Command(goto)），不在单章内嵌独立 deepagents 循环。
  - A. supervisor 动态路由（已定，§5.2）
  - B. 章内嵌 deepagents ReAct（工具循环属章节 writer，非编排级）
- **Q3（阻塞级）：audit/revise 的 LLM 质检实现深度** ✅ 已定（方案 A for 后端批）— audit 用 `llm_client.chat` 结构化输出质量分+问题清单；revise 用改善 agent 改写（复用 writer 默认链）。真实质检质量属 S2 实现轨，后端批以「存在 audit/revise 节点 + 落盘」为门禁。
  - A. 轻量 LLM 质检（已定，后端批门禁 = 节点存在 + 落盘）
  - B. 深度多重审校循环（S2 实现轨，后端批范围外）
