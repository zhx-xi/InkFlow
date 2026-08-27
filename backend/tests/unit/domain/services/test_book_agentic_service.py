"""F49 (#551) BookService agentic 模式契约 — TDD RED 测试（追加段形态）。

被测契约（GREEN 才实现）:
    - BookService.write_book_agentic(plan_id, limits, config) -> dict
    - BookService.prepare_run(mode="agentic") 分支
    - BookRunRequest.mode Literal 扩展 "agentic"
    - AgenticBookConfig (domain/models/agent_book.py)

RED 预期
--------
- write_book_agentic 用例 → AttributeError（方法不存在）
- AgenticBookConfig 用例 → ImportError（模块不存在）
- BookRunRequest.mode="agentic" 用例 → Pydantic ValidationError（Literal 不含 agentic）

权威来源: specs/f49-autonomous-writing/spec.md §3/§5.4（装配契约：复用 F44 book run
骨架 + agentic_pipeline 委托）+ F44 §3/§13.4（后台任务 + prepare_run 预校验）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.asyncio


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _plan(**overrides):
    from inkflow.domain.models.writing_plan import WritingPlan

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


def _limits(**kw):
    from inkflow.domain.models.writing_plan import BookLimits

    return BookLimits(**kw)


def _make_service(agentic_pipeline=None, **overrides):
    """构造 BookService 全部 mock 依赖 + 注入 agentic_pipeline（GREEN 契约）。"""
    from inkflow.domain.services.book_service import BookService

    repo = AsyncMock()
    repo.get_writing_plan.return_value = None
    repo.update_writing_plan.return_value = None
    outline_repo = AsyncMock()
    outline_repo.list.return_value = ([], 0)
    fake_agent = AsyncMock()
    fake_agent.invoke.return_value = {
        "messages": [{"role": "assistant", "content": "章节正文" * 20}],
        "usage": {"total_tokens": 100},
    }
    writer_factory = AsyncMock(return_value=fake_agent)
    draft_service = AsyncMock()
    draft_service.create.return_value = SimpleNamespace(id="draft-1")

    kwargs = dict(
        repo=repo,
        outline_repo=outline_repo,
        writer_factory=writer_factory,
        draft_service=draft_service,
        content_checker=overrides.get("content_checker", AsyncMock(return_value=False)),
        project_config_getter=overrides.get("project_config_getter", AsyncMock(return_value=None)),
        execution_store=overrides.get("execution_store", AsyncMock()),
    )
    if agentic_pipeline is not None:
        kwargs["agentic_pipeline"] = agentic_pipeline
    return BookService(**kwargs)


class TestWriteBookAgentic:
    @pytest.mark.asyncio
    async def test_delegates_to_agentic_pipeline(self) -> None:
        """write_book_agentic 委托 agentic_pipeline.execute 并返回结果（§5.4）。"""
        plan = _plan(status="ready")
        pipeline = AsyncMock()
        pipeline.execute.return_value = {"run_id": str(plan.id), "status": "completed"}
        svc = _make_service(agentic_pipeline=pipeline)
        svc._repo.get_writing_plan.return_value = plan
        result = await svc.write_book_agentic(plan.id, _limits(max_chapters=5, max_agent_calls=50))
        pipeline.execute.assert_awaited_once()
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_prepare_run_mode_agentic(self) -> None:
        """prepare_run(mode="agentic") 预校验（计划存在 + run 载体 + running 落库）。"""
        plan = _plan(status="ready")
        svc = _make_service()
        svc._repo.get_writing_plan.return_value = plan
        result = await svc.prepare_run(plan.id, limits=None, mode="agentic")
        assert result["status"] == "running"
        svc._repo.update_writing_plan.assert_awaited()

    @pytest.mark.asyncio
    async def test_mode_agentic_no_pipeline_raises(self) -> None:
        """agentic 模式但 agentic_pipeline 未装配 → ValueError（防静默降级）。"""
        plan = _plan(status="ready")
        svc = _make_service(agentic_pipeline=None)
        svc._repo.get_writing_plan.return_value = plan
        with pytest.raises(ValueError):
            await svc.write_book_agentic(plan.id, _limits(max_chapters=5, max_agent_calls=50))


class TestAgenticBookConfig:
    @pytest.mark.asyncio
    async def test_defaults(self) -> None:
        """AgenticBookConfig 默认值（§2.2）。"""
        from inkflow.domain.models.agent_book import AgenticBookConfig

        cfg = AgenticBookConfig()
        assert cfg.max_steps == 100
        assert cfg.max_consecutive == 4
        assert cfg.max_chapter_cycles == 5
        assert cfg.audit_required is True

    @pytest.mark.asyncio
    async def test_validator_rejects_out_of_range(self) -> None:
        """AgenticBookConfig validator 越界拒绝（max_steps / max_chapter_cycles）。"""
        from inkflow.domain.models.agent_book import AgenticBookConfig

        with pytest.raises(ValidationError):
            AgenticBookConfig(max_steps=0)
        with pytest.raises(ValidationError):
            AgenticBookConfig(max_chapter_cycles=0)


class TestBookRunRequestMode:
    @pytest.mark.asyncio
    async def test_mode_accepts_agentic(self) -> None:
        """BookRunRequest.mode 接受 "agentic"（§3，向后兼容 static/volume）。"""
        from inkflow.api.routers.books import BookRunRequest

        req = BookRunRequest(writing_plan_id=uuid.uuid4(), mode="agentic")
        assert req.mode == "agentic"


class TestAgenticAuthorizationGate:
    """#598 全自动授权门禁契约（D9-a1：prepare_run mode=agentic 前置授权检查）。

    契约（放 prepare_run 同步预校验，与计划存在/护栏/安全阀同层）：
    - project_config_getter 返回 None（无项目 config）-> 放行（向后兼容 CLI/旧路径）
    - config 存在且 auto_write_enabled=True -> 放行（授权后）
    - config 存在且 auto_write_enabled=False -> ValueError（未授权拒绝）

    RED 预期：prepare_run(mode=agentic) 无授权检查 -> 未授权用例 pytest.raises
    DID NOT RAISE（干净断言 FAIL）；GREEN 后全部转绿。
    """

    async def test_prepare_run_agentic_unauthorized_raises(self) -> None:
        """config.auto_write_enabled=False（未授权）-> prepare_run(mode=agentic) 拒绝。"""
        from inkflow.domain.models.project import ProjectConfig

        plan = _plan(status="ready")
        svc = _make_service()
        svc._repo.get_writing_plan.return_value = plan
        svc._project_config_getter = AsyncMock(return_value=ProjectConfig(auto_write_enabled=False))
        with pytest.raises(ValueError):
            await svc.prepare_run(plan.id, limits=None, mode="agentic")

    async def test_prepare_run_agentic_authorized_passes(self) -> None:
        """config.auto_write_enabled=True（已授权）-> prepare_run(mode=agentic) 放行 running。"""
        from inkflow.domain.models.project import ProjectConfig

        plan = _plan(status="ready")
        svc = _make_service()
        svc._repo.get_writing_plan.return_value = plan
        svc._project_config_getter = AsyncMock(return_value=ProjectConfig(auto_write_enabled=True))
        result = await svc.prepare_run(plan.id, limits=None, mode="agentic")
        assert result["status"] == "running"

    async def test_prepare_run_agentic_no_config_passes(self) -> None:
        """project_config_getter 返回 None（无 config）-> 放行（向后兼容 CLI/旧路径）。"""
        plan = _plan(status="ready")
        svc = _make_service()
        svc._repo.get_writing_plan.return_value = plan
        svc._project_config_getter = AsyncMock(return_value=None)
        result = await svc.prepare_run(plan.id, limits=None, mode="agentic")
        assert result["status"] == "running"


class Test708BookRunMixinCoverageGaps:
    """#708 coverage 补测 — book_run_mixin 未覆盖分支。"""

    async def test_prepare_run_agentic_loops_over_multiple_chapters(self) -> None:
        """agentic 预校验多章节全未写 → 循环走完（74->75 / 75->74 / 75->76）。"""
        plan = _plan(status="ready")
        svc = _make_service()
        svc._repo.get_writing_plan.return_value = plan
        svc._outline_repo.list.return_value = (
            [
                SimpleNamespace(
                    id=uuid.uuid4(), level="chapter", sort_order=0, chapter_id=uuid.uuid4()
                ),
                SimpleNamespace(
                    id=uuid.uuid4(), level="chapter", sort_order=1, chapter_id=uuid.uuid4()
                ),
            ],
            2,
        )

        result = await svc.prepare_run(plan.id, limits=None, mode="agentic")

        assert result["status"] == "running"

    async def test_prepare_run_agentic_written_chapter_raises(self) -> None:
        """agentic 预校验命中已写章节 → ChapterAlreadyWrittenError（75->76 + L76）。"""
        from inkflow.domain.services.book_service import ChapterAlreadyWrittenError

        plan = _plan(status="ready")
        svc = _make_service(content_checker=AsyncMock(return_value=True))
        svc._repo.get_writing_plan.return_value = plan
        svc._outline_repo.list.return_value = (
            [
                SimpleNamespace(
                    id=uuid.uuid4(), level="chapter", sort_order=0, chapter_id=uuid.uuid4()
                ),
            ],
            1,
        )

        with pytest.raises(ChapterAlreadyWrittenError):
            await svc.prepare_run(plan.id, limits=None, mode="agentic")

    async def test_prepare_run_agentic_no_config_getter_passes(self) -> None:
        """project_config_getter=None → 授权检查直接放行（102->103）。"""
        plan = _plan(status="ready")
        svc = _make_service(project_config_getter=None)
        svc._repo.get_writing_plan.return_value = plan

        result = await svc.prepare_run(plan.id, limits=None, mode="agentic")

        assert result["status"] == "running"

    async def test_write_book_agentic_plan_missing_raises(self) -> None:
        """计划不存在 → ValueError（163->164）。"""
        svc = _make_service(agentic_pipeline=AsyncMock())
        svc._repo.get_writing_plan.return_value = None

        with pytest.raises(ValueError):
            await svc.write_book_agentic(_pid(), _limits(max_chapters=5, max_agent_calls=50))

    async def test_write_book_agentic_written_chapter_raises(self) -> None:
        """首个章节已写 → ChapterAlreadyWrittenError（169->170 True 分支）。"""
        from inkflow.domain.services.book_service import ChapterAlreadyWrittenError

        plan = _plan(status="ready")
        svc = _make_service(
            agentic_pipeline=AsyncMock(),
            content_checker=AsyncMock(return_value=True),
        )
        svc._repo.get_writing_plan.return_value = plan
        chapter = SimpleNamespace(
            id=uuid.uuid4(), level="chapter", sort_order=0, chapter_id=uuid.uuid4()
        )
        svc._outline_repo.list.return_value = ([chapter], 1)

        with pytest.raises(ChapterAlreadyWrittenError):
            await svc.write_book_agentic(plan.id, _limits(max_chapters=5, max_agent_calls=50))

    async def test_write_book_agentic_loops_all_chapters(self) -> None:
        """多章节全未写 → 循环回边 + 退出（170->169 / 170->171）并委托 pipeline。"""
        plan = _plan(status="ready")
        pipeline = AsyncMock()
        pipeline.execute.return_value = {"run_id": str(plan.id), "status": "completed"}
        svc = _make_service(agentic_pipeline=pipeline)
        svc._repo.get_writing_plan.return_value = plan
        svc._outline_repo.list.return_value = (
            [
                SimpleNamespace(
                    id=uuid.uuid4(), level="chapter", sort_order=0, chapter_id=uuid.uuid4()
                ),
                SimpleNamespace(
                    id=uuid.uuid4(), level="chapter", sort_order=1, chapter_id=uuid.uuid4()
                ),
            ],
            2,
        )

        result = await svc.write_book_agentic(plan.id, _limits(max_chapters=5, max_agent_calls=50))

        assert result["status"] == "completed"
        pipeline.execute.assert_awaited_once()
