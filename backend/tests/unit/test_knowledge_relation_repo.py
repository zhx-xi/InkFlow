"""F48 知识图谱 — knowledge_relations 仓储层 RED 契约测试（spec v1.1 §9 repo ~14 cases，M1 验收）.

GREEN 必须匹配的契约（导入路径 = spec §8 文件表声明，缺模块 →
本文件收集期 ModuleNotFoundError = 预期 RED）:
- ORM 模型:   inkflow.infrastructure.database.models.knowledge_graph.KnowledgeRelationORM
              （__tablename__ = "knowledge_relations"；无 is_deleted 列——真删语义；
              唯一索引 uq_knowledge_relations_key(project_id, source_type, source_id,
              target_type, target_id, relation_type)；FK 仅 project_id → projects.id CASCADE）
- 仓储实现:   inkflow.infrastructure.database.repositories.
              knowledge_relation_repo.SQLiteKnowledgeRelationRepository
- 领域模型:   inkflow.domain.models.knowledge_graph.{EntityType, RelationSource, KnowledgeRelation}

方法契约（入参 int 主键，UUID↔int 映射沿用 F1 uuid.UUID(int=orm.id) 惯例）:
- add(relation) -> KnowledgeRelation                    # DB 自增分配 int 主键，往返映射
- get(relation_id: int) -> KnowledgeRelation | None
- get_by_key(project_id, source_type, source_id, target_type,
  target_id, relation_type) -> KnowledgeRelation | None
- list(project_id, offset=0, limit=50) -> (list, total)  # created_at DESC（新在前）
- filter(project_id, source_type=None, target_type=None, relation_type=None, source=None,
         offset=0, limit=50) -> (list, total)            # 组合过滤 + 分页
- update(relation) -> KnowledgeRelation                  # 按 id 定位全字段覆盖
- delete(relation_id) -> bool                            # 真删（无 is_deleted）；不存在 False
- list_by_project(project_id) -> list                    # 图谱聚合用全量（§5.2）
- delete_by_entity(entity_type, entity_id) -> int        # source 或 target 匹配删除，返回删除行数
- cleanup_for_entity(entity_type, entity_id) -> int      # delete_by_entity 别名（§5.3）

唯一约束: 同六元组 (project_id, source_type, source_id, target_type, target_id, relation_type)
重复 add → IntegrityError（§2.1 规则 4）。

fixture 镜像生产（#327 教训）: in-memory SQLite + PRAGMA foreign_keys=ON（生产已全局启用 FK，
FK CASCADE 语义必须开）——同 test_character_repo.py 形态。

依据: specs/f48-knowledge-graph/spec.md §2.1/§2.5/§9/§13 M1。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.knowledge_graph import EntityType, KnowledgeRelation, RelationSource
from inkflow.infrastructure.database.models.knowledge_graph import KnowledgeRelationORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.knowledge_relation_repo import (
    SQLiteKnowledgeRelationRepository,
)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（启用 FK 级联，镜像生产 #327）."""
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
    """一个基础项目（knowledge_relations.project_id 的 FK 依赖）."""
    p = ProjectORM(name="测试项目")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


def _now() -> datetime:
    """当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _rel(
    project: ProjectORM,
    *,
    source_type: str = "character",
    source_id: uuid.UUID,
    target_type: str = "world",
    target_id: uuid.UUID,
    relation_type: str,
    description: str = "",
    source: str = "manual",
    created_at: datetime | None = None,
) -> KnowledgeRelation:
    """构造待持久化的图谱关系领域对象（source_id/target_id 为实体 UUID，仓储层转 int 存储）."""
    ts = created_at or _now()
    return KnowledgeRelation(
        id=uuid.UUID(int=100),
        project_id=uuid.UUID(int=project.id),
        source_type=EntityType(source_type),
        source_id=source_id,
        target_type=EntityType(target_type),
        target_id=target_id,
        relation_type=relation_type,
        description=description,
        source=RelationSource(source),
        created_at=ts,
        updated_at=ts,
    )


@pytest.mark.integration
class TestKnowledgeRelationRepository:
    """SQLiteKnowledgeRelationRepository 集成测试 — CRUD/唯一约束/过滤/真删/delete_by_entity."""

    # ── add/get/get_by_key ──

    async def test_add_and_get_roundtrip(self, db_session, project):
        """add 落库并返回领域对象；get 按 int 主键读回，UUID↔int 映射与时间戳往返正确."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        src = uuid.UUID(int=101)
        tgt = uuid.UUID(int=102)
        saved = await repo.add(
            _rel(
                project,
                source_id=src,
                target_id=tgt,
                relation_type="属于",
                description="林尘出身清河县",
            )
        )

        assert isinstance(saved.id, uuid.UUID)
        assert saved.project_id == uuid.UUID(int=project.id)
        assert saved.source_type == EntityType.CHARACTER
        assert saved.source_id == src
        assert saved.target_type == EntityType.WORLD
        assert saved.target_id == tgt
        assert saved.relation_type == "属于"
        assert saved.description == "林尘出身清河县"
        assert saved.source == RelationSource.MANUAL
        # 时区感知 UTC（域对象侧）；往返相等（F9 同款断言）
        assert saved.created_at.tzinfo is not None
        assert saved.updated_at.tzinfo is not None

        # 持久化验证：直接查表（int 列）
        row = await db_session.execute(
            select(KnowledgeRelationORM).where(KnowledgeRelationORM.id == saved.id.int)
        )
        orm = row.scalar_one()
        assert orm.project_id == project.id
        assert orm.source_type == "character"
        assert orm.source_id == src.int
        assert orm.target_id == tgt.int
        assert orm.relation_type == "属于"
        assert orm.source == "manual"

        got = await repo.get(saved.id.int)
        assert got is not None
        assert got.id == saved.id
        assert got.source_id == src
        assert got.target_id == tgt
        assert got.created_at == saved.created_at
        assert got.updated_at == saved.updated_at

    async def test_get_returns_none_for_missing(self, db_session, project):
        """get 对不存在的 id 返回 None."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        assert await repo.get(99999) is None

    async def test_get_by_key_hit_miss(self, db_session, project):
        """get_by_key 六元组精确命中；改任一维度/跨项目均 miss."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        src = uuid.UUID(int=103)
        tgt = uuid.UUID(int=104)
        r = await repo.add(_rel(project, source_id=src, target_id=tgt, relation_type="属于"))

        hit = await repo.get_by_key(project.id, "character", src.int, "world", tgt.int, "属于")
        assert hit is not None and hit.id == r.id

        assert (
            await repo.get_by_key(project.id, "character", src.int, "world", tgt.int, "宿敌")
            is None
        )
        assert (
            await repo.get_by_key(project.id, "outline", src.int, "world", tgt.int, "属于") is None
        )

        # 跨项目 miss
        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        assert (
            await repo.get_by_key(other.id, "character", src.int, "world", tgt.int, "属于") is None
        )

    # ── list（created_at DESC）与分页 ──

    async def test_list_orders_by_created_at_desc(self, db_session, project):
        """list 按 created_at DESC（新关系在前）；total 正确."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        old = await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=105),
                target_id=uuid.UUID(int=106),
                relation_type="旧关系",
                created_at=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            )
        )
        mid = await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=107),
                target_id=uuid.UUID(int=108),
                relation_type="中关系",
                created_at=datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC),
            )
        )
        new = await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=109),
                target_id=uuid.UUID(int=110),
                relation_type="新关系",
                created_at=datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC),
            )
        )

        rels, total = await repo.list(project.id)
        assert total == 3
        assert [r.id for r in rels] == [new.id, mid.id, old.id]

    async def test_list_pagination(self, db_session, project):
        """list 支持 offset/limit 分页."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        ids = []
        for i in range(5):
            r = await repo.add(
                _rel(
                    project,
                    source_id=uuid.UUID(int=111),
                    target_id=uuid.UUID(int=112),
                    relation_type=f"关系{i}",
                    created_at=datetime(2026, 1, 1 + i, 0, 0, 0, tzinfo=UTC),
                )
            )
            ids.append(r.id)

        page, total = await repo.list(project.id, offset=1, limit=2)
        assert total == 5
        assert [r.id for r in page] == [ids[3], ids[2]]  # DESC 分页

    # ── filter（source_type/target_type/relation_type/source 组合）──

    async def test_filter_by_source_type(self, db_session, project):
        """filter 按 source_type 精确过滤."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        c = await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=113),
                target_id=uuid.UUID(int=114),
                relation_type="属于",
            )
        )
        await repo.add(
            _rel(
                project,
                source_type="world",
                source_id=uuid.UUID(int=115),
                target_id=uuid.UUID(int=116),
                relation_type="位于",
            )
        )

        rels, total = await repo.filter(project.id, source_type="character")
        assert total == 1
        assert [r.id for r in rels] == [c.id]

    async def test_filter_by_target_type_and_relation_type(self, db_session, project):
        """filter 按 target_type / relation_type 精确过滤（可组合）."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        hit = await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=117),
                target_type="outline",
                target_id=uuid.UUID(int=118),
                relation_type="参与",
            )
        )
        await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=119),
                target_type="outline",
                target_id=uuid.UUID(int=120),
                relation_type="伏笔指向",
            )
        )

        rels, total = await repo.filter(project.id, target_type="outline", relation_type="参与")
        assert total == 1
        assert [r.id for r in rels] == [hit.id]

    async def test_filter_by_source_manual_and_ai(self, db_session, project):
        """filter 按 source 过滤：manual 行与 #479 预留 ai 行互斥可见."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        manual = await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=121),
                target_id=uuid.UUID(int=122),
                relation_type="属于",
            )
        )
        ai = await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=123),
                target_id=uuid.UUID(int=124),
                relation_type="提取关系",
                source="ai",
            )
        )

        m, m_total = await repo.filter(project.id, source="manual")
        assert m_total == 1 and m[0].id == manual.id
        a, a_total = await repo.filter(project.id, source="ai")
        assert a_total == 1 and a[0].id == ai.id

    async def test_filter_combined_with_pagination(self, db_session, project):
        """filter 组合条件 + 分页."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        for i in range(3):
            await repo.add(
                _rel(
                    project,
                    source_id=uuid.UUID(int=125),
                    target_id=uuid.UUID(int=200 + i),
                    relation_type="师徒",
                    created_at=datetime(2026, 1, 1 + i, 0, 0, 0, tzinfo=UTC),
                )
            )
        rels, total = await repo.filter(project.id, relation_type="师徒", offset=1, limit=1)
        assert total == 3
        assert len(rels) == 1

    # ── update ──

    async def test_update_overwrites_fields(self, db_session, project):
        """update 按 id 定位全字段覆盖（改终点/改类型/改描述）；source 字段透传不变."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        src = uuid.UUID(int=127)
        old_tgt = uuid.UUID(int=128)
        r = await repo.add(
            _rel(
                project,
                source_id=src,
                target_id=old_tgt,
                relation_type="属于",
                description="旧说明",
            )
        )

        new_tgt = uuid.UUID(int=129)
        updated = await repo.update(
            r.model_copy(
                update={
                    "target_id": new_tgt,
                    "relation_type": "出身",
                    "description": "新说明",
                }
            )
        )
        assert updated.id == r.id
        assert updated.target_id == new_tgt
        assert updated.relation_type == "出身"
        assert updated.description == "新说明"
        assert updated.source == RelationSource.MANUAL  # source 不可经 update 变更

        got = await repo.get(r.id.int)
        assert got is not None
        assert got.target_id == new_tgt
        assert got.relation_type == "出身"

    # ── delete（真删语义，无 is_deleted）──

    async def test_delete_hard_deletes_row(self, db_session, project):
        """delete 物理删除；重复删除返回 False（真删语义，无软删列）."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        r = await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=130),
                target_id=uuid.UUID(int=131),
                relation_type="属于",
            )
        )

        assert await repo.delete(r.id.int) is True
        count = await db_session.execute(select(func.count()).select_from(KnowledgeRelationORM))
        assert count.scalar_one() == 0
        assert await repo.get(r.id.int) is None
        assert await repo.delete(r.id.int) is False

    async def test_table_has_no_is_deleted_column(self, db_session, project):
        """M1 验收: knowledge_relations 表存在且无 is_deleted 列（真删语义，§2.1 规则 7）."""
        result = await db_session.execute(text("PRAGMA table_info(knowledge_relations)"))
        cols = {row[1] for row in result.fetchall()}
        assert "is_deleted" not in cols
        assert {
            "id",
            "project_id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            "description",
            "source",
            "created_at",
            "updated_at",
        } <= cols

    # ── 唯一约束 ──

    async def test_duplicate_six_tuple_raises_integrity_error(self, db_session, project):
        """同六元组 (project_id, source_type, source_id, target_type, target_id, relation_type)
        重复 add → IntegrityError（uq_knowledge_relations_key 兜底）."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        src = uuid.UUID(int=132)
        tgt = uuid.UUID(int=133)
        await repo.add(_rel(project, source_id=src, target_id=tgt, relation_type="属于"))

        with pytest.raises(IntegrityError):
            await repo.add(_rel(project, source_id=src, target_id=tgt, relation_type="属于"))
        await db_session.rollback()

    # ── list_by_project（§5.2 图谱聚合数据源）──

    async def test_list_by_project_returns_all_rows_project_scoped(self, db_session, project):
        """list_by_project 返回项目内全量（无分页）；跨项目行不混入."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        r1 = await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=134),
                target_id=uuid.UUID(int=135),
                relation_type="属于",
            )
        )
        r2 = await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=136),
                target_id=uuid.UUID(int=137),
                relation_type="参与",
            )
        )

        other = ProjectORM(name="其他项目")
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        await repo.add(
            _rel(
                other,
                source_id=uuid.UUID(int=138),
                target_id=uuid.UUID(int=139),
                relation_type="属于",
            )
        )

        rows = await repo.list_by_project(project.id)
        assert {r.id for r in rows} == {r1.id, r2.id}

    # ── delete_by_entity / cleanup_for_entity（§5.3 实体硬删级联清理）──

    async def test_delete_by_entity_source_and_target(self, db_session, project):
        """delete_by_entity: 实体作为 source 或 target 的行均被删除；无关行保留；返回删除行数."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        ent = uuid.UUID(int=140)
        other_ent = uuid.UUID(int=141)
        await repo.add(
            _rel(project, source_id=ent, target_id=uuid.UUID(int=142), relation_type="属于")
        )
        await repo.add(
            _rel(project, source_id=uuid.UUID(int=143), target_id=ent, relation_type="参与")
        )
        keep = await repo.add(
            _rel(project, source_id=other_ent, target_id=uuid.UUID(int=144), relation_type="位于")
        )

        deleted = await repo.delete_by_entity("character", ent.int)
        assert deleted == 2
        rows, total = await repo.list(project.id)
        assert total == 1
        assert rows[0].id == keep.id

    async def test_cleanup_for_entity_is_alias_of_delete_by_entity(self, db_session, project):
        """cleanup_for_entity 与 delete_by_entity 行为一致（§5.3 回调端口别名）."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        ent = uuid.UUID(int=145)
        await repo.add(
            _rel(project, source_id=ent, target_id=uuid.UUID(int=146), relation_type="属于")
        )

        deleted = await repo.cleanup_for_entity("world", ent.int)
        assert deleted == 1
        _, total = await repo.list(project.id)
        assert total == 0

    # ── 项目硬删 → FK 级联（§2.5）──

    async def test_project_hard_delete_cascades_relations(self, db_session, project):
        """项目硬删 → knowledge_relations 行物理级联删除（project_id FK CASCADE）."""
        repo = SQLiteKnowledgeRelationRepository(db_session)
        await repo.add(
            _rel(
                project,
                source_id=uuid.UUID(int=147),
                target_id=uuid.UUID(int=148),
                relation_type="属于",
            )
        )

        p_row = await db_session.execute(select(ProjectORM).where(ProjectORM.id == project.id))
        await db_session.delete(p_row.scalar_one())
        await db_session.commit()

        count = await db_session.execute(select(func.count()).select_from(KnowledgeRelationORM))
        assert count.scalar_one() == 0
