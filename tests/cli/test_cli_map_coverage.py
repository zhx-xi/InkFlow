"""F36 CLI 覆盖缺口闭合补测 — TestMapCoverageGaps（人类输出/错误信封/children 命令）.

拆分原因: test_cli_map.py 原 1020 行 > 900 行护栏（F24 教训）——TestMapCoverageGaps
独立成文件（2026-08-09 CI lint-backend check_file_length 失败后拆分）。
fixtures/helpers 复制自 test_cli_map.py（cli_runner/fake_http_client/PID/_make_map/_http_error），
保持同构。ci.yml integration-cli-backend 已登记本文件。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from inkflow.cli.commands.map import app
from inkflow.cli.context import CliContext

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）."""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（复制自 test_cli_map.py 同形态）.

    F38 陷阱: async with client 形态必须覆盖 __aenter__/__aexit__，
    否则 await 记录在 child mock 上，await_args 断言失败。裸
    AsyncMock → post_file/put_file/get_bytes 新方法自动生成。
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
            "inkflow.cli.commands.map.ensure_kernel",
            AsyncMock(return_value=fake_handle),
        ),
        patch("inkflow.cli.commands.map.InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_instance
        yield mock_instance


class TestMapCoverageGaps:
    """F36 CLI 覆盖率缺口闭合补测（2026-08-09 QA，人类输出分支/错误信封/children 命令）.

    追加原因: test_cli_map.py 既有 17 用例主测 --json 信封与退出码，人类可读输出
    分支与错误信封分支未被覆盖（coverage.xml 实测 cli/commands/map.py 80%）。
    """

    def test_create_human_output(self, cli_runner, fake_http_client, tmp_path):
        """create 非 --json → typer.echo 人类输出（✅ 前缀）."""
        img = tmp_path / "main.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        fake_http_client.post_file = AsyncMock(
            return_value={
                "id": "3f2e1d4a-0000-4000-8000-000000000009",
                "project_id": str(PID),
                "name": "清河县城图",
                "image_path": "maps/x/main.png",
                "description": "",
                "root_location_id": None,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        )
        result = cli_runner.invoke(
            app,
            [
                "create",
                "--project-id",
                str(PID),
                "--name",
                "清河县城图",
                "--image",
                str(img),
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 地图创建成功" in result.stdout

    def test_get_human_output_with_image_download(
        self, cli_runner, fake_http_client, tmp_path
    ):
        """get 非 --json → 人类输出；--image-output 下载图片."""
        fake_http_client.get = AsyncMock(
            return_value={
                "id": "3f2e1d4a-0000-4000-8000-000000000009",
                "project_id": str(PID),
                "name": "清河县城图",
                "image_path": "maps/x/main.png",
                "description": "",
                "root_location_id": None,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        )
        fake_http_client.get_bytes = AsyncMock(return_value=b"\x89PNG-data")
        out = tmp_path / "out.png"
        result = cli_runner.invoke(
            app,
            ["get", "3f2e1d4a-0000-4000-8000-000000000009", "--image-output", str(out)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 地图: [清河县城图]" in result.stdout
        assert out.read_bytes() == b"\x89PNG-data"

    def test_update_description_human_output(self, cli_runner, fake_http_client):
        """update --description → body 含 description + 人类输出."""
        fake_http_client.patch = AsyncMock(
            return_value={
                "id": "3f2e1d4a-0000-4000-8000-000000000009",
                "project_id": str(PID),
                "name": "清河县城图",
                "image_path": "maps/x/main.png",
                "description": "新描述",
                "root_location_id": None,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        )
        result = cli_runner.invoke(
            app,
            [
                "update",
                "3f2e1d4a-0000-4000-8000-000000000009",
                "--description",
                "新描述",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 地图已更新" in result.stdout
        body = fake_http_client.patch.await_args.kwargs["json"]
        assert body["description"] == "新描述"

    def test_image_human_output(self, cli_runner, fake_http_client, tmp_path):
        """image 换图 → put_file 被调 + 人类输出."""
        img = tmp_path / "main.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        fake_http_client.put_file = AsyncMock(
            return_value={
                "id": "3f2e1d4a-0000-4000-8000-000000000009",
                "project_id": str(PID),
                "name": "清河县城图",
                "image_path": "maps/x/main.png",
                "description": "",
                "root_location_id": None,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        )
        result = cli_runner.invoke(
            app,
            ["image", "3f2e1d4a-0000-4000-8000-000000000009", "--image", str(img)],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 图片已更换" in result.stdout
        fake_http_client.put_file.assert_awaited_once()

    def test_delete_interactive_cancel(self, cli_runner, fake_http_client):
        """delete 无 --force 交互确认取消 → 不调 DELETE."""
        result = cli_runner.invoke(
            app,
            ["delete", "3f2e1d4a-0000-4000-8000-000000000009"],
            input="n\n",
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "已取消" in result.stdout
        fake_http_client.delete.assert_not_awaited()

    def test_delete_human_output(self, cli_runner, fake_http_client):
        """delete --force 非 --json → 人类输出."""
        fake_http_client.delete = AsyncMock(return_value={})
        result = cli_runner.invoke(
            app,
            ["delete", "3f2e1d4a-0000-4000-8000-000000000009", "--force"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ 地图已删除" in result.stdout

    def test_children_success_json(self, cli_runner, fake_http_client):
        """children 成功 → 信封 data 含 items/total（children 命令补测）."""
        fake_http_client.get = AsyncMock(
            return_value={
                "items": [
                    {
                        "id": "3f2e1d4a-0000-4000-8000-000000000012",
                        "project_id": str(PID),
                        "name": "清河县城坊市图",
                        "image_path": "maps/y/main.png",
                        "description": "",
                        "root_location_id": "3f2e1d4a-0000-4000-8000-000000000005",
                        "created_at": "2026-01-01T00:00:00",
                        "updated_at": "2026-01-01T00:00:00",
                    }
                ],
                "total": 1,
            }
        )
        result = cli_runner.invoke(
            app,
            ["children", "3f2e1d4a-0000-4000-8000-000000000009"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)["data"]
        assert data["total"] == 1
        assert data["items"][0]["name"] == "清河县城坊市图"
        fake_http_client.get.assert_awaited_once_with(
            "/maps/3f2e1d4a-0000-4000-8000-000000000009/children"
        )

    def test_pin_add_human_output(self, cli_runner, fake_http_client):
        """pin add 非 --json → 人类输出."""
        fake_http_client.post = AsyncMock(
            return_value={
                "id": "3f2e1d4a-0000-4000-8000-000000000011",
                "map_id": "3f2e1d4a-0000-4000-8000-000000000009",
                "location_id": None,
                "x": 42.5,
                "y": 68.0,
                "label": "清河县城",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        )
        result = cli_runner.invoke(
            app,
            [
                "pin",
                "add",
                "3f2e1d4a-0000-4000-8000-000000000009",
                "--x",
                "42.5",
                "--y",
                "68.0",
                "--label",
                "清河县城",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ pin 已添加" in result.stdout

    def test_pin_update_y_label_human_output(self, cli_runner, fake_http_client):
        """pin update --y/--label → body 含字段 + 人类输出（L437/439/451）."""
        fake_http_client.patch = AsyncMock(
            return_value={
                "id": "3f2e1d4a-0000-4000-8000-000000000011",
                "map_id": "3f2e1d4a-0000-4000-8000-000000000009",
                "location_id": None,
                "x": 42.5,
                "y": 99.0,
                "label": "新标签",
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        )
        result = cli_runner.invoke(
            app,
            [
                "pin",
                "update",
                "3f2e1d4a-0000-4000-8000-000000000011",
                "--y",
                "99.0",
                "--label",
                "新标签",
            ],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ pin 已更新" in result.stdout
        body = fake_http_client.patch.await_args.kwargs["json"]
        assert body["y"] == 99.0 and body["label"] == "新标签"

    def test_pin_delete_human_output(self, cli_runner, fake_http_client):
        """pin delete → 人类输出（L478）."""
        fake_http_client.delete = AsyncMock(return_value={})
        result = cli_runner.invoke(
            app,
            ["pin", "delete", "3f2e1d4a-0000-4000-8000-000000000011"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0
        assert "✅ pin 已删除" in result.stdout

    def test_invalid_uuid_not_found(self, cli_runner, fake_http_client):
        """_parse_uuid 非法 → NOT_FOUND 信封（L54-56）."""
        result = cli_runner.invoke(
            app, ["get", "not-a-uuid"], obj=CliContext(json_output=True)
        )
        assert result.exit_code == 1
        err = json.loads(result.stdout)["error"]
        assert err["code"] == "NOT_FOUND"
        assert err["message"] == "地图不存在"

    def test_kernel_startup_error(self, cli_runner, fake_http_client):
        """ensure_kernel 抛 KernelStartupError → KERNEL_ERROR 信封（L69）."""
        from unittest.mock import patch as _patch

        from inkflow.infrastructure.kernel import KernelStartupError

        with _patch(
            "inkflow.cli.commands.map.ensure_kernel",
            AsyncMock(side_effect=KernelStartupError("boom")),
        ):
            result = cli_runner.invoke(
                app,
                ["children", "3f2e1d4a-0000-4000-8000-000000000009"],
                obj=CliContext(json_output=True),
            )
        assert result.exit_code == 1
        err = json.loads(result.stdout)["error"]
        assert err["code"] == "KERNEL_ERROR"

    def test_list_human_output(self, cli_runner, fake_http_client):
        """list 非 --json → 覆盖 else 分支（L163）."""
        fake_http_client.get = AsyncMock(
            return_value={
                "items": [],
                "total": 0,
                "offset": 0,
                "limit": 50,
            }
        )
        result = cli_runner.invoke(
            app, ["list", "--project-id", str(PID)], obj=CliContext(json_output=False)
        )
        assert result.exit_code == 0

    def test_children_human_output(self, cli_runner, fake_http_client):
        """children 非 --json → 覆盖 else 分支（L345）."""
        fake_http_client.get = AsyncMock(return_value={"items": [], "total": 0})
        result = cli_runner.invoke(
            app,
            ["children", "3f2e1d4a-0000-4000-8000-000000000009"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0

    def test_pin_list_human_output(self, cli_runner, fake_http_client):
        """pin list 非 --json → 覆盖 else 分支（L409）."""
        fake_http_client.get = AsyncMock(return_value={"items": [], "total": 0})
        result = cli_runner.invoke(
            app,
            ["pin", "list", "3f2e1d4a-0000-4000-8000-000000000009"],
            obj=CliContext(json_output=False),
        )
        assert result.exit_code == 0

    def test_validation_error_envelope(self, cli_runner, fake_http_client):
        """pydantic ValidationError → VALIDATION_ERROR 信封（L71-72）."""
        from pydantic import ValidationError

        fake_http_client.get = AsyncMock(
            side_effect=ValidationError.from_exception_data(
                "x",
                [
                    {
                        "type": "value_error",
                        "loc": ("x",),
                        "msg": "boom",
                        "input": None,
                        "ctx": {"error": ValueError("boom")},
                    }
                ],
            )
        )
        result = cli_runner.invoke(
            app,
            ["children", "3f2e1d4a-0000-4000-8000-000000000009"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        err = json.loads(result.stdout)["error"]
        assert err["code"] == "VALIDATION_ERROR"

    def test_db_error_envelope(self, cli_runner, fake_http_client):
        """未分类异常 → DB_ERROR 信封（L75-76）."""
        fake_http_client.get = AsyncMock(side_effect=RuntimeError("boom"))
        result = cli_runner.invoke(
            app,
            ["children", "3f2e1d4a-0000-4000-8000-000000000009"],
            obj=CliContext(json_output=True),
        )
        assert result.exit_code == 1
        err = json.loads(result.stdout)["error"]
        assert err["code"] == "DB_ERROR"
