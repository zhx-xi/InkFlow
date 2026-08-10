"""F28 M3 偏好仓储 RED 契约测试 — SQLitePreferenceRepository（真实 in-memory SQLite 轨）.

被测模块（全部未实现，1l repo 整模块 RED 形态）:
    from inkflow.infrastructure.database.repositories.preference_repo import (
        SQLitePreferenceRepository,
    )

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. SQLitePreferenceRepository（infrastructure/database/repositories/
   preference_repo.py 新建，异步 SQLAlchemy，构造签名
   `SQLitePreferenceRepository(db_session: AsyncSession)`，
   镜像 F27 draft_repo 模式）:

       class SQLitePreferenceRepository:
           async def create(
               self, *, project_id: uuid.UUID, category: PreferenceCategory,
               pattern: str, value: str, confidence: float, count: int,
               source_events: list[str],
           ) -> ProjectPreference: ...
           async def get(self, preference_id: str) -> ProjectPreference | None: ...
           async def list_by_project(
               self, project_id: uuid.UUID,
               category: PreferenceCategory | None = None,
           ) -> tuple[list[ProjectPreference], int]: ...
           async def update(
               self, preference_id: str, *, count: int,
               confidence: float, source_events: list[str],
           ) -> ProjectPreference | None: ...
           async def delete(self, preference_id: str) -> bool: ...
           async def delete_by_project(self, project_id: uuid.UUID) -> int: ...

   语义: create 落库（id=uuid4 字符串 default、created_at/updated_at=UTC）；
   list_by_project 按 project_id 过滤（category 可空=全部），count desc 排序
   （同 count 按 created_at asc），返回 (列表, total)；update 不存在 → None；
   delete 返回是否删除；delete_by_project 返回删除行数。

2. 领域 ProjectPreference/PreferenceCategory（domain/models/preference.py
   新建，Pydantic + StrEnum，model_config={"from_attributes": True}）:

       class PreferenceCategory(StrEnum):
           ADDRESSING = "addressing"
           STYLE_WORD = "style_word"
           STRUCTURE = "structure"
           OTHER = "other"

       class ProjectPreference(BaseModel):
           id: str
           project_id: uuid.UUID
           category: PreferenceCategory
           pattern: str
           value: str
           confidence: float
           count: int
           source_events: list[str] = []
           created_at: datetime
           updated_at: datetime

3. ORM（infrastructure/database/models/preference.py 新建，
   ProjectPreferenceORM + MemoryEventORM 两表同文件）: project_preferences
   表列（spec §2.3）— id(String36 PK default uuid4) / project_id(String36
   idx 无 FK) / category(String20) / pattern(Text) / value(Text) /
   confidence(Float) / count(Integer) / source_events(JSON) / created_at /
   updated_at。

RED 预期
--------
收集期失败（1l 整模块 RED 形态: pytest exit 2 / collected 0 items /
1 error）:
    ModuleNotFoundError: No module named
    'inkflow.infrastructure.database.repositories.preference_repo'
顶部仅 import 主契约模块（preference_repo）；domain models / ORM models
全部惰性（fixture 与用例体内 import）——部分落地态（领域层先于基础设施）
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
from inkflow.infrastructure.database.repositories.preference_repo import (
    SQLitePreferenceRepository,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
PROJECT_ID_2 = uuid.UUID("87654321-4321-8765-4321-876543218765")


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库.

    ORM 惰性导入必须在 create_all 之前（规则 1l）——Base.metadata 需先注册
    新表（ProjectPreferenceORM），否则 create_all 不建 project_preferences 表.
    """

    # 惰性：RED 阶段模块未实现（create_all 前注册表——load-bearing）
    from inkflow.infrastructure.database.models.preference import (  # noqa: F401  # 惰性导入触发 Base.metadata 表注册（create_all 需要）
        ProjectPreferenceORM,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _create_pref(repo, *, pattern, category=None, count=2, project_id=PROJECT_ID, **kw):
    """经 repo.create 落库一条偏好（category 缺省 OTHER，其余字段可覆盖）."""
    from inkflow.domain.models.preference import PreferenceCategory  # 惰性

    values = {
        "project_id": project_id,
        "category": category if category is not None else PreferenceCategory.OTHER,
        "pattern": pattern,
        "value": f"value-{pattern}",
        "confidence": 0.5,
        "count": count,
        "source_events": [f"evt-{pattern}"],
    }
    values.update(kw)
    return await repo.create(**values)


async def _insert_preference_direct(
    db_session, *, project_id, category, pattern, count, created_at
):
    """排序造数：repo.create 不保留显式 created_at（DB 默认 _utcnow 生效）."""
    from inkflow.infrastructure.database.models.preference import (
        ProjectPreferenceORM,
    )

    await db_session.execute(
        insert(ProjectPreferenceORM).values(
            project_id=str(project_id),
            category=category,
            pattern=pattern,
            value=f"value-{pattern}",
            confidence=0.5,
            count=count,
            source_events=["direct-ev"],
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await db_session.commit()


@pytest.mark.integration
class TestSQLitePreferenceRepository:
    """SQLitePreferenceRepository 集成测试（真实 in-memory SQLite 轨）."""

    async def test_create_roundtrips_all_fields(self, db_session):
        """契约①: create 落库全字段，get 读回等值（含 JSON source_events）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.preference import (
            PreferenceCategory,
            ProjectPreference,
        )

        repo = SQLitePreferenceRepository(db_session)
        pref = await repo.create(
            project_id=PROJECT_ID,
            category=PreferenceCategory.ADDRESSING,
            pattern="称呼主角为林晚",
            value="林晚",
            confidence=0.67,
            count=2,
            source_events=["evt-1", "evt-2"],
        )

        assert isinstance(pref, ProjectPreference)
        assert pref.project_id == PROJECT_ID
        assert pref.category == PreferenceCategory.ADDRESSING
        assert pref.pattern == "称呼主角为林晚"
        assert pref.value == "林晚"
        assert pref.confidence == 0.67
        assert pref.count == 2
        assert pref.source_events == ["evt-1", "evt-2"]

        # 持久化验证：读回
        fetched = await repo.get(pref.id)
        assert fetched is not None
        assert fetched.pattern == pref.pattern
        assert fetched.value == pref.value
        assert fetched.count == pref.count
        assert fetched.source_events == pref.source_events

    async def test_create_generates_id_and_utc_timestamps(self, db_session):
        """契约②: create 自动生成 uuid4 字符串 id + UTC created_at/updated_at."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.preference import PreferenceCategory

        repo = SQLitePreferenceRepository(db_session)
        pref = await repo.create(
            project_id=PROJECT_ID,
            category=PreferenceCategory.STYLE_WORD,
            pattern="用词偏好：低声道",
            value="低声道",
            confidence=0.67,
            count=2,
            source_events=[],
        )

        assert isinstance(pref.id, str)
        assert len(pref.id) == 36
        assert isinstance(pref.created_at, datetime)
        assert isinstance(pref.updated_at, datetime)

    async def test_get_missing_returns_none(self, db_session):
        """契约③: get 对缺失偏好返回 None."""
        repo = SQLitePreferenceRepository(db_session)

        assert await repo.get("00000000-0000-0000-0000-000000000000") is None

    async def test_list_by_project_returns_all_and_total(self, db_session):
        """契约④: list_by_project 返回 (全部, total)，跨项目隔离."""
        repo = SQLitePreferenceRepository(db_session)
        await _create_pref(repo, pattern="P1")
        await _create_pref(repo, pattern="P2")
        await _create_pref(repo, pattern="P3", project_id=PROJECT_ID_2)

        items, total = await repo.list_by_project(PROJECT_ID)

        assert total == 2
        assert {p.pattern for p in items} == {"P1", "P2"}

    async def test_list_by_project_filters_by_category(self, db_session):
        """契约⑤: category 过滤（不传 = 全部）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.preference import PreferenceCategory

        repo = SQLitePreferenceRepository(db_session)
        await _create_pref(repo, pattern="P1", category=PreferenceCategory.ADDRESSING)
        await _create_pref(repo, pattern="P2", category=PreferenceCategory.STYLE_WORD)

        items, total = await repo.list_by_project(
            PROJECT_ID, category=PreferenceCategory.ADDRESSING
        )

        assert total == 1
        assert [p.pattern for p in items] == ["P1"]

    async def test_list_by_project_sorts_count_desc_then_created_at_asc(self, db_session):
        """契约⑥: count desc 排序，同 count 按 created_at asc（直插显式时间）."""
        repo = SQLitePreferenceRepository(db_session)
        await _insert_preference_direct(
            db_session,
            project_id=PROJECT_ID,
            category="addressing",
            pattern="A",
            count=3,
            created_at=datetime(2026, 8, 1, 10, 0, 0),
        )
        await _insert_preference_direct(
            db_session,
            project_id=PROJECT_ID,
            category="addressing",
            pattern="B",
            count=3,
            created_at=datetime(2026, 8, 1, 11, 0, 0),
        )
        await _insert_preference_direct(
            db_session,
            project_id=PROJECT_ID,
            category="addressing",
            pattern="C",
            count=5,
            created_at=datetime(2026, 8, 1, 12, 0, 0),
        )

        items, total = await repo.list_by_project(PROJECT_ID)

        assert total == 3
        assert [p.pattern for p in items] == ["C", "A", "B"]

    async def test_list_by_project_empty_project(self, db_session):
        """契约⑦: 无偏好的项目 → ([], 0)."""
        repo = SQLitePreferenceRepository(db_session)

        items, total = await repo.list_by_project(PROJECT_ID)

        assert items == []
        assert total == 0

    async def test_update_refreshes_count_confidence_source_events(self, db_session):
        """契约⑧: update 更新 count/confidence/source_events，持久化读回生效."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.preference import PreferenceCategory

        repo = SQLitePreferenceRepository(db_session)
        pref = await _create_pref(
            repo,
            pattern="P1",
            category=PreferenceCategory.ADDRESSING,
            count=2,
            confidence=0.67,
            source_events=["evt-1"],
        )

        updated = await repo.update(
            pref.id, count=3, confidence=0.75, source_events=["evt-1", "evt-2"]
        )

        assert updated is not None
        assert updated.count == 3
        assert updated.confidence == 0.75
        assert updated.source_events == ["evt-1", "evt-2"]
        # 持久化读回
        fetched = await repo.get(pref.id)
        assert fetched is not None
        assert fetched.count == 3
        assert fetched.source_events == ["evt-1", "evt-2"]

    async def test_update_missing_returns_none(self, db_session):
        """契约⑨: update 对缺失偏好返回 None."""
        repo = SQLitePreferenceRepository(db_session)

        result = await repo.update(
            "00000000-0000-0000-0000-000000000000",
            count=3,
            confidence=0.75,
            source_events=[],
        )

        assert result is None

    async def test_delete_existing_returns_true_and_removes(self, db_session):
        """契约⑩: delete 删除成功返回 True，读回 None."""
        repo = SQLitePreferenceRepository(db_session)
        pref = await _create_pref(repo, pattern="P1")

        deleted = await repo.delete(pref.id)

        assert deleted is True
        assert await repo.get(pref.id) is None

    async def test_delete_missing_returns_false(self, db_session):
        """契约⑪: delete 对缺失偏好返回 False."""
        repo = SQLitePreferenceRepository(db_session)

        assert await repo.delete("00000000-0000-0000-0000-000000000000") is False

    async def test_delete_by_project_returns_deleted_count(self, db_session):
        """契约⑫: delete_by_project 返回删除行数，其他项目不受影响."""
        repo = SQLitePreferenceRepository(db_session)
        await _create_pref(repo, pattern="P1")
        await _create_pref(repo, pattern="P2")
        await _create_pref(repo, pattern="P3", project_id=PROJECT_ID_2)

        deleted = await repo.delete_by_project(PROJECT_ID)

        assert deleted == 2
        items, total = await repo.list_by_project(PROJECT_ID)
        assert items == []
        assert total == 0
        other_items, other_total = await repo.list_by_project(PROJECT_ID_2)
        assert other_total == 1
        assert other_items[0].pattern == "P3"

    async def test_source_events_json_roundtrip(self, db_session):
        """契约⑬: source_events JSON 列读回等值（事件 id 列表可追溯）."""
        # 惰性：RED 阶段模块未实现
        from inkflow.domain.models.preference import PreferenceCategory

        repo = SQLitePreferenceRepository(db_session)
        event_ids = ["evt-100", "evt-200", "evt-300"]
        pref = await _create_pref(
            repo,
            pattern="P1",
            category=PreferenceCategory.ADDRESSING,
            source_events=event_ids,
        )

        fetched = await repo.get(pref.id)

        assert fetched is not None
        assert isinstance(fetched.source_events, list)
        assert fetched.source_events == event_ids
