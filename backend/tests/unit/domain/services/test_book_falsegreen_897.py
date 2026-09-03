"""#897 RED 契约：残留假绿——凭据存在但无效时章全 failed 仍顶层 completed。

缺陷根因（main 2610511 源码实证，issue #897）：
- 静态轨 book_service.write_book 章循环 except Exception → progress=failed 后，
  循环结束「无条件」plan.status="completed"（L213），异常原因丢弃（L208-209）
- volume/agentic 轨 execute/resume 返回后同样无条件 completed
- 三轨共同后果：全章 failed、tokens_used=0、顶层 completed（假绿），且 status
  不含失败原因（fire-and-forget 后台任务只能靠轮询发现，定位成本极高）

权威来源：specs/f44-book-orchestrator/spec.md §5.5（v1.3 完成态判据收紧 +
失败原因可见，#897 拍板）：

| 章级事实（plan.progress）                     | run 终态            |
|------------------------------------------------|---------------------|
| failed 章 > 0 且 done 章 == 0                  | failed              |
| failed 章 > 0 且 done 章 > 0                   | degraded（新增）    |
| failed 章 == 0（含无章级事实——旧 mock 兼容）   | completed           |

派生适用范围 = 一切「欲设 completed」的收尾点（write_book / write_book_volume /
confirm_run / resume_run / write_book_agentic）；aborted / waiting_hitl 不重派生。

章级事实来源（volume/agentic 轨）：服务层收尾时若 pipeline 鸭子提供
get_checkpoint_state（real pipeline / 新测试双鸭子）→ 读 checkpoint 的章事实
（volume = state["results"]，agentic = state["progress"]）同步回 plan.progress
后派生；鸭子无该方法或返回非 dict（AsyncMock 自动生成属性形态）→ 跳过派生维持
completed（向后兼容守护——阶段 3/4 既有 mock 用例零翻转）。

progress_reason（WritingPlan 新增顶层字段，先例 = hitl_payload）：failed/degraded
时可见——静态轨 = 委托失败异常摘要行（含 outline_id + 异常类名/消息）；volume/
agentic 轨 = failed 章列表 + 运行时错误提示。get_status / get_summary 顶层新增键
progress_reason（其余状态 null）。

【mock 策略】镜像 test_book_service.py/_make_deps 形态：repo/outline_repo AsyncMock；
writer_factory AsyncMock 包装 fake agent（invoke 抛 401 RuntimeError = 「凭据存在但
无效」的确定性等价注入）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService

_UNAUTHORIZED = "Error code: 401 - invalid API key"


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


def _ok_agent() -> AsyncMock:
    agent = AsyncMock()
    agent.invoke.return_value = {
        "messages": [
            SimpleNamespace(
                content="本章正文内容……",
                tool_calls=[],
                usage_metadata={"total_tokens": 100},
            )
        ]
    }
    return agent


def _401_agent() -> AsyncMock:
    agent = AsyncMock()
    agent.invoke.side_effect = RuntimeError(_UNAUTHORIZED)
    return agent


def _static_service(plan: WritingPlan, chapters: list[Outline], fail_idx: set[int]):
    """静态轨服务：fail_idx 之外的章成功，之内抛 401（凭据无效等价注入）。"""
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = (chapters, len(chapters))
    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")

    calls = {"n": 0}

    async def writer_factory(**kwargs):
        i = calls["n"]
        calls["n"] += 1
        return _401_agent() if i in fail_idx else _ok_agent()

    svc = BookService(
        repo=repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
    )
    return svc, repo


# ── 静态轨：完成态判据按章级事实派生（spec §5.5 表）────────────────


async def test_write_book_all_chapters_failed_not_completed():
    """全章 failed（凭据无效）→ result/plan.status = failed，绝不 completed。

    RED 形态：当前 L213 无条件 completed → AssertionError（假绿实证）。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(3)]
    svc, _ = _static_service(plan, chapters, fail_idx={0, 1, 2})

    result = await svc.write_book(plan.id, limits=BookLimits())

    assert result["status"] == "failed", (
        f"#897 假绿：全章 failed 顶层仍 {result['status']}"
    )
    assert plan.status == "failed"
    assert set(plan.progress.values()) == {"failed"}
    # 全失败零 token：委托未成功，execution_refs 为空
    assert plan.execution_refs == {}


async def test_write_book_partial_failure_degraded():
    """3 章中第 2 章 failed → 顶层 degraded（部分成功，不再掩蔽）。

    RED 形态：当前无条件 completed → AssertionError。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(3)]
    svc, _ = _static_service(plan, chapters, fail_idx={1})

    result = await svc.write_book(plan.id, limits=BookLimits())

    assert result["status"] == "degraded"
    assert plan.status == "degraded"
    assert plan.progress[str(chapters[0].id)] == "done"
    assert plan.progress[str(chapters[1].id)] == "failed"
    assert plan.progress[str(chapters[2].id)] == "done"


async def test_write_book_all_done_still_completed():
    """全章 done → completed 语义不变（判据收紧不误伤成功路径）。

    守护用例 RED 期 PASS 刻意（当前实现全成功即 completed）。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(3)]
    svc, _ = _static_service(plan, chapters, fail_idx=set())

    result = await svc.write_book(plan.id, limits=BookLimits())

    assert result["status"] == "completed"
    assert plan.status == "completed"
    assert all(v == "done" for v in plan.progress.values())
    assert plan.limits["tokens_used"] == 300


# ── progress_reason：失败原因落库可见（spec §5.5）─────────────────


async def test_get_status_exposes_progress_reason_with_exception():
    """静态轨失败 → get_status 顶层 progress_reason 含异常类名与消息。

    RED 形态：字段不存在（AttributeError/KeyError）→ FAILED。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    svc, _ = _static_service(plan, chapters, fail_idx={0, 1})

    await svc.write_book(plan.id, limits=BookLimits())
    status = await svc.get_status(str(plan.id))

    assert status is not None
    reason = status["progress_reason"]
    assert reason, "失败态 progress_reason 必须非空（原因可见）"
    assert "RuntimeError" in reason and _UNAUTHORIZED in reason
    # 定位锚点：failed 章的 outline_id 出现在原因中
    assert str(chapters[0].id) in reason


async def test_get_summary_exposes_same_progress_reason():
    """get_summary 与 get_status 同键同值（回归摘要一致性）。"""
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(1)]
    svc, _ = _static_service(plan, chapters, fail_idx={0})

    await svc.write_book(plan.id, limits=BookLimits())
    status = await svc.get_status(str(plan.id))
    summary = await svc.get_summary(str(plan.id))

    assert summary is not None
    assert summary["progress_reason"] == status["progress_reason"]


async def test_progress_reason_none_when_completed():
    """成功态 progress_reason 键存在且为 None（键恒在，值随状态）。"""
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    svc, _ = _static_service(plan, chapters, fail_idx=set())

    await svc.write_book(plan.id, limits=BookLimits())
    status = await svc.get_status(str(plan.id))

    assert status is not None
    assert "progress_reason" in status
    assert status["progress_reason"] is None


async def test_progress_reason_persisted_via_repo_update():
    """progress_reason 随 update_writing_plan 落库（收尾写回 plan 对象）。"""
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    svc, repo = _static_service(plan, chapters, fail_idx={0, 1})

    await svc.write_book(plan.id, limits=BookLimits())

    assert plan.progress_reason, "收尾时 progress_reason 必须写回 plan（供持久化）"
    repo.update_writing_plan.assert_awaited()


# ── volume 轨：服务层收尾派生（checkpoint 章事实同步）─────────────


class _VolumePipelineWithState:
    """volume 轨双鸭子：execute 返回 completed + 提供 get_checkpoint_state(results)。

    real BookVolumePipeline 语义镜像：results = {outline_id: execution_id|"failed"}。
    """

    def __init__(self, results: dict[str, str]) -> None:
        self._results = results
        self.resume_calls: list[tuple] = []

    async def execute(self, plan, volumes, limits, *, thread_id=None):
        return {"run_id": str(plan.id), "status": "completed", "thread_id": thread_id or "t"}

    async def resume(self, interrupt_obj, *, approved=True, decision="", thread_id=""):
        self.resume_calls.append((interrupt_obj, approved, decision, thread_id))
        return {"run_id": thread_id, "status": "completed", "thread_id": thread_id}

    async def get_checkpoint_state(self, run_id):
        return {"results": dict(self._results), "finished": True}


async def _volume_service(plan: WritingPlan, pipeline, chapters: list[Outline]):
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
    return svc, repo


async def test_write_book_volume_all_failed_maps_failed():
    """volume 轨 checkpoint 全章 failed → 顶层 failed（不再 completed）。

    RED 形态：当前无条件 completed 且不读 checkpoint → AssertionError。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    results = {str(c.id): "failed" for c in chapters}
    pipeline = _VolumePipelineWithState(results)
    svc, _ = await _volume_service(plan, pipeline, chapters)

    result = await svc.write_book_volume(plan.id, limits=BookLimits())

    assert result["status"] == "failed"
    assert plan.status == "failed"
    assert plan.progress == {oid: "failed" for oid in results}
    assert plan.progress_reason


async def test_write_book_volume_partial_failure_degraded():
    """volume 轨 checkpoint 部分 failed → degraded + progress 同步 + 原因含 failed 章。"""
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(3)]
    results = {
        str(chapters[0].id): "draft-1",
        str(chapters[1].id): "failed",
        str(chapters[2].id): "draft-1",
    }
    pipeline = _VolumePipelineWithState(results)
    svc, _ = await _volume_service(plan, pipeline, chapters)

    result = await svc.write_book_volume(plan.id, limits=BookLimits())

    assert result["status"] == "degraded"
    assert plan.status == "degraded"
    assert plan.progress[str(chapters[1].id)] == "failed"
    assert str(chapters[1].id) in plan.progress_reason


async def test_write_book_volume_success_syncs_progress_completed():
    """volume 轨 checkpoint 全 done → completed + progress/execution_refs 同步回 plan。

    同步契约：real pipeline 此前从不回写 plan.progress（get_status 空进度双重掩蔽），
    服务层收尾从 checkpoint 补同步——成功路径也须可见章级事实。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    results = {str(c.id): "draft-1" for c in chapters}
    pipeline = _VolumePipelineWithState(results)
    svc, _ = await _volume_service(plan, pipeline, chapters)

    result = await svc.write_book_volume(plan.id, limits=BookLimits())

    assert result["status"] == "completed"
    assert len(plan.progress) == 2, "checkpoint 章事实必须同步回 plan.progress"
    assert all(v == "done" for v in plan.progress.values())
    assert len(plan.execution_refs) == 2
    assert set(plan.execution_refs.values()) == {"draft-1"}
    assert plan.progress_reason is None


async def test_confirm_run_all_failed_maps_failed():
    """confirm_run resume 正常返回 + checkpoint 全 failed → failed（收尾点全覆盖）。"""
    plan = _plan(status="waiting_hitl", thread_id="t-897")
    plan.hitl_payload = {"question": "卷执行失败，如何继续？", "failed": []}
    chapters = [_outline(plan, i) for i in range(2)]
    results = {str(c.id): "failed" for c in chapters}
    pipeline = _VolumePipelineWithState(results)
    svc, _ = await _volume_service(plan, pipeline, chapters)

    result = await svc.confirm_run(str(plan.id), approved=True, decision="continue")

    assert result["status"] == "failed"
    assert plan.status == "failed"


# ── agentic 轨：服务层收尾派生（state["progress"] 事实）───────────


async def test_write_book_agentic_all_failed_maps_failed():
    """agentic 轨 execute 返回 completed 但 checkpoint progress 全 failed → failed。

    RED 形态：当前无条件写 result.status → AssertionError。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = (chapters, len(chapters))
    pipeline = AsyncMock()
    pipeline.execute.return_value = {
        "run_id": str(plan.id),
        "status": "completed",
        "thread_id": str(plan.id),
    }
    pipeline.get_checkpoint_state.return_value = {
        "progress": {str(c.id): "failed" for c in chapters},
        "finished": True,
    }
    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        agentic_pipeline=pipeline,
    )

    result = await svc.write_book_agentic(plan.id, limits=BookLimits())

    assert result["status"] == "failed"
    assert plan.status == "failed"
    assert plan.progress == {str(c.id): "failed" for c in chapters}
    assert plan.progress_reason


async def test_write_book_agentic_partial_failure_degraded():
    """agentic 轨混合（1 done 1 failed）→ degraded。"""
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = (chapters, len(chapters))
    pipeline = AsyncMock()
    pipeline.execute.return_value = {
        "run_id": str(plan.id),
        "status": "completed",
        "thread_id": str(plan.id),
    }
    pipeline.get_checkpoint_state.return_value = {
        "progress": {str(chapters[0].id): "done", str(chapters[1].id): "failed"},
        "finished": True,
    }
    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        agentic_pipeline=pipeline,
    )

    result = await svc.write_book_agentic(plan.id, limits=BookLimits())

    assert result["status"] == "degraded"
    assert plan.status == "degraded"


async def test_write_book_agentic_checkpoint_missing_keeps_completed():
    """向后兼容守护：旧鸭子无 get_checkpoint_state（裸类无方法/非 dict 返回）→
    跳过派生维持 completed（阶段 4 既有 mock 用例零翻转的契约背书）。

    守护用例 RED 期 PASS 刻意。
    """
    plan = _plan()
    chapters = [_outline(plan, i) for i in range(2)]
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = (chapters, len(chapters))

    class _LegacyPipeline:  # 阶段 4 旧形态：无 get_checkpoint_state
        async def execute(self, plan, chapters, limits, *, config=None, thread_id=None):
            return {"run_id": str(plan.id), "status": "completed", "thread_id": "t"}

    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
        agentic_pipeline=_LegacyPipeline(),
    )

    result = await svc.write_book_agentic(plan.id, limits=BookLimits())

    assert result["status"] == "completed"


# ── progress_reason 持久化链路（domain/ORM/repo/迁移，先例=hitl_payload）──

_OLD_WRITING_PLAN_SCHEMA = """
CREATE TABLE writing_plans (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    project_id VARCHAR(36) NOT NULL,
    title VARCHAR(200) NOT NULL,
    status VARCHAR(30) NOT NULL,
    root_outline_id VARCHAR(36),
    character_ids JSON NOT NULL,
    limits JSON NOT NULL,
    progress JSON NOT NULL,
    execution_refs JSON NOT NULL,
    thread_id VARCHAR(64),
    hitl_payload JSON,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""


def test_writing_plan_domain_has_progress_reason():
    """WritingPlan 领域模型新增顶层字段 progress_reason（默认 None，可空 str）。"""
    plan = _plan()
    assert plan.progress_reason is None
    assert _plan(progress_reason="boom").progress_reason == "boom"


def test_writing_plan_orm_progress_reason_column():
    """ORM 列定义：String(2000) nullable（上限对齐长文本诊断摘要，勿超 2000 截断契约）。"""
    from sqlalchemy import String

    from inkflow.infrastructure.database.models.writing_plan import WritingPlanORM

    col = WritingPlanORM.__table__.columns["progress_reason"]
    assert isinstance(col.type, String)
    assert col.type.length == 2000
    assert col.nullable is True


def test_migration_old_db_gets_progress_reason_column(tmp_path):
    """旧库（无列）→ ensure 补列，幂等可重跑。"""
    from sqlalchemy import create_engine, text

    # 惰性 import：RED 时函数不存在 → ImportError（FAILED 非收集期错误）
    from inkflow.core.database import ensure_writing_plan_progress_reason_column

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text(_OLD_WRITING_PLAN_SCHEMA))
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(writing_plans)"))}
        assert "progress_reason" not in cols
        ensure_writing_plan_progress_reason_column(conn)
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(writing_plans)"))}
        assert "progress_reason" in cols
        ensure_writing_plan_progress_reason_column(conn)  # 幂等
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(writing_plans)"))}
        assert "progress_reason" in cols
    engine.dispose()


def test_migration_new_db_and_missing_table_noop(tmp_path):
    """新库（create_all 已含列）→ no-op；表不存在（全新环境）→ no-op 不抛。"""
    from sqlalchemy import create_engine, text

    from inkflow.core.database import ensure_writing_plan_progress_reason_column

    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with engine.connect() as conn:
        ensure_writing_plan_progress_reason_column(conn)
        tables = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
        assert tables == []

    engine2 = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    import inkflow.infrastructure.database.models.writing_plan  # noqa: F401  # 注册 ORM
    from inkflow.core.database import Base

    Base.metadata.create_all(engine2)
    with engine2.connect() as conn:
        before = {r[1] for r in conn.execute(text("PRAGMA table_info(writing_plans)"))}
        ensure_writing_plan_progress_reason_column(conn)
        after = {r[1] for r in conn.execute(text("PRAGMA table_info(writing_plans)"))}
        assert before == after
        assert "progress_reason" in after
    engine2.dispose()
    engine.dispose()


# ── 审查（#897 request-changes）派生：resume_run fresh-read + 原因门控/前缀 ──


class _ResumePipeline:
    """resume 轨序贯鸭子：第 1 读=动作前快照（interrupt 判定用），第 2 读=动作后
    fresh 事实源（spec §5.5 v1.3 澄清：动作前快照不得复用为事实源）。"""

    def __init__(self, pre_state: dict, post_state: dict) -> None:
        self._states = [pre_state, post_state]
        self._i = 0

    async def get_checkpoint_state(self, thread_id):
        state = self._states[min(self._i, len(self._states) - 1)]
        self._i += 1
        return state

    async def resume(self, interrupt_obj, *, approved=True, decision="", thread_id=""):
        return {"run_id": thread_id, "status": "completed", "thread_id": thread_id}

    async def execute(self, plan, volumes, limits, *, thread_id=None):
        return {
            "run_id": str(plan.id),
            "status": "completed",
            "thread_id": thread_id or "t",
        }


async def test_resume_run_interrupt_branch_fresh_read_maps_failed():
    """MAJOR 回归：interrupt 分支续跑段全 failed → failed。

    动作前快照仅 __interrupt__ 键（无章事实），复用为事实源 = 假绿残留；
    修复 = resume 完成后重读 checkpoint（fresh）取 results 再派生。
    RED 形态：当前实现复用 pre-state → facts None → completed → AssertionError。
    """
    plan = _plan(status="paused", thread_id="t-resume-897")
    chapters = [_outline(plan, i) for i in range(2)]
    results = {str(c.id): "failed" for c in chapters}
    pipeline = _ResumePipeline(
        pre_state={"__interrupt__": [SimpleNamespace(value={"volume_index": 1})]},
        post_state={"results": results, "finished": True},
    )
    svc, _ = await _volume_service(plan, pipeline, chapters)

    result = await svc.resume_run(str(plan.id))

    assert result["status"] == "failed", (
        f"#897 假绿残留：resume 续跑段全 failed 顶层仍 {result['status']}"
    )
    assert plan.status == "failed"
    assert plan.progress == {oid: "failed" for oid in results}
    assert plan.progress_reason


async def test_resume_run_no_interrupt_branch_fresh_read_maps_degraded():
    """MAJOR 回归：cancel 续跑（无 interrupt 重新 execute）段部分 failed → degraded。"""
    plan = _plan(status="paused", thread_id="t-resume-897b")
    chapters = [_outline(plan, i) for i in range(3)]
    results = {
        str(chapters[0].id): "draft-a",
        str(chapters[1].id): "failed",
        str(chapters[2].id): "draft-b",
    }
    pipeline = _ResumePipeline(
        pre_state={"volume_index": 1, "total_volumes": 2, "status": "running"},
        post_state={"results": results, "finished": True},
    )
    svc, _ = await _volume_service(plan, pipeline, chapters)

    result = await svc.resume_run(str(plan.id))

    assert result["status"] == "degraded"
    assert plan.status == "degraded"
    assert plan.progress[str(chapters[1].id)] == "failed"
    assert plan.execution_refs[str(chapters[0].id)] == "draft-a"
    assert str(chapters[1].id) in plan.progress_reason


async def test_progress_reason_gated_outside_failed_states():
    """MINOR 回归（审查 #2）：非 failed/degraded 态 get_status/get_summary 门控
    progress_reason=null——中间态（waiting_hitl）不显示陈旧原因。"""
    plan = _plan(status="waiting_hitl", progress_reason="stale from earlier run")
    plan.hitl_payload = {"question": "卷边界确认？", "volume_index": 1}
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=AsyncMock(),
        limits=STAGE1_LIMITS,
    )

    status = await svc.get_status(str(plan.id))
    assert status["progress_reason"] is None, "waiting_hitl 态不得透出陈旧 progress_reason"
    summary = await svc.get_summary(str(plan.id))
    assert summary["progress_reason"] is None


async def test_mark_failed_clears_stale_progress_reason():
    """MINOR 回归（审查 #2）：mark_failed（整单异常兜底）清空 progress_reason。"""
    plan = _plan(status="running", progress_reason="stale")
    repo = AsyncMock()
    repo.get_writing_plan.return_value = plan
    svc = BookService(
        repo=repo,
        writer_factory=AsyncMock(),
        draft_service=AsyncMock(),
        outline_repo=AsyncMock(),
        limits=STAGE1_LIMITS,
    )

    result = await svc.mark_failed(str(plan.id))

    assert result["status"] == "failed"
    assert plan.progress_reason is None, "mark_failed 无章级原因语义，陈旧值必须清空"


async def test_static_reason_line_has_single_outline_prefix():
    """NIT 回归（审查 #3）：静态轨原因行单前缀「outline_id: 类名: 消息」不重复。"""
    plan = _plan()
    chapters = [_outline(plan, 0)]
    svc, _ = _static_service(plan, chapters, fail_idx={0})

    await svc.write_book(plan.id, limits=BookLimits())

    oid = str(chapters[0].id)
    reason = plan.progress_reason
    assert reason
    assert reason.count(oid) == 1, f"outline_id 双前缀（审查 NIT #3）: {reason!r}"
    assert reason.startswith(f"{oid}: RuntimeError")


async def test_book_repository_roundtrip_persists_progress_reason():
    """SQLiteBookRepository add/update/get 全链路往返 progress_reason（零加工透传）。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import inkflow.infrastructure.database.models.writing_plan  # noqa: F401  # 注册 ORM
    from inkflow.core.database import Base
    from inkflow.infrastructure.repositories.book_repository import SQLiteBookRepository

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        repo = SQLiteBookRepository(session)
        plan = _plan(progress_reason="initial reason")
        added = await repo.add_writing_plan(plan)
        assert added.progress_reason == "initial reason"

        fetched = await repo.get_writing_plan(plan.id)
        assert fetched is not None
        assert fetched.progress_reason == "initial reason"

        fetched.progress_reason = "boom: RuntimeError"
        fetched.status = "failed"
        await repo.update_writing_plan(fetched)
        again = await repo.get_writing_plan(plan.id)
        assert again is not None
        assert again.progress_reason == "boom: RuntimeError"
        assert again.status == "failed"
    await engine.dispose()
