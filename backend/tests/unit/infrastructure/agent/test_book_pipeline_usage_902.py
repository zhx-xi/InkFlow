"""#902 RED 契约 F2：卷轨（BookVolumePipeline）usage 事件通道采集。

权威来源：.hermes/plans/contract-902.md §1.1/§1.3/§1.4 + §3 F2。
被测（真实图 + InMemorySaver checkpointer）：state["usage"] 事件通道——
每成功 LLM 调用恰一个事件，节点返回增量产出（operator.add reducer 通道），
checkpoint 持久化 → 跨 HITL resume 不丢不重；委托重试中间失败无事件（防伪计费）。

事件 schema：{"source": "write" | "audit" | "decision" | "supervisor",
"chapter": "<outline_id 或 ''>", "prompt_tokens": int, "completion_tokens": int,
"total_tokens": int}

fake 形态镜像 test_book_pipeline.py（_chapter/_volume/_plan/_make_deps/_pipeline）；
agent.invoke 结果带 messages usage_metadata（repro_902.py USAGE_PER_CALL 形态）：
{total_tokens: 100, prompt_tokens: 60, completion_tokens: 40}（2 章 → 每成功章
total=100/prompt=60/completion=40；手工核算：2×100=200 total、2×60=120 prompt、
2×40=80 completion——服务层 F4 复核用）。

用例标注：
- 【R】当前 VolumeState 无 usage 通道 → state["usage"] KeyError → FAILED（修复锚）。
- 【G】旧 fake 无 usage → 无事件/全零事件，执行不抛（RED 期 PASS 刻意）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.infrastructure.agent.book_pipeline import (
    BookVolumePipeline,
    VolumeHITLInterrupt,
)

pytestmark = pytest.mark.asyncio

# 每成功委托的 usage（repro_902.py USAGE_PER_CALL 形态：别名键族）
_USAGE = {"total_tokens": 100, "prompt_tokens": 60, "completion_tokens": 40}


def _chapter(**overrides) -> dict:
    """构造章 dict（镜像 test_book_pipeline.py _chapter）。"""
    base = {
        "outline_id": uuid.uuid4(),
        "chapter_id": uuid.uuid4(),
        "name": "第一章",
        "description": "主角在时间旅途中发现悖论",
        "sort_order": 0,
    }
    base.update(overrides)
    return base


def _volume(chapters, **overrides) -> dict:
    """构造卷 dict: {"volume_id": uuid, "chapters": [章 dict, ...]}。"""
    base = {"volume_id": uuid.uuid4(), "chapters": chapters}
    base.update(overrides)
    return base


def _plan(**overrides):
    """构造 WritingPlan（镜像 test_book_pipeline.py _plan）。"""
    from inkflow.domain.models.writing_plan import WritingPlan

    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "title": "卷级 usage 测试",
        "status": "running",
        "root_outline_id": uuid.uuid4(),
        "character_ids": [],
        "limits": {"max_chapters": 100, "max_agent_calls": 200},
        "progress": {},
        "execution_refs": {},
        "thread_id": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return WritingPlan(**base)


def _usage_agent() -> AsyncMock:
    """成功委托 fake：invoke 结果 messages 带 usage_metadata（真实 graph 返回形态）。"""
    agent = AsyncMock()
    agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="正文", usage_metadata=dict(_USAGE))]
    }
    return agent


def _no_usage_agent() -> AsyncMock:
    """旧 fake：invoke 结果无任何 usage 载体（usage_metadata/usage 均无）。"""
    agent = AsyncMock()
    agent.invoke.return_value = {"messages": [SimpleNamespace(content="正文")]}
    return agent


def _failing_agent() -> AsyncMock:
    """失败委托 fake：invoke 恒抛（重试耗尽 → 章 failed，无 result 可提取 usage）。"""
    agent = AsyncMock()
    agent.invoke.side_effect = RuntimeError("delegate boom")
    return agent


def _deps(**overrides) -> dict:
    """构造 BookVolumePipeline 依赖（默认 writer_factory 恒成功带 usage）。"""
    writer_factory = AsyncMock(return_value=_usage_agent())
    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")
    llm_client = AsyncMock()
    deps = {
        "llm_client": llm_client,
        "writer_factory": writer_factory,
        "draft_service": draft_service,
        "retry_limit": 2,
    }
    deps.update(overrides)
    return deps


def _pipeline(deps: dict) -> BookVolumePipeline:
    """构造真实 BookVolumePipeline（显式 InMemorySaver checkpointer）。"""
    from langgraph.checkpoint.memory import InMemorySaver

    return BookVolumePipeline(
        deps["llm_client"],
        writer_factory=deps["writer_factory"],
        draft_service=deps["draft_service"],
        retry_limit=deps["retry_limit"],
        checkpointer=InMemorySaver(),
    )


# ── R：成功委托产事件（source=write，chapter=outline_id，数值分列）──


async def test_usage_events_two_successful_chapters_write_source() -> None:
    """【R】2 章成功（fake messages usage_metadata 100/60/40）→ checkpoint
    state["usage"] 恰 2 事件：source="write"、chapter=str(outline_id) 匹配、
    total_tokens=100/prompt_tokens=60/completion_tokens=40。

    RED 形态：当前 VolumeState 无 usage 键 → state["usage"] KeyError → FAILED。
    """
    from inkflow.domain.models.writing_plan import BookLimits

    chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(2)]
    pipeline = _pipeline(_deps())
    result = await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())
    assert result["status"] == "completed"

    state = await pipeline.get_checkpoint_state(result["run_id"])
    assert state is not None
    events = state["usage"]  # RED：KeyError
    assert len(events) == 2
    by_chapter = {e["chapter"]: e for e in events}
    for ch in chapters:
        event = by_chapter[str(ch["outline_id"])]
        assert event["source"] == "write"
        assert event["total_tokens"] == 100
        assert event["prompt_tokens"] == 60
        assert event["completion_tokens"] == 40
    # 事件数 = 成功章数（无多余事件）；2×100=200 总耗
    assert sum(e["total_tokens"] for e in events) == 200


# ── R：卷级失败 supervisor 补救产事件（source=supervisor）─────────


async def test_usage_event_supervisor_rescue_from_llm_chat() -> None:
    """【R】全卷 failed → volume_failure interrupt → resume(decision="supervisor")
    → llm.chat 返回带 usage（token_usage 15/10/25）→ state["usage"] 恰 1 事件：
    source="supervisor"、total=25/prompt=15/completion=10；失败的 write 委托零事件。

    RED 形态：当前无 usage 通道 → state["usage"] KeyError → FAILED。
    """
    from inkflow.domain.models.writing_plan import BookLimits

    deps = _deps(writer_factory=AsyncMock(return_value=_failing_agent()))
    # supervisor chat 返回 ChatResponse 形态（token_usage 主源）
    deps["llm_client"].chat.return_value = SimpleNamespace(
        content='{"action": "continue"}',
        token_usage=SimpleNamespace(prompt_tokens=15, completion_tokens=10, total_tokens=25),
    )
    chapter = _chapter()
    pipeline = _pipeline(deps)
    try:
        await pipeline.execute(_plan(), [_volume([chapter])], BookLimits())
        raise AssertionError("全卷 failed 应抛 VolumeHITLInterrupt")
    except VolumeHITLInterrupt as exc:
        interrupt = exc

    result = await pipeline.resume(interrupt, decision="supervisor")
    assert result["status"] == "completed"

    state = await pipeline.get_checkpoint_state(result["run_id"])
    assert state is not None
    events = state["usage"]  # RED：KeyError
    assert len(events) == 1, f"仅 supervisor 补救 1 事件，实际 {events}"
    event = events[0]
    assert event["source"] == "supervisor"
    assert event["total_tokens"] == 25
    assert event["prompt_tokens"] == 15
    assert event["completion_tokens"] == 10


# ── R：失败章无事件（防伪计费）───────────────────────────────────


async def test_usage_no_event_for_failed_chapter_partial_failure() -> None:
    """【R】2 章中 1 成功（usage 100/60/40）+ 1 失败（invoke 恒抛）→ completed；
    state["usage"] 恰 1 事件且 chapter=成功章 outline_id——失败章零事件
    （委托重试中间失败 attempt 抛异常拿不到 result → 天然无事件，防伪计费）。

    RED 形态：当前无 usage 通道 → state["usage"] KeyError → FAILED。
    """
    from inkflow.domain.models.writing_plan import BookLimits

    ok_ch = _chapter(name="成功章", sort_order=0)
    fail_ch = _chapter(name="失败章", sort_order=1)

    async def writer_factory(**kwargs):
        if kwargs.get("expected_chapter_id") == fail_ch["chapter_id"]:
            return _failing_agent()
        return _usage_agent()

    deps = _deps(writer_factory=writer_factory)
    pipeline = _pipeline(deps)
    result = await pipeline.execute(_plan(), [_volume([ok_ch, fail_ch])], BookLimits())
    assert result["status"] == "completed"

    state = await pipeline.get_checkpoint_state(result["run_id"])
    assert state is not None
    assert state["results"][str(fail_ch["outline_id"])] == "failed"
    events = state["usage"]  # RED：KeyError
    assert [e["chapter"] for e in events] == [str(ok_ch["outline_id"])]
    assert events[0]["source"] == "write"


# ── G：旧 fake 无 usage → 无事件/全零，执行不抛 ──────────────────


async def test_legacy_fake_without_usage_no_events_no_raise() -> None:
    """【G】旧 fake（invoke 结果无 usage_metadata 也无顶层 usage）→ 执行不抛、
    completed；state["usage"] 为空或全零事件（无真实 usage 可采集）。

    守护用例 RED 期 PASS 刻意（当前实现根本不采集，天然零事件）。
    """
    from inkflow.domain.models.writing_plan import BookLimits

    chapters = [_chapter(name=f"第{i + 1}章", sort_order=i) for i in range(2)]
    deps = _deps(writer_factory=AsyncMock(return_value=_no_usage_agent()))
    pipeline = _pipeline(deps)
    result = await pipeline.execute(_plan(), [_volume(chapters)], BookLimits())
    assert result["status"] == "completed"

    state = await pipeline.get_checkpoint_state(result["run_id"])
    assert state is not None
    assert sorted(state["results"].keys()) == sorted(str(c["outline_id"]) for c in chapters)
    events = state.get("usage", [])
    assert all(e.get("total_tokens", 0) == 0 for e in events), "无 usage fake 不得产生计费事件"


# ── R：HITL 双卷中断重放不重复计费 ───────────────────────────────


async def test_usage_events_hitl_two_volumes_no_duplicate() -> None:
    """【R】两卷各 1 章：vol0 完成 → volume_boundary interrupt → resume approved
    → vol1 完成 → completed；usage 事件数 = 总章数（2），中断重放不重复计费
    （LangGraph 已完成节点不重放，usage 通道 checkpoint 持久化跨 resume 累积）。

    RED 形态：当前无 usage 通道 → state["usage"] KeyError → FAILED。
    """
    from inkflow.domain.models.writing_plan import BookLimits

    vol0_ch = _chapter(name="一卷章", sort_order=0)
    vol1_ch = _chapter(name="二卷章", sort_order=0)
    deps = _deps()
    pipeline = _pipeline(deps)
    try:
        await pipeline.execute(_plan(), [_volume([vol0_ch]), _volume([vol1_ch])], BookLimits())
        raise AssertionError("卷边界应抛 VolumeHITLInterrupt")
    except VolumeHITLInterrupt as exc:
        interrupt = exc
    assert interrupt.payload.get("volume_index") == 0

    result = await pipeline.resume(interrupt, approved=True)
    assert result["status"] == "completed"

    state = await pipeline.get_checkpoint_state(result["run_id"])
    assert state is not None
    events = state["usage"]  # RED：KeyError
    assert len(events) == 2, f"事件数必须 = 总章数（不重复计费），实际 {len(events)}"
    chapters_by_oid = {str(c["outline_id"]): c for c in (vol0_ch, vol1_ch)}
    for event in events:
        assert event["source"] == "write"
        assert event["chapter"] in chapters_by_oid
        assert event["total_tokens"] == 100
    assert {e["chapter"] for e in events} == set(chapters_by_oid)
