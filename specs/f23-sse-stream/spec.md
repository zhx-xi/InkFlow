# F23: SSE 流式输出 (sse_stream) — 功能规格

> **Spec 版本**: 1.1 | **日期**: 2026-08-02 | **依据**: PRD v2.1 §6.3 P1-12, Constitution P1-P6, ADR-012/015/018/019(v2)/021
> **Spec 变更**: v1.1 — 用户拍板 Q1=选项 C（统一端点 `POST /api/v1/writing/stream` + mode 判别联合 DTO）/ Q2=选项 A（流式直通 + done 帧报告，不自动重试）/ Q3=修改（CLI **默认**流式输出，消费 service 流式方法——非加 `--stream` 标志）
> **所属阶段**: 0.3.0 里程碑（**提前**，原 0.5.0——GUI 写作流式渲染的依赖项，ADR-019 v2；估算 **3-4 人天**（Q1=C 联合 DTO +0.5、Q3 CLI 默认流式 +0.5-1；v1.0 的 2-3 已含基础））
> **关联 Issues**: [#50](https://github.com/zhx-xi/InkFlow/issues/50)
> **依赖**: F3 ✅（WritingService 三原语 + DTO）；F5 ✅（**LLMClientProtocol.chat_stream 已实现**——`AsyncGenerator[StreamEvent]` 逐 token，基础设施层 LangChain astream 就绪）；F1 ✅（项目校验）；F2 ✅（章节校验）；F19（GUI 消费方，**反向依赖**——F23 端点先行，GUI 侧待 F19 落地后消费）
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md) (模块化单体), [ADR-002](../../adr/ADR-002.md) (六边形分层), [ADR-012](../../adr/ADR-012.md) (错误处理), [ADR-015](../../adr/ADR-015.md) (LangChain 隔离), [ADR-018](../../adr/ADR-018.md) (测试分层), [ADR-019](../../adr/ADR-019.md) (版本里程碑 v2——F23 提前 0.3.0), [ADR-021](../../adr/ADR-021.md) (本地内核进程化——SSE 一条代码路径两用：GUI 与云端)
> **状态**: ✅ 已实现（PR #83）

>
> **快速导航**（2026-08-08 #201）：
> [1. 概述](L13) · [2. 数据模型](L53) · [3. API 契约](L131) · [4. CLI 命令签名（Q3 拍板：默认流式）](L175)
> [5. 流式管线设计（服务层）](L210) · [6. SSE 帧协议](L304) · [7. 边界情况与错误处理](L358) · [8. 文件结构](L373)
> [9. 测试策略](L415) · [10. 不在范围内](L496) · [11. 依赖关系](L512) · [12. 关键架构决策记录](L525)
> [13. 验收标准](L539) · [待澄清问题（3 个，已全部拍板 ✅）](L556)
---

## 1. 概述

为 F3 写作管道增加 **SSE（Server-Sent Events）流式输出**：`POST /api/v1/writing/stream` 端点（mode 判别 generate/continue/revise）逐 token 推送生成内容，前端（GUI / 云端 Web）实时渲染（PRD P1-12「逐 token 推送；前端实时渲染」）。**CLI 同步升级为默认流式输出**（Q3 拍板）——`inkflow write` 三子命令直接消费 service 流式方法逐 token 打印，终端用户获得实时生成反馈。流式端点与既有非流式端点**共享同一 WritingService 与同一请求 DTO 族**，只增加一条流式代码路径——**服务端零新增依赖**（FastAPI `StreamingResponse`），SSE 帧协议自定义 JSON（§6）。

**核心价值**: 长篇生成（≥2000 字）非流式端点需等待完整生成（数十秒）后才返回，GUI 无法展示中间过程；流式端点让用户**首 token ≤ 2s 看到输出**（ADR-019 0.3.0 验收标准），逐 token 渲染出"正在写作"的实时感，并支持**中途停止**（客户端断开 → 服务端生成器终止，不泄漏任务）。CLI 默认流式将同一实时体验带给终端用户。

**与 F9-F16 样板的关系（关键差异——本模块是「传输增强型」：不新建实体表、不新增算法，为既有 WritingService 增加流式通道 + CLI 默认流式）**:

```text
F3  写作:    WritingRequest ──LLM chat──▶ WritingResult（完整等待，格式重试 ≤3）
F23 流式:    WritingRequest ──LLM chat_stream──▶ SSE 帧流 / CLI 逐 token（done 帧/末尾报告校验状态）
             复用: F3 三原语 DTO / service 校验 / prompt 构建 / FormatValidator
             新增: service 流式方法 + API StreamingResponse 端点 + SSE 帧协议 + CLI 流式输出
```

**关键事实（现状盘点，2026-08-02 实测）**:
- `LLMClientProtocol.chat_stream`（domain/ports/llm_client.py）**已存在**：`AsyncGenerator[StreamEvent]`，`StreamEvent{content, is_final, token_usage}`——F5 基础设施 `LangChainLLMClient.chat_stream` 已用 `chat_model.astream` 实现（langchain_client.py L99-137）
- `WritingService`（domain/services/writing_service.py）三原语 `generate_chapter` / `continue_writing` / `revise_content` 均走 `self._llm.chat`（非流式）+ `FormatValidator` 校验 + 格式修复重试 ≤3（`_generate_with_retry`）
- writing router（api/routers/writing.py）三个 POST 端点（/generate /continue /revise），错误映射 `_map_service_error`（LLMRequestError → 404 或 500）
- CLI（cli/commands/write.py）三子命令（next / continue / revise）走 `_build_service` + 非流式方法 + `print_result`（--json 信封）或摘要 echo
- `httpx-sse>=0.4` 已在 backend/pyproject.toml 锁定（测试侧）；服务端**不新增 sse-starlette**（StreamingResponse 手写帧，零新增依赖——ADR-025 流程零触发）

**边界声明**:
- F23 **不新建实体表、不落库**：流式输出是瞬态传输，`done` 帧/CLI 末尾携带完整写作结果（内容由调用方经 F2 保存，同 F3 §1 边界）
- F23 **不改写 F3 非流式路径**：`_generate_with_retry` 原样保留，流式走独立方法（§5）；非流式 API 端点（/generate /continue /revise）保留（0.x 兼容）
- F23 **服务端不做格式修复重试**（Q2 拍板）：流式直通 LLM 输出，`done` 帧报告 `format_valid` 校验状态；不自动重试——重试会打断用户已看到的输出流，且违背首 token ≤ 2s 目标（§5.4）
- F23 **CLI 默认流式**（Q3 拍板）：`inkflow write` 三子命令默认逐 token 输出；`--json` 保持完整信封（静默收集，§4.2）；**不提供 `--no-stream` 回退标志**（默认即流式，非流式仅 API 端点保留）
- F23 **不含前端**：GUI 流式渲染属 F19（Electron 壳）与云端 Web（2.0.0）；本 spec 只定义后端 SSE 契约与冒烟验证（§13 M8）

### 1.1 依赖方向

```
✅ api/routers/writing.py → domain/services/writing_service.py → domain/ports/llm_client.py (Protocol.chat_stream)
✅ cli/commands/write.py → domain/services/writing_service.py（同一流式方法，不经 HTTP）
✅ api/routers/writing.py → fastapi.StreamingResponse（传输层框架，仅表现层）
❌ domain/ 不出现 StreamingResponse / sse 相关 import（ADR-002/015）
```

---

## 2. 数据模型

F23 不新建业务实体表（YAGNI——流式事件是瞬态传输模型）。领域层新增**一个纯 dataclass 事件模型** `WritingStreamEvent`（§2.1）与 **API 层判别联合 DTO** `StreamWritingRequest`（§2.2，Q1=C 拍板）。SSE 帧序列化在 API 层完成（手写 JSON，§6）。**复用** F3 全部既有 DTO（`WritingRequest` / `ContinueWritingRequest` / `RevisionRequest`，domain/models/writing.py——**零变更**）与 `StreamEvent` / `TokenUsage`（domain/ports/llm_client.py——零变更）。

### 2.1 WritingStreamEvent（流式事件）

```python
@dataclass
class WritingStreamEvent:
    """流式写作事件 — service 流式方法逐事件 yield，API 层序列化为 SSE 帧（§6）.

    delta 帧: done=False，携带文本增量
    done 帧:  done=True，携带完整写作结果（format_valid/warnings/word_count/model/token_usage）
    """

    delta: str = ""
    """文本增量（当前 LLM chunk 内容；done 帧为空字符串）."""

    done: bool = False
    """是否为结束帧（LLM 流结束后发出，携带结果字段）."""

    format_valid: bool | None = None
    """done 帧: 最终内容是否通过 FormatValidator 校验（§5.4）."""

    warnings: list[str] = field(default_factory=list)
    """done 帧: 校验/重试警告列表（非流式路径 warnings 语义的流式镜像）."""

    word_count: int | None = None
    """done 帧: count_words(完整内容) 字数统计."""

    model: str | None = None
    """done 帧: 实际使用的模型名（provider/model_name）."""

    token_usage: TokenUsage | None = None
    """done 帧: Token 消耗统计（LLM 最终事件携带；可能为 None）."""

    error: str | None = None
    """error 帧: 非空表示流中错误（LLM 失败等），帧后流结束（§7 E3）."""
```

> **为什么是 dataclass 而非 Pydantic**: 与 `StreamEvent`（F5 port 模型）同为 dataclass，保持流式事件模型一致；SSE 帧 JSON 序列化在 API 层手写（§6.2），无需 Pydantic 校验层——事件是内部传输载体，不对外暴露 schema（OpenAPI 无法描述 SSE 流，§3 注）。

### 2.2 StreamWritingRequest（流式请求判别联合，Q1=C 拍板）

统一端点需要判别联合 DTO——三个包装模型**继承 F3 既有 DTO**（字段/校验零复制），各追加 `mode` 判别字段；Pydantic discriminated union 按 `mode` 值选择分支：

```python
# domain/models/writing.py — MODIFY（仅追加，既有模型零变更）

class StreamGenerateRequest(WritingRequest):
    """流式生成请求 — mode=generate 判别（Q1=C）."""

    mode: Literal["generate"] = "generate"


class StreamContinueRequest(ContinueWritingRequest):
    """流式续写请求 — mode=continue 判别."""

    mode: Literal["continue"] = "continue"


class StreamReviseRequest(RevisionRequest):
    """流式修订请求 — mode=revise 判别."""

    mode: Literal["revise"] = "revise"


StreamWritingRequest = Annotated[
    Union[StreamGenerateRequest, StreamContinueRequest, StreamReviseRequest],
    Field(discriminator="mode"),
]
```

> **判别语义**: 请求体必须显式携带 `mode`（判别字段必填，无默认值歧义——`Literal["generate"]` 默认值虽可让 FastAPI 接受缺省，但为判别确定性**要求显式传 mode**，缺失时 422）；`mode` 值与对应字段组的对应关系由客户端保证（generate 需 outline、continue 需 existing_content、revise 需 content+feedback——与 F3 DTO 各自校验一致）。API 层收到后按 `mode` 分发到对应 service 流式方法（§5.2）。
> **为什么 mode 带默认值但要求显式**: 默认值让 Pydantic 在 union 解析时能实例化（OpenAPI schema 友好），但判别字段缺失时 FastAPI 返回 422（discriminator required）——行为等价于必填。

---

## 3. API 契约

### 3.1 流式端点（新增 1 个统一端点，Q1=C 拍板）

| 方法 | 路径 | 请求体 | 响应 |
|------|------|--------|------|
| POST | `/api/v1/writing/stream` | `StreamWritingRequest`（判别联合，§2.2） | `text/event-stream`（SSE 帧流，§6） |

**请求体示例（三种 mode）**:

```json
{"mode": "generate", "project_id": "...", "chapter_id": "...", "outline": "主角首次踏入宗门试炼场", "min_words": 2000}
{"mode": "continue", "project_id": "...", "chapter_id": "...", "existing_content": "……", "target_words": 2000}
{"mode": "revise", "project_id": "...", "chapter_id": "...", "content": "……", "feedback": "节奏太慢，删减环境描写"}
```

> **端点形态决策（Q1=C 拍板）**: 统一端点 + mode 判别——①「SSE 是传输通道，动作是业务参数」语义自洽，API 面最小（1 入口）；②POST 支持长请求体（outline/context 可达 5000/20000 字符，GET+query 受 URL 限制）；③前端消费用 fetch+ReadableStream（EventSource 不支持 POST 且无法携带 header/token——ADR-021 本地 token 校验要求；云端 JWT 走 header 同理）；④与 CLI 默认流式（Q3）形成一致心智。代价 = 判别联合 DTO 复杂度（§2.2），已接受。SSE 帧格式保持标准兼容（`data:` 行 + 空行），若未来需要 EventSource 兼容变体可加 GET 端点复用同一帧协议（§12 决策记录）。

**响应头**（StreamingResponse 必须显式设置）:

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no        # 云端部署防代理缓冲（ADR-021 一条代码路径两用）
```

> **OpenAPI 注**: SSE 流响应无法用标准 JSON schema 描述——流式端点 `responses` 只声明 200 + `text/event-stream` media type（FastAPI `StreamingResponse` 天然如此），帧格式以本文档 §6 为准。

### 3.2 错误映射（流开始前——HTTP 状态码）

流式端点的**校验阶段错误在流开始前抛出**，走既有 `_map_service_error`（writing.py L30-43，**零变更**）：

| 错误 | 状态码 | 说明 |
|------|--------|------|
| 项目不存在 / 章节不存在（LLMRequestError message ∈ `_NOT_FOUND_MESSAGES`） | 404 | 流未开始，正常 HTTP 响应 |
| 请求体校验失败（Pydantic，如 outline 空 / 字数越界 / max_words < min_words） | 422 | FastAPI 自动（含 mode 缺失/非法——判别字段必填） |
| 无效 UUID | 422 | FastAPI 自动 |
| 其他 LLMRequestError（API key 缺失等） | 500 | `_map_service_error` 既有逻辑 |

**流开始后（已发送首帧）的错误走 SSE error 帧**（§7 E3）——HTTP 状态码无法在流中途变更。

---

## 4. CLI 命令签名（Q3 拍板：默认流式）

`inkflow write` 三子命令（next / continue / revise）**默认改为流式输出**：直接消费 service 流式方法（`async for ev in svc.stream_xxx(request)`），逐 token 打印 `ev.delta`，流结束后打印摘要行。`--json` 保持完整信封（静默收集 delta，流结束后输出与现有信封兼容的 JSON）。**不提供 `--no-stream`**。

### 4.1 人类模式（默认）输出格式

```text
$ inkflow write next --project-id <uuid> --chapter-id <uuid> --outline "……"
清晨的薄雾尚未散尽，青云宗的试炼场已经人声鼎沸……   ← 逐 token 追加（ev.delta 连续打印，无换行）
                                                      ← 流结束
✅ 章节生成成功: 2347 字 (deepseek/deepseek-chat)
```

- **逐 token 打印**: `typer.echo(ev.delta, nl=False)` 连续追加；chunk 间无分隔（LLM chunk 可能切词，直接拼接）
- **流结束摘要**: 镜像现有摘要行（`✅/⚠️ 章节生成成功: {word_count} 字 (重试 {retry_count} 次, {model})`）——流式不重试，`retry_count` 恒 0，摘要含 format_valid 状态（⚠️ 时 warnings 逐条 echo）
- **continue**: `✅ 续写完成: {word_count} 字 ({model})`；**revise**: `✅ 修订完成: {word_count} 字 ({model})`
- **--count > 1**（仅 next）: 逐章流式循环——每章完成后打印该章摘要行，章间空行分隔；`--count 2` = 两次流式生成
- **中断（Ctrl+C）**: `KeyboardInterrupt` 终止生成器（`aclose` 由 async generator 生命周期保证），退出码 130（Typer 默认）

### 4.2 `--json` 模式（信封兼容）

`--json` 时**静默收集**全部 delta（不逐 token 打印），流结束后输出与现有信封兼容的结果：

```json
{"ok": true, "data": {"content": "完整全文", "word_count": 2347, "mode": "generate", "format_valid": true, "retry_count": 0, "model": "deepseek/deepseek-chat", "token_usage": {...}, "warnings": []}}
```

- 构造 `WritingResult`（收集的 content + done 帧字段）→ `model_dump(mode="json")` → `print_result`（现有信封路径零变更）
- `--count > 1` + `--json`: 数组信封（镜像现有 next 逻辑 L78-84）
- **错误**: LLM 错误在 `async for` 中抛出 → `print_error(cli_ctx, "LLM_ERROR", ...)`（现有模式）；NOT_FOUND（项目/章节）在流开始前由 service 校验抛出 → 404 语义映射为 NOT_FOUND 退出码（现有模式）

> **CLI 消费 service 而非 HTTP 端点（架构要点）**: CLI 与 API 同为表现层适配器（六边形），直接调用 `WritingService.stream_*`（同一 domain 管线）；error 帧是 HTTP 传输层概念，CLI 直接捕获异常（§5.3 注）。

---

## 5. 流式管线设计（服务层）

### 5.1 WritingService 新增方法（3 个 async generator）

```python
# domain/services/writing_service.py — MODIFY

async def stream_generate(self, request: WritingRequest) -> AsyncGenerator[WritingStreamEvent, None]:
    """流式生成章节 — 校验 → 构建 prompt → llm.chat_stream 逐事件 yield → done 帧."""

async def stream_continue(self, request: ContinueWritingRequest) -> AsyncGenerator[WritingStreamEvent, None]:
    """流式续写 — 语义镜像 continue_writing."""

async def stream_revise(self, request: RevisionRequest) -> AsyncGenerator[WritingStreamEvent, None]:
    """流式修订 — 语义镜像 revise_content."""
```

**每个流式方法内部结构**（以 `stream_generate` 为例，其余镜像）：

```text
1. 项目校验:   await self._project_repo.get(request.project_id)          # 不存在 → LLMRequestError("项目不存在")（同非流式）
2. 章节校验:   await self._validate_chapter(...)                          # 复用既有私有方法
3. 参数解析:   style/model/temperature 解析（同 generate_chapter L64-68）
4. 上下文:     await self._context_provider.get_context(...)              # 复用（mode="generate"）
5. Prompt:     system_msg + user_msg 构建（与 _generate_with_retry L182-195 相同的组装逻辑）
6. 流式调用:   async for ev in self._llm.chat_stream(messages=..., model=..., temperature=...):
                  yield WritingStreamEvent(delta=ev.content)              # 透传文本增量（is_final 事件 delta 为空）
7. 结束帧:     完整内容 = 拼接所有 chunk → FormatValidator.validate → yield WritingStreamEvent(
                  done=True, format_valid=..., warnings=..., word_count=count_words(...),
                  model=..., token_usage=...)
```

> **设计要点 — prompt 构建复用**: 第 5 步的 prompt 组装与 `_generate_with_retry` 重复——抽取私有方法 `_build_generate_messages(outline, context, min_words, style)` 供两路径共用（**跨方法 REFACTOR**，非跨模块；非流式路径行为不变，F3 测试全绿保证）。`stream_continue` 的 prompt 组装（"续写：{tail}"）同理抽取。
> **设计要点 — 格式校验**: `revise_content` 无格式校验（F3 L119-160 直通 chat），`stream_revise` 同样不做 FormatValidator（done 帧 format_valid 恒 None → API 层序列化省略该字段，§6.2）。
> **设计要点 — 错误传播**: service 流式方法中 LLM 错误**直接 raise**（`chat_stream` 内部已包装 LLMRequestError，langchain_client.py L129-134）——`async for` 消费方（API 层 `_event_generator` / CLI `_run`）各自捕获处理（§5.2/§4.2），service 层不吞异常。

### 5.2 API 端点实现（StreamingResponse）

```python
# api/routers/writing.py — MODIFY（新增）

@router.post("/stream")
async def stream_write(
    data: StreamWritingRequest,
    request: Request,
    svc: WritingService = Depends(get_writing_service),
) -> StreamingResponse:
    """流式写作 — SSE 逐 token 推送（mode 判别分发，帧协议见 spec §6）."""
    if data.mode == "generate":
        events = svc.stream_generate(data)
    elif data.mode == "continue":
        events = svc.stream_continue(data)
    else:
        events = svc.stream_revise(data)
    return _stream_response(request, events)
```

```python
# 内部辅助 — 共用（§5.3 断开处理封装）

async def _event_generator(
    request: Request,
    events: AsyncGenerator[WritingStreamEvent, None],
) -> AsyncGenerator[str, None]:
    """包装 service 流 → SSE 帧字符串；客户端断开立即停止（§5.3）."""
    try:
        async for ev in events:
            if await request.is_disconnected():
                await events.aclose()          # 客户端断开 → 终止 service 生成器（不泄漏任务）
                return
            yield _encode_sse(ev)               # §6.2 帧编码
    except LLMRequestError as exc:
        yield _encode_sse(WritingStreamEvent(done=True, error="LLM 调用失败，请稍后重试"))  # §7 E3
```

> **注意**: `is_disconnected()` 检查在每次事件循环中执行；StreamingResponse 自身在客户端断开时会抛 `ClientDisconnect`（starlette 内部处理），双重保障。LLMRequestError 在生成器内部由 `chat_stream` 抛出——`_event_generator` 捕获转 error 帧；`_map_service_error` 的 500 分支**不适用**于流中途（已发帧），仅流开始前的校验异常走 HTTP 状态码（§3.2）。

### 5.3 客户端断开语义

- **服务端**: 每帧前 `request.is_disconnected()` → 真则 `events.aclose()` 终止 LLM 流（LangChain astream 的 async generator 被 close 会中止底层请求），**不泄漏后台任务**
- **客户端**: 断开后服务端不再推送；客户端重连需重新发起请求（**从头重拉**，MVP 不做断点续传——§10）
- **CLI**: `KeyboardInterrupt`/异常退出时 async generator 的 `aclose` 由 Python 生命周期保证（`async for` 中途退出自动 close）
- **测试**: httpx-sse `aconnect_sse` 上下文退出即模拟客户端断开（§9）

### 5.4 格式校验与自动重试（Q2 拍板：直通 + 报告）

**流式直通 + done 帧/摘要报告校验状态**（Q2=A 拍板，v1.0 已按此设计）：

- `stream_generate`/`stream_continue` 结束时对完整内容做 `FormatValidator.validate(content, min_words)` → `done` 帧携带 `format_valid` / `warnings`（CLI 摘要行 ⚠️ + warnings 逐条）
- 格式无效时**不自动重试**——用户已看到完整输出流，重试需清空重来；warnings 提示"格式校验未通过"，客户端可让用户决定是否重试（再次发起流式请求 / CLI 重跑）
- **自动重试设置项否决**（Q2 拍板注）：流式下自动重试语义混乱（重试期间用户已见第一遍输出），v1.0 不提供，§10 声明远期

---

## 6. SSE 帧协议

### 6.1 帧序列（客户端视角）

```text
POST /api/v1/writing/stream
→ 200 text/event-stream

data: {"delta": "清晨的薄雾尚未散尽", "done": false}
data: {"delta": "，青云宗的试炼场已经", "done": false}
data: {"delta": "人声鼎沸……", "done": false}
data: {"done": true, "format_valid": true, "word_count": 2347, "model": "deepseek/deepseek-chat", "token_usage": {"prompt_tokens": 1820, "completion_tokens": 2600, "total_tokens": 4420}}
```

**帧序列不变量**:
1. 首个事件前可能有 0 帧（LLM 首 token 延迟，验收 ≤ 2s）
2. `delta` 帧可 0 至 N 个（N ≥ 0）；全部 delta 拼接 = 最终完整内容
3. 恰好 1 个 `done` 帧（`done: true`）结尾；此后连接关闭
4. 流中错误：`done` 帧携带 `error` 字段（§7 E3），`format_valid` 等结果字段省略
5. `revise` 流式：done 帧无 `format_valid`（§5.1 注）

### 6.2 帧编码（`_encode_sse`）

```python
def _encode_sse(ev: WritingStreamEvent) -> str:
    """WritingStreamEvent → SSE 帧字符串（data: <json> + 空行）."""
    payload: dict = {"done": ev.done}
    if ev.delta:
        payload["delta"] = ev.delta
    if ev.error:
        payload["error"] = ev.error
    if ev.format_valid is not None:
        payload["format_valid"] = ev.format_valid
    if ev.warnings:
        payload["warnings"] = ev.warnings
    if ev.word_count is not None:
        payload["word_count"] = ev.word_count
    if ev.model:
        payload["model"] = ev.model
    if ev.token_usage:
        payload["token_usage"] = dataclasses.asdict(ev.token_usage)
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

> **字段省略规则**: `None`/空值字段不进入 JSON（保持帧最小化）；`ensure_ascii=False` 保证中文原文可读（调试友好）。`TokenUsage` 为 dataclass（llm_client.py L49-55）——用 `dataclasses.asdict` 序列化。

### 6.3 标准 SSE 兼容性

- 帧 = `data:` 行 + `\n\n` 空行（标准 SSE 格式，任何 SSE 客户端可解析）
- **不发送** `event:` 类型行（统一 message 事件）；**不发送** `id:` 行（MVP 无断点续传，§10）
- 心跳：MVP 不发送注释心跳行（`chat_stream` 流活跃期间无空闲；LLM 长停顿场景远期加，§10）

---

## 7. 边界情况与错误处理

| # | 场景 | 处理 | 帧/状态码/CLI |
|---|------|------|-----------|
| E1 | 项目不存在 / 章节不存在 / 跨项目章节 | 流开始前 `_map_service_error` | HTTP 404 / CLI NOT_FOUND 退出码 |
| E2 | 请求体校验失败（outline 空、字数越界、UUID 无效、**mode 缺失/非法**） | Pydantic 自动（判别字段必填） | HTTP 422 / CLI 退出码 2 |
| E3 | 流中 LLM 调用失败（网络/超时/Provider 错误） | `_event_generator` 捕获 → error 帧 → 流结束；CLI `async for` 抛出 → LLM_ERROR | `data: {"done": true, "error": "LLM 调用失败，请稍后重试"}` / CLI LLM_ERROR 退出码 |
| E4 | 客户端断开（关闭连接 / 取消请求 / Ctrl+C） | `is_disconnected()` → `events.aclose()` 终止生成器 | 连接关闭，服务端无泄漏任务；CLI 退出码 130 |
| E5 | LLM 返回空流（0 个 delta） | 直接发 done 帧（format_valid=false + warning「生成内容为空」） | 正常结束 / CLI ⚠️ 摘要 |
| E6 | 格式校验失败（generate/continue） | done 帧 `format_valid=false` + warnings（不重试，§5.4） | 正常结束 / CLI ⚠️ + warnings |
| E7 | `revise` 目标范围未定位 | warnings 携带「未能定位目标范围…已全文修订」（镜像非流式 L127-128） | 正常结束 / CLI warnings |
| E8 | token_usage 不可用 | done 帧省略该字段 | 正常结束 |

---

## 8. 文件结构

遵循 ADR-007v2 包结构。新增/修改文件（**对照主仓现行树逐文件核对**；F23 除 writing_service.py 内 prompt 组装抽取（同文件 REFACTOR）外**零跨模块 MODIFY**）：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   └── writing.py         ← MODIFY: 新增 WritingStreamEvent（§2.1）+ StreamGenerateRequest /
│   │                                      StreamContinueRequest / StreamReviseRequest /
│   │                                      StreamWritingRequest 判别联合（§2.2）
│   └── services/
│       └── writing_service.py ← MODIFY: 新增 stream_generate / stream_continue /
│                                      stream_revise（§5.1）+ _build_generate_messages /
│                                      _build_continue_messages 抽取（§5.1 注）
├── api/
│   └── routers/
│       └── writing.py         ← MODIFY: 新增 /stream 端点（mode 判别分发）+ _event_generator /
│                                      _encode_sse 辅助（§5.2/§6.2）；app.py 零变更
│                                    （writing.router 已注册）
└── cli/
    └── commands/
        └── write.py           ← MODIFY: 三子命令默认流式输出（§4.1）+ --json 静默收集信封
                                      （§4.2）+ --count 循环 + 中断处理
```

```text
backend/tests/unit/
├── test_writing_models.py     ← MODIFY: WritingStreamEvent 字段/默认值 + StreamWritingRequest
│                                     判别联合（mode 分发/非法 mode 422/字段校验继承）断言（§9 M1）
├── test_writing_service.py    ← MODIFY: 流式方法测试（§9 M2/M3——Mock chat_stream）
tests/api/
├── test_writing_api.py        ← MODIFY: 流式端点 SSE 测试（httpx-sse，§9 M4/M5）
tests/cli/
└── test_cli_write.py          ← MODIFY: CLI 流式测试（§9 M6/M7——Mock service 流式方法，
                                      逐 token 输出断言 + --json 信封 + --count + 错误路径）
```

**零新增运行时依赖**（服务端 StreamingResponse；测试侧 httpx-sse 已锁定）。**ci.yml 零变更**——`tests/api/test_writing_api.py` 已在 `integration-writing-backend` job（L261）、`tests/cli/test_cli_write.py` 已在 `integration-cli-backend` job（L336）显式列出；backend/tests/unit/ 自动覆盖。

---

## 9. 测试策略

### M1 模型测试（test_writing_models.py MODIFY）

- `WritingStreamEvent` 默认值（delta="" / done=False / 其余 None）
- done 帧构造：format_valid/warnings/word_count/model/token_usage 赋值
- error 帧构造：error 字段 + done=True
- **判别联合（Q1=C）**: `StreamWritingRequest` 按 mode 解析到正确分支（generate/continue/revise）；mode 缺失/非法 → ValidationError（422 语义）；字段校验继承（如 StreamGenerateRequest.outline 空 → 422；StreamContinueRequest.existing_content < 50 字符 → 422）

### M2 service 流式方法·generate（test_writing_service.py MODIFY）

Mock `llm_client.chat_stream`（AsyncMock 返回 async generator）：

```python
async def _fake_stream(chunks: list[str]):
    for c in chunks:
        yield StreamEvent(content=c)
    yield StreamEvent(content="", is_final=True)
```

- 项目校验失败 → LLMRequestError（"项目不存在"）——**流开始前抛出**（await 首个事件即异常）
- 章节校验失败 → LLMRequestError（"章节不存在"）/ 跨项目 → 同上
- 成功路径：delta 事件逐个透传（chunk 拼接 == 期望全文）；done 帧 format_valid=True、word_count 正确、model/token_usage 透传
- 格式无效：done 帧 format_valid=False + warnings（不重试断言：`chat_stream` 仅调用 1 次）
- 空流：done 帧 format_valid=False + 「生成内容为空」warning
- prompt 组装：`chat_stream` 的 messages 参数断言（与 `_generate_with_retry` 相同组装——回归保护抽取 REFACTOR）

### M3 service 流式方法·continue/revise

- `stream_continue`: tail 截断（existing_content[-800:]）、target_words 透传、done 帧语义
- `stream_revise`: 无 FormatValidator（done 帧 format_valid 省略）、target_range 未定位 warning、messages 断言（system 修订助手 + 原文/意见）

### M4 API 流式端点·成功路径（tests/api/test_writing_api.py MODIFY，httpx-sse）

```python
from httpx_sse import aconnect_sse

async def test_stream_generate_deltas(override_writing_service):
    # Mock WritingService.stream_generate → 预置 WritingStreamEvent 序列（2 delta + done）
    async with _client() as client:
        async with aconnect_sse(client, "POST", "/api/v1/writing/stream", json={"mode": "generate", ...}) as sse:
            events = [ev async for ev in sse.aiter_sse()]
    # 断言: 2 个 delta 帧（data.delta 拼接 == 全文）+ 1 个 done 帧（done=true, format_valid=true）
    # 断言: 响应头 Content-Type == text/event-stream
```

- 三 mode 各 1 个成功用例（generate/continue/revise 判别分发正确）
- done 帧字段断言（format_valid/warnings/word_count/model/token_usage 完整透传）

### M5 API 流式端点·错误路径

- 404（Mock service raise LLMRequestError("项目不存在")）→ 普通 HTTP 404（非 SSE）
- 422（outline 空 / max_words < min_words / **mode 缺失或非法**）→ 普通 HTTP 422
- 流中 LLM 错误（Mock chat_stream raise LLMRequestError）→ SSE error 帧（done=true + error 文案）+ 流结束
- 客户端断开（`aconnect_sse` 上下文提前退出）→ service 生成器被 close（Mock 断言 `aclose` 被调用 / is_disconnected 路径）

### M6 CLI 流式·人类模式（tests/cli/test_cli_write.py MODIFY，Q3 拍板）

- Mock `WritingService.stream_generate` → async generator 逐 token（现有 `mock_writing_service` fixture 改为 mock 流式方法）
- `next` 默认流式：stdout 含逐 delta 文本（拼接 == 全文）+ 摘要行（✅/⚠️ + word_count + model）
- `continue` / `revise` 流式输出 + 摘要行
- `--count 2`: 两次流式 + 两个摘要行 + 章间分隔
- Ctrl+C / KeyboardInterrupt: 退出码 130（mock 抛 KeyboardInterrupt 路径）
- NOT_FOUND（service raise LLMRequestError("项目不存在")）→ 退出码 1 + NOT_FOUND 错误
- LLM_ERROR（流中异常）→ 退出码 1 + LLM_ERROR 错误

### M7 CLI 流式·--json 信封（Q3 拍板）

- `next --json`: 静默收集（stdout 无逐 delta）→ json 信封 content == 全文拼接、format_valid/word_count/model/token_usage 完整
- `--count 2 --json`: 数组信封（镜像现有逻辑）
- `revise --json`: 信封含 warnings（target_range 未定位）

### M8 全量回归 + 覆盖率 + lint/type + 冒烟

- `pytest -v` 全绿（backend/tests/unit/ 与 tests/api/、tests/cli/ 分命令跑——F15 教训）
- F23 新增代码行覆盖 ≥ 80%（writing_service.py / writing.py / write.py 流式部分）；全仓 ≥ 60%
- ruff + mypy 通过（CI 门禁 ADR-017）；domain/ 零框架 import（ADR-002/015——writing_service.py 不出现 StreamingResponse/sse）
- **冒烟（ADR-019 0.3.0 验收）**: `inkflow serve` → `curl.exe -N -X POST http://127.0.0.1:8000/api/v1/writing/stream -H "Content-Type: application/json" -d '{"mode":"generate",...}'` → 逐 token 输出 + 首 token ≤ 2s + done 帧；`inkflow write next --project-id ... --chapter-id ... --outline "……"` → 终端逐 token 打印 + 摘要行

---

## 10. 不在范围内

| 项 | 原因/归属 |
|----|----------|
| GUI 流式渲染 / 前端 EventSource 消费 | F19（Electron 壳）+ 云端 Web（2.0.0）；F23 只交付后端契约 + CLI 消费 |
| 断点续传（`id:` 帧 + Last-Event-ID 重连补发） | MVP 从头重拉；续传复杂度高收益低 |
| SSE 心跳注释帧 | LLM 流活跃期间无空闲；长停顿场景远期加 |
| 流式自动重试（格式无效自动重新生成） | Q2 拍板：直通 + done 帧报告（§5.4）；重试语义与流式渲染冲突，远期按需 |
| `--no-stream` CLI 回退标志 | Q3 拍板：默认即流式；非流式输出仅 API 端点保留（0.x 兼容） |
| 多客户端广播 / 共享流 | 无此需求（每请求独立流）；云端远期再评估 |
| GET + EventSource 兼容端点 | 前端 fetch+ReadableStream 已覆盖（Q1 拍板）；EventSource 变体远期按需加 |
| Token 鉴权 / 本地安全基线 | F19（ADR-021：`inkflow serve` 强化版 --port 0 + token + WAL）；F23 端点自身无鉴权，由 serve 层统一校验 |
| 非流式 API 端点移除 | F3 既有端点保留（0.x 兼容；1.0.0 契约冻结前允许评估） |

---

## 11. 依赖关系

| 依赖 | 状态 | 说明 |
|------|------|------|
| F3 WritingService / DTO / FormatValidator | ✅ 已实现 | 流式方法复用其校验与 prompt 组装（§5.1）；DTO 继承追加 mode（§2.2） |
| F5 LLMClientProtocol.chat_stream | ✅ 已实现 | `AsyncGenerator[StreamEvent]` 逐 token（langchain_client.py） |
| F1 项目仓储 / F2 章节仓储 | ✅ 已实现 | 校验复用（deps.py 既有装配） |
| httpx-sse ≥ 0.4 | ✅ 已锁定 | 测试侧（pyproject.toml L23） |
| F19 GUI | ⬜ 未开始 | 反向依赖：F23 端点先行，F19 落地后消费 |
| 服务端新增依赖 | ❌ 无 | StreamingResponse 零新增（ADR-025 零触发） |

---

## 12. 关键架构决策记录

| # | 决策 | 理由 | 备选 |
|---|------|------|------|
| D1 | 服务端用 FastAPI `StreamingResponse` 手写 SSE 帧，**不引入 sse-starlette** | 帧协议极简（data 行 + 空行），手写 20 行；零新增依赖（ADR-025 流程零触发）；sse-starlette 主要价值是 ping/事件命名等，MVP 不需要 | sse-starlette（+1 依赖，协议封装）；WebSocket（双向但复杂，SSE 单向足够） |
| D2 | **统一端点 `POST /api/v1/writing/stream` + mode 判别联合 DTO（Q1=C 拍板）** | 「SSE 是传输通道，动作是业务参数」语义自洽；API 面最小（1 入口）；与 CLI 默认流式形成一致心智；代价 = 判别联合 DTO 复杂度（§2.2，已接受） | mirror 三端点 `/generate/stream` 等（与既有 API 一一对应，但端点面 ×3）；`/writing/{chapter_id}/stream`（chapter_id 入路径——与 F3 body 风格不一致） |
| D3 | 流式直通 LLM 输出，格式校验只在 done 帧报告，**不自动重试（Q2=A 拍板）** | 重试打断已见输出流；首 token ≤ 2s 目标；客户端可自行决定重发（GUI 按钮/CLI 重跑） | 先完整生成校验再回放（首 token 延迟 = 完整生成时间，违背流式意义）；自动重试设置项（语义混乱，v1.0 否决） |
| D4 | `WritingStreamEvent` dataclass + API 层 `_encode_sse` 手写 JSON | 事件是内部传输载体不进 OpenAPI；与 F5 StreamEvent dataclass 一致；字段省略规则保持帧最小化 | Pydantic 模型（过度设计——无校验需求） |
| D5 | 客户端断开用 `is_disconnected()` + `events.aclose()` 双保障 | 不泄漏后台 LLM 任务（服务端资源）；StreamingResponse 内部 ClientDisconnect 兜底 | 仅依赖 starlette 自动处理（无法主动终止 service 生成器） |
| D6 | 流中错误用 SSE error 帧（done + error），非 HTTP 状态码 | HTTP 状态码在流中途不可变更；error 帧让客户端有统一结束语义（恰好 1 个 done 帧不变量） | 直接断连（客户端无法区分错误与正常结束）；HTTP 500 后断连（非标准） |
| D7 | **CLI 默认流式，直接消费 service 流式方法（Q3 拍板）** | CLI 与 API 同为表现层适配器（六边形）——共享 domain 流式管线，不经 HTTP 打自己；终端用户获得实时反馈（真实 UX 提升）；`--json` 静默收集保持信封兼容 | `--stream` 标志（默认非流式，用户需显式开启——Q3 拍板默认即流式）；CLI 消费 HTTP SSE 端点（多一跳，无意义） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | WritingStreamEvent 模型 + StreamWritingRequest 判别联合（mode 分发/非法 mode/字段校验继承） | `pytest tests/unit/test_writing_models.py -v` 全绿（流式相关用例） |
| M2 | service 流式·generate（校验前置 / delta 透传 / done 帧完整 / 格式无效不重试 / 空流 / prompt 组装回归） | `pytest tests/unit/test_writing_service.py -v` 全绿（流式用例） |
| M3 | service 流式·continue/revise（tail 截断 / 无 FormatValidator / target_range warning） | `pytest tests/unit/test_writing_service.py -v` 全绿（流式用例） |
| M4 | API 统一端点成功路径（httpx-sse delta 序列 + done 帧 + Content-Type + 三 mode 判别） | `pytest tests/api/test_writing_api.py -v` 全绿（流式用例） |
| M5 | API 错误路径（404/422 流前 HTTP / 流中 error 帧 / 客户端断开终止） | `pytest tests/api/test_writing_api.py -v` 全绿（流式用例） |
| M6 | CLI 人类模式流式（逐 token 输出 + 摘要 + --count 循环 + Ctrl+C + NOT_FOUND/LLM_ERROR） | `pytest tests/cli/test_cli_write.py -v` 全绿（流式用例） |
| M7 | CLI --json 信封（静默收集 + 信封兼容 + --count 数组） | `pytest tests/cli/test_cli_write.py -v` 全绿（流式用例） |
| M8 | 全量回归 + 覆盖率 + lint/type + 冒烟 | `pytest -v` 全绿（单元+集成+CLI 分命令）；流式新增代码行覆盖 ≥ 80%、全仓 ≥ 60%；ruff + mypy 通过；domain/ 零框架 import；`curl.exe -N` 逐 token + 首 token ≤ 2s + done 帧；`inkflow write next` 终端流式 |

> **验收标准 ↔ Issue #50 映射**: ①「逐 token 推送」→ M2/M4/M6/M8（chat_stream 透传 + httpx-sse delta 序列 + CLI 终端流式 + curl 实测）；②「前端实时渲染」→ 后端契约就绪（M4/M8），渲染属 F19/#79；③「SSE 端点同时供云端 Web 消费（2.0.0）」→ D1/D6 + 响应头 X-Accel-Buffering（一条代码路径两用，ADR-021）；④「首 token ≤ 2s」→ M8；⑤「CLI 默认流式（Q3）」→ M6/M7/M8。

---

## 待澄清问题（3 个，已全部拍板 ✅）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | **端点形态？** 选项 A：mirror 三端点 + POST（`/generate/stream` 等，复用 F3 DTO）——与既有 API 一一对应、支持长 body；选项 B：GET + EventSource 兼容端点——浏览器原生自动重连，但 GET 无法携带长 body 且 token 进 URL（ADR-021 冲突）；选项 C：统一 `POST /api/v1/writing/stream` + mode 字段——单端点，需联合 DTO（判别联合） | 端点面（3 vs 1）；DTO 是否新增联合模型；前端消费方式 | **✅ 已确认（用户拍板：选项 C）**：正文已按拍板结果修订——统一端点 + `StreamWritingRequest` 判别联合（§2.2/§3.1），`StreamGenerateRequest` 等三包装模型继承 F3 DTO（§2.2）；估算 +0.5 人天；决策记录 D2（§12） |
| Q2 | **流式与格式校验重试的关系？** 选项 A：流式直通 + done 帧报告 format_valid，**不重试**——首 token ≤ 2s 达成、实现最简，客户端自行决定重发；选项 B：先完整生成校验通过后再流式回放——保证格式，但首 token 延迟 = 完整生成时间，违背逐 token 渲染目标；选项 C：直通 + 自动重试设置项（`stream_auto_retry` 默认 false）——重试时用户已看到第一遍输出，语义混乱 | 首 token ≤ 2s 验收；warnings 语义；设置项面 | **✅ 已确认（用户拍板：选项 A）**：v1.0 已按此设计，仅标记确认——正文无需改动（§5.4/§6.1/§7 E6/§10） |
| Q3 | **CLI 输出方式？** 选项 A：CLI 零变更——`inkflow write` 保持非流式，SSE 是 GUI/云端传输通道；选项 B：`inkflow write --stream` 逐 token 打印——新增 CLI 消费逻辑 + 测试面；选项 C：CLI 内部消费流式端点但输出不变——无意义（多一跳） | CLI 变更面；测试面（tests/cli/ 已列 ci.yml）；交互价值 | **✅ 已确认（用户拍板：修改——CLI 默认流式输出，非加 `--stream` 标志）**：正文已按拍板结果修订——`inkflow write` 三子命令默认逐 token 输出（§4.1，直接消费 service 流式方法，不经 HTTP），`--json` 静默收集保持信封兼容（§4.2），不提供 `--no-stream`（§10）；估算 +0.5-1 人天（总 3-4）；决策记录 D7（§12）；验收 M6/M7（§13） |

---

*本文档为 F23 功能规格（What），实施步骤（How）见后续 `specs/f23-sse-stream/plan.md`。所有里程碑验收以本节 M1-M8 为准。*
