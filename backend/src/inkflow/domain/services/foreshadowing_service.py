"""F13 伏笔业务服务 — 伏笔档案 CRUD + resolve/reopen 状态机 + 事件锚点校验.

职责（spec §5.1/§5.2/§7）:
- 伏笔 CRUD 编排：委托 ForeshadowingRepositoryProtocol，负责领域层
  UUID ↔ 仓储层 int 转换（沿用 F1 `_to_int_id` 模式）
- 同名唯一性校验（422，spec §2.3/§3.4）: 项目内活动伏笔 title 唯一
  （partial unique），创建/改名时经 repo.get_by_title 检查，
  命中 → ForeshadowingNameConflictError
- 事件锚点校验（422，spec §2.1/§3.4）: event_id 非 None 时复用 F12
  TimelineRepositoryProtocol.get 校验存在性（get 不含软删事件）与
  同项目归属，失败 → EventNotFoundError / EventNotInProjectError
- 状态机迁移（spec §2.4/§5.2）: resolve（open→resolved，自动设置
  resolved_at=now(UTC)）/ reopen（resolved→open，清空 resolved_at）；
  重复动作幂等（已 resolved 再 resolve 原样返回、已 open 再 reopen
  原样返回）；resolved_at 只由状态迁移维护，update 不触碰
- 资源不存在（404 语义）: 多数方法返回 None 由 router 层转 404；
  _ensure_project 校验失败抛 ProjectNotFoundError

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:
- repository: ForeshadowingRepositoryProtocol
- project_repo: ProjectRepositoryProtocol（F1，项目存在性校验用）
- timeline_repo: TimelineRepositoryProtocol（F12，event_id 事件锚点校验用）

依据: specs/f13-foreshadowing-service/spec.md §5/§7/§9。
"""

from __future__ import annotations

import builtins
import logging
import uuid
from datetime import UTC, datetime

from inkflow.domain.models.foreshadowing import (
    Foreshadowing,
    ForeshadowingCreate,
    ForeshadowingStatus,
    ForeshadowingUpdate,
)
from inkflow.domain.ports.foreshadowing_errors import (
    EventNotFoundError,
    EventNotInProjectError,
    ForeshadowingNameConflictError,
    ForeshadowingServiceError,
    ProjectNotFoundError,
)
from inkflow.domain.ports.foreshadowing_repository import ForeshadowingRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1 `_to_int_id` 模式）。"""
    if isinstance(value, uuid.UUID):
        return value.int
    return value


class ForeshadowingService:
    """伏笔业务服务 — 伏笔档案 CRUD、状态机迁移与事件锚点校验.

    Args:
        repository: 伏笔仓储端口.
        project_repo: 项目仓储（F1），项目存在性校验用；默认 None 时
            依赖项目的入口报错（防止静默降级）.
        timeline_repo: 时间线事件仓储（F12），event_id 事件锚点校验用；
            默认 None 时挂接事件的入口报错（防止静默降级）.
    """

    def __init__(
        self,
        *,
        repository: ForeshadowingRepositoryProtocol,
        project_repo: ProjectRepositoryProtocol | None = None,
        timeline_repo: TimelineRepositoryProtocol | None = None,
    ) -> None:
        self._repo = repository
        self._project_repo = project_repo
        self._timeline_repo = timeline_repo

    async def _ensure_project(self, project_id: uuid.UUID) -> None:
        """校验项目存在（spec §3.4: 项目不存在 → 404 语义）.

        Args:
            project_id: 所属项目 UUID.

        Raises:
            ForeshadowingServiceError: project_repo 未注入（配置错误，防静默降级）.
            ProjectNotFoundError: 项目不存在（router 层转 404「项目不存在」）.
        """
        if self._project_repo is None:
            raise ForeshadowingServiceError("项目仓储未配置，无法校验项目存在性")
        project = await self._project_repo.get(_to_int_id(project_id))
        if project is None:
            raise ProjectNotFoundError()

    async def _validate_event(self, project_id: uuid.UUID, event_id: uuid.UUID) -> None:
        """校验 event_id 事件锚点（spec §2.1/§3.4）: 事件存在且属于同一项目.

        复用 F12 TimelineRepositoryProtocol.get（get 不含软删事件，故软删
        事件视为不存在 → 422「事件不存在」）.

        Args:
            project_id: 伏笔所属项目 UUID.
            event_id: 待挂接的事件 UUID.

        Raises:
            ForeshadowingServiceError: timeline_repo 未注入（配置错误，防静默降级）.
            EventNotFoundError: 事件不存在（含已软删事件）.
            EventNotInProjectError: 事件属于其他项目.
        """
        if self._timeline_repo is None:
            raise ForeshadowingServiceError("时间线仓储未配置，无法校验事件锚点")
        event = await self._timeline_repo.get(event_id.int)
        if event is None:
            raise EventNotFoundError()
        if event.project_id != project_id:
            raise EventNotInProjectError()

    # ── Foreshadowing ─────────────────────────────────────

    async def create(self, data: ForeshadowingCreate) -> Foreshadowing:
        """创建伏笔（spec §2.4: 创建即 open；priority 默认 50）.

        Args:
            data: 创建请求 DTO（status 不可传，创建即 open）.

        Returns:
            持久化后的完整 Foreshadowing.

        Raises:
            ProjectNotFoundError: 项目不存在（router 层转 404）.
            ForeshadowingNameConflictError: 项目内已存在同名伏笔（422）.
            EventNotFoundError / EventNotInProjectError: event_id 锚点校验失败（422）.
            ForeshadowingServiceError: project_repo / timeline_repo 未注入（配置错误）.
        """
        await self._ensure_project(data.project_id)
        existing = await self._repo.get_by_title(_to_int_id(data.project_id), data.title)
        if existing is not None:
            raise ForeshadowingNameConflictError()
        if data.event_id is not None:
            await self._validate_event(data.project_id, data.event_id)
        now = _utcnow()
        foreshadowing = Foreshadowing(
            id=uuid.uuid4(),
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            priority=data.priority,
            status=ForeshadowingStatus.OPEN,
            location=data.location,
            event_id=data.event_id,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建伏笔: project=%s title=%s", data.project_id, data.title)
        return await self._repo.add(foreshadowing)

    async def get(self, foreshadowing_id: int | uuid.UUID) -> Foreshadowing | None:
        """按主键获取伏笔；不存在返回 None（router 转 404）."""
        return await self._repo.get(_to_int_id(foreshadowing_id))

    async def list(
        self,
        project_id: uuid.UUID,
        search: str | None = None,
        status: str | None = None,
        sort_by: str = "priority",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[Foreshadowing], int]:
        """分页查询项目内伏笔列表（spec §6.3）.

        Args:
            project_id: 所属项目 UUID（router 解析路径参数后传入）.
            search: 伏笔名不区分大小写子串匹配（可选）.
            status: 状态精确过滤（open / resolved；不传 = 全部伏笔）.
            sort_by: 排序字段（priority / title / status / updated_at / created_at）.
            sort_desc: 是否倒序（默认 True，priority 大者在前）.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (当前页伏笔列表, 符合条件的总记录数).

        Raises:
            ProjectNotFoundError: 项目不存在（router 层转 404）.
            ForeshadowingServiceError: project_repo 未注入（配置错误）.
        """
        await self._ensure_project(project_id)
        return await self._repo.list(
            project_id=_to_int_id(project_id),
            search=search,
            status=status,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )

    async def update(
        self, foreshadowing_id: int | uuid.UUID, data: ForeshadowingUpdate
    ) -> Foreshadowing | None:
        """部分更新伏笔（exclude_unset 语义，同 F1）.

        event_id 语义（spec §2.5/§7）: None 不修改；"" 解除事件挂接
        （置 None）；UUID 挂接（仅当与现有值不同时校验存在性 + 同项目）。
        title 变更时做同名检查（命中其他伏笔 → 422）。
        status / resolved_at 不可经本方法修改（DTO 无此字段，天然满足）。

        Args:
            foreshadowing_id: 伏笔主键（支持 int 或 UUID）.
            data: 含待更新字段的 ForeshadowingUpdate DTO.

        Returns:
            更新后的完整 Foreshadowing；伏笔不存在返回 None（router 转 404）.

        Raises:
            ForeshadowingNameConflictError: 改名与项目内其他伏笔同名（422）.
            EventNotFoundError / EventNotInProjectError: event_id 锚点校验失败（422）.
            ForeshadowingServiceError: timeline_repo 未注入（配置错误）.
        """
        fid = _to_int_id(foreshadowing_id)
        existing = await self._repo.get(fid)
        if existing is None:
            return None
        # None = 不修改（与未传入等价，同 F12 update 模式）；"",
        # UUID 等真实值保留参与合并
        updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        if "event_id" in updates:
            new_event_id = updates["event_id"]
            if isinstance(new_event_id, str):  # "" = 解除事件挂接
                updates["event_id"] = None
            elif new_event_id != existing.event_id:
                # 事件校验只在 event_id 发生变化时执行（避免对未变字段重复校验）
                await self._validate_event(existing.project_id, new_event_id)
        # title 改名同名检查（命中其他伏笔 → 422）
        if "title" in updates and updates["title"] != existing.title:
            dup = await self._repo.get_by_title(_to_int_id(existing.project_id), updates["title"])
            if dup is not None and dup.id != existing.id:
                raise ForeshadowingNameConflictError()
        merged = existing.model_copy(update=updates)
        logger.info("更新伏笔: foreshadowing_id=%s", foreshadowing_id)
        return await self._repo.update(merged)

    async def resolve(self, foreshadowing_id: int | uuid.UUID) -> Foreshadowing | None:
        """标记回收（spec §2.4: open→resolved，自动设置 resolved_at=now(UTC)）.

        Args:
            foreshadowing_id: 伏笔主键（支持 int 或 UUID）.

        Returns:
            迁移后的 Foreshadowing；已 resolved 原样返回（幂等，resolved_at
            不更新）；伏笔不存在返回 None（router 转 404）.
        """
        fid = _to_int_id(foreshadowing_id)
        existing = await self._repo.get(fid)
        if existing is None:
            return None
        if existing.status == ForeshadowingStatus.RESOLVED:
            return existing  # 幂等：状态不变，resolved_at 不更新
        merged = existing.model_copy(
            update={"status": ForeshadowingStatus.RESOLVED, "resolved_at": _utcnow()}
        )
        logger.info("伏笔已回收: foreshadowing_id=%s", foreshadowing_id)
        return await self._repo.update(merged)

    async def reopen(self, foreshadowing_id: int | uuid.UUID) -> Foreshadowing | None:
        """重新开启（spec §2.4: resolved→open，清空 resolved_at）.

        Args:
            foreshadowing_id: 伏笔主键（支持 int 或 UUID）.

        Returns:
            迁移后的 Foreshadowing；已 open 原样返回（幂等）；伏笔不存在
            返回 None（router 转 404）.
        """
        fid = _to_int_id(foreshadowing_id)
        existing = await self._repo.get(fid)
        if existing is None:
            return None
        if existing.status == ForeshadowingStatus.OPEN:
            return existing  # 幂等：状态不变
        merged = existing.model_copy(
            update={"status": ForeshadowingStatus.OPEN, "resolved_at": None}
        )
        logger.info("伏笔已重新开启: foreshadowing_id=%s", foreshadowing_id)
        return await self._repo.update(merged)

    async def delete(self, foreshadowing_id: int | uuid.UUID) -> bool:
        """删除伏笔（v1.1 默认真删，不可恢复；spec §7: 不存在 → False，router 转 404）.

        Args:
            foreshadowing_id: 伏笔主键（支持 int 或 UUID）.

        Returns:
            True 表示删除成功；False 表示未找到记录.
        """
        fid = _to_int_id(foreshadowing_id)
        logger.info("真删伏笔: foreshadowing_id=%s", foreshadowing_id)
        return await self._repo.hard_delete(fid)
