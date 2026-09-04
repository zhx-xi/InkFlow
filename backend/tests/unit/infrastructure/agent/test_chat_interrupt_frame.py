"""#766 阶段② ChatAgentService interrupt SSE 帧契约测试.

spec f26-agent-tools §6.3（HITL 中断机制: stream_events 遇 `__interrupt__` 帧 →
发送 interrupt SSE 帧 type="interrupt" payload={...} → 前端弹窗）+ §6.5 装配点
（chat_stream.py stream_events 检测 `__interrupt__`）。契约锁定:
1. stream_events 遇 astream_events v2 `on_chain_stream` 事件、data.chunk 为含
   `__interrupt__` 键的 dict（langgraph 1.2.10 实测形态: value 为
   (Interrupt(value=payload),) 元组）→ yield ChatStreamEvent(type="interrupt",
   payload={"tool": ..., "entity_id": ..., "entity_name": ...}, done=False)
   ——而非落入 except 变 error 帧;
2. 非 interrupt 事件（delta / 非 dict chunk 的 on_chain_stream）不受影响，
   流仍以 done 终帧结束;
3. _encode_frame 新增 interrupt 分支 → SSE 帧
   {"type": "interrupt", "payload": {...}, "done": false}（前端 HITL 弹窗依据）。

ChatStreamEvent 扩展（父侧 GREEN 契约）: 新增 `payload: dict | None = None`
字段（spec §6.3 `type: "interrupt"`, `payload: {...}`; payload 内容 =
tool/entity_id/entity_name 三键，与 delete_tools.py L255-260 interrupt(payload)
同源）。

RED 形态:
- ChatStreamEvent 无 payload 字段 → 构造 interrupt 帧 TypeError FAILED;
- stream_events 无 __interrupt__ 检测分支 → 帧序列缺 interrupt FAILED;
- _encode_frame 无 interrupt 分支 → 落入 delta 分支帧形不符 FAILED。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langgraph.types import Interrupt

from inkflow.api.routers.chat_stream import _encode_frame
from inkflow.domain.services.chat_service import ChatStreamEvent
from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

SYSTEM_PROMPT = "你是 InkFlow 系统级 Agent，拥有全部创作工具"

INTERRUPT_PAYLOAD = {
    "tool": "delete_character",
    "entity_id": "550e8400-e29b-41d4-a716-44665544000c",
    "entity_name": "角色",
}


def _chunk(content: str) -> SimpleNamespace:
    """AIMessageChunk 鸭子替身（.content）。"""
    return SimpleNamespace(content=content)


def _llm_chunk_event(content: str) -> dict:
    """astream_events v2: on_chat_model_stream（run_type='llm'）→ delta 帧源。"""
    return {
        "event": "on_chat_model_stream",
        "run_type": "llm",
        "data": {"chunk": _chunk(content)},
    }


def _interrupt_chunk_event(payload: dict) -> dict:
    """astream_events v2: on_chain_stream 的 chunk 含 __interrupt__ 键。

    langgraph 1.2.10 实测形态: chunk = {"__interrupt__": (Interrupt(value=payload),)}
    （探针脚本验证，非臆造）。
    """
    return {
        "event": "on_chain_stream",
        "name": "ChatAgent",
        "run_id": "chain_1",
        "data": {"chunk": {"__interrupt__": (Interrupt(value=payload),)}},
    }


class _FakeAgent:
    """fake deepagents agent — astream_events 为 async generator，按预置事件 dict 列表 yield。"""

    def __init__(self, events: list[dict] | None = None) -> None:
        self._events = list(events or [])

    async def astream_events(self, inputs, version="v2", config=None):
        for ev in self._events:
            yield ev


def _make_svc(events: list[dict]) -> tuple[ChatAgentService, _FakeAgent]:
    """构造 ChatAgentService(agent=fake, system_prompt=...)。"""
    agent = _FakeAgent(events=events)
    svc = ChatAgentService(agent=agent, system_prompt=SYSTEM_PROMPT)
    return svc, agent


class TestChatInterruptFrame:
    """ChatAgentService.stream_events __interrupt__ 检测 → interrupt 帧契约。"""

    @pytest.mark.asyncio
    async def test_interrupt_chunk_yields_interrupt_frame(self) -> None:
        """__interrupt__ chunk → ChatStreamEvent(type="interrupt", payload=tool 三键,
        done=False)；流仍以 done 终帧结束，无 error 帧。"""
        svc, _ = _make_svc(events=[_interrupt_chunk_event(INTERRUPT_PAYLOAD)])
        frames = [ev async for ev in svc.stream_events(prompt="删除主角")]

        assert [ev.type for ev in frames] == ["interrupt", "done"]
        ev = frames[0]
        assert ev.done is False
        assert ev.payload == INTERRUPT_PAYLOAD
        assert set(ev.payload.keys()) == {"tool", "entity_id", "entity_name"}
        assert frames[-1].type == "done"
        assert frames[-1].done is True
        assert not any(f.type == "error" for f in frames)

    @pytest.mark.asyncio
    async def test_interrupt_mid_stream_keeps_delta_and_done(self) -> None:
        """delta + 非 dict chunk 的 on_chain_stream + interrupt + delta →
        [delta, interrupt, delta, done]：非 interrupt 帧不受影响，无 error 帧。"""
        svc, _ = _make_svc(
            events=[
                _llm_chunk_event("你"),
                {"event": "on_chain_stream", "data": {"chunk": "plain text"}},
                _interrupt_chunk_event(INTERRUPT_PAYLOAD),
                _llm_chunk_event("好"),
            ]
        )
        frames = [ev async for ev in svc.stream_events(prompt="你好")]

        assert [ev.type for ev in frames] == ["delta", "interrupt", "delta", "done"]
        assert [ev.delta for ev in frames if ev.type == "delta"] == ["你", "好"]
        assert not any(ev.type == "error" for ev in frames)

    def test_encode_frame_interrupt_branch(self) -> None:
        """_encode_frame interrupt 分支 → SSE 帧
        {"type": "interrupt", "payload": {...}, "done": false}（前端弹窗依据）。"""
        ev = ChatStreamEvent(type="interrupt", payload=INTERRUPT_PAYLOAD, done=False)
        frame = _encode_frame(ev)
        parsed = json.loads(frame.split("data: ", 1)[-1].strip())

        assert parsed == {
            "type": "interrupt",
            "payload": INTERRUPT_PAYLOAD,
            "done": False,
        }
