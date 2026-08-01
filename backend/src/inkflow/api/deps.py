"""FastAPI 依赖注入 — 数据库 session 和 Service 获取."""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.core.database import get_session
from inkflow.domain.ports.context_sources import ContextSourceProtocol
from inkflow.domain.services._character_extractor import CharacterExtractor
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.domain.services.character_service import CharacterService
from inkflow.domain.services.context_service import ContextService
from inkflow.domain.services.project_service import ProjectService
from inkflow.domain.services.summary_service import SummaryService
from inkflow.domain.services.writing_service import WritingService
from inkflow.infrastructure.database.repositories.chapter_repo import (
    SQLiteChapterRepository,
)
from inkflow.infrastructure.database.repositories.character_repo import (
    SQLiteCharacterRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.database.repositories.summary_repo import (
    SQLiteSummaryRepository,
)
from inkflow.infrastructure.llm import LangChainLLMClient, LangChainPromptManager


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """获取数据库 session（FastAPI 依赖）."""
    async for session in get_session():
        yield session


def get_project_service(
    db: AsyncSession,
) -> ProjectService:
    """获取 ProjectService 实例（注入数据库 session）."""
    return ProjectService(db)


def get_chapter_service(
    db: AsyncSession,
) -> ChapterService:
    """获取 ChapterService 实例（注入数据库 session）."""
    return ChapterService(db)


def get_writing_service(
    db: AsyncSession = Depends(get_db),
) -> WritingService:
    """获取 WritingService 实例（LLM 客户端 + Prompt 模板 + 仓储）."""
    return WritingService(
        llm_client=LangChainLLMClient(),
        prompt_manager=LangChainPromptManager(),
        project_repo=SQLiteProjectRepository(db),
        chapter_repo=SQLiteChapterRepository(db),
    )


def get_context_service(
    db: AsyncSession,
) -> ContextService:
    """获取 ContextService 实例.

    Phase 1 空实现：Character/World/Foreshadowing 数据源为空。
    使用 Mock count_tokens（生产环境由 F5 LLMClient.count_tokens 替换）。
    """
    from inkflow.domain.models.context import ContextSourceType
    from inkflow.infrastructure.context.sources import (
        CharacterSettingSource,
        ForeshadowingSource,
        ProjectConfigOutlineSource,
        WorldSettingSource,
    )

    project_repo = SQLiteProjectRepository(db)
    summary_repo = SQLiteSummaryRepository(db)

    sources: dict[ContextSourceType, ContextSourceProtocol] = {
        ContextSourceType.OUTLINE: ProjectConfigOutlineSource(project_repo),
        ContextSourceType.CHARACTER_SETTING: CharacterSettingSource(),
        ContextSourceType.WORLD_SETTING: WorldSettingSource(),
        ContextSourceType.FORESHADOWING: ForeshadowingSource(),
    }

    return ContextService(
        sources=sources,
        summary_repo=summary_repo,
    )


def get_summary_service(
    db: AsyncSession,
) -> SummaryService:
    """获取 SummaryService 实例."""
    from inkflow.infrastructure.database.repositories.chapter_repo import (
        SQLiteChapterRepository,
    )

    return SummaryService(
        summary_repo=SQLiteSummaryRepository(db),
        llm_client=LangChainLLMClient(),
        prompt_manager=LangChainPromptManager(),
        chapter_reader=SQLiteChapterRepository(db),
    )


def get_character_service(
    db: AsyncSession,
) -> CharacterService:
    """获取 CharacterService 实例（角色/分组/关系仓储 + AI 提取器）.

    装配 CharacterExtractor（LLM 客户端 + Prompt 模板 + 同一仓储实例），
    extract 入口的项目存在性校验使用 F1 项目仓储。
    """
    repo = SQLiteCharacterRepository(db)
    return CharacterService(
        repository=repo,
        extractor=CharacterExtractor(
            llm_client=LangChainLLMClient(),
            prompt_manager=LangChainPromptManager(),
            repository=repo,
        ),
        project_repo=SQLiteProjectRepository(db),
    )
