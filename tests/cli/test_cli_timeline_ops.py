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
