"""SQLAlchemy async engine and session factory."""

import numbers
import re
from collections.abc import AsyncGenerator, Callable
from contextlib import suppress
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
    - ``PRAGMA foreign_keys=ON``: 启用 SQLite 外键约束（#327），使 ORM 声明的
      ``ForeignKey(..., ondelete=...)``（CASCADE/SET NULL）真正生效，
      project 硬删时子实体级联清理。

    PRAGMA 不支持 ``?`` 参数占位，busy_timeout 为 config int，f-string 拼接安全。
    cursor 用完即 close。对同一连接重复调用幂等；内存库 WAL 不生效但不抛错。
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={config.db_busy_timeout_ms}")
        cursor.execute("PRAGMA foreign_keys=ON")
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


def ensure_agent_executions_hitl_payload_column(conn: Connection) -> None:
    """#161 补充：为既有库 agent_executions 表补 hitl_payload 列（幂等，配合 conn.run_sync 调用）.

    项目无 alembic 基建（create_all 管理 schema）；SQLite ALTER TABLE ADD COLUMN 幂等，
    先查 PRAGMA table_info 确认列缺失才执行。表不存在（全新环境）→ no-op 不抛错，
    等 create_all 建新表（自动含 hitl_payload 列）。
    """
    cols = conn.execute(text("PRAGMA table_info(agent_executions)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含 hitl_payload 列）
    if "hitl_payload" not in names:
        conn.execute(text("ALTER TABLE agent_executions ADD COLUMN hitl_payload TEXT"))


def ensure_agent_executions_relations_column(conn: Connection) -> None:
    """F46 #270 补充：为既有库 agent_executions 表补 relations 列（幂等，配合 conn.run_sync 调用）。

    项目无 alembic 基建（create_all 管理 schema）；SQLite ALTER TABLE ADD COLUMN 幂等，
    先查 PRAGMA table_info 确认列缺失才执行。表不存在（全新环境）→ no-op 不抛错，
    等 create_all 建新表（自动含 relations 列）。
    """
    cols = conn.execute(text("PRAGMA table_info(agent_executions)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含 relations 列）
    if "relations" not in names:
        conn.execute(text("ALTER TABLE agent_executions ADD COLUMN relations TEXT"))


def ensure_agent_executions_trace_column(conn: Connection) -> None:
    """F47 #379 补充：为存量库 agent_executions 表补 trace 列（幂等，配合 conn.run_sync 调用）。

    项目无 alembic 基础（create_all 管理 schema）；SQLite ALTER TABLE ADD COLUMN 幂等，
    先查 PRAGMA table_info 确认列缺失才执行。表不存在（全新环境）→ no-op 不抛错，
    等 create_all 建新表（自动含 trace 列）。
    """
    cols = conn.execute(text("PRAGMA table_info(agent_executions)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含 trace 列）
    if "trace" not in names:
        conn.execute(text("ALTER TABLE agent_executions ADD COLUMN trace TEXT"))


def ensure_agent_executions_thread_id_column(conn: Connection) -> None:
    """F44 阶段 4（#338）：为存量库 agent_executions 表补 thread_id 列（幂等）。

    镜像 ensure_agent_executions_trace_column 形态：先查 PRAGMA table_info 确认
    列缺失才执行 ALTER TABLE ADD COLUMN；表不存在（全新环境）→ no-op 不抛错，
    等 create_all 建新表（ORM 已含 thread_id 列）。
    """
    cols = conn.execute(text("PRAGMA table_info(agent_executions)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含 thread_id 列）
    if "thread_id" not in names:
        conn.execute(text("ALTER TABLE agent_executions ADD COLUMN thread_id TEXT"))


def ensure_agent_role_key_column(conn: Connection) -> None:
    """F42 v1.5 #484：为存量库 agents 表补 role_key 列（幂等，配合 conn.run_sync 调用）。

    镜像 ensure_agent_executions_trace_column 形态：先查 PRAGMA table_info 确认
    列缺失才执行 ALTER TABLE ADD COLUMN；表不存在（全新环境）→ no-op 不抛错，
    等 create_all 建新表（ORM 已含 role_key 列）。存量行 role_key 值由
    seed_builtin_agents 升级钩子回填（spec §5.7.1 seed 升级钩子）。
    """
    cols = conn.execute(text("PRAGMA table_info(agents)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含 role_key 列）
    if "role_key" not in names:
        conn.execute(text("ALTER TABLE agents ADD COLUMN role_key VARCHAR(100)"))


def ensure_chat_messages_is_deleted_column(conn: Connection) -> None:
    """#566：为既有库 chat_messages 表补 is_deleted 列（幂等，配合 conn.run_sync 调用）。

    镜像 ensure_agent_role_key_column 形态：先查 PRAGMA table_info 确认列缺失
    才执行 ALTER TABLE ADD COLUMN；表不存在（全新环境）→ no-op 不抛错，
    等 create_all 建新表（ORM 已含 is_deleted 列）。
    """
    cols = conn.execute(text("PRAGMA table_info(chat_messages)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含 is_deleted 列）
    if "is_deleted" not in names:
        conn.execute(
            text("ALTER TABLE chat_messages ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0")
        )


def ensure_chat_messages_conversation_id_column(conn: Connection) -> None:
    """#744：为存量库 chat_messages 补 conversation_id 列 + 回填（幂等）。

    镜像 ensure_chat_messages_is_deleted_column 形态：先查 PRAGMA table_info 确认
    列缺失才执行 ALTER TABLE ADD COLUMN；表不存在（全新环境）→ no-op 不抛错，等
    create_all 建新表（自动含 conversation_id 列 + conversations 表）。

    回填（幂等，仅首次缺列时执行）：
    (1) 为还有 NULL conversation_id 消息的项目各建一条 conversation，并链接
        （每项目取最早一条 conversation）；
    (2) UPDATE chat_messages SET conversation_id = 该项目最早 conversation.id。
    """
    cols = conn.execute(text("PRAGMA table_info(chat_messages)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含 conversation_id 列）
    if "conversation_id" not in names:
        conn.execute(text("ALTER TABLE chat_messages ADD COLUMN conversation_id INTEGER"))
    # 回填：为还有 NULL conversation_id 消息的项目各建一条 conversation，并链接
    # （幂等，仅首次缺列时执行）
    # ① 建 conversation
    conn.execute(
        text(
            "INSERT INTO conversations (project_id, created_at, is_deleted) "
            "SELECT DISTINCT project_id, CURRENT_TIMESTAMP, 0 FROM chat_messages "
            "WHERE conversation_id IS NULL"
        )
    )
    # ② 链接（每项目取其最早一条 conversation）
    conn.execute(
        text(
            "UPDATE chat_messages SET conversation_id = ("
            "  SELECT c.id FROM conversations c WHERE c.project_id = chat_messages.project_id "
            "ORDER BY c.id LIMIT 1"
            ") WHERE conversation_id IS NULL"
        )
    )


def ensure_conversations_delete_permission_column(conn: Connection) -> None:
    """#766 阶段②：为存量库 conversations 表补 delete_permission 列（幂等，conn.run_sync 调用）.

    镜像 ensure_characters_brief_column 幂等模式：先查 PRAGMA table_info 确认列缺失
    才执行 ALTER TABLE ADD COLUMN；表不存在（全新环境）→ no-op 不抛错，等
    create_all 建新表（ORM 已含 delete_permission 列）。默认 manual（删除不可用，
    AI 不注册删除工具，spec f26 §6.2）。
    """
    cols = conn.execute(text("PRAGMA table_info(conversations)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含 delete_permission 列）
    if "delete_permission" not in names:
        conn.execute(
            text(
                "ALTER TABLE conversations ADD COLUMN "
                "delete_permission VARCHAR(16) NOT NULL DEFAULT 'manual'"
            )
        )


def ensure_conversation_title_column(conn: Connection) -> None:
    """#770：为既有库 conversations 表补 title 列（幂等，配合 conn.run_sync 调用）。

    镜像 ensure_chat_messages_is_deleted_column 形态：先查 PRAGMA table_info 确认
    列缺失才执行 ALTER TABLE ADD COLUMN；表不存在（全新环境）→ no-op 不抛错，
    等 create_all 建新表（自动含 title 列）。
    """
    cols = conn.execute(text("PRAGMA table_info(conversations)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含 title 列）
    if "title" not in names:
        conn.execute(
            text("ALTER TABLE conversations ADD COLUMN title VARCHAR(200) NOT NULL DEFAULT ''")
        )


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
        if "parent_map_id" not in map_names:
            conn.execute(text("ALTER TABLE maps ADD COLUMN parent_map_id INTEGER"))
    pin_cols = conn.execute(text("PRAGMA table_info(map_pins)")).fetchall()
    pin_names = {row[1] for row in pin_cols}
    if pin_names:
        if "type" not in pin_names:
            conn.execute(
                text("ALTER TABLE map_pins ADD COLUMN type VARCHAR(16) DEFAULT 'location'")
            )
        if "ref_id" not in pin_names:
            conn.execute(text("ALTER TABLE map_pins ADD COLUMN ref_id INTEGER"))


def ensure_outline_columns(conn: Connection) -> None:
    """F43 P3：为既有库 outlines 表补 level/parent_id/chapter_id 列（幂等）.

    沿用 ensure_map_columns 幂等模式：先查 PRAGMA table_info 确认列缺失
    才执行 ALTER TABLE ADD COLUMN；表不存在（全新环境）→ no-op 不抛错，
    等 create_all 建新表（ORM 已含三列）。spec §2.8 迁移（接线点在
    create_tables() 后，与 ensure_map_columns 同点）。
    """
    cols = conn.execute(text("PRAGMA table_info(outlines)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含三列）
    if "level" not in names:
        conn.execute(text("ALTER TABLE outlines ADD COLUMN level VARCHAR(16) DEFAULT 'chapter'"))
    if "parent_id" not in names:
        conn.execute(text("ALTER TABLE outlines ADD COLUMN parent_id INTEGER"))
    if "chapter_id" not in names:
        conn.execute(text("ALTER TABLE outlines ADD COLUMN chapter_id INTEGER"))


def ensure_characters_brief_column(conn: Connection) -> None:
    """#593 F6 D5-a1：为既有库 characters 表补 brief 列（幂等，配合 conn.run_sync 调用）.

    镜像 ensure_outline_columns 幂等模式：先查 PRAGMA table_info 确认列缺失
    才执行 ALTER TABLE ADD COLUMN；表不存在（全新环境）→ no-op 不抛错，
    等 create_all 建新表（ORM 已含 brief 列）。
    """
    cols = conn.execute(text("PRAGMA table_info(characters)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含 brief 列）
    if "brief" not in names:
        conn.execute(text("ALTER TABLE characters ADD COLUMN brief TEXT NOT NULL DEFAULT ''"))


def ensure_project_watermark_column(conn: Connection) -> None:
    """#617 Q1=A：为存量库 projects 表补 active_watermark 列（幂等，配合 conn.run_sync 调用）.

    镜像 ensure_characters_brief_column 幂等模式：先查 PRAGMA table_info 确认列缺失
    才执行 ALTER TABLE ADD COLUMN；表不存在（全新环境）→ no-op 不抛错，等
    create_all 建新表（ORM 已含 active_watermark 列）。首迁水位 0 初始化（Q1=A 拍板）.
    """
    cols = conn.execute(text("PRAGMA table_info(projects)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含 active_watermark 列）
    if "active_watermark" not in names:
        conn.execute(
            text("ALTER TABLE projects ADD COLUMN active_watermark FLOAT NOT NULL DEFAULT 0.0")
        )


def ensure_preference_superseded_column(conn: Connection) -> None:
    """#618：为存量库 project_preferences 表补 superseded_by 列（幂等，镜像
    ensure_project_watermark_column）."""
    cols = conn.execute(text("PRAGMA table_info(project_preferences)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）→ create_all 建新表（自动含列）
    if "superseded_by" not in names:
        conn.execute(
            text(
                "ALTER TABLE project_preferences ADD COLUMN superseded_by "
                "TEXT NOT NULL DEFAULT ''"
            )
        )


def ensure_user_preference_superseded_column(conn: Connection) -> None:
    """#618：为存量库 user_preferences 表补 superseded_by 列（幂等，镜像
    ensure_project_watermark_column）."""
    cols = conn.execute(text("PRAGMA table_info(user_preferences)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return
    if "superseded_by" not in names:
        conn.execute(
            text(
                "ALTER TABLE user_preferences ADD COLUMN superseded_by " "TEXT NOT NULL DEFAULT ''"
            )
        )


def ensure_outline_volume_id_column(conn: Connection) -> None:
    """#592：为既有库 outlines 表补 volume_id 列 + 建唯一索引（幂等）.

    表不存在（全新环境）-> no-op，等 create_all 建新表（ORM 已含列+索引）。
    """
    cols = conn.execute(text("PRAGMA table_info(outlines)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return
    if "volume_id" not in names:
        conn.execute(text("ALTER TABLE outlines ADD COLUMN volume_id INTEGER"))
    conn.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS uq_outlines_volume_id ON outlines(volume_id)")
    )


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


def ensure_world_categories(conn: Connection) -> None:
    """#389 v1.2：world_categories 分类实体表建表（仅 create_all，无存量数据迁移）.

    全新表（非补列/改索引），由 Base.metadata.create_all 幂等创建——checkfirst
    仅建缺失表；无需 ALTER 迁移。接线点若需显式调用，置于 create_tables() 之后
    （与 ensure_map_columns / ensure_outline_columns 同点）。
    """
    Base.metadata.create_all(conn)


def ensure_world_categories_kind_column(conn: Connection) -> None:
    """#699: add kind column to world_categories (idempotent)."""
    cols = conn.execute(text("PRAGMA table_info(world_categories)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # table missing (fresh env) -> create_all builds it with the column
    if "kind" not in names:
        conn.execute(
            text(
                "ALTER TABLE world_categories " "ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'geo'"
            )
        )


def ensure_world_root_unique_index(conn: Connection) -> None:
    """#849: 为既有库 world_settings 补根单例部分唯一索引（幂等，conn.run_sync 调用）."""
    cols = conn.execute(text("PRAGMA table_info(world_settings)")).fetchall()
    names = {row[1] for row in cols}
    if not names:
        return  # 表不存在（全新环境）-> create_all 建新表自动含索引
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_world_settings_root_per_project "
            "ON world_settings (project_id) WHERE parent_id IS NULL"
        )
    )


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
                text(f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table} ({columns})")
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


def _sql_top_level_segments(create_sql: str) -> list[str]:
    """按顶层逗号拆分 CREATE TABLE 主体为列/约束定义段（括号嵌套感知）.

    重建 characters 表需要从 sqlite_master.sql 的原 DDL 中剔除 group_id 列
    及引用它的 FK；先按顶层逗号切分，再逐段判定是否引用 group_id。
    """
    start = create_sql.index("(")
    end = create_sql.rindex(")")
    body = create_sql[start + 1 : end]
    segments: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            segments.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        segments.append("".join(current).strip())
    return [seg for seg in segments if seg]


def _references_group_id(segment: str) -> bool:
    """判定建表/索引段是否引用 group_id（列定义本身或 FK/UNIQUE 等约束）.

    列定义以 ``group_id`` 开头（允许引号）；表级约束/索引用词边界匹配
    ``group_id``，避免误伤 ``some_group_id`` 之类相似列名。
    """
    if re.match(r'^\s*"?group_id"?\s', segment):
        return True
    return re.search(r"\bgroup_id\b", segment) is not None


def _foreign_keys_enabled(conn: Connection) -> bool:
    """读取当前连接 ``PRAGMA foreign_keys`` 是否开启（供重建表时恢复）."""
    row = conn.exec_driver_sql("PRAGMA foreign_keys").fetchone()
    if row is None:
        raise RuntimeError("无法读取 SQLite foreign_keys pragma")
    return int(row[0]) == 1


def _rebuild_characters_without_group_id(conn: Connection) -> None:
    """#831：重建 characters 表以安全移除 group_id 列及引用它的 FK.

    SQLite DROP COLUMN 拒绝删除被 FK 引用的列（旧 schema characters.group_id
    有 ``FOREIGN KEY ... ON DELETE SET NULL``），且 FK 不存于 sqlite_master
    索引记录，仅枚举索引无法解阻。本函数走官方重建表路径：
    ① 从 sqlite_master.sql 取原 CREATE TABLE DDL，剔除 group_id 列定义与
       引用 group_id 的 FK 等约束段；
    ② 建临时表 ``_characters_new``（无 group_id），按其余全部列
       INSERT ... SELECT 拷贝数据；
    ③ DROP 旧表 → RENAME 为 characters → 重建原非 group_id 索引
       （含 uq_characters_active_name 等既有结构）。

    SQLite 的 ``PRAGMA foreign_keys`` 只能在无挂起事务时切换；生产路径由
    ``run_character_group_members_migration`` 在独立 AUTOCOMMIT 连接上先 FK=OFF
    再调用本函数（无挂起事务 → pragma 生效），重建体由调用方包 ``BEGIN/COMMIT``
    原子化——避免 DROP 后 RENAME 前崩溃残留 ``_characters_new``/空 characters（数据丢）。
    若本函数被直接在事务内连接（FK=ON 无法关闭）调用则抛错，否则 DROP 父表会沿
    FK CASCADE 清空 character_relations / character_group_members（#831 数据丢失）。
    重建前先幂等清理遗留 ``_characters_new``（防重试报 already exists）。
    """
    create_sql_row = conn.execute(
        text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'characters'")
    ).fetchone()
    if create_sql_row is None:
        raise RuntimeError("characters 表 DDL 缺失，无法安全重建以移除 group_id")
    create_sql = create_sql_row[0]
    if create_sql is None:
        raise RuntimeError("characters 表 DDL 缺失，无法安全重建以移除 group_id")
    keep_segments = [
        seg for seg in _sql_top_level_segments(create_sql) if not _references_group_id(seg)
    ]
    col_rows = conn.execute(text("PRAGMA table_info(characters)")).fetchall()
    keep_cols = [col[1] for col in col_rows if col[1] != "group_id"]
    fk_was_on = _foreign_keys_enabled(conn)
    if fk_was_on:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if _foreign_keys_enabled(conn):
            raise RuntimeError(
                "无法关闭 foreign_keys（事务已挂起时 pragma 为 no-op），"
                "重建 characters 会沿 FK CASCADE 清空关联表"
            )
    try:
        # 幂等清理遗留临时表（partial-crash 后重试不报 already exists）
        conn.execute(text("DROP TABLE IF EXISTS _characters_new"))
        conn.execute(text(f"CREATE TABLE _characters_new ({', '.join(keep_segments)})"))
        col_list = ", ".join(keep_cols)
        conn.execute(
            text(f"INSERT INTO _characters_new ({col_list}) SELECT {col_list} FROM characters")
        )
        index_rows = conn.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = 'characters' "
                "AND sql IS NOT NULL AND name NOT LIKE 'sqlite_autoindex%'"
            )
        ).fetchall()
        conn.execute(text("DROP TABLE characters"))
        conn.execute(text("ALTER TABLE _characters_new RENAME TO characters"))
        for (index_sql,) in index_rows:
            if not _references_group_id(index_sql):
                conn.execute(text(index_sql))
    except Exception:
        if fk_was_on:
            with suppress(Exception):
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        raise
    if fk_was_on:
        with suppress(Exception):
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def ensure_character_group_members_migration(conn: Connection) -> None:
    """#701：角色分组 N:M 关联表迁移（幂等，配合 conn.run_sync 调用）.

    步骤（load-bearing 顺序）:
    ① CREATE TABLE IF NOT EXISTS character_group_members（复合主键 + 双 FK
       CASCADE，角色/分组硬删级联移除关联行）；
    ② 旧库 characters 表若仍含 group_id 列：先把存量分组归属 INSERT 到关联表，
       再走重建表路径移除列（见 _rebuild_characters_without_group_id：旧列被
       FK 引用时 SQLite DROP COLUMN 会被拒止，#831）；
    ③ 全新库（create_all 已建关联表且 characters 无 group_id 列）→ no-op。
    """
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS character_group_members ("
            "character_id INTEGER NOT NULL, "
            "group_id INTEGER NOT NULL, "
            "PRIMARY KEY(character_id, group_id), "
            "FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE, "
            "FOREIGN KEY(group_id) REFERENCES character_groups(id) ON DELETE CASCADE"
            ")"
        )
    )
    cols = conn.execute(text("PRAGMA table_info(characters)")).fetchall()
    names = {row[1] for row in cols}
    if not names or "group_id" not in names:
        return  # 表不存在（全新环境）或列已移除 → no-op
    # ① 存量分组归属回填到关联表（必须先于移列生效；OR IGNORE 保证重建失败
    #    重跑时不会因重复主键报错）
    conn.execute(
        text(
            "INSERT OR IGNORE INTO character_group_members(character_id, group_id) "
            "SELECT id, group_id FROM characters WHERE group_id IS NOT NULL"
        )
    )
    # ② 重建 characters 安全移除 group_id（旧列被 FK 引用，DROP COLUMN 被拒止）
    _rebuild_characters_without_group_id(conn)


async def run_character_group_members_migration() -> None:
    """#831：在 FK=OFF（AUTOCOMMIT）独立连接上执行角色分组 N:M 迁移，安全重建 characters.

    app lifespan 的主迁移链在 ``engine.begin()``（FK=ON）事务内运行——SQLite 的
    ``PRAGMA foreign_keys`` 在同一事务内是 no-op（无法切换），且主事务 DDL 已持有
    写锁，若在共享连接上重建 characters，``DROP TABLE characters`` 会沿 FK CASCADE
    清空 ``character_relations`` 与回填后的 ``character_group_members``（数据丢失）。
    故本函数在独立 AUTOCOMMIT 连接上：先关闭 FK（无事务时才生效）、执行
    ``ensure_character_group_members_migration``（含重建表）、再恢复 FK=ON。
    调用方须在其它写事务提交后调用（app lifespan 已保证），避免写锁冲突。
    """
    async with engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            # 原子化：整段迁移（建关联表 + 回填 + 重建 characters）包 BEGIN/COMMIT，
            # FK=OFF 在事务外设置；中途崩溃即 ROLLBACK，不留 _characters_new / 空 characters，
            # 下次启动可整段重试（配合 _rebuild_* 的 DROP TABLE IF EXISTS _characters_new）。
            await conn.exec_driver_sql("BEGIN")
            try:
                await conn.run_sync(ensure_character_group_members_migration)
            except Exception:
                with suppress(Exception):
                    await conn.exec_driver_sql("ROLLBACK")
                raise
            await conn.exec_driver_sql("COMMIT")
        finally:
            with suppress(Exception):
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")


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


def ensure_foreshadowing_drop_is_deleted(conn: Connection) -> None:
    """#211 v1.1：foreshadowings 软删 → 真删迁移（partial unique → 全唯一）."""
    _migrate_drop_is_deleted(
        conn,
        "foreshadowings",
        {"uq_foreshadowings_active_title": "project_id, title"},
    )


async def drop_tables() -> None:
    """Drop all tables (for test teardown)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
