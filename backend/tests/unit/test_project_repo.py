"""SQLiteProjectRepository 集成测试 — in-memory SQLite（Issue #104 Phase 3 覆盖率补齐）.

覆盖 project_repo.py 未达行:
- _get_config_dict 兜底分支（config 既非 ProjectConfig 也非 dict → {}）
- update 不存在的项目 → ValueError（回查无行）
- hard_delete 不存在的项目 → False
- add/get 基础往返（真实 DB 落库 + 断言）

fixture 模式镜像 test_character_repo.py（in-memory SQLite + FK pragma）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
    _get_config_dict,
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


def _now() -> datetime:
    """当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _project(name: str, **kw) -> Project:
    """构造待持久化的项目领域对象（id 为随机 UUID，落库后由 DB 自增分配）."""
    return Project(
        id=uuid.uuid4(),
        name=name,
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


class TestProjectRepositoryCoverageGaps:
    """SQLiteProjectRepository 缺口覆盖（Issue #104 Phase 3）."""

    # ── 基础往返 ──

    async def test_add_and_get_roundtrip(self, db_session):
        """add 落库并返回领域对象；get 按 int 主键读回，字段映射正确."""
        repo = SQLiteProjectRepository(db_session)
        saved = await repo.add(
            _project("测试项目", tags=["玄幻"], target_words=100000, language="zh-CN")
        )

        assert isinstance(saved.id, uuid.UUID)
        assert saved.name == "测试项目"
        assert saved.tags == ["玄幻"]
        assert saved.target_words == 100000
        assert saved.is_deleted is False

        got = await repo.get(saved.id.int)
        assert got is not None
        assert got.id == saved.id
        assert got.tags == ["玄幻"]
        assert got.config.model is None  # #520: ProjectConfig 默认 model=None

    # ── _get_config_dict 兜底 ──

    def test_get_config_dict_fallback_empty(self):
        """config 既非 ProjectConfig 也非 dict（None/任意对象）→ {} 兜底."""
        assert _get_config_dict(None) == {}
        assert _get_config_dict("raw-string") == {}
        # 正常路径不受影响
        assert _get_config_dict(ProjectConfig(model="deepseek"))["model"] == "deepseek"
        assert _get_config_dict({"model": "gpt-4o"}) == {"model": "gpt-4o"}

    # ── update 不存在 → ValueError ──

    async def test_update_missing_raises_value_error(self, db_session):
        """update 不存在的项目 → 回查无行 → ValueError（project_repo 不检查 rowcount）."""
        repo = SQLiteProjectRepository(db_session)
        ghost = _project("幽灵项目")
        ghost.id = uuid.UUID(int=99999)  # 仓储层 int id：不存在但落在 SQLite 64 位范围内
        with pytest.raises(ValueError, match="Project with id 99999 not found after update"):
            await repo.update(ghost)

    # ── hard_delete 不存在 → False ──

    async def test_hard_delete_missing_returns_false(self, db_session):
        """hard_delete 不存在的项目 → False."""
        repo = SQLiteProjectRepository(db_session)
        assert await repo.hard_delete(99999) is False

    async def test_soft_delete_and_restore_missing(self, db_session):
        """soft_delete 不存在 → False；restore 不存在 → None（重复操作无毒）."""
        repo = SQLiteProjectRepository(db_session)
        assert await repo.soft_delete(99999) is False
        assert await repo.restore(99999) is None

    # ── 其余行补齐（原由 api/integration 测试覆盖，本 worktree 只有 unit） ──

    async def test_get_missing_returns_none(self, db_session):
        """get 对不存在的 id 返回 None."""
        repo = SQLiteProjectRepository(db_session)
        assert await repo.get(99999) is None

    async def test_list_all_search_sort_pagination(self, db_session):
        """list_all 搜索（icontains）/排序/分页/total；软删项目不出现."""
        repo = SQLiteProjectRepository(db_session)
        p1 = await repo.add(_project("alpha 项目"))
        p2 = await repo.add(_project("bravo 项目"))
        p3 = await repo.add(_project("charlie 项目"))
        await repo.soft_delete(p3.id.int)

        # 搜索
        found, total = await repo.list_all(search="项目")
        assert total == 2
        assert {p.id for p in found} == {p1.id, p2.id}
        assert await repo.list_all(search="不存在") == ([], 0)

        # name 升序
        asc, _ = await repo.list_all(sort_by="name", sort_desc=False)
        assert [p.name for p in asc] == ["alpha 项目", "bravo 项目"]

        # name 降序 + 分页
        desc, _ = await repo.list_all(sort_by="name", sort_desc=True, offset=0, limit=1)
        assert [p.name for p in desc] == ["bravo 项目"]
        page2, _ = await repo.list_all(sort_by="name", sort_desc=True, offset=1, limit=1)
        assert [p.name for p in page2] == ["alpha 项目"]

    async def test_update_roundtrip(self, db_session):
        """update 成功路径：字段落库并读回最新领域对象."""
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(_project("旧名"))

        updated = await repo.update(
            created.model_copy(update={"name": "新名", "tags": ["科幻"]})
        )
        assert updated.id == created.id
        assert updated.name == "新名"
        assert updated.tags == ["科幻"]
        assert updated.updated_at >= created.updated_at

        got = await repo.get(created.id.int)
        assert got is not None and got.name == "新名"

    async def test_soft_delete_and_restore_roundtrip(self, db_session):
        """soft_delete 后 get 不可见；restore 恢复并返回领域对象."""
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(_project("待删项目"))

        assert await repo.soft_delete(created.id.int) is True
        assert await repo.get(created.id.int) is None

        restored = await repo.restore(created.id.int)
        assert restored is not None
        assert restored.id == created.id
        assert restored.is_deleted is False
        assert await repo.get(created.id.int) is not None

    async def test_hard_delete_roundtrip(self, db_session):
        """hard_delete 成功路径：行物理消失，重复删除返回 False."""
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(_project("待硬删项目"))

        assert await repo.hard_delete(created.id.int) is True
        assert await repo.get(created.id.int) is None
        assert await repo.hard_delete(created.id.int) is False

    # ── #225 agent_* 三态持久化（确认型守护：repo 层行为不变，锁定落库/读回契约） ──

    async def test_update_config_agent_null_persists(self, db_session):
        """#225 M1：config.agent_writer=null（关闭）→ 真实 DB 落库 → 读回仍为 None。

        确认型：repo 层当前实现已满足（config.model_dump() 全字段落库），本用例守护
        「显式 null 落库 + 重新构造读回」链路——GREEN 若把 null 视作缺失/移除键，
        此用例转 RED。
        """
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(
            _project(
                "开关持久化项目",
                config=ProjectConfig(model="gpt-4o", agent_writer="deepseek/deepseek-chat"),
            )
        )

        updated = await repo.update(
            created.model_copy(update={"config": ProjectConfig(model="gpt-4o", agent_writer=None)})
        )
        assert updated.config.agent_writer is None

        # 「重启读回」单元级锚点：get 重新构造领域对象，null 必须保留（非默认回填）
        got = await repo.get(created.id.int)
        assert got is not None
        assert got.config.agent_writer is None
        assert got.config.model == "gpt-4o"

    async def test_config_sentinel_roundtrip(self, db_session):
        """#225 M3：sentinel "__default__"（跟随默认）→ 真实 DB 落库 → 读回保留。

        确认型守护：repo 层对字符串值透明，锁定 sentinel 持久化不丢失。
        """
        repo = SQLiteProjectRepository(db_session)
        created = await repo.add(
            _project("sentinel 项目", config=ProjectConfig(agent_writer="__default__"))
        )

        got = await repo.get(created.id.int)
        assert got is not None
        assert got.config.agent_writer == "__default__"
