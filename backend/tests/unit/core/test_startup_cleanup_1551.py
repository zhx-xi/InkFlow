"""#1551 内核启动期暂存清理契约（RED）。

被测（GREEN 才实现）:
- ``inkflow.core.startup_cleanup.cleanup_expired_staging(session_factory, *,
  retention_days=STAGING_RETENTION_DAYS)`` → 删除 ``extract_staging`` 中 ``created_at``
  早于「当前 UTC − retention_days 天」的行，返回清理条数；幂等（第二次 0）；
  失败不阻塞启动（吞异常 + WARNING 日志，返回 0）。

依据: specs/f14-extraction/spec.md §5.9（#1551，0.17.0 W8c）。

RED 预期: ``inkflow.core.startup_cleanup`` 模块尚不存在 → 函数内 import 抛
``ModuleNotFoundError`` → 用例 FAIL（文件可收集，非收集期 error）。

注: 暂存行 ``created_at`` 由 ORM 默认工厂写「当前时刻」——为构造超期行，本文件直接
插入 ORM 行并显式指定 ``created_at``（不经 ``add_many``）；不用真实 30 天等待。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from loguru import logger as loguru_logger
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.infrastructure.database.models.extract_staging import ExtractStagingORM
from inkflow.infrastructure.database.models.project import ProjectORM


@pytest.fixture
async def db_factory() -> async_sessionmaker[AsyncSession]:
    """独立 in-memory SQLite 的 session 工厂（启用 FK；每测试全新库）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed(factory: async_sessionmaker[AsyncSession], ages_days: list[int]) -> None:
    """按「年龄天数」构造暂存行（正数 = 超期候选，0/负 = 未超期）。"""
    async with factory() as session:
        project = ProjectORM(name="测试项目")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        now = datetime.now(UTC)
        for i, age in enumerate(ages_days):
            session.add(
                ExtractStagingORM(
                    project_id=project.id,
                    batch_id=f"b{i}",
                    type="character",
                    entity_type="character",
                    action="create",
                    payload="{}",
                    created_at=now - timedelta(days=age),
                )
            )
        await session.commit()


async def _total(factory: async_sessionmaker[AsyncSession]) -> int:
    """直接查表统计暂存行总数（绕过待测代码，印证持久化真相）。"""
    async with factory() as session:
        result = await session.execute(select(func.count()).select_from(ExtractStagingORM))
        return result.scalar_one()


@pytest.mark.integration
class TestCleanupExpiredStaging:
    """启动期暂存清理（#1551，spec §5.9）。"""

    async def test_removes_expired_keeps_recent(self, db_factory) -> None:
        """超期行被清、未超期行保留（默认 30 天口径）。"""
        from inkflow.core.startup_cleanup import cleanup_expired_staging

        await _seed(db_factory, [40, 1])  # 40 天（超期） + 1 天（保留）

        deleted = await cleanup_expired_staging(db_factory)

        assert deleted == 1
        assert await _total(db_factory) == 1  # 未超期行仍在

    async def test_is_idempotent(self, db_factory) -> None:
        """幂等：连续触发两次 → 第二次 0 删除、0 报错。"""
        from inkflow.core.startup_cleanup import cleanup_expired_staging

        await _seed(db_factory, [40])

        assert await cleanup_expired_staging(db_factory) == 1
        assert await cleanup_expired_staging(db_factory) == 0
        assert await _total(db_factory) == 0

    async def test_noop_when_nothing_expired(self, db_factory) -> None:
        """无超期行 → 0、不报错、行不受影响。"""
        from inkflow.core.startup_cleanup import cleanup_expired_staging

        await _seed(db_factory, [1, 29])  # 均在 30 天窗口内

        assert await cleanup_expired_staging(db_factory) == 0
        assert await _total(db_factory) == 2

    async def test_threshold_is_configurable(self, db_factory) -> None:
        """阈值可配：retention_days 覆盖默认 → 判定边界随参数变。"""
        from inkflow.core.startup_cleanup import cleanup_expired_staging

        await _seed(db_factory, [5])  # 5 天

        # 阈值 3 天 → 5 天行超期被清
        assert await cleanup_expired_staging(db_factory, retention_days=3) == 1
        assert await _total(db_factory) == 0


@pytest.mark.unit
class TestCleanupFailureDoesNotBlockStartup:
    """清理失败不阻塞启动（吞异常 + WARNING 日志）。"""

    async def test_failure_returns_zero_and_logs_warning(self) -> None:
        """session 工厂抛错 → 吞掉、返回 0、记 WARNING（不向上传播）。"""
        from typing import Any, cast

        from inkflow.core.startup_cleanup import cleanup_expired_staging

        def _boom():  # 模拟取 session 即失败（DB 不可用）
            raise RuntimeError("db down")

        records: list[str] = []
        sink_id = loguru_logger.add(lambda msg: records.append(msg), level="WARNING")
        try:
            assert await cleanup_expired_staging(cast("Any", _boom)) == 0
        finally:
            loguru_logger.remove(sink_id)

        assert any("暂存" in r for r in records)
