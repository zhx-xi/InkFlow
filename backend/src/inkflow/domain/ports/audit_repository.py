"""审计软删集合补充查询端口 — 一致性审计持久化契约.

AuditRepositoryProtocol 定义审计特有的软删集合读取（list_deleted），
基础设施层（SQLiteAuditRepository，infrastructure/database/repositories/
audit_repo.py）实现此 Protocol。各模块既有 Protocol 查询默认不含软删
（list/list_relations/list_groups/view 均为活动数据），而审计的
「软删 → warning」分级（R-C1/R-C2/R-F1）需要软删集合——本端口承载该
审计特有读取需求，不改动任何既有 Protocol/仓储（零跨模块 MODIFY）。

注: F2 章节无软删概念（硬删除），本端口不提供章节软删查询（spec §5.5 注）。

依据: specs/f15-audit-service/spec.md §8.2。
"""

from __future__ import annotations

import builtins
from typing import Protocol


class AuditRepositoryProtocol(Protocol):
    """审计软删集合补充查询端口（spec §5.1 注/§5.4）.

    各模块既有 Protocol 查询默认不含软删（list/list_relations/list_groups/
    view 均为活动数据），而审计的「软删 → warning」分级（R-C1/R-C2/R-F1）
    需要软删集合——本端口承载该审计特有读取需求，由 F15 自有实现
    （infrastructure/database/repositories/audit_repo.py）提供，不改动
    任何既有 Protocol/仓储（零跨模块 MODIFY）。

    注: F2 章节无软删概念（硬删除），本端口不提供章节软删查询（§5.5 注）。
    """

    async def list_deleted(
        self, project_id: int
    ) -> tuple[builtins.list[int], builtins.list[int], builtins.list[int]]:
        """列出项目内三类软删实体 id（角色 / 分组 / 事件）.

        Args:
            project_id: 项目主键（int，与 ORM 层一致）.

        Returns:
            (软删角色 ids, 软删分组 ids, 软删事件 ids) 三元组——
            分别来自 characters / character_groups / timeline_events 表的
            is_deleted=1 行（按 project_id 过滤）.
        """
        ...
