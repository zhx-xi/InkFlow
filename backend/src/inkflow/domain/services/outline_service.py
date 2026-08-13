"""F11 大纲业务服务 — 编排大纲/情节点/弧线 CRUD + AI 生成入口.

职责（spec §6/§7）:
- 三实体 CRUD 编排：委托 OutlineRepositoryProtocol，负责领域层
  UUID ↔ 仓储层 int 转换（沿用 F1 `_to_int_id` 模式）
- 业务校验（422 语义，抛 OutlineServiceError 子类）: 同名活动大纲/弧线、
  arc_id 跨项目或不存在
- 资源不存在（404 语义）: 多数方法返回 None 由 router 层转 404；
  create_point 等返回非 Optional 的方法抛 OutlineNotFoundError
- 级联编排（spec §6.1/§6.2，v1.1 真删）: 大纲真删 → 情节点由 DB FK CASCADE
  物理级联删除；弧线真删 → 成员情节点 arc_id 置 NULL（DB FK SET NULL，
  情节点保留）
- AI 生成入口（§5.1 步骤 ①）: 校验项目存在并组装 project_info（项目名/
  类型/目标字数/写作风格/extra 纯文本），以 project.config.model 作为
  默认模型，再委托 OutlineGenerator 执行管线（②-⑦）

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:
- repository: OutlineRepositoryProtocol（B1 已实现）
- generator: OutlineGenerator（B2 已实现）
- project_repo: ProjectRepositoryProtocol（F1 已实现，generate 入口校验用）

依据: specs/f11-outline-service/spec.md §6/§7/§9。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

from inkflow.domain.models.outline import (
    Outline,
    OutlineGenerateRequest,
    OutlineGenerationResult,
    OutlineUpdate,
    PlotPoint,
    PlotPointUpdate,
    StoryArc,
    StoryArcUpdate,
)
from inkflow.domain.models.project import Project
from inkflow.domain.ports.outline_errors import (
    ArcNameConflictError,
    ArcNotInProjectError,
    OutlineNameConflictError,
    OutlineNotFoundError,
    OutlineServiceError,
    ProjectNotFoundError,
)
from inkflow.domain.ports.outline_repository import OutlineRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.services._outline_generator import OutlineGenerator

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1 `_to_int_id` 模式）。"""
    if isinstance(value, uuid.UUID):
        return value.int
    return value


def _build_project_info(project: Project) -> str:
    """组装生成上下文（spec §5.1 步骤 ①）— 项目基本信息纯文本.

    含项目名/类型/目标字数/写作风格/extra 中的已有信息；MVP 不查
    F9/F10 档案（角色/世界观自动聚合归 Phase 2+）。

    Args:
        project: 已校验存在的项目实体.

    Returns:
        供 outline_generate 模板渲染的纯文本.
    """
    parts = [
        f"项目名: {project.name}",
        f"类型: {project.genre.value}",
        f"目标字数: {project.target_words}",
        f"写作风格: {project.config.writing_style or '未指定'}",
    ]
    if project.config.extra:
        parts.append(f"扩展配置: {json.dumps(project.config.extra, ensure_ascii=False)}")
    return "\n".join(parts)


class OutlineService:
    """大纲业务服务 — 编排大纲/情节点/弧线 CRUD 与 AI 生成.

    Args:
        repository: 大纲/情节点/弧线仓储端口（B1）.
        generator: 大纲生成管线（B2）；deps.py 负责组装，默认 None 时
            generate 入口报错（防止静默降级）.
        project_repo: 项目仓储（F1），generate 入口校验项目存在并读取默认模型.
    """

    def __init__(
        self,
        *,
        repository: OutlineRepositoryProtocol,
        generator: OutlineGenerator | None = None,
        project_repo: ProjectRepositoryProtocol | None = None,
    ) -> None:
        self._repo = repository
        self._generator = generator
        self._project_repo = project_repo

    # ── Outline ────────────────────────────────────────────────

    async def create_outline(
        self,
        project_id: uuid.UUID,
        name: str,
        description: str = "",
        sort_order: int = 0,
    ) -> Outline:
        """创建大纲（spec §7: 同名活动大纲 → 422）.

        Args:
            project_id: 所属项目 UUID（router 解析路径参数后传入）.
            name: 大纲名（OutlineCreate 已去空白校验）.
            description: 大纲总体描述.
            sort_order: 大纲间排序权重（小者在前）.

        Returns:
            持久化后的完整 Outline.

        Raises:
            OutlineNameConflictError: 项目内已存在同名活动大纲.
        """
        pid_int = _to_int_id(project_id)
        existing = await self._repo.get_by_name(pid_int, name)
        if existing is not None:
            raise OutlineNameConflictError()
        now = _utcnow()
        outline = Outline(
            id=uuid.uuid4(),
            project_id=project_id,
            name=name,
            description=description,
            sort_order=sort_order,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建大纲: project=%s name=%s", project_id, name)
        return await self._repo.add(outline)

    async def get_outline(self, outline_id: int | uuid.UUID) -> Outline | None:
        """按主键获取大纲；不存在返回 None（router 转 404）."""
        return await self._repo.get(_to_int_id(outline_id))

    async def list_outlines(
        self,
        project_id: int | uuid.UUID,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Outline], int]:
        """分页查询项目内大纲列表，支持名称模糊搜索（spec §6.3）.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.
            search: 大纲名模糊搜索（可选）.
            sort_by: 排序字段（updated_at / name / sort_order）.
            sort_desc: 是否倒序.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (当前页大纲列表, 符合条件的总记录数).
        """
        return await self._repo.list(
            project_id=_to_int_id(project_id),
            search=search,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )

    async def update_outline(
        self, outline_id: int | uuid.UUID, update: OutlineUpdate
    ) -> Outline | None:
        """部分更新大纲（exclude_unset 语义，同 F1）.

        业务校验（spec §7）: 改名撞项目内其他活动大纲 → 422。

        Args:
            outline_id: 大纲主键（支持 int 或 UUID）.
            update: 含待更新字段的 OutlineUpdate DTO.

        Returns:
            更新后的完整 Outline；大纲不存在返回 None（router 转 404）.
        """
        oid = _to_int_id(outline_id)
        existing = await self._repo.get(oid)
        if existing is None:
            return None
        if "name" in update.model_fields_set and update.name is not None:
            dup = await self._repo.get_by_name(_to_int_id(existing.project_id), update.name)
            if dup is not None and dup.id != existing.id:
                raise OutlineNameConflictError()
        updates = {k: v for k, v in update.model_dump(exclude_unset=True).items() if v is not None}
        merged = existing.model_copy(update=updates)
        logger.info("更新大纲: outline_id=%s", outline_id)
        return await self._repo.update(merged)

    async def delete_outline(self, outline_id: int | uuid.UUID) -> bool:
        """真删大纲（v1.1，spec §7: 大纲不存在 → False，router 转 404）.

        Args:
            outline_id: 大纲主键（支持 int 或 UUID）.

        Returns:
            True 表示删除成功；False 表示未找到记录.
        """
        oid = _to_int_id(outline_id)
        logger.info("真删大纲: outline_id=%s（情节点由 FK CASCADE 级联）", outline_id)
        return await self._repo.hard_delete(oid)

    # ── PlotPoint ──────────────────────────────────────────────

    async def create_point(
        self,
        outline_id: int | uuid.UUID,
        name: str,
        type: str = "",
        description: str = "",
        position: int | None = None,
        arc_id: uuid.UUID | None = None,
    ) -> PlotPoint:
        """创建情节点（spec §7: 大纲不存在 → 404；arc_id 不存在/跨项目 → 422）.

        Args:
            outline_id: 所属大纲主键（支持 int 或 UUID）.
            name: 情节点名（PlotPointCreate 已去空白校验）.
            type: 情节点类型（空串 = 未分类）.
            description: 情节点要点描述.
            position: 大纲内排序；None = 追加到大纲末尾（next_position）.
            arc_id: 所属故事弧线 UUID（None = 不挂弧线）.

        Returns:
            持久化后的完整 PlotPoint.

        Raises:
            OutlineNotFoundError: 大纲不存在（router 转 404）.
            ArcNotInProjectError: 弧线不存在或不属于该项目（422 语义）.
        """
        oid_int = _to_int_id(outline_id)
        outline = await self._repo.get(oid_int)
        if outline is None:
            raise OutlineNotFoundError()
        if arc_id is not None:
            arc = await self._repo.get_arc(_to_int_id(arc_id))
            if arc is None or arc.project_id != outline.project_id:
                raise ArcNotInProjectError()
        if position is None:
            position = await self._repo.next_position(oid_int)
        now = _utcnow()
        point = PlotPoint(
            id=uuid.uuid4(),
            outline_id=outline.id,
            project_id=outline.project_id,
            name=name,
            type=type,
            description=description,
            position=position,
            arc_id=arc_id,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建情节点: outline=%s name=%s position=%s", outline_id, name, position)
        return await self._repo.add_point(point)

    async def get_point(self, point_id: int | uuid.UUID) -> PlotPoint | None:
        """按主键获取情节点；不存在返回 None（router 转 404）."""
        return await self._repo.get_point(_to_int_id(point_id))

    async def update_point(
        self, point_id: int | uuid.UUID, update: PlotPointUpdate
    ) -> PlotPoint | None:
        """部分更新情节点（exclude_unset 语义，同 F1）.

        arc_id 三态（spec §7/模型注释）: 不传 = 不修改；None/"" = 清除弧线
        归属（置为不挂弧线）；UUID = 设置（校验弧线存在且属于同一项目）。

        Args:
            point_id: 情节点主键（支持 int 或 UUID）.
            update: 含待更新字段的 PlotPointUpdate DTO.

        Returns:
            更新后的完整 PlotPoint；情节点不存在返回 None（router 转 404）.

        Raises:
            ArcNotInProjectError: 新弧线不存在或不属于该项目（422 语义）.
        """
        pid = _to_int_id(point_id)
        existing = await self._repo.get_point(pid)
        if existing is None:
            return None
        updates = {k: v for k, v in update.model_dump(exclude_unset=True).items() if v is not None}
        if "arc_id" in update.model_fields_set:
            if isinstance(update.arc_id, uuid.UUID):
                arc = await self._repo.get_arc(_to_int_id(update.arc_id))
                if arc is None or arc.project_id != existing.project_id:
                    raise ArcNotInProjectError()
                updates["arc_id"] = update.arc_id
            else:
                # None / "" → 清除弧线归属
                updates["arc_id"] = None
        merged = existing.model_copy(update=updates)
        logger.info("更新情节点: point_id=%s", point_id)
        return await self._repo.update_point(merged)

    async def delete_point(self, point_id: int | uuid.UUID) -> bool:
        """真删情节点（v1.1，spec §7: 情节点不存在 → False，router 转 404）.

        Args:
            point_id: 情节点主键（支持 int 或 UUID）.

        Returns:
            True 表示删除成功；False 表示未找到记录.
        """
        pid = _to_int_id(point_id)
        logger.info("真删情节点: point_id=%s", point_id)
        return await self._repo.hard_delete_point(pid)

    async def list_points(self, outline_id: int | uuid.UUID) -> list[PlotPoint]:
        """查询大纲内全部情节点（position ASC 稳定排序，spec §6.3）.

        Args:
            outline_id: 大纲主键（支持 int 或 UUID）.

        Returns:
            该大纲的情节点列表；大纲不存在返回空列表.
        """
        oid = _to_int_id(outline_id)
        outline = await self._repo.get(oid)
        if outline is None:
            return []
        return await self._repo.list_points(oid)

    # ── StoryArc ───────────────────────────────────────────────

    async def create_arc(
        self,
        project_id: uuid.UUID,
        name: str,
        description: str = "",
    ) -> StoryArc:
        """创建故事弧线（spec §2.4: 项目内活动弧线名唯一）.

        Args:
            project_id: 所属项目 UUID.
            name: 弧线名（StoryArcCreate 已去空白校验）.
            description: 弧线说明.

        Returns:
            持久化后的完整 StoryArc.

        Raises:
            ArcNameConflictError: 项目内已存在同名活动弧线.
        """
        pid_int = _to_int_id(project_id)
        existing = await self._repo.get_arc_by_name(pid_int, name)
        if existing is not None:
            raise ArcNameConflictError()
        now = _utcnow()
        arc = StoryArc(
            id=uuid.uuid4(),
            project_id=project_id,
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建弧线: project=%s name=%s", project_id, name)
        return await self._repo.add_arc(arc)

    async def get_arc(self, arc_id: int | uuid.UUID) -> StoryArc | None:
        """按主键获取弧线；不存在返回 None（router 转 404）."""
        return await self._repo.get_arc(_to_int_id(arc_id))

    async def list_arcs(self, project_id: int | uuid.UUID) -> list[StoryArc]:
        """查询项目内全部故事弧线（name ASC，spec §6.3）."""
        return await self._repo.list_arcs(_to_int_id(project_id))

    async def update_arc(self, arc_id: int | uuid.UUID, update: StoryArcUpdate) -> StoryArc | None:
        """部分更新弧线（exclude_unset 语义，同 F1）.

        业务校验（spec §7）: 改名撞项目内其他活动弧线 → 422。

        Args:
            arc_id: 弧线主键（支持 int 或 UUID）.
            update: 含待更新字段的 StoryArcUpdate DTO.

        Returns:
            更新后的完整 StoryArc；弧线不存在返回 None（router 转 404）.
        """
        aid = _to_int_id(arc_id)
        existing = await self._repo.get_arc(aid)
        if existing is None:
            return None
        if "name" in update.model_fields_set and update.name is not None:
            dup = await self._repo.get_arc_by_name(_to_int_id(existing.project_id), update.name)
            if dup is not None and dup.id != existing.id:
                raise ArcNameConflictError()
        updates = {k: v for k, v in update.model_dump(exclude_unset=True).items() if v is not None}
        merged = existing.model_copy(update=updates)
        logger.info("更新弧线: arc_id=%s", arc_id)
        return await self._repo.update_arc(merged)

    async def delete_arc(self, arc_id: int | uuid.UUID) -> bool:
        """真删弧线（v1.1，spec §6.2/§7: 成员情节点 arc_id 由 FK SET NULL，情节点本身保留）.

        Args:
            arc_id: 弧线主键（支持 int 或 UUID）.

        Returns:
            True 表示删除成功；False 表示未找到记录.
        """
        aid = _to_int_id(arc_id)
        logger.info("真删弧线: arc_id=%s（成员 arc_id 由 FK SET NULL）", arc_id)
        return await self._repo.hard_delete_arc(aid)

    # ── AI 生成入口（spec §5.1 步骤 ①）────────────────────────

    async def generate(self, request: OutlineGenerateRequest) -> OutlineGenerationResult:
        """AI 生成大纲 — 校验项目存在并组装 project_info 后委托 OutlineGenerator.

        Args:
            request: 生成请求（project_id / name? / prompt? /
                num_chapters? / save / model?）.

        Returns:
            落库后的生成报告（save=True）或预览结构（save=False）.

        Raises:
            ProjectNotFoundError: 项目不存在（router 转 404「项目不存在」）.
            OutlineServiceError: 生成器/项目仓储未注入（配置错误）.
            OutlineGenerationError: 生成管线解析失败（透传，router 转 500）.
            LLMRequestError: LLM 调用失败（透传，router 转 500）.
        """
        if self._generator is None:
            raise OutlineServiceError("大纲生成器未配置")
        if self._project_repo is None:
            raise OutlineServiceError("项目仓储未配置，无法校验项目存在性")
        project = await self._project_repo.get(_to_int_id(request.project_id))
        if project is None:
            raise ProjectNotFoundError()
        logger.info(
            "大纲生成: project=%s model=%s",
            request.project_id,
            request.model or project.config.model,
        )
        return await self._generator.generate(
            request,
            project_info=_build_project_info(project),
            default_model=project.config.model,
        )
