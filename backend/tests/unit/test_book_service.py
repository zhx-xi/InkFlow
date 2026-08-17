"""F44 阶段1 书级运行服务单测（TDD RED 阶段）。

权威来源：specs/f44-long-task-orchestrator/spec.md §2.4（多维上限 + 计数器）、
§5.1（委托契约：章 brief → build_agentic_writer → save_draft 回收 → Draft 落库）、
§13.1 M1/M3。
本文件为 `domain/services/book_service.py`（NEW）定义契约。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【模块契约】`inkflow.domain.services.book_service` 必须暴露：
   - `BookService`，构造签名（关键字）：
       BookService(*, repo, writer_factory=None, draft_service=None,
                   outline_repo=None, limits=STAGE1_LIMITS)
     repo: BookRepositoryProtocol（get_writing_plan/update_writing_plan）
     writer_factory: 可调用（镜像 build_agentic_writer 签名，见 §5.1）——
       **kwargs → agent（含 async invoke(messages)）
     draft_service: 鸭子对象（create(*, project_id, chapter_id, content,
       summary) → Draft）——save_draft 回收
     outline_repo: 鸭子对象（list(project_id, ...) → [(Outline, total)]，
       镜像 OutlineRepositoryProtocol）——找计划章节点
     limits: BookLimits（默认 STAGE1_LIMITS = 写死 max_chapters=1/
       max_agent_calls=1）
   - 方法：
     - `async write_book(plan_id: uuid.UUID, limits: BookLimits | None = None)
       -> dict` 启动书级运行（202 语义）→ {run_id, status}
     - `async get_status(run_id: str) -> dict | None`
       书级运行状态（进度树 + 计数器）→ None = run 不存在
     - `async _delegate_chapter(plan, chapter, limits) -> str`
       委托契约核心：章 brief → writer_factory → agent.invoke → save_draft
       回收 → 返回 execution_id（内部方法，测试直调断言委托契约）

2. 【run 载体】阶段 1 run_id = str(WritingPlan.id)（计划即运行载体，
   progress/execution_refs 在 WritingPlan 上，§2.1 权威进度）。

3. 【上限与计数器】（§2.4 + #335 要点 + M3）
   - write_book 启动前校验：limits 合并（请求显式 > 默认 STAGE1_LIMITS）+
     validate_at_least_one_hard_limit（全无护栏 → ValueError「至少一道」）
   - 阶段 1 上限写死 max_chapters=1/max_agent_calls=1——即使请求传入更大值，
     实际执行也按「最多 1 章 / 1 次 agent 调用」推进（#335「上限写死但计数器
     立起来」）
   - get_status 返回 counters 派生字段：
       {max_chapters, max_agent_calls, agent_calls, chapters_written}
     agent_calls = len(plan.execution_refs)；chapters_written = progress 中
     value=="done" 的节点数
   - 计划不存在 → write_book 抛 ValueError("计划不存在")

4. 【进度状态机】（§2.1 PlanNodeStatus + §5.2 章级进度）
   - 委托成功后 progress[chapter_outline_id] == "done"（整棵树锚点推进）
   - 每章 execution_refs[outline_id] = execution_id

5. 【委托契约】（§5.1 + §13.1 M1，mock F27）
   - 章 brief 构造：outline 章节点切片（description/父卷上下文）+ character
     摘要 + 风格/偏好——`_delegate_chapter` 渲染后的 system_prompt 必须包含
     章大纲文本与偏好标记（断言包含关系，不锁格式）
   - writer_factory 以 system_prompt=渲染后的章 brief 调用（断言
     system_prompt 关键字传递）
   - agent.invoke(messages) 被调用一次（ReAct 闭环）
   - 结果经 draft_service.create 回收（save_draft 语义：Draft 落库
     status=draft）——断言 create 调用且 content 非空

6. 【mock 策略】repo/outline_repo 用 AsyncMock；writer_factory 用
   AsyncMock 包装返回 fake agent（async invoke 返回 dict(messages=[...])）；
   draft_service 用 AsyncMock（create 返回 SimpleNamespace(id="draft-1")）。
   GREEN 实现调用断言记录在 mock 上。

7. 【RED 预期形态】模块不存在 → 本文件全用例 ImportError 收集期失败。
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService


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
    """构造 BookService 全部 mock 依赖（可覆盖）。"""
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


# ── 上限校验 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_book_plan_missing_raises():
    """计划不存在 → write_book 抛 ValueError（API 映射 404）。"""
    svc = _service()
    with pytest.raises(ValueError, match="计划不存在"):
        await svc.write_book(uuid.uuid4())


@pytest.mark.asyncio
async def test_write_book_rejects_no_hard_limit():
    """上限全无护栏 → ValueError（「至少一道有限护栏」不变式，§2.4 + §13.1 M3）。"""
    repo = AsyncMock()
    repo.get_writing_plan.return_value = _plan()
    svc = _service(repo=repo)

    with pytest.raises(ValueError, match="至少一道"):
        await svc.write_book(uuid.uuid4(), limits=BookLimits(max_chapters=0, max_agent_calls=0))


@pytest.mark.asyncio
async def test_write_book_limits_hardcoded_stage1():
    """阶段 1 上限写死：即使请求更大值也按 max_chapters=1/max_agent_calls=1 推进。"""
    repo = AsyncMock()
    plan = _plan()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapter = _outline(parent_id=plan.root_outline_id)
    outline_repo.list.return_value = ([chapter], 1)
    svc = _service(repo=repo, outline_repo=outline_repo)

    result = await svc.write_book(plan.id, limits=BookLimits(max_chapters=10, max_agent_calls=10))

    assert result["status"] in {"completed", "running"}
    # 只执行了一章（上限 1）——execution_refs 恰好 1 条
    assert len(plan.execution_refs) == 1


# ── write_book 主路径 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_book_delegates_one_chapter():
    """write_book 主路径：委托一章 → progress done + execution_refs 落库。"""
    repo = AsyncMock()
    plan = _plan()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapter = _outline(parent_id=plan.root_outline_id)
    outline_repo.list.return_value = ([chapter], 1)
    svc = _service(repo=repo, outline_repo=outline_repo)

    result = await svc.write_book(plan.id)

    assert result["run_id"] == str(plan.id)
    assert result["status"] in {"completed", "running"}
    assert plan.progress.get(str(chapter.id)) == "done"
    assert str(chapter.id) in plan.execution_refs
    repo.update_writing_plan.assert_awaited()


@pytest.mark.asyncio
async def test_write_book_empty_outline_completes():
    """计划无章节点 → 无委托、状态 completed、计数器 0（不炸）。"""
    repo = AsyncMock()
    plan = _plan()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([], 0)
    svc = _service(repo=repo, outline_repo=outline_repo)

    result = await svc.write_book(plan.id)

    assert result["status"] == "completed"
    assert plan.execution_refs == {}
    repo.update_writing_plan.assert_awaited()


# ── 委托契约（mock F27）──────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_chapter_passes_brief_to_writer_factory():
    """章 brief（大纲切片 + 偏好）→ writer_factory system_prompt 传递（§5.1）。"""
    repo = AsyncMock()
    plan = _plan()
    chapter = _outline(description="主角在时间旅途中发现悖论")
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([chapter], 1)
    deps = _make_deps(repo=repo, outline_repo=outline_repo)
    svc = BookService(**deps)

    execution_id = await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)

    assert execution_id
    deps["writer_factory"].assert_awaited_once()
    call_kwargs = deps["writer_factory"].await_args.kwargs
    prompt = call_kwargs.get("system_prompt", "")
    # 章 brief 必须包含大纲切片（描述）与偏好注入
    assert "时间旅途中发现悖论" in prompt
    assert "偏好" in prompt or "风格" in prompt


@pytest.mark.asyncio
async def test_delegate_chapter_save_draft_recycle():
    """agent.invoke → draft_service.create 回收（save_draft 语义，Draft 落库）。"""
    repo = AsyncMock()
    plan = _plan()
    chapter = _outline(description="主角在时间旅途中发现悖论")
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([chapter], 1)
    deps = _make_deps(repo=repo, outline_repo=outline_repo)
    svc = BookService(**deps)

    execution_id = await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)

    agent = deps["writer_factory"].return_value
    agent.invoke.assert_awaited_once()
    deps["draft_service"].create.assert_awaited_once()
    create_kwargs = deps["draft_service"].create.await_args.kwargs
    assert create_kwargs["project_id"] == plan.project_id
    assert create_kwargs["content"].strip()
    assert execution_id


@pytest.mark.asyncio
async def test_delegate_chapter_uses_agentic_deps_context():
    """writer_factory 收到 expected_project_id/expected_chapter_id（#275 上下文防御）。"""
    repo = AsyncMock()
    plan = _plan()
    chapter = _outline(description="测试章")
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([chapter], 1)
    deps = _make_deps(repo=repo, outline_repo=outline_repo)
    svc = BookService(**deps)

    await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)

    call_kwargs = deps["writer_factory"].await_args.kwargs
    assert call_kwargs.get("expected_project_id") == plan.project_id
    assert call_kwargs.get("expected_chapter_id") == chapter.chapter_id


# ── get_status 计数器 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_status_shows_counters():
    """book status 显示计数：max=1/1 + agent_calls + chapters_written（M3 验收）。"""
    repo = AsyncMock()
    plan = _plan(
        limits={"max_chapters": 1, "max_agent_calls": 1},
        progress={"c1": "done"},
        execution_refs={"c1": "exec-1"},
        status="completed",
    )
    repo.get_writing_plan.return_value = plan
    svc = _service(repo=repo)

    status = await svc.get_status(str(plan.id))

    assert status is not None
    assert status["status"] == "completed"
    counters = status["counters"]
    assert counters["max_chapters"] == 1
    assert counters["max_agent_calls"] == 1
    assert counters["agent_calls"] == 1
    assert counters["chapters_written"] == 1


@pytest.mark.asyncio
async def test_get_status_missing_returns_none():
    """run 不存在 → get_status 返回 None。"""
    repo = AsyncMock()
    repo.get_writing_plan.return_value = None
    svc = _service(repo=repo)

    assert await svc.get_status(str(uuid.uuid4())) is None
