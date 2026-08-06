"""#106 SQLiteProviderConfigRepository 集成测试 — in-memory SQLite（RED 批，P1 实体）。

覆盖 ProviderConfigRepositoryProtocol 全部方法（spec §8.5「ProviderConfig
CRUD + 内置 seed」）:
- add/get/get_by_name/list 往返（含 models JSON 列存取 roundtrip）
- update（全量按 id 更新，updated_at 刷新；不存在 → ValueError）
- delete（不存在 → False）
- name unique：重复插入同名 → IntegrityError（回滚后可继续）
- seed_builtin_providers 幂等插入内置 4 provider（openai/deepseek/zhipu/ollama）

依据: specs/f19-gui/spec.md §8.2①（ORM/repo 模块）+ §8.5 测试策略「后端单元」。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

1. ORM: ``inkflow.infrastructure.database.models.provider_config.ProviderConfigORM``
   （本批新建，当前不存在 → 收集期 ModuleNotFoundError 即预期 RED 形态）:
   - ``__tablename__ = "provider_configs"``
   - ``id: Mapped[int]`` Integer PK autoincrement
   - ``name: Mapped[str]`` String(100) nullable=False unique=True（§8.2① name 唯一）
   - ``base_url: Mapped[str | None]`` String(500) nullable=True
   - ``default_model: Mapped[str | None]`` String(200) nullable=True
   - ``models: Mapped[list]`` JSON nullable=False default=list（仿 ProjectORM.config）
   - ``max_retries: Mapped[int]`` Integer nullable=False default=3
   - ``timeout: Mapped[int]`` Integer nullable=False default=120
   - ``created_at / updated_at: Mapped[datetime]`` DateTime(timezone=True)
     nullable=False default=_utcnow（updated_at 另加 onupdate=_utcnow）
   - 转换函数（_orm_to_domain / _domain_to_orm）放在 repo 层（项目惯例）:
     models 列存 ``[ProviderModel.model_dump()]``（dict 列表）；
     读回 ``[ProviderModel.model_validate(m) for m in (orm.models or [])]``

2. Repo: ``inkflow.infrastructure.database.repositories.provider_config_repo``
   ``SQLiteProviderConfigRepository(session: AsyncSession)``，方法签名:
   - ``async add(self, pc: ProviderConfig) -> ProviderConfig``（id 由 DB 自增；
     name 唯一冲突 → IntegrityError 冒泡，服务层先查重给出 422）
   - ``async get(self, provider_config_id: int) -> ProviderConfig | None``
   - ``async get_by_name(self, name: str) -> ProviderConfig | None``（精确匹配）
   - ``async list(self, search: str | None = None) -> builtins.list[ProviderConfig]``
     （按 name 升序；search 对 name icontains 子串过滤）
   - ``async update(self, pc: ProviderConfig) -> ProviderConfig``（全量按 id；
     不存在 → ValueError；updated_at=_utcnow() 刷新；created_at 保留）
   - ``async delete(self, provider_config_id: int) -> bool``（不存在 → False）
   - ``async seed_builtin_providers(self) -> int``（幂等：已存在同名跳过；
     返回本次实际插入条数；seed 值 = openai/deepseek/zhipu/ollama 四 provider，
     base_url 复用 infrastructure.llm.provider_config 的 _PROVIDER_BASE_URLS
     语义（deepseek=https://api.deepseek.com/v1），或等价本地常量）

3. fixture: tests/unit/conftest.py 无 DB fixture（仅有 event_loop/temp_keys_dir），
   故本文件自带 ``db_session`` fixture（镜像 test_foreshadowing_repo.py：
   in-memory SQLite + PRAGMA foreign_keys=ON + Base.metadata.create_all）。

4. 时区注意（既有行为，同 F13）: SQLite 读回 DateTime(timezone=True) 为 naive
   datetime，故时间戳断言只用 is not None / >=，不做精确相等。

5. 错误类归属: repo 层不定义业务错误（update 不存在抛内置 ValueError）；
   ProviderConfigNotFoundError/NameConflictError 属 domain/ports（服务层用）。

══════════════ #126 A1 builtin_key 契约（2026-08-06，方案已拍板）══════════════

1. builtin_key 字段语义: ``ProviderConfig.builtin_key: str | None`` —
   内置行稳定标识（openai/deepseek/zhipu/ollama，seed 插入时设置）；
   用户行 = None。ORM 列 ``builtin_key VARCHAR(50) NULL``。
   update 改名（name 变更）时 builtin_key 保持不变。

2. seed 判重契约: 从 ``get_by_name(name)`` 改为 ``get_by_builtin_key(key)``:
   - 存在同 key 行 → 跳过（改名后重启不复活：openai→myai 后重启 seed
     不得重新插入 openai 行）
   - 按 key 未命中但按 name 命中内置名（旧库回填场景）→ 回填
     builtin_key = key（更新非插入，不计入返回插入数）

3. Protocol 新增 ``get_by_builtin_key(builtin_key: str) -> ProviderConfig | None``
   （按内置 key 精确查询；用户行 builtin_key=None 不命中）。

4. 转换函数契约: ``_orm_to_domain`` / ``_domain_to_orm`` 携带 builtin_key。

5. RED 预期失败形态（实现未写，以实测为准）:
   - ``get_by_builtin_key`` 方法不存在 → AttributeError
   - 领域模型/ORM 缺 builtin_key 字段 → ``ProviderConfig(builtin_key=...)``
     构造 TypeError / 访问 ``.builtin_key`` AttributeError
   - seed 仍按名判重 → 场景 A 断言失败（改名后再次 seed 返回 1、列表 5 行）
   - 场景 B（回填）断言 ``openai.builtin_key == "openai"`` → AttributeError

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述签名实现后本文件应全绿。
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.provider_config import ProviderConfig, ProviderModel
from inkflow.infrastructure.database.models.provider_config import ProviderConfigORM
from inkflow.infrastructure.database.repositories.provider_config_repo import (
    SQLiteProviderConfigRepository,
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


def _config(name: str, **kw) -> ProviderConfig:
    """构造待持久化的 ProviderConfig 领域对象.

    id/created_at/updated_at 默认 None：id 由 DB 自增分配，时间戳由 ORM
    default 填充（落库读回后为 naive datetime，断言只用 is not None）。
    可通过 kw 覆盖 base_url/default_model/models/max_retries/timeout 等字段.
    """
    return ProviderConfig(name=name, **kw)


@pytest.mark.integration
class TestProviderConfigRepository:
    """SQLiteProviderConfigRepository 集成测试."""

    # ── CRUD 往返 ──

    async def test_add_and_get_roundtrip(self, db_session):
        """add 落库并返回领域对象（id 分配、默认字段）；get 按 int 主键读回."""
        repo = SQLiteProviderConfigRepository(db_session)
        saved = await repo.add(_config("openai", base_url="https://api.openai.com/v1"))

        assert isinstance(saved.id, int)
        assert saved.id > 0
        assert saved.name == "openai"
        assert saved.base_url == "https://api.openai.com/v1"
        assert saved.default_model is None
        assert saved.models == []
        assert saved.max_retries == 3
        assert saved.timeout == 120
        assert saved.created_at is not None
        assert saved.updated_at is not None

        # 持久化验证：直接查表
        row = await db_session.execute(
            select(ProviderConfigORM).where(ProviderConfigORM.id == saved.id)
        )
        assert row.scalar_one().name == "openai"

        got = await repo.get(saved.id)
        assert got is not None
        assert got.id == saved.id
        assert got.name == "openai"
        assert got.created_at == saved.created_at

    async def test_get_returns_none_for_missing(self, db_session):
        """get 对不存在的 id 返回 None."""
        repo = SQLiteProviderConfigRepository(db_session)
        assert await repo.get(99999) is None

    async def test_get_by_name_hit_and_miss(self, db_session):
        """get_by_name 精确匹配命中；未命中返回 None."""
        repo = SQLiteProviderConfigRepository(db_session)
        saved = await repo.add(_config("deepseek"))
        hit = await repo.get_by_name("deepseek")
        assert hit is not None
        assert hit.id == saved.id
        assert await repo.get_by_name("DeepSeek") is None  # 大小写敏感
        assert await repo.get_by_name("ghost") is None

    async def test_name_unique_conflict(self, db_session):
        """name 唯一：插入第二个同名 → IntegrityError，回滚后可继续."""
        repo = SQLiteProviderConfigRepository(db_session)
        await repo.add(_config("openai"))
        with pytest.raises(IntegrityError):
            await repo.add(_config("openai"))
        await db_session.rollback()  # 事务回滚，恢复可用

        items = await repo.list()
        assert len(items) == 1
        assert items[0].name == "openai"

    # ── list（含 seed 过滤）──

    async def test_list_sorted_by_name_and_search_filter(self, db_session):
        """list 按 name 升序；search 对 name icontains 子串过滤."""
        repo = SQLiteProviderConfigRepository(db_session)
        await repo.add(_config("zhipu"))
        await repo.add(_config("openai"))
        await repo.add(_config("deepseek"))

        items = await repo.list()
        assert [p.name for p in items] == ["deepseek", "openai", "zhipu"]

        (filtered,) = await repo.list(search="deep")
        assert filtered.name == "deepseek"
        assert await repo.list(search="不存在") == []

    async def test_list_includes_seed_after_seed(self, db_session):
        """seed 过滤：seed_builtin_providers 幂等插入内置 4 provider 后，
        list 正常返回全部（seed 与自定义同列表，无 is_builtin 列——内置性由
        name ∈ {openai, deepseek, zhipu, ollama} 判定，服务层负责）；search
        可过滤 seed 子集。"""
        repo = SQLiteProviderConfigRepository(db_session)
        n = await repo.seed_builtin_providers()
        assert n == 4

        items = await repo.list()
        assert {p.name for p in items} == {"openai", "deepseek", "zhipu", "ollama"}

        deepseek = await repo.get_by_name("deepseek")
        assert deepseek is not None
        assert deepseek.base_url == "https://api.deepseek.com/v1"
        assert deepseek.models == []

        # 幂等：重复 seed 不重复插入
        n2 = await repo.seed_builtin_providers()
        assert n2 == 0
        assert len(await repo.list()) == 4

        # seed 可被 search 过滤
        hits = await repo.list(search="oll")
        assert [p.name for p in hits] == ["ollama"]

        # seed 后自定义 provider 可正常加入
        custom = await repo.add(_config("my-custom"))
        assert custom.id > 0
        assert len(await repo.list()) == 5

    # ── models JSON 存取 ──

    async def test_models_json_roundtrip(self, db_session):
        """models 列表经 JSON 列落库读回：领域对象相等 + DB 行为 dict 列表."""
        repo = SQLiteProviderConfigRepository(db_session)
        models = [
            ProviderModel(id="gpt-4o", type="chat", roles=["writing", "audit"]),
            ProviderModel(id="text-embedding-3-small", type="embedding"),
        ]
        saved = await repo.add(
            _config(
                "openai",
                base_url="https://api.openai.com/v1",
                default_model="gpt-4o",
                models=models,
                max_retries=5,
                timeout=60,
            )
        )

        got = await repo.get(saved.id)
        assert got is not None
        assert got.models == models
        assert got.models[0].roles == ["writing", "audit"]
        assert got.max_retries == 5
        assert got.timeout == 60

        # DB 行存 dict 列表（ProviderModel.model_dump() 产物）
        row = await db_session.execute(
            select(ProviderConfigORM).where(ProviderConfigORM.id == saved.id)
        )
        assert row.scalar_one().models == [
            {"id": "gpt-4o", "type": "chat", "roles": ["writing", "audit"]},
            {"id": "text-embedding-3-small", "type": "embedding", "roles": []},
        ]

    async def test_models_empty_by_default(self, db_session):
        """未传 models 落库为 []（非 NULL）."""
        repo = SQLiteProviderConfigRepository(db_session)
        saved = await repo.add(_config("openai"))
        row = await db_session.execute(
            select(ProviderConfigORM).where(ProviderConfigORM.id == saved.id)
        )
        assert row.scalar_one().models == []

    # ── update ──

    async def test_update_fields_and_preserves_created_at(self, db_session):
        """update 按 id 全量更新字段并返回最新领域对象；created_at 保留、
        updated_at 刷新。"""
        repo = SQLiteProviderConfigRepository(db_session)
        saved = await repo.add(
            _config("openai", base_url="https://old.example/v1", default_model="old")
        )
        updated = await repo.update(
            saved.model_copy(
                update={
                    "base_url": "https://new.example/v1",
                    "default_model": "new-model",
                    "models": [ProviderModel(id="gpt-4o", type="chat")],
                    "max_retries": 7,
                    "timeout": 30,
                }
            )
        )
        assert updated.id == saved.id
        assert updated.name == "openai"
        assert updated.base_url == "https://new.example/v1"
        assert updated.default_model == "new-model"
        assert updated.models == [ProviderModel(id="gpt-4o", type="chat")]
        assert updated.max_retries == 7
        assert updated.timeout == 30
        assert updated.created_at == saved.created_at
        assert updated.updated_at >= saved.updated_at

        # 持久化验证
        got = await repo.get(saved.id)
        assert got is not None
        assert got.base_url == "https://new.example/v1"

    async def test_update_missing_raises_value_error(self, db_session):
        """update 不存在的 id → ValueError（镜像 F13 仓储惯例）."""
        repo = SQLiteProviderConfigRepository(db_session)
        with pytest.raises(ValueError):
            await repo.update(ProviderConfig(id=99999, name="ghost"))
        await db_session.rollback()

    # ── delete ──

    async def test_delete_existing_and_missing(self, db_session):
        """delete 命中返回 True 且 get 不可见；不存在返回 False."""
        repo = SQLiteProviderConfigRepository(db_session)
        saved = await repo.add(_config("temp-provider"))

        assert await repo.delete(saved.id) is True
        assert await repo.get(saved.id) is None
        assert await repo.delete(saved.id) is False
        assert await repo.delete(99999) is False


# ═══════════════════ #126 A1 builtin_key 契约（2026-08-06）═══════════════════


@pytest.mark.integration
class TestBuiltinKeyContract:
    """#126 A1 builtin_key — get_by_builtin_key / seed 按 key 判重 / 旧库回填.

    RED 预期（实现未写，详见文件头部 docstring）:
    - ``get_by_builtin_key`` 方法不存在 → AttributeError
    - 领域模型/ORM 缺 builtin_key 字段 → 构造 TypeError / 访问 AttributeError
    - seed 仍按名判重 → 场景 A 断言失败（改名后复活：插入数 1、列表 5 行）
    - 场景 B 断言 ``openai.builtin_key == \"openai\"`` → AttributeError
    - 场景 C（幂等保持）为既有行为护栏，RED 阶段即应通过
    """

    async def test_get_by_builtin_key_hit_and_miss(self, db_session):
        """按内置 key 精确查询：seed 后命中；用户行（builtin_key=None）与
        不存在的 key → None."""
        repo = SQLiteProviderConfigRepository(db_session)
        await repo.seed_builtin_providers()
        await repo.add(_config("my-custom"))

        hit = await repo.get_by_builtin_key("openai")
        assert hit is not None
        assert hit.name == "openai"
        assert hit.builtin_key == "openai"
        # 用户行 builtin_key=None → 按 key 不命中
        assert await repo.get_by_builtin_key("my-custom") is None
        assert await repo.get_by_builtin_key("ghost") is None

    async def test_seed_sets_builtin_key_for_all_builtins(self, db_session):
        """seed 插入时设置 builtin_key：全新库 seed 后 4 个内置 key 均命中."""
        repo = SQLiteProviderConfigRepository(db_session)
        assert await repo.seed_builtin_providers() == 4
        for key in ("openai", "deepseek", "zhipu", "ollama"):
            got = await repo.get_by_builtin_key(key)
            assert got is not None, f"seed 后内置 key {key} 应可命中"
            assert got.builtin_key == key

    async def test_seed_after_rename_does_not_resurrect(self, db_session):
        """场景 A（核心 RED）：seed → 改名 openai→myai（repo.update 保持
        builtin_key='openai'）→ 再次 seed → 不复活 openai 行（插入 0、
        列表仍 4 行、myai 行 builtin_key 仍 'openai'）."""
        repo = SQLiteProviderConfigRepository(db_session)
        assert await repo.seed_builtin_providers() == 4

        openai = await repo.get_by_name("openai")
        assert openai is not None
        await repo.update(openai.model_copy(update={"name": "myai"}))

        n = await repo.seed_builtin_providers()
        assert n == 0  # RED: 当前按名判重 → 重新插入 openai → 实际 1

        items = await repo.list()
        assert len(items) == 4  # RED: 实际 5 行（openai 复活）
        assert {p.name for p in items} == {"myai", "deepseek", "zhipu", "ollama"}

        myai = await repo.get_by_name("myai")
        assert myai is not None
        assert myai.builtin_key == "openai"  # RED: 模型缺 builtin_key → AttributeError

    async def test_seed_backfills_builtin_key_on_legacy_row(self, db_session):
        """场景 B（旧库回填）：手工插入 name='openai' 且 builtin_key=NULL 的行
        （模拟迁移前旧库）→ seed → 该行 builtin_key 回填 'openai'（更新非插入）、
        返回插入数不含回填（= 3）、列表无重复."""
        repo = SQLiteProviderConfigRepository(db_session)
        legacy = ProviderConfigORM(name="openai", base_url="https://api.openai.com/v1")
        db_session.add(legacy)
        await db_session.commit()
        await db_session.refresh(legacy)

        n = await repo.seed_builtin_providers()
        assert n == 3  # openai 回填不计数；插入 deepseek/zhipu/ollama

        items = await repo.list()
        assert len(items) == 4
        assert {p.name for p in items} == {"openai", "deepseek", "zhipu", "ollama"}

        openai = await repo.get_by_name("openai")
        assert openai is not None
        assert openai.builtin_key == "openai"  # RED: AttributeError（模型缺字段）
        assert openai.id == legacy.id  # 回填是更新，不是新插入

    async def test_seed_idempotent_fresh_then_reseed(self, db_session):
        """场景 C（幂等保持，既有行为护栏）：全新库 seed → 4 行；再 seed → 0."""
        repo = SQLiteProviderConfigRepository(db_session)
        assert await repo.seed_builtin_providers() == 4
        assert await repo.seed_builtin_providers() == 0
        assert len(await repo.list()) == 4

    async def test_conversion_functions_carry_builtin_key(self, db_session):
        """转换函数契约：_domain_to_orm / _orm_to_domain 携带 builtin_key."""
        from inkflow.infrastructure.database.repositories.provider_config_repo import (
            _domain_to_orm,
            _orm_to_domain,
        )

        domain = ProviderConfig(name="openai", builtin_key="openai")  # RED: TypeError
        orm = _domain_to_orm(domain)
        assert orm.builtin_key == "openai"

        back = _orm_to_domain(orm)
        assert back.builtin_key == "openai"
