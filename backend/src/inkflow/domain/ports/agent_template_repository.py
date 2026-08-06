"""AgentTemplate 仓储端口 — 模板持久化契约.

AgentTemplateRepositoryProtocol 定义 AgentTemplate 的 CRUD 操作、默认模板
单例（set_default）与引用查询（list_projects_by_template），基础设施层
（SQLite / mock / memory）实现此 Protocol。仓储层方法入参用 int（与 ORM
层一致），list_projects_by_template 返回领域 Project 对象列表（非 dict）。

依据: specs/f19-gui/spec.md §9.2。
"""

from __future__ import annotations

import builtins
from typing import Protocol

from inkflow.domain.models.agent_template import AgentTemplate
from inkflow.domain.models.project import Project


class AgentTemplateRepositoryProtocol(Protocol):
    """模板仓储端口.

    注: 类内方法名 ``list`` 会在 mypy 类作用域解析中遮蔽内置 ``list``，
    因此返回注解中的列表类型统一写作 ``builtins.list[...]``（同 F9-F16）。
    """

    async def add(self, at: AgentTemplate) -> AgentTemplate:
        """插入新模板（id 由 DB 自增分配；name 唯一冲突 → IntegrityError 冒泡）."""
        ...

    async def get(self, template_id: int) -> AgentTemplate | None:
        """按主键查询模板；不存在返回 None."""
        ...

    async def get_by_name(self, name: str) -> AgentTemplate | None:
        """按名称精确查询模板（同名唯一检查用）；不存在返回 None."""
        ...

    async def list(self) -> builtins.list[AgentTemplate]:
        """列出全部模板，按 name 升序."""
        ...

    async def update(self, at: AgentTemplate) -> AgentTemplate:
        """按 id 全量更新模板字段（updated_at 刷新，created_at 保留）；不存在 → ValueError."""
        ...

    async def delete(self, template_id: int) -> bool:
        """物理删除模板；不存在返回 False."""
        ...

    async def set_default(self, template_id: int) -> AgentTemplate | None:
        """将指定模板设为默认（其他行自动降级 False，单例）；不存在返回 None."""
        ...

    async def list_projects_by_template(self, template_id: int) -> builtins.list[Project]:
        """列出引用指定模板的项目（config JSON template_id 精确匹配，排除软删，按 name 升序）."""
        ...
