"""#576 coverage 补测：chat_stream is_disconnected 分支。

直接调用 router 函数（非 HTTP 层，同 #177 先例：TestClient 异常路径是
coverage 盲区），覆盖 src/inkflow/api/routers/chat_stream.py 第 67-69 行：
`if await request.is_disconnected(): return` 提前返回分支。

用例：
- test_stream_chat_disconnected_returns_no_frames：is_disconnected=True →
  事件循环第一个事件即提前 return，不 yield 任何帧
- test_stream_chat_disconnected_false_yields_frames：对照用例，证明 0 帧
  是 disconnected 导致而非流为空（is_disconnected=False → 正常 yield 全部帧）
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from inkflow.api.routers.chat_stream import ChatStreamRequest, stream_chat
from inkflow.domain.services.chat_service import ChatStreamEvent


def _make_svc_stream(events):
    """返回可 async for 迭代的 svc.stream 绑定（真实 async generator）。"""

    async def _gen(**_kwargs):
        for ev in events:
            yield ev

    return _gen


async def test_stream_chat_disconnected_returns_no_frames():
    """is_disconnected=True：首个事件即提前 return，body_iterator 不产生任何帧。"""
    data = ChatStreamRequest(project_id=str(uuid.uuid4()), prompt="你好")
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=True)
    events = [
        ChatStreamEvent(delta="你"),
        ChatStreamEvent(delta="好"),
        ChatStreamEvent(done=True),
    ]
    svc = MagicMock()
    svc.stream = _make_svc_stream(events)

    resp = await stream_chat(data=data, request=request, svc=svc)
    frames = [frame async for frame in resp.body_iterator]

    assert frames == []


async def test_stream_chat_disconnected_false_yields_frames():
    """is_disconnected=False：对照用例，正常 yield 全部事件帧（证明 0 帧由断开导致）。"""
    data = ChatStreamRequest(project_id=str(uuid.uuid4()), prompt="你好")
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)
    events = [
        ChatStreamEvent(delta="你"),
        ChatStreamEvent(delta="好"),
        ChatStreamEvent(done=True),
    ]
    svc = MagicMock()
    svc.stream = _make_svc_stream(events)

    resp = await stream_chat(data=data, request=request, svc=svc)
    frames = [frame async for frame in resp.body_iterator]

    assert len(frames) == len(events)
    assert '"delta"' in frames[0]
