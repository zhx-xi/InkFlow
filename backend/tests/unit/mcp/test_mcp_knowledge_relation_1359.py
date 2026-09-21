"""#1359 RED 契约：跨实体知识图谱关系 MCP 工具（manage_knowledge_relation）。

## 背景（issue #1359）

`manage_tools.py` 的 `manage_relation` **只打 F9 角色关系三端点**
（`/characters/{id}/relations`）。而 `knowledge_relations` 才是图谱关系的真实承载表
（#495 后 `character_relations` 已并入本表的 character↔character 子空间）。

⇒ MCP 面只能操作角色↔角色子空间；跨实体关系
（character→world / →foreshadow / →timeline / →outline / →map_pin）
在 MCP 面**完全不可达**，而 GUI/CLI/HTTP 三面已有完整能力
（`api/routers/knowledge_graph.py` 六端点）。

## GREEN 义务（以本文件断言为准）

W1. 新增第 19 个工具 `manage_knowledge_relation`，进入 `MCP_TOOL_REGISTRY`
    （追加在末尾，**不改**既有 18 项顺序 → 不破坏既有 `test_registry_names_match_spec` 前缀）。
W2. 参数模型 `ManageKnowledgeRelationParams`（`mcp/tools/schemas.py`），
    `action: Literal["create","list","graph","get","update","delete"]` + 六元组可选字段。
    🔴 字段名与 `KnowledgeRelationCreate` **逐字对齐**：source_type / source_id /
    target_type / target_id / relation_type / description（笔误会被 Pydantic 静默丢弃，
    见 mcp-schema-drift-guard-923 第四形态）。
W3. 端点映射（对齐 `api/routers/knowledge_graph.py` 实证路由）：
      create → POST   /projects/{project_id}/knowledge-relations   json 六元组
      list   → GET    /projects/{project_id}/knowledge-relations   params 过滤+分页
      graph  → GET    /projects/{project_id}/knowledge-graph       params{scope}
      get    → GET    /knowledge-relations/{id}
      update → PATCH  /knowledge-relations/{id}                    json（剔 None）
      delete → DELETE /knowledge-relations/{id}
W4. 六元组校验复用服务层（`knowledge_graph_service.py` 校验链 ①-⑥ 已在 REST 侧就绪）：
    MCP 工具是**薄客户端**，不自建校验；服务层 422 经 `map_http_error` 映射为
    `VALIDATION_ERROR` 信封（透传语义）。
W5. 跨实体核心场景：character → world 关系可建。
W6. `tool_search` 自动覆盖新工具（本地装配 `MCP_TOOL_REGISTRY`，无需改代码）。

## RED 形态

`ManageKnowledgeRelationParams` 与 `build_manage_knowledge_relation_tool` 均不存在
→ 顶部 import 收集期 ImportError（整模块 RED）。注册表长度 18 ≠ 19。

## 测试约定

对齐 `test_mcp_tools.py`：FakeClient 有状态 fake + `fake_env` fixture（patch
`ensure_kernel` / `InkFlowHTTPClient`，返回**同一** client 实例）；信封 json.loads 断言。
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.mcp.tools import MCP_TOOL_REGISTRY, MCPTool, build_mcp_tools
from inkflow.mcp.tools.manage_tools import build_manage_knowledge_relation_tool
from inkflow.mcp.tools.schemas import ManageKnowledgeRelationParams

kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
http_mod = importlib.import_module("inkflow.infrastructure.http")

TOOL_NAME = "manage_knowledge_relation"

# 六元组字段名（🔴 与 KnowledgeRelationCreate 逐字对齐）
SIX_TUPLE = (
    "source_type",
    "source_id",
    "target_type",
    "target_id",
    "relation_type",
    "description",
)


class FakeClient:
    """有状态 fake：记录 (method, path, params, json)，async 上下文管理器。"""

    def __init__(self, handle):
        self.handle = handle
        self.calls: list[tuple[str, str, object, object]] = []
        self.response: object = {"id": "kr1", "relation_type": "归属"}

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, path, *, params=None, json=None) -> dict:
        self.calls.append(("GET", path, params, json))
        return self.response  # type: ignore[return-value]  # 鸭子 fake：response 预置为 object 但方法契约返回 dict

    async def post(self, path, *, params=None, json=None, timeout=None) -> dict:
        self.calls.append(("POST", path, params, json))
        return self.response  # type: ignore[return-value]  # 鸭子 fake：response 预置为 object 但方法契约返回 dict

    async def patch(self, path, *, params=None, json=None) -> dict:
        self.calls.append(("PATCH", path, params, json))
        return self.response  # type: ignore[return-value]  # 鸭子 fake：response 预置为 object 但方法契约返回 dict

    async def delete(self, path, *, params=None, json=None) -> dict:
        self.calls.append(("DELETE", path, params, json))
        return self.response  # type: ignore[return-value]  # 鸭子 fake：response 预置为 object 但方法契约返回 dict

    async def get_raw(self, path, *, params=None) -> str:
        self.calls.append(("GET_RAW", path, params, None))
        return "raw"


@pytest.fixture
def fake_env(monkeypatch):
    """装配缝：ensure_kernel → 鸭子 handle；InkFlowHTTPClient → 恒同一 client 实例。

    🔴 patch 必须返回**同一**预建实例（lambda 闭包）：func 内
    `async with InkFlowHTTPClient(handle)` 每次构造新实例，patch 成类则调用记录
    落在新实例上、预建实例恒空（test_mcp_tools.py 同款实测）。
    """
    client = FakeClient(SimpleNamespace(port=1, token="t"))
    fake_ensure = AsyncMock(return_value=SimpleNamespace(port=1, token="t", pid=2, version="0.1.0"))
    monkeypatch.setattr(kernel_mod, "ensure_kernel", fake_ensure)
    monkeypatch.setattr(http_mod, "InkFlowHTTPClient", lambda handle: client)
    return SimpleNamespace(client=client, fake_ensure=fake_ensure)


def _parse_envelope(text: str) -> dict:
    return json.loads(text)


def _last_call(client: FakeClient) -> tuple[str, str, object, object]:
    assert client.calls, "未发生 HTTP 调用"
    return client.calls[-1]


class TestRegistryAndSchema:
    """工具已注册 + schema 形态（W1/W2/W6）。"""

    def test_registry_has_19_tools(self):
        """新增第 19 个工具（#1359）。"""
        assert len(MCP_TOOL_REGISTRY) == 19

    def test_build_mcp_tools_returns_19(self):
        assert len(build_mcp_tools()) == 19

    def test_registry_preserves_existing_18_prefix(self):
        """既有 18 项顺序不变（追加在末尾）→ 不破坏既有工具面契约。"""
        names = [t.spec.name for t in MCP_TOOL_REGISTRY]
        assert names[:18] == [
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
        assert names[18:] == [TOOL_NAME]

    def test_new_tool_in_registry(self):
        assert TOOL_NAME in [t.spec.name for t in MCP_TOOL_REGISTRY]

    def test_tool_is_mcptool_with_spec(self):
        tool = build_manage_knowledge_relation_tool()
        assert isinstance(tool, MCPTool)
        assert tool.spec.name == TOOL_NAME
        assert tool.spec.description
        assert tool.spec.input_schema.get("type") == "object"

    def test_schema_action_enum(self):
        """action 枚举 = 六操作（对齐 REST 端点面）。"""
        schema = ManageKnowledgeRelationParams.model_json_schema()
        assert schema["properties"]["action"]["enum"] == [
            "create",
            "list",
            "graph",
            "get",
            "update",
            "delete",
        ]

    @pytest.mark.parametrize("field", SIX_TUPLE)
    def test_schema_has_six_tuple_field(self, field: str):
        """🔴 六元组字段名逐字冻结（防 schema 漂移静默丢数据）。"""
        schema = ManageKnowledgeRelationParams.model_json_schema()
        assert field in schema["properties"], f"字段名漂移：缺 {field}"

    def test_tool_search_covers_new_tool(self, fake_env):
        """tool_search 本地装配 → 自动覆盖新工具与 6 个 action（W6）。"""
        tool = next(t for t in MCP_TOOL_REGISTRY if t.spec.name == "tool_search")
        import asyncio

        envelope = _parse_envelope(asyncio.run(tool.func(action="list")))
        assert envelope["ok"] is True
        entry = next(item for item in envelope["data"] if item["name"] == TOOL_NAME)
        assert entry["description"]
        assert entry["actions"] == [
            "create",
            "list",
            "graph",
            "get",
            "update",
            "delete",
        ]


class TestCreate:
    """create → POST /projects/{pid}/knowledge-relations（六元组 body）。"""

    @pytest.mark.asyncio
    async def test_create_cross_entity_character_to_world(self, fake_env):
        """🔴 核心场景：跨实体 character → world 关系可建。"""
        tool = build_manage_knowledge_relation_tool()
        env = _parse_envelope(
            await tool.func(
                action="create",
                project_id="p1",
                source_type="character",
                source_id="c1",
                target_type="world",
                target_id="w1",
                relation_type="归属",
                description="角色隶属该势力",
            )
        )
        assert env["ok"] is True
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects/p1/knowledge-relations")
        assert body["source_type"] == "character" and body["source_id"] == "c1"
        assert body["target_type"] == "world" and body["target_id"] == "w1"
        assert body["relation_type"] == "归属"
        assert body["description"] == "角色隶属该势力"

    @pytest.mark.asyncio
    async def test_create_compact_drops_none(self, fake_env):
        """未传字段不出现在 body（httpx 把 None 编码空串 → 422 陷阱）。"""
        tool = build_manage_knowledge_relation_tool()
        await tool.func(
            action="create",
            project_id="p1",
            source_type="character",
            source_id="c1",
            target_type="foreshadow",
            target_id="f1",
            relation_type="伏笔",
        )
        _, _, _, body = _last_call(fake_env.client)
        assert "description" not in body
        assert set(body) == {
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
        }


class TestListGraphGet:
    """list → 过滤列表；graph → 聚合视图（scope）；get → 详情。"""

    @pytest.mark.asyncio
    async def test_list_with_filters_and_paging(self, fake_env):
        tool = build_manage_knowledge_relation_tool()
        await tool.func(
            action="list",
            project_id="p1",
            source_type="character",
            target_type="world",
            relation_type="归属",
            offset=10,
            limit=20,
        )
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects/p1/knowledge-relations")
        assert params["source_type"] == "character"
        assert params["target_type"] == "world"
        assert params["relation_type"] == "归属"
        assert params["offset"] == 10 and params["limit"] == 20

    @pytest.mark.asyncio
    async def test_list_without_filters_omits_query(self, fake_env):
        tool = build_manage_knowledge_relation_tool()
        await tool.func(action="list", project_id="p1")
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects/p1/knowledge-relations")
        assert not params

    @pytest.mark.asyncio
    async def test_graph_scope_related(self, fake_env):
        tool = build_manage_knowledge_relation_tool()
        await tool.func(action="graph", project_id="p1", scope="related")
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects/p1/knowledge-graph")
        assert params == {"scope": "related"}

    @pytest.mark.asyncio
    async def test_graph_scope_all(self, fake_env):
        tool = build_manage_knowledge_relation_tool()
        await tool.func(action="graph", project_id="p1", scope="all")
        _, _, params, _ = _last_call(fake_env.client)
        assert params == {"scope": "all"}

    @pytest.mark.asyncio
    async def test_get(self, fake_env):
        tool = build_manage_knowledge_relation_tool()
        await tool.func(action="get", id="kr1")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/knowledge-relations/kr1")


class TestUpdateDelete:
    """update → PATCH；delete → DELETE（扁平路径）。"""

    @pytest.mark.asyncio
    async def test_update_partial(self, fake_env):
        tool = build_manage_knowledge_relation_tool()
        await tool.func(action="update", id="kr1", relation_type="敌对")
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("PATCH", "/knowledge-relations/kr1")
        assert body == {"relation_type": "敌对"}

    @pytest.mark.asyncio
    async def test_update_full_six_tuple(self, fake_env):
        tool = build_manage_knowledge_relation_tool()
        await tool.func(
            action="update",
            id="kr1",
            source_type="character",
            source_id="c1",
            target_type="timeline",
            target_id="t1",
            relation_type="发生于",
            description="改终点实体",
        )
        _, _, _, body = _last_call(fake_env.client)
        assert body["target_type"] == "timeline" and body["target_id"] == "t1"
        assert body["relation_type"] == "发生于"
        assert body["description"] == "改终点实体"

    @pytest.mark.asyncio
    async def test_delete(self, fake_env):
        tool = build_manage_knowledge_relation_tool()
        await tool.func(action="delete", id="kr1")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("DELETE", "/knowledge-relations/kr1")


class TestErrorMapping:
    """服务层校验透传（W4）：422 → VALIDATION_ERROR 信封。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "detail", "expect_code"),
        [
            (422, "自环：起点与终点不能是同一实体", "VALIDATION_ERROR"),
            (422, "同键关系已存在", "VALIDATION_ERROR"),
            (404, "关系不存在", "NOT_FOUND"),
            (404, "项目不存在", "NOT_FOUND"),
        ],
    )
    async def test_http_error_mapped(
        self, fake_env, monkeypatch, status: int, detail: str, expect_code: str
    ):
        """服务层 422/404 → 结构化错误信封（对齐 test_mcp_tools_errors 形态）。"""
        from inkflow.infrastructure.http import HttpApiError

        class FailingClient(FakeClient):
            async def post(self, path, *, params=None, json=None, timeout=None) -> dict:
                raise HttpApiError(status_code=status, detail=detail)

        monkeypatch.setattr(http_mod, "InkFlowHTTPClient", FailingClient)
        tool = build_manage_knowledge_relation_tool()
        env = _parse_envelope(
            await tool.func(
                action="create",
                project_id="p1",
                source_type="character",
                source_id="c1",
                target_type="world",
                target_id="w1",
                relation_type="归属",
            )
        )
        assert env["ok"] is False
        assert env["error"]["code"] == expect_code, (
            f"期望 {expect_code}，实际 {env['error']}（detail={detail}）"
        )
        assert env["error"]["hint"]

    @pytest.mark.asyncio
    async def test_invalid_args_envelope(self, fake_env):
        """action 非法 → INVALID_ARGS 信封（不触 HTTP）。"""
        tool = build_manage_knowledge_relation_tool()
        env = _parse_envelope(await tool.func(action="bogus"))
        assert env["ok"] is False
        assert env["error"]["code"] == "INVALID_ARGS"
        assert not fake_env.client.calls


class TestToolBoundary:
    """与 manage_relation 的边界（issue #1359「不做」节：两者并存不互替）。"""

    def test_both_tools_coexist(self):
        """两个工具并存，各有独立 action 面（不改既有 manage_relation）。"""
        names = [t.spec.name for t in MCP_TOOL_REGISTRY]
        assert "manage_relation" in names
        assert TOOL_NAME in names

    def test_description_states_boundary(self):
        """描述点明边界，引导 LLM 正确选工具（避免两工具混用）。"""
        tool = build_manage_knowledge_relation_tool()
        assert "manage_relation" in tool.spec.description

    def test_manage_relation_action_enum_unchanged(self):
        """既有 F9 工具 action 面不变（向后兼容）。"""
        from inkflow.mcp.tools.schemas import ManageRelationParams

        schema = ManageRelationParams.model_json_schema()
        assert schema["properties"]["action"]["enum"] == [
            "create",
            "list",
            "get",
            "update",
            "delete",
        ]
