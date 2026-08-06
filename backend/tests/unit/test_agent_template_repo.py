"""#107 SQLiteAgentTemplateRepository 集成测试 — in-memory SQLite（RED 批）。

覆盖 AgentTemplateRepositoryProtocol 全部方法（spec §9.2①「模板 CRUD +
设为默认」+ §9.3 used_by 引用查询）:
- add/get/get_by_name/list 往返（含 roles JSON 列存取 roundtrip）
- update（全量按 id 更新，updated_at 刷新；不存在 → ValueError）
- delete（不存在 → False）
- name unique：重复插入同名 → IntegrityError（回滚后可继续）
- is_default 单例：update 置 True 时其他行自动降级 False
- set_default 便捷方法（单例语义同上；不存在 → None）
- list_projects_by_template：projects 表 config JSON 含 template_id 匹配

依据: specs/f19-gui/spec.md §9.2①（ORM/repo 模块）+ §9.5 测试策略「后端单元」。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

1. ORM: ``inkflow.infrastructure.database.models.agent_template.AgentTemplateORM``
   （本批新建，当前不存在 → 收集期 ModuleNotFoundError 即预期 RED 形态）:
   - ``__tablename__ = "agent_templates"``
   - ``id: Mapped[int]`` Integer PK autoincrement
   - ``name: Mapped[str]`` String(100) nullable=False unique=True
   - ``description: Mapped[str]`` Text/String nullable=False default=""
   - ``main_model: Mapped[str | None]`` String(200) nullable=True
   - ``default_temperature: Mapped[float | None]`` Float nullable=True
   - ``roles: Mapped[dict]`` JSON nullable=False default=dict
     （存 ``{key: RoleTemplate.model_dump()}``，读回
     ``{key: RoleTemplate.model_validate(v)}``）
   - ``default_words: Mapped[int | None]`` Integer nullable=True
   - ``is_default: Mapped[bool]`` Boolean nullable=False default=False
   - ``created_at / updated_at: Mapped[datetime]`` DateTime(timezone=True)
     nullable=False default=_utcnow（updated_at 另加 onupdate=_utcnow）
   - 转换函数（_orm_to_domain / _domain_to_orm）放在 repo 层（项目惯例）

2. Repo: ``inkflow.infrastructure.database.repositories.agent_template_repo``
   ``SQLiteAgentTemplateRepository(session: AsyncSession)``，方法签名:
   - ``async add(self, at: AgentTemplate) -> AgentTemplate``（id 由 DB 自增；
     name 唯一冲突 → IntegrityError 冒泡，服务层先查重给出 422）
   - ``async get(self, template_id: int) -> AgentTemplate | None``
   - ``async get_by_name(self, name: str) -> AgentTemplate | None``（精确匹配）
   - ``async list(self) -> builtins.list[AgentTemplate]``（按 name 升序）
   - ``async update(self, at: AgentTemplate) -> AgentTemplate``（全量按 id；
     不存在 → ValueError；updated_at=_utcnow() 刷新；created_at 保留；
     **is_default 单例：at.is_default=True 时先清空其他行 is_default=False**）
   - ``async delete(self, template_id: int) -> bool``（不存在 → False）
   - ``async set_default(self, template_id: int) -> AgentTemplate | None``
     （目标行 is_default=True + 其他行降级 False；不存在 → None）
   - ``async list_projects_by_template(self, template_id: int)
     -> builtins.list[Project]``（返回**领域对象列表**（非 dict），按 name
     升序；匹配 = projects.config JSON 的 ``template_id`` 字段
     **精确等于 str(template_id)**（config 存 str，如 "5"）；排除软删除项目；
     实现方式 SQLite json_extract 或 Python 过滤皆可——契约只定返回值）

3. fixture: tests/unit/conftest.py 无 DB fixture（仅有 event_loop/temp_keys_dir），
   故本文件自带 ``db_session`` fixture（镜像 test_provider_config_repo.py：
   in-memory SQLite + PRAGMA foreign_keys=ON + Base.metadata.create_all）。

4. 时区注意（既有行为，同 F13）: SQLite 读回 DateTime(timezone=True) 为 naive
   datetime，故时间戳断言只用 is not None / >=，不做精确相等。

5. 错误类归属: repo 层不定义业务错误（update 不存在抛内置 ValueError）；
   AgentTemplateNotFoundError/NameConflictError/BuiltinError 属
   domain/ports/agent_template_errors（服务层用）。

6. 内置模板 seed（spec §9.7 Q2=A「默认模板 = 系统内置首行」）不在本批契约：
   GREEN 可用 builtin_key 列标识内置行（镜像 #126 A1），但本批测试不约束
   该字段/seed 方法——本批只锁定「is_default 单例」+「删除 is_default=True
   拒绝（服务层契约，见 test_agent_template_service.py）」。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述签名实现后本文件应全绿。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.agent_template import AgentTemplate, RoleTemplate
from inkflow.domain.models.project import Project
from inkflow.infrastructure.database.models.agent_template import AgentTemplateORM
from inkflow.infrastructure.database.models.project import ProjectORM
from inkflow.infrastructure.database.repositories.agent_template_repo import (
    SQLiteAgentTemplateRepository,
)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（镜像 F13 仓储测试 fixture）."""
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


def _template(name: str, **kw) -> AgentTemplate:
    """构造待持久化的 AgentTemplate 领域对象.

    id/created_at/updated_at 默认 None：id 由 DB 自增分配，时间戳由 ORM
    default 填充（落库读回后为 naive datetime，断言只用 is not None）。
    可通过 kw 覆盖 description/main_model/default_temperature/roles/
    default_words/is_default 等字段.
    """
    return AgentTemplate(name=name, **kw)


def _add_project(
    db_session: AsyncSession, name: str, config: dict, is_deleted: bool = False
) -> ProjectORM:
    """直接插入 ProjectORM 行（绕过领域层，模拟既有项目 config JSON）。"""
    orm = ProjectORM(
        name=name,
        config=config,
        is_deleted=is_deleted,
    )
    db_session.add(orm)
    return orm


@pytest.mark.integration
class TestAgentTemplateRepository:
    """SQLiteAgentTemplateRepository 集成测试."""

    # ── CRUD 往返 ──

    async def test_add_and_get_roundtrip(self, db_session):
        """add 落库并返回领域对象（id 分配、默认字段）；get 按 int 主键读回."""
        repo = SQLiteAgentTemplateRepository(db_session)
        saved = await repo.add(_template("我的模板", description="desc"))

        assert isinstance(saved.id, int)
        assert saved.id > 0
        assert saved.name == "我的模板"
        assert saved.description == "desc"
        assert saved.main_model is None
        assert saved.default_temperature is None
        assert saved.roles == {}
        assert saved.default_words is None
        assert saved.is_default is False
        assert saved.created_at is not None
        assert saved.updated_at is not None

        # 持久化验证：直接查表
        row = await db_session.execute(
            select(AgentTemplateORM).where(AgentTemplateORM.id == saved.id)
        )
        assert row.scalar_one().name == "我的模板"

        got = await repo.get(saved.id)
        assert got is not None
        assert got.id == saved.id
        assert got.name == "我的模板"
        assert got.created_at == saved.created_at

    async def test_get_returns_none_for_missing(self, db_session):
        """get 对不存在的 id 返回 None."""
        repo = SQLiteAgentTemplateRepository(db_session)
        assert await repo.get(99999) is None

    async def test_get_by_name_hit_and_miss(self, db_session):
        """get_by_name 精确匹配命中；未命中返回 None."""
        repo = SQLiteAgentTemplateRepository(db_session)
        saved = await repo.add(_template("玄幻模板"))
        hit = await repo.get_by_name("玄幻模板")
        assert hit is not None
        assert hit.id == saved.id
        assert await repo.get_by_name("玄幻模板 ") is None  # 不做去空白
        assert await repo.get_by_name("ghost") is None

    async def test_name_unique_conflict(self, db_session):
        """name 唯一：插入第二个同名 → IntegrityError，回滚后可继续."""
        repo = SQLiteAgentTemplateRepository(db_session)
        await repo.add(_template("模板A"))
        with pytest.raises(IntegrityError):
            await repo.add(_template("模板A"))
        await db_session.rollback()  # 事务回滚，恢复可用

        items = await repo.list()
        assert len(items) == 1
        assert items[0].name == "模板A"

    # ── list ──

    async def test_list_sorted_by_name(self, db_session):
        """list 按 name 升序。"""
        repo = SQLiteAgentTemplateRepository(db_session)
        await repo.add(_template("z模板"))
        await repo.add(_template("a模板"))
        await repo.add(_template("m模板"))

        items = await repo.list()
        assert [t.name for t in items] == ["a模板", "m模板", "z模板"]

    # ── roles JSON 存取 ──

    async def test_roles_json_roundtrip(self, db_session):
        """roles 经 JSON 列落库读回：领域对象相等 + DB 行为 dict 嵌套。"""
        repo = SQLiteAgentTemplateRepository(db_session)
        roles = {
            "architect": RoleTemplate(model="openai/gpt-4o", temperature=0.7),
            "writer": RoleTemplate(model="deepseek/deepseek-chat", enabled=False),
            "auditor": RoleTemplate(),
        }
        saved = await repo.add(
            _template(
                "t",
                main_model="openai/gpt-4o",
                default_temperature=0.8,
                roles=roles,
                default_words=50000,
            )
        )

        got = await repo.get(saved.id)
        assert got is not None
        assert got.roles == roles
        assert got.roles["writer"].enabled is False
        assert got.roles["auditor"] == RoleTemplate()
        assert got.main_model == "openai/gpt-4o"
        assert got.default_temperature == 0.8
        assert got.default_words == 50000

        # DB 行存 dict 嵌套（RoleTemplate.model_dump() 产物）
        row = await db_session.execute(
            select(AgentTemplateORM).where(AgentTemplateORM.id == saved.id)
        )
        assert row.scalar_one().roles == {
            "architect": {"model": "openai/gpt-4o", "temperature": 0.7, "enabled": True},
            "writer": {"model": "deepseek/deepseek-chat", "temperature": None, "enabled": False},
            "auditor": {"model": None, "temperature": None, "enabled": True},
        }

    async def test_roles_empty_by_default(self, db_session):
        """未传 roles 落库为 {}（非 NULL）."""
        repo = SQLiteAgentTemplateRepository(db_session)
        saved = await repo.add(_template("t"))
        row = await db_session.execute(
            select(AgentTemplateORM).where(AgentTemplateORM.id == saved.id)
        )
        assert row.scalar_one().roles == {}

    # ── update ──

    async def test_update_fields_and_preserves_created_at(self, db_session):
        """update 按 id 全量更新字段并返回最新领域对象；created_at 保留、
        updated_at 刷新。"""
        repo = SQLiteAgentTemplateRepository(db_session)
        saved = await repo.add(_template("旧名", description="old", main_model="m/old"))
        updated = await repo.update(
            saved.model_copy(
                update={
                    "name": "新名",
                    "description": "new",
                    "main_model": "m/new",
                    "default_temperature": 1.1,
                    "roles": {"writer": RoleTemplate(model="m/w")},
                    "default_words": 30000,
                }
            )
        )
        assert updated.id == saved.id
        assert updated.name == "新名"
        assert updated.description == "new"
        assert updated.main_model == "m/new"
        assert updated.default_temperature == 1.1
        assert updated.roles == {"writer": RoleTemplate(model="m/w")}
        assert updated.default_words == 30000
        assert updated.created_at == saved.created_at
        assert updated.updated_at >= saved.updated_at

        # 持久化验证
        got = await repo.get(saved.id)
        assert got is not None
        assert got.name == "新名"
        assert got.main_model == "m/new"

    async def test_update_missing_raises_value_error(self, db_session):
        """update 不存在的 id → ValueError（镜像 F13 仓储惯例）."""
        repo = SQLiteAgentTemplateRepository(db_session)
        with pytest.raises(ValueError):
            await repo.update(AgentTemplate(id=99999, name="ghost"))
        await db_session.rollback()

    # ── delete ──

    async def test_delete_existing_and_missing(self, db_session):
        """delete 命中返回 True 且 get 不可见；不存在返回 False."""
        repo = SQLiteAgentTemplateRepository(db_session)
        saved = await repo.add(_template("临时模板"))

        assert await repo.delete(saved.id) is True
        assert await repo.get(saved.id) is None
        assert await repo.delete(saved.id) is False
        assert await repo.delete(99999) is False

    # ── is_default 单例 ──

    async def test_update_is_default_singleton(self, db_session):
        """update 置 is_default=True 时其他行自动降级 False；置 False 后无默认。"""
        repo = SQLiteAgentTemplateRepository(db_session)
        a = await repo.add(_template("模板A"))
        b = await repo.add(_template("模板B"))

        updated_b = await repo.update(b.model_copy(update={"is_default": True}))
        assert updated_b.is_default is True

        # 单例：A 被降级
        a_after = await repo.get(a.id)
        assert a_after is not None
        assert a_after.is_default is False
        b_after = await repo.get(b.id)
        assert b_after is not None
        assert b_after.is_default is True

        # 取消默认：B 置 False → 无默认行
        await repo.update(updated_b.model_copy(update={"is_default": False}))
        assert (await repo.get(b.id)).is_default is False  # type: ignore[union-attr]
        assert (await repo.get(a.id)).is_default is False  # type: ignore[union-attr]

    async def test_set_default_sets_singleton(self, db_session):
        """set_default(id)：目标行 is_default=True，其他行降级 False；
        不存在 → None。"""
        repo = SQLiteAgentTemplateRepository(db_session)
        a = await repo.add(_template("模板A"))
        b = await repo.add(_template("模板B"))

        # 先设 A 默认，再切到 B → A 降级
        await repo.set_default(a.id)
        assert (await repo.get(a.id)).is_default is True  # type: ignore[union-attr]

        got_b = await repo.set_default(b.id)
        assert got_b is not None
        assert got_b.id == b.id
        assert got_b.is_default is True
        assert (await repo.get(a.id)).is_default is False  # type: ignore[union-attr]

        assert await repo.set_default(99999) is None


@pytest.mark.integration
class TestListProjectsByTemplate:
    """list_projects_by_template — projects 表 config JSON 引用计数查询."""

    async def test_matches_projects_by_config_template_id(self, db_session):
        """config JSON 含 template_id 的项目命中；返回领域 Project（name 升序）。"""
        repo = SQLiteAgentTemplateRepository(db_session)
        p1 = _add_project(db_session, "A项目", {"template_id": "5", "temperature": 0.9})
        p2 = _add_project(db_session, "B项目", {"template_id": "5"})
        _add_project(db_session, "未引用", {})
        await db_session.commit()
        for orm in (p1, p2):
            await db_session.refresh(orm)

        refs = await repo.list_projects_by_template(5)

        # name 升序（ASCII 前缀，SQLite BINARY 排序）
        assert [p.name for p in refs] == ["A项目", "B项目"]
        assert all(isinstance(p, Project) for p in refs)
        assert all(p.config.template_id == "5" for p in refs)
        # id 为领域 UUID（int→UUID 可逆转换，同 project_repo._orm_to_domain）
        assert all(isinstance(p.id, uuid.UUID) for p in refs)

    async def test_exact_match_not_substring(self, db_session):
        """匹配为精确相等：config.template_id="55" 不命中 5；"5" 不命中 55。"""
        repo = SQLiteAgentTemplateRepository(db_session)
        _add_project(db_session, "五五", {"template_id": "55"})
        _add_project(db_session, "五", {"template_id": "5"})
        await db_session.commit()

        assert [p.name for p in await repo.list_projects_by_template(5)] == ["五"]
        assert [p.name for p in await repo.list_projects_by_template(55)] == ["五五"]

    async def test_excludes_soft_deleted_and_missing_template_id(self, db_session):
        """软删除项目不命中；config 无 template_id / template_id=None 不命中。"""
        repo = SQLiteAgentTemplateRepository(db_session)
        _add_project(db_session, "已删除", {"template_id": "5"}, is_deleted=True)
        _add_project(db_session, "无字段", {})
        _add_project(db_session, "空值", {"template_id": None})
        await db_session.commit()

        assert await repo.list_projects_by_template(5) == []

    async def test_no_matches_returns_empty(self, db_session):
        """无任何引用 → 空列表。"""
        repo = SQLiteAgentTemplateRepository(db_session)
        _add_project(db_session, "普通项目", {})
        await db_session.commit()
        assert await repo.list_projects_by_template(999) == []
