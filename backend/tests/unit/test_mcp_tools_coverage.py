"""MCP 工具工厂覆盖率补测（#627，规则 1j：新用例直接通过，无 RED 阶段）。

补 session_tools / operation_tools 漏覆盖分支：
- operation_tools `_serialize_data`：list 分支（51）、model_dump 非 dict 分支（54-56）
- operation_tools `_HTTPClient` Protocol 方法体 `...`（28/31/39/42/45 ->exit）
- session_tools `_HTTPClient` Protocol 方法体 `...`（22/25/33/36/39 ->exit）
- session_tools `_actions_of` 防御分支（67/70/73/76）
- session_tools `build_tool_search_tool` except Exception（172-173）

独立的 module 级 from-import 缺一即 ImportError；工具 func 内延迟 import 的
MCP_TOOL_REGISTRY 在调用期从 inkflow.mcp.tools 解析 → monkeypatch 命中。
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest

from inkflow.mcp.tools.manage_tools import (
    _HTTPClient as ManageHTTPClient,
    _serialize_data as _manage_serialize,
)
from inkflow.mcp.tools.operation_tools import (
    _HTTPClient as OpHTTPClient,
    _serialize_data,
)
from inkflow.mcp.tools.session_tools import (
    _HTTPClient as SessionHTTPClient,
    _actions_of,
    build_tool_search_tool,
)

tools_pkg = importlib.import_module("inkflow.mcp.tools")


class TestSerializeData:
    """_serialize_data 递归序列化：list / pydantic model_dump / 原样。"""

    def test_list_elementwise(self):
        """list → 逐元素递归（覆盖 line 51 list 分支）。"""
        assert _serialize_data([1, {"a": 2}, "x"]) == [1, {"a": 2}, "x"]

    def test_model_dump_returns_dict(self):
        """含 model_dump 且返回 dict → 返回 dumped（覆盖 line 53-54）。"""

        class _M:
            def model_dump(self, mode=None):
                return {"x": 1}

        assert _serialize_data(_M()) == {"x": 1}

    def test_model_dump_returns_non_dict(self):
        """model_dump 返回非 dict（如 list）→ 原样返回 value（覆盖 line 55-56）。"""

        class _M:
            def model_dump(self, mode=None):
                return [1, 2, 3]

        obj = _M()
        assert _serialize_data(obj) is obj

    def test_scalar_passthrough(self):
        """非 list / 无 model_dump → 原样返回（覆盖 line 57 fallthrough）。"""
        assert _serialize_data(42) == 42


class TestProtocolStubsExecute:
    """_HTTPClient Protocol 方法体 `...` 未覆盖（branch ->exit）。

    Protocol 方法体只含 `...`，正常调用路径从不执行（FakeClient 为鸭子 fake，
    不继承 Protocol）；用继承 Protocol 的具体子类实例 await 其上：方法体执行并
    返回 None（不能直接实例化 Protocol——非 runtime-checkable 且无 __init__）。
    """

    class _OpConcrete(OpHTTPClient):
        pass

    class _SessionConcrete(SessionHTTPClient):
        pass

    @pytest.mark.asyncio
    async def test_operation_http_protocol_stubs(self):
        client = self._OpConcrete()
        assert await client.get("/x") is None
        assert await client.post("/x", json={}) is None
        assert await client.patch("/x", json={}) is None
        assert await client.delete("/x") is None
        assert await client.get_raw("/x") is None

    @pytest.mark.asyncio
    async def test_session_http_protocol_stubs(self):
        client = self._SessionConcrete()
        assert await client.get("/x") is None
        assert await client.post("/x", json={}) is None
        assert await client.patch("/x", json={}) is None
        assert await client.delete("/x") is None
        assert await client.get_raw("/x") is None


def _mk_tool(input_schema: object) -> object:
    """构造 _actions_of 输入（tool.spec.input_schema）。"""
    return SimpleNamespace(spec=SimpleNamespace(input_schema=input_schema))


class TestActionsOfGuards:
    """tool_search._actions_of 防御分支（session_tools 67/70/73/76）。"""

    def test_schema_not_dict_returns_empty(self):
        """spec.input_schema 非 dict → []（guard 67）。"""
        assert _actions_of(_mk_tool("nope")) == []
        assert _actions_of(None) == []

    def test_properties_not_dict_returns_empty(self):
        """schema dict 但无 properties / properties 非 dict → []（guard 70）。"""
        assert _actions_of(_mk_tool({"type": "object"})) == []

    def test_action_prop_not_dict_returns_empty(self):
        """properties.action 非 dict → []（guard 73）。"""
        assert _actions_of(_mk_tool({"properties": {"action": "x"}})) == []

    def test_enum_not_list_returns_empty(self):
        """action.enum 非 list → []（guard 76）。"""
        assert _actions_of(_mk_tool({"properties": {"action": {"enum": "x"}}})) == []

    def test_valid_enum_returns_items(self):
        """合法 enum → 字符串列表（line 77 正常返回）。"""
        assert _actions_of(_mk_tool({"properties": {"action": {"enum": ["a", "b"]}}})) == [
            "a",
            "b",
        ]


class TestToolSearchException:
    """tool_search func 内 MCP_TOOL_REGISTRY 迭代异常 → _fail（172-173）。"""

    @pytest.mark.asyncio
    async def test_registry_iteration_raises(self, monkeypatch):
        # registry=[None]：dict 推导访问 None.spec.name → AttributeError → except
        monkeypatch.setattr(tools_pkg, "MCP_TOOL_REGISTRY", [None])
        tool = build_tool_search_tool()
        text = await tool.func(action="list")
        env = json.loads(text)
        assert env["ok"] is False
        assert "error" in env


class TestManageToolsCoverage:
    """manage_tools（#627 临界 97%）：_HTTPClient Protocol `...` 存根（32/35/43/46/49
    ->exit）+ `_serialize_data` 的 list 分支（55）/ model_dump dict 分支（58-60）。

    与 operation/session 同形：现有测试 FakeClient 响应恒为普通 dict → _serialize_data
    的 list / model_dump 分支从未执行；Protocol 存根被捕获为 branch ->exit。
    """

    class _ManageConcrete(ManageHTTPClient):
        pass

    @pytest.mark.asyncio
    async def test_manage_http_protocol_stubs(self):
        client = self._ManageConcrete()
        assert await client.get("/x") is None
        assert await client.post("/x", json={}) is None
        assert await client.patch("/x", json={}) is None
        assert await client.delete("/x") is None
        assert await client.get_raw("/x") is None

    def test_manage_serialize_list(self):
        """_serialize_data list 分支（line 55）。"""
        assert _manage_serialize([1, {"a": 2}]) == [1, {"a": 2}]

    def test_manage_serialize_model_dump_dict(self):
        """model_dump 返回 dict → dumped（line 58-60）。"""

        class _M:
            def model_dump(self, mode=None):
                return {"x": 1}

        assert _manage_serialize(_M()) == {"x": 1}

    def test_manage_serialize_model_dump_non_dict(self):
        """model_dump 返回非 dict → 原样返回 value（line 61 fallthrough）。"""

        class _M:
            def model_dump(self, mode=None):
                return [1, 2, 3]

        obj = _M()
        assert _manage_serialize(obj) is obj
