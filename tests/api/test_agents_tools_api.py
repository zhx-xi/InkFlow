"""#955 F58 §3 契约升级 — GET /api/v1/agents/tools 工具目录
（34 自定义工具 + domain/op + 路由顺序硬契约）。

自 tests/api/test_agents_api.py 拆出（#838 统一 35 工具目录契约，2026-08-31）。
#955 F58 §3 契约升级（F58 spec 取代 #854/#838 平铺目录契约）：
- 目录从全量 44 工具收敛为 34 自定义工具（is_core=True 的 10 核心工具不进目录：
  agent_run/agent_call + 8 个 delete/memory_remove）。
- 每项 6 键 → 8 键：新增 `domain` / `op` 两键（GRANT_TOOL_MAP 格值，
  contract-955 §3 GRANT_TOOL_MAP + §4 catalog 升级）。
- CORE_TOOL_NAMES 断言反转：核心 10 工具「不出现在 items」。
参考：contract-955 §3（契约升级迁移处置）+ specs/f58-agent-tool-scope/spec.md
§3.2（工具目录端点）+ spec §2.1（GRANT_TOOL_MAP）。

【G】守护：`test_tools_route_not_swallowed_by_agent_id`（200 路由顺序，既有行为
守护，契约升级不破坏，保持不动）；catalog 用例随 #955 契约升级改断言（RED）。
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
    "update_character",
    "update_world_setting",
    "list_outlines",
    "get_outline",
    "list_plot_points",
    "create_overall_outline",
    "create_volume_outline",
    "create_chapter_outline",
    "update_volume_outline",
    "update_chapter_outline",
    "create_plot_point",
    "update_plot_point",
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
    "delete_plot_point",
    "delete_map",
    "delete_timeline_event",
    "delete_foreshadowing",
    "memory_remove",
    "agent_run",
    "agent_call",
]
"""ALL_TOOL_SPECS 全量 44 工具全集（10 组，含 10 核心工具，仅作全集参考；
catalog 端点按 #955 F58 §3 只返回 34 自定义工具）。"""

CORE_TOOL_NAMES = {
    "agent_run",
    "agent_call",
    "delete_character",
    "delete_world_setting",
    "delete_outline",
    "delete_plot_point",
    "delete_map",
    "delete_timeline_event",
    "delete_foreshadowing",
    "memory_remove",
}
"""#838 核心工具（allow_custom_agent=False，is_core=True，不进 TOOL_REGISTRY）。
#955 F58 §3：这 10 个工具**不在** catalog 响应 items 中。"""

EXPECTED_TOOL_NAMES = set(ALL_TOOL_NAMES)
"""ALL_TOOL_SPECS 全量 44 名字全集（含核心）。"""

CUSTOM_TOOL_NAMES = EXPECTED_TOOL_NAMES - CORE_TOOL_NAMES
"""#955 F58 §3 自定义 Agent 可见工具（allow_custom_agent=True，is_core=False，
= catalog 响应 items 全集，34 个，= TOOL_REGISTRY）。"""

EXPECTED_DOMAIN_OP = {
    "search_characters": ("character", "read"),
    "check_foreshadowing": ("foreshadowing", "read"),
    "get_prior_summary": ("writing", "read"),
    "audit_chapter": ("writing", "read"),
    "count_words": ("writing", "read"),
    "save_draft": ("writing", "write"),
    "create_character": ("character", "write"),
    "create_world_setting": ("world", "write"),
    "update_character": ("character", "write"),
    "update_world_setting": ("world", "write"),
    "list_outlines": ("outline", "read"),
    "get_outline": ("outline", "read"),
    "list_plot_points": ("outline", "read"),
    "create_overall_outline": ("outline", "write"),
    "create_volume_outline": ("outline", "write"),
    "create_chapter_outline": ("outline", "write"),
    "update_volume_outline": ("outline", "write"),
    "update_chapter_outline": ("outline", "write"),
    "create_plot_point": ("outline", "write"),
    "update_plot_point": ("outline", "write"),
    "list_maps": ("world", "read"),
    "create_map": ("world", "write"),
    "update_map": ("world", "write"),
    "list_timeline_events": ("timeline", "read"),
    "create_timeline_event": ("timeline", "write"),
    "update_timeline_event": ("timeline", "write"),
    "create_foreshadowing": ("foreshadowing", "write"),
    "update_foreshadowing": ("foreshadowing", "write"),
    "memory_list": ("memory", "read"),
    "memory_add": ("memory", "write"),
    "memory_update": ("memory", "write"),
    "generate": ("writing", "write"),
    "continue": ("writing", "write"),
    "revise": ("writing", "write"),
}
"""#955 F58 §3 每工具 (domain, op) 格值表——34 自定义工具逐字来自
contract-955 §3 GRANT_TOOL_MAP（值 = TOOL_NAME_TO_CELL 反查）。"""


def _assert_tool_entry(tool: dict) -> None:
    """工具目录单项契约（#954 F58 §3.2）：8 键 = 原 6 键 + domain + op。
    {name, description, group, input_schema, allow_custom_agent, is_core,
    domain, op}。"""
    assert isinstance(tool, dict)
    for key in (
        "name",
        "description",
        "group",
        "input_schema",
        "allow_custom_agent",
        "is_core",
        "domain",
        "op",
    ):
        assert key in tool, f"工具目录项缺少契约字段 {key}"
    assert isinstance(tool["name"], str) and tool["name"] != ""
    assert isinstance(tool["description"], str)
    assert tool["group"] in TOOL_GROUPS, f"未知分组: {tool['group']}"
    assert isinstance(tool["input_schema"], dict)
    assert isinstance(tool["allow_custom_agent"], bool)
    assert isinstance(tool["is_core"], bool)
    assert isinstance(tool["domain"], str) and tool["domain"] != ""
    assert isinstance(tool["op"], str) and tool["op"] != ""


def _assert_tool_catalog(items: list) -> None:
    """工具目录整体契约（#955 F58 §3）：34 自定义工具全集 + 每项 8 键 +
    核心 10 工具不出现在 items + 每工具 domain/op == GRANT_TOOL_MAP 格值。"""
    assert isinstance(items, list)
    names = [t["name"] for t in items]
    assert len(items) == 34, f"工具目录应含 34 自定义工具: {len(items)}"
    assert set(names) == CUSTOM_TOOL_NAMES, f"工具目录名字全集不符: {names}"
    by_name = {t["name"]: t for t in items}
    for tool in items:
        _assert_tool_entry(tool)
    # #955 F58 §3：核心 10 工具不进目录（is_core 过滤），断言反转为「不出现在 items」
    for n in CORE_TOOL_NAMES:
        assert n not in names, f"核心工具 {n} 不应出现在目录（#955 F58 is_core 过滤）"
    # #955 F58 §3：34 自定义工具 allow_custom_agent=True / is_core=False，
    # domain/op == contract §3 GRANT_TOOL_MAP 格值
    for n in CUSTOM_TOOL_NAMES:
        assert by_name[n]["allow_custom_agent"] is True, f"{n} 应 allow_custom_agent=True"
        assert by_name[n]["is_core"] is False, f"{n} 应为 is_core=False"
        domain, op = EXPECTED_DOMAIN_OP[n]
        assert by_name[n]["domain"] == domain, (
            f"{n} domain 应为 {domain}: {by_name[n]['domain']}"
        )
        assert by_name[n]["op"] == op, f"{n} op 应为 {op}: {by_name[n]['op']}"
    assert len(CUSTOM_TOOL_NAMES) == 34, "自定义 Agent 可见工具应为 34"
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
    """工具目录端点契约（设计假设 #3/#6 + #954 F58 §3.2，M2 验收）。

    路由顺序硬契约的验证机制：若 GREEN 实现把 `GET /tools` 声明在
    `GET /{agent_id}` 之后，"tools" 会被 {agent_id} 路径参数捕获 →
    _parse_id 解析失败 → 404「Agent 不存在」→ 下方 200 断言 FAIL。
    """

    async def test_tools_route_not_swallowed_by_agent_id(
        self, client, db_session, override_get_db
    ):
        """【G】GET /api/v1/agents/tools → 200（非 404）+ 顶层含 items 键。"""
        resp = await client.get(ENDPOINT_TOOLS)
        assert (
            resp.status_code == 200
        ), f"/tools 被 /{{agent_id}} 吞（路由顺序错）或端点未实现: {resp.status_code}"
        body = resp.json()
        assert isinstance(body, dict)
        assert "items" in body

    async def test_tools_catalog_34_custom_tools_with_domain_op(
        self, client, db_session, override_get_db
    ):
        """【R】#955 F58 §3：34 自定义工具全集 + 每项 8 键（+domain/op）+
        核心 10 工具不在 items + 每工具 domain/op == GRANT_TOOL_MAP 格值。"""
        resp = await client.get(ENDPOINT_TOOLS)
        assert resp.status_code == 200
        items = resp.json()["items"]
        _assert_tool_catalog(items)
