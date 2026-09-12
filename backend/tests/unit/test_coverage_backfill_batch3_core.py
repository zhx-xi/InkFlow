"""Batch 3 coverage backfill: core database/config public behavior."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from pydantic_settings import SettingsConfigDict
from sqlalchemy import create_engine, event, text

import inkflow.infrastructure.database.models  # noqa: F401  # register metadata
from inkflow.core.database import (
    ensure_character_group_members_migration,
    ensure_project_columns,
)


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}


def _tables(conn) -> set[str]:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).fetchall()
    return {row[0] for row in rows}


def test_ensure_project_columns_missing_table_is_noop(tmp_path: Path) -> None:
    """Missing projects table returns early without creating schema."""
    engine = create_engine(f"sqlite:///{tmp_path / 'missing-projects.db'}")
    try:
        with engine.connect() as conn:
            ensure_project_columns(conn)
            assert "projects" not in _tables(conn)
    finally:
        engine.dispose()


def test_character_group_rebuild_restores_non_group_index_and_fk(tmp_path: Path) -> None:
    """Public migration rebuilds characters and restores safe indexes/FK state."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'group-rebuild.db'}",
        isolation_level="AUTOCOMMIT",
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE character_groups (id INTEGER PRIMARY KEY)"))
            conn.execute(
                text(
                    "CREATE TABLE characters ("
                    "id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL, "
                    "group_id INTEGER, "
                    "FOREIGN KEY(group_id) REFERENCES character_groups(id) ON DELETE SET NULL)"
                )
            )
            conn.execute(text("CREATE INDEX ix_characters_name ON characters(name)"))
            conn.execute(text("CREATE INDEX ix_characters_group_id ON characters(group_id)"))
            conn.execute(text("INSERT INTO character_groups (id) VALUES (1)"))
            conn.execute(
                text(
                    "INSERT INTO characters (id, project_id, name, group_id) "
                    "VALUES (1, 7, 'A', 1)"
                )
            )

            ensure_character_group_members_migration(conn)

            assert "group_id" not in _columns(conn, "characters")
            indexes = {
                row[0]
                for row in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'index'")
                ).fetchall()
            }
            assert "ix_characters_name" in indexes
            assert "ix_characters_group_id" not in indexes
            fk = conn.execute(text("PRAGMA foreign_keys")).fetchone()
            assert fk is not None and int(fk[0]) == 1
            members = conn.execute(
                text("SELECT character_id, group_id FROM character_group_members")
            ).fetchall()
            assert members == [(1, 1)]
    finally:
        engine.dispose()


def test_character_group_migration_rejects_foreign_keys_on_in_transaction(
    tmp_path: Path,
) -> None:
    """Public migration refuses unsafe rebuild when SQLite cannot turn FK off."""
    engine = create_engine(f"sqlite:///{tmp_path / 'group-fk-on.db'}")

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE character_groups (id INTEGER PRIMARY KEY)"))
            conn.execute(
                text(
                    "CREATE TABLE characters ("
                    "id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL, "
                    "group_id INTEGER, "
                    "FOREIGN KEY(group_id) REFERENCES character_groups(id) ON DELETE SET NULL)"
                )
            )
            conn.execute(text("INSERT INTO character_groups (id) VALUES (1)"))
            conn.execute(
                text(
                    "INSERT INTO characters (id, project_id, name, group_id) "
                    "VALUES (1, 7, 'A', 1)"
                )
            )
            with pytest.raises(RuntimeError, match="foreign_keys"):
                ensure_character_group_members_migration(conn)
            fk = conn.execute(text("PRAGMA foreign_keys")).fetchone()
            assert fk is not None and int(fk[0]) == 1
    finally:
        engine.dispose()


def test_character_group_migration_restores_fk_after_inner_failure(tmp_path: Path) -> None:
    """A public rebuild failure restores FK pragma before propagating."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'group-inner-fail.db'}",
        isolation_level="AUTOCOMMIT",
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def _fail_rebuild(dbapi_conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith("CREATE TABLE _CHARACTERS_NEW"):
            raise RuntimeError("injected rebuild failure")

    event.listen(engine, "before_cursor_execute", _fail_rebuild)
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE character_groups (id INTEGER PRIMARY KEY)"))
            conn.execute(
                text(
                    "CREATE TABLE characters ("
                    "id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL, "
                    "group_id INTEGER, "
                    "FOREIGN KEY(group_id) REFERENCES character_groups(id) ON DELETE SET NULL)"
                )
            )
            conn.execute(text("INSERT INTO character_groups (id) VALUES (1)"))
            conn.execute(
                text(
                    "INSERT INTO characters (id, project_id, name, group_id) "
                    "VALUES (1, 7, 'A', 1)"
                )
            )

            with pytest.raises(RuntimeError, match="injected rebuild failure"):
                ensure_character_group_members_migration(conn)

            assert "group_id" in _columns(conn, "characters")
            fk = conn.execute(text("PRAGMA foreign_keys")).fetchone()
            assert fk is not None and int(fk[0]) == 1
    finally:
        engine.dispose()


def test_character_group_migration_requires_real_table_ddl(tmp_path: Path) -> None:
    """Public migration rejects a characters view that lacks table DDL."""
    engine = create_engine(f"sqlite:///{tmp_path / 'characters-view.db'}")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE base (id INTEGER, group_id INTEGER)"))
            conn.execute(text("CREATE VIEW characters AS SELECT id, group_id FROM base"))

            with pytest.raises(RuntimeError, match="DDL"):
                ensure_character_group_members_migration(conn)
    finally:
        engine.dispose()


def test_load_or_create_secret_key_non_windows_branch(tmp_path: Path, monkeypatch) -> None:
    """Public secret-key helper uses exclusive file creation on non-Windows."""
    config_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(sys, "platform", "linux")

    key = config_mod.load_or_create_secret_key(tmp_path)

    assert len(key) == 64
    assert (tmp_path / "keys" / ".secret_key").read_text(encoding="utf-8") == key


def test_instance_env_source_case_sensitive_returns_raw_keys(
    tmp_path: Path, monkeypatch
) -> None:
    """Case-sensitive config source preserves instance.env key casing."""
    config_mod = importlib.import_module("inkflow.core.config")
    instance_env = tmp_path / "instance.env"
    instance_env.write_text("INKFLOW_DEBUG=1\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "get_instance_env_path", lambda: instance_env)

    class CaseSensitiveConfig(config_mod.InkFlowConfig):
        model_config = SettingsConfigDict(
            env_prefix="INKFLOW_",
            env_file=None,
            case_sensitive=True,
        )

    cfg = CaseSensitiveConfig(data_dir=tmp_path / "data")
    assert cfg.debug is True


def test_config_debug_fallback_from_config_json(tmp_path: Path, monkeypatch) -> None:
    """Public config construction honors config.json debug fallback."""
    config_mod = importlib.import_module("inkflow.core.config")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "config.json").write_text(json.dumps({"debug": True}), encoding="utf-8")
    monkeypatch.setattr(config_mod, "get_instance_env_path", lambda: tmp_path / "missing.env")

    cfg = config_mod.InkFlowConfig(_env_file=None, data_dir=data_dir)

    assert cfg.debug is True


def test_config_debug_fallback_when_config_json_source_is_not_configured(
    tmp_path: Path, monkeypatch
) -> None:
    """Config validator still honors config.json when a caller omits that source."""
    config_mod = importlib.import_module("inkflow.core.config")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "config.json").write_text(json.dumps({"debug": True}), encoding="utf-8")
    monkeypatch.setattr(config_mod, "get_instance_env_path", lambda: tmp_path / "missing.env")

    class InputOnlyConfig(config_mod.InkFlowConfig):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls,
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        ):
            return (init_settings, env_settings, dotenv_settings, file_secret_settings)

    cfg = InputOnlyConfig(_env_file=None, data_dir=data_dir)

    assert cfg.debug is True
