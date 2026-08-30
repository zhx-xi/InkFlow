"""Coverage backfill: idempotent schema-migration helpers in ``core/database.py``.

每个 ``ensure_*`` 迁移助手都是模块级公开函数（幂等：表缺失 no-op / 旧库补列 /
新库不改动），契约见 specs/f44-book-orchestrator/spec.md §8.2、f26/f27 迁移登记。
镜像 tests/unit/test_conversation_title.py 的「旧库补列 / 新库 no-op / 无表 no-op」
三形态模式：用同步 SQLite engine + conn 直接调用公开迁移函数，断言列集/表集变化。

覆盖（combined coverage 缺行）：
- ensure_agent_executions_thread_id_column（193-197）
- ensure_agent_role_key_column（209-213）
- ensure_chat_messages_is_deleted_column（224-228）
- ensure_chat_messages_conversation_id_column（246-262）
- ensure_conversations_delete_permission_column（281-285）
- ensure_characters_brief_column（392-396）
- ensure_preference_superseded_column（420-424）
- ensure_user_preference_superseded_column（436-440）
- ensure_world_categories（508）
- ensure_character_group_members_migration（623-644）
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

import inkflow.infrastructure.database.models  # noqa: F401  # 导入触发 Base.metadata 注册（create_all 用）


def _columns(conn, table: str) -> set[str]:
    """PRAGMA table_info 列名集合（镜像 test_conversation_title.py 助手）。"""
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _tables(conn) -> set[str]:
    """sqlite_master 全部表名。"""
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
    ).fetchall()
    return {row[0] for row in rows}


def _missing_table_noop(tmp_path, ensure_fn, filename: str) -> None:
    """无表环境 → 迁移函数 no-op 不抛错（全新环境由 create_all 建表）。"""
    db = tmp_path / filename
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        ensure_fn(conn)
        assert _tables(conn) == set()
    engine.dispose()


def _old_schema_adds_column(
    tmp_path, ensure_fn, filename: str, table: str, schema: str, column: str
) -> None:
    """旧库缺列 → ALTER 补列，重复执行幂等。"""
    db = tmp_path / filename
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        conn.execute(text(schema))
    with engine.connect() as conn:
        assert column not in _columns(conn, table)
        ensure_fn(conn)
        assert column in _columns(conn, table)
        ensure_fn(conn)
        assert column in _columns(conn, table)
    engine.dispose()


class TestAgentExecutionsThreadIdColumn:
    """ensure_agent_executions_thread_id_column：无表 no-op / 旧库补列。"""

    def test_missing_table_noop(self, tmp_path) -> None:
        from inkflow.core.database import ensure_agent_executions_thread_id_column

        _missing_table_noop(tmp_path, ensure_agent_executions_thread_id_column, "t1.db")

    def test_old_schema_adds_column(self, tmp_path) -> None:
        from inkflow.core.database import ensure_agent_executions_thread_id_column

        _old_schema_adds_column(
            tmp_path,
            ensure_agent_executions_thread_id_column,
            "t2.db",
            "agent_executions",
            "CREATE TABLE agent_executions (id INTEGER PRIMARY KEY AUTOINCREMENT)",
            "thread_id",
        )


class TestAgentRoleKeyColumn:
    """ensure_agent_role_key_column：无表 no-op / 旧库补列。"""

    def test_missing_table_noop(self, tmp_path) -> None:
        from inkflow.core.database import ensure_agent_role_key_column

        _missing_table_noop(tmp_path, ensure_agent_role_key_column, "a1.db")

    def test_old_schema_adds_column(self, tmp_path) -> None:
        from inkflow.core.database import ensure_agent_role_key_column

        _old_schema_adds_column(
            tmp_path,
            ensure_agent_role_key_column,
            "a2.db",
            "agents",
            "CREATE TABLE agents (id INTEGER PRIMARY KEY AUTOINCREMENT)",
            "role_key",
        )


class TestChatMessagesIsDeletedColumn:
    """ensure_chat_messages_is_deleted_column：无表 no-op / 旧库补列。"""

    def test_missing_table_noop(self, tmp_path) -> None:
        from inkflow.core.database import ensure_chat_messages_is_deleted_column

        _missing_table_noop(tmp_path, ensure_chat_messages_is_deleted_column, "c1.db")

    def test_old_schema_adds_column(self, tmp_path) -> None:
        from inkflow.core.database import ensure_chat_messages_is_deleted_column

        _old_schema_adds_column(
            tmp_path,
            ensure_chat_messages_is_deleted_column,
            "c2.db",
            "chat_messages",
            "CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT)",
            "is_deleted",
        )


class TestChatMessagesConversationIdColumn:
    """ensure_chat_messages_conversation_id_column：无表 no-op / 旧库补列 + 回填。"""

    def test_missing_table_noop(self, tmp_path) -> None:
        from inkflow.core.database import ensure_chat_messages_conversation_id_column

        _missing_table_noop(
            tmp_path, ensure_chat_messages_conversation_id_column, "cc1.db"
        )

    def test_old_schema_adds_column_and_backfills(self, tmp_path) -> None:
        """旧库缺 conversation_id + 存量 NULL 消息 → 补列并回填 conversation。"""
        from inkflow.core.database import ensure_chat_messages_conversation_id_column

        db = tmp_path / "cc2.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE conversations ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "project_id INTEGER NOT NULL, "
                    "created_at DATETIME NOT NULL, "
                    "is_deleted BOOLEAN NOT NULL DEFAULT 0)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE chat_messages ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "project_id INTEGER NOT NULL)"
                )
            )
            conn.execute(
                text("INSERT INTO chat_messages (project_id) VALUES (1), (1), (2)")
            )
        with engine.connect() as conn:
            assert "conversation_id" not in _columns(conn, "chat_messages")
            ensure_chat_messages_conversation_id_column(conn)
            assert "conversation_id" in _columns(conn, "chat_messages")
            # 回填：每个 project 一条 conversation，消息全部挂接
            conversations = conn.execute(
                text("SELECT COUNT(*) FROM conversations")
            ).fetchone()
            assert conversations is not None
            assert conversations[0] == 2
            null_count = conn.execute(
                text("SELECT COUNT(*) FROM chat_messages WHERE conversation_id IS NULL")
            ).fetchone()
            assert null_count is not None
            assert null_count[0] == 0
        engine.dispose()


class TestConversationsDeletePermissionColumn:
    """ensure_conversations_delete_permission_column：无表 no-op / 旧库补列。"""

    def test_missing_table_noop(self, tmp_path) -> None:
        from inkflow.core.database import (
            ensure_conversations_delete_permission_column,
        )

        _missing_table_noop(
            tmp_path, ensure_conversations_delete_permission_column, "dp1.db"
        )

    def test_old_schema_adds_column(self, tmp_path) -> None:
        from inkflow.core.database import (
            ensure_conversations_delete_permission_column,
        )

        _old_schema_adds_column(
            tmp_path,
            ensure_conversations_delete_permission_column,
            "dp2.db",
            "conversations",
            "CREATE TABLE conversations (id INTEGER PRIMARY KEY AUTOINCREMENT)",
            "delete_permission",
        )


class TestCharactersBriefColumn:
    """ensure_characters_brief_column：无表 no-op / 旧库补列。"""

    def test_missing_table_noop(self, tmp_path) -> None:
        from inkflow.core.database import ensure_characters_brief_column

        _missing_table_noop(tmp_path, ensure_characters_brief_column, "ch1.db")

    def test_old_schema_adds_column(self, tmp_path) -> None:
        from inkflow.core.database import ensure_characters_brief_column

        _old_schema_adds_column(
            tmp_path,
            ensure_characters_brief_column,
            "ch2.db",
            "characters",
            "CREATE TABLE characters (id INTEGER PRIMARY KEY AUTOINCREMENT)",
            "brief",
        )


class TestPreferenceSupersededColumn:
    """ensure_preference_superseded_column：无表 no-op / 旧库补列。"""

    def test_missing_table_noop(self, tmp_path) -> None:
        from inkflow.core.database import ensure_preference_superseded_column

        _missing_table_noop(tmp_path, ensure_preference_superseded_column, "p1.db")

    def test_old_schema_adds_column(self, tmp_path) -> None:
        from inkflow.core.database import ensure_preference_superseded_column

        _old_schema_adds_column(
            tmp_path,
            ensure_preference_superseded_column,
            "p2.db",
            "project_preferences",
            "CREATE TABLE project_preferences (id INTEGER PRIMARY KEY AUTOINCREMENT)",
            "superseded_by",
        )


class TestUserPreferenceSupersededColumn:
    """ensure_user_preference_superseded_column：无表 no-op / 旧库补列。"""

    def test_missing_table_noop(self, tmp_path) -> None:
        from inkflow.core.database import ensure_user_preference_superseded_column

        _missing_table_noop(tmp_path, ensure_user_preference_superseded_column, "u1.db")

    def test_old_schema_adds_column(self, tmp_path) -> None:
        from inkflow.core.database import ensure_user_preference_superseded_column

        _old_schema_adds_column(
            tmp_path,
            ensure_user_preference_superseded_column,
            "u2.db",
            "user_preferences",
            "CREATE TABLE user_preferences (id INTEGER PRIMARY KEY AUTOINCREMENT)",
            "superseded_by",
        )


class TestWorldCategories:
    """ensure_world_categories：空库上 create_all 建出 world_categories 表。"""

    def test_empty_db_creates_table(self, tmp_path) -> None:
        from inkflow.core.database import ensure_world_categories

        db = tmp_path / "w1.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            ensure_world_categories(conn)
            assert "world_categories" in _tables(conn)
        engine.dispose()


class TestCharacterGroupMembersMigration:
    """ensure_character_group_members_migration：旧库回填 + 删列 / 无 group_id no-op。"""

    def test_old_schema_backfills_and_drops_group_id(self, tmp_path) -> None:
        from inkflow.core.database import ensure_character_group_members_migration

        db = tmp_path / "g1.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE character_groups ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "project_id INTEGER NOT NULL)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE characters ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "project_id INTEGER NOT NULL, "
                    "group_id INTEGER)"
                )
            )
            conn.execute(text("CREATE INDEX ix_characters_group_id ON characters(group_id)"))
            conn.execute(text("INSERT INTO character_groups (id, project_id) VALUES (1, 1)"))
            conn.execute(text("INSERT INTO characters (id, project_id, group_id) VALUES (1, 1, 1)"))
        with engine.connect() as conn:
            ensure_character_group_members_migration(conn)
            assert "character_group_members" in _tables(conn)
            assert "group_id" not in _columns(conn, "characters")
            members = conn.execute(
                text("SELECT COUNT(*) FROM character_group_members")
            ).fetchone()
            assert members is not None
            assert members[0] == 1
        engine.dispose()

    def test_no_group_id_column_noop(self, tmp_path) -> None:
        from inkflow.core.database import ensure_character_group_members_migration

        db = tmp_path / "g2.db"
        engine = create_engine(f"sqlite:///{db}")
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE characters (id INTEGER PRIMARY KEY AUTOINCREMENT)")
            )
        with engine.connect() as conn:
            ensure_character_group_members_migration(conn)
            assert "group_id" not in _columns(conn, "characters")
        engine.dispose()
