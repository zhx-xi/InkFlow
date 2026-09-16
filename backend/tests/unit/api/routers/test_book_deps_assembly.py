"""RED 契约（#464）：get_book_service 的 volume_pipeline 必须装配真实 writer_factory/draft_service。

缺陷背景（0.10.0-rc4 实证 2026-08-18）：books.py `_build_book_service` 构造
BookVolumePipeline 时 writer_factory=None / draft_service=None（注释「真实 writer
装配留待 M2 冒烟」）→ book run 的 `_delegate_chapter` 必抛「writer_factory 未装配」
→ 章全 failed（零 token、execution_id=null），但 run 状态 completed（静默失败）。

本契约：调 books.get_book_service(db)（真实 deps 装配），断言返回实例的
volume_pipeline 的 writer_factory 和 draft_service **均非 None**（真实可用）。
修复后全部 PASS。

⚠️ RED 期形态：当前 writer_factory/draft_service 均 None → 断言 FAIL（干净 RED）。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from inkflow.api.routers import books
from inkflow.core.database import Base


def db_session():
    """模块级 in-memory SQLite 会话工厂（测试直接调用；pytest 9 禁直接调 fixture，
    镜像 test_planner_deps_assembly.py）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    return asyncio.run(_setup())


def _get_book_service():
    """装配缝契约测试：凭据解析按 #860 同源契约经 resolve_llm_credentials 打桩注入。

    本文件锁的是「volume_pipeline 装配完整」（#464），与凭据值无关；#860 修复后
    _build_book_service 复用 resolve_llm_credentials（keyless CI 下抛 422），故桩住
    该缝返回固定凭据（契约 fixture 适配，断言零改动，#821 先例）。
    """
    session_factory = db_session()
    with patch(
        "inkflow.api._llm_resolver.resolve_llm_credentials",
        return_value=("deepseek/deepseek-chat", "test-assembly-key", "https://example.test/v1"),
    ):
        return books.get_book_service(db=session_factory())


def test_volume_pipeline_writer_factory_injected():
    """get_book_service 的 volume_pipeline._writer_factory 必须非 None。"""
    svc = _get_book_service()
    pipeline = svc._volume_pipeline
    assert pipeline is not None, "volume_pipeline 未装配"
    assert pipeline._writer_factory is not None, "writer_factory 未装配（book run 章委托必败）"
    assert callable(pipeline._writer_factory), "writer_factory 必须可调用"


def test_volume_pipeline_draft_service_injected():
    """get_book_service 的 volume_pipeline._draft_service 必须非 None。"""
    svc = _get_book_service()
    pipeline = svc._volume_pipeline
    assert pipeline is not None, "volume_pipeline 未装配"
    assert pipeline._draft_service is not None, "draft_service 未装配（草稿回收必败）"


def test_book_service_volume_pipeline_assembly():
    """装配完整快照：writer_factory + draft_service 同时非 None。"""
    svc = _get_book_service()
    pipeline = svc._volume_pipeline
    missing = [
        name
        for name in ("_writer_factory", "_draft_service")
        if getattr(pipeline, name, None) is None
    ]
    assert missing == [], f"volume_pipeline 装配缺口: {missing}"


# ── F59-M4 (#965) B6: writer_factory 按 cfg.reasoning_effort 解析思考档位 ──


def test_writer_factory_passes_project_reasoning_effort():
    """B6：cfg.reasoning_effort='high' → writer_factory 传该档位给 build_agentic_writer。

    RED：当前 _writer_factory 调用 build_agentic_writer 未传 reasoning_effort → mock kwargs
    无该键 → None != 'high' 翻红（B6 缺功能）。

    build_agentic_writer 是 _build_book_service 内的局部绑定（闭包捕获），故须在
    get_book_service 装配期 patch 源模块，让闭包快照到 mock（post-assembly patch 无效）。
    """
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from inkflow.domain.models.project import ProjectConfig

    cfg = ProjectConfig.model_construct(reasoning_effort="high")
    with (
        patch("inkflow.infrastructure.agent.agentic_writer.build_agentic_writer") as m_baw,
        patch(
            "inkflow.infrastructure.database.repositories.project_repo.SQLiteProjectRepository.get",
            new=AsyncMock(return_value=SimpleNamespace(config=cfg)),
        ),
    ):
        svc = _get_book_service()
        factory = svc._writer_factory
        result = asyncio.run(
            factory(
                system_prompt="你是章节写手",
                expected_project_id=uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
                expected_chapter_id=None,
            )
        )

    assert m_baw.call_args.kwargs.get("reasoning_effort") == "high", (
        f"writer_factory 必须把项目档位透传给 build_agentic_writer（B6），"
        f"实得 kwargs={m_baw.call_args.kwargs!r}"
    )
    assert result is m_baw.return_value, "writer_factory 必须透传 build_agentic_writer 返回值"


def test_writer_factory_uses_global_when_cfg_missing():
    """B6：cfg=None（无项目级）→ writer_factory 按全局档位解析传给 build_agentic_writer。

    RED：当前 _writer_factory 未传 reasoning_effort → None != 全局值 翻红（B6 缺功能）。
    """
    from unittest.mock import patch

    from inkflow.core.config import config

    original = config.llm_reasoning_effort
    config.llm_reasoning_effort = "medium"
    try:
        with patch("inkflow.infrastructure.agent.agentic_writer.build_agentic_writer") as m_baw:
            svc = _get_book_service()
            factory = svc._writer_factory
            asyncio.run(
                factory(
                    system_prompt="你是章节写手",
                    expected_project_id=None,
                    expected_chapter_id=None,
                )
            )
        assert m_baw.call_args.kwargs.get("reasoning_effort") == "medium", (
            f"cfg 缺失时 writer_factory 必须按全局档位解析（B6），"
            f"实得 kwargs={m_baw.call_args.kwargs!r}"
        )
    finally:
        config.llm_reasoning_effort = original


# ── #1200：章级写作要求取值 getter（chapters.writing_requirements 列）─────


def test_chapter_requirements_getter_reads_column():
    """装配层 `_chapter_requirements_getter` 读 `chapters.writing_requirements` 列（#1200）.

    真实形态：GUI 章级栏 → PATCH /api/v1/chapters/{id} → 该列；book 三轨经
    `BookService._to_chapter_dicts` 用它把列值搬进章 dict → brief。
    """
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    svc = _get_book_service()
    getter = svc._chapter_requirements_getter
    assert getter is not None, "chapter_requirements_getter 未装配（#1200 回归）"

    cid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    with patch(
        "inkflow.infrastructure.database.repositories.chapter_repo."
        "SQLiteChapterRepository.get_chapter",
        new=AsyncMock(return_value=SimpleNamespace(writing_requirements="本章需写主角独立出诊")),
    ):
        assert asyncio.run(getter(cid)) == "本章需写主角独立出诊"


def test_chapter_requirements_getter_degrades_to_none():
    """章不存在 / 列为空 / 异常 → None（调用方回退 `outline.extra`，绝不炸编排）。"""
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    svc = _get_book_service()
    getter = svc._chapter_requirements_getter
    cid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
    repo_path = (
        "inkflow.infrastructure.database.repositories.chapter_repo."
        "SQLiteChapterRepository.get_chapter"
    )

    # 章不存在
    with patch(repo_path, new=AsyncMock(return_value=None)):
        assert asyncio.run(getter(cid)) is None

    # 列值为空串
    with patch(repo_path, new=AsyncMock(return_value=SimpleNamespace(writing_requirements=""))):
        assert asyncio.run(getter(cid)) is None

    # 仓储抛异常（uuid 溢出等）→ 吞掉返 None
    with patch(repo_path, new=AsyncMock(side_effect=OverflowError("int too large"))):
        assert asyncio.run(getter(cid)) is None
