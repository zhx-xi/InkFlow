"""#953 内核启动对账：重启后把 writing_plans 遗留 running 态置为 failed，
独立成文件以避免 database.py 突破 900 行护栏。"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def reconcile_stale_running_plans(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """内核启动对账：#953——重启后 writing_plans 遗留 running 态 → failed。

    book run 崩溃/进程被杀后，writing_plans.status 停在 'running'，重启会以 422
    「存在进行中的」挡掉重跑（黑洞：永久挂起无异常时无终态映射可走）。本函数在
    lifespan seed 之后调用：把 running 行置为 failed 并写 progress_reason，释放
    重跑名额；ready 及其它终态不动。返回处理行数。
    """
    reason = "内核重启对账：运行遗留 running 态（#953）"
    async with session_factory() as session:
        result = await session.execute(
            text(
                "UPDATE writing_plans SET status = 'failed', progress_reason = :reason "
                "WHERE status = 'running'"
            ),
            {"reason": reason},
        )
        await session.commit()
    # rowcount 仅在 DML 的 CursorResult 上存在；静态类型以 Result[Any] 呈现，cast 对齐
    return int(cast(CursorResult[Any], result).rowcount or 0)
