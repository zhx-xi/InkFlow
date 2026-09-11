# F23: SSE 流式输出 (sse_stream) — 功能规格
> **端**: cross

> **Spec 版本**: 1.4 | **日期**: 2026-08-02（v1.2 增量 / v1.3 实测修订 / v1.4 A3 实测修订 2026-09-10）| **依据**: PRD v2.1 §6.3 P1-12, Constitution P1-P6, ADR-012/015/018/019(v2)/021、**ADR-053（数据面变更统一推送）**
> **Spec 变更**: v1.1 — 用户拍板 Q1=选项 C（统一端点 `POST /api/v1/writing/stream` + mode 判别联合 DTO）/ Q2=选项 A（流式直通 + done 帧报告，不自动重试）/ Q3=修改（CLI **默认**流式输出，消费 service 流式方法——非加 `--stream` 标志）。**v1.2（2026-09-10，issue #992 设计单）— 新增 §15「数据面变更统一推送」（ADR-053 实现规范：事件信封 `DataChangeEvent` / `EventBus` / `GET /api/v1/events/stream` 订阅端点 / 失效语义矩阵 / #973-#989 ad-hoc 重拉收编 / 排期拆解）；§1-§14 内容不变。** **v1.3（2026-09-10，A1/A2 实施期实测修订）— ① §15.5.1 全局域示例帧去掉 `"project_id":null`（与同节不变量 3「省略该键」自相矛盾，实测修正）；② §15.2.2 补队列容量 `MAX_QUEUE_SIZE=100` + `subscribe()` 返回标注收窄为 `AsyncGenerator` + `source` ContextVar 位置与接线约束；③ §15.3.3 补 domain→infra 局部 import 说明；④ §15.13 修正「A1 ∥ A2 可并行」为「可并行开发，**A1 必须先合并**」，并补**两道契约门禁的完整清单**（快照漂移 / 前端类型漂移 / 前端调用面）+ 推论「改契约的 PR 必须自带两个同步产物（快照 + `openapi.d.ts`）」；⑤ 排期表补 A1 交付面含快照刷新 **+ `openapi.d.ts` 重生**（#1091 首轮 CI 因漏重生 d.ts 而 `lint-frontend` 红，实测修正）。** **v1.4（2026-09-10，A3 实施期实测修订）— ① §15.3.2 修正 `delete_character` 误判：实测为**薄透传**（`repo.hard_delete`，未加载实体），原 spec 声称「先取实体触发 map_cleanup」为假；补批次 A/B 域「薄透传」实测清单（`delete_character`/`delete_group`/`delete_pin`/`delete_outline`/`delete_point`/`delete_arc` → `None`+warning；`update_pin` 无 project_id 字段；**反例** `delete_relation` 反而可得）；② 明确「禁止为发声事件新增查询」铁律。**
> **所属阶段**: 0.3.0 里程碑（**提前**，原 0.5.0——GUI 写作流式渲染的依赖项，ADR-019 v2；估算 **3-4 人天**（Q1=C 联合 DTO +0.5、Q3 CLI 默认流式 +0.5-1；v1.0 的 2-3 已含基础））
> **关联 Issues**: [#50](https://github.com/zhx-xi/InkFlow/issues/50)
> **依赖**: F3 ✅（WritingService 三原语 + DTO）；F5 ✅（**LLMClientProtocol.chat_stream 已实现**——`AsyncGenerator[StreamEvent]` 逐 token，基础设施层 LangChain astream 就绪）；F1 ✅（项目校验）；F2 ✅（章节校验）；F19（GUI 消费方，**反向依赖**——F23 端点先行，GUI 侧待 F19 落地后消费）
> **参考 ADR**: [ADR-001](../../adr/architecture/ADR-001.md) (模块化单体), [ADR-002](../../adr/architecture/ADR-002.md) (六边形分层), [ADR-012](../../adr/architecture/ADR-012.md) (错误处理), [ADR-015](../../adr/llm/ADR-015.md) (LangChain 隔离), [ADR-018](../../adr/test-ci/ADR-018.md) (测试分层), [ADR-019](../../adr/packaging/ADR-019.md) (版本里程碑 v2——F23 提前 0.3.0), [ADR-021](../../adr/kernel/ADR-021.md) (本地内核进程化——SSE 一条代码路径两用：GUI 与云端)
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

*本文档为 F23 功能规格（What），实施步骤（How）见后续 `specs/f23-sse/plan.md`。所有里程碑验收以本节 M1-M8 为准。*
## 14. 动作确认

> 每个端点/命令的完整状态流表（基于 §3 API + §4 CLI + §6 SSE 帧协议 + §7 边界事实，不重复、不新增行为）。SSE 帧序列与流式错误处理为本节重点（§14.2）。

### 14.1 端点状态流

| 端点 | 前置条件 | 动作/状态转换 | 成功 | 失败 | 边界 |
|------|---------|--------------|------|------|------|
| POST /api/v1/writing/stream | mode 显式必填（缺失/非法 → 422）；项目/章节存在；请求体字段校验（outline 空 / 字数越界 / max_words < min_words → 422）；无效 UUID → 422 | mode 判别分发（generate/continue/revise）→ service 流式方法（校验 → prompt 构建 → chat_stream 逐事件 yield）→ _event_generator 逐帧编码 → StreamingResponse | 200 text/event-stream + Cache-Control: no-cache + Connection: keep-alive + X-Accel-Buffering: no；帧序列 = 0..N delta 帧 + 恰好 1 个 done 帧（§6.1 不变量）；首 token ≤ 2s | 流开始前：404（项目/章节不存在，LLMRequestError 属 _NOT_FOUND_MESSAGES）、422（Pydantic 校验 / mode 缺失非法）、500（其他 LLMRequestError，API key 缺失等）——均为普通 HTTP 响应非 SSE；流开始后：error 帧（见 §14.2） | 客户端断开 → is_disconnected + events.aclose() 终止生成器不泄漏（E4）；空流 → done 帧 format_valid=false +「生成内容为空」（E5）；格式无效 → done 帧 format_valid=false + warnings 不重试（E6）；revise done 帧无 format_valid（E7/§5.1 注）；token_usage 不可用 → done 帧省略该字段（E8） |

### 14.2 SSE 帧序列与流式错误处理（重点）

| 场景 | 帧序列 / 行为 | 依据 |
|------|--------------|------|
| 正常流 | 0..N 个 delta 帧（data: {"delta": "...", "done": false}，全部 delta 拼接 = 完整内容）→ 1 个 done 帧（data: {"done": true, "format_valid": ..., "word_count": ..., "model": ..., "token_usage": {...}}）→ 连接关闭 | §6.1 不变量 1-3 |
| 流中 LLM 失败（网络/超时/Provider） | 捕获 LLMRequestError → 发 error 帧 data: {"done": true, "error": "LLM 调用失败，请稍后重试"} → 流结束（结果字段省略） | §7 E3 + §6.1 不变量 4 |
| 客户端断开（关连接/取消请求/Ctrl+C） | 每帧前 is_disconnected() → 真则 events.aclose() 终止 LLM 流（LangChain astream 中止底层请求），服务端无泄漏任务；断开后客户端重连 = 从头重拉（MVP 无断点续传） | §5.3 + §7 E4 |
| 格式校验失败（generate/continue） | done 帧 format_valid=false + warnings；不自动重试（重试打断已见输出流） | §5.4 + §7 E6 |
| revise 目标范围未定位 | done 帧 warnings 携带「未能定位目标范围…已全文修订」；无 format_valid | §7 E7 |
| 空流（0 个 delta） | done 帧 format_valid=false + warning「生成内容为空」 | §7 E5 |

### 14.3 CLI 命令状态流

| 命令 | 前置 | 动作 | 成功 | 失败 | 边界 |
|------|------|------|------|------|------|
| inkflow write next / continue / revise（默认流式） | 项目/章节存在（service 校验，流开始前抛出）；DTO 字段校验 | 直接消费 service 流式方法（不经 HTTP），逐 token 打印 ev.delta（typer.echo nl=False 连续拼接）→ 流结束摘要行 | 退出 0；摘要「✅/⚠️ 章节生成成功: {word_count} 字 (重试 0 次, {model})」/「✅ 续写完成」/「✅ 修订完成」；--json 静默收集 → 信封 data 含 content/word_count/format_valid/retry_count/model/token_usage/warnings | 项目/章节不存在 → 退出 1 NOT_FOUND；流中 LLM 错误 → 退出 1 LLM_ERROR；Ctrl+C → 退出码 130（KeyboardInterrupt，aclose 由 async generator 生命周期保证） | 无 --no-stream 回退（Q3 拍板）；--count > 1 逐章循环（仅 next，章间空行）；--count + --json → 数组信封 |

### 14.4 验收锚点（写入 §14）

- A1：流开始前项目不存在 → 普通 HTTP 404（非 SSE error 帧）
- A2：mode 缺失/非法 → 422（判别字段必填，FastAPI 自动）
- A3：帧序列不变量：delta 帧均带 done:false；恰好 1 个 done 帧收尾后连接关闭
- A4：流中 LLM 失败 → error 帧「LLM 调用失败，请稍后重试」后流结束（客户端可区分错误与正常结束）
- A5：客户端断开 → service 生成器被 aclose（Mock 断言 aclose 被调用，无后台泄漏）
- A6：空流 → done 帧 format_valid=false +「生成内容为空」warning
- A7：格式无效 → done 帧 format_valid=false 且 chat_stream 仅调用 1 次（不重试）
- A8：revise done 帧无 format_valid 字段（字段省略规则 §6.2）

### 14.5 漂移标注

- 无关键漂移：实现 `api/routers/writing.py` 的 _encode_sse 字段省略规则、error 帧文案「LLM 调用失败，请稍后重试」、is_disconnected + aclose 断开处理与 spec §6.2/§7 E3/E4 逐行一致；service 层 stream_generate/stream_continue/stream_revise 的 done 帧语义（format_valid /「生成内容为空」warning / revise 无校验）与 §5.1/§7 E5-E8 一致。实现含「预消费探针」模式（先 await 首事件再返回 StreamingResponse，writing.py L220-235）——落实 spec §3.2「流开始前校验异常 → HTTP 状态码」的惰性生成器实现细节，属实现补充非漂移。

---

## 15. 数据面变更统一推送（#992 / ADR-053 实现规范）

> **章节定位（2026-09-10 #992 设计单新增）**：本章是 **ADR-053「数据面变更统一推送」的实现规范**。ADR-053 已于 2026-09-07 merge（PR #1012）确立核心决策（D1 service 层 publish / D2 推信号不推实体 / D3 双层去重 / D4 轮询降级常开），但 **§15.1 实测确认其代码实现为零**——后端全树 `event_bus|EventBus|publish|subscribe` 零命中。本章补齐**可实现的契约级规范**：事件信封 schema、EventBus/SSE 端点、GUI 订阅与失效语义矩阵、#973/#989 ad-hoc 重拉收编、排期拆解。
>
> **本章为何挂 F23 而不新起 F 号**：F23 已定义 SSE 传输层（§3 端点 / §6 帧协议 / §5.3 断开语义 / §14.2 帧序列契约），本机制**复用同一条 SSE 通道与帧编码模式**（ADR-053 D1「复用 F23/内核 SSE 通道」），属同一传输能力的第二个消费面，新起 F 号会造成同一 SSE 基建的两处契约分叉。**编号裁决**：沿用「已编号节最大号 +1」→ F23 现最大 §14 → 本章 = **§15**。
>
> **与 F23 §3-§6 的边界（关键，勿混）**：F23 §3-§6 是**写作流式端点**（`POST /api/v1/writing/stream`，**请求-响应式单向流**：一个请求对应一条流，流随生成结束关闭）；本章是**事件广播端点**（`GET /api/v1/events/stream`，**长驻订阅流**：GUI 挂载即订阅、跨请求持续接收其他客户端的写入）。两者共享帧编码风格（`data: <json>\n\n`）但**帧 schema 不同**（§15.5 vs §6.2），**生命周期不同**（§15.5.3 vs §5.3）。

### 15.1 问题陈述与根因

**问题不是 bug，是结构性缺机制**：GUI 各列表/数据面普遍是「挂载时一次性快照」——任何**外部或同进程其他界面**改了数据，已挂载的 GUI 不感知。

InkFlow 的 CLI / HTTP / MCP / chat-agent 工具面与 GUI 都是**同一内核进程的一等客户端**（ADR-021/030），因此**任何两处并发写同一资源**都触发快照陈旧。

**0.13.0-rc4 三次爆点（全部 ad-hoc 补丁收敛，未治根因）**：

| 爆点 | 症状 | ad-hoc 修法（已 merge） | 残留 |
|------|------|----------------------|------|
| **#973** maps 快照 | 外部（CLI/HTTP/MCP/agent）建图，GUI 停留设定库永远不可见（rc4 实测误导用户「地图功能坏了」） | `library.tsx` maps effect 依赖补入 `reloadKey/workbenchActive`（进/退工作台重拉，PR #982） | 只覆盖 maps 一个面；「进页面重拉」不是失效广播 |
| **#989** 模板 used_by 快照 | 外部挂引用后点删除，风险确认读旧 `used_by=[]` → 漏列引用项目 = 可能静默断链删被引用模板；E2E 时红时绿 | `settings.tsx` **两个入口**（删除 onClick L506 / 编辑保存 L642）前 `await loadTemplates()` 重拉（PR #990） | 每加一个确认入口手工补一次，第三次爆点可预期 |
| **#987** config 只写不读（开放中） | 重启后 `llm_default_model` 等键丢失 | （#758 治理轨） | 同「配置/数据面不一致」族 |

**根因**：**写路径没有统一的「变更信号」出口，读取面没有统一的「失效订阅」入口**。

**下一个候选面（按同构可预判）**：写作页草稿树、角色卡列表、伏笔/时间线列表、Agent 列表、知识图谱关系列表。

**边界声明（本章不做什么）**：
- **不做前端状态管理重写**（Zustand 保持，非目标）
- **不做 optimistic update 体系**（非目标）——本机制是**失效信号**，不是本地先行写入
- **不承诺多窗口实时同步**（2.0.0 前单机内可见性优先，非目标）
- **不做推送内容合并/冲突解决**（无 CRDT；服务端权威 + 客户端失效，§15.8）
- **不做断线期间补发**（事件是尽力而为的失效信号，§15.5 E4）

### 15.2 领域模型：事件信封与事件总线

#### 15.2.1 `DataChangeEvent`（领域事件，新增）

领域层新增**一个纯 dataclass**（无框架依赖，ADR-002/015；镜像 §2.1 `WritingStreamEvent` 的「dataclass 而非 Pydantic」决策——事件是内部传输载体，不进 OpenAPI）：

```python
# domain/models/data_change_event.py — CREATE

@dataclass(frozen=True)
class DataChangeEvent:
    """数据面变更事件 — service 层写路径末尾发布，SSE 层序列化为帧（§15.5）."""

    domain: str
    """变更域（= 资源类型）：project|chapter|volume|character|character_group|
    character_relation|outline|plot_point|story_arc|world_setting|world_category|
    map|map_pin|foreshadowing|timeline_event|memory|agent_template|agent|
    knowledge_relation|session|skill|settings|provider_config|draft."""

    op: str
    """操作类型：create|update|delete."""

    resource_id: str
    """被变更资源的标识（UUID 字符串或整型主键字符串）."""

    project_id: str | None = None
    """所属项目 UUID 字符串；**全局域为 None**（§15.2.3 作用域分类）."""

    source: str = "unknown"
    """发起方：gui|cli|mcp|agent|scheduler|unknown（self-originated 过滤用，ADR-053 D3）."""

    entity_id: str | None = None
    """向后兼容别名（= resource_id）；ADR-053 原信封字段名为 entity_id（§15.2.4）."""

    traceparent: str | None = None
    """W3C traceparent（复用 #931 上下文，§15.7）；无上下文时为 None."""

    occurred_at: str | None = None
    """事件产生时刻（ISO-8601 UTC，遵循 ADR-055）；调试/排序用."""
```

> **字段命名裁决（ADR-053 原信封用 `entity_id`，issue #992 用 `resource_id`）**：两者语义相同。**本章以 `resource_id` 为规范字段名**（对齐 issue #992 提案），同时保留 `entity_id` 作为**兼容别名**（ADR-053 已把 `entity_id` 写进文档，下游若按 ADR 实现需平滑）。**实现裁决：序列化时同时输出两键**（值相同）——避免「照 ADR 实现」与「照 issue 实现」的两拨人各写一半而互不兼容；冗余一个键成本可忽略，后续可弃用其一（§15.9 批次 B 决策点）。

#### 15.2.2 `EventBus`（进程内总线，新增）

```python
# infrastructure/events/event_bus.py — CREATE
# （放 infrastructure/ 而非 domain/：总线是进程内传输实现，domain 只定义事件模型）

class EventBus:
    """进程内发布/订阅总线（ADR-053 D1）— asyncio.Queue per subscriber."""

    def subscribe(self) -> AsyncIterator[DataChangeEvent]:
        """注册订阅者，返回事件异步生成器；生成器被 aclose 时自动注销."""

    async def publish(self, event: DataChangeEvent) -> None:
        """广播事件给全部订阅者（尽力而为：慢订阅者不阻塞发布方，§15.5 E2）."""

    @property
    def subscriber_count(self) -> int:
        """当前订阅者数（可观测性 + 测试断言锚点）."""


# 进程级单例（API 层与 CLI/agent 同进程共享，ADR-021）
def get_event_bus() -> EventBus: ...
```

**设计要点**：
- **`publish` 必须非阻塞且绝不抛异常**——事件是失效信号，不是事务保证（ADR-053 影响节）。发布方（service 写路径）不因无订阅者/订阅者异常而受影响。
- **队列满时丢弃最旧事件**（不背压发布方）——GUI 失效信号可丢（下一次写入或窗口期重拉会收敛），写入正确性不可受影响。
  - **队列容量**：模块常量 `MAX_QUEUE_SIZE = 100`（A1 实施期确定，2026-09-10；测试直接引用该常量，不引入可配置面）。
- **`subscribe()` 返回标注 = `AsyncGenerator[DataChangeEvent, None]`**（非裸 `AsyncIterator`）——§15.4.2 要求生成器可 `aclose()`，`AsyncIterator` 标注下 mypy 报 `has no attribute "aclose"`。`AsyncGenerator` 是其子类型，契约语义不变（A1 实施期修正，2026-09-10）。
- **单例作用域 = 进程内**：GUI 经 HTTP/SSE 连接内核进程订阅；CLI/agent 在同一进程内直接 publish（ADR-021 内核进程化）。
- **`source` 解析链的 ContextVar 位置 = `domain/services/_data_change.py`**（`set_event_source` / `reset_event_source`）——因**读取方 `publish_change` 在 domain，而 domain 不能 import api**（AGENTS §4.2）。HTTP 中间件（批次 A）须**从该模块导入**写入。
  - ⚠️ **接线约束**：若批次 A 中间件未接线，该 contextvar 分支为**死代码**——A3 必须补一个「中间件写入 → service 读到 source」的集成断言。

#### 15.2.3 作用域分类（**实测关键约束**，决定 `project_id` 是否可空）

逐条 grep 后端 domain models 实测（2026-09-10），17 个域存在**两类作用域**：

| 类别 | 域 | `project_id` | 依据 |
|------|-----|-------------|------|
| **项目作用域** | project, chapter, volume, character, character_group, character_relation, outline, plot_point, story_arc, world_setting, world_category, map, map_pin, foreshadowing, timeline_event, knowledge_relation, draft | ✅ 有（实体带 `project_id`） | 实体模型逐条实测 |
| **全局作用域** | **agent_template**, **agent**, **skill**, **settings**, **provider_config** | ❌ **无**（`project_id = None`） | `AgentTemplate`（`id/name/is_default`，无 project_id）/ `Skill`（`name` 键，无 project_id）/ `ProviderConfig` / `AppSettings` |
| **双作用域** | **memory** | ⚠️ 部分（项目偏好有、用户偏好无） | `ProjectPreference`（`preference.py` L61 带 `project_id`）vs `UserPreference`（`user_preference.py` **无 project_id 字段**——跨项目累计 `source_projects`，事实全局单份） |

> **🔴 实测发现的 ADR-053 缺口（load-bearing）**：ADR-053 事件信封把 `project_id` 写成**必填**（`"project_id": "<uuid>"`），但据此实现会 **对全局域强行编造 project_id 或直接失败**——`AgentTemplate`/`Skill`/`ProviderConfig`/`AppSettings` 模型**根本没有 project_id 字段**。**本章裁决：`project_id` 为 `str | None`**，全局域发 `None`，GUI 侧按「全局域事件对所有项目页面生效」处理（§15.6 矩阵）。此项已回写 ADR-053 v1.1（§15.10）。

> **#989 正是全局域缺 project_id 的直接后果**：模板是全局资源、被多项目引用，`used_by` 是**跨项目引用集合**——所以它的陈旧不是「某项目内数据旧」，而是「引用关系全局旧」。收编方案见 §15.6.2。

#### 15.2.4 `source` 归属判定（ADR-053 D3 落地）

`source` 取值与判定来源：

| source | 判定方式 | 现状 |
|--------|---------|------|
| `gui` | HTTP 请求头 `X-Inkflow-Source: gui`（GUI 的 `apiFetch` 统一注入） | ⬜ 待实现（§15.9 批次 A） |
| `cli` | CLI 直连 service（不经 HTTP）→ 调用点显式传参 | ⬜ 待实现 |
| `mcp` | MCP 工具调用点显式传参 | ⬜ 待实现 |
| `agent` | agent/scheduler 内部写入点显式传参 | ⬜ 待实现 |
| `unknown` | 缺省（无法判定时） | ✅ 默认值 |

**判定链（实现规范）**：`显式参数 > 请求头（contextvar）> "unknown"`——镜像 #496 correlation 的解析链形态（`显式参数 > contextvar > ""`，见 `logging/correlation.py` docstring）。HTTP 侧由中间件把 `X-Inkflow-Source` 写入 contextvar；service 层发布时读取。

> **⚠️ 诚实标注（勿高估现状）**：**当前无任何 source 标记机制**——`X-Inkflow-Source` 头、相关 contextvar、GUI `apiFetch` 注入全部**尚不存在**，属本章新增。D3 的「后端 source 过滤」在批次 A 交付前**不可用**，此期间 self-originated 去重**完全依赖前端防抖 + 本地写入后既有局部更新**（§15.5.4 E1）。

### 15.3 变更事件发射挂点（后端写路径）

#### 15.3.1 挂点位置裁决：service 层（ADR-053 D1 确认落地）

在 **domain services 的 create/update/delete 方法末尾**发布事件（不是仓储层统一广播）：

- service 层携带**领域语义**（什么域、什么动作）；仓储层退化为「表行级」会丢语义
- service 层是**语义最准的汇聚点**：HTTP router（GUI/CLI 共用）与内核内 agent/scheduler 写入都经 service
- 覆盖范围**按域增量**，不过度插桩（AGENTS.md §1「不做架构宇航员」）

**不选仓储层的理由**（ADR-053 备选 A 已否决）：漏插风险最小但事件粒度退化为表行级，且**级联删除/钩子写操作**（如角色删除触发 `map_cleanup`）会在仓储层产生无法归属语义的事件。

#### 15.3.2 `project_id` 可得性（**实测发现的核心实现约束，load-bearing**）

逐条 grep 后端 service 签名实测（2026-09-10），写方法按签名分**两类**：

| 类 | 形态 | 示例（实测签名） | `project_id` 来源 |
|----|------|----------------|------------------|
| **A. create 类** | `(project_id, ...)` 首参带 project_id | `create_character(self, project_id: uuid.UUID, name, ...)` / `create_map(self, project_id, name, ...)` / `create_outline(self, project_id, name, ...)` / `create_volume(self, project_id, title, ...)` / `create_chapter(self, project_id, title, ...)` / `create_setting(self, project_id, name, ...)` / `create_category(self, project_id, name, ...)` / `create_arc(self, project_id, name, ...)` / `create_group(self, project_id, name, ...)` / `create_project(self, name, ...)` | ✅ **直接可用**（形参） |
| **B. update/delete 类** | `(entity_id, ...)` **只有实体 id** | `update_character(self, character_id, update)` / `delete_character(self, character_id)` / `update_map(self, map_id, update)` / `delete_map(self, map_id, ...)` / `update_outline(self, outline_id, update)` / `delete_chapter(self, chapter_id)` / `move_chapter(self, chapter_id, target_volume_id)` / `update_volume(self, volume_id, dto)` / `delete_point(self, point_id)` | ⚠️ **需从已加载实体解析**（`existing.project_id`） |

> **🔴 实现规范（否则事件会缺 project_id）**：B 类方法**必须在发布前先取得实体**——多数方法**本就已加载实体**（如 `update_character` 内部 `existing = await self._repo.get(...)`），因此 **`project_id = str(existing.project_id)` 可零额外查询获得**。**禁止**为发事件新增一次 `repo.get()` 查询（违反「事件是尽力而为信号」的轻量定位）。
>
> **⚠️ 实测修正（A3 实施期，2026-09-10）——「薄透传」方法比预想的多**：原 v1.2 举例称 `delete_character`（L232）「先取实体以触发 map_cleanup」故 project_id 可得，**实测为假**：它直接 `await self._repo.hard_delete(cid)`，**未加载实体**（map_cleanup 用的是 `character_id` 而非实体）。同类「薄透传」实测清单（A3 接的批次 A/B 域）：
> - `delete_character` / `delete_group` / `delete_pin` / `delete_outline` / `delete_point` / `delete_arc` —— 均**未加载实体** → 发 `None` + `logger.warning`
> - `update_pin` —— 非透传但 `MapPin` 模型**无 project_id 字段**且未加载 map → `None` + warning
> - **反例（原判「可能薄透传」但实测反而可得）**：`delete_relation` **会加载 relation** → `project_id` 可解析（非 None）
>
> **铁律重申**：**拿不到 project_id 时发 `None` 并记 warning**（不阻断写入、不伪造 id）——GUI 侧该事件退化为「全项目刷新」（§15.6.3 有意的安全偏向）。**禁止**为此新增查询（若确需带上 project_id，须先改 spec 讨论「是否允许为发声事件付一次查询」）。

#### 15.3.3 发布点实现形态（避免侵入式铺开）

```python
# domain/services/<domain>_service.py — MODIFY（每域写方法末尾）

# 形态：写操作成功后 finally 式发布（成功才发，失败不发）
result = await self._repo.create_character(...)
await self._publish("character", "create", str(result.id), result.project_id)
return result
```

**统一辅助（避免 17 个 service 各写一遍样板）**：在 `domain/services/_data_change.py` 提供

```python
async def publish_change(
    domain: str,
    op: str,                     # create|update|delete
    resource_id: object,         # UUID | int → str()
    project_id: object | None,   # UUID | None
    *,
    source: str | None = None,   # None → 由 contextvar 解析（§15.2.4）
) -> None:
    """发布数据面变更事件（尽力而为，绝不抛异常，绝不阻断写路径）."""
```

**关键不变量**：
1. **写路径成功后才发布**——写失败（异常/校验失败/返回 None）**不发布**（避免 GUI 拉取到不存在的资源）
2. **发布调用包在 `try/except` 内**，异常吞掉 + 记 warning——**事件发布永不影响写入结果**（ADR-053 影响节「尽力而为」）
3. **`delete` 类在删除成功后发布**（此时实体已不在，GUI 收到 event 后 refetch 列表自然移除该项）
4. **不发布高频噪声写**——见 §15.6.4 过滤规则

> **依赖方向说明（A1 实施期确定，2026-09-10）**：`publish_change` 需取总线（实现于 `infrastructure/events/`），但本函数在 `domain/services/`——采用**函数内局部 import**（`from inkflow.infrastructure.events import get_event_bus`），**模块顶层保持 domain 零 infra/框架依赖**（AGENTS §4.2；镜像 `agent_service` 等存量形态）。是否改由 domain port 抽象留待 A3/评审裁定（当前 YAGNI）。

#### 15.3.4 首批覆盖域（按 issue 指定 + 失效矩阵反推）

**批次 A（首批，8 个域，覆盖三次爆点 + 同构高危面）**：
`map` / `map_pin` / `agent_template` / `settings` / `provider_config` / `agent` / `character` / `outline`

**批次 B（补齐项目作用域）**：
`chapter` / `volume` / `world_setting` / `world_category` / `foreshadowing` / `timeline_event` / `plot_point` / `story_arc` / `character_group` / `character_relation` / `knowledge_relation` / `memory` / `session` / `skill` / `draft`

> **为何 A 批含 `map`/`agent_template`**：正是 #973/#989 两爆点所属域，**收编必须让原 ad-hoc 补丁可被替换**（§15.6.2 替换条件）。`settings`/`provider_config` 对应 #987 族。`character`/`outline` 是「同构高危面」中列表最重者。

### 15.4 API 契约：事件订阅端点

#### 15.4.1 端点定义（新增 1 个长驻订阅端点）

| 方法 | 路径 | 请求体 | 响应 |
|------|------|--------|------|
| GET | `/api/v1/events/stream` | 无 | `text/event-stream`（事件帧流，§15.5） |

**查询参数（可选过滤器）**：

| 参数 | 类型 | 语义 |
|------|------|------|
| `project_id` | str? | 只接收该项目的项目作用域事件（+ 全部全局域事件）；缺省 = 接收全部 |

**为何是 GET**（与 §3.1 写作端点 POST 的对比裁决）：订阅流**无请求体**（无长 outline/context 载荷），且**长驻**——GET 语义正确。**仍用 `fetch + ReadableStream` 而非 `EventSource`**（ADR-053 影响节明确禁止 EventSource）：需要携带 `X-InkFlow-Token` 自定义头（ADR-021 本地 token 校验），EventSource 做不到。

**响应头**（与 §3.1 同族，StreamingResponse 必须显式设置）：

```text
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no        # 云端部署防代理缓冲
```

#### 15.4.2 鉴权与中间件约束（**ADR-053 影响节硬约束**）

- **SSE 端点禁止 `BaseHTTPMiddleware`**——必须纯 ASGI（`BaseHTTPMiddleware` 会缓冲/破坏 StreamingResponse）。**实测先例**：`CorrelationIdMiddleware` / `TokenAuthMiddleware` / `DocsGateMiddleware` 均为纯 ASGI（`async def __call__(self, scope, receive, send)`）。
- **TokenAuth 必须放行长驻流**——`GET /api/v1/events/stream` 与写作流同属需带 token 的路径；实现时**核对 `token_auth.py` 的路径白名单/校验逻辑**，确保 SSE 长连接不被超时或缓冲策略误杀（实现期验证项，§15.9 批次 A）。
- **断连清理**：订阅生成器被 `aclose` 时注销订阅者；`asyncio.CancelledError` **不吞、`raise` 后清理**（`chat_stream` 已修同族坑，ADR-053 影响节明确要求）。

#### 15.4.3 与内核生命周期对齐

GUI 订阅的前提是**内核已就绪**（`useKernelStore.status === 'ready'`）。订阅**不得**在内核 boot 期发起——`apiFetch` 在未就绪时返回 401（#78 preload 竞态族）。**实现规范**：订阅 effect 依赖 `kernelStatus === 'ready'`，且先 `await ensureApiReady()`（`library.tsx` 既有同源防竞态先例，L217-222）。

### 15.5 SSE 事件帧协议与订阅时序

#### 15.5.1 事件帧 schema（与 §6.2 写作帧**不同的另一种帧**）

```text
GET /api/v1/events/stream
→ 200 text/event-stream

data: {"domain":"map","op":"create","resource_id":"7","entity_id":"7","project_id":"3f2b...","source":"cli","traceparent":"00-4bf9...-a1c2...-01","occurred_at":"2026-09-10T12:00:01Z"}
data: {"domain":"agent_template","op":"update","resource_id":"2","entity_id":"2","source":"gui","occurred_at":"2026-09-10T12:00:03Z"}
```

**帧编码（`_encode_change_frame`）**：

```python
def _encode_change_frame(ev: DataChangeEvent) -> str:
    """DataChangeEvent → SSE 帧字符串（data: <json> + 空行）."""
    payload = {
        "domain": ev.domain,
        "op": ev.op,
        "resource_id": ev.resource_id,
        "entity_id": ev.entity_id or ev.resource_id,   # 兼容别名（§15.2.1）
    }
    if ev.project_id is not None:
        payload["project_id"] = ev.project_id           # None 时省略（帧最小化，同 §6.2 省略规则）
    if ev.source:
        payload["source"] = ev.source
    if ev.traceparent:
        payload["traceparent"] = ev.traceparent
    if ev.occurred_at:
        payload["occurred_at"] = ev.occurred_at
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

> **与 §6.2 写作帧的关键差异（勿混用编解码器）**：写作帧靠 `done` 布尔判别 delta/done；**事件帧无 `done` 字段**（长驻流不结束）——判别靠 **`domain` + `op` 存在**。两套帧**共用 `data:` + `\n\n` 传输形态**，但**解码器必须分开**（前端 `api/sse.ts` 的 `StreamFrame` 解析不得复用于事件流）。

**帧序列不变量**：
1. 事件帧**数量无上限**（长驻流，随写操作持续到达）
2. **无 `done` 帧**、**无终止帧**（流仅在断连/内核停止时结束）
3. `project_id` 在全局域事件中**省略**（≠ 空串，§15.2.3）
4. **不发送 `event:` 类型行、不发送 `id:` 行**（同 §6.3；无断点续传，§15.8）

#### 15.5.2 订阅时序图（内核 → SSE → store → 组件）

```text
┌──────────┐        ┌──────────────┐      ┌───────────┐    ┌──────────────┐   ┌─────────┐
│ 外部客户端 │        │  FastAPI 内核 │      │ EventBus  │    │ GUI 订阅客户端 │   │ Zustand │
│ CLI/MCP/  │        │  （单进程）   │      │（进程内）  │    │ (Electron)   │   │ store   │
│ agent/GUI │        │              │      │           │    │              │   │         │
└────┬─────┘        └──────┬───────┘      └─────┬─────┘    └──────┬───────┘   └────┬────┘
     │                     │                    │                 │                │
     │ ① CLI 写请求（直连 service，不经 HTTP）    │                 │                │
     ├────────────────────►│                    │                 │                │
     │                     │ ② service.create_map(...)            │                │
     │                     │    └─ 成功 ─┐       │                 │                │
     │                     │ ③ publish_change(domain="map",        │                │
     │                     │      op="create", project_id=...)     │                │
     │                     ├───────────────────►│                 │                │
     │                     │                    │ ④ 广播给全部订阅者 │                │
     │                     │                    ├────────────────►│                │
     │  ◄── ⑤ 写响应返回 ───┤                    │                 │                │
     │                     │                    │   ⑥ 帧: data:{domain:"map",op:"create",…}
     │                     │                    │                 │                │
     │                     │                    │      ⑦ 匹配 domain→map 订阅表      │
     │                     │                    │         self-originated? source=cli ≠ gui → 处理
     │                     │                    │         debounce 300ms（§15.5.4）  │
     │                     │                    │                 ├───────────────►│
     │                     │                    │                 │ ⑧ loadMaps()   │
     │                     │                    │                 │  （invalidate→  │
     │                     │                    │                 │   refetch）    │
     │                     │                    │                 │  ◄── 列表更新 ──┤
     │                     │                    │                 │                │
     │                     │ ⑨ 订阅断开（内核停止/GUI 关闭）        │                │
     │                     │  ◄───────────────────────────────────┤                │
     │                     │    └─ aclose → 注销订阅者（不吞          │                │
     │                     │        CancelledError，§15.4.2）      │                │
```

**时序不变量**：
- ③→④ **发布不阻塞写响应**（⑤ 可先于 ④ 完成）——GUI 可能比写请求方**更早或更晚**看到事件，无顺序保证（§15.5.3 E2）
- ⑦ **self-originated 判定**在订阅客户端侧（前端为主，ADR-053 D3）
- ⑧ **refetch 失败静默**（不阻断、不弹错）——ADR-053 影响节「GUI 重拉失败应静默不阻断」

#### 15.5.3 生命周期与边界

| # | 场景 | 处理 |
|---|------|------|
| E1 | GUI 自己发起写（source=gui） | 前端 debounce + **忽略自己产生的部分事件**；本地写入后既有 store 局部更新（如 `templates.createTemplate` 已 append）先于/替代 refetch |
| E2 | 订阅者处理慢 / 队列积压 | **丢弃最旧事件**，不背压发布方（`publish` 非阻塞，§15.2.2） |
| E3 | 无订阅者（纯 CLI 会话） | `publish` 静默丢弃（零成本）；写入正常 |
| E4 | SSE 断连 | 回退 `startPolling` 轮询（`lib/polling.ts` 已有）；**断线期间事件不补发**（无 `Last-Event-ID`，§15.8）——重连后由下一次写事件或轮询窗口收敛 |
| E5 | 重复事件（同一写触发多次 publish） | **幂等**：refetch 是幂等读；GUI 侧按 domain 去重（debounce 窗口内合并） |
| E6 | 事件帧 JSON 解析失败 | 前端**跳过该帧**并记 warning，不断开订阅（健壮性优于严格） |
| E7 | 内核重启 | GUI 订阅重连（§15.5.4 重连策略）；期间快照陈旧靠轮询兜底 |
| E8 | 全局域事件（project_id 省略） | GUI **对所有项目页面生效**（§15.6.3） |

#### 15.5.4 前端订阅实现规范

**订阅客户端**（新增 `api/event-stream.ts`，镜像 `api/sse.ts` 的 fetch+ReadableStream 模式但**独立解码器**）：

```typescript
/** 订阅内核数据面变更事件；返回 abort 函数（生命周期持有者调用） */
export async function subscribeDataChanges(
  onEvent: (ev: DataChangeFrame) => void,
  onError?: (message: string) => void,
): Promise<() => void>;
```

**去重与防抖（ADR-053 D3 前端为主）**：
- **debounce 300ms**：同一 `project_id + domain` 在窗口内合并为一次 reload（吸收 burst，如保存正文时 content 多次 PATCH）
- **self-originated 过滤**：`source === 'gui'` 时**可跳过**（本地写入已有局部更新）；批次 A 前 source 机制未就绪 → **仅靠 debounce**（§15.2.4 诚实标注）
- **防抖放前端**（ADR-053 D3 已裁决否决后端防抖）：只有 GUI 手持「当前看哪个 project / 编辑哪章」的客户端状态，能识别 self-originated 并控制刷新节奏

**重连策略**：断连后**指数退避重连**（1s → 2s → 4s → 上限 30s）；重连成功即视为「可能错过事件」→ **触发当前页面全部订阅 domain 的一次全量 refetch**（收敛断线期间的陈旧）。**这不违反「不补发」**：不补发**单个事件**，但重连后做一次**兜底全量拉取**（代价可控、实现简单）。**订阅就绪语义（#1102 修订）**：该兜底在**首次连接成功**后同样触发一次——`onReconnect` 语义从「重连」放宽为「订阅就绪」（每次成功建立连接恰好一次；连接失败不触发）。消除「页面 mount 首拉 → 订阅生效」之间外部写入（CLI/HTTP/MCP/agent）的永久丢失窗口：挂载期落在无订阅者间隙的写入，由订阅就绪后的这次全量 refetch 收敛（多一次拉取，数据量小，成本可控）。

**生命周期归属**：订阅句柄由**全局单例 effect 持有**（建议放 `kernel.ts` store 旁或 `App.tsx` 顶层），**不是每页面各订阅**——避免 N 个页面 N 条 SSE 连接。**页面只注册「我关心哪些 domain」**（§15.6 矩阵），失效分发由全局订阅器统一路由。

### 15.6 失效语义矩阵（**本章核心交付物**）

#### 15.6.1 粒度裁决原则（为什么不是「全量事件化」）

**裁决原则**（AGENTS.md §1「不做架构宇航员」）：

| 推送价值 | 判据 | 处置 |
|---------|------|------|
| **高**（值得推送） | ① 有**外部写入路径**（CLI/HTTP/MCP/agent 能改同一资源）② **低频**（人操作级，非每 token/每次击键）③ **陈旧有用户可见后果**（误导判断/数据丢失风险） | **推送 + 订阅失效** |
| **低**（保持重拉） | ① 几乎只由 GUI 自身写入 ② **高频**（如正文自动保存） ③ 陈旧后果轻微（用户切页面即重取） | **保持既有重拉机制**（不推送） |

**明确不推送的面（避免过度设计）**：

| 面 | 不推送理由 |
|----|-----------|
| **章节列表（树）随项目切换** | 高频低险——项目切换本就整体重取（`chapter.ts` `loadChapterTree(projectId)`）；外部改章节的频率远低于 GUI 自身 |
| **正文草稿自动保存（`draft.update`）** | 每几秒一次的高频写；推送会给所有 GUI 造成持续 refetch 风暴 |
| **chat 消息流（`chat_message`）** | 已有专属 SSE 流（`chat_stream.py`）；另一条事件面会造成双通道 |
| **agentic 执行进度（`agent_run` step 级）** | 已有专属轮询/流（`useExecutionPoll.ts` + `startPolling`）；推它属重复基建 |
| **日志/追踪（`logs`）** | 已有 #496 日志页自身刷新机制 |

> **判定口诀**：**已有专属推送/轮询通道的面，不进统一事件面**（否则双通道分叉）；**高频自动写不进事件面**（噪声淹没真信号）。

#### 15.6.2 失效粒度表（domain × 页面 × 重拉/局部更新）

**图例**：`FR` = 全量 refetch（invalidate→refetch）；`LU` = 局部更新（store 内增删改）；`—` = 不推送（保持现状）

| domain | 作用域 | 受影响页面/组件 | 现有加载方法（实测） | 失效方式 | 理由 |
|--------|--------|----------------|-------------------|---------|------|
| **map** | 项目 | library（世界观/地图视图）、地图工作台 | `library.tsx` maps effect（L226-259） | **FR** | #973 爆点域；列表轻、外部建图频繁；FR 最简且已收敛 |
| **map_pin** | 项目 | 地图工作台 | `map_service.list_pins` 经工作台拉取 | **FR**（工作台内） | pin 列表随图切换重取；外部加 pin 需可见 |
| **agent_template** | **全局** | settings（模板面板） | `templates.loadTemplates()` | **FR** | #989 爆点域；`used_by` 是跨项目引用集合，**必须服务端权威重取**，不可局部推算 |
| **settings** | **全局** | settings 页、写作页（依赖默认模型等） | `settings` 相关加载 | **FR** | #987 族；配置影响面广，局部更新易漏 |
| **provider_config** | **全局** | settings（模型页）、modelReadiness | `models.loadProviders?`（`models.ts`） | **FR** | 模型列表/默认模型是跨页公共依赖 |
| **agent** | **全局** | agents 页、AgentChainCard、写作页 | `agents.loadAgents()` | **FR** | Agent 池被多页消费（含链编排） |
| **character** | 项目 | library（角色分类）、角色详情面板 | `library.tsx` characters effect | **FR** | 列表重、外部（AI 提取）批量创建角色常见 |
| **outline** | 项目 | library（大纲分类）、写作页大纲面板 | `useOutlineLibrary(projectId, cat, reloadKey)` | **FR** | 外部（AI 生成大纲）写入频繁 |
| **volume** | 项目 | 章节树 | `chapter.loadChapterTree` | **FR**（项目内） | 卷变更影响树结构 |
| **chapter** | 项目 | 章节树、写作页 | `chapter.loadChapterTree(projectId)` | **FR**（**仅当前项目**） | ⚠️ 见下方「分级裁决」——章节树高频，**只在事件 project_id == 当前项目时**才失效 |
| **world_setting** | 项目 | library（世界观） | `useWorldCategories` / world 列表 effect | **FR** | 同 outline 族 |
| **world_category** | 项目 | library（世界观分类 chips） | `useWorldCategories(..., reloadKey, ...)` | **FR** | 分类 chips 是跨视图筛选源 |
| **foreshadowing** | 项目 | library（伏笔分类） | `LibraryItemList` 经 library effect | **FR** | 同 world 族 |
| **timeline_event** | 项目 | library（时间线） | library timeline effect | **FR** | 同 world 族 |
| **plot_point / story_arc** | 项目 | library（大纲分类） | `useOutlineLibrary` | **FR** | 大纲子实体，随大纲面失效 |
| **character_group / character_relation** | 项目 | library（角色分类） | character/relation effect | **FR** | 随角色面失效 |
| **knowledge_relation** | 项目 | library（知识图谱） | `library.tsx` kg effect（L338-355） | **FR**（图谱视图激活时） | 已用 `reloadKey` 局部刷新先例 |
| **memory** | **双** | memory 页 | `memory.tsx` 挂载拉取 | **FR** | 项目偏好按 project_id 过滤；用户偏好（`scope=user`）全局事件 |
| **session** | 项目 | sessions 页 | `sessions.tsx` 三路 effect + `reloadKey` | **FR** | 外部 agent 建会话常见 |
| **skill** | **全局** | agents 页（技能列表）、settings | `agents.loadSkills()` | **FR** | 技能全局共享 |
| **draft** | 项目 | 写作页（草稿树） | `chapter.loadPendingDrafts(projectId)` | **—（暂不推送）** | 高频写，噪声大；列入候选观察（§15.6.5） |

**粒度裁决（FR vs LU 的判据）**：

- **默认 FR（全量重拉）**——理由：① 复用既有 `loadXxx` 方法零新代码；② 本地自用项目数据量小，重拉成本可忽略（ADR-053 D2 已裁）；③ **LU 需要前端自行推算服务端变更结果**，一旦推算错过字段就产生「局部更新后仍陈旧」的更隐蔽 bug（比 FR 危险）。
- **LU 仅在「store 已有局部更新方法且语义完全等价」时采用**——实测 `templates.ts` 已有 `createTemplate`(append, L86) / `updateTemplate`(map, L100) / `deleteTemplate`(filter, L118) / `duplicateTemplate`(append, L128) / `setDefault`(L141)，**但这些是 GUI 自身写路径的返回值更新，不是事件驱动的**。**本机制不新增 LU 路径**；GUI 自身写入继续用它（self-originated 场景），**事件到达一律 FR**。
- **`used_by` 类聚合字段强制 FR**（#989 教训）：`used_by` 是**服务端聚合计算**的跨项目引用集合，前端**无法**从单个 `agent_template` 事件推算——必须 refetch。这是 #989 用 `await loadTemplates()` 而非局部改的根本原因。

#### 15.6.3 全局域事件的跨项目语义

`project_id` 缺省的全局域事件（`agent_template`/`settings`/`provider_config`/`agent`/`skill`）：

- **对所有项目页面生效**——GUI 侧不做 project_id 过滤（无法过滤：事件本就不带）
- **影响面更大**：一个模板更新会让**任意项目**的 settings 页 refetch（正确——模板是全局的）
- **不与当前项目绑定**：即使当前无选中项目，全局域事件仍应处理（settings 页可在无项目时打开）

**`project_id` 过滤规则（前端）**：

```typescript
// 事件是否对我当前上下文生效
function affectsCurrent(ev: DataChangeFrame, currentProjectId: string | null): boolean {
  if (ev.project_id == null) return true;              // 全局域：总是生效（§15.6.3）
  return ev.project_id === currentProjectId;           // 项目域：仅当前项目
}
```

> **⚠️ project_id 拿不到时的退化**（§15.3.2 已知例外）：事件带 `project_id: null` 但**实际是项目域**（如 `delete_chapter` 未取到 project_id）——上式为真 → **全项目刷新**（比漏刷安全，代价是多刷一次）。这是**有意的安全偏向**。

#### 15.6.4 服务端过滤规则（不发布什么）

**不发布**（即使方法被调用）：

| 情况 | 理由 |
|------|------|
| 写操作**失败/未变更**（返回 `None`/`False`/抛异常） | 无实际变化，发布会产生假信号（§15.3.3 不变量 1） |
| **纯读操作**（`list_*`/`get_*`） | 不是变更 |
| **GUI 高频自动保存**（`draft.update`） | 噪声（§15.6.1） |
| **已有专属通道**（chat message、agent_run step、logs） | 双通道分叉（§15.6.1） |
| 批量内部写入的**中间态**（如 AI 提取循环逐条建实体） | 应**批量完成后发布一条域级事件**（或依赖 GUI debounce 合并）——实现期按域裁决，避免 N 条事件风暴 |

> **`op` 语义边界**：`move`/`reorder`/`set_default`/`resolve` 等**语义化操作**统一映射为 `op="update"`（信封只有三值，保持简单）；细分动作不进信封（GUI 一律 FR，不需知道具体动作）。

#### 15.6.5 候选观察面（本期不推，留档）

| 面 | 观察理由 | 触发条件（何时考虑推） |
|----|---------|---------------------|
| `draft`（草稿树） | 写作页草稿树是 issue 明列候选面 | 若实测「外部（AI 续写落草稿）后 GUI 草稿树陈旧」成为用户可见问题 |
| `agent_run`（执行视图） | 已有轮询，若 2.0.0 云端多端需推送则统一 | 云端多端同步立项时 |

### 15.7 #973 / #989 ad-hoc 重拉收编（**验收项**）

**issue #992 验收明确要求**：把两个 ad-hoc 重拉点收编为「**推送缺位时的降级重拉**」，并写明**未来替换条件**。

#### 15.7.1 收编语义（定位转变，非删除）

两处 ad-hoc 补丁**不立即删除**，而是**重新定位**：

| 补丁 | 现状（ad-hoc） | 收编后定位 | 删除条件 |
|------|--------------|-----------|---------|
| **#973** `library.tsx` maps effect 依赖 `[projectId, reloadKey, workbenchActive]` | 「进/退工作台重拉」= 唯一失效手段 | **降级重拉**（推送缺位时的兜底） | 批次 A（map 域事件上线）**且** E2E 验证推送覆盖该场景后 |
| **#989** `settings.tsx` 确认入口前 `await loadTemplates()` | 「确认前重拉」= 防止用旧 `used_by` 判风险 | **降级重拉**（同上） | 批次 A（agent_template 域事件上线）**且**「外部挂引用 → GUI 停留 → 点删除」E2E 场景验证推送已使 `used_by` 新鲜后 |

**收编动作（文档层，本次设计单交付）**：在两处代码**补注释**标注其新定位（实现批执行）；spec 侧在本节登记定位与替换条件（本节即登记处）。

#### 15.7.2 为何不立即删除（**关键安全论证**）

**#989 的补丁有独立价值，不能因为有了推送就删**：

- 推送是**尽力而为**的失效信号（ADR-053 影响节）——断连、队列丢弃、内核重启期间事件可能不到
- **#989 的后果是数据丢失**（静默断链删被引用模板）——**不能把「防数据丢失」的唯一保障押在一条可能断的推送流上**
- 因此 **#989 的「确认前重拉」应长期保留为「最后一道防线」**，推送只是让它**更早生效**（用户停留时就能看到新引用），而**不是替代它**

> **🔴 安全偏向原则（本章硬约束，**2026-09-10 用户拍板 Q15-2=A 确认落地**）**：**「防数据丢失」类校验（#989）的双保险不可拆**；**「可见性」类补丁（#973）可在推送验证后移除**。区别判据 = **该陈旧会导致数据损坏/丢失吗？** 会 → **长期保留兜底**；只会「看不到」→ 可移除。

#### 15.7.3 替换验证清单（何时可以删 #973 补丁）

必须**全部**满足（实现批执行，设计单定义判据）：

1. `map` 域事件已在批次 A 上线（service 层 publish + SSE 广播 + GUI 订阅）
2. E2E 场景通过：「GUI 停留设定库 → 外部（CLI/HTTP）建图 → **不切换页面** → 地图列表自动出现新图」
3. E2E 场景通过：「断连后重连 → 兜底全量 refetch 使新图出现」（§15.5.4 重连策略）
4. 回归：`library-map-workbench-fixes.test.tsx` 中依赖 `reloadKey/workbenchActive` 的用例（实测 K3 等）语义迁移或保持通过

**未满足前禁止删除补丁**（宁可双保险，不可单依赖）。

### 15.8 2.0.0 前瞻约束（云端多端）

issue #992 要求「设计需预留不自缚」。本章对 2.0.0 的**承诺与不承诺**：

| 维度 | 承诺（本章设计已预留） | 不承诺（明确排除） |
|------|---------------------|-----------------|
| **权威模型** | **服务端权威 + 客户端失效**（事件只是失效信号，数据永远从服务端拉） | 无 CRDT / 无 OT / 无冲突合并 |
| **事件面复用** | 同一 `DataChangeEvent` 信封 + 同一 SSE 语义可跨端复用（云端多端「跨窗口同步」地基） | 不做多端一致性保证（无版本向量/无因果序） |
| **投影** | `project_id` 已预留（云端多租户隔离维度） | 不做用户级/租户级过滤（`X-Inkflow-Source` 只标识发起方，不是身份） |
| **传输** | 复用 F23 通道与 `fetch+ReadableStream` 模式（ADR-021 一条代码路径两用） | 不承诺 WebSocket（ADR-053 备选 C 已否决） |
| **可靠性** | 尽力而为 + 降级轮询（§15.5.4） | **不补发**（无 `id:` 帧 / 无 `Last-Event-ID`）；断线期间事件永久丢失，靠重连全量拉取收敛 |
| **顺序** | 无顺序保证（§15.5.2 时序不变量） | 不做事件排序/去重窗口的因果保证 |

> **为何「无 CRDT」是可接受的**：InkFlow 2.0.0 前是**单机自用**（用户 profile：个人自用项目，非商业产品）；云端多端场景下**服务端权威 + 客户端失效**已足够——两端不同时编辑同一字段时，先写者的变更经事件通知后写者失效重拉，后写者看到最新状态。**同时编辑同一字段的冲突**属 2.0.0 立项时另行设计（本章不预设机制，只保证不把路堵死）。

**已预留但本批不实现的扩展点（不自缚的关键）**：

- `occurred_at`（时间戳）——未来需要顺序/窗口时可作依据
- `traceparent`——跨端追踪可复用（§15.9）
- `project_id: str | None`——多租户维度已就位
- **`DataChangeEvent` 为 frozen dataclass**——新增字段（如 `version`/`seq`）向后兼容（GUI 解码器跳过未知键，§15.5.3 E6）

### 15.9 与 #931（correlation/trace）的关系

issue #992 要求「事件信封复用 trace 字段，对齐不重复造」。**实测确认 #931 已就绪，可直接复用**：

| 能力 | 实测位置 | 复用方式 |
|------|---------|---------|
| `TraceContext`（trace_id/span_id/parent_span_id） | `logging/trace.py` L28-35 | 事件发布时读 `get_trace_context()` |
| `make_traceparent(ctx)` → `00-<32hex>-<16hex>-01` | `logging/trace.py` L53-55 | 直接生成信封 `traceparent` 字段 |
| `get_trace_context()` contextvar 读取 | `logging/trace.py` L83-85 | service 层 publish 时调用 |
| 请求级建立（合法头 → 子 span；缺失 → 新根） | `api/middleware/correlation.py` L71-82 | HTTP 写入路径自带 trace 上下文，**零额外代码** |
| 响应头回写 traceparent | `api/middleware/correlation.py` L84-95 | 既有行为，无需改 |

**分层对齐（不重复造）**——两者是**互补而非重叠**：

- **#931（已实现）**：解决「**一次请求跨面可追踪**」——同一 trace 贯穿 HTTP → service → LLM → 日志
- **#992（本章）**：解决「**一次写入跨界面可见**」——写入产生的事件带上该写入的 trace 上下文
- **复用点**：事件信封的 `traceparent` = **产生该变更的那次请求**的 traceparent（`get_trace_context()`）→ GUI 收到事件后可关联「是哪个请求改的」（调试/溯源）
- **不重复造**：**不新建** trace 机制、**不新建** correlation 机制、**不新建** ID 生成——全部复用 `logging/trace.py`

**实现规范**：
```python
# publish_change 内部（§15.3.3）
from inkflow.logging.trace import get_trace_context, make_traceparent
ctx = get_trace_context()
traceparent = make_traceparent(ctx) if ctx is not None else None
```

> **⚠️ 边界**：CLI/agent 直连 service（不经 HTTP 中间件）时 `get_trace_context()` 返回 `None` → 信封 `traceparent = None`（省略该键，§15.5.1）。**不为 CLI 路径强行造 trace 上下文**（超出本章范围；如需，属 #931 后续扩展）。

### 15.10 ADR-053 修订（v1 → v1.1）

本章实测发现两处需回写 ADR-053（**原地 v1.1，不新开 ADR**，遵循 ADR 演进约定）：

| # | ADR-053 原文 | v1.1 修订 | 依据 |
|---|-------------|----------|------|
| 1 | 事件信封 `"project_id": "<uuid>"`（**必填**） | `"project_id": "<uuid>" \| null`（**可空**；全局域为 null） | §15.2.3 实测：`AgentTemplate`/`Skill`/`ProviderConfig`/`AppSettings` 模型无 project_id 字段 |
| 2 | 信封字段名 `entity_id` | 规范名 `resource_id`，`entity_id` 保留为兼容别名（序列化同输出两键） | issue #992 提案用 `resource_id`；ADR 用 `entity_id`，两者需调和避免两拨实现互不兼容（§15.2.1） |

> **修订动作**：本设计单**同步修改 `adr/architecture/ADR-053.md`**（状态行标 v1.1 + 信封块 + 新增「v1.1 修订说明」小节），并在 `adr/README.md` 决策表行标注版本。

### 15.11 文件结构（对照真实树）

```text
backend/src/inkflow/
├── domain/
│   ├── models/
│   │   └── data_change_event.py      ← CREATE: DataChangeEvent dataclass（§15.2.1）
│   └── services/
│       ├── _data_change.py           ← CREATE: publish_change 统一辅助（§15.3.3）
│       ├── map_service.py            ← MODIFY: 写方法末尾发布（批次 A）
│       ├── agent_template_service.py ← MODIFY: 同上（批次 A，#989 域）
│       ├── settings_service.py       ← MODIFY: 同上（批次 A，#987 域）
│       ├── provider_config_service.py← MODIFY: 同上（批次 A）
│       ├── agent_entity_service.py   ← MODIFY: 同上（批次 A）
│       ├── character_service.py      ← MODIFY: 同上（批次 A）
│       ├── outline_service.py        ← MODIFY: 同上（批次 A）
│       └── …（批次 B 域各自 MODIFY）
├── infrastructure/
│   └── events/
│       ├── __init__.py               ← CREATE
│       └── event_bus.py              ← CREATE: EventBus + get_event_bus 单例（§15.2.2）
└── api/
    ├── routers/
    │   ├── events.py                 ← CREATE: GET /api/v1/events/stream + _encode_change_frame
    │   └── __init__.py               ← MODIFY: 导出 events router（当前仅导出 6 个旧 router）
    ├── middleware/
    │   └── source.py                 ← CREATE: X-Inkflow-Source → contextvar（§15.2.4，批次 A）
    └── app.py                        ← MODIFY: 注册 events router + source 中间件
```

```text
frontend/packages/renderer/src/
├── api/
│   ├── event-stream.ts               ← CREATE: subscribeDataChanges（独立解码器，§15.5.4）
│   └── client.ts                     ← MODIFY: apiFetch 注入 X-Inkflow-Source: gui（批次 A）
├── hooks/
│   └── useDataChangeSubscription.ts  ← CREATE: 全局订阅 + debounce + domain 路由
└── （页面侧仅注册关心的 domain → 调既有 loadXxx，零新 store 方法）
```

```text
backend/tests/unit/
├── test_data_change_event.py         ← CREATE: 信封模型 + 帧编码（§15.12 M1）
├── test_event_bus.py                 ← CREATE: 订阅/发布/丢弃/注销（§15.12 M2）
└── （各 service 测试 MODIFY: 写路径发布断言 —— §15.12 M3）
tests/api/
└── test_events_api.py                ← CREATE: SSE 订阅端点（§15.12 M4/M5）
frontend/packages/renderer/src/
├── api/event-stream.test.ts          ← CREATE: 帧解码 + 断连/重连（§15.12 M6）
└── hooks/useDataChangeSubscription.test.ts ← CREATE: debounce/self-originated/路由（§15.12 M7）
```

**零新增运行时依赖**（复用 FastAPI `StreamingResponse` + `asyncio`，同 §8）。

### 15.12 测试策略与验收标准

#### 15.12.1 测试分层（遵循 ADR-018 分层）

| # | 层 | 载体（CREATE/MODIFY） | 覆盖 |
|---|----|---------------------|------|
| M1 | 单元·模型 | `backend/tests/unit/test_data_change_event.py`（CREATE） | `DataChangeEvent` 字段/默认值/frozen；`_encode_change_frame` 帧 JSON（`project_id=None` 时**省略键**、`entity_id` 兼容别名同值、`ensure_ascii=False` 中文可读）；**反例**：project_id 有值时必须出现 |
| M2 | 单元·总线 | `backend/tests/unit/test_event_bus.py`（CREATE） | `subscribe` 后 `publish` 收到事件；多订阅者都收到；**无订阅者时 publish 不抛异常**；订阅者异常/队列满**不影响 publish 返回**（丢弃最旧）；`aclose` 后自动注销（`subscriber_count` 断言）；**反例**：注销后 publish 不再投递 |
| M3 | 单元·service 发布 | 各 service 测试 MODIFY（批次 A 7 个域） | 写成功 → 发布一条事件（domain/op/resource_id/project_id 正确）；**写失败/返回 None 不发布**（反例）；**B 类方法 project_id 从实体解析**（断言 project_id 非 None）；`delete_chapter` 类「薄透传」方法的行为（取到 → 带 project_id；未取到 → project_id None + warning） |
| M4 | API·订阅端点 | `tests/api/test_events_api.py`（CREATE） | 订阅后触发一次写 → 收到对应事件帧；多事件顺序到达；查询参数 `project_id` 过滤；响应头 `text/event-stream` |
| M5 | API·边界 | 同上 | 客户端断开 → 订阅者注销（`subscriber_count` 归零，**无泄漏**）；`asyncio.CancelledError` 不吞（ADR-053 硬约束）；**反例**：无订阅时写入仍 200（publish 不影响写路径） |
| M6 | 前端·订阅客户端 | `api/event-stream.test.ts`（CREATE） | 帧解析（分块到达的 `data:` 行拼接）；**与写作帧解码器隔离**（事件帧无 `done` 不误判）；断连触发重连（指数退避）；重连成功触发兜底全量 refetch |
| M7 | 前端·订阅调度 | `hooks/useDataChangeSubscription.test.ts`（CREATE） | debounce 300ms 合并同 domain 事件；`affectsCurrent` 过滤（全局域 project_id=null → true；项目域不匹配 → false）；self-originated（source=gui）跳过；**反例**：不同 domain 事件不互相合并 |
| M8 | E2E（推送到位后） | `frontend/packages/electron/e2e/`（批次 A 后补） | **跨界面可见性**：GUI 停留某页 → 外部 CLI/HTTP 改数据 → **不切页面**列表自动更新（#973/#989 场景复刻）；断连重连兜底 |

#### 15.12.2 验收里程碑

| 里程碑 | 内容 | 验收方式 |
|--------|------|---------|
| **M-design（本单）** | 统一方案 spec（本章）+ ADR-053 v1.1 + 失效矩阵 + 排期拆解 | 本 PR merge（**无代码**） |
| M-A1 | EventBus + 信封 + 帧编码 + 订阅端点（§15.2/15.4/15.5 后端骨架） | M1/M2/M4/M5 全绿 |
| M-A2 | 批次 A 7 域写路径发布 + source 中间件 + GUI 订阅客户端 | M3/M6/M7 全绿 |
| M-A3 | 批次 A 页面接入（library maps / settings templates 等）+ E2E | M8 通过；**#973 补丁删除判据评估**（§15.7.3） |
| M-B | 批次 B 15 域补齐（§15.3.4） | 各域 M3 用例绿 + 矩阵逐行覆盖 |

### 15.13 排期拆解（实现批数量级）

> **数量级估算（非承诺工期）**：以「实现批（PR）」为单位，遵循 ADR-053「按域增量」与本章安全偏向。

| 批次 | 范围 | 规模 | 依赖 | 可并行 |
|------|------|------|------|--------|
| **批 0（本设计单）** | spec §15 + ADR-053 v1.1 | 文档 only，**1 PR** | — | — |
| **批 A1：后端基建** | 信封 dataclass + EventBus + `publish_change` + `GET /events/stream` + 帧编码 + 单测 + **刷新 `ci_cd/openapi_snapshot.json` + 重生 `api/schema/openapi.d.ts`** | **1 PR**（≈ 后端 6-8 文件新增 + 3 测试） | 批 0 | 与 A2 **可并行开发，但 A1 必须先合并**（见下方「🔴 契约门禁硬依赖」） |
| **批 A2：前端消费基建** | `api/event-stream.ts` + 订阅 hook + debounce + `affectsCurrent` + 前端单测 | **1 PR**（≈ 前端 2 新增 + 2 测试） | A1 已合并 + 本批 rebase | 与 A1 并行**开发**；**合并须待 A1 先入** |
| **批 A3：批次 A 域接入** | 7 域 service 发布 + source 中间件 + 页面订阅注册 | **1-2 PR**（7 域 × 数个写方法 + 页面接入） | A1 + A2 | 分域可并行（建议 map/template 先，因对应爆点） |
| **批 A4：E2E + #973 补丁收编** | E2E 跨界面可见性场景 + 补丁注释标注/删除评估 | **1 PR** | A3 | 串行（依赖 A3） |
| **批 B：批次 B 域** | 15 域补齐 | **2-3 PR**（按域分组） | A3（复用基建） | 组间可并行 |

**总计：约 7-9 个 PR**（批 0 + A1-A4 + B）。

**里程碑归属**：**挂 0.14.0**（与 issue #992 一致的 milestone 18）——批 0 + A1 + A2 为本迭代目标；A3/A4 + 批 B 视迭代余量顺延（**不写完成时间**，仅挂 milestone，遵循用户偏好）。

**并行度建议**：A1 ∥ A2（**可并行开发**）→ **A1 先 merge**（含快照 + d.ts 两个同步产物）→ A2 rebase（无需自己重生 d.ts）→ A3（A1+A2 完成后）→ A4 → 批 B。**峰值并行 2**（低）。

> **🔴 契约门禁硬依赖（A1/A2 实施期实测，#1091 CI 实证 2026-09-10）**：仓库对「后端契约 ↔ 前端消费面」有**两道互相独立**的门禁，均要求**改契约的那个 PR 自己带上全部同步产物**：
>
> | 门禁 | 位置 | 检查 | 产物 |
> |------|------|------|------|
> | **M1 快照漂移** | `backend/tests/unit/test_openapi_contract.py` | 后端 schema ↔ `ci_cd/openapi_snapshot.json` | `uv run python ../ci_cd/export_openapi.py`（cwd=backend） |
> | **前端类型漂移** | CI `lint-frontend` job | `pnpm gen:api` 后 `git diff --exit-code -- api/schema/openapi.d.ts` | `pnpm gen:api`（cwd=`frontend/packages/renderer`） |
> | **前端调用面契约** | `src/api/__contract__/contract.test.ts` | 前端 `apiFetch` 调用面 ⊆ 快照路径 | 端点须**先存在于快照** |
>
> **推论（两条，缺一即 CI 红）**：
> 1. **A1（后端基建）必须自带两个同步产物**：刷新 `ci_cd/openapi_snapshot.json` **且** 重生 `frontend/packages/renderer/src/api/schema/openapi.d.ts`。
>    - ⚠️ **易漏点**：`openapi.d.ts` 在 `frontend/` 下，写后端的人**天然想不到**要重生它；漏了 → `lint-frontend` 红（#1091 首轮 CI 实证）。
> 2. **A2（前端消费基建）必须先有 A1 合并**：A2 的 `api/event-stream.ts` 调用 `GET /api/v1/events/stream`，`contract.test.ts` 要求该路径**已在快照中**（A1 未合并时快照没有 → 红）。
>
> **禁止**为让某一批先绿而手改快照 / 手改生成的 d.ts / 删改契约测试——三者都是生成物或门禁本体，绕过等同伪造契约。
>
> **「A1 ∥ A2 可并行」的准确含义**：仅**开发**可并行；**合并必须 A1 先**，A2 随后 rebase（rebase 后 A1 的快照与 d.ts 已在 main，A2 无需自己重生 d.ts）。

### 15.14 关键决策记录（本章）

| # | 决策 | 理由 | 备选（否决） |
|---|------|------|-------------|
| D15-1 | **失效粒度默认 FR（全量 refetch），不新增 LU 事件路径** | 复用既有 `loadXxx` 零新代码；LU 需前端推算服务端结果，推算错更隐蔽；数据量小成本可忽略 | LU 局部更新（需逐域实现推算逻辑，错漏风险高）；混合（复杂） |
| D15-2 | **`project_id` 可空**（全局域 null） | 实测 `AgentTemplate`/`Skill`/`ProviderConfig`/`AppSettings` 无 project_id 字段，必填即不可实现 | 必填（ADR-053 原文，实测不可行）；伪造哨兵值（脏数据） |
| D15-3 | **`resource_id` 规范名 + `entity_id` 兼容别名双输出** | 调和 ADR-053 与 issue #992 的字段名分歧，避免两拨实现互不兼容 | 只留一个（造成 ADR/issue 实现分叉） |
| D15-4 | **#989 补丁长期保留，不因推送删除** | 其后果是**数据丢失**，不能把唯一防线押在尽力而为的推送流上 | 推送上线即删（单点依赖，断连即丢数据） |
| D15-5 | **事件帧与写作帧解码器分离** | 事件帧无 `done`（长驻不结束），复用 `StreamFrame` 解析会误判 | 复用 `api/sse.ts` 解码器（语义错配） |
| D15-6 | **全局订阅单例，非每页面订阅** | 避免 N 页面 N 条 SSE 连接；页面只注册关心 domain | 每页面各订阅（连接爆炸、失效分散） |
| D15-7 | **断连重连后全量 refetch（不等于事件补发）** | 收敛断线期间陈旧，实现简单；不引入 `Last-Event-ID` 复杂度 | 事件补发（需缓冲 + 序号，复杂度高，MVP 不值） |
| D15-8 | **不推 draft/chat/agent_run/logs** | 高频噪声或已有专属通道，避免双通道分叉 | 全量事件化（过度设计） |
| D15-9 | **`op` 只三值（create/update/delete）** | GUI 一律 FR，不需细分动作；信封保持简单 | 保留 move/set_default 等细粒度（GUI 用不上） |

### 15.15 待澄清问题（**需用户拍板**）

| # | 问题 | 选项 | 建议 |
|---|------|------|------|
| Q15-1 | **失效粒度**：事件到达后是「全量重拉」还是「局部更新」？ | A. **一律 FR 全量重拉**（本章 D15-1，复用既有 loadXxx，实现最简）；B. 逐域 LU 局部更新（省流量但需逐域推算，错漏风险高）；C. 混合（列表 FR + 高频面 LU） | **✅ 已确认（用户拍板：选项 A，2026-09-10）**——正文已按此定稿（§15.6.2 粒度裁决 / §15.14 D15-1）；LU 推算错风险 > 收益 |
| Q15-2 | **#989 类「防数据丢失」补丁是否保留**？ | A. **长期保留为最后防线**（本章 D15-4）；B. 推送验证后删除（靠推送唯一保障） | **✅ 已确认（用户拍板：选项 A，2026-09-10）**——§15.7.2 安全偏向原则为硬约束；#989 补丁保留，仅 #973（可见性类）可在推送验证后移除 |
| Q15-3 | **首批覆盖域（批次 A）范围**？ | A. **本章 §15.3.4 的 8 域**（map/map_pin/agent_template/settings/provider_config/agent/character/outline）；B. 仅 3 个爆点域（map/agent_template/settings）；C. 一次性全 17 域 | **✅ 已确认（用户拍板：选项 A，2026-09-10）**——批次 A = 8 域（§15.3.4 / §15.13） |
| Q15-4 | **批次 B（其余 15 域）是否本迭代做**？ | A. **挂 0.14.0 但视余量顺延**（批 0+A1+A2 为本迭代目标）；B. 本迭代全做完；C. 全部顺延到下迭代 | **✅ 已确认（用户拍板：选项 A，2026-09-10）**——批 0+A1+A2 为 0.14.0 目标，A3/A4+批 B 视余量顺延（§15.13） |

> **✅ 四项全部拍板（2026-09-10）**：Q15-1=A（一律 FR）/ Q15-2=A（#989 补丁保留）/ Q15-3=A（批次 A 8 域）/ Q15-4=A（批 0+A1+A2 本迭代）。Q15 与 issue #992 验收的对应：Q15-1/Q15-2 影响 §15.6/§15.7；Q15-3/Q15-4 影响 §15.13。**正文无需改动**（v1.2 定稿本即按 A 建议撰写，拍板为确认性留痕）。

---

*本章为 F23 spec v1.2 增量（§15 数据面变更统一推送）。原 §1-§14 内容不变；本章实现批独立排期（§15.13）。所有里程碑验收以 §15.12.2 为准。*
