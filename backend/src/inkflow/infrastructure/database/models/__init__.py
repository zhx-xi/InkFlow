"""SQLAlchemy ORM 模型 — import 触发 Base.metadata 注册."""

from inkflow.infrastructure.database.models.agent import AgentExecutionORM, AgentStageResultORM
from inkflow.infrastructure.database.models.chapter import ChapterORM, VolumeORM
from inkflow.infrastructure.database.models.character import (
    CharacterGroupORM,
    CharacterORM,
    CharacterRelationORM,
)
from inkflow.infrastructure.database.models.context import ChapterSummaryORM
from inkflow.infrastructure.database.models.outline import (
    OutlineORM,
    PlotPointORM,
    StoryArcORM,
)
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.timeline import TimelineEventORM
from inkflow.infrastructure.database.models.world import WorldSettingORM

__all__ = [
    "ProjectORM",
    "VolumeORM",
    "ChapterORM",
    "AgentExecutionORM",
    "AgentStageResultORM",
    "ChapterSummaryORM",
    "CharacterORM",
    "CharacterGroupORM",
    "CharacterRelationORM",
    "WorldSettingORM",
    "OutlineORM",
    "PlotPointORM",
    "StoryArcORM",
    "TimelineEventORM",
]
