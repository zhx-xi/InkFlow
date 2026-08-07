"""F24 会话服务单元测试 — Mock Repository（M3 CRUD + M4 状态机矩阵，RED→GREEN）.

覆盖 spec §9 服务测试/状态机专项 + §7 边界表:
- 创建: 默认 status=active / context/result {}；项目存在性校验（project_id 非 None 时
  前置校验先于创建，spec §7 #1）；project_id=None 跳过校验（§7 #2）
- get: 详情经 list_include_deleted（归档详情可读，§7 #7）+ 视图聚合（count_logs/last_log）
- list: 过滤透传（UUID→int 转换）+ 每项 SessionView 聚合
- update: exclude_unset 合并；status 不可经 update 修改（DTO 无 status 字段，
  extra=ignore 静默忽略 → 断言「status 不变」而非 422，F13 v1.1 教训）；缺失/归档 → None
- 状态机全矩阵: 4 状态 × 4 动作（§2.4/§7 #3/#4）+ 时间戳副产物（§5.2）
- 动作/日志端点对缺失或归档会话 → SessionNotFoundError（404，§7 #5/#6）
- 日志: seq 连续性（next_seq 服务层分配，1 起）；终态可追加（Q2 拍板，§7 #9）；
  list_logs 归档 → SessionNotFoundError（§7 #8）
- 删除两级: 首次 = 归档（soft_delete）、已归档再删 = 真实删除（hard_delete）、
  force=true 直删（§2.5/§7 #8b/#15）；restore 解除归档（幂等）

══════════════════════════════════════════════════════════════════════════
设计假设（实现者以本文件为准）:
- 服务类: inkflow.domain.services.session_service.SessionService
  构造: SessionService(repository: SessionRepositoryProtocol, project_repo:
  ProjectRepositoryProtocol | None = None)——project_repo 未注入且创建带
  project_id → SessionServiceError（配置错误防静默降级，同 F13）
- 方法签名（全部 async，session_id 均为领域 UUID，服务内部转 int 调仓储）:
  * create(data: SessionCreate) -> SessionView
  * get(session_id: uuid.UUID) -> SessionView | None        # list_include_deleted
  * list(session_type: SessionType | None = None, status: SessionStatus | None = None,
    project_id: uuid.UUID | None = None, search: str | None = None,
    offset: int = 0, limit: int = 50) -> tuple[list[SessionView], int]
  * update(session_id: uuid.UUID, data: SessionUpdate) -> Session | None  # repo.get(活动)
  * pause(session_id: uuid.UUID) -> Session
  * resume(session_id: uuid.UUID) -> Session
  * complete(session_id: uuid.UUID, data: SessionComplete) -> Session
  * fail(session_id: uuid.UUID, data: SessionFail) -> Session
  * delete(session_id: uuid.UUID, force: bool = False) -> bool
  * restore(session_id: uuid.UUID) -> Session | None        # 未归档幂等返回原对象
  * add_log(session_id: uuid.UUID, data: SessionLogCreate) -> SessionLogEntry
  * list_logs(session_id: uuid.UUID, offset: int = 0, limit: int = 50)
    -> tuple[list[SessionLogEntry], int]                    # 归档 → SessionNotFoundError
- 状态迁移表（§2.4）: active×{pause,complete,fail}=✅、paused×{resume,complete,fail}=✅、
  completed/failed×任意=❌、active×resume / paused×pause=❌
- 时间戳副产物（§5.2）: pause 写 paused_at=now；resume 清 paused_at=None；
  complete/fail 写 completed_at=now（统一终态时间戳）；complete 写 result、
  fail 写 error（同一事务）
- 迁移失败错误: SessionTransitionError(f"会话当前状态 {当前状态} 不允许 {动作}")
  （spec §3.4 示例文案格式「会话当前状态 completed 不允许 pause」）
- 错误类（inkflow.domain.ports.session_errors，spec §8.1）:
  SessionServiceError(Exception) 基类（422 语义）/ SessionNotFoundError(Exception)
  默认消息「会话不存在」（404 语义，不继承基类）/ SessionTransitionError(SessionServiceError)
  （422）。ProjectNotFoundError 复用 F9 inkflow.domain.ports.character_errors——
  本模块不定义不导出（陷阱 16）
- 服务透传 repo.list 调用为位置参数（session_type, status, project_id, search,
  offset, limit），枚举以 .value 字符串传递；project_id 转 int
- list 的视图聚合: 对每个会话调用 repo.count_logs(id) + repo.last_log(id) 构建
  SessionView；create 返回的视图 log_count=0 / last_log=None（新建无日志）
══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import Project
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
from inkflow.domain.ports import session_errors as session_errors_module
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.session_errors import (
    SessionNotFoundError,
    SessionServiceError,
    SessionTransitionError,
)
from inkflow.domain.ports.session_repository import SessionRepositoryProtocol
from inkflow.domain.services.session_service import SessionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
SID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _session(
    title: str = "第三章续写",
    *,
    status: SessionStatus = SessionStatus.ACTIVE,
    session_type: SessionType = SessionType.WRITING,
    paused_at: datetime | None = None,
    completed_at: datetime | None = None,
    is_deleted: bool = False,
    **kw,
) -> Session:
    """构造测试用会话实体（固定时间戳，便于断言）。"""
    return Session(
        id=SID,
        session_type=session_type,
        status=status,
        project_id=PID,
        title=title,
        paused_at=paused_at,
        completed_at=completed_at,
        is_deleted=is_deleted,
        started_at=TS,
        created_at=TS,
        updated_at=TS,
        **kw,
    )


def _project() -> Project:
    """构造测试用项目实体."""
    return Project(id=PID, name="测试项目", created_at=TS, updated_at=TS)


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock SessionRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=SessionRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.get = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=([], 0))
    repo.list_include_deleted = AsyncMock(return_value=None)
    repo.update = AsyncMock(side_effect=lambda s: s)
    repo.soft_delete = AsyncMock(return_value=True)
    repo.restore = AsyncMock(return_value=None)
    repo.hard_delete = AsyncMock(return_value=True)
    repo.add_log = AsyncMock(side_effect=lambda e: e)
    repo.next_seq = AsyncMock(return_value=1)
    repo.list_logs = AsyncMock(return_value=([], 0))
    repo.count_logs = AsyncMock(return_value=0)
    repo.last_log = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — 项目存在性校验（默认项目存在）。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=_project())
    return repo


@pytest.fixture
def service(mock_repo: MagicMock, mock_project_repo: MagicMock) -> SessionService:
    """被测服务实例（全 Mock 依赖注入）。"""
    return SessionService(repository=mock_repo, project_repo=mock_project_repo)


class TestErrorContract:
    """错误类层级契约（spec §8.1）。"""

    def test_error_class_hierarchy(self) -> None:
        """SessionTransitionError 继承 SessionServiceError；SessionNotFoundError 不继承
        （404 与 422 语义分离，同 F12/F13 惯例）。"""
        assert issubclass(SessionTransitionError, SessionServiceError)
        assert not issubclass(SessionNotFoundError, SessionServiceError)

    def test_not_found_default_message(self) -> None:
        """SessionNotFoundError 默认消息「会话不存在」（spec §3.4 detail）。"""
        assert str(SessionNotFoundError()) == "会话不存在"
        assert str(SessionNotFoundError("自定义")) == "自定义"

    def test_project_not_found_reused_from_f9(self) -> None:
        """ProjectNotFoundError 复用 F9 character_errors（陷阱 16：session_errors
        不定义不导出同名类，避免遮蔽既有 router except 链）。"""
        assert ProjectNotFoundError.__module__ == "inkflow.domain.ports.character_errors"
        assert str(ProjectNotFoundError()) == "项目不存在"
        assert not hasattr(session_errors_module, "ProjectNotFoundError")


class TestCreate:
    """会话创建 — 默认值 / 项目校验。"""

    async def test_create_defaults(self, service: SessionService, mock_repo: MagicMock) -> None:
        """最小创建: status=active、project_id 透传、未软删除、无日志."""
        created = await service.create(
            SessionCreate(session_type=SessionType.WRITING, project_id=PID, title="第三章续写")
        )
        assert isinstance(created, SessionView)
        assert created.session.status == SessionStatus.ACTIVE
        assert created.session.title == "第三章续写"
        assert created.session.project_id == PID
        assert created.session.context == {}
        assert created.session.result == {}
        assert created.session.error == ""
        assert created.session.is_deleted is False
        assert created.session.started_at is not None
        assert created.log_count == 0
        assert created.last_log is None

        added = mock_repo.add.await_args.args[0]
        assert isinstance(added, Session)
        assert added.id != SID  # 服务为新会话分配新 UUID
        assert added.session_type == SessionType.WRITING
        assert added.status == SessionStatus.ACTIVE
        assert added.paused_at is None
        assert added.completed_at is None

    async def test_create_project_checked_before_add(
        self, service: SessionService, mock_repo: MagicMock, mock_project_repo: MagicMock
    ) -> None:
        """project_id 非 None → project_repo.get(项目 int id) 前置校验（先于创建）."""
        await service.create(
            SessionCreate(session_type=SessionType.TASK, project_id=PID, title="每日定时写作")
        )
        mock_project_repo.get.assert_awaited_once_with(PID.int)
        mock_repo.add.assert_awaited_once()

    async def test_create_project_id_none_skips_validation(
        self, service: SessionService, mock_repo: MagicMock, mock_project_repo: MagicMock
    ) -> None:
        """project_id=None（全局会话）→ 不校验项目存在（spec §7 #2）."""
        created = await service.create(
            SessionCreate(session_type=SessionType.TASK, title="全局任务")
        )
        mock_project_repo.get.assert_not_awaited()
        assert created.session.project_id is None

    async def test_create_project_missing_raises(
        self, service: SessionService, mock_repo: MagicMock, mock_project_repo: MagicMock
    ) -> None:
        """项目不存在 → ProjectNotFoundError（404 语义），不落库（spec §7 #1）."""
        mock_project_repo.get = AsyncMock(return_value=None)
        with pytest.raises(ProjectNotFoundError):
            await service.create(
                SessionCreate(session_type=SessionType.TASK, project_id=PID, title="任务")
            )
        mock_repo.add.assert_not_awaited()

    async def test_create_project_repo_unconfigured_raises(self, mock_repo: MagicMock) -> None:
        """project_repo 未注入且携带 project_id → SessionServiceError（配置错误防静默降级）."""
        svc = SessionService(repository=mock_repo)
        with pytest.raises(SessionServiceError):
            await svc.create(
                SessionCreate(session_type=SessionType.TASK, project_id=PID, title="任务")
            )
        mock_repo.add.assert_not_awaited()


class TestGet:
    """会话详情 — 归档可追溯 + 视图聚合。"""

    async def test_get_returns_view_with_aggregation(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """get → SessionView；list_include_deleted + count_logs/last_log 聚合（spec §3.2）."""
        s = _session(status=SessionStatus.COMPLETED, completed_at=TS, result={"words": 1280})
        mock_repo.list_include_deleted = AsyncMock(return_value=s)
        mock_repo.count_logs = AsyncMock(return_value=5)
        last = SessionLogEntry(
            id=uuid.uuid4(), session_id=SID, seq=5, message="任务完成", created_at=TS
        )
        mock_repo.last_log = AsyncMock(return_value=last)

        view = await service.get(SID)
        assert view is not None
        assert view.session.id == SID
        assert view.session.status == SessionStatus.COMPLETED
        assert view.log_count == 5
        assert view.last_log is not None
        assert view.last_log.seq == 5
        mock_repo.list_include_deleted.assert_awaited_once_with(SID.int)
        mock_repo.count_logs.assert_awaited_once_with(SID.int)
        mock_repo.last_log.assert_awaited_once_with(SID.int)

    async def test_get_archived_session_readable(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """归档会话详情可读（spec §7 #7：详情可追溯，列表不显示）."""
        mock_repo.list_include_deleted = AsyncMock(return_value=_session(is_deleted=True))
        view = await service.get(SID)
        assert view is not None
        assert view.session.is_deleted is True

    async def test_get_missing_returns_none(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """会话不存在 → None（router 层转 404）."""
        assert await service.get(SID) is None


class TestList:
    """会话列表 — 过滤透传 + 视图聚合。"""

    async def test_list_passes_filters_and_aggregates(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """list → repo.list 位置透传（枚举 .value 字符串、project_id 转 int）+
        每项 count_logs/last_log 聚合构建 SessionView."""
        s1 = _session("每日定时写作", session_type=SessionType.TASK)
        s2 = _session("第三章续写", status=SessionStatus.COMPLETED)
        mock_repo.list = AsyncMock(return_value=([s1, s2], 2))

        views, total = await service.list(
            session_type=SessionType.TASK,
            status=SessionStatus.COMPLETED,
            project_id=PID,
            search="每日",
            offset=0,
            limit=20,
        )
        assert total == 2
        assert isinstance(views[0], SessionView)
        assert views[0].session.title == "每日定时写作"
        assert views[1].session.status == SessionStatus.COMPLETED
        mock_repo.list.assert_awaited_once_with("task", "completed", PID.int, "每日", 0, 20)
        assert mock_repo.count_logs.await_count == 2
        assert mock_repo.last_log.await_count == 2

    async def test_list_defaults(self, service: SessionService, mock_repo: MagicMock) -> None:
        """全缺省 → repo.list(None, None, None, None, 0, 50)（全量未归档）."""
        await service.list()
        mock_repo.list.assert_awaited_once_with(None, None, None, None, 0, 50)


class TestUpdate:
    """会话更新 — 部分更新 / status 不可改。"""

    async def test_update_merges_fields_and_keeps_status(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """update 只合并传入字段；status 不变（DTO 无 status，extra=ignore 静默忽略）."""
        mock_repo.get = AsyncMock(
            return_value=_session(description="旧描述", context={"mode": "continue"})
        )
        updated = await service.update(SID, SessionUpdate(title="第三章续写（改）"))
        assert updated is not None
        assert updated.title == "第三章续写（改）"
        assert updated.description == "旧描述"  # 未传字段不变
        assert updated.context == {"mode": "continue"}
        assert updated.status == SessionStatus.ACTIVE  # status 不变（非 422）

        call = mock_repo.update.await_args
        assert call.args[0].id == SID
        mock_repo.get.assert_awaited_once_with(SID.int)

    async def test_update_context_replaces_whole_dict(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """context 整体替换（spec §3.2：`context` 整体替换，未传字段不变）."""
        mock_repo.get = AsyncMock(
            return_value=_session(context={"mode": "continue", "style": "冷峻"})
        )
        updated = await service.update(SID, SessionUpdate(context={"mode": "revise"}))
        assert updated is not None
        assert updated.context == {"mode": "revise"}

    async def test_update_with_status_field_silently_ignored(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """PATCH 携带 status → 静默忽略（extra='ignore'），最终 status 不变（F13 v1.1 教训）."""
        mock_repo.get = AsyncMock(return_value=_session(status=SessionStatus.PAUSED))
        updated = await service.update(
            SID,
            SessionUpdate(title="新标题", status="completed"),  # type: ignore[call-arg]  # 故意传非法值断言 Pydantic 校验
        )
        assert updated is not None
        assert updated.status == SessionStatus.PAUSED
        assert updated.title == "新标题"

    async def test_update_empty_body_no_change(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """空 body {} → 200 无变化（spec §7 #11：不强制至少一个字段）."""
        mock_repo.get = AsyncMock(return_value=_session(title="原标题"))
        updated = await service.update(SID, SessionUpdate())
        assert updated is not None
        assert updated.title == "原标题"
        mock_repo.update.assert_awaited_once()

    async def test_update_missing_returns_none(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """会话不存在 → None（repo.get 不含软删，归档会话同样返回 None → 404）."""
        assert await service.update(SID, SessionUpdate(title="新标题")) is None
        mock_repo.update.assert_not_awaited()


# ── M4 状态机 ──

_ACTIONS = ("pause", "resume", "complete", "fail")

# (初始状态, 动作, 是否合法) 全组合（spec §2.4/§7 #3/#4）
_TRANSITION_MATRIX = [
    (SessionStatus.ACTIVE, "pause", True),
    (SessionStatus.ACTIVE, "resume", False),
    (SessionStatus.ACTIVE, "complete", True),
    (SessionStatus.ACTIVE, "fail", True),
    (SessionStatus.PAUSED, "pause", False),
    (SessionStatus.PAUSED, "resume", True),
    (SessionStatus.PAUSED, "complete", True),
    (SessionStatus.PAUSED, "fail", True),
    (SessionStatus.COMPLETED, "pause", False),
    (SessionStatus.COMPLETED, "resume", False),
    (SessionStatus.COMPLETED, "complete", False),
    (SessionStatus.COMPLETED, "fail", False),
    (SessionStatus.FAILED, "pause", False),
    (SessionStatus.FAILED, "resume", False),
    (SessionStatus.FAILED, "complete", False),
    (SessionStatus.FAILED, "fail", False),
]

_TARGET_STATUS = {
    "pause": SessionStatus.PAUSED,
    "resume": SessionStatus.ACTIVE,
    "complete": SessionStatus.COMPLETED,
    "fail": SessionStatus.FAILED,
}


class TestStateMachineMatrix:
    """状态机迁移矩阵（4 状态 × 4 动作全组合，spec §9 场景 1）。"""

    @pytest.mark.parametrize(("initial", "action", "valid"), _TRANSITION_MATRIX)
    async def test_transition_matrix(
        self,
        service: SessionService,
        mock_repo: MagicMock,
        initial: SessionStatus,
        action: str,
        valid: bool,
    ) -> None:
        """(状态, 动作) 组合合法性: 合法 → 迁移到目标状态；非法 → SessionTransitionError."""
        mock_repo.get = AsyncMock(return_value=_session(status=initial))

        async def _act():
            if action == "pause":
                return await service.pause(SID)
            if action == "resume":
                return await service.resume(SID)
            if action == "complete":
                return await service.complete(SID, SessionComplete())
            return await service.fail(SID, SessionFail(error="原因"))

        if valid:
            updated = await _act()
            assert updated.status == _TARGET_STATUS[action]
            mock_repo.update.assert_awaited_once()
        else:
            with pytest.raises(SessionTransitionError) as exc_info:
                await _act()
            # spec §3.4 文案格式: 「会话当前状态 {状态} 不允许 {动作}」
            assert str(exc_info.value) == f"会话当前状态 {initial.value} 不允许 {action}"
            mock_repo.update.assert_not_awaited()

    async def test_action_missing_session_raises_not_found(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """对不存在的会话调用任意动作 → SessionNotFoundError（spec §7 #5）."""
        for action in _ACTIONS:
            mock_repo.update.reset_mock()
            with pytest.raises(SessionNotFoundError):
                if action == "pause":
                    await service.pause(SID)
                elif action == "resume":
                    await service.resume(SID)
                elif action == "complete":
                    await service.complete(SID, SessionComplete())
                else:
                    await service.fail(SID, SessionFail(error="原因"))
            mock_repo.update.assert_not_awaited()

    async def test_action_archived_session_raises_not_found(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """对归档会话调用状态机动作 → SessionNotFoundError（repo.get 不含软删，spec §7 #6）."""
        mock_repo.get = AsyncMock(return_value=None)  # 归档会话对 get 不可见
        with pytest.raises(SessionNotFoundError):
            await service.pause(SID)


class TestTimestampSideEffects:
    """时间戳副产物（spec §5.2/§9 场景 2）。"""

    async def test_pause_writes_paused_at(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """pause（active→paused）写 paused_at=now."""
        mock_repo.get = AsyncMock(return_value=_session(status=SessionStatus.ACTIVE))
        updated = await service.pause(SID)
        assert updated.status == SessionStatus.PAUSED
        assert updated.paused_at is not None
        assert updated.completed_at is None

    async def test_resume_clears_paused_at(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """resume（paused→active）清空 paused_at（spec §3.3 响应 paused_at: null）."""
        mock_repo.get = AsyncMock(return_value=_session(status=SessionStatus.PAUSED, paused_at=TS))
        updated = await service.resume(SID)
        assert updated.status == SessionStatus.ACTIVE
        assert updated.paused_at is None

    async def test_complete_writes_completed_at_and_result(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """complete 写 completed_at=now 且 result 落库（spec §5.2 同一事务）."""
        mock_repo.get = AsyncMock(return_value=_session(status=SessionStatus.ACTIVE))
        updated = await service.complete(
            SID, SessionComplete(result={"words": 1280, "chapter_id": "7b9c"})
        )
        assert updated.status == SessionStatus.COMPLETED
        assert updated.completed_at is not None
        assert updated.result == {"words": 1280, "chapter_id": "7b9c"}

    async def test_complete_default_result_empty_dict(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """complete 不携带 result → {} 落库."""
        mock_repo.get = AsyncMock(return_value=_session(status=SessionStatus.ACTIVE))
        updated = await service.complete(SID, SessionComplete())
        assert updated.status == SessionStatus.COMPLETED
        assert updated.result == {}

    async def test_fail_writes_completed_at_and_error(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """fail 写 completed_at=now（统一终态时间戳）且 error 落库."""
        mock_repo.get = AsyncMock(return_value=_session(status=SessionStatus.PAUSED))
        updated = await service.fail(SID, SessionFail(error="LLM 调用超时"))
        assert updated.status == SessionStatus.FAILED
        assert updated.completed_at is not None
        assert updated.error == "LLM 调用超时"

    async def test_paused_session_can_complete(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """paused → completed 允许（用户暂停后直接完成，spec §2.4）."""
        mock_repo.get = AsyncMock(return_value=_session(status=SessionStatus.PAUSED, paused_at=TS))
        updated = await service.complete(SID, SessionComplete(result={"words": 500}))
        assert updated.status == SessionStatus.COMPLETED
        assert updated.completed_at is not None


class TestLogs:
    """履历日志 — seq 分配 / 终态可追加 / 归档 404。"""

    async def test_add_log_seq_continuous(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """连续追加 3 条 → seq=1,2,3（服务层经 next_seq 分配，spec §2.2/§9 场景 3）."""
        mock_repo.get = AsyncMock(return_value=_session())
        mock_repo.next_seq = AsyncMock(side_effect=[1, 2, 3])

        e1 = await service.add_log(SID, SessionLogCreate(message="任务开始"))
        e2 = await service.add_log(SID, SessionLogCreate(message="完成章节 3"))
        e3 = await service.add_log(
            SID,
            SessionLogCreate(
                level="warning",
                message="LLM 调用失败，重试第 2 次",
                payload={"attempt": 2},
            ),
        )
        assert [e1.seq, e2.seq, e3.seq] == [1, 2, 3]
        assert e3.level == "warning"
        assert e3.payload == {"attempt": 2}

        assert mock_repo.next_seq.await_count == 3
        assert mock_repo.add_log.await_count == 3
        entry = mock_repo.add_log.await_args.args[0]
        assert isinstance(entry, SessionLogEntry)
        assert entry.session_id == SID
        assert entry.message == "LLM 调用失败，重试第 2 次"
        assert entry.created_at is not None

    async def test_add_log_on_terminal_state_allowed(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """终态会话（completed）追加日志允许（Q2 拍板，履历补记，spec §7 #9）."""
        mock_repo.get = AsyncMock(
            return_value=_session(status=SessionStatus.COMPLETED, completed_at=TS)
        )
        entry = await service.add_log(SID, SessionLogCreate(message="任务完成，共 1280 字"))
        assert entry.seq == 1
        mock_repo.add_log.assert_awaited_once()

    async def test_add_log_missing_session_raises_not_found(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """对不存在的会话追加日志 → SessionNotFoundError（spec §7 #5）."""
        with pytest.raises(SessionNotFoundError):
            await service.add_log(SID, SessionLogCreate(message="消息"))
        mock_repo.add_log.assert_not_awaited()

    async def test_add_log_archived_session_raises_not_found(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """对归档会话追加日志 → SessionNotFoundError（spec §7 #6）."""
        mock_repo.get = AsyncMock(return_value=None)
        with pytest.raises(SessionNotFoundError):
            await service.add_log(SID, SessionLogCreate(message="消息"))

    async def test_list_logs_passthrough(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """list_logs 透传 repo（seq ASC，分页）."""
        mock_repo.list_include_deleted = AsyncMock(return_value=_session())
        entry = SessionLogEntry(
            id=uuid.uuid4(), session_id=SID, seq=1, message="开始", created_at=TS
        )
        mock_repo.list_logs = AsyncMock(return_value=([entry], 1))

        logs, total = await service.list_logs(SID, offset=0, limit=50)
        assert total == 1
        assert logs[0].message == "开始"
        mock_repo.list_logs.assert_awaited_once_with(SID.int, 0, 50)

    async def test_list_logs_missing_session_raises_not_found(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """对不存在的会话查日志 → SessionNotFoundError."""
        with pytest.raises(SessionNotFoundError):
            await service.list_logs(SID)

    async def test_list_logs_archived_session_raises_not_found(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """对归档会话查日志 → SessionNotFoundError（子资源跟随父归档 404，spec §7 #8）."""
        mock_repo.list_include_deleted = AsyncMock(return_value=_session(is_deleted=True))
        with pytest.raises(SessionNotFoundError):
            await service.list_logs(SID)


class TestDeleteRestore:
    """两级删除（spec §2.5）与解除归档。"""

    async def test_delete_first_time_archives(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """首次 DELETE（活动会话）→ soft_delete（归档）."""
        mock_repo.list_include_deleted = AsyncMock(return_value=_session(is_deleted=False))
        assert await service.delete(SID) is True
        mock_repo.soft_delete.assert_awaited_once_with(SID.int)
        mock_repo.hard_delete.assert_not_awaited()

    async def test_delete_archived_hard_deletes(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """已归档再 DELETE → 真实删除（物理 + 日志级联，spec §7 #8b）."""
        mock_repo.list_include_deleted = AsyncMock(return_value=_session(is_deleted=True))
        assert await service.delete(SID) is True
        mock_repo.hard_delete.assert_awaited_once_with(SID.int)
        mock_repo.soft_delete.assert_not_awaited()

    async def test_delete_force_hard_deletes_active(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """force=true 对活动会话直接真实删除（spec §2.5 显式通道）."""
        assert await service.delete(SID, force=True) is True
        mock_repo.hard_delete.assert_awaited_once_with(SID.int)
        mock_repo.soft_delete.assert_not_awaited()
        mock_repo.list_include_deleted.assert_not_awaited()

    async def test_delete_missing_returns_false(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """会话不存在 → False（router 层转 404）."""
        assert await service.delete(SID) is False
        mock_repo.soft_delete.assert_not_awaited()
        mock_repo.hard_delete.assert_not_awaited()

    async def test_restore_archived_session(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """restore 解除归档 → is_deleted=False 的会话."""
        mock_repo.list_include_deleted = AsyncMock(return_value=_session(is_deleted=True))
        mock_repo.restore = AsyncMock(return_value=_session(is_deleted=False))
        restored = await service.restore(SID)
        assert restored is not None
        assert restored.is_deleted is False
        mock_repo.restore.assert_awaited_once_with(SID.int)

    async def test_restore_active_session_idempotent(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """restore 未归档会话 → 幂等返回原对象（不调 repo.restore，同 F13 幂等语义）."""
        s = _session(is_deleted=False)
        mock_repo.list_include_deleted = AsyncMock(return_value=s)
        restored = await service.restore(SID)
        assert restored is not None
        assert restored.is_deleted is False
        mock_repo.restore.assert_not_awaited()

    async def test_restore_missing_returns_none(
        self, service: SessionService, mock_repo: MagicMock
    ) -> None:
        """会话不存在 → None."""
        assert await service.restore(SID) is None
        mock_repo.restore.assert_not_awaited()
