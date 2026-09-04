"""MCP 工具层 LLM 长任务 per-request timeout 契约（#926，RED 阶段测试契约 §4 文件 C）。

契约依据：`backend/src/inkflow/mcp/` 同族面清单（§0 MCP 表）——7 处 `client.post(...)`
长任务调用当前不带 `timeout`（全局仅 30s 默认），LLM 生成 1-10 分钟 → httpx
`ReadTimeout` 假失败。此处逐处经**公开 `tool.func(**kwargs)`** 触发并断言 fake client
记录的 `timeout == 300.0`。

§4-C 全量用例（本文件独占）：
- C-R1..R7【R】七处调用点（operation_tools 6 处 + manage_tools outline generate 1 处，
  §0 MCP 表共 7 行）逐个断言 `post` 调用 `kwargs.get("timeout") == 300.0`——现在无
  timeout → None != 300.0，必 FAIL。
- C-R9【R】超时信封语义：`HttpApiError(0, …超时文案…, "TIMEOUT")` → outline 工具信封
  `error.code == "TIMEOUT"` + `hint` 含「list/get」。现在 `map_http_error` 无 TIMEOUT
  分支 → INTERNAL_ERROR，必 FAIL。
- C-R10【R】`_hint_for("TIMEOUT")` 含「查询结果」（operation/manage 两模块各测）——现在
  走默认文案，必 FAIL。
- C-G1【G】`extract` action=retrieve 不覆盖 timeout（`is None`）——现在即 PASS。

纪律：只经公开 `tool.func(**kwargs)` 触发（禁直调私有 `_route_*`）；fake client 必须为
记录型；每个 action 先读 `schemas.py` 构造合法 kwargs；断言 message/hint 只用子串语义，
不锁全句。

装配缝镜像 `test_mcp_tools.py`：MCP 工具在函数体内 lazy import 源头模块
(`inkflow.infrastructure.http`)，故 patch 源头命名空间 `http_mod` 的属性
`InkFlowHTTPClient`（恒返回同一记录的 client 实例）。
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.mcp.tools.manage_tools import _hint_for as _mgr_hint_for
from inkflow.mcp.tools.manage_tools import (
    build_manage_outline_tool,
)
from inkflow.mcp.tools.operation_tools import _hint_for as _op_hint_for
from inkflow.mcp.tools.operation_tools import (
    build_audit_tool,
    build_extract_tool,
    build_write_tool,
)

kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
http_mod = importlib.import_module("inkflow.infrastructure.http")


class FakeClient:
    """有状态记录型 fake：每次 HTTP 调用记录 method/path/params/json/timeout。

    🔴 与镜像不同的是把 `timeout` 一并落盘——#926 契约断言的就是它。`post` 支持
    预置 `post_error`（等价于 AsyncMock 的 side_effect）供 C-R9 注入 HttpApiError。
    """

    def __init__(self, handle):
        self.handle = handle
        self.calls: list[dict] = []
        self.response: object = {"id": "x", "name": "resp"}
        self.raw_response: str = "raw-text"
        self.post_error: Exception | None = None

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, path, *, params=None, json=None) -> dict:
        self.calls.append(
            {"method": "GET", "path": path, "params": params, "json": json, "timeout": None}
        )
        return self.response  # type: ignore[return-value]  # 测试 fake：用例均预置 dict 响应

    async def post(self, path, *, params=None, json=None, timeout=None) -> dict:
        self.calls.append(
            {"method": "POST", "path": path, "params": params, "json": json, "timeout": timeout}
        )
        if self.post_error is not None:
            raise self.post_error
        return self.response  # type: ignore[return-value]  # 测试 fake：用例均预置 dict 响应

    async def patch(self, path, *, params=None, json=None) -> dict:
        self.calls.append(
            {"method": "PATCH", "path": path, "params": params, "json": json, "timeout": None}
        )
        return self.response  # type: ignore[return-value]  # 测试 fake：用例均预置 dict 响应

    async def delete(self, path, *, params=None, json=None) -> dict:
        self.calls.append(
            {"method": "DELETE", "path": path, "params": params, "json": json, "timeout": None}
        )
        return self.response  # type: ignore[return-value]  # 测试 fake：用例均预置 dict 响应


@pytest.fixture
def fake_env(monkeypatch):
    """装配缝：ensure_kernel → 鸭子 handle；InkFlowHTTPClient → 恒返回同一 client 实例。

    🔴 func 内部 `async with InkFlowHTTPClient(handle)` 每次构造新实例——patch 必须
    返回**同一个**预建实例（lambda 闭包），断言 `fake_env.client.calls` 才能命中。
    """
    client = FakeClient(SimpleNamespace(port=1, token="t"))
    fake_ensure = AsyncMock(
        return_value=SimpleNamespace(port=1, token="t", pid=2, version="0.1.0")
    )
    monkeypatch.setattr(kernel_mod, "ensure_kernel", fake_ensure)
    monkeypatch.setattr(http_mod, "InkFlowHTTPClient", lambda handle: client)
    return SimpleNamespace(client=client, fake_ensure=fake_ensure)


def _parse_envelope(text: str) -> dict:
    """解析工具 func 返回的信封 JSON 字符串。"""
    return json.loads(text)


def _last_post(client: FakeClient) -> dict:
    """最近一次 POST 调用（含 timeout 记录）。"""
    posts = [c for c in client.calls if c["method"] == "POST"]
    assert posts, "未发生 POST 调用"
    return posts[-1]


class TestPerRequestTimeout:
    """§4-C-R1..R7：七处 LLM 长任务调用点必须带 per-request timeout=300.0。

    每个 action 经公开 `tool.func(**kwargs)` 触发，断言记录型 fake client 收到的
    `post` 调用 `timeout == 300.0`（RED：当前未带 → None != 300.0 FAIL）。
    """

    @pytest.mark.asyncio
    async def test_outline_generate_timeout(self, fake_env):
        """【R】§4-C-R1：manage_outline action=generate → POST /outlines/generate timeout=300.0。"""
        tool = build_manage_outline_tool()
        await tool.func(
            action="generate", project_id="p1", name="大纲", prompt="生成三卷大纲", num_chapters=3
        )
        post = _last_post(fake_env.client)
        assert post["path"] == "/outlines/generate"
        assert post["timeout"] == 300.0

    @pytest.mark.asyncio
    async def test_write_generate_timeout(self, fake_env):
        """【R】§4-C-R2：write action=generate → POST /writing/generate timeout=300.0。"""
        tool = build_write_tool()
        await tool.func(
            action="generate",
            project_id="p1",
            chapter_id="c1",
            outline="楔子",
            context="背景",
            target_words=1000,
        )
        post = _last_post(fake_env.client)
        assert post["path"] == "/writing/generate"
        assert post["timeout"] == 300.0

    @pytest.mark.asyncio
    async def test_write_continue_timeout(self, fake_env):
        """【R】§4-C-R3：write action=continue → POST /writing/continue timeout=300.0。"""
        tool = build_write_tool()
        await tool.func(
            action="continue",
            project_id="p1",
            chapter_id="c1",
            existing_content="正文",
            context="背景",
            target_words=800,
        )
        post = _last_post(fake_env.client)
        assert post["path"] == "/writing/continue"
        assert post["timeout"] == 300.0

    @pytest.mark.asyncio
    async def test_write_revise_timeout(self, fake_env):
        """【R】§4-C-R4：write action=revise → POST /writing/revise timeout=300.0。"""
        tool = build_write_tool()
        await tool.func(
            action="revise",
            project_id="p1",
            chapter_id="c1",
            content="原稿",
            feedback="节奏太慢",
            instruction="整体提速",
        )
        post = _last_post(fake_env.client)
        assert post["path"] == "/writing/revise"
        assert post["timeout"] == 300.0

    @pytest.mark.asyncio
    async def test_audit_chapter_timeout(self, fake_env):
        """【R】§4-C-R5：audit action=chapter →
        POST /projects/{pid}/chapters/{cid}/audit timeout=300.0。
        """
        tool = build_audit_tool()
        await tool.func(action="chapter", project_id="p1", chapter_id="c1", include_static=True)
        post = _last_post(fake_env.client)
        assert post["path"] == "/projects/p1/chapters/c1/audit"
        assert post["timeout"] == 300.0

    @pytest.mark.asyncio
    async def test_extract_extract_timeout(self, fake_env):
        """【R】§4-C-R6：extract action=extract → POST /extract timeout=300.0。"""
        tool = build_extract_tool()
        await tool.func(action="extract", project_id="p1", content="设定文本")
        post = _last_post(fake_env.client)
        assert post["path"] == "/extract"
        assert post["timeout"] == 300.0

    @pytest.mark.asyncio
    async def test_extract_reindex_timeout(self, fake_env):
        """【R】§4-C-R7：extract action=reindex →
        POST /projects/{pid}/vector/reindex timeout=300.0。
        """
        tool = build_extract_tool()
        await tool.func(action="reindex", project_id="p1", entity_types=["地点", "人物"])
        post = _last_post(fake_env.client)
        assert post["path"] == "/projects/p1/vector/reindex"
        assert post["timeout"] == 300.0


class TestTimeoutEnvelope:
    """§4-C-R9：超时信封语义收敛（TIMEOUT 码 + 自愈 hint）。"""

    @pytest.mark.asyncio
    async def test_timeout_envelope_code_and_hint(self, fake_env):
        """【R】§4-C-R9：HttpApiError(0, 超时文案, "TIMEOUT") → 信封 ok=False、
        error.code=="TIMEOUT" + hint 含「list/get」。

        RED 现状：map_http_error 无 TIMEOUT 分支 → 返回 INTERNAL_ERROR → code 断言 FAIL；
        _hint_for(INTERNAL_ERROR) 走默认文案 → hint 不含「list/get」FAIL。
        """
        from inkflow.infrastructure.http import HttpApiError

        tool = build_manage_outline_tool()
        fake_env.client.post_error = HttpApiError(
            status_code=0,
            detail=(
                "请求超时（300s）：服务端任务可能仍在进行，"
                "请稍后用 list/get 查询结果，勿直接重试"
            ),
            code="TIMEOUT",
        )
        env = _parse_envelope(
            await tool.func(
                action="generate",
                project_id="p1",
                name="n",
                prompt="p",
                num_chapters=3,
            )
        )
        assert env["ok"] is False
        assert env["error"]["code"] == "TIMEOUT"
        assert "list/get" in env["error"]["hint"]


class TestHintForTimeout:
    """§4-C-R10：_hint_for("TIMEOUT") 返回「查询结果」自愈提示（D4，两模块各一份）。"""

    def test_operation_hint_contains_query_result(self):
        """【R】§4-C-R10：operation_tools._hint_for("TIMEOUT") 含「查询结果」。"""
        assert "查询结果" in _op_hint_for("TIMEOUT")

    def test_manage_hint_contains_query_result(self):
        """【R】§4-C-R10：manage_tools._hint_for("TIMEOUT") 含「查询结果」。"""
        assert "查询结果" in _mgr_hint_for("TIMEOUT")


class TestRetrieveNoOverride:
    """§4-C-G1：确定性/embedding 单次查询不吃 300s 覆盖（守护，当前即 PASS）。"""

    @pytest.mark.asyncio
    async def test_extract_retrieve_no_timeout_override(self, fake_env):
        """【G】§4-C-G1：extract action=retrieve → timeout 不覆盖（is None）。"""
        tool = build_extract_tool()
        await tool.func(
            action="retrieve",
            project_id="p1",
            query="查找地点",
            top_k=5,
            min_score=0.3,
        )
        post = _last_post(fake_env.client)
        assert post["path"] == "/projects/p1/vector/retrieve"
        assert post["timeout"] is None
