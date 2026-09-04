"""#926 传输层超时分类 RED 契约测试 —— 覆盖契约 §4 文件 B（B-R1..R7、B-G1..G4）。

覆盖 `inkflow.infrastructure.http` 的传输层超时分类：httpx.TimeoutException →
HttpApiError(status_code=0, code="TIMEOUT", detail=超时文案)（契约 §1-D1/D3）与
map_http_error 的 TIMEOUT 分支（契约 §2.74）、LLM_TASK_TIMEOUT 常量导出（§1-D2）。

── 触发形态说明（防 flaky 实证）───────────────────────────────
⚠️ 实证（httpx 0.28.1，`MockTransport.handle_async_request` 直接在事件循环调用 handler 且
响应体已被完整物化）：`time.sleep()` + `timeout=0.05` 在 MockTransport 轨**不会**产生
httpx.ReadTimeout（mock 是纯进程内传输，无真实连接/字节流超时机）。故非流式超时用例改用
handler **直接 raise httpx.ReadTimeout**（确定性模拟 httpx 对真实慢响应的超时抛出），
流式超时用例用 `httpx.AsyncByteStream` 先 yield 一帧再 raise httpx.ReadTimeout
（镜像 TestStreamSseInterrupted 的流中断形态，走真实 stream_sse 消费路径），
二者都是绿色实现「catch httpx.TimeoutException → HttpApiError(TIMEOUT)」的确定性触发源，
绝非赌时序。

── RED/GREEN 判据 ──────────────────────────────────────────
【R】当前必 FAIL：非流式路径 httpx.ReadTimeout 直接抛出（未捕获）；流式被 STREAM_INTERRUPTED
分支吞成 code=STREAM_INTERRUPTED + 空 detail；map_http_error 无 TIMEOUT 分支返回 INTERNAL_ERROR；
LLM_TASK_TIMEOUT 未导出。
【G】当前应 PASS（守护既有行为，防误伤）：per-request timeout、非超时异常传播、常规 2xx/404/500、
既有映射表回归。

── 测试约定 ────────────────────────────────────────────────
- KernelHandle 真实 frozen dataclass 构造（inkflow.infrastructure.kernel.bootstrap）。
- patch 注入点 = 源头模块命名空间 `inkflow.infrastructure.http.client.httpx.AsyncClient`
  （client.py 以模块属性形态构造 AsyncClient；禁止 from-import，否则 patch 不生效）。
- detail/code/status_code 经 HttpApiError dataclass 三字段断言（§1 红线）。
- 超时值一律字面 0.05（客户端默认），断言 detail 子串「请求超时」+「0.05」，勿锁全句
  （§1-D3 模板由实现侧定稿）。

禁改任何既有文件与 src/；本文件仅落 new 测试，不改实现。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel.bootstrap import KernelHandle

# patch 注入点 = 源头模块命名空间（见文件头契约 §7）
HTTP_MOD = "inkflow.infrastructure.http.client.httpx.AsyncClient"

BASE_URL = "http://127.0.0.1:38291/api/v1"
TOKEN = "test-token-abc123"


def _make_handle() -> KernelHandle:
    """F30 KernelHandle 真实构造（frozen dataclass）。"""
    return KernelHandle(
        port=38291,
        token=TOKEN,
        pid=4242,
        version="0.1.0",
        started_at=datetime(2026, 8, 7, tzinfo=UTC),
        reused=True,
    )


@pytest.fixture
def handle() -> KernelHandle:
    return _make_handle()


@contextmanager
def _mock_http(handle: KernelHandle, handler):
    """patch 源头模块命名空间 → 真实 httpx.AsyncClient + MockTransport 轨
    （镜像 test_http_client.py）。

    yield 捕获到的 AsyncClient 构造 kwargs 列表；客户端在 with 块内**内联**构造（可传 timeout）。
    ⚠️ _factory 必须调用捕获的原类（_real_async_client）而非受 patch 影响的属性访问（防递归）。
    """
    captured: list[dict] = []
    _real_async_client = httpx.AsyncClient  # patch 前捕获原类（防递归）

    def _factory(**kwargs):
        captured.append(kwargs)
        return _real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    with patch(HTTP_MOD, new=_factory):
        yield captured


def _json_response(status: int, payload: dict, headers: dict | None = None) -> httpx.Response:
    """构造带 request 的 httpx.Response（httpx 校验要求）。"""
    return httpx.Response(
        status, json=payload, headers=headers, request=httpx.Request("GET", BASE_URL)
    )


class TestTimeoutClassification:
    """传输层超时分类：httpx.TimeoutException → HttpApiError(TIMEOUT)（契约 §1-D1/D3）。"""

    async def test_post_read_timeout_maps_to_timout(self, handle):
        """【R】B-R1: post 读超时 → HttpApiError(status_code=0, code="TIMEOUT",
        detail 非空含「请求超时」+「0.05」).

        契约 §4-B-R1 / §1-D1 / §1-D3。
        RED 现状: httpx.ReadTimeout 直接从 `_request` 抛出（无 try/except TimeoutException）
        → 非 HttpApiError → FAIL。
        """
        def _handler(request):
            raise httpx.ReadTimeout("simulated read timeout", request=request)

        with _mock_http(handle, _handler):
            async with InkFlowHTTPClient(handle, timeout=0.05) as client:
                with pytest.raises(HttpApiError) as exc_info:
                    await client.post("/llm/long", json={"project_id": "p1"})

        err = exc_info.value
        assert err.status_code == 0
        assert err.code == "TIMEOUT"
        assert err.detail, "detail 不得为空"
        assert "超时" in err.detail
        assert "0.05" in err.detail

    async def test_get_read_timeout_maps_to_timout(self, handle):
        """【R】B-R2: get 读超时 → HttpApiError(0, TIMEOUT)
        （map_http_error/stream_sse 同族面全量收敛）.

        契约 §4-B-R2 / §1-D1。
        RED 现状: httpx.ReadTimeout 直接抛出（非 HttpApiError）→ FAIL。
        """
        def _handler(request):
            raise httpx.ReadTimeout("simulated read timeout", request=request)

        with _mock_http(handle, _handler):
            async with InkFlowHTTPClient(handle, timeout=0.05) as client:
                with pytest.raises(HttpApiError) as exc_info:
                    await client.get("/llm/long")

        err = exc_info.value
        assert err.status_code == 0
        assert err.code == "TIMEOUT"
        assert err.detail, "detail 不得为空"
        assert "超时" in err.detail
        assert "0.05" in err.detail

    async def test_patch_read_timeout_maps_to_timout(self, handle):
        """【R】B-R3: patch 读超时 → HttpApiError(0, TIMEOUT)（对称补齐 timeout 参数后同族收敛）.

        契约 §4-B-R3 / §1-D1。
        RED 现状: httpx.ReadTimeout 直接抛出（非 HttpApiError）→ FAIL。
        """
        def _handler(request):
            raise httpx.ReadTimeout("simulated read timeout", request=request)

        with _mock_http(handle, _handler):
            async with InkFlowHTTPClient(handle, timeout=0.05) as client:
                with pytest.raises(HttpApiError) as exc_info:
                    await client.patch("/llm/long/p1", json={"x": 1})

        err = exc_info.value
        assert err.status_code == 0
        assert err.code == "TIMEOUT"
        assert err.detail, "detail 不得为空"
        assert "超时" in err.detail
        assert "0.05" in err.detail

    async def test_delete_read_timeout_maps_to_timout(self, handle):
        """【R】B-R4: delete 读超时 → HttpApiError(0, TIMEOUT)（对称补齐 timeout 参数后同族收敛）.

        契约 §4-B-R4 / §1-D1。
        RED 现状: httpx.ReadTimeout 直接抛出（非 HttpApiError）→ FAIL。
        """
        def _handler(request):
            raise httpx.ReadTimeout("simulated read timeout", request=request)

        with _mock_http(handle, _handler):
            async with InkFlowHTTPClient(handle, timeout=0.05) as client:
                with pytest.raises(HttpApiError) as exc_info:
                    await client.delete("/llm/long/p1")

        err = exc_info.value
        assert err.status_code == 0
        assert err.code == "TIMEOUT"
        assert err.detail, "detail 不得为空"
        assert "超时" in err.detail
        assert "0.05" in err.detail

    async def test_post_per_request_timeout_override_returns_200(self, handle):
        """【G】B-R5: post(timeout=5.0) 覆盖客户端默认 0.05 → 慢 handler 仍正常 200 返回.

        契约 §4-B-R5（per-request 覆盖生效，而非全局 0.05/30.0）。
        现即 PASS（post 已具 timeout 参数透传，mock 轨超时惰性）→ 守护不误伤。
        """
        def _handler(request):
            time.sleep(0.3)
            return _json_response(200, {"ok": True, "id": "p1"})

        with _mock_http(handle, _handler):
            async with InkFlowHTTPClient(handle, timeout=0.05) as client:
                result = await client.post(
                    "/llm/long", json={"project_id": "p1"}, timeout=5.0
                )

        assert result == {"ok": True, "id": "p1"}

    async def test_stream_sse_idle_timeout_maps_to_timout(self, handle):
        """【R】B-R6: stream_sse 读空闲超时 → HttpApiError(code="TIMEOUT",
        detail 含「流式响应空闲超时」).

        契约 §4-B-R6 / §1-D3（流式前缀模板）。
        RED 现状: httpx.ReadTimeout 落入 `except httpx.HTTPError`
        → code=STREAM_INTERRUPTED + 空 detail → FAIL。
        """
        class _SlowIdleStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"done": false, "delta": "part"}\n\n'
                raise httpx.ReadTimeout("simulated stream idle timeout")

        def _handler(request):
            return httpx.Response(
                200,
                stream=_SlowIdleStream(),
                headers={"content-type": "text/event-stream"},
                request=request,
            )

        with _mock_http(handle, _handler):
            async with InkFlowHTTPClient(handle, timeout=0.05) as client:
                with pytest.raises(HttpApiError) as exc_info:
                    async for _frame in client.stream_sse("/writing/stream", json={"x": 1}):
                        pass

        err = exc_info.value
        assert err.status_code == 0
        assert err.code == "TIMEOUT"
        assert err.detail, "detail 不得为空"
        assert "流式响应空闲超时" in err.detail

    async def test_connect_error_propagates_unmapped(self, handle):
        """【G】B-G1: httpx.ConnectError 原样传播（只转 TimeoutException，不误伤连接错误）.

        契约 §4-B-G1（非超时异常不得被归类为 TIMEOUT）。
        现即 PASS（当前实现不 catch ConnectError，GREEN 的 `_send` 同样 only catch
        TimeoutException）→ 守护。
        """
        def _handler(request):
            raise httpx.ConnectError("connection refused")

        with _mock_http(handle, _handler):
            async with InkFlowHTTPClient(handle) as client:
                with pytest.raises(httpx.ConnectError):
                    await client.get("/projects")

    async def test_normal_2xx_behavior_unchanged(self, handle):
        """【G】B-G2: 正常 2xx 行为零变化 → 返回 JSON body（不被超时逻辑干扰）.

        契约 §4-B-G2。
        现即 PASS → 守护。
        """
        body = {"ok": True, "data": [{"id": "p1"}]}

        def _handler(request):
            return _json_response(200, body)

        with _mock_http(handle, _handler):
            async with InkFlowHTTPClient(handle) as client:
                result = await client.get("/projects")

        assert result == body

    async def test_normal_404_behavior_unchanged(self, handle):
        """【G】B-G2: 404 行为零变化 → HttpApiError(404, detail)（超时改造不改变非 2xx 提取）.

        契约 §4-B-G2。
        现即 PASS → 守护。
        """
        def _handler(request):
            return _json_response(404, {"detail": "项目不存在"})

        with _mock_http(handle, _handler):
            async with InkFlowHTTPClient(handle) as client:
                with pytest.raises(HttpApiError) as exc_info:
                    await client.get("/projects/999")

        err = exc_info.value
        assert err.status_code == 404
        assert err.detail == "项目不存在"
        assert err.code is None

    async def test_normal_500_behavior_unchanged(self, handle):
        """【G】B-G2: 500 行为零变化 → HttpApiError(500, detail)（超时改造不改变非 2xx 提取）.

        契约 §4-B-G2。
        现即 PASS → 守护。
        """
        def _handler(request):
            return _json_response(500, {"detail": "内部错误"})

        with _mock_http(handle, _handler):
            async with InkFlowHTTPClient(handle) as client:
                with pytest.raises(HttpApiError) as exc_info:
                    await client.get("/projects/999")

        err = exc_info.value
        assert err.status_code == 500
        assert err.detail == "内部错误"


class TestMapHttpErrorTimeout:
    """map_http_error 的 TIMEOUT 分支（契约 §2.74）与既有映射表回归（spec §5.3）。"""

    @pytest.mark.parametrize(
        ("detail", "expected_message"),
        [
            ("", "请求超时"),
            (
                "请求超时（300s）：服务端任务可能仍在进行，请稍后用 list/get 查询结果，勿直接重试",
                "请求超时（300s）：服务端任务可能仍在进行，请稍后用 list/get 查询结果，勿直接重试",
            ),
            (
                "请求超时（0.05s）：服务端任务可能仍在进行，请稍后用 list/get 查询结果，勿直接重试",
                "请求超时（0.05s）：服务端任务可能仍在进行，请稍后用 list/get 查询结果，勿直接重试",
            ),
        ],
    )
    def test_map_http_error_timeout(self, detail, expected_message):
        """【R】B-R7: map_http_error(0, detail, "TIMEOUT") → ("TIMEOUT", 兜底或透传 detail).

        契约 §4-B-R7 / §1-D1 / §2.74：`if header_code == "TIMEOUT":
        return "TIMEOUT", detail or "请求超时"`。
        RED 现状: 无 TIMEOUT 分支 → 落入兜底 ("INTERNAL_ERROR", …) → FAIL。
        """
        code, message = map_http_error(0, detail, "TIMEOUT")
        assert code == "TIMEOUT"
        assert message == expected_message

    @pytest.mark.parametrize(
        ("status_code", "header_code", "expected_code", "expected_message"),
        [
            (404, None, "NOT_FOUND", "资源不存在"),
            (422, None, "VALIDATION_ERROR", "参数校验失败"),
            (401, None, "CONFIG_ERROR", "鉴权失败"),
            (403, None, "INTERNAL_ERROR", "无权限"),
            (500, "LLM_ERROR", "LLM_ERROR", "内部错误（无详情）"),
            (500, None, "INTERNAL_ERROR", "内部错误（无详情）"),
        ],
    )
    def test_map_http_error_existing_table_regression(
        self, status_code, header_code, expected_code, expected_message
    ):
        """【G】B-G3: 既有映射表回归（404/422/401/403/500+LLM_ERROR/500 无头）零变化.

        契约 §4-B-G3 / spec §5.3（加 TIMEOUT 分支不得污染既有六组）。
        现即 PASS → 守护。
        """
        code, message = map_http_error(status_code, "", header_code)
        assert code == expected_code
        assert message == expected_message


class TestSharedTimeoutConstant:
    """LLM_TASK_TIMEOUT 共享常量导出契约（§1-D2）。"""

    def test_llm_task_timeout_constant_exported(self):
        """【R】B-G4: LLM_TASK_TIMEOUT 从 inkflow.infrastructure.http 导出且 == 300.0.

        契约 §4-B-G4 / §1-D2（常量定义于 `infrastructure/http/__init__.py`
        并导出，值对齐 #274 的 300s）。
        RED 现状: __init__.py 未定义/未导出该常量 → 属性访问 AttributeError → FAIL
        （常量新增，RED 期必红）。
        """
        import inkflow.infrastructure.http as http_mod

        assert http_mod.LLM_TASK_TIMEOUT == 300.0
