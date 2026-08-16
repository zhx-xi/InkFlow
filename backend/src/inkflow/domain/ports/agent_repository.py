"""Agent 仓储端口 — Agent 持久化出站契约.

AgentRepositoryProtocol 定义 Agent 的 CRUD 操作与 skill 反向查询
（list_agents_by_skill：删除 Skill 级联清引用反查用），基础设施层
（SQLite / mock / memory）实现此 Protocol。仓储层方法入参用 int（与
ORM 层一致），list / list_agents_by_skill 返回领域 Agent 对象列表
（非 dict）。

依据: specs/f39-multi-agent/spec.md §2.1 + §5.6。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.agent import Agent, AgentUpdate


class AgentRepositoryProtocol(Protocol):
    """Agent 仓储端口.

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9-F16）。
    """

    async def add(self, agent: Agent) -> Agent:
        """插入新 Agent（id 由 DB 自增分配；name 唯一冲突 → IntegrityError 冒出）."""
        ...

    async def get(self, agent_id: int) -> Agent | None:
        """按主键查询 Agent；不存在返回 None."""
        ...

    async def get_by_name(self, name: str) -> Agent | None:
        """按名称精确查询 Agent（同名唯一检测用）；不存在返回 None."""
        ...

    async def list(self) -> builtins.list[Agent]:
        """列出全部 Agent，按 name 升序."""
        ...

    async def update(self, agent_id: int, data: AgentUpdate) -> Agent | None:
        """按 id 部分更新 Agent（exclude_unset 合并；updated_at 刷新，created_at 保留）；
        不存在返回 None（builtin 只读保护在服务层）."""
        ...

    async def delete(self, agent_id: int) -> bool:
        """物理删除 Agent；不存在返回 False."""
        ...

    async def list_agents_by_skill(self, skill_id: int) -> builtins.list[Agent]:
        """列出引用指定 Skill 的 Agent（skill_ids 精确含 str(skill_id)），
        按 name 升序（删除 Skill 级联清引用反查用）."""
        ...
