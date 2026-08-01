"""Outline CLI 命令测试 — Mock OutlineService 隔离数据库（spec §4 CLI 测试）.

覆盖（依据 specs/f11-outline-service/spec.md §4/§7）:
- outline 组成功路径（create/list/get/update/delete/restore）
- point 子组（list/create/update/delete，含 --position/--arc-id）
- arc 子组（list/create/update/delete）
- generate（--save/--no-save、--prompt/--prompt-file）
- 信封格式与退出码 0/1/2
- delete 二次确认 + --force；--json + delete 无 --force → VALIDATION_ERROR
- --prompt 与 --prompt-file 互斥 → 退出码 2
- generate 人类可读摘要与 --json 完整结果
- NOT_FOUND、LLM_ERROR 错误信封
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.outline import app
from inkflow.cli.context import CliContext
from inkflow.domain.models.outline import (
    GeneratedArc,
    GeneratedOutline,
    GeneratedPlotPoint,
    Outline,
    OutlineGenerateRequest,
    OutlineGenerationResult,
    PlotPoint,
    StoryArc,
)
from inkflow.domain.ports.outline_errors import (
    ArcNameConflictError,
    OutlineGenerationError,
    OutlineNameConflictError,
    OutlineNotFoundError,
    ProjectNotFoundError,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
AID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000003")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def mock_outline_service():
    """Mock OutlineService，绕过数据库（ADR-015 依赖注入）."""
    with patch(
        "inkflow.cli.commands.outline.OutlineService", autospec=True
    ) as mock_cls:
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_create_tables():
    """Mock create_tables 避免数据库初始化."""
    with patch("inkflow.cli.commands.outline.create_tables", AsyncMock()):
        yield


def _make_outline(**overrides) -> Outline:
    """构造测试用 Outline 领域对象."""
    defaults = dict(
        id=uuid.uuid4(),
        project_id=PID,
        name="第一卷大纲",
        description="故事主线概述",
        sort_order=0,
        extra={},
        is_deleted=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return Outline(**defaults)


def _make_point(**overrides) -> PlotPoint:
    """构造测试用 PlotPoint 领域对象."""
    defaults = dict(
        id=uuid.uuid4(),
        outline_id=OID,
        project_id=PID,
        name="主角登场",
        type="开篇",
        description="主角在宗门大比中亮相。",
        position=1,
        arc_id=None,
        extra={},
        is_deleted=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return PlotPoint(**defaults)


def _make_arc(**overrides) -> StoryArc:
    """构造测试用 StoryArc 领域对象."""
    defaults = dict(
        id=uuid.uuid4(),
        project_id=PID,
        name="主角成长线",
        description="主角从废柴到巅峰的成长轨迹。",
        is_deleted=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return StoryArc(**defaults)


def _make_generation_result(**overrides) -> OutlineGenerationResult:
    """构造测试用 OutlineGenerationResult 领域对象."""
    defaults = dict(
        saved=True,
        outline=_make_outline(name="第一卷大纲"),
        plot_points=[_make_point(name="主角登场", type="开篇")],
        arcs=[_make_arc(name="主角成长线")],
        preview=None,
        warnings=[],
        model="deepseek/deepseek-chat",
    )
    defaults.update(overrides)
    return OutlineGenerationResult(**defaults)


class TestOutlineCreate:
    def test_create_json_envelope(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """create --json → 成功信封 + 参数透传（UUID 转换）."""
        mock_outline_service.create_outline.return_value = _make_outline(
            name="第一卷大纲"
        )
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "第一卷大纲",
                "--description",
                "故事主线概述",
                "--sort-order",
                "2",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "第一卷大纲"
        mock_outline_service.create_outline.assert_awaited_once_with(
            project_id=PID,
            name="第一卷大纲",
            description="故事主线概述",
            sort_order=2,
        )

    def test_create_human(self, cli_runner, mock_outline_service, mock_create_tables):
        """create 人类模式 → 成功提示（含大纲名）."""
        mock_outline_service.create_outline.return_value = _make_outline(
            name="第一卷大纲"
        )
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "第一卷大纲"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "大纲创建成功" in result.output
        assert "第一卷大纲" in result.output

    def test_create_name_conflict(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """同名大纲 → VALIDATION_ERROR 信封 + 退出码 1."""
        mock_outline_service.create_outline.side_effect = OutlineNameConflictError()
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "第一卷大纲"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"


class TestOutlineList:
    def test_list_json(self, cli_runner, mock_outline_service, mock_create_tables):
        """list --json → 成功信封 + 大纲数组."""
        mock_outline_service.list_outlines.return_value = ([_make_outline()], 1)
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert isinstance(data["data"], list)
        assert data["data"][0]["name"] == "第一卷大纲"

    def test_list_params_passthrough(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """list 搜索/排序/分页参数透传."""
        mock_outline_service.list_outlines.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            [
                "list",
                "--project-id",
                str(PID),
                "--search",
                "第一卷",
                "--sort",
                "name",
                "--no-sort-desc",
                "--offset",
                "10",
                "--limit",
                "5",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        mock_outline_service.list_outlines.assert_awaited_once_with(
            project_id=PID,
            search="第一卷",
            sort_by="name",
            sort_desc=False,
            offset=10,
            limit=5,
        )

    def test_list_human_empty(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """空列表人类模式 → 暂无大纲."""
        mock_outline_service.list_outlines.return_value = ([], 0)
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无大纲" in result.output


class TestOutlineGet:
    def test_get_json(self, cli_runner, mock_outline_service, mock_create_tables):
        """大纲存在 → 成功信封."""
        sid = uuid.uuid4()
        mock_outline_service.get_outline.return_value = _make_outline(name="第一卷大纲")
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(sid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "第一卷大纲"
        mock_outline_service.get_outline.assert_awaited_once_with(outline_id=sid)

    def test_get_not_found_json(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """大纲不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_outline_service.get_outline.return_value = None
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert "大纲不存在" in data["error"]["message"]

    def test_get_invalid_uuid(
        self, cli_runner, mock_outline_service, mock_create_tables
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


class TestOutlineUpdate:
    def test_update_json(self, cli_runner, mock_outline_service, mock_create_tables):
        """update --json → 成功信封 + OutlineUpdate 透传（仅传入字段）."""
        sid = uuid.uuid4()
        mock_outline_service.update_outline.return_value = _make_outline(
            name="第一卷大纲·改"
        )
        result = cli_runner.invoke(
            app,
            [
                "update",
                "--id",
                str(sid),
                "--name",
                "第一卷大纲·改",
                "--sort-order",
                "3",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "第一卷大纲·改"
        call = mock_outline_service.update_outline.await_args
        assert call.kwargs["outline_id"] == sid
        upd = call.kwargs["update"]
        assert upd.name == "第一卷大纲·改"
        assert upd.sort_order == 3
        assert "description" not in upd.model_fields_set

    def test_update_not_found(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """大纲不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_outline_service.update_outline.return_value = None
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(uuid.uuid4()), "--name", "新大纲名"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestOutlineDelete:
    def test_delete_force_json(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """delete --force --json → 成功信封 + 软删除（force=False）."""
        sid = uuid.uuid4()
        mock_outline_service.delete_outline.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        mock_outline_service.delete_outline.assert_awaited_once_with(
            outline_id=sid, force=False
        )

    def test_delete_permanent_passes_force(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """delete --permanent → 服务层 force=True（物理删除）."""
        sid = uuid.uuid4()
        mock_outline_service.delete_outline.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid), "--force", "--permanent"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        mock_outline_service.delete_outline.assert_awaited_once_with(
            outline_id=sid, force=True
        )

    def test_delete_confirm_yes(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除."""
        sid = uuid.uuid4()
        mock_outline_service.delete_outline.return_value = True
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output
        mock_outline_service.delete_outline.assert_awaited_once_with(
            outline_id=sid, force=False
        )

    def test_delete_confirm_no(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """无 --force 人类模式 → 回答 n 取消，不调用服务."""
        sid = uuid.uuid4()
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid)],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "取消" in result.output
        mock_outline_service.delete_outline.assert_not_awaited()

    def test_delete_json_no_force(
        self, cli_runner, mock_outline_service, mock_create_tables
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
        mock_outline_service.delete_outline.assert_not_awaited()

    def test_delete_not_found(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """大纲不存在（服务返回 False）→ NOT_FOUND 错误信封."""
        mock_outline_service.delete_outline.return_value = False
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestOutlineRestore:
    def test_restore_json(self, cli_runner, mock_outline_service, mock_create_tables):
        """restore --json → 成功信封."""
        mock_outline_service.restore_outline.return_value = _make_outline(
            name="第一卷大纲"
        )
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "第一卷大纲"

    def test_restore_not_found(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """大纲不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_outline_service.restore_outline.return_value = None
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestPointList:
    def test_point_list_json(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """point list --json → 情节点数组信封."""
        mock_outline_service.list_points.return_value = [_make_point(name="主角登场")]
        result = cli_runner.invoke(
            app,
            ["point", "list", "--outline-id", str(OID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"][0]["name"] == "主角登场"
        mock_outline_service.list_points.assert_awaited_once_with(outline_id=OID)


class TestPointCreate:
    def test_point_create_json(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """point create --json → 成功信封 + --position/--arc-id 透传."""
        mock_outline_service.create_point.return_value = _make_point(
            name="主角登场", type="开篇", position=3, arc_id=AID
        )
        result = cli_runner.invoke(
            app,
            [
                "point",
                "create",
                "--outline-id",
                str(OID),
                "--name",
                "主角登场",
                "--type",
                "开篇",
                "--description",
                "主角亮相。",
                "--position",
                "3",
                "--arc-id",
                str(AID),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["position"] == 3
        mock_outline_service.create_point.assert_awaited_once_with(
            outline_id=OID,
            name="主角登场",
            type="开篇",
            description="主角亮相。",
            position=3,
            arc_id=AID,
        )

    def test_point_create_human(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """point create 人类模式 → 成功提示（含名称与类型）."""
        mock_outline_service.create_point.return_value = _make_point(
            name="主角登场", type="开篇"
        )
        result = cli_runner.invoke(
            app,
            [
                "point",
                "create",
                "--outline-id",
                str(OID),
                "--name",
                "主角登场",
                "--type",
                "开篇",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "情节点创建成功" in result.output
        assert "主角登场" in result.output
        assert "开篇" in result.output

    def test_point_create_outline_not_found(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """大纲不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_outline_service.create_point.side_effect = OutlineNotFoundError()
        result = cli_runner.invoke(
            app,
            ["point", "create", "--outline-id", str(OID), "--name", "主角登场"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"


class TestPointUpdate:
    def test_point_update_json(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """point update --json → PlotPointUpdate 透传（仅传入字段）."""
        pid = uuid.uuid4()
        mock_outline_service.update_point.return_value = _make_point(name="主角登场·改")
        result = cli_runner.invoke(
            app,
            [
                "point",
                "update",
                "--id",
                str(pid),
                "--name",
                "主角登场·改",
                "--type",
                "转折",
                "--position",
                "4",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "主角登场·改"
        call = mock_outline_service.update_point.await_args
        assert call.kwargs["point_id"] == pid
        upd = call.kwargs["update"]
        assert upd.name == "主角登场·改"
        assert upd.type == "转折"
        assert upd.position == 4
        assert "description" not in upd.model_fields_set

    def test_point_update_clear_arc_id(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """point update --arc-id \"\" → 清除弧线归属（arc_id=\"\" 进入 update）."""
        pid = uuid.uuid4()
        mock_outline_service.update_point.return_value = _make_point(arc_id=None)
        result = cli_runner.invoke(
            app,
            ["point", "update", "--id", str(pid), "--arc-id", ""],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_outline_service.update_point.await_args
        upd = call.kwargs["update"]
        assert "arc_id" in upd.model_fields_set
        assert upd.arc_id == ""

    def test_point_update_set_arc_id(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """point update --arc-id <uuid> → arc_id 为 UUID 进入 update."""
        pid = uuid.uuid4()
        mock_outline_service.update_point.return_value = _make_point(arc_id=AID)
        result = cli_runner.invoke(
            app,
            ["point", "update", "--id", str(pid), "--arc-id", str(AID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_outline_service.update_point.await_args
        upd = call.kwargs["update"]
        assert upd.arc_id == AID


class TestPointDelete:
    def test_point_delete_force_json(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """point delete --force --json → 成功信封 + 软删除."""
        pid = uuid.uuid4()
        mock_outline_service.delete_point.return_value = True
        result = cli_runner.invoke(
            app,
            ["point", "delete", "--id", str(pid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        mock_outline_service.delete_point.assert_awaited_once_with(
            point_id=pid, force=False
        )

    def test_point_delete_json_no_force(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """point delete --json 且无 --force → VALIDATION_ERROR."""
        result = cli_runner.invoke(
            app,
            ["point", "delete", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        mock_outline_service.delete_point.assert_not_awaited()


class TestArcList:
    def test_arc_list_json(self, cli_runner, mock_outline_service, mock_create_tables):
        """arc list --json → 弧线数组信封."""
        mock_outline_service.list_arcs.return_value = [_make_arc(name="主角成长线")]
        result = cli_runner.invoke(
            app,
            ["arc", "list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"][0]["name"] == "主角成长线"
        mock_outline_service.list_arcs.assert_awaited_once_with(project_id=PID)


class TestArcCreate:
    def test_arc_create_json(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """arc create --json → 成功信封 + 参数透传."""
        mock_outline_service.create_arc.return_value = _make_arc(name="主角成长线")
        result = cli_runner.invoke(
            app,
            [
                "arc",
                "create",
                "--project-id",
                str(PID),
                "--name",
                "主角成长线",
                "--description",
                "成长轨迹。",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "主角成长线"
        mock_outline_service.create_arc.assert_awaited_once_with(
            project_id=PID, name="主角成长线", description="成长轨迹。"
        )

    def test_arc_create_name_conflict(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """同名弧线 → VALIDATION_ERROR 信封 + 退出码 1."""
        mock_outline_service.create_arc.side_effect = ArcNameConflictError()
        result = cli_runner.invoke(
            app,
            ["arc", "create", "--project-id", str(PID), "--name", "主角成长线"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"


class TestArcUpdate:
    def test_arc_update_json(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """arc update --json → StoryArcUpdate 透传."""
        aid = uuid.uuid4()
        mock_outline_service.update_arc.return_value = _make_arc(name="主角成长线·改")
        result = cli_runner.invoke(
            app,
            ["arc", "update", "--id", str(aid), "--name", "主角成长线·改"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "主角成长线·改"
        call = mock_outline_service.update_arc.await_args
        assert call.kwargs["arc_id"] == aid
        upd = call.kwargs["update"]
        assert upd.name == "主角成长线·改"
        assert "description" not in upd.model_fields_set


class TestArcDelete:
    def test_arc_delete_force_json(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """arc delete --force --json → 成功信封 + 软删除."""
        aid = uuid.uuid4()
        mock_outline_service.delete_arc.return_value = True
        result = cli_runner.invoke(
            app,
            ["arc", "delete", "--id", str(aid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        mock_outline_service.delete_arc.assert_awaited_once_with(
            arc_id=aid, force=False
        )

    def test_arc_delete_json_no_force(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """arc delete --json 且无 --force → VALIDATION_ERROR."""
        result = cli_runner.invoke(
            app,
            ["arc", "delete", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        mock_outline_service.delete_arc.assert_not_awaited()


class TestGenerate:
    def test_generate_save_json(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """generate --json → 完整结果信封 + OutlineGenerateRequest 透传."""
        mock_outline_service.generate.return_value = _make_generation_result(
            plot_points=[
                _make_point(name="主角登场", type="开篇"),
                _make_point(name="转折", type="转折"),
            ],
            arcs=[_make_arc(name="主角成长线"), _make_arc(name="反派阴谋线")],
        )
        result = cli_runner.invoke(
            app,
            [
                "generate",
                "--project-id",
                str(PID),
                "--name",
                "第一卷大纲",
                "--prompt",
                "爽文, 废柴逆袭",
                "--num-chapters",
                "12",
                "--model",
                "deepseek/deepseek-chat",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["saved"] is True
        assert data["data"]["outline"]["name"] == "第一卷大纲"
        assert len(data["data"]["plot_points"]) == 2
        assert data["data"]["plot_points"][0]["name"] == "主角登场"
        assert data["data"]["arcs"][1]["name"] == "反派阴谋线"
        assert data["data"]["model"] == "deepseek/deepseek-chat"
        call = mock_outline_service.generate.await_args
        req: OutlineGenerateRequest = call.args[0]
        assert req.project_id == PID
        assert req.name == "第一卷大纲"
        assert req.prompt == "爽文, 废柴逆袭"
        assert req.num_chapters == 12
        assert req.save is True
        assert req.model == "deepseek/deepseek-chat"

    def test_generate_no_save_json(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """generate --no-save --json → 预览结果信封（saved=False + preview）."""
        mock_outline_service.generate.return_value = _make_generation_result(
            saved=False,
            outline=None,
            plot_points=[],
            arcs=[],
            preview=GeneratedOutline(
                name="第一卷大纲",
                description="",
                arcs=[GeneratedArc(name="主角成长线", description="")],
                plot_points=[
                    GeneratedPlotPoint(
                        name="主角登场", type="开篇", description="", arc="主角成长线"
                    )
                ],
            ),
        )
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--no-save", "--prompt", "爽文"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["saved"] is False
        assert data["data"]["outline"] is None
        assert data["data"]["preview"]["plot_points"][0]["name"] == "主角登场"
        call = mock_outline_service.generate.await_args
        req: OutlineGenerateRequest = call.args[0]
        assert req.save is False

    def test_generate_human_summary_saved(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """generate 人类模式（保存）→ 可读摘要（含情节点/弧线计数与警告）."""
        mock_outline_service.generate.return_value = _make_generation_result(
            plot_points=[
                _make_point(name="主角登场"),
                _make_point(name="转折"),
                _make_point(name="高潮"),
            ],
            arcs=[_make_arc(name="主角成长线"), _make_arc(name="反派阴谋线")],
            warnings=['情节点 "？？" 名称为空已跳过'],
        )
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt", "爽文"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "大纲生成并保存" in result.output
        assert "第一卷大纲" in result.output
        assert "3 个情节点、2 条弧线" in result.output
        assert "生成完成但有警告" in result.output

    def test_generate_human_summary_preview(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """generate 人类模式（--no-save）→ 预览摘要提示."""
        mock_outline_service.generate.return_value = _make_generation_result(
            saved=False,
            outline=None,
            plot_points=[],
            arcs=[],
            preview=GeneratedOutline(
                name="第一卷大纲",
                description="",
                arcs=[GeneratedArc(name="主角成长线", description="")],
                plot_points=[
                    GeneratedPlotPoint(
                        name="主角登场", type="开篇", description="", arc="主角成长线"
                    )
                ],
            ),
        )
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--no-save", "--prompt", "爽文"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "大纲预览（未保存）" in result.output
        assert "1 个情节点、1 条弧线" in result.output
        assert "使用 --save 保存后落库" in result.output

    def test_generate_prompt_file(
        self, cli_runner, mock_outline_service, mock_create_tables, tmp_path
    ):
        """generate --prompt-file → 读取文件内容作为生成提示."""
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("废柴逆袭，宗门大比。", encoding="utf-8")
        mock_outline_service.generate.return_value = _make_generation_result()
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt-file", str(prompt_file)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        call = mock_outline_service.generate.await_args
        req: OutlineGenerateRequest = call.args[0]
        assert req.prompt == "废柴逆袭，宗门大比。"

    def test_generate_prompt_and_prompt_file_exclusive(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """--prompt 与 --prompt-file 同时传入 → 用法错误退出码 2."""
        result = cli_runner.invoke(
            app,
            [
                "generate",
                "--project-id",
                str(PID),
                "--prompt",
                "爽文",
                "--prompt-file",
                "p.txt",
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 2
        mock_outline_service.generate.assert_not_awaited()

    def test_generate_llm_error(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """LLM 输出无法解析 → LLM_ERROR 错误信封 + 退出码 1."""
        mock_outline_service.generate.side_effect = OutlineGenerationError(
            detail="非法 JSON"
        )
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt", "爽文"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "LLM_ERROR"

    def test_generate_project_not_found(
        self, cli_runner, mock_outline_service, mock_create_tables
    ):
        """项目不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        mock_outline_service.generate.side_effect = ProjectNotFoundError()
        result = cli_runner.invoke(
            app,
            ["generate", "--project-id", str(PID), "--prompt", "爽文"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
