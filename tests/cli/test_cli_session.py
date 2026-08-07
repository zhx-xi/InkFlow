"""Session CLI 命令测试 — Mock SessionService 隔离数据库（spec §4/§9 CLI 测试，M6）.

覆盖（依据 specs/f24-session-service/spec.md §4/§9）:
- 各子命令成功路径与参数透传（create/list/get/update/pause/resume/complete/fail/
  logs/log add/delete/restore 共 11 个子命令 + 组帮助）
- 信封格式与退出码 0/1/2（--type/--status/--level 非法枚举值 → 退出码 2；
  --context-json 与 --context-file 互斥 → 退出码 2，同 F9 双通道约定）
- 错误码映射: NOT_FOUND（SessionNotFoundError/ProjectNotFoundError/无效 UUID）、
  VALIDATION_ERROR（SessionServiceError 含 SessionTransitionError、pydantic
  ValidationError）、DB_ERROR（未知异常）——F24 无 LLM，无 LLM_ERROR（同 F12）
- 状态机命令 human 输出与 --json 完整对象；日志命令信封
- delete 两级: 默认归档（svc.delete(force=False)）、--force 直删（force=True）

══════════════════════════════════════════════════════════════════════════
设计假设（实现者以本文件为准）:
- 模块: inkflow.cli.commands.session；`app = typer.Typer(name="session",
  help="会话管理", no_args_is_help=True)`；注册进 inkflow.cli.app
- 命令签名（typer 选项）:
  * create --type <writing|task> --project-id <uuid|None> --title <str>
    [--description <str>] [--context-json <json>|--context-file <path>]
  * list [--type] [--status] [--project-id] [--search] [--limit 50] [--offset 0]
  * get --id <uuid>
  * update --id <uuid> [--title] [--description] [--context-json]
  * pause/resume --id <uuid>
  * complete --id <uuid> [--result-json <json>]
  * fail --id <uuid> --error <str>
  * logs --id <uuid> [--limit 50] [--offset 0]
  * log add --id <uuid> [--level info|warning|error] --message <str>
    [--payload-json <json>]（log 为 session 组下的子组）
  * delete --id <uuid> [--force]
  * restore --id <uuid>
- 服务调用（Mock SessionService，关键字参数）:
  create(data=SessionCreate) / list(session_type=, status=, project_id=, search=,
  limit=, offset=) / get(session_id=) / update(session_id=, data=SessionUpdate) /
  pause/resume(session_id=) / complete(session_id=, data=SessionComplete) /
  fail(session_id=, data=SessionFail) / delete(session_id=, force=) /
  restore(session_id=) / list_logs(session_id=, limit=, offset=) /
  add_log(session_id=, data=SessionLogCreate)
- JSON 信封（--json 时经 CliContext 注入）: 成功 {"ok": true, "data": ...}；
  失败 {"ok": false, "error": {"code", "message"}}；退出码 0/1/2
- data 形状: create/get → SessionView 完整 JSON（session/log_count/last_log）；
  list/logs → {"items": [...], "total": N, "offset": N, "limit": N}（spec §4.1）；
  delete → {"deleted": true, "id": "<uuid>"}
- _run 异常映射（同 F13）: SessionNotFoundError/ProjectNotFoundError/无效 UUID →
  NOT_FOUND（退出码 1）；SessionServiceError 含 SessionTransitionError →
  VALIDATION_ERROR（退出码 1）；pydantic ValidationError → VALIDATION_ERROR；
  其余 → DB_ERROR（"内部错误: ..."）；typer 参数解析错误 → 退出码 2
- human 输出: get 遵循 spec §4.2 示例首行「会话: {title} ({type}/{status})」与
  「日志: N 条」；create 含「创建成功」；pause/resume/complete/fail 分别含
  「已暂停/已恢复/已完成/已失败」；delete 含「已删除」；restore 含「已恢复」
══════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
import typer
from pydantic import ValidationError
from typer.testing import CliRunner

from inkflow.cli.commands.session import app
from inkflow.cli.context import CliContext
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
    SessionServiceError,
    SessionTransitionError,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


@pytest.fixture
def cli_runner():
    """click CliRunner — NO_COLOR 规避彩色渲染脆弱断言（陷阱 14）."""
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def mock_session_service():
    """Mock SessionService，绕过数据库（ADR-015 依赖注入）."""
    with patch(
        "inkflow.cli.commands.session.SessionService", autospec=True
    ) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_create_tables():
    """Mock create_tables 避免数据库初始化."""
    with patch("inkflow.cli.commands.session.create_tables", AsyncMock()):
        yield


def _make_session(**overrides) -> Session:
    """构造测试用会话领域对象."""
    defaults = dict(
        id=uuid.uuid4(),
        session_type=SessionType.WRITING,
        status=SessionStatus.ACTIVE,
        project_id=PID,
        title="第三章续写",
        description="续写第三章，接上一章结尾",
        context={"chapter_id": "7b9c", "mode": "continue"},
        result={},
        error="",
        started_at=TS,
        paused_at=None,
        completed_at=None,
        is_deleted=False,
        created_at=TS,
        updated_at=TS,
    )
    defaults.update(overrides)
    return Session(**defaults)


def _make_log(seq: int = 1, **overrides) -> SessionLogEntry:
    """构造测试用日志条目对象."""
    defaults = dict(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        seq=seq,
        level=LogLevel.INFO,
        message="开始写作章节 3",
        payload={"progress": 0.1},
        created_at=TS,
    )
    defaults.update(overrides)
    return SessionLogEntry(**defaults)


def _make_view(**overrides) -> SessionView:
    """构造会话视图（详情/列表项）."""
    defaults = dict(session=_make_session(), log_count=0, last_log=None)
    defaults.update(overrides)
    return SessionView(**defaults)


class TestSessionRegistration:
    def test_group_help_lists_all_commands(self):
        """session 组帮助包含全部 11 个命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）."""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in (
            "create",
            "list",
            "get",
            "update",
            "pause",
            "resume",
            "complete",
            "fail",
            "logs",
            "log",
            "delete",
            "restore",
        ):
            assert name in result.output


class TestSessionCreate:
    def test_create_json_envelope(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """create --json → 成功信封 + SessionView data + 参数透传（UUID 转换、
        --context-json 解析为 dict）."""
        view = _make_view()
        mock_session_service.create.return_value = view
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--type",
                "task",
                "--project-id",
                str(PID),
                "--title",
                "每日定时写作",
                "--description",
                "每日 800 字",
                "--context-json",
                '{"schedule": "daily", "target": 800}',
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["session"]["title"] == "第三章续写"
        assert data["data"]["log_count"] == 0
        assert data["data"]["last_log"] is None

        call = mock_session_service.create.await_args
        from inkflow.domain.models.session import SessionCreate

        create_data: SessionCreate = call.kwargs["data"]
        assert create_data.session_type == SessionType.TASK
        assert create_data.project_id == PID
        assert create_data.title == "每日定时写作"
        assert create_data.description == "每日 800 字"
        assert create_data.context == {"schedule": "daily", "target": 800}

    def test_create_context_file(
        self, cli_runner, mock_session_service, mock_create_tables, tmp_path
    ):
        """--context-file 读取 JSON 文件内容（长 context 双通道）."""
        context_file = tmp_path / "context.json"
        context_file.write_text(
            '{"schedule": "daily", "target": 800}', encoding="utf-8"
        )
        mock_session_service.create.return_value = _make_view()

        result = cli_runner.invoke(
            app,
            [
                "create",
                "--type",
                "task",
                "--title",
                "每日定时写作",
                "--context-file",
                str(context_file),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        from inkflow.domain.models.session import SessionCreate

        create_data: SessionCreate = mock_session_service.create.await_args.kwargs[
            "data"
        ]
        assert create_data.context == {"schedule": "daily", "target": 800}

    def test_create_context_json_and_file_mutually_exclusive(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """--context-json 与 --context-file 互斥 → 退出码 2（同 F9 双通道约定）."""
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--type",
                "task",
                "--title",
                "每日定时写作",
                "--context-json",
                "{}",
                "--context-file",
                "x.json",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_session_service.create.assert_not_awaited()

    def test_create_project_not_found(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_session_service.create.side_effect = ProjectNotFoundError()
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--type",
                "task",
                "--project-id",
                str(PID),
                "--title",
                "每日定时写作",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "项目不存在" in data["error"]["message"]

    def test_create_invalid_type_exit_code_2(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """--type 非法枚举值 → 退出码 2（typer 用法错误，F7 §7 非法枚举值）."""
        result = cli_runner.invoke(
            app,
            ["create", "--type", "bogus", "--title", "标题"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_session_service.create.assert_not_awaited()

    def test_create_human(self, cli_runner, mock_session_service, mock_create_tables):
        """create 人类模式 → 成功提示."""
        mock_session_service.create.return_value = _make_view()
        result = cli_runner.invoke(
            app,
            ["create", "--type", "writing", "--title", "第三章续写"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "创建成功" in result.output


class TestSessionList:
    def test_list_json(self, cli_runner, mock_session_service, mock_create_tables):
        """list --json → 成功信封 + {items, total, offset, limit}（spec §4.1）."""
        mock_session_service.list.return_value = ([_make_view(log_count=5)], 1)
        result = cli_runner.invoke(
            app,
            ["list"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["total"] == 1
        assert data["data"]["offset"] == 0
        assert data["data"]["limit"] == 50
        assert data["data"]["items"][0]["log_count"] == 5
        assert data["data"]["items"][0]["session"]["title"] == "第三章续写"

    def test_list_params_passthrough(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """list 过滤/分页参数透传（type/status/project_id 转枚举与 UUID）."""
        mock_session_service.list.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            [
                "list",
                "--type",
                "task",
                "--status",
                "completed",
                "--project-id",
                str(PID),
                "--search",
                "每日",
                "--limit",
                "20",
                "--offset",
                "0",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        mock_session_service.list.assert_awaited_once_with(
            session_type="task",
            status="completed",
            project_id=PID,
            search="每日",
            limit=20,
            offset=0,
        )

    def test_list_invalid_type_exit_code_2(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """--type 非法值 → 退出码 2."""
        result = cli_runner.invoke(
            app,
            ["list", "--type", "bogus"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_session_service.list.assert_not_awaited()


class TestSessionGet:
    def test_get_json(self, cli_runner, mock_session_service, mock_create_tables):
        """get --json → 成功信封 + SessionView data + id 透传."""
        eid = uuid.uuid4()
        mock_session_service.get.return_value = _make_view(log_count=5)
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["session"]["title"] == "第三章续写"
        assert data["data"]["log_count"] == 5
        mock_session_service.get.assert_awaited_once_with(session_id=eid)

    def test_get_not_found_json(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """会话不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_session_service.get.return_value = None
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "会话不存在" in data["error"]["message"]

    def test_get_invalid_uuid(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """无效 UUID → NOT_FOUND（spec §7: 无效 UUID 格式 → 404 语义）."""
        result = cli_runner.invoke(
            app,
            ["get", "--id", "not-a-uuid"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_get_human(self, cli_runner, mock_session_service, mock_create_tables):
        """get 人类模式 → spec §4.2 示例首行「会话: {title} ({type}/{status})」+
        「日志: N 条」."""
        mock_session_service.get.return_value = _make_view(
            session=_make_session(
                session_type=SessionType.TASK, status=SessionStatus.ACTIVE
            ),
            log_count=5,
        )
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "会话: 第三章续写 (task/active)" in result.output
        assert "日志: 5 条" in result.output


class TestSessionUpdate:
    def test_update_json(self, cli_runner, mock_session_service, mock_create_tables):
        """update --json → 成功信封 + SessionUpdate 透传（仅传入字段）."""
        eid = uuid.uuid4()
        mock_session_service.update.return_value = _make_session(
            title="第三章续写（改）"
        )
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                str(eid),
                "--title",
                "第三章续写（改）",
                "--context-json",
                '{"mode": "revise"}',
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "第三章续写（改）"

        call = mock_session_service.update.await_args
        from inkflow.domain.models.session import SessionUpdate

        assert call.kwargs["session_id"] == eid
        upd: SessionUpdate = call.kwargs["data"]
        assert upd.title == "第三章续写（改）"
        assert upd.context == {"mode": "revise"}
        assert "description" not in upd.model_fields_set

    def test_update_not_found(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """会话不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_session_service.update.return_value = None
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestSessionStateActions:
    """状态机动作命令（pause/resume/complete/fail）。"""

    def test_pause_json(self, cli_runner, mock_session_service, mock_create_tables):
        """pause --json → 成功信封 + paused 状态."""
        eid = uuid.uuid4()
        mock_session_service.pause.return_value = _make_session(
            status=SessionStatus.PAUSED, paused_at=TS
        )
        result = cli_runner.invoke(
            app,
            ["pause", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["status"] == "paused"
        assert data["data"]["paused_at"] == "2026-08-01T10:00:00Z"
        mock_session_service.pause.assert_awaited_once_with(session_id=eid)

    def test_resume_json(self, cli_runner, mock_session_service, mock_create_tables):
        """resume --json → active 状态 + paused_at 清空."""
        mock_session_service.resume.return_value = _make_session(
            status=SessionStatus.ACTIVE, paused_at=None
        )
        result = cli_runner.invoke(
            app,
            ["resume", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["status"] == "active"
        assert data["data"]["paused_at"] is None

    def test_complete_json_with_result(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """complete --result-json → SessionComplete 透传 + completed 状态."""
        eid = uuid.uuid4()
        mock_session_service.complete.return_value = _make_session(
            status=SessionStatus.COMPLETED, completed_at=TS, result={"words": 1280}
        )
        result = cli_runner.invoke(
            app,
            ["complete", "--id", str(eid), "--result-json", '{"words": 1280}'],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["status"] == "completed"
        assert data["data"]["result"] == {"words": 1280}

        from inkflow.domain.models.session import SessionComplete

        complete_data: SessionComplete = (
            mock_session_service.complete.await_args.kwargs["data"]
        )
        assert complete_data.result == {"words": 1280}

    def test_fail_json_with_error(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """fail --error → SessionFail 透传 + failed 状态."""
        eid = uuid.uuid4()
        mock_session_service.fail.return_value = _make_session(
            status=SessionStatus.FAILED, completed_at=TS, error="LLM 调用超时"
        )
        result = cli_runner.invoke(
            app,
            ["fail", "--id", str(eid), "--error", "LLM 调用超时"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["status"] == "failed"
        assert data["data"]["error"] == "LLM 调用超时"

        from inkflow.domain.models.session import SessionFail

        fail_data: SessionFail = mock_session_service.fail.await_args.kwargs["data"]
        assert fail_data.error == "LLM 调用超时"

    def test_transition_error_validation(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """非法迁移（SessionTransitionError）→ VALIDATION_ERROR 信封 + 退出码 1."""
        mock_session_service.pause.side_effect = SessionTransitionError(
            "会话当前状态 paused 不允许 pause"
        )
        result = cli_runner.invoke(
            app,
            ["pause", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "不允许" in data["error"]["message"]

    def test_action_not_found(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """动作对不存在的会话 → NOT_FOUND 信封."""
        mock_session_service.resume.side_effect = SessionNotFoundError()
        result = cli_runner.invoke(
            app,
            ["resume", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_pause_human(self, cli_runner, mock_session_service, mock_create_tables):
        """pause 人类模式 → 已暂停提示."""
        mock_session_service.pause.return_value = _make_session(
            status=SessionStatus.PAUSED, paused_at=TS
        )
        result = cli_runner.invoke(
            app,
            ["pause", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已暂停" in result.output


class TestSessionLogs:
    """履历日志命令（logs / log add）。"""

    def test_logs_json(self, cli_runner, mock_session_service, mock_create_tables):
        """logs --json → 成功信封 + {items, total, offset, limit}（seq ASC）."""
        eid = uuid.uuid4()
        mock_session_service.list_logs.return_value = (
            [_make_log(seq=1), _make_log(seq=2, message="重试")],
            2,
        )
        result = cli_runner.invoke(
            app,
            ["logs", "--id", str(eid), "--limit", "20", "--offset", "0"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["total"] == 2
        assert data["data"]["offset"] == 0
        assert data["data"]["limit"] == 20
        assert [item["seq"] for item in data["data"]["items"]] == [1, 2]
        mock_session_service.list_logs.assert_awaited_once_with(
            session_id=eid, limit=20, offset=0
        )

    def test_log_add_json(self, cli_runner, mock_session_service, mock_create_tables):
        """log add --json → 成功信封 + SessionLogCreate 透传（level/message/payload）."""
        eid = uuid.uuid4()
        mock_session_service.add_log.return_value = _make_log(
            seq=1,
            level=LogLevel.WARNING,
            message="LLM 调用失败，重试第 2 次",
            payload={"attempt": 2},
        )
        result = cli_runner.invoke(
            app,
            [
                "log",
                "add",
                "--id",
                str(eid),
                "--level",
                "warning",
                "--message",
                "LLM 调用失败，重试第 2 次",
                "--payload-json",
                '{"attempt": 2}',
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["seq"] == 1
        assert data["data"]["level"] == "warning"
        assert data["data"]["payload"] == {"attempt": 2}

        from inkflow.domain.models.session import SessionLogCreate

        log_data: SessionLogCreate = mock_session_service.add_log.await_args.kwargs[
            "data"
        ]
        assert log_data.level == LogLevel.WARNING
        assert log_data.message == "LLM 调用失败，重试第 2 次"
        assert log_data.payload == {"attempt": 2}

    def test_log_add_invalid_level_exit_code_2(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """--level 非法值 → 退出码 2."""
        result = cli_runner.invoke(
            app,
            [
                "log",
                "add",
                "--id",
                str(uuid.uuid4()),
                "--level",
                "debug",
                "--message",
                "消息",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_session_service.add_log.assert_not_awaited()

    def test_log_add_not_found(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """对不存在的会话追加日志 → NOT_FOUND 信封."""
        mock_session_service.add_log.side_effect = SessionNotFoundError()
        result = cli_runner.invoke(
            app,
            ["log", "add", "--id", str(uuid.uuid4()), "--message", "消息"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestSessionDeleteRestore:
    """删除两级 + 恢复命令。"""

    def test_delete_json_archive(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """delete --json（无 --force）→ 成功信封 {deleted, id} + svc.delete(force=False)."""
        eid = uuid.uuid4()
        mock_session_service.delete.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        assert data["data"]["id"] == str(eid)
        mock_session_service.delete.assert_awaited_once_with(
            session_id=eid, force=False
        )

    def test_delete_force_json(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """delete --force → svc.delete(force=True)（真实删除通道）."""
        eid = uuid.uuid4()
        mock_session_service.delete.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout)["data"]["deleted"] is True
        mock_session_service.delete.assert_awaited_once_with(session_id=eid, force=True)

    def test_delete_not_found(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """会话不存在（服务返回 False）→ NOT_FOUND 错误信封."""
        mock_session_service.delete.return_value = False
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_restore_json(self, cli_runner, mock_session_service, mock_create_tables):
        """restore --json → 成功信封 + 解除归档的 Session."""
        eid = uuid.uuid4()
        mock_session_service.restore.return_value = _make_session(is_deleted=False)
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["is_deleted"] is False
        mock_session_service.restore.assert_awaited_once_with(session_id=eid)

    def test_restore_not_found(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """会话不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_session_service.restore.return_value = None
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestSessionErrorMapping:
    """_run 异常映射补全：ServiceError / ValidationError / DB_ERROR."""

    def test_create_service_error(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """服务抛 SessionServiceError → VALIDATION_ERROR 信封 + 退出码 1."""
        mock_session_service.create.side_effect = SessionServiceError("会话创建失败")
        result = cli_runner.invoke(
            app,
            ["create", "--type", "task", "--title", "每日定时写作"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "会话创建失败" in data["error"]["message"]

    def test_create_validation_error(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """pydantic ValidationError → VALIDATION_ERROR 信封."""
        mock_session_service.create.side_effect = ValidationError.from_exception_data(
            "SessionCreate",
            [
                {
                    "type": "string_type",
                    "loc": ("title",),
                    "msg": "Input should be a valid string",
                    "input": 123,
                }
            ],
        )
        result = cli_runner.invoke(
            app,
            ["create", "--type", "task", "--title", "每日定时写作"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_create_db_error(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """服务抛未知异常 → DB_ERROR 信封 + 退出码 1（F24 无 LLM_ERROR，同 F12）."""
        mock_session_service.create.side_effect = RuntimeError("boom")
        result = cli_runner.invoke(
            app,
            ["create", "--type", "task", "--title", "每日定时写作"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"
        assert "boom" in data["error"]["message"]


class TestCoverageGapFill:
    """F24 coverage 补盲（PR #157 CI coverage-backend 98.5% 门槛）— 补齐
    session.py 剩余 miss 行：_run 透传 typer.Exit（L92）、_utc_aware list 分支
    （L111）、_parse_json_value 非法 JSON/非对象（L147-152）、_resolve_context
    文件读取失败（L164-166）、list 人类模式空态与逐条（L274-282）、update
    --description 分支与人类模式（L337-340/356）、resume/complete/fail 人类模式
    （L403/427/450）、logs 人类模式空态与逐条（L488-493）、log add 人类模式
    （L525）、delete/restore 人类模式（L553/578）。

    L84（_parse_uuid 中 print_error 后的 raise typer.Exit）经实证确认静态不可达：
    print_error（inkflow/cli/output.py L54）恒 raise typer.Exit，控制流不会到达
    该行，无法也不应覆盖。
    """

    def test_run_passthrough_typer_exit(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """服务协程内抛 typer.Exit → _run 原样透传，退出码保持（L92）."""
        mock_session_service.create.side_effect = typer.Exit(2)
        result = cli_runner.invoke(
            app,
            ["create", "--type", "task", "--title", "每日定时写作"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2

    def test_utc_aware_list_branch(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """context 含 list 值 → _utc_aware 递归 list 分支正常序列化（L111）."""
        mock_session_service.create.return_value = _make_view(
            session=_make_session(context={"tags": ["a", "b"]})
        )
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--type",
                "task",
                "--title",
                "每日定时写作",
                "--context-json",
                '{"tags": ["a", "b"]}',
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["session"]["context"]["tags"] == ["a", "b"]

    def test_create_context_json_invalid_exit_code_2(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """--context-json 非法 JSON → JSONDecodeError → 退出码 2（L147-149）."""
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--type",
                "task",
                "--title",
                "每日定时写作",
                "--context-json",
                "{not json",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_session_service.create.assert_not_awaited()

    def test_create_context_json_not_object_exit_code_2(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """--context-json 为 JSON 数组（非对象）→ 退出码 2（L151-152）."""
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--type",
                "task",
                "--title",
                "每日定时写作",
                "--context-json",
                '["a", "b"]',
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_session_service.create.assert_not_awaited()

    def test_create_context_file_missing_exit_code_2(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """--context-file 指向不存在文件 → 读取 OSError → 退出码 2（L164-166）."""
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--type",
                "task",
                "--title",
                "每日定时写作",
                "--context-file",
                "D:/no/such/context.json",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_session_service.create.assert_not_awaited()

    def test_list_human_empty(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """list 人类模式空结果 → 「📭 暂无会话」（L274-276）."""
        mock_session_service.list.return_value = ([], 0)
        result = cli_runner.invoke(app, ["list"], obj=CliContext(json_output=False))
        assert result.exit_code == 0
        assert "暂无会话" in result.output

    def test_list_human(self, cli_runner, mock_session_service, mock_create_tables):
        """list 人类模式非空 → 逐条输出 + 「共 N 个会话」（L277-282）."""
        mock_session_service.list.return_value = (
            [
                _make_view(log_count=5),
                _make_view(session=_make_session(title="第二个会话"), log_count=0),
            ],
            2,
        )
        result = cli_runner.invoke(app, ["list"], obj=CliContext(json_output=False))
        assert result.exit_code == 0
        assert "第三章续写" in result.output
        assert "第二个会话" in result.output
        assert "日志 5 条" in result.output
        assert "共 2 个会话" in result.output

    def test_update_with_description_only(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """update 仅传 --description → 仅 description 字段透传（L337->339/340）."""
        eid = uuid.uuid4()
        mock_session_service.update.return_value = _make_session()
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(eid), "--description", "新描述"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        from inkflow.domain.models.session import SessionUpdate

        upd: SessionUpdate = mock_session_service.update.await_args.kwargs["data"]
        assert upd.description == "新描述"
        assert "title" not in upd.model_fields_set

    def test_update_human(self, cli_runner, mock_session_service, mock_create_tables):
        """update 人类模式 → 「已更新」提示（L356）."""
        mock_session_service.update.return_value = _make_session(
            title="第三章续写（改）"
        )
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "第三章续写（改）"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已更新" in result.output

    def test_resume_human(self, cli_runner, mock_session_service, mock_create_tables):
        """resume 人类模式 → 「已恢复」提示（L403）."""
        mock_session_service.resume.return_value = _make_session(
            status=SessionStatus.ACTIVE, paused_at=None
        )
        result = cli_runner.invoke(
            app,
            ["resume", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已恢复" in result.output

    def test_complete_human(self, cli_runner, mock_session_service, mock_create_tables):
        """complete 人类模式 → 「已完成」提示（L427）."""
        mock_session_service.complete.return_value = _make_session(
            status=SessionStatus.COMPLETED, completed_at=TS
        )
        result = cli_runner.invoke(
            app,
            ["complete", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已完成" in result.output

    def test_fail_human(self, cli_runner, mock_session_service, mock_create_tables):
        """fail 人类模式 → 「已失败」提示（L450）."""
        mock_session_service.fail.return_value = _make_session(
            status=SessionStatus.FAILED, error="LLM 调用超时"
        )
        result = cli_runner.invoke(
            app,
            ["fail", "--id", str(uuid.uuid4()), "--error", "LLM 调用超时"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已失败" in result.output

    def test_logs_human_empty(
        self, cli_runner, mock_session_service, mock_create_tables
    ):
        """logs 人类模式空结果 → 「📭 暂无日志」（L488-490）."""
        mock_session_service.list_logs.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            ["logs", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无日志" in result.output

    def test_logs_human(self, cli_runner, mock_session_service, mock_create_tables):
        """logs 人类模式非空 → 逐条 + 「共 N 条日志」（L491-493）."""
        mock_session_service.list_logs.return_value = (
            [_make_log(seq=1), _make_log(seq=2, message="重试")],
            2,
        )
        result = cli_runner.invoke(
            app,
            ["logs", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "#1 [info] 开始写作章节 3" in result.output
        assert "#2 [info] 重试" in result.output
        assert "共 2 条日志" in result.output

    def test_log_add_human(self, cli_runner, mock_session_service, mock_create_tables):
        """log add 人类模式 → 「日志已添加」提示（L525）."""
        mock_session_service.add_log.return_value = _make_log(seq=3)
        result = cli_runner.invoke(
            app,
            ["log", "add", "--id", str(uuid.uuid4()), "--message", "追加日志"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "日志已添加" in result.output

    def test_delete_human(self, cli_runner, mock_session_service, mock_create_tables):
        """delete 人类模式 → 「已删除」提示（L553）."""
        eid = uuid.uuid4()
        mock_session_service.delete.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output

    def test_restore_human(self, cli_runner, mock_session_service, mock_create_tables):
        """restore 人类模式 → 「已恢复」提示（L578）."""
        mock_session_service.restore.return_value = _make_session(is_deleted=False)
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已恢复" in result.output
