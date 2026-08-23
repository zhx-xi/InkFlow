# F49: 长期记忆衰减（memory-decay）功能规格

**Spec 版本**: 1.0
**日期**: 2026-08-23
**依据**: 设计定稿（docs/agentic-orchestrator-and-memory-design-2026-08-14.md §3 记忆系统演进，唯一真相）+ Issue #617（① 时间衰减）/ #618（② LLM 显式覆盖）/ #619（③ GUI）+ 用户拍板（2026-08-23 五点决策）+ F28 spec v1.0（specs/f28-agent-memory/spec.md）+ F45 spec v1.1（specs/f45-memory-evolution/spec.md，两段式基线）
**所属阶段**: 0.12.0（长期记忆衰减，F49），估算 ① 3-5 人天 + ② 4-6 人天 + ③ 3-5 人天（合计 10-16 人天）
**关联 Issues**: #617（① 后端·时间衰减 + 活跃时钟）· #618（② 后端·显式覆盖 + LLM 冲突判定）· #619（③ 前端 GUI + summary remove 端点）
**依赖**: ✅ F28 agent-memory（project_preferences / user_preferences / memory_events / preference_learner / memory_service / PreferenceSource，PR #242）· ✅ F45 memory-evolution（M1 用户级偏好层 + M2 语义总结，semantic_summarizer / semantic_summaries，PR #442/#452）· ✅ F6 context-service（注入端口 ContextSourceType / PreferenceSource）· ✅ F32 settings-persistence（app_settings 分层对照）· ✅ #415（LLM 默认模型唯一默认源）· ✅ F38（CLI 恒 HTTP）· ✅ F34（audit_logs）· ⏳ ③ 依赖 ①②
**参考 ADR**: adr/ADR-037.md（记忆提取：规则化先行 + LLM 第二阶段）、adr/ADR-038.md（memory_learning 默认 false）、adr/ADR-031.md（双模式开关 extra 键）、ADR-027（覆盖率门禁）
**状态**: 待实现 🔲

> **Spec 变更**: v1.0 初稿（2026-08-23）。基于用户五点拍板 + #617 拆分（①②③ 三子 issue）+ 母 feature 评论留痕。

> **模块类型声明**: 本模块为「**偏好学习闭环型（记忆衰减演进）**」变体——F28（第 12 变体）与 F45（第 20 变体）之上的遗忘机制增量，补上长期记忆「只增不衰」的短板。与 F45 的「AI 语义总结」不同：本模块新增**时间衰减**（活跃时钟 + 注入动态分）与**显式覆盖**（LLM 判定冲突 → superseded）。编号依据：按「最新无冲突基线」接续——F48=第 21 变体（实体关系图谱型）为当前最新无冲突基线，本模块声明**第 22 变体**（冲突以 ADR-019 v5+ 为准）。

---

## 1. 概述

F49 交付 F28/F45 长期记忆的**遗忘机制**：当前记忆只增量累积、永不遗忘（`confidence = 1 - 1/(count+1)` 只随 count 单调递增；注入排序只看 `count desc`、不看新旧）。后果 = 陈旧偏好带高 count 霸占注入名额，废弃称谓/文风持续喂给下游生成。本模块补齐两种遗忘路径 + 用户控制缺口 + GUI：

1. **时间衰减（#617）**——偏好不物理删，按「项目活跃使用时长」的半衰期指数降权，久未强化的偏好自动退出注入。
2. **显式覆盖（#618）**——LLM 语义判定新偏好是否取代旧偏好，被取代的标注 `superseded`、注入排除（用户级同规则）。
3. **用户控制补缺口（#619）**——`/memory/summaries` remove 端点 + GUI 设置项/按钮。

### 1.1 三种遗忘机制定位

| 机制 | 现状（F28/F45） | 本模块 |
|------|----------------|--------|
| ① 时间衰减 | ❌ 未实现、未设计 | 核心交付（#617） |
| ② 显式覆盖 | ⚠️ 仅聚合摘要层有「重算替换」，偏好层无冲突仲裁/过期标记 | 纳入（#618，LLM 判定） |
| ③ 用户控制 | ✅ 已实现（API+CLI）；唯一缺口 = summary 无 remove 端点 | 补缺口 + GUI（#619） |

### 1.2 与既有模块的边界

- **开关边界**：沿用 `memory_learning` 显式开启铁律（adr/ADR-038.md，默认 false）——false 时时间衰减/显式覆盖/summary 删除全路径零行为（不算分/不判定/不注入）。
- **衰减阈值边界**：score 低于阈值（默认 0.05）不再注入——**不物理删除**（count 证据保留），可查可恢复。
- **注入边界**：随时间衰减的 score 与 LLM 判定的 `superseded` 都在注入读路径（`get_preferences_for_injection` / `get_user_preferences_for_injection`）生效，经既有 PreferenceSource 注入，不直接改 system prompt。
- **配置边界**：`memory_decay_enabled` / `memory_decay_half_life` 落在 `project.config.extra`（与 `memory_learning` 同层，详见 §2.2）。
- **明确不含**：向量化记忆衰减、跨项目持久化偏好分层扩展（超出本次范围）、回收站 GUI 完整化（本次只提供被覆盖/降权状态展示 + 查看/恢复入口，见 §10）。

### 1.3 与 F45 的差异

| 维度 | F45（两段式基线） | F49（本模块） |
|------|-----------------|--------------|
| 遗忘 | 无（只增不衰） | 时间衰减 + 显式覆盖 |
| 注入排序 | count desc | score desc（count × 衰减因子，排除 superseded） |
| 冲突仲裁 | 无（不同 value 共存） | LLM 判定取代 → superseded |
| 计时口径 | 无 | 活跃时钟（只随项目活跃使用推进，防挂机误衰减） |
| GUI | 记忆面板基础（#486/#521） | 衰减设置项 + 删除总结按钮 + 被覆盖/降权状态展示 |

## 2. 数据模型

### 2.1 领域实体（Pydantic，`preference.py` / `user_preference.py` / `project.py`）

**ProjectPreference（项目级偏好）**——新增字段（`domain/models/preference.py`）：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `active_watermark_at_last_access` | float（活跃基准） | 0.0 | 上次注入/访问时的项目活跃水位（用于 Δt_active 计算）；旧数据缺省 0 |
| `superseded_by` | str | "" | 被取代时指向新 value（或新偏好 id）；空 = 未取代 |

**UserPreference（用户级偏好）**——新增字段（`domain/models/user_preference.py`）：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `active_watermark_at_last_access` | float | 0.0 | 同项目级语义 |
| `superseded_by` | str | "" | 同项目级语义 |

> ⚠️ 迁移注意：`superseded_by` 独立于 `active_watermark_at_last_access`——前者是「显式覆盖」标记（#618），后者是「时间衰减」水位（#617）。缺省值必须是「无影响」形态（空串 / 0.0），确保旧库数据不触发意外衰减或取代。

**Project / ProjectConfig（项目级活跃基准）**——`domain/models/project.py`：

- `ProjectConfig.extra` 新增 `memory_decay_enabled`（bool，默认 false）+ `memory_decay_half_life`（int，默认 30 天）——与 `memory_learning` 同层（零迁移，旧 config JSON 缺键 → 默认值）。
- **活跃基准** `active_watermark`（float，单调累积）：落点建议为 `Project` 级别字段（`projects` 表加列）或作为 `ProjectConfig.extra` 键。**决策点见 §14 Q1**（影响迁移形态 + 多个读端）。

### 2.2 活跃时钟（A 核心设计）

- **基准**：`project.active_watermark` 单调累积，只在用户**实际使用项目**时推进（打开项目 / 触发写作 / 手编草稿 / 发送 chat 等用户行为）；项目闲置期间不推进。
- **Δt_active**：`active_watermark_now - preference.active_watermark_at_last_access`（**不是** `now - last_accessed_at`）。
- **效果**：用户离开一个月（无活跃 → Δt_active=0）→ 记忆**不衰减**；持续写作但某偏好不再被强化 → 按半衰期自然降权。

### 2.3 注入动态分 & 排序

- **score = strength × decay(Δt_active)**，`strength = count`（支撑强度），`decay(Δt) = 0.5^(Δt/half_life)`。
- 逻辑收敛于 `MemoryService._score_pref`（新增纯函数，供 `get_preferences_for_injection` / `get_user_preferences_for_injection` 共用）。
- 注入排序：`count desc` → `score desc`；过滤 `superseded` 条目 + score < `低注入阈值` 条目。
- **刷新访问**：每次偏好被注入（读）时，`active_watermark_at_last_access` 写回当前项目活跃水位——「用即保鲜」。

### 2.4 SemanticSummary（语义总结）

- **不新增字段**；仅补 `/memory/summaries` 的 remove 端点（§3.3）。`semantic_summaries` 表沿用 F45 定义（scope=project/user + project_id + anchor_hash + content）。

## 3. API 契约

### 3.1 记忆衰减配置（项目级）

`config.extra` 透传，经既有项目配置端点读写（`/api/v1/projects/{id}/config`），**不新增独立端点**——衰减开关与半衰期作为 `ProjectConfig.extra` 键（`memory_decay_enabled` / `memory_decay_half_life`）随项目配置一起读写。

**PATCH `/api/v1/projects/{id}/config`**（已存在端点，扩展 extra 键）：

```json
{
  "config": {
    "extra": {
      "memory_learning": true,
      "memory_decay_enabled": true,
      "memory_decay_half_life": 30
    }
  }
}
```

- 校验：`memory_decay_enabled` 必须为 bool；`memory_decay_half_life` 必须为 int（范围 1-365 天，越界 422）；缺省值（未提供键）零迁移。
- 读取：`GET /api/v1/projects/{id}/config` 返回完整 config（含 extra）。

### 3.2 偏好注入排序（行为变更，非新端点）

`GET /agent/preferences`（list）与 `GET /agent/user-preferences`（list）返回顺序从 `count desc` 改为 **`score desc`**（count × 衰减因子），并**过滤 superseded** 条目。`get_preferences_for_injection` 内部实现同规则（无 HTTP 契约变化，仅排序/过滤语义）。

**响应示例（`GET /agent/preferences?project_id=...`）**：

```json
{
  "items": [
    {
      "id": "...", "category": "addressing", "pattern": "她", "value": "林晚",
      "confidence": 0.667, "count": 2,
      "score": 1.0,
      "superseded_by": "",
      "active_watermark_at_last_access": 42.0,
      "created_at": "...", "updated_at": "..."
    }
  ],
  "total": 1
}
```

### 3.3 语义总结删除（新端点）

**DELETE `/api/v1/agent/memory/summaries`**

Query：`project_id`（必填）。删除该项目级语义总结；`scope=user` 的全局总结删除需显式 `scope=user`（无 project_id）。

Request:

```http
DELETE /api/v1/agent/memory/summaries?project_id=<uuid>
```

Response `200`:

```json
{ "project_id": "<uuid>", "deleted": true }
```

- `404`：项目不存在。
- 删除后下次 `summarize`（注入前 or 手动）重新生成——对齐 `remove_preference`「删除即停止注入」语义。
- **幂等**：summary 不存在 → `deleted: true`（no-op），不 404（对齐 F45 幂等语义）。

### 3.4 异常映射

| 场景 | 状态码 | 说明 |
|------|--------|------|
| 半衰期越界 | 422 | `memory_decay_half_life` 不在 1-365 |
| 项目不存在（删除总结） | 404 | ProjectNotFoundError |
| memory_learning=false 且显式删除总结 | 200 | 零行为（no-op，不删不报错）？——见 §14 Q2 |
| LLM 冲突判定防幻觉丢弃 | 502? | 见 §14 Q3（沿 F45 semantic_summary_failed 审计语义） |

## 4. CLI 命令签名

沿用 F7 全局约定（`--json` 信封 + 退出码 0/1/2；CLI 恒经 HTTP，F38）。

| 命令 | 参数 | 说明 |
|------|------|------|
| `inkflow memory summarize --project-id <uuid> --remove` | `--remove` 调用 §3.3 删除 | 删除语义总结（替代/补 get_summaries 只读） |
| `inkflow memory list --project-id <uuid>` | 不变 | 返回按 score desc 排序（含 score/superseded_by 字段） |
| `inkflow memory user-list` | 不变 | 同 list，用户级 |
| `inkflow project config set --project-id <uuid> --key memory_decay_enabled --value true` | 透传 extra | 走既有 project config CLI（若存在）；否则经 GUI 设置项 |

> `--remove` 语义：删除后复用 `get_summaries` 幂等（锚点未变 → 下次 summarize 可复用既有逻辑，删除只是清当前快照）。与 `remove_preference` 的分歧点见 §14 Q2。

## 5. 关键差异节：记忆衰减机制型

本模块为「记忆衰减机制」变体，区别于 F28 提取型 / F45 语义总结型的核心差异是**遗忘行为的注入读路径改造**而非**新增记忆来源**。

### 5.1 时间衰减（#617 核心，第 22 变体 A 面）

公式收敛于 `MemoryService._score_pref`：

```
score = count × 0.5^(Δt_active / half_life)
Δt_active = project.active_watermark_now − preference.active_watermark_at_last_access
```

- **注入排序**：`score desc`（替换 `count desc`）。
- **低注入阈值**：`score < 0.05` 不再注入（不删）。
- **刷新**：注入即把 `active_watermark_at_last_access` 写为当前水位。
- **零行为边界**：`memory_learning=false` → 不算分、不刷新、排序保持 count desc（回归零影响）。

### 5.2 显式覆盖 + LLM 判定（#618 核心，第 22 变体 B 面）

**冲突判定 = LLM 语义管线**（对齐 F45 M2 `semantic_summarizer.py` 形态：锚定证据 + JSON 输出 + 防幻觉 B + 修复式重试 ≤2 次 + 温度 0.2）。

- 新候选 value 落库前，LLM 判断它是否**语义取代**某既有偏好（同规则细化/替换）→ 是则旧偏好 `superseded_by = 新value`、注入排除；二者只是并存无关则不标。
- **用户级同规则**（`get_user_preferences_for_injection` 同样过滤 superseded）。
- **防幻觉 B**：LLM 输出引用必须 ⊆ 锚点证据集（anchor_refs ⊆ value 集），不通过 → 丢弃该条（审计 `semantic_summary_failed` 同类），否则 502。
- **注入排除**：`superseded` 条目不进入注入列表（但保留在 `list` 响应中，附 `superseded_by` 供 GUI 展示）。

### 5.3 注入读路径统一改造

`memory_service.py`：
- `get_preferences_for_injection` / `get_user_preferences_for_injection`：排序 `count desc`→`score desc`，过滤 superseded + score<阈值。
- 新增 `_score_pref`（纯函数）+ `_bump_access_watermark`（写回水位）。
- `list_preferences` / `list_user_preferences`：过滤 superseded 由是否展示决定（list 展示全部含 superseded 供 GUI；injection 排除）——见 §14 Q3。

## 6. 组织规则

- 时间衰减（①）与显式覆盖（②）同处 `memory_service.py` 注入读路径 + 领域模型加字段——**同一后端 spec 域**，代码集中在 `domain/services/memory_service.py` + `domain/models/preference.py`/`user_preference.py` + `domain/services/preference_learner.py`（新增 _score/_decay 纯函数）+ `infrastructure/llm/templates/`（若新增 LLM 判定模板则 CREATE，否则复用 F45 memory_semantic_summary 若结构可扩展）。
- 显式覆盖的 LLM 判定复用 `SemanticSummarizer` 骨架（`_extract_json_fragment` / `_build_fix_prompt` / `_ParseOutcome` / 防幻觉 B）与 `LangChainLLMClient`+`LangChainPromptManager` 注入——**不重造轮子**。

## 7. 边界情况与错误处理

| 场景 | 行为 | 说明 |
|------|------|------|
| `memory_learning=false` | 全路径零行为（不算分/不判定/不刷新/排序 count desc/删除总结 no-op） | 回归零影响 |
| 项目闲置（无活跃） | Δt_active=0 → 记忆不衰减 | 「用即保鲜」核心 |
| 偏好 count 支撑但久未强化 | 按半衰期降权 → score<0.05 退出注入（数不删） | 可查可恢复 |
| 旧库偏好（active_watermark=0） | Δt_active = 当前水位 - 0 → 若已累积多，score 自然衰减；**决策点见 §14 Q1（首次回溯）** | 迁移安全 |
| 同 (category,pattern) 不同 value 并存 | LLM 判定是否取代；并存无关则不标 | 防误判 |
| LLM 判定不可解析/防幻觉 B 失败 | 重试 ≤2 → 仍失败丢弃该条（审计）或 502 | 沿 F45 |
| 删除语义总结时 summary 不存在 | deleted:true（幂等 no-op） | 不 404 |
| `memory_decay_half_life` 越界/非 int | 422 | 校验 |

## 8. 文件结构（CREATE / MODIFY，对照真实树）

**MODIFY**：

- `backend/src/inkflow/domain/models/preference.py`（+active_watermark_at_last_access / superseded_by）
- `backend/src/inkflow/domain/models/user_preference.py`（同）
- `backend/src/inkflow/domain/models/project.py`（ProjectConfig.extra 键 + active_watermark）
- `backend/src/inkflow/domain/services/memory_service.py`（_score_pref / _bump_access_watermark / 注入读路径改造 / summarize --remove 支持）
- `backend/src/inkflow/domain/services/preference_learner.py`（_score_decay 纯函数）
- `backend/src/inkflow/infrastructure/database/repositories/preference_repo.py` / `user_preference_repo.py`（新字段 → ORM）
- `backend/src/inkflow/infrastructure/database/repositories/semantic_summary_repo.py`（delete_by_scope / delete）
- `backend/src/inkflow/api/routers/memory.py`（DELETE /memory/summaries）
- `backend/src/inkflow/cli/commands/memory_cmd.py`（summary --remove）
- `backend/src/inkflow/core/database.py`（若加列 → ensure_*_column 幂等迁移，见 §2.1）
- `backend/tests/unit/test_memory_service.py`（排序/过滤/衰减断言）
- `frontend/packages/renderer/src/api/memory.ts`（summary remove + 字段）
- `frontend/packages/renderer/src/pages/memory.tsx`（删除总结按钮 + 被覆盖/降权状态 + 查看/恢复入口）
- `frontend/packages/renderer/src/pages/project-settings.tsx`（衰减设置区块：开关 + τ 输入，i18n）
- `frontend/packages/renderer/src/i18n/zh.ts` / `en.ts`（新增文案）
- `frontend/packages/renderer/src/pages/memory.test.tsx` / `project-settings.test.tsx`（组件测试）

**CREATE（若新增 LLM 判定模板）**：

- `backend/src/inkflow/infrastructure/llm/templates/memory_supersede.yaml`（显式覆盖 LLM 判定模板；若可复用 memory_semantic_summary 则不建）

> ⚠️ 迁移三形态测试（旧库补列/新库 no-op/无表 no-op）必须覆盖——沿用 `ensure_*_column` 幂等模式（database.py 先例）。

## 9. 测试策略

**层次**：单元（_score_pref 数学锁定 + 注入排序 + 过滤）+ 集成（API 端点）+ 前端组件（Vitest + RTL）。

**关键场景**：
- 单元：`score = count × 0.5^(Δt/half_life)` 边界（Δt=0 → count；Δt=half_life → count/2；Δt→∞ → 0）；排序 score desc；superseded 过滤；memory_learning=false 零行为回归。
- 单元：_score_pref 纯函数（无 LLM 依赖）。
- 集成：DELETE /memory/summaries（幂等/404）；PATCH config extra 校验（half_life 越界 422）。
- LLM 判定（②）：Mock LLM 驱动防幻觉 B（anchor_refs ⊄ 证据集 → 丢弃）+ 取代判定（superseded 注入排除）。
- 前端：设置项开关/τ 校验；删除总结按钮调 remove 端点（mock）；被覆盖/降权 status 展示。
- **覆盖率**：模块 ≥80%、全仓 ≥60%（ADR-027）——新增字段/端点测试不得用 smoke/恒真断言（#524 P0）。

**CI 注意**：`backend/tests/` 与顶层 `../tests/` 不能同 pytest 命令（conftest 冲突）；新增测试文件必须登记 ci.yml。

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| 向量化记忆衰减 | 本次偏好/总结为结构化 + 语义总结，不含向量库衰减（F14 归 RAG 域） |
| 回收站完整化 | 只提供被覆盖/降权状态展示 + 查看/恢复入口；完整回收站另立 |
| 跨项目偏好分层扩展 | 超出本次（F45 M1 已交付归属分层，本次只加遗忘） |
| 活跃时钟的具体推进点枚举 | spec 定方向（用户行为推进），实现期定推进点清单（见 §14 Q1） |

## 11. 依赖关系

| 依赖 | 说明 |
|------|------|
| ✅ F28 | 偏好/事件/learner/memory_service/PreferenceSource |
| ✅ F45 | M1 user_preferences + M2 semantic_summarizer（LLM 判定复用骨架） |
| ✅ F6 | 注入端口 ContextSourceType/PreferenceSource |
| ✅ F34 | audit_logs（LLM 判定/衰减审计） |
| ⏳ ③ 依赖 ①② | GUI 消费配置 + superseded 状态字段 |
| ⏳ ② 依赖 ① | 同域（需 ① 落下的模型字段/注入读路径） |

## 12. 关键架构决策记录

| # | 决策 | 方案 | 备选否决 |
|---|------|------|---------|
| D1 | 衰减函数 | 半衰期 `0.5^(Δt/τ)` | 指数 `e^(-Δt/τ)`（数学等价但语义不直观）/ 线性 |
| D2 | 计时口径 | **活跃时钟**（只随项目活跃使推进；Δ=活跃水位差） | 墙钟 `now-last_access`（挂机误衰减，用户否决） |
| D3 | 作用点 | 注入时算分（非破坏性） | 周期清理任务（破坏性删分） |
| D4 | 显式覆盖判定 | **LLM 语义判定**取代（用户级同规则） | 字面 (category,pattern) 匹配（误判，用户否决） |
| D5 | summary 删除 | 补 remove 端点 + GUI 按钮 | 不补（用户控制缺口保留） |
| D6 | 交付面 | 后端 + GUI | 仅后端（用户否决） |

## 13. 验收标准（M 里程碑）

**M1（#617 时间衰减）**：
- 注入排序 `score desc`；久未强化偏好按 τ 降位/退出阈值。
- 用户长期不用项目 → Δt_active=0 → 记忆不衰减（**探针实证**：不推进活跃水位时 score 不变）。
- `memory_decay_enabled=false` 回归零影响。
- `_score_pref` 数学锁定测试通过；`get_preferences_for_injection` 排序断言。

**M2（#618 显式覆盖）**：
- LLM 判定取代 → 旧偏好 superseded、注入排除；用户级同规则。
- Mock LLM 驱动防幻觉 B 校验（anchor_refs 不含 → 丢弃）；重试 ≤2 → 502/丢弃。
- `superseded_by` 链可查；`list` 展示 superseded 供 GUI。

**M3（#619 GUI + summary remove）**：
- GUI：衰减设置项（开关 + τ）可操作保存 + 状态反馈。
- 记忆管理页删除总结按钮可用（调 remove 端点），删除即停止注入。
- 被覆盖/降权状态 GUI 可见；查看/恢复入口可用。
- 前端组件测试 + 后端 remove 端点测试（单元/集成/CLI）。
- ADR 记录（ADR-019 版本表补 0.12.0 行 + F49 Feature 登记）。

> 所有里程碑验收以本节 M1-M3 为准（对应用于部 ①②③）。

## 14. 待澄清问题（≤3 阻塞级）

**Q1（阻塞级）**——活跃基准 `active_watermark` 的落点与推进点：
- 选项 A：落 `projects` 表新列（`Project.active_watermark` 领域字段 + ORM 列 + `ensure_project_watermark_column` 迁移），推进点 = 用户行为（触发写作/手编/chat/打开项目）。
- 选项 B：落 `ProjectConfig.extra`（零迁移，但归属在 config JSON 而非项目表）。
- **建议：A**（活跃基准是项目级事实，非配置，进表列语义清晰；迁移沿 `ensure_*_column` 幂等模式）。
- **影响**：旧库首迁后 `active_watermark_at_last_access=0` → 首次 Δt_active=当前水位（可能立即衰减）；建议首迁时 `active_watermark` 初始化 = 0 并在开启衰减时以当前水位重算（见 §7「旧库偏好」）。

**Q2（阻塞级）**——`memory_learning=false` 时显式删除总结的语义：
- 选项 A：no-op（返回 deleted:false，不删不报错）——与 ② 零行为铁律一致。
- 选项 B：仍可删（用户显式操作越闸）。
- **建议：A**（`memory_learning` 是全局闭源铁律，false 时记忆子域全路径零行为，含显式删除——除非用户需要强制清理，见下）。
- 备注：用户主动清理需求与开关冲突时，可另设「强制删除」标志（本期不做，登记 §10）。

**Q3（阻塞级）**——list 展示 vs injection 排除 superseded 的分界 + LLM 判定失败语义：
- 选项 A：list 展示全部（含 superseded），injection 排除 superseded；LLM 判定失败 → 该条标记「待判定」不入注入 + 审计（不 502）。
- 选项 B：list 也默认过滤 superseded（需 `--all` 查看）；LLM 失败 → 502。
- **建议：A**（GUI 需展示被覆盖状态；判定失败降级为「不取消注入」+ 审计，避免一次 LLM 抖动阻断整个记忆注入）。

---

## 附：变体编号与 ADR 登记

- 本 spec 声明第 22 变体（F48=21 为当前最新无冲突基线；冲突以 ADR-019 v5+ 为准）。
- 实现收尾时 ADR-019 版本表补 0.12.0 行 + F49 Feature 编号登记；ADR 决策记录对应 §12 D1-D6。
