"""F44 阶段4 后台任务 BookService 契约单测（TDD RED 阶段，契约先行）。

权威来源：fix-010-bug-batch 实施计划任务 2 §B（#456 第一部分：F44 阶段4
FastAPI 后台任务——POST /runs 由同步执行改为 asyncio 后台任务）。
本文件为 `domain/services/book_service.py` 的两个新方法定义契约：
- prepare_run(plan_id, limits=None, mode="static")：启动前准备（校验/安全阀/
  状态落库），由端点同步调用后决定是否 spawn 后台任务。
- mark_failed(run_id)：后台任务失败收尾（状态置 failed 落库）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【prepare_run 签名】async def prepare_run(self, plan_id: uuid.UUID,
   limits: BookLimits | None = None, mode: str = "static") -> dict：
   a. plan 不存在 → ValueError("计划不存在")（API 映射 404）。
   b. merge_book_limits + validate_at_least_one_hard_limit——全无护栏
      → ValueError("至少一道有限护栏...")（422 语义）。
   c. 生效上限写回 plan.limits（max_chapters / max_agent_calls /
      max_tokens / max_sessions，不覆盖 tokens_* 运行计数）。
   d. mode="static"：_find_chapters + 每章内容安全阀（_check_content_written）
      ——已有内容 → ChapterAlreadyWrittenError("该章已有内容，拒绝重跑")。
   e. mode="volume"：_find_volumes 拆卷 + 卷内每章安全阀
      （_check_chapter_written）——命中 → ChapterAlreadyWrittenError；
      volume_pipeline 未装配（None）不报错——prepare_run 只拆卷+安全阀，
      不调 pipeline。
   f. 无章节点 → plan.status="completed" + 落库 → 返回
      {"run_id": str(plan.id), "status": "completed"}（快路径，不启任务；
      spawn 是端点层职责——completed 语义 = 端点不 spawn）。
   g. 有章节点 → plan.status="running" + 落库 → 返回
      {"run_id": str(plan.id), "status": "running"}。
   h. 重复提交守卫：plan.status == "running" → ValueError("运行已在进行中")
      （双跑防护，422；守卫须先于无章快路径——test 7 用空大纲构造锁定位）。

2. 【mark_failed 签名】async def mark_failed(self, run_id: str) -> dict：
   a. plan 不存在 → ValueError("运行不存在")（API 映射 404）。
   b. 存在 → plan.status="failed" + 落库 → 返回
      {"run_id": str(plan.id), "status": "failed"}。

【mock 策略】镜像 test_book_service.py：repo/outline_repo/content_checker
全 AsyncMock（get_writing_plan 返回 plan / update_writing_plan 返回 None /
outline_repo.list 返回 ([Outline], total) / content_checker 是 async 函数）；
volume 模式 volume_pipeline 缺省 None（契约 1e：prepare_run 不调 pipeline）。

【RED 预期形态】全部 9 用例 FAILED，0 passed：BookService 当前无
prepare_run/mark_failed 方法 → 用例体 `svc.prepare_run(...)` 属性访问抛
AttributeError（用例体异常 = FAILED 非 ERROR；无收集/setup 错误）。
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService, ChapterAlreadyWrittenError


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _plan(**overrides) -> WritingPlan:
    base = dict(
        id=uuid.uuid4(),
        project_id=_pid(),
        title="测试计划",
        status="ready",
        root_outline_id=uuid.uuid4(),
        character_ids=[],
        limits={"max_chapters": 1, "max_agent_calls": 1},
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return WritingPlan(**base)


def _outline(**overrides) -> Outline:
    base = dict(
        id=uuid.uuid4(),
        project_id=_pid(),
        name="第一章",
        description="主角在时间旅途中发现悖论",
        sort_order=0,
        level="chapter",
        parent_id=None,
        chapter_id=None,
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return Outline(**base)


def _make_deps(**overrides):
    """构造 BookService 全部 mock 依赖（镜像 test_book_service.py；可覆盖）。"""
    repo = AsyncMock()
    repo.get_writing_plan.return_value = None
    repo.update_writing_plan.return_value = None

    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="第一章正文内容", tool_calls=[])]
    }
    writer_factory = AsyncMock(return_value=fake_agent)

    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")

    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([], 0)

    deps = dict(
        repo=repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
        outline_repo=outline_repo,
        limits=STAGE1_LIMITS,
    )
    deps.update(overrides)
    return deps


def _service(**overrides) -> BookService:
    return BookService(**_make_deps(**overrides))


# ── prepare_run：plan 缺失 / 护栏（契约 1a/1b）─────────────────────


@pytest.mark.asyncio
async def test_prepare_run_plan_missing_raises():
    """契约 1a：plan 不存在 → ValueError("计划不存在")（API 映射 404）。"""
    svc = _service()
    with pytest.raises(ValueError, match="计划不存在"):
        await svc.prepare_run(uuid.uuid4())


@pytest.mark.asyncio
async def test_prepare_run_rejects_no_hard_limit():
    """契约 1b：全无护栏 → ValueError（「至少一道有限护栏」不变式，422 语义）。"""
    repo = AsyncMock()
    repo.get_writing_plan.return_value = _plan()
    svc = _service(repo=repo)

    with pytest.raises(ValueError, match="至少一道"):
        await svc.prepare_run(uuid.uuid4(), limits=BookLimits(max_chapters=0, max_agent_calls=0))


# ── prepare_run：running / completed / 守卫（契约 1c/1f/1g/1h）──────


@pytest.mark.asyncio
async def test_prepare_run_running_persists_limits_and_status():
    """契约 1b/1c/1g：有章节点 → running + 落库；生效上限写回 plan.limits。"""
    repo = AsyncMock()
    plan = _plan()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    c1 = _outline(parent_id=plan.root_outline_id, chapter_id=uuid.uuid4(), name="第一章")
    outline_repo.list.return_value = ([c1], 1)
    svc = _service(repo=repo, outline_repo=outline_repo)

    result = await svc.prepare_run(plan.id, limits=BookLimits(max_chapters=1, max_agent_calls=1))

    assert result == {"run_id": str(plan.id), "status": "running"}
    assert plan.status == "running"
    assert plan.limits["max_chapters"] == 1
    assert plan.limits["max_agent_calls"] == 1
    assert plan.limits["max_tokens"] == 200_000
    assert plan.limits["max_sessions"] == 5
    repo.update_writing_plan.assert_awaited()


@pytest.mark.asyncio
async def test_prepare_run_completed_fast_path():
    """契约 1f：无章节点 → completed 快路径（状态落库，不启任务）。"""
    repo = AsyncMock()
    plan = _plan()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([], 0)
    svc = _service(repo=repo, outline_repo=outline_repo)

    result = await svc.prepare_run(plan.id)

    assert result == {"run_id": str(plan.id), "status": "completed"}
    assert plan.status == "completed"
    repo.update_writing_plan.assert_awaited()


@pytest.mark.asyncio
async def test_prepare_run_running_guard_rejects():
    """契约 1h：重复提交守卫——plan.status=="running" → ValueError（422，双跑防护）。

    空大纲构造：守卫必须先于「无章快路径」触发，锁守卫位置。
    """
    repo = AsyncMock()
    plan = _plan(status="running")
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([], 0)
    svc = _service(repo=repo, outline_repo=outline_repo)

    with pytest.raises(ValueError, match="运行已在进行中"):
        await svc.prepare_run(plan.id)


# ── prepare_run：内容安全阀（契约 1d/1e）───────────────────────────


@pytest.mark.asyncio
async def test_prepare_run_static_safety_valve_raises():
    """契约 1d：static 模式安全阀——content_checker 命中 → ChapterAlreadyWrittenError，
    writer_factory 零调用（安全阀先于一切执行）。"""
    repo = AsyncMock()
    plan = _plan()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    c1 = _outline(parent_id=plan.root_outline_id, chapter_id=uuid.uuid4(), name="第一章")
    outline_repo.list.return_value = ([c1], 1)
    content_checker = AsyncMock(return_value=True)
    svc = _service(repo=repo, outline_repo=outline_repo, content_checker=content_checker)

    with pytest.raises(ChapterAlreadyWrittenError, match="该章已有内容，拒绝重跑"):
        await svc.prepare_run(plan.id)

    content_checker.assert_awaited_once_with(c1.chapter_id)


@pytest.mark.asyncio
async def test_prepare_run_volume_mode_safety_valve_raises():
    """契约 1e：volume 模式拆卷 + 卷内每章安全阀（_check_chapter_written 消费
    chapter dict）；volume_pipeline 缺省 None 不报错——prepare_run 不调 pipeline。"""
    repo = AsyncMock()
    plan = _plan()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    vol = _outline(level="volume", name="第一卷", parent_id=None)
    c1 = _outline(parent_id=vol.id, chapter_id=uuid.uuid4(), name="第一章")
    outline_repo.list.return_value = ([vol, c1], 2)
    content_checker = AsyncMock(return_value=True)
    svc = _service(repo=repo, outline_repo=outline_repo, content_checker=content_checker)

    with pytest.raises(ChapterAlreadyWrittenError, match="该章已有内容，拒绝重跑"):
        await svc.prepare_run(plan.id, mode="volume")

    content_checker.assert_awaited_once_with(c1.chapter_id)


# ── mark_failed（契约 2）───────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_failed_sets_failed_and_persists():
    """契约 2b：mark_failed 置 failed + 落库 → {"run_id", "status": "failed"}。"""
    repo = AsyncMock()
    plan = _plan(status="running")
    repo.get_writing_plan.return_value = plan
    svc = _service(repo=repo)

    result = await svc.mark_failed(str(plan.id))

    assert result == {"run_id": str(plan.id), "status": "failed"}
    assert plan.status == "failed"
    repo.update_writing_plan.assert_awaited()


@pytest.mark.asyncio
async def test_mark_failed_missing_raises():
    """契约 2a：run 不存在 → ValueError("运行不存在")（API 映射 404）。"""
    svc = _service()
    with pytest.raises(ValueError, match="运行不存在"):
        await svc.mark_failed(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_prepare_run_volume_mode_clean_chapters_returns_running():
    """契约 1e 补测（book_run_mixin L66 通过路径）：volume 模式安全阀全部通过
    （content_checker=False）→ has_targets=True → running + 落库（既有 volume 用例
    只覆盖安全阀 raise 分支，本用例补 has_targets 为真的成功路径）。"""
    repo = AsyncMock()
    plan = _plan()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    vol = _outline(level="volume", name="第一卷", parent_id=None)
    c1 = _outline(parent_id=vol.id, chapter_id=uuid.uuid4(), name="第一章")
    outline_repo.list.return_value = ([vol, c1], 2)
    content_checker = AsyncMock(return_value=False)
    svc = _service(repo=repo, outline_repo=outline_repo, content_checker=content_checker)

    result = await svc.prepare_run(plan.id, mode="volume")

    assert result == {"run_id": str(plan.id), "status": "running"}
    assert plan.status == "running"
    content_checker.assert_awaited_once_with(c1.chapter_id)
    repo.update_writing_plan.assert_awaited()
