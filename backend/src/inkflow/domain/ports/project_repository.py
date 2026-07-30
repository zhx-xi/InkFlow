"""
项目仓储端口 — 定义领域层与基础设施层之间的契约.

ProjectRepositoryProtocol 使用 typing.Protocol 实现结构化子类型（static duck typing），
基础设施层（SQLAlchemy / mock / memory）实现这些方法即可自动满足接口要求。
"""

from typing import Protocol

from inkflow.domain.models.project import Project


class ProjectRepositoryProtocol(Protocol):
    """项目仓储端口 — 定义持久化操作的契约."""

    async def add(self, project: Project) -> Project:
        """新增项目.

        Args:
            project: 待创建的项目实体.

        Returns:
            持久化后的完整 Project（含 id, created_at 等自动生成字段）.
        """
        ...

    async def get(self, project_id: int) -> Project | None:
        """根据主键获取项目（排除软删除记录）.

        Args:
            project_id: 项目主键.

        Returns:
            若找到且 is_deleted=False 则返回 Project，否则返回 None.
        """
        ...

    async def list_all(
        self,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Project], int]:
        """分页列举项目，支持搜索、排序.

        Args:
            search: 按名称模糊搜索（icontains），None 表示不过滤.
            sort_by: 排序字段，默认为 updated_at.
            sort_desc: 是否降序排列，默认为 True.
            offset: 偏移量，默认为 0.
            limit: 每页条数，默认为 50.

        Returns:
            (当前页项目列表, 符合条件的总记录数).
        """
        ...

    async def update(self, project: Project) -> Project:
        """更新项目.

        Args:
            project: 包含新数据的项目实体（主键 id 标识待更新行）.

        Returns:
            更新后的完整 Project.
        """
        ...

    async def soft_delete(self, project_id: int) -> bool:
        """软删除项目（标记 is_deleted=True）.

        Args:
            project_id: 待删除的项目主键.

        Returns:
            True 表示成功删除一条记录，False 表示未找到记录.
        """
        ...

    async def restore(self, project_id: int) -> Project | None:
        """恢复软删除的项目（设置 is_deleted=False）.

        Args:
            project_id: 待恢复的项目主键.

        Returns:
            恢复后的 Project，若记录不存在则返回 None.
        """
        ...

    async def hard_delete(self, project_id: int) -> bool:
        """物理删除项目（从数据库中永久移除）.

        Args:
            project_id: 待删除的项目主键.

        Returns:
            True 表示成功删除一条记录，False 表示未找到记录.
        """
        ...
