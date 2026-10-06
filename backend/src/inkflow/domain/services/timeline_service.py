"""F12 时间线业务服务 — 编排事件 CRUD + 双线视图 + 一致性检查.

职责（spec §5/§6/§7）:
- 事件 CRUD 编排：委托 TimelineRepositoryProtocol，负责领域层
  UUID ↔ 仓储层 int 转换（沿用 F1 `_to_uuid` 模式）
- 业务校验（422 语义，抛 TimelineServiceError 子类）: 本模块无冲突类
  校验（timeline_events 无唯一约束，见 spec §2.4）；配置错误（项目仓储
  未注入）同样抛 TimelineServiceError
- 资源不存在（404 语义）: 多数方法返回 None 由 router 层转 404；
  _ensure_project 校验失败抛 ProjectNotFoundError
- 双线视图（spec §5.2）: event_timeline 按 (归一日尺度 ASC NULLS LAST,
  narrative_position ASC) 排序；narrative_order 按叙事位置升序
  （list_all 已按 (narrative_position ASC, created_at ASC) 稳定排序）
- 一致性检查（spec §5.3，确定性算法，无 LLM）: 先按 §2.7 S2/S4 把
  time_value 从 time_unit 归一到「日」，再对叙事顺序上相邻且归一值均
  非 None 的事件对做相邻对扫描，报告全部逆序对；已声明
  flashback/flashforward 的逆序对计入 flashbacks（不影响 consistent），
  未声明的计入 conflicts

`#1409`：`time_unit` 不再是「仅语义」——它是 `time_value` 的物理尺度，
参与归一排序与比较（见 `_timeline_timebase`）。

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:
- repository: TimelineRepositoryProtocol（B1 已实现）
- project_repo: ProjectRepositoryProtocol（F1 已实现，项目存在性校验用）

依据: specs/f12-timeline/spec.md §5/§6/§7/§9。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime

from inkflow.domain.models.timeline import (
    ConsistencyReport,
    EventCheckReport,
    TimelineConflict,
    TimelineEvent,
    TimelineEventRef,
    TimelineEventUpdate,
    TimelineView,
    resolve_era_fields,
)
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.timeline_errors import (
    ProjectNotFoundError,
    TimelineServiceError,
)
from inkflow.domain.ports.timeline_repository import TimelineRepositoryProtocol
from inkflow.domain.services._data_change import publish_change
from inkflow.domain.services._timeline_timebase import (
    FLASHBACK_WORDS,
    FLASHFORWARD_WORDS,
    UNIT_DAYS,
    has_flag,
    normalized_days,
    to_days,
)
from inkflow.domain.services.era_conversion import to_global

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


def _to_uuid(value: int | uuid.UUID) -> uuid.UUID:
    """将 int 或 UUID 统一转为 uuid.UUID（#1291：仅兼容外部 int 入参，非仓库层中转）."""
    if isinstance(value, int):
        return uuid.UUID(int=value)
    return value


def _time_label(event: TimelineEvent) -> str:
    """事件时间的人类可读表达（#1409 拍板 3：必须含**当前** time_value）.

    形态：`time_display`（缺失时回退 `f"{原值}{time_unit}"`）+ `（time_value=原值）`；
    单位因子 ≠ 1 时追加 `，归一={days:g}日`（如 `3.0月（time_value=3.0），归一=90日`）。
    `time_display` 与 `time_unit` **都为空**时保持原行为 `str(time_value)`
    （向后兼容：既有精确消息断言依赖裸数值形态，见 U9）。
    """
    unit = (event.time_unit or "").strip()
    if not event.time_display and not unit:
        return str(event.time_value)
    base = event.time_display or f"{event.time_value}{event.time_unit}"
    label = f"{base}（time_value={event.time_value}）"
    days = to_days(event.time_value, event.time_unit)
    if days is not None and UNIT_DAYS.get(unit, 1.0) != 1.0:
        label += f"，归一={days:g}日"
    return label


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


def _global_scalar_keys(events: list[TimelineEvent]) -> dict[uuid.UUID, float | None]:
    """按 `era` **分桶**求**全局标量**比较键（spec §2.8 E11 / §5.3，v1.5 #1411）.

    - **默认轴**（`era == ""`）：§2.7 S2/S4 归一日尺度（`normalized_days`，**v1.4 口径不变**）；
    - **纪元轴**（`era != ""`）：`to_global(era, era_value, era_scale)` 换算后的**全局标量**
      （`era_value` 为 None → 键为 None，该事件按未知时间处置）。

    **跨桶**（`era` 不同）比较即在此口径上进行——两侧都已是全局量纲（ADR-065 §2.1）。
    换算只做**判定层只读投影**，不回写 `time_value`（spec §12 判定层/数据层分离）。

    Args:
        events: 事件序列（叙事序或任意序，键与顺序无关）.

    Returns:
        事件 id → 全局标量（None = 时间未知）。
    """
    days = normalized_days(events)
    return {
        e.id: (to_global(e.era, e.era_value, e.era_scale) if e.era else days.get(e.id))
        for e in events
    }


def _classify_pair(
    prev: TimelineEvent,
    nxt: TimelineEvent,
    keys: Mapping[uuid.UUID, float | None],
) -> TimelineConflict | None:
    """分类相邻事件对（spec §5.4）——check_consistency 与 check_event 共用.

    比较的是**归一日尺度**键 `keys`（§2.7 S2/S4：单位归一 + 时/时辰 日锚点），
    不再直接比较裸 `time_value`（否则「8 日 vs 3 月」会被误判为倒叙）。仅当双方
    归一值均已知且 `keys[prev] > keys[nxt]`（逆序对）时返回 TimelineConflict：
    next 标记倒叙 → flashback；prev 标记插叙 → flashforward；否则 →
    order_conflict。正序/同时刻/任一时间未知 → None（不参与比较）。

    🔴 #1323 G6：标记判定为**包含式**（``has_flag``），兼容中文自由文本
    （真实数据「倒叙/插叙」）与既有英文值（flashback/flashforward）。

    Args:
        prev: 叙事序中靠前的事件.
        nxt: 叙事序中靠后的事件.
        keys: 事件 id → 归一日尺度值（`normalized_days` 的输出）.

    Returns:
        逆序对的分类结果；正序/同时刻/时间未知返回 None.
    """
    prev_days = keys.get(prev.id)
    next_days = keys.get(nxt.id)
    if prev_days is None or next_days is None or prev_days <= next_days:
        return None
    if has_flag(nxt.timeline_flag, *FLASHBACK_WORDS):
        return TimelineConflict(
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
    if has_flag(prev.timeline_flag, *FLASHFORWARD_WORDS):
        return TimelineConflict(
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
    return TimelineConflict(
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


def _sort_event_timeline(events: list[TimelineEvent]) -> list[TimelineEvent]:
    """事件时间线视图排序（spec §5.2）: 归一日尺度 ASC NULLS LAST, narrative_position ASC。

    #1409：排序前按 `time_unit` 归一到「日」（§2.7 S2/S4）——不再比较裸
    `time_value`（否则「3 月」会排在「8 日」之前）。

    Args:
        events: 待排序的事件列表.

    Returns:
        排序后的新列表（不修改入参）.
    """
    keys = _global_scalar_keys(events)
    return sorted(
        events,
        key=lambda e: (keys.get(e.id) is None, keys.get(e.id), e.narrative_position),
    )


class TimelineService:
    """时间线业务服务 — 编排事件 CRUD、双线视图与一致性检查.

    Args:
        repository: 时间线事件仓储端口（B1）.
        project_repo: 项目仓储（F1），项目存在性校验用；默认 None 时
            依赖项目的入口报错（防止静默降级）.
        map_cleanup: 事件硬删钩子（F43 P5）：删除成功后解除 map_pins.ref_id
            （type=event）关联；失败由 deps 闭包处理，不阻断主流程.
    """

    def __init__(
        self,
        *,
        repository: TimelineRepositoryProtocol,
        project_repo: ProjectRepositoryProtocol | None = None,
        map_cleanup: Callable[[uuid.UUID], Awaitable[None]] | None = None,
    ) -> None:
        self._repo = repository
        self._project_repo = project_repo
        self._map_cleanup = map_cleanup

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
        project = await self._project_repo.get(project_id)
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
        era: str = "",
        era_value: float | str | None = None,
        era_scale: float = 1.0,
    ) -> TimelineEvent:
        """创建时间线事件（spec §2.1: narrative_position 缺省 = 叙事末尾追加）.

        Args:
            project_id: 所属项目 UUID（router 解析路径参数后传入）.
            title: 事件标题（TimelineEventCreate 已去空白校验）.
            description: 事件描述.
            time_value: 世界内时间数值键；None = 时间未知.
            time_unit: 时间单位（time_value 的尺度；参与归一排序，
                见 _timeline_timebase / spec §2.7）.
            time_display: 原始时间表达.
            narrative_position: 叙事位置；None = 先 next_position 再追加.
            timeline_flag: 时间线标记（""/flashback/flashforward）.
            era: 纪元轴名（"" = 不设纪元，#1353 §2.8 E1）.
            era_value: 纪元轴内值（None = 不设轴内值，#1353 §2.8 E2）.
            era_scale: 流速比（#1411 §2.8 E11；默认 1.0 = 与项目时基同速）.

        Returns:
            持久化后的完整 TimelineEvent.

        Raises:
            ProjectNotFoundError: 项目不存在（router 层转 404）.
            TimelineServiceError: project_repo 未注入（配置错误）.
        """
        await self._ensure_project(project_id)
        if narrative_position is None:
            narrative_position = await self._repo.next_position(project_id)
        now = _utcnow()
        # #1410 / §2.8 E4：纪元落**正式列**（v1.4；extra 不再承载纪元）
        resolved_era, resolved_era_value = resolve_era_fields("", None, era, era_value)
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
            era=resolved_era,
            era_value=resolved_era_value,
            era_scale=era_scale,
            created_at=now,
            updated_at=now,
        )
        logger.info(
            "创建时间线事件: project=%s title=%s position=%s",
            project_id,
            title,
            narrative_position,
        )
        created: TimelineEvent = await self._repo.add(event)
        await publish_change("timeline_event", "create", created.id, created.project_id)
        return created

    async def get_event(self, event_id: uuid.UUID) -> TimelineEvent | None:
        """按主键获取事件；不存在返回 None（router 转 404）."""
        return await self._repo.get(event_id)

    async def list_events(
        self,
        project_id: uuid.UUID,
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
        # #1151: 先判父项目存在——缺失 → 404；顺带防 128 位 int 走到过滤 SQL 绑定
        # 抛 OverflowError → 500（project_repo.get 自带 int64 守卫，#1139 同族口径）
        project_repo = self._project_repo
        if project_repo is not None and await project_repo.get(project_id) is None:
            raise ProjectNotFoundError()
        return await self._repo.list(
            project_id=project_id,
            search=search,
            sort_by=sort_by,
            sort_desc=sort_desc,
            offset=offset,
            limit=limit,
        )

    async def update_event(
        self, event_id: uuid.UUID, update: TimelineEventUpdate
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
        existing = await self._repo.get(event_id)
        if existing is None:
            return None
        updates = {k: v for k, v in update.model_dump(exclude_unset=True).items() if v is not None}
        updates.pop("era", None)
        updates.pop("era_value", None)
        if "time_value" in updates and updates["time_value"] == "":
            updates["time_value"] = None  # "" = 清除世界内时间（置为未知）
        merged = existing.model_copy(update=updates)
        # §2.8 E4 成对语义：写**正式列**（v1.4；extra 旧键不再承载纪元）
        era = update.era if "era" in update.model_fields_set else None
        era_value = update.era_value if "era_value" in update.model_fields_set else None
        resolved_era, resolved_era_value = resolve_era_fields(
            existing.era, existing.era_value, era, era_value
        )
        merged = merged.model_copy(update={"era": resolved_era, "era_value": resolved_era_value})
        logger.info("更新时间线事件: event_id=%s", event_id)
        updated: TimelineEvent | None = await self._repo.update(merged)
        if updated is not None:
            await publish_change("timeline_event", "update", updated.id, existing.project_id)
        return updated

    async def delete_event(self, event_id: int | uuid.UUID) -> bool:
        """真删事件（v1.1，spec §7: 事件不存在 → False，router 转 404）.

        F43 P5: 删除成功后触发 map_cleanup 钩子（解除 map_pins.ref_id 关联）。

        Args:
            event_id: 事件主键（支持 int 或 UUID）.

        Returns:
            True 表示删除成功；False 表示未找到记录.
        """
        eid = _to_uuid(event_id)
        logger.info("真删时间线事件: event_id=%s", event_id)
        deleted: bool = await self._repo.hard_delete(eid)
        if deleted and self._map_cleanup is not None:
            await self._map_cleanup(eid)
        if deleted:
            logger.warning(
                "timeline_event 删除事件缺 project_id"
                "（delete_event 未加载实体，spec §15.3.2）: id=%s",
                event_id,
            )
            await publish_change("timeline_event", "delete", event_id, None)
        return deleted

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
        events = await self._repo.list_all(project_id)
        return TimelineView(
            project_id=project_id,
            total=len(events),
            event_timeline=_sort_event_timeline(events),
            narrative_order=events,
        )

    async def check_event(self, event_id: uuid.UUID) -> EventCheckReport | None:
        """单事件检查（F43 P4 spec §2.9/§3.7）——报告该事件参与的相邻对逆序冲突.

        ① repo.get 取事件，不存在 → 返回 None（router 转 404）；
        ② 事件**全局标量**为 None（默认轴 `time_value=None` / 纪元轴 `era_value=None`）
           → checked=false、consistent=true、冲突为空（不参与检查，非冲突）；
        ③ repo.list_all(project_id) 取全部事件（已按 narrative_position ASC
           稳定排序），按 §2.8 E11 / §5.3 对**全量**事件算一次**全局标量**键
           `keys = _global_scalar_keys(events)`（默认轴归一日尺度；纪元轴
           `to_global` 换算；`时/时辰` 需序列上下文），定位
           该事件在叙事序中的位置 i；
        ④ 检查相邻对 (events[i-1], events[i]) 与 (events[i], events[i+1])，
           复用 _classify_pair（比较归一值，与 check_consistency 同口径）；
           该事件最多参与两对，两对的逆序冲突均计入；
        ⑤ 返回 EventCheckReport（consistent = conflicts 为空，flashbacks 不影响）.

        Args:
            event_id: 事件主键（支持 int 或 UUID）.

        Returns:
            EventCheckReport；事件不存在返回 None（router 转 404「事件不存在」）.
        """
        event: TimelineEvent | None = await self._repo.get(event_id)
        if event is None:
            return None
        events = await self._repo.list_all(event.project_id)
        keys = _global_scalar_keys(events)
        if keys.get(event.id) is None:
            # 全局标量未知（默认轴 time_value=None / 纪元轴 era_value=None）→ 不参与检查
            return EventCheckReport(
                event_id=event.id,
                checked=False,
                consistent=True,
                conflicts=[],
                flashbacks=[],
            )
        # 事件在叙事序中的位置 i（list_all 已按 narrative_position ASC 稳定排序）
        i = next((idx for idx, e in enumerate(events) if e.id == event.id), None)
        conflicts: list[TimelineConflict] = []
        flashbacks: list[TimelineConflict] = []
        if i is not None:
            if i > 0:
                conflict = _classify_pair(events[i - 1], events[i], keys)
                if conflict is not None:
                    if conflict.conflict_type in ("flashback", "flashforward"):
                        flashbacks.append(conflict)
                    else:
                        conflicts.append(conflict)
            if i + 1 < len(events):
                conflict = _classify_pair(events[i], events[i + 1], keys)
                if conflict is not None:
                    if conflict.conflict_type in ("flashback", "flashforward"):
                        flashbacks.append(conflict)
                    else:
                        conflicts.append(conflict)
        logger.info(
            "单事件检查: event=%s checked=True conflicts=%d flashbacks=%d",
            event.id,
            len(conflicts),
            len(flashbacks),
        )
        return EventCheckReport(
            event_id=event.id,
            checked=True,
            consistent=len(conflicts) == 0,
            conflicts=conflicts,
            flashbacks=flashbacks,
        )

    async def check_consistency(
        self, project_id: uuid.UUID, include_flashbacks: bool = True
    ) -> ConsistencyReport | None:
        """一致性检查（spec §5.3，确定性算法，无 LLM）— 相邻对扫描.

        先按 §2.8 E11 / §5.3 **按 `era` 分桶**求全局标量键
        （`keys = _global_scalar_keys(events)`：默认轴按 §2.7 S2/S4 归一到「日」，
        纪元轴用 `to_global` 换算；`时/时辰` 用叙事序上的日锚点），
        再对叙事顺序（list_all 已按 narrative_position ASC, created_at ASC
        稳定排序）上归一值均非 None 的相邻事件对 (A, B) 逐一比较：
        `keys[A] > keys[B]` 为逆序对，按 §5.4 分类：
        - next 标记 flashback → flashbacks（合法倒叙）
        - prev 标记 flashforward → flashbacks（合法插叙/预叙）
        - 否则 → conflicts（order_conflict，需修正）

        #1409：`time_unit` 参与比较（不再比较裸 `time_value`）——「8 日 → 3 月」
        归一后 `8 < 90` 为正序，不误报倒叙（§2.7 S3）。

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
        events = await self._repo.list_all(project_id)
        keys = _global_scalar_keys(events)
        # 参与比较集合: 叙事顺序上归一值非 None 的事件（#1409 §2.7 S2/S4；
        # time_value None → 归一值 None → 计入 skipped，语义与 v1.1 一致）
        seq = [e for e in events if keys.get(e.id) is not None]
        skipped = len(events) - len(seq)
        conflicts: list[TimelineConflict] = []
        flashbacks: list[TimelineConflict] = []
        for i in range(len(seq) - 1):
            conflict = _classify_pair(seq[i], seq[i + 1], keys)
            if conflict is None:
                continue  # 正序/同刻/时间未知：不冲突（§5.4）
            if conflict.conflict_type in ("flashback", "flashforward"):
                if include_flashbacks:
                    flashbacks.append(conflict)
            else:
                conflicts.append(conflict)
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
