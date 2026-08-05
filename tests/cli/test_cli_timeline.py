"""Timeline CLI 命令测试 — Mock TimelineService 隔离数据库（spec §4/§9 CLI 测试）.

覆盖（依据 specs/f12-timeline-service/spec.md §4/§9）:
- 各子命令成功路径与参数透传（create/list/view/check/get/update/delete/restore）
- 信封格式与退出码 0/1
- delete 二次确认 + --force；--json + delete 无 --force → VALIDATION_ERROR
- check 人类可读摘要（一致 vs 冲突 vs 已声明倒叙）与 --json 完整报告
- NOT_FOUND 错误信封；--time-value "" 清除语义透传
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from inkflow.cli.commands.timeline import app
from inkflow.cli.context import CliContext
from inkflow.domain.models.timeline import (
    ConsistencyReport,
    TimelineConflict,
    TimelineEvent,
    TimelineEventRef,
    TimelineEventUpdate,
    TimelineView,
)
from inkflow.domain.ports.timeline_errors import (
    ProjectNotFoundError,
    TimelineNotFoundError,
    TimelineServiceError,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def mock_timeline_service():
    """Mock TimelineService，绕过数据库（ADR-015 依赖注入）."""
    with patch(
        "inkflow.cli.commands.timeline.TimelineService", autospec=True
    ) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_create_tables():
    """Mock create_tables 避免数据库初始化."""
    with patch("inkflow.cli.commands.timeline.create_tables", AsyncMock()):
        yield


def _make_event(**overrides) -> TimelineEvent:
    """构造测试用 TimelineEvent 领域对象."""
    defaults = dict(
        id=uuid.uuid4(),
        project_id=PID,
        title="林尘觉醒金手指",
        description="外门考核夜，林尘丹田中的古鼎第一次亮起。",
        time_value=317.5,
        time_unit="年",
        time_display="青元历 317 年秋",
        narrative_position=3,
        timeline_flag="",
        extra={},
        is_deleted=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return TimelineEvent(**defaults)


def _make_conflict(**overrides) -> TimelineConflict:
    """构造测试用 TimelineConflict 领域对象."""
    defaults = dict(
        conflict_type="order_conflict",
        prev=TimelineEventRef(
            id=uuid.uuid4(),
            title="林尘觉醒金手指",
            time_value=317.5,
            time_display="青元历 317 年秋",
            narrative_position=2,
            timeline_flag="",
        ),
        next=TimelineEventRef(
            id=uuid.uuid4(),
            title="外门往事",
            time_value=312.0,
            time_display="青元历 312 年",
            narrative_position=3,
            timeline_flag="",
        ),
        message=(
            "叙事第 2 位事件「林尘觉醒金手指」（青元历 317 年秋）晚于叙事第 3 位"
            "事件「外门往事」（青元历 312 年）：叙事顺序与世界内时间矛盾。"
        ),
    )
    defaults.update(overrides)
    return TimelineConflict(**defaults)


def _make_report(**overrides) -> ConsistencyReport:
    """构造测试用 ConsistencyReport 领域对象."""
    defaults = dict(
        project_id=PID,
        checked=2,
        skipped=0,
        consistent=True,
        conflicts=[],
        flashbacks=[],
        event_timeline=[],
        narrative_order=[],
    )
    defaults.update(overrides)
    return ConsistencyReport(**defaults)


def _make_view(**overrides) -> TimelineView:
    """构造测试用 TimelineView 领域对象."""
    defaults = dict(project_id=PID, total=0, event_timeline=[], narrative_order=[])
    defaults.update(overrides)
    return TimelineView(**defaults)


class TestTimelineRegistration:
    def test_group_help_lists_all_commands(self):
        """timeline 组帮助包含全部 8 个命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）."""
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
            "restore",
        ):
            assert name in result.output


class TestTimelineCreate:
    def test_create_json_envelope(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """create --json → 成功信封 + 参数透传（UUID/float 转换）."""
        mock_timeline_service.create_event.return_value = _make_event(
            timeline_flag="flashback"
        )
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
        mock_timeline_service.create_event.assert_awaited_once_with(
            project_id=PID,
            title="林尘觉醒金手指",
            description="外门考核夜，古鼎第一次亮起。",
            time_value=317.5,
            time_unit="年",
            time_display="青元历 317 年秋",
            narrative_position=3,
            timeline_flag="flashback",
        )

    def test_create_human(self, cli_runner, mock_timeline_service, mock_create_tables):
        """create 人类模式 → 成功提示（含时间表达与叙事位置）."""
        mock_timeline_service.create_event.return_value = _make_event()
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

    def test_create_project_not_found(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_timeline_service.create_event.side_effect = ProjectNotFoundError()
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林尘觉醒金手指"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestTimelineList:
    def test_list_json(self, cli_runner, mock_timeline_service, mock_create_tables):
        """list --json → 成功信封 + 事件数组."""
        mock_timeline_service.list_events.return_value = ([_make_event()], 1)
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

    def test_list_human_empty(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """空列表人类模式 → 暂无事件."""
        mock_timeline_service.list_events.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无事件" in result.output

    def test_list_params_passthrough(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """list 搜索/排序/降序参数透传."""
        mock_timeline_service.list_events.return_value = ([], 0)
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
        mock_timeline_service.list_events.assert_awaited_once_with(
            project_id=PID,
            search="金手指",
            sort_by="time_value",
            sort_desc=False,
        )


class TestTimelineView:
    def test_view_json(self, cli_runner, mock_timeline_service, mock_create_tables):
        """view --json → 双线视图完整信封."""
        ev1 = _make_event(
            title="林尘拜入青云宗", time_value=315.0, narrative_position=1
        )
        ev2 = _make_event(title="宗门大比夺冠", time_value=319.0, narrative_position=4)
        mock_timeline_service.get_timeline_view.return_value = _make_view(
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
        mock_timeline_service.get_timeline_view.assert_awaited_once_with(project_id=PID)

    def test_view_human(self, cli_runner, mock_timeline_service, mock_create_tables):
        """view 人类模式 → 双线总览摘要（两种视图标题）."""
        ev1 = _make_event(
            title="林尘拜入青云宗", time_value=315.0, narrative_position=1
        )
        ev2 = _make_event(title="宗门大比夺冠", time_value=319.0, narrative_position=4)
        mock_timeline_service.get_timeline_view.return_value = _make_view(
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

    def test_view_project_not_found(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_timeline_service.get_timeline_view.side_effect = ProjectNotFoundError()
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
    def test_check_json(self, cli_runner, mock_timeline_service, mock_create_tables):
        """check --json → 完整一致性报告信封（含冲突与倒叙项）."""
        mock_timeline_service.check_consistency.return_value = _make_report(
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
        mock_timeline_service.check_consistency.assert_awaited_once_with(
            project_id=PID, include_flashbacks=True
        )

    def test_check_human_consistent(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """check 人类模式一致 → ✅ 摘要（含跳过计数）."""
        mock_timeline_service.check_consistency.return_value = _make_report(
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

    def test_check_human_conflicts(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """check 人类模式有冲突 → ⚠️ 摘要 + 逐条 [冲突] 行."""
        mock_timeline_service.check_consistency.return_value = _make_report(
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

    def test_check_human_flashbacks(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """check 人类模式含已声明倒叙 → 💡 摘要 + [倒叙] 行（不影响一致）."""
        mock_timeline_service.check_consistency.return_value = _make_report(
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

    def test_check_no_include_flashbacks(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """check --no-include-flashbacks → include_flashbacks=False 透传."""
        mock_timeline_service.check_consistency.return_value = _make_report(
            consistent=True
        )
        result = cli_runner.invoke(
            app,
            ["check", "--project-id", str(PID), "--no-include-flashbacks"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        mock_timeline_service.check_consistency.assert_awaited_once_with(
            project_id=PID, include_flashbacks=False
        )

    def test_check_project_not_found(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_timeline_service.check_consistency.side_effect = ProjectNotFoundError()
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
    def test_get_json(self, cli_runner, mock_timeline_service, mock_create_tables):
        """事件存在 → 成功信封 + event_id 透传."""
        eid = uuid.uuid4()
        mock_timeline_service.get_event.return_value = _make_event()
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林尘觉醒金手指"
        mock_timeline_service.get_event.assert_awaited_once_with(event_id=eid)

    def test_get_not_found_json(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """事件不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_timeline_service.get_event.return_value = None
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

    def test_get_invalid_uuid(
        self, cli_runner, mock_timeline_service, mock_create_tables
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


class TestTimelineUpdate:
    def test_update_json(self, cli_runner, mock_timeline_service, mock_create_tables):
        """update --json → 成功信封 + TimelineEventUpdate 透传（仅传入字段）."""
        eid = uuid.uuid4()
        mock_timeline_service.update_event.return_value = _make_event(
            title="林尘觉醒金手指·改"
        )
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
        call = mock_timeline_service.update_event.await_args
        assert call.kwargs["event_id"] == eid
        upd: TimelineEventUpdate = call.kwargs["update"]
        assert upd.title == "林尘觉醒金手指·改"
        assert upd.description == "新描述"
        assert "time_value" not in upd.model_fields_set
        assert "timeline_flag" not in upd.model_fields_set

    def test_update_clear_time_value(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """update --time-value \"\" → 清除语义透传（time_value=\"\" 进入 DTO）."""
        eid = uuid.uuid4()
        mock_timeline_service.update_event.return_value = _make_event(time_value=None)
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(eid), "--time-value", ""],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_timeline_service.update_event.await_args
        upd: TimelineEventUpdate = call.kwargs["update"]
        assert "time_value" in upd.model_fields_set
        assert upd.time_value == ""

    def test_update_float_conversion(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """update --time-value 317.5 → float 转换后进入 DTO."""
        eid = uuid.uuid4()
        mock_timeline_service.update_event.return_value = _make_event()
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(eid), "--time-value", "317.5"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_timeline_service.update_event.await_args
        upd: TimelineEventUpdate = call.kwargs["update"]
        assert upd.time_value == 317.5

    def test_update_invalid_time_value(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
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
        mock_timeline_service.update_event.assert_not_awaited()

    def test_update_not_found(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """事件不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_timeline_service.update_event.return_value = None
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestTimelineDelete:
    def test_delete_force_json(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """delete --force --json → 成功信封 + 软删除（服务层 soft_delete）."""
        eid = uuid.uuid4()
        mock_timeline_service.soft_delete_event.return_value = True
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
        mock_timeline_service.soft_delete_event.assert_awaited_once_with(event_id=eid)

    def test_delete_permanent_hard_delete(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """delete --permanent → 服务层 hard_delete_event（物理删除）."""
        eid = uuid.uuid4()
        mock_timeline_service.hard_delete_event.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid), "--force", "--permanent"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        mock_timeline_service.hard_delete_event.assert_awaited_once_with(event_id=eid)
        mock_timeline_service.soft_delete_event.assert_not_awaited()

    def test_delete_confirm_yes(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除."""
        eid = uuid.uuid4()
        mock_timeline_service.soft_delete_event.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output
        mock_timeline_service.soft_delete_event.assert_awaited_once_with(event_id=eid)

    def test_delete_confirm_no(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """无 --force 人类模式 → 回答 n 取消，不调用服务."""
        eid = uuid.uuid4()
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid)],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "取消" in result.output
        mock_timeline_service.soft_delete_event.assert_not_awaited()

    def test_delete_json_no_force(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
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
        mock_timeline_service.soft_delete_event.assert_not_awaited()

    def test_delete_not_found(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """事件不存在（服务返回 False）→ NOT_FOUND 错误信封."""
        mock_timeline_service.soft_delete_event.return_value = False
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestTimelineRestore:
    def test_restore_json(self, cli_runner, mock_timeline_service, mock_create_tables):
        """restore --json → 成功信封 + event_id 透传."""
        eid = uuid.uuid4()
        mock_timeline_service.restore_event.return_value = _make_event()
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林尘觉醒金手指"
        mock_timeline_service.restore_event.assert_awaited_once_with(event_id=eid)

    def test_restore_not_found(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """事件不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_timeline_service.restore_event.return_value = None
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestTimelineErrorMapping:
    """_run 异常映射补全：NotFound 抛异常 / ServiceError / ValidationError / DB_ERROR."""

    def test_get_not_found_error_raised(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """服务抛 TimelineNotFoundError → NOT_FOUND 信封 + 退出码 1."""
        mock_timeline_service.get_event.side_effect = TimelineNotFoundError()
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_update_service_error(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """服务抛 TimelineServiceError → VALIDATION_ERROR 信封 + 退出码 1."""
        mock_timeline_service.update_event.side_effect = TimelineServiceError(
            "非法状态"
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
        assert "非法状态" in data["error"]["message"]

    def test_update_validation_error(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """pydantic ValidationError → VALIDATION_ERROR 信封."""
        mock_timeline_service.update_event.side_effect = (
            ValidationError.from_exception_data(
                "TimelineEventUpdate",
                [
                    {
                        "type": "string_type",
                        "loc": ("title",),
                        "msg": "Input should be a valid string",
                        "input": 123,
                    }
                ],
            )
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

    def test_update_db_error(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """服务抛未知异常 → DB_ERROR 信封 + 退出码 1."""
        mock_timeline_service.update_event.side_effect = RuntimeError("boom")
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"
        assert "boom" in data["error"]["message"]


class TestTimelineHumanOutput:
    """人类可读输出补全：时间未知 / list 非空 / view 空 / get 详情 / update / restore."""

    def test_create_time_unknown_human(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """create 人类模式无时间信息 → 时间未知."""
        mock_timeline_service.create_event.return_value = _make_event(
            time_value=None, time_display=""
        )
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林尘觉醒金手指"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "时间未知" in result.output

    def test_list_human_non_empty(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """list 人类模式非空 → 总数汇总 + 逐条事件输出."""
        mock_timeline_service.list_events.return_value = ([_make_event()], 1)
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "共 1 个事件" in result.output
        assert "#3 [林尘觉醒金手指]（青元历 317 年秋）" in result.output

    def test_view_human_empty(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """view 人类模式空时间线 → 暂无事件."""
        mock_timeline_service.get_timeline_view.return_value = _make_view(total=0)
        result = cli_runner.invoke(
            app,
            ["view", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无事件" in result.output

    def test_get_human(self, cli_runner, mock_timeline_service, mock_create_tables):
        """get 人类模式 → 全字段详情输出（含正叙标记回退）."""
        mock_timeline_service.get_event.return_value = _make_event()
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

    def test_update_all_fields(
        self, cli_runner, mock_timeline_service, mock_create_tables
    ):
        """update 传全字段 → time_unit/time_display/narrative_position/timeline_flag 进入 DTO."""
        eid = uuid.uuid4()
        mock_timeline_service.update_event.return_value = _make_event()
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
        call = mock_timeline_service.update_event.await_args
        upd: TimelineEventUpdate = call.kwargs["update"]
        assert upd.time_unit == "月"
        assert upd.time_display == "青元历 318 年春"
        assert upd.narrative_position == 5
        assert upd.timeline_flag == "flashforward"
        assert "title" not in upd.model_fields_set

    def test_update_human(self, cli_runner, mock_timeline_service, mock_create_tables):
        """update 人类模式 → 成功提示."""
        mock_timeline_service.update_event.return_value = _make_event(
            title="林尘觉醒金手指·改"
        )
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "林尘觉醒金手指·改"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "事件已更新: [林尘觉醒金手指·改]" in result.output

    def test_restore_human(self, cli_runner, mock_timeline_service, mock_create_tables):
        """restore 人类模式 → 成功提示."""
        mock_timeline_service.restore_event.return_value = _make_event()
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "事件已恢复: [林尘觉醒金手指]" in result.output
