"""InkFlow HTTP 客户端测试 — Issue #169 CLI 恒经 HTTP 路由改造（ADR-030 ② D1=A，RED 阶段测试契约）。

覆盖 `inkflow.infrastructure.http` 三件套：InkFlowHTTPClient（get/post/patch/delete/
stream_sse + async 上下文管理器）、HttpApiError、map_http_error。全部请求经
httpx.MockTransport 轨（走真实 httpx 客户端逻辑、零网络），**绝不**发起真实 HTTP 请求。

── GREEN 实现契约（backend/src/inkflow/infrastructure/http/ 必须满足）────────

1. 模块与导出（infrastructure/http/__init__.py）：
   - 导出 InkFlowHTTPClient / HttpApiError / map_http_error 三符号——本文件顶部
     from-import 即导出契约，缺一即 ImportError。
   - 文件布局：client.py（InkFlowHTTPClient + HttpApiError）、errors.py（map_http_error）。
   - ⚠️ http 包任何模块禁止 import inkflow.cli（层间依赖单向：cli → http，测试 15 守护）。

2. HttpApiError（client.py 内，`@dataclass`，**不 frozen**）：
   - 字段：status_code: int / detail: str / code: str | None = None；继承 Exception。
   - code 语义 = 响应头 X-InkFlow-Error-Code 的**原始值**（无头 → None）；**不是**
     map_http_error 的 F7 输出（F7 映射由命令层捕获 HttpApiError 后调用，见 §6）。
   - ⚠️ frozen 契约修正（模拟 GREEN 实测，load-bearing）：任务书原稿为
     `@dataclass(frozen=True)`，但 frozen 异常在 stream_sse 非 2xx 路径**必然被遮蔽**——
     httpx `async with client.stream(...)` 基于 contextlib，异常跨出时 contextlib 在
     Python 层执行 `exc.__traceback__ = traceback`（contextlib.py:268），frozen 的
     __setattr__ 抛 FrozenInstanceError 盖掉原 HttpApiError（实测 traceback 证据）。
     故契约改为普通 dataclass（与项目既有错误类先例 kernel_errors.py 一致，后者为
     纯 Exception 子类）。

3. InkFlowHTTPClient 构造（client.py）：
   - 签名：`__init__(self, handle, timeout: float = 30.0)`；handle 为 F30 KernelHandle
     （frozen dataclass：port/token/pid/version/started_at/reused——本文件真实构造）。
   - base_url 推导：`f"http://127.0.0.1:{handle.port}/api/v1"`（测试 1 守护完整请求 URL）。
   - 请求头：X-InkFlow-Token: handle.token（每次请求都携带，测试 2 守护）。
   - timeout 参数以 **float 原样**传给 httpx.AsyncClient(timeout=...)，默认 30.0
     （测试 18 守护；禁止包装成 httpx.Timeout 等其它形态）。
   - 支持 async 上下文管理器：`async with InkFlowHTTPClient(handle) as client`，退出时
     关闭 httpx 连接池（await aclose，测试 17 守护）。AsyncClient 可在 __init__ 或
     __aenter__ 惰性创建——本文件统一 async with 形态，两种实现均兼容。

4. 请求方法语义（get/post/patch/delete，均为
   `async def X(self, path, *, params=None, json=None) -> dict`）：
   - 2xx → 返回响应 JSON body 原样 dict（**无信封包装**、不增删键，测试 3 守护）。
   - 非 2xx → raise HttpApiError：
       detail 提取 = resp.json() 的 "detail" 键值（body 为 dict 且含 detail 键时），
       否则 ""；code = resp.headers.get("X-InkFlow-Error-Code")（无头 → None）。
     （测试 8/9 守护；提取规则对 stream_sse 同样适用）

5. stream_sse（`async def stream_sse(self, path, *, json=None)
   -> AsyncGenerator[dict, None]`）：
   - 非 2xx → 在 yield 任何帧之前 raise HttpApiError（测试 13 守护）。
   - 2xx → 按行解析响应体：以 "data: " 前缀开头的行 → 去掉前缀后 json.loads →
     yield 原始帧 dict（不做包装/规范化）；空行与其它无前缀行跳过（测试 11/12 守护）。
   - 帧 JSON 形状与后端 F23（api/routers/writing.py `_encode_sse`）对齐：
     delta 帧 {"done": false, "delta": "..."}；done 帧 {"done": true, "format_valid": ...,
     "warnings": [...], "word_count": ..., "model": ..., "token_usage": {...}}——原样透传。
   - ⚠️ 实现陷阱（模拟 GREEN 实测）：签名参数名 `json=None` 会遮蔽 json 模块——帧解析
     用 `json.loads` 前必须别名导入（`import json as jsonlib`），否则 AttributeError。

6. map_http_error（errors.py）：
   - 签名：`map_http_error(status_code: int, detail: str, header_code: str | None)
     -> tuple[str, str]`，返回 (F7 错误码, 展示消息)；展示消息 = detail 原样透传。
   - 映射表（spec §5.3，测试 10 参数化全表守护）：
       404              → ("NOT_FOUND", detail)
       422              → ("VALIDATION_ERROR", detail)
       401              → ("CONFIG_ERROR", detail)
       500 + LLM_ERROR  → ("LLM_ERROR", detail)
       500 + None       → ("INTERNAL_ERROR", detail)
       其它状态码       → ("INTERNAL_ERROR", detail)

7. patch 注入点（本文件全部用例）：
   - patch 目标 = 源头模块命名空间 `inkflow.infrastructure.http.client.httpx.AsyncClient`。
   - client.py 必须以 **`import httpx` 模块属性访问形态**构造 AsyncClient
     （`httpx.AsyncClient(base_url=..., headers=..., timeout=...)`）；**禁止**
     `from httpx import AsyncClient`（from-import 固化绑定 → patch 不生效 → 全文件 ERROR）。
   - 命令层测试（后续文件）patch 命令模块自身名字——本文件不涉及。

── RED 形态说明 ─────────────────────────────────────────
本文件顶部 from-import 尚未实现的 `inkflow.infrastructure.http` → 收集期
ModuleNotFoundError（`collected 0 items / 1 error`，pytest exit 2）——全新模块整组
RED 的预期形态；GREEN 落地后整文件自动收集转绿。

⚠️ import 排序说明：RED 阶段 ruff 因 http 模块不可解析将其归类 third-party（I001
建议把 `from inkflow.infrastructure.http import ...` 并入 pytest 块）——**不要**
`ruff --fix` 机械修复：GREEN 模块落地后 ruff 会重新归类 first-party 并反向再报 I001
（先例 test_cli_kernel.py，实测两头脏）；保持三段结构，GREEN 后自动消解。

⚠️ 测试 16（命令层 import 面收敛）跨批语义：该断言针对**命令层改造**（后续 GREEN 批，
project.py 等命令改走 HTTP client）。http 模块落地但命令层未改造时，project.py 仍直连
domain.services → 该用例 FAIL 属预期（RED 阶段文件整体不收集，无单用例结果）；命令层
改造完成后转绿。父侧验证 http 模块 GREEN 时请按此口径判定。

── 测试约定 ──────────────────────────────────────────────
- KernelHandle 用真实 frozen dataclass 构造（inkflow.infrastructure.kernel.bootstrap），
  避免 SimpleNamespace 与 F30 契约漂移。
- 请求测试统一 `async with InkFlowHTTPClient(handle) as client` 形态（兼容 AsyncClient
  在 __init__ 或 __aenter__ 创建两种实现，见契约 §3）。
- MockTransport handler 内只**记录**不断言（seen 列表），断言在请求完成后进行——
  失败信息更清晰。
"""

from __future__ import annotations

import importlib
import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from inkflow.infrastructure.http import HttpApiError, InkFlowHTTPClient, map_http_error
from inkflow.infrastructure.kernel.bootstrap import KernelHandle

# patch 注入点 = 源头模块命名空间（见文件头契约 §7）
HTTP_MOD = "inkflow.infrastructure.http.client.httpx.AsyncClient"

# 契约基线：handle.port=38291 → base_url；handle.token → 请求头（见文件头契约 §3）
BASE_URL = "http://127.0.0.1:38291/api/v1"
TOKEN = "test-token-abc123"


def _make_handle() -> KernelHandle:
    """F30 KernelHandle 真实构造（frozen dataclass，字段见文件头契约 §3）。"""
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
    """patch 源头模块命名空间 → 真实 httpx.AsyncClient + MockTransport 轨（契约 §7）。

    yield (client 工厂, 构造 kwargs 捕获列表)；patch 在 with 块内全程生效。
    ⚠️ _factory 必须调用**捕获的原类**（_real_async_client）而非 `httpx.AsyncClient`
    属性访问——patch 在真实 httpx 模块上替换同名属性，属性访问会无限递归。
    """
    captured: list[dict] = []
    _real_async_client = httpx.AsyncClient  # patch 前捕获原类（防递归）

    def _factory(**kwargs):
        captured.append(kwargs)
        return _real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    with patch(HTTP_MOD, new=_factory):
        yield lambda: InkFlowHTTPClient(handle), captured


def _json_response(status: int, payload: dict, headers: dict | None = None) -> httpx.Response:
    """构造带 request 的 httpx.Response（httpx 校验要求）。"""
    return httpx.Response(
        status, json=payload, headers=headers, request=httpx.Request("GET", BASE_URL)
    )


class TestBaseUrlAndToken:
    """base_url 推导与 token 请求头（契约 §3）。"""

    async def test_base_url_from_handle_port(self, handle):
        """GET /projects → 完整请求 URL = http://127.0.0.1:38291/api/v1/projects。"""
        seen: list[str] = []

        def _handler(request):
            seen.append(str(request.url))
            return _json_response(200, {"ok": True, "data": []})

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                await client.get("/projects")
        assert seen == [f"{BASE_URL}/projects"]

    async def test_token_header_on_every_request(self, handle):
        """每次请求都携带 X-InkFlow-Token: handle.token（get + post 双请求守护）。"""
        seen: list[tuple[str, str | None]] = []

        def _handler(request):
            seen.append((request.method, request.headers.get("X-InkFlow-Token")))
            return _json_response(200, {"ok": True})

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                await client.get("/projects")
                await client.post("/projects", json={"name": "示例"})
        assert seen == [("GET", TOKEN), ("POST", TOKEN)]


class TestRequestMethods:
    """四个请求方法的 URL/方法/json/params 语义（契约 §4）。"""

    async def test_get_returns_json_body(self, handle):
        """2xx → 返回响应 JSON body 原样 dict（无信封包装、不增删键）。"""
        body = {"ok": True, "data": [{"id": "p1", "name": "示例"}]}

        def _handler(request):
            return _json_response(200, body)

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                result = await client.get("/projects")
        assert result == body

    async def test_get_passes_query_params(self, handle):
        """get 的 params 拼接到请求 URL 查询串。"""
        seen: list[str] = []

        def _handler(request):
            seen.append(str(request.url))
            return _json_response(200, {"ok": True})

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                await client.get("/projects", params={"limit": 10})
        assert seen == [f"{BASE_URL}/projects?limit=10"]

    async def test_post_sends_json_body(self, handle):
        """post 携带 json body 到 /projects，返回 2xx body。"""
        seen: list[tuple[str, str, object]] = []

        def _handler(request):
            seen.append((request.method, str(request.url), json.loads(request.content)))
            return _json_response(200, {"ok": True, "id": "p1"})

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                result = await client.post("/projects", json={"name": "示例"})
        assert seen == [("POST", f"{BASE_URL}/projects", {"name": "示例"})]
        assert result == {"ok": True, "id": "p1"}

    async def test_patch_sends_json_body(self, handle):
        """patch 携带 json body 到资源路径，返回 2xx body。"""
        seen: list[tuple[str, str, object]] = []

        def _handler(request):
            seen.append((request.method, str(request.url), json.loads(request.content)))
            return _json_response(200, {"ok": True})

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                result = await client.patch("/projects/p1", json={"name": "改名"})
        assert seen == [("PATCH", f"{BASE_URL}/projects/p1", {"name": "改名"})]
        assert result == {"ok": True}

    async def test_delete_passes_params(self, handle):
        """delete 发到资源路径，params 拼查询串。"""
        seen: list[tuple[str, str]] = []

        def _handler(request):
            seen.append((request.method, str(request.url)))
            return _json_response(200, {"ok": True})

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                await client.delete("/projects/p1", params={"hard": "true"})
        assert seen == [("DELETE", f"{BASE_URL}/projects/p1?hard=true")]


class TestErrorHandling:
    """非 2xx → HttpApiError（契约 §4 提取规则）。"""

    async def test_404_raises_http_api_error(self, handle):
        """404 + {"detail": "项目不存在"} → HttpApiError(404, detail, code=None)。"""

        def _handler(request):
            return _json_response(404, {"detail": "项目不存在"})

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                with pytest.raises(HttpApiError) as exc_info:
                    await client.get("/projects")
        err = exc_info.value
        assert err.status_code == 404
        assert err.detail == "项目不存在"
        assert err.code is None

    async def test_500_error_header_maps_to_code(self, handle):
        """500 + X-InkFlow-Error-Code: LLM_ERROR → code="LLM_ERROR"；无头 → code=None。"""

        def _handler(request):
            if request.url.path.endswith("/with-header"):
                return _json_response(
                    500, {"detail": "LLM 调用失败"}, headers={"X-InkFlow-Error-Code": "LLM_ERROR"}
                )
            return _json_response(500, {"detail": "内部错误"})

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                with pytest.raises(HttpApiError) as exc_info:
                    await client.get("/with-header")
                with pytest.raises(HttpApiError) as exc_info2:
                    await client.get("/no-header")
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "LLM 调用失败"
        assert exc_info.value.code == "LLM_ERROR"
        assert exc_info2.value.status_code == 500
        assert exc_info2.value.detail == "内部错误"
        assert exc_info2.value.code is None

    @pytest.mark.parametrize(
        ("status_code", "header_code", "expected_code"),
        [
            (404, None, "NOT_FOUND"),
            (422, None, "VALIDATION_ERROR"),
            (401, None, "CONFIG_ERROR"),
            (500, "LLM_ERROR", "LLM_ERROR"),
            (500, None, "INTERNAL_ERROR"),
            (503, None, "INTERNAL_ERROR"),
        ],
    )
    def test_map_http_error_table(self, status_code, header_code, expected_code):
        """map_http_error 映射全表（spec §5.3；展示消息 = detail 原样透传）。"""
        code, message = map_http_error(status_code, "展示详情", header_code)
        assert code == expected_code
        assert message == "展示详情"


class TestStreamSse:
    """stream_sse 帧解析（契约 §5）。"""

    async def test_stream_sse_delta_frames_and_blank_lines(self, handle):
        """data: 帧 → yield 原始帧 dict；帧间空行跳过。"""
        frames = (
            'data: {"done": false, "delta": "你好"}\n\n'
            "\n"
            'data: {"done": false, "delta": "，世界"}\n\n'
        )

        def _handler(request):
            return httpx.Response(
                200,
                content=frames.encode("utf-8"),
                headers={"content-type": "text/event-stream"},
            )

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                events = [ev async for ev in client.stream_sse("/stream", json={"mode": "draft"})]
        assert events == [
            {"done": False, "delta": "你好"},
            {"done": False, "delta": "，世界"},
        ]

    async def test_stream_sse_done_frame(self, handle):
        """done 帧 → yield 原始 dict（format_valid/word_count/model/warnings 透传）。"""
        frames = (
            'data: {"done": true, "format_valid": true, "word_count": 12,'
            ' "model": "gpt-4o", "warnings": []}\n\n'
        )

        def _handler(request):
            return httpx.Response(
                200,
                content=frames.encode("utf-8"),
                headers={"content-type": "text/event-stream"},
            )

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                events = [ev async for ev in client.stream_sse("/stream", json={"mode": "draft"})]
        assert events == [
            {
                "done": True,
                "format_valid": True,
                "word_count": 12,
                "model": "gpt-4o",
                "warnings": [],
            }
        ]

    async def test_stream_sse_non_2xx_raises_before_stream(self, handle):
        """非 2xx → 流开始前（yield 任何帧之前）raise HttpApiError。"""

        def _handler(request):
            return _json_response(404, {"detail": "项目不存在"})

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                with pytest.raises(HttpApiError) as exc_info:
                    async for _ev in client.stream_sse("/stream", json={}):
                        pass
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "项目不存在"
        assert exc_info.value.code is None


class TestHttpApiErrorContract:
    """HttpApiError 数据类契约（契约 §2，不 frozen——见文件头修正说明）。"""

    def test_http_api_error_fields(self):
        """字段默认值 + Exception 继承。"""
        err = HttpApiError(status_code=404, detail="项目不存在")
        assert isinstance(err, Exception)
        assert err.status_code == 404
        assert err.detail == "项目不存在"
        assert err.code is None
        err2 = HttpApiError(status_code=500, detail="LLM 调用失败", code="LLM_ERROR")
        assert err2.code == "LLM_ERROR"


class TestImportSurface:
    """层间依赖单向性（cli → http，禁止反向；契约 §1/§7）。"""

    def test_no_cli_import_on_http_import(self):
        """import inkflow.infrastructure.http 不得连带 import inkflow.cli。"""
        # 本文件顶部 import 已加载 http 包；tests/unit 套件无其它 test_cli_* 文件、
        # conftest 亦不 import inkflow.cli，且本类定义序先于下方 test_cli_* 用例——
        # 裸 not in sys.modules 断言在 unit 套件内稳健。
        assert "inkflow.cli" not in sys.modules

    def test_cli_project_command_import_surface(self):
        """import inkflow.cli.commands.project 不得连带加载 domain.services/llm/database。"""
        # 快照差集（而非裸 not in sys.modules）：对全量套件先加载过这些模块的场景也稳健。
        prefixes = (
            "inkflow.domain.services",
            "inkflow.infrastructure.llm",
            "inkflow.infrastructure.database",
        )
        before = {m for m in sys.modules if m.startswith(prefixes)}
        importlib.import_module("inkflow.cli.commands.project")
        leaked = {m for m in sys.modules if m.startswith(prefixes)} - before
        assert leaked == set()


class TestLifecycle:
    """async 上下文管理器与 timeout 传递（契约 §3）。"""

    async def test_async_context_manager_closes_client(self, handle):
        """async with 退出时关闭 httpx 连接池（await aclose 一次）。"""
        mock_client = MagicMock()
        _response = httpx.Response(
            200, json={"ok": True}, request=httpx.Request("GET", f"{BASE_URL}/projects")
        )
        # get 与 request 双配置：兼容实现直调 `client.get(...)` 或统一
        # `client.request(...)` 两种形态
        mock_client.get = AsyncMock(return_value=_response)
        mock_client.request = AsyncMock(return_value=_response)
        mock_client.aclose = AsyncMock()
        with patch(HTTP_MOD, return_value=mock_client):
            async with InkFlowHTTPClient(handle) as client:
                # 发一次请求触发 AsyncClient 构造（无论 __init__ 还是 __aenter__ 创建）
                await client.get("/projects")
        mock_client.aclose.assert_awaited_once()

    @pytest.mark.parametrize(
        ("timeout_arg", "expected"),
        [(None, 30.0), (5.0, 5.0)],
    )
    async def test_timeout_forwarded_to_async_client(self, handle, timeout_arg, expected):
        """timeout 构造参数以 float 原样传给 httpx.AsyncClient（默认 30.0）。"""

        def _handler(request):
            return _json_response(200, {"ok": True})

        with _mock_http(handle, _handler) as (_make_client, captured):
            kwargs = {"timeout": timeout_arg} if timeout_arg is not None else {}
            async with InkFlowHTTPClient(handle, **kwargs) as client:
                await client.get("/projects")
        assert captured and captured[0]["timeout"] == expected


class TestExtractDetailFallback:
    """_extract_detail 容错分支：body 非 dict / 无 detail 键 / detail 非 str / 非 JSON。"""

    @pytest.mark.parametrize(
        ("payload", "expected_detail"),
        [
            ([1, 2, 3], ""),  # body 是 list（非 dict）→ ""
            ({"msg": "服务器错误"}, ""),  # dict 但无 detail 键 → ""
            ({"detail": 123}, "123"),  # detail 非 str（int）→ str() 转换
        ],
    )
    async def test_non_2xx_malformed_body_detail(self, handle, payload, expected_detail):
        """非 2xx + 异常 body 形状 → HttpApiError.detail 按提取规则兜底。"""

        def _handler(request):
            return _json_response(500, payload)

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                with pytest.raises(HttpApiError) as exc_info:
                    await client.get("/projects")
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == expected_detail

    async def test_non_2xx_plain_text_body_detail_empty(self, handle):
        """500 返回纯文本（非 JSON）→ response.json() 抛错 → detail == ""。"""

        def _handler(request):
            return httpx.Response(
                500,
                content=b"<html><body>Internal Server Error</body></html>",
                request=httpx.Request("GET", BASE_URL),
            )

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                with pytest.raises(HttpApiError) as exc_info:
                    await client.get("/projects")
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == ""


class TestStreamSseInterrupted:
    """stream_sse 流中断分支（契约 §5：流中途断开 → HttpApiError(code=STREAM_INTERRUPTED)）。"""

    async def test_stream_interrupted_after_partial_frame(self, handle):
        """已 yield 部分帧后流中断 → HttpApiError(status_code=0, STREAM_INTERRUPTED)。"""

        async def _aiter_lines():
            yield 'data: {"done": false, "delta": "部分"}'
            raise httpx.ReadError("connection lost")

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.aiter_lines = _aiter_lines

        mock_client = MagicMock()
        mock_client.aclose = AsyncMock()
        stream_cm = mock_client.stream.return_value
        stream_cm.__aenter__ = AsyncMock(return_value=fake_response)
        stream_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(HTTP_MOD, return_value=mock_client):
            async with InkFlowHTTPClient(handle) as client:
                events = []
                with pytest.raises(HttpApiError) as exc_info:
                    async for ev in client.stream_sse("/stream", json={}):
                        events.append(ev)

        assert events == [{"done": False, "delta": "部分"}]
        err = exc_info.value
        assert err.status_code == 0
        assert err.code == "STREAM_INTERRUPTED"
        assert "connection lost" in err.detail
        assert isinstance(err.__cause__, httpx.ReadError)


class TestGetRaw:
    """get_raw 原始文本下载（F21 导出契约 §4：返回 text/plain 响应文本，非 JSON 信封）。

    设计假设（F21 RED 阶段父侧裁定，2026-08-09）:
    - `async def get_raw(self, path, *, params=None) -> str`：GET 请求，2xx
      时返回响应文本（response.text，UTF-8 解码）；非 2xx 抛 HttpApiError
      （与 _request 同规则：detail 提取 + X-InkFlow-Error-Code 头）。
    - 用途：F21 export 端点返回 text/plain 字节流，CLI 经此下载 TXT；
      _request 的 response.json() 无法解析纯文本（会抛 JSONDecodeError）。
    - 实现提示：可独立方法（httpx.AsyncClient.get → .text），不复用
      _request（后者强制 json 解析）。
    """

    async def test_get_raw_returns_text_body(self, handle):
        """2xx text/plain → 返回原始响应文本（UTF-8 解码，非 JSON 解析）。"""
        text = "我的小说\n==============================\n第 1 章 开端\n（正文……）\n"

        def _handler(request):
            return httpx.Response(
                200,
                content=text.encode("utf-8"),
                headers={"content-type": "text/plain; charset=utf-8"},
            )

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                result = await client.get_raw("/projects/1/export")
        assert result == text

    async def test_get_raw_passes_query_params(self, handle):
        """params 拼接到请求 URL 查询串（include_settings=true 透传）。"""
        seen: list[str] = []

        def _handler(request):
            seen.append(str(request.url))
            return httpx.Response(
                200,
                content="TXT",
                headers={"content-type": "text/plain; charset=utf-8"},
            )

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                await client.get_raw("/projects/1/export", params={"include_settings": "true"})
        assert seen == [f"{BASE_URL}/projects/1/export?include_settings=true"]

    async def test_get_raw_404_raises_http_api_error(self, handle):
        """非 2xx（404）→ HttpApiError(404, detail)，与 _request 同规则。"""

        def _handler(request):
            return _json_response(404, {"detail": "项目不存在"})

        with _mock_http(handle, _handler) as (make_client, _captured):
            async with make_client() as client:
                with pytest.raises(HttpApiError) as exc_info:
                    await client.get_raw("/projects/999/export")
        err = exc_info.value
        assert err.status_code == 404
        assert err.detail == "项目不存在"
