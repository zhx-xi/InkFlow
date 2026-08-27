"""#708 coverage 补测 鈥?chat_stream 路由缺口分支。

被测模块: ``inkflow.api.routers.chat_stream``
补齐缺口:
- ``_encode_frame`` done 帧无 run_id（82->102）
- stream_chat_agent 通用异常发生在 run 创建前（257->259，run is None）
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.api.routers.chat_stream import ChatStreamRequest, _encode_frame, stream_chat_agent
from inkflow.domain.services.chat_service import ChatStreamEvent

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def test_encode_frame_done_without_run_id() -> None:
    """done 帧未传 run_id 鈫?payload 不含 run_id 键（82->102 分支）。"""
    frame = _encode_frame(ChatStreamEvent(type="done", done=True))
    payload = json.loads(frame.removeprefix("data: ").strip())

    assert payload == {"type": "done", "done": True}
    assert "run_id" not in payload


@pytest.mark.asyncio
async def test_generic_exception_before_run_create_skips_save() -> None:
    """repo.create 抛通用异常（run 未创建）鈫?257->259：仅 error 帧，不 save。"""
    svc = MagicMock()
    mock_repo = MagicMock()
    mock_repo.create = AsyncMock(side_effect=RuntimeError("create boom"))
    mock_repo.save = AsyncMock(return_value=None)
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)

    resp = await stream_chat_agent(
        data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
        request=request,
        svc=svc,
        repo=mock_repo,
    )

    frames = [frame async for frame in resp.body_iterator]
    payload = json.loads(frames[0].removeprefix("data: ").strip())
    assert payload["type"] == "error"
    assert payload["done"] is True
    assert "Agent 执行失败" in payload["error"]
    mock_repo.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_exception_after_run_create_saves_failed() -> None:
    """svc.stream_events 直接抛通用异常（run 已创建）鈫?257->258：save failed + error 帧。"""
    svc = MagicMock()

    async def _boom(**kwargs):
        raise RuntimeError("agent boom")
        yield  # pragma: no cover

    svc.stream_events = _boom
    svc.consume_trace = MagicMock(return_value=([], "", 0))
    mock_repo = MagicMock()
    mock_repo.create = AsyncMock(return_value=MagicMock(id="r1", created_at=MagicMock()))
    mock_repo.save = AsyncMock(return_value=None)
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)

    resp = await stream_chat_agent(
        data=ChatStreamRequest(project_id=PROJECT_ID, prompt="hi"),
        request=request,
        svc=svc,
        repo=mock_repo,
    )

    frames = [frame async for frame in resp.body_iterator]
    payload = json.loads(frames[0].removeprefix("data: ").strip())
    assert payload["type"] == "error"
    assert "Agent 执行失败" in payload["error"]
    mock_repo.save.assert_awaited_once()
