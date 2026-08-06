"""#126 A1 builtin_key 轻量列迁移契约（2026-08-06，方案已拍板）。

背景: 项目无 alembic 基建（无 alembic.ini/env.py/versions，全部表由
``Base.metadata.create_all`` 管理）→ 采用轻量列迁移: 启动时幂等检查
``provider_configs`` 表缺 ``builtin_key`` 列则 ``ALTER TABLE ... ADD COLUMN``
（新库 create_all 自动含列，旧库加列后由 seed 回填）。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

1. 迁移函数（本文件定义，GREEN 必须匹配）:
   - 导入路径: ``inkflow.core.database.ensure_provider_builtin_key_column``
     （落点 core/database.py，与 create_tables 并列）
   - 签名: ``def ensure_provider_builtin_key_column(conn) -> None`` —
     同步 callable，接收 SQLAlchemy sync Connection，配合
     ``await conn.run_sync(ensure_provider_builtin_key_column)`` 调用
     （与 ``create_tables`` 的 ``run_sync(Base.metadata.create_all)`` 同模式）
   - 语义: 幂等。表缺 ``builtin_key`` 列 → ``ALTER TABLE provider_configs
     ADD COLUMN builtin_key VARCHAR(50)``；列已存在 → no-op 不报错

2. 列契约: 列名 ``builtin_key``，**nullable**（旧行无值 → NULL，回填由
   seed 负责）；GREEN ORM 映射 ``Mapped[str | None]``
   ``mapped_column(String(50), nullable=True)``。

3. 旧库模拟: 测试手工 ``CREATE TABLE``（不含 builtin_key 列，其余列与
   ProviderConfigORM 一致）+ 插入 1 行旧数据，验证迁移后列存在且数据保留。

4. fixture: 本文件自带 in-memory SQLite engine fixture（unit 树 conftest
   无 DB fixture，镜像 test_provider_config_repo.py 模式）;
   ``import ProviderConfigORM`` 确保注册进 ``Base.metadata``
   （幂等用例的 create_all 才会建 provider_configs 表）。

5. RED 预期失败形态: 迁移函数不存在 → 模块级 import 失败 →
   本文件【收集期 ImportError】collected 0 items。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 实现迁移函数后本文件应全绿。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from inkflow.core.database import (
    Base,
    ensure_provider_builtin_key_column,  # RED 收集断言：函数不存在 → ImportError
)
from inkflow.infrastructure.database.models.provider_config import (  # noqa: F401  # 注册进 Base.metadata（幂等用例 create_all 用）
    ProviderConfigORM,
)


@pytest.fixture
async def engine():
    """独立 in-memory SQLite — 每个测试一个全新数据库（镜像 repo 测试 fixture）."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield eng
    await eng.dispose()


async def _create_legacy_provider_configs(conn) -> None:
    """模拟旧库: 手工建 provider_configs 表（无 builtin_key 列）+ 1 行旧数据."""
    await conn.execute(
        text(
            """
            CREATE TABLE provider_configs (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL UNIQUE,
                base_url VARCHAR(500),
                default_model VARCHAR(200),
                models JSON NOT NULL,
                max_retries INTEGER NOT NULL,
                timeout INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            INSERT INTO provider_configs
                (name, base_url, models, max_retries, timeout, created_at, updated_at)
            VALUES
                ('openai', 'https://api.openai.com/v1', '[]', 3, 120,
                 '2026-01-01 00:00:00', '2026-01-01 00:00:00')
            """
        )
    )


@pytest.mark.integration
class TestProviderBuiltinKeyMigration:
    """#126 A1 轻量列迁移契约 — 旧库加列 / 数据保留 / nullable / 幂等."""

    async def test_legacy_table_gets_column_and_keeps_data(self, engine):
        """旧库（无 builtin_key 列）迁移后: 列存在 + 既有数据保留."""
        async with engine.begin() as conn:
            await _create_legacy_provider_configs(conn)
            await conn.run_sync(ensure_provider_builtin_key_column)

            cols = (await conn.execute(text("PRAGMA table_info(provider_configs)"))).fetchall()
            col_names = [row[1] for row in cols]
            assert "builtin_key" in col_names, f"迁移后应含 builtin_key 列，实际列: {col_names}"

            names = (await conn.execute(text("SELECT name FROM provider_configs"))).scalars().all()
            assert names == ["openai"]  # 迁移不丢数据

    async def test_migrated_column_nullable_for_legacy_rows(self, engine):
        """旧行 builtin_key 为 NULL（nullable 列，回填由 seed 负责）."""
        async with engine.begin() as conn:
            await _create_legacy_provider_configs(conn)
            await conn.run_sync(ensure_provider_builtin_key_column)

            value = (
                await conn.execute(
                    text("SELECT builtin_key FROM provider_configs " "WHERE name = 'openai'")
                )
            ).scalar_one()
            assert value is None

    async def test_idempotent_when_column_exists(self, engine):
        """新库（create_all 已含列）→ 迁移 no-op 不报错（幂等）."""
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(ensure_provider_builtin_key_column)  # no-op

            cols = (await conn.execute(text("PRAGMA table_info(provider_configs)"))).fetchall()
            assert "builtin_key" in [row[1] for row in cols]

    async def test_noop_when_table_missing(self, engine):
        """#126 评审修复 🔴: 表不存在 → 迁移 no-op 不抛错.

        背景: lifespan 新增迁移调用打在真实全局 engine 上；CI 全新 runner
        无 provider_configs 表（test_health.py mock 了 create_tables 但未
        mock 迁移）→ 旧实现 ALTER 抛 ``OperationalError: no such table``
        → lifespan 启动失败（开发机只因本地 backend/inkflow.db 存在才通过）。

        契约: 全新 in-memory 库（不 create_all、不建表）上调用迁移 →
        正常返回 None 不抛异常；PRAGMA table_info 仍为空（未建表、
        未 ALTER）。宽容断言：只钉「表不存在不抛错」，不钉实现细节
        （PRAGMA 空判断 return / try-except 均合法）。
        """
        async with engine.begin() as conn:
            result = await conn.run_sync(ensure_provider_builtin_key_column)
            assert result is None  # 不抛异常（签名契约 -> None）

            cols = (await conn.execute(text("PRAGMA table_info(provider_configs)"))).fetchall()
            assert cols == []  # 附加断言: 未建表、未 ALTER（无副作用）
