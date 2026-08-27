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
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from inkflow.core.config import config
from inkflow.domain.models.world import (
    WorldCategory,
    WorldExtractionResult,
    WorldExtractRequest,
    WorldSetting,
    WorldUpdate,
)
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.world_errors import (
    ProjectNotFoundError,
    WorldCategoryNameConflictError,
    WorldChildrenActionRequiredError,
    WorldCycleError,
    WorldNameConflictError,
    WorldParentNotFoundError,
    WorldReparentTargetError,
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
        location_cleanup: 地点硬删钩子（F36 D10=b）：真删地点后清理关联地图 pin
            （MapService.clear_location_pins）；失败仅 log warning 不阻断主流程.
        llm_default_model: 全局默认模型（#520 D1=C）——project.config.model 为
            None 时回退该值（deps.py 注入 config.llm_default_model）.
    """

    def __init__(
        self,
        *,
        repository: WorldRepositoryProtocol,
        extractor: WorldExtractor | None = None,
        project_repo: ProjectRepositoryProtocol | None = None,
        location_cleanup: Callable[[list[int]], Awaitable[None]] | None = None,
        llm_default_model: str = config.llm_default_model,
    ) -> None:
        self._repo = repository
        self._extractor = extractor
        self._project_repo = project_repo
        self._location_cleanup = location_cleanup
        self._llm_default_model = llm_default_model

    # ── WorldSetting ─────────────────────────────────────────────

    async def create_setting(
        self,
        project_id: uuid.UUID,
        name: str,
        category: str = "",
        content: str = "",
        parent_id: uuid.UUID | None = None,
    ) -> WorldSetting:
        """创建世界观条目（F35: parent_id 挂接 + 同级同名校验）.

        F35 校验链（spec §5.1）：
        ① parent_id 若提供 → 父存在 + 同项目（WorldParentNotFoundError）
        ② 同级同名（含顶层应用层校验，get_by_parent_and_name）→ WorldNameConflictError
        ③ 循环防护（parent 的祖先链不含自身）→ WorldCycleError

        Args:
            project_id: 所属项目 UUID（router 解析路径参数后传入）.
            name: 条目名（WorldCreate 已去空白校验）.
            category: 类别（空串 = 未分类）.
            content: 条目内容.
            parent_id: 父地点 UUID；None = 顶层（F35 新增）.

        Returns:
            持久化后的完整 WorldSetting.

        Raises:
            WorldParentNotFoundError: 父地点不存在/不在同一项目.
            WorldNameConflictError: 同级（含顶层）已存在同名活动条目.
        """
        pid_int = _to_int_id(project_id)
        parent_int = _to_int_id(parent_id) if parent_id is not None else None
        # ① 父存在 + 同项目（repo.get 真删语义下不存在即无记录）
        if parent_int is not None:
            parent = await self._repo.get(parent_int)
            if parent is None or _to_int_id(parent.project_id) != pid_int:
                raise WorldParentNotFoundError()
        # F10 兼容：顶层创建沿用项目级同名预检（既有测试契约）；同级校验见下
        if parent_int is None:
            existing = await self._repo.get_by_name(pid_int, name)
            if existing is not None:
                raise WorldNameConflictError()
        # ② 同级同名（parent_id=None = 顶层应用层校验，SQLite NULL 不冲突坑）
        dup = await self._repo.get_by_parent_and_name(pid_int, parent_int, name)
        if dup is not None:
            raise WorldNameConflictError()
        # ③ 循环防护：创建时自身尚无 id，parent 祖先链不可能含自身——语义完整
        #    保留注释（对齐 spec §5.1 顺序；update 改挂时由 _assert_no_cycle 落地）
        now = _utcnow()
        setting = WorldSetting(
            id=uuid.uuid4(),
            project_id=project_id,
            name=name,
            category=category,
            content=content,
            parent_id=parent_id,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建世界观条目: project=%s name=%s parent_id=%s", project_id, name, parent_id)
        return await self._repo.add(setting)

    async def get_setting(self, setting_id: int | uuid.UUID) -> WorldSetting | None:
        """按主键获取条目；不存在返回 None（router 转 404）."""
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
        parent_id: int | uuid.UUID | None = None,
        top_level_only: bool = False,
    ) -> tuple[list[WorldSetting], int]:
        """分页查询项目内条目列表，支持搜索、类别过滤、排序（F35 树过滤）.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.
            search: 条目名模糊搜索（可选）.
            category: 类别精确过滤（可选；空串查询未分类条目）.
            sort_by: 排序字段（updated_at / name / created_at）.
            sort_desc: 是否倒序.
            offset: 分页偏移.
            limit: 分页大小.
            parent_id: 直接父级过滤（可选；F35 新增，None + top_level_only 区分顶层）.
            top_level_only: True 只返回顶层（parent_id IS NULL，F35 新增）.

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
            parent_id=_to_int_id(parent_id) if parent_id is not None else None,
            top_level_only=top_level_only,
        )

    async def list_categories(self, project_id: int | uuid.UUID) -> list[tuple[str, int]]:
        """聚合项目内活动条目的类别计数（排除空类别）.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.

        Returns:
            (类别, 条目数) 列表，按计数降序、类别名升序.
        """
        return await self._repo.list_categories(_to_int_id(project_id))

    async def has_root_setting(self, project_id: int | uuid.UUID) -> bool:
        """项目是否已有根世界观条目（parent_id IS NULL）。

        #567 单例校验：创建根条目前判重。repo.list top_level_only=True limit=1 判空。
        """
        roots, _ = await self._repo.list(_to_int_id(project_id), top_level_only=True, limit=1)
        return len(roots) > 0

    async def get_root_setting(self, project_id: int | uuid.UUID) -> WorldSetting | None:
        """项目根世界观条目（parent_id IS NULL）；无根返回 None。

        #641：create_world_setting 对 body 无 parent_id 时先取根——有根则自动挂根，
        无根则建根（保留一项目一根硬语义）。repo.list top_level_only=True limit=1 取根。
        """
        roots, _ = await self._repo.list(_to_int_id(project_id), top_level_only=True, limit=1)
        return roots[0] if roots else None

    async def update_setting(
        self, setting_id: int | uuid.UUID, update: WorldUpdate
    ) -> WorldSetting | None:
        """部分更新条目（exclude_unset 语义，同 F1；F35 parent_id 例外）.

        业务校验（spec §5.1）：
        - 改名撞同级（含顶层）其他活动条目 → 422（WorldNameConflictError）
        - parent_id 出现即更新：None=置顶、非 null=改挂；改挂前校验父存在/循环/同级同名
        - category/content 的 None=不修改（F10 语义）与 parent_id 的 None=置顶可区分

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
        # F10 兼容：顶层条目改名沿用项目级同名预检（既有测试契约）
        if (
            "name" in update.model_fields_set
            and update.name is not None
            and existing.parent_id is None
        ):
            dup_legacy = await self._repo.get_by_name(_to_int_id(existing.project_id), update.name)
            if dup_legacy is not None and dup_legacy.id != existing.id:
                raise WorldNameConflictError()
        # 改名同级同名校验（F35: 按同级语义，含顶层）
        if "name" in update.model_fields_set and update.name is not None:
            target_parent_int = (
                _to_int_id(update.parent_id)
                if "parent_id" in update.model_fields_set and update.parent_id is not None
                else (_to_int_id(existing.parent_id) if existing.parent_id is not None else None)
            )
            dup = await self._repo.get_by_parent_and_name(
                _to_int_id(existing.project_id), target_parent_int, update.name
            )
            if dup is not None and dup.id != existing.id:
                raise WorldNameConflictError()
        # F35: parent_id 出现即更新（None=置顶）；其余字段 None=不修改（F10 语义）
        updates = {k: v for k, v in update.model_dump(exclude_unset=True).items() if v is not None}
        if "parent_id" in update.model_fields_set:
            updates["parent_id"] = update.parent_id  # 可能为 None（置顶）
        # F35: 改挂/置顶前校验（父存在/循环/同级同名）——只有 parent_id 变化才需要
        if "parent_id" in update.model_fields_set:
            new_parent_int = _to_int_id(update.parent_id) if update.parent_id is not None else None
            if new_parent_int is not None:
                # 父存在 + 同项目
                parent = await self._repo.get(new_parent_int)
                if parent is None or _to_int_id(parent.project_id) != _to_int_id(
                    existing.project_id
                ):
                    raise WorldParentNotFoundError()
            # 循环防护（spec §5.2）
            await self._assert_no_cycle(sid, new_parent_int)
            # 同级同名（改挂后新父下是否撞名）
            if "name" in update.model_fields_set and update.name is not None:
                new_name = update.name
            else:
                new_name = existing.name
            dup2 = await self._repo.get_by_parent_and_name(
                _to_int_id(existing.project_id), new_parent_int, new_name
            )
            if dup2 is not None and dup2.id != existing.id:
                raise WorldNameConflictError()
        merged = existing.model_copy(update=updates)
        logger.info("更新世界观条目: setting_id=%s", setting_id)
        return await self._repo.update(merged)

    async def delete_setting(
        self,
        setting_id: int | uuid.UUID,
        cascade: bool = False,
        reparent_to: uuid.UUID | None = None,
    ) -> bool:
        """删除条目（v1.1 默认真删 + F35 树级删除语义，spec §5.5）.

        语义矩阵：
        - 无子地点：真删（hard_delete）
        - 有子地点 + 未指定 cascade/reparent_to → WorldChildrenActionRequiredError
        - cascade=True → 真删整棵子树（list_descendants + hard_delete_many 单事务原子）
        - reparent_to=<id> → 真删自身 + 直接子改挂新父（delete_with_reparent 单事务）
        - cascade 与 reparent_to 同时提供 → cascade 优先

        F43 P5: reparent 分支补调 location_cleanup 钩子（spec §5.18，
        cascade/单删分支已有，reparent 分支此前漏调）。

        Args:
            setting_id: 条目主键（支持 int 或 UUID）.
            cascade: True 级联真删整棵子树（优先于 reparent_to）.
            reparent_to: 子地点改挂新父后真删自身.

        Returns:
            True 表示删除成功；False 表示未找到记录（router 转 404）.

        Raises:
            WorldChildrenActionRequiredError: 有子地点且未指定 cascade/reparent_to.
            WorldReparentTargetError: reparent 目标不存在/跨项目/是自身子树.
        """
        sid = _to_int_id(setting_id)
        # 解析条目所在项目（查子/reparent 校验用；缺失时删除由 repo 返回 False 兜底——
        # 测试契约要求 cascade/reparent 路径不做存在性闸门）
        existing = await self._repo.get(sid)
        project_int = _to_int_id(existing.project_id) if existing is not None else 0
        # 判断是否有直接子地点（repo.list parent_id 过滤）
        children, _ = await self._repo.list(project_int, parent_id=sid, limit=1)
        if cascade:
            logger.info("级联真删世界观地点子树: setting_id=%s", setting_id)
            subtree = await self._repo.list_descendants(sid)
            ids = [s.id.int for s in subtree] if subtree else [sid]
            await self._repo.hard_delete_many(ids)
            await self._notify_location_cleanup(ids)
            return True
        if reparent_to is not None:
            target_int = _to_int_id(reparent_to)
            # reparent 目标校验（存在/同项目/非自身子树 → WorldReparentTargetError）
            target = await self._repo.get(target_int)
            if target is None:
                raise WorldReparentTargetError()
            # 同项目校验：以直接子所在项目为准（数据隔离保证子与自身同项目）
            ref_project_int = (
                _to_int_id(children[0].project_id)
                if children
                else (_to_int_id(existing.project_id) if existing is not None else None)
            )
            if ref_project_int is not None and _to_int_id(target.project_id) != ref_project_int:
                raise WorldReparentTargetError()
            subtree = await self._repo.list_descendants(sid)
            if target_int in [s.id.int for s in subtree]:
                raise WorldReparentTargetError()
            logger.info("reparent 真删世界观条目: setting_id=%s → %s", setting_id, reparent_to)
            await self._notify_location_cleanup([sid])
            return await self._repo.delete_with_reparent(sid, target_int)
        if children:
            raise WorldChildrenActionRequiredError()
        logger.info("真删世界观条目: setting_id=%s", setting_id)
        deleted = await self._repo.hard_delete(sid)
        if deleted:
            await self._notify_location_cleanup([sid])
        return deleted

    async def _notify_location_cleanup(self, ids: list[int]) -> None:
        """调用地点硬删钩子（F36 D10=b）；失败仅 log warning 不阻断主流程."""
        if self._location_cleanup is None:
            return
        try:
            await self._location_cleanup(ids)
        except Exception:
            logger.warning("地点硬删后 pin 清理失败: %s", ids, exc_info=True)

    # ── WorldCategory（v1.2，issue #389）──────────────────────────

    async def create_category(
        self, project_id: uuid.UUID, name: str, kind: str = "geo"
    ) -> WorldCategory:
        """创建世界观分类（spec §2.6：项目内分类名唯一）.

        Args:
            project_id: 所属项目 UUID.
            name: 分类名（WorldCategoryCreateBody 已去空白校验）.

        Returns:
            持久化后的完整 WorldCategory.

        Raises:
            WorldCategoryNameConflictError: 项目内已存在同名分类.
        """
        existing = await self._repo.get_category_by_name(project_id, name)
        if existing is not None:
            raise WorldCategoryNameConflictError()
        logger.info("创建世界观分类: project=%s name=%s", project_id, name)
        return await self._repo.create_category(project_id, name, kind)

    async def list_world_categories(self, project_id: uuid.UUID) -> list[tuple[WorldCategory, int]]:
        """分类实体列表 + 每个分类名匹配的条目计数（spec §3.1/§6.1）."""
        return await self._repo.list_world_categories(project_id)

    async def rename_category(self, category_id: uuid.UUID, name: str) -> WorldCategory | None:
        """重命名分类（反向同步条目 category，spec §6.1 D2=A）.

        Args:
            category_id: 分类主键 UUID.
            name: 新分类名（WorldCategoryUpdateBody 已去空白校验）.

        Returns:
            更新后的 WorldCategory；分类不存在返回 None（router 转 404）.

        Raises:
            WorldCategoryNameConflictError: 新名撞项目内其他分类.
        """
        existing = await self._repo.get_category(category_id)
        if existing is None:
            return None
        dup = await self._repo.get_category_by_name(existing.project_id, name)
        if dup is not None and dup.id != existing.id:
            raise WorldCategoryNameConflictError()
        logger.info("重命名世界观分类: category_id=%s → %s", category_id, name)
        return await self._repo.rename_category(category_id, name)

    async def delete_category(self, category_id: uuid.UUID) -> bool:
        """删除分类（反向清空条目 category，spec §6.1 D2=A）.

        Args:
            category_id: 分类主键 UUID.

        Returns:
            True 表示删除成功；False 表示未找到记录（router 转 404）.
        """
        return await self._repo.delete_category(category_id)

    # ── F35 树查询（spec §5.3）────────────────────────────────────

    async def list_ancestors(self, setting_id: int | uuid.UUID) -> list[WorldSetting] | None:
        """祖先链（含自身，自身在前，面包屑展示）.

        Returns:
            祖先链（[自身, 父, 祖父, ...]）；条目不存在 → None（router 转 404）。
        """
        sid = _to_int_id(setting_id)
        setting = await self._repo.get(sid)
        if setting is None:
            return None
        chain: list[WorldSetting] = [setting]
        current = setting
        # 逐级上溯（祖先链深度有限，应用层遍历；与 repo.collect_ancestor_ids 语义一致）
        seen: set[int] = set()
        while current.parent_id is not None:
            parent_int = _to_int_id(current.parent_id)
            if parent_int in seen:
                break  # 防御：数据异常成环时截断
            seen.add(parent_int)
            parent = await self._repo.get(parent_int)
            if parent is None:
                break  # 父不存在 → 链在此截断
            chain.append(parent)
            current = parent
        return chain

    async def list_descendants(self, setting_id: int | uuid.UUID) -> list[WorldSetting] | None:
        """子树（含自身，层序：父先子后）——直接透传 repo（测试契约）.

        Returns:
            子树列表；层序/含自身由 repo 保证（不存在 id → 空列表）。
        """
        return await self._repo.list_descendants(_to_int_id(setting_id))

    async def _assert_no_cycle(self, pid_int: int, new_parent_id: int | None) -> None:
        """校验 new_parent_id 不是 self 或其子孙（spec §5.2，O(depth)）."""
        if new_parent_id is None:
            return
        if new_parent_id == pid_int:
            raise WorldCycleError()
        ancestor_ids = await self._repo.collect_ancestor_ids(new_parent_id)
        if pid_int in ancestor_ids:
            raise WorldCycleError()

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
        return await self._extractor.extract(
            request, default_model=project.config.model or self._llm_default_model
        )
