"""#1149 RED 契约 — create_chapter 对不存在项目必须 404 语义（ProjectNotFoundError）。

背景（rc7 实产验证实证）：
    POST /api/v1/projects/{任何不存在的 pid}/chapters → 500
    root cause: chapter_service.py:165 把 `pid.int`（128 位 UUID int）传给
    get_next_chapter_order → SQLite 绑定 int64 OverflowError。
    对照 create_volume（同文件 92-95）落库前有 `_project_repo.get(pid.int)` 校验 → 404。

契约（三组）：
  A. 不存在项目（含非法/溢出 id）→ ProjectNotFoundError（router 转 404），不落库
  B. 存在项目 → 正常创建（护栏，当前即绿）
  C. 既有 create_volume 同族语义不回归（护栏，当前即绿）

RED 预期（GREEN 前）：
  - TestCreateChapterProjectGuard 全部 FAILED（ProjectNotFoundError 未抛 → 500/OverflowError）
  - TestExistingBehaviorGuard 全部 PASSED（护栏）

轨道：真实 in-memory SQLite（镜像 test_chapter_service.py），不走 mock 工厂 ——
      #1106 实证：mock 轨（@patch get_chapter_service）会让守卫落点判断失真。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.ports.world_errors import ProjectNotFoundError
from inkflow.domain.services.chapter_service import ChapterService
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.project import ProjectORM


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每用例全新库。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def svc(db_session) -> ChapterService:
    return ChapterService(db_session)


@pytest.fixture
async def project(db_session) -> ProjectORM:
    p = ProjectORM(name="存在项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _uuid_int(orm_id: int) -> uuid.UUID:
    """ORM int 主键 → 领域 UUID（真实契约：uuid.UUID(int=id)）。"""
    return uuid.UUID(int=orm_id)


async def _chapter_count(db_session) -> int:
    return (await db_session.execute(select(func.count()).select_from(ChapterORM))).scalar_one()


class TestCreateChapterProjectGuard:
    """A 组：不存在项目 → ProjectNotFoundError（当前 RED）。"""

    async def test_high_uuid_nonexistent_project_raises(self, svc, db_session) -> None:
        """高位 UUID（>2**63）指向不存在项目 → ProjectNotFoundError（rc7 实测 500 的主形态）。"""
        ghost = uuid.uuid5(uuid.NAMESPACE_DNS, "no-such-project")
        assert ghost.int > 2**63 - 1, "前置：该 UUID int 必须超出 int64（复现 500 条件）"

        with pytest.raises(ProjectNotFoundError):
            await svc.create_chapter(ghost, "幽灵章", content="x")

        assert await _chapter_count(db_session) == 0, "不得落库（无孤儿行）"

    async def test_low_int_nonexistent_project_raises(self, svc, db_session) -> None:
        """小整数 id（不触发溢出，纯不存在）→ ProjectNotFoundError（证明与溢出无关）。"""
        with pytest.raises(ProjectNotFoundError):
            await svc.create_chapter(uuid.UUID(int=999999), "幽灵章", content="x")

        assert await _chapter_count(db_session) == 0

    async def test_overflow_int_project_raises(self, svc, db_session) -> None:
        """裸溢出 int 传入（>=2**63）→ ProjectNotFoundError（不得抛 OverflowError）。"""
        with pytest.raises(ProjectNotFoundError):
            await svc.create_chapter(2**63, "幽灵章", content="x")

        assert await _chapter_count(db_session) == 0

    async def test_nonexistent_project_with_volume_raises(self, svc, db_session) -> None:
        """不存在项目 + 带 volume_id → 仍 ProjectNotFoundError（项目校验优先）。"""
        ghost = uuid.uuid5(uuid.NAMESPACE_DNS, "no-such-project-2")

        with pytest.raises(ProjectNotFoundError):
            await svc.create_chapter(ghost, "幽灵章", volume_id=1, content="x")

        assert await _chapter_count(db_session) == 0


class TestExistingBehaviorGuard:
    """护栏组：当前即绿，防 GREEN 改坏既有分支。"""

    async def test_existing_project_creates_chapter(self, svc, project) -> None:
        """护栏：存在项目 → 正常创建，order_index 编排生效。"""
        pid = _uuid_int(project.id)
        ch = await svc.create_chapter(pid, "第一章", content="第一章内容")

        assert ch.project_id == pid
        assert ch.title == "第一章"
        assert ch.order_index == 1.0
        assert ch.word_count == 5  # count_words("第一章内容") = 5

    async def test_existing_project_explicit_order_kept(self, svc, project) -> None:
        """护栏：显式 order_index 原样落库（守卫不得误伤）。"""
        ch = await svc.create_chapter(_uuid_int(project.id), "第一章", order_index=5.0)
        assert ch.order_index == 5.0

    async def test_create_volume_same_guard_unchanged(self, svc, db_session) -> None:
        """护栏：create_volume 同族语义不回归（已存在 → 建卷 / 不存在 → 抛）。"""
        ghost = uuid.uuid5(uuid.NAMESPACE_DNS, "no-such-project-3")

        with pytest.raises(ProjectNotFoundError):
            await svc.create_volume(ghost, "幽灵卷")

        p = ProjectORM(name="卷项目")
        db_session.add(p)
        await db_session.commit()
        await db_session.refresh(p)

        vol = await svc.create_volume(_uuid_int(p.id), "第一卷")
        assert vol.title == "第一卷"
        assert vol.order_index == 1.0
