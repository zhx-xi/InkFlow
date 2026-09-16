"""SessionService 数据面变更事件测试（#1090 批次 B；spec §15.3.2/§15.3.3/§15.6.4）。

契约来源：W3C 设计裁定表 §2.7（父侧单一真相源）+ spec §15.3.3 四不变量。
- create 成功 → session/create（project_id 可为 None = 全局会话，前端天然视为全局生效）。
- update 成功 → session/update；不存在（None）→ 零发布。
- _transition（pause/resume/complete/fail 公共路径）末尾一处接入 → 四个状态机动作统一发
  session/update（§15.6.4 op 语义边界）；NotFound / 非法迁移走异常 → 零发布。
- delete：非 force（已加载实体）→ project_id 非 None；**force=True 薄透传** → None + warning。
- restore **仅真实恢复**（is_deleted=True → repo.restore）；未归档幂等分支 → 不发。
- add_log **不发**（高频履历追加，§15.6.1 高频噪声裁决）。

依赖全 Mock 注入（镜像 test_session_service.py 的 fixture 形态）。
RED 阶段预期：正例断言 FAIL，负例可能已 PASS。
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
    SessionStatus,
    SessionType,
    SessionUpdate,
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.ports.session_errors import SessionNotFoundError, SessionTransitionError
from inkflow.domain.ports.session_repository import SessionRepositoryProtocol
from inkflow.domain.services.session_service import SessionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
SID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)
LOGGER_NAME = "inkflow.domain.services.session_service"


def _session(
    *,
    status: SessionStatus = SessionStatus.ACTIVE,
    is_deleted: bool = False,
    project_id: uuid.UUID | None = PID,
) -> Session:
    """构造测试用会话实体（固定时间戳，便于断言）。"""
    return Session(
        id=SID,
        session_type=SessionType.WRITING,
        status=status,
        project_id=project_id,
        title="第三章续写",
        is_deleted=is_deleted,
        started_at=TS,
        created_at=TS,
        updated_at=TS,
    )


def _project() -> Project:
    """构造测试用项目实体。"""
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


class TestSessionCrudDataChange:
    """会话 CRUD 写路径发布事件。"""

    async def test_create_publishes_create(self, service: SessionService, recorded_events) -> None:
        """create 成功 → session/create，project_id 取会话实体。"""
        view = await service.create(
            SessionCreate(session_type=SessionType.WRITING, project_id=PID, title="续写")
        )

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("session", "create")
        assert event.resource_id == str(view.session.id)
        assert event.project_id == str(PID)

    async def test_create_global_session_publishes_none_project_id(
        self, service: SessionService, recorded_events
    ) -> None:
        """全局会话（project_id=None）→ 事件 project_id None（前端视为全局生效）。"""
        view = await service.create(
            SessionCreate(session_type=SessionType.WRITING, project_id=None, title="全局会话")
        )

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("session", "create")
        assert event.resource_id == str(view.session.id)
        assert event.project_id is None

    async def test_create_project_missing_publishes_nothing(
        self,
        service: SessionService,
        mock_project_repo: MagicMock,
        recorded_events,
    ) -> None:
        """反例：项目不存在（写失败）→ 零发布。"""
        mock_project_repo.get = AsyncMock(return_value=None)

        with pytest.raises(ProjectNotFoundError):
            await service.create(
                SessionCreate(session_type=SessionType.WRITING, project_id=PID, title="续写")
            )

        assert recorded_events == []

    async def test_update_publishes_update(
        self, service: SessionService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """update 成功 → session/update，project_id 从已加载实体解析。"""
        mock_repo.get = AsyncMock(return_value=_session())

        updated = await service.update(SID, SessionUpdate(title="第三章续写（改）"))

        assert updated is not None
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("session", "update")
        assert event.resource_id == str(SID)
        assert event.project_id == str(PID)

    async def test_update_missing_publishes_nothing(
        self, service: SessionService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：会话不存在（返回 None）→ 零发布。"""
        mock_repo.get = AsyncMock(return_value=None)

        assert await service.update(SID, SessionUpdate(title="x")) is None
        assert recorded_events == []

    async def test_add_log_publishes_nothing(
        self, service: SessionService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """add_log **不发**（高频履历追加，§15.6.1 高频噪声裁决）。"""
        mock_repo.get = AsyncMock(return_value=_session())

        entry = await service.add_log(SID, SessionLogCreate(message="开始执行"))

        assert entry is not None
        assert recorded_events == []


class TestTransitionDataChange:
    """四态状态机公共路径（_transition）发布 session/update。"""

    @pytest.mark.parametrize(
        ("action", "current", "call"),
        [
            ("pause", SessionStatus.ACTIVE, lambda svc: svc.pause(SID)),
            ("resume", SessionStatus.PAUSED, lambda svc: svc.resume(SID)),
            ("complete", SessionStatus.ACTIVE, lambda svc: svc.complete(SID, SessionComplete())),
            (
                "fail",
                SessionStatus.PAUSED,
                lambda svc: svc.fail(SID, SessionFail(error="模型超时")),
            ),
        ],
    )
    async def test_transition_publishes_update(
        self,
        service: SessionService,
        mock_repo: MagicMock,
        recorded_events,
        action: str,
        current: SessionStatus,
        call,
    ) -> None:
        """pause/resume/complete/fail 真实迁移 → 统一发 session/update（一处接入覆盖四动作）。"""
        mock_repo.get = AsyncMock(return_value=_session(status=current))

        await call(service)

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("session", "update")
        assert event.resource_id == str(SID)
        assert event.project_id == str(PID)

    async def test_transition_illegal_publishes_nothing(
        self, service: SessionService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：非法迁移（已 completed 再 pause）→ 异常，零发布。"""
        mock_repo.get = AsyncMock(return_value=_session(status=SessionStatus.COMPLETED))

        with pytest.raises(SessionTransitionError):
            await service.pause(SID)

        assert recorded_events == []

    async def test_transition_missing_publishes_nothing(
        self, service: SessionService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：会话不存在（异常）→ 零发布。"""
        mock_repo.get = AsyncMock(return_value=None)

        with pytest.raises(SessionNotFoundError):
            await service.pause(SID)

        assert recorded_events == []


class TestDeleteAndRestoreDataChange:
    """两级删除 / 恢复的发布契约。"""

    async def test_delete_soft_publishes_delete_with_entity_project_id(
        self, service: SessionService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """首次删除 = 归档（soft_delete）→ session/delete，project_id 从已加载实体解析。"""
        mock_repo.list_include_deleted = AsyncMock(return_value=_session())

        assert await service.delete(SID) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("session", "delete")
        assert event.resource_id == str(SID)
        assert event.project_id == str(PID)

    async def test_delete_archived_hard_publishes_delete(
        self, service: SessionService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """已归档再删 = 真实删除（hard_delete）→ session/delete，project_id 非 None。"""
        mock_repo.list_include_deleted = AsyncMock(return_value=_session(is_deleted=True))

        assert await service.delete(SID) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("session", "delete")
        assert event.resource_id == str(SID)
        assert event.project_id == str(PID)

    async def test_delete_missing_publishes_nothing(
        self, service: SessionService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：会话不存在（返回 False）→ 零发布。"""
        mock_repo.list_include_deleted = AsyncMock(return_value=None)

        assert await service.delete(SID) is False
        assert recorded_events == []

    async def test_delete_force_publishes_none_project_id_with_warning(
        self, service: SessionService, mock_repo: MagicMock, recorded_events, caplog
    ) -> None:
        """force=True 薄透传（不查归档状态）→ None + warning（spec §15.3.2 已知例外）。"""
        caplog.set_level("WARNING", logger=LOGGER_NAME)

        assert await service.delete(SID, force=True) is True

        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("session", "delete")
        assert event.resource_id == str(SID)
        assert event.project_id is None
        assert any("project_id" in record.getMessage() for record in caplog.records)

    async def test_restore_publishes_update(
        self, service: SessionService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """restore 真实恢复（is_deleted=True → repo.restore）→ session/update。"""
        archived = _session(is_deleted=True)
        restored = _session(is_deleted=False)
        mock_repo.list_include_deleted = AsyncMock(return_value=archived)
        mock_repo.restore = AsyncMock(return_value=restored)

        result = await service.restore(SID)

        assert result is restored
        assert len(recorded_events) == 1
        event = recorded_events[0]
        assert (event.domain, event.op) == ("session", "update")
        assert event.resource_id == str(SID)
        assert event.project_id == str(PID)

    async def test_restore_not_archived_publishes_nothing(
        self, service: SessionService, mock_repo: MagicMock, recorded_events
    ) -> None:
        """反例：未归档幂等分支（不调 repo.restore）→ 零发布。"""
        mock_repo.list_include_deleted = AsyncMock(return_value=_session(is_deleted=False))

        assert await service.restore(SID) is not None
        assert recorded_events == []
