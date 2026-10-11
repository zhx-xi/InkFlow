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
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
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
from inkflow.domain.models.timeline import (
    PendingTimelineEvent,
    TimelineEvent,
    TimelineExtractionResult,
)
from inkflow.domain.models.world import WorldExtractionResult, WorldSetting
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.extraction_errors import ExtractionRunError, ExtractionValidationError
from inkflow.domain.services.extraction_service import ExtractionService
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.character_repo import SQLiteCharacterRepository
from inkflow.infrastructure.database.repositories.timeline_repo import SQLiteTimelineRepository

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
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


def _pending_result(reason: str = "相对时间，需作者锚定") -> TimelineExtractionResult:
    """构造「1 条未定条目」的时间线管线结果（门面分流用）。"""
    event = TimelineEvent(
        id=uuid.uuid4(),
        project_id=PID,
        title="未定事件",
        time_display="过了两天",
        time_value=None,
        narrative_position=1,
        created_at=NOW,
        updated_at=NOW,
    )
    return TimelineExtractionResult(
        created=[],
        updated=[],
        warnings=[],
        model="openai/gpt-4o",
        pending=[PendingTimelineEvent(event=event, reason=reason)],
    )


class TestPendingTimelineStaging1581:
    """#1581：非 stage 路径下，时间线「未定」条目由门面落暂存（待确认区数据源）。"""

    async def test_non_stage_pending_is_staged_with_reason(self, svc) -> None:
        """pending → 落暂存（entity_type=timeline_event，payload 含 parse_reason）。"""
        svc._timeline_extractor.extract = AsyncMock(return_value=_pending_result())
        svc._staging_repo.add_many.reset_mock()

        await svc.extract(
            ExtractionRequest(
                project_id=PID,
                type=ExtractionType.TIMELINE,
                chapter_ids=[CID],
                auto_extract=True,
            )
        )

        entries = svc._staging_repo.add_many.await_args.args[-1]
        assert len(entries) == 1
        assert entries[0].entity_type == "timeline_event"
        assert entries[0].action == "create"
        assert entries[0].name == "未定事件"
        assert entries[0].payload["parse_reason"] == "相对时间，需作者锚定"
        assert entries[0].payload["time_display"] == "过了两天"

    async def test_non_stage_pending_without_staging_repo_is_visible(self, svc) -> None:
        """暂存仓储未装配 → 记 warning（不静默丢弃）。"""
        svc._timeline_extractor.extract = AsyncMock(return_value=_pending_result())
        svc._staging_repo = None

        result = await svc.extract(
            ExtractionRequest(
                project_id=PID,
                type=ExtractionType.TIMELINE,
                chapter_ids=[CID],
                auto_extract=True,
            )
        )

        assert any("暂存仓储未装配" in w for w in result.warnings)


# ── #1586：条目级确认返回的 event_id 必须能回读 ─────────────────────────


@pytest.fixture
async def sqlite_session():
    """独立 in-memory SQLite（真仓储用；同 test_extract_rollback_service_1485 fixture 惯例）."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def staged_env(sqlite_session):
    """真仓储（timeline / character）+ 桩暂存仓储的确认环境（#1586）.

    物化目标必须是**真仓储** —— 各实体仓储 `add()` 的主键由 DB 自增分配，
    读回时映射为 `uuid.UUID(int=orm.id)`；桩对象直接回传入参实体会掩盖真身份。
    """
    project = ProjectORM(name="条目确认回读项目")
    sqlite_session.add(project)
    await sqlite_session.commit()
    await sqlite_session.refresh(project)

    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=_project())
    staging_repo = MagicMock()
    staging_repo.list_by_batch = AsyncMock(return_value=[])
    staging_repo.delete_by_id = AsyncMock(return_value=1)
    timeline_repo = SQLiteTimelineRepository(sqlite_session)
    character_repo = SQLiteCharacterRepository(sqlite_session)
    svc = ExtractionService(
        project_repo=project_repo,
        chapter_repo=MagicMock(),
        run_repo=MagicMock(),
        character_service=MagicMock(),
        world_service=MagicMock(),
        outline_service=MagicMock(),
        timeline_service=MagicMock(),
        foreshadowing_extractor=MagicMock(),
        timeline_extractor=MagicMock(),
        style_service=MagicMock(),
        character_repo=character_repo,
        timeline_repo=timeline_repo,
        staging_repo=staging_repo,
    )
    return SimpleNamespace(
        svc=svc,
        pid=uuid.UUID(int=project.id),
        staging_repo=staging_repo,
        timeline_repo=timeline_repo,
        character_repo=character_repo,
    )


class TestConfirmStagedItemEventIdReadback1586:
    """#1586：确认单条暂存返回的 `event_id` 必须是**物化后**可回读的真身份。"""

    async def test_timeline_item_confirm_returns_readable_event_id(self, staged_env) -> None:
        """时间线条目：payload 里的 `id` 与主键无关 → 返回物化后真身份才可回读."""
        payload_id = "6fae87cb-d68d-46c4-bf4c-7b437c28c4f5"
        staged_env.staging_repo.list_by_batch.return_value = [
            StagedEntry(
                id=7,
                entity_type="timeline_event",
                action="create",
                name="未定事件",
                payload={
                    "id": payload_id,
                    "project_id": str(staged_env.pid),
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
                },
            )
        ]

        out = await staged_env.svc.confirm_staged_item(
            staged_env.pid, "ext-1", 7, time_value=9.0, time_unit="日"
        )

        assert out["item_id"] == 7
        event = await staged_env.timeline_repo.get(uuid.UUID(out["event_id"]))
        assert event is not None, "返回的 event_id 必须能在正式表回读（#1586）"
        assert event.time_value == 9.0
        assert event.time_unit == "日"
        assert event.time_display == "那年冬天"

    async def test_character_item_confirm_returns_readable_event_id(self, staged_env) -> None:
        """角色条目：修法对全部分派类型生效（不是只修时间线）."""
        staged_env.staging_repo.list_by_batch.return_value = [
            StagedEntry(
                id=3,
                entity_type="character",
                action="create",
                name="角色甲",
                payload={
                    "id": str(uuid.uuid4()),
                    "project_id": str(staged_env.pid),
                    "name": "角色甲",
                    "created_at": NOW.isoformat(),
                    "updated_at": NOW.isoformat(),
                },
            )
        ]

        out = await staged_env.svc.confirm_staged_item(
            staged_env.pid, "ext-2", 3, time_value=1.0, time_unit="日"
        )

        assert out["item_id"] == 3
        character = await staged_env.character_repo.get(uuid.UUID(out["event_id"]))
        assert character is not None, "返回的 event_id 必须能在正式表回读（#1586）"
        assert character.name == "角色甲"
