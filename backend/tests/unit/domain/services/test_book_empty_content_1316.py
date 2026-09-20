"""#1316 RED 契约：book 轨空 LLM 产出守卫 + 有限重试 + 专用异常归因。

权威来源：GitHub issue #1316（v0.15.0-rc4 旅程 stage6 第 10 章空产出 → 整章 failed）
+ issue 评论「方案审计」（2026-09-20）两条硬约束：
  ① `book_service.py` 已 888/900 行 → 守卫/重试/归因必须抽函数，禁止内联膨胀；
  ② 兄弟点 `infrastructure/agent/book_pipeline.py:_delegate_chapter` 为逐字同形兜底、
     同样无空内容守卫 → 必须走**同一处** helper（修一次，所有 caller 走同一处）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 【专用异常】新增 `ChapterContentEmptyError`（继承 Exception），语义 = 「LLM 连续空产出」。
   消息须含明确归因串 `LLM 空产出`，与下游 `draft_service` 的输入校验拒绝
   （ValueError「草稿内容不能为空」）**可区分**——issue 明确要求 progress_reason
   区分「LLM 空产出」与「下游校验拒绝」。

2. 【守卫位置】守卫放在**上游调用方**（book 轨），**不得**放宽
   `draft_service.create` 的空内容校验（那是 #275 同族正确 trust-boundary 守卫，
   issue §建议修法 明令）。

3. 【有限重试】空内容命中 → 重试 1 次（重新走 writer_factory + agent.invoke）。
   - 首空、次成功 → 章节成功（正常返回 execution_id）
   - 连续 2 次空 → 抛 `ChapterContentEmptyError`
   即总尝试次数 = 2（1 初始 + 1 重试）；两种结果都必须**不**把空串传给
   `draft_service.create`。

4. 【计数语义】重试计入 `agent_calls`：`_delegate_chapter` 每次真实委托
   （含每次重试的 `agent.invoke`）都累计 token/调用记账，与
   `len(plan.execution_refs) >= max_agent_calls` 硬护栏口径一致
   （rc4 旅程判据断言 agent_calls == N，重试须计入否则破护栏）。

5. 【兄弟点同修】`book_pipeline.py:_delegate_chapter` 的同形兜底同样受守卫保护，
   且与 book_service **共用同一 helper**（不允许两份守卫漂移）。

6. 【可证伪自证】去掉守卫 → 断言 1/2（空产出必重试）必须 FAIL。

【RED 预期形态】GREEN 前：`ChapterContentEmptyError` 不存在 → ImportError；
即便绕过 import，空内容亦未被守卫 → 断言 1 的「重试 1 次」不成立 → RED。
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, BookLimits, WritingPlan
from inkflow.domain.services.book_service import BookService

# ── 夹具（镜像 test_book_service.py 的轻量版，避免耦合 897 行贴线文件）──


def _plan(**overrides) -> WritingPlan:
    base = dict(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
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
        project_id=uuid.uuid4(),
        name="第一章",
        description="主角在时间旅途中发现悖论",
        sort_order=0,
        level="chapter",
        parent_id=None,
        chapter_id=uuid.uuid4(),
        extra={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return Outline(**base)


def _empty_result() -> dict:
    """空产出形态：末条 message content 为 ""（`_extract_final_content` 返回 ""）。"""
    return {
        "messages": [SimpleNamespace(content="", tool_calls=[])],
        "usage": {"total_tokens": 100},
    }


def _ok_result(body: str = "第一章正文内容") -> dict:
    return {
        "messages": [SimpleNamespace(content=body, tool_calls=[])],
        "usage": {"total_tokens": 100},
    }


def _service(**overrides) -> tuple[BookService, dict]:
    repo = AsyncMock()
    repo.get_writing_plan.return_value = None
    repo.update_writing_plan.return_value = None

    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = _ok_result()
    writer_factory = AsyncMock(return_value=fake_agent)

    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")

    deps: dict = dict(
        repo=repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
        outline_repo=AsyncMock(),
        limits=STAGE1_LIMITS,
    )
    deps.update(overrides)
    return BookService(**deps), deps


# ── 契约 1/3：空产出触发重试，重试成功即正常 ──────────────────────


@pytest.mark.asyncio
async def test_empty_content_retries_once_then_succeeds_1316():
    """【R】首空 → 重试 1 次 → 次正常 → 章节成功（不 failed）。

    守护的可证伪点：无守卫时实现只 invoke 1 次且把 "" 直传 draft_service
    （真实下游抛 ValueError）→ `invoke.await_count == 2` 与执行成功断言双红。
    """
    plan = _plan()
    chapter = _outline()
    svc, deps = _service()
    deps["writer_factory"].return_value.invoke.side_effect = [
        _empty_result(),
        _ok_result("第一章正文内容"),
    ]

    execution_id = await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)

    assert execution_id == "draft-1"
    # 重试 1 次：总尝试 2（1 初始 + 1 重试）
    assert deps["writer_factory"].return_value.invoke.await_count == 2
    # 空串绝不落库：唯一一次 create 收到的 content 非空
    assert deps["draft_service"].create.await_count == 1
    create_kwargs = deps["draft_service"].create.await_args.kwargs
    assert create_kwargs["content"].strip() == "第一章正文内容"


# ── 契约 2：两次都空 → 专用异常，归因可区分 ──────────────────────


@pytest.mark.asyncio
async def test_empty_content_twice_raises_dedicated_error_1316():
    """【R】连续 2 次空产出 → `ChapterContentEmptyError`，归因含「LLM 空产出」。

    区分度保证：消息含「LLM 空产出」而非下游 ValueError 的「草稿内容不能为空」。
    """
    from inkflow.domain.services.book_service import ChapterContentEmptyError

    plan = _plan()
    chapter = _outline()
    svc, deps = _service()
    deps["writer_factory"].return_value.invoke.side_effect = [
        _empty_result(),
        _empty_result(),
    ]

    with pytest.raises(ChapterContentEmptyError, match="LLM 空产出"):
        await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)

    # 有限重试：total 2 次尝试，不无限循环
    assert deps["writer_factory"].return_value.invoke.await_count == 2
    # 空串从未触发下游 create（守卫在上游拦截，不依赖下游 ValueError）
    assert deps["draft_service"].create.await_count == 0


@pytest.mark.asyncio
async def test_writes_empty_content_marks_chapter_failed_with_reason_1316():
    """【R】端到端（write_book）：两次空产出 → 该章 failed + progress_reason 含归因。

    归因必须是**专用异常**而非下游 ValueError——rc4 实测的
    `ValueError: 草稿内容不能为空` 正是本 issue 要消灭的错归因。
    """
    repo = AsyncMock()
    plan = _plan()
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapters = [_outline(parent_id=plan.root_outline_id)]
    outline_repo.list.return_value = (chapters, 1)
    svc, deps = _service(repo=repo, outline_repo=outline_repo)
    deps["writer_factory"].return_value.invoke.side_effect = [
        _empty_result(),
        _empty_result(),
    ]

    result = await svc.write_book(plan.id)

    assert result["status"] == "failed"
    assert plan.progress.get(str(chapters[0].id)) == "failed"
    reason = plan.progress_reason or ""
    assert "ChapterContentEmptyError" in reason
    assert "LLM 空产出" in reason
    # 不得再出现下游输入校验的归因（本 issue 的核心缺陷签名）
    assert "草稿内容不能为空" not in reason


# ── 契约 4：重试计入 agent_calls（护栏口径） ──────────────────────


@pytest.mark.asyncio
async def test_retry_counts_toward_agent_calls_1316():
    """【R】重试计入 agent_calls：max_agent_calls=1 + 首空 → 重试后不再委托第 2 章。

    口径：一次章委托（含其重试）消耗 1 个 agent_calls 名额是不成立的——
    重试是**真实 LLM 调用**，必须计入。本用例断言：首章重试后
    `len(plan.execution_refs)` 未超 `max_agent_calls`，第二章被 skipped。
    """
    repo = AsyncMock()
    plan = _plan(limits={"max_chapters": 1, "max_agent_calls": 1}, root_outline_id=uuid.uuid4())
    repo.get_writing_plan.return_value = plan
    outline_repo = AsyncMock()
    chapters = [
        _outline(parent_id=plan.root_outline_id, sort_order=0, name="第1章"),
        _outline(parent_id=plan.root_outline_id, sort_order=1, name="第2章"),
    ]
    outline_repo.list.return_value = (chapters, 2)
    svc, deps = _service(repo=repo, outline_repo=outline_repo)
    deps["writer_factory"].return_value.invoke.side_effect = [
        _empty_result(),
        _ok_result("第一章正文内容"),
        _ok_result("第二章正文内容"),
    ]

    # 🔴 上限必须经**请求显式** limits= 传入：merge_book_limits 从默认 BookLimits()
    # 起步，plan.limits 不是输入面（只作持久化/回显）——见 writing_plan.merge_book_limits。
    await svc.write_book(plan.id, limits=BookLimits(max_chapters=10, max_agent_calls=1))

    # 第 1 章成功（重试 1 次）；第 2 章因 max_agent_calls 已满被 skipped
    assert plan.progress.get(str(chapters[0].id)) == "done"
    assert plan.progress.get(str(chapters[1].id)) == "skipped"
    assert len(plan.execution_refs) <= 1


# ── 契约 5：兄弟点同修（book_pipeline 同形兜底） ──────────────────


def test_sibling_book_pipeline_shares_guard_helper_1316():
    """【R】兄弟点共用同一 helper：book_pipeline 与 book_service 不得各写一份守卫。

    判据（结构化，非文本比对）：两模块的兜底路径必须引用**同一个**守卫符号
    —— `ChapterContentEmptyError` 由 `book_service` 定义，`book_pipeline` 直接 import
    使用（同族先例：`draft_fallback_needed` / `_extract_final_content` 均走
    `usage_accounting` 单点实现）。
    """
    from inkflow.domain.services import book_service
    from inkflow.infrastructure.agent import book_pipeline

    assert hasattr(book_service, "ChapterContentEmptyError")
    # 兄弟点导入同一异常类（身份相等，非同名两份）
    assert getattr(book_pipeline, "ChapterContentEmptyError", None) is (
        book_service.ChapterContentEmptyError
    )
    # 同一守卫函数（helper 单点实现）
    guard = getattr(book_service, "guard_empty_chapter_content", None)
    assert guard is not None, "守卫 helper 未抽为模块级函数（book_service 贴线，必须抽）"
    assert getattr(book_pipeline, "guard_empty_chapter_content", None) is guard
