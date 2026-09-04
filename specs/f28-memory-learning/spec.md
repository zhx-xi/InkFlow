# F28: Agent 记忆系统（agent-memory）功能规格
> **端**: backend

**Spec 版本**: 1.0（初稿待评审）
**日期**: 2026-08-11
**依据**: PRD §6.1 F3/F4/F5 + Agent 化升级路径 v1.1（design/agent-upgrade-path-2026-08-03.md）§4 Stage 2 + adr/memory-skills/ADR-037.md/adr/memory-skills/ADR-038.md + F27 spec v1.0（specs/f27-writer-agent/spec.md，事件源契约）+ 用户拍板（2026-08-03 判据 E 纳入核心路径）
**所属阶段**: 0.7.0（Agent 化升级第三批），估算 6-10 人天
**关联 Issues**: #159（F28 Agent Memory 记忆系统）
**依赖**: ✅ F27 writer-agent（diff 事件源：draft 表 + update_content 未接线 + audit_logs，PR #241）· ✅ F6 context-service（注入端口，ContextSourceType/SOURCE_LAYER）· ✅ F26 agent-tools · ✅ F13（extra 键 + 请求覆盖先例）· ✅ F34（audit_logs 复用）· ✅ F32（settings 键扩展先例——本模块不新增全局设置键）
**参考 ADR**: adr/memory-skills/ADR-037.md（记忆提取方式：规则化统计 N≥2）、adr/memory-skills/ADR-038.md（memory_learning 默认 false）、adr/agent/ADR-031.md（双模式开关 extra 键）、adr/agent/ADR-034.md（产物保留语义）、ADR-027（覆盖率门禁）
**状态**: ✅ 已实现（PR #242，2026-08-11 合入；Q1-Q4 拍板 2026-08-11）

> **模块类型声明**: 本模块为 Agent 化升级新增变体——「**偏好学习闭环型**」（第 12 个模块变体，编号依据：AGENTS.md 模块类型谱系，F27=第 11 变体口径延续）。与 F27（自主循环闭环型）不同：F28 是**首个从用户行为反向学习并回注生成流程**的模块，新增 2 张表（project_preferences + memory_events，Q2 拍板），跨模块 MODIFY F27 draft 服务（接线 update_content）+ F6 context（新增数据源）。

---

## 1. 概述

F28 交付判据 E（升级路径 v1.1 §1 补充判据，用户拍板新增）：**越用越智能**——从用户修改/确认/重新生成行为中学习项目偏好并注入后续生成。

### 1.1 闭环定位

```
F27 agentic 生成 → 草稿（draft 状态）
  → 用户确认前手动编辑草稿（F28 接线 update_content）
  → 编辑 diff 事件（before/after）落 memory_events
  → 规则化统计提取（同一模式 N≥2 次）→ project_preferences
  → PreferenceSource 注入 F6 context（protected 层）
  → 下次 agentic 生成自动遵循 → 用户修改减少 → 越用越智能
```

### 1.2 与既有模块的边界

- **事件边界**：diff 事件只从**用户主动行为**产生（编辑草稿/拒绝草稿/确认草稿）；LLM 自身输出与护栏触发不产生学习事件。
- **写入边界**：偏好提取/落库/删除只经 memory_service（调 repo，不碰 ORM，F27 adr/agent/ADR-036.md 约束①同构）。
- **注入边界**：偏好只经 F6 context 端口注入（新增 PreferenceSource），不直接改 agentic_writer 的 system prompt。
- **开关边界**：`memory_learning=false`（默认）时**零行为变化**——不捕获事件、不提取、不注入、不额外审计（验收判据④）。
- **明确不含**：LLM 提取偏好（第二阶段远期，F14 extraction 模式）、跨项目偏好共享、向量化检索、GUI 界面（F19 渲染层未排期，CLI 先行 Q3 拍板）、F29 supervisor 记忆消费。

### 1.3 与样板差异

非 F9 实体 CRUD（无标准全量 CRUD 端点）、非 F14 横切门面、非 F27 编排闭环。本模块是「**事件捕获 + 规则化提取 + 结构化存储 + 上下文注入 + 透明控制**」五件套的组合变体——核心是**可解释、可测试的规则化统计**（adr/memory-skills/ADR-037.md：LLM 提取为第二阶段）。

---

## 2. 数据模型

### 2.1 领域模型（新增 `domain/models/preference.py`）

```python
class PreferenceCategory(StrEnum):
    """偏好分类维度（Q1 拍板：4 类起步，2026-08-11）。

    Attributes:
        ADDRESSING: 称呼习惯（主角/配角称谓、人称替换，如「她」→「林晚」）.
        STYLE_WORD: 风格用词（形容词/副词/固定表达替换，如「说」→「低声道」）.
        STRUCTURE: 结构偏好（段落/标题/列表组织模式）.
        OTHER: 其他（兜底）.
    """
    ADDRESSING = "addressing"
    STYLE_WORD = "style_word"
    STRUCTURE = "structure"
    OTHER = "other"


class ProjectPreference(BaseModel):
    """一条已学习的项目偏好（结构化偏好表，非向量——adr/memory-skills/ADR-037.md）。

    Attributes:
        id: 偏好 UUID 字符串（uuid4）.
        project_id: 所属项目 UUID.
        category: 分类维度.
        pattern: 模式描述（学习到的稳定模式，如「称呼主角为林晚」）.
        value: 偏好值（用户反复修改后保留的文本，如「林晚」）.
        confidence: 置信度（0-1，随 count 增长单调递增，公式见 §5.2）.
        count: 支撑事件数（≥2 才落库）.
        source_events: 支撑事件 id 列表（memory_events.id，可追溯）.
        created_at: 创建时间（UTC）.
        updated_at: 最后更新时间（UTC）.
    """
    model_config = {"from_attributes": True}

    id: str
    project_id: uuid.UUID
    category: PreferenceCategory
    pattern: str
    value: str
    confidence: float
    count: int
    source_events: list[str] = []
    created_at: datetime
    updated_at: datetime
```

### 2.2 diff 事件模型（新增 `domain/models/memory_event.py`，Q2 已拍板：独立表）

```python
class MemoryEventType(StrEnum):
    """学习事件类型——用户主动行为的分类.

    Attributes:
        DRAFT_EDITED: 用户确认前手动编辑草稿（before/after 均有值）.
        DRAFT_REJECTED: 用户拒绝草稿（重新生成信号，after 为空）.
        DRAFT_CONFIRMED: 用户直接确认草稿（未编辑，0 修改信号）.
    """
    DRAFT_EDITED = "draft_edited"
    DRAFT_REJECTED = "draft_rejected"
    DRAFT_CONFIRMED = "draft_confirmed"


class MemoryEvent(BaseModel):
    """一次用户修改/确认/重新生成行为的 diff 事件快照（Q2 独立表）.

    Attributes:
        id: 事件 UUID 字符串（uuid4）.
        project_id: 所属项目 UUID.
        draft_id: 关联草稿 id（可空）.
        chapter_id: 目标章节 UUID（可空）.
        agent_run_id: 来源 agent run id（可空）.
        event_type: 事件类型.
        before_content: 修改前内容（edited 必填；rejected/confirmed 可空）.
        after_content: 修改后内容（edited 必填；rejected 可空）.
        diff_chars: 修改量 = |after| - |before| 字符数差（可负，只读统计用）.
        created_at: 事件时间（UTC）.
    """
    model_config = {"from_attributes": True}

    id: str
    project_id: uuid.UUID
    draft_id: str | None = None
    chapter_id: uuid.UUID | None = None
    agent_run_id: str | None = None
    event_type: MemoryEventType
    before_content: str | None = None
    after_content: str | None = None
    diff_chars: int = 0
    created_at: datetime
```

### 2.3 ORM（新增 `infrastructure/database/models/preference.py`）

| 表 | 关键列 | 说明 |
|----|--------|------|
| `project_preferences` | id(String36 PK) / project_id(String36 idx) / category(String20) / pattern(Text) / value(Text) / confidence(Float) / count(Integer) / source_events(JSON) / created_at / updated_at | 结构化偏好表（adr/memory-skills/ADR-037.md）；project_id 无 FK（镜像 agent_runs/drafts 先例） |
| `memory_events` | id(String36 PK) / project_id(String36 idx) / draft_id(String36) / chapter_id(String36) / agent_run_id(String36) / event_type(String20) / before_content(Text) / after_content(Text) / diff_chars(Integer) / created_at | diff 事件表（Q2 独立表）；全部 FK 可空且无 FK 声明（镜像 drafts 先例，级联由服务层承担） |

> 决策论证：`source_events` 用 **JSON 数组**（事件 id 字符串列表）——只读消费、一次写入，与 agent_runs.steps JSON 快照先例一致（F27 §2.3）；事件详情可经 memory_events 表查询（可追溯性）。

### 2.4 复用既有模型

- `Draft` / `DraftStatus`（F27）：diff 事件的 before 源（draft.content 修改前）+ 确认/拒绝状态信号。
- `ContextItem` / `ContextSourceType`（F6）：偏好注入载体（§5.4）。
- `ProjectConfig.extra`（F1）：`memory_learning` 开关键（§5.5）。
- `AuditLog` / `AuditLogService`（F34/F27）：学习/删除动作审计（§5.6）。

---

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 说明 | 状态 |
|------|------|------|------|
| PATCH | `/api/v1/agent/drafts/{draft_id}` | 编辑草稿正文（确认前手动修改；**接线 F27 未接线的 update_content** + diff 事件捕获） | 新增（MODIFY agent_runs.py） |
| GET | `/api/v1/agent/preferences?project_id=` | 项目已学偏好列表（用户可查看） | 新增 |
| DELETE | `/api/v1/agent/preferences/{preference_id}` | 删除偏好（立即停止注入） | 新增 |
| GET | `/api/v1/agent/memory/stats?project_id=` | 修改率统计（对照 F27 基线，验收判据①） | 新增 |

> 约束：既有 `/api/v1/agent/drafts` 端点（F27 list/confirm/reject）**零改动**；PATCH 是新增方法同前缀共存。偏好端点挂 `/api/v1/agent/` 前缀（与 F27 agent_runs router 同文件或独立文件，以实现为准——建议独立 `memory.py` router 保持职责单一）。

### 3.2 请求/响应示例

```json
PATCH /api/v1/agent/drafts/{draft_id}
{"content": "修改后的章节正文..."}
→ 200 {"draft_id": "uuid", "status": "draft", "word_count": 2100,
       "learned": true}   // learned=true: 本次修改触发偏好提取（N≥2 且已落库）

GET /api/v1/agent/preferences?project_id=uuid
→ 200 {"items": [{"id": "uuid", "category": "addressing", "pattern": "称呼主角为林晚",
                  "value": "林晚", "confidence": 0.67, "count": 2,
                  "source_events": ["uuid1", "uuid2"], "created_at": "..."}],
       "total": 1}

DELETE /api/v1/agent/preferences/{preference_id}
→ 200 {"preference_id": "uuid", "deleted": true}

GET /api/v1/agent/memory/stats?project_id=uuid
→ 200 {"project_id": "uuid",
       "agentic": {"chapters": 5, "direct_confirms": 2, "avg_diff_chars": 320,
                   "modify_rate": 0.6, "regenerate_rate": 0.2},
       "learned_preferences": 3,
       "baseline_ref": "design/agent-baseline-2026-08-10.md"}
```

### 3.3 异常映射表

| 场景 | HTTP | 错误码/说明 |
|------|------|-------------|
| 草稿不存在（PATCH） | 404 | 复用 F27 DraftNotFoundError 语义 |
| 草稿状态非 draft（PATCH） | 409 | 复用 DraftStateError（confirmed/rejected 不可编辑） |
| 内容为空（PATCH） | 422 | Pydantic 校验（content 非空，镜像 DraftService.create 语义） |
| 偏好不存在（DELETE） | 404 | 新错误面 PreferenceNotFoundError |
| project_id 非法 | 404 | `_parse_id` 复用（F27 先例） |

---

## 4. CLI 命令签名

### 4.1 `inkflow memory` 顶层命令组（新文件 `cli/commands/memory_cmd.py`，app.py 注册）

```text
inkflow memory list --project-id <UUID> [--category addressing|style_word|structure|other] [--json]
   人类模式: 每行「[addressing] 称呼主角为林晚 (confidence 0.67, ×2)」
   --json 信封: {"ok": true, "data": {"items": [...], "total": N}}

inkflow memory remove <preference_id> [--json]
   删除后打印: ✅ 已删除偏好（下次生成立即停止注入）

inkflow memory stats --project-id <UUID> [--json]
   人类模式: 修改率/重新生成率 + 基线对照提示
   输出: 「agentic 修改率 60%（基线 N/A——F27 基线随使用积累，见 design/agent-baseline-2026-08-10.md）」
```

> 恒 HTTP 纪律（F38）：`memory` 命令全部经 ensure_kernel() + InkFlowHTTPClient 调内核 REST API，镜像 F27 `agent draft/runs` 子命令模式（agent_cmd.py `_run`/`_print_json_envelope` 同构）。

### 4.2 `inkflow write next` 扩展（MODIFY `cli/commands/write.py`）

```text
inkflow write next --project-id <UUID> --chapter-id <UUID> --outline <文本>
                   [--mode agentic] [--memory-learning|--no-memory-learning]
   请求覆盖项目级 memory_learning 配置（F13 同构：请求显式 > extra 键 > 默认 false）
   agentic 模式下（memory_learning 开启且本轮学习到新偏好）:
     人类模式追加打印: 🤖 AI 已记住：称呼主角为林晚（下次生成将遵循）
```

---

## 5. 关键差异节：偏好学习闭环

### 5.1 事件捕获（接线 F27 update_content + confirm/reject 信号）

**F27 现状核对（2026-08-11 实证）**：`draft_repo.update_content` 已实现（docstring「修改草稿正文（确认前用户手动修改落库）」）但 **DraftService 无 update 方法、API 无编辑端点**——F28 接线为 diff 事件捕获入口：

| 动作 | 事件 | 捕获点 | before/after |
|------|------|--------|--------------|
| 用户编辑草稿（PATCH drafts） | `draft_edited` | DraftService.update（新增方法，接线 update_content） | before=旧 content / after=新 content |
| 用户拒绝草稿（既有 reject） | `draft_rejected` | DraftService.reject（MODIFY：追加事件记录） | before=draft.content / after=None |
| 用户确认草稿（既有 confirm） | `draft_confirmed` | DraftService.confirm（MODIFY：追加事件记录） | before=None / after=draft.content |

- **捕获条件**：`memory_learning=true`（项目级开启）才落 memory_events；关闭时上述路径**零额外行为**（验收判据④）。
- **只读消费**：memory_events 一次写入、只读消费（镜像 agent_runs.steps JSON 快照语义）；无更新/删除端点（YAGNI）。
- **事务语义**：PATCH drafts 编辑 = 单次 commit（镜像 F27 单工具单事务 adr/agent/ADR-036.md 约束②）；事件记录与内容更新同事务（原子）。

### 5.2 偏好提取（规则化统计，adr/memory-skills/ADR-037.md）

**输入**：项目内全部 `draft_edited` 事件（`draft_rejected` 不直接提取——只贡献重新生成率统计；`draft_confirmed` 不提取）。

**提取算法**（纯 Python 规则，无 LLM——可解释可测试）：

```
对每个 draft_edited 事件 (before, after):
  1. difflib.SequenceMatcher(None, before, after).get_opcodes()
     → 提取 replace/delete/insert 片段对
  2. 候选偏好 = (pattern=被替换的旧片段, value=替换后的新片段)
     - 过滤噪声: 片段长度 ≥2 且 ≤50 字符; value 非纯标点; 忽略空白/换行纯变体
  3. 分类（Q1 拍板）:
     - addressing: value 匹配人物名模式（前后文含「称呼/叫/唤」或
       value 命中项目角色档案 name 列表）→ 「称呼{被替换者}为{value}」
     - style_word: value 长度 2-20 且非句末标点、pattern 长度 ≥2 → 「用词偏好：{value}」
     - structure: pattern/value 含 Markdown 结构标记（#/列表/标题行）→ 「结构偏好：{...}」
     - other: 兜底

统计合并:
  4. 同项目内同 (category, value) 聚合 → count += 1
  5. count == 2（阈值 N≥2，adr/memory-skills/ADR-037.md）→ 落库 ProjectPreference（防过度泛化：
     一次修改可能是试错，两次同类修改才是稳定偏好）
  6. count > 2 → 更新既有偏好（count+1, confidence 重算, source_events 追加）
  7. confidence = 1 - 1 / (count + 1)   // 单调递增: N=2→0.67, N=3→0.75, N=5→0.83
```

**阈值语义（验收判据②）**：同一模式第 1 次出现 → 仅事件落库（无偏好）；第 2 次出现 → 偏好落库（learned=true 回显）；删除后重新积累 → 重新计数（从 0 开始）。

**边界**：before==after（无实际修改）→ 不产生事件（PATCH 幂等判定）；单事件内多片段 → 每片段独立候选，分类后分别聚合。

### 5.3 存储

- `project_preferences`：非向量结构化表（adr/memory-skills/ADR-037.md）——category/pattern/value/confidence/count/source_events 六要素 + 时间戳。
- `memory_events`：diff 事件表（Q2 独立表）——可追溯（source_events 反查事件详情）。
- **项目删除级联**：project 删除时偏好/事件清理由服务层承担（镜像 F27 无 FK 先例，级联语义在 service——跨模块钩子接线，F28 RED 批内置既有 project_service 改动用例，规则 1k 形态）。
- **无缓存**：读路径实时查库（删除偏好立即生效 = 无内存/进程缓存，验收判据③）。

### 5.4 注入（扩展 F6 context_provider）

**新增 `PreferenceSource`**（`infrastructure/context/preference_source.py`，镜像 ForeshadowingSource 形态）：

```python
class PreferenceSource:
    """已学偏好数据源 — 注入项目学习到的稳定偏好（protected 层）.

    Args:
        preference_repo: 偏好仓储（list_by_project 查询活跃偏好）.
        project_repo: 项目仓储（memory_learning 开关判定）.
    """
    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        # 1. memory_learning=false（默认）→ 返回 []（零行为，验收判据④）
        # 2. 查询项目偏好（count≥2 恒成立——落库即有）→ 每条一个 ContextItem
        # 3. 冲突过滤（Q4 拍板）：命中显式设定的偏好跳过（§5.4.1）
        # 4. ContextItem(source=ContextSourceType.PREFERENCE, title=「AI 已记住：...」,
        #    content=pattern + value, priority=...)（Q4 拍板）
```

- **ContextSourceType 扩展**（MODIFY `domain/models/context.py`）：`PREFERENCE = "preference"` → `SOURCE_LAYER[PREFERENCE] = ContextLayer.PROTECTED`（升级路径 Stage 2：protected 层，与写作要求/大纲并列）。
- **装配**（MODIFY `api/deps.py`）：context_service sources dict 追加 PreferenceSource（镜像 ForeshadowingSource 注册位）。
- **protected 预算风险**：偏好注入量必须受控——单条 content ≤ 200 字符（pattern+value 精简渲染），单项目最多注入 10 条（limit 常量，防 protected 层超预算硬失败 ContextBudgetExceededError——F6 §3 语义）。
- **透明性**：注入 title 恒为「AI 已记住：{pattern}」格式（用户可见「AI 学到了什么」）。

#### 5.4.1 注入优先级冲突规则（Q4 细化）

| 优先级 | 来源 | 冲突处理 |
|--------|------|----------|
| 1（最高） | **显式设定**（角色档案 name/称呼、世界观条目、大纲） | 恒注入（既有 F6 行为不动） |
| 2 | **学习偏好**（本项目 project_preferences） | 与显式设定冲突时**跳过该条**（不覆盖显式设定） |
| 3（最低） | 默认/缺失 | — |

**冲突判定规则（可测试）**：偏好 value 若**已存在于同项目任意显式设定文本**（角色档案 fields、世界观条目、大纲内容——经注入的其他 sources 输出文本匹配），判定冲突 → 跳过。实现：PreferenceSource.collect 时加载显式设定文本集合（character/world/outline 查询），偏好 value 子串匹配即跳过。
**删除立即生效**：collect 实时查库（无缓存），删除偏好后下次生成即不含该条（验收判据③）。

### 5.5 开关（adr/memory-skills/ADR-038.md：memory_learning 默认 false）

| 层级 | 键/字段 | 默认 | 说明 |
|------|---------|------|------|
| 项目配置 | `project.config.extra["memory_learning"]` | false | 项目级开关（F13 timeline_auto_extract 同构） |
| 请求覆盖 | `AgenticWriteRequest.memory_learning: bool \| None` | None=读项目配置 | API/CLI 显式覆盖（F13：请求显式值 > extra 键 > 默认） |
| CLI 覆盖 | `write next --memory-learning/--no-memory-learning` | 未传=读项目配置 | 人类模式显式开启/关闭 |

**读取优先级**：请求体显式字段（--memory-learning）> 项目配置（extra 键）> 默认 false。
**零行为保证（验收判据④）**：false 时——PATCH drafts 不落 memory_events、不触发提取、PreferenceSource.collect 返回 []、无额外审计日志、agentic run 无「AI 已记住」输出。全路径零改动可测（RED 契约锁定）。

### 5.6 审计与透明提示

- **审计**（复用 F34 audit_logs，F27 severity_summary 语义先例）：偏好落库（`preference_learned`）、偏好删除（`preference_removed`）——actor="memory"（经 AuditLogService.record，异常静默旁路）。
- **透明提示（Q3 拍板：CLI 先行 + GUI 后续，2026-08-11）**：
  - CLI 先行：`write next --mode agentic` 完成后，若本轮学习到新偏好（落库动作发生）→ 人类模式追加「🤖 AI 已记住：{pattern}」；`--json` 信封 data 追加 `"learned": [{"pattern": "...", "category": "..."}]`。
  - GUI 形态（远期 F19 渲染层接入时）：toast「AI 已记住：称呼主角为 X」+ memory 面板查看/删除（Q3 建议 CLI 先行）。

### 5.7 修改率统计（验收判据①对照机制）

- **数据源**：memory_events（draft_edited.diff_chars + draft_confirmed/draft_rejected 计数）+ drafts 表（status 分布）。
- **指标**：修改率 = 非直接确认章节数 / agentic 章节总数；平均修改 diff = Σ|diff_chars| / 编辑事件数；重新生成率 = rejected 数 / 章节总数。
- **对照**：`inkflow memory stats` 输出与 `design/agent-baseline-2026-08-10.md` 基线的对比字段（baseline_ref 引用）；**基线数据现实**：F27 基线表 N=5/模式为「待填」（随使用积累，F27 spec §14 Q3 拍板）——F28 验收语义 = stats 命令输出可用 + 对照机制就绪 + 后续数据积累后数值可比；若基线仍无数据，stats 输出标注「基线 N/A」。
- **口径**：只统计 agentic 模式（deterministic 无草稿流，基线报告同口径）。

---

## 6. 组织规则

- 提取算法（difflib 规则化统计）放 `domain/services/preference_learner.py`（纯函数，零 IO——可独立单测）；编排（事件捕获/落库/统计）放 `domain/services/memory_service.py`（注入 repo，不碰 ORM）。
- 领域模型：`domain/models/preference.py`、`domain/models/memory_event.py`（纯 Pydantic，零 infrastructure import——F27 纪律延续）。
- repo：`infrastructure/database/repositories/preference_repo.py`、`memory_event_repo.py`（异步 SQLAlchemy，镜像 F27 draft_repo 形态）；ORM 转换函数在 repo 层。
- 注入源：`infrastructure/context/preference_source.py`（F6 sources 目录，镜像 ForeshadowingSource）。
- API：`api/routers/memory.py` 独立 router（偏好/统计端点）+ `api/routers/agent_runs.py` MODIFY（PATCH drafts）。
- CLI：`cli/commands/memory_cmd.py` 顶层命令（app.py 注册 `memory`）；`cli/commands/write.py` MODIFY（--memory-learning 覆盖）。
- 开关读取：memory_service + PreferenceSource 各自实时读 project_repo（不引入共享缓存——删除立即生效语义）。

---

## 7. 边界情况与错误处理

| 场景 | 行为 | 错误面 |
|------|------|--------|
| memory_learning=false（默认） | PATCH drafts 不落事件、不提取、不注入、无审计 | 无（零行为） |
| PATCH 草稿但内容与 before 相同 | 幂等：不落事件、不触发提取（before==after 判定） | 无 |
| PATCH 已确认/已拒绝草稿 | 409 DraftStateError（复用 F27） | HTTP 错误 |
| 第 1 次修改（count=1） | 仅事件落库，无偏好（阈值语义） | 无 |
| 第 2 次同类修改（count=2） | 偏好落库 + learned=true + 审计 preference_learned | 无 |
| 偏好与显式设定冲突 | 注入时跳过该条（显式设定胜，Q4） | 无（偏好保留可查） |
| 删除偏好后立即生成 | collect 实时查库 → 不含该条 | 无 |
| 偏好 value 为空/纯标点 | 过滤（提取规则噪声过滤） | 无 |
| 项目被删除 | 服务层级联清理偏好/事件（跨模块钩子） | 无（F27 先例） |
| 事件落库失败（DB 故障） | 编辑动作仍成功（事件捕获旁路：try/except 包裹，审计镜像语义） | 无（不阻断用户编辑） |
| protected 层超预算（偏好注入量失控） | limit 10 条 + 单条 ≤200 字符硬约束 | 无（设计防护） |
| 偏好表中无任何记录 | PreferenceSource.collect 返回 []（跳过） | 无 |

---

## 8. 文件结构

| 动作 | 文件 | 说明 |
|------|------|------|
| CREATE | `backend/src/inkflow/domain/models/preference.py` | ProjectPreference/PreferenceCategory 领域模型 |
| CREATE | `backend/src/inkflow/domain/models/memory_event.py` | MemoryEvent/MemoryEventType 领域模型 |
| CREATE | `backend/src/inkflow/domain/services/preference_learner.py` | 规则化提取纯函数（difflib + 分类 + 阈值聚合） |
| CREATE | `backend/src/inkflow/domain/services/memory_service.py` | 记忆编排服务（事件捕获/偏好管理/统计查询/开关判定） |
| CREATE | `backend/src/inkflow/infrastructure/database/models/preference.py` | ProjectPreferenceORM + MemoryEventORM |
| CREATE | `backend/src/inkflow/infrastructure/database/repositories/preference_repo.py` | project_preferences 异步仓储 |
| CREATE | `backend/src/inkflow/infrastructure/database/repositories/memory_event_repo.py` | memory_events 异步仓储 |
| CREATE | `backend/src/inkflow/infrastructure/context/preference_source.py` | PreferenceSource（F6 注入源） |
| MODIFY | `backend/src/inkflow/domain/models/context.py` | ContextSourceType.PREFERENCE + SOURCE_LAYER 映射（protected） |
| MODIFY | `backend/src/inkflow/domain/services/draft_service.py` | update 方法（接线 update_content + 事件捕获钩子） |
| MODIFY | `backend/src/inkflow/domain/services/project_service.py` 或等价 | 项目删除级联（偏好/事件清理钩子，跨模块接线） |
| CREATE | `backend/src/inkflow/api/routers/memory.py` | preferences/stats 端点 |
| MODIFY | `backend/src/inkflow/api/routers/agent_runs.py` | PATCH /drafts/{id} 编辑端点 |
| MODIFY | `backend/src/inkflow/api/deps.py` | memory_service/preference_repo/memory_event_repo 装配 + PreferenceSource 注册进 context sources |
| MODIFY | `backend/src/inkflow/domain/models/agent_run.py` | AgenticWriteRequest.memory_learning 字段（请求覆盖） |
| MODIFY | `backend/src/inkflow/domain/services/agentic_writer_service.py` | run 完成后「AI 已记住」提示数据（learned 列表回传） |
| CREATE | `backend/src/inkflow/cli/commands/memory_cmd.py` | memory list/remove/stats 命令组 |
| MODIFY | `backend/src/inkflow/cli/app.py` | 注册 memory 命令组 |
| MODIFY | `backend/src/inkflow/cli/commands/write.py` | next 命令 --memory-learning/--no-memory-learning |
| CREATE | `backend/tests/unit/test_preference_learner.py` | 提取算法契约（difflib 片段/分类/阈值聚合，RED 主批） |
| CREATE | `backend/tests/unit/test_memory_service.py` | 编排服务契约（事件捕获/偏好 CRUD/开关判定/统计，全 mock 轨） |
| CREATE | `backend/tests/unit/test_preference_repo.py` | 偏好仓储集成（真实 SQLite 轨） |
| CREATE | `backend/tests/unit/test_memory_event_repo.py` | 事件仓储集成（真实 SQLite 轨） |
| CREATE | `backend/tests/unit/test_preference_source.py` | 注入源契约（开关/冲突过滤/limit/透明标注） |
| CREATE | `tests/api/test_memory_api.py` | 偏好/统计端点 + PATCH drafts 契约 |
| CREATE | `tests/cli/test_cli_memory.py` | memory 命令 CLI 测试（**须登记 ci.yml integration-cli-backend**） |

---

## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 提取算法（核心） | ① 一次修改不学/两次同学（阈值语义）② 三次更新 count+confidence ③ 不同项目隔离 ④ 噪声过滤（标点/空/超长）⑤ 四类分类判定 ⑥ before==after 幂等 | ≥90% |
| 编排服务 | ⑦ memory_learning=false 零行为（无事件/无提取/无审计）⑧ 事件捕获落库 ⑨ 偏好删除后 collect 为空 ⑩ 统计指标计算 ⑪ 项目删除级联 | ≥90% |
| 仓储 | project_preferences/memory_events CRUD + source_events JSON 往返（真实 in-memory SQLite） | ≥90% |
| 注入源 | ⑫ 开关关闭返回 [] ⑬ 冲突过滤（显式设定命中跳过）⑭ 单条 ≤200 字符 + 最多 10 条 ⑮ title 恒「AI 已记住」 | ≥90% |
| API | PATCH drafts 200/404/409/422；preferences list/delete 200/404；stats 200 口径 | ≥90% |
| CLI | memory list/remove/stats 信封/人类模式/退出码；write next --memory-learning 覆盖 | ≥90% |
| 回归 | F27 drafts/confirm/reject 既有测试仍绿；F6 context 既有测试仍绿；deterministic 零回归 | 全仓 ≥60%（ADR-027 门禁 98.5/95.0） |

**RED 形态**：新模块整体不存在 → 顶部 import ModuleNotFoundError（收集期失败，exit 2）；既有文件追加段 → 404 断言 FAIL（PATCH drafts 端点、preferences 端点）。

**测试基建**：提取算法纯函数直测（无 mock）；编排服务全 mock 轨（memory_event_repo/preference_repo 显式默认值——规则 1m 形态）；注入源真实 repo + in-memory SQLite。

---

## 10. 不在范围内

| 项 | 归属 |
|----|------|
| LLM 提取偏好（语义级） | 第二阶段远期（adr/memory-skills/ADR-037.md，F14 extraction 模式） |
| 跨项目偏好共享/全局偏好 | 未排期（本项目内学习，防污染） |
| 向量化检索/语义相似偏好 | 未排期（非向量结构化表，adr/memory-skills/ADR-037.md） |
| GUI 记忆面板/toast | F19 渲染层接入时（Q3：CLI 先行） |
| F29 supervisor 记忆消费 | F29（0.8.0，#161） |
| 偏好自动过期/置信度衰减 | 远期（YAGNI；当前 count 单调累积） |
| memory_events 更新/删除端点 | YAGNI（一次写入只读消费） |
| deterministic 模式注入偏好 | 明确不含（deterministic 静态链零改动纪律，F27 延续） |
| 修改率统计 UI / 图表 | 未排期（CLI stats 先行，F19 接入时评估） |

---

## 11. 依赖关系

- **依赖**: F27（事件源：drafts 表 + update_content 未接线 + audit_logs + AgenticWriteRequest，PR #241）、F6（ContextSourceType/SOURCE_LAYER/ContextItem + sources 装配）、F26（agentic 装配点）、F13（extra 键 + 请求覆盖先例）、F34（audit_logs + AuditLogService）、F1（ProjectConfig.extra）、F38（CLI 恒 HTTP 纪律）。
- **被依赖**: F29（supervisor 记忆消费，0.8.0）、F19 GUI（渲染层接入偏好面板/toast，远期）。
- 新增运行时依赖：**无**（difflib 标准库 + 既有 SQLAlchemy）。
- 编号口径声明：以 ADR-019 v5 版本表为准（F28=本模块，Stage 2 口径延续升级路径 v1.1 §6）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 备选（否决理由） |
|------|------|-----------------|
| 偏好提取方式 | 规则化统计（difflib 文本片段 + N≥2 阈值，adr/memory-skills/ADR-037.md） | LLM 提取（不可解释不可测试，第二阶段远期） |
| 偏好存储形态 | 结构化表 project_preferences（category/pattern/value/confidence/count/source_events） | 向量库（过重；偏好是短文本精确匹配，非语义检索） |
| diff 事件存储 | 独立 memory_events 表（Q2 建议） | agent_run 扩展 payload（run 是生成侧记录，用户编辑事件混入职责污染；run 可能被清理而事件需留存） |
| 注入层 | F6 ContextSourceType.PREFERENCE → PROTECTED（升级路径 Stage 2 指定） | COMPRESSIBLE（可被压缩裁剪，偏好稳定性受损）；DYNAMIC（预算竞争可能全丢） |
| 冲突规则 | 显式设定 > 学习偏好（value 子串命中显式设定文本即跳过） | 偏好覆盖显式设定（用户显式录入的角色档案被学习噪声覆盖，违背可控性） |
| 删除语义 | 实时查库无缓存，删除立即生效 | 进程内缓存（删除不生效窗口期，验收判据③无法满足） |
| 开关 | extra["memory_learning"] 默认 false + 请求/CLI 覆盖（adr/memory-skills/ADR-038.md，F13 同构） | 全局设置键（F32 白名单扩展——偏好开关是项目级语义，非全局用户设置） |
| 事件捕获点 | 接线 F27 update_content（新增 PATCH drafts 端点） | 确认时对比章节内容（F27 confirm 原子写入无 before 留存；章节原内容可能是空/旧稿，非用户意图信号） |
| 透明提示 | CLI 输出「AI 已记住」+ JSON learned 字段（Q3 建议） | 静默学习（用户失去控制感，违背可解释 AI 目标） |

---

## 13. 验收标准

- **M1 提取算法全绿**: `pytest tests/unit/test_preference_learner.py` — 阈值语义（1 次不学/2 次学/3 次更新）+ 分类 + 噪声过滤 RED（ModuleNotFoundError）→ GREEN 全过
- **M2 编排服务全绿**: `pytest tests/unit/test_memory_service.py` — 零行为开关 + 事件捕获 + 偏好 CRUD + 统计 + 级联
- **M3 仓储全绿**: `pytest tests/unit/test_preference_repo.py tests/unit/test_memory_event_repo.py` — 真实 SQLite 轨 CRUD + JSON 往返
- **M4 注入源全绿**: `pytest tests/unit/test_preference_source.py` — 开关关闭返回 [] / 冲突过滤 / limit / 透明标注
- **M5 API 全绿**: `tests/api/test_memory_api.py` — PATCH drafts 200/404/409/422 + preferences list/delete + stats 口径
- **M6 CLI 全绿**: `tests/cli/test_cli_memory.py`（**已登记 ci.yml integration-cli-backend**）— 信封/人类模式/退出码
- **M7 回归零破坏**: F27 drafts 既有测试（confirm/reject/update 语义）+ F6 context 既有测试 + deterministic 全路径零回归；覆盖率全仓 ≥60%（ADR-027 门禁 98.5/95.0）
- **M8 阈值正确（手工）**: 同一修改模式执行 2 次 PATCH → `inkflow memory list` 出现偏好；第 1 次 PATCH 后列表为空
- **M9 删除即停注入（手工）**: `inkflow memory remove <id>` 后立即 `write next --mode agentic` → 生成输出不含该偏好提示
- **M10 默认关闭零行为（手工）**: 未开启 memory_learning 的项目 PATCH drafts → memory_events 表无新行、`memory list` 为空、run 输出无「AI 已记住」
- **M11 修改率对照**: `inkflow memory stats --project-id` 输出修改率/重新生成率 + baseline_ref 引用；基线数据仍待填时标注「基线 N/A」（F27 Q3 拍板：随使用积累）

---

## 14. 待澄清问题

- **Q1: 偏好 pattern 分类维度** ✅ 已确认（用户拍板：选项 A，2026-08-11）
  - 背景：提取算法需将候选偏好归类（§5.2 步骤 3），分类维度决定注入展示形态（「AI 已记住：称呼主角为 X」的标题格式）与用户查看/删除的筛选入口（memory list --category）。
  - A. **4 类起步**（**已拍板**——覆盖 F27 冒烟观察到的核心修改类型：称呼/用词/结构 + 兜底；分类规则简单可测，后续可扩）
    - `addressing`（称呼习惯：人称/称谓替换）、`style_word`（风格用词：形容词/表达替换）、`structure`（结构偏好：段落/标题组织）、`other`（兜底）
  - B. 3 类（称呼/用词/其他——结构并入其他；规则更少但结构偏好丢失可读性）
  - C. 6 类（称呼/用词/句式/结构/标点/其他——更细但分类规则边界模糊，测试成本↑）
  - 建议：A（估算 4 类 vs 6 类：+0 人天；6 类分类器规则调试 +0.5 人天）
- **Q2: diff 事件存储形态** ✅ 已确认（用户拍板：选项 A，2026-08-11）
  - 背景：用户编辑/拒绝/确认行为产生的事件需要落库供提取与统计（§5.1/§5.3）。F27 agent_runs.steps 是**生成侧**决策轨迹（run 一次写入），用户编辑事件是**用户侧**行为记录（独立生命周期，可跨 run 累积、run 清理后仍需留存）。
  - A. **独立 memory_events 表**（**已拍板**——职责单一：生成侧 agent_runs 记录「AI 做了什么」，用户侧 memory_events 记录「用户改了什么」；source_events 可追溯；不触碰 F27 已交付表结构，跨模块零破坏）
  - B. 扩展 agent_run payload（steps JSON 内嵌用户编辑）——省一张表，但 run 是生成视角（一次 run 一次写回），用户编辑可跨多 run 多次发生、run 不存在时（直接编辑旧草稿）无处落；语义污染
  - C. 复用 audit_logs（severity_summary 扩展）——审计日志是旁路摘要（record 异常静默），不是结构化事件源；diff 提取需要 before/after 全文，audit summary 承载不了
  - 建议：A（估算 +0.5 人天 vs B 省表但语义债——与 F27 Q4 同构判断）
- **Q3: 透明提示形态** ✅ 已确认（用户拍板：选项 A，2026-08-11）
  - 背景：升级路径 Stage 2 用户可见功能 = 「AI 已记住：称呼主角为 X」式透明提示（§5.6）。F27 交付时 GUI 无 agentic 入口（F19 渲染层未排期），CLI/API 是当前唯一消费面。
  - A. **CLI 输出先行 + GUI 后续**（**已拍板**——`write next --mode agentic` 完成时人类模式打印「🤖 AI 已记住：...」，--json 信封 data.learned 数组；GUI toast/面板随 F19 渲染层接入，接口契约已预留（learned 字段））
  - B. CLI + API 响应都带 learned（API 响应字段已含——实现上无额外成本，其实只是 A 的自然延伸，无独立价值）
  - C. 仅 memory list 被动查看（无主动提示）——用户不主动看就不知道 AI 学了什么，违背「透明」目标
  - 建议：A（CLI 先行成本 ≈0.5 人天；C 省 0.5 人天但透明性目标落空）
- **Q4: 注入优先级冲突规则细化** ✅ 已确认（用户拍板：选项 A，2026-08-11）
  - 背景：升级路径风险表「偏好与显式设定冲突 → 显式设定（角色档案）优先级高于学习偏好」（§5.4.1）。冲突判定需要可测试的确定性规则。
  - A. **子串命中跳过**（**已拍板**——偏好 value 若已存在于同项目显式设定文本（角色档案/世界观/大纲经其他 sources 注入的内容），判定冲突 → 跳过该条注入；规则简单可测（RED 契约锁定），偏好本身保留可查可删）
  - B. 分类级跳过（addressing 类偏好整体跳过——粗暴，用户对称呼的学习被完全禁用，失去核心价值）
  - C. 偏好优先（学习偏好覆盖显式设定注入顺序——违背「显式设定 > 学习偏好」拍板原则，否决）
  - 补充：删除偏好立即生效（实时查库无缓存）为**既定设计**（§5.3/§5.4.1，验收判据③），无需拍板
  - 建议：A（冲突规则与删除语义正交；A 实现 ≈0 额外人天，B 负价值）

---

**完成门禁对照**（本 spec 交付时）：13 节 + §14 待澄清 Q1-Q4；围栏偶数；参照 F27 spec（493 行）体量目标 ≤800 行。

## 15. 动作确认

> 每个端点/命令的完整状态流表（基于 §3 + §4 + §5 + §7 事实，不重复）。

### 15.1 端点状态流

| 端点 | 前置条件 | 动作/状态转换 | 成功 | 失败 | 边界 |
|------|---------|--------------|------|------|------|
| PATCH /api/v1/agent/drafts/{draft_id} | 草稿存在且状态 draft | update_content（接线 F27 未接线的 update_content）+ diff 事件捕获（memory_learning=true 时，与内容更新同事务原子） | 200 + {draft_id, status: draft, word_count, learned} | 404（草稿不存在）；409（状态非 draft，DraftStateError）；422（content 空） | before==after 幂等不落事件不触发提取；memory_learning=false 零额外行为 |
| GET /api/v1/agent/preferences?project_id= | 项目存在 | 项目已学偏好列表 | 200 + {items, total} | — | — |
| DELETE /api/v1/agent/preferences/{preference_id} | 偏好存在 | 删除（立即停止注入） | 200 + {preference_id, deleted} | 404（偏好不存在） | 无缓存实时查库；删除后重新积累重新计数 |
| GET /api/v1/agent/memory/stats?project_id= | 项目存在 | 修改率统计（对照 F27 基线，验收判据①） | 200 + agentic/learned_preferences/baseline_ref | — | 基线无数据 → 标注「基线 N/A」 |

### 15.2 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow memory list --project-id [--category] [--json] | — | 偏好列表 | 每行「[addressing] 称呼主角为林晚 (confidence 0.67, ×2)」/ --json 信封 | 退出码 1（内核启动失败/HTTP 错误） | 恒经 HTTP（F38，ensure_kernel + InkFlowHTTPClient） |
| inkflow memory remove &lt;preference_id&gt; [--json] | 偏好存在 | 删除 | 「✅ 已删除偏好（下次生成立即停止注入）」 | 404 → 退出码 1 | — |
| inkflow memory stats --project-id [--json] | — | 修改率/重新生成率 + 基线对照 | 「agentic 修改率 60%（基线 N/A——F27 基线随使用积累，见 design/agent-baseline-2026-08-10.md）」 | 退出码 1 | 只统计 agentic 模式 |
| inkflow write next --mode agentic [--memory-learning|--no-memory-learning] | 项目/章节存在 | 生成 + 偏好学习开关覆盖 | 本轮学习到新偏好时人类模式追加「🤖 AI 已记住：称呼主角为林晚（下次生成将遵循）」；--json 信封 data 追加 learned 数组 | 退出码 1 | 请求显式 &gt; extra 键 &gt; 默认 false（F13 同构） |

### 15.3 验收锚点

- A1：阈值语义——第 1 次修改不学 / 第 2 次同学 → 偏好落库 + learned=true + 审计 preference_learned（M1/M8）
- A2：memory_learning=false 零行为——无事件/无提取/无审计/collect 返回 []/无「AI 已记住」（M10）
- A3：删除偏好后立即生成 → 注入不含该条（M9）
- A4：PATCH drafts 200/404/409/422 + preferences list/delete 200/404 + stats 口径（M5）
- A5：冲突过滤（偏好 value 命中显式设定文本 → 跳过）+ 单条 ≤200 字符 + 最多 10 条 + title 恒「AI 已记住」（M4）
- A6：修改率统计输出 + baseline_ref 引用（M11）
