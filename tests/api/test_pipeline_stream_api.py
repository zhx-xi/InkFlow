"""#642-1 管线 SSE 流式端点冒烟契约 — POST /api/v1/agent/pipelines/stream。

镜像 tests/api/test_chat_agent_api.py（#597 先例）：httpx_sse aconnect_sse +
patch _svc 注入 mock stream_pipeline；帧协议 delta / done（final_output + intent）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from httpx_sse import aconnect_sse

from inkflow.api.app import app

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _ev_frame(
    type_: str,
    delta: str = "",
    done: bool = False,
    final_output: str = "",
    intent: str | None = None,
    error: str = "",
    execution_id: str | None = None,
):
    """构造 PipelineStreamEvent 形状的事件对象（鸭子替身，避免 RED 期 import 前置依赖）。"""
    return SimpleNamespace(
        type=type_,
        delta=delta,
        done=done,
        final_output=final_output,
        intent=intent,
        error=error,
        execution_id=execution_id,
    )


def _stream_stub(*events):
    """mock service.stream_pipeline(data) — 返回预置事件序列的 async generator。"""

    async def _gen(data):
        for ev in events:
            yield ev

    return _gen


def _mock_svc(*events) -> MagicMock:
    svc = MagicMock()
    svc.stream_pipeline = _stream_stub(*events)
    return svc


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=httpx.Timeout(30.0)
    )


def _payload(pipeline: str = "builtin:write_auto") -> dict:
    return {"project_id": PROJECT_ID, "pipeline": pipeline}


class TestPipelineStreamSuccess:
    """POST /api/v1/agent/pipelines/stream — 200 + SSE 帧（delta / done 带 final_output）。"""

    @pytest.mark.asyncio
    async def test_stream_delta_and_done_frames(self):
        """帧序列：delta → delta → done(final_output, intent=content) 逐帧 JSON 精确锁定。"""
        svc = _mock_svc(
            _ev_frame("delta", delta="序章：风起"),
            _ev_frame("delta", delta="青云山巅。"),
            _ev_frame("done", done=True, final_output="序章：风起青云山巅。", intent="content"),
        )
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with (
                _client() as client,
                aconnect_sse(
                    client, "POST", "/api/v1/agent/pipelines/stream", json=_payload()
                ) as sse,
            ):
                assert sse.response.status_code == 200
                assert sse.response.headers["content-type"].startswith("text/event-stream")
                frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
        assert len(frames) == 3
        assert frames[0] == {"type": "delta", "delta": "序章：风起", "done": False}
        assert frames[1] == {"type": "delta", "delta": "青云山巅。", "done": False}
        assert frames[2] == {
            "type": "done",
            "done": True,
            "final_output": "序章：风起青云山巅。",
            "intent": "content",
        }

    @pytest.mark.asyncio
    async def test_stream_error_frame(self):
        """service 抛异常 → SSE error 帧（HTTP 仍 200）。"""
        svc = MagicMock()

        async def _gen(data):
            raise RuntimeError("boom")

        svc.stream_pipeline = _gen
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with (
                _client() as client,
                aconnect_sse(
                    client, "POST", "/api/v1/agent/pipelines/stream", json=_payload()
                ) as sse,
            ):
                assert sse.response.status_code == 200
                frames = [json.loads(ev.data) async for ev in sse.aiter_sse()]
        assert len(frames) == 1
        assert frames[0]["type"] == "error"
        assert frames[0]["done"] is True


class TestPipelineStreamValidation:
    """builtin:chat 缺 prompt → 422（镜像 execute_pipeline 校验语义）。"""

    @pytest.mark.asyncio
    async def test_chat_without_prompt_422(self):
        svc = _mock_svc()
        with patch("inkflow.api.routers.agent._svc", return_value=svc):
            async with _client() as client:
                resp = await client.post(
                    "/api/v1/agent/pipelines/stream", json=_payload(pipeline="builtin:chat")
                )
        assert resp.status_code == 422
