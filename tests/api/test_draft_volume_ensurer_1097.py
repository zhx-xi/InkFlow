"""#1097 RED 契约 — `make_volume_ensurer` 装配工厂真实路径（真库集成面）.

契约依据: specs/f2-chapter/spec.md §2.2 业务规则（卷唯一/同名复用）+
specs/f44-book-orchestrator/spec.md §5.2（#1097 自动建卷归卷）。

被测（当前不存在 → ImportError RED）:
`inkflow.api.deps_draft.make_volume_ensurer(db) -> Callable[[uuid.UUID, uuid.UUID],
Awaitable[uuid.UUID | None]]` —— 镜像同模块 `make_outline_bindder` 的 db 会话
闭包工厂形态（ORM 延迟导入，弱依赖永不抛错）。

GREEN 必实现语义:
- 沿章大纲节点 `parent_id` 上溯 `level == "volume"` 的父大纲 → 取其 `name` 作卷名；
- 按 (project_id, title) ensure volumes 行：命中同项目同名复用，未命中新建
  （order_index 走 `get_next_volume_order` 既有语义）；
- 无卷父（章节点无 parent / parent 非 volume / 行不存在 / 跨项目）→ 返回 None
  （不臆造卷，验收「无卷父保持 None」）；
- 幂等：多章同卷 → 同一 volumes 行（行数不增）。

真库（in-memory SQLite + db_session fixture，镜像 tests/conftest.py 集成链）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from inkflow.infrastructure.database.models.chapter import VolumeORM
from inkflow.infrastructure.database.models.outline import OutlineORM
from inkflow.infrastructure.database.models.project import ProjectORM

pytestmark = pytest.mark.asyncio


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _make_project(db, name: str = "自动建卷测试书") -> int:
    """落库一个项目，返回其 int 主键（卷/大纲 FK 载体）。"""
    project = ProjectORM(
        name=name,
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return int(project.id)


async def _add_outline(db, *, project_id: int, level: str, name: str, parent_id: int | None) -> int:
    """落库一条大纲（volume/chapter 三级结构），返回 int 主键。"""
    row = OutlineORM(
        project_id=project_id,
        name=name,
        description="",
        sort_order=0,
        level=level,
        parent_id=parent_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return int(row.id)


async def _volume_count(db, project_id: int) -> int:
    """统计项目下 volumes 行数（幂等判据）。"""
    stmt = select(func.count()).select_from(VolumeORM).where(VolumeORM.project_id == project_id)
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)


async def test_ensurer_creates_volume_from_volume_parent(db_session):
    """【R】章节点有 volume 父 → 建 volumes 行（标题=卷大纲名）并返回其 UUID.

    当前模块无 make_volume_ensurer → ImportError（RED）。
    """
    from inkflow.api.deps_draft import make_volume_ensurer

    project_id = await _make_project(db_session)
    volume_outline_id = await _add_outline(
        db_session, project_id=project_id, level="volume", name="第一卷·蜀山重立", parent_id=None
    )
    chapter_outline_id = await _add_outline(
        db_session,
        project_id=project_id,
        level="chapter",
        name="第1章 拜入蜀山",
        parent_id=volume_outline_id,
    )
    ensurer = make_volume_ensurer(db_session)

    result = await ensurer(
        uuid.UUID(int=project_id), uuid.UUID(int=chapter_outline_id)
    )

    assert result is not None
    rows = (
        await db_session.execute(
            select(VolumeORM).where(VolumeORM.project_id == project_id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "第一卷·蜀山重立"
    assert str(result) == str(uuid.UUID(int=int(rows[0].id)))


async def test_ensurer_reuses_same_named_volume(db_session):
    """【R】同项目已有同名卷 → 复用不新建（多章同卷行数不增）.

    幂等核心：第二次 ensure 命中既有行 → volumes 行数仍为 1 且返回同 UUID。
    """
    from inkflow.api.deps_draft import make_volume_ensurer

    project_id = await _make_project(db_session, "幂等测试书")
    volume_outline_id = await _add_outline(
        db_session, project_id=project_id, level="volume", name="第一卷·蜀山重立", parent_id=None
    )
    first_outline = await _add_outline(
        db_session,
        project_id=project_id,
        level="chapter",
        name="第1章 拜入蜀山",
        parent_id=volume_outline_id,
    )
    second_outline = await _add_outline(
        db_session,
        project_id=project_id,
        level="chapter",
        name="第2章 药庐学医",
        parent_id=volume_outline_id,
    )
    ensurer = make_volume_ensurer(db_session)

    first = await ensurer(uuid.UUID(int=project_id), uuid.UUID(int=first_outline))
    second = await ensurer(uuid.UUID(int=project_id), uuid.UUID(int=second_outline))

    assert first is not None
    assert first == second
    assert await _volume_count(db_session, project_id) == 1


async def test_ensurer_returns_none_without_volume_parent(db_session):
    """【R】章节点无父（孤立章）→ None，不建卷（不臆造）.

    无卷父是合法旧形态；ensurer 必须返回 None 而非兜底建卷。
    """
    from inkflow.api.deps_draft import make_volume_ensurer

    project_id = await _make_project(db_session, "孤立章测试书")
    chapter_outline_id = await _add_outline(
        db_session, project_id=project_id, level="chapter", name="第1章 独章", parent_id=None
    )
    ensurer = make_volume_ensurer(db_session)

    result = await ensurer(uuid.UUID(int=project_id), uuid.UUID(int=chapter_outline_id))

    assert result is None
    assert await _volume_count(db_session, project_id) == 0


async def test_ensurer_returns_none_when_row_missing(db_session):
    """【R】章节点行不存在 / id 溢出 → None（弱依赖永不抛错）.

    回填同族契约：无行静默返回（uuid4 随机值溢出 SQLite INTEGER 无对应行）。
    """
    from inkflow.api.deps_draft import make_volume_ensurer

    project_id = await _make_project(db_session, "无行测试书")
    ensurer = make_volume_ensurer(db_session)

    result = await ensurer(uuid.UUID(int=project_id), uuid.uuid4())

    assert result is None
    assert await _volume_count(db_session, project_id) == 0


async def test_ensurer_isolates_projects(db_session):
    """【R】卷大纲属于别的项目 → None（项目隔离，不跨项目复用卷）.

    章节点与卷父跨项目时视为无卷父；同名卷也不得跨项目复用。
    """
    from inkflow.api.deps_draft import make_volume_ensurer

    project_a = await _make_project(db_session, "项目A书")
    project_b = await _make_project(db_session, "项目B书")
    foreign_volume_outline = await _add_outline(
        db_session, project_id=project_b, level="volume", name="第一卷·外项目", parent_id=None
    )
    chapter_outline_id = await _add_outline(
        db_session,
        project_id=project_a,
        level="chapter",
        name="第1章 跨项目章",
        parent_id=foreign_volume_outline,
    )
    ensurer = make_volume_ensurer(db_session)

    result = await ensurer(uuid.UUID(int=project_a), uuid.UUID(int=chapter_outline_id))

    assert result is None
    assert await _volume_count(db_session, project_a) == 0
    assert await _volume_count(db_session, project_b) == 0
