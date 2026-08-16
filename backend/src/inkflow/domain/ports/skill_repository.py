"""Skill 仓储端口 — Skill 持久化出站契约.

SkillRepositoryProtocol 定义 Skill 的 CRUD 操作，基础设施层（SQLite /
mock / memory）实现此 Protocol。仓储层方法入参用 int（与 ORM 层一致），
list 返回领域 Skill 对象列表（非 dict）。

依据: specs/f39-multi-agent/spec.md §2.2 + §5.6。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.skill import Skill, SkillUpdate


class SkillRepositoryProtocol(Protocol):
    """Skill 仓储端口.

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9-F16）。
    """

    async def add(self, skill: Skill) -> Skill:
        """插入新 Skill（id 由 DB 自增分配；name 唯一冲突 → IntegrityError 冒出）."""
        ...

    async def get(self, skill_id: int) -> Skill | None:
        """按主键查询 Skill；不存在返回 None."""
        ...

    async def get_by_name(self, name: str) -> Skill | None:
        """按名称精确查询 Skill（同名唯一检测用）；不存在返回 None."""
        ...

    async def list(self) -> builtins.list[Skill]:
        """列出全部 Skill，按 name 升序."""
        ...

    async def update(self, skill_id: int, data: SkillUpdate) -> Skill | None:
        """按 id 部分更新 Skill（exclude_unset 合并；updated_at 刷新，created_at 保留）；
        不存在返回 None（builtin 只读保护在服务层）."""
        ...

    async def delete(self, skill_id: int) -> bool:
        """物理删除 Skill；不存在返回 False."""
        ...
