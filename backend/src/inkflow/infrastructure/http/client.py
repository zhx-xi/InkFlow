"""内核 HTTP 传输客户端 —— Issue #169 CLI 恒经 HTTP 路由改造（ADR-030 ② D1=A）。

纯基础设施层：为 CLI / MCP / skills 复用提供统一的内核 HTTP 访问。
禁 import inkflow.cli（层间依赖单向：cli → http）。
"""

from __future__ import annotations

import json as jsonlib
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from types import TracebackType
from typing import cast

import httpx

from inkflow.infrastructure.kernel.bootstrap import KernelHandle

_SSE_DATA_PREFIX = "data: "


@dataclass
class HttpApiError(Exception):
    """内核 HTTP 非 2xx 响应异常。

    普通 dataclass（非 frozen）：stream_sse 非 2xx 路径在 contextlib 退出时会对异常
    赋值 `exc.__traceback__`，frozen 的 __setattr__ 会抛 FrozenInstanceError 遮蔽原异常。
    code = 响应头 X-InkFlow-Error-Code 原始值（无头 → None），不是 map_http_error 输出。
    """

    status_code: int
    detail: str
    code: str | None = None


def _extract_detail(response: httpx.Response) -> str:
    """从响应 body 提取 "detail" 键值；body 非 dict / 无 detail / 非 JSON → ""。"""
    try:
        body = response.json()
    except Exception:
        return ""
    if not isinstance(body, dict):
        return ""
    detail = body.get("detail")
    if detail is None:
        return ""
    return detail if isinstance(detail, str) else str(detail)


def _filter_none_params(params: dict | None) -> dict | None:
    """过滤值为 None 的查询参数（#254：httpx 会把 None 编码为空串 → FastAPI 解析失败）.

    None 过滤，显式空串保留（调用方显式传 "" 是其意图）.
    """
    if not params:
        return params
    return {k: v for k, v in params.items() if v is not None}


class InkFlowHTTPClient:
    """内核 HTTP 客户端：base_url + X-InkFlow-Token 请求头 + 请求/SSE 流式方法。"""

    def __init__(self, handle: KernelHandle, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{handle.port}/api/v1",
            headers={"X-InkFlow-Token": handle.token},
            timeout=timeout,
        )

    async def __aenter__(self) -> InkFlowHTTPClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def get(self, path, *, params=None, json=None) -> dict:
        return await self._request("GET", path, params=params, json=json)

    async def post(self, path, *, params=None, json=None) -> dict:
        return await self._request("POST", path, params=params, json=json)

    async def patch(self, path, *, params=None, json=None) -> dict:
        return await self._request("PATCH", path, params=params, json=json)

    async def delete(self, path, *, params=None, json=None) -> dict:
        return await self._request("DELETE", path, params=params, json=json)

    async def _request(self, method, path, *, params=None, json=None) -> dict:
        response = await self._client.request(
            method, path, params=_filter_none_params(params), json=json
        )
        if not 200 <= response.status_code < 300:
            raise HttpApiError(
                status_code=response.status_code,
                detail=_extract_detail(response),
                code=response.headers.get("X-InkFlow-Error-Code"),
            )
        return cast(dict, response.json())

    async def get_raw(self, path, *, params=None) -> str:
        """GET 请求并返回原始响应文本（F21 导出下载，非 JSON 信封）。

        与 _request 的区别: _request 强制 response.json() 解析，无法处理
        text/plain 字节流（TXT 导出）；本方法返回 response.text（UTF-8 解码）。

        Args:
            path: API 路径（不含 base_url 前缀）.
            params: 查询参数 dict（可选）.

        Returns:
            响应文本（2xx；UTF-8 解码）.

        Raises:
            HttpApiError: 非 2xx（与 _request 同规则: detail 提取 + X-InkFlow-Error-Code 头）.
        """
        response = await self._client.get(path, params=_filter_none_params(params))
        if not 200 <= response.status_code < 300:
            raise HttpApiError(
                status_code=response.status_code,
                detail=_extract_detail(response),
                code=response.headers.get("X-InkFlow-Error-Code"),
            )
        return response.text

    async def post_file(
        self, path, *, data: dict, filename: str, content: bytes, params=None
    ) -> dict:
        """multipart 表单上传（F36 地图图片上传；files={'file': (filename, content)}）."""
        return await self._request_file(
            "POST", path, data=data, filename=filename, content=content, params=params
        )

    async def put_file(
        self, path, *, data: dict, filename: str, content: bytes, params=None
    ) -> dict:
        """multipart 表单上传（F36 地图换图 PUT）."""
        return await self._request_file(
            "PUT", path, data=data, filename=filename, content=content, params=params
        )

    async def get_bytes(self, path, *, params=None) -> bytes:
        """GET 原始字节（F36 地图图片下载；非 JSON 响应）."""
        response = await self._client.request("GET", path, params=_filter_none_params(params))
        if not 200 <= response.status_code < 300:
            raise HttpApiError(
                status_code=response.status_code,
                detail=_extract_detail(response),
                code=response.headers.get("X-InkFlow-Error-Code"),
            )
        return response.content

    async def _request_file(self, method, path, *, data, filename, content, params) -> dict:
        """multipart 请求（错误处理同 _request）."""
        files = {"file": (filename, content)}
        response = await self._client.request(
            method, path, params=_filter_none_params(params), data=data, files=files
        )
        if not 200 <= response.status_code < 300:
            raise HttpApiError(
                status_code=response.status_code,
                detail=_extract_detail(response),
                code=response.headers.get("X-InkFlow-Error-Code"),
            )
        return cast(dict, response.json())

    async def stream_sse(self, path, *, json=None) -> AsyncGenerator[dict, None]:
        """POST + SSE 流式消费：`data: {json}` 帧逐行解析并 yield 原样 dict。

        空行与其它无前缀行跳过；流开始前非 2xx 抛 HttpApiError；流中断抛 HttpApiError。
        """
        async with self._client.stream("POST", path, json=json) as response:
            if not 200 <= response.status_code < 300:
                raise HttpApiError(
                    status_code=response.status_code,
                    detail=_extract_detail(response),
                    code=response.headers.get("X-InkFlow-Error-Code"),
                )
            try:
                async for line in response.aiter_lines():
                    if not line.startswith(_SSE_DATA_PREFIX):
                        continue
                    yield jsonlib.loads(line.removeprefix(_SSE_DATA_PREFIX))
            except httpx.HTTPError as exc:
                raise HttpApiError(
                    status_code=0,
                    detail=str(exc),
                    code="STREAM_INTERRUPTED",
                ) from exc
