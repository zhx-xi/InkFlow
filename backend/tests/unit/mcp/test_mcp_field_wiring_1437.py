"""#1437 MCP 字段接线契约（RED）——「声明了却零消费」同族第三批（承接 #1436 口径）。

Issue #1437 两条静默失效（字段已声明、``extra="forbid"`` 拦不到、工具层零消费 →
调用方拿 ``{ok: true}`` 却什么都没发生）：

A. ``write action=revise`` 的 ``instruction`` —— 声明但从不读取
   （``_route_write`` revise 分支 body 只发 project_id/chapter_id/content/feedback）；
   内核 DTO ``RevisionRequest`` **无** ``instruction`` 字段（只有 content/feedback/
   target_range/model/temperature）。
   拍板（承接 #1436 既定口径 + CLI 先例）：
   ``instruction`` 是内核 ``feedback`` 的**回退别名** —— ``feedback`` 缺失时落到
   ``feedback``（CLI ``write revise --instruction`` → ``"feedback": instruction`` 同一语义）；
   ``feedback`` 存在时**仍以 feedback 为准**（既有 ``test_revise`` /
   ``test_write_revise_timeout`` 已钉住该优先级，不新造冲突报错，勿改既有测试）。

B. ``export`` 的 ``output_path`` —— 声明但从不读取
   内核侧**无对应能力**：``GET /projects/{pid}/export``（``get_raw``）直接回文本，
   无任何路径参数；MCP 工具的职责是把文本交给调用方，服务端不写调用方文件系统
   （任意路径写入是安全反模式）。故按 issue 约束「无法接线的字段 → 显式报错 + 说明」
   处理：传 ``output_path`` → 本地 ``INVALID_ARGS``（**零 HTTP**，把「静默无操作」
   升级为显式失败），与同函数既有 ``format != txt`` 护栏同形。

── 装配缝（镜像 test_mcp_field_wiring_1436.py）────────────────
func 内 lazy import 源头模块 → patch ``http_mod.InkFlowHTTPClient`` 恒返回同一记录型
FakeClient；只经公开面触发：``MCP_TOOL_REGISTRY`` 取工具 → ``func(**kwargs)``。

── RED 形态 ────────────────────────────────────────────────────
A 组：``instruction`` 单给 → body 无 ``feedback`` 键 → ``RevisionRequest.model_validate``
抛 ``ValidationError``（instruction 被静默丢弃）；B 组：``output_path`` 被接受（无护栏）
→ ``ok=True`` 且发生 HTTP 调用 → 断言 ``ok is False`` / 零调用 FAIL；
C 组：``test_mcp_field_wiring_1436.py`` 的 ``_KNOWN_UNWIRED`` 清空后，真实源码审计
``missing == {WriteParams.instruction, ExportParams.output_path} != set()`` → FAIL。
GREEN 落地后整批转绿。

── 测试约定 ────────────────────────────────────────────────────
- body/params 断言一律 ``.get(...)``（缺键 → None → AssertionError，而非 KeyError）。
- 落点断言经**内核 DTO 本体**校验（``RevisionRequest.model_validate``），
  而非仅比对键名 —— 键名对但被静默吞掉的形态必须能被抓住。
"""

from __future__ import annotations

import importlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.writing import RevisionRequest
from inkflow.mcp.tools import MCP_TOOL_REGISTRY

kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
http_mod = importlib.import_module("inkflow.infrastructure.http")


class FakeClient:
    """记录型 fake：预置响应队列，逐次出栈，耗尽后回退 ``default``。"""

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


def _tool(name: str):
    """按名取已装配工具（tools/list 同源）。"""
    return next(tool for tool in MCP_TOOL_REGISTRY if tool.spec.name == name)


def _envelope(text: str) -> dict:
    return json.loads(text)


def _last_body(client: FakeClient) -> dict:
    return client.calls[-1]["json"] or {}


# ── A：write action=revise 的 instruction → 内核 feedback ─────────────


class TestWriteReviseInstruction1437:
    """A：``instruction`` 单给须落到内核 ``RevisionRequest.feedback``（CLI 先例映射）。"""

    def _revise_args(self) -> dict[str, object]:
        return {
            "action": "revise",
            "project_id": str(uuid.uuid4()),
            "chapter_id": str(uuid.uuid4()),
            "content": "待修订正文占位内容样本",  # ≥10 字，满足内核 validator
        }

    @pytest.mark.asyncio
    async def test_instruction_only_is_mapped_to_feedback_key(self, fake_env):
        """``instruction`` 单给 → body 出现 ``feedback`` 键且值逐字相等。"""
        env = _envelope(
            await _tool("write").func(**{**self._revise_args(), "instruction": "精简对话"})
        )
        assert env["ok"] is True
        call = fake_env.client.calls[-1]
        assert (call["method"], call["path"]) == ("POST", "/writing/revise")
        body = call["json"] or {}
        assert body.get("feedback") == "精简对话", "instruction 未落到内核 feedback（静默丢弃）"

    @pytest.mark.asyncio
    async def test_instruction_roundtrip_lands_in_kernel_dto(self, fake_env):
        """往返一致：透传值经**内核 DTO 本体**校验后落在 ``feedback`` 字段上。"""
        await _tool("write").func(**{**self._revise_args(), "instruction": "加快节奏"})
        parsed = RevisionRequest.model_validate(_last_body(fake_env.client))
        assert parsed.feedback == "加快节奏"

    @pytest.mark.asyncio
    async def test_instruction_not_transmitted_as_raw_key(self, fake_env):
        """反例守护：内核 DTO 无 ``instruction`` 字段 → 不得原样发该键。"""
        await _tool("write").func(**{**self._revise_args(), "instruction": "润色措辞"})
        body = _last_body(fake_env.client)
        assert "instruction" not in body, "instruction 原样外发（内核 DTO 无此字段）"

    @pytest.mark.asyncio
    async def test_feedback_precedence_when_both_present(self, fake_env):
        """反例守护：两字段同给 → ``feedback`` 为准（既有 ``test_revise`` 已钉住）。

        ``instruction`` 是 ``feedback`` 的回退别名，不得反向覆盖规范字段。
        """
        env = _envelope(
            await _tool("write").func(
                **{**self._revise_args(), "feedback": "太拖沓", "instruction": "精简"}
            )
        )
        assert env["ok"] is True
        parsed = RevisionRequest.model_validate(_last_body(fake_env.client))
        assert parsed.feedback == "太拖沓"

    @pytest.mark.asyncio
    async def test_feedback_only_path_unchanged(self, fake_env):
        """反例守护：只给 ``feedback`` 的既有通道不得改坏。"""
        env = _envelope(
            await _tool("write").func(**{**self._revise_args(), "feedback": "需补心理描写"})
        )
        assert env["ok"] is True
        parsed = RevisionRequest.model_validate(_last_body(fake_env.client))
        assert parsed.feedback == "需补心理描写"

    def test_kernel_revision_dto_has_no_instruction_field(self):
        """根因取证（反例守护）：内核 ``RevisionRequest`` 确实没有 ``instruction`` 字段。

        一旦该断言失败 → 内核已原生支持 instruction → 本映射契约需重新评估。
        """
        assert "instruction" not in RevisionRequest.model_fields
        assert "feedback" in RevisionRequest.model_fields


# ── B：export 的 output_path（内核无能力）→ 显式报错 ───────────────────


class TestExportOutputPath1437:
    """B：``output_path`` 内核无对应能力 → 显式 ``INVALID_ARGS``（零 HTTP，非静默）。"""

    @pytest.mark.asyncio
    async def test_output_path_is_explicit_error_without_http(self, fake_env):
        env = _envelope(
            await _tool("export").func(
                action="export", project_id="p1", format="txt", output_path="D:/tmp/out.txt"
            )
        )
        assert env["ok"] is False, "output_path 被静默接受（内核无能力，却 ok=True）"
        assert env["error"]["code"] == "INVALID_ARGS"
        assert fake_env.client.calls == [], "output_path 拒绝路径不得发生 HTTP 调用"

    @pytest.mark.asyncio
    async def test_output_path_error_carries_explanation(self, fake_env):
        """显式报错必须带「说明」：讲清为何不支持（issue 约束）。"""
        env = _envelope(
            await _tool("export").func(action="export", project_id="p1", output_path="/tmp/x.txt")
        )
        text = env["error"]["message"] + env["error"]["hint"]
        assert "output_path" in text or "不支持" in text, "错误缺少可自愈说明"

    @pytest.mark.asyncio
    async def test_export_without_output_path_still_returns_text(self, fake_env):
        """反例守护：不传 ``output_path`` 的既有导出通道不得改坏（仍回原始文本）。"""
        env = _envelope(await _tool("export").func(action="export", project_id="p1", format="txt"))
        assert env["ok"] is True
        call = fake_env.client.calls[-1]
        assert call["method"] == "GET_RAW"
        assert call["path"] == "/projects/p1/export"

    @pytest.mark.asyncio
    async def test_non_txt_format_still_rejected(self, fake_env):
        """反例守护：既有 ``format != txt`` 护栏不得被新护栏顶掉。"""
        env = _envelope(await _tool("export").func(action="export", project_id="p1", format="md"))
        assert env["ok"] is False
        assert env["error"]["code"] == "INVALID_ARGS"
        assert fake_env.client.calls == []


# ── C：内核 DTO 无法识别未知键（静默丢弃根因，反例守护）──────────────


def test_kernel_dto_silently_ignores_unknown_keys():
    """根因取证：未设 ``extra="forbid"`` 的内核 DTO 会**静默忽略**未知键。

    这正是 A/C 两族「键名对但值不生效 / 声明未接线」的底座形态 ——
    故落点断言必须经 DTO 本体（``model_validate``）取证。
    """
    payload = {
        "project_id": str(uuid.uuid4()),
        "chapter_id": str(uuid.uuid4()),
        "content": "占位正文内容示例文本甲乙",
        "feedback": "占位修订意见",
        "instruction": "这个名字内核根本不认识",
    }
    parsed = RevisionRequest.model_validate(payload)
    assert not hasattr(parsed, "instruction"), "RevisionRequest 已能识别 instruction → 契约需重估"
    assert parsed.feedback == "占位修订意见"
