"""#988 创建点回填 RED 契约 — F49 agentic 轨（BookAgenticPipeline._delegate_write）.

被测: book_agentic_pipeline.py:792 建草稿调用。章 dict 恒含 outline_id
（L803 usage 事件同键实证）→ GREEN 必把 chapter["outline_id"] 作为
source_outline_id 透传给 draft_service.create。

当前 create kwargs 无该键 → FakeDraftService.created[0] KeyError（RED）。
fake 形态镜像 test_book_agentic_pipeline.py（FakeDecisionLLM/FakeWriterFactory/
FakeDraftService，write→mark_done→finish 最短序列）。

asyncio 模式: pyproject asyncio_mode = "auto"；文件级 pytestmark 双保险。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

pytestmark = pytest.mark.asyncio


def _make_chapters(n: int) -> list[dict]:
    """n 个章 dict（镜像 test_book_agentic_pipeline._make_chapters）。"""
    return [
        {
            "outline_id": uuid.uuid4(),
            "chapter_id": uuid.uuid4(),
            "name": f"第{i + 1}章",
            "description": f"第{i + 1}章大纲描述",
            "sort_order": i,
        }
        for i in range(n)
    ]


def _make_limits(**kw) -> object:
    from inkflow.domain.models.writing_plan import BookLimits

    return BookLimits(**kw)


def _make_plan() -> object:
    return SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status="running",
        progress={},
        execution_refs={},
        limits={},
        character_ids=[],
        root_outline_id=None,
        title="测试书",
    )


def _gotos(op: str, outline_id) -> str:
    return f'{{"action": "goto", "op": "{op}", "outline_id": "{outline_id}"}}'


class FakeDecisionLLM:
    """supervisor 决策 fake（镜像 test_book_agentic_pipeline.FakeDecisionLLM）。"""

    def __init__(self, decisions: list[str]) -> None:
        self.decisions = list(decisions)

    async def chat(self, messages, **kwargs):
        system = messages[0].content if messages else ""
        if "决策" in system:
            content = self.decisions.pop(0) if self.decisions else '{"action": "finish"}'
            return SimpleNamespace(content=content)
        return SimpleNamespace(content='{"score": 85, "issues": []}')


class FakeWriterFactory:
    def __init__(self, content: str = "本章正文。" * 50) -> None:
        self.content = content

    async def __call__(self, **kwargs):
        agent = AsyncMock()
        agent.invoke.return_value = {"messages": [{"role": "assistant", "content": self.content}]}
        return agent


class RecordingDraftService:
    """记录 create kwargs 的 fake draft_service（镜像 FakeDraftService 形态）。"""

    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id=str(uuid.uuid4()))


async def test_agentic_write_delegate_passes_source_outline_id() -> None:
    """【R】单章 write→mark_done→finish → draft_service.create 收 source_outline_id."""
    chapters = _make_chapters(1)
    drafts = RecordingDraftService()
    llm = FakeDecisionLLM(
        [
            _gotos("write_chapter", chapters[0]["outline_id"]),
            _gotos("mark_done", chapters[0]["outline_id"]),
            '{"action": "finish"}',
        ]
    )
    pipeline = BookAgenticPipeline(
        llm,
        writer_factory=FakeWriterFactory(),
        draft_service=drafts,
        audit_callable=llm.chat,
    )

    result = await pipeline.execute(
        _make_plan(), chapters, _make_limits(max_chapters=5, max_agent_calls=50)
    )

    assert result["status"] == "completed"
    assert len(drafts.created) == 1
    # 当前 create kwargs 无该键 → KeyError（RED）；GREEN 后 = 章 dict outline_id
    assert drafts.created[0]["source_outline_id"] == chapters[0]["outline_id"]
    # 既有绑定语义守护（当前即成立）
    assert drafts.created[0]["chapter_id"] == chapters[0]["chapter_id"]
