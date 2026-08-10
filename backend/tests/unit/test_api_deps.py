"""inkflow.api.deps 依赖注入装配层单元测试。

覆盖 deps.py 全部 service getter（Project/Chapter/Writing/Context/Summary/
Character/World/Outline/Timeline/Foreshadowing/Extraction/Audit/Style）的
装配正确性（类型 + 仓储 session 注入），以及 get_vector_store 懒加载单例
与初始化失败 → RAGUnavailableError 映射（Issue #104 Phase 3 覆盖率补齐）。

注: getter 均为同步函数（db 为 FastAPI 注入的 AsyncSession），测试用
MagicMock 模拟 session；get_vector_store 的 LangChainVectorStore /
HuggingFaceBgeEmbeddings 全程 mock，避免真实下载 BGE 模型（~100MB）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inkflow.api import deps
from inkflow.domain.ports.extraction_errors import RAGUnavailableError
from inkflow.domain.services.audit_service import AuditService
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.domain.services.character_service import CharacterService
from inkflow.domain.services.context_service import ContextService
from inkflow.domain.services.extraction_service import ExtractionService
from inkflow.domain.services.foreshadowing_service import ForeshadowingService
from inkflow.domain.services.outline_service import OutlineService
from inkflow.domain.services.project_service import ProjectService
from inkflow.domain.services.style_service import StyleService
from inkflow.domain.services.summary_service import SummaryService
from inkflow.domain.services.timeline_service import TimelineService
from inkflow.domain.services.world_service import WorldService
from inkflow.domain.services.writing_service import WritingService
from inkflow.infrastructure.database.repositories.chapter_repo import (
    SQLiteChapterRepository,
)
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)


@pytest.fixture
def db() -> MagicMock:
    """Mock AsyncSession — service getter 仅透传 session，不执行 SQL。"""
    return MagicMock()


@pytest.fixture(autouse=True)
def _reset_vector_store_singleton():
    """每个用例前后重置模块级 _vector_store 单例，隔离懒加载状态。"""
    original = deps._vector_store
    deps._vector_store = None
    yield
    deps._vector_store = original


# ── 各 service getter 装配正确性 ─────────────────────────────────


def test_get_project_service_injects_db(db) -> None:
    """get_project_service → ProjectService，且仓储持有同一 session。"""
    svc = deps.get_project_service(db)
    assert isinstance(svc, ProjectService)
    assert svc._repo._session is db


def test_get_chapter_service_injects_db(db) -> None:
    """get_chapter_service → ChapterService，且仓储持有同一 session。"""
    svc = deps.get_chapter_service(db)
    assert isinstance(svc, ChapterService)
    assert svc._repo._session is db


def test_get_writing_service_assembles_full_stack(db) -> None:
    """get_writing_service → WritingService（LLM 客户端 + Prompt 管理器 + 双仓储）。"""
    svc = deps.get_writing_service(db)
    assert isinstance(svc, WritingService)
    assert isinstance(svc._project_repo, SQLiteProjectRepository)
    assert isinstance(svc._chapter_repo, SQLiteChapterRepository)
    assert svc._project_repo._session is db
    assert svc._chapter_repo._session is db


def test_get_context_service_registers_five_sources(db) -> None:
    """get_context_service → ContextService，5 类 ContextSourceType 槽位全注册.

    F28 变更（2026-08-11）: 追加 ContextSourceType.PREFERENCE（PreferenceSource，
    已学偏好注入，spec f28 §5.4）。
    """
    from inkflow.domain.models.context import ContextSourceType

    svc = deps.get_context_service(db)
    assert isinstance(svc, ContextService)
    assert set(svc._sources) == {
        ContextSourceType.OUTLINE,
        ContextSourceType.CHARACTER_SETTING,
        ContextSourceType.WORLD_SETTING,
        ContextSourceType.FORESHADOWING,
        ContextSourceType.PREFERENCE,
    }
    assert svc._summary_repo._session is db


def test_get_summary_service_assembles_stack(db) -> None:
    """get_summary_service → SummaryService（summary 仓储 + LLM + 章节读取器）。"""
    svc = deps.get_summary_service(db)
    assert isinstance(svc, SummaryService)
    assert svc._repo._session is db
    assert svc._chapters._session is db


def test_get_character_service_assembles_extractor(db) -> None:
    """get_character_service → CharacterService（同一仓储注入 extractor 与 project_repo）。"""
    from inkflow.domain.services._character_extractor import CharacterExtractor

    svc = deps.get_character_service(db)
    assert isinstance(svc, CharacterService)
    assert svc._repo._session is db
    assert svc._project_repo._session is db
    assert isinstance(svc._extractor, CharacterExtractor)
    assert svc._extractor._repo is svc._repo  # 同一仓储实例复用


def test_get_world_service_assembles_extractor(db) -> None:
    """get_world_service → WorldService（extractor 复用同一仓储实例）。"""
    from inkflow.domain.services._world_extractor import WorldExtractor

    svc = deps.get_world_service(db)
    assert isinstance(svc, WorldService)
    assert svc._repo._session is db
    assert svc._project_repo._session is db
    assert isinstance(svc._extractor, WorldExtractor)
    assert svc._extractor._repo is svc._repo


def test_get_outline_service_assembles_generator(db) -> None:
    """get_outline_service → OutlineService（generator 复用同一仓储实例）。"""
    from inkflow.domain.services._outline_generator import OutlineGenerator

    svc = deps.get_outline_service(db)
    assert isinstance(svc, OutlineService)
    assert svc._repo._session is db
    assert svc._project_repo._session is db
    assert isinstance(svc._generator, OutlineGenerator)
    assert svc._generator._repo is svc._repo


def test_get_timeline_service_injects_repos(db) -> None:
    """get_timeline_service → TimelineService（事件仓储 + 项目仓储同 session）。"""
    svc = deps.get_timeline_service(db)
    assert isinstance(svc, TimelineService)
    assert svc._repo._session is db
    assert svc._project_repo._session is db


def test_get_foreshadowing_service_injects_repos(db) -> None:
    """get_foreshadowing_service → ForeshadowingService（三仓储同 session）。"""
    svc = deps.get_foreshadowing_service(db)
    assert isinstance(svc, ForeshadowingService)
    assert svc._repo._session is db
    assert svc._project_repo._session is db
    assert svc._timeline_repo._session is db


async def test_get_extraction_service_assembles_facade(db) -> None:
    """get_extraction_service → ExtractionService（F14 门面全装配，vector_store mock）。

    F19 B+ 改造（spec §5.2）：get_extraction_service 改 async（内部 await
    get_vector_store）——同步 patch 升级为 AsyncMock 并 await。
    """
    with patch.object(deps, "get_vector_store", new=AsyncMock()) as mock_vs:
        svc = await deps.get_extraction_service(db)
    assert isinstance(svc, ExtractionService)
    assert svc._project_repo._session is db
    assert svc._chapter_repo._session is db
    assert svc._run_repo._session is db
    assert isinstance(svc._character_service, CharacterService)
    assert isinstance(svc._style_service, StyleService)
    mock_vs.assert_awaited_once()
    assert svc._vector_store is not None


def test_get_audit_service_assembles_facade(db) -> None:
    """get_audit_service → AuditService（F15 门面全装配，audit_repo 同 session）。"""
    svc = deps.get_audit_service(db)
    assert isinstance(svc, AuditService)
    assert svc._project_repo._session is db
    assert svc._chapter_repo._session is db
    assert svc._run_repo._session is db
    assert svc._audit_repo._session is db
    assert isinstance(svc._timeline_service, TimelineService)


def test_get_style_service_assembles_analyzer(db) -> None:
    """get_style_service → StyleService（F16 门面，StyleLLMAnalyzer 装配）。"""
    from inkflow.domain.services._style_llm_analyzer import StyleLLMAnalyzer

    svc = deps.get_style_service(db)
    assert isinstance(svc, StyleService)
    assert svc._project_repo._session is db
    assert svc._chapter_repo._session is db
    assert isinstance(svc._llm_analyzer, StyleLLMAnalyzer)


# ── get_vector_store 懒加载单例（spec §5.2，F19 B+ 改造后 async）──


async def test_get_vector_store_lazy_init_and_cached(db) -> None:
    """首次调用初始化 LangChainVectorStore（API embedding），再次调用返回同一实例。

    F19 B+ 改造（spec §5.2/§5.3）：装配从 ProviderConfig 读 embedding 模型
    （repo.list + APIKeyManager.load），不再用 HuggingFaceBgeEmbeddings；
    get_vector_store 改 async。契约细节以 test_deps_embedding.py 为准。
    """
    from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel

    fake_store = MagicMock()
    repo = MagicMock()
    repo.list = AsyncMock(
        return_value=[
            ProviderConfig(
                name="openai",
                builtin_key="openai",
                base_url="https://api.test.example/v1",
                models=[ProviderModel(id="text-embedding-3-small", type="embedding")],
            )
        ]
    )
    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        patch(
            "inkflow.infrastructure.llm.key_manager.APIKeyManager.load",
            return_value="sk-test-123",
        ),
        patch(
            "inkflow.infrastructure.rag.langchain_vector_store.LangChainVectorStore",
            return_value=fake_store,
        ) as mock_vs,
    ):
        first = await deps.get_vector_store()
        second = await deps.get_vector_store()

    assert first is fake_store
    assert second is fake_store
    mock_vs.assert_called_once()


async def test_get_vector_store_init_failure_raises_rag_unavailable(db) -> None:
    """LangChainVectorStore 初始化抛异常 → RAGUnavailableError（500 语义）。

    F19 B+ 改造后：无 embedding 模型（空注册表）→ RAGUnavailableError（E1 契约），
    单例保持 None 可重试。LangChainVectorStore 构造失败路径同 test_deps_embedding.py
    的 E1/E4（未配置 → RAGUnavailableError）。
    """
    repo = MagicMock()
    repo.list = AsyncMock(return_value=[])
    with (
        patch(
            "inkflow.infrastructure.database.repositories.provider_config_repo.SQLiteProviderConfigRepository",
            return_value=repo,
        ),
        pytest.raises(RAGUnavailableError, match="未配置 embedding 模型"),
    ):
        await deps.get_vector_store()
    # 初始化失败后单例仍为 None（下次调用重试）
    assert deps._vector_store is None
