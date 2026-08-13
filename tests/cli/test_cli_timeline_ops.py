"""Timeline CLI 命令测试（delete/错误映射/人类输出）— Mock ensure_kernel +
InkFlowHTTPClient（spec §4/§9 CLI 测试）.

覆盖（依据 specs/f12-timeline-service/spec.md §4/§9）:
- delete 二次确认 + --force（v1.1 真删，不可恢复）
- --json + delete 无 --force → VALIDATION_ERROR
- 错误映射：NotFound → NOT_FOUND；ServiceError → VALIDATION_ERROR；
  未知异常 → INTERNAL_ERROR；typer.Exit 透传
- 人类可读输出补全（时间未知 / list 非空 / view 空 / get 详情 / update）

F38 改造（#169）：mock 目标从 domain Service 迁移到 ensure_kernel + InkFlowHTTPClient
（HTTP JSON 响应）；create_tables patch 已移除。

── RED 形态说明 ─────────────────────────────────────────────
- fake_http_client fixture patch 命令模块命名空间
  （inkflow.cli.commands.timeline.ensure_kernel / .InkFlowHTTPClient）——当前命令模块
  尚无这两个属性 → fixture setup 抛 AttributeError → 相关用例 ERROR（同根因，
  预期 RED；GREEN 命令改造落地后自动转绿）。
- HttpApiError 在用例体内惰性导入：RED 阶段 inkflow.infrastructure.http 尚未实现，
  顶部 import 会使整文件收集失败（ModuleNotFoundError），无法呈现上述预期形态。

── 端点契约（spec §3.1 表）────────────────────────────────
- delete → DELETE /timeline/events/{id}（v1.1 真删，无 params）；204 无 body →
  CLI 自构 {"deleted": true, "id": ...} 信封
- 错误映射（spec §5.3）：404 → NOT_FOUND；422 → VALIDATION_ERROR；500 无头 →
  INTERNAL_ERROR（DB_ERROR 恒 HTTP 后由 INTERNAL_ERROR 替代，spec §5.3 注）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.timeline import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP（F38 mock 轨）。"""
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
            "inkflow.cli.commands.timeline.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.timeline.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_cls.return_value = mock_instance
        yield mock_instance


def _make_event(**overrides: object) -> dict:
    """构造测试用 TimelineEvent JSON dict（model_dump(mode="json") 形态）."""
    defaults: dict[str, object] = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        title="林尘觉醒金手指",
        description="外门考核夜，林尘丹田中的古鼎第一次亮起。",
        time_value=317.5,
        time_unit="年",
        time_display="青元历 317 年秋",
        narrative_position=3,
        timeline_flag="",
        extra={},
        created_at="2026-08-02T12:00:00",
        updated_at="2026-08-02T12:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_conflict(**overrides: object) -> dict:
    """构造测试用 TimelineConflict JSON dict."""
    defaults: dict[str, object] = dict(
        conflict_type="order_conflict",
        prev={
            "id": str(uuid.uuid4()),
            "title": "林尘觉醒金手指",
            "time_value": 317.5,
            "time_display": "青元历 317 年秋",
            "narrative_position": 2,
            "timeline_flag": "",
        },
        next={
            "id": str(uuid.uuid4()),
            "title": "外门往事",
            "time_value": 312.0,
            "time_display": "青元历 312 年",
            "narrative_position": 3,
            "timeline_flag": "",
        },
        message=(
            "叙事第 2 位事件「林尘觉醒金手指」（青元历 317 年秋）晚于叙事第 3 位"
            "事件「外门往事」（青元历 312 年）：叙事顺序与世界内时间矛盾。"
        ),
    )
    defaults.update(overrides)
    return defaults


def _make_report(**overrides: object) -> dict:
    """构造测试用 ConsistencyReport JSON dict."""
    defaults: dict[str, object] = dict(
        project_id=str(PID),
        checked=2,
        skipped=0,
        consistent=True,
        conflicts=[],
        flashbacks=[],
        event_timeline=[],
        narrative_order=[],
    )
    defaults.update(overrides)
    return defaults


def _make_view(**overrides: object) -> dict:
    """构造测试用 TimelineView JSON dict."""
    defaults: dict[str, object] = dict(
        project_id=str(PID), total=0, event_timeline=[], narrative_order=[]
    )
    defaults.update(overrides)
    return defaults


class TestTimelineDelete:
    def test_delete_force_json(self, cli_runner, fake_http_client):
        """delete --force --json → 成功信封 + 真删除."""
        eid = uuid.uuid4()
        fake_http_client.delete.return_value = {}
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        assert data["data"]["id"] == str(eid)
        fake_http_client.delete.assert_awaited_once_with(f"/timeline/events/{eid}")

    def test_delete_confirm_yes(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除."""
        eid = uuid.uuid4()
        fake_http_client.delete.return_value = {}
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output
        fake_http_client.delete.assert_awaited_once_with(f"/timeline/events/{eid}")

    def test_delete_confirm_no(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 回答 n 取消，不调用客户端."""
        eid = uuid.uuid4()
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid)],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "取消" in result.output
        fake_http_client.delete.assert_not_awaited()

    def test_delete_json_no_force(self, cli_runner, fake_http_client):
        """--json 且无 --force → VALIDATION_ERROR + 退出码 1（F7 §7 约定）."""
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.delete.assert_not_awaited()

    def test_delete_not_found(self, cli_runner, fake_http_client):
        """事件不存在（API 404）→ NOT_FOUND 错误信封."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.delete.side_effect = HttpApiError(404, "事件不存在")
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestTimelineErrorMapping:
    """错误映射补全：NotFound / ServiceError / ValidationError / INTERNAL_ERROR."""

    def test_get_not_found_error_raised(self, cli_runner, fake_http_client):
        """API 404（事件不存在）→ NOT_FOUND 信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.get.side_effect = HttpApiError(404, "事件不存在")
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_update_service_error(self, cli_runner, fake_http_client):
        """API 422（业务校验失败）→ VALIDATION_ERROR 信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.patch.side_effect = HttpApiError(422, "非法状态")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "非法状态" in data["error"]["message"]

    def test_update_validation_error(self, cli_runner, fake_http_client):
        """API 422（参数校验）→ VALIDATION_ERROR 信封."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.patch.side_effect = HttpApiError(
            422, "Input should be a valid string"
        )
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_update_db_error(self, cli_runner, fake_http_client):
        """HTTP 500 无错误码头 → INTERNAL_ERROR 信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.patch.side_effect = HttpApiError(500, "boom")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert "boom" in data["error"]["message"]


class TestTimelineHumanOutput:
    """人类可读输出补全：时间未知 / list 非空 / view 空 / get 详情 / update."""

    def test_create_time_unknown_human(self, cli_runner, fake_http_client):
        """create 人类模式无时间信息 → 时间未知."""
        fake_http_client.post.return_value = _make_event(
            time_value=None, time_display=""
        )
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林尘觉醒金手指"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "时间未知" in result.output

    def test_list_human_non_empty(self, cli_runner, fake_http_client):
        """list 人类模式非空 → 总数汇总 + 逐条事件输出."""
        fake_http_client.get.return_value = {
            "items": [_make_event()],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "共 1 个事件" in result.output
        assert "#3 [林尘觉醒金手指]（青元历 317 年秋）" in result.output

    def test_view_human_empty(self, cli_runner, fake_http_client):
        """view 人类模式空时间线 → 暂无事件."""
        fake_http_client.get.return_value = _make_view(total=0)
        result = cli_runner.invoke(
            app,
            ["view", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无事件" in result.output

    def test_get_human(self, cli_runner, fake_http_client):
        """get 人类模式 → 全字段详情输出（含正叙标记回退）."""
        fake_http_client.get.return_value = _make_event()
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        for token in (
            "标题:",
            "林尘觉醒金手指",
            "世界内时间:",
            "青元历 317 年秋",
            "叙事位置:",
            "时间线标记:",
            "（正叙）",
        ):
            assert token in result.output

    def test_update_all_fields(self, cli_runner, fake_http_client):
        """update 传全字段 → time_unit/time_display/narrative_position/timeline_flag 进入 body."""
        eid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_event()
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                str(eid),
                "--time-unit",
                "月",
                "--time-display",
                "青元历 318 年春",
                "--narrative-position",
                "5",
                "--timeline-flag",
                "flashforward",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body: dict = fake_http_client.patch.await_args.kwargs["json"]
        assert body["time_unit"] == "月"
        assert body["time_display"] == "青元历 318 年春"
        assert body["narrative_position"] == 5
        assert body["timeline_flag"] == "flashforward"
        assert "title" not in body

    def test_update_human(self, cli_runner, fake_http_client):
        """update 人类模式 → 成功提示."""
        fake_http_client.patch.return_value = _make_event(title="林尘觉醒金手指·改")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "林尘觉醒金手指·改"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "事件已更新: [林尘觉醒金手指·改]" in result.output
