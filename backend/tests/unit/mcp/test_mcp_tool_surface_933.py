"""#933 MCP 工具面补全契约（RED 阶段测试契约，spec f20 §2.2/§4.1/§13 A7-A11）。

覆盖三新工具 + write 扩 actions 的**行为契约**（实现方：`mcp/tools/`）：

1. `manage_book`（P0）：plan_start/plan_respond/plan_auto/plan_show/plan_confirm +
   run/status/confirm/intervene/summary → 薄客户端转 `/agent/books/*`（F44）；
2. `write` 扩 actions（P1）：confirm_draft/reject_draft/draft_list → 转 `/agent/drafts*`
   （F27），**与 CLI `inkflow agent draft confirm` 同端点同 body 语义**；
3. `manage_config`（P2 只读）：provider_list/llm_status → GET `/provider-configs`
   （+ 可选 GET `/projects/{pid}/vector/status`）——**不暴露 set-key/PATCH 写面**；
4. `manage_log`（P2）：query → GET `/logs`（from_ts/to_ts → 查询参数 `from`/`to`）。

契约来源：issue #933（工具面覆盖缺口）+ F20 spec §2.2 映射表 + 内核 router 源码实证
（`api/routers/books.py` / `agent_runs.py` / `provider_configs.py` / `logs.py`）。
同批落地 #923 护栏扩展：**新工具 inputSchema ⊇ 对应 DTO 字段面**（防 extra/level 覆辙）。

── RED 形态说明 ─────────────────────────────────────────────────
`schemas` 模块缺 ManageBookParams/ManageConfigParams/ManageLogParams 且 WriteParams 缺
草稿字段；`mcp/tools/book_tools.py` / `inspect_tools.py` 不存在；`operation_tools._route_write`
无草稿分支；`MCP_TOOL_REGISTRY` 仍 15 项 → 本文件断言失败（ImportError / AttributeError /
AssertionError）。GREEN 落地后整文件转绿。

── 测试约定 ─────────────────────────────────────────────────────
- 只经公开面触发：`build_*_tool().func(**kwargs)`；禁直调私有 `_route_*`。
- 装配缝镜像 `test_mcp_tools.py`：func 内 lazy import 源头模块 → patch 命名空间
  `http_mod.InkFlowHTTPClient` 恒返回同一记录型 FakeClient。
- body 断言一律 `.get(...)`（缺键 → None → AssertionError，而非 KeyError）。
- async 用例显式 @pytest.mark.asyncio（pytest-asyncio STRICT）。
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.mcp.tools import MCP_TOOL_REGISTRY, build_mcp_tools
from inkflow.mcp.tools import schemas as schemas_mod

kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
http_mod = importlib.import_module("inkflow.infrastructure.http")

#: 新增工具名（spec §4.1 #16-18）
_NEW_TOOL_NAMES = ("manage_book", "manage_config", "manage_log")

#: 注册表全量顺序（spec §4.1 表；前 15 为既有面，16-18 为 #933 追加）
_EXPECTED_NAMES = [
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
    "manage_book",
    "manage_config",
    "manage_log",
]


class FakeClient:
    """记录型 fake：每次调用落 dict（method/path/params/json/timeout）。"""

    def __init__(self, handle):
        self.handle = handle
        self.calls: list[dict] = []
        self.response: object = {"id": "x", "name": "resp"}
        self.raw_response: str = "raw-text"

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    def _record(self, method: str, path: str, params, json, timeout=None) -> None:
        self.calls.append(
            {"method": method, "path": path, "params": params, "json": json, "timeout": timeout}
        )

    async def get(self, path, *, params=None, json=None) -> dict:
        self._record("GET", path, params, json)
        return self.response  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def post(self, path, *, params=None, json=None, timeout=None) -> dict:
        self._record("POST", path, params, json, timeout)
        return self.response  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def patch(self, path, *, params=None, json=None) -> dict:
        self._record("PATCH", path, params, json)
        return self.response  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def delete(self, path, *, params=None, json=None) -> dict:
        self._record("DELETE", path, params, json)
        return self.response  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def get_raw(self, path, *, params=None) -> str:
        self._record("GET_RAW", path, params, None)
        return self.raw_response


@pytest.fixture
def fake_env(monkeypatch):
    """装配缝（镜像 test_mcp_tools.py）：ensure_kernel → 鸭子 handle；client 恒同一实例。"""
    client = FakeClient(SimpleNamespace(port=1, token="t"))
    fake_ensure = AsyncMock(return_value=SimpleNamespace(port=1, token="t", pid=2, version="0.1.0"))
    monkeypatch.setattr(kernel_mod, "ensure_kernel", fake_ensure)
    monkeypatch.setattr(http_mod, "InkFlowHTTPClient", lambda handle: client)
    return SimpleNamespace(client=client, fake_ensure=fake_ensure)


def _envelope(text: str) -> dict:
    return json.loads(text)


def _last(client: FakeClient) -> dict:
    assert client.calls, "未发生 HTTP 调用"
    return client.calls[-1]


def _tool(module: str, builder: str):
    """lazy 取新工具工厂（RED：模块不存在 → ImportError）。"""
    mod = importlib.import_module(f"inkflow.mcp.tools.{module}")
    return getattr(mod, builder)()


def _book():
    return _tool("book_tools", "build_manage_book_tool")


def _config():
    return _tool("inspect_tools", "build_manage_config_tool")


def _log():
    return _tool("inspect_tools", "build_manage_log_tool")


class TestRegistrySurface933:
    """spec §4.1/§13 A7：注册表 18 项 + 新增工具名。"""

    def test_registry_has_18_tools(self):
        assert len(MCP_TOOL_REGISTRY) == 18

    def test_build_mcp_tools_returns_18(self):
        assert len(build_mcp_tools()) == 18

    def test_registry_names_match_spec_order(self):
        assert [t.spec.name for t in MCP_TOOL_REGISTRY] == _EXPECTED_NAMES

    def test_all_schemas_has_18_models(self):
        assert len(schemas_mod.ALL_SCHEMAS) == 18

    def test_new_schemas_registered(self):
        for name in ("ManageBookParams", "ManageConfigParams", "ManageLogParams"):
            assert name in schemas_mod.ALL_SCHEMAS

    def test_new_tools_have_non_empty_spec(self):
        by_name = {tool.spec.name: tool for tool in MCP_TOOL_REGISTRY}
        found = {name for name in _NEW_TOOL_NAMES if name in by_name}
        missing = set(_NEW_TOOL_NAMES) - found
        assert found == set(_NEW_TOOL_NAMES), f"注册表缺新工具 {sorted(missing)}"
        for name in _NEW_TOOL_NAMES:
            tool = by_name[name]
            assert tool.spec.description
            assert tool.spec.input_schema.get("type") == "object"


class TestSchemaContract933:
    """spec §2.2：三新模型 action 枚举 + 字段面；WriteParams 扩 actions/字段。"""

    def test_manage_book_actions_and_fields(self):
        model = schemas_mod.ManageBookParams
        assert model.model_json_schema()["properties"]["action"]["enum"] == [
            "plan_start",
            "plan_respond",
            "plan_auto",
            "plan_show",
            "plan_confirm",
            "run",
            "status",
            "confirm",
            "intervene",
            "summary",
        ]
        for field in (
            "project_id",
            "one_liner",
            "mode",
            "source_outline_id",
            "session_id",
            "answers",
            "auto",
            "confirm",
            "writing_plan_id",
            "limits",
            "config",
            "run_id",
            "approved",
            "decision",
            "intervene_action",
            "target",
            "to",
            "payload",
        ):
            assert field in model.model_fields, f"ManageBookParams 缺字段 {field}"
            assert field not in model.model_json_schema().get("required", [])

    def test_manage_config_actions_and_readonly_fields(self):
        model = schemas_mod.ManageConfigParams
        assert model.model_json_schema()["properties"]["action"]["enum"] == [
            "provider_list",
            "llm_status",
        ]
        assert "project_id" in model.model_fields

    def test_manage_log_query_action_and_filters(self):
        model = schemas_mod.ManageLogParams
        assert model.model_json_schema()["properties"]["action"]["enum"] == ["query"]
        for field in (
            "level",
            "caller_type",
            "project_id",
            "from_ts",
            "to_ts",
            "q",
            "correlation_id",
            "trace_id",
            "page",
            "limit",
        ):
            assert field in model.model_fields, f"ManageLogParams 缺字段 {field}"

    def test_write_actions_extended(self):
        model = schemas_mod.WriteParams
        assert model.model_json_schema()["properties"]["action"]["enum"] == [
            "generate",
            "continue",
            "revise",
            "confirm_draft",
            "reject_draft",
            "draft_list",
        ]

    def test_write_has_draft_fields(self):
        model = schemas_mod.WriteParams
        for field in ("draft_id", "status", "source_outline_id", "title"):
            assert field in model.model_fields, f"WriteParams 缺字段 {field}"


class TestSchemaDriftGuard933:
    """spec §13 A8（#923 护栏扩展）：新工具 Params ⊇ 对应 DTO 字段面。"""

    def test_book_params_superset_of_book_router_dtos(self):
        """ManageBookParams ⊇ F44 五个请求 DTO（action 因路由冲突豁免）。"""
        from inkflow.api.routers.books import (
            BookRunRequest,
            ConfirmRunRequest,
            InterveneRequest,
            PlannerRespondRequest,
            PlannerStartRequest,
        )

        params = set(schemas_mod.ManageBookParams.model_fields)
        for dto in (
            PlannerStartRequest,
            PlannerRespondRequest,
            BookRunRequest,
            ConfirmRunRequest,
            InterveneRequest,
        ):
            # InterveneRequest.action 与工具路由字段 action 同名冲突 → 用
            # intervene_action 承载，护栏按豁免处理（spec §2.2/§13 A8）。
            missing = set(dto.model_fields) - params - {"action"}
            assert missing == set(), f"{dto.__name__} 缺字段 {sorted(missing)}"

    def test_write_params_superset_of_draft_confirm_request(self):
        """WriteParams ⊇ ConfirmRequest（草稿确认 body 三字段）。"""
        from inkflow.api.routers.agent_runs import ConfirmRequest

        params = set(schemas_mod.WriteParams.model_fields)
        missing = set(ConfirmRequest.model_fields) - params
        assert missing == set(), f"ConfirmRequest 缺字段 {sorted(missing)}"

    def test_log_params_superset_of_logs_query_surface(self):
        """ManageLogParams ⊇ GET /logs 查询参数面（from_ts/to_ts 映射 from/to）。"""
        params = set(schemas_mod.ManageLogParams.model_fields)
        assert {
            "level",
            "caller_type",
            "project_id",
            "from_ts",
            "to_ts",
            "q",
            "correlation_id",
            "trace_id",
            "page",
            "limit",
        } <= params


class TestManageBookRouting933:
    """spec §2.2/§13 A9：manage_book 各 action → 内核端点（method/path/body）。"""

    @pytest.mark.asyncio
    async def test_plan_start(self, fake_env):
        env = _envelope(
            await _book().func(action="plan_start", project_id="p1", one_liner="少年登山")
        )
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["method"] == "POST"
        assert last["path"] == "/agent/books/planner"
        body = last["json"] or {}
        assert body.get("project_id") == "p1"
        assert body.get("one_liner") == "少年登山"
        assert "source_outline_id" not in body
        assert last["timeout"] is not None  # LLM 长任务：显式超时覆盖

    @pytest.mark.asyncio
    async def test_plan_start_mode_and_source_outline(self, fake_env):
        env = _envelope(
            await _book().func(
                action="plan_start",
                project_id="p1",
                one_liner="续写",
                mode="continue",
                source_outline_id="o1",
            )
        )
        assert env["ok"] is True
        body = _last(fake_env.client)["json"] or {}
        assert body.get("mode") == "continue"
        assert body.get("source_outline_id") == "o1"

    @pytest.mark.asyncio
    async def test_plan_respond_answers(self, fake_env):
        env = _envelope(
            await _book().func(
                action="plan_respond",
                session_id="s1",
                answers={"主角": "少年"},
                auto=False,
            )
        )
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["method"] == "POST"
        assert last["path"] == "/agent/books/planner/s1/respond"
        body = last["json"] or {}
        assert body.get("answers") == {"主角": "少年"}
        assert body.get("auto") is False
        assert "confirm" not in body

    @pytest.mark.asyncio
    async def test_plan_confirm(self, fake_env):
        env = _envelope(await _book().func(action="plan_confirm", session_id="s1"))
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["path"] == "/agent/books/planner/s1/respond"
        assert (last["json"] or {}).get("confirm") is True

    @pytest.mark.asyncio
    async def test_plan_auto_two_step(self, fake_env):
        """plan_auto = start → respond auto=true 两步（镜像 CLI plan auto）。"""
        fake_env.client.response = {"session_id": "s9", "completed": True}
        env = _envelope(
            await _book().func(action="plan_auto", project_id="p1", one_liner="全部你决定")
        )
        assert env["ok"] is True
        assert len(fake_env.client.calls) == 2
        first, second = fake_env.client.calls
        assert first["path"] == "/agent/books/planner"
        assert second["path"] == "/agent/books/planner/s9/respond"
        assert (second["json"] or {}).get("auto") is True

    @pytest.mark.asyncio
    async def test_plan_show(self, fake_env):
        env = _envelope(await _book().func(action="plan_show", session_id="s1"))
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["method"] == "GET"
        assert last["path"] == "/agent/books/planner/s1"

    @pytest.mark.asyncio
    async def test_run_with_limits_and_config(self, fake_env):
        env = _envelope(
            await _book().func(
                action="run",
                writing_plan_id="wp1",
                limits={"max_chapters": 3},
                mode="agentic",
                config={"max_steps": 5},
            )
        )
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["method"] == "POST"
        assert last["path"] == "/agent/books/runs"
        body = last["json"] or {}
        assert body.get("writing_plan_id") == "wp1"
        assert body.get("limits") == {"max_chapters": 3}
        assert body.get("mode") == "agentic"
        assert body.get("config") == {"max_steps": 5}

    @pytest.mark.asyncio
    async def test_status(self, fake_env):
        env = _envelope(await _book().func(action="status", run_id="r1"))
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["method"] == "GET"
        assert last["path"] == "/agent/books/runs/r1"

    @pytest.mark.asyncio
    async def test_confirm_run(self, fake_env):
        env = _envelope(
            await _book().func(action="confirm", run_id="r1", approved=True, decision="继续")
        )
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["path"] == "/agent/books/runs/r1/confirm"
        body = last["json"] or {}
        assert body.get("approved") is True
        assert body.get("decision") == "继续"

    @pytest.mark.asyncio
    async def test_intervene_maps_intervene_action_to_body_action(self, fake_env):
        env = _envelope(
            await _book().func(
                action="intervene",
                run_id="r1",
                intervene_action="redirect",
                target="o1",
                to="skip",
            )
        )
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["path"] == "/agent/books/runs/r1/intervene"
        body = last["json"] or {}
        assert body.get("action") == "redirect"
        assert body.get("target") == "o1"
        assert body.get("to") == "skip"

    @pytest.mark.asyncio
    async def test_summary(self, fake_env):
        env = _envelope(await _book().func(action="summary", run_id="r1"))
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["method"] == "GET"
        assert last["path"] == "/agent/books/runs/r1/summary"

    @pytest.mark.asyncio
    async def test_missing_required_args_no_http(self, fake_env):
        """缺必填 id → 本地 INVALID_ARGS 信封，零 HTTP 往返（spec §7 #16）。"""
        for kwargs in (
            {"action": "plan_start", "project_id": "p1"},  # 缺 one_liner
            {"action": "plan_respond"},  # 缺 session_id
            {"action": "run"},  # 缺 writing_plan_id
            {"action": "status"},  # 缺 run_id
            {"action": "intervene", "run_id": "r1"},  # 缺 intervene_action
        ):
            fake_env.client.calls.clear()
            env = _envelope(await _book().func(**kwargs))
            assert env["ok"] is False, f"{kwargs} 应本地拒绝"
            assert env["error"]["code"] == "INVALID_ARGS"
            assert fake_env.client.calls == []


class TestWriteDraftRouting933:
    """spec §13 A10：write 草稿 actions 与 CLI `agent draft confirm` 语义一致。"""

    @pytest.mark.asyncio
    async def test_confirm_draft_path_and_body(self, fake_env):
        tool = importlib.import_module("inkflow.mcp.tools.operation_tools").build_write_tool()
        env = _envelope(
            await tool.func(
                action="confirm_draft",
                draft_id="d1",
                chapter_id="c1",
                title="第一章",
                source_outline_id="o1",
            )
        )
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["method"] == "POST"
        assert last["path"] == "/agent/drafts/d1/confirm"
        body = last["json"] or {}
        assert body.get("chapter_id") == "c1"
        assert body.get("title") == "第一章"
        assert body.get("source_outline_id") == "o1"

    @pytest.mark.asyncio
    async def test_confirm_draft_omits_none_fields(self, fake_env):
        tool = importlib.import_module("inkflow.mcp.tools.operation_tools").build_write_tool()
        env = _envelope(await tool.func(action="confirm_draft", draft_id="d1"))
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["path"] == "/agent/drafts/d1/confirm"
        body = last["json"] or {}
        assert "chapter_id" not in body
        assert "title" not in body
        assert "source_outline_id" not in body

    @pytest.mark.asyncio
    async def test_reject_draft(self, fake_env):
        tool = importlib.import_module("inkflow.mcp.tools.operation_tools").build_write_tool()
        env = _envelope(await tool.func(action="reject_draft", draft_id="d1"))
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["method"] == "POST"
        assert last["path"] == "/agent/drafts/d1/reject"

    @pytest.mark.asyncio
    async def test_draft_list_filters(self, fake_env):
        tool = importlib.import_module("inkflow.mcp.tools.operation_tools").build_write_tool()
        env = _envelope(
            await tool.func(action="draft_list", project_id="p1", status="draft")
        )
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["method"] == "GET"
        assert last["path"] == "/agent/drafts"
        assert last["params"] == {"project_id": "p1", "status": "draft"}

    @pytest.mark.asyncio
    async def test_confirm_draft_missing_id_no_http(self, fake_env):
        tool = importlib.import_module("inkflow.mcp.tools.operation_tools").build_write_tool()
        env = _envelope(await tool.func(action="confirm_draft"))
        assert env["ok"] is False
        assert env["error"]["code"] == "INVALID_ARGS"
        assert fake_env.client.calls == []

    @pytest.mark.asyncio
    async def test_draft_list_missing_project_no_http(self, fake_env):
        tool = importlib.import_module("inkflow.mcp.tools.operation_tools").build_write_tool()
        env = _envelope(await tool.func(action="draft_list"))
        assert env["ok"] is False
        assert env["error"]["code"] == "INVALID_ARGS"
        assert fake_env.client.calls == []

    def test_confirm_draft_semantics_match_cli(self):
        """语义等价锚点：CLI `agent draft confirm` 同端点同 body 键集合。

        源码实证 `cli/commands/agent_cmd.py::draft_confirm` →
        POST /agent/drafts/{id}/confirm，body 键 ⊆ {chapter_id, title}；
        F27 API 另支持 source_outline_id（#976 D4）。MCP 侧须为同端点同键语义。
        """
        import inspect

        from inkflow.cli.commands import agent_cmd

        source = inspect.getsource(agent_cmd.draft_confirm)
        assert "/agent/drafts/{draft_id}/confirm" in source
        assert "chapter_id" in source
        assert "title" in source


class TestManageConfigRouting933:
    """spec §13 A11：manage_config 只读（provider_list / llm_status）。"""

    def test_description_readonly_no_set_key(self):
        desc = _config().spec.description
        assert "只读" in desc
        assert "set-key" not in desc.lower()
        assert "写入" not in desc

    @pytest.mark.asyncio
    async def test_provider_list(self, fake_env):
        env = _envelope(await _config().func(action="provider_list"))
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["method"] == "GET"
        assert last["path"] == "/provider-configs"

    @pytest.mark.asyncio
    async def test_llm_status_summary(self, fake_env):
        fake_env.client.response = {
            "items": [
                {
                    "name": "deepseek",
                    "key_saved": True,
                    "models": [{"id": "bge-m3", "type": "embedding"}],
                }
            ],
            "total": 1,
        }
        env = _envelope(await _config().func(action="llm_status"))
        assert env["ok"] is True
        data = env["data"]
        assert "providers" in data
        assert data["embedding_model"] == {"provider": "deepseek", "model_id": "bge-m3"}
        assert fake_env.client.calls[0]["path"] == "/provider-configs"
        # 无 project_id → 不查 vector status（单次 HTTP）
        assert len(fake_env.client.calls) == 1

    @pytest.mark.asyncio
    async def test_llm_status_with_project_adds_vector_status(self, fake_env):
        fake_env.client.response = {"items": [], "total": 0}
        env = _envelope(await _config().func(action="llm_status", project_id="p1"))
        assert env["ok"] is True
        paths = [c["path"] for c in fake_env.client.calls]
        assert paths == ["/provider-configs", "/projects/p1/vector/status"]
        assert env["data"]["embedding_model"] is None


class TestManageLogRouting933:
    """spec §2.2：manage_log query → GET /logs（from_ts/to_ts → from/to）。"""

    @pytest.mark.asyncio
    async def test_query_filters(self, fake_env):
        env = _envelope(
            await _log().func(
                action="query",
                level="WARN",
                caller_type="mcp",
                correlation_id="c1",
                from_ts="2026-01-01T00:00:00",
                to_ts="2026-01-02T00:00:00",
                limit=20,
            )
        )
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["method"] == "GET"
        assert last["path"] == "/logs"
        params = last["params"] or {}
        assert params.get("level") == "WARN"
        assert params.get("caller_type") == "mcp"
        assert params.get("correlation_id") == "c1"
        assert params.get("from") == "2026-01-01T00:00:00"
        assert params.get("to") == "2026-01-02T00:00:00"
        assert params.get("limit") == 20
        assert "q" not in params

    @pytest.mark.asyncio
    async def test_query_no_filters_allowed(self, fake_env):
        """无过滤参数合法（巡检默认全量分页）——不本地拒绝。"""
        env = _envelope(await _log().func(action="query"))
        assert env["ok"] is True
        last = _last(fake_env.client)
        assert last["path"] == "/logs"
        assert (last["params"] or {}) == {}


class TestToolSearchIncludesNew933:
    """spec §4.2：tool_search 与 tools/list 同源——新增工具须出现在自描述面。"""

    @pytest.mark.asyncio
    async def test_tool_search_lists_new_tools(self, fake_env):
        tool = importlib.import_module(
            "inkflow.mcp.tools.session_tools"
        ).build_tool_search_tool()
        env = _envelope(await tool.func(action="list"))
        assert env["ok"] is True
        by_name = {item["name"]: item for item in env["data"]}
        for name in _NEW_TOOL_NAMES:
            assert name in by_name, f"tool_search 缺 {name}"
            assert by_name[name]["actions"], f"{name} 无 action 枚举"
        assert "confirm_draft" in by_name["write"]["actions"]

class TestCoverageBranches933:
    """#933 新工具内部防御/循环分支覆盖（覆盖率门禁）。"""

    @pytest.mark.asyncio
    async def test_plan_auto_missing_session_id(self, fake_env):
        """planner start 响应无 session_id → INTERNAL_ERROR（零额外 HTTP）。"""
        fake_env.client.response = {"round": 1}  # 无 session_id
        env = _envelope(
            await _book().func(action="plan_auto", project_id="p1", one_liner="自动")
        )
        assert env["ok"] is False
        assert env["error"]["code"] == "INTERNAL_ERROR"
        assert len(fake_env.client.calls) == 1

    @pytest.mark.asyncio
    async def test_llm_status_loop_branches(self, fake_env):
        """llm_status 遍历防御分支：非 dict 项 / 无 models / 非 dict model / 命中 break。"""
        fake_env.client.response = {
            "items": [
                "not-a-dict",
                {"name": "p1"},
                {"name": "p2", "models": [None, {"id": "x", "type": "chat"}]},
                {"name": "p3", "models": [{"id": "emb", "type": "embedding"}]},
            ],
            "total": 4,
        }
        env = _envelope(await _config().func(action="llm_status"))
        assert env["ok"] is True
        assert env["data"]["embedding_model"] == {"provider": "p3", "model_id": "emb"}
