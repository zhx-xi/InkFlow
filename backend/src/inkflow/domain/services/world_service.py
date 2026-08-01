"""F10 世界观业务服务 — 编排条目 CRUD + AI 提取入口.

职责（spec §7/§9）:
- 条目 CRUD 编排：委托 WorldRepositoryProtocol，负责领域层
  UUID ↔ 仓储层 int 转换（沿用 F1 `_to_int_id` 模式）
- 业务校验（422 语义，抛 WorldServiceError 子类）: 同名活动条目
- 资源不存在（404 语义）: 多数方法返回 None 由 router 层转 404
- AI 提取入口（§5.1 步骤 ①）: 校验项目存在并取 project.config.model 作为
  默认模型，再委托 WorldExtractor 执行管线（②-⑦）

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:
- repository: WorldRepositoryProtocol（B1/B2 已实现）
- extractor: WorldExtractor（B2 已实现）
- project_repo: ProjectRepositoryProtocol（F1 已实现，extract 入口校验用）

依据: specs/f10-world-service/spec.md §6/§7/§9。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from inkflow.domain.models.world import (
    WorldExtractionResult,
    WorldExtractRequest,
    WorldSetting,
    WorldUpdate,
)
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_errors import (
    ProjectNotFoundError,
    WorldNameConflictError,
    WorldServiceError,
)
from inkflow.domain.ports.world_repository import WorldRepositoryProtocol
from inkflow.domain.services._world_extractor import WorldExtractor

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1 `_to_int_id` 模式）."""
    if isinstance(value, uuid.UUID):
        return value.int
    return value


class WorldService:
    """世界观业务服务 — 编排条目 CRUD 与 AI 提取.

    Args:
        repository: 世界观条目仓储端口（B1）.
        extractor: 世界观提取管线（B2）；deps.py 负责组装，默认 None 时
            extract 入口报错（防止静默降级）.
        project_repo: 项目仓储（F1），extract 入口校验项目存在并读取默认模型.
    """

    def __init__(
        self,
        *,
        repository: WorldRepositoryProtocol,
        extractor: WorldExtractor | None = None,
        project_repo: ProjectRepositoryProtocol | None = None,
    ) -> None:
        self._repo = repository
        self._extractor = extractor
        self._project_repo = project_repo

    # ── WorldSetting ─────────────────────────────────────────────

    async def create_setting(
        self,
        project_id: uuid.UUID,
        name: str,
        category: str = "",
        content: str = "",
    ) -> WorldSetting:
        """创建世界观条目（spec §7: 同名活动条目 → 422）.

        Args:
            project_id: 所属项目 UUID（router 解析路径参数后传入）.
            name: 条目名（WorldCreate 已去空白校验）.
            category: 类别（空串 = 未分类）.
            content: 条目内容.

        Returns:
            持久化后的完整 WorldSetting.

        Raises:
            WorldNameConflictError: 项目内已存在同名活动条目.
        """
        pid_int = _to_int_id(project_id)
        existing = await self._repo.get_by_name(pid_int, name)
        if existing is not None:
            raise WorldNameConflictError()
        now = _utcnow()
        setting = WorldSetting(
            id=uuid.uuid4(),
            project_id=project_id,
            name=name,
            category=category,
            content=content,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建世界观条目: project=%s name=%s", project_id, name)
        return await self._repo.add(setting)

    async def get_setting(self, setting_id: int | uuid.UUID) -> WorldSetting | None:
        """按主键获取条目（不含已软删除）；不存在返回 None（router 转 404）."""
        return await self._repo.get(_to_int_id(setting_id))

    async def list_settings(
        self,
        project_id: int | uuid.UUID,
        search: str | None = None,
        category: str | None = None,
        sort_by: str = "updated_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[WorldSetting], int]:
        """分页查询项目内条目列表，支持搜索、类别过滤、排序.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.
            search: 条目名模糊搜索（可选）.
            category: 类别精确过滤（可选；空串查询未分类条目）.
            sort_by: 排序字段（updated_at / name / created_at）.
            sort_desc: 是否倒序.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (当前页条目列表, 符合条件的总记录数).
        """
        return await self._repo.list(
            project_id=_to_int_id(project_id),
            search=search,
            category=category,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )

    async def list_categories(self, project_id: int | uuid.UUID) -> list[tuple[str, int]]:
        """聚合项目内活动条目的类别计数（排除空类别）.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.

        Returns:
            (类别, 条目数) 列表，按计数降序、类别名升序.
        """
        return await self._repo.list_categories(_to_int_id(project_id))

    async def update_setting(
        self, setting_id: int | uuid.UUID, update: WorldUpdate
    ) -> WorldSetting | None:
        """部分更新条目（exclude_unset 语义，同 F1）.

        业务校验（spec §7）: 改名撞项目内其他活动条目 → 422。
        category 显式置 None 表示不修改；"" 表示清除类别（置为未分类）。

        Args:
            setting_id: 条目主键（支持 int 或 UUID）.
            update: 含待更新字段的 WorldUpdate DTO.

        Returns:
            更新后的完整 WorldSetting；条目不存在返回 None（router 转 404）.
        """
        sid = _to_int_id(setting_id)
        existing = await self._repo.get(sid)
        if existing is None:
            return None
        if "name" in update.model_fields_set and update.name is not None:
            dup = await self._repo.get_by_name(_to_int_id(existing.project_id), update.name)
            if dup is not None and dup.id != existing.id:
                raise WorldNameConflictError()
        updates = {k: v for k, v in update.model_dump(exclude_unset=True).items() if v is not None}
        merged = existing.model_copy(update=updates)
        logger.info("更新世界观条目: setting_id=%s", setting_id)
        return await self._repo.update(merged)

    async def delete_setting(self, setting_id: int | uuid.UUID, force: bool = False) -> bool:
        """删除条目（spec §7: 条目不存在 → False，router 转 404）.

        Args:
            setting_id: 条目主键（支持 int 或 UUID）.
            force: True 物理删除；False（默认）软删除.

        Returns:
            True 表示删除成功；False 表示未找到记录.
        """
        sid = _to_int_id(setting_id)
        if force:
            logger.info("硬删除世界观条目: setting_id=%s", setting_id)
            return await self._repo.hard_delete(sid)
        logger.info("软删除世界观条目: setting_id=%s", setting_id)
        return await self._repo.soft_delete(sid)

    async def restore_setting(self, setting_id: int | uuid.UUID) -> WorldSetting | None:
        """恢复软删除条目.

        Args:
            setting_id: 条目主键（支持 int 或 UUID）.

        Returns:
            恢复后的 WorldSetting；条目不存在/未删除返回 None（重复操作无毒，同 F1）.
        """
        sid = _to_int_id(setting_id)
        restored = await self._repo.restore(sid)
        if restored is not None:
            logger.info("恢复世界观条目: setting_id=%s", setting_id)
        return restored

    # ── AI 提取入口（spec §5.1 步骤 ①）────────────────────────────

    async def extract(self, request: WorldExtractRequest) -> WorldExtractionResult:
        """AI 提取世界观条目 — 校验项目存在后委托 WorldExtractor.

        Args:
            request: 提取请求（project_id / text / 可选 model 覆盖）.

        Returns:
            合并落库后的提取报告.

        Raises:
            ProjectNotFoundError: 项目不存在（router 转 404「项目不存在」）.
            WorldServiceError: 提取器/项目仓储未注入（配置错误）.
            WorldExtractionError: 提取管线解析失败（透传，router 转 500）.
            LLMRequestError: LLM 调用失败（透传，router 转 500）.
        """
        if self._extractor is None:
            raise WorldServiceError("世界观提取器未配置")
        if self._project_repo is None:
            raise WorldServiceError("项目仓储未配置，无法校验项目存在性")
        project = await self._project_repo.get(_to_int_id(request.project_id))
        if project is None:
            raise ProjectNotFoundError()
        logger.info(
            "世界观提取: project=%s model=%s",
            request.project_id,
            request.model or project.config.model,
        )
        return await self._extractor.extract(request, default_model=project.config.model)
