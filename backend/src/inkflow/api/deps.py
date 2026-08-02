"""FastAPI 依赖注入 — 数据库 session 和 Service 获取."""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.core.database import get_session
from inkflow.domain.ports.context_sources import ContextSourceProtocol
from inkflow.domain.ports.vector_store import VectorStoreProtocol
from inkflow.domain.services._character_extractor import CharacterExtractor
from inkflow.domain.services._foreshadowing_extractor import ForeshadowingExtractor
from inkflow.domain.services._outline_generator import OutlineGenerator
from inkflow.domain.services._timeline_extractor import TimelineExtractor
from inkflow.domain.services._world_extractor import WorldExtractor
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.domain.services.character_service import CharacterService
from inkflow.domain.services.context_service import ContextService
from inkflow.domain.services.extraction_service import ExtractionService
from inkflow.domain.services.foreshadowing_service import ForeshadowingService
from inkflow.domain.services.outline_service import OutlineService
from inkflow.domain.services.project_service import ProjectService
from inkflow.domain.services.summary_service import SummaryService
from inkflow.domain.services.timeline_service import TimelineService
from inkflow.domain.services.world_service import WorldService
from inkflow.domain.services.writing_service import WritingService
from inkflow.infrastructure.database.repositories.chapter_repo import (
    SQLiteChapterRepository,
)
from inkflow.infrastructure.database.repositories.character_repo import (
    SQLiteCharacterRepository,
)
from inkflow.infrastructure.database.repositories.extraction_run_repo import (
    SQLExtractionRunRepository,
)
from inkflow.infrastructure.database.repositories.foreshadowing_repo import (
    SQLiteForeshadowingRepository,
)
from inkflow.infrastructure.database.repositories.outline_repo import (
    SQLiteOutlineRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.database.repositories.summary_repo import (
    SQLiteSummaryRepository,
)
from inkflow.infrastructure.database.repositories.timeline_repo import (
    SQLiteTimelineRepository,
)
from inkflow.infrastructure.database.repositories.world_repo import (
    SQLiteWorldRepository,
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
    from inkflow.infrastructure.database.repositories.foreshadowing_repo import (
        SQLiteForeshadowingRepository,
    )

    project_repo = SQLiteProjectRepository(db)
    summary_repo = SQLiteSummaryRepository(db)

    sources: dict[ContextSourceType, ContextSourceProtocol] = {
        ContextSourceType.OUTLINE: ProjectConfigOutlineSource(project_repo),
        ContextSourceType.CHARACTER_SETTING: CharacterSettingSource(),
        ContextSourceType.WORLD_SETTING: WorldSettingSource(),
        ContextSourceType.FORESHADOWING: ForeshadowingSource(SQLiteForeshadowingRepository(db)),
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


def get_world_service(
    db: AsyncSession,
) -> WorldService:
    """获取 WorldService 实例（世界观条目仓储 + AI 提取器）.

    装配 WorldExtractor（LLM 客户端 + Prompt 模板 + 同一仓储实例），
    extract 入口的项目存在性校验使用 F1 项目仓储。
    """
    repo = SQLiteWorldRepository(db)
    return WorldService(
        repository=repo,
        extractor=WorldExtractor(
            llm_client=LangChainLLMClient(),
            prompt_manager=LangChainPromptManager(),
            repository=repo,
        ),
        project_repo=SQLiteProjectRepository(db),
    )


def get_outline_service(
    db: AsyncSession,
) -> OutlineService:
    """获取 OutlineService 实例（大纲/情节点/弧线仓储 + AI 生成器）.

    装配 OutlineGenerator（LLM 客户端 + Prompt 模板 + 同一仓储实例），
    generate 入口的项目存在性校验使用 F1 项目仓储。
    """
    repo = SQLiteOutlineRepository(db)
    return OutlineService(
        repository=repo,
        generator=OutlineGenerator(
            llm_client=LangChainLLMClient(),
            prompt_manager=LangChainPromptManager(),
            repository=repo,
        ),
        project_repo=SQLiteProjectRepository(db),
    )


def get_timeline_service(
    db: AsyncSession,
) -> TimelineService:
    """获取 TimelineService 实例（时间线事件仓储 + F1 项目仓储）.

    装配 SQLiteTimelineRepository（事件 CRUD + 双线视图 + 一致性检查），
    项目存在性校验使用 F1 项目仓储（同 F9/F10/F11 模式）。
    """
    return TimelineService(
        repository=SQLiteTimelineRepository(db),
        project_repo=SQLiteProjectRepository(db),
    )


def get_foreshadowing_service(
    db: AsyncSession,
) -> ForeshadowingService:
    """获取 ForeshadowingService 实例（伏笔仓储 + F1 项目仓储 + F12 时间线仓储）.

    装配 SQLiteForeshadowingRepository（伏笔 CRUD + 状态机），项目存在性
    校验使用 F1 项目仓储，event_id 事件锚点校验复用 F12 时间线事件仓储
    （镜像 get_timeline_service 模式）。
    """
    return ForeshadowingService(
        repository=SQLiteForeshadowingRepository(db),
        project_repo=SQLiteProjectRepository(db),
        timeline_repo=SQLiteTimelineRepository(db),
    )


def get_extraction_service(
    db: AsyncSession,
) -> ExtractionService:
    """获取 ExtractionService 实例（F14 统一提取门面，spec §5/§8）.

    装配: 复用 F9/F10/F11/F12 Service（get_character_service 等）+ F14 两条
    新管线（ForeshadowingExtractor / TimelineExtractor，LLM 客户端 + Prompt
    模板 + 对应仓储）+ SQLExtractionRunRepository（增量追踪）+ F1/F2 仓储 +
    懒加载向量存储（get_vector_store，BGE 首次调用才下载 ~100MB，spec §8）。
    """
    return ExtractionService(
        project_repo=SQLiteProjectRepository(db),
        chapter_repo=SQLiteChapterRepository(db),
        run_repo=SQLExtractionRunRepository(db),
        character_service=get_character_service(db),
        world_service=get_world_service(db),
        outline_service=get_outline_service(db),
        timeline_service=get_timeline_service(db),
        foreshadowing_extractor=ForeshadowingExtractor(
            llm_client=LangChainLLMClient(),
            prompt_manager=LangChainPromptManager(),
            foreshadowing_repo=SQLiteForeshadowingRepository(db),
        ),
        timeline_extractor=TimelineExtractor(
            llm_client=LangChainLLMClient(),
            prompt_manager=LangChainPromptManager(),
            timeline_repo=SQLiteTimelineRepository(db),
        ),
        character_repo=SQLiteCharacterRepository(db),
        world_repo=SQLiteWorldRepository(db),
        timeline_repo=SQLiteTimelineRepository(db),
        foreshadowing_repo=SQLiteForeshadowingRepository(db),
        vector_store=get_vector_store(),
    )


_vector_store: VectorStoreProtocol | None = None
"""模块级向量存储单例 — 懒加载（首次调用才初始化，spec §8）。"""


def get_vector_store() -> VectorStoreProtocol:
    """获取 RAG 向量存储（模块级单例，懒加载，spec §8/§12）.

    LangChainVectorStore（Chroma 持久化到 config.vector_store_dir）+ BGE
    本地 Embedding（config.embedding_model / embedding_device）。BGE 模型
    首次使用需联网下载 ~100MB，仅首次调用时初始化；初始化失败抛
    RAGUnavailableError（spec §3.4: 500「RAG 向量库不可用」前缀）。
    """
    global _vector_store
    if _vector_store is None:
        from langchain_community.embeddings import HuggingFaceBgeEmbeddings

        from inkflow.core.config import config
        from inkflow.domain.ports.extraction_errors import RAGUnavailableError
        from inkflow.infrastructure.rag.langchain_vector_store import (  # type: ignore[import-untyped]  # M6 落地后自动消除（warn_unused_ignores 未开启）
            LangChainVectorStore,
        )

        try:
            _vector_store = LangChainVectorStore(
                persist_dir=config.vector_store_dir,
                embeddings=HuggingFaceBgeEmbeddings(
                    model_name=config.embedding_model,
                    device=config.embedding_device,
                ),
            )
        except Exception as e:
            raise RAGUnavailableError(f"RAG 向量库不可用: Embedding 模型加载失败（{e}）") from e
    return _vector_store
