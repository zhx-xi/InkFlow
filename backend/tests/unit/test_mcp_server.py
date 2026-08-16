"""F20 MCP server 装配契约（M3 验收）— spec §3/§4/§9/§13（Issue #49，RED 阶段测试契约）。

server.py（mcp 2.0 SDK）装配形态（2026-08-16 mcp==2.0.0 API 实证）：
- build_mcp_server(tools=None) -> mcp.server.Server：on_list_tools / on_call_tool
  回调装配（mcp 2.0 构造器参数），tools 缺省 = build_mcp_tools()（15 工具）。
- list_tools_result(tools) -> mt.ListToolsResult：tools/list handler 核心
  （纯函数，供测试直接调用）——恰好 15 项 Tool，name/description/inputSchema 非空。
- call_tool_result(tools, name, arguments) -> mt.CallToolResult：tools/call handler
  核心——按 name 查工具 → 信封透传（isError = not ok）；未知工具 → isError。
- main() async：stdio_server() → server.run(read_stream, write_stream,
  server.create_initialization_options())（mcp 2.0 官方入口形态）。
- run() 同步：anyio.run(main)（pyproject entry point inkflow-mcp）。
- 信封：CallToolResult.content=[mt.TextContent(text=<工具返回的信封 JSON>)]，
  isError 由信封 ok 字段决定（spec §3.2）。text 保留原始 JSON（ensure_ascii=False）。

── GREEN 实现契约 ────────────────────────────────────────────────
1. 模块 inkflow.mcp.server（CREATE）+ inkflow.mcp（__init__.py 导出 run /
   build_mcp_server / main）+ inkflow.mcp.__main__（python -m inkflow.mcp →
   run()）。
2. 🔴 工具参数校验落在**工具 func 内部**（schemas 模型 model_validate，第一行；
   ValidationError → _fail）——server 层只做「查工具 + 信封透传」，不做二次校验。
   call_tool_result 对未知工具名返回 isError=True（text = 信封 ok=False）。
3. import 面收敛（spec §5.1 / §13 M3）：import inkflow.mcp.server **不得**拖入
   inkflow.domain.services / inkflow.infrastructure.llm / inkflow.infrastructure.database
   ——mcp 层只 import mcp SDK + infrastructure.http/kernel（工具 func 内延迟）+
   domain.models.agent_tools（ToolSpec）。tools 模块**顶部禁止 import** http/kernel
   （延迟在 func 内，规则 1e 逃生门形态，与 test_mcp_tools GREEN 契约一致）。
4. tools/list 与 tool_search 同源（spec §4.2）：同一注册表 build_mcp_tools()。

── RED 形态说明 ─────────────────────────────────────────────────
inkflow.mcp.tools 包不存在 → 顶部 import 收集期 ModuleNotFoundError（exit 2，
规则 1c）。inkflow.mcp.server 的 import 放用例体 lazy（避免混入顶部失败集合）。

── 测试约定 ─────────────────────────────────────────────────────
- import 面收敛断言用 delta 法：用例体 lazy import inkflow.mcp.server，比较
  sys.modules 前后差集（其他测试文件的既有 import 不影响差集判断）。
- async 用例显式 @pytest.mark.asyncio（pytest-asyncio 1.x STRICT）。
- 本文件不顶部 import inkflow.mcp.server（破坏 delta；tools 已覆盖收集期 RED）。
"""

from __future__ import annotations

import importlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import mcp.types as mt
import pytest

from inkflow.mcp.tools import build_mcp_tools

kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
http_mod = importlib.import_module("inkflow.infrastructure.http")


class FakeClient:
    """有状态 fake（同 test_mcp_tools）：async 上下文管理器 + 记录调用。"""

    def __init__(self, handle):
        self.handle = handle
        self.calls: list[tuple[str, str, object, object]] = []
        self.response: object = {"id": "x", "name": "resp"}

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


@pytest.fixture
def fake_env(monkeypatch):
    """装配缝（同 test_mcp_tools）：ensure_kernel → 鸭子 handle；client → FakeClient。"""
    fake_ensure = AsyncMock(return_value=SimpleNamespace(port=1, token="t", pid=2, version="0.1.0"))
    monkeypatch.setattr(kernel_mod, "ensure_kernel", fake_ensure)
    monkeypatch.setattr(http_mod, "InkFlowHTTPClient", FakeClient)
    return SimpleNamespace(fake_ensure=fake_ensure)


class TestListTools:
    """tools/list 装配（spec §4.1/§4.2 渐进发现）。"""

    @pytest.mark.asyncio
    async def test_list_tools_returns_15(self):
        from inkflow.mcp.server import list_tools_result

        result = await list_tools_result(build_mcp_tools())
        assert isinstance(result, mt.ListToolsResult)
        assert len(result.tools) == 15

    @pytest.mark.asyncio
    async def test_tool_metadata_nonempty(self):
        from inkflow.mcp.server import list_tools_result

        result = await list_tools_result(build_mcp_tools())
        for tool in result.tools:
            assert isinstance(tool, mt.Tool)
            assert tool.name
            assert tool.description
            assert tool.input_schema.get("type") == "object"
            assert "action" in tool.input_schema.get("properties", {})

    @pytest.mark.asyncio
    async def test_tools_list_names_match_spec(self):
        from inkflow.mcp.server import list_tools_result

        result = await list_tools_result(build_mcp_tools())
        names = [t.name for t in result.tools]
        assert names == [
            "manage_project",
            "manage_chapter",
            "manage_character",
            "manage_relation",
            "manage_timeline",
            "manage_world",
            "manage_outline",
            "manage_foreshadowing",
            "write",
            "audit",
            "extract",
            "export",
            "search",
            "manage_session",
            "tool_search",
        ]


class TestCallTool:
    """tools/call 装配（spec §3.2 信封 / §3.3 错误映射）。"""

    @pytest.mark.asyncio
    async def test_call_known_tool_success(self, fake_env):
        from inkflow.mcp.server import call_tool_result

        result = await call_tool_result(
            build_mcp_tools(), "manage_project", {"action": "list", "search": "x"}
        )
        assert isinstance(result, mt.CallToolResult)
        assert result.is_error is False
        text = result.content[0].text
        env = json.loads(text)
        assert env["ok"] is True

    @pytest.mark.asyncio
    async def test_call_unknown_tool_is_error(self):
        from inkflow.mcp.server import call_tool_result

        result = await call_tool_result(build_mcp_tools(), "no_such_tool", {})
        assert result.is_error is True
        env = json.loads(result.content[0].text)
        assert env["ok"] is False

    @pytest.mark.asyncio
    async def test_call_http_error_is_error(self, fake_env, monkeypatch):
        from inkflow.mcp.server import call_tool_result

        class FailingClient(FakeClient):
            async def get(self, path, *, params=None, json=None) -> dict:
                from inkflow.infrastructure.http import HttpApiError

                raise HttpApiError(status_code=404, detail="不存在")

        monkeypatch.setattr(http_mod, "InkFlowHTTPClient", FailingClient)
        result = await call_tool_result(build_mcp_tools(), "manage_project", {"action": "list"})
        assert result.is_error is True
        env = json.loads(result.content[0].text)
        assert env["ok"] is False
        assert "NOT_FOUND" in env["error"]

    @pytest.mark.asyncio
    async def test_call_invalid_action_is_error(self, fake_env):
        """非法 action：工具 func 内模型校验 → _fail → isError（spec §7 #12）。"""
        from inkflow.mcp.server import call_tool_result

        result = await call_tool_result(
            build_mcp_tools(), "manage_project", {"action": "frobnicate"}
        )
        assert result.is_error is True


class TestBuildServer:
    """build_mcp_server 返回 mcp 2.0 Server（回调装配）。"""

    def test_returns_server_instance(self):
        from inkflow.mcp.server import build_mcp_server

        server = build_mcp_server()
        assert server.name == "inkflow"

    def test_server_has_request_handlers(self):
        from inkflow.mcp.server import build_mcp_server

        server = build_mcp_server()
        # mcp 2.0 Server 注册 tools/list + tools/call 回调（构造器 on_* 参数）
        assert hasattr(server, "add_request_handler")


class TestEntryPoints:
    """入口函数存在性（pyproject entry point inkflow-mcp）。"""

    def test_main_and_run_exist(self):
        server_mod = importlib.import_module("inkflow.mcp.server")
        assert callable(server_mod.main)
        assert callable(server_mod.run)

    def test_package_exports(self):
        pkg = importlib.import_module("inkflow.mcp")
        assert callable(pkg.run)
        assert callable(pkg.build_mcp_server)


class TestImportSurface:
    """import 面收敛（spec §5.1/§13 M3）：mcp.server 不拖入重组件。"""

    def test_server_import_surface(self):
        """import inkflow.mcp.server 后 sys.modules 无 domain.services/llm/database。"""
        before = set(sys.modules)
        importlib.import_module("inkflow.mcp.server")
        after = set(sys.modules)
        added = after - before
        assert not any(m.startswith("inkflow.domain.services") for m in added)
        assert not any(m.startswith("inkflow.infrastructure.llm") for m in added)
        assert not any(m.startswith("inkflow.infrastructure.database") for m in added)
