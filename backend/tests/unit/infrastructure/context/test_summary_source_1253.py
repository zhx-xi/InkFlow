"""#1253 契约：SummarySource 适配器把前文摘要接入 F6 组装通道（真实 sqlite 表值驱动）.

背景（#1236 取证 + #1253 实施）：
- spec §3.2 规划 `chapter_summary`（dynamic 层前文摘要）；
- 设施大半就位：ChapterSummary 模型 / chapter_summaries 表 / SummaryService（§4.6）/
  ContextService(summary_repo=) 注入点；
- 唯一缺口 = SummarySource 适配器未实现 → 运行时注册表无该槽位；
- 本文件钉住「缺口已补齐」的四个面：
  1. 注册表含 CHAPTER_SUMMARY（get_context_service 装配 6 源）；
  2. 有摘要（真实 chapter_summaries 行）→ build_context 产出 chapter_summary block
     （dynamic 层，章节序号倒序，≤ summary_max_chapters）；
  3. 无摘要 / 摘要读取失败 → 不阻断组装，只是不产出该 block（spec §4.6 失败策略）；
  4. 可证伪自证：注册表去掉 SummarySource → 断言 2 必须 FAIL。

⚠️ #1200 教训：断言走**真实 repo / 真实表值**（in-memory sqlite + SQLiteSummaryRepository），
不用手工构造的 fake，避免「同源假绿」。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.api import deps
from inkflow.core.database import Base
from inkflow.domain.models.context import (
    SOURCE_LAYER,
    ContextLayer,
    ContextRequest,
    ContextSourceType,
)
from inkflow.domain.services.context_service import ContextService
from inkflow.infrastructure.context.sources import SummarySource
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.context import ChapterSummaryORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.chapter_repo import SQLiteChapterRepository
from inkflow.infrastructure.database.repositories.summary_repo import SQLiteSummaryRepository

_MODEL = "openai/gpt-4o"


# ── 真实数据面夹具（in-memory SQLite + 真实 ORM 行）────────────────


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（真实表结构）."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project_and_chapters(db_session):
    """1 个项目 + 3 章（order_index 1.0 / 2.0 / 3.0），准备作为摘要来源."""
    project = ProjectORM(name="摘要源测试项目")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    chapters = []
    for idx in (1.0, 2.0, 3.0):
        ch = ChapterORM(
            project_id=project.id,
            title=f"第 {int(idx)} 章",
            content="正文内容",
            status="draft",
            word_count=4,
            order_index=idx,
        )
        db_session.add(ch)
        await db_session.commit()
        await db_session.refresh(ch)
        chapters.append(ch)
    return project, chapters


async def _seed_summary(
    db: AsyncSession, chapter_id: int, text: str, *, minutes_ago: int = 0
) -> None:
    """向 chapter_summaries 表写入真实行（模拟已生成摘要缓存）."""
    now = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    db.add(
        ChapterSummaryORM(
            chapter_id=chapter_id,
            summary=text,
            model=_MODEL,
            created_at=now,
            updated_at=now,
        )
    )
    await db.commit()


def _source(
    repo: SQLiteSummaryRepository | object, session: AsyncSession, **kwargs: object
) -> SummarySource:
    """构造 SummarySource（真实 summary repo + 真实 chapter repo 补序号）."""
    return SummarySource(
        repo,  # type: ignore[arg-type]  # 允许注入 ExplodingRepo 探针
        chapter_repo=SQLiteChapterRepository(session),
        summary_max_chapters=10,
        model=_MODEL,
        **kwargs,  # type: ignore[arg-type]  # 透传覆盖项（探针用）
    )


def _req(project_id: int, chapter_id: int, **overrides: object) -> ContextRequest:
    defaults: dict[str, object] = {
        "project_id": uuid.UUID(int=project_id),
        "chapter_id": uuid.UUID(int=chapter_id),
        "model": _MODEL,
        "writing_requirements": "续写第 4 章",
    }
    defaults.update(overrides)
    return ContextRequest(**defaults)  # type: ignore[arg-type]  # dict 覆盖项由调用方保证


def _svc(session: AsyncSession, source: SummarySource) -> ContextService:
    """装配 ContextService（deps 之外的显式 1 源注册，供端到端/降级断言）."""
    return ContextService(
        sources={ContextSourceType.CHAPTER_SUMMARY: source},
        summary_repo=SQLiteSummaryRepository(session),
    )


async def _summaries_in(result) -> list:
    """结果里全部 chapter_summary 来源的 block（含层信息）."""
    return [b for b in result.blocks if b.item.source == ContextSourceType.CHAPTER_SUMMARY]


# ── 1. 注册表：槽位已补 ──────────────────────────────────────────


def test_deps_registry_contains_chapter_summary(db_session) -> None:
    """get_context_service 装配的注册表必须含 CHAPTER_SUMMARY（#1253 补齐缺口）."""
    svc = deps.get_context_service(db_session)
    assert isinstance(svc, ContextService)
    assert ContextSourceType.CHAPTER_SUMMARY in svc._sources
    assert isinstance(svc._sources[ContextSourceType.CHAPTER_SUMMARY], SummarySource)


def test_chapter_summary_maps_to_dynamic_layer() -> None:
    """层级映射：chapter_summary ∈ dynamic（spec §3.2）."""
    assert SOURCE_LAYER[ContextSourceType.CHAPTER_SUMMARY] is ContextLayer.DYNAMIC


# ── 2. 产出：真实表值驱动 ───────────────────────────────────────


async def test_collect_produces_items_from_real_table(db_session, project_and_chapters) -> None:
    """真实 chapter_summaries 行 → collect 产出「第 N 章摘要」条目（倒序）."""
    project, chapters = project_and_chapters
    await _seed_summary(db_session, chapters[0].id, "第一章摘要正文")
    await _seed_summary(db_session, chapters[2].id, "第三章摘要正文")

    source = _source(SQLiteSummaryRepository(db_session), db_session)
    items = await source.collect(uuid.UUID(int=project.id), uuid.UUID(int=chapters[1].id))

    assert [i.title for i in items] == ["第 3 章摘要", "第 1 章摘要"]  # order_index 倒序
    assert [i.content for i in items] == ["第三章摘要正文", "第一章摘要正文"]
    assert all(i.source == ContextSourceType.CHAPTER_SUMMARY for i in items)
    assert items[0].metadata["chapter_id"] == str(uuid.UUID(int=chapters[2].id))
    assert items[0].metadata["chapter_index"] == 3.0


async def test_build_context_yields_chapter_summary_block(db_session, project_and_chapters) -> None:
    """有摘要缓存 → build_context 产出 dynamic 层 chapter_summary block（端到端）."""
    project, chapters = project_and_chapters
    await _seed_summary(db_session, chapters[0].id, "第一章摘要正文")
    await _seed_summary(db_session, chapters[1].id, "第二章摘要正文")
    await _seed_summary(db_session, chapters[2].id, "第三章摘要正文")

    repo = SQLiteSummaryRepository(db_session)
    svc = _svc(db_session, _source(repo, db_session))
    result = await svc.build_context(_req(project.id, chapters[2].id))

    blocks = await _summaries_in(result)
    assert len(blocks) == 3
    assert all(b.layer is ContextLayer.DYNAMIC for b in blocks)
    # 层内 priority 降序 → 章节序号倒序（最新在前）
    assert [b.item.title for b in blocks] == [
        "第 3 章摘要",
        "第 2 章摘要",
        "第 1 章摘要",
    ]
    # 最新章摘要优先注入：其 content 与 title 一致配对（防「序号与内容错位」）
    assert blocks[0].item.content == "第三章摘要正文"
    assert blocks[0].item.priority == 3
    assert blocks[-1].item.content == "第一章摘要正文"
    # 注入文本可读（render_system_prompt 输出形如「## 第 3 章摘要」）
    assert "## 第 3 章摘要" in svc.render_system_prompt(result)


async def test_candidate_count_capped_by_summary_max_chapters(
    db_session, project_and_chapters
) -> None:
    """候选数受 summary_max_chapters 约束（spec §4.1：最多 N 条）."""
    project, chapters = project_and_chapters
    for ch in chapters:
        await _seed_summary(db_session, ch.id, f"{ch.title}摘要")

    repo = SQLiteSummaryRepository(db_session)
    source = SummarySource(
        repo,
        chapter_repo=SQLiteChapterRepository(db_session),
        summary_max_chapters=2,
        model=_MODEL,
    )
    items = await source.collect(uuid.UUID(int=project.id), uuid.UUID(int=chapters[0].id))

    assert [i.title for i in items] == ["第 3 章摘要", "第 2 章摘要"]  # 只取最近 2 条


async def test_other_project_summaries_not_injected(db_session, project_and_chapters) -> None:
    """别的项目的摘要不得混入（repo 按 project_id 过滤的真实语义）."""
    project, chapters = project_and_chapters
    other = ProjectORM(name="另一个项目")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    other_ch = ChapterORM(
        project_id=other.id,
        title="别项目第 1 章",
        content="x",
        status="draft",
        word_count=1,
        order_index=1.0,
    )
    db_session.add(other_ch)
    await db_session.commit()
    await db_session.refresh(other_ch)
    await _seed_summary(db_session, other_ch.id, "别项目摘要")
    await _seed_summary(db_session, chapters[0].id, "本项目摘要")

    source = _source(SQLiteSummaryRepository(db_session), db_session)
    items = await source.collect(uuid.UUID(int=project.id), uuid.UUID(int=chapters[1].id))

    assert [i.content for i in items] == ["本项目摘要"]


# ── 3. 降级：不阻断（spec §4.6 失败策略）────────────────────────


async def test_no_summary_yields_no_block_but_no_error(db_session, project_and_chapters) -> None:
    """无摘要缓存 → 不产出该 block（正常空路径，不报错，spec §4.6）."""
    project, chapters = project_and_chapters
    repo = SQLiteSummaryRepository(db_session)
    svc = _svc(db_session, _source(repo, db_session))
    result = await svc.build_context(_req(project.id, chapters[0].id))

    assert await _summaries_in(result) == []
    # 组装本身仍成功（其它 layer 正常产出）
    assert any(b.item.source == ContextSourceType.WRITING_REQUIREMENTS for b in result.blocks)


async def test_repo_failure_does_not_block_assembly(db_session, project_and_chapters) -> None:
    """摘要读取失败（反向断言）→ 不阻断组装：不抛错，只是不产出该 block."""

    class ExplodingRepo:
        """读摘要即炸（模拟 LLM/DB 侧失败路径）."""

        async def get(self, chapter_id: object) -> object:
            raise RuntimeError("summary read down")

        async def upsert(self, chapter_id: object, summary: str, model: str) -> object:
            raise RuntimeError("summary read down")

        async def list_recent(self, project_id: int, limit: int = 10) -> list:
            raise RuntimeError("summary read down")

    project, chapters = project_and_chapters
    repo = ExplodingRepo()
    source = _source(repo, db_session)  # type: ignore[arg-type]  # ExplodingRepo 探针
    svc = _svc(db_session, source)

    # 源层契约：collect 自身咽下异常（spec §4.6 降级），不把失败甩给组装层
    assert await source.collect(uuid.UUID(int=project.id), None) == []

    result = await svc.build_context(_req(project.id, chapters[0].id))
    assert await _summaries_in(result) == []
    assert any(b.item.source == ContextSourceType.WRITING_REQUIREMENTS for b in result.blocks)


async def test_collect_without_chapter_or_project_is_empty(
    db_session, project_and_chapters
) -> None:
    """chapter_id=None（chat agent 未锁定章节）不报错；空项目返回空列表."""
    project, chapters = project_and_chapters
    await _seed_summary(db_session, chapters[0].id, "第一章摘要正文")
    source = _source(SQLiteSummaryRepository(db_session), db_session)

    assert len(await source.collect(uuid.UUID(int=project.id), None)) == 1
    assert await source.collect(uuid.UUID(int=10**6), uuid.UUID(int=chapters[0].id)) == []


# ── 4. 可证伪自证：去掉注册即断 ─────────────────────────────────


async def test_falsification_removing_source_breaks_production(
    db_session, project_and_chapters
) -> None:
    """可证伪自证：注册表里去掉 SummarySource → 断言 2 的产出必然消失（非假绿）."""
    project, chapters = project_and_chapters
    await _seed_summary(db_session, chapters[0].id, "第一章摘要正文")

    repo = SQLiteSummaryRepository(db_session)
    registered = _svc(db_session, _source(repo, db_session))
    unregistered = ContextService(sources={}, summary_repo=repo)

    req = _req(project.id, chapters[0].id)
    assert await _summaries_in(await registered.build_context(req))
    assert await _summaries_in(await unregistered.build_context(req)) == []
