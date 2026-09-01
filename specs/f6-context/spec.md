# F6: 上下文管理 (context_service) — 功能规格
> **端**: backend

> **Spec 版本**: 1.1 | **日期**: 2026-08-23 | **依据**: PRD v2.1 §6.1 F6, Constitution P1-P6, ADR-010, issue #593 (F6 上下文数据源补齐)
> **所属阶段**: Phase 1 — 核心引擎（v1.1 数据源补齐）
> **关联 Issues**: [#6](https://github.com/zhx-xi/InkFlow/issues/6), [#593](https://github.com/zhx-xi/InkFlow/issues/593)
> **依赖**: F1 (project_service), F2 (chapter_service), F5 (llm_service), F9 (character_service ✅), F10 (world_service ✅), F11 (outline_service ✅), F13 (foreshadowing_service ✅)
> **参考 ADR**: [ADR-010](../../adr/llm/ADR-010.md) (分层 Token 预算 → RAG 增强), [ADR-013](../../adr/llm/ADR-013.md) (Phase 2 RAG), [ADR-014](../../adr/llm/ADR-014.md) (ChatPromptTemplate), [ADR-015](../../adr/llm/ADR-015.md) (LangChain 隔离), [ADR-007v2](../../adr/architecture/ADR-007v2.md) (包结构)
> **状态**: ✅ 已实现（PR #27）

---

> **Spec 变更（v1.1，2026-08-23，issue #593）— F6 上下文数据源补齐**：
> ① CharacterSettingSource / WorldSettingSource 从 Phase 1 空实现改为**接真表**（characters / world_settings）；② OutlineSource 从读 `project.config.extra["outline"]` 改为**读 outlines 表**（overall→volume→chapter 三级，缺级降级）；③ 新增 `ContextRequest.override` 通道（`character_ids` / `foreshadowing_ids`，勾选时才注入，未勾选不注入）；④ 依赖 F9/F10/F11/F13 数据源（§10 已从「不在范围」移除对应项）。**角色注入轻量化 D5=A（名 + brief）**，`Character` 新增 `brief` 字段（D5-a1，见 f9 v1.1）。

---

## 1. 概述

为 LLM 写作 Prompt 组装上下文：按 **分层 Token 预算**（protected / compressible / dynamic）从各数据源收集上下文块，注入到系统提示词中。预算上限为模型上下文窗口的 **80%**，超出部分执行「摘要压缩」或「按优先级裁剪」。

**核心价值**: 写第 50 章时，角色设定、世界设定、前文摘要、未解决伏笔按优先级进入上下文窗口，在 Token 预算内最大化长篇小说一致性；为 Phase 2 的 RAG 增强（ADR-013）预留精确语义检索的替换点。

> **Phase 1 范围**: 分层预算机制 + 前文摘要（LLM 生成）+ 上下文组装完整实现；角色/世界/伏笔数据源为 Port 空实现（对应模块 F8/F9/F14 属 Phase 2），机制与注入格式先行就位。

---

## 2. 架构依赖方向检查

```
F3 writing_service ──> domain/services/context_service.py
                            │
                            ├──> domain/ports/context_sources.py  ← ContextSourceProtocol
                            │          ▲ (依赖倒置)
                            │   infrastructure/context/sources.py (Outline/Character/World/Foreshadowing)
                            │
                            ├──> domain/ports/summary_repository.py ← SummaryRepositoryProtocol
                            │          ▲
                            │   infrastructure/database/repositories/summary_repo.py
                            │
                            └──> domain/ports/llm_client.py + prompt_template.py (F5, 已有)
                                       ▲
                                infrastructure/llm/ (LangChainLLMClient / LangChainPromptManager)

domain/ 不 import langchain（CI 强制检查，沿用 F5 约束）
domain/ 不 import infrastructure/
```

F6 是**纯领域服务**：自身不直接调用 LLM，摘要生成与内容压缩通过 F5 的 `LLMClientProtocol` / `PromptTemplateProtocol` 完成。

---

## 3. 数据模型

### 3.1 ContextLayer 枚举 — 上下文分层

```python
class ContextLayer(StrEnum):
    PROTECTED    = "protected"     # 必须包含，不可压缩、不可裁剪
    COMPRESSIBLE = "compressible"  # 可摘要压缩，压缩后仍超预算才裁剪
    DYNAMIC      = "dynamic"       # 按预算择优选择，放不下直接裁剪
```

### 3.2 ContextSourceType 枚举 — 数据源类型

| 值 | 层 | 说明 | Phase 1 数据来源 |
|----|----|------|-----------------|
| `writing_requirements` | protected | 本次写作要求（任务指令） | F3 调用时必传入参 |
| `outline` | protected | 大纲 | `outlines` 表（F11；overall→volume→chapter 三级，缺级降级） |
| `character_setting` | compressible | 角色设定 | `characters` 表（F9；名+brief 轻量化，D5=A） |
| `world_setting` | compressible | 世界设定 | `world_settings` 表（F10） |
| `chapter_summary` | dynamic | 前文摘要 | 本模块 LLM 生成 + 缓存表 |
| `foreshadowing` | dynamic | 未解决伏笔提醒 | `foreshadowings` 表（F13） |

### 3.3 ContextItem / ContextBlock / ContextRequest / ContextAssemblyResult

```python
@dataclass
class ContextItem:
    """单一上下文条目（数据源产出）"""
    source: ContextSourceType
    title: str                    # 注入时的分段标题，如「角色：林晚」「第 3 章摘要」
    content: str                  # 内容文本
    priority: int = 0             # 同层内优先级（大者先注入）
    metadata: dict[str, Any] = field(default_factory=dict)
                                  # 如 {"chapter_id": ..., "chapter_index": 3, "location": "青云城"}

@dataclass
class ContextBlock:
    """注入块（预算分配后的产物）"""
    item: ContextItem
    layer: ContextLayer
    token_count: int
    compressed: bool = False      # True = 内容已被摘要压缩

@dataclass
class DroppedItem:
    """被裁剪的条目及原因"""
    item: ContextItem
    reason: str                   # "over_budget" | "compression_insufficient" | "layer_cap"

@dataclass
class ContextRequest:
    project_id: UUID
    chapter_id: UUID              # 目标章节（F3 正在写的章节）
    model: str                    # 目标模型，格式 provider/model_name（同 F5）
    writing_requirements: str     # 必填：写作要求（protected 层核心输入）
    max_tokens: int | None = None # 覆盖预算；None = 模型窗口 × max_ratio
    override: ContextOverride | None = None  # v1.1（#593）：勾选的角色/伏笔才注入

@dataclass
class ContextOverride:
    """v1.1（#593）：上下文注入的显式勾选通道（UI「勾选」语义）.

    - character_ids 非空 → 只注入 metadata.character_id 命中的角色 item；空 → 注入全部
    - foreshadowing_ids 非空 → 只注入 metadata.foreshadowing_id 命中的伏笔 item；空 → 注入全部
    - 只过滤 character_setting / foreshadowing 两类来源，不影响 outline/summary/世界设定等
    """
    character_ids: list[UUID] = field(default_factory=list)
    foreshadowing_ids: list[UUID] = field(default_factory=list)

@dataclass
class ContextAssemblyResult:
    """上下文组装结果 —— F3 据此渲染最终 Prompt"""
    blocks: list[ContextBlock]    # 按 protected → compressible → dynamic 有序
    budget_tokens: int
    total_tokens: int
    model: str
    dropped: list[DroppedItem]
```

### 3.4 TokenBudgetConfig — 分层预算配置（可配）

```python
class TokenBudgetConfig(BaseModel):
    max_ratio: float = 0.8        # 预算上限 = 模型窗口 × 0.8（PRD 验收：≤ 模型限制 80%）
    layer_ratio: dict[ContextLayer, float] = {
        ContextLayer.PROTECTED:    0.30,   # protected 层上限占预算 30%
        ContextLayer.COMPRESSIBLE: 0.40,   # compressible 层上限占预算 40%
        ContextLayer.DYNAMIC:      0.30,   # dynamic 层上限占预算 30%
    }
    summary_model: str | None = None      # 摘要专用模型（None = 用请求的 model）
    summary_max_chapters: int = 10        # dynamic 层最多注入的摘要数
    compress_target_ratio: float = 0.5    # 压缩目标：压缩后 ≤ 原文 token × 0.5
```

**存储位置**: `project.config.extra["context"]`（F1 的 ProjectConfig.extra 已支持任意 dict，**不改动已实现的 F1 模型**）。缺省时使用上表默认值。

**业务规则**:
- `layer_ratio` 各层求和应 ≤ 1.0；若 > 1.0，按比例归一化
- protected 层实际用量超出其 cap 时**硬失败**（见 §5）
- compressible / dynamic 层超 cap 时**软降级**（压缩/裁剪）

### 3.5 ChapterSummary — 前文摘要缓存

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| chapter_id | UUID | PK, FK→chapters.id, UNIQUE | 被摘要的章节 |
| summary | str | NOT NULL | 摘要文本（≤ 300 字） |
| model | str | NOT NULL | 生成摘要所用模型 |
| created_at | datetime | NOT NULL, AUTO | 创建时间 (UTC) |
| updated_at | datetime | NOT NULL, AUTO | 更新时间 (UTC) |

**失效规则**: `chapter.updated_at > summary.updated_at` 时缓存过期 → 重新生成。

---

## 4. 领域服务

### 4.1 ContextService (`domain/services/context_service.py`)

| 方法 | 说明 |
|------|------|
| `build_context(request: ContextRequest) -> ContextAssemblyResult` | 主入口：收集 → 预算分配 → 组装 |
| `get_budget(model: str, max_tokens: int | None) -> int` | 计算预算 = min(模型窗口, max_tokens) × max_ratio |
| `get_layer_cap(layer, budget) -> int` | 分层 cap = budget × layer_ratio[layer] |
| `render_system_prompt(result) -> str` | 将 blocks 渲染为系统提示词分段（`## {title}` 结构），F3 可直接使用 |

**build_context 流程**:

```
1. 收集: writing_requirements（请求必填） + OutlineSource + CharacterSource
         + WorldSource + SummarySource + ForeshadowingSource 各自产出 ContextItem
   （v1.1 #593：override.character_ids/foreshadowing_ids 非空时，仅保留勾选命中的
    character_setting / foreshadowing item，未勾选不注入；不影响其他来源）
2. 预算: budget = get_budget(model, max_tokens)；layer_cap = ...
3. PROTECTED 层（§4.3）: 全量注入，超 cap → ContextBudgetExceededError
4. COMPRESSIBLE 层（§4.4）: 按 priority 降序累积；超 cap → 逐项 LLM 压缩；
   压缩后仍超 cap → 裁剪（记 DroppedItem）
5. DYNAMIC 层（§4.5）: 摘要按章节序号倒序、伏笔按 priority，贪心选择至 cap
6. 输出: blocks 按 protected → compressible → dynamic 排列（层内 priority 降序）
```

### 4.2 分层预算分配算法（核心）

```python
def allocate(
    items: dict[ContextLayer, list[ContextItem]],
    budget: int,
    caps: dict[ContextLayer, int],
    compress: Callable[[ContextItem], Awaitable[ContextItem]],  # LLM 压缩（F5）
) -> ContextAssemblyResult:
    ...
```

**默认分配比例**: protected 30% / compressible 40% / dynamic 30%（可配置，PRD「分层可配置」）。

**摘要选择规则**（dynamic 层）:
- 章节摘要按 `chapter_index` **倒序**（最新在前）
- 目标章节（正在写的章节）之前的所有章节均可作为摘要来源，最多 `summary_max_chapters` 条候选
- 伏笔条目按 `priority` 降序
- 混合时：摘要优先（保证连贯性），伏笔次之；同优先级先到先得

### 4.3 protected 层规则（必须包含）

| 条目 | 来源 | 规则 |
|------|------|------|
| writing_requirements | F3 传参 | 必填；为空 → `ValueError("writing_requirements cannot be empty")` |
| outline | OutlineSource | 缺失/为空 → 跳过（不报错）；超 cap → 硬失败 |

**硬失败**: protected 层总 token 超 cap 时抛 `ContextBudgetExceededError`（含预算/用量/建议），由 F3 捕获后提示用户精简写作要求或改用更大窗口模型。

### 4.4 compressible 层规则（可压缩）

1. 按 priority 降序逐项尝试放入，直到 cap
2. 放不下的项 → 调用压缩（LLM，模板 `context_compress`），压缩后 token ≤ 原文 × `compress_target_ratio`
3. 压缩后仍超 cap → 裁剪，记 `DroppedItem(reason="compression_insufficient")`

> Phase 1 角色/世界数据源为空，本层机制通过单元测试（Mock 数据源 + Mock LLM）完整验证。

### 4.5 dynamic 层规则（按预算择优）

- 只选择、不压缩；放不下的条目直接裁剪，记 `DroppedItem(reason="over_budget")`
- 预算为 0 或候选为空 → 空注入（正常路径，不报错）

### 4.6 SummaryService (`domain/services/summary_service.py`)

| 方法 | 说明 |
|------|------|
| `ensure_summary(chapter, model) -> str` | 缓存命中（未过期）直接返回；过期/缺失则生成并 upsert |
| `summarize_chapter(chapter, model) -> str` | 调 F5 `chat()` + `context_summary` 模板，≤ 300 字 |
| `list_recent(project_id, limit) -> list[ChapterSummary]` | dynamic 层候选（按章节序号倒序） |

**失败策略**: 摘要生成失败（LLM 错误）→ 记日志 WARNING、跳过该章节摘要（不阻断写作），并在结果 `dropped` 中记录 `reason="summary_failed"`。

---

## 5. API 契约

> F6 是内部服务，正常写作路径由 F3 直接调用（无 HTTP）。以下端点用于**调试与验证**。

### 5.1 端点总览

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/context/assemble` | 组装上下文（调试） | `ContextRequest` | 200 + ContextAssemblyResult JSON |
| GET | `/api/v1/context/chapters/{chapter_id}/summary` | 查看摘要缓存 | — | 200 + `{summary, model, updated_at}` / 404 |
| POST | `/api/v1/context/chapters/{chapter_id}/summary/refresh` | 强制重新生成摘要 | — | 200 + `{summary, model, updated_at}` |

### 5.2 请求/响应示例

**组装上下文**:
```http
POST /api/v1/context/assemble
Content-Type: application/json

{
  "project_id": "3f2e1d4a-...",
  "chapter_id": "9b1c2d3e-...",
  "model": "deepseek/deepseek-chat",
  "writing_requirements": "续写第 5 章，约 3000 字，保持悬疑氛围，注意林晚的伏笔"
}
```
→ 200
```json
{
  "blocks": [
    {"item": {"source": "writing_requirements", "title": "写作要求", "content": "...", "priority": 0, "metadata": {}},
     "layer": "protected", "token_count": 42, "compressed": false},
    {"item": {"source": "chapter_summary", "title": "第 3 章摘要", "content": "...", "priority": 0,
              "metadata": {"chapter_id": "...", "chapter_index": 3}},
     "layer": "dynamic", "token_count": 180, "compressed": false}
  ],
  "budget_tokens": 51200,
  "total_tokens": 6420,
  "model": "deepseek/deepseek-chat",
  "dropped": [{"item": {"source": "chapter_summary", "title": "第 1 章摘要", "content": "...", "priority": 0, "metadata": {}},
               "reason": "over_budget"}]
}
```

### 5.3 错误响应

```json
// 404 — 项目/章节不存在
{"detail": "项目不存在"}
{"detail": "章节不存在"}

// 400 — protected 层超预算
{"detail": "上下文预算超限: protected 层需要 20000 tokens, 预算 15360 tokens"}
```

---

## 6. CLI 命令签名

Phase 1 **不提供独立 `context` 命令组**（F7 命令树限定为 serve/project/chapter/write/llm/config）。

上下文调试入口：
- `inkflow write next|continue --show-context` — 在写命令中打印本次组装的 ContextAssemblyResult（人类可读或 `--json` 信封）
- 调试 API（§5）— 独立验证

---

## 7. 文件结构

遵循 ADR-007v2 包结构，新增/修改文件：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── context.py           ← CREATE: ContextLayer, ContextSourceType, ContextItem,
│   │   │                            ContextBlock, DroppedItem, ContextRequest,
│   │   │                            ContextAssemblyResult, TokenBudgetConfig
│   │   └── __init__.py          ← MODIFY: 导出新模型
│   ├── ports/
│   │   ├── context_sources.py   ← CREATE: ContextSourceProtocol
│   │   ├── summary_repository.py← CREATE: SummaryRepositoryProtocol (get/upsert/list_recent)
│   │   ├── context_errors.py    ← CREATE: ContextBudgetExceededError, SummaryGenerationError
│   │   └── __init__.py          ← MODIFY
│   └── services/
│       ├── context_service.py   ← CREATE: ContextService（预算分配 + 组装 + render_system_prompt）
│       ├── summary_service.py   ← CREATE: SummaryService（摘要生成 + 缓存失效）
│       └── __init__.py          ← MODIFY
├── infrastructure/
│   ├── context/
│   │   ├── __init__.py          ← CREATE
│   │   └── sources.py           ← CREATE: ProjectConfigOutlineSource + Character/World/
│   │                                ForeshadowingSource（Phase 1 空实现，注明 F8/F9/F14）
│   ├── llm/
│   │   └── templates/           ← MODIFY: 新增 2 个 YAML 模板
│   │       ├── context_summary.yaml   ← 章节摘要（≤300 字）
│   │       └── context_compress.yaml  ← 通用内容压缩（目标 ≤ 原文 50%）
│   └── database/
│       ├── models/
│       │   ├── context.py       ← CREATE: ChapterSummaryORM
│       │   └── __init__.py      ← MODIFY
│       └── repositories/
│           ├── summary_repo.py  ← CREATE: SQLiteSummaryRepository
│           └── __init__.py      ← MODIFY
├── api/
│   ├── routers/
│   │   ├── context.py           ← CREATE: 3 个调试端点
│   │   └── __init__.py          ← MODIFY
│   ├── deps.py                  ← MODIFY: get_context_service, get_summary_service
│   └── app.py                   ← MODIFY: 注册 context.router
└── core/
    ├── config.py                ← MODIFY: 新增 context 配置节（default_window 等）
    └── model_registry.py        ← CREATE: ModelContextRegistry（模型窗口查询）

backend/tests/
├── conftest.py                  ← MODIFY: mock_llm_client, sample_context_items fixtures
├── test_context_budget.py       ← CREATE: 预算计算/分层 cap/归一化
├── test_context_service.py      ← CREATE: 组装全流程（Mock 数据源 + Mock LLM）
├── test_summary_service.py      ← CREATE: 摘要生成/缓存命中/过期/失败跳过
├── test_summary_repo.py         ← CREATE: 摘要缓存 CRUD
├── test_context_sources.py      ← CREATE: Outline 读取/空实现
└── test_context_api.py          ← CREATE: API 集成测试
```

### ModelContextRegistry 查询规则

| 匹配 | 规则 | 示例 |
|------|------|------|
| 精确匹配 | 查内置表 | `openai/gpt-4o` → 128000 |
| provider 前缀 | 未精确命中时按 provider 默认 | `deepseek/*` → 128000 |
| 兜底 | `config.context.default_window`（默认 128000）+ WARNING 日志 | 未知模型 |

内置表（Phase 1）: `openai/gpt-4o` 128000, `openai/gpt-4o-mini` 128000, `deepseek/deepseek-chat` 128000, `deepseek/deepseek-reasoner` 128000, `anthropic/claude-3-5-sonnet-*` 200000。

---

## 8. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| writing_requirements 为空 | `ValueError("writing_requirements cannot be empty")` |
| protected 层超预算 | `ContextBudgetExceededError`（含预算/用量/建议），不静默裁剪 |
| outline 缺失/为空 | 跳过该条目，正常组装 |
| compressible 项压缩后仍超 cap | 裁剪 + `DroppedItem(reason="compression_insufficient")` |
| dynamic 预算不足 | 只保留最新摘要，其余裁剪 + `DroppedItem(reason="over_budget")` |
| 摘要缓存过期（章节已更新） | 自动重新生成（`ensure_summary`） |
| 摘要生成失败（LLM 错误） | WARNING + 跳过该摘要 + `dropped(reason="summary_failed")`，不阻断写作 |
| 角色/世界/伏笔数据源为空（Phase 1） | 空注入，正常路径 |
| 未知模型窗口 | registry 兜底 128000 + WARNING |
| 无 tiktoken tokenizer | F5 `count_tokens` 回退字符数/4（沿用 F5 行为） |
| `layer_ratio` 求和 > 1.0 | 按比例归一化 |
| project/chapter 不存在 | API 404「项目不存在」「章节不存在」 |
| 目标模型窗口 < 4096 | 视为配置错误：`ContextBudgetExceededError`（预算过小无法工作） |

---

## 9. 测试策略

### 测试层次

```
单元测试: 预算分配算法（纯函数，无 IO）           ~10 cases
单元测试: ContextService 组装（Mock 数据源 + Mock LLM） ~12 cases
单元测试: SummaryService（Mock LLM）               ~6 cases
集成测试: SummaryRepository（in-memory SQLite）     ~4 cases
集成测试: API 端点（Mock Service）                  ~5 cases
```

### 关键测试场景

**预算分配**: 预算 = 窗口×0.8 / max_tokens 覆盖 / 分层 cap 计算 / layer_ratio 归一化 / protected 超限抛错 / compressible 压缩后放入 / 压缩后仍超裁剪 / dynamic 摘要倒序择优 / dynamic 预算不足 / 全部空数据源

**组装流程**: 完整三层层序 / 层内 priority 排序 / render_system_prompt 分段格式 / dropped 记录完整

**摘要服务**: 生成调用 F5 chat + context_summary 模板 / 缓存命中不重复生成 / 章节更新后重新生成 / LLM 失败跳过不阻断 / list_recent 按序号倒序

**API**: assemble 200 + 结构正确 / 无效 project 404 / 无效 chapter 404 / summary 查看 / summary refresh

---

## 10. 不在范围内

| 项 | 原因 |
|----|------|
| RAG 语义检索（替换压缩层摘要注入） | Phase 2，ADR-013 |
| 角色设定数据源实现 | v1.1（#593）已实现：`CharacterSettingSource` 接 `characters` 表 |
| 世界设定数据源实现 | v1.1（#593）已实现：`WorldSettingSource` 接 `world_settings` 表 |
| 伏笔管理数据源实现 | 已实现（F13）：`ForeshadowingSource` 接 `foreshadowings` 表 |
| 大纲管理（结构化大纲/多级大纲） | 已实现（F11）：`OutlineSource` 读 `outlines` 表（overall→volume→chapter 三级） |
| 摘要质量评估/多级摘要 | Phase 2+ |
| 上下文可视化调试 UI | Phase 2 Web UI |
| 独立 `context` CLI 命令组 | Phase 1 通过 `write --show-context` + API 调试 |

---

## 11. 依赖关系

```text
F6 依赖:
  F1 (project_service) — 项目配置（config.extra["context"] 预算配置）
  F2 (chapter_service) — 章节内容（摘要生成输入）、章节元数据（chapter_index/updated_at）
  F5 (llm_service)     — LLMClientProtocol.chat / count_tokens、PromptTemplateProtocol
                         （context_summary / context_compress 模板）
  F9 (character_service)  — characters 表（v1.1，CharacterSettingSource，名+brief）
  F10 (world_service)     — world_settings 表（v1.1，WorldSettingSource）
  F11 (outline_service)   — outlines 表（v1.1，OutlineSource，overall→volume→chapter）
  F13 (foreshadowing_service) — foreshadowings 表（ForeshadowingSource，open 伏笔提醒）

F6 被依赖:
  F3 (writing_service) — 写作前调用 build_context 组装上下文注入 Prompt
  F7 (CLI)             — write 命令的 --show-context 调试输出
```

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| 分层模型 | protected / compressible / dynamic（30/40/30 可配） | PRD §6.1 F6「上下文分层」，分层可配置；ADR-010 的「角色>世界>摘要>大纲」优先级留待 Phase 2 RAG 检索排序体现 |
| 预算上限 | 模型窗口 × 0.8，`max_tokens` 可覆盖 | PRD 验收标准「不超过模型限制的 80%」 |
| 数据源抽象 | `ContextSourceProtocol` Port + infrastructure 实现 | 角色/世界/伏笔模块 Phase 2 才存在，Port 空实现保证 Phase 1 可交付且不返工 |
| 摘要缓存 | `chapter_summaries` 表 + `updated_at` 失效 | 避免每章每次写作都重新生成摘要（LLM 成本高） |
| 摘要/压缩模板 | 走 F5 PromptManager（YAML） | 复用 ADR-014/015 决策，模板与代码分离 |
| 预算配置存储 | `project.config.extra["context"]` | F1 已实现，不改动其模型；每项目独立预算策略 |
| protected 超限 | 硬失败（异常） | 必须包含的内容不可静默丢弃，宁停勿错（Constitution 质量优先） |
| compressible/dynamic 超限 | 软降级（压缩/裁剪 + dropped 记录） | 可牺牲部分细节，保证写作流程不被阻断 |
| Token 计数 | 复用 F5 `count_tokens` | 单一计数实现，避免两套估算不一致 |
| 模型窗口 | `ModelContextRegistry`（精确→前缀→兜底） | 未知模型可运行且可观测（WARNING） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | 预算分配算法全部单元测试通过（含 protected 硬失败） | `pytest tests/test_context_budget.py -v` 全绿 |
| M2 | 组装全流程（Mock 数据源 + Mock LLM）通过 | `pytest tests/test_context_service.py -v` 全绿 |
| M3 | 摘要生成/缓存/失败降级通过 | `pytest tests/test_summary_service.py -v` 全绿 |
| M4 | 调试 API 3 端点通过 | `pytest tests/test_context_api.py -v` 全绿 |
| M5 | domain/ 零 LangChain import | CI 强制检查通过 |
| M6 | `write --show-context` 输出完整三层信息 | 手工验证（F7 落地后联调） |
## 14. 动作确认

> 基于 §5 API + §6 CLI + §8 边界事实的状态流表，不新增行为。

### 14.1 API 端点状态流

| 端点 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| POST /api/v1/context/assemble | 项目 + 章节存在 | build_context：收集 → 预算 → 分层组装 | 200 + ContextAssemblyResult JSON（blocks/budget_tokens/total_tokens/dropped） | 404「项目不存在/章节不存在」；400「上下文预算超限: protected 层需要 X tokens, 预算 Y tokens」 | 调试端点（正常写作路径由 F3 直接调用）；protected 层超限硬失败 |
| GET /api/v1/context/chapters/{chapter_id}/summary | 章节存在；摘要存在 | 查摘要缓存 | 200 + {summary, model, updated_at} | 404（章节不存在 / 无摘要） | — |
| POST /api/v1/context/chapters/{chapter_id}/summary/refresh | 章节存在 | 强制重新生成摘要并 upsert | 200 + {summary, model, updated_at} | 404（章节不存在） | 缓存失效规则见 §3.5 |

### 14.2 领域服务状态流（build_context 分层）

| 层/方法 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| protected 层 | writing_requirements 非空 | 全量注入（不可压缩、不可裁剪） | 注入成功 | 超 cap → ContextBudgetExceededError 硬失败 | writing_requirements 空 → ValueError("writing_requirements cannot be empty")；outline 缺失/为空 → 跳过不报错 |
| compressible 层 | — | priority 降序累积 → 超 cap 逐项 LLM 压缩（目标 ≤ 原文 token × 0.5） | 压缩后放入 | 压缩后仍超 cap → 裁剪 + DroppedItem("compression_insufficient") | 软降级，不阻断写作 |
| dynamic 层 | — | 摘要按 chapter_index 倒序 + 伏笔按 priority 贪心选择至 cap | 择优注入 | 放不下 → 裁剪 + DroppedItem("over_budget") | 只选不压缩；预算为 0 或候选为空 → 空注入（正常路径） |
| ensure_summary(chapter, model) | 章节存在 | 缓存命中（未过期）直接返回 / 过期或缺失 → 生成并 upsert | str（≤ 300 字） | LLM 错误 → WARNING + 跳过该摘要 + dropped("summary_failed")，不阻断写作 | chapter.updated_at > summary.updated_at → 缓存过期重新生成 |

### 14.3 CLI 调试入口状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow write next/continue --show-context | 项目/章节存在 | 写作时打印本次组装的 ContextAssemblyResult | 每层块标题/token/压缩标记 + 预算 + 丢弃项；--json 输出 context 字段 | 404/400 → 退出码 1 | Phase 1 无独立 context 命令组（F7 命令树限定 serve/project/chapter/write/llm/config） |

### 14.4 验收锚点

- A1：writing_requirements 为空 → ValueError("writing_requirements cannot be empty")（protected 层必填）
- A2：protected 层超预算 → ContextBudgetExceededError 硬失败（不静默裁剪）→ API 400「上下文预算超限: protected 层需要 … tokens, 预算 … tokens」
- A3：compressible 项压缩后仍超 cap → 裁剪 + DroppedItem(reason="compression_insufficient")
- A4：dynamic 预算不足 → 只保留最新摘要，其余裁剪 + DroppedItem(reason="over_budget")
- A5：摘要缓存过期（章节已更新）→ ensure_summary 自动重新生成
- A6：目标模型窗口 < 4096 → ContextBudgetExceededError（配置错误）；未知模型 → registry 兜底 default_window（默认 128000）+ WARNING
