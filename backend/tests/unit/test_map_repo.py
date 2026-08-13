"""SQLiteMapRepository 集成测试 — in-memory SQLite（F36 仓储层 RED→GREEN）.

覆盖 MapRepositoryProtocol 全部 16 个方法（spec §2.1/§2.2/§5.2/§5.5 + 父侧定稿契约）:
- maps CRUD: add/get/get_by_name/list/update/delete/delete_many
- pins CRUD: list_pins/add_pin/update_pin/delete_pin
- children JOIN（地点软删过滤——评审 F2；DISTINCT）
- list_by_root_locations（#175 共用查询）/ delete_by_project / clear_location_pins

【设计假设】——父侧定稿契约，GREEN 实现按此落地（本文件逐字钉死）:
1. list 签名: list(project_id, root_location_id=None, top_level_only=False,
   offset=0, limit=50) -> tuple[list[WorldMap], int]。过滤组合:
   root_location_id=None + top_level_only=False = 不过滤（全量）;
   top_level_only=True = 只返回全局图（root_location_id IS NULL）;
   root_location_id 非 None = 精确过滤。排序 created_at DESC。
2. delete(map_id) -> bool: 单事务 DELETE map_pins WHERE map_id=? +
   DELETE maps WHERE id=?（D10=b 显式级联——不依赖 DB FK 动作）。
3. delete_many(map_ids) -> int: 单事务逐 id 删其 pins + 行；返回删除的
   maps 行数（列表含不存在 id 不影响计数；空列表 = 0）。
4. children(map_id) -> list[WorldMap]: 单 SQL JOIN map_pins p
   (p.map_id=:id AND p.location_id IS NOT NULL) JOIN world_settings w
   (w.id=p.location_id AND w.is_deleted=0) JOIN maps m2
   (m2.root_location_id=p.location_id)；DISTINCT；ORDER BY created_at ASC。
5. update(map) -> WorldMap | None（按 id 定位全字段覆盖，不存在 → None）;
   update_pin(pin) -> MapPin | None（同语义）; delete_pin(pin_id) -> bool;
   list_pins(map_id) -> list[MapPin]（created_at ASC）;
   list_by_root_locations(project_id, location_ids) -> list[WorldMap]
   （空列表 → 空）; delete_by_project(project_id) -> int（单事务删
   pins+maps，返回 maps 行数）; clear_location_pins(location_id) -> int
   （UPDATE map_pins SET location_id=NULL，pin 保留、label 不变）。
6. maps/map_pins 均【无 is_deleted 列】（真删语义，spec §2.4）——repo 方法
   无任何软删过滤。
7. 领域/ORM 转换: repo 内部 _orm_to_domain/_domain_to_orm（int↔UUID）。
   跨实体引用一律用持久化返回的 id（陷阱 18）——本文件 pin/root_location_id
   全部取 add()/add_pin() 读回的 UUID。
8. add() 不保留领域 created_at/updated_at（DB 默认 _utcnow，F35 同款）——
   排序断言用显式 created_at 的 core insert 造数（_insert_map_direct /
   _insert_pin_direct）。

【RED 预期】
- 收集期 ModuleNotFoundError（模块未实现；顶部仅 import 主契约模块
  inkflow.infrastructure.database.repositories.map_repo）——正确 RED。
- 若 GREEN 分批落地中出现「模块存在但方法缺失」，按方法报
  AttributeError/TypeError——同样视为 RED 阶段预期形态。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.models.world import WorldSettingORM
from inkflow.infrastructure.database.repositories.map_repo import (
    SQLiteMapRepository,
)

# 顶部仅 import 主契约模块 map_repo（RED 阶段唯一必须顶层导入的未实现模块——
# 收集期 ModuleNotFoundError = 预期 RED）。其余未实现模块一律惰性导入（陷阱 5）:
#   - WorldMap/MapPin: 工厂 helper 内导入
#   - MapORM/MapPinORM: db_session fixture 内导入（create_all 前注册表）


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（启用 FK pragma）."""
    # 惰性导入 ORM：create_all 前注册 maps/map_pins 表。GREEN 后
    # models/__init__.py 亦会导入，此处显式导入保证本文件自足。
    from inkflow.infrastructure.database.models.map import (  # noqa: F401  # 惰性注册 ORM 供 create_all（fixture 内显式 import）
        MapORM,
        MapPinORM,
    )

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
    """一个基础项目（地图/pin/地点的 FK 依赖）."""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _now() -> datetime:
    """当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _map(project: ProjectORM, name: str, **kw):
    """构造待持久化的地图领域对象（kw 覆盖默认值，陷阱 4）.

    base dict + kw.update——不允许在 base 硬编码某字段后又经 kw 传同名
    参数（会 TypeError: multiple values for keyword argument）。
    """
    from inkflow.domain.models.map import WorldMap  # 惰性：RED 阶段模块未实现

    values = {
        "id": uuid.uuid4(),
        "project_id": uuid.UUID(int=project.id),
        "name": name,
        "image_path": "maps/x/main.png",
        "description": "",
        "root_location_id": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    values.update(kw)
    return WorldMap(**values)


def _pin(map_obj, **kw):
    """构造待持久化的 pin 领域对象（map_id 用持久化读回的 UUID，陷阱 18）."""
    from inkflow.domain.models.map import MapPin  # 惰性：RED 阶段模块未实现

    values = {
        "id": uuid.uuid4(),
        "map_id": map_obj.id,
        "location_id": None,
        "x": 50.0,
        "y": 50.0,
        "label": "标记",
        "created_at": _now(),
        "updated_at": _now(),
    }
    values.update(kw)
    return MapPin(**values)


async def _add_location(db_session, project, name: str) -> WorldSettingORM:
    """造一个持久化的地点（F35 WorldSettingORM 直接落库，非被测对象）."""
    loc = WorldSettingORM(project_id=project.id, name=name)
    db_session.add(loc)
    await db_session.commit()
    await db_session.refresh(loc)
    return loc


async def _insert_map_direct(db_session, project_id: int, name: str, created_at: datetime) -> int:
    """core insert 直插 maps 行（显式 created_at）——排序断言造数（陷阱 7）.

    repo.add 不保留领域 created_at（DB 默认 _utcnow，F35 同款），
    排序用例须绕过 repo 直插，才能得到确定性时间序。
    """
    from inkflow.infrastructure.database.models.map import MapORM  # 惰性

    result = await db_session.execute(
        insert(MapORM).values(
            project_id=project_id,
            name=name,
            image_path="maps/x/main.png",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    await db_session.commit()
    return int(result.inserted_primary_key[0])


async def _insert_pin_direct(db_session, map_id: int, created_at: datetime, **kw) -> int:
    """core insert 直插 map_pins 行（显式 created_at）——pins ASC 排序造数."""
    from inkflow.infrastructure.database.models.map import MapPinORM  # 惰性

    values = {
        "map_id": map_id,
        "location_id": None,
        "x": 50.0,
        "y": 50.0,
        "label": "直插pin",
        "created_at": created_at,
        "updated_at": created_at,
    }
    values.update(kw)
    result = await db_session.execute(insert(MapPinORM).values(**values))
    await db_session.commit()
    return int(result.inserted_primary_key[0])


@pytest.mark.integration
class TestMapRepository:
    """SQLiteMapRepository 集成测试 — maps/pins CRUD + children JOIN + 真删."""

    # ── maps CRUD ──

    async def test_add_and_get_roundtrip(self, db_session, project):
        """add 落库并读回；get 按 int 主键读回，UUID 映射与全字段一致."""
        repo = SQLiteMapRepository(db_session)
        loc = await _add_location(db_session, project, "青州")
        saved = await repo.add(
            _map(
                project,
                "青州地图",
                image_path="maps/abc/main.png",
                description="州域全图",
                root_location_id=uuid.UUID(int=loc.id),
            )
        )

        assert isinstance(saved.id, uuid.UUID)
        assert saved.project_id == uuid.UUID(int=project.id)
        assert saved.name == "青州地图"
        assert saved.image_path == "maps/abc/main.png"
        assert saved.description == "州域全图"
        assert saved.root_location_id == uuid.UUID(int=loc.id)

        # 持久化验证：直查 maps 表
        row = (
            await db_session.execute(
                text("SELECT name, root_location_id FROM maps WHERE id = :id"),
                {"id": saved.id.int},
            )
        ).one()
        assert row.name == "青州地图"
        assert row.root_location_id == loc.id

        got = await repo.get(saved.id.int)
        assert got is not None
        assert got.id == saved.id
        assert got.project_id == saved.project_id
        assert got.name == saved.name
        assert got.image_path == saved.image_path
        assert got.description == saved.description
        assert got.root_location_id == saved.root_location_id
        assert got.created_at == saved.created_at
        assert got.updated_at == saved.updated_at

    async def test_get_returns_none_for_missing(self, db_session, project):
        """get 对不存在的 id 返回 None."""
        repo = SQLiteMapRepository(db_session)
        assert await repo.get(99999) is None

    async def test_get_by_name_hit_miss_and_project_isolation(self, db_session, project):
        """get_by_name 命中；未命中/跨项目均返回 None."""
        repo = SQLiteMapRepository(db_session)
        m = await repo.add(_map(project, "东大陆全图"))

        hit = await repo.get_by_name(project.id, "东大陆全图")
        assert hit is not None and hit.id == m.id
        assert await repo.get_by_name(project.id, "不存在") is None

        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert await repo.get_by_name(other.id, "东大陆全图") is None

    async def test_list_full_sorted_by_created_at_desc(self, db_session, project):
        """list 全量（不过滤）按 created_at DESC；排除其他项目."""
        repo = SQLiteMapRepository(db_session)
        t = _now() - timedelta(minutes=10)
        await _insert_map_direct(db_session, project.id, "A地图", t)
        await _insert_map_direct(db_session, project.id, "B地图", t + timedelta(minutes=1))
        await _insert_map_direct(db_session, project.id, "C地图", t + timedelta(minutes=2))

        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        await _insert_map_direct(db_session, other.id, "Z地图", _now())

        maps, total = await repo.list(project.id)
        assert total == 3
        assert [m.name for m in maps] == ["C地图", "B地图", "A地图"]

    async def test_list_top_level_only_and_root_location_filter(self, db_session, project):
        """top_level_only=True → 仅全局图；root_location_id=X → 精确过滤."""
        repo = SQLiteMapRepository(db_session)
        loc1 = await _add_location(db_session, project, "青州")
        loc2 = await _add_location(db_session, project, "东大陆")
        g1 = await repo.add(_map(project, "全局图一"))
        g2 = await repo.add(_map(project, "全局图二"))
        m1 = await repo.add(_map(project, "青州图", root_location_id=uuid.UUID(int=loc1.id)))
        m2 = await repo.add(_map(project, "东大陆图", root_location_id=uuid.UUID(int=loc2.id)))

        tops, total = await repo.list(project.id, top_level_only=True)
        assert total == 2
        assert {m.id for m in tops} == {g1.id, g2.id}

        filtered, total_f = await repo.list(project.id, root_location_id=loc1.id)
        assert total_f == 1
        assert [m.id for m in filtered] == [m1.id]

        # 缺省（root_location_id=None + top_level_only=False）→ 全量
        all_maps, total_all = await repo.list(project.id)
        assert total_all == 4
        assert {m.id for m in all_maps} == {g1.id, g2.id, m1.id, m2.id}

    async def test_unique_constraints_name_and_root_location(self, db_session, project):
        """双唯一约束（repo 层断言 IntegrityError；422 语义归 service 层）.

        uq_maps_name (project_id, name) 冲突；uq_maps_root_location
        (project_id, root_location_id WHERE IS NOT NULL) 同地点第二张图冲突；
        全局图（root NULL）多张 OK。
        """
        repo = SQLiteMapRepository(db_session)
        loc = await _add_location(db_session, project, "青州")
        loc_id = loc.id  # rollback 会过期 ORM 属性（F13 教训：先缓存 int 主键）
        await repo.add(_map(project, "青州地图"))
        await repo.add(_map(project, "东大陆图", root_location_id=uuid.UUID(int=loc_id)))

        # 同名冲突
        with pytest.raises(IntegrityError):
            await repo.add(_map(project, "青州地图"))
        await db_session.rollback()
        # rollback 使全部 ORM 属性过期（F13 教训）——refresh 后工厂才可安全访问 project.id
        await db_session.refresh(project)
        await db_session.refresh(loc)

        # 同地点第二张图冲突
        with pytest.raises(IntegrityError):
            await repo.add(_map(project, "清河图", root_location_id=uuid.UUID(int=loc_id)))
        await db_session.rollback()
        await db_session.refresh(project)

        # 全局图多张 OK（partial unique 对 NULL 不冲突）
        g1 = await repo.add(_map(project, "全局图一"))
        g2 = await repo.add(_map(project, "全局图二"))
        assert g1.id != g2.id

    async def test_update_map_roundtrip(self, db_session, project):
        """update 改名/改描述/改挂 root_location_id（含改全局）→ 读回一致；不存在 → None."""
        repo = SQLiteMapRepository(db_session)
        loc1 = await _add_location(db_session, project, "青州")
        loc2 = await _add_location(db_session, project, "东大陆")
        m = await repo.add(_map(project, "青州图", root_location_id=uuid.UUID(int=loc1.id)))

        updated = await repo.update(
            m.model_copy(
                update={
                    "name": "青州图·改",
                    "description": "新描述",
                    "root_location_id": uuid.UUID(int=loc2.id),
                }
            )
        )
        assert updated is not None
        assert updated.id == m.id
        assert updated.name == "青州图·改"
        assert updated.description == "新描述"
        assert updated.root_location_id == uuid.UUID(int=loc2.id)

        got = await repo.get(m.id.int)
        assert got is not None
        assert got.name == "青州图·改"
        assert got.root_location_id == uuid.UUID(int=loc2.id)

        # 改全局图（root_location_id=None）
        back_to_global = await repo.update(updated.model_copy(update={"root_location_id": None}))
        assert back_to_global is not None and back_to_global.root_location_id is None
        got2 = await repo.get(m.id.int)
        assert got2 is not None and got2.root_location_id is None

        # 不存在 → None
        ghost = _map(project, "幽灵图", id=uuid.UUID(int=99999))
        assert await repo.update(ghost) is None

    async def test_delete_map_cascades_pins(self, db_session, project):
        """delete 单事务删地图行 + 其 pins（D10=b 显式级联）；不存在/重复删 → False."""
        repo = SQLiteMapRepository(db_session)
        m = await repo.add(_map(project, "青州图"))
        await repo.add_pin(_pin(m, label="标记一"))
        await repo.add_pin(_pin(m, label="标记二"))

        assert await repo.delete(m.id.int) is True
        assert await repo.get(m.id.int) is None
        # pins 显式级联删除（不依赖 DB FK 动作）
        count = (await db_session.execute(text("SELECT COUNT(*) FROM map_pins"))).scalar_one()
        assert count == 0

        assert await repo.delete(m.id.int) is False
        assert await repo.delete(99999) is False

    async def test_delete_many_maps_and_pins(self, db_session, project):
        """delete_many 单事务删多图 + 各自 pins；返回删除行数；含不存在 id 不影响计数."""
        repo = SQLiteMapRepository(db_session)
        m1 = await repo.add(_map(project, "图一"))
        m2 = await repo.add(_map(project, "图二"))
        m3 = await repo.add(_map(project, "图三"))
        await repo.add_pin(_pin(m1))
        await repo.add_pin(_pin(m2))
        await repo.add_pin(_pin(m3))

        deleted = await repo.delete_many([m1.id.int, m2.id.int, 99999])
        assert deleted == 2
        assert await repo.get(m1.id.int) is None
        assert await repo.get(m2.id.int) is None
        assert await repo.get(m3.id.int) is not None
        count = (await db_session.execute(text("SELECT COUNT(*) FROM map_pins"))).scalar_one()
        assert count == 1

        assert await repo.delete_many([]) == 0

    # ── pins CRUD ──

    async def test_add_pin_and_list_pins_created_at_asc(self, db_session, project):
        """add_pin 往返；list_pins 按 created_at ASC（直插显式时间造数）."""
        repo = SQLiteMapRepository(db_session)
        m = await repo.add(_map(project, "青州图"))
        t = _now() - timedelta(minutes=5)
        id1 = await _insert_pin_direct(db_session, m.id.int, t, label="最早")
        id2 = await _insert_pin_direct(db_session, m.id.int, t + timedelta(minutes=1), label="中间")
        id3 = await _insert_pin_direct(db_session, m.id.int, t + timedelta(minutes=2), label="最晚")

        pins = await repo.list_pins(m.id.int)
        assert [p.id.int for p in pins] == [id1, id2, id3]
        assert [p.label for p in pins] == ["最早", "中间", "最晚"]

        # add_pin 往返：UUID 映射 + 字段（location_id 缺省 None）
        added = await repo.add_pin(_pin(m, x=42.5, y=68.0, label="新pin"))
        assert isinstance(added.id, uuid.UUID)
        assert added.map_id == m.id
        assert added.x == 42.5 and added.y == 68.0
        assert added.label == "新pin"
        assert added.location_id is None

        pins2 = await repo.list_pins(m.id.int)
        assert len(pins2) == 4
        assert pins2[-1].id == added.id

    async def test_update_pin_full_field(self, db_session, project):
        """update_pin 全字段覆盖（x/y/label/location_id）；不存在 → None."""
        repo = SQLiteMapRepository(db_session)
        m = await repo.add(_map(project, "青州图"))
        loc = await _add_location(db_session, project, "清河县城")
        p = await repo.add_pin(_pin(m, x=10.0, y=20.0, label="旧label"))

        updated = await repo.update_pin(
            p.model_copy(
                update={
                    "x": 33.5,
                    "y": 44.5,
                    "label": "新label",
                    "location_id": uuid.UUID(int=loc.id),
                }
            )
        )
        assert updated is not None
        assert updated.id == p.id
        assert updated.x == 33.5 and updated.y == 44.5
        assert updated.label == "新label"
        assert updated.location_id == uuid.UUID(int=loc.id)

        got = (await repo.list_pins(m.id.int))[0]
        assert got.x == 33.5 and got.label == "新label"
        assert got.location_id == uuid.UUID(int=loc.id)

        # 不存在 → None
        ghost = _pin(m, id=uuid.UUID(int=99999))
        assert await repo.update_pin(ghost) is None

    async def test_delete_pin(self, db_session, project):
        """delete_pin 真删；重复删/不存在 → False."""
        repo = SQLiteMapRepository(db_session)
        m = await repo.add(_map(project, "青州图"))
        p1 = await repo.add_pin(_pin(m, label="一"))
        p2 = await repo.add_pin(_pin(m, label="二"))

        assert await repo.delete_pin(p1.id.int) is True
        pins = await repo.list_pins(m.id.int)
        assert [p.id for p in pins] == [p2.id]
        assert await repo.delete_pin(p1.id.int) is False
        assert await repo.delete_pin(99999) is False

    # ── children（drill-down JOIN，评审 F2，load-bearing）──

    async def test_children_with_location_and_hard_delete_filter(self, db_session, project):
        """children: A pin→B，B 挂图 C → children(A) 含 C；无 pin → 空；
        B 真删（物理删除，v1.1）→ children(A) 不含 C."""
        repo = SQLiteMapRepository(db_session)
        a = await repo.add(_map(project, "A全图"))
        b = await _add_location(db_session, project, "青州")
        c = await repo.add(_map(project, "C青州图", root_location_id=uuid.UUID(int=b.id)))
        await repo.add_pin(_pin(a, location_id=uuid.UUID(int=b.id), label="青州"))

        # 懒构建合法态：无 pin 的地图 → 空列表
        empty_map = await repo.add(_map(project, "无pin图"))
        assert await repo.children(empty_map.id.int) == []

        children = await repo.children(a.id.int)
        assert [m.id for m in children] == [c.id]

        # 地点真删（FK ON 下先清依赖：clear_location_pins 置空 pin、删除以 B 为根的地图 C，
        # 再物理删 B）→ 该地点下地图不再出现在 children（v1.1 真删语义）
        await repo.clear_location_pins(b.id)
        await repo.delete(c.id.int)
        from inkflow.infrastructure.database.repositories.world_repo import SQLiteWorldRepository

        await SQLiteWorldRepository(db_session).hard_delete(b.id)
        assert await repo.children(a.id.int) == []

    async def test_children_dedup_same_location_two_pins(self, db_session, project):
        """两个 pin 指向同一地点 → children 只返回一次（DISTINCT）."""
        repo = SQLiteMapRepository(db_session)
        a = await repo.add(_map(project, "A全图"))
        b = await _add_location(db_session, project, "青州")
        c = await repo.add(_map(project, "C青州图", root_location_id=uuid.UUID(int=b.id)))
        await repo.add_pin(_pin(a, location_id=uuid.UUID(int=b.id), label="青州1"))
        await repo.add_pin(_pin(a, location_id=uuid.UUID(int=b.id), label="青州2"))

        children = await repo.children(a.id.int)
        assert [m.id for m in children] == [c.id]

    # ── 共用查询 / 项目级操作（#175 / D10=b）──

    async def test_list_by_root_locations(self, db_session, project):
        """list_by_root_locations 批量多地点查询；空列表/不存在地点 → 空.

        F37 契约升级（spec §8）：签名扩展 include_global: bool = True（默认含全局图）。
        本用例显式传 include_global=False 保持原语义（不含全局图）。
        RED: 签名未扩展 → TypeError: ... unexpected keyword argument 'include_global'.
        """
        repo = SQLiteMapRepository(db_session)
        b1 = await _add_location(db_session, project, "青州")
        b2 = await _add_location(db_session, project, "东大陆")
        c1 = await repo.add(_map(project, "C1青州图", root_location_id=uuid.UUID(int=b1.id)))
        c2 = await repo.add(_map(project, "C2东大陆图", root_location_id=uuid.UUID(int=b2.id)))
        await repo.add(_map(project, "全局图"))

        found = await repo.list_by_root_locations(project.id, [b1.id, b2.id], include_global=False)
        assert {m.id for m in found} == {c1.id, c2.id}

        assert await repo.list_by_root_locations(project.id, [], include_global=False) == []
        assert await repo.list_by_root_locations(project.id, [99999], include_global=False) == []

    async def test_delete_by_project_and_clear_location_pins(self, db_session, project):
        """delete_by_project 单事务删项目全部 maps+pins 返回 maps 行数；
        clear_location_pins 置空 location_id，pin 保留且 label 不变."""
        repo = SQLiteMapRepository(db_session)
        loc = await _add_location(db_session, project, "青州")
        m1 = await repo.add(_map(project, "图一"))
        await repo.add(_map(project, "图二", root_location_id=uuid.UUID(int=loc.id)))
        await repo.add_pin(_pin(m1, location_id=uuid.UUID(int=loc.id), label="青州pin"))
        await repo.add_pin(_pin(m1, label="注释pin"))

        # clear_location_pins：SET NULL，pin 保留、label 不变
        cleared = await repo.clear_location_pins(loc.id)
        assert cleared == 1
        pins = await repo.list_pins(m1.id.int)
        assert len(pins) == 2
        by_label = {p.label: p for p in pins}
        assert by_label["青州pin"].location_id is None
        assert by_label["注释pin"].location_id is None

        # delete_by_project：删项目全部 maps + pins（D10=b 显式级联）
        deleted = await repo.delete_by_project(project.id)
        assert deleted == 2
        assert await repo.list(project.id) == ([], 0)
        count = (await db_session.execute(text("SELECT COUNT(*) FROM map_pins"))).scalar_one()
        assert count == 0


# ── F37 跨书复制（#175）：list_by_root_locations include_global（Q3=B 全局图，spec §8）──


@pytest.mark.integration
class TestListByRootLocationsGlobal:
    """F37 include_global 契约（spec §8）: 默认 True 含全局图；False 仅关联地点图.

    统一契约签名（父侧定稿，GREEN 按此实现）:
    map_repository.py 签名扩展:
      async def list_by_root_locations(
          self, project_id: int, location_ids: builtins.list[int],
          include_global: bool = True,
      ) -> builtins.list[WorldMap]
    map_repo.py 实现: WHERE project_id=? AND (root_location_id IN (:ids) OR
      (include_global AND root_location_id IS NULL))

    RED 阶段预期: 签名未扩展 → TypeError（unexpected keyword argument
    'include_global'）；缺省语义用例 → AssertionError（全局图缺失）；既有其余用例 PASS。
    """

    async def test_default_include_global_true(self, db_session, project):
        """缺省调用（不传 include_global）→ 关联地点图 + 全局图（root NULL）.
        RED: 缺省不含全局图 → AssertionError.
        """
        repo = SQLiteMapRepository(db_session)
        b1 = await _add_location(db_session, project, "青州")
        c1 = await repo.add(_map(project, "C1青州图", root_location_id=uuid.UUID(int=b1.id)))
        g1 = await repo.add(_map(project, "全局图"))

        found = await repo.list_by_root_locations(project.id, [b1.id])
        assert {m.id for m in found} == {c1.id, g1.id}

    async def test_include_global_false_excludes_global(self, db_session, project):
        """include_global=False → 仅关联地点图（不含全局图）.
        RED: 签名未扩展 → TypeError.
        """
        repo = SQLiteMapRepository(db_session)
        b1 = await _add_location(db_session, project, "青州")
        c1 = await repo.add(_map(project, "C1青州图", root_location_id=uuid.UUID(int=b1.id)))
        await repo.add(_map(project, "全局图"))

        found = await repo.list_by_root_locations(project.id, [b1.id], include_global=False)
        assert [m.id for m in found] == [c1.id]

    async def test_empty_location_ids_true_returns_only_global(self, db_session, project):
        """空地点列表 + include_global=True → 只返回全局图（Q3=B）.
        RED: 签名未扩展 → TypeError.
        """
        repo = SQLiteMapRepository(db_session)
        await repo.add(_map(project, "全局图"))

        found = await repo.list_by_root_locations(project.id, [], include_global=True)
        assert [m.name for m in found] == ["全局图"]

    async def test_empty_location_ids_false_returns_empty(self, db_session, project):
        """空地点列表 + include_global=False → 空列表.
        RED: 签名未扩展 → TypeError.
        """
        repo = SQLiteMapRepository(db_session)
        await repo.add(_map(project, "全局图"))

        assert await repo.list_by_root_locations(project.id, [], include_global=False) == []
