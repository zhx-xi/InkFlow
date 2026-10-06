"""#1481 建项目自动建根钩子装配（自 `api/deps.py` 拆出，900 行护栏）.

`ProjectService.root_initializer` 的工厂：延迟构造 `WorldService`（非创建端点零开销），
并让 `deps.py` 不必内联 world 域细节。钩子入参 = 新建项目的领域 UUID。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession


def make_world_root_initializer(db: AsyncSession) -> Callable[[uuid.UUID], Awaitable[object]]:
    """返回「建项目自动建根」钩子（#1481，specs/f35-world-tree §5.7）.

    调用 `WorldService.ensure_root_setting`：有根原样返回、无根建默认根
    「世界观总纲」（`parent_id=None`、`category=""`）。

    Args:
        db: 与项目创建同一请求的 session（同事务语义；路由 `Depends(get_db)`）。

    Returns:
        `Callable[[uuid.UUID], Awaitable[WorldSetting]]` —— 供
        `ProjectService(..., root_initializer=...)` 注入。
    """

    async def _seed_world_root(project_id: uuid.UUID) -> object:
        # 延迟 import：避免 api.deps ←→ api.deps_world_root 模块级循环
        from inkflow.api.deps import get_world_service

        return await get_world_service(db).ensure_root_setting(project_id)

    return _seed_world_root
