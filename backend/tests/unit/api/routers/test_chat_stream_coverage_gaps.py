"""Coverage backfill: chat_stream 公开 route handler 的未覆盖分支（f47 §14.2 帧协议）。

全部通过公开接口 ``stream_chat_agent``（route handler）驱动，断言 SSE 帧：
- ``_result_to_str`` 非 str 结果：dict → JSON 序列化；不可序列化对象 → str() 兜底
  （工具结果帧，f47 §14.2 tool_result 帧）。
- ``_encode_frame`` reasoning 帧（f47 §14.2 推理增量）。
- 用户中断（#719）：cancel_event 置位 → TERMINATED 运行落库 + done 终帧（含 run_id），
  覆盖循环内（299-300）与循环后（332-333）两条路径。

镜像 tests/unit/api/routers/test_chat_stream_gaps.py 的 mock 模式：直接
await stream_chat_agent(data, request, svc, repo)。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.api.routers.chat_stream import ChatStreamRequest, stream_chat_agent
from inkflow.domain.models.agent_run import AgentRun, AgentRunStatus
from inkflow.domain.services.chat_service import ChatStreamEvent

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _make_run() -> AgentRun:
    """最小 AgentRun（repo.create 返回对象）。"""
    now = datetime.now(UTC)
    return AgentRun(
        id="chat-run-cov-0001",
        project_id=uuid.UUID(PROJECT_ID),
        created_at=now,
        updated_at=now,
    )


def _make_repo() -> MagicMock:
    repo = MagicMock()
    repo.create = AsyncMock(return_value=_make_run())
    repo.save = AsyncMock(return_value=None)
    return repo


def _make_request() -> MagicMock:
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)
    return request


async def _frames(resp) -> list[dict]:
    """收集 body_iterator 全部 SSE 帧并解析为 dict。"""
    raw = [frame async for frame in resp.body_iterator]
    return [json.loads(f.split("data: ", 1)[-1].strip()) for f in raw]


def _stream_factory(events, on_first=None):
    """包装事件序列为 svc.stream_events 绑定（async generator）。"""
    called = False

    async def _gen(prompt, project_id=None, chapter_context=None, cancel_event=None):
        nonlocal called
        for ev in events:
            if on_first is not None and not called:
                called = True
                on_first(cancel_event)
            yield ev

    return _gen


@pytest.mark.asyncio
async def test_agent_stream_reasoning_frame_encoded() -> None:
    """reasoning 帧 → SSE {"type": "reasoning", "delta": ..., "done": false}。"""
    svc = MagicMock()
    svc.stream_events = _stream_factory(
        [
            ChatStreamEvent(type="reasoning", delta="思考中…"),
            ChatStreamEvent(type="done", done=True),
        ]
    )
    svc.consume_trace = MagicMock(return_value=([], "", 0))
    repo = _make_repo()
    data = ChatStreamRequest(project_id=PROJECT_ID, prompt="hi")

    resp = await stream_chat_agent(data=data, request=_make_request(), svc=svc, repo=repo)
    frames = await _frames(resp)

    reasoning = next(f for f in frames if f.get("type") == "reasoning")
    assert reasoning["delta"] == "思考中…"
    assert reasoning["done"] is False
    assert frames[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_agent_stream_tool_result_dict_json_serialized() -> None:
    """tool_result.result 为非 str dict → JSON 字符串序列化（f47 §14.2）。"""
    svc = MagicMock()
    svc.stream_events = _stream_factory(
        [
            ChatStreamEvent(
                type="tool_result",
                id="call_1",
                name="search_characters",
                result={"ok": True, "count": 2},
            ),
            ChatStreamEvent(type="done", done=True),
        ]
    )
    svc.consume_trace = MagicMock(return_value=([], "", 0))
    repo = _make_repo()
    data = ChatStreamRequest(project_id=PROJECT_ID, prompt="hi")

    resp = await stream_chat_agent(data=data, request=_make_request(), svc=svc, repo=repo)
    frames = await _frames(resp)

    tool_result = next(f for f in frames if f.get("type") == "tool_result")
    assert json.loads(tool_result["result"]) == {"ok": True, "count": 2}


@pytest.mark.asyncio
async def test_agent_stream_tool_result_unserializable_falls_back_to_str() -> None:
    """tool_result.result 不可 JSON 序列化 → str(result) 兜底（不抛错）。"""
    svc = MagicMock()
    svc.stream_events = _stream_factory(
        [
            ChatStreamEvent(
                type="tool_result",
                id="call_1",
                name="search_characters",
                result=SimpleNamespace(name="林晚"),
            ),
            ChatStreamEvent(type="done", done=True),
        ]
    )
    svc.consume_trace = MagicMock(return_value=([], "", 0))
    repo = _make_repo()
    data = ChatStreamRequest(project_id=PROJECT_ID, prompt="hi")

    resp = await stream_chat_agent(data=data, request=_make_request(), svc=svc, repo=repo)
    frames = await _frames(resp)

    tool_result = next(f for f in frames if f.get("type") == "tool_result")
    assert "namespace(name=" in tool_result["result"]


@pytest.mark.asyncio
async def test_agent_stream_cancel_inside_loop_saves_terminated() -> None:
    """循环内 cancel 置位（首个事件后）→ TERMINATED 落库 + done 终帧（#719）。"""
    svc = MagicMock()

    def _set_cancel(cancel_event) -> None:
        if cancel_event is not None:
            cancel_event.set()

    svc.stream_events = _stream_factory(
        [ChatStreamEvent(delta="一段"), ChatStreamEvent(delta="内容")],
        on_first=_set_cancel,
    )
    svc.consume_trace = MagicMock(return_value=([], "内容", 10))
    repo = _make_repo()
    data = ChatStreamRequest(project_id=PROJECT_ID, prompt="hi")

    resp = await stream_chat_agent(data=data, request=_make_request(), svc=svc, repo=repo)
    frames = await _frames(resp)

    assert frames[0]["type"] == "run_started"
    assert frames[-1]["type"] == "done"
    assert frames[-1]["run_id"] == "chat-run-cov-0001"
    save_call = repo.save.await_args
    assert save_call is not None
    saved = save_call.args[0]
    assert saved.status == AgentRunStatus.TERMINATED
    assert saved.terminated_by == "user"
    assert saved.final_content == "内容"


@pytest.mark.asyncio
async def test_agent_stream_cancel_after_loop_saves_terminated() -> None:
    """循环结束后 cancel 置位 → 兜底 TERMINATED 落库 + done 终帧（#719）。"""
    svc = MagicMock()

    async def _gen(prompt, project_id=None, chapter_context=None, cancel_event=None):
        yield ChatStreamEvent(type="done", done=True)
        if cancel_event is not None:
            cancel_event.set()

    svc.stream_events = _gen
    svc.consume_trace = MagicMock(return_value=([], "", 0))
    repo = _make_repo()
    data = ChatStreamRequest(project_id=PROJECT_ID, prompt="hi")

    resp = await stream_chat_agent(data=data, request=_make_request(), svc=svc, repo=repo)
    frames = await _frames(resp)

    done_frames = [f for f in frames if f.get("type") == "done"]
    assert len(done_frames) == 2  # completed + terminated 兜底
    save_calls = [c.args[0] for c in repo.save.await_args_list]
    assert [s.status for s in save_calls] == [
        AgentRunStatus.COMPLETED,
        AgentRunStatus.TERMINATED,
    ]
