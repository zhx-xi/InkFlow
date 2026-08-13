"""项目业务服务 — 编排核心业务逻辑.

将数据访问委托给 SQLiteProjectRepository，同时处理领域层的转换逻辑
（如 UUID ↔ int ID 转换）和部分更新合并。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from inkflow.domain.models.project import Genre, Project, ProjectConfig, ProjectUpdate
from inkflow.infrastructure.database.repositories.project_repo import (
    SQLiteProjectRepository,
)

logger = logging.getLogger(__name__)


def _validate_agent_order_config(config: ProjectConfig) -> None:
    """配置驱动模式语义校验（C1，spec §2.3/§7）：agent_order 非空时必须包含全部启用角色。

    - agent_order 空（默认模板模式）→ 直接返回（不校验，B1 零迁移）
    - 非空（配置驱动模式）→ 启用角色 = 内置 agent_* 非 null ∪ agent_roles 非 null
      （F42 #295，spec §5.3.4 第 4 点；agent_roles key 已带 agent_ 前缀）：
      - 启用集合为空 → ValueError（至少 1 个启用角色）
      - order 展开集缺启用角色 → ValueError（消息含缺失字段名，内置四角色按
        声明序、自定义角色按字段序追加，逗号+空格连接）
    """
    if not config.agent_order:
        return
    enabled_roles = {
        field
        for field in ("agent_architect", "agent_writer", "agent_auditor", "agent_reviser")
        if getattr(config, field) is not None
    }
    # F42 #295：自定义角色启用口径 = agent_roles 非 null 的 key（带前缀，直接并入）
    for field, value in (config.agent_roles or {}).items():
        if value is not None:
            enabled_roles.add(field)
    if not enabled_roles:
        raise ValueError("配置驱动模式至少需要 1 个启用角色")
    order_roles = {role for layer in config.agent_order for role in layer}
    # 缺失字段名按角色字段声明序（architect/writer/auditor/reviser）输出——
    # 与 UI/模板角色顺序一致（契约断言锚定首个缺失角色，如 agent_writer）
    missing: list[str] = [
        field
        for field in ("agent_architect", "agent_writer", "agent_auditor", "agent_reviser")
        if field in enabled_roles and field not in order_roles
    ]
    # 自定义角色（agent_roles）追加在末尾（无固定声明序，按字段序输出）
    for field in config.agent_roles or {}:
        if field in enabled_roles and field not in order_roles and field not in missing:
            missing.append(field)
    if missing:
        raise ValueError(f"agent_order 必须包含全部启用角色: {', '.join(missing)}")


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _to_int_id(project_id: int | uuid.UUID) -> int:
    """将 Project 的 UUID id 转换为数据库的 int id.

    Project 实体使用 uuid.UUID 作为 id 类型（_orm_to_domain 将 int PK
    转换为 UUID），但基础设施层的仓储方法接受 int 参数。
    """
    if isinstance(project_id, uuid.UUID):
        return project_id.int
    return project_id


class ProjectService:
    """项目业务服务 — 编排核心业务逻辑.

    所有方法均委托给 SQLiteProjectRepository，仅在必要时进行领域层转换。

    Args:
        db_session: SQLAlchemy 异步 session.
        map_cleanup: 项目硬删钩子（F36 D10=b）：项目硬删后清理地图与 pin
            （MapService.cleanup_project）；失败仅 log warning 不阻断主流程.
    """

    def __init__(
        self,
        db_session,
        *,
        map_cleanup: Callable[[int], Awaitable[int]] | None = None,
    ) -> None:
        self._repo = SQLiteProjectRepository(db_session)
        self._map_cleanup = map_cleanup

    async def create_project(
        self,
        name: str,
        genre: Genre = Genre.QITA,
        language: str = "zh-CN",
        target_words: int = 0,
        config: ProjectConfig | None = None,
    ) -> Project:
        """创建一个新项目。

        Args:
            name: 项目名称.
            genre: 小说分类，默认为 QITA（其他）.
            language: 写作语言，默认为 zh-CN.
            target_words: 目标字数，默认为 0（不限）.
            config: AI 写作配置，默认为空配置.

        Returns:
            持久化后的完整 Project（含数据库分配的 id）.
        """
        project = Project(
            id=uuid.uuid4(),
            name=name,
            genre=genre,
            language=language,
            target_words=target_words,
            config=config or ProjectConfig(),
            is_deleted=False,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        return await self._repo.add(project)

    async def get(self, project_id: int | uuid.UUID) -> Project | None:
        """根据主键获取项目（排除软删除记录）.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.

        Returns:
            若找到则返回 Project，否则返回 None.
        """
        return await self._repo.get(_to_int_id(project_id))

    async def list_projects(
        self,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Project], int]:
        """分页列举项目，支持搜索、排序。

        Args:
            search: 按名称模糊搜索（icontains），None 表示不过滤.
            sort_by: 排序字段，默认为 updated_at.
            sort_desc: 是否降序排列，默认为 True.
            offset: 偏移量，默认为 0.
            limit: 每页条数，默认为 50.

        Returns:
            (当前页项目列表, 符合条件的总记录数).
        """
        return await self._repo.list_all(search, sort_by, sort_desc, offset, limit)

    async def update(self, project_id: int | uuid.UUID, dto: ProjectUpdate) -> Project | None:
        """部分更新项目。

        先获取现有项目，合并传入的更新字段，再持久化。

        Args:
            project_id: 项目主键（支持 int 或 UUID）.
            dto: 包含待更新字段的 ProjectUpdate DTO.

        Returns:
            更新后的完整 Project，若项目不存在则返回 None.
        """
        existing = await self._repo.get(_to_int_id(project_id))
        if existing is None:
            return None
        updates = dto.model_dump(exclude_unset=True)
        config_updates = updates.get("config")
        if isinstance(config_updates, dict):
            updates["config"] = existing.config.model_copy(update=config_updates)
        updated = existing.model_copy(update=updates)
        # C1：合并后语义校验（配置驱动模式必须包含全部启用角色）→ ValueError 由 router 转 422
        _validate_agent_order_config(updated.config)
        return await self._repo.update(updated)

    async def soft_delete(self, project_id: int | uuid.UUID) -> bool:
        """软删除项目（标记 is_deleted=True）.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.

        Returns:
            True 表示成功删除一条记录，False 表示未找到记录.
        """
        return await self._repo.soft_delete(_to_int_id(project_id))

    async def restore(self, project_id: int | uuid.UUID) -> Project | None:
        """恢复软删除的项目（设置 is_deleted=False）.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.

        Returns:
            恢复后的 Project，若记录不存在则返回 None.
        """
        return await self._repo.restore(_to_int_id(project_id))

    async def hard_delete(self, project_id: int | uuid.UUID) -> bool:
        """物理删除项目（从数据库中永久移除）.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.

        Returns:
            True 表示成功删除一条记录，False 表示未找到记录.
        """
        pid_int = _to_int_id(project_id)
        deleted = await self._repo.hard_delete(pid_int)
        if deleted and self._map_cleanup is not None:
            try:
                await self._map_cleanup(pid_int)
            except Exception:
                logger.warning("项目硬删后地图清理失败: %s", project_id, exc_info=True)
        return deleted
