# F34: 章节审计（chapter_audit）— 功能规格

> **时间口径（ADR-055 / #1000）**：本模块时间字段（created_at/confirmed_at（--confirm 确认输出 + --history 列表））**存储 / API / MCP / `--json` 一律 UTC ISO 原始值**；CLI 人类输出经 `cli/_time.format_local` 转**系统本地时区**显示（'YYYY-MM-DD HH:mm:ss'，naive 串=UTC 口径先补 tzinfo 再换算）。硬约束惯例，非可配置开关。
>
> **端**: cross

> **Spec 版本**: 1.5 | **日期**: 2026-10-07 | **依据**: Issue #208（2026-08-09 用户拍板立项）、PRD P1-07 审计能力延伸、Constitution P1-P6（P2 解耦 / P5 YAGNI）；v1.2 增量依据 Issue #1267（审计结果消费方——写作链须按审计结论阻断）；v1.3 增量依据 Issue #1266（审计能力缺口——补「前后章连贯性」+「大纲符合度」两类 check_type）；v1.4 增量依据 Issue #1420（客户端超时后审计明细不可恢复——findings 落库 + 读口 + 超时文案对齐）；v1.5 增量依据 Issue #1425（审计异步语义——触发即返回 `log_id`（202）+ 后台执行 + 按 id 轮询状态；用户 2026-10-06 拍板**方案 B**）
> **所属阶段**: 0.6.0（#208 章节审计，估算 5-7 人天——v1.1 拍板含轻量记录 + CLI 确认 + GUI 最小版）
>
> **Spec 变更（v1.0 → v1.1）**: **用户拍板（2026-08-09）**——Q1=C **轻量审计记录**（audit_logs 表：时间/章节/结果/确认状态/备注，不含 findings 明细；可追溯性落地且避免全量持久化膨胀）；Q2=B **CLI 支持确认**（`--confirm accept|reject`——单 CLI 用户不应被迫下载 GUI，双入口确认状态统一落 audit_logs）；Q3=C **GUI 最小版一并做**（章节页审计按钮 + 报告弹层 + accept/reject，无历史页/通知——确认闭环是功能定义）。§1/§2/§3/§4/§5/§7/§8/§9/§10/§12/§13 同步修订；Issue #208 验收标准已更新（gh comment 留痕 2026-08-09）。
>
> **Spec 变更（v1.3 → v1.4）——Q1=C 演进（非推翻）**: 客户端 300s 超时（响应被丢弃）后审计明细永久不可达，实测 352 章批审计命中 9 章（2.6%），只能重跑（约 200–300 秒 LLM 调用）且新增重复记录（Issue #1420）。
> ① **方案 2（推荐·本版本采用）**：`audit_logs` 增 `findings` JSON 快照列（`TEXT NOT NULL DEFAULT '[]'`，`LenientJSON` 读回空串/旧行安全）——**触发审计出参（POST /audit 响应体）零变化**，仅落库多一份快照；新增读口 `GET /api/v1/audit-logs/{log_id}` + CLI `audit chapter --log <id>` 按记录 ID 取回明细（轻量记录元信息 + findings）。列表端点 `GET /projects/{pid}/audit-logs` **仍返回轻量 `AuditLog`**（响应形态零变化，Q1=C 摘要级口径不变）。
> ② **方案 1（无论如何都做，同 PR 落地）**：传输层 TIMEOUT 文案不再承诺不存在的 `list/get` 能力（原「请稍后用 list/get 查询结果」→「请稍后查看结果」）——文案不得指向不存在的读口。
> ③ **方案 3（异步语义：触发即返回 log_id + 按 id 轮询）** 本版本不做，归后续演进（§10）。
> 连带修订：§2.3 / §3.1 / §3.2 / §3.3 / §4 / §5.1 / §5.7 / §7 / §8.1 / §9 / §10 / §12 / §13。
>
> **Spec 变更（v1.4 → v1.5）——异步语义（#1425，用户 2026-10-06 拍板方案 B，**破坏性端点变更**）**: v1.4 读口让「超时后的明细」可恢复，但**触发仍是阻塞式**（65–305s/章）——客户端 300s 超时后既不知道任务是否在跑，重试还会再落一条无法区分的新记录（#1420 实测 9/352 章超时后重跑）。
> ① **`POST /projects/{pid}/chapters/{cid}/audit` 由阻塞 200 改为 202 + `{log_id, status}`**：请求只做「校验 + 受理」，**立即返回**（< 1s）；实际检查在**后台任务**中执行（`asyncio` fire-and-forget，先例 F44 #456 `POST /books/runs`）。
> ② **任务状态承载 = 复用 `audit_logs` 本表**（不新建表、不复用 `agent_executions`——后者是 agent 管线运行记录，语义不匹配，见 issue 方案矩阵 D）：增 `run_status`（`running` / `completed` / `failed`，历史行/同步路径默认 `completed`）+ `error`（失败原因）+ `content_hash`（章节内容指纹，幂等去重用，**不出现在 API 响应**）。
> ③ **新增轻量轮询端点 `GET /api/v1/audit-logs/{log_id}/status`**；findings 仍由 v1.4 读口 `GET /api/v1/audit-logs/{log_id}` 取回（**复用**，不新增明细面）。列表/明细响应**增补字段** `run_status` / `error`（加法式，向后兼容）。
> ④ **重跑幂等**：同章同内容重复触发 → 复用「运行中（窗口内）/ 最近完成且待确认未降级」的记录，**不产生新记录**；确认后（accepted/rejected）或内容变更 → 新记录（`--history` 可见 `run_status`，据此区分「哪条对应哪次尝试」）。
> ⑤ **CLI 默认保 UX**：`audit chapter <章> -p <项目>` 默认 `--wait`（内部轮询至终态后输出报告，人类输出与今天一致），`--no-wait` 立即返回 `log_id`。
> ⑥ **审计域 TIMEOUT hint 收敛**（#1425 顺带项）：MCP `_hint_for("TIMEOUT")` 文案原为「请先用对应 list/get 工具查询结果」——审计域**没有 list/get action**，恢复路径是「按 `log_id` 查询」；审计工具改用域专属 hint（`audit` action=`result`），并同步升级 `backend/tests/unit/mcp/test_mcp_llm_timeout_926.py`（属契约演进）。
> 连带修订：§1 / §2.3 / §2.4 / §3.1 / §3.2 / §3.3 / §4 / §5.1 / §5.7 / §7 / §8.1 / §8.2 / §9 / §10 / §12 / §13。
>
> **关联 Issues**: [#208](https://github.com/zhx-xi/InkFlow/issues/208)（本模块）；[#54](https://github.com/zhx-xi/InkFlow/issues/54)（F22 全文搜索——本模块为 F22「AI 自动维护」的增强触发语义前置，**F22 不阻塞等待本模块**）；[#45](https://github.com/zhx-xi/InkFlow/issues/45)（F15 审计服务——静态档案一致性，与本模块互补）
> **依赖**: ✅ F2（章节 + ChapterStatus 四态：REVIEW/FINAL 为「写完一章」天然钩子）· ✅ F5（LLM 管线，ChatOpenAI 既有）· ✅ F9（角色档案读取）· ✅ F10（世界观条目读取）· ✅ F15（静态一致性审计可委托，API 已存在）· ✅ F19（GUI 渲染层，确认流程 UI 接线）· ⏳ F22（#54，被依赖方，非前置）
> **参考 ADR**: [ADR-001](../../adr/architecture/ADR-001.md)（模块化单体）· [ADR-002](../../adr/architecture/ADR-002.md)（六边形分层）· [ADR-012](../../adr/architecture/ADR-012.md)（错误处理）· [ADR-014](../../adr/llm/ADR-014.md)（ChatPromptTemplate）· [ADR-015](../../adr/llm/ADR-015.md)（LangChain 隔离）· [ADR-018](../../adr/test-ci/ADR-018.md)（测试分层）· [ADR-019](../../adr/packaging/ADR-019.md)（版本里程碑 + 模块编号口径）· [ADR-027](../../adr/test-ci/ADR-027.md)（覆盖率门禁）· [ADR-026](../../adr/test-ci/ADR-026.md)（真实 AI CI：LLM 测试 Fake 注入 + label 触发验证）
> **状态**: ✅ 已实现（PR #219，#208 2026-08-09）

---

## 1. 概述

提供**章节级审计**能力：当一章**写完**（章节状态进入 REVIEW/FINAL）或用户手动触发时，对该章内容执行四项检查——**字数**（F2 既有计数）、**人设漂移**（章节文本 vs 角色档案）、**设定漂移**（章节文本 vs 世界观条目）、**静态一致性**（委托 F15）——产出**审计报告**，**落轻量审计记录（audit_logs）**，并由**用户在 GUI 或 CLI 中确认**（接受 / 拒绝后修改重审）。

**核心价值**: 长篇写作的核心风险是「写偏了」——人设 OOC（Out of Character）、设定与世界观冲突，写到 20 万字才发现要回头改。章节审计把「检查 + 确认」嵌入写完一章的自然节点（REVIEW 状态），让漂移在发生当章就被发现。**AI 只做建议，用户是最终决策者**（与 F27「草稿+确认」哲学一致：控制感在用户手里）。

**v1.1 变更要点（用户拍板 2026-08-09）**:
1. **Q1=C 轻量审计记录**：每次审计落一条 audit_logs 记录（时间/章节/结果摘要/确认状态/备注），**不存 findings 明细**——满足「可追溯」验收（Issue #208）且避免全量持久化膨胀；GUI 历史页不做（Q3=C 范围），追溯通过 CLI 查询/API 端点（§3.3/§4）
2. **Q2=B CLI 确认**：CLI 支持 `--confirm accept|reject`（含备注）——单 CLI 用户不应被迫下载 GUI 才能完成确认闭环；GUI/CLI 双入口确认状态统一写 audit_logs（单一真相源）
3. **Q3=C GUI 最小版一并做**：章节页「审计」按钮 + 报告弹层（findings 按严重级别）+ 接受/拒绝——确认闭环是功能定义的一部分（用户拍板原话「最后由用户进行确认」），不做历史页/通知

**变体定位（第 17 变体「章节审计型」）**: 本模块是 **F15 横切审计型 × F16 文本分析型 × F14 LLM 管线**的产物变体——像 F15 一样横切只读聚合多模块档案（角色/世界观/章节），像 F16 一样对**文本内容**做分析，但分析主体是 **LLM 语义漂移检查**（非确定性统计），且新增 **用户确认工作流 + 轻量审计记录**（F15/F16 都无确认环节、无记录表）。编号依据 AGENTS.md 模块类型谱系（F30=13 / F32=14 / F21=15 / F22=16 → 本模块第 17 变体），冲突以 ADR-019 v5+ 为准。

```
章节进入 REVIEW / 手动触发
        │
        ▼
① 字数检查（F2 word_count 确定性）
② 人设漂移检查（LLM：章节文本 vs Character 档案）
③ 设定漂移检查（LLM：章节文本 vs WorldSetting 档案）
④ 静态一致性（委托 F15 audit，可选包含）
        │
        ▼
ChapterAuditReport（检查项 + 严重级别 + 建议）
        │
        ▼
落 audit_logs 轻量记录（时间/结果/摘要）
        │
        ▼
确认：GUI（弹层 accept/reject）或 CLI（--confirm）──▶ 更新 audit_logs 确认状态
```

**边界声明**:
- F34 做**章节级**审计（一章一报告），**不做**全书批处理审计（F15 已覆盖档案间一致性，全书级由 CLI 循环调用实现）
- F34 的 LLM 漂移检查是**辅助建议**（提示「此段与人设描述可能有冲突」），**不自动改文**；最终由作者确认/修改（F27 哲学）
- F34 新增**一张轻量记录表 audit_logs**（Q1=C 拍板：仅摘要级字段，无 findings 明细、无 JSON 快照；schema 由 `Base.metadata.create_all` 管理，零迁移）
- F34 的确认流程 GUI（最小版）+ CLI 双入口均属于本功能范围（Q2=B / Q3=C 拍板）；F22 索引同步**不阻塞等待**本模块（F22 v1.1 用内容变更 + REVIEW/FINAL 状态触发增量，本模块实现后审计确认可作为增强触发点，见 §10）
- F34 不修改任何既有模块的 Repository/Service（零跨模块 MODIFY；读取全走既有只读方法 + F15 audit 委托，见 §8）

---

## 2. 数据模型

遵循「领域 Pydantic 实体 + DTO」模式（ADR-004）。F34 新增**一张持久化表**（audit_logs，轻量记录，Q1=C）+ **瞬态报告模型**（ChapterAuditReport）+ **触发/确认 DTO**。

### 2.1 AuditCheckType（检查项枚举）

| 值 | 检查项 | 性质 | 数据源 |
|----|--------|------|--------|
| `word_count` | 字数检查 | 确定性 | F2 Chapter.word_count vs 目标（ProjectConfig.default_words / 历史基线） |
| `character_drift` | 人设漂移 | LLM 分析 | F9 Character（name/personality/background/goals） |
| `setting_drift` | 设定漂移 | LLM 分析 | F10 WorldSetting（name/content） |
| `static_consistency` | 静态一致性 | 确定性（委托 F15） | F15 AuditService（可选包含，默认含） |
| `cross_chapter` | 前后章连贯性 | LLM 分析 | 前一章摘要（#1253 `chapter_summaries`）+ 后一章大纲（#1266） |
| `outline_compliance` | 大纲符合度 | LLM 分析 | 本章章纲 + 所属卷纲（F11 outlines，#1266） |

> **#1266 增量（两类 check 的定义与前置条件）**：
> - `cross_chapter`（前后章连贯性）：比对本章正文 vs **前一章摘要**（复用 #1253 `SummaryService.ensure_summary` 缓存，**不读前章全文**——跨章检查的预算纪律）与**后一章大纲**（章纲序列中紧随本章章纲的下一个）。判定跨章连贯性断点：前章悬念未接、因果链缺失、人物状态突变、时间线矛盾。**前置**：前一章摘要可得 + 本章在大纲序列中可定位；缺 → 跳过该检查（不产 finding、不降级）。
> - `outline_compliance`（大纲符合度）：比对本章正文 vs **本章章纲**（`outline.chapter_id == 本章` 且 `level == "chapter"`）与**所属卷纲**（章纲 `parent_id` 指向的卷）。判定正文是否覆盖大纲要点、是否偏离。**前置**：本章存在章纲；无 → 跳过该检查（不产 finding、不降级）。
> - 两类均复用既有 `_run_drift_check` 范式（`(findings, degraded)` 返回 + 模型异常立即降级 / 解析失败重试 1 次 + 降级落日志）；severity 与既有漂移检查同级（`error` = 明确矛盾，`warning` = 明显疑似）；正文截断沿用既有 `_audit_context._MAX_CHAPTER_CHARS` 常量（不新造预算）。
> - 降级语义对**每类检查独立**：某类 LLM 失败 → 该类 findings 为空 + 报告 `degraded=true`，其余检查与确定性检查照常（HTTP 仍 200）。

### 2.2 ChapterAuditFinding / ChapterAuditReport（瞬态报告模型）

```python
class AuditSeverity(StrEnum):
    INFO = "info"       # 提示（如：章节字数低于目标 20%）
    WARNING = "warning" # 警告（如：角色行为可能与人设冲突）
    ERROR = "error"     # 错误（如：明确与设定矛盾）

class ChapterAuditFinding(BaseModel):
    check_type: AuditCheckType
    severity: AuditSeverity
    message: str            # 人类可读描述（中文）
    suggestion: str = ""    # 修改建议（LLM 给，可为空）
    ref_entity_id: uuid.UUID | None = None  # 关联档案条目（角色/设定），无则 None
    ref_entity_name: str = ""               # 关联条目名（展示用）
    context: str = ""       # 章节中相关片段（≤200 字，定位用）

class ChapterAuditReport(BaseModel):
    chapter_id: uuid.UUID
    chapter_title: str
    status: Literal["pending", "accepted", "rejected"] = "pending"
    findings: list[ChapterAuditFinding]
    summary: str            # LLM 一句话总结（可选）
    degraded: bool = False  # LLM 检查是否降级（v1.0 已有；记录进 audit_logs）
    created_at: datetime
    confirmed_at: datetime | None = None
```

### 2.3 AuditLog（轻量记录实体，Q1=C 拍板；v1.4 增 findings 快照列）

**新表 audit_logs**（轻量：不含 findings 明细，可追溯的最小形态）。**v1.4（#1420）演进**：增 `findings` JSON 快照列 + 读口专用明细模型 `AuditLogDetail`——**列表端点仍返回下方轻量 `AuditLog`（响应形态零变化）**，仅 `GET /api/v1/audit-logs/{log_id}` 返回明细：

```python
class AuditRunStatus(StrEnum):        # v1.5（#1425）：审计任务运行状态
    """审计任务运行状态（执行态，与确认态 `status` 正交）."""
    RUNNING = "running"        # 已受理，后台执行中（findings 尚未落库）
    COMPLETED = "completed"    # 执行完成（findings/severity_summary 已落库；默认值）
    FAILED = "failed"          # 执行失败（error 落失败原因）

class AuditLog(BaseModel):
    """单次审计的轻量记录（可追溯；无 findings 明细）。"""
    id: uuid.UUID
    project_id: uuid.UUID
    chapter_id: uuid.UUID
    chapter_title: str          # 快照（章节改名后仍可读）
    status: Literal["pending", "accepted", "rejected"]
    # pending=已审计未确认 / accepted=已接受 / rejected=已拒绝
    run_status: AuditRunStatus = AuditRunStatus.COMPLETED
    # v1.5（#1425）：执行态（running/completed/failed）；默认 completed = 同步路径/历史行
    severity_summary: str       # 摘要：如 "1 error, 2 warnings, 0 info"（计数落库；running 时为空串）
    summary: str = ""           # LLM 一句话总结（可空）
    degraded: bool = False      # LLM 降级标记（可追溯审计质量）
    note: str = ""              # 拒绝原因/备注（用户确认时填写，可空）
    created_at: datetime        # 审计时间（异步语义下 = 受理时间）
    confirmed_at: datetime | None = None  # 确认时间（pending 为 None）
    error: str = ""             # v1.5（#1425）：执行失败原因（failed 时非空，其余为空串）

class AuditLogDetail(AuditLog):        # v1.4（#1420）：读口专用明细形态（列表端点不返回）
    """轻量记录 + findings 快照（与触发审计时的 POST 响应体同源）."""
    findings: list[ChapterAuditFinding] = []   # 旧记录/未落快照/执行中 → 空列表

class AuditLogORM(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    chapter_title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10))   # pending/accepted/rejected
    severity_summary: Mapped[str] = mapped_column(String(50))
    summary: Mapped[str] = mapped_column(Text, default="")
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    findings: Mapped[list] = mapped_column(LenientJSON(fallback=[]), default=list)  # v1.4（#1420）
    content_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    # v1.5（#1425）：章节内容 sha256 指纹（幂等去重键；空串 = 旧行/未记录；不出现在 API 响应）
    run_status: Mapped[str] = mapped_column(String(10), default="completed", server_default="completed")
    # v1.5（#1425）：执行态 running/completed/failed；server_default 'completed' 覆盖历史行
    error: Mapped[str] = mapped_column(Text, default="", server_default="")
    # v1.5（#1425）：失败原因（failed 时非空）
```

> **决策论证表**：为什么是「轻量记录」而非「完整快照」（Q1=C 拍板，2026-08-09）：① 验收标准「可追溯」的最小满足 = 何时审计过/结果如何/为何拒绝，findings 明细是**即时消费**（看报告当下就处理），历史回看明细场景弱（F25 教训：不为假设场景付全量成本）；② 完整 JSON 快照每章审计 × 100 章 = 千级冗余数据，单用户本地工具无此必要；③ `severity_summary`（计数）落库使「过去一周审计质量趋势」可查，覆盖实际追溯需求。FK ondelete 级联：项目/章节删除时审计记录随删（审计是附属记录，非独立资产）。**v1.4 演进（#1420）**：Q1=C 的「不存 findings 明细」前提被实测场景推翻——**客户端 300s 超时会让「即时消费」的明细彻底不可达**（352 章批审计命中 2.6%，重跑约 200–300 秒且新增重复记录），而快照成本远低于重跑成本（单章几 KB~几十 KB，352 章量级可接受）。故增 `findings` JSON 列 + 按记录 ID 读口：**摘要级列表（Q1=C 主体）不变**，明细改为「落库快照 + 只读按需取回」，不再要求客户端在响应窗口内消费。

### 2.4 AuditTriggerRequest / AuditConfirmRequest（DTO）

```python
class AuditTriggerRequest(BaseModel):
    """手动触发审计（API 请求体；自动触发无需 body）。"""
    include_static: bool = True    # 是否包含 F15 静态一致性委托

class AuditConfirmRequest(BaseModel):
    """用户确认（接受 / 拒绝）——GUI 与 CLI 共用同一契约（Q2=B 双入口）。"""
    action: Literal["accept", "reject"]
    note: str = ""                 # 拒绝原因/备注（可选，写入 audit_logs.note）

class AuditTriggerAccepted(BaseModel):    # v1.5（#1425）：POST /audit 的 202 响应体
    """审计触发受理响应（异步语义）——`{log_id, status}`，status = 任务执行态."""
    log_id: uuid.UUID              # 审计记录 ID（轮询/取结果的键）
    status: AuditRunStatus         # running（新任务）/ completed（幂等复用已完成记录）

class AuditRunInfo(BaseModel):            # v1.5（#1425）：GET /audit-logs/{log_id}/status 响应体
    """审计任务运行状态（轻量轮询读口，不含 findings）."""
    log_id: uuid.UUID
    run_status: AuditRunStatus
    status: Literal["pending", "accepted", "rejected"]
    degraded: bool = False
    error: str = ""
    chapter_id: uuid.UUID | None = None
    chapter_title: str = ""
    created_at: datetime
```

---

## 3. API 契约

### 3.1 端点总览（5 个）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/projects/{project_id}/chapters/{chapter_id}/audit` | **v1.5（#1425）202 异步语义**：受理审计并返回 `{log_id, status}`；检查在后台执行（原为阻塞 200 + 完整报告）。自动触发不经过此端点（见 §5.1） |
| POST | `/api/v1/projects/{project_id}/chapters/{chapter_id}/audit/confirm` | 用户确认（accept/reject，GUI/CLI 共用，Q2=B） |
| GET | `/api/v1/projects/{project_id}/audit-logs` | 审计记录查询（轻量列表，Q1=C 可追溯入口；v1.5 起每条含 `run_status`/`error`） |
| GET | `/api/v1/audit-logs/{log_id}` | **v1.4（#1420）** 审计记录明细（轻量记录 + findings 快照；超时后的恢复路径，**无项目段**——超时场景客户端只有 log id） |
| GET | `/api/v1/audit-logs/{log_id}/status` | **v1.5（#1425）** 任务运行状态轮询读口（轻量：`run_status`/`error`，不含 findings；无项目段） |

> **读口路径口径（v1.4）**：`{log_id}` 为审计记录 ID（UUID；兼容整数形态 = ORM 自增主键背书）。无项目段是刻意的——上游项目名/ID 在超时场景下可能不可得，且记录 ID 已全局唯一。记录不存在 → 404（§3.3）。服务取用**不走**需要 project_id 的装配路径（`_get_svc`），直接经 `get_chapter_audit_service(db)` 装配（该端点为只读，不消费 LLM）。

> 自动触发（章节状态进入 REVIEW/FINAL）由**前端在状态变更后调用** audit 端点（F2 状态变更端点既有，F34 不 MODIFY F2——前端编排，见 §5.1 注）。

### 3.2 请求/响应示例

```http
POST /api/v1/projects/1/chapters/2/audit
→ 202（v1.5 #1425 异步语义：立即返回受理凭证，不返回 findings）
{
  "log_id": "00000000-0000-0000-0000-0000000000a1",
  "status": "running"          # 新任务 running；幂等复用已完成记录时 completed
}

GET /api/v1/audit-logs/00000000-0000-0000-0000-0000000000a1/status
→ 200（v1.5 轮询读口：running → completed / failed；轻量，不含 findings）
{
  "log_id": "00000000-0000-0000-0000-0000000000a1",
  "run_status": "completed",
  "status": "pending",
  "degraded": false,
  "error": "",
  "chapter_id": "00000000-0000-0000-0000-000000000002",
  "chapter_title": "第 3 章 龙的苏醒",
  "created_at": "2026-08-09T10:00:00Z"
}

# 执行完成后结果（findings）经 v1.4 读口取回（与 202 的 log_id 同键）：
GET /api/v1/audit-logs/00000000-0000-0000-0000-0000000000a1
→ 200 AuditLogDetail（轻量记录 + run_status/error + findings 快照，示例见下）

POST /api/v1/projects/1/chapters/2/audit/confirm  {"action": "accept"}
→ 200 { "status": "accepted", "confirmed_at": "2026-08-09T10:05:00Z" }

GET /api/v1/projects/1/audit-logs?limit=20&offset=0
→ 200 {
  "total": 2,
  "logs": [
    {
      "id": "00000000-0000-0000-0000-0000000000a1",
      "chapter_id": "00000000-0000-0000-0000-000000000002",
      "chapter_title": "第 3 章 龙的苏醒",
      "status": "accepted",
      "severity_summary": "1 error, 2 warnings, 0 info",
      "summary": "本章整体符合设定，一处角色行为值得斟酌",
      "degraded": false,
      "note": "",
      "created_at": "2026-08-09T10:00:00Z",
      "confirmed_at": "2026-08-09T10:05:00Z"
    }
  ]
}
```

```http
GET /api/v1/audit-logs/00000000-0000-0000-0000-0000000000a1
→ 200（v1.4 #1420 读口：轻量记录元信息 + findings 快照）
{
  "id": "00000000-0000-0000-0000-0000000000a1",
  "project_id": "00000000-0000-0000-0000-000000000001",
  "chapter_id": "00000000-0000-0000-0000-000000000002",
  "chapter_title": "第 3 章 龙的苏醒",
  "status": "pending",
  "severity_summary": "1 error, 1 warnings, 0 info",
  "summary": "",
  "degraded": false,
  "note": "",
  "created_at": "2026-08-09T10:00:00Z",
  "confirmed_at": null,
  "findings": [
    {
      "check_type": "character_drift",
      "severity": "error",
      "message": "本章「李青焰」怒斥同伴，但角色档案性格为「温厚沉稳」，行为可能与人设冲突",
      "suggestion": "可改为隐忍不发，或先铺垫情绪积累",
      "ref_entity_id": "00000000-0000-0000-0000-00000000000c",
      "ref_entity_name": "李青焰",
      "context": "“够了！”李青焰猛地拍案而起，怒视众人……"
    }
  ]
}

GET /api/v1/audit-logs/999999
→ 404 { "detail": "审计记录不存在" }
```

### 3.3 异常映射表

| 场景 | HTTP 状态 | 错误 body（ADR-012 统一格式） | 抛出/捕获点 |
|------|-----------|-------------------------------|-------------|
| 项目不存在 / 已软删 | 404 | `{"detail": "Project not found"}` | 复用 F9 character_errors `ProjectNotFoundError`（陷阱 16：不导出到 ports/__init__.py，router 显式 except） |
| 章节不存在 / 不属于该项目 | 404 | `{"detail": "Chapter not found"}` | 复用 F14 extraction_errors 章节错误类（F16 双入口先例） |
| confirm 时无对应 pending 记录 | 422 | `{"detail": "No pending audit log"}` | service 校验（audit_logs 中该章最新记录非 pending） |
| 请求体非法（action 非 accept/reject） | 422 | Pydantic 校验错误 | DTO 层 |
| audit-logs 分页参数越界 | 422 | Pydantic 校验错误 | DTO 层 |
| 审计记录不存在（v1.4 读口 log_id 无效/查无） | 404 | `{"detail": "审计记录不存在"}` | service 抛 `AuditLogNotFoundError`（router 显式 except；非法 log_id 在解析层即 404，不进服务层） |
| LLM 分析失败 | 200 + degraded | 见 §5.3（降级策略：确定性检查仍返回，LLM 检查标记降级） | 不视为 HTTP 错误 |

> ⚠️ **LLM 失败语义（重要）**：LLM 漂移检查失败**不使整个审计失败**——报告返回时 LLM 类 findings 标记为降级（`degraded=true` + message 注明「LLM 分析暂不可用」），确定性检查（字数/静态）正常返回；audit_logs 记录 `degraded=true`（可追溯审计质量）。这使 API 错误面只有 404/422，LLM 失败走 200 + 降级标记。
>
> ⚠️ **v1.5 异步语义下的错误面（#1425）**：`POST .../audit` 只承担「校验 + 受理」——项目/章节不存在仍 **404**（受理前校验），请求体非法仍 **422**（DTO 层），受理后立即 **202**。**后台执行阶段失败不进 HTTP 错误面**：失败落 `audit_logs.run_status='failed'` + `error`（经 `/status` 或列表/明细读口可见）。故 202 的 `status` 语义 = 任务执行态（`running`/`completed`/`failed`），与 `AuditLog.status`（确认态 pending/accepted/rejected）**正交**。既有各消费面（CLI/GUI/MCP）在 202 后**自行轮询**至终态（CLI `--wait` 默认、GUI/MCP 内部轮询）。

---

## 4. CLI 命令签名

F7 全局约定：`--json` 信封、退出码 0/1/2。F34 新增 `inkflow audit chapter` 子命令（挂入既有 audit 组，F15 CLI 不动）。**v1.1 新增 `--confirm`（Q2=B 拍板：单 CLI 用户无需 GUI 即可完成确认闭环）**。

```text
inkflow audit chapter [<chapter>] --project <name|id> [--include-static] [--wait|--no-wait] [--confirm accept|reject] [--note TEXT] [--log <log_id>] [--json]

参数:
  chapter                  章节名称或 ID（--history / --log 模式下省略）
  --project, -p            项目名称或 ID（**v1.4：--log 模式可省略**；其余模式必填）
  --include-static         包含 F15 静态一致性委托（默认含）
  --wait / --no-wait       **v1.5（#1425）** 触发审计时是否等待完成：默认 `--wait`
                           （内部轮询 `/status` 至终态后输出报告，UX 与同步版一致）；
                           `--no-wait` 立即返回 `{log_id, status}`（批场景/自管轮询）
  --confirm                确认动作：accept（接受）/ reject（拒绝）（v1.1，可省略）
  --note, -n               确认备注（拒绝原因等，写入 audit_logs.note；与 --confirm 搭配使用）
  --log                    **v1.4（#1420）** 按审计记录 ID 取回明细（含 findings）；与
                           chapter / --confirm / --history 互斥；模式下 -p 被忽略
  --json                   输出 JSON 信封（data = 审计记录明细（--wait 取回）/ 受理凭证
                           （--no-wait）/ 确认结果 / 记录列表 / 记录明细）

用法:
  触发审计（默认 --wait）: inkflow audit chapter <章节> -p <项目>          → 输出报告
  仅受理（不等待）:        inkflow audit chapter <章节> -p <项目> --no-wait → 输出 {log_id, status}
  审计 + 确认:      inkflow audit chapter <章节> -p <项目> --confirm accept
                    inkflow audit chapter <章节> -p <项目> --confirm reject --note "人设需再打磨"
  查审计记录:       inkflow audit chapter --history -p <项目>         → 轻量记录列表（v1.1 Q1=C；v1.5 含 run_status）
  取回明细:         inkflow audit chapter --log <记录ID>              → 记录元信息 + findings（v1.4）
                    （异步任务完成后取回结果的路径 = --history 找 id → --log <id>）

成功: 退出 0；人类可读输出按 severity 排序打印 findings；--json 输出记录明细/受理凭证/确认结果/记录列表
失败: 项目/章节/记录不存在 → 退出 1；用法错误 → 退出 2；--confirm 时无 pending 记录 → 退出 1；
      --wait 轮询到 run_status=failed（或超时）→ 退出 1（错误信封含 log_id 恢复指引）
```

> v1.4 说明（#1420）：`--log` 是**超时恢复路径**——先 `--history -p <项目>` 找到目标记录的 id，再 `--log <id>` 取回明细（`--history` 只给 `severity_summary`，不足以复核）。`--log` 与触发/确认/列表互斥（一次一个动作）；缺 `-p` 且无 `--log` → 用法错误（退出 2）。

> v1.5 说明（#1425，**CLI 契约演进**）：触发路径不再直接返回报告——POST 得 202 `{log_id, status}` 后，`--wait`（默认）轮询 `GET /audit-logs/{log_id}/status`（间隔 1s，总预算 `_POLL_TOTAL_TIMEOUT`）至 `completed`/`failed`，再经 `GET /audit-logs/{log_id}` 取回记录明细并以**与今天一致的人类输出**打印 findings（`--json` 的 data 因此由 `ChapterAuditReport` 变为 `AuditLogDetail`——属破坏性变更，见 PR 清单）。`--no-wait` 则直接以受理凭证为 `data` 输出。轮询超时/`failed` → 退出 1（错误消息含 `--log <id>` 恢复指引）。`--history` / `--log` / `--confirm` 行为不变（`--history` 输出行增补 `run_status`）。轮询只在触发路径生效，`--no-wait` 与之互斥语义由「不等待」表达（不额外禁用）。

> v1.1 说明：`--confirm` 与 `--history` 互斥（一次一个动作）；`--note` 仅与 `--confirm reject` 有业务意义（accept 也可留备注，如「改过再确认」），无 `--confirm` 时 `--note` 报用法错误（退出 2）。

---

## 5. 章节审计模式（关键差异：LLM 漂移检查 + 用户确认工作流 + 轻量记录）

> ⚠️ **本节是 F34 与既有样板的核心差异点**：F15 §5 是「确定性规则引擎」（档案 vs 档案），F16 §5 是「文本统计 + 可选 LLM 分析」；本模块 §5 是**「确定性检查 + LLM 漂移分析 + 轻量记录 + 用户确认」四阶段工作流**——LLM 分析是主体（非可选增强），用户确认是新增环节，audit_logs 是新增持久化。

### 5.1 模式总览

```text
 ┌─────────────────────────────────────────────────────────────┐
 │ ChapterAuditService.audit(project_id, chapter_id,            │
 │                           include_static: bool)              │
 └──────────────────────────┬──────────────────────────────────┘
                            ▼
 ① 校验项目 + 章节存在（F1 ProjectRepository.get / F2 ChapterRepository.get_chapter）
 ② 字数检查（确定性）: chapter.word_count vs 目标
    - 目标 = ProjectConfig.default_words（F1，章节目标字数）
    - < 80% → INFO；> 120% → INFO（提示），不设 ERROR
 ③ 并行拉取 LLM 检查输入:
    - 章节全文（chapter.content，截断到模型上下文预算，见 §5.4）
    - F9 CharacterRepository.list(pid)（活动角色）
    - F10 WorldRepository.list(pid)（活动条目）
 ④ 人设漂移检查（LLM）: 章节文本 + 角色档案 → findings（character_drift）
 ⑤ 设定漂移检查（LLM）: 章节文本 + 世界观条目 → findings（setting_drift）
 ⑥ 静态一致性（include_static=true 时）: 委托 F15 AuditService.audit(project_id)
    → 过滤出与本章相关 findings（source_chapter_id == chapter_id 或章节级），
      转映射为 static_consistency 类型（§5.5）
 ⑦ 组装 ChapterAuditReport（status=pending，degraded 标记）→ 返回
 ⑧ 落 audit_logs 轻量记录（Q1=C）+ **v1.4 findings 快照**: status=pending +
     severity_summary（findings 计数）+ summary + degraded + findings（与本次返回的
     报告同源）→ 可追溯，且客户端超时后可按记录 ID 取回（§3.1 读口）
 ── confirm 阶段 ──
 ⑨ confirm(project_id, chapter_id, action, note):
    - 校验该章最新 audit_logs 记录为 pending（无 → 422）
    - 更新 status=accepted/rejected + confirmed_at + note → 终态
    - GUI 与 CLI 双入口共用此服务方法（Q2=B 单一真相源）
```

**v1.5（#1425）异步语义下的服务编排**（HTTP 触发路径，上图 ①-⑨ 收敛为 `_run_checks` 纯计算段）：

```text
 ┌─────────────────────────────────────────────────────────────┐
 │ submit(project_id, chapter_id, include_static)  ← POST 端点 │
 └──────────────────────────┬──────────────────────────────────┘
   ① 校验项目 + 章节存在（同 audit ① ②；404 语义，受理前）
   ② 计算 content_hash = sha256(chapter.content)
   ③ find_reusable(chapter, hash, stale_before=now-REUSE_WINDOW)
      - 命中「运行中（窗口内）」或「已完成 + pending（含 degraded）」→ 复用，不新增记录
      - 未命中 → 落一条 run_status='running'（status='pending'，findings=[]）记录
   ④ 返回 (AuditLog, created: bool)
 ── HTTP 层 ──
   ⑤ 202 {log_id, status=run_status}
   ⑥ created=True 时 spawn_background_task(run_audit_job(...))（fire-and-forget）
 ── 后台任务 ──
   ⑦ run_audit_job(pid, cid, log_id, include_static):
      - 复用 audit 的 ①-⑧ 计算段（`_run_checks`）→ ChapterAuditReport
      - 成功 → complete(log_id, findings=..., severity_summary=..., summary=..., degraded=...)
               （run_status='completed'）
      - 异常 → fail(log_id, error=...)（run_status='failed'，绝不透传进程外）
```

**v1.5 要点**：① **状态承载复用 `audit_logs` 本表**（不新建表）——一条记录即一次「审计任务 + 其确认状态」；执行态（`run_status`）与确认态（`status`）正交。② **幂等去重键** = `(chapter_id, content_hash)` + 复用谓词（见 §7 E8）；确认后的记录不再被复用（用户已决策的审计周期已闭合）。③ **同步 `audit()` 保持不变**（F44 写作链 `_audit_bridge` / 卷级 `book_pipeline` / agent `reader_tools` 三处**进程内**调用仍走同步路径，落 `run_status='completed'`）——异步只改变 **HTTP 触发面**。④ 后台任务先例 = F44 #456（`infrastructure/background/tasks.py`），状态落表使进程崩溃后**状态可观测**（不再「不知道任务是否在跑」）。

**模式要点**:
1. **LLM 主体 + 确定性兜底**：字数/静态是确定性检查（快、可断言），人设/设定漂移是 LLM 分析（慢、非确定）——两类 findings 同报告不同性质，测试策略分层（§9）
2. **轻量记录可追溯**：audit_logs 只存摘要（severity 计数 + summary + degraded），findings 明细瞬态——追溯「何时/结果/为何拒绝」，不存快照（Q1=C）。**v1.4（#1420）例外**：findings 另落一份 JSON 快照列供按记录 ID 读回（列表响应仍只输出摘要）——条目形态仍是轻量，删掉的是「明细不可恢复」这一副作用
3. **确认双入口闭环**：GUI（弹层）+ CLI（--confirm）→ 同一 service 方法 → audit_logs 状态更新；确认不改变任何业务数据（无副作用，D3）
4. **LLM 降级不阻塞**：LLM 失败 → 200 + degraded 标记（§5.3），确定性检查照常；degraded 落记录可追溯

### 5.2 LLM 漂移检查（人设 / 设定）

**模板**（`infrastructure/llm/templates/`，F5 PromptManager str.replace 渲染，陷阱 12）：

```yaml
chapter_audit_drift.yaml:
  人设漂移: 系统提示「你是小说一致性审校。比对章节文本与角色档案，
            找出角色行为/言语/心理与档案描述冲突之处。只报明确冲突或
            明显疑似，不报细枝末节。输出 JSON: findings[{character, issue,
            severity, suggestion, context}]」
  设定漂移: 同构，比对世界观条目
```

- **输入预算**：章节全文 + 档案列表可能超上下文——**按相关性截断**：角色/设定条目按名称匹配章节中出现的词优先取（F14 chunking 先例），预算上限 ~4000 token（§5.4）
- **输出解析**：LLM 返回 JSON 数组 → Pydantic 校验 → ChapterAuditFinding（非法 JSON → 该检查降级标记 + loguru，不炸）
- **重试**：JSON 解析失败重试 1 次（F9 提取管线先例）；仍失败 → 降级
- **确定性声明**：LLM findings **不承诺确定性**（模型输出可变）——测试用 Fake LLM 固定返回（F14 Fake 注入先例）；报告排序用 `(severity, check_type, ref_entity_name)` 稳定键（F15 教训）

### 5.3 LLM 失败降级策略

| 失败形态 | 行为 |
|----------|------|
| 模型调用异常（超时/网络/4xx/5xx） | 该检查项 findings 为空 + `degraded: true` + message 注明；**HTTP 仍 200**；audit_logs.degraded=true |
| JSON 解析失败（重试 1 次后） | 同上降级 |
| 档案为空（项目无角色/无设定） | 对应检查项跳过（不报错——没档案可比对） |

### 5.4 上下文预算与截断

- 章节全文 > 8000 字符 → 按段落取首段 + 末段 + 中间均匀采样（最多 ~60% 内容，LLM 提示「已截断，关注节选」）
- 角色/设定条目：按「章节文本中出现的名称」优先（jieba 分词 + 名称集合匹配，F16 分词复用），最多取 20 条 × 每条 ≤500 字符
- 预算常量集中在 `_audit_context.py`（可单测，防魔法数字散落）

### 5.5 静态一致性委托（F15）

- 调用 `F15 AuditService`（注入委托，F15 spec 先例「委托 TimelineService.check_consistency」同款）
- F15 是全项目审计 → F34 过滤**与本章相关**的 findings：`source_chapter_id == chapter_id` 的（R-X1 类）或时间线事件挂本章的；与本章无关的静态 findings **不展示**（章节审计聚焦本章）
- 映射：F15 finding → `ChapterAuditFinding(check_type=static_consistency, severity=映射, ...)`，保留 F15 finding 的 rule_id 到 `suggestion` 前缀（追溯）

### 5.6 自动触发（写完一章）

- **触发点**：F2 章节状态变更为 REVIEW 或 FINAL（`PATCH /api/v1/projects/{pid}/chapters/{cid}` 既有端点）
- **实现方式（零跨模块 MODIFY）**：前端在状态变更成功后调用 `POST .../audit`（前端编排，F34 不挂 F2 service 钩子——F15 零 MODIFY 纪律）；CLI 用户可手动 `inkflow audit chapter`
- 未来增强（#208 后续）：F22 AI 自动维护设置开启时，审计确认（accept）可作为 F22 索引增量触发的增强信号——**本 spec 不实现该联动**（F22 v1.1 已声明不阻塞），留 §10 演进

### 5.7 章节审计型 vs 既有样板：差异对照表

| 维度 | F15 审计 | F16 风格分析 | **F34 章节审计** |
|------|----------|--------------|------------------|
| 分析对象 | 档案间引用 | 章节文本统计 | **章节文本 vs 档案（漂移）** |
| 分析主体 | 确定性规则 | 统计 + 可选 LLM | **LLM 主体 + 确定性兜底** |
| 用户确认 | 无 | 无 | **有（GUI + CLI 双入口）** |
| 新实体表 | 无 | 无 | **1 张轻量表 audit_logs（Q1=C）** |
| 新 API | 1 只读端点 | 1 端点 | **5 端点（触发（v1.5 起 202 异步）+ 确认 + 记录列表 + v1.4 记录明细读口 + v1.5 任务状态轮询）** |
| 跨模块 MODIFY | 无 | 无 | **无（前端编排自动触发）** |
| LLM 失败语义 | N/A | 可选降级 | **降级不阻塞（200 + degraded 标记落记录）** |

---

## 6. 检查项规则明细

| 检查项 | 判定 | 严重级别 | 说明 |
|--------|------|----------|------|
| word_count | `word_count < target * 0.8` | INFO | 低于目标 20% 提示 |
| word_count | `word_count > target * 1.2` | INFO | 超出目标 20% 提示 |
| character_drift | LLM 判定明确冲突 | ERROR | 如「畏火」角色纵火 |
| character_drift | LLM 判定疑似冲突 | WARNING | 如行为与人设不符但可解释 |
| setting_drift | LLM 判定明确矛盾 | ERROR | 如世界观「灵气枯竭」却写灵气充沛 |
| setting_drift | LLM 判定疑似矛盾 | WARNING | |
| static_consistency | F15 finding 映射 | 按 F15 原级别 | 仅本章相关 |

- 排序键：`(severity: error<warning<info, check_type, ref_entity_name)`——severity 降序（error 在前），其余稳定
- `severity_summary` 生成：`"{n_error} error, {n_warning} warnings, {n_info} info"`（落 audit_logs，§2.3）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| E1 | 项目/章节不存在 | 404（§3.3） |
| E2 | 项目无角色档案 | character_drift 跳过（§5.3） |
| E3 | 项目无世界观条目 | setting_drift 跳过 |
| E4 | 章节为空（无内容） | 报告仅字数检查（0 字 INFO）+ 提示「章节为空」，LLM 检查跳过 |
| E5 | LLM 超时/失败 | 200 + degraded 标记 + audit_logs.degraded=true（§5.3） |
| E6 | LLM 返回非法 JSON | 重试 1 次 → 仍失败降级 |
| E7 | 章节超长 | 上下文截断（§5.4），报告注明「已截断」 |
| E8 | 重复触发审计 | **v1.5（#1425）修订**：同章**同内容**重复触发 → **复用**既有记录（不新增）——复用谓词 = 「`run_status='running'` 且在复用窗口（`_REUSE_STALE_SECONDS`）内」**或**「`run_status='completed'` 且 `status='pending'`」（**含 `degraded=true`**：降级同样是「已完成的一次结果」，不复用会让「无可用模型 / LLM 抖动」环境下每次重试都新增一条无法区分的记录——正是本 issue 要根治的形态，见 §9.2-15 实测）；内容变更（章节正文改动）/ 上一轮已确认（accepted/rejected）/ 上一轮 `failed` → **新记录**（历史保留，`--history` 以 `run_status` + `created_at` 区分尝试）。同步路径 `audit()`（F44 写作链等进程内调用）**保持每次一条**（不经去重） |
| E9 | confirm 时该章无 pending 记录 | 422（§3.3）——已确认过/从未审计过 |
| E10 | 章节状态未到 REVIEW 就手动审计 | 允许（作者可随时自检，不强制状态门槛） |
| E11 | 修改后重审 | 改章节 → 重新触发 audit（新记录）；旧记录 rejected/历史保留 |
| E12 | CLI --confirm 但无 pending 记录 | 退出 1（error 提示「该章无待确认审计」） |
| E13 | CLI --note 无 --confirm | 退出 2（用法错误） |
| E14 | 章节/项目删除 | audit_logs FK 级联删除（§2.3，附属记录随删） |
| E15 | audit-logs 查询分页 | limit 默认 20 最大 100，offset ≥0（422 越界） |
| E16 | **v1.4（#1420）** 按记录 ID 取明细，记录不存在 | 404「审计记录不存在」（service 抛 `AuditLogNotFoundError`；非法 log_id 解析层即 404） |
| E17 | **v1.4（#1420）** 旧库（#1420 前建的 audit_logs 无 findings 列） | lifespan 迁移补列（`ensure_audit_logs_findings_column`，存量行默认 `'[]'`）→ 读口返回空 findings 列表（不 404、不崩溃） |
| E18 | **v1.4（#1420）** 客户端超时（响应丢弃）后想复核明细 | `--history -p <项目>` 取记录 ID → `audit chapter --log <id>` / `GET /api/v1/audit-logs/{log_id}` 取回（无需重跑，不新增记录） |
| E19 | **v1.5（#1425）** 后台执行失败（DB/LLM 未捕获异常等） | 记录置 `run_status='failed'` + `error`（进程内异常绝不透传到 HTTP）；客户端轮询/`--wait` 得到终态失败 → 退出 1 / 错误信封 |
| E20 | **v1.5（#1425）** 执行中的记录被读口/列表读取 | `run_status='running'`、`findings=[]`、`severity_summary=''`——读口**不报错**（明细暂空，`/status` 给进度） |
| E21 | **v1.5（#1425）** 内核崩溃遗留 `running` 行 | 超过复用窗口（`_REUSE_STALE_SECONDS`）后**不再复用**（不阻塞重审）；旧行**保持 `running`**（其余实例可能仍在跑，遵循 #1317「不误伤」纪律）——`--history` 可见，`/status` 仍报 running，客户端轮询超时后经 `--log` 查看 |
| E22 | **v1.5（#1425）** 复用命中已完成记录（幂等重跑） | 202 返回 `status='completed'` + 同一 `log_id`；**不启动**后台任务、不新增记录；`--wait` 直接取回该记录明细 |
| E23 | **v1.5（#1425）** 旧库（v1.5 前建的 audit_logs 无新列） | lifespan 迁移补列（`ensure_audit_logs_async_columns`；`run_status` 默认 `'completed'`、`content_hash`/`error` 默认空串）→ 历史行读作「已完成」；`content_hash=''` 永不参与去重命中 |

---

## 8. 文件结构

### 8.1 CREATE/MODIFY 清单（对照真实源码树 `backend/src/inkflow/`）

| 类型 | 路径 | 说明 |
|------|------|------|
| CREATE | `domain/models/chapter_audit.py` | AuditCheckType / AuditSeverity / ChapterAuditFinding / ChapterAuditReport / AuditLog / AuditTriggerRequest / AuditConfirmRequest（§2） |
| CREATE | `domain/ports/chapter_audit_errors.py` | 模块专属错误（NoPendingAuditError 等）；ProjectNotFoundError/ChapterNotFoundError 复用既有类（§3.3，陷阱 16） |
| CREATE | `domain/ports/audit_log_repository.py` | 自有端口（F15 audit_repo 先例）：add / latest_pending / confirm / list（§8.2） |
| CREATE | `domain/services/chapter_audit_service.py` | ChapterAuditService：audit() 编排 + confirm() + 降级处理 + 记录落库（§5.1） |
| CREATE | `domain/services/_audit_context.py` | 上下文预算/截断/条目选取（jieba 名称匹配，§5.4）——`_style_analyzer.py` 先例 |
| CREATE | `domain/services/_audit_prompts.py` | LLM 提示词组装（人设/设定两模板，§5.2）——`_style_llm_analyzer.py` 先例 |
| CREATE | `infrastructure/llm/templates/chapter_audit_drift.yaml` | LLM 模板（F5 PromptManager str.replace 渲染） |
| CREATE | `infrastructure/database/models/audit_log.py` | AuditLogORM（§2.3；`Base.metadata.create_all` 自动建表，零迁移） |
| CREATE | `infrastructure/database/repositories/audit_log_repo.py` | SQLiteAuditLogRepository（轻量 CRUD） |
| CREATE | `api/routers/chapter_audit.py` | POST audit / POST confirm / GET audit-logs（§3） |
| CREATE | `cli/commands/audit_chapter.py` | `inkflow audit chapter` 子命令（含 --confirm/--history/--note，§4；挂入 F15 audit 组） |
| CREATE | `backend/tests/unit/domain/models/test_chapter_audit_models.py` | DTO/枚举校验 |
| CREATE | `backend/tests/unit/domain/services/test_chapter_audit_service.py` | 编排（mock repos + **Fake LLM 固定返回**）——字数判定/降级/跳过/排序 |
| CREATE | `backend/tests/unit/domain/services/test_audit_context.py` | 截断/预算/名称匹配 |
| CREATE | `backend/tests/unit/infrastructure/database/test_audit_log_repo.py` | audit_logs 轻量记录 CRUD（真 SQLite 内存库） |
| CREATE | `backend/tests/unit/domain/services/test_audit_service_confirm.py` | confirm 状态机（accept/reject/重复/无 pending 422） |
| CREATE | `backend/tests/unit/domain/services/test_chapter_audit_llm.py` | LLM 解析（Fake 返回 JSON → 映射；非法 JSON 重试 → 降级） |
| CREATE | `tests/api/test_chapter_audit_api.py` | API 端点（404/422/200 降级/confirm/audit-logs） |
| CREATE | `tests/cli/test_cli_audit_chapter.py` | CLI（触发/--confirm/--history/--note 校验/--json/404） |
| CREATE | `frontend/packages/renderer/src/...`（Q3=C 最小版，实现会话细化） | 章节页审计按钮 + 报告弹层 + accept/reject（F19 渲染层接线） |
| MODIFY | `api/app.py` | `app.include_router(chapter_audit.router)` + import（1 行） |
| MODIFY | `api/deps.py` | ChapterAuditService 装配（注入 project/chapter/character/world repo + F15 AuditService + LLM 客户端 + audit_log_repo） |
| MODIFY | `cli/commands/audit.py` | 注册 audit_chapter 子命令（1-2 行） |
| MODIFY | `.github/workflows/ci.yml` | `tests/cli/test_cli_audit_chapter.py` 追加 integration-cli-backend + `tests/api/test_chapter_audit_api.py` 追加对应 integration job（陷阱 13/15） |

> ⚠️ 反向核对：上表 CREATE 均已核实不存在、MODIFY 均已确认存在（2026-08-09）；前端文件清单（Q3=C 最小版）在实现会话细化——先读 F19 渲染层结构（writing 页/store 模式）再落具体路径。

> **v1.4（#1420）增量清单**（相对上表的改动）：
> - CREATE `core/migrations_chapter_audit.py` — `ensure_audit_logs_findings_column`（幂等补列）
> - MODIFY `core/database.py` — re-export + `__all__`（迁移 wiring 门禁注册集口径）
> - MODIFY `api/app.py` — lifespan 迁移链接线（`await conn.run_sync(ensure_audit_logs_findings_column)`）
> - MODIFY `infrastructure/database/models/audit_log.py` — `findings` JSON 列（LenientJSON）
> - MODIFY `domain/models/chapter_audit.py` — 新增 `AuditLogDetail`（读口形态；`AuditLog` 本身零变化）
> - MODIFY `domain/ports/audit_log_repository.py` — `add(*, findings=...)` + `get(log_id)`
> - MODIFY `domain/ports/chapter_audit_errors.py` — 新增 `AuditLogNotFoundError`（404 语义）
> - MODIFY `infrastructure/database/repositories/audit_log_repo.py` — findings 落库/读回（`_log_orm_to_domain` 不变 → 列表路径不变）
> - MODIFY `domain/services/chapter_audit_service.py` — `audit()` 传 findings + `get_log()`
> - MODIFY `api/routers/chapter_audit.py` — `GET /audit-logs/{log_id}` + 404 映射
> - MODIFY `cli/commands/audit_chapter.py` — `--log` 模式（`-p` 变可选）
> - MODIFY `infrastructure/http/client.py` — TIMEOUT 文案对齐（方案 1）
> - CREATE 测试：`backend/tests/unit/core/test_audit_logs_findings_migration_1420.py`、`backend/tests/unit/domain/models/test_chapter_audit_detail_1420.py`、`backend/tests/unit/infrastructure/database/test_audit_log_findings_repo_1420.py`、`backend/tests/unit/domain/services/test_chapter_audit_findings_persist_1420.py`、`backend/tests/unit/infrastructure/http/test_timeout_copy_1420.py`、`tests/api/test_chapter_audit_log_detail_1420.py`、`tests/cli/test_cli_audit_chapter_log_1420.py`
> - 契约生成物（同 PR 刷新）：`ci_cd/openapi_snapshot.json` + `frontend/packages/renderer/src/api/schema/openapi.d.ts`

> **v1.5（#1425）增量清单**（相对上表的改动）：
> - MODIFY `domain/models/chapter_audit.py` — 增 `AuditRunStatus` 枚举 + `AuditLog.run_status`/`error` + DTO `AuditTriggerAccepted` / `AuditRunInfo`
> - MODIFY `infrastructure/database/models/audit_log.py` — 三列（`content_hash` / `run_status` / `error`，均带 `server_default`）
> - CREATE（并入既有文件）`core/migrations_chapter_audit.py` — `ensure_audit_logs_async_columns`（幂等补三列）
> - MODIFY `core/database.py` — re-export + `__all__`（迁移 wiring 门禁注册集口径）
> - MODIFY `api/app.py` — lifespan 迁移链接线（`await conn.run_sync(ensure_audit_logs_async_columns)`）
> - MODIFY `domain/ports/audit_log_repository.py` — `add(*, findings=, content_hash=)` + `find_reusable` / `complete` / `fail` / `get_status`
> - MODIFY `infrastructure/database/repositories/audit_log_repo.py` — 新列读写 + 复用谓词查询（`running` 窗口内 ∪ `completed`+`pending`+未降级）
> - MODIFY `domain/services/chapter_audit_service.py` — 抽出 `_run_checks`（纯计算）+ 新增 `submit` / `run_audit_job` / `get_status`；`audit()` 保持同步语义（三处进程内调用零改动）
> - MODIFY `api/routers/chapter_audit.py` — POST 改 `status_code=202` + `spawn_background_task` + 新增 `GET /audit-logs/{log_id}/status`
> - MODIFY `cli/commands/audit_chapter.py` — `--wait/--no-wait` + 轮询 helper（`_poll_until_done`）
> - MODIFY `mcp/tools/operation_tools.py` + `mcp/tools/schemas.py` — `audit` 增 `action="result"`（按 `log_id` 取结果）+ 审计域专属 TIMEOUT hint（`_hint_for_audit`）；审计 chapter POST 不再带 300s 覆盖
> - MODIFY `frontend/packages/renderer/src/api/audit.ts` — 202 + 内部轮询（`pollAuditStatus` / `fetchAuditReport`；`auditChapter` 签名不变，UI 行为不变）
> - CREATE 测试：`backend/tests/unit/core/test_audit_logs_async_migration_1425.py`、`backend/tests/unit/domain/models/test_chapter_audit_run_status_1425.py`、`backend/tests/unit/infrastructure/database/test_audit_log_async_repo_1425.py`、`backend/tests/unit/domain/services/test_chapter_audit_async_1425.py`、`tests/api/test_chapter_audit_async_1425.py`、`tests/cli/test_cli_audit_async_1425.py`
> - MODIFY 测试（契约演进）：`tests/api/test_chapter_audit_api.py`（POST 200 → 202 + `submit` 契约）、`tests/cli/test_cli_audit_chapter.py`、`backend/tests/unit/mcp/test_mcp_llm_timeout_926.py`（C-R5 审计 POST 去 300s 覆盖 + 审计域 hint 独立断言）、`frontend/packages/renderer/src/api/audit.test.ts`
> - 契约生成物（同 PR 刷新）：`ci_cd/openapi_snapshot.json` + `frontend/packages/renderer/src/api/schema/openapi.d.ts`

### 8.2 注入依赖（ChapterAuditService 构造签名）

零跨模块 MODIFY 的关键：注入既有 Protocol + 委托 F15 + 自有 audit_log 端口：

```python
class ChapterAuditService:
    def __init__(
        self,
        project_repo: ProjectRepositoryProtocol,
        chapter_repo: ChapterRepositoryProtocol,
        character_repo: CharacterRepositoryProtocol,
        world_repo: WorldRepositoryProtocol,
        audit_service: AuditService,          # F15 委托（静态一致性）
        llm_client: ChatOpenAIProtocol,        # F5 LLM（Fake 注入测试）
        audit_log_repo: AuditLogRepositoryProtocol,  # 自有端口（Q1=C 轻量记录）
        outline_repo: OutlineRepositoryProtocol | None = None,  # #1266 大纲符合度 + 后章大纲
        summary_service: SummaryService | None = None,          # #1266 前章摘要（#1253 缓存）
    ) -> None: ...
```

> **#1266 新增两参数均可选（None = 跳过对应 check）**：旧装配点零改动即兼容（缺省跳过而非报错）；
> 生产装配点 `api/deps_chapter_audit.py` 已注入 `SQLiteOutlineRepository` + `get_summary_service(db)`。

> LLM 客户端注入走 F5 既有 Protocol（`domain/ports/llm_client.py`），不新建 LLM 端口（F16 `_style_llm_analyzer` 先例）；audit_log_repo 是**本模块自有端口**（F15 audit_repo 先例：业务表之外的补充持久化，不 MODIFY 任何既有 Protocol）。

---

## 9. 测试策略

沿用 ADR-018 三层目录 + pytest markers；LLM 测试全用 **Fake LLM 注入**（F14/F16 先例；真实 LLM 走 ADR-026 e2e-ai-backend label 触发验证）。

### 9.1 测试层次

| 层 | 文件 | 内容 |
|----|------|------|
| 单元 | `backend/tests/unit/domain/services/test_chapter_audit_service.py` | 编排（mock repos + Fake LLM）：字数判定边界（79%/80%/120%/121%）、无档案跳过、降级、排序 |
| 单元 | `backend/tests/unit/domain/services/test_audit_context.py` | 截断预算、名称匹配（jieba）、超长章节采样 |
| 单元 | `backend/tests/unit/domain/services/test_chapter_audit_llm.py` | LLM JSON 解析、非法 JSON 重试、重试后降级 |
| 单元 | `backend/tests/unit/infrastructure/database/test_audit_log_repo.py` | audit_logs CRUD（真 SQLite）：add/latest_pending/confirm/list 分页/FK 级联 |
| 单元 | `backend/tests/unit/domain/services/test_audit_service_confirm.py` | confirm 状态机（accept/reject/重复 422/无 pending 422/note 落库） |
| API | `tests/api/test_chapter_audit_api.py` | 404（项目/章节）/422（confirm 无 pending）/200 降级 /200 确认 /audit-logs 分页 |
| CLI | `tests/cli/test_cli_audit_chapter.py` | 触发输出、--confirm accept/reject、--note 校验、--history、--json 信封、404/422 错误 |
| E2E | 前端最小版（Q3=C） | GUI 展示 findings + accept/reject 点击闭环（章节页） |
| 单元 | `backend/tests/unit/core/test_audit_logs_findings_migration_1420.py` | **v1.4** findings 列迁移三形态（旧库补列/新库 no-op/无表 no-op） |
| 单元 | `backend/tests/unit/domain/models/test_chapter_audit_detail_1420.py` | **v1.4** `AuditLog` 字段集不变（反例守护）+ `AuditLogDetail` 边界 |
| 单元 | `backend/tests/unit/infrastructure/database/test_audit_log_findings_repo_1420.py` | **v1.4** findings 落库/读回往返 + `get` 未命中 None + 列表/确认路径仍轻量 |
| 单元 | `backend/tests/unit/domain/services/test_chapter_audit_findings_persist_1420.py` | **v1.4** audit 落库 findings == 响应体 + `get_log` 404 语义 |
| 单元 | `backend/tests/unit/infrastructure/http/test_timeout_copy_1420.py` | **v1.4** TIMEOUT 文案不含 list/get（回归断言） |
| API | `tests/api/test_chapter_audit_log_detail_1420.py` | **v1.4** 读口 200（含空 findings）/404（缺失·非法·整数形态）/500 |
| CLI | `tests/cli/test_cli_audit_chapter_log_1420.py` | **v1.4** `--log` 人类输出/`--json`/无 `-p`/互斥退出 2/404 退出 1 |
| 单元 | `backend/tests/unit/core/test_audit_logs_async_migration_1425.py` | **v1.5** 三列迁移形态（旧库补列 + 默认值 `completed`/空串；新库 no-op；无表 no-op） |
| 单元 | `backend/tests/unit/domain/models/test_chapter_audit_run_status_1425.py` | **v1.5** `AuditRunStatus` 取值 + `AuditLog.run_status` 默认 `completed`/`error` 默认 `""` + `AuditLogDetail` 继承 + 反例守护（D11 字段集只增不改） |
| 单元 | `backend/tests/unit/infrastructure/database/test_audit_log_async_repo_1425.py` | **v1.5** 新列往返（`content_hash`/`run_status`/`error`）+ `find_reusable` 六形态 + `complete`/`fail`/`get_status` |
| 单元 | `backend/tests/unit/domain/services/test_chapter_audit_async_1425.py` | **v1.5** `submit` 新建 running 记录 / 幂等复用（不新增）/ 404 透传；`run_audit_job` 完成落库 == 报告 findings / 异常 → `failed` + error |
| API | `tests/api/test_chapter_audit_async_1425.py` | **v1.5** POST → 202 `{log_id, status}` + 立即返回 + 后台任务被派发（created 才派发）；复用 → 202 completed 且不派发；404 语义不变；`/status` 200（running/completed/failed）/404 |
| CLI | `tests/cli/test_cli_audit_async_1425.py` | **v1.5** 默认 `--wait` 轮询至 completed 后人类输出报告；`--no-wait` 输出受理凭证；`run_status=failed` → 退出 1；`--json` 信封形态 |

### 9.2 关键场景

1. **漂移命中**：Fake LLM 返回人设冲突 → 报告含 ERROR finding + 正确 ref_entity
2. **LLM 降级**：Fake LLM 抛异常 → 200 + degraded 标记 + 字数检查仍在 + audit_logs.degraded=true
3. **记录落库（Q1=C）**：audit 后 audit_logs 新增一条（severity_summary 正确）；重复审计 → 两条记录
4. **确认闭环（Q2=B 双入口）**：GUI confirm(accept) 与 CLI --confirm accept 走同一 service → status=accepted + confirmed_at + note 落库；重复 confirm → 422
5. **静态委托过滤**：F15 报告含 5 findings，仅 1 条挂本章 → 报告只含 1 条 static_consistency
6. **空档案**：无角色/无世界观 → 对应检查跳过不报错
7. **截断**：超长章节 → 报告注明截断 + 预算内条目选取
8. **audit-logs 查询**：分页正确；章节删除 → 记录级联删除（E14）
9. **v1.4 findings 落库（#1420）**：audit 后按记录 ID 读回明细 == 触发时的响应体 findings（含 ref_entity_id/context 往返保真）；旧记录无快照 → 空列表不 404
10. **v1.4 超时文案（#1420）**：传输层超时文案不含 `list`/`get` 词元（回归断言），且仍保留「勿直接重试」劝止语义
11. **v1.5 异步受理（#1425）**：`POST /audit` 立即 202 + `{log_id, status=running}`；后台任务完成后 `/status` → `completed` 且读口可取出 findings（与同步版报告一致）
12. **v1.5 幂等重跑（#1425）**：同章同内容二次触发 → 202 返回**同一 log_id**、`status=completed`、**不新增记录**；章节内容改动后再触发 → 新 log_id + 新记录
13. **v1.5 失败可见（#1425）**：后台任务异常 → 记录 `run_status='failed'` + `error` 非空；`/status` 与 `--history` 均可见；CLI `--wait` 以退出 1 收口
14. **v1.5 审计域 hint（#1425）**：审计工具 TIMEOUT 信封 hint 指向「按 log_id 查询」（`audit` action=`result`），不含 `list/get`；其他域 hint 不变
15. **v1.5 降级记录也复用（#1425 实测修正）**：LLM 不可用（无可用模型）→ 记录 `run_status='completed'` + `degraded=true` + 确定性 findings；同章同内容**再次触发 → 复用同一 `log_id`（202 status=completed），不新增记录**——#1425 的 M7 实证探针在真实内核上抓到首版实现（复用谓词带 `degraded=false`）会导致「每次重试 +1 条记录」，与本 issue 目标相反，故谓词收敛为「completed + pending」；刷新降级结果的路径 = 确认（accept/reject）或改正文

### 9.3 覆盖率

模块 ≥80%（ADR-027 口径）；LLM 路径用 Fake 覆盖解析/降级全分支（F16 非确定性板块 Mock 测试模式）；audit_log_repo 真 SQLite 覆盖持久化路径。

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| 全书批处理审计 | F15 已覆盖档案间一致性；章节审计是单章粒度，全书级由 CLI 循环调用 |
| 自动改文/自动修复漂移 | F27 哲学：AI 只建议，用户决策；自动改文是未来 Agent 化（F27 writer-agent）职责 |
| ~~audit_logs 存 findings 明细/JSON 快照~~ **（v1.4 已演进，见下）** | ~~Q1=C 拍板：轻量记录（摘要级）即可追溯；明细是即时消费，历史回看场景弱（§2.3 决策论证）~~ → **v1.4（#1420）改为落 JSON 快照列 + 按记录 ID 读口**：客户端 300s 超时会让「即时消费」的明细彻底丢失（实测 2.6% 命中），副作用超过节省的存储 |
| ~~**v1.4 仍在范围外**：异步语义（触发即返回 log_id，超时后按 id 轮询）~~ **（v1.5 已交付）** | #1425（用户 2026-10-06 拍板方案 B）已落地：`POST /audit` → 202 + 后台执行 + `/status` 轮询 + 幂等重跑；本条自 v1.5 起移出「范围外」 |
| **v1.5 仍在范围外**：进度百分比 / 分阶段进度（如「正在做人设漂移检查」） | 当前状态粒度 = `running`/`completed`/`failed`（够用即可，P5 YAGNI）；细粒度进度须改后台任务为可上报的阶段模型，收益不足 |
| **v1.5 仍在范围外**：内核重启后对遗留 `running` 行做自动对账（置 failed） | #1317 教训：多内核并存时「无条件释放 running」会误伤别实例正在跑的任务；`audit_logs` 无实例归属载体（不像 `writing_plans.limits.kernel_owner_pid`），故不引入自动对账——改用**复用窗口**（超窗不复用 + 旧行保持 running）规避「永久卡死」，见 §7 E21 |
| **v1.5 仍在范围外**：服务端主动推送任务完成（SSE/长轮询） | 客户端轮询已满足（本地单用户工具，任务时长秒~分钟级）；推送须新增事件面，收益不足 |
| **v1.4 仍在范围外**：GUI 审计明细回看页 | 读口先供 CLI/API（超时恢复的主战场是批审计）；GUI 历史/明细页沿用 Q3=C「后续演进」口径 |
| GUI 审计历史页/全局列表 | Q3=C 拍板：最小版只做章节页确认闭环；历史查询走 CLI `--history` + API audit-logs，GUI 历史页后续演进 |
| 审计通知/提醒（推送） | 无场景（本地单用户工具），YAGNI |
| 与 F22 索引同步联动 | F22 v1.1 不阻塞等待本模块；联动是增强（§5.6 注），归 F22 演进 |
| 风格分析/文笔建议 | F16 已覆盖（风格统计 + AI 痕迹），F34 不重复 |
| 多章节批量审计 UI | GUI 按单章确认流程做；批量是 CLI 场景 |
| 审计发现自动生成修复建议的落库 | 建议随报告展示，不写入章节（无副作用原则） |

---

## 11. 依赖关系

### 依赖（本模块需要）

| 模块 | 依赖类型 | 用途 |
|------|----------|------|
| F1 Project | 硬依赖 | 项目校验 + default_words 目标 |
| F2 Chapter | 硬依赖 | 章节读取 + 状态（REVIEW/FINAL 触发语义） |
| F5 LLM | 硬依赖 | 漂移分析（ChatOpenAI 既有，Fake 注入测试） |
| F9 Character | 硬依赖 | 人设档案 |
| F10 World | 硬依赖 | 世界观条目 |
| F15 Audit | 条件依赖（include_static=true） | 静态一致性委托 |
| F16 jieba | 硬依赖 | 名称匹配（上下文选取，复用 0.42.1） |
| F19 GUI | 硬依赖（Q3=C 拍板） | 章节页确认流程最小版 |

### 被依赖（谁依赖本模块）

| 消费方 | 方式 |
|--------|------|
| F44 全自动写作链（#1267） | **写作门禁**：`severity=error`（阻断级，口径 `_audit_bridge.BLOCKING_SEVERITY`）→ 停止后续章节，被阻断章 `progress=needs_review`，run 终态 `blocked`；`warning`/`info` 不阻断；`degraded=true` **不阻断但告警**（「没审出来 ≠ 审出问题」）。阻断判定唯一实现点 = `_audit_bridge.audit_blocks_writing` / `inspect_audit_conclusion`（交 F44 §5.5 展开） |
| F22 搜索（#54） | 增强触发语义（审计确认 → 索引增量），**非阻塞**（F22 v1.1 已用状态变更触发） |
| GUI | 章节页审计按钮 + 确认弹层（交互式轨 = 用户决定是否阻断，复用 `confirm accept\|reject` 状态机） |
| CLI | `inkflow audit chapter`（触发 + 确认 + 历史 + **v1.4 按记录 ID 取明细**） |

### 编号口径声明

F34 编号为 0.6.0 新增（2026-08-09 用户拍板立项，F 编号顺序 F33 之后）；变体编号第 17 变体声明依据 AGENTS.md 模块类型谱系，冲突以 ADR-019 v5+ 为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| D1 | **v1.1：轻量记录 audit_logs（Q1=C）** | 摘要级记录表（时间/章节/结果/确认状态/备注），无 findings 明细 | 用户拍板（2026-08-09）：满足「可追溯」验收且避免全量持久化膨胀；severity_summary 支持质量趋势查询；FK 级联随项目/章节删除 | v1.0 瞬态（可追溯验收不满足）；完整快照持久化（数据膨胀 + 场景弱，F25 教训） |
| D2 | LLM 降级不阻塞 | 200 + degraded 标记 + 落记录 | 审计是建议非门禁；LLM 抖动不该阻塞作者流程；确定性检查兜底；degraded 可追溯审计质量 | LLM 失败 → 500（错误面扩大 + 用户困惑） |
| D3 | 确认不改变业务数据 | accept/reject 只影响 audit_logs 状态 | 无副作用原则（F15 先例）；确认语义是「闭环记录」，业务数据由作者自行修改 | 确认时自动触发 F22 索引/自动改文（耦合 + 副作用） |
| D4 | 自动触发走前端编排 | 状态变更后前端调 audit 端点 | 零跨模块 MODIFY（F2 service 不动）；F19 前端已掌握状态变更事件 | F2 service 挂钩子（破坏零 MODIFY 纪律） |
| D5 | LLM 检查主体化（非可选） | character_drift/setting_drift 是核心检查项 | 用户设想就是「人设/设定漂移检查」；F16 的 LLM 是可选增强，F34 相反 | 仅确定性检查（不满足需求） |
| D6 | 上下文截断集中在 `_audit_context.py` | 预算常量 + 采样 + 名称匹配单一模块 | 可单测、防魔法数字散落、参数可调 | 散落 service（不可测） |
| D7 | confirm 独立端点（非 PATCH 报告） | `POST .../audit/confirm` | 报告是瞬态无资源 id；动作语义（accept/reject）用 POST 动作端点（F24 状态动作端点先例） | PATCH 瞬态报告（无 id 可 PATCH，伪资源化） |
| D8 | **v1.1：CLI 确认双入口（Q2=B）** | `--confirm accept\|reject` + `--note`，GUI/CLI 共用 confirm service | 用户拍板（2026-08-09）：单 CLI 用户不应被迫下载 GUI 才能完成确认闭环；双入口状态统一落 audit_logs（单一真相源） | v1.0 CLI 只触发（单 CLI 用户确认悬空） |
| D9 | **v1.1：GUI 最小版一并做（Q3=C）** | 章节页审计按钮 + 报告弹层 + accept/reject，无历史页/通知 | 用户拍板（2026-08-09）：确认闭环是功能定义的一部分（「最后由用户确认」）；F22 联动需要 accept 事件发生 | 后端先行 GUI 后置（确认语义悬空 + 重蹈 F15 GUI 缺位）；完整 GUI（历史页/通知超范围） |
| D10 | 自有端口 audit_log_repository | 本模块自己的 Protocol + repo | 业务表之外的补充持久化不 MODIFY 既有 Protocol（F15 audit_repo 先例）；SQLite 轻量 CRUD 可独立测试 | 复用 F32 settings_repo（语义不同，key-value vs 记录表）；service 直连 ORM（破坏分层） |
| D11 | **v1.4（#1420）：findings 落库 + 按记录 ID 读口（Q1=C 演进）** | `audit_logs` 增 `findings` JSON 快照列（`LenientJSON`，`TEXT NOT NULL DEFAULT '[]'`）；`add(*, findings=...)` 落库（与 POST 响应体同源）；新增 `GET /api/v1/audit-logs/{log_id}` + CLI `--log <id>`；**列表端点仍返回轻量 `AuditLog`**（独立 `AuditLogDetail` 模型，不污染列表形态） | 客户端 300s 超时会让「即时消费」的明细永久丢失（352 章批审计命中 2.6%，重跑 200–300 秒且新增重复记录）；快照成本（单章几 KB~几十 KB）远低于重跑成本；读口独立模型使 Q1=C 的摘要级列表契约零变化（向后兼容） | 仅改文案（明细仍不可恢复——#1420 方案 1 单独不足）；异步语义（触发即返回 log_id + 轮询，#1420 方案 3，改动面大，归后续）；写产物文件 + 存路径（引入清理策略与孤儿文件问题，DB 列更内聚） |
| D12 | **v1.5（#1425）：审计触发异步语义（202 + 后台 + 轮询）** | `POST .../audit` 由阻塞 200 改 **202 + `{log_id, status}`**；检查走 `spawn_background_task`（fire-and-forget，F44 #456 先例）；**状态承载复用 `audit_logs` 本表**（增 `run_status`/`error`/`content_hash` 三列，不新建表）；新增 `GET /api/v1/audit-logs/{log_id}/status` 轮询读口（findings 仍由 v1.4 读口复用）；CLI `--wait`（默认）/`--no-wait`；三消费面（GUI/CLI/MCP）同 PR 同步 | ① 与既有超时文案「服务端任务可能仍在进行」天然一致（v1.4 只解决「事后可查」，v1.5 解决「当场可知状态」）；② 幂等去重根治 #1420 残留的「重跑重复记录」；③ 状态落表 → 进程崩溃后状态可观测（不再有「不知道任务是否在跑」的黑洞）；④ 复用本表 = 一条记录即一次「任务 + 确认」，零新表零新装配面；⑤ 与 #1484（批量审计入口）的断点续跑/状态可观测需求直接对齐（任务状态语义写进 spec 供其引用） | 方案 A 维持同步（重复记录 + 无状态，痛点未解）；方案 C `?wait=false` 双语义并存（心智负担 + 老路径仍超时，未采纳）；方案 D 复用 `agent_executions`（语义不匹配：那是 agent 管线运行记录，字段面 stages/final_output 与审计无关，查询面须额外适配）；新建 `audit_tasks` 表（一条审计拆两表 → 一致性与级联复杂度，YAGNI）。**架构参照**：ADR-011（异步无阻塞架构）+ F44 #456 202 fire-and-forget 先例；模块级决策记录沿用 F34 惯例（D1–D11 均记于本表，未单开 ADR 文件） |

---

## 13. 验收标准

> 「自动化载体」列：单元/API/CLI/E2E/手动。

| # | 验收标准 | 自动化载体 | 验证命令（backend 目录，uv run） |
|---|----------|------------|-------------------------------|
| M1 | 手动触发审计（API）返回报告，含字数/人设/设定/静态检查项 | API | `pytest ../tests/api/test_chapter_audit_api.py` |
| M2 | 字数判定边界正确（79%/80%/120%/121%） | 单元 | `pytest backend/tests/unit/domain/services/test_chapter_audit_service.py -k word` |
| M3 | Fake LLM 人设漂移命中 → ERROR finding + ref_entity | 单元 | `pytest backend/tests/unit/domain/services/test_chapter_audit_llm.py` |
| M4 | LLM 失败 → 200 + degraded + 确定性检查仍在 + 记录 degraded | 单元+API | `pytest backend/tests/unit/domain/services/test_chapter_audit_service.py -k degrade` |
| M5 | **v1.1：审计落 audit_logs（severity_summary 正确，重复审计多条）** | 单元 | `pytest backend/tests/unit/infrastructure/database/test_audit_log_repo.py backend/tests/unit/domain/services/test_chapter_audit_service.py -k log` |
| M6 | confirm 闭环（accept → accepted + confirmed_at；重复 → 422；无 pending → 422） | 单元+API | `pytest backend/tests/unit/domain/services/test_audit_service_confirm.py` |
| M7 | **v1.1：CLI --confirm accept/reject + --note 落库 + --history 列表 + --note 无 --confirm 报错** | CLI | `pytest ../tests/cli/test_cli_audit_chapter.py` |
| M8 | **v1.1：audit-logs API 分页查询 + 章节删除级联** | API+单元 | `pytest ../tests/api/test_chapter_audit_api.py backend/tests/unit/infrastructure/database/test_audit_log_repo.py -k cascade` |
| M9 | 静态委托过滤（仅本章相关 findings 展示） | 单元 | `pytest backend/tests/unit/domain/services/test_chapter_audit_service.py -k static` |
| M10 | 空档案跳过 / 空章节仅字数 | 单元 | `pytest backend/tests/unit/domain/services/test_chapter_audit_service.py -k empty` |
| M11 | **v1.1：GUI 最小版** 章节页审计按钮 → 报告弹层 → accept/reject 点击闭环（audit_logs 状态更新） | E2E | `pytest`（前端 E2E，Q3=C 细化） |
| M12 | 全量门禁：lint/unit/integration/api/cli 绿 + 覆盖率达标 | CI | `uv run ruff check src/ tests/unit/ ../tests/` + 全量 pytest |
| M13 | 真实 LLM 验证（ADR-026 label 触发） | CI（label） | e2e-ai-backend job：真实模型一次审计成功 + 降级路径 |
| M14 | **v1.3：#1266 前后章连贯性** check 产出（不连贯输入 → `cross_chapter` finding）+ 反向断言（连贯 → 不产）+ LLM 失败降级（`degraded=true` 不抛错）+ 无前章摘要跳过 | 单元 | `pytest backend/tests/unit/domain/services/test_chapter_audit_check_types.py` |
| M15 | **v1.3：#1266 大纲符合度** check 产出（偏离输入 → `outline_compliance` finding）+ 反向断言（符合 → 不产）+ LLM 失败降级 + 无章纲跳过 + 正文截断沿用既有常量 | 单元 | `pytest backend/tests/unit/domain/services/test_chapter_audit_check_types.py` |
| M16 | **v1.4（#1420）：findings 落库 + 读口** —— 迁移三形态（旧库补列/新库 no-op/无表 no-op）+ audit 落库 findings == 响应体 + `GET /api/v1/audit-logs/{log_id}` 200（含空 findings）/404 + CLI `--log` 取回 + 列表形态零变化（反例守护） | 单元+API+CLI | `pytest backend/tests/unit/core/test_audit_logs_findings_migration_1420.py backend/tests/unit/infrastructure/database/test_audit_log_findings_repo_1420.py backend/tests/unit/domain/services/test_chapter_audit_findings_persist_1420.py ../tests/api/test_chapter_audit_log_detail_1420.py ../tests/cli/test_cli_audit_chapter_log_1420.py` |
| M17 | **v1.4（#1420）：超时文案不承诺不存在的能力** —— 传输层 TIMEOUT 文案（非流式 + 流式）不含 `list`/`get` 词元，保留「勿直接重试」劝止语义 | 单元 | `pytest backend/tests/unit/infrastructure/http/test_timeout_copy_1420.py backend/tests/unit/infrastructure/http/test_timeout_classification_926.py` |
| M18 | **v1.5（#1425）：触发即返回 log_id（202）** —— POST → 202 + `{log_id, status}` 且**立即返回**；后台执行完成后 `/status` → completed 且读口可取 findings | API+单元 | `pytest ../tests/api/test_chapter_audit_async_1425.py backend/tests/unit/domain/services/test_chapter_audit_async_1425.py` |
| M19 | **v1.5（#1425）：幂等重跑 + CLI UX 不退化** —— 同章同内容重复触发不新增记录（202 completed 复用同一 log_id）；CLI 默认 `--wait` 输出报告、`--no-wait` 输出 `log_id`；后台失败 → `failed` 可见 | 单元+API+CLI | `pytest backend/tests/unit/infrastructure/database/test_audit_log_async_repo_1425.py ../tests/api/test_chapter_audit_async_1425.py ../tests/cli/test_cli_audit_async_1425.py` |
| M20 | **v1.5（#1425）：审计域 TIMEOUT hint 收敛** —— 审计工具 TIMEOUT hint 指向按 `log_id` 查询（不含 `list/get`）；其他域 hint 不变；`test_mcp_llm_timeout_926.py` 同步升级后全绿 | 单元 | `pytest backend/tests/unit/mcp/test_mcp_llm_timeout_926.py` |

> Issue #208 验收标准映射（v1.1 拍板同步 2026-08-09）：写完一章可触发=M11（前端自动触发） · 报告含字数/人设/设定+级别=M1/M3 · GUI 确认交互=M11 · **记录可追溯=Q1=C 轻量记录（M5/M7/M8，audit_logs + CLI --history + API audit-logs）** · **CLI 可确认=Q2=B（M7）**。

---

## 待澄清问题（评审时确认）

| # | 问题 | 选项 | 建议 |
|---|------|------|------|
| Q1 | 审计历史追溯：报告瞬态还是留记录？ | A. 瞬态（零实体零迁移，重审覆盖）<br>B. 完整持久化（audit_runs 全量 findings + 历史页）<br>C. 轻量记录（audit_logs 摘要级：时间/章节/结果/确认状态/备注，无 findings 明细） | ✅ 已确认（用户拍板 2026-08-09：C）——正文已按轻量记录修订（§2.3 audit_logs + §3.3 GET audit-logs + §4 --history + §12 D1）；可追溯验收落地且避免全量膨胀。⚠️ **v1.4（#1420）演进留痕**：Q1=C 本身不变（列表仍是摘要级轻量记录），仅**增** findings JSON 快照列 + 按记录 ID 读口（§2.3 / §3.1 / §12 D11）——原「findings 明细是即时消费、历史回看场景弱」的假设被「客户端 300s 超时导致明细永久丢失」证伪 |
| Q2 | CLI 是否支持确认？ | A. CLI 只触发（确认是 GUI 交互语义）<br>B. CLI 也支持 `--confirm accept/reject`（+备注） | ✅ 已确认（用户拍板 2026-08-09：B，理由「单 CLI 用户不应被迫下载 GUI」）——正文已按双入口确认修订（§4 --confirm/--note + §5.1 ⑨ + §12 D8），GUI/CLI 状态统一落 audit_logs |
| Q3 | GUI 确认流程范围？ | A. 完整前后端同 PR（含历史页）<br>B. 后端先行，GUI 归后续 issue<br>C. 最小版一并做（章节页按钮 + 报告弹层 + accept/reject，无历史页/通知） | ✅ 已确认（用户拍板 2026-08-09：C）——正文已按最小版修订（§8 前端清单 + §12 D9），确认闭环是功能定义；历史查询走 CLI/API 即可 |
