"""FastAPI 依赖注入 — 数据库 session 和 Service 获取."""

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.core.database import async_session_factory, get_session
from inkflow.domain.models.agent_run import AgenticWriteRequest
from inkflow.domain.ports.context_sources import ContextSourceProtocol
from inkflow.domain.ports.extraction_errors import RAGUnavailableError
from inkflow.domain.ports.vector_store import VectorStoreProtocol
from inkflow.domain.services._character_extractor import CharacterExtractor
from inkflow.domain.services._foreshadowing_extractor import ForeshadowingExtractor
from inkflow.domain.services._outline_generator import OutlineGenerator
from inkflow.domain.services._style_llm_analyzer import StyleLLMAnalyzer
from inkflow.domain.services._timeline_extractor import TimelineExtractor
from inkflow.domain.services._world_extractor import WorldExtractor
from inkflow.domain.services.agentic_writer_service import AgenticWriterService
from inkflow.domain.services.audit_log_service import AuditLogService
from inkflow.domain.services.audit_service import AuditService
from inkflow.domain.services.chapter_audit_service import ChapterAuditService
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.domain.services.character_service import CharacterService
from inkflow.domain.services.context_service import ContextService
from inkflow.domain.services.copy_service import WorldCopyService
from inkflow.domain.services.draft_service import DraftService
from inkflow.domain.services.extraction_service import ExtractionService
from inkflow.domain.services.foreshadowing_service import ForeshadowingService
from inkflow.domain.services.map_service import MapService
from inkflow.domain.services.memory_service import MemoryService
from inkflow.domain.services.outline_service import OutlineService
from inkflow.domain.services.output_service import ExportService
from inkflow.domain.services.project_service import ProjectService
from inkflow.domain.services.provider_config_service import ProviderConfigService
from inkflow.domain.services.search_service import SearchService
from inkflow.domain.services.session_service import SessionService
from inkflow.domain.services.settings_service import SettingsService
from inkflow.domain.services.style_service import StyleService
from inkflow.domain.services.summary_service import SummaryService
from inkflow.domain.services.timeline_service import TimelineService
from inkflow.domain.services.world_service import WorldService
from inkflow.domain.services.writing_service import WritingService
from inkflow.infrastructure.database.repositories.agent_run_repo import (
    SQLiteAgentRunRepository,
)
from inkflow.infrastructure.database.repositories.audit_log_repo import (
    SQLiteAuditLogRepository,
)
from inkflow.infrastructure.database.repositories.audit_repo import (
    SQLiteAuditRepository,
)
from inkflow.infrastructure.database.repositories.chapter_repo import (
    SQLiteChapterRepository,
)
from inkflow.infrastructure.database.repositories.character_repo import (
    SQLiteCharacterRepository,
)
from inkflow.infrastructure.database.repositories.draft_repo import (
    SQLiteDraftRepository,
)
from inkflow.infrastructure.database.repositories.extraction_run_repo import (
    SQLExtractionRunRepository,
)
from inkflow.infrastructure.database.repositories.foreshadowing_repo import (
    SQLiteForeshadowingRepository,
)
from inkflow.infrastructure.database.repositories.memory_event_repo import (
    SQLiteMemoryEventRepository,
)
from inkflow.infrastructure.database.repositories.outline_repo import (
    SQLiteOutlineRepository,
)
from inkflow.infrastructure.database.repositories.preference_repo import (
    SQLitePreferenceRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)
from inkflow.infrastructure.database.repositories.provider_config_repo import (
    SQLiteProviderConfigRepository,
)
from inkflow.infrastructure.database.repositories.search_repo import (
    SQLiteSearchRepository,
)
from inkflow.infrastructure.database.repositories.session_repo import (
    SQLiteSessionRepository,
)
from inkflow.infrastructure.database.repositories.settings_repo import (
    SQLiteSettingsRepository,
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
    """获取 ProjectService 实例（注入数据库 session + F36 项目硬删钩子）."""
    import uuid

    map_svc = get_map_service(db)
    return ProjectService(db, map_cleanup=lambda pid: map_svc.cleanup_project(uuid.UUID(int=pid)))


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


def get_agent_run_repo(
    db: AsyncSession = Depends(get_db),
) -> SQLiteAgentRunRepository:
    """获取 AgentRun 仓储实例（run 查询端点用）."""
    return SQLiteAgentRunRepository(db)


def get_preference_repo(
    db: AsyncSession = Depends(get_db),
) -> SQLitePreferenceRepository:
    """获取偏好仓储实例（F28 偏好查询端点用）."""
    return SQLitePreferenceRepository(db)


def get_memory_event_repo(
    db: AsyncSession = Depends(get_db),
) -> SQLiteMemoryEventRepository:
    """获取记忆事件仓储实例（F28 事件查询端点用）."""
    return SQLiteMemoryEventRepository(db)


def get_memory_service(
    db: AsyncSession = Depends(get_db),
) -> MemoryService:
    """获取 MemoryService 实例（偏好学习编排）."""
    return MemoryService(
        preference_repo=SQLitePreferenceRepository(db),
        event_repo=SQLiteMemoryEventRepository(db),
        project_repo=SQLiteProjectRepository(db),
        audit_service=AuditLogService(SQLiteAuditLogRepository(db)),
    )


def get_draft_service(
    db: AsyncSession = Depends(get_db),
) -> DraftService:
    """获取 DraftService 实例（草稿列表/确认/拒绝/编辑；F28 接入 diff 事件）."""
    return DraftService(
        draft_repo=SQLiteDraftRepository(db),
        chapter_service=get_chapter_service(db),
        audit_service=AuditLogService(SQLiteAuditLogRepository(db)),
        memory_service=get_memory_service(db),
    )


def get_agentic_writer_service(
    db: AsyncSession = Depends(get_db),
) -> AgenticWriterService:
    """获取 AgenticWriterService 实例（agentic 编排，装配 F26/F27 工具）."""
    from inkflow.core.config import config
    from inkflow.infrastructure.agent.agentic_writer import (
        AgenticWriterDeps,
        build_agentic_writer,
        build_writer_agent_system_prompt,
    )
    from inkflow.infrastructure.llm.provider_config import (
        get_provider_config,
        parse_model_string,
    )

    # 循环依赖注意：不重复调 get_draft_service(db)（直接 Python 调用无 FastAPI
    # 依赖缓存）——草稿服务在同一函数内联构建，deps 与 service 共享同源实例
    draft_service = DraftService(
        draft_repo=SQLiteDraftRepository(db),
        chapter_service=get_chapter_service(db),
        audit_service=AuditLogService(SQLiteAuditLogRepository(db)),
        memory_service=get_memory_service(db),
    )
    audit_service = AuditLogService(SQLiteAuditLogRepository(db))
    deps = AgenticWriterDeps(
        character_service=get_character_service(db),
        foreshadowing_service=get_foreshadowing_service(db),
        summary_service=get_summary_service(db),
        chapter_audit_service=get_chapter_audit_service(db),
        draft_service=draft_service,
        audit_service=audit_service,
    )
    prompt_manager = LangChainPromptManager()

    def _build_agent(request: AgenticWriteRequest) -> object:
        """每次 run 构建 agent——系统提示与工具期望上下文按请求注入（#275）."""

        system_prompt = build_writer_agent_system_prompt(
            prompt_manager,
            project_id=request.project_id,
            chapter_id=request.chapter_id,
        )
        return build_agentic_writer(
            model=model,
            api_key=api_key,
            base_url=base_url,
            deps=deps,
            system_prompt=system_prompt,
            expected_project_id=request.project_id,
            expected_chapter_id=request.chapter_id,
        )

    # 模型/密钥/base_url 同源装配（F5 provider_config）：默认模型解析 provider，
    # 未配置 key/base_url 时回退空串（harness 支持空 key/base_url 走 ChatOpenAI 默认）
    model = config.llm_default_model
    api_key = ""
    base_url = ""
    try:
        provider, _ = parse_model_string(model)
        provider_cfg = get_provider_config(provider)
        api_key = provider_cfg.api_key
        base_url = provider_cfg.base_url or ""
    except ValueError:
        pass
    return AgenticWriterService(
        agent_factory=_build_agent,
        draft_service=draft_service,
        audit_service=audit_service,
        run_repo=SQLiteAgentRunRepository(db),
        chapter_service=get_chapter_service(db),
    )


def _collect_explicit_texts(db: AsyncSession):
    """收集显式设定文本（冲突过滤用）：角色档案 name 列表.

    调用 get_character_service(db).list_characters(project_id) 取角色名；
    返回形态以真实实现为准（tuple (list, total) 或 list——宽松兼容）。
    """

    async def loader(project_id: uuid.UUID) -> list[str]:
        svc = get_character_service(db)
        result = await svc.list_characters(project_id)
        characters = result[0] if isinstance(result, tuple) else result
        return [c.name for c in characters if getattr(c, "name", "")]

    return loader


def get_context_service(
    db: AsyncSession,
) -> ContextService:
    """获取 ContextService 实例.

    Phase 1 空实现：Character/World/Foreshadowing 数据源为空。
    使用 Mock count_tokens（生产环境由 F5 LLMClient.count_tokens 替换）。
    """
    from inkflow.domain.models.context import ContextSourceType
    from inkflow.infrastructure.context.preference_source import PreferenceSource
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
        ContextSourceType.PREFERENCE: PreferenceSource(
            SQLitePreferenceRepository(db),
            project_repo,
            explicit_texts=_collect_explicit_texts(db),
        ),
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
    extract 入口的项目存在性校验使用 F1 项目仓储；F36 地点硬删钩子接线
    MapService.clear_location_pins（D10=b 显式级联）。
    """
    import uuid

    repo = SQLiteWorldRepository(db)
    map_svc = get_map_service(db)

    async def _location_cleanup(location_ids: list[int]) -> None:
        """地点硬删钩子：pin SET NULL（D10=b 显式级联；mypy 契约 Awaitable[None]）."""
        await map_svc.clear_location_pins([uuid.UUID(int=i) for i in location_ids])

    return WorldService(
        repository=repo,
        extractor=WorldExtractor(
            llm_client=LangChainLLMClient(),
            prompt_manager=LangChainPromptManager(),
            repository=repo,
        ),
        project_repo=SQLiteProjectRepository(db),
        location_cleanup=_location_cleanup,
    )


def get_copy_service(
    db: AsyncSession,
) -> WorldCopyService:
    """获取 WorldCopyService 实例（世界观跨书复制编排）。"""
    from inkflow.core.config import config
    from inkflow.infrastructure.assets import LocalMapAssetStore
    from inkflow.infrastructure.database.repositories.map_repo import (
        SQLiteMapRepository,
    )

    return WorldCopyService(
        repository=SQLiteWorldRepository(db),
        project_repo=SQLiteProjectRepository(db),
        map_repo=SQLiteMapRepository(db),
        asset_store=LocalMapAssetStore(config.data_dir),
    )


def get_map_service(
    db: AsyncSession,
) -> MapService:
    """获取 MapService 实例（地图仓储 + 图片资产存储 + 世界观/项目仓储）."""
    from inkflow.core.config import config
    from inkflow.infrastructure.assets import LocalMapAssetStore
    from inkflow.infrastructure.database.repositories.map_repo import (
        SQLiteMapRepository,
    )

    return MapService(
        repository=SQLiteMapRepository(db),
        asset_store=LocalMapAssetStore(config.data_dir),
        world_repo=SQLiteWorldRepository(db),
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


def get_session_service(
    db: AsyncSession,
) -> SessionService:
    """获取 SessionService 实例（会话仓储 + F1 项目仓储）.

    装配 SQLiteSessionRepository（双实体 CRUD + 状态机 + 履历日志），项目
    存在性校验复用 F1 SQLiteProjectRepository（同 F12/F13 模式）.
    """
    return SessionService(
        repository=SQLiteSessionRepository(db),
        project_repo=SQLiteProjectRepository(db),
    )


def get_provider_config_service(
    db: AsyncSession,
) -> ProviderConfigService:
    """获取 ProviderConfigService 实例（Provider 注册表仓储）."""
    return ProviderConfigService(
        repository=SQLiteProviderConfigRepository(db),
    )


def get_settings_service(
    db: AsyncSession = Depends(get_db),
) -> SettingsService:
    """获取 SettingsService 实例（app_settings 键值仓储，F32 #152）.

    显式 Depends(get_db) 依赖链：测试经 app.dependency_overrides[get_db]
    替换 session（tests/api/conftest.py override_get_db 生效前提），
    镜像 get_writing_service 形态（spec §3.5 评审修订）。
    """
    return SettingsService(
        repository=SQLiteSettingsRepository(db),
    )


async def get_extraction_service(
    db: AsyncSession,
) -> ExtractionService:
    """获取 ExtractionService 实例（F14 统一提取门面，spec §5/§8）.

    装配: 复用 F9/F10/F11/F12 Service（get_character_service 等）+ F14 两条
    新管线（ForeshadowingExtractor / TimelineExtractor，LLM 客户端 + Prompt
    模板 + 对应仓储）+ F16 StyleService（get_style_service，STYLE 槽位，
    §8.2）+ SQLExtractionRunRepository（增量追踪）+ F1/F2 仓储 +
    懒加载向量存储（get_vector_store，API embedding——从 ProviderConfig
    注册表读取 embedding 模型，首次调用才初始化，spec f19 §5）+ #276
    reindex 四步协议指纹提供器（fingerprint_provider，dimension 取 store
    实测值；None = 不写指纹，向后兼容）。
    """
    vector_store = await get_vector_store()

    async def _fingerprint_provider() -> dict | None:
        """reindex 指纹提供器（#276）— configured 指纹 + store 实测维度。"""
        dimension = (
            vector_store.embedding_dimension  # type: ignore[attr-defined]  # embedding_dimension 为 G2 运行时实例属性（Protocol 未声明，LangChainVectorStore 与测试 fake 均提供）
            if vector_store is not None
            else None
        )
        return await build_configured_fingerprint(dimension=dimension)

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
        style_service=get_style_service(db),
        character_repo=SQLiteCharacterRepository(db),
        world_repo=SQLiteWorldRepository(db),
        timeline_repo=SQLiteTimelineRepository(db),
        foreshadowing_repo=SQLiteForeshadowingRepository(db),
        vector_store=vector_store,
        fingerprint_provider=_fingerprint_provider,
    )


def get_audit_service(
    db: AsyncSession,
) -> AuditService:
    """获取 AuditService 实例（F15 审计服务，spec §5/§8）.

    装配: 复用 F9/F10/F13/F14/F2/F1 各 SQLite 仓储 + F12 TimelineService
    （get_timeline_service 先例）+ SQLiteAuditRepository（F15 自有软删集合
    查询实现，§8.2）——除 audit_repo 外全部为既有实现。
    """
    return AuditService(
        project_repo=SQLiteProjectRepository(db),
        character_repo=SQLiteCharacterRepository(db),
        world_repo=SQLiteWorldRepository(db),
        timeline_service=get_timeline_service(db),
        foreshadowing_repo=SQLiteForeshadowingRepository(db),
        chapter_repo=SQLiteChapterRepository(db),
        run_repo=SQLExtractionRunRepository(db),
        audit_repo=SQLiteAuditRepository(db),
    )


def get_chapter_audit_service(
    db: AsyncSession,
) -> ChapterAuditService:
    """获取 ChapterAuditService 实例（F34 章节审计服务，spec §5/§8）.

    装配: 复用 F1/F2/F9/F10 各 SQLite 仓储 + F15 AuditService
    （get_audit_service 先例，静态一致性委托）+ F5 LangChainLLMClient
    （人设/设定漂移 LLM 检查）+ F34 自有 SQLiteAuditLogRepository
    （审计日志轻量记录，§8.2）——除 audit_log_repo 外全部为既有实现。
    """
    return ChapterAuditService(
        project_repo=SQLiteProjectRepository(db),
        chapter_repo=SQLiteChapterRepository(db),
        character_repo=SQLiteCharacterRepository(db),
        world_repo=SQLiteWorldRepository(db),
        audit_service=get_audit_service(db),
        llm_client=LangChainLLMClient(),
        audit_log_repo=SQLiteAuditLogRepository(db),
    )


def get_export_service(
    db: AsyncSession,
) -> ExportService:
    """获取 ExportService 实例（F21 导出服务，spec §8.2）。

    装配: 复用 F1/F2/F9/F10/F11/F12/F13 各 SQLite 仓储——全部既有实现，
    零跨模块 MODIFY（§8.2）。
    """
    return ExportService(
        project_repo=SQLiteProjectRepository(db),
        chapter_repo=SQLiteChapterRepository(db),
        character_repo=SQLiteCharacterRepository(db),
        world_repo=SQLiteWorldRepository(db),
        outline_repo=SQLiteOutlineRepository(db),
        timeline_repo=SQLiteTimelineRepository(db),
        foreshadowing_repo=SQLiteForeshadowingRepository(db),
    )


def get_style_service(
    db: AsyncSession,
) -> StyleService:
    """获取 StyleService 实例（F16 风格检测服务，spec §5.1/§8.1）.

    装配: F1 SQLiteProjectRepository（项目校验）+ F2 SQLiteChapterRepository
    （章节读取）+ 可选 LLM 深度分析器 StyleLLMAnalyzer（LangChainLLMClient +
    LangChainPromptManager，模板 style_llm_analysis——镜像 F14
    TimelineExtractor 装配模式，spec §5.6）。
    """
    return StyleService(
        project_repo=SQLiteProjectRepository(db),
        chapter_repo=SQLiteChapterRepository(db),
        llm_analyzer=StyleLLMAnalyzer(
            llm_client=LangChainLLMClient(),
            prompt_manager=LangChainPromptManager(),
        ),
    )


async def get_search_service(
    db: AsyncSession,
) -> SearchService:
    """获取 SearchService 实例（F22 全文搜索，spec §8.1）.

    #264：注入 get_vector_store_optional()——未配置 embedding 时 None 兜底，
    semantic 模式真实可用（原硬编码 vector_store=None 导致 semantic 恒空）。
    """
    return SearchService(
        project_repo=SQLiteProjectRepository(db),
        chapter_repo=SQLiteChapterRepository(db),
        character_repo=SQLiteCharacterRepository(db),
        world_repo=SQLiteWorldRepository(db),
        outline_repo=SQLiteOutlineRepository(db),
        timeline_repo=SQLiteTimelineRepository(db),
        foreshadowing_repo=SQLiteForeshadowingRepository(db),
        search_repo=SQLiteSearchRepository(db),
        # #264: 注入可选 vector_store（未配置 embedding 时 None → keyword 正常）
        vector_store=await get_vector_store_optional(),
    )


_vector_store: VectorStoreProtocol | None = None
"""模块级向量存储单例 — 懒加载（首次调用才初始化，spec §8）。"""


async def _resolve_embedding_spec() -> tuple[str, str, str]:
    """解析 embedding 装配选型 → (provider, model_id, base_url)（#276 G3）.

    选型规则（用户拍板 2026-08-12）: ProviderConfig 注册表首个
    type="embedding" 模型为唯一真相源；注册表无 → config.embedding_model
    本地 BGE 离线 fallback（provider 标记 "local"）；两者皆不可用 →
    RAGUnavailableError「未配置 embedding 模型」。base_url 为 None 时归一化为
    空串（指纹 dict 与 OpenAI 构造共用同一元组）。
    """
    from inkflow.core.config import config
    from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel
    from inkflow.domain.ports.extraction_errors import RAGUnavailableError
    from inkflow.infrastructure.database.repositories.provider_config_repo import (
        SQLiteProviderConfigRepository,
    )

    # 读 ProviderConfig 注册表取首个 type="embedding" 模型（spec f19 §5.4）
    found: tuple[ProviderConfig, ProviderModel] | None = None
    async with async_session_factory() as session:
        repo = SQLiteProviderConfigRepository(session)
        for p in await repo.list():
            for m in p.models:
                if m.type == "embedding":
                    found = (p, m)
                    break
            if found:
                break
    if found is not None:
        provider_cfg, model = found
        return provider_cfg.name, model.id, provider_cfg.base_url or ""
    if config.embedding_model:
        return "local", config.embedding_model, ""
    raise RAGUnavailableError("未配置 embedding 模型")


async def _build_store() -> VectorStoreProtocol:
    """按当前配置装配新向量存储（不赋值全局单例，供 get/refresh 复用）.

    与 _resolve_embedding_spec 共用选型段: API embedding（OpenAIEmbeddings）
    或本地 BGE 离线 fallback（HuggingFaceBgeEmbeddings）；embedding 或
    LangChainVectorStore 构造失败 → RAGUnavailableError（500 RAG 前缀，
    spec §3.4/§5.5 B1）。
    """
    provider, model_id, base_url = await _resolve_embedding_spec()
    from langchain_core.embeddings import Embeddings

    from inkflow.core.config import config
    from inkflow.infrastructure.llm.key_manager import APIKeyManager
    from inkflow.infrastructure.rag.langchain_vector_store import (
        LangChainVectorStore,
    )

    try:
        # 显式类型注解：if/else 分支赋值不同类型（BGE/OpenAI）——mypy 推断
        # 首分支类型导致第二分支 [assignment] 报错（CI lint-backend 实测）
        embeddings: Embeddings
        if provider == "local":
            from langchain_community.embeddings import HuggingFaceBgeEmbeddings

            embeddings = HuggingFaceBgeEmbeddings(
                model_name=model_id,
                # device 非顶层字段（pydantic extra_forbidden）——走 model_kwargs
                # （2026-08-12 实测修正）
                model_kwargs={"device": config.embedding_device},
            )
        else:
            from langchain_openai import OpenAIEmbeddings

            key = APIKeyManager(
                secret_key=config.secret_key,
                storage_dir=config.data_dir / "keys",
            ).load(provider)
            embeddings = OpenAIEmbeddings(
                model=model_id,
                api_key=SecretStr(key),
                base_url=base_url or None,
            )
        return LangChainVectorStore(
            persist_dir=config.vector_store_dir,
            embeddings=embeddings,
        )
    except Exception as e:
        raise RAGUnavailableError(f"RAG 向量库不可用: Embedding 模型加载失败（{e}）") from e


async def get_vector_store() -> VectorStoreProtocol:
    """获取 RAG 向量存储（模块级单例，懒加载，spec f19 §5）.

    LangChainVectorStore（Chroma 持久化到 config.vector_store_dir）+ embedding
    装配（#276 G3）: 注册表首个 type="embedding" 模型为唯一真相源（API
    embedding，spec f19 §5.2/§5.4）；注册表无 → config.embedding_model 本地
    BGE 离线 fallback；两者皆不可用 → RAGUnavailableError（500「RAG 向量库
    不可用」前缀，§5.5 B1/B6）。仅首次调用时初始化，懒加载单例语义不变。
    """
    global _vector_store
    if _vector_store is None:
        _vector_store = await _build_store()
    return _vector_store


async def refresh_vector_store() -> VectorStoreProtocol:
    """刷新向量存储单例（#276 G3 契约 14）——重建失败保留旧实例.

    用当前配置重建 store（重新走选型 + 构造）；成功 → 原子替换模块级
    _vector_store；失败 → RAGUnavailableError 上抛，旧实例保留不动
    （不允许半替换/静默回退，防 reindex 用旧模型重写旧向量假成功）。
    """
    global _vector_store
    new_store = await _build_store()
    _vector_store = new_store
    return new_store


async def build_configured_fingerprint(*, dimension: int | None = None) -> dict | None:
    """构建当前 embedding 配置的指纹 dict（#276 G3 契约 15）.

    与 _build_store 共用 _resolve_embedding_spec 选型；解析失败
    （RAGUnavailableError）→ 返回 None。base_url 去尾部斜杠；chunking 为
    当前固定切片默认值（fixed / 500 / 0.0 / 1，与领域常量一致）。
    """
    from inkflow.domain.ports.extraction_errors import RAGUnavailableError

    try:
        provider, model_id, base_url = await _resolve_embedding_spec()
    except RAGUnavailableError:
        return None
    return {
        "schema_version": 1,
        "embedding": {
            "provider": provider,
            "model_id": model_id,
            "base_url": base_url.rstrip("/"),
            "dimension": dimension,
        },
        "chunking": {
            "mode": "fixed",
            "chunk_size": 500,
            "overlap_ratio": 0.0,
            "chunker_version": 1,
        },
        "indexed_at": None,
        "status": "fresh",
    }


async def get_vector_status(project_id: str) -> dict:
    """返回项目 RAG 向量状态 dict（#276 G3 契约 15）.

    configured_fp 来自当前配置（dimension 取 store.embedding_dimension 实测值，
    未 embed 过 = None）；indexed_fp 来自 store.read_fingerprint；stale/reason
    由 compare_fingerprints 判定（dimension 不参与比对）；dimension_mismatch
    为独立判据: 索引存在且维度不同，或无索引但集合已含不同维度向量。
    """
    store = await get_vector_store_optional()
    if store is None:
        return {
            "configured_fp": None,
            "indexed_fp": None,
            "stale": False,
            "reason": "no_embedding",
            "dimension_mismatch": False,
        }
    configured_dict = await build_configured_fingerprint(
        dimension=(
            store.embedding_dimension if store.embedding_dimension else None  # type: ignore[attr-defined]  # embedding_dimension 为 G2 运行时实例属性（Protocol 未声明，LangChainVectorStore 与测试 fake 均提供）
        )
    )
    indexed_raw = await store.read_fingerprint(project_id)

    from inkflow.domain.models.vector_fingerprint import VectorFingerprint
    from inkflow.domain.services.vector_fingerprint import compare_fingerprints

    configured = VectorFingerprint.model_validate(configured_dict)
    indexed = VectorFingerprint.model_validate(indexed_raw) if indexed_raw else None
    stale, reason = compare_fingerprints(configured, indexed)
    mismatch = False
    if (
        indexed is not None
        and configured.embedding.dimension is not None
        and indexed.embedding.dimension is not None
        and configured.embedding.dimension != indexed.embedding.dimension
    ):
        mismatch = True
    elif indexed is None and configured.embedding.dimension is not None:
        probe = await store.probe_collection_dimension(project_id)
        mismatch = probe != 0 and probe != configured.embedding.dimension
    return {
        "configured_fp": configured_dict,
        "indexed_fp": indexed_raw,
        "stale": stale,
        "reason": reason,
        "dimension_mismatch": mismatch,
    }


async def get_vector_store_optional() -> VectorStoreProtocol | None:
    """获取 RAG 向量存储（可选）——未配置 embedding 时返回 None 而非抛错。

    #264：search semantic 恒空根因——get_search_service 硬编码 vector_store=None。
    此处兜底为 None：未配置 embedding 模型时 keyword 模式保持正常（懒装配降级），
    已配置时注入真实 vector_store（semantic 模式可用）。
    """
    try:
        return await get_vector_store()
    except RAGUnavailableError:
        return None
