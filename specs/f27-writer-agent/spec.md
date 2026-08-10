# F27: Writer Agent 闭环（writer-agent）功能规格

**Spec 版本**: 1.0（初稿待评审）
**日期**: 2026-08-10
**依据**: PRD §6.1 F3/F4/F5 + Agent 化升级路径 v1.1（design/agent-upgrade-path-2026-08-03.md）§4 Stage 1 + F26 spec v1.1（specs/f26-agent-tools/spec.md §5.7）+ Spike 0 报告（docs/deepagents-evaluation-2026-08-10.md ② 空 content）+ 0.7.0 路线图拍板记录（2026-08-10）
**所属阶段**: 0.7.0（Agent 化升级第二批），估算 8-12 人天
**关联 Issues**: #160（F27 Writer Agent 闭环）
**依赖**: ✅ F26 agent-tools（deepagents 集成 + 5 只读工具，PR #236）· ✅ F5 LLM Provider · ✅ F4 Agent 管线 · ✅ #87 LangGraph 重构 · ✅ F34 单章审计 · ✅ F3 writing_service · ⏳ F28 agent-memory（F27 是事件源，反向依赖）
**参考 ADR**: ADR-D（护栏触发语义）、ADR-E（编排引擎=deepagents 0.7.5）、ADR-F（写工具形态）、ADR-C（预算护栏数值——本 spec 定稿）、ADR-015（LangChain 隔离）、ADR-027（覆盖率门禁）
**状态**: ✅ 已拍板（Q1=选项 A、Q2=选项 A + 设置可改、Q3=选项 A（N=5/模式）、Q4=选项 A，2026-08-10）

> **模块类型声明**: 本模块为 Agent 化升级新增变体——「**自主循环闭环型**」（第 11 个模块变体，编号依据：AGENTS.md 模块类型谱系，F26=第 10 变体口径延续）。与 F26（deepagents 集成 + 工具定义型）不同：F27 是**首个有 LLM 自主控制流 + 写操作落库 + 用户确认流**的业务闭环，新增 1 张 agent_run 表 + 1 张 draft 表（Q4 拍板）。

---

## 1. 概述

F27 交付判据 B+C（升级路径 v1.1 §1）：**writer_node 升级为 ReAct 工具循环 + save_draft 草稿写工具 + 修改率指标**——「LLM 与工具循环（调用→观察→再决策）+ LLM 自主终止（受安全上限约束）」。

### 1.1 双模式定位

| 模式 | 默认 | 控制流 | 工具 | 产出 | 状态流转 |
|------|------|--------|------|------|----------|
| `deterministic` | ✅ 默认 | 既有静态链（Architect→Writer→Auditor→Reviser，代码写死） | 无 | 直接写章节内容 | 现有语义不动 |
| `agentic` | 显式开启 | LLM 自主（deepagents ReAct 循环） | 5 只读 + save_draft | **草稿**（用户确认后生效） | draft →（确认）→ final |

- 双模式开关：`pipeline.mode: deterministic | agentic`，项目级配置 + CLI/请求覆盖（F13 同构，升级路径 v1.1 ADR-A）。
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
- `ChapterUpdate`（既有）：确认时经 chapter_service.update_chapter 写内容与状态（**service 层，不碰 ORM**——ADR-F 约束①）。

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

> 约束：既有 `/api/v1/writing/generate` 等端点**零改动**（deterministic 默认路径不动）；agentic 用独立前缀 `/writing/agentic/` 隔离语义，避免误用既有端点（升级路径 ADR-A：双模式并存）。

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
| guardrail 触发（max_steps/重复工具/空 content/token） | 200 + status=`terminated_by_guardrail` | **产物保留**（ADR-D），不视为 HTTP 错误；客户端按 status 分支 |
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

**工程约束（用户拍板，升级路径 v1.1 ADR-F）**：

| # | 约束 | 实现 |
|---|------|------|
| ① | 调 service 层不碰 ORM | save_draft 经 **draft_service**（新增领域服务）落库；字数统计/状态流转复用 domain/services（`_word_count.count_words` 等），不直接操作 SQLAlchemy session |
| ② | 单工具单事务 | 每次 save_draft 调用独立事务（draft repo 单次 commit）；agent run 长任务不跨工具持有事务 |
| ③ | 写操作落审计日志 | save_draft 每次成功/失败写 audit_logs（actor="agent:writer"，action 语义经 F34 AuditLog 结构——字段映射见 §5.5） |
| ④ | 草稿状态 | 落库时 status=DRAFT；用户确认（API confirm）→ 经 chapter_service.update_chapter 写入正式章节 + draft 置 CONFIRMED |

**工具返回**：成功 → `{"ok": true, "draft_id": "uuid", "status": "draft", "word_count": N}`；失败 → `{"ok": false, "error": "..."}`（is_error 语义，循环不中断）。

### 5.3 自主终止双保险

**预算护栏数值（ADR-C 定稿，Q2 拍板）**：默认值 = max_steps=12 / token_budget=32K / 同工具连续=3，**可在全局设置中更改**（F32 app_settings 扩展键，用户拍板 2026-08-10）。读取优先级：请求体显式字段（--max-steps/--token-budget）> 全局设置（agent_max_steps / agent_token_budget / agent_max_consecutive_tool）> 默认值。

| 终止路径 | 判定 | 结果 |
|----------|------|------|
| LLM 自然终止 | 最终 AIMessage 含正文 content 且无 tool_calls | status=completed，terminated_by="llm"，产物=正文 → 自动 save_draft 落草稿（若 LLM 未显式调用 save_draft，服务层兜底保存——**产物保留语义，ADR-D**） |
| max_steps 超限 | 步骤数 ≥ max_steps（默认 12，设置可改） | status=terminated_by_guardrail，terminated_by="max_steps"，产物保留（已 save 的草稿不动） |
| 同工具连续调用超限 | 同一工具连续调用 ≥ 上限（默认 3，设置可改） | status=terminated_by_guardrail，terminated_by="repeat_tool"，产物保留 |
| 空 content | §5.4 重试后仍空 | status=terminated_by_guardrail，terminated_by="empty_content"，产物保留 |
| token 超限 | 累计 token ≥ token_budget（默认 32K，设置可改） | status=terminated_by_guardrail，terminated_by="token_budget"，产物保留 |

> 全部 guardrail 映射 ADR-D：产物保留 + terminated_by_guardrail，**不视为 HTTP 错误**（200 + status 字段）；agentic 失败可回退 deterministic（用户自行决定，不自动回退）。

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
- 写工具放 `infrastructure/agent/tools/save_draft_tool.py`，经 draft_service + chapter_service + audit_log_service（调 service 不碰 ORM——ADR-F 约束①，与 F26 工具层规则一致）。
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
| LLM 未调 save_draft 就自然终止 | 服务层兜底保存草稿（产物保留，ADR-D） | 无（审计标注 "auto_saved"） |
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
| 自动回退 deterministic | 不自动（用户显式决定，升级路径 ADR-D） |
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
| 编排引擎 | deepagents 0.7.5 复用（F26 已集成，ADR-E） | LangGraph 手写循环（重复 deepagents 内建能力） |
| 写工具形态 | save_draft 自定义工具（进程内调 service，ADR-F） | MCP 写工具（跨进程开销，F20 再做） |
| 草稿机制 | 草稿状态 + 用户确认后生效（ADR-F ④） | agent 直接写正式章节（用户失控，F28 无事件源） |
| 单工具单事务 | 每次 save_draft 独立事务（ADR-F ②） | agent run 级大事务（长任务持锁风险） |
| 审计 | 复用 F34 audit_logs（severity_summary 承载动作语义） | 新建 audit 表（跨模块零 MODIFY 纪律，F34 表结构可表达） |
| 空 content 护栏 | 自动重试 1 次 + 仍空 → guardrail（Spike ② 实测 ~66% 空响应） | 不重试直接失败（弱模型主力场景，1 次重试成本低收益高） |
| 终止语义 | 双保险：LLM 自然终止 + 三类 guardrail（max_steps/重复工具/空 content/token），产物保留（ADR-D） | 硬失败丢弃产物（用户损失；guardrail 映射 FAILED 但产物可查） |
| steps 存储 | agent_run.steps JSON 快照 | 独立 steps 子表（YAGNI；AgentExecutionORM.stages JSON 先例） |
| 双模式开关 | extra 键 + CLI/请求覆盖，默认 deterministic（F13 同构，ADR-A） | 独立配置表（过重；extra 已有 F13 先例） |
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
  - C. 自动确认（草稿即生效）——违背用户拍板「用户确认后才转正式」（ADR-F ④），否决
  - 建议：A（估算 A=8-12 人天 / B=+2 人天且体验差）
- **Q2: 预算护栏数值（ADR-C 定稿）** ✅ 已确认（用户拍板：选项 A + 设置可改，2026-08-10）
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
