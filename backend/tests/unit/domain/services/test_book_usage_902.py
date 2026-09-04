"""#902 RED 契约 F4：服务层收尾/记账（BookService + BookRunMixin）usage 覆盖派生。

权威来源：.hermes/plans/contract-902.md §1.4/§1.5/§1.6 + §3 F4。

收尾语义（§1.4，_finalize_from_state facts 非 None 分支内、progress 同步后）：
    events = state.get("usage")
    if isinstance(events, list) and events:
        plan.limits["tokens_used"] = sum(total_tokens)      # 覆盖，非累加
        plan.limits["prompt_tokens"] = sum(prompt_tokens)
        plan.limits["completion_tokens"] = sum(completion_tokens)
        plan.limits["tokens_warning"] = total > max_tokens
    # 无 usage 键/空列表 → 三键不写（旧 checkpoint 向后兼容）
- 覆盖语义 = 幂等：同 state 收尾两次不重复计费【R C3】。
- counters 扩展（§1.5）：既有 7 键 + prompt_tokens/completion_tokens = 9 键。

数值核算（2 章 × {total:100, prompt:60, completion:40}）：
    tokens_used=200 / prompt_tokens=120 / completion_tokens=80 / tokens_warning=False
    （max_tokens=50 变体 → tokens_warning=True 且 status 仍 completed——软护栏不终止）

用例标注：
- 【R】当前 _finalize_from_state「token 记账不动」→ tokens_used 恒 0 /
  prompt_tokens 键不存在 → FAILED（修复锚）。
- 【G】旧 checkpoint 无 usage 键 → tokens_used 维持原值（RED 期 PASS 刻意）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService

_USAGE = {"prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100}

_COUNTERS_9_KEYS = {
    "max_chapters",
    "max_agent_calls",
    "max_tokens",
    "tokens_used",
    "tokens_warning",
    "agent_calls",
    "chapters_written",
    "prompt_tokens",
    "completion_tokens",
}


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _plan(**overrides) -> WritingPlan:
    base = dict(
        id=uuid.uuid4(),
        project_id=_pid(),
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
    base.update(overrides)
    return WritingPlan(**base)


def _outline(plan: WritingPlan, sort_order: int) -> Outline:
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


def _usage_agent() -> AsyncMock:
    """委托 fake：invoke 结果 messages 带 usage_metadata（repro_902 形态 100/60/40）。"""
    agent = AsyncMock()
    agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="本章正文内容……", usage_metadata=dict(_USAGE))]
    }
    return agent


def _usage_events(*, n: int = 2, chapter: str = "c") -> list[dict]:
    """n 个 write 事件（每事件 100/60/40）；收尾核算 = tokens_used 200/120/80。"""
    return [
        {
            "source": "write",
            "chapter": f"{chapter}{i}",
            "prompt_tokens": 60,
            "completion_tokens": 40,
            "total_tokens": 100,
        }
        for i in range(n)
    ]


def _make_repo_outline(plan: WritingPlan, chapters: list[Outline]) -> tuple[AsyncMock, AsyncMock]:
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = (chapters, len(chapters))
    return repo, outline_repo


class _PlainVolumePipeline:
    """volume 轨双鸭子：execute 返回 completed + get_checkpoint_state 固定 state。"""

    def __init__(self, state: dict | None = None) -> None:
        self._state = state or {"results": {}, "finished": True}

    async def execute(self, plan, volumes, limits, *, thread_id=None):
        return {"run_id": str(plan.id), "status": "completed", "thread_id": thread_id or "t"}

    async def resume(self, interrupt_obj, *, approved=True, decision="", thread_id=""):
        return {"run_id": thread_id, "status": "completed", "thread_id": thread_id}

    async def get_checkpoint_state(self, run_id):
        return dict(self._state)


class _SeqVolumePipeline:
    """resume_run 序贯鸭子：第 1 读=动作前快照（interrupt 判定），第 2 读=动作后事实源。"""

    def __init__(self, pre_state: dict, post_state: dict) -> None:
        self._states = [pre_state, post_state]
        self._i = 0

    async def get_checkpoint_state(self, run_id):
        state = self._states[min(self._i, len(self._states) - 1)]
        self._i += 1
        return state

    async def resume(self, interrupt_obj, *, approved=True, decision="", thread_id=""):
        return {"run_id": thread_id, "status": "completed", "thread_id": thread_id}

    async def execute(self, plan, volumes, limits, *, thread_id=None):
        return {"run_id": str(plan.id), "status": "completed", "thread_id": thread_id or "t"}


class _AgenticUsagePipeline:
    """agentic 轨双鸭子：execute completed + checkpoint progress done + usage 事件。"""

    def __init__(self, state: dict) -> None:
        self._state = state

    async def execute(self, plan, chapters, limits, *, config=None, thread_id=None):
        return {
            "run_id": str(plan.id),
            "status": "completed",
            "thread_id": thread_id or str(plan.id),
        }

    async def get_checkpoint_state(self, run_id):
        return dict(self._state)


async def _usage_writer_factory(**kwargs) -> AsyncMock:
    """恒成功带 usage 的 writer_factory（每调用新 agent）。"""
    return _usage_agent()


# ── R：volume 轨端到端（真实 pipeline）收尾记账 ──────────────────


async def test_volume_rail_end_to_end_tokens_and_counters() -> None:
    """【R】真实 BookVolumePipeline + BookService.write_book_volume（2 章 × usage
    100/60/40）→ plan.limits tokens_used==200/prompt_tokens==120/completion_tokens==80；
    get_status counters 9 键精确集且含新值；status completed。

    RED 形态：当前收尾「token 记账不动」→ tokens_used 恒 0 → AssertionError。
    """
    from langgraph.checkpoint.memory import InMemorySaver

    from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline

    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    repo, outline_repo = _make_repo_outline(plan, chapters)
    drafts = AsyncMock()
    drafts.create.return_value = SimpleNamespace(id="draft-v")
    pipeline = BookVolumePipeline(
        AsyncMock(),
        writer_factory=_usage_writer_factory,
        draft_service=drafts,
        checkpointer=InMemorySaver(),
    )
    svc = BookService(
        repo=repo,
        writer_factory=_usage_writer_factory,
        draft_service=drafts,
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        volume_pipeline=pipeline,
    )

    result = await svc.write_book_volume(plan.id, limits=BookLimits())

    assert result["status"] == "completed"
    assert plan.status == "completed"
    # §1.4 覆盖派生：checkpoint usage 事件全量求和
    assert plan.limits["tokens_used"] == 200, "volume 轨必须收尾记账（当前恒 0 = 缺陷锚）"
    assert plan.limits["prompt_tokens"] == 120
    assert plan.limits["completion_tokens"] == 80
    assert plan.limits["tokens_warning"] is False
    # counters 9 键（§1.5 契约升级）含新值
    status = await svc.get_status(str(plan.id))
    assert status is not None
    counters = status["counters"]
    assert set(counters.keys()) == _COUNTERS_9_KEYS
    assert counters["tokens_used"] == 200
    assert counters["prompt_tokens"] == 120
    assert counters["completion_tokens"] == 80
    assert counters["tokens_warning"] is False


async def test_volume_rail_soft_guardrail_warns_not_aborts() -> None:
    """【R】软护栏：max_tokens=50 < 实际 200 → 完成后 tokens_warning is True 且
    status 仍 completed（超限仅告警不终止，硬护栏行为零变化）。

    RED 形态：当前 tokens 恒 0 → warning False → AssertionError。
    """
    from langgraph.checkpoint.memory import InMemorySaver

    from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline

    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    repo, outline_repo = _make_repo_outline(plan, chapters)
    drafts = AsyncMock()
    drafts.create.return_value = SimpleNamespace(id="draft-v")
    pipeline = BookVolumePipeline(
        AsyncMock(),
        writer_factory=_usage_writer_factory,
        draft_service=drafts,
        checkpointer=InMemorySaver(),
    )
    svc = BookService(
        repo=repo,
        writer_factory=_usage_writer_factory,
        draft_service=drafts,
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        volume_pipeline=pipeline,
    )

    result = await svc.write_book_volume(plan.id, limits=BookLimits(max_tokens=50))

    assert result["status"] == "completed", "软护栏超限不得终止运行"
    assert plan.status == "completed"
    assert plan.limits["tokens_used"] == 200
    assert plan.limits["tokens_warning"] is True
    status = await svc.get_status(str(plan.id))
    assert status is not None
    assert status["counters"]["tokens_warning"] is True


# ── R：agentic 轨收尾记账 ────────────────────────────────────────


async def test_agentic_rail_tokens_override_from_checkpoint_usage() -> None:
    """【R】fake agentic pipeline：execute completed + get_checkpoint_state 返回
    progress 全 done + usage 2 事件 → write_book_agentic → plan.limits 三键覆盖
    200/120/80。

    RED 形态：当前收尾不读 usage → tokens_used 恒 0 → AssertionError。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    repo, outline_repo = _make_repo_outline(plan, chapters)
    state = {
        "progress": {str(c.id): "done" for c in chapters},
        "usage": _usage_events(chapter="ag"),
        "finished": True,
    }
    pipeline = _AgenticUsagePipeline(state)
    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        agentic_pipeline=pipeline,
    )

    result = await svc.write_book_agentic(plan.id, limits=BookLimits())

    assert result["status"] == "completed"
    assert plan.limits["tokens_used"] == 200, "agentic 轨必须收尾记账（当前恒 0 = 缺陷锚）"
    assert plan.limits["prompt_tokens"] == 120
    assert plan.limits["completion_tokens"] == 80
    assert plan.limits["tokens_warning"] is False


# ── R：幂等（同 state 收尾两次不翻倍）────────────────────────────


async def test_finalize_from_state_idempotent_no_double_count() -> None:
    """【R】§1.4 覆盖语义：_finalize_from_state 同 state 连续两次调用 →
    tokens_used 恒 200（覆盖非累加，绝不 400）；prompt/completion 同。

    RED 形态：当前不记账 → tokens_used 0 → AssertionError。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    results = {str(c.id): f"draft-{i}" for i, c in enumerate(chapters)}
    state = {"results": results, "usage": _usage_events(), "finished": True}
    svc = BookService(
        repo=AsyncMock(),
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=AsyncMock(),
        limits=STAGE1_LIMITS,
    )

    first = svc._finalize_from_state(plan, state, "凭据无效或运行时错误")
    second = svc._finalize_from_state(plan, state, "凭据无效或运行时错误")

    assert first == "completed"
    assert second == "completed"
    assert plan.limits["tokens_used"] == 200, "收尾必须幂等（覆盖非累加，防 confirm→resume 链翻倍）"
    assert plan.limits["prompt_tokens"] == 120
    assert plan.limits["completion_tokens"] == 80


# ── R：跨重启 resume_run 计数 = checkpoint 全量覆盖 ──────────────


async def test_resume_run_cross_restart_usage_override() -> None:
    """【R】resume_run（fake checkpoint 含 usage；interrupt 续跑 completed）→
    计数 = checkpoint 全量覆盖（200/120/80），动作后 fresh 事实源生效。

    RED 形态：当前收尾不读 usage → tokens_used 恒 0 → AssertionError。
    """
    plan = _plan(status="paused", thread_id="t-902-resume")
    chapters = [_outline(plan, i) for i in range(2)]
    results = {str(c.id): f"draft-{i}" for i, c in enumerate(chapters)}
    pipeline = _SeqVolumePipeline(
        pre_state={"__interrupt__": [SimpleNamespace(value={"volume_index": 1})]},
        post_state={"results": results, "usage": _usage_events(chapter="rs"), "finished": True},
    )
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = (chapters, len(chapters))
    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        volume_pipeline=pipeline,
    )

    result = await svc.resume_run(str(plan.id))

    assert result["status"] == "completed"
    assert plan.status == "completed"
    assert plan.limits["tokens_used"] == 200, "跨重启计数必须 = checkpoint 全量（当前恒 0）"
    assert plan.limits["prompt_tokens"] == 120
    assert plan.limits["completion_tokens"] == 80


# ── R：static 轨 prompt/completion 分列 ──────────────────────────


async def test_static_rail_prompt_completion_split() -> None:
    """【R】§1.6 static 轨分列：write_book 2 章 × usage 100/60/40 →
    tokens_used==200（既有累计语义不变）+ prompt_tokens==120/completion_tokens==80
    分列累计；warning False。

    RED 形态：当前 _delegate_chapter 只累计 total → plan.limits["prompt_tokens"]
    KeyError → FAILED。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    repo, outline_repo = _make_repo_outline(plan, chapters)
    drafts = AsyncMock()
    drafts.create.return_value = SimpleNamespace(id="draft-s")
    svc = BookService(
        repo=repo,
        writer_factory=_usage_writer_factory,
        draft_service=drafts,
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
    )

    result = await svc.write_book(plan.id, limits=BookLimits())

    assert result["status"] == "completed"
    assert plan.limits["tokens_used"] == 200
    assert plan.limits["prompt_tokens"] == 120, "static 轨必须分列累计 prompt_tokens"
    assert plan.limits["completion_tokens"] == 80, "static 轨必须分列累计 completion_tokens"
    assert plan.limits["tokens_warning"] is False


# ── G：旧 checkpoint 无 usage 键 → 计数维持原值 ──────────────────


async def test_old_checkpoint_without_usage_preserves_counters() -> None:
    """【G】旧 checkpoint（无 usage 键）→ 三键不写：tokens_used 维持原值 77、
    prompt_tokens/completion_tokens 键不出现、status completed（既有 fake
    pipeline 用例零翻转背书）。

    守护用例 RED 期 PASS 刻意（当前实现本就不碰 token 记账）。
    """
    plan = _plan()
    plan.limits["tokens_used"] = 77
    chapters = [_outline(plan, i) for i in range(2)]
    results = {str(c.id): f"draft-{i}" for i, c in enumerate(chapters)}
    pipeline = _PlainVolumePipeline({"results": results, "finished": True})  # 无 usage 键
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = (chapters, len(chapters))
    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        volume_pipeline=pipeline,
    )

    result = await svc.write_book_volume(plan.id, limits=BookLimits())

    assert result["status"] == "completed"
    assert plan.limits["tokens_used"] == 77, "旧 checkpoint 无 usage → 既有计数不得被清/改"
    assert "prompt_tokens" not in plan.limits
    assert "completion_tokens" not in plan.limits


# ── R：volume 轨 waiting_hitl 落点同步（契约 §1.4 落点 1）────────────


class _HitlUsageVolumePipeline:
    """write_book_volume 卷边界鸭子：execute 抛 VolumeHITLInterrupt（第一卷完成即
    暂停，多卷书 GUI 主路径），get_checkpoint_state 返回含 usage 事件 state。"""

    def __init__(self, state: dict) -> None:
        self._state = state

    async def execute(self, plan, volumes, limits, *, thread_id=None):
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        raise VolumeHITLInterrupt(
            {"question": "确认继续下一卷？", "volume_index": 0, "progress": {}}
        )

    async def resume(self, interrupt_obj, *, approved=True, decision="", thread_id=""):
        return {"run_id": thread_id, "status": "completed", "thread_id": thread_id}

    async def get_checkpoint_state(self, run_id):
        return dict(self._state)


class _ResumeHitlUsagePipeline:
    """confirm_run 再中断鸭子：resume 抛 VolumeHITLInterrupt（下一卷边界），
    get_checkpoint_state 含 usage 事件。"""

    def __init__(self, state: dict) -> None:
        self._state = state

    async def execute(self, plan, volumes, limits, *, thread_id=None):
        return {"run_id": str(plan.id), "status": "completed", "thread_id": thread_id or "t"}

    async def resume(self, interrupt_obj, *, approved=True, decision="", thread_id=""):
        from inkflow.infrastructure.agent.book_pipeline import VolumeHITLInterrupt

        raise VolumeHITLInterrupt(
            {"question": "确认继续下一卷？", "volume_index": 1, "progress": {}}
        )

    async def get_checkpoint_state(self, run_id):
        return dict(self._state)


async def test_volume_rail_waiting_hitl_syncs_usage() -> None:
    """【R】§1.4 落点 1：write_book_volume 卷边界中断 → 返回 waiting_hitl 时
    plan.limits 已同步 checkpoint usage（200/120/80）。

    RED 形态：当前 except VolumeHITLInterrupt 分支只存 payload 不同步 → tokens_used 恒 0。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    repo, outline_repo = _make_repo_outline(plan, chapters)
    state = {
        "results": {str(c.id): f"draft-{i}" for i, c in enumerate(chapters)},
        "usage": _usage_events(chapter="hitl"),
        "finished": False,
        "volume_index": 0,
        "total_volumes": 2,
    }
    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        volume_pipeline=_HitlUsageVolumePipeline(state),
    )

    result = await svc.write_book_volume(plan.id, limits=BookLimits())

    assert result["status"] == "waiting_hitl"
    assert plan.status == "waiting_hitl"
    assert plan.limits["tokens_used"] == 200, "waiting_hitl 落点必须同步 usage（当前恒 0 = 缺陷锚）"
    assert plan.limits["prompt_tokens"] == 120
    assert plan.limits["completion_tokens"] == 80


async def test_confirm_run_second_interrupt_syncs_usage() -> None:
    """【R】§1.4 落点 1（confirm_run 再中断）：resume 再抛 VolumeHITLInterrupt →
    waiting_hitl 落库前同步 usage（覆盖语义，前值被吞并不翻倍）。

    RED 形态：当前 confirm_run except 分支不同步 → tokens_used 恒 0。
    """
    plan = _plan(status="waiting_hitl")
    plan.hitl_payload = {"question": "确认继续下一卷？"}
    plan.limits["tokens_used"] = 50  # 前一次 waiting_hitl 的部分值——覆盖语义下被 200 吞并
    state = {
        "results": {"c1": "draft-1"},
        "usage": _usage_events(n=2, chapter="cf"),
        "finished": False,
        "volume_index": 1,
        "total_volumes": 3,
    }
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=AsyncMock(),
        limits=STAGE1_LIMITS,
        volume_pipeline=_ResumeHitlUsagePipeline(state),
    )

    result = await svc.confirm_run(str(plan.id), approved=True)

    assert result["status"] == "waiting_hitl"
    assert plan.status == "waiting_hitl"
    assert plan.limits["tokens_used"] == 200, "再中断落点覆盖同步（50 → 200，非 250）"
    assert plan.limits["prompt_tokens"] == 120
    assert plan.limits["completion_tokens"] == 80
