"""F32 设置仓储契约测试 — SQLiteSettingsRepository（RED 批）。

覆盖 spec §2.4（仓储实现骨架逐字为准）+ §9.4 契约断言表:
- get_all 空表 → {}
- 多行 JSON 编解码往返（repo 不解析，原样返回字符串值——解析在 service）
- set_many upsert（同 key 覆盖 → 单行 + 新值；commit 调用断言）

依据: specs/f32-settings/spec.md §2.3/§2.4 + §9.1/§9.4。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

1. ORM（infrastructure/database/models/settings.py，本批新建，当前不存在
   → 收集期 ModuleNotFoundError 即预期 RED 形态）:
   - ``class SettingsORM(Base)``，``__tablename__ = "app_settings"``（§2.3 逐字）
   - ``key: Mapped[str]`` String(50) primary_key=True
   - ``value: Mapped[str]`` Text nullable=False（JSON 编码值）
   - 注册进 ``infrastructure/database/models/__init__.py``（create_all 建表前提）

2. Repo（infrastructure/database/repositories/settings_repo.py）:
   - ``class SQLiteSettingsRepository(SettingsRepositoryProtocol)``
   - ``def __init__(self, session: AsyncSession) -> None``
   - ``async def get_all(self) -> dict[str, str]``: 全量 {key: value}，
     **value 为 JSON 编码原串**（repo 不解析；空表 → {}）
   - ``async def set_many(self, values: dict[str, str]) -> None``: 批量
     upsert（INSERT OR REPLACE / ON CONFLICT 皆可），同 key 覆盖为单行，
     **每次调用 commit 一次**
   - 实现形态（text SQL / ORM select）spec 不锁定（§2.4 注）——本文件用
     真实 in-memory SQLite 验证语义（单行覆盖 / 原串往返），不锁 SQL 文本

3. fixture: tests/unit/conftest.py 无 DB fixture → 本文件自带 ``db_session``
   （镜像 test_provider_config_repo.py: in-memory SQLite + create_all +
   async_sessionmaker(expire_on_commit=False)）。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述签名实现后本文件应全绿。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.infrastructure.database.models.settings import SettingsORM
from inkflow.infrastructure.database.repositories.settings_repo import (
    SQLiteSettingsRepository,
)


@pytest.fixture
async def db_session():
    """独立 in-memory SQLite — 每个测试一个全新数据库（镜像 provider_config repo 测试）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.integration
class TestSQLiteSettingsRepository:
    """SQLiteSettingsRepository 集成测试（真实 in-memory SQLite，语义验证）。"""

    async def test_get_all_empty_table(self, db_session):
        """空表 get_all() == {}（§9.4「空表」）。"""
        repo = SQLiteSettingsRepository(db_session)
        assert await repo.get_all() == {}

    async def test_set_many_roundtrip_raw_json_strings(self, db_session):
        """多行写入 → get_all 原样返回 JSON 编码串（repo 不解析，§9.4「编解码往返」）。"""
        repo = SQLiteSettingsRepository(db_session)
        raw = {"theme": '"night"', "bg": '"parchment"'}
        await repo.set_many(raw)

        got = await repo.get_all()
        assert got == raw
        # 关键契约：值是带引号的 JSON 原串，不是解析后的 "night"
        assert got["theme"] == '"night"'

        # 持久化验证：直接查表
        rows = (await db_session.execute(select(SettingsORM))).scalars().all()
        assert len(rows) == 2
        assert {r.key: r.value for r in rows} == raw

    async def test_set_many_upsert_same_key_single_row(self, db_session):
        """同 key 两次 set_many → 单行 + 新值（§9.4「upsert 覆盖」）。"""
        repo = SQLiteSettingsRepository(db_session)
        await repo.set_many({"theme": '"paper"'})
        await repo.set_many({"theme": '"night"'})

        assert await repo.get_all() == {"theme": '"night"'}
        rows = (await db_session.execute(select(SettingsORM))).scalars().all()
        assert len(rows) == 1
        assert rows[0].key == "theme"
        assert rows[0].value == '"night"'

    async def test_set_many_commits_once(self, db_session):
        """每次 set_many 恰好 commit 一次（§2.4 骨架语义，commit 调用断言）。"""
        repo = SQLiteSettingsRepository(db_session)
        with patch.object(
            db_session, "commit", new=AsyncMock(wraps=db_session.commit)
        ) as commit_mock:
            await repo.set_many({"theme": '"night"', "font": '"serif"'})
        commit_mock.assert_awaited_once()

    async def test_set_many_does_not_parse_values(self, db_session):
        """set_many 收什么存什么（含非法 JSON 原串）——解析防御在 service 层。"""
        repo = SQLiteSettingsRepository(db_session)
        await repo.set_many({"theme": "not-json{{{"})
        assert await repo.get_all() == {"theme": "not-json{{{"}
