"""#1545 提取两段式暂存 — 门面契约（RED）。

被测（GREEN 才实现）:
- ``ExtractionRequest.stage`` 字段（默认 False）
- ``ExtractionService.extract(stage=True)``：character/setting 走零写入（管线以
  ``dry_run=True`` 调用，且不写 run 表），结果落暂存仓储（``staging_repo.add_many``），
  信封回 ``batch_id``
- ``_validate_input``：非 character/setting 带 ``stage`` → 422（ExtractionValidationError）
- ``confirm_staged``：按 action 物化（create→repo.add / update→repo.update），随后清暂存
- ``cancel_staged``：仅清暂存，零物化

依据: specs/f14-extraction/spec.md §5.9（#1545）。

RED 预期: ``ExtractionRequest(stage=True)`` 字段被静默丢弃 → AttributeError；
``svc.confirm_staged`` / ``svc.cancel_staged`` / ``svc._staging_repo`` 不存在 → AttributeError。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.character import Character, CharacterExtractionResult
from inkflow.domain.models.extraction import (
    CancelStagedResult,
    ConfirmStagedResult,
    ExtractionRequest,
    ExtractionType,
    StagedEntry,
)
from inkflow.domain.models.world import WorldExtractionResult, WorldSetting
from inkflow.domain.ports.extraction_errors import ExtractionValidationError
from inkflow.domain.services.extraction_service import ExtractionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 9, tzinfo=UTC)


def _project() -> MagicMock:
    """项目替身（门面只需 config.model）。"""
    project = MagicMock()
    project.config.model = "openai/gpt-4o"
    return project


def _char(name: str) -> Character:
    return Character(id=uuid.uuid4(), project_id=PID, name=name, created_at=NOW, updated_at=NOW)


def _world(name: str) -> WorldSetting:
    return WorldSetting(id=uuid.uuid4(), project_id=PID, name=name, created_at=NOW, updated_at=NOW)


def _char_result() -> CharacterExtractionResult:
    """1 新建 + 1 更新（供暂存行数与 action 断言）。"""
    return CharacterExtractionResult(
        created=[_char("角色甲")],
        updated=[_char("角色乙")],
        relations_created=[],
        relations_updated=[],
        warnings=[],
        model="openai/gpt-4o",
    )


@pytest.fixture
def svc() -> ExtractionService:
    """全 Mock 依赖的 ExtractionService（含 staging_repo）。"""
    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=_project())
    run_repo = MagicMock()
    run_repo.get = AsyncMock(return_value=None)
    run_repo.upsert = AsyncMock()
    chapter_repo = MagicMock()
    chapter_repo.get_chapter = AsyncMock(
        side_effect=lambda cid: SimpleNamespace(
            project_id=PID, content=f"正文-{cid}", title=f"章-{cid}"
        )
    )
    character_service = MagicMock()
    character_service.extract = AsyncMock(return_value=_char_result())
    world_service = MagicMock()
    world_service.extract = AsyncMock(
        return_value=WorldExtractionResult(
            created=[], updated=[], warnings=[], model="openai/gpt-4o"
        )
    )
    character_repo = MagicMock()
    character_repo.add = AsyncMock(side_effect=lambda c: c)
    character_repo.update = AsyncMock(side_effect=lambda c: c)
    world_repo = MagicMock()
    world_repo.add = AsyncMock(side_effect=lambda w: w)
    world_repo.update = AsyncMock(side_effect=lambda w: w)
    staging_repo = MagicMock()
    staging_repo.add_many = AsyncMock(return_value=2)
    staging_repo.list_by_batch = AsyncMock(return_value=[])
    staging_repo.delete_by_batch = AsyncMock(return_value=2)
    return ExtractionService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        run_repo=run_repo,
        character_service=character_service,
        world_service=world_service,
        outline_service=MagicMock(),
        timeline_service=MagicMock(),
        foreshadowing_extractor=MagicMock(),
        timeline_extractor=MagicMock(),
        style_service=MagicMock(),
        character_repo=character_repo,
        world_repo=world_repo,
        staging_repo=staging_repo,
    )


class TestStageDto:
    """DTO：``stage`` 字段必须存在且默认向后兼容。"""

    def test_stage_default_false(self) -> None:
        req = ExtractionRequest(project_id=PID, type=ExtractionType.CHARACTER, text="t")
        assert req.stage is False

    def test_stage_accepted(self) -> None:
        req = ExtractionRequest(project_id=PID, type=ExtractionType.CHARACTER, text="t", stage=True)
        assert req.stage is True


class TestStageExtract:
    """``stage=True`` 提取：零写入 + 落暂存 + 回批次。"""

    async def test_character_stage_zero_write_and_persists_staging(self, svc) -> None:
        result = await svc.extract(
            ExtractionRequest(project_id=PID, type=ExtractionType.CHARACTER, text="t", stage=True)
        )
        # 零写入：管线以 dry_run=True 调用
        assert svc._character_service.extract.await_args.kwargs["dry_run"] is True
        # 预览语义：不写 run 表
        svc._run_repo.upsert.assert_not_awaited()
        # 信封回批次
        assert result.batch_id and result.batch_id.startswith("ext-")
        # 落暂存（1 created + 1 updated = 2 行）
        svc._staging_repo.add_many.assert_awaited_once()
        entries = svc._staging_repo.add_many.await_args.args[-1]
        assert len(entries) == 2
        assert sorted(e.action for e in entries) == ["create", "update"]

    async def test_stage_rejected_for_non_character_setting(self, svc) -> None:
        with pytest.raises(ExtractionValidationError):
            await svc.extract(
                ExtractionRequest(
                    project_id=PID, type=ExtractionType.FORESHADOWING, text="t", stage=True
                )
            )


class TestConfirmStaged:
    """``confirm_staged``：按 action 物化后清暂存。"""

    async def test_confirm_materializes_then_clears(self, svc) -> None:
        svc._staging_repo.list_by_batch = AsyncMock(
            return_value=[
                StagedEntry(
                    entity_type="character",
                    action="create",
                    name="角色甲",
                    payload=_char("角色甲").model_dump(mode="json"),
                ),
                StagedEntry(
                    entity_type="character",
                    action="update",
                    name="角色乙",
                    payload=_char("角色乙").model_dump(mode="json"),
                ),
            ]
        )
        out = await svc.confirm_staged(PID, "ext-1")

        assert isinstance(out, ConfirmStagedResult)
        assert out.batch_id == "ext-1"
        assert (out.created, out.updated) == (1, 1)
        svc._character_repo.add.assert_awaited_once()
        svc._character_repo.update.assert_awaited_once()
        svc._staging_repo.delete_by_batch.assert_awaited_once()


class TestCancelStaged:
    """``cancel_staged``：只清暂存，零物化。"""

    async def test_cancel_clears_without_materializing(self, svc) -> None:
        out = await svc.cancel_staged(PID, "ext-1")

        assert isinstance(out, CancelStagedResult)
        assert out.batch_id == "ext-1"
        assert out.deleted == 2
        svc._character_repo.add.assert_not_awaited()
        svc._character_repo.update.assert_not_awaited()
        svc._staging_repo.delete_by_batch.assert_awaited_once()
