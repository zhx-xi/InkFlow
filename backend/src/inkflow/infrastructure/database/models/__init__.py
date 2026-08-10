"""SQLAlchemy ORM 模型 — import 触发 Base.metadata 注册."""

from inkflow.infrastructure.database.models.agent import AgentExecutionORM, AgentStageResultORM
from inkflow.infrastructure.database.models.agent_run import AgentRunORM, DraftORM
from inkflow.infrastructure.database.models.audit_log import AuditLogORM
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM
from inkflow.infrastructure.database.models.character import (
    CharacterGroupORM,
    CharacterORM,
    CharacterRelationORM,
)
from inkflow.infrastructure.database.models.context import ChapterSummaryORM
from inkflow.infrastructure.database.models.extraction_run import ExtractionRunORM
from inkflow.infrastructure.database.models.foreshadowing import ForeshadowingORM
from inkflow.infrastructure.database.models.map import MapORM, MapPinORM
from inkflow.infrastructure.database.models.outline import (
    OutlineORM,
    PlotPointORM,
    StoryArcORM,
)
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.provider_config import ProviderConfigORM
from inkflow.infrastructure.database.models.session import SessionLogORM, SessionORM
from inkflow.infrastructure.database.models.settings import SettingsORM
from inkflow.infrastructure.database.models.timeline import TimelineEventORM
from inkflow.infrastructure.database.models.world import WorldSettingORM

__all__ = [
    "AgentExecutionORM",
    "AgentRunORM",
    "AgentStageResultORM",
    "AuditLogORM",
    "ChapterORM",
    "ChapterSummaryORM",
    "CharacterGroupORM",
    "CharacterORM",
    "CharacterRelationORM",
    "DraftORM",
    "ExtractionRunORM",
    "ForeshadowingORM",
    "MapORM",
    "MapPinORM",
    "OutlineORM",
    "PlotPointORM",
    "ProjectORM",
    "ProviderConfigORM",
    "SessionLogORM",
    "SessionORM",
    "SettingsORM",
    "StoryArcORM",
    "TimelineEventORM",
    "VolumeORM",
    "WorldSettingORM",
]
