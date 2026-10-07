"""#1439 supervisor 任务清单（落库 + 供决策）—— RED 契约。

设计真相源：``specs/f44-book-orchestrator/spec.md`` §5.9（链路）+ §2.1（WritingPlan.tasklist）
+ §12 D15（三点结论）+ §13.8（M20-M22）+ §9.2 场景 12-15。

本文件锁定 **supervisor 侧**契约：

A. **产出**（M20）：每条**被接受**的决策 → ``tasklist`` 追加一条
   ``{"op", "outline_id", "title"}``（``title`` = 目标章名；取不到 → ``outline_id``；
   ``finish_book`` 条目 ``outline_id=""``）。
B. **持久化 + 同源**（M20）：运行收尾把 checkpoint state 的 ``tasklist`` 写回
   ``plan.tasklist``（共享引用；落库由 ``BookService.write_book_agentic`` 承担）；
   ``get_checkpoint_state()["tasklist"]`` 与 ``plan.tasklist`` 同源。
C. **回读**（M21）：``execute`` 以 ``plan.tasklist`` 播种 → 下次运行的决策消息含
   「上次清单」段（提示上下文）。
D. **降级**（M22）：决策 4 次重试耗尽 → 追加 ``{"op": "__degraded__",
   "reason": "decision_invalid"}`` + **不崩**（走既有 fallback/abort）。
E. **非约束**（M21 负例）：预置清单**不覆盖** supervisor 决策
   （``_guarded_route`` 语义零改动）—— 清单只是上下文，非约束。

RED 预期（backfill 前）：``WritingPlan`` 无 ``tasklist`` 字段 / state 无 ``tasklist``
通道 / 决策消息无「上次清单」段 → 断言 FAIL（新模块经函数体惰性 import，
避免整文件收集期失败，保证每条断言各自可用）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from inkflow.domain.models.writing_plan import BookLimits, WritingPlan
from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

pytestmark = pytest.mark.asyncio

_PLAN_ID = uuid.UUID("01920000-0000-7000-8000-00000000f143")
_PROJECT_ID = uuid.UUID("01920000-0000-7000-8000-000000000001")


def _make_chapters(n: int) -> list[dict]:
    """n 个章 dict（ChapterDict 形态）。"""
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


def _make_plan(**overrides) -> WritingPlan:
    """真实 WritingPlan（tasklist 为新增字段；RED 期不存在 → AttributeError）。"""
    base: dict = dict(
        id=_PLAN_ID,
        project_id=_PROJECT_ID,
        title="测试书",
        status="running",
        root_outline_id=None,
        character_ids=[],
        limits={},
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return WritingPlan(**base)


def _limits() -> BookLimits:
    return BookLimits(max_chapters=20, max_agent_calls=100)


def _config(**kw) -> object:
    from inkflow.domain.models.agent_book import AgenticBookConfig

    kw.setdefault("audit_required", False)
    return AgenticBookConfig(**kw)


def _gotos(op: str, outline_id) -> str:
    return f'{{"action": "goto", "op": "{op}", "outline_id": "{outline_id}"}}'


class FakeDecisionLLM:
    """书级 supervisor 决策 fake（system prompt 含「决策」→ 返回队列决策）。

    ``systems`` 记录每次决策 system prompt，供「上次清单读回」断言。
    """

    def __init__(self, decisions: list[str]) -> None:
        self.decisions = list(decisions)
        self.systems: list[str] = []

    async def chat(self, messages, **kwargs):
        system = messages[0].content if messages else ""
        if "决策" in system:
            self.systems.append(system)
            content = self.decisions.pop(0) if self.decisions else '{"action": "finish"}'
            return SimpleNamespace(content=content)
        return SimpleNamespace(content='{"score": 80, "issues": []}')

    @property
    def decision_calls(self) -> int:
        return len(self.systems)


class _FakeAgent:
    def __init__(self, content: str) -> None:
        self._content = content

    async def invoke(self, messages, config=None):
        return {"messages": [{"role": "assistant", "content": self._content}]}


class FakeWriterFactory:
    def __init__(self, content: str = "本章正文。" * 50) -> None:
        self.content = content

    async def __call__(self, **kwargs):
        return _FakeAgent(self.content)


class FakeDraftService:
    def __init__(self, content: str = "本章正文。" * 50) -> None:
        self.content = content

    async def create(self, **kwargs):
        return SimpleNamespace(id=str(uuid.uuid4()))

    async def get(self, draft_id):
        return SimpleNamespace(id=draft_id, content=self.content)


class GarbageDecisionLLM:
    """恒返回非法决策（4 次重试全失败）→ 驱动降级路径。"""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        return SimpleNamespace(content="这不是 JSON 决策")


def _pipeline(llm) -> BookAgenticPipeline:
    return BookAgenticPipeline(
        llm, writer_factory=FakeWriterFactory(), draft_service=FakeDraftService()
    )


def _ops(tasklist: list[dict]) -> list[str]:
    return [str(e.get("op")) for e in tasklist]


# ══════════════════════════════════════════════════════════════════════
# A. 产出 + B. 持久化/同源（M20）
# ══════════════════════════════════════════════════════════════════════


async def test_tasklist_records_each_accepted_decision_with_chapter_title() -> None:
    """每条被接受决策 → 一条 {op, outline_id, title}；title = 目标章名。"""
    chapters = _make_chapters(2)
    plan = _make_plan()
    llm = FakeDecisionLLM(
        [
            _gotos("write_chapter", chapters[0]["outline_id"]),
            _gotos("mark_done", chapters[0]["outline_id"]),
            _gotos("write_chapter", chapters[1]["outline_id"]),
            _gotos("mark_done", chapters[1]["outline_id"]),
            '{"action": "finish"}',
        ]
    )
    pipeline = _pipeline(llm)

    await pipeline.execute(plan, chapters, _limits(), config=_config())

    assert _ops(plan.tasklist) == [
        "write_chapter",
        "mark_done",
        "write_chapter",
        "mark_done",
        "finish_book",
    ]
    first = plan.tasklist[0]
    assert first["outline_id"] == str(chapters[0]["outline_id"])
    assert first["title"] == "第1章"
    # finish_book 条目无章锚点
    assert plan.tasklist[-1]["outline_id"] == ""


async def test_tasklist_persisted_and_checkpoint_state_same_source() -> None:
    """收尾回写 plan.tasklist；get_checkpoint_state()["tasklist"] 与 plan.tasklist 同源。"""
    chapters = _make_chapters(1)
    plan = _make_plan()
    llm = FakeDecisionLLM(
        [
            _gotos("write_chapter", chapters[0]["outline_id"]),
            _gotos("mark_done", chapters[0]["outline_id"]),
            '{"action": "finish"}',
        ]
    )
    pipeline = _pipeline(llm)

    result = await pipeline.execute(plan, chapters, _limits(), config=_config())
    state = await pipeline.get_checkpoint_state(result["run_id"])

    assert state is not None
    assert _ops(state["tasklist"]) == _ops(plan.tasklist)
    assert _ops(plan.tasklist) == ["write_chapter", "mark_done", "finish_book"]


# ══════════════════════════════════════════════════════════════════════
# C. 回读（M21）：播种 → 下次决策消息含「上次清单」段
# ══════════════════════════════════════════════════════════════════════


async def test_next_run_seeds_from_persisted_tasklist_and_shows_it_in_prompt() -> None:
    """plan.tasklist 非空 → execute 播种（state 前缀保留）+ 决策消息含「上次清单」段。"""
    chapters = _make_chapters(1)
    seeded = [
        {"op": "write_chapter", "outline_id": str(chapters[0]["outline_id"]), "title": "第1章"}
    ]
    plan = _make_plan(tasklist=list(seeded))
    llm = FakeDecisionLLM(
        [
            _gotos("mark_done", chapters[0]["outline_id"]),
            '{"action": "finish"}',
        ]
    )
    pipeline = _pipeline(llm)

    result = await pipeline.execute(plan, chapters, _limits(), config=_config())
    state = await pipeline.get_checkpoint_state(result["run_id"])

    assert state is not None
    # 播种条目在最终清单前缀（回读证据 1）
    assert state["tasklist"][0] == seeded[0]
    # 决策消息带「上次清单」段（回读证据 2）
    assert any("上次清单" in s for s in llm.systems), llm.systems[:1]


# ══════════════════════════════════════════════════════════════════════
# D. 降级（M22）：决策非法 → 不崩 + 降级条目
# ══════════════════════════════════════════════════════════════════════


async def test_invalid_decision_records_degraded_entry_without_crashing() -> None:
    """LLM 决策恒非法 → 追加 __degraded__ 条目 + 走既有 fallback（不崩）。"""
    chapters = _make_chapters(1)
    plan = _make_plan()
    llm = GarbageDecisionLLM()
    pipeline = _pipeline(llm)

    result = await pipeline.execute(plan, chapters, _limits(), config=_config())

    # 不崩：返回 dict 且状态是既有语义（completed via fallback）
    assert result["status"] in ("completed", "aborted")
    degraded = [e for e in plan.tasklist if e.get("op") == "__degraded__"]
    assert degraded, f"应留降级条目，实际 tasklist={plan.tasklist}"
    assert degraded[0]["reason"] == "decision_invalid"


# ══════════════════════════════════════════════════════════════════════
# E. 非约束（M21 负例）：清单不覆盖 supervisor 决策
# ══════════════════════════════════════════════════════════════════════


async def test_preset_tasklist_does_not_constrain_supervisor_decision() -> None:
    """预置清单「先 write 第 1 章」，supervisor 决策 mark_done 第 2 章 → 按决策执行。"""
    chapters = _make_chapters(2)
    preset = [
        {"op": "write_chapter", "outline_id": str(chapters[0]["outline_id"]), "title": "第1章"}
    ]
    plan = _make_plan(tasklist=list(preset))
    llm = FakeDecisionLLM(
        [
            _gotos("mark_done", chapters[1]["outline_id"]),
            '{"action": "finish"}',
        ]
    )
    pipeline = _pipeline(llm)

    result = await pipeline.execute(plan, chapters, _limits(), config=_config())
    state = await pipeline.get_checkpoint_state(result["run_id"])

    assert state is not None
    # 实际路由 = supervisor 决策（mark_done 第 2 章），不是清单声明的 write 第 1 章
    assert state["route_history"][0] == "mark_done"
    assert state["progress"][str(chapters[1]["outline_id"])] == "done"
    assert state["progress"].get(str(chapters[0]["outline_id"])) != "done"
    # 清单记录的是**被执行的**决策（mark_done 第 2 章），非预置声明的 write 第 1 章
    assert _ops(state["tasklist"]) == ["write_chapter", "mark_done", "finish_book"]
    assert state["tasklist"][1]["outline_id"] == str(chapters[1]["outline_id"])
