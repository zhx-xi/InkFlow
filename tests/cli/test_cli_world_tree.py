"""F35 世界观地点层级 CLI 测试 — ancestors/descendants 命令 + --parent / delete 参数（追加段）。

拆分原因: test_cli_world.py 已有 779 行，追加 F35 用例将超 900 行护栏（F24 教训），
故新用例独立成文件。fixtures/helpers 复制自 test_cli_world.py（cli_runner /
fake_http_client / _http_error / _make_setting），保持同构。

覆盖（依据 specs/f35-world-tree/spec.md §4/§7）:
- world ancestors <id> / descendants <id>（新命令）→ GET /world-settings/{id}/ancestors|descendants
- create/update 新增 --parent <UUID>（契约定死: 无 --parent 时 body 不含 parent_id 键）
- delete 新增 --cascade / --reparent-to <UUID>（params 透传）
- F35 422 错误映射复用既有 map_http_error（有子地点 → VALIDATION_ERROR 信封）

── RED 形态说明 ────────────────────────────────────────────────
命令模块未实现 F35 命令/参数: ancestors/descendants → "No such command"（exit 2）；
--parent / --cascade / --reparent-to → "No such option"（exit 2）→ 用例断言
exit_code == 0 FAIL。守护用例（create 无 --parent body 无 parent_id 键 / 422 →
VALIDATION_ERROR）RED 阶段即 PASS（既有行为已满足）。
⚠️ 新文件不在 ci.yml integration-cli-backend job 文件列表——需父 agent 追加登记。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.world import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient，绕过真实内核与 HTTP（同 test_cli_world.py）."""
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
            "inkflow.cli.commands.world.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch(
            "inkflow.cli.commands.world.InkFlowHTTPClient", autospec=True
        ) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_error(status_code: int, detail: str, code: str | None = None):
    """构造 HttpApiError（同 test_cli_world.py）."""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _make_setting(**overrides) -> dict:
    """构造测试用 WorldSetting JSON dict（同 test_cli_world.py）."""
    defaults = dict(
        id=str(uuid.uuid4()),
        project_id=str(PID),
        name="灵气复苏",
        category="设定",
        content="天地灵气重新复苏，修炼体系重现。",
        extra={},
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return defaults


class TestWorldTreeQuery:
    """F35 地点树只读命令（ancestors/descendants，spec §4）."""

    def test_ancestors_json(self, cli_runner, fake_http_client):
        """ancestors <id> --json → 成功信封 + GET /world-settings/{id}/ancestors.

        RED 预期: 命令未注册 → "No such command" → exit 2 → 断言失败。
        """
        sid = uuid.uuid4()
        fake_http_client.get.return_value = {
            "items": [_make_setting(name="清河县城")],
            "total": 1,
        }
        result = cli_runner.invoke(
            app, ["ancestors", str(sid)], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["items"][0]["name"] == "清河县城"
        fake_http_client.get.assert_awaited()
        assert (
            fake_http_client.get.await_args.args[0]
            == f"/world-settings/{sid}/ancestors"
        )

    def test_descendants_json(self, cli_runner, fake_http_client):
        """descendants <id> --json → 成功信封 + GET /world-settings/{id}/descendants.

        RED 预期: 命令未注册 → "No such command" → exit 2 → 断言失败。
        """
        sid = uuid.uuid4()
        fake_http_client.get.return_value = {
            "items": [_make_setting(name="清河县城")],
            "total": 1,
        }
        result = cli_runner.invoke(
            app, ["descendants", str(sid)], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["items"][0]["name"] == "清河县城"
        fake_http_client.get.assert_awaited()
        assert (
            fake_http_client.get.await_args.args[0]
            == f"/world-settings/{sid}/descendants"
        )


class TestWorldTreeParentOption:
    """F35 create/update --parent 参数（缺省 = 顶层）."""

    def test_create_with_parent(self, cli_runner, fake_http_client):
        """create --parent <uuid> → POST body 含 parent_id 字段.

        RED 预期: --parent 选项未注册 → "No such option" → exit 2 → 断言失败。
        """
        parent = uuid.uuid4()
        fake_http_client.post.return_value = _make_setting(name="清河县城")
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "清河县城",
                "--parent",
                str(parent),
            ],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        fake_http_client.post.assert_awaited()
        _, kwargs = fake_http_client.post.await_args
        assert kwargs["json"]["parent_id"] == str(parent)

    def test_create_without_parent_no_parent_key(self, cli_runner, fake_http_client):
        """守护: create 无 --parent → body 不含 parent_id 键（契约定死，缺省顶层）.

        RED 阶段即 PASS（既有实现已满足）——防 GREEN 实现画蛇添足。
        """
        fake_http_client.post.return_value = _make_setting()
        result = cli_runner.invoke(
            app,
            ["create", "--project-id", str(PID), "--name", "灵气复苏"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.post.assert_awaited()
        _, kwargs = fake_http_client.post.await_args
        assert "parent_id" not in kwargs["json"]

    def test_update_with_parent(self, cli_runner, fake_http_client):
        """update --parent <uuid> → PATCH body 含 parent_id 字段.

        RED 预期: --parent 选项未注册 → exit 2 → 断言失败。
        """
        sid = uuid.uuid4()
        parent = uuid.uuid4()
        fake_http_client.patch.return_value = _make_setting()
        result = cli_runner.invoke(
            app,
            ["update", "--id", str(sid), "--parent", str(parent)],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.patch.assert_awaited()
        _, kwargs = fake_http_client.patch.await_args
        assert kwargs["json"]["parent_id"] == str(parent)


class TestWorldTreeDeleteParams:
    """F35 delete --cascade / --reparent-to 参数（spec §5.5 D6）."""

    def test_delete_cascade(self, cli_runner, fake_http_client):
        """delete --cascade --force → DELETE params 含 cascade=true.

        RED 预期: --cascade 选项未注册 → exit 2 → 断言失败。
        """
        sid = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid), "--cascade", "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.delete.assert_awaited()
        _, kwargs = fake_http_client.delete.await_args
        assert kwargs["params"]["cascade"] == "true"

    def test_delete_reparent_to(self, cli_runner, fake_http_client):
        """delete --reparent-to <uuid> --force → DELETE params 含 reparent_to=str(uuid).

        RED 预期: --reparent-to 选项未注册 → exit 2 → 断言失败。
        """
        sid = uuid.uuid4()
        target = uuid.uuid4()
        fake_http_client.delete.return_value = None
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(sid), "--reparent-to", str(target), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        fake_http_client.delete.assert_awaited()
        _, kwargs = fake_http_client.delete.await_args
        assert kwargs["params"]["reparent_to"] == str(target)

    def test_delete_children_422_validation_error(self, cli_runner, fake_http_client):
        """守护: 有子地点 DELETE → HttpApiError(422) → VALIDATION_ERROR 信封（复用 map_http_error）.

        RED 阶段即 PASS（既有 422 映射已生效）——锁 F35 错误码映射契约。
        """
        fake_http_client.delete.side_effect = _http_error(
            422,
            "该地点存在子地点，必须指定 cascade=true（级联删除）或 "
            "reparent_to=<id>（子地点改挂新父）",
        )
        result = cli_runner.invoke(
            app,
            ["delete", "--id", str(uuid.uuid4()), "--force"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "该地点存在子地点" in data["error"]["message"]


class TestWorldTreeHumanOutput:
    """F35 人类可读输出分支补测（非 --json，world.py L255-258 / L285-291）.

    既有 F35 CLI 用例只测 --json 信封（print_result 信封分支），人类输出分支
    （面包屑 / 「暂无」提示 / depth 缩进列表）此前全 miss——#177 覆盖率补测。
    """

    def test_ancestors_human_breadcrumb(self, cli_runner, fake_http_client):
        """ancestors 非空 → stdout 面包屑「清河县城 → 青州 → 大越国」（L258 join 分支）."""
        sid = uuid.uuid4()
        fake_http_client.get.return_value = {
            "items": [
                _make_setting(name="清河县城"),
                _make_setting(name="青州"),
                _make_setting(name="大越国"),
            ],
            "total": 3,
        }
        result = cli_runner.invoke(
            app, ["ancestors", str(sid)], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "清河县城 → 青州 → 大越国" in result.stdout
        assert (
            fake_http_client.get.await_args.args[0]
            == f"/world-settings/{sid}/ancestors"
        )

    def test_ancestors_human_empty(self, cli_runner, fake_http_client):
        """ancestors 空列表 → stdout「📭 暂无祖先链」（L256，emoji 码点精确）."""
        sid = uuid.uuid4()
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            app, ["ancestors", str(sid)], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "\U0001f4ed 暂无祖先链" in result.stdout

    def test_descendants_human_indent(self, cli_runner, fake_http_client):
        """descendants 非空 → stdout 按 depth 缩进平铺「- 名称」（L288-291）."""
        sid = uuid.uuid4()
        fake_http_client.get.return_value = {
            "items": [
                _make_setting(name="大越国", depth=0),
                _make_setting(name="青州", depth=1),
                _make_setting(name="清河县城", depth=2),
            ],
            "total": 3,
        }
        result = cli_runner.invoke(
            app, ["descendants", str(sid)], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "- 大越国" in result.stdout
        assert "  - 青州" in result.stdout
        assert "    - 清河县城" in result.stdout
        assert (
            fake_http_client.get.await_args.args[0]
            == f"/world-settings/{sid}/descendants"
        )

    def test_descendants_human_empty(self, cli_runner, fake_http_client):
        """descendants 空列表 → stdout「📭 暂无子地点」（L286，emoji 码点精确）."""
        sid = uuid.uuid4()
        fake_http_client.get.return_value = {"items": [], "total": 0}
        result = cli_runner.invoke(
            app, ["descendants", str(sid)], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0
        assert "\U0001f4ed 暂无子地点" in result.stdout
