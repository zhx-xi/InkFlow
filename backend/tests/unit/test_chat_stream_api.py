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
from unittest.mock import AsyncMock, MagicMock, patch

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


async def test_stream_chat_redacts_secret_before_sending_to_svc():
    """#614 端点级脱敏：prompt 进 svc.stream 前经 redact_secrets 替换（spec §3.2/§4.1 回调语义）。

    RED 状态：redact_secrets 尚未接线进 chat_stream.py——patch 后 router 不会调用它，
    因此 mock_redact.assert_called_once 失败、svc 收到的是原始明文 prompt = 预期 FAIL（门禁 M1）。
    """
    data = ChatStreamRequest(project_id=str(uuid.uuid4()), prompt="使用密钥 sk-abcdefghijklm 测试")
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)

    captured_prompts = []

    async def _svc_stream(**kwargs):
        captured_prompts.append(kwargs.get("prompt"))
        yield ChatStreamEvent(done=True)

    svc = MagicMock()
    svc.stream = _svc_stream

    with patch(
        "inkflow.api.routers.chat_stream.redact_secrets",
        return_value="使用密钥 sk-**** 测试",
    ) as mock_redact:
        resp = await stream_chat(data=data, request=request, svc=svc)
        frames = [frame async for frame in resp.body_iterator]

    mock_redact.assert_called_once()
    assert captured_prompts == ["使用密钥 sk-**** 测试"]
    assert frames  # 脱敏不改变流式出帧行为
