"""#766 阶段②/③ chat agent 装配守卫辅助——会话读取 + agent 服务 getter（从 deps.py 迁出防超 900 行）.

deps.py 以 `from inkflow.api._chat_auth import ...` re-export，命名空间不变。
"""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.models.conversation import Conversation
from inkflow.infrastructure.database.models.conversation import ConversationORM

if TYPE_CHECKING:
    from inkflow.domain.services.agent_entity_service import AgentEntityService
    from inkflow.domain.services.agent_service import AgentService


class _ConversationService:
    """会话读取服务（#766 阶段②）——chat agent 装配守卫按 per-conversation 删除授权决策."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(self, conversation_id: uuid.UUID) -> Conversation | None:
        """按 id 读取会话领域实体；不存在返回 None（装配层按 manual 兜底）."""
        row = (
            await self._db.execute(
                select(ConversationORM).where(ConversationORM.id == conversation_id.int)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return Conversation(
            id=uuid.UUID(int=row.id),
            project_id=uuid.UUID(int=row.project_id),
            created_at=(
                row.created_at
                if row.created_at.tzinfo is not None
                else row.created_at.replace(tzinfo=UTC)
            ),
            is_deleted=row.is_deleted,
            delete_permission=row.delete_permission,
        )


def get_conversation_service(db: AsyncSession) -> _ConversationService:
    """获取会话读取服务（#766 阶段②：装配守卫按 conversation.delete_permission 注入删除工具）."""
    return _ConversationService(db)


def get_agent_service(
    db: AsyncSession,
) -> AgentService:
    """获取 AgentService 实例（F4 管线执行服务，#766 阶段③ agent_run 工具用）."""
    from inkflow.api.deps import get_summary_service
    from inkflow.domain.services.agent_service import AgentService
    from inkflow.infrastructure.agent.langgraph_pipeline import LangGraphAgentPipeline
    from inkflow.infrastructure.database.repositories.character_repo import (
        SQLiteCharacterRepository,
    )
    from inkflow.infrastructure.database.repositories.outline_repo import (
        SQLiteOutlineRepository,
    )
    from inkflow.infrastructure.database.repositories.world_repo import (
        SQLiteWorldRepository,
    )
    from inkflow.infrastructure.llm.langchain_client import LangChainLLMClient

    llm_client = LangChainLLMClient()
    return AgentService(
        pipeline=LangGraphAgentPipeline(llm_client=llm_client),
        db_session=db,
        summary_service=get_summary_service(db),
        character_repo=SQLiteCharacterRepository(db),
        world_repo=SQLiteWorldRepository(db),
        outline_repo=SQLiteOutlineRepository(db),
    )


def get_agent_entity_service(
    db: AsyncSession,
) -> AgentEntityService:
    """获取 AgentEntityService 实例（F39 Agent 实体，#766 阶段③ agent_call 工具用）."""
    from inkflow.core.config import config
    from inkflow.domain.services.agent_entity_service import AgentEntityService
    from inkflow.infrastructure.database.repositories.agent_repo import (
        SQLiteAgentRepository,
    )

    return AgentEntityService(
        agent_repository=SQLiteAgentRepository(db),
        skills_root=config.data_dir / "skills",
    )
