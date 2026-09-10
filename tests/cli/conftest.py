"""CLI 集成测试共享 fixture.

提供独立临时 SQLite 数据库和 JSON 输出解析器。
"""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from typer.testing import CliRunner

import inkflow.core.database as db

runner = CliRunner()


def local_display(iso: str) -> str:
    """ISO → 系统本地时区 'YYYY-MM-DD HH:mm:ss'（#1000 / ADR-055 期望值独立换算）.

    测试侧平行实现：naive 串 = UTC 存储口径（SQLite DateTime 剥 tzinfo，生产
    API 常态）→ 先补 UTC 再 astimezone()。**不 import 被测 format_local**，
    避免自引用弱断言；结果与 runner 系统时区无关地恒等于「显示本地」契约值。
    """
    parsed = datetime.fromisoformat(iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")


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
