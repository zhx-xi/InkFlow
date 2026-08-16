"""F20 MCP 工具工厂端点映射契约（M2 验收）— spec §2.2/§4/§9（Issue #49，RED 阶段测试契约）。

15 个 MCP 工具工厂（Q1=A 聚合 manage_* / Q2=A 契约同源）：
- manage_tools.py:   build_manage_project_tool / build_manage_chapter_tool /
                     build_manage_character_tool / build_manage_relation_tool /
                     build_manage_timeline_tool / build_manage_world_tool /
                     build_manage_outline_tool / build_manage_foreshadowing_tool（8 个）
- operation_tools.py: build_write_tool / build_audit_tool / build_extract_tool /
                      build_export_tool / build_search_tool（5 个）
- session_tools.py:  build_manage_session_tool / build_tool_search_tool（2 个）

每个工厂返回 MCPTool（mcp/tools/__init__.py 定义：spec: ToolSpec + func）。
func 签名：async def func(**kwargs) -> str（信封 JSON 字符串，对齐 F26 _ok/_fail）。

── GREEN 实现契约 ────────────────────────────────────────────────
1. MCPTool（mcp/tools/__init__.py）：
   - @dataclass: spec: ToolSpec / func: Callable[..., Awaitable[str]]
   - ToolSpec 直接复用 F26（inkflow.domain.models.agent_tools，import 不复制）。
   - MCP_TOOL_REGISTRY: list[MCPTool]（15 项，顺序 = spec §4.1 表）+
     build_mcp_tools() -> list[MCPTool]（装配工厂函数，tools/list 数据源）。

2. 工具 func 内部访问 client 的形态（🔴 load-bearing，测试 patch 依赖此形态）：
   - func 内部 **延迟 import**（函数体内 `from inkflow.infrastructure.http import
     InkFlowHTTPClient, HttpApiError, map_http_error` + `from
     inkflow.infrastructure.kernel import ensure_kernel, KernelStartupError`）——
     每次调用从 sys.modules 重新取属性，monkeypatch 模块属性动态生效
     （规则 1e 逃生门形态；禁模块级 from-import 绑定，否则 patch 不命中）。
   - 调用链：handle = await ensure_kernel() → async with
     InkFlowHTTPClient(handle) as client: → 端点调用 → _ok(_serialize_data(data))。
   - 异常映射（spec §3.3）：HttpApiError → map_http_error(status, detail, code)
     → error 文本含 F7 错误码（如 "NOT_FOUND: ..."）；KernelStartupError →
     "内核启动失败: ..."；其余异常 → str(exc)（对齐 F26 _fail）。

3. 端点映射（method/path/body/params，实证 F38 §3.1 + router 源码）：
   manage_project:  create→POST /projects json{name,genre,language,target_words}
                    list→GET /projects params{search} | get→GET /projects/{id}
                    update→PATCH /projects/{id} json | delete→DELETE /projects/{id}
                    params{permanent} | restore→POST /projects/{id}/restore
   manage_chapter:  create→POST /projects/{pid}/chapters json{title,volume_id,content}
                    list→GET /projects/{pid}/chapters params{volume_id,status}
                    get→GET /chapters/{cid} | update→PATCH /chapters/{cid} json
                    delete→DELETE /chapters/{cid} | move→POST /chapters/{cid}/move
                    json{to_volume}
   manage_character: create→POST /projects/{pid}/characters json{name,personality,
                    background,goals,group_id} | list→GET /projects/{pid}/characters
                    params{search,group_id} | get→GET /characters/{id}
                    update→PATCH /characters/{id} json | delete→DELETE /characters/{id}
                    restore→POST /characters/{id}/restore
   manage_relation: create→POST /characters/{cid}/relations json{source_id,
                    target_id,relation_type} | list→GET /characters/{cid}/relations
                    update→PATCH /characters/{cid}/relations/{rid} json
                    delete→DELETE /characters/{cid}/relations/{rid}
   manage_timeline: create→POST /projects/{pid}/timeline/events json | list→GET
                    /projects/{pid}/timeline/events params{search} | get→GET
                    /timeline/events/{id} | update→PATCH /timeline/events/{id} json
                    delete→DELETE /timeline/events/{id} | check→GET
                    /projects/{pid}/timeline/check
   manage_world:    create→POST /projects/{pid}/world-settings json{name,category,
                    content,parent} | list→GET /projects/{pid}/world-settings
                    params{search,category} | get→GET /world-settings/{id}
                    update→PATCH /world-settings/{id} json | delete→DELETE
                    /world-settings/{id} | restore→POST /world-settings/{id}/restore
   manage_outline:  create→POST /projects/{pid}/outlines json{name,description,
                    sort_order} | list→GET /projects/{pid}/outlines params{search}
                    get→GET /outlines/{id} | update→PATCH /outlines/{id} json
                    delete→DELETE /outlines/{id} | generate→POST /outlines/generate
                    json{project_id,name,prompt,num_chapters}
   manage_foreshadowing: create→POST /projects/{pid}/foreshadowings
                    json{title,description,priority,location,event_id} | list→GET
                    /projects/{pid}/foreshadowings params{status,search} | get→GET
                    /foreshadowings/{id} | update→PATCH /foreshadowings/{id} json
                    delete→DELETE /foreshadowings/{id} | resolve→POST
                    /foreshadowings/{id}/resolve | reopen→POST
                    /foreshadowings/{id}/reopen
   write:           generate→POST /writing/generate json{project_id,chapter_id,
                    outline,context,...} | continue→POST /writing/continue
                    json{project_id,chapter_id,existing_content,target_words,...}
                    revise→POST /writing/revise json{project_id,chapter_id,content,
                    feedback,target_range,...}
   audit:           project→GET /projects/{pid}/audit | chapter→POST
                    /projects/{pid}/chapters/{cid}/audit json{include_static}
   extract:         extract→POST /extract json{content,...} | reindex→POST
                    /projects/{pid}/vector/reindex json{entity_types} | retrieve→POST
                    /projects/{pid}/vector/retrieve json{query,top_k,min_score}
   export:          export→GET /projects/{pid}/export params{format}（get_raw）
   search:          search→GET /search params{q,project_id,types,limit,offset}
   manage_session:  create→POST /sessions json{session_type,project_id,title,
                    description} | list→GET /sessions params{session_type,status,
                    project_id,search} | get→GET /sessions/{id} |
                    pause/resume/complete/fail→POST /sessions/{id}/pause 等 |
                    add_log→POST /sessions/{id}/logs json
   tool_search:     list→本地装配结果（不经 HTTP，spec §7 #15）——信封
                    data = [{"name": ..., "description": ..., "actions": [...]}, ...]

── RED 形态说明 ─────────────────────────────────────────────────
inkflow.mcp.tools 包整个不存在 → 顶部 import 收集期 ModuleNotFoundError
（exit 2，规则 1c 整模块 RED）。GREEN 落地后自动转绿。

── 测试约定 ─────────────────────────────────────────────────────
- pytest-asyncio 1.x STRICT 模式：async 用例显式 @pytest.mark.asyncio。
- 测试经 monkeypatch.setattr 替换模块属性（延迟 import 命中）：
    kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
    http_mod = importlib.import_module("inkflow.infrastructure.http")
    monkeypatch.setattr(kernel_mod, "ensure_kernel", fake_ensure)
    monkeypatch.setattr(http_mod, "InkFlowHTTPClient", FakeClient)
  fake_ensure 返回 SimpleNamespace(port=1, token="t")（KernelHandle 鸭子）；
  FakeClient 是**有状态类**（__init__ 记 handle；calls 列表记
  (method, path, params, json)；async 上下文管理器；预置响应）。
- 断言信封：json.loads(await tool.func(action=..., ...)) → {"ok": True, "data": ...}
  或 {"ok": False, "error": "..."}（错误映射码前缀断言）。
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# 主契约：inkflow.mcp.tools 包不存在 → 收集期 ModuleNotFoundError（规则 1c）
from inkflow.mcp.tools import MCP_TOOL_REGISTRY, MCPTool, build_mcp_tools
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


class TestRegistryContract:
    """注册表 + 工厂面（spec §4.1 15 工具 / §4.2 同源）。"""

    def test_registry_has_15_tools(self):
        assert len(MCP_TOOL_REGISTRY) == 15

    def test_build_mcp_tools_returns_15(self):
        assert len(build_mcp_tools()) == 15

    def test_registry_names_match_spec(self):
        expected = [
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
        assert [t.spec.name for t in MCP_TOOL_REGISTRY] == expected

    def test_registry_tools_have_specs(self):
        for tool in MCP_TOOL_REGISTRY:
            assert isinstance(tool, MCPTool)
            assert tool.spec.name
            assert tool.spec.description
            assert tool.spec.input_schema.get("type") == "object"

    def test_tool_search_tool_local(self):
        """tool_search 是本地工具：data 含工具面清单（name/description/actions）。"""
        tool = next(t for t in MCP_TOOL_REGISTRY if t.spec.name == "tool_search")
        envelope = _parse_envelope(await_call(tool, action="list"))
        assert envelope["ok"] is True
        names = [item["name"] for item in envelope["data"]]
        assert "manage_project" in names and "tool_search" in names
        for item in envelope["data"]:
            assert item["description"]
            assert item["actions"]


def await_call(tool: MCPTool, **kwargs) -> str:
    """同步包装：await 工具 func（async 用例内调用）。"""
    import asyncio

    return asyncio.run(tool.func(**kwargs))


class TestManageProject:
    """manage_project 端点映射（6 actions）。"""

    @pytest.mark.asyncio
    async def test_create(self, fake_env):
        tool = build_manage_project_tool()
        env = _parse_envelope(
            await tool.func(
                action="create", name="星辰变", genre="玄幻", language="zh-CN", target_words=50000
            )
        )
        assert env["ok"] is True
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects")
        assert body["name"] == "星辰变" and body["genre"] == "玄幻"
        assert body["language"] == "zh-CN" and body["target_words"] == 50000

    @pytest.mark.asyncio
    async def test_list(self, fake_env):
        tool = build_manage_project_tool()
        env = _parse_envelope(await tool.func(action="list", search="星"))
        assert env["ok"] is True
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects")
        assert params == {"search": "星"}

    @pytest.mark.asyncio
    async def test_get(self, fake_env):
        tool = build_manage_project_tool()
        await tool.func(action="get", id="p1")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects/p1")

    @pytest.mark.asyncio
    async def test_update(self, fake_env):
        tool = build_manage_project_tool()
        await tool.func(action="update", id="p1", name="新名", target_words=80000)
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("PATCH", "/projects/p1")
        assert body["name"] == "新名" and body["target_words"] == 80000

    @pytest.mark.asyncio
    async def test_delete(self, fake_env):
        tool = build_manage_project_tool()
        await tool.func(action="delete", id="p1", force=True, permanent=True)
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("DELETE", "/projects/p1")
        assert params == {"permanent": True}

    @pytest.mark.asyncio
    async def test_restore(self, fake_env):
        tool = build_manage_project_tool()
        await tool.func(action="restore", id="p1")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects/p1/restore")


class TestManageChapter:
    """manage_chapter 端点映射（6 actions）。"""

    @pytest.mark.asyncio
    async def test_create(self, fake_env):
        tool = build_manage_chapter_tool()
        env = _parse_envelope(
            await tool.func(
                action="create", project_id="p1", title="第一章", volume_id="v1", content="正文"
            )
        )
        assert env["ok"] is True
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects/p1/chapters")
        assert body["title"] == "第一章" and body["volume_id"] == "v1"
        assert body["content"] == "正文"

    @pytest.mark.asyncio
    async def test_list(self, fake_env):
        tool = build_manage_chapter_tool()
        await tool.func(action="list", project_id="p1", volume_id="v1", status="draft")
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects/p1/chapters")
        assert params == {"volume_id": "v1", "status": "draft"}

    @pytest.mark.asyncio
    async def test_get(self, fake_env):
        tool = build_manage_chapter_tool()
        await tool.func(action="get", id="c1")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/chapters/c1")

    @pytest.mark.asyncio
    async def test_update(self, fake_env):
        tool = build_manage_chapter_tool()
        await tool.func(action="update", id="c1", title="改名", status="published")
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("PATCH", "/chapters/c1")
        assert body["title"] == "改名" and body["status"] == "published"

    @pytest.mark.asyncio
    async def test_delete(self, fake_env):
        tool = build_manage_chapter_tool()
        await tool.func(action="delete", id="c1")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("DELETE", "/chapters/c1")

    @pytest.mark.asyncio
    async def test_move(self, fake_env):
        tool = build_manage_chapter_tool()
        await tool.func(action="move", id="c1", to_volume="v2")
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/chapters/c1/move")
        assert body["to_volume"] == "v2"


class TestManageCharacter:
    """manage_character 端点映射（6 actions）。"""

    @pytest.mark.asyncio
    async def test_create(self, fake_env):
        tool = build_manage_character_tool()
        await tool.func(
            action="create",
            project_id="p1",
            name="林动",
            personality="坚韧",
            background="山村少年",
            goals="变强",
            group_id="g1",
        )
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects/p1/characters")
        assert body["name"] == "林动" and body["personality"] == "坚韧"
        assert body["background"] == "山村少年" and body["goals"] == "变强"
        assert body["group_id"] == "g1"

    @pytest.mark.asyncio
    async def test_list(self, fake_env):
        tool = build_manage_character_tool()
        await tool.func(action="list", project_id="p1", search="林", group_id="g1")
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects/p1/characters")
        assert params == {"search": "林", "group_id": "g1"}

    @pytest.mark.asyncio
    async def test_get_update_delete_restore(self, fake_env):
        tool = build_manage_character_tool()
        await tool.func(action="get", id="ch1")
        assert _last_call(fake_env.client)[:2] == ("GET", "/characters/ch1")
        await tool.func(action="update", id="ch1", name="改名")
        assert _last_call(fake_env.client)[:2] == ("PATCH", "/characters/ch1")
        await tool.func(action="delete", id="ch1", force=True)
        assert _last_call(fake_env.client)[:2] == ("DELETE", "/characters/ch1")
        await tool.func(action="restore", id="ch1")
        assert _last_call(fake_env.client)[:2] == ("POST", "/characters/ch1/restore")


class TestManageRelation:
    """manage_relation 端点映射（4 actions，F9 relations 三端点 + update）。"""

    @pytest.mark.asyncio
    async def test_create(self, fake_env):
        tool = build_manage_relation_tool()
        await tool.func(
            action="create",
            character_id="c1",
            source_id="c1",
            target_id="c2",
            relation_type="师徒",
            description="亦师亦友",
        )
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/characters/c1/relations")
        assert body["source_id"] == "c1" and body["target_id"] == "c2"
        assert body["relation_type"] == "师徒" and body["description"] == "亦师亦友"

    @pytest.mark.asyncio
    async def test_list(self, fake_env):
        tool = build_manage_relation_tool()
        await tool.func(action="list", character_id="c1")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/characters/c1/relations")

    @pytest.mark.asyncio
    async def test_update(self, fake_env):
        tool = build_manage_relation_tool()
        await tool.func(action="update", character_id="c1", id="r1", relation_type="恋人")
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("PATCH", "/characters/c1/relations/r1")
        assert body["relation_type"] == "恋人"

    @pytest.mark.asyncio
    async def test_delete(self, fake_env):
        tool = build_manage_relation_tool()
        await tool.func(action="delete", character_id="c1", id="r1")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("DELETE", "/characters/c1/relations/r1")


class TestManageTimeline:
    """manage_timeline 端点映射（6 actions）。"""

    @pytest.mark.asyncio
    async def test_create(self, fake_env):
        tool = build_manage_timeline_tool()
        await tool.func(
            action="create",
            project_id="p1",
            title="进城",
            description="主角初入帝都",
            time_value=3.0,
            time_unit="年",
        )
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects/p1/timeline/events")
        assert body["title"] == "进城" and body["time_value"] == 3.0

    @pytest.mark.asyncio
    async def test_list(self, fake_env):
        tool = build_manage_timeline_tool()
        await tool.func(action="list", project_id="p1", search="城")
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects/p1/timeline/events")
        assert params == {"search": "城"}

    @pytest.mark.asyncio
    async def test_get_update_delete(self, fake_env):
        tool = build_manage_timeline_tool()
        await tool.func(action="get", id="e1")
        assert _last_call(fake_env.client)[:2] == ("GET", "/timeline/events/e1")
        await tool.func(action="update", id="e1", title="改名")
        assert _last_call(fake_env.client)[:2] == ("PATCH", "/timeline/events/e1")
        await tool.func(action="delete", id="e1")
        assert _last_call(fake_env.client)[:2] == ("DELETE", "/timeline/events/e1")

    @pytest.mark.asyncio
    async def test_check(self, fake_env):
        tool = build_manage_timeline_tool()
        await tool.func(action="check", project_id="p1")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects/p1/timeline/check")


class TestManageWorld:
    """manage_world 端点映射（6 actions）。"""

    @pytest.mark.asyncio
    async def test_create(self, fake_env):
        tool = build_manage_world_tool()
        await tool.func(
            action="create",
            project_id="p1",
            name="大炎王朝",
            category="地理",
            content="东域第一王朝",
            parent="w0",
        )
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects/p1/world-settings")
        assert body["name"] == "大炎王朝" and body["category"] == "地理"
        assert body["content"] == "东域第一王朝" and body["parent"] == "w0"

    @pytest.mark.asyncio
    async def test_list(self, fake_env):
        tool = build_manage_world_tool()
        await tool.func(action="list", project_id="p1", search="王朝", category="地理")
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects/p1/world-settings")
        assert params == {"search": "王朝", "category": "地理"}

    @pytest.mark.asyncio
    async def test_get_update_delete_restore(self, fake_env):
        tool = build_manage_world_tool()
        await tool.func(action="get", id="w1")
        assert _last_call(fake_env.client)[:2] == ("GET", "/world-settings/w1")
        await tool.func(action="update", id="w1", name="改名")
        assert _last_call(fake_env.client)[:2] == ("PATCH", "/world-settings/w1")
        await tool.func(action="delete", id="w1", force=True)
        assert _last_call(fake_env.client)[:2] == ("DELETE", "/world-settings/w1")
        await tool.func(action="restore", id="w1")
        assert _last_call(fake_env.client)[:2] == ("POST", "/world-settings/w1/restore")


class TestManageOutline:
    """manage_outline 端点映射（6 actions）。"""

    @pytest.mark.asyncio
    async def test_create(self, fake_env):
        tool = build_manage_outline_tool()
        await tool.func(
            action="create", project_id="p1", name="第一卷", description="启程", sort_order=1
        )
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects/p1/outlines")
        assert body["name"] == "第一卷" and body["sort_order"] == 1

    @pytest.mark.asyncio
    async def test_list_get_update_delete(self, fake_env):
        tool = build_manage_outline_tool()
        await tool.func(action="list", project_id="p1", search="卷")
        assert _last_call(fake_env.client)[:2] == ("GET", "/projects/p1/outlines")
        await tool.func(action="get", id="o1")
        assert _last_call(fake_env.client)[:2] == ("GET", "/outlines/o1")
        await tool.func(action="update", id="o1", name="改名")
        assert _last_call(fake_env.client)[:2] == ("PATCH", "/outlines/o1")
        await tool.func(action="delete", id="o1", force=True)
        assert _last_call(fake_env.client)[:2] == ("DELETE", "/outlines/o1")

    @pytest.mark.asyncio
    async def test_generate(self, fake_env):
        tool = build_manage_outline_tool()
        await tool.func(
            action="generate",
            project_id="p1",
            name="新大纲",
            prompt="玄幻修炼体系",
            num_chapters=10,
        )
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/outlines/generate")
        assert body["project_id"] == "p1" and body["name"] == "新大纲"
        assert body["prompt"] == "玄幻修炼体系" and body["num_chapters"] == 10


class TestManageForeshadowing:
    """manage_foreshadowing 端点映射（7 actions）。"""

    @pytest.mark.asyncio
    async def test_create(self, fake_env):
        tool = build_manage_foreshadowing_tool()
        await tool.func(
            action="create",
            project_id="p1",
            title="玉佩",
            description="主角随身玉佩",
            priority=80,
            location="第一章",
            event_id="e1",
        )
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects/p1/foreshadowings")
        assert body["title"] == "玉佩" and body["priority"] == 80

    @pytest.mark.asyncio
    async def test_list(self, fake_env):
        tool = build_manage_foreshadowing_tool()
        await tool.func(action="list", project_id="p1", status="open", search="玉佩")
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects/p1/foreshadowings")
        assert params == {"status": "open", "search": "玉佩"}

    @pytest.mark.asyncio
    async def test_get_update_delete(self, fake_env):
        tool = build_manage_foreshadowing_tool()
        await tool.func(action="get", id="f1")
        assert _last_call(fake_env.client)[:2] == ("GET", "/foreshadowings/f1")
        await tool.func(action="update", id="f1", title="改名")
        assert _last_call(fake_env.client)[:2] == ("PATCH", "/foreshadowings/f1")
        await tool.func(action="delete", id="f1", force=True)
        assert _last_call(fake_env.client)[:2] == ("DELETE", "/foreshadowings/f1")

    @pytest.mark.asyncio
    async def test_resolve_reopen(self, fake_env):
        tool = build_manage_foreshadowing_tool()
        await tool.func(action="resolve", id="f1")
        assert _last_call(fake_env.client)[:2] == ("POST", "/foreshadowings/f1/resolve")
        await tool.func(action="reopen", id="f1")
        assert _last_call(fake_env.client)[:2] == ("POST", "/foreshadowings/f1/reopen")


class TestWrite:
    """write 端点映射（3 actions，Q3=A 同步非流式端点）。"""

    @pytest.mark.asyncio
    async def test_generate(self, fake_env):
        tool = build_write_tool()
        await tool.func(
            action="generate",
            project_id="p1",
            chapter_id="c1",
            outline="主角突破",
            context="前文",
            style_hint="爽文",
        )
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/writing/generate")
        assert body["project_id"] == "p1" and body["chapter_id"] == "c1"
        assert body["outline"] == "主角突破"

    @pytest.mark.asyncio
    async def test_continue(self, fake_env):
        tool = build_write_tool()
        await tool.func(
            action="continue",
            project_id="p1",
            chapter_id="c1",
            existing_content="前文内容",
            target_words=2000,
        )
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/writing/continue")
        assert body["existing_content"] == "前文内容"
        assert body["target_words"] == 2000

    @pytest.mark.asyncio
    async def test_revise(self, fake_env):
        tool = build_write_tool()
        await tool.func(
            action="revise",
            project_id="p1",
            chapter_id="c1",
            content="原文",
            feedback="太拖沓",
            instruction="精简",
        )
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/writing/revise")
        assert body["content"] == "原文" and body["feedback"] == "太拖沓"


class TestAudit:
    """audit 端点映射（2 actions）。"""

    @pytest.mark.asyncio
    async def test_project(self, fake_env):
        tool = build_audit_tool()
        await tool.func(action="project", project_id="p1")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/projects/p1/audit")

    @pytest.mark.asyncio
    async def test_chapter(self, fake_env):
        tool = build_audit_tool()
        await tool.func(action="chapter", project_id="p1", chapter_id="c1", include_static=True)
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects/p1/chapters/c1/audit")
        assert body["include_static"] is True


class TestExtract:
    """extract 端点映射（3 actions）。"""

    @pytest.mark.asyncio
    async def test_extract(self, fake_env):
        tool = build_extract_tool()
        await tool.func(action="extract", content="林动是山村少年")
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/extract")
        assert body["content"] == "林动是山村少年"

    @pytest.mark.asyncio
    async def test_reindex(self, fake_env):
        tool = build_extract_tool()
        await tool.func(action="reindex", project_id="p1")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects/p1/vector/reindex")

    @pytest.mark.asyncio
    async def test_retrieve(self, fake_env):
        tool = build_extract_tool()
        await tool.func(action="retrieve", project_id="p1", query="主角", top_k=5, min_score=0.3)
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/projects/p1/vector/retrieve")
        assert body["query"] == "主角" and body["top_k"] == 5


class TestExport:
    """export 端点映射（get_raw，F21 GET /projects/{pid}/export）。"""

    @pytest.mark.asyncio
    async def test_export(self, fake_env):
        tool = build_export_tool()
        fake_env.client.raw_response = "【书名】星辰变\n正文..."
        env = _parse_envelope(await tool.func(action="export", project_id="p1", format="txt"))
        assert env["ok"] is True
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET_RAW", "/projects/p1/export")
        assert params == {"format": "txt"}


class TestSearch:
    """search 端点映射（GET /search，F22 router prefix=/api/v1/search）。"""

    @pytest.mark.asyncio
    async def test_search(self, fake_env):
        tool = build_search_tool()
        await tool.func(
            action="search",
            project_id="p1",
            query="林动",
            content_type="character",
            limit=10,
            offset=0,
        )
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/search")
        assert params["q"] == "林动" and params["project_id"] == "p1"
        assert params["types"] == "character"


class TestManageSession:
    """manage_session 端点映射（7 actions + logs）。"""

    @pytest.mark.asyncio
    async def test_create(self, fake_env):
        tool = build_manage_session_tool()
        await tool.func(
            action="create",
            session_type="writing",
            project_id="p1",
            title="写作会话",
            description="d",
        )
        method, path, _, body = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/sessions")
        assert body["session_type"] == "writing" and body["project_id"] == "p1"

    @pytest.mark.asyncio
    async def test_list(self, fake_env):
        tool = build_manage_session_tool()
        await tool.func(
            action="list", session_type="writing", status="active", project_id="p1", search="写作"
        )
        method, path, params, _ = _last_call(fake_env.client)
        assert (method, path) == ("GET", "/sessions")
        assert params["session_type"] == "writing" and params["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_pause_resume(self, fake_env):
        tool = build_manage_session_tool()
        await tool.func(action="get", id="s1")
        assert _last_call(fake_env.client)[:2] == ("GET", "/sessions/s1")
        await tool.func(action="pause", id="s1")
        assert _last_call(fake_env.client)[:2] == ("POST", "/sessions/s1/pause")
        await tool.func(action="resume", id="s1")
        assert _last_call(fake_env.client)[:2] == ("POST", "/sessions/s1/resume")

    @pytest.mark.asyncio
    async def test_complete_fail(self, fake_env):
        tool = build_manage_session_tool()
        await tool.func(action="complete", id="s1", result_json='{"ok": true}')
        assert _last_call(fake_env.client)[:2] == ("POST", "/sessions/s1/complete")
        await tool.func(action="fail", id="s1")
        assert _last_call(fake_env.client)[:2] == ("POST", "/sessions/s1/fail")

    @pytest.mark.asyncio
    async def test_add_log(self, fake_env):
        tool = build_manage_session_tool()
        await tool.func(action="add_log", id="s1", logs="step1 done")
        method, path, _, _ = _last_call(fake_env.client)
        assert (method, path) == ("POST", "/sessions/s1/logs")
