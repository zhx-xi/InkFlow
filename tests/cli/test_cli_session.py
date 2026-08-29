"""Session CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（F38 HTTP mock 轨，spec §4/§9.1）.

覆盖（依据 specs/f24-session/spec.md §4/§9 + specs/f38-cli-http/spec.md §3.1/§5.3）:
- 各子命令成功路径与参数透传（create/list/get/update/pause/resume/complete/fail/
  logs/log add/delete/restore 共 11 个子命令 + 组帮助）
- 信封格式与退出码 0/1/2（--type/--status/--level 非法枚举值 → 退出码 2；
  --context-json 与 --context-file 互斥 → 退出码 2，同 F9 双通道约定）
- 错误码映射（F38 §5.3）: HTTP 404 → NOT_FOUND、HTTP 422 → VALIDATION_ERROR、
  HTTP 500（无响应头）→ INTERNAL_ERROR（恒 HTTP 后替代 DB_ERROR，spec §5.3 注）
- 状态机命令 human 输出与 --json 完整对象；日志命令信封
- delete 两级: 默认归档（?force=false）、--force 直删（?force=true）

F38 改造（#169）：mock 目标从 domain Service/LLM 客户端迁移到 ensure_kernel +
InkFlowHTTPClient（HTTP JSON 响应 + SSE 流式 mock）；create_tables/session/LLM
patch 已移除。命令改造后不再 import 服务层——GREEN 目标为命令模块内
`from inkflow.infrastructure.kernel import ensure_kernel` 与
`from inkflow.infrastructure.http import InkFlowHTTPClient`；RED 阶段两符号
不存在 → fake_http_client fixture 的 patch setup 抛 AttributeError（同根因，
预期 RED 形态）。

══════════════════════════════════════════════════════════════════════════
HTTP 契约（实现者以本文件为准）:
- 端点映射（base_url = http://127.0.0.1:{port}/api/v1，F38 §3.1）:
  * create  → POST /sessions（body = SessionCreate JSON）
  * list    → GET /sessions（params: session_type/status/project_id/search/limit/offset）
  * get     → GET /sessions/{id}
  * update  → PATCH /sessions/{id}（body = SessionUpdate JSON，仅传入字段）
  * pause/resume → POST /sessions/{id}/pause|resume（无 body）
  * complete/fail → POST /sessions/{id}/complete|fail（body: result/error）
  * logs    → GET /sessions/{id}/logs（params: limit/offset）
  * log add → POST /sessions/{id}/logs（body = SessionLogCreate JSON）
  * delete  → DELETE /sessions/{id}（params: force）
  * restore → POST /sessions/{id}/restore
- 响应 = API 裸 JSON（SessionView/Session/SessionLogEntry model_dump(mode="json")
  形态；list/logs 为 {items, total, offset, limit}）；delete 204 无 body，
  CLI 自行输出 {deleted: true, id} 信封
- 错误 = HttpApiError(status_code, detail[, code]) → F38 §5.3 映射表；
  HttpApiError 惰性 import（infrastructure.http RED 阶段不存在，顶部 import
  会整文件收集失败——先例 test_cli_http_kernel.py 用例体 lazy import）
══════════════════════════════════════════════════════════════════════════
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
TS = datetime(2026, 8, 1, 10, 0, 0)


@pytest.fixture
def cli_runner():
    """click CliRunner — NO_COLOR 规避彩色渲染脆弱断言（陷阱 14）."""
    return CliRunner(env={"NO_COLOR": "1"})


@pytest.fixture
def fake_http_client():
    """patch ensure_kernel + InkFlowHTTPClient（命令模块命名空间）→ fake client 实例.

    RED 阶段命令模块无 ensure_kernel/InkFlowHTTPClient 属性 → patch setup
    AttributeError（同根因，预期 RED）；GREEN 命令模块顶层 from-import 后生效。
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
    def test_create_json_envelope(self, cli_runner, fake_http_client):
        """create --json → 成功信封 + SessionView data + 参数透传（UUID 转换、
        --context-json 解析为 dict 进请求体）."""
        fake_http_client.post.return_value = _view_json()
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

        call = fake_http_client.post.await_args
        assert call.args[0] == "/sessions"
        create_data = SessionCreate.model_validate(call.kwargs["json"])
        assert create_data.session_type == SessionType.TASK
        assert create_data.project_id == PID
        assert create_data.title == "每日定时写作"
        assert create_data.description == "每日 800 字"
        assert create_data.context == {"schedule": "daily", "target": 800}

    def test_create_context_file(self, cli_runner, fake_http_client, tmp_path):
        """--context-file 读取 JSON 文件内容（长 context 双通道）."""
        context_file = tmp_path / "context.json"
        context_file.write_text(
            '{"schedule": "daily", "target": 800}', encoding="utf-8"
        )
        fake_http_client.post.return_value = _view_json()

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
        create_data = SessionCreate.model_validate(
            fake_http_client.post.await_args.kwargs["json"]
        )
        assert create_data.context == {"schedule": "daily", "target": 800}

    def test_create_context_json_and_file_mutually_exclusive(
        self, cli_runner, fake_http_client
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
        fake_http_client.post.assert_not_awaited()

    def test_create_project_not_found(self, cli_runner, fake_http_client):
        """项目不存在（HTTP 404）→ NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_err(404, "项目不存在")
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

    def test_create_invalid_type_exit_code_2(self, cli_runner, fake_http_client):
        """--type 非法枚举值 → 退出码 2（typer 用法错误，F7 §7 非法枚举值）."""
        result = cli_runner.invoke(
            app,
            ["create", "--type", "bogus", "--title", "标题"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.post.assert_not_awaited()

    def test_create_human(self, cli_runner, fake_http_client):
        """create 人类模式 → 成功提示."""
        fake_http_client.post.return_value = _view_json()
        result = cli_runner.invoke(
            app,
            ["create", "--type", "writing", "--title", "第三章续写"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "创建成功" in result.output


class TestSessionList:
    def test_list_json(self, cli_runner, fake_http_client):
        """list --json → 成功信封 + {items, total, offset, limit}（spec §4.1）."""
        fake_http_client.get.return_value = {
            "items": [_view_json(log_count=5)],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
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

    def test_list_params_passthrough(self, cli_runner, fake_http_client):
        """list 过滤/分页参数透传（type/status/project_id 转枚举与 UUID）."""
        fake_http_client.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
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
        call = fake_http_client.get.await_args
        assert call.args[0] == "/sessions"
        assert call.kwargs["params"] == {
            "session_type": "task",
            "status": "completed",
            "project_id": str(PID),
            "search": "每日",
            "limit": 20,
            "offset": 0,
        }

    def test_list_invalid_type_exit_code_2(self, cli_runner, fake_http_client):
        """--type 非法值 → 退出码 2."""
        result = cli_runner.invoke(
            app,
            ["list", "--type", "bogus"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        fake_http_client.get.assert_not_awaited()


class TestSessionGet:
    def test_get_json(self, cli_runner, fake_http_client):
        """get --json → 成功信封 + SessionView data + id 透传."""
        eid = uuid.uuid4()
        fake_http_client.get.return_value = _view_json(log_count=5)
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
        fake_http_client.get.assert_awaited_once_with(f"/sessions/{eid}")

    def test_get_not_found_json(self, cli_runner, fake_http_client):
        """会话不存在（HTTP 404）→ NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.get.side_effect = _http_err(404, "会话不存在")
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

    def test_get_invalid_uuid(self, cli_runner, fake_http_client):
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

    def test_get_human(self, cli_runner, fake_http_client):
        """get 人类模式 → spec §4.2 示例首行「会话: {title} ({type}/{status})」+
        「日志: N 条」."""
        fake_http_client.get.return_value = _view_json(
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
    def test_update_json(self, cli_runner, fake_http_client):
        """update --json → 成功信封 + SessionUpdate 透传（仅传入字段）."""
        eid = uuid.uuid4()
        fake_http_client.patch.return_value = _session_json(title="第三章续写（改）")
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

        call = fake_http_client.patch.await_args
        assert call.args[0] == f"/sessions/{eid}"
        upd = SessionUpdate.model_validate(call.kwargs["json"])
        assert upd.title == "第三章续写（改）"
        assert upd.context == {"mode": "revise"}
        assert "description" not in upd.model_fields_set

    def test_update_not_found(self, cli_runner, fake_http_client):
        """会话不存在（HTTP 404）→ NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.patch.side_effect = _http_err(404, "会话不存在")
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

    def test_pause_json(self, cli_runner, fake_http_client):
        """pause --json → 成功信封 + paused 状态."""
        eid = uuid.uuid4()
        fake_http_client.post.return_value = _session_json(
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
        fake_http_client.post.assert_awaited_once_with(f"/sessions/{eid}/pause")

    def test_resume_json(self, cli_runner, fake_http_client):
        """resume --json → active 状态 + paused_at 清空."""
        fake_http_client.post.return_value = _session_json(
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

    def test_complete_json_with_result(self, cli_runner, fake_http_client):
        """complete --result-json → body result 透传 + completed 状态."""
        eid = uuid.uuid4()
        fake_http_client.post.return_value = _session_json(
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

        call = fake_http_client.post.await_args
        assert call.args[0] == f"/sessions/{eid}/complete"
        complete_data = SessionComplete.model_validate(call.kwargs["json"])
        assert complete_data.result == {"words": 1280}

    def test_fail_json_with_error(self, cli_runner, fake_http_client):
        """fail --error → body error 透传 + failed 状态."""
        eid = uuid.uuid4()
        fake_http_client.post.return_value = _session_json(
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

        call = fake_http_client.post.await_args
        assert call.args[0] == f"/sessions/{eid}/fail"
        fail_data = SessionFail.model_validate(call.kwargs["json"])
        assert fail_data.error == "LLM 调用超时"

    def test_transition_error_validation(self, cli_runner, fake_http_client):
        """非法迁移（HTTP 422，状态机错误）→ VALIDATION_ERROR 信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_err(
            422, "会话当前状态 paused 不允许 pause"
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

    def test_action_not_found(self, cli_runner, fake_http_client):
        """动作对不存在的会话（HTTP 404）→ NOT_FOUND 信封."""
        fake_http_client.post.side_effect = _http_err(404, "会话不存在")
        result = cli_runner.invoke(
            app,
            ["resume", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_pause_human(self, cli_runner, fake_http_client):
        """pause 人类模式 → 已暂停提示."""
        fake_http_client.post.return_value = _session_json(
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

    def test_logs_json(self, cli_runner, fake_http_client):
        """logs --json → 成功信封 + {items, total, offset, limit}（seq ASC）."""
        eid = uuid.uuid4()
        fake_http_client.get.return_value = {
            "items": [_log_json(seq=1), _log_json(seq=2, message="重试")],
            "total": 2,
            "offset": 0,
            "limit": 20,
        }
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
        call = fake_http_client.get.await_args
        assert call.args[0] == f"/sessions/{eid}/logs"
        assert call.kwargs["params"] == {"limit": 20, "offset": 0}

    def test_log_add_json(self, cli_runner, fake_http_client):
        """log add --json → 成功信封 + SessionLogCreate 透传（level/message/payload）."""
        eid = uuid.uuid4()
        fake_http_client.post.return_value = _log_json(
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

        call = fake_http_client.post.await_args
        assert call.args[0] == f"/sessions/{eid}/logs"
        log_data = SessionLogCreate.model_validate(call.kwargs["json"])
        assert log_data.level == LogLevel.WARNING
        assert log_data.message == "LLM 调用失败，重试第 2 次"
        assert log_data.payload == {"attempt": 2}

    def test_log_add_invalid_level_exit_code_2(self, cli_runner, fake_http_client):
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
        fake_http_client.post.assert_not_awaited()

    def test_log_add_not_found(self, cli_runner, fake_http_client):
        """对不存在的会话追加日志（HTTP 404）→ NOT_FOUND 信封."""
        fake_http_client.post.side_effect = _http_err(404, "会话不存在")
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

    def test_delete_json_archive(self, cli_runner, fake_http_client):
        """delete --json（无 --force）→ 成功信封 {deleted, id} + force=false."""
        eid = uuid.uuid4()
        fake_http_client.delete.return_value = {}
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
        fake_http_client.delete.assert_awaited_once_with(
            f"/sessions/{eid}", params={"force": False}
        )

    def test_delete_force_json(self, cli_runner, fake_http_client):
        """delete --force → force=true（真实删除通道）."""
        eid = uuid.uuid4()
        fake_http_client.delete.return_value = {}
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout)["data"]["deleted"] is True
        fake_http_client.delete.assert_awaited_once_with(
            f"/sessions/{eid}", params={"force": True}
        )

    def test_delete_not_found(self, cli_runner, fake_http_client):
        """会话不存在（HTTP 404）→ NOT_FOUND 错误信封."""
        fake_http_client.delete.side_effect = _http_err(404, "会话不存在")
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_restore_json(self, cli_runner, fake_http_client):
        """restore --json → 成功信封 + 解除归档的 Session."""
        eid = uuid.uuid4()
        fake_http_client.post.return_value = _session_json(is_deleted=False)
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["is_deleted"] is False
        fake_http_client.post.assert_awaited_once_with(f"/sessions/{eid}/restore")

    def test_restore_not_found(self, cli_runner, fake_http_client):
        """会话不存在（HTTP 404）→ NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_err(404, "会话不存在")
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
    """_run 异常映射补全：HTTP 422 / HTTP 500 → 错误信封."""

    def test_create_service_error(self, cli_runner, fake_http_client):
        """HTTP 422（服务层业务错误）→ VALIDATION_ERROR 信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_err(422, "会话创建失败")
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

    def test_create_validation_error(self, cli_runner, fake_http_client):
        """HTTP 422（内核侧 pydantic 校验）→ VALIDATION_ERROR 信封."""
        fake_http_client.post.side_effect = _http_err(422, "参数校验失败")
        result = cli_runner.invoke(
            app,
            ["create", "--type", "task", "--title", "每日定时写作"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_create_internal_error(self, cli_runner, fake_http_client):
        """HTTP 500（无响应头）→ INTERNAL_ERROR 信封 + 退出码 1（F38 §5.3:
        恒 HTTP 后 DB_ERROR 由 INTERNAL_ERROR 替代）."""
        fake_http_client.post.side_effect = _http_err(500, "数据库错误")
        result = cli_runner.invoke(
            app,
            ["create", "--type", "task", "--title", "每日定时写作"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert "数据库错误" in data["error"]["message"]

    def test_create_kernel_startup_error(self, cli_runner):
        """ensure_kernel 失败（内核冷启动超时）→ KERNEL_ERROR 信封 + 退出码 1（F38 spec §5.3）."""
        from inkflow.infrastructure.kernel import KernelStartupError

        with patch(
            "inkflow.cli.commands.session.ensure_kernel",
            AsyncMock(side_effect=KernelStartupError("启动超时")),
        ):
            result = cli_runner.invoke(
                app,
                ["create", "--type", "task", "--title", "每日定时写作"],
                obj=CliContext(json_output=True),
            )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "KERNEL_ERROR"
        assert "内核启动失败" in data["error"]["message"]
