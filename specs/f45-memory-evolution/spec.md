# F45: 记忆系统 AI 总结演进（memory-evolution）功能规格

**Spec 版本**: 1.1（Q1=B/Q2=B/Q3=A 拍板固化）
**日期**: 2026-08-17
**依据**: 设计定稿（design/agentic-orchestrator-and-memory-design-2026-08-14.md §3 记忆系统演进，唯一真相）+ Issue #339（M1 用户级偏好层）+ Issue #340（M2 语义风格提取）+ F28 spec v1.0（specs/f28-agent-memory/spec.md，演进基线）+ 用户拍板（2026-08-14 两段式架构 / 记忆演进独立排期）+ LLM 配置拍板（#415，2026-08-16）
**所属阶段**: 0.10.0（记忆系统 AI 总结演进，F45），估算 M1 4-6 人天 + M2 6-8 人天（合计 10-14 人天）
**关联 Issues**: #339（M1 用户级偏好层 + 归属分层 + 跨项目聚合）· #340（M2 语义风格提取——difflib 锚点 → LLM 语义总结）
**依赖**: ✅ F28 agent-memory（演进基线：project_preferences/memory_events/learner/memory_service/PreferenceSource，PR #242）· ✅ F6 context-service（注入端口 ContextSourceType/SOURCE_LAYER）· ✅ F16 style-service（LLM 模板管线样板 _style_llm_analyzer）· ✅ F32 settings-persistence（app_settings 分层对照）· ✅ #415（LLM 默认模型 deepseek/deepseek-v4-flash，配置唯一默认源）· ✅ F38（CLI 恒 HTTP）· ✅ F34（audit_logs）· ⏳ M2 依赖 M1（#339 → #340）
**参考 ADR**: adr/ADR-037.md（记忆提取方式：规则化先行 + LLM 第二阶段）、adr/ADR-038.md（memory_learning 默认 false）、adr/ADR-031.md（双模式开关 extra 键）、ADR-027（覆盖率门禁）
**状态**: ✅ 已实现（PR #442/#452）

> **Spec 变更**: v1.0→v1.1（2026-08-17 用户拍板固化）：Q1=B（用户级偏好**惰性重算**——删除钩子零成本，查询/collect 时重算 + user-list 幽灵项目过滤，§5.1/§7/§13 联动）· Q2=B（注入前**惰性总结 + 后台异步刷新**——先用旧总结注入不等待 LLM，M2 硬依赖 F44 阶段4 后台任务基建，后台就位前降级同步总结过渡，§5.4/§11 联动）· Q3=A（用户级偏好注入过**显式设定冲突过滤**，§5.6 已覆盖，仅标 ✅）

> **模块类型声明**: 本模块为「**偏好学习闭环型（AI 语义总结演进）**」变体——F28（第 12 变体）的演进升级，补齐两段式架构的 LLM 后半截。与 F28 纯函数 difflib 不同：F45 新增**用户级偏好层**（user_preferences 全局表 + 归属分层 + 跨项目聚合）+ **语义风格提取**（difflib 锚点 → LLM 抽象偏好，替代字面片段注入）。编号依据：按「最新无冲突基线」接续——F46=第 19 变体为当前最新无冲突基线，本模块声明**第 20 变体**（冲突以 ADR-019 v5+ 为准；F44 编排器为并行轨独立声明）。

---

## 1. 概述

F45 交付设计定稿 §3 的记忆系统演进：把 F28 的「纯函数 difflib 字面片段记忆」升级为「difflib 证据收集 + LLM 语义总结」的两段式架构，并引入用户级（跨项目）偏好层。**架构论断（设计定稿 §3.2）**：规则化 difflib 字面片段无法安全跨项目——不理解语义，会把「她→林晚」这类项目特有设定原样搬到别的项目 = 幻觉；AI 总结是安全跨项目的前提（LLM 能分离「项目特有设定」与「用户通用风格」）。

### 1.1 两段式闭环定位（设计定稿 §3.3）

```
F28 事件捕获（用户编辑/确认/拒绝草稿 → memory_events）
  → 第一段：difflib 证据收集（确定性零成本）
      产出「用户反复修改的片段」作为锚点（堵幻觉 B——防 LLM 编造偏好）
  → 第二段：LLM 语义总结（锚定证据，不自由发挥）
      产出「抽象偏好」（风格/习惯/称谓规则）（堵幻觉 A——防字面碎片注入下游被错误套用）
  → 注入：抽象风格指令（替代 F28 的字面碎片「AI 已记住：她（林晚）」）
  → 下次 agentic 生成自动遵循 → 用户修改减少 → 越用越智能
```

### 1.2 演进拆分（设计定稿 §3.5）

| 演进项 | Issue | 内容 | 学习价值 |
|--------|-------|------|---------|
| **M1 用户级偏好层** | #339 | `user_preferences` 表（全局）+ 归属分层（用户级/项目级）+ 跨项目聚合 | 中（归属语义设计） |
| **M2 语义风格提取** | #340 | difflib 筛片段（锚点）→ LLM 归纳抽象风格 → 注入为「风格指令」而非碎片 | 高（agent 记忆最核心的一课） |

**依赖**：M2 依赖 M1（先有跨项目聚合，LLM 才有跨项目证据可总结）。M2 建议接编排器阶段 4（长跑）之后——长跑产生大量修改证据喂给 difflib 锚点；但**不硬阻塞**：可先用 F28 既有证据跑通（设计定稿 §5）。（Q2=B 拍板后补充：证据喂料仍软咬合；但 M2 惰性总结的后台异步刷新**硬依赖** F44 阶段4 后台任务框架——后台就位前 M2 降级「注入前同步总结」过渡，见 §5.4/§11。）

### 1.3 与既有模块的边界

- **归属边界（M1 核心）**：偏好归属分两层——**项目级**（该项目 difflib 片段 N≥2 → 该项目风格偏好：称谓规则/结构习惯/文风，该项目内每次写作注入）+ **用户级**（多项目 difflib 片段聚合 → 用户通用风格：句长/冗余/叙述对话比例，所有项目注入）。LLM 总结时显式区分「项目特有设定」（留在项目级）与「用户通用风格」（升到用户级）——这是 LLM 语义能力才能做的事（设计定稿 §3.4）。
- **开关边界**：沿用 F28 `memory_learning` 显式开启铁律（adr/ADR-038.md，默认 false）——false 时 M1/M2 全路径零行为（不捕获/不聚合/不总结/不注入）。
- **注入边界**：抽象偏好仍经 F6 context 端口注入（扩展既有 PreferenceSource，不直接改 system prompt）。
- **配置边界**：M2 的 LLM 语义总结遵循 #415 拍板——`config.py` 为唯一默认源（`llm_default_model` = deepseek/deepseek-v4-flash），**代码不写第二份默认值**，env 优先覆盖。
- **明确不含**：向量化检索、偏好自动过期/置信度衰减、GUI 记忆面板（F19 渲染层接入时）、F29 supervisor 记忆消费、编排器长跑证据喂料（F44 咬合，见 §10）。

### 1.4 与 F28 的差异

| 维度 | F28（现状） | F45（演进后） |
|------|------------|--------------|
| 归属 | 仅项目级（project_preferences） | 项目级 + 用户级（user_preferences 全局表） |
| 跨项目 | 显式隔离（跨项目不混算） | 跨项目聚合（保守规则：同 (category, value) 在 ≥2 项目出现才升用户级） |
| 提取 | 纯函数 difflib（规则化） | difflib 证据收集（保留）+ LLM 语义总结（新增，M2） |
| 注入 | 字面碎片「AI 已记住：她（林晚）」 | 抽象风格指令「叙述偏好：用角色全名而非代词」（M2） |
| 表 | project_preferences + memory_events | + user_preferences（M1）+ semantic_summaries（M2） |

---

## 2. 数据模型

### 2.1 归属分层模型（M1 核心设计决策：独立表）

**决策：`user_preferences` 独立新表**（不扩 project_preferences 加列、不做表内迁移）。论证见 §12 决策表首行。

| 方案 | 说明 | 否决理由 |
|------|------|---------|
| **A. 独立 user_preferences 表**（✅ 采纳） | 全局表（无 project_id），存用户级偏好 | — |
| B. project_preferences 加 scope 列 + project_id 可空 | 一表两用 | 语义混载：项目级偏好按项目隔离、用户级全局注入，过滤条件分叉（scope 判断 + project_id 判断）贯穿 repo/service/API/CLI 全部消费方，复杂度集中到一表；F28 已交付表结构被 MODIFY，跨模块回归面大 |
| C. 加 user_id 列（多用户） | 为多用户预留 | InkFlow 单用户本地优先（P1）；YAGNI |

**归属分层语义（可测试）**：

```
项目级偏好（project_preferences，F28 不动）：
  聚合键 = (project_id, category, value)，该项目内 N≥2 落库
  注入范围 = 该项目内每次写作

用户级偏好（user_preferences，M1 新增）：
  聚合键 = (category, value) 全局聚合（跨项目），且支撑项目数 ≥2 才落库
  注入范围 = 所有项目（memory_learning 开启时）
  「不混算项目特有设定」规则：仅 1 个项目出现的 (category, value) 绝不升用户级
```

### 2.2 领域模型（新增 `domain/models/user_preference.py`）

```python
class UserPreference(BaseModel):
    """一条已学习的用户级偏好（全局跨项目，M1 新增）。

    Attributes:
        id: 偏好 UUID 字符串（uuid4）.
        category: 分类维度（复用 F28 PreferenceCategory 四类）.
        pattern: 模式描述（被替换的旧文本片段，difflib 锚点）.
        value: 偏好值（用户反复修改后保留的新文本）.
        confidence: 置信度（0-1，随 count 增长单调递增）.
        count: 支撑事件数（跨项目累计，≥2 且项目数 ≥2 才落库）.
        project_count: 支撑项目数（≥2 才落库——保守规则防混算）.
        source_projects: 支撑项目 id 列表（跨项目追溯）.
        source_events: 支撑事件 id 列表（memory_events.id，可追溯）.
        created_at: 创建时间（UTC）.
        updated_at: 最后更新时间（UTC）.
    """
    model_config = {"from_attributes": True}

    id: str
    category: PreferenceCategory
    pattern: str
    value: str
    confidence: float
    count: int
    project_count: int
    source_projects: list[str] = []
    source_events: list[str] = []
    created_at: datetime
    updated_at: datetime
```

### 2.3 语义总结模型（M2 新增 `domain/models/semantic_summary.py`）

```python
class SummaryScope(StrEnum):
    """语义总结的归属范围（M2 两层归属落地）. """
    PROJECT = "project"      # 项目级风格偏好（称谓规则/结构习惯/文风）
    USER = "user"            # 用户级通用风格（句长/冗余/叙述对话比例）

class SemanticSummary(BaseModel):
    """一次 LLM 语义总结的产物（锚定 difflib 证据，不自由发挥）.

    Attributes:
        id: 总结 UUID 字符串（uuid4）.
        scope: 归属范围（project/user）.
        project_id: scope=project 时的项目 UUID；scope=user 时为 None.
        content: 抽象风格指令文本（LLM 产出，如「叙述偏好：用角色全名而非代词」）.
        anchor_hash: 锚点集合哈希（difflib 证据指纹——锚点未变化时复用总结，
            锚点变化触发重新总结，防陈旧）.
        anchor_count: 锚点数（证据量，可解释性）.
        model: 生成模型（config.llm_default_model 读取，不硬编码）.
        created_at: 创建时间（UTC）.
        updated_at: 最后更新时间（UTC）.
    """
    model_config = {"from_attributes": True}

    id: str
    scope: SummaryScope
    project_id: uuid.UUID | None = None
    content: str
    anchor_hash: str
    anchor_count: int
    model: str
    created_at: datetime
    updated_at: datetime
```

### 2.4 ORM（新增 `infrastructure/database/models/user_preference.py`）

| 表 | 关键列 | 说明 |
|----|--------|------|
| `user_preferences` | id(String36 PK) / category(String20 idx) / pattern(Text) / value(Text) / confidence(Float) / count(Integer) / project_count(Integer) / source_projects(JSON) / source_events(JSON) / created_at / updated_at | 用户级偏好表（M1）；无 project_id 列（全局表）；无 FK（镜像 project_preferences 先例） |
| `semantic_summaries` | id(String36 PK) / scope(String20) / project_id(String36 nullable) / content(Text) / anchor_hash(String64) / anchor_count(Integer) / model(String100) / created_at / updated_at | 语义总结表（M2）；project_id 无 FK；scope=user 时 project_id=None |

> 决策论证：`source_projects`/`source_events` 用 JSON 数组（镜像 F28 project_preferences.source_events 先例，F27 §2.3 agent_runs.steps JSON 快照语义）；`anchor_hash` 为锚点集合的确定性指纹（SHA-256 of 排序锚点键），使「锚点是否变化 → 是否需要重新总结」可测（§5.4）。

### 2.5 分层对照：app_settings vs 写作偏好记忆（#339 要点）

| 层 | 承载 | 语义 | 来源 | 归属 |
|----|------|------|------|------|
| **应用级设置** | `app_settings`（F32） | UI/行为全局设置（theme/bg/lang/font 等，固定 6 项） | 用户显式设置（设置页） | 全局用户设置 |
| **项目级写作偏好** | `project_preferences`（F28） | 该项目写作习惯（称谓/结构/文风） | 用户在该项目内的修改行为（difflib 学习） | 项目 |
| **用户级写作偏好** | `user_preferences`（M1） | 用户通用写作风格（句长/冗余/叙述比例） | 多项目修改行为跨项目聚合（difflib 学习） | 用户（跨项目） |

> 三层互不重叠：app_settings 是**显式设置**（用户主动配置，key-value 无自由扩展键）；写作偏好是**隐式学习**（用户修改行为反向提炼，结构化偏好）。M1 不触碰 F32 表结构。

### 2.6 复用既有模型

- `PreferenceCategory`（F28）：分类维度四类复用（addressing/style_word/structure/other）。
- `MemoryEvent` / `MemoryEventType`（F28）：M1 跨项目聚合的证据源（event.project_id 区分项目）。
- `ProjectPreference`（F28）：项目级偏好保持不动（演进基线）。
- `ContextItem` / `ContextSourceType`（F6）：抽象偏好注入载体（§5.6）。
- `ProjectConfig.extra`（F1）：`memory_learning` 开关键复用（§5.5）。

---

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 说明 | 状态 |
|------|------|------|------|
| GET | `/api/v1/agent/preferences?project_id=` | 项目级偏好列表（F28 既有，不动） | 既有 |
| DELETE | `/api/v1/agent/preferences/{preference_id}` | 删除项目级偏好（F28 既有，不动） | 既有 |
| GET | `/api/v1/agent/user-preferences` | 用户级偏好列表（全局跨项目，M1 新增） | 新增 |
| DELETE | `/api/v1/agent/user-preferences/{preference_id}` | 删除用户级偏好（立即停止全局注入，M1 新增） | 新增 |
| GET | `/api/v1/agent/memory/summaries?project_id=` | 项目级 + 用户级语义总结（M2 新增，返回两层的抽象风格指令） | 新增 |
| POST | `/api/v1/agent/memory/summarize?project_id=` | 手动触发语义总结（M2 新增；幂等——锚点未变化返回既有总结） | 新增 |
| GET | `/api/v1/agent/memory/stats?project_id=` | 修改率统计（F28 既有，M1 扩展 user 层计数） | MODIFY |

> 约束：既有 F28 preferences/stats 端点语义零改动（项目级）；新增端点挂 `/api/v1/agent/` 前缀（同 memory.py router，职责单一延续）。

### 3.2 请求/响应示例

```json
GET /api/v1/agent/user-preferences
→ 200 {"items": [{"id": "uuid", "category": "style_word",
                  "pattern": "说", "value": "低声道",
                  "confidence": 0.75, "count": 3, "project_count": 2,
                  "source_projects": ["uuidA", "uuidB"],
                  "source_events": ["uuid1", "uuid2", "uuid3"],
                  "created_at": "..."}],
       "total": 1}

DELETE /api/v1/agent/user-preferences/{preference_id}
→ 200 {"preference_id": "uuid", "deleted": true}

GET /api/v1/agent/memory/summaries?project_id=uuid
→ 200 {"project_id": "uuid",
       "project": {"content": "叙述偏好：称呼主角用全名「林晚」而非代词；章节开头用场景描写而非直接对话",
                   "anchor_count": 5, "model": "deepseek/deepseek-v4-flash", "updated_at": "..."},
       "user": {"content": "用户通用风格：句长偏短（≤20 字为主）、叙述/对话比例约 6:4、避免冗余修饰",
                "anchor_count": 12, "model": "deepseek/deepseek-v4-flash", "updated_at": "..."}}

POST /api/v1/agent/memory/summarize?project_id=uuid
→ 200 {"project_id": "uuid", "summarized": true,
       "project": {"content": "...", "anchor_hash": "sha256...", "anchor_count": 5},
       "user": {"content": "...", "anchor_hash": "sha256...", "anchor_count": 12}}
   // 幂等：锚点未变化 → {"summarized": false, ...既有总结}
```

### 3.3 异常映射表

| 场景 | HTTP | 错误码/说明 |
|------|------|-------------|
| 用户级偏好不存在（DELETE） | 404 | 复用 F28 PreferenceNotFoundError 语义 |
| project_id 非法 | 404 | `_parse_id` 复用（F27 先例） |
| LLM 调用失败（summarize） | 502 | 新错误面 SemanticSummaryError（镜像 F16 StyleLLMAnalysisError 500 语义，502 表示上游 LLM 故障） |
| LLM 输出不可解析（重试 2 次仍失败） | 502 | SemanticSummaryError（模板 JSON 契约 + 修复式重试，§5.4） |
| memory_learning=false（summaries/summarize） | 200 空 | 返回空结构（project/user 均为 None，零行为语义） |

---

## 4. CLI 命令签名

### 4.1 `inkflow memory` 顶层命令组扩展（MODIFY `cli/commands/memory_cmd.py`）

```text
inkflow memory list --project-id <UUID> [--category ...] [--json]          # F28 既有（项目级）
inkflow memory user-list [--category ...] [--json]                          # M1 新增：用户级偏好列表（全局）
   人类模式: 每行「[style_word] 说 → 低声道 (confidence 0.75, ×3, 2 项目)」
   --json 信封: {"ok": true, "data": {"items": [...], "total": N}}

inkflow memory remove <preference_id> [--json]                             # F28 既有（项目级）
inkflow memory user-remove <preference_id> [--json]                         # M1 新增：删除用户级偏好
   删除后打印: ✅ 已删除用户级偏好（所有项目生成立即停止注入）

inkflow memory summarize --project-id <UUID> [--force] [--json]             # M2 新增：手动触发语义总结
   --force: 忽略锚点哈希强制重新总结（默认锚点未变化返回既有总结）
   人类模式: 「✅ 已生成项目级风格摘要（5 锚点）」「✅ 已生成用户级风格摘要（12 锚点）」
            或「ℹ️ 锚点未变化，复用既有摘要（--force 强制重新总结）」

inkflow memory stats --project-id <UUID> [--json]                           # F28 既有（M1 扩展输出 user 层计数）
   扩展输出: 「用户级偏好: N 条（跨 M 项目）」追加在既有输出后
```

> 恒 HTTP 纪律（F38）：`memory` 命令全部经 ensure_kernel() + InkFlowHTTPClient 调内核 REST API，镜像 F28 memory_cmd.py `_run`/`_print_json_envelope` 同构（不动现有模式，仅追加子命令）。

### 4.2 `inkflow write next` 扩展（MODIFY `cli/commands/write.py`）

```text
inkflow write next --project-id <UUID> --chapter-id <UUID> --outline <文本>
                   [--mode agentic] [--memory-learning|--no-memory-learning]
   不变（F28 既有）；M2 注入形态升级后：
   agentic 模式下（memory_learning 开启且存在语义总结）:
     人类模式追加打印: 🧠 风格指令：叙述偏好用角色全名而非代词（AI 语义总结）
```

---

## 5. 关键差异节：两段式记忆演进（difflib 证据收集 + LLM 语义总结）

### 5.1 第一段：difflib 证据收集（M1 保留 + 用户级扩展）

**现状（F28 实现实证）**：`preference_learner.aggregate_candidates(events)` 聚合键 = `(event.project_id, category, value)`，**跨项目不混算**（同 value 在不同项目各自独立计数）。

**M1 扩展（`preference_learner.py` 新增用户级聚合）**：

```
新增 aggregate_user_candidates(events: list[MemoryEvent]) -> list[UserPreferenceCandidate]:
  1. 取全部 DRAFT_EDITED 事件（跨项目，同一调用点 record_draft_edit 已有全量证据）
  2. 每事件 extract_edits(before, after) → (category, value) 片段
  3. 聚合键 = (category, value)（无 project_id 维度）
  4. 组内统计: count = 事件数（跨项目累计）、projects = {event.project_id} 集合
  5. project_count = len(projects)
  6. 阈值: count ≥ 2 且 project_count ≥ 2 才产出（保守规则——「跨项目不混算」落地）
     → 仅 1 个项目出现的 (category, value) 永不升用户级
  7. confidence = confidence_for(count)（复用 F28 公式）
```

**关键：不重复 difflib 计算**——`aggregate_user_candidates` 与 `aggregate_candidates` 共享 `extract_edits` 纯函数（同一片段对，两种聚合维度）；record_draft_edit 一次 difflib 提取，项目级 + 用户级两条聚合链并行。

**落库语义（MemoryService 扩展）**：

| 场景 | 项目级（F28 既有） | 用户级（M1 新增） |
|------|-------------------|------------------|
| 同 value 第 1 次出现（单项目） | 事件落库，无偏好 | 不落库（project_count=1 < 2） |
| 同 value 第 2 次出现（同项目） | 偏好落库（count=2） | 仍不落库（project_count=1） |
| 同 value 在第 2 个项目出现 | 各自项目偏好更新 | **用户级偏好落库**（count=2, project_count=2） |
| 同 value 在第 3 个项目出现 | 各自项目偏好更新 | 用户级 count+1, project_count+1, confidence 重算 |
| 项目被删除（source_projects 含被删项目） | 不影响（既有偏好保持） | **惰性重算（Q1=B）**：删除钩子零成本不动 user_preferences；查询/collect 时发现已删项目 → 重算（移除该项目；project_count<2 → 删该偏好，降级回项目级证据不足），user-list 查询时过滤幽灵项目来源（§7） |

### 5.2 M1 开关与零行为

沿用 F28 `memory_learning` 读取优先级（请求显式 > extra 键 > 默认 false，adr/ADR-038.md）：

- false（默认）→ `aggregate_user_candidates` 不调用、user_preferences 无写入、无用户级注入、无额外审计（零行为，F28 验收判据④同构扩展到 M1）。
- **零行为可测（RED 契约）**：未开启 memory_learning 的项目编辑草稿 → user_preferences 表无新行、user-list 为空、注入不含用户级条目。

### 5.3 第二段：LLM 语义总结（M2 核心）

**输入（锚点，difflib 证据）**：
- 项目级：该项目 `project_preferences`（N≥2 已落库的 difflib 片段）
- 用户级：全局 `user_preferences`（跨项目 N≥2 + 项目数≥2 的片段）

**用户级总结的全局单一性**：`semantic_summaries` 中 scope=user 的记录**全局仅一份**（project_id=None）。任何项目触发 summarize 时，用户级部分检查的是**全局 user_preferences 锚点哈希**（与调用项目无关）——锚点变化则更新同一份全局记录；项目级部分按调用项目独立检查/落库。两层的锚点哈希分别计算（§5.4）。

**LLM 总结管线（镜像 F16 `_style_llm_analyzer.py` 骨架，替换模板与领域实体）**：

```
① 锚点为空 → 不调用 LLM，返回 None（无总结语义）
② 渲染 memory_semantic_summary.yaml（PromptManager，变量 {anchors}）
③ LLMClient.chat(model=config.llm_default_model, temperature=0.2)
   —— model 从 config 读取，代码不写第二份默认值（#415）
④ 解析 JSON（容忍代码块围栏/前后缀文字，复用 F16 _extract_json_fragment 逻辑）
   → 校验结构: {"project_specific": [...], "user_general": [...]} 两组
⑤ 修复式重试 ≤ 2 次（附错误信息）→ 仍失败 → SemanticSummaryError（502）
⑥ content 截断 ≤ 2000 字符 → 落库 SemanticSummary（anchor_hash/anchor_count 记录）
```

**防幻觉双向堵（设计定稿 §3.3，验收核心）**：

| 幻觉方向 | 堵法 | 落地点 |
|---------|------|--------|
| A. 字面碎片注入下游被错误套用 | LLM 产出抽象偏好（风格/习惯/称谓规则），注入形态 = 风格指令非碎片 | §5.6 注入形态 |
| B. LLM 编造证据之外的偏好 | difflib 锚点先筛（确定性地找到「用户反复修改的片段」），LLM 锚定证据不自由发挥 | ① 锚点 = 已落库偏好（N≥2 实证）；② prompt 显式约束「只归纳给定锚点呈现的偏好，禁止臆造」；③ **验收判据（#340）**：给定修改证据集 → LLM 产出可解释抽象偏好，且不编造证据之外的偏好——RED 契约用 mock LLM 注入「编造输出」验证被拒（见 §5.3.1） |

#### 5.3.1 防幻觉 B 的测试契约（M2 RED 主场景）

mock LLM 返回包含「证据集之外偏好」的输出（如证据全为「她→林晚」，LLM 却输出「用户喜欢用比喻修辞」）→ 总结管线**拒绝该条**（模板校验：每条抽象偏好必须可回溯到至少 1 个锚点——实现为 prompt 要求 LLM 每条偏好附 `anchor_refs`（引用的锚点 value 列表），程序校验 anchor_refs ⊆ 锚点集；不通过 → 该条丢弃 + 记审计）。这是「不编造证据之外偏好」的可测试落地。

### 5.4 锚点哈希与陈旧复用（M2）

- `anchor_hash` = SHA-256(排序锚点键列表)（锚点键 = `(category, value)` 序列化）。
- **幂等总结**：summarize 时先计算当前锚点哈希，与既有 SemanticSummary.anchor_hash 相同 → 不调 LLM，返回既有总结（`summarized: false`）。
- **注入前惰性总结 + 后台异步刷新（Q2=B 拍板）**：PreferenceSource.collect 时若锚点哈希 ≠ 既有总结哈希 → **先用旧总结注入**（注入不等待 LLM，零阻塞）+ 审计 pending_summary（§7 边界表）→ **后台异步刷新**：后台任务基建（F44 阶段4）就位后，由后台任务重新总结并更新总结记录。
- **两段式过渡（Q2=B）**：后台任务基建（F44 阶段4）就位前，M2 降级为「注入前同步总结」临时兜底——collect 时锚点变化 → 同步调 LLM 总结后再注入（LLM 失败回退旧总结 + 字面兜底，不阻断注入）；F44 阶段4 落地后自动切换回「惰性总结 + 后台异步刷新」。避免 M2 被 F44 阶段4 硬卡。
- 锚点变化后的总结时机已拍板（Q2=B：惰性总结 + 后台异步刷新；成本 vs 新鲜度权衡见 §14 Q2 留痕）。

### 5.5 开关（M2 语义总结沿用 memory_learning + 无独立新开关）

| 层级 | 键/字段 | 默认 | 说明 |
|------|---------|------|------|
| 项目配置 | `project.config.extra["memory_learning"]` | false | 复用 F28（adr/ADR-038.md）——M2 总结/注入一并受控 |
| LLM 模型 | `config.llm_default_model` | deepseek/deepseek-v4-flash | #415 拍板：配置文件唯一默认源，代码不写第二份默认值，env 优先 |

> 不新增独立「语义总结开关」（YAGNI）：memory_learning=true 即开启 M1+M2 全链路（差异仅在注入形态——M2 阶段语义总结优先、字面偏好兜底，§5.6）。

### 5.6 注入（扩展 F6 PreferenceSource）

**M1 阶段（无 LLM）**：PreferenceSource.collect 注入项目级 + 用户级字面偏好（用户级条目 title 前缀「AI 已记住（全局）：{pattern}」区分归属）。

**M2 阶段（语义总结优先）**：

```
PreferenceSource.collect(project_id, chapter_id):
  1. memory_learning=false → 返回 []（零行为）
  2. 查询项目级 SemanticSummary（scope=project, project_id）
  3. 查询用户级 SemanticSummary（scope=user, project_id=None）
  4. 注入优先级:
     a. 项目级语义总结（若存在）→ ContextItem 风格指令（title=「🧠 项目风格：」）
     b. 用户级语义总结（若存在）→ ContextItem 风格指令（title=「🧠 通用风格：」）
     c. 无语义总结时 → 回退 F28 字面偏好注入（项目级 + 用户级，保底不丢失记忆）
  5. 冲突过滤沿用 F28 Q4 规则（value 命中显式设定文本 → 跳过；项目级/用户级条目同规则过滤，Q3=A 已确认）
  6. 预算: 单条 ≤ 200 字符 + 最多 10 条（F28 既有防护延续）
```

**归属可视化**：注入 title 区分「项目风格」（该项目写作）vs「通用风格」（跨项目用户习惯）——用户可辨「AI 学到了什么、从哪学来」。

### 5.7 审计与透明提示（M1/M2 扩展）

- **审计**（复用 F34 audit_logs）：用户级偏好落库（`user_preference_learned`）、用户级偏好删除（`user_preference_removed`）、语义总结生成（`semantic_summary_generated`）、总结失败（`semantic_summary_failed`，degraded=True）——actor="memory"，异常静默旁路（F28 语义延续）。
- **透明提示**：CLI 追加「🧠 风格指令」输出（§4.2）；`--json` 信封 data 追加 `"semantic_summaries": {...}` 字段（GUI 后续接入预留）。

---

## 6. 组织规则

- 用户级聚合纯函数放 `domain/services/preference_learner.py`（新增 `aggregate_user_candidates`，与既有 `aggregate_candidates` 共享 `extract_edits`）；编排扩展放 `domain/services/memory_service.py`（注入 user_repo/summary_repo，不碰 ORM）。
- LLM 语义总结放 `domain/services/semantic_summarizer.py`（纯管线：模板渲染 → LLM → JSON 解析 → 修复重试，零框架 import——ADR-015 领域层零 LangChain，经 Protocol 注入 LLMClientProtocol/PromptTemplateProtocol，镜像 F16 `_style_llm_analyzer.py`）。
- 领域模型：`domain/models/user_preference.py`、`domain/models/semantic_summary.py`（纯 Pydantic，零 infrastructure import）。
- repo：`infrastructure/database/repositories/user_preference_repo.py`、`semantic_summary_repo.py`（异步 SQLAlchemy，镜像 F28 repo 形态）；ORM 转换函数在 repo 层。
- 注入源：`infrastructure/context/preference_source.py` MODIFY（M2 语义总结优先 + 字面兜底）。
- API：`api/routers/memory.py` MODIFY（追加 user-preferences/summaries/summarize 端点）。
- CLI：`cli/commands/memory_cmd.py` MODIFY（追加 user-list/user-remove/summarize）；`cli/commands/write.py` MODIFY（🧠 输出）。
- 模板：`infrastructure/llm/templates/memory_semantic_summary.yaml` 新增（PromptManager 加载，ADR-014 惯例）。
- 开关读取：memory_service + PreferenceSource 各自实时读 project_repo（无缓存，删除立即生效语义延续）。

---

## 7. 边界情况与错误处理

| 场景 | 行为 | 错误面 |
|------|------|--------|
| memory_learning=false（默认） | M1/M2 全路径零行为：不聚合用户级、不总结、不注入、无审计 | 无（零行为） |
| 仅 1 项目出现的 (category, value) | 只落项目级，永不升用户级（保守规则） | 无 |
| 用户级偏好删除后立即生成 | collect 实时查库 → 不含该条（全局立即生效） | 无 |
| 项目被删除 | 服务层级联清理：该项目 project_preferences/memory_events（F28 既有，删除钩子不变）；用户级偏好**惰性重算**（Q1=B 拍板）——删除钩子零成本不动 user_preferences；collect/查询时发现 source_projects 含已删项目 → 重算（移除该项目；project_count<2 → 删该偏好，降级回项目级证据不足）；user-list 查询时过滤幽灵项目来源 | 无（F27 先例） |
| 全部项目被删除 | 惰性（Q1=B）：下次查询/collect 时逐条重算，全部 project_count<2 → user_preferences 全清；semantic_summaries 清空（scope=user） | 无 |
| 锚点为空（无任何已学偏好） | summarize 不调 LLM，返回 None；注入回退字面（也无字面可注入 → []） | 无 |
| LLM 调用失败（summarize/summaries） | 502 SemanticSummaryError；**注入路径不受阻**——collect 回退字面偏好（保底） | HTTP 错误（502） |
| LLM 输出不可解析（重试 2 次仍失败） | 502；审计 semantic_summary_failed | HTTP 错误（502） |
| LLM 编造证据之外偏好（anchor_refs 校验失败） | 该条丢弃 + 审计（防幻觉 B，§5.3.1） | 无（静默丢弃，保留锚点） |
| 锚点变化但总结未刷新 | collect 先用旧总结注入 + 审计 pending_summary → 后台异步刷新（Q2=B 拍板；后台任务基建 F44 阶段4 就位后）；基建就位前降级「注入前同步总结」兜底 | 无（降级不阻断） |
| 用户级偏好与某项目显式设定冲突 | 该项目注入时跳过该条（F28 Q4 规则延续） | 无（偏好保留可查） |
| 偏好 value 为空/纯标点 | 过滤（F28 提取规则复用） | 无 |
| 单条内容超预算 | 截断 ≤ 200 字符（F28 防护延续） | 无 |
| 事件落库失败（DB 故障） | 编辑动作仍成功（F28 事件捕获旁路语义） | 无（不阻断用户编辑） |

---

## 8. 文件结构

### M1（#339）

| 动作 | 文件 | 说明 |
|------|------|------|
| CREATE | `backend/src/inkflow/domain/models/user_preference.py` | UserPreference 领域模型 |
| CREATE | `backend/src/inkflow/infrastructure/database/models/user_preference.py` | UserPreferenceORM |
| CREATE | `backend/src/inkflow/infrastructure/database/repositories/user_preference_repo.py` | user_preferences 异步仓储（list_all/delete/get/create/update/delete_by_project_ref） |
| MODIFY | `backend/src/inkflow/domain/services/preference_learner.py` | 新增 aggregate_user_candidates（共享 extract_edits） |
| MODIFY | `backend/src/inkflow/domain/services/memory_service.py` | record_draft_edit 追加用户级聚合链 + user_preferences CRUD + stats 扩展 user 层计数 |
| MODIFY | `backend/src/inkflow/api/routers/memory.py` | user-preferences GET/DELETE 端点 |
| MODIFY | `backend/src/inkflow/cli/commands/memory_cmd.py` | user-list/user-remove 子命令 |
| MODIFY | `backend/src/inkflow/infrastructure/context/preference_source.py` | collect 注入用户级字面偏好（M1） |
| MODIFY | `backend/src/inkflow/api/deps.py` | user_preference_repo/memory_service 装配扩展 |
| CREATE | `backend/tests/unit/test_user_preference_learner.py` | 用户级聚合契约（阈值/保守规则/跨项目） |
| CREATE | `backend/tests/unit/test_user_preference_repo.py` | user_preferences 仓储集成（真实 SQLite） |
| CREATE | `backend/tests/unit/test_memory_service_user.py` | M1 编排契约（零行为/落库/删除/项目删除惰性重算 + 幽灵项目过滤） |
| MODIFY | `tests/api/test_memory_api.py` | user-preferences 端点契约 |
| MODIFY | `tests/cli/test_cli_memory.py` | user-list/user-remove 契约（**已登记 ci.yml integration-cli-backend**） |

### M2（#340）

| 动作 | 文件 | 说明 |
|------|------|------|
| CREATE | `backend/src/inkflow/domain/models/semantic_summary.py` | SemanticSummary/SummaryScope 领域模型 |
| CREATE | `backend/src/inkflow/domain/services/semantic_summarizer.py` | LLM 语义总结管线（镜像 F16 _style_llm_analyzer 骨架） |
| CREATE | `backend/src/inkflow/infrastructure/database/models/semantic_summary.py` | SemanticSummaryORM |
| CREATE | `backend/src/inkflow/infrastructure/database/repositories/semantic_summary_repo.py` | semantic_summaries 异步仓储 |
| CREATE | `backend/src/inkflow/infrastructure/llm/templates/memory_semantic_summary.yaml` | 语义总结模板（project_specific/user_general 两组 + anchor_refs 契约） |
| MODIFY | `backend/src/inkflow/api/routers/memory.py` | summaries/summarize 端点 |
| MODIFY | `backend/src/inkflow/cli/commands/memory_cmd.py` | summarize 子命令 |
| MODIFY | `backend/src/inkflow/infrastructure/context/preference_source.py` | M2 语义总结优先 + 字面兜底 |
| MODIFY | `backend/src/inkflow/domain/services/memory_service.py` | summarize 编排 + 锚点哈希 + 审计 |
| MODIFY | `backend/src/inkflow/cli/commands/write.py` | 🧠 风格指令输出 |
| MODIFY | `backend/src/inkflow/api/deps.py` | semantic_summary_repo/summarizer 装配 |
| CREATE | `backend/tests/unit/test_semantic_summarizer.py` | 总结管线契约（模板渲染/mock LLM/JSON 解析/修复重试/防幻觉 B） |
| CREATE | `backend/tests/unit/test_semantic_summary_repo.py` | semantic_summaries 仓储集成 |
| MODIFY | `backend/tests/unit/test_preference_source.py` | M2 注入优先级 + 字面兜底 + 归属 title |
| MODIFY | `tests/api/test_memory_api.py` | summaries/summarize 端点契约 |
| MODIFY | `tests/cli/test_cli_memory.py` | summarize 子命令契约 |

> ⚠️ **装配契约预埋（F28 回马枪教训 #245）**：`app.py` 的 `include_router(memory.router)` 已存在（F28 合入），M1/M2 新增端点**必须**在既有 memory router 内追加（非新 router 文件），避免重蹈「router 存在但未装配」的覆辙；API 测试 RED 期 lazy import 合理，但 docstring 必须注明「GREEN 后移除手动安装、改走真实装配」。

---

## 9. 测试策略

| 层次 | 关键场景 | 覆盖率目标 |
|------|---------|-----------|
| 用户级聚合（M1 核心） | ① 单项目不升用户级（保守规则）② 第 2 项目出现落库（count=2, project_count=2）③ 第 3 项目更新（count+1/confidence 重算）④ 跨项目不混算（项目 A 的「她→林晚」不污染项目 B）⑤ 与项目级聚合共享 extract_edits 零重复计算 | ≥90% |
| 编排服务（M1） | ⑥ memory_learning=false 零行为（无用户级写入/注入/审计）⑦ user_preferences CRUD ⑧ 删除后 collect 不含该条 ⑨ 项目删除惰性重算（查询/collect 时发现已删项目→移除/project_count<2 删除；user-list 过滤幽灵项目）⑩ stats 输出 user 层计数 | ≥90% |
| 语义总结管线（M2 核心） | ⑪ 锚点为空不调 LLM ⑫ 模板渲染正确（{anchors} 注入）⑬ mock LLM 输出 → JSON 解析 → 落库 ⑭ 修复式重试（首次非法 JSON → 重试成功）⑮ **防幻觉 B**：mock LLM 编造偏好 → anchor_refs 校验拒绝 ⑯ 幂等（锚点哈希未变不调 LLM）⑰ 锚点哈希变化触发重新总结 | ≥90% |
| 注入源（M2） | ⑱ 语义总结优先 + 字面兜底 ⑲ 项目级/用户级归属 title 区分 ⑳ 预算 10 条/200 字符 ㉑ 冲突过滤延续（项目级/用户级同规则，Q3=A）㉒ 惰性总结两段式（锚点变化先用旧总结注入 + pending_summary 审计；后台基建缺位时同步总结兜底） | ≥90% |
| API | user-preferences list/delete 200/404；summaries 200 空（零行为）；summarize 200/502 | ≥90% |
| CLI | user-list/user-remove/summarize 信封/人类模式/退出码 | ≥90% |
| 回归 | F28 preferences/stats 既有测试仍绿；F6 context 既有测试仍绿；F16 style 既有测试仍绿（模板管线共享区域）；deterministic 零回归 | 全仓 ≥60%（ADR-027 门禁 98.5/95.0） |

**RED 形态**：新模块整体不存在 → 顶部 import ModuleNotFoundError（收集期失败，exit 2）；既有文件追加段 → 404 断言 FAIL（user-preferences/summaries/summarize 端点）。

**测试基建**：用户级聚合纯函数直测；编排服务全 mock 轨（user_repo/summary_repo/event_repo 显式默认值）；总结管线 mock LLM（注入 FakeLLM 返回契约 JSON / 编造输出 / 非法 JSON 三形态）；仓储真实 SQLite。

---

## 10. 不在范围内

| 项 | 归属 |
|----|------|
| 向量化检索/语义相似偏好 | 未排期（结构化偏好表 + 抽象指令，非向量检索语义） |
| 偏好自动过期/置信度衰减 | 远期（YAGNI；count 单调累积延续 F28） |
| GUI 记忆面板/toast（F19 渲染层） | F19 接入时（CLI 先行，接口契约已预留 semantic_summaries 字段） |
| F29 supervisor 记忆消费 | F29（0.8.0） |
| 多用户（user_id 维度） | 未排期（InkFlow 单用户本地优先 P1） |
| 编排器长跑证据喂料（M2 ← 编排器阶段 4 咬合） | F44（0.10.0）——M2 可先用 F28 既有证据跑通，不硬阻塞（设计定稿 §5；Q2=B 后补充：证据喂料仍软咬合，但后台任务基建为 M2 惰性总结**硬依赖**，见 §11） |
| memory_events 更新/删除端点 | YAGNI（一次写入只读消费延续） |
| deterministic 模式注入偏好 | 明确不含（F27 延续） |
| 语义总结 GUI 展示/编辑 | 未排期（CLI summarize + --json 先行） |
| LLM 总结输出翻译/多语言 | 未排期（中文优先，与 F16 同域） |

---

## 11. 依赖关系

- **依赖**（✅ 已合入）：F28（演进基线：project_preferences/memory_events/preference_learner/memory_service/PreferenceSource/开关语义，PR #242）、F6（ContextSourceType/SOURCE_LAYER/ContextItem + sources 装配）、F16（LLM 模板管线样板 `_style_llm_analyzer.py`/`style_llm_analysis.yaml`/`_extract_json_fragment`）、F32（app_settings 分层对照，不触碰表结构）、F1（ProjectConfig.extra）、F34（audit_logs）、F38（CLI 恒 HTTP）、#415（config.py LLM 默认模型 deepseek/deepseek-v4-flash，配置唯一默认源）。
- **依赖**（⏳ 模块内）：M2 依赖 M1（#339 → #340，先有跨项目聚合 LLM 才有跨项目证据）。
- **依赖**（⏳ 模块外）：**F44 阶段4 后台任务框架（M2 硬依赖，Q2=B 拍板）**——惰性总结的「后台异步刷新」前提；后台就位前 M2 降级「注入前同步总结」过渡（两段式，§5.4）。证据喂料（阶段 4 长跑）仍软咬合不阻塞（§1.2/§10）。
- **被依赖**：F44 编排器（阶段 4 长跑产生修改证据喂 difflib 锚点——证据来源软咬合；但 M2 惰性总结**硬依赖** F44 阶段4 后台任务框架，见上）、F19 GUI（渲染层接入偏好面板/toast，远期）。
- 新增运行时依赖：**无**（difflib 标准库 + 既有 SQLAlchemy + 既有 LangChain LLMClient；semantic_summarizer 复用 F16 已注入的 LLMClientProtocol/PromptTemplateProtocol）。
- 编号口径声明：以 ADR-019 v5+ 版本表为准（F45=本模块；变体编号按「最新无冲突基线」接续 F46=19 → 本模块第 20 变体）。

---

## 12. 关键架构决策记录

| 决策 | 方案 | 备选（否决理由） |
|------|------|-----------------|
| 用户级偏好存储（M1 核心） | **独立 user_preferences 表**（全局，无 project_id，source_projects JSON 追溯） | project_preferences 加 scope 列（语义混载，过滤分叉贯穿全部消费方，回归面大）；user_id 列（多用户 YAGNI，P1 单用户） |
| 跨项目聚合保守规则 | **同 (category, value) 在 ≥2 项目出现才升用户级**（count≥2 且 project_count≥2） | 直接跨项目聚合（单项目特有设定「她→林晚」会污染其他项目 = 设计定稿 §3.2 幻觉场景）；单项目也升用户级（无证据支撑的过度泛化） |
| 归属分层模型 | **项目级 + 用户级两层**（project_preferences 项目内注入 / user_preferences 全局注入，设计定稿 §3.4） | 单层全局（丢失项目特有设定语义）；三层（加卷级——超出设计定稿范围，YAGNI） |
| LLM 总结管线 | **镜像 F16 _style_llm_analyzer 骨架**（模板渲染 → LLM → JSON 解析 → 修复重试 ≤2 → 截断落库） | 自研新管线（重复 F16 已验证的 JSON 解析/重试逻辑，违背复用）；LangChain 直接调用（ADR-015 领域层零 LangChain） |
| 防幻觉 B | **anchor_refs 契约校验**（LLM 每条偏好必须附引用的锚点 value，程序校验 ⊆ 锚点集，不通过丢弃） | 纯 prompt 约束（不可测试，LLM 编造无法程序拦截）；不做校验（验收判据「不编造证据之外偏好」无法落地） |
| 总结陈旧复用 | **anchor_hash 幂等**（SHA-256 锚点键指纹，未变化不调 LLM 返回既有总结） | 每次注入都总结（成本不可控，LLM 调用频繁）；无缓存每次总结（成本 + 陈旧不可知） |
| 注入形态 | **M2 语义总结优先 + 字面偏好兜底**（F28 字面注入为保底不丢失记忆） | 完全替代字面（LLM 失败时记忆丢失）；字面优先（M2 语义总结白做） |
| LLM 模型配置 | **config.llm_default_model 唯一默认源**（#415 拍板，代码不写第二份默认值，env 优先） | 代码硬编码模型名（双份默认值漂移，违背 #415 治理）；新增独立配置键（YAGNI，默认模型同一来源足够） |
| 开关 | **复用 memory_learning 单一开关**（不新增语义总结独立开关） | 独立 semantic_summarize 开关（两开关组合矩阵复杂度，YAGNI） |
| 审计 | 复用 F34 audit_logs（user_preference_learned/removed、semantic_summary_generated/failed） | 新审计表（F34 既有表足够，异常静默旁路语义延续） |
| 项目删除重算时机（Q1=B 拍板，2026-08-17） | **惰性重算**：删除钩子零成本不动 user_preferences；collect/查询时发现 source_projects 含已删项目 → 重算（移除该项目；project_count<2 → 删偏好）；user-list 查询时过滤幽灵项目来源 | 同步重算（删除钩子内全量重算——语义即时但删除路径变重，估算 0.5 人天，用户否决） |
| 总结刷新时机（Q2=B 拍板，2026-08-17） | **注入前惰性总结 + 后台异步刷新**：先用旧总结注入（注入不等待 LLM）+ pending_summary 审计，后台任务基建（F44 阶段4）就位后异步重总结；基建缺位降级同步总结兜底（+1 人天） | 注入前同步总结（注入阻塞 LLM 调用，锚点变化后首个生成请求变慢）；仅手动 summarize（闭环断点，越用越智能失效） |
| 用户级注入冲突过滤（Q3=A 拍板，2026-08-17） | **用户级偏好注入任何项目都过该项目显式设定冲突过滤**（同规则；PreferenceSource.collect 复用 explicit_texts，≈0 额外人天） | 仅项目级过滤（项目 B 显式设定可能被项目 A 学来的偏好覆盖，违背「显式设定 > 学习偏好」拍板原则） |

---

## 13. 验收标准

### M1（#339 用户级偏好层）

- **M1-1 用户级聚合全绿**: `pytest tests/unit/test_user_preference_learner.py` — 保守规则（单项目不升）+ 第 2 项目落库 + 第 3 项目更新 + 跨项目不混算 + 共享 extract_edits
- **M1-2 编排服务全绿**: `pytest tests/unit/test_memory_service_user.py` — memory_learning=false 零行为 + user_preferences CRUD + 项目删除惰性重算（查询时触发 + 幽灵项目过滤）+ stats user 层计数
- **M1-3 仓储全绿**: `pytest tests/unit/test_user_preference_repo.py` — 真实 SQLite CRUD + source_projects/source_events JSON 往返
- **M1-4 API 全绿**: `tests/api/test_memory_api.py` — user-preferences list/delete 200/404
- **M1-5 CLI 全绿**: `tests/cli/test_cli_memory.py`（已登记 ci.yml）— user-list/user-remove 信封/人类模式/退出码
- **M1-6 归属分层（手工）**: 项目 A、B 都开启 memory_learning；A 中「说→低声道」改 2 次（仅 A）、B 中「说→低声道」改 2 次 → `inkflow memory user-list` 出现该偏好（project_count=2）；A 中「她→林晚」改 2 次（仅 A）→ user-list 不出现（项目特有设定不升用户级）
- **M1-7 跨项目不混算（手工）**: 项目 A 学习「她→林晚」，项目 B 写作用户级注入不含「她→林晚」；B 内项目级偏好正常注入
- **M1-8 默认关闭零行为（手工）**: 未开启 memory_learning → user-list 为空、user_preferences 表无行、注入无用户级条目
- **M1-9 删除即停注入（手工）**: `inkflow memory user-remove <id>` 后任意项目 `write next --mode agentic` → 输出不含该用户级偏好
- **M1-10 项目删除惰性重算（手工/契约，Q1=B）**: 删除 source_projects 中的某项目后：① 删除钩子不触碰 user_preferences（零成本，`user_preferences` 表行数不变）；② 下次 `inkflow memory user-list` / collect 时该偏好 source_projects 已移除该项目（**user-list 不显示幽灵项目来源**）；③ 仅剩 1 个项目支撑的偏好自动删除（project_count<2 → 降级回项目级证据不足）

### M2（#340 语义风格提取）

- **M2-1 总结管线全绿**: `pytest tests/unit/test_semantic_summarizer.py` — 锚点为空不调 LLM + 模板渲染 + mock LLM JSON 解析 + 修复重试 + 幂等（anchor_hash）+ 锚点变化重新总结
- **M2-2 防幻觉 B 全绿**: `pytest tests/unit/test_semantic_summarizer.py -k hallucination` — mock LLM 编造偏好 → anchor_refs 校验拒绝 + 审计 semantic_summary_failed
- **M2-3 仓储全绿**: `pytest tests/unit/test_semantic_summary_repo.py` — semantic_summaries CRUD + scope 过滤
- **M2-4 注入升级全绿**: `pytest tests/unit/test_preference_source.py` — 语义总结优先 + 字面兜底 + 项目级/用户级 title 区分 + 预算延续
- **M2-5 API 全绿**: `tests/api/test_memory_api.py` — summaries 200（含零行为空）/ summarize 200/502
- **M2-6 CLI 全绿**: `tests/cli/test_cli_memory.py` — summarize 信封/人类模式/--force/退出码
- **M2-7 可解释抽象偏好（手工）**: 项目有 ≥5 条项目级偏好 → `inkflow memory summarize --project-id` → 输出「项目风格」+「通用风格」两段可读抽象指令（非字面碎片）
- **M2-8 注入形态升级（手工）**: summarize 后 `write next --mode agentic` 人类模式出现「🧠 风格指令：...」；`--json` 信封含 semantic_summaries 字段
- **M2-9 锚点未变幂等（手工）**: 连续两次 summarize 无新修改 → 第二次输出「锚点未变化，复用既有摘要」且不调用 LLM（日志无 LLM 调用记录）
- **M2-10 惰性总结 + 后台刷新（契约，Q2=B）**: 锚点变化 → collect 先用旧总结注入（注入不等待 LLM）+ 审计 pending_summary；后台任务基建（F44 阶段4）就位后异步刷新总结；基建缺位时降级同步总结兜底（`pytest tests/unit/test_preference_source.py -k lazy_summary`）

> 所有里程碑验收以本节 M1/M2 为准（#339/#340 验收标准映射：归属分层→M1-6、跨项目不混算→M1-7、可解释抽象偏好→M2-7、不编造证据之外偏好→M2-2/M2-8）。

---

## 14. 待澄清问题

- **Q1: 项目删除时用户级偏好的重算时机** ✅ 已确认（用户拍板：选项 B——惰性重算）
  - 背景：项目删除的级联清理（§7）——用户级偏好的 source_projects 含被删项目时，需重算（移除该项目；project_count<2 → 删除该偏好）。F28 项目删除级联是服务层钩子（跨模块接线），F45 需要确定重算粒度。
  - A. **同步重算**（建议）：项目删除钩子内同步重算全部受影响用户级偏好（项目少、行数少，SQLite 同步成本可接受；删除即正确的语义，无残留窗口）
  - B. 惰性重算：collect/查询时发现 source_projects 含已删项目 → 重算（删除钩子零成本，但 user-list 可能短暂显示「幽灵项目」来源，需查询时过滤）
  - 建议：A（同步重算——删除语义确定性优先，F28「删除立即生效」精神延续；估算 0.5 人天）——**用户否决，拍板 B**：删除钩子零成本，collect/查询时发现 source_projects 含已删项目 → 重算（移除该项目；project_count<2 → 删偏好），user-list 查询时过滤幽灵项目来源。正文已按 B 修订：§7 项目删除行、§5.1 落库语义、§13 M1-10/M1-2。
- **Q2: 锚点变化后语义总结的触发时机（M2 成本 vs 新鲜度）** ✅ 已确认（用户拍板：选项 B——注入前惰性总结 + 后台异步刷新）
  - 背景：§5.4 锚点哈希检查发现锚点变化时，何时重新总结？（LLM 调用有成本；每次编辑都触发总结不可接受）
  - A. **注入前同步总结**（建议）：PreferenceSource.collect 时锚点哈希不一致 → 同步调 LLM 总结后再注入（保证注入始终最新；LLM 失败回退旧总结 + 字面兜底）。成本 = 每次生成调用至多 1 次 LLM 总结（有 anchor_hash 幂等，只有锚点真的变化才触发；实际修改频率低）
  - B. 注入前惰性总结（先用旧总结注入，后台异步刷新）——注入不等待 LLM，但需要后台任务基建（InkFlow 无后台任务框架，F44 阶段 4 才引入；M2 独立排期时为复杂度买单）
  - C. 仅手动 summarize 触发（无自动总结）——零隐式成本，但「越用越智能」需要用户手动刷新，闭环断点
  - 建议：A（同步总结——无后台任务基建依赖、锚点幂等控成本；估算 0.5 人天 vs B +1 人天）——**用户否决，拍板 B**：锚点变化先用旧总结注入（注入不等待 LLM），后台任务基建（F44 阶段4）就位后异步刷新；**M2→F44 阶段4 依赖升为硬依赖**；后台就位前 M2 降级「注入前同步总结」过渡（两段式，§5.4 已写）。+1 人天。正文已按 B 修订：§5.4、§7 边界表、§11 依赖、§12 决策表、§13 M2-10。
- **Q3: M1 用户级偏好注入是否也受「显式设定冲突过滤」约束** ✅ 已确认（用户拍板：选项 A——是，同规则过滤）
  - 背景：F28 Q4 冲突规则 = 偏好 value 命中同项目显式设定文本 → 跳过该条注入（显式设定 > 学习偏好）。用户级偏好是**跨项目**学习来的，注入到项目 B 时是否也按项目 B 的显式设定做冲突过滤？
  - A. **是，同规则过滤**（建议）：用户级偏好注入到任何项目都过该项目的显式设定冲突过滤（一致性；防止项目 A 学来的「称呼习惯」覆盖项目 B 已显式设定的称呼——正是「跨项目不混算」的注入侧保障）
  - B. 否，仅项目级偏好过滤：用户级偏好全局注入不检查冲突（省一次显式文本加载，但项目 B 的显式设定可能被项目 A 学来的偏好覆盖，违背「显式设定 > 学习偏好」拍板原则）
  - 建议：A（一致性 + 防跨项目覆盖显式设定；实现 = PreferenceSource.collect 已加载 explicit_texts，用户级条目复用同一过滤，≈0 额外人天）——**采纳**：正文 §5.6 冲突过滤已覆盖项目级/用户级同规则（Q3=A 已确认标注），无需大改。

---

**完成门禁对照**（本 spec 交付时）：13 节 + §14 待澄清 Q1-Q3（≤3，v1.1 已全部拍板 ✅ 留痕不删）；围栏偶数；marker 残留 0；参照 F28 spec（525 行）体量目标 ≤800 行；M1 覆盖 #339、M2 覆盖 #340（两段式架构 + 两层归属 + user_preferences 表）、LLM 配置遵循 #415。
