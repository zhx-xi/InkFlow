# F34: 章节审计（chapter_audit）— 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-09 | **依据**: Issue #208（2026-08-09 用户拍板立项）、PRD P1-07 审计能力延伸、Constitution P1-P6（P2 解耦 / P5 YAGNI）
> **所属阶段**: 0.6.0（#208 章节审计，估算 4-6 人天）
> **关联 Issues**: [#208](https://github.com/zhx-xi/InkFlow/issues/208)（本模块）；[#54](https://github.com/zhx-xi/InkFlow/issues/54)（F22 全文搜索——本模块为 F22「AI 自动维护」的增强触发语义前置，**F22 不阻塞等待本模块**）；[#45](https://github.com/zhx-xi/InkFlow/issues/45)（F15 审计服务——静态档案一致性，与本模块互补）
> **依赖**: ✅ F2（章节 + ChapterStatus 四态：REVIEW/FINAL 为「写完一章」天然钩子）· ✅ F5（LLM 管线，ChatOpenAI 既有）· ✅ F9（角色档案读取）· ✅ F10（世界观条目读取）· ✅ F15（静态一致性审计可委托，API 已存在）· ✅ F19（GUI 渲染层，确认流程 UI 接线）· ⏳ F22（#54，被依赖方，非前置）
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md)（模块化单体）· [ADR-002](../../adr/ADR-002.md)（六边形分层）· [ADR-012](../../adr/ADR-012.md)（错误处理）· [ADR-014](../../adr/ADR-014.md)（ChatPromptTemplate）· [ADR-015](../../adr/ADR-015.md)（LangChain 隔离）· [ADR-018](../../adr/ADR-018.md)（测试分层）· [ADR-019](../../adr/ADR-019.md)（版本里程碑 + 模块编号口径）· [ADR-027](../../adr/ADR-027.md)（覆盖率门禁）· [ADR-026](../../adr/ADR-026.md)（真实 AI CI：LLM 测试 Fake 注入 + label 触发验证）
> **状态**: 待实现 🔲（0.6.0）

---

## 1. 概述

提供**章节级审计**能力：当一章**写完**（章节状态进入 REVIEW/FINAL）或用户手动触发时，对该章内容执行四项检查——**字数**（F2 既有计数）、**人设漂移**（章节文本 vs 角色档案）、**设定漂移**（章节文本 vs 世界观条目）、**静态一致性**（委托 F15）——产出**审计报告**，并由**用户在 GUI 中确认**（接受 / 修改后重审）。

**核心价值**: 长篇写作的核心风险是「写偏了」——人设 OOC（Out of Character）、设定与世界观冲突，写到 20 万字才发现要回头改。章节审计把「检查 + 确认」嵌入写完一章的自然节点（REVIEW 状态），让漂移在发生当章就被发现。**AI 只做建议，用户是最终决策者**（与 F27「草稿+确认」哲学一致：控制感在用户手里）。

**变体定位（第 17 变体「章节审计型」）**: 本模块是 **F15 横切审计型 × F16 文本分析型 × F14 LLM 管线**的产物变体——像 F15 一样横切只读聚合多模块档案（角色/世界观/章节），像 F16 一样对**文本内容**做分析，但分析主体是 **LLM 语义漂移检查**（非确定性统计），且新增 **用户确认工作流**（F15/F16 都无确认环节）。编号依据 AGENTS.md 模块类型谱系（F30=13 / F32=14 / F21=15 / F22=16 → 本模块第 17 变体），冲突以 ADR-019 v5+ 为准。

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
GUI 确认：接受 ✅ / 修改后重审 🔄
```

**边界声明**:
- F34 做**章节级**审计（一章一报告），**不做**全书批处理审计（F15 已覆盖档案间一致性，全书级由 CLI 循环调用实现）
- F34 的 LLM 漂移检查是**辅助建议**（提示「此段与人设描述可能有冲突」），**不自动改文**；最终由作者确认/修改（F27 哲学）
- F34 **不新建持久化实体表**（审计报告为瞬态产物；审计历史可追溯性见待澄清 Q1）
- F34 的确认流程 GUI 属于本功能范围（用户拍板「最后由用户确认」）；F22 索引同步**不阻塞等待**本模块（F22 v1.1 用内容变更 + REVIEW/FINAL 状态触发增量，本模块实现后可作为增强触发点，见 §10）
- F34 不修改任何既有模块的 Repository/Service（零跨模块 MODIFY；读取全走既有只读方法 + F15 audit 委托，见 §8）

---

## 2. 数据模型

遵循「领域 Pydantic 实体 + DTO」模式（ADR-004），F34 **不新建持久化业务实体**——新增的是**瞬态报告模型**（ChapterAuditReport）+ **触发/确认 DTO**。

### 2.1 AuditCheckType（检查项枚举）

| 值 | 检查项 | 性质 | 数据源 |
|----|--------|------|--------|
| `word_count` | 字数检查 | 确定性 | F2 Chapter.word_count vs 目标（ProjectConfig.default_words / 历史基线） |
| `character_drift` | 人设漂移 | LLM 分析 | F9 Character（name/personality/background/goals） |
| `setting_drift` | 设定漂移 | LLM 分析 | F10 WorldSetting（name/content） |
| `static_consistency` | 静态一致性 | 确定性（委托 F15） | F15 AuditService（可选包含，默认含） |

### 2.2 ChapterAuditFinding / ChapterAuditReport（瞬态报告模型）

```python
class AuditSeverity(StrEnum):
    INFO = "info"       # 提示（如：章节字数低于目标 20%）
    WARNING = "warning" # 警告（如：角色行为可能与人设冲突）
    ERROR = "error"     # 错误（如：明确与设定矛盾，如「龙族畏火」却写龙喷火）

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
    # pending=待用户确认 / accepted=已接受 / rejected=已拒绝（修改后重审）
    findings: list[ChapterAuditFinding]
    summary: str            # LLM 一句话总结（可选）
    created_at: datetime
    confirmed_at: datetime | None = None
```

### 2.3 AuditTriggerRequest / AuditConfirmRequest（DTO）

```python
class AuditTriggerRequest(BaseModel):
    """手动触发审计（API 请求体；自动触发无需 body）。"""
    include_static: bool = True    # 是否包含 F15 静态一致性委托

class AuditConfirmRequest(BaseModel):
    """用户确认（接受 / 拒绝）。"""
    action: Literal["accept", "reject"]
    note: str = ""                 # 拒绝原因/备注（可选，便于追溯）
```

> **决策论证表**：报告模型选「扁平 findings 列表」而非「按检查项分组的树」——展示层按 severity 排序即可，树结构把分组逻辑硬编码进数据模型（F15 AuditReport 扁平 findings 先例）；`status` 字段承载确认生命周期（pending→accepted/rejected），不建状态机实体（单字段三值够用，YAGNI）。

---

## 3. API 契约

### 3.1 端点总览（2 个）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/projects/{project_id}/chapters/{chapter_id}/audit` | 触发审计（手动）；自动触发不经过此端点（见 §5.1） |
| POST | `/api/v1/projects/{project_id}/chapters/{chapter_id}/audit/confirm` | 用户确认（accept/reject） |

> 自动触发（章节状态进入 REVIEW/FINAL）由**前端在状态变更后调用** audit 端点（F2 状态变更端点既有，F34 不 MODIFY F2——前端编排，见 §5.1 注）。

### 3.2 请求/响应示例

```http
POST /api/v1/projects/1/chapters/2/audit
→ 200
{
  "chapter_id": "00000000-0000-0000-0000-000000000002",
  "chapter_title": "第 3 章 龙的苏醒",
  "status": "pending",
  "findings": [
    {
      "check_type": "character_drift",
      "severity": "warning",
      "message": "本章「李青焰」怒斥同伴，但角色档案性格为「温厚沉稳」，行为可能与人设冲突",
      "suggestion": "可改为隐忍不发，或先铺垫情绪积累",
      "ref_entity_id": "00000000-0000-0000-0000-00000000000c",
      "ref_entity_name": "李青焰",
      "context": "“够了！”李青焰猛地拍案而起，怒视众人……"
    },
    {
      "check_type": "word_count",
      "severity": "info",
      "message": "本章 2,845 字，低于目标 3,000 字",
      "suggestion": "",
      "ref_entity_id": null,
      "ref_entity_name": "",
      "context": ""
    }
  ],
  "summary": "本章整体符合设定，一处角色行为值得斟酌",
  "created_at": "2026-08-09T10:00:00Z",
  "confirmed_at": null
}

POST /api/v1/projects/1/chapters/2/audit/confirm  {"action": "accept"}
→ 200 { "status": "accepted", "confirmed_at": "2026-08-09T10:05:00Z" }
```

### 3.3 异常映射表

| 场景 | HTTP 状态 | 错误 body（ADR-012 统一格式） | 抛出/捕获点 |
|------|-----------|-------------------------------|-------------|
| 项目不存在 / 已软删 | 404 | `{"detail": "Project not found"}` | 复用 F9 character_errors `ProjectNotFoundError`（陷阱 16：不导出到 ports/__init__.py，router 显式 except） |
| 章节不存在 / 不属于该项目 | 404 | `{"detail": "Chapter not found"}` | 复用 F14 extraction_errors 章节错误类（F16 双入口先例） |
| confirm 时无 pending 报告 | 422 | `{"detail": "No pending audit report"}` | service 校验（报告为瞬态，重新触发后旧报告失效） |
| 请求体非法（action 非 accept/reject） | 422 | Pydantic 校验错误 | DTO 层 |
| LLM 分析失败（网络/模型） | 502? | `{"detail": "LLM analysis failed"}` | 见 §5.3（降级策略：确定性检查仍返回，LLM 检查标记 failed） |

> ⚠️ **LLM 失败语义（重要）**：LLM 漂移检查失败**不使整个审计失败**——报告返回时 LLM 类 findings 标记为降级（`severity=INFO` + message 注明「LLM 分析暂不可用」），确定性检查（字数/静态）正常返回。审计是「检查 + 建议」，LLM 不可用不该阻塞用户确认流程（§5.3）。这使 API 错误面只有 404/422，LLM 失败走 200 + 降级标记。

---

## 4. CLI 命令签名

F7 全局约定：`--json` 信封、退出码 0/1/2。F34 新增 `inkflow audit chapter` 子命令（注意：`inkflow audit` 组已被 F15 占用——F34 作为子命令挂入既有 audit 组，F15 CLI 不动，见 §8 注）。

```text
inkflow audit chapter <chapter> --project <name|id> [--include-static] [--json]

参数:
  chapter                  章节名称或 ID
  --project, -p            项目名称或 ID
  --include-static         包含 F15 静态一致性委托（默认含）
  --json                   输出 JSON 信封（data = ChapterAuditReport）

成功: 退出 0；人类可读输出按 severity 排序打印 findings；--json 输出报告
失败: 项目/章节不存在 → 退出 1；用法错误 → 退出 2
```

> CLI 只做**触发**，不做确认（确认是 GUI 交互语义；CLI 用户查看报告后自行修改章节，无需 accept/reject 状态机——Q2 待拍板：CLI 是否也支持 confirm）。

---

## 5. 章节审计模式（关键差异：LLM 漂移检查 + 用户确认工作流）

> ⚠️ **本节是 F34 与既有样板的核心差异点**：F15 §5 是「确定性规则引擎」（档案 vs 档案），F16 §5 是「文本统计 + 可选 LLM 分析」；本模块 §5 是**「确定性检查 + LLM 漂移分析 + 用户确认」三阶段工作流**——LLM 分析是主体（非可选增强），用户确认是新增环节。

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
    - < 80% → INFO；> 120% → INFO（提示），不设 ERROR（字数不是硬伤）
 ③ 并行拉取 LLM 检查输入:
    - 章节全文（chapter.content，截断到模型上下文预算，见 §5.4）
    - F9 CharacterRepository.list(pid)（活动角色）
    - F10 WorldRepository.list(pid)（活动条目）
 ④ 人设漂移检查（LLM）: 章节文本 + 角色档案 → findings（character_drift）
 ⑤ 设定漂移检查（LLM）: 章节文本 + 世界观条目 → findings（setting_drift）
 ⑥ 静态一致性（include_static=true 时）: 委托 F15 AuditService.audit(project_id)
    → 过滤出与本章相关 findings（source_chapter_id == chapter_id 或章节级），
      转映射为 static_consistency 类型（F15 报告不复制，只引用 id，见 §5.5）
 ⑦ 组装 ChapterAuditReport（status=pending）→ 返回（瞬态，不落库，Q1 拍板）
```

**模式要点**:
1. **LLM 主体 + 确定性兜底**：字数/静态是确定性检查（快、可断言），人设/设定漂移是 LLM 分析（慢、非确定）——两类 findings 同报告不同性质，测试策略分层（§9）
2. **用户确认闭环**：报告 status=pending → GUI 展示 → accept/reject → 终态；**确认只影响展示与（未来）F22 触发语义，不改变任何业务数据**（无副作用）
3. **无副作用**：审计不修改章节/档案；报告瞬态（重审计 = 新报告，旧 pending 失效）
4. **LLM 降级不阻塞**：LLM 失败 → 200 + 降级标记（§3.3/§5.3），确定性检查照常

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
- **确定性声明**：LLM findings **不承诺确定性**（模型输出可变）——测试用 Fake LLM 固定返回（F14 Fake 注入先例）；报告排序用 `(severity, check_type, ref_entity_name)` 稳定键（F15 教训：中文名排序用码点序，测试断言对齐）

### 5.3 LLM 失败降级策略

| 失败形态 | 行为 |
|----------|------|
| 模型调用异常（超时/网络/4xx/5xx） | 该检查项 findings 为空 + 报告级 `degraded: true` 标记 + message 注明；**HTTP 仍 200** |
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
| 用户确认 | 无 | 无 | **有（accept/reject 闭环）** |
| 新实体表 | 无 | 无 | **无（瞬态报告，Q1 拍板）** |
| 新 API | 1 只读端点 | 1 端点 | **2 端点（触发 + 确认）** |
| 跨模块 MODIFY | 无 | 无 | **无（前端编排自动触发）** |
| LLM 失败语义 | N/A | 可选降级 | **降级不阻塞（200 + 标记）** |

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
- `ref_entity_name` 空（字数/静态无实体）排末尾

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 |
|---|------|------|
| E1 | 项目/章节不存在 | 404（§3.3） |
| E2 | 项目无角色档案 | character_drift 跳过（§5.3） |
| E3 | 项目无世界观条目 | setting_drift 跳过 |
| E4 | 章节为空（无内容） | 报告仅字数检查（0 字 INFO）+ 提示「章节为空」，LLM 检查跳过 |
| E5 | LLM 超时/失败 | 200 + degraded 标记（§5.3），确定性检查照常 |
| E6 | LLM 返回非法 JSON | 重试 1 次 → 仍失败降级 |
| E7 | 章节超长 | 上下文截断（§5.4），报告注明「已截断」 |
| E8 | 重复触发审计 | 旧 pending 报告失效（瞬态覆盖），新报告生成 |
| E9 | confirm 时无 pending 报告 | 422（§3.3） |
| E10 | 章节状态未到 REVIEW 就手动审计 | 允许（作者可随时自检，不强制状态门槛） |
| E11 | 修改后重审 | 用户改章节 → 重新触发 audit（新报告）；旧报告 reject 留痕（Q1 拍板决定是否保留历史） |

---

## 8. 文件结构

### 8.1 CREATE/MODIFY 清单（对照真实源码树 `backend/src/inkflow/`）

| 类型 | 路径 | 说明 |
|------|------|------|
| CREATE | `domain/models/chapter_audit.py` | AuditCheckType / AuditSeverity / ChapterAuditFinding / ChapterAuditReport / AuditTriggerRequest / AuditConfirmRequest（§2） |
| CREATE | `domain/ports/chapter_audit_errors.py` | 模块专属错误（NoPendingAuditError 等）；ProjectNotFoundError/ChapterNotFoundError 复用既有类（§3.3，陷阱 16） |
| CREATE | `domain/services/chapter_audit_service.py` | ChapterAuditService：audit() 编排 + confirm() + 降级处理（§5.1） |
| CREATE | `domain/services/_audit_context.py` | 上下文预算/截断/条目选取（jieba 名称匹配，§5.4）——`_style_analyzer.py` 先例 |
| CREATE | `domain/services/_audit_prompts.py` | LLM 提示词组装（人设/设定两模板，§5.2）——`_style_llm_analyzer.py` 先例 |
| CREATE | `infrastructure/llm/templates/chapter_audit_drift.yaml` | LLM 模板（F5 PromptManager str.replace 渲染） |
| CREATE | `api/routers/chapter_audit.py` | POST audit / POST confirm（§3） |
| CREATE | `cli/commands/audit_chapter.py` | `inkflow audit chapter` 子命令（§4；**挂入 F15 audit 组**，MODIFY cli/commands/audit.py 注册） |
| CREATE | `backend/tests/unit/test_chapter_audit_models.py` | DTO/枚举校验 |
| CREATE | `backend/tests/unit/test_chapter_audit_service.py` | 编排（mock repos + **Fake LLM 固定返回**）——字数判定/降级/跳过/排序 |
| CREATE | `backend/tests/unit/test_audit_context.py` | 截断/预算/名称匹配 |
| CREATE | `backend/tests/unit/test_audit_service_confirm.py` | confirm 状态机（pending→accept/reject、重复 confirm 422） |
| CREATE | `backend/tests/unit/test_chapter_audit_llm.py` | LLM 解析（Fake 返回 JSON → 映射；非法 JSON 重试 → 降级） |
| CREATE | `tests/api/test_chapter_audit_api.py` | API 端点（404/422/200 降级/confirm） |
| CREATE | `tests/cli/test_cli_audit_chapter.py` | CLI（触发输出/--json/404） |
| MODIFY | `api/app.py` | `app.include_router(chapter_audit.router)` + import（1 行） |
| MODIFY | `api/deps.py` | ChapterAuditService 装配（注入 project/chapter/character/world repo + F15 AuditService + LLM 客户端） |
| MODIFY | `cli/commands/audit.py` | 注册 audit_chapter 子命令（`app.add_typer(...)` 或命令挂载，1-2 行） |
| MODIFY | `.github/workflows/ci.yml` | `tests/cli/test_cli_audit_chapter.py` 追加 integration-cli-backend + `tests/api/test_chapter_audit_api.py` 追加对应 integration job（陷阱 13/15） |
| CREATE | `frontend/...`（GUI 确认流程，Q3 拍板后列具体文件） | 审计结果展示 + accept/reject 交互（F19 渲染层接线） |

> ⚠️ 反向核对：上表 CREATE 均已核实不存在、MODIFY 均已确认存在（2026-08-09）；GUI 文件清单待 Q3 拍板后补全（本 spec 为后端先行，GUI 接线在实现会话细化）。

### 8.2 注入依赖（ChapterAuditService 构造签名）

零跨模块 MODIFY 的关键：注入既有 Protocol + 委托 F15：

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
    ) -> None: ...
```

> LLM 客户端注入走 F5 既有 Protocol（`domain/ports/llm_client.py`），**不新建** LLM 端口（F16 `_style_llm_analyzer` 先例：LLM 分析器接收 client 参数）。

---

## 9. 测试策略

沿用 ADR-018 三层目录 + pytest markers；LLM 测试全用 **Fake LLM 注入**（F14/F16 先例：模型下载不进测试路径；真实 LLM 走 ADR-026 e2e-ai-backend label 触发验证）。

### 9.1 测试层次

| 层 | 文件 | 内容 |
|----|------|------|
| 单元 | `tests/unit/test_chapter_audit_service.py` | 编排（mock repos + Fake LLM）：字数判定边界（79%/80%/120%/121%）、无档案跳过、降级、排序 |
| 单元 | `tests/unit/test_audit_context.py` | 截断预算、名称匹配（jieba）、超长章节采样 |
| 单元 | `tests/unit/test_chapter_audit_llm.py` | LLM JSON 解析、非法 JSON 重试、重试后降级 |
| 单元 | `tests/unit/test_audit_service_confirm.py` | confirm 状态机（accept/reject/重复 422/无 pending 422） |
| API | `tests/api/test_chapter_audit_api.py` | 404（项目/章节）/422（confirm 无 pending）/200 降级 /200 确认 |
| CLI | `tests/cli/test_cli_audit_chapter.py` | 触发输出、--json 信封、404 错误 |
| E2E（可选，Q3 拍板） | 前端确认流程 | GUI 展示 findings + accept/reject 点击闭环 |

### 9.2 关键场景

1. **漂移命中**：Fake LLM 返回人设冲突 → 报告含 ERROR finding + 正确 ref_entity
2. **LLM 降级**：Fake LLM 抛异常 → 200 + degraded 标记 + 字数检查仍在
3. **确认闭环**：audit → confirm(accept) → status=accepted + confirmed_at；重复 confirm → 422
4. **静态委托过滤**：F15 报告含 5 findings，仅 1 条挂本章 → 报告只含 1 条 static_consistency
5. **空档案**：无角色/无世界观 → 对应检查跳过不报错
6. **截断**：超长章节 → 报告注明截断 + 预算内条目选取

### 9.3 覆盖率

模块 ≥80%（ADR-027 口径）；LLM 路径用 Fake 覆盖解析/降级全分支（F16 非确定性板块 Mock 测试模式）。

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| 全书批处理审计 | F15 已覆盖档案间一致性；章节审计是单章粒度，全书级由 CLI 循环调用 |
| 自动改文/自动修复漂移 | F27 哲学：AI 只建议，用户决策；自动改文是未来 Agent 化（F27 writer-agent）职责 |
| 审计历史持久化 | Q1 待拍板（瞬态报告 vs audit_runs 记录表）；MVP 倾向瞬态 |
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
| F19 GUI | 条件依赖（Q3 拍板） | 确认流程 UI |

### 被依赖（谁依赖本模块）

| 消费方 | 方式 |
|--------|------|
| F22 搜索（#54） | 增强触发语义（审计确认 → 索引增量），**非阻塞**（F22 v1.1 已用状态变更触发） |
| GUI | 章节页审计按钮 + 确认流程 |
| CLI | `inkflow audit chapter` |

### 编号口径声明

F34 编号为 0.6.0 新增（2026-08-09 用户拍板立项，F 编号顺序 F33 之后）；变体编号第 17 变体声明依据 AGENTS.md 模块类型谱系，冲突以 ADR-019 v5+ 为准。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| D1 | 报告瞬态不落库 | 审计报告为内存产物，重审覆盖 | 审计是「即时检查」，历史追溯需求弱（Q1 可复议）；零迁移零实体（无 alembic 成本） | audit_runs 记录表（+迁移 +实体 +UI 历史页，YAGNI） |
| D2 | LLM 降级不阻塞 | 200 + degraded 标记 | 审计是建议非门禁；LLM 抖动不该阻塞作者流程；确定性检查兜底 | LLM 失败 → 500（错误面扩大 + 用户困惑） |
| D3 | 确认不改变业务数据 | accept/reject 只影响报告状态 | 无副作用原则（F15 先例）；确认语义是「展示层闭环」，业务数据由作者自行修改 | 确认时自动触发 F22 索引/自动改文（耦合 + 副作用） |
| D4 | 自动触发走前端编排 | 状态变更后前端调 audit 端点 | 零跨模块 MODIFY（F2 service 不动）；F19 前端已掌握状态变更事件 | F2 service 挂钩子（破坏零 MODIFY 纪律） |
| D5 | LLM 检查主体化（非可选） | character_drift/setting_drift 是核心检查项 | 用户设想就是「人设/设定漂移检查」；F16 的 LLM 是可选增强，F34 相反 | 仅确定性检查（不满足需求） |
| D6 | 上下文截断集中在 `_audit_context.py` | 预算常量 + 采样 + 名称匹配单一模块 | 可单测、防魔法数字散落、参数可调 | 散落 service（不可测） |
| D7 | confirm 独立端点（非 PATCH 报告） | `POST .../audit/confirm` | 报告是瞬态无资源 id；动作语义（accept/reject）用 POST 动作端点（F24 状态动作端点先例） | PATCH 瞬态报告（无 id 可 PATCH，伪资源化） |

---

## 13. 验收标准

> 「自动化载体」列：单元/API/CLI/E2E/手动。

| # | 验收标准 | 自动化载体 | 验证命令（backend 目录，uv run） |
|---|----------|------------|-------------------------------|
| M1 | 手动触发审计（API）返回报告，含字数/人设/设定/静态检查项 | API | `pytest ../tests/api/test_chapter_audit_api.py` |
| M2 | 字数判定边界正确（79%/80%/120%/121%） | 单元 | `pytest tests/unit/test_chapter_audit_service.py -k word` |
| M3 | Fake LLM 人设漂移命中 → ERROR finding + ref_entity | 单元 | `pytest tests/unit/test_chapter_audit_llm.py` |
| M4 | LLM 失败 → 200 + degraded + 确定性检查仍在 | 单元+API | `pytest tests/unit/test_chapter_audit_service.py -k degrade` |
| M5 | confirm 闭环（accept → accepted；重复 → 422） | 单元+API | `pytest tests/unit/test_audit_service_confirm.py` |
| M6 | 静态委托过滤（仅本章相关 findings 展示） | 单元 | `pytest tests/unit/test_chapter_audit_service.py -k static` |
| M7 | 空档案跳过 / 空章节仅字数 | 单元 | `pytest tests/unit/test_chapter_audit_service.py -k empty` |
| M8 | CLI `inkflow audit chapter` 输出 + --json | CLI | `pytest ../tests/cli/test_cli_audit_chapter.py` |
| M9 | 章节状态到 REVIEW 后前端可触发审计（E2E 或手动） | E2E/手动 | GUI 冒烟：状态改 REVIEW → 审计按钮 → 报告展示 |
| M10 | 全量门禁：lint/unit/integration/api/cli 绿 + 覆盖率达标 | CI | `uv run ruff check src/ tests/unit/ ../tests/` + 全量 pytest |
| M11 | 真实 LLM 验证（ADR-026 label 触发） | CI（label） | e2e-ai-backend job：真实模型一次审计成功 + 降级路径 |

> Issue #208 验收标准映射：写完一章可触发=M9 · 报告含字数/人设/设定+级别=M1/M3 · GUI 确认交互=M9（Q3 拍板后细化） · 记录可追溯=Q1 拍板（瞬态则映射为「重审可覆盖」）。

---

## 待澄清问题（评审时确认）

| # | 问题 | 选项 | 建议 |
|---|------|------|------|
| Q1 | **审计历史追溯**：审计报告是瞬态（重审覆盖）还是持久化（audit_runs 表 + 历史查询）？ | A. 瞬态（零迁移零实体，重审覆盖）<br>B. 持久化（新表 audit_runs + 查询端点 + GUI 历史页）<br>C. 瞬态 + 轻量记录（仅存 audit_id/时间/结果摘要，不做全量 findings 历史） | **A**：审计是即时检查工具，历史追溯需求弱（作者关心「当前这章是否漂移」，不关心三个月前某次检查）；B 引入实体+迁移+UI 三件成本，估算 +2 人天；若后续发现需要（如版本对比），C 是低成本演进 |
| Q2 | **CLI 是否支持确认**：CLI 只触发，还是也支持 accept/reject？ | A. CLI 只触发（确认是 GUI 交互语义）<br>B. CLI 也支持 `--confirm accept/reject` | **A**：确认是「看完报告 → 点击接受」的 GUI 心智；CLI 用户改完章节自然重审，不需要状态机；B 多一个命令面但无场景 |
| Q3 | **GUI 确认流程纳入范围**：本 spec 后端先行，GUI 接线何时做？ | A. 本模块实现时一并做（前后端同 PR，估算 +2 人天）<br>B. 后端先交付，GUI 接线归 GUI 演进 issue（#105 导航重构的后续）<br>C. 本模块实现时做最小版（只读报告列表 + accept/reject 按钮，无历史页） | **C**：用户拍板「最后由用户确认」——确认闭环是本功能核心体验，没有 GUI 确认 = 功能不完整（F15 教训：后端有、GUI 无 = 用户感知不到）；最小版不做历史页/通知，只做「审计结果展示 + 接受/拒绝」 |
