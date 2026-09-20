"""#1316 兄弟轨契约：卷级 / 自主编排 pipeline 的空产出守卫走同一 helper。

补测动机（CI `coverage-function` 门禁实证）：`book_service` 轨的守卫由
`test_book_empty_content_1316.py` 覆盖，但两条兄弟轨的重试闭包
（`BookVolumePipeline._delegate_chapter.<locals>._invoke_again` /
`BookAgenticPipeline._delegate_write.<locals>._invoke_again`）未被任何用例走到 →
`FAIL: new uncalled functions`。本文件补上这两条的端到端行为契约。

契约（与 book_service 轨同语义）：
- 首空 → 重试 1 次 → 次正常 → 章节成功；
- 连续 2 次空 → `ChapterContentEmptyError`（消息含「LLM 空产出」），空串不落草稿；
- 重试 token 并入 usage 事件（计费口径不丢）。
"""

import uuid
from datetime import UTC, datetime

import pytest

from inkflow.domain.services.usage_accounting import ChapterContentEmptyError


def _chapter(**overrides) -> dict:
    base = {
        "outline_id": uuid.uuid4(),
        "chapter_id": uuid.uuid4(),
        "name": "第一章",
        "description": "主角在时间旅途中发现悖论",
        "sort_order": 0,
    }
    base.update(overrides)
    return base


def _plan():
    from inkflow.domain.models.writing_plan import WritingPlan

    return WritingPlan(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="空产出守卫测试",
        status="running",
        root_outline_id=uuid.uuid4(),
        character_ids=[],
        limits={"max_chapters": 100, "max_agent_calls": 200},
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class _ScriptedAgent:
    """按脚本逐次返回 invoke 结果（空产出 → 正常 → ...）。"""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.invoke_count = 0

    async def invoke(self, messages, config=None):
        content = self._contents.pop(0) if self._contents else ""
        self.invoke_count += 1
        return {
            "messages": [{"role": "assistant", "content": content}],
            "usage": {"total_tokens": 100},
        }


class _ScriptedWriterFactory:
    """每次 writer_factory 调用返回同一脚本 agent（重试=同一章重新委托）。"""

    def __init__(self, agent: _ScriptedAgent) -> None:
        self._agent = agent
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._agent


class _RecordingDraftService:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, **kwargs):
        from types import SimpleNamespace

        self.created.append(kwargs)
        return SimpleNamespace(id="draft-1")


# ── 卷级轨（BookVolumePipeline） ──────────────────────────────────


def _volume_pipeline(agent: _ScriptedAgent, drafts: _RecordingDraftService):
    from langgraph.checkpoint.memory import InMemorySaver

    from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline

    return BookVolumePipeline(
        llm_client=None,
        writer_factory=_ScriptedWriterFactory(agent),
        draft_service=drafts,
        retry_limit=2,
        checkpointer=InMemorySaver(),
    )


@pytest.mark.asyncio
async def test_volume_pipeline_empty_content_retries_then_succeeds_1316():
    """【R】卷级轨：首空 → 重试 → 正常 → 成功（重试闭包被走到）。"""
    agent = _ScriptedAgent(["", "第一章正文内容"])
    drafts = _RecordingDraftService()
    pipeline = _volume_pipeline(agent, drafts)
    pipeline._plan = _plan()

    execution_id, event = await pipeline._delegate_chapter(_chapter())

    assert execution_id == "draft-1"
    assert agent.invoke_count == 2  # 1 初始 + 1 重试
    assert len(drafts.created) == 1
    assert drafts.created[0]["content"].strip() == "第一章正文内容"
    assert event["total_tokens"] == 200  # 重试 token 并入事件


@pytest.mark.asyncio
async def test_volume_pipeline_empty_twice_raises_1316():
    """【R】卷级轨：连续 2 次空 → ChapterContentEmptyError，空串不落草稿。"""
    agent = _ScriptedAgent(["", ""])
    drafts = _RecordingDraftService()
    pipeline = _volume_pipeline(agent, drafts)
    pipeline._plan = _plan()

    with pytest.raises(ChapterContentEmptyError, match="LLM 空产出"):
        await pipeline._delegate_chapter(_chapter())

    assert agent.invoke_count == 2
    assert drafts.created == []


# ── 自主编排轨（BookAgenticPipeline） ────────────────────────────


def _agentic_pipeline(agent: _ScriptedAgent, drafts: _RecordingDraftService):
    from langgraph.checkpoint.memory import InMemorySaver

    from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

    return BookAgenticPipeline(
        llm_client=None,
        writer_factory=_ScriptedWriterFactory(agent),
        draft_service=drafts,
        retry_limit=2,
        checkpointer=InMemorySaver(),
    )


@pytest.mark.asyncio
async def test_agentic_pipeline_empty_content_retries_then_succeeds_1316():
    """【R】自主编排轨：首空 → 重试 → 正常 → 成功（重试闭包被走到）。"""
    agent = _ScriptedAgent(["", "第一章正文内容"])
    drafts = _RecordingDraftService()
    pipeline = _agentic_pipeline(agent, drafts)
    pipeline._plan = _plan()

    execution_id, event = await pipeline._delegate_write(_chapter())

    assert execution_id == "draft-1"
    assert agent.invoke_count == 2
    assert len(drafts.created) == 1
    assert drafts.created[0]["content"].strip() == "第一章正文内容"
    assert event["total_tokens"] == 200  # 重试 token 并入本事件


@pytest.mark.asyncio
async def test_agentic_pipeline_empty_twice_raises_1316():
    """【R】自主编排轨：连续 2 次空 → ChapterContentEmptyError，空串不落草稿。"""
    agent = _ScriptedAgent(["", ""])
    drafts = _RecordingDraftService()
    pipeline = _agentic_pipeline(agent, drafts)
    pipeline._plan = _plan()

    with pytest.raises(ChapterContentEmptyError, match="LLM 空产出"):
        await pipeline._delegate_write(_chapter())

    assert agent.invoke_count == 2
    assert drafts.created == []
