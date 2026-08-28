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

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from inkflow.api.routers.chat_stream import ChatStreamRequest, stream_chat, stream_chat_agent
from inkflow.domain.models.agent_run import AgentRun
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
    data = ChatStreamRequest(project_id=str(uuid.uuid4()), prompt="使用密钥 «redacted:sk-…» 测试")
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


# ── #748 设定库写入工具：/agent/stream 工具调用后正确终止（不卡 running） ──

AGENT_PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _make_agent_stream(events):
    """返回可 async for 迭代的 svc.stream_events 绑定（真实 async generator）。"""

    async def _gen(prompt, project_id=None, chapter_context=None, cancel_event=None):
        for ev in events:
            yield ev

    return _gen


def _parse_frame(raw: str) -> dict:
    """剥离 SSE `data: ` 前缀与尾随换行后 json.loads（body_iterator 产出原始帧串）。"""
    return json.loads(raw.split("data: ", 1)[-1].strip())


async def test_agent_stream_setting_write_reaches_done_without_error():
    """#748：/agent/stream 触发设定库写入工具 → tool_call + tool_result + done，无 error 帧。

    RED 期：设定库写入工具（create_character 等）在 chat agent tools 集不存在 → 装配的
    build_deep_agent tools 不含之；但端点对工具帧编码是通用的，本用例在端点层锁定
    「工具调用后产 tool_call/tool_result + done 终帧、无 error、不无限 running」行为。
    若端点对工具帧处理回归（如缺失 done 兜底）→ 本用例 FAIL。
    """
    now = datetime.now(UTC)
    run = AgentRun(
        id="chat-run-0001",
        project_id=uuid.UUID(AGENT_PROJECT_ID),
        created_at=now,
        updated_at=now,
    )
    repo = MagicMock()
    repo.create = AsyncMock(return_value=run)
    repo.save = AsyncMock(return_value=None)
    svc = MagicMock()
    svc.stream_events = _make_agent_stream(
        [
            ChatStreamEvent(
                type="tool_call",
                id="call_1",
                name="create_character",
                args={"name": "林晚"},
            ),
            ChatStreamEvent(
                type="tool_result",
                id="call_1",
                name="create_character",
                result='{"ok": true, "character_id": "char-1"}',
            ),
            ChatStreamEvent(type="done", done=True),
        ]
    )
    svc.consume_trace = MagicMock(return_value=([], "", 0))
    data = ChatStreamRequest(project_id=AGENT_PROJECT_ID, prompt="创建角色林晚")
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)

    resp = await stream_chat_agent(data=data, request=request, svc=svc, repo=repo)
    frames = [_parse_frame(f) async for f in resp.body_iterator]

    types = [f.get("type") for f in frames]
    assert "error" not in types
    assert "tool_call" in types
    assert "tool_result" in types
    tool_call = next(f for f in frames if f.get("type") == "tool_call")
    assert tool_call["name"] == "create_character"
    assert tool_call["args"] == {"name": "林晚"}
    tool_result = next(f for f in frames if f.get("type") == "tool_result")
    assert '"ok": true' in tool_result["result"]
    assert "char-1" in tool_result["result"]
    # 终帧必须是 done（不无限 running、不裸断）
    assert frames[-1]["type"] == "done"
    assert frames[-1]["done"] is True
