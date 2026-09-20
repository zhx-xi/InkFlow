"""#953 内核启动对账：重启后把 writing_plans 遗留 running 态置为 failed，
独立成文件以避免 database.py 突破 900 行护栏。

#1317：对账加**实例归属判据**——多内核并存时，新实例 lifespan 不得把别实例正在跑的
run 打成 failed（rc4 实测误伤）。归属载体 = ``writing_plans.limits['kernel_owner_pid']``
（int pid，零迁移；写入点在 domain/services/book_run_mixin.py 的 run 落库前）。
存活判据经关键字参数注入（``is_alive``）：core/ 不 import infrastructure（分层门禁）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

REASON_953 = "内核重启对账：运行遗留 running 态（#953）"

_OWNER_KEY = "kernel_owner_pid"
"""归属键名（与 domain/services/book_run_mixin.py 的 KERNEL_OWNER_PID_KEY 同键；
core 层不 import domain/infrastructure，故此处独立持常量）。"""


def _owner_pid(raw_limits: Any) -> int | None:
    """从 DB 原始 ``limits`` JSON 值解析归属 pid；无 owner / 畸形 → None。

    🔴 严格类型判据 ``type(v) is int``：``True`` 是 ``int`` 子类，若用 ``isinstance``
    会把 bool 当 pid=1 去探测存活 → 结果取决于机器上 pid 1 是否存在（不可判定）。
    契约要求 bool / None / 字符串等畸形值一律归入「无 owner」（确定性行为）。

    Args:
        raw_limits: 原始列值（SQLite JSON 列 → 文本；空串/损坏 JSON 由容错分支兜底）.

    Returns:
        合法 int pid；否则 None.
    """
    if not isinstance(raw_limits, str) or not raw_limits.strip():
        return None
    try:
        parsed = json.loads(raw_limits)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    owner = parsed.get(_OWNER_KEY)
    return owner if type(owner) is int else None


def _should_release(raw_limits: Any, is_alive: Callable[[int], bool] | None) -> bool:
    """判据（#1317 契约表逐条）：True = 释放（置 failed）；False = 保留 running。

    - owner 缺失 / 畸形 → 释放（历史遗留行保持 #953 原行为）
    - ``is_alive is None``（无法判定存活）→ 全部释放（#953 重启语义向后兼容）
    - owner 存活 → 不碰；owner 已死（含他实例崩溃遗留）→ 释放
    """
    owner = _owner_pid(raw_limits)
    if owner is None or is_alive is None:
        return True
    return not is_alive(owner)


async def reconcile_stale_running_plans(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    is_alive: Callable[[int], bool] | None = None,
) -> int:
    """内核启动对账：#953——重启后 writing_plans 遗留 running 态 → failed。

    book run 崩溃/进程被杀后，writing_plans.status 停在 'running'，重启会以 422
    「存在进行中的」挡掉重跑（黑洞：永久挂起无异常时无终态映射可走）。本函数在
    lifespan seed 之后调用：把 running 行置为 failed 并写 progress_reason，释放
    重跑名额；ready 及其它终态不动。返回处理行数。

    #1317 实例归属：仅释放「无归属 / 归属无法判定 / 归属进程已死」的 running 行，
    归属进程仍存活的行（别实例正在跑的 run）原样保留，防跨实例误伤。

    兼容语义：
    - owner 缺失 → 保持现行为置 failed（修复只对**新增**运行生效，历史残留仍能释放）。
    - ``is_alive=None``（默认，不可判定存活）→ 全部释放（#953 重启释放语义不变）。
    - reset_run / 终态不必清 owner（回收只作用于 status='running'）。

    Args:
        session_factory: 应用级异步 session 工厂.
        is_alive: 进程存活判据（注入 ``infrastructure.kernel.state.is_process_alive``）；
            缺省 None = 不可判定 → 全部释放.

    Returns:
        实际置为 failed 的行数（0 = 无可释放行）.
    """
    async with session_factory() as session:
        # 先取 id + limits 再按归属选择性释放：用 raw SQL 而非 ORM —— core/ 不 import
        # infrastructure（ORM 模型所在层），且归属键在 JSON 列内需 Python 侧解析。
        rows = (
            await session.execute(
                text("SELECT id, limits FROM writing_plans WHERE status = 'running'")
            )
        ).all()
        release_ids = [str(row[0]) for row in rows if _should_release(row[1], is_alive)]
        if not release_ids:
            return 0
        result = await session.execute(
            text(
                "UPDATE writing_plans SET status = 'failed', progress_reason = :reason "
                "WHERE status = 'running' AND id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"reason": REASON_953, "ids": release_ids},
        )
        await session.commit()
    # rowcount 仅在 DML 的 CursorResult 上存在；静态类型以 Result[Any] 呈现，cast 对齐
    return int(cast(CursorResult[Any], result).rowcount or 0)
