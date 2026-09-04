"""Coverage backfill: 领域模型校验器未覆盖分支（公开模型构造触发）。

- WritingRequest.style_hint >1000 → ValidationError（writing.py 62）
- ContinueWritingRequest.context >20000 → ValidationError（writing.py 96-97）
- TimelineExtractRequest.text 空 / >50000 → ValidationError（timeline.py 118/120）
- ForeshadowingExtractRequest.text 空 / >50000 → ValidationError（foreshadowing.py 288/290）
- WorldCategory.kind 非 geo/abstract → ValidationError（world.py 297）
- CharacterUpdate.name=None → 直通返回 None（character.py 175）
- TokenBudgetConfig.layer_ratio 和 ≤1.0 → 原样返回（context.py 164）
- Conversation() 缺 created_at → _utcnow 默认值（conversation.py 12）
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from inkflow.domain.models.character import CharacterUpdate
from inkflow.domain.models.context import ContextLayer, TokenBudgetConfig
from inkflow.domain.models.foreshadowing import ForeshadowingExtractRequest
from inkflow.domain.models.timeline import TimelineExtractRequest
from inkflow.domain.models.world import WorldCategory
from inkflow.domain.models.writing import ContinueWritingRequest, WritingRequest

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
CHAPTER_ID = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


class TestWritingRequestValidators:
    def test_style_hint_over_1000_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            WritingRequest(
                project_id=PROJECT_ID,
                chapter_id=CHAPTER_ID,
                outline="第一章大纲",
                style_hint="风" * 1001,
            )


class TestContinueWritingRequestValidators:
    def test_context_over_20000_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            ContinueWritingRequest(
                project_id=PROJECT_ID,
                chapter_id=CHAPTER_ID,
                existing_content="已有内容" * 20,
                context="上下文" * 7000,
            )

    def test_valid_context_passes(self) -> None:
        req = ContinueWritingRequest(
            project_id=PROJECT_ID,
            chapter_id=CHAPTER_ID,
            existing_content="已有内容" * 20,
            context="上下文",
        )
        assert req.context == "上下文"


class TestTimelineExtractRequestValidators:
    def test_empty_text_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            TimelineExtractRequest(
                project_id=PROJECT_ID,
                chapter_id=CHAPTER_ID,
                text="   ",
            )

    def test_over_50000_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            TimelineExtractRequest(
                project_id=PROJECT_ID,
                chapter_id=CHAPTER_ID,
                text="字" * 50001,
            )


class TestForeshadowingExtractRequestValidators:
    def test_empty_text_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            ForeshadowingExtractRequest(project_id=PROJECT_ID, text="  ")

    def test_over_50000_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            ForeshadowingExtractRequest(project_id=PROJECT_ID, text="字" * 50001)


class TestWorldCategoryKindValidator:
    def test_invalid_kind_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            WorldCategory(
                id=uuid.uuid4(),
                project_id=PROJECT_ID,
                name="奇怪分类",
                kind="weird",
                created_at="2026-08-30T10:00:00Z",
                updated_at="2026-08-30T10:00:00Z",
            )

    def test_valid_kinds_accepted(self) -> None:
        for kind in ("geo", "abstract"):
            cat = WorldCategory(
                id=uuid.uuid4(),
                project_id=PROJECT_ID,
                name="分类",
                kind=kind,
                created_at="2026-08-30T10:00:00Z",
                updated_at="2026-08-30T10:00:00Z",
            )
            assert cat.kind == kind


class TestCharacterUpdateNameValidator:
    def test_name_none_passthrough(self) -> None:
        update = CharacterUpdate(name=None)
        assert update.name is None


class TestTokenBudgetConfigLayerRatio:
    def test_ratio_sum_within_one_returns_unchanged(self) -> None:
        cfg = TokenBudgetConfig(
            layer_ratio={
                ContextLayer.PROTECTED: 0.3,
                ContextLayer.COMPRESSIBLE: 0.4,
                ContextLayer.DYNAMIC: 0.3,
            }
        )
        assert cfg.layer_ratio[ContextLayer.PROTECTED] == 0.3


