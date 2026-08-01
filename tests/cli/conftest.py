"""CLI 集成测试共享 fixture.

提供独立临时 SQLite 数据库和 JSON 输出解析器。
"""

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from typer.testing import CliRunner

import inkflow.core.database as db

runner = CliRunner()


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    """每个测试独立临时 SQLite — patch CLI 和 core 两处."""
    db_path = tmp_path / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # patch core 模块（API 依赖）
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "async_session_factory", factory)

    # patch CLI 模块（CLI 命令的 import 缓存）
    import inkflow.cli.commands.project as cli_mod

    monkeypatch.setattr(cli_mod, "async_session_factory", factory)

    import inkflow.cli.commands.write as write_mod

    monkeypatch.setattr(write_mod, "async_session_factory", factory)

    yield


def _parse_json_output(output: str):
    """从 CliRunner 输出中提取 JSON，信封格式时返回 data 部分."""
    text = output.strip()
    for i, ch in enumerate(text):
        if ch in ("[", "{"):
            parsed = json.loads(text[i:])
            if isinstance(parsed, dict) and "ok" in parsed and "data" in parsed:
                return parsed["data"]
            return parsed
    raise ValueError(f"No JSON found: {text[:100]!r}")
