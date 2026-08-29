"""F24 会话业务服务 — 会话 CRUD + 四态状态机 + 履历日志.

职责（spec §2.4/§3.1/§5）:
- 会话 CRUD 编排：委托 SessionRepositoryProtocol，负责领域层 UUID ↔
  仓储层 int 转换（沿用 F1 `_to_int_id` 模式）
- 项目存在性校验（spec §7 #1）: project_id 非 None 时复用 F9
  ProjectRepositoryProtocol.get 校验存在性，失败 → ProjectNotFoundError
  （复用 F9 character_errors，不重复定义，陷阱 16）
- 四态状态机迁移（spec §2.4/§5.2）: pause（active→paused，写
  paused_at=now）/ resume（paused→active，清 paused_at）/ complete
  （active|paused→completed，写 completed_at=now + result）/ fail
  （active|paused→failed，写 completed_at=now + error）；终态不可逆，
  非法迁移 → SessionTransitionError
- 两级删除（spec §2.5）: 首次 DELETE 归档（soft_delete）、已归档再删 =
  真实删除（hard_delete）、force=true 直删；restore 解除归档（幂等）
- 履历日志（spec §2.2/§5.4）: add_log 服务层经 next_seq 分配 seq（1 起）；
  终态可追加（Q2 拍板）；list_logs 对归档会话抛 SessionNotFoundError
  （子资源跟随父归档 404，spec §7 #8）

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）:
- repository: SessionRepositoryProtocol
- project_repo: ProjectRepositoryProtocol（F1，项目存在性校验用；未注入
  且创建带 project_id → SessionServiceError 配置错误，防静默降级）

依据: specs/f24-session/spec.md §5/§7/§9。
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime
from typing import Any

from inkflow.domain.models.session import (
    Session,
    SessionComplete,
    SessionCreate,
    SessionFail,
    SessionLogCreate,
    SessionLogEntry,
    SessionStatus,
    SessionType,
    SessionUpdate,
    SessionView,
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.session_errors import (
    SessionNotFoundError,
    SessionServiceError,
    SessionTransitionError,
)
from inkflow.domain.ports.session_repository import SessionRepositoryProtocol


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）."""
    return datetime.now(UTC)


def _to_int_id(value: int | uuid.UUID) -> int:
    """将领域 UUID 转换为仓储层 int id（沿用 F1 `_to_int_id` 模式）."""
    if isinstance(value, uuid.UUID):
        return value.int
    return value


class SessionService:
    """会话业务服务 — 会话 CRUD、四态状态机与履历日志.

    Args:
        repository: 会话仓储端口.
        project_repo: 项目仓储（F1），创建带 project_id 时校验项目存在；
            默认 None 时携带 project_id 的创建入口报错（防止静默降级）.
    """

    def __init__(
        self,
        repository: SessionRepositoryProtocol,
        project_repo: ProjectRepositoryProtocol | None = None,
    ) -> None:
        self._repo = repository
        self._project_repo = project_repo

    # ── Session ─────────────────────────────────────────

    async def create(self, data: SessionCreate) -> SessionView:
        """创建会话（spec §2.4: 创建即 active；project_id 可空）.

        project_id 非 None 时前置校验项目存在（先于创建，spec §7 #1）；
        project_id=None（全局会话）跳过校验（spec §7 #2）。

        Args:
            data: 创建请求 DTO（status 不可传，创建即 active）.

        Returns:
            会话 + 履历摘要视图（新建无日志: log_count=0 / last_log=None）.

        Raises:
            SessionServiceError: project_repo 未注入且 project_id 非 None
                （配置错误，防静默降级）.
            ProjectNotFoundError: 项目不存在（复用 F9，router 层转 404）.
        """
        if data.project_id is not None:
            if self._project_repo is None:
                raise SessionServiceError("项目仓储未配置，无法校验项目存在性")
            project = await self._project_repo.get(_to_int_id(data.project_id))
            if project is None:
                raise ProjectNotFoundError()
        now = _utcnow()
        session = Session(
            id=uuid.uuid4(),
            session_type=data.session_type,
            status=SessionStatus.ACTIVE,
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            context=data.context,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        created = await self._repo.add(session)
        return SessionView(session=created, log_count=0, last_log=None)

    async def get(self, session_id: uuid.UUID) -> SessionView | None:
        """按主键获取会话详情（含已归档，履历可追溯；spec §7 #7）.

        Args:
            session_id: 会话领域 UUID.

        Returns:
            SessionView（含 count_logs/last_log 聚合）；不存在返回 None
            （router 层转 404）.
        """
        sid = _to_int_id(session_id)
        session = await self._repo.list_include_deleted(sid)
        if session is None:
            return None
        return await self._to_view(session)

    async def list(
        self,
        session_type: SessionType | None = None,
        status: SessionStatus | None = None,
        project_id: uuid.UUID | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> tuple[builtins.list[SessionView], int]:
        """分页查询活动会话列表（过滤透传 + 每项视图聚合）.

        Args:
            session_type: 会话类型精确过滤（枚举 .value 字符串；不传 = 全部）.
            status: 状态精确过滤（枚举 .value 字符串；不传 = 全部）.
            project_id: 项目 UUID 精确过滤（转 int 透传；不传 = 全部）.
            search: 标题不区分大小写子串匹配（可选）.
            offset: 分页偏移.
            limit: 分页大小.
            include_deleted: True = 含已归档全量（活动 + 归档一起返回）；默认 False
                保持既有活动列表语义（#486 会话页需列出/恢复已归档会话）.

        Returns:
            (当前页 SessionView 列表, 符合条件的总记录数).
        """
        sessions, total = await self._repo.list(
            session_type.value if session_type is not None else None,
            status.value if status is not None else None,
            _to_int_id(project_id) if project_id is not None else None,
            search,
            offset,
            limit,
            include_deleted=include_deleted,
        )
        views = [await self._to_view(s) for s in sessions]
        return views, total

    async def update(self, session_id: uuid.UUID, data: SessionUpdate) -> Session | None:
        """部分更新会话（exclude_unset 合并；status 不可经 update 修改）.

        None = 不修改（与未传入等价，同 F12/F13 update 模式）；空 body
        {} 合法无变化（spec §7 #11）。缺失/归档会话（repo.get 不含软删）
        → None（router 层转 404）。

        Args:
            session_id: 会话领域 UUID.
            data: 含待更新字段的 SessionUpdate DTO.

        Returns:
            更新后的完整 Session；会话不存在返回 None.
        """
        sid = _to_int_id(session_id)
        existing = await self._repo.get(sid)
        if existing is None:
            return None
        updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
        merged = existing.model_copy(update=updates)
        return await self._repo.update(merged)

    # ── 状态机动作 ─────────────────────────────────────

    async def _transition(
        self,
        session_id: uuid.UUID,
        action: str,
        allowed: tuple[SessionStatus, ...],
        updates: dict[str, Any],
    ) -> Session:
        """状态机动作公共路径: 存在性 → 迁移合法性 → 合并落库.

        校验顺序（spec §7 #5/#6）: 先查会话存在（repo.get 不含软删，缺失
        或归档 → SessionNotFoundError），再校验迁移合法性（非法 →
        SessionTransitionError，文案「会话当前状态 {状态} 不允许 {动作}」）.
        """
        sid = _to_int_id(session_id)
        existing = await self._repo.get(sid)
        if existing is None:
            raise SessionNotFoundError()
        if existing.status not in allowed:
            raise SessionTransitionError(f"会话当前状态 {existing.status.value} 不允许 {action}")
        merged = existing.model_copy(update=updates)
        return await self._repo.update(merged)

    async def pause(self, session_id: uuid.UUID) -> Session:
        """暂停会话（active→paused；写 paused_at=now，spec §5.2）."""
        return await self._transition(
            session_id,
            "pause",
            (SessionStatus.ACTIVE,),
            {"status": SessionStatus.PAUSED, "paused_at": _utcnow()},
        )

    async def resume(self, session_id: uuid.UUID) -> Session:
        """恢复会话（paused→active；清 paused_at，spec §3.3 响应 null）."""
        return await self._transition(
            session_id,
            "resume",
            (SessionStatus.PAUSED,),
            {"status": SessionStatus.ACTIVE, "paused_at": None},
        )

    async def complete(self, session_id: uuid.UUID, data: SessionComplete) -> Session:
        """完成会话（active|paused→completed；写 completed_at=now + result）."""
        return await self._transition(
            session_id,
            "complete",
            (SessionStatus.ACTIVE, SessionStatus.PAUSED),
            {
                "status": SessionStatus.COMPLETED,
                "completed_at": _utcnow(),
                "result": data.result,
            },
        )

    async def fail(self, session_id: uuid.UUID, data: SessionFail) -> Session:
        """失败会话（active|paused→failed；写 completed_at=now + error）."""
        return await self._transition(
            session_id,
            "fail",
            (SessionStatus.ACTIVE, SessionStatus.PAUSED),
            {
                "status": SessionStatus.FAILED,
                "completed_at": _utcnow(),
                "error": data.error,
            },
        )

    # ── 删除 / 恢复 ────────────────────────────────────

    async def delete(self, session_id: uuid.UUID, force: bool = False) -> bool:
        """删除会话（spec §2.5 两级）: 首次归档、已归档再删 = 真实删除.

        force=true 对任意会话直接真实删除（显式通道，不查归档状态）。

        Args:
            session_id: 会话领域 UUID.
            force: True 时直接真实删除（spec §2.5）.

        Returns:
            True 表示删除成功（归档或真实删除）；False 表示会话不存在
            （router 层转 404）.
        """
        sid = _to_int_id(session_id)
        if force:
            return await self._repo.hard_delete(sid)
        existing = await self._repo.list_include_deleted(sid)
        if existing is None:
            return False
        if existing.is_deleted:
            return await self._repo.hard_delete(sid)
        return await self._repo.soft_delete(sid)

    async def restore(self, session_id: uuid.UUID) -> Session | None:
        """解除归档（spec §2.5；未归档幂等返回原对象）.

        Args:
            session_id: 会话领域 UUID.

        Returns:
            恢复后的 Session（is_deleted=False）；不存在返回 None
            （router 层转 404）.
        """
        sid = _to_int_id(session_id)
        existing = await self._repo.list_include_deleted(sid)
        if existing is None:
            return None
        if not existing.is_deleted:
            return existing  # 幂等: 不调 repo.restore，原对象原样返回
        return await self._repo.restore(sid)

    # ── 履历日志 ───────────────────────────────────────

    async def add_log(self, session_id: uuid.UUID, data: SessionLogCreate) -> SessionLogEntry:
        """追加履历日志（seq 服务层经 next_seq 分配；终态可追加）.

        Args:
            session_id: 会话领域 UUID.
            data: 日志请求 DTO.

        Returns:
            持久化后的 SessionLogEntry.

        Raises:
            SessionNotFoundError: 会话不存在/已归档（spec §7 #5/#6）.
        """
        sid = _to_int_id(session_id)
        existing = await self._repo.get(sid)
        if existing is None:
            raise SessionNotFoundError()
        seq = await self._repo.next_seq(sid)
        entry = SessionLogEntry(
            id=uuid.uuid4(),
            session_id=session_id,
            seq=seq,
            level=data.level,
            message=data.message,
            payload=data.payload,
            created_at=_utcnow(),
        )
        return await self._repo.add_log(entry)

    async def list_logs(
        self,
        session_id: uuid.UUID,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[builtins.list[SessionLogEntry], int]:
        """分页查询会话履历日志（seq ASC，透传 repo）.

        Args:
            session_id: 会话领域 UUID.
            offset: 分页偏移.
            limit: 分页大小.

        Returns:
            (当前页日志列表, 总条数).

        Raises:
            SessionNotFoundError: 会话不存在或已归档（spec §7 #8）.
        """
        sid = _to_int_id(session_id)
        existing = await self._repo.list_include_deleted(sid)
        if existing is None or existing.is_deleted:
            raise SessionNotFoundError()
        return await self._repo.list_logs(sid, offset, limit)

    # ── 视图聚合 ───────────────────────────────────────

    async def _to_view(self, session: Session) -> SessionView:
        """构建会话视图: 聚合 count_logs / last_log（spec §3.2）."""
        sid = _to_int_id(session.id)
        log_count = await self._repo.count_logs(sid)
        last_log = await self._repo.last_log(sid)
        return SessionView(session=session, log_count=log_count, last_log=last_log)
