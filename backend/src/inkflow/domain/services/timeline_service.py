"""F12 时间线业务服务 — 编排事件 CRUD + 双线视图 + 一致性检查.

职责（spec §5/§6/§7）:
- 事件 CRUD 编排：委托 TimelineRepositoryProtocol，负责领域层
  UUID ↔ 仓储层 int 转换（沿用 F1 `_to_int_id` 模式）
- 业务校验（422 语义，抛 TimelineServiceError 子类）: 本模块无冲突类
  校验（timeline_events 无唯一约束，见 spec §2.4）；配置错误（项目仓储
  未注入）同样抛 TimelineServiceError
- 资源不存在（404 语义）: 多数方法返回 None 由 router 层转 404；
  _ensure_project 校验失败抛 ProjectNotFoundError
- 双线视图（spec §5.2）: event_timeline 按 (time_value ASC NULLS LAST,
  narrative_position ASC) 排序；narrative_order 按叙事位置升序
  （list_all 已按 (narrative_position ASC, created_at ASC) 稳定排序）
- 一致性检查（spec §5.3，确定性算法，无 LLM）: 对叙事顺序上相邻且
  time_value 均非 None 的事件对做相邻对扫描，报告全部逆序对；
  已声明 flashback/flashforward 的逆序对计入 flashbacks（不影响
  consistent），未声明的计入 conflicts

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:
- repository: TimelineRepositoryProtocol（B1 已实现）
- project_repo: ProjectRepositoryProtocol（F1 已实现，项目存在性校验用）

依据: specs/f12-timeline-service/spec.md §5/§6/§7/§9。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from inkflow.domain.models.timeline import (
    ConsistencyReport,
    TimelineConflict,
    TimelineEvent,
    TimelineEventRef,
    TimelineEventUpdate,
    TimelineView,
)
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_errors import (
    ProjectNotFoundError,
    TimelineServiceError,
)
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


def _time_label(event: TimelineEvent) -> str:
    """事件时间的人类可读表达（time_display 优先，缺失时回退数值字符串）。"""
    return event.time_display or str(event.time_value)


def _to_ref(event: TimelineEvent) -> TimelineEventRef:
    """构造一致性检查中的事件引用（轻量快照，spec §2.6）。"""
    return TimelineEventRef(
        id=event.id,
        title=event.title,
        time_value=event.time_value,
        time_display=event.time_display,
        narrative_position=event.narrative_position,
        timeline_flag=event.timeline_flag,
    )


def _sort_event_timeline(events: list[TimelineEvent]) -> list[TimelineEvent]:
    """事件时间线视图排序（spec §5.2）: time_value ASC NULLS LAST, narrative_position ASC。

    Args:
        events: 待排序的事件列表.

    Returns:
        排序后的新列表（不修改入参）.
    """
    return sorted(
        events,
        key=lambda e: (e.time_value is None, e.time_value, e.narrative_position),
    )


class TimelineService:
    """时间线业务服务 — 编排事件 CRUD、双线视图与一致性检查.

    Args:
        repository: 时间线事件仓储端口（B1）.
        project_repo: 项目仓储（F1），项目存在性校验用；默认 None 时
            依赖项目的入口报错（防止静默降级）.
    """

    def __init__(
        self,
        *,
        repository: TimelineRepositoryProtocol,
        project_repo: ProjectRepositoryProtocol | None = None,
    ) -> None:
        self._repo = repository
        self._project_repo = project_repo

    async def _ensure_project(self, project_id: uuid.UUID) -> None:
        """校验项目存在（spec §3.4: 项目不存在 → 404 语义）.

        Args:
            project_id: 所属项目 UUID.

        Raises:
            TimelineServiceError: project_repo 未注入（配置错误，防静默降级）.
            ProjectNotFoundError: 项目不存在（router 层转 404「项目不存在」）.
        """
        if self._project_repo is None:
            raise TimelineServiceError("项目仓储未配置，无法校验项目存在性")
        project = await self._project_repo.get(_to_int_id(project_id))
        if project is None:
            raise ProjectNotFoundError()

    # ── TimelineEvent ─────────────────────────────────────────────

    async def create_event(
        self,
        project_id: uuid.UUID,
        title: str,
        description: str = "",
        time_value: float | None = None,
        time_unit: str = "",
        time_display: str = "",
        narrative_position: int | None = None,
        timeline_flag: str = "",
    ) -> TimelineEvent:
        """创建时间线事件（spec §2.1: narrative_position 缺省 = 叙事末尾追加）.

        Args:
            project_id: 所属项目 UUID（router 解析路径参数后传入）.
            title: 事件标题（TimelineEventCreate 已去空白校验）.
            description: 事件描述.
            time_value: 世界内时间数值键；None = 时间未知.
            time_unit: 时间单位标签（仅语义）.
            time_display: 原始时间表达.
            narrative_position: 叙事位置；None = 先 next_position 再追加.
            timeline_flag: 时间线标记（""/flashback/flashforward）.

        Returns:
            持久化后的完整 TimelineEvent.

        Raises:
            ProjectNotFoundError: 项目不存在（router 层转 404）.
            TimelineServiceError: project_repo 未注入（配置错误）.
        """
        await self._ensure_project(project_id)
        if narrative_position is None:
            narrative_position = await self._repo.next_position(_to_int_id(project_id))
        now = _utcnow()
        event = TimelineEvent(
            id=uuid.uuid4(),
            project_id=project_id,
            title=title,
            description=description,
            time_value=time_value,
            time_unit=time_unit,
            time_display=time_display,
            narrative_position=narrative_position,
            timeline_flag=timeline_flag,
            created_at=now,
            updated_at=now,
        )
        logger.info(
            "创建时间线事件: project=%s title=%s position=%s",
            project_id,
            title,
            narrative_position,
        )
        return await self._repo.add(event)

    async def get_event(self, event_id: int | uuid.UUID) -> TimelineEvent | None:
        """按主键获取事件（不含已软删除）；不存在返回 None（router 转 404）."""
        return await self._repo.get(_to_int_id(event_id))

    async def list_events(
        self,
        project_id: int | uuid.UUID,
        search: str | None = None,
        sort_by: str = "narrative_position",
        sort_desc: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[TimelineEvent], int]:
        """分页查询项目内事件列表，支持标题模糊搜索（spec §6.3）.

        Args:
            project_id: 项目主键（支持 int 或 UUID）.
            search: 事件标题模糊搜索（可选）.
            sort_by: 排序字段（narrative_position / time_value / title /
                updated_at / created_at）.
            sort_desc: 是否倒序.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (当前页事件列表, 符合条件的总记录数).
        """
        return await self._repo.list(
            project_id=_to_int_id(project_id),
            search=search,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )

    async def update_event(
        self, event_id: int | uuid.UUID, update: TimelineEventUpdate
    ) -> TimelineEvent | None:
        """部分更新事件（exclude_unset 语义，同 F1）.

        清除语义（spec §7/模型 docstring）: time_value "" → 置 None（清除
        世界内时间）；time_value None → 不修改；timeline_flag "" → 置 ""
        （清除标记，置为正叙）；其余字段 None → 不修改（title/description
        传 None 不修改，与未传入等价）.

        Args:
            event_id: 事件主键（支持 int 或 UUID）.
            update: 含待更新字段的 TimelineEventUpdate DTO.

        Returns:
            更新后的完整 TimelineEvent；事件不存在返回 None（router 转 404）.
        """
        eid = _to_int_id(event_id)
        existing = await self._repo.get(eid)
        if existing is None:
            return None
        updates = {k: v for k, v in update.model_dump(exclude_unset=True).items() if v is not None}
        if "time_value" in updates and updates["time_value"] == "":
            updates["time_value"] = None  # "" = 清除世界内时间（置为未知）
        merged = existing.model_copy(update=updates)
        logger.info("更新时间线事件: event_id=%s", event_id)
        return await self._repo.update(merged)

    async def soft_delete_event(self, event_id: int | uuid.UUID) -> bool:
        """软删除事件（spec §7: 事件不存在 → False，router 转 404）.

        Args:
            event_id: 事件主键（支持 int 或 UUID）.

        Returns:
            True 表示删除成功；False 表示未找到记录.
        """
        eid = _to_int_id(event_id)
        logger.info("软删除时间线事件: event_id=%s", event_id)
        return await self._repo.soft_delete(eid)

    async def restore_event(self, event_id: int | uuid.UUID) -> TimelineEvent | None:
        """恢复软删除事件（重复操作无毒，同 F1）.

        Args:
            event_id: 事件主键（支持 int 或 UUID）.

        Returns:
            恢复后的 TimelineEvent；事件不存在/未删除返回 None.
        """
        eid = _to_int_id(event_id)
        restored = await self._repo.restore(eid)
        if restored is not None:
            logger.info("恢复时间线事件: event_id=%s", event_id)
        return restored

    # ── 双线视图与一致性检查（spec §5）──────────────────────────

    async def get_timeline_view(self, project_id: uuid.UUID) -> TimelineView | None:
        """双线总览（spec §3.3/§5.2）— 同一批活动事件的两种投影.

        Args:
            project_id: 所属项目 UUID.

        Returns:
            TimelineView；项目不存在抛 ProjectNotFoundError（router 转 404）.

        Raises:
            ProjectNotFoundError: 项目不存在（router 层转 404）.
            TimelineServiceError: project_repo 未注入（配置错误）.
        """
        await self._ensure_project(project_id)
        events = await self._repo.list_all(_to_int_id(project_id))
        return TimelineView(
            project_id=project_id,
            total=len(events),
            event_timeline=_sort_event_timeline(events),
            narrative_order=events,
        )

    async def check_consistency(
        self, project_id: uuid.UUID, include_flashbacks: bool = True
    ) -> ConsistencyReport | None:
        """一致性检查（spec §5.3，确定性算法，无 LLM）— 相邻对扫描.

        对叙事顺序（list_all 已按 narrative_position ASC, created_at ASC
        稳定排序）上 time_value 均非 None 的相邻事件对 (A, B) 逐一比较：
        A.time_value > B.time_value 为逆序对，按 §5.4 分类：
        - next 标记 flashback → flashbacks（合法倒叙）
        - prev 标记 flashforward → flashbacks（合法插叙/预叙）
        - 否则 → conflicts（order_conflict，需修正）

        Args:
            project_id: 所属项目 UUID.
            include_flashbacks: True（默认）收集已声明的倒叙/插叙；
                False 时 flashbacks 返回空列表（conflicts/consistent 不受影响）.

        Returns:
            ConsistencyReport；项目不存在抛 ProjectNotFoundError（router 转 404）.

        Raises:
            ProjectNotFoundError: 项目不存在（router 层转 404）.
            TimelineServiceError: project_repo 未注入（配置错误）.
        """
        await self._ensure_project(project_id)
        events = await self._repo.list_all(_to_int_id(project_id))
        # 参与比较集合: 叙事顺序上 time_value 非 None 的事件（元组携带收窄后的
        # float 时间值，供 mypy 静态收窄；None 事件计入 skipped）
        seq = [(e, e.time_value) for e in events if e.time_value is not None]
        skipped = len(events) - len(seq)
        conflicts: list[TimelineConflict] = []
        flashbacks: list[TimelineConflict] = []
        for i in range(len(seq) - 1):
            (prev, prev_tv), (nxt, nxt_tv) = seq[i], seq[i + 1]
            if prev_tv <= nxt_tv:
                continue  # 正序/同刻：不冲突（§5.4）
            if nxt.timeline_flag == "flashback":
                if include_flashbacks:
                    flashbacks.append(
                        TimelineConflict(
                            conflict_type="flashback",
                            prev=_to_ref(prev),
                            next=_to_ref(nxt),
                            message=(
                                f"叙事第 {nxt.narrative_position} 位事件"
                                f"「{nxt.title}」声明为倒叙（flashback）："
                                f"其世界内时间（{_time_label(nxt)}）早于前叙事件"
                                f"（{_time_label(prev)}），已标记，判定合法。"
                            ),
                        )
                    )
            elif prev.timeline_flag == "flashforward":
                if include_flashbacks:
                    flashbacks.append(
                        TimelineConflict(
                            conflict_type="flashforward",
                            prev=_to_ref(prev),
                            next=_to_ref(nxt),
                            message=(
                                f"叙事第 {prev.narrative_position} 位事件"
                                f"「{prev.title}」声明为插叙（flashforward）："
                                f"其世界内时间（{_time_label(prev)}）晚于后叙事件"
                                f"（{_time_label(nxt)}），已标记，判定合法。"
                            ),
                        )
                    )
            else:
                conflicts.append(
                    TimelineConflict(
                        conflict_type="order_conflict",
                        prev=_to_ref(prev),
                        next=_to_ref(nxt),
                        message=(
                            f"叙事第 {prev.narrative_position} 位事件"
                            f"「{prev.title}」（{_time_label(prev)}）晚于叙事第"
                            f" {nxt.narrative_position} 位事件「{nxt.title}」"
                            f"（{_time_label(nxt)}）：叙事顺序与世界内时间矛盾。"
                            "若为倒叙/插叙请给后叙事件标记 "
                            "timeline_flag=flashback（或前叙事件标记 "
                            "flashforward）；否则请修正事件时间或叙事位置。"
                        ),
                    )
                )
        logger.info(
            "一致性检查: project=%s checked=%d skipped=%d conflicts=%d flashbacks=%d",
            project_id,
            len(seq),
            skipped,
            len(conflicts),
            len(flashbacks),
        )
        return ConsistencyReport(
            project_id=project_id,
            checked=len(seq),
            skipped=skipped,
            consistent=len(conflicts) == 0,
            conflicts=conflicts,
            flashbacks=flashbacks,
            event_timeline=_sort_event_timeline(events),
            narrative_order=events,
        )
