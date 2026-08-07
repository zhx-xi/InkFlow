"""F24 会话管理 API 测试 — Mock Service 层（M5 RED→GREEN）。

测试范围 (spec §3 契约 + §9 API 测试 + §7 边界表):
- 12 端点成功路径（201/200/204）: 创建/列表/详情/更新/pause/resume/complete/fail/
  日志追加/日志列表/删除两级/restore
- 404 全路径: 会话不存在（详情/动作/日志/删除）、无效 UUID → 404「会话不存在」、
  创建时项目不存在 → 404「项目不存在」（跨模块错误复用，spec §7 #1/#6/#8）
- 422: Pydantic 字段校验（空白标题、非法 session_type）、非法状态迁移
  （SessionTransitionError → 422，detail 透传）、分页越界（limit=0 / >200）
- PATCH 携带 status → 静默忽略（200，status 不变——extra='ignore'，spec §7 #10）
- 删除两级: 首次 DELETE → 204 归档；?force=true → 204 真实删除；不存在 → 404
- DB_ERROR → 500 {"detail": "数据库错误"}（spec §3.4）

══════════════════════════════════════════════════════════════════════════
设计假设（实现者以本文件为准）:
- 路由模块: inkflow.api.routers.sessions（router = APIRouter(prefix="/api/v1")，
  注册进 inkflow.api.app）；服务获取函数 get_session_service（自 inkflow.api.deps
  导入，测试 patch 路由模块本地绑定 `inkflow.api.routers.sessions.get_session_service`，
  同 F12/F13 模式）
- 端点与方法映射（服务方法一律关键字参数调用）:
  * POST /api/v1/sessions → svc.create(data=SessionCreate) → 201 SessionView
  * GET /api/v1/sessions → svc.list(session_type=, status=, project_id=, search=,
    offset=, limit=) → 200 {items, total, offset, limit}（items 为 SessionView 数组）
  * GET /api/v1/sessions/{id} → svc.get(session_id=) → 200 SessionView（归档可读）
  * PATCH /api/v1/sessions/{id} → svc.update(session_id=, data=SessionUpdate) → 200 Session
  * POST .../pause|resume → svc.pause/resume(session_id=) → 200 Session
  * POST .../complete → svc.complete(session_id=, data=SessionComplete) → 200 Session
  * POST .../fail → svc.fail(session_id=, data=SessionFail) → 200 Session
  * POST .../logs → svc.add_log(session_id=, data=SessionLogCreate) → 201 SessionLogEntry
  * GET .../logs → svc.list_logs(session_id=, offset=, limit=) → 200
    {items, total, offset, limit}
  * DELETE /api/v1/sessions/{id}[?force=true] → svc.delete(session_id=, force=) → 204
  * POST .../restore → svc.restore(session_id=) → 200 Session
- 错误映射: SessionNotFoundError / F9 ProjectNotFoundError → 404（detail = str(e)）；
  SessionServiceError（含 SessionTransitionError）→ 422（detail = str(e)）；
  其余异常 → 500 {"detail": "数据库错误"}
- 路径参数 UUID 解析失败 → 404「会话不存在」（同 F12 _parse_id 模式）
- Query 校验: offset ≥ 0；limit 默认 50、1 ≤ limit ≤ 200（spec §6.3）；越界 → 422
- 分页查询 project_id 为 UUID（路由解析后以 UUID 传服务，服务转 int）
══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.models.session import (
    LogLevel,
    Session,
    SessionLogEntry,
    SessionStatus,
    SessionType,
    SessionView,
)
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.session_errors import (
    SessionNotFoundError,
    SessionTransitionError,
)

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _session(**overrides: object) -> Session:
    """构造测试用会话实体（固定时间戳，便于断言）。"""
    kwargs: dict[str, object] = {
        "id": uuid.uuid4(),
        "session_type": SessionType.WRITING,
        "status": SessionStatus.ACTIVE,
        "project_id": PID,
        "title": "第三章续写",
        "description": "续写第三章，接上一章结尾",
        "context": {"chapter_id": "7b9c", "mode": "continue"},
        "result": {},
        "error": "",
        "started_at": TS,
        "paused_at": None,
        "completed_at": None,
        "is_deleted": False,
        "created_at": TS,
        "updated_at": TS,
    }
    kwargs.update(overrides)
    return Session(**kwargs)  # type: ignore[arg-type]  # kwargs 覆盖字段类型由测试意图保证


def _log_entry(seq: int = 1, **overrides: object) -> SessionLogEntry:
    """构造测试用日志条目实体。"""
    kwargs: dict[str, object] = {
        "id": uuid.uuid4(),
        "session_id": _session().id,
        "seq": seq,
        "level": LogLevel.INFO,
        "message": "开始写作章节 3",
        "payload": {"progress": 0.1},
        "created_at": TS,
    }
    kwargs.update(overrides)
    return SessionLogEntry(**kwargs)  # type: ignore[arg-type]  # kwargs 覆盖字段类型由测试意图保证


def _view(**overrides: object) -> SessionView:
    """构造会话详情/列表项视图."""
    kwargs: dict[str, object] = {"session": _session(), "log_count": 0, "last_log": None}
    kwargs.update(overrides)
    return SessionView(**kwargs)  # type: ignore[arg-type]  # kwargs 覆盖字段类型由测试意图保证


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock SessionService。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestCreateSessionAPI:
    """创建会话端点（POST /api/v1/sessions）。"""

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_create_session_success_201(self, mock_get_svc: MagicMock) -> None:
        """创建返回 201 + SessionView JSON（session/log_count/last_log 同构）."""
        svc = _mock_svc(mock_get_svc)
        svc.create = AsyncMock(return_value=_view(log_count=0))

        response = client.post(
            "/api/v1/sessions",
            json={
                "session_type": "writing",
                "project_id": str(PID),
                "title": "第三章续写",
                "description": "续写第三章",
                "context": {"chapter_id": "7b9c", "mode": "continue"},
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["session"]["title"] == "第三章续写"
        assert data["session"]["status"] == "active"
        assert data["session"]["project_id"] == str(PID)
        assert data["session"]["result"] == {}
        assert data["session"]["is_deleted"] is False
        assert data["log_count"] == 0
        assert data["last_log"] is None

        call = svc.create.await_args
        from inkflow.domain.models.session import SessionCreate

        create_data: SessionCreate = call.kwargs["data"]
        assert create_data.session_type == SessionType.WRITING
        assert create_data.project_id == PID
        assert create_data.title == "第三章续写"
        assert create_data.context == {"chapter_id": "7b9c", "mode": "continue"}

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_create_session_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """创建时项目不存在 → 404「项目不存在」（跨模块错误复用: sessions router
        except F9 ProjectNotFoundError，spec §7 #1/§9 场景 6，而非 500）."""
        svc = _mock_svc(mock_get_svc)
        svc.create = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            "/api/v1/sessions",
            json={"session_type": "task", "project_id": str(PID), "title": "每日定时写作"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_create_session_blank_title_422(self) -> None:
        """标题为空白返回 422（Pydantic 校验）."""
        response = client.post(
            "/api/v1/sessions",
            json={"session_type": "writing", "title": "   "},
        )
        assert response.status_code == 422
        assert "会话标题不能为空" in response.text

    def test_create_session_invalid_type_422(self) -> None:
        """session_type 非法值返回 422."""
        response = client.post(
            "/api/v1/sessions",
            json={"session_type": "bogus", "title": "标题"},
        )
        assert response.status_code == 422

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_create_session_db_error_500(self, mock_get_svc: MagicMock) -> None:
        """服务抛未知异常 → 500 {"detail": "数据库错误"}（spec §3.4 DB_ERROR）."""
        svc = _mock_svc(mock_get_svc)
        svc.create = AsyncMock(side_effect=RuntimeError("boom"))

        response = client.post(
            "/api/v1/sessions",
            json={"session_type": "writing", "title": "标题"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "数据库错误"


class TestListSessionsAPI:
    """会话列表端点（GET /api/v1/sessions）。"""

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_list_sessions_success(self, mock_get_svc: MagicMock) -> None:
        """列表返回 200 + {items, total, offset, limit}（items 为 SessionView 数组）."""
        svc = _mock_svc(mock_get_svc)
        view = _view(log_count=5)
        svc.list = AsyncMock(return_value=([view], 1))

        response = client.get(
            "/api/v1/sessions",
            params={
                "session_type": "task",
                "status": "completed",
                "project_id": str(PID),
                "search": "每日",
                "offset": 0,
                "limit": 20,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 20
        assert data["items"][0]["session"]["title"] == "第三章续写"
        assert data["items"][0]["log_count"] == 5
        svc.list.assert_awaited_once_with(
            session_type="task",
            status="completed",
            project_id=PID,
            search="每日",
            offset=0,
            limit=20,
        )

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_list_sessions_default_params(self, mock_get_svc: MagicMock) -> None:
        """无过滤参数 → 服务默认参数（全量未归档）."""
        svc = _mock_svc(mock_get_svc)
        svc.list = AsyncMock(return_value=([], 0))

        response = client.get("/api/v1/sessions")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "offset": 0, "limit": 50}
        svc.list.assert_awaited_once_with(
            session_type=None, status=None, project_id=None, search=None, offset=0, limit=50
        )

    def test_list_sessions_invalid_pagination_422(self) -> None:
        """分页越界（limit=0 / limit=201）返回 422（spec §6.3: limit 默认 50 上限 200）."""
        r1 = client.get("/api/v1/sessions", params={"limit": 0})
        assert r1.status_code == 422
        r2 = client.get("/api/v1/sessions", params={"limit": 201})
        assert r2.status_code == 422


class TestGetSessionAPI:
    """会话详情端点（GET /api/v1/sessions/{session_id}）。"""

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_get_session_success_200(self, mock_get_svc: MagicMock) -> None:
        """详情返回 200 + SessionView JSON（含 last_log）."""
        svc = _mock_svc(mock_get_svc)
        sid = uuid.uuid4()
        svc.get = AsyncMock(
            return_value=_view(session=_session(id=sid), log_count=2, last_log=_log_entry(seq=2))
        )

        response = client.get(f"/api/v1/sessions/{sid}")
        assert response.status_code == 200
        data = response.json()
        assert data["session"]["id"] == str(sid)
        assert data["log_count"] == 2
        assert data["last_log"]["seq"] == 2
        svc.get.assert_awaited_once_with(session_id=sid)

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_get_session_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """会话不存在返回 404「会话不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.get = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/sessions/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "会话不存在"

    def test_get_session_invalid_uuid_404(self) -> None:
        """无效 UUID 格式返回 404「会话不存在」."""
        response = client.get("/api/v1/sessions/not-a-uuid")
        assert response.status_code == 404
        assert response.json()["detail"] == "会话不存在"


class TestUpdateSessionAPI:
    """更新会话端点（PATCH /api/v1/sessions/{session_id}）。"""

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_update_session_success_200(self, mock_get_svc: MagicMock) -> None:
        """更新返回 200 + Session JSON（title/description/context 透传）."""
        svc = _mock_svc(mock_get_svc)
        sid = uuid.uuid4()
        svc.update = AsyncMock(
            return_value=_session(title="第三章续写（改）", context={"mode": "revise"})
        )

        response = client.patch(
            f"/api/v1/sessions/{sid}",
            json={"title": "第三章续写（改）", "context": {"mode": "revise"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "第三章续写（改）"
        assert data["context"] == {"mode": "revise"}

        call = svc.update.await_args
        from inkflow.domain.models.session import SessionUpdate

        assert call.kwargs["session_id"] == sid
        upd: SessionUpdate = call.kwargs["data"]
        assert upd.title == "第三章续写（改）"
        assert upd.description is None
        assert "context" in upd.model_fields_set

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_update_session_status_ignored(self, mock_get_svc: MagicMock) -> None:
        """PATCH 携带 status → 静默忽略（extra='ignore'），status 不变（spec §7 #10）."""
        svc = _mock_svc(mock_get_svc)
        svc.update = AsyncMock(return_value=_session(title="新标题", status=SessionStatus.ACTIVE))
        sid = uuid.uuid4()

        response = client.patch(
            f"/api/v1/sessions/{sid}", json={"title": "新标题", "status": "completed"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "active"  # status 未被修改

        from inkflow.domain.models.session import SessionUpdate

        upd: SessionUpdate = svc.update.await_args.kwargs["data"]
        assert "status" not in upd.model_fields_set

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_update_session_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """会话不存在返回 404."""
        svc = _mock_svc(mock_get_svc)
        svc.update = AsyncMock(return_value=None)

        response = client.patch(f"/api/v1/sessions/{uuid.uuid4()}", json={"title": "新标题"})
        assert response.status_code == 404
        assert response.json()["detail"] == "会话不存在"


class TestStateMachineAPI:
    """状态机动作端点（pause/resume/complete/fail）。"""

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_pause_success_200(self, mock_get_svc: MagicMock) -> None:
        """pause 返回 200 + paused 状态的 Session（paused_at 已填）."""
        svc = _mock_svc(mock_get_svc)
        sid = uuid.uuid4()
        svc.pause = AsyncMock(return_value=_session(status=SessionStatus.PAUSED, paused_at=TS))

        response = client.post(f"/api/v1/sessions/{sid}/pause")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "paused"
        assert data["paused_at"] == "2026-08-01T10:00:00Z"
        svc.pause.assert_awaited_once_with(session_id=sid)

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_resume_success_200(self, mock_get_svc: MagicMock) -> None:
        """resume 返回 200 + active 状态（paused_at 清空）."""
        svc = _mock_svc(mock_get_svc)
        svc.resume = AsyncMock(return_value=_session(status=SessionStatus.ACTIVE, paused_at=None))

        response = client.post(f"/api/v1/sessions/{uuid.uuid4()}/resume")
        assert response.status_code == 200
        assert response.json()["status"] == "active"
        assert response.json()["paused_at"] is None

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_complete_success_200(self, mock_get_svc: MagicMock) -> None:
        """complete 携带 result 返回 200 + completed 状态（result/completed_at 已写）."""
        svc = _mock_svc(mock_get_svc)
        sid = uuid.uuid4()
        svc.complete = AsyncMock(
            return_value=_session(
                status=SessionStatus.COMPLETED,
                completed_at=TS,
                result={"words": 1280, "chapter_id": "7b9c"},
            )
        )

        response = client.post(
            f"/api/v1/sessions/{sid}/complete",
            json={"result": {"words": 1280, "chapter_id": "7b9c"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"] == {"words": 1280, "chapter_id": "7b9c"}
        assert data["completed_at"] == "2026-08-01T10:00:00Z"

        call = svc.complete.await_args
        from inkflow.domain.models.session import SessionComplete

        assert call.kwargs["session_id"] == sid
        complete_data: SessionComplete = call.kwargs["data"]
        assert complete_data.result == {"words": 1280, "chapter_id": "7b9c"}

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_fail_success_200(self, mock_get_svc: MagicMock) -> None:
        """fail 携带 error 返回 200 + failed 状态（error/completed_at 已写）."""
        svc = _mock_svc(mock_get_svc)
        sid = uuid.uuid4()
        svc.fail = AsyncMock(
            return_value=_session(
                status=SessionStatus.FAILED, completed_at=TS, error="LLM 调用超时"
            )
        )

        response = client.post(f"/api/v1/sessions/{sid}/fail", json={"error": "LLM 调用超时"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["error"] == "LLM 调用超时"

        from inkflow.domain.models.session import SessionFail

        fail_data: SessionFail = svc.fail.await_args.kwargs["data"]
        assert fail_data.error == "LLM 调用超时"

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_illegal_transition_422(self, mock_get_svc: MagicMock) -> None:
        """非法迁移（如 paused×pause）→ 422，detail 为 SessionTransitionError 消息."""
        svc = _mock_svc(mock_get_svc)
        svc.pause = AsyncMock(
            side_effect=SessionTransitionError("会话当前状态 paused 不允许 pause")
        )

        response = client.post(f"/api/v1/sessions/{uuid.uuid4()}/pause")
        assert response.status_code == 422
        assert response.json()["detail"] == "会话当前状态 paused 不允许 pause"

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_action_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """动作端点对不存在的会话 → 404（SessionNotFoundError 语义）."""
        svc = _mock_svc(mock_get_svc)
        svc.pause = AsyncMock(side_effect=SessionNotFoundError())

        response = client.post(f"/api/v1/sessions/{uuid.uuid4()}/pause")
        assert response.status_code == 404
        assert response.json()["detail"] == "会话不存在"

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_fail_blank_error_422(self, mock_get_svc: MagicMock) -> None:
        """fail 的 error 为空 → 422（Pydantic 校验，服务不被调用）."""
        svc = _mock_svc(mock_get_svc)
        response = client.post(f"/api/v1/sessions/{uuid.uuid4()}/fail", json={"error": "   "})
        assert response.status_code == 422
        assert "失败原因不能为空" in response.text
        # 裸 MagicMock 无 assert_not_awaited（AsyncMock 专属），assert_not_called 语义等价
        svc.fail.assert_not_called()


class TestLogsAPI:
    """日志子资源端点（POST/GET /api/v1/sessions/{session_id}/logs）。"""

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_add_log_success_201(self, mock_get_svc: MagicMock) -> None:
        """追加日志返回 201 + SessionLogEntry JSON（seq 由服务分配）."""
        svc = _mock_svc(mock_get_svc)
        sid = uuid.uuid4()
        svc.add_log = AsyncMock(
            return_value=_log_entry(seq=1, message="开始写作章节 3", payload={"progress": 0.1})
        )

        response = client.post(
            f"/api/v1/sessions/{sid}/logs",
            json={"level": "info", "message": "开始写作章节 3", "payload": {"progress": 0.1}},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["seq"] == 1
        assert data["message"] == "开始写作章节 3"
        assert data["payload"] == {"progress": 0.1}

        call = svc.add_log.await_args
        from inkflow.domain.models.session import SessionLogCreate

        assert call.kwargs["session_id"] == sid
        log_data: SessionLogCreate = call.kwargs["data"]
        assert log_data.message == "开始写作章节 3"
        assert log_data.payload == {"progress": 0.1}

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_list_logs_success_200(self, mock_get_svc: MagicMock) -> None:
        """日志列表返回 200 + {items, total, offset, limit}（seq ASC）."""
        svc = _mock_svc(mock_get_svc)
        sid = uuid.uuid4()
        svc.list_logs = AsyncMock(
            return_value=([_log_entry(seq=1), _log_entry(seq=2, message="重试")], 2)
        )

        response = client.get(f"/api/v1/sessions/{sid}/logs", params={"offset": 0, "limit": 50})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["offset"] == 0
        assert data["limit"] == 50
        assert [item["seq"] for item in data["items"]] == [1, 2]
        svc.list_logs.assert_awaited_once_with(session_id=sid, offset=0, limit=50)

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_list_logs_archived_404(self, mock_get_svc: MagicMock) -> None:
        """归档会话查日志 → 404（子资源跟随父归档，spec §7 #8）."""
        svc = _mock_svc(mock_get_svc)
        svc.list_logs = AsyncMock(side_effect=SessionNotFoundError())

        response = client.get(f"/api/v1/sessions/{uuid.uuid4()}/logs")
        assert response.status_code == 404
        assert response.json()["detail"] == "会话不存在"

    def test_add_log_blank_message_422(self) -> None:
        """日志消息为空白 → 422（spec §7 #12）."""
        response = client.post(f"/api/v1/sessions/{uuid.uuid4()}/logs", json={"message": "   "})
        assert response.status_code == 422
        assert "日志消息不能为空" in response.text


class TestDeleteRestoreAPI:
    """删除两级 + 恢复端点（DELETE / POST restore）。"""

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_delete_first_time_204(self, mock_get_svc: MagicMock) -> None:
        """首次 DELETE → 204 归档（svc.delete(force=False)）."""
        svc = _mock_svc(mock_get_svc)
        sid = uuid.uuid4()
        svc.delete = AsyncMock(return_value=True)

        response = client.delete(f"/api/v1/sessions/{sid}")
        assert response.status_code == 204
        svc.delete.assert_awaited_once_with(session_id=sid, force=False)

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_delete_force_true_204(self, mock_get_svc: MagicMock) -> None:
        """?force=true → 204 真实删除（svc.delete(force=True)）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete = AsyncMock(return_value=True)

        response = client.delete(f"/api/v1/sessions/{uuid.uuid4()}?force=true")
        assert response.status_code == 204
        svc.delete.assert_awaited_once_with(
            session_id=svc.delete.await_args.kwargs["session_id"], force=True
        )

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_delete_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """会话不存在 → 404."""
        svc = _mock_svc(mock_get_svc)
        svc.delete = AsyncMock(return_value=False)

        response = client.delete(f"/api/v1/sessions/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "会话不存在"

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_restore_success_200(self, mock_get_svc: MagicMock) -> None:
        """restore 返回 200 + 解除归档的 Session（is_deleted=False）."""
        svc = _mock_svc(mock_get_svc)
        sid = uuid.uuid4()
        svc.restore = AsyncMock(return_value=_session(is_deleted=False))

        response = client.post(f"/api/v1/sessions/{sid}/restore")
        assert response.status_code == 200
        assert response.json()["is_deleted"] is False
        svc.restore.assert_awaited_once_with(session_id=sid)

    @patch("inkflow.api.routers.sessions.get_session_service")
    def test_restore_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """会话不存在 → 404."""
        svc = _mock_svc(mock_get_svc)
        svc.restore = AsyncMock(return_value=None)

        response = client.post(f"/api/v1/sessions/{uuid.uuid4()}/restore")
        assert response.status_code == 404
        assert response.json()["detail"] == "会话不存在"
