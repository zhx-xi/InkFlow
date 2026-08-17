"""F45 M2 后台刷新模块 RED 契约测试（summary_background_refresh 整模块，全 mock 轨）.

设计假设（GREEN 实现必须满足的契约）:
- 模块路径: inkflow.infrastructure.context.summary_background_refresh（本批新建；
  RED 期模块不存在 → 顶部 import 收集期 ImportError（cannot import name，
  等价 ModuleNotFoundError 收集错误），测试体不执行）
- run_summary_background_refresh(anchors, *, scope, project_id, anchor_hash,
  session_factory=None, summarizer=None, summary_repo=None, audit=None) -> bool:
  独立 session 内 summarize → upsert → 审计；True=成功落库 / False=失败
  （已审计，不抛出——后台任务绝不让异常逃逸）
  - 成功（summarize → (new_summary, [])）: upsert(new_summary) +
    audit.record(project_id=project_id, severity_summary="semantic_summary_generated",
    degraded=True, actor="memory")
  - 防幻觉丢弃（summarize → (None, dropped) 且 dropped truthy）: 不 upsert +
    audit.record(project_id=project_id, severity_summary="semantic_summary_failed",
    degraded=True, actor="memory", note=含 dropped 内容) + False
  - SemanticSummaryError（inkflow.domain.ports.semantic_summary_errors）: 不抛 +
    audit.record(severity_summary="semantic_summary_failed") + False
  - 其它异常: 不抛 + 同上审计 + False
  - 测试注入形态: session_factory = async 上下文管理器（可多次进入；内部 session
    可为假对象——注入 fakes 后不被真正使用）；summarizer/summary_repo/audit 全
    AsyncMock；run 内部调 summarizer.summarize(anchors, scope=scope, project_id=
    project_id, anchor_hash=anchor_hash, model=...)（model 走 config.llm_default_model
    唯一默认源 #415，mock 轨不断言 model 值）
- schedule_summary_background_refresh(anchors, *, scope, project_id, anchor_hash)
  -> None: fire-and-forget——await 立即返回，不等待任务完成；函数体内
  from inkflow.infrastructure.background.tasks import spawn_background_task
  （模块属性 patch 生效前提；该共享框架由任务 2 并行批新建，GREEN 前已存在）；
  把 run_summary_background_refresh(...) 协程交给 spawn（key 形态为父侧实现
  细节，本批不断言 key）

RED 预期: 模块不存在 → 收集期 ModuleNotFoundError（exit 2, collected 0 items /
1 error）；GREEN 后本文件全绿。
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.semantic_summary import SemanticSummary, SummaryScope
from inkflow.domain.ports.semantic_summary_errors import SemanticSummaryError
from inkflow.infrastructure.context import summary_background_refresh

run_summary_background_refresh = summary_background_refresh.run_summary_background_refresh
schedule_summary_background_refresh = (
    summary_background_refresh.schedule_summary_background_refresh
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

PROJECT_ID = uuid.UUID(int=100)


def _summary(
    content, *, scope="project", project_id=None, anchor_hash="anchor-hash",
    anchor_count=3, **kw
):
    """构造语义总结领域实体（模块已实现，直接构造）. """
    values = {
        "id": str(uuid.uuid4()),
        "scope": SummaryScope.PROJECT if scope == "project" else SummaryScope.USER,
        "project_id": project_id,
        "content": content,
        "anchor_hash": anchor_hash,
        "anchor_count": anchor_count,
        "model": "deepseek/deepseek-v4-flash",
        "created_at": datetime(2026, 8, 18, tzinfo=UTC),
        "updated_at": datetime(2026, 8, 18, tzinfo=UTC),
    }
    values.update(kw)
    return SemanticSummary(**values)


def _arg(call, name: str, index: int, default=None):
    """宽松取参：位置或关键字（规则 1o 同款，兼容两种 GREEN 传参形态）."""
    args, kwargs = call.await_args
    return args[index] if len(args) > index else kwargs.get(name, default)


class _FakeSessionFactory:
    """async 上下文管理器（可多次进入；内部 session 为假对象——注入 fakes 后不被使用）."""

    def __init__(self) -> None:
        self.enters = 0

    async def __aenter__(self):
        self.enters += 1
        return SimpleNamespace()  # 假 session（注入 fakes 后不被真正使用）

    async def __aexit__(self, *exc_info) -> bool:
        return False


class TestRunSummaryBackgroundRefresh:
    """run_summary_background_refresh 后台刷新任务体契约（全 mock 轨注入）."""

    async def test_success_upserts_and_audits_generated(self):
        """① 成功: summarize → (new_summary, []) → upsert(new_summary) + audit
        semantic_summary_generated（project_id 透传, degraded=True, actor="memory"）
        + 返回 True（GREEN 后: 独立 session 内完成，不依赖请求 session）."""
        factory = _FakeSessionFactory()
        summarizer = AsyncMock()
        new_summary = _summary("叙述偏好：用角色全名而非代词", project_id=PROJECT_ID)
        summarizer.summarize.return_value = (new_summary, [])
        summary_repo = AsyncMock()
        audit = AsyncMock()
        anchors = [SimpleNamespace(value="林晚")]

        ok = await run_summary_background_refresh(
            anchors, scope=SummaryScope.PROJECT, project_id=PROJECT_ID,
            anchor_hash="hash-1", session_factory=factory,
            summarizer=summarizer, summary_repo=summary_repo, audit=audit,
        )

        assert ok is True  # RED: 模块不存在 → 收集期 ModuleNotFoundError
        summarizer.summarize.assert_awaited_once()
        scope = _arg(summarizer.summarize, "scope", 1)
        assert getattr(scope, "value", scope) == "project"
        assert _arg(summarizer.summarize, "project_id", 2) == PROJECT_ID
        assert _arg(summarizer.summarize, "anchor_hash", 3) == "hash-1"
        assert factory.enters >= 1  # 自持 session（async with 进入）
        summary_repo.upsert.assert_awaited_once_with(new_summary)
        audit.record.assert_awaited_once_with(
            project_id=PROJECT_ID, severity_summary="semantic_summary_generated",
            degraded=True, actor="memory",
        )

    async def test_dropped_no_upsert_audits_failed(self):
        """② 防幻觉丢弃: summarize → (None, ["x"])（dropped truthy）→ 不 upsert +
        audit semantic_summary_failed（note 含 dropped 内容）+ 返回 False（丢弃
        留痕不阻断，spec §5.3.1）."""
        factory = _FakeSessionFactory()
        summarizer = AsyncMock()
        summarizer.summarize.return_value = (None, ["x"])
        summary_repo = AsyncMock()
        audit = AsyncMock()

        ok = await run_summary_background_refresh(
            [SimpleNamespace(value="林晚")], scope=SummaryScope.PROJECT,
            project_id=PROJECT_ID, anchor_hash="hash-1", session_factory=factory,
            summarizer=summarizer, summary_repo=summary_repo, audit=audit,
        )

        assert ok is False  # RED: 模块不存在 → 收集期 ModuleNotFoundError
        summary_repo.upsert.assert_not_awaited()
        audit.record.assert_awaited_once()
        assert _arg(audit.record, "project_id", 0) == PROJECT_ID
        assert _arg(audit.record, "severity_summary", 1) == "semantic_summary_failed"
        assert _arg(audit.record, "degraded", 2) is True
        assert _arg(audit.record, "actor", 3) == "memory"
        assert "x" in str(_arg(audit.record, "note", 4))  # note 含 dropped

    async def test_semantic_summary_error_not_raised(self):
        """③ LLM 失败（SemanticSummaryError）→ 不抛给调用方 + audit failed +
        返回 False（后台任务异常不逃逸；回退旧总结由 collect 层负责）."""
        factory = _FakeSessionFactory()
        summarizer = AsyncMock()
        summarizer.summarize.side_effect = SemanticSummaryError("LLM 总结失败")
        summary_repo = AsyncMock()
        audit = AsyncMock()

        ok = await run_summary_background_refresh(  # 不抛（若抛出本用例 ERROR）
            [SimpleNamespace(value="林晚")], scope=SummaryScope.PROJECT,
            project_id=PROJECT_ID, anchor_hash="hash-1", session_factory=factory,
            summarizer=summarizer, summary_repo=summary_repo, audit=audit,
        )

        assert ok is False  # RED: 模块不存在 → 收集期 ModuleNotFoundError
        summary_repo.upsert.assert_not_awaited()
        audit.record.assert_awaited_once()
        assert _arg(audit.record, "severity_summary", 1) == "semantic_summary_failed"

    async def test_unexpected_exception_not_raised(self):
        """④ 未预期异常（RuntimeError）→ 不抛 + audit failed + 返回 False（后台
        任务绝不能因异常炸掉调度器，语义同 F28 异常静默旁路）."""
        factory = _FakeSessionFactory()
        summarizer = AsyncMock()
        summarizer.summarize.side_effect = RuntimeError("boom")
        summary_repo = AsyncMock()
        audit = AsyncMock()

        ok = await run_summary_background_refresh(
            [SimpleNamespace(value="林晚")], scope=SummaryScope.PROJECT,
            project_id=PROJECT_ID, anchor_hash="hash-1", session_factory=factory,
            summarizer=summarizer, summary_repo=summary_repo, audit=audit,
        )

        assert ok is False  # RED: 模块不存在 → 收集期 ModuleNotFoundError
        summary_repo.upsert.assert_not_awaited()
        audit.record.assert_awaited_once()
        assert _arg(audit.record, "severity_summary", 1) == "semantic_summary_failed"


class TestScheduleSummaryBackgroundRefresh:
    """schedule_summary_background_refresh fire-and-forget 调度契约."""

    async def test_schedule_spawns_unawaited_coroutine(self, monkeypatch):
        """⑤ fire-and-forget: await schedule 立即返回（不阻塞）→ spawn 收到
        coroutine 且未被 await（调度不等待任务完成）；run 可跑完性由用例 ①-④
        （注入 fakes）证明——本用例不手动 await 捕获协程（真实装配会触真实
        DB/LLM），断言 cr_frame/cr_await 后 close 防 never-awaited 警告."""
        from inkflow.infrastructure.background import tasks as background_tasks

        captured: list = []

        def _fake_spawn(coro, *, key=None):
            captured.append(coro)
            return coro

        monkeypatch.setattr(background_tasks, "spawn_background_task", _fake_spawn)

        result = await schedule_summary_background_refresh(
            [SimpleNamespace(value="林晚")], scope=SummaryScope.PROJECT,
            project_id=PROJECT_ID, anchor_hash="hash-1",
        )

        assert result is None  # RED: 模块不存在 → 收集期 ModuleNotFoundError
        assert len(captured) == 1
        assert inspect.iscoroutine(captured[0])
        assert not captured[0].cr_running  # 未被驱动
        assert captured[0].cr_frame is not None  # 未运行到完成（调度未等待）
        captured[0].close()  # 防 "coroutine was never awaited" RuntimeWarning
