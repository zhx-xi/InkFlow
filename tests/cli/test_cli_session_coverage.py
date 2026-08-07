"""Session CLI coverage 补盲测试（F24 PR #157 CI coverage-backend 98.5% 门槛修复）。

从 test_cli_session.py 拆分（原 1152 行 > check_file_length 900 上限）：
TestCoverageGapFill 类独立成文件，补齐 session.py 剩余 miss 行。

fixtures/helpers 与 test_cli_session.py 同构（cli_runner/mock_session_service/
mock_create_tables/_make_session/_make_log/_make_view）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
import typer
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
