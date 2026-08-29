"""Timeline CLI 命令测试 — Mock ensure_kernel + InkFlowHTTPClient（spec §4/§9 CLI 测试）.

覆盖（依据 specs/f12-timeline/spec.md §4/§9）:
- 各子命令成功路径与参数透传（create/list/view/check/get/update/delete）
- 信封格式与退出码 0/1
- delete 二次确认 + --force；--json + delete 无 --force → VALIDATION_ERROR
- check 人类可读摘要（一致 vs 冲突 vs 已声明倒叙）与 --json 完整报告
- NOT_FOUND 错误信封；--time-value "" 清除语义透传

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
- create → POST /projects/{pid}/timeline/events（body = TimelineEventCreateBody 字段）
- list → GET /projects/{pid}/timeline/events（params: search/sort_by/sort_desc）
- view → GET /projects/{pid}/timeline
- check → GET /projects/{pid}/timeline/check（params: include_flashbacks）
- get → GET /timeline/events/{id}；update → PATCH /timeline/events/{id}
- delete → DELETE /timeline/events/{id}（v1.1 真删，无 params）
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


class TestTimelineRegistration:
    def test_group_help_lists_all_commands(self):
        """timeline 组帮助包含全部 7 个命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）."""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in (
            "create",
            "list",
            "view",
            "check",
            "get",
            "update",
            "delete",
        ):
            assert name in result.output


class TestTimelineCreate:
    def test_create_json_envelope(self, cli_runner, fake_http_client):
        """create --json → 成功信封 + 参数透传（UUID/float 转换）."""
        fake_http_client.post.return_value = _make_event(timeline_flag="flashback")
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--title",
                "林尘觉醒金手指",
                "--description",
                "外门考核夜，古鼎第一次亮起。",
                "--time-value",
                "317.5",
                "--time-unit",
                "年",
                "--time-display",
                "青元历 317 年秋",
                "--narrative-position",
                "3",
                "--timeline-flag",
                "flashback",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林尘觉醒金手指"
        assert data["data"]["time_value"] == 317.5
        fake_http_client.post.assert_awaited_once_with(
            f"/projects/{PID}/timeline/events",
            json={
                "title": "林尘觉醒金手指",
                "description": "外门考核夜，古鼎第一次亮起。",
                "time_value": 317.5,
                "time_unit": "年",
                "time_display": "青元历 317 年秋",
                "narrative_position": 3,
                "timeline_flag": "flashback",
            },
        )

    def test_create_human(self, cli_runner, fake_http_client):
        """create 人类模式 → 成功提示（含时间表达与叙事位置）."""
        fake_http_client.post.return_value = _make_event()
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林尘觉醒金手指"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "事件创建成功" in result.output
        assert "林尘觉醒金手指" in result.output
        assert "青元历 317 年秋" in result.output
        assert "叙事第 3 位" in result.output

    def test_create_project_not_found(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.post.side_effect = HttpApiError(404, "项目不存在")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林尘觉醒金手指"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_create_kernel_startup_error(self, cli_runner):
        """ensure_kernel 失败（内核冷启动超时）→ KERNEL_ERROR 信封 + 退出码 1（F38 spec §5.3）."""
        from inkflow.infrastructure.kernel import KernelStartupError

        with patch(
            "inkflow.cli.commands.timeline.ensure_kernel",
            AsyncMock(side_effect=KernelStartupError("启动超时")),
        ):
            result = cli_runner.invoke(
                app,
                ["create", "--project-id", str(PID), "--title", "林尘觉醒金手指"],
                obj=CliContext(json_output=True),
            )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "KERNEL_ERROR"
        assert "内核启动失败" in data["error"]["message"]


class TestTimelineList:
    def test_list_json(self, cli_runner, fake_http_client):
        """list --json → 成功信封 + 事件数组."""
        fake_http_client.get.return_value = {
            "items": [_make_event()],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert isinstance(data["data"], list)
        assert data["data"][0]["title"] == "林尘觉醒金手指"

    def test_list_human_empty(self, cli_runner, fake_http_client):
        """空列表人类模式 → 暂无事件."""
        fake_http_client.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无事件" in result.output

    def test_list_params_passthrough(self, cli_runner, fake_http_client):
        """list 搜索/排序/降序参数透传."""
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
                "--project-id",
                str(PID),
                "--search",
                "金手指",
                "--sort",
                "time_value",
                "--no-sort-desc",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.get.assert_awaited_once_with(
            f"/projects/{PID}/timeline/events",
            params={"search": "金手指", "sort_by": "time_value", "sort_desc": False},
        )


class TestTimelineView:
    def test_view_json(self, cli_runner, fake_http_client):
        """view --json → 双线视图完整信封."""
        ev1 = _make_event(
            title="林尘拜入青云宗", time_value=315.0, narrative_position=1
        )
        ev2 = _make_event(title="宗门大比夺冠", time_value=319.0, narrative_position=4)
        fake_http_client.get.return_value = _make_view(
            total=2, event_timeline=[ev1, ev2], narrative_order=[ev1, ev2]
        )
        result = cli_runner.invoke(
            app,
            ["view", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["total"] == 2
        assert data["data"]["event_timeline"][0]["title"] == "林尘拜入青云宗"
        assert data["data"]["narrative_order"][1]["title"] == "宗门大比夺冠"
        fake_http_client.get.assert_awaited_once_with(f"/projects/{PID}/timeline")

    def test_view_human(self, cli_runner, fake_http_client):
        """view 人类模式 → 双线总览摘要（两种视图标题）."""
        ev1 = _make_event(
            title="林尘拜入青云宗", time_value=315.0, narrative_position=1
        )
        ev2 = _make_event(title="宗门大比夺冠", time_value=319.0, narrative_position=4)
        fake_http_client.get.return_value = _make_view(
            total=2, event_timeline=[ev1, ev2], narrative_order=[ev1, ev2]
        )
        result = cli_runner.invoke(
            app,
            ["view", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "双线总览" in result.output
        assert "共 2 个事件" in result.output
        assert "1. 林尘拜入青云宗(青元历 317 年秋)" in result.output
        assert "2. 宗门大比夺冠" in result.output

    def test_view_project_not_found(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.get.side_effect = HttpApiError(404, "项目不存在")
        result = cli_runner.invoke(
            app,
            ["view", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestTimelineCheck:
    def test_check_json(self, cli_runner, fake_http_client):
        """check --json → 完整一致性报告信封（含冲突与倒叙项）."""
        fake_http_client.get.return_value = _make_report(
            checked=4,
            skipped=1,
            consistent=False,
            conflicts=[_make_conflict()],
            flashbacks=[
                _make_conflict(
                    conflict_type="flashback",
                    message="叙事第 5 位事件「外门往事」声明为倒叙（flashback）：判定合法。",
                )
            ],
        )
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["checked"] == 4
        assert data["data"]["skipped"] == 1
        assert data["data"]["consistent"] is False
        assert data["data"]["conflicts"][0]["conflict_type"] == "order_conflict"
        assert data["data"]["flashbacks"][0]["conflict_type"] == "flashback"
        fake_http_client.get.assert_awaited_once_with(
            f"/projects/{PID}/timeline/check", params={"include_flashbacks": True}
        )

    def test_check_human_consistent(self, cli_runner, fake_http_client):
        """check 人类模式一致 → ✅ 摘要（含跳过计数）."""
        fake_http_client.get.return_value = _make_report(
            checked=4, skipped=1, consistent=True
        )
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "一致性检查" in result.output
        assert "✅ 一致" in result.output
        assert "检查 4 个事件" in result.output
        assert "跳过 1 个时间未知" in result.output

    def test_check_human_conflicts(self, cli_runner, fake_http_client):
        """check 人类模式有冲突 → ⚠️ 摘要 + 逐条 [冲突] 行."""
        fake_http_client.get.return_value = _make_report(
            checked=2, skipped=0, consistent=False, conflicts=[_make_conflict()]
        )
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "发现 1 个冲突" in result.output
        assert "[冲突]" in result.output
        assert "叙事顺序与世界内时间矛盾" in result.output

    def test_check_human_flashbacks(self, cli_runner, fake_http_client):
        """check 人类模式含已声明倒叙 → 💡 摘要 + [倒叙] 行（不影响一致）."""
        fake_http_client.get.return_value = _make_report(
            checked=2,
            skipped=0,
            consistent=True,
            flashbacks=[
                _make_conflict(
                    conflict_type="flashback",
                    message="叙事第 5 位事件「外门往事」声明为倒叙（flashback）：判定合法。",
                )
            ],
        )
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 一致" in result.output
        assert "1 个已声明倒叙/插叙" in result.output
        assert "[倒叙]" in result.output

    def test_check_no_include_flashbacks(self, cli_runner, fake_http_client):
        """check --no-include-flashbacks → include_flashbacks=False 透传."""
        fake_http_client.get.return_value = _make_report(consistent=True)
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID), "--no-include-flashbacks"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.get.assert_awaited_once_with(
            f"/projects/{PID}/timeline/check", params={"include_flashbacks": False}
        )

    def test_check_project_not_found(self, cli_runner, fake_http_client):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.get.side_effect = HttpApiError(404, "项目不存在")
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestTimelineGet:
    def test_get_json(self, cli_runner, fake_http_client):
        """事件存在 → 成功信封 + event_id 透传."""
        eid = uuid.uuid4()
        fake_http_client.get.return_value = _make_event()
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林尘觉醒金手指"
        fake_http_client.get.assert_awaited_once_with(f"/timeline/events/{eid}")

    def test_get_not_found_json(self, cli_runner, fake_http_client):
        """事件不存在 → NOT_FOUND 错误信封 + 退出码 1."""
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
        assert "事件不存在" in data["error"]["message"]

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


class TestTimelineUpdate:
    def test_update_json(self, cli_runner, fake_http_client):
        """update --json → 成功信封 + 更新字段透传（仅传入字段）."""
        eid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_event(title="林尘觉醒金手指·改")
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                str(eid),
                "--title",
                "林尘觉醒金手指·改",
                "--description",
                "新描述",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林尘觉醒金手指·改"
        call = fake_http_client.patch.await_args
        assert call.args[0] == f"/timeline/events/{eid}"
        body: dict = call.kwargs["json"]
        assert body["title"] == "林尘觉醒金手指·改"
        assert body["description"] == "新描述"
        assert "time_value" not in body
        assert "timeline_flag" not in body

    def test_update_clear_time_value(self, cli_runner, fake_http_client):
        """update --time-value "" → 清除语义透传（time_value="" 进入 body）."""
        eid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_event(time_value=None)
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(eid), "--time-value", ""],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body: dict = fake_http_client.patch.await_args.kwargs["json"]
        assert "time_value" in body
        assert body["time_value"] == ""

    def test_update_float_conversion(self, cli_runner, fake_http_client):
        """update --time-value 317.5 → float 转换后进入 body."""
        eid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_event()
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(eid), "--time-value", "317.5"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        body: dict = fake_http_client.patch.await_args.kwargs["json"]
        assert body["time_value"] == 317.5

    def test_update_invalid_time_value(self, cli_runner, fake_http_client):
        """update --time-value 非数字 → VALIDATION_ERROR + 退出码 1."""
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--time-value", "abc"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.patch.assert_not_awaited()

    def test_update_not_found(self, cli_runner, fake_http_client):
        """事件不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        from inkflow.infrastructure.http import HttpApiError  # RED 期惰性导入

        fake_http_client.patch.side_effect = HttpApiError(404, "事件不存在")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
