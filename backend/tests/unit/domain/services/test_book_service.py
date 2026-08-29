"""F44 阶段2 书级运行服务单测（TDD RED 阶段，契约先行）。

权威来源：specs/f44-book-orchestrator/spec.md §2.4（多维上限 + 读取优先级）、
§5.2（阶段 2：顺序派发 + 进度状态机 + 安全阀）、§7 场景 4-6、§12 D7-D11、
§13.2 M4-M6。
本文件为 `domain/services/book_service.py`（阶段 1 合入，阶段 2 扩展）定义契约。

════════════════════════════════════════════════════════════════════
设计假设（阶段 2 GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【构造扩展】BookService 阶段 2 新增两个可选关键字参数（放最后，默认 None）：
   - content_checker: Callable[[uuid.UUID], Awaitable[bool]]——给定
     outline.chapter_id 返回该章是否已有内容（Chapter.content/Draft 检查）
   - project_config_getter: Callable[[uuid.UUID], Awaitable[ProjectConfig | None]]
     ——给定 project_id 返回项目配置（Q2=C：ProjectConfig.extra 项目级上限，
     §2.4/D11）
   阶段 1 既有参数签名不变（向后兼容）。

2. 【write_book 阶段 2 新语义】
   a. limits 解析链（读取优先级 = 请求显式 > 项目级 extra > 默认，§2.4）：
      默认 BookLimits() → project_config_getter 返回 ProjectConfig.extra 键
      book_max_chapters/book_max_agent_calls/book_max_tokens/book_max_sessions
      → 请求显式 BookLimits（request.model_fields_set 只覆盖显式键）→
      validate_at_least_one_hard_limit（全无护栏 → ValueError）
   b. 「内容已写」安全阀预检（§5.2/D8，先于一切执行）：全部目标章任一章
      execution_refs[outline_id] 存在且 progress==done，或
      content_checker(chapter.chapter_id) 返回 True → 抛 ChapterAlreadyWrittenError
      （类定义在 book_service.py，消息含「该章已有内容，拒绝重跑」），
      一个章都不委托（writer_factory 零调用）。
   c. 顺序派发（§5.2/M4）：_find_chapters 全部 level=chapter 按 sort_order 升序；
      每章先 progress[outline_id]=in_progress 落库（update_writing_plan）→
      _delegate_chapter → 成功 progress=done + execution_refs 落库；
      异常 progress=failed 落库继续下一章（章级只报告）。
   d. 硬护栏（§2.4/D10）：已执行章数 >= max_chapters 或
      len(execution_refs) >= max_agent_calls → 剩余章 progress=skipped 落库后终止。
   e. token 软超限（§7-6/D10）：_delegate_chapter 内从 agent.invoke 结果提取
      result.get("usage", {}).get("total_tokens", 0)，累计到
      plan.limits["tokens_used"]；超过 limits.max_tokens →
      plan.limits["tokens_warning"]=True（告警不终止）。

3. 【get_status 阶段 2 新键】counters 增加 max_tokens / tokens_used /
   tokens_warning（plan.limits.get 预置），既有 4 键不变（向后兼容）。

4. 【RED 预期形态】阶段 2 新契约在阶段 1 实现下失败：
   - 安全阀用例：ImportError（ChapterAlreadyWrittenError 不存在）/ TypeError
     （content_checker/project_config_getter 构造参数不存在）
   - 顺序派发/硬护栏/失败继续用例：AssertionError（阶段 1 只委托 1 章）
   - token 用例：AssertionError（plan.limits 无 tokens_used/tokens_warning）
   - get_status 新键：KeyError
   - 守护用例（docstring 注明「守护用例 RED 期 PASS 刻意」）：阶段 1 已满足，
     阶段 2 语义向后兼容，RED 期刻意保持 PASS。

【mock 策略】repo/outline_repo 用 AsyncMock；writer_factory 用 AsyncMock 包装
返回 fake agent（async invoke 返回 dict(messages=[...])）；draft_service 用
AsyncMock（create 返回 SimpleNamespace(id="draft-1")）。GREEN 实现调用断言
记录在 mock 上。
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


def _chapters(plan: WritingPlan, n: int, *, parent_id: uuid.UUID | None = None) -> list[Outline]:
    """构造 n 个章 outline（parent_id 默认挂 plan.root_outline_id；sort_order 0..n-1）。"""
    pid = plan.root_outline_id if parent_id is None else parent_id
    return [
        _outline(parent_id=pid, sort_order=i, chapter_id=uuid.uuid4(), name=f"第{i + 1}章")
        for i in range(n)
    ]


def _make_deps(**overrides):
    """构造 BookService 全部 mock 依赖（可覆盖；阶段 2 新参数 content_checker/
    project_config_getter 由用例显式传入——阶段 1 构造不接受 → RED）。"""
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
    """计划不存在 → write_book 抛 ValueError（API 映射 404）。（守护用例 RED 期 PASS 刻意）"""
    svc = _service()
    with pytest.raises(ValueError, match="计划不存在"):
        await svc.write_book(uuid.uuid4())


@pytest.mark.asyncio
async def test_write_book_rejects_no_hard_limit():
    """上限全无护栏 → ValueError（「至少一道有限护栏」不变式，§2.4 + §13.2 M5）。
    （守护用例 RED 期 PASS 刻意：阶段 2 limits 解析链末端仍执行该校验）"""
    repo = AsyncMock()
    repo.get_writing_plan.return_value = _plan()
    svc = _service(repo=repo)

    with pytest.raises(ValueError, match="至少一道"):
        await svc.write_book(uuid.uuid4(), limits=BookLimits(max_chapters=0, max_agent_calls=0))


@pytest.mark.asyncio
async def test_write_book_max_chapters_hard_limit_stops():
    """max_chapters 硬护栏生效：请求 limits=max_chapters=2/max_agent_calls=10，outline 5 章
    → 只写前 2 章 done，后 3 章 skipped 落库（§2.4/D10 硬护栏超限终止 + 进度落库）。

    （改写自阶段 1 test_write_book_limits_hardcoded_stage1：旧语义「上限写死 1 章」
    被阶段 2「可配置上限 + 剩余章 skipped」取代——阶段 1 实现只写 1 章 → RED）
    """
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapters = _chapters(plan, 5)
    outline_repo.list.return_value = (chapters, 5)
    svc = _service(repo=repo, outline_repo=outline_repo)

    result = await svc.write_book(plan.id, limits=BookLimits(max_chapters=2, max_agent_calls=10))

    assert result["status"] in {"completed", "running"}
    assert len([k for k, v in plan.progress.items() if v == "done"]) == 2
    assert len([k for k, v in plan.progress.items() if v == "skipped"]) == 3
    assert len(plan.execution_refs) == 2


# ── write_book 主路径 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_book_delegates_one_chapter():
    """write_book 主路径：委托一章 → progress done + execution_refs 落库。
    （守护用例 RED 期 PASS 刻意：1 章场景在阶段 2 顺序派发语义下行为不变）"""
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
    """计划无章节点 → 无委托、状态 completed、计数器 0（不炸）。
    （守护用例 RED 期 PASS 刻意）"""
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


@pytest.mark.asyncio
async def test_write_book_dispatches_all_chapters_in_order():
    """顺序派发多章（§5.2/M4）：outline 3 章 → writer_factory 委托 3 次、
    progress 3 个 done、execution_refs 3 条、每章 in_progress/done 落库
    （update_writing_plan 调用 ≥ 章数×2 次）。

    阶段 1 实现只委托第一章 → 委托次数/进度/落库次数全不满足 → RED。
    """
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapters = _chapters(plan, 3)
    outline_repo.list.return_value = (chapters, 3)
    deps = _make_deps(repo=repo, outline_repo=outline_repo)
    svc = BookService(**deps)

    result = await svc.write_book(plan.id)

    assert result["status"] == "completed"
    assert len(deps["writer_factory"].await_args_list) == 3
    assert all(plan.progress.get(str(c.id)) == "done" for c in chapters)
    assert len(plan.execution_refs) == 3
    # 每章至少 in_progress + done 两次落库（3 章 ≥ 6 次）
    assert repo.update_writing_plan.await_count >= 6


@pytest.mark.asyncio
async def test_write_book_dispatches_in_sort_order():
    """顺序派发按 sort_order（§5.2）：3 章 sort_order 2/0/1 → 执行顺序 0→1→2，
    以委托调用顺序与 execution_refs 键序双重断言。

    （改写自阶段 1 test_write_book_anchored_chapter_preferred：旧语义「锚点章优先
    只取一章」被阶段 2「全部章按 sort_order 顺序派发」取代——阶段 1 只委托 1 章 → RED）
    """
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    c_sort2 = _outline(
        parent_id=plan.root_outline_id,
        sort_order=2,
        chapter_id=uuid.uuid4(),
        name="第三章",
    )
    c_sort0 = _outline(
        parent_id=plan.root_outline_id,
        sort_order=0,
        chapter_id=uuid.uuid4(),
        name="第一章",
    )
    c_sort1 = _outline(
        parent_id=plan.root_outline_id,
        sort_order=1,
        chapter_id=uuid.uuid4(),
        name="第二章",
    )
    outline_repo.list.return_value = ([c_sort2, c_sort0, c_sort1], 3)
    deps = _make_deps(repo=repo, outline_repo=outline_repo)
    svc = BookService(**deps)

    result = await svc.write_book(plan.id)

    assert result["status"] == "completed"
    actual_order = [
        call.kwargs["expected_chapter_id"] for call in deps["writer_factory"].await_args_list
    ]
    assert actual_order == [c_sort0.chapter_id, c_sort1.chapter_id, c_sort2.chapter_id]
    assert list(plan.execution_refs.keys()) == [str(c_sort0.id), str(c_sort1.id), str(c_sort2.id)]


@pytest.mark.asyncio
async def test_write_book_no_anchor_dispatches_all_chapters():
    """无锚点匹配 → 仍派发全部章（2 章都写 done，§5.2 顺序派发全量语义）。

    （改写自阶段 1 test_write_book_fallback_any_chapter：旧语义「回退任意一章」被
    阶段 2「全部章派发」取代——阶段 1 只委托 1 章 → RED）
    """
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapters = [
        _outline(parent_id=None, chapter_id=uuid.uuid4(), name="游离章一"),
        _outline(parent_id=None, chapter_id=uuid.uuid4(), name="游离章二"),
    ]
    outline_repo.list.return_value = (chapters, 2)
    svc = _service(repo=repo, outline_repo=outline_repo)

    result = await svc.write_book(plan.id)

    assert result["status"] == "completed"
    assert len(plan.execution_refs) == 2
    assert all(plan.progress.get(str(c.id)) == "done" for c in chapters)


# ── 「内容已写」安全阀（§5.2/D8，§7-4，§13.2 M6）───────────────────


@pytest.mark.asyncio
async def test_write_book_safety_valve_already_executed_raises():
    """安全阀-执行已完成：execution_refs[outline_id] 存在且 progress==done →
    ChapterAlreadyWrittenError（消息含「该章已有内容，拒绝重跑」），writer_factory
    零调用（§5.2 预检全部目标章，一个章都不委托）。

    阶段 1 无安全阀/异常类 → ImportError + 阶段 1 仍委托 → RED。
    """
    from inkflow.domain.services.book_service import ChapterAlreadyWrittenError

    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    c1 = _outline(parent_id=None, chapter_id=uuid.uuid4(), name="第一章")
    c2 = _outline(parent_id=None, chapter_id=uuid.uuid4(), name="第二章")
    outline_repo.list.return_value = ([c1, c2], 2)
    # 预置：c1 已执行完成
    plan.progress[str(c1.id)] = "done"
    plan.execution_refs[str(c1.id)] = "exec-1"
    deps = _make_deps(repo=repo, outline_repo=outline_repo)
    svc = BookService(**deps)

    with pytest.raises(ChapterAlreadyWrittenError, match="该章已有内容，拒绝重跑"):
        await svc.write_book(plan.id)

    deps["writer_factory"].assert_not_awaited()


@pytest.mark.asyncio
async def test_write_book_safety_valve_content_checker_blocks():
    """安全阀-内容已写：content_checker(chapter.chapter_id) 返回 True →
    ChapterAlreadyWrittenError（消息含「已有内容」），writer_factory 零调用（§2.3-1）。

    阶段 1 构造不接受 content_checker 参数 → TypeError → RED。
    """
    from inkflow.domain.services.book_service import ChapterAlreadyWrittenError

    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    c1 = _outline(parent_id=plan.root_outline_id, chapter_id=uuid.uuid4(), name="第一章")
    outline_repo.list.return_value = ([c1], 1)
    content_checker = AsyncMock(return_value=True)
    deps = _make_deps(repo=repo, outline_repo=outline_repo, content_checker=content_checker)
    svc = BookService(**deps)

    with pytest.raises(ChapterAlreadyWrittenError, match="已有内容"):
        await svc.write_book(plan.id)

    deps["writer_factory"].assert_not_awaited()
    content_checker.assert_awaited_once_with(c1.chapter_id)


@pytest.mark.asyncio
async def test_write_book_safety_valve_passes_when_clean():
    """安全阀放行：content_checker 返回 False + 无执行记录 → 正常委托（§9.2-1）。

    阶段 1 构造不接受 content_checker 参数 → TypeError → RED。
    """
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    c1 = _outline(parent_id=plan.root_outline_id, chapter_id=uuid.uuid4(), name="第一章")
    outline_repo.list.return_value = ([c1], 1)
    content_checker = AsyncMock(return_value=False)
    deps = _make_deps(repo=repo, outline_repo=outline_repo, content_checker=content_checker)
    svc = BookService(**deps)

    result = await svc.write_book(plan.id)

    assert result["status"] in {"completed", "running"}
    assert plan.progress.get(str(c1.id)) == "done"
    content_checker.assert_awaited_once_with(c1.chapter_id)


# ── 项目级上限（Q2=C：ProjectConfig.extra，§2.4/D11）──────────────


@pytest.mark.asyncio
async def test_write_book_project_level_limits_via_extra():
    """项目级上限：project_config_getter 返回 ProjectConfig(extra={"book_max_chapters": 2})，
    outline 3 章 → 2 done + 1 skipped（§2.4 读取优先级 项目级 > 默认）。

    阶段 1 构造不接受 project_config_getter 参数 → TypeError → RED。
    """
    from inkflow.domain.models.project import ProjectConfig

    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapters = _chapters(plan, 3)
    outline_repo.list.return_value = (chapters, 3)
    project_config_getter = AsyncMock(return_value=ProjectConfig(extra={"book_max_chapters": 2}))
    deps = _make_deps(
        repo=repo, outline_repo=outline_repo, project_config_getter=project_config_getter
    )
    svc = BookService(**deps)

    result = await svc.write_book(plan.id)

    assert result["status"] == "completed"
    assert len([k for k, v in plan.progress.items() if v == "done"]) == 2
    assert len([k for k, v in plan.progress.items() if v == "skipped"]) == 1
    project_config_getter.assert_awaited_once_with(plan.project_id)


@pytest.mark.asyncio
async def test_write_book_request_limits_override_project_level():
    """请求显式覆盖项目级：项目级 extra book_max_chapters=2 + 请求 BookLimits(max_chapters=3)
    → 3 done（读取优先级 请求显式 > 项目级，§2.4）。

    阶段 1 构造不接受 project_config_getter 参数 → TypeError → RED。
    """
    from inkflow.domain.models.project import ProjectConfig

    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapters = _chapters(plan, 3)
    outline_repo.list.return_value = (chapters, 3)
    project_config_getter = AsyncMock(return_value=ProjectConfig(extra={"book_max_chapters": 2}))
    deps = _make_deps(
        repo=repo, outline_repo=outline_repo, project_config_getter=project_config_getter
    )
    svc = BookService(**deps)

    result = await svc.write_book(plan.id, limits=BookLimits(max_chapters=3))

    assert result["status"] == "completed"
    assert len([k for k, v in plan.progress.items() if v == "done"]) == 3
    assert len([k for k, v in plan.progress.items() if v == "skipped"]) == 0


# ── 硬护栏 / token 软护栏（§2.4/D10，§7-6，§13.2 M5）──────────────


@pytest.mark.asyncio
async def test_write_book_max_agent_calls_hard_limit_stops():
    """调用数硬护栏：max_agent_calls=1 + outline 3 章 → 1 done + 2 skipped（§2.4
    硬护栏超限终止 + 剩余章 skipped 落库）。

    阶段 1 只委托 1 章且无 skipped 落库 → AssertionError → RED。
    """
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapters = _chapters(plan, 3)
    outline_repo.list.return_value = (chapters, 3)
    svc = _service(repo=repo, outline_repo=outline_repo)

    result = await svc.write_book(plan.id, limits=BookLimits(max_chapters=100, max_agent_calls=1))

    assert result["status"] == "completed"
    assert len([k for k, v in plan.progress.items() if v == "done"]) == 1
    assert len([k for k, v in plan.progress.items() if v == "skipped"]) == 2
    assert len(plan.execution_refs) == 1


@pytest.mark.asyncio
async def test_write_book_token_soft_limit_warns_not_stops():
    """token 软超限告警：agent.invoke 返回 usage.total_tokens=300000、limits
    max_tokens=200000、3 章 → 全部章完成（不终止）+ plan.limits["tokens_warning"]==True
    + tokens_used 累计 900000（§7-6：token 软护栏超限告警不强制终止）。

    阶段 1 只委托 1 章且 plan.limits 无 tokens_warning/tokens_used → AssertionError → RED。
    """
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapters = _chapters(plan, 3)
    outline_repo.list.return_value = (chapters, 3)

    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="正文", tool_calls=[])],
        "usage": {"total_tokens": 300_000},
    }
    writer_factory = AsyncMock(return_value=fake_agent)
    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")
    svc = _service(
        repo=repo,
        outline_repo=outline_repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
    )

    result = await svc.write_book(plan.id, limits=BookLimits(max_tokens=200_000))

    assert result["status"] == "completed"
    assert len([k for k, v in plan.progress.items() if v == "done"]) == 3  # 软护栏不终止
    assert plan.limits.get("tokens_warning") is True
    assert plan.limits.get("tokens_used") == 900_000  # 3 × 300000 累计


@pytest.mark.asyncio
async def test_write_book_token_under_limit_no_warning():
    """token 正常不告警：usage.total_tokens=1000 < max_tokens → tokens_used 累计 1000、
    无 tokens_warning（§7-6 软护栏不触发）。

    阶段 1 不写 plan.limits["tokens_used"] → None ≠ 1000 → AssertionError → RED。
    """
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    c1 = _outline(parent_id=plan.root_outline_id, chapter_id=uuid.uuid4(), name="第一章")
    outline_repo.list.return_value = ([c1], 1)

    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {
        "messages": [SimpleNamespace(content="正文", tool_calls=[])],
        "usage": {"total_tokens": 1_000},
    }
    writer_factory = AsyncMock(return_value=fake_agent)
    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")
    svc = _service(
        repo=repo,
        outline_repo=outline_repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
    )

    result = await svc.write_book(plan.id, limits=BookLimits(max_tokens=200_000))

    assert result["status"] in {"completed", "running"}
    assert plan.limits.get("tokens_used") == 1_000
    assert plan.limits.get("tokens_warning") is not True


# ── 章级进度状态机（§5.2：failed 分支继续）────────────────────────


@pytest.mark.asyncio
async def test_write_book_chapter_failure_marks_failed_continues():
    """章级失败标记 failed 继续：writer_factory 对第 2 章抛异常 → progress 第 2 章
    failed 落库 + 第 3 章仍 done（§5.2 状态机 failed 分支，章级只报告不中断）。

    阶段 1 只委托 1 章 → 第 2 章无 failed 进度 → AssertionError → RED。
    """
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapters = _chapters(plan, 3)
    outline_repo.list.return_value = (chapters, 3)

    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {"messages": [SimpleNamespace(content="正文", tool_calls=[])]}
    writer_factory = AsyncMock(side_effect=[fake_agent, RuntimeError("章级失败"), fake_agent])
    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")
    svc = _service(
        repo=repo,
        outline_repo=outline_repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
    )

    result = await svc.write_book(plan.id)

    assert result["status"] == "completed"
    assert plan.progress.get(str(chapters[0].id)) == "done"
    assert plan.progress.get(str(chapters[1].id)) == "failed"
    assert plan.progress.get(str(chapters[2].id)) == "done"


# ── 委托契约（mock F27，§5.1 + §13.1 M1）─────────────────────────


@pytest.mark.asyncio
async def test_delegate_chapter_passes_brief_to_writer_factory():
    """章 brief（大纲切片 + 偏好）→ writer_factory system_prompt 传递（§5.1）。
    （守护用例 RED 期 PASS 刻意：阶段 2 _delegate_chapter 签名不变仍返回 str）"""
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
    """agent.invoke → draft_service.create 回收（save_draft 语义，Draft 落库）。
    （守护用例 RED 期 PASS 刻意）"""
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
    """writer_factory 收到 expected_project_id/expected_chapter_id（#275 上下文防御）。
    （守护用例 RED 期 PASS 刻意）"""
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


@pytest.mark.asyncio
async def test_delegate_chapter_writer_factory_none_raises():
    """writer_factory 未装配 → ValueError（委托防御分支）。
    （守护用例 RED 期 PASS 刻意）"""
    repo = AsyncMock()
    plan = _plan()
    chapter = _outline(description="测试章")
    svc = _service(repo=repo, writer_factory=None)

    with pytest.raises(ValueError, match="writer_factory 未装配"):
        await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)


# ── get_status 计数器 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_status_shows_counters():
    """book status 显示计数：max=1/1 + agent_calls + chapters_written（M3 验收）。
    （守护用例 RED 期 PASS 刻意：阶段 2 既有 4 键向后兼容）"""
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
async def test_get_status_counters_stage2_keys():
    """get_status 阶段 2 新键：counters 含 max_tokens/tokens_used/tokens_warning
    （plan.limits 预置；§2.4 计数器 + 阶段 2 放开配置）。

    阶段 1 counters 只有 4 键 → KeyError → RED。
    """
    repo = AsyncMock()
    plan = _plan(
        limits={
            "max_chapters": 1,
            "max_agent_calls": 1,
            "max_tokens": 200_000,
            "tokens_used": 12_345,
            "tokens_warning": True,
        },
        progress={"c1": "done"},
        execution_refs={"c1": "exec-1"},
        status="completed",
    )
    repo.get_writing_plan.return_value = plan
    svc = _service(repo=repo)

    status = await svc.get_status(str(plan.id))

    assert status is not None
    counters = status["counters"]
    assert counters["max_tokens"] == 200_000
    assert counters["tokens_used"] == 12_345
    assert counters["tokens_warning"] is True


@pytest.mark.asyncio
async def test_get_status_missing_returns_none():
    """run 不存在 → get_status 返回 None。（守护用例 RED 期 PASS 刻意）"""
    repo = AsyncMock()
    repo.get_writing_plan.return_value = None
    svc = _service(repo=repo)

    assert await svc.get_status(str(uuid.uuid4())) is None


# ── Coverage-Gap 补测（2026-08-17 CI coverage-backend 98.39% 缺口）──


@pytest.mark.asyncio
async def test_write_book_outline_repo_none_completes():
    """outline_repo 未装配 → 无委托、状态 completed（_find_chapters 防御分支）。
    （守护用例 RED 期 PASS 刻意）"""
    repo = AsyncMock()
    plan = _plan()
    repo.get_writing_plan.return_value = plan
    svc = _service(repo=repo, outline_repo=None)

    result = await svc.write_book(plan.id)

    assert result["status"] == "completed"
    assert plan.execution_refs == {}


@pytest.mark.asyncio
async def test_write_book_root_outline_none_any_chapter():
    """root_outline_id 为 None → 跳过锚点逻辑直接取章（142->146 分支）。
    阶段 2 语义变为「派发全部章」，本用例 1 章场景下新旧语义无差异。
    （守护用例 RED 期 PASS 刻意）"""
    repo = AsyncMock()
    plan = _plan(root_outline_id=None)
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    other = _outline(parent_id=None, description="游离章")
    outline_repo.list.return_value = ([other], 1)
    svc = _service(repo=repo, outline_repo=outline_repo)

    result = await svc.write_book(plan.id)

    assert result["status"] == "completed"
    assert str(other.id) in plan.execution_refs


@pytest.mark.asyncio
async def test_extract_final_content_variants():
    """_extract_final_content 变体：空 messages → ""；dict 末条；无 content → ""。
    （守护用例 RED 期 PASS 刻意）"""
    from inkflow.domain.services.book_service import _extract_final_content

    assert _extract_final_content({}) == ""
    assert _extract_final_content({"messages": []}) == ""
    # dict 形态末条
    assert _extract_final_content({"messages": [{"content": "正文A"}]}) == "正文A"
    # 无 content → ""
    assert _extract_final_content({"messages": [{"role": "user"}]}) == ""
