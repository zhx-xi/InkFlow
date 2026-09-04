"""#902 RED 契约 F3：agentic 轨（BookAgenticPipeline）usage 事件通道采集。

权威来源：.hermes/plans/contract-902.md §1.1/§1.3 + §3 F3。
被测（真实 BookAgenticPipeline）：write/audit/revise/fallback 内 write 委托与
supervisor 决策 chat 每成功调用产 usage 事件 → checkpoint state["usage"]：
source ∈ {"write", "audit", "decision"}，数值分列，事件数=成功 LLM 调用数。

fake 形态镜像 test_book_agentic_pipeline.py（_make_chapters/_gotos/FakeDecisionLLM/
_FakeAgent/FakeWriterFactory/FakeDraftService），各响应附加 usage 载体：
- write 委托（agent.invoke messages usage_metadata）：100/60/40（2 次 write → 200/120/80）
- audit chat（llm.chat 返回 usage_metadata dict，AIMessage 鸭子）：15/9/6
- decision chat：7/5/2（每 supervisor 访问 1 次成功 chat）

单章 write→audit→mark_done→finish 序列事件核算（R1 锚点）：
1 write(100/60/40) + 1 audit(15/9/6) + 4 decision(7/5/2 each)
→ 6 事件；total=100+15+28=143、prompt=60+9+20=89、completion=40+6+8=54。

用例标注：
- 【R】当前 BookAgenticState 无 usage 键 → state["usage"] KeyError → FAILED（修复锚）。
- 【G】无 usage fake 零事件/全零事件不抛（RED 期 PASS 刻意）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticPipeline

pytestmark = pytest.mark.asyncio

_W_USAGE = {"total_tokens": 100, "prompt_tokens": 60, "completion_tokens": 40}
_A_USAGE = {"total_tokens": 15, "prompt_tokens": 9, "completion_tokens": 6}
_D_USAGE = {"total_tokens": 7, "prompt_tokens": 5, "completion_tokens": 2}


def _make_chapters(n: int) -> list[dict]:
    """n 个章 dict（ChapterDict 形态，镜像既有测试）。"""
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


def _gotos(op: str, outline_id) -> str:
    return f'{{"action": "goto", "op": "{op}", "outline_id": "{outline_id}"}}'


class _FakeAgent:
    """委托 agent fake：invoke 结果 messages 可选带 usage_metadata（真实形态）。"""

    def __init__(self, content: str, usage_metadata: dict | None = None) -> None:
        self._content = content
        self._usage = usage_metadata

    async def invoke(self, messages, config=None):
        msg = {"role": "assistant", "content": self._content}
        if self._usage is not None:
            msg["usage_metadata"] = dict(self._usage)
        return {"messages": [msg]}


class FakeWriterFactory:
    """writer_factory fake：按章产出带 usage 的 _FakeAgent。"""

    def __init__(self, content: str = "本章正文。", usage_metadata: dict | None = None) -> None:
        self.content = content
        self._usage = usage_metadata
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeAgent(self.content, usage_metadata=self._usage)


class FakeDecisionLLM:
    """supervisor/审校 chat fake：决策调用带 decision usage，审校调用带 audit usage。
    usage=None → 返回纯 SimpleNamespace(content)（旧 fake 形态，G 用例用）。
    audit_usage 未给定时回退 usage_metadata（#902 父侧修：_A_USAGE 按文件头契约
    意图接线到审校分支——原实现把同一 usage 贴给两分支，与 audit=15/9/6 断言矛盾）。"""

    def __init__(
        self,
        decisions: list[str],
        audit_output: str = '{"score": 85, "issues": ["节奏略慢"]}',
        usage_metadata: dict | None = None,
        audit_usage: dict | None = None,
    ) -> None:
        self.decisions = list(decisions)
        self.audit_output = audit_output
        self._usage = usage_metadata
        self._audit_usage = audit_usage
        self.call_count = 0

    def _respond(self, content: str, usage: dict | str | None = "auto") -> SimpleNamespace:
        if usage == "auto":
            usage = self._usage
        if usage is None:
            return SimpleNamespace(content=content)
        return SimpleNamespace(content=content, usage_metadata=dict(usage))

    async def chat(self, messages, **kwargs):
        self.call_count += 1
        system = messages[0].content if messages else ""
        if "决策" in system:
            content = self.decisions.pop(0) if self.decisions else '{"action": "finish"}'
            return self._respond(content)
        # audit_chapter 审校调用（非决策）→ 结构化质量输出（audit_usage 缺省回退 decision usage）
        return self._respond(
            self.audit_output, self._audit_usage if self._audit_usage is not None else "auto"
        )


class FakeDraftService:
    """draft_service fake：记录 create 调用，返回随机 draft id。"""

    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id=str(uuid.uuid4()))


def _make_plan() -> object:
    """WritingPlan 鸭子对象（镜像既有测试 _make_plan：真实 WritingPlan 亦可）。"""
    from inkflow.domain.models.writing_plan import WritingPlan

    return WritingPlan(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="测试书",
        status="running",
        progress={},
        execution_refs={},
        limits={},
        character_ids=[],
        root_outline_id=None,
    )


async def _run_pipeline(
    decisions: list[str],
    chapters: list[dict],
    *,
    write_usage: dict | None = _W_USAGE,
    chat_usage: dict | None = _D_USAGE,
    audit_usage: dict | None = _A_USAGE,
):
    """装配真实 BookAgenticPipeline 并 execute（默认 audit_callable=llm.chat；
    audit_usage=_A_USAGE 按文件头契约接线审校分支）。"""
    from inkflow.domain.models.writing_plan import BookLimits

    plan = _make_plan()
    writer = FakeWriterFactory(usage_metadata=write_usage)
    drafts = FakeDraftService()
    llm = FakeDecisionLLM(decisions, usage_metadata=chat_usage, audit_usage=audit_usage)
    pipeline = BookAgenticPipeline(
        llm, writer_factory=writer, draft_service=drafts, audit_callable=llm.chat
    )
    result = await pipeline.execute(plan, chapters, BookLimits(max_chapters=5, max_agent_calls=50))
    assert result["status"] == "completed"
    return pipeline, result, writer, drafts, llm, plan


# ── R：write→audit→mark_done→finish 事件序列（source/数值分列）────


async def test_usage_events_write_audit_decision_sequence() -> None:
    """【R】单章 write→audit→mark_done→finish → state["usage"] 恰 6 事件：
    write 1（100/60/40）+ audit 1（15/9/6）+ decision 4（7/5/2 each）；source
    分别 write/audit/decision；write/audit 事件 chapter=目标 outline_id。
    全量核算：total=143、prompt=89、completion=54。

    RED 形态：当前 BookAgenticState 无 usage 键 → state["usage"] KeyError → FAILED。
    """
    chapters = _make_chapters(1)
    oid = str(chapters[0]["outline_id"])
    pipeline, result, *_ = await _run_pipeline(
        [
            _gotos("write_chapter", chapters[0]["outline_id"]),
            _gotos("audit_chapter", chapters[0]["outline_id"]),
            _gotos("mark_done", chapters[0]["outline_id"]),
            '{"action": "finish"}',
        ],
        chapters,
    )
    state = await pipeline.get_checkpoint_state(result["run_id"])
    assert state is not None
    events = state["usage"]  # RED：KeyError
    assert len(events) == 6, f"事件数必须=成功 LLM 调用数（6），实际 {len(events)}"
    by_source: dict[str, list[dict]] = {}
    for e in events:
        by_source.setdefault(e["source"], []).append(e)
    assert len(by_source.get("write", [])) == 1
    assert len(by_source.get("audit", [])) == 1
    assert len(by_source.get("decision", [])) == 4
    write_ev = by_source["write"][0]
    assert write_ev["chapter"] == oid
    assert (write_ev["prompt_tokens"], write_ev["completion_tokens"], write_ev["total_tokens"]) == (
        60,
        40,
        100,
    )
    audit_ev = by_source["audit"][0]
    assert audit_ev["chapter"] == oid
    assert (audit_ev["prompt_tokens"], audit_ev["completion_tokens"], audit_ev["total_tokens"]) == (
        9,
        6,
        15,
    )
    for decision_ev in by_source["decision"]:
        triple = (
            decision_ev["prompt_tokens"],
            decision_ev["completion_tokens"],
            decision_ev["total_tokens"],
        )
        assert triple == (5, 2, 7)
    assert sum(e["total_tokens"] for e in events) == 143
    assert sum(e["prompt_tokens"] for e in events) == 89
    assert sum(e["completion_tokens"] for e in events) == 54


# ── R：revise/fallback 路径 write 委托同样产事件 ─────────────────


async def test_usage_events_revise_path_write_delegations() -> None:
    """【R】write→audit→revise→mark_done→finish：revise 内 write 委托同样产事件 →
    write 源事件恰 2（初始写 + 修订写，各 100/60/40，sum 200/120/80）+ audit 1。

    RED 形态：当前无 usage 键 → state["usage"] KeyError → FAILED。
    """
    chapters = _make_chapters(1)
    oid = str(chapters[0]["outline_id"])
    pipeline, result, *_ = await _run_pipeline(
        [
            _gotos("write_chapter", chapters[0]["outline_id"]),
            _gotos("audit_chapter", chapters[0]["outline_id"]),
            _gotos("revise_chapter", chapters[0]["outline_id"]),
            _gotos("mark_done", chapters[0]["outline_id"]),
            '{"action": "finish"}',
        ],
        chapters,
    )
    state = await pipeline.get_checkpoint_state(result["run_id"])
    assert state is not None
    events = state["usage"]  # RED：KeyError
    write_events = [e for e in events if e["source"] == "write"]
    assert len(write_events) == 2, f"初始写 + 修订写 = 2 事件，实际 {len(write_events)}"
    for event in write_events:
        assert event["chapter"] == oid
        assert event["total_tokens"] == 100
    assert sum(e["total_tokens"] for e in write_events) == 200
    assert sum(e["prompt_tokens"] for e in write_events) == 120
    assert sum(e["completion_tokens"] for e in write_events) == 80
    assert sum(1 for e in events if e["source"] == "audit") == 1


async def test_usage_events_fallback_path_writes_all_remaining() -> None:
    """【R】决策全废（LLM 输出不可解析 → 重试耗尽）→ 确定性 fallback 写全部剩余章：
    fallback 内 write 委托产事件 → write 源事件恰 2（各章 100/60/40，chapter 匹配）。

    RED 形态：当前无 usage 键 → state["usage"] KeyError → FAILED。
    """
    chapters = _make_chapters(2)
    oids = {str(c["outline_id"]) for c in chapters}
    pipeline, result, *_ = await _run_pipeline(
        ["not-a-json", "not-a-json", "not-a-json", "not-a-json"], chapters
    )
    state = await pipeline.get_checkpoint_state(result["run_id"])
    assert state is not None
    events = state["usage"]  # RED：KeyError
    write_events = [e for e in events if e["source"] == "write"]
    assert len(write_events) == 2, f"fallback 2 章各 1 次 write 事件，实际 {len(write_events)}"
    assert {e["chapter"] for e in write_events} == oids
    assert all(e["total_tokens"] == 100 for e in write_events)


# ── G：无 usage fake 零事件/全零事件不抛 ─────────────────────────


async def test_legacy_fakes_without_usage_zero_events_no_raise() -> None:
    """【G】旧 fake（原 test_book_agentic_pipeline.py 形态：无任何 usage 载体）→
    执行不抛、completed；state["usage"] 为空或全零事件。

    守护用例 RED 期 PASS 刻意（当前不采集，天然零事件）。
    """
    from inkflow.domain.models.writing_plan import BookLimits

    chapters = _make_chapters(1)
    plan = _make_plan()
    writer = FakeWriterFactory()  # usage_metadata=None（旧形态）
    drafts = FakeDraftService()
    llm = FakeDecisionLLM(  # usage_metadata=None（旧形态）
        [
            _gotos("write_chapter", chapters[0]["outline_id"]),
            _gotos("audit_chapter", chapters[0]["outline_id"]),
            _gotos("mark_done", chapters[0]["outline_id"]),
            '{"action": "finish"}',
        ]
    )
    pipeline = BookAgenticPipeline(
        llm, writer_factory=writer, draft_service=drafts, audit_callable=llm.chat
    )
    result = await pipeline.execute(plan, chapters, BookLimits(max_chapters=5, max_agent_calls=50))
    assert result["status"] == "completed"

    state = await pipeline.get_checkpoint_state(result["run_id"])
    assert state is not None
    assert state.get("progress", {}).get(str(chapters[0]["outline_id"])) == "done"
    events = state.get("usage", [])
    assert all(e.get("total_tokens", 0) == 0 for e in events), "无 usage fake 不得产生计费事件"
