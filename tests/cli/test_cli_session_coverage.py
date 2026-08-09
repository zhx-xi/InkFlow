"""Session CLI coverage 补盲测试（F24 PR #157 CI coverage-backend 98.5% 门槛修复，
F38 HTTP mock 轨改造）。

从 test_cli_session.py 拆分（原 1152 行 > check_file_length 900 上限）：
TestCoverageGapFill 类独立成文件，补齐 session.py 剩余 miss 行。

fixtures/helpers 与 test_cli_session.py 同构（cli_runner/fake_http_client/
_make_session/_make_log/_make_view/_view_json/_session_json/_log_json）。

F38 改造（#169）：mock 目标从 domain Service/LLM 客户端迁移到 ensure_kernel +
InkFlowHTTPClient（HTTP JSON 响应 + SSE 流式 mock）；create_tables/session/LLM
patch 已移除。RED 阶段命令模块无 ensure_kernel/InkFlowHTTPClient 属性 →
fake_http_client fixture 的 patch setup 抛 AttributeError（同根因，预期 RED）。

改造说明:
- 原 L92（_run 透传 typer.Exit）用例已移除——F38 后命令内错误统一经
  print_error 抛 typer.Exit，该内部接缝不复存在，退出码语义由既有错误路径
  用例（NOT_FOUND/VALIDATION_ERROR/INTERNAL_ERROR → 退出码 1）覆盖。
- 原「服务抛未知异常 → DB_ERROR」语义由 HTTP 500 → INTERNAL_ERROR 替代
  （F38 §5.3: 恒 HTTP 后 CLI 不再直连 DB，F7 DB_ERROR 行由 INTERNAL_ERROR 替代）。
- 错误注入统一为 HttpApiError(status_code, detail[, code]) → F38 §5.3 映射表；
  HttpApiError 惰性 import（infrastructure.http RED 阶段不存在）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.session import app
from inkflow.cli.context import CliContext
from inkflow.domain.models.session import (
    LogLevel,
    Session,
    SessionLogEntry,
    SessionStatus,
    SessionType,
    SessionUpdate,
    SessionView,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


@pytest.fixture
def cli_runner():
    """click CliRunner — NO_COLOR 规避彩色渲染脆弱断言（陷阱 14）."""
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def fake_http_client():
    """patch ensure_kernel + InkFlowHTTPClient（命令模块命名空间）→ fake client 实例.

    __aenter__ 返回自身：命令 `async with InkFlowHTTPClient(handle) as client`
    的 client 即本 mock，后续 post/get 等调用记录在 mock_instance 上。
    """
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch(
            "inkflow.cli.commands.session.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.session.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_err(status_code: int, detail: str, code: str | None = None):
    """惰性构造 HttpApiError（infrastructure.http RED 阶段不存在，禁顶部 import）."""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


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


def _view_json(**overrides) -> dict:
    """SessionView → JSON dict（HTTP 响应形态，model_dump(mode="json")）."""
    return _make_view(**overrides).model_dump(mode="json")


def _session_json(**overrides) -> dict:
    """Session → JSON dict（update/pause/resume/complete/fail/restore 响应）."""
    return _make_session(**overrides).model_dump(mode="json")


def _log_json(**overrides) -> dict:
    """SessionLogEntry → JSON dict（log add/logs 响应）."""
    return _make_log(**overrides).model_dump(mode="json")


class TestCoverageGapFill:
    """F24 coverage 补盲（PR #157 CI coverage-backend 98.5% 门槛）— 补齐
    session.py 剩余 miss 行：_parse_json_value 非法 JSON/非对象、_resolve_context
    文件读取失败、list 人类模式空态与逐条、update 仅 description 分支与人类模式、
    resume/complete/fail 人类模式、logs 人类模式空态与逐条、log add 人类模式、
    delete/restore 人类模式。

    F38 改造后行号语义：_utc_aware/list 序列化分支移至内核侧（API 返回裸 JSON），
    CLI 侧仅剩参数解析（退出码 2 分支）与 human 输出分支——以下用例按新架构
    语义保留输出契约断言。
    """

    def test_utc_aware_list_branch(self, cli_runner, fake_http_client):
        """context 含 list 值 → JSON 响应原样透传（内核已序列化）."""
        fake_http_client.post.return_value = _view_json(
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
        self, cli_runner, fake_http_client
    ):
        """--context-json 非法 JSON → JSONDecodeError → 退出码 2."""
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
        fake_http_client.post.assert_not_awaited()

    def test_create_context_json_not_object_exit_code_2(
        self, cli_runner, fake_http_client
    ):
        """--context-json 为 JSON 数组（非对象）→ 退出码 2."""
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
        fake_http_client.post.assert_not_awaited()

    def test_create_context_file_missing_exit_code_2(
        self, cli_runner, fake_http_client
    ):
        """--context-file 指向不存在文件 → 读取 OSError → 退出码 2."""
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
        fake_http_client.post.assert_not_awaited()

    def test_list_human_empty(self, cli_runner, fake_http_client):
        """list 人类模式空结果 → 「📭 暂无会话」."""
        fake_http_client.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(app, ["list"], obj=CliContext(json_output=False))
        assert result.exit_code == 0
        assert "暂无会话" in result.output

    def test_list_human(self, cli_runner, fake_http_client):
        """list 人类模式非空 → 逐条输出 + 「共 N 个会话」."""
        fake_http_client.get.return_value = {
            "items": [
                _view_json(log_count=5),
                _view_json(session=_make_session(title="第二个会话"), log_count=0),
            ],
            "total": 2,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(app, ["list"], obj=CliContext(json_output=False))
        assert result.exit_code == 0
        assert "第三章续写" in result.output
        assert "第二个会话" in result.output
        assert "日志 5 条" in result.output
        assert "共 2 个会话" in result.output

    def test_update_with_description_only(self, cli_runner, fake_http_client):
        """update 仅传 --description → 仅 description 字段进请求体."""
        eid = uuid.uuid4()
        fake_http_client.patch.return_value = _session_json()
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(eid), "--description", "新描述"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        upd = SessionUpdate.model_validate(
            fake_http_client.patch.await_args.kwargs["json"]
        )
        assert upd.description == "新描述"
        assert "title" not in upd.model_fields_set

    def test_update_human(self, cli_runner, fake_http_client):
        """update 人类模式 → 「已更新」提示."""
        fake_http_client.patch.return_value = _session_json(title="第三章续写（改）")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "第三章续写（改）"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已更新" in result.output

    def test_resume_human(self, cli_runner, fake_http_client):
        """resume 人类模式 → 「已恢复」提示."""
        fake_http_client.post.return_value = _session_json(
            status=SessionStatus.ACTIVE, paused_at=None
        )
        result = cli_runner.invoke(
            app,
            ["resume", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已恢复" in result.output

    def test_complete_human(self, cli_runner, fake_http_client):
        """complete 人类模式 → 「已完成」提示."""
        fake_http_client.post.return_value = _session_json(
            status=SessionStatus.COMPLETED, completed_at=TS
        )
        result = cli_runner.invoke(
            app,
            ["complete", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已完成" in result.output

    def test_fail_human(self, cli_runner, fake_http_client):
        """fail 人类模式 → 「已失败」提示."""
        fake_http_client.post.return_value = _session_json(
            status=SessionStatus.FAILED, error="LLM 调用超时"
        )
        result = cli_runner.invoke(
            app,
            ["fail", "--id", str(uuid.uuid4()), "--error", "LLM 调用超时"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已失败" in result.output

    def test_logs_human_empty(self, cli_runner, fake_http_client):
        """logs 人类模式空结果 → 「📭 暂无日志」."""
        fake_http_client.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            app,
            ["logs", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无日志" in result.output

    def test_logs_human(self, cli_runner, fake_http_client):
        """logs 人类模式非空 → 逐条 + 「共 N 条日志」."""
        fake_http_client.get.return_value = {
            "items": [_log_json(seq=1), _log_json(seq=2, message="重试")],
            "total": 2,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            app,
            ["logs", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "#1 [info] 开始写作章节 3" in result.output
        assert "#2 [info] 重试" in result.output
        assert "共 2 条日志" in result.output

    def test_log_add_human(self, cli_runner, fake_http_client):
        """log add 人类模式 → 「日志已添加」提示."""
        fake_http_client.post.return_value = _log_json(seq=3)
        result = cli_runner.invoke(
            app,
            ["log", "add", "--id", str(uuid.uuid4()), "--message", "追加日志"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "日志已添加" in result.output

    def test_delete_human(self, cli_runner, fake_http_client):
        """delete 人类模式 → 「已删除」提示."""
        eid = uuid.uuid4()
        fake_http_client.delete.return_value = {}
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output

    def test_restore_human(self, cli_runner, fake_http_client):
        """restore 人类模式 → 「已恢复」提示."""
        fake_http_client.post.return_value = _session_json(is_deleted=False)
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已恢复" in result.output
