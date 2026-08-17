"""F45 M1 用户级偏好仓储 RED 契约测试 — SQLiteUserPreferenceRepository（真实 in-memory SQLite 轨）.

依据: specs/f45-memory-evolution/spec.md §2.1/§2.2/§2.4（UserPreference 模型 /
user_preferences 表结构）+ §8 M1 文件表 + §9 测试策略 + §13 M1-3 验收，父侧定稿
契约同源（test_user_preference_repo.py docstring 即契约载体，镜像 F28
test_preference_repo.py 形态）。

被测模块（全部未实现，1l repo 整模块 RED 形态）:
    from inkflow.infrastructure.database.repositories.user_preference_repo import (
        SQLiteUserPreferenceRepository,
    )

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. SQLiteUserPreferenceRepository（infrastructure/database/repositories/
   user_preference_repo.py 新建，异步 SQLAlchemy，构造签名
   `SQLiteUserPreferenceRepository(db_session: AsyncSession)`，
   镜像 F28 SQLitePreferenceRepository 模式）:

       class SQLiteUserPreferenceRepository:
           async def create(
               self, *, category: PreferenceCategory, pattern: str, value: str,
               confidence: float, count: int, project_count: int,
               source_projects: list[str], source_events: list[str],
           ) -> UserPreference: ...   # id 由 ORM default 生成 uuid4 字符串
           async def get(self, preference_id: str) -> UserPreference | None: ...
           async def list_all(
               self, category: PreferenceCategory | None = None,
           ) -> tuple[list[UserPreference], int]: ...
           async def update(
               self, preference_id: str, *, count: int, confidence: float,
               project_count: int, source_projects: list[str],
               source_events: list[str],
           ) -> UserPreference | None: ...
           async def delete(self, preference_id: str) -> bool: ...
           async def delete_by_project_ref(self, project_id: uuid.UUID) -> int: ...

   语义: create 落库（id=uuid4 字符串 default、created_at/updated_at=UTC）；
   list_all 按 category 过滤（可空=全部），count desc 排序（同 count 按
   created_at asc），返回 (列表, total)；update 不存在 → None；delete 返回
   是否删除（rowcount>0）；delete_by_project_ref 删除 source_projects JSON
   中含该项目 id 的行，返回删除行数（实现可 SQL LIKE 或全量过滤——契约锁行为
   不锁实现）。

2. 领域 UserPreference/PreferenceCategory（domain/models/user_preference.py
   新建，Pydantic + StrEnum，model_config={"from_attributes": True}，
   镜像 ProjectPreference）:

       class UserPreference(BaseModel):
           id: str
           category: PreferenceCategory
           pattern: str
           value: str
           confidence: float
           count: int
           project_count: int
           source_projects: list[str] = []
           source_events: list[str] = []
           created_at: datetime
           updated_at: datetime

   （PreferenceCategory 复用 F28 domain/models/preference.py 四类枚举——
   addressing/style_word/structure/other）

3. ORM（infrastructure/database/models/user_preference.py 新建，
   UserPreferenceORM）: user_preferences 表列（spec §2.4）— id(String36 PK
   default uuid4) / category(String20 idx) / pattern(Text) / value(Text) /
   confidence(Float) / count(Integer) / project_count(Integer) /
   source_projects(JSON) / source_events(JSON) / created_at / updated_at。
   无 project_id 列（全局表）、无 FK（镜像 project_preferences 先例）。

RED 预期
--------
收集期失败（1l 整模块 RED 形态: pytest exit 2 / collected 0 items /
1 error）:
    ModuleNotFoundError: No module named
    'inkflow.infrastructure.database.repositories.user_preference_repo'
顶部仅 import 主契约模块（user_preference_repo）；domain models / ORM models
全部惰性（fixture 与用例体内 import）——RED 阶段同批 CREATE 尚未落地，
收集错误保持聚焦主模块（规则 1l）。

asyncio 模式: 本 venv pytest-asyncio mode=Mode.AUTO（pyproject
asyncio_mode = "auto" 生效）；文件级 pytestmark = pytest.mark.asyncio
双保险（STRICT/AUTO 两种模式均成立），全部用例 async def。
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.infrastructure.database.repositories.user_preference_repo import (
    SQLiteUserPreferenceRepository,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
PROJECT_ID_2 = uuid.UUID("87654321-4321-8765-4321-876543218765")
PROJECT_ID_3 = uuid.UUID("abcdefab-1234-4abc-8def-abcdefabcdef")


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库.

    ORM 惰性导入必须在 create_all 之前（规则 1l）——Base.metadata 需先注册
    新表（UserPreferenceORM），否则 create_all 不建 user_preferences 表.
    """

    # 惰性：RED 阶段模块未实现（create_all 前注册表——load-bearing）
    from inkflow.infrastructure.database.models.user_preference import (  # noqa: F401  # 惰性导入触发 Base.metadata 表注册（create_all 需要）
        UserPreferenceORM,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _create_pref(repo, *, pattern, category=None, count=2, project_count=2, **kw):
    """经 repo.create 落库一条用户级偏好（category 缺省 OTHER，其余字段可覆盖）."""
    from inkflow.domain.models.user_preference import PreferenceCategory  # 惰性

    values = {
        "category": category if category is not None else PreferenceCategory.OTHER,
        "pattern": pattern,
        "value": f"value-{pattern}",
        "confidence": 0.5,
        "count": count,
        "project_count": project_count,
        "source_projects": [str(PROJECT_ID)],
        "source_events": [f"evt-{pattern}"],
    }
    values.update(kw)
    return await repo.create(**values)


async def _insert_preference_direct(db_session, *, category, pattern, count, created_at):
    """排序造数：repo.create 不保留显式 created_at（DB 默认 _utcnow 生效）."""
    from inkflow.infrastructure.database.models.user_preference import (
        UserPreferenceORM,
    )

    await db_session.execute(
        insert(UserPreferenceORM).values(
            category=category,
            pattern=pattern,
            value=f"value-{pattern}",
            confidence=0.5,
            count=count,
            project_count=2,
            source_projects=[str(PROJECT_ID)],
            source_events=["direct-ev"],
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await db_session.commit()


@pytest.mark.integration
class TestSQLiteUserPreferenceRepository:
    """SQLiteUserPreferenceRepository 集成测试（真实 in-memory SQLite 轨）."""

    async def test_create_roundtrips_all_fields(self, db_session):
        """契约①: create 落库全字段，get 读回等值（含 JSON source_projects/source_events）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.user_preference import (
            PreferenceCategory,
            UserPreference,
        )

        repo = SQLiteUserPreferenceRepository(db_session)
        pref = await repo.create(
            category=PreferenceCategory.ADDRESSING,
            pattern="称呼主角为林晚",
            value="林晚",
            confidence=0.67,
            count=2,
            project_count=2,
            source_projects=[str(PROJECT_ID), str(PROJECT_ID_2)],
            source_events=["evt-1", "evt-2"],
        )

        assert isinstance(pref, UserPreference)
        assert pref.category == PreferenceCategory.ADDRESSING
        assert pref.pattern == "称呼主角为林晚"
        assert pref.value == "林晚"
        assert pref.confidence == 0.67
        assert pref.count == 2
        assert pref.project_count == 2
        assert pref.source_projects == [str(PROJECT_ID), str(PROJECT_ID_2)]
        assert pref.source_events == ["evt-1", "evt-2"]

        # 持久化验证：读回
        fetched = await repo.get(pref.id)
        assert fetched is not None
        assert fetched.pattern == pref.pattern
        assert fetched.value == pref.value
        assert fetched.count == pref.count
        assert fetched.project_count == pref.project_count
        assert fetched.source_projects == pref.source_projects
        assert fetched.source_events == pref.source_events

    async def test_create_generates_id_and_utc_timestamps(self, db_session):
        """契约②: create 自动生成 uuid4 字符串 id + UTC created_at/updated_at."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.user_preference import PreferenceCategory

        repo = SQLiteUserPreferenceRepository(db_session)
        pref = await repo.create(
            category=PreferenceCategory.STYLE_WORD,
            pattern="用词偏好：低声道",
            value="低声道",
            confidence=0.67,
            count=2,
            project_count=2,
            source_projects=[str(PROJECT_ID)],
            source_events=[],
        )

        assert isinstance(pref.id, str)
        assert len(pref.id) == 36
        assert isinstance(pref.created_at, datetime)
        assert isinstance(pref.updated_at, datetime)

    async def test_get_missing_returns_none(self, db_session):
        """契约③: get 对缺失偏好返回 None."""
        repo = SQLiteUserPreferenceRepository(db_session)

        assert await repo.get("00000000-0000-0000-0000-000000000000") is None

    async def test_list_all_returns_all_and_total(self, db_session):
        """契约④: list_all 返回 (全部, total)（全局表无项目过滤）."""
        repo = SQLiteUserPreferenceRepository(db_session)
        await _create_pref(repo, pattern="P1")
        await _create_pref(repo, pattern="P2")
        await _create_pref(repo, pattern="P3")

        items, total = await repo.list_all()

        assert total == 3
        assert {p.pattern for p in items} == {"P1", "P2", "P3"}

    async def test_list_all_filters_by_category(self, db_session):
        """契约⑤: category 过滤（不传 = 全部）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.user_preference import PreferenceCategory

        repo = SQLiteUserPreferenceRepository(db_session)
        await _create_pref(repo, pattern="P1", category=PreferenceCategory.ADDRESSING)
        await _create_pref(repo, pattern="P2", category=PreferenceCategory.STYLE_WORD)

        items, total = await repo.list_all(category=PreferenceCategory.ADDRESSING)

        assert total == 1
        assert [p.pattern for p in items] == ["P1"]

    async def test_list_all_sorts_count_desc_then_created_at_asc(self, db_session):
        """契约⑥: count desc 排序，同 count 按 created_at asc（直插显式时间）."""
        repo = SQLiteUserPreferenceRepository(db_session)
        await _insert_preference_direct(
            db_session,
            category="addressing",
            pattern="A",
            count=3,
            created_at=datetime(2026, 8, 1, 10, 0, 0),
        )
        await _insert_preference_direct(
            db_session,
            category="addressing",
            pattern="B",
            count=3,
            created_at=datetime(2026, 8, 1, 11, 0, 0),
        )
        await _insert_preference_direct(
            db_session,
            category="addressing",
            pattern="C",
            count=5,
            created_at=datetime(2026, 8, 1, 12, 0, 0),
        )

        items, total = await repo.list_all()

        assert total == 3
        assert [p.pattern for p in items] == ["C", "A", "B"]

    async def test_list_all_empty_returns_empty(self, db_session):
        """契约⑦: 空表 → ([], 0)."""
        repo = SQLiteUserPreferenceRepository(db_session)

        items, total = await repo.list_all()

        assert items == []
        assert total == 0

    async def test_update_refreshes_all_fields(self, db_session):
        """契约⑧: update 更新 count/confidence/project_count/source_projects/
        source_events，持久化读回生效."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.user_preference import PreferenceCategory

        repo = SQLiteUserPreferenceRepository(db_session)
        pref = await _create_pref(
            repo,
            pattern="P1",
            category=PreferenceCategory.ADDRESSING,
            count=2,
            confidence=0.67,
            project_count=2,
            source_projects=[str(PROJECT_ID)],
            source_events=["evt-1"],
        )

        updated = await repo.update(
            pref.id,
            count=3,
            confidence=0.75,
            project_count=3,
            source_projects=[str(PROJECT_ID), str(PROJECT_ID_2)],
            source_events=["evt-1", "evt-2"],
        )

        assert updated is not None
        assert updated.count == 3
        assert updated.confidence == 0.75
        assert updated.project_count == 3
        assert updated.source_projects == [str(PROJECT_ID), str(PROJECT_ID_2)]
        assert updated.source_events == ["evt-1", "evt-2"]
        # 持久化读回
        fetched = await repo.get(pref.id)
        assert fetched is not None
        assert fetched.count == 3
        assert fetched.project_count == 3
        assert fetched.source_projects == [str(PROJECT_ID), str(PROJECT_ID_2)]
        assert fetched.source_events == ["evt-1", "evt-2"]

    async def test_update_missing_returns_none(self, db_session):
        """契约⑨: update 对缺失偏好返回 None."""
        repo = SQLiteUserPreferenceRepository(db_session)

        result = await repo.update(
            "00000000-0000-0000-0000-000000000000",
            count=3,
            confidence=0.75,
            project_count=2,
            source_projects=[str(PROJECT_ID)],
            source_events=[],
        )

        assert result is None

    async def test_delete_existing_returns_true_and_removes(self, db_session):
        """契约⑩: delete 删除成功返回 True，读回 None."""
        repo = SQLiteUserPreferenceRepository(db_session)
        pref = await _create_pref(repo, pattern="P1")

        deleted = await repo.delete(pref.id)

        assert deleted is True
        assert await repo.get(pref.id) is None

    async def test_delete_missing_returns_false(self, db_session):
        """契约⑪: delete 对缺失偏好返回 False."""
        repo = SQLiteUserPreferenceRepository(db_session)

        assert await repo.delete("00000000-0000-0000-0000-000000000000") is False

    async def test_delete_by_project_ref_deletes_matching_rows_only(self, db_session):
        """契约⑫: delete_by_project_ref 删除 source_projects 含该项目 id 的行，
        返回删除行数；不含该项目的行不受影响."""
        repo = SQLiteUserPreferenceRepository(db_session)
        await _create_pref(
            repo,
            pattern="P1",
            source_projects=[str(PROJECT_ID), str(PROJECT_ID_2)],
        )
        await _create_pref(
            repo,
            pattern="P2",
            source_projects=[str(PROJECT_ID)],
        )
        await _create_pref(
            repo,
            pattern="P3",
            source_projects=[str(PROJECT_ID_2), str(PROJECT_ID_3)],
        )

        deleted = await repo.delete_by_project_ref(PROJECT_ID)

        assert deleted == 2
        items, total = await repo.list_all()
        assert total == 1
        assert [p.pattern for p in items] == ["P3"]

    async def test_source_projects_and_source_events_json_roundtrip(self, db_session):
        """契约⑬: source_projects/source_events JSON 列读回等值
        （跨项目追溯/事件可追源）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.user_preference import PreferenceCategory

        repo = SQLiteUserPreferenceRepository(db_session)
        project_ids = [str(PROJECT_ID), str(PROJECT_ID_2), str(PROJECT_ID_3)]
        event_ids = ["evt-100", "evt-200", "evt-300"]
        pref = await _create_pref(
            repo,
            pattern="P1",
            category=PreferenceCategory.ADDRESSING,
            source_projects=project_ids,
            source_events=event_ids,
        )

        fetched = await repo.get(pref.id)

        assert fetched is not None
        assert isinstance(fetched.source_projects, list)
        assert fetched.source_projects == project_ids
        assert isinstance(fetched.source_events, list)
        assert fetched.source_events == event_ids


async def test_orm_repr_includes_id_and_pattern() -> None:
    """覆盖 UserPreferenceORM.__repr__（coverage 门禁 models/user_preference.py:113）."""
    from inkflow.infrastructure.database.models.user_preference import (
        UserPreferenceORM,
    )

    orm = UserPreferenceORM(
        category="style_word",
        pattern="说",
        value="低声道",
        confidence=0.5,
        count=2,
        project_count=2,
        source_projects=[str(PROJECT_ID)],
        source_events=["evt-1"],
    )
    text = repr(orm)
    assert "UserPreferenceORM" in text
    assert "说" in text
