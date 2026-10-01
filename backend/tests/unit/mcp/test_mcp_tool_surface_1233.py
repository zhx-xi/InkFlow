"""#1233 MCP 工具面补齐契约（RED，spec f20 §2.2/§4.1/§7/§13）。

Issue #1233 拍板 **方案 B（最小止血）** + **通用要求**：

1. **未知字段禁止静默丢弃**（通用要求，无论方案必做）：所有 MCP 参数模型拒绝
   未声明字段 → `INVALID_ARGS` 信封 + **零 HTTP 往返**。现行行为是 pydantic 默认
   `extra="ignore"` 静默丢弃 → `ok=True` 无变更（违反「显式失败优于静默错误」）。
2. **`write` 补 `mode` + `show_context`**（0.15.0 写作链修复在 MCP 面缺失）：
   - `mode="agentic"` → `POST /writing/agentic/generate`（CLI `write next --mode agentic`
     同端点同语义；`target_words` → `AgenticWriteRequest.min_words`）；
   - `show_context=True` → 先取章级要求（`GET /chapters/{id}`，镜像 CLI
     `_fetch_chapter_requirements`，失败/为空 → 语义中性占位）→
     `POST /context/assemble`（`model=""`，服务端按兜底窗口计预算）→
     组装结果挂到信封 `data["context"]`（镜像 CLI `--show-context` 的
     `{**data, "context": assembly}`）。
   - `mode="agentic"` / `show_context=True` **仅对 `action="generate"` 有效**；
     用于其它 action → `INVALID_ARGS`（把「静默不生效」升级为显式失败）。
3. **`manage_project` 补 `config` 透传**（消静默失败）：`create` / `update` 两条写
   路径带 `config`（镜像 API `ProjectCreate.config` / `ProjectUpdate.config` 与
   CLI `project update --config`）。

── 落点与端点（源码实证，父侧亲读）────────────────────────────────
- CLI：`cli/commands/write.py::next`（--mode / --show-context / --min-words）、
  `cli/commands/project.py::update`（--config）
- API：`api/routers/writing.py`（/writing/generate、/writing/agentic/generate）、
  `api/routers/context.py`（/context/assemble）、`api/routers/project.py`（PATCH /projects/{id}）
- DTO：`domain/models/agent_run.py::AgenticWriteRequest`、
  `domain/models/context.py::ContextRequest`（`writing_requirements` min_length=1）
- config 部分合并语义：`domain/services/project_service.py::update` →
  `existing.config.model_copy(update=config_updates)`（既有单测
  `test_project_service.py::test_update_merges_config_subobject_fields` 锁定）

── 装配缝（镜像 test_mcp_tools.py）───────────────────────────────
func 内 lazy import 源头模块 → patch `http_mod.InkFlowHTTPClient` 恒返回同一记录型
FakeClient。本文件 FakeClient 额外支持 `responses` 队列（show_context 多连调用需逐次
不同响应）。

── RED 形态 ────────────────────────────────────────────────────
schemas 现无 `mode` / `show_context` / `config` 字段且 `extra` 默认 ignore →
本文件 schema 与路由用例 FAIL（AssertionError / 缺键）、未知字段用例 FAIL
（现行 `ok=True`）。GREEN 落地后整文件转绿。

── 测试约定 ────────────────────────────────────────────────────
- 只经公开面触发：`MCP_TOOL_REGISTRY` 取工具 → `func(**kwargs)`；禁直调私有 `_route_*`。
- body/params 断言一律 `.get(...)`（缺键 → None → AssertionError，而非 KeyError）。
- async 用例显式 `@pytest.mark.asyncio`（pytest-asyncio STRICT）。
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from inkflow.mcp.tools import MCP_TOOL_REGISTRY
from inkflow.mcp.tools.schemas import ALL_SCHEMAS, ManageProjectParams, WriteParams

kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
http_mod = importlib.import_module("inkflow.infrastructure.http")

#: 19 工具 × 各自一组**合法**最小参数（未知字段用例先以此证明「无污染」，再注入未知字段）
_VALID_ARGS: dict[str, dict[str, object]] = {
    "manage_project": {"action": "list"},
    "manage_chapter": {"action": "list"},
    "manage_character": {"action": "list"},
    "manage_relation": {"action": "list"},
    "manage_timeline": {"action": "list"},
    "manage_world": {"action": "list"},
    "manage_outline": {"action": "list"},
    "manage_foreshadowing": {"action": "list"},
    # draft_list 的本地必填守卫需 project_id（否则未知字段用例会被守卫抢先拒绝 → 假绿）
    "write": {"action": "draft_list", "project_id": "p1"},
    "audit": {"action": "project"},
    "extract": {"action": "extract"},
    "export": {"action": "export"},
    "search": {"action": "search"},
    "manage_session": {"action": "list"},
    "tool_search": {"action": "list"},
    # status 的本地必填守卫需 run_id（同上，防假绿）
    "manage_book": {"action": "status", "run_id": "r1"},
    "manage_config": {"action": "provider_list"},
    "manage_log": {"action": "query"},
    "manage_knowledge_relation": {"action": "list"},
}

#: 未声明字段名（断言出现在错误消息里，调用方可自愈）
_BOGUS_FIELD = "not_a_declared_field"

#: 章级要求占位（逐字镜像 CLI `write next` 的语义中性占位，不冒充章级要求）
_PLACEHOLDER = "（未配置章级写作要求）"


class FakeClient:
    """记录型 fake：`responses` 队列逐次出栈，耗尽后回退 `default`。"""

    def __init__(self, handle: object) -> None:
        self.handle = handle
        self.calls: list[dict] = []
        self.responses: list[object] = []
        self.default: object = {"id": "x", "name": "resp"}

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def _next(self) -> object:
        if self.responses:
            return self.responses.pop(0)
        return self.default

    def _record(
        self, method: str, path: str, params: object, json_body: object, timeout: object = None
    ) -> None:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json": json_body,
                "timeout": timeout,
            }
        )

    async def get(self, path: str, *, params: object = None, json: object = None) -> dict:
        self._record("GET", path, params, json)
        return self._next()  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def post(
        self, path: str, *, params: object = None, json: object = None, timeout: object = None
    ) -> dict:
        self._record("POST", path, params, json, timeout)
        return self._next()  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def patch(self, path: str, *, params: object = None, json: object = None) -> dict:
        self._record("PATCH", path, params, json)
        return self._next()  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def delete(self, path: str, *, params: object = None, json: object = None) -> dict:
        self._record("DELETE", path, params, json)
        return self._next()  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def get_raw(self, path: str, *, params: object = None) -> str:
        self._record("GET_RAW", path, params, None)
        value = self._next()
        return value if isinstance(value, str) else "raw-text"


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """装配缝：ensure_kernel → 鸭子 handle；InkFlowHTTPClient 恒同一记录型实例。"""
    client = FakeClient(SimpleNamespace(port=1, token="t"))
    fake_ensure = AsyncMock(return_value=SimpleNamespace(port=1, token="t", pid=2, version="0.1.0"))
    monkeypatch.setattr(kernel_mod, "ensure_kernel", fake_ensure)
    monkeypatch.setattr(http_mod, "InkFlowHTTPClient", lambda handle: client)
    return SimpleNamespace(client=client, fake_ensure=fake_ensure)


def _envelope(text: str) -> dict:
    return json.loads(text)


def _tool(name: str):
    """按名取已装配工具（tools/list 同源）。"""
    return next(tool for tool in MCP_TOOL_REGISTRY if tool.spec.name == name)


def _calls(client: FakeClient) -> list[tuple[str, str]]:
    return [(call["method"], call["path"]) for call in client.calls]


class TestUnknownFieldForbidden1233:
    """通用要求：未声明字段 → INVALID_ARGS + 零 HTTP（禁静默丢弃）。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", sorted(_VALID_ARGS))
    async def test_unknown_field_rejected_for_every_tool(self, fake_env, tool_name):
        """两段式：合法参数先证「无污染」（ok=True），再注入未知字段 → 必拒。"""
        valid = _envelope(await _tool(tool_name).func(**_VALID_ARGS[tool_name]))
        assert valid["ok"] is True, f"{tool_name} 合法参数未通过（用例前提失效，需修契约）"
        fake_env.client.calls.clear()

        env = _envelope(
            await _tool(tool_name).func(**{**_VALID_ARGS[tool_name], _BOGUS_FIELD: "x"})
        )
        assert env["ok"] is False, f"{tool_name} 未拒绝未知字段（静默丢弃 → ok=True）"
        assert env["error"]["code"] == "INVALID_ARGS"
        assert fake_env.client.calls == [], f"{tool_name} 在拒绝前发生了 HTTP 往返"

    @pytest.mark.asyncio
    async def test_error_message_names_offending_field(self, fake_env):
        env = _envelope(await _tool("manage_project").func(action="list", **{_BOGUS_FIELD: "x"}))
        assert env["error"]["code"] == "INVALID_ARGS"
        assert _BOGUS_FIELD in env["error"]["message"], "错误消息须点名未声明字段（自愈前提）"

    @pytest.mark.asyncio
    async def test_declared_fields_still_pass(self, fake_env):
        """反例守护：合法字段仍正常透传（不得因加固而误杀）。"""
        env = _envelope(
            await _tool("manage_project").func(action="create", name="通用书名", tags=["通用标签"])
        )
        assert env["ok"] is True
        body = fake_env.client.calls[-1]["json"] or {}
        assert body.get("name") == "通用书名"
        assert body.get("tags") == ["通用标签"]


class TestSchemaUnknownFieldGuard1233:
    """模型级契约：19 个参数模型全部禁止未声明字段（extra=forbid）。"""

    @pytest.mark.parametrize("model_name", sorted(ALL_SCHEMAS))
    def test_all_models_forbid_extra_fields(self, model_name):
        schema = ALL_SCHEMAS[model_name].model_json_schema()
        assert schema.get("additionalProperties") is False, f"{model_name} 未禁止未声明字段"

    def test_write_params_declares_mode(self):
        props = WriteParams.model_json_schema()["properties"]
        assert "mode" in props, "WriteParams 缺 mode 字段"
        dumped = json.dumps(props["mode"])
        assert '"deterministic"' in dumped and '"agentic"' in dumped, "inputSchema 未暴露 mode 枚举"
        assert "mode" not in set(WriteParams.model_json_schema().get("required", []))

    def test_write_params_declares_show_context(self):
        props = WriteParams.model_json_schema()["properties"]
        assert "show_context" in props, "WriteParams 缺 show_context 字段"
        assert "boolean" in json.dumps(props["show_context"])
        assert "show_context" not in set(WriteParams.model_json_schema().get("required", []))

    def test_write_mode_literal_validation(self):
        assert WriteParams(action="generate", mode="agentic").mode == "agentic"
        assert WriteParams(action="generate", mode="deterministic").mode == "deterministic"
        assert WriteParams(action="generate").mode is None
        with pytest.raises(ValidationError):
            WriteParams(action="generate", mode="yolo")

    def test_manage_project_declares_config(self):
        props = ManageProjectParams.model_json_schema()["properties"]
        assert "config" in props, "ManageProjectParams 缺 config 字段"
        assert "config" not in set(ManageProjectParams.model_json_schema().get("required", []))
        parsed = ManageProjectParams(action="update", id="p1", config={"writing_style": "克制"})
        assert parsed.config == {"writing_style": "克制"}

    def test_write_description_mentions_agentic(self):
        """工具自描述须让 LLM 知道 agentic 模式可用（工具选择依据）。"""
        assert "agentic" in _tool("write").spec.description.lower()


class TestManageProjectConfig1233:
    """`manage_project` config 透传（create / update 写路径，消静默失败）。"""

    @pytest.mark.asyncio
    async def test_update_transmits_config(self, fake_env):
        env = _envelope(
            await _tool("manage_project").func(
                action="update", id="p1", config={"writing_style": "克制"}
            )
        )
        assert env["ok"] is True
        call = fake_env.client.calls[-1]
        assert (call["method"], call["path"]) == ("PATCH", "/projects/p1")
        assert (call["json"] or {}).get("config") == {"writing_style": "克制"}

    @pytest.mark.asyncio
    async def test_update_without_config_omits_key(self, fake_env):
        env = _envelope(
            await _tool("manage_project").func(action="update", id="p1", name="通用新名")
        )
        assert env["ok"] is True
        body = fake_env.client.calls[-1]["json"] or {}
        assert body.get("name") == "通用新名"
        assert "config" not in body, "未传 config 时不得凭默认值覆盖既有配置"

    @pytest.mark.asyncio
    async def test_create_transmits_config(self, fake_env):
        env = _envelope(
            await _tool("manage_project").func(
                action="create", name="通用书名", config={"writing_style": "简洁"}
            )
        )
        assert env["ok"] is True
        call = fake_env.client.calls[-1]
        assert (call["method"], call["path"]) == ("POST", "/projects")
        assert (call["json"] or {}).get("config") == {"writing_style": "简洁"}


class TestWriteMode1233:
    """`write` mode：agentic 走 F27 非流式端点（CLI `write next --mode agentic` 镜像）。"""

    @pytest.mark.asyncio
    async def test_agentic_routes_to_agentic_endpoint(self, fake_env):
        env = _envelope(
            await _tool("write").func(
                action="generate",
                project_id="p1",
                chapter_id="c1",
                outline="主角突破",
                mode="agentic",
            )
        )
        assert env["ok"] is True
        call = fake_env.client.calls[-1]
        assert (call["method"], call["path"]) == ("POST", "/writing/agentic/generate")
        body = call["json"] or {}
        assert body.get("project_id") == "p1"
        assert body.get("chapter_id") == "c1"
        assert body.get("outline") == "主角突破"

    @pytest.mark.asyncio
    async def test_agentic_maps_target_words_to_min_words(self, fake_env):
        await _tool("write").func(
            action="generate",
            project_id="p1",
            chapter_id="c1",
            outline="o",
            mode="agentic",
            target_words=3000,
        )
        body = fake_env.client.calls[-1]["json"] or {}
        assert body.get("min_words") == 3000
        assert "target_words" not in body, "agentic 端点 DTO 无 target_words 字段，勿透传"

    @pytest.mark.asyncio
    async def test_agentic_forwards_context_and_style(self, fake_env):
        await _tool("write").func(
            action="generate",
            project_id="p1",
            chapter_id="c1",
            outline="o",
            context="前文摘要",
            style_hint="冷静克制",
            mode="agentic",
        )
        body = fake_env.client.calls[-1]["json"] or {}
        assert body.get("context") == "前文摘要"
        assert body.get("style_hint") == "冷静克制"

    @pytest.mark.asyncio
    async def test_default_mode_stays_deterministic(self, fake_env):
        await _tool("write").func(action="generate", project_id="p1", chapter_id="c1", outline="o")
        assert _calls(fake_env.client) == [("POST", "/writing/generate")]

    @pytest.mark.asyncio
    async def test_explicit_deterministic_stays_deterministic(self, fake_env):
        await _tool("write").func(
            action="generate",
            project_id="p1",
            chapter_id="c1",
            outline="o",
            mode="deterministic",
        )
        assert _calls(fake_env.client) == [("POST", "/writing/generate")]

    @pytest.mark.asyncio
    async def test_agentic_with_non_generate_action_rejected(self, fake_env):
        env = _envelope(
            await _tool("write").func(
                action="revise",
                project_id="p1",
                chapter_id="c1",
                content="待修订内容占位",
                feedback="改得更紧凑",
                mode="agentic",
            )
        )
        assert env["ok"] is False
        assert env["error"]["code"] == "INVALID_ARGS"
        assert fake_env.client.calls == []


class TestWriteShowContext1233:
    """`write` show_context：镜像 CLI `write next --show-context`（#1186/#1232 语义）。"""

    @pytest.mark.asyncio
    async def test_show_context_assembles_then_attaches(self, fake_env):
        assembly = {
            "model": "m",
            "total_tokens": 12,
            "budget_tokens": 100,
            "blocks": [],
            "dropped": [],
        }
        fake_env.client.responses = [
            {"writing_requirements": " 本章要写雪景 "},
            assembly,
            {"content": "正文", "word_count": 2},
        ]
        env = _envelope(
            await _tool("write").func(
                action="generate",
                project_id="p1",
                chapter_id="c1",
                outline="o",
                show_context=True,
            )
        )
        assert env["ok"] is True
        assert env["data"].get("context") == assembly
        assert env["data"].get("content") == "正文"
        assert _calls(fake_env.client) == [
            ("GET", "/chapters/c1"),
            ("POST", "/context/assemble"),
            ("POST", "/writing/generate"),
        ]
        body = fake_env.client.calls[1]["json"] or {}
        assert body.get("project_id") == "p1"
        assert body.get("chapter_id") == "c1"
        assert body.get("model") == ""
        assert body.get("writing_requirements") == "本章要写雪景"

    @pytest.mark.asyncio
    async def test_show_context_uses_placeholder_when_chapter_has_none(self, fake_env):
        fake_env.client.responses = [{}, {"model": "m"}, {"content": "正文"}]
        envelope = _envelope(
            await _tool("write").func(
                action="generate",
                project_id="p1",
                chapter_id="c1",
                outline="o",
                show_context=True,
            )
        )
        assert envelope["ok"] is True
        body = fake_env.client.calls[1]["json"] or {}
        assert body.get("writing_requirements") == _PLACEHOLDER

    @pytest.mark.asyncio
    async def test_show_context_absent_makes_single_call(self, fake_env):
        """未开 show_context → 不取章级要求、不调 assemble（零额外往返）。"""
        await _tool("write").func(action="generate", project_id="p1", chapter_id="c1", outline="o")
        assert _calls(fake_env.client) == [("POST", "/writing/generate")]

    @pytest.mark.asyncio
    async def test_show_context_combined_with_agentic(self, fake_env):
        fake_env.client.responses = [
            {"writing_requirements": "本章要写雪景"},
            {"model": "m", "blocks": []},
            {"draft_id": "d1", "status": "completed"},
        ]
        env = _envelope(
            await _tool("write").func(
                action="generate",
                project_id="p1",
                chapter_id="c1",
                outline="o",
                mode="agentic",
                show_context=True,
            )
        )
        assert env["ok"] is True
        assert env["data"].get("context") == {"model": "m", "blocks": []}
        assert env["data"].get("draft_id") == "d1"
        assert _calls(fake_env.client) == [
            ("GET", "/chapters/c1"),
            ("POST", "/context/assemble"),
            ("POST", "/writing/agentic/generate"),
        ]

    @pytest.mark.asyncio
    async def test_show_context_with_non_generate_action_rejected(self, fake_env):
        env = _envelope(
            await _tool("write").func(
                action="continue",
                project_id="p1",
                chapter_id="c1",
                existing_content="已有正文占位" * 10,
                show_context=True,
            )
        )
        assert env["ok"] is False
        assert env["error"]["code"] == "INVALID_ARGS"
        assert fake_env.client.calls == []
