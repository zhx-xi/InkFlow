"""#1186 P2-a/P2-d RED 契约 — supervisor 决策输入含书任务上下文 / 兜底 draft 带 volume_id.

被测行为（对照当前实现全部 FAIL）:

- P2-a：``_build_decision_messages`` 产出的 system 消息当前只有
  章节状态/计数/路由历史/护栏数值（book_agentic_pipeline.py:248-287），
  **缺**书任务上下文（WritingPlan title + 大纲切片 + 角色摘要 + 风格偏好）。
  spec：specs/f27-writer-agent/spec.md f49 §5.3 L707-711。

- P2-d：``BookAgenticPipeline._delegate_write`` 的兜底 ``draft_service.create``
  （book_agentic_pipeline.py:812-818）只传 ``source_outline_id``，**漏 volume_id**；
  另两轨（book_service.py:866-872 / book_pipeline.py:505-512）都传。
  → 本契约要求 pipeline 装配 ``volume_lookup``（镜像 book_pipeline）并在兜底透传解析值。

RED 形态：本文件可在当前实现下正常收集并运行（父侧要求「先跑 → 确认 FAIL」，
非 collection error）。P2-a 断言 system 文本含书任务上下文；
P2-d 断言兜底 create 收到非 None 的 volume_id。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from inkflow.domain.models.writing_plan import BookLimits, WritingPlan

pytestmark = pytest.mark.asyncio

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
VOLUME_OUTLINE_ID = uuid.UUID("aaaaaaaa-1111-2222-3333-444444444444")
VOLUME_ID = uuid.UUID("bbbbbbbb-1111-2222-3333-444444444444")

BOOK_TITLE = "蜀山，我是掌门"
CHAPTER_OUTLINE = "主角随师父出诊，于山道救下重伤的散修，引出医武不分家的传承。"
CHARACTER_SUMMARY = "主角：少年掌门，医道初成，性格沉静。"
PROJECT_STYLE = "古典仙侠，白描为主，忌恶俗打脸立威。"


def _make_plan() -> WritingPlan:
    """真实 WritingPlan（含 title；character_ids 走摘要来源）。"""
    return WritingPlan(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        title=BOOK_TITLE,
        character_ids=[uuid.uuid4()],
        root_outline_id=VOLUME_OUTLINE_ID,
    )


def _make_chapters() -> list[dict]:
    return [
        {
            "outline_id": uuid.uuid4(),
            "chapter_id": uuid.uuid4(),
            "name": "第一章 山道救人",
            "description": CHAPTER_OUTLINE,
            "volume_outline_id": VOLUME_OUTLINE_ID,
            "sort_order": 0,
        }
    ]


def _gotos(op: str, outline_id) -> str:
    """决策 JSON（goto 形态）。"""
    return f'{{"action": "goto", "op": "{op}", "outline_id": "{outline_id}"}}'


def _make_limits() -> BookLimits:
    return BookLimits(max_chapters=5, max_agent_calls=50)


class _CapturingLLM:
    """捕获决策消息的 fake LLM（镜像 FakeDecisionLLM 判别式：system 含「决策」）。

    decisions: 决策轮次队列；耗尽后回 '{"action": "finish"}'。
    """

    def __init__(self, decisions: list[str] | None = None) -> None:
        self.decision_systems: list[str] = []
        self._decisions = list(decisions or [])

    async def chat(self, messages, **kwargs):
        system = messages[0].content if messages else ""
        if "决策" in system:
            self.decision_systems.append(system)
            content = self._decisions.pop(0) if self._decisions else '{"action": "finish"}'
            return SimpleNamespace(content=content)
        return SimpleNamespace(content='{"score": 85, "issues": []}')


class _CaptureDraftService:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id=str(uuid.uuid4()))


class _FakeAgent:
    def __init__(self, content: str) -> None:
        self._content = content

    async def invoke(self, messages, config=None):
        return {"messages": [{"role": "assistant", "content": self._content}]}


class _FakeWriterFactory:
    def __init__(self) -> None:
        self.content = "本章正文。" * 50

    async def __call__(self, **kwargs):
        return _FakeAgent(self.content)


# ── P2-a：supervisor 决策输入含书任务上下文 ────────────────────


class TestSupervisorDecisionContext:
    async def test_decision_system_includes_book_title(self) -> None:
        """P2-a：决策 system 消息须含书任务上下文 —— WritingPlan title（f49 §5.3）。"""
        from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

        llm = _CapturingLLM()
        pipeline = BookAgenticPipeline(llm, context_builder=None)
        await pipeline.execute(_make_plan(), _make_chapters(), _make_limits())

        assert llm.decision_systems, "supervisor 未产生决策调用"
        system = llm.decision_systems[0]
        assert BOOK_TITLE in system, f"决策输入缺书任务上下文（title）：\n{system}"
        # 标签形态锚定「书任务上下文」段（防误命中章节名等其它位置）
        assert "书任务" in system or "书名" in system, f"决策输入缺书任务上下文段：\n{system}"

    async def test_decision_system_includes_outline_slice(self) -> None:
        """P2-a：决策输入须含大纲切片（章 description 片段，f49 §5.3）。"""
        from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

        llm = _CapturingLLM()
        pipeline = BookAgenticPipeline(llm, context_builder=None)
        await pipeline.execute(_make_plan(), _make_chapters(), _make_limits())

        system = llm.decision_systems[0]
        assert CHAPTER_OUTLINE[:20] in system, f"决策输入缺大纲切片：\n{system}"

    async def test_decision_system_includes_style_preference(self) -> None:
        """P2-a：决策输入须含风格偏好（project style；缺席则通用祈使句）。"""
        from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

        llm = _CapturingLLM()

        async def _style_getter(project_id):
            return SimpleNamespace(writing_style=PROJECT_STYLE, default_words=3000)

        pipeline = BookAgenticPipeline(
            llm, context_builder=None, project_config_getter=_style_getter
        )
        await pipeline.execute(_make_plan(), _make_chapters(), _make_limits())

        system = llm.decision_systems[0]
        assert PROJECT_STYLE in system, f"决策输入缺风格偏好：\n{system}"

    async def test_decision_system_includes_character_summary(self) -> None:
        """P2-a：决策输入须含角色摘要（F6 context 装配文本经 context_builder 注入）。"""
        from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

        llm = _CapturingLLM()

        async def _ctx_builder(project_id, chapter):
            return CHARACTER_SUMMARY

        pipeline = BookAgenticPipeline(llm, context_builder=_ctx_builder)
        await pipeline.execute(_make_plan(), _make_chapters(), _make_limits())

        system = llm.decision_systems[0]
        assert CHARACTER_SUMMARY in system, f"决策输入缺角色摘要：\n{system}"


# ── P2-d：兜底 draft 带 volume_id ────────────────────────────


class TestFallbackDraftVolume:
    async def test_fallback_draft_carries_volume_id(self) -> None:
        """P2-d：兜底 draft_service.create 须收到非 None 的 volume_id（镜像另两轨）。

        路由到 fallback 的确定性手法：决策返回一个合法 ``goto``，但 ``max_steps=0``
        → `_guarded_route` 首条判据（steps >= max_steps）即返回 None → supervisor
        goto="fallback"（见 book_agentic_pipeline `_supervisor_node` / `_guarded_route`）。
        注意：不能靠「决策队列耗尽→finish」——``action == "finish"`` 在护栏之前短路。
        """
        from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

        chapters = _make_chapters()
        drafts = _CaptureDraftService()
        llm = _CapturingLLM([_gotos("write_chapter", chapters[0]["outline_id"])])

        async def _volume_lookup(project_id, lookup_id):
            return VOLUME_ID

        pipeline = BookAgenticPipeline(
            llm,
            writer_factory=_FakeWriterFactory(),
            draft_service=drafts,
            audit_callable=llm.chat,
            volume_lookup=_volume_lookup,
        )
        # max_steps=0 → 首个决策必被护栏判 fallback（确定性兜底路径）
        await pipeline.execute(
            _make_plan(), chapters, BookLimits(max_chapters=5, max_agent_calls=50, max_steps=0)
        )

        assert drafts.created, "兜底未产生 draft_service.create 调用"
        for call in drafts.created:
            assert (
                call.get("volume_id") == VOLUME_ID
            ), f"兜底 draft 未透传 volume_id（应为 {VOLUME_ID}）：{call}"

    async def test_no_volume_lookup_leaves_volume_none(self) -> None:
        """P2-d 反例守护：未装配 volume_lookup → volume_id=None（既有装配不受影响）。"""
        from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

        chapters = _make_chapters()
        drafts = _CaptureDraftService()
        llm = _CapturingLLM([_gotos("write_chapter", chapters[0]["outline_id"])])
        pipeline = BookAgenticPipeline(
            llm, writer_factory=_FakeWriterFactory(), draft_service=drafts, audit_callable=llm.chat
        )
        await pipeline.execute(
            _make_plan(), chapters, BookLimits(max_chapters=5, max_agent_calls=50, max_steps=0)
        )

        assert drafts.created, "兜底未产生 draft_service.create 调用"
        for call in drafts.created:
            assert call.get("volume_id") is None
