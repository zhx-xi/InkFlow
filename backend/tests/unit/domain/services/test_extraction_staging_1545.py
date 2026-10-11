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
    StagedListResult,
    StagingBatch,
)
from inkflow.domain.models.world import WorldExtractionResult, WorldSetting
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ExtractionRunError, ExtractionValidationError
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
    # #1581：批次列表 + 条目级丢弃
    staging_repo.list_batches = AsyncMock(return_value=[])
    staging_repo.delete_by_id = AsyncMock(return_value=1)
    # #1581：条目级确认的物化目标（timeline_event → 时间线仓储）
    timeline_repo = MagicMock()
    timeline_repo.add = AsyncMock(side_effect=lambda e: e)
    timeline_repo.update = AsyncMock(side_effect=lambda e: e)
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
        timeline_repo=timeline_repo,
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

    async def test_stage_rejected_for_type_without_materialization_target(self, svc) -> None:
        """#1545 PR-2b 迁移：stage 现覆盖全部「有档案实体产物」的类型
        （character/setting/foreshadowing/timeline/knowledge_relation）；
        outline / style 无实体产物 → 仍 422。"""
        with pytest.raises(ExtractionValidationError):
            await svc.extract(
                ExtractionRequest(project_id=PID, type=ExtractionType.STYLE, text="t", stage=True)
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


class TestListStaged:
    """``list_staged``：读取本批暂存条目（前端结果视图数据源）。"""

    async def test_list_staged_returns_items(self, svc) -> None:
        svc._staging_repo.list_by_batch = AsyncMock(
            return_value=[
                StagedEntry(
                    entity_type="character",
                    action="create",
                    name="角色甲",
                    payload={"name": "角色甲"},
                )
            ]
        )
        out = await svc.list_staged(PID, "ext-1")

        assert isinstance(out, StagedListResult)
        assert out.batch_id == "ext-1"
        assert out.items[0].name == "角色甲"
        svc._staging_repo.list_by_batch.assert_awaited_once()


class TestStagingItemOps1581:
    """#1581：暂存批次列表 + 条目级确认 / 丢弃（待确认区数据面与动作面）。"""

    @staticmethod
    def _timeline_payload() -> dict[str, object]:
        """未定时间的时间线事件 payload（含 `parse_reason`；物化时被 Pydantic 忽略）。"""
        return {
            "id": str(uuid.uuid4()),
            "project_id": str(PID),
            "title": "未定事件",
            "description": "",
            "time_value": None,
            "time_unit": "",
            "time_display": "那年冬天",
            "narrative_position": 1,
            "timeline_flag": "",
            "parse_reason": "无绝对时间量（相对 / 模糊表达）",
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
        }

    async def test_list_staging_batches_returns_aggregate(self, svc) -> None:
        """批次列表 → StagingBatchList（契约冻结形状的数据面）。"""
        svc._staging_repo.list_batches.return_value = [
            StagingBatch(batch_id="ext-1", type="timeline", created_at=NOW, item_count=3)
        ]

        out = await svc.list_staging_batches(PID)

        assert [b.batch_id for b in out.batches] == ["ext-1"]
        assert out.batches[0].item_count == 3
        svc._staging_repo.list_batches.assert_awaited_once_with(PID)

    async def test_list_staging_batches_project_not_found(self, svc) -> None:
        """项目不存在 → ProjectNotFoundError（同 rollback 口径）。"""
        svc._project_repo.get.return_value = None

        with pytest.raises(ProjectNotFoundError):
            await svc.list_staging_batches(PID)

    async def test_confirm_item_overrides_time_then_deletes_row(self, svc) -> None:
        """条目确认：以给定时间覆盖 payload → 走既有物化路径 → 删该行（其余行不动）。"""
        svc._staging_repo.list_by_batch.return_value = [
            StagedEntry(
                id=7,
                entity_type="timeline_event",
                action="create",
                name="未定事件",
                payload=self._timeline_payload(),
            )
        ]

        out = await svc.confirm_staged_item(PID, "ext-1", 7, time_value=5.0, time_unit="日")

        assert out["item_id"] == 7
        added = svc._timeline_repo.add.await_args.args[0]
        assert added.title == "未定事件"
        assert (added.time_value, added.time_unit) == (5.0, "日")
        assert added.time_display == "那年冬天"  # 原文保留
        svc._staging_repo.delete_by_id.assert_awaited_once_with(PID, "ext-1", 7)

    async def test_confirm_item_missing_raises(self, svc) -> None:
        """条目不存在 → ExtractionRunError（不静默）。"""
        svc._staging_repo.list_by_batch.return_value = []

        with pytest.raises(ExtractionRunError):
            await svc.confirm_staged_item(PID, "ext-1", 404, time_value=1.0)

    async def test_discard_item_deletes_row_without_materializing(self, svc) -> None:
        """条目丢弃：只删该行，零物化（幂等：不存在 → deleted=0）。"""
        svc._staging_repo.delete_by_id.return_value = 0

        out = await svc.discard_staged_item(PID, "ext-1", 9)

        assert out == {"deleted": 0}
        svc._timeline_repo.add.assert_not_awaited()
        svc._staging_repo.delete_by_id.assert_awaited_once_with(PID, "ext-1", 9)
