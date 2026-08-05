"""F3 写作 API 集成测试 — Mock WritingService（不触发真实 LLM 调用）。

TDD RED 阶段：路由尚未注册，预期全部失败。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from httpx_sse import aconnect_sse

from inkflow.domain.models.writing import WritingMode, WritingResult
from inkflow.domain.ports.llm_client import TokenUsage
from inkflow.domain.ports.llm_errors import LLMRequestError


def _preset_result(mode: str) -> WritingResult:
    """预设 WritingResult — 模拟 WritingService 的返回。"""
    return WritingResult(
        content="# 试炼场风波\n\n清晨的薄雾尚未散尽，青云宗的试炼场已经人声鼎沸……",
        word_count=2347,
        mode=WritingMode(mode),
        format_valid=True,
        retry_count=1,
        model="deepseek/deepseek-chat",
        token_usage=TokenUsage(
            prompt_tokens=1820, completion_tokens=2600, total_tokens=4420
        ),
        warnings=[],
    )


@pytest.fixture
def mock_writing_service() -> MagicMock:
    """Mock WritingService — 三个方法均返回预设 WritingResult。"""
    svc = MagicMock()
    svc.generate_chapter = AsyncMock(return_value=_preset_result("generate"))
    svc.continue_writing = AsyncMock(return_value=_preset_result("continue"))
    svc.revise_content = AsyncMock(return_value=_preset_result("revise"))
    return svc


@pytest.fixture
def override_writing_service(mock_writing_service):
    """将 FastAPI 的 get_writing_service 替换为 Mock，避免真实 LLM/DB 调用。"""

    from inkflow.api.app import app
    from inkflow.api.deps import get_writing_service

    app.dependency_overrides[get_writing_service] = lambda: mock_writing_service
    yield mock_writing_service
    app.dependency_overrides.clear()


def _client():
    """构造 ASGI 测试客户端。"""
    from inkflow.api.app import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _payload() -> dict:
    return {
        "project_id": str(uuid.uuid4()),
        "chapter_id": str(uuid.uuid4()),
    }


# ── 成功路径 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_endpoint(override_writing_service):
    """POST /api/v1/writing/generate → 200 + WritingResult。"""
    body = {**_payload(), "outline": "主角首次踏入宗门试炼场，遭遇同门挑衅"}
    async with _client() as client:
        resp = await client.post("/api/v1/writing/generate", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "generate"
    assert data["word_count"] == 2347
    assert data["format_valid"] is True
    assert data["retry_count"] == 1
    assert data["model"] == "deepseek/deepseek-chat"
    assert data["token_usage"]["total_tokens"] == 4420
    assert data["warnings"] == []


@pytest.mark.asyncio
async def test_continue_endpoint(override_writing_service):
    """POST /api/v1/writing/continue → 200 + WritingResult。"""
    body = {**_payload(), "existing_content": "林尘深吸一口气，缓缓走向试炼台……" * 3}
    async with _client() as client:
        resp = await client.post("/api/v1/writing/continue", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "continue"
    assert data["word_count"] == 2347


@pytest.mark.asyncio
async def test_revise_endpoint(override_writing_service):
    """POST /api/v1/writing/revise → 200 + WritingResult。"""
    body = {
        **_payload(),
        "content": "……（原文段落内容，此处为待修订的完整段落文本，超过十个字符）",
        "feedback": "对话节奏太拖沓，删减无关寒暄",
        "target_range": "第 3 段",
    }
    async with _client() as client:
        resp = await client.post("/api/v1/writing/revise", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "revise"
    assert data["word_count"] == 2347


# ── 错误路径 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_project_not_found(
    override_writing_service, mock_writing_service
):
    """项目不存在 → 404 \"项目不存在\"。"""
    mock_writing_service.generate_chapter.side_effect = LLMRequestError("项目不存在")
    body = {**_payload(), "outline": "测试大纲"}
    async with _client() as client:
        resp = await client.post("/api/v1/writing/generate", json=body)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "项目不存在"


@pytest.mark.asyncio
async def test_generate_chapter_not_found(
    override_writing_service, mock_writing_service
):
    """章节不存在/不属于项目 → 404 \"章节不存在\"。"""
    mock_writing_service.generate_chapter.side_effect = LLMRequestError("章节不存在")
    body = {**_payload(), "outline": "测试大纲"}
    async with _client() as client:
        resp = await client.post("/api/v1/writing/generate", json=body)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "章节不存在"


@pytest.mark.asyncio
async def test_generate_validation_error(override_writing_service):
    """outline 缺失 → 422（Pydantic 验证，未到达服务层）。"""
    body = _payload()
    async with _client() as client:
        resp = await client.post("/api/v1/writing/generate", json=body)
    assert resp.status_code == 422
    errors = resp.json()["detail"]
    assert any("outline" in str(e.get("loc")) for e in errors)


@pytest.mark.asyncio
async def test_generate_llm_error_500(override_writing_service, mock_writing_service):
    """LLM 调用失败 → 500 + 通用消息（不泄漏内部细节，ADR-012）。"""
    mock_writing_service.generate_chapter.side_effect = LLMRequestError(
        "API key invalid"
    )
    body = {**_payload(), "outline": "测试大纲"}
    async with _client() as client:
        resp = await client.post("/api/v1/writing/generate", json=body)
    assert resp.status_code == 500
    assert resp.json()["detail"] == "LLM 调用失败，请稍后重试"
    assert "API key invalid" not in resp.text


# ═══════════════════════════════════════════════════════════════════════════
# Issue #104 Phase 3 覆盖率补齐：continue/revise 异常映射 + 断开分支
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_continue_llm_error_500(override_writing_service, mock_writing_service):
    """continue 端点 LLM 调用失败 → 500 通用消息（_map_service_error 非 404 分支）。"""
    mock_writing_service.continue_writing.side_effect = LLMRequestError(
        "API key invalid"
    )
    body = {**_payload(), "existing_content": "林尘深吸一口气，缓缓走向试炼台……" * 3}
    async with _client() as client:
        resp = await client.post("/api/v1/writing/continue", json=body)
    assert resp.status_code == 500
    assert resp.json()["detail"] == "LLM 调用失败，请稍后重试"


@pytest.mark.asyncio
async def test_revise_unknown_error_500(override_writing_service, mock_writing_service):
    """revise 端点未预期异常 → 500「服务器内部错误」（未知异常分支）。"""
    mock_writing_service.revise_content.side_effect = RuntimeError("boom")
    body = {
        **_payload(),
        "content": "……（原文段落内容，此处为待修订的完整段落文本，超过十个字符）",
        "feedback": "对话节奏太拖沓",
    }
    async with _client() as client:
        resp = await client.post("/api/v1/writing/revise", json=body)
    assert resp.status_code == 500
    assert resp.json()["detail"] == "服务器内部错误，请稍后重试"


@pytest.mark.asyncio
async def test_event_generator_disconnect_stops_and_closes():
    """客户端已断开 → _event_generator 立即停止并关闭 service 生成器（不泄漏任务）。"""
    from inkflow.api.routers.writing import _event_generator
    from inkflow.domain.models.writing import WritingStreamEvent

    closed = False

    async def _events():
        nonlocal closed
        try:
            yield WritingStreamEvent(delta="第一帧")
            yield WritingStreamEvent(delta="第二帧")
        finally:
            closed = True

    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=True)

    frames = [f async for f in _event_generator(request, _events())]

    assert frames == []  # 断开后不产出任何帧
    request.is_disconnected.assert_awaited()
    assert closed is True  # events.aclose() 已触发 finally


# ═══════════════════════════════════════════════════════════════════════
# F23 SSE 流式端点（spec §3/§6/§9 M4/M5）— RED 阶段：/stream 未注册 + 模型未实现
# ═══════════════════════════════════════════════════════════════════════
# 注：WritingStreamEvent 在用例内延迟导入（F23 模型未实现前保持本文件可收集、
# 既有 F3 用例全绿）；Green 阶段实现落地后可上移为模块级导入。


def _stream_stub(*events):
    """service 流式方法 mock 工厂 — 调用返回预置 WritingStreamEvent 序列的 async generator。

    设计假设: 端点调用 `svc.stream_generate(request)`（async generator 调用，不 await）→
    返回 AsyncGenerator[WritingStreamEvent, None]（spec §5.1 签名）。
    """

    async def _gen(_request):
        for ev in events:
            yield ev

    return _gen


def _stream_client():
    """构造 SSE 测试客户端 — 长超时（30s）防流式慢挂（spec §9 M4 注）。"""
    from inkflow.api.app import app

    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=httpx.Timeout(30.0),
    )


class TestStreamGenerate:
    """F23 mode=generate 流式成功路径（spec §3.1/§6.1/§9 M4）。

    设计假设:
    - 接口签名: POST /api/v1/writing/stream，body=StreamWritingRequest 判别联合（mode 必填）→
      StreamingResponse，Content-Type: text/event-stream（§3.1 响应头）
    - patch 目标: mock_writing_service.stream_generate（经 override_writing_service 注入）——
      签名 `stream_generate(request: WritingRequest) ->
      AsyncGenerator[WritingStreamEvent, None]`（§5.1）
    - 帧协议（§6.1/§6.2）: delta 帧 {"delta": str, "done": false}；done 帧 {"done": true,
      format_valid/warnings/word_count/model/token_usage}；None/空值字段省略（warnings=[] 省略）
    - 帧序列不变量: N 个 delta 拼接 == 完整内容；恰好 1 个 done 帧结尾（§6.1 不变量 2/3）
    """

    @pytest.mark.asyncio
    async def test_stream_generate_deltas(
        self, override_writing_service, mock_writing_service
    ):
        """2 delta + done 帧序列，delta 拼接 == 全文，done 帧字段完整透传。"""
        from inkflow.domain.models.writing import WritingStreamEvent

        mock_writing_service.stream_generate = _stream_stub(
            WritingStreamEvent(delta="清晨的薄雾尚未散尽，青云宗的试炼场已经"),
            WritingStreamEvent(delta="人声鼎沸……"),
            WritingStreamEvent(
                done=True,
                format_valid=True,
                warnings=[],
                word_count=2347,
                model="deepseek/deepseek-chat",
                token_usage=TokenUsage(
                    prompt_tokens=1820, completion_tokens=2600, total_tokens=4420
                ),
            ),
        )
        body = {
            **_payload(),
            "mode": "generate",
            "outline": "主角首次踏入宗门试炼场，遭遇同门挑衅",
        }
        async with (
            _stream_client() as client,
            aconnect_sse(client, "POST", "/api/v1/writing/stream", json=body) as sse,
        ):
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
            content_type = sse.response.headers["content-type"]
        assert content_type.startswith("text/event-stream")
        assert len(frames) == 3
        assert frames[0]["done"] is False
        assert frames[0]["delta"] == "清晨的薄雾尚未散尽，青云宗的试炼场已经"
        assert frames[1]["done"] is False
        assert frames[1]["delta"] == "人声鼎沸……"
        joined = "".join(f["delta"] for f in frames[:2])
        assert joined == "清晨的薄雾尚未散尽，青云宗的试炼场已经人声鼎沸……"
        done = frames[2]
        assert done["done"] is True
        assert done["format_valid"] is True
        assert done["word_count"] == 2347
        assert done["model"] == "deepseek/deepseek-chat"
        assert done["token_usage"]["total_tokens"] == 4420
        assert "delta" not in done  # §6.2 空字段省略
        assert "warnings" not in done  # §6.2 空列表省略


class TestStreamContinue:
    """F23 mode=continue 流式成功路径（spec §3.1/§9 M4）。

    设计假设: mode=continue → 判别分发到 `svc.stream_continue(request: ContinueWritingRequest)`
    （§5.1）；帧协议/响应头同 TestStreamGenerate（§6）。
    """

    @pytest.mark.asyncio
    async def test_stream_continue_deltas(
        self, override_writing_service, mock_writing_service
    ):
        """2 delta + done 帧序列，判别分发到 stream_continue。"""
        from inkflow.domain.models.writing import WritingStreamEvent

        mock_writing_service.stream_continue = _stream_stub(
            WritingStreamEvent(delta="林尘的剑光划破夜色，"),
            WritingStreamEvent(delta="试炼台上的欢呼声如潮水般涌来。"),
            WritingStreamEvent(
                done=True,
                format_valid=True,
                warnings=[],
                word_count=1800,
                model="deepseek/deepseek-chat",
                token_usage=TokenUsage(
                    prompt_tokens=900, completion_tokens=2000, total_tokens=2900
                ),
            ),
        )
        body = {
            **_payload(),
            "mode": "continue",
            "existing_content": "林尘深吸一口气，缓缓走向试炼台，全场寂静无声。"
            * 3,  # F3: ≥50 字
        }
        async with (
            _stream_client() as client,
            aconnect_sse(client, "POST", "/api/v1/writing/stream", json=body) as sse,
        ):
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
            content_type = sse.response.headers["content-type"]
        assert content_type.startswith("text/event-stream")
        joined = "".join(f["delta"] for f in frames[:2])
        assert joined == "林尘的剑光划破夜色，试炼台上的欢呼声如潮水般涌来。"
        done = frames[-1]
        assert done["done"] is True
        assert done["format_valid"] is True
        assert done["word_count"] == 1800
        assert done["model"] == "deepseek/deepseek-chat"
        assert done["token_usage"]["total_tokens"] == 2900


class TestStreamRevise:
    """F23 mode=revise 流式成功路径（spec §3.1/§5.1 注/§9 M4）。

    设计假设: mode=revise → 判别分发到 `svc.stream_revise(request: RevisionRequest)`（§5.1）；
    revise 无 FormatValidator → done 帧省略 format_valid 字段（§5.1 注 / §6.1 不变量 5）。
    """

    @pytest.mark.asyncio
    async def test_stream_revise_deltas(
        self, override_writing_service, mock_writing_service
    ):
        """2 delta + done 帧序列，done 帧无 format_valid。"""
        from inkflow.domain.models.writing import WritingStreamEvent

        mock_writing_service.stream_revise = _stream_stub(
            WritingStreamEvent(delta="修订后的段落："),
            WritingStreamEvent(delta="对话更紧凑，节奏明快。"),
            WritingStreamEvent(
                done=True,
                warnings=["未能定位目标范围…已全文修订"],
                word_count=1200,
                model="deepseek/deepseek-chat",
                token_usage=TokenUsage(
                    prompt_tokens=600, completion_tokens=1300, total_tokens=1900
                ),
            ),
        )
        body = {
            **_payload(),
            "mode": "revise",
            "content": "……（原文段落内容，此处为待修订的完整段落文本，超过十个字符）",
            "feedback": "对话节奏太拖沓，删减无关寒暄",
        }
        async with (
            _stream_client() as client,
            aconnect_sse(client, "POST", "/api/v1/writing/stream", json=body) as sse,
        ):
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
            content_type = sse.response.headers["content-type"]
        assert content_type.startswith("text/event-stream")
        joined = "".join(f["delta"] for f in frames[:2])
        assert joined == "修订后的段落：对话更紧凑，节奏明快。"
        done = frames[-1]
        assert done["done"] is True
        assert (
            "format_valid" not in done
        )  # §6.1 不变量 5：revise done 帧无 format_valid
        assert done["warnings"] == ["未能定位目标范围…已全文修订"]
        assert done["word_count"] == 1200
        assert done["model"] == "deepseek/deepseek-chat"
        assert done["token_usage"]["total_tokens"] == 1900


class TestStreamErrors:
    """F23 流式端点错误路径（spec §3.2/§7/§9 M5）。

    设计假设:
    - 流开始前（校验阶段）错误走 HTTP 状态码（§3.2）: LLMRequestError 且 message ∈
      ("项目不存在", "章节不存在")（router._NOT_FOUND_MESSAGES 常量）→ 404
      （_map_service_error 既有逻辑）；Pydantic 校验失败（含 mode 缺失/非法——判别字段必填）→ 422
    - 流中错误（已发首帧）→ SSE error 帧 `{"done": true, "error": "LLM 调用失败，请稍后重试"}`
      （§5.2 _event_generator / §7 E3，精确文案常量）
    - 客户端断开 → request.is_disconnected() → events.aclose()（§5.3/E4，不泄漏任务）
    """

    @pytest.mark.asyncio
    async def test_stream_project_not_found_http_404(
        self, override_writing_service, mock_writing_service
    ):
        """项目不存在 → 普通 HTTP 404（非 SSE），detail=「项目不存在」。"""
        mock_writing_service.stream_generate.side_effect = LLMRequestError("项目不存在")
        body = {**_payload(), "mode": "generate", "outline": "测试大纲"}
        async with _client() as client:
            resp = await client.post("/api/v1/writing/stream", json=body)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "项目不存在"
        assert "text/event-stream" not in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_stream_project_not_found_real_generator_http_404(
        self, override_writing_service, mock_writing_service
    ):
        """真实 async generator 内部校验失败 → HTTP 404（探针路径，修正 mock side_effect 盲区）。"""

        async def _gen(_request):
            raise LLMRequestError("项目不存在")
            yield  # pragma: no cover

        mock_writing_service.stream_generate = _gen
        body = {**_payload(), "mode": "generate", "outline": "测试大纲"}
        async with _client() as client:
            resp = await client.post("/api/v1/writing/stream", json=body)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "项目不存在"
        assert "text/event-stream" not in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            {**_payload(), "outline": "测试大纲"},  # mode 缺失（判别字段必填）
            {**_payload(), "mode": "bogus", "outline": "测试大纲"},  # mode 非法
            {**_payload(), "mode": "generate", "outline": "   "},  # outline 空白
            {  # max_words < min_words（F3 模型校验继承）
                **_payload(),
                "mode": "generate",
                "outline": "测试大纲",
                "min_words": 3000,
                "max_words": 2000,
            },
        ],
        ids=["mode_missing", "mode_invalid", "outline_empty", "max_words_lt_min_words"],
    )
    async def test_stream_validation_422(self, override_writing_service, body):
        """请求体校验失败（mode 缺失/非法、outline 空、字数倒挂）→ 普通 HTTP 422。"""
        async with _client() as client:
            resp = await client.post("/api/v1/writing/stream", json=body)
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    @pytest.mark.asyncio
    async def test_stream_llm_error_mid_stream_error_frame(
        self, override_writing_service, mock_writing_service
    ):
        """流中 LLM 失败 → SSE error 帧（done=true + 精确文案），流结束。"""
        from inkflow.domain.models.writing import WritingStreamEvent

        async def _gen_with_error(_request):
            yield WritingStreamEvent(delta="清晨的薄雾尚未散尽")
            raise LLMRequestError("upstream provider timeout")

        mock_writing_service.stream_generate = _gen_with_error
        body = {**_payload(), "mode": "generate", "outline": "测试大纲"}
        async with (
            _stream_client() as client,
            aconnect_sse(client, "POST", "/api/v1/writing/stream", json=body) as sse,
        ):
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
        assert len(frames) == 2
        assert frames[0]["delta"] == "清晨的薄雾尚未散尽"
        assert frames[0]["done"] is False
        assert frames[1]["done"] is True
        assert frames[1]["error"] == "LLM 调用失败，请稍后重试"
        assert "format_valid" not in frames[1]  # §6.1 不变量 4：error 帧省略结果字段

    @pytest.mark.asyncio
    async def test_stream_first_delta_then_llm_error_error_frame(
        self, override_writing_service, mock_writing_service
    ):
        """探针消费首 delta 后流中 LLM 失败 → delta 帧 + error 帧（§7 E3，探针不破坏流中语义）。"""
        from inkflow.domain.models.writing import WritingStreamEvent

        async def _gen(_request):
            yield WritingStreamEvent(delta="探针首帧")
            yield WritingStreamEvent(delta="第二帧")
            raise LLMRequestError("upstream provider timeout")

        mock_writing_service.stream_generate = _gen
        body = {**_payload(), "mode": "generate", "outline": "测试大纲"}
        async with (
            _stream_client() as client,
            aconnect_sse(client, "POST", "/api/v1/writing/stream", json=body) as sse,
        ):
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
            content_type = sse.response.headers["content-type"]
        assert content_type.startswith("text/event-stream")
        assert len(frames) == 3
        assert frames[0]["delta"] == "探针首帧"
        assert frames[0]["done"] is False
        assert frames[1]["delta"] == "第二帧"
        assert frames[1]["done"] is False
        assert frames[2]["done"] is True
        assert frames[2]["error"] == "LLM 调用失败，请稍后重试"
        assert "format_valid" not in frames[2]  # §6.1 不变量 4：error 帧省略结果字段

    @pytest.mark.asyncio
    async def test_stream_client_disconnect_closes_generator(
        self, override_writing_service, mock_writing_service
    ):
        """客户端提前断开（aconnect_sse 上下文退出）→ service 生成器被 close（§5.3/E4）。"""
        from inkflow.domain.models.writing import WritingStreamEvent

        closed = False

        async def _long_stream(_request):
            nonlocal closed
            try:
                for i in range(50):
                    yield WritingStreamEvent(delta=f"片段{i}")
            finally:
                closed = True

        mock_writing_service.stream_generate = _long_stream
        body = {**_payload(), "mode": "generate", "outline": "测试大纲"}
        async with (
            _stream_client() as client,
            aconnect_sse(client, "POST", "/api/v1/writing/stream", json=body) as sse,
        ):
            async for _ev in sse.aiter_sse():
                break  # 消费首帧后立即退出 = 客户端断开
        assert closed is True
