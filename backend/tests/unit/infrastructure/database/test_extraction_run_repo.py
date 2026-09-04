"""SQLExtractionRunRepository 集成测试 — in-memory SQLite（F14 仓储层 RED→GREEN）.

覆盖 ExtractionRunRepositoryProtocol 全部方法（spec §8.1 / §9 仓储测试）:
- get 命中 / 未命中（含项目隔离）
- upsert 新建（字段默认值 + id 自增分配）
- upsert 同键 (project_id, type, source_key) 更新（SQLite ON CONFLICT DO UPDATE：
  字段整体覆盖 + run_at 更新，行数不增、id 不变）
- upsert 不同源 / 不同项目并存（唯一约束粒度 = (项目, 类型, 源)）
- list 按 type 过滤（不传 = 全部）、run_at DESC 排序（最新在前）、分页
- 项目硬删 → extraction_runs 级联清理（FK ON DELETE CASCADE）
- 空表 list → ([], 0)

注: fixture 显式开启 PRAGMA foreign_keys=ON（SQLite 默认关闭），
FK CASCADE 语义才生效（同 F13 测试惯例）。
SQLite 存储时区感知时间会丢失 tzinfo（读回为 naive），
往返断言用 naive 时间戳（项目既有行为，同 F13/F12）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.extraction import (
    ExtractionRun,
    ExtractionStatus,
    ExtractionType,
)
from inkflow.infrastructure.database.models.extraction_run import ExtractionRunORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.extraction_run_repo import (
    SQLExtractionRunRepository,
)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（启用 FK 级联）."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session):
    """一个基础项目（extraction_runs 的 FK 依赖）."""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _now() -> datetime:
    """当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _dt(day: int) -> datetime:
    """构造 2026-01-day 的 UTC 时间（时区感知，测试用固定时间戳）."""
    return datetime(2026, 1, day, tzinfo=UTC)


def _run(
    project: ProjectORM,
    type_: ExtractionType,
    source_key: str,
    **kw,
) -> ExtractionRun:
    """构造待持久化的提取运行领域对象.

    领域 id 为 0 占位（DB 自增分配，读回时以真实 int 返回）；
    project_id 用持久化返回的 project.id 映射为 UUID（UUID.int 陷阱）。
    可通过 kw 覆盖 content_hash/status/created_count/updated_count/
    warnings_json/error/model/indexed/run_at 等字段.
    """
    return ExtractionRun(
        id=kw.pop("id", 0),
        project_id=uuid.UUID(int=project.id),
        type=type_,
        source_key=source_key,
        content_hash=kw.pop("content_hash", f"hash-{source_key}"),
        status=kw.pop("status", ExtractionStatus.SUCCESS),
        created_count=kw.pop("created_count", 0),
        updated_count=kw.pop("updated_count", 0),
        warnings_json=kw.pop("warnings_json", "[]"),
        error=kw.pop("error", None),
        model=kw.pop("model", None),
        indexed=kw.pop("indexed", False),
        run_at=kw.pop("run_at", _now()),
        **kw,
    )


async def _count_rows(db_session, project_id: int) -> int:
    """直接查表统计某项目的 run 行数（绕过 repo，验证持久化真相）."""
    result = await db_session.execute(
        select(func.count())
        .select_from(ExtractionRunORM)
        .where(ExtractionRunORM.project_id == project_id)
    )
    return result.scalar_one()


@pytest.mark.integration
class TestExtractionRunRepository:
    """SQLExtractionRunRepository 集成测试."""

    # ── upsert 新建 + get ──

    async def test_upsert_creates_and_get_roundtrip(self, db_session, project):
        """upsert 新建落库（id 自增、字段默认值），get 按 (项目, 类型, 源) 读回."""
        repo = SQLExtractionRunRepository(db_session)
        saved = await repo.upsert(
            _run(
                project,
                ExtractionType.CHARACTER,
                "chapter-1",
                content_hash="abc123",
                created_count=3,
                updated_count=1,
                warnings_json='["w1"]',
                model="gpt-4o",
                indexed=True,
                run_at=_dt(1),
            )
        )

        assert isinstance(saved.id, int)
        assert saved.id > 0  # DB 自增分配
        assert saved.project_id == uuid.UUID(int=project.id)
        assert saved.type == ExtractionType.CHARACTER
        assert saved.source_key == "chapter-1"
        assert saved.content_hash == "abc123"
        assert saved.status == ExtractionStatus.SUCCESS
        assert saved.created_count == 3
        assert saved.updated_count == 1
        assert saved.warnings_json == '["w1"]'
        assert saved.error is None
        assert saved.model == "gpt-4o"
        assert saved.indexed is True
        # SQLite 读回丢失 tzinfo（项目既有行为）→ 断言用 naive 时间戳
        assert saved.run_at == datetime(2026, 1, 1)

        # 持久化验证：直接查表
        assert await _count_rows(db_session, project.id) == 1

        got = await repo.get(project.id, ExtractionType.CHARACTER, "chapter-1")
        assert got is not None
        assert got.id == saved.id
        assert got.content_hash == "abc123"
        assert got.model == "gpt-4o"
        assert got.indexed is True
        assert got.run_at == saved.run_at

    async def test_get_miss_returns_none(self, db_session, project):
        """get 对不存在的 (项目, 类型, 源) 返回 None（含跨项目隔离）."""
        repo = SQLExtractionRunRepository(db_session)
        await repo.upsert(_run(project, ExtractionType.CHARACTER, "chapter-1"))

        # 未知源
        assert await repo.get(project.id, ExtractionType.CHARACTER, "chapter-999") is None
        # 未知类型
        assert await repo.get(project.id, ExtractionType.SETTING, "chapter-1") is None

        # 项目隔离：其他项目查不到
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.get(other.id, ExtractionType.CHARACTER, "chapter-1") is None

    # ── upsert 同键更新（ON CONFLICT DO UPDATE）──

    async def test_upsert_same_key_updates_overwrites_all_fields(self, db_session, project):
        """同键 upsert → 单行更新：字段整体覆盖 + run_at 更新，行数不增、id 不变."""
        repo = SQLExtractionRunRepository(db_session)
        first = await repo.upsert(
            _run(
                project,
                ExtractionType.FORESHADOWING,
                "chapter-2",
                content_hash="hash-v1",
                status=ExtractionStatus.SUCCESS,
                created_count=5,
                updated_count=0,
                warnings_json="[]",
                error=None,
                model="gpt-4o",
                indexed=False,
                run_at=_dt(1),
            )
        )

        second = await repo.upsert(
            _run(
                project,
                ExtractionType.FORESHADOWING,
                "chapter-2",
                content_hash="hash-v2",
                status=ExtractionStatus.SKIPPED,
                created_count=0,
                updated_count=0,
                warnings_json='["内容未变更"]',
                error="boom",
                model=None,
                indexed=True,
                run_at=_dt(2),
            )
        )

        # 单行（未新增），id 不变
        assert await _count_rows(db_session, project.id) == 1
        assert second.id == first.id

        # 字段整体覆盖为第二次的值
        assert second.content_hash == "hash-v2"
        assert second.status == ExtractionStatus.SKIPPED
        assert second.created_count == 0
        assert second.warnings_json == '["内容未变更"]'
        assert second.error == "boom"
        assert second.model is None
        assert second.indexed is True
        # run_at 更新为第二次运行时间（naive 读回）
        assert second.run_at == datetime(2026, 1, 2)
        assert second.run_at != first.run_at

        # get 读回与第二次一致
        got = await repo.get(project.id, ExtractionType.FORESHADOWING, "chapter-2")
        assert got is not None
        assert got.content_hash == "hash-v2"
        assert got.status == ExtractionStatus.SKIPPED

    async def test_upsert_different_sources_and_projects_coexist(self, db_session, project):
        """唯一约束粒度 = (项目, 类型, 源)：不同源 / 不同项目互不冲突."""
        repo = SQLExtractionRunRepository(db_session)
        s1 = await repo.upsert(_run(project, ExtractionType.CHARACTER, "chapter-1"))
        s2 = await repo.upsert(_run(project, ExtractionType.CHARACTER, "chapter-2"))
        s3 = await repo.upsert(_run(project, ExtractionType.SETTING, "chapter-1"))

        assert len({s1.id, s2.id, s3.id}) == 3
        assert await _count_rows(db_session, project.id) == 3

        # 不同项目，同类型同源 → 各自一行
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        s4 = await repo.upsert(_run(other, ExtractionType.CHARACTER, "chapter-1"))
        assert s4.id != s1.id
        assert await _count_rows(db_session, other.id) == 1

    # ── list ──

    async def test_list_filters_by_type(self, db_session, project):
        """list 按 type 精确过滤（不传 = 全部）；total 为过滤后总数."""
        repo = SQLExtractionRunRepository(db_session)
        await repo.upsert(_run(project, ExtractionType.CHARACTER, "chapter-1"))
        await repo.upsert(_run(project, ExtractionType.CHARACTER, "chapter-2"))
        await repo.upsert(_run(project, ExtractionType.SETTING, "manual"))

        all_items, all_total = await repo.list(project.id)
        assert all_total == 3
        assert {r.source_key for r in all_items} == {"chapter-1", "chapter-2", "manual"}

        char_items, char_total = await repo.list(project.id, type=ExtractionType.CHARACTER)
        assert char_total == 2
        assert {r.source_key for r in char_items} == {"chapter-1", "chapter-2"}
        assert all(r.type == ExtractionType.CHARACTER for r in char_items)

        setting_items, setting_total = await repo.list(project.id, type=ExtractionType.SETTING)
        assert setting_total == 1
        assert setting_items[0].source_key == "manual"

        # 无匹配类型 → 空
        empty, empty_total = await repo.list(project.id, type=ExtractionType.OUTLINE)
        assert empty == []
        assert empty_total == 0

    async def test_list_sorted_by_run_at_desc(self, db_session, project):
        """list 按 run_at DESC 排序（最新在前，spec §8.1）."""
        repo = SQLExtractionRunRepository(db_session)
        old = await repo.upsert(
            _run(project, ExtractionType.CHARACTER, "chapter-old", run_at=_dt(1))
        )
        mid = await repo.upsert(
            _run(project, ExtractionType.CHARACTER, "chapter-mid", run_at=_dt(2))
        )
        new = await repo.upsert(
            _run(project, ExtractionType.CHARACTER, "chapter-new", run_at=_dt(3))
        )

        items, _ = await repo.list(project.id)
        assert [r.id for r in items] == [new.id, mid.id, old.id]
        # 时间序断言（naive 读回）
        assert [r.run_at for r in items] == [
            datetime(2026, 1, 3),
            datetime(2026, 1, 2),
            datetime(2026, 1, 1),
        ]

    async def test_list_pagination(self, db_session, project):
        """offset/limit 分页，total 为未分页总数；越界返回空列表."""
        repo = SQLExtractionRunRepository(db_session)
        for i in range(5):
            await repo.upsert(
                _run(project, ExtractionType.CHARACTER, f"chapter-{i}", run_at=_dt(i + 1))
            )

        page1, total = await repo.list(project.id, offset=0, limit=2)
        page2, _ = await repo.list(project.id, offset=2, limit=2)

        assert total == 5
        assert len(page1) == 2
        assert len(page2) == 2
        assert {r.id for r in page1}.isdisjoint({r.id for r in page2})

        # 分页越界 → 空列表
        page3, _ = await repo.list(project.id, offset=99, limit=2)
        assert page3 == []

    # ── 项目硬删 → 级联清理（FK CASCADE）──

    async def test_project_delete_cascades_runs(self, db_session, project):
        """项目硬删 → extraction_runs 级联物理删除（spec §2.3）."""
        repo = SQLExtractionRunRepository(db_session)
        await repo.upsert(_run(project, ExtractionType.CHARACTER, "chapter-1"))
        await repo.upsert(_run(project, ExtractionType.SETTING, "manual"))

        assert await _count_rows(db_session, project.id) == 2

        await db_session.delete(project)
        await db_session.commit()

        # 级联后无残留行
        result = await db_session.execute(select(func.count()).select_from(ExtractionRunORM))
        assert result.scalar_one() == 0
        # repo 视角：项目已不存在 → 空列表
        items, total = await repo.list(project.id)
        assert items == []
        assert total == 0

    # ── 空表 ──

    async def test_list_empty_table(self, db_session, project):
        """空表 list → ([], 0)；get → None."""
        repo = SQLExtractionRunRepository(db_session)
        assert await repo.list(project.id) == ([], 0)
        assert await repo.get(project.id, ExtractionType.CHARACTER, "chapter-1") is None
