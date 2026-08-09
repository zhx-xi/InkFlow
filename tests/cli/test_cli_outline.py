"""Outline CLI 命令测试（outline/point/arc CRUD）— Mock ensure_kernel + InkFlowHTTPClient。

覆盖（依据 specs/f11-outline-service/spec.md §4/§7）:
- outline 组成功路径（create/list/get/update/delete/restore）
- point 子组（list/create/update/delete，含 --position/--arc-id）
- arc 子组（list/create/update/delete）
- 信封格式与退出码 0/1/2
- delete 二次确认 + --force；--json + delete 无 --force → VALIDATION_ERROR
- NOT_FOUND、VALIDATION_ERROR 错误信封

F38 改造（#169）：mock 目标从 domain Service（OutlineService + create_tables）
迁移到 ensure_kernel + InkFlowHTTPClient；返回值从领域对象改为 JSON dict
（model_dump(mode="json") 等价物）；create_tables/session 相关 patch 已移除；
错误路径抛 HttpApiError（lazy import，RED 阶段模块未实现）。
list 端点返回 {"items", "total"}，命令层提取 items 后保持原信封（list 输出）。
HTTP 错误码映射（命令侧，输出不变）：404→NOT_FOUND、422→VALIDATION_ERROR。

── 拆分说明 ────────────────────────────────────────────────────
原 test_cli_outline.py 1408 行超 CI check_file_length（< 900）护栏：
generate/错误映射/人类输出用例拆至 test_cli_outline_http.py（复制所需
imports 与 helpers），本文件保留 outline/point/arc CRUD 用例。

── RED 形态说明 ────────────────────────────────────────────────
命令模块仍直连 domain Service（未改造），patch 目标
inkflow.cli.commands.outline.ensure_kernel / .InkFlowHTTPClient 不存在
→ 全部用例 fixture setup AttributeError（同根因，预期 RED）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.outline import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
OID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
AID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000003")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP。

    fake client 提供 post/get/patch/delete 返回预设 JSON（dict）；
    错误路径抛 HttpApiError。patch 目标 = 命令模块命名空间（GREEN 后
    命令模块 from-import 绑定自身命名空间，F19 #77 先例）。
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
            "inkflow.cli.commands.outline.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.outline.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_error(status_code: int, detail: str, code: str | None = None):
    """构造 HttpApiError（lazy import：RED 阶段 inkflow.infrastructure.http
    未实现，仅在用例体调用时执行，不影响 RED 形态）。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _make_outline(**overrides) -> dict:
    """构造测试用 Outline JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="第一卷大纲",
        description="故事主线概述",
        sort_order=0,
        extra={},
        is_deleted=False,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_point(**overrides) -> dict:
    """构造测试用 PlotPoint JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        outline_id=str(OID),
        project_id=str(PID),
        name="主角登场",
        type="开篇",
        description="主角在宗门大比中亮相。",
        position=1,
        arc_id=None,
        extra={},
        is_deleted=False,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_arc(**overrides) -> dict:
    """构造测试用 StoryArc JSON dict（model_dump(mode="json") 等价物）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="主角成长线",
        description="主角从废柴到巅峰的成长轨迹。",
        is_deleted=False,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


class TestOutlineCreate:
    def test_create_json_envelope(self, cli_runner, fake_http_client):
        """create --json → 成功信封 + HTTP 调用（UUID 转换在命令侧）."""
        fake_http_client.post.return_value = _make_outline(name="第一卷大纲")
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
        fake_http_client.post.assert_awaited()

    def test_create_human(self, cli_runner, fake_http_client):
        """create 人类模式 → 成功提示（含大纲名）."""
        fake_http_client.post.return_value = _make_outline(name="第一卷大纲")
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "第一卷大纲"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "大纲创建成功" in result.output
        assert "第一卷大纲" in result.output

    def test_create_name_conflict(self, cli_runner, fake_http_client):
        """同名大纲 → VALIDATION_ERROR 信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(422, "同名大纲")
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
    def test_list_json(self, cli_runner, fake_http_client):
        """list --json → 成功信封 + 大纲数组."""
        fake_http_client.get.return_value = {
            "items": [_make_outline()],
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
        assert data["data"][0]["name"] == "第一卷大纲"

    def test_list_params_passthrough(self, cli_runner, fake_http_client):
        """list 搜索/排序/分页参数 → HTTP 调用发生（参数透传在命令侧）."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
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
        fake_http_client.get.assert_awaited()

    def test_list_human_empty(self, cli_runner, fake_http_client):
        """空列表人类模式 → 暂无大纲."""
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            app,
            ["list", "--project-id", str(PID)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "暂无大纲" in result.output


class TestOutlineGet:
    def test_get_json(self, cli_runner, fake_http_client):
        """大纲存在 → 成功信封."""
        sid = uuid.uuid4()
        fake_http_client.get.return_value = _make_outline(name="第一卷大纲")
        result = cli_runner.invoke(
            app,
            ["get", "--id", str(sid)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "第一卷大纲"
        fake_http_client.get.assert_awaited()

    def test_get_not_found_json(self, cli_runner, fake_http_client):
        """大纲不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.get.side_effect = _http_error(404, "大纲不存在")
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


class TestOutlineUpdate:
    def test_update_json(self, cli_runner, fake_http_client):
        """update --json → 成功信封（仅传入字段进入 update，命令侧）."""
        sid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_outline(name="第一卷大纲·改")
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
        fake_http_client.patch.assert_awaited()

    def test_update_not_found(self, cli_runner, fake_http_client):
        """大纲不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.patch.side_effect = _http_error(404, "大纲不存在")
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
    def test_delete_force_json(self, cli_runner, fake_http_client):
        """delete --force --json → 成功信封 + 软删除（force=False）."""
        sid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        fake_http_client.delete.assert_awaited()

    def test_delete_permanent_passes_force(self, cli_runner, fake_http_client):
        """delete --permanent → HTTP 调用发生（force=True 透传在命令侧）."""
        sid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid), "--force", "--permanent"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.delete.assert_awaited()

    def test_delete_confirm_yes(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除."""
        sid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid)],
            input="y\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output
        fake_http_client.delete.assert_awaited()

    def test_delete_confirm_no(self, cli_runner, fake_http_client):
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
        """大纲不存在（HTTP 404）→ NOT_FOUND 错误信封."""
        fake_http_client.delete.side_effect = _http_error(404, "大纲不存在")
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
    def test_restore_json(self, cli_runner, fake_http_client):
        """restore --json → 成功信封."""
        fake_http_client.post.return_value = _make_outline(name="第一卷大纲")
        result = cli_runner.invoke(
            app,
            ["restore", "--id", str(uuid.uuid4())],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "第一卷大纲"

    def test_restore_not_found(self, cli_runner, fake_http_client):
        """大纲不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(404, "大纲不存在")
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
    def test_point_list_json(self, cli_runner, fake_http_client):
        """point list --json → 情节点数组信封."""
        fake_http_client.get.return_value = {
            "items": [_make_point(name="主角登场")],
            "total": 1,
        }
        result = cli_runner.invoke(
            app,
            ["point", "list", "--outline-id", str(OID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"][0]["name"] == "主角登场"
        fake_http_client.get.assert_awaited()


class TestPointCreate:
    def test_point_create_json(self, cli_runner, fake_http_client):
        """point create --json → 成功信封 + HTTP 调用（--position/--arc-id 命令侧）."""
        fake_http_client.post.return_value = _make_point(
            name="主角登场", type="开篇", position=3, arc_id=str(AID)
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
        fake_http_client.post.assert_awaited()

    def test_point_create_human(self, cli_runner, fake_http_client):
        """point create 人类模式 → 成功提示（含名称与类型）."""
        fake_http_client.post.return_value = _make_point(name="主角登场", type="开篇")
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

    def test_point_create_outline_not_found(self, cli_runner, fake_http_client):
        """大纲不存在 → NOT_FOUND 错误信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(404, "大纲不存在")
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
    def test_point_update_json(self, cli_runner, fake_http_client):
        """point update --json → 成功信封（仅传入字段进入 update，命令侧）."""
        pid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_point(name="主角登场·改")
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
        fake_http_client.patch.assert_awaited()

    def test_point_update_clear_arc_id(self, cli_runner, fake_http_client):
        """point update --arc-id \"\" → 清除弧线归属（HTTP 调用发生）."""
        pid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_point(arc_id=None)
        result = cli_runner.invoke(
            app,
            ["point", "update", "--id", str(pid), "--arc-id", ""],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.patch.assert_awaited()

    def test_point_update_set_arc_id(self, cli_runner, fake_http_client):
        """point update --arc-id <uuid> → HTTP 调用发生（UUID 转换在命令侧）."""
        pid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_point(arc_id=str(AID))
        result = cli_runner.invoke(
            app,
            ["point", "update", "--id", str(pid), "--arc-id", str(AID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.patch.assert_awaited()


class TestPointDelete:
    def test_point_delete_force_json(self, cli_runner, fake_http_client):
        """point delete --force --json → 成功信封 + 软删除."""
        pid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["point", "delete", "--id", str(pid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        fake_http_client.delete.assert_awaited()

    def test_point_delete_json_no_force(self, cli_runner, fake_http_client):
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
        fake_http_client.delete.assert_not_awaited()


class TestArcList:
    def test_arc_list_json(self, cli_runner, fake_http_client):
        """arc list --json → 弧线数组信封."""
        fake_http_client.get.return_value = {
            "items": [_make_arc(name="主角成长线")],
            "total": 1,
        }
        result = cli_runner.invoke(
            app,
            ["arc", "list", "--project-id", str(PID)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"][0]["name"] == "主角成长线"
        fake_http_client.get.assert_awaited()


class TestArcCreate:
    def test_arc_create_json(self, cli_runner, fake_http_client):
        """arc create --json → 成功信封 + HTTP 调用."""
        fake_http_client.post.return_value = _make_arc(name="主角成长线")
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
        fake_http_client.post.assert_awaited()

    def test_arc_create_name_conflict(self, cli_runner, fake_http_client):
        """同名弧线 → VALIDATION_ERROR 信封 + 退出码 1."""
        fake_http_client.post.side_effect = _http_error(422, "同名弧线")
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
    def test_arc_update_json(self, cli_runner, fake_http_client):
        """arc update --json → 成功信封（仅传入字段进入 update，命令侧）."""
        aid = uuid.uuid4()
        fake_http_client.patch.return_value = _make_arc(name="主角成长线·改")
        result = cli_runner.invoke(
            app,
            ["arc", "update", "--id", str(aid), "--name", "主角成长线·改"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["name"] == "主角成长线·改"
        fake_http_client.patch.assert_awaited()


class TestArcDelete:
    def test_arc_delete_force_json(self, cli_runner, fake_http_client):
        """arc delete --force --json → 成功信封 + 软删除."""
        aid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["arc", "delete", "--id", str(aid), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        fake_http_client.delete.assert_awaited()

    def test_arc_delete_json_no_force(self, cli_runner, fake_http_client):
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
        fake_http_client.delete.assert_not_awaited()
