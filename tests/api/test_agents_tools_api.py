"""F39/#838 工具目录端点契约 — GET /api/v1/agents/tools（35 工具 + 双标记 + 路由顺序硬契约）。

自 tests/api/test_agents_api.py 拆出（#838 统一 35 工具目录契约，2026-08-31）。
契约：#838 ToolSpec allow_custom_agent/is_core 标记；GET /agents/tools 返回全量 35 项，
每项含 name/description/group/input_schema/allow_custom_agent/is_core 六键。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import inkflow.api.routers.agents  # noqa: F401  # 模块存在性契约（GREEN 后即被使用）
from inkflow.api.app import app

ENDPOINT_TOOLS = "/api/v1/agents/tools"
"""工具目录端点（spec §3.1；路由顺序硬契约 #3）。"""

TOOL_GROUPS = ("writing", "retrieval", "audit", "project")
"""工具目录四分组键（spec §2.3，D2 勾选 UI 用）。"""

ALL_TOOL_NAMES = [
    "search_characters",
    "check_foreshadowing",
    "get_prior_summary",
    "audit_chapter",
    "count_words",
    "save_draft",
    "create_character",
    "create_world_setting",
    "create_outline",
    "update_character",
    "update_world_setting",
    "update_outline",
    "list_maps",
    "create_map",
    "update_map",
    "list_timeline_events",
    "create_timeline_event",
    "update_timeline_event",
    "create_foreshadowing",
    "update_foreshadowing",
    "memory_list",
    "memory_add",
    "memory_update",
    "generate",
    "continue",
    "revise",
    "delete_character",
    "delete_world_setting",
    "delete_outline",
    "delete_map",
    "delete_timeline_event",
    "delete_foreshadowing",
    "memory_remove",
    "agent_run",
    "agent_call",
]
"""#838 统一 35 工具目录全集（9 组，ALL_TOOL_SPECS 顺序）。"""

CORE_TOOL_NAMES = {
    "agent_run",
    "agent_call",
    "delete_character",
    "delete_world_setting",
    "delete_outline",
    "delete_map",
    "delete_timeline_event",
    "delete_foreshadowing",
    "memory_remove",
}
"""#838 核心工具（allow_custom_agent=False，is_core=True，不进 TOOL_REGISTRY）。"""

EXPECTED_TOOL_NAMES = set(ALL_TOOL_NAMES)
"""#838 统一 35 工具目录名字全集。"""

CUSTOM_TOOL_NAMES = EXPECTED_TOOL_NAMES - CORE_TOOL_NAMES
"""#838 自定义 Agent 可见工具（allow_custom_agent=True，26 个，= TOOL_REGISTRY）。"""

def _assert_tool_entry(tool: dict) -> None:
    """工具目录单项契约（#838）：{name, description, group, input_schema,
    allow_custom_agent, is_core}。"""
    assert isinstance(tool, dict)
    for key in ("name", "description", "group", "input_schema", "allow_custom_agent", "is_core"):
        assert key in tool, f"工具目录项缺少契约字段 {key}"
    assert isinstance(tool["name"], str) and tool["name"] != ""
    assert isinstance(tool["description"], str)
    assert tool["group"] in TOOL_GROUPS, f"未知分组: {tool['group']}"
    assert isinstance(tool["input_schema"], dict)
    assert isinstance(tool["allow_custom_agent"], bool)
    assert isinstance(tool["is_core"], bool)


def _assert_tool_catalog(items: list) -> None:
    """工具目录整体契约（#838）：35 工具全集 + 每项 6 键 + 核心/自定义标记。"""
    assert isinstance(items, list)
    names = [t["name"] for t in items]
    assert len(items) == 35, f"工具目录应含 35 工具: {len(items)}"
    assert set(names) == EXPECTED_TOOL_NAMES, f"工具目录名字全集不符: {names}"
    by_name = {t["name"]: t for t in items}
    for tool in items:
        _assert_tool_entry(tool)
    # #838 标记契约：9 核心工具 allow_custom_agent=False + is_core=True；26 自定义反之
    core = {n for n, t in by_name.items() if not t["allow_custom_agent"]}
    assert core == CORE_TOOL_NAMES, f"allow_custom_agent=False 集合不符: {core}"
    for n in CORE_TOOL_NAMES:
        assert by_name[n]["is_core"] is True, f"{n} 应为 is_core=True"
    for n in CUSTOM_TOOL_NAMES:
        assert by_name[n]["allow_custom_agent"] is True, f"{n} 应 allow_custom_agent=True"
        assert by_name[n]["is_core"] is False, f"{n} 应为 is_core=False"
    assert len(CUSTOM_TOOL_NAMES) == 26, "自定义 Agent 可见工具应为 26"
    save_draft = by_name["save_draft"]
    assert save_draft["group"] == "writing"
    assert save_draft["allow_custom_agent"] is True

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（spec §2.3.1）：本文件全部用例依赖未设置 → 直通。"""


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，镜像 test_agents_api.py #1/#2 同款 + 无 token 模式）。

    显式 delenv INKFLOW_SERVER_TOKEN → token 中间件直通；ASGITransport 不触发
    lifespan，建表由 test_engine fixture 完成。
    """
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── GET /api/v1/agents/tools（spec §3.1 工具目录 + 路由顺序硬契约）──


@pytest.mark.asyncio
@pytest.mark.api
class TestToolCatalog:
    """工具目录端点契约（设计假设 #3/#6，M2 验收）。

    路由顺序硬契约的验证机制：若 GREEN 实现把 `GET /tools` 声明在
    `GET /{agent_id}` 之后，"tools" 会被 {agent_id} 路径参数捕获 →
    _parse_id 解析失败 → 404「Agent 不存在」→ 下方 200 断言 FAIL。
    """

    async def test_tools_route_not_swallowed_by_agent_id(
        self, client, db_session, override_get_db
    ):
        """GET /api/v1/agents/tools → 200（非 404）+ 顶层含 items 键（#3）。"""
        resp = await client.get(ENDPOINT_TOOLS)
        assert (
            resp.status_code == 200
        ), f"/tools 被 /{{agent_id}} 吞（路由顺序错）或端点未实现: {resp.status_code}"
        body = resp.json()
        assert isinstance(body, dict)
        assert "items" in body

    async def test_tools_catalog_35_tools_with_markers(
        self, client, db_session, override_get_db
    ):
        """工具目录：35 工具全集 + 每项 6 键（含 allow_custom_agent/is_core）+ 核心标记（#838）。"""
        resp = await client.get(ENDPOINT_TOOLS)
        assert resp.status_code == 200
        items = resp.json()["items"]
        _assert_tool_catalog(items)
