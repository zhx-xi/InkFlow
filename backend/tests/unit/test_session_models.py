"""F24 会话管理领域模型单元测试 — 无 I/O，纯 Pydantic 验证（M1 RED→GREEN）.

测试范围（spec §2.6 + §9 测试策略「领域模型」）:
- SessionType / SessionStatus / LogLevel 枚举值
- Session 实体默认值与必填字段
- SessionCreate / SessionUpdate 标题去空白 1-100、描述 ≤5000、context 默认 {}
- SessionUpdate 部分更新语义 + status 字段被静默忽略（extra='ignore'，F13 v1.1 教训）
- SessionLogEntry / SessionLogCreate 消息 1-2000 去空白、payload 默认 {}
- SessionComplete result 默认 {} / SessionFail error 非空 ≤2000
- SessionView（session + log_count + last_log）构造与 JSON roundtrip
- Session/SessionView JSON 序列化（UUID/datetime → str/ISO）

══════════════════════════════════════════════════════════════════════════
设计假设（实现者以本文件为准，spec §2.6 原文逐字段一致）:
- 模块路径: inkflow.domain.models.session
- 枚举: SessionType(WRITING="writing"/TASK="task")、SessionStatus(ACTIVE="active"/
  PAUSED="paused"/COMPLETED="completed"/FAILED="failed")、LogLevel(INFO="info"/
  WARNING="warning"/ERROR="error")，均为 str 子类枚举（StrEnum，可 JSON 序列化）
- 校验器错误文案（精确匹配）:
  * 标题: "会话标题不能为空" / "会话标题不能超过 100 个字符"（strip 后 len 判断）
  * 描述: "会话描述不能超过 5000 个字符"（不 strip）
  * 消息: "日志消息不能为空" / "日志消息不能超过 2000 个字符"（strip 后 len 判断）
  * 失败原因: "失败原因不能为空" / "失败原因不能超过 2000 个字符"（strip 后 len 判断）
- SessionUpdate 显式校验 title/description（None 原样返回）；status 非字段 →
  Pydantic v2 默认 extra='ignore' 静默丢弃（本文件断言「不报错且 status 不入
  model_fields_set」，不做 422 断言——F13 v1.1 教训）
- SessionView: session: Session / log_count: int / last_log: SessionLogEntry | None = None
══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from inkflow.domain.models.session import (
    LogLevel,
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

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
SID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


def _session(**overrides: object) -> Session:
    """构造测试用会话实体（固定时间戳，便于断言）。"""
    kwargs: dict[str, object] = {
        "id": SID,
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


def _log_entry(**overrides: object) -> SessionLogEntry:
    """构造测试用日志条目实体。"""
    kwargs: dict[str, object] = {
        "id": uuid.uuid4(),
        "session_id": SID,
        "seq": 1,
        "level": LogLevel.INFO,
        "message": "开始写作章节 3",
        "payload": {"chapter_id": "7b9c", "progress": 0.1},
        "created_at": TS,
    }
    kwargs.update(overrides)
    return SessionLogEntry(**kwargs)  # type: ignore[arg-type]  # kwargs 覆盖字段类型由测试意图保证


class TestEnums:
    """三个枚举的值契约（spec §2.3/§2.4/§2.2）。"""

    def test_session_type_values(self) -> None:
        """SessionType: writing / task."""
        assert SessionType.WRITING == "writing"
        assert SessionType.TASK == "task"
        assert len(SessionType) == 2

    def test_session_status_values(self) -> None:
        """SessionStatus: active / paused / completed / failed."""
        assert SessionStatus.ACTIVE == "active"
        assert SessionStatus.PAUSED == "paused"
        assert SessionStatus.COMPLETED == "completed"
        assert SessionStatus.FAILED == "failed"
        assert len(SessionStatus) == 4

    def test_log_level_values(self) -> None:
        """LogLevel: info / warning / error."""
        assert LogLevel.INFO == "info"
        assert LogLevel.WARNING == "warning"
        assert LogLevel.ERROR == "error"
        assert len(LogLevel) == 3


class TestSessionModel:
    """Session 领域实体（spec §2.1）。"""

    def test_session_defaults(self) -> None:
        """默认值: status=active, project_id=None, description='', context={},
        result={}, error='', paused_at=None, completed_at=None, is_deleted=False."""
        session = Session(
            id=SID,
            session_type=SessionType.TASK,
            title="每日定时写作",
            started_at=TS,
            created_at=TS,
            updated_at=TS,
        )
        assert session.status == SessionStatus.ACTIVE
        assert session.project_id is None
        assert session.description == ""
        assert session.context == {}
        assert session.result == {}
        assert session.error == ""
        assert session.paused_at is None
        assert session.completed_at is None
        assert session.is_deleted is False

    def test_session_required_fields(self) -> None:
        """缺少必填字段（title）应抛出 ValidationError."""
        with pytest.raises(ValidationError):
            Session(
                id=SID,
                session_type=SessionType.WRITING,
                started_at=TS,
                created_at=TS,
                updated_at=TS,
            )

    def test_session_context_result_default_factory_isolation(self) -> None:
        """context/result 默认 {} 且实例间互不共享（default_factory 语义）."""

        def _bare() -> Session:
            return Session(
                id=uuid.uuid4(),
                session_type=SessionType.TASK,
                title="每日定时写作",
                started_at=TS,
                created_at=TS,
                updated_at=TS,
            )

        a = _bare()
        b = _bare()
        a.context["k"] = "v"
        assert a.context == {"k": "v"}
        assert b.context == {}  # 实例间不共享（非可变默认值陷阱）
        assert b.result == {}

    def test_session_json_roundtrip(self) -> None:
        """Session → JSON（UUID/datetime 序列化）→ 反序列化字段一致."""
        session = _session(
            status=SessionStatus.PAUSED,
            paused_at=TS,
            completed_at=None,
            is_deleted=False,
        )
        payload = json.dumps(session.model_dump(mode="json"))
        restored = Session.model_validate(json.loads(payload))
        assert restored == session
        assert restored.id == SID
        assert restored.paused_at == TS
        # JSON 形态: id 为字符串、时间为 ISO 8601
        raw = session.model_dump(mode="json")
        assert isinstance(raw["id"], str)
        assert raw["started_at"] == "2026-08-01T10:00:00Z"


class TestSessionCreateValidation:
    """SessionCreate 请求 DTO（spec §2.6）。"""

    def test_create_valid_and_strips_title(self) -> None:
        """合法创建: title 去空白、description 默认 ''、context 默认 {}、project_id 可空."""
        dto = SessionCreate(
            session_type=SessionType.WRITING,
            title="  第三章续写  ",
            description="续写第三章",
            context={"mode": "continue"},
        )
        assert dto.title == "第三章续写"
        assert dto.description == "续写第三章"
        assert dto.context == {"mode": "continue"}
        assert dto.project_id is None

    def test_create_project_id_allowed(self) -> None:
        """project_id 显式传入保留（全局/挂项目两态，Q1 拍板可空）."""
        dto = SessionCreate(session_type=SessionType.TASK, title="每日定时写作", project_id=PID)
        assert dto.project_id == PID

    def test_create_empty_title_raises(self) -> None:
        """空标题 → ValidationError."""
        with pytest.raises(ValidationError, match="会话标题不能为空"):
            SessionCreate(session_type=SessionType.WRITING, title="")

    def test_create_whitespace_title_raises(self) -> None:
        """纯空白标题 → ValidationError."""
        with pytest.raises(ValidationError, match="会话标题不能为空"):
            SessionCreate(session_type=SessionType.WRITING, title="   ")

    def test_create_title_too_long_raises(self) -> None:
        """超过 100 字符的标题 → ValidationError."""
        with pytest.raises(ValidationError, match="会话标题不能超过 100 个字符"):
            SessionCreate(session_type=SessionType.WRITING, title="长" * 101)

    def test_create_title_100_chars_ok(self) -> None:
        """恰好 100 字符的标题合法."""
        dto = SessionCreate(session_type=SessionType.WRITING, title="题" * 100)
        assert dto.title == "题" * 100

    def test_create_description_too_long_raises(self) -> None:
        """超过 5000 字符的 description → ValidationError."""
        with pytest.raises(ValidationError, match="会话描述不能超过 5000 个字符"):
            SessionCreate(session_type=SessionType.WRITING, title="标题", description="文" * 5001)

    def test_create_context_must_be_dict(self) -> None:
        """context 非 dict → ValidationError."""
        with pytest.raises(ValidationError):
            SessionCreate(session_type=SessionType.WRITING, title="标题", context=["not", "dict"])

    def test_create_invalid_session_type_raises(self) -> None:
        """session_type 非法值 → ValidationError."""
        with pytest.raises(ValidationError):
            SessionCreate(session_type="bogus", title="标题")  # type: ignore[arg-type]  # kwargs 覆盖字段类型由测试意图保证


class TestSessionUpdate:
    """SessionUpdate 部分更新语义（spec §2.6/§7 #10）。"""

    def test_update_partial_semantics(self) -> None:
        """未传入的字段保持 None，且不出现在 model_fields_set."""
        update = SessionUpdate(title="新标题")
        assert update.title == "新标题"
        assert update.description is None
        assert update.context is None
        assert "description" not in update.model_fields_set

    def test_update_empty_body_all_fields_none(self) -> None:
        """空 body {} 合法（全字段 None，200 无变化语义，spec §7 #11）."""
        update = SessionUpdate()
        assert update.title is None
        assert update.description is None
        assert update.context is None

    def test_update_title_stripped(self) -> None:
        """update 的 title 同样去空白."""
        update = SessionUpdate(title="  新标题  ")
        assert update.title == "新标题"

    def test_update_blank_title_raises(self) -> None:
        """update 的 title 为空/纯空白 → ValidationError."""
        with pytest.raises(ValidationError, match="会话标题不能为空"):
            SessionUpdate(title="   ")

    def test_update_description_too_long_raises(self) -> None:
        """update 的 description 超过 5000 → ValidationError."""
        with pytest.raises(ValidationError, match="会话描述不能超过 5000 个字符"):
            SessionUpdate(description="文" * 5001)

    def test_update_status_field_silently_ignored(self) -> None:
        """携带 status 字段 → 静默忽略（extra='ignore'），status 不入 model_fields_set.

        F13 v1.1 教训: 断言「被忽略」而非「422」——状态机走动作端点，PATCH 不许改 status.
        """
        update = SessionUpdate(title="新标题", status="completed")  # type: ignore[call-arg]  # 故意传非法值断言 Pydantic 校验
        assert update.title == "新标题"
        assert "status" not in update.model_fields_set
        # 构造不抛错（extra=ignore 而非 forbid）
        assert update.model_dump() == {"title": "新标题", "description": None, "context": None}


class TestSessionLogEntry:
    """SessionLogEntry 日志子实体（spec §2.2）。"""

    def test_log_entry_defaults(self) -> None:
        """默认值: level=info, payload={}."""
        entry = SessionLogEntry(
            id=uuid.uuid4(),
            session_id=SID,
            seq=1,
            message="开始写作章节 3",
            created_at=TS,
        )
        assert entry.level == LogLevel.INFO
        assert entry.payload == {}

    def test_log_entry_seq_required(self) -> None:
        """缺少 seq → ValidationError."""
        with pytest.raises(ValidationError):
            SessionLogEntry(id=uuid.uuid4(), session_id=SID, message="消息", created_at=TS)

    def test_log_entry_json_roundtrip(self) -> None:
        """SessionLogEntry JSON roundtrip（UUID/枚举/datetime 序列化）."""
        entry = _log_entry(level=LogLevel.WARNING, payload={"attempt": 2})
        raw = json.loads(json.dumps(entry.model_dump(mode="json")))
        restored = SessionLogEntry.model_validate(raw)
        assert restored == entry


class TestSessionLogCreateValidation:
    """SessionLogCreate 请求 DTO（spec §2.2/§7 #12）。"""

    def test_log_create_valid_and_strips_message(self) -> None:
        """合法: message 去空白、level 默认 info、payload 默认 {}."""
        dto = SessionLogCreate(level=LogLevel.WARNING, message="  LLM 调用失败，重试第 2 次  ")
        assert dto.message == "LLM 调用失败，重试第 2 次"
        assert dto.level == LogLevel.WARNING
        assert dto.payload == {}

    def test_log_create_default_level_info(self) -> None:
        """level 缺省 = info."""
        dto = SessionLogCreate(message="任务开始")
        assert dto.level == LogLevel.INFO

    def test_log_create_empty_message_raises(self) -> None:
        """空消息 → ValidationError."""
        with pytest.raises(ValidationError, match="日志消息不能为空"):
            SessionLogCreate(message="")

    def test_log_create_whitespace_message_raises(self) -> None:
        """纯空白消息 → ValidationError."""
        with pytest.raises(ValidationError, match="日志消息不能为空"):
            SessionLogCreate(message="   ")

    def test_log_create_message_too_long_raises(self) -> None:
        """超过 2000 字符的消息 → ValidationError."""
        with pytest.raises(ValidationError, match="日志消息不能超过 2000 个字符"):
            SessionLogCreate(message="长" * 2001)

    def test_log_create_invalid_level_raises(self) -> None:
        """level 非法值 → ValidationError."""
        with pytest.raises(ValidationError):
            SessionLogCreate(level="debug", message="消息")  # type: ignore[arg-type]  # kwargs 覆盖字段类型由测试意图保证


class TestSessionCompleteFail:
    """SessionComplete / SessionFail 请求 DTO（spec §2.6）。"""

    def test_complete_result_default_empty_dict(self) -> None:
        """complete 的 result 默认 {}."""
        dto = SessionComplete()
        assert dto.result == {}

    def test_complete_result_passthrough(self) -> None:
        """result 显式传入保留."""
        dto = SessionComplete(result={"words": 1280, "chapter_id": "7b9c"})
        assert dto.result == {"words": 1280, "chapter_id": "7b9c"}

    def test_fail_valid_and_strips_error(self) -> None:
        """fail 的 error 去空白."""
        dto = SessionFail(error="  LLM 调用超时（连续 3 次重试失败）  ")
        assert dto.error == "LLM 调用超时（连续 3 次重试失败）"

    def test_fail_error_required(self) -> None:
        """fail 缺 error → ValidationError."""
        with pytest.raises(ValidationError):
            SessionFail()

    def test_fail_empty_error_raises(self) -> None:
        """fail 的 error 为空/纯空白 → ValidationError."""
        with pytest.raises(ValidationError, match="失败原因不能为空"):
            SessionFail(error="   ")

    def test_fail_error_too_long_raises(self) -> None:
        """fail 的 error 超过 2000 字符 → ValidationError."""
        with pytest.raises(ValidationError, match="失败原因不能超过 2000 个字符"):
            SessionFail(error="错" * 2001)


class TestSessionView:
    """SessionView 视图模型（spec §2.6/§3.2）。"""

    def test_view_default_last_log_none(self) -> None:
        """0 日志 → last_log=None."""
        view = SessionView(session=_session(), log_count=0)
        assert view.session.id == SID
        assert view.log_count == 0
        assert view.last_log is None

    def test_view_with_last_log(self) -> None:
        """有日志 → last_log 为 SessionLogEntry."""
        entry = _log_entry()
        view = SessionView(session=_session(), log_count=3, last_log=entry)
        assert view.log_count == 3
        assert view.last_log is not None
        assert view.last_log.seq == 1

    def test_view_json_roundtrip(self) -> None:
        """SessionView → JSON（含 session 嵌套）→ 反序列化一致."""
        view = SessionView(session=_session(), log_count=1, last_log=_log_entry())
        raw = json.loads(json.dumps(view.model_dump(mode="json")))
        assert raw["log_count"] == 1
        assert raw["last_log"]["seq"] == 1
        assert raw["session"]["title"] == "第三章续写"
        restored = SessionView.model_validate(raw)
        assert restored == view
