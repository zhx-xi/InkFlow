"""Pydantic 领域模型."""

from inkflow.domain.models.agent_pipeline import (
    PipelineConfig,
    PipelineExecuteRequest,
    RoleOverride,
)
from inkflow.domain.models.chapter import (
    Chapter,
    ChapterCreate,
    ChapterStatus,
    ChapterUpdate,
    StatusHistoryEntry,
    Volume,
    VolumeCreate,
    VolumeUpdate,
)
from inkflow.domain.models.character import (
    Character,
    CharacterCreate,
    CharacterExtractionResult,
    CharacterExtractRequest,
    CharacterGroup,
    CharacterRelation,
    CharacterRelationCreate,
    CharacterUpdate,
    ExtractedCharacter,
    ExtractedRelation,
)
from inkflow.domain.models.context import (
    ChapterSummary,
    ContextAssemblyResult,
    ContextBlock,
    ContextItem,
    ContextLayer,
    ContextRequest,
    ContextSourceType,
    DroppedItem,
    TokenBudgetConfig,
)
from inkflow.domain.models.project import Project, ProjectConfig, ProjectCreate, ProjectUpdate
from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    FormatValidationResult,
    RevisionRequest,
    WritingMode,
    WritingRequest,
    WritingResult,
)

__all__ = [
    "PipelineConfig",
    "PipelineExecuteRequest",
    "RoleOverride",
    "Project",
    "ProjectConfig",
    "ProjectCreate",
    "ProjectUpdate",
    "Chapter",
    "ChapterCreate",
    "ChapterStatus",
    "ChapterUpdate",
    "StatusHistoryEntry",
    "Volume",
    "VolumeCreate",
    "VolumeUpdate",
    # ── character (F9) ──
    "Character",
    "CharacterCreate",
    "CharacterUpdate",
    "CharacterGroup",
    "CharacterRelation",
    "CharacterRelationCreate",
    "ExtractedCharacter",
    "ExtractedRelation",
    "CharacterExtractRequest",
    "CharacterExtractionResult",
    "WritingMode",
    "WritingRequest",
    "ContinueWritingRequest",
    "RevisionRequest",
    "WritingResult",
    "FormatValidationResult",
    # ── context (F6) ──
    "ContextLayer",
    "ContextSourceType",
    "ContextItem",
    "ContextBlock",
    "DroppedItem",
    "ChapterSummary",
    "TokenBudgetConfig",
    "ContextRequest",
    "ContextAssemblyResult",
]
