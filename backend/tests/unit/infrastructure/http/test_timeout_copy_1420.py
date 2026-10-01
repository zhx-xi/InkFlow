"""#1420 RED 契约 —— TIMEOUT 文案不得指向不存在的 list/get 能力（方案 1：文案对齐）.

背景（issue #1420 现象）: 客户端 300s 超时返回

    {"ok": false, "error": {"code": "TIMEOUT",
     "message": "请求超时（300s）：服务端任务可能仍在进行，请稍后用 list/get 查询结果，勿直接重试"}}

但 `--history` 只给 severity_summary、CLI 无 get 用法、HTTP 侧无「按记录取报告」读端点
——**文案在承诺一个当时不存在的能力**（本单方案 2 已补上读口，但传输层文案是
**跨命令通用**的，不得指向任何单一域的能力）。

契约:
- `InkFlowHTTPClient._timeout_message(...)`（非流式 + 流式）文案不得出现
  `list` / `get` 词汇（回归断言，防再次承诺不存在的能力）。
- 保留「服务端任务可能仍在进行 … 勿直接重试」语义（用户仍被劝止盲目重试）。
- 传输层超时仍映射为 HttpApiError(status_code=0, code="TIMEOUT")，
  且经 map_http_error 后用户可见 message 同样不含 list/get。

依据: issue #1420（方案 1，本单必做项）+ specs/f34-chapter-audit/spec.md §7（v1.4）。
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel.bootstrap import KernelHandle

# patch 注入点 = 源头模块命名空间（client.py 以模块属性形态构造 AsyncClient）
HTTP_MOD = "inkflow.infrastructure.http.client.httpx.AsyncClient"
BASE_URL = "http://127.0.0.1:38291/api/v1"
TOKEN = "test-token-abc123"

# 不得出现的词汇（#1420：文案曾承诺「请稍后用 list/get 查询结果」）
_FORBIDDEN = re.compile(r"\b(list|get)\b")


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


@contextmanager
def _mock_http(handler):
    """patch 源头模块命名空间 → 真实 httpx.AsyncClient + MockTransport 轨。"""
    _real_async_client = httpx.AsyncClient  # patch 前捕获原类（防递归）

    def _factory(**kwargs):
        return _real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    with patch(HTTP_MOD, new=_factory):
        yield


def _assert_no_capability_promise(message: str) -> None:
    """回归断言：超时文案不得提及 list / get（不存在的查询能力指引）."""
    assert "list/get" not in message, f"超时文案仍在承诺 list/get: {message!r}"
    assert _FORBIDDEN.search(message) is None, (
        f"超时文案出现 list/get 词元，指向不存在的能力: {message!r}"
    )


async def test_non_stream_timeout_message_has_no_list_get() -> None:
    """非流式超时文案：不含 list/get，且保留「勿直接重试」劝止语义."""

    async with InkFlowHTTPClient(_make_handle()) as client:
        message = client._timeout_message(300.0)

    _assert_no_capability_promise(message)
    assert "请求超时" in message
    assert "300" in message
    assert "服务端任务可能仍在进行" in message
    assert "勿直接重试" in message


async def test_stream_timeout_message_has_no_list_get() -> None:
    """流式空闲超时文案：不含 list/get（SSE 分支同族收敛）."""

    async with InkFlowHTTPClient(_make_handle()) as client:
        message = client._timeout_message(300.0, stream=True)

    _assert_no_capability_promise(message)
    assert "流式响应空闲超时" in message
    assert "勿直接重试" in message


async def test_http_timeout_error_detail_has_no_list_get() -> None:
    """端到端：真实 httpx 读超时 → HttpApiError(TIMEOUT) 的 detail 不含 list/get."""

    def _handler(request):
        raise httpx.ReadTimeout("simulated read timeout", request=request)

    with _mock_http(_handler):
        async with InkFlowHTTPClient(_make_handle()) as client:
            with pytest.raises(HttpApiError) as exc_info:
                await client.post("/projects/1/chapters/2/audit", json={}, timeout=300.0)

    err = exc_info.value
    assert err.status_code == 0
    assert err.code == "TIMEOUT"
    _assert_no_capability_promise(err.detail)


async def test_timeout_user_visible_message_after_map_http_error() -> None:
    """用户可见面：map_http_error 透传的超时 message 同样不含 list/get."""

    async with InkFlowHTTPClient(_make_handle()) as client:
        detail = client._timeout_message(300.0)

    code, message = map_http_error(0, detail, "TIMEOUT")

    assert code == "TIMEOUT"
    _assert_no_capability_promise(message)
