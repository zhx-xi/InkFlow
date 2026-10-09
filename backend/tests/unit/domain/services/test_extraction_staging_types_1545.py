"""#1545 PR-2b 提取两段式暂存 — 其余三类型契约（RED）。

被测（GREEN 才实现）:
- ``_validate_input``：``stage=True`` 对 FORESHADOWING / TIMELINE / KNOWLEDGE_RELATION
  不再 422（PR-2a 仅放开 character/setting）
- ``extract(stage=True, type=FORESHADOWING)``：伏笔管线以 ``dry_run=True`` 调用（零写入），
  结果落暂存（``entity_type='foreshadowing'``）
- ``extract(stage=True, type=KNOWLEDGE_RELATION)``：关系写入被跳过，结果落暂存
  （``entity_type='knowledge_relation'``）
- ``confirm_staged``：按 ``entity_type`` 分派到对应仓储物化（伏笔 → ``foreshadowing_repo``）

依据: specs/f14-extraction/spec.md §5.9（#1545 PR-2b）。

RED 预期: ``stage=True`` 的非 character/setting 类型仍抛 ExtractionValidationError → FAIL。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.extraction import ExtractionRequest, ExtractionType
from inkflow.domain.models.foreshadowing import Foreshadowing, ForeshadowingExtractionResult
from inkflow.domain.services.extraction_service import ExtractionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 9, tzinfo=UTC)


def _project() -> MagicMock:
    project = MagicMock()
    project.config.model = "openai/gpt-4o"
    project.config.timeline_auto_extract = True
    return project


def _fs(title: str) -> Foreshadowing:
    return Foreshadowing(
        id=uuid.uuid4(), project_id=PID, title=title, created_at=NOW, updated_at=NOW
    )


def _fs_result() -> ForeshadowingExtractionResult:
    return ForeshadowingExtractionResult(
        created=[_fs("伏笔甲")], updated=[], warnings=[], model="openai/gpt-4o"
    )


@pytest.fixture
def svc() -> ExtractionService:
    """带 foreshadowing_repo 的 ExtractionService（PR-2b 门面测试）。"""
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
    foreshadowing_extractor = MagicMock()
    foreshadowing_extractor.extract = AsyncMock(return_value=_fs_result())
    foreshadowing_repo = MagicMock()
    foreshadowing_repo.add = AsyncMock(side_effect=lambda f: f)
    foreshadowing_repo.update = AsyncMock(side_effect=lambda f: f)
    staging_repo = MagicMock()
    staging_repo.add_many = AsyncMock(return_value=1)
    staging_repo.list_by_batch = AsyncMock(return_value=[])
    staging_repo.delete_by_batch = AsyncMock(return_value=1)
    return ExtractionService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        run_repo=run_repo,
        character_service=MagicMock(),
        world_service=MagicMock(),
        outline_service=MagicMock(),
        timeline_service=MagicMock(),
        foreshadowing_extractor=foreshadowing_extractor,
        timeline_extractor=MagicMock(),
        style_service=MagicMock(),
        foreshadowing_repo=foreshadowing_repo,
        staging_repo=staging_repo,
    )


class TestStageAllowsOtherTypes:
    """``stage`` 不再限于 character/setting。"""

    async def test_stage_foreshadowing_is_allowed_and_zero_write(self, svc) -> None:
        result = await svc.extract(
            ExtractionRequest(
                project_id=PID, type=ExtractionType.FORESHADOWING, text="t", stage=True
            )
        )
        # 零写入：管线以 dry_run=True 调用
        assert svc._foreshadowing_extractor.extract.await_args.kwargs["dry_run"] is True
        # 落暂存：entity_type = foreshadowing
        svc._staging_repo.add_many.assert_awaited_once()
        entries = svc._staging_repo.add_many.await_args.args[-1]
        assert [e.entity_type for e in entries] == ["foreshadowing"]
        assert result.batch_id and result.batch_id.startswith("ext-")

    async def test_stage_knowledge_relation_is_allowed(self, svc) -> None:
        """关系类型（项目级，无源参数）也支持 stage。"""
        result = await svc.extract(
            ExtractionRequest(project_id=PID, type=ExtractionType.KNOWLEDGE_RELATION, stage=True)
        )
        assert result.batch_id is not None


class TestConfirmDispatchesByEntityType:
    """``confirm_staged`` 按 entity_type 分派到对应仓储。"""

    async def test_confirm_foreshadowing_row_uses_foreshadowing_repo(self, svc) -> None:
        from inkflow.domain.models.extraction import StagedEntry

        svc._staging_repo.list_by_batch = AsyncMock(
            return_value=[
                StagedEntry(
                    entity_type="foreshadowing",
                    action="create",
                    name="伏笔甲",
                    payload=_fs("伏笔甲").model_dump(mode="json"),
                )
            ]
        )
        out = await svc.confirm_staged(PID, "ext-1")

        assert out.created == 1
        svc._foreshadowing_repo.add.assert_awaited_once()
        svc._staging_repo.delete_by_batch.assert_awaited_once()


class TestStageKnowledgeRelationStaging:
    """关系服务在线时：stage 产出 would-be 关系并落暂存（零落库）。"""

    async def test_stage_knowledge_relation_stages_would_be_relations(self) -> None:
        from inkflow.domain.models.knowledge_graph import KnowledgeRelationCreate
        from inkflow.domain.ports.vector_store import EntityType

        project_repo = MagicMock()
        project_repo.get = AsyncMock(return_value=_project())
        run_repo = MagicMock()
        run_repo.get = AsyncMock(return_value=None)
        run_repo.upsert = AsyncMock()

        relation_service = MagicMock()

        async def _rules(pid, candidates, warnings):  # 测试替身：签名对齐 extract_rules（公开入口）
            candidates.append(
                KnowledgeRelationCreate(
                    source_type=EntityType.CHARACTER,
                    source_id=str(uuid.uuid4()),
                    target_type=EntityType.CHARACTER,
                    target_id=str(uuid.uuid4()),
                    relation_type="师承",
                )
            )

        relation_service.extract_rules = _rules  # #1551：公开入口（原私有 _extract_rules）
        staging_repo = MagicMock()
        staging_repo.add_many = AsyncMock(return_value=1)
        staging_repo.list_by_batch = AsyncMock(return_value=[])
        staging_repo.delete_by_batch = AsyncMock(return_value=0)

        svc = ExtractionService(
            project_repo=project_repo,
            chapter_repo=MagicMock(),
            run_repo=run_repo,
            character_service=MagicMock(),
            world_service=MagicMock(),
            outline_service=MagicMock(),
            timeline_service=MagicMock(),
            foreshadowing_extractor=MagicMock(),
            timeline_extractor=MagicMock(),
            style_service=MagicMock(),
            relation_extraction_service=relation_service,
            staging_repo=staging_repo,
        )

        await svc.extract(
            ExtractionRequest(project_id=PID, type=ExtractionType.KNOWLEDGE_RELATION, stage=True)
        )

        staging_repo.add_many.assert_awaited_once()
        entries = staging_repo.add_many.await_args.args[-1]
        assert [e.entity_type for e in entries] == ["knowledge_relation"]
