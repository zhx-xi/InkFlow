"""#597 chat agent 流式 SSE 端点冒烟契约 — POST /api/v1/chat/agent/stream（spec f47 §14.2）。

镜像 tests/api/test_chat_stream_api.py（#541 先例）：httpx_sse aconnect_sse +
dependency_overrides 注入 mock ChatAgentService；帧协议在 #541 基础上扩展 type 键
（delta / tool_call / tool_result / done / error）。

RED 阶段：/chat/agent/stream 端点尚未注册 + deps.get_chat_agent_service 尚不存在——
模块顶层给 deps 模块补 MagicMock 属性占位（仅属性缺失时；GREEN 期真函数已定义 →
hasattr 为真 → 跳过），使 fixture 内 import 可解析 → 全部用例跑到端点 →
「路由未注册 → 404」纯断言失败（逐用例粒度，非 collection error）。

GREEN 实现契约（Codex 按此实现，spec §14.2/§14.6）：
1. 端点：chat_stream.py 模块内新增 POST /agent/stream（router 前缀 /api/v1/chat 既有）：
       async def stream_chat_agent(
           data: ChatStreamRequest, request: Request,
           svc: ChatAgentService = Depends(get_chat_agent_service),
       ) -> StreamingResponse
   - handler 内 prompt = (data.prompt or "").strip()；空白 → HTTPException(422, ...)
     （复用 ChatStreamRequest + #541 校验语义）
   - 流内 LLMRequestError / RAGUnavailableError → SSE error 帧（HTTP 仍 200）
2. get_chat_agent_service 在 inkflow.api.deps 模块级定义；chat_stream.py 模块顶层
   `from inkflow.api.deps import get_chat_agent_service`（绑定名同一性 → 本文件
   dependency_overrides 命中；禁止在 chat_stream.py 内重定义/别名）。
3. service 契约：svc.stream_events(prompt: str, chapter_context: str | None = None)
   （async generator 调用，不 await）→ ChatStreamEvent
   （type/delta/done/error/id/name/args/result）。
4. _encode_frame 增 type 键（spec §14.2 帧表）：
   - type="delta"      → {"type": "delta", "delta": str, "done": false}
   - type="tool_call"  → {"type": "tool_call", "id": str, "name": str, "args": dict, "done": false}
   - type="tool_result"→ {"type": "tool_result", "id": str, "name": str,
     "result": str, "done": false}
   - type="done"       → {"type": "done", "done": true}
   - error             → {"type": "error", "error": str, "done": true}
5. StreamingResponse media_type="text/event-stream"。

RED 预期：全部用例 `assert 200 == 404` / `assert 422 == 404` 纯断言失败。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from httpx_sse import aconnect_sse

import inkflow.api.deps as _deps
from inkflow.api.app import app  # 必须先于 stub 行导入（GREEN 时 app 导入链注册真模块/真 deps）
from inkflow.domain.ports.llm_errors import LLMRequestError

# RED 阶段 inkflow.api.deps.get_chat_agent_service 属性尚不存在——补 MagicMock 占位，
# 使 fixture 内 import 可解析（missing-module-stub-patch 规则 1e 变体：父模块已存在、
# 仅属性缺失 → setattr 逃生门）。GREEN 期真函数已定义 → hasattr 为真 → 零改动转绿。
if not hasattr(_deps, "get_chat_agent_service"):
    _deps.get_chat_agent_service = MagicMock()

PROMPT = "帮我整理一下主角的人物设定"


def _ev(
    type_: str,
    delta: str = "",
    done: bool = False,
    error: str | None = None,
    id_: str | None = None,
    name: str | None = None,
    args: dict | None = None,
    result: str | None = None,
) -> SimpleNamespace:
    """构造 ChatStreamEvent 形状的事件对象。

    RED 期 ChatStreamEvent 新字段（type/id/name/args/result）未扩展——SimpleNamespace
    鸭子替代（延迟 import 会把干净 404 RED 变成 TypeError ERROR）；GREEN 期 router
    仅访问属性（鸭子类型），两者兼容。
    """
    return SimpleNamespace(
        type=type_,
        delta=delta,
        done=done,
        error=error,
        id=id_,
        name=name,
        args=args,
        result=result,
    )


def _stream_stub(*events):
    """service.stream_events() mock 工厂 — 返回预置事件序列的 async generator。

    签名锁定 GREEN 契约：`svc.stream_events(prompt=..., chapter_context=...)`。
    """

    async def _gen(prompt: str, chapter_context: str | None = None):
        for ev in events:
            yield ev

    return _gen


@pytest.fixture
def mock_chat_agent_service() -> MagicMock:
    """Mock ChatAgentService — stream_events() 默认产出 delta/tool_call/tool_result/done 帧序列。"""
    svc = MagicMock()
    svc.stream_events = MagicMock(
        side_effect=_stream_stub(
            _ev("delta", delta="你"),
            _ev(
                "tool_call",
                id_="call_1",
                name="search_characters",
                args={"project_id": "550e8400-e29b-41d4-a716-446655440000"},
            ),
            _ev(
                "tool_result",
                id_="call_1",
                name="search_characters",
                result='{"ok": true, "data": []}',
            ),
            _ev("done", done=True),
        )
    )
    return svc


@pytest.fixture
def override_chat_agent_service(mock_chat_agent_service):
    """将 deps 模块级 get_chat_agent_service 依赖替换为 mock（GREEN 期函数对象同一性命中）。"""
    from inkflow.api.deps import get_chat_agent_service

    app.dependency_overrides[get_chat_agent_service] = lambda: mock_chat_agent_service
    yield mock_chat_agent_service
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    """SSE 测试客户端 — 长超时（30s）防流式慢挂（镜像 test_chat_stream_api.py）。"""
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=httpx.Timeout(30.0),
    )


def _payload(prompt: str = PROMPT) -> dict:
    return {"project_id": str(uuid.uuid4()), "prompt": prompt}


# ── 成功路径 ────────────────────────────────────────────────────


class TestChatAgentStreamSuccess:
    """POST /api/v1/chat/agent/stream — 200 + SSE 帧类型表（spec §14.2）。"""

    @pytest.mark.asyncio
    async def test_agent_stream_frame_types(self, override_chat_agent_service):
        """帧类型表：delta / tool_call / tool_result / done 逐帧 JSON 精确锁定。"""
        body = _payload()
        async with (
            _client() as client,
            aconnect_sse(client, "POST", "/api/v1/chat/agent/stream", json=body) as sse,
        ):
            status = sse.response.status_code
            assert status == 200  # RED：路由未注册 → 404，此处断言失败
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
        assert len(frames) == 4
        assert frames[0] == {"type": "delta", "delta": "你", "done": False}
        assert frames[1] == {
            "type": "tool_call",
            "id": "call_1",
            "name": "search_characters",
            "args": {"project_id": "550e8400-e29b-41d4-a716-446655440000"},
            "done": False,
        }
        assert frames[2] == {
            "type": "tool_result",
            "id": "call_1",
            "name": "search_characters",
            "result": '{"ok": true, "data": []}',
            "done": False,
        }
        assert frames[3] == {"type": "done", "done": True}

    @pytest.mark.asyncio
    async def test_agent_stream_calls_service_with_prompt_and_context(
        self, override_chat_agent_service, mock_chat_agent_service
    ):
        """mock stream_events() 收到 prompt + chapter_context（keyword 透传）。"""
        body = {
            **_payload("帮我写一段打斗场景"),
            "chapter_id": str(uuid.uuid4()),
            "chapter_context": "第一章：主角初入宗门，遭遇同门挑衅。",
        }
        async with (
            _client() as client,
            aconnect_sse(client, "POST", "/api/v1/chat/agent/stream", json=body) as sse,
        ):
            status = sse.response.status_code
            assert status == 200
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
        assert frames[-1]["done"] is True
        mock_chat_agent_service.stream_events.assert_called_once_with(
            prompt="帮我写一段打斗场景",
            chapter_context="第一章：主角初入宗门，遭遇同门挑衅。",
        )


# ── 流中错误路径 ────────────────────────────────────────────────


class TestChatAgentStreamErrors:
    """流中 LLM 失败 → SSE error 帧（type='error'），HTTP 仍 200（spec §14.2）。"""

    @pytest.mark.asyncio
    async def test_agent_stream_llm_error_yields_error_frame(
        self, override_chat_agent_service, mock_chat_agent_service
    ):
        """首帧 delta 后抛 LLMRequestError → error 终帧，不泄漏内部细节。"""

        async def _gen(prompt: str, chapter_context: str | None = None):
            yield _ev("delta", delta="你")
            raise LLMRequestError("API key invalid")
            yield  # pragma: no cover

        mock_chat_agent_service.stream_events = _gen
        body = _payload()
        async with (
            _client() as client,
            aconnect_sse(client, "POST", "/api/v1/chat/agent/stream", json=body) as sse,
        ):
            status = sse.response.status_code
            assert status == 200
            frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
        assert len(frames) == 2
        assert frames[0] == {"type": "delta", "delta": "你", "done": False}
        assert frames[1] == {"type": "error", "done": True, "error": "LLM 调用失败，请稍后重试"}
        assert "API key invalid" not in json.dumps(frames, ensure_ascii=False)


# ── 校验错误路径 ────────────────────────────────────────────────


class TestChatAgentStreamValidation:
    """prompt 缺失/空白 → 422（复用 ChatStreamRequest + #541 校验语义）。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            {"project_id": str(uuid.uuid4())},  # prompt 缺失
            {"project_id": str(uuid.uuid4()), "prompt": "   "},  # trim 后为空
        ],
    )
    async def test_missing_or_blank_prompt_returns_422(self, override_chat_agent_service, body):
        async with _client() as client:
            resp = await client.post("/api/v1/chat/agent/stream", json=body)
        assert resp.status_code == 422  # RED：路由未注册 → 404，此处断言失败
