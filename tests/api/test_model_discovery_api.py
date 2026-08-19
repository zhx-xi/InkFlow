"""Issue #483 模型发现 RED 契约 — POST /api/v1/provider-configs/models（模型发现代理）.

本文件为 `api/routers/provider_configs.py` 新增端点（NEW，Issue #483 模型发现
代理）定义 API 测试契约：给定 base_url（+ 可选 api_key / provider keychain
回退），代理向上游 `GET {base_url.rstrip('/')}/models` 发现模型列表，归一化
为模型 ID 字符串列表返回。测试方式镜像 tests/api/test_provider_config_api.py
（ASGITransport + AsyncClient + 无 token 模式 + override_get_db 真实内存库）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【端点】`POST /api/v1/provider-configs/models`，挂载在既有
   `inkflow.api.routers.provider_configs.router`（prefix=/api/v1/provider-configs，
   app.py 已 include_router，本文件仅新增子路径路由）。RED 形态：路由未注册
   → POST 命中 `/{provider_config_id}` 路径但方法不允许 → 405（422 用例
   断言失败）；patch 目标缺失 → 其余用例 ERROR。

2. 【请求体（pydantic）】
   - base_url: str 必填，strip 后非空（空白 → 422；缺失 → 422）
   - api_key: str | None 可选（提供即直用，Bearer 注入上游请求头）
   - provider: str | None 可选（keychain 回退锚点）

3. 【响应信封——HTTP 恒 200，业务成败在 ok（镜像 settings.py llm/test 语义）】
   - 成功：{ok: true, models: ["id1", "id2", ...]}（models = 模型 ID 字符串列表）
   - 失败：{ok: false, message: "..."}（上游 401/403、网络不可达、超时、
     非 JSON 响应 → 一律 200 + ok:false，绝不抛 502/500）

4. 【上游请求行为（本文件 patch 目标 = 最终契约，GREEN 必须匹配）】
   - 实现约定：模块内 `import httpx`，经 `httpx.AsyncClient` 发起请求 →
     测试 patch 目标 `inkflow.api.routers.provider_configs.httpx.AsyncClient`
     （RED 阶段模块未 import httpx → patch 抛 ModuleNotFoundError/AttributeError）
   - 上游 URL = `base_url.rstrip('/') + '/models'`
     （例 base_url='https://api.deepseek.com/v1' → GET https://api.deepseek.com/v1/models）
   - api_key 提供 → 上游请求头 `Authorization: Bearer {api_key}`
   - api_key 缺省 + provider 提供 → keychain 回退：patch 目标
     `inkflow.api.routers.provider_configs.get_key_manager`（零参模块级工厂，
     镜像 settings.py `_get_key_manager` 模式）→ 返回对象 `.get_key(provider)`
     得到 key → 上游请求头带该 key（provider 作为 get_key 入参锚点）
   - keychain 也无 key（get_key 返回 None）→ 仍发请求（不带 Authorization，
     兼容本地 Ollama 无 key 场景），上游成功 → ok:true

5. 【上游响应归一化（两种格式）】
   - OpenAI 风格：{"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]}
     → models: ["gpt-4o", "gpt-4o-mini"]
   - Ollama /api/tags 风格：{"models": [{"name": "qwen2.5"}, {"name": "llama3"}]}
     → models: ["qwen2.5", "llama3"]

6. 【安全红线】响应体（含 message）不得回显明文 api_key（settings.py 同款红线）。

7. 【测试方式】与 test_provider_config_api.py 同款：`db_session` +
   `override_get_db` fixture（tests/api/conftest.py 既有，本文件不修改
   conftest）免疫 GREEN 若引入 get_db 依赖；无 token 模式（显式 delenv
   INKFLOW_SERVER_TOKEN）；全部用例显式 `@pytest.mark.asyncio`。

8. 【mock 形态】httpx.AsyncClient 为 async context manager：mock 实例须支持
   `async with`（__aenter__/__aexit__ 已配置），`get()` 为 AsyncMock 返回
   真实 httpx.Response（构造时附 request，兼容实现调用 raise_for_status）；
   网络异常用真实 `httpx.ConnectError` / `httpx.TimeoutException` 作
   side_effect。上游调用断言兼容 `get(url, headers=...)` 位置/关键字两种形态。

════════════════════════════════════════════════════════════════════
RED 阶段预期：`/models` 子路由未注册 → 422 两用例 FAIL（405 ≠ 422）；
其余用例 patch 目标缺失（模块无 `httpx` / `get_key_manager` 属性）→ ERROR。
GREEN 阶段：按上述契约实现后全绿。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import inkflow.api.routers.provider_configs  # noqa: F401  # RED 收集断言：模块存在性契约（router 已注册，/models 端点缺失 → 405）
from inkflow.api.app import app

# ── 契约常量 ──

ENDPOINT = "/api/v1/provider-configs/models"
"""模型发现代理端点（Issue #483，挂在 provider_configs router 下）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 中间件直通（无 token 模式）。"""

PATCH_HTTPX = "inkflow.api.routers.provider_configs.httpx.AsyncClient"
"""上游 HTTP 客户端 patch 目标（设计假设 #4）：GREEN 须在模块内 import httpx。"""

PATCH_KEY_MANAGER = "inkflow.api.routers.provider_configs.get_key_manager"
"""keychain 回退工厂 patch 目标（设计假设 #4）：零参模块级工厂，镜像 settings.py。"""

UPSTREAM_BASE = "https://api.deepseek.com/v1"
UPSTREAM_URL = "https://api.deepseek.com/v1/models"
"""例：base_url='https://api.deepseek.com/v1' → GET https://api.deepseek.com/v1/models。"""

API_KEY = "sk-red-contract-483-secret"
"""请求体直传 api_key（测试 1/7/8/9/10/11 用；断言响应不回显此字面量）。"""

KEYCHAIN_KEY = "sk-keychain-483-secret"
"""keychain 回退 key（测试 5 用；断言上游请求头 Bearer 此值）。"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，test_provider_config_api.py 同款 + 无 token 模式）。

    设计假设 #7：显式 delenv INKFLOW_SERVER_TOKEN → token 中间件直通；
    ASGITransport 不触发 lifespan。
    """
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── mock / 断言辅助 ──

_UPSTREAM_REQUEST = httpx.Request("GET", UPSTREAM_URL)
"""上游请求对象（附在 mock Response 上，兼容 GREEN 调 raise_for_status）。"""


def _upstream_response(
    status_code: int, *, json_body: dict | None = None, text: str | None = None
) -> httpx.Response:
    """构造真实 httpx.Response 作上游响应 mock（json()/text/status_code 全真实）。"""
    kwargs: dict[str, Any] = {}
    if json_body is not None:
        kwargs["json"] = json_body
    elif text is not None:
        kwargs["text"] = text
    else:
        kwargs["text"] = ""
    return httpx.Response(status_code, request=_UPSTREAM_REQUEST, **kwargs)


@contextlib.contextmanager
def _patch_upstream(
    mock_resp: httpx.Response | None = None, *, side_effect: Exception | None = None
) -> Iterator[AsyncMock]:
    """patch provider_configs.httpx.AsyncClient → yield mock 客户端实例。

    mock 支持 async with（__aenter__ 返回自身）；`get()` 为 AsyncMock：
    return_value=mock_resp 或 side_effect 抛上游异常。RED 阶段模块无 httpx
    属性 → patch 抛 ModuleNotFoundError（预期失败形态）。
    """
    mock_client = AsyncMock()
    if mock_resp is not None:
        mock_client.get.return_value = mock_resp
    if side_effect is not None:
        mock_client.get.side_effect = side_effect
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    with patch(PATCH_HTTPX, return_value=mock_client):
        yield mock_client


class _FakeKeyManager:
    """get_key_manager 工厂返回对象契约（设计假设 #4）：.get_key(provider) -> str | None。"""

    def __init__(self, key: str | None) -> None:
        self._key = key
        self.calls: list[str] = []

    def get_key(self, provider: str) -> str | None:
        self.calls.append(provider)
        return self._key


@contextlib.contextmanager
def _patch_keychain(key: str | None) -> Iterator[_FakeKeyManager]:
    """patch provider_configs.get_key_manager → yield fake（provider → key 映射）。

    RED 阶段模块无 get_key_manager 属性 → patch 抛 AttributeError（预期失败形态）。
    """
    fake = _FakeKeyManager(key)
    with patch(PATCH_KEY_MANAGER, return_value=fake):
        yield fake


def _assert_upstream_request(
    mock_client: AsyncMock,
    expected_url: str,
    *,
    auth: str | None = None,
    no_auth: bool = False,
) -> None:
    """上游请求契约（设计假设 #4）：URL 精确匹配 + Authorization 头断言。

    兼容 `get(url, headers=...)` 位置/关键字两种调用形态，不锁 GREEN 调用签名。
    """
    mock_client.get.assert_awaited_once()
    call = mock_client.get.await_args
    assert call is not None, "未发起上游请求"
    url = call.args[0] if call.args else call.kwargs.get("url")
    assert url == expected_url, f"上游 URL 应为 {expected_url}，实际 {url}"
    headers = call.kwargs.get("headers")
    if headers is None and len(call.args) > 1:
        headers = call.args[1]
    headers = headers or {}
    if no_auth:
        assert "Authorization" not in headers, "无 key 场景不得携带 Authorization 头"
    else:
        actual = headers.get("Authorization")
        assert actual == auth, f"Authorization 头应为 {auth!r}，实际 {actual!r}"


# ── 成功路径 ──


@pytest.mark.asyncio
@pytest.mark.api
class TestModelDiscoverySuccess:
    """模型发现成功路径（设计假设 #3/#4/#5）。"""

    async def test_openai_format_success_with_bearer_header(
        self, client, db_session, override_get_db
    ):
        """OpenAI 风格归一化：200 + ok:true + models ID 列表；上游 URL 与 Bearer 头精确断言。

        base_url='https://api.deepseek.com/v1'（无尾斜杠）→ 上游 GET
        https://api.deepseek.com/v1/models；api_key 提供 → Authorization:
        Bearer {api_key}（设计假设 #4/#5）。
        """
        mock_resp = _upstream_response(
            200, json_body={"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]}
        )
        with _patch_upstream(mock_resp) as mock_client:
            resp = await client.post(
                ENDPOINT, json={"base_url": UPSTREAM_BASE, "api_key": API_KEY}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["models"] == ["gpt-4o", "gpt-4o-mini"]
        _assert_upstream_request(mock_client, UPSTREAM_URL, auth=f"Bearer {API_KEY}")

    async def test_ollama_tags_format_normalized(
        self, client, db_session, override_get_db
    ):
        """Ollama /api/tags 风格归一化：{"models": [{"name": ...}]} → models ID 列表。

        base_url 带尾斜杠 'http://localhost:11434/' → 上游 URL 必须
        rstrip('/') 后拼接 → http://localhost:11434/models（设计假设 #4/#5）。
        """
        mock_resp = _upstream_response(
            200, json_body={"models": [{"name": "qwen2.5"}, {"name": "llama3"}]}
        )
        with _patch_upstream(mock_resp) as mock_client:
            resp = await client.post(
                ENDPOINT,
                json={"base_url": "http://localhost:11434/", "api_key": API_KEY},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["models"] == ["qwen2.5", "llama3"]
        _assert_upstream_request(
            mock_client, "http://localhost:11434/models", auth=f"Bearer {API_KEY}"
        )

    async def test_keychain_fallback_when_api_key_omitted(
        self, client, db_session, override_get_db
    ):
        """api_key 缺省 + provider 提供 → keychain 回退：get_key_manager 工厂被调用，
        get_key(provider) 返回的 key 注入上游 Bearer 头（设计假设 #4）。

        provider 必须作为 get_key 入参锚点传递（fake.calls 断言）。
        """
        mock_resp = _upstream_response(
            200, json_body={"data": [{"id": "deepseek-chat"}]}
        )
        with _patch_upstream(mock_resp) as mock_client, _patch_keychain(
            KEYCHAIN_KEY
        ) as km:
            resp = await client.post(
                ENDPOINT, json={"base_url": UPSTREAM_BASE, "provider": "deepseek"}
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert km.calls == [
            "deepseek"
        ], f"get_key 应以 provider 为锚点，实际调用 {km.calls}"
        _assert_upstream_request(
            mock_client, UPSTREAM_URL, auth=f"Bearer {KEYCHAIN_KEY}"
        )

    async def test_no_key_no_auth_header_still_proxies(
        self, client, db_session, override_get_db
    ):
        """api_key 与 keychain 均无（get_key 返回 None）→ 仍发上游请求、无
        Authorization 头（兼容本地 Ollama），上游成功 → ok:true（设计假设 #4）。"""
        mock_resp = _upstream_response(
            200, json_body={"models": [{"name": "llama3.1"}]}
        )
        with _patch_upstream(mock_resp) as mock_client, _patch_keychain(None) as km:
            resp = await client.post(
                ENDPOINT, json={"base_url": UPSTREAM_BASE, "provider": "ollama"}
            )

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["models"] == ["llama3.1"]
        assert km.calls == ["ollama"]
        _assert_upstream_request(mock_client, UPSTREAM_URL, no_auth=True)


# ── 请求体验证 ──


@pytest.mark.asyncio
@pytest.mark.api
class TestModelDiscoveryValidation:
    """请求体校验（设计假设 #2）：base_url 必填、strip 后非空 → 422。"""

    async def test_blank_base_url_422(self, client, db_session, override_get_db):
        """base_url 为空白字符串 → 422（Pydantic 校验错误列表）。"""
        resp = await client.post(ENDPOINT, json={"base_url": "   "})
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    async def test_missing_base_url_422(self, client, db_session, override_get_db):
        """请求体缺 base_url 字段 → 422。"""
        resp = await client.post(ENDPOINT, json={})
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)


# ── 上游失败路径 ──


@pytest.mark.asyncio
@pytest.mark.api
class TestModelDiscoveryUpstreamFailure:
    """上游异常归一化（设计假设 #3）：一律 HTTP 200 + ok:false + message，不抛 502/500。"""

    async def test_upstream_401_ok_false_message_api_key(
        self, client, db_session, override_get_db
    ):
        """上游 401 → 200 {ok:false, message 含 'API Key' 字样}（镜像 llm/test 语义）。"""
        mock_resp = _upstream_response(
            401, json_body={"error": {"message": "Invalid API Key provided"}}
        )
        with _patch_upstream(mock_resp) as mock_client:
            resp = await client.post(
                ENDPOINT, json={"base_url": UPSTREAM_BASE, "api_key": API_KEY}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert (
            "API Key" in body["message"]
        ), f"message 应含 'API Key'，实际 {body['message']!r}"
        assert mock_client.get.await_count == 1

    async def test_upstream_connect_error_ok_false(
        self, client, db_session, override_get_db
    ):
        """上游网络不可达（httpx.ConnectError）→ 200 {ok:false, message 非空}。"""
        with _patch_upstream(side_effect=httpx.ConnectError("connection refused")):
            resp = await client.post(
                ENDPOINT, json={"base_url": UPSTREAM_BASE, "api_key": API_KEY}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["message"], "失败 message 不得为空"

    async def test_upstream_timeout_ok_false(self, client, db_session, override_get_db):
        """上游超时（httpx.TimeoutException）→ 200 {ok:false, message 非空}。"""
        with _patch_upstream(side_effect=httpx.TimeoutException("request timed out")):
            resp = await client.post(
                ENDPOINT, json={"base_url": UPSTREAM_BASE, "api_key": API_KEY}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["message"], "失败 message 不得为空"

    async def test_upstream_non_json_ok_false(
        self, client, db_session, override_get_db
    ):
        """上游返回非 JSON（text/html）→ 200 {ok:false, message 非空}。

        格式解析失败归入业务失败。
        """
        mock_resp = _upstream_response(
            200, text="<html><body>Gateway Error</body></html>"
        )
        with _patch_upstream(mock_resp):
            resp = await client.post(
                ENDPOINT, json={"base_url": UPSTREAM_BASE, "api_key": API_KEY}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["message"], "失败 message 不得为空"

    async def test_response_never_echoes_api_key(
        self, client, db_session, override_get_db
    ):
        """安全红线（设计假设 #6）：任何响应（含 ok:false message）不得回显明文 api_key。"""
        mock_resp = _upstream_response(200, json_body={"data": [{"id": "gpt-4o"}]})
        with _patch_upstream(mock_resp):
            resp = await client.post(
                ENDPOINT, json={"base_url": UPSTREAM_BASE, "api_key": API_KEY}
            )

        assert resp.status_code == 200
        assert API_KEY not in resp.text, "响应体不得回显明文 api_key"
