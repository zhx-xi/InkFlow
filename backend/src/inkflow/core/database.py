"""SQLAlchemy async engine and session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from inkflow.core.config import config


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


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


async def drop_tables() -> None:
    """Drop all tables (for test teardown)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
