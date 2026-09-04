"""#915 RED 契约：write_book_agentic 服务层直传 Outline 对象给 dict 消费 pipeline。

真实装配链缺陷（main @ d7d38e1 实证）：`book_run_mixin.write_book_agentic` 把
`_find_chapters` 产出的 `list[Outline]` 原样传入 `BookAgenticPipeline.execute`，
而 pipeline 消费契约 = 章 dict（`_find_chapter`/`_build_decision_messages`/
`_delegate_write` 均 `ch.get(...)`/`chapter[...]`）→ book_supervisor 节点即抛
`AttributeError: 'Outline' object has no attribute 'get'` → 真实 agentic run 整链
崩溃。volume 轨在拆章层有 `_outline_to_chapter_dict` 统一转换（2026-08-17 冒烟
先例），agentic 入口漏镜像。

契约（issue #915 期望 1/2）：
- write_book_agentic 传 pipeline 前统一转 ChapterDict 形态（镜像 volume 轨，
  服务层函数体 import 规避模块级循环）；「内容已写」安全阀仍在 Outline 形态先跑。
- 本文件 = 真实 BookAgenticPipeline + BookService 端到端（outline_repo 产真实
  Outline 对象）——堵死「AsyncMock pipeline 吞任意入参形态」盲区。

用例标注：
- 【R】当前崩溃 → write_book_agentic 传播 AttributeError → FAILED（修复锚）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService
from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

pytestmark = pytest.mark.asyncio


def _plan() -> WritingPlan:
    return WritingPlan(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="测试计划",
        status="running",
        root_outline_id=uuid.uuid4(),
        character_ids=[],
        limits={
            "max_chapters": 100,
            "max_agent_calls": 200,
            "max_tokens": 200_000,
            "tokens_used": 0,
            "tokens_warning": False,
        },
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _outline(plan: WritingPlan, sort_order: int) -> Outline:
    """真实 Outline 领域对象（_find_chapters 产物形态——缺陷触发源）。"""
    return Outline(
        id=uuid.uuid4(),
        project_id=plan.project_id,
        name=f"第{sort_order + 1}章",
        description="测试大纲切片",
        sort_order=sort_order,
        level="chapter",
        parent_id=plan.root_outline_id,
        chapter_id=uuid.uuid4(),
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _gotos(op: str, outline_id) -> str:
    return f'{{"action": "goto", "op": "{op}", "outline_id": "{outline_id}"}}'


class FakeDraftService:
    """draft_service 记录型 fake（镜像 test_book_agentic_pipeline.py 既有形态）。"""

    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id=str(uuid.uuid4()))


class FakeDecisionLLM:
    """supervisor 决策 fake（镜像 test_book_agentic_pipeline.py 形态）。"""

    def __init__(self, decisions: list[str]) -> None:
        self.decisions = list(decisions)
        self.call_count = 0

    async def chat(self, messages, **kwargs):
        self.call_count += 1
        system = messages[0].content if messages else ""
        if "决策" in system:
            content = self.decisions.pop(0) if self.decisions else '{"action": "finish"}'
            return SimpleNamespace(content=content)
        return SimpleNamespace(content='{"score": 85, "issues": ["节奏略慢"]}')


def _make_service(
    plan: WritingPlan, chapters: list[Outline], decisions: list[str]
) -> tuple[BookService, BookAgenticPipeline, FakeDraftService]:
    """真实装配链：BookService + 真实 BookAgenticPipeline + outline_repo 产 Outline。

    draft_service 用记录型 fake（镜像 test_book_agentic_pipeline.FakeDraftService——
    AsyncMock 的 .created 子 mock 永不记录 kwargs，#915 父侧修）。"""
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = (chapters, len(chapters))
    draft_service = FakeDraftService()

    async def writer_factory(**kwargs):
        agent = AsyncMock()
        agent.invoke.return_value = {
            "messages": [{"role": "assistant", "content": "本章正文内容。"}]
        }
        return agent

    llm = FakeDecisionLLM(decisions)
    pipeline = BookAgenticPipeline(
        llm,
        writer_factory=writer_factory,
        draft_service=draft_service,
        audit_callable=llm.chat,
    )
    svc = BookService(
        repo=repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
        outline_repo=outline_repo,
        agentic_pipeline=pipeline,
    )
    return svc, pipeline, draft_service


async def test_write_book_agentic_real_pipeline_completes() -> None:
    """【R】真实 BookAgenticPipeline + Outline 对象章源 → write_book_agentic 不崩：

    当前实现直传 list[Outline] → book_supervisor 节点 _build_decision_messages
    对 Outline 调 .get → AttributeError 传播 → 本用例 FAILED（修复锚）。
    期望（修复后）：completed + 每章 done + 草稿落库（委托真实发生）。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    oids = [str(c.id) for c in chapters]
    decisions = [
        _gotos("write_chapter", chapters[0].id),
        _gotos("audit_chapter", chapters[0].id),
        _gotos("mark_done", chapters[0].id),
        _gotos("write_chapter", chapters[1].id),
        _gotos("audit_chapter", chapters[1].id),
        _gotos("mark_done", chapters[1].id),
        '{"action": "finish"}',
    ]
    svc, _pipeline, drafts = _make_service(plan, chapters, decisions)

    result = await svc.write_book_agentic(plan.id, limits=BookLimits())

    assert result["status"] == "completed", f"#915 真实装配链崩溃/未完成：{result['status']}"
    assert plan.status == "completed"
    assert plan.progress == {oid: "done" for oid in oids}
    assert len(drafts.created) == 2, "两章各一次委托落草稿（委托真实发生）"
    for call in drafts.created:
        assert (call["content"] or "").strip()
    assert set(plan.execution_refs.keys()) == set(oids)


async def test_write_book_agentic_chapter_id_none_survives() -> None:
    """【R】Outline.chapter_id 为 None（大纲节点未绑章）→ 转换后 dict["chapter_id"]=None，

    pipeline 委托/draft 落库均容忍 None（ChapterDict.chapter_id: uuid | None 契约）。
    当前崩溃形态同上 → FAILED 修复锚。
    """
    plan = _plan()
    chapter = _outline(plan, 0)
    chapter = chapter.model_copy(update={"chapter_id": None})
    chapters = [chapter]
    decisions = [
        _gotos("write_chapter", chapter.id),
        _gotos("audit_chapter", chapter.id),
        _gotos("mark_done", chapter.id),
        '{"action": "finish"}',
    ]
    svc, _pipeline, drafts = _make_service(plan, chapters, decisions)

    result = await svc.write_book_agentic(plan.id, limits=BookLimits())

    assert result["status"] == "completed"
    assert plan.progress == {str(chapter.id): "done"}
    assert len(drafts.created) == 1
    assert drafts.created[0]["chapter_id"] is None
