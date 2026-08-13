"""SQLAlchemy async engine and session factory."""

import numbers
from collections.abc import AsyncGenerator, Callable
from typing import Any, TypeVar, overload

from sqlalchemy import Connection, event, text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.type_api import TypeEngineMixin
from sqlalchemy.types import TypeEngine

from inkflow.core.config import config

_TE = TypeVar("_TE", bound=TypeEngine[Any])


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


class LenientJSON(JSON):
    """容错 JSON 列类型（#261）：DB 空串/空白串/损坏 JSON 回退默认值，不再抛 ValueError。

    SQLAlchemy SQLite JSON 类型的 result_processor 对非 None 原始值无条件 json.loads，
    历史数据把 extra/config 等 JSON 列写成空串 ''（如旧版本落库/手工改库）时，任何 ORM
    读取都会 ValueError("Expecting value: line 1 column 1")。本类型在解析前先做空串检查，
    解析失败按列 fallback（dict 列 {} / list 列 []）容错，与既有 `orm.extra or {}` 防护互补。
    """

    def __init__(self, *args: Any, fallback: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._fallback = fallback

    @overload
    def adapt(self, cls: type[_TE], **kw: Any) -> _TE: ...

    @overload
    def adapt(self, cls: type[TypeEngineMixin], **kw: Any) -> TypeEngine[Any]: ...

    def adapt(self, cls: type[TypeEngine[Any] | TypeEngineMixin], **kw: Any) -> TypeEngine[Any]:
        # SQLite 方言会把泛型 JSON 适配为内部 _SQliteJson；constructor_copy 只复制签名
        # 匹配的参数，fallback 状态会丢失，容错 result_processor 被绕过。本项目仅使用
        # SQLite，JSON 语义不变：适配时返回带同样 fallback 的新实例（不能返回 self，
        # SQLAlchemy _dialect_info 要求 impl 与类型实例分离，否则断言失败）。
        if issubclass(cls, JSON):
            return type(self)(fallback=self._fallback, **kw)
        return super().adapt(cls, **kw)

    def result_processor(self, dialect: Dialect, coltype: Any) -> Callable[[Any], Any] | None:
        base_process = super().result_processor(dialect, coltype)

        def _process(value: Any) -> Any:
            if value is None or (isinstance(value, str) and not value.strip()):
                return self._fallback
            try:
                return base_process(value) if base_process is not None else value
            except ValueError:
                return self._fallback
            except TypeError:
                # 镜像 _SQliteJson 语义：SQLite 返回的裸数值（JSON 标量）原样透传
                return value if isinstance(value, numbers.Number) else self._fallback

        return _process


engine = create_async_engine(
    config.database_url,
    echo=(config.log_level == "DEBUG"),
)


def apply_sqlite_pragma(dbapi_connection) -> None:
    """Apply SQLite PRAGMAs on a new DBAPI connection (spec §2.4).

    - ``PRAGMA journal_mode=WAL``: WAL 日志模式（文件级持久，跨连接生效）
    - ``PRAGMA busy_timeout=<config.db_busy_timeout_ms>``: 多进程写并发锁等待
      超时，数值在**调用时**从 config 单例读取（默认 5000）。

    PRAGMA 不支持 ``?`` 参数占位，busy_timeout 为 config int，f-string 拼接安全。
    cursor 用完即 close。对同一连接重复调用幂等；内存库 WAL 不生效但不抛错。
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={config.db_busy_timeout_ms}")
    finally:
        cursor.close()


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """connect 事件委托：PRAGMA 逻辑收敛在 apply_sqlite_pragma 单一函数。"""
    apply_sqlite_pragma(dbapi_connection)


async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a new async database session (for FastAPI dependency injection)."""
    async with async_session_factory() as session:
        yield session


async def create_tables() -> None:
    """Create all tables (for dev/CLI startup)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def ensure_provider_builtin_key_column(conn: Connection) -> None:
    """#126 A1：为既有库 provider_configs 表补充 builtin_key 列（幂等，配合 conn.run_sync 调用）.

    项目无 alembic 基建（create_all 管理 schema）；SQLite ALTER TABLE ADD COLUMN 幂等，
    先查 PRAGMA table_info 确认列缺失才执行。表不存在（全新环境）→ no-op 不抛错，
    等 create_all 建新表（自动含 builtin_key 列）。迁移后内置行 key 由 seed 回填。
    """
    cols = conn.execute(text("PRAGMA table_info(provider_configs)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        # 表不存在（CI 全新 runner / 测试 mock create_tables 场景）→ 无列可补，no-op
        return
    if "builtin_key" not in names:
        conn.execute(text("ALTER TABLE provider_configs ADD COLUMN builtin_key VARCHAR(50)"))


def ensure_world_parent_id_column(conn: Connection) -> None:
    """#173：为既有库 world_settings 补 parent_id 列 + 替换唯一索引（幂等）.

    表不存在（全新环境）→ no-op，等 create_all 建新表（自动含列+新索引）；
    旧全局唯一索引 uq_world_settings_active_name 与新同级唯一语义冲突，必须删除重建。
    v1.1（#211）is_deleted 列移除后（全新 schema）→ 全唯一索引已由 create_all
    建好，仅补列（如有缺失）并跳过 partial unique 替换。
    """
    cols = conn.execute(text("PRAGMA table_info(world_settings)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含列+新索引）
    if "parent_id" not in names:
        conn.execute(text("ALTER TABLE world_settings ADD COLUMN parent_id INTEGER"))
    if "is_deleted" not in names:
        # v1.1 真删语义：新 schema 无 is_deleted 列，全唯一索引已存在，跳过替换
        return
    # 唯一索引替换：旧全局唯一 → 新同级唯一（先删旧，再建新，幂等）
    conn.execute(text("DROP INDEX IF EXISTS uq_world_settings_active_name"))
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_world_settings_active_name_parent "
            "ON world_settings (project_id, parent_id, name) WHERE is_deleted = 0"
        )
    )


def ensure_map_columns(conn: Connection) -> None:
    """F43 P2：为既有库 maps/map_pins 补 bg_source/extra/type/ref_id 列（幂等）.

    沿用 ensure_world_parent_id_column 模式：先查 PRAGMA table_info 确认列缺失
    才执行 ALTER TABLE ADD COLUMN；表不存在（全新环境）→ no-op 不抛错，等
    create_all 建新表（ORM 已含新列）。spec §2.7.3。
    """
    map_cols = conn.execute(text("PRAGMA table_info(maps)")).fetchall()
    map_names = {row[1] for row in map_cols}
    if map_names:
        if "bg_source" not in map_names:
            conn.execute(text("ALTER TABLE maps ADD COLUMN bg_source VARCHAR(16) DEFAULT 'image'"))
        if "extra" not in map_names:
            conn.execute(text("ALTER TABLE maps ADD COLUMN extra JSON"))
    pin_cols = conn.execute(text("PRAGMA table_info(map_pins)")).fetchall()
    pin_names = {row[1] for row in pin_cols}
    if pin_names:
        if "type" not in pin_names:
            conn.execute(
                text("ALTER TABLE map_pins ADD COLUMN type VARCHAR(16) DEFAULT 'location'")
            )
        if "ref_id" not in pin_names:
            conn.execute(text("ALTER TABLE map_pins ADD COLUMN ref_id INTEGER"))
def ensure_world_drop_is_deleted(conn: Connection) -> None:
    """#211 v1.1：world_settings 软删语义 → 真删迁移（幂等，spec §8.3）.

    步骤（load-bearing 顺序，SQLite DROP COLUMN 不能删除被索引/partial WHERE
    引用的列）：
    ① DELETE 存量软删记录（is_deleted=1 物理清除）；
    ② DROP 依赖 is_deleted 的索引（partial unique + is_deleted 单列索引）；
    ③ CREATE 全唯一索引 uq_world_settings_active_name_parent（无 WHERE 条件）；
    ④ ALTER TABLE world_settings DROP COLUMN is_deleted。

    表不存在或列已不存在（全新环境/已迁移）→ no-op。
    """
    cols = conn.execute(text("PRAGMA table_info(world_settings)")).fetchall()
    names = {row[1] for row in cols}
    if not names or "is_deleted" not in names:
        return  # 表不存在（全新环境）或列已移除 → no-op
    # ① 清存量软删
    conn.execute(text("DELETE FROM world_settings WHERE is_deleted = 1"))
    # ② 删依赖 is_deleted 的索引（partial unique + 单列索引，按 sqlite_master 枚举）
    index_rows = conn.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = 'world_settings' AND sql LIKE '%is_deleted%'"
        )
    ).fetchall()
    for (index_name,) in index_rows:
        conn.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))
    # ③ 重建全唯一索引（无 WHERE is_deleted = 0）
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_world_settings_active_name_parent "
            "ON world_settings (project_id, parent_id, name)"
        )
    )
    # ④ 删列
    conn.execute(text("ALTER TABLE world_settings DROP COLUMN is_deleted"))


def _migrate_drop_is_deleted(
    conn: Connection,
    table: str,
    unique_indexes: dict[str, str] | None = None,
) -> None:
    """#211 v1.1：单表 is_deleted 列移除迁移（幂等，spec §8.3 通用步骤）.

    步骤（load-bearing 顺序，SQLite DROP COLUMN 不能删除被索引/partial WHERE
    引用的列）：
    ① DELETE 存量软删记录（is_deleted=1 物理清除）；
    ② DROP 依赖 is_deleted 的索引（partial unique + is_deleted 单列索引，
       按 sqlite_master 枚举）；
    ③ CREATE 全唯一索引（无 WHERE 条件，仅 unique_indexes 提供的表）；
    ④ ALTER TABLE <table> DROP COLUMN is_deleted。

    表不存在或列已不存在（全新环境/已迁移）→ no-op。

    Args:
        conn: 同步连接（conn.run_sync 传入）.
        table: 目标表名（硬编码常量，非用户输入）.
        unique_indexes: {索引名: 索引列列表（不含表名）}，partial unique → 全唯一；
            None/空表示该表无唯一索引（仅清理存量软删 + 删列）.
    """
    cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    names = {row[1] for row in cols}
    if not names or "is_deleted" not in names:
        return  # 表不存在（全新环境）或列已移除 → no-op
    # ① 清存量软删
    conn.execute(text(f"DELETE FROM {table} WHERE is_deleted = 1"))
    # ② 删依赖 is_deleted 的索引（partial unique + 单列索引，按 sqlite_master 枚举）
    index_rows = conn.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = :tbl AND sql LIKE '%is_deleted%'"
        ),
        {"tbl": table},
    ).fetchall()
    for (index_name,) in index_rows:
        conn.execute(text(f'DROP INDEX IF EXISTS "{index_name}"'))
    # ③ 重建全唯一索引（无 WHERE is_deleted = 0）
    if unique_indexes:
        for index_name, columns in unique_indexes.items():
            conn.execute(
                text(f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} " f"ON {table} ({columns})")
            )
    # ④ 删列
    conn.execute(text(f"ALTER TABLE {table} DROP COLUMN is_deleted"))


def ensure_character_drop_is_deleted(conn: Connection) -> None:
    """#211 v1.1：characters/character_groups/character_relations 软删 → 真删迁移.

    三表均含 partial unique 索引（角色名/分组名/关系键，spec §2.4）→ 全唯一；
    角色/分组删除语义由 DB FK（关系 CASCADE / 成员 group_id SET NULL）保证。
    """
    _migrate_drop_is_deleted(
        conn,
        "characters",
        {"uq_characters_active_name": "project_id, name"},
    )
    _migrate_drop_is_deleted(
        conn,
        "character_groups",
        {"uq_character_groups_active_name": "project_id, name"},
    )
    _migrate_drop_is_deleted(
        conn,
        "character_relations",
        {
            "uq_character_relations_active_key": (
                "project_id, from_character_id, to_character_id, relation_type"
            )
        },
    )


def ensure_outline_drop_is_deleted(conn: Connection) -> None:
    """#211 v1.1：outlines/plot_points/story_arcs 软删 → 真删迁移.

    outlines 与 story_arcs 含 partial unique（大纲名/弧线名，spec §2.4）→ 全唯一；
    plot_points 无唯一约束（仅清理存量软删 + 删列）。
    """
    _migrate_drop_is_deleted(
        conn,
        "outlines",
        {"uq_outlines_active_name": "project_id, name"},
    )
    _migrate_drop_is_deleted(conn, "plot_points")
    _migrate_drop_is_deleted(
        conn,
        "story_arcs",
        {"uq_story_arcs_active_name": "project_id, name"},
    )


def ensure_timeline_drop_is_deleted(conn: Connection) -> None:
    """#211 v1.1：timeline_events 软删 → 真删迁移（无唯一约束，仅清理 + 删列）."""
    _migrate_drop_is_deleted(conn, "timeline_events")


async def drop_tables() -> None:
    """Drop all tables (for test teardown)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
