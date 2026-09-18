"""#1265 安全闸判据解耦：`_check_content_written` 以实际数据为准（TDD RED 阶段）。

权威来源：`specs/f44-book-orchestrator/spec.md` §5.2/D8（「内容已写」安全阀）。

════════════════════════════════════════════════════════════════════
缺陷（v0.15.0-rc2 旅程实测，#1265）
════════════════════════════════════════════════════════════════════

安全闸判据与实际数据状态解耦：判据里的**执行态记录分支短路**了实际数据检查。

`book_service._check_content_written` 旧形态：

    if str(chapter.id) in plan.execution_refs and plan.progress.get(str(chapter.id)) == "done":
        return True                                    # ← 短路：不再查实际数据
    if self._content_checker is not None and chapter.chapter_id is not None:
        return bool(await self._content_checker(chapter.chapter_id))
    return False

用户旅程复现：stage6 跑完 10 章 → 删光章节正文 + 清空 drafts + 清空
outlines.chapter_id → 重跑 `book run` 仍 rc=1「该章已有内容，拒绝重跑」。

双重失效路径（两条叠加，实际数据从未被查）：

1. **执行态短路**：`writing_plans.progress` 持久化在独立两列
   （`progress` / `execution_refs`），删章/清草稿**不会**触碰它 ——
   `progress[oid]=="done"` 恒真 → 第 1 个 `if` 直接 return True。
2. **`chapter_id` 被 FK 置 NULL**：`outlines.chapter_id` 是
   `ForeignKey("chapters.id", ondelete="SET NULL")`
   （`infrastructure/database/models/outline.py:115-121`）——
   删章后自动置 NULL → 第 2 个 `if` 的 `chapter_id is not None`
   门槛不满足 → `content_checker` **根本不被调用**。

修复语义（本契约冻结）：

- **实际数据是唯一判据**：`chapter_id` 为 NULL（章已删）→ 判定「未写」→ 允许重跑；
  `content_checker(chapter_id)` 返回 True（`Chapter.content` 非空）→ 判定「已写」→ 拒绝。
- **执行态记录不再短路**：`progress=="done"` 而实际数据为空 → 允许重跑。
- **原始意图保持**（防重复跑消耗 token）：真有正文的章仍被拒，零 LLM 委托。

【RED 预期形态】本文件全部用例在旧实现下失败：

- 用例 1/3（删空后可重跑）：旧实现返回 True → `ChapterAlreadyWrittenError` → RED。
- 用例 2（真已写拒绝）：旧实现**恰好也返回 True**（走短路分支而非数据分支）→
  断言 `content_checker.assert_awaited_once_with(...)` 失败 → RED（证明走了错分支）。

【可证伪自证】用例 4 把判据改回「只看 progress」后，用例 1 必须 FAIL
（见 `test_regression_guard_progress_only_judgement_is_falsifiable`）。

【mock 策略】沿用 `test_book_service.py` 的 `_make_deps`/`_service` 形状；
`chapter_id=None` 用 `_outline(..., chapter_id=None)` 构造（删章后的真实落库形态）。
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.services.book_service import (
    BookService,
    ChapterAlreadyWrittenError,
)
from tests.unit.domain.services.test_book_service import (  # noqa: F401  # 复用既有构造器（同目录单测共享）
    _chapters,
    _make_deps,
    _outline,
    _plan,
)


def _service_with_chapters(
    *,
    chapter_id: uuid.UUID | None,
    content_checker_result: bool | None,
    progress_state: str = "done",
):
    """构造「单章 + 执行态 done」场景（#1265 核心组合）。

    Args:
        chapter_id: outline.chapter_id（None = 章已删，FK SET NULL 后的真实形态）.
        content_checker_result: content_checker 返回值；None = 不装配 checker
            （镜像 content_checker=None 的降级路径）.
        progress_state: plan.progress[oid] 取值（默认 done = 旧实现短路触发条件）.

    Returns:
        (svc, plan, chapter, deps)
    """
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    chapter = _outline(parent_id=plan.root_outline_id, chapter_id=chapter_id, name="第一章")
    plan.progress[str(chapter.id)] = progress_state
    plan.execution_refs[str(chapter.id)] = "exec-existing"
    repo.get_writing_plan.return_value = plan

    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([chapter], 1)

    overrides: dict = dict(repo=repo, outline_repo=outline_repo)
    if content_checker_result is not None:
        overrides["content_checker"] = AsyncMock(return_value=content_checker_result)
    deps = _make_deps(**overrides)
    return BookService(**deps), plan, chapter, deps


@pytest.mark.asyncio
async def test_write_book_allows_rerun_after_chapters_deleted():
    """用例 1（核心反向断言）：progress=done + 章已删（chapter_id=None）→ 允许重跑。

    issue #1265 的原始场景：删光章节正文后 `chapter_id` 被 FK 置 NULL，
    此时必须判定「未写」放行——而非被执行态记录判为「已写」。
    """
    svc, plan, _chapter, deps = _service_with_chapters(
        chapter_id=None, content_checker_result=False
    )

    result = await svc.write_book(plan.id)

    assert result["status"] in {"completed", "running"}
    deps["writer_factory"].assert_awaited()  # 章被重新委托（重跑生效）


@pytest.mark.asyncio
async def test_write_book_allows_rerun_when_content_empty_despite_progress_done():
    """用例 3：progress=done + chapter_id 存在但正文为空 → 允许重跑。

    与用例 1 的区别：章**未删**，只是正文被清空（`content_checker` 返回 False）。
    执行态记录同样是 done —— 判据必须落到实际数据。
    """
    svc, plan, chapter, deps = _service_with_chapters(
        chapter_id=uuid.uuid4(), content_checker_result=False
    )

    result = await svc.write_book(plan.id)

    assert result["status"] in {"completed", "running"}
    deps["writer_factory"].assert_awaited()
    deps["content_checker"].assert_awaited_once_with(chapter.chapter_id)


@pytest.mark.asyncio
async def test_write_book_safety_valve_blocks_real_content_despite_same_progress():
    """用例 2：真已写（content_checker=True）→ 拒绝，原始防重复意图保持。

    断言 `content_checker` **被调用**：旧实现走执行态短路分支直接 return True，
    从不调用 checker —— 这条断言即「走了错分支」的判据（RED）。

    注意用例 2/3 的 plan/progress/execution_refs 完全同形，
    唯一差异是 content_checker 返回值 → 判据必须读实际数据才能区分。
    """
    svc, plan, chapter, deps = _service_with_chapters(
        chapter_id=uuid.uuid4(), content_checker_result=True
    )

    with pytest.raises(ChapterAlreadyWrittenError, match="已有内容"):
        await svc.write_book(plan.id)

    deps["writer_factory"].assert_not_awaited()  # 零 LLM 委托（防重复消耗）
    deps["content_checker"].assert_awaited_once_with(chapter.chapter_id)


@pytest.mark.asyncio
async def test_write_book_safety_valve_allows_rerun_when_content_cleared():
    """#1265 核心场景（`test_book_service.py` 用例镜像）：execution_refs done
    但实际正文已清空 → 放行重跑（不抛 ChapterAlreadyWrittenError）。

    与用例 1 的区别：章**未删**（chapter_id 非空），仅正文被清空 →
    `content_checker` 返回 False。两条路径都必须放行。
    """
    repo = AsyncMock()
    plan = _plan(root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    c1 = _outline(parent_id=None, chapter_id=uuid.uuid4(), name="第一章")
    outline_repo.list.return_value = ([c1], 1)
    plan.progress[str(c1.id)] = "done"
    plan.execution_refs[str(c1.id)] = "exec-1"
    content_checker = AsyncMock(return_value=False)  # 实际数据：无正文
    deps = _make_deps(repo=repo, outline_repo=outline_repo, content_checker=content_checker)
    svc = BookService(**deps)

    result = await svc.write_book(plan.id)

    assert result["status"] in {"completed", "running"}
    deps["writer_factory"].assert_awaited()  # 重跑生效
    content_checker.assert_awaited_once_with(c1.chapter_id)


@pytest.mark.asyncio
async def test_prepare_run_allows_rerun_after_chapters_deleted():
    """#1265 真实入口：`prepare_run`（GUI/CLI `book run` → `start_run` → 409 走这条）
    在章已删（`chapter_id=None`）+ 执行态 done 时必须放行 running。

    issue 现象即从此路径来：`inkflow book run <plan>` rc=1「该章已有内容，拒绝重跑」。
    """
    svc, plan, _chapter, deps = _service_with_chapters(
        chapter_id=None, content_checker_result=False
    )

    result = await svc.prepare_run(plan.id)

    assert result["status"] == "running"
    deps["writer_factory"].assert_not_awaited()  # prepare_run 只预检 + 落 running，不委托


@pytest.mark.asyncio
async def test_prepare_run_blocks_real_content():
    """`prepare_run` 真已写（checker=True）→ 仍抛 ChapterAlreadyWrittenError（409）。

    防重复意图在真实入口上的守护。
    """
    svc, plan, chapter, deps = _service_with_chapters(
        chapter_id=uuid.uuid4(), content_checker_result=True
    )

    with pytest.raises(ChapterAlreadyWrittenError, match="已有内容"):
        await svc.prepare_run(plan.id)

    deps["content_checker"].assert_awaited_once_with(chapter.chapter_id)


@pytest.mark.asyncio
async def test_check_content_written_only_progress_must_not_block():
    """用例 4（可证伪自证）：纯执行态记录（无 checker 可查）→ 不得拒绝。

    构造：`progress=done` + `execution_refs` 有值 + 章已删（chapter_id=None）
    + 未装配 `content_checker`（无从查证实际数据）。

    旧判据「只看 progress」在此返回 True（拒绝）→ 必须 FAIL。
    该用例是修复的证伪锚点：任何人把判据改回「只看 progress」都会撞红。
    """
    svc, plan, _chapter, deps = _service_with_chapters(chapter_id=None, content_checker_result=None)

    result = await svc.write_book(plan.id)

    # 未被安全闸拦截 → 走到委托（旧实现抛 ChapterAlreadyWrittenError）
    assert result["status"] in {"completed", "running"}
    deps["writer_factory"].assert_awaited()
