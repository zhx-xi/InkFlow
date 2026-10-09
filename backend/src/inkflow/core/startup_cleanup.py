"""#1551 内核启动期暂存清理：清理超期未确认的提取暂存行（spec §5.9）.

复用 #953 ``reconcile_stale_running_plans`` 的**启动期幂等维护范式**：内核 lifespan
启动时（``reconcile_stale_running_plans`` 之后、scheduler 之前）执行一次，幂等、返回
清理条数、**失败不阻塞启动**。本仓无真定时器范式，故不引入调度库（AGENTS §10.2 简单优先）。

独立成文件（同 ``startup_reconcile.py`` 拆分先例），避免 ``core/database.py`` 体积膨胀。
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

STAGING_RETENTION_DAYS = 30
"""暂存行过期阈值（天）——对齐软删 30 天纪律（spec §5.9；阈值走代码常量）。"""


async def cleanup_expired_staging(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    retention_days: int = STAGING_RETENTION_DAYS,
) -> int:
    """清理超期未确认的提取暂存行（#1551，spec §5.9）——启动期幂等维护.

    删除 ``created_at`` 早于「当前 UTC − ``retention_days`` 天」的 ``extract_staging``
    行，返回清理条数并落日志（有清理才记 INFO）。**失败不阻塞启动**：任何异常被吞并
    记 WARNING（同 scheduler shutdown 吞异常约定）。

    #1551：core/ 不 import infrastructure（分层门禁）——仓储经函数内**惰性 import**
    （先例 ``core/log.py`` 惰性 import ``infrastructure.kernel``）。

    Args:
        session_factory: 应用级异步 session 工厂（lifespan 提供）.
        retention_days: 过期阈值天数（默认 ``STAGING_RETENTION_DAYS`` = 30）.

    Returns:
        实际清理的行数（无超期行 / 失败 → 0）.
    """
    from inkflow.infrastructure.database.repositories.extract_staging_repo import (
        SQLExtractStagingRepository,
    )

    try:
        async with session_factory() as session:
            deleted = await SQLExtractStagingRepository(session).delete_expired(retention_days)
    except Exception:  # 启动期维护：任何失败吞掉，不得阻塞内核启动
        logger.opt(exception=True).warning("提取暂存行过期清理失败（不阻塞启动）")
        return 0
    if deleted:
        logger.info("清理超期提取暂存行 {} 条（阈值 {} 天）", deleted, retention_days)
    return deleted
