"""AgentTemplate 业务服务 — 模板 CRUD + 默认模板 + 复制 + 删除级联清引用.

职责（spec §9.2/§9.3）:
- 模板 CRUD 编排：委托 AgentTemplateRepositoryProtocol
- 同名唯一性校验（422）: create 前 / update 改名时 / duplicate 命名时经
  repo.get_by_name 检查，命中 → AgentTemplateNameConflictError
- 资源不存在（404 语义）: get/update/set_default/duplicate/delete 目标缺失
  → AgentTemplateNotFoundError
- update 为 exclude_unset 浅合并（同 F1/F13）: None 值 = 不修改，予以剔除；
  仅 name 变更时查重；updated_at 刷新为 now(UTC)，created_at 保留
- set_default 委托 repo（单例由 repo 保证，服务层零逻辑）
- duplicate 复制模板：新 name = 指定名或「原名称 副本」；id/is_default/
  时间戳重置
- delete 级联：is_default=True（内置默认模板）→ AgentTemplateBuiltinError；
  被引用模板 → 先逐个清空项目 config.template_id（project_repository.update
  一次写，spec §9.2.4 评审 C2）再删除；repo.delete 返回 False → NotFound

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）。
"""

from __future__ import annotations

import builtins
import logging
from datetime import UTC, datetime

from inkflow.domain.models.agent_template import (
    AgentTemplate,
    AgentTemplateCreate,
    AgentTemplateUpdate,
)
from inkflow.domain.ports.agent_template_errors import (
    AgentTemplateBuiltinError,
    AgentTemplateNameConflictError,
    AgentTemplateNotFoundError,
)
from inkflow.domain.ports.agent_template_repository import AgentTemplateRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


class AgentTemplateService:
    """模板业务服务 — CRUD + 默认模板 + 复制 + 删除级联清引用.

    Args:
        template_repository: 模板仓储端口.
        project_repository: 项目仓储端口（删除级联清引用用）.
    """

    def __init__(
        self,
        *,
        template_repository: AgentTemplateRepositoryProtocol,
        project_repository: ProjectRepositoryProtocol,
    ) -> None:
        self._template_repo = template_repository
        self._project_repo = project_repository

    async def create(self, data: AgentTemplateCreate) -> AgentTemplate:
        """创建模板（同名冲突 → 422；id=None/is_default=False/时间戳由服务层填充）."""
        existing = await self._template_repo.get_by_name(data.name)
        if existing is not None:
            raise AgentTemplateNameConflictError()
        now = _utcnow()
        entity = AgentTemplate(
            id=None,
            name=data.name,
            description=data.description,
            main_model=data.main_model,
            default_temperature=data.default_temperature,
            roles=data.roles,
            default_words=data.default_words,
            is_default=False,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建模板: name=%s", data.name)
        return await self._template_repo.add(entity)

    async def get(self, template_id: int) -> AgentTemplate:
        """按主键获取模板；不存在 → AgentTemplateNotFoundError（404）."""
        template = await self._template_repo.get(template_id)
        if template is None:
            raise AgentTemplateNotFoundError()
        return template

    async def list(self) -> builtins.list[AgentTemplate]:
        """列出全部模板（按 name 升序，委托 repo）."""
        return await self._template_repo.list()

    async def update(self, template_id: int, data: AgentTemplateUpdate) -> AgentTemplate:
        """部分更新模板（exclude_unset 浅合并，同 F1/F13）.

        None 值 = 不修改（与未传入等价，合并前剔除）；name 变更时查重
        （命中其他 id → 422）；updated_at 刷新，created_at 保留；
        is_default=True 时单例由 repo.update 内部保证，服务层零逻辑。
        """
        existing = await self._template_repo.get(template_id)
        if existing is None:
            raise AgentTemplateNotFoundError()
        # 直接取已校验的字段值（避免 model_dump 将嵌套 RoleTemplate 摊平为 dict）
        updates = {
            k: getattr(data, k) for k in data.model_fields_set if getattr(data, k) is not None
        }
        if "name" in updates and updates["name"] != existing.name:
            dup = await self._template_repo.get_by_name(updates["name"])
            if dup is not None and dup.id != existing.id:
                raise AgentTemplateNameConflictError()
        merged = existing.model_copy(update=updates)
        merged.updated_at = _utcnow()
        logger.info("更新模板: template_id=%s", template_id)
        return await self._template_repo.update(merged)

    async def set_default(self, template_id: int) -> AgentTemplate:
        """将模板设为默认（单例由 repo 保证）；目标不存在 → NotFound（404）."""
        existing = await self._template_repo.get(template_id)
        if existing is None:
            raise AgentTemplateNotFoundError()
        result = await self._template_repo.set_default(template_id)
        if result is None:
            raise AgentTemplateNotFoundError()
        return result

    async def duplicate(self, template_id: int, *, name: str | None = None) -> AgentTemplate:
        """复制模板.

        新 name = 指定名或「原名称 副本」；查重命中 → NameConflictError；
        id/is_default/时间戳重置（副本不继承默认位，时间戳由服务层/ORM
        重新填充）。
        """
        template = await self._template_repo.get(template_id)
        if template is None:
            raise AgentTemplateNotFoundError()
        new_name = name or f"{template.name} 副本"
        existing = await self._template_repo.get_by_name(new_name)
        if existing is not None:
            raise AgentTemplateNameConflictError()
        clone = template.model_copy(
            update={
                "id": None,
                "name": new_name,
                "is_default": False,
                "created_at": None,
                "updated_at": None,
            }
        )
        logger.info("复制模板: template_id=%s → name=%s", template_id, new_name)
        return await self._template_repo.add(clone)

    async def delete(self, template_id: int) -> None:
        """删除模板.

        不存在 → NotFound（404）；is_default=True（内置默认模板）→
        AgentTemplateBuiltinError；被引用模板 → 先级联清空每个引用项目
        config.template_id（project_repository.update 一次写）再删除；
        repo.delete 返回 False（竞态已删）→ NotFound。
        """
        template = await self._template_repo.get(template_id)
        if template is None:
            raise AgentTemplateNotFoundError()
        if template.is_default:
            raise AgentTemplateBuiltinError()
        refs = await self._template_repo.list_projects_by_template(template_id)
        for project in refs:
            project.config.template_id = None
            await self._project_repo.update(project)
        if not await self._template_repo.delete(template_id):
            raise AgentTemplateNotFoundError()
        logger.info("删除模板: template_id=%s", template_id)
