# F27: Writer Agent 闭环（writer-agent）功能规格
> **端**: backend

**Spec 版本**: 1.0（初稿待评审）
**日期**: 2026-08-10
**依据**: PRD §6.1 F3/F4/F5 + Agent 化升级路径 v1.1（design/agent-upgrade-path-2026-08-03.md）§4 Stage 1 + F26 spec v1.1（specs/f26-agent-tools/spec.md §5.7）+ Spike 0 报告（docs/deepagents-evaluation-2026-08-10.md ② 空 content）+ 0.7.0 路线图拍板记录（2026-08-10）
**所属阶段**: 0.7.0（Agent 化升级第二批），估算 8-12 人天
**关联 Issues**: #160（F27 Writer Agent 闭环）
**依赖**: ✅ F26 agent-tools（deepagents 集成 + 5 只读工具，PR #236）· ✅ F5 LLM Provider · ✅ F4 Agent 管线 · ✅ #87 LangGraph 重构 · ✅ F34 单章审计 · ✅ F3 writing_service · ⏳ F28 agent-memory（F27 是事件源，反向依赖）
**参考 ADR**: adr/ADR-034.md（护栏触发语义）、adr/ADR-035.md（编排引擎=deepagents 0.7.5）、adr/ADR-036.md（写工具形态）、adr/ADR-033.md（预算护栏数值——本 spec 定稿）、ADR-015（LangChain 隔离）、ADR-027（覆盖率门禁）
**状态**: ✅ 已实现（PR #241，2026-08-10 合入；Q1-Q4 拍板 2026-08-10）

> **模块类型声明**: 本模块为 Agent 化升级新增变体——「**自主循环闭环型**」（第 11 个模块变体，编号依据：AGENTS.md 模块类型谱系，F26=第 10 变体口径延续）。与 F26（deepagents 集成 + 工具定义型）不同：F27 是**首个有 LLM 自主控制流 + 写操作落库 + 用户确认流**的业务闭环，新增 1 张 agent_run 表 + 1 张 draft 表（Q4 拍板）。

---

## 1. 概述

F27 交付判据 B+C（升级路径 v1.1 §1）：**writer_node 升级为 ReAct 工具循环 + save_draft 草稿写工具 + 修改率指标**——「LLM 与工具循环（调用→观察→再决策）+ LLM 自主终止（受安全上限约束）」。

### 1.1 双模式定位

| 模式 | 默认 | 控制流 | 工具 | 产出 | 状态流转 |
|------|------|--------|------|------|----------|
| `deterministic` | ✅ 默认 | 既有静态链（Architect→Writer→Auditor→Reviser，代码写死） | 无 | 直接写章节内容 | 现有语义不动 |
| `agentic` | 显式开启 | LLM 自主（deepagents ReAct 循环） | 5 只读 + save_draft | **草稿**（用户确认后生效） | draft →（确认）→ final |

- 双模式开关：`pipeline.mode: deterministic | agentic`，项目级配置 + CLI/请求覆盖（F13 同构，升级路径 v1.1 adr/ADR-031.md）。
- **deterministic 零改动**：现有 `builtin:write_chapter` 静态链、writing API、CLI 默认路径全部不动（回归零破坏是本模块验收项 M4）。
- agentic 只通过**新增装配点**接入：CLI `write next --mode agentic` 与 REST 扩展（§3/§4），内部路由到 agentic_writer 服务。

### 1.2 与既有模块的边界

- **写入边界**：agentic 写操作**只经 save_draft 工具**（调 service 层），不直接碰 ORM/仓储；save_draft 是 agent 唯一写面。
- **数据边界**：agent 产物先落**草稿**（draft 状态），用户确认后才转正式章节（draft → final）。未确认前不产生正式章节变更。
- **运行边界**：每次 agentic run 落 agent_run 记录（steps 快照/工具调用/token），可观测 + F28 打底。
- **明确不含**：记忆系统（F28）、Supervisor/HITL interrupt（F29 0.8.0）、subagent task 工具（F29）、MCP 暴露（F20）、LangSmith tracing 接入（F26 遗留点 5，待定）。

### 1.3 与样板差异

非 F9 实体 CRUD（无标准 CRUD 端点）、非 F14 横切门面（有独立运行上下文）、非 F26 纯基础设施（有用户可见功能 + 数据落库）。本模块是「**编排层 + 写工具 + 运行记录 + 确认流**」四件套的组合变体。

---

## 2. 数据模型

### 2.1 领域模型（新增 `domain/models/agent_run.py`）

```python
@dataclass  # 或 Pydantic BaseModel（以实现为准，倾向 Pydantic——与既有 domain models 一致）
class AgentToolCall:
    """单次工具调用记录（决策轨迹的原子单元）。"""
    step_index: int          # 所属步骤序号（0-based）
    tool_name: str           # 工具名（search_characters / save_draft / ...）
    arguments: dict          # 已解析参数
    result: str              # 工具返回文本
    is_error: bool = False

@dataclass
class AgentStep:
    """单次 LLM 决策步骤快照。"""
    index: int
    message_content: str     # 该步 AIMessage 文本（空 = 只调工具）
    tool_calls: list[AgentToolCall]
    tokens: int = 0          # 该步 token 消耗

@dataclass
class AgentRun:
    """一次 agentic 写入运行。"""
    id: str
    project_id: uuid.UUID
    chapter_id: uuid.UUID | None   # 目标章节（草稿确认时写入）
    mode: str = "agentic"
    status: str                    # running / completed / failed / terminated_by_guardrail
    steps: list[AgentStep]
    final_content: str = ""        # 最终正文（自然终止时非空；guardrail 触发时可能为空）
    draft_id: str | None = None    # 关联草稿（save_draft 落库后回填）
    model: str = ""
    token_usage_total: int = 0
    terminated_by: str = ""        # "llm" / "max_steps" / "repeat_tool" / "empty_content" / "token_budget"
    created_at: datetime
    updated_at: datetime
```

### 2.2 草稿模型（新增 `domain/models/draft.py`，Q4 拍板后定稿）

| 决策 | 方案 | 理由 |
|------|------|------|
| 草稿存储形态 | **独立 draft 表（方案 A，建议）** vs 复用章节表 draft 状态（方案 B） | 见 Q4：独立表隔离 agent 产物与正式章节，确认原子写入，F28 diff 事件源干净；B 复用 ChapterStatus.DRAFT 但混入既有章节语义，确认时状态机污染 |
| 草稿与章节关系 | draft.chapter_id 指向目标章节（可空） | agent 写入时明确目标，确认时写入该章节 |

```python
class DraftStatus(StrEnum):
    DRAFT = "draft"          # agent 已写入，待用户确认
    CONFIRMED = "confirmed"  # 用户确认 → 已转正式章节
    REJECTED = "rejected"    # 用户拒绝/放弃（保留记录供 F28 分析）

class Draft(BaseModel):
    id: str
    project_id: uuid.UUID
    chapter_id: uuid.UUID | None   # 目标章节（确认时写入；None = 确认时需指定）
    agent_run_id: str | None       # 来源 agent run
    content: str
    status: DraftStatus = DraftStatus.DRAFT
    summary: str = ""              # LLM 一句话说明（可选，用户确认时展示）
    created_at: datetime
    confirmed_at: datetime | None
```

### 2.3 ORM（新增 `infrastructure/database/models/agent_run.py`，Q4 拍板后定稿）

| 表 | 关键列 | 说明 |
|----|--------|------|
| `agent_runs` | id / project_id(FK) / chapter_id(FK?) / mode / status / steps(JSON) / final_content / model / token_usage_total / terminated_by / created_at / updated_at | steps JSON 快照（AgentStep 序列，决策轨迹全量）——F28 与可观测性打底 |
| `drafts` | id / project_id(FK) / chapter_id(FK?) / agent_run_id(FK?) / content / status / summary / created_at / confirmed_at | 草稿表；FK 级联语义与 audit_logs 对齐（F34 先例） |

> 决策论证：steps 用 **JSON 快照**（非独立子表）——与 AgentExecutionORM.stages JSON 先例一致（F4），决策轨迹一次写入、只读消费；F28 如需要结构化查询再拆子表（YAGNI，不过早规范化）。

### 2.4 复用既有模型

- `ChapterStatus`（domain/models/chapter.py）：确认流转终点 `draft → final`（既有枚举已有 DRAFT/FINAL，确认动作 = 内容写入 + status 置 FINAL，Q4 方案 B 时草稿态用 DRAFT）。
- `ChapterUpdate`（既有）：确认时经 chapter_service.update_chapter 写内容与状态（**service 层，不碰 ORM**——adr/ADR-036.md 约束①）。

---

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 说明 | 状态 |
|------|------|------|------|
| POST | `/api/v1/writing/agentic/generate` | agentic 生成章节（显式开启，不改变既有 /generate 语义） | 新增 |
| GET | `/api/v1/agent/runs/{run_id}` | 查询单次 run 决策轨迹（steps/工具调用/token） | 新增 |
| GET | `/api/v1/agent/runs?project_id=&limit=` | 项目 run 列表（分页，倒序） | 新增 |
| POST | `/api/v1/agent/drafts/{draft_id}/confirm` | 确认草稿 → 写入正式章节 | 新增 |
| GET | `/api/v1/agent/drafts?project_id=&status=` | 草稿列表（用户确认入口） | 新增 |

> 约束：既有 `/api/v1/writing/generate` 等端点**零改动**（deterministic 默认路径不动）；agentic 用独立前缀 `/writing/agentic/` 隔离语义，避免误用既有端点（升级路径 adr/ADR-031.md：双模式并存）。

### 3.2 请求/响应示例

```json
POST /api/v1/writing/agentic/generate
{
  "project_id": "uuid",
  "chapter_id": "uuid",
  "outline": "本章大纲...",
  "context": "额外上下文（可选）",
  "min_words": 2000,
  "style_hint": "冷峻硬汉风",
  "max_steps": 12,
  "token_budget": 32000
}
→ 200
{
  "run_id": "uuid",
  "status": "completed",
  "draft_id": "uuid",
  "final_content": "草稿正文...",
  "word_count": 2100,
  "steps": [{"index": 0, "message_content": "", "tool_calls": [...]}],
  "token_usage_total": 8120,
  "terminated_by": "llm"
}
```

```json
POST /api/v1/agent/drafts/{draft_id}/confirm
{"chapter_id": "uuid"}   // 可选：草稿未绑定章节时指定
→ 200 {"draft_id": "uuid", "status": "confirmed", "chapter_id": "uuid"}
```

### 3.3 异常映射表

| 场景 | HTTP | 错误码/说明 |
|------|------|-------------|
| 项目/章节不存在 | 404 | 复用既有 `_NOT_FOUND_MESSAGES` 语义 |
| LLM 调用失败 | 500 | `X-InkFlow-Error-Code: LLM_ERROR`（既有映射复用） |
| guardrail 触发（max_steps/重复工具/空 content/token） | 200 + status=`terminated_by_guardrail` | **产物保留**（adr/ADR-034.md），不视为 HTTP 错误；客户端按 status 分支 |
| 草稿不存在 | 404 | 确认流错误面 |
| 草稿状态非 draft（重复确认） | 409 | 幂等防护 |
| 参数非法（max_steps 越界等） | 422 | Pydantic 校验 |

---

## 4. CLI 命令签名

### 4.1 `inkflow write next --mode agentic`（既有命令扩展）

```
inkflow write next --project-id <UUID> --chapter-id <UUID> --outline <文本>
                   [--context <文本>] [--min-words 2000] [--style <文本>]
                   [--mode deterministic|agentic]   # 默认 deterministic，显式 agentic 开启
                   [--max-steps 12] [--token-budget 32000] [--json]
  退出码: 0 成功 / 1 运行错误 / 2 参数错误
  --json 信封: {"ok": true, "data": {"run_id", "status", "draft_id", ...}}
  agentic 模式下:
    - 人类模式: 生成后打印「草稿已保存 (draft_id)，确认命令: inkflow agent draft confirm <draft_id>」
    - 决策轨迹: --json 信封含 steps 数组；人类模式打印摘要（N 步 / 调用了哪些工具 / token 消耗）
```

### 4.2 `inkflow agent draft` 子命令（agent_cmd.py 扩展）

```
inkflow agent draft list --project-id <UUID> [--status draft|confirmed|rejected] [--json]
inkflow agent draft confirm <draft_id> [--chapter-id <UUID>] [--json]
   确认后打印: 章节已更新 (status=final, 字数 N)
inkflow agent draft reject <draft_id> [--json]
   拒绝后打印: 草稿已拒绝（保留记录）
```

### 4.3 `inkflow agent run` 子命令（agent_cmd.py 扩展）

```
inkflow agent run list --project-id <UUID> [--limit 20] [--json]
inkflow agent run show <run_id> [--json]   # 决策轨迹: steps 每步 message + tool_calls + result
```

> 与 F26 `agent tools list` 的 CLI 豁免边界一致：`agent draft/run` 子命令经 HTTP（F38 恒 HTTP 纪律），`agent tools list` 保留本地枚举豁免。

---

## 5. 关键差异节：自主循环闭环

### 5.1 agentic 装配（`infrastructure/agent/agentic_writer.py` 新增）

```
CLI/API 请求 (--mode agentic)
  → AgenticWriterService.run(request)
      → 校验项目/章节/预算参数
      → build_deep_agent(model, api_key, base_url,
                         tools=[5 只读 + save_draft],   # F26 build_reader_tools + 新写工具
                         system_prompt=writer_agent_prompt)
      → agent.invoke({"messages": [...]})               # deepagents ReAct 循环（内建）
      → 后处理: 空 content 重试护栏（§5.4）/ 结果落 agent_run / 草稿关联
```

- **复用 F26**：`build_deep_agent`（ChatOpenAI 直传 + 模型名前缀剥离 + HarnessProfile）+ `build_reader_tools`（5 只读）。
- **新增**：`build_save_draft_tool(deps) -> Tool`（§5.2）。
- **注入**：工具工厂需要 chapter_service（确认/校验）、draft repo（草稿落库）、audit repo（审计日志）、agent_run repo（运行记录）——`AgenticWriterDeps` dataclass（鸭子类型，镜像 ReaderToolDeps 模式）。
- **system_prompt**：writer_agent 专用（继承既有 writer 角色提示 + 工具使用指引 + 「写正文前可查角色/伏笔/前文」「完成后输出正文，不要输出 JSON」）。模板放 `infrastructure/llm/templates/`（既有 yaml 模板体系）。

### 5.2 save_draft 写工具（`infrastructure/agent/tools/save_draft_tool.py` 新增）

```python
class SaveDraftParams(BaseModel):
    """save_draft 工具参数。"""
    project_id: uuid.UUID
    chapter_id: uuid.UUID | None = None   # 目标章节（可选，确认时指定）
    content: str                          # 草稿正文（Markdown）
    summary: str | None = None            # 一句话说明（用户确认时展示）

ToolSpec(
    name="save_draft",
    description="保存章节草稿（不修改正式章节）。agent 完成正文后必须调用本工具保存草稿；"
                "草稿需用户确认后才生效。返回草稿 id。",
    input_schema=SaveDraftParams.model_json_schema(),
)
```

**工程约束（用户拍板，升级路径 v1.1 adr/ADR-036.md）**：

| # | 约束 | 实现 |
|---|------|------|
| ① | 调 service 层不碰 ORM | save_draft 经 **draft_service**（新增领域服务）落库；字数统计/状态流转复用 domain/services（`_word_count.count_words` 等），不直接操作 SQLAlchemy session |
| ② | 单工具单事务 | 每次 save_draft 调用独立事务（draft repo 单次 commit）；agent run 长任务不跨工具持有事务 |
| ③ | 写操作落审计日志 | save_draft 每次成功/失败写 audit_logs（actor="agent:writer"，action 语义经 F34 AuditLog 结构——字段映射见 §5.5） |
| ④ | 草稿状态 | 落库时 status=DRAFT；用户确认（API confirm）→ 经 chapter_service.update_chapter 写入正式章节 + draft 置 CONFIRMED |

**工具返回**：成功 → `{"ok": true, "draft_id": "uuid", "status": "draft", "word_count": N}`；失败 → `{"ok": false, "error": "..."}`（is_error 语义，循环不中断）。

### 5.3 自主终止双保险

**预算护栏数值（adr/ADR-033.md 定稿，Q2 拍板）**：默认值 = max_steps=12 / token_budget=32K / 同工具连续=3，**可在全局设置中更改**（F32 app_settings 扩展键，用户拍板 2026-08-10）。读取优先级：请求体显式字段（--max-steps/--token-budget）> 全局设置（agent_max_steps / agent_token_budget / agent_max_consecutive_tool）> 默认值。

| 终止路径 | 判定 | 结果 |
|----------|------|------|
| LLM 自然终止 | 最终 AIMessage 含正文 content 且无 tool_calls | status=completed，terminated_by="llm"，产物=正文 → 自动 save_draft 落草稿（若 LLM 未显式调用 save_draft，服务层兜底保存——**产物保留语义，adr/ADR-034.md**） |
| max_steps 超限 | 步骤数 ≥ max_steps（默认 12，设置可改） | status=terminated_by_guardrail，terminated_by="max_steps"，产物保留（已 save 的草稿不动） |
| 同工具连续调用超限 | 同一工具连续调用 ≥ 上限（默认 3，设置可改） | status=terminated_by_guardrail，terminated_by="repeat_tool"，产物保留 |
| 空 content | §5.4 重试后仍空 | status=terminated_by_guardrail，terminated_by="empty_content"，产物保留 |
| token 超限 | 累计 token ≥ token_budget（默认 32K，设置可改） | status=terminated_by_guardrail，terminated_by="token_budget"，产物保留 |

> 全部 guardrail 映射 adr/ADR-034.md：产物保留 + terminated_by_guardrail，**不视为 HTTP 错误**（200 + status 字段）；agentic 失败可回退 deterministic（用户自行决定，不自动回退）。

### 5.4 空 content 重试护栏（Spike ② 必做，F26 spec v1.1 §5.7 硬性前置）

```
最终 AIMessage content 为空（工具已执行、未输出正文）
  → 自动重试 1 次: 附加一条用户消息
    「工具结果已回填。请基于以上工具结果直接输出章节正文（Markdown）。」
    重新调用 agent（保留上下文与已执行工具结果）
  → 重试后仍空 → terminated_by_guardrail("empty_content")
  → 重试后非空 → 正常完成（completed）
```

- **注意**：空 content 判定 = `content == ""`（deepagents 返回的 AIMessage content 为空串）；重试次数固定 1（Spike ② 实测弱模型 2/3 概率空响应，1 次重试是成本与收益平衡，Q2 可调）。
- **不重试 tool_calls 场景**：若最终消息含 tool_calls（模型仍在调工具），不算空 content，继续循环（直到 max_steps 或自然终止）。

### 5.5 审计日志（F34 audit_logs 复用）

save_draft / confirm / reject 三个写动作均落 audit_logs：

| 字段 | save_draft | confirm | reject |
|------|-----------|---------|--------|
| project_id | ✓ | ✓ | ✓ |
| chapter_id | 目标章节（可空） | 确认写入章节 | 目标章节（可空） |
| chapter_title | 快照（若章节存在） | 快照 | 快照（可空） |
| status | 复用枚举语义映射（pending→draft 动作标记） | confirmed | rejected |
| severity_summary | "draft_saved" | "draft_confirmed" | "draft_rejected" |
| summary | 草稿摘要/字数 | 确认摘要 | 拒绝原因（可空） |
| degraded | agentic=True | agentic=True | agentic=True |

> 实现说明：audit_logs 表结构是 F34 领域专用（severity 等），F27 通过 **audit_log_service（F34 既有）** 写入，动作语义用 severity_summary 承载（不扩表结构——跨模块零 MODIFY 纪律）；如 Q4 拍板独立 audit 语义则修订。

### 5.6 修改率基线（F28 生效前基线）

- **测量对象**：agentic vs deterministic 各生成 N 章（N 值 Q3 拍板，建议 N=5/模式）。
- **测量方式**：对每章记录（① 生成后用户是否直接确认（0 修改）② 确认前手动修改字数 diff ③ 是否 reject 重新生成）。
- **数据源**：drafts 表 status/confirmed_at + 确认时内容对比（草稿 vs 确认后写入内容——confirm 时计算 diff 字数落 draft 表 audit 字段）+ audit_logs。
- **指标输出**：基线报告（`docs/agent-baseline-YYYY-MM-DD.md`）——每模式 N 章的修改率均值/重新生成率，F28 验收判据「修改率下降」的对照值。
- **F27 只建测量**，不做统计 UI/命令（F28 交付 `inkflow memory stats` 类命令时并入）；基线报告生成可由手工脚本或 QA 执行。

### 5.7 决策轨迹暴露

- **存储**：agent_run.steps JSON 快照（每步 message + tool_calls + result + tokens）。
- **查询**：`GET /api/v1/agent/runs/{id}` 与 `inkflow agent run show <id>`（§3/§4）。
- **展示**：CLI 人类模式打印轨迹摘要（步骤数、工具调用序列如 `[search_characters → audit_chapter → save_draft]`、token 消耗、终止原因）；`--json` 全量。

---

## 6. 组织规则

- agentic 编排层放 `infrastructure/agent/agentic_writer.py`；领域服务 `domain/services/agentic_writer_service.py` 持编排契约（端口），实现细节不泄漏到 domain（ADR-015：deepagents/langchain 类型封闭在 infrastructure）。
- 写工具放 `infrastructure/agent/tools/save_draft_tool.py`，经 draft_service + chapter_service + audit_log_service（调 service 不碰 ORM——adr/ADR-036.md 约束①，与 F26 工具层规则一致）。
- 新增 domain models：`domain/models/agent_run.py`、`domain/models/draft.py`（纯 Pydantic，零 infrastructure import）。
- 新增 repo：`infrastructure/database/repositories/agent_run_repo.py`、`draft_repo.py`（异步 SQLAlchemy，镜像 ExecutionStore 模式）。
- ORM：`infrastructure/database/models/agent_run.py`（含 agent_runs + drafts 两表；或分文件，以实现为准）。
- 确认流经 **chapter_service.update_chapter**（领域规则：状态流转/字数统计在 service 层）——不新增「agent 直写章节」路径。
- 双模式开关读取：`project.config.extra["pipeline_mode"]`（extra 键，F13 同构）+ 请求体显式字段覆盖（`mode`）；**默认 deterministic**（未配置/未显式 → deterministic）。
- 预算护栏读取：请求体显式 > 全局设置（F32 `app_settings` 扩展键 `agent_max_steps` / `agent_token_budget` / `agent_max_consecutive_tool`）> 默认值 12/32K/3（§5.3，Q2 拍板）；设置键值域校验走 F32 SettingsKey 白名单扩展。

---

## 7. 边界情况与错误处理

| 场景 | 行为 | 错误面 |
|------|------|--------|
| agentic 请求但项目/章节不存在 | 404（复用既有映射） | HTTP 错误 |
| LLM 全程不调工具直接输出正文 | 正常完成（completed，terminated_by="llm"）；save_draft 兜底落草稿 | 无 |
| LLM 调 save_draft 多次（多草稿） | 每次独立事务落库；最终以最后一次为准（或保留多版本，Q4 拍板） | 无（记录全部，决策轨迹可见） |
| LLM 未调 save_draft 就自然终止 | 服务层兜底保存草稿（产物保留，adr/ADR-034.md） | 无（审计标注 "auto_saved"） |
| 最终消息含 tool_calls 但无正文 | 不是空 content 场景，继续循环；达 max_steps → guardrail | 200 + terminated_by_guardrail |
| 空 content 重试 1 次仍空 | terminated_by_guardrail("empty_content")，产物保留 | 200 + status 字段 |
| 同一工具连续调用 ≥ 上限 | terminated_by_guardrail("repeat_tool") | 200 + status 字段 |
| token 累计超限 | terminated_by_guardrail("token_budget") | 200 + status 字段 |
| 草稿确认时章节已被删 | 404（确认流报错，草稿保持 draft 可改绑） | HTTP 错误 |
| 重复确认同一草稿 | 409（草稿已 confirmed） | HTTP 错误 |
| save_draft 工具内部异常（DB 故障等） | 工具返回 is_error 文本，循环继续 | 不中断循环（F26 工具异常语义） |
| agentic 中途进程崩溃 | agent_run 状态保持 running（超时无恢复机制——F29 checkpointer 前 YAGNI） | 记录可见，人工重跑 |

---

## 8. 文件结构

| 动作 | 文件 | 说明 |
|------|------|------|
| CREATE | `backend/src/inkflow/domain/models/agent_run.py` | AgentRun/AgentStep/AgentToolCall 领域模型 |
| CREATE | `backend/src/inkflow/domain/models/draft.py` | Draft/DraftStatus 领域模型 |
| CREATE | `backend/src/inkflow/domain/services/draft_service.py` | 草稿服务（落库/确认/拒绝/列表；调 repo 不碰 ORM） |
| CREATE | `backend/src/inkflow/domain/services/agentic_writer_service.py` | agentic 编排服务（装配/护栏/兜底/run 记录） |
| CREATE | `backend/src/inkflow/infrastructure/agent/agentic_writer.py` | build_deep_agent 装配 + 循环后处理（空 content 重试护栏等） |
| CREATE | `backend/src/inkflow/infrastructure/agent/tools/save_draft_tool.py` | save_draft 写工具工厂 |
| CREATE | `backend/src/inkflow/infrastructure/database/models/agent_run.py` | AgentRunORM + DraftORM |
| CREATE | `backend/src/inkflow/infrastructure/database/repositories/agent_run_repo.py` | agent_runs 异步仓储 |
| CREATE | `backend/src/inkflow/infrastructure/database/repositories/draft_repo.py` | drafts 异步仓储 |
| CREATE | `backend/src/inkflow/infrastructure/llm/templates/writer_agent.yaml` | agentic writer system prompt 模板 |
| MODIFY | `backend/src/inkflow/domain/models/settings.py` | 预算护栏设置键扩展（agent_max_steps/agent_token_budget/agent_max_consecutive_tool，Q2 拍板设置可改；F32 SettingsKey 白名单增量） |
| MODIFY | `backend/src/inkflow/api/routers/writing.py` | 新增 /writing/agentic/generate（既有端点零改动） |
| CREATE | `backend/src/inkflow/api/routers/agent_runs.py` | run 查询 + draft 确认/列表端点（或并入 agent.py 既有 router，以实现为准） |
| MODIFY | `backend/src/inkflow/api/deps.py` | AgenticWriterDeps / draft_service / repos 装配 |
| MODIFY | `backend/src/inkflow/cli/commands/write.py` | next 命令加 --mode/--max-steps/--token-budget |
| MODIFY | `backend/src/inkflow/cli/commands/agent_cmd.py` | 新增 draft/run 子命令组 |
| CREATE | `backend/tests/unit/test_agentic_writer_service.py` | 编排服务契约（mock LLM 序列驱动，RED 主批） |
| CREATE | `backend/tests/unit/test_save_draft_tool.py` | 写工具契约（service 注入 + 事务 + 审计） |
| CREATE | `backend/tests/unit/test_draft_repo.py` | 草稿仓储集成（真实 SQLite 轨） |
| CREATE | `backend/tests/unit/test_agent_run_repo.py` | run 仓储集成（真实 SQLite 轨） |
| CREATE | `tests/cli/test_cli_agent_draft.py` | draft 子命令 CLI 测试（**须登记 ci.yml integration-cli-backend**） |
| CREATE | `tests/cli/test_cli_agent_run.py` | run 子命令 CLI 测试（同上登记） |
| CREATE | `tests/cli/test_cli_write_agentic.py` | write next --mode agentic CLI 测试（同上登记） |

---

## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 编排服务（核心） | mock LLM 固定 tool_call 序列驱动：① 先调 2 工具再写正文（正常闭环）② 连续 5 次同工具 → guardrail ③ max_steps 超限 → terminated_by_guardrail ④ 空 content → 重试 1 次 → guardrail ⑤ save_draft 草稿落库 + 确认转正式 ⑥ 审计日志写入 ⑦ 决策轨迹暴露 | ≥90% |
| 写工具 | save_draft 成功/失败（service 抛错 → is_error）；单事务断言（repo commit 次数）；audit 写入断言 | ≥90% |
| 仓储 | drafts/agent_runs CRUD + JSON 快照往返（真实 in-memory SQLite） | ≥90% |
| API | agentic/generate 200 双形态（completed/terminated_by_guardrail）；404/409/422 映射；确认流 | ≥90% |
| CLI | --mode agentic 信封/人类模式；draft/run 子命令；退出码 0/1/2 | ≥90% |
| 回归 | F26 5 只读工具测试仍绿；deterministic 全路径零回归 | 全仓 ≥60%（ADR-027 门禁 98.5/95.0） |

**RED 形态**：新模块整体不存在 → 顶部 import ModuleNotFoundError（收集期失败，exit 2）；既有文件追加段 → 404 断言 FAIL（如 API 新端点、CLI 新子命令）。

**测试基建（独立交付，升级路径 Stage 1）**：脚本化 mock LLM——固定 tool_call 序列驱动（不依赖真实 LLM），控制 flaky（PRD Flaky=0）。形态：mock `build_deep_agent` 返回值（fake agent 对象，invoke 按预置序列返回 AIMessage：tool_calls → ToolResult → 正文/空 content），或 patch deepagents 调用链；父侧 RED 批定死序列契约，GREEN 按契约实现。

---

## 10. 不在范围内

| 项 | 归属 |
|----|------|
| 记忆系统（diff 捕获/偏好提取/注入） | F28（事件源 = F27 草稿确认流，§5.6 测量数据） |
| Supervisor 自主编排 / HITL interrupt | F29（0.8.0，#161；CLI HITL 体验问题，升级路径 v1.1 §4 Stage 3 结论） |
| subagent task 工具 | F29（F26 §5.4 决策延续） |
| 草稿 diff 统计 UI / memory stats 命令 | F28 |
| checkpointer / 崩溃恢复 / 跨进程恢复 | 远期（F29 后评估） |
| LangSmith tracing 接入 | 待定（F26 遗留点 5） |
| agentic 模式在 GUI 的入口 | 未排期（GUI 在 F19 渲染层，CLI/API 先行——升级路径 v1.1 Stage 3 反思：GUI 体验优于 CLI，落地时以 GUI 为主，但 F27 范围仅 CLI/API） |
| 自动回退 deterministic | 不自动（用户显式决定，升级路径 adr/ADR-034.md） |
| MCP 工具暴露 | F20（同源复用工具定义） |
| 独立 ToolRegistry Protocol | YAGNI（F26 否决延续） |

---

## 11. 依赖关系

- **依赖**: F26（build_deep_agent + 5 只读工具 + HarnessProfile）、F5（LLM Provider/parse_model_string）、F3（writing_service 字数/格式规则）、F34（audit_logs + audit service）、F4（AgentExecutionORM/ExecutionStore 仓储先例）、F2（chapter_service 状态流转）、F32（全局设置键扩展，Q2 拍板）、#87（已合 0.3.1）。
- **被依赖**: F28（agent-memory：草稿确认流 diff 事件源 + 修改率基线对照）、F20（MCP 工具同源）、F29（0.8.0 supervisor 复用 agentic_writer 装配）。
- 新增运行时依赖：**无**（deepagents/langchain 已在 F26 引入）。
- 编号口径声明：以 ADR-019 v5 版本表为准（F26=本阶段前置，F27=本模块；F29 已移 0.8.0，#161）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 备选（否决理由） |
|------|------|-----------------|
| 编排引擎 | deepagents 0.7.5 复用（F26 已集成，adr/ADR-035.md） | LangGraph 手写循环（重复 deepagents 内建能力） |
| 写工具形态 | save_draft 自定义工具（进程内调 service，adr/ADR-036.md） | MCP 写工具（跨进程开销，F20 再做） |
| 草稿机制 | 草稿状态 + 用户确认后生效（adr/ADR-036.md ④） | agent 直接写正式章节（用户失控，F28 无事件源） |
| 单工具单事务 | 每次 save_draft 独立事务（adr/ADR-036.md ②） | agent run 级大事务（长任务持锁风险） |
| 审计 | 复用 F34 audit_logs（severity_summary 承载动作语义） | 新建 audit 表（跨模块零 MODIFY 纪律，F34 表结构可表达） |
| 空 content 护栏 | 自动重试 1 次 + 仍空 → guardrail（Spike ② 实测 ~66% 空响应） | 不重试直接失败（弱模型主力场景，1 次重试成本低收益高） |
| 终止语义 | 双保险：LLM 自然终止 + 三类 guardrail（max_steps/重复工具/空 content/token），产物保留（adr/ADR-034.md） | 硬失败丢弃产物（用户损失；guardrail 映射 FAILED 但产物可查） |
| steps 存储 | agent_run.steps JSON 快照 | 独立 steps 子表（YAGNI；AgentExecutionORM.stages JSON 先例） |
| 双模式开关 | extra 键 + CLI/请求覆盖，默认 deterministic（F13 同构，adr/ADR-031.md） | 独立配置表（过重；extra 已有 F13 先例） |
| agentic 端点 | 独立 /writing/agentic/generate | 扩展现有 /generate（deterministic 默认路径零改动纪律） |
| 自动回退 | 不自动 | 自动回退 deterministic（掩盖 agentic 失败，用户不知情） |

---

## 13. 验收标准

- **M1 编排契约全绿**: `pytest tests/unit/test_agentic_writer_service.py` — 7 类契约（正常闭环/同工具×5/max_steps/空 content 重试/save_draft 落库+确认/审计日志/决策轨迹）RED（ModuleNotFoundError）→ GREEN 全过
- **M2 写工具全绿**: `pytest tests/unit/test_save_draft_tool.py` — 正反例 + 单事务断言 + 审计写入
- **M3 仓储全绿**: `pytest tests/unit/test_draft_repo.py tests/unit/test_agent_run_repo.py` — 真实 SQLite 轨 CRUD + JSON 快照
- **M4 回归零破坏**: F26 5 只读工具测试仍绿（`tests/unit/test_reader_tools.py`）+ deterministic 全路径（`tests/api/test_writing_api.py` 等）零回归；覆盖率全仓 ≥60%（ADR-027 门禁 98.5/95.0）
- **M5 CLI 全绿**: `tests/cli/test_cli_write_agentic.py test_cli_agent_draft.py test_cli_agent_run.py`（**已登记 ci.yml integration-cli-backend**）— 信封/人类模式/退出码
- **M6 API 全绿**: agentic/generate + runs + drafts 端点契约（404/409/422 映射 + 双形态 200）
- **M7 真实模型冒烟（手工）**: 有 key 时 `write next --mode agentic` 真实运行 1 章 ≥ 2000 字、正文命中检索角色名/伏笔（升级路径验收判据②）
- **M8 修改率基线**: agentic vs deterministic 各 N 章（Q3 拍板值），产出基线报告 `docs/agent-baseline-YYYY-MM-DD.md`（修改率均值/重新生成率，F28 对照值）
- **M9 决策轨迹可查**: `inkflow agent run show <run_id> --json` 输出完整 steps（工具调用序列 + 结果 + token），`--json` 信封字段契约测试覆盖

---

## 14. 待澄清问题

- **Q1: save_draft 确认流形态** ✅ 已确认（用户拍板：选项 A，2026-08-10）
  - A. **CLI/API 显式确认**（**已拍板**）——agent 落草稿后，用户经 `inkflow agent draft confirm <id>` 或 REST confirm 端点确认；控制感在用户手里，产物可审阅再确认；与升级路径 v1.1 Stage 3 先例判断一致（HITL 在 CLI 体验差）
  - B. deepagents interrupt_on（HITL）——agent 循环中暂停等待用户输入；CLI 交互体验差、无 GUI 前置（F19 渲染层未排期），且 deepagents 0.7.5 interrupt 形态未 spike 验证
  - C. 自动确认（草稿即生效）——违背用户拍板「用户确认后才转正式」（adr/ADR-036.md ④），否决
  - 建议：A（估算 A=8-12 人天 / B=+2 人天且体验差）
- **Q2: 预算护栏数值（adr/ADR-033.md 定稿）** ✅ 已确认（用户拍板：选项 A + 设置可改，2026-08-10）
  - A. **max_steps=12 / token_budget=32K / 同工具连续=3 为默认值**（**已拍板**——升级路径 v1.1 §4 Stage 1 与 §7 风险节初值；Spike 0 实测 1 章正文约 3-6 步工具 + 1 步正文，12 步余量充分）
  - B. max_steps=8 / token_budget=16K / 同工具连续=3（更紧，省钱但弱模型重试后易触发 guardrail）
  - C. max_steps=20 / token_budget=64K / 同工具连续=5（更松，复杂章节容错高但 token 成本 3-8 倍风险↑）
  - **用户补充（已并入正文）**：默认值可在**设置中更改**——新增 F32 app_settings 扩展键 agent_max_steps / agent_token_budget / agent_max_consecutive_tool；读取优先级 = 请求体显式 > 全局设置 > 默认值（§5.3/§6/§8）
  - 建议：A
- **Q3: 修改率基线 N 值** ✅ 已确认（用户拍板：选项 A，N=5/模式，2026-08-10）
  - 背景：F27 交付「修改率基线」测量——agentic vs deterministic 各生成 N 章，记录每章 ① 是否直接确认（0 修改）② 确认前手动修改字数 diff ③ 是否 reject 重新生成；产出基线报告 `docs/agent-baseline-YYYY-MM-DD.md`（修改率均值/重新生成率），作为 F28 验收判据「修改率下降」的对照值（§5.6）
  - A. **N=5/模式**（**已拍板**——统计意义初步、成本可控：agentic 每章 8-32K token，5 章 ≤160K token 量级；基线测量随开发自然积累，不强制一次性跑完）
  - B. N=3/模式（最少成本，统计噪声大——一章好一章差即 ±30% 波动）
  - C. N=10/模式（更稳，成本 ×2）
  - 建议：A
- **Q4: agent_run / drafts 表结构（快照粒度）** ✅ 已确认（用户拍板：选项 A，2026-08-10）
  - A. **steps JSON 快照 + drafts 独立表**（**已拍板**）——agent_runs.steps 存全量决策轨迹（每步 message/tool_calls/result/tokens），F28 可观测直接消费；drafts 独立表隔离 agent 产物与正式章节，确认原子写入，diff 事件源干净；多草稿保留多版本
  - B. steps 拆子表 + drafts 独立表——结构化查询灵活但过度规范化（当前只读消费，YAGNI；AgentExecutionORM.stages JSON 先例）
  - C. 复用章节表 draft 状态（不建 drafts 表）——无新表，但 agent 产物混入正式章节表、确认语义污染既有状态机、多版本丢失
  - 建议：A（估算 +0.5 人天 vs C 省表但语义债）

---


---

## 附录：f49-autonomous-writing（原独立 spec，容器化合并）

> 本章节由原 `specs/f49-autonomous-writing/spec.md` 合并而来（2026-08-29 spec 目录重构）。

# F49: 自主全自动写作（autonomous-writing）功能规格

**Spec 版本**: 1.0（初稿，2026-08-23）
**日期**: 2026-08-23
**依据**: Issue #551（Agent 全自动写作，milestone 0.12.0）+ 用户拍板 2026-08-21（#551 归 0.12.0，拆批：后端编排核心 → 前端面板 #597 → 验证）+ 既有源码核查（F44 book run / F29 supervisor / F27 writer / deepagents harness 0.7.5）+ 参考规格 `specs/f44-book-orchestrator/spec.md`（书级运行骨架 + HITL + checkpoint）+ `specs/f29-supervisor/spec.md`（supervisor 动态路由 + 护栏 + 回退 + HITL）
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
