"""F35 世界观地点树（world-location-tree）专项测试 — 仓储层 + 迁移（RED 阶段契约）.

覆盖 spec §9 层次：迁移幂等（~4）/ 递归 CTE（~7）/ 列表 parent_id 过滤（~4）/
删除语义 repo 层（~6）/ 三写点 parent_id 往返（~3）/ get_by_parent_and_name（~6）。

═══════════════════════════════════════════════════════════════════════
GREEN 实现契约（本文件 docstring 即契约，GREEN 实现者以此为准）
═══════════════════════════════════════════════════════════════════════

1. WorldRepositoryProtocol / SQLiteWorldRepository 新增方法（签名逐字）:

   async def get_by_parent_and_name(
       project_id: int, parent_id: int | None, name: str
   ) -> WorldSetting | None:
       '''按 (project_id, parent_id, name) 查询活动条目（parent_id=None = 顶层）——
       同级唯一校验用（spec §5.1）。'''

   async def collect_ancestor_ids(setting_id: int) -> list[int]:
       '''祖先链 id 列表，**不含自身**（父链，从近到远 [父, 祖父, ...]；
       用于循环防护：检查新父的祖先链是否含自身，spec §5.2）。'''

   async def list_descendants(setting_id: int) -> list[WorldSetting]:
       '''子树（**含自身**），层序（父先子后，同层 created_at ASC）；
       仅活动条目（is_deleted=0）；不存在/软删 id → 空列表（spec §5.3）。'''

   async def hard_delete_many(setting_ids: list[int]) -> int:
       '''单事务原子物理删除（DELETE WHERE id IN (...)），返回删除行数；
       空列表 → 0 不报错；不存在的 id 不影响计数（spec §5.5 级联真删）。'''

   async def delete_with_reparent(setting_id: int, reparent_to: int) -> bool:
       '''单事务: UPDATE world_settings SET parent_id=<reparent_to>
       WHERE parent_id=<setting_id> + DELETE 自身；返回自身是否被删；
       子地点层级深度不变（孙子继续挂子，树整体平移，spec §5.5 实现注意）。'''

2. list 追加两个末尾参数（向后兼容，缺省行为不变）:

   async def list(
       project_id: int, search=None, category=None, sort_by="updated_at",
       sort_desc=True, offset=0, limit=50,
       parent_id: int | None = None,        # 非 None → 只返回该父的直接子级
       top_level_only: bool = False,        # True → 只返回 parent_id IS NULL 顶层
   ) -> tuple[list[WorldSetting], int]:
       '''parent_id=None 是「未过滤」哨兵（非顶层过滤）；parent_id + top_level_only
       同时给出 = 等价 AND（先 top_level_only 过滤再加 parent_id 条件）。total 为过滤后总数。'''

3. 迁移函数（inkflow.core.database，与 ensure_provider_builtin_key_column 并列，spec §5.4 逐字）:

   def ensure_world_parent_id_column(conn: Connection) -> None:
       '''幂等: PRAGMA table_info 查列 → 缺列 ALTER TABLE ADD COLUMN parent_id INTEGER；
       DROP INDEX IF EXISTS uq_world_settings_active_name（旧全局唯一）；
       CREATE UNIQUE INDEX IF NOT EXISTS uq_world_settings_active_name_parent
       ON world_settings (project_id, parent_id, name) WHERE is_deleted = 0。
       表不存在（全新环境）→ no-op 不抛错（create_all 建新表自动含列+新索引）。'''

4. 领域模型（domain/models/world.py）: WorldSetting 新增 `parent_id: uuid.UUID | None = None`
   （None = 顶层）；_orm_to_domain / _domain_to_orm / update 三写点均映射 parent_id
   （DB int ↔ 领域 UUID 用 _int_to_uuid/_uuid_to_int 既有辅助，F14 教训）；DB 自增 int
   id 与 UUID 的换算: 持久化 int = domain.id.int（跨实体引用 parent_id 用 int）。

5. 错误类归属（本文件不直接断言，service 测试文件覆盖）: WorldParentNotFoundError /
   WorldCycleError / WorldChildrenActionRequiredError / WorldReparentTargetError
   全部继承 WorldServiceError（inkflow.domain.ports.world_errors），API 映射 422。

═══════════════════════════════════════════════════════════════════════
RED 预期形态（当前 src/ 未实现 F35）— 混合失败，全部 FAILED 无 ERROR:
  - 迁移 4 用例: 用例体内惰性 import 抛 ImportError（ensure_world_parent_id_column
    不存在）→ FAILED（惰性原因: 文件顶部 import 会收集期整文件失败，F23 教训）
  - repo 新方法 19 用例: AttributeError 'SQLiteWorldRepository' object has no
    attribute 'collect_ancestor_ids' / 'list_descendants' / 'get_by_parent_and_name'
    / 'hard_delete_many' / 'delete_with_reparent'
  - 列表过滤 4 用例: TypeError list() got an unexpected keyword argument
    'parent_id' / 'top_level_only'
  - 三写点 3 用例: AttributeError 'WorldSetting' object has no attribute 'parent_id'
    （领域模型缺字段；pydantic v2 默认忽略 extra 不报错，断言访问才暴露）
  - 1 个用例（get_by_parent_and_name::same_name_different_parents）: sqlite3.IntegrityError
    UNIQUE constraint failed (project_id, name) —— 当前库仍是旧全局唯一索引
    uq_world_settings_active_name，跨层同名被 DB 拒绝；GREEN 换新索引
    uq_world_settings_active_name_parent 后自动转绿（spec §2.3 索引替换语义）
  - 1 个用例 PASS: list 缺省全量（向后兼容回归，不依赖新参数）
═══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.world import WorldSetting
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.world import WorldSettingORM
from inkflow.infrastructure.database.repositories.world_repo import SQLiteWorldRepository

# 注意: 不在此处 import ensure_world_parent_id_column（F35 尚未实现，
# 顶部 import 会收集期整文件失败）——迁移用例体内惰性 import（F23 教训）。


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库.

    ⚠️ 不开 PRAGMA foreign_keys=ON（与生产 D10=b 一致：生产连接未开 FK，
    运行时 FK 语义由 service 层显式保证）——本文件测的 repo 语义（hard_delete_many
    精确删给定集合、级联由 service 用 list_descendants 计算）在 FK OFF 下才成立；
    FK ON 会让 DELETE 父行级联删子，破坏「返回删除行数」断言。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def project(db_session):
    """一个基础项目（世界观条目的 FK 依赖）."""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.fixture
def sync_conn():
    """独立 in-memory SQLite（同步轨）— 迁移函数测试用（signature: conn: Connection）."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        yield conn
    engine.dispose()


def _now() -> datetime:
    """当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _setting(project: ProjectORM, name: str, **kw) -> WorldSetting:
    """构造待持久化的世界观条目领域对象（同 test_world_repo.py 镜像基准）.

    领域 id 为随机 UUID；落库时由 DB 自增分配 int 主键，读回时以
    uuid.UUID(int=orm.id) 还原。F35: parent_id 以 kw 透传（领域 UUID | None）；
    kw 覆盖默认 created_at/updated_at（排序断言需精确控制时间）。
    """
    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.UUID(int=project.id),
        "name": name,
        "created_at": _now(),
        "updated_at": _now(),
    }
    base.update(kw)
    return WorldSetting(**base)


async def _add_setting(repo, project, name, *, parent=None, created_at=None) -> WorldSetting:
    """建地点条目：parent 为父条目领域对象（None = 顶层）；created_at 可控（排序断言用）."""
    kw: dict = {}
    if parent is not None:
        kw["parent_id"] = parent.id
    if created_at is not None:
        kw["created_at"] = created_at
    return await repo.add(_setting(project, name, **kw))


async def _build_3level_tree(repo, project):
    """建 3 层树 国→州→县（spec §9 关键场景 1），返回 (country, state, county)."""
    country = await _add_setting(repo, project, "loc_country")
    state = await _add_setting(repo, project, "loc_state", parent=country)
    county = await _add_setting(repo, project, "loc_county", parent=state)
    return country, state, county


_LEGACY_TABLE_SQL = """
CREATE TABLE world_settings (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name VARCHAR(50) NOT NULL,
    category VARCHAR(50) NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    extra JSON NOT NULL DEFAULT '{}',
    is_deleted BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""


def _create_legacy_world_settings(conn) -> None:
    """构造 F10 旧库: world_settings 无 parent_id 列 + 旧全局唯一索引（spec §2.3/§5.4）."""
    conn.execute(text(_LEGACY_TABLE_SQL))
    conn.execute(
        text(
            "CREATE UNIQUE INDEX uq_world_settings_active_name "
            "ON world_settings (project_id, name) WHERE is_deleted = 0"
        )
    )


def _index_names(conn) -> set[str]:
    """PRAGMA index_list 断言辅助: 返回 (索引名, unique, partial) 三元组集合."""
    rows = conn.execute(text("PRAGMA index_list(world_settings)")).fetchall()
    return {row[1] for row in rows}


def _index_unique(conn, index_name: str) -> bool:
    rows = conn.execute(text("PRAGMA index_list(world_settings)")).fetchall()
    for row in rows:
        if row[1] == index_name:
            return bool(row[2])
    raise AssertionError(f"index {index_name} not found")


def _index_partial(conn, index_name: str) -> bool:
    rows = conn.execute(text("PRAGMA index_list(world_settings)")).fetchall()
    for row in rows:
        if row[1] == index_name:
            return bool(row[4])
    raise AssertionError(f"index {index_name} not found")


def _index_columns(conn, index_name: str) -> list[str]:
    rows = conn.execute(text(f"PRAGMA index_info({index_name})")).fetchall()
    return [row[2] for row in rows]


# ────────────────────────────────────────────────────────────────────
# 迁移幂等（spec §5.4 / §7 边界 15 / §9 关键场景 7）— ~4 cases
# ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWorldParentIdMigration:
    """ensure_world_parent_id_column 幂等迁移 — 真 SQLite 同步轨."""

    def test_migration_noop_when_table_missing(self, sync_conn):
        """表不存在（全新环境）→ no-op 不抛错，PRAGMA table_info 仍为空（spec §5.4）."""
        from inkflow.core.database import ensure_world_parent_id_column  # 惰性 import（F23）

        ensure_world_parent_id_column(sync_conn)
        cols = sync_conn.execute(text("PRAGMA table_info(world_settings)")).fetchall()
        assert cols == []

    def test_migration_legacy_table_adds_column_and_replaces_index(self, sync_conn):
        """旧库（无 parent_id 列 + 旧唯一索引）→ ALTER 加列 + 旧索引删 + 新索引建成，数据保留."""
        from inkflow.core.database import ensure_world_parent_id_column  # 惰性 import（F23）

        _create_legacy_world_settings(sync_conn)
        # 旧库已有数据：迁移不得破坏
        sync_conn.execute(
            text(
                "INSERT INTO world_settings (project_id, name, category, content, "
                "extra, is_deleted, created_at, updated_at) "
                "VALUES (1, '旧条目', '', '', '{}', 0, '2026-01-01', '2026-01-01')"
            )
        )

        ensure_world_parent_id_column(sync_conn)

        cols_rows = sync_conn.execute(text("PRAGMA table_info(world_settings)")).fetchall()
        cols = {row[1] for row in cols_rows}
        assert "parent_id" in cols

        names = _index_names(sync_conn)
        assert "uq_world_settings_active_name" not in names  # 旧索引已删
        assert "uq_world_settings_active_name_parent" in names  # 新索引建成
        assert _index_unique(sync_conn, "uq_world_settings_active_name_parent") is True
        assert _index_partial(sync_conn, "uq_world_settings_active_name_parent") is True
        # 新索引列序 = (project_id, parent_id, name)（同级唯一，spec §2.3）
        assert _index_columns(sync_conn, "uq_world_settings_active_name_parent") == [
            "project_id",
            "parent_id",
            "name",
        ]
        # 数据保留
        count = sync_conn.execute(text("SELECT COUNT(*) FROM world_settings")).scalar_one()
        assert count == 1

    def test_migration_idempotent_on_repeated_calls(self, sync_conn):
        """重复调用幂等: 第二次调用 no-op 不报错，不重复建索引（spec §5.4 / §9 场景 7）."""
        from inkflow.core.database import ensure_world_parent_id_column  # 惰性 import（F23）

        _create_legacy_world_settings(sync_conn)
        ensure_world_parent_id_column(sync_conn)
        ensure_world_parent_id_column(sync_conn)  # 再跑一次 → no-op

        rows = sync_conn.execute(text("PRAGMA index_list(world_settings)")).fetchall()
        new_index_count = sum(1 for row in rows if row[1] == "uq_world_settings_active_name_parent")
        assert new_index_count == 1
        assert "uq_world_settings_active_name" not in {row[1] for row in rows}

    def test_migration_applies_to_create_all_schema(self, sync_conn):
        """create_all 建的全新库（当前 F10 ORM 形态）→ 迁移补列 + 索引替换，
        终态一致（§7 边界 15）."""
        from inkflow.core.database import ensure_world_parent_id_column  # 惰性 import（F23）

        Base.metadata.create_all(sync_conn)  # F10 ORM 形态（无 parent_id + 旧索引）

        ensure_world_parent_id_column(sync_conn)

        cols_rows = sync_conn.execute(text("PRAGMA table_info(world_settings)")).fetchall()
        cols = {row[1] for row in cols_rows}
        assert "parent_id" in cols
        names = _index_names(sync_conn)
        assert "uq_world_settings_active_name" not in names
        assert "uq_world_settings_active_name_parent" in names
        assert _index_columns(sync_conn, "uq_world_settings_active_name_parent") == [
            "project_id",
            "parent_id",
            "name",
        ]


# ────────────────────────────────────────────────────────────────────
# 递归 CTE（spec §5.3 / §9 关键场景 1）— ~7 cases（真 SQLite 集成）
# ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWorldAncestorDescendantCte:
    """collect_ancestor_ids（不含自身，父链）与 list_descendants（含自身，层序）."""

    async def test_collect_ancestor_ids_returns_parent_chain_excluding_self(
        self, db_session, project
    ):
        """3 层树 国→州→县: collect_ancestor_ids(县) = [州, 国]，不含自身（spec §9 场景 1）."""
        repo = SQLiteWorldRepository(db_session)
        country, state, county = await _build_3level_tree(repo, project)

        assert await repo.collect_ancestor_ids(county.id.int) == [state.id.int, country.id.int]
        assert await repo.collect_ancestor_ids(state.id.int) == [country.id.int]
        assert await repo.collect_ancestor_ids(country.id.int) == []

    async def test_list_descendants_includes_self_level_order(self, db_session, project):
        """list_descendants(国) = [国, 州, 县]（含自身，层序父先子后，spec §9 场景 1）."""
        repo = SQLiteWorldRepository(db_session)
        country, state, county = await _build_3level_tree(repo, project)

        desc = await repo.list_descendants(country.id.int)
        assert [s.id for s in desc] == [country.id, state.id, county.id]
        assert [s.name for s in desc] == ["loc_country", "loc_state", "loc_county"]

    async def test_deep_tree_four_levels(self, db_session, project):
        """4 层深树（A→B→C→D）: 祖先链与子树均正确（任意深度，spec §2.1 规则 1）."""
        repo = SQLiteWorldRepository(db_session)
        a = await _add_setting(repo, project, "loc_A")
        b = await _add_setting(repo, project, "loc_B", parent=a)
        c = await _add_setting(repo, project, "loc_C", parent=b)
        d = await _add_setting(repo, project, "loc_D", parent=c)

        assert await repo.collect_ancestor_ids(d.id.int) == [c.id.int, b.id.int, a.id.int]
        desc = await repo.list_descendants(a.id.int)
        assert [s.id for s in desc] == [a.id, b.id, c.id, d.id]

    async def test_soft_deleted_excluded_from_cte(self, db_session, project):
        """软删条目不进入 CTE 结果: 软删中间节点 → 祖先链断、子孙不可达
        （spec §5.3 WHERE is_deleted=0）."""
        repo = SQLiteWorldRepository(db_session)
        country, state, county = await _build_3level_tree(repo, project)

        await repo.soft_delete(state.id.int)

        # 县仍活动，但其父链经过软删的州 → 断链 → 无祖先
        assert await repo.collect_ancestor_ids(county.id.int) == []
        # 国的子树只剩自身（州被排除，县经州不可达）
        desc = await repo.list_descendants(country.id.int)
        assert [s.id for s in desc] == [country.id]
        # 软删节点自身也不可进入 CTE
        assert await repo.collect_ancestor_ids(state.id.int) == []
        assert await repo.list_descendants(state.id.int) == []

    async def test_missing_id_returns_empty(self, db_session, project):
        """不存在的 id → 空列表（不抛错，spec §5.3 起始 SELECT 不命中）."""
        repo = SQLiteWorldRepository(db_session)
        assert await repo.collect_ancestor_ids(99999) == []
        assert await repo.list_descendants(99999) == []

    async def test_descendants_same_level_sorted_by_created_at(self, db_session, project):
        """同层按 created_at ASC 层序稳定输出（F15 教训: 排序键用时间键，不依赖中文文本）."""
        repo = SQLiteWorldRepository(db_session)
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        a = await _add_setting(repo, project, "loc_A", created_at=t0)
        b1 = await _add_setting(
            repo, project, "loc_B1", parent=a, created_at=datetime(2026, 1, 2, tzinfo=UTC)
        )
        b2 = await _add_setting(
            repo, project, "loc_B2", parent=a, created_at=datetime(2026, 1, 3, tzinfo=UTC)
        )
        await _add_setting(
            repo, project, "loc_C1", parent=b1, created_at=datetime(2026, 1, 4, tzinfo=UTC)
        )
        await _add_setting(
            repo, project, "loc_C2", parent=b2, created_at=datetime(2026, 1, 5, tzinfo=UTC)
        )

        desc = await repo.list_descendants(a.id.int)
        assert [s.name for s in desc] == ["loc_A", "loc_B1", "loc_B2", "loc_C1", "loc_C2"]

    async def test_descendants_map_parent_id_to_domain_uuid(self, db_session, project):
        """list_descendants 返回完整领域对象: parent_id 为领域 UUID（DB int → UUID 映射正确）."""
        repo = SQLiteWorldRepository(db_session)
        country, state, county = await _build_3level_tree(repo, project)

        desc = await repo.list_descendants(country.id.int)
        by_id = {s.id: s for s in desc}
        assert by_id[country.id].parent_id is None
        assert by_id[state.id].parent_id == country.id
        assert by_id[county.id].parent_id == state.id


# ────────────────────────────────────────────────────────────────────
# 列表 parent_id 过滤（spec §5.3 / §7 边界 16 / §9 关键场景 6）— ~4 cases
# ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWorldListParentFilter:
    """list 末尾追加 parent_id / top_level_only 过滤参数（Q3=A，向后兼容）."""

    async def _build_filter_tree(self, repo, project):
        a = await _add_setting(repo, project, "loc_A")  # 顶层
        b = await _add_setting(repo, project, "loc_B")  # 顶层
        c = await _add_setting(repo, project, "loc_C", parent=a)
        d = await _add_setting(repo, project, "loc_D", parent=a)
        e = await _add_setting(repo, project, "loc_E", parent=b)
        return a, b, c, d, e

    async def test_list_default_no_filter_returns_all(self, db_session, project):
        """缺省（不传 parent_id/top_level_only）→ 全量，向后兼容（spec §7 边界 16）."""
        repo = SQLiteWorldRepository(db_session)
        await self._build_filter_tree(repo, project)

        settings, total = await repo.list(project.id, sort_by="name", sort_desc=False)
        assert total == 5
        assert [s.name for s in settings] == ["loc_A", "loc_B", "loc_C", "loc_D", "loc_E"]

    async def test_list_parent_id_returns_direct_children(self, db_session, project):
        """parent_id=<int> → 只返回该父的直接子级（不含孙辈与顶层，spec §7 边界 16）."""
        repo = SQLiteWorldRepository(db_session)
        a, _, _, c, _ = await self._build_filter_tree(repo, project)

        settings, total = await repo.list(
            project.id, parent_id=a.id.int, sort_by="name", sort_desc=False
        )
        assert total == 2
        assert [s.name for s in settings] == ["loc_C", "loc_D"]

        # 父无子 → 空
        assert await repo.list(project.id, parent_id=c.id.int) == ([], 0)

    async def test_list_top_level_only(self, db_session, project):
        """top_level_only=True → 只返回 parent_id IS NULL 的顶层（spec §7 边界 16）."""
        repo = SQLiteWorldRepository(db_session)
        await self._build_filter_tree(repo, project)

        settings, total = await repo.list(
            project.id, top_level_only=True, sort_by="name", sort_desc=False
        )
        assert total == 2
        assert [s.name for s in settings] == ["loc_A", "loc_B"]

    async def test_list_parent_id_and_top_level_only_are_anded(self, db_session, project):
        """parent_id + top_level_only 同时给出 → 等价 AND
        （先 top_level_only 过滤再加 parent_id 条件）."""
        repo = SQLiteWorldRepository(db_session)
        a, _, _, _, _ = await self._build_filter_tree(repo, project)

        # AND: 无条目既属于 A 的直接子级又是顶层 → 空
        assert await repo.list(project.id, parent_id=a.id.int, top_level_only=True) == ([], 0)
        # parent_id=None（哨兵 = 未过滤）+ top_level_only → 顶层
        settings, total = await repo.list(project.id, parent_id=None, top_level_only=True)
        assert total == 2
        assert {s.name for s in settings} == {"loc_A", "loc_B"}


# ────────────────────────────────────────────────────────────────────
# 删除语义 repo 层（spec §5.5 / §9 关键场景 4）— ~6 cases
# ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWorldHardDeleteSemantics:
    """hard_delete_many（级联真删底座）与 delete_with_reparent（子改挂）— 真删，物理消失."""

    async def test_hard_delete_many_removes_subtree_and_returns_count(self, db_session, project):
        """hard_delete_many(子树 id 列表) → 单事务物理删除，返回删除行数；
        get 全 None（spec §5.5）."""
        repo = SQLiteWorldRepository(db_session)
        country, state, county = await _build_3level_tree(repo, project)

        n = await repo.hard_delete_many([country.id.int, state.id.int, county.id.int])
        assert n == 3
        assert await repo.get(country.id.int) is None
        assert await repo.get(state.id.int) is None
        assert await repo.get(county.id.int) is None
        # 物理删除（非 is_deleted=1）: 表内行数归零
        count = await db_session.execute(select(func.count()).select_from(WorldSettingORM))
        assert count.scalar_one() == 0

    async def test_hard_delete_many_empty_list_returns_zero(self, db_session, project):
        """空列表 → 返回 0 不报错（幂等）."""
        repo = SQLiteWorldRepository(db_session)
        assert await repo.hard_delete_many([]) == 0

    async def test_hard_delete_many_missing_ids_and_partial(self, db_session, project):
        """不存在的 id 不计入删除数；混合列表只删存在的行（行为: 按传入 id 精确物理删）."""
        repo = SQLiteWorldRepository(db_session)
        country, state, county = await _build_3level_tree(repo, project)

        assert await repo.hard_delete_many([99999]) == 0
        # 只删 country（未传子级）→ 返回 1，子级仍在（子树集合由 service 用 list_descendants 计算）
        assert await repo.hard_delete_many([country.id.int, 99999]) == 1
        assert await repo.get(country.id.int) is None
        assert await repo.get(state.id.int) is not None
        assert await repo.get(county.id.int) is not None

    async def test_delete_with_reparent_moves_children_and_deletes_self(self, db_session, project):
        """delete_with_reparent(父id, 新父id) → 子改挂新父 + 自身删除，单事务（spec §5.5）."""
        repo = SQLiteWorldRepository(db_session)
        country, state, county = await _build_3level_tree(repo, project)
        x = await _add_setting(repo, project, "loc_X")  # reparent 目标（顶层）

        assert await repo.delete_with_reparent(state.id.int, x.id.int) is True
        assert await repo.get(state.id.int) is None  # 自身物理删除
        assert await repo.get(country.id.int) is not None  # 父不受影响

        county_after = await repo.get(county.id.int)
        assert county_after is not None
        assert county_after.parent_id == x.id  # 直接子改挂新父

    async def test_delete_with_reparent_grandchild_level_unchanged(self, db_session, project):
        """孙子层级不变: 4 层树 A→B→C→D，删 B reparent 到 X → C 改挂 X，D 仍挂 C（树整体平移）."""
        repo = SQLiteWorldRepository(db_session)
        a = await _add_setting(repo, project, "loc_A")
        b = await _add_setting(repo, project, "loc_B", parent=a)
        c = await _add_setting(repo, project, "loc_C", parent=b)
        d = await _add_setting(repo, project, "loc_D", parent=c)
        x = await _add_setting(repo, project, "loc_X")

        assert await repo.delete_with_reparent(b.id.int, x.id.int) is True
        c_after = await repo.get(c.id.int)
        d_after = await repo.get(d.id.int)
        assert c_after is not None and c_after.parent_id == x.id
        assert d_after is not None and d_after.parent_id == c.id  # 孙的 parent 仍指向子

    async def test_delete_with_reparent_without_children_deletes_only_self(
        self, db_session, project
    ):
        """无子地点 → 自身物理删除，返回 True（UPDATE 0 行 + DELETE 自身仍为合法机械操作）."""
        repo = SQLiteWorldRepository(db_session)
        a = await _add_setting(repo, project, "loc_A")
        b = await _add_setting(repo, project, "loc_B")

        assert await repo.delete_with_reparent(a.id.int, b.id.int) is True
        assert await repo.get(a.id.int) is None
        assert await repo.get(b.id.int) is not None


# ────────────────────────────────────────────────────────────────────
# 三写点 parent_id 往返（spec §9 关键场景 8，F14 教训）— ~3 cases
# ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWorldParentIdWriteRoundtrip:
    """add / update / domain↔orm 转换三写点 parent_id 往返一致（UUID.int 跨实体引用陷阱）."""

    async def test_add_with_parent_id_roundtrip(self, db_session, project):
        """add 带 parent_id（领域 UUID）→ 返回与 get 读回一致；DB 行为 int（UUID.int 映射）."""
        repo = SQLiteWorldRepository(db_session)
        country = await _add_setting(repo, project, "loc_country")
        county = await _add_setting(repo, project, "loc_county", parent=country)

        assert county.parent_id == country.id
        got = await repo.get(county.id.int)
        assert got is not None and got.parent_id == country.id

        # 持久化验证: DB 行 parent_id 为 int（uuid.UUID(int=...).int 换算）
        row = await db_session.execute(
            select(WorldSettingORM).where(WorldSettingORM.id == county.id.int)
        )
        assert row.scalar_one().parent_id == country.id.int

    async def test_update_changes_parent_id_roundtrip(self, db_session, project):
        """update 改 parent_id → 返回对象与 get 读回一致（改挂）."""
        repo = SQLiteWorldRepository(db_session)
        a = await _add_setting(repo, project, "loc_A")
        b = await _add_setting(repo, project, "loc_B")
        c = await _add_setting(repo, project, "loc_C", parent=a)

        updated = await repo.update(c.model_copy(update={"parent_id": b.id}))
        assert updated.parent_id == b.id

        got = await repo.get(c.id.int)
        assert got is not None and got.parent_id == b.id

    async def test_parent_id_none_preserved_and_promote_via_update(self, db_session, project):
        """parent_id None 往返保持 None（顶层）; update 显式置 None = 置顶
        （spec §2.2 None 语义）."""
        repo = SQLiteWorldRepository(db_session)
        a = await _add_setting(repo, project, "loc_A")
        b = await _add_setting(repo, project, "loc_B", parent=a)
        assert b.parent_id == a.id

        top = await _add_setting(repo, project, "loc_top")  # 缺省 = 顶层
        assert top.parent_id is None
        got_top = await repo.get(top.id.int)
        assert got_top is not None and got_top.parent_id is None

        # 置顶: update 显式 parent_id=None → 读回 None
        promoted = await repo.update(b.model_copy(update={"parent_id": None}))
        assert promoted.parent_id is None
        got_b = await repo.get(b.id.int)
        assert got_b is not None and got_b.parent_id is None


# ────────────────────────────────────────────────────────────────────
# get_by_parent_and_name（spec §5.1 / §2.4 同级唯一校验用）— ~6 cases
# ────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWorldGetByParentAndName:
    """按 (project_id, parent_id, name) 查询活动条目 — 顶层应用层校验与同级唯一语义底座."""

    async def test_sibling_hit(self, db_session, project):
        """同级命中: 同父同名条目返回（partial unique 语义，spec §2.4）."""
        repo = SQLiteWorldRepository(db_session)
        _, state, county = await _build_3level_tree(repo, project)

        hit = await repo.get_by_parent_and_name(project.id, state.id.int, "loc_county")
        assert hit is not None and hit.id == county.id

    async def test_top_level_hit(self, db_session, project):
        """顶层命中: parent_id=None 查询顶层条目（顶层应用层校验，spec §2.4）."""
        repo = SQLiteWorldRepository(db_session)
        country, _, _ = await _build_3level_tree(repo, project)

        hit = await repo.get_by_parent_and_name(project.id, None, "loc_country")
        assert hit is not None and hit.id == country.id

    async def test_missing_returns_none(self, db_session, project):
        """不存在（父下无此名 / 父不存在）→ None."""
        repo = SQLiteWorldRepository(db_session)
        _, state, _ = await _build_3level_tree(repo, project)

        assert await repo.get_by_parent_and_name(project.id, state.id.int, "loc_nope") is None
        assert await repo.get_by_parent_and_name(project.id, 99999, "loc_county") is None

    async def test_soft_deleted_not_matched(self, db_session, project):
        """软删条目不命中（仅活动条目，spec §5.1 校验语义）."""
        repo = SQLiteWorldRepository(db_session)
        _, state, county = await _build_3level_tree(repo, project)
        await repo.soft_delete(county.id.int)

        assert await repo.get_by_parent_and_name(project.id, state.id.int, "loc_county") is None

    async def test_project_isolation(self, db_session, project):
        """跨项目不命中（parent 归属校验数据隔离基线，spec §2.1 规则 3）."""
        repo = SQLiteWorldRepository(db_session)
        _, state, _ = await _build_3level_tree(repo, project)

        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        # 其他项目建同名条目
        other_repo = SQLiteWorldRepository(db_session)
        await other_repo.add(_setting(other, "loc_county"))

        assert await repo.get_by_parent_and_name(project.id, state.id.int, "loc_county") is not None
        assert await repo.get_by_parent_and_name(other.id, state.id.int, "loc_county") is None

    async def test_same_name_different_parents_both_match(self, db_session, project):
        """不同父同名（跨层同名合法，新语义）→ 各自按 (父, 名) 命中（spec §2.4 场景表）."""
        repo = SQLiteWorldRepository(db_session)
        a = await _add_setting(repo, project, "loc_A")
        b = await _add_setting(repo, project, "loc_B")
        x1 = await _add_setting(repo, project, "loc_X", parent=a)
        x2 = await _add_setting(repo, project, "loc_X", parent=b)

        hit_a = await repo.get_by_parent_and_name(project.id, a.id.int, "loc_X")
        hit_b = await repo.get_by_parent_and_name(project.id, b.id.int, "loc_X")
        assert hit_a is not None and hit_a.id == x1.id
        assert hit_b is not None and hit_b.id == x2.id
        assert hit_a.id != hit_b.id
