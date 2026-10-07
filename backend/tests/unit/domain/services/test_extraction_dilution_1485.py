"""#1485 统一提取门面契约（RED）— granularity/dry_run 透传 + batch_id + 整批回滚。

被测（GREEN 才实现）:
- ``ExtractionService.extract``：把 ``granularity`` / ``dry_run`` 透传给 character/setting
  管线；非 dry_run 生成并回显 ``batch_id``；dry_run 不写 run 表（§5.8.4/§5.8.5）
- ``ExtractionService.rollback_batch``：按 batch_id 整批删除（幂等，§5.8.5）
- ``_validate_input``：非 character/setting 类型带 granularity/dry_run → 422（§6.4）

依据: specs/f14-extraction/spec.md §5.8 + §6.4 + §7（#1485）。

RED 预期
- ``ExtractionRequest(dry_run=True)`` 的字段被静默丢弃 → ``req.dry_run`` AttributeError
- ``result.batch_id`` 不存在 → AttributeError
- ``svc.rollback_batch`` 不存在 → AttributeError
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.character import CharacterExtractionResult
from inkflow.domain.models.extraction import ExtractionRequest, ExtractionType
from inkflow.domain.models.foreshadowing import ForeshadowingExtractionResult
from inkflow.domain.models.world import WorldExtractionResult
from inkflow.domain.ports.extraction_errors import ExtractionValidationError
from inkflow.domain.services.extraction_service import ExtractionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


def _project() -> MagicMock:
    """项目替身（门面只需 config.model）。"""
    project = MagicMock()
    project.config.model = "openai/gpt-4o"
    return project


def _world_result() -> WorldExtractionResult:
    return WorldExtractionResult(created=[], updated=[], warnings=[], model="openai/gpt-4o")


def _char_result() -> CharacterExtractionResult:
    return CharacterExtractionResult(
        created=[],
        updated=[],
        relations_created=[],
        relations_updated=[],
        warnings=[],
        model="openai/gpt-4o",
    )


@pytest.fixture
def svc() -> ExtractionService:
    """全 Mock 依赖的 ExtractionService（门面编排测试）。"""
    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=_project())
    run_repo = MagicMock()
    run_repo.get = AsyncMock(return_value=None)
    run_repo.upsert = AsyncMock()
    # 章节替身：显式提供协程实现（真实仓储恒为协程；不依赖任何替身容错分支）
    chapter_repo = MagicMock()
    chapter_repo.get_chapter = AsyncMock(
        side_effect=lambda cid: SimpleNamespace(
            project_id=PID, content=f"正文-{cid}", title=f"章-{cid}"
        )
    )
    world_service = MagicMock()
    world_service.extract = AsyncMock(return_value=_world_result())
    character_service = MagicMock()
    character_service.extract = AsyncMock(return_value=_char_result())
    foreshadowing_extractor = MagicMock()
    foreshadowing_extractor.extract = AsyncMock(
        return_value=ForeshadowingExtractionResult(
            created=[], updated=[], warnings=[], model="openai/gpt-4o"
        )
    )
    return ExtractionService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        run_repo=run_repo,
        character_service=character_service,
        world_service=world_service,
        outline_service=MagicMock(),
        timeline_service=MagicMock(),
        foreshadowing_extractor=foreshadowing_extractor,
        timeline_extractor=MagicMock(),
        style_service=MagicMock(),
        world_repo=MagicMock(),
        character_repo=MagicMock(),
    )


class TestExtractionRequestContract:
    """DTO 层：新字段必须存在且默认向后兼容。"""

    def test_granularity_and_dry_run_defaults(self) -> None:
        """默认 fine / False（不改变既有调用语义）。"""
        req = ExtractionRequest(project_id=PID, type=ExtractionType.SETTING, text="t")
        assert req.granularity.value == "fine"
        assert req.dry_run is False

    def test_granularity_and_dry_run_accepted(self) -> None:
        """显式传值被接收（RED：字段不存在 → 被静默丢弃 → AttributeError）。"""
        req = ExtractionRequest(
            project_id=PID,
            type=ExtractionType.SETTING,
            text="t",
            granularity="coarse",
            dry_run=True,
        )
        assert req.granularity.value == "coarse"
        assert req.dry_run is True


class TestFacadePassthrough:
    """门面透传与批次回显。"""

    async def test_setting_receives_granularity_dry_run_batch_id(self, svc) -> None:
        """SETTING 管线收到 granularity/dry_run/batch_id 三个关键字参数。"""
        result = await svc.extract(
            ExtractionRequest(project_id=PID, type=ExtractionType.SETTING, text="t")
        )

        kwargs = svc._world_service.extract.await_args.kwargs
        assert kwargs["granularity"].value == "fine"
        assert kwargs["dry_run"] is False
        assert kwargs["batch_id"] == result.batch_id
        assert result.batch_id and result.batch_id.startswith("ext-")

    async def test_character_receives_same_kwargs(self, svc) -> None:
        """CHARACTER 管线同样收到三参数。"""
        result = await svc.extract(
            ExtractionRequest(project_id=PID, type=ExtractionType.CHARACTER, text="t")
        )

        kwargs = svc._character_service.extract.await_args.kwargs
        assert kwargs["granularity"].value == "fine"
        assert kwargs["dry_run"] is False
        assert kwargs["batch_id"] == result.batch_id

    async def test_batch_id_stable_across_sources(self, svc) -> None:
        """同一次 request 的多源共享同一 batch_id。"""
        await svc.extract(
            ExtractionRequest(
                project_id=PID,
                type=ExtractionType.SETTING,
                chapter_ids=[uuid.uuid4(), uuid.uuid4()],
            )
        )
        first, second = svc._world_service.extract.await_args_list
        assert first.kwargs["batch_id"] == second.kwargs["batch_id"]

    async def test_dry_run_skips_run_upsert(self, svc) -> None:
        """dry_run → run 表零写入且 batch_id 为 None（DB 零写入契约）。"""
        result = await svc.extract(
            ExtractionRequest(project_id=PID, type=ExtractionType.SETTING, text="t", dry_run=True)
        )

        assert svc._run_repo.upsert.await_count == 0
        assert result.batch_id is None
        assert svc._world_service.extract.await_args.kwargs["dry_run"] is True

    async def test_normal_run_writes_run_row(self, svc) -> None:
        """非 dry_run → run 表落一行（既有语义守护）。"""
        await svc.extract(ExtractionRequest(project_id=PID, type=ExtractionType.SETTING, text="t"))
        assert svc._run_repo.upsert.await_count == 1


class TestFacadeValidation:
    """§6.4：granularity / dry_run 仅 character/setting 生效。"""

    async def test_dry_run_on_foreshadowing_rejected(self, svc) -> None:
        """非 character/setting 类型传 dry_run → 422。"""
        with pytest.raises(ExtractionValidationError):
            await svc.extract(
                ExtractionRequest(
                    project_id=PID, type=ExtractionType.FORESHADOWING, text="t", dry_run=True
                )
            )

    async def test_coarse_on_outline_rejected(self, svc) -> None:
        """非 character/setting 类型传 granularity=coarse → 422。"""
        with pytest.raises(ExtractionValidationError):
            await svc.extract(
                ExtractionRequest(
                    project_id=PID,
                    type=ExtractionType.KNOWLEDGE_RELATION,
                    granularity="coarse",
                )
            )

    async def test_fine_and_no_dry_run_stay_backward_compatible(self, svc) -> None:
        """反向守护：默认值（fine / dry_run=False）对其他类型不报错。"""
        await svc.extract(
            ExtractionRequest(project_id=PID, type=ExtractionType.FORESHADOWING, text="t")
        )


class TestRollbackBatch:
    """§5.8.5 整批回滚。"""

    async def test_rollback_deletes_world_and_character_entries(self, svc) -> None:
        """回滚聚合两张表的删除计数。"""
        svc._world_repo.delete_by_batch = AsyncMock(return_value=2)
        svc._character_repo.delete_by_batch = AsyncMock(return_value=1)

        result = await svc.rollback_batch(PID, "ext-batch-1")

        assert result.batch_id == "ext-batch-1"
        assert result.deleted == 3
        assert svc._world_repo.delete_by_batch.await_args.args == (PID, "ext-batch-1")
        assert svc._character_repo.delete_by_batch.await_args.args == (PID, "ext-batch-1")

    async def test_rollback_is_idempotent(self, svc) -> None:
        """重复回滚 → deleted=0 且不报错。"""
        svc._world_repo.delete_by_batch = AsyncMock(return_value=0)
        svc._character_repo.delete_by_batch = AsyncMock(return_value=0)

        result = await svc.rollback_batch(PID, "ext-gone")

        assert result.deleted == 0

    async def test_rollback_warns_about_updated_entries(self, svc) -> None:
        """更新条目不回滚 → 返回 warning 提示（不静默）。"""
        svc._world_repo.delete_by_batch = AsyncMock(return_value=0)
        svc._character_repo.delete_by_batch = AsyncMock(return_value=0)

        result = await svc.rollback_batch(PID, "ext-batch-2")

        assert any("不可回滚" in w for w in result.warnings)
