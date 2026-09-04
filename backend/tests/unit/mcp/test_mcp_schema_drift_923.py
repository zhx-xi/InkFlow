"""MCP 工具面 schema drift 契约（#923，RED 阶段测试契约文件 §4，含并入 #925 export desc 收窄）。

契约依据：`backend/src/inkflow/mcp/tools/` 的 `schemas.py`（Pydantic Params 模型 →
inputSchema）与各 `build_*_tool()` 工厂返回的 MCPTool（spec + func）。func 内部 lazy
import `inkflow.infrastructure.http` / `inkflow.infrastructure.kernel`，经
`ensure_kernel()` + `InkFlowHTTPClient` 透传 HTTP。缺陷如下（拍板方向 C，修复后应变为
的行为 = 本文件契约）：

1. `ManageCharacterParams` 缺 `extra`（domain `CharacterCreate.extra` 必填
   `extra.role_rank`，#833）与 `brief`（F6 一句话简介）→ MCP 传不进去，角色创建在 MCP
   面永远 422「角色等级必填」。修复后：参数模型有 extra/brief，create/update 路由把
   非 None 的 extra/brief 透传进 POST/PATCH body（现有 `_compact` 语义：None 键剔除）。
2. `ManageOutlineParams` 缺 `level/parent_id/volume_id/chapter_id`（F43 三级大纲链
   overall→volume→chapter；domain `OutlineCreate/OutlineUpdate` 全有）→ MCP 无法建层级。
   修复后：四个字段可传，create/update body 透传（`_compact`：None 剔除；`""` 是
   OutlineUpdate 的「清除」哨兵，必须原样透传不剔除）。
3. export 工具 description 宣称「EPUB/Markdown/TXT/DOCX」但 HTTP 端点
   `Literal["txt"]`（F21 D9 拍板 TXT-only）→ 误导 agent。修复后：
   `build_export_tool().spec.description` 不再出现 EPUB/DOCX/Markdown 字样且含 TXT；
   `func(action="export", format!="txt")` 在**本地前置友好报错**（不调 ensure_kernel、
   不发 HTTP），信封 ok=False、code="INVALID_ARGS"、message/hint 含「txt」（大小写不敏感）；
   format="txt" 正常 GET_RAW 透传。

RED 形态说明：本文件为**非收集错误**的纯断言失败（AssertionError）。字段缺失 → Pydantic
`extra=ignore`（默认）静默丢弃未知 kwarg（extra/brief/level/parent_id/...）→ `_compact`
body 无这些键 → `.get(...)` 断言失败；export description / 非 txt 前置拦截当前 FAIL。
用例 11 为 GREEN-now 守护（当前即 PASS，修复后仍须 PASS）。

纪律：只经公开 `tool.func(**kwargs)` 触发（禁直调私有 `_route_*`）；fake client 必须为
记录型且**必须实现 `get_raw`**（#926 镜像未含，本文件补上）；断言 message/hint 只用
子串语义，不锁全句；body 断言一律走 `.get(...)`（缺键返回 None → AssertionError，而非
KeyError）。装配缝镜像 `tests/unit/mcp/test_mcp_tools.py`：MCP 工具在函数体内 lazy import
源头模块，故 patch 命名空间 `http_mod` 的属性 `InkFlowHTTPClient`（恒返回同一记录 client）。
"""
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.mcp.tools.manage_tools import (
    build_manage_character_tool,
    build_manage_outline_tool,
)
from inkflow.mcp.tools.operation_tools import build_export_tool
from inkflow.mcp.tools.schemas import ManageCharacterParams, ManageOutlineParams

kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
http_mod = importlib.import_module("inkflow.infrastructure.http")


class FakeClient:
    """有状态记录型 fake：每次 HTTP 调用记录 method/path/params/json/timeout 为 dict。

    🔴 与 #926 镜像不同的是每个调用落成 dict（含 `timeout`），且**额外实现
    `get_raw`**——export 工具经 `_route_export` 调 `client.get_raw(...)` 返回原始文本
    （镜像 #926 未用 export，故无 get_raw；本文件必须补上，参考 `test_mcp_tools.py` 的
    get_raw：#923 契约的 export 用例依赖它）。
    """

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
        return self.response  # type: ignore[return-value]  # 测试 fake：用例均预置 dict 响应

    async def post(self, path, *, params=None, json=None, timeout=None) -> dict:
        self._record("POST", path, params, json, timeout)
        return self.response  # type: ignore[return-value]  # 测试 fake：用例均预置 dict 响应

    async def patch(self, path, *, params=None, json=None) -> dict:
        self._record("PATCH", path, params, json)
        return self.response  # type: ignore[return-value]  # 测试 fake：用例均预置 dict 响应

    async def delete(self, path, *, params=None, json=None) -> dict:
        self._record("DELETE", path, params, json)
        return self.response  # type: ignore[return-value]  # 测试 fake：用例均预置 dict 响应

    async def get_raw(self, path, *, params=None) -> str:
        self._record("GET_RAW", path, params, None)
        return self.raw_response


@pytest.fixture
def fake_env(monkeypatch):
    """装配缝：ensure_kernel → 鸭子 handle；InkFlowHTTPClient → 恒返回同一 client 实例。

    🔴 func 内部 `async with InkFlowHTTPClient(handle)` 每次构造新实例——patch 必须
    返回**同一个**预建实例（lambda 闭包），断言 `fake_env.client.calls` 才能命中。
    """
    client = FakeClient(SimpleNamespace(port=1, token="t"))
    fake_ensure = AsyncMock(return_value=SimpleNamespace(port=1, token="t", pid=2, version="0.1.0"))
    monkeypatch.setattr(kernel_mod, "ensure_kernel", fake_ensure)
    monkeypatch.setattr(http_mod, "InkFlowHTTPClient", lambda handle: client)
    return SimpleNamespace(client=client, fake_ensure=fake_ensure)


def _parse_envelope(text: str) -> dict:
    """解析工具 func 返回的信封 JSON 字符串。"""
    return json.loads(text)


def _last_call(client: FakeClient) -> dict:
    """最近一次 HTTP 调用记录（dict：method/path/params/json/timeout）。"""
    assert client.calls, "未发生 HTTP 调用"
    return client.calls[-1]


class TestCharacterSchemaDrift923:
    """#923 方向 1：ManageCharacterParams 缺 extra/brief → MCP 面角色创建永远 422。"""

    def test_params_has_extra_and_brief(self):
        """【R】ManageCharacterParams.model_fields 含 extra 与 brief；JSON Schema 亦含。

        RED 现状：两字段均不存在（extra/brief 被 Pydantic 默认 extra=ignore 丢弃）。
        """
        fields = ManageCharacterParams.model_fields
        assert "extra" in fields
        assert "brief" in fields
        props = ManageCharacterParams.model_json_schema()["properties"]
        assert "extra" in props
        assert "brief" in props

    @pytest.mark.asyncio
    async def test_create_passes_extra_and_brief(self, fake_env):
        """【R】character action=create 透传 extra/brief → POST body 含二者。

        RED 现状：extra/brief 被 Pydantic 丢弃 → body 无键 → `.get(...)` 断言失败。
        """
        tool = build_manage_character_tool()
        env = _parse_envelope(
            await tool.func(
                action="create",
                project_id="p1",
                name="玄明",
                personality="沉稳",
                extra={"role_rank": "protagonist"},
                brief="前世程序员",
            )
        )
        assert env["ok"] is True
        last = _last_call(fake_env.client)
        assert last["method"] == "POST"
        assert last["path"] == "/projects/p1/characters"
        body = last["json"] or {}
        assert body.get("extra") == {"role_rank": "protagonist"}
        assert body.get("brief") == "前世程序员"

    @pytest.mark.asyncio
    async def test_update_passes_extra(self, fake_env):
        """【R】character action=update 透传 extra → PATCH body 含 extra。

        RED 现状：extra 被丢弃 → body 无键 → `.get(...)` 断言失败。
        """
        tool = build_manage_character_tool()
        env = _parse_envelope(
            await tool.func(action="update", id="ch1", extra={"role_rank": "major"})
        )
        assert env["ok"] is True
        last = _last_call(fake_env.client)
        assert last["method"] == "PATCH"
        assert last["path"] == "/characters/ch1"
        body = last["json"] or {}
        assert body.get("extra") == {"role_rank": "major"}


class TestOutlineSchemaDrift923:
    """#923 方向 2：ManageOutlineParams 缺 level/parent_id/volume_id/chapter_id。"""

    def test_params_has_hierarchy_fields(self):
        """【R】ManageOutlineParams.model_fields 含 level/parent_id/volume_id/chapter_id。

        RED 现状：四字段均不存在。
        """
        fields = ManageOutlineParams.model_fields
        for name in ("level", "parent_id", "volume_id", "chapter_id"):
            assert name in fields

    @pytest.mark.asyncio
    async def test_create_overall_level(self, fake_env):
        """【R】outline action=create level=overall → POST body level；parent_id=None 剔除。

        RED 现状：level 被丢弃 → body 无键 → `.get(...)` 断言失败。
        """
        tool = build_manage_outline_tool()
        env = _parse_envelope(
            await tool.func(action="create", project_id="p1", name="全书总纲", level="overall")
        )
        assert env["ok"] is True
        last = _last_call(fake_env.client)
        assert last["method"] == "POST"
        assert last["path"] == "/projects/p1/outlines"
        body = last["json"] or {}
        assert body.get("level") == "overall"
        assert "parent_id" not in body

    @pytest.mark.asyncio
    async def test_create_volume_under_overall(self, fake_env):
        """【R】outline action=create level=volume + parent_id → body 原样透传字符串。

        RED 现状：level/parent_id 均被丢弃 → `.get(...)` 断言失败。
        """
        tool = build_manage_outline_tool()
        parent = "2b3c4d5e-6f70-4181-9293-a4b5c6d7e8f9"
        env = _parse_envelope(
            await tool.func(
                action="create", project_id="p1", name="第一卷", level="volume", parent_id=parent
            )
        )
        assert env["ok"] is True
        last = _last_call(fake_env.client)
        assert last["method"] == "POST"
        body = last["json"] or {}
        assert body.get("level") == "volume"
        assert body.get("parent_id") == parent

    @pytest.mark.asyncio
    async def test_create_chapter_with_volume_and_chapter(self, fake_env):
        """【R】outline action=create level=chapter + volume_id + chapter_id → body 含二者。

        RED 现状：volume_id/chapter_id 被丢弃 → `.get(...)` 断言失败。
        """
        tool = build_manage_outline_tool()
        volume_id = "3c4d5e6f-7081-4293-a4b5-c6d7e8f9a0b1"
        chapter_id = "4d5e6f70-8191-4293-9495-a6b7c8d9e0f1"
        env = _parse_envelope(
            await tool.func(
                action="create",
                project_id="p1",
                name="第一章",
                level="chapter",
                volume_id=volume_id,
                chapter_id=chapter_id,
            )
        )
        assert env["ok"] is True
        last = _last_call(fake_env.client)
        assert last["method"] == "POST"
        body = last["json"] or {}
        assert body.get("volume_id") == volume_id
        assert body.get("chapter_id") == chapter_id

    @pytest.mark.asyncio
    async def test_update_hierarchy_and_empty_sentinel(self, fake_env):
        """【R】outline action=update level=volume + parent_id="" → body 透传清除哨兵。

        RED 现状：level/parent_id 被丢弃，parent_id 的 "" 也未透传（当前根本无该键）。
        """
        tool = build_manage_outline_tool()
        env = _parse_envelope(
            await tool.func(action="update", id="o1", level="volume", parent_id="")
        )
        assert env["ok"] is True
        last = _last_call(fake_env.client)
        assert last["method"] == "PATCH"
        assert last["path"] == "/outlines/o1"
        body = last["json"] or {}
        assert body.get("level") == "volume"
        assert body.get("parent_id") == ""
        assert "chapter_id" not in body


class TestExportContract923:
    """#923 方向 3（并入 #925）：export desc 收窄 + 非 txt 前置友好报错。"""

    def test_description_txt_only(self):
        """【R】export spec.description 不含 EPUB/DOCX/Markdown 且含 TXT。

        RED 现状：desc 为「导出：项目导出为 EPUB/Markdown/TXT/DOCX」→ EPUB 断言失败。
        """
        desc = build_export_tool().spec.description
        assert "EPUB" not in desc
        assert "DOCX" not in desc
        assert "Markdown" not in desc
        assert "TXT" in desc

    @pytest.mark.asyncio
    async def test_non_txt_friendly_error_without_http(self, fake_env):
        """【R】export format!=txt → 本地前置友好报错，零 HTTP 往返。

        RED 现状：当前直接透传 get_raw 且 ok=True → 首条断言失败；calls 也非空。
        """
        tool = build_export_tool()
        env = _parse_envelope(await tool.func(action="export", project_id="p1", format="markdown"))
        assert env.get("ok") is False
        err = env.get("error") or {}
        assert err.get("code") == "INVALID_ARGS"
        combined = (str(err.get("message", "")) + str(err.get("hint", ""))).lower()
        assert "txt" in combined
        assert fake_env.client.calls == []

    @pytest.mark.asyncio
    async def test_txt_success_and_default_passthrough(self, fake_env):
        """【G】export format=txt → GET_RAW 透传（当前即 PASS，修复后仍须 PASS）。

        GREEN-now 守护。
        """
        tool = build_export_tool()
        env = _parse_envelope(await tool.func(action="export", project_id="p1", format="txt"))
        assert env["ok"] is True
        last = _last_call(fake_env.client)
        assert last["method"] == "GET_RAW"
        assert last["path"] == "/projects/p1/export"
        assert last["params"] == {"format": "txt"}


class TestSchemaDriftGuard923:
    """#923 防再漂移护栏（CI 拦截）：MCP Params 字段面 ⊇ 对应领域 DTO 字段面。"""

    def test_character_params_superset_of_dto(self):
        """【R】ManageCharacterParams ⊇ CharacterCreate/Update（剔除 group_ids/project_id）。

        RED 现状：缺 extra/brief → 差集非空。
        """
        from inkflow.domain.models.character import CharacterCreate, CharacterUpdate

        mcp_fields = set(ManageCharacterParams.model_fields)
        for dto in (CharacterCreate, CharacterUpdate):
            missing = set(dto.model_fields) - mcp_fields - {"group_ids", "project_id"}
            assert missing == set()

    def test_outline_params_superset_of_dto(self):
        """【R】ManageOutlineParams ⊇ OutlineCreate/Update（剔除 project_id）。

        RED 现状：缺 level/parent_id/chapter_id/volume_id → 差集非空。
        """
        from inkflow.domain.models.outline import OutlineCreate, OutlineUpdate

        for dto in (OutlineCreate, OutlineUpdate):
            missing = set(dto.model_fields) - set(ManageOutlineParams.model_fields) - {"project_id"}
            assert missing == set()
