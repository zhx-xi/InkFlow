"""Foreshadowing CLI 命令测试 — Mock ForeshadowingService 隔离数据库（spec §4/§9 CLI 测试）.

覆盖（依据 specs/f13-foreshadowing-service/spec.md §4/§9）:
- 各子命令成功路径与参数透传（create/list/get/update/delete/restore/resolve/reopen，含 --event-id）
- 信封格式与退出码 0/1/2（--status 非法值 → 退出码 2）
- delete 二次确认 + --force；--json + delete 无 --force → VALIDATION_ERROR
- resolve/reopen 人类可读输出（✅ 伏笔已回收/已重新开启）与 --json 完整对象
- NOT_FOUND 错误信封；--event-id "" 清除语义透传
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from inkflow.cli.commands.foreshadowing import app
from inkflow.cli.context import CliContext
from inkflow.domain.models.foreshadowing import (
    Foreshadowing,
    ForeshadowingCreate,
    ForeshadowingStatus,
    ForeshadowingUpdate,
)
from inkflow.domain.ports.foreshadowing_errors import (
    ForeshadowingServiceError,
    ProjectNotFoundError,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def mock_foreshadowing_service():
    """Mock ForeshadowingService，绕过数据库（ADR-015 依赖注入）."""
    with patch(
        "inkflow.cli.commands.foreshadowing.ForeshadowingService", autospec=True
    ) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_create_tables():
    """Mock create_tables 避免数据库初始化."""
    with patch("inkflow.cli.commands.foreshadowing.create_tables", AsyncMock()):
        yield


def _make_foreshadowing(**overrides) -> Foreshadowing:
    """构造测试用 Foreshadowing 领域对象."""
    defaults = dict(
        id=uuid.uuid4(),
        project_id=PID,
        title="林晚的身世",
        description="林晚右肩的胎记与女主母亲的信物相同；预期第 30 章前后揭露。",
        priority=80,
        status=ForeshadowingStatus.OPEN,
        location="第 5 章·林晚沐浴场景",
        event_id=None,
        resolved_at=None,
        extra={},
        is_deleted=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return Foreshadowing(**defaults)


class TestForeshadowingRegistration:
    def test_group_help_lists_all_commands(self):
        """foreshadowing 组帮助包含全部 8 个命令（NO_COLOR 规避 FORCE_COLOR 渲染坑）."""
        runner = CliRunner(env={"NO_COLOR": "1"})
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for name in (
            "create",
            "list",
            "get",
            "update",
            "delete",
            "restore",
            "resolve",
            "reopen",
        ):
            assert name in result.output


class TestForeshadowingCreate:
    def test_create_json_envelope(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """create --json → 成功信封 + 参数透传（UUID/priority 转换，含 --event-id 挂接）."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.create.return_value = _make_foreshadowing(
            event_id=eid
        )
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--title",
                "林晚的身世",
                "--description",
                "林晚右肩的胎记与女主母亲的信物相同。",
                "--priority",
                "80",
                "--location",
                "第 5 章·林晚沐浴场景",
                "--event-id",
                str(eid),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林晚的身世"
        assert data["data"]["priority"] == 80
        assert data["data"]["event_id"] == str(eid)
        call = mock_foreshadowing_service.create.await_args
        create_data: ForeshadowingCreate = call.kwargs["data"]
        assert create_data.project_id == PID
        assert create_data.title == "林晚的身世"
        assert create_data.priority == 80
        assert create_data.event_id == eid

    def test_create_human(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """create 人类模式 → 成功提示（含优先级与未回收状态）."""
        mock_foreshadowing_service.create.return_value = _make_foreshadowing(
            priority=80
        )
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 伏笔创建成功: [林晚的身世]" in result.output
        assert "优先级 80" in result.output
        assert "未回收" in result.output

    def test_create_project_not_found(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_foreshadowing_service.create.side_effect = ProjectNotFoundError()
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestForeshadowingList:
    def test_list_json(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """list --json → 成功信封 + 伏笔数组."""
        mock_foreshadowing_service.list.return_value = ([_make_foreshadowing()], 1)
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert isinstance(data["data"], list)
        assert data["data"][0]["title"] == "林晚的身世"

    def test_list_human_empty(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """空列表人类模式 → 暂无伏笔."""
        mock_foreshadowing_service.list.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无伏笔" in result.output

    def test_list_human_open(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """未回收伏笔人类模式 → 📋 摘要（编号 + 优先级 + 埋设位置）."""
        mock_foreshadowing_service.list.return_value = ([_make_foreshadowing()], 1)
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "未回收伏笔 1 条" in result.output
        assert "1. [林晚的身世] (优先级 80, 第 5 章·林晚沐浴场景)" in result.output

    def test_list_human_resolved(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """已回收伏笔人类模式 → 🔍 摘要（含回收日期）."""
        mock_foreshadowing_service.list.return_value = (
            [
                _make_foreshadowing(
                    status=ForeshadowingStatus.RESOLVED,
                    resolved_at=datetime(2026, 8, 10, 3, 0, 0),
                )
            ],
            1,
        )
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已回收伏笔 1 条" in result.output
        assert "[林晚的身世] (回收于 2026-08-10)" in result.output

    def test_list_params_passthrough(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """list 状态过滤/搜索/排序/降序参数透传."""
        mock_foreshadowing_service.list.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            [
                "list",
                "--project-id",
                str(PID),
                "--status",
                "open",
                "--search",
                "身世",
                "--sort",
                "title",
                "--no-sort-desc",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        mock_foreshadowing_service.list.assert_awaited_once_with(
            project_id=PID,
            search="身世",
            status="open",
            sort_by="title",
            sort_desc=False,
        )

    def test_list_invalid_status_exit_code_2(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """--status 非法值 → 用法错误退出码 2（F7 §7 非法枚举值）."""
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID), "--status", "bogus"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_foreshadowing_service.list.assert_not_awaited()

    def test_list_project_not_found(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_foreshadowing_service.list.side_effect = ProjectNotFoundError()
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestForeshadowingGet:
    def test_get_json(self, cli_runner, mock_foreshadowing_service, mock_create_tables):
        """伏笔存在 → 成功信封 + id 透传."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.get.return_value = _make_foreshadowing()
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林晚的身世"
        mock_foreshadowing_service.get.assert_awaited_once_with(foreshadowing_id=eid)

    def test_get_not_found_json(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """伏笔不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_foreshadowing_service.get.return_value = None
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "伏笔不存在" in data["error"]["message"]

    def test_get_invalid_uuid(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
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


class TestForeshadowingUpdate:
    def test_update_json(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """update --json → 成功信封 + ForeshadowingUpdate 透传（仅传入字段）."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.update.return_value = _make_foreshadowing(
            title="林晚的身世·改"
        )
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                str(eid),
                "--title",
                "林晚的身世·改",
                "--description",
                "新描述",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林晚的身世·改"
        call = mock_foreshadowing_service.update.await_args
        assert call.kwargs["foreshadowing_id"] == eid
        upd: ForeshadowingUpdate = call.kwargs["data"]
        assert upd.title == "林晚的身世·改"
        assert upd.description == "新描述"
        assert "priority" not in upd.model_fields_set
        assert "event_id" not in upd.model_fields_set

    def test_update_clear_event_id(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """update --event-id "" → 清除语义透传（event_id="" 进入 DTO）."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.update.return_value = _make_foreshadowing(
            event_id=None
        )
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(eid), "--event-id", ""],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_foreshadowing_service.update.await_args
        upd: ForeshadowingUpdate = call.kwargs["data"]
        assert "event_id" in upd.model_fields_set
        assert upd.event_id == ""

    def test_update_event_id_uuid(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """update --event-id <uuid> → UUID 转换后进入 DTO."""
        eid = uuid.uuid4()
        new_eid = uuid.uuid4()
        mock_foreshadowing_service.update.return_value = _make_foreshadowing(
            event_id=new_eid
        )
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(eid), "--event-id", str(new_eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_foreshadowing_service.update.await_args
        upd: ForeshadowingUpdate = call.kwargs["data"]
        assert upd.event_id == new_eid

    def test_update_not_found(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """伏笔不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_foreshadowing_service.update.return_value = None
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "新名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestForeshadowingDelete:
    def test_delete_force_json(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """delete --force --json → 成功信封 + 软删除（服务层 soft_delete）."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.get.return_value = _make_foreshadowing()
        mock_foreshadowing_service.soft_delete.return_value = True
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
        mock_foreshadowing_service.soft_delete.assert_awaited_once_with(
            foreshadowing_id=eid
        )

    def test_delete_permanent_hard_delete(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """delete --permanent → 服务层 hard_delete（物理删除）."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.get.return_value = _make_foreshadowing()
        mock_foreshadowing_service.hard_delete.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid), "--force", "--permanent"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        mock_foreshadowing_service.hard_delete.assert_awaited_once_with(
            foreshadowing_id=eid
        )
        mock_foreshadowing_service.soft_delete.assert_not_awaited()

    def test_delete_confirm_yes(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除（输出含标题）."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.get.return_value = _make_foreshadowing()
        mock_foreshadowing_service.soft_delete.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 伏笔已删除: [林晚的身世]" in result.output
        mock_foreshadowing_service.soft_delete.assert_awaited_once_with(
            foreshadowing_id=eid
        )

    def test_delete_confirm_no(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
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
        mock_foreshadowing_service.soft_delete.assert_not_awaited()

    def test_delete_json_no_force(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
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
        mock_foreshadowing_service.soft_delete.assert_not_awaited()

    def test_delete_not_found(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """伏笔不存在（get 返回 None）→ NOT_FOUND 错误信封."""
        mock_foreshadowing_service.get.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        mock_foreshadowing_service.soft_delete.assert_not_awaited()


class TestForeshadowingRestore:
    def test_restore_json(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """restore --json → 成功信封 + id 透传."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.restore.return_value = _make_foreshadowing()
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["title"] == "林晚的身世"
        mock_foreshadowing_service.restore.assert_awaited_once_with(
            foreshadowing_id=eid
        )

    def test_restore_not_found(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """伏笔不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_foreshadowing_service.restore.return_value = None
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestForeshadowingResolve:
    def test_resolve_json(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """resolve --json → 成功信封 + 完整对象（status=resolved）."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.resolve.return_value = _make_foreshadowing(
            status=ForeshadowingStatus.RESOLVED,
            resolved_at=datetime(2026, 8, 10, 3, 0, 0),
        )
        result = cli_runner.invoke(
            app,
            ["resolve", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["status"] == "resolved"
        assert data["data"]["resolved_at"] is not None
        mock_foreshadowing_service.resolve.assert_awaited_once_with(
            foreshadowing_id=eid
        )

    def test_resolve_human(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """resolve 人类模式 → ✅ 伏笔已回收."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.resolve.return_value = _make_foreshadowing(
            status=ForeshadowingStatus.RESOLVED
        )
        result = cli_runner.invoke(
            app,
            ["resolve", "--id", str(eid)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 伏笔已回收: [林晚的身世]" in result.output

    def test_resolve_not_found(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """伏笔不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_foreshadowing_service.resolve.return_value = None
        result = cli_runner.invoke(
            app,
            ["resolve", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestForeshadowingReopen:
    def test_reopen_json(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """reopen --json → 成功信封 + 完整对象（status=open, resolved_at=None）."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.reopen.return_value = _make_foreshadowing(
            status=ForeshadowingStatus.OPEN, resolved_at=None
        )
        result = cli_runner.invoke(
            app,
            ["reopen", "--id", str(eid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["status"] == "open"
        assert data["data"]["resolved_at"] is None
        mock_foreshadowing_service.reopen.assert_awaited_once_with(foreshadowing_id=eid)

    def test_reopen_human(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """reopen 人类模式 → ✅ 伏笔已重新开启."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.reopen.return_value = _make_foreshadowing()
        result = cli_runner.invoke(
            app,
            ["reopen", "--id", str(eid)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 伏笔已重新开启: [林晚的身世]" in result.output

    def test_reopen_not_found(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """伏笔不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_foreshadowing_service.reopen.return_value = None
        result = cli_runner.invoke(
            app,
            ["reopen", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestForeshadowingErrorMapping:
    """_run 异常映射补全：ServiceError / ValidationError / DB_ERROR."""

    def test_create_service_error(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """服务抛 ForeshadowingServiceError → VALIDATION_ERROR 信封 + 退出码 1."""
        mock_foreshadowing_service.create.side_effect = ForeshadowingServiceError(
            "同名伏笔已存在"
        )
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "同名伏笔已存在" in data["error"]["message"]

    def test_create_validation_error(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """pydantic ValidationError → VALIDATION_ERROR 信封."""
        mock_foreshadowing_service.create.side_effect = (
            ValidationError.from_exception_data(
                "ForeshadowingCreate",
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
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_create_db_error(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """服务抛未知异常 → DB_ERROR 信封 + 退出码 1."""
        mock_foreshadowing_service.create.side_effect = RuntimeError("boom")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "DB_ERROR"
        assert "boom" in data["error"]["message"]


class TestForeshadowingHumanOutput:
    """人类可读输出补全：已回收状态 / get 详情 / update / restore / delete 软删失败."""

    def test_create_human_resolved_status(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """create 人类模式返回已回收状态 → 状态标签为已回收."""
        mock_foreshadowing_service.create.return_value = _make_foreshadowing(
            status=ForeshadowingStatus.RESOLVED
        )
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--title", "林晚的身世"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已回收" in result.output

    def test_list_human_resolved_no_date(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """已回收且无回收日期 → 列表项显示（已回收）."""
        mock_foreshadowing_service.list.return_value = (
            [
                _make_foreshadowing(
                    status=ForeshadowingStatus.RESOLVED, resolved_at=None
                )
            ],
            1,
        )
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已回收伏笔 1 条" in result.output
        assert "[林晚的身世] (已回收)" in result.output

    def test_get_human(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """get 人类模式 → 全字段详情输出（含未挂接/未回收回退）."""
        mock_foreshadowing_service.get.return_value = _make_foreshadowing()
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        for token in (
            "标题:",
            "林晚的身世",
            "优先级:",
            "状态:",
            "未回收",
            "埋设位置:",
            "事件锚点:",
            "（未挂接）",
            "回收时间:",
            "（未回收）",
        ):
            assert token in result.output

    def test_update_priority_location(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """update --priority/--location → 字段进入 ForeshadowingUpdate."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.update.return_value = _make_foreshadowing()
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                str(eid),
                "--priority",
                "90",
                "--location",
                "第 8 章",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_foreshadowing_service.update.await_args
        upd: ForeshadowingUpdate = call.kwargs["data"]
        assert upd.priority == 90
        assert upd.location == "第 8 章"
        assert "title" not in upd.model_fields_set

    def test_update_human(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """update 人类模式 → 成功提示."""
        mock_foreshadowing_service.update.return_value = _make_foreshadowing(
            title="林晚的身世·改"
        )
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--title", "林晚的身世·改"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "伏笔已更新: [林晚的身世·改]" in result.output

    def test_restore_human(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """restore 人类模式 → 成功提示."""
        mock_foreshadowing_service.restore.return_value = _make_foreshadowing()
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "伏笔已恢复: [林晚的身世]" in result.output

    def test_delete_soft_delete_false(
        self, cli_runner, mock_foreshadowing_service, mock_create_tables
    ):
        """delete 服务层 soft_delete 返回 False → NOT_FOUND 错误信封."""
        eid = uuid.uuid4()
        mock_foreshadowing_service.get.return_value = _make_foreshadowing()
        mock_foreshadowing_service.soft_delete.return_value = False
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(eid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
