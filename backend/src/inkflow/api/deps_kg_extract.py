"""#479 知识图谱提取依赖装配（G2）— 独立模块承载。

原 deps.py 装配 get_relation_extraction_service / get_kg_extract_scheduler 后
超 900 行护栏（check_file_length.py），故抽离瘦身：本模块只放 #479 提取相关的
两个 getter，deps.py 末尾 `from inkflow.api.deps_kg_extract import ...` re-export
（router 与 app.py lifespan 仍从 inkflow.api.deps 导入，命名空间不变）。

装配关系：get_relation_extraction_service 复用 deps.get_knowledge_graph_service
的八仓库装配（关系/项目/角色/世界观/大纲/时间线/伏笔/地图）+ 章节仓库；
key/LLM 客户端均为 factory 形态（G1 契约：AI 门禁调
key_manager_factory().list_providers()）；extraction_run_repo=None（run 记录落盘
归 #496 日志页）。get_kg_extract_scheduler 从 request.app.state.kg_scheduler 读取
lifespan 挂载的单例（未就绪 → 503；测试经 dependency_overrides 覆盖不经过此路径）。
"""

from __future__ import annotations

from typing import cast

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.api.deps import get_db
from inkflow.domain.services.relation_extraction_service import RelationExtractionService
from inkflow.infrastructure.scheduler.kg_extract_scheduler import KnowledgeExtractScheduler


def get_relation_extraction_service(
    db: AsyncSession = Depends(get_db),
) -> RelationExtractionService:
    """装配 RelationExtractionService（#479 G2：手动/定时知识图谱关系提取）。

    复用 get_knowledge_graph_service 的八仓库装配，另注入章节仓库；key/LLM 客户端
    均为 factory 形态（G1 契约：AI 门禁调 key_manager_factory().list_providers()）。
    """
    # 延迟 import：get_knowledge_graph_service 在 deps.py 定义，避免模块级循环导入
    from inkflow.api.deps import get_knowledge_graph_service
    from inkflow.core.config import config
    from inkflow.infrastructure.database.repositories.chapter_repo import (
        SQLiteChapterRepository,
    )
    from inkflow.infrastructure.database.repositories.character_repo import (
        SQLiteCharacterRepository,
    )
    from inkflow.infrastructure.database.repositories.foreshadowing_repo import (
        SQLiteForeshadowingRepository,
    )
    from inkflow.infrastructure.database.repositories.map_repo import (
        SQLiteMapRepository,
    )
    from inkflow.infrastructure.database.repositories.outline_repo import (
        SQLiteOutlineRepository,
    )
    from inkflow.infrastructure.database.repositories.timeline_repo import (
        SQLiteTimelineRepository,
    )
    from inkflow.infrastructure.database.repositories.world_repo import (
        SQLiteWorldRepository,
    )
    from inkflow.infrastructure.llm import LangChainLLMClient
    from inkflow.infrastructure.llm.key_manager import APIKeyManager

    def _get_key_manager() -> APIKeyManager:
        """构造 APIKeyManager（镜像 api/routers/settings.py 工厂模式）。"""
        return APIKeyManager(
            secret_key=config.secret_key,
            storage_dir=config.data_dir / "keys",
        )

    return RelationExtractionService(
        knowledge_graph_service=get_knowledge_graph_service(db),
        character_repo=SQLiteCharacterRepository(db),
        world_repo=SQLiteWorldRepository(db),
        outline_repo=SQLiteOutlineRepository(db),
        timeline_repo=SQLiteTimelineRepository(db),
        foreshadow_repo=SQLiteForeshadowingRepository(db),
        map_pin_repo=SQLiteMapRepository(db),
        chapter_repo=SQLiteChapterRepository(db),
        key_manager_factory=lambda: _get_key_manager(),
        llm_client_factory=lambda: LangChainLLMClient(default_model=config.llm_default_model),
        llm_default_model=config.llm_default_model,
        extraction_run_repo=None,
    )


def get_kg_extract_scheduler(request: Request) -> KnowledgeExtractScheduler:
    """获取 KnowledgeExtractScheduler（长生命周期单例，lifespan 挂载 app.state）。

    #479 G2: scheduler 由 lifespan 装配并持有应用级 session，挂载到
    app.state.kg_scheduler；status 端点经本 getter 读取。未就绪 → 503
    （测试经 dependency_overrides 覆盖，不经过此真实路径）。
    """
    scheduler = getattr(request.app.state, "kg_scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="定时提取调度器未就绪，请稍后重试")
    return cast(KnowledgeExtractScheduler, scheduler)
