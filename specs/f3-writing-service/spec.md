# F3: AI 写作管道 (writing_service) — 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-07-31 | **依据**: PRD v2.1 §6.1 F3, Constitution P1-P6
> **所属阶段**: Phase 1 — Sprint 1.3 (W5-W7) 核心引擎（P0-06，预计 8-12 天）
> **关联 Issues**: [#3](https://github.com/zhx-xi/InkFlow/issues/3)
> **依赖**: F1 ✅, F2 ✅, F5 ✅（前置）；F6 ✅（上下文注入）
> **参考 ADR**: [ADR-012](../../adr/ADR-012.md) (错误处理), [ADR-005v2](../../adr/ADR-005v2.md) (ChatOpenAI 兼容路由), [ADR-014](../../adr/ADR-014.md) (ChatPromptTemplate), [ADR-015](../../adr/ADR-015.md) (LangChain 隔离规则)
> **状态**: ✅ 已实现（PR #21）

---

## 1. 概述

实现 AI 写作管道的三个核心原语：**生成章节**（从大纲+上下文生成完整章节）、**续写内容**（接续已有内容继续写作）、**修改润色**（基于反馈修订指定内容）。所有输出经过**格式校验**，格式异常时自动修复重试（≤ 3 次），并保证**风格一致性**（注入项目写作风格 + 原文风格锚点）。

**核心价值**: 用户/Agent 通过统一接口获得高质量、格式稳定、风格一致的章节内容；弱模型（DeepSeek/GLM 等）输出格式不稳定时由管道自动修复重试，写作流程不中断（PRD §4 场景 4）。

**边界声明**:
- F3 只做**内容生成与校验**，不负责章节持久化（F2 职责）、不负责 Agent 编排（F4 职责）、不负责上下文分层构建（F6 职责）
- 流式输出（SSE 逐 token）和写作循环自动化（生成→审校→修订）在 PRD 中明确标注 Phase 2 / F4 职责，见 §10 不在范围内
- F3 不落库：`WritingResult` 是瞬态结果，由调用方（F4 / CLI / API 客户端）通过 F2 保存

### 1.1 依赖方向

```
 api/routers/writing.py → domain/services/writing_service.py
                                    │ 依赖 Port（依赖倒置）
        ┌───────────────────────────┼───────────────────────────┐
        ↓                           ↓                           ↓
LLMClientProtocol           PromptTemplateProtocol      ContextProviderProtocol
   (F5 已实现)                (F5 已实现)                  (F6 待实现, F3 提供 Null 实现)

 domain/ 不 import langchain / infrastructure（CI 强制检查，ADR-015）
```

---

## 2. 数据模型

### 2.1 WritingMode 枚举

```python
class WritingMode(StrEnum):
    GENERATE = "generate"   # 生成章节 — 从大纲+上下文生成完整章节
    CONTINUE = "continue"   # 续写内容 — 接续已有内容继续写作
    REVISE   = "revise"     # 修改润色 — 基于反馈修改指定内容
```

### 2.2 WritingRequest（生成章节请求）

| 字段 | 类型 | 默认值 | 验证 | 说明 |
|------|------|--------|------|------|
| project_id | UUID | **必填** | — | 所属项目（校验存在性，读取 config） |
| chapter_id | UUID | **必填** | 章节必须属于该项目 | 目标章节（内容不写入，仅校验归属） |
| outline | str | **必填** | 1-5000 字符, 去空白 | 章节大纲/要点 |
| context | str | "" | ≤ 20000 字符 | 额外上下文（角色/设定/前文摘要；F6 未就绪时由调用方传入） |
| min_words | int | 2000 | [2000, 50000] | 最少字数（PRD 验收：输出 ≥ 2000 字，不允许低于 2000） |
| max_words | int | 4000 | [min_words, 100000] | 建议字数上限（超出不强制） |
| style_hint | str? | None | ≤ 1000 字符 | 覆盖项目 config.writing_style |
| model | str? | None | — | 覆盖项目默认模型（格式 `provider/model_name`） |
| temperature | float? | None | [0.0, 2.0] | 覆盖项目默认温度 |

### 2.3 ContinueWritingRequest（续写请求）

| 字段 | 类型 | 默认值 | 验证 | 说明 |
|------|------|--------|------|------|
| project_id | UUID | **必填** | — | 所属项目 |
| chapter_id | UUID | **必填** | 章节必须属于该项目 | 目标章节 |
| existing_content | str | **必填** | ≥ 50 字符, 去空白 | 已有内容（尾部作为衔接锚点注入 prompt） |
| context | str | "" | ≤ 20000 字符 | 额外上下文 |
| target_words | int | 2000 | [200, 50000] | 本次续写目标字数 |
| style_hint | str? | None | ≤ 1000 字符 | 覆盖项目写作风格 |
| model | str? | None | — | 覆盖默认模型 |
| temperature | float? | None | [0.0, 2.0] | 覆盖默认温度 |

### 2.4 RevisionRequest（修订请求）

| 字段 | 类型 | 默认值 | 验证 | 说明 |
|------|------|--------|------|------|
| project_id | UUID | **必填** | — | 所属项目 |
| chapter_id | UUID | **必填** | 章节必须属于该项目 | 目标章节 |
| content | str | **必填** | ≥ 10 字符, 去空白 | 待修订的原文（段落或全文） |
| feedback | str | **必填** | 1-2000 字符, 去空白 | 修订意见，如"节奏太慢，删减环境描写" |
| target_range | str? | None | ≤ 200 字符 | 定位信息，如"第 3 段"、"第二章后半"；无法定位时全文修订 + warning |
| model | str? | None | — | 覆盖默认模型 |
| temperature | float? | None | [0.0, 2.0] | 覆盖默认温度（修订建议低温 0.4，见 §5.3） |

### 2.5 WritingResult（写作结果）

| 字段 | 类型 | 说明 |
|------|------|------|
| content | str | 最终文本（生成/续写/修订后的完整内容） |
| word_count | int | `count_words(content)`（复用 F2 字数统计算法） |
| mode | WritingMode | 本次操作模式 |
| format_valid | bool | 最终是否通过格式校验（false = 3 次重试仍失败，见 §6.2） |
| retry_count | int | 实际格式修复重试次数（0-3） |
| model | str | 实际使用的模型（provider/model_name） |
| token_usage | TokenUsage? | Token 消耗统计（F5 `TokenUsage`，可能不可用） |
| warnings | list[str] | 非致命警告（字数仍不足、target_range 未定位等） |

### 2.6 FormatValidationResult（内部校验结果 — 不对外暴露）

```python
@dataclass
class FormatValidationResult:
    valid: bool
    errors: list[str]      # 违反的校验规则描述（每项一条）
    # 违规项会拼接进修复 prompt，指导 LLM 针对性修复（见 §6.2）
```

---

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 用途 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/writing/generate` | 生成章节 | `WritingRequest` | 200 + WritingResult |
| POST | `/api/v1/writing/continue` | 续写内容 | `ContinueWritingRequest` | 200 + WritingResult |
| POST | `/api/v1/writing/revise` | 修改润色 | `RevisionRequest` | 200 + WritingResult |

> 三个端点均为动作型接口（不创建持久化资源），统一返回 200。耗时较长，建议调用方设置合理超时（Phase 1 不提供异步任务队列）。

### 3.2 请求/响应示例

**生成章节**:
```http
POST /api/v1/writing/generate
Content-Type: application/json

{
  "project_id": "3f2e1d4a-...",
  "chapter_id": "9c1b2a3d-...",
  "outline": "主角首次踏入宗门试炼场，遭遇同门挑衅，展露隐藏实力",
  "context": "主角：林尘，废柴体质觉醒者；宗门：青云宗，内门试炼",
  "min_words": 2000,
  "style_hint": "热血少年，轻快节奏"
}
```
→ 200
```json
{
  "content": "# 试炼场风波\n\n清晨的薄雾尚未散尽，青云宗的试炼场已经人声鼎沸……",
  "word_count": 2347,
  "mode": "generate",
  "format_valid": true,
  "retry_count": 1,
  "model": "deepseek/deepseek-chat",
  "token_usage": { "prompt_tokens": 1820, "completion_tokens": 2600, "total_tokens": 4420 },
  "warnings": []
}
```

**续写内容**:
```http
POST /api/v1/writing/continue
Content-Type: application/json

{
  "project_id": "3f2e1d4a-...",
  "chapter_id": "9c1b2a3d-...",
  "existing_content": "林尘深吸一口气，缓缓走向试炼台……",
  "target_words": 2000
}
```
→ 200 (WritingResult，`mode: "continue"`)

**修改润色**:
```http
POST /api/v1/writing/revise
Content-Type: application/json

{
  "project_id": "3f2e1d4a-...",
  "chapter_id": "9c1b2a3d-...",
  "content": "……（原文段落）",
  "feedback": "对话节奏太拖沓，删减无关寒暄，突出冲突",
  "target_range": "第 3 段"
}
```
→ 200 (WritingResult，`mode: "revise"`)

### 3.3 错误响应格式（遵循 ADR-012）

```json
// 404 — 资源不存在（领域异常 → 明确状态码）
{"detail": "项目不存在"}
{"detail": "章节不存在"}

// 422 — 请求验证失败 / 业务规则违反（Pydantic 自动生成 + 自定义）
{"detail": [{"loc": ["body", "outline"], "msg": "大纲不能为空", "type": "value_error"}]}
{"detail": "上下文 Token 预算超限，请精简大纲或上下文"}

// 500 — 基础设施异常（ADR-012: 包装为领域可见错误，记录日志，不泄漏堆栈）
{"detail": "LLM 调用失败，请稍后重试"}
```

**异常映射表**（`domain/exceptions` 已有基类，F3 复用）：

| 异常 | 映射 | 响应 |
|------|------|------|
| `NotFoundError`（项目/章节） | 404 | `"项目不存在"` / `"章节不存在"` |
| Pydantic `ValidationError` | 422 | FastAPI 自动生成 |
| `ContextBudgetExceededError`（F6 预算超限） | 422 | `"上下文 Token 预算超限，请精简大纲或上下文"` |
| `LLMRequestError`（F5 重试耗尽） | 500 | `"LLM 调用失败，请稍后重试"`（日志记录原始异常） |

---

## 4. CLI 命令签名

```bash
# 生成章节
inkflow write generate \
    --project-id <uuid> \
    --chapter-id <uuid> \
    --outline <str> \
    [--context <str>] \
    [--min-words 2000] \
    [--style <str>] \
    [--json]

# 续写内容
inkflow write continue \
    --project-id <uuid> \
    --chapter-id <uuid> \
    [--target-words 2000] \
    [--context <str>] \
    [--json]

# 修改润色
inkflow write revise \
    --project-id <uuid> \
    --chapter-id <uuid> \
    --feedback <str> \
    [--range <str>] \
    [--json]
```

### 4.1 输出格式

```bash
# 默认人类可读
✅ 章节生成成功: 2347 字 (重试 1 次, deepseek/deepseek-chat)
⚠️ 生成完成但格式校验未通过: 2347 字 (3 次重试后仍异常)

# --json 输出
inkflow write generate --project-id ... --chapter-id ... --outline "..." --json
→ {"content": "...", "word_count": 2347, "format_valid": true, "retry_count": 1, ...}
```

> `inkflow write next --project-id N --count 5`（PRD §5.4 一键写作）属于 F4 Agent 编排职责，不在 F3 CLI 范围。

---

## 5. 核心流程

### 5.1 生成管道（generate_chapter）

```
WritingRequest
  ├── 1. 校验: 项目存在 → 章节存在且属于项目 → outline/min_words 合法
  ├── 2. 组装 Prompt: system(风格) + user(大纲 + 上下文)   ← F5 PromptTemplateProtocol
  │       - system: 写作风格描述（style_hint 或 project.config.writing_style）
  │       - user: 大纲、上下文、字数要求（min_words/max_words）、格式要求
  ├── 3. 调用 LLM: LLMClientProtocol.chat()               ← F5，内部已含网络重试 ≤3
  ├── 4. 格式校验: FormatValidator.validate(content, min_words)
  │       ├── 通过 → 返回 WritingResult
  │       └── 不通过且 retry_count < 3
  │           ├── 构建修复 Prompt（原输出 + 违规项列表）
  │           ├── 重新调用 LLM（retry_count += 1）→ 回到步骤 4
  │           └── 3 次仍失败 → 返回最后一次输出, format_valid=false + warnings
  └── 5. 统计 word_count / token_usage，组装 WritingResult
```

### 5.2 续写管道（continue_writing）

与生成管道相同，差异在 Prompt 组装：
- 注入已有内容**末尾 800 字符**作为衔接锚点，要求"风格保持一致、衔接自然、不重复已有内容"
- 目标字数 = `target_words`（校验下限为 200，不强制 ≥2000——续写是增量操作）

### 5.3 修订管道（revise_content）

- 默认 `temperature = 0.4`（修订保守，项目配置可覆盖）
- Prompt 注入原文 + feedback + target_range，明确要求**保留原有叙事风格与口吻，仅修复反馈中指出的问题**
- target_range 无法定位 → 全文修订 + `warnings.append("未能定位目标范围，已对全文执行修订")`

### 5.4 风格一致性策略

| 层 | 机制 |
|----|------|
| Prompt 层 | system prompt 注入写作风格（`style_hint` > `project.config.writing_style` > 空） |
| 锚点层 | 续写注入原文尾部片段；修订注入原文全文——LLM 以原文为风格参照 |
| 校验层 | 仅做格式/字数硬校验；**深度风格一致性审计归 F16 风格检测（Phase 2）** |
| 警告层 | 输出字数低于 min_words 但格式合格时，`format_valid=true` + warnings 提示 |

---

## 6. 格式校验与自动重试

### 6.1 校验规则（FormatValidator）

| # | 规则 | 检测方式 | 修复提示示例 |
|---|------|---------|-------------|
| R1 | 无代码块包裹 | 内容以 ``` 开头/结尾 | "去掉代码块标记，直接输出正文" |
| R2 | 非 JSON/键值对泄漏 | 内容可解析为 JSON 或含 `"key":` 结构 | "不要输出 JSON，输出纯文本正文" |
| R3 | 标题格式正确 | 章节标题使用 Markdown `#`/`##`，首行非纯文本 | "章节标题使用 # 标记" |
| R4 | 无占位符残留 | 含 `{{...}}`、`[TODO]`、`[此处插入...]`、`...` 待补 | "补全占位符内容" |
| R5 | 无重复段落 | 连续 ≥ 3 段内容相同（弱模型常见故障） | "删除重复段落，合并内容" |
| R6 | 无截断 | 最后一段过短（< 20 字）且无句末标点，或以"未完待续"等结尾 | "补全结尾，完成完整段落" |
| R7 | 字数达标 | `count_words(content) >= min_words`（generate 默认 2000） | "扩写内容，达到最少 X 字" |

### 6.2 重试策略

- **修复式重试**：不丢弃原输出，将违规项列表（errors）拼入修复 Prompt 重新生成——比整篇重写成本低、针对性强（PRD §4 场景 4：格式修复，确保管道不中断）
- 上限 **3 次**（`retry_count ≤ 3`，与 PRD F3"格式异常自动重试 ≤ 3 次"一致）
- 重试仅针对**格式/字数不合格**；LLM 调用失败（`LLMRequestError`）不消耗格式重试次数——网络重试由 F5 内部处理（max_retries=3），F3 直接透传
- 3 次仍失败：返回最后一次输出 + `format_valid=false` + warnings，**不抛错**（用户可手动处理，管道不中断）

---

## 7. 边界情况与错误处理

| 场景 | 预期行为 |
|------|---------|
| outline 为空/全空白 | 422: "大纲不能为空" |
| outline > 5000 字符 | 422: "大纲不能超过 5000 个字符" |
| min_words < 2000 | 422: "最少字数不能低于 2000"（PRD 验收硬约束） |
| existing_content < 50 字符 | 422: "已有内容太短，无法续写" |
| feedback 为空 | 422: "修订意见不能为空" |
| content（修订）为空 | 422: "待修订内容不能为空" |
| 项目不存在 | 404: "项目不存在" |
| 章节不存在 | 404: "章节不存在" |
| 章节不属于该项目 | 404: "章节不存在"（不泄漏归属信息） |
| 无效 UUID 格式 | 404: 统一解析失败处理（同 F1/F2） |
| LLM 调用失败（网络/超时/Key 无效） | 500: "LLM 调用失败，请稍后重试"（F5 已内部重试 3 次；日志记录原始异常，ADR-012） |
| 上下文 Token 预算超限 | 422: "上下文 Token 预算超限，请精简大纲或上下文"（`ContextBudgetExceededError`） |
| 输出格式不合格（首次） | 自动修复重试，retry_count=1，最终 format_valid=true |
| 输出格式不合格（3 次后） | 200 + format_valid=false + warnings，不抛错 |
| 输出字数不足（3 次后） | format_valid=false + warning "字数不足: X/2000" |
| target_range 无法定位 | 全文修订 + warning |
| 项目未配置模型 | 500: "LLM 调用失败，请稍后重试"（底层 LLMRequestError） |
| temperature 超出范围 | 422: Pydantic 验证拒绝 |
| 同一章节并发写作请求 | Phase 1 不处理（无锁，最后写入者胜——F3 不落库，冲突由调用方/Phase 2 处理） |

---

## 8. 文件结构

遵循 ADR-007 包结构，新增/修改文件：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   ├── writing.py           ← CREATE: WritingMode, WritingRequest, ContinueWritingRequest,
│   │   │                                  RevisionRequest, WritingResult, FormatValidationResult
│   │   └── __init__.py          ← MODIFY: 导出新模型
│   ├── ports/
│   │   ├── context_provider.py  ← CREATE: ContextProviderProtocol (F6 实现；F3 提供 NullContextProvider)
│   │   └── __init__.py          ← MODIFY
│   └── services/
│       ├── writing_service.py   ← CREATE: WritingService (generate_chapter / continue_writing / revise_content)
│       ├── _format_validator.py ← CREATE: 格式校验规则 + 修复 Prompt 构建
│       └── __init__.py          ← MODIFY
├── api/
│   ├── routers/
│   │   ├── writing.py           ← CREATE: 3 个 REST 端点
│   │   └── __init__.py          ← MODIFY
│   ├── deps.py                  ← MODIFY: 添加 get_writing_service
│   └── app.py                   ← MODIFY: 注册 writing.router
├── cli/
│   └── commands/
│       ├── write.py             ← CREATE: write 子命令 (generate/continue/revise)
│       └── __init__.py          ← MODIFY
└── __main__.py                  ← MODIFY: 注册 write 子命令

backend/tests/
├── conftest.py                  ← MODIFY: 添加 mock_llm / sample_project+chapter fixtures
├── test_writing_models.py       ← CREATE: DTO 验证测试
├── test_format_validator.py     ← CREATE: 校验规则测试
├── test_writing_service.py      ← CREATE: 服务测试 (Mock LLM)
└── test_writing_api.py          ← CREATE: API 集成测试 (Mock Service)
```

> 复用 F5 已实现的 `infrastructure/llm/`（LangChainLLMClient + PromptManager + templates）。F3 使用现有 `writer.yaml`（生成/续写）与 `reviser.yaml`（修订）模板；如需细分可在 `infrastructure/llm/templates/` 新增 `writing_generate.yaml` 等，属 F5 范围的小扩展。

### 8.1 ContextProviderProtocol（F6 依赖的 Port）

```python
class ContextProviderProtocol(Protocol):
    """上下文注入端口 — 由 F6 (context_service) 实现。

    F6 (context_service) 未装配时，F3 使用 NullContextProvider（返回空字符串），
    上下文由调用方通过请求中的 context 字段传入（F6 已实现后由 ContextProvider 注入）。
    """

    async def get_context(
        self,
        *,
        project_id: UUID,
        chapter_id: UUID | None = None,
        mode: WritingMode,
    ) -> str:
        """返回注入到写作 Prompt 的上下文文本（角色/设定/前文摘要/伏笔）。"""
        ...
```

---

## 9. 测试策略

### 9.1 领域模型测试（TDD RED 起点）

| 测试 | 验证点 |
|------|--------|
| `test_generate_request_defaults` | 默认 min_words=2000, max_words=4000, context="" |
| `test_generate_request_empty_outline_raises` | 空/空白 outline → ValidationError |
| `test_generate_request_outline_too_long_raises` | >5000 字符 → ValidationError |
| `test_generate_request_min_words_below_2000_raises` | min_words=1000 → ValidationError（PRD 硬约束） |
| `test_continue_request_short_content_raises` | existing_content < 50 → ValidationError |
| `test_revise_request_empty_feedback_raises` | 空 feedback → ValidationError |
| `test_revise_request_default_temperature` | 默认 temperature 语义（服务层强制 0.4，模型层验证） |

### 9.2 格式校验器测试

| 测试 | 验证点 |
|------|--------|
| `test_valid_markdown_chapter` | 正常章节 → valid=True, errors=[] |
| `test_fenced_code_block_detected` | ``` 包裹 → R1 违规 |
| `test_json_output_detected` | JSON 结构 → R2 违规 |
| `test_placeholder_detected` | `{{变量}}`/`[TODO]` → R4 违规 |
| `test_duplicate_paragraph_detected` | 连续 3 段重复 → R5 违规 |
| `test_truncated_ending_detected` | 末段过短无句末标点 → R6 违规 |
| `test_word_count_below_minimum` | 字数不足 → R7 违规 |
| `test_multi_error_reporting` | 同时违规多条 → errors 全量列出 |

### 9.3 服务测试（Mock LLM，遵循 ADR-015：每个 Protocol 至少一个 Mock 实现）

| 测试 | 验证点 |
|------|--------|
| `test_generate_chapter_success` | Mock 返回合格内容 → word_count ≥ 2000, retry_count=0, format_valid=true |
| `test_generate_retries_on_bad_format` | 首次不合格 → 修复 Prompt 重试 → 成功, retry_count=1 |
| `test_generate_retries_exhausted` | 连续 3 次不合格 → format_valid=false, warnings 非空, 不抛错 |
| `test_generate_llm_error_propagates` | Mock 抛 LLMRequestError → 原样抛出（不消耗格式重试） |
| `test_generate_injects_style` | 断言 Prompt 含 project.config.writing_style / style_hint |
| `test_generate_uses_project_config` | 未传 model/temperature → 使用项目配置值 |
| `test_continue_injects_tail_anchor` | 断言 Prompt 含 existing_content 末尾 800 字符 |
| `test_revise_preserves_style_instruction` | 断言 Prompt 含"保留原文风格"指令 + 默认低温 |
| `test_revise_unlocatable_range_warns` | target_range 未定位 → 全文修订 + warning |
| `test_context_provider_injected` | Mock ContextProvider 的返回内容出现在 Prompt 中 |
| `test_null_context_provider` | NullContextProvider → 上下文仅来自请求 context 字段 |

### 9.4 API 集成测试（Mock Service）

| 测试 | 验证点 |
|------|--------|
| `test_generate_endpoint` | POST /writing/generate → 200 + WritingResult |
| `test_continue_endpoint` | POST /writing/continue → 200 |
| `test_revise_endpoint` | POST /writing/revise → 200 |
| `test_generate_project_not_found` | 项目不存在 → 404 |
| `test_generate_chapter_not_found` | 章节不存在/不属于项目 → 404 |
| `test_generate_validation_error` | outline 缺失 → 422 |
| `test_generate_llm_error_500` | LLMRequestError → 500 + 通用消息（不泄漏细节） |
| `test_budget_exceeded_422` | ContextBudgetExceededError → 422 |

### 9.5 测试覆盖率目标

- DTO 验证规则 100%（默认值 + 全部约束）
- FormatValidator 全部 7 条规则（R1-R7）+ 多违规组合
- 重试逻辑分支全覆盖：0 次/1 次/3 次耗尽/LLM 异常不消耗次数
- 3 个 API 端点 + 典型错误路径（404/422/500）

---

## 10. 不在范围内

| 项 | 原因/归属 |
|----|----------|
| SSE 流式输出（逐 token） | PRD F3 明确标注 Phase 2（首 token ≤ 2s） |
| 写作循环自动化（生成→审校→修订循环） | F4 agent_service 职责（F3 只提供单步原语） |
| `inkflow write next` 一键写作 | F4 编排 + F7 CLI |
| 上下文分层注入（角色/世界/前文摘要/伏笔） | F6 context_service 职责（F3 仅定义 Port） |
| 深度风格一致性审计 / 风格检测 | F16 一致性审计（Phase 2） |
| RAG 知识库检索增强生成 | Phase 2（vector_store 已有 Port 但未启用） |
| 章节内容持久化 / 字数落库 | F2 chapter_service 职责 |
| 后台守护自动写作 | F17 后台写作守护（Phase 2） |
| 多模型并行生成 / 对比择优 | Phase 2+ |
| 写作任务队列 / 异步任务状态查询 | Phase 2（当前同步请求） |

---

## 11. 依赖关系

```text
F3 依赖:
  F1 (project_service) ✅ — project.config 读取（model / temperature / writing_style）
  F2 (chapter_service) ✅ — 章节存在性与归属校验（count_words 复用）
  F5 (llm_service)     ✅ — LLMClientProtocol + PromptTemplateProtocol（ADR-015 隔离）
  F6 (context_service) ⏳ — ContextProviderProtocol 上下文注入（F3 提供 Null 实现先行开发，
                             F6 就绪后替换为真实实现，零改动）

F3 被依赖:
  F4 (agent_service) — Writer/Reviser 环节调用 generate_chapter / continue_writing / revise_content
  F7 (CLI)           — write 子命令
```

---

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| 重试策略 | 修复式重试（原输出 + 违规列表），≤ 3 次 | 比整篇重写成本低、针对性强；PRD 弱模型格式稳定性场景 |
| 重试耗尽 | 返回 format_valid=false + warnings，不抛错 | 写作管道不中断（PRD §4 场景 4），用户可手动处理 |
| 最小字数 | min_words 硬下限 2000（[2000, 50000]） | PRD F3 验收标准"输出 ≥ 2000 字"作为硬约束而非建议 |
| LLM 失败映射 | LLMRequestError → 500 通用消息 | ADR-012：基础设施异常不泄漏内部细节 |
| 风格一致性 | Prompt 注入 + 原文锚点，不做硬校验 | 深度审计归 F16；硬校验误报风险高、收益低 |
| 上下文注入 | 定义 ContextProviderProtocol + Null 实现 | F6 未就绪时 F3 可独立开发测试；就绪后无感替换 |
| 修订温度 | 默认 0.4 低温 | 修订是保守操作，避免风格漂移 |
| F3 不落库 | 结果瞬态返回，调用方负责持久化 | 单一职责；避免与 F2 的写入路径重复 |
