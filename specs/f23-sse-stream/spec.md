# F23: SSE 流式输出 (sse_stream) — 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-02 | **依据**: PRD v2.1 §6.3 P1-12, Constitution P1-P6, ADR-012/015/018/019(v2)/021
> **所属阶段**: 0.3.0 里程碑（**提前**，原 0.5.0——GUI 写作流式渲染的依赖项，ADR-019 v2；估算 2-3 人天）
> **关联 Issues**: [#50](https://github.com/zhx-xi/InkFlow/issues/50)
> **依赖**: F3 ✅（WritingService 三原语 + DTO）；F5 ✅（**LLMClientProtocol.chat_stream 已实现**——`AsyncGenerator[StreamEvent]` 逐 token，基础设施层 LangChain astream 就绪）；F1 ✅（项目校验）；F2 ✅（章节校验）；F19（GUI 消费方，**反向依赖**——F23 端点先行，GUI 侧待 F19 落地后消费）
> **参考 ADR**: [ADR-001](../../adr/ADR-001.md) (模块化单体), [ADR-002](../../adr/ADR-002.md) (六边形分层), [ADR-012](../../adr/ADR-012.md) (错误处理), [ADR-015](../../adr/ADR-015.md) (LangChain 隔离), [ADR-018](../../adr/ADR-018.md) (测试分层), [ADR-019](../../adr/ADR-019.md) (版本里程碑 v2——F23 提前 0.3.0), [ADR-021](../../adr/ADR-021.md) (本地内核进程化——SSE 一条代码路径两用：GUI 与云端)
> **状态**: 提议中（待澄清问题 Q1-Q3 拍板后定稿）

---

## 1. 概述

为 F3 写作管道增加 **SSE（Server-Sent Events）流式输出**：`POST /api/v1/writing/{action}/stream` 端点逐 token 推送生成内容，前端（GUI / 云端 Web）实时渲染（PRD P1-12「逐 token 推送；前端实时渲染」）。流式端点与既有非流式端点**共享同一 WritingService 与同一请求 DTO**，只增加一条流式代码路径——**服务端零新增依赖**（FastAPI `StreamingResponse`），SSE 帧协议自定义 JSON（§6）。

**核心价值**: 长篇生成（≥2000 字）非流式端点需等待完整生成（数十秒）后才返回，GUI 无法展示中间过程；流式端点让用户**首 token ≤ 2s 看到输出**（ADR-019 0.3.0 验收标准），逐 token 渲染出"正在写作"的实时感，并支持**中途停止**（客户端断开 → 服务端生成器终止，不泄漏任务）。

**与 F9-F16 样板的关系（关键差异——本模块是「传输增强型」：不新建实体表、不新增算法，为既有 WritingService 增加流式通道）**:

```text
F3  写作:    WritingRequest ──LLM chat──▶ WritingResult（完整等待，格式重试 ≤3）
F23 流式:    WritingRequest ──LLM chat_stream──▶ SSE 帧流（逐 token，done 帧报告校验状态）
             复用: F3 三原语 DTO / service 校验 / prompt 构建 / FormatValidator
             新增: service 流式方法 + API StreamingResponse 端点 + SSE 帧协议
```

**关键事实（现状盘点，2026-08-02 实测）**:
- `LLMClientProtocol.chat_stream`（domain/ports/llm_client.py）**已存在**：`AsyncGenerator[StreamEvent]`，`StreamEvent{content, is_final, token_usage}`——F5 基础设施 `LangChainLLMClient.chat_stream` 已用 `chat_model.astream` 实现（langchain_client.py L99-137）
- `WritingService`（domain/services/writing_service.py）三原语 `generate_chapter` / `continue_writing` / `revise_content` 均走 `self._llm.chat`（非流式）+ `FormatValidator` 校验 + 格式修复重试 ≤3（`_generate_with_retry`）
- writing router（api/routers/writing.py）三个 POST 端点（/generate /continue /revise），错误映射 `_map_service_error`（LLMRequestError → 404 或 500）
- `httpx-sse>=0.4` 已在 backend/pyproject.toml 锁定（测试侧）；服务端**不新增 sse-starlette**（StreamingResponse 手写帧，零新增依赖——ADR-025 流程零触发）

**边界声明**:
- F23 **不新建实体表、不落库**：流式输出是瞬态传输，`done` 帧携带完整写作结果（内容由调用方经 F2 保存，同 F3 §1 边界）
- F23 **不改写 F3 非流式路径**：`_generate_with_retry` 原样保留，流式走独立方法（§5）
- F23 **服务端不做格式修复重试**（Q2 拍板）：流式直通 LLM 输出，`done` 帧报告 `format_valid` 校验状态；自动重试可选（设置项默认关闭，§5.4）——重试会打断用户已看到的输出流，且违背首 token ≤ 2s 目标
- F23 **不含前端**：GUI 流式渲染属 F19（Electron 壳）与云端 Web（2.0.0）；本 spec 只定义后端 SSE 契约与冒烟验证（§13 M7）
- F23 **CLI 不新增流式输出**（Q3 拍板）：`inkflow write` 保持非流式；SSE 是 GUI/云端的传输通道，CLI 逐 token 打印无交互价值

### 1.1 依赖方向

```
✅ api/routers/writing.py → domain/services/writing_service.py → domain/ports/llm_client.py (Protocol.chat_stream)
✅ api/routers/writing.py → fastapi.StreamingResponse（传输层框架，仅表现层）
❌ domain/ 不出现 StreamingResponse / sse 相关 import（ADR-002/015）
```

---

## 2. 数据模型

F23 不新建业务实体表（YAGNI——流式事件是瞬态传输模型）。领域层新增**一个纯 dataclass 事件模型** `WritingStreamEvent`（§2.1），承载流式管道的全部观测信息；SSE 帧序列化在 API 层完成（`model_dump` 式手写 JSON，§6）。**复用** F3 全部既有 DTO（`WritingRequest` / `ContinueWritingRequest` / `RevisionRequest`，domain/models/writing.py——零变更）与 `StreamEvent` / `TokenUsage`（domain/ports/llm_client.py——零变更）。

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

---

## 3. API 契约

### 3.1 流式端点（新增 3 个，mirror F3 非流式端点）

| 方法 | 路径 | 请求体 | 响应 |
|------|------|--------|------|
| POST | `/api/v1/writing/generate/stream` | `WritingRequest`（同 F3 §2.2） | `text/event-stream`（SSE 帧流，§6） |
| POST | `/api/v1/writing/continue/stream` | `ContinueWritingRequest`（同 F3 §2.3） | `text/event-stream` |
| POST | `/api/v1/writing/revise/stream` | `RevisionRequest`（同 F3 §2.4） | `text/event-stream` |

> **端点形态决策（Q1 拍板）**: mirror 三端点 + POST——①与既有 F3 端点一一对应，客户端心智简单（"要流式就在路径加 /stream"）；②POST 支持长请求体（outline/context 可达 5000/20000 字符，GET+query 受 URL 限制）；③前端消费用 fetch+ReadableStream（EventSource 不支持 POST 且无法携带 header/token——ADR-021 本地 token 校验要求；云端 JWT 走 header 同理）。SSE 帧格式保持标准兼容（`data:` 行 + 空行），若未来需要 EventSource 兼容变体可加 GET 端点复用同一帧协议（§12 决策记录）。

**响应头**（StreamingResponse 必须显式设置）:

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no        # 云端部署防代理缓冲（ADR-021 一条代码路径两用）
```

> **OpenAPI 注**: SSE 流响应无法用标准 JSON schema 描述——三个流式端点的 `responses` 只声明 200 + `text/event-stream` media type（FastAPI `StreamingResponse` 天然如此），帧格式以本文档 §6 为准。

### 3.2 错误映射（流开始前——HTTP 状态码）

流式端点的**校验阶段错误在流开始前抛出**，走既有 `_map_service_error`（writing.py L30-43，**零变更**）：

| 错误 | 状态码 | 说明 |
|------|--------|------|
| 项目不存在 / 章节不存在（LLMRequestError message ∈ `_NOT_FOUND_MESSAGES`） | 404 | 流未开始，正常 HTTP 响应 |
| 请求体校验失败（Pydantic，如 outline 空 / 字数越界 / max_words < min_words） | 422 | FastAPI 自动 |
| 无效 UUID | 422 | FastAPI 自动 |
| 其他 LLMRequestError（API key 缺失等） | 500 | `_map_service_error` 既有逻辑 |

**流开始后（已发送首帧）的错误走 SSE error 帧**（§7 E3）——HTTP 状态码无法在流中途变更。

---

## 4. CLI 命令签名

**无变更**（Q3 拍板）。`inkflow write` 保持非流式输出（F7 CLI spec 既有行为）；SSE 流式端点面向 GUI/云端消费方，CLI 逐 token 打印无交互价值。冒烟验证用 `curl --no-buffer`（§13 M7）。

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
> **设计要点 — 格式校验**: `revise_content` 无格式校验（F3 L119-160 直通 chat），`stream_revise` 同样不做 FormatValidator（done 帧 format_valid 恒 None → API 层序列化省略该字段，§6.2）。`stream_generate`/`stream_continue` 在结束时校验（§5.4）。

### 5.2 API 端点实现（StreamingResponse）

```python
# api/routers/writing.py — MODIFY（新增）

@router.post("/generate/stream")
async def generate_chapter_stream(
    data: WritingRequest,
    request: Request,
    svc: WritingService = Depends(get_writing_service),
) -> StreamingResponse:
    """流式生成章节 — SSE 逐 token 推送（帧协议见 spec §6）."""
    return _stream_response(request, svc.stream_generate(data))
```

```python
# 内部辅助 — 三端点共用（§5.3 断开处理封装）

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

> **注意**: `is_disconnected()` 检查在每次事件循环中执行；StreamingResponse 自身在客户端断开时会抛 `ClientDisconnect`（starlette 内部处理），双重保障。LLMRequestError 在生成器内部也可能被 `chat_stream` 抛出（langchain_client.py L129-134）——`_event_generator` 捕获转 error 帧；`_map_service_error` 的 500 分支**不适用**于流中途（已发帧），仅流开始前的校验异常走 HTTP 状态码（§3.2）。

### 5.3 客户端断开语义

- **服务端**: 每帧前 `request.is_disconnected()` → 真则 `events.aclose()` 终止 LLM 流（LangChain astream 的 async generator 被 close 会中止底层请求），**不泄漏后台任务**
- **客户端**: 断开后服务端不再推送；客户端重连需重新发起请求（**从头重拉**，MVP 不做断点续传——Q2 范围声明，§10）
- **测试**: httpx-sse `aconnect_sse` 上下文退出即模拟客户端断开（§9）

### 5.4 格式校验与自动重试（Q2 拍板落点）

**流式直通 + done 帧报告校验状态**（默认）：

- `stream_generate`/`stream_continue` 结束时对完整内容做 `FormatValidator.validate(content, min_words)` → `done` 帧携带 `format_valid` / `warnings`
- 格式无效时**不自动重试**（默认）——用户已看到完整输出流，重试需清空重来；warnings 提示"格式校验未通过"，客户端可让用户决定是否重试（再次发起流式请求）
- **自动重试可选（设置项 `stream_auto_retry`，默认 `false`）**：开启时格式无效自动重新生成（最多 1 次重试，重试期间不推送新 delta——客户端看到第一遍完整输出后收到第二个完整流？**否决**——见 Q2 拍板注：自动重试在流式下语义混乱，v1.0 不提供，§10 声明远期）

> **Q2 拍板后定稿**: v1.0 按「直通 + done 帧报告」设计（§5.4 无自动重试小节）；若拍板选项 C（自动重试设置项），本节追加设置项落点（project config `extra["stream_auto_retry"]` + 请求覆盖，镜像 F16 style_llm_analysis 三级判定模式）。

---

## 6. SSE 帧协议

### 6.1 帧序列（客户端视角）

```text
POST /api/v1/writing/generate/stream
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
        payload["token_usage"] = ev.token_usage.model_dump()   # TokenUsage 是 dataclass → dataclasses.asdict
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

> **字段省略规则**: `None`/空值字段不进入 JSON（保持帧最小化）；`ensure_ascii=False` 保证中文原文可读（调试友好）。`TokenUsage` 为 dataclass（llm_client.py L49-55）——用 `dataclasses.asdict` 序列化。

### 6.3 标准 SSE 兼容性

- 帧 = `data:` 行 + `\n\n` 空行（标准 SSE 格式，任何 SSE 客户端可解析）
- **不发送** `event:` 类型行（统一 message 事件）；**不发送** `id:` 行（MVP 无断点续传，§10）
- 心跳：MVP 不发送注释心跳行（`chat_stream` 流活跃期间无空闲；LLM 长停顿场景远期加，§10）

---

## 7. 边界情况与错误处理

| # | 场景 | 处理 | 帧/状态码 |
|---|------|------|-----------|
| E1 | 项目不存在 / 章节不存在 / 跨项目章节 | 流开始前 `_map_service_error` | HTTP 404 |
| E2 | 请求体校验失败（outline 空、字数越界、UUID 无效等） | Pydantic 自动 | HTTP 422 |
| E3 | 流中 LLM 调用失败（网络/超时/Provider 错误） | `_event_generator` 捕获 → error 帧 → 流结束 | `data: {"done": true, "error": "LLM 调用失败，请稍后重试"}` |
| E4 | 客户端断开（关闭连接 / 取消请求） | `is_disconnected()` → `events.aclose()` 终止生成器 | 连接关闭，服务端无泄漏任务 |
| E5 | LLM 返回空流（0 个 delta） | 直接发 done 帧（format_valid=false + warning「生成内容为空」） | 正常结束 |
| E6 | 格式校验失败（generate/continue） | done 帧 `format_valid=false` + warnings（不重试，§5.4） | 正常结束 |
| E7 | `revise` 目标范围未定位 | warnings 携带「未能定位目标范围…已全文修订」（镜像非流式 L127-128） | 正常结束 |
| E8 | token_usage 不可用 | done 帧省略该字段 | 正常结束 |

---

## 8. 文件结构

遵循 ADR-007v2 包结构。新增/修改文件（**对照主仓现行树逐文件核对**；F23 除 writing_service.py 内 prompt 组装抽取（同文件 REFACTOR）外**零跨模块 MODIFY**）：

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   └── writing.py         ← MODIFY: 新增 WritingStreamEvent（§2.1）
│   └── services/
│       └── writing_service.py ← MODIFY: 新增 stream_generate / stream_continue /
│                                      stream_revise（§5.1）+ _build_generate_messages /
│                                      _build_continue_messages 抽取（§5.1 注）
├── api/
│   └── routers/
│       └── writing.py         ← MODIFY: 新增 3 个 /stream 端点 + _event_generator /
│                                      _encode_sse 辅助（§5.2/§6.2）；app.py 零变更
│                                    （writing.router 已注册）
```

```text
backend/tests/unit/
├── test_writing_models.py     ← MODIFY: WritingStreamEvent 字段/默认值/序列化断言（§9 M1）
├── test_writing_service.py    ← MODIFY: 流式方法测试（§9 M2/M3——Mock chat_stream）
tests/api/
└── test_writing_api.py        ← MODIFY: 流式端点 SSE 测试（httpx-sse，§9 M4/M5）
```

**零新增运行时依赖**（服务端 StreamingResponse；测试侧 httpx-sse 已锁定）。**CLI 零变更**（Q3）。**ci.yml 零变更**（tests/api/test_writing_api.py 与 backend/tests/unit/ 均已覆盖——`integration-api-backend` job 是否显式列出 test_writing_api.py 需核对，若未列出则追加，Issue #59 教训）。

---

## 9. 测试策略

### M1 模型测试（test_writing_models.py MODIFY）

- `WritingStreamEvent` 默认值（delta="" / done=False / 其余 None）
- done 帧构造：format_valid/warnings/word_count/model/token_usage 赋值
- error 帧构造：error 字段 + done=True
- **帧编码测试**（`_encode_sse` 放 API 层还是测试内联？——API 层函数，M4 覆盖；模型测试只测字段语义）

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

async def test_generate_stream_deltas(override_writing_service):
    # Mock WritingService.stream_generate → 预置 WritingStreamEvent 序列（2 delta + done）
    async with _client() as client:
        async with aconnect_sse(client, "POST", "/api/v1/writing/generate/stream", json=body) as sse:
            events = [ev async for ev in sse.aiter_sse()]
    # 断言: 2 个 delta 帧（data.delta 拼接 == 全文）+ 1 个 done 帧（done=true, format_valid=true）
    # 断言: 响应头 Content-Type == text/event-stream
```

- 三端点各 1 个成功用例（/generate/stream、/continue/stream、/revise/stream）
- done 帧字段断言（format_valid/warnings/word_count/model/token_usage 完整透传）

### M5 API 流式端点·错误路径

- 404（Mock service raise LLMRequestError("项目不存在")）→ 普通 HTTP 404（非 SSE）
- 422（outline 空 / max_words < min_words）→ 普通 HTTP 422
- 流中 LLM 错误（Mock chat_stream raise LLMRequestError）→ SSE error 帧（done=true + error 文案）+ 流结束
- 客户端断开（`aconnect_sse` 上下文提前退出）→ service 生成器被 close（Mock 断言 `aclose` 被调用 / is_disconnected 路径）

### M6 全量回归 + 覆盖率 + lint/type

- `pytest -v` 全绿（backend/tests/unit/ + tests/api/ 分别跑——单元与集成分命令，F15 教训）
- F23 新增代码行覆盖 ≥ 80%（writing_service.py / writing.py 流式部分）；全仓 ≥ 60%
- ruff + mypy 通过（CI 门禁 ADR-017）；domain/ 零框架 import（ADR-002/015——writing_service.py 不出现 StreamingResponse/sse）

### M7 冒烟验证（手工，0.3.0 验收标准）

`inkflow serve` 启动 → `curl -N -X POST http://127.0.0.1:8000/api/v1/writing/generate/stream -H "Content-Type: application/json" -d '{...}'`（PowerShell 下 `curl.exe`）→ 观察逐 token 输出 + 首 token ≤ 2s（ADR-019 验收）+ done 帧结束。

---

## 10. 不在范围内

| 项 | 原因/归属 |
|----|----------|
| GUI 流式渲染 / 前端 EventSource 消费 | F19（Electron 壳）+ 云端 Web（2.0.0）；F23 只交付后端契约 |
| 断点续传（`id:` 帧 + Last-Event-ID 重连补发） | MVP 从头重拉（Q2 范围声明）；续传复杂度高收益低 |
| SSE 心跳注释帧 | LLM 流活跃期间无空闲；长停顿场景远期加 |
| 流式自动重试（格式无效自动重新生成） | v1.0 直通 + done 帧报告（§5.4）；重试语义与流式渲染冲突 |
| 多客户端广播 / 共享流 | 无此需求（每请求独立流）；云端远期再评估 |
| CLI 流式输出 | Q3 拍板：无交互价值（GUI/云端是流式消费方） |
| GET + EventSource 兼容端点 | 前端 fetch+ReadableStream 已覆盖（Q1 拍板）；EventSource 变体远期按需加 |
| Token 鉴权 / 本地安全基线 | F19（ADR-021：`inkflow serve` 强化版 --port 0 + token + WAL）；F23 端点自身无鉴权，由 serve 层统一校验 |

---

## 11. 依赖关系

| 依赖 | 状态 | 说明 |
|------|------|------|
| F3 WritingService / DTO / FormatValidator | ✅ 已实现 | 流式方法复用其校验与 prompt 组装（§5.1） |
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
| D2 | 端点 mirror F3 三端点（`/generate/stream` 等），非统一 `/stream` + mode 字段 | 与既有 API 一一对应、客户端心智简单；DTO 复用零变更；mode 字段会引入联合 DTO 复杂度 | 统一端点 + mode（DTO 联合/判别）；`/writing/{chapter_id}/stream`（chapter_id 入路径——与 F3 body 风格不一致） |
| D3 | 流式直通 LLM 输出，格式校验只在 done 帧报告，**不自动重试** | 重试打断已见输出流；首 token ≤ 2s 目标；客户端可自行决定重发（GUI 按钮） | 先完整生成校验再回放（首 token 延迟 = 完整生成时间，违背流式意义）；自动重试设置项（语义混乱，v1.0 否决） |
| D4 | `WritingStreamEvent` dataclass + API 层 `_encode_sse` 手写 JSON | 事件是内部传输载体不进 OpenAPI；与 F5 StreamEvent dataclass 一致；字段省略规则保持帧最小化 | Pydantic 模型（过度设计——无校验需求） |
| D5 | 客户端断开用 `is_disconnected()` + `events.aclose()` 双保障 | 不泄漏后台 LLM 任务（服务端资源）；StreamingResponse 内部 ClientDisconnect 兜底 | 仅依赖 starlette 自动处理（无法主动终止 service 生成器） |
| D6 | 流中错误用 SSE error 帧（done + error），非 HTTP 状态码 | HTTP 状态码在流中途不可变更；error 帧让客户端有统一结束语义（恰好 1 个 done 帧不变量） | 直接断连（客户端无法区分错误与正常结束）；HTTP 500 后断连（非标准） |

---

## 13. 验收标准

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| M1 | WritingStreamEvent 模型（字段/默认值/done 帧/error 帧） | `pytest tests/unit/test_writing_models.py -v` 全绿（流式相关用例） |
| M2 | service 流式·generate（校验前置 / delta 透传 / done 帧完整 / 格式无效不重试 / 空流 / prompt 组装回归） | `pytest tests/unit/test_writing_service.py -v` 全绿（流式用例） |
| M3 | service 流式·continue/revise（tail 截断 / 无 FormatValidator / target_range warning） | `pytest tests/unit/test_writing_service.py -v` 全绿（流式用例） |
| M4 | API 三端点成功路径（httpx-sse delta 序列 + done 帧 + Content-Type） | `pytest tests/api/test_writing_api.py -v` 全绿（流式用例） |
| M5 | API 错误路径（404/422 流前 HTTP / 流中 error 帧 / 客户端断开终止） | `pytest tests/api/test_writing_api.py -v` 全绿（流式用例） |
| M6 | 全量回归 + 覆盖率 + lint/type | `pytest -v` 全绿（单元+集成分命令）；流式新增代码行覆盖 ≥ 80%、全仓 ≥ 60%；ruff + mypy 通过；domain/ 零框架 import |
| M7 | 冒烟闭环：`inkflow serve` + `curl.exe -N` 逐 token 输出 + 首 token ≤ 2s + done 帧 | 手工验证（ADR-019 0.3.0 验收标准）；F3 非流式端点回归不受影响 |

> **验收标准 ↔ Issue #50 映射**: ①「逐 token 推送」→ M2/M4/M7（chat_stream 透传 + httpx-sse delta 序列 + curl 实测）；②「前端实时渲染」→ 后端契约就绪（M4/M7），渲染属 F19/#79；③「SSE 端点同时供云端 Web 消费（2.0.0）」→ D1/D6 + 响应头 X-Accel-Buffering（一条代码路径两用，ADR-021）；④「首 token ≤ 2s」→ M7。

---

## 待澄清问题（≤ 3 个，待拍板）

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| Q1 | **端点形态？** 选项 A：mirror 三端点 + POST（`/generate/stream` 等，复用 F3 DTO，本 spec 设计）——与既有 API 一一对应、支持长 body、前端 fetch+ReadableStream；选项 B：GET + EventSource 兼容端点——浏览器原生自动重连，但 GET 无法携带长 body（outline/context ≤ 20000 字符超 URL 限制）且 token 进 URL（ADR-021 本地 token 校验冲突）；选项 C：统一 `POST /api/v1/writing/stream` + mode 字段——单端点，但需联合 DTO（WritingRequest/ContinueWritingRequest/RevisionRequest 判别联合），复杂度转移 | 端点面（3 vs 1）；DTO 是否新增联合模型；前端消费方式 | **✅ 推荐选项 A**（mirror 三端点 + POST）：零新 DTO、错误映射零变更、与既有 API 风格一致；SSE 帧协议保持标准兼容，远期可按需加 GET 变体 |
| Q2 | **流式与格式校验重试的关系？** 选项 A：流式直通 + done 帧报告 format_valid，**不重试**（本 spec 设计）——首 token ≤ 2s 达成、实现最简，客户端自行决定重发；选项 B：先完整生成校验通过后再流式回放——保证格式，但首 token 延迟 = 完整生成时间，**违背逐 token 渲染目标**；选项 C：直通 + 自动重试设置项（`stream_auto_retry` 默认 false，格式无效自动重新生成 1 次）——重试时用户已看到第一遍完整输出，语义混乱且增加设置项面 | 首 token ≤ 2s 验收；warnings 语义；设置项面 | **✅ 推荐选项 A**（直通 + done 帧报告）：格式校验的修复重试价值在流式场景下降（用户实时可见输出，warnings 已足够）；重试权交给客户端（GUI 按钮/CLI 重发） |
| Q3 | **CLI 是否支持流式输出？** 选项 A：CLI 零变更（本 spec 设计）——`inkflow write` 保持非流式，SSE 是 GUI/云端传输通道；选项 B：`inkflow write --stream` 逐 token 打印——终端用户可见实时输出，但需新增 CLI 流式消费逻辑（httpx-sse 或 fetch），且无 GUI 渲染价值；选项 C：CLI 内部消费流式端点但输出不变——无意义（多一跳） | CLI 变更面；测试面（tests/cli/ + ci.yml 显式列出）；交互价值 | **✅ 推荐选项 A**（CLI 零变更）：流式价值在 GUI 渲染（F19）；CLI 冒烟验证用 curl（M7）足够 |
