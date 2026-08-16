"""F20 MCP 工具工厂错误映射契约（覆盖率补测拆分）— spec §3.3（Issue #49）。

从 test_mcp_tools.py 拆出（900 行护栏）：TestErrorMapping + TestErrorMappingAllTools
（每工厂 4 类错误分支全覆盖）。契约内容见 test_mcp_tools.py docstring 与 GREEN 契约。
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# 主契约：inkflow.mcp.tools 包不存在 → 收集期 ModuleNotFoundError（规则 1c）
from inkflow.mcp.tools.manage_tools import (
    build_manage_chapter_tool,
    build_manage_character_tool,
    build_manage_foreshadowing_tool,
    build_manage_outline_tool,
    build_manage_project_tool,
    build_manage_relation_tool,
    build_manage_timeline_tool,
    build_manage_world_tool,
)
from inkflow.mcp.tools.operation_tools import (
    build_audit_tool,
    build_export_tool,
    build_extract_tool,
    build_search_tool,
    build_write_tool,
)
from inkflow.mcp.tools.session_tools import (
    build_manage_session_tool,
    build_tool_search_tool,
)

kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
http_mod = importlib.import_module("inkflow.infrastructure.http")


class FakeClient:
    """有状态 fake：记录 (method, path, params, json)，async 上下文管理器。"""

    def __init__(self, handle):
        self.handle = handle
        self.calls: list[tuple[str, str, object, object]] = []
        self.response: object = {"id": "x", "name": "resp"}
        self.raw_response: str = "raw-text"

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, path, *, params=None, json=None) -> dict:
        self.calls.append(("GET", path, params, json))
        return self.response  # type: ignore[return-value]

    async def post(self, path, *, params=None, json=None, timeout=None) -> dict:
        self.calls.append(("POST", path, params, json))
        return self.response  # type: ignore[return-value]

    async def patch(self, path, *, params=None, json=None) -> dict:
        self.calls.append(("PATCH", path, params, json))
        return self.response  # type: ignore[return-value]

    async def delete(self, path, *, params=None, json=None) -> dict:
        self.calls.append(("DELETE", path, params, json))
        return self.response  # type: ignore[return-value]

    async def get_raw(self, path, *, params=None) -> str:
        self.calls.append(("GET_RAW", path, params, None))
        return self.raw_response


@pytest.fixture
def fake_env(monkeypatch):
    """装配缝：ensure_kernel → 鸭子 handle；InkFlowHTTPClient → 恒返回同一 client 实例。

    🔴 func 内部 `async with InkFlowHTTPClient(handle)` 每次构造新实例——patch 必须
    返回**同一个**预建实例（lambda 闭包），断言 `fake_env.client.calls` 才能命中。
    （Codex GREEN 2026-08-16 实测：patch 成类 → 调用记录落在新实例上，预建实例恒空）
    """
    client = FakeClient(SimpleNamespace(port=1, token="t"))
    fake_ensure = AsyncMock(return_value=SimpleNamespace(port=1, token="t", pid=2, version="0.1.0"))
    monkeypatch.setattr(kernel_mod, "ensure_kernel", fake_ensure)
    monkeypatch.setattr(http_mod, "InkFlowHTTPClient", lambda handle: client)
    return SimpleNamespace(client=client, fake_ensure=fake_ensure)


def _parse_envelope(text: str) -> dict:
    """解析工具 func 返回的信封 JSON 字符串。"""
    return json.loads(text)


def _last_call(client: FakeClient) -> tuple[str, str, object, object]:
    """最近一次 HTTP 调用的 (method, path, params, json)。"""
    assert client.calls, "未发生 HTTP 调用"
    return client.calls[-1]


class TestErrorMapping:
    """错误映射（spec §3.3：F7 错误码 + F38 map_http_error 复用）。"""

    @pytest.mark.asyncio
    async def test_http_404_maps_not_found(self, fake_env, monkeypatch):
        """HttpApiError(404) → 信封 ok=False + error 含 NOT_FOUND。"""
        tool = build_manage_project_tool()

        class FailingClient(FakeClient):
            async def get(self, path, *, params=None, json=None) -> dict:
                from inkflow.infrastructure.http import HttpApiError

                raise HttpApiError(status_code=404, detail="项目不存在")

        monkeypatch.setattr(http_mod, "InkFlowHTTPClient", FailingClient)
        env = _parse_envelope(await tool.func(action="list", search="x"))
        assert env["ok"] is False
        assert "NOT_FOUND" in env["error"]

    @pytest.mark.asyncio
    async def test_http_422_maps_validation(self, fake_env, monkeypatch):
        tool = build_manage_chapter_tool()

        class FailingClient(FakeClient):
            async def post(self, path, *, params=None, json=None, timeout=None) -> dict:
                from inkflow.infrastructure.http import HttpApiError

                raise HttpApiError(status_code=422, detail="参数错误")

        monkeypatch.setattr(http_mod, "InkFlowHTTPClient", FailingClient)
        env = _parse_envelope(await tool.func(action="create", project_id="p1", title="t"))
        assert env["ok"] is False
        assert "VALIDATION_ERROR" in env["error"]

    @pytest.mark.asyncio
    async def test_kernel_startup_error(self, fake_env, monkeypatch):
        """ensure_kernel 失败 → 内核启动失败消息。"""
        tool = build_manage_project_tool()

        async def _fail_ensure(**kwargs):
            from inkflow.infrastructure.kernel import KernelStartupError

            raise KernelStartupError("超时")

        monkeypatch.setattr(kernel_mod, "ensure_kernel", _fail_ensure)
        env = _parse_envelope(await tool.func(action="list"))
        assert env["ok"] is False
        assert "内核启动失败" in env["error"]

    @pytest.mark.asyncio
    async def test_unexpected_exception(self, fake_env, monkeypatch):
        """未知异常 → 错误文本（对齐 F26 _fail）。"""
        tool = build_manage_project_tool()

        class BoomClient(FakeClient):
            async def get(self, path, *, params=None, json=None) -> dict:
                raise RuntimeError("boom")

        monkeypatch.setattr(http_mod, "InkFlowHTTPClient", BoomClient)
        env = _parse_envelope(await tool.func(action="list"))
        assert env["ok"] is False
        assert "boom" in env["error"]


# ── 覆盖率补测：每个工具工厂的错误分支（except 块）全覆盖 ────────────
# 每个工厂 _impl 含 4 类错误分支（ValidationError/HttpApiError/KernelStartupError/
# Exception ≈ 13 行 × 15 工厂）。TestErrorMapping 只覆盖 manage_project/chapter，
# 其余 13 工厂的 except 块漏覆盖（coverage 98.04% < 98.5% 门槛实测 2026-08-16）。
# 泛化补测：每工厂 1 个 HttpApiError(404) + 1 个 RuntimeError，逐工厂参数化。

_ALL_FACTORIES: dict[str, tuple[object, dict]] = {
    "manage_project": (build_manage_project_tool, {"action": "list"}),
    "manage_chapter": (build_manage_chapter_tool, {"action": "list", "project_id": "p1"}),
    "manage_character": (build_manage_character_tool, {"action": "list", "project_id": "p1"}),
    "manage_relation": (build_manage_relation_tool, {"action": "list", "character_id": "c1"}),
    "manage_timeline": (build_manage_timeline_tool, {"action": "list", "project_id": "p1"}),
    "manage_world": (build_manage_world_tool, {"action": "list", "project_id": "p1"}),
    "manage_outline": (build_manage_outline_tool, {"action": "list", "project_id": "p1"}),
    "manage_foreshadowing": (
        build_manage_foreshadowing_tool,
        {"action": "list", "project_id": "p1"},
    ),
    "write": (build_write_tool, {"action": "generate", "project_id": "p1", "chapter_id": "c1"}),
    "audit": (build_audit_tool, {"action": "project", "project_id": "p1"}),
    "extract": (build_extract_tool, {"action": "extract", "content": "文本"}),
    "export": (build_export_tool, {"action": "export", "project_id": "p1"}),
    "search": (build_search_tool, {"action": "search", "query": "q"}),
    "manage_session": (build_manage_session_tool, {"action": "list"}),
    "tool_search": (build_tool_search_tool, {"action": "list"}),
}

# tool_search 不走 HTTP（本地装配，spec §7 #15）——HTTP 类错误测试
# （http/unexpected/kernel）排除它；invalid_action 测试保留（本地仍做
# ValidationError 校验 → 失败信封）。
_HTTP_FACTORIES: dict[str, tuple[object, dict]] = {
    k: v for k, v in _ALL_FACTORIES.items() if k != "tool_search"
}


class TestErrorMappingAllTools:
    """每工厂错误分支全覆盖（覆盖率补测，规则 1j：新用例直接通过，无 RED 阶段）。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", list(_HTTP_FACTORIES))
    async def test_http_error_envelope(self, fake_env, monkeypatch, name):
        """HttpApiError(404) → ok=False + NOT_FOUND（覆盖各工厂 HttpApiError except）。"""
        factory, args = _ALL_FACTORIES[name]
        tool = factory()

        class FailingClient(FakeClient):
            async def get(self, path, *, params=None, json=None) -> dict:
                raise self._err()

            async def get_raw(self, path, *, params=None) -> str:
                raise self._err()

            async def post(self, path, *, params=None, json=None, timeout=None) -> dict:
                raise self._err()

            async def patch(self, path, *, params=None, json=None) -> dict:
                raise self._err()

            async def delete(self, path, *, params=None, json=None) -> dict:
                raise self._err()

            @staticmethod
            def _err():
                from inkflow.infrastructure.http import HttpApiError

                return HttpApiError(status_code=404, detail="不存在")

        monkeypatch.setattr(http_mod, "InkFlowHTTPClient", FailingClient)
        env = _parse_envelope(await tool.func(**args))
        assert env["ok"] is False
        assert "NOT_FOUND" in env["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", list(_HTTP_FACTORIES))
    async def test_unexpected_exception_envelope(self, fake_env, monkeypatch, name):
        """RuntimeError → ok=False + 错误文本（覆盖各工厂 Exception except）。"""
        factory, args = _ALL_FACTORIES[name]
        tool = factory()

        class BoomClient(FakeClient):
            async def get(self, path, *, params=None, json=None) -> dict:
                raise RuntimeError("boom")

            async def get_raw(self, path, *, params=None) -> str:
                raise RuntimeError("boom")

            async def post(self, path, *, params=None, json=None, timeout=None) -> dict:
                raise RuntimeError("boom")

            async def patch(self, path, *, params=None, json=None) -> dict:
                raise RuntimeError("boom")

            async def delete(self, path, *, params=None, json=None) -> dict:
                raise RuntimeError("boom")

        monkeypatch.setattr(http_mod, "InkFlowHTTPClient", BoomClient)
        env = _parse_envelope(await tool.func(**args))
        assert env["ok"] is False
        assert "boom" in env["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", list(_HTTP_FACTORIES))
    async def test_kernel_error_envelope(self, fake_env, monkeypatch, name):
        """KernelStartupError → ok=False + 内核启动失败（覆盖各工厂 KernelStartupError except）。"""
        factory, args = _ALL_FACTORIES[name]
        tool = factory()

        async def _fail_ensure(**kwargs):
            from inkflow.infrastructure.kernel import KernelStartupError

            raise KernelStartupError("超时")

        monkeypatch.setattr(kernel_mod, "ensure_kernel", _fail_ensure)
        env = _parse_envelope(await tool.func(**args))
        assert env["ok"] is False
        assert "内核启动失败" in env["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", list(_ALL_FACTORIES))
    async def test_invalid_action_envelope(self, fake_env, name):
        """非法 action → ok=False（覆盖各工厂 ValidationError except）。"""
        factory, args = _ALL_FACTORIES[name]
        tool = factory()
        bad_args = dict(args)
        bad_args["action"] = "frobnicate"
        env = _parse_envelope(await tool.func(**bad_args))
        assert env["ok"] is False
